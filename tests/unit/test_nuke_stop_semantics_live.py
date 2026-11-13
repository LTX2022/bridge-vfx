# -*- coding: utf-8 -*-
"""R04 review repro with a REAL live child process (controlled, terminated).

Mirrors the reviewer's reproduction: a background render whose owned child
process is still alive must NOT be reported as stopped even when every frame
is already on disk; the slot stays held; cancel sends an actual terminate();
only confirmed process exit releases the slot — exactly once.
"""
from __future__ import annotations

import importlib.util
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


def _write_structural_exr(path: Path, payload: bytes = b"live-child-frame") -> None:
    path.write_bytes(encode_tiny_exr(float(sum(payload) % 2000 + 1)))
for _src in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline"):
    _p = ROOT / "packages" / _src / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vfx_pipeline.graph_scheduler import GraphScheduler  # noqa: E402


def _load_addon():
    path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("bridge_test_r04_live_child_addon", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeKnob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _FakeRoot:
    def __init__(self, name):
        self._name = name
        self._first = _FakeKnob(1)
        self._last = _FakeKnob(4)

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


class LiveChildStopSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="r04-live-child-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.scheduler = GraphScheduler(self.tmp / "scheduler")
        self.addon = _load_addon()
        self.addon._NUKE_SCHEDULER = self.scheduler
        self.previous_launcher = self.addon._NUKE_BACKGROUND_LAUNCHER
        self.addon._NUKE_BACKGROUND_LAUNCHER = self._launch_real_child
        self.previous_records_dir = self.addon._RENDER_RECORDS_DIR
        self.addon._RENDER_RECORDS_DIR = self.tmp / "nuke_renders"
        self.addCleanup(self._restore)
        self.pattern = str(self.tmp / "render.%03d.exr")
        self.children = []
        self.previous_nuke = sys.modules.get("nuke")
        script_path = self.tmp / "script.nk"
        script_path.write_text("NUKE SOFTWARE TEST SCRIPT\n", encoding="utf-8")
        fake_nuke = types.SimpleNamespace(
            root=lambda: _FakeRoot(str(script_path)),
            node=lambda name: _FakeWrite(self.pattern),
            toNode=lambda name: _FakeWrite(self.pattern),
            scriptSave=lambda: script_path.write_text("NUKE SOFTWARE TEST SCRIPT\n", encoding="utf-8"),
        )
        fake_nuke.executeBackgroundNuke = self._launch_real_child
        sys.modules["nuke"] = fake_nuke

    def _restore(self):
        self.addon._RENDER_RECORDS_DIR = self.previous_records_dir
        self.addon._NUKE_BACKGROUND_LAUNCHER = self.previous_launcher
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)

    def _launch_real_child(self, task_id, script_path, node_name, first, last):
        from dcc_task_runtime.owned_process import launch
        release_path = self.tmp / 'child-release'
        identity = {'task_id':task_id,'operation_id':task_id,'launch_nonce':'controlled-child'}
        directory = self.addon._render_records_dir() / (task_id + '.supervisor')
        executable = getattr(sys, '_base_executable', None) or sys.executable
        child = launch([executable, '-c',
                        'from pathlib import Path\nimport sys,time\n'
                        'release=Path(sys.argv[1])\n'
                        'while not release.exists(): time.sleep(.01)\n', str(release_path)],
                      directory=directory,identity=identity,supervisor_executable=executable)
        self.children.append(child)
        return {'pid':child.pid,'kind':'owned_render_subprocess','handle':child,
                'supervisor_directory':str(directory),'supervisor_identity':identity}

    def _write_fresh_frames(self):
        for frame in (1, 2, 3, 4):
            path = Path(self.pattern % frame)
            _write_structural_exr(path, f"live-child-{frame}".encode("ascii"))

    def test_outputs_complete_with_live_child_hold_slot_until_confirmed_exit(self) -> None:
        result = self.addon.dispatch("render_write", {"node": "Write1", "background": True})
        task_id = result["task_id"]
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        self._write_fresh_frames()
        # all frames on disk, child ALIVE: not stopped, slot stays held
        status = self.addon.dispatch("render_status", {"task_id": task_id})
        self.assertTrue(status["executing"])
        self.assertIsNone(status["stop_confirmed_at"])
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # cancel sends an actual terminate() against the owned child
        cancel = self.addon.dispatch("render_cancel", {"task_id": task_id})
        self.assertTrue(cancel["cancel_requested"])
        self.assertTrue(cancel["stop_request_sent"])
        # the child may not be dead yet at this instant
        if cancel["process_exited"] is not True:
            self.assertEqual(cancel["state"], "CANCEL_PENDING")
            self.assertIsNone(cancel["stop_confirmed_at"])
            self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # confirm exit (wait for the real process to die) → release once
        child = self.children[0]
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("terminated child did not exit")
        status = self.addon.dispatch("render_status", {"task_id": task_id})
        self.assertFalse(status["executing"])
        self.assertTrue(status["stop_confirmed_at"])
        self.assertEqual(self.scheduler.snapshot()["active"], 0)
        # already terminal: a later cancel never rewrites history
        again = self.addon.dispatch("render_cancel", {"task_id": task_id})
        self.assertEqual(again["state"], "CANCELLED")
        self.assertEqual(self.scheduler.snapshot()["active"], 0)


if __name__ == "__main__":
    unittest.main()
