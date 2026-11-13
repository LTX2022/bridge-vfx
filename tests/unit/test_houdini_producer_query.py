"""Actual dispatch/validator/store with in-process HOM and filesystem boundaries only.

No subprocess, DCC, sampling, signed launch fixture or key is created.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
sys.path.insert(0, str(ROOT / 'tools'))
from source_host_fixture import FakeSourceHost
from houdini_bridge.operation_receipts import (
    SCHEMA, QUERY_SCHEMA, CHILDREN_INSPECT_POLICY, QUERY_MAX_CHILDREN,
    canonical_sha256, operation_receipt_sha256, validate_operation_receipt,
)
from houdini_bridge.operation_receipt_store import load_record
from vfx_pipeline.graph_job_worker import GraphJobWorker, _verify_native_dispatch_receipt
from vfx_pipeline.scene_lease import SceneLeaseStore
from dcc_task_runtime import platform_support
import readiness_evidence as evidence


class ProducerQueryTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        spec = importlib.util.spec_from_file_location('_producer_query_addon', source)
        self.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.addon)
        # macOS /var is a symlink; use the canonical temp root without weakening path guards.
        self.enterContext(patch.object(tempfile, 'tempdir', str(Path(tempfile.gettempdir()).resolve())))
        self.host = self.enterContext(FakeSourceHost(self.addon))
        self.task, self.nonce, self.graph_hash = 'abc123', 'inproc-query-boundary', 'a' * 64
        graph_identity = self.addon.graph_worker_identity()
        self.addon._TASK_HOST_IDENTITY = dict(
            self.addon._host_identity(), session_id=graph_identity['session_id'],
            process_generation=graph_identity['process_generation'], task_id=self.task,
            pid=os.getpid(), launch_nonce=self.nonce, plugin_build=self.addon._FX_LOADED_ADDON_SHA256)
        self.root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((self.task + ':' + self.graph_hash).encode()).hexdigest()
        self.addon.dispatch('scene.create_task_root', dict(task_id=self.task, parent='/obj',
            type='geo', root_name=self.root.rsplit('/', 1)[1]))
        self.runner = self.addon.fx_operation_runner(self.task)
        self.directory = self.host.state_path.parent

    def request(self, operation='query', **extra):
        return dict(task_id=self.task, operation_id=operation, request_id=operation,
                    frozen_input_manifest=[], path=self.root, root_path=self.root,
                    inspect_policy=CHILDREN_INSPECT_POLICY, **extra)

    def record(self, operation='query'):
        return load_record(self.runner.path, self.task, operation)

    def test_query_avoids_scene_capture_and_defaults_remain_full_operation(self):
        with patch.object(self.addon, '_fx_producer_scene', wraps=self.addon._fx_producer_scene) as capture:
            before = self.host.writes()
            result = self.addon.dispatch('node.children', self.request())
            capture.assert_not_called()
            self.assertEqual(self.host.writes(), before)
            receipt = result['operation_receipt']
            validate_operation_receipt(receipt)
            self.assertEqual(receipt['schema'], QUERY_SCHEMA)
            self.assertFalse(receipt['facts']['full_scene_identity_verified'])
            self.assertNotIn('before_scene', receipt)
            self.assertNotIn('after_scene', receipt)
            self.assertEqual(receipt, self.record())
            old = self.request('old-default')
            old.pop('inspect_policy')
            legacy = self.addon.dispatch('node.children', old)['operation_receipt']
            self.assertEqual(legacy['schema'], SCHEMA)
            self.assertEqual(capture.call_count, 2)
            validate_operation_receipt(legacy)
        queried = self.addon.dispatch('agent.fx.operation_receipt', {'task_id': self.task, 'operation_id': 'query'})
        self.assertEqual(queried['operation_receipt'], receipt)
        self.assertIsNone(queried['current_scene'])

    def test_graph_producer_and_root_lease_have_distinct_native_identities(self):
        native_identity=self.addon._fx_producer_identity
        def graph_identity(task_id):
            return dict(native_identity(task_id),session_id='independent-graph-session',
                        process_generation='independent-graph-generation')
        with patch.object(self.addon,'_fx_producer_identity',graph_identity):
            result=self.addon.dispatch('node.children',self.request())
            receipt=result['operation_receipt']
            validate_operation_receipt(receipt)
            before=receipt['before_query']
            self.assertNotEqual(before['host_identity']['session_id'],before['lease_identity']['session_id'])
            self.assertNotEqual(before['host_identity']['process_generation'],before['lease_identity']['process_generation'])
            self.assertTrue(self.addon.dispatch('node.children',self.request())['idempotent'])
        for field in ('owner_session_id','owner_generation','scene_epoch'):
            changed=deepcopy(receipt)
            value=changed['before_query']['root_lease'][field]
            changed['before_query']['root_lease'][field]=value+1 if type(value) is int else 'foreign'
            changed['after_query']=deepcopy(changed['before_query'])
            changed['operation_receipt_sha256']=operation_receipt_sha256(changed)
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_operation_receipt(changed)

    def test_replay_checks_current_direct_children_but_not_unobserved_parameters(self):
        child = self.host.hou.node(self.root).createNode('attribwrangle', 'child')
        request = self.request()
        result = self.addon.dispatch('node.children', request)
        payload = Path(result['operation_store_path']).read_bytes()
        child.parm('snippet').set('unobserved parameter edit')
        replay = self.addon.dispatch('node.children', request)
        self.assertTrue(replay['idempotent'])
        self.assertEqual(replay['operation_receipt'], result['operation_receipt'])
        self.host.hou.node(self.root).createNode('attribwrangle', 'new_child')
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon.dispatch('node.children', request)
        self.assertEqual(caught.exception.code, 'SCENE_STATE_DRIFT')
        self.assertEqual(Path(result['operation_store_path']).read_bytes(), payload)
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon.dispatch('node.children', request | {'path': child.path()})
        self.assertEqual(caught.exception.code, 'CONTENT_CHANGED')

    def test_policy_rejects_mutations_foreign_paths_and_extra_query_fields(self):
        for command, changes in [('node.create', {'parent': self.root, 'type': 'attribwrangle', 'name': 'never'}),
                                 ('node.subtree', {}), ('node.children', {'path': '/obj'}),
                                 ('node.children', {'path': self.root + '/../foreign'}),
                                 ('node.children', {'recursive': True})]:
            with self.subTest(command=command, changes=changes), self.assertRaises((ValueError, self.addon.BridgeCommandError)):
                self.addon.dispatch(command, self.request() | changes)
        self.assertIsNone(self.host.hou.node(self.root + '/never'))
        self.assertIsNone(self.record())

    def test_frozen_bytes_checked_before_query_and_after_dispatch(self):
        path = self.directory / 'frozen.dat'
        path.write_bytes(b'original')
        frozen = [{'index': 0, 'source_uri': str(path), 'sha256': hashlib.sha256(b'original').hexdigest(), 'bytes': 8}]
        request = self.request() | {'frozen_input_manifest': frozen}
        node_class = type(self.host.hou.node(self.root))
        native = node_class.children
        def change(node):
            result = native(node)
            path.write_bytes(b'changed!')
            return result
        with patch.object(node_class, 'children', change):
            with self.assertRaises(self.addon.BridgeCommandError):
                self.addon.dispatch('node.children', request)
        self.assertEqual(self.record()['state'], 'FAILED')
        with self.assertRaises(self.addon.BridgeCommandError):
            self.addon.dispatch('node.children', request | {'operation_id': 'bad-input', 'request_id': 'bad-input'})
        self.assertIsNone(self.record('bad-input'))

    def test_native_epoch_hip_and_lease_drift_persist_failed(self):
        node_class = type(self.host.hou.node(self.root))
        native = node_class.children
        for case in ('epoch', 'hip', 'lease'):
            with self.subTest(case=case):
                # Each case gets a fresh addon/HOM fixture so its ownership is valid.
                fixture = ProducerQueryTests(methodName='runTest')
                fixture.setUp()
                try:
                    cls = type(fixture.host.hou.node(fixture.root))
                    children = cls.children
                    def drift(node):
                        result = children(node)
                        if case == 'epoch':
                            fixture.addon._bridge_scene_event(fixture.host.hou.hipFileEventType.BeforeLoad)
                        elif case == 'hip':
                            fixture.host.hou.hipFile.setName(str(fixture.directory / 'changed.hip'))
                        else:
                            lease_path = fixture.addon._root_lease_path(fixture.root)
                            lease = json.loads(lease_path.read_bytes())
                            lease['owner_generation'] = 'foreign-generation'
                            lease_path.write_text(json.dumps(lease))
                        return result
                    with patch.object(cls, 'children', drift), self.assertRaises(fixture.addon.BridgeCommandError):
                        fixture.addon.dispatch('node.children', fixture.request())
                    self.assertEqual(fixture.record()['state'], 'FAILED')
                finally:
                    fixture.doCleanups()

    def test_result_is_bounded_and_only_direct_children_are_accepted(self):
        root = self.host.hou.node(self.root)
        child = root.createNode('attribwrangle', 'child')
        cls, native = type(root), type(root).children
        for operation, result in [('oversized', tuple(child for _ in range(QUERY_MAX_CHILDREN + 1))),
                                  ('foreign-result', (self.host.hou.node('/obj'),))]:
            def children(node):
                return result if node.path() == self.root else native(node)
            with self.subTest(operation=operation), patch.object(cls, 'children', children):
                with self.assertRaises(ValueError):
                    self.addon.dispatch('node.children', self.request(operation))
            self.assertEqual(self.record(operation)['state'], 'FAILED')

    def test_writer_failure_retains_incomplete_and_replay_never_reads_children(self):
        native_replace = platform_support.atomic_replace
        def refuse_completed(source, target, *args, **kwargs):
            if 'producer-records' in Path(target).parts and json.loads(Path(source).read_bytes())['state'] in {'COMPLETED', 'FAILED'}:
                raise OSError('bottom filesystem failure')
            return native_replace(source, target, *args, **kwargs)
        with patch.object(platform_support, 'atomic_replace', refuse_completed), self.assertRaises(OSError):
            self.addon.dispatch('node.children', self.request())
        self.assertEqual(self.record()['state'], 'INTENT')
        cls = type(self.host.hou.node(self.root))
        with patch.object(cls, 'children', side_effect=AssertionError('incomplete query reexecuted')):
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                self.addon.dispatch('node.children', self.request())
        self.assertEqual(caught.exception.code, 'PRODUCER_RECONCILE_REQUIRED')

    def test_validator_rejects_self_consistent_wrong_scope_and_mutation_schema(self):
        receipt = self.addon.dispatch('node.children', self.request())['operation_receipt']
        for change in ('command', 'scene', 'identity', 'proof', 'result', 'request_digest'):
            altered = deepcopy(receipt)
            if change == 'command':
                altered['command'] = 'node.create'
            elif change == 'scene':
                altered['after_scene'] = {'scene_contract': {}}
            elif change == 'identity':
                altered['after_query']['host_identity']['scene_epoch'] += 1
            elif change == 'proof':
                altered['facts']['full_scene_identity_verified'] = True
            elif change == 'result':
                altered['result']['nodes'] = [{'path': self.root + '/nested/child', 'name': 'child', 'type': 'null'}]
                altered['facts']['handler_result_sha256'] = canonical_sha256(altered['result'])
            else:
                altered['request_sha256'] = '0' * 64
            altered['operation_receipt_sha256'] = operation_receipt_sha256(altered)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_operation_receipt(altered)

    def worker(self):
        worker = GraphJobWorker.__new__(GraphJobWorker)
        worker.addon, worker.repo_root = self.addon, ROOT
        worker.root, worker.result_path = self.directory, self.directory / 'result.json'
        worker.execution_task_id, worker.operation_id = self.task, 'query-worker'
        worker.job = {'attempt_token': self.nonce, 'attempt_generation': 1}
        worker.managed, worker.scheduler = True, None
        worker.clock = time.time
        worker.deadline_at, worker._deadline_monotonic = time.time() + 60, time.monotonic() + 60
        worker.native_operation_sequence, worker.native_operation_receipts = 0, []
        worker.lease_store = SceneLeaseStore(self.directory / 'lease.sqlite3')
        identity = worker._host_identity()
        worker.lease = worker.lease_store.acquire(task_id=self.task, root=self.root,
            **{key: identity[key] for key in ('session_id', 'process_generation', 'scene_id')})
        return worker

    def test_actual_worker_opt_in_dispatch_store_bytes_and_publication(self):
        worker = self.worker()
        parent = worker._fenced_dispatch('node.children', {'path': '/obj'})
        self.assertNotIn('operation_receipt', parent)
        self.assertEqual(worker.native_operation_receipts, [])
        result = worker._fenced_dispatch('node.children', {'path': self.root})
        self.assertEqual(result['operation_receipt']['schema'], QUERY_SCHEMA)
        published = worker._native_receipt_evidence(SimpleNamespace(graph_hash=self.graph_hash))
        self.assertEqual(published['count'], 1)
        path = Path(result['operation_store_path'])
        payload = path.read_bytes()
        path.write_bytes(payload + b'\n')
        with self.assertRaisesRegex(ValueError, 'evidence bytes changed'):
            worker._native_receipt_evidence(SimpleNamespace(graph_hash=self.graph_hash))

    def test_unmanaged_worker_children_does_not_opt_in_or_add_receipts(self):
        worker = self.worker()
        worker.managed = False
        before = self.host.writes()
        records = sorted(self.runner.path.parent.glob('producer-records/*/*.json'))
        with patch.object(self.addon, 'dispatch', wraps=self.addon.dispatch) as dispatch:
            result = worker._fenced_dispatch('node.children', {'path': self.root})
        dispatch.assert_called_once_with('node.children', {'path': self.root})
        self.assertEqual(result, {'path': self.root, 'nodes': []})
        self.assertNotIn('operation_receipt', result)
        self.assertEqual(worker.native_operation_sequence, 0)
        self.assertEqual(worker.native_operation_receipts, [])
        self.assertIsNone(worker._native_receipt_evidence(SimpleNamespace(graph_hash=self.graph_hash)))
        self.assertEqual(self.host.writes(), before)
        self.assertEqual(sorted(self.runner.path.parent.glob('producer-records/*/*.json')), records)

    def test_worker_rejects_stale_dispatch_result_and_persisted_tampering(self):
        result = self.addon.dispatch('node.children', self.request())
        receipt = result['operation_receipt']
        expected = dict(command='node.children', request=self.request(), result=result, task_id=self.task,
            host_identity=self.addon.graph_worker_identity(), launch_nonce=self.nonce,
            plugin_build=self.addon._FX_LOADED_ADDON_SHA256)
        self.assertEqual(_verify_native_dispatch_receipt(receipt, **expected), receipt)
        for changes in ({'result': result | {'nodes': [{'different': 'current result'}]}},
                        {'launch_nonce': 'stale-attempt'}, {'request': self.request('other-query')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _verify_native_dispatch_receipt(receipt, **(expected | changes))
        worker = self.worker()
        cls, native = type(self.host.hou.node(self.root)), type(self.host.hou.node(self.root)).children
        def tamper(node):
            result = native(node)
            for path in self.runner.path.parent.glob('producer-records/*/*.json'):
                record = json.loads(path.read_bytes())
                if record['state'] == 'INTENT':
                    record['started_at'] = 'concurrent record replacement'
                    record['operation_receipt_sha256'] = operation_receipt_sha256(record)
                    path.write_text(json.dumps(record))
            return result
        with patch.object(cls, 'children', tamper), self.assertRaises(self.addon.BridgeCommandError):
            worker._fenced_dispatch('node.children', {'path': self.root})
        self.assertEqual(worker.native_operation_receipts, [])

    def prepared_query_evidence(self):
        worker = self.worker()
        result = worker._fenced_dispatch('node.children', {'path': self.root})
        reference = worker._native_receipt_evidence(SimpleNamespace(graph_hash=self.graph_hash))
        names = ('plugins/houdini/_impl/houdini_bridge_addon.py',
                 'packages/houdini-bridge/src/houdini_bridge/operation_receipts.py',
                 'packages/houdini-bridge/src/houdini_bridge/operation_receipt_store.py',
                 'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py')
        entries = []
        for name in names:
            frozen = self.directory / 'snapshot' / name
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes((ROOT / name).read_bytes())
            entries.append({'path': name, 'sha256': evidence.digest(frozen)})
        manifest = self.directory / 'run.json'
        manifest.write_text('{}')
        index = self.directory / 'snapshot-manifest.json'
        index.write_text(json.dumps({'files': entries}))
        source = dict(manifest_path=str(manifest), manifest_sha256=evidence.digest(manifest),
            repo_root=str(self.directory / 'snapshot'), snapshot_manifest_sha256=evidence.digest(index))
        arguments = dict(owner=self.task, graph_id='query-graph', graph_version=0,
                         graph_hash=self.graph_hash, operation_id=worker.operation_id)
        return result, reference, source, arguments

    def test_final_evidence_reader_accepts_query_scope_then_requires_real_stop(self):
        result, reference, source, arguments = self.prepared_query_evidence()
        with patch.object(evidence, '_prepared_stop_at', return_value={}) as stop:
            proofs, _stale = evidence._prepared_native_commands(
                reference, self.directory, source, **arguments)
        self.assertEqual(proofs, [dict(stage='inspect', proof_scope='owned_root_children',
            command='node.children', operation_id=result['operation_receipt']['operation_id'],
            operation_receipt_sha256=result['operation_receipt']['operation_receipt_sha256'],
            task_id=self.task, graph_id='query-graph', graph_version=0, graph_hash=self.graph_hash,
            source=source, current_source_matches=False)])
        stop.assert_called_once()
        self.assertEqual(stop.call_args.kwargs, {'require_success': False})
        with self.assertRaises((ValueError, OSError)) as caught:
            evidence._prepared_native_commands(reference, self.directory, source, **arguments)
        self.assertRegex(str(caught.exception), 'stop|supervisor|receipt|missing')
        self.assertNotIn('producer result/owner/root', str(caught.exception))

    def test_final_reader_rejects_rehashed_wrong_root_and_cross_schema_scopes(self):
        result, reference, source, arguments = self.prepared_query_evidence()
        packet_path = Path(reference['path'])
        packet = json.loads(packet_path.read_bytes())

        def persist(record, path):
            record['facts']['handler_result_sha256'] = canonical_sha256(record['result'])
            record['request_sha256'] = canonical_sha256(dict(task_id=record['task_id'],
                command=record['command'], request_id=record['request_id'], request=record['request']))
            record['operation_receipt_sha256'] = operation_receipt_sha256(record)
            payload = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
            Path(path).write_bytes(payload)
            altered = deepcopy(packet)
            descriptor = altered['receipts'][0]
            for key in descriptor.keys() & record.keys():
                descriptor[key] = deepcopy(record[key])
            descriptor.update(path=str(path), bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                              handler_result_sha256=record['facts']['handler_result_sha256'])
            packet_path.write_text(json.dumps(altered))
            return reference | {'bytes': packet_path.stat().st_size, 'sha256': evidence.digest(packet_path)}

        full_request = self.request('full-scope')
        full_request.pop('inspect_policy')
        full = self.addon.dispatch('node.children', full_request)
        cases = [('wrong-root', 'native producer result/owner/root'),
                 ('query-native-scope', 'PRODUCER_QUERY_INVALID: query facts'),
                 ('query-scene-scope', 'PRODUCER_QUERY_INVALID: query facts'),
                 ('full-query-scope', 'native producer result/owner/root')]
        for case, error in cases:
            record = deepcopy((full if case == 'full-query-scope' else result)['operation_receipt'])
            path = (full if case == 'full-query-scope' else result)['operation_store_path']
            if case == 'wrong-root':
                wrong_root = '/obj/BRIDGE_GRAPH_' + 'b' * 64
                record['request'].update(path=wrong_root, root_path=wrong_root)
                record['result']['path'] = wrong_root
                for name in ('before_query', 'after_query'):
                    record[name]['root_lease']['root'] = wrong_root
            else:
                record['facts']['proof_scope'] = {
                    'query-native-scope': 'native_command', 'query-scene-scope': 'task_scene',
                    'full-query-scope': 'owned_root_children'}[case]
            altered_reference = persist(record, path)
            if case in {'wrong-root', 'full-query-scope'}:
                validate_operation_receipt(record)
            with self.subTest(case=case), patch.object(evidence, '_prepared_stop_at', return_value={}) as stop:
                with self.assertRaisesRegex(ValueError, error):
                    evidence._prepared_native_commands(altered_reference, self.directory, source, **arguments)
                stop.assert_not_called()

    def test_current_save_acceptance_rejects_valid_query_receipt(self):
        result = self.addon.dispatch('node.children', self.request())
        validate_operation_receipt(result['operation_receipt'])
        with self.assertRaisesRegex(ValueError, 'current SAVE typed producer owner/command/storage mismatch'):
            evidence._prepared_current_save(result, {}, {}, {}, self.directory,
                owner=self.task, graph_id='query-graph', graph_version=0)


if __name__ == '__main__':
    unittest.main()
