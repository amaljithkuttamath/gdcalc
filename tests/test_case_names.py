"""Case-name classifier (regex, then naive Bayes), learning from audits, and governing cases."""
import json
import tempfile
import unittest
from pathlib import Path

from test_pipeline import report, template
from mcdxkit import engine, group_report
from mcdxkit.review import runner
from mcdxkit.review.classify import names
from mcdxkit.review.history import AuditHistory, MemoryHistory, audit_examples
from mcdxkit.server import create_server


def summary(cases):
    """Synthetic final summary; cases are (id, name, P, Mz) with proportional other components."""
    names = ''.join(f'LOAD CASE : {i}\nCASE NAME : {name}\n' for i, name, _, _ in cases)
    blocks = ''
    for i, _, p, m in cases:
        blocks += f'''LOAD CASE : {i}
* PILE TOP REACTIONS, LOCAL *
AXIAL,KIP LAT. y,KIP LAT. z,KIP MOM x,KIP-IN MOM y,KIP-IN MOM z,KIP-IN
MINIMUM {p * .8} -{p / 10} -{p / 20} 1 -{m / 5} -{m}
MAXIMUM {p} {p / 10} {p / 20} 1 {m / 5} {m}
* EFFECTS FOR LATERALLY LOADED PILE *
y-DIR z-DIR z-DIR y-DIR y-DIR z-DIR y-DIR z-DIR STRESS
IN IN KIP-IN KIP-IN KIP KIP KIP/IN KIP/IN KIP/IN**2
Min. -.1 -.2 -{m} -{m / 5} -{p / 10} -{p / 20} -.4 -.5 1
Max. .2 .3 {m} {m / 5} {p / 10} {p / 20} .4 .5 10
'''
    return names + 'SUMMARY FOR LOAD CASES AND COMBINATIONS\n' + blocks


class ClassifierTests(unittest.TestCase):
    def test_common_limit_state_names(self):
        model = names.model()
        expected = {'Strength I': 'strength', 'STR-IA': 'strength', 'Str 3': 'strength', 'ULS2': 'strength',
                    'Service I': 'service', 'SER-II': 'service', 'SLS1': 'service', 'Extreme Event I': 'extreme',
                    'Fatigue I': 'fatigue', 'Dead Load': 'other', 'Construction': 'other'}
        for name, label in expected.items():
            predicted, probability, evidence = model.predict(name)
            self.assertEqual(predicted, label, name)
            self.assertGreaterEqual(probability, names.CONFIDENCE)
            self.assertTrue(evidence, name)

    def test_ambiguous_or_unseen_names_abstain(self):
        model = names.model()
        for name in ('', 'Max axial', 'S1', 'PILE CAP A'):
            self.assertIsNone(model.predict(name)[0], name)

    def test_seed_corpus_held_out_quality(self):
        correct = wrong = 0
        for i, (name, label) in enumerate(names.SEED):
            predicted = names.NameModel().fit(names.SEED[:i] + names.SEED[i + 1:]).predict(name)[0]
            correct += predicted == label
            wrong += predicted not in (None, label)
        self.assertGreaterEqual(correct / len(names.SEED), 0.85)
        self.assertLessEqual(wrong / len(names.SEED), 0.03)


