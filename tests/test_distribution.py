"""Verify the public installed package, command and browser assets together."""
import importlib.metadata
import importlib.resources
import subprocess
import sys
import unittest


class DistributionTests(unittest.TestCase):
    def test_installed_command_and_module_agree_with_distribution(self):
        distribution = importlib.metadata.distribution('mcdxkit')
        commands = {entry.name: entry for entry in distribution.entry_points
                    if entry.group == 'console_scripts'}
        self.assertEqual(set(commands), {'mcdxkit'})
        self.assertEqual(commands['mcdxkit'].value, 'mcdxkit.cli:main')
        for invocation in (['mcdxkit'], [sys.executable, '-m', 'mcdxkit']):
            result = subprocess.run(invocation + ['--version'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'mcdxkit ' + distribution.version)
        self.assertTrue(callable(commands['mcdxkit'].load()))

    def test_installed_resources_include_browser_and_calculator_bridge(self):
        package = importlib.resources.files('mcdxkit')
        self.assertIn('MCDXKit', package.joinpath('web/index.html').read_text())
        self.assertIn('mcdxkit-calcpad', package.joinpath('calcpad_bridge/Bridge.csproj').read_text())
        from mcdxkit.engine import inspect_report, convert, validate
        self.assertTrue(all(callable(fn) for fn in (inspect_report, convert, validate)))


if __name__ == '__main__':
    unittest.main()
