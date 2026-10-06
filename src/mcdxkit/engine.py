"""Public conversion engine independent of CLI, agent host, HTTP and Mathcad."""
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from . import group_report, mcdx, calcpad
from .review import runner as review_runner


def _read_report(path, load_source):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise ValueError('Raw report exceeds 16 MiB')
    raw=path.read_bytes()
    if b'\x00' in raw:raise ValueError('Expected a text GROUP report, not a binary workbook')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    return raw,group_report.parse(text,load_source)


def review_checks(parsed, selected=None, *, checks='default', history=None, plan=None):
    """Advisory review-checks/1 block. Never fails the caller; an invalid ``checks`` value raises
    ValueError before any work when ``plan`` is not supplied."""
    plan=plan if plan is not None else review_runner.prepare(checks)
    return review_runner.review(parsed,selected,plan=plan,history=history)


def _governing(block):
    rows={a['component']:a['data'] for a in block['annotations'] if a['kind']=='governing'}
    return rows or None


def _case_suggestions(parsed, block):
    """Summarise classifier suggestions; recommended strength cases are checked with the same
    select rules as a manual selection, and never applied here."""
    rows=[s for s in block['suggestions'] if s['kind']=='limit_state']
    if not rows:return None
    names={c['id']:c['name'] for c in parsed['cases']}
    recommended=[s['case'] for s in rows if s['value']=='strength']
    issue=None
    try:group_report.select(parsed,recommended)
    except ValueError as exc:issue=str(exc)
    basis=rows[0]['basis']
    return {'classifier':rows[0]['classifier'],'trained_on':{'seed':basis.get('seed'),'history':basis.get('history')},
            'cases':[{'id':s['case'],'name':names.get(s['case']),'category':s['value'] or 'unknown',
                      'confidence':s['confidence'],'evidence':s['evidence'],'stage':s['basis'].get('stage')} for s in rows],
            'recommended_cases':recommended,'selection_issue':issue,
            'unresolved_case_ids':[s['case'] for s in rows if s['value'] is None]}


DECISIONS=('included_case','kept_service','will_fix_in_group')
DECISION_FIELDS={'rule','case','component','decision','note','decided_at'}


def _decisions(block, decisions):
    """Validate engineer decisions on raised flags. Each names a flag (rule, case, component),
    one of DECISIONS, an optional note and an ISO 8601 decided_at time."""
    if decisions is None:return None
    if not isinstance(decisions,(list,tuple)) or len(decisions)>500:
        raise ValueError('review_decisions must be a list of at most 500 decisions')
    flags={(f['rule'],f['case'],f['component']) for f in block['flags']}
    result=[];seen=set()
    for item in decisions:
        if not isinstance(item,dict) or set(item)-DECISION_FIELDS or not {'rule','case','component','decision','decided_at'}<=set(item):
            raise ValueError('Each review decision is {rule, case, component, decision, note, decided_at}')
        key=(item['rule'],item['case'],item['component'])
        if key not in flags:
            raise ValueError(f'Review decision does not match a raised flag: {key}')
        if key in seen:raise ValueError(f'More than one review decision for flag {key}')
        seen.add(key)
        if item['decision'] not in DECISIONS:
            raise ValueError('Review decision must be one of '+', '.join(DECISIONS))
        note=item.get('note')
        if note is not None and (not isinstance(note,str) or len(note)>500):
            raise ValueError('Review decision note must be text of at most 500 characters')
        try:datetime.fromisoformat(item['decided_at'])
        except (TypeError,ValueError):raise ValueError('Review decision decided_at must be an ISO 8601 date-time')
        result.append({'rule':key[0],'case':key[1],'component':key[2],'decision':item['decision'],
                       'note':note,'decided_at':item['decided_at']})
    return result


def review_note(block):
    """Plain-text worksheet note, written only when at least one review decision exists."""
    decisions=block.get('decisions')
    if not decisions:return None
    run=sum(c['kind']=='check' and c['status']=='ok' for c in block['checks_run'])
    raised=len(block['flags'])
    items=f'{raised} item{"" if raised==1 else "s"} raised'
    reviewed='reviewed by the engineer' if len(decisions)>=raised else f'{len(decisions)} reviewed by the engineer'
    return (f'Automated input checks: {run} run, {items}, {reviewed}\n'
            'Checks review the GROUP summary for consistency. They do not verify the design.')


