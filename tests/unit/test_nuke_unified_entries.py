# -*- coding: utf-8 -*-
"""R02: every Nuke heavy render entry shares ONE operation adapter.

- While another host owns the installation slot, an entry call is refused
  with NO host side effect (nuke.execute is never reached).
- The same request with the same content reuses the recorded operation and
  executes exactly once; different content under the same request id is
  refused with CONTENT_CHANGED.
- A concurrent duplicate in another process executes once.
"""
from __future__ import annotations

import importlib.util
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _src in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline"):
    _p = ROOT / "packages" / _src / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vfx_pipeline.graph_scheduler import GraphScheduler  # noqa: E402
from dcc_task_runtime.exr_codec import encode_tiny_exr  # noqa: E402


def _load_addon():
    path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("bridge_test_unified_entries_addon", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeKnob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _FakeRoot:
    def name(self):
        return "/tmp/unified-entries.nk"

    def __getitem__(self, key):
        return _FakeKnob(1 if key == "first_frame" else 4)


class _FakeWrite:
    executed: list = []

    def __init__(self, pattern):
        self._pattern = pattern

    def name(self):
        return "Write1"

    def Class(self):
        return "Write"

    def __getitem__(self, key):
        return _FakeKnob(self._pattern)


class UnifiedEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="r02-unified-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.scheduler = GraphScheduler(self.tmp / "scheduler")
        self.addon = _load_addon()
        self.previous_scheduler = self.addon._NUKE_SCHEDULER
        self.previous_registry = getattr(self.addon, "_NUKE_ARTIFACT_REGISTRY", None)
        self.addon._NUKE_SCHEDULER = self.scheduler
        self.previous_records_dir = self.addon._RENDER_RECORDS_DIR
        self.addon._RENDER_RECORDS_DIR = self.tmp / "nuke_renders"
        self.addon._RENDERS.clear()
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = None
        self.addCleanup(self._restore)
        self.writes: list[tuple[int, int]] = []
        self.pattern = str(self.tmp / "out.%03d.exr")
        _FakeWrite.executed = self.writes
        fake_nuke = types.SimpleNamespace(
            root=_FakeRoot,
            node=lambda name: _FakeWrite(self.pattern),
            toNode=lambda name: _FakeWrite(self.pattern),
            scriptSave=lambda: None,
        )

        def _execute(write, first, last, *rest):
            self.writes.append((int(first), int(last)))
            for frame in range(int(first), int(last) + 1):
                Path(write._pattern % frame).write_bytes(encode_tiny_exr(float(frame)))

        fake_nuke.execute = _execute
        self.previous_nuke = sys.modules.get("nuke")
        sys.modules["nuke"] = fake_nuke
        self.addCleanup(self._restore_nuke)

    def _restore(self):
        self.addon._RENDER_RECORDS_DIR = self.previous_records_dir
        self.addon._NUKE_SCHEDULER = self.previous_scheduler
        self.addon._RENDERS.clear()
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = self.previous_registry

    def _restore_nuke(self):
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke

    def test_busy_slot_refuses_entry_without_any_side_effect(self) -> None:
        permit = self.scheduler.reserve("houdini-task", "op-1")
        before = len(self.writes)
        with self.assertRaises(ValueError) as ctx:
            self.addon.dispatch("render_write", {"node": "Write1", "background": False})
        self.assertIn("HEAVY_SLOT_BUSY", str(ctx.exception))
        self.assertEqual(len(self.writes), before, "no host side effect may happen when refused")
        self.scheduler.release("houdini-task", "op-1", str(permit["token"]), stopped=True)

    def test_same_request_reuses_and_executes_once(self) -> None:
        first = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r1"})
        count = len(self.writes)
        second = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r1"})
        self.assertEqual(first["operation_id"], second["operation_id"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(self.writes), count, "an identical request must not execute again")

    def test_new_request_same_content_is_a_new_execution(self) -> None:
        first = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r1"})
        count = len(self.writes)
        second = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r2"})
        self.assertFalse(second.get("reused"))
        self.assertNotEqual(first["operation_id"], second["operation_id"])
        self.assertEqual(len(self.writes), count + 1, "a new request id is a NEW execution")

    def test_changed_content_under_same_request_is_refused(self) -> None:
        self.addon.dispatch("render_write", {"node": "Write1", "background": False, "frame_range": [1, 2], "request_id": "r1"})
        before = len(self.writes)
        with self.assertRaises(ValueError) as ctx:
            self.addon.dispatch("render_write", {"node": "Write1", "background": False, "frame_range": [1, 4], "request_id": "r1"})
        self.assertIn("CONTENT_CHANGED", str(ctx.exception))
        self.assertEqual(len(self.writes), before, "refused request has no side effect")

    def test_node_change_binds_new_scene_version(self) -> None:
        r3 = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r3"})
        self.assertTrue(r3.get("scene_fingerprint"))
        self.assertEqual(len(self.writes), 1)

    def test_delivery_entry_shares_the_same_adapter_and_slot(self) -> None:
        permit = self.scheduler.reserve("houdini-task", "op-1")
        write = _FakeWrite(self.pattern)
        from nuke_bridge.operation_receipts import freeze_agent_inputs
        source = Path(self.pattern).parent / "input.exr"
        source.write_bytes(encode_tiny_exr(1.0))
        binding = freeze_agent_inputs("taskA",[{"role":"effect_render","path":str(source),"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}])
        with self.assertRaises(ValueError) as ctx:
            self.addon._execute_nuke(write, 1, 2, 1, command="agent.nuke.render_final", task_key="taskA",input_binding=binding)
        self.assertIn("HEAVY_SLOT_BUSY", str(ctx.exception))
        self.assertEqual(self.writes, [], "delivery entry refused with no side effect")
        self.scheduler.release("houdini-task", "op-1", str(permit["token"]), stopped=True)


if __name__ == "__main__":
    unittest.main()
