"""Template discovery is independent of the agent host and preserves explicit choices."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcdxkit import generate


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.generic = self.home / '.config/mcdxkit/reference.mcdx'
        self.checkout = self.root / 'checkout'
        self.local = self.checkout / 'assets/local/reference.mcdx'
        self.legacy = self.home / '.codex/skills/mcdxkit/assets/local/reference.mcdx'
        for context in (
            patch.dict(os.environ, {}, clear=True),
            patch.object(Path, 'home', return_value=self.home),
            patch.object(generate, '__file__', str(self.checkout / 'src/mcdxkit/generate.py')),
        ):
            context.start()
            self.addCleanup(context.stop)

    def make_template(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'template-discovery-fixture')

    def test_explicit_missing_template_is_not_replaced_by_fallback(self):
        self.make_template(self.generic)
        chosen = self.root / 'explicit.mcdx'
        os.environ['MCDXKIT_TEMPLATE'] = str(chosen)
        self.assertEqual(generate.default_template(), chosen)

    def test_checkout_precedes_generic_and_generic_precedes_legacy(self):
        for path in (self.local, self.generic, self.legacy):
            self.make_template(path)
        self.assertEqual(generate.default_template(), self.local)
        self.local.unlink()
        self.assertEqual(generate.default_template(), self.generic)

    def test_custom_config_directory_and_agent_neutral_skill(self):
        config = self.root / 'config'
        os.environ['XDG_CONFIG_HOME'] = str(config)
        configured = config / 'mcdxkit/reference.mcdx'
        self.make_template(configured)
        self.assertEqual(generate.default_template(), configured)
        configured.unlink()
        skill = self.home / '.agents/skills/mcdxkit/assets/local/reference.mcdx'
        self.make_template(skill)
        self.assertEqual(generate.default_template(), skill)

    def test_legacy_remains_compatible_and_missing_default_is_generic(self):
        self.assertEqual(generate.default_template(), self.generic)
        self.make_template(self.legacy)
        self.assertEqual(generate.default_template(), self.legacy)


if __name__ == '__main__':
    unittest.main()
