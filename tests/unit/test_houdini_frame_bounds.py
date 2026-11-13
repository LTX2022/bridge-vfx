from __future__ import annotations

import builtins
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dcc_task_runtime import Step, TaskSpec
from houdini_bridge import tasks, recipes
from houdini_bridge.client import BridgeError
from houdini_bridge.tasks import HoudiniCommandAdapter

HISTORY_END = 10**12


class UnexpectedHistoryExpansion(RuntimeError):
    pass


def bounded_range_probe(*args):
    """Detect the old allocation request before returning any large range."""
    if len(args) == 1:
        start, stop, stride = 0, args[0], 1
    elif len(args) == 2:
        start, stop, stride = args[0], args[1], 1
    else:
        start, stop, stride = args
    count = max(0, (stop - start + stride - 1) // stride)
    if count > 12:
        raise UnexpectedHistoryExpansion("attempted {}-frame expansion".format(count))
    return builtins.range(*args)


def spec(output_dir='', *, end=HISTORY_END, stride=1, schema='1.0', inputs=()):
    return TaskSpec.from_mapping({
        'schema_version':schema,'task_type':'houdini.model_to_karma','intent':'bounded model render',
        'target':{'application':'houdini'},'inputs':list(inputs),
        'render':{'frame_range':{'start':1,'end':end,'step':stride},'output_dir':str(output_dir)},
    })


class RecordingClient:
    def __init__(self, result):
        self.calls=[]
        self.result=result

    def call(self, method, payload=None):
        self.calls.append((method,payload))
        return self.result


class HoudiniFrameBoundsTests(unittest.TestCase):
    def test_full_task_range_is_accepted_without_materialization(self):
        task=spec()
        self.assertEqual(task.render['frame_range']['end'],HISTORY_END)
        self.assertEqual(task.target_application,'houdini')

    def test_empty_inputs_never_request_any_history_range(self):
        with patch.object(tasks,'range',side_effect=bounded_range_probe,create=True) as probe:
            self.assertEqual(HoudiniCommandAdapter._frozen_inputs_manifest(spec()),[])
        self.assertEqual(probe.call_count,0)

    def test_nonsequence_input_still_freezes_with_large_task_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'model.bgeo';source.write_bytes(b'frozen geometry input')
            item={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
            with patch.object(tasks,'range',side_effect=bounded_range_probe,create=True) as probe:
                manifest=HoudiniCommandAdapter._frozen_inputs_manifest(spec(inputs=[item]))
            self.assertEqual(manifest[0]['sha256'],item['sha256'])
            self.assertEqual(probe.call_count,0)

    def test_v2_mismatched_sequence_count_rejects_before_file_probe_or_history_allocation(self):
        item={'path':'/missing/input.%04d.exr','frames':[{'frame':1,'path':'/missing/input.0001.exr','sha256':'a'*64}]}
        with patch.object(tasks,'range',side_effect=bounded_range_probe,create=True) as probe:
            with self.assertRaisesRegex(BridgeError,'does not exactly cover'):
                HoudiniCommandAdapter._frozen_inputs_manifest(spec(schema='2.0',inputs=[item]))
        self.assertEqual(probe.call_count,0)

    def test_large_model_recipe_requires_segmented_planning_before_expansion(self):
        with patch.object(recipes,'range',side_effect=bounded_range_probe,create=True) as probe:
            with self.assertRaisesRegex(ValueError,'at most 12'):
                recipes.ModelToKarmaRecipe().steps(spec(),{})
        self.assertEqual(probe.call_count,0)

    def test_recipe_twelve_actual_frames_and_sparse_large_numbers_still_plan(self):
        with patch.object(recipes,'range',side_effect=bounded_range_probe,create=True):
            plan=recipes.ModelToKarmaRecipe().steps(spec(end=12),{})
            sparse=recipes.ModelToKarmaRecipe().steps(spec(stride=HISTORY_END),{})
        self.assertEqual(len([s for s in plan if s.action=='agent.model.render_final']),12)
        self.assertEqual(len([s for s in sparse if s.action=='agent.model.render_final']),1)

    def test_reference_recipe_requires_explicit_short_frames_for_large_history(self):
        task=spec()
        with patch.object(recipes,'range',side_effect=bounded_range_probe,create=True) as probe:
            with self.assertRaisesRegex(ValueError,'at most 12'):
                recipes.ReferenceEffectRecipe._frames(task)
            task.constraints['fx']={'frames':[1,500,HISTORY_END]}
            self.assertEqual(recipes.ReferenceEffectRecipe._frames(task),[1,500,HISTORY_END])
        self.assertEqual(probe.call_count,0)
        for invalid in ([1]*13,[2,1],[1,1],[0,1],[1,HISTORY_END+1],[True]):
            task.constraints['fx']['frames']=invalid
            with self.assertRaises(ValueError):recipes.ReferenceEffectRecipe._frames(task)

    def test_verify_and_wait_reject_large_operation_before_materialization(self):
        verify=Step('verify','ARTIFACT_VERIFY','agent.model.verify_final')
        render=Step('render','FINAL_RENDER','agent.model.render_final')
        with patch.object(tasks,'range',side_effect=bounded_range_probe,create=True) as probe:
            with self.assertRaisesRegex(ValueError,'at most 12'):
                HoudiniCommandAdapter._verify_outputs(spec(),verify)
            with self.assertRaisesRegex(ValueError,'at most 12'):
                HoudiniCommandAdapter._wait_for_render_outputs(render,spec(),{'output_pattern':'/missing/final.$F4.exr'})
        self.assertEqual(probe.call_count,0)

    def test_actual_adapter_refuses_large_render_before_scene_guard_or_dcc_call(self):
        client=RecordingClient({});adapter=HoudiniCommandAdapter(client)
        step=Step('render','FINAL_RENDER','agent.model.render_final')
        with tempfile.TemporaryDirectory() as tmp,patch.object(adapter,'_ensure_target_scene') as scene:
            with self.assertRaisesRegex(ValueError,'at most 12'):
                adapter.execute(step,spec(),Path(tmp))
        self.assertEqual(client.calls,[]);scene.assert_not_called()

    def test_adapter_sends_only_actual_short_segment_and_preserves_full_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            for frame in builtins.range(11,23):(output/f'final.{frame:04d}.exr').write_bytes(b'fresh software boundary output')
            result={'output_pattern':str(output/'final.$F4.exr'),'before':{},'gates':[{'name':'final_rendered','kind':'operation','passed':True}]}
            client=RecordingClient(result);adapter=HoudiniCommandAdapter(client);task=spec(output)
            step=Step('segment','FINAL_RENDER','agent.model.render_final',params={'frame_range':{'start':11,'end':22,'step':1}})
            with patch.object(adapter,'_ensure_target_scene',return_value=None),patch.object(adapter,'_record_target_scene_mutation'),patch.object(tasks,'range',side_effect=bounded_range_probe,create=True):
                actual=adapter.execute(step,task,output)
            payload=client.calls[0][1]
            self.assertEqual(payload['render']['frame_range'],{'start':11,'end':22,'step':1})
            self.assertEqual(payload['task_frame_range'],{'start':1,'end':HISTORY_END,'step':1})
            self.assertEqual(task.render['frame_range']['end'],HISTORY_END)
            self.assertTrue(actual['gates'][0]['passed'])

    def test_host_verify_short_segment_does_not_scan_full_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            for frame in builtins.range(11,23):(output/f'final.{frame:04d}.exr').write_bytes(b'file gate')
            client=RecordingClient({});adapter=HoudiniCommandAdapter(client)
            step=Step('verify','ARTIFACT_VERIFY','agent.model.verify_final',params={'frame_range':{'start':11,'end':22,'step':1}})
            with patch.object(adapter,'_ensure_target_scene',return_value=None),patch.object(adapter,'_record_target_scene_mutation'),patch.dict(os.environ,{'DCC_BRIDGE_HOST_VERIFY':'1'}),patch.object(tasks,'range',side_effect=bounded_range_probe,create=True):
                result=adapter.execute(step,spec(output),output)
            self.assertEqual(len(result['artifacts']),12)
            self.assertEqual(client.calls,[])

    def test_optional_dcc_verify_receives_same_bounded_segment(self):
        client=RecordingClient({'gates':[{'name':'final_artifacts','kind':'verification','passed':True}]})
        adapter=HoudiniCommandAdapter(client)
        step=Step('verify','ARTIFACT_VERIFY','agent.model.verify_final',params={'frame_range':{'start':7,'end':9,'step':1}})
        with tempfile.TemporaryDirectory() as tmp,patch.object(adapter,'_ensure_target_scene',return_value=None),patch.object(adapter,'_record_target_scene_mutation'),patch.dict(os.environ,{'DCC_BRIDGE_HOST_VERIFY':'0'}):
            adapter.execute(step,spec(),Path(tmp))
        self.assertEqual(client.calls[0][1]['render']['frame_range'],{'start':7,'end':9,'step':1})

    def test_single_high_numbered_frame_is_not_conflated_with_history_size(self):
        step=Step('frame','FINAL_RENDER','agent.model.render_final',params={'frame':HISTORY_END})
        with patch.object(tasks,'range',side_effect=bounded_range_probe,create=True):
            self.assertEqual(HoudiniCommandAdapter._render_operation_frames(spec(),step),[HISTORY_END])

    def test_frame_bounds_stride_and_conflicting_segment_are_checked(self):
        task=spec(end=99,stride=2)
        for params in ({'frame':2},{'frame':101},{'frame':True},{'frame':3.9},{'frame_range':{'start':1,'end':5,'step':1}},
                       {'frame_range':{'start':1,'end':3,'step':0}}, {'frame':1,'frame_range':{'start':1,'end':1,'step':1}}):
            step=Step('frame','FINAL_RENDER','agent.model.render_final',params=params)
            with self.assertRaises(ValueError):HoudiniCommandAdapter._render_operation_frames(task,step)
        self.assertEqual(HoudiniCommandAdapter._render_operation_frames(task,Step('frame','FINAL_RENDER','agent.model.render_final',params={'frame_range':{'start':3,'end':25,'step':2}})),list(builtins.range(3,26,2)))

    def test_preview_is_one_explicit_actual_frame(self):
        step=Step('preview','TECH_VERIFY','agent.model.verify_preview')
        with patch.object(tasks,'range',side_effect=bounded_range_probe,create=True):
            self.assertEqual(HoudiniCommandAdapter._render_operation_frames(spec(),step),[1])
        invalid=Step('preview','PREVIEW_RENDER','agent.model.render_preview',params={'frame_range':{'start':1,'end':2,'step':1}})
        with self.assertRaisesRegex(ValueError,'exactly one'):HoudiniCommandAdapter._render_operation_range(spec(),invalid)

    def test_time_budget_is_validated_before_actual_adapter_mutations(self):
        client=RecordingClient({});adapter=HoudiniCommandAdapter(client)
        step=Step('frame','FINAL_RENDER','agent.model.render_final',params={'frame':1})
        with tempfile.TemporaryDirectory() as tmp,patch.object(adapter,'_ensure_target_scene') as scene:
            for value in ('121','inf','nan','0','-1'):
                with patch.dict(os.environ,{'DCC_BRIDGE_RENDER_WAIT_SECONDS':value}):
                    with self.assertRaisesRegex(ValueError,'120 seconds'):
                        adapter.execute(step,spec(),Path(tmp))
        scene.assert_not_called();self.assertEqual(client.calls,[])
        with patch.dict(os.environ,{'DCC_BRIDGE_RENDER_WAIT_SECONDS':'120'}):
            self.assertEqual(HoudiniCommandAdapter._render_wait_seconds(),120)

    def test_cache_wait_uses_resource_from_actual_adapter_payload_envelope(self):
        complete={'cached':True,'cache':{'state':'COMPLETE','stop_confirmed':True},'artifacts':[{'kind':'simulation_cache'}]}
        client=RecordingClient(complete)
        payload={'task_id':'cache','constraints':{'fx':{'resource_contract':{'max_seconds':1}}},'step_params':{'frames':[1,5,9]}}
        self.assertEqual(HoudiniCommandAdapter(client)._wait_for_fx_cache(complete,payload),complete)
        payload['step_params']['resource_contract']={'max_seconds':121}
        with self.assertRaisesRegex(RuntimeError,'time budget'):
            HoudiniCommandAdapter(client)._wait_for_fx_cache(complete,payload)
        self.assertEqual(client.calls,[])

    def test_wait_rejects_producer_frame_mismatch(self):
        step=Step('frame','FINAL_RENDER','agent.model.render_final',params={'frame':1})
        with self.assertRaisesRegex(RuntimeError,'does not match'):
            HoudiniCommandAdapter._wait_for_render_outputs(step,spec(),{'output_pattern':'/missing/final.$F4.exr','frame':2})
