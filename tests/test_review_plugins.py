"""Review plug-in contract, registry, isolation and the review package's dependency rule.

The contract tests run over every registered plug-in (the built-ins plus the example
installed plug-in below): deterministic, no mutation, no I/O, no flags on clean reports.
Each built-in check must also flag its planted-error fixture.
"""
import ast
import builtins
import copy
import importlib.metadata
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_pipeline import clean_report, report, template
from test_review import FIXTURES, case_block, fixture
from mcdxkit import engine, group_report
from mcdxkit.review import registry, runner, view
from mcdxkit.review.api import Context, Flag, NotApplicable, frozen_mapping
from mcdxkit.review.history import MemoryHistory

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'src' / 'mcdxkit' / 'review'
FORBIDDEN = {'mcdx', 'calcpad', 'engine', 'server', 'service', 'cli', 'generate', 'batch', 'inspection',
             'group_report'}
CLEAN = (['seed505_clean.txt', 'seed529_clean.txt'] +
         sorted(p.name for p in FIXTURES.glob('round2_*_clean.txt')))
HISTORY = MemoryHistory([('LC-A', True), ('LC-B', False), ('Strength I', True)])


class PileCount:
    """Example installed plug-in (entry point in tests): a case naming fewer piles than the others."""
    kind = 'check'
    id = 'pile_count'
    version = '1'
    title = 'Fewer piles than other cases'
    params = frozen_mapping({})

    def run(self, report_view, ctx):
        most = max(len(c.pile_ids) for c in report_view.cases)
        for case in report_view.cases:
            if case.pile_ids and len(case.pile_ids) < most / 2:
                yield Flag(self.id, case.id, None, f'{case.label} names {len(case.pile_ids)} piles.')


class Raises:
    kind = 'check'
    id = 'raises'
    version = '1'
    title = 'Raises'
    params = frozen_mapping({})

    def run(self, report_view, ctx):
        raise RuntimeError('plug-in bug')


class Sleeps:
    kind = 'check'
    id = 'sleeps'
    version = '1'
    title = 'Sleeps'
    params = frozen_mapping({})

    def run(self, report_view, ctx):
        time.sleep(2)
        return []


class WrongType:
    kind = 'check'
    id = 'wrong_type'
    version = '1'
    title = 'Wrong type'
    params = frozen_mapping({})

    def run(self, report_view, ctx):
        return [{'rule': 'wrong_type'}]


class DuplicateId(PileCount):
    id = 'duplicate_case'


class BadParams(PileCount):
    id = 'bad_params'
    params = 5


class RaisingKind(PileCount):
    id = 'raising_kind'

    @property
    def kind(self):
        raise RuntimeError('metadata bug')


class Exits(PileCount):
    id = 'exits'

    def run(self, report_view, ctx):
        raise SystemExit(3)


class Interrupts(PileCount):
    id = 'interrupts'

    def run(self, report_view, ctx):
        raise KeyboardInterrupt


class ClosesGenerator(PileCount):
    id = 'closes_generator'

    def run(self, report_view, ctx):
        raise GeneratorExit


LOADED = []


class Counted(PileCount):
    """Records each instantiation, to show that unnamed plug-ins are never imported."""
    id = 'counted'

    def __init__(self):
        LOADED.append(self.id)


def point(name, target):
    return importlib.metadata.EntryPoint(name=name, value='test_review_plugins:' + target, group=registry.GROUP)


def installed(*points):
    """Patch importlib.metadata.entry_points to return these mcdxkit.review entry points."""
    def entry_points(**selection):
        return [p for p in points if selection.get('group') == p.group]
    return mock.patch('importlib.metadata.entry_points', side_effect=entry_points)


def plugins():
    with installed(point('pile_count', 'PileCount')):
        return [e.plugin for e in registry.discover().entries]


