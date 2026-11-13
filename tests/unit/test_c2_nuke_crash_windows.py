"""C2 public recovery entry: fault windows use real durable scheduling."""
from __future__ import annotations

import sys
import time
import unittest
from unittest import mock

import test_nuke_render_persistence as fixtures


class NukeCrashWindowTests(unittest.TestCase):
    setUp = fixtures.NukeRenderPersistenceTests.setUp
    _restore = fixtures.NukeRenderPersistenceTests._restore
    _restore_secret = fixtures.NukeRenderPersistenceTests._restore_secret
    _launch_background = fixtures.NukeRenderPersistenceTests._launch_background
    _sign = fixtures.NukeRenderPersistenceTests._sign
    _write_fresh_frames = fixtures.NukeRenderPersistenceTests._write_fresh_frames

    def resolve(self, action, task_id):
        return self.addon.dispatch("control.render_resolve", {
            "action": action, "task_id": task_id,
            "authorization": {"verified_by": "software-test-controller",
                              "signature": self._sign(action, {"task_id": task_id})}})

    def launch(self, request_id="crash-request"):
        return self.addon.dispatch("render_write", {
            "node": "Write1", "background": True, "request_id": request_id})

    def kinds(self):
        return [item["kind"] for item in
                self.addon.dispatch("control.render_recover", {})["orphans"]]

    def test_reservation_without_record_can_be_fenced_and_released(self):
        with mock.patch.object(self.addon, "_persist_render_record",
                               side_effect=RuntimeError("crash before first record")):
            with self.assertRaisesRegex(RuntimeError, "crash before"):
                self.launch()
        slot = self.scheduler.snapshot()
        task_id = slot["operation_id"]
        self.assertIsNone(self.addon._load_render_record(task_id))
        self.assertIsNone(self.handle)
        self.assertIn("reserved_without_record", self.kinds())
        self.assertEqual(self.scheduler.snapshot(), slot, "discovery must be read-only")
        self.assertTrue(self.resolve("release_unstarted", task_id)["released"])
        self.assertFalse(self.scheduler.snapshot()["active"])
        result = self.launch()
        self.assertFalse(result["reused"])
        self.assertEqual(result["task_id"], task_id)
        self.assertIsNotNone(self.handle)

    def test_recovered_unstarted_permit_fences_a_resuming_launcher(self):
        original = self.scheduler.arm

        def revoke(owner, operation, token):
            self.assertTrue(self.scheduler.fence_unstarted(owner, operation, token))
            self.assertTrue(self.scheduler.release(owner, operation, token, unstarted=True))
            original(owner, operation, token)

        with mock.patch.object(self.scheduler, "arm", side_effect=revoke):
            with self.assertRaisesRegex(ValueError, "fenced"):
                self.launch()
        self.assertIsNone(self.handle, "a revoked permit must never call the host")
        self.assertFalse(self.scheduler.snapshot()["active"])

    def test_unknown_dispatch_is_called_once_and_cannot_be_released(self):
        calls = []

        def uncertain(*args):
            calls.append(args)
            raise TypeError("dispatch outcome unknown")

        self.addon._NUKE_BACKGROUND_LAUNCHER = uncertain
        with self.assertRaisesRegex(TypeError, "outcome unknown"):
            self.launch()
        slot = self.scheduler.snapshot()
        self.assertEqual(len(calls), 1)
        self.assertEqual(slot["phase"], "DISPATCHING")
        self.assertIn("launch_not_saved", self.kinds())
        with self.assertRaisesRegex(ValueError, "UNSTARTED_UNPROVEN"):
            self.resolve("release_unstarted", slot["operation_id"])
        self.assertTrue(self.scheduler.snapshot()["active"])

    def test_corrupt_record_and_unknown_slot_remain_held(self):
        result = self.launch()
        task_id = result["task_id"]
        (self.addon._render_records_dir() / (task_id + ".json")).write_text("{broken")
        self.addon._RENDERS.clear()
        self.assertIn("unknown_active", self.kinds())
        with self.assertRaises(ValueError):
            self.resolve("release_unstarted", task_id)
        self.assertTrue(self.scheduler.snapshot()["active"])

    def test_terminal_label_without_stop_fact_is_not_releasable(self):
        result = self.launch()
        task_id = result["task_id"]
        record = self.addon._load_render_record(task_id)
        record["state"] = "COMPLETED"
        self.addon._persist_render_record(record)
        with self.assertRaisesRegex(ValueError, "STOP_UNCONFIRMED"):
            self.resolve("release_terminal", task_id)
        self.assertTrue(self.scheduler.snapshot()["active"])

    def test_pid_liveness_is_not_adoption_evidence(self):
        result = self.launch()
        with mock.patch.object(self.addon, "_fx_pid_alive", return_value=True):
            with self.assertRaisesRegex(ValueError, "ADOPT_UNVERIFIED"):
                self.resolve("adopt_launched", result["task_id"])
        self.assertTrue(self.scheduler.snapshot()["active"])

    def test_wrong_operation_never_releases_another_slot(self):
        self.launch()
        before = self.scheduler.snapshot()
        with self.assertRaises(ValueError):
            self.resolve("release_unstarted", "another-operation")
        self.assertEqual(before, self.scheduler.snapshot())

    def test_same_operation_stale_marker_cannot_release_another_owner(self):
        with mock.patch.object(self.addon, "_persist_render_record", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.launch()
        old = self.scheduler.snapshot()
        self.assertTrue(self.scheduler.fence_unstarted(old["owner_root"], old["operation_id"], old["token"]))
        self.assertTrue(self.scheduler.release(old["owner_root"], old["operation_id"], old["token"], unstarted=True))
        self.scheduler.reserve("nuke:another-task", old["operation_id"])
        before = self.scheduler.snapshot()
        with self.assertRaisesRegex(ValueError, "UNSTARTED_UNPROVEN"):
            self.resolve("release_unstarted", old["operation_id"])
        self.assertEqual(before, self.scheduler.snapshot())

    def test_synchronous_unknown_dispatch_is_not_retried_or_released(self):
        execute = mock.Mock(side_effect=TypeError("synchronous outcome unknown"))
        with mock.patch.object(sys.modules["nuke"], "execute", execute, create=True):
            with self.assertRaisesRegex(TypeError, "outcome unknown"):
                self.addon.dispatch("render_write", {
                    "node": "Write1", "background": False, "request_id": "sync-unknown"})
        self.assertEqual(execute.call_count, 1)
        slot = self.scheduler.snapshot()
        self.assertTrue(slot["active"])
        self.assertEqual(slot["phase"], "DISPATCHING")
        record = self.addon._load_render_record(slot["operation_id"])
        self.assertEqual(record["state"], "NEEDS_RECONCILE")

    def test_completed_record_before_slot_release_recovers_without_render(self):
        def execute(write, first, last):
            self._write_fresh_frames(range(first, last + 1))
        with mock.patch.object(sys.modules["nuke"], "execute", side_effect=execute, create=True) as host:
            with mock.patch.object(self.addon, "_fx_release_render_slot", return_value=None):
                result = self.addon.dispatch("render_write", {
                    "node": "Write1", "background": False, "request_id": "terminal-crash",
                    "colorspace": "scene_linear", "premultiplied": False})
            self.addon._RENDERS.clear()
            self.assertTrue(self.scheduler.snapshot()["active"])
            self.assertIn("terminal_not_released", self.kinds())
            self.assertTrue(self.resolve("release_terminal", result["task_id"])["released"])
            self.assertFalse(self.scheduler.snapshot()["active"])
            self.assertEqual(host.call_count, 1)

    def test_launch_receipt_before_record_commit_rebinds_exact_supervisor(self):
        from pathlib import Path
        from test_c2_nuke_contract import _NativeNuke
        sys.modules["nuke"] = _NativeNuke(str(self.tmp / "script.nk"), self.pattern)
        self.addon.configure_nuke_background_route(
            nuke_executable=str(Path(sys.executable).resolve()),
            worker_script=str(fixtures.ROOT / "tools/nuke_owned_render_worker.py"), software_api=True)
        original = self.addon._persist_render_record
        def crash(record):
            if record.get("process"):
                raise RuntimeError("crash after launch before identity commit")
            original(record)
        try:
            with mock.patch.object(self.addon, "_persist_render_record", side_effect=crash):
                with self.assertRaisesRegex(RuntimeError, "before identity commit"):
                    self.addon.dispatch("render_write", {
                        "node": "Write1", "background": True, "frame_set": [1, 2],
                        "request_id": "launch-crash", "colorspace": "scene_linear", "premultiplied": False})
            task_id = self.scheduler.snapshot()["operation_id"]
            handle = self.addon._RENDER_HANDLES[task_id]
            self.addon._RENDERS.clear()
            self.addon._RENDER_HANDLES.clear()
            self.assertIsNone(self.addon._load_render_record(task_id).get("process"))
            self.assertIn("launch_not_saved", self.kinds())
            self.assertTrue(self.resolve("adopt_launched", task_id)["adopted"])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                status = self.addon.dispatch("render_status", {"task_id": task_id})
                if status["state"] == "COMPLETED":
                    break
                time.sleep(.01)
            self.assertEqual(status["state"], "COMPLETED", status)
            self.assertTrue(status["artifact"])
            self.assertFalse(self.scheduler.snapshot()["active"])
        finally:
            for owned in set(self.addon._RENDER_HANDLES.values()):
                if owned is not None:
                    if owned.poll() is None:
                        owned.terminate()
                    owned.wait(timeout=10)
            if "handle" in locals():
                handle.wait(timeout=10)

    def test_owned_nonzero_exit_never_becomes_completed(self):
        from pathlib import Path
        worker = self.tmp / "nonzero-worker.py"
        worker.write_text("raise SystemExit(42)\n", encoding="utf-8")
        self.addon.configure_nuke_background_route(
            nuke_executable=str(Path(sys.executable).resolve()), worker_script=str(worker), software_api=True)
        result = self.launch("nonzero-exit")
        handle = self.addon._RENDER_HANDLES[result["task_id"]]
        try:
            self.assertEqual(handle.wait(timeout=10), 42)
            status = self.addon.dispatch("render_status", {"task_id": result["task_id"]})
            self.assertEqual(status["state"], "FAILED")
            self.assertEqual(status["exit_code"], 42)
            self.assertTrue(status["stop_confirmed"])
            self.assertFalse(self.scheduler.snapshot()["active"])
            self.assertIsNone(status.get("artifact"))
        finally:
            if handle.poll() is None:
                handle.terminate()
            handle.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
