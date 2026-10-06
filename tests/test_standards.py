"""Synthetic register records: no licensed clauses or approved engineering rules."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from mcdxkit import standards


def audit():
    return {'sha256': 'a'*64, 'source_sha256': 'b'*64, 'template_sha256': 'c'*64,
            'source': 'synthetic.txt', 'cases': [1], 'load_source': 'effects',
            'envelope': {'P': 10, 'Vy': 2, 'Vz': 1, 'My': 20, 'Mz': 30},
            'source_cases': [{'id': 1, 'pairs': {'P': [8, 10]},
                              'source_rows': {'local': ['MINIMUM 8', 'MAXIMUM 10']}}],
            'overrides': {}, 'calculation': {'calculated': True, 'html_sha256': 'd'*64},
            'checks': [{'name': 'Synthetic check', 'expression': 'P <= C', 'region_id': '5',
                        'passed': True, 'result': 1, 'unit': 'kip', 'ratio': 0.5}]}


def populated():
    a = audit()
    r = standards.from_audit(a)
    r['project_basis'] = {key: 'SYNTHETIC' for key in standards.BASIS_FIELDS}
    r['project_basis']['load_source'] = 'effects'
    r['sources'].append({'id': 'test-code', 'kind': 'standard', 'version': '1',
                         'reference': 'Synthetic test authority', 'edition': 'test edition', 'sha256': None})
    r['rules'] = [{'id': 'test-rule', 'version': '1', 'source_id': 'test-code',
                   'source_version': '1', 'clause': 'Synthetic clause (not engineering)',
                   'value_ids': ['P_a'], 'dimension': 'force',
                   'applicability': {'design_method': 'SYNTHETIC'},
                   'check': {'region_id': '5', 'expression': 'P <= C'}, 'review': None}]
    return a, r


def reviewed(r):
    r['rules'][0]['review'] = {'decision': 'reviewed', 'reviewer': 'Synthetic reviewer',
                              'reviewed_at': '2026-10-06T12:00:00Z', 'reason': 'Synthetic test only',
                              'content_sha256': standards.content_hash(r)}


class RegisterTests(unittest.TestCase):
    def test_generated_register_preserves_provenance_and_never_claims_approval(self):
        a = audit(); r = standards.from_audit(a)
        self.assertEqual(r['rules'], [])
        self.assertEqual(r['sources'][0]['sha256'], a['source_sha256'])
        self.assertEqual(r['values'][0]['source_locator']['case_ids'], [1])
        self.assertEqual(r['values'][0]['quantity'], 10)
        self.assertEqual(standards.assess(r, a)['status'], 'missing_basis')
        self.assertFalse(standards.assess(r, a)['engineering_approval_verified'])

    def test_review_required_even_with_complete_citations(self):
        a, r = populated()
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'awaiting_engineering_review')

    def test_recorded_review_uses_calculated_result_without_recalculating(self):
        for passed in (True, False):
            a, r = populated(); a['checks'][0].update(passed=passed, result=int(passed))
            r['calculation_sha256'] = standards.audit_hash(a)
            reviewed(r)
            result = standards.assess(r, a)
            self.assertEqual(result['rules'][0]['state'], 'pass' if passed else 'fail')
            self.assertFalse(result['engineering_approval_verified'])

    def test_source_basis_value_rule_or_revision_change_invalidates_review(self):
        for field in ('edition', 'basis', 'value', 'version', 'revision'):
            a, r = populated(); reviewed(r)
            if field == 'edition': r['sources'][-1]['edition'] = 'changed'
            if field == 'basis': r['project_basis']['owner_amendments'] = 'changed'
            if field == 'value': r['values'][0]['transformations'].append('New note')
            if field == 'version': r['rules'][0]['version'] = '2'
            if field == 'revision': r['revision'] = 2
            with self.subTest(field=field):
                self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'awaiting_engineering_review')

    def test_other_audit_or_contradictory_result_is_calculation_error(self):
        a, r = populated(); reviewed(r)
        a['source_sha256'] = 'e'*64
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'calculation_error')
        a, r = populated(); a['checks'][0]['result'] = 0
        r['calculation_sha256'] = standards.audit_hash(a); reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'calculation_error')

    def test_unit_conversion_is_equivalent_but_wrong_dimension_is_rejected(self):
        a, r = populated()
        r['values'][0].update(quantity=44.482216152605, unit='kN')
        reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'pass')
        r['values'][0]['unit'] = 'm'; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'unsupported')

    def test_changed_load_value_cannot_claim_a_calculated_pass(self):
        a, r = populated(); r['values'][0]['quantity'] = 9; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'calculation_error')

    def test_missing_reference_applicability_and_missing_expression_states(self):
        a, r = populated(); r['rules'][0]['clause'] = None; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'missing_basis')
        a, r = populated(); r['rules'][0]['applicability']['design_method'] = 'OTHER'; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'not_applicable')
        a, r = populated(); r['rules'][0]['applicability']['unknown_property'] = 'x'; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'unsupported')
        a, r = populated(); r['rules'][0]['check']['expression'] = 'Other'; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'unsupported')

    def test_override_without_reason_stays_awaiting_review(self):
        a = audit(); a['overrides'] = {'n_z': 3}
        r = standards.from_audit(a)
        self.assertIsNone(r['overrides'][0]['reason'])
        self.assertEqual(r['overrides'][0]['review_state'], 'awaiting_engineering_review')

    def test_invalid_schema_duplicate_ids_and_nonfinite_values_rejected(self):
        for mutation in (lambda r: r.update(schema='unknown'),
                         lambda r: r['values'].append(copy.deepcopy(r['values'][0])),
                         lambda r: r['values'][0].update(quantity=float('nan')),
                         lambda r: r.update(revision=True)):
            a, r = populated(); mutation(r)
            with self.assertRaises(ValueError): standards.assess(r, a)

    def test_removed_mapping_or_override_cannot_claim_a_pass(self):
        a, r = populated(); r['values'][0]['component'] = None; reviewed(r)
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'calculation_error')
        a, r = populated(); a['overrides'] = {'n_z': 3}
        r['calculation_sha256'] = standards.audit_hash(a); reviewed(r)
        self.assertEqual(standards.assess(r, a)['status'], 'calculation_error')
        self.assertEqual(standards.assess(r, a)['rules'][0]['state'], 'calculation_error')

    def test_malformed_nested_records_are_rejected(self):
        for mutation in (lambda r: r['sources'][0].update(version=[]),
                         lambda r: r['values'][0].update(source_id={}),
                         lambda r: r['overrides'].append({'variable': [], 'quantity': 3}),
                         lambda r: r['overrides'].append({'variable': 'x', 'quantity': True})):
            a, r = populated(); mutation(r)
            with self.assertRaises(ValueError): standards.assess(r, a)

    def test_assessment_does_not_mutate_register_or_audit(self):
        a, r = populated(); before=copy.deepcopy((a,r)); standards.assess(r,a)
        self.assertEqual((a,r),before)

    def test_cli_initialization_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'input.audit.json'; dest=Path(folder)/'register.json'
            source.write_text(json.dumps(audit()))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(standards.main(['init',str(source),'--output',str(dest)]),0)
                self.assertEqual(standards.main(['inspect',str(dest),'--audit',str(source)]),0)
                self.assertEqual(standards.main(['init',str(source),'--output',str(dest)]),2)
            self.assertEqual(json.loads(dest.read_text())['schema'],standards.SCHEMA)
