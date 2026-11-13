"""Bounded prepared lighting recovery through Python/TCP and owned OS processes."""
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

from prepare_workbuddy_graph import prepare_graph
from software_host_bootstrap import HYTHON, BOOTSTRAP_RUN, SOFTWARE_PYTHON
import test_production_task_hosts as production_hosts
STRICT_RENDER_NATIVE = production_hosts.STRICT_RENDER_NATIVE
from test_nuke_task_host import FAKE
from vfx_pipeline.workbuddy_assembly import prepared_graph_facade
from vfx_pipeline.production_hosts import stop_hosts
from vfx_pipeline.graph_job_evidence import (atomic_json, file_sha256, graph_recovery_snapshot, process_identity,
                                             capture_prepared_graph_interruption, reconcile_prepared_graph_job)

AUDIT_NATIVE = '''
audit_path=Path(os.environ['BRIDGE_FORMAL_RECOVERY_AUDIT'])
def audit_native(method,target,label):
    original=getattr(target,method)
    def observed(*args,**kwargs):
        result=original(*args,**kwargs)
        with audit_path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'pid':os.getpid(),'native_api':label})+'\\n')
            stream.flush();os.fsync(stream.fileno())
        return result
    setattr(target,method,observed)
audit_native('createNode',Node,'hou.Node.createNode')
audit_native('save',hou.hipFile,'hou.hipFile.save')
audit_native('load',hou.hipFile,'hou.hipFile.load')
'''

RECOVERY_RUN = '''
pref=os.environ.get('HOUDINI_USER_PREF_DIR')
if pref:Path(pref).mkdir(parents=True,exist_ok=True)
if '--job' in sys.argv:
    recovery_source=Path(os.environ['BRIDGE_FORMAL_RECOVERY_WORKER'])
    if hashlib.sha256(recovery_source.read_bytes()).hexdigest() != 'RECOVERY_WORKER_SHA256':
        raise ValueError('FORMAL_RECOVERY_WORKER_SOURCE_CHANGED')
    spec=importlib.util.spec_from_file_location('formal_recovery_worker',recovery_source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.exit(module.prepared_graph_worker(json.loads(sys.argv[sys.argv.index('--job')+1])))
sys.argv=[str(runner),*sys.argv[2:]]
runpy.run_path(str(runner),run_name='__main__')
'''

OCIO_CONTEXT_DRIFT_NATIVE = '''
import types
ocio_fixture=Path(os.environ['BRIDGE_TEST_EXR_FIXTURE']).parent/'explicit-parent-config.ocio'
ocio_fixture.write_bytes(b'explicit bottom-level OCIO API fixture, not native writer proof')
ocio_context_state={'cache':'before-native-frame'}
class NativeOcioContext:
    def getCacheID(self):return ocio_context_state['cache']
    def getSearchPath(self):return ''
    def getWorkingDir(self):return str(ocio_fixture.parent)
class NativeOcioConfig:
    def getCacheID(self):return 'explicit-config-cache'
    def getSearchPath(self):return ''
    def getWorkingDir(self):return str(ocio_fixture.parent)
    def getCurrentContext(self):return NativeOcioContext()
    def getFileRules(self):return types.SimpleNamespace(getNumEntries=lambda:0)
    def getColorSpaceFromFilepath(self,path):return ('explicit-fixture-space',0)
hou.Color=types.SimpleNamespace(ocio_configPath=lambda:str(ocio_fixture),
    ocio_spaces=lambda:('explicit-fixture-space',),ocio_roles=lambda:(),
    ocio_activeDisplays=lambda:(),ocio_activeViews=lambda:())
sys.modules['PyOpenColorIO']=types.SimpleNamespace(Config=types.SimpleNamespace(CreateFromFile=lambda path:NativeOcioConfig()))
original_native_render=Node.render
def native_render_with_context_change(self,*args,**kwargs):
    result=original_native_render(self,*args,**kwargs)
    ocio_context_state['cache']='after-native-frame'
    return result
Node.render=native_render_with_context_change
'''


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise TimeoutError('formal recovery boundary did not become ready')


@contextmanager
def facade_for(project):
    with prepared_graph_facade(project / 'control/run.json',
            repo_root=project / 'control/snapshot', scheduler_root=project / 'scheduler',
            backend='production', allow_software_processes=True) as facade:
        yield facade


