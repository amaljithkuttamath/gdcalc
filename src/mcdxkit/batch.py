"""Resumable, bounded parallel conversion pipeline around the same core engine."""
import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path

from . import engine, calcpad, group_report
from . import checks as worksheet_checks
from .review import runner as review_runner
from .review.history import AuditHistory, MemoryHistory

from .generate import case_ids, default_template


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def discover(inputs, output_dir, *, recursive=False):
    output_dir = Path(output_dir).resolve()
    found = set()
    for value in inputs:
        path = Path(value).resolve()
        if not path.exists():
            raise ValueError(f'Input does not exist: {path}')
        candidates = path.rglob('*') if path.is_dir() and recursive else path.glob('*') if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file() or candidate.is_symlink():
                continue
            candidate = candidate.resolve()
            if candidate.is_relative_to(output_dir):
                continue
            if candidate.suffix.lower() in ('.gp11t', '.txt'):
                found.add(candidate)
            elif not path.is_dir():
                raise ValueError(f'Unsupported report: {path.name}; use .gp11t or .txt')
    return sorted(found)


@contextmanager
def manifest_lock(root):
    # OS locks are released after process death; no stale lock recovery flag needed.
    with (root / '.mcdxkit-batch.lock').open('a+b') as handle:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.write(b'0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('Another batch owns this output directory. Use a separate directory or wait.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _convert_job(job):
    started = time.monotonic()
    row = {k: job[k] for k in ('job_id', 'source', 'source_sha256', 'template_sha256', 'settings', 'output')}
    row['native_execution_verified'] = False
    output = Path(job['output']); audit = output.with_suffix('.audit.json')
    try:
        identity = {k: row[k] for k in ('job_id', 'source_sha256', 'template_sha256', 'settings')}
        metadata = output.parent / 'job.json'
        if output.exists() or audit.exists():
            if not job['resume']:
                raise ValueError('Output already exists. Use --resume or a new output directory.')
            if not output.is_file() or not audit.is_file() or not metadata.is_file():
                raise ValueError('Incomplete output pair. Preserve it for review and use a new output directory.')
            previous = json.loads(metadata.read_text())
            evidence = json.loads(audit.read_text())
            if (previous != identity or evidence['source_sha256'] != job['source_sha256']
                    or evidence['template_sha256'] != job['template_sha256']
                    or evidence['sha256'] != digest(output)):
                raise ValueError('Existing output failed identity/hash checks. It was not overwritten.')
            engine.validate(output)
            calculation = evidence.get('calculation', {})
            if not calculation.get('calculated') or calculation.get('revision') != calcpad.REVISION:
                raise ValueError('Saved output has no verified CalcpadCE calculation')
            artifact = output.with_suffix('.cpd')
            if not artifact.is_file() or digest(artifact) != calculation.get('source_sha256'):
                raise ValueError('Calculated worksheet failed artifact hash checks')
            # Hash and parse the same bytes so check outcomes come only from the verified page.
            rendered = output.with_suffix('.html')
            page = rendered.read_bytes() if rendered.is_file() else None
            if page is None or hashlib.sha256(page).hexdigest() != calculation.get('html_sha256'):
                raise ValueError('Calculated worksheet failed artifact hash checks')
            row.update(status='skipped', sha256=evidence['sha256'], audit=str(audit),
                       check_summary=resumed_checks(page, calculation.get('region_lines')),
                       open_checks=review_runner.open_flags(evidence.get('review_checks')),
                       check_errors=review_runner.check_errors(evidence.get('review_checks')))

        else:
            if Path(job['source']).stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Raw report exceeds 16 MiB')
            source_dir = output.parent / '_source'
            source_dir.mkdir(parents=True, exist_ok=True)
            snapshots = [(Path(job['source']), source_dir / Path(job['source']).name, job['source_sha256']),
                         (Path(job['template']), source_dir / 'template.mcdx', job['template_sha256'])]
            for original, snapshot, expected in snapshots:
                if not snapshot.exists():
                    # The coordinator lock prevents simultaneous batches from writing here.
                    with original.open('rb') as src, snapshot.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                if digest(snapshot) != expected:
                    raise ValueError('Input changed or snapshot is incomplete. Retry in a new output directory.')
            if metadata.exists():
                if json.loads(metadata.read_text()) != identity:
                    raise ValueError('Job identity mismatch. Existing files were not overwritten.')
            else:
                with metadata.open('x') as stream:
                    json.dump(identity, stream, indent=2)
            result = engine.convert(snapshots[0][1], snapshots[1][1], output, **job['settings'])
            row.update(status='succeeded', sha256=result['sha256'], audit=str(audit),
                       cases=result['cases'], envelope=result['envelope'], check_summary=result['check_summary'],
                       open_checks=review_runner.open_flags(result['review_checks']),
                       check_errors=review_runner.check_errors(result['review_checks']))

    except Exception as exc:
        row.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    if job.get('suggest'):
        try:
            row['suggestions'] = suggestions(job)
        except Exception as exc:  # advisory: never changes the job's status
            row['suggestions'] = {'error': f'{type(exc).__name__}: {exc}'}
    if row.get('status') in ('succeeded', 'skipped'):
        row.update(calculation_engine='CalcpadCE', calculated=True,
                   open_worksheet=str(output.with_suffix('.cpd')), calculated_worksheet=str(output.with_suffix('.html')))
    row['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return row


# (examples, skipped) read once from --history at batch start; set per worker process.
HISTORY = None


def _use_history(value):
    global HISTORY
    HISTORY = value


def suggestions(job):
    """Advisory case triage for one report, read-only: it never changes the cases, outputs or status.

    The report is re-read only if its bytes still match the job's hash, so the advice is about the
    converted input. ``selected_cases`` is the job's selection rule applied to that input (empty,
    with ``selection_required``, when it fails); ``differences`` lists cases to look at."""
    settings = job['settings']
    raw = engine._read_raw(job['source'])
    if hashlib.sha256(raw).hexdigest() != job['source_sha256']:
        raise ValueError('Report changed since the job started')
    parsed = engine._parse_raw(raw, settings['load_source'])
    issue = None
    try:
        selected = [c['id'] for c in group_report.select(parsed, settings['cases'])]
    except ValueError as exc:
        selected, issue = [], str(exc)
    history = MemoryHistory(*HISTORY) if HISTORY is not None else None
    block = review_runner.review(parsed, selected, plan=review_runner.prepare(settings['checks']), history=history)
    advice = engine._case_suggestions(parsed, block)
    if advice is None:
        detail = '; '.join(e['message'] for e in block['errors'])
        raise ValueError('case-name classifier did not run' + (': ' + detail if detail else ''))
    names = {c['id']: c['name'] for c in parsed['cases']}
    chosen = set(selected)
    reasons = {}
    for case in advice['cases']:
        if case['category'] == 'strength' and case['id'] not in chosen:
            reasons.setdefault((case['id'], 'add'), []).append(f"strength {case['confidence']:.2f}")
        elif case['id'] in chosen and case['category'] not in ('strength', 'unknown'):
            reasons.setdefault((case['id'], 'drop'), []).append(f"{case['category']} {case['confidence']:.2f}")
    flags = []
    for flag in block['flags']:
        flags.append({k: flag[k] for k in ('rule', 'case', 'component', 'message')} | {'selection': flag['impact']['selection']})
        if flag['impact']['selection'] and flag['case'] is not None and flag['case'] not in chosen:
            reasons.setdefault((flag['case'], 'add'), []).append('flag ' + flag['rule'])
    differences = [{'case': case, 'name': names.get(case), 'action': action, 'reasons': list(dict.fromkeys(why))}
                   for (case, action), why in sorted(reasons.items())]
    return {'selected_cases': selected, 'selection_required': issue, 'case_suggestions': advice,
            'flags': flags, 'review_errors': block['errors'], 'differences': differences}


def suggestion_text(result):
    """Compact triage cell: cases to add or drop and why; empty when the selection matches."""
    advice = result.get('suggestions')
    if not isinstance(advice, dict) or 'differences' not in advice:
        error = advice.get('error') if isinstance(advice, dict) else None
        return 'unavailable: ' + (error or 'report not read')
    parts = [f"{d['action']} {d['case']} {d['name'] or ''} [{', '.join(d['reasons'])}]" for d in advice['differences']]
    unresolved = [i for i in advice['case_suggestions']['unresolved_case_ids'] if i not in advice['selected_cases']]
    if unresolved:
        parts.append('unclassified ' + ', '.join(map(str, unresolved)))
    return '; '.join(' '.join(p.split()) for p in parts)


def resumed_checks(page, region_lines):
    """Check summary re-read from a verified page; None (not recorded) without region lines."""
    if not isinstance(region_lines, dict) or not all(type(v) is int for v in region_lines.values()):
        return None
    return worksheet_checks.extract(page.decode('utf-8'), region_lines)[1]


CHECK_COLUMNS = ('source', 'status', 'checks', 'passed', 'failed', 'governing_dc', 'governing_check',
                 'failed_checks', 'note')
SUGGEST_COLUMNS = ('suggested_cases',)


def source_label(source, base=None):
    """Report path relative to the batch input root, so equal basenames stay distinct."""
    path = Path(source)
    if base is not None and path.is_relative_to(base):
        return path.relative_to(base).as_posix()
    return path.as_posix()


def input_root(inputs):
    """Deepest folder containing every input; files count by their parent folder."""
    folders = [str(p if p.is_dir() else p.parent) for p in (Path(i).resolve() for i in inputs)]
    try:
        return Path(os.path.commonpath(folders))
    except ValueError:  # e.g. inputs on different Windows drives
        return None


def check_row(result, base=None, suggest=False):
    """One table row per report; outcomes come only from validated check summaries."""
    row = dict.fromkeys(CHECK_COLUMNS + (SUGGEST_COLUMNS if suggest else ()), '')
    if suggest:
        row['suggested_cases'] = suggestion_text(result)
    row.update(source=source_label(result['source'], base), status=result['status'])
    summary = result.get('check_summary')
    if result['status'] == 'failed':
        row['note'] = 'conversion failed'
    elif not worksheet_checks.valid_summary(summary):
        row['note'] = 'checks not recorded for this output'
    elif not summary.get('total'):
        row['note'] = 'no checks found'
    else:
        governing = summary.get('governing')
        row.update(checks=summary['total'], passed=summary['passed'], failed=summary['failed'],
                   failed_checks='; '.join(summary.get('failed_checks', [])),
                   governing_dc=f"{governing['ratio']:.3f}" if governing else '',
                   governing_check=governing['name'] if governing else '',
                   note='FAILURES' if summary['failed'] else 'all checks passed')
    return row


def _cell(value):
    # Worksheet variable names reach this table; stop spreadsheet formula injection.
    value = str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


def write_check_table(root, rows, columns=CHECK_COLUMNS):
    """Write a new timestamped CSV; earlier tables are never overwritten."""
    stamp = time.strftime('%Y%m%dT%H%M%S')
    for attempt in range(100):
        path = root / (f'check-summary-{stamp}' + (f'-{attempt}' if attempt else '') + '.csv')
        try:
            stream = path.open('x', newline='', encoding='utf-8')
        except FileExistsError:
            continue
        with stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows({k: _cell(v) for k, v in row.items()} for row in rows)
        return path
    raise ValueError('Could not create a new check summary table')


def format_check_table(rows):
    """Plain-text per-report table: governing D/C and any failed checks."""
    columns = ('source', 'status', 'checks', 'failed', 'governing_dc', 'governing_check', 'note')
    widths = {c: max([len(c)] + [len(str(r[c])) for r in rows]) for c in columns}
    lines = ['  '.join(c.upper().ljust(widths[c]) for c in columns)]
    lines += ['  '.join(str(r[c]).ljust(widths[c]) for c in columns) for r in rows]
    lines += [f"{r['source']}: failed {r['failed_checks']}" for r in rows if r['failed_checks']]
    lines += [f"{r['source']}: suggest {r['suggested_cases']}" for r in rows if r.get('suggested_cases')]
    return '\n'.join(line.rstrip() for line in lines)


def convert_batch(inputs, template, output_dir, *, workers=1, recursive=False, resume=False,
                  cases=None, load_source='effects', overrides=None, checks='default', progress=None, check_rows=None,
                  suggest=False, history=None):
    """Convert files independently; append durable records and verify outputs on resume.

    The job identity includes the enabled review checks and their versions, so a new check
    version gives a new job (and a fresh review) on resume.

    ``suggest`` adds advisory case suggestions and review flags to each manifest row and a
    ``suggested_cases`` table column. It is not part of the job identity and never changes the
    cases or outputs. ``history`` (with ``suggest`` only) is an output directory of earlier,
    reviewed conversions whose case names the classifier learns from; it is read once, here."""

    if not 1 <= workers <= 32:
        raise ValueError('workers must be between 1 and 32')
    template = Path(template).resolve(); root = Path(output_dir).resolve()
    if not template.is_file():
        raise ValueError('Template not found. Pass --template /path/to/reference.mcdx')
    if template.is_relative_to(root):
        raise ValueError('Keep the reference template outside the batch output directory.')
    plan = review_runner.prepare(checks)
    if history is not None and not suggest:
        raise ValueError('--history applies to batch only with --suggest')
    if suggest and not any(e.plugin.kind == 'classifier' for e in plan.entries):
        raise ValueError('--suggest needs the case-name classifier; use --checks default or include case_names')
    learned = None
    if history is not None:
        history = Path(history).resolve()
        if not history.is_dir():
            raise ValueError('--history must be an existing output directory')
        if history.is_relative_to(root) or root.is_relative_to(history):
            # Batch selections are automatic, not reviewed, and would change on every resume.
            raise ValueError('--history must not overlap the batch output directory')
        found = AuditHistory(history)
        learned = (found.case_examples(), found.skipped)
    files = discover(inputs, root, recursive=recursive)
    base = input_root(inputs)
    if not files:
        raise ValueError('No .gp11t or .txt reports found. Use --recursive for subfolders.')
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / 'batch-manifest.jsonl'
    # Normalise once (tuples become lists) so identity matches the JSON saved in job.json.
    settings = json.loads(json.dumps({'cases': cases, 'load_source': load_source, 'overrides': overrides or {}, 'checks': checks}, allow_nan=False))
    template_hash = digest(template)
    counts = {'total': len(files), 'succeeded': 0, 'skipped': 0, 'failed': 0,
              'manifest': str(manifest), 'workers': workers, 'calculation_engine': 'CalcpadCE', 'native_execution_verified': False}
    started = time.monotonic()
    table = []
    with manifest_lock(root), manifest.open('a', encoding='utf-8') as log:
        def record(result):
            result['recorded_at'] = time.time()
            try:
                line = json.dumps(result, allow_nan=False)
            except (TypeError, ValueError):
                # Never drop the manifest line over an unserializable check summary.
                result['check_summary'] = None
                if 'suggestions' in result:
                    result['suggestions'] = {'error': 'suggestions not serializable'}
                line = json.dumps(result, allow_nan=False)
            log.write(line + '\n'); log.flush(); os.fsync(log.fileno())
            # The durable manifest line is written first; a bad summary only degrades the table row.
            try:
                table.append(check_row(result, base, suggest))
            except Exception:
                table.append(check_row({**result, 'check_summary': None, 'suggestions': None}, base, suggest))
            counts[result['status']] += 1
            if progress:
                progress(result)

        def jobs():
            for path in files:
                try:
                    if path.stat().st_size > 16 * 1024 * 1024:
                        raise ValueError('Raw report exceeds 16 MiB')
                    source_hash = digest(path)
                    identity = json.dumps([str(path), source_hash, template_hash, settings, calcpad.REVISION, calcpad.TRANSLATOR_VERSION, plan.identity], sort_keys=True, allow_nan=False)
                    job_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
                    stem = re.sub(r'[^A-Za-z0-9_-]+', '-', path.stem).strip('-')[:80] or 'worksheet'
                    yield {'job_id': job_id, 'source': str(path), 'source_sha256': source_hash,
                           'template': str(template), 'template_sha256': template_hash, 'settings': settings,
                           'output': str(root / job_id / (stem + '.mcdx')), 'resume': resume, 'suggest': suggest}
                except (ValueError, OSError) as exc:
                    record({'source': str(path), 'source_sha256': None, 'status': 'failed', 'error': str(exc),
                            'native_execution_verified': False})

        if workers == 1:
            _use_history(learned)
            try:
                for job in jobs():
                    record(_convert_job(job))
            finally:
                _use_history(None)
        else:
            iterator = iter(jobs())
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
                                     initializer=_use_history, initargs=(learned,)) as pool:
                pending = {}
                exhausted = False
                while pending or not exhausted:
                    while not exhausted and len(pending) < workers * 2:
                        job = next(iterator, None)
                        if job is None:
                            exhausted = True
                        else:
                            pending[pool.submit(_convert_job, job)] = job
                    if not pending:
                        break
                    completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in completed:
                        job = pending.pop(future)
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = {**job, 'status': 'failed', 'error': str(exc), 'native_execution_verified': False}
                        record(result)
        table.sort(key=lambda r: tuple(str(r[c]) for c in CHECK_COLUMNS))
        if check_rows is not None:
            check_rows.extend(table)
        columns = CHECK_COLUMNS + (SUGGEST_COLUMNS if suggest else ())
        if suggest:
            counts['suggestions'] = {
                'reports_with_suggestions': sum(1 for r in table if r['suggested_cases']
                                                and not r['suggested_cases'].startswith('unavailable')),
                'reports_unavailable': sum(1 for r in table if r['suggested_cases'].startswith('unavailable')),
                'history': None if learned is None else {'examples': len(learned[0]), 'skipped': learned[1]}}
        counts['checks'] = {'table': str(write_check_table(root, table, columns)),
                            'reports_with_failures': sum(1 for r in table if r['failed'] not in ('', 0)),
                            'reports_without_checks': sum(1 for r in table if r['note'] == 'no checks found'),
                            'reports_not_recorded': sum(1 for r in table if r['note'] == 'checks not recorded for this output')}
    counts['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(prog='mcdxkit batch', description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path, help='Report files and/or directories')
    parser.add_argument('--template', type=Path, default=default_template())
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--recursive', action='store_true', help='Search all subfolders for reports')
    parser.add_argument('--workers', type=int, default=min(4, os.cpu_count() or 1), help='Parallel worker processes, 1–32 (default: up to 4)')
    parser.add_argument('--resume', action='store_true', help='Skip completed outputs after verifying identity, hashes and package structure')
    parser.add_argument('--cases', type=case_ids)
    parser.add_argument('--load-source', choices=['effects', 'reactions'], default='effects')
    parser.add_argument('--set', action='append', default=[], metavar='VARIABLE=VALUE')
    parser.add_argument('--checks', default='default', metavar='SPEC',
                        help='Advisory review plug-ins: default, none, or a comma list such as default,my_check')
    parser.add_argument('--suggest', action='store_true',
                        help='Record advisory case suggestions and review flags in the manifest and check table; never applied')
    parser.add_argument('--history', type=Path, metavar='OUTPUT_DIR',
                        help='With --suggest: learn case naming from reviewed conversions in another output directory')
    parser.add_argument('--quiet', action='store_true', help='Suppress per-file progress on stderr')
    args = parser.parse_args(argv)
    try:
        overrides = {}
        for pair in args.set:
            key, value = pair.split('=', 1)
            if key in overrides:
                raise ValueError('Duplicate override: ' + key)
            overrides[key] = float(value)
        def progress(row):
            if not args.quiet:
                print(json.dumps({'source': row['source'], 'status': row['status'], 'error': row.get('error')}), file=sys.stderr, flush=True)
        rows = []
        summary = convert_batch(args.inputs, args.template, args.output_dir, workers=args.workers,
                                recursive=args.recursive, resume=args.resume, cases=args.cases,
                                load_source=args.load_source, overrides=overrides, checks=args.checks, progress=progress,
                                check_rows=rows, suggest=args.suggest, history=args.history)
        print(format_check_table(rows), file=sys.stderr)
        if args.suggest:
            found = summary['suggestions']
            print(f"Case suggestions: {found['reports_with_suggestions']} of {summary['total']} reports differ from the "
                  f"selection used; {found['reports_unavailable']} unavailable. Advisory only: nothing was applied.",
                  file=sys.stderr)
        print('Check summary table: ' + summary['checks']['table'], file=sys.stderr, flush=True)

        print(json.dumps(summary, indent=2))
        return 1 if summary['failed'] else 0
    except (ValueError, OSError) as exc:
        print('mcdxkit: ' + str(exc), file=sys.stderr)
        return 2
