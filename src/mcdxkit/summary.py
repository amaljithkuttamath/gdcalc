"""Write one CSV of per-case local loads for several reports or completed output directories."""
import argparse
import json
import sys
from pathlib import Path

from . import engine
from .generate import case_ids


def collect(inputs, *, cases=None, load_source=None):
    """Rows for report files and output directories (searched recursively for .audit.json).
    Any unreadable input fails the whole summary; nothing is skipped silently. Overlapping inputs
    (the same resolved file, or the same source bytes with the same basis and selection) are
    skipped and listed in the returned duplicates."""
    rows, keys, paths, duplicates = [], set(), set(), []

    def add(origin, found):
        key = engine.summary_key(found)
        if key in keys:
            duplicates.append(origin)
            return
        keys.add(key)
        rows.extend(found)

    for value in inputs:
        path = Path(value)
        if not path.exists():
            raise ValueError(f'Input does not exist: {path}')
        if path.is_dir():
            if cases is not None or load_source is not None:
                raise ValueError(f'{path}: output directories use the cases and load basis recorded in each audit; '
                                 'do not pass --cases or --load-source with a directory')
            audits = sorted(p for p in path.rglob('*.audit.json') if '_source' not in p.relative_to(path).parts)
            if not audits:
                raise ValueError(f'{path}: no .audit.json files found; pass GROUP report files directly')
            for audit in audits:
                origin = audit.relative_to(path).as_posix()
                if audit.resolve() in paths:
                    duplicates.append(origin)
                    continue
                paths.add(audit.resolve())
                add(origin, engine.summarize_audit(audit, origin=origin))
        elif path.suffix.lower() in ('.gp11t', '.txt'):
            if path.resolve() in paths:
                duplicates.append(str(value))
                continue
            paths.add(path.resolve())
            add(str(value), engine.summarize_report(path, cases=cases, load_source=load_source or 'effects',
                                                          origin=str(value)))
        else:
            raise ValueError(f'Unsupported input: {path.name}; use .gp11t/.txt reports or an output directory')
    if not keys:
        raise ValueError('No reports to summarize')
    return rows, len(keys), duplicates


def write(text, output):
    """Exclusive creation: an existing summary is never replaced. UTF-8 with BOM so Excel reads names."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open('x', encoding='utf-8-sig', newline='') as stream:
            try:
                stream.write(text)
            except BaseException:
                stream.close(); output.unlink(missing_ok=True); raise
    except FileExistsError:
        raise ValueError(f'{output} already exists; choose a new filename') from None


def main(argv=None, prog='mcdxkit summary'):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path, help='GROUP .gp11t/.txt reports and/or MCDXKit output directories')
    parser.add_argument('-o', '--output', required=True, type=Path, help='New .csv path (never overwritten)')
    parser.add_argument('--cases', type=case_ids, help='Explicit case IDs for every report input; default detects STR case names')
    parser.add_argument('--load-source', choices=['effects', 'reactions'], default=None,
                        help='Report inputs only: local pile effects (default) or local pile-top reactions for shear/moments')
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() != '.csv':
            raise ValueError('Summary filename must end in .csv')
        if args.output.exists():
            raise ValueError(f'{args.output} already exists; choose a new filename')
        rows, sources, duplicates = collect(args.inputs, cases=args.cases, load_source=args.load_source)
        write(engine.summary_csv(rows), args.output)
    except (ValueError, OSError) as exc:
        print('mcdxkit: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({'output': str(args.output), 'reports': sources, 'rows': len(rows),
                      'duplicates_skipped': duplicates, 'units': {'force': 'kip', 'moment': 'kip-in'}}, indent=2))
    return 0
