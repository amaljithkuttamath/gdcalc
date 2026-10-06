"""Independent interpreter for the tiny synthetic fixture; not a Mathcad engine."""
import zipfile
import xml.etree.ElementTree as E

def evaluate(path):
    env={'kip':1,'in':1,'ft':12}
    def tag(e):return e.tag.split('}')[-1]
    def run(e):
        t=tag(e);c=list(e)
        if t=='real':return float(e.text)
        if t=='id':return env[e.text]
        if t=='define':env[c[0].text]=run(c[1]);return env[c[0].text]
        if t=='sequence':return [run(x) for x in c]
        if t=='eval':return run(c[0])
        if t=='apply':
            op=tag(c[0]);a=[run(x) for x in c[1:]]
            if op=='id' and c[0].text=='max':return max(a[0])
            if op=='plus':return sum(a)
            if op=='mult':return a[0]*a[1]
        raise AssertionError(t)
    with zipfile.ZipFile(path) as z:root=E.fromstring(z.read('mathcad/worksheet.xml'))
    for r in sorted(root.findall('.//{http://schemas.mathsoft.com/worksheet50}region'),key=lambda e:(float(e.get('top')),float(e.get('left')))):
        m=r.find('{http://schemas.mathsoft.com/worksheet50}math')
        if m is not None:run(m[0])
    return env