def call(plugin, report_view, ctx):
    try:
        return list(getattr(plugin, registry.KINDS[plugin.kind])(report_view, ctx))
    except NotApplicable:
        return 'not applicable'


def views():
    texts = [('pipeline report', report()), ('pipeline clean', clean_report())] + [(n, fixture(n)) for n in CLEAN]
    for name, text in texts:
        for load_source in ('effects', 'reactions'):
            parsed = group_report.parse(text, load_source)
            for selected in (None, [parsed['cases'][0]['id']]):
                yield f'{name} {load_source} {selected}', parsed, view.build(parsed, selected)


def duplicated_case():
    text = clean_report()
    start, end = case_block(text, 1)
    copied = text[start:end].replace('LOAD CASE : 1', 'LOAD CASE : 7')
    start7, end7 = case_block(text, 7)
    return text[:start7] + copied + text[end7:]


# Each built-in check and a planted-error report it must flag (fixtures from the review-flags study).
PLANTED = {
    'service_axial_above_strength': lambda: fixture('seed505_mislabel_str_as_ser.txt'),
    'effects_below_top': lambda: fixture('round2_seed370001_copied_effects.txt'),
    'duplicate_case': duplicated_case,
    'ratio_outlier': lambda: fixture('seed529_digit_edit.txt'),
    'gross_magnitude': lambda: fixture('round2_seed320000_unit_force_lb.txt'),
}


class ContractTests(unittest.TestCase):
    def test_every_plugin_is_deterministic(self):
        for plugin in plugins():
            for name, _, report_view in views():
                with self.subTest(plugin.id, report=name):
                    ctx = Context(history=HISTORY)
                    self.assertEqual(call(plugin, report_view, ctx), call(plugin, report_view, ctx))

    def test_no_plugin_mutates_the_view_or_the_parsed_report(self):
        for plugin in plugins():
            for name, parsed, report_view in views():
                with self.subTest(plugin.id, report=name):
                    before, original = copy.deepcopy(parsed), view.build(parsed, report_view.selected)
                    call(plugin, report_view, Context(history=HISTORY))
                    self.assertEqual(report_view, original)
                    self.assertEqual(parsed, before)
        with self.assertRaises(TypeError):
            report_view.cases[0].maximum['P'] = 0

    def test_no_plugin_does_io(self):
        def refuse(*args, **kwargs):
            raise AssertionError('I/O during a review plug-in run')
        prepared = list(views())
        for plugin in plugins():
            for name, _, report_view in prepared:
                with self.subTest(plugin.id, report=name), mock.patch.object(builtins, 'open', refuse), \
                        mock.patch.object(io, 'open', refuse), mock.patch.object(socket, 'socket', refuse):
                    call(plugin, report_view, Context(history=HISTORY))

    def test_clean_reports_give_no_flags(self):
        texts = [('pipeline clean', clean_report())] + [(n, fixture(n)) for n in CLEAN]
        for plugin in plugins():
            if plugin.kind != 'check':
                continue
            for name, text in texts:
                for load_source in ('effects', 'reactions'):
                    with self.subTest(plugin.id, report=name, load_source=load_source):
                        result = call(plugin, view.build(group_report.parse(text, load_source)), Context())
                        self.assertIn(result, ([], 'not applicable'))

    def test_every_builtin_check_flags_its_planted_error(self):
        checks = {p.id: p for p in registry.builtins() if p.kind == 'check'}
        self.assertEqual(set(checks), set(PLANTED))
        for check_id, make in PLANTED.items():
            with self.subTest(check_id):
                found = call(checks[check_id], view.build(group_report.parse(make())), Context())
                self.assertTrue(found)
                self.assertTrue(all(f.rule == check_id for f in found))

    def test_every_plugin_declares_its_contract(self):
        for plugin in plugins():
            with self.subTest(plugin.id):
                self.assertIsNone(registry._problem(plugin))
                json.dumps(runner.jsonable(plugin.params))


