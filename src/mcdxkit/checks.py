"""Read check outcomes from a CalcpadCE calculated HTML snapshot.

CalcpadCE evaluates a comparison (<, ≤, >, ≥, ≡, ≠, chains joined by "and") to
1 or 0 and renders it as ``name = symbolic = substituted = result``. Only those
rendered comparisons are reported. Nothing is recalculated here: the outcome is
the 1/0 CalcpadCE printed, and a demand/capacity ratio is derived only when
both substituted operands are single positive numbers with identical units.
Hidden conditionals and string messages (for example "OK"/"NG") are not
interpreted; a worksheet without rendered comparisons reports no checks found.
"""
import bisect
import math
import re
from lxml import html as H

NO_CHECKS = 'no checks found'
COMPARISONS = ('≤', '≥', '<', '>', '≡', '≠')
# A single value with an optional unit made only of unit names, '·', '/' and powers.
UNIT = r'[A-Za-zμ°]+(?:\^\(?[-−]?\d+\)?)?(?:\s*[·/]\s*[A-Za-zμ°]+(?:\^\(?[-−]?\d+\)?)?)*'
NUMBER = re.compile(r'^([-−]?\d+(?:\.\d+)?)(?:×10\^\(?([-−]?\d+)\)?)?(?:\s+(' + UNIT + r'))?$')


def _classes(node):
    return (node.get('class') or '').split()


def _flatten(node):
    """Readable linear text; division blocks become (numerator)/(denominator)."""
    if 'dvc' in _classes(node):
        parts, current = [], [node.text or '']
        for child in node:
            if 'dvl' in _classes(child):
                parts.append(''.join(current)); current = []
            else:
                current.append(_flatten(child))
            current.append(child.tail or '')
        parts.append(''.join(current))
        return '/'.join('(' + ' '.join(p.split()) + ')' for p in parts)
    text = node.text or ''
    if node.tag == 'sup':
        text = '^(' + text + ''.join(_flatten(c) + (c.tail or '') for c in node) + ')'
        return text
    return text + ''.join(_flatten(c) + (c.tail or '') for c in node)


def _top_level(text, words):
    """Comparison operators outside parentheses."""
    depth, found = 0, []
    for index, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and char in words:
            found.append((index, char))
    return found


def _quantity(text):
    match = NUMBER.match(text.strip())
    if not match:
        return None
    # float() of the decimal form saturates to inf instead of raising on huge exponents.
    exponent = match.group(2).replace('−', '-') if match.group(2) else '0'
    value = float(match.group(1).replace('−', '-') + 'e' + exponent)
    if not math.isfinite(value):
        return None
    return value, (match.group(3) or '').strip()


def _ratio(substituted):
    """Demand/capacity only for a single comparison between two plain quantities."""
    if ' and ' in substituted:
        return None
    operators = _top_level(substituted, COMPARISONS)
    if len(operators) != 1 or operators[0][1] not in ('≤', '<', '≥', '>'):
        return None
    index, operator = operators[0]
    left, right = _quantity(substituted[:index]), _quantity(substituted[index + 1:])
    if left is None or right is None or left[1] != right[1]:
        return None
    demand, capacity = (left, right) if operator in ('≤', '<') else (right, left)
    if capacity[0] <= 0 or demand[0] < 0:
        return None
    ratio = demand[0] / capacity[0]
    if not math.isfinite(ratio):
        return None
    return {'ratio': ratio, 'demand': demand[0], 'capacity': capacity[0], 'unit': capacity[1]}


def extract(document, region_lines=None):
    """Return (checks, summary) for a calculated HTML document string."""
    root = H.document_fromstring(document)
    starts = sorted((line, region) for region, line in (region_lines or {}).items()
                    if type(line) is int)
    start_lines = [line for line, _ in starts]
    checks, label = [], None
    for paragraph in root.iter('p', 'h1', 'h2'):
        equations = [n for n in paragraph if n.tag == 'span' and 'eq' in _classes(n)]
        if not equations:
            label = ' '.join(paragraph.text_content().split()) or None
            continue
        line = None
        match = re.fullmatch(r'line-(\d+)', paragraph.get('id') or '')
        if match:
            line = int(match.group(1))
        # The region is the last one whose first source line precedes this page line.
        position = bisect.bisect_right(start_lines, line) if line is not None else 0
        region = starts[position - 1][1] if position else None
        for equation in equations:
            segments = [' '.join(s.split()) for s in _flatten(equation).split(' = ')]
            if len(segments) < 2 or segments[-1] not in ('0', '1'):
                continue
            body = segments[:-1]
            comparisons = [s for s in body if _top_level(s, COMPARISONS)]
            if not comparisons:
                continue
            defined = not _top_level(body[0], COMPARISONS)
            name = body[0] if defined else (label or 'Expression')
            item = {'name': name, 'expression': comparisons[0], 'substituted': comparisons[-1],
                    'result': int(segments[-1]), 'passed': segments[-1] == '1',
                    'ratio': None, 'demand': None, 'capacity': None, 'unit': None,
                    'region_id': region, 'line': line}
            item.update(_ratio(comparisons[-1]) or {})
            checks.append(item)
    return checks, summarize(checks)


def summarize(checks):
    rated = [c for c in checks if c.get('ratio') is not None]
    governing = max(rated, key=lambda c: c['ratio'], default=None)
    failed = [c['name'] for c in checks if not c['passed']]
    return {'status': 'failures' if failed else 'passed' if checks else NO_CHECKS,
            'total': len(checks), 'passed': len(checks) - len(failed), 'failed': len(failed),
            'failed_checks': failed,
            'governing': None if governing is None else
            {k: governing[k] for k in ('name', 'ratio', 'passed', 'region_id')}}


def valid_summary(summary):
    """True only for a summary in the shape `summarize` writes; anything else is unrecorded."""
    if not isinstance(summary, dict) or summary.get('status') not in ('passed', 'failures', NO_CHECKS):
        return False
    counts = [summary.get(k) for k in ('total', 'passed', 'failed')]
    if any(type(n) is not int or n < 0 for n in counts) or counts[0] != counts[1] + counts[2]:
        return False
    failed = summary.get('failed_checks')
    if not isinstance(failed, list) or len(failed) != counts[2] or not all(isinstance(n, str) for n in failed):
        return False
    governing = summary.get('governing')
    if governing is None:
        return True
    ratio = governing.get('ratio') if isinstance(governing, dict) else None
    return (isinstance(governing, dict) and isinstance(governing.get('name'), str)
            and type(ratio) in (int, float) and math.isfinite(ratio) and ratio >= 0)
