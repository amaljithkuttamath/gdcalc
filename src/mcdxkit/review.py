"""Phase 1 review flags: advisory, rules-first checks of a parsed GROUP final summary.

The checks read only the final local summary that the conversion already uses. They
never change inputs, case selection, worksheets or results, and they are not a pass
or fail verdict: a flag asks the engineer to look at the GROUP input again.

Rules (each one a physical or labelling invariant, with only a 1% rounding tolerance):

* ``service_exceeds_strength``: a SER case's axial load exceeds every STR case.
* ``effects_below_top``: the largest magnitude along the pile is smaller than the
  pile-top reaction for the same quantity. Effects load source only.
* ``duplicate_case``: two cases have identical numeric tables.

Statistics (robust, within one report, no history):

* ``ratio_outlier``: Iglewicz-Hoaglin modified z-score of log10 lever arms (M/V) and
  along-pile/top ratios across the report's cases.
* ``gross_magnitude``: maximum axial load or lateral resultant about an order of magnitude
  or more from the report's median, the signature of a possible unit slip.

Case dominance lists strength cases that cannot govern any envelope component.

Parameters come from the planted-error validation described in docs/machine-learning.md.
"""
import math
import re
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .group_report import COMPONENTS, limit_state, peak

METHOD = 'rules+robust-ratio-z+gross-magnitude'
VERSION = 2

# Relative rounding tolerance for the invariant rules.
TOLERANCE = 0.01
# Modified z-score threshold: 95th percentile of the per-report maximum on 300 clean reports
# of the harder synthetic corpus (5% report-level false positives). Recalibrate on real reports.
Z_THRESHOLD = 4.64
# Floor on the MAD of log10 ratios (about 5%); keeps the threshold portable between corpora.
MAD_FLOOR = 0.02
# A ratio needs defined values in at least three cases; with fewer, the median/MAD z-score
# cannot exceed 0.6745, so the check could not flag anything.
MIN_CASES = 3
# A quantity is negligible below this share of the report's median for that quantity:
# ratios with a negligible denominator are undefined, negligible peaks are not compared.
NEGLIGIBLE = 0.01
# gross_magnitude: |log10(x / report median)| above this many decades (97.5th percentile on
# clean reports of the harder synthetic corpus).
GROSS_DECADES = 0.95
# Names treated as extreme events by the review-only fallback basis for case dominance.
EXTREME_EVENT = re.compile(r'^\s*(ext|extreme|eq|seis)', re.I)

# (component, pile-top reaction column, along-pile effects column) for the same quantity.
EFFECT_PAIRS = (('Vy', 1, 4), ('Vz', 2, 5), ('My', 4, 3), ('Mz', 5, 2))
LOCAL_COLUMNS = {'Vy': 1, 'Vz': 2, 'My': 4, 'Mz': 5}
EFFECT_COLUMNS = {name: column for name, _, column in EFFECT_PAIRS}
# (feature, numerator, denominator); 'top:' and 'eff:' name the table and component.
RATIO_FEATURES = (
    ('lever arm Mz/Vy', 'top:Mz', 'top:Vy'),
    ('lever arm My/Vz', 'top:My', 'top:Vz'),
    ('along-pile/top Mz', 'eff:Mz', 'top:Mz'),
    ('along-pile/top My', 'eff:My', 'top:My'),
    ('along-pile/top Vy', 'eff:Vy', 'top:Vy'),
    ('along-pile/top Vz', 'eff:Vz', 'top:Vz'),
)

Case = Dict[str, Any]
Flag = Dict[str, Any]


def _magnitude(rows: Sequence[Sequence[float]], column: int) -> float:
    """Largest absolute value of a [minimum, maximum] column; sign conventions do not matter."""
    return max(abs(rows[0][column]), abs(rows[1][column]))


def _label(case: Case) -> str:
    return 'Case ' + str(case['id']) + (' ' + case['name'] if case['name'] else '')


def _limit_state(case: Case) -> Optional[str]:
    return limit_state(case['name'], long_names=True)


def _flag(rule: str, case: Optional[int], component: Optional[str], detail: str, values: Dict[str, Any]) -> Flag:
    return {'rule': rule, 'case': case, 'component': component, 'detail': detail, 'values': values}


def _positive_median(values: Sequence[float]) -> float:
    positive = [v for v in values if v > 0]
    return median(positive) if positive else 0.0


