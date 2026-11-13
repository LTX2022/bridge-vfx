from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import importlib.util
import os

from vfx_pipeline.production_hosts import (
    _atomic,
    _reconcile_scene_transition_records,
    _scene_epoch_transition_is_authorized,
    _scene_transition_operation_digest,
    _scene_transition_operation_store_path,
    _scene_transition_path,
    _scene_transition_snapshot,
)
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary, ProductionBoundaryError


class SceneTransitionContractTests(unittest.TestCase):
    def identities(self):
        base = {
            "task_id": "transition-task", "session_id": "session",
            "launch_nonce": "nonce", "pid": 42,
            "process_generation": "generation", "plugin_build": "a" * 64,
            "version": "21.0.631",
        }
        return {**base, "scene_epoch": 0}, {**base, "scene_epoch": 1}

    def write_store(self, control, records):
        _atomic(_scene_transition_path(control), {
            "schema": "bridge.production.scene-transitions/1.0",
            "task_id": "transition-task", "records": records,
        })

    def test_generated_load_identity_distinguishes_host_restart_at_same_epoch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            boundary = _ConfiguredBoundary.__new__(_ConfiguredBoundary)
            boundary.bound_task_id = "transition-task"
            boundary.scene_transition_path = root / "scene-transitions.json"
            params = {"path": str(root / "scene.hip"), "sha256": "a" * 64}
            before, _ = self.identities()
            first = boundary._start_scene_transition("scene.reopen_task_hip", params, before)
            retry = boundary._start_scene_transition("scene.reopen_task_hip", params, before)
            self.assertEqual(first["operation_id"], retry["operation_id"])
            restarted = {**before, "session_id": "new-session", "launch_nonce": "new-launch",
                         "pid": 43, "process_generation": "new-generation"}
            second = boundary._start_scene_transition("scene.reopen_task_hip", params, restarted)
            self.assertNotEqual(first["operation_id"], second["operation_id"])
            explicit = {**params, "operation_id": "logical-retry", "request_id": "logical-request"}
            for identity in (before, restarted):
                record = boundary._start_scene_transition("scene.reopen_task_hip", explicit, identity)
                self.assertEqual(record["operation_id"], "logical-retry")
                self.assertEqual(record["request_id"], "logical-request")

    def test_completed_load_uses_immutable_snapshot_after_source_is_saved_again(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); control = root / "control"; source = root / "scene.hip"
            source.write_bytes(b"loaded-version")
            before, after = self.identities()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            record = {
                "schema": "bridge.production.scene-transition/1.0", "status": "INTENT",
                "kind": "houdini", "task_id": "transition-task",
                "command": "scene.reopen_task_hip", "before_scene_epoch": 0,
                "before_identity": before, "request": {"path": str(source), "sha256": digest},
            }
            snapshot = _scene_transition_snapshot(control, record, task_root=root, require_source=True)
            record.update({"status": "COMPLETED", "after_scene_epoch": 1,
                           "after_identity": after, "result": snapshot})
            self.write_store(control, [record])
            source.write_bytes(b"later-save-to-the-same-path")
            self.assertTrue(_scene_epoch_transition_is_authorized(
                control, task_id="transition-task", from_epoch=0, to_epoch=1,
                task_root=root, expected_identity=before, actual_identity=after))

    def test_intent_is_recovered_only_from_the_same_source_fact(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); control = root / "control"; source = root / "scene.hip"
            source.write_bytes(b"pending-load")
            before, after = self.identities()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            record = {
                "schema": "bridge.production.scene-transition/1.0", "status": "INTENT",
                "kind": "houdini", "task_id": "transition-task",
                "command": "scene.reopen_task_hip", "before_scene_epoch": 0,
                "before_identity": before, "request": {"path": str(source), "sha256": digest},
            }
            self.write_store(control, [record])
            self.assertTrue(_scene_epoch_transition_is_authorized(
                control, task_id="transition-task", from_epoch=0, to_epoch=1,
                task_root=root, expected_identity=before, actual_identity=after))
            stored = json.loads(_scene_transition_path(control).read_text())
            self.assertEqual(stored["records"][0]["status"], "COMPLETED")
            self.assertTrue(stored["records"][0]["recovered_from_intent"])

            source.write_bytes(b"external-change-after-crash-window")
            control2 = root / "control-2"
            self.write_store(control2, [record])
            self.assertFalse(_scene_epoch_transition_is_authorized(
                control2, task_id="transition-task", from_epoch=0, to_epoch=1,
                task_root=root, expected_identity=before, actual_identity=after))

    def test_external_epoch_without_transition_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); control = root / "control"; control.mkdir()
            before, after = self.identities()
            self.assertFalse(_scene_epoch_transition_is_authorized(
                control, task_id="transition-task", from_epoch=0, to_epoch=1,
                task_root=root, expected_identity=before, actual_identity=after))

    def test_host_completed_interrupt_builds_controller_snapshot_before_authorizing(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); control = root / "control"; source = root / "scene.hip"
            source.write_bytes(b"host-completed-load")
            before, after = self.identities()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            operation_id = "scene-interrupted"
            request_id = "request-interrupted"
            request = {"path": str(source.resolve()), "sha256": digest}
            request_sha256 = hashlib.sha256(json.dumps({
                "task_id": "transition-task", "command": "scene.reopen_task_hip",
                "request": request, "request_id": request_id,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            controller_record = {
                "schema": "bridge.production.scene-transition/1.0", "status": "INTENT",
                "kind": "houdini", "task_id": "transition-task",
                "operation_id": operation_id, "request_id": request_id,
                "request_sha256": request_sha256,
                "command": "scene.reopen_task_hip", "before_scene_epoch": 0,
                "before_identity": before, "request": request,
            }
            self.write_store(control, [controller_record])
            host_snapshot = (control / "houdini-instances" / "scene-transition-snapshots"
                             / "transition-task" / (digest + ".hip"))
            host_snapshot.parent.mkdir(parents=True)
            host_snapshot.write_bytes(source.read_bytes())
            formal = {
                "schema": "bridge.houdini.scene-transition-operation/1.0",
                "state": "COMPLETED", "task_id": "transition-task",
                "operation_id": operation_id, "request_id": request_id,
                "request_sha256": request_sha256,
                "command": "scene.reopen_task_hip", "request": request,
                "before_identity": before, "before_scene_epoch": 0,
                "after_identity": after, "after_scene_epoch": 1,
                "result": {"path": str(source.resolve()), "sha256": digest,
                           "snapshot_path": str(host_snapshot), "snapshot_sha256": digest},
                "store_cas": 2, "started_at": "test", "completed_at": "test",
            }
            formal["operation_receipt_sha256"] = _scene_transition_operation_digest(formal)
            _atomic(_scene_transition_operation_store_path(control, "transition-task"), {
                "scene_transitions": {operation_id: formal},
            })

            class Client:
                def call(self, command, params):
                    self.command = command
                    self.params = params
                    return {"scene_transition": formal, "reconciled": False}

            client = Client()
            self.assertTrue(_reconcile_scene_transition_records(
                control, client, task_id="transition-task", expected_identity=before,
                actual_identity=after, task_root=root))
            stored = json.loads(_scene_transition_path(control).read_text())["records"][0]
            controller_snapshot = Path(stored["result"]["snapshot_path"])
            self.assertTrue(controller_snapshot.is_file())
            self.assertTrue(controller_snapshot.resolve().is_relative_to(
                (control / "scene-transition-snapshots" / "transition-task").resolve()))
            self.assertEqual(hashlib.sha256(controller_snapshot.read_bytes()).hexdigest(), digest)
            self.assertTrue(_scene_epoch_transition_is_authorized(
                control, task_id="transition-task", from_epoch=0, to_epoch=1,
                task_root=root, expected_identity=before, actual_identity=after))


class HostSceneTransitionCapacityTests(unittest.TestCase):
    def test_formal_load_reserves_completion_then_archived_retry_never_loads(self):
        from source_host_fixture import FakeSourceHost, ROOT
        from houdini_bridge import operation_store, render_observation_budget as budget
        spec = importlib.util.spec_from_file_location('_scene_capacity_addon', ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
        addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(addon)
        with FakeSourceHost(addon) as host:
            addon._TASK_HOST_IDENTITY = dict(addon._host_identity(), task_id='capacity-task',
                pid=os.getpid(), launch_nonce='explicit-unit-boundary',
                plugin_build=addon._FX_LOADED_ADDON_SHA256, version=host.version)
            source = host.state_path.with_suffix('.hip')
            source.write_bytes(b'explicit synthetic HIP metadata fixture')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            current_path, calls = [str(source)], []
            def load(path, **_options):
                calls.append(path)
                for callback in tuple(host.hou.hipFile.eventCallbacks()):
                    callback(host.hou.hipFileEventType.BeforeLoad)
                current_path[0] = str(path)
            runner = addon.fx_operation_runner('capacity-task')
            initial = {'task_id': 'capacity-task', 'operations': {
                str(index): {'task_id': 'capacity-task', 'request_id': str(index),
                    'state': 'COMPLETED', 'request_sha256': 'a' * 64, 'padding': 'x' * 2500}
                for index in range(2)}, 'render_observation_intents': {
                    'historical-failed-preflight': {'request_sha256': 'a' * 64,
                        'budget': {'schema': budget.FILE_BUDGET_SCHEMA, 'used_bytes': 432}}}}
            runner.path.write_text(json.dumps(initial), encoding='utf-8')
            original = runner.path.read_bytes()
            params = {'task_id': 'capacity-task', 'operation_id': 'controlled-load',
                      'request_id': 'controlled-load', 'path': str(source), 'sha256': digest}
            with patch.object(host.hou.hipFile, 'load', side_effect=load), \
                    patch.object(host.hou.hipFile, 'path', side_effect=lambda: current_path[0]), \
                    patch.object(budget, 'MAX_STORE_BYTES', 10000), patch.object(budget, 'MAX_OPERATION_BYTES', 4096):
                with self.assertRaises(addon.BridgeCommandError) as full:
                    addon.dispatch('scene.open_hip', params)
                self.assertEqual(full.exception.code, 'RENDER_OBSERVATION_BUDGET_EXCEEDED')
                self.assertEqual(calls, [])
                self.assertEqual(runner.path.read_bytes(), original)
                with runner._locked():
                    operation_store.compact_store(runner.path, 'capacity-task')
                completed = addon.dispatch('scene.open_hip', params)
                self.assertEqual(len(calls), 1)
                self.assertEqual(completed['scene_transition']['state'], 'COMPLETED')
                self.assertEqual(runner._load()['render_observation_intents'], initial['render_observation_intents'])
                with runner._locked():
                    operation_store.compact_store(runner.path, 'capacity-task')
                replay = addon.dispatch('scene.open_hip', params)
                self.assertTrue(replay['idempotent'])
                self.assertEqual(replay['scene_transition'], completed['scene_transition'])
                self.assertEqual(len(calls), 1)
                for fault in ('host', 'epoch', 'content'):
                    with self.subTest(fault=fault):
                        previous = dict(addon._TASK_HOST_IDENTITY)
                        epoch = addon._BRIDGE_SCENE_STATE.scene_epoch
                        if fault == 'host':
                            addon._TASK_HOST_IDENTITY['launch_nonce'] = 'foreign-launch'
                        elif fault == 'epoch':
                            addon._BRIDGE_SCENE_STATE.scene_epoch += 1
                        else:
                            source.write_bytes(b'external change')
                        try:
                            with self.assertRaises(addon.BridgeCommandError):
                                addon.dispatch('scene.open_hip', params)
                            self.assertEqual(len(calls), 1)
                        finally:
                            addon._TASK_HOST_IDENTITY = previous
                            addon._BRIDGE_SCENE_STATE.scene_epoch = epoch
                            source.write_bytes(b'explicit synthetic HIP metadata fixture')

    def test_multiple_transition_history_members_over_eight_mib_archive_by_family(self):
        from houdini_bridge import operation_store, render_observation_budget as budget
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'operations.json'
            family = 'scene_transitions'
            records = {str(index): {'schema': 'bridge.houdini.scene-transition-operation/1.0',
                'task_id': 'history-task', 'operation_id': str(index), 'request_id': 'request-' + str(index),
                'request_sha256': 'b' * 64, 'state': 'COMPLETED', 'padding': 'x' * (3 * 1024 * 1024)}
                for index in range(3)}
            store = {'task_id': 'history-task', family: records}
            path.write_text(json.dumps(store), encoding='utf-8')
            self.assertGreater(path.stat().st_size, budget.MAX_OPERATION_BYTES)
            report = operation_store.compact_store(path, 'history-task')
            self.assertEqual(report['archived_operations'], 3)
            compact = json.loads(budget.read_store_payload(path))
            self.assertEqual(operation_store.resolve_record(path, compact, '1', family=family), records['1'])
            forged = {'task_id': 'history-task', 'operations': {'1': compact[family]['1']}}
            with self.assertRaises(ValueError):
                operation_store.resolve_record(path, forged, '1')
            with self.assertRaises(ValueError):
                budget.validate_store(forged)


class TaskReopenLockCompositionTests(unittest.TestCase):
    def test_each_domain_rebind_commits_or_rolls_back_without_recursive_root_lock(self):
        """Finite lock composition only; registry/native metadata are explicit spies."""
        from contextlib import contextmanager, ExitStack
        from source_host_fixture import FakeSourceHost, ROOT
        spec = importlib.util.spec_from_file_location('_task_reopen_lock_addon', ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py')
        addon = importlib.util.module_from_spec(spec); spec.loader.exec_module(addon)
        with FakeSourceHost(addon) as host:
            task = 'finite-rebind-lock-task'
            addon._TASK_HOST_IDENTITY = dict(addon._host_identity(), task_id=task, pid=os.getpid(),
                launch_nonce='explicit-lock-composition', plugin_build=addon._FX_LOADED_ADDON_SHA256, version=host.version)
            root_path = addon._fx_task_paths(task, None)[0]
            root = host.hou.node('/obj').createNode('subnet', root_path.rsplit('/',1)[-1])
            root.setUserData('bridge_fx_owned', '1')
            roles = {role:root.createNode('geo', role).path() for role in ('carrier','aux')}
            addon._root_lease_issue(root_path, task, scope='sop')
            hip = host.state_path.with_suffix('.hip'); hip.write_bytes(b'explicit finite native-lock fixture')
            host.hou.hipFile.setName(str(hip))
            digest = hashlib.sha256(hip.read_bytes()).hexdigest()
            held, lock_calls, native_calls = set(), [], []
            real_locked = addon._root_lease_locked
            @contextmanager
            def checked_locked(path):
                if path in held: raise AssertionError('recursive root lease lock: '+path)
                held.add(path); lock_calls.append(path)
                try:
                    with real_locked(path): yield
                finally: held.remove(path)
            for domain, key, host_method, authority in (
                ('procedural_geometry_v1','geometry_registry_checkpoint','_fx_geometry_registry','_fx_geometry_reopen_authority'),
                ('rbd_destruction_v1','rbd_velocity_checkpoint','_fx_rbd_velocity_host','_fx_rbd_reopen_authority'),
                ('particles_v1','particle_emission_checkpoint','_fx_particle_emission_host','_fx_particle_emission_reopen_authority')):
                for fail_commit in (False, True):
                    with self.subTest(domain=domain, fail_commit=fail_commit):
                        native_calls.clear(); lock_calls.clear()
                        checkpoint = {'roles':roles}
                        pack = {'native_domain_id':domain,'nodes':[
                            {'role':role,'types':['geo']} for role in roles]}
                        manifest = {'task_id':task,'domain_pack':domain,'execution_root':root_path,
                                    'nodes':roles,key:checkpoint}
                        root = host.hou.node(root_path)
                        root.setUserData('bridge_fx_manifest_v1',json.dumps(manifest))
                        host.hou.hipFile.save(str(hip))
                        digest = hashlib.sha256(hip.read_bytes()).hexdigest()
                        contract = {'execution_root':root_path,key:checkpoint}
                        receipt = {'path':str(hip),'sha256':digest,'scene_contract':contract,
                                   'scene_contract_sha256':addon._fx_scene_contract_digest(contract)}
                        runner = addon.fx_operation_runner(task)
                        saves = addon._fx_task_saves_path(task)
                        saves.write_text(json.dumps({'saves':[receipt],'active_generation':runner.generation}))
                        operation = domain + ('-abort' if fail_commit else '-commit')
                        transition = addon._fx_scene_transition_begin({'task_id':task,'operation_id':operation,
                            'request_id':operation},'scene.reopen_task_hip',hip,digest,
                            scene_contract_sha256=receipt['scene_contract_sha256'])
                        snapshot = addon._fx_scene_transition_snapshot(task,{'path':str(hip),'sha256':digest},require_source=True)
                        host.hou.hipFile.load(snapshot['snapshot_path'],suppress_save_prompt=True)
                        transition = addon._fx_task_reopen_record_loaded(transition,snapshot,1,[])
                        host.hou.hipFile.setName(str(hip))
                        root = host.hou.node(root_path)
                        before_save, before_generation = saves.read_bytes(), runner.generation
                        before_manifest = addon._fx_snapshot_manifest_persistence(root,task)
                        before_lease = addon._root_lease_read(root_path)
                        test = self
                        class NativeRegistry:
                            def __init__(_self): _self.authority={'reopens':{}}
                            def reopen(_self, actual_roles, actual_pack, actual_checkpoint):
                                test.assertEqual(held,{root_path})
                                test.assertEqual((actual_roles,actual_pack,actual_checkpoint),(roles,pack,checkpoint))
                                test.assertTrue(getattr(addon,authority)(actual_roles,actual_pack,actual_checkpoint))
                                native_calls.append('reopen'); _self.authority['reopens']['finite-token']=True
                                return 'finite-token'
                            def end(_self, token, commit):
                                test.assertEqual(held,{root_path}); test.assertEqual(token,'finite-token')
                                native_calls.append('commit' if commit else 'abort')
                                if commit and fail_commit: raise ValueError('explicit native commit failure')
                                _self.authority['reopens'].pop(token,None)
                        native = NativeRegistry()
                        with ExitStack() as stack:
                            stack.enter_context(patch.object(addon,'_root_lease_locked',side_effect=checked_locked))
                            stack.enter_context(patch.object(addon,'_fx_pack',return_value=(domain,pack)))
                            stack.enter_context(patch.object(addon,host_method,return_value=native))
                            def finalize():
                                return addon._fx_finalize_task_reopen(task,hip,digest,receipt,snapshot,
                                    transition,warnings=[],structure_verified=0,contract_verification={})
                            if fail_commit:
                                with self.assertRaises(addon.BridgeCommandError): finalize()
                            else:
                                result = finalize()
                                test.assertTrue(result[{'procedural_geometry_v1':'geometry_registry_restored',
                                    'rbd_destruction_v1':'rbd_velocity_restored','particles_v1':'particle_emission_restored'}[domain]])
                        self.assertEqual(held,set())
                        self.assertEqual(native_calls,['reopen','commit','abort'] if fail_commit else ['reopen','commit'])
                        self.assertEqual(len(lock_calls),3 if fail_commit else 2)
                        if fail_commit:
                            self.assertEqual(saves.read_bytes(),before_save)
                            self.assertEqual(runner.generation,before_generation)
                            self.assertEqual(runner._load()['scene_transitions'][operation]['state'],'INTENT')
                            self.assertEqual(addon._fx_snapshot_manifest_persistence(root,task),before_manifest)
                            lease=addon._root_lease_read(root_path)
                            for field in ('owner_generation','owner_session_id','scene_epoch'):
                                self.assertEqual(lease[field],before_lease[field])


class ConfiguredBoundarySceneEpochTests(unittest.TestCase):
    class Transport:
        def __init__(self, identity):
            self.identity = dict(identity)

        def health(self):
            return {"task_host_identity": dict(self.identity)}

        def call(self, command, params):
            if command not in {"scene.open_hip", "scene.reopen_task_hip", "scene.reopen_owned_hip"}:
                return {}
            self.identity["scene_epoch"] += 1
            request = {"path": str(Path(params["path"]).expanduser().resolve()),
                       "sha256": str(params["sha256"]).lower()}
            request_sha256 = hashlib.sha256(json.dumps({
                "task_id": self.identity["task_id"], "command": command,
                "request": request, "request_id": params["request_id"],
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            formal = {
                "state": "COMPLETED", "task_id": self.identity["task_id"],
                "operation_id": params["operation_id"], "request_id": params["request_id"],
                "request_sha256": request_sha256, "store_cas": 2,
                "operation_receipt_sha256": "b" * 64,
            }
            return {"path": request["path"], "sha256": request["sha256"],
                    "scene_transition": formal}

    def make_client(self, root):
        identity = {
            "task_id": "owner-A", "session_id": "session", "launch_nonce": "nonce",
            "pid": 123, "process_generation": "generation", "plugin_build": "a" * 64,
            "scene_epoch": 0, "version": "21.0.631",
        }
        transport = self.Transport(identity)
        control = root / "control"
        client = _ConfiguredBoundary(kind="houdini", transport=transport, config={
            "expected_identity": identity, "evidence_source": "software_test",
            "application": "houdini", "version": "21.0.631", "plugin_build": "a" * 64,
            "transport": "http", "host": "127.0.0.1", "port": 54321,
            "task_root": str(root), "controller_root": str(control),
            "executable": "/not-started/houdini",
        }, state_dir=control / "client")
        client.bind_task("owner-A")
        source = root / "scene.hip"
        source.write_bytes(b"controlled-scene")
        return client, transport, source, hashlib.sha256(source.read_bytes()).hexdigest()

    def test_snapshot_failure_keeps_old_epoch_and_marks_failed(self):
        with tempfile.TemporaryDirectory() as raw:
            client, _transport, source, digest = self.make_client(Path(raw))

            def fail_snapshot(_record):
                raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_SNAPSHOT_INVALID")

            client._scene_transition_snapshot = fail_snapshot
            with self.assertRaises(ProductionBoundaryError):
                client.call("scene.reopen_task_hip", {"path": str(source), "sha256": digest})
            self.assertEqual(client.expected_identity["scene_epoch"], 0)
            records = json.loads(client.scene_transition_path.read_text())["records"]
            self.assertEqual(records[-1]["status"], "FAILED")
            with self.assertRaises(ProductionBoundaryError):
                client.call("scene.info", {})

    def test_completed_record_persistence_failure_keeps_old_epoch(self):
        with tempfile.TemporaryDirectory() as raw:
            client, _transport, source, digest = self.make_client(Path(raw))
            original_persist = client._persist_scene_transition

            def fail_completed(record):
                if record.get("status") == "COMPLETED":
                    raise OSError("controller store unavailable")
                return original_persist(record)

            client._persist_scene_transition = fail_completed
            with self.assertRaises(OSError):
                client.call("scene.reopen_task_hip", {"path": str(source), "sha256": digest})
            self.assertEqual(client.expected_identity["scene_epoch"], 0)
            with self.assertRaises(ProductionBoundaryError):
                client.call("scene.info", {})

    def test_completed_record_commits_epoch_and_allows_next_call(self):
        with tempfile.TemporaryDirectory() as raw:
            client, _transport, source, digest = self.make_client(Path(raw))
            client.call("scene.reopen_task_hip", {"path": str(source), "sha256": digest})
            self.assertEqual(client.expected_identity["scene_epoch"], 1)
            self.assertEqual(client.call("scene.info", {}), {})


if __name__ == "__main__":
    unittest.main()
