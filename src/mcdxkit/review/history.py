"""HistoryStore adapters: past decisions the case-name classifier learns from.

AuditHistory reads completed conversion audits in ONE output directory, once, when it is
created, so plug-ins never touch the filesystem while they run. MemoryHistory is for tests
and for callers with their own store.
"""
import json
from pathlib import Path
from typing import Iterable, List, Tuple

Example = Tuple[str, bool]
MAX_AUDIT_BYTES = 2 * 1024 * 1024


class MemoryHistory:
    def __init__(self, examples: Iterable[Example] = (), skipped: int = 0):
        self._examples = tuple((str(name), bool(selected)) for name, selected in examples)
        # Audits that could not be read; reported in the classifier's basis, never hidden.
        self.skipped = skipped

    def case_examples(self) -> Tuple[Example, ...]:
        return self._examples


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


def audit_examples(output_dir, limit: int = 500) -> Tuple[Tuple[Example, ...], int]:
    """(case name, selected) from the newest ``limit`` audits under ``output_dir``, and the
    number of audits skipped.

    Unreadable, dangling, oversized, symlinked or malformed audits are skipped and counted:
    history is advisory training data, and one damaged file must not stop inspection.
    """
    examples = []
    root = Path(output_dir)
    if not root.is_dir():
        return (), 0
    audits, skipped = newest(root.rglob('*.audit.json'), limit)
    for path in audits:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_AUDIT_BYTES:
                skipped += 1
                continue
            audit = json.loads(path.read_text(encoding='utf-8'))
            selected = {str(i) for i in audit['cases']}
            # case_names lists every final-summary case (audits from gdcalc 0.2.0 and earlier
            # only record the selected ones, which still teach the strength class).
            names = audit.get('case_names') or {str(c['id']): c.get('name') for c in audit['source_cases']}
            found = [(name, ident in selected) for ident, name in names.items() if isinstance(name, str)]
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            skipped += 1
            continue
        examples.extend(found)
    return tuple(examples), skipped


class AuditHistory(MemoryHistory):
    """Case-name decisions from the completed conversions in one output directory."""
    def __init__(self, output_dir, limit: int = 500):
        super().__init__(*audit_examples(output_dir, limit))
