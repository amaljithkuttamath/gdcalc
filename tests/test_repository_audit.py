"""Audit-ticket planning is synthetic and never contacts GitHub."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
# Tool scripts ship in the repository, not the installed calculation SDK.
spec = importlib.util.spec_from_file_location('audit_repository', SCRIPTS / 'audit_repository.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
with mock.patch.dict(sys.modules, {'audit_repository': audit}):
    spec = importlib.util.spec_from_file_location('report_audit', SCRIPTS / 'report_audit.py')
    reporter = importlib.util.module_from_spec(spec); spec.loader.exec_module(reporter)


def report(failed=None):
    return {'schema': 'repository-audit/1', 'revision': 'a' * 40, 'run_id': '123', 'run_attempt': '1',
            'checks': [{'id': key, 'state': 'failed' if key == failed else 'passed', 'exit_code': 1 if key == failed else 0}
                       for key in audit.CHECKS]}


class AuditTests(unittest.TestCase):
    def test_clean_audit_is_quiet_and_failure_has_reproduction_evidence(self):
        self.assertEqual(reporter.plan(report(), [], 'https://example.test/run'), [])
        action, = reporter.plan(report('tests'), [], 'https://example.test/run')
        self.assertEqual(action['action'], 'create')
        for text in ('a' * 40, 'unittest discover', 'regression test', 'https://example.test/run'):
            self.assertIn(text, action['body'])

    def test_repeated_findings_update_one_issue_and_same_run_is_idempotent(self):
        first, = reporter.plan(report('lint'), [], 'https://example.test/1')
        existing = {'number': 10, 'state': 'open', 'body': first['body']}
        self.assertEqual(reporter.plan(report('lint'), [existing], 'https://example.test/1'), [])
        action, = reporter.plan(report('lint'), [existing], 'https://example.test/2')
        self.assertEqual((action['action'], action['number']), ('update', 10))
        existing['body'] = action['body'] + '\nMaintainer acceptance note: preserve this.'
        action, = reporter.plan(report('lint'), [existing], 'https://example.test/3')
        self.assertIn('Maintainer acceptance note: preserve this.', action['body'])
        self.assertNotIn('https://example.test/2', action['body'])
        self.assertIn('https://example.test/1', action['body'])
        self.assertEqual(action['body'].count('<!-- latest-audit-evidence -->'), 1)

    def test_closed_regression_reopens_and_clean_run_never_closes_issues(self):
        first, = reporter.plan(report('types'), [], 'https://example.test/1')
        existing = {'number': 7, 'state': 'closed', 'body': first['body']}
        action, = reporter.plan(report('types'), [existing], 'https://example.test/2')
        self.assertEqual(action['action'], 'reopen')
        self.assertEqual(reporter.plan(report(), [existing], 'https://example.test/3'), [])

    def test_interrupted_reopen_can_be_retried(self):
        first, = reporter.plan(report('types'), [], 'https://example.test/1')
        existing = {'number': 7, 'state': 'closed', 'body': first['body']}
        action, = reporter.plan(report('types'), [existing], 'https://example.test/1')
        self.assertEqual(action['action'], 'reopen')

    def test_skipped_and_inconsistent_outcomes_cannot_look_clean(self):
        for changes in ({'state': 'skipped', 'exit_code': None}, {'state': 'passed', 'exit_code': 2}, {'state': 'failed', 'exit_code': 0}):
            value = report(); value['checks'][0].update(changes)
            with self.assertRaises(ValueError): reporter.validate(value)

    def test_existing_open_issue_preferred_over_closed_duplicate(self):
        body = reporter.marker('tests')
        issues = [{'number': 1, 'state': 'open', 'body': body}, {'number': 2, 'state': 'closed', 'body': body}]
        self.assertEqual(reporter.plan(report('tests'), issues, 'https://example.test/3')[0]['number'], 1)

    def test_unknown_partial_or_malformed_evidence_is_rejected(self):
        for mutation in (lambda r: r.update(revision='not-a-sha'),
                         lambda r: r['checks'].pop(),
                         lambda r: r['checks'].append(copy.deepcopy(r['checks'][0])),
                         lambda r: r['checks'][0].update(id='arbitrary-command'),
                         lambda r: r['checks'][0].update(state='approved')):
            value = report(); mutation(value)
            with self.assertRaises(ValueError): reporter.validate(value)

    def test_timeouts_and_missing_tools_are_explicit_not_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(audit.subprocess, 'run', side_effect=subprocess.TimeoutExpired('x', 1)):
                self.assertEqual(audit.run_check('tests', ['x'], root)['state'], 'timeout')
            self.assertEqual(audit.run_check('missing', [str(root / 'no-such-tool')], root)['state'], 'unavailable')
            self.assertEqual(audit.run_check('ok', [sys.executable, '-c', 'print("synthetic")'], root)['state'], 'passed')
            self.assertIn('synthetic', (root / 'ok.log').read_text())

    def test_setup_failure_records_no_test_execution_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(audit.subprocess, 'check_output', return_value='b'*40):
            dest = Path(folder) / 'evidence'
            with mock.patch.object(audit, 'run_check') as run:
                self.assertEqual(audit.main(['--setup-failed', '--output', str(dest)]), 1)
                run.assert_not_called()
            value = json.loads((dest / 'report.json').read_text())
            self.assertEqual(value['checks'][0]['id'], 'setup')
            reporter.validate(value)
            with self.assertRaises(FileExistsError): audit.main(['--setup-failed', '--output', str(dest)])

    def test_clean_cli_never_uses_github_and_wrong_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(reporter, 'gh') as gh:
            path = Path(folder) / 'report.json'; path.write_text(json.dumps(report()))
            args = [str(path), '--repo', 'owner/repo', '--run-id', '123', '--expected-revision', 'a'*40]
            self.assertEqual(reporter.main(args), 0); gh.assert_not_called()
            with self.assertRaises(SystemExit): reporter.main(args[:-1] + ['b'*40])

    def test_publish_requires_explicit_flag_and_matching_destination(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(reporter, 'gh') as gh, mock.patch.dict(os.environ, {'GITHUB_REPOSITORY': 'different/repo'}):
            path = Path(folder) / 'report.json'; path.write_text(json.dumps(report('tests')))
            args = [str(path), '--repo', 'owner/repo', '--run-id', '123', '--expected-revision', 'a'*40]
            with mock.patch('builtins.print'): self.assertEqual(reporter.main(args), 0)
            gh.assert_not_called()
            with self.assertRaises(SystemExit): reporter.main(args + ['--publish'])
            gh.assert_not_called()
