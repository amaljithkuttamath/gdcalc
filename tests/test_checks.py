"""Check-outcome extraction from CalcpadCE pages, with synthetic fixtures only."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from lxml import etree as E

from gdcalc import batch, calcpad, checks, engine, mcdx
from gdcalc.service import Session
from test_calcpad import apply, definition, worksheet
from test_pipeline import report, template

CLI = Path(__file__).resolve().parents[1] / 'scripts/cli.py'


def page(*equations):
    """Minimal page in the shape CalcpadCE renders (see calcpad.calculate)."""
    body = ''.join(f'<p id="line-{n}" class="line">{e}</p>' for n, e in enumerate(equations, 1))
    return '<!doctype html><html><body><div>' + body + '</div></body></html>'


def check_template(path, capacity):
    """Synthetic template plus a capacity input and one rendered axial check."""
    template(path)
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = E.fromstring(parts['mathcad/worksheet.xml'])
    regions = root.find('{' + mcdx.W + '}regions')
    for index, expression in enumerate([
            definition('P_cap', mcdx.quantity(mcdx.real(capacity), 'kip')),
            definition('axial_check', apply('lessOrEqual', mcdx.ident('P_u'), mcdx.ident('P_cap')))]):
        region = E.SubElement(regions, '{' + mcdx.W + '}region', {'region-id': str(60 + index), 'top': str(480 + 40 * index), 'left': '10'})
        E.SubElement(region, '{' + mcdx.W + '}math').append(expression)
    parts['mathcad/worksheet.xml'] = E.tostring(root)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in parts.items():
            z.writestr(name, content)


class ExtractTests(unittest.TestCase):
    def test_comparisons_report_outcome_expression_and_simple_ratio(self):
        found, summary = checks.extract(page(
            '<span class="eq"><var>c</var> = <var>P_u</var> ≤ <var>P_r</var> = 145 <i>kip</i> ≤ 200 <i>kip</i> = 1</span>',
            '<span class="eq"><var>d</var> = <var>P_r</var> ≥ <var>P_u</var> = 100 <i>kip</i> ≥ 150 <i>kip</i> = 0</span>'))
        self.assertEqual([c['name'] for c in found], ['c', 'd'])
        self.assertEqual(found[0]['expression'], 'P_u ≤ P_r')
        self.assertEqual(found[0]['substituted'], '145 kip ≤ 200 kip')
        self.assertTrue(found[0]['passed']); self.assertFalse(found[1]['passed'])
        self.assertAlmostEqual(found[0]['ratio'], 0.725)
        # For ≥ the right-hand side is the demand.
        self.assertAlmostEqual(found[1]['ratio'], 1.5)
        self.assertEqual(found[1]['line'], 2)
        self.assertEqual(summary['status'], 'failures')
        self.assertEqual((summary['total'], summary['passed'], summary['failed']), (2, 1, 1))
        self.assertEqual(summary['failed_checks'], ['d'])
        self.assertEqual(summary['governing']['name'], 'd')

    def test_ratio_is_not_guessed_for_compound_mismatched_or_signed_operands(self):
        found, summary = checks.extract(page(
            '<span class="eq"><var>a</var> = 145 <i>kip</i> ≤ 0.75 · 200 <i>kip</i> = 1</span>',
            '<span class="eq"><var>b</var> = 10 <i>in</i> ≤ 2 <i>ft</i> = 1</span>',
            '<span class="eq"><var>s</var> = 2 + 3 <i>kip</i> ≤ 4 + 3 <i>kip</i> = 1</span>',
            '<span class="eq"><var>m</var> = 2 · 3 ≤ 4 · 3 = 1</span>',
            '<span class="eq"><var>c</var> = 0 &lt; 3 and 3 ≤ 4 = 1</span>',
            '<span class="eq"><var>d</var> = 5 <i>kip</i> ≤ -2.5×10<sup>-6</sup> <i>kip</i> = 0</span>',
            '<span class="eq"><var>e</var> = <var>x</var> ≡ 0.75 = 0.75 ≡ 0.75 = 1</span>'))
        self.assertEqual(len(found), 7)
        self.assertTrue(all(c['ratio'] is None for c in found))
        self.assertIsNone(summary['governing'])
        self.assertEqual(found[5]['substituted'], '5 kip ≤ -2.5×10^(-6) kip')

    def test_fraction_and_exponent_operands(self):
        found, _ = checks.extract(page(
            '<span class="eq"><var>r</var> = <span class="dvc"><var>a</var><span class="dvl"></span><var>b</var></span> ≤ 1'
            ' = 9.5×10<sup>-1</sup> ≤ 1 = 1</span>'))
        self.assertEqual(found[0]['expression'], '(a)/(b) ≤ 1')
        self.assertAlmostEqual(found[0]['ratio'], 0.95)
        found, _ = checks.extract(page('<span class="eq"><var>m</var> = 300 <i>kip</i>·<i>in</i> ≤ 400 <i>kip</i>·<i>in</i> = 1</span>'))
        self.assertEqual((found[0]['ratio'], found[0]['unit']), (0.75, 'kip·in'))

    def test_non_comparisons_and_string_messages_are_not_checks(self):
        document = page('<span class="eq"><var>n</var> = 1</span>',
                        '<span class="eq"><var>k</var> = <var>a</var> + <var>b</var> = 0 + 1 = 1</span>',
                        'status', 'OK', 'NG')
        found, summary = checks.extract(document)
        self.assertEqual(found, [])
        self.assertEqual(summary['status'], checks.NO_CHECKS)
        self.assertEqual(summary['total'], 0)
        self.assertIsNone(summary['governing'])

    def test_evaluated_expression_takes_preceding_label_and_region(self):
        found, _ = checks.extract(page('Expression', '<span class="eq"><var>a</var> &gt; <var>b</var> = 3 &gt; 2 = 1</span>'),
                                  {'7': 1, '3': 0})
        self.assertEqual((found[0]['name'], found[0]['region_id'], found[0]['ratio']), ('Expression', '7', 2 / 3))


class EngineCheckTests(unittest.TestCase):
    def test_real_calcpad_comparisons_are_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'checks.mcdx'
            worksheet(source, [
                definition('P_u', mcdx.quantity(mcdx.real(145), 'kip')),
                definition('P_r', mcdx.quantity(mcdx.real(200), 'kip')),
                definition('ok', apply('lessOrEqual', mcdx.ident('P_u'), mcdx.ident('P_r'))),
                definition('bad', apply('greaterOrEqual', mcdx.ident('P_u'), apply('mult', mcdx.real(2), mcdx.ident('P_r'))))])
            evidence = calcpad.calculate(source, root / 'checks.cpd', root / 'checks.html')
            found, summary = checks.extract((root / 'checks.html').read_text(), evidence['region_lines'])
        self.assertEqual([(c['name'], c['passed'], c['region_id']) for c in found], [('ok', True, '2'), ('bad', False, '3')])
        self.assertAlmostEqual(found[0]['ratio'], 145 / 200)
        self.assertIsNone(found[1]['ratio'])
        self.assertEqual(summary['governing']['name'], 'ok')

    def test_audit_records_checks_and_no_checks_found(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); raw = root / 'report.txt'; raw.write_text(report())
            plain = root / 'plain.mcdx'; template(plain)
            result = engine.convert(raw, plain, root / 'plain-out.mcdx')
            self.assertEqual(result['checks'], [])
            self.assertEqual(result['check_summary']['status'], 'no checks found')
            for capacity, passed in ((200, True), (100, False)):
                ref = root / f'ref-{capacity}.mcdx'; check_template(ref, capacity)
                result = engine.convert(raw, ref, root / f'out-{capacity}.mcdx')
                audit = json.loads((root / f'out-{capacity}.audit.json').read_text())
                self.assertEqual(audit['checks'], result['checks'])
                (check,) = audit['checks']
                # P_u = 140 kip envelope + 5 kip downdrag (see PackageTests).
                self.assertEqual((check['name'], check['passed']), ('axial_check', passed))
                self.assertEqual(check['substituted'], f'145 kip ≤ {capacity} kip')
                self.assertAlmostEqual(check['ratio'], 145 / capacity)
                self.assertEqual(audit['check_summary']['failed'], 0 if passed else 1)

    def test_service_returns_checks_and_marks_older_audits_unrecorded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); ref = root / 'reference.mcdx'; check_template(ref, 100)
            session = Session(ref, root / 'results')
            try:
                uploaded = session.upload('loads.txt', 'report', report().encode())
                converted = session.operation('/api/convert', {'id': uploaded['id']})
                self.assertEqual(converted['check_summary']['failed_checks'], ['axial_check'])
                self.assertAlmostEqual(converted['check_summary']['governing']['ratio'], 1.45)
                (saved,) = session.history()
                self.assertEqual(saved['check_summary'], converted['check_summary'])
                audit = Path(converted['output']).with_suffix('.audit.json')
                legacy = json.loads(audit.read_text()); del legacy['checks'], legacy['check_summary']
                audit.write_text(json.dumps(legacy))
                (saved,) = session.history()
                self.assertIsNone(saved['check_summary']); self.assertIsNone(saved['checks'])
            finally:
                session.temp.cleanup()


class BatchCheckTests(unittest.TestCase):
    def test_batch_table_reports_governing_ratio_failures_and_conversion_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); raw = root / 'raw'; raw.mkdir()
            (raw / 'good.txt').write_text(report()); (raw / 'bad.txt').write_text('incomplete report')
            ref = root / 'reference.mcdx'; check_template(ref, 100); out = root / 'out'
            def run(*extra):
                process = subprocess.run([sys.executable, str(CLI), 'batch', str(raw), '--template', str(ref),
                                          '--output-dir', str(out), '--workers', '1', '--quiet', *extra],
                                         capture_output=True, text=True)
                return process, json.loads(process.stdout)
            process, data = run()
            self.assertEqual(process.returncode, 1, process.stderr)
            self.assertEqual(data['checks']['reports_with_failures'], 1)
            with Path(data['checks']['table']).open(encoding='utf-8') as stream:
                rows = {r['source']: r for r in csv.DictReader(stream)}
            self.assertEqual(rows['good.txt']['governing_dc'], '1.450')
            self.assertEqual(rows['good.txt']['failed_checks'], 'axial_check')
            self.assertEqual(rows['bad.txt']['note'], 'conversion failed')
            self.assertIn('good.txt: failed axial_check', process.stderr)
            first = data['checks']['table']
            # Resume reads recorded outcomes and writes a new table beside the old one.
            process, data = run('--resume')
            self.assertNotEqual(data['checks']['table'], first)
            self.assertTrue(Path(first).is_file())
            self.assertEqual(data['checks']['rows'][1]['status'], 'skipped')
            self.assertEqual(data['checks']['rows'][1]['governing_dc'], '1.450')

    def test_table_cells_cannot_start_spreadsheet_formulas(self):
        row = batch.check_row({'source': '/x/r.txt', 'status': 'succeeded', 'check_summary': {
            'total': 1, 'passed': 0, 'failed': 1, 'failed_checks': ['=HYPERLINK("x")'],
            'governing': {'name': '+cmd', 'ratio': 2.0, 'passed': False, 'region_id': '1'}}})
        with tempfile.TemporaryDirectory() as folder:
            path = batch.write_check_table(Path(folder), [row])
            with path.open(encoding='utf-8') as stream:
                saved = next(csv.DictReader(stream))
        self.assertEqual(saved['failed_checks'], '\'=HYPERLINK("x")')
        self.assertEqual(saved['governing_check'], "'+cmd")
        self.assertEqual(batch.check_row({'source': 'a', 'status': 'succeeded', 'check_summary': None})['note'],
                         'checks not recorded for this output')


if __name__ == '__main__':
    unittest.main()
