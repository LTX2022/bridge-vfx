from pathlib import Path
import tempfile
import unittest
from unittest import mock
from vfx_pipeline.domain_readiness import DomainReadinessError, DomainReadinessRunner

class EmptySuccessTransport:
    boundary_kind='test_transport'
    def __init__(self):self.commands=[]
    def call(self,command,params):
        self.commands.append(command)
        return {'status':'PASS','gates':[{'passed':True}]}

class DomainReadinessEvidenceTests(unittest.TestCase):
    def _assert_full_formal_feedback(self, result, domain, native_version, scenario):
        from dcc_task_runtime.domains import builtin_domain_registry
        from houdini_bridge.native_render_domains import control_contract

        approved = builtin_domain_registry().get(domain, '1.0.0').control_map
        expected = list(control_contract(domain, native_version))
        self.assertEqual(set(expected), set(approved))
        expected = expected if scenario == 'causal_candidate' else []
        self.assertEqual(result.get('semantic_control_coverage', []), expected)
        self.assertEqual(result['graph_version'], len(expected))
        controls = result.get('feedback_controls', [])
        self.assertEqual([item['name'] for item in controls], expected)
        self.assertEqual([item['graph_version'] for item in controls], list(range(1, len(expected) + 1)))
        stages = result['stage_receipts']
        versions = [row['result']['version'] for row in stages if row['operation'] == 'graph_version']
        self.assertEqual(versions, list(range(len(expected) + 1)))
        for operation in ('feedback_edit', 'task_save', 'task_reopen'):
            rows = [row for row in stages if row['operation'] == operation and 'semantic_control' in row]
            self.assertEqual([row['semantic_control'] for row in rows], expected)
            self.assertEqual([row['graph_version'] for row in rows],
                list(range(len(expected))) if operation == 'feedback_edit' else list(range(1, len(expected) + 1)))
        previous_saved = result['initial_save_receipt']
        for index, (name, control) in enumerate(zip(expected, controls), 1):
            self.assertNotEqual(control['before'], control['after'])
            self.assertEqual(control['reopened'], control['after'])
            rows = {row['operation']: row for row in stages if row.get('semantic_control') == name}
            feedback = rows['feedback_edit']['result']
            self.assertEqual(feedback, control['feedback'])
            self.assertEqual({item['semantic_control'] for item in feedback['parameter_diff']}, {name})
            self.assertTrue(all(item['readback_verified'] is True for item in feedback['parameter_diff']))
            saved = rows['task_save']['result']
            self.assertEqual(saved, control['save_receipt'])
            self.assertIn('graph:{}:{}:version:{}'.format(result['controller_task_id'], result['graph_id'], index),
                          saved['feedback_dependencies'])
            for field in ('saved_scene_id', 'sha256', 'feedback_dependencies'):
                self.assertNotEqual(saved[field], previous_saved[field])
            reopened = rows['task_reopen']['result']
            self.assertEqual(rows['task_reopen']['saved_scene_id'], saved['saved_scene_id'])
            self.assertEqual(reopened['path'], saved['path'])
            self.assertEqual(reopened['sha256'], saved['sha256'])
            previous_saved = saved
        self.assertEqual(result['save_receipt'], previous_saved)

    def test_construction_wait_rejects_foreign_operation_and_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='owner', output_root=Path(directory))
            for mutation in ({'operation_id':'foreign'}, {'graph_id':'foreign'}):
                facade = mock.Mock()
                facade.graph_status.return_value = {'state':'FAILED', 'operation_id':'owned',
                                                    'graph_id':'graph', **mutation}
                with self.subTest(mutation=mutation), mock.patch('vfx_pipeline.domain_readiness.time.monotonic', return_value=0), \
                     mock.patch('vfx_pipeline.domain_readiness.time.sleep'):
                    with self.assertRaisesRegex(DomainReadinessError, 'OPERATION_MISMATCH'):
                        runner._wait_for_construction(facade, 'graph', 'request',
                            {'state':'RUNNING', 'operation_id':'owned', 'graph_id':'graph'}, 1)
                facade.graph_trial.assert_not_called()

    def test_construction_deadline_and_unknown_stop_never_replay_or_accept(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='owner', output_root=Path(directory))
            for trial in ({'state':'RUNNING', 'operation_id':'owned', 'graph_id':'graph'},
                          {'state':'SUCCEEDED', 'operation_id':'owned', 'graph_id':'graph', 'stop_confirmed':False},
                          {'state':'FAILED', 'operation_id':'owned', 'graph_id':'graph', 'stop_confirmed':True}):
                facade = mock.Mock()
                with self.subTest(trial=trial), mock.patch('vfx_pipeline.domain_readiness.time.monotonic', return_value=2):
                    with self.assertRaisesRegex(DomainReadinessError, 'GRAPH_INCOMPLETE'):
                        runner._wait_for_construction(facade, 'graph', 'request', trial, 1)
                facade.graph_status.assert_not_called()
                facade.graph_trial.assert_not_called()

    def test_empty_successes_never_prove_48_domains_or_composites(self):
        host=EmptySuccessTransport();nuke=EmptySuccessTransport()
        with tempfile.TemporaryDirectory() as root:
            receipt=DomainReadinessRunner(host_client=host,nuke_client=nuke,task_id='test',output_root=Path(root)).run_all()
        self.assertEqual(receipt['case_count'],48)
        self.assertTrue(all(c['status']=='BLOCKED' for c in receipt['cases']+receipt['composites']))
        self.assertTrue(all(not c['recovery']['tested'] for c in receipt['cases']))
        self.assertEqual(set(host.commands),{'agent.fx.build_preview'})
        self.assertEqual(set(nuke.commands),{'agent.nuke.composite.build_graph'})
        self.assertEqual(receipt['software_preparation_status'],'NOT_READY')
    def test_nuke_only_does_not_require_houdini(self):
        nuke=EmptySuccessTransport()
        with tempfile.TemporaryDirectory() as root:
            result=DomainReadinessRunner(nuke_client=nuke,task_id='nuke-only',output_root=Path(root)).run_case('nuke_composite_v1','build_inspect')
        self.assertEqual(nuke.commands,['agent.nuke.composite.build_graph'])
        self.assertEqual(result.application,'nuke')
        self.assertEqual(result.result['status'],'BLOCKED')
    def test_failed_build_is_retained_per_domain_instead_of_aborting_inventory(self):
        class FailureTransport:
            def call(self,command,params):raise RuntimeError('native input absent')
        with tempfile.TemporaryDirectory() as root:
            receipt=DomainReadinessRunner(host_client=FailureTransport(),task_id='test',output_root=Path(root)).run_all()
        self.assertEqual(len(receipt['cases']),48)
        self.assertIn('native input absent',receipt['cases'][0]['blocker'])

    def test_prepared_lighting_stops_before_ledger_and_nuke_without_writer_facts(self):
        import json
        import os
        import sys
        from contextlib import nullcontext
        from unittest import mock
        import test_production_task_hosts as fixture
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        from prepare_workbuddy_graph import prepare_graph
        from run_full_readiness_cases import prepared_case_factory
        from vfx_pipeline.production_hosts import stop_hosts

        retained = os.environ.get('BRIDGE_FORMAL_READINESS_EVIDENCE_DIR')
        if retained:
            Path(retained).mkdir(parents=True, exist_ok=False)
        workspace = nullcontext(retained) if retained else tempfile.TemporaryDirectory()
        with workspace as temporary:
            base = Path(temporary).resolve()
            api = base / 'api'; api.mkdir(); (api / 'nuke.py').write_text(fixture.FAKE)
            frames = base / 'native.%03d.exr'
            for frame, name in [(1, 'openexr-3.4.15-2.exr'), (3, 'openexr-3.4.15-2-frame3.exr')]:
                Path(str(frames) % frame).write_bytes((fixture.ROOT / 'tests/fixtures/exr' / name).read_bytes())
            native = fixture.HYTHON.replace("sys.modules['houdini_bridge_addon']=addon",
                "sys.modules['houdini_bridge_addon']=addon\n" + fixture.STRICT_RENDER_NATIVE)
            python_host = base / 'python-native-host.py'
            python_host.write_text(native, encoding='utf-8')
            helper = fixture.ProductionTaskHostsTests()
            for version in ('21.0.631', '22.0.429'):
                for scenario in ('build_inspect', 'causal_candidate'):
                    with self.subTest(version=version, scenario=scenario):
                        case_id = 'lighting_camera_render_v1__' + scenario
                        project = base / version / scenario
                        h = helper.config(project, 'houdini', python_host, api); h['version'] = version
                        n = helper.config(project, 'nuke', fixture.SOFTWARE_PYTHON, api)
                        h['session_seconds'] = n['session_seconds'] = 120
                        prepare_graph(project, app=None, scheduler_root=project / 'scheduler',
                            execution_profile=True, render_profile=True,
                            production_host_config=h, production_nuke_config=n)
                        factory = prepared_case_factory({version: {case_id: str(project)}}, version,
                                                        allow_software_processes=True)
                        original_register = ArtifactRegistry.register
                        attempts = []
                        def register(ledger, **kwargs):
                            if kwargs.get('artifact_id') == case_id + '-input':
                                attempts.append(kwargs['operation_id'])
                                if len(attempts) == 1:
                                    raise OSError('test interrupted ledger commit')
                            return original_register(ledger, **kwargs)
                        environment = {'BRIDGE_TEST_EXR_FIXTURE': str(frames),
                            'BRIDGE_TEST_NATIVE_ROOT': str(fixture.ROOT), 'BRIDGE_TEST_NATIVE_VERSION': version,
                            'HOUDINI_BRIDGE_STATE_DIR': str(project / 'bridge-state'),
                            'BRIDGE_SKILLS_STATE_ROOT': str(project / 'runtime-state')}
                        try:
                            with mock.patch.dict(os.environ, environment), mock.patch.object(ArtifactRegistry, 'register', register):
                                result = DomainReadinessRunner(task_id='readiness', output_root=project / 'receipts',
                                    houdini_versions=(version,), case_facade_factory=factory).run_case(
                                        'lighting_camera_render_v1', scenario).to_dict()
                            (project / 'readiness.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
                            failures = []
                            for stage in result.get('stage_receipts', []):
                                receipt = stage.get('result', {})
                                operation = receipt.get('operation', {})
                                state = receipt.get('state') or operation.get('state')
                                if receipt.get('error') or operation.get('error') or state in {'FAILED', 'NEEDS_RECONCILE'}:
                                    failures.append({'stage': stage.get('operation'),
                                        'state': state, 'error': receipt.get('error') or operation.get('error'),
                                        'frames_done': operation.get('frames_done')})
                            self.assertEqual(result['status'], 'BLOCKED',
                                str(result.get('blocker')) + '\n' + json.dumps(failures, ensure_ascii=False))
                            self.assertIn('FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED', result['blocker'])
                            self.assertFalse(result['formal_domain_lifecycle_verified'])
                            self.assertTrue(result['formal_controller_verified'])
                            self.assertEqual(attempts, [], 'incomplete native output cannot reach ledger registration')
                            operations = [stage['operation'] for stage in result['stage_receipts']]
                            self.assertNotIn('register_render_artifact', operations)
                            self.assertNotIn('consume_artifact', operations)
                            self.assertNotIn('nuke_input_binding', operations)
                            registry = ArtifactRegistry(project / 'control/artifact_ledger')
                            self.assertIsNone(registry.lookup(case_id + '-input'))
                            self.assertEqual(registry.history(case_id + '-input'), [])
                            self.assertEqual(result['execution_fact']['state'], 'COMPLETED')
                            self.assertEqual(result['execution_fact']['frames_done'], [1, 3])
                            self.assertEqual(result['execution_fact']['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
                            self.assertEqual(result['execution_fact']['metadata'], {})
                            calls = [json.loads(line) for line in (project / 'control/houdini-task-host/native-render-calls.jsonl').read_text().splitlines()]
                            self.assertEqual([item['frame'] for item in calls], [1, 3])
                            self.assertEqual({item['hip_sha256'] for item in calls}, {result['save_receipt']['sha256']})
                            self._assert_full_formal_feedback(result, 'lighting_camera_render_v1', version, scenario)
                            if scenario == 'causal_candidate':
                                self.assertNotEqual(result['save_receipt']['feedback_dependencies'], result['initial_save_receipt']['feedback_dependencies'])
                            self.assertFalse(result['real_dcc_verified'])
                            self.assertNotIn('nuke_input_binding', result)
                            self.assertTrue(all(row['task_id'] == result['controller_task_id'] for row in result['stage_receipts']))
                        finally:
                            if (project / 'control/production-hosts.json').exists():
                                stop_hosts(project / 'control')

    def test_prepared_material_chain_and_rbd_semantic_rejection(self):
        import json
        import os
        from contextlib import nullcontext
        import test_production_task_hosts as fixture
        from prepare_workbuddy_graph import prepare_graph
        from run_full_readiness_cases import prepared_case_factory
        from vfx_pipeline.production_hosts import stop_hosts

        retained = os.environ.get('BRIDGE_FORMAL_READINESS_EVIDENCE_DIR')
        if retained:
            Path(retained).mkdir(parents=True, exist_ok=False)
        workspace = nullcontext(retained) if retained else tempfile.TemporaryDirectory()
        with workspace as temporary:
            base = Path(temporary).resolve()
            api = base / 'api'; api.mkdir(); (api / 'nuke.py').write_text(fixture.FAKE)
            frames = base / 'native.%03d.exr'
            for frame, name in [(1, 'openexr-3.4.15-2.exr'), (3, 'openexr-3.4.15-2-frame3.exr')]:
                Path(str(frames) % frame).write_bytes((fixture.ROOT / 'tests/fixtures/exr' / name).read_bytes())
            native = fixture.HYTHON.replace("sys.modules['houdini_bridge_addon']=addon",
                "sys.modules['houdini_bridge_addon']=addon\n" + fixture.STRICT_RENDER_NATIVE)
            python_host = base / 'python-native-host.py'
            python_host.write_text(native, encoding='utf-8')
            helper = fixture.ProductionTaskHostsTests()
            version = '21.0.631'
            for domain, scenario in (('material_lookdev_v1', 'build_inspect'),
                                     ('material_lookdev_v1', 'causal_candidate'),
                                     ('rbd_destruction_v1', 'causal_candidate')):
                with self.subTest(domain=domain, scenario=scenario):
                    case_id = domain + '__' + scenario
                    project = base / case_id
                    host = helper.config(project, 'houdini', python_host, api)
                    nuke = helper.config(project, 'nuke', fixture.SOFTWARE_PYTHON, api)
                    host['session_seconds'] = nuke['session_seconds'] = 120
                    prepare_graph(project, app=None, scheduler_root=project / 'scheduler',
                        execution_profile=True, render_profile=True,
                        production_host_config=host, production_nuke_config=nuke)
                    factory = prepared_case_factory({version:{case_id:str(project)}}, version,
                        allow_software_processes=True)
                    environment = {'BRIDGE_TEST_EXR_FIXTURE':str(frames),
                        'BRIDGE_TEST_NATIVE_ROOT':str(fixture.ROOT), 'BRIDGE_TEST_NATIVE_VERSION':version,
                        'HOUDINI_BRIDGE_STATE_DIR':str(project / 'bridge-state'),
                        'BRIDGE_SKILLS_STATE_ROOT':str(project / 'runtime-state')}
                    try:
                        with mock.patch.dict(os.environ, environment):
                            result = DomainReadinessRunner(task_id='nonlighting-readiness',
                                output_root=project / 'receipts', houdini_versions=(version,),
                                case_facade_factory=factory).run_case(domain, scenario).to_dict()
                        (project / 'readiness.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
                        self.assertEqual(result['status'], 'BLOCKED', result)
                        operations = [stage['operation'] for stage in result['stage_receipts']]
                        self.assertIn('graph_propose', operations, result)
                        self.assertIn('task_reopen', operations, result)
                        self.assertNotIn('agent.fx.build_preview', operations)
                        if domain == 'rbd_destruction_v1':
                            self.assertIn('FORMAL_SEMANTIC_FEEDBACK_UNAVAILABLE', result['blocker'])
                            self.assertNotIn('houdini_render_bounded', operations)
                        else:
                            self.assertIn('FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED', result['blocker'])
                            self.assertTrue(result['formal_controller_verified'])
                            self.assertEqual(result['execution_fact']['state'], 'COMPLETED')
                            self.assertEqual(result['execution_fact']['frames_done'], [1,3])
                            self.assertEqual(result['execution_fact']['scene']['sha256'], result['save_receipt']['sha256'])
                            self.assertNotIn('nuke_input_binding', result)
                            self._assert_full_formal_feedback(result, domain, version, scenario)
                            self.assertEqual(result['execution_fact']['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
                            self.assertEqual(result['execution_fact']['metadata'], {})
                            self.assertNotIn('register_render_artifact', operations)
                            self.assertNotIn('consume_artifact', operations)
                            self.assertNotIn('nuke_input_binding', operations)
                        self.assertFalse(result['real_dcc_verified'])
                    finally:
                        if (project / 'control/production-hosts.json').exists():
                            stops = stop_hosts(project / 'control')
                            (project / 'stops.json').write_text(json.dumps(stops, indent=2) + '\n', encoding='utf-8')
