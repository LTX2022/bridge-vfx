# -*- coding: utf-8 -*-
"""Contract between the controller acceptance entry and the add-on state paths.

The acceptance entry locates the task manifest deterministically; that
derivation must stay in lockstep with the add-on's ``_fx_state_path`` (full-id
digest under ``<state root>/fx_tasks``).  The old entry derived a hex subset
with the wrong directory, which is exactly the "manifest directory written
wrong" defect; this test makes any future drift a test failure instead of a
silent wrong-path lookup.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
ENTRY_PATH = ROOT / "controller-entry" / "accept_core_chain.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _entry_manifest_state_path():
    """Extract manifest_state_path() from the entry without running its CLI."""
    tree = ast.parse(ENTRY_PATH.read_text(encoding="utf-8"))
    func = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "manifest_state_path")
    module = types_module()
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(ENTRY_PATH), "exec"), module)
    return module["manifest_state_path"]


def types_module():
    import types
    module: dict = {}
    module["sys"] = sys
    module["os"] = os
    module["Path"] = Path
    module["hashlib"] = hashlib
    return module


class AcceptanceEntryPathContractTests(unittest.TestCase):
    def test_entry_manifest_path_matches_addon_for_every_id_shape(self) -> None:
        addon = _load("_acceptance_contract_addon", ADDON_PATH)
        entry_path = _entry_manifest_state_path()
        for task_id in ("coreacc-0f3a", "task-01", "task-x01", "任务-中文-01", "t" * 64):
            self.assertEqual(entry_path(task_id), addon._fx_state_path(task_id),
                             "entry manifest derivation must match the add-on for %r" % task_id)

    def test_distinct_ids_map_to_distinct_manifest_paths(self) -> None:
        entry_path = _entry_manifest_state_path()
        self.assertNotEqual(entry_path("task-01"), entry_path("task-x01"))

    def test_derivation_uses_full_id_digest(self) -> None:
        entry_path = _entry_manifest_state_path()
        expected_digest = hashlib.sha256("task-01".encode("utf-8")).hexdigest()[:16]
        self.assertIn("fx_%s.json" % expected_digest, str(entry_path("task-01")))


if __name__ == "__main__":
    unittest.main()
