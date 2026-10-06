"""Offline models: case-name classifier, learning from audits, and load outliers."""
import json
import tempfile
import unittest
from pathlib import Path

from test_pipeline import report, template
from gdcalc import engine, group_report, learn
from gdcalc.server import create_server


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
        model = learn.classifier()
        expected = {'Strength I': 'strength', 'STR-IA': 'strength', 'Str 3': 'strength', 'ULS2': 'strength',
                    'Service I': 'service', 'SER-II': 'service', 'SLS1': 'service', 'Extreme Event I': 'extreme',
                    'Fatigue I': 'fatigue', 'Dead Load': 'other', 'Construction': 'other'}
        for name, label in expected.items():
            predicted, probability, evidence = model.predict(name)
            self.assertEqual(predicted, label, name)
            self.assertGreaterEqual(probability, learn.CONFIDENCE)
            self.assertTrue(evidence, name)

    def test_ambiguous_or_unseen_names_abstain(self):
        model = learn.classifier()
        for name in ('', 'Max axial', 'S1', 'PILE CAP A'):
            self.assertIsNone(model.predict(name)[0], name)

    def test_seed_corpus_held_out_quality(self):
        correct = wrong = 0
        for i, (name, label) in enumerate(learn.SEED):
            predicted = learn.CaseClassifier().fit(learn.SEED[:i] + learn.SEED[i + 1:]).predict(name)[0]
            correct += predicted == label
            wrong += predicted not in (None, label)
        self.assertGreaterEqual(correct / len(learn.SEED), 0.85)
        self.assertLessEqual(wrong / len(learn.SEED), 0.03)


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
        result = learn.suggest_cases(path)
        self.assertEqual(result['recommended_cases'], [1])
        self.assertEqual(result['unresolved_case_ids'], [4])
        self.assertEqual([c['category'] for c in result['cases']], ['strength', 'service', 'extreme', 'unknown'])
        self.assertIsNone(result['selection_issue'])
        self.assertEqual(result['trained_on']['history'], 0)

    def test_unusable_recommendation_is_reported(self):
        # Tension in the only strength case: the compression template cannot use it.
        path = self.write('r.txt', summary([(1, 'Strength I', 100, 900)]).replace('MINIMUM 80.0', 'MINIMUM -10.0'))
        self.assertIn('tension', learn.suggest_cases(path)['selection_issue'])

    def test_learns_project_naming_from_completed_audits(self):
        cases = [(1, 'LC-A', 100, 900), (2, 'LC-B', 80, 700), (3, 'LC-C', 110, 950)]
        path = self.write('r.txt', summary(cases))
        self.assertEqual(learn.suggest_cases(path)['recommended_cases'], [])
        history = self.root / 'outputs'
        for job in range(3):
            engine.convert(path, self.template, history / str(job) / 'w.mcdx', cases=[1, 3])
        result = learn.suggest_cases(path, output_dir=history)
        self.assertEqual(result['trained_on']['history'], 9)
        self.assertEqual(result['recommended_cases'], [1, 3])
        self.assertNotEqual(result['cases'][1]['category'], 'strength')

    def test_corrupt_history_is_ignored(self):
        history = self.root / 'outputs'
        history.mkdir()
        (history / 'bad.audit.json').write_text('{"cases": 3}')
        (history / 'worse.audit.json').write_text('not json')
        self.assertEqual(learn.history_examples(history), [])


class AnomalyTests(unittest.TestCase):
    def cases(self, moments):
        return group_report.parse(summary([(i + 1, f'STR-{i + 1}', 100 + i, m) for i, m in enumerate(moments)]))['cases']

    def test_flags_moment_twelve_times_typical_as_unit_error(self):
        found = learn.anomalies(self.cases([900, 950, 870, 1000, 920, 11000]))
        mz = [f for f in found if f['component'] == 'Mz']
        self.assertEqual([f['case'] for f in mz], [6])
        self.assertEqual(mz[0]['possible_unit_error'], 'kip-ft vs kip-in')
        self.assertGreater(mz[0]['score'], 3.5)

    def test_ordinary_scatter_and_small_reports_are_not_flagged(self):
        self.assertEqual(learn.anomalies(self.cases([900, 950, 870, 1000, 920, 1300])), [])
        self.assertEqual(learn.anomalies(self.cases([900, 950, 9000])), [])

    def test_inspect_reports_anomalies_and_governing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'r.txt'
            path.write_text(report())
            inspected = engine.inspect_report(path)
        self.assertEqual(inspected['anomalies'], [])
        governing = inspected['governing']
        self.assertEqual((governing['P']['case'], governing['P']['value'], governing['P']['runner_up_case']), (7, 140, 1))
        self.assertAlmostEqual(governing['P']['lead_ratio'], 140 / 120)
        self.assertEqual(governing['Mz']['case_name'], 'STR-V')
        self.assertIsNone(group_report.governing(group_report.select(group_report.parse(report()), [1]))['P']['lead_ratio'])


class SuggestEndpointTests(unittest.TestCase):
    def test_suggest_cases_endpoint(self):
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
                    headers = {'X-Gdcalc-Token': token}
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
                self.assertEqual(uploaded['inspection']['anomalies'], [])
                status, result = request('/api/suggest-cases', {'id': uploaded['id'], 'load_source': 'reactions'}, token)
                self.assertEqual((status, result['recommended_cases']), (200, [1, 7]))
                self.assertEqual(request('/api/suggest-cases', {'id': 'missing'}, token)[0], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
