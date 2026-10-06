"""HistoryStore adapters: past decisions the case-name classifier learns from, and the past
jobs the similar-jobs annotator compares against.

AuditHistory reads completed conversion audits in ONE output directory, once, when it is
created, so plug-ins never touch the filesystem while they run. It never looks outside that
directory: the workspace is not tenant-isolated, so history must not cross output directories.
MemoryHistory is for tests and for callers with their own store.
"""
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from .api import COMPONENTS, PastJob, frozen_mapping

Example = Tuple[str, bool]
MAX_AUDIT_BYTES = 2 * 1024 * 1024
# Audits from before units were recorded were parsed under these (the parser enforces them).
DEFAULT_UNITS = frozen_mapping({'force': 'kip', 'moment': 'kip-in'})
SHA256 = re.compile(r'[0-9a-f]{64}')


class MemoryHistory:
    def __init__(self, examples: Iterable[Example] = (), skipped: int = 0, jobs: Iterable[PastJob] = ()):
        self._examples = tuple((str(name), bool(selected)) for name, selected in examples)
        self._jobs = tuple(jobs)
        # Audits that could not be read; reported in the classifier's basis, never hidden.
        self.skipped = skipped

    def case_examples(self) -> Tuple[Example, ...]:
        return self._examples

    def past_jobs(self) -> Tuple[PastJob, ...]:
        return self._jobs


def newest(paths: Iterable[Path], limit: int) -> Tuple[List[Path], int]:
    """The ``limit`` most recently modified paths, and how many could not be stat'ed
    (dangling symlinks, files removed or unreadable meanwhile); those are skipped."""
    dated, skipped = [], 0
    for path in paths:
        try:
            dated.append((path.stat().st_mtime, path))
        except OSError:
            skipped += 1
    dated.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in dated[:limit]], skipped


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('not a finite number')
    return float(value)


def _job(audit: Any, path: Path, root: Path, mtime: float) -> Optional[PastJob]:
    """A PastJob from one audit's JSON, or None when the audit does not record what is needed.
    The name is relative to ``root``; recorded absolute paths in the audit are never used."""
    try:
        envelope = audit['envelope']
        values = {key: _number(envelope[key]) for key in COMPONENTS}
        cases = tuple(audit['cases'])
        if not cases or len(cases) > 1000 or not all(type(i) is int for i in cases):
            return None
        load_source = audit['load_source']
        if load_source not in ('effects', 'reactions'):
            return None
        units = audit.get('units')
        if units is None:
            units = DEFAULT_UNITS
        elif not isinstance(units, dict) or not all(isinstance(units.get(k), str) for k in DEFAULT_UNITS):
            return None
        digest = audit.get('source_sha256')
        template = audit.get('template_name')
        if not isinstance(template, str) or not template or len(template) > 200 or any(
                c in template for c in '/\\') or any(ord(c) < 32 for c in template):
            template = None
        name = path.with_name(path.name[:-len('.audit.json')] + '.mcdx').relative_to(root).as_posix()
        date = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime('%Y-%m-%d')
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError):
        return None
    return PastJob(name=name[:300], date=date, envelope=frozen_mapping(values), cases=cases,
                   load_source=load_source, units=frozen_mapping({k: units[k][:20] for k in DEFAULT_UNITS}),
                   source_sha256=digest if isinstance(digest, str) and SHA256.fullmatch(digest) else None,
                   template=template)


def read_audits(output_dir, limit: int = 500) -> Tuple[Tuple[Example, ...], Tuple[PastJob, ...], int]:
    """Case-name examples and past jobs from the newest ``limit`` audits under ``output_dir``,
    and the number of audits skipped for the examples.

    Unreadable, dangling, oversized, symlinked, outside-the-directory or malformed audits are
    skipped (and counted): history is advisory, and one damaged file must not stop inspection.
    An audit without a usable envelope still teaches case names, and the reverse.
    """
    examples: List[Example] = []
    jobs: List[PastJob] = []
    root = Path(output_dir)
    if not root.is_dir():
        return (), (), 0
    try:
        base = root.resolve()
    except OSError:
        return (), (), 0
    audits, skipped = newest(root.rglob('*.audit.json'), limit)
    for path in audits:
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(base):
                skipped += 1
                continue
            stat = path.stat()
            if stat.st_size > MAX_AUDIT_BYTES:
                skipped += 1
                continue
            audit = json.loads(path.read_text(encoding='utf-8'))
            job = _job(audit, path, root, stat.st_mtime) if isinstance(audit, dict) else None
            if job is not None:
                jobs.append(job)
            selected = {str(i) for i in audit['cases']}
            # case_names lists every final-summary case (audits from gdcalc 0.2.0 and earlier
            # only record the selected ones, which still teach the strength class).
            names = audit.get('case_names') or {str(c['id']): c.get('name') for c in audit['source_cases']}
            found = [(name, ident in selected) for ident, name in names.items() if isinstance(name, str)]
        except (ValueError, KeyError, TypeError, AttributeError, OSError, RecursionError):
            skipped += 1
            continue
        examples.extend(found)
    return tuple(examples), tuple(jobs), skipped


def audit_examples(output_dir, limit: int = 500) -> Tuple[Tuple[Example, ...], int]:
    """(case name, selected) from the newest ``limit`` audits under ``output_dir``, and the
    number of audits skipped."""
    examples, _, skipped = read_audits(output_dir, limit)
    return examples, skipped


class AuditHistory(MemoryHistory):
    """Case-name decisions and past jobs from the completed conversions in one output directory."""
    def __init__(self, output_dir, limit: int = 500):
        examples, jobs, skipped = read_audits(output_dir, limit)
        super().__init__(examples, skipped, jobs)
