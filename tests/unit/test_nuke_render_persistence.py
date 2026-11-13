# -*- coding: utf-8 -*-
"""T06: Nuke render records are persistent, fresh and cancellable.

- A render record survives a host process restart (status/cancel recover it
  from disk, including the installation slot reservation).
- Completion is judged by existence AND size AND freshness: frames that
  predate the render never satisfy the verification.
- Cancel request and confirmed stop are recorded separately; the slot is
  released only after the stop is confirmed by observation.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
WORKER_SCRIPT = ROOT / "packages/nuke-bridge/src/nuke_bridge/owned_render_worker.py"
for _src in ("dcc-task-runtime", "nuke-bridge", "houdini-bridge", "vfx-pipeline"):
    _p = ROOT / "packages" / _src / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from vfx_pipeline.graph_scheduler import GraphScheduler  # noqa: E402
from dcc_task_runtime.exr_codec import encode_tiny_exr  # noqa: E402


def _load_addon():
    path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("bridge_test_render_persistence_addon", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeHandle:
    """Popen-like handle with faithful async termination semantics."""

    def __init__(self):
        self.pid = 424242
        self._running = True
        self.terminate_called = False

    def poll(self):
        return None if self._running else 0

    def terminate(self):
        # SIGTERM has been SENT; the process exits asynchronously
        self.terminate_called = True


class _FakeKnob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def isAnimated(self): return False

    def hasExpression(self): return False


class _FakeRoot:
    def __init__(self, name):
        self._name = name
        self._first = _FakeKnob(1)
        self._last = _FakeKnob(4)

    def name(self):
        return self._name

    def __getitem__(self, key):
        return self._first if key == "first_frame" else self._last


class _FakeWrite:
    def __init__(self, pattern):
        self._pattern = pattern

    def name(self):
        return "Write1"

    def Class(self):
        return "Write"

    def knob(self, key):
        values = {'file': self._pattern, 'colorspace': 'linear', 'premultiplied': True, 'raw': False}
        return _FakeKnob(values[key]) if key in values else None

    def __getitem__(self, key):
        knob = self.knob(key)
        if knob is None: raise KeyError(key)
        return knob


class NukeRenderPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="nuke-render-persist-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.scheduler = GraphScheduler(self.tmp / "scheduler")
        self.handle = None
        self.addon = _load_addon()
        self.previous_scheduler = self.addon._NUKE_SCHEDULER
        self.previous_registry = getattr(self.addon, "_NUKE_ARTIFACT_REGISTRY", None)
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = None
        self.addon._NUKE_SCHEDULER = self.scheduler
        self.previous_launcher = self.addon._NUKE_BACKGROUND_LAUNCHER
        self.addon._NUKE_BACKGROUND_LAUNCHER = self._launch_background
        self.previous_records_dir = self.addon._RENDER_RECORDS_DIR
        self._previous_secret = os.environ.get('HOUDINI_BRIDGE_APPROVAL_SECRET')
        os.environ['HOUDINI_BRIDGE_APPROVAL_SECRET'] = "unit-test-control-secret-0123456789abcdef"
        self.addCleanup(self._restore_secret)
        self.addon._RENDER_RECORDS_DIR = self.tmp / "nuke_renders"
        self.addCleanup(self._restore)
        self.pattern = str(self.tmp / "render.%03d.exr")
        self.previous_nuke = sys.modules.get("nuke")
        def _script_save():
            (self.tmp / "script.nk").write_text("# frozen software test script\n", encoding="utf-8")

        fake_nuke = types.SimpleNamespace(
            root=lambda: _FakeRoot(str(self.tmp / "script.nk")),
            node=lambda name: _FakeWrite(self.pattern),
            toNode=lambda name: _FakeWrite(self.pattern),
            scriptSave=_script_save,
            executeBackgroundNuke=self._launch_background,
        )
        sys.modules["nuke"] = fake_nuke

    def _launch_background(self, task_id, script_path, node_name, first, last):
        # owned_subprocess backend fake: Popen-like handle + persisted identity
        self.handle = _FakeHandle()
        return {"pid": self.handle.pid, "kind": "owned_render_subprocess", "handle": self.handle}

    def _restore(self):
        self.addon._RENDER_RECORDS_DIR = self.previous_records_dir
        self.addon._NUKE_BACKGROUND_LAUNCHER = self.previous_launcher
        self.addon._NUKE_SCHEDULER = self.previous_scheduler
        self.addon._RENDER_HANDLES.clear()
        if hasattr(self.addon, "_NUKE_ARTIFACT_REGISTRY"):
            self.addon._NUKE_ARTIFACT_REGISTRY = self.previous_registry

    def _restore_secret(self):
        if self._previous_secret is None:
            os.environ.pop('HOUDINI_BRIDGE_APPROVAL_SECRET', None)
        else:
            os.environ['HOUDINI_BRIDGE_APPROVAL_SECRET'] = self._previous_secret
        if self.previous_nuke is None:
            sys.modules.pop("nuke", None)
        else:
            sys.modules["nuke"] = self.previous_nuke

    def _sign(self, action, payload):
        import hmac as _hm
        body = json.dumps({"action": action, **payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return _hm.new(b"unit-test-control-secret-0123456789abcdef", body.encode(), hashlib.sha256).hexdigest()

    def _write_fresh_frames(self, frames=(1, 2, 3, 4)):
        for frame in frames:
            path = Path(self.pattern % frame)
            path.write_bytes(encode_tiny_exr(float(frame)))

    def _age_files(self, seconds: float) -> None:
        for path in self.tmp.glob("render.*.exr"):
            old = path.stat().st_mtime - seconds
            os.utime(path, (old, old))

    def _selected_input_render(self, output_verification=None, claimed_grade=None, replace_input_during_execute=False, owner_task_id="test-owner", request_id="inherit-project-color"):
        from nuke_bridge.operation_receipts import capture_completion_metadata
        source_pattern = str(self.tmp / 'source.%03d.exr')
        Path(source_pattern % 1).write_bytes(encode_tiny_exr(1.0))
        color = {'schema':'bridge.project-color/1.0', 'project_id':'test-project',
                 'revision':1, 'colorspace':'linear', 'source':'human_project_selection'}
        snapshots = self.addon._snapshot_frames(source_pattern, [1])
        metadata = capture_completion_metadata({'frame_set':[1], 'pattern':source_pattern,
            'project_color':color, 'native_output_settings':{'colorspace':'linear', 'premultiplied':True}}, snapshots)
        source_fact = {'task_id':'test-owner', 'state':'COMPLETED', 'frame_set':[1],
            'output_pattern':source_pattern, 'started_at_epoch':1.0,
            'scene_fingerprint':'source-scene', 'dependencies':['source-scene'],
            'frame_snapshots':snapshots, 'metadata':metadata, 'project_color':color,
            'completion_metadata_status':'AVAILABLE', 'operation_receipt_sha256':'a'*64}
        if output_verification is not None:
            source_fact['output_verification'] = output_verification
            for image in metadata.values(): image['output_verification'] = output_verification
        registry = self.addon._nuke_artifact_registry()
        registry.set_operation_source(lambda operation: source_fact if operation == 'source-op'
                                      else self.addon._nuke_operation_fact(operation))
        registry.register(artifact_id='source', task_id='test-owner', artifact_class='preview_temp',
            pattern=source_pattern, frame_set=[1], colorspace='linear', premultiplied=True,
            operation_id='source-op', dependencies=['source-scene'])
        def execute(write, first, last):
            self._write_fresh_frames(range(first,last+1))
            if replace_input_during_execute:
                Path(source_pattern % 1).write_bytes(encode_tiny_exr(.25))
        sys.modules['nuke'].execute = execute
        result = self.addon.dispatch('render_write', {'node':'Write1', 'background':False,
            'frame_set':[1], 'pattern':self.pattern, 'request_id':request_id,
            'colorspace':'linear', 'premultiplied':True,
            'output_binding':{'source':'controller', 'task_id':'test-owner', 'node':'Write1',
                'pattern':self.pattern, 'frames':[1],
                **({'output_verification': claimed_grade} if claimed_grade is not None else {}),
                'input_binding':{'kind':'artifact_read', 'artifact_id':'source', 'owner_task_id':owner_task_id}}})
        record = self.addon._RENDERS[result['task_id']]
        contract = record['input_contract']
        self.assertEqual(fact_contract_sha := self.addon._canonical_payload_sha256(contract), record['execution_fact']['input_contract_sha256'])
        self.assertEqual(contract['registry_inputs']['source']['version'], registry.lookup('source')['version'])
        self.assertEqual(contract['input_binding']['schema'], 'bridge.nuke.agent-input-binding/1.0')
        self.assertEqual(contract['input_binding']['frozen_inputs_manifest'][0]['frames'][0]['sha256'], snapshots['1']['sha256'])
        fact = self.addon._nuke_operation_fact(result['task_id'])
        self.assertEqual(fact.get('project_color'), color, repr(fact))
        self.assertEqual(fact['metadata']['1']['project_color'], color)
        self.assertEqual(fact['formal_receipt']['request']['project_color'], color)
        self.assertEqual(fact['formal_receipt']['request']['input_contract_sha256'], fact_contract_sha)
        self.assertEqual(registry.lookup('nuke-render-'+result['task_id'])['project_color'], color)
        if output_verification is not None:
            self.assertEqual(fact['output_verification'], output_verification)
            self.assertEqual(fact['metadata']['1']['output_verification'], output_verification)
            receipt = fact['formal_receipt']
            self.assertEqual(receipt['request']['output_verification'], output_verification)
            self.assertEqual(receipt['execution_fact']['output_verification'], output_verification)
            self.assertEqual(registry.lookup('nuke-render-'+result['task_id'])['output_verification'], output_verification)
        return fact

    def test_selected_input_color_is_inherited_when_output_binding_omits_it(self):
        self._selected_input_render()

    @staticmethod
    def _controlled_grade():
        return {'schema':'bridge.output-verification-provenance/1.0',
            'verification_basis':'controlled_output_v1', 'native_internal_status':'NOT_OBSERVED',
            'native_internal_unknowns':['native writer close'],
            'origin_verification_operation_id':'verify-source', 'origin_render_operation_id':'render-source',
            'source_receipt_sha256':'c'*64, 'stopped_receipt_sha256':'d'*64, 'evidence_source':'software_test'}

    def test_controlled_grade_survives_nuke_without_caller_binding_grade(self):
        fact = self._selected_input_render(self._controlled_grade())
        self.assertNotIn('output_verification', fact['formal_receipt']['request']['input_binding'])

    def test_same_request_rejects_new_ledger_version_for_identical_input_bytes(self):
        original = self._selected_input_render(self._controlled_grade())
        original_task = self.addon._RENDERS[original['operation_id']]
        old_version = original_task['input_contract']['registry_inputs']['source']['version']
        with self.assertRaisesRegex(ValueError, 'CONTENT_CHANGED'):
            self._selected_input_render(self._controlled_grade())
        fresh = self._selected_input_render(self._controlled_grade(), request_id='inherit-new-ledger-version')
        fresh_task = self.addon._RENDERS[fresh['operation_id']]
        self.assertGreater(fresh_task['input_contract']['registry_inputs']['source']['version'], old_version)
        self.assertEqual(original_task['input_binding'], fresh_task['input_binding'])
        self.assertNotEqual(original_task['request_sha256'], fresh_task['request_sha256'])

    def test_registered_artifact_read_rejects_source_replacement_and_foreign_owner(self):
        with self.assertRaisesRegex(ValueError, 'INPUT_SOURCE_HASH_MISMATCH'):
            self._selected_input_render(self._controlled_grade(), replace_input_during_execute=True)
        record = next(iter(self.addon._RENDERS.values()))
        self.assertIsNone(self.addon._nuke_artifact_registry().lookup('nuke-render-'+record['task_id']))
        with self.assertRaisesRegex(ValueError, 'OWNER_MISMATCH|INPUT_SOURCE_HASH_MISMATCH'):
            self._selected_input_render(self._controlled_grade(), owner_task_id='foreign-owner')

    def test_caller_cannot_change_registered_controlled_grade(self):
        grade = self._controlled_grade()
        with self.assertRaisesRegex(ValueError, 'OUTPUT_VERIFICATION_INPUT_MISMATCH'):
            self._selected_input_render(
                grade, {**grade, 'native_internal_unknowns':['forged']})

    def test_graded_completion_cannot_fall_back_to_ungraded_legacy(self):
        task = {'output_verification': self._controlled_grade(),
                'execution_fact': {'completion_metadata_status':'UNAVAILABLE_NATIVE_WRITE_SETTINGS'}}
        with self.assertRaisesRegex(ValueError, 'OUTPUT_VERIFICATION_COMPLETION_REQUIRED'):
            self.addon._register_render_artifact(task)

    def test_mixed_grades_or_graded_and_legacy_input_are_rejected(self):
        grade = self._controlled_grade()
        for second in (None, {**grade, 'origin_render_operation_id':'another-render'}):
            registry = mock.Mock()
            registry.lookup.side_effect = [
                {'task_id':'owner', 'output_verification':grade},
                {'task_id':'owner', **({'output_verification':second} if second else {})}]
            registry.verify.return_value = {'usable': True}
            with self.subTest(second=second), mock.patch.object(self.addon, '_nuke_artifact_registry', return_value=registry):
                with self.assertRaisesRegex(ValueError, 'OUTPUT_VERIFICATION_INPUT_MISMATCH'):
                    self.addon._nuke_render_operation('software_grade_probe', 'owner', _FakeWrite(self.pattern), 1, 1, 1,
                        input_binding={'owner_task_id':'owner', 'frozen_inputs_manifest':[
                            {'artifact_id':'first'}, {'artifact_id':'second'}]})


    def test_human_color_capture_preserves_provenance_and_rejects_write_mismatch(self):
        from nuke_bridge.operation_receipts import capture_completion_metadata
        self._write_fresh_frames([1])
        color = {'schema':'bridge.project-color/1.0', 'project_id':'test-project',
                 'revision':1, 'colorspace':'linear', 'source':'human_project_selection'}
        snapshot = self.addon._snapshot_frames(self.pattern, [1])
        task = {'frame_set':[1], 'pattern':self.pattern, 'project_color':color,
                'native_output_settings':{'colorspace':'linear', 'premultiplied':True}}
        metadata = capture_completion_metadata(task, snapshot)
        self.assertEqual(metadata['1']['project_color'], color)
        self.assertEqual(metadata['1']['color_metadata_source'], 'human_project_selection')
        self.assertIs(metadata['1']['premultiplied'], True)
        task['native_output_settings']['colorspace'] = 'other'
        with self.assertRaisesRegex(ValueError, 'PROJECT_COLOR_OUTPUT_MISMATCH'):
            capture_completion_metadata(task, snapshot)

    def test_typed_completed_operation_uses_real_source_ledger_and_fails_closed(self):
        from dcc_task_runtime.exr_codec import read_exr
        calls = []
        def execute(write, first, last):
            calls.append((first, last)); self._write_fresh_frames(range(first, last + 1))
        sys.modules['nuke'].execute = execute
        result = self.addon.dispatch('render_write', {'node':'Write1', 'background':False,
            'frame_set':[1,3], 'request_id':'typed-native-completion',
            'colorspace':'caller-unverified-color', 'premultiplied':False})
        operation = result['task_id']; producer = self.addon._nuke_operation_fact(operation)
        self.assertEqual(producer['operation_id'], operation)
        self.assertTrue(producer['stop_confirmed'])
        self.assertEqual(producer['execution_kind'], 'synchronous_nuke_execute')
        artifact = self.addon._nuke_artifact_registry().lookup('nuke-render-' + operation)
        self.assertEqual(artifact['payload']['completion_metadata'], producer['metadata'])
        from dcc_task_runtime.denoise_blend import _dependency
        _dependency(artifact, {'source_artifact_id':artifact['artifact_id'],'source_version':artifact['version'],
            'source_operation_id':operation,'task_id':producer['task_id'],'scene_fingerprint':producer['scene_fingerprint'],
            'frame':1,'artifact_source':self.addon._nuke_artifact_registry().lookup,
            'operation_source':self.addon._nuke_operation_fact},denoised=False)
        for frame in (1,3):
            meta = producer['metadata'][str(frame)]; actual = read_exr(self.pattern % frame, with_pixels=False)
            for key in ('width','height','channels','channel_layout','pixel_count','sample_count'):
                self.assertEqual(meta[key], actual[key])
            self.assertEqual(meta['sha256'], producer['frame_snapshots'][str(frame)]['sha256'])
            self.assertEqual(meta['bytes'], producer['frame_snapshots'][str(frame)]['bytes'])
            self.assertEqual(meta['colorspace'], 'linear'); self.assertIs(meta['premultiplied'], True)
            self.assertNotIn('rows',meta)
        from nuke_bridge.operation_receipts import completed_operation_projection, _typed_completion_valid
        human_receipt = json.loads(json.dumps(producer['formal_receipt']))
        color = {'schema':'bridge.project-color/1.0', 'project_id':'test-project',
                 'revision':1, 'colorspace':'linear', 'source':'human_project_selection'}
        human_receipt['execution_fact']['project_color'] = color
        for image in human_receipt['execution_fact']['completion_metadata'].values():
            image.update(project_color=dict(color), color_metadata_source='human_project_selection')
        self.assertTrue(_typed_completion_valid(human_receipt))
        human_receipt['execution_fact']['completion_metadata']['1']['project_color']['revision'] = 2
        self.assertFalse(_typed_completion_valid(human_receipt))
        for defect in ('unknown_stop', 'wrong_operation', 'no_start', 'corrupt_receipt'):
            receipt = json.loads(json.dumps(producer['formal_receipt']))
            if defect == 'unknown_stop': receipt['execution_fact']['stop_confirmed'] = False
            elif defect == 'wrong_operation': receipt['operation_id'] = 'another-operation'
            elif defect == 'no_start': receipt['execution_fact']['verification']['ok'] = False
            else: receipt['operation_receipt_sha256'] = '0' * 64
            with self.subTest(defect=defect):
                self.assertIsNone(completed_operation_projection(receipt, producer))
        original_metadata = json.loads(json.dumps(producer['metadata']))
        producer['execution_fact']['completion_metadata']['1']['channels'][0] = 'caller-mutated-copy'
        self.assertEqual(self.addon._nuke_operation_fact(operation)['metadata'], original_metadata)
        def consume_copy(path, **kwargs):
            # The source changes after SHA validation; decoding must consume the
            # verified copy, never reopen the public output path for pixels.
            if kwargs.get('with_pixels'):
                self.assertNotEqual(str(path),self.pattern % 1)
                Path(self.pattern % 1).write_bytes(encode_tiny_exr(7.))
            return read_exr(path, **kwargs)
        with mock.patch('dcc_task_runtime.artifact_registry.read_exr',side_effect=consume_copy):
            consumed = self.addon._nuke_artifact_registry().read_frame(artifact['artifact_id'],1)
        self.assertEqual(consumed['sha256'],producer['frame_snapshots']['1']['sha256'])
        self.assertEqual(consumed['image']['rows'][0]['channels']['R'],[1.])
        changed_producer=self.addon._nuke_operation_fact(operation)
        self.assertNotEqual(changed_producer['completion_metadata_status'],'AVAILABLE')
        self.assertEqual(changed_producer['execution_fact']['completion_metadata'],original_metadata)
        with self.assertRaisesRegex(Exception,'COMPLETION_BYTES_UNAVAILABLE'):
            self.addon._nuke_artifact_registry().lookup(artifact['artifact_id'])
        with self.assertRaises(Exception):self.addon._nuke_artifact_registry().read_frame(artifact['artifact_id'],1)
        with self.assertRaisesRegex(Exception, 'OPERATION_OUTPUT_MISMATCH'):
            self.addon._nuke_artifact_registry().register(artifact_id='wrong-output',task_id=producer['task_id'],
                artifact_class='preview_temp',pattern=str(self.tmp/'different.%03d.exr'),frame_set=[1,3],operation_id=operation)
        self.assertEqual(len(calls),2)

    def test_typed_completion_restart_ledger_retry_never_recaptures_or_executes(self):
        calls = []
        def execute(write, first, last):
            calls.append((first,last)); self._write_fresh_frames(range(first,last+1))
        sys.modules['nuke'].execute = execute
        registry=self.addon._nuke_artifact_registry(); register=registry.register
        source = self.addon._nuke_operation_fact
        for window in ('register_entry_replacement','after_fact_callback'):
            def race(**kwargs):
                Path(self.pattern % 1).write_bytes(encode_tiny_exr(83.))
                return register(**kwargs)
            def fact_then_replace(operation):
                frozen = source(operation)
                Path(self.pattern % 1).write_bytes(encode_tiny_exr(84.))
                return frozen
            with self.subTest(window=window):
                registry.set_operation_source(fact_then_replace if window=='after_fact_callback' else source)
                register_context = (mock.patch.object(registry,'register',side_effect=race)
                    if window=='register_entry_replacement' else mock.patch.object(registry,'register',wraps=register))
                with register_context, self.assertRaisesRegex(ValueError,'COMPLETION_'):
                    self.addon.dispatch('render_write',{'node':'Write1','background':False,'frame_set':[1],
                        'request_id':'typed-register-race-' + window})
                record=next(iter(self.addon._RENDERS.values()))
                self.assertEqual(record['state'],'NEEDS_RECONCILE')
                self.assertNotEqual(source(record['task_id'])['completion_metadata_status'],'AVAILABLE')
                self.assertEqual(registry.history('nuke-render-'+record['task_id']),[])
            self.addon._RENDERS.clear();calls.clear()
        registry.set_operation_source(source)
        request = {'node':'Write1','background':False,'frame_set':[1], 'request_id':'typed-ledger-restart'}
        with mock.patch.object(self.addon,'_register_render_artifact',side_effect=OSError('controlled ledger outage')):
            with self.assertRaises(OSError): self.addon.dispatch('render_write',request)
        record = next(iter(self.addon._RENDERS.values())); frozen = json.loads(json.dumps(record['execution_fact']['completion_metadata']))
        self.assertEqual(record['state'],'NEEDS_RECONCILE'); self.assertTrue(record['slot_released'])
        self.addon._RENDERS.clear(); self.addon._RENDER_HANDLES.clear()
        with mock.patch.object(self.addon,'_capture_render_completion_metadata',side_effect=AssertionError('metadata recapture forbidden')):
            result = self.addon.dispatch('render_write',request)
        self.assertEqual(result['state'],'COMPLETED'); self.assertEqual(calls,[(1,1)])
        self.assertEqual(result['execution_fact']['completion_metadata'], frozen)
        self.assertEqual(self.addon._nuke_artifact_registry().lookup('nuke-render-'+result['task_id'])['payload']['completion_metadata'],frozen)
        record = self.addon._RENDERS[result['task_id']]
        record['execution_fact'].pop('completion_metadata'); record['execution_fact'].pop('completion_metadata_status')
        legacy = self.addon._nuke_operation_fact(result['task_id'])
        self.assertEqual(legacy['completion_metadata_status'],'UNAVAILABLE_LEGACY')
        self.assertNotIn('1',legacy['metadata'])

    def test_typed_owned_worker_requires_actual_signed_stop_and_capture_byte_identity(self):
        source = str(self.tmp/'owned-input.%03d.exr')
        for frame in (1,3):Path(source % frame).write_bytes(encode_tiny_exr(float(frame)))
        snapshot_settings={'colorspace':'linear','premultiplied':True,'raw':False}
        def save():
            (self.tmp/'script.nk').write_text(json.dumps({'schema':'bridge.software_nuke_snapshot/1',
                'root':{'first_frame':1,'last_frame':3}, 'nodes':{
                    'Read1':{'class':'Read','file':source,'inputs':[]},
                    'Write1':{'class':'Write','file':self.pattern,'inputs':['Read1'],
                        'knobs':dict(snapshot_settings)}}}))
        sys.modules['nuke'].scriptSave = save
        handles = []
        route = {'executable':sys.executable, 'supervisor_executable':sys.executable,'software_api':True,
            'worker_script':str(WORKER_SCRIPT)}
        with mock.patch.object(self.addon,'_NUKE_BACKGROUND_ROUTE',route):
            result=self.addon.dispatch('render_write',{'node':'Write1','background':True,'frame_set':[1,3],
                'request_id':'typed-owned-fixed-worker','budget_seconds':8.5})
        handles.append(self.addon._RENDER_HANDLES[result['task_id']])
        self.assertEqual(result['budget_seconds'],8.5)
        self.assertEqual(handles[0].started['budget_seconds'],8.5)
        self.addCleanup(lambda: [(h.terminate(),h.wait(timeout=10)) for h in handles if h.returncode is None])
        self.assertEqual(handles[0].wait(timeout=15),0)
        completed=self.addon.dispatch('render_status',{'task_id':result['task_id']})
        producer=self.addon._nuke_operation_fact(result['task_id'])
        self.assertEqual(completed['state'],'COMPLETED')
        self.assertEqual(producer['execution_kind'],'owned_subprocess');self.assertTrue(producer['stop_confirmed'])
        self.assertEqual(producer['completion_metadata_status'],'AVAILABLE')
        self.assertEqual(producer['formal_receipt']['execution_fact']['worker_receipt']['execute_calls'],[1,3])
        record=self.addon._RENDERS[result['task_id']]; process=record['process']
        with self.subTest(window='legacy_owned_receipt_retry'):
            observed = record['execution_fact']['worker_receipt'].pop('write_readback')
            legacy = self.addon._nuke_operation_fact(result['task_id'])
            self.assertEqual(legacy['completion_metadata_status'],'UNAVAILABLE_LEGACY_WORKER_READBACK')
            self.assertNotIn('1',legacy['metadata'])
            self.assertIsNotNone(self.addon._register_render_artifact(record))
            record['execution_fact']['worker_receipt']['write_readback'] = observed
        stopped=Path(process['supervisor_directory'])/'stopped.json'; original=stopped.read_bytes()
        envelope=json.loads(original);envelope['signature']='0'*64;stopped.write_text(json.dumps(envelope))
        invalid=self.addon._nuke_operation_fact(result['task_id'])
        self.assertFalse(invalid['stop_confirmed']);self.assertNotIn('1',invalid['metadata'])
        self.assertIsNone(invalid['formal_receipt'])
        with self.assertRaisesRegex(ValueError,'COMPLETION_METADATA_UNVERIFIED'):
            self.addon._register_render_artifact(record)
        stopped.write_bytes(original)
        start=Path(process['supervisor_directory'])/'started.json'; started_bytes=start.read_bytes();start.unlink()
        self.assertFalse(self.addon._nuke_operation_fact(result['task_id'])['stop_confirmed'])
        start.write_bytes(started_bytes)
        identity=process['supervisor_identity'];process['supervisor_identity']={**identity,'operation_id':'foreign'}
        self.assertFalse(self.addon._nuke_operation_fact(result['task_id'])['stop_confirmed'])
        process['supervisor_identity']=identity
        from nuke_bridge.operation_receipts import capture_completion_metadata
        frozen=json.loads(json.dumps(record['execution_fact']['completion_metadata']))
        Path(self.pattern % 1).write_bytes(encode_tiny_exr(19.))
        with self.assertRaisesRegex(ValueError,'COMPLETION_OUTPUT_DRIFT'):
            self.addon._register_render_artifact(record)
        with self.assertRaisesRegex(ValueError,'COMPLETION_OUTPUT_CHANGED'):
            capture_completion_metadata(record,record['execution_fact']['frame_snapshots'])
        self.assertEqual(record['execution_fact']['completion_metadata'],frozen)
        snapshot_settings.update(colorspace='sRGB',premultiplied=False,raw=True)
        with mock.patch.object(self.addon,'_NUKE_BACKGROUND_ROUTE',route):
            mismatch=self.addon.dispatch('render_write',{'node':'Write1','background':True,'frame_set':[1,3],
                'request_id':'typed-snapshot-live-mismatch'})
        handles.append(self.addon._RENDER_HANDLES[mismatch['task_id']])
        self.assertEqual(handles[-1].wait(timeout=15),0)
        mismatch=self.addon.dispatch('render_status',{'task_id':mismatch['task_id']})
        with self.subTest(window='snapshot_write_differs_from_live'):
            self.assertNotEqual(mismatch['execution_fact']['completion_metadata_status'],'AVAILABLE')
            actual=mismatch['execution_fact']['worker_receipt']['write_readback']['settings']
            self.assertEqual(actual['colorspace'],'sRGB');self.assertIs(actual['premultiplied'],False);self.assertIs(actual['raw'],True)
            self.assertNotIn('1',self.addon._nuke_operation_fact(mismatch['task_id'])['metadata'])
        corrupt=self.tmp/'corrupt.exr';corrupt.write_bytes(b'not-an-exr')
        broken={**record,'frame_set':[1],'pattern':str(corrupt)}
        with self.assertRaises(ValueError):capture_completion_metadata(broken,{'1':self.addon._artifact(corrupt)})

    def test_actual_supervisor_cancel_race_requires_signed_stop_reason(self):
        from dcc_task_runtime.owned_process import launch
        for window in ('cancel_return', 'later_status', 'bad_signature', 'wrong_identity', 'actual_cancel', 'budget_cancel'):
            with self.subTest(window=window):
                release_path = self.tmp / ('release-' + window)
                owned = {}
                outer = self
                def launcher(task_id, script_path, node_name, first, last):
                    identity = {'task_id':task_id,'operation_id':task_id,'launch_nonce':window}
                    directory = outer.addon._render_records_dir() / (task_id+'.supervisor')
                    executable = getattr(sys, '_base_executable', None) or sys.executable
                    command = [executable, '-c',
                        'from pathlib import Path\nimport sys,time\n'
                        'release=Path(sys.argv[1])\n'
                        'while not release.exists(): time.sleep(.01)\n', str(release_path)]
                    handle = launch(command,directory=directory,identity=identity,supervisor_executable=executable,budget_seconds=.2 if window == 'budget_cancel' else 120)
                    owned.update(handle=handle,directory=directory,identity=identity)
                    outer.addCleanup(lambda: (handle.terminate(),handle.wait(timeout=10)) if handle.returncode is None else None)
                    class RaceHandle:
                        pid = handle.pid
                        hidden = False
                        terminated = False
                        def poll(self):
                            if window == 'budget_cancel' and not self.terminated:return None
                            if self.hidden:
                                self.hidden = False
                                return None
                            return handle.poll()
                        @property
                        def returncode(self): return handle.returncode
                        def terminate(self):
                            if window == 'budget_cancel':
                                outer.assertNotEqual(handle.wait(timeout=10),0)
                                outer.assertEqual(handle.receipt()['stop_reason'],'TIME_BUDGET_EXCEEDED')
                                self.terminated=True;handle.terminate();return
                            release_path.write_bytes(b'x')
                            outer.assertEqual(handle.wait(timeout=10),0)
                            outer.assertIsNone(handle.receipt()['stop_reason'])
                            handle.terminate()
                            if window == 'later_status': self.hidden = True
                            if window == 'wrong_identity':
                                outer.addon._RENDERS[task_id]['process']['supervisor_identity'] = {**identity,'operation_id':'other-operation'}
                            if window == 'bad_signature':
                                path = directory/'stopped.json'
                                envelope = json.loads(path.read_text()); envelope['signature'] = '0'*64
                                path.write_text(json.dumps(envelope))
                    return {'pid':handle.pid,'kind':'owned_render_subprocess','handle':handle if window == 'actual_cancel' else RaceHandle(),
                            'supervisor_directory':str(directory),'supervisor_identity':identity}
                with mock.patch.object(self.addon,'_NUKE_BACKGROUND_LAUNCHER',side_effect=launcher):
                    started = self.addon.dispatch('render_write',{'node':'Write1','background':True})
                self._write_fresh_frames()
                result = self.addon.dispatch('render_cancel',{'task_id':started['task_id']})
                if window == 'later_status':
                    self.assertEqual(result['state'],'CANCEL_PENDING')
                    result = self.addon.dispatch('render_status',{'task_id':started['task_id']})
                if window == 'actual_cancel':
                    owned['handle'].wait(timeout=10)
                    result = self.addon.dispatch('render_status',{'task_id':started['task_id']})
                    self.assertEqual(owned['handle'].receipt()['stop_reason'],'CANCEL_REQUESTED')
                    self.assertEqual(result['state'],'CANCELLED')
                elif window == 'budget_cancel':
                    self.assertEqual(result['state'],'FAILED')
                    self.assertEqual(result['supervisor_stop_reason'],'TIME_BUDGET_EXCEEDED')
                    self.assertTrue(result.get('stop_confirmed'))
                    self.assertEqual(self.scheduler.snapshot()['active'],0)
                elif window in {'bad_signature','wrong_identity'}:
                    self.assertEqual(result['state'],'NEEDS_RECONCILE')
                    self.assertFalse(result.get('slot_released',False))
                    self.assertEqual(self.scheduler.snapshot()['active'],1)
                    # This independent failure case owns an isolated scheduler.
                    from vfx_pipeline.graph_scheduler import GraphScheduler
                    self.addon._NUKE_SCHEDULER = self.scheduler = GraphScheduler(self.tmp / ('scheduler-'+window))
                else:
                    self.assertEqual(result['state'],'COMPLETED')
                    self.assertEqual(result['ledger_state'],'REGISTERED')
                    self.assertEqual(self.scheduler.snapshot()['active'],0)

    def test_cancel_observes_natural_exit_before_recording_stop_request(self):
        result = self.addon.dispatch('render_write', {'node':'Write1', 'background':True})
        self._write_fresh_frames()
        self.handle._running = False
        result = self.addon.dispatch('render_cancel', {'task_id':result['task_id']})
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(result['ledger_state'], 'REGISTERED')
        self.assertFalse(self.handle.terminate_called)
        self.assertFalse(result.get('cancel_requested', False))
        self.assertEqual(self.scheduler.snapshot()['active'], 0)
        for state, rc in [('FAILED',7), ('NEEDS_RECONCILE',0)]:
            with self.subTest(natural_state=state):
                result = self.addon.dispatch('render_write',{'node':'Write1','background':True})
                self._write_fresh_frames()
                self.handle.poll = lambda: rc
                if state == 'NEEDS_RECONCILE':
                    with mock.patch.object(self.addon,'_register_render_artifact',side_effect=OSError('ledger offline')):
                        result = self.addon.dispatch('render_cancel',{'task_id':result['task_id']})
                else:
                    result = self.addon.dispatch('render_cancel',{'task_id':result['task_id']})
                self.assertEqual(result['state'],state)
                self.assertFalse(self.handle.terminate_called)
                self.assertFalse(result.get('cancel_requested',False))
                self.assertEqual(self.scheduler.snapshot()['active'],0)

    def test_record_surfaces_freshness_not_mere_existence(self) -> None:
        self._write_fresh_frames()
        self._age_files(120.0)  # frames from a PREVIOUS render
        result = self.addon.dispatch("render_write", {"node": "Write1", "background": True})
        status = self.addon.dispatch("render_status", {"task_id": result["task_id"]})
        self.assertTrue(status["executing"], "pre-existing frames must not count as this render's output")
        self.assertEqual(status["verification"]["stale_frames"], [1, 2, 3, 4])
        self.assertEqual(self.scheduler.snapshot()["active"], 1, "stale files never confirm completion")
        # fresh frames satisfy the artifact condition, but the background
        # process is still running: completion is NOT proven
        self._write_fresh_frames()
        status = self.addon.dispatch("render_status", {"task_id": result["task_id"]})
        self.assertTrue(status["executing"], "outputs alone never prove stopped")
        self.assertFalse(status["process_exited"])
        self.assertIsNone(status["stop_confirmed_at"])
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # process exit evidence completes the render and frees the slot once
        self.handle._running = False
        status = self.addon.dispatch("render_status", {"task_id": result["task_id"]})
        self.assertFalse(status["executing"])
        self.assertTrue(status["stop_confirmed_at"])
        self.assertEqual(self.scheduler.snapshot()["active"], 0)

    def test_record_survives_process_restart_and_keeps_unknown_result_held(self) -> None:
        result = self.addon.dispatch("render_write", {"node": "Write1", "background": True})
        task_id = result["task_id"]
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        self.addon._RENDERS.clear()
        self.addon._RENDER_HANDLES.clear()  # the handle is in-memory process evidence
        status = self.addon.dispatch("render_status", {"task_id": task_id})
        self.assertEqual(status["state"], "NEEDS_RECONCILE",
                         "pid dead without rc after restart: unknown, never treated as stopped")
        self.assertIsNone(status["stop_confirmed_at"])
        self.assertEqual(self.scheduler.snapshot()["active"], 1, "recovered record keeps holding the slot")
        self._write_fresh_frames()
        status = self.addon.dispatch("render_status", {"task_id": task_id})
        self.assertEqual(self.scheduler.snapshot()["active"], 1,
                         "complete frames + unknown rc still needs control recovery")
        # A restart loses the owned process handle.  Signed intent and fresh
        # output are not a stop receipt, so completion recovery is refused and
        # the installation slot remains held for real reconciliation.
        with self.assertRaisesRegex(ValueError, "RECOVER_STOP_UNCONFIRMED"):
            self.addon.dispatch("control.render_resolve", {
                "action": "complete_recovered", "task_id": task_id,
                "authorization": {"verified_by": "controller/recover-1",
                                  "signature": self._sign("complete_recovered", {"task_id": task_id})}})
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        record_path = self.addon._RENDER_RECORDS_DIR / "{}.json".format(task_id)
        self.assertTrue(record_path.is_file())
        final = json.loads(record_path.read_text())
        self.assertEqual(final["state"], "NEEDS_RECONCILE")

    def test_lost_handle_during_cancel_cannot_release_on_pid_absence(self):
        result = self.addon.dispatch("render_write", {"node": "Write1", "background": True})
        task_id = result["task_id"]
        self.addon.dispatch("render_cancel", {"task_id": task_id})
        self.addon._RENDER_HANDLES.clear()
        self.addon._fx_pid_alive = lambda pid: False
        status = self.addon.dispatch("render_status", {"task_id": task_id})
        self.assertFalse(status["stop_confirmed"])
        self.assertEqual(status["state"], "NEEDS_RECONCILE")
        self.assertEqual(self.scheduler.snapshot()["active"], 1)

    def test_cancel_request_and_confirmed_stop_recorded_separately(self) -> None:
        result = self.addon.dispatch("render_write", {"node": "Write1", "background": True})
        task_id = result["task_id"]
        first = self.addon.dispatch("render_cancel", {"task_id": task_id})
        self.assertTrue(first["cancel_requested"])
        self.assertTrue(first["cancel_requested_at"])
        self.assertIsNone(first["stop_confirmed_at"], "stop not yet confirmed")
        self.assertEqual(first["state"], "CANCEL_PENDING")
        self.assertEqual(self.scheduler.snapshot()["active"], 1, "cancel request alone keeps the slot")
        # the cancel sends a REAL stop request to the owned process
        self.assertTrue(first.get("stop_request_sent"), "terminate() must be called on the owned handle")
        # the process has not confirmed exit yet: CANCEL_PENDING + slot held
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        # A bare handle exit has no signed cancellation cause.
        self.handle._running = False
        second = self.addon.dispatch("render_cancel", {"task_id": task_id})
        self.assertIsNone(second["stop_confirmed_at"])
        self.assertEqual(second["state"], "NEEDS_RECONCILE")
        self.assertEqual(self.scheduler.snapshot()["active"], 1)
        record = json_record(self.addon._RENDER_RECORDS_DIR / "{}.json".format(task_id))
        transitions = [(entry["from"], entry["to"]) for entry in record["history"]]
        self.assertIn(("RUNNING", "CANCEL_PENDING"), transitions)
        self.assertIn(("CANCEL_PENDING", "NEEDS_RECONCILE"), transitions)

    def test_recovery_rejects_replaced_outputs_and_keeps_original_snapshot(self) -> None:
        request_id = "ledger-drift-recovery"
        original_register = self.addon._register_render_artifact

        def fail_ledger(task):
            raise RuntimeError("injected ledger outage")

        self.addon._register_render_artifact = fail_ledger
        try:
            result = self.addon.dispatch("render_write", {
                "node": "Write1", "background": True, "request_id": request_id,
            })
            task_id = result["task_id"]
            self._write_fresh_frames()
            self.handle._running = False
            failed = self.addon.dispatch("render_status", {"task_id": task_id})
        finally:
            self.addon._register_render_artifact = original_register
        self.assertEqual(failed["state"], "NEEDS_RECONCILE")
        self.assertTrue(failed["stop_confirmed_at"], "the durable execution fact proves the owned process stopped")
        self.assertTrue(failed["slot_released"], "ledger outage must not strand a verified stopped slot")
        self.assertEqual(self.scheduler.snapshot()["active"], 0,
                         "artifact-ledger outage leaves only a registration retry, not a running job")
        record_path = self.addon._RENDER_RECORDS_DIR / "{}.json".format(task_id)
        original_record = json.loads(record_path.read_text())
        original_snapshots = original_record["execution_fact"]["frame_snapshots"]

        # A different producer replaces every file with fresh-looking bytes.
        self._write_fresh_frames()
        self.addon._RENDERS.clear()
        self.addon._RENDER_HANDLES.clear()
        recovered = self.addon.dispatch("render_write", {
            "node": "Write1", "background": True, "request_id": request_id,
        })
        self.assertTrue(recovered.get("reused"))
        self.assertTrue(recovered.get("active"), recovered)
        self.assertEqual(recovered["state"], "NEEDS_RECONCILE")
        persisted = json.loads(record_path.read_text())
        self.assertEqual(persisted["execution_fact"]["frame_snapshots"], original_snapshots)
        self.assertEqual(persisted.get("ledger_state"), "PENDING")


def json_record(path):
    import json
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
