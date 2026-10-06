"""Run bounded, synthetic repository checks. Writes local evidence; never opens tickets."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CHECKS = {
    'tests': ('Synthetic SDK, CLI, HTTP and real-calculator tests', ['-m', 'unittest', 'discover', '-s', 'tests', '-v']),
    'lint': ('Python correctness lint', ['-m', 'ruff', 'check', 'src', 'tests', 'scripts']),
    'types': ('Python type checks', ['-m', 'mypy']),
    'browser-syntax': ('Browser JavaScript syntax', ['node', '--check', 'src/mcdxkit/web/app.js']),
    'browser-tests': ('Browser orchestration tests', ['node', '--test']),
    'package-build': ('Distribution build', ['-m', 'build']),
    'package-content': ('Packaged assets, licenses and metadata', ['scripts/check_package.py']),
    'package-metadata': ('Strict distribution metadata', ['-m', 'twine', 'check', '--strict']),
}


def command(check, python=sys.executable):
    parts = list(CHECKS[check][1])
    if check == 'browser-tests':
        parts += [str(p) for p in sorted(Path('tests').glob('*.test.cjs'))]
    if check == 'package-metadata':
        parts += [str(p) for p in sorted(Path('dist').glob('*')) if p.is_file()]
    return parts if parts[0] == 'node' else [python, *parts]


def run_check(name, argv, folder, timeout=600):
    """Use argv without a shell; stream logs to disk rather than retaining them in RAM."""
    started = time.monotonic()
    try:
        with (folder / (name + '.log')).open('xb') as log:
            result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        state, code = ('passed' if result.returncode == 0 else 'failed'), result.returncode
    except subprocess.TimeoutExpired:
        state, code = 'timeout', None
    except OSError:
        state, code = 'unavailable', None
    return {'id': name, 'state': state, 'exit_code': code, 'seconds': round(time.monotonic() - started, 2)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.mcdxkit/audit'))
    parser.add_argument('--setup-failed', action='store_true', help='Record prerequisite failure without claiming tests ran')
    args = parser.parse_args(argv)
    # New directory only. Never mix evidence from separate runs or overwrite prior results.
    args.output.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if args.setup_failed:
        results = [{'id': 'setup', 'state': 'unavailable', 'exit_code': None, 'seconds': 0}]
    else:
        results = []
        for name in CHECKS:
            if name.startswith('package-') and name != 'package-build' and any(r['id'] == 'package-build' and r['state'] != 'passed' for r in results):
                results.append({'id': name, 'state': 'skipped', 'exit_code': None, 'seconds': 0})
                continue
            result = run_check(name, command(name), args.output)
            results.append(result)
            print(name + ': ' + result['state'], flush=True)
    report = {'schema': 'repository-audit/1', 'revision': revision, 'checks': results,
              'scope': 'Synthetic software verification; no private engineering files or professional approval',
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return int(any(r['state'] not in ('passed', 'skipped') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
