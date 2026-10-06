"""Assistant boundaries with a fake model client: no network, no credentials."""
import json
import tempfile
import threading
import unittest
import http.client
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlencode

from test_pipeline import report, template
from gdcalc import assist, engine, group_report
from gdcalc.server import create_server


class FakeClient:
    """Records each request and answers with a prepared parsed_output."""
    def __init__(self, *answers, stop_reason='end_turn'):
        self.answers = list(answers)
        self.requests = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        return SimpleNamespace(stop_reason=self.stop_reason, model=kwargs['model'],
                               parsed_output=kwargs['output_format'](**answer))


def advice(recommended):
    return {'summary': 'STR cases are strength limit states.', 'recommended_cases': recommended,
            'cases': [{'id': 1, 'category': 'strength', 'reason': 'STR-I'},
                      {'id': 2, 'category': 'service', 'reason': 'SER-I'},
                      {'id': 7, 'category': 'strength', 'reason': 'STR-V'},
                      {'id': 99, 'category': 'strength', 'reason': 'not in report'}]}


REVIEW = {'summary': 'Axial compression governs.', 'governing': 'P = 140 kip from case 7',
          'findings': [{'severity': 'info', 'title': 'Single case', 'detail': 'Case 7 governs P.', 'evidence': '140 kip'},
                       {'severity': 'critical', 'title': 'Downdrag', 'detail': 'Inherited.', 'evidence': 'P_downdrag = 5 kip'}],
          'verify_next': ['Confirm downdrag for this site.']}


class AssistTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.report = self.root / 'loads.txt'
        self.report.write_text(report())
        self.template = self.root / 'reference.mcdx'
        template(self.template)

    def tearDown(self):
        self.folder.cleanup()

    def test_governing_names_case_and_lead_over_runner_up(self):
        parsed = group_report.parse(report())
        governing = group_report.governing(group_report.select(parsed, [1, 7]))
        self.assertEqual((governing['P']['case'], governing['P']['value'], governing['P']['runner_up_case']), (7, 140, 1))
        self.assertAlmostEqual(governing['P']['lead_ratio'], 140 / 120)
        self.assertEqual(governing['Mz']['case_name'], 'STR-V')
        self.assertIsNone(group_report.governing(group_report.select(parsed, [1]))['P']['lead_ratio'])
        self.assertEqual(engine.inspect_report(self.report)['governing']['Vy']['case'], 7)

    def test_case_suggestion_sends_only_names_and_extrema_and_drops_unknown_ids(self):
        client = FakeClient(advice([1, 7, 99]))
        result = assist.suggest_cases(self.report, client=client)
        self.assertEqual(result['recommended_cases'], [1, 7])
        self.assertEqual(result['ignored_case_ids'], [99])
        self.assertEqual(result['withheld_case_ids'], [])
        self.assertIsNone(result['selection_issue'])
        self.assertEqual([c['category'] for c in result['cases']], ['strength', 'service', 'strength'])
        sent = client.requests[0]
        self.assertEqual(sent['model'], assist.DEFAULT_MODEL)
        self.assertEqual(sent['fallbacks'], 'default')
        payload = json.loads(sent['messages'][0]['content'])
        self.assertEqual(payload['cases'][2]['extrema']['P'], {'min': 100, 'max': 140})
        # The raw report, including earlier non-summary tables, is never sent.
        self.assertNotIn('99999', sent['messages'][0]['content'])
        self.assertNotIn('PILE TOP REACTIONS', sent['messages'][0]['content'])

    def test_unusable_suggestion_is_reported_not_applied(self):
        text = report().replace('MINIMUM 100 -25', 'MINIMUM -100 -25')
        self.report.write_text(text)
        result = assist.suggest_cases(self.report, client=FakeClient(advice([7])))
        self.assertIn('tension', result['selection_issue'])

    def test_recommendation_must_match_the_assistants_own_strength_classification(self):
        result = assist.suggest_cases(self.report, client=FakeClient(advice([1, 2, 7])))
        self.assertEqual((result['recommended_cases'], result['withheld_case_ids']), ([1, 7], [2]))

    def test_model_override_drops_unsupported_options_and_reports_answering_model(self):
        client = FakeClient(advice([1]))
        with mock.patch.dict('os.environ', {'GDCALC_AI_MODEL': 'claude-haiku-4-5'}):
            result = assist.suggest_cases(self.report, client=client)
        self.assertNotIn('fallbacks', client.requests[0])
        self.assertNotIn('output_config', client.requests[0])
        self.assertEqual(result['model'], 'claude-haiku-4-5')

    def test_client_failures_and_bad_audits_become_assist_errors(self):
        class Broken(FakeClient):
            def parse(self, **kwargs):
                raise TypeError('Could not resolve authentication method')
        with self.assertRaisesRegex(assist.AssistError, 'request failed: Could not resolve') as caught:
            assist.suggest_cases(self.report, client=Broken())
        self.assertEqual(caught.exception.status, 502)
        output = self.root / 'out' / 'design.mcdx'
        engine.convert(self.report, self.template, output)
        output.with_suffix('.audit.json').write_text('{"calculation": [], "cases": [1], "source_cases": [{"id": 1}]}')
        with self.assertRaisesRegex(assist.AssistError, 'not a gdcalc conversion audit') as caught:
            assist.review(output, client=FakeClient(REVIEW))
        self.assertEqual(caught.exception.status, 400)

    def test_refusal_and_truncation_are_explicit_failures(self):
        with self.assertRaisesRegex(ValueError, 'declined'):
            assist.suggest_cases(self.report, client=FakeClient(advice([1]), stop_reason='refusal'))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            assist.suggest_cases(self.report, client=FakeClient(advice([1]), stop_reason='max_tokens'))

    def test_review_uses_audit_and_calculated_results_and_orders_findings(self):
        output = self.root / 'out' / 'design.mcdx'
        engine.convert(self.report, self.template, output)
        client = FakeClient(REVIEW)
        result = assist.review(output, client=client)
        self.assertEqual([f['severity'] for f in result['findings']], ['critical', 'info'])
        payload = json.loads(client.requests[0]['messages'][0]['content'])
        self.assertIn('P_u = P_a + P_downdrag', payload['calculated_results'])
        self.assertNotIn('<', payload['calculated_results'])
        self.assertEqual(payload['governing']['P']['case'], 7)
        self.assertEqual([c['id'] for c in payload['selected_cases']], [1, 7])
        text = assist.markdown(result)
        self.assertIn('Not an engineering check', text)
        self.assertIn('CRITICAL: Downdrag', text)

    def test_review_requires_completed_calculation(self):
        with self.assertRaisesRegex(ValueError, 'No audit'):
            assist.review(self.template, client=FakeClient(REVIEW))


