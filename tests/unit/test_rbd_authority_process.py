"""Controlled hosts restore R05 only through a verified saved HIP checkpoint."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from dcc_task_runtime.owned_process import OwnedProcessHandle
from houdini_bridge.client import BridgeError
from vfx_pipeline.production_hosts import stop_hosts
from vfx_pipeline.workbuddy_assembly import production_host_client
import test_production_task_hosts as support


PACKED_API = '''sys.path.insert(0,str(native_root/'tests/unit'))
from test_native_rbd_controls_program import packed_geometry
Node.isBypassed=lambda self:False
original_input_geometry=Node.inputGeometry
def fixed_packed_output(self,frame,output_index=0):
    if (self.type().name()!='rbdconfigure' and not self.path().endswith('/rbd_velocity')) or output_index!=0:
        raise ValueError('explicit packed source supports owned configure/carrier output zero only')
    return packed_geometry()
def fixed_actual_input(self,input_index):
    if self.type().name()!='rbdbulletsolver' or input_index!=0:
        return original_input_geometry(self,input_index)
    connections=[connection for connection in self.inputConnections() if connection.inputIndex()==input_index]
    if len(connections)!=1:raise ValueError('actual input unavailable')
    return connections[0].inputNode().geometryAtFrame(hou.frame(),output_index=connections[0].outputIndex())
Node.geometryAtFrame=fixed_packed_output
Node.inputGeometry=fixed_actual_input
probe_path=Path(os.environ['BRIDGE_TEST_RBD_NATIVE_PROBE'])
phase_path=probe_path.with_suffix('.phase.json')
def trace_rbd_event(kind,path,**facts):
    if not phase_path.is_file():return
    phase=json.loads(phase_path.read_text(encoding='utf-8'))
    with probe_path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(dict(kind=kind,path=path,pid=os.getpid(),phase=phase,**facts),ensure_ascii=False)+'\\n')
original_userdata=Node.userData
original_set_userdata=Node.setUserData
def traced_userdata(self,key):
    value=original_userdata(self,key)
    if self.path().endswith('/rbd_velocity') and key in ('bridge_rbd_velocity_basis_v1','bridge_rbd_velocity_program_v1'):
        trace_rbd_event('userdata_read',self.path(),key=key,value=value)
    return value
def traced_set_userdata(self,key,value):
    if self.path().endswith('/rbd_velocity') and key in ('bridge_rbd_velocity_basis_v1','bridge_rbd_velocity_program_v1'):
        trace_rbd_event('userdata_write',self.path(),key=key,value=value)
    return original_set_userdata(self,key,value)
Node.userData=traced_userdata
Node.setUserData=traced_set_userdata
Parm=hou._native_schema_parm_class
original_parm_set=Parm.set
def traced_parm_set(self,value,**kwargs):
    if self.node().path().endswith('/rbd_velocity'):
        trace_rbd_event('parm_write',self.node().path(),name=self.name(),value=value)
    return original_parm_set(self,value,**kwargs)
Parm.set=traced_parm_set
original_hip_load=hou.hipFile.load
def traced_hip_load(path,*args,**kwargs):
    trace_rbd_event('hip_load_begin',str(path))
    result=original_hip_load(path,*args,**kwargs)
    trace_rbd_event('hip_load_end',str(path))
    return result
hou.hipFile.load=traced_hip_load
'''


class RbdAuthorityProcessTests(unittest.TestCase):
    def verified_stop(self, project, state, identity):
        stopped = stop_hosts(project / 'control')
        self.assertTrue(stopped['houdini']['receipt']['confirmed_exit'], stopped)
        self.assertTrue(stopped['houdini']['receipt']['heavy_slot_released'], stopped)
        work = Path(state['hosts']['houdini']['work_dir'])
        binding = json.loads((work / 'supervisor-binding.json').read_text(encoding='utf-8'))
        stop_fact = OwnedProcessHandle(binding['directory'], binding['identity']).receipt()
        self.assertIsNotNone(stop_fact)
        self.assertEqual(stop_fact['pid'], identity['pid'])
        self.assertEqual(stop_fact['observed_by'], 'owned_child_wait', stop_fact)
        if os.name == 'nt':
            self.assertTrue(stop_fact['child_wait_observed'], stop_fact)
            self.assertEqual(stop_fact['job_active_processes'], 0, stop_fact)
        return stopped, stop_fact

    def saved_store(self, project, saved):
        matching = []
        for path in project.rglob('*.saves.json'):
            store = json.loads(path.read_text(encoding='utf-8'))
            receipts = [receipt for receipt in store.get('saves', [])
                        if Path(receipt['path']).resolve() == Path(saved['path']).resolve()
                        and receipt['sha256'] == saved['sha256']]
            if receipts:
                matching.append((path, store, receipts[-1]))
        self.assertEqual(len(matching), 1, [str(item[0]) for item in matching])
        return matching[0]

    def test_generated_workers_verified_checkpoint_restores_new_identity_without_apply(self):
        helper = support.ProductionTaskHostsTests(
            'test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen')
        for version in ('21.0.631', '22.0.429'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                project, api = base / 'project with space', base / 'api'
                api.mkdir()
                (api / 'nuke.py').write_text(support.FAKE, encoding='utf-8')
                native = support.STRICT_RENDER_NATIVE.replace(
                    "native.constrain_hou(native_root/",
                    "states.setdefault('Sop/attribwrangle',{})['snippet']=dict(origin='test_injected_native_api',value='',locked=False,disabled=False,hidden=False)\nnative.constrain_hou(native_root/")
                launch = support.HYTHON.replace("sys.modules['houdini_bridge_addon']=addon",
                    "sys.modules['houdini_bridge_addon']=addon\n" + native + PACKED_API)
                bootstrap = base / '固定底层 API.py'
                bootstrap.write_text(launch, encoding='utf-8')
                host_config = helper.config(project, 'houdini', bootstrap, api)
                host_config.update(version=version, session_seconds=120)
                nuke_config = helper.config(project, 'nuke', support.SOFTWARE_PYTHON, api)
                nuke_config['session_seconds'] = 120
                support.prepare_graph(project, app=None, scheduler_root=project / 'scheduler',
                    execution_profile=True, render_profile=True,
                    production_host_config=host_config, production_nuke_config=nuke_config)
                process = None
                lifecycle = {}
                probe = project / 'rbd-native-calls.jsonl'
                phase_file = probe.with_suffix('.phase.json')
                with patch.dict(os.environ, {'BRIDGE_TEST_NATIVE_ROOT': str(support.ROOT),
                        'BRIDGE_TEST_NATIVE_VERSION': version,
                        'BRIDGE_TEST_RBD_NATIVE_PROBE': str(probe),
                        'HOUDINI_BRIDGE_STATE_DIR': str(project / 'bridge-state'),
                        'BRIDGE_SKILLS_STATE_ROOT': str(project / 'runtime-state')}):
                    try:
                        process = helper.boot(project)
                        for index, asset in enumerate(helper.tool(process, 'catalog', {})['assets']):
                            helper.tool(process, 'submit_observation', dict(asset_id=asset['asset_id'],
                                request_id='rbd-observation-' + str(index), observation=dict(
                                    description='fixed actual packed geometry boundary', dominant_colors=['grey'])))
                        proposal = helper.tool(process, 'graph_propose', dict(request_id='rbd-proposal',
                            proposal=dict(schema='bridge.registered-domain-construction/1',
                                          domain_pack='rbd_destruction_v1', houdini_version=version)))
                        self.assertIn('graph_id', proposal, proposal)
                        trial = helper.completed_graph_trial(process, project,
                            dict(graph_id=proposal['graph_id'], request_id='rbd-trial'))
                        lifecycle['trial'] = trial
                        errors = [path.read_text(encoding='utf-8', errors='replace')[-32768:]
                                  for path in project.rglob('error.txt')]
                        for path in project.rglob('journal.sqlite3'):
                            with closing(sqlite3.connect(path)) as database:
                                errors.extend(row[0] for row in database.execute('SELECT payload FROM entries')
                                              if json.loads(row[0]).get('status') != 'COMPLETE')
                        self.assertEqual(trial.get('state'), 'SUCCEEDED', str(trial) + '\n' + '\n'.join(errors))
                        self.assertTrue(trial['stop_confirmed'])
                        roles = {address.rsplit('/', 1)[-1]: path
                                 for address, path in trial['result']['topology']['nodes'].items()}
                        state = json.loads((project / 'control/production-hosts.json').read_text(encoding='utf-8'))
                        client = production_host_client(state['hosts']['houdini'], project / 'probe')
                        client.bind_task(state['task_id'])
                        before = client.call('ping', {})['task_host_identity']
                        client.call('node.set_parms', dict(path=roles['solver'], parms={'usescale': 0}))
                        params = dict(task_id=state['task_id'], constraints={'fx': dict(
                            domain_pack='rbd_destruction_v1', run_mode='diagnose', changes={'velocity_variance': 0.})})
                        phase_file.write_text(json.dumps('zero_apply'), encoding='utf-8')
                        applied = client.call('agent.fx.apply_candidate', params)
                        lifecycle['applied'] = applied
                        self.assertEqual(applied['native_geometry_readback']['controls'], {'velocity_variance': 0.})
                        names = ['snippet', 'class', 'group', 'vex_precision', 'exportlist', 'bindings']
                        saved_parameters = client.call('node.parms', dict(path=roles['rbd_velocity'], names=names))['parms']
                        zero_events = [json.loads(line) for line in probe.read_text(encoding='utf-8').splitlines()
                                       if json.loads(line).get('phase') == 'zero_apply']
                        before_registration = {event['key']: event['value'] for event in zero_events
                                               if event['kind'] == 'userdata_read'}
                        self.assertEqual(set(before_registration),
                            {'bridge_rbd_velocity_basis_v1', 'bridge_rbd_velocity_program_v1'})
                        phase_file.write_text(json.dumps('nonzero_refusal'), encoding='utf-8')
                        params['constraints']['fx']['changes']['velocity_variance'] = 2.
                        with self.assertRaises(BridgeError) as mismatch:
                            client.call('agent.fx.apply_candidate', params)
                        self.assertEqual(mismatch.exception.code, 'CANDIDATE_APPLY_FAILED')
                        self.assertIn('RBD_ACTUAL_VELOCITY_CONSUMPTION_MISMATCH', str(mismatch.exception))
                        self.assertEqual(client.call('node.parms', dict(path=roles['rbd_velocity'], names=names))['parms'], saved_parameters)
                        rejected_write_events = [json.loads(line) for line in probe.read_text(encoding='utf-8').splitlines()
                                                 if json.loads(line).get('phase') == 'nonzero_refusal']
                        rolled_back_registration = {event['key']: event['value'] for event in rejected_write_events
                                                    if event['kind'] == 'userdata_read'}
                        self.assertEqual(rolled_back_registration, before_registration)
                        phase_file.write_text(json.dumps('save_checkpoint'), encoding='utf-8')
                        saved = helper.tool(process, 'task_save', {})
                        lifecycle['saved'] = saved
                        self.assertIn('saved_scene_id', saved, saved)
                        checkpoint = saved['scene_contract']['rbd_velocity_checkpoint']
                        self.assertEqual(checkpoint['schema'], 'bridge.rbd-velocity-checkpoint/1')
                        self.assertEqual(checkpoint['native_version'], version)
                        self.assertEqual(checkpoint['identity'], before)
                        self.assertTrue(checkpoint['parameters'])
                        self.assertTrue(checkpoint['wires'])
                        self.assertEqual(set(checkpoint['data']),
                            {'bridge_rbd_velocity_basis_v1', 'bridge_rbd_velocity_program_v1'})
                        saved_basis = json.loads(checkpoint['data']['bridge_rbd_velocity_basis_v1'])
                        saved_program = json.loads(checkpoint['data']['bridge_rbd_velocity_program_v1'])
                        self.assertIs(type(saved_basis['task_seed']), int)
                        self.assertEqual(saved_program['basis_sha256'], saved_basis['content_sha256'])
                        self.assertEqual(saved_program['value'], 0.)
                        self.assertEqual(checkpoint['data'], before_registration)
                        store_path, _, saved_receipt = self.saved_store(project, saved)
                        self.assertEqual(saved_receipt['scene_contract']['rbd_velocity_checkpoint'], checkpoint)
                        helper.close(process)
                        process = None
                        stopped, stop_fact = self.verified_stop(project, state, before)
                        process = helper.boot(project)
                        reopened = helper.tool(process, 'task_reopen', dict(saved_scene_id=saved['saved_scene_id']))
                        lifecycle['reopened'] = reopened
                        self.assertTrue(reopened.get('parameters_verified'), reopened)
                        self.assertTrue(reopened.get('nodes_verified'), reopened)
                        self.assertTrue(reopened.get('connections_verified'), reopened)
                        self.assertTrue(reopened.get('rbd_velocity_restored'), reopened)
                        state = json.loads((project / 'control/production-hosts.json').read_text(encoding='utf-8'))
                        client = production_host_client(state['hosts']['houdini'], project / 'reopen-probe')
                        client.bind_task(state['task_id'])
                        after = client.call('ping', {})['task_host_identity']
                        self.assertNotEqual(before['pid'], after['pid'])
                        self.assertNotEqual(before['launch_nonce'], after['launch_nonce'])
                        self.assertEqual(client.call('node.parms', dict(path=roles['rbd_velocity'], names=names))['parms'], saved_parameters)
                        original_frame = client.call('scene.info', {})['frame']
                        phase_file.write_text(json.dumps('direct_readback'), encoding='utf-8')
                        observation = dict(task_id=state['task_id'], constraints={'fx': dict(
                            domain_pack='rbd_destruction_v1', run_mode='diagnose', frames=[1])},
                            render={'frame_range': {'start': 1, 'end': 1, 'step': 1}})
                        evidence = client.call('agent.fx.collect_evidence', observation)['evidence']
                        self.assertEqual(set(evidence['native_geometry_readback']), {'1'})
                        direct_readback = evidence['native_geometry_readback']['1']
                        self.assertEqual(direct_readback['controls'], {'velocity_variance': 0.})
                        self.assertEqual(direct_readback['evidence_scope'], 'packed_initial_velocity_carrier')
                        self.assertEqual(direct_readback['native_simulation'], 'NOT_RUN')
                        self.assertEqual(direct_readback['actual_consumer_geometry'],
                            applied['native_geometry_readback']['actual_consumer_geometry'])
                        self.assertEqual(client.call('scene.info', {})['frame'], original_frame)
                        self.assertEqual(client.call('node.parms', dict(path=roles['rbd_velocity'], names=names))['parms'], saved_parameters)
                        direct_events = [json.loads(line) for line in probe.read_text(encoding='utf-8').splitlines()
                                         if json.loads(line).get('phase') == 'direct_readback']
                        self.assertFalse([event for event in direct_events if event['kind'] in ('parm_write', 'userdata_write')])
                        self.assertTrue(direct_events)
                        self.assertEqual({event['pid'] for event in direct_events}, {after['pid']})
                        actual_registration = {event['key']: event['value'] for event in direct_events
                                               if event['kind'] == 'userdata_read'}
                        self.assertEqual(actual_registration, checkpoint['data'])
                        lifecycle = dict(trial=trial, applied=applied, mismatch_code=mismatch.exception.code,
                            mismatch_detail=str(mismatch.exception),
                            saved=saved, stop_before_reopen=stopped, reopened=reopened, host_before=before,
                            verified_owned_stop_fact=stop_fact,
                            host_after=after, parameters=saved_parameters, direct_readback=direct_readback,
                            saved_checkpoint=checkpoint, saved_basis=saved_basis, saved_program=saved_program,
                            reopened_basis=json.loads(actual_registration['bridge_rbd_velocity_basis_v1']),
                            reopened_program=json.loads(actual_registration['bridge_rbd_velocity_program_v1']),
                            task_seed=saved_basis['task_seed'], direct_readback_native_events=direct_events,
                            registration_before_nonzero=before_registration,
                            registration_after_rollback=rolled_back_registration,
                            original_frame=original_frame, restored_frame=client.call('scene.info', {})['frame'],
                            checkpoint_refusals=[],
                            scope='verified R05 checkpoint/new PID zero baseline software boundary; native simulation NOT_RUN')
                        helper.close(process)
                        process = None
                        positive_stop, positive_stop_fact = self.verified_stop(project, state, after)
                        lifecycle['stop_after_direct_readback'] = positive_stop
                        lifecycle['verified_positive_stop_fact'] = positive_stop_fact
                        original_store = store_path.read_bytes()
                        for corruption in ('missing_checkpoint', 'tampered_checkpoint'):
                            store = json.loads(original_store)
                            receipt = next(receipt for receipt in reversed(store['saves'])
                                if Path(receipt['path']).resolve() == Path(saved['path']).resolve()
                                and receipt['sha256'] == saved['sha256'])
                            contract = receipt['scene_contract']
                            if corruption == 'missing_checkpoint':
                                del contract['rbd_velocity_checkpoint']
                            else:
                                contract['rbd_velocity_checkpoint']['schema'] = 'bridge.invalid-rbd-checkpoint/0'
                            receipt['scene_contract_sha256'] = hashlib.sha256(json.dumps(
                                contract, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')).encode('utf-8')).hexdigest()
                            store_path.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')
                            try:
                                phase_file.write_text(json.dumps(corruption), encoding='utf-8')
                                process = helper.boot(project)
                                refused_state = json.loads((project / 'control/production-hosts.json').read_text(encoding='utf-8'))
                                refused_client = production_host_client(refused_state['hosts']['houdini'],
                                    project / (corruption + '-probe'))
                                refused_client.bind_task(refused_state['task_id'])
                                refused_identity = refused_client.call('ping', {})['task_host_identity']
                                self.assertNotEqual(refused_identity['pid'], after['pid'])
                                self.assertNotEqual(refused_identity['launch_nonce'], after['launch_nonce'])
                                refusal = helper.tool(process, 'task_reopen', dict(saved_scene_id=saved['saved_scene_id']))
                                lifecycle['checkpoint_refusals'].append(dict(
                                    corruption=corruption, result=refusal, host_before=refused_identity,
                                    rewritten_contract_sha256=receipt['scene_contract_sha256']))
                                self.assertTrue(refusal.get('isError'), refusal)
                                self.assertRegex(refusal.get('text', ''),
                                    r'RBD_[A-Z_]+|ARTIFACT_STRUCTURE_MISMATCH|ARTIFACT_CONTRACT_INVALID')
                                self.assertEqual(hashlib.sha256(Path(saved['path']).read_bytes()).hexdigest(), saved['sha256'])
                                rejected_events = [json.loads(line) for line in probe.read_text(encoding='utf-8').splitlines()
                                                   if json.loads(line).get('phase') == corruption]
                                load_ends = [index for index, event in enumerate(rejected_events) if event['kind'] == 'hip_load_end']
                                after_load = rejected_events[load_ends[-1] + 1:] if load_ends else rejected_events
                                self.assertFalse([event for event in after_load if event['kind'] in ('parm_write', 'userdata_write')])
                                self.assertFalse([event for event in rejected_events if event['kind'] == 'userdata_write'])
                                lifecycle['checkpoint_refusals'][-1]['native_events'] = rejected_events
                                helper.close(process)
                                process = None
                                refused_stop, refused_stop_fact = self.verified_stop(project, refused_state, refused_identity)
                                lifecycle['checkpoint_refusals'][-1].update(
                                    stop=refused_stop, verified_owned_stop_fact=refused_stop_fact)
                            finally:
                                store_path.write_bytes(original_store)
                    finally:
                        if process is not None:
                            helper.close(process)
                        final_stop = stop_hosts(project / 'control')
                        archive = os.environ.get('BRIDGE_TEST_RBD_AUTHORITY_ARCHIVE')
                        if archive:
                            target = Path(archive) / version
                            target.mkdir(parents=True, exist_ok=False)
                            (target / 'lifecycle.json').write_text(json.dumps(lifecycle, ensure_ascii=False, indent=2), encoding='utf-8')
                            (target / 'stop.json').write_text(json.dumps(final_stop, ensure_ascii=False, indent=2), encoding='utf-8')
                            if probe.is_file():
                                shutil.copyfile(probe, target / 'native-api-calls.jsonl')
                            snapshot = project / 'control/snapshot'
                            rows = []
                            for path in sorted(snapshot.rglob('*.py')):
                                relative = path.relative_to(snapshot)
                                original = support.ROOT / relative
                                rows.append(dict(path=relative.as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    current_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest() if original.is_file() else None))
                            (target / 'snapshot-code.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
                            for path in project.rglob('*.log'):
                                if path.name in {'child.stderr.log', 'child.stdout.log', 'supervisor.stderr.log', 'supervisor.stdout.log'}:
                                    destination = target / 'logs' / path.relative_to(project)
                                    destination.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copyfile(path, destination)
                            for filename in ('error.txt', 'result.json', 'completion.json'):
                                for path in project.rglob(filename):
                                    destination = target / 'job-results' / path.relative_to(project)
                                    destination.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copyfile(path, destination)