class IsolationTests(unittest.TestCase):
    def setUp(self):
        # Plug-ins that time out are disabled for the process; start each test with none.
        patcher = mock.patch.object(runner, 'TIMED_OUT', set())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failing_slow_and_malformed_plugins_become_check_errors(self):
        points = [point('raises', 'Raises'), point('sleeps', 'Sleeps'), point('wrong_type', 'WrongType')]
        with installed(*points):
            plan = runner.prepare('default,raises,sleeps,wrong_type')
        started = time.monotonic()
        result = runner.review(group_report.parse(report()), [1, 7], plan=plan, budget=0.3)
        self.assertLess(time.monotonic() - started, 1.8)
        errors = {e['id']: e for e in result['errors']}
        self.assertEqual(set(errors), {'raises', 'sleeps', 'wrong_type'})
        self.assertTrue(all(e['type'] == 'check_error' for e in errors.values()))
        self.assertIn('plug-in bug', errors['raises']['message'])
        self.assertIn('time budget', errors['sleeps']['message'])
        self.assertIn('must return Flag', errors['wrong_type']['message'])
        status = {c['id']: c['status'] for c in result['checks_run']}
        self.assertEqual([status[i] for i in ('raises', 'sleeps', 'wrong_type')], ['error'] * 3)
        # The built-ins still ran and flagged as usual.
        self.assertIn('service_axial_above_strength', {f['rule'] for f in result['flags']})

    def test_conversion_succeeds_when_plugins_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template(root / 'reference.mcdx')
            source = root / 'r.txt'
            source.write_text(report())
            with installed(point('raises', 'Raises'), point('sleeps', 'Sleeps')), \
                    mock.patch.object(runner, 'BUDGET_SECONDS', 0.3):
                result = engine.convert(source, root / 'reference.mcdx', root / 'out' / 'w.mcdx',
                                        checks='default,raises,sleeps')
                inspected = engine.inspect_report(source, checks='default,raises,sleeps')
            for block in (result['review_checks'], inspected['review_checks']):
                self.assertEqual({e['id'] for e in block['errors']}, {'raises', 'sleeps'})
            self.assertTrue((root / 'out' / 'w.mcdx').is_file())
            self.assertTrue(result['calculation']['calculated'])


