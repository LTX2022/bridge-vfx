"""Full add-on cache/runner/scheduler with only the native hou API replaced.

The input is an already-built scene fixture; this suite proves cache lifecycle,
not domain graph construction or native geometry byte-format correctness.
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from vfx_pipeline.workbuddy_assembly import software_host_client
from windows_filesystem_fixture import fixture_private_permissions

ROOT = Path(__file__).resolve().parents[2]


class OwnedCacheRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.env = patch.dict(os.environ, {'HOUDINI_BRIDGE_STATE_DIR':str(self.root / 'state'),
            'BRIDGE_SKILLS_STATE_ROOT':str(self.root / 'bridge'),
            'BRIDGE_SKILLS_SCHEDULER_ROOT':str(self.root / 'scheduler'),
            'BRIDGE_SKILLS_APPROVAL_SECRET_FILE':str(self.root / 'approval.key'),
            'HOUDINI_BRIDGE_APPROVAL_SECRET':''})
        self.env.start(); self.addCleanup(self.env.stop)
        approval_key = self.root / 'approval.key'
        approval_key.write_text('s'*64, encoding='utf-8')
        fixture_private_permissions(approval_key)
        previous = sys.modules.get('hou')
        self.addCleanup(lambda: sys.modules.pop('hou', None) if previous is None else sys.modules.__setitem__('hou', previous))
        self.client, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.root / 'host')
        self.hou = sys.modules['hou']
        self.frames = []; self.current_frame = 0; self.fail_write = False
        def set_frame(frame):
            self.current_frame = frame; self.frames.append(frame)
        self.hou.setFrame = set_frame
        self.hou.expandString = lambda value: value.replace('$F4', '0001')
        self.task = 'cache-task'
        name = 'BRIDGE_GRAPH_' + 'a'*64
        self.client.call('scene.create_task_root', {'task_id':self.task,'parent':'/obj','root_name':name,'type':'geo'})
        root_path = '/obj/' + name
        output_path = self.client.call('node.create', {'task_id':self.task,'parent':root_path,'name':'output','type':'null'})['path']
        output = self.hou.node(output_path)
        outer = self
        class Geometry:
            def saveToFile(self, path):
                if outer.fail_write: raise OSError('injected native write failure')
                Path(path).write_bytes(('explicit software geometry frame '+str(outer.current_frame)).encode())
            def boundingBox(self):
                class BB:
                    def sizevec(self): return (1,1,1)
                return BB()
            def points(self): return []
            def prims(self): return []
            def pointAttribs(self): return []
        output.geometry = Geometry
        self.addon._fx_store_manifest(self.hou.node(root_path), {'task_id':self.task,'domain_pack':'pyro_smoke_v1',
            'execution_root':root_path,'nodes':{'output':output_path},'input_digest':'fixture-input','revision':1,'seed':1})
        self.params = {'task_id':self.task,'constraints':{'fx':{'domain_pack':'pyro_smoke_v1',
            'cache_output':str(self.root / 'output' / 'sim.$F4.bgeo.sc')}},
            'render':{'frame_range':{'start':13,'end':14,'step':1}}}
        _, manifest = self.addon._fx_manifest(self.task)
        subject, self.subject_hash = self.addon._fx_cache_subject(self.params, 'pyro_smoke_v1', manifest)
        resource = {'estimated_bytes':1024,'max_disk_bytes':1024*1024,'max_seconds':120,
            'task_roots':[str(self.root / 'output')], 'simulation_start_frame':1,
            'output_path':subject['cache_output'],'frame_range':[13,14,1],
            'content_version':self.addon._canonical_payload_sha256(subject['scene']),
            'invalidation_scope':['smoke.simulation','render']}
        resource_hash = self.addon._canonical_payload_sha256(resource)
        expiry = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
        signed = 'houdini_simulation_cache:{}:grant:{}:{}'.format(self.subject_hash,expiry,resource_hash)
        self.params['constraints']['fx'].update({'resource_contract':resource,'approval':{
            'purpose':'houdini_simulation_cache','subject_hash':self.subject_hash,'grant_id':'grant','expires_at':expiry,
            'resource_contract_hash':resource_hash,'signature':hmac.new(('s'*64).encode(),signed.encode(),hashlib.sha256).hexdigest()}})

    def test_contiguous_history_segmented_under_one_owned_slot_and_hash_checked_output(self):
        result = self.addon._fx_cache(self.params,'pyro_smoke_v1',{'simulation_cache':True})
        runner = self.addon.fx_operation_runner(self.task)
        op = result['cache']['operation_id']
        slot = runner.status(op)['slot']
        for i in range(14):
            runner.advance()
            record = runner.status(op)
            self.assertEqual(record['slot']['token'], slot['token'])
            self.assertLessEqual(len(record['frames']),12)
        self.assertEqual(self.frames,list(range(1,15)))
        self.assertEqual(record['state'],'COMPLETED')
        self.assertEqual([row['frame_range'] for row in record['cache_segments_done']], [[1,12],[13,14]])
        self.assertEqual(result['cache']['history_range'], [1,14])
        self.assertNotIn('segments', result['cache'])
        self.assertLessEqual(len(record['frames_done']),12)
        self.assertLessEqual(len(record['evidence']),14)
        self.assertFalse(self.addon._fx_graph_scheduler().snapshot().get('active'))
        status = self.addon._fx_cache_status({**self.params,'expected_subject_hash':self.subject_hash},'pyro_smoke_v1',{})
        self.assertTrue(status['cached']); self.assertTrue(status['cache']['stop_confirmed'])
        self.assertEqual(len(status['artifacts']),2)
        replay = self.addon._fx_cache(self.params,'pyro_smoke_v1',{'simulation_cache':True})
        self.assertTrue(replay['cached']); self.assertEqual(self.frames,list(range(1,15)))
        (self.root/'output'/'sim.0013.bgeo.sc').write_bytes(b'replaced')
        self.assertFalse(self.addon._fx_cache_status({**self.params,'expected_subject_hash':self.subject_hash},'pyro_smoke_v1',{})['cached'])

    def test_history_range_expands_only_one_bounded_segment(self):
        binding = {'history_range':[1,10**12], 'segment_count':(10**12-1)//12+1}
        self.assertEqual(self.addon._fx_cache_segment(binding,0),list(range(1,13)))
        last = self.addon._fx_cache_segment(binding,binding['segment_count']-1)
        self.assertEqual(last[-1],10**12)
        self.assertEqual(self.addon._fx_cache_segment({'segments':[list(range(1,13)),[13,14]]},1),[13,14])
        self.assertLessEqual(len(last),12)
        with self.assertRaises(self.addon.BridgeCommandError):
            self.addon._fx_cache_segment({**binding,'segment_count':1},0)

    def test_native_write_failure_keeps_unknown_slot_and_does_not_retry_frame(self):
        result = self.addon._fx_cache(self.params,'pyro_smoke_v1',{'simulation_cache':True})
        runner=self.addon.fx_operation_runner(self.task); op=result['cache']['operation_id']
        self.fail_write=True
        for _ in range(12): runner.advance()
        with self.assertRaises(OSError): runner.advance()
        runner.advance()
        self.assertEqual(runner.status(op)['state'],'RECONCILE')
        self.assertTrue(self.addon._fx_graph_scheduler().snapshot()['active'])
        self.assertEqual(self.frames.count(13),1)

    def test_resource_hash_mismatch_never_submits_or_cooks(self):
        self.params['constraints']['fx']['resource_contract']['estimated_bytes']=2048
        with self.assertRaises(self.addon.BridgeCommandError) as caught:
            self.addon._fx_cache(self.params,'pyro_smoke_v1',{'simulation_cache':True})
        self.assertEqual(caught.exception.code,'APPROVAL_SCOPE_MISMATCH')
        self.assertEqual(self.frames,[])
