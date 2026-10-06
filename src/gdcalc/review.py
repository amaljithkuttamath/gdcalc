"""Phase 1 review flags: advisory, rules-first checks of a parsed GROUP final summary.

The checks read only the final local summary that the conversion already uses. They
never change inputs, case selection, worksheets or results, and they are not a pass
or fail verdict: a flag asks the engineer to look at the GROUP input again.

Rules (each one a physical or labelling invariant, with only a 1% rounding tolerance):

* ``service_exceeds_strength``: a SER case exceeds every STR case in a component.
* ``effects_below_top``: the largest magnitude along the pile is smaller than the
  pile-top reaction for the same quantity. Effects load source only.
* ``duplicate_case``: two cases have identical numeric tables.

Statistics (robust, within one report, no history):

* ``ratio_outlier``: Iglewicz-Hoaglin modified z-score of log10 lever arms (M/V) and
  along-pile/top ratios across the report's cases.
* ``unit_slip``: a component peak about 1000x away from the report's median, the
  signature of a possible lb/kip slip.

Parameters come from the planted-error validation described in docs/machine-learning.md.
"""
import math
import re
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

METHOD = 'rules+robust-ratio-z'
VERSION = 1

# Relative rounding tolerance for the invariant rules (GROUP prints 5 significant digits).
TOLERANCE = 0.01
# Modified z-score threshold: 95th percentile of the per-report maximum on clean synthetic
# reports (5% report-level false positives). Recalibrate on real clean reports.
Z_THRESHOLD = 4.35
# Floor on the MAD of log10 ratios, so near-constant ratios do not explode on rounding.
MAD_FLOOR = 1e-3
# Smallest report in the validation set: three gravity combinations plus three wind cases.
MIN_CASES = 6
# A ratio needs defined values in at least three cases; with fewer, the median/MAD z-score
# cannot exceed 0.6745 and the check would only look like it ran.
MIN_FEATURE_VALUES = 3
# A ratio is undefined when its denominator is below this share of the report's median scale.
NEGLIGIBLE = 0.01
# unit_slip: departures within half a decade of 1000x (at least 10**2.5, about 316x).
UNIT_SLIP_DECADES = 2.5

COMPONENTS = ('P', 'Vy', 'Vz', 'My', 'Mz')
# (component, pile-top reaction column, along-pile effects column) for the same quantity.
EFFECT_PAIRS = (('Vy', 1, 4), ('Vz', 2, 5), ('My', 4, 3), ('Mz', 5, 2))
LOCAL_COLUMNS = {'Vy': 1, 'Vz': 2, 'My': 4, 'Mz': 5}
# (feature, numerator, denominator); 'top:' and 'eff:' name the table and component.
RATIO_FEATURES = (
    ('lever arm Mz/Vy', 'top:Mz', 'top:Vy'),
    ('lever arm My/Vz', 'top:My', 'top:Vz'),
    ('along-pile/top Mz', 'eff:Mz', 'top:Mz'),
    ('along-pile/top My', 'eff:My', 'top:My'),
    ('along-pile/top Vy', 'eff:Vy', 'top:Vy'),
    ('along-pile/top Vz', 'eff:Vz', 'top:Vz'),
)
EFFECT_COLUMNS = {name: column for name, _, column in EFFECT_PAIRS}

Case = Dict[str, Any]
Flag = Dict[str, Any]


def _magnitude(rows: Sequence[Sequence[float]], column: int) -> float:
    """Largest absolute value of a [minimum, maximum] column; sign conventions do not matter."""
    return max(abs(rows[0][column]), abs(rows[1][column]))


def _peak(case: Case, component: str) -> float:
    """Envelope peak as gdcalc uses it: maximum axial compression, otherwise largest magnitude."""
    values = case['pairs'][component]
    return max(values) if component == 'P' else max(map(abs, values))


def _label(case: Case) -> str:
    return 'Case ' + str(case['id']) + (' ' + case['name'] if case['name'] else '')


def _limit_state(case: Case) -> Optional[str]:
    match = re.match(r'^(STR|SER)(?:\b|[-_])', case['name'] or '', re.I)
    return match.group(1).upper() if match else None


def _flag(rule: str, case: Optional[int], component: Optional[str], detail: str, values: Dict[str, Any]) -> Flag:
    return {'rule': rule, 'case': case, 'component': component, 'detail': detail, 'values': values}


def service_exceeds_strength(cases: List[Case]) -> List[Flag]:
    strength = [c for c in cases if _limit_state(c) == 'STR']
    service = [c for c in cases if _limit_state(c) == 'SER']
    flags = []
    for component in COMPONENTS:
        governing = max(strength, key=lambda c: _peak(c, component))
        limit = _peak(governing, component)
        for case in service:
            value = _peak(case, component)
            if value > 0 and value > limit * (1 + TOLERANCE):
                flags.append(_flag(
                    'service_exceeds_strength', case['id'], component,
                    f'{_label(case)} {component} {value:.4g} exceeds every STR case '
                    f'(largest {limit:.4g}, case {governing["id"]}). Check the case name and load factors.',
                    {'service': value, 'strength_max': limit, 'strength_case': governing['id']}))
    return sorted(flags, key=lambda f: f['case'])


def effects_below_top(cases: List[Case]) -> List[Flag]:
    flags = []
    for case in cases:
        local, effects = case['tables']['local'], case['tables']['effects']
        for component, top_column, effect_column in EFFECT_PAIRS:
            top = _magnitude(local, top_column)
            along = _magnitude(effects, effect_column)
            if top > 0 and along < top * (1 - TOLERANCE):
                flags.append(_flag(
                    'effects_below_top', case['id'], component,
                    f'{_label(case)} {component}: largest along-pile magnitude {along:.4g} is below the '
                    f'pile-top reaction {top:.4g}. Check that the effects table belongs to this case.',
                    {'along_pile': along, 'pile_top': top}))
    return flags