def initial_controller(project, event):
    with facade_for(project) as facade:
        for index, asset in enumerate(facade.catalog()['assets']):
            facade.submit_observation(asset['asset_id'], {'description': 'bounded lighting software reference',
                'dominant_colors': ['grey']}, 'observation-' + str(index))
        graph = facade.graph_propose({'schema': 'bridge.registered-domain-construction/1',
            'domain_pack': 'lighting_camera_render_v1', 'houdini_version': '21.0.631'}, 'recovery-proposal')
        trial = facade.graph_trial(graph['graph_id'], 'recovery-trial')
        operation_id = trial['operation_id']
        directory = facade.jobs_service._worker_paths(operation_id)['directory']
        wait_for(lambda: (directory / 'formal-worker-active.json').is_file())
        worker = json.loads((directory / 'formal-worker-active.json').read_text())
        committed = graph_recovery_snapshot(facade.jobs_service, operation_id)
        interruption = capture_prepared_graph_interruption(facade.jobs_service, operation_id)
        atomic_json(event, {'graph_id': graph['graph_id'], 'operation_id': operation_id,
            'request_id': 'recovery-trial', 'controller_pid': os.getpid(),
            'worker': worker, 'committed': committed, 'interruption': interruption}, root=event.parent)
        os._exit(17)


