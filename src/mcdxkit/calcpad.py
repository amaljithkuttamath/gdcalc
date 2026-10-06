"""Strict scalar worksheet translation and local CalcpadCE calculation.

No Mathcad cached values are consumed. Unknown syntax fails; no XML fallback.
The source language is generated exclusively from the supported AST below.
"""
import hashlib
import html
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from decimal import Decimal
from lxml import html as H
from . import mcdx

REVISION = '0b20dba11ebd50b303eedb57e8ec042c272c68ab'
TRANSLATOR_VERSION = 2
OPS = {'mult': '*', 'scale': '*', 'plus': '+', 'minus': '-', 'div': '/', 'pow': '^',
       'lessThan': '<', 'lessOrEqual': '≤', 'greaterThan': '>', 'greaterOrEqual': '≥',
       'equal': '≡', 'and': '∧'}
COMPARISONS = {'lessThan', 'lessOrEqual', 'greaterThan', 'greaterOrEqual', 'equal'}
UNITS = {'in', 'ft', 'kip', 'ksi'}
STYLE = '''body{font:16px Georgia,serif;max-width:1000px;margin:40px auto;padding:20px;color:#202620}
p{line-height:1.7}.eq{white-space:nowrap}var{font-style:italic}.dvc{display:inline-flex;flex-direction:column;vertical-align:middle;text-align:center;padding:0 .15em}.dvl{border-top:1px solid;margin:.1em 0}sup{font-size:.75em}.source-label{font:600 13px system-ui;color:#426854;margin-top:24px}.check{font:15px system-ui}.err{color:#a00}'''


def default_engine_dir():
    return Path(os.environ.get('MCDXKIT_ENGINE_DIR', str(Path.home()/'.cache'/'mcdxkit'/'calcpad')))


def executable():
    path = Path(os.environ['MCDXKIT_CALCPAD']) if os.environ.get('MCDXKIT_CALCPAD') else default_engine_dir()/('mcdxkit-calcpad.exe' if os.name == 'nt' else 'mcdxkit-calcpad')
    if not path.is_file():
        raise ValueError('The required CalcpadCE calculator is not installed. Run mcdxkit setup-engine with the .NET 10 SDK and Git installed.')
    return path.resolve()


