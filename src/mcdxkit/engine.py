"""Public conversion engine independent of CLI, agent host, HTTP and Mathcad."""
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from . import group_report, mcdx, calcpad
from . import checks as worksheet_checks
from .review import runner as review_runner



def _read_raw(path):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise ValueError('Raw report exceeds 16 MiB')
    return path.read_bytes()


def _decode(raw):
    if b'\x00' in raw:raise ValueError('Expected a text GROUP report, not a binary workbook')
    try:return raw.decode('utf-8-sig')
    except UnicodeDecodeError:return raw.decode('cp1252')


def _parse_raw(raw, load_source):
    return group_report.parse(_decode(raw),load_source)


def _read_report(path, load_source):
    raw=_read_raw(path)
    return raw,_parse_raw(raw,load_source)


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
    return {'classifier':rows[0]['classifier'],'trained_on':{'seed':basis.get('seed'),'history':basis.get('history'),
                                                     'history_skipped':basis.get('history_skipped')},
            'cases':[{'id':s['case'],'name':names.get(s['case']),'category':s['value'] or 'unknown',
                      'confidence':s['confidence'],'evidence':s['evidence'],'stage':s['basis'].get('stage')} for s in rows],
            'recommended_cases':recommended,'selection_issue':issue,
            'unresolved_case_ids':[s['case'] for s in rows if s['value'] is None]}


DECISIONS=('included_case','kept_service','will_fix_in_group')
DECISION_FIELDS={'rule','case','component','decision','note','decided_at'}
# ISO 8601 date and time (minutes required; seconds, milliseconds or microseconds optional),
# with an optional Z or +hh:mm offset. Explicit so Python 3.10 and 3.12 accept the same values.
DECIDED_AT=re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{3}(?:\d{3})?)?)?(?:Z|[+-]\d{2}:\d{2})?')


def _decided_at(value):
    if not isinstance(value,str) or not DECIDED_AT.fullmatch(value):return False
    try:datetime.fromisoformat(value[:-1]+'+00:00' if value.endswith('Z') else value)
    except ValueError:return False
    return True


def _decisions(block, decisions):
    """Validate engineer decisions on raised flags. Each names a flag (rule, case, component),
    one of DECISIONS, an optional note and an ISO 8601 decided_at date and time.

    A decision whose rule ran successfully must match a flag it raised. When the rule did not
    run successfully (error, timeout, skipped or not enabled) the decision cannot be checked;
    it is kept in the audit with ``unverified: true`` instead of failing the conversion."""
    if decisions is None:return None
    if not isinstance(decisions,(list,tuple)) or len(decisions)>500:
        raise ValueError('review_decisions must be a list of at most 500 decisions')
    flags={(f['rule'],f['case'],f['component']) for f in block['flags']}
    ran={c['id'] for c in block['checks_run'] if c['kind']=='check' and c['status']=='ok'}
    result=[];seen=set()
    for item in decisions:
        if not isinstance(item,dict) or set(item)-DECISION_FIELDS or not {'rule','case','component','decision','decided_at'}<=set(item):
            raise ValueError('Each review decision is {rule, case, component, decision, note, decided_at}')
        if (not isinstance(item['rule'],str) or not isinstance(item['decision'],str)
                or not (item['case'] is None or (isinstance(item['case'],int) and not isinstance(item['case'],bool)))
                or not (item['component'] is None or isinstance(item['component'],str))):
            raise ValueError('Review decision rule and decision are text, case is an integer or null, component is text or null')
        key=(item['rule'],item['case'],item['component'])
        if key in seen:raise ValueError(f'More than one review decision for flag {key}')
        seen.add(key)
        if item['decision'] not in DECISIONS:
            raise ValueError('Review decision must be one of '+', '.join(DECISIONS))
        note=item.get('note')
        if note is not None and (not isinstance(note,str) or len(note)>500):
            raise ValueError('Review decision note must be text of at most 500 characters')
        if not _decided_at(item['decided_at']):
            raise ValueError('Review decision decided_at must be an ISO 8601 date and time such as 2026-10-06T09:30:00Z')
        unverified=key not in flags
        if unverified and key[0] in ran:
            raise ValueError(f'Review decision does not match a raised flag: {key}')
        row={'rule':key[0],'case':key[1],'component':key[2],'decision':item['decision'],
             'note':note,'decided_at':item['decided_at']}
        if unverified:row['unverified']=True
        result.append(row)
    return result


