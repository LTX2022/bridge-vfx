"""Authenticated process evidence through the real writer receipt implementation.

Only OS observation and native Houdini APIs are explicit boundaries here. These
fixtures never authorize or execute a commercial host.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for name in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT/'packages'/name/'src'))
sys.path.insert(0, str(ROOT/'tests/unit'))
from dcc_task_runtime import owned_process, process_image
from dcc_task_runtime.artifact_registry import ArtifactError, ArtifactRegistry
from dcc_task_runtime.platform_support import ensure_private_directory
from houdini_bridge import client, render_writer_facts as writer
from test_render_writer_facts import RenderWriterFactsTests


class WriterProcessReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RenderWriterFactsTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.record = self.fixture.record
        self.expected = {
            'schema':process_image.EXECUTABLE_SCHEMA, 'platform':'darwin', 'version':'21.0.631',
            'image':{'path':'/explicit/software-boundary/python', 'sha256':'a'*64,
                'stat':{'device':1, 'inode':2, 'size':10, 'mtime_ns':1, 'ctime_ns':1,
                    'mode':stat.S_IFREG|0o700, 'uid':501, 'gid':20, 'links':1}}}
        self.anchor = {'schema':process_image.OBSERVATION_SCHEMA, 'platform':'darwin',
            'pid':12345, 'parent_pid':1, 'birth':'2026-10-16 01:00:00.123 +0000',
            'load_address':'0x100000000', 'image':copy.deepcopy(self.expected['image'])}
        current = dict(copy.deepcopy(self.anchor), pid=os.getpid(), parent_pid=12345,
                       birth='2026-10-16 01:00:01.123 +0000')
        self.proof = {'schema':process_image.PROOF_SCHEMA, 'platform':'darwin',
            'expected_executable':copy.deepcopy(self.expected), 'host_anchor':copy.deepcopy(self.anchor),
            'chain':[current, copy.deepcopy(self.anchor)],
            'rechecked_chain':[copy.deepcopy(current), copy.deepcopy(self.anchor)]}
        self.digest = writer._digest(self.expected)
        self.record['host_identity'].update(task_id=self.record['task_id'], version='21.0.631',
                                           writer_executable_sha256=self.digest)
        self.record['supervisor_binding']['identity'] = {
            'task_id':self.record['task_id'], 'launch_nonce':'fixture-not-a-host',
            'writer_executable_sha256':self.digest}
        directory = ensure_private_directory(Path(self.record['supervisor_binding']['directory']))
        key = directory/'receipt.key'
        key.write_bytes(b'explicit-new-software-test-key'); key.chmod(0o600)
        self.started = {'schema':owned_process.SCHEMA, 'event':'started',
            'identity':self.record['supervisor_binding']['identity'], 'pid':12345,
            'writer_process_binding':{'expected_executable':self.expected, 'host_anchor':self.anchor}}
        owned_process._signed_write(directory, self.started)

    def observed(self):
        with mock.patch.object(process_image, 'capture_ancestry', return_value=copy.deepcopy(self.proof)) as capture, \
                mock.patch.object(writer.os, 'getppid', return_value=12345):
            observation = self.fixture.observed()
        self.assertEqual(capture.call_args.args, (self.expected, self.anchor))
        self.assertIsInstance(capture.call_args.kwargs['read_budget'], writer.FileReadBudget)
        return observation

    def validate(self, observed, **kwargs):
        return writer.validate_writer_observation(observed,
            client.render_receipt_digest(client.render_producer_binding(self.record)), 1,
            expected_root=self.fixture.root, host_identity=self.record['host_identity'],
            supervisor_binding=self.record['supervisor_binding'], **kwargs)

    def resign_observation(self, observed):
        directory = Path(observed['directory'])
        import hmac
        encoded = writer._canonical({'body':observed['body'], 'hmac_sha256':hmac.new(
            (directory/'capture.key').read_bytes(), writer._canonical(observed['body']), hashlib.sha256).hexdigest()})
        (directory/'observation.json').write_bytes(encoded)
        observed['receipt_sha256'] = hashlib.sha256(encoded).hexdigest()

    def test_signed_identity_closes_only_process_gap_and_registry_still_refuses(self):
        observed = self.observed()
        body = self.validate(observed)
        self.assertNotIn('WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED', body['missing_facts'])
        self.assertIn('WRITER_BEAUTY_ALPHA_ASSOCIATION_UNOBSERVED', body['missing_facts'])
        self.record['frame_snapshots']['1'] = self.fixture.fixture.snapshot()
        fact = client.collect_render_output_fact(self.record, 1)
        self.record['output_facts'] = {'1':fact}
        terminal = client.render_execution_fact(self.record)
        self.assertEqual(terminal['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(terminal['metadata'], {})
        self.assertNotIn('WRITER_EXECUTABLE_PROCESS_IDENTITY_UNVERIFIED',
                         terminal['completion_metadata_missing_facts'])
        registry = ArtifactRegistry(self.fixture.fixture.root/'registry')
        registry.set_operation_source(lambda operation_id: terminal)
        with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED'):
            registry.register(artifact_id='explicit-software-output', task_id=self.record['task_id'],
                artifact_class='preview_temp', pattern=self.record['output_pattern'], frame_set=[1],
                colorspace='', premultiplied=None, dependencies=self.record['dependencies'],
                operation_id=self.record['request_id'], scene_fingerprint=self.record['scene_fingerprint'],
                receipt_source_files={str(Path(client.__file__).resolve()):
                    hashlib.sha256(Path(client.__file__).read_bytes()).hexdigest()})
        self.assertEqual(registry.history('explicit-software-output'), [])

    def test_signed_start_missing_tampered_or_foreign_is_refused_before_dispatch(self):
        directory = Path(self.record['supervisor_binding']['directory'])
        original = (directory/'started.json').read_bytes()
        for mode in ('missing', 'signature', 'anchor_pid', 'expected', 'binding_error'):
            with self.subTest(mode=mode):
                (directory/'started.json').write_bytes(original)
                started = copy.deepcopy(self.started)
                if mode == 'missing':(directory/'started.json').unlink()
                elif mode == 'signature':(directory/'started.json').write_bytes(original+b'broken')
                else:
                    if mode == 'anchor_pid':started['writer_process_binding']['host_anchor']['pid'] += 1
                    if mode == 'expected':started['writer_process_binding']['expected_executable']['image']['sha256'] = 'b'*64
                    if mode == 'binding_error':started['writer_process_binding_error'] = 'denied'
                    owned_process._signed_write(directory, started)
                with self.assertRaises((ValueError, OSError)):
                    with writer.render_writer_frame(self.fixture.node, self.record, 1,
                                                    self.fixture.root, hou_module=self.fixture.hou):
                        self.fail('invalid signed identity dispatched a frame')
        (directory/'started.json').write_bytes(original)

    def test_capture_errors_restore_hooks_and_leave_no_observation(self):
        with mock.patch.object(process_image, 'capture_ancestry', side_effect=process_image.ProcessImageError('denied')):
            with self.assertRaisesRegex(ValueError, 'denied'):
                self.fixture.observed()
        self.assertEqual(self.fixture.parms['husk_postframe'].value, '')
        self.assertEqual(self.fixture.parms['husk_tpostframe'].value, 0)
        self.assertNotIn('writer_observations', self.record)

    def test_unsigned_or_inconsistent_proof_cannot_be_adopted(self):
        observed = self.observed()
        foreign = copy.deepcopy(observed)
        foreign['body']['process_observation']['proof']['chain'][0]['birth'] = '2026-10-16 01:00:02.123 +0000'
        with self.assertRaisesRegex(ValueError, 'authentication'):
            self.validate(foreign)
        self.resign_observation(foreign)
        with self.assertRaises(ValueError):self.validate(foreign)
        original = self.observed()
        original['body']['process_observation']['pid'] += 1
        self.resign_observation(original)
        with self.assertRaisesRegex(ValueError, 'fields differ'):self.validate(original)

    def test_process_proof_requires_external_frozen_producer_and_original_start(self):
        observed = self.observed()
        with self.assertRaisesRegex(ValueError, 'frozen producer'):
            writer.validate_writer_observation(observed,
                client.render_receipt_digest(client.render_producer_binding(self.record)), 1,
                expected_root=self.fixture.root)
        started = copy.deepcopy(self.started)
        started['writer_process_binding']['host_anchor']['birth'] = '2026-10-16 00:00:00.123 +0000'
        owned_process._signed_write(Path(self.record['supervisor_binding']['directory']), started)
        with self.assertRaisesRegex(ValueError, 'signed producer start'):self.validate(observed)

    def test_plugin_launch_identity_rechecks_signed_anchor_and_source_file(self):
        tree = ast.parse((ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_task_writer_process_identity')
        namespace = {'os':os, 'json':json, 'hashlib':hashlib, 'time':__import__('time')}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<plugin identity helper>', 'exec'), namespace)
        environment = {'BRIDGE_OWNED_SUPERVISOR_DIR':self.record['supervisor_binding']['directory'],
            'BRIDGE_OWNED_SUPERVISOR_IDENTITY':json.dumps(self.record['supervisor_binding']['identity'])}
        identity = dict(self.record['host_identity'])
        with mock.patch.dict(os.environ, environment), \
                mock.patch.object(process_image, 'freeze_executable', return_value=copy.deepcopy(self.expected)), \
                mock.patch.object(process_image, 'observe_process', return_value=copy.deepcopy(self.anchor)):
            self.assertEqual(namespace['_task_writer_process_identity'](self.expected, identity), identity)
            with mock.patch.object(process_image, 'observe_process', return_value=dict(self.anchor, birth='different')):
                with self.assertRaisesRegex(ValueError, 'anchor differs'):
                    namespace['_task_writer_process_identity'](self.expected, identity)


if __name__ == '__main__':
    unittest.main()
