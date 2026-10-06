"""Run enabled review plug-ins in isolation and serialise a ``review-checks/1`` report.

Each plug-in runs in its own thread with a time budget, in a fixed order (built-ins, then
installed plug-ins by id). A plug-in that raises, overruns its budget or returns the wrong
types is recorded as a ``check_error`` and the others still run; the review never raises,
so inspection and conversion never fail because of it.

Python cannot kill a thread: a plug-in that overruns its budget is abandoned (it is a
daemon thread, so it does not keep the process alive) and may keep using CPU until it
returns. Its late results are discarded.
"""
import json
import math
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import registry, view as views
from .api import SCHEMA, Annotation, Context, Flag, NotApplicable, ReportView, Suggestion

# Seconds each plug-in may run on one report. The built-ins take milliseconds.
BUDGET_SECONDS = 5.0
RESULT_TYPES = {'check': Flag, 'annotator': Annotation, 'classifier': Suggestion}
OWNER_FIELDS = {'check': 'rule', 'annotator': 'annotator', 'classifier': 'classifier'}


@dataclass(frozen=True)
class Plan:
    """Enabled plug-ins for one --checks value, and load errors for plug-ins it named."""
    entries: Tuple[registry.Entry, ...]
    load_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def identity(self) -> List[List[str]]:
        """[id, version] pairs: what a cached review result depends on."""
        return [[e.id, e.plugin.version] for e in self.entries]


def prepare(checks: Optional[str] = 'default', catalog: Optional[registry.Catalog] = None) -> Plan:
    """Resolve a --checks value. Raises ValueError for an invalid value or unknown id."""
    entries, errors = registry.select(checks, catalog)
    return Plan(entries, errors)


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (frozenset, set)):
        return sorted(jsonable(v) for v in value)
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite number in result')
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'{type(value).__name__} is not a JSON value')


def serialise(item: Any) -> Dict[str, Any]:
    if isinstance(item, Flag):
        return {'rule': item.rule, 'case': item.case, 'component': item.component, 'message': item.message,
                'value': jsonable(item.value), 'compared_to': jsonable(item.compared_to), 'unit': item.unit,
                'evidence': {str(k): jsonable(v) for k, v in item.evidence}, 'actions': list(item.actions),
                'impact': {'envelope': bool(item.impact.envelope), 'selection': bool(item.impact.selection),
                           'magnitude': jsonable(float(item.impact.magnitude)),
                           'components': list(item.impact.components)}}
    if isinstance(item, Annotation):
        return {'annotator': item.annotator, 'kind': item.kind, 'case': item.case, 'component': item.component,
                'data': jsonable(item.data)}
    return {'classifier': item.classifier, 'case': item.case, 'kind': item.kind, 'value': item.value,
            'confidence': jsonable(item.confidence), 'evidence': list(item.evidence), 'basis': jsonable(item.basis)}


def _call(plugin: Any, view: ReportView, ctx: Context, budget: float) -> List[Any]:
    method = getattr(plugin, registry.KINDS[plugin.kind])
    box: Dict[str, Any] = {}

    def target():
        try:
            box['result'] = list(method(view, ctx))
        except BaseException as exc:  # noqa: BLE001 - reported to the caller thread
            box['error'] = exc

    thread = threading.Thread(target=target, name='mcdxkit-review-' + plugin.id, daemon=True)
    thread.start()
    thread.join(budget)
    if thread.is_alive():
        raise TimeoutError(f'exceeded its {budget:g} s time budget')
    if 'error' in box:
        raise box['error']
    return box['result']


def _validate(plugin: Any, results: Sequence[Any], view: ReportView) -> List[Dict[str, Any]]:
    expected = RESULT_TYPES[plugin.kind]
    owner = OWNER_FIELDS[plugin.kind]
    case_ids = {c.id for c in view.cases}
    rows = []
    for item in results:
        if not isinstance(item, expected):
            raise TypeError(f'returned {type(item).__name__}; a {plugin.kind} must return {expected.__name__}')
        if getattr(item, owner) != plugin.id:
            raise ValueError(f'returned a result whose {owner} is {getattr(item, owner)!r}, not {plugin.id!r}')
        if item.case is not None and item.case not in case_ids:
            raise ValueError(f'returned a result for case {item.case}, which is not in the report')
        row = serialise(item)
        json.dumps(row, allow_nan=False)
        rows.append(row)
    return rows


def empty(load_source: Optional[str]) -> Dict[str, Any]:
    return {'schema': SCHEMA, 'advisory': True, 'load_source': load_source, 'checks_run': [], 'skipped': [],
            'flags': [], 'annotations': [], 'suggestions': [], 'errors': []}


def review(parsed: Mapping[str, Any], selected: Optional[Sequence[int]] = None, *, plan: Optional[Plan] = None,
           history: Any = None, budget: Optional[float] = None) -> Dict[str, Any]:
    """Advisory review of a group_report.parse() dict. Never raises.

    ``selected`` is the case selection in use, if any. ``history`` is a HistoryStore or None.
    """
    plan = plan if plan is not None else prepare('default')
    budget = BUDGET_SECONDS if budget is None else budget
    report = empty(parsed.get('load_source') if isinstance(parsed, Mapping) else None)
    for name, message in plan.load_errors:
        report['errors'].append({'type': 'check_error', 'id': name, 'version': None, 'message': message})
    if not plan.entries:
        return report
    try:
        view = views.build(parsed, selected)
    except Exception as exc:  # noqa: BLE001 - recorded explicitly, never presented as clean
        report['errors'].append({'type': 'review_error', 'id': None, 'version': None,
                                 'message': 'review view unavailable: ' + (str(exc) or type(exc).__name__)})
        return report
    ctx = Context(history=history)
    buckets = {'check': 'flags', 'annotator': 'annotations', 'classifier': 'suggestions'}
    for entry in plan.entries:
        plugin = entry.plugin
        record = {'id': plugin.id, 'version': plugin.version, 'kind': plugin.kind, 'source': entry.source}
        try:
            record['params'] = jsonable(plugin.params)
            rows = _validate(plugin, _call(plugin, view, ctx, budget), view)
        except NotApplicable as exc:
            report['skipped'].append({'id': plugin.id, 'reason': str(exc)})
            record['status'] = 'skipped'
        except Exception as exc:  # noqa: BLE001 - one plug-in must not stop the others
            report['errors'].append({'type': 'check_error', 'id': plugin.id, 'version': plugin.version,
                                     'message': f'{type(exc).__name__}: {exc}'})
            record['status'] = 'error'
        else:
            report[buckets[plugin.kind]].extend(rows)
            record['status'] = 'ok'
        record.setdefault('params', None)
        report['checks_run'].append(record)
    return report


def open_flags(report: Optional[Mapping[str, Any]]) -> Optional[int]:
    """Flags without an engineer decision, or None when there is no review block."""
    if not isinstance(report, Mapping):
        return None
    decided = {(d.get('rule'), d.get('case'), d.get('component')) for d in report.get('decisions') or ()}
    return sum((f['rule'], f['case'], f['component']) not in decided for f in report.get('flags', ()))
