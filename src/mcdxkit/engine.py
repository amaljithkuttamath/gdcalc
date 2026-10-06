"""Public conversion engine independent of CLI, agent host, HTTP and Mathcad."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from . import group_report, mcdx, calcpad, checks


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
    with tempfile.TemporaryDirectory(prefix='.mcdxkit-',dir=output.parent) as folder:
        staged=Path(folder)/'worksheet.mcdx'
        result=mcdx.generate(template,staged,selected,report.name,title,overrides,geometry_cases=parsed['cases'])
        result.update({'output':str(output),'audit':str(audit),'source_sha256':hashlib.sha256(raw).hexdigest(),
                       'geometry_case_ids':[c['id'] for c in parsed['cases']]})
        cpd_staged=Path(folder)/'worksheet.cpd'; html_staged=Path(folder)/'worksheet.html'
        calculation=calcpad.calculate(staged,cpd_staged,html_staged)
        result.update({'calculation':calculation,'open_worksheet':str(cpd),'calculated_worksheet':str(calculated)})
        # Outcomes are read from the published snapshot, never recalculated.
        found,summary=checks.extract(html_staged.read_text(encoding='utf-8'),calculation['region_lines'])
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


def validate(worksheet):
    """Check ZIP/XML relationships. Does not execute Mathcad or validate PTC schemas."""
    return mcdx.validate(worksheet)