class FormalDomainRecoveryTests(unittest.TestCase):
    def setup_case(self, name, recovery=False, *, native_boundary='', version='21.0.631'):
        base = Path(os.environ.get('BRIDGE_FORMAL_RECOVERY_ARCHIVE',
            str(ROOT / 'outputs/formal-domain-recovery'))).resolve() / name
        base.mkdir(parents=True, exist_ok=False)
        project = base / 'project'
        api = base / 'api'
        api.mkdir()
        (api / 'nuke.py').write_text(FAKE, encoding='utf-8')
        fixture = base / 'native.%03d.exr'
        for frame, filename in ((1, 'openexr-3.4.15-2.exr'), (3, 'openexr-3.4.15-2-frame3.exr')):
            Path(str(fixture) % frame).write_bytes((ROOT / 'tests/fixtures/exr' / filename).read_bytes())
        self.environment = mock.patch.dict(os.environ, {
            'BRIDGE_TEST_EXR_FIXTURE': str(fixture), 'BRIDGE_TEST_NATIVE_ROOT': str(ROOT),
            'BRIDGE_TEST_NATIVE_VERSION': version,
            'BRIDGE_FORMAL_RECOVERY_AUDIT': str(base / 'native-audit.jsonl'),
            'BRIDGE_FORMAL_RECOVERY_WORKER': str(ROOT / 'tools/software_recovery_worker.py'),
            'HOUDINI_BRIDGE_STATE_DIR': str(base / 'bridge-state'),
            'BRIDGE_SKILLS_STATE_ROOT': str(base / 'runtime-state')})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        native = HYTHON.replace("sys.modules['houdini_bridge_addon']=addon",
            "sys.modules['houdini_bridge_addon']=addon\n" + STRICT_RENDER_NATIVE + AUDIT_NATIVE + native_boundary)
        if recovery:
            recovery_run = RECOVERY_RUN.replace('RECOVERY_WORKER_SHA256',
                file_sha256(ROOT / 'tools/software_recovery_worker.py'))
            native = native.replace(BOOTSTRAP_RUN, recovery_run)
        launcher = base / 'explicit-native-api.py'
        launcher.write_text(native, encoding='utf-8')
        harness = production_hosts.ProductionTaskHostsTests(methodName='runTest')
        houdini_config = harness.config(project, 'houdini', launcher, api)
        houdini_config['version'] = version
        nuke_config = harness.config(project, 'nuke', SOFTWARE_PYTHON, api)
        houdini_config['session_seconds'] = nuke_config['session_seconds'] = 120
        prepare_graph(project, app=None, scheduler_root=project / 'scheduler', execution_profile=True,
            render_profile=True, production_host_config=houdini_config, production_nuke_config=nuke_config)
        self.addCleanup(lambda: stop_hosts(project / 'control')
                        if (project / 'control/production-hosts.json').is_file() else None)
        return base, project

    def test_a_current_formal_readiness_recovery_is_blocked(self):
        from vfx_pipeline.domain_readiness import DomainReadinessRunner
        base, project = self.setup_case('baseline-' + str(time.time_ns()))
        runner = DomainReadinessRunner(task_id='baseline', output_root=base / 'readiness',
            houdini_versions=('21.0.631',), case_facade_factory=lambda **kwargs: facade_for(project))
        result = runner.run_case('lighting_camera_render_v1', 'approval_recovery').to_dict()
        atomic_json(base / 'baseline.json', result, root=base)
        self.assertEqual(result['status'], 'BLOCKED', result)
        self.assertIn('FORMAL_RECOVERY_NOT_EXECUTED', result['blocker'])

    def test_b_committed_owned_worker_interrupt_controller_restart_and_recovery_guards(self):
        base, project = self.setup_case('case-' + str(time.time_ns()), recovery=True)
        event = base / 'initial.json'
        child = subprocess.Popen([str(SOFTWARE_PYTHON), '-X', 'utf8', str(Path(__file__).resolve()),
            '--initial-controller', str(project), str(event)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        stdout, stderr = child.communicate(timeout=45)
        (base / 'controller.stdout.log').write_bytes(stdout)
        (base / 'controller.stderr.log').write_bytes(stderr)
        self.assertEqual(child.returncode, 17, stderr.decode(errors='replace'))
        initial = json.loads(event.read_text())
        operation_id = initial['operation_id']
        with facade_for(project) as facade:
            arguments = dict(graph_id=initial['graph_id'], request_id=initial['request_id'],
                             operation_id=operation_id, committed=initial['committed'],
                             interruption=initial['interruption'])
            for key, invalid in (
                ('controller_identity', process_identity(os.getpid())),
                ('state_before_interruption', 'SUCCEEDED'),
                ('worker_identity', {**initial['interruption']['worker_identity'], 'pid': os.getpid()}),
                ('active_event_sha256', '0' * 64),
                ('started_receipt_sha256', '0' * 64),
                ('observed_at', time.time() + 120),
            ):
                with self.subTest(rejected=key), self.assertRaisesRegex(ValueError, 'INTERRUPTION_IDENTITY_UNPROVEN'):
                    reconcile_prepared_graph_job(facade, **{**arguments,
                        'interruption': {**initial['interruption'], key: invalid}})
            unknown = reconcile_prepared_graph_job(facade, **arguments)
            self.assertFalse(unknown['tested'])
            self.assertTrue(unknown['slot_retained'])
            row = facade.jobs_service._row(operation_id)
            handle = facade.jobs_service._supervised_handle(row)
            self.assertEqual(handle.pid, initial['worker']['process_identity']['pid'])
            self.assertIsNone(handle.poll())
            handle.terminate()
            exit_code = handle.wait(timeout=15)
            receipt = handle.receipt()
            self.assert_stopped(handle, receipt)
            stopped_path = handle.directory / 'stopped.json'
            stopped_bytes = stopped_path.read_bytes()
            stopped_path.unlink()
            try:
                missing_stop = reconcile_prepared_graph_job(facade, **arguments)
                self.assertFalse(missing_stop['tested'])
                self.assertTrue(missing_stop['slot_retained'])
            finally:
                stopped_path.write_bytes(stopped_bytes)
            from dcc_task_runtime.owned_process import OwnedProcessHandle
            with mock.patch.object(OwnedProcessHandle, 'receipt', return_value={**receipt,
                    'exit_code': 0, 'supervisor_exit_code': 0, 'execution_result': 'succeeded',
                    'stop_reason': None, 'descendant_result_unobserved': False}):
                with self.assertRaisesRegex(ValueError, 'SUPERVISOR_STOP_MISSING'):
                    reconcile_prepared_graph_job(facade, **arguments)
            audit_before = (base / 'native-audit.jsonl').read_text().splitlines()
            recovered = reconcile_prepared_graph_job(facade, **arguments)
            self.assertTrue(recovered['tested'])
            self.assertTrue(recovered['slot_released'])
            atomic_json(base / 'recovery-partial.json', {
                'status': 'BLOCKED', 'scope': 'prepared_graph_commit_recovery',
                'full_domain_pass': False, 'recovery': recovered,
                'unknown_stop': unknown, 'missing_stop': missing_stop,
                'controller_source': facade.controller_source,
                'source_sha256': file_sha256(ROOT / 'packages/vfx-pipeline/src/vfx_pipeline/domain_readiness.py'),
                'blocker': 'remaining domain lifecycle stages not yet executed'}, root=base)
            worker_pid = handle.pid
            worker_effects = [json.loads(line) for line in audit_before if json.loads(line)['pid'] == worker_pid]
            self.assertTrue(any(effect['native_api'] == 'hou.Node.createNode' for effect in worker_effects))
            self.assertEqual(graph_recovery_snapshot(facade.jobs_service, operation_id), initial['committed'])
            audit_after = (base / 'native-audit.jsonl').read_text().splitlines()
            # Rebinding may reopen the committed HIP; construction and saving must not repeat.
            effects = lambda lines: [json.loads(line) for line in lines
                if json.loads(line)['native_api'] != 'hou.hipFile.load']
            self.assertEqual(effects(audit_after), effects(audit_before))
            atomic_json(base / 'result.json', {
                'scope': 'prepared_graph_commit_recovery_guards_only',
                'controller_exit_code': child.returncode, 'worker_exit_code': exit_code,
                'unknown_stop': unknown, 'missing_stop': missing_stop, 'recovery': recovered,
                'full_domain_pass': False}, root=base)

    def assert_stopped(self, handle, receipt):
        self.assertEqual(receipt['observed_by'], 'owned_child_wait')
        self.assertEqual(receipt['pid'], handle.pid)
        self.assertEqual(receipt['identity'], handle.identity)
        if os.name == 'nt':
            self.assertTrue(receipt['child_wait_observed'])
            self.assertEqual(receipt['job_active_processes'], 0)
        else:
            self.assertNotEqual(handle.pid, os.getpgrp())
            with self.assertRaises(ProcessLookupError):
                os.killpg(handle.pid, 0)

    @staticmethod
    def completed_render(facade, operation_id):
        result = facade.operation_query(operation_id)
        return result if result.get('operation', {}).get('state') in {'COMPLETED', 'FAILED'} else None

    def test_c_readiness_consumes_real_recovery_and_keeps_completed_stages_when_registration_blocks(self):
        from vfx_pipeline.domain_readiness import DomainReadinessRunner
        from houdini_bridge.operation_receipts import canonical_sha256
        base, project = self.setup_case('runner-' + str(time.time_ns()), recovery=True)
        event = base / 'initial.json'
        child = subprocess.Popen([str(SOFTWARE_PYTHON), '-X', 'utf8', str(Path(__file__).resolve()),
            '--initial-controller', str(project), str(event)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        stdout, stderr = child.communicate(timeout=45)
        (base / 'controller.stdout.log').write_bytes(stdout)
        (base / 'controller.stderr.log').write_bytes(stderr)
        self.assertEqual(child.returncode, 17, stderr.decode(errors='replace'))
        initial = json.loads(event.read_text())
        with facade_for(project) as facade:
            handle = facade.jobs_service._supervised_handle(facade.jobs_service._row(initial['operation_id']))
            self.assertEqual(handle.pid, initial['worker']['process_identity']['pid'])
            self.assertIsNone(handle.poll())
            handle.terminate()
            handle.wait(timeout=15)
            self.assert_stopped(handle, handle.receipt())
            before = (base / 'native-audit.jsonl').read_text().splitlines()
            recovery_input = {key: initial[key] for key in ('graph_id', 'operation_id', 'committed', 'interruption')}
            recovery_input['request_id'] = initial['request_id']
            case_id = 'lighting_camera_render_v1__approval_recovery'
            runner = DomainReadinessRunner(task_id='runner-recovery', output_root=base / 'readiness',
                houdini_versions=('21.0.631',), case_facade_factory=lambda **kwargs: nullcontext(facade),
                case_specs={case_id: {'formal_recovery': recovery_input}})
            result = runner.run_case('lighting_camera_render_v1', 'approval_recovery').to_dict()
            # A complete case aggregates several separately bounded receipts.
            # Preserve its bytes without treating it as one graph-job record.
            import gzip
            import hashlib
            from dcc_task_runtime.platform_support import atomic_write
            payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8')
            report = base / 'partial-case.json.gz'
            atomic_write(report, gzip.compress(payload, mtime=0), owned_root=base)
            self.assertEqual(gzip.decompress(report.read_bytes()), payload)
            atomic_json(base / 'partial-case.json', {'encoding': 'gzip+utf8-json',
                'file': report.name, 'bytes': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest()}, root=base)
            self.assertEqual(result['status'], 'BLOCKED', result)
            self.assertTrue(result['recovery']['tested'], result)
            self.assertFalse(result['recovery']['domain_lifecycle_verified'])
            self.assertFalse(result['formal_domain_lifecycle_verified'])
            self.assertTrue(result['formal_controller_verified'])
            self.assertEqual(result['controller_task_id'], facade.pipeline_task_id)
            self.assertEqual(result['graph_id'], initial['graph_id'])
            self.assertIn('FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED', result['blocker'])
            self.assertEqual(result['output_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
            self.assertIn('KARMA_HUSK_BEAUTY_ALPHA_ASSOCIATION_REQUIRED',
                          result['output_metadata_missing_facts'])
            from dcc_task_runtime.artifact_registry import frame_path
            execution=result['execution_fact']
            for frame in execution['frame_set']:
                configuration=execution['render_config'][str(frame)]['ocio_configuration_fact']
                self.assertEqual(configuration['source'],'parent_houdini_preflight')
                self.assertEqual(configuration['final_output_path'],
                                 str(frame_path(execution['output_pattern'],frame)))
                self.assertEqual(execution['output_facts'][str(frame)]['ocio_configuration_fact'],configuration)
                self.assertNotIn('colorspace',configuration)
                self.assertNotIn('premultiplied',configuration)
            self.assertEqual(execution['metadata'],{})
            self.assertFalse(any(stage['operation'] == 'register_render_artifact'
                                 for stage in result['stage_receipts']))
            saved = result['save_receipt']
            self.assertEqual(saved['sha256'], file_sha256(Path(saved['path'])))
            self.assertEqual(result['execution_fact']['scene']['sha256'], saved['sha256'])
            self.assertEqual(result['execution_fact']['scene']['scene_contract_sha256'],
                             canonical_sha256(saved['scene_contract']))
            self.assertIn('full_semantic', result['explicit_stage_gaps'])
            self.assertIn('domain_recovery', result['explicit_stage_gaps'])
            self.assertFalse(any(stage['operation'] == 'graph_propose' for stage in result['stage_receipts']))
            after = (base / 'native-audit.jsonl').read_text().splitlines()
            self.assertEqual(sum(json.loads(line)['native_api'] == 'hou.Node.createNode' for line in before),
                             sum(json.loads(line)['native_api'] == 'hou.Node.createNode' for line in after))
            self.assertEqual(graph_recovery_snapshot(facade.jobs_service, initial['operation_id']), initial['committed'])

    def test_d_parent_ocio_context_drift_during_native_frame_rejects_completion(self):
        for version in ('21.0.631','22.0.429'):
            with self.subTest(version=version):
                base,project=self.setup_case('ocio-drift-'+str(time.time_ns()),
                    native_boundary=OCIO_CONTEXT_DRIFT_NATIVE,version=version)
                with facade_for(project) as facade:
                    for index,asset in enumerate(facade.catalog()['assets']):
                        facade.submit_observation(asset['asset_id'],{'description':'explicit lighting reference',
                            'dominant_colors':['grey']},'ocio-observation-'+str(index))
                    graph=facade.graph_propose({'schema':'bridge.registered-domain-construction/1',
                        'domain_pack':'lighting_camera_render_v1','houdini_version':version},'ocio-proposal')
                    trial=facade.graph_trial(graph['graph_id'],'ocio-trial')
                    operation_id=trial['operation_id']
                    def completed_trial():
                        result=facade.graph_status(operation_id)
                        return result if result.get('state') in {'SUCCEEDED','FAILED'} else None
                    completed=wait_for(completed_trial,seconds=30)
                    self.assertEqual(completed['state'],'SUCCEEDED',completed)
                    completed=facade.graph_trial(graph['graph_id'],'ocio-trial')
                    self.assertEqual(completed['operation_id'],operation_id)
                    self.assertEqual(completed['state'],'SUCCEEDED',completed)
                    target=next(path for address,path in completed['result']['topology']['nodes'].items()
                                if address.endswith('/render'))
                    saved=facade.task_save()
                    facade.task_reopen(saved['saved_scene_id'])
                    pattern=str(project/'saves'/'context-drift.%03d.exr')
                    submitted=facade.houdini_render_bounded('ocio-drift-render',saved['saved_scene_id'],
                        target,pattern,[1],20.0)
                    result=wait_for(lambda:self.completed_render(facade,submitted['operation_id']),seconds=25)
                    atomic_json(base/'context-drift-result.json',result,root=base)
                    record=result['operation']
                    self.assertEqual(record['state'],'FAILED',result)
                    self.assertIn('native render configuration changed during frame',record['error'])
                    self.assertEqual(record['frames_done'],[])
                    self.assertEqual(record['frame_snapshots'],{})
                    self.assertEqual(record.get('output_facts',{}),{})
                    self.assertEqual(result['execution_fact']['completion_metadata_status'],'BLOCKED_MISSING_NATIVE_FACTS')
                    self.assertEqual(result['execution_fact']['metadata'],{})
                    calls=(project/'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines()
                    self.assertEqual(len(calls),1)
                    self.assertTrue((project/'saves'/'context-drift.001.exr').is_file())
                self.doCleanups()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--initial-controller':
        initial_controller(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
