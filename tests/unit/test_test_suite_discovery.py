"""Exercise the standard runner using real, tiny discoverable Python modules."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run_tests.py"
spec = importlib.util.spec_from_file_location("bridge_discovery_test_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def collected_cases(suite):
    for case in suite:
        if isinstance(case, unittest.TestSuite):
            yield from collected_cases(case)
        else:
            yield case


class TestSuiteDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bridge-discovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "unit"
        self.directory.mkdir()
        self.prefix = "test_discovery_fixture_" + self._testMethodName + "_"
        previous_path = sys.path[:]

        def restore_imports():
            sys.path[:] = previous_path
            for name in tuple(sys.modules):
                if name.startswith(self.prefix):
                    del sys.modules[name]

        self.addCleanup(restore_imports)

    def module(self, suffix, source, directory=None):
        name = self.prefix + suffix
        (directory or self.directory).joinpath(name + ".py").write_text(
            textwrap.dedent(source), encoding="utf-8")
        return name

    def original(self, suffix="z_original"):
        return self.module(suffix, """
            import unittest
            events = []
            class Fixture(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    events.append(('setup', cls.__module__))
                def test_normal(self):
                    events.append(('normal', type(self).__module__))
                def test_fault(self):
                    with self.assertRaises(ValueError):
                        raise ValueError('unique fault')
                    events.append(('fault', type(self).__module__))
        """)

    def raw_suite(self):
        loader = unittest.TestLoader()
        suites = [loader.discover(str(directory), top_level_dir=str(directory))
                  for name in ("unit", "contract", "integration")
                  if (directory := self.root / name).is_dir()]
        self.assertEqual(loader.errors, [])
        return unittest.TestSuite(suites)

    def compare(self):
        raw_ids = [case.id() for case in collected_cases(self.raw_suite())]
        suite = runner.discover_suite(self.root)
        kept_ids = [case.id() for case in collected_cases(suite)]
        self.assertEqual(set(kept_ids), set(raw_ids))
        return suite, raw_ids, kept_ids

    def run_tiny(self, suite):
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        return result.testsRun

    def test_import_aliases_run_once_at_original_module_in_either_order(self):
        original = self.original()
        self.module("a_alias", f"from {original} import Fixture as ImportedFixture")
        self.module("zz_alias", f"from {original} import Fixture as AnotherFixture")
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual((len(raw_ids), len(kept_ids)), (6, 2))
        self.assertEqual(self.run_tiny(suite), 2)
        self.assertEqual(sys.modules[original].events,
                         [('setup', original), ('fault', original), ('normal', original)])

    def test_independent_subclass_keeps_inherited_and_unique_methods(self):
        original = self.original()
        subclass = self.module("a_subclass", f"""
            from {original} import Fixture as ImportedFixture
            class Independent(ImportedFixture):
                def test_unique_fault(self):
                    with self.assertRaises(KeyError):
                        raise KeyError('independent fault')
        """)
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual((len(raw_ids), len(kept_ids)), (7, 5))
        self.assertIn(subclass + '.Independent.test_normal', kept_ids)
        self.assertIn(subclass + '.Independent.test_unique_fault', kept_ids)
        self.assertEqual(self.run_tiny(suite), 5)

    def test_load_tests_gets_default_alias_suite_and_pattern_unchanged(self):
        original = self.original()
        hook = self.module("a_hook", f"""
            from {original} import Fixture as ImportedFixture
            calls = []
            def load_tests(loader, tests, pattern):
                calls.append((tests.countTestCases(), pattern))
                return tests
        """)
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual(sys.modules[hook].calls, [(2, 'test*.py'), (2, 'test*.py')])
        self.assertEqual(self.run_tiny(suite), 4)

    def test_custom_hook_keeps_parameterized_instances_even_with_same_id(self):
        hook = self.module("a_parameters", """
            import unittest
            events = []
            class Variant(unittest.TestCase):
                def __init__(self, methodName='test_value', value=None):
                    super().__init__(methodName)
                    self.value = value
                def test_value(self):
                    self.assertIn(self.value, (0, 1))
                    events.append(self.value)
            def load_tests(loader, tests, pattern):
                return unittest.TestSuite([Variant(value=0), Variant(value=1)])
        """)
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual((len(kept_ids), len(set(kept_ids))), (2, 1))
        self.assertEqual(self.run_tiny(suite), 2)
        self.assertEqual(sys.modules[hook].events, [0, 1])

    def test_generated_parameter_methods_all_survive_alias_filter(self):
        original = self.module("z_generated", """
            import unittest
            events = []
            class Generated(unittest.TestCase):
                pass
            def example(value):
                def check(self):
                    self.assertIn(value, (0, 1))
                    events.append(value)
                return check
            for value in (0, 1):
                setattr(Generated, 'test_value_' + str(value), example(value))
        """)
        self.module("a_alias", f"from {original} import Generated as ImportedGenerated")
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual((len(raw_ids), len(kept_ids)), (4, 2))
        self.assertEqual(self.run_tiny(suite), 2)
        self.assertEqual(sys.modules[original].events, [0, 1])

    def test_custom_constructor_alias_is_preserved(self):
        original = self.module("z_constructor", """
            import unittest
            values = []
            class Constructed(unittest.TestCase):
                def __init__(self, methodName='test_value'):
                    super().__init__(methodName)
                    self.value = len(values)
                    values.append(self.value)
                def test_value(self):
                    self.assertIsInstance(self.value, int)
        """)
        self.module("a_alias", f"from {original} import Constructed as ImportedConstructed")
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual(self.run_tiny(suite), 2)

    def test_custom_ids_do_not_merge_independent_cases(self):
        self.module("a_same_ids", """
            import unittest
            events = []
            class First(unittest.TestCase):
                def id(self):
                    return 'shared.parameterized.id'
                def test_value(self):
                    events.append('first')
            class Second(First):
                def test_value(self):
                    events.append('second')
        """)
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual((len(kept_ids), len(set(kept_ids))), (2, 1))
        self.assertEqual(self.run_tiny(suite), 2)

    def test_imported_only_class_outside_discovery_is_preserved(self):
        original = self.original("helper")
        original_path = self.directory / (original + '.py')
        helper = "helper_" + original
        original_path.rename(self.directory / (helper + '.py'))
        self.addCleanup(sys.modules.pop, helper, None)
        self.module("a_alias", f"from {helper} import Fixture as ImportedFixture")
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual(self.run_tiny(suite), 2)

    def test_owner_hook_excluding_fixture_does_not_erase_imported_only_tests(self):
        original = self.original()
        with (self.directory / (original + '.py')).open('a', encoding='utf-8') as stream:
            stream.write('\ndef load_tests(loader, tests, pattern):\n    return unittest.TestSuite()\n')
        self.module("a_alias", f"from {original} import Fixture as ImportedFixture")
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual(self.run_tiny(suite), 2)

    def test_hook_discarded_owner_collection_does_not_erase_alias(self):
        original = self.original("helper")
        original_path = self.directory / (original + '.py')
        helper = "helper_" + original
        original_path.rename(self.directory / (helper + '.py'))
        self.addCleanup(sys.modules.pop, helper, None)
        self.module("a_alias", f"from {helper} import Fixture as ImportedFixture")
        self.module("b_hook", f"""
            import unittest
            import {helper} as helper
            def load_tests(loader, tests, pattern):
                loader.loadTestsFromModule(helper)
                return unittest.TestSuite()
        """)
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual(kept_ids, raw_ids)
        self.assertEqual(self.run_tiny(suite), 2)

    def test_alias_in_other_discovery_root_keeps_original(self):
        original = self.original()
        contract = self.root / "contract"
        contract.mkdir()
        self.module("a_alias", f"from {original} import Fixture as ImportedFixture", contract)
        suite, raw_ids, kept_ids = self.compare()
        self.assertEqual((len(raw_ids), len(kept_ids)), (4, 2))
        self.assertEqual(self.run_tiny(suite), 2)

    def test_custom_hook_failure_remains_a_failed_test(self):
        self.module("a_hook_failure", """
            def load_tests(loader, tests, pattern):
                raise RuntimeError('hook failure')
        """)
        suite = runner.discover_suite(self.root)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn('hook failure', result.errors[0][1])
