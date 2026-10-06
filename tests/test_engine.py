import json
import tempfile
import unittest
from pathlib import Path
from test_pipeline import report, template
from mcdxkit import engine

class EngineTests(unittest.TestCase):
    def test_core_api_converts_without_cli_or_codex(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);raw=d/'raw.txt';raw.write_text(report());ref=d/'reference.mcdx';template(ref)
            self.assertEqual(engine.inspect_report(raw)['selected_cases'],[1,7])
            result=engine.convert(raw,ref,d/'result.mcdx')
            self.assertEqual(result['envelope']['P'],140)
            self.assertEqual(json.loads((d/'result.audit.json').read_text())['source_sha256'],result['source_sha256'])

    def test_audit_collision_does_not_create_partial_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);raw=d/'raw.txt';raw.write_text(report());ref=d/'reference.mcdx';template(ref)
            audit=d/'result.audit.json';audit.write_text('keep')
            with self.assertRaises(ValueError):engine.convert(raw,ref,d/'result.mcdx')
            self.assertEqual(audit.read_text(),'keep');self.assertFalse((d/'result.mcdx').exists())

if __name__=='__main__':unittest.main()