class RegistryTests(unittest.TestCase):
    def test_entry_point_is_discovered_but_off_by_default(self):
        with installed(point('pile_count', 'PileCount')):
            catalog = registry.discover()
            self.assertEqual(catalog.ids('entry-point'), ['pile_count'])
            self.assertNotIn('pile_count', [e.id for e in registry.select('default', catalog)[0]])
            enabled = [e.id for e in registry.select('default,pile_count', catalog)[0]]
            self.assertEqual(enabled[-1], 'pile_count')
            self.assertEqual(enabled[:-1], [p.id for p in registry.builtins()])
            self.assertEqual([e.id for e in registry.select('pile_count', catalog)[0]], ['pile_count'])
            self.assertEqual(registry.select('none', catalog), ((), ()))
            rows = {r['id']: r for r in registry.listing('default')}
            self.assertEqual((rows['pile_count']['source'], rows['pile_count']['enabled']), ('entry-point', False))
            self.assertTrue(rows['ratio_outlier']['enabled'])
            text = ROOT / 'tests' / 'fixtures' / 'review' / 'seed529_clean.txt'
            on = engine.inspect_report(text, checks='default,pile_count')['review_checks']
            off = engine.inspect_report(text)['review_checks']
        self.assertIn('pile_count', [c['id'] for c in on['checks_run']])
        self.assertNotIn('pile_count', [c['id'] for c in off['checks_run']])

    def test_broken_duplicate_and_unknown_plugins(self):
        points = [point('broken', 'NoSuchClass'), point('duplicate', 'DuplicateId')]
        with installed(*points):
            catalog = registry.discover()
            errors = dict(catalog.errors)
            self.assertIn('failed to load', errors['broken'])
            self.assertIn("duplicate id 'duplicate_case'", errors['duplicate'])
            self.assertEqual(catalog.ids('entry-point'), [])
            # Naming a broken plug-in records its load error instead of failing.
            plan = runner.prepare('default,broken')
            result = runner.review(group_report.parse(clean_report()), [1, 7], plan=plan)
            self.assertEqual([(e['type'], e['id']) for e in result['errors']], [('check_error', 'broken')])
        for spec in ('default,missing', 'none,default', 'default,,x', 'default,default'):
            with self.subTest(spec), self.assertRaises(ValueError):
                runner.prepare(spec)

    def test_checks_list_command(self):
        from mcdxkit import cli
        output = io.StringIO()
        with installed(point('pile_count', 'PileCount')), redirect_stdout(output):
            self.assertEqual(cli.main(['checks', 'list']), 0)
        lines = output.getvalue().splitlines()
        self.assertTrue(any(line.split()[:2] == ['ratio_outlier', '2'] and line.endswith('on') for line in lines))
        self.assertTrue(any(line.startswith('pile_count') and 'entry-point' in line and line.endswith('off')
                            for line in lines))
        process = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'cli.py'), 'checks', 'list', '--json',
                                  '--checks', 'none'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(any(row['enabled'] for row in json.loads(process.stdout)))


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(runner, 'TIMED_OUT', set())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_plugin_metadata_errors_are_load_errors(self):
        points = [point('bad_params', 'BadParams'), point('raising_kind', 'RaisingKind')]
        with installed(*points):
            errors = dict(registry.discover().errors)
            self.assertIn('TypeError', errors['bad_params'])
            self.assertIn('metadata bug', errors['raising_kind'])
            plan = runner.prepare('default,bad_params,raising_kind')
            self.assertEqual({name for name, _ in plan.load_errors}, {'bad_params', 'raising_kind'})
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / 'r.txt'
                source.write_text(report())
                self.assertEqual(engine.inspect_report(source)['review_checks']['errors'], [])
        # checks=none never looks at installed plug-ins at all.
        with mock.patch.object(registry, 'discover', side_effect=AssertionError('discovered')):
            self.assertEqual(runner.prepare('none').entries, ())

    def test_base_exceptions_from_plugins_become_check_errors(self):
        points = [point('exits', 'Exits'), point('interrupts', 'Interrupts'),
                  point('closes_generator', 'ClosesGenerator')]
        with installed(*points):
            plan = runner.prepare('default,exits,interrupts,closes_generator')
        result = runner.review(group_report.parse(report()), [1, 7], plan=plan)
        errors = {e['id']: e['message'] for e in result['errors']}
        self.assertEqual(set(errors), {'exits', 'interrupts', 'closes_generator'})
        self.assertIn('SystemExit', errors['exits'])
        self.assertIn('KeyboardInterrupt', errors['interrupts'])
        self.assertIn('GeneratorExit', errors['closes_generator'])

    def test_only_named_entry_points_are_imported(self):
        LOADED.clear()
        points = [point('counted', 'Counted'), point('broken', 'NoSuchClass')]
        with installed(*points):
            plan = runner.prepare('default')
            self.assertEqual((LOADED, plan.load_errors), ([], ()))
            self.assertEqual(runner.prepare('default,counted').entries[-1].id, 'counted')
            self.assertEqual(LOADED, ['counted'])
            registry.listing()
            self.assertEqual(LOADED, ['counted', 'counted'])

    def test_server_session_resolves_checks_once(self):
        from mcdxkit.service import Session
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'r.txt'
            source.write_text(report())
            with mock.patch.object(registry, 'discover', wraps=registry.discover) as discover:
                session = Session(None, root / 'out')
                try:
                    session.inspect(source)
                    session.inspect(source)
                finally:
                    session.temp.cleanup()
            self.assertEqual(discover.call_count, 1)

    def test_timed_out_plugin_is_disabled_for_the_process(self):
        with installed(point('sleeps', 'Sleeps')):
            plan = runner.prepare('sleeps')
        parsed = group_report.parse(report())
        first = runner.review(parsed, [1, 7], plan=plan, budget=0.2)
        self.assertIn('time budget', first['errors'][0]['message'])
        started = time.monotonic()
        second = runner.review(parsed, [1, 7], plan=plan, budget=0.2)
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertEqual([(e['type'], e['id']) for e in second['errors']], [('check_error', 'sleeps')])
        self.assertIn('disabled after timeout', second['errors'][0]['message'])
        self.assertEqual(second['checks_run'][0]['status'], 'error')