def review_note(block):
    """Plain-text worksheet note, written only when at least one review decision exists."""
    decisions=block.get('decisions')
    if not decisions:return None
    run=sum(c['kind']=='check' and c['status']=='ok' for c in block['checks_run'])
    raised=len(block['flags'])
    items=f'{raised} item{"" if raised==1 else "s"} raised'
    verified=sum(not d.get('unverified') for d in decisions)
    reviewed=('reviewed by the engineer' if verified>=raised else f'{verified} reviewed by the engineer') if verified else 'no verified review decisions'
    unverified=len(decisions)-verified
    if unverified:reviewed+=f', {unverified} unverified decision(s)'
    return (f'Automated input checks: {run} run, {items}, {reviewed}\n'
            'Checks review the GROUP summary for consistency. They do not verify the design.')


def inspect_report(report, *, cases=None, load_source='effects', checks='default', history=None):
    """Inspect available cases; selection_required explains unresolved classification.

    ``checks`` selects review plug-ins ('default', 'none', a comma list of ids, or a plan from
    review.runner.prepare() resolved once by a long-running caller); ``history``
    is an optional review.api.HistoryStore the case-name classifier learns from."""
    plan=review_runner.prepare(checks)
    _,parsed=_read_report(report,load_source)
    return _inspect(Path(report).name,parsed,cases,load_source,plan,history)


def _inspect(name, parsed, cases, load_source, plan, history=None):
    issue=None
    try:selected=group_report.select(parsed,cases)
    except ValueError as exc:
        if cases is not None:raise
        selected=[];issue=str(exc)
    block=review_runner.review(parsed,[c['id'] for c in selected],plan=plan,history=history)
    return {'source':name,'cases':[{'id':c['id'],'name':c['name']} for c in parsed['cases']],
            'selected_cases':[c['id'] for c in selected],'selection_required':issue,
            'load_source':load_source,'envelope':group_report.envelope(selected) if selected else None,
            'governing':_governing(block) if selected else None,
            'case_suggestions':_case_suggestions(parsed,block),
            'review_checks':block,
            'largest_observed_pile_id':max((p for c in parsed['cases'] for p in c['pile_ids']),default=0)}


COMPARE_SCHEMA='report-compare/1'
COMPONENT_UNITS={'P':'force','Vy':'force','Vz':'force','My':'moment','Mz':'moment'}
COMPONENT_LABELS={'P':'Axial load','Vy':'Shear Vy','Vz':'Shear Vz','My':'Moment My','Mz':'Moment Mz'}


class UnitMismatchError(ValueError):
    """Two reports name different force or moment units; compare_reports never converts."""


def _change_pct(old, new):
    if old==new:return 0.0
    if old==0:return None
    return (new-old)/abs(old)*100


def _plural(count, word):
    return f'{count} {word}' if count==1 else f'{count} {word}s'


def _compare_headline(result):
    """One line: the largest envelope change (and its new governing case), case and review changes."""
    parts=[]
    unresolved=[side.upper() for side in ('old','new') if result[side]['selection_required']]
    if unresolved:
        parts.append('Envelope not compared: case selection unresolved in '+' and '.join(unresolved)+'; pass explicit cases')
    else:
        changed=[c for c in result['components'] if c['governing_changed'] or c['change_pct']!=0]
        if changed:
            lead=max(changed,key=lambda c:float('inf') if c['change_pct'] is None else abs(c['change_pct']))
            label=COMPONENT_LABELS[lead['component']]
            if lead['change_pct'] is None:text=f'{label} now nonzero (was 0)'
            elif lead['change_pct']==0:text=f'{label} unchanged'
            elif round(lead['change_pct'],1)==0:text=f'{label} changed by less than 0.1%'
            else:text=f"{label} {'up' if lead['change_pct']>0 else 'down'} {abs(lead['change_pct']):.1f}%"
            if lead['governing_changed']:text+=f" (case {lead['governing_new']['case']} now governs)"
            if len(changed)>1:text+=f"; {_plural(len(changed)-1,'other component')} changed"
            parts.append(text)
        else:parts.append('Envelope loads and governing cases unchanged')
    cases=result['cases']
    counts=[_plural(len(cases[k]),'case')+' '+k for k in ('added','removed','renamed') if cases[k]]
    if counts:parts.append(', '.join(counts))
    selection=cases['selection']
    if selection['changed']:
        parts.append('selected cases '+(','.join(map(str,selection['old'])) or 'none')+' -> '+(','.join(map(str,selection['new'])) or 'none'))
    review=result['review']
    if review['checks']:
        appeared,cleared=len(review['appeared']),len(review['cleared'])
        if appeared:parts.append(_plural(appeared,'new item')+' to review')
        if cleared:parts.append(_plural(cleared,'review item')+' cleared')
        if not appeared and not cleared:parts.append('no new review items')
    return '; '.join(parts)


