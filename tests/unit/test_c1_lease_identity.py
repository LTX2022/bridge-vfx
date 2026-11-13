# -*- coding: utf-8 -*-
"""C1 frozen entry-level acceptance: lease and recovery share one identity.

- REAL ``scene_reopen_task_hip`` (fake HOM only) transfers the task's leases
  to the new host PROCESS generation; the new host's next mutation through the
  real dispatch succeeds, the old host's next mutation is refused.
- Lease renewal is a CAS against the owner+version it verified: a stale
  writer loses (LEASE_CAS_CONFLICT → GENERATION_TAKEOVER) instead of undoing
  a completed takeover.
- ``resolve_reconcile`` requeue is a recoverable transaction: intent phase
  first, then rotation; a crash between reserve and record-commit is
  discovered (record slot mismatch + phase file) and recovered by the signed
  control action ``adopt_requeue`` — no new side effect, nothing released.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"

GRAPH_ROOT = "BRIDGE_GRAPH_" + "3c" * 32


def _load_addon(name="_c1_addon"):
    spec = importlib.util.spec_from_file_location(name, ADDON_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Parm:
    def __init__(self, name):
        self._name = name
        self.value = 0.0

    def name(self):
        return self._name

    def eval(self):
        return self.value

    def set(self, value):
        self.value = value


class _Node:
    def __init__(self, path):
        self._path = path
        self.parms_dict = {"scale": _Parm("scale")}
        self._data = {}
        self._inputs = []
        self._children = []

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def userData(self, key):
        return self._data.get(key)

    def setUserData(self, key, value):
        self._data[key] = value

    def type(self):
        import types
        return types.SimpleNamespace(nameWithCategory=lambda: "Sop/null")

    def cook(self, force=False):
        self.cooked = True

    def errors(self):
        return []

    def warnings(self):
        return []

    def geometry(self):
        import types
        return types.SimpleNamespace(
            boundingBox=lambda: types.SimpleNamespace(sizevec=lambda: (1.0, 1.0, 1.0)),
            points=lambda: [], prims=lambda: [], pointAttribs=lambda: [])

    def parms(self):
        return list(self.parms_dict.values())

    def parm(self, name):
        return self.parms_dict.get(name)

    def inputs(self):
        return list(self._inputs)

    def isLockedHDA(self):
        return False

    def isDelayedDefinition(self):
        return False

    def allSubChildren(self, top_down=True, recurse_in_locked_nodes=True, sync_delayed_definition=False):
        result = []
        for child in self._children:
            if top_down:
                result.append(child)
            result.extend(child.allSubChildren(top_down, recurse_in_locked_nodes, sync_delayed_definition))
            if not top_down:
                result.append(child)
        return result


class C1LeaseIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="c1-lease-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.state_dir = self.tmp / "state"
        self._env_backup = {k: os.environ.get(k) for k in
                            ("HOUDINI_BRIDGE_STATE_DIR", "BRIDGE_SKILLS_SCHEDULER_ROOT",
                             "HOUDINI_BRIDGE_APPROVAL_SECRET")}
        os.environ["HOUDINI_BRIDGE_STATE_DIR"] = str(self.state_dir)
        os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(self.state_dir / "sched")
        os.environ["HOUDINI_BRIDGE_APPROVAL_SECRET"] = "unit-test-control-secret-0123456789abcdef"
        self.addCleanup(self._restore_env)
        from test_operation_runner_recovery import control_auth  # signed helper
        self.control_auth = control_auth
        self.addon = _load_addon("_c1_addon_main")
        self.task_id = "c1-task"
        digest = hashlib.sha256(self.task_id.encode()).hexdigest()[:16]
        self.fx_root = "/obj/BRIDGE_FX_" + digest
        self.nodes = {"/obj": _Node("/obj"), "/obj/node": _Node("/obj/node"),
                      self.fx_root: _Node(self.fx_root)}
        self._hip_path = str(self.tmp / "c1.hip")
        fake_hou = types.SimpleNamespace(
            node=lambda p: self.nodes.get(p),
            undos=None,
            isUIAvailable=lambda: False,
            hipFile=types.SimpleNamespace(
                path=lambda: self._hip_path,
                setName=lambda path: setattr(self, "_hip_path", str(path)),
                load=lambda *a, **k: None,
                hasUnsavedChanges=lambda: False),
            setFrame=lambda f: None,
            time=lambda: 0.0,
        )
        self._previous_hou = sys.modules.get("hou")
        sys.modules["hou"] = fake_hou
        self.addCleanup(self._restore_hou)

    def _restore_env(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _restore_hou(self):
        if self._previous_hou is None:
            sys.modules.pop("hou", None)
        else:
            sys.modules["hou"] = self._previous_hou

    def _issue_and_reopen(self):
        """Issue a lease as the OLD host, then run the REAL reopen transfer."""
        old_identity = self.addon._host_identity()
        self.addon._root_lease_issue("/obj/node", self.task_id, scope="sop")
        self.addon._root_lease_issue(self.fx_root, self.task_id, scope="sop")
        # the NEW host has a different process generation/session: rotate the
        # module's scene identity before running the reopen (as a restart would)
        new_identity = {"session_id": "session-new-host", "process_generation": "gen-new-host-99",
                        "scene_epoch": 1}
        self.addon._BRIDGE_SCENE_STATE = types.SimpleNamespace(**new_identity)
        hip = self.tmp / "c1.hip"
        hip.write_bytes(b"task hip bytes")
        saves_path = self.addon._fx_task_saves_path(self.task_id)
        saves_path.parent.mkdir(parents=True, exist_ok=True)
        saves_path.write_text(json.dumps({"saves": [{"path": str(hip), "sha256": hashlib.sha256(hip.read_bytes()).hexdigest(),
                                                     "structure": {"/obj/node": "Sop/null"},
                                                     "saved_at": "2026-09-20T00:00:00+00:00",
                                                     "process_generation": old_identity["process_generation"]}]}), encoding="utf-8")
        result = self.addon.dispatch("scene.reopen_task_hip",
                                     {"task_id": self.task_id, "path": str(hip), "sha256": hashlib.sha256(hip.read_bytes()).hexdigest()})
        return old_identity, result

    def test_reopen_transfers_host_generation_and_old_host_is_stopped(self) -> None:
        old_identity, result = self._issue_and_reopen()
        lease = self.addon._root_lease_read("/obj/node")
        # owner_generation is the HOST process generation (one namespace)
        self.assertEqual(lease["owner_generation"], "gen-new-host-99")
        self.assertEqual(lease["owner_generation"], self.addon._host_identity()["process_generation"])
        self.assertNotEqual(lease["owner_generation"], old_identity["process_generation"])
        self.assertEqual(sorted(result.get("leases_transferred")), sorted(["/obj/node", self.fx_root]))
        # NEW host succeeds through the real dispatch
        ok = self.addon.dispatch("node.set_parms", {"path": "/obj/node", "parms": {"scale": 3.0}, "task_id": self.task_id})
        self.assertEqual(ok["values"]["scale"], 3.0)
        # OLD host's next write is refused
        self.addon._BRIDGE_SCENE_STATE = None
        old_module = _load_addon("_c1_addon_old")
        old_module._BRIDGE_SCENE_STATE = types.SimpleNamespace(
            session_id=old_identity["session_id"] + "-old",
            process_generation=old_identity["process_generation"],
            scene_epoch=0)
        with self.assertRaises(old_module.BridgeCommandError) as ctx:
            old_module.dispatch("node.set_parms", {"path": "/obj/node", "parms": {"scale": 1.0}, "task_id": self.task_id})
        self.assertEqual(ctx.exception.code, "GENERATION_TAKEOVER")

    def test_stale_renewal_cannot_undo_takeover(self) -> None:
        self.addon._root_lease_issue("/obj/node", self.task_id, scope="sop")
        seen = self.addon._root_lease_read("/obj/node")
        # a takeover bumps the version while the old writer still holds `seen`
        takeover = dict(seen)
        takeover["owner_generation"] = "generation-of-new-host"
        takeover["renewed_at"] = "2026-09-20T00:00:00+00:00"
        self.addon._root_lease_write("/obj/node", takeover, expect_version=int(seen["version"]))
        # the stale writer's CAS renewal must lose, not overwrite
        stale = dict(seen)
        stale["renewed_at"] = "2026-09-20T00:00:01+00:00"
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon._root_lease_write("/obj/node", stale, expect_version=int(seen["version"]))
        self.assertEqual(ctx.exception.code, "LEASE_CAS_CONFLICT")
        final = self.addon._root_lease_read("/obj/node")
        self.assertEqual(final["owner_generation"], "generation-of-new-host",
                         "the takeover must survive a stale renewal")

    def test_saved_task_contract_detects_parameter_and_connection_drift(self) -> None:
        source_path = self.fx_root + "/source"
        sink_path = self.fx_root + "/sink"
        source, sink = _Node(source_path), _Node(sink_path)
        sink._inputs = [source]
        self.nodes.update({source_path: source, sink_path: sink})
        self.nodes[self.fx_root]._children.extend([source, sink])
        graph_hash = "ab" * 32
        self.addon._fx_write_state(self.task_id, {
            "task_id": self.task_id, "execution_root": self.fx_root,
            "graph_hash": graph_hash,
            "nodes": {"source": source_path, "sink": sink_path},
        })
        contract = {
            "schema": "houdini.task_scene_contract/1.0", "task_id": self.task_id,
            "execution_root": self.fx_root, "graph_hash": graph_hash,
            "nodes": [
                {"role": "source", "path": source_path, "type": "Sop/null",
                 "parameters": {"scale": 0.0}, "inputs": []},
                {"role": "sink", "path": sink_path, "type": "Sop/null",
                 "parameters": {"scale": 0.0}, "inputs": [source_path]},
            ],
        }
        verified = self.addon._fx_verify_scene_contract(contract, self.task_id)
        self.assertTrue(verified["nodes_verified"])
        self.assertTrue(verified["parameters_verified"])
        self.assertTrue(verified["connections_verified"])
        sink.parm("scale").set(3.0)
        with self.assertRaises(self.addon.BridgeCommandError) as parameter_error:
            self.addon._fx_verify_scene_contract(contract, self.task_id)
        self.assertEqual(parameter_error.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")
        sink.parm("scale").set(0.0)
        sink._inputs = []
        with self.assertRaises(self.addon.BridgeCommandError) as connection_error:
            self.addon._fx_verify_scene_contract(contract, self.task_id)
        self.assertEqual(connection_error.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")

    def test_saved_contract_preserves_unevaluated_native_driver_and_detects_drift(self) -> None:
        path = self.fx_root + "/driven"
        node = _Node(path)
        parm = node.parm("scale")
        parm.expression = lambda: "$F * 2"
        parm.expressionLanguage = lambda: "hou.exprLanguage.Hscript"
        parm.keyframes = lambda: ()
        def unevaluated():
            raise RuntimeError("software boundary cannot evaluate native expression")
        parm.eval = unevaluated
        self.nodes[path] = node
        self.nodes[self.fx_root]._children.append(node)
        self.addon._fx_write_state(self.task_id, {
            "task_id": self.task_id, "execution_root": self.fx_root,
            "graph_hash": "ef" * 32, "nodes": {"source": path},
        })
        contract = self.addon._fx_capture_scene_contract(self.task_id)
        self.assertEqual(contract["schema"], "houdini.task_scene_contract/2.0")
        saved = contract["nodes"][0]
        self.assertEqual(saved["parameters"], {})
        self.assertFalse(saved["parameter_channels"]["scale"]["evaluated_available"])
        self.assertEqual(saved["parameter_channels"]["scale"]["expression"], "$F * 2")
        self.assertTrue(self.addon._fx_verify_scene_contract(contract, self.task_id)["parameters_verified"])
        parm.expression = lambda: "$F * 3"
        with self.assertRaises(self.addon.BridgeCommandError) as error:
            self.addon._fx_verify_scene_contract(contract, self.task_id)
        self.assertEqual(error.exception.code, "ARTIFACT_STRUCTURE_MISMATCH")
        # Missing native defaults have no serialized driver and remain errors.
        del parm.expression
        with self.assertRaises(self.addon.BridgeCommandError) as missing:
            self.addon._fx_capture_scene_contract(self.task_id)
        self.assertEqual(missing.exception.code, "SCENE_CONTRACT_READBACK_FAILED")

    def test_requeue_crash_window_is_discovered_and_adopted(self) -> None:
        from vfx_pipeline.graph_scheduler import GraphScheduler
        scheduler = GraphScheduler(self.state_dir / "sched")
        self.addon._FX_GRAPH_SCHEDULER = scheduler
        # a prior build produced the task manifest frame operations verify
        self.addon._fx_write_state(self.task_id, {
            "domain_pack": "pyro_smoke_v1", "build_state": "BUILT_VERIFIED",
            "execution_root": self.fx_root, "nodes": {"source": "/obj/node", "output": "/obj/node"},
            "input_digest": "c1-fixed-input"})
        runner = self.addon.fx_operation_runner(self.task_id)
        # build a RECONCILE record bound to slot generation 1
        op = runner.submit({"step_params": {"domain_pack": "pyro_smoke_v1", "frames": [2, 4]}}, "pyro_smoke_v1", {})
        store_path = self.addon._fx_operations_store_path(self.task_id)
        store = json.loads(store_path.read_text())
        record = store["operations"][op["operation_id"]]
        record["state"] = "RECONCILE"
        record["claimed_by_generation"] = "dead-generation"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        slot_v1 = dict(record["slot"])
        scheduler.release(slot_v1["owner_root"], slot_v1["operation_id"], slot_v1["token"], stopped=True)
        # control decides requeue; the fresh reserve commits, then the record
        # save crashes (simulate via a store write failure)
        original_save = runner._save
        def crashing_save(store_payload):
            raise RuntimeError("injected crash between reserve and record commit")
        runner._save = crashing_save
        reconcile_evidence = {
            "kind": "confirmed_not_started",
            "task_id": self.task_id,
            "request_id": op["operation_id"],
            "slot_generation": int(slot_v1["generation"]),
            "slot_token": str(slot_v1["token"]),
            "observed_at": "2026-09-27T00:00:00+00:00",
            "source": "unit-test-control-observation",
            "confirmed": True,
            "side_effect_started": False,
        }
        authorization = self.control_auth(
            "resolve_reconcile",
            {"task_id": self.task_id, "request_id": op["operation_id"],
             "decision": "requeue", "evidence": reconcile_evidence})
        with self.assertRaises(RuntimeError):
            runner.resolve_reconcile(op["operation_id"], "requeue",
                                     authorization, evidence=reconcile_evidence)
        runner._save = original_save
        # disk: record still RECONCILE with the OLD slot generation; a NEW
        # active reservation (generation+1) exists with no committed record
        store = json.loads(store_path.read_text())
        record = store["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "RECONCILE")
        self.assertNotEqual(int(record["slot"]["generation"]), int(scheduler.snapshot()["generation"]))
        report = runner.discover_orphans()
        kinds = [o["kind"] for o in report["orphans"]]
        self.assertIn("requeue_interrupted", kinds, "the mismatch must be discovered, not invisible")
        # plain submit still blocked (the slot is active); unknown stays held
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            runner.submit({"step_params": {"domain_pack": "pyro_smoke_v1", "frames": [2]}}, "pyro_smoke_v1", {})
        self.assertEqual(ctx.exception.code, "HEAVY_SLOT_BUSY")
        # signed control adoption binds the record to the ACTIVE slot
        adopted = runner.adopt_requeue(op["operation_id"],
                                       self.control_auth("adopt_requeue", {"operation_id": op["operation_id"], "task_id": self.task_id}))
        self.assertTrue(adopted["adopted"])
        record = json.loads(store_path.read_text())["operations"][op["operation_id"]]
        self.assertEqual(record["state"], "QUEUED")
        self.assertEqual(int(record["slot"]["generation"]), int(scheduler.snapshot()["generation"]))
        self.assertFalse((store_path.with_suffix(".requeue-phase.json")).exists())
        # recovery continued the SAME operation: submitting the same request is
        # idempotent (no second execution) and the operation then completes
        again = runner.submit({"step_params": {"domain_pack": "pyro_smoke_v1", "frames": [2, 4]}}, "pyro_smoke_v1", {})
        self.assertTrue(again["idempotent"])
        # the fx build chain issues the task-root lease before execution
        self.addon._root_lease_issue(self.fx_root, self.task_id, scope="sop")
        for _ in range(4):
            runner.advance()
            record = json.loads(store_path.read_text())["operations"][op["operation_id"]]
            if record["state"] in ("COMPLETED", "FAILED", "BUDGET_REACHED", "RECONCILE"):
                break
        self.assertEqual(record["state"], "COMPLETED")
        self.assertEqual(scheduler.snapshot()["active"], 0)

    def test_preserved_rules_still_hold(self) -> None:
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.create", {"parent": "/obj", "type": "geo", "name": "x"})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")
        self.addon._root_lease_issue("/obj/node", "task-a", scope="sop")
        with self.assertRaises(self.addon.BridgeCommandError) as ctx:
            self.addon.dispatch("node.set_parms", {"path": "/obj/node", "parms": {"scale": 1.0}, "task_id": "task-b"})
        self.assertEqual(ctx.exception.code, "SCENE_OWNERSHIP_REQUIRED")


if __name__ == "__main__":
    unittest.main()
