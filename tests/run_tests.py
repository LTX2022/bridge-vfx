#!/usr/bin/env python3
"""Run the standard-library test suite without requiring pytest."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))


class DiscoveryLoader(unittest.TestLoader):
    """Retain module provenance without changing unittest's loading hooks."""

    def __init__(self):
        super().__init__()
        self.module_suites = {}
        self.hook_suites = set()

    def loadTestsFromModule(self, module, *args, **kwargs):
        suite = super().loadTestsFromModule(module, *args, **kwargs)
        if getattr(module, "load_tests", None) is None:
            self.module_suites[id(suite)] = (module.__name__, suite)
        else:
            self.hook_suites.add(id(suite))
        return suite

    @staticmethod
    def ordinary_signature(suite):
        if type(suite) is not unittest.TestSuite:
            return ()
        cases = tuple(suite)
        if not cases or any(
            not isinstance(case, unittest.TestCase)
            or type(case) is not type(cases[0])
            or type(case).__init__ is not unittest.TestCase.__init__
            or type(case).id is not unittest.TestCase.id
            for case in cases
        ):
            return ()
        return tuple((type(case), case.id()) for case in cases)

    def without_imported_fixtures(self, suite):
        def reachable_modules(current):
            if id(current) in self.hook_suites or type(current) is not unittest.TestSuite:
                return
            if id(current) in self.module_suites:
                yield self.module_suites[id(current)]
                return
            for child in current:
                yield from reachable_modules(child)

        originals = {
            signature
            for module_name, module_suite in reachable_modules(suite)
            for group in module_suite
            if (signature := self.ordinary_signature(group))
            and signature[0][0].__module__ == module_name
        }

        def retain(current):
            if id(current) in self.hook_suites or type(current) is not unittest.TestSuite:
                return current
            if id(current) in self.module_suites:
                module_name, _ = self.module_suites[id(current)]
                return self.suiteClass(
                    group for group in current
                    if not ((signature := self.ordinary_signature(group))
                            and signature[0][0].__module__ != module_name
                            and signature in originals)
                )
            return self.suiteClass(retain(child) for child in current)

        return retain(suite)


def discover_suite(tests_root: Path | None = None) -> unittest.TestSuite:
    """Collect every standard test, keeping proven fixture aliases at their origin."""
    loader = DiscoveryLoader()
    suites = []
    for name in ("unit", "contract", "integration"):
        directory = (tests_root if tests_root is not None else ROOT / "tests") / name
        if directory.is_dir():
            suites.append(loader.discover(str(directory), top_level_dir=str(directory)))
    return loader.without_imported_fixtures(unittest.TestSuite(suites))


def run_all() -> bool:
    """Run the standard suite inside temporary, restored state roots."""
    import os as _os

    keys = ("HOUDINI_BRIDGE_STATE_DIR", "BRIDGE_SKILLS_STATE_ROOT",
            "BRIDGE_SKILLS_SCHEDULER_ROOT", "BRIDGE_ARTIFACT_LEDGER_ROOT")
    missing = object()
    previous = {key: _os.environ.get(key, missing) for key in keys}
    with TemporaryDirectory(prefix="bridge-skills-test-state-") as state_root:
        roots = {
            "HOUDINI_BRIDGE_STATE_DIR": state_root,
            "BRIDGE_SKILLS_STATE_ROOT": str(Path(state_root) / "bridge-state"),
            "BRIDGE_SKILLS_SCHEDULER_ROOT": str(Path(state_root) / "graph-scheduler"),
        }
        _os.environ.update(roots)
        # Derive each ledger from its test's isolated records directory;
        # a suite-wide override would merge independent test identities.
        _os.environ.pop("BRIDGE_ARTIFACT_LEDGER_ROOT", None)
        try:
            suite = discover_suite()
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return result.wasSuccessful()
        finally:
            for key, value in previous.items():
                if value is missing:
                    _os.environ.pop(key, None)
                else:
                    _os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(not run_all())
