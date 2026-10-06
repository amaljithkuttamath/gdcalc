"""Public conversion engine independent of CLI, agent host, HTTP and Mathcad."""
import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from . import group_report, mcdx, calcpad


def _read_report(path, load_source):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise ValueError('Raw report exceeds 16 MiB')
    raw=path.read_bytes()
    if b'\x00' in raw:raise ValueError('Expected a text GROUP report, not a binary workbook')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    return raw,group_report.parse(text,load_source)


def inspect_report(report, *, cases=None, load_source='effects'):
    """Inspect available cases; selection_required explains unresolved classification."""
    _,parsed=_read_report(report,load_source)
    issue=None
    try:selected=group_report.select(parsed,cases)
    except ValueError as exc:
        if cases is not None:raise
        selected=[];issue=str(exc)
    return {'source':Path(report).name,'cases':[{'id':c['id'],'name':c['name']} for c in parsed['cases']],
            'selected_cases':[c['id'] for c in selected],'selection_required':issue,
            'load_source':load_source,'envelope':group_report.envelope(selected) if selected else None,
            'largest_observed_pile_id':max((p for c in parsed['cases'] for p in c['pile_ids']),default=0)}


def convert(report, template, output, *, cases=None, load_source='effects', title=None, overrides=None):
    """Generate .mcdx, executable .cpd, calculated .html and .audit.json. Never overwrite sources or existing outputs."""
    report=Path(report).resolve();template=Path(template).resolve();output=Path(output).resolve()
    audit=output.with_suffix('.audit.json')
    if output.suffix.lower()!='.mcdx':raise ValueError('Output filename must end in .mcdx')
    if output in (report,template) or audit in (report,template):raise ValueError('Output cannot replace a source')
    cpd=output.with_suffix('.cpd'); calculated=output.with_suffix('.html')
    if any(p.exists() for p in (output,audit,cpd,calculated)):raise ValueError('Output artifact already exists; choose a new filename')
    if not template.is_file():raise ValueError('Template not found. Provide --template /path/to/reference.mcdx')
    raw,parsed=_read_report(report,load_source)
    selected=group_report.select(parsed,cases)
    output.parent.mkdir(parents=True,exist_ok=True)
    # Stage both artifacts before publishing either. Hard links fail if a destination
    # was concurrently created and avoid replacing it; all paths share a filesystem.
    with tempfile.TemporaryDirectory(prefix='.gdcalc-',dir=output.parent) as folder:
        staged=Path(folder)/'worksheet.mcdx'
        result=mcdx.generate(template,staged,selected,report.name,title,overrides,geometry_cases=parsed['cases'])
        result.update({'output':str(output),'audit':str(audit),'source_sha256':hashlib.sha256(raw).hexdigest(),
                       'geometry_case_ids':[c['id'] for c in parsed['cases']]})
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


SUMMARY_MEASURES=(('P','kip'),('Vy','kip'),('Vz','kip'),('My','kip_in'),('Mz','kip_in'))
SUMMARY_COLUMNS=(['report','origin','source_sha256','load_source','case_id','case_name','selected']+
                 [key+'_'+unit for key,unit in SUMMARY_MEASURES]+['governs'])


def _summary_rows(name, origin, raw, parsed, selected):
    """One row per final-summary case. Values are that case's component maxima (P: max compression,
    others: max magnitude); `governs` names measures for which the case is the selected-case maximum."""
    governing=group_report.envelope(selected)
    chosen={c['id'] for c in selected}
    rows=[]
    for case in parsed['cases']:
        values=group_report.envelope([case])
        row={'report':name,'origin':origin,'source_sha256':hashlib.sha256(raw).hexdigest(),
             'load_source':parsed['load_source'],'case_id':case['id'],'case_name':case['name'],
             'selected':case['id'] in chosen}
        row.update({key+'_'+unit:values[key] for key,unit in SUMMARY_MEASURES})
        row['governs']=[key for key,_ in SUMMARY_MEASURES if case['id'] in chosen and values[key]==governing[key]]
        rows.append(row)
    return rows


def summarize_report(report, *, cases=None, load_source='effects', origin=None):
    """Summary rows for one report. Unresolved or invalid case selection raises ValueError."""
    report=Path(report)
    raw,parsed=_read_report(report,load_source)
    try:selected=group_report.select(parsed,cases)
    except ValueError as exc:raise ValueError(f'{report.name}: {exc}') from exc
    return _summary_rows(report.name,origin or report.name,raw,parsed,selected)


def summarize_audit(audit, *, origin=None):
    """Summary rows for a completed conversion, re-parsed from its hash-verified `_source` snapshot
    with the audit's recorded cases and load basis. A missing or changed snapshot raises ValueError."""
    audit=Path(audit)
    if audit.is_symlink() or audit.stat().st_size>2*1024*1024:raise ValueError(f'{audit.name}: unsupported audit file')
    try:
        data=json.loads(audit.read_text(encoding='utf-8'))
        name,expected,cases,basis=data['source'],data['source_sha256'],data['cases'],data['load_source']
    except (ValueError,KeyError,TypeError) as exc:raise ValueError(f'{audit.name}: not a gdcalc conversion audit') from exc
    if (not isinstance(name,str) or Path(name).name!=name or name in ('','.','..') or not isinstance(cases,list)
            or not all(type(i) is int for i in cases)):
        raise ValueError(f'{audit.name}: not a gdcalc conversion audit')
    snapshot=audit.parent/'_source'/name
    if snapshot.is_symlink() or not snapshot.is_file():
        raise ValueError(f'{audit.name}: source snapshot _source/{name} is missing')
    raw,parsed=_read_report(snapshot,basis)
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError(f'{audit.name}: source snapshot does not match the audited SHA-256')
    return _summary_rows(name,origin or audit.name,raw,parsed,group_report.select(parsed,cases))


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
