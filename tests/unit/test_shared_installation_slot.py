# -*- coding: utf-8 -*-
"""T02: ONE installation-wide heavy slot shared by Houdini and Nuke.

The GraphScheduler database is the single authority: Houdini frame
operations, Nuke renders and the graph flow must all resolve the same root
and must exclude each other.  A crashed holder leaves the slot blocked
until a control release with an observed stop; an idle executor must never
free a foreign reservation.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
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
from dcc_task_runtime.exr_codec import encode_tiny_exr  # noqa: E402


def _write_structural_exr(path: Path, payload: bytes = b"shared-slot-frame") -> None:
    path.write_bytes(encode_tiny_exr(float(sum(payload) % 2000 + 1)))
for _src in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline"):
    _p = ROOT / "packages" / _src / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vfx_pipeline.graph_scheduler import GraphScheduler, SchedulerBusy  # noqa: E402
from vfx_pipeline.paths import installation_scheduler_root  # noqa: E402

import test_operation_runner_recovery as _orr  # runner harness (real scheduler primitive)  # noqa: E402


class SharedInstallationSlotTests(_orr.OperationRunnerCase):
    """Runner-based cases reuse the harness with a real per-test scheduler."""

    def test_houdini_runner_and_foreign_owner_exclude_each_other(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        # a Nuke-like foreign owner reserving the same installation slot is refused
        with self.assertRaises(SchedulerBusy):
            self.m._test_scheduler.reserve("nuke:/script.nk", "render-1")
        runner.cancel(op["operation_id"])
        permit = self.m._test_scheduler.reserve("nuke:/script.nk", "render-1")
        self.assertTrue(permit["token"])
        # and now a Houdini submit is refused until the render releases
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        self.m._test_scheduler.release("nuke:/script.nk", "render-1", str(permit["token"]), stopped=True)

    def test_different_work_dirs_share_one_installation_slot(self) -> None:
        m = self.m
        first = m.OperationRunner("taskA", store_root=self.tmp_path / "workdirA")
        second = m.OperationRunner("taskB", store_root=self.tmp_path / "workdirB")
        op = first.submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(op["record"]["state"], "QUEUED")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            second.submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        first.cancel(op["operation_id"])

    def test_scheduler_root_is_single_and_installation_wide(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sched-root-") as tmp:
            previous = os.environ.get("BRIDGE_SKILLS_SCHEDULER_ROOT")
            os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(Path(tmp) / "sched")
            try:
                import importlib
                import vfx_pipeline.paths as paths
                importlib.reload(paths)
                self.assertEqual(paths.installation_scheduler_root(), Path(tmp) / "sched")
            finally:
                if previous is None:
                    os.environ.pop("BRIDGE_SKILLS_SCHEDULER_ROOT", None)
                else:
                    os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = previous
                importlib.reload(paths)


_NUKE_ADDON = None


def _load_nuke_addon():
    global _NUKE_ADDON
    if _NUKE_ADDON is None:
        path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
        spec = importlib.util.spec_from_file_location("bridge_test_shared_slot_nuke_addon", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _NUKE_ADDON = module
    return _NUKE_ADDON


class _FakeKnob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _FakeRoot:
    def __init__(self, name, first, last):
        self._name = name
        self._first = _FakeKnob(first)
        self._last = _FakeKnob(last)

    def name(self):
        return self._name

    def __getitem__(self, key):
        return self._first if key == "first_frame" else self._last


class _FakeWrite:
    def __init__(self, pattern):
        self._pattern = pattern

    def name(self):
        return "Write1"

    def Class(self):
        return "Write"

    def __getitem__(self, key):
        return _FakeKnob(self._pattern)


class NukeRenderSharedSlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="nuke-slot-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.scheduler = GraphScheduler(self.tmp / "scheduler")
        self.addon = _load_nuke_addon()
        self.previous_scheduler = self.addon._NUKE_SCHEDULER
        self.previous_records_dir = self.addon._RENDER_RECORDS_DIR
        self.previous_registry = getattr(self.addon, "_NUKE_ARTIFACT_REGISTRY", None)
        self.addon._RENDER_RECORDS_DIR = self.tmp / "nuke_renders"
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = None
        self.addon._NUKE_SCHEDULER = self.scheduler  # isolate the installation root
        self.previous_launcher = self.addon._NUKE_BACKGROUND_LAUNCHER
        self.addon._NUKE_BACKGROUND_LAUNCHER = self._launch_background
        self.previous_nuke = sys.modules.get("nuke")
        script = self.tmp / "script.nk"
        script.write_text("NUKE SCRIPT", encoding="utf-8")
        self.script = script
        pattern = str(self.tmp / "render.%03d.exr")
        self.pattern = pattern
        self._handle = None
        fake_nuke = types.SimpleNamespace(
            root=lambda: _FakeRoot(str(script), 1, 4),
            node=lambda name: _FakeWrite(pattern),
            toNode=lambda name: _FakeWrite(pattern),
            scriptSave=lambda: None,
            execute=lambda *a, **k: self._synchronous_render(),
        )
        fake_nuke.executeBackgroundNuke = self._launch_background
        sys.modules["nuke"] = fake_nuke
        self.addCleanup(self._restore_nuke)

    def _launch_background(self, task_id, script_path, node_name, first, last):
        class _Handle:
            pid = 424242
            _running = True
            terminate_called = False
            def poll(self_inner):
                return None if self_inner._running else 0
            def terminate(self_inner):
                self_inner.terminate_called = True  # signal sent; exit is async
        self._handle = _Handle()
        return {"pid": self._handle.pid, "kind": "owned_render_subprocess", "handle": self._handle}

    def _restore_nuke(self):
        self.addon._NUKE_BACKGROUND_LAUNCHER = self.previous_launcher
        self.addon._NUKE_SCHEDULER = self.previous_scheduler
        self.addon._RENDER_RECORDS_DIR = self.previous_records_dir
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = self.previous_registry
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke

    def _synchronous_render(self):
        for frame in (1, 2, 3, 4):
            path = self.tmp / "render.{:03d}.exr".format(frame)
            _write_structural_exr(path)

    def _frame_file(self, frame: int) -> Path:
        path = self.tmp / "render.{:03d}.exr".format(frame)
        _write_structural_exr(path)
        return path

    def test_synchronous_render_reserves_then_releases(self) -> None:
        addon = self.addon
        result = addon.dispatch("render_write", {"node": "Write1", "background": False})
        snapshot = self.scheduler.snapshot()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["active"], 0, "synchronous completion is an observed stop")
        self.assertEqual(result["frame_range"], [1, 4])

    def test_background_render_holds_slot_until_status_observes_completion(self) -> None:
        addon = self.addon
        result = addon.dispatch("render_write", {"node": "Write1", "background": True})
        task_id = result["task_id"]
        self.assertEqual(self.scheduler.snapshot()["active"], 1, "background render holds the slot")
        # foreign heavy jobs are excluded while the render runs
        with self.assertRaises(SchedulerBusy):
            self.scheduler.reserve("houdini-task", "op-1")
        # no files yet: status keeps the slot
        status = addon.dispatch("render_status", {"task_id": task_id})
        self.assertTrue(status["executing"])
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # frames appear but the owned process is still running: no completion
        for frame in (1, 2, 3, 4):
            self._frame_file(frame)
        status = addon.dispatch("render_status", {"task_id": task_id})
        self.assertTrue(status["executing"], "outputs alone never prove stopped")
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # process exit evidence completes the render and frees the slot once
        self._handle._running = False
        status = addon.dispatch("render_status", {"task_id": task_id})
        self.assertFalse(status["executing"])
        self.assertTrue(status["stop_confirmed_at"])
        self.assertEqual(self.scheduler.snapshot()["active"], 0)

    def test_render_write_refused_while_another_owner_holds(self) -> None:
        addon = self.addon
        permit = self.scheduler.reserve("houdini-task", "op-1")
        with self.assertRaises(ValueError) as ctx:
            addon.dispatch("render_write", {"node": "Write1", "background": False})
        self.assertIn("HEAVY_SLOT_BUSY", str(ctx.exception))
        self.scheduler.release("houdini-task", "op-1", str(permit["token"]), stopped=True)


if __name__ == "__main__":
    unittest.main()
