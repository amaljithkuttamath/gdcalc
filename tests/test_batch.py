import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_pipeline import report, template

CLI = Path(__file__).resolve().parents[1] / 'scripts/cli.py'


class BatchTests(unittest.TestCase):
    def test_parallel_folder_failure_resume_and_changed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); raw = root / 'raw'; raw.mkdir()
            for sub in ('a', 'b'):
                (raw/sub).mkdir(); (raw/sub/'same.txt').write_text(report())
            (raw/'bad.txt').write_text('incomplete report')
            ref = root/'reference.mcdx'; template(ref); out = root/'out'
            def run(*extra):
                process = subprocess.run([sys.executable, str(CLI), 'batch', str(raw), '--recursive',
                    '--template', str(ref), '--output-dir', str(out), '--workers', '2', *extra], capture_output=True, text=True)
                return process, json.loads(process.stdout)
            first, data = run()
            self.assertEqual(first.returncode, 1, first.stderr)
            self.assertEqual((data['succeeded'], data['failed']), (2, 1))
            self.assertEqual(len(list(out.glob('*/*.mcdx'))), 2)
            again, data = run('--resume')
            self.assertEqual((data['skipped'], data['failed']), (2, 1))
            (raw/'bad.txt').write_text(report())
            fixed, data = run('--resume')
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertEqual((data['succeeded'], data['skipped'], data['failed']), (1, 2, 0))
            manifest = [json.loads(line) for line in Path(data['manifest']).read_text().splitlines()]
            self.assertTrue(all('source_sha256' in row for row in manifest))
            # report() raises review items; every converted or verified row counts them.
            self.assertTrue(all(row['open_checks'] > 0 and row['check_errors'] == 0
                                for row in manifest if row['status'] != 'failed'))
            # Calculation artifacts are part of the resume contract too.
            rendered = next(out.glob('*/*.html')); saved = rendered.read_bytes(); rendered.write_bytes(b'corrupt')
            broken, data = run('--resume')
            self.assertEqual(broken.returncode, 1); self.assertEqual(data['failed'], 1)
            rendered.write_bytes(saved)
            # Resume must not accept damaged files merely because a manifest says done.
            next(out.glob('*/*.mcdx')).write_bytes(b'corrupt')
            corrupt, data = run('--resume')
            self.assertEqual(corrupt.returncode, 1)
            self.assertEqual(data['failed'], 1)

    def test_python_api_resume_with_tuple_cases(self):
        from mcdxkit.batch import convert_batch
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'a.txt'; source.write_text(report())
            ref = root/'reference.mcdx'; template(ref); out = root/'out'
            first = convert_batch([source], ref, out, cases=(1, 7))
            self.assertEqual((first['succeeded'], first['failed']), (1, 0))
            again = convert_batch([source], ref, out, cases=(1, 7), resume=True)
            self.assertEqual((again['skipped'], again['failed']), (1, 0))

    def test_explicit_files_and_output_subtree_exclusion(self):
        from mcdxkit.batch import discover
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); out = root/'out'; out.mkdir()
            source = root/'a.txt'; source.write_text(report())
            (out/'snapshot.txt').write_text(report())
            self.assertEqual(discover([root, source], out, recursive=True), [source.resolve()])

    def test_new_check_version_reruns_review_on_resume(self):
        from unittest import mock
        from mcdxkit.batch import convert_batch
        from mcdxkit.review.checks.ratios import RatioOutlier
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'r.txt'; source.write_text(report())
            ref = root / 'reference.mcdx'; template(ref); out = root / 'out'
            first = convert_batch([source], ref, out)
            self.assertEqual(first['succeeded'], 1)
            self.assertEqual(convert_batch([source], ref, out, resume=True)['skipped'], 1)
            with mock.patch.object(RatioOutlier, 'version', '3'):
                again = convert_batch([source], ref, out, resume=True)
            self.assertEqual((again['succeeded'], again['skipped']), (1, 0))
            rows = [json.loads(line) for line in Path(again['manifest']).read_text().splitlines()]
            self.assertNotEqual(rows[0]['job_id'], rows[-1]['job_id'])
            audit = json.loads(Path(rows[-1]['audit']).read_text())
            self.assertIn({'id': 'ratio_outlier', 'version': '3'},
                          [{k: c[k] for k in ('id', 'version')} for c in audit['review_checks']['checks_run']])
            self.assertEqual(convert_batch([source], ref, out, resume=True, checks='none')['succeeded'], 1)


FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'review'


