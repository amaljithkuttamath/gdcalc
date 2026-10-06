"""Helpers shared by the built-in checks and annotators (review.api types only)."""
import re
from statistics import median
from typing import Dict, Optional, Sequence, Tuple

from ..api import COMPONENTS, CaseView, Impact, Range, ReportView

# A quantity is negligible below this share of the report's median for that quantity:
# ratios with a negligible denominator are undefined, negligible peaks are not compared.
NEGLIGIBLE = 0.01
# Robust statistics need defined values in at least three cases; with fewer, the median/MAD
# z-score cannot exceed 0.6745, so a statistical check could not flag anything.
MIN_CASES = 3

# STR/SER prefixes and AASHTO long names ('Strength I', 'Service I'). Advisory review only:
# the default case selection in group_report still recognizes only the STR/SER prefixes.
LIMIT_STATE = re.compile(r'^(?:(STR)(?:ENGTH)?|(SER)(?:VICE)?)(?:\b|[-_])', re.I)


def limit_state(name: Optional[str]) -> Optional[str]:
    match = LIMIT_STATE.match(name or '')
    return None if match is None else next(group for group in match.groups() if group).upper()


def magnitude(value: Range) -> float:
    """Largest absolute value of a (minimum, maximum) range; sign conventions do not matter."""
    return max(abs(value[0]), abs(value[1]))


def positive_median(values: Sequence[float]) -> float:
    positive = [v for v in values if v > 0]
    return median(positive) if positive else 0.0


def envelope(view: ReportView) -> Dict[str, float]:
    """Peaks of the selected cases; empty when no selection is resolved."""
    cases = [c for c in view.cases if c.id in view.selected]
    return {key: max(c.peak(key) for c in cases) for key in COMPONENTS} if cases else {}


def governs(view: ReportView, case: CaseView) -> Tuple[str, ...]:
    """Components whose selected envelope peak this (selected) case sets."""
    if case.id not in view.selected:
        return ()
    peaks = envelope(view)
    return tuple(key for key in COMPONENTS if case.peak(key) >= peaks[key])


def addition_impact(view: ReportView, case: CaseView, *, selection: bool) -> Impact:
    """What adding ``case`` to the selected envelope would raise, relative to the current peaks."""
    peaks = envelope(view)
    if case.id in view.selected or not peaks:
        return Impact(selection=selection)
    rises = {key: (case.peak(key) - peaks[key]) / peaks[key] for key in COMPONENTS
             if peaks[key] > 0 and case.peak(key) > peaks[key]}
    return Impact(envelope=bool(rises), selection=selection, magnitude=max(rises.values(), default=0.0),
                  components=tuple(rises))


def relative(a: float, b: float) -> float:
    """Relative size of a factor between two positive values: 10x and 0.1x are both 9."""
    if a <= 0 or b <= 0:
        return 0.0
    return max(a / b, b / a) - 1
