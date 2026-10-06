"""Gross magnitude: a value about an order of magnitude or more from the report's median."""
import math
from statistics import median
from typing import Iterator

from ..api import CaseView, Context, Flag, Impact, NotApplicable, ReportView, frozen_mapping
from ._shared import MIN_CASES, NEGLIGIBLE, magnitude, positive_median, relative

# |log10(x / report median)| above this many decades (97.5th percentile on clean reports of
# the harder synthetic corpus).
GROSS_DECADES = 0.95


def _lateral_resultant(case: CaseView) -> float:
    return math.hypot(magnitude(case.pile_top['Vy']), magnitude(case.pile_top['Vz']))


class GrossMagnitude:
    """Maximum axial load and pile-top lateral resultant against the report's median.

    The wording is only "possible unit slip": a kip-ft hint was wrong for every moment-unit
    slip in the validation, so no specific unit is suggested.
    """
    kind = 'check'
    id = 'gross_magnitude'
    version = '2'
    title = 'Possible unit slip'
    params = frozen_mapping({'threshold_decades': GROSS_DECADES, 'negligible': NEGLIGIBLE, 'min_cases': MIN_CASES})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Flag]:
        cases = view.cases
        if len(cases) < MIN_CASES:
            raise NotApplicable(f'needs at least {MIN_CASES} cases; the report has {len(cases)}')
        quantities = (('P', 'maximum axial load', lambda c: c.peak('P')),
                      ('V', 'lateral resultant', _lateral_resultant))
        for component, label, get in quantities:
            values = [(c, get(c)) for c in cases]
            centre = positive_median([v for _, v in values])
            # Negligible values (a gravity case's 0.02 kip shear beside 15 kip wind cases) are not compared.
            logs = [(c, math.log10(v)) for c, v in values if v > NEGLIGIBLE * centre and v > 0]
            if len(logs) < MIN_CASES:
                continue
            middle = median(value for _, value in logs)
            for case, value in logs:
                if abs(value - middle) > GROSS_DECADES:
                    factor = 10 ** (value - middle)
                    yield Flag(
                        self.id, case.id, component,
                        f'{case.label} {label} {10 ** value:.4g} is {factor:.3g}x the report median '
                        f'{10 ** middle:.4g}: possible unit slip. Check the units of this case.',
                        value=10 ** value, compared_to=10 ** middle, unit=view.units[component],
                        evidence=(('value', 10 ** value), ('median', 10 ** middle), ('factor', factor),
                                  ('threshold_decades', GROSS_DECADES)),
                        # A unit slip in a selected case scales its values in the envelope.
                        impact=Impact(envelope=case.id in view.selected,
                                      magnitude=relative(factor, 1.0) if case.id in view.selected else 0.0,
                                      components=(('P',) if component == 'P' else ('Vy', 'Vz'))
                                      if case.id in view.selected else ()))