class BatchSuggestTests(unittest.TestCase):
    """--suggest is advisory: it adds manifest/table content and never changes cases or outputs."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name); self.raw = self.root / 'raw'; self.raw.mkdir()
        # A mislabelled STR case (flagged) and a report whose EXT-I name defeats the default rule.
        for name in ('seed505_mislabel_str_as_ser.txt', 'round2_seed320000_clean.txt'):
            (self.raw / name).write_bytes((FIXTURES / name).read_bytes())
        self.ref = self.root / 'reference.mcdx'; template(self.ref)

    def batch(self, out, **options):
        from mcdxkit.batch import convert_batch
        rows = []
        counts = convert_batch([self.raw], self.ref, self.root / out, overrides={'n_z': 16}, check_rows=rows, **options)
        manifest = [json.loads(line) for line in Path(counts['manifest']).read_text().splitlines()]
        return counts, {Path(r['source']).name: r for r in manifest}, {r['source']: r for r in rows}

    def outputs(self, out):
        return {p.relative_to(self.root / out).as_posix(): p.read_bytes()
                for p in sorted((self.root / out).glob('*/*')) if p.suffix in ('.mcdx', '.cpd', '.html')}

    def test_suggestions_recorded_and_outputs_identical(self):
        plain, plain_rows, plain_table = self.batch('plain')
        counts, rows, table = self.batch('suggest', suggest=True)
        self.assertEqual((counts['succeeded'], counts['failed']), (plain['succeeded'], plain['failed']))
        self.assertEqual((counts['succeeded'], counts['failed']), (1, 1))
        # Same job ids, same worksheet bytes, same cases: nothing was applied.
        self.assertTrue(self.outputs('plain'))
        self.assertEqual(self.outputs('plain'), self.outputs('suggest'))
        mislabel = rows['seed505_mislabel_str_as_ser.txt']
        self.assertEqual(mislabel['job_id'], plain_rows['seed505_mislabel_str_as_ser.txt']['job_id'])
        self.assertEqual(mislabel['cases'], plain_rows['seed505_mislabel_str_as_ser.txt']['cases'])
        self.assertNotIn('suggestions', plain_rows['seed505_mislabel_str_as_ser.txt'])
        advice = mislabel['suggestions']
        self.assertEqual(advice['selected_cases'], mislabel['cases'])
        self.assertEqual({c['id']: c['category'] for c in advice['case_suggestions']['cases']}[3], 'service')
        self.assertIn('service_axial_above_strength', {f['rule'] for f in advice['flags']})
        self.assertEqual(advice['differences'], [{'case': 3, 'name': 'SER-IX', 'action': 'add',
                                                  'reasons': ['flag service_axial_above_strength']}])
        # A failed default selection still gets suggestions: the cases to pass with --cases.
        failed = rows['round2_seed320000_clean.txt']
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['suggestions']['selected_cases'], [])
        self.assertIn('Case classification unavailable', failed['suggestions']['selection_required'])
        self.assertEqual([d['case'] for d in failed['suggestions']['differences']], [3, 6, 7])
        self.assertEqual(table['round2_seed320000_clean.txt']['suggested_cases'],
                         'add 3 STR-I [strength 1.00]; add 6 STR-I-MIN [strength 1.00]; add 7 STR-V-W225 [strength 1.00]')
        self.assertEqual(counts['suggestions'], {'reports_with_suggestions': 2, 'reports_unavailable': 0, 'history': None})
        # The new column is last, and only present with --suggest.
        with open(counts['checks']['table'], encoding='utf-8') as stream:
            self.assertEqual(next(csv.reader(stream))[-2:], ['note', 'suggested_cases'])
        with open(plain['checks']['table'], encoding='utf-8') as stream:
            self.assertNotIn('suggested_cases', next(csv.reader(stream)))
        self.assertNotIn('suggested_cases', next(iter(plain_table.values())))

    def test_explicit_cases_report_drop_and_resume_triages_without_reconverting(self):
        first, _, _ = self.batch('out', cases=[2, 3])
        before = self.outputs('out')
        counts, rows, table = self.batch('out', cases=[2, 3], resume=True, suggest=True)
        self.assertEqual((counts['skipped'], counts['succeeded']), (first['succeeded'], 0))
        self.assertEqual(self.outputs('out'), before)
        mislabel = rows['seed505_mislabel_str_as_ser.txt']
        self.assertEqual(mislabel['status'], 'skipped')
        self.assertEqual(mislabel['suggestions']['selected_cases'], [2, 3])
        # Case 3 (SER-IX) was selected explicitly; the classifier reads it as service.
        self.assertIn({'case': 3, 'name': 'SER-IX', 'action': 'drop', 'reasons': ['service 1.00']},
                      mislabel['suggestions']['differences'])
        self.assertIn('drop 3 SER-IX [service 1.00]', table['seed505_mislabel_str_as_ser.txt']['suggested_cases'])

    def test_history_is_read_once_and_reaches_workers(self):
        history = self.root / 'reviewed'; (history / 'job').mkdir(parents=True)
        (history / 'job' / 'w.audit.json').write_text(json.dumps(
            {'cases': [1], 'case_names': {'1': 'Ultimate A', '2': 'Working B'}}))
        counts, rows, _ = self.batch('out', suggest=True, history=history, workers=2)
        self.assertEqual(counts['suggestions']['history'], {'examples': 2, 'skipped': 0})
        for row in rows.values():
            self.assertEqual(row['suggestions']['case_suggestions']['trained_on']['history'], 2)

    def test_invalid_suggest_setups_are_rejected(self):
        from mcdxkit.batch import convert_batch
        out = self.root / 'out'
        for options, message in (({'history': self.root}, 'only with --suggest'),
                                 ({'suggest': True, 'checks': 'none'}, 'case-name classifier'),
                                 ({'suggest': True, 'history': self.root}, 'must not overlap')):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                convert_batch([self.raw], self.ref, out, **options)
        self.assertFalse(out.exists())

    def test_cli_exit_codes_unchanged(self):
        def run(*extra):
            return subprocess.run([sys.executable, str(CLI), 'batch', str(self.raw), '--template', str(self.ref),
                                   '--output-dir', str(self.root / 'out'), '--set', 'n_z=16', '--quiet', *extra],
                                  capture_output=True, text=True)
        done = run('--suggest', '--workers', '1')
        self.assertEqual(done.returncode, 1, done.stderr)  # the unresolved report still fails
        self.assertEqual(json.loads(done.stdout)['suggestions']['reports_with_suggestions'], 2)
        self.assertIn('Case suggestions: 2 of 2 reports differ from the selection used', done.stderr)
        self.assertIn('round2_seed320000_clean.txt: suggest add 3 STR-I', done.stderr)
        self.assertEqual(run('--history', str(self.root)).returncode, 2)
        self.assertEqual(run('--suggest', '--checks', 'none').returncode, 2)