class AssistServerTests(unittest.TestCase):
    def start(self, **kwargs):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        template(root / 'reference.mcdx')
        self.server = create_server(port=0, template=root / 'reference.mcdx', output_dir=root / 'results', **kwargs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.token = self.request('GET', '/api/session')[1]['token']

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def request(self, method, path, data=None):
        headers = {'X-Gdcalc-Token': getattr(self, 'token', '')}
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        elif data is not None:
            headers['Content-Type'] = 'application/octet-stream'
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        conn.request(method, path, data, headers)
        response = conn.getresponse()
        value = json.loads(response.read())
        conn.close()
        return response.status, value

    def test_assistant_is_disabled_by_default(self):
        self.start()
        self.assertFalse(self.request('GET', '/api/session')[1]['ai']['enabled'])
        status, _ = self.request('POST', '/api/assist/cases', {'id': 'x'})
        self.assertEqual(status, 404)

    def test_enabled_assistant_suggests_cases_and_reviews_outputs(self):
        client = FakeClient(advice([1, 7]), REVIEW)
        self.start(ai=True, ai_client=client)
        self.assertEqual(self.request('GET', '/api/session')[1]['ai'], {'enabled': True, 'model': assist.DEFAULT_MODEL})
        status, uploaded = self.request('POST', '/api/upload?' + urlencode({'name': 'loads.txt', 'kind': 'report'}), report().encode())
        self.assertEqual(status, 200, uploaded)
        status, suggestion = self.request('POST', '/api/assist/cases', {'id': uploaded['id'], 'load_source': 'reactions'})
        self.assertEqual((status, suggestion['recommended_cases']), (200, [1, 7]))
        self.assertEqual(json.loads(client.requests[0]['messages'][0]['content'])['load_source'], 'reactions')
        status, converted = self.request('POST', '/api/convert', {'id': uploaded['id'], 'cases': [1, 7]})
        self.assertEqual(status, 200, converted)
        status, review = self.request('POST', '/api/assist/review', {'id': converted['worksheet']['id']})
        self.assertEqual((status, review['governing']), (200, REVIEW['governing']))
        # A report ID cannot be reviewed and unknown IDs never reach the model.
        self.assertEqual(self.request('POST', '/api/assist/review', {'id': uploaded['id']})[0], 400)
        self.assertEqual(self.request('POST', '/api/assist/cases', {'id': 'missing'})[0], 404)
        self.assertEqual(len(client.requests), 2)


if __name__ == '__main__':
    unittest.main()
