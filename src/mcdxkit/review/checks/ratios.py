"""Robust ratio statistics within one report (no history).

A consistent pile-group model keeps lever arms (M/V) and along-pile/top ratios near-constant
across cases, while one wrong cell moves them. Each ratio is scored with the Iglewicz-Hoaglin
modified z-score of its log10 across the report's cases.
"""
import math
from statistics import median
from typing import Any, Dict, Iterator, List, Sequence, Tuple

from ..api import COMPONENTS, CaseView, Context, Flag, Impact, NotApplicable, ReportView, frozen_mapping
from ._shared import MIN_CASES, NEGLIGIBLE, governs, magnitude, positive_median, relative

# Modified z-score threshold: the 97.5th percentile of the per-report maximum on 300 clean
# reports of the harder synthetic corpus (57% harmful recall at 3.5% false alarms there,
# against 60% at 7.0% for the 95th percentile 4.64). Recalibrate on real reports.
Z_THRESHOLD = 5.63
# Floor on the MAD of log10 ratios (about 5%); keeps the threshold portable between corpora.
MAD_FLOOR = 0.02
# (feature, numerator, denominator); 'top:' and 'eff:' name the table and component.
FEATURES = (
    ('lever arm Mz/Vy', 'top:Mz', 'top:Vy'),
    ('lever arm My/Vz', 'top:My', 'top:Vz'),
    ('along-pile/top Mz', 'eff:Mz', 'top:Mz'),
    ('along-pile/top My', 'eff:My', 'top:My'),
    ('along-pile/top Vy', 'eff:Vy', 'top:Vy'),
    ('along-pile/top Vz', 'eff:Vz', 'top:Vz'),
)


def _quantity(case: CaseView, reference: str) -> float:
    table, component = reference.split(':')
    values = case.pile_top if table == 'top' else case.along_pile
    if values is None:
        raise NotApplicable('needs the along-pile effects table')
    return magnitude(values[component])


def robust_z(values: Sequence[float], floor: float = MAD_FLOOR) -> Tuple[float, List[float]]:
    """Iglewicz-Hoaglin modified z-scores, 0.6745 (x - median) / MAD, with a floored MAD."""
    centre = median(values)
    spread = max(median(abs(v - centre) for v in values), floor)
    return centre, [0.6745 * (v - centre) / spread for v in values]


class RatioOutlier:
    """One flag per case: the ratio with the largest |z| when it exceeds the threshold."""
    kind = 'check'
    id = 'ratio_outlier'
    version = '2'
    title = 'Unusual ratio'
    params = frozen_mapping({'z_threshold': Z_THRESHOLD, 'mad_floor': MAD_FLOOR, 'negligible': NEGLIGIBLE,
                             'min_cases': MIN_CASES})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Flag]:
        cases = view.cases
        if len(cases) < MIN_CASES:
            raise NotApplicable(f'needs at least {MIN_CASES} cases; the report has {len(cases)}')
        features = FEATURES if view.load_source == 'effects' else FEATURES[:2]
        scale = {denominator: positive_median([_quantity(c, denominator) for c in cases])
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
            centre, scores = robust_z([value for _, value in logs])
            for (case, value), score in zip(logs, scores, strict=True):
                if abs(score) > Z_THRESHOLD and abs(score) > abs(worst.get(case.id, {}).get('z', 0)):
                    worst[case.id] = {'case': case, 'feature': feature, 'ratio': 10 ** value,
                                      'components': tuple(r.split(':')[1] for r in (numerator, denominator)),
                                      'median_ratio': 10 ** centre, 'z': score}
        for case_id in sorted(worst):
            found = worst[case_id]
            yield Flag(
                self.id, case_id, found['feature'],
                f'{found["case"].label}: {found["feature"]} is {found["ratio"]:.4g} against a report median of '
                f'{found["median_ratio"]:.4g} (robust z {found["z"]:.1f}). Check this case for a single wrong value.',
                value=found['ratio'], compared_to=found['median_ratio'],
                unit='in' if found['feature'].startswith('lever arm') else None,
                evidence=(('ratio', found['ratio']), ('median_ratio', found['median_ratio']),
                          ('z', round(found['z'], 2)), ('threshold', Z_THRESHOLD)),
                impact=self._impact(view, found))

    @staticmethod
    def _impact(view, found):
        # One wrong value in a selected case changes the envelope if that case sets the peak, or if
        # the value is too small and the corrected value could set it.
        case = found['case']
        components = tuple(c for c in found['components'] if c in COMPONENTS)
        led = set(governs(view, case)) & set(components)
        if case.id not in view.selected or not (led or found['ratio'] < found['median_ratio']):
            return Impact()
        return Impact(envelope=True, magnitude=relative(found['ratio'], found['median_ratio']),
                      components=tuple(c for c in components if c in led) or components)
