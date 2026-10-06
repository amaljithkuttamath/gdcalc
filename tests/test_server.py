"""Exercise the actual loopback HTTP boundary using synthetic engineering inputs."""
import csv
import http.client
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from test_pipeline import report, template
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
                self.assertEqual(call('POST', '/api/login', {'access_token': 'wrong'})[0], 401)
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
