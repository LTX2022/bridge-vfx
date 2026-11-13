# -*- coding: utf-8 -*-
"""R1/R2/R3 failure-injection tests for OperationRunner and host lifecycle.

Method mirrors the independent review's reproduce.py: the OperationRunner class
is extracted verbatim from the addon source via AST with a fake ``hou`` module,
so these tests run without a DCC and target the exact shipped class.

Standard-library unittest so ``tests/run_tests.py`` discovers every case.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from uuid import uuid4

ADDON = Path(__file__).resolve().parents[2] / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"

_ROOT = Path(__file__).resolve().parents[2]
for _src in ("packages/vfx-pipeline/src", "packages/dcc-task-runtime/src", "packages/nuke-bridge/src", "packages/houdini-bridge/src"):
    if str(_ROOT / _src) not in sys.path:
        sys.path.insert(0, str(_ROOT / _src))

_HB_SRC = _ROOT / "packages" / "houdini-bridge" / "src"
if str(_HB_SRC) not in sys.path:
    sys.path.insert(0, str(_HB_SRC))


class FakeServer:
    port = 8101
    session_id = "sess"


class FakeGeometry:
    def boundingBox(self):
        class BB:
            def sizevec(self):
                return (0.0, 0.0, 0.0)
        return BB()

    def points(self):
        return []

    def prims(self):
        return []

    def pointAttribs(self):
        return []


class FakeNode:
    def userData(self, name):
        return None

    def cook(self, force=False):
        pass

    def errors(self):
        return []

    def geometry(self):
        return FakeGeometry()


def build_runner_module(tmp_path, extra_env=None):
    """Extract OperationRunner + helpers verbatim; inject fake dependencies."""
    tree = ast.parse(ADDON.read_text(encoding="utf-8"))
    helpers = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_fx_frame_values", "_fx_configuration", "_task_name",
            "_check_executor_generation", "fx_operation_runner",
            "_fx_pack_declared_connections", "_validate_reconcile_evidence",
            "_reconcile_source_is_trusted", "_reconcile_observed_at_is_valid",
            "_lifecycle_fact_digest", "_new_lifecycle_fact",
            "_lifecycle_fact_is_valid",
            "_fx_producer_record", "_fx_reject_producer_operation_id",
        ):
            helpers.append(node)
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OperationRunner")
    module = types.ModuleType("runner_under_test")
    module.hou = types.SimpleNamespace(node=lambda p: FakeNode(), setFrame=lambda f: None, time=lambda: 0.0)
    module.hou_node = lambda p: FakeNode()
    module.hou_set_frame = lambda f: None
    module.hou_time = lambda: 0.0
    module.os = os
    module.json = json
    module.re = __import__("re")
    module.time = time
    module.hashlib = __import__("hashlib")
    module.hmac = __import__("hmac")
    module.threading = threading
    module.uuid4 = uuid4
    module.Path = Path
    module.datetime = __import__("datetime").datetime
    module.timezone = __import__("datetime").timezone
    from contextlib import contextmanager as _cm
    module.contextmanager = _cm
    module.BridgeCommandError = type("BridgeCommandError", (RuntimeError,), {})
    module._SERVER = FakeServer()
    module._FX_LOADED_ADDON_SHA256 = "0" * 64
    # real control-authorization verification from the shipped addon module
    import importlib.util as _ilu
    _addon_spec = _ilu.spec_from_file_location("_runner_test_addon", ADDON)
    _addon_mod = _ilu.module_from_spec(_addon_spec)
    _addon_spec.loader.exec_module(_addon_mod)
    module._verify_control_authorization = _addon_mod._verify_control_authorization
    module._approval_secret_value = _addon_mod._approval_secret_value
    module.BridgeCommandError = _addon_mod.BridgeCommandError  # one error class across the real code path
    module._root_lease_check = lambda root, task_id=None, scope=None: {"root": root, "status": "ACTIVE", "version": 1}
    module._root_lease_read = lambda root: {"root": root, "status": "ACTIVE", "version": 1}
    @module.contextmanager
    def _test_root_lease_fence(root, *, task_id=None, scope=None):
        module._root_lease_check(root, task_id=task_id, scope=scope)
        yield {"root": root, "status": "ACTIVE", "version": 1}
    module._root_lease_fence = _test_root_lease_fence
    module._fx_check_disk_budget = lambda directory, estimated_bytes=0: {"enforced": False}
    module._root_lease_issue = lambda root, task_id, scope: {"root": root}
    module._fx_operations_store_path = lambda task: tmp_path / ("ops_%s.json" % task)
    module._fx_legacy_operations_store_path = lambda task: tmp_path / ("legacy_ops_%s.json" % task)
    # real installation slot primitive, isolated per-test scheduler root
    from vfx_pipeline.graph_scheduler import GraphScheduler as _GS
    _test_scheduler = _GS(tmp_path / "scheduler")
    module._fx_graph_scheduler = lambda: _test_scheduler
    module._test_scheduler = _test_scheduler
    module._fx_host_generation = lambda: uuid4().hex[:12]
    module._fx_frame_values = lambda p: p.get("frames") or [1]
    module._fx_manifest = lambda t, **k: (None, {"domain_pack": "p", "nodes": {"output": "/out"}, "input_digest": "same"})
    module._check_executor_generation = lambda t: None
    module._task_name = lambda task, prefix: prefix + "_" + task
    module._task_paths = lambda t: ("/obj/model_" + t, "/stage/model_" + t)
    module._fx_task_paths = lambda t, root=None: ("/obj/BRIDGE_FX_" + t, "/stage/st_" + t)
    module._fx_state_path = lambda t: tmp_path / ("state_%s.json" % t)
    module._fx_task_saves_path = lambda t: tmp_path / ("saves_%s.json" % t)
    module._load_core_contract = _addon_mod._load_core_contract
    # real durable lock (vendored, same primitive as the runtime package)
    lock_spec = __import__("importlib").util.spec_from_file_location(
        "_test_durable_lock", ADDON.parent / "durable_lock.py")
    lock_module = __import__("importlib").util.module_from_spec(lock_spec)
    lock_spec.loader.exec_module(lock_module)
    module._durable_execution_lock = lock_module.execution_lock
    tmp_path.mkdir(parents=True, exist_ok=True)
    code = ast.Module(body=helpers + [klass], type_ignores=[])
    exec(compile(code, str(ADDON), "exec"), vars(module))
    return module


def control_auth(action, payload, secret="unit-test-control-secret-0123456789abcdef"):
    import hashlib as _h
    import hmac as _hm
    import json as _j
    body = _j.dumps({"action": action, **payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"verified_by": "controller/" + action, "signature": _hm.new(secret.encode(), body.encode(), _h.sha256).hexdigest()}


class OperationRunnerCase(unittest.TestCase):
    """Base: fresh store directory and runner module per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="op-runner-case-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self._previous_secret = os.environ.get("HOUDINI_BRIDGE_APPROVAL_SECRET")
        os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = "unit-test-control-secret-0123456789abcdef"
        self.addCleanup(self._restore_secret)
        self._finish_setup()

    def _restore_secret(self):
        if self._previous_secret is None:
            os.environ.pop("HOUDINI_BRIDGE_APPROVAL_SECRET", None)
        else:
            os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = self._previous_secret

    def _finish_setup(self):
        if "hou" not in sys.modules:
            sys.modules["hou"] = types.SimpleNamespace(
                node=lambda p: FakeNode(), setFrame=lambda f: None, time=lambda: 0.0,
                applicationVersionString=lambda: "21.0.631", isUIAvailable=lambda: False)
        self.m = build_runner_module(self.tmp_path)


