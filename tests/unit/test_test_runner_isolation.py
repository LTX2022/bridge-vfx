"""The standard runner must never inherit a caller's artifact ledger."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


class TestRunnerIsolationTests(unittest.TestCase):
    def exercise(self, *, inherited: bool, fail: bool):
        source = Path(__file__).resolve().parents[1] / "run_tests.py"
        spec = importlib.util.spec_from_file_location("_isolated_standard_runner", source)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        keys = ("HOUDINI_BRIDGE_STATE_DIR", "BRIDGE_SKILLS_STATE_ROOT",
                "BRIDGE_SKILLS_SCHEDULER_ROOT", "BRIDGE_ARTIFACT_LEDGER_ROOT")
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ):
            external = Path(temp) / "external-ledger"
            external.mkdir()
            sentinel = external / "sentinel"
            sentinel.write_text("unchanged")
            for key in keys:
                os.environ[key] = str(external)
            if not inherited:
                os.environ.pop("BRIDGE_ARTIFACT_LEDGER_ROOT")
            before = {key: os.environ.get(key) for key in keys}
            observed = []

            def run_suite(_suite):
                root = Path(os.environ["HOUDINI_BRIDGE_STATE_DIR"])
                self.assertNotIn("BRIDGE_ARTIFACT_LEDGER_ROOT", os.environ)
                addon_source = source.parents[1] / "plugins/nuke/nuke_bridge_addon.py"
                addon_spec = importlib.util.spec_from_file_location("_runner_ledger_probe", addon_source)
                addon = importlib.util.module_from_spec(addon_spec)
                addon_spec.loader.exec_module(addon)
                addon._RENDER_RECORDS_DIR = root / "case" / "nuke_renders"
                registry = addon._nuke_artifact_registry()
                ledger = root / "case" / "artifact_ledger"
                self.assertEqual(registry.root, ledger.resolve())
                self.assertNotEqual(ledger, external)
                self.assertTrue(ledger.is_relative_to(root))
                ledger.mkdir(parents=True, exist_ok=True)
                (ledger / "test-write").write_text("test only")
                observed.append(root)
                # A test can replace or remove environment values before failing.
                for key in keys:
                    os.environ.pop(key, None)
                if fail:
                    raise RuntimeError("fixture failure")
                return mock.Mock(wasSuccessful=lambda: True)

            with mock.patch.object(runner.unittest.defaultTestLoader, "discover", return_value=unittest.TestSuite()), \
                 mock.patch.object(runner.unittest.TextTestRunner, "run", side_effect=run_suite):
                if fail:
                    with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                        runner.run_all()
                else:
                    self.assertTrue(runner.run_all())
            self.assertEqual({key: os.environ.get(key) for key in keys}, before)
            self.assertEqual(sentinel.read_text(), "unchanged")
            self.assertEqual(list(external.iterdir()), [sentinel])
            self.assertTrue(observed)
            self.assertFalse(observed[0].exists())

    def test_inherited_ledger_isolated_and_restored(self):
        self.exercise(inherited=True, fail=False)

    def test_absent_ledger_removed_after_run(self):
        self.exercise(inherited=False, fail=False)

    def test_environment_restored_after_exception(self):
        self.exercise(inherited=True, fail=True)