def inspect_report(report, *, cases=None, load_source='effects', checks='default', history=None):
    """Inspect available cases; selection_required explains unresolved classification.

    ``checks`` selects review plug-ins ('default', 'none' or a comma list of ids); ``history``
    is an optional review.api.HistoryStore the case-name classifier learns from."""
    plan=review_runner.prepare(checks)
    _,parsed=_read_report(report,load_source)
    issue=None
    try:selected=group_report.select(parsed,cases)
    except ValueError as exc:
        if cases is not None:raise
        selected=[];issue=str(exc)
    block=review_checks(parsed,[c['id'] for c in selected],plan=plan,history=history)
    return {'source':Path(report).name,'cases':[{'id':c['id'],'name':c['name']} for c in parsed['cases']],
            'selected_cases':[c['id'] for c in selected],'selection_required':issue,
            'load_source':load_source,'envelope':group_report.envelope(selected) if selected else None,
            'governing':_governing(block) if selected else None,
            'case_suggestions':_case_suggestions(parsed,block),
            'review_checks':block,
            'largest_observed_pile_id':max((p for c in parsed['cases'] for p in c['pile_ids']),default=0)}


def convert(report, template, output, *, cases=None, load_source='effects', title=None, overrides=None,
            checks='default', review_decisions=None):
    """Generate .mcdx, executable .cpd, calculated .html and .audit.json. Never overwrite sources or existing outputs.

    The advisory review (``checks``) and any ``review_decisions`` are recorded in the audit. Only when
    a decision exists does the worksheet gain a plain-text "Automated input checks" note; otherwise
    the .mcdx, .cpd and .html are identical with checks on or off."""
    plan=review_runner.prepare(checks)
    report=Path(report).resolve();template=Path(template).resolve();output=Path(output).resolve()
    audit=output.with_suffix('.audit.json')
    if output.suffix.lower()!='.mcdx':raise ValueError('Output filename must end in .mcdx')
    if output in (report,template) or audit in (report,template):raise ValueError('Output cannot replace a source')
    cpd=output.with_suffix('.cpd'); calculated=output.with_suffix('.html')
    if any(p.exists() for p in (output,audit,cpd,calculated)):raise ValueError('Output artifact already exists; choose a new filename')
    if not template.is_file():raise ValueError('Template not found. Provide --template /path/to/reference.mcdx')
    raw,parsed=_read_report(report,load_source)
    selected=group_report.select(parsed,cases)
    block=review_checks(parsed,[c['id'] for c in selected],plan=plan)
    decisions=_decisions(block,review_decisions)
    if decisions is not None:block['decisions']=decisions
    output.parent.mkdir(parents=True,exist_ok=True)
    # Stage both artifacts before publishing either. Hard links fail if a destination
    # was concurrently created and avoid replacing it; all paths share a filesystem.
    with tempfile.TemporaryDirectory(prefix='.mcdxkit-',dir=output.parent) as folder:
        staged=Path(folder)/'worksheet.mcdx'
        result=mcdx.generate(template,staged,selected,report.name,title,overrides,geometry_cases=parsed['cases'],
                             review_note=review_note(block))
        result.update({'output':str(output),'audit':str(audit),'source_sha256':hashlib.sha256(raw).hexdigest(),
                       'geometry_case_ids':[c['id'] for c in parsed['cases']],
                       'case_names':{str(c['id']):c['name'] for c in parsed['cases']},
                       'review_checks':block})
        cpd_staged=Path(folder)/'worksheet.cpd'; html_staged=Path(folder)/'worksheet.html'
        calculation=calcpad.calculate(staged,cpd_staged,html_staged)
        result.update({'calculation':calculation,'open_worksheet':str(cpd),'calculated_worksheet':str(calculated)})
        audit_staged=Path(folder)/'audit.json'
        audit_staged.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        published=[]
        try:
            # Audit is the completion marker, published last.
            for source,destination in ((staged,output),(cpd_staged,cpd),(html_staged,calculated),(audit_staged,audit)):
                os.link(source,destination);published.append((source,destination))
        except OSError:
            for source,destination in published:
                if destination.exists() and os.path.samefile(destination,source):destination.unlink()
            raise
    return result


def validate(worksheet):
    """Check ZIP/XML relationships. Does not execute Mathcad or validate PTC schemas."""
    return mcdx.validate(worksheet)
