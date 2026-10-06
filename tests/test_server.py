"""Exercise the actual loopback HTTP boundary using synthetic engineering inputs."""
import csv
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from urllib.parse import urlencode

from test_pipeline import report, template
from mcdxkit import server as server_module
from mcdxkit.server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.template = self.root / 'reference.mcdx'
        template(self.template)
        self.server = create_server(port=0, template=self.template, output_dir=self.root / 'results')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.token = self.request('GET', '/api/session', authenticated=False)[1]['token']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def request(self, method, path, data=None, headers=None, authenticated=True):
        h = {'X-MCDXKit-Token': self.token} if authenticated else {}
        h.update(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            h['Content-Type'] = 'application/json'
        elif data is not None:
            h.setdefault('Content-Type', 'application/octet-stream')
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, data, h)
        response = conn.getresponse()
        raw = response.read()
        value = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw
        conn.close()
        return response.status, value

    def upload(self, name='loads.gp11t', content=None, kind='report'):
        return self.request('POST', '/api/upload?' + urlencode({'name': name, 'kind': kind}),
                            report().encode() if content is None else content)

    def test_inspect_convert_download_and_validate_native_formulas(self):
        status, uploaded = self.upload()
        self.assertEqual(status, 200, uploaded)
        self.assertEqual(uploaded['inspection']['selected_cases'], [1, 7])
        status, inspected = self.request('POST', '/api/inspect', {'id': uploaded['id'], 'cases': [1]})
        self.assertEqual(inspected['envelope']['P'], 120)
        status, preview = self.request('POST', '/api/preview', {'id': uploaded['id'], 'cases': [1, 7]})
        self.assertEqual(status, 200, preview)
        self.assertTrue(preview['preview'])
        self.assertEqual(len([c for c in preview['diff']['changes'] if c['kind'] == 'changed']), 4)
        self.assertFalse((self.root / 'results').exists())
        _, source = self.request('POST', '/api/view', {'id': uploaded['id']})
        self.assertEqual(source['text'], report())
        status, converted = self.request('POST', '/api/convert', {'id': uploaded['id'], 'cases': [1, 7]})
        self.assertEqual(status, 200, converted)
        self.assertFalse(converted['validation']['native_execution_verified'])
        self.assertEqual(converted['validation']['cached_results'], 0)
        self.assertTrue(converted['calculation']['calculated'])
        for key in ('open_worksheet', 'calculated_worksheet'):
            self.assertEqual(self.request('GET', '/api/download/' + converted[key]['id'])[0], 200)
        _, raw = self.request('GET', '/api/download/' + converted['worksheet']['id'])
        dest = self.root / 'download.mcdx'
        dest.write_bytes(raw)
        from evaluate_fixture import evaluate
        self.assertEqual(evaluate(dest)['P_u'], 145)
        _, audit = self.request('GET', '/api/download/' + converted['audit']['id'])
        self.assertEqual(json.loads(audit)['envelope']['P'], 140)
        _, validation = self.request('POST', '/api/validate', {'id': converted['worksheet']['id']})
        self.assertEqual(validation['cached_results'], 0)
        _, view = self.request('POST', '/api/view', {'id': converted['worksheet']['id']})
        self.assertTrue(any('P_u :=' in r.get('expression', '') for r in view['regions']))
        self.assertIn('145', view['calculated_html'])
        self.assertEqual(view['calculation_engine'], 'CalcpadCE')
        _, changes = self.request('POST', '/api/diff', {'id': converted['worksheet']['id']})
        self.assertEqual(changes, converted['diff'])
        self.assertEqual(len(list((self.root / 'results').glob('*/*.mcdx'))), 1)
        # A fresh registry reconstructs download links from complete pairs only.
        self.server.state.files.clear()
        status, history = self.request('GET', '/api/history')
        self.assertEqual(status, 200)
        self.assertEqual(len(history), 1)
        self.assertEqual(self.request('GET', '/api/download/' + history[0]['worksheet']['id'])[1], raw)

    def test_standards_register_is_bound_to_actual_calculated_artifacts(self):
        _, uploaded = self.upload()
        _, converted = self.request('POST', '/api/convert', {'id': uploaded['id'], 'cases': [1, 7]})
        key = converted['worksheet']['id']
        status, result = self.request('POST', '/api/standards', {'id': key})
        self.assertEqual(status, 200, result)
        register = result['register']
        self.assertEqual(register['values'][0]['quantity'], 140)
        self.assertEqual(register['rules'], [])
        self.assertFalse(result['assessment']['engineering_approval_verified'])
        self.assertEqual(self.request('POST', '/api/standards', {'id': key, 'register': register})[0], 200)
        register['values'][0]['source_id'] = []
        self.assertEqual(self.request('POST', '/api/standards', {'id': key, 'register': register})[0], 400)
        self.assertEqual(self.request('POST', '/api/standards', {'id': key}, authenticated=False)[0], 403)
        artifact = self.server.state.get(key, ['worksheet'])['path']
        artifact.with_suffix('.html').write_text('Changed result')
        self.assertEqual(self.request('POST', '/api/standards', {'id': key})[0], 400)

    def test_untrusted_requests_paths_and_sizes_are_rejected(self):
        self.assertEqual(self.request('POST', '/api/upload?name=x.txt&kind=report', b'x', authenticated=False)[0], 403)
        for headers in [{'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}]:
            self.assertEqual(self.request('GET', '/api/session', headers=headers, authenticated=False)[0], 403)
        self.assertEqual(self.upload('../escape.txt')[0], 400)
        self.assertEqual(self.upload('x.xlsm')[0], 400)
        self.assertEqual(self.upload(content=b'not a report')[0], 400)
        self.assertEqual(self.request('POST', '/api/upload?name=x.txt&kind=report', b'',
                                      {'Content-Length': str(40 * 1024 * 1024)})[0], 413)
        self.assertEqual(self.request('GET', '/api/download/../../reference.mcdx')[0], 404)

    def test_template_upload_duplicate_names_and_invalid_selection(self):
        _, first = self.upload()
        _, second = self.upload()
        self.assertNotEqual(first['id'], second['id'])
        status, t = self.upload('other.mcdx', self.template.read_bytes(), 'template')
        self.assertEqual(status, 200, t)
        self.assertEqual(self.request('POST', '/api/convert', {'id': first['id'], 'cases': []})[0], 400)
        self.assertEqual(self.request('POST', '/api/convert', {'id': first['id'], 'cases': [99]})[0], 400)
        self.assertEqual(self.request('POST', '/api/convert', {'id': first['id'], 'cases': [True]})[0], 400)
        a = self.request('POST', '/api/convert', {'id': first['id'], 'template_id': t['id']})
        b = self.request('POST', '/api/convert', {'id': second['id'], 'template_id': t['id']})
        self.assertEqual(a[0], 200, a)
        self.assertEqual(b[0], 200, b)
        self.assertNotEqual(a[1]['worksheet']['id'], b[1]['worksheet']['id'])

    def test_review_decisions_reach_the_preview_and_audit_through_http(self):
        fixture = Path(__file__).parent / 'fixtures' / 'review' / 'seed505_mislabel_str_as_ser.txt'
        status, uploaded = self.upload('pile-cap.txt', fixture.read_bytes())
        self.assertEqual(status, 200, uploaded)
        import hashlib
        self.assertEqual(uploaded['source_sha256'], hashlib.sha256(fixture.read_bytes()).hexdigest())
        flag = uploaded['inspection']['review_checks']['flags'][0]
        self.assertEqual((flag['rule'], flag['case'], flag['component']), ('service_axial_above_strength', 3, 'P'))
        decision = {'rule': flag['rule'], 'case': 3, 'component': 'P', 'decision': 'included_case',
                    'note': None, 'decided_at': '2026-10-06T09:30:00.000Z'}
        base = {'id': uploaded['id'], 'cases': [2, 3, 4], 'overrides': {'n_z': 9}}
        status, preview = self.request('POST', '/api/preview', {**base, 'review_decisions': [decision]})
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview['review_checks']['decisions'], [decision])
        noted = lambda result: any('Automated input checks' in (r.get('text') or '') for r in
                                   self.request('POST', '/api/view', {'id': result['worksheet']['id']})[1]['regions'])
        self.assertTrue(noted(preview))
        # Without decisions nothing about the review reaches the worksheet or the audit.
        status, plain = self.request('POST', '/api/convert', base)
        self.assertEqual(status, 200, plain)
        self.assertNotIn('decisions', plain['review_checks'])
        self.assertFalse(noted(plain))
        status, converted = self.request('POST', '/api/convert', {**base, 'review_decisions': [decision]})
        self.assertEqual(status, 200, converted)
        _, audit = self.request('GET', '/api/download/' + converted['audit']['id'])
        self.assertEqual(json.loads(audit)['review_checks']['decisions'], [decision])
        # Malformed or unmatched decisions are rejected before any output is written.
        written = sorted((self.root / 'results').rglob('*.mcdx'))
        for bad in ([dict(decision, decision='approve')], [dict(decision, case=5)], 'yes'):
            status, error = self.request('POST', '/api/convert', {**base, 'review_decisions': bad})
            self.assertEqual(status, 400, error)
            # The browser retries the preview without decisions on exactly this wording.
            self.assertRegex(error['error'], '(?i)review[ _]decision')
        self.assertEqual(sorted((self.root / 'results').rglob('*.mcdx')), written)

    def test_many_review_decisions_with_notes_fit_a_preview_request(self):
        # Every flag on a card carries the card's note, so a few long notes exceeded the old 16 KiB limit (413).
        _, uploaded = self.upload()
        note = 'é' * 500
        decisions = [{'rule': 'my_check', 'case': n, 'component': 'P', 'decision': 'kept_service',
                      'note': note, 'decided_at': '2026-10-06T09:30:00Z'} for n in range(1, 31)]
        body = {'id': uploaded['id'], 'cases': [1, 7], 'review_decisions': decisions}
        self.assertGreater(len(json.dumps(body).encode()), 16384)
        status, preview = self.request('POST', '/api/preview', body)
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(preview['review_checks']['decisions']), 30)
        self.assertTrue(all(d['unverified'] for d in preview['review_checks']['decisions']))
        # Identifiers of decisions that cannot be checked are still bounded before they reach the audit.
        for bad in ({'rule': 'x' * 70}, {'rule': 'Not an id'}, {'component': 'P' * 65}):
            status, error = self.request('POST', '/api/preview', {**body, 'review_decisions': [{**decisions[0], **bad}]})
            self.assertEqual(status, 400, error)
            self.assertRegex(error['error'], '(?i)review[ _]decision')
        status, error = self.request('POST', '/api/inspect', {'id': uploaded['id'], 'pad': 'x' * 20000})
        self.assertEqual(status, 413, error)

    def test_summary_csv_for_uploaded_reports(self):
        _, first = self.upload('a.txt')
        _, second = self.upload('b.gp11t', report().replace('Max. .2 .3 400 180 14 7', 'Max. .2 .3 400 180 14 9').encode())
        reports = [{'id': first['id'], 'cases': [1, 7]}, {'id': second['id']}]
        status, value = self.request('POST', '/api/summary', {'reports': reports, 'load_source': 'effects'})
        self.assertEqual(status, 200, value)
        self.assertEqual((value['reports'], value['rows']), (2, 6))
        rows = {(r['report'], r['case_id']): r for r in csv.DictReader(io.StringIO(value['csv']))}
        self.assertEqual(rows['b.gp11t', '1']['governs'], 'Vz')
        self.assertEqual(rows['a.txt', '7']['P_kip'], '140')
        self.assertFalse((self.root / 'results').exists())
        self.assertEqual(self.request('POST', '/api/summary', {'reports': reports[:1]})[0], 400)
        self.assertEqual(self.request('POST', '/api/summary', {'reports': [reports[0], reports[0]]})[0], 400)
        _, third = self.upload('copy.txt')
        status, value = self.request('POST', '/api/summary', {'reports': reports + [{'id': third['id'], 'cases': [1, 7]}]})
        self.assertEqual(status, 200, value)
        self.assertEqual((value['reports'], value['rows'], value['duplicates_skipped']), (2, 6, ['copy.txt']))
        for bad in (['x'], {'a': 1}, None, 5):
            self.assertEqual(self.request('POST', '/api/summary', {'reports': [reports[0], {'id': bad}]})[0], 400)
        self.assertEqual(self.request('POST', '/api/summary', {'reports': [reports[0], {'id': 'missing'}]})[0], 404)
        self.assertEqual(self.request('POST', '/api/summary', {'reports': [reports[0], {'id': second['id'], 'cases': [99]}]})[0], 400)
        self.assertEqual(self.request('POST', '/api/summary', {'reports': reports, 'load_source': 'global'})[0], 400)
        self.assertEqual(self.request('POST', '/api/summary', {'reports': reports}, authenticated=False)[0], 403)

    def test_static_ui_and_missing_template_error(self):
        status, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'webkitdirectory', html)
        self.assertEqual(self.request('GET', '/app.js')[0], 200)
        for name in ('regular', 'medium', 'semibold'):
            status, font = self.request('GET', f'/fonts/plex-{name}.ttf', authenticated=False)
            self.assertEqual(status, 200)
            self.assertTrue(font.startswith(b'\x00\x01\x00\x00'))
        self.assertEqual(self.request('GET', '/fonts/unlisted.ttf')[0], 404)
        self.assertEqual(self.request('GET', '/fonts/%2e%2e%2fserver.py')[0], 404)
        self.assertEqual(self.request('GET', '/../../pyproject.toml')[0], 404)
        self.server.state.template = None
        _, uploaded = self.upload()
        status, error = self.request('POST', '/api/convert', {'id': uploaded['id']})
        self.assertEqual(status, 400)
        self.assertIn('template', error['error'].lower())


