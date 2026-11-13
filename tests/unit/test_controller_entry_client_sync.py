# -*- coding: utf-8 -*-
"""R05: the controller entry's bundled client must mirror the packages.

``controller-entry/client/`` is a copy of the two client packages the
acceptance entry imports.  A stale snapshot silently validates against code
that no longer ships.  The packages are the single generation source: every
bundled module must be byte-identical to its package source.
"""
from __future__ import annotations

import unittest
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "controller-entry" / "client"
MAPPING = {
    "dcc_task_runtime": ROOT / "packages" / "dcc-task-runtime" / "src" / "dcc_task_runtime",
    "houdini_bridge": ROOT / "packages" / "houdini-bridge" / "src" / "houdini_bridge",
}


class ControllerEntryClientSyncTests(unittest.TestCase):
    def test_every_bundled_client_module_matches_its_package_source(self) -> None:
        mismatches = []
        for module, source_dir in MAPPING.items():
            for source in sorted(source_dir.glob("*.py")):
                bundled = CLIENT / module / source.name
                if not bundled.is_file():
                    mismatches.append(f"missing bundled copy: {module}/{source.name}")
                    continue
                if source.read_bytes() != bundled.read_bytes():
                    mismatches.append(f"stale bundled copy: {module}/{source.name}")
        self.assertEqual(mismatches, [])

    def test_sync_check_is_read_only_and_write_is_repeatable(self) -> None:
        spec = importlib.util.spec_from_file_location("client_sync_test_tool", ROOT / "tools/sync_controller_client.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for module, package in tool.PACKAGES.items():
                source = root / "packages" / package / "src" / module
                source.mkdir(parents=True)
                (source / "__init__.py").write_text("SOURCE = True\n")
            target = root / "controller-entry/client/dcc_task_runtime"
            target.mkdir(parents=True)
            (target / "__init__.py").write_text("SOURCE = False\n")
            (target / "obsolete.py").write_text("stale\n")
            other = root / "controller-entry/client/other_plugin.py"
            other.write_text("preserve\n")
            changes = tool.synchronize(root)
            self.assertEqual(len(changes), 3)
            self.assertEqual((target / "__init__.py").read_text(), "SOURCE = False\n")
            self.assertTrue((target / "obsolete.py").is_file())
            self.assertEqual(tool.synchronize(root, write=True), changes)
            self.assertEqual(tool.synchronize(root), [])
            self.assertEqual(tool.synchronize(root, write=True), [])
            self.assertEqual(other.read_text(), "preserve\n")

    def test_no_extra_modules_in_the_bundled_client(self) -> None:
        extras = []
        for module, source_dir in MAPPING.items():
            for bundled in (CLIENT / module).glob("*.py"):
                if not (source_dir / bundled.name).is_file():
                    extras.append(f"{module}/{bundled.name}")
        self.assertEqual(extras, [])


if __name__ == "__main__":
    unittest.main()
