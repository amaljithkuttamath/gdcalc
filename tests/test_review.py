"""Phase 1 review flags: planted errors in synthetic reports, clean reports, audit and inspect API.

fixtures/review holds two planted-error reports from the review-flags proof of concept and
their clean originals. They come from that study's synthetic pile-group generator (seeds 505
and 529), not from GROUP or any project.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from test_pipeline import clean_report, report, template
from gdcalc import engine, group_report, learn, review

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'review'


def fixture(name):
    return (FIXTURES / name).read_text()


def flags(text, load_source='effects'):
    return review.review(group_report.parse(text, load_source))['flags']


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
        for name, text in (('pipeline clean', clean_report()), ('seed 505', fixture('seed505_clean.txt')),
                           ('seed 529', fixture('seed529_clean.txt'))):
            for load_source in ('effects', 'reactions'):
                with self.subTest(name, load_source=load_source):
                    self.assertEqual(flags(text, load_source), [])

    def test_result_is_advisory_and_names_checks_that_could_not_run(self):
        result = review.review(group_report.parse(clean_report(), 'reactions'))
        self.assertEqual((result['advisory'], result['method'], result['version']), (True, review.METHOD, review.VERSION))
        self.assertEqual(result['checks'], ['service_exceeds_strength', 'duplicate_case'])
        self.assertEqual({s['rule'] for s in result['skipped']}, {'effects_below_top', 'ratio_outlier', 'unit_slip'})
        full = review.review(group_report.parse(fixture('seed529_clean.txt')))
        self.assertEqual(full['skipped'], [])

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
        self.assertEqual(summary(found), [('service_exceeds_strength', 7, c) for c in ('P', 'Vy', 'Vz', 'My', 'Mz')])
        self.assertEqual(found[0]['values'], {'service': 140, 'strength_max': 120, 'strength_case': 1})

    def test_poc_mislabel_sample(self):
        clean, planted = fixture('seed505_clean.txt'), fixture('seed505_mislabel_str_as_ser.txt')
        self.assertEqual(planted, clean.replace('CASE NAME : STR-I\n', 'CASE NAME : SER-IX\n'))
        found = flags(planted)
        self.assertTrue(found)
        self.assertEqual({f['rule'] for f in found}, {'service_exceeds_strength'})
        self.assertIn(3, {f['case'] for f in found})

    def test_ten_times_pile_top_cell(self):
        found = flags(scale_cell(clean_report(), 1, 'MINIMUM', 5, 10))
        self.assertEqual(summary(found), [('effects_below_top', 1, 'Mz')])
        self.assertEqual(found[0]['values'], {'along_pile': 950, 'pile_top': 9000})

    def test_ten_times_service_cell(self):
        found = flags(scale_cell(clean_report(), 2, 'MAXIMUM', 0, 10), 'reactions')
        self.assertEqual(summary(found), [('service_exceeds_strength', 2, 'P')])

    def test_poc_ten_times_effects_cell(self):
        clean, planted = fixture('seed529_clean.txt'), fixture('seed529_digit_edit.txt')
        changed = [(a, b) for a, b in zip(clean.splitlines(), planted.splitlines(), strict=True) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(float(changed[0][1].split()[4]), 10 * float(changed[0][0].split()[4]))
        found = flags(planted)
        self.assertEqual(summary(found), [('ratio_outlier', 3, 'along-pile/top My')])
        self.assertAlmostEqual(found[0]['values']['ratio'], 10, places=6)
        self.assertGreater(abs(found[0]['values']['z']), review.Z_THRESHOLD)

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
        self.assertEqual(found[0]['values'], {'duplicate_of': 1})

    def test_effects_copied_from_another_case(self):
        text = clean_report()
        found = flags(text.replace(effects_rows(text, 7), effects_rows(text, 1)))
        self.assertEqual(summary(found), [('effects_below_top', 7, 'Vy'), ('effects_below_top', 7, 'Vz'),
                                          ('effects_below_top', 7, 'My')])

    def test_thousand_times_lateral_load(self):
        text = fixture('seed529_clean.txt')
        for row in ('MINIMUM', 'MAXIMUM'):
            text = scale_cell(text, 2, row, 1, 1000)
        for row in ('Min.', 'Max.'):
            text = scale_cell(text, 2, row, 4, 1000)
        slips = [f for f in flags(text) if f['rule'] == 'unit_slip']
        self.assertEqual(summary(slips), [('unit_slip', 2, 'Vy')])
        self.assertIn('possible unit slip (lb vs kip)', slips[0]['detail'])

    def test_small_reports_skip_statistics(self):
        found = flags(scale_cell(clean_report(), 1, 'Max.', 3, 10))
        self.assertEqual(found, [])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_inspect_api(self):
        path = self.root / 'r.txt'
        path.write_text(clean_report().replace('CASE NAME : STR-V', 'CASE NAME : SER-V'))
        inspected = engine.inspect_report(path)
        self.assertNotIn('anomalies', inspected)
        self.assertEqual(inspected['selected_cases'], [1])
        result = inspected['review_flags']
        self.assertTrue(result['advisory'])
        self.assertEqual(summary(result['flags'])[0], ('service_exceeds_strength', 7, 'P'))
        self.assertEqual(engine.inspect_report(path, cases=[1, 7])['review_flags'], result)
        self.assertEqual(learn.suggest_cases(path)['review_flags'], result)
        path.write_text(clean_report())
        self.assertEqual(engine.inspect_report(path)['review_flags']['flags'], [])

    def test_audit_json_records_flags(self):
        path = self.root / 'r.txt'
        path.write_text(report())
        template(self.root / 'reference.mcdx')
        result = engine.convert(path, self.root / 'reference.mcdx', self.root / 'out' / 'w.mcdx')
        audit = json.loads((self.root / 'out' / 'w.audit.json').read_text())
        self.assertEqual(audit['review_flags'], result['review_flags'])
        flagged = audit['review_flags']
        self.assertTrue(flagged['advisory'])
        self.assertIn(('service_exceeds_strength', 2, 'P'), summary(flagged['flags']))
        self.assertIn(('effects_below_top', 1, 'Mz'), summary(flagged['flags']))
        for entry in flagged['flags']:
            self.assertEqual(set(entry), {'rule', 'case', 'component', 'detail', 'values'})
        # Advisory only: the selection and envelope are those of the unflagged default.
        self.assertEqual(audit['envelope'], {'P': 140, 'Vy': 24, 'Vz': 8, 'My': 190, 'Mz': 850})
        self.assertIs(audit.get('native_execution_verified', False), False)


if __name__ == '__main__':
    unittest.main()
