"""Case annotations: the governing case of each envelope component, and dominated cases."""
import re
from typing import Iterator

from ..api import COMPONENTS, Annotation, Context, ReportView, frozen_mapping

# Names treated as extreme events by the review-only fallback basis for case dominance.
EXTREME_EVENT = re.compile(r'^\s*(ext|extreme|eq|seis)', re.I)


class GoverningCases:
    """For each component of the selected envelope: the case behind the peak and its lead over the runner-up."""
    kind = 'annotator'
    id = 'governing'
    version = '1'
    title = 'Governing cases'
    params = frozen_mapping({})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Annotation]:
        cases = [c for c in view.cases if c.id in view.selected]
        if not cases:
            return
        for key in COMPONENTS:
            peaks = sorted(((c.peak(key), c) for c in cases), key=lambda pair: (-pair[0], pair[1].id))
            value, case = peaks[0]
            runner = peaks[1] if len(peaks) > 1 else None
            yield Annotation(self.id, 'governing', case.id, key, frozen_mapping({
                'value': value, 'case': case.id, 'case_name': case.name,
                'runner_up_case': runner[1].id if runner else None,
                'lead_ratio': value / runner[0] if runner and runner[0] > 0 else None}))


class Dominance:
    """Cases that cannot govern: another considered case is at least as large in every component.

    With no selection, the review considers all cases except extreme-event names. That basis is
    for this advisory hint only; it is never applied as a case selection.
    """
    kind = 'annotator'
    id = 'dominance'
    version = '2'
    title = 'Cases that never govern'
    params = frozen_mapping({'fallback_excludes': EXTREME_EVENT.pattern})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Annotation]:
        if view.selected:
            basis, note = 'selected', 'Selected cases.'
            considered = [c for c in view.cases if c.id in view.selected]
        else:
            basis = 'fallback_non_extreme'
            note = ('No case selection: review-only fallback of all cases except extreme-event names. '
                    'This is not a case selection.')
            considered = [c for c in view.cases if not EXTREME_EVENT.match(c.name or '')]
        peaks = {c.id: [c.peak(key) for key in COMPONENTS] for c in considered}
        dominated = []
        for case in considered:
            mine = peaks[case.id]
            by = [other.id for other in considered
                  if peaks[other.id] != mine and all(o >= m for o, m in zip(peaks[other.id], mine, strict=True))]
            if by:
                dominated.append(frozen_mapping({'case': case.id, 'dominated_by': tuple(by)}))
        yield Annotation(self.id, 'dominance', None, None, frozen_mapping({
            'basis': basis, 'note': note, 'cases': tuple(c.id for c in considered), 'dominated': tuple(dominated)}))
