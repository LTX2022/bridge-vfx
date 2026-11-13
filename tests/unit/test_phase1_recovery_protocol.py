# -*- coding: utf-8 -*-
"""R03: crash-window recovery protocol with signed control authorization.

Fault windows covered:
- reserve committed but the operation record never persisted (crash between
  the reservation and the store write) -> ``reserved_without_record``;
- record reached an observed terminal state but the release never ran
  (crash between the terminal write and the release) ->
  ``terminal_without_release``;
- the durable ATTEMPT marker of an interrupted reserve -> ``uncommitted_attempt``;
- an active reservation with NO matching evidence -> ``unknown_active`` and
  explicitly NOT releasable.

Recovery goes through the public control entry only, with an HMAC-signed
control authorization; a bare non-empty verified_by string is refused.
Queries never release anything and never treat unknowns as stopped.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from test_operation_runner_recovery import OperationRunnerCase, control_auth

ADDON = Path(__file__).resolve().parents[2] / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"


class OrphanDiscoveryTests(OperationRunnerCase):
    def _reserve_only(self, request_id="op-orphan-1", task="t", with_attempt=True, bound_attempt=True):
        """Simulate a crash AFTER the scheduler reservation, BEFORE the record.

        ``with_attempt`` writes the durable ATTEMPT marker the real submit
        protocol commits before reserving (reserve->record crash window);
        without it the reservation has no evidence at all (unknown_active).
        """
        m = self.m
        runner = m.OperationRunner(task)
        if with_attempt:
            m._fx_operations_store_path(task).with_suffix(".attempt.json").write_text(
                json.dumps({"task_id": task, "request_id": request_id, "intent": "reserve"}), encoding="utf-8")
        permit = m._test_scheduler.reserve(str(runner.path), request_id)
        if with_attempt:
            marker = {
                'task_id': task, 'request_id': request_id, 'request_sha256': 'a' * 64,
                'phase': 'reserved' if bound_attempt else 'intent'}
            if bound_attempt:
                marker['slot'] = {'owner_root': str(runner.path), 'operation_id': request_id, **permit}
            runner.path.with_suffix('.attempt.json').write_text(json.dumps(marker), encoding='utf-8')
        return runner, permit

    def test_reserved_without_record_is_discovered_and_releasable(self) -> None:
        m = self.m
        runner, permit = self._reserve_only()
        report = runner.discover_orphans()
        kinds = [o["kind"] for o in report["orphans"]]
        self.assertIn("reserved_without_record", kinds)
        # queries release nothing
        self.assertEqual(m._test_scheduler.snapshot()["active"], 1)
        # unsigned / wrong-signature authorization is refused
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.release_orphan("op-orphan-1", {"verified_by": "controller/impersonated"})
        self.assertEqual(ctx.exception.code, "APPROVAL_INVALID")
        # signed authorization releases the proven orphan exactly once
        result = runner.release_orphan("op-orphan-1", control_auth("release_orphan", {"operation_id": "op-orphan-1", "task_id": "t"}))
        self.assertTrue(result["released"])
        self.assertEqual(m._test_scheduler.snapshot()["active"], 0)
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.release_orphan("op-orphan-1", control_auth("release_orphan", {"operation_id": "op-orphan-1", "task_id": "t"}))
        self.assertEqual(ctx.exception.code, "ORPHAN_GONE")

    def test_same_operation_id_cannot_release_another_task_orphan(self):
        owner, _permit = self._reserve_only(request_id='shared-request', task='task-B')
        foreign = self.m.OperationRunner('task-A')
        marker = owner.path.with_suffix('.attempt.json')
        before_marker = marker.read_bytes()
        before_slot = self.m._test_scheduler.snapshot()
        with self.assertRaises(self.m.BridgeCommandError) as denied:
            foreign.release_orphan('shared-request', control_auth('release_orphan', {
                'operation_id': 'shared-request', 'task_id': 'task-A'}))
        self.assertEqual(denied.exception.code, 'ORPHAN_NOT_RELEASABLE')
        self.assertEqual(self.m._test_scheduler.snapshot(), before_slot)
        self.assertEqual(marker.read_bytes(), before_marker)
        self.assertTrue(owner.release_orphan('shared-request', control_auth('release_orphan', {
            'operation_id': 'shared-request', 'task_id': 'task-B'}))['released'])
        self.assertFalse(self.m._test_scheduler.snapshot()['active'])
        self.assertFalse(marker.exists())

    def test_unknown_active_is_never_releasable(self) -> None:
        m = self.m
        runner, permit = self._reserve_only(request_id="op-ghost", with_attempt=False)
        report = runner.discover_orphans()
        # the reservation has no attempt marker and no record: unknown
        kinds = [o["kind"] for o in report["orphans"]]
        self.assertIn("unknown_active", kinds)
        with self.assertRaises(m.BridgeCommandError) as ctx:
            runner.release_orphan("op-ghost", control_auth("release_orphan", {"operation_id": "op-ghost", "task_id": "t"}))
        self.assertEqual(ctx.exception.code, "ORPHAN_NOT_RELEASABLE")
        self.assertEqual(m._test_scheduler.snapshot()["active"], 1, "unknown stays blocked")
        m._test_scheduler.release(str(runner.path), "op-ghost", str(permit["token"]), stopped=True)

    def test_unrelated_invalid_stores_preserved_while_proven_unstarted_orphan_recovers(self):
        for index, content in enumerate(('[]', 'null')):
            with self.subTest(content=content):
                bad = self.tmp_path / ('ops_bad_' + str(index) + '.json')
                bad.write_text(content, encoding='utf-8')
                operation_id = 'unstarted-' + str(index)
                runner, permit = self._reserve_only(request_id=operation_id, bound_attempt=index == 0)
                report = runner.discover_orphans()
                self.assertTrue(any(item['kind'] == 'corruption_blocked' and item.get('task_store') == str(bad)
                                    for item in report['orphans']))
                self.assertTrue(any(item['kind'] == 'reserved_without_record' and item.get('operation_id') == operation_id
                                    for item in report['orphans']))
                result = runner.release_orphan(operation_id, control_auth('release_orphan', {
                    'operation_id': operation_id, 'task_id': 't'}))
                self.assertTrue(result['released'])
                self.assertFalse(self.m._test_scheduler.snapshot()['active'])
                self.assertEqual(bad.read_text(encoding='utf-8'), content)
                with self.assertRaises(ValueError):
                    self.m._test_scheduler.arm(str(runner.path), operation_id, permit['token'], identity={})
                with self.assertRaises(ValueError):
                    self.m._test_scheduler.launched_fact(str(runner.path), operation_id, permit['token'])

    def test_dispatched_preflight_attempt_cannot_be_released_without_owned_stop(self):
        import os
        import threading
        from unittest.mock import patch
        from dcc_task_runtime import owned_process
        from test_render_configuration_time import built_scene, native
        with built_scene('21.0.631', native.LIGHTING, task_owned=True) as (addon, configuration):
            task_id, operation_id = 'render-configuration-time', 'preflight-still-running'
            driver = dict(zip(configuration.__code__.co_freevars,
                              (cell.cell_contents for cell in configuration.__closure__)))['driver']
            scene = addon._fx_task_saves_path(task_id).parent / 'thread-preflight.hip'
            addon.dispatch('scene.save_hip', {'task_id': task_id, 'path': str(scene)})
            addon.scene_reopen_task_hip({'task_id': task_id, 'path': str(scene)})
            identity = addon._host_identity()
            supervisor = scene.parent / 'explicit-started-process-boundary'
            supervisor.mkdir()
            (supervisor / 'receipt.key').write_bytes(os.urandom(32))
            (supervisor / 'receipt.key').chmod(0o600)
            binding = {'task_id': task_id, 'launch_nonce': identity['launch_nonce']}
            started = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': binding,
                'pid': identity['pid'], 'resource_budget': {'max_bytes': 64 * 1024 * 1024,
                    'roots': [str(scene.parent)]}}
            entered, resume = threading.Event(), threading.Event()
            original = addon._fx_render_configuration
            result = {}
            def preflight(*args, **kwargs):
                entered.set()
                if not resume.wait(8):
                    raise AssertionError('preflight event was not released')
                return original(*args, **kwargs)
            writer = addon.OperationRunner(task_id)
            def submit():
                try:
                    result['submitted'] = writer.submit_render({'request_id': operation_id, 'frames': [1],
                        'project_color': {'schema':'bridge.project-color/1.0','project_id':'software-fixture','revision':1,'colorspace':'linear','source':'human_project_selection'},
                        'budget_seconds': 30, 'render_target': driver.path(),
                        'output_pattern': str(scene.parent / 'thread.%03d.exr')})
                except BaseException as error:
                    result['error'] = error
            # Only the process-start observation is replaced; no stopped fact is supplied.
            def process_boundary(directory, event, *, identity):
                self.assertEqual(Path(directory), supervisor)
                self.assertEqual(identity, binding)
                return started if event == 'started' else None
            with patch.dict(os.environ, {'BRIDGE_OWNED_SUPERVISOR_DIR': str(supervisor),
                    'BRIDGE_OWNED_SUPERVISOR_IDENTITY': json.dumps(binding)}), \
                    patch.object(owned_process, 'read_receipt', side_effect=process_boundary), \
                    patch.object(addon, '_fx_render_configuration', side_effect=preflight):
                worker = threading.Thread(target=submit)
                worker.start()
                try:
                    self.assertTrue(entered.wait(8), result)
                    recovery = addon.OperationRunner(task_id)
                    report = recovery.discover_orphans()
                    self.assertFalse(any(item.get('operation_id') == operation_id and item['kind'] in {
                        'reserved_without_record', 'stopped_preflight_without_record'} for item in report['orphans']))
                    with self.assertRaises(addon.BridgeCommandError) as error:
                        recovery.release_orphan(operation_id, control_auth('release_orphan', {
                            'operation_id': operation_id, 'task_id': task_id}))
                    self.assertEqual(error.exception.code, 'ORPHAN_NOT_RELEASABLE')
                    self.assertTrue(addon._fx_graph_scheduler().snapshot()['active'])
                    slot = addon._fx_graph_scheduler().snapshot()
                    self.assertEqual(slot['phase'], 'DISPATCHING')
                    self.assertEqual(json.loads(slot['process_json']), {
                        'host_identity': identity, 'supervisor_binding': {
                            'directory': str(supervisor), 'identity': binding}})
                    self.assertFalse((scene.parent / 'thread.001.exr').exists())
                finally:
                    resume.set()
                    worker.join(8)
                self.assertFalse(worker.is_alive())
                self.assertNotIn('error', result)
                self.assertEqual(result['submitted']['record']['state'], 'QUEUED')
                cancelled = writer.cancel(operation_id)
                self.assertEqual(cancelled['state'], 'CANCELLED')
                self.assertFalse(addon._fx_graph_scheduler().snapshot()['active'])

    def test_corrupt_active_owner_is_not_reclassified_as_unstarted(self):
        runner, permit = self._reserve_only(request_id='unknown-corrupt-owner')
        runner.path.write_text('[]', encoding='utf-8')
        report = runner.discover_orphans()
        self.assertTrue(any(item['kind'] == 'corruption_blocked'
                            and item.get('operation_id') == 'unknown-corrupt-owner'
                            for item in report['orphans']))
        with self.assertRaises(self.m.BridgeCommandError) as error:
            runner.release_orphan('unknown-corrupt-owner', control_auth('release_orphan', {
                'operation_id': 'unknown-corrupt-owner', 'task_id': 't'}))
        self.assertEqual(error.exception.code, 'ORPHAN_NOT_RELEASABLE')
        self.assertTrue(self.m._test_scheduler.snapshot()['active'])
        self.assertEqual(runner.path.read_text(encoding='utf-8'), '[]')
        self.m._test_scheduler.release(str(runner.path), 'unknown-corrupt-owner', permit['token'], stopped=True)

    def test_terminal_without_release_is_discovered_and_releasable(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        op = runner.submit({"frames": [2]}, "p", {})
        # crash between the terminal record write and the slot release:
        # force the store terminal while the reservation is still active
        store_path = m._fx_operations_store_path("t")
        store = json.loads(store_path.read_text())
        record = store["operations"][op["operation_id"]]
        record["state"] = "COMPLETED"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        report = runner.discover_orphans()
        kinds = [o["kind"] for o in report["orphans"]]
        self.assertIn("terminal_without_release", kinds)
        self.assertEqual(m._test_scheduler.snapshot()["active"], 1)
        result = runner.release_orphan(op["operation_id"], control_auth("release_orphan", {"operation_id": op["operation_id"], "task_id": "t"}))
        self.assertTrue(result["released"])
        self.assertEqual(m._test_scheduler.snapshot()["active"], 0)

    def test_uncommitted_attempt_marker_is_reported(self) -> None:
        m = self.m
        runner = m.OperationRunner("t")
        runner.submit({"frames": [2]}, "p", {})
        # a crashed reserve left an attempt marker behind
        attempt = m._fx_operations_store_path("t").with_suffix(".attempt.json")
        attempt.write_text(json.dumps({"task_id": "t", "request_id": "op-crash", "intent": "reserve"}), encoding="utf-8")
        report = runner.discover_orphans()
        kinds = [o["kind"] for o in report["orphans"]]
        self.assertIn("uncommitted_attempt", kinds)

    def test_control_dispatch_entry_is_wired(self) -> None:
        """The REAL production dispatch handles the trusted control commands."""
        import importlib.util
        import os
        self.state_tmp = self.tmp_path / "real-addon-state"
        self._control_env_backup = {
            "HOUDINI_BRIDGE_STATE_DIR": os.environ.get("HOUDINI_BRIDGE_STATE_DIR"),
            "BRIDGE_SKILLS_SCHEDULER_ROOT": os.environ.get("BRIDGE_SKILLS_SCHEDULER_ROOT"),
        }
        os.environ["HOUDINI_BRIDGE_STATE_DIR"] = str(self.state_tmp)
        os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(self.state_tmp / "sched")
        self.addCleanup(self._restore_control_env)
        spec = importlib.util.spec_from_file_location("_real_addon_control", ADDON)
        addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(addon)
        runner = addon.fx_operation_runner("t")
        permit = addon._fx_graph_scheduler().reserve(str(runner.path), "op-dispatch")
        runner.path.with_suffix(".attempt.json").write_text(
            json.dumps({"task_id": "t", "request_id": "op-dispatch", "request_sha256": "a" * 64,
                        "phase": "reserved", "intent": "reserve", "slot": {
                            "owner_root": str(runner.path), "operation_id": "op-dispatch", **permit}}), encoding="utf-8")
        report = addon.dispatch("control.discover_orphans", {"task_id": "t"})
        self.assertIn("reserved_without_record", [o["kind"] for o in report["orphans"]])
        result = addon.dispatch("control.resolve", {
            "action": "release_orphan", "task_id": "t", "operation_id": "op-dispatch",
            "authorization": control_auth("release_orphan", {"operation_id": "op-dispatch", "task_id": "t"})})
        self.assertTrue(result["released"])
        self.assertEqual(addon._fx_graph_scheduler().snapshot()["active"], 0)

    def _restore_control_env(self):
        import os
        for key, value in self._control_env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
