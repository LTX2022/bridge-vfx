from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from nuke_bridge import owned_render_worker as worker
from vfx_pipeline.workbuddy_assembly import software_nuke_client

ROOT = Path(__file__).resolve().parents[2]


class SoftwareSnapshotTests(unittest.TestCase):
    def test_save_load_restores_parameters_connections_and_frame_range(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            root = Path(temp)
            software_nuke_client(ROOT / 'plugins/nuke/nuke_bridge_addon.py', root)
            api = sys.modules['nuke']
            read, write = api.toNode('Read1'), api.toNode('Write1')
            read['file'].setValue(str(root / 'input.%03d.exr'))
            write['file'].setValue(str(root / 'output.%03d.exr'))
            write.setInput(0, read)
            api.root()['first_frame'].setValue(3)
            path = root / 'scene.nk'
            api.scriptSaveAs(str(path))
            original = path.read_bytes()
            write['file'].setValue('changed.exr')
            write.setInput(0, None)
            api.root()['first_frame'].setValue(9)
            api.scriptSaveAs(str(root / 'changed.nk'))
            self.assertNotEqual(original, (root / 'changed.nk').read_bytes())
            software_nuke_client(ROOT / 'plugins/nuke/nuke_bridge_addon.py', root / 'reopened')
            api = sys.modules['nuke']
            api.scriptOpen(str(path))
            self.assertEqual(api.toNode('Write1')['file'].value(), str(root / 'output.%03d.exr'))
            self.assertIs(api.toNode('Write1').input(0), api.toNode('Read1'))
            self.assertEqual(api.root()['first_frame'].value(), 3)
            self.assertEqual(api.root().name(), str(path.resolve()))

    def test_worker_rejects_fabricated_node_path_and_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            root = Path(temp)
            software_nuke_client(ROOT / 'plugins/nuke/nuke_bridge_addon.py', root)
            api = sys.modules['nuke']; path = root / 'scene.nk'
            pattern = str(root / 'output.%03d.exr')
            api.toNode('Write1')['file'].setValue(pattern)
            api.scriptSaveAs(str(path))
            for node, requested in [('MissingWrite', pattern), ('Write1', str(root / 'wrong.%03d.exr'))]:
                with self.subTest(node=node, pattern=requested), mock.patch.object(worker, '_load_nuke_api', return_value=worker._SoftwareNuke(requested)), mock.patch.object(worker, '_write_receipt'):
                    with self.assertRaises((ValueError, RuntimeError)):
                        worker.main(['worker', str(path), node, '1', '1', requested, '[1]'])
            path.write_text('# invalid fixed-text snapshot')
            with self.assertRaises(ValueError):
                worker._SoftwareNuke(pattern).scriptOpen(str(path))
            self.assertEqual(list(root.glob('*.exr')), [])

    def test_fresh_worker_reads_snapshot_and_executes_exact_frames(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            root = Path(temp)
            software_nuke_client(ROOT / 'plugins/nuke/nuke_bridge_addon.py', root)
            api = sys.modules['nuke']; path = root / 'scene.nk'
            pattern = str(root / 'output.%03d.exr')
            api.toNode('Write1')['file'].setValue(pattern)
            api.toNode('Read1')['file'].setValue(str(root / 'input.%03d.exr'))
            api.toNode('Write1').setInput(0, api.toNode('Read1'))
            from dcc_task_runtime.exr_codec import encode_tiny_exr
            for frame in (1, 3):
                (root / ('input.%03d.exr' % frame)).write_bytes(encode_tiny_exr(float(frame)))
            api.scriptSaveAs(str(path))
            fresh = worker._SoftwareNuke('must-not-use-argument.exr')
            with mock.patch.object(worker, '_load_nuke_api', return_value=fresh), mock.patch.object(worker, '_write_receipt'):
                self.assertEqual(worker.main(['worker', str(path), 'Write1', '1', '3', pattern, '[1,3]']), 0)
            self.assertEqual(fresh.execute_calls, [1, 3])
            self.assertEqual(sorted(p.name for p in root.glob('output.*.exr')), ['output.001.exr', 'output.003.exr'])

    def test_missing_source_and_cyclic_graph_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            root = Path(temp)
            software_nuke_client(ROOT / 'plugins/nuke/nuke_bridge_addon.py', root)
            api = sys.modules['nuke']; path = root / 'scene.nk'
            api.toNode('Write1').setInput(0, api.toNode('Read1'))
            api.scriptSaveAs(str(path))
            fresh = worker._SoftwareNuke('unused')
            fresh.scriptOpen(str(path))
            with self.assertRaisesRegex(ValueError, 'Read source'):
                fresh.execute(fresh.toNode('Write1'), 1, 1)
            payload = json.loads(path.read_text())
            payload['nodes']['Write1']['inputs'] = ['Write1']
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'cycle'):
                fresh.scriptOpen(str(path))
            self.assertEqual(list(root.glob('*.exr')), [])

class ActualPluginRetryTests(unittest.TestCase):
    def _fixture(self, root, *, legacy=False):
        from dcc_task_runtime import TaskSpec, Step
        from dcc_task_runtime.graph_scheduler import GraphScheduler
        from dcc_task_runtime.exr_codec import encode_tiny_exr
        from nuke_bridge.tasks import NukeCommandAdapter
        client = software_nuke_client(ROOT / 'plugins/nuke/nuke_bridge_addon.py', root)
        addon = dict(zip(client.call.__func__.__code__.co_freevars,
                         (cell.cell_contents for cell in client.call.__func__.__closure__)))['addon']
        native_call = client.call
        client.call = lambda command, params=None: native_call(command, params or {})
        api = sys.modules['nuke']
        # Only native knob serialization and dependency enumeration are replaced.
        knob_type = type(api.toNode('Read1')['file'])
        knob_type.toScript = lambda knob: json.dumps(knob.value(), sort_keys=True)
        node_type = type(api.toNode('Read1'))
        node_type.dependencies = lambda node, flags: [node.input(i) for i in range(node.inputs()) if node.input(i)]
        api.INPUTS, api.HIDDEN_INPUTS, api.EXPRESSIONS = 1, 2, 4
        addon._NUKE_SCHEDULER = GraphScheduler(root/'scheduler')
        addon._RENDER_RECORDS_DIR = root/'records'
        source = root/'input.%04d.exr'
        (root/'input.0001.exr').write_bytes(encode_tiny_exr(1.0))
        directory = root/'task-one'
        inputs = ({'role':'effect_render', 'path':str(source), 'frames':[{'frame':1, 'path':str(root/'input.0001.exr'), 'sha256':__import__('hashlib').sha256((root/'input.0001.exr').read_bytes()).hexdigest()}]},)
        render = {'frame_range':{'start':1,'end':1,'step':1}, 'output_dir':str(root/'out')}
        client.call('agent.nuke.build_graph' if legacy else 'agent.nuke.composite.build_graph', {'task_id':directory.name,'inputs':list(inputs),'render':render})
        scene = root/'scene.nk'; api.scriptSaveAs(str(scene))
        spec = TaskSpec(task_type='nuke.render_delivery' if legacy else 'nuke.reference_composite', intent='actual plugin retry',
                        target_application='nuke',target_scene='existing',target_scene_path=str(scene),
                        inputs=inputs,render=render)
        step = Step('preview-1','PREVIEW_RENDER','agent.nuke.render_preview' if legacy else 'agent.nuke.composite.render_preview',params={'frame':1},gate_policy='strict')
        return api, addon, client, spec, step, directory, NukeCommandAdapter

    def test_public_agent_retry_refuses_unconfirmed_reused_operation(self):
        from dataclasses import replace
        for legacy in (False, True):
            for final in (False, True):
                for state in ('FAILED', 'CANCELLED', 'NEEDS_RECONCILE', 'RUNNING'):
                    with self.subTest(legacy=legacy, final=final, state=state), tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
                        api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp),legacy=legacy)
                        if final:
                            step = replace(step,phase='FINAL_RENDER',action=step.action.replace('render_preview','render_final'))
                        persist = addon._persist_render_record
                        def fail_result(record):
                            if record.get('agent_result'):
                                raise OSError('result write failed')
                            return persist(record)
                        with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                            with mock.patch.object(addon,'_persist_render_record',side_effect=fail_result):
                                with self.assertRaisesRegex(OSError,'result write failed'):
                                    adapter(client).execute(step,spec,directory)
                            record = next(iter(addon._RENDERS.values()))
                            record.pop('agent_result',None); record.pop('execution_fact',None)
                            record['state'] = state
                            persist(record)
                            with self.assertRaisesRegex(RuntimeError,'RENDER_RESULT_UNCONFIRMED'):
                                adapter(client).execute(step,spec,directory)
                            self.assertEqual(execute.call_count,1)

    def test_actual_agent_operation_and_receipt_bind_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            native_call = client.call
            source = Path(spec.inputs[0]['frames'][0]['path'])
            original_bytes = source.read_bytes()
            def replace_before_consumer(command, params=None):
                if command == step.action:
                    source.write_bytes(original_bytes + b'consumer-boundary-change')
                return native_call(command,params)
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                with mock.patch.object(client,'call',side_effect=replace_before_consumer):
                    with self.assertRaisesRegex(RuntimeError,'INPUT_SOURCE_HASH_MISMATCH'):
                        adapter(client).execute(step,spec,directory)
                self.assertEqual(execute.call_count,0)
            source.write_bytes(original_bytes)
            adapter(client).execute(step,spec,directory)
            record = next(iter(addon._RENDERS.values()))
            binding = record['input_binding']
            self.assertEqual(binding['owner_task_id'],directory.name)
            self.assertTrue(binding['frozen_inputs_manifest'])
            self.assertIn('input-sha256:'+binding['frozen_inputs_sha256'],record['dependencies'])
            receipt = addon._nuke_operation_fact(record['task_id'])['formal_receipt']
            self.assertIsNotNone(receipt)
            self.assertEqual(receipt['request']['input_binding'],binding)
            from nuke_bridge.operation_receipts import receipt_errors, receipt_digest
            changed = json.loads(json.dumps(receipt))
            changed['request']['input_binding'] = {}
            changed['request_sha256'] = addon._canonical_payload_sha256(changed['request'])
            changed['operation_receipt_sha256'] = receipt_digest(changed)
            self.assertTrue(receipt_errors(changed))

    def test_success_retry_after_adapter_restart_does_not_execute_again(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                first = adapter(client).execute(step,spec,directory)
                second = adapter(client).execute(step,spec,directory)
                self.assertEqual(first['step_output']['produced'],second['step_output']['produced'])
                self.assertEqual(execute.call_count,1)

    def test_lost_response_and_dirty_owned_scene_recover_from_record(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            native_call = client.call
            dirty = {'value':False}
            api.modified = lambda: dirty['value']
            def lose_response(command, params=None):
                result = native_call(command, params)
                if command == step.action:
                    dirty['value'] = True
                    raise ConnectionError('first response lost')
                return result
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                client.call = lose_response
                with self.assertRaisesRegex(ConnectionError,'response lost'):
                    adapter(client).execute(step,spec,directory)
                client.call = native_call
                addon._RENDERS.clear()
                recovered = adapter(client).execute(step,spec,directory)
                self.assertTrue(recovered['gates'][0]['passed'])
                self.assertEqual(execute.call_count,1)

    def test_ledger_failure_registers_existing_execution_without_rerender(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                with mock.patch.object(addon,'_register_render_artifact',side_effect=OSError('ledger failed')):
                    with self.assertRaisesRegex(OSError,'ledger failed'):
                        adapter(client).execute(step,spec,directory)
                addon._RENDERS.clear()
                result = adapter(client).execute(step,spec,directory)
                self.assertEqual(execute.call_count,1)
                verified = client.call('agent.nuke.composite.verify_preview',{
                    'task_id':directory.name,'inputs':list(spec.inputs),'render':spec.render})
                self.assertTrue(verified['gates'][0]['passed'])
                self.assertNotEqual(result['step_output']['before'],result['step_output']['produced'])

    def test_actual_content_scene_output_changes_reject_and_new_step_executes(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                adapter(client).execute(step,spec,directory)
                with self.assertRaisesRegex(RuntimeError,'CONTENT_CHANGED'):
                    adapter(client).execute(step,replace(spec,intent='changed content'),directory)
                blur = api.toNode(addon._composite_state(directory.name)['graph_nodes']['effect_blur'])
                original = blur['size'].value(); blur['size'].setValue(2.0)
                with self.assertRaisesRegex(RuntimeError,'CONTENT_CHANGED'):
                    adapter(client).execute(step,spec,directory)
                blur['size'].setValue(original)
                api.root()['first_frame'].setValue(2)
                with self.assertRaisesRegex(RuntimeError,'CONTENT_CHANGED'):
                    adapter(client).execute(step,spec,directory)
                api.root()['first_frame'].setValue(1)
                source = Path(spec.inputs[0]['frames'][0]['path'])
                source_bytes = source.read_bytes(); source.write_bytes(source_bytes + b'changed')
                with self.assertRaisesRegex(RuntimeError,'INPUT_SOURCE_HASH_MISMATCH'):
                    adapter(client).execute(step,spec,directory)
                source.write_bytes(source_bytes)
                output = Path(next(iter(addon._RENDERS.values()))['pattern'] % 1)
                original_bytes = output.read_bytes(); output.write_bytes(original_bytes + b'changed')
                with self.assertRaisesRegex(RuntimeError,'OUTPUT_CHANGED'):
                    adapter(client).execute(step,spec,directory)
                output.write_bytes(original_bytes)
                adapter(client).execute(replace(step,identifier='preview-2'),spec,directory)
                self.assertEqual(execute.call_count,2)

    def test_explicit_iteration_uses_new_operation_then_freezes_its_content(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            explicit = replace(step,params={**step.params,'request_id':'controller-iteration-two'})
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                adapter(client).execute(step,spec,directory)
                adapter(client).execute(explicit,spec,directory)
                adapter(client).execute(explicit,spec,directory)
                self.assertEqual(execute.call_count,2)
                self.assertEqual(len(addon._RENDERS),2)
                with self.assertRaisesRegex(RuntimeError,'CONTENT_CHANGED'):
                    adapter(client).execute(explicit,replace(spec,intent='changed iteration'),directory)

    def test_result_record_failure_rolls_back_write_and_reuses_existing_execution(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            persist = addon._persist_render_record
            def fail_result(record):
                if record.get('agent_result'):
                    raise OSError('result write failed')
                return persist(record)
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                with mock.patch.object(addon,'_persist_render_record',side_effect=fail_result):
                    with self.assertRaisesRegex(OSError,'result write failed'):
                        adapter(client).execute(step,spec,directory)
                addon._RENDERS.clear()
                adapter(client).execute(step,spec,directory)
                self.assertEqual(execute.call_count,1)

    def test_result_record_post_commit_failure_reads_back_durable_response(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
            api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp))
            persist = addon._persist_render_record
            def fail_after_commit(record):
                persist(record)
                if record.get('agent_result'):
                    raise OSError('response write reported error after commit')
            with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                with mock.patch.object(addon,'_persist_render_record',side_effect=fail_after_commit):
                    result = adapter(client).execute(step,spec,directory)
                addon._RENDERS.clear()
                recovered = adapter(client).execute(step,spec,directory)
                self.assertEqual(result['step_output']['produced'],recovered['step_output']['produced'])
                self.assertEqual(execute.call_count,1)

    def test_delivery_recipe_retries_success_ledger_and_response_record_failures(self):
        for window in ('success', 'ledger', 'response_record'):
            with self.subTest(window=window), tempfile.TemporaryDirectory() as temp, mock.patch.dict(sys.modules):
                api, addon, client, spec, step, directory, adapter = self._fixture(Path(temp),legacy=True)
                persist = addon._persist_render_record
                def fail_result(record):
                    if record.get('agent_result'):
                        raise OSError('result write failed')
                    return persist(record)
                with mock.patch.object(api,'execute',wraps=api.execute) as execute:
                    if window == 'success':
                        adapter(client).execute(step,spec,directory)
                    else:
                        failure = mock.patch.object(addon,'_register_render_artifact',side_effect=OSError('ledger failed')) if window == 'ledger' else mock.patch.object(addon,'_persist_render_record',side_effect=fail_result)
                        with failure, self.assertRaises(OSError):
                            adapter(client).execute(step,spec,directory)
                    addon._RENDERS.clear()
                    adapter(client).execute(step,spec,directory)
                    self.assertEqual(execute.call_count,1)
                    self.assertTrue(client.call('agent.nuke.verify_preview',{'task_id':directory.name,'inputs':list(spec.inputs),'render':spec.render})['gates'][0]['passed'])