def service_exceeds_strength(cases: List[Case]) -> List[Flag]:
    """Axial load only: service lateral loads legitimately exceed strength (e.g. 1.2 TU vs 0.5 TU)."""
    strength = [c for c in cases if _limit_state(c) == 'STR']
    service = [c for c in cases if _limit_state(c) == 'SER']
    governing = max(strength, key=lambda c: peak(c, 'P'))
    limit = peak(governing, 'P')
    if limit <= NEGLIGIBLE * _positive_median([peak(c, 'P') for c in cases]):
        return []  # no strength compression to compare against
    flags = []
    for case in service:
        value = peak(case, 'P')
        if value > limit * (1 + TOLERANCE):
            flags.append(_flag(
                'service_exceeds_strength', case['id'], 'P',
                f'{_label(case)} axial load {value:.4g} exceeds every STR case '
                f'(largest {limit:.4g}, case {governing["id"]}). Check the case name and load factors.',
                {'service': value, 'strength_max': limit, 'strength_case': governing['id']}))
    return flags


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
    scale = {denominator: _positive_median([_quantity(c, denominator) for c in cases])
             for _, _, denominator in features}
    worst: Dict[int, Dict[str, Any]] = {}
    for feature, numerator, denominator in features:
        logs = []
        for case in cases:
            top, bottom = _quantity(case, numerator), _quantity(case, denominator)
            if top > 0 and bottom > NEGLIGIBLE * scale[denominator]:
                logs.append((case, math.log10(top / bottom)))
        if len(logs) < MIN_CASES:
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


def _lateral_resultant(case: Case) -> float:
    local = case['tables']['local']
    return math.hypot(_magnitude(local, 1), _magnitude(local, 2))


def gross_magnitude(cases: List[Case]) -> List[Flag]:
    """Maximum axial load and pile-top lateral resultant against the report's median."""
    quantities = (('P', 'maximum axial load', lambda c: peak(c, 'P')),
                  ('V', 'lateral resultant', _lateral_resultant))
    flags = []
    for component, label, get in quantities:
        values = [(c, get(c)) for c in cases]
        centre = _positive_median([v for _, v in values])
        # Negligible values (a gravity case's 0.02 kip shear beside 15 kip wind cases) are not compared.
        logs = [(c, math.log10(v)) for c, v in values if v > NEGLIGIBLE * centre and v > 0]
        if len(logs) < MIN_CASES:
            continue
        middle = median(value for _, value in logs)
        for case, value in logs:
            if abs(value - middle) > GROSS_DECADES:
                factor = 10 ** (value - middle)
                flags.append(_flag(
                    'gross_magnitude', case['id'], component,
                    f'{_label(case)} {label} {10 ** value:.4g} is {factor:.3g}x the report median '
                    f'{10 ** middle:.4g}: possible unit slip. Check the units of this case.',
                    {'value': 10 ** value, 'median': 10 ** middle, 'factor': factor, 'threshold_decades': GROSS_DECADES}))
    return flags


def dominance(cases: List[Case], selected: Optional[Sequence[int]]) -> Dict[str, Any]:
    """Cases that cannot govern: another considered case is at least as large in every component.

    With no selection, the review considers all cases except extreme-event names. That basis is
    for this advisory hint only; it is never applied as a case selection.
    """
    if selected:
        basis, note = 'selected', 'Selected cases.'
        considered = [c for c in cases if c['id'] in set(selected)]
    else:
        basis = 'fallback_non_extreme'
        note = ('No case selection: review-only fallback of all cases except extreme-event names. '
                'This is not a case selection.')
        considered = [c for c in cases if not EXTREME_EVENT.match(c['name'] or '')]
    peaks = {c['id']: [peak(c, key) for key in COMPONENTS] for c in considered}
    dominated = []
    for case in considered:
        mine = peaks[case['id']]
        by = [other['id'] for other in considered
              if peaks[other['id']] != mine and all(o >= m for o, m in zip(peaks[other['id']], mine, strict=True))]
        if by:
            dominated.append({'case': case['id'], 'dominated_by': by})
    return {'basis': basis, 'note': note, 'cases': [c['id'] for c in considered], 'dominated': dominated}


def review(parsed: Dict[str, Any], selected: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """Return advisory review flags for a group_report.parse result.

    ``selected`` is the case selection in use, if any; it only sets the dominance basis.
    Checks that cannot run on this report are listed under ``skipped`` with the reason;
    they are not reported as clean.
    """
    cases = parsed['cases']
    effects = parsed['load_source'] == 'effects'
    named = {_limit_state(c) for c in cases}
    few = None if len(cases) >= MIN_CASES else f'needs at least {MIN_CASES} cases; the report has {len(cases)}'
    plan: List[Tuple[str, Optional[str], Callable[[], List[Flag]]]] = [
        ('service_exceeds_strength',
         None if {'STR', 'SER'} <= named else 'needs both strength and service case names',
         lambda: service_exceeds_strength(cases)),
        ('effects_below_top',
         None if effects else 'needs the effects load source',
         lambda: effects_below_top(cases)),
        ('duplicate_case', None, lambda: duplicate_case(cases)),
        ('ratio_outlier', few, lambda: ratio_outlier(cases, RATIO_FEATURES if effects else RATIO_FEATURES[:2])),
        ('gross_magnitude', few, lambda: gross_magnitude(cases)),
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
            'checks': checks, 'skipped': skipped, 'flags': flags, 'dominance': dominance(cases, selected)}