class ServerConfigurationTests(unittest.TestCase):
    def test_server_enables_builtins_unless_mcdxkit_checks_names_more(self):
        from mcdxkit.server import create_server
        from mcdxkit.service import Session
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.dict('os.environ', {'MCDXKIT_CHECKS': 'default,no_such_check'}), \
                    self.assertRaisesRegex(ValueError, 'Unknown review check'):
                create_server(port=0, output_dir=root / 'out')
            with installed(point('pile_count', 'PileCount')), mock.patch.dict('os.environ', {'MCDXKIT_CHECKS': 'default,pile_count'}):
                server = create_server(port=0, output_dir=root / 'out')
                try:
                    self.assertEqual(server.state.checks, 'default,pile_count')
                    source = root / 'r.txt'
                    source.write_text(report())
                    ran = [c['id'] for c in server.state.inspect(source)['review_checks']['checks_run']]
                    self.assertEqual(ran[-1], 'pile_count')
                finally:
                    server.server_close()
            with mock.patch.dict('os.environ', {}, clear=False):
                import os
                os.environ.pop('MCDXKIT_CHECKS', None)
                server = create_server(port=0, output_dir=root / 'out')
                try:
                    self.assertEqual(server.state.checks, 'default')
                finally:
                    server.server_close()
            session = Session(None, root / 'out', 'none')
            try:
                self.assertEqual(session.inspect(source)['review_checks']['checks_run'], [])
            finally:
                session.temp.cleanup()


def imported_modules(path):
    """Absolute module names imported by a file under src/mcdxkit/review, resolving relative imports."""
    # The containing package: for both a module and an __init__.py, drop the last part.
    package = path.relative_to(ROOT / 'src').with_suffix('').parts[:-1]
    found = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module.split('.') if node.module else []
            if node.level:
                base = list(package[:len(package) - node.level + 1]) + base
            found.append('.'.join(base))
            found += ['.'.join(base + [alias.name]) for alias in node.names]
    return found


class DependencyRuleTests(unittest.TestCase):
    def test_review_does_not_import_conversion_modules(self):
        files = sorted(REVIEW.rglob('*.py'))
        self.assertGreater(len(files), 8)
        for path in files:
            for name in imported_modules(path):
                parts = name.split('.')
                with self.subTest(file=str(path.relative_to(ROOT)), module=name):
                    self.assertFalse(parts[0] == 'mcdxkit' and len(parts) > 1 and parts[1] in FORBIDDEN)

    def test_rule_catches_relative_and_absolute_imports(self):
        with tempfile.TemporaryDirectory(dir=REVIEW) as folder:
            probe = Path(folder) / 'probe.py'
            probe.write_text('from ... import engine\nimport mcdxkit.calcpad\nfrom ...group_report import parse\n')
            names = imported_modules(probe)
        self.assertIn('mcdxkit.engine', names)
        self.assertIn('mcdxkit.calcpad', names)
        self.assertIn('mcdxkit.group_report', names)

    def test_api_uses_the_standard_library_only(self):
        for name in imported_modules(REVIEW / 'api.py'):
            self.assertIn(name.split('.')[0], sys.stdlib_module_names, name)


if __name__ == '__main__':
    unittest.main()
