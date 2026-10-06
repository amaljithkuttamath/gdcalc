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
