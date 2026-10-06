"""Numerical contract tests against the real required CalcpadCE process."""
import copy
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from lxml import etree as E, html
from mcdxkit import calcpad, engine, mcdx
from test_pipeline import template, report


def worksheet(path, expressions):
    root = E.Element(mcdx.q(mcdx.W, 'worksheet'))
    regions = E.SubElement(root, mcdx.q(mcdx.W, 'regions'))
    for index, expression in enumerate(expressions):
        region = E.SubElement(regions, mcdx.q(mcdx.W, 'region'), {'region-id': str(index), 'top': str(index*40), 'left': '0'})
        E.SubElement(region, mcdx.q(mcdx.W, 'math')).append(expression)
    with zipfile.ZipFile(path, 'w') as z: z.writestr('mathcad/worksheet.xml', mcdx.xml(root))


def definition(name, value): return mcdx.node('define', mcdx.ident(name), value)
def apply(op, *args): return mcdx.node('apply', mcdx.node(op), *args)
def branch(condition, yes, no):
    return mcdx.node('program', mcdx.node('if', mcdx.node('test', condition),
        mcdx.node('then', mcdx.node('program', yes)), mcdx.node('else', mcdx.node('program', no))))


class CalcpadTests(unittest.TestCase):
    def calculate(self, expressions):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'test.mcdx'; worksheet(source, expressions)
            evidence = calcpad.calculate(source, root/'test.cpd', root/'test.html')
            return html.parse(str(root/'test.html')).getroot().text_content(), evidence

    def test_dimensional_zero_conditional_and_chained_comparison(self):
        negative = definition('stress', mcdx.quantity(mcdx.real(-2), 'ksi'))
        choice = definition('choice', branch(apply('lessThan', mcdx.ident('stress'), mcdx.real(0)), mcdx.real(7), mcdx.real(99)))
        chained = apply('lessOrEqual', apply('lessThan', mcdx.real(1), mcdx.real(3)), mcdx.real(4))
        final = definition('selected', branch(chained, mcdx.real(11), mcdx.real(999)))
        text, result = self.calculate([negative, choice, final])
        self.assertIn('choice = 7', text); self.assertIn('selected = 11', text)
        self.assertTrue(result['calculated']); self.assertFalse(result['native_execution_verified'])

    def test_conditional_strings_preserve_text_and_equality(self):
        yes = mcdx.node('str'); yes.text = 'Compact <web> "safe"'
        no = mcdx.node('str'); no.text = 'Not compact'
        condition = definition('status', branch(apply('lessThan', mcdx.real(1), mcdx.real(2)), yes, no))
        equal = definition('match', branch(apply('equal', mcdx.ident('status'), copy.deepcopy(yes)), mcdx.real(42), mcdx.real(100)))
        text, _ = self.calculate([condition, equal])
        self.assertIn('Compact <web> "safe"', text); self.assertIn('match = 42', text)

    def test_hidden_dimensional_error_fails_instead_of_publishing(self):
        expression = definition('bad', branch(apply('lessThan', mcdx.real(1), mcdx.real(2)),
            apply('plus', mcdx.quantity(mcdx.real(2), 'kip'), mcdx.quantity(mcdx.real(2), 'in')), mcdx.real(0)))
        with self.assertRaisesRegex(ValueError, 'Inconsistent units'):
            self.calculate([expression])

    def test_unsupported_operator_and_string_arithmetic_fail(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported expression'):
            self.calculate([definition('bad', apply('integral', mcdx.real(1), mcdx.real(2)))])
        string = mcdx.node('str'); string.text = 'Do not treat as a number'
        with self.assertRaisesRegex(ValueError, 'String used'):
            self.calculate([definition('bad', apply('plus', string, mcdx.real(2)))])

    def test_conversion_calculates_and_missing_engine_leaves_no_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); ref=root/'reference.mcdx'; raw=root/'report.txt'; template(ref); raw.write_text(report())
            result=engine.convert(raw,ref,root/'result.mcdx')
            self.assertTrue(result['calculation']['calculated'])
            text=html.parse(str(root/'result.html')).getroot().text_content()
            self.assertIn('P_u = 145',text)
            self.assertIn('mcdxkit', (root/'result.cpd').read_text())
            with patch.dict(os.environ, {'MCDXKIT_CALCPAD': str(root/'missing')}):
                with self.assertRaisesRegex(ValueError, 'required CalcpadCE'):
                    engine.convert(raw,ref,root/'failed.mcdx')
            self.assertEqual(list(root.glob('failed.*')),[])

    def test_negation_powers_and_literal_magnitudes_match_mathcad(self):
        x=mcdx.ident('x'); large=mcdx.real(0); large.text='1E3'
        text,_=self.calculate([
            definition('x',mcdx.real(3)),
            definition('negpow',apply('pow',apply('neg',x),mcdx.real(2))),
            definition('litpow',apply('pow',mcdx.real(-3),mcdx.real(2))),
            definition('powneg',apply('neg',apply('pow',mcdx.ident('x'),mcdx.real(2)))),
            definition('product',apply('mult',mcdx.ident('x'),apply('neg',mcdx.ident('x')))),
            definition('difference',apply('minus',mcdx.ident('x'),apply('neg',mcdx.ident('x')))),
            definition('tiny',apply('mult',mcdx.quantity(mcdx.real(5e-08),'kip'),mcdx.real(1e8))),
            definition('large',large)])
        # (-3)^2 = 9; -(3^2) = -9; 3*(-3) = -9; 3-(-3) = 6; 5e-8 kip*1e8 = 5 kip.
        results={line.split(' = ')[0]:line.split(' = ')[-1].replace('\u2009',' ') for line in text.splitlines() if ' = ' in line}
        self.assertEqual(results,{'x':'3','negpow':'9','litpow':'9','powneg':'-9','product':'-9','difference':'6','tiny':'5 kip','large':'1000'})

    def test_program_returns_last_statement_unless_returned_early(self):
        def program(*statements): return mcdx.node('program',*statements)
        def when(condition,value): return mcdx.node('if',mcdx.node('test',condition),mcdx.node('then',value))
        true,false=apply('lessThan',mcdx.real(1),mcdx.real(2)),apply('lessThan',mcdx.real(2),mcdx.real(1))
        text,_=self.calculate([
            definition('last',program(mcdx.real(5),mcdx.real(7))),
            definition('skipped',program(when(true,mcdx.real(5)),mcdx.real(7))),
            definition('early',program(when(copy.deepcopy(true),mcdx.node('return',mcdx.real(5))),mcdx.real(7))),
            definition('notearly',program(when(false,mcdx.node('return',mcdx.real(5))),mcdx.real(7))),
            definition('chosen',branch(copy.deepcopy(true),mcdx.real(11),mcdx.real(99)))])
        results={line.split(' = ')[0]:line.split(' = ')[-1] for line in text.splitlines() if ' = ' in line}
        self.assertEqual(results,{'last':'7','skipped':'7','early':'5','notearly':'7','chosen':'11'})
        with self.assertRaises(ValueError):
            self.calculate([definition('missing',program(when(copy.deepcopy(false),mcdx.real(5))))])

    def test_literal_text_cannot_inject_calcpad_directives(self):
        string=mcdx.node('str'); string.text="hello'\n#include /etc/passwd\n<script>alert(1)</script>"
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mcdx'; worksheet(source,[definition('message',string)])
            cpd=calcpad.Translator().translate(source)
            self.assertFalse(any(line.startswith('#include') for line in cpd.splitlines()))

if __name__ == '__main__': unittest.main()