class DeploymentTests(unittest.TestCase):
    def test_network_mode_requires_secret_and_https_remote_origin(self):
        from mcdxkit.server import check_configuration
        with self.assertRaises(ValueError): check_configuration('0.0.0.0', None, None)
        with self.assertRaises(ValueError): check_configuration('0.0.0.0', 'https://example.com', 'short')
        with self.assertRaises(ValueError): check_configuration('0.0.0.0', 'http://example.com', 'x' * 32)
        check_configuration('0.0.0.0', 'https://example.com', 'x' * 32)

    def test_cloud_auth_cookie_csrf_and_health(self):
        with tempfile.TemporaryDirectory() as folder:
            server = create_server(port=0, host='0.0.0.0', public_url='https://calc.example.test',
                                   access_token='test-only-' + 'x' * 32, output_dir=folder)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def call(method, route, data=None, headers=None):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                h = {'Host': 'calc.example.test', **(headers or {})}
                if data is not None:
                    h['Content-Type'] = 'application/json'; data = json.dumps(data)
                conn.request(method, route, data, h)
                r = conn.getresponse(); body = r.read(); status = r.status; cookie = r.getheader('Set-Cookie')
                conn.close()
                return status, json.loads(body), cookie
            try:
                self.assertEqual(call('GET', '/healthz')[0], 200)
                self.assertEqual(call('GET', '/api/session')[0], 401)
                with mock.patch.object(server_module, 'LOGIN_DELAY_STEP', 0.01), mock.patch.object(server_module, 'LOGIN_DELAY_MAX', 0.05):
                    for _ in range(12):
                        start = time.monotonic()
                        self.assertEqual(call('POST', '/api/login', {'access_token': 'wrong'})[0], 401)
                    self.assertGreaterEqual(time.monotonic() - start, 0.05)
                status, _, cookie = call('POST', '/api/login', {'access_token': 'test-only-' + 'x' * 32})
                self.assertEqual(status, 200)
                for flag in ['HttpOnly', 'Secure', 'SameSite=strict']:
                    self.assertIn(flag, cookie)
                h = {'Cookie': cookie.split(';')[0]}
                status, info, _ = call('GET', '/api/session', headers=h)
                self.assertEqual(status, 200); self.assertTrue(info['network'])
                self.assertEqual(call('GET', '/api/history', headers=h)[0], 403)
                h['X-MCDXKit-Token'] = info['token']
                self.assertEqual(call('GET', '/api/history', headers=h)[0], 200)
                h['Origin'] = 'https://attacker.example'
                self.assertEqual(call('GET', '/api/history', headers=h)[0], 403)
            finally:
                server.shutdown(); thread.join(); server.server_close()


if __name__ == '__main__':
    unittest.main()