class Translator:
    def __init__(self):
        self.ids = {}
        self.strings = {}
        self.types = {}
        self.lines = []
        self.regions = []
        self.region_lines = {}

    def ident(self, name):
        # Never put arbitrary variable names into executable Calcpad syntax.
        if name not in self.ids:
            self.ids[name] = 'v'+str(len(self.ids)+1)
        return self.ids[name]

    def text(self, text):
        return "'"+html.escape(text, quote=True).replace('\n', ' ').replace('\r', ' ')

    def string(self, text):
        if text not in self.strings:
            self.strings[text] = len(self.strings)+1
        return str(self.strings[text])

    def kind(self, node):
        tag = mcdx.tag(node)
        if tag == 'str': return 'string'
        if tag == 'id': return self.types.get(mcdx.name(node), 'number')
        if tag in ('eval', 'parens', 'return'): return self.kind(node[0])
        return 'number'

    def expr(self, node, depth=0):
        if depth > 100: raise ValueError('Expression nesting exceeds 100')
        tag = mcdx.tag(node); children = list(node)
        def expr(child): return self.expr(child, depth+1)
        if tag == 'real':
            value = float(node.text)
            if not math.isfinite(value): raise ValueError('Nonfinite literal')
            # Calcpad reads an exponent letter as a unit, so always emit plain decimals.
            text = format(Decimal(node.text), 'f')
            return '('+text+')' if text.startswith('-') else text
        if tag == 'id':
            name = mcdx.name(node)
            if node.get('labels') == 'UNIT':
                if name not in UNITS: raise ValueError('Unsupported unit: '+name)
                return name
            if name == 'π': return 'π'
            return self.ident(name)
        if tag == 'str': return self.string(node.text or '')
        if tag in ('eval', 'parens', 'return') and children:
            return '('+expr(children[0])+')'
        if tag == 'apply' and children:
            op = mcdx.tag(children[0]); args = children[1:]
            if op == 'id':
                function = mcdx.name(children[0])
                args = list(args[0]) if len(args) == 1 and mcdx.tag(args[0]) == 'sequence' else args
                if function not in ('max', 'min', 'abs'): raise ValueError('Unsupported function: '+function)
                if not args or any(self.kind(a) != 'number' for a in args): raise ValueError('Function requires numeric arguments')
                return function+'('+'; '.join(expr(a) for a in args)+')'
            if op == 'equal':
                if len(args) != 2 or self.kind(args[0]) != self.kind(args[1]): raise ValueError('Mixed string/numeric comparison')
            elif any(self.kind(a) != 'number' for a in args):
                raise ValueError('String used in a numeric expression')
            if op in COMPARISONS and len(args) == 2 and mcdx.tag(args[0]) == 'apply' and mcdx.tag(args[0][0]) in COMPARISONS:
                inner = args[0]
                return '('+expr(inner)+') ∧ ('+expr(inner[-1])+OPS[op]+expr(args[1])+')'
            if op in COMPARISONS and len(args) == 2 and all(self.kind(a) == 'number' for a in args):
                # Mathcad accepts a literal zero in a dimensional comparison.
                # Calcpad requires both operands to carry compatible units.
                for index in (0, 1):
                    if mcdx.tag(args[index]) == 'real' and float(args[index].text) == 0:
                        terms = [expr(a) for a in args]
                        terms[index] = '(0*('+terms[1-index]+'))'
                        return '('+OPS[op].join(terms)+')'
            if op == 'nthRoot' and len(args) == 2:
                return '('+expr(args[1])+')^(1/'+('2' if mcdx.tag(args[0]) == 'placeholder' else expr(args[0]))+')'
            if op == 'neg' and len(args) == 1: return '(-('+expr(args[0])+'))'
            if op in OPS and len(args) == 2: return '('+(' '+OPS[op]+' ').join(expr(a) for a in args)+')'
        raise ValueError('Unsupported expression: '+tag)

    def returns(self, node):
        tag = mcdx.tag(node)
        if tag in ('test', 'placeholder'): return set()
        if tag in ('program', 'if', 'alsoif', 'elseif', 'then', 'else', 'return', 'parens', 'eval'):
            result = set()
            for child in node: result |= self.returns(child)
            return result
        return {self.kind(node)}

    def program(self, node, target, done, kind, depth=0, exits=False):
        # Mathcad returns the last statement executed; only return exits early.
        if depth > 100: raise ValueError('Program nesting exceeds 100')
        tag = mcdx.tag(node); children = list(node)
        def emit(child, exits=exits): self.program(child, target, done, kind, depth+1, exits)
        if tag == 'placeholder': return
        if tag in ('then', 'else', 'return', 'parens'):
            if len(children) != 1: raise ValueError('Invalid program wrapper')
            emit(children[0], exits or tag == 'return')
        elif tag == 'program':
            for child in children:
                self.lines += ['#if '+done+' ≡ 0']; emit(child, False); self.lines += ['#end if']
        elif tag in ('if', 'alsoif', 'elseif'):
            taken = 'taken'+str(len(self.lines))
            self.lines += [taken+' = 0']
            self.conditional(node, taken, emit)
        else:
            # Some original numeric programs return a diagnostic string on failure.
            # Fail calculation if that branch is selected; never coerce it to a number.
            value = self.expr(node) if self.kind(node) == kind else 'gdInvalidReturnType'
            self.lines += [target+' = '+value, done+'set = 1']+([done+' = 1'] if exits else [])

    def conditional(self, node, taken, emit):
        children = list(node)
        if len(children) < 2 or mcdx.tag(children[0]) != 'test' or mcdx.tag(children[1]) != 'then':
            raise ValueError('Invalid conditional')
        self.lines += ['#if '+self.expr(children[0][0]), taken+' = 1']; emit(children[1]); self.lines += ['#end if']
        for child in children[2:]:
            if mcdx.tag(child) not in ('else', 'alsoif', 'elseif'): raise ValueError('Unsupported conditional branch')
            self.lines += ['#if '+taken+' ≡ 0']
            if mcdx.tag(child) == 'else': emit(child)
            else: self.conditional(child, taken, emit)
            self.lines += ['#end if']

    def display(self, node):
        if self.kind(node) == 'string':
            for text, code in self.strings.items():
                self.lines += ['#if '+self.expr(node)+' ≡ '+str(code), self.text(text), '#end if']
        else:
            self.lines.append(self.expr(node))

    def translate(self, path):
        root = mcdx.read_xml(mcdx.read_package(path)['mathcad/worksheet.xml'])
        self.lines = ["'<h1>Calculated worksheet · CalcpadCE</h1>",
                      "'Scalar formulas translated from the generated Mathcad file. Native Prime execution remains unverified."]
        regions = sorted(root.findall('.//w:region', mcdx.NS), key=lambda r: (float(r.get('top', '0')), float(r.get('left', '0'))))
        for region in regions:
            math_node = region.find('w:math', mcdx.NS)
            if math_node is None: continue
            if not len(math_node) or any(mcdx.tag(n) not in ('resultFormat', 'formattingOverride') for n in list(math_node)[1:]):
                raise ValueError('Unsupported math region metadata')
            node = math_node[0]; region_id = region.get('region-id')
            self.regions.append(region_id); self.region_lines[region_id] = len(self.lines)+1
            try:
                if mcdx.tag(node) == 'define':
                    if len(node) != 2 or mcdx.tag(node[0]) != 'id': raise ValueError('Only scalar definitions supported')
                    name = mcdx.name(node[0]); target = self.ident(name); rhs = node[1]
                    while mcdx.tag(rhs) in ('eval', 'parens'): rhs = rhs[0]
                    kinds = self.returns(rhs)
                    kind = 'string' if kinds == {'string'} else 'number'
                    self.lines += [self.text(name)]
                    if mcdx.tag(rhs) in ('program', 'if'):
                        done = 'done'+str(len(self.regions))
                        self.lines += ['#hide', done+' = 0', done+'set = 0']
                        self.program(rhs, target, done, kind)
                        self.lines += ['#if '+done+'set ≡ 0', target+' = gdMissingBranch', '#end if', '#end hide']
                        self.types[name] = kind
                        self.display(node[0])
                    else:
                        self.types[name] = kind
                        if kind == 'string':
                            self.lines += ['#hide', target+' = '+self.expr(rhs), '#end hide']
                            self.display(node[0])
                        else:
                            self.lines += [target+' = '+self.expr(rhs)]
                elif mcdx.tag(node) == 'eval':
                    self.lines += [self.text(mcdx.name(node[0]) if mcdx.tag(node[0]) == 'id' else 'Expression')]
                    self.display(node[0])
                else: raise ValueError('Unsupported region: '+mcdx.tag(node))
            except (ValueError, IndexError) as exc:
                raise ValueError('Region '+str(region_id)+': '+str(exc)) from exc
        self.lines += ["'<p id=\"mcdxkit-complete\">Calculation complete.</p>"]
        source = '\n'.join(self.lines)+'\n'
        if len(source.encode()) > 4*1024*1024: raise ValueError('Translated source exceeds 4 MiB')
        return source


