from __future__ import annotations

import json
import time
import unittest

import test_formal_domain_recovery as recovery
from houdini_bridge.client import BridgeError
from vfx_pipeline.graph_job_evidence import atomic_json


SAMPLED_FORMAT_NATIVE = '''
sampled_output_state={'after_frame':False}
original_output_stage=Node.stage
class SampledOutputCompression:
    def __init__(self,attribute):
        self.attribute=attribute
        self.kind,self.value=attribute.kind,attribute.value
    def GetTypeName(self):return self.attribute.GetTypeName()
    def GetName(self):return self.attribute.GetName()
    def HasAuthoredValueOpinion(self):return self.attribute.HasAuthoredValueOpinion()
    def Get(self,frame=None):
        default=self.attribute.Get()
        if frame==3:return 'dwaa'
        if frame==1 and sampled_output_state['after_frame']:
            return 'none' if default!='none' else 'zip'
        return default
def sampled_output_stage(self,*arguments,**keywords):
    stage=original_output_stage(self,*arguments,**keywords)
    for prim in stage.prims.values():
        name='driver:parameters:husk:OpenEXR:compression'
        if name in prim.attributes:
            prim.attributes[name]=SampledOutputCompression(prim.attributes[name])
    if keywords.get('frame')==5:
        target='/Filters/explicit_budget'
        settings=next(prim for prim in stage.prims.values() if prim.kind=='RenderSettings')
        settings.relations['husk:orderedImageFilters']=[target]
        image_filter=api.Prim(target,'Scope')
        for index in range(4):
            name='explicit:array'+str(index)
            image_filter.attributes[name]=api.Attribute('token[]',['X'*8192]*128,name)
        stage.prims[target]=image_filter
    return stage
Node.stage=sampled_output_stage
original_output_render=Node.render
def sampled_output_render(self,*arguments,**keywords):
    result=original_output_render(self,*arguments,**keywords)
    sampled_output_state['after_frame']=True
    if keywords.get('frame_range', (None,))[0] == 2:
        self.parm('soho_foreground').set(0)
    return result
Node.render=sampled_output_render
'''


PUBLICATION_FAILURE_NATIVE = '''
original_terminal_save=addon.OperationRunner._save
def deny_terminal_publication(self,store):
    if any(row.get('kind')=='render' and row.get('state')=='COMPLETED'
           and row.get('request_id')=='sealed-publication-fault'
           for row in (store.get('operations') or {}).values()):
        raise PermissionError('controlled terminal publication failure')
    return original_terminal_save(self,store)
addon.OperationRunner._save=deny_terminal_publication
'''

BUDGET_FINISH_FAILURE_NATIVE = '''
original_render_budget=addon.OperationRunner._render_budget
def deny_budget_finish(self,record,*,finished=False):
    if finished and record.get('request_id')=='sealed-publication-fault':
        raise PermissionError('controlled operation-finished failure')
    return original_render_budget(self,record,finished=finished)
addon.OperationRunner._render_budget=deny_budget_finish
'''