def compare_reports(old, new, *, cases=None, load_source='effects', checks='default'):
    """Compare two GROUP reports (an earlier and a revised run): envelope and governing case per
    component, cases added/removed/renamed (matched by ID) and advisory review flags that appeared
    or cleared. ``cases`` and ``load_source`` apply to both reports, as in inspect_report.

    Read-only. Reports whose unit headers differ raise UnitMismatchError (a ValueError); values are
    never converted. Unresolved default selection leaves the envelope uncompared, with the reason in
    ``old``/``new.selection_required``; an explicit invalid selection raises ValueError."""
    plan=review_runner.prepare(checks)
    sides={}
    for label,report in (('old',old),('new',new)):
        report=Path(report)
        try:
            raw=_read_raw(report);text=_decode(raw)
            sides[label]={'path':report,'raw':raw,'text':text,'units':group_report.units(text)}
        except ValueError as exc:raise ValueError(f'{label.upper()} {report.name}: {exc}') from exc
    units={k:v['units'] for k,v in sides.items()}
    if units['old'] and units['new'] and units['old']!=units['new']:
        def named(u):return f"force {u['force']}, moment {u['moment']}"
        raise UnitMismatchError(f"Units differ: OLD {sides['old']['path'].name} uses {named(units['old'])}; "
                                f"NEW {sides['new']['path'].name} uses {named(units['new'])}. "
                                'Compare does not convert units; rerun GROUP with matching units')
    info={}
    for label,side in sides.items():
        try:info[label]=_inspect(side['path'].name,group_report.parse(side['text'],load_source),cases,load_source,plan)
        except ValueError as exc:raise ValueError(f"{label.upper()} {side['path'].name}: {exc}") from exc
    a,b=info['old'],info['new']
    def side(label):
        data=info[label]
        return {'source':data['source'],'sha256':hashlib.sha256(sides[label]['raw']).hexdigest(),
                'cases':data['cases'],'selected_cases':data['selected_cases'],
                'selection_required':data['selection_required'],'envelope':data['envelope']}
    def governing(data,key):
        row=(data['governing'] or {}).get(key)
        return None if row is None else {'case':row['case'],'name':row['case_name']}
    components=[]
    for key in group_report.COMPONENTS:
        before=a['envelope'][key] if a['envelope'] else None
        after=b['envelope'][key] if b['envelope'] else None
        was,now=governing(a,key),governing(b,key)
        components.append({'component':key,'unit':'kip' if COMPONENT_UNITS[key]=='force' else 'kip-in',
                           'old':before,'new':after,
                           'change_pct':_change_pct(before,after) if before is not None and after is not None else None,
                           'governing_old':was,'governing_new':now,
                           'governing_changed':bool(was and now and was['case']!=now['case'])})
    names_old={c['id']:c['name'] for c in a['cases']};names_new={c['id']:c['name'] for c in b['cases']}
    case_changes={'added':[{'id':i,'name':names_new[i]} for i in sorted(names_new.keys()-names_old.keys())],
                  'removed':[{'id':i,'name':names_old[i]} for i in sorted(names_old.keys()-names_new.keys())],
                  'renamed':[{'id':i,'old_name':names_old[i],'new_name':names_new[i]}
                             for i in sorted(names_old.keys()&names_new.keys()) if names_old[i]!=names_new[i]],
                  'selection':{'old':a['selected_cases'],'new':b['selected_cases'],
                               'changed':a['selected_cases']!=b['selected_cases']}}
    # A flag is the same item in both reports when rule, case ID and component match; its message
    # and values may differ with the loads. A rule may raise several flags with one key.
    def keyed(data):return [((f['rule'],f['case'],f['component']),f) for f in data['review_checks']['flags']]
    before_flags,after_flags=keyed(a),keyed(b)
    before_keys,after_keys={k for k,_ in before_flags},{k for k,_ in after_flags}
    review={'advisory':True,'checks':plan.identity,
            'appeared':[f for k,f in after_flags if k not in before_keys],
            'cleared':[f for k,f in before_flags if k not in after_keys],
            'unchanged':sum(k in before_keys for k,_ in after_flags),
            'errors':{'old':a['review_checks']['errors'],'new':b['review_checks']['errors']}}
    result={'schema':COMPARE_SCHEMA,'old':side('old'),'new':side('new'),'load_source':load_source,
            'units':{'force':'kip','moment':'kip-in'},'components':components,'cases':case_changes,'review':review}
    result['headline']=_compare_headline(result)
    return result


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
    block=review_runner.review(parsed,[c['id'] for c in selected],plan=plan)
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
        # Outcomes are read from the published snapshot, never recalculated.
        found,summary=worksheet_checks.extract(html_staged.read_text(encoding='utf-8'),calculation['region_lines'])
        result.update({'checks':found,'check_summary':summary})
        audit_staged=Path(folder)/'audit.json'
        audit_staged.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
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


