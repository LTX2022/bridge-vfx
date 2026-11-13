"""Runner tests use only files, signed software boundary events, and launch mocks."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import contextlib
import io
import json
import shlex
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
spec = importlib.util.spec_from_file_location('alpha_runner_under_test', ROOT / 'tools/run_alpha_calibration.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from dcc_task_runtime import owned_process, alpha_calibration
sys.path.insert(0, str(ROOT / 'tests/unit'))
from test_native_scope import software_scope
from houdini_bridge import controlled_output


class AlphaRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope_path = self.root / 'scope.json'
        self.color = {'schema': 'bridge.project-color/1.0', 'project_id': 'explicit-software-fixture',
            'revision': 1, 'colorspace': 'ACEScg', 'source': 'human_project_selection'}
        self.inventory = [
            {'start_id': start, 'operation_id': operation, 'host': host, 'parent_start_id': parent,
             'role': role, 'heavy': role not in ('houdini-host', 'nuke-host')}
            for start, operation, host, parent, role in (
                ('alpha-h21', 'alpha-h21', 'husk', None, 'alpha-husk'),
                ('alpha-nuke', 'alpha-nuke', 'nuke', None, 'alpha-nuke'),
                ('houdini-initial', 'formal-h21', 'hython', None, 'houdini-host'),
                ('nuke-control', 'formal-h21', 'nuke', None, 'nuke-host'),
                ('formal-graph', 'formal-h21', 'hython', None, 'graph-worker'),
                ('houdini-reopen', 'formal-h21', 'hython', None, 'houdini-host'),
                ('main-render', 'formal-h21', 'husk', 'houdini-reopen', 'main-husk'),
                ('nuke-render', 'consume-nuke', 'nuke', None, 'nuke-render'))]
        self.scope = {'schema': 'bridge.engineering-closure-scope/1', 'scope_id': 'software-fixture-scope',
            'output_root': str(self.root), 'budget': runner.LIMITS,
            'execution_authorized': False, 'status': 'BLOCKED_RUNTIME_PREPARATION_PENDING',
            'versions': {'houdini': '21.0.631', 'nuke': '17.0v1'}, 'project_color': self.color,
            'operations': [{'id': name} for name in ('alpha-h21', 'alpha-nuke', 'formal-h21', 'consume-nuke')]}
        hosts = {}
        for name in ('hython', 'husk', 'nuke', 'supervisor_python'):
            path = self.root / name
            path.write_text('explicit software file fixture, not native software')
            path.chmod(0o700)
            hosts[name] = runner.file_record(path)
        ocio = self.root / 'fixture.ocio'; ocio.write_text('name: ACEScg\n')
        self.scope.update(hosts=hosts, native_color_tokens={'houdini_static_config': runner.file_record(ocio)})
        software_scope(self.root, **self.scope)
        self.scope = json.loads(self.scope_path.read_text())
        self.initial_state = (self.root / 'native-scope-state.json').read_bytes()
        self.bindings_path = self.root / 'runtime-bindings.json'
        self.bindings_path.write_text(json.dumps({'native_start_inventory': self.inventory}))

    def budget(self):
        return runner.ScopeBudget(self.scope_path, self.bindings_path)

    def authorized_budget(self):
        fields = {key: value for key, value in self.scope.items()
                  if key not in ('output_root', 'accounting', 'status', 'execution_authorized')}
        root = self.root / 'authorized-software'
        binding = software_scope(root, **fields)
        return runner.ScopeBudget(binding['path'])

    def signed_stop(self, directory, identity, code=0):
        """Synthetic supervisor API boundary; never actual native process evidence."""
        directory.mkdir(mode=0o700)
        (directory / 'receipt.key').write_bytes(b'explicit-software-test-signing-key')
        start = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': identity, 'pid': 19,
                 'execution_protocol': 1, 'observed_at': time.time()}
        owned_process._signed_write(directory, start)
        stop = {'schema': owned_process.SCHEMA, 'event': 'stopped', 'identity': identity, 'pid': 19,
            'execution_protocol': 1, 'exit_code': code, 'supervisor_exit_code': 0,
            'execution_result': 'succeeded' if code == 0 else 'failed', 'descendant_result_unobserved': False,
            'stop_reason': None, 'observed_by': 'owned_child_wait', 'observed_at': time.time(),
            'started_sha256': alpha_calibration._sha(start)}
        owned_process._signed_write(directory, stop)
        return start, stop

    def test_preflight_default_cannot_launch_or_create_budget_ledger(self):
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native launch forbidden')) as launch:
            report, _ = runner.preflight(self.scope_path)
        self.assertEqual(report['native_execution_status'], 'NOT_RUN')
        self.assertEqual(report['state'], 'BLOCKED')
        self.assertTrue(any('RUNTIME_BINDINGS_REQUIRED' in blocker for blocker in report['blockers']))
        self.assertFalse(any('EXCEEDS_6' in blocker for blocker in report['blockers']))
        self.assertEqual(report['shared_scope_admission_status'], 'UNVERIFIED')
        self.assertFalse((self.root / 'native-budget.json').exists())
        self.assertEqual((self.root / 'native-scope-state.json').read_bytes(), self.initial_state)
        launch.assert_not_called()

    def test_old_six_start_scope_is_not_admitted_and_new_limit_is_exactly_eight(self):
        old_scope = copy.deepcopy(self.scope)
        old_scope['budget'] = dict(runner.LIMITS, max_dcc_starts=6)
        self.scope_path.write_text(json.dumps(old_scope))
        original = self.scope_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_BUDGET_INVALID'):
            self.budget()
        self.assertEqual(self.scope_path.read_bytes(), original)
        self.scope_path.write_text(json.dumps(self.scope))
        budget = self.budget()
        self.assertEqual(budget.available(starts=8)['dcc_starts'], 0)
        with self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_STARTS_EXHAUSTED'):
            budget.available(starts=9)

    def test_tool_facade_reads_shared_admission_and_unknown_stop_survives_restart(self):
        budget = self.authorized_budget()
        directory = budget.root / 'supervisor-alpha-h21'
        identity = {'task_id': 'software-fixture', 'launch_nonce': 'fixture'}
        ticket = budget.native.admit('alpha-husk', directory, identity)
        restarted = runner.ScopeBudget(budget.scope_path)
        self.assertEqual(restarted.snapshot()['dcc_starts'], 1)
        with self.assertRaisesRegex(ValueError, 'STOP_UNKNOWN'):
            restarted.native.finish(ticket)
        with self.assertRaisesRegex(ValueError, 'HEAVY_BUSY'):
            restarted.available()
        self.signed_stop(directory, identity)
        restarted.native.finish(ticket)
        state = restarted.snapshot()
        self.assertIsNotNone(state['tickets'][0]['stopped_at'])
        self.assertGreaterEqual(state['total_seconds'], 0)
        self.assertTrue(restarted.native.admit('alpha-husk', directory, identity)['reused'])
        self.assertEqual(restarted.snapshot()['dcc_starts'], 1)
        self.assertFalse((self.root / 'native-budget.json').exists())
        self.assertEqual(restarted.resource_budget['native_scope'], restarted.native.binding)

    def test_shared_core_counts_husk_descendant_without_second_runner_ledger(self):
        budget = self.authorized_budget()
        directory = budget.root / 'formal-supervisor'
        identity = {'task_id': 'software-fixture'}
        parent = budget.native.admit('houdini-host', directory, identity, heavy=False)
        child = budget.native.admit('main-husk', directory, identity, parent=parent)
        self.assertEqual(budget.snapshot()['dcc_starts'], 2)
        self.assertEqual(child['parent'], parent['id'])
        self.assertFalse((self.root / 'native-budget.json').exists())

    def test_signed_failure_and_policy_failure_close_the_same_shared_core(self):
        budget = self.authorized_budget()
        identity = {'task_id': 'software-fixture'}
        directory = budget.root / 'failed-process'
        ticket = budget.native.admit('alpha-husk', directory, identity)
        self.signed_stop(directory, identity, code=7)
        with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
            budget.native.finish(ticket)
        with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
            runner.ScopeBudget(budget.scope_path).available()
        self.assertEqual(budget.fail('ALPHA_NUMERIC_FAILURE'), 'NATIVE_SCOPE_EXECUTION_FAILED')
        self.assertEqual(runner.ScopeBudget(budget.scope_path).snapshot()['dcc_starts'], 1)
        self.assertFalse((self.root / 'native-budget.json').exists())

    def test_execute_requires_both_hashes_before_any_native_or_budget_mutation(self):
        report = {'blockers': [], 'scope_sha256': 'a' * 64, 'bindings_sha256': 'b' * 64}
        with mock.patch.object(runner, 'preflight', return_value=(report, {})), \
             mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native launch forbidden')) as launch:
            for approved_scope, approved_bindings in ((None, None), ('a' * 64, None), ('a' * 64, 'c' * 64)):
                with self.subTest(approved_bindings=approved_bindings), self.assertRaisesRegex(ValueError, 'EXPLICIT_FROZEN_APPROVAL_REQUIRED'):
                    runner.execute(self.scope_path, self.bindings_path,
                        approved_scope_sha256=approved_scope, approved_bindings_sha256=approved_bindings)
        launch.assert_not_called()
        self.assertFalse((self.root / 'native-budget.json').exists())

    def full_preparation(self):
        """Static fake native files allow preflight; no process may use them."""
        hosts = self.scope['hosts']
        ocio = Path(self.scope['native_color_tokens']['houdini_static_config']['path'])
        scene = self.root / 'chart.usda'; scene.write_text('#usda 1.0\n')
        chart = self.root / 'chart.exr'
        route = {'resolution': [128, 128], 'renderer': 'BRAY_HdKarma', 'colorspace': 'ACEScg',
            'denoiser': 'off', 'motion_blur': False, 'image_filters': [], 'aov_semantics': 'karma_beauty_lpe_v1',
            'products': [{'kind': 'beauty', 'channels': ['R', 'G', 'B', 'A'], 'multipart': False}]}
        preparation = {'schema': 'bridge.alpha-chart.preparation/1.0', 'houdini_version': '21.0.631',
            'native_execution_status': 'NOT_RUN', 'generator': runner.file_record(ROOT / 'tools/prepare_native_alpha_scene.py'),
            'primary_sources': {'fixture': runner.file_record(scene)}, 'scene': runner.file_record(scene),
            'runtime_ready_adapter': runner.file_record(ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'),
            'chart_path': str(chart), 'route': route, 'route_sha256': controlled_output.controlled_route_sha256(route),
            'husk': hosts['husk'], 'command': [hosts['husk']['path'], '--prerender-script',
                shlex.quote(str(ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py')), '--renderer', 'BRAY_HdKarma',
                '--settings', '/Render/Settings', '--frame', '1', '--frame-count', '1', '--output', str(chart), str(scene)]}
        prep = self.root / 'preparation.json'; prep.write_text(json.dumps(preparation))
        paths = runner.required_source_paths()
        sources = {str(path): runner.file_record(path)['sha256'] for path in paths}
        bindings = {'schema': 'bridge.engineering-closure.runtime-bindings/1',
            'scope_sha256': runner.file_record(self.scope_path)['sha256'], 'native_start_inventory': self.inventory,
            'source_freeze': sources, 'plugin_build': sources[str(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')],
            'alpha_preparation': runner.file_record(prep), 'nuke_output_root': str(self.root / 'nuke-output'),
            'route_sha256': preparation['route_sha256'], 'output_acceptance': controlled_output._POLICY,
            'environment': {'OCIO': str(ocio)}}
        self.bindings_path.write_text(json.dumps(bindings))
        return bindings

    def complete_preparation(self):
        bindings = self.full_preparation()
        driver = self.root / 'software-main-driver.py'
        driver.write_text("raise RuntimeError('software fixture only; never execute')\n")
        bindings['source_freeze'][str(driver)] = runner.file_record(driver)['sha256']
        plan = self.root / 'main-writer-plan.json'
        plan.write_text(json.dumps({'schema': 'bridge.controlled-output.main-writer-plan/1.0',
            'state': 'PREPARED', 'output_acceptance': bindings['output_acceptance'],
            'project_color': self.color, 'route_sha256': bindings['route_sha256'],
            'plugin_build': bindings['plugin_build'],
            'command': [self.scope['hosts']['supervisor_python']['path'], str(driver)]}))
        bindings['main_writer_plan'] = runner.file_record(plan)
        binding = {'path': str(self.scope_path), 'sha256': runner.file_record(self.scope_path)['sha256']}
        deployments = {}
        for kind, host in (('houdini', 'hython'), ('nuke', 'nuke')):
            config = {'application': kind, 'lifecycle': 'task_owned', 'version': self.scope['versions'][kind],
                'executable': self.scope['hosts'][host]['path'],
                'supervisor_executable': self.scope['hosts']['supervisor_python']['path'],
                'task_root': str(self.root), 'session_seconds': 120, 'evidence_source': 'software_test',
                'native_scope': binding, 'project_color': self.color,
                'resource_budget': {'roots': [str(self.root)], 'max_bytes': 536870912, 'native_scope': binding}}
            if kind == 'houdini': config['output_acceptance'] = bindings['output_acceptance']
            path = self.root / (kind + '-deployment.json'); path.write_text(json.dumps(config))
            deployments[kind] = runner.file_record(path)
        bindings.update(deployments=deployments, controller_root=str(self.root / 'control'), evidence_source='software_test')
        self.bindings_path.write_text(json.dumps(bindings))
        return bindings

    def test_missing_main_driver_remains_a_specific_blocker(self):
        self.full_preparation()
        report, _ = runner.preflight(self.scope_path, self.bindings_path)
        self.assertEqual(report['state'], 'BLOCKED')
        self.assertTrue(any('MAIN_WRITER_PLAN_REQUIRED' in blocker for blocker in report['blockers']))

    def test_complete_software_preflight_is_prepared_without_launch_or_authorization(self):
        bindings = self.complete_preparation()
        plan_path = Path(bindings['main_writer_plan']['path'])
        plan = json.loads(plan_path.read_text())
        plan['command'].insert(1, '-I')
        plan_path.write_text(json.dumps(plan))
        bindings['main_writer_plan'] = runner.file_record(plan_path)
        self.bindings_path.write_text(json.dumps(bindings))
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native launch forbidden')) as launch:
            report, _ = runner.preflight(self.scope_path, self.bindings_path)
            self.assertEqual(report['state'], 'PREPARED', report['blockers'])
            preparation = runner.load(bindings['alpha_preparation']['path'])
            Path(preparation['chart_path']).write_bytes(b'completed output existence fixture; not alpha proof')
            Path(bindings['nuke_output_root']).mkdir()
            normal, _ = runner.preflight(self.scope_path, self.bindings_path)
            self.assertTrue(any('FRESH_SCOPED_OUTPUT_REQUIRED' in error for error in normal['blockers']))
            resumed, _ = runner.preflight(self.scope_path, self.bindings_path, allow_completed=True)
            self.assertEqual(resumed['state'], 'PREPARED', resumed['blockers'])
            Path(preparation['chart_path']).unlink()
            Path(bindings['nuke_output_root']).rmdir()
            self.assertEqual(report['blockers'], [])
            self.assertEqual(report['native_execution_status'], 'NOT_RUN')
            self.assertEqual(report['shared_scope_admission_status'], 'SOURCE_BOUND')
            with self.assertRaisesRegex(ValueError, 'LIVE_AUTHORIZATION_REQUIRED'):
                runner.execute(self.scope_path, self.bindings_path,
                    approved_scope_sha256=report['scope_sha256'], approved_bindings_sha256=report['bindings_sha256'])
        launch.assert_not_called()
        self.assertEqual((self.root / 'native-scope-state.json').read_bytes(), self.initial_state)
        self.assertFalse((self.root / 'native-budget.json').exists())

    def test_valid_hashes_and_configuration_cannot_authorize_current_scope(self):
        self.complete_preparation()
        report, data = runner.preflight(self.scope_path, self.bindings_path)
        self.assertEqual(report['state'], 'PREPARED', report['blockers'])
        self.assertIs(data['scope']['execution_authorized'], False)
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native launch forbidden')) as launch:
            with self.assertRaisesRegex(ValueError, 'LIVE_AUTHORIZATION_REQUIRED'):
                runner.execute(self.scope_path, self.bindings_path,
                    approved_scope_sha256=report['scope_sha256'], approved_bindings_sha256=report['bindings_sha256'])
        launch.assert_not_called()
        self.assertEqual((self.root / 'native-scope-state.json').read_bytes(), self.initial_state)

    def test_wrong_parent_missing_role_and_host_heavy_mismatches_refuse_preflight(self):
        original = self.complete_preparation()
        for failure in ('wrong_parent', 'missing_role', 'wrong_host', 'wrong_heavy', 'duplicate_role'):
            bindings = copy.deepcopy(original)
            inventory = bindings['native_start_inventory']
            if failure == 'wrong_parent': inventory[6]['parent_start_id'] = 'houdini-initial'
            elif failure == 'missing_role': inventory.pop()
            elif failure == 'wrong_host': inventory[6]['host'] = 'hython'
            elif failure == 'wrong_heavy': inventory[2]['heavy'] = True
            else: inventory[-1].update(role='alpha-nuke', host='nuke')
            self.bindings_path.write_text(json.dumps(bindings))
            with self.subTest(failure=failure):
                report, _ = runner.preflight(self.scope_path, self.bindings_path)
                self.assertEqual(report['state'], 'BLOCKED')
                self.assertTrue(report['blockers'])

    def test_missing_budget_hook_source_or_deployment_refuses_preflight(self):
        original = self.complete_preparation()
        for failure in ('missing_hook', 'missing_profile_source', 'changed_profile_source', 'missing_deployment', 'wrong_deployment_scope'):
            bindings = copy.deepcopy(original)
            if failure == 'missing_hook':
                bindings['source_freeze'].pop(str(ROOT / 'packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py'))
            elif failure == 'missing_profile_source':
                bindings['source_freeze'].pop(str(ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/render_profiles.py'))
            elif failure == 'changed_profile_source':
                bindings['source_freeze'][str(ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/render_profiles.py')] = '0' * 64
            elif failure == 'missing_deployment': bindings['deployments'].pop('nuke')
            else:
                path = Path(bindings['deployments']['nuke']['path'])
                config = json.loads(path.read_text()); config.pop('native_scope')
                path.write_text(json.dumps(config)); bindings['deployments']['nuke'] = runner.file_record(path)
            self.bindings_path.write_text(json.dumps(bindings))
            with self.subTest(failure=failure):
                report, _ = runner.preflight(self.scope_path, self.bindings_path)
                self.assertEqual(report['state'], 'BLOCKED')

    def test_native_launch_contract_delegates_exact_scope_role_without_double_admission(self):
        bindings = self.full_preparation()
        budget = self.authorized_budget()
        boundaries = {}
        for name in ('houdini_launch_script', 'nuke_api', 'alpha_husk_script'):
            path = self.root / (name + '.py'); path.write_text('# explicit software API fixture\n')
            boundaries[name] = runner.file_record(path)
        budget.scope['software_native_boundaries'] = boundaries
        bindings['evidence_source'] = 'software_test'
        preparation = runner.load(bindings['alpha_preparation']['path'])
        data = {'scope': budget.scope, 'bindings': bindings, 'preparation': preparation,
                'observer_root': bindings['nuke_output_root']}
        handle = mock.Mock()
        with mock.patch.object(runner.process_image, 'freeze_executable', return_value={'explicit': 'native-api-fixture'}), \
             mock.patch.object(owned_process, 'launch', return_value=handle) as launch, \
             mock.patch.object(owned_process, 'read_receipt', return_value={'exit_code': 7}), \
             mock.patch.object(budget.native, 'admit', side_effect=AssertionError('runner must delegate admission')), \
             mock.patch.object(budget.native, 'finish', side_effect=AssertionError('runner must delegate completion')):
            with self.assertRaisesRegex(ValueError, 'NATIVE_EXECUTION_FAILED'):
                runner._execute_approved(data, {}, budget)
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(launch.call_args.kwargs['scope_role'], 'alpha-husk')
        self.assertIs(launch.call_args.kwargs['scope_heavy'], True)
        self.assertEqual(launch.call_args.kwargs['resource_budget']['native_scope'], budget.binding)

    def test_missing_writer_binding_stops_before_alpha_output_and_second_launch(self):
        """Real Python supervisor receipts; only native launch/capture is substituted."""
        from engineering_houdini_api_fixture import _PIXELS
        bindings = self.full_preparation()
        executable = Path(sys.executable).resolve()
        host_record = runner.file_record(executable)
        boundaries = {}
        for name in ('houdini_launch_script', 'nuke_api', 'alpha_husk_script'):
            path = self.root / (name + '.py'); path.write_text('# explicit unused native API boundary\n')
            boundaries[name] = runner.file_record(path)
        bindings['evidence_source'] = 'software_test'
        preparation = runner.load(bindings['alpha_preparation']['path'])
        preparation['command'] = [str(executable), '-B', '-c', 'pass']
        pixels = {'Path': Path}; exec(_PIXELS, pixels)
        pixels['write_pixels'](preparation['chart_path'])
        actual_launch = owned_process.launch
        for failure in ('missing', 'wrong-executable', 'wrong-argv'):
            with self.subTest(failure=failure):
                fields = {key: value for key, value in self.scope.items()
                    if key not in ('output_root', 'accounting', 'status', 'execution_authorized')}
                binding = software_scope(self.root / ('early-' + failure), **fields)
                budget = runner.ScopeBudget(binding['path'])
                budget.scope['hosts'] = {name: dict(host_record) for name in budget.scope['hosts']}
                if failure == 'wrong-executable':
                    # A trusted version label alone cannot replace the executable's file identity.
                    budget.scope['hosts']['husk'] = runner.file_record(Path('/usr/bin/true'))
                budget.scope['software_native_boundaries'] = boundaries
                data = {'scope': budget.scope, 'bindings': bindings, 'preparation': preparation,
                        'observer_root': bindings['nuke_output_root']}
                def failed_writer_capture(command, **kwargs):
                    # The actual supervisor still signs/waits the actual ordinary child.
                    # Capture omission explicitly simulates unavailable image evidence.
                    kwargs.pop('writer_executable')
                    if failure == 'wrong-argv': command = command + ['unapproved-extra']
                    return actual_launch(command, **kwargs)
                reason = ('ALPHA_NATIVE_WRITER_BINDING_REQUIRED' if failure == 'missing'
                          else 'ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
                with mock.patch.object(owned_process, 'launch', side_effect=failed_writer_capture) as launch:
                    try:
                        runner._execute_approved(data, {}, budget)
                    except BaseException as error:
                        budget.fail(type(error).__name__ + ':' + str(error))
                        self.assertEqual(launch.call_count, 1, 'a rejected first host must not launch Nuke')
                        self.assertIn(reason, str(error))
                    else:
                        self.fail('invalid native image binding was accepted')
                state = budget.snapshot()
                self.assertEqual(state['dcc_starts'], 1)
                self.assertIsNotNone(state['tickets'][0]['stopped_at'])
                self.assertIn(reason, state['closed_reason'])
                directory = budget.root / 'supervisor-alpha-h21'
                identity = state['tickets'][0]['identity']
                stopped = owned_process.read_receipt(directory, 'stopped', identity=identity)
                self.assertEqual(owned_process.execution_returncode(stopped), 0)
                self.assertFalse((directory / 'alpha-output.json').exists())
                self.assertFalse((budget.root / 'supervisor-alpha-nuke').exists())

    def test_failed_writer_cause_requires_authenticated_operation_before_second_launch(self):
        """Signed software receipts exercise cause propagation, without native capture."""
        bindings = self.full_preparation()
        boundaries = {}
        for name in ('houdini_launch_script', 'nuke_api', 'alpha_husk_script'):
            path = self.root / (name + '.py'); path.write_text('# explicit unused software boundary\n')
            boundaries[name] = runner.file_record(path)
        bindings['evidence_source'] = 'software_test'
        preparation = runner.load(bindings['alpha_preparation']['path'])
        for failure, reason in (('signed', 'ALPHA_NATIVE_WRITER_BINDING_REQUIRED:ProcessImageError:PROCESS_IMAGE_TOOL_FAILED'),
                                ('signature', 'SUPERVISOR_RECEIPT_MISMATCH'),
                                ('argv', 'ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')):
            with self.subTest(failure=failure):
                fields = {key: value for key, value in self.scope.items()
                    if key not in ('output_root', 'accounting', 'status', 'execution_authorized')}
                binding = software_scope(self.root / ('failed-cause-' + failure), **fields)
                budget = runner.ScopeBudget(binding['path'])
                budget.scope['software_native_boundaries'] = boundaries
                data = {'scope': budget.scope, 'bindings': bindings, 'preparation': preparation,
                        'observer_root': bindings['nuke_output_root']}
                def failed_launch(command, **kwargs):
                    directory = kwargs['directory']; directory.mkdir()
                    (directory / 'receipt.key').write_bytes(b'explicit-software-receipt-fixture')
                    identity = kwargs['identity']
                    started = {'schema': owned_process.SCHEMA, 'event': 'started', 'identity': identity,
                        'pid': 1234, 'execution_protocol': 1,
                        'argv_sha256': runner.alpha_calibration._sha(command if failure != 'argv' else command + ['extra']),
                        'writer_process_binding_error': 'ProcessImageError:PROCESS_IMAGE_TOOL_FAILED'}
                    stopped = {'schema': owned_process.SCHEMA, 'event': 'stopped', 'identity': identity,
                        'pid': 1234, 'execution_protocol': 1, 'exit_code': 0, 'supervisor_exit_code': 2,
                        'execution_result': 'failed', 'descendant_result_unobserved': False,
                        'stop_reason': 'SUPERVISOR_WRITER_COLLECTION_FAILED', 'observed_by': 'owned_child_wait',
                        'started_sha256': runner.alpha_calibration._sha(started)}
                    owned_process._signed_write(directory, started)
                    owned_process._signed_write(directory, stopped)
                    if failure == 'signature':
                        envelope = json.loads((directory / 'started.json').read_text())
                        envelope['signature'] = '0' * 64
                        (directory / 'started.json').write_text(json.dumps(envelope))
                    handle = mock.Mock(); handle.wait.return_value = 2
                    return handle
                with mock.patch.object(owned_process, 'launch', side_effect=failed_launch) as launch:
                    with self.assertRaisesRegex(ValueError, reason):
                        runner._execute_approved(data, {}, budget)
                self.assertEqual(launch.call_count, 1)
                self.assertFalse((budget.root / 'supervisor-alpha-h21/alpha-output.json').exists())
                self.assertFalse((budget.root / 'supervisor-alpha-nuke').exists())

    def test_execute_requires_current_local_activation_before_budget_and_reenters_driver_lock(self):
        """Authorization protocol fixtures never execute a native or software renderer."""
        from dcc_task_runtime.execution_lock import execution_lock
        report = {'blockers': [], 'scope_sha256': runner.file_record(self.scope_path)['sha256'],
                  'bindings_sha256': runner.file_record(self.bindings_path)['sha256']}
        data = {'scope': dict(self.scope, execution_authorized=True,
                    status='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION', evidence_source='real_host'),
                'bindings': {'evidence_source': 'real_host'}}
        approvals = dict(approved_scope_sha256=report['scope_sha256'], approved_bindings_sha256=report['bindings_sha256'])
        validator = mock.Mock(return_value={'authorization': 'explicit_local_terminal_controller'})
        budget = SimpleNamespace(scope_sha256=report['scope_sha256'], fail=mock.Mock())
        with mock.patch.object(runner, 'preflight', return_value=(report, data)), \
             mock.patch.object(runner, '_activation_module', return_value=SimpleNamespace(validate_activation=validator)), \
             mock.patch.object(runner, 'ScopeBudget', return_value=budget), \
             mock.patch.object(runner, '_execute_approved', return_value={'unit_gate_only': True}) as core, \
             mock.patch.object(owned_process, 'launch', side_effect=AssertionError('no renderer launch')):
            with execution_lock(self.root/'engineering-driver-state.json', 'controlled-engineering'):
                self.assertEqual(runner.execute(self.scope_path, self.bindings_path, **approvals), {'unit_gate_only': True})
            self.assertEqual(validator.call_count, 2)
            core.assert_called_once()
            for failure in ('missing_receipt', 'software_authorization', 'changed_inside_lock'):
                validator.reset_mock()
                validator.side_effect = None
                validator.return_value = {'authorization': 'explicit_local_terminal_controller'}
                if failure == 'missing_receipt': validator.side_effect = ValueError('ACTIVATION_RECEIPT_REQUIRED')
                elif failure == 'software_authorization': validator.return_value = {'authorization': 'explicit_software_test_controller'}
                else: validator.side_effect = [{'authorization': 'explicit_local_terminal_controller'}, ValueError('ACTIVATION_RECEIPT_CHANGED')]
                with self.subTest(failure=failure), mock.patch.object(runner, 'ScopeBudget', side_effect=AssertionError('invalid activation before budget')):
                    with self.assertRaisesRegex(ValueError, 'ACTIVATION'):
                        runner.execute(self.scope_path, self.bindings_path, **approvals)
            budget.fail.assert_not_called()
        self.assertEqual((self.root/'native-scope-state.json').read_bytes(), self.initial_state)

    def test_execute_lock_drift_busy_and_completed_original_do_not_dispatch_or_close_scope(self):
        from dcc_task_runtime.execution_lock import execution_lock
        report = {'blockers': [], 'scope_sha256': runner.file_record(self.scope_path)['sha256'],
                  'bindings_sha256': runner.file_record(self.bindings_path)['sha256']}
        data = {'scope': dict(self.scope, execution_authorized=True,
                    status='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION', evidence_source='real_host'),
                'bindings': {'evidence_source': 'real_host'}}
        approvals = dict(approved_scope_sha256=report['scope_sha256'], approved_bindings_sha256=report['bindings_sha256'])
        validator = SimpleNamespace(validate_activation=mock.Mock(return_value={'authorization':'explicit_local_terminal_controller'}))
        with mock.patch.object(runner, '_activation_module', return_value=validator), \
             mock.patch.object(runner, 'ScopeBudget', side_effect=AssertionError('read-only guard must not construct execution budget')), \
             mock.patch.object(runner, '_execute_approved', side_effect=AssertionError('no duplicate dispatch')):
            with mock.patch.object(runner, 'preflight', side_effect=[(report,data),(dict(report, bindings_sha256='c'*64),data)]):
                with self.assertRaisesRegex(ValueError, 'FROZEN_INPUTS_CHANGED'):
                    runner.execute(self.scope_path,self.bindings_path,**approvals)
            entered, release = threading.Event(), threading.Event()
            def owner():
                with execution_lock(self.root/'engineering-driver-state.json','controlled-engineering'):
                    entered.set(); release.wait(5)
            thread=threading.Thread(target=owner);thread.start();self.assertTrue(entered.wait(2))
            try:
                with mock.patch.object(runner, 'preflight', return_value=(report,data)):
                    with self.assertRaisesRegex(runner.AlphaRunnerBusy,'ALPHA_RUNNER_BUSY'):
                        runner.execute(self.scope_path,self.bindings_path,**approvals)
            finally: release.set();thread.join(5)
            original={'schema':'bridge.alpha-runner.result/1','original_reauthenticated':True}
            with mock.patch.object(runner, 'preflight', return_value=(report,data)), \
                 mock.patch.object(runner, '_completed_original', side_effect=[None,original]):
                self.assertEqual(runner.execute(self.scope_path,self.bindings_path,**approvals),original)
        self.assertEqual((self.root/'native-scope-state.json').read_bytes(),self.initial_state)
        self.assertFalse((self.root / 'native-budget.json').exists())

    def test_prepare_rerun_cannot_reinitialize_missing_accounting_original(self):
        spec = importlib.util.spec_from_file_location('prepare_scope_under_test', ROOT / 'tools/prepare_engineering_closure.py')
        preparer = importlib.util.module_from_spec(spec); spec.loader.exec_module(preparer)
        state = self.root / 'native-scope-state.json'; state.unlink()
        from dcc_task_runtime.native_scope import NativeScope
        with mock.patch.object(preparer, 'OUTPUT', self.root), \
             mock.patch.object(preparer.secrets, 'token_bytes', side_effect=AssertionError('rerun cannot create key')) as random_key, \
             mock.patch.object(NativeScope, 'initialize', side_effect=AssertionError('rerun cannot initialize')) as initialize, \
             mock.patch.object(sys, 'argv', ['prepare-scope']), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_result: preparer.main()
        self.assertEqual(exit_result.exception.code, 2)
        random_key.assert_not_called(); initialize.assert_not_called()
        self.assertFalse(state.exists())

    def test_missing_accounting_state_refuses_preflight_without_reinitialization(self):
        self.complete_preparation()
        state = self.root / 'native-scope-state.json'
        state.unlink()
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('native launch forbidden')) as launch:
            report, _ = runner.preflight(self.scope_path, self.bindings_path)
        self.assertEqual(report['state'], 'BLOCKED')
        self.assertTrue(report['blockers'])
        self.assertFalse(state.exists())
        launch.assert_not_called()

    def test_signing_is_immutable_and_changed_frozen_input_is_refused(self):
        directory = self.root / 'software-receipts'
        identity = {'task_id': 'software-fixture'}
        self.signed_stop(directory, identity)
        payload = {'schema': owned_process.SCHEMA, 'event': 'alpha-output', 'identity': identity,
                   'evidence_source': 'software_test', 'fixture_only': True}
        runner._seal(directory, identity, payload)
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_EVENT_ALREADY_EXISTS'):
            runner._seal(directory, identity, dict(payload, fixture_only=False))
        path = self.root / 'frozen-input'; path.write_text('original')
        record = runner.file_record(path)
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'FROZEN_FILE_CHANGED'):
            runner.checked(record)


if __name__ == '__main__': unittest.main()
