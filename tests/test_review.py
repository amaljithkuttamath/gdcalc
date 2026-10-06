"""Built-in review checks: planted errors in synthetic reports, clean reports, audit and inspect API.

fixtures/review holds planted-error reports from the review-flags study and their clean
originals: seed505/seed529 from its round 1 generator and round2_* from its harder round 2
generator (thermal, 0.9D, extreme-event cases, naming styles, 4 significant figures). They are
synthetic pile-group models, not GROUP output or any project.
"""
import json
import re
from unittest import mock
import tempfile
import time
import unittest
from pathlib import Path

from test_pipeline import clean_report, report, template
from mcdxkit import engine, group_report, inspection
from mcdxkit.review import runner, view
from mcdxkit.review.api import Context
from mcdxkit.review.checks.consistency import ServiceAxialAboveStrength
from mcdxkit.review.checks.magnitude import GrossMagnitude
from mcdxkit.review.checks.ratios import Z_THRESHOLD

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'review'


def fixture(name):
    return (FIXTURES / name).read_text()


def review(text, load_source='effects', selected=None):
    return runner.review(group_report.parse(text, load_source), selected)


def flags(text, load_source='effects'):
    return review(text, load_source)['flags']


def run_check(check, parsed):
    return list(check.run(view.build(parsed), Context()))


ROUND2 = (('320000', 'unit_force_lb'), ('340022', 'mislabel_str_as_ser'), ('360011', 'digit_edit'),
          ('370001', 'copied_effects'))
CLEAN = ['seed505_clean.txt', 'seed529_clean.txt'] + [f'round2_seed{seed}_clean.txt' for seed, _ in ROUND2]


def summary(found):
    return [(f['rule'], f['case'], f['component']) for f in found]


def case_block(text, case_id):
    """(start, end) of a case's block in the final summary."""
    head = text.index('SUMMARY FOR LOAD CASES AND COMBINATIONS')
    start = text.index(f'LOAD CASE : {case_id}\n*', head)
    following = text.find('LOAD CASE :', start + 1)
    return start, len(text) if following < 0 else following


def scale_cell(text, case_id, row, column, factor):
    """Multiply one numeric cell of a case's row ('MINIMUM', 'MAXIMUM', 'Min.' or 'Max.')."""
    start, end = case_block(text, case_id)
    block = text[start:end]
    line = re.search(r'^' + re.escape(row) + r' .*$', block, re.M)
    words = line.group(0).split()
    words[column + 1] = repr(float(words[column + 1]) * factor)
    block = block[:line.start()] + ' '.join(words) + block[line.end():]
    return text[:start] + block + text[end:]


def effects_rows(text, case_id):
    start, end = case_block(text, case_id)
    return re.search(r'^Min\. .*\n(?:Pile N\..*\n)?Max\. .*$', text[start:end], re.M).group(0)


class CleanReportTests(unittest.TestCase):
    def test_clean_reports_give_no_flags(self):
        for name, text in [('pipeline clean', clean_report())] + [(n, fixture(n)) for n in CLEAN]:
            for load_source in ('effects', 'reactions'):
                with self.subTest(name, load_source=load_source):
                    self.assertEqual(flags(text, load_source), [])

    def test_result_is_advisory_and_names_checks_that_could_not_run(self):
        result = review(clean_report(), 'reactions')
        self.assertEqual((result['schema'], result['advisory']), ('review-checks/1', True))
        self.assertEqual(result['skipped'], [{'id': 'effects_below_top', 'reason': 'needs the effects load source'}])
        self.assertEqual(result['errors'], [])
        run = {c['id']: c for c in result['checks_run']}
        self.assertEqual(run['effects_below_top']['status'], 'skipped')
        self.assertEqual((run['ratio_outlier']['version'], run['ratio_outlier']['params']['z_threshold']), ('2', 5.63))
        two = clean_report().split('LOAD CASE : 7\n*')[0]
        self.assertEqual({s['id'] for s in review(two)['skipped']}, {'ratio_outlier', 'gross_magnitude'})
        unnamed = review(clean_report().replace('SER-I', 'Wind'))
        self.assertEqual(unnamed['skipped'][0]['id'], 'service_axial_above_strength')

    def test_effects_moment_sign_convention_does_not_matter(self):
        # The POC generator reports pile-effect moments with the opposite sign to the pile-top
        # reactions; test_pipeline uses the same sign. Magnitudes are compared, so both are clean.
        text = clean_report()
        for case_id in (1, 2, 7):
            rows = effects_rows(text, case_id)
            minimum, maximum = (line.split() for line in rows.splitlines())
            for column in (3, 4):  # moment z-DIR and y-DIR
                minimum[column], maximum[column] = repr(-float(maximum[column])), repr(-float(minimum[column]))
            text = text.replace(rows, ' '.join(minimum) + '\n' + ' '.join(maximum))
        self.assertEqual(flags(text), [])
        self.assertEqual(group_report.envelope(group_report.select(group_report.parse(text))),
                         group_report.envelope(group_report.select(group_report.parse(clean_report()))))


