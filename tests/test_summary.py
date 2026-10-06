import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_pipeline import report, template
from gdcalc import engine

CLI = Path(__file__).resolve().parents[1] / 'scripts/cli.py'
COLUMNS = ['report', 'origin', 'source_sha256', 'load_source', 'case_id', 'case_name', 'selected',
           'P_kip', 'Vy_kip', 'Vz_kip', 'My_kip_in', 'Mz_kip_in', 'governs']


def split_report():
    # Case 1 now has the larger z shear (9 > 8); case 7 still governs every other measure.
    return report().replace('Max. .2 .3 400 180 14 7', 'Max. .2 .3 400 180 14 9')


def parse(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows, {(r['report'], r['case_id']): r for r in rows}


class SummaryRowTests(unittest.TestCase):
    def test_per_case_values_and_governing_case_per_measure(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / 'a.txt'; a.write_text(report())
            b = Path(d) / 'b.gp11t'; b.write_text(split_report())
            text = engine.summary_csv(engine.summarize_report(a) + engine.summarize_report(b))
            self.assertEqual(text.splitlines()[0].split(','), COLUMNS)
            rows, by = parse(text)
            self.assertEqual(len(rows), 6)
            # Hand-read from the fixture's final local summary (pile effects basis).
            self.assertEqual([by['a.txt', '1'][k] for k in COLUMNS[7:12]], ['120', '18', '7', '180', '800'])
            self.assertEqual([by['a.txt', '7'][k] for k in COLUMNS[7:12]], ['140', '24', '8', '190', '850'])
            self.assertEqual(by['a.txt', '7']['governs'], 'P Vy Vz My Mz')
            self.assertEqual(by['a.txt', '1']['governs'], '')
            # The service case has larger loads but is not selected, so it never governs.
            self.assertEqual((by['a.txt', '2']['P_kip'], by['a.txt', '2']['selected'], by['a.txt', '2']['governs']), ('1000', 'no', ''))
            self.assertEqual(by['b.gp11t', '1']['governs'], 'Vz')
            self.assertEqual(by['b.gp11t', '7']['governs'], 'P Vy My Mz')
            self.assertEqual(by['a.txt', '1']['case_name'], 'STR-I')
            self.assertEqual(by['a.txt', '1']['source_sha256'], hashlib.sha256(a.read_bytes()).hexdigest())

    def test_reactions_basis_explicit_cases_and_unresolved_selection(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'r.txt'; src.write_text(report())
            _, by = parse(engine.summary_csv(engine.summarize_report(src, load_source='reactions')))
            self.assertEqual((by['r.txt', '7']['Vy_kip'], by['r.txt', '7']['Mz_kip_in'], by['r.txt', '7']['load_source']), ('25', '950', 'reactions'))
            _, by = parse(engine.summary_csv(engine.summarize_report(src, cases=[1])))
            self.assertEqual(by['r.txt', '1']['governs'], 'P Vy Vz My Mz')
            self.assertEqual(by['r.txt', '7']['selected'], 'no')
            unnamed = Path(d) / 'unnamed.txt'; unnamed.write_text(report().split('SUMMARY FOR')[1].join(['SUMMARY FOR', '']))
            with self.assertRaisesRegex(ValueError, 'unnamed.txt.*cases'):
                engine.summarize_report(unnamed)
            with self.assertRaises(ValueError):
                engine.summarize_report(src, cases=[99])

    def test_spreadsheet_formula_names_are_neutralized(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'f.txt'; src.write_text(report().replace('CASE NAME : SER-I', 'CASE NAME : =HYPERLINK("x")'))
            _, by = parse(engine.summary_csv(engine.summarize_report(src, cases=[1, 7])))
            self.assertEqual(by['f.txt', '2']['case_name'], '\'=HYPERLINK("x")')


class SummaryCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)

    def test_duplicate_reports_are_skipped_and_non_ascii_names_survive(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); a = d / 'a.txt'; a.write_text(report().replace('SER-I', 'SER-Ä'), encoding='utf-8')
            copy = d / 'copy.txt'; copy.write_bytes(a.read_bytes()); out = d / 's.csv'
            r = self.run_cli('summary', a, a, copy, '-o', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['duplicates_skipped'], [str(a), str(copy)])
            rows, by = parse(out.read_text(encoding='utf-8-sig'))
            self.assertEqual(len(rows), 3); self.assertEqual(by['a.txt', '2']['case_name'], 'SER-Ä')
            # The same bytes with a different selection are a different summary, not a duplicate.
            r = self.run_cli('summary', a, '--cases', '1', '-o', d / 'one.csv')
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_reports_to_csv_never_overwrites_and_failures_write_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); a = d / 'a.txt'; a.write_text(report()); b = d / 'b.txt'; b.write_text(split_report())
            out = d / 'summary.csv'
            r = self.run_cli('summary', a, b, '-o', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['rows'], 6)
            self.assertTrue(out.read_bytes().startswith(b'\xef\xbb\xbf'))
            rows, by = parse(out.read_text(encoding='utf-8-sig'))
            self.assertEqual(by['b.txt', '1']['governs'], 'Vz')
            before = out.read_bytes()
            again = self.run_cli('summary', a, '-o', out)
            self.assertEqual(again.returncode, 2); self.assertIn('exists', again.stderr)
            self.assertEqual(out.read_bytes(), before)
            bad = d / 'bad.txt'; bad.write_text('incomplete report')
            failed = d / 'failed.csv'
            r = self.run_cli('summary', a, bad, '-o', failed)
            self.assertEqual(r.returncode, 2); self.assertFalse(failed.exists())
            (d / 'summary.json').write_text('{}')
            r = self.run_cli('summary', a, '-o', d / 'summary.json')
            self.assertEqual(r.returncode, 2); self.assertIn('.csv', r.stderr)
            self.assertEqual(self.run_cli('summary', d / 'absent.txt', '-o', d / 'x.csv').returncode, 2)

    def test_output_directory_uses_audited_selection_and_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); raw = d / 'raw'; raw.mkdir()
            (raw / 'a.txt').write_text(report()); (raw / 'b.txt').write_text(split_report())
            ref = d / 'reference.mcdx'; template(ref); results = d / 'results'
            batch = self.run_cli('batch', raw, '--template', ref, '--output-dir', results, '--workers', '1', '--cases', '1', '--quiet')
            self.assertEqual(batch.returncode, 0, batch.stderr)
            out = d / 'summary.csv'
            r = self.run_cli('summary', results, '-o', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            rows, by = parse(out.read_text(encoding='utf-8-sig'))
            self.assertEqual(json.loads(r.stdout)['reports'], 2)
            # The audit recorded cases [1], so case 7 is listed but not selected.
            self.assertEqual((by['b.txt', '1']['governs'], by['b.txt', '7']['selected']), ('P Vy Vz My Mz', 'no'))
            self.assertTrue(by['a.txt', '1']['origin'].endswith('/a.audit.json'))
            self.assertEqual(self.run_cli('summary', results, '--cases', '1,7', '-o', d / 'cases.csv').returncode, 2)
            # Even the default basis, given explicitly, cannot override audited settings.
            self.assertEqual(self.run_cli('summary', results, '--load-source', 'effects', '-o', d / 'basis.csv').returncode, 2)
            # Overlapping inputs: a directory, its subfolder and the identical report are summarized once.
            job = next(results.glob('*/a.audit.json')).parent
            r = self.run_cli('summary', results, job, '-o', d / 'overlap.csv')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((json.loads(r.stdout)['reports'], len(json.loads(r.stdout)['duplicates_skipped'])), (2, 1))
            self.assertEqual(len(parse((d / 'overlap.csv').read_text(encoding='utf-8-sig'))[0]), 6)
            # An audited selection that no longer resolves names the audit file.
            audit = job / 'a.audit.json'; original = audit.read_text()
            audit.write_text(json.dumps({**json.loads(original), 'cases': [99]}))
            r = self.run_cli('summary', results, '-o', d / 'bad-cases.csv')
            self.assertEqual(r.returncode, 2); self.assertIn('a.audit.json', r.stderr)
            audit.write_text(original)
            # A symlinked _source folder is rejected.
            moved = job / 'elsewhere'; (job / '_source').rename(moved); (job / '_source').symlink_to(moved)
            r = self.run_cli('summary', results, '-o', d / 'linked.csv')
            self.assertEqual(r.returncode, 2); self.assertIn('not a regular file', r.stderr)
            (job / '_source').unlink(); moved.rename(job / '_source')
            self.assertEqual(self.run_cli('summary', raw, '-o', d / 'reports-dir.csv').returncode, 2)
            snapshot = next(results.glob('*/_source/a.txt'))
            # Unparseable bytes still report a hash mismatch: the hash is checked before parsing.
            snapshot.write_text('not a GROUP report')
            tampered = d / 'tampered.csv'
            r = self.run_cli('summary', results, '-o', tampered)
            self.assertEqual(r.returncode, 2); self.assertIn('SHA-256', r.stderr)
            self.assertFalse(tampered.exists())
            snapshot.unlink()
            r = self.run_cli('summary', results, '-o', tampered)
            self.assertEqual(r.returncode, 2); self.assertIn('missing', r.stderr)


if __name__ == '__main__':
    unittest.main()