# ---------------------------------------------------------------- R1
class TestR1PersistentOperations(OperationRunnerCase):
    def test_corrupt_store_preserved_and_refused(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        runner.submit({"frames": [2]}, "p", {})
        store = m._fx_operations_store_path("t")
        store.write_text("{corrupt", encoding="utf-8")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(ctx.exception.code, "CORRUPT_STORE")
        # the broken bytes are preserved for reconciliation, never treated as empty
        preserved = list(self.tmp_path.glob("ops_t.json.corrupt*"))
        self.assertTrue(preserved, "corrupt record must be preserved")

    def test_second_task_cannot_start_heavy_job_while_first_running(self) -> None:
        m = self.m
        a = m.OperationRunner("taskA")
        b = m.OperationRunner("taskB")
        op = a.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        a.advance()  # claims and cooks frame one; op still RUNNING -> slot held
        store = json.loads(m._fx_operations_store_path("taskA").read_text())
        self.assertEqual(store["operations"][op["request_id"]]["state"], "RUNNING")
        with self.assertRaises(m.BridgeCommandError) as ctx:
            b.submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        a.cancel(op["request_id"])

    def test_concurrent_same_request_single_claim(self) -> None:
        m = self.m
        results = []
        errors = []

        def fire():
            r = m.OperationRunner("t")
            try:
                results.append(r.submit({"frames": [2, 4]}, "p", {}))
            except Exception as exc:  # BUSY is acceptable for the loser
                errors.append(exc)

        threads = [threading.Thread(target=fire) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ids = {r["operation_id"] for r in results}
        self.assertLessEqual(len(ids), 1, "same request must map to one claim")

    def test_identity_fields_split(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        record = op["record"]
        self.assertEqual(record["request_id"], op["operation_id"])
        self.assertTrue(record.get("execution_id"))
        self.assertIn(record.get("claimed_by_generation"), (None, runner.generation))


# ---------------------------------------------------------------- R2
class TestR2RecoveryWithoutQueries(OperationRunnerCase):
    def test_advance_claims_queued_itself(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        self.assertEqual(op["record"]["state"], "QUEUED")
        runner.advance()
        store = json.loads(m._fx_operations_store_path("t").read_text())
        rec = store["operations"][op["operation_id"]]
        self.assertIn(rec["state"], ("RUNNING", "COMPLETED", "CANCEL_PENDING"))
        self.assertTrue(rec["frames_done"], "advance must cook without any status query")
        self.assertEqual(rec.get("claimed_by_generation"), runner.generation)

    def test_status_is_pure_read(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        before = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]["state"]
        runner.status(op["operation_id"])
        after = json.loads(m._fx_operations_store_path("t").read_text())["operations"][op["operation_id"]]["state"]
        self.assertEqual(before, "QUEUED")
        self.assertEqual(after, "QUEUED")
        self.assertEqual(before, after, "status must not start execution")

    def test_stale_running_becomes_reconcile_via_advance_not_status(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        rec = store["operations"][op["operation_id"]]
        rec["state"] = "RUNNING"
        rec["claimed_by_generation"] = "dead-generation"
        rec["execution_id"] = "dead-exec"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        runner.status(op["operation_id"])  # pure read: no promotion, no reconcile write
        on_disk = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertEqual(on_disk["state"], "RUNNING")
        fresh = m.OperationRunner("t")  # new generation takes over via advance
        fresh.advance()
        on_disk = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertEqual(on_disk["state"], "RECONCILE", "unknown-result frame work must not auto-rerun")

    def test_queued_from_old_generation_is_claimable(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        store["operations"][op["operation_id"]]["generation"] = "dead-generation"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        fresh = m.OperationRunner("t")
        fresh.advance()  # queued work was never executed: claimable
        on_disk = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertIn(on_disk["state"], ("RUNNING", "COMPLETED"))

    def test_cancel_pending_observed_then_cancelled(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        runner.advance()
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        store["operations"][op["operation_id"]]["state"] = "CANCEL_PENDING"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        runner.advance()
        on_disk = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertEqual(on_disk["state"], "CANCELLED")

    def test_unknown_in_flight_frame_not_silently_rerun(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"step_params": {"frames": [2, 4]}}, "p", {})
        runner.advance()  # frame 2 done
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        rec = store["operations"][op["operation_id"]]
        rec["in_flight_frame"] = 4  # crash marker between cook and save
        store_path.write_text(json.dumps(store), encoding="utf-8")
        fresh = m.OperationRunner("t")
        fresh.advance()
        on_disk = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertEqual(on_disk["state"], "RECONCILE", "a frame whose result is unknown must reconcile, not rerun")

    def test_fence_rejection_blocks_frame_side_effect_and_keeps_slot(self) -> None:
        m = self.m
        runner = m.OperationRunner("fenced-task")
        op = runner.submit({"step_params": {"frames": [2]}}, "p", {})
        calls = []
        output = FakeNode()
        output.cook = lambda force=False: calls.append(("cook", force))
        m.hou_node = lambda path: output
        m.hou_set_frame = lambda frame: calls.append(("set_frame", frame))

        @m.contextmanager
        def rejecting_fence(root, *, task_id=None, scope=None):
            raise m.BridgeCommandError("GENERATION_TAKEOVER", "lease changed before side effect")
            yield  # pragma: no cover - contextmanager shape only

        m._root_lease_fence = rejecting_fence
        runner.advance()
        record = json.loads(m._fx_operations_store_path("fenced-task").read_text())["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "RECONCILE")
        self.assertEqual(calls, [], "a rejected fence must precede both setFrame and cook")
        self.assertTrue(m._test_scheduler.snapshot()["active"], "reconciliation retains the heavy slot")


# ---------------------------------------------------------------- R3 (pure parts)
class TestR3LifecyclePureParts(OperationRunnerCase):
    def test_runner_template_has_no_implicit_warmup_and_public_api(self) -> None:
        from houdini_bridge import task_host as th
        self.assertIn("warmup={warmup!r}", th.RUNNER_TEMPLATE, "warmup must be an explicit runner argument")
        self.assertNotIn("sys.modules", th.RUNNER_TEMPLATE, "runner must use the public module surface")
        self.assertIn("task_host_serve", th.RUNNER_TEMPLATE)

    def test_launch_nonce_in_runner(self) -> None:
        from houdini_bridge import task_host as th
        self.assertIn("launch_nonce", th.RUNNER_TEMPLATE)

    def test_active_owner_refuses_second_start(self) -> None:
        from houdini_bridge import task_host as th
        ready = self.tmp_path / th.WORKDIR_READY
        ready.write_text(json.dumps({"pid": os.getpid(), "port": 8101}), encoding="utf-8")
        self.assertIs(th.active_owner_present(self.tmp_path), True)
        # dead pid -> no active owner
        ready.write_text(json.dumps({"pid": 999999, "port": 8101}), encoding="utf-8")
        self.assertIs(th.active_owner_present(self.tmp_path), False)


# ---------------------------------------------------------------- R1 cross-process
class TestCrossProcessHeavySlot(OperationRunnerCase):
    def test_foreign_process_blocks_heavy_slot_and_crash_leaves_it_blocked(self) -> None:
        """A foreign process reserving the SAME installation scheduler blocks
        submits; killing it must NOT free the slot (crash leaves a blocked
        reservation); only a control release with an observed stop reopens it."""
        m = self.m
        holder_code = (
            "import sys, time, json\n"
            "sys.path[:0] = {paths!r}\n"
            "from vfx_pipeline.graph_scheduler import GraphScheduler\n"
            "sched = GraphScheduler({root!r})\n"
            "permit = sched.reserve('foreign-process', 'op-foreign')\n"
            "print(json.dumps(permit), flush=True)\n"
            "time.sleep(30)\n"
        ).format(paths=[str(Path(__file__).resolve().parents[2] / "packages" / name / "src")
                        for name in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline")],
                 root=str(self.tmp_path / "scheduler"))
        proc = subprocess.Popen([sys.executable, "-c", holder_code], stdout=subprocess.PIPE, text=True)
        try:
            permit = json.loads(proc.stdout.readline())
            self.assertEqual(permit["generation"], 1)
            runner = m.OperationRunner("t")
            with self.assertRaises(m.BridgeCommandError) as ctx:
                runner.submit({"step_params": {"frames": [2]}}, "p", {})
            self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        finally:
            proc.kill()
            proc.wait()
        # process death alone must not free the installation slot
        with self.assertRaises(m.BridgeCommandError) as ctx:
            m.OperationRunner("t").submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        # control plane releases with the observed-stop evidence, then submit works
        self.m._test_scheduler.release("foreign-process", "op-foreign", str(permit["token"]), stopped=True)
        op = m.OperationRunner("t").submit({"step_params": {"frames": [2]}}, "p", {})
        self.assertEqual(op["record"]["state"], "QUEUED")


if __name__ == "__main__":
    unittest.main()
