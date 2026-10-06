"""Transport-independent browser session and conversion operations."""
import math
import json
import re
import secrets
import tempfile
import threading
import shutil
from pathlib import Path
from . import engine, inspection, learn

MIB = 1024 * 1024

class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Session:
    def __init__(self, template, output_dir):
        self.template = Path(template).resolve() if template else None
        self.output_dir = Path(output_dir).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix='mcdxkit-browser-')
        self.token = secrets.token_urlsafe(32)
        self.files = {}
        self.upload_bytes = 0
        self.upload_count = 0
        self.conversions = 0
        self.previews = 0
        self.lock = threading.Lock()

    def get(self, file_id, kinds):
        if not isinstance(file_id, str) or file_id not in self.files:
            raise RequestError('File is not in this session. Select it again.', 404)
        entry = self.files[file_id]
        if entry['kind'] not in kinds:
            raise RequestError('This operation requires a ' + ' or '.join(kinds) + ' file')
        return entry

    def register(self, path, kind):
        for file_id, entry in self.files.items():
            if entry['path'] == path and entry['kind'] == kind:
                return {'id': file_id, 'name': path.name, 'kind': kind}
        file_id = secrets.token_hex(16)
        self.files[file_id] = {'path': path, 'kind': kind}
        return {'id': file_id, 'name': path.name, 'kind': kind}

    def history(self):
        """Recover complete generated pairs after a restart, without trusting saved paths."""
        rows = []
        candidates = sorted(self.output_dir.glob('*/*.audit.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for audit in candidates[:100]:
            output = audit.with_name(audit.name.removesuffix('.audit.json') + '.mcdx')
            if (not re.fullmatch('[0-9a-f]{16}', audit.parent.name) or audit.parent.is_symlink()
                    or audit.is_symlink() or output.is_symlink() or not output.is_file() or audit.stat().st_size > 2 * MIB):
                continue
            try:
                metadata = json.loads(audit.read_text())
                rows.append({'worksheet': self.register(output, 'worksheet'), 'audit': self.register(audit, 'audit'),
                             'output': str(output), 'created': audit.stat().st_mtime,
                             'envelope': metadata.get('envelope'), 'native_execution_verified': False,
                             **self.calculated_files(output, metadata.get('calculation'))})
            except (ValueError, OSError, AttributeError):
                continue
        return rows

    def calculated_files(self, output, calculation):
        cpd = output.with_suffix('.cpd'); rendered = output.with_suffix('.html')
        if not calculation or not calculation.get('calculated') or not cpd.is_file() or not rendered.is_file():
            return {}
        return {'open_worksheet': self.register(cpd, 'open_worksheet'),
                'calculated_worksheet': self.register(rendered, 'calculated_worksheet'),
                'calculation': {k: calculation[k] for k in ('engine', 'calculated', 'translated_math_regions')}}

    def upload(self, name, kind, raw):
        if not name or len(name) > 200 or name in ('.', '..') or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
            raise RequestError('Choose a filename without directory separators or control characters.')
        suffix = Path(name).suffix.lower()
        if kind not in ('report', 'template', 'worksheet') or suffix not in ({'.gp11t', '.txt'} if kind == 'report' else {'.mcdx'}):
            raise RequestError('Use .gp11t or .txt reports, or .mcdx worksheets/templates.')
        state = self
        if state.upload_count >= 100:
            raise RequestError('Session contains 100 uploads. Restart mcdxkit serve to start a new session.', 413)
        if len(raw) > (16 * MIB if kind == 'report' else 32 * MIB):
            raise RequestError('File exceeds the upload limit.', 413)
        if state.upload_bytes + len(raw) > 256 * MIB:
            raise RequestError('Session uploads exceed 256 MiB. Restart the server for a new session.', 413)
        folder = Path(state.temp.name) / secrets.token_hex(16)
        folder.mkdir()
        path = folder / name
        try:
            path.write_bytes(raw)
            checks = {'inspection': engine.inspect_report(path)} if kind == 'report' else {'validation': engine.validate(path)}
        except Exception:
            path.unlink(missing_ok=True)
            folder.rmdir()
            raise
        result = state.register(path, kind)
        state.upload_count += 1
        state.upload_bytes += len(raw)
        return {**result, **checks}

    def operation(self, route, data):
        state = self
        if route == '/api/view':
            if data.get('id') == 'default-template':
                if self.template is None or not self.template.is_file():
                    raise RequestError('Select a template first.')
                return inspection.worksheet(self.template)
            entry = self.get(data.get('id'), ['report', 'worksheet', 'template'])
            if entry['kind'] == 'report':
                raw = entry['path'].read_bytes()
                try: text = raw.decode('utf-8-sig')
                except UnicodeDecodeError: text = raw.decode('cp1252')
                return {'name': entry['path'].name, 'kind': 'report', 'text': text}
            view = inspection.worksheet(entry['path'])
            rendered = entry['path'].with_suffix('.html')
            if entry['kind'] == 'worksheet' and rendered.is_file():
                view['calculated_html'] = rendered.read_text(encoding='utf-8')
                view['calculation_engine'] = 'CalcpadCE'
            return view
        if route == '/api/diff':
            output = self.get(data.get('id'), ['worksheet'])['path']
            original = output.parent / '_source' / 'template.mcdx'
            if not original.is_file():
                raise RequestError('No original template snapshot is available for this file.')
            return inspection.diff(original, output)
        if route == '/api/validate':
            return engine.validate(state.get(data.get('id'), ['worksheet', 'template'])['path'])
        entry = state.get(data.get('id'), ['report'])
        cases = data.get('cases')
        if cases is not None and (not isinstance(cases, list) or not cases or len(cases) > 100 or
                                  any(type(i) is not int or i < 1 for i in cases) or len(set(cases)) != len(cases)):
            raise RequestError('Select one or more unique positive load case IDs.')
        basis = data.get('load_source', 'effects')
        if basis not in ('effects', 'reactions'):
            raise RequestError('Load source must be effects or reactions.')
        if route == '/api/inspect':
            return engine.inspect_report(entry['path'], cases=cases, load_source=basis)
        if route == '/api/suggest-cases':
            return learn.suggest_cases(entry['path'], load_source=basis, output_dir=self.output_dir)
        template = state.get(data['template_id'], ['template'])['path'] if data.get('template_id') else state.template
        if template is None or not template.is_file():
            raise RequestError('Select a compatible .mcdx template before converting.')
        overrides = data.get('overrides', {})
        if not isinstance(overrides, dict) or len(overrides) > 50 or any(
            not isinstance(k, str) or len(k) > 100 or type(v) not in (int, float) or not math.isfinite(v)
            for k, v in overrides.items()
        ):
            raise RequestError('Overrides must be finite numeric template inputs.')
        title = data.get('title')
        if title is not None and (not isinstance(title, str) or len(title) > 160):
            raise RequestError('Title must contain at most 160 characters.')
        if state.conversions >= 100 or (route == '/api/preview' and state.previews >= 100):
            raise RequestError('Session has generated 100 worksheets. Restart the server for a new session.', 413)
        stem = re.sub(r'[^A-Za-z0-9_-]+', '-', entry['path'].stem).strip('-')[:80] or 'worksheet'
        preview = route == '/api/preview'
        folder = (Path(state.temp.name) / 'previews' if preview else state.output_dir) / secrets.token_hex(8)
        output = folder / (stem + '.mcdx')
        sources = folder / '_source'
        sources.mkdir(parents=True)
        try:
            snapshot_report = sources / entry['path'].name
            snapshot_template = sources / 'template.mcdx'
            shutil.copyfile(entry['path'], snapshot_report)
            shutil.copyfile(template, snapshot_template)
            result = engine.convert(snapshot_report, snapshot_template, output, cases=cases,
                                    load_source=basis, title=title, overrides=overrides)
            changes = inspection.diff(snapshot_template, output)
        except Exception:
            shutil.rmtree(folder)
            raise
        if preview:
            state.previews += 1
        else:
            state.conversions += 1
        return {'worksheet': state.register(output, 'worksheet'),
                'audit': state.register(output.with_suffix('.audit.json'), 'audit'),
                'output': str(output), 'envelope': result['envelope'], 'cases': result['cases'],
                'validation': result['validation'], 'native_execution_verified': False,
                'preview': preview, 'diff': changes, 'review_flags': result['review_flags'],
                **self.calculated_files(output, result['calculation'])}