def suggestions(path, history=None):
    return engine.inspect_report(path, history=history)['case_suggestions']


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.template = self.root / 'reference.mcdx'
        template(self.template)

    def tearDown(self):
        self.folder.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def test_recommends_confident_strength_cases_only(self):
        path = self.write('r.txt', summary([(1, 'Strength I', 100, 900), (2, 'Service I', 80, 700),
                                            (3, 'Extreme Event I', 120, 1000), (4, 'Max axial', 90, 800)]))
        self.assertIn('classification unavailable', engine.inspect_report(path)['selection_required'])
        result = suggestions(path)
        self.assertEqual(result['recommended_cases'], [1])
        self.assertEqual(result['unresolved_case_ids'], [4])
        self.assertEqual([c['category'] for c in result['cases']], ['strength', 'service', 'extreme', 'unknown'])
        # AASHTO long names are recognized by the regex stage before the model.
        self.assertEqual([c['stage'] for c in result['cases']], ['regex', 'regex', 'naive-bayes', 'naive-bayes'])
        self.assertIsNone(result['selection_issue'])
        self.assertEqual(result['trained_on']['history'], 0)

    def test_unusable_recommendation_is_reported(self):
        # Tension in the only strength case: the compression template cannot use it.
        path = self.write('r.txt', summary([(1, 'Strength I', 100, 900)]).replace('MINIMUM 80.0', 'MINIMUM -10.0'))
        self.assertIn('tension', suggestions(path)['selection_issue'])

    def test_learns_project_naming_from_completed_audits(self):
        cases = [(1, 'LC-A', 100, 900), (2, 'LC-B', 80, 700), (3, 'LC-C', 110, 950)]
        path = self.write('r.txt', summary(cases))
        self.assertEqual(suggestions(path)['recommended_cases'], [])
        history = self.root / 'outputs'
        for job in range(3):
            engine.convert(path, self.template, history / str(job) / 'w.mcdx', cases=[1, 3])
        result = suggestions(path, AuditHistory(history))
        self.assertEqual(result['trained_on']['history'], 9)
        self.assertEqual(result['recommended_cases'], [1, 3])
        self.assertNotEqual(result['cases'][1]['category'], 'strength')
        # The same decisions from an in-memory store give the same suggestions.
        memory = MemoryHistory([('LC-A', True), ('LC-B', False), ('LC-C', True)] * 3)
        self.assertEqual(suggestions(path, memory), result)

    def test_corrupt_history_is_ignored(self):
        history = self.root / 'outputs'
        history.mkdir()
        (history / 'bad.audit.json').write_text('{"cases": 3}')
        (history / 'worse.audit.json').write_text('not json')
        self.assertEqual(audit_examples(history), ())
        self.assertEqual(AuditHistory(self.root / 'missing').case_examples(), ())


def path_for(text):
    folder = Path(tempfile.mkdtemp())
    path = folder / 'r.txt'
    path.write_text(text)
    return path


class GoverningTests(unittest.TestCase):
    def test_inspect_reports_governing_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'r.txt'
            path.write_text(report())
            inspected = engine.inspect_report(path)
        self.assertNotIn('anomalies', inspected)
        governing = inspected['governing']
        self.assertEqual((governing['P']['case'], governing['P']['value'], governing['P']['runner_up_case']), (7, 140, 1))
        self.assertAlmostEqual(governing['P']['lead_ratio'], 140 / 120)
        self.assertEqual(governing['Mz']['case_name'], 'STR-V')
        parsed = group_report.parse(report())
        single = engine.inspect_report(path_for(report()), cases=[1])['governing']
        self.assertIsNone(single['P']['lead_ratio'])
        annotations = runner.review(parsed, [1, 7])['annotations']
        self.assertEqual({a['component']: a['data'] for a in annotations if a['kind'] == 'governing'}, governing)


class SuggestEndpointTests(unittest.TestCase):
    def test_suggestions_through_inspect_endpoint(self):
        import http.client
        import threading
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template(root / 'reference.mcdx')
            server = create_server(port=0, template=root / 'reference.mcdx', output_dir=root / 'results')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, data, token=''):
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                    headers = {'X-MCDXKit-Token': token}
                    if isinstance(data, dict):
                        data, headers['Content-Type'] = json.dumps(data).encode(), 'application/json'
                    elif data is not None:
                        headers['Content-Type'] = 'application/octet-stream'
                    conn.request('GET' if data is None else 'POST', path, data, headers)
                    response = conn.getresponse()
                    value = json.loads(response.read())
                    conn.close()
                    return response.status, value
                token = request('/api/session', None)[1]['token']
                status, uploaded = request('/api/upload?' + urlencode({'name': 'r.txt', 'kind': 'report'}), report().encode(), token)
                self.assertEqual(status, 200, uploaded)
                self.assertTrue(uploaded['inspection']['review_checks']['advisory'])
                self.assertEqual(uploaded['inspection']['case_suggestions']['recommended_cases'], [1, 7])
                status, result = request('/api/inspect', {'id': uploaded['id'], 'load_source': 'reactions'}, token)
                self.assertEqual((status, result['case_suggestions']['recommended_cases']), (200, [1, 7]))
                # Suggestions come from inspect; the former endpoint is gone.
                self.assertEqual(request('/api/suggest-cases', {'id': uploaded['id']}, token)[0], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
