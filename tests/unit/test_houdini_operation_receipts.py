"""Actual addon handlers with explicit, in-process captured HOM substitutes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))
from source_host_fixture import FakeSourceHost as SourceHost, source_params, canonical


class FakeSourceHost(SourceHost):
    def __enter__(self):
        host=super().__enter__()
        # This addon is imported before the fixture creates its separate HOM session.
        self.addon._BRIDGE_SCENE_STATE=sys.modules['_houdini_bridge_scene_identity_state']
        return host



class HoudiniOperationReceiptTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "_operation_receipt_addon", ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py")
        self.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.addon)

    def bind(self, host):
        self.addon._TASK_HOST_IDENTITY = dict(
            self.addon._host_identity(), task_id="abc123", pid=os.getpid(),
            launch_nonce="explicit-unit-boundary", plugin_build=self.addon._FX_LOADED_ADDON_SHA256,
            version=host.version)

    def params(self, operation_id, **extra):
        params = source_params()
        source = {"index": 0, "asset_id": "synthetic-ref", "role": "reference", "source_uri": "data:text/plain,fixture",
                  "sha256": hashlib.sha256(b"fixture").hexdigest(), "bytes": 7}
        params["inputs"] = [source]
        params["step_params"]["source_input_binding_sha256"] = canonical([
            {name: source[name] for name in ("asset_id", "role", "sha256")}])
        return dict(params, operation_id=operation_id, request_id=operation_id,
                    frozen_input_manifest=[source], **extra)

    def native_params(self, operation_id, **extra):
        return dict(task_id="abc123", operation_id=operation_id, request_id=operation_id,
                    frozen_input_manifest=[], **extra)

    def test_producer_captures_twice_and_after_is_inside_the_actual_root_fence(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            native_capture = self.addon._fx_producer_scene
            native_fence = self.addon._task_scene_lease_fence
            captures, fences = [], []
            active = set()

            @contextmanager
            def fence(task_id, params=None, *, required_root=None):
                self.assertEqual(required_root, root)
                fences.append(params["root_path"])
                with native_fence(task_id, params, required_root=required_root):
                    active.add(params["root_path"])
                    try:
                        yield
                    finally:
                        active.remove(params["root_path"])

            def capture(*args, **kwargs):
                captures.append(set(active))
                return native_capture(*args, **kwargs)

            with patch.object(self.addon, "_task_scene_lease_fence", fence), patch.object(
                    self.addon, "_fx_producer_scene", capture):
                result = self.addon.dispatch("node.info", self.native_params("two-captures", path=root))
            self.verify(result, "inspect")
            self.assertEqual(captures, [set(), {root}])
            self.assertEqual(fences, [root])

    def test_producer_first_root_uses_strict_requested_root_and_checks_handler_path(self):
        from houdini_bridge.operation_receipt_store import load_record
        for mismatch in (False, True):
            self.setUp()
            with self.subTest(mismatch=mismatch), FakeSourceHost(self.addon) as host:
                self.bind(host)
                root = "/obj/BRIDGE_GRAPH_" + "ce" * 32
                request = self.native_params("first-root", root_name=root.rsplit("/", 1)[-1], parent="/obj", type="geo")
                native = self.addon._dispatch_command

                def dispatch(command, params):
                    result = native(command, params)
                    return result | {"path": "/obj/foreign"} if mismatch else result

                with patch.object(self.addon, "_dispatch_command", dispatch), patch.object(
                        self.addon, "_fx_producer_scene", wraps=self.addon._fx_producer_scene) as captures:
                    if mismatch:
                        with self.assertRaises(self.addon.BridgeCommandError) as caught:
                            self.addon.dispatch("scene.create_task_root", request)
                        self.assertEqual(caught.exception.code, "SCENE_CONTRACT_SCOPE_INVALID")
                        runner = self.addon.fx_operation_runner("abc123")
                        self.assertEqual(load_record(runner.path, "abc123", "first-root")["state"], "FAILED")
                        self.assertEqual(captures.call_count, 1)
                    else:
                        result = self.addon.dispatch("scene.create_task_root", request)
                        self.verify(result, "build")
                        self.assertIsNone(result["operation_receipt"]["before_scene"]["scene_contract"])
                        self.assertEqual(result["operation_receipt"]["after_scene"]["scene_contract"]["execution_root"], root)
                        self.assertEqual(captures.call_count, 2)

    def test_producer_refuses_root_disagreement_and_after_root_drift(self):
        from houdini_bridge.operation_receipt_store import load_record
        for case in ("request", "after"):
            self.setUp()
            with self.subTest(case=case), FakeSourceHost(self.addon) as host:
                root = self.creation_root(host)
                params = self.native_params("root-drift", path=root)
                native_capture = self.addon._fx_producer_scene
                count = 0

                def capture(*args, **kwargs):
                    nonlocal count
                    count += 1
                    scene = native_capture(*args, **kwargs)
                    if count == 2:
                        scene["scene_contract"]["execution_root"] = "/obj/foreign"
                    return scene

                if case == "request":
                    params["root_path"] = "/obj/foreign"
                with patch.object(self.addon, "_fx_producer_scene", capture):
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon.dispatch("node.info", params)
                self.assertIn(caught.exception.code, {"SCENE_CONTRACT_SCOPE_INVALID", "SCENE_CONTRACT_REQUIRED"})
                runner = self.addon.fx_operation_runner("abc123")
                record = load_record(runner.path, "abc123", "root-drift")
                self.assertEqual(record["state"] if record else None, "FAILED" if case == "after" else None)

    def test_producer_takeover_between_handler_and_after_never_completes(self):
        from houdini_bridge.operation_receipt_store import load_record
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            native_dispatch = self.addon._dispatch_command
            captures = self.addon._fx_producer_scene

            def take_over(command, request):
                result = native_dispatch(command, request)
                lease = self.addon._root_lease_read(root)
                lease["owner_generation"] = "concurrent-host"
                self.addon._root_lease_write(root, lease, expect_version=lease["version"])
                return result

            with patch.object(self.addon, "_dispatch_command", take_over), patch.object(
                    self.addon, "_fx_producer_scene", wraps=captures) as observed:
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.info", self.native_params("takeover-after-handler", path=root))
            self.assertEqual(caught.exception.code, "GENERATION_TAKEOVER")
            self.assertEqual(observed.call_count, 1)
            runner = self.addon.fx_operation_runner("abc123")
            self.assertEqual(load_record(runner.path, "abc123", "takeover-after-handler")["state"], "FAILED")

    def test_producer_required_root_survives_takeover_during_fence_selection(self):
        from houdini_bridge.operation_receipt_store import load_record
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            other = self.addon._fx_task_paths("abc123")[0]
            host.hou.node("/obj").createNode("geo", other.rsplit("/", 1)[-1])
            self.addon._root_lease_issue(other, "abc123", "sop")
            other_bytes = self.addon._root_lease_path(other).read_bytes()
            native_task_fence = self.addon._task_scene_lease_fence
            native_root_fence = self.addon._root_lease_fence
            entered = []

            @contextmanager
            def observed_root_fence(path, **kwargs):
                entered.append(path)
                with native_root_fence(path, **kwargs) as lease:
                    yield lease

            with patch.object(self.addon, "_root_lease_fence", observed_root_fence):
                with native_task_fence("abc123", {"root_path": root}, required_root=root):
                    pass
            self.assertEqual(entered, sorted([other, root]))
            self.assertEqual(entered.count(root), 1)

            @contextmanager
            def take_over_before_selection(task_id, params=None, *, required_root=None):
                # Dispatch has completed its preliminary root check. The task
                # fence has not yet enumerated optional same-task candidates.
                self.assertEqual(required_root, root)
                lease = self.addon._root_lease_read(root)
                lease.update(task_id="foreign-task", owner_generation="concurrent-host")
                self.addon._root_lease_write(root, lease, expect_version=lease["version"])
                with native_task_fence(task_id, params, required_root=required_root):
                    yield

            with patch.object(self.addon, "_task_scene_lease_fence", take_over_before_selection), patch.object(
                    self.addon, "_fx_producer_scene", wraps=self.addon._fx_producer_scene) as captures:
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.info", self.native_params("selection-takeover", path=root))
            self.assertEqual(caught.exception.code, "GENERATION_TAKEOVER")
            self.assertEqual(captures.call_count, 1)
            runner = self.addon.fx_operation_runner("abc123")
            self.assertEqual(load_record(runner.path, "abc123", "selection-takeover")["state"], "FAILED")
            self.assertEqual(self.addon._root_lease_read(root)["task_id"], "foreign-task")
            self.assertEqual(self.addon._root_lease_path(other).read_bytes(), other_bytes)

    def test_producer_timing_is_opt_in_bounded_and_failure_tolerant(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(os, "write") as write:
            os.environ.pop("BRIDGE_GRAPH_STARTUP_DIAGNOSTICS", None)
            self.addon._fx_producer_checkpoint("before_start", "safe-id")
            write.assert_not_called()
            os.environ["BRIDGE_GRAPH_STARTUP_DIAGNOSTICS"] = "1"
            with patch.object(self.addon.time, "time_ns", return_value=123), patch.object(
                    self.addon.time, "monotonic_ns", return_value=456):
                self.addon._fx_producer_checkpoint("before_start", "safe-id")
            message = write.call_args.args[1].decode("ascii")
            self.assertIn(" wall_time_ns=123 monotonic_ns=456 ", message)
            self.assertIn(" operation_id=safe-id pid=", message)
            self.assertLess(len(message), 512)
            write.side_effect = OSError("stderr unavailable")
            self.addon._fx_producer_checkpoint("before_end", "safe-id")

    def test_native_producer_records_avoid_taskstore_rewrites(self):
        from dcc_task_runtime import platform_support

        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            runner = self.addon.fx_operation_runner("abc123")
            with runner._locked():
                runner._save({"task_id": "abc123", "producer_operations": {}})
            unchanged = runner.path.read_bytes()
            with patch.object(platform_support, "atomic_write", wraps=platform_support.atomic_write) as writes:
                created = self.addon.dispatch("node.create", self.native_params(
                    "storage-create", parent=root, type="attribwrangle", name="stored"))
                inspected = self.addon.dispatch("node.info", self.native_params("storage-info", path=created["path"]))
            self.assertEqual(runner.path.read_bytes(), unchanged)
            self.assertNotIn(runner.path, [call.args[0] for call in writes.call_args_list])
            self.assertEqual(len([call for call in writes.call_args_list if "producer-records" in call.args[0].parts]), 4)
            before_native = host.writes()
            queried = self.addon.dispatch('agent.fx.operation_receipt',
                {'task_id': 'abc123', 'operation_id': 'storage-info'})
            self.assertEqual(queried['operation_receipt'], inspected['operation_receipt'])
            self.assertEqual(queried['current_host_identity'], inspected['operation_receipt']['host_identity'])
            self.assertEqual(queried['current_scene'], inspected['operation_receipt']['after_scene'])
            missing = self.addon.dispatch('agent.fx.operation_receipt',
                {'task_id': 'abc123', 'operation_id': 'not-dispatched'})
            self.assertIsNone(missing['operation_receipt'])
            self.assertIsNone(missing['current_scene'])
            with self.assertRaises(self.addon.BridgeCommandError):
                self.addon.dispatch('agent.fx.operation_receipt',
                    {'task_id': 'foreign-task', 'operation_id': 'storage-info'})
            self.assertEqual(host.writes(), before_native)
            self.assertEqual(runner.path.read_bytes(), unchanged)
            for result in (created, inspected):
                self.assertEqual(json.loads(Path(result["operation_store_path"]).read_text()), result["operation_receipt"])

    def test_standalone_completed_ids_refuse_reverse_fx_and_transition_submits(self):
        from dcc_task_runtime import platform_support
        from houdini_bridge.operation_receipts import operation_receipt_sha256

        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            result = self.addon.dispatch("agent.fx.build_preview", self.params("cross-kind"))
            runner = self.addon.fx_operation_runner("abc123")
            path = Path(result["operation_store_path"])
            completed = result["operation_receipt"]
            for state in ("COMPLETED", "INTENT", "FAILED"):
                record = json.loads(json.dumps(completed))
                record["state"] = state
                record["operation_receipt_sha256"] = operation_receipt_sha256(record)
                platform_support.atomic_write(path, json.dumps(record).encode(), owned_root=runner.path.parent)
                unchanged = path.read_bytes()
                before = host.writes()
                for kind in ("fx", "transition"):
                    with self.subTest(state=state, kind=kind), self.assertRaises(self.addon.BridgeCommandError) as caught:
                        if kind == "fx":
                            runner.submit(source_params() | {"frames": [1]}, "pyro_smoke_v1", self.addon._FX_PACKS["pyro_smoke_v1"], request_id="cross-kind")
                        else:
                            self.addon._fx_scene_transition_begin({"task_id": "abc123", "operation_id": "cross-kind"},
                                "scene.reopen_owned_hip", host.state_path.with_suffix(".hip"), "a" * 64)
                    self.assertEqual(caught.exception.code, "CONTENT_CHANGED")
                self.assertEqual(host.writes(), before)
                self.assertEqual(path.read_bytes(), unchanged)
                self.assertFalse(runner.path.exists())

    def test_legacy_producer_replay_and_conflicts_preserve_legacy_bytes(self):
        from dcc_task_runtime import platform_support
        from houdini_bridge.operation_receipts import operation_receipt_sha256
        from houdini_bridge.operation_receipt_store import load_record

        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            params = self.native_params("legacy-info", path=root)
            result = self.addon.dispatch("node.info", params)
            runner = self.addon.fx_operation_runner("abc123")
            path = Path(result["operation_store_path"])
            standalone_bytes = path.read_bytes()
            receipt = result["operation_receipt"]
            with runner._locked():
                runner._save({"task_id": "abc123", "producer_operations": {"legacy-info": receipt}})
            path.unlink()
            unchanged = runner.path.read_bytes()
            replay = self.addon.dispatch("node.info", params)
            self.assertTrue(replay["idempotent"])
            self.assertEqual(replay["operation_store_format"], "legacy_task_store")
            self.assertEqual(Path(replay["operation_store_path"]), runner.path)
            self.assertEqual(runner.path.read_bytes(), unchanged)
            self.assertFalse(path.exists())
            self.addon.dispatch("node.info", self.native_params("new-after-legacy", path=root))
            self.assertEqual(runner.path.read_bytes(), unchanged)
            platform_support.atomic_write(path, standalone_bytes, owned_root=runner.path.parent)
            replay = self.addon.dispatch("node.info", params)
            self.assertEqual(replay["operation_store_format"], "producer_record")
            self.assertEqual(runner.path.read_bytes(), unchanged)
            for state in ("COMPLETED", "INTENT", "FAILED", "UNKNOWN"):
                altered = json.loads(json.dumps(receipt))
                altered["completed_at"] = "conflicting-legacy-attempt"
                altered["state"] = state
                altered["operation_receipt_sha256"] = operation_receipt_sha256(altered)
                with runner._locked():
                    runner._save({"task_id": "abc123", "producer_operations": {"legacy-info": altered}})
                legacy_bytes = runner.path.read_bytes()
                with self.subTest(state=state), self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.info", params)
                self.assertEqual(caught.exception.code, "PRODUCER_RECEIPT_INVALID")
                self.assertEqual(runner.path.read_bytes(), legacy_bytes)
                self.assertEqual(path.read_bytes(), standalone_bytes)
            path.unlink()
            for state in ("INTENT", "FAILED", "UNKNOWN"):
                altered = json.loads(json.dumps(receipt))
                altered["state"] = state
                altered["operation_receipt_sha256"] = operation_receipt_sha256(altered)
                with runner._locked():
                    runner._save({"task_id": "abc123", "producer_operations": {"legacy-info": altered}})
                legacy_bytes = runner.path.read_bytes()
                with self.subTest(legacy_only=state), self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.info", params)
                self.assertEqual(caught.exception.code, "PRODUCER_RECEIPT_INVALID" if state == "UNKNOWN" else "PRODUCER_RECONCILE_REQUIRED")
                self.assertEqual(runner.path.read_bytes(), legacy_bytes)
                with runner._locked():
                    self.assertIsNone(load_record(runner.path, "abc123", "legacy-info"))

    def test_standalone_receipt_corruption_and_old_kind_ids_refuse_before_native(self):
        from dcc_task_runtime import platform_support

        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            params = self.native_params("corrupt-info", path=root)
            result = self.addon.dispatch("node.info", params)
            runner = self.addon.fx_operation_runner("abc123")
            path = Path(result["operation_store_path"])
            valid = path.read_bytes()
            before = host.writes()
            altered = result["operation_receipt"] | {"task_id": "foreign"}
            for payload in (b"", b"{", json.dumps(altered).encode()):
                platform_support.atomic_write(path, payload, owned_root=runner.path.parent)
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.info", params)
                self.assertEqual(caught.exception.code, "PRODUCER_RECEIPT_INVALID")
                self.assertEqual(path.read_bytes(), payload)
            platform_support.atomic_write(path, valid, owned_root=runner.path.parent)
            for kind in ("operations", "scene_transitions"):
                with runner._locked():
                    runner._save({"task_id": "abc123", kind: {"new-collision": {"state": "INTENT"}}})
                unchanged = runner.path.read_bytes()
                with self.subTest(kind=kind), self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.create", self.native_params("new-collision", parent=root, type="attribwrangle", name="never_created"))
                self.assertEqual(caught.exception.code, "CONTENT_CHANGED")
                self.assertEqual(runner.path.read_bytes(), unchanged)
            self.assertEqual(host.writes(), before)

    def test_standalone_writer_failure_retains_intent_or_failed_and_never_reexecutes(self):
        from dcc_task_runtime import platform_support
        from houdini_bridge.operation_receipt_store import load_record, record_path

        for blocked_states, final_state in (({"INTENT"}, None), ({"COMPLETED"}, "FAILED"), ({"COMPLETED", "FAILED"}, "INTENT")):
            self.setUp()
            with self.subTest(blocked=sorted(blocked_states)), FakeSourceHost(self.addon) as host:
                root = self.creation_root(host)
                runner = self.addon.fx_operation_runner("abc123")
                params = self.native_params("writer-create", parent=root, type="attribwrangle", name="written_once")
                native_replace = platform_support.atomic_replace
                def refuse_state(source, target, *args, **kwargs):
                    if "producer-records" in Path(target).parts and json.loads(Path(source).read_text())["state"] in blocked_states:
                        raise OSError("explicit bottom filesystem replace failure")
                    return native_replace(source, target, *args, **kwargs)
                before = host.writes()
                with patch.object(platform_support, "atomic_replace", refuse_state):
                    with self.assertRaises(OSError):
                        self.addon.dispatch("node.create", params)
                with runner._locked():
                    record = load_record(runner.path, "abc123", "writer-create")
                if final_state is None:
                    self.assertIsNone(record)
                    self.assertEqual(host.writes(), before)
                else:
                    self.assertEqual(record["state"], final_state)
                    self.assertIsNotNone(host.hou.node(root + "/written_once"))
                    calls = host.writes()
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon.dispatch("node.create", params)
                    self.assertEqual(caught.exception.code, "PRODUCER_RECONCILE_REQUIRED")
                    self.assertEqual(host.writes(), calls)
                    self.assertEqual(len(list(record_path(runner.path, "abc123", "writer-create").parent.iterdir())), 1)

    def verify(self, result, stage):
        from houdini_bridge.operation_receipts import validate_operation_receipt
        receipt = result["operation_receipt"]
        validate_operation_receipt(receipt)
        self.assertEqual(receipt["stage"], stage)
        self.assertEqual(receipt["execution_boundary"], "software_hou_api")
        store = json.loads(Path(result["operation_store_path"]).read_text(encoding="utf-8"))
        persisted = store["producer_operations"][receipt["operation_id"]] if result.get("operation_store_format") != "producer_record" else store
        self.assertEqual(persisted, receipt)
        return receipt

    def test_actual_build_returns_typed_producer_fact(self):
        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            result = self.addon.dispatch("agent.fx.build_preview", self.params("build-1"))
            receipt = result["operation_receipt"]
            self.assertEqual(receipt["kind"], "build")
            self.assertEqual(receipt["state"], "COMPLETED")
            self.assertTrue(host.writes())
            self.assertTrue(receipt["after_scene"]["scene_contract"]["nodes"])

    def test_formal_native_command_sequence_without_fx_manifest(self):
        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            root = "/obj/BRIDGE_GRAPH_" + "ab" * 32
            created = self.addon.dispatch("scene.create_task_root", self.native_params(
                "root-1", parent="/obj", type="geo", root_name=root.rsplit("/", 1)[-1]))
            self.verify(created, "build")
            self.assertEqual(created["operation_receipt"]["facts"]["proof_scope"], "native_command")
            first = self.addon.dispatch("node.create", self.native_params(
                "create-1", parent=root, type="attribwrangle", name="source"))
            self.verify(first, "build")
            second = self.addon.dispatch("node.create_batch", self.native_params(
                "create-2", parent=root, nodes=[{"id": "target", "name": "target", "type": "attribwrangle"}]))
            self.verify(second, "build")
            target = second["nodes"]["target"]
            connected = self.addon.dispatch("node.connect", self.native_params(
                "connect-1", source=first["path"], destination=target, input_index=0, output_index=0))
            self.verify(connected, "build")
            edited = self.addon.dispatch("node.set_parms", self.native_params(
                "edit-1", path=target, parms={"snippet": "f@density = 2;"}))
            self.verify(edited, "edit")
            single = self.addon.dispatch("node.set_parm", self.native_params(
                "edit-2", path=target, name="snippet", value="f@density = 3;"))
            self.verify(single, "edit")
            self.assertEqual(host.hou.node(target).parm("snippet").eval(), "f@density = 3;")
            for command in ("node.info", "node.parms", "node.children"):
                inspected = self.addon.dispatch(command, self.native_params(command.replace(".", "-"), path=target))
                self.verify(inspected, "inspect")
            cooked = self.addon.dispatch("node.cook", self.native_params("cook-1", path=target))
            self.verify(cooked, "cook")
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "graph.hip")
                saved = self.addon.dispatch("scene.save_hip", self.native_params("save-1", path=path, root_path=root))
                receipt = self.verify(saved, "save")
                self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), receipt["facts"]["saved_scene"]["sha256"])
                self.assertEqual(Path(receipt["facts"]["saved_scene"]["snapshot_path"]).read_bytes(), Path(path).read_bytes())
                inspected = self.addon.dispatch("scene.info", self.native_params("scene-inspect", root_path=root))
                self.verify(inspected, "inspect")

    def test_idempotence_content_change_and_native_failure(self):
        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            self.addon.dispatch("agent.fx.build_preview", self.params("build-1"))
            node = host.role("source_control")
            params = self.native_params("edit-1", path=node.path(), parms={"snippet": "f@density = 2;"})
            result = self.addon.dispatch("node.set_parms", params)
            self.verify(result, "edit")
            count = len(host.writes())
            repeated = self.addon.dispatch("node.set_parms", params)
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(len(host.writes()), count)
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("node.set_parms", params | {"parms": {"snippet": "changed"}})
            self.assertEqual(caught.exception.code, "CONTENT_CHANGED")
            failed = self.native_params("bad-edit", path=node.path(), parms={"unknown_parm": 3})
            with self.assertRaises(ValueError):
                self.addon.dispatch("node.set_parms", failed)
            from houdini_bridge.operation_receipt_store import load_record
            runner = self.addon.fx_operation_runner("abc123")
            with runner._locked():
                self.assertEqual(load_record(runner.path, "abc123", "bad-edit")["state"], "FAILED")
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("node.set_parms", failed)
            self.assertEqual(caught.exception.code, "PRODUCER_RECONCILE_REQUIRED")

    def test_missing_owner_frozen_input_and_changed_bytes_refused(self):
        with FakeSourceHost(self.addon) as host:
            params = self.params("build-1")
            with self.assertRaises(self.addon.BridgeCommandError):
                self.addon.dispatch("agent.fx.build_preview", params)
            self.assertEqual(host.writes(), [])
            self.bind(host)
            del params["frozen_input_manifest"]
            with self.assertRaises(self.addon.BridgeCommandError):
                self.addon.dispatch("agent.fx.build_preview", params)
            self.assertEqual(host.writes(), [])
            params = self.params("build-2")
            params["frozen_input_manifest"][0]["source_uri"] = "data:text/plain,changed"
            with self.assertRaises(self.addon.BridgeCommandError):
                self.addon.dispatch("agent.fx.build_preview", params)
            self.assertEqual(host.writes(), [])

    def test_receipt_tampering_and_stale_scene_refused(self):
        from houdini_bridge.operation_receipts import validate_operation_receipt
        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            params = self.params("build-1")
            result = self.addon.dispatch("agent.fx.build_preview", params)
            receipt = result["operation_receipt"]
            with self.assertRaises(ValueError):
                validate_operation_receipt(receipt | {"stage": "preview"})
            host.role("source_control").parm("snippet").set("changed after completion")
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("agent.fx.build_preview", params)
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")

    def test_foreign_inspect_and_existing_save_are_not_completed(self):
        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            built = self.addon.dispatch("agent.fx.build_preview", self.params("build-1"))
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("node.info", self.native_params("foreign-info", path="/obj"))
            self.assertEqual(caught.exception.code, "SCENE_OWNERSHIP_REQUIRED")
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "old.hip"
                path.write_bytes(b"old scene bytes")
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("scene.save_hip", self.native_params("old-save", path=str(path)))
                self.assertEqual(caught.exception.code, "PRODUCER_SAVE_NOT_FRESH")
                self.assertEqual(path.read_bytes(), b"old scene bytes")
            from houdini_bridge.operation_receipt_store import load_record
            runner = self.addon.fx_operation_runner("abc123")
            with runner._locked():
                self.assertIsNone(load_record(runner.path, "abc123", "foreign-info"))
                self.assertIsNone(load_record(runner.path, "abc123", "old-save"))

    def test_graph_supervisor_boundary_is_verified_without_starting_processes(self):
        import secrets
        from dcc_task_runtime import owned_process
        with FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
            boundary = Path(directory)
            binding = {"operation_id": "graph-build", "attempt_token": "explicit-boundary-token", "generation": 1}
            (boundary / "receipt.key").write_bytes(secrets.token_bytes(32))
            observed = owned_process.process_identity(os.getpid())
            owned_process._signed_write(boundary, {"schema": owned_process.SCHEMA, "event": "started",
                "identity": binding, "pid": os.getpid(), "platform": observed["platform"],
                "process_birth": observed["birth"], "boundary": "explicit_unit_process_receipt",
                "job": {"name": "BridgeOwnedJob-explicit-unit-boundary", "assigned_at_creation": True,
                        "kill_on_close": True, "process_is_in_job": True}})
            with patch.dict(os.environ, {"BRIDGE_OWNED_SUPERVISOR_DIR": str(boundary),
                                        "BRIDGE_OWNED_SUPERVISOR_IDENTITY": json.dumps(binding)}):
                root = "/obj/BRIDGE_GRAPH_" + "cd" * 32
                result = self.addon.dispatch("scene.create_task_root", self.native_params(
                    "graph-root", root_name=root.rsplit("/", 1)[-1], parent="/obj", type="geo"))
                receipt = self.verify(result, "build")
                self.assertEqual(receipt["host_identity"]["supervisor_identity"], binding)
                self.assertEqual(receipt["host_identity"]["launch_nonce"], binding["attempt_token"])
                payload = json.loads((boundary / "started.json").read_text())
                payload["payload"]["pid"] += 1
                (boundary / "started.json").write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    self.addon.dispatch("node.children", self.native_params("tampered-start", path=root))

    def test_actual_semantic_edit_keeps_native_diff_and_invalidation(self):
        with FakeSourceHost(self.addon) as host:
            self.bind(host)
            self.addon.dispatch("agent.fx.build_preview", self.params("build-1"))
            params = self.params("candidate-1")
            params["step_params"]["changes"] = {"voxel_size": 0.08}
            result = self.addon.dispatch("agent.fx.apply_candidate", params)
            receipt = self.verify(result, "edit")
            self.assertTrue(receipt["facts"]["parameter_diff"])
            self.assertEqual(receipt["facts"]["invalidates_from"], result["invalidates_from"])

    def test_native_tuple_named_readback_uses_actual_components_in_both_versions(self):
        for version in ("21.0.631", "22.0.429"):
            with self.subTest(version=version), FakeSourceHost(self.addon, version=version) as host:
                material = host.hou.node("/mat").createNode("mtlxstandard_surface", "tuple_readback")
                self.assertIsNone(material.parm("base_color"))
                for values in ([0.2, 0.4, 0.8], [0.9, 0.1, 0.3]):
                    material.parmTuple("base_color").set(values)
                    result = self.addon.dispatch("node.parms", {"path": material.path(), "names": ["base_color", "specular_roughness"]})
                    self.assertEqual(result["parms"]["base_color"], values)
                    self.assertEqual(result["parms"]["specular_roughness"], material.parm("specular_roughness").eval())
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("node.parms", {"path": material.path(), "names": ["missing_tuple"]})
                self.assertEqual(caught.exception.code, "UNSUPPORTED_PARAMETER")

    def creation_root(self, host, suffix="ef", task_id="abc123"):
        self.bind(host)
        root = "/obj/BRIDGE_GRAPH_" + suffix * 32
        self.addon.dispatch("scene.create_task_root", {
            "task_id": task_id, "root_name": root.rsplit("/", 1)[-1], "parent": "/obj", "type": "geo"})
        return root

    def test_graph_producer_missing_launch_binding_stays_refused(self):
        with FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
            graph_identity = self.addon.graph_worker_identity()
            binding = {"operation_id": "missing-start", "attempt_token": "no-start-receipt", "generation": 1}
            for environment in ({}, {"BRIDGE_OWNED_SUPERVISOR_DIR": directory,
                                     "BRIDGE_OWNED_SUPERVISOR_IDENTITY": json.dumps(binding)}):
                with self.subTest(binding_present=bool(environment)), patch.dict(os.environ):
                    os.environ.pop("BRIDGE_OWNED_SUPERVISOR_DIR", None)
                    os.environ.pop("BRIDGE_OWNED_SUPERVISOR_IDENTITY", None)
                    os.environ.update(environment)
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon._fx_producer_identity("abc123")
                    self.assertEqual(caught.exception.code, "SUPERVISOR_REQUIRED")
                    self.assertEqual(self.addon.graph_worker_identity(), graph_identity)
                    self.assertFalse(getattr(self.addon, "_TASK_HOST_IDENTITY", None))
                    self.assertEqual(host.writes(), [])

    def owned_reopen_fixture(self, host, directory, *, manifest=False):
        path = str(Path(directory) / "owned.hip")
        self.assertFalse(Path(path).exists())
        host.hou.hipFile.setName(path)
        self.assertEqual(Path(host.hou.hipFile.path()), Path(path))
        self.assertFalse(Path(path).exists())
        if manifest:
            self.bind(host)
            self.addon.dispatch("agent.fx.build_preview", self.params("rebind-build"))
            root = self.addon._fx_manifest("abc123")[1]["execution_root"]
        else:
            root = self.creation_root(host)
            first = self.addon.dispatch("node.create", {"task_id": "abc123", "parent": root,
                "type": "attribwrangle", "name": "source"})["path"]
            second = self.addon.dispatch("node.create", {"task_id": "abc123", "parent": root,
                "type": "attribwrangle", "name": "target"})["path"]
            self.addon.dispatch("node.connect", {"task_id": "abc123", "source": first, "destination": second})
        pref = Path(directory) / "houdini-user-pref" / "21.0"
        pref.mkdir(parents=True)
        saved = self.addon.dispatch("scene.save_hip", self.native_params("rebind-save", path=path, root_path=root))
        return root, pref, {"task_id": "abc123", "path": path, "sha256": saved["sha256"], "root_path": root}

    def test_owned_reopen_rebinds_only_verified_root_with_and_without_manifest(self):
        for manifest in (False, True):
            self.setUp()
            with self.subTest(manifest=manifest), FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
                root, pref, params = self.owned_reopen_fixture(host, directory, manifest=manifest)
                other = self.creation_root(host, suffix="ad")
                untouched = self.addon._root_lease_path(other).read_bytes()
                before = self.addon._root_lease_read(root)
                with patch.dict(os.environ, {"HOUDINI_USER_PREF_DIR": str(pref)}):
                    self.addon.dispatch("scene.reopen_owned_hip", params)
                rebound = self.addon._root_lease_read(root)
                self.assertEqual(rebound["scene_epoch"], self.addon._host_identity()["scene_epoch"])
                self.assertEqual(rebound["version"], before["version"] + 1)
                self.assertEqual(rebound["owner_generation"], before["owner_generation"])
                self.assertEqual(self.addon._root_lease_path(other).read_bytes(), untouched)
                inspected = self.addon.dispatch("node.children", self.native_params("after-rebind", path=root))
                self.verify(inspected, "inspect")
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon._root_lease_check(other, task_id="abc123", renew=False)
                self.assertEqual(caught.exception.code, "SCENE_EPOCH_CHANGED")

    def test_owned_reopen_invalid_binding_and_saved_contract_refused_before_load(self):
        cases = {"missing_launch": "SUPERVISOR_REQUIRED", "other_task": "SCENE_OWNERSHIP_REQUIRED",
                 "child_path": "SCENE_OWNERSHIP_REQUIRED", "stale_epoch": "SCENE_EPOCH_CHANGED",
                 "takeover": "GENERATION_TAKEOVER", "revoked": "SCENE_OWNERSHIP_REQUIRED",
                 "missing_save": "ARTIFACT_UNREGISTERED", "bad_digest": "ARTIFACT_CONTRACT_INVALID",
                 "live_drift": "ARTIFACT_STRUCTURE_MISMATCH", "changed_file": "ARTIFACT_INVALID"}
        for case, code in cases.items():
            self.setUp()
            with self.subTest(case=case), FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
                root, pref, params = self.owned_reopen_fixture(host, directory)
                if case == "missing_launch":
                    self.addon._TASK_HOST_IDENTITY = None
                elif case == "other_task":
                    params["task_id"] = "other-task"
                    self.addon._TASK_HOST_IDENTITY["task_id"] = "other-task"
                elif case == "child_path":
                    params["root_path"] += "/source"
                elif case == "stale_epoch":
                    self.addon._bridge_scene_event(host.hou.hipFileEventType.BeforeLoad)
                elif case in {"takeover", "revoked"}:
                    lease = self.addon._root_lease_read(root)
                    lease["owner_generation" if case == "takeover" else "status"] = "foreign" if case == "takeover" else "REVOKED"
                    self.addon._root_lease_write(root, lease, expect_version=lease["version"])
                elif case in {"missing_save", "bad_digest"}:
                    saves_path = self.addon._fx_task_saves_path("abc123")
                    store = json.loads(saves_path.read_text())
                    if case == "missing_save":
                        store["saves"] = []
                    else:
                        store["saves"][-1]["scene_contract_sha256"] = "0" * 64
                    saves_path.write_text(json.dumps(store), encoding="utf-8")
                elif case == "live_drift":
                    host.hou.node(root + "/source").parm("snippet").set("changed before load")
                elif case == "changed_file":
                    Path(params["path"]).write_bytes(b"replaced HIP")
                untouched = self.addon._root_lease_path(root).read_bytes()
                with patch.dict(os.environ, {"HOUDINI_USER_PREF_DIR": str(pref)}), patch.object(host.hou.hipFile, "load", wraps=host.hou.hipFile.load) as load:
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon.dispatch("scene.reopen_owned_hip", params)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(load.call_count, 0)
                self.assertEqual(self.addon._root_lease_path(root).read_bytes(), untouched)

    def test_owned_reopen_loaded_native_drift_never_rebinds(self):
        cases = {"parameter": "ARTIFACT_STRUCTURE_MISMATCH", "connection": "ARTIFACT_STRUCTURE_MISMATCH",
                 "extra_node": "ARTIFACT_STRUCTURE_MISMATCH", "missing_node": "ARTIFACT_STRUCTURE_MISMATCH",
                 "host": "SCENE_STATE_DRIFT", "callback": "SCENE_STATE_DRIFT",
                 "file": "SCENE_STATE_DRIFT", "epoch": "SCENE_STATE_DRIFT"}
        for case, code in cases.items():
            self.setUp()
            with self.subTest(case=case), FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
                root, pref, params = self.owned_reopen_fixture(host, directory)
                untouched = self.addon._root_lease_path(root).read_bytes()
                native_load = host.hou.hipFile.load
                def drift_after_load(*args, **kwargs):
                    native_load(*args, **kwargs)
                    if case == "parameter":
                        host.hou.node(root + "/source").parm("snippet").set("changed after load")
                    elif case == "connection":
                        host.hou.node(root + "/target").setInput(0, None)
                    elif case == "extra_node":
                        host.hou.node(root).createNode("attribwrangle", "unsaved")
                    elif case == "missing_node":
                        host.hou.node(root + "/source").destroy()
                    elif case == "host":
                        self.addon._TASK_HOST_IDENTITY["process_generation"] = "foreign-host"
                    elif case == "callback":
                        host.hou.hipFile.eventCallbacks().remove(self.addon._bridge_scene_event)
                    elif case == "file":
                        Path(params["path"]).write_bytes(b"replaced during load")
                    elif case == "epoch":
                        self.addon._bridge_scene_event(host.hou.hipFileEventType.BeforeLoad)
                with patch.dict(os.environ, {"HOUDINI_USER_PREF_DIR": str(pref)}), patch.object(host.hou.hipFile, "load", drift_after_load):
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon.dispatch("scene.reopen_owned_hip", params)
                    self.assertEqual(caught.exception.code, code)
                self.assertEqual(self.addon._root_lease_path(root).read_bytes(), untouched)

    def test_owned_reopen_cas_preserves_takeover_after_verified_load(self):
        from dcc_task_runtime import platform_support

        with FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
            root, pref, params = self.owned_reopen_fixture(host, directory)
            before = self.addon._root_lease_read(root)
            armed = {"takeover": False}
            native_load = host.hou.hipFile.load
            native_unlock = platform_support.unlock_file
            def load_then_arm(*args, **kwargs):
                native_load(*args, **kwargs)
                armed["takeover"] = True
            def unlock_then_takeover(descriptor):
                native_unlock(descriptor)
                if armed["takeover"]:
                    armed["takeover"] = False
                    lease = self.addon._root_lease_read(root)
                    lease["owner_generation"] = "concurrent-host-generation"
                    self.addon._root_lease_write(root, lease, expect_version=lease["version"])
            with patch.dict(os.environ, {"HOUDINI_USER_PREF_DIR": str(pref)}), patch.object(host.hou.hipFile, "load", load_then_arm), patch.object(platform_support, "unlock_file", unlock_then_takeover):
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    self.addon.dispatch("scene.reopen_owned_hip", params)
                self.assertEqual(caught.exception.code, "LEASE_CAS_CONFLICT")
            actual = self.addon._root_lease_read(root)
            self.assertEqual(actual["owner_generation"], "concurrent-host-generation")
            self.assertEqual(actual["version"], before["version"] + 1)
            self.assertEqual(actual["scene_epoch"], before["scene_epoch"])

    def test_h01_batch_foreign_input_rejected_before_native_mutation(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            foreign = self.creation_root(host, suffix="ac", task_id="other-task")
            source = self.addon.dispatch("node.create", {"task_id": "other-task", "parent": foreign,
                                                       "type": "attribwrangle", "name": "foreign_source"})["path"]
            writes = len(host.writes())
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("node.create_batch", self.native_params(
                    "h01-foreign", parent=root, nodes=[{"id": "target", "type": "attribwrangle",
                                                        "inputs": [source]}]))
            self.assertEqual(caught.exception.code, "SCENE_OWNERSHIP_REQUIRED")
            self.assertEqual(len(host.writes()), writes)
            self.assertIsNone(host.hou.node(root + "/target"))

    def test_h01_batch_ids_and_same_root_external_path_remain_supported(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            source = self.addon.dispatch("node.create", self.native_params(
                "h01-source", parent=root, type="attribwrangle", name="existing"))["path"]
            result = self.addon.dispatch("node.create_batch", self.native_params(
                "h01-normal", parent=root, nodes=[
                    {"id": "target", "type": "attribwrangle", "inputs": ["later", None, source]},
                    {"id": "later", "name": "late_source", "type": "attribwrangle"}]))
            self.verify(result, "build")
            wires = host.hou.node(result["nodes"]["target"]).inputConnections()
            self.assertEqual({wire.inputIndex(): wire.inputNode().path() for wire in wires},
                             {0: result["nodes"]["later"], 2: source})

    def test_h02_single_create_same_root_inputs_are_node_paths(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            source = self.addon.dispatch("node.create", self.native_params(
                "h02-source", parent=root, type="attribwrangle", name="existing"))["path"]
            result = self.addon.dispatch("node.create", self.native_params(
                "h02-normal", parent=root, type="attribwrangle", name="wired", inputs=[source]))
            self.verify(result, "build")
            self.assertEqual(host.hou.node(result["path"]).inputs()[0].path(), source)

    def test_h02_single_create_foreign_input_refused_before_native_mutation(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            foreign = self.creation_root(host, suffix="ac", task_id="other-task")
            source = self.addon.dispatch("node.create", {"task_id": "other-task", "parent": foreign,
                                                       "type": "attribwrangle", "name": "foreign_source"})["path"]
            writes = len(host.writes())
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("node.create", self.native_params(
                    "h02-foreign", parent=root, type="attribwrangle", name="wired", inputs=[source]))
            self.assertEqual(caught.exception.code, "SCENE_OWNERSHIP_REQUIRED")
            self.assertEqual(len(host.writes()), writes)
            self.assertIsNone(host.hou.node(root + "/wired"))

    def test_creation_invalid_batch_ids_and_unresolved_paths_have_no_native_side_effects(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            cases = [
                [{"id": "first", "type": "attribwrangle"}, {"id": "second", "type": "attribwrangle", "inputs": ["unknown_id"]}],
                [{"id": "first", "type": "attribwrangle"}, {"id": "second", "type": "attribwrangle", "inputs": [root + "/missing"]}],
                [{"id": "duplicate", "type": "attribwrangle"}, {"id": "duplicate", "type": "attribwrangle"}],
                [{"type": "attribwrangle"}],
            ]
            for index, nodes in enumerate(cases):
                with self.subTest(index=index):
                    writes = len(host.writes())
                    expected_error = ValueError if index == 1 else self.addon.BridgeCommandError
                    with self.assertRaises(expected_error):
                        self.addon.dispatch("node.create_batch", self.native_params(
                            "invalid-batch-" + str(index), parent=root, nodes=nodes))
                    self.assertEqual(len(host.writes()), writes)
            self.assertEqual(host.hou.node(root).children(), ())

    def test_creation_legacy_paths_names_and_forward_batch_ids_still_execute(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            source = self.addon.dispatch("node.create", {
                "task_id": "abc123", "parent": root, "name": "source", "type": "attribwrangle"})["path"]
            single = self.addon.dispatch("node.create", {
                "task_id": "abc123", "parent": root, "name": "single", "type": "attribwrangle", "inputs": [None, source]})
            self.assertNotIn("operation_receipt", single)
            self.assertEqual(host.hou.node(single["path"]).inputs()[1].path(), source)
            batch = self.addon.dispatch("node.create_batch", {"task_id": "abc123", "parent": root, "nodes": [
                {"name": "target", "type": "attribwrangle", "inputs": ["later", source]},
                {"name": "later", "type": "attribwrangle"}]})
            self.assertNotIn("operation_receipt", batch)
            self.assertEqual([node.path() for node in host.hou.node(batch["nodes"]["target"]).inputs()],
                             [batch["nodes"]["later"], source])

    def test_creation_same_task_other_root_is_outside_declared_scope(self):
        with FakeSourceHost(self.addon) as host:
            root = self.creation_root(host)
            other_root = self.creation_root(host, suffix="ac")
            source = self.addon.dispatch("node.create", {"task_id": "abc123", "parent": other_root,
                                                       "type": "attribwrangle", "name": "other_source"})["path"]
            for command in ("node.create", "node.create_batch"):
                with self.subTest(command=command):
                    params = self.native_params(command.replace(".", "-"), parent=root)
                    if command == "node.create":
                        params.update(type="attribwrangle", name="wired", inputs=[source])
                    else:
                        params["nodes"] = [{"id": "wired", "type": "attribwrangle", "inputs": [source]}]
                    writes = len(host.writes())
                    with self.assertRaises(self.addon.BridgeCommandError) as caught:
                        self.addon.dispatch(command, params)
                    self.assertEqual(caught.exception.code, "SCENE_OWNERSHIP_REQUIRED")
                    self.assertEqual(len(host.writes()), writes)

    def test_creation_node_inputs_keep_real_frozen_file_validation(self):
        with FakeSourceHost(self.addon) as host, tempfile.TemporaryDirectory() as directory:
            root = self.creation_root(host)
            source = self.addon.dispatch("node.create", self.native_params(
                "file-source", parent=root, name="source", type="attribwrangle"))["path"]
            path = Path(directory) / "source.dat"
            path.write_bytes(b"frozen bytes")
            params = self.native_params("file-normal", parent=root, name="wired", type="attribwrangle", inputs=[source])
            params["frozen_input_manifest"] = [{"index": 0, "source_uri": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}]
            result = self.addon.dispatch("node.create", params)
            self.verify(result, "build")
            path.write_bytes(b"changed bytes")
            writes = len(host.writes())
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch("node.create", params | {"operation_id": "file-changed", "request_id": "file-changed", "name": "rejected"})
            self.assertEqual(caught.exception.code, "SCENE_STATE_DRIFT")
            self.assertEqual(len(host.writes()), writes)


if __name__ == "__main__":
    unittest.main()
