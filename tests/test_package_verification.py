"""Prevent source shadowing and incomplete source-distribution test payloads."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

def script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

installed = script('test_installed')
package = script('check_package')


class DistributionTests(unittest.TestCase):
    def test_checkout_shadowing_is_rejected_even_when_other_modules_are_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); site = root / 'site-packages'
            modules = {'mcdxkit': SimpleNamespace(__file__=site/'mcdxkit/__init__.py'),
                       'mcdxkit.engine': SimpleNamespace(__file__=root/'src/mcdxkit/engine.py')}
            with self.assertRaisesRegex(RuntimeError, 'non-installed'): installed.verify_imports(modules, [site])
            modules['mcdxkit.engine'].__file__ = site/'mcdxkit/engine.py'
            self.assertEqual(len(installed.verify_imports(modules, [site])), 2)
            with self.assertRaises(RuntimeError): installed.verify_imports({}, [site])

    def test_source_archive_missing_helper_or_fixture_is_rejected(self):
        names = ['scripts/install_skill.py','scripts/audit_repository.py','scripts/report_audit.py',
                 'scripts/test_installed.py','scripts/cli.py','scripts/check_package.py',
                 'tests/test_pipeline.py','tests/test_repository_audit.py','tests/fixtures/review/seed529_clean.txt']
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder)/'mcdxkit-test.tar.gz'
            for omitted in (None, 'scripts/install_skill.py', 'tests/fixtures/review/seed529_clean.txt'):
                with tarfile.open(archive, 'w:gz') as bundle:
                    for name in names:
                        if name == omitted: continue
                        info = tarfile.TarInfo('mcdxkit-test/'+name); info.size=9
                        bundle.addfile(info, io.BytesIO(b'synthetic'))
                if omitted:
                    with self.assertRaisesRegex(ValueError, 'omits'): package.check_sdist(archive)
                else: package.check_sdist(archive)
