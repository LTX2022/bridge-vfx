# -*- coding: utf-8 -*-
"""C2 frozen acceptance: native API contract + request identity sequence.

- The native ``executeBackgroundNuke`` fake follows the OFFICIAL Nuke 17
  signature (exe_path, nodes, frameRange, views, limits) and returns an
  INTEGER task id (-1 failure) — never a Popen.  No poll/terminate may be
  attempted on it; cancellation is reported unsupported and the slot stays
  held for the control plane.
- Request identity sequence: r1 retried executes once; a NEW request r2 with
  the same content is a NEW execution; r1 with changed content is refused;
  after the node changes, r3 executes a third time and the record carries the
  new scene version fingerprint.
"""
from __future__ import annotations

import importlib.util
import json
import os
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

ADDON_PATH = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"


class _Knob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _Root:
    def __init__(self, name):
        self._name = name
        self.modified_flag = False

    def name(self):
        return self._name

    def modified(self):
        return self.modified_flag

    def __getitem__(self, key):
        return _Knob(1 if key == "first_frame" else 4)


class _Write:
    def __init__(self, pattern):
        self._pattern = pattern

    def name(self):
        return "Write1"

    def Class(self):
        return "Write"

    def __getitem__(self, key):
        return _Knob(self._pattern)


class _NativeNuke:
    """Fake built STRICTLY on the official Nuke 17 signature/types.

    executeBackgroundNuke(exe_path, nodes, frameRange, views, limits,
    continueOnError=False, flipbookToRun="", flipbookOptions={}) -> int
    task id (-1 failure).  No Popen, no poll, no terminate.
    """

    NUKE_VERSION_STRING = "17.0v1"

    def __init__(self, script_path, pattern):
        self._script_path = script_path
        self._pattern = pattern
        self.calls: list[dict] = []
        self.execute_calls = 0
        self._root = _Root(script_path)

    def root(self):
        return self._root

    def node(self, name):
        return _Write(self._pattern)

    def toNode(self, name):
        return _Write(self._pattern)

    def scriptSave(self):
        self._root.modified_flag = False
        source_pattern = str(Path(self._script_path).parent / "source.%03d.exr")
        for frame in (1, 2, 10000):
            Path(source_pattern % frame).write_bytes(encode_tiny_exr(float(frame)))
        Path(self._script_path).write_text(json.dumps({
            "schema": "bridge.software_nuke_snapshot/1",
            "root": {"first_frame": 1, "last_frame": 12},
            "nodes": {"Read1": {"class": "Read", "file": source_pattern, "inputs": []},
                      "Write1": {"class": "Write", "file": self._pattern, "inputs": ["Read1"]}},
        }, sort_keys=True), encoding="utf-8")

    def execute(self, write, first, last, *rest):
        self.execute_calls += 1
        for frame in range(int(first), int(last) + 1):
            Path(self._pattern % frame).write_bytes(encode_tiny_exr(float(frame)))
        return None

    def executeBackgroundNuke(self, exe_path, nodes, frameRange, views, limits,
                              continueOnError=False, flipbookToRun="", flipbookOptions={}):
        # STRICT type checks: anything else is a contract violation
        assert isinstance(exe_path, str), type(exe_path)
        assert isinstance(nodes, list) and all(isinstance(n, str) for n in nodes), nodes
        assert isinstance(frameRange, list) and all(isinstance(f, int) for f in frameRange), frameRange
        assert isinstance(views, list), views
        assert isinstance(limits, dict), limits
        self.calls.append({"exe_path": exe_path, "nodes": list(nodes),
                           "frameRange": list(frameRange), "views": list(views)})
        self._native_running = True
        return 7  # integer task id per the documented contract


class NativeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="c2-native-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._env_backup = {key: os.environ.get(key) for key in (
            "BRIDGE_SKILLS_STATE_ROOT", "BRIDGE_SKILLS_SCHEDULER_ROOT",
            "HOUDINI_BRIDGE_APPROVAL_SECRET")}
        os.environ["BRIDGE_SKILLS_STATE_ROOT"] = str(self.tmp)
        os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(self.tmp / "sched")
        os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = "unit-test-control-secret-0123456789abcdef"
        self.addCleanup(self._restore_env)
        spec = importlib.util.spec_from_file_location("_c2_native_addon", ADDON_PATH)
        self.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.addon)
        self.scheduler = GraphScheduler(self.tmp / "sched")
        self.previous_scheduler = self.addon._NUKE_SCHEDULER
        self.previous_artifact_registry = getattr(self.addon, "_NUKE_ARTIFACT_REGISTRY", None)
        self.previous_background_route = getattr(self.addon, "_NUKE_BACKGROUND_ROUTE", None)
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = None
        self.addon._NUKE_SCHEDULER = self.scheduler
        self.addon._NUKE_BACKGROUND_LAUNCHER = None  # native backend in these tests
        self.addon._NUKE_BACKGROUND_ROUTE = None
        self.previous_records_dir = self.addon._RENDER_RECORDS_DIR
        self.addon._RENDER_RECORDS_DIR = self.tmp / "nuke_renders"
        self.pattern = str(self.tmp / "out.%03d.exr")
        self.fake = _NativeNuke(str(self.tmp / "script.nk"), self.pattern)
        self.previous_nuke = sys.modules.get("nuke")
        sys.modules["nuke"] = self.fake
        self.addCleanup(self._restore)

    def _restore(self):
        self.addon._RENDER_RECORDS_DIR = self.previous_records_dir
        self.addon._NUKE_BACKGROUND_LAUNCHER = None
        self.addon._NUKE_BACKGROUND_ROUTE = self.previous_background_route
        self.addon._NUKE_SCHEDULER = self.previous_scheduler
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = self.previous_artifact_registry
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke

    def _restore_env(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_native_task_id_is_never_treated_as_a_process(self) -> None:
        result = self.addon.dispatch("render_write", {"node": "Write1", "background": True,
                                                      "background_backend": "native_task_id",
                                                      "nuke_executable": str(Path(sys.executable).resolve()),
                                                      "request_id": "native-r1"})
        self.assertEqual(result.get("backend"), "native_task_id")
        self.assertEqual(result.get("native_task_id"), 7)
        self.assertIs(result.get("native_cancel_supported"), False)
        # status: no process evidence from an int id; stays RUNNING
        status = self.addon.dispatch("render_status", {"task_id": result["task_id"]})
        self.assertEqual(status["state"], "RUNNING")
        self.assertIsNone(status.get("process_exited"))
        self.assertEqual(self.scheduler.snapshot()["active"], 1, "native task holds the slot")
        # cancel: the int id cannot be terminated -> unsupported, slot held
        cancel = self.addon.dispatch("render_cancel", {"task_id": result["task_id"]})
        self.assertFalse(cancel.get("stop_request_sent"))
        self.assertEqual(cancel["state"], "CANCEL_PENDING")
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # no poll/terminate-style calls were possible; one native launch
        self.assertEqual(len(self.fake.calls), 1)

    def test_request_identity_sequence(self) -> None:
        # r1: first execution
        r1 = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r1"})
        self.assertFalse(r1["reused"])
        self.assertEqual(self.fake.execute_calls, 1)
        # r1 retried (same request, same content): 1 execute total
        r1b = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r1"})
        self.assertTrue(r1b["reused"])
        self.assertEqual(self.fake.execute_calls, 1)
        # r2 (new request, same content): a NEW execution -> 2
        r2 = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r2"})
        self.assertFalse(r2["reused"])
        self.assertEqual(self.fake.execute_calls, 2)
        # r1 with changed content: refused, no side effect
        with self.assertRaises(ValueError) as ctx:
            self.addon.dispatch("render_write", {"node": "Write1", "background": False,
                                                 "frame_range": [1, 2], "request_id": "r1"})
        self.assertIn("CONTENT_CHANGED", str(ctx.exception))
        self.assertEqual(self.fake.execute_calls, 2)
        # node change (pattern change -> new scene/output): new request r3 -> 3
        self.fake._pattern = str(self.tmp / "out2.%03d.exr")
        self.fake.root().modified_flag = True
        r3 = self.addon.dispatch("render_write", {"node": "Write1", "background": False, "request_id": "r3"})
        self.assertFalse(r3["reused"])
        self.assertEqual(self.fake.execute_calls, 3)
        self.assertNotEqual(r3["scene_fingerprint"], r1["scene_fingerprint"],
                            "the r3 record must carry the new scene version")
        record = json.loads((self.addon._RENDER_RECORDS_DIR / "{}.json".format(r3["task_id"])).read_text())
        self.assertEqual(record["scene_fingerprint"], r3["scene_fingerprint"])

    def test_owned_worker_route_uses_verified_executable_snapshot_and_exact_frames(self) -> None:
        worker = ROOT / "tools" / "nuke_owned_render_worker.py"
        route = self.addon.configure_nuke_background_route(
            nuke_executable=str(Path(sys.executable).resolve()),
            worker_script=str(worker), software_api=True,
        )
        result = self.addon.dispatch("render_write", {
            "node": "Write1", "background": True, "background_backend": "owned",
            "frame_set": [1, 10000], "request_id": "owned-r1",
            "colorspace": "scene_linear", "premultiplied": False,
        })
        self.assertEqual(result["backend"], "owned_subprocess")
        self.assertEqual(result["process"]["argv0"], route["executable"])
        self.assertEqual(result["process"]["worker_script"], route["worker_script"])
        self.assertTrue(Path(result["script_snapshot"]).is_file())
        self.assertEqual(json.loads(result["process"]["argv"][-1]), [1, 10000])
        self.assertEqual(result["process"]["argv"][1], route["worker_script"])

        deadline = __import__("time").time() + 10
        status = None
        while __import__("time").time() < deadline:
            status = self.addon.dispatch("render_status", {"task_id": result["task_id"]})
            if status["state"] in {"COMPLETED", "FAILED", "NEEDS_RECONCILE"}:
                break
            __import__("time").sleep(0.05)
        self.assertIsNotNone(status)
        self.assertEqual(status["state"], "COMPLETED", status)
        self.assertEqual(status["verification"]["expected_frames"], [1, 10000])
        self.assertTrue((self.tmp / "out.001.exr").is_file())
        self.assertTrue((self.tmp / "out.10000.exr").is_file())
        self.assertFalse((self.tmp / "out.002.exr").exists())
        self.assertTrue(status.get("artifact"), status)
        self.assertEqual(self.scheduler.snapshot()["active"], 0)

    def test_owned_worker_exit_is_recoverable_after_controller_handle_loss(self):
        worker = ROOT / "tools" / "nuke_owned_render_worker.py"
        self.addon.configure_nuke_background_route(
            nuke_executable=str(Path(sys.executable).resolve()), worker_script=str(worker), software_api=True)
        result = self.addon.dispatch("render_write", {
            "node": "Write1", "background": True, "frame_set": [1, 2],
            "request_id": "restart-owned", "colorspace": "scene_linear", "premultiplied": False})
        task_id = result["task_id"]
        self.addon._RENDERS.clear()
        self.addon._RENDER_HANDLES.clear()
        import time
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.addon.dispatch("render_status", {"task_id": task_id})
            if status["state"] == "COMPLETED": break
            time.sleep(.01)
        self.assertEqual(status["state"], "COMPLETED", status)
        self.assertTrue(status["stop_confirmed"])
        self.assertEqual(self.scheduler.snapshot()["active"], 0)
        self.assertTrue(status["artifact"])


if __name__ == "__main__":
    unittest.main()
