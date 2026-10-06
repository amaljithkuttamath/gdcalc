import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcdxkit import engine, group_report

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/cli.py'
FIXTURES = ROOT / 'tests/fixtures/review'
KIP_HEADER = 'AXIAL,KIP LAT. y,KIP LAT. z,KIP MOM x,KIP-IN MOM y,KIP-IN MOM z,KIP-IN'


def clean():
    return (FIXTURES / 'seed505_clean.txt').read_text()


def raised_axial():
    # Case 2 axial maximum 256.03 -> 317.0: P envelope 304.23 (case 3) -> 317.0 (case 2), +4.196%.
    text = clean()
    assert text.count('MAXIMUM 2.5603E+02') == 1
    return text.replace('MAXIMUM 2.5603E+02', 'MAXIMUM 3.1700E+02')


def revised_cases():
    """Case 6 removed, case 7 added (a copy of case 5's loads), case 1 renamed. Only service cases change."""
    text = clean()
    names, summary = text.split(group_report.MARKER)
    names = names.replace('CASE NAME : SER-IV-W225', 'CASE NAME : SER-IV-W230')
    names = names.replace('LOAD CASE : 6\nCASE NAME : SER-II\n', 'LOAD CASE : 7\nCASE NAME : SER-III\n')
    blocks = summary.split('LOAD CASE : ')
    assert blocks[6].startswith('6\n') and blocks[5].startswith('5\n')
    blocks[6] = '7' + blocks[5][1:]
    return names + group_report.MARKER + 'LOAD CASE : '.join(blocks)


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return path

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), 'compare', *map(str, args)], capture_output=True, text=True)

    def test_identical_reports_show_no_change(self):
        old = self.write('old.txt', clean()); new = self.write('new.txt', clean())
        result = engine.compare_reports(old, new)
        self.assertEqual([c['change_pct'] for c in result['components']], [0.0] * 5)
        self.assertFalse(any(c['governing_changed'] for c in result['components']))
        self.assertEqual(result['cases'], {'added': [], 'removed': [], 'renamed': [],
                                           'selection': {'old': [2, 3, 4], 'new': [2, 3, 4], 'changed': False}})
        self.assertEqual((result['review']['appeared'], result['review']['cleared']), ([], []))
        self.assertEqual(result['old']['sha256'], result['new']['sha256'])
        self.assertEqual(result['headline'], 'Envelope loads and governing cases unchanged; no new review items')
        run = self.run_cli(old, new)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(run.stdout.startswith('Envelope loads and governing cases unchanged'))
        self.assertIn('byte-identical', run.stdout)
        self.assertNotIn('[changed]', run.stdout)

    def test_load_increase_with_governing_case_change(self):
        old = self.write('old.txt', clean()); new = self.write('new.txt', raised_axial())
        result = engine.compare_reports(old, new)
        rows = {c['component']: c for c in result['components']}
        p = rows['P']
        self.assertEqual((p['old'], p['new'], p['unit']), (304.23, 317.0, 'kip'))
        self.assertAlmostEqual(p['change_pct'], (317.0 - 304.23) / 304.23 * 100)
        self.assertEqual((p['governing_old'], p['governing_new']),
                         ({'case': 3, 'name': 'STR-I'}, {'case': 2, 'name': 'STR-V-W225'}))
        self.assertTrue(p['governing_changed'])
        for key in ('Vy', 'Vz', 'My', 'Mz'):
            self.assertEqual(rows[key]['change_pct'], 0.0)
            self.assertFalse(rows[key]['governing_changed'])
        self.assertEqual(result['headline'], 'Axial load up 4.2% (case 2 now governs); no new review items')
        run = self.run_cli(old, new)
        self.assertEqual(run.returncode, 0, run.stderr)
        line = next(x for x in run.stdout.splitlines() if x.startswith('P (kip)'))
        self.assertIn('+4.2%', line)
        self.assertIn('3 STR-I -> 2 STR-V-W225  [changed]', line)

    def test_cases_added_removed_and_renamed_by_id(self):
        old = self.write('old.txt', clean()); new = self.write('new.txt', revised_cases())
        result = engine.compare_reports(old, new)
        self.assertEqual(result['cases']['added'], [{'id': 7, 'name': 'SER-III'}])
        self.assertEqual(result['cases']['removed'], [{'id': 6, 'name': 'SER-II'}])
        self.assertEqual(result['cases']['renamed'], [{'id': 1, 'old_name': 'SER-IV-W225', 'new_name': 'SER-IV-W230'}])
        self.assertFalse(result['cases']['selection']['changed'])
        self.assertEqual([c['change_pct'] for c in result['components']], [0.0] * 5)
        self.assertIn('1 case added, 1 case removed, 1 case renamed', result['headline'])
        run = self.run_cli(old, new)
        self.assertEqual(run.returncode, 0, run.stderr)
        for expected in ('added    7 SER-III', 'removed  6 SER-II', 'renamed  1 SER-IV-W225 -> SER-IV-W230'):
            self.assertIn(expected, run.stdout)

    def test_new_review_flag_from_mislabelled_case(self):
        old = FIXTURES / 'seed505_clean.txt'; new = FIXTURES / 'seed505_mislabel_str_as_ser.txt'
        result = engine.compare_reports(old, new)
        self.assertEqual([(f['rule'], f['case'], f['component']) for f in result['review']['appeared']],
                         [('service_axial_above_strength', 3, 'P')])
        self.assertEqual((result['review']['cleared'], result['review']['unchanged']), ([], 0))
        self.assertTrue(result['review']['advisory'])
        self.assertEqual(result['cases']['renamed'], [{'id': 3, 'old_name': 'STR-I', 'new_name': 'SER-IX'}])
        self.assertEqual(result['cases']['selection'], {'old': [2, 3, 4], 'new': [2, 4], 'changed': True})
        self.assertTrue(result['headline'].endswith('selected cases 2,3,4 -> 2,4; 1 new item to review'), result['headline'])
        # Swapped, the flag clears.
        back = engine.compare_reports(new, old)
        self.assertEqual(len(back['review']['cleared']), 1)
        self.assertEqual(back['review']['appeared'], [])
        self.assertIn('1 review item cleared', back['headline'])
        # With checks off there is nothing to compare, and the text output says so.
        off = engine.compare_reports(old, new, checks='none')
        self.assertEqual((off['review']['checks'], off['review']['appeared']), ([], []))
        self.assertNotIn('review', off['headline'])
        run = self.run_cli(old, new, '--checks', 'none')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('no review checks enabled', run.stdout)

    def test_unit_mismatch_stops_without_converting(self):
        old = self.write('old.txt', clean())
        new = self.write('new.txt', clean().replace(KIP_HEADER, 'AXIAL,KN LAT. y,KN LAT. z,KN MOM x,KN-M MOM y,KN-M MOM z,KN-M'))
        with self.assertRaisesRegex(engine.UnitMismatchError, 'Units differ.*KIP-IN.*KN-M.*does not convert'):
            engine.compare_reports(old, new)
        run = self.run_cli(old, new)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stdout, '')
        self.assertIn('Units differ: OLD old.txt uses force KIP, moment KIP-IN; NEW new.txt uses force KN, moment KN-M',
                      run.stderr)
        # Mixed units inside one report are reported for that report.
        mixed = clean().replace(KIP_HEADER, KIP_HEADER.replace('KIP', 'KN'), 1)
        run = self.run_cli(old, self.write('mixed.txt', mixed))
        self.assertEqual(run.returncode, 2)
        self.assertIn('NEW mixed.txt: Local reaction headers use more than one set of units', run.stderr)

    def test_selection_errors_name_the_report(self):
        old = self.write('old.txt', clean()); new = self.write('new.txt', revised_cases())
        run = self.run_cli(old, new, '--cases', '2,6')
        self.assertEqual(run.returncode, 2)
        self.assertIn('NEW new.txt: Select nonempty, unique, existing --cases', run.stderr)
        unnamed = self.write('unnamed.txt', group_report.MARKER + clean().split(group_report.MARKER)[1])
        result = engine.compare_reports(old, unnamed)
        self.assertIsNone(result['new']['envelope'])
        self.assertIsNotNone(result['new']['selection_required'])
        self.assertEqual({(c['new'], c['change_pct'], c['governing_changed']) for c in result['components']}, {(None, None, False)})
        self.assertTrue(result['headline'].startswith('Envelope not compared: case selection unresolved in NEW'))
        explicit = engine.compare_reports(old, unnamed, cases=[2, 3, 4])
        self.assertEqual([c['change_pct'] for c in explicit['components']], [0.0] * 5)
        self.assertEqual(len(explicit['cases']['renamed']), 6)

    def test_json_schema(self):
        old = FIXTURES / 'seed505_clean.txt'; new = FIXTURES / 'seed505_mislabel_str_as_ser.txt'
        run = self.run_cli(old, new, '--json', '--load-source', 'reactions')
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertEqual(set(data), {'schema', 'old', 'new', 'load_source', 'units', 'components', 'cases', 'review', 'headline'})
        self.assertEqual(data['schema'], 'report-compare/1')
        self.assertEqual((data['load_source'], data['units']), ('reactions', {'force': 'kip', 'moment': 'kip-in'}))
        for side in ('old', 'new'):
            self.assertEqual(set(data[side]), {'source', 'sha256', 'cases', 'selected_cases', 'selection_required', 'envelope'})
            self.assertEqual(len(data[side]['sha256']), 64)
        self.assertEqual([c['component'] for c in data['components']], ['P', 'Vy', 'Vz', 'My', 'Mz'])
        self.assertEqual([c['unit'] for c in data['components']], ['kip', 'kip', 'kip', 'kip-in', 'kip-in'])
        for row in data['components']:
            self.assertEqual(set(row), {'component', 'unit', 'old', 'new', 'change_pct', 'governing_old', 'governing_new', 'governing_changed'})
            self.assertEqual(set(row['governing_old']), {'case', 'name'})
        self.assertEqual(set(data['cases']), {'added', 'removed', 'renamed', 'selection'})
        self.assertEqual(set(data['review']), {'advisory', 'checks', 'appeared', 'cleared', 'unchanged', 'errors'})
        self.assertEqual(set(data['review']['errors']), {'old', 'new'})
        self.assertEqual(set(data['review']['appeared'][0]) >= {'rule', 'case', 'component', 'message'}, True)
        self.assertIsInstance(data['headline'], str)
        # Same values as inspect on the reactions basis.
        inspected = engine.inspect_report(old, load_source='reactions')
        self.assertEqual(data['old']['envelope'], inspected['envelope'])

    def test_change_from_zero_and_missing_input(self):
        # A change below display precision is still reported as a change.
        old = self.write('old.txt', clean()); new = self.write('new.txt', clean().replace('MAXIMUM 3.0423E+02', 'MAXIMUM 3.0424E+02'))
        result = engine.compare_reports(old, new)
        self.assertEqual(result['headline'], 'Axial load changed by less than 0.1%; no new review items')
        run = self.run_cli(old, new)
        self.assertIn('+<0.1%', next(x for x in run.stdout.splitlines() if x.startswith('P (kip)')))
        self.assertIsNone(engine._change_pct(0.0, 5.0))
        self.assertEqual(engine._change_pct(0.0, 0.0), 0.0)
        self.assertEqual(engine._change_pct(10.0, 5.0), -50.0)
        run = self.run_cli(self.dir / 'absent.txt', FIXTURES / 'seed505_clean.txt')
        self.assertEqual(run.returncode, 2)
        self.assertIn('absent.txt', run.stderr)


if __name__ == '__main__':
    unittest.main()