class PlantedErrorTests(unittest.TestCase):
    def test_strength_case_relabelled_service(self):
        found = flags(clean_report().replace('CASE NAME : STR-V', 'CASE NAME : SER-V'))
        self.assertEqual(summary(found), [('service_axial_above_strength', 7, 'P')])
        self.assertEqual(found[0]['evidence'], {'service': 140, 'strength_max': 120, 'strength_case': 1})

    def test_aashto_long_names(self):
        long = (clean_report().replace('STR-I\n', 'Strength I\n').replace('SER-I\n', 'Service I\n')
                .replace('STR-V\n', 'STRENGTH V\n'))
        self.assertEqual(flags(long), [])
        self.assertEqual(summary(flags(long.replace('STRENGTH V\n', 'SERVICE V\n'))),
                         [('service_axial_above_strength', 7, 'P')])
        # Default selection still recognizes only the STR/SER prefixes (unchanged behaviour).
        with self.assertRaisesRegex(ValueError, 'classification unavailable'):
            group_report.select(group_report.parse(long))

    def test_service_rule_needs_strength_compression(self):
        text = (clean_report().replace('MINIMUM 90 -20', 'MINIMUM -120 -20').replace('MAXIMUM 120 15', 'MAXIMUM -90 15')
                .replace('MINIMUM 100 -25', 'MINIMUM -140 -25').replace('MAXIMUM 140 18', 'MAXIMUM -100 18'))
        parsed = group_report.parse(text)
        self.assertEqual([group_report.peak(c, 'P') for c in parsed['cases']], [-90, 90, -100])
        self.assertEqual(run_check(ServiceAxialAboveStrength(), parsed), [])

    def test_poc_mislabel_samples(self):
        clean, planted = fixture('seed505_clean.txt'), fixture('seed505_mislabel_str_as_ser.txt')
        self.assertEqual(planted, clean.replace('CASE NAME : STR-I\n', 'CASE NAME : SER-IX\n'))
        self.assertEqual(summary(flags(planted)), [('service_axial_above_strength', 3, 'P')])
        found = flags(fixture('round2_seed340022_mislabel_str_as_ser.txt'))
        self.assertEqual(summary(found), [('service_axial_above_strength', 1, 'P')])

    def test_ten_times_pile_top_cell(self):
        found = flags(scale_cell(clean_report(), 1, 'MINIMUM', 5, 10))
        self.assertEqual(summary(found)[0], ('effects_below_top', 1, 'Mz'))
        self.assertEqual(found[0]['evidence'], {'along_pile': 950, 'pile_top': 9000})
        self.assertEqual({f['case'] for f in found}, {1})

    def test_ten_times_service_cell(self):
        found = flags(scale_cell(clean_report(), 2, 'MAXIMUM', 0, 10), 'reactions')
        self.assertEqual(summary(found), [('service_axial_above_strength', 2, 'P')])

    def test_ten_times_effects_cell(self):
        found = flags(scale_cell(clean_report(), 1, 'Max.', 3, 10))
        self.assertEqual(summary(found), [('ratio_outlier', 1, 'along-pile/top My')])
        clean, planted = fixture('seed529_clean.txt'), fixture('seed529_digit_edit.txt')
        changed = [(a, b) for a, b in zip(clean.splitlines(), planted.splitlines(), strict=True) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(float(changed[0][1].split()[4]), 10 * float(changed[0][0].split()[4]))
        found = flags(planted)
        self.assertEqual(summary(found), [('ratio_outlier', 3, 'along-pile/top My')])
        self.assertAlmostEqual(found[0]['evidence']['ratio'], 10, places=6)
        self.assertGreater(abs(found[0]['evidence']['z']), Z_THRESHOLD)
        self.assertEqual(summary(flags(fixture('round2_seed360011_digit_edit.txt'))),
                         [('effects_below_top', 8, 'Vy'), ('ratio_outlier', 8, 'along-pile/top Vy')])

    def test_sign_flip(self):
        # A flip that keeps minimum <= maximum leaves every magnitude, the envelope and the
        # flags unchanged: magnitude rules cannot see it, and it does not change the result.
        flipped = scale_cell(clean_report(), 1, 'MAXIMUM', 5, -1)
        self.assertEqual(flags(flipped), [])
        envelope = group_report.envelope(group_report.select(group_report.parse(flipped, 'reactions')))
        self.assertEqual(envelope['Mz'], 950)
        # A flip that inverts the extrema is refused by the parser, not reviewed.
        with self.assertRaisesRegex(ValueError, 'Minimum exceeds maximum'):
            group_report.parse(scale_cell(clean_report(), 1, 'Min.', 2, -1))

    def test_duplicated_case(self):
        text = clean_report()
        start, end = case_block(text, 1)
        source = text[start:end].replace('LOAD CASE : 1', 'LOAD CASE : 7')
        start7, end7 = case_block(text, 7)
        found = flags(text[:start7] + source + text[end7:])
        self.assertEqual(summary(found), [('duplicate_case', 7, None)])
        self.assertEqual(found[0]['evidence'], {'duplicate_of': 1})

    def test_effects_copied_from_another_case(self):
        text = clean_report()
        found = flags(text.replace(effects_rows(text, 7), effects_rows(text, 1)))
        self.assertEqual(summary(found)[:3], [('effects_below_top', 7, 'Vy'), ('effects_below_top', 7, 'Vz'),
                                              ('effects_below_top', 7, 'My')])
        self.assertEqual({f['case'] for f in found}, {7})
        found = flags(fixture('round2_seed370001_copied_effects.txt'))
        self.assertIn(('effects_below_top', 4, 'My'), summary(found))

    def test_thousand_times_lateral_load(self):
        text = fixture('seed529_clean.txt')
        for row in ('MINIMUM', 'MAXIMUM'):
            text = scale_cell(text, 2, row, 1, 1000)
        for row in ('Min.', 'Max.'):
            text = scale_cell(text, 2, row, 4, 1000)
        gross = [f for f in flags(text) if f['rule'] == 'gross_magnitude']
        self.assertEqual(summary(gross), [('gross_magnitude', 2, 'V')])
        self.assertIn('possible unit slip', gross[0]['message'])
        self.assertNotIn('kip-ft', gross[0]['message'])
        found = flags(fixture('round2_seed320000_unit_force_lb.txt'))
        self.assertIn(('gross_magnitude', 3, 'V'), summary(found))

    def test_negligible_lateral_load_is_not_a_unit_slip(self):
        # A gravity case with 0.02 kip shear beside wind cases near 15 kip.
        rows = [(1, 'STR-I', 0.02), (2, 'STR-III-W0', 15), (3, 'STR-III-W90', 14), (4, 'STR-V-W0', 16),
                (5, 'SER-I', 13), (6, 'SER-IV-W0', 12)]
        text = ''.join(f'LOAD CASE : {i}\nCASE NAME : {n}\n' for i, n, _ in rows) + 'SUMMARY FOR LOAD CASES AND COMBINATIONS\n'
        for i, _, v in rows:
            text += (f'LOAD CASE : {i}\n* PILE TOP REACTIONS, LOCAL *\n'
                     'AXIAL,KIP LAT. y,KIP LAT. z,KIP MOM x,KIP-IN MOM y,KIP-IN MOM z,KIP-IN\n'
                     f'MINIMUM 90 0 0 0 0 0\nMAXIMUM 120 {v} 0 0 0 {v * 40}\n')
        parsed = group_report.parse(text, 'reactions')
        self.assertEqual(run_check(GrossMagnitude(), parsed), [])
        self.assertEqual(flags(text, 'reactions'), [])


def inspection_text(path):
    """All worksheet text, as the read-only inspection reconstructs it."""
    return json.dumps(inspection.worksheet(path))


def dominance(block):
    found = [a['data'] for a in block['annotations'] if a['kind'] == 'dominance']
    return found[0] if found else None


class DominanceTests(unittest.TestCase):
    def test_dominated_case_is_marked_but_stays_selected(self):
        result = dominance(review(clean_report(), selected=[1, 7]))
        self.assertEqual(result['basis'], 'selected')
        self.assertEqual(result['dominated'], [{'case': 1, 'dominated_by': [7]}])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'r.txt'
            path.write_text(clean_report())
            inspected = engine.inspect_report(path)
        self.assertEqual(inspected['selected_cases'], [1, 7])
        self.assertEqual(dominance(inspected['review_checks'])['dominated'], [{'case': 1, 'dominated_by': [7]}])
        self.assertEqual(inspected['envelope']['P'], 140)

    def test_unresolved_selection_uses_review_only_fallback(self):
        text = (clean_report().replace('STR-I\n', 'Comb 1\n').replace('SER-I\n', 'EQ-1\n')
                .replace('STR-V\n', 'Comb 7\n'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'r.txt'
            path.write_text(text)
            inspected = engine.inspect_report(path)
        self.assertIn('classification unavailable', inspected['selection_required'])
        self.assertEqual((inspected['selected_cases'], inspected['envelope'], inspected['governing']), ([], None, None))
        found = dominance(inspected['review_checks'])
        self.assertEqual(found['basis'], 'fallback_non_extreme')
        self.assertIn('not a case selection', found['note'])
        self.assertEqual(found['cases'], [1, 7])
        self.assertEqual(found['dominated'], [{'case': 1, 'dominated_by': [7]}])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        template(self.root / 'reference.mcdx')

    def tearDown(self):
        self.folder.cleanup()

    def convert(self, text, name, **options):
        path = self.root / ('source-' + name) / 'r.txt'
        path.parent.mkdir()
        path.write_text(text)
        return engine.convert(path, self.root / 'reference.mcdx', self.root / name / 'w.mcdx', **options)

    def test_inspect_api(self):
        path = self.root / 'r.txt'
        path.write_text(clean_report().replace('CASE NAME : STR-V', 'CASE NAME : SER-V'))
        inspected = engine.inspect_report(path)
        self.assertNotIn('anomalies', inspected)
        self.assertNotIn('review_flags', inspected)
        self.assertEqual(inspected['selected_cases'], [1])
        result = inspected['review_checks']
        self.assertTrue(result['advisory'])
        self.assertEqual(summary(result['flags']), [('service_axial_above_strength', 7, 'P')])
        # Impact depends on the selection: with case 7 unselected, selecting it raises every component
        # (P by 1/6; magnitude is the largest relative rise).
        self.assertEqual(result['flags'][0]['impact'], {'envelope': True, 'selection': True,
                                                        'magnitude': result['flags'][0]['impact']['magnitude'],
                                                        'components': ['P', 'Vy', 'Vz', 'My', 'Mz']})
        self.assertGreaterEqual(result['flags'][0]['impact']['magnitude'], 140 / 120 - 1)
        both = engine.inspect_report(path, cases=[1, 7])['review_checks']['flags']
        self.assertEqual([dict(f, impact=None) for f in both], [dict(f, impact=None) for f in result['flags']])
        self.assertEqual(both[0]['impact'], {'envelope': False, 'selection': True, 'magnitude': 0.0, 'components': []})
        path.write_text(clean_report())
        self.assertEqual(engine.inspect_report(path)['review_checks']['flags'], [])
        off = engine.inspect_report(path, checks='none')
        self.assertEqual((off['review_checks']['checks_run'], off['governing'], off['case_suggestions']), ([], None, None))
        with self.assertRaisesRegex(ValueError, 'Unknown review check'):
            engine.inspect_report(path, checks='default,no_such_check')
        only = engine.inspect_report(path, checks='ratio_outlier')['review_checks']
        self.assertEqual([c['id'] for c in only['checks_run']], ['ratio_outlier'])

    def test_audit_json_records_flags(self):
        result = self.convert(report(), 'out')
        audit = json.loads((self.root / 'out' / 'w.audit.json').read_text())
        self.assertEqual(audit['review_checks'], result['review_checks'])
        self.assertNotIn('review_flags', audit)
        flagged = audit['review_checks']
        self.assertEqual((flagged['schema'], flagged['advisory']), ('review-checks/1', True))
        self.assertIn(('service_axial_above_strength', 2, 'P'), summary(flagged['flags']))
        self.assertIn(('effects_below_top', 1, 'Mz'), summary(flagged['flags']))
        self.assertEqual(dominance(flagged)['basis'], 'selected')
        self.assertEqual(dominance(flagged)['cases'], [1, 7])
        for entry in flagged['flags']:
            self.assertEqual(set(entry), {'rule', 'case', 'component', 'message', 'value', 'compared_to', 'unit',
                                          'evidence', 'actions', 'impact'})
            self.assertEqual(set(entry['impact']), {'envelope', 'selection', 'magnitude', 'components'})
            self.assertEqual(entry['actions'], ['show_in_report', 'mark_reviewed'])
        # Each check's version and thresholds are recorded with the result.
        for entry in flagged['checks_run']:
            self.assertEqual(set(entry), {'id', 'version', 'kind', 'source', 'params', 'status'})
        self.assertNotIn('decisions', flagged)
        # Advisory only: the selection and envelope are those of the unflagged default.
        self.assertEqual(audit['envelope'], {'P': 140, 'Vy': 24, 'Vz': 8, 'My': 190, 'Mz': 850})
        self.assertIs(audit.get('native_execution_verified', False), False)

    def test_review_decisions_are_recorded_and_noted_in_the_worksheet(self):
        decision = {'rule': 'service_axial_above_strength', 'case': 2, 'component': 'P', 'decision': 'kept_service',
                    'note': 'Service factors confirmed with the designer.', 'decided_at': '2026-10-06T09:30:00+00:00'}
        fixed = mock.patch('time.localtime', return_value=time.struct_time((2020, 1, 1, 0, 0, 0, 2, 1, 0)))
        with fixed:
            plain = self.convert(report(), 'plain')
            decided = self.convert(report(), 'decided', review_decisions=[decision])
        block = decided['review_checks']
        self.assertEqual(block['decisions'], [decision])
        self.assertEqual(runner.open_flags(block), runner.open_flags(plain['review_checks']) - 1)
        audit = json.loads((self.root / 'decided' / 'w.audit.json').read_text())
        self.assertEqual(audit['review_checks']['decisions'], [decision])
        raised = len(block['flags'])
        note = engine.review_note(block)
        self.assertEqual(note, f'Automated input checks: 5 run, {raised} items raised, 1 reviewed by the engineer\n'
                               'Checks review the GROUP summary for consistency. They do not verify the design.')
        self.assertIsNone(engine.review_note(plain['review_checks']))
        texts = inspection_text(self.root / 'decided' / 'w.mcdx')
        self.assertIn('Automated input checks: 5 run', texts)
        self.assertIn('They do not verify the design.', texts)
        self.assertNotIn('Automated input checks', inspection_text(self.root / 'plain' / 'w.mcdx'))
        # The note is plain text outside any math region: the calculation is unchanged.
        for suffix in ('.cpd', '.html'):
            self.assertEqual((self.root / 'plain' / ('w' + suffix)).read_bytes(),
                             (self.root / 'decided' / ('w' + suffix)).read_bytes(), suffix)
        bad = [dict(decision, case=1), dict(decision, decision='approve'), dict(decision, extra=1),
               dict(decision, decided_at='yesterday'), {k: v for k, v in decision.items() if k != 'decided_at'},
               'x']
        for index, item in enumerate(bad):
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.convert(report(), f'bad{index}', review_decisions=[item])
            self.assertFalse((self.root / f'bad{index}').exists())
        with self.assertRaisesRegex(ValueError, 'More than one'):
            self.convert(report(), 'twice', review_decisions=[decision, decision])

    def test_every_flag_decided_uses_the_short_wording(self):
        text = clean_report().replace('CASE NAME : STR-V', 'CASE NAME : SER-V')
        found = flags(text)
        self.assertEqual(len(found), 1)
        decision = {'rule': found[0]['rule'], 'case': 7, 'component': 'P', 'decision': 'will_fix_in_group',
                    'note': None, 'decided_at': '2026-10-06T09:30:00'}
        result = self.convert(text, 'one', review_decisions=[decision])
        self.assertEqual(engine.review_note(result['review_checks']).splitlines()[0],
                         'Automated input checks: 5 run, 1 item raised, reviewed by the engineer')

    def test_decision_for_a_rule_that_did_not_run_is_kept_unverified(self):
        decision = {'rule': 'service_axial_above_strength', 'case': 2, 'component': 'P', 'decision': 'kept_service',
                    'note': None, 'decided_at': '2026-10-06T09:30:00Z'}
        with mock.patch.object(ServiceAxialAboveStrength, 'run', side_effect=RuntimeError('crash')):
            result = self.convert(report(), 'crashed', review_decisions=[decision])
        block = result['review_checks']
        self.assertEqual(block['decisions'], [dict(decision, unverified=True)])
        self.assertIn('service_axial_above_strength', {e['id'] for e in block['errors']})
        # Rules that ran successfully still reject decisions that match none of their flags.
        with self.assertRaisesRegex(ValueError, 'does not match a raised flag'):
            self.convert(report(), 'stale', review_decisions=[dict(decision, rule='ratio_outlier')])

    def test_malformed_decision_values_raise_value_error(self):
        decision = {'rule': 'service_axial_above_strength', 'case': 2, 'component': 'P', 'decision': 'kept_service',
                    'note': None, 'decided_at': '2026-10-06T09:30:00'}
        flagged = {'flags': [{'rule': decision['rule'], 'case': 2, 'component': 'P'}],
                   'checks_run': [{'id': decision['rule'], 'kind': 'check', 'status': 'ok'}]}
        for bad in (dict(decision, case=[1]), dict(decision, rule={}), dict(decision, case=True),
                    dict(decision, component=['P']), dict(decision, decision=['kept_service']),
                    dict(decision, decided_at=20261006), dict(decision, decided_at='2026-10-06'),
                    dict(decision, decided_at='2026-10-06T09'), dict(decision, decided_at='2026-13-06T09:30:00'),
                    dict(decision, decided_at='20261006T093000')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                engine._decisions(flagged, [bad])
        for good in ('2026-10-06T09:30', '2026-10-06T09:30:00Z', '2026-10-06T09:30:00.123Z',
                     '2026-10-06T09:30:00.123456+02:00'):
            with self.subTest(good=good):
                self.assertEqual(engine._decisions(flagged, [dict(decision, decided_at=good)])[0]['decided_at'], good)

    def test_open_checks_is_null_when_no_check_ran(self):
        path = self.root / 'r.txt'
        path.write_text(report())
        with mock.patch.object(runner.views, 'build', side_effect=RuntimeError('boom')):
            failed = engine.inspect_report(path)['review_checks']
        self.assertIsNone(runner.open_flags(failed))
        self.assertEqual(runner.check_errors(failed), 1)
        self.assertIsNone(runner.open_flags(engine.inspect_report(path, checks='none')['review_checks']))
        clean = self.root / 'clean.txt'
        clean.write_text(clean_report())
        block = engine.inspect_report(clean)['review_checks']
        self.assertEqual((runner.open_flags(block), runner.check_errors(block)), (0, 0))

    def test_review_failure_never_fails_inspect_or_convert(self):
        path = self.root / 'r.txt'
        path.write_text(report())
        with mock.patch.object(runner.views, 'build', side_effect=RuntimeError('boom')):
            inspected = engine.inspect_report(path)
            result = self.convert(report(), 'failed')
        for value in (inspected['review_checks'], result['review_checks']):
            self.assertEqual(value['errors'], [{'type': 'review_error', 'id': None, 'version': None,
                                                'message': 'review view unavailable: boom'}])
            self.assertTrue(value['advisory'])
            self.assertEqual(value['flags'], [])
        self.assertEqual(inspected['selected_cases'], [1, 7])
        audit = json.loads((self.root / 'failed' / 'w.audit.json').read_text())
        self.assertEqual(audit['review_checks']['errors'][0]['message'], 'review view unavailable: boom')

    def test_outputs_identical_with_review_on_and_off(self):
        text = report()  # heavily flagged report: flags must still change nothing
        # ZIP entries (including nested Xaml packages) carry the wall-clock time; fix it.
        fixed = mock.patch('time.localtime', return_value=time.struct_time((2020, 1, 1, 0, 0, 0, 2, 1, 0)))
        with fixed:
            self.convert(text, 'on', checks='default')
            self.convert(text, 'off', checks='none')
        for suffix in ('.mcdx', '.cpd', '.html'):
            self.assertEqual((self.root / 'on' / ('w' + suffix)).read_bytes(),
                             (self.root / 'off' / ('w' + suffix)).read_bytes(), suffix)
        on, off = (json.loads((self.root / n / 'w.audit.json').read_text().replace(f'/{n}/', '/X/'))
                   for n in ('on', 'off'))
        self.assertTrue(on.pop('review_checks')['flags'])
        self.assertEqual(off.pop('review_checks'), runner.empty('effects'))
        self.assertEqual(on, off)


if __name__ == '__main__':
    unittest.main()
