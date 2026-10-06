"""Deduplicate evidence-backed audit tickets. Dry run unless --publish is explicit."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from audit_repository import CHECKS

ALLOWED = {*CHECKS, 'setup'}
STATES = {'passed', 'failed', 'timeout', 'unavailable', 'skipped'}


def validate(report):
    if not isinstance(report, dict) or report.get('schema') != 'repository-audit/1':
        raise ValueError('Unsupported audit report')
    if not re.fullmatch(r'[a-f0-9]{40}', report.get('revision', '')):
        raise ValueError('Audit revision must be a full Git SHA')
    checks = report.get('checks')
    if not isinstance(checks, list) or not checks or len(checks) > len(ALLOWED):
        raise ValueError('Audit needs a bounded nonempty check list')
    seen = set()
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get('id'), str) or check['id'] not in ALLOWED or check['id'] in seen:
            raise ValueError('Unknown or duplicate audit check')
        if check.get('state') not in STATES:
            raise ValueError('Unknown audit outcome')
        if check.get('exit_code') is not None and type(check['exit_code']) is not int:
            raise ValueError('Invalid exit code')
        state, code = check['state'], check.get('exit_code')
        if (state == 'passed' and code != 0) or (state == 'failed' and (code is None or code == 0)) or (state in ('timeout', 'unavailable', 'skipped') and code is not None):
            raise ValueError('Inconsistent outcome and exit code')
        if state == 'skipped' and check['id'] not in ('package-content', 'package-metadata'):
            raise ValueError('Only dependent packaging checks can be skipped')
        seen.add(check['id'])
    if seen != {'setup'} and seen != set(CHECKS):
        raise ValueError('Incomplete audit: all check outcomes must be present')
    if any(c['state'] == 'skipped' for c in checks) and not any(c['id'] == 'package-build' and c['state'] in ('failed', 'timeout', 'unavailable') for c in checks):
        raise ValueError('Skipped checks need failed build evidence')
    return report


def marker(check):
    return '<!-- mcdxkit-audit:' + check + ' -->'


def plan(report, issues, run_url):
    """Stable per-check fingerprints; repeated runs update one open ticket, never spam comments."""
    validate(report)
    actions = []
    for check in report['checks']:
        if check['state'] in ('passed', 'skipped'):
            continue
        key = check['id']
        matched = [i for i in issues if marker(key) in i.get('body', '')]
        opened = [i for i in matched if i['state'] == 'open']
        chosen = max(opened or matched, key=lambda i: i['number'], default=None)
        stamp = '<!-- audit-evidence:' + run_url + ' -->'
        if chosen and chosen['state'] == 'open' and stamp in chosen['body']:
            continue
        title = '[Audit] ' + ('Prerequisite setup unavailable' if key == 'setup' else CHECKS[key][0])
        repro = 'Install requirements.lock / requirements-dev.txt, Node 22 and .NET 10; run mcdxkit setup-engine.' if key == 'setup' else ' '.join(command_for_docs(key))
        evidence = (f'\n\n{stamp}\nObserved `{check["state"]}` at `{report["revision"]}` '
                    f'(exit code: `{check.get("exit_code")}`). [Workflow evidence and logs]({run_url}).\n\n'
                    f'Reproduce in a clean checkout at that revision: `{repro}`\n\n'
                    'Acceptance: identify whether the cause is a product regression, dependency/service failure or runner setup; '
                    'fix the confirmed cause on an issue branch; add a focused regression test when behavior changes; '
                    'pass the affected check and current-head CI. Link the fixing PR and verify post-merge publication. '
                    'This observation does not establish a defect in engineering formulas or an engineering approval.\n')
        if chosen:
            body = chosen['body']
            # Keep original acceptance/discussion intact and replace only the last automation evidence block.
            start, end = '<!-- latest-audit-evidence -->', '<!-- /latest-audit-evidence -->'
            block = start + evidence + end
            if start in body and end in body.split(start, 1)[1]:
                prefix, rest = body.split(start, 1)
                body = prefix + block + rest.split(end, 1)[1]
            else:
                body += '\n\n' + block
            actions.append({'action': 'update' if opened else 'reopen', 'number': chosen['number'], 'body': body, 'title': title})
        else:
            actions.append({'action': 'create', 'title': title,
                            'body': marker(key) + '\n\nA repository audit observed a reproducible check failure or unavailable prerequisite. Triage before assigning a product cause.' + evidence})
    return actions


def command_for_docs(key):
    parts = CHECKS[key][1]
    if key == 'browser-tests': return ['node', '--test', 'tests/*.test.cjs']
    if key == 'package-metadata': return ['python', *parts, 'dist/*']
    return parts if parts[0] == 'node' else ['python', *parts]


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def publish(repo, actions):
    for action in actions:
        with tempfile.TemporaryDirectory() as folder:
            body = Path(folder) / 'body.md'; body.write_text(action['body'])
            if action['action'] == 'create':
                print(gh('issue', 'create', '--repo', repo, '--title', action['title'], '--body-file', str(body)))
            else:
                # Evidence first; an interrupted reopen can be safely retried.
                print(gh('issue', 'edit', str(action['number']), '--repo', repo, '--body-file', str(body)))
                if action['action'] == 'reopen':
                    print(gh('issue', 'reopen', str(action['number']), '--repo', repo))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--attempt', default='1')
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo) or not args.run_id.isdigit() or not args.attempt.isdigit():
        parser.error('Invalid repository or run identity')
    with args.report.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536: parser.error('Audit report exceeds 64 KiB')
    report = validate(json.loads(raw))
    if report['revision'] != args.expected_revision:
        parser.error('Artifact revision differs from the audited checkout')
    if report.get('run_id') != args.run_id or report.get('run_attempt') != args.attempt:
        parser.error('Artifact belongs to a different workflow run/attempt')
    run_url = f'https://github.com/{args.repo}/actions/runs/{args.run_id}/attempts/{args.attempt}'
    # No issue reads/writes on clean runs. Scheduled reports contain only known metadata, not raw logs.
    failed = any(c['state'] not in ('passed', 'skipped') for c in report['checks'])
    if not failed:
        print('All checks passed; no tickets created.'); return 0
    issues = []
    if args.publish:
        if os.environ.get('GITHUB_REPOSITORY') != args.repo:
            parser.error('Publishing requires matching GITHUB_REPOSITORY')
        pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{args.repo}/issues?state=all&per_page=100'))
        issues = [item for page in pages for item in page if 'pull_request' not in item]
    actions = plan(report, issues, run_url)
    if args.publish: publish(args.repo, actions)
    else: print(json.dumps(actions, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
