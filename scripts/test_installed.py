"""Run repository tests against the installed SDK, rejecting source-path shadowing."""
import argparse
import importlib
from pathlib import Path
import sys
import sysconfig
import unittest


def verify_imports(modules=None, roots=None):
    modules = sys.modules if modules is None else modules
    roots = [Path(sysconfig.get_path(key)).resolve() for key in ('purelib', 'platlib')] if roots is None else roots
    checked = []
    for name, module in list(modules.items()):
        if name == 'mcdxkit' or name.startswith('mcdxkit.'):
            filename = getattr(module, '__file__', None)
            if not filename or not any(Path(filename).resolve().is_relative_to(root) for root in roots):
                raise RuntimeError(f'Installed SDK test selected a non-installed module: {name}: {filename}')
            checked.append(name)
    if not checked:
        raise RuntimeError('No installed SDK modules loaded')
    return checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests', type=Path, default=Path('tests'))
    args = parser.parse_args(argv)
    suite = unittest.defaultTestLoader.discover(str(args.tests))
    importlib.import_module('mcdxkit.engine')
    verify_imports()  # Discovery itself must not replace the installed SDK.
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    checked = verify_imports()
    print(f'Verified installed SDK origins for {len(checked)} modules.')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
