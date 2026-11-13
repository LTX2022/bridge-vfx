"""In-process HOM records and synthetic signed process-boundary unit fixtures."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import stat
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import readiness_evidence as evidence
from source_host_fixture import FakeSourceHost
from vfx_pipeline.graph_job_worker import GraphJobWorker


class NativeCommandEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory(dir=ROOT / 'outputs')))
        addon_path = ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        spec = importlib.util.spec_from_file_location('_readiness_native_addon', addon_path)
        self.addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.addon)
        host = self.enterContext(FakeSourceHost(self.addon))
        self.enterContext(patch.object(self.addon, '_state_dir',
            return_value=self.directory / 'houdini-instances' / 'instances'))
        self.owner, self.nonce, self.operation_id = 'abc123', 'explicit-parser-unit', 'parser-publication'
        self.graph_hash = 'a' * 64
        self.addon._TASK_HOST_IDENTITY = dict(self.addon._host_identity(), task_id=self.owner,
            pid=os.getpid(), launch_nonce=self.nonce, plugin_build=evidence.digest(addon_path), version=host.version)
        graph_root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((self.owner + ':' + self.graph_hash).encode()).hexdigest()
        requests = [('scene.create_task_root', {'parent': '/obj', 'type': 'geo', 'root_name': graph_root.rsplit('/', 1)[1]}),
                    ('node.info', {'path': graph_root}),
                    ('scene.save_hip', {'path': str(self.directory / 'owned.hip'), 'root_path': graph_root})]
        self.descriptors = []
        for index, (command, params) in enumerate(requests):
            native_id = 'native-parser-' + str(index)
            result = self.addon.dispatch(command, dict(params, task_id=self.owner, operation_id=native_id,
                request_id=native_id, graph_hash=self.graph_hash, frozen_input_manifest=[]))
            record = result['operation_receipt']
            payload = Path(result['operation_store_path']).read_bytes()
            descriptor = {key: record[key] for key in ('schema', 'task_id', 'operation_id', 'request_id',
                'command', 'kind', 'state', 'operation_receipt_sha256', 'request_sha256', 'host_identity')}
            descriptor.update(handler_result_sha256=record['facts']['handler_result_sha256'],
                storage_format=result['operation_store_format'], path=result['operation_store_path'],
                bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            self.descriptors.append(descriptor)
        self.saved = result
        worker = GraphJobWorker.__new__(GraphJobWorker)
        worker.addon, worker.root, worker.execution_task_id = self.addon, self.directory, self.owner
        worker.operation_id, worker.result_path = self.operation_id, self.directory / 'result.json'
        worker.job = {'attempt_token': self.nonce, 'attempt_generation': 1}
        worker.native_operation_receipts = self.descriptors
        self.reference = worker._native_receipt_evidence(SimpleNamespace(graph_hash=self.graph_hash))
        source_names = ('plugins/houdini/_impl/houdini_bridge_addon.py',
            'packages/houdini-bridge/src/houdini_bridge/operation_receipts.py',
            'packages/houdini-bridge/src/houdini_bridge/operation_receipt_store.py',
            'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py',
            'packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py')
        entries = []
        for name in source_names:
            frozen = self.directory / 'snapshot' / name
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes((ROOT / name).read_bytes())
            entries.append({'path': name, 'sha256': evidence.digest(frozen)})
        manifest = self.directory / 'run.json'
        manifest.write_text('{}', encoding='utf-8')
        index = self.directory / 'snapshot-manifest.json'
        index.write_text(json.dumps({'files': entries}), encoding='utf-8')
        self.source = {'manifest_path': str(manifest), 'manifest_sha256': evidence.digest(manifest),
            'repo_root': str(self.directory / 'snapshot'), 'snapshot_manifest_sha256': evidence.digest(index)}

    def inspect(self, reference=None):
        return evidence._prepared_native_commands(self.reference if reference is None else reference, ROOT,
            self.source, owner=self.owner, graph_id='owned-graph', graph_version=0,
            graph_hash=self.graph_hash, operation_id=self.operation_id)

    def rewrite_packet(self, mutate):
        path = Path(self.reference['path'])
        packet = json.loads(path.read_bytes())
        mutate(packet)
        path.write_text(json.dumps(packet), encoding='utf-8')
        return dict(self.reference, bytes=path.stat().st_size, sha256=evidence.digest(path))

    def signed_stop_fixture(self, exit_code=1, *, start_fields=None, stop_fields=None,
                            directory=None, identity=None):
        owned = evidence._owned_receipt_module()
        directory = directory or Path(self.reference['path']).parent / 'owned-supervisor'
        directory.mkdir(parents=True, exist_ok=True)
        identity = identity or {'operation_id': self.operation_id, 'attempt_token': self.nonce, 'generation': 1}
        key = secrets.token_bytes(32)
        (directory / 'receipt.key').write_bytes(key)
        started = {'schema': owned.SCHEMA, 'event': 'started', 'identity': identity,
            'execution_protocol': 1, 'evidence_source': 'software_fixture',
            'pid': self.descriptors[-1]['host_identity']['pid'], 'platform': 'windows',
            'process_birth': '123456789', 'job': {'name': 'BridgeOwnedJob-explicit-unit-fixture',
                'assigned_at_creation': True, 'kill_on_close': True, 'process_is_in_job': True}}
        started.update(start_fields or {})
        stopped = dict(started, event='stopped', exit_code=exit_code, observed_by='owned_child_wait',
            supervisor_exit_code=0, execution_result='failed' if exit_code else 'succeeded',
            descendant_result_unobserved=False, stop_reason=None,
            child_wait_observed=True, job_active_processes=0,
            started_sha256=hashlib.sha256(owned._canonical(started)).hexdigest())
        stopped.update(stop_fields or {})
        for payload in (started, stopped):
            envelope = {'payload': payload,
                'signature': hmac.new(key, owned._canonical(payload), hashlib.sha256).hexdigest()}
            (directory / (payload['event'] + '.json')).write_text(json.dumps(envelope), encoding='utf-8')
        return directory, identity

    def test_signed_stop_default_and_render_wrapper_require_success(self):
        host = self.descriptors[-1]['host_identity']
        render_identity = {key: host[key] for key in ('task_id', 'launch_nonce')}
        render_directory = Path(self.source['manifest_path']).parent / 'houdini-task-host' / ('supervisor-' + self.nonce)
        for exit_code in (0, 1, -15):
            with self.subTest(exit_code=exit_code):
                directory, identity = self.signed_stop_fixture(exit_code)
                self.signed_stop_fixture(exit_code, directory=render_directory, identity=render_identity)
                if exit_code == 0:
                    self.assertEqual(evidence._prepared_stop_at(host, str(directory), identity, None)['identity'], identity)
                    self.assertEqual(evidence._prepared_stop(host, self.source, None)['identity'], render_identity)
                else:
                    with self.assertRaisesRegex(ValueError, 'owner stop/child wait proof missing'):
                        evidence._prepared_stop_at(host, str(directory), identity, None)
                    with self.assertRaisesRegex(ValueError, 'owner stop/child wait proof missing'):
                        evidence._prepared_stop(host, self.source, None)

    def test_completed_native_commands_accept_signed_abnormal_stop_only_as_primitives(self):
        for exit_code in (0, 1, -15):
            with self.subTest(exit_code=exit_code):
                self.signed_stop_fixture(exit_code)
                proofs, stale = self.inspect()
                self.assertEqual(stale, [])
                self.assertEqual([proof['stage'] for proof in proofs], ['build', 'inspect', 'save'])
                self.assertEqual([proof['proof_scope'] for proof in proofs], ['native_command', 'native_command', 'task_scene'])
                case = self.prepared_case()
                case['status'] = 'BLOCKED'
                result = evidence.inspect_prepared_case(case, ROOT)
                self.assertEqual(case['status'], 'BLOCKED')
                self.assertEqual(result['errors'], [])
                self.assertEqual(len(result['proofs']), 4)
                self.assertTrue(any('full_semantic' in missing for missing in result['missing_proofs']))
                self.assertTrue(any('recovery' in missing for missing in result['missing_proofs']))
                self.assertFalse(any(missing.startswith('save:') for missing in result['missing_proofs']))
                self.assertEqual(result['proofs'][0]['proof_scope'], 'current_task_save')
                self.assertIn('primitive stages only', result['supporting_evidence']['native_command_scope'])

    def test_abnormal_stop_rejects_wrong_pid_and_attempt_even_when_signed(self):
        for fields in ({'pid': os.getpid() + 10000},
                       {'identity': {'operation_id': self.operation_id, 'attempt_token': 'old-attempt', 'generation': 1}},
                       {'identity': {'operation_id': 'other-operation', 'attempt_token': self.nonce, 'generation': 1}},
                       {'identity': {'operation_id': self.operation_id, 'attempt_token': self.nonce, 'generation': 2}}):
            with self.subTest(fields=fields):
                self.signed_stop_fixture(start_fields=fields)
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_abnormal_stop_keeps_child_wait_and_windows_job_binding_mandatory(self):
        for fields in ({'observed_by': 'controller_claim'}, {'child_wait_observed': False},
                       {'child_wait_observed': None}, {'job_active_processes': 1},
                       {'job_active_processes': None}, {'job_active_processes': False},
                       {'job_active_processes': 0.0}, {'process_birth': '987654321'},
                       {'job': {'name': 'BridgeOwnedJob-other'}}, {'platform': 'posix'},
                       {'started_sha256': '0' * 64},
                       {'exit_code': None}, {'exit_code': False}, {'exit_code': 1.0}):
            with self.subTest(fields=fields):
                self.signed_stop_fixture(stop_fields=fields)
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_abnormal_stop_rejects_missing_or_tampered_signed_evidence(self):
        for name in ('started.json', 'stopped.json'):
            for mutation in ('signature_missing', 'signature_wrong', 'payload_tampered'):
                with self.subTest(name=name, mutation=mutation):
                    directory, _ = self.signed_stop_fixture()
                    path = directory / name
                    envelope = json.loads(path.read_bytes())
                    if mutation == 'signature_missing':
                        envelope.pop('signature')
                    elif mutation == 'signature_wrong':
                        envelope['signature'] = '0' * 64
                    else:
                        envelope['payload']['pid'] += 1
                    path.write_text(json.dumps(envelope), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'SUPERVISOR_RECEIPT_MISMATCH'):
                        self.inspect()
        for name in ('started.json', 'stopped.json', 'receipt.key'):
            with self.subTest(missing=name):
                directory, _ = self.signed_stop_fixture()
                (directory / name).unlink()
                with self.assertRaises((ValueError, OSError)):
                    self.inspect()

    def test_incomplete_native_receipts_reject_before_abnormal_stop(self):
        from houdini_bridge.operation_receipts import operation_receipt_sha256

        self.signed_stop_fixture()
        descriptor = self.descriptors[-1]
        record_path = Path(descriptor['path'])
        original_record = record_path.read_bytes()
        original_packet = Path(self.reference['path']).read_bytes()
        for state in ('INTENT', 'FAILED'):
            with self.subTest(state=state):
                Path(self.reference['path']).write_bytes(original_packet)
                record = json.loads(original_record)
                record['state'] = state
                record['operation_receipt_sha256'] = operation_receipt_sha256(record)
                record_path.write_text(json.dumps(record), encoding='utf-8')

                def mutate(packet):
                    packet['receipts'][-1].update(state=state,
                        operation_receipt_sha256=record['operation_receipt_sha256'],
                        sha256=evidence.digest(record_path), bytes=record_path.stat().st_size)

                reference = self.rewrite_packet(mutate)
                with patch.object(evidence, '_prepared_stop_at', wraps=evidence._prepared_stop_at) as stop:
                    with self.assertRaisesRegex(ValueError, 'schema, command or state'):
                        self.inspect(reference)
                    stop.assert_not_called()
        record_path.write_bytes(original_record)
        Path(self.reference['path']).write_bytes(original_packet)
        reference = self.rewrite_packet(lambda packet: packet.update(receipts=[]))
        reference['count'] = 0
        with patch.object(evidence, '_prepared_stop_at', wraps=evidence._prepared_stop_at) as stop:
            with self.assertRaisesRegex(ValueError, 'attempt/count binding missing'):
                self.inspect(reference)
            stop.assert_not_called()

    def test_abnormal_stop_does_not_bypass_frozen_source_or_saved_bytes(self):
        self.signed_stop_fixture()
        frozen = Path(self.source['repo_root']) / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        snapshot = Path(self.saved['operation_receipt']['facts']['saved_scene']['snapshot_path'])
        for path in (frozen, snapshot):
            with self.subTest(path=path):
                original = path.read_bytes()
                original_mode = path.stat().st_mode
                try:
                    path.chmod(original_mode | stat.S_IWUSR)
                    path.write_bytes(original + b'\ncorrupt')
                    with patch.object(evidence, '_prepared_stop_at', wraps=evidence._prepared_stop_at) as stop:
                        with self.assertRaisesRegex(ValueError, 'evidence file bytes/hash mismatch'):
                            self.inspect()
                        stop.assert_not_called()
                finally:
                    path.write_bytes(original)
                    path.chmod(original_mode)

    def test_actual_inprocess_records_cannot_claim_supervised_stages(self):
        with self.assertRaises((ValueError, OSError)):
            self.inspect()

    def test_actual_record_parsing_preserves_primitive_scope_and_attempt_binding(self):
        with patch.object(evidence, '_prepared_stop_at', return_value={}) as stop:
            proofs, stale = self.inspect()
        self.assertEqual(stale, [])
        self.assertEqual([item['stage'] for item in proofs], ['build', 'inspect', 'save'])
        self.assertEqual([item['proof_scope'] for item in proofs], ['native_command', 'native_command', 'task_scene'])
        stop.assert_called_once_with({key: self.descriptors[-1]['host_identity'][key] for key in
             ('task_id', 'pid', 'launch_nonce', 'session_id', 'process_generation', 'plugin_build')},
            str(Path(self.reference['path']).parent / 'owned-supervisor'),
            {'operation_id': self.operation_id, 'attempt_token': self.nonce, 'generation': 1}, None,
            require_success=False)

    def test_relative_public_locator_resolves_only_owned_operation_attempt(self):
        relative = Path('graph-jobs') / self.operation_id / 'attempt-1' / (self.operation_id + '.native-operations.json')
        published = self.directory / 'jobs' / relative
        published.parent.mkdir(parents=True)
        published.write_bytes(Path(self.reference['path']).read_bytes())
        reference = dict(self.reference, path=relative.as_posix())
        with patch.object(evidence, '_prepared_stop_at', return_value={}) as stop:
            proofs, stale = self.inspect(reference)
        self.assertEqual(stale, [])
        self.assertEqual(len(proofs), len(self.descriptors))
        self.assertEqual(stop.call_args.args[1], str(published.parent / 'owned-supervisor'))
        with self.assertRaisesRegex(ValueError, 'locator does not bind'):
            self.inspect(dict(reference, path='../' + relative.as_posix()))

    def test_graph_trial_status_envelope_admits_only_partial_native_proofs(self):
        case = self.prepared_case()
        case['stage_receipts'][0]['operation'] = 'graph_trial'
        with patch.object(evidence, '_prepared_stop_at', return_value={}):
            result = evidence.inspect_prepared_case(case, ROOT)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['stages'], ['build', 'inspect', 'save'])
        self.assertTrue(result['missing_proofs'])

    def test_changed_producer_bytes_rejected_even_with_recomputed_packet_hash(self):
        descriptor = self.descriptors[1]
        path = Path(descriptor['path'])
        path.write_bytes(path.read_bytes() + b'\n')
        reference = self.rewrite_packet(lambda packet: None)
        with self.assertRaisesRegex(ValueError, 'evidence file bytes/hash mismatch'):
            self.inspect(reference)

    def test_descriptor_owner_and_duplicate_operations_rejected(self):
        original = Path(self.reference['path']).read_bytes()
        for mutation in (lambda packet: packet['receipts'][0].update(task_id='another-owner'),
                         lambda packet: packet['receipts'].__setitem__(1, deepcopy(packet['receipts'][0]))):
            with self.subTest(mutation=mutation):
                Path(self.reference['path']).write_bytes(original)
                reference = self.rewrite_packet(mutation)
                with self.assertRaisesRegex(ValueError, 'descriptor differs|unique operation mismatch'):
                    self.inspect(reference)

    def test_stale_attempt_and_unbound_graph_rejected(self):
        for field, value in (('attempt_token', 'previous-attempt'), ('attempt_generation', True),
                             ('graph_hash', 'b' * 64), ('count', 1)):
            with self.subTest(field=field), patch.object(evidence, '_prepared_stop_at', return_value={}) as stop:
                with self.assertRaises(ValueError):
                    self.inspect(dict(self.reference, **{field: value}))
                stop.assert_not_called()

    def prepared_case(self):
        graph_id = 'owned-graph'
        saved = dict(self.saved, feedback_dependencies=[f'graph:{self.owner}:{graph_id}:output:domain_output',
            f'graph:{self.owner}:{graph_id}:version:0'])
        context = {'task_id': self.owner, 'graph_id': graph_id, 'graph_version': 0, 'source': self.source}
        case = {'case_id': 'parser-only-case', 'controller_task_id': self.owner,
            'graph_id': graph_id, 'graph_version': 0, 'save_receipt': saved,
            'stage_receipts': [dict(context, operation='graph_status', result={'result': {
                'operation_id': self.operation_id, 'native_operation_evidence': self.reference}}),
                dict(context, operation='graph_version', result={'task_id': self.owner, 'version': 0, 'state': 'COMPLETE', 'compiled': {'graph_hash': self.graph_hash}}),
                dict(context, operation='task_save', result=saved)]}
        return case

    def test_adapter_keeps_full_domain_missing_proofs_after_primitive_admission(self):
        case = self.prepared_case()
        with patch.object(evidence, '_prepared_stop_at', return_value={}):
            result = evidence.inspect_prepared_case(case, ROOT)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['stages'], ['build', 'inspect', 'save'])
        self.assertTrue(any('full_semantic' in missing for missing in result['missing_proofs']))
        self.assertTrue(any('recovery' in missing for missing in result['missing_proofs']))
        self.assertFalse(any(missing.startswith('save:') for missing in result['missing_proofs']))
        self.assertFalse(result['proofs'][0]['domain_lifecycle_verified'])
        self.assertIn('primitive stages only', result['supporting_evidence']['native_command_scope'])

    def test_extra_reference_fields_do_not_duplicate_proofs(self):
        case = self.prepared_case()
        duplicate = deepcopy(case['stage_receipts'][0])
        duplicate['result']['result']['native_operation_evidence']['mapper_hint'] = 1
        case['stage_receipts'].append(duplicate)
        with patch.object(evidence, '_prepared_stop_at', return_value={}):
            result = evidence.inspect_prepared_case(case, ROOT)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(result['proofs']), len(self.descriptors) + 1)

    def test_session_drift_rejected_before_stop_after_digest_recomputation(self):
        from houdini_bridge.operation_receipts import operation_receipt_sha256

        def mutate(packet):
            descriptor = packet['receipts'][1]
            path = Path(descriptor['path'])
            record = json.loads(path.read_bytes())
            record['host_identity']['session_id'] += '-different-session'
            for phase in ('before_scene', 'after_scene'):
                record[phase]['host_identity'] = deepcopy(record['host_identity'])
            record['operation_receipt_sha256'] = operation_receipt_sha256(record)
            path.write_text(json.dumps(record), encoding='utf-8')
            descriptor.update(host_identity=record['host_identity'],
                operation_receipt_sha256=record['operation_receipt_sha256'],
                sha256=evidence.digest(path), bytes=path.stat().st_size)

        reference = self.rewrite_packet(mutate)
        with patch.object(evidence, '_prepared_stop_at', return_value={}) as stop:
            with self.assertRaisesRegex(ValueError, 'actual process/frozen addon mismatch'):
                self.inspect(reference)
            stop.assert_not_called()

    def test_changed_packet_with_overlapping_operations_is_rejected(self):
        case = self.prepared_case()
        packet = json.loads(Path(self.reference['path']).read_bytes())
        packet['mapper_hint'] = 1
        copied = self.directory / 'overlapping-native.json'
        copied.write_text(json.dumps(packet), encoding='utf-8')
        duplicate = deepcopy(case['stage_receipts'][0])
        duplicate['result']['result']['native_operation_evidence'].update(
            path=str(copied), sha256=evidence.digest(copied), bytes=copied.stat().st_size)
        case['stage_receipts'].append(duplicate)
        with patch.object(evidence, '_prepared_stop_at', return_value={}):
            result = evidence.inspect_prepared_case(case, ROOT)
        self.assertEqual(len(result['proofs']), len(self.descriptors) + 1)
        self.assertTrue(any('operations overlap' in error for error in result['errors']))

    def test_malformed_historical_versions_do_not_annotate_proofs(self):
        for mutation in ({'version': True}, {'version': -1}, {'state': 'DISPATCHED'}):
            with self.subTest(mutation=mutation):
                case = self.prepared_case()
                historical = deepcopy(case['stage_receipts'][1])
                historical['result'].update(mutation)
                case['stage_receipts'].insert(0, historical)
                with patch.object(evidence, '_prepared_stop_at', return_value={}):
                    result = evidence.inspect_prepared_case(case, ROOT)
                self.assertEqual(result['errors'], [])
                self.assertTrue(all(type(proof['graph_version']) is int and proof['graph_version'] == 0
                                    for proof in result['proofs']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
