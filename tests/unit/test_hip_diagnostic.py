"""HIP-only software checks. Only HOM/USD, transport and process APIs are substitutes."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import run_hip_diagnostic as hip
from dcc_task_runtime import owned_process
from dcc_task_runtime.native_scope import NativeScope


def tool(name):
    spec = importlib.util.spec_from_file_location('hip_test_' + name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HipDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp', prefix='hip-diagnostic-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.modules = self.enterContext(mock.patch.dict(sys.modules))
        self.environment = self.enterContext(mock.patch.dict(os.environ))
        self.plan = ROOT / 'handover/HIP_ONLY_PLAN_20261024.md'
        self.python = Path(sys.executable).resolve()
        self.ocio = self.root / 'config.ocio'
        self.ocio.write_text('software test config\n')

    def candidate(self):
        return hip.prepare(self.root / 'candidate', plan=self.plan, hython=self.python,
            supervisor_python=self.python, ocio_config=self.ocio, evidence_source='software_test')

    def activated(self):
        prepared = self.candidate()
        data = hip.frozen_data(prepared['scope']['path'])
        target = self.root / 'live'
        expected = {'candidate_scope': prepared['scope'], 'candidate_freeze': prepared['freeze'],
            'source_sha256': hashlib.sha256(hip.canonical(data['freeze']['sources'])).hexdigest(),
            'target_root': str(target)}
        review = hip.write(self.root / 'review.json', {'schema': 'bridge.hip-diagnostic.review/1',
            'decision': 'APPROVED', 'reviewer': '/root/hip_only_plan_review', **expected})
        authorization = hip.write(self.root / 'authorization.json', {
            'schema': 'bridge.hip-diagnostic.conditional-authorization/1',
            'authority': 'current_user_conditional_instruction', 'instruction': hip.AUTH_TEXT,
            'review': review, **expected})
        result = hip.activate(prepared['scope']['path'], review_path=review['path'],
            authorization_path=authorization['path'], output_root=target)
        entry = target / 'control/snapshot/tools/run_hip_diagnostic.py'
        spec = importlib.util.spec_from_file_location('hip_frozen_test', entry)
        frozen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frozen)
        return result, frozen

    def test_prepare_preflight_activation_are_zero_native_and_source_bound(self):
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native forbidden')) as launch, \
                mock.patch.object(hip, 'active_native_processes', return_value=[]):
            prepared = self.candidate()
            report = hip.preflight(prepared['scope']['path'])
            self.assertEqual(report['state'], 'PREPARED')
            self.assertEqual(report['dcc_starts'], 0)
            self.assertEqual(report['native_execution_status'], 'NOT_RUN')
            self.assertFalse(NativeScope(prepared['scope']).scope['execution_authorized'])
            data = hip.frozen_data(prepared['scope']['path'])
            self.assertEqual(data['freeze']['sources'], hip.source_manifest(ROOT))
            with self.assertRaisesRegex(ValueError, 'FRESH_ROOT'):
                self.candidate()
        launch.assert_not_called()

    def test_freeze_inputs_path_and_budget_drift_refuse_before_launch(self):
        prepared = self.candidate()
        scope_path = Path(prepared['scope']['path'])
        data = hip.frozen_data(scope_path)
        paths = [self.ocio, data['frozen'] / hip.SCENE,
                 data['frozen'] / 'tools/run_hip_diagnostic.py', data['root'] / 'plan.md']
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native forbidden')):
            for path in paths:
                with self.subTest(path=path.name):
                    original = path.read_bytes()
                    path.write_bytes(original + b'\n')
                    with self.assertRaisesRegex(ValueError, 'CHANGED|DRIFT'):
                        hip.frozen_data(scope_path)
                    path.write_bytes(original)
            link = self.root / 'alias'
            link.symlink_to(data['frozen'] / hip.SCENE)
            with self.assertRaisesRegex(ValueError, 'PATH|SYMLINK'):
                hip.record(link)
            freeze_path = data['root'] / 'freeze.json'
            original = freeze_path.read_bytes()
            changed = json.loads(original); changed['limits']['starts'] = 3
            freeze_path.write_bytes(hip.canonical(changed))
            with self.assertRaisesRegex(ValueError, 'FREEZE_DRIFT'):
                hip.frozen_data(scope_path)
            freeze_path.write_bytes(original)

    def test_authorization_requires_independent_review_and_explicit_trusted_record(self):
        prepared = self.candidate()
        fake = hip.write(self.root / 'public-hash.json', {'decision': 'APPROVED',
            'candidate_scope': prepared['scope'], 'candidate_freeze': prepared['freeze']})
        with self.assertRaisesRegex(ValueError, 'INDEPENDENT_REVIEW_REQUIRED'):
            hip.activate(prepared['scope']['path'], review_path=fake['path'],
                authorization_path=fake['path'], output_root=self.root / 'live')
        self.assertEqual(NativeScope(prepared['scope']).snapshot()['dcc_starts'], 0)

    def test_software_source_cannot_execute_real_entry_and_activation_drift_refused(self):
        activated, frozen = self.activated()
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native forbidden')):
            with self.assertRaisesRegex(ValueError, 'SOURCE_MISMATCH'):
                frozen.execute(activated['scope']['path'])
            data = frozen.frozen_data(activated['scope']['path'])
            path = data['root'] / 'activation.json'
            envelope = json.loads(path.read_bytes())
            envelope['payload']['trusted_action'] = 'public_hash'
            path.write_bytes(hip.canonical(envelope))
            with self.assertRaisesRegex(ValueError, 'SIGNATURE_INVALID'):
                frozen._activation(data)

    def test_same_authenticated_ledger_inner_limits_disk_unknown_and_third_refused(self):
        prepared = self.candidate()
        native = NativeScope(prepared['scope'])
        baseline = native.snapshot()
        invalid = [dict(baseline, dcc_starts=2), dict(baseline, total_seconds=240),
            dict(baseline, disk_bytes=536870912), dict(baseline, closed_reason='unknown'),
            dict(baseline, dcc_starts=1, tickets=[{'role': 'graph-worker', 'stopped_at': None}])]
        for value in invalid:
            with self.subTest(state=value), mock.patch.object(native, 'snapshot', return_value=value):
                with self.assertRaisesRegex(ValueError, 'ADMISSION'):
                    hip.admission(native, 0)
        self.assertEqual(hip.admission(native, 0)['native_scope'], native.binding)
        with self.assertRaisesRegex(ValueError, 'ADMISSION'):
            hip.admission(native, 2)
        overlong = dict(baseline, dcc_starts=1, tickets=[{'role':'graph-worker',
            'stopped_at':1, 'charged_seconds':120.001}])
        with mock.patch.object(native, 'snapshot', return_value=overlong):
            with self.assertRaisesRegex(ValueError, 'ADMISSION'):
                hip.admission(native, 1)

    def test_cold_runner_uses_only_frozen_packages_and_public_serve_without_warmup(self):
        prepared = self.candidate()
        data = hip.frozen_data(prepared['scope']['path'])
        budget = hip.admission(data['native'], 0)
        runner = hip.cold_runner(data, data['control'] / 'cold-host', 'fresh-test-nonce', budget)
        bootstrap = runner.split('# Generated by houdini_bridge.task_host', 1)[0]
        code = bootstrap + "import importlib.util,json; print(json.dumps({name: importlib.util.find_spec(name).origin for name in ['dcc_task_runtime','houdini_bridge','nuke_bridge','vfx_pipeline']}))"
        completed = subprocess.run([str(self.python), '-I', '-B', '-c', code],
            capture_output=True, text=True, timeout=10, check=True, env={'PATH':'/usr/bin:/bin'})
        origins = json.loads(completed.stdout)
        self.assertTrue(all(Path(path).is_relative_to(data['frozen']) for path in origins.values()))
        self.assertIn('warmup=False', runner)
        self.assertNotIn('writer_executable=', runner)
        self.assertNotIn('_TASK_HOST_IDENTITY', runner)
        self.assertNotIn('graph_initialize', runner)
        directory = data['root'] / 'environment'
        directory.mkdir()
        env = hip._host_environment(data, directory, {'task_id':'unit','launch_nonce':'nonce'})
        self.assertEqual(env['BRIDGE_SKILLS_SCHEDULER_ROOT'], str(data['control'] / 'scheduler'))
        self.assertEqual(env['HOUDINI_BRIDGE_STATE_DIR'], env['HOUDINI_BRIDGE_TASK_STATE_DIR'])

    def test_cold_validator_requires_complete_readback_from_existing_native_api_fixture(self):
        from test_controlled_native_readback import ControlledNativeReadbackTests
        fixture = ControlledNativeReadbackTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        path = fixture.root / 'readback.hip'
        saved = fixture.addon.dispatch('scene.save_hip', {'task_id':fixture.task_id, 'path':str(path)})
        before = fixture.addon._host_identity()
        operation = 'diagnostic-validator'
        reopened = fixture.addon.dispatch('scene.reopen_task_hip', {'task_id':fixture.task_id,
            'path':str(path), 'sha256':saved['sha256'], 'scene_contract_sha256':saved['scene_contract_sha256'],
            'operation_id':operation, 'request_id':operation, 'scene_before_identity':before})
        graph = {'save':saved, 'hip':hip.record(path)}
        snapshot = hip.record(reopened['scene_transition']['result']['snapshot_path'])
        hip.validate_cold(reopened, before, graph, operation, snapshot)
        self.assertTrue(all('parameter_channels' in n for n in saved['scene_contract']['nodes']))
        self.assertEqual(set(reopened['frozen_scene_parameters']['geometry']), {'Sphere','Ground'})
        for field in ('parameters_verified','nodes_verified','connections_verified','frozen_scene_parameters','scene_transition'):
            broken = copy.deepcopy(reopened)
            broken.pop(field)
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, 'READBACK'):
                hip.validate_cold(broken, before, graph, operation, snapshot)

        control = self.root / 'contract-control'
        saves = control / 'houdini-instances/fx_operations'
        saves.mkdir(parents=True)
        saved_path = saves / 'task.saves.json'
        saved_path.write_bytes(hip.canonical({'saves':[saved]}))
        data = {'control':control, 'config':{'task_id':fixture.task_id}}
        hip._saved_contract(data, path, saved['sha256'], saved['scene_contract_sha256'])
        for field in ('parameter_channels', 'inputs'):
            broken = copy.deepcopy(saved)
            broken['scene_contract']['nodes'][0].pop(field)
            broken['scene_contract_sha256'] = hashlib.sha256(hip.canonical(broken['scene_contract'])).hexdigest()
            saved_path.write_bytes(hip.canonical({'saves':[broken]}))
            with self.subTest(contract_missing=field), self.assertRaisesRegex(ValueError, 'READBACK'):
                hip._saved_contract(data, path, saved['sha256'], broken['scene_contract_sha256'])
        snapshot_path = Path(snapshot['path'])
        snapshot_path.chmod(0o600)
        snapshot_path.write_bytes(snapshot_path.read_bytes() + b'drift')
        with self.assertRaisesRegex(ValueError, 'FILE_CHANGED'):
            hip.validate_cold(reopened, before, graph, operation, snapshot)
        with self.assertRaisesRegex(ValueError, 'SIGNED_STOP'):
            hip.receipt_pair({'directory':str(self.root), 'identity':{'task_id':'none'}})

    def test_cold_stop_unknown_is_bounded_and_keeps_scheduler_slot(self):
        prepared = self.candidate()
        data = hip.frozen_data(prepared['scope']['path'])
        source = data['root'] / 'unverified.hip'
        source.write_bytes(b'explicit failure fixture, never a successful HIP')
        source_record = hip.record(source)
        snapshot = (data['control'] / 'houdini-instances/scene-transition-snapshots' /
                    data['config']['task_id'] / (source_record['sha256'] + '.hip'))
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes(source.read_bytes())
        handle = mock.Mock(pid=123456, directory=data['control'] / 'cold-host/owned-supervisor')
        handle.poll.return_value = None
        handle.wait.side_effect = subprocess.TimeoutExpired('explicit software handle', .01)
        budget = {'max_seconds':.1, 'max_bytes':536870912, 'roots':[str(data['root'])],
                  'native_scope':data['native'].binding}
        with mock.patch.object(owned_process, 'launch', return_value=handle), \
                mock.patch.object(hip, 'process_identity', return_value={'pid':123456, 'birth':'cold'}):
            with self.assertRaisesRegex(ValueError, 'READY_UNPROVEN'):
                hip.run_cold(data, budget, {'hip':source_record, 'birth_identity':{'pid':1,'birth':'worker'}})
        self.assertEqual(handle.wait.call_count, 2)
        handle.terminate.assert_called_once()
        self.assertTrue(hip.GraphScheduler(data['control'] / 'scheduler').snapshot()['active'])
        self.assertEqual(hip.load(data['control'] / 'cold-host/stop-unknown.json')['state'], 'STOP_UNKNOWN')

    def test_native_inventory_includes_current_nuke17_names(self):
        observed = types.SimpleNamespace(stdout='11 /Applications/Nuke17.0\n12 /Applications/Nuke17.0v1\n13 /usr/bin/python3\n')
        with mock.patch.object(hip.subprocess, 'run', return_value=observed):
            self.assertEqual([p['pid'] for p in hip.active_native_processes()], [11,12])

    def test_first_launch_failure_or_unknown_closes_scope_and_never_starts_cold(self):
        activated, frozen = self.activated()
        data = frozen.frozen_data(activated['scope']['path'])
        calls = []
        def unknown(command, **kwargs):
            calls.append(kwargs['scope_role'])
            NativeScope(kwargs['resource_budget']['native_scope']).admit(kwargs['scope_role'],
                kwargs['directory'], kwargs['identity'], heavy=kwargs['scope_heavy'])
            raise RuntimeError('explicit software launch outcome unknown')
        with mock.patch.object(frozen, 'active_native_processes', return_value=[]), \
                mock.patch.object(owned_process, 'launch', side_effect=unknown):
            with self.assertRaisesRegex(ValueError, 'GRAPH_NOT_SUCCEEDED'):
                frozen.execute_software_test(activated['scope']['path'])
            with self.assertRaisesRegex(ValueError, 'ALREADY_ATTEMPTED'):
                frozen.execute_software_test(activated['scope']['path'])
        self.assertEqual(calls, ['graph-worker'])
        self.assertIsNotNone(NativeScope(activated['scope']).snapshot()['closed_reason'])
        self.assertTrue(frozen.GraphScheduler(data['control'] / 'scheduler').snapshot()['active'])


if __name__ == '__main__':
    unittest.main()
