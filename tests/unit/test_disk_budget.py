# -*- coding: utf-8 -*-
"""R08: configurable disk budget for task-owned output directories."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DiskBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="disk-budget-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.previous = os.environ.get("HOUDINI_BRIDGE_DISK_BUDGET_MB")
        self.addCleanup(self._restore)

    def _restore(self):
        if self.previous is None:
            os.environ.pop("HOUDINI_BRIDGE_DISK_BUDGET_MB", None)
        else:
            os.environ["HOUDINI_BRIDGE_DISK_BUDGET_MB"] = self.previous

    def _addon(self):
        spec = importlib.util.spec_from_file_location(
            "_disk_budget_addon", ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_not_enforced_without_configuration(self) -> None:
        addon = self._addon()
        report = addon._fx_check_disk_budget(self.tmp)
        self.assertIs(report["enforced"], False)

    def test_refuses_over_budget_and_preserves_everything(self) -> None:
        addon = self._addon()
        (self.tmp / "task").mkdir()
        (self.tmp / "task" / "cache.bin").write_bytes(b"x" * 4096)
        os.environ["HOUDINI_BRIDGE_DISK_BUDGET_MB"] = "0.001"  # ~1048 bytes
        with self.assertRaises(addon.BridgeCommandError) as ctx:
            addon._fx_check_disk_budget(self.tmp / "task", estimated_bytes=2048)
        self.assertEqual(ctx.exception.code, "DISK_BUDGET_EXCEEDED")
        self.assertTrue((self.tmp / "task" / "cache.bin").is_file(), "nothing may be deleted")

    def test_allows_under_budget(self) -> None:
        addon = self._addon()
        (self.tmp / "task").mkdir()
        os.environ["HOUDINI_BRIDGE_DISK_BUDGET_MB"] = "100"
        report = addon._fx_check_disk_budget(self.tmp / "task", estimated_bytes=1024)
        self.assertIs(report["enforced"], True)

    def test_nuke_side_budget(self) -> None:
        sys.path.insert(0, str(ROOT / "packages" / "dcc-task-runtime" / "src"))
        sys.path.insert(0, str(ROOT / "packages" / "nuke-bridge" / "src"))
        spec = importlib.util.spec_from_file_location(
            "_disk_budget_nuke_addon", ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_nuke_budget = os.environ.get("NUKE_BRIDGE_DISK_BUDGET_MB")
        os.environ["NUKE_BRIDGE_DISK_BUDGET_MB"] = "0.001"
        try:
            with self.assertRaises(ValueError) as ctx:
                module._fx_check_disk_budget(self.tmp, estimated_bytes=4096)
            self.assertIn("DISK_BUDGET_EXCEEDED", str(ctx.exception))
        finally:
            if previous_nuke_budget is None:
                os.environ.pop("NUKE_BRIDGE_DISK_BUDGET_MB", None)
            else:
                os.environ["NUKE_BRIDGE_DISK_BUDGET_MB"] = previous_nuke_budget


if __name__ == "__main__":
    unittest.main()
