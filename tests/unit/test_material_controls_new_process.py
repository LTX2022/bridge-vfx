"""Material 11-control persistence in two supervised software Python processes.

Run one selected version per interpreter, with the central channel allocated.
Only bottom HOM/USD is substituted; current addon dispatch, writer, collectors,
TCP transport and signed platform process-tree supervision are exercised unchanged.
No graph acceptance, registry completion, DCC, model or render is claimed.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import uuid

from test_native_controls_new_process import (
    PACKAGES, assert_owned_stop, digest, freeze, load_module, run_isolated_test, write_json,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get('BRIDGE_TEST_MATERIAL_CONTROLS_ARCHIVE') or
              ROOT / 'outputs/material-controls-new-process')
DOMAIN = 'material_lookdev_v1'
CHANGES = {
    'base_color': [0.7200000000000001] * 3, 'roughness': 0.22000000000000003,
    'ior': 1.65, 'transmission': 0.01, 'subsurface': 0.01, 'normal_strength': 1.1,
    'specular_weight': 0.9, 'coat_weight': 0.01, 'anisotropy': 0.01,
    'displacement_scale': 1.1, 'emission_weight': 0.01,
}
HISTORY = ('outputs/windows-followup-20261004/repair-staging/consumer-integration-2300/'
           'outputs/formal-material-controls-json-fix-20261005')


BOOTSTRAP_NATIVE = '''
sys.dont_write_bytecode=True
import importlib.util
def injected_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
api=injected_module('material_stage_api',snapshot/'tools/software_render_api_boundary.py')
native=injected_module('material_native_api',snapshot/'tools/native_schema_test_boundary.py')
version=os.environ['BRIDGE_MATERIAL_VERSION']
interfaces,states,ports=api.interface_profiles(snapshot,version)
native.constrain_hou(snapshot/'docs/native-basis/hda-interface-capture.json',version,
    instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
hou=sys.modules['hou']
api.install_stage_api(hou)
request=json.loads(Path(os.environ['BRIDGE_MATERIAL_REQUEST']).read_text(encoding='utf-8'))
from houdini_bridge.native_render_domains import control_contract
contract=control_contract('material_lookdev_v1',version)
def finite_json(value):
    return json.loads(json.dumps(value,sort_keys=True,allow_nan=False))
def native_controls():
    root,manifest=addon._fx_manifest(request['task_id'])
    domain,pack=addon._fx_pack(request)
    roles=manifest['nodes']
    fields=[]
    for name,item in contract.items():
        for field in item['aliases']:
            fields.append({'control':name,'role':item['role'],'parm':field,
                'observation':addon._fx_native_field_observation(hou.node(roles[item['role']]),field)})
    semantic=addon._fx_render_domain_readback(domain,dict.fromkeys(contract),roles,pack)
    return finite_json({'controls':semantic,'native_fields':fields})
fresh={'pid':os.getpid(),'scene_node_count':sum(len(hou.node(path).allSubChildren())
    for path in ('/obj','/stage','/mat')),'hip_path':hou.hipFile.path()}
(runner.parent/'fresh-scene.json').write_text(json.dumps(fresh),encoding='utf-8')
events=runner.parent/'calls.jsonl'
probes=runner.parent/'native-probes.jsonl'
watched={'dispatch','_fx_build_preview','_fx_apply_candidate','_fx_initialize_render_domain',
    '_set_parm_verified','_fx_apply_parameter_sets'}
def trace_calls(frame,event,arg):
    if frame.f_code.co_filename!=str(addon_source):return trace_calls
    name=frame.f_code.co_name
    command=frame.f_locals.get('command')
    if event=='call' and name in watched:
        with events.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'pid':os.getpid(),'function':name,'command':command})+'\\n')
    if event=='return' and name=='dispatch' and isinstance(arg,dict) and command in {
            'agent.fx.build_preview','agent.fx.apply_candidate','scene.save_hip','scene.reopen_task_hip'}:
        record={'pid':os.getpid(),'command':command,'native_readback':native_controls()}
        with probes.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(record,sort_keys=True,allow_nan=False)+'\\n')
    return trace_calls
sys.setprofile(trace_calls)
'''

BOOTSTRAP_COLLECT = '''
sys.setprofile(None)
import hashlib
root,manifest=addon._fx_manifest(request['task_id'])
domain,pack=addon._fx_pack(request)
roles=manifest['nodes']
observed=native_controls()
observed['native_static_readback']=addon._fx_static_domain_readback(domain,roles,pack)
binding=observed['native_static_readback']['usd_binding_readback']
terminal=hou.node(roles['settings_binding'])
stage=terminal.stage(frame=hou.frame(),apply_viewport_overrides=False,ignore_errors=False)
observed['final_lop_path']=terminal.path()
observed['material_binding_targets']=[str(path) for path in stage.GetPrimAtPath(
    binding['geometry_prefix']).GetRelationship('material:binding').GetTargets()]
observed['render_configuration']=addon._fx_render_configuration(hou.node(roles['render']),[1,2])
hip=Path(hou.hipFile.path())
record={'pid':os.getpid(),'identity':addon._host_identity(),
    'collectors':['_fx_render_domain_readback','_fx_native_field_observation',
        '_fx_static_domain_readback','_fx_render_configuration'],
    'readback':finite_json(observed),'hip_path':str(hip),
    'hip_sha256':hashlib.sha256(hip.read_bytes()).hexdigest(),
    'software_hom_usd_only':True,'native_execution_claim':False}
(runner.parent/'collector.json').write_text(json.dumps(record,sort_keys=True,allow_nan=False),encoding='utf-8')
print('MATERIAL_DIRECT_COLLECTOR',json.dumps(record,sort_keys=True),flush=True)
'''


class MaterialControlsNewProcessTests(unittest.TestCase):
    def assert_native_readback(self, record, expected):
        self.assertEqual(record['controls'], expected)
        self.assertEqual({field['control'] for field in record['native_fields']}, set(CHANGES))
        self.assertEqual(len(record['native_fields']), 11)
        for field in record['native_fields']:
            observation = field['observation']
            self.assertEqual(observation['origin'], 'runtime_hom')
            self.assertEqual(observation['value'], expected[field['control']])
            self.assertFalse(any(observation[key] for key in ('locked', 'disabled', 'hidden')))

    def run_version(self, version):
        started_at = time.monotonic()
        run = OUTPUT / ('run-' + version + '-' + uuid.uuid4().hex[:8])
        snapshot = run / 'frozen'
        records = freeze(snapshot)
        relative = 'tests/unit/test_material_controls_new_process.py'
        source = ROOT / relative
        payload = source.read_bytes()
        (snapshot / relative).write_bytes(payload)
        self.assertEqual(digest(source), digest(snapshot / relative))
        records.append({'path': relative, 'sha256': digest(snapshot / relative)})
        write_json(run / 'source-manifest.json', records)
        for package in PACKAGES:
            sys.path.insert(0, str(snapshot / 'packages' / package / 'src'))
        from houdini_bridge import task_host, native_render_domains
        from houdini_bridge.client import HoudiniClient
        from dcc_task_runtime import owned_process
        for module in (task_host, native_render_domains, owned_process):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(snapshot),
                            'Run each selected version in a fresh interpreter; dependency already imported')
        bootstrap = load_module('material_process_bootstrap', snapshot / 'tests/unit/software_host_bootstrap.py')
        self.assertEqual(set(native_render_domains.control_contract(DOMAIN, version)), set(CHANGES))
        script = run / 'software-launch.py'
        script.write_text(bootstrap.BOOTSTRAP_SETUP + BOOTSTRAP_NATIVE + bootstrap.BOOTSTRAP_RUN
                          + BOOTSTRAP_COLLECT, encoding='utf-8')
        task = 'material-new-process-' + version.replace('.', '-')
        params = {'task_id': task, 'constraints': {'fx': {
            'domain_pack': DOMAIN, 'run_mode': 'diagnose', 'frames': [1, 2]}},
            'render': {'frame_range': {'start': 1, 'end': 2, 'step': 1}}}
        request = run / 'request.json'
        write_json(request, params)
        write_json(run / 'candidate-inputs.json', {'source': HISTORY + '/TWO_VERSIONS.md',
            'purpose': 'explicit test candidate values only; historical results are not reused as evidence',
            'controls': CHANGES})
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'USERPROFILE'}}
        environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
            LOCALAPPDATA=str(run / 'localappdata'), HOUDINI_BRIDGE_STATE_DIR=str(run / 'instances'),
            BRIDGE_SKILLS_STATE_ROOT=str(run / 'runtime'), BRIDGE_SKILLS_SCHEDULER_ROOT=str(run / 'scheduler'),
            BRIDGE_MATERIAL_VERSION=version, BRIDGE_MATERIAL_REQUEST=str(request))
        result = {'version': version, 'scope': 'software_task_host_api_persistence_only',
            'graph_status': 'NOT_RUN', 'real_host_status': 'NOT_RUN', 'metadata_status': 'BLOCKED',
            'registry_status': 'BLOCKED', 'registry_blocker': 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED',
            'source_manifest_sha256': digest(run / 'source-manifest.json'),
            'software_launch_sha256': digest(script), 'children': [], 'feedback': []}
        handles = []
        try:
            with patch.dict(os.environ, environment, clear=True):
                for index in (1, 2):
                    work = run / ('child' + str(index))
                    args = argparse.Namespace(task_id=task, work_dir=str(work),
                        addon_root=str(snapshot / 'plugins/houdini'), version=version,
                        houdini_bin=str(bootstrap.SOFTWARE_PYTHON),
                        supervisor_executable=str(bootstrap.SOFTWARE_PYTHON),
                        software_launch_script=str(script), evidence_source='software_test',
                        allow_software_processes=True, environment=environment, max_seconds=120,
                        ready_timeout=20, poll_seconds=.02, warmup=False,
                        resource_budget={'roots': [str(run)], 'max_bytes': 256 * 1024 * 1024})
                    output = io.StringIO()
                    with redirect_stdout(output):
                        returncode = task_host.start(args)
                    (work / 'start.stdout.log').write_text(output.getvalue(), encoding='utf-8')
                    write_json(work / 'start-command.json', {'entry': 'task_host.start',
                        'arguments': vars(args), 'exit_code': returncode})
                    self.assertEqual(returncode, 0, output.getvalue())
                    ready = json.loads(output.getvalue())
                    binding = json.loads((work / 'supervisor-binding.json').read_text())
                    handle = owned_process.OwnedProcessHandle(binding['directory'], binding['identity'])
                    handles.append(handle)
                    self.assertEqual(handle.pid, ready['pid'])
                    self.assertEqual(ready['addon_sha256'], digest(snapshot / 'plugins/houdini/_impl/houdini_bridge_addon.py'))
                    fresh = json.loads((work / 'fresh-scene.json').read_text())
                    self.assertEqual(fresh['pid'], handle.pid)
                    self.assertEqual(fresh['scene_node_count'], 0)
                    token_root = run / 'instances/instances'
                    instance = json.loads((token_root / (str(handle.pid) + '.json')).read_text())
                    token = (token_root / instance['token_file']).read_text()
                    client = HoudiniClient(ready['port'], token=token, timeout_seconds=25)
                    self.assertEqual(client.health()['task_host_identity']['launch_nonce'], ready['launch_nonce'])
                    if index == 1:
                        built = client.call('agent.fx.build_preview', params)
                        result['build'] = built
                        initial = json.loads((work / 'native-probes.jsonl').read_text().splitlines()[-1])['native_readback']
                        self.assertEqual(set(initial['controls']), set(CHANGES))
                        before = initial
                        for name, value in CHANGES.items():
                            self.assertNotEqual(before['controls'][name], value)
                            applied = client.call('agent.fx.apply_candidate', {**params,
                                'constraints': {'fx': {**params['constraints']['fx'], 'changes': {name: value}}}})
                            diffs = applied['parameter_diff']
                            self.assertEqual({item['semantic_control'] for item in diffs}, {name})
                            self.assertTrue(all(item['readback_verified'] is True for item in diffs))
                            after = json.loads((work / 'native-probes.jsonl').read_text().splitlines()[-1])['native_readback']
                            expected = {**before['controls'], name: value}
                            self.assert_native_readback(after, expected)
                            protected_before = [field for field in before['native_fields'] if field['control'] != name]
                            protected_after = [field for field in after['native_fields'] if field['control'] != name]
                            self.assertEqual(protected_after, protected_before)
                            result['feedback'].append({'name': name, 'before': before, 'after': after, 'result': applied})
                            before = after
                        saved = client.call('scene.save_hip', {'task_id': task,
                            'path': str(run / 'material.hip'), 'root_path': built['scene_manifest']['execution_root']})
                        self.assertEqual(saved['sha256'], digest(run / 'material.hip'))
                        self.assertTrue((run / 'material.hip').read_bytes().startswith(b'bridge.software_hom_snapshot/1\n'))
                        result['save'] = saved
                    else:
                        first = result['children'][0]
                        self.assertNotEqual(handle.pid, first['ready']['pid'])
                        self.assertNotEqual(ready['launch_nonce'], first['ready']['launch_nonce'])
                        with self.assertRaisesRegex(ValueError, 'SUPERVISOR_RECEIPT_MISMATCH'):
                            owned_process.read_receipt(binding['directory'], 'started', identity={
                                **binding['identity'], 'launch_nonce': first['ready']['launch_nonce']})
                        result['stale_nonce_rejection'] = 'SUPERVISOR_RECEIPT_MISMATCH'
                        result['reopen'] = client.call('scene.reopen_task_hip', {
                            'task_id': task, 'path': saved['path'], 'sha256': saved['sha256']})
                        for field in ('nodes_verified', 'parameters_verified', 'connections_verified'):
                            self.assertTrue(result['reopen'][field])
                        self.assertEqual(result['reopen']['sha256'], saved['sha256'])
                    output = io.StringIO()
                    with redirect_stdout(output):
                        returncode = task_host.stop(argparse.Namespace(work_dir=str(work), timeout=10, exit_grace=10))
                    (work / 'stop.stdout.log').write_text(output.getvalue(), encoding='utf-8')
                    write_json(work / 'stop-command.json', {'entry': 'task_host.stop', 'exit_code': returncode})
                    self.assertEqual(returncode, 0, output.getvalue())
                    self.assertEqual(handle.wait(5), 0)
                    stopped = handle.receipt()
                    assert_owned_stop(self, handle, stopped)
                    collector = json.loads((work / 'collector.json').read_text())
                    self.assertEqual(collector['pid'], handle.pid)
                    self.assertEqual(collector['identity']['launch_nonce'], ready['launch_nonce'])
                    self.assertEqual(collector['hip_sha256'], saved['sha256'])
                    readback = collector['readback']
                    self.assert_native_readback(readback, CHANGES)
                    native_static = readback['native_static_readback']
                    self.assertTrue(native_static['topology_and_parameters_verified'])
                    self.assertEqual(native_static['output_role'], 'settings_binding')
                    usd_binding = native_static['usd_binding_readback']
                    self.assertTrue(usd_binding['imported_prim_paths'])
                    self.assertEqual(readback['material_binding_targets'], [usd_binding['material_prim_path']])
                    self.assertEqual(set(readback['render_configuration']), {'1', '2'})
                    for configuration in readback['render_configuration'].values():
                        self.assertEqual(configuration['loppath'], readback['final_lop_path'])
                        self.assertTrue(all(configuration[field] for field in ('products', 'aovs', 'lights')))
                        self.assertEqual(configuration['exr_format']['storage'], 'scanline')
                    calls = [json.loads(line) for line in (work / 'calls.jsonl').read_text().splitlines()]
                    if index == 2:
                        self.assertFalse(any(call['function'] != 'dispatch' for call in calls))
                        self.assertFalse(any(call['command'] in ('agent.fx.build_preview', 'agent.fx.apply_candidate') for call in calls))
                        self.assertEqual(readback, first['collector']['readback'])
                        self.assertEqual([json.loads(line)['command'] for line in (work / 'native-probes.jsonl').read_text().splitlines()],
                                         ['scene.reopen_task_hip'])
                    result['children'].append({'ready': ready, 'started': handle.started, 'fresh': fresh,
                        'stop': json.loads(output.getvalue()), 'stopped': stopped, 'collector': collector, 'calls': calls})
            self.assertEqual(len(result['feedback']), 11)
            for record in records:
                self.assertEqual(digest(snapshot / record['path']), record['sha256'])
            result['persistence_status'] = 'PASS'
        except BaseException as error:
            result.update(persistence_status='BLOCKED', error=repr(error))
            raise
        finally:
            cleanup_errors = []
            for handle in handles:
                try:
                    if handle.poll() is None:
                        handle.terminate()
                        handle.wait(10)
                    task_host._ACTIVE_CHILDREN.pop(handle.pid, None)
                except Exception as error:
                    cleanup_errors.append({'pid': handle.pid, 'error': repr(error)})
            if cleanup_errors:
                result.update(persistence_status='BLOCKED', cleanup_errors=cleanup_errors)
            result['elapsed_seconds'] = time.monotonic() - started_at
            write_json(run / 'result.json', result)
            print('MATERIAL_NEW_PROCESS_RESULT', str(run / 'result.json'), result.get('persistence_status'), flush=True)
        self.assertEqual(result['persistence_status'], 'PASS', result.get('cleanup_errors'))

    @unittest.skipUnless(os.name in ('nt', 'posix'), 'requires supported process-tree supervision')
    def test_material_houdini21_new_process(self):
        run_isolated_test(self, '21.0.631', OUTPUT)

    @unittest.skipUnless(os.name in ('nt', 'posix'), 'requires supported process-tree supervision')
    def test_material_houdini22_new_process(self):
        run_isolated_test(self, '22.0.429', OUTPUT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