SUMMARY_MEASURES=(('P','kip'),('Vy','kip'),('Vz','kip'),('My','kip_in'),('Mz','kip_in'))
SUMMARY_COLUMNS=(['report','origin','source_sha256','load_source','case_id','case_name','selected']+
                 [key+'_'+unit for key,unit in SUMMARY_MEASURES]+['governs'])


def _summary_rows(name, origin, digest, parsed, selected):
    """One row per final-summary case. Values are that case's component maxima (P: max compression,
    others: max magnitude); `governs` names measures for which the case is the selected-case maximum."""
    governing=group_report.envelope(selected)
    chosen={c['id'] for c in selected}
    rows=[]
    for case in parsed['cases']:
        values=group_report.envelope([case])
        row={'report':name,'origin':origin,'source_sha256':digest,
             'load_source':parsed['load_source'],'case_id':case['id'],'case_name':case['name'],
             'selected':case['id'] in chosen}
        row.update({key+'_'+unit:values[key] for key,unit in SUMMARY_MEASURES})
        row['governs']=[key for key,_ in SUMMARY_MEASURES if case['id'] in chosen and values[key]==governing[key]]
        rows.append(row)
    return rows


def _select(label, parsed, cases):
    try:return group_report.select(parsed,cases)
    except ValueError as exc:raise ValueError(f'{label}: {exc}') from exc


def summary_key(rows):
    """Identity of one summarized input: identical source bytes, load basis and selection give identical rows."""
    return (rows[0]['source_sha256'],rows[0]['load_source'],tuple(r['case_id'] for r in rows if r['selected']))


def summarize_report(report, *, cases=None, load_source='effects', origin=None):
    """Summary rows for one report. Unresolved or invalid case selection raises ValueError."""
    report=Path(report)
    raw,parsed=_read_report(report,load_source)
    return _summary_rows(report.name,origin or report.name,hashlib.sha256(raw).hexdigest(),parsed,
                         _select(report.name,parsed,cases))


def load_audit(audit):
    """Bounded JSON read of a conversion audit; rejects symlinked audits and audit folders."""
    audit=Path(audit)
    if audit.is_symlink() or audit.parent.is_symlink() or not audit.is_file() or audit.stat().st_size>2*1024*1024:
        raise ValueError(f'{audit.name}: unsupported audit file')
    try:data=json.loads(audit.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError) as exc:raise ValueError(f'{audit.name}: unreadable audit JSON') from exc
    if not isinstance(data,dict):raise ValueError(f'{audit.name}: unreadable audit JSON')
    return data


def summarize_audit(audit, *, origin=None):
    """Summary rows for a completed conversion, parsed from its `_source` snapshot only after the
    snapshot matches the audited SHA-256, with the audit's recorded cases and load basis."""
    audit=Path(audit)
    data=load_audit(audit)
    name,expected,cases,basis=(data.get(k) for k in ('source','source_sha256','cases','load_source'))
    if (not isinstance(name,str) or Path(name).name!=name or name in ('','.','..') or not isinstance(expected,str)
            or not isinstance(cases,list) or not all(type(i) is int for i in cases) or basis not in ('effects','reactions')):
        raise ValueError(f'{audit.name}: not an MCDXKit conversion audit')
    folder=audit.parent/'_source';snapshot=folder/name
    if folder.is_symlink() or snapshot.is_symlink() or not snapshot.is_file():
        raise ValueError(f'{audit.name}: source snapshot _source/{name} is missing or not a regular file')
    raw=_read_raw(snapshot);digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected:
        raise ValueError(f'{audit.name}: source snapshot does not match the audited SHA-256')
    parsed=_parse_raw(raw,basis)
    return _summary_rows(name,origin or audit.name,digest,parsed,_select(audit.name,parsed,cases))


def summary_csv(rows):
    """Render summary rows as CSV text (units in column names, kip and kip-in)."""
    def text(value):
        # Spreadsheet formula injection: report/case names are untrusted text.
        return "'"+value if isinstance(value,str) and value[:1] in ('=','+','-','@','\t','\r') else value
    def cell(key,value):
        if isinstance(value,bool):return 'yes' if value else 'no'
        if isinstance(value,float):return format(value,'.12g')
        if isinstance(value,list):return ' '.join(value)
        return '' if value is None else text(value)
    stream=io.StringIO()
    writer=csv.writer(stream,lineterminator='\n')
    writer.writerow(SUMMARY_COLUMNS)
    for row in rows:writer.writerow([cell(key,row[key]) for key in SUMMARY_COLUMNS])
    return stream.getvalue()


def validate(worksheet):
    """Check ZIP/XML relationships. Does not execute Mathcad or validate PTC schemas."""
    return mcdx.validate(worksheet)
