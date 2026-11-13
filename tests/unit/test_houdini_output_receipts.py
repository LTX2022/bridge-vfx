"""Contract tests using explicit file/transport fixtures, never DCC receipts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from uuid import uuid4
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('houdini-bridge', 'dcc-task-runtime'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from houdini_bridge import client
from dcc_task_runtime.artifact_registry import ArtifactRegistry, ArtifactError
from dcc_task_runtime.exr_codec import encode_tiny_exr
from dcc_task_runtime.graph_scheduler import GraphScheduler


class HoudiniOutputReceiptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='explicit-output-file-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'frame.001.exr'
        self.path.write_bytes(encode_tiny_exr())
        self.scene = self.root / 'fixture.hip'
        self.scene.write_bytes(b'explicit file fixture, not a Houdini save')
        scene_sha = hashlib.sha256(self.scene.read_bytes()).hexdigest()
        config = {'1': {'exr_format': {'compression': 'none'}, 'color_configuration_fact': {
            'schema': 'bridge.houdini.render-color-facts/1.0', 'frame': 1,
            'missing_facts': ['OCIO not observed in file fixture']}}}
        self.record = {
            'kind': 'render', 'request_id': 'fixture-operation', 'task_id': 'fixture-owner',
            'host_identity': {'pid': 12345, 'launch_nonce': 'fixture-not-a-host'},
            'scene': {'snapshot_path': str(self.scene), 'snapshot_sha256': scene_sha},
            'render_target': '/out/fixture', 'render_config': config,
            'frames': [1], 'frames_done': [1], 'output_pattern': str(self.root / 'frame.%03d.exr'),
            'budget_seconds': 1.0, 'started_at_epoch': 1.0, 'finished_at': 'fixture-time',
            'state': 'COMPLETED', 'dependencies': ['fixture-scene'],
            'frame_snapshots': {'1': self.snapshot()},
            'lifecycle_fact': {'stop_confirmed': True},
            'supervisor_binding': {'directory': str(self.root / 'supervisor'), 'identity': {'fixture': True}},
        }
        self.record['scene_fingerprint'] = client.render_receipt_digest({'scene': scene_sha, 'config': config})
        self.record['request_sha256'] = client.render_receipt_digest({
            'task_id': self.record['task_id'], 'frames': [1], 'budget_seconds': 1.0,
            'scene_sha256': scene_sha, 'render_target': '/out/fixture',
            'output_pattern': self.record['output_pattern'], 'dependencies': ['fixture-scene']})

    def snapshot(self):
        info = self.path.stat()
        return {'path': str(self.path), 'bytes': info.st_size, 'modified_ns': info.st_mtime_ns,
                'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def test_existing_producer_registry_refusal(self):
        fact = client.render_execution_fact(self.record)
        registry = ArtifactRegistry(self.root / 'registry')
        registry.set_operation_source(lambda operation_id: fact)
        with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED'):
            registry.register(artifact_id='fixture-output', task_id='fixture-owner',
                artifact_class='preview_temp', pattern=self.record['output_pattern'], frame_set=[1],
                colorspace='', premultiplied=None, dependencies=['fixture-scene'],
                operation_id='fixture-operation', scene_fingerprint=self.record['scene_fingerprint'],
                receipt_source_files={str(Path(client.__file__).resolve()):
                    hashlib.sha256(Path(client.__file__).read_bytes()).hexdigest()})
        self.assertEqual(registry.history('fixture-output'), [])

    def persist_contract_fixture(self, *, crash_before_terminal=False):
        """Actual supervised Python file producer; never a DCC render receipt."""
        self.store = self.root / 'operations.json'
        self.scheduler = GraphScheduler(self.root / 'scheduler')
        slot = self.scheduler.reserve(str(self.store), self.record['request_id'])
        self.record['slot'] = dict(slot, owner_root=str(self.store), operation_id=self.record['request_id'])
        self.record['scheduler_root'] = str(self.scheduler.root)
        from dcc_task_runtime.owned_process import launch, read_receipt
        identity = {'task_id': self.record['task_id'], 'launch_nonce': uuid4().hex}
        supervisor = self.root / 'actual-supervisor'
        self.record['supervisor_binding'] = {'directory': str(supervisor), 'identity': identity}
        initial = self.root / 'input.json'
        if crash_before_terminal:
            self.record['fixture_crash_before_terminal'] = True
        initial.write_text(json.dumps(self.record), encoding='utf-8')
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        executable = getattr(sys, '_base_executable', sys.executable)
        handle = launch([executable, '-B', str(Path(__file__).resolve()), '--producer-fixture', str(initial)],
                        directory=supervisor, identity=identity, supervisor_executable=executable,
                        env=env, budget_seconds=20)
        try:
            prepared = self.root / 'prepared.json'
            deadline = time.monotonic() + 10
            while not prepared.exists():
                if handle.poll() is not None or time.monotonic() > deadline:
                    self.fail('file producer did not prepare: ' + (supervisor / 'child.stderr.log').read_text())
                time.sleep(.01)
            self.record = json.loads(prepared.read_text(encoding='utf-8'))
            self.freeze_binding()
            (self.root / 'continue').write_text('frozen', encoding='utf-8')
            self.assertEqual(handle.wait(timeout=12), 7 if crash_before_terminal else 0,
                             (supervisor / 'child.stderr.log').read_text())
            self.assertIsNotNone(read_receipt(supervisor, 'stopped', identity=identity))
            self.record = json.loads(self.store.read_text(encoding='utf-8'))['operations']['fixture-operation']
            if not crash_before_terminal:
                self.anchor_path = supervisor / (client._render_terminal_event(self.binding['producer_binding']) + '.json')
        finally:
            if handle.poll() is None:
                handle.terminate()
                handle.wait(timeout=8)

    def freeze_binding(self):
        self.binding = {key: copy.deepcopy(self.record[key]) for key in (
            'request_sha256', 'host_identity', 'supervisor_binding')}
        self.binding.update(operation_store_path=str(self.store),
                            producer_binding=client.render_producer_binding(self.record))

    def persist(self):
        self.record['execution_fact'] = client.render_execution_fact(self.record)
        self.write_store()

    def write_store(self):
        self.store.write_text(json.dumps({'operations': {'fixture-operation': self.record}}), encoding='utf-8')

    def read(self):
        return client.read_render_operation(self.binding, task_id='fixture-owner', operation_id='fixture-operation')

    def test_real_worker_crash_recovers_same_binding_after_capacity_maintenance(self):
        from houdini_bridge import operation_store, render_observation_budget as budget
        from dcc_task_runtime.execution_lock import execution_lock
        from dcc_task_runtime.owned_process import read_receipt
        self.persist_contract_fixture(crash_before_terminal=True)
        self.assertEqual(self.record['state'], 'RUNNING')
        self.assertNotIn('execution_fact', self.record)
        stopped = read_receipt(self.record['supervisor_binding']['directory'], 'stopped',
                               identity=self.record['supervisor_binding']['identity'])
        self.assertEqual(stopped['exit_code'], 7)
        store = json.loads(self.store.read_text(encoding='utf-8'))
        for index in range(3):
            operation_id = 'legacy-history-' + str(index)
            store['operations'][operation_id] = {'task_id': 'fixture-owner', 'request_id': operation_id,
                'request_sha256': 'a' * 64, 'state': 'COMPLETED', 'padding': 'x' * 4000}
        original = json.dumps(store).encode('utf-8')
        self.store.write_bytes(original)
        slot = self.scheduler.snapshot()
        start_file = Path(self.record['supervisor_binding']['directory']) / 'started.json'
        stopped_file = start_file.with_name('stopped.json')
        original_start, original_stop = start_file.read_bytes(), stopped_file.read_bytes()
        with mock.patch.object(budget, 'MAX_STORE_BYTES', len(original) + 4), \
                mock.patch.object(budget, 'MAX_OPERATION_BYTES', 8192):
            with self.assertRaises(client.BridgeError) as full:
                self.read()
            self.assertEqual(full.exception.code, 'RENDER_OBSERVATION_BUDGET_EXCEEDED')
            self.assertEqual(self.store.read_bytes(), original)
            self.assertFalse(self.scheduler.snapshot()['active'])
            # This is the same locked maintenance called by signed control.resolve.
            with execution_lock(self.store.parent, 'fixture-owner'):
                report = operation_store.compact_store(self.store, 'fixture-owner')
            self.assertEqual(report['archived_operations'], 3)
            self.assertFalse(self.scheduler.snapshot()['active'])
            recovered = self.read()
            self.assertEqual(recovered['operation']['state'], 'FAILED')
            self.assertEqual(recovered['operation']['stage'], 'owned_host_stop_observed')
            self.assertEqual(recovered['execution_fact']['stop_basis'], stopped)
            self.assertFalse(self.scheduler.snapshot()['active'])
            self.assertEqual(self.read(), recovered)
            self.assertLessEqual(self.store.stat().st_size, budget.MAX_STORE_BYTES)
        self.assertEqual(start_file.read_bytes(), original_start)
        self.assertEqual(stopped_file.read_bytes(), original_stop)
        self.assertFalse(list(start_file.parent.glob('render-terminal-*.json')))

    def test_observes_actual_physical_metadata_without_color_or_alpha_defaults(self):
        observed = client.collect_render_output_fact(self.record, 1)
        self.assertEqual(observed['metadata']['sha256'], self.snapshot()['sha256'])
        self.assertEqual(observed['metadata']['width'], 1)
        self.assertTrue(observed['metadata']['structural_validated'])
        self.assertNotIn('rows', observed['metadata'])
        self.assertNotIn('colorspace', observed['metadata'])
        self.assertNotIn('premultiplied', observed['metadata'])
        self.assertIn('KARMA_HUSK_BEAUTY_ALPHA_ASSOCIATION_REQUIRED', observed['missing_facts'])

    def test_collected_fact_stays_blocked_and_detached_from_record(self):
        self.persist_contract_fixture()
        fact = self.read()['execution_fact']
        self.assertEqual(fact['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(fact['metadata'], {})
        self.record['render_config']['1']['arbitrary'] = True
        self.assertNotIn('arbitrary', fact['render_config']['1'])
        self.assertEqual(fact['operation_receipt_sha256'], client.render_receipt_digest(fact))

    def test_caller_metadata_and_available_are_not_adopted(self):
        self.record.update(completion_metadata_status='AVAILABLE',
                           metadata={'1': {'colorspace': 'linear', 'premultiplied': False}})
        fact = client.render_execution_fact(self.record)
        self.assertEqual(fact['metadata'], {})
        self.assertEqual(fact['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')

    def test_old_binding_cannot_be_upgraded_from_status(self):
        self.persist_contract_fixture()
        del self.binding['producer_binding']
        with self.assertRaises(client.BridgeError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'OPERATION_PRODUCER_BINDING_REQUIRED')
        self.assertTrue(self.scheduler.snapshot()['active'])

    def test_rehashed_fact_cannot_substitute_metadata_scene_or_config(self):
        self.persist_contract_fixture()
        original = copy.deepcopy(self.record['execution_fact'])
        for field, value in [('metadata', {'1': {'colorspace': 'linear', 'premultiplied': False}}),
                             ('scene', {}), ('render_config', {}), ('completion_metadata_status', 'AVAILABLE')]:
            with self.subTest(field=field):
                fact = copy.deepcopy(original)
                fact[field] = value
                fact['operation_receipt_sha256'] = client.render_receipt_digest(fact)
                self.record['execution_fact'] = fact
                self.write_store()
                with self.assertRaises(client.BridgeError) as caught:
                    self.read()
                self.assertEqual(caught.exception.code, 'RENDER_TERMINAL_ANCHOR_MISMATCH')
                self.assertFalse(self.scheduler.snapshot()['active'])

    def test_rehashed_record_config_cannot_replace_start_binding(self):
        self.persist_contract_fixture()
        self.record['render_config']['1']['color_configuration_fact']['frame'] = 2
        self.record['scene_fingerprint'] = client.render_receipt_digest({
            'scene': self.record['scene']['snapshot_sha256'], 'config': self.record['render_config']})
        self.persist()
        with self.assertRaises(client.BridgeError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'OPERATION_BINDING_MISMATCH')

    def test_rehashed_physical_metadata_is_checked_against_actual_bytes(self):
        self.persist_contract_fixture()
        self.record['output_facts']['1']['metadata']['width'] = 2
        self.persist()
        with self.assertRaises(client.BridgeError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'RENDER_TERMINAL_ANCHOR_MISMATCH')

    def test_changed_output_or_saved_scene_is_refused(self):
        self.persist_contract_fixture()
        for path in (self.path, self.scene):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                original_stat = path.stat()
                path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                with self.assertRaises(client.BridgeError) as caught:
                    self.read()
                self.assertEqual(caught.exception.code, 'RENDER_OUTPUT_BYTES_UNVERIFIED')
                path.write_bytes(original)
                os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    def test_rehashed_output_store_cannot_replace_terminal_original(self):
        self.persist_contract_fixture()
        original_binding = copy.deepcopy(self.binding)
        original_anchor = self.anchor_path.read_bytes()
        self.path.write_bytes(encode_tiny_exr(2.0))
        self.record['frame_snapshots']['1'] = self.snapshot()
        self.record['output_facts']['1'] = client.collect_render_output_fact(self.record, 1)
        self.persist()
        self.assertEqual(self.binding, original_binding)
        with self.assertRaises(client.BridgeError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'RENDER_TERMINAL_ANCHOR_MISMATCH')
        self.assertEqual(self.anchor_path.read_bytes(), original_anchor)
        self.assertFalse(self.scheduler.snapshot()['active'])

    def test_missing_or_tampered_terminal_original_cannot_be_recovered_from_status(self):
        self.persist_contract_fixture()
        anchor = self.anchor_path.read_bytes()
        self.anchor_path.unlink()
        with self.assertRaises(client.BridgeError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'RENDER_TERMINAL_ANCHOR_REQUIRED')
        self.assertFalse(self.anchor_path.exists())
        envelope = json.loads(anchor)
        envelope['payload']['execution_fact']['metadata'] = {'forged': True}
        self.anchor_path.write_text(json.dumps(envelope), encoding='utf-8')
        with self.assertRaises(client.BridgeError) as caught:
            self.read()
        self.assertEqual(caught.exception.code, 'RENDER_TERMINAL_ANCHOR_INVALID')

    def test_controller_cannot_seal_or_overwrite_terminal_original(self):
        self.persist_contract_fixture()
        original = self.anchor_path.read_bytes()
        with self.assertRaises(client.BridgeError) as caught:
            client.seal_render_terminal(self.record)
        self.assertEqual(caught.exception.code, 'RENDER_TERMINAL_PRODUCER_REQUIRED')
        self.assertEqual(self.anchor_path.read_bytes(), original)

    def test_replacement_during_decode_is_not_an_immutable_observation(self):
        from dcc_task_runtime import exr_codec
        original_decode = exr_codec.read_exr

        def replace_original(copy_path, **kwargs):
            image = original_decode(copy_path, **kwargs)
            replacement = self.path.with_suffix('.replacement')
            replacement.write_bytes(self.path.read_bytes())
            replacement.replace(self.path)
            return image

        with mock.patch.object(exr_codec, 'read_exr', side_effect=replace_original):
            with self.assertRaises(client.BridgeError) as caught:
                client.collect_render_output_fact(self.record, 1)
        self.assertEqual(caught.exception.code, 'RENDER_OUTPUT_BYTES_UNVERIFIED')

    def test_wrong_frame_path_or_compression_is_refused(self):
        self.record['frame_snapshots']['1']['path'] = str(self.scene)
        with self.assertRaises(client.BridgeError):
            client.collect_render_output_fact(self.record, 1)
        self.record['frame_snapshots']['1'] = self.snapshot()
        self.record['render_config']['1']['exr_format']['compression'] = 'zip'
        self.record['scene_fingerprint'] = client.render_receipt_digest({
            'scene': self.record['scene']['snapshot_sha256'], 'config': self.record['render_config']})
        with self.assertRaises(client.BridgeError):
            client.collect_render_output_fact(self.record, 1)


def run_file_producer(initial):
    """Only real process/file/codec primitives; explicitly synthetic render fields."""
    from dcc_task_runtime.owned_process import read_receipt, _atomic
    initial = Path(initial)
    record = json.loads(initial.read_text(encoding='utf-8'))
    supervisor = record['supervisor_binding']
    deadline = time.monotonic() + 8
    while read_receipt(supervisor['directory'], 'started', identity=supervisor['identity']) is None:
        if time.monotonic() > deadline:
            raise RuntimeError('actual supervisor start was not observed')
        time.sleep(.01)
    record['host_identity'] = {'pid': os.getpid(), 'launch_nonce': supervisor['identity']['launch_nonce'],
                               'fixture_kind': 'explicit_python_file_producer_not_DCC'}
    if record.get('fixture_crash_before_terminal'):
        from houdini_bridge.operation_store import write_snapshot
        record.update(state='RUNNING', frames_done=[], frame_snapshots={}, budget_token='fixture-budget-token',
                      lifecycle_fact={'stop_confirmed': False, 'source': 'explicit_python_file_fixture'})
        record.pop('finished_at', None)
        record.pop('execution_fact', None)
        write_snapshot(initial.parent / 'operations.json', {
            'task_id': record['task_id'], 'operations': {'fixture-operation': record}})
    _atomic(initial.parent / 'prepared.json', record)
    while not (initial.parent / 'continue').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('controller did not freeze start')
        time.sleep(.01)
    if record.get('fixture_crash_before_terminal'):
        raise SystemExit(7)
    record['output_facts'] = {'1': client.collect_render_output_fact(record, 1)}
    record['execution_fact'] = client.render_execution_fact(record)
    original = client.seal_render_terminal(record)
    anchor_path = Path(supervisor['directory']) / (original['event'] + '.json')
    original_bytes, original_stat = anchor_path.read_bytes(), anchor_path.stat()
    assert client.seal_render_terminal(record) == original
    assert anchor_path.read_bytes() == original_bytes
    assert anchor_path.stat().st_mtime_ns == original_stat.st_mtime_ns
    changed = copy.deepcopy(record)
    changed['output_facts']['1']['metadata']['width'] = 2
    changed['execution_fact'] = client.render_execution_fact(changed)
    try:
        client.seal_render_terminal(changed)
    except client.BridgeError as exc:
        assert exc.code == 'RENDER_TERMINAL_ANCHOR_MISMATCH', exc.code
    else:
        raise AssertionError('producer was allowed to overwrite its terminal original')
    _atomic(initial.parent / 'operations.json', {'operations': {'fixture-operation': record}})


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--producer-fixture':
        run_file_producer(sys.argv[2])
    else:
        unittest.main(verbosity=2)