class RenderTimeProcessTests(unittest.TestCase):
    def test_original_seal_recovers_after_publication_denial_without_rerender(self):
        for native_boundary, held in ((PUBLICATION_FAILURE_NATIVE, False),
                                      (BUDGET_FINISH_FAILURE_NATIVE, True)):
            with self.subTest(supervisor_budget_finish_failed=held):
                self._sealed_publication_recovery(native_boundary, held)

    def _sealed_publication_recovery(self, native_boundary, held):
        from dcc_task_runtime.graph_scheduler import GraphScheduler
        from dcc_task_runtime.owned_process import read_receipt
        from houdini_bridge.client import render_producer_binding, _render_terminal_event
        harness = recovery.FormalDomainRecoveryTests(methodName='runTest')
        self.addCleanup(harness.doCleanups)
        base, project = harness.setup_case('sealed-publication-' + str(time.time_ns()),
            native_boundary=native_boundary)
        with recovery.facade_for(project) as facade:
            for index, asset in enumerate(facade.catalog()['assets']):
                facade.submit_observation(asset['asset_id'], {'description': 'synthetic publication test',
                    'dominant_colors': ['grey']}, 'seal-obs-' + str(index))
            graph = facade.graph_propose({'schema': 'bridge.registered-domain-construction/1',
                'domain_pack': 'lighting_camera_render_v1', 'houdini_version': '21.0.631'}, 'seal-proposal')
            trial = facade.graph_trial(graph['graph_id'], 'seal-trial')
            def ready():
                value = facade.graph_status(trial['operation_id'])
                return value if value.get('state') in {'SUCCEEDED', 'FAILED'} else None
            built = recovery.wait_for(ready, seconds=30)
            self.assertEqual(built['state'], 'SUCCEEDED', built)
            facade.graph_trial(graph['graph_id'], 'seal-trial')
            saved = facade.task_save()
            target = next(path for address, path in built['result']['topology']['nodes'].items()
                          if address.endswith('/render'))
            facade.houdini_render_bounded('sealed-publication-fault', saved['saved_scene_id'], target,
                str(project / 'saves' / 'publish-fault.%03d.exr'), [1], 20.0)
            def pending():
                value = facade.operation_query('sealed-publication-fault')
                return value if value.get('operation', {}).get('stage') == 'render_terminal_sealing' else None
            observed = recovery.wait_for(pending, seconds=15)
            record = observed['operation']
            self.assertEqual(record['state'], 'RUNNING')
            self.assertIsNone(observed.get('execution_fact'))
            producer = render_producer_binding(record)
            supervisor = record['supervisor_binding']
            sealed = recovery.wait_for(lambda: read_receipt(supervisor['directory'],
                _render_terminal_event(producer), identity=supervisor['identity']), seconds=15)
            self.assertEqual(sealed['execution_fact']['state'], 'COMPLETED')
            scheduler = GraphScheduler(project / 'scheduler')
            if held:
                self.assertTrue(scheduler.snapshot()['active'])
            else:
                recovery.wait_for(lambda: not scheduler.snapshot()['active'], seconds=15)
            stops = recovery.stop_hosts(project / 'control')
            self.assertTrue(stops['houdini']['receipt']['confirmed_exit'])
            recovered = facade.operation_query('sealed-publication-fault')
            self.assertEqual(recovered['operation']['state'], 'COMPLETED', recovered)
            self.assertEqual(recovered['execution_fact'], sealed['execution_fact'])
            self.assertEqual(recovered['operation']['terminal_recovery_stop_receipt']['event'], 'stopped')
            self.assertFalse(scheduler.snapshot()['active'])
            calls = (project / 'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines()
            self.assertEqual(len(calls), 1)
        self.doCleanups()

    def test_sampled_format_is_checked_before_and_after_actual_frame(self):
        for version in ('21.0.631', '22.0.429'):
            with self.subTest(version=version):
                harness = recovery.FormalDomainRecoveryTests(methodName='runTest')
                self.addCleanup(harness.doCleanups)
                base, project = harness.setup_case('output-time-' + str(time.time_ns()),
                    native_boundary=SAMPLED_FORMAT_NATIVE, version=version)
                (base / 'native.002.exr').write_bytes((base / 'native.001.exr').read_bytes())
                with recovery.facade_for(project) as facade:
                    for index, asset in enumerate(facade.catalog()['assets']):
                        facade.submit_observation(asset['asset_id'], {
                            'description': 'explicit output sampling reference',
                            'dominant_colors': ['grey']}, 'time-observation-' + str(index))
                    graph = facade.graph_propose({
                        'schema': 'bridge.registered-domain-construction/1',
                        'domain_pack': 'lighting_camera_render_v1',
                        'houdini_version': version}, 'time-proposal')
                    trial = facade.graph_trial(graph['graph_id'], 'time-trial')
                    operation_id = trial['operation_id']
                    def completed_trial():
                        result = facade.graph_status(operation_id)
                        return result if result.get('state') in {'SUCCEEDED', 'FAILED'} else None
                    completed = recovery.wait_for(completed_trial, seconds=30)
                    self.assertEqual(completed['state'], 'SUCCEEDED', completed)
                    completed = facade.graph_trial(graph['graph_id'], 'time-trial')
                    self.assertEqual(completed['operation_id'], operation_id)
                    target = next(path for address, path in completed['result']['topology']['nodes'].items()
                                  if address.endswith('/render'))
                    saved = facade.task_save()
                    call_log = project / 'control/houdini-task-host/native-render-calls.jsonl'
                    with self.assertRaises(BridgeError) as caught:
                        facade.houdini_render_bounded('sampled-invalid-format', saved['saved_scene_id'],
                            target, str(project / 'saves' / 'invalid-time.%03d.exr'), [3], 20.0)
                    self.assertEqual(caught.exception.code, 'RENDER_CONFIG_INVALID')
                    self.assertFalse(call_log.exists())
                    self.assertFalse((project / 'saves' / 'invalid-time.003.exr').exists())
                    with self.assertRaises(BridgeError) as oversized:
                        facade.houdini_render_bounded('oversized-output-observation', saved['saved_scene_id'],
                            target, str(project / 'saves' / 'oversized.%03d.exr'), [5], 20.0)
                    self.assertEqual(oversized.exception.code, 'RENDER_CONFIG_INVALID')
                    self.assertFalse(call_log.exists())
                    self.assertFalse((project / 'saves' / 'oversized.005.exr').exists())
                    submitted = facade.houdini_render_bounded('sampled-format-drift', saved['saved_scene_id'],
                        target, str(project / 'saves' / 'sampled-drift.%03d.exr'), [1], 20.0)
                    result = recovery.wait_for(lambda: harness.completed_render(
                        facade, submitted['operation_id']), seconds=25)
                    atomic_json(base / 'sampled-format-result.json', result, root=base)
                    record = result['operation']
                    self.assertEqual(record['state'], 'FAILED', result)
                    self.assertIn('native render configuration changed during frame', record['error'])
                    self.assertEqual(record['frames_done'], [])
                    self.assertEqual(record['frame_snapshots'], {})
                    self.assertEqual(record.get('output_facts', {}), {})
                    self.assertEqual(result['execution_fact']['metadata'], {})
                    self.assertEqual(result['execution_fact']['completion_metadata_status'],
                                     'BLOCKED_MISSING_NATIVE_FACTS')
                    calls = [json.loads(line) for line in call_log.read_text().splitlines()]
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0]['frame'], 1)
                    self.assertTrue((project / 'saves' / 'sampled-drift.001.exr').is_file())
                    unknown = facade.houdini_render_bounded('writer-wait-drift', saved['saved_scene_id'],
                        target, str(project / 'saves' / 'unknown-stop.%03d.exr'), [2], 20.0)
                    def stop_unknown():
                        query = facade.operation_query(unknown['operation_id'])
                        return query if query.get('operation', {}).get('state') == 'RECONCILE' else None
                    held = recovery.wait_for(stop_unknown, seconds=25)
                    self.assertEqual(held['operation']['stage'], 'render_writer_stop_unknown')
                    self.assertEqual(held['operation']['in_flight_frame'], 2)
                    self.assertFalse(held['operation'].get('lifecycle_fact', {}).get('stop_confirmed'))
                    self.assertIsNone(held.get('execution_fact'))
                    from dcc_task_runtime.graph_scheduler import GraphScheduler
                    self.assertTrue(GraphScheduler(project / 'scheduler').snapshot()['active'])
                self.doCleanups()


if __name__ == '__main__':
    unittest.main()
