import tempfile
import unittest
import zipfile
from pathlib import Path
from mcdxkit import inspection, mcdx
from test_pipeline import template


class InspectionTests(unittest.TestCase):
    def test_file_coordinates_and_saved_values_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.mcdx';template(path);parts=mcdx.read_package(path)
            parts['mathcad/result.xml']=b'<resultsList xmlns="http://schemas.mathsoft.com/result10" xmlns:ml="http://schemas.mathsoft.com/math50"><resultData result-id="51"><ml:result><ml:real>123.456</ml:real></ml:result></resultData></resultsList>'
            with zipfile.ZipFile(path,'w') as z:
                for name,value in parts.items():z.writestr(name,value)
            view=inspection.worksheet(path)
            self.assertEqual(view['page']['content_height'],864)
            self.assertEqual(view['page']['count'],1)
            self.assertEqual(view['regions'][0]['left'],'10')
            self.assertEqual(view['regions'][0]['width'],'120')
            self.assertTrue(view['has_cached_results'])
            rendered=str(view['regions'][-1]['presentation'])
            self.assertIn('123.46',rendered);self.assertIn('kip',rendered)
            self.assertFalse(view['native_execution_verified'])

    def test_text_formatting_is_structured_not_executable_markup(self):
        source=mcdx.read_xml(b'<Section FontSize="12"><Paragraph><Run FontWeight="Bold">&lt;script&gt;unsafe&lt;/script&gt;</Run><LineBreak/><Run Foreground="#FFFF0000">red</Run></Paragraph></Section>')
        flow=inspection.flow(source)
        self.assertEqual(flow['children'][0]['node']['tag'],'p')
        run=flow['children'][0]['node']['children'][0]['node']
        self.assertEqual(run['tag'],'span');self.assertEqual(run['style']['fontWeight'],'bold')
        self.assertEqual(run['text'],'<script>unsafe</script>')

    def test_presentation_groups_negated_and_power_operands(self):
        a,b,c=(mcdx.ident(x) for x in 'abc')
        def apply(op,*args): return mcdx.node('apply',mcdx.node(op),*args)
        def text(node): return (node['text'] or '')+''.join(text(child) for child in node['children'])
        def shown(node): return text(inspection.presentation(node))
        self.assertEqual(shown(apply('neg',apply('plus',a,b))),'−(a+b)')
        self.assertEqual(shown(apply('mult',apply('neg',apply('minus',a,b)),c)),'−(a−b)×c')
        self.assertEqual(shown(apply('minus',a,apply('neg',b))),'a−(−b)')
        self.assertEqual(shown(apply('neg',a)),'−a')
        power=inspection.presentation(apply('pow',apply('plus',a,b),mcdx.real(2)))
        self.assertEqual(power['tag'],'msup')
        self.assertEqual(text(power['children'][0]),'(a+b)');self.assertEqual(text(power['children'][1]),'2')
        self.assertEqual(text(inspection.presentation(apply('pow',apply('neg',a),mcdx.real(2)))['children'][0]),'(−a)')
        self.assertEqual(text(inspection.presentation(apply('pow',a,mcdx.real(2)))['children'][0]),'a')