def duplicate_case(cases: List[Case]) -> List[Flag]:
    flags = []
    seen: Dict[Tuple[Any, ...], Case] = {}
    for case in cases:
        tables = case['tables']
        key = tuple(tuple(row) for row in tables['local']) + tuple(tuple(row) for row in tables['effects'] or ())
        first = seen.setdefault(key, case)
        if first is not case:
            flags.append(_flag(
                'duplicate_case', case['id'], None,
                f'{_label(case)} has tables identical to {_label(first)}. Check for a copied case.',
                {'duplicate_of': first['id']}))
    return flags


def _quantity(case: Case, reference: str) -> float:
    table, component = reference.split(':')
    if table == 'top':
        return _magnitude(case['tables']['local'], LOCAL_COLUMNS[component])
    return _magnitude(case['tables']['effects'], EFFECT_COLUMNS[component])


def _robust_z(values: Sequence[float]) -> Tuple[float, List[float]]:
    """Iglewicz-Hoaglin modified z-scores, 0.6745 (x - median) / MAD, with a floored MAD."""
    centre = median(values)
    spread = max(median(abs(v - centre) for v in values), MAD_FLOOR)
    return centre, [0.6745 * (v - centre) / spread for v in values]


def ratio_outlier(cases: List[Case], features: Sequence[Tuple[str, str, str]]) -> List[Flag]:
    """One flag per case: the feature with the largest |z| when it exceeds Z_THRESHOLD."""
    scale = {}
    for _, _, denominator in features:
        sizes = [_quantity(c, denominator) for c in cases]
        sizes = [s for s in sizes if s > 0]
        scale[denominator] = median(sizes) if sizes else 0.0
    worst: Dict[int, Dict[str, Any]] = {}
    for feature, numerator, denominator in features:
        logs = []
        for case in cases:
            top, bottom = _quantity(case, numerator), _quantity(case, denominator)
            if top > 0 and bottom > NEGLIGIBLE * scale[denominator]:
                logs.append((case, math.log10(top / bottom)))
        if len(logs) < MIN_FEATURE_VALUES:
            continue
        centre, scores = _robust_z([value for _, value in logs])
        for (case, value), score in zip(logs, scores, strict=True):
            if abs(score) > Z_THRESHOLD and abs(score) > abs(worst.get(case['id'], {}).get('z', 0)):
                worst[case['id']] = {'case': case, 'feature': feature, 'ratio': 10 ** value,
                                     'median_ratio': 10 ** centre, 'z': score}
    flags = []
    for case_id in sorted(worst):
        found = worst[case_id]
        flags.append(_flag(
            'ratio_outlier', case_id, found['feature'],
            f'{_label(found["case"])}: {found["feature"]} is {found["ratio"]:.4g} against a report median of '
            f'{found["median_ratio"]:.4g} (robust z {found["z"]:.1f}). Check this case for a single wrong value.',
            {'ratio': found['ratio'], 'median_ratio': found['median_ratio'], 'z': round(found['z'], 2),
             'threshold': Z_THRESHOLD}))
    return flags


def unit_slip(cases: List[Case]) -> List[Flag]:
    flags = []
    for component in COMPONENTS:
        logs = [(c, math.log10(_peak(c, component))) for c in cases if _peak(c, component) > 0]
        if len(logs) < MIN_CASES:
            continue
        centre = median(value for _, value in logs)
        for case, value in logs:
            if abs(value - centre) >= UNIT_SLIP_DECADES:
                factor = 10 ** (value - centre)
                flags.append(_flag(
                    'unit_slip', case['id'], component,
                    f'{_label(case)} {component} {10 ** value:.4g} is {factor:.3g}x the report median '
                    f'{10 ** centre:.4g}: possible unit slip (lb vs kip).',
                    {'peak': 10 ** value, 'median': 10 ** centre, 'factor': factor}))
    return flags


def review(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Return advisory review flags for a group_report.parse result.

    Checks that cannot run on this report are listed under ``skipped`` with the reason;
    they are not reported as clean.
    """
    cases = parsed['cases']
    effects = parsed['load_source'] == 'effects'
    named = {_limit_state(c) for c in cases}
    plan: List[Tuple[str, Optional[str], Callable[[], List[Flag]]]] = [
        ('service_exceeds_strength',
         None if {'STR', 'SER'} <= named else 'needs both STR and SER case names',
         lambda: service_exceeds_strength(cases)),
        ('effects_below_top',
         None if effects else 'needs the effects load source',
         lambda: effects_below_top(cases)),
        ('duplicate_case', None, lambda: duplicate_case(cases)),
        ('ratio_outlier',
         None if len(cases) >= MIN_CASES else f'needs at least {MIN_CASES} cases; the report has {len(cases)}',
         lambda: ratio_outlier(cases, RATIO_FEATURES if effects else RATIO_FEATURES[:2])),
        ('unit_slip',
         None if len(cases) >= MIN_CASES else f'needs at least {MIN_CASES} cases; the report has {len(cases)}',
         lambda: unit_slip(cases)),
    ]
    flags: List[Flag] = []
    checks, skipped = [], []
    for rule, reason, run in plan:
        if reason:
            skipped.append({'rule': rule, 'reason': reason})
            continue
        checks.append(rule)
        flags.extend(run())
    return {'advisory': True, 'method': METHOD, 'version': VERSION, 'load_source': parsed['load_source'],
            'checks': checks, 'skipped': skipped, 'flags': flags}
