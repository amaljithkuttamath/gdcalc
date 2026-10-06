"""HistoryStore adapters: past decisions the case-name classifier learns from.

AuditHistory reads completed conversion audits in ONE output directory, once, when it is
created, so plug-ins never touch the filesystem while they run. MemoryHistory is for tests
and for callers with their own store.
"""
import json
from pathlib import Path
from typing import Iterable, Tuple

Example = Tuple[str, bool]
MAX_AUDIT_BYTES = 2 * 1024 * 1024


class MemoryHistory:
    def __init__(self, examples: Iterable[Example] = ()):
        self._examples = tuple((str(name), bool(selected)) for name, selected in examples)

    def case_examples(self) -> Tuple[Example, ...]:
        return self._examples


def audit_examples(output_dir, limit: int = 500) -> Tuple[Example, ...]:
    """(case name, selected) from the newest ``limit`` audits under ``output_dir``.

    Unreadable, oversized, symlinked or malformed audits are skipped: history is advisory
    training data, and one damaged file must not stop inspection.
    """
    examples = []
    root = Path(output_dir)
    if not root.is_dir():
        return ()
    audits = sorted(root.rglob('*.audit.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for path in audits:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_AUDIT_BYTES:
                continue
            audit = json.loads(path.read_text(encoding='utf-8'))
            selected = {str(i) for i in audit['cases']}
            # case_names lists every final-summary case (audits from gdcalc 0.2.0 and earlier
            # only record the selected ones, which still teach the strength class).
            names = audit.get('case_names') or {str(c['id']): c.get('name') for c in audit['source_cases']}
            for ident, name in names.items():
                if isinstance(name, str):
                    examples.append((name, ident in selected))
        except (ValueError, KeyError, TypeError, OSError):
            continue
    return tuple(examples)


class AuditHistory(MemoryHistory):
    """Case-name decisions from the completed conversions in one output directory."""
    def __init__(self, output_dir, limit: int = 500):
        super().__init__(audit_examples(output_dir, limit))
        self.output_dir = Path(output_dir)
