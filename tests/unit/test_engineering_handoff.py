"""Engineering handoff uses production boundaries with explicit software transports."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/package/'src'))
sys.path.insert(0,str(ROOT/'tests/unit'))
from test_native_scope import software_scope
from test_alpha_calibration import signed_fixture
from dcc_task_runtime import alpha_calibration, owned_process
from dcc_task_runtime.artifact_registry import ArtifactRegistry
from houdini_bridge import controlled_output, client as hclient
from vfx_pipeline import workbuddy_assembly
from vfx_pipeline.workbuddy_graph_mcp import GraphRun
import test_controlled_output as controlled_fixtures


def _tool(name):
    spec=importlib.util.spec_from_file_location('handoff_'+name,ROOT/'tools'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


nuke_save=_tool('prepare_nuke_project')
verify=_tool('verify_controlled_output')


class EngineeringHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary_root=mock.patch.object(tempfile,'tempdir','/private/tmp');temporary_root.start();self.addCleanup(temporary_root.stop)
        fixture_helper=controlled_fixtures.ControlledOutputTests();self.addCleanup(fixture_helper.doCleanups)
        self.producer=fixture_helper.prepared_fixture()
        self.root=self.producer.root;self.project=self.root/'project'
        self.control=self.project/'control';self.snapshot=self.control/'snapshot'
        (self.snapshot/'tools').mkdir(parents=True)
        (self.project/'saves').mkdir()
        for name in ('prepare_nuke_project','verify_controlled_output'):
            (self.snapshot/'tools'/f'{name}.py').write_bytes((ROOT/'tools'/f'{name}.py').read_bytes())
        (self.control/'run.json').write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'software-handoff','assets':[],'construction_authorized':True}))
        self.color={'schema':'bridge.project-color/1.0','project_id':'software-fixture','revision':1,
                    'colorspace':'ACEScg','source':'human_project_selection'}
        executable=Path(sys.executable).resolve()
        record={'path':str(executable),'bytes':executable.stat().st_size,
                'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}
        self.binding=software_scope(self.root,versions={'houdini':'21.0.631','nuke':'17.0v1'},
            project_color=self.color,hosts={'nuke':record,'hython':record,'husk':record,'supervisor_python':record})
        self.identity={'task_id':'fixture-owner','session_id':'session','launch_nonce':'nonce',
            'pid':123,'process_generation':'generation','plugin_build':'fixture-build','scene_epoch':0,'version':'17.0v1'}
        self.config={'application':'nuke','version':'17.0v1','plugin_build':'fixture-build',
            'task_root':str(self.project),'controller_root':str(self.control),
            'ledger_root':str(self.control/'artifact_ledger'),'scheduler_root':str(self.root/'scheduler'),
            'executable':str(executable),'supervisor_executable':str(executable),
            'port':1,'host':'127.0.0.1','transport':'tcp','project_color':self.color,
            'expected_identity':self.identity,'evidence_source':'software_test','native_scope':self.binding,
            'resource_budget':{'roots':[str(self.root)],'max_bytes':536870912,'native_scope':self.binding}}
        hconfig=dict(copy.deepcopy(self.config),application='houdini',version='21.0.631',transport='http',output_acceptance=copy.deepcopy(controlled_output._POLICY))
        hconfig['expected_identity']['version']='21.0.631'
        authority,terminal=signed_fixture(self.root/'main-alpha')
        terminal['route_sha256']=controlled_output.controlled_route_sha256(fixture_helper.readback())
        owned_process._signed_write(Path(authority['directory']),terminal)
        authority['terminal_sha256']=alpha_calibration._sha(terminal)
        hconfig['alpha_calibration']=authority
        calibration=alpha_calibration.validate_alpha_calibration(authority,expected_version='21.0.631',expected_plugin_build='fixture-build',expected_route_sha256=terminal['route_sha256'],evidence_source='software_test')
        (self.root/'alpha-calibration-result.json').write_text(json.dumps({'schema':'bridge.alpha-runner.result/1','scope_sha256':self.binding['sha256'],'alpha_calibration':authority,'calibration':calibration}))
        self.saved={'task_id':'fixture-owner','hosts':{'nuke':self.config,'houdini':hconfig}}
        manifest=json.loads((self.control/'run.json').read_text())
        manifest.update(production_host=dict(hconfig,lifecycle='task_owned',session_seconds=120),
            production_nuke=dict(self.config,lifecycle='task_owned',session_seconds=120,software_api_dir=str(self.root/'software-api')))
        (self.control/'run.json').write_text(json.dumps(manifest))
        host=workbuddy_assembly.production_host_client(hconfig,self.control/'host-state')
        host.bind_task('fixture-owner')
        host._store_operation_owner('fixture-operation',dict(copy.deepcopy(self.producer.binding),task_id='fixture-owner'))
        registry=ArtifactRegistry(self.control/'artifact_ledger');host.bind_artifact_registry(registry)
        facade=GraphRun(self.control/'run.json',None,task_id='fixture-owner',host_client=host,artifact_registry=registry,save_root=str(self.project/'saves'))
        facade._register_operation('fixture-operation','houdini-render','houdini','fixture-operation')
        fact=facade.verify_render_output('verify-handoff','fixture-operation')['execution_fact']
        sources={str(Path(module.__file__).resolve()):hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (hclient,controlled_output,alpha_calibration,workbuddy_assembly)}
        registry.register(artifact_id='engineering_h21_main',task_id='fixture-owner',artifact_class='preview_temp',pattern=fact['output_pattern'],frame_set=fact['frame_set'],colorspace='ACEScg',premultiplied=True,dependencies=fact['dependencies'],operation_id='verify-handoff',operation_receipt_sha256=fact['operation_receipt_sha256'],scene_fingerprint=fact['scene_fingerprint'],receipt_source_files=sources)
        self.saved_path=self.control/'production-hosts.json'
        self.saved_path.write_text(json.dumps(self.saved))
        self.script=self.project/'saves/composite.nk'
        self.patch=mock.patch.object(nuke_save,'ROOT',self.snapshot);self.patch.start();self.addCleanup(self.patch.stop)
        self.node_state={name:{'name':name,'class':kind,'inputs':[],'knobs':{'file':'','colorspace':'ACEScg','raw':False,'premultiplied':True,'channels':'rgb'}} for name,kind in (('Read1','Read'),('Write1','Write'))}
        self.transport=mock.Mock();self.transport.health.return_value={'task_host_identity':self.identity}
        self.transport.call.side_effect=self.rpc
        patch=mock.patch('nuke_bridge.client.NukeClient',return_value=self.transport)
        self.transport_patch=patch
        patch.start();self.addCleanup(patch.stop)

    def rpc(self,command,params):
        if command=='get_node': return copy.deepcopy(self.node_state[params['name']])
        if command=='set_knob':
            self.node_state[params['node']]['knobs'][params['knob']]=params['value']
            return {'value':params['value']}
        if command=='connect_nodes':
            self.node_state[params['dst']]['inputs']=[params['src']]
            return dict(params)
        if command=='save_script':
            self.assertIs(params['overwrite'],False)
            self.script.write_text('Read { name Read1 }\nWrite { name Write1 }\n')
            return {'path':str(self.script)}
        if command=='script.info': return {'script':str(self.script),'modified':False}
        raise AssertionError(command)

    def test_formal_nuke_save_and_authenticated_retry_without_rpc(self):
        before=self.saved_path.read_bytes()
        result=nuke_save.prepare_nuke_project(self.project,self.script)
        self.assertEqual(result['evidence_source'],'software_test')
        self.assertEqual(result['sha256'],hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.assertEqual(result['nodes'][1]['inputs'],['Read1'])
        self.assertEqual(result['nodes'][1]['knobs']['channels'],'rgba')
        self.transport.reset_mock();self.transport.call.side_effect=AssertionError('retry issued RPC')
        self.assertEqual(nuke_save.prepare_nuke_project(self.project,self.script),result)
        self.transport.call.assert_not_called()
        self.assertEqual(self.saved_path.read_bytes(),before)
        self.script.write_text('changed')
        with self.assertRaisesRegex(ValueError,'SAVE_RECEIPT_MISMATCH'):
            nuke_save.prepare_nuke_project(self.project,self.script)

    def test_clamped_rgb_write_is_rejected_before_nk_save(self):
        def clamped(command, params):
            if command == 'set_knob' and params.get('knob') == 'channels':
                return {'value':'rgba'}
            return self.rpc(command, params)
        self.transport.call.side_effect = clamped
        with self.assertRaisesRegex(ValueError, 'ENGINEERING_NUKE_RGBA_WRITE_REQUIRED'):
            nuke_save.prepare_nuke_project(self.project,self.script)
        self.assertFalse(self.script.exists())

    def test_first_nuke_host_is_started_only_after_registered_input_and_saved_without_h_restart(self):
        self.transport_patch.stop()
        from test_nuke_task_host import FAKE
        from vfx_pipeline.production_hosts import validate_deployments
        from dcc_task_runtime.native_scope import NativeScope
        from nuke_bridge import task_host
        for relative in ('plugins/nuke/nuke_bridge_addon.py','plugins/houdini/_impl/houdini_bridge_addon.py'):
            target=self.snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/relative).read_bytes())
        api=self.root/'software-api';api.mkdir()
        native=FAKE.replace('"colorspace":Knob("linear")',
            '"colorspace":Knob("linear"),"raw":Knob(False),"premultiplied":Knob(True),"channels":Knob("rgb")')
        (api/'nuke.py').write_text(native+'\ndef modified():return False\n')
        manifest=json.loads((self.control/'run.json').read_text())
        hraw,nraw=manifest['production_host'],manifest['production_nuke']
        configs=validate_deployments(hraw,nraw,controller_root=self.control,repo_root=self.snapshot,
                                    allow_software_processes=True)
        self.saved.pop('restarts',None)
        self.saved['config_sha256']=hashlib.sha256(json.dumps(configs,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
        self.saved['hosts'].pop('nuke')
        self.saved_path.write_text(json.dumps(self.saved))
        native_scope=NativeScope(self.binding)
        self.assertEqual(native_scope.snapshot()['dcc_starts'],0)
        result=None
        try:
            with mock.patch('houdini_bridge.task_host.start',side_effect=AssertionError('H must not restart')):
                result=nuke_save.prepare_nuke_project(self.project,self.script)
            self.assertEqual(result['nodes'][1]['inputs'][0],'Read1')
            self.assertEqual(result['evidence_source'],'software_test')
            saved=json.loads(self.saved_path.read_text())
            self.assertEqual(saved['hosts']['houdini'],self.saved['hosts']['houdini'])
            self.assertEqual(saved['hosts']['nuke']['render_records_root'],str(self.project/'state/nuke_renders'))
            state=native_scope.snapshot()
            self.assertEqual(state['dcc_starts'],1)
            self.assertEqual([item['role'] for item in state['tickets']],['nuke-host'])
            self.assertEqual(nuke_save.prepare_nuke_project(self.project,self.script),result)
            self.assertEqual(native_scope.snapshot()['dcc_starts'],1)
            # Simulate interruption after native save/readback but before the controller receipt commit.
            (self.control/'nuke-save-receipt.json').unlink()
            from nuke_bridge.client import NukeClient
            original_call=NukeClient.call
            def read_only(client,command,params=None):
                self.assertIn(command,{'nuke_ping','get_node','script.info'})
                return original_call(client,command,params)
            with mock.patch.object(NukeClient,'call',autospec=True,side_effect=read_only), \
                 mock.patch.object(owned_process,'launch',side_effect=AssertionError('reconcile must not launch')):
                adopted=nuke_save.prepare_nuke_project(self.project,self.script,reconcile_saved=True)
            self.assertEqual(adopted['observed_by'],'trusted_controller_reconciled_current_task_script')
            self.assertEqual(adopted['sha256'],result['sha256'])
            self.assertEqual(native_scope.snapshot()['dcc_starts'],1)
            self.assertEqual(nuke_save.prepare_nuke_project(self.project,self.script),adopted)
        finally:
            saved=json.loads(self.saved_path.read_text())
            if 'nuke' in saved['hosts']:
                stopped=task_host.stop(saved['hosts']['nuke']['work_dir'])
                self.assertTrue(stopped['stopped'])

    def test_wrong_path_existing_file_and_unapproved_scope_never_dispatch(self):
        with self.assertRaisesRegex(ValueError,'SCRIPT_PATH_NOT_FROZEN'):
            nuke_save.prepare_nuke_project(self.project,self.project/'saves/other.nk')
        self.script.write_text('unowned existing file')
        with self.assertRaisesRegex(ValueError,'SCRIPT_ALREADY_EXISTS'):
            nuke_save.prepare_nuke_project(self.project,self.script)
        prepared_root=self.root/'unapproved'
        denied=software_scope(prepared_root,execution_authorized=False,status='PREPARED_REQUIRES_EXPLICIT_LIVE_SCOPE_APPROVAL')
        self.saved['hosts']['nuke']['native_scope']=denied
        self.saved_path.write_text(json.dumps(self.saved))
        with self.assertRaisesRegex(ValueError,'SCOPE_NOT_AUTHORIZED'):
            nuke_save.prepare_nuke_project(self.project,self.script)
        self.transport.call.assert_not_called()

    def test_signed_alpha_result_is_injected_without_mutating_configuration(self):
        authority,_=signed_fixture(self.root/'alpha')
        calibration=alpha_calibration.validate_alpha_calibration(authority,expected_version='21.0.631',
            expected_plugin_build='fixture-build',expected_route_sha256='a'*64,evidence_source='software_test')
        result={'schema':'bridge.alpha-runner.result/1','scope_sha256':self.binding['sha256'],
                'alpha_calibration':authority,'calibration':calibration}
        path=self.root/'alpha-calibration-result.json';path.write_text(json.dumps(result))
        config={'native_scope':self.binding,'version':'21.0.631','plugin_build':'fixture-build','evidence_source':'software_test'}
        original=copy.deepcopy(config)
        prepared=verify._alpha_configuration(config,path)
        self.assertEqual(prepared['alpha_calibration'],authority)
        self.assertEqual(config,original)
        config['evidence_source']='real_host'
        with self.assertRaises(ValueError): verify._alpha_configuration(config,path)
        config['evidence_source']='software_test'
        for problem in ('scope','path','claimed-pass','module-change'):
            with self.subTest(problem=problem):
                candidate=copy.deepcopy(result)
                if problem=='scope':candidate['scope_sha256']='0'*64
                if problem=='claimed-pass':candidate['alpha_calibration']={'status':'PASS'}
                if problem=='module-change':candidate['calibration']['plugin_build']='other'
                path.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError):
                    verify._alpha_configuration(config,self.root/'other.json' if problem=='path' else path)

if __name__=='__main__': unittest.main()
