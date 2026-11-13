import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from vfx_pipeline.workbuddy_graph_mcp import GraphRun, GraphMCP
from vfx_pipeline.workbuddy_mcp import DiagnosticMCP


class Jobs:
    def __init__(self): self.calls=[]
    def propose(self, proposal, request_id):
        self.calls.append(('propose',proposal,request_id));return {'graph_id':'graph1','executed':False}
    def trial(self, graph_id, request_id):
        self.calls.append(('trial',graph_id,request_id));return {'operation_id':'op1','state':'RUNNING'}
    def status(self, operation_id):return {'operation_id':operation_id,'state':'RUNNING','model_acceptance':False}


class FrameHost:
    def __init__(self):
        self.calls = []

    def call(self, command, payload):
        self.calls.append((command, payload))
        return {'request_id': 'sparse-op', 'record': {'state': 'COMPLETED'}}


class GraphMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);data=b'\x89PNG\r\n\x1a\nfixture'
        (self.root/'image.png').write_bytes(data)
        self.manifest={'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'test','construction_authorized':True,
            'assets':[{'asset_id':'image1','file':'image.png','classification':'controller_generated_synthetic','sha256':hashlib.sha256(data).hexdigest()}]}
        self.path=self.root/'run.json';self.path.write_text(json.dumps(self.manifest))
        self.jobs=Jobs();self.facade=GraphRun(self.path,self.jobs);self.mcp=GraphMCP(self.facade)

    def call(self,name,arguments):return self.mcp._call({'name':name,'arguments':arguments})

    def test_diagnostic_adapter_cannot_accidentally_expose_graph_tools(self):
        result=DiagnosticMCP(self.facade)._call({'name':'graph_trial','arguments':{'graph_id':'g','request_id':'r'}})
        self.assertTrue(result['isError']);self.assertEqual(self.jobs.calls,[])

    def test_graph_requires_observations_and_explicit_authorization(self):
        result=self.call('graph_propose',{'proposal':{},'request_id':'r'})
        self.assertTrue(result['isError']);self.assertEqual(self.jobs.calls,[])
        self.facade.submit_observation('image1',{'description':'my observation'},'observe1')
        # Strict MCP schema validation rejects an incomplete proposal before
        # the jobs service is touched.
        self.assertTrue(self.call('graph_propose',{'proposal':{},'request_id':'r'})['isError'])
        self.manifest['construction_authorized']=False
        other=self.root/'other';other.mkdir();(other/'run.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):GraphRun(other/'run.json',self.jobs)

    def test_trial_extra_paths_and_scripts_rejected(self):
        for key in ('path','script','grant','cache'):
            result=self.call('graph_trial',{'graph_id':'g','request_id':'r',key:'bad'})
            self.assertTrue(result['isError'])
        self.assertEqual(self.jobs.calls,[])

    def test_construction_status_does_not_claim_simulation_or_model_acceptance(self):
        health=self.facade.health()
        self.assertFalse(health['dcc_dispatch_enabled'])
        for key in ('simulation_enabled','cache_enabled','render_enabled','release_acceptance','model_identity_verified'):
            self.assertFalse(health[key])
        result=self.call('graph_status',{'operation_id':'op1'})
        self.assertEqual(json.loads(result['content'][0]['text'])['state'],'RUNNING')


    def test_recovery_and_cancellation_are_not_model_tools(self):
        for name in ('graph_reconcile','graph_cancel','reconcile','reconcile_orphan','cancel'):
            for adapter in (self.mcp, DiagnosticMCP(self.facade)):
                result=adapter._call({'name':name,'arguments':{'operation_id':'op1','resume_not_started':True}})
                self.assertTrue(result['isError'])
        self.assertEqual(self.jobs.calls,[])

    def test_sparse_frame_set_is_forwarded_exactly_and_rejected_before_host(self):
        execution_root = self.root / 'execution-sparse'
        execution_root.mkdir()
        manifest = dict(self.manifest, execution_authorized=True,
                        simulation_authorized=True, run_id='execution-sparse')
        path = execution_root / 'execution.json'
        path.write_text(json.dumps(manifest))
        host = FrameHost()
        facade = GraphRun(path, self.jobs, host_client=host, task_id='sparse-task')
        mcp = GraphMCP(facade)

        result = mcp._call({'name': 'frame_execute',
                            'arguments': {'request_id': 'sparse-1', 'frames': [1, 10000],
                                          'budget_seconds': 60}})
        self.assertFalse(result['isError'])
        self.assertEqual(host.calls[0][0], 'agent.fx.simulate_segment')
        self.assertEqual(host.calls[0][1]['step_params']['frames'], [1, 10000])

        rejected = mcp._call({'name': 'frame_execute',
                              'arguments': {'request_id': 'sparse-float', 'frames': [1.0, 10000],
                                            'budget_seconds': 60}})
        self.assertTrue(rejected['isError'])
        self.assertEqual(len(host.calls), 1, 'invalid frame types must not reach the host')

    def test_execution_simulation_and_render_authorizations_are_independent(self):
        class NukeHost:
            boundary_kind = 'strict_fake_nuke_test'
            backend_kind = 'strict_fake_nuke'
            real_host_bound = False
            real_nuke_bound = False
            def __init__(self):self.calls=[];self.bindings=[]
            def render_binding(self,task_id,pattern,frames,colorspace,premultiplied,*,artifact_binding):
                self.bindings.append((task_id,pattern,frames,colorspace,premultiplied))
                return {'source':'controller','task_id':task_id,'node':'Write1','pattern':pattern,
                    'frames':frames,'colorspace':colorspace,'premultiplied':premultiplied,
                    'input_binding':{'kind':'artifact_read','artifact_id':artifact_binding['artifact_id'],
                        'connection_verified':True}}
            def call(self,command,payload):
                self.calls.append((command,payload))
                return {'operation_id':'nuke-op','state':'RUNNING'}

        class RegisteredArtifactGraphRun(GraphRun):
            def consume_artifact(self,artifact_id):
                return {'artifact_id':artifact_id,'usable_as_render_input':True,
                    'verification':{'frame_set':[1]},'colorspace':'ACEScg',
                    'premultiplied':True}

        for execution in (False,True):
            for simulation in (False,True):
                for rendering in (False,True):
                    with self.subTest(execution=execution,simulation=simulation,render=rendering):
                        root=self.root/('profile-{}-{}-{}'.format(int(execution),int(simulation),int(rendering)))
                        root.mkdir()
                        manifest=dict(self.manifest,run_id=root.name,
                            execution_authorized=execution,simulation_authorized=simulation,
                            render_authorized=rendering)
                        run_path=root/'run.json';run_path.write_text(json.dumps(manifest))
                        host=FrameHost();nuke=NukeHost()
                        facade=RegisteredArtifactGraphRun(run_path,self.jobs,host_client=host,
                            nuke_client=nuke,task_id='profile-task',save_root=str(root/'saves'))
                        mcp=GraphMCP(facade)
                        frame=mcp._call({'name':'frame_execute','arguments':{
                            'request_id':'profile-frame','frames':[1],'budget_seconds':30}})
                        if execution and simulation:
                            self.assertFalse(frame['isError'])
                            self.assertEqual([item[0] for item in host.calls],['agent.fx.simulate_segment'])
                        else:
                            self.assertTrue(frame['isError'])
                            self.assertEqual(host.calls,[])
                        render=mcp._call({'name':'nuke_render_bounded','arguments':{
                            'request_id':'profile-render','artifact_id':'registered-input',
                            'pattern':str(root/'saves'/'output.%04d.exr'),'frames':[1]}})
                        if execution and rendering:
                            self.assertFalse(render['isError'])
                            self.assertEqual(len(nuke.bindings),1)
                            self.assertEqual(nuke.bindings[0][-2:],('ACEScg',True))
                            self.assertEqual([item[0] for item in nuke.calls],['render_write'])
                            for supplied in ({'colorspace':'scene_linear'},{'premultiplied':False}):
                                refused=mcp._call({'name':'nuke_render_bounded','arguments':{
                                    'request_id':'mismatch','artifact_id':'registered-input',
                                    'pattern':str(root/'saves'/'output.%04d.exr'),'frames':[1],**supplied}})
                                self.assertTrue(refused['isError'],refused)
                            self.assertEqual(len(nuke.bindings),1)
                            self.assertEqual(len(nuke.calls),1)
                        else:
                            self.assertTrue(render['isError'])
                            self.assertEqual(nuke.bindings,[])
                            self.assertEqual(nuke.calls,[])
