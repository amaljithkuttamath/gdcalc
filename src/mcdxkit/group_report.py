"""Parse GROUP's final local summary without mixing in global or detail tables."""
import math
import re

MARKER = 'SUMMARY FOR LOAD CASES AND COMBINATIONS'
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?'


def _table(block, header, minimum, maximum, columns):
    matches = list(re.finditer(header, block, re.I))
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous ' + header)
    tail = block[matches[0].end():]
    following = re.search(r'\n\s*\*\s+[A-Z]', tail)
    if following:
        tail = tail[:following.start()]
    rows, locations = [], []
    for label in [minimum, maximum]:
        found = list(re.finditer(r'^\s*' + re.escape(label) + r'\s+([^\r\n]+)', tail, re.M))
        if len(found) != 1:
            raise ValueError('Missing or duplicate ' + label + ' in ' + header)
        words = found[0].group(1).split()
        if len(words) != columns or any(not re.fullmatch(NUMBER, w) for w in words):
            raise ValueError('Malformed numeric row in ' + header)
        values = [float(w.replace('D', 'E').replace('d', 'e')) for w in words]
        if not all(math.isfinite(x) for x in values):
            raise ValueError('Non-finite numeric value in ' + header)
        rows.append(values)
        locations.append(found[0].group(0).strip())
    if any(a > b for a, b in zip(*rows)):
        raise ValueError('Minimum exceeds maximum in ' + header)
    ids = []
    for line in re.findall(r'^\s*Pile N\.\s+([^\r\n]+)', tail, re.M | re.I):
        words = line.split()
        if len(words) != columns or any(not w.isdigit() or int(w) < 1 for w in words):
            raise ValueError('Malformed local pile identifiers')
        ids.extend(map(int, words))
    return rows, ids, locations, tail


def parse(text, load_source='effects'):
    """Return case data; case names before the final summary are metadata only."""
    if load_source not in ('effects', 'reactions'):
        raise ValueError('load_source must be effects or reactions')
    if MARKER not in text:
        raise ValueError('Final GROUP summary heading was not found')
    prefix, summary = text.rsplit(MARKER, 1)
    names = {}
    for ident, label in re.findall(r'LOAD CASE\s*:\s*(\d+)\s+CASE NAME\s*:\s*([^\r\n]+)', prefix):
        ident = int(ident); label = label.strip()
        if ident in names and names[ident] != label:
            raise ValueError('Conflicting case names for case ' + str(ident))
        names[ident] = label
    if re.search(r'LOAD COMBINATION\s*:', summary, re.I):
        raise ValueError('Separate load-combination sections are not supported; provide a case summary')
    cases = []
    for block in re.split(r'LOAD CASE\s*:\s*', summary)[1:]:
        head = re.match(r'(\d+)', block)
        if head is None: raise ValueError('Malformed load case heading')
        ident = int(head.group(1))
        if any(c['id'] == ident for c in cases):
            raise ValueError('Duplicate case in final summary: ' + str(ident))
        local, ids, raw_local, local_text = _table(block, r'\* PILE TOP REACTIONS, LOCAL \*', 'MINIMUM', 'MAXIMUM', 6)
        if not re.search(r'AXIAL\s*,\s*KIP\b', local_text, re.I) or not re.search(r'KIP-IN\b', local_text, re.I):
            raise ValueError('Expected local reaction units: kip and kip-in')
        if load_source == 'effects':
            effects, effect_ids, raw_effects, effect_text = _table(block, r'\* EFFECTS FOR LATERALLY LOADED PILE \*', 'Min.', 'Max.', 9)
            if not re.search(r'KIP-IN\s+KIP-IN\s+KIP\s+KIP\b', effect_text, re.I):
                raise ValueError('Expected pile-effect units: kip-in and kip')
            directions = re.search(r'y-DIR\s+z-DIR\s+z-DIR\s+y-DIR\s+y-DIR\s+z-DIR', effect_text, re.I)
            if directions is None: raise ValueError('Unrecognized local pile-effect column directions')
            pairs = {key: [row[col] for row in effects] for key, col in [('Vy',4),('Vz',5),('My',3),('Mz',2)]}
            ids += effect_ids
        else:
            raw_effects = []
            pairs = {key: [row[col] for row in local] for key, col in [('Vy',1),('Vz',2),('My',4),('Mz',5)]}
        pairs['P'] = [row[0] for row in local]
        cases.append({'id':ident, 'name':names.get(ident), 'pairs':pairs, 'pile_ids':sorted(set(ids)),
                      'load_source':load_source, 'source_rows':{'local':raw_local,'effects':raw_effects}})
    if not cases: raise ValueError('No load cases in final summary')
    return {'cases':cases,'load_source':load_source}


def select(parsed, cases=None):
    available = {c['id']:c for c in parsed['cases']}
    if cases is None:
        if any(c['name'] is None or not re.match(r'^(STR|SER)(?:\b|[-_])', c['name'], re.I) for c in available.values()):
            raise ValueError('Case classification unavailable; specify --cases explicitly')
        cases = [c['id'] for c in available.values() if c['name'].upper().startswith('STR')]
    if not cases or len(cases) != len(set(cases)) or any(i not in available for i in cases):
        raise ValueError('Select nonempty, unique, existing --cases')
    selected = [available[i] for i in cases]
    if any(max(c['pairs']['P']) <= 0 or min(c['pairs']['P']) < 0 for c in selected):
        raise ValueError('Selected cases contain tension or no compression; this compression template needs engineering review')
    return selected


def envelope(cases):
    return {key:max(max(c['pairs'][key]) if key=='P' else max(map(abs,c['pairs'][key])) for c in cases)
            for key in ['P','Vy','Vz','My','Mz']}
