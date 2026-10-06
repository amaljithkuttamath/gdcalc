"""Compare two GROUP report revisions: envelope loads, governing cases, case list and review flags."""
import argparse
import json
import sys
from pathlib import Path

from . import engine
from .generate import case_ids


def _number(value):
    if value is None:
        return '-'
    return format(value, '.6g') if abs(value) < 1e6 else format(value, '.0f')


def _change(row):
    if row['old'] is None or row['new'] is None:
        return '-'
    if row['change_pct'] is None:
        return 'new'  # was exactly zero
    if row['change_pct'] == 0:
        return '0.0%'
    if round(row['change_pct'], 1) == 0:
        return ('+' if row['change_pct'] > 0 else '-') + '<0.1%'
    return f"{row['change_pct']:+.1f}%"


def _case(row):
    if row is None:
        return '-'
    return str(row['case']) + (' ' + row['name'] if row['name'] else '')


def _flag(row):
    where = ' '.join(x for x in (f"case {row['case']}" if row['case'] is not None else None, row['component']) if x)
    return f"{row['rule']}{' (' + where + ')' if where else ''}: {row['message']}"


def render(result):
    """Plain-text report for a compare_reports() result."""
    old, new = result['old'], result['new']
    lines = [result['headline'], '',
             f"OLD  {old['source']}  sha256 {old['sha256'][:12]}",
             f"NEW  {new['source']}  sha256 {new['sha256'][:12]}",
             f"Load basis: {result['load_source']}; units: {result['units']['force']}, {result['units']['moment']}"]
    if old['sha256'] == new['sha256']:
        lines.append('The two reports are byte-identical.')
    for label, side in (('OLD', old), ('NEW', new)):
        if side['selection_required']:
            lines.append(f"{label} case selection unresolved: {side['selection_required']}")
    lines += ['', f"{'Component':<12} {'Old':>11} {'New':>11} {'Change':>10}  Governing case (old -> new)"]
    for row in result['components']:
        governing = _case(row['governing_old']) + ' -> ' + _case(row['governing_new'])
        if row['governing_changed']:
            governing += '  [changed]'
        lines.append(f"{row['component'] + ' (' + row['unit'] + ')':<12} {_number(row['old']):>11} "
                     f"{_number(row['new']):>11} {_change(row):>10}  {governing}")
    lines.append('Component maxima may come from different piles and cases; they are not concurrent loads.')
    cases = result['cases']
    lines += ['', 'Cases (matched by ID)']
    for row in cases['added']:
        lines.append(f"  added    {row['id']} {row['name'] or ''}".rstrip())
    for row in cases['removed']:
        lines.append(f"  removed  {row['id']} {row['name'] or ''}".rstrip())
    for row in cases['renamed']:
        lines.append(f"  renamed  {row['id']} {row['old_name'] or '(no name)'} -> {row['new_name'] or '(no name)'}")
    if not (cases['added'] or cases['removed'] or cases['renamed']):
        lines.append('  no cases added, removed or renamed')
    selection = cases['selection']
    lines.append(f"  selected {','.join(map(str, selection['old'])) or 'none'} -> "
                 f"{','.join(map(str, selection['new'])) or 'none'}" + ('  [changed]' if selection['changed'] else ''))
    review = result['review']
    lines += ['', 'Review items (advisory; flags ask you to check the GROUP input)']
    if not review['checks']:
        lines.append('  no review checks enabled')
    else:
        lines += [f'  new      {_flag(f)}' for f in review['appeared']]
        lines += [f'  cleared  {_flag(f)}' for f in review['cleared']]
        lines.append(f"  {review['unchanged']} unchanged")
    for label in ('old', 'new'):
        for error in review['errors'][label]:
            lines.append(f"  {label.upper()} check error {error['id'] or ''}: {error['message']}")
    return '\n'.join(lines)


def main(argv=None, prog='mcdxkit compare'):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__ + ' Read-only; units are never converted.')
    parser.add_argument('old', type=Path, help='Earlier GROUP .gp11t/.txt report')
    parser.add_argument('new', type=Path, help='Revised GROUP .gp11t/.txt report')
    parser.add_argument('--cases', type=case_ids, help='Explicit case IDs applied to both reports; default detects STR case names')
    parser.add_argument('--load-source', choices=['effects', 'reactions'], default='effects',
                        help='Local pile effects (default) or local pile-top reactions for shear/moments, for both reports')
    parser.add_argument('--checks', default='default', metavar='SPEC',
                        help='Advisory review checks: default, none, or a comma list of ids (see mcdxkit checks list)')
    parser.add_argument('--json', action='store_true', help='Print the full comparison as JSON (schema report-compare/1)')
    args = parser.parse_args(argv)
    try:
        result = engine.compare_reports(args.old, args.new, cases=args.cases, load_source=args.load_source,
                                        checks=args.checks)
    except (ValueError, OSError) as exc:
        print('mcdxkit: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False) if args.json else render(result))
    return 0