def calculate(path, cpd_path, html_path):
    binary = executable()
    translator = Translator(); source = translator.translate(path)
    # Each call gets an isolated process and working directory. No shell, imports,
    # includes, macros, file reads, scripting or user-supplied Calcpad are accepted.
    with tempfile.TemporaryDirectory(prefix='mcdxkit-calculate-') as folder:
        try:
            run = subprocess.run([str(binary)], input=json.dumps({'source': source}), text=True,
                                 capture_output=True, timeout=60, cwd=folder)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('CalcpadCE calculation exceeded 60 seconds') from exc
    try: result = json.loads(run.stdout)
    except ValueError as exc: raise ValueError('CalcpadCE failed: '+run.stderr[:300]) from exc
    if run.returncode or result.get('errors'):
        raise ValueError('CalcpadCE calculation failed: '+json.dumps(result.get('errors', []), ensure_ascii=False)[:1500])
    root = H.fragment_fromstring(result['html'], create_parent='div')
    if root.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," err ")]') or not root.xpath('.//*[@id="mcdxkit-complete"]'):
        raise ValueError('CalcpadCE returned incomplete results or calculation errors')
    # Only inert markup is retained. Render original variable names instead of safe
    # execution aliases; no formulas or result values are changed here.
    aliases = {value: key for key, value in translator.ids.items()}
    for node in root.iter('var'):
        if node.text in aliases: node.text = aliases[node.text]
    allowed = {'div', 'p', 'span', 'var', 'sup', 'sub', 'i', 'b', 'strong', 'em', 'h1', 'h2', 'br'}
    for node in list(root.iterdescendants()):
        if node.tag not in allowed:
            node.drop_tag(); continue
        for key in list(node.attrib):
            if key not in ('class', 'id'): del node.attrib[key]
    body = H.tostring(root, encoding='unicode')
    document = '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>MCDXKit calculated worksheet</title><style>'+STYLE+'</style></head><body>'+body+'</body></html>'
    Path(cpd_path).write_text(source, encoding='utf-8'); Path(html_path).write_text(document, encoding='utf-8')
    return {'engine': 'CalcpadCE', 'revision': REVISION, 'translator_version': TRANSLATOR_VERSION,
            'calculated': True, 'translated_math_regions': len(translator.regions),
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'html_sha256': hashlib.sha256(document.encode()).hexdigest(),
            'variables': translator.ids, 'region_lines': translator.region_lines,
            'native_execution_verified': False}
