"""Swarm software HOM persistence across two genuinely supervised Python PIDs.

Runs current task_host.start/task_host_serve and authenticated loopback HTTP/TCP.
Only HOM is substituted. No DCC, simulation, cache, model or render is executed.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get('BRIDGE_TEST_NATIVE_CONTROLS_ARCHIVE') or
              ROOT / 'outputs/native-controls-new-process')
PACKAGES = ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')
CHANGES = {'target_noise': 2.0, 'noise_strength': 8.0}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_owned_stop(case, handle, stopped):
    """Require the signed child wait and the platform's observed tree exit."""
    case.assertEqual(stopped['observed_by'], 'owned_child_wait')
    case.assertEqual(stopped['pid'], handle.pid)
    case.assertEqual(stopped['identity'], handle.identity)
    case.assertEqual(stopped['exit_code'], 0)
    if os.name == 'nt':
        case.assertTrue(stopped['child_wait_observed'])
        case.assertEqual(stopped['job_active_processes'], 0)
    else:
        # The production supervisor signs stopped only after wait() and an
        # ESRCH process-group observation. Verify that group remains absent.
        case.assertNotEqual(handle.pid, os.getpgrp())
        with case.assertRaises(ProcessLookupError):
            os.killpg(handle.pid, 0)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_isolated_test(case, version, output_root):
    selected = type(case).__name__ + '.' + case._testMethodName
    if type(case).__module__ == '__main__' and selected in sys.argv[1:]:
        case.run_version(version)
        return
    module = sys.modules[type(case).__module__]
    directory = output_root / ('driver-' + version + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    command = [str(Path(getattr(sys, '_base_executable', None) or sys.executable).resolve()),
               '-B', str(Path(module.__file__).resolve()), selected]
    environment = {name: value for name, value in os.environ.items()
                   if name.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'USERPROFILE'}}
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    for key in ('BRIDGE_TEST_NATIVE_CONTROLS_ARCHIVE', 'BRIDGE_TEST_MATERIAL_CONTROLS_ARCHIVE'):
        if os.environ.get(key):
            environment[key] = str(Path(os.environ[key]).resolve())
    record = {'argv': command, 'cwd': str(ROOT), 'parent_pid': os.getpid(),
              'timeout_seconds': 120, 'version': version, 'selected_test': selected,
              'test_sha256': digest(Path(module.__file__).resolve()), 'timed_out': False}
    started_at = time.monotonic()
    try:
        with (directory / 'stdout.log').open('wb') as output, (directory / 'stderr.log').open('wb') as errors:
            process = subprocess.Popen(command, cwd=ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            record['driver_pid'] = process.pid
            try:
                record['exit_code'] = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                record['timed_out'] = True
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                record['exit_code'] = process.returncode
    except BaseException as error:
        record['error'] = repr(error)
        raise
    finally:
        record['elapsed_seconds'] = time.monotonic() - started_at
        write_json(directory / 'command.json', record)
        print('ISOLATED_TEST_DRIVER', str(directory / 'command.json'), flush=True)
    case.assertFalse(record['timed_out'], 'driver timeout; evidence retained at ' + str(directory))
    case.assertEqual(record['exit_code'], 0,
        (directory / 'stdout.log').read_text(encoding='utf-8', errors='replace') +
        (directory / 'stderr.log').read_text(encoding='utf-8', errors='replace'))


def freeze(destination):
    files = []
    for package in PACKAGES:
        files.extend((ROOT / 'packages' / package / 'src').rglob('*.py'))
    files.extend((ROOT / 'plugins/houdini').rglob('*.py'))
    files.extend((ROOT / 'docs/native-basis').glob('*.json'))
    files.extend(ROOT / name for name in (
        'tools/native_schema_test_boundary.py', 'tools/software_render_api_boundary.py',
        'tests/helpers/swarm_api_fixture.py', 'tests/unit/software_host_bootstrap.py',
        'tests/unit/test_native_swarm_controls.py', 'tests/unit/test_native_controls_new_process.py'))
    records = []
    for source in sorted(set(files)):
        relative = source.relative_to(ROOT)
        payload = source.read_bytes()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        source_sha = hashlib.sha256(payload).hexdigest()
        if digest(source) != source_sha:
            raise RuntimeError('SOURCE_CHANGED_DURING_FREEZE:' + str(relative))
        records.append({'path': relative.as_posix(), 'sha256': source_sha})
    write_json(destination.parent / 'source-manifest.json', records)
    return records


BOOTSTRAP_NATIVE = '''
sys.dont_write_bytecode=True
sys.path.insert(0,str(snapshot/'tests/unit'))
from test_native_swarm_controls import load_fixture
api=load_fixture('new_process_stage_api',snapshot/'tools/software_render_api_boundary.py')
native=load_fixture('new_process_native_api',snapshot/'tools/native_schema_test_boundary.py')
fixture=load_fixture('new_process_swarm_api',snapshot/'tests/helpers/swarm_api_fixture.py')
version=os.environ['BRIDGE_SWARM_VERSION']
interfaces,states,ports=api.interface_profiles(snapshot,version)
native.constrain_hou(snapshot/'docs/native-basis/hda-interface-capture.json',version,
    instance_states=states,native_api_interfaces=interfaces,native_api_ports=ports)
hou=sys.modules['hou']
api.install_stage_api(hou)
fixture.install_time_api(hou)
events=runner.parent/'calls.jsonl'
def trace_calls(frame,event,arg):
    if event=='call' and frame.f_code.co_filename==str(addon_source):
        name=frame.f_code.co_name
        if name=='dispatch' or name=='_fx_apply_candidate':
            with events.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'pid':os.getpid(),'function':name,
                    'command':frame.f_locals.get('command')})+'\\n')
    return trace_calls
sys.setprofile(trace_calls)
'''

BOOTSTRAP_COLLECT = '''
sys.setprofile(None)
import hashlib
request=json.loads(Path(os.environ['BRIDGE_SWARM_REQUEST']).read_text(encoding='utf-8'))
task=request['task_id']
root,manifest=addon._fx_manifest(task)
domain,pack=addon._fx_pack(request)
observed=addon._fx_swarm_host().readback(manifest['nodes'],pack,
    {'target_noise':2.0,'noise_strength':8.0})
hip=Path(hou.hipFile.path())
record={'pid':os.getpid(),'identity':addon._host_identity(),
    'collector':'addon._fx_swarm_host().readback','readback':observed,
    'hip_path':str(hip),'hip_sha256':hashlib.sha256(hip.read_bytes()).hexdigest(),
    'software_hom_only':True,'native_execution_claim':False}
(runner.parent/'collector.json').write_text(json.dumps(record,sort_keys=True,allow_nan=False),encoding='utf-8')
print('SWARM_DIRECT_COLLECTOR',json.dumps(record,sort_keys=True),flush=True)
'''


class NativeControlsNewProcessTests(unittest.TestCase):
    def run_version(self, version):
        started_at = time.monotonic()
        run = OUTPUT / ('run-' + version + '-' + uuid.uuid4().hex[:8])
        snapshot = run / 'frozen'
        records = freeze(snapshot)
        for package in PACKAGES:
            sys.path.insert(0, str(snapshot / 'packages' / package / 'src'))
        from houdini_bridge import task_host
        from houdini_bridge.client import HoudiniClient
        from dcc_task_runtime.owned_process import OwnedProcessHandle, read_receipt
        bootstrap = load_module('new_process_bootstrap', snapshot / 'tests/unit/software_host_bootstrap.py')
        fixture = load_module('new_process_basis', snapshot / 'tests/helpers/swarm_api_fixture.py')
        script = run / 'software-launch.py'
        script.write_text(bootstrap.BOOTSTRAP_SETUP + BOOTSTRAP_NATIVE + bootstrap.BOOTSTRAP_RUN
                          + BOOTSTRAP_COLLECT, encoding='utf-8')
        task = 'swarm-new-process-' + version.replace('.', '-')
        params = {'task_id': task, 'constraints': {'fx': {
            'domain_pack': 'swarm_flocking_v1', 'run_mode': 'diagnose', 'frames': [1, 2],
            'swarm_basis': fixture.swarm_basis()}},
            'render': {'frame_range': {'start': 1, 'end': 2, 'step': 1}}}
        request = run / 'request.json'
        write_json(request, params)
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC', 'USERPROFILE'}}
        environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
            LOCALAPPDATA=str(run / 'localappdata'),
            HOUDINI_BRIDGE_STATE_DIR=str(run / 'instances'),
            BRIDGE_SKILLS_STATE_ROOT=str(run / 'runtime'),
            BRIDGE_SKILLS_SCHEDULER_ROOT=str(run / 'scheduler'),
            BRIDGE_SWARM_VERSION=version, BRIDGE_SWARM_REQUEST=str(request))
        result = {'version': version, 'scope': 'software_task_host_api_only',
                  'graph_status': 'NOT_RUN', 'real_host_status': 'NOT_RUN',
                  'source_manifest_sha256': digest(run / 'source-manifest.json'),
                  'software_launch_sha256': digest(script), 'children': []}
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
                        allow_software_processes=True, environment=environment,
                        max_seconds=120, ready_timeout=20, poll_seconds=.02, warmup=False,
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
                    handle = OwnedProcessHandle(binding['directory'], binding['identity'])
                    handles.append(handle)
                    self.assertEqual(handle.pid, ready['pid'])
                    self.assertEqual(ready['addon_sha256'], digest(snapshot / 'plugins/houdini/_impl/houdini_bridge_addon.py'))
                    token_root = run / 'instances/instances'
                    instance = json.loads((token_root / (str(handle.pid) + '.json')).read_text())
                    token = (token_root / instance['token_file']).read_text()
                    client = HoudiniClient(ready['port'], token=token, timeout_seconds=25)
                    self.assertEqual(client.health()['task_host_identity']['launch_nonce'], ready['launch_nonce'])
                    if index == 1:
                        built = client.call('agent.fx.build_preview', params)
                        applied = client.call('agent.fx.apply_candidate', {
                            **params, 'constraints': {'fx': {**params['constraints']['fx'], 'changes': CHANGES}}})
                        saved = client.call('scene.save_hip', {'task_id': task,
                            'path': str(run / 'swarm.hip'),
                            'root_path': built['scene_manifest']['execution_root']})
                        self.assertEqual(saved['sha256'], digest(run / 'swarm.hip'))
                        result.update(build=built, apply=applied, save=saved)
                    else:
                        first = result['children'][0]
                        self.assertNotEqual(handle.pid, first['ready']['pid'])
                        self.assertNotEqual(ready['launch_nonce'], first['ready']['launch_nonce'])
                        with self.assertRaisesRegex(ValueError, 'SUPERVISOR_RECEIPT_MISMATCH'):
                            read_receipt(binding['directory'], 'started', identity={
                                **binding['identity'], 'launch_nonce': first['ready']['launch_nonce']})
                        result['stale_nonce_rejection'] = 'SUPERVISOR_RECEIPT_MISMATCH'
                        result['reopen'] = client.call('scene.reopen_task_hip', {
                            'task_id': task, 'path': saved['path'], 'sha256': saved['sha256']})
                        self.assertTrue(result['reopen']['parameters_verified'])
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
                    self.assertEqual(collector['readback']['controls'], CHANGES)
                    self.assertEqual(collector['hip_sha256'], saved['sha256'])
                    calls = [json.loads(line) for line in (work / 'calls.jsonl').read_text().splitlines()]
                    if index == 2:
                        self.assertFalse(any(call['function'] == '_fx_apply_candidate' for call in calls))
                        self.assertFalse(any(call['command'] in ('agent.fx.build_preview', 'agent.fx.apply_candidate') for call in calls))
                        self.assertEqual(collector['readback'], first['collector']['readback'])
                    result['children'].append({'ready': ready, 'started': handle.started,
                        'stop': json.loads(output.getvalue()), 'stopped': stopped, 'collector': collector,
                        'calls': calls})
            for record in records:
                self.assertEqual(digest(snapshot / record['path']), record['sha256'])
            result['status'] = 'PASS'
        except BaseException as error:
            result.update(status='BLOCKED', error=repr(error))
            raise
        finally:
            for handle in handles:
                if handle.poll() is None:
                    handle.terminate()
                    handle.wait(10)
                task_host._ACTIVE_CHILDREN.pop(handle.pid, None)
            result['elapsed_seconds'] = time.monotonic() - started_at
            write_json(run / 'result.json', result)
            print('NEW_PROCESS_RESULT', str(run / 'result.json'), result.get('status'), flush=True)

    @unittest.skipUnless(os.name in ('nt', 'posix'), 'requires supported process-tree supervision')
    def test_swarm_houdini21_new_process(self):
        run_isolated_test(self, '21.0.631', OUTPUT)

    @unittest.skipUnless(os.name in ('nt', 'posix'), 'requires supported process-tree supervision')
    def test_swarm_houdini22_new_process(self):
        run_isolated_test(self, '22.0.429', OUTPUT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
