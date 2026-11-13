"""Fault injection regressions for cache freshness and asynchronous failures."""

from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


def load_addon():
    spec = importlib.util.spec_from_file_location("_bridge_review_addon", ADDON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Houdini Bridge add-on")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeUI:
    def __init__(self) -> None:
        self.callbacks = []

    def addEventLoopCallback(self, callback) -> None:
        self.callbacks.append(callback)

    def removeEventLoopCallback(self, callback) -> None:
        if callback in self.callbacks:
            self.callbacks.remove(callback)


class RaisingParm:
    def pressButton(self) -> None:
        raise RuntimeError("simulated Houdini button failure")


class FakeNodeType:
    def name(self) -> str:
        return "filecache"


class FakeOutputNode:
    def __init__(self, root) -> None:
        self._root = root

    def parent(self):
        return self._root


class FakeRoot:
    def __init__(self) -> None:
        self.cache_node = None

    def node(self, name):
        return self.cache_node if name == "FX_APPROVED_CACHE" else None

    def createNode(self, _node_type, _name):
        self.cache_node = FakeCacheNode(self)
        return self.cache_node


class FakeCacheNode:
    def __init__(self, root) -> None:
        self._root = root
        self.input_node = None

    def setInput(self, _index, node) -> None:
        self.input_node = node

    def input(self, _index):
        return self.input_node

    def path(self) -> str:
        return "/obj/FX_APPROVED_CACHE"


class HoudiniCacheRecoveryRegressions(unittest.TestCase):
    def test_cache_status_rejects_preexisting_file_not_updated_by_this_attempt(self) -> None:
        """A non-empty old frame must not satisfy an in-flight cache record."""

        addon = load_addon()
        with tempfile.TemporaryDirectory() as directory:
            old_path = Path(directory) / "sim.0001.bgeo.sc"
            old_path.write_bytes(b"old cache from an earlier run")
            old_stat = old_path.stat()
            pattern = str(Path(directory) / "sim.$F4.bgeo.sc")
            manifest = {
                "cache": {
                    "subject_hash": "subject-hash",
                    "node": "/obj/FX_APPROVED_CACHE",
                    "output_pattern": pattern,
                    "frames": [1],
                    # Deliberately newer than the old file: it records the
                    # snapshot taken immediately before the attempted launch.
                    "before": {
                        "1": {
                            "bytes": old_stat.st_size,
                            "modified_ns": old_stat.st_mtime_ns + 1,
                        }
                    },
                    "state": "STARTED",
                }
            }
            fake_hou = SimpleNamespace(node=lambda _path: object())
            with patch.dict(sys.modules, {"hou": fake_hou}), patch.object(
                addon, "_fx_manifest", return_value=(object(), manifest)
            ), patch.object(
                addon, "_fx_cache_subject", return_value=({}, "subject-hash")
            ):
                result = addon._fx_cache_status(
                    {"task_id": "task", "expected_subject_hash": "subject-hash"},
                    "pyro_smoke_v1",
                    {},
                )

            self.assertFalse(result["cached"])
            self.assertNotEqual(result["cache"]["state"], "COMPLETE")
            self.assertFalse(result["gates"][0]["passed"])

    def test_cache_button_without_owned_resource_contract_is_refused(self) -> None:
        addon = load_addon()
        root = FakeRoot()
        manifest = {"nodes": {"output": "/obj/output"}}
        params = {"task_id": "task", "constraints": {"fx": {}}, "render": {"frame_range": {"start": 1, "end": 1, "step": 1}}}
        with patch.object(addon, "_fx_manifest", return_value=(root, manifest)), patch.object(
            addon, "_fx_cache_subject", return_value=({}, "subject-hash")
        ), patch.object(addon, "_press_button_async") as press:
            with self.assertRaises(addon.BridgeCommandError) as caught:
                addon._fx_cache(params, "pyro_smoke_v1", {"simulation_cache": True})
            self.assertEqual(caught.exception.code, "APPROVAL_REQUIRED")
            press.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
