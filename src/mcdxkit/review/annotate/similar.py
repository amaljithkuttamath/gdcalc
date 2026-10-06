"""Similar past jobs: the nearest earlier conversions in the SAME output directory.

Each report is reduced to the log10 magnitudes of its selected-case envelope (P, Vy, Vz,
My, Mz) plus the log10 of its selected-case count. Distance is the root-mean-square of the
log10 differences, so it is scale-free and reads as "typically within x%": a distance of
log10(1.25) means the components differ by about 25% on average. Past jobs with different
units or a different load source are not comparable and are left out. The report under
review (same source SHA-256) is left out too.

Advisory context only: it reads the history the caller loaded for this output directory,
never the filesystem, and changes nothing.
"""
import math
from typing import Iterator, Mapping

from ..api import COMPONENTS, Annotation, Context, ReportView, frozen_mapping

# Envelope values below this (kip or kip-in) count as this, so near-zero components
# (an unloaded shear direction) do not dominate a scale-free distance.
FLOOR = 1.0
# Typical difference of at most 50% across components.
MAX_DISTANCE = math.log10(1.5)
# The selected-case count matters less than the loads themselves.
CASE_WEIGHT = 0.5
LIMIT = 3


def _log(value: float) -> float:
    return math.log10(max(abs(value), FLOOR))


def features(envelope: Mapping[str, float], case_count: int) -> tuple:
    return tuple(_log(envelope[key]) for key in COMPONENTS) + (CASE_WEIGHT * math.log10(max(case_count, 1)),)


def distance(a: tuple, b: tuple) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) / len(COMPONENTS))


class SimilarJobs:
    """Up to three earlier conversions in this output directory with the closest envelopes."""
    kind = 'annotator'
    id = 'similar_jobs'
    version = '1'
    title = 'Similar past jobs'
    params = frozen_mapping({'max_distance_log10': round(MAX_DISTANCE, 6), 'floor': FLOOR,
                             'case_weight': CASE_WEIGHT, 'limit': LIMIT})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Annotation]:
        cases = [c for c in view.cases if c.id in view.selected]
        past = getattr(ctx.history, 'past_jobs', None)
        if not cases or not callable(past):
            return
        envelope = {key: max(c.peak(key) for c in cases) for key in COMPONENTS}
        mine = features(envelope, len(cases))
        units = {key: view.units.get(key) for key in ('force', 'moment')}
        ranked = []
        for job in past():
            if ctx.source_sha256 and job.source_sha256 == ctx.source_sha256:
                continue
            if job.load_source != view.load_source or {k: job.units.get(k) for k in units} != units:
                continue
            gap = distance(features(job.envelope, len(job.cases)), mine)
            if gap <= MAX_DISTANCE:
                ranked.append((gap, job.name, job))
        ranked.sort(key=lambda row: (row[0], row[1]))
        for rank, (gap, _, job) in enumerate(ranked[:LIMIT], 1):
            differences = {key: round(100 * (10 ** (_log(job.envelope[key]) - _log(envelope[key])) - 1), 1)
                           for key in COMPONENTS}
            yield Annotation(self.id, 'similar_job', None, None, frozen_mapping({
                'rank': rank, 'name': job.name, 'date': job.date, 'template': job.template,
                'cases': list(job.cases), 'case_count': len(job.cases), 'load_source': job.load_source,
                'distance': round(gap, 6), 'typical_difference_pct': round(100 * (10 ** gap - 1), 1),
                'difference_pct': differences, 'envelope': dict(job.envelope)}))
