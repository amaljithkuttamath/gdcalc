"""Consistency rules: physical or labelling invariants with only a 1% rounding tolerance."""
from typing import Any, Dict, Iterator, Tuple

from ..api import Context, Flag, Impact, NotApplicable, ReportView, frozen_mapping
from ._shared import NEGLIGIBLE, addition_impact, envelope, governs, limit_state, magnitude, positive_median

# Relative rounding tolerance for GROUP's printed values.
TOLERANCE = 0.01
# Components compared between the pile-top reaction and the along-pile effects tables.
EFFECT_COMPONENTS = ('Vy', 'Vz', 'My', 'Mz')


class ServiceAxialAboveStrength:
    """A service case's maximum axial load exceeds every strength case.

    Axial load only: service lateral loads legitimately exceed strength (AASHTO LRFD
    Table 3.4.1-1 uses 1.2 TU in Service I against 0.5 TU in Strength).
    """
    kind = 'check'
    id = 'service_axial_above_strength'
    version = '2'
    title = 'Service axial load above strength'
    params = frozen_mapping({'tolerance': TOLERANCE, 'negligible': NEGLIGIBLE})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Flag]:
        strength = [c for c in view.cases if limit_state(c.name) == 'STR']
        service = [c for c in view.cases if limit_state(c.name) == 'SER']
        if not strength or not service:
            raise NotApplicable('needs both strength and service case names')
        governing = max(strength, key=lambda c: c.peak('P'))
        limit = governing.peak('P')
        if limit <= NEGLIGIBLE * positive_median([c.peak('P') for c in view.cases]):
            return  # no strength compression to compare against
        for case in service:
            value = case.peak('P')
            if value > limit * (1 + TOLERANCE):
                yield Flag(
                    self.id, case.id, 'P',
                    f'{case.label} axial load {value:.4g} exceeds every STR case '
                    f'(largest {limit:.4g}, case {governing.id}). Check the case name and load factors.',
                    value=value, compared_to=limit, unit=view.units['P'],
                    evidence=(('service', value), ('strength_max', limit), ('strength_case', governing.id)),
                    # A mislabelled strength case: selecting it would change the selection and may raise the envelope.
                    impact=addition_impact(view, case, selection=True))


class EffectsBelowTop:
    """The largest magnitude along the pile is below the pile-top reaction for the same quantity."""
    kind = 'check'
    id = 'effects_below_top'
    version = '1'
    title = 'Along-pile effects below pile-top reaction'
    params = frozen_mapping({'tolerance': TOLERANCE})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Flag]:
        if view.load_source != 'effects':
            raise NotApplicable('needs the effects load source')
        peaks = envelope(view)
        for case in view.cases:
            if case.along_pile is None:
                raise NotApplicable('needs the along-pile effects table')
            for component in EFFECT_COMPONENTS:
                top = magnitude(case.pile_top[component])
                along = magnitude(case.along_pile[component])
                if top > 0 and along < top * (1 - TOLERANCE):
                    yield Flag(
                        self.id, case.id, component,
                        f'{case.label} {component}: largest along-pile magnitude {along:.4g} is below the '
                        f'pile-top reaction {top:.4g}. Check that the effects table belongs to this case.',
                        value=along, compared_to=top, unit=view.units[component],
                        evidence=(('along_pile', along), ('pile_top', top)),
                        impact=self._impact(view, case, component, top, peaks))

    @staticmethod
    def _impact(view, case, component, top, peaks):
        # The envelope reads the effects table; if it belongs to another case, the true value is at
        # least the pile-top reaction, which may set a new peak.
        if case.id not in view.selected or top <= peaks[component]:
            return Impact()
        return Impact(envelope=True, magnitude=(top - peaks[component]) / peaks[component] if peaks[component] else 0.0,
                      components=(component,))


class DuplicateCase:
    """Two cases with identical numeric tables, usually a copied case."""
    kind = 'check'
    id = 'duplicate_case'
    version = '1'
    title = 'Duplicate case'
    params = frozen_mapping({})

    def run(self, view: ReportView, ctx: Context) -> Iterator[Flag]:
        seen: Dict[Tuple[Any, ...], Any] = {}
        for case in view.cases:
            key = tuple(case.pile_top.values()) + tuple((case.along_pile or {}).values())
            first = seen.setdefault(key, case)
            if first is not case:
                yield Flag(self.id, case.id, None,
                           f'{case.label} has tables identical to {first.label}. Check for a copied case.',
                           evidence=(('duplicate_of', first.id),),
                           # The copied case's real values are unknown: a selected copy may hide a peak.
                           impact=Impact(envelope=case.id in view.selected, components=governs(view, case)))
