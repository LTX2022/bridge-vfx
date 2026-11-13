from pathlib import Path
from contextlib import nullcontext
import hashlib
import json
import os
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from vfx_pipeline.domain_readiness import DOMAIN_IDS, SCENARIOS, DomainReadinessError, DomainReadinessRunner


def _nuke_composite_api_source(snapshot):
    """Explicit native API seam; the controller, add-on and workers stay shipped code."""
    return '''from pathlib import Path
import sys
_snapshot=Path(SNAPSHOT_ROOT)
for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(_snapshot/'packages'/package/'src'))
from vfx_pipeline.workbuddy_assembly import software_nuke_client
_client=software_nuke_client(_snapshot/'plugins/nuke/nuke_bridge_addon.py',Path(__file__).parent/'api-state')
_api=sys.modules['nuke']
_api.NUKE_VERSION_STRING='17.0v1'
_callbacks=[]
_original_open=_api.scriptOpen
def _open(path):
    _original_open(path)
    for callback in _callbacks:callback()
_api.scriptOpen=_open
_api.scriptClear=lambda:None
_api.addOnScriptLoad=_callbacks.append
_api.addOnScriptClose=lambda callback:None
_create=_api.createNode
def _profile(node):
    extras={'Read':{'colorspace':'linear','raw':False},
            'Write':{'colorspace':'linear','premultiplied':False,'raw':False}}
    for name,value in extras.get(node.Class(),{}).items():
        if node.knob(name) is None:
            knob=_api.String_Knob(name,name);knob.setValue(value);node.addKnob(knob)
    return node
def _create_profile(kind,inpanel=False):return _profile(_create(kind,inpanel=inpanel))
_api.createNode=_create_profile
for node in _api.allNodes():_profile(node)
_execute=_api.execute
def _execute_with_input_race(write,first,last,*rest):
    roles={str(node.knob('bridge_graph_role').value()):node for node in _api.allNodes()
           if node.knob('bridge_graph_role') is not None}
    if 'effect_blur' in roles and 'effect_premult' in roles:
        import json
        proof={'script':str(_api.root().name()),
               'blur_size':roles['effect_blur']['size'].value(),
               'premult_disabled':roles['effect_premult']['disable'].value(),
               'write_colorspace':write['colorspace'].value(),
               'write_premultiplied':write['premultiplied'].value(),
               'read_colorspace':roles['input_effect_render']['colorspace'].value()}
        (_snapshot.parent.parent/'consumed-composite-proof.json').write_text(json.dumps(proof))
    marker=_snapshot.parent.parent/'input-race.json'
    if marker.is_file():
        import hashlib,json
        from dcc_task_runtime.exr_codec import encode_tiny_exr
        request=json.loads(marker.read_text());marker.unlink()
        read=write
        while read.Class()!='Read':read=read.input(0)
        consumed=Path(str(read['file'].value()) % int(first))
        observed={'read_path':str(consumed),'sha256':hashlib.sha256(consumed.read_bytes()).hexdigest()}
        Path(request['source']).write_bytes(encode_tiny_exr(99.0))
        Path(request['proof']).write_text(json.dumps(observed))
    return _execute(write,first,last,*rest)
_api.execute=_execute_with_input_race
'''.replace('SNAPSHOT_ROOT', repr(str(snapshot)))


class FormalDomainRoutingTests(unittest.TestCase):
    def check_factory_failure(self, domain, scenario):
        host = mock.Mock()
        nuke = mock.Mock()
        factory = mock.Mock(side_effect=ValueError('FORMAL_CASE_CONFIG_REQUIRED: isolated case'))
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='contract', output_root=Path(directory),
                host_client=host, nuke_client=nuke, case_facade_factory=factory)
            result = runner.run_case(domain, scenario).to_dict()
        factory.assert_called_once_with(case_id=domain + '__' + scenario,
                                        domain=domain, scenario=scenario)
        host.call.assert_not_called()
        nuke.call.assert_not_called()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('FORMAL_CASE_CONFIG_REQUIRED', result['blocker'])
        self.assertEqual(result['case_execution'], 'prepared_production_controller')
        self.assertFalse(result['formal_controller_verified'])

    def test_material_and_rbd_never_fall_back_to_diagnostic(self):
        for domain in ('material_lookdev_v1', 'rbd_destruction_v1'):
            with self.subTest(domain=domain):
                self.check_factory_failure(domain, 'build_inspect')

    def test_every_formal_case_requires_its_own_factory(self):
        for domain in DOMAIN_IDS:
            for scenario in SCENARIOS:
                with self.subTest(domain=domain, scenario=scenario):
                    self.check_factory_failure(domain, scenario)

    def rejection_facade(self):
        owner = 'isolated-contract-owner'
        return SimpleNamespace(pipeline_task_id=owner, backend_kind='production',
            host_client=SimpleNamespace(bound_task_id=owner, backend_kind='production'),
            nuke_client=SimpleNamespace(bound_task_id=owner, backend_kind='production'),
            controller_source={'backend':'production', 'snapshot_manifest_sha256':'contract-input'},
            catalog=mock.Mock(return_value={'assets':[]}),
            graph_propose=mock.Mock(side_effect=ValueError('contract stops before native construction')))

    def test_material_and_rbd_select_registered_capability_and_retain_rejection(self):
        for domain in ('material_lookdev_v1', 'rbd_destruction_v1'):
            facade = self.rejection_facade()
            factory = mock.Mock(return_value=nullcontext(facade))
            with self.subTest(domain=domain), tempfile.TemporaryDirectory() as directory:
                runner = DomainReadinessRunner(task_id='contract', output_root=directory,
                    houdini_versions=('21.0.631',), case_facade_factory=factory)
                result = runner.run_case(domain, 'build_inspect').to_dict()
            facade.graph_propose.assert_called_once_with({
                'schema':'bridge.registered-domain-construction/1', 'domain_pack':domain,
                'houdini_version':'21.0.631'}, domain + '__build_inspect-proposal')
            self.assertEqual(result['status'], 'BLOCKED')
            rejected = result['stage_receipts'][-1]
            self.assertEqual(rejected['operation'], 'graph_propose')
            self.assertIn('stops before native construction', rejected['error'])
            self.assertEqual(rejected['task_id'], facade.pipeline_task_id)
            self.assertEqual(rejected['source'], facade.controller_source)
            self.assertEqual(result['controller_task_id'], facade.pipeline_task_id)
            self.assertEqual(result['controller_source'], facade.controller_source)
            self.assertFalse(result['formal_domain_lifecycle_verified'])
            self.assertTrue(result['explicit_stage_gaps'])

    def test_owner_source_and_owner_reuse_reject_before_graph_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            for mutation, blocker in (
                ('owner', 'FORMAL_CASE_OWNER_MISMATCH'),
                ('source', 'FORMAL_SOURCE_MISSING'),
                ('reuse', 'FORMAL_CASE_OWNER_REUSED'),
            ):
                facade = self.rejection_facade()
                if mutation == 'owner':
                    facade.host_client.bound_task_id = 'foreign'
                elif mutation == 'source':
                    facade.controller_source.pop('snapshot_manifest_sha256')
                runner = DomainReadinessRunner(task_id='contract', output_root=directory,
                    case_facade_factory=lambda **kwargs: nullcontext(facade))
                if mutation == 'reuse':
                    runner._formal_owners[facade.pipeline_task_id] = 'another-case'
                with self.subTest(mutation=mutation):
                    result = runner.run_case('material_lookdev_v1', 'build_inspect').to_dict()
                    self.assertEqual(result['status'], 'BLOCKED')
                    self.assertIn(blocker, result['blocker'])
                    facade.catalog.assert_not_called()
                    facade.graph_propose.assert_not_called()

    def test_unsupported_domains_and_both_vellum_branches_stay_specific_blocked(self):
        for domain, blocker in (
            ('explosion_composite_v1', 'FORMAL_DOMAIN_CONSTRUCTION_UNAVAILABLE'),
            ('vellum_softbody_grains_v1', 'FORMAL_NATIVE_BRANCH_COVERAGE_REQUIRED'),
        ):
            facade = self.rejection_facade()
            with self.subTest(domain=domain), tempfile.TemporaryDirectory() as directory:
                runner = DomainReadinessRunner(task_id='contract', output_root=directory,
                    case_facade_factory=lambda **kwargs: nullcontext(facade))
                result = runner.run_case(domain, 'build_inspect').to_dict()
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertIn(blocker, result['blocker'])
            facade.graph_propose.assert_not_called()

    def test_formal_nuke_requires_registered_input_without_accessing_houdini(self):
        facade = self.rejection_facade()
        facade.host_client = None
        facade.nuke_client.production_config = {'version': '17.0v1'}
        facade.manifest = {}
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='nuke-only', output_root=directory,
                case_facade_factory=lambda **kwargs: nullcontext(facade))
            result = runner.run_case('nuke_composite_v1', 'build_inspect').to_dict()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('NUKE_INPUT_ARTIFACT_NOT_BOUND', result['blocker'])
        facade.graph_propose.assert_not_called()
        facade.catalog.assert_not_called()
        self.assertEqual(result['controller_task_id'], facade.pipeline_task_id)

    def test_formal_nuke_never_prepares_or_builds_an_unusable_input(self):
        for mutation in ('missing', 'foreign', 'stale'):
            facade = self.rejection_facade()
            facade.host_client = None
            facade.nuke_client.production_config = {'version': '17.0v1'}
            facade.manifest = {'nuke_input_artifact_id': 'explicit-input'}
            facade.artifact_registry = mock.Mock()
            entry = {'task_id': facade.pipeline_task_id, 'frame_set': [1, 2]}
            facade.artifact_registry.lookup.return_value = None if mutation == 'missing' else {
                **entry, 'task_id': 'foreign' if mutation == 'foreign' else facade.pipeline_task_id}
            facade.consume_artifact = mock.Mock(return_value={'usable_as_render_input': False})
            facade.nuke_composite_action = mock.Mock()
            facade.nuke_client.prepare_input_artifact = mock.Mock()
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                result = DomainReadinessRunner(task_id='nuke-only', output_root=directory,
                    case_facade_factory=lambda **kwargs: nullcontext(facade)).run_case(
                        'nuke_composite_v1', 'build_inspect').to_dict()
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertIn('NUKE_INPUT_ARTIFACT_', result['blocker'])
            facade.nuke_composite_action.assert_not_called()
            facade.nuke_client.prepare_input_artifact.assert_not_called()
            facade.catalog.assert_not_called()

    def test_formal_composite_never_uses_diagnostic_upstream(self):
        host = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='contract', output_root=directory,
                host_client=host, case_facade_factory=mock.Mock())
            result = runner._composite_dataflow('isolated-composite', ['rbd_destruction_v1'])
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('FORMAL_COMPOSITE_DATAFLOW_UNAVAILABLE', result['blocker'])
        self.assertEqual(result['upstream_attempts'], [])
        host.call.assert_not_called()

    def test_terminal_construction_rejects_foreign_graph_before_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='contract', output_root=directory)
            with self.assertRaisesRegex(DomainReadinessError, 'FORMAL_GRAPH_OPERATION_MISMATCH'):
                runner._wait_for_construction(mock.Mock(), 'owned-graph', 'request',
                    {'operation_id':'owned-operation', 'graph_id':'foreign-graph',
                     'state':'SUCCEEDED', 'stop_confirmed':True}, 1)

    def test_diagnostic_success_is_retained_without_domain_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = DomainReadinessRunner(task_id='contract', output_root=directory)
            with mock.patch.object(runner, '_houdini', return_value={'status':'PASS',
                    'stage_receipts':[], 'recovery':{'tested':False}}):
                result = runner.run_case('rbd_destruction_v1', 'build_inspect').to_dict()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['diagnostic_status'], 'PASS')
        self.assertIn('FORMAL_CASE_FACADE_REQUIRED', result['blocker'])
        self.assertFalse(result['formal_controller_verified'])


class FormalProducerRejectionTests(unittest.TestCase):
    def test_missing_diagnostic_stale_foreign_and_unknown_stop_facts_are_rejected(self):
        saved = {'path':'current.hip', 'sha256':'saved-content',
            'scene_contract':{'task_id':'owner'}, 'scene_contract_sha256':'owned-contract',
            'feedback_dependencies':['graph-version-1']}
        arguments = dict(operation_id='owned-render', owner='owner', frames=[1,3],
            pattern='contract.%03d.exr', target='/owned/render', saved=saved)
        contract = {'kind':'houdini-render', 'operation':{'state':'COMPLETED'},
            'execution_fact':{'schema':'bridge.houdini.render.execution_fact/1.0',
                'state':'COMPLETED', 'command':'render.start',
                'operation_id':'owned-render', 'stop_confirmed':True, 'task_id':'owner',
                'frame_set':[1,3], 'frames_done':[1,3], 'output_pattern':'contract.%03d.exr',
                'render_target':'/owned/render', 'scene':{'path':'current.hip', 'sha256':'saved-content',
                    'snapshot_sha256':'saved-content', 'scene_contract':saved['scene_contract'],
                    'scene_contract_sha256':saved['scene_contract_sha256']}, 'operation_receipt_sha256':'contract-input',
                'dependencies':['graph-version-1']}}
        for mutation in (
            {'state':'RUNNING'}, {'command':'agent.fx.software_boundary_execute'},
            {'operation_id':'foreign'}, {'stop_confirmed':False}, {'task_id':'foreign'},
            {'frame_set':[1,2]}, {'frames_done':[1]}, {'output_pattern':'foreign.%03d.exr'},
            {'render_target':'/foreign/render'}, {'scene':{'sha256':'old-content'}},
            {'schema':'legacy-render-metadata'},
            {'scene':{**contract['execution_fact']['scene'], 'path':'foreign.hip'}},
            {'scene':{**contract['execution_fact']['scene'], 'scene_contract':{'task_id':'foreign'}}},
            {'operation_receipt_sha256':''}, {'dependencies':['graph-version-0']},
        ):
            queried = {**contract, 'execution_fact':{**contract['execution_fact'], **mutation}}
            with self.subTest(mutation=mutation), self.assertRaisesRegex(DomainReadinessError, 'FORMAL_RENDER_INCOMPLETE'):
                DomainReadinessRunner._formal_producer_fact(queried, **arguments)
        for queried in ({}, {'status':'PASS'}, {**contract, 'kind':'diagnostic'},
                        {**contract, 'operation':{'state':'RUNNING'}}):
            with self.subTest(queried=queried), self.assertRaisesRegex(DomainReadinessError, 'FORMAL_RENDER_INCOMPLETE'):
                DomainReadinessRunner._formal_producer_fact(queried, **arguments)


class PreparedNukeOnlyTests(unittest.TestCase):
    def test_nuke_only_tcp_saved_composite_and_owned_preview(self):
        self._run_nuke_only_tcp_case(feedback=True)

    def test_nuke_only_tcp_replacement_during_execute_never_registers_output(self):
        self._run_nuke_only_tcp_case(input_race=True)

    def _run_nuke_only_tcp_case(self, *, input_race=False, feedback=False):
        from dcc_task_runtime.exr_codec import encode_tiny_exr
        from prepare_workbuddy_graph import prepare_graph
        from run_full_readiness_cases import prepared_case_factory
        from vfx_pipeline.production_hosts import stop_hosts
        from software_host_bootstrap import SOFTWARE_PYTHON
        retained = os.environ.get('BRIDGE_FORMAL_NUKE_EVIDENCE_DIR')
        workspace = nullcontext(retained) if retained else tempfile.TemporaryDirectory()
        with workspace as temporary:
            root = Path(temporary).resolve(); root.mkdir(parents=True, exist_ok=True)
            project = root / 'project'; api = root / 'api'; api.mkdir()
            (api / 'nuke.py').write_text(_nuke_composite_api_source(project/'control/snapshot'), encoding='utf-8')
            config = {'lifecycle':'task_owned','application':'nuke','version':'17.0v1',
                'executable':str(SOFTWARE_PYTHON),'supervisor_executable':str(SOFTWARE_PYTHON),
                'task_root':str(project), 'resource_budget':{'roots':[str(project)],'max_bytes':128*1024*1024},
                'session_seconds':120, 'evidence_source':'software_test', 'software_api_dir':str(api)}
            prepare_graph(project, app=None, application='nuke', scheduler_root=project/'scheduler',
                execution_profile=True, render_profile=True, production_nuke_config=config)
            scenario = 'causal_candidate' if feedback else 'build_inspect'
            case_id = 'nuke_composite_v1__' + scenario
            configured = prepared_case_factory({'17.0v1':{case_id:str(project)}}, 'no-houdini-required',
                allow_software_processes=True)
            race_expected = {}
            from contextlib import contextmanager
            @contextmanager
            def factory(**kwargs):
                with configured(**kwargs) as facade:
                    self.assertIsNone(facade.host_client)
                    self.assertIsNone(facade.jobs_service)
                    client = facade.nuke_client
                    source = project / 'synthetic-source.%04d.exr'
                    pattern = str(Path(facade.save_root) / 'registered-input.%04d.exr')
                    for frame in (1,2):
                        Path(str(source) % frame).write_bytes(encode_tiny_exr(float(frame)))
                    for node, settings in (('Read1',{'file':str(source),'colorspace':'linear','raw':False}),
                            ('Write1',{'file':pattern,'colorspace':'linear','raw':False,'premultiplied':False})):
                        for knob,value in settings.items():client.call('set_knob',{'node':node,'knob':knob,'value':value})
                    client.call('connect_nodes',{'src':'Read1','dst':'Write1','input_index':0})
                    client.call('save_script',{'path':str(Path(facade.save_root)/'fixture.nk'),'overwrite':True})
                    bootstrap = client.call('render_write',{'node':'Write1','request_id':'explicit-software-fixture',
                        'frame_set':[1,2],'frame_range':[1,2],'pattern':pattern,'background':True,
                        'colorspace':'linear','premultiplied':False,
                        'output_binding':{'source':'controller','task_id':facade.pipeline_task_id,'node':'Write1','pattern':pattern,'frames':[1,2],
                            'input_binding':{'kind':'bootstrap_source','owner_task_id':facade.pipeline_task_id}}})
                    deadline = time.monotonic() + 25
                    while True:
                        status = client.call('render_status',{'task_id':bootstrap['operation_id']})
                        if status.get('state') not in {'RUNNING','CANCEL_PENDING'} or time.monotonic() >= deadline:break
                        time.sleep(.05)
                    self.assertEqual(status.get('state'),'COMPLETED',str(status))
                    artifact_id = 'nuke-render-' + bootstrap['operation_id']
                    self.assertTrue(facade.consume_artifact(artifact_id)['usable_as_render_input'])
                    facade.manifest['nuke_input_artifact_id'] = artifact_id
                    if input_race:
                        public = Path(pattern % 1)
                        race_expected['sha256'] = hashlib.sha256(public.read_bytes()).hexdigest()
                        (project/'input-race.json').write_text(json.dumps({'source':str(public),
                            'proof':str(project/'consumed-input-proof.json')}))
                    yield facade
            try:
                result = DomainReadinessRunner(task_id='nuke-only',output_root=root/'receipts',
                    case_facade_factory=factory).run_case('nuke_composite_v1',scenario).to_dict()
                (root/'nuke-readiness.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                self.assertEqual(result['status'],'BLOCKED')
                self.assertIn('FORMAL_NUKE_PREVIEW_INCOMPLETE' if input_race else 'FORMAL_NUKE_LIFECYCLE_INCOMPLETE',result['blocker'])
                self.assertTrue(result['formal_controller_verified'])
                self.assertFalse(result['formal_domain_lifecycle_verified'])
                if input_race:
                    self.assertIn('preview',result['explicit_stage_gaps'])
                    self.assertEqual(result['preview_operation']['state'],'FAILED')
                    proof = json.loads((project/'consumed-input-proof.json').read_text())
                    self.assertEqual(proof['sha256'],race_expected['sha256'])
                    self.assertIn('verified-nuke-input-',proof['read_path'])
                    from vfx_pipeline.artifact_registry import ArtifactRegistry
                    ledger=ArtifactRegistry(project/'control/artifact_ledger')
                    self.assertIsNone(ledger._lookup_unchecked('nuke-render-'+result['preview_operation']['task_id']))
                    self.assertTrue(result['preview_operation']['slot_released'])
                else:
                    self.assertNotIn('preview',result['explicit_stage_gaps'])
                    self.assertEqual(result['execution_fact']['execution_kind'],'owned_subprocess')
                    self.assertTrue(result['execution_fact']['stop_confirmed'])
                    self.assertEqual(result['preview_operation']['state'],'COMPLETED')
                    self.assertTrue(result['execution_fact']['execution_fact']['worker_receipt']['input_readback']['after_verified'])
                    if feedback:
                        proof = json.loads((project/'consumed-composite-proof.json').read_text())
                        worker = result['execution_fact']['execution_fact']['worker_receipt']
                        supervisor = result['execution_fact']['execution_fact']['process_identity']['supervisor_identity']
                        formal = result['execution_fact']['formal_receipt']
                        self.assertEqual(worker['composite_readback']['owner_task_id'],result['controller_task_id'])
                        self.assertEqual(supervisor['owner_task_id'],result['controller_task_id'])
                        self.assertEqual(worker['composite_readback']['contract_sha256'],supervisor['composite_contract_sha256'])
                        self.assertEqual(formal['composite_contract']['task_id'],formal['task_id'])
                        self.assertEqual(formal['task_id'],result['controller_task_id'])
                        self.assertEqual(proof['script'], worker['snapshot'])
                        self.assertEqual(proof['blur_size'], 1.5)
                        self.assertIs(proof['premult_disabled'], False)
                        self.assertEqual(proof['read_colorspace'], 'linear')
                        self.assertEqual(proof['write_colorspace'], 'linear')
                        self.assertIs(proof['write_premultiplied'], True)
                self.assertTrue(result['reopen_receipt']['registry_cache_invalidated'])
                self.assertFalse((project/'control/houdini-task-host').exists())
                deployment = json.loads((project/'control/production-hosts.json').read_text())
                self.assertEqual(set(deployment['hosts']),{'nuke'})
            finally:
                if (project/'control/production-hosts.json').exists():stop_hosts(project/'control')

    def test_prepared_nuke_selection_uses_only_nuke_version_configuration(self):
        from run_full_readiness_cases import prepared_case_factory
        case_id = 'nuke_composite_v1__build_inspect'
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory); (project / 'control').mkdir()
            (project / 'control/run.json').write_text(json.dumps({'production_nuke':{'version':'17.0v1'}}))
            (project / 'control/snapshot-manifest.json').write_text('{}')
            with mock.patch('run_full_readiness_cases.prepared_graph_facade') as prepared:
                prepared_case_factory({'17.0v1':{case_id:str(project)}}, 'not-a-houdini-version')(
                    case_id=case_id, domain='nuke_composite_v1', scenario='build_inspect')
                self.assertEqual(prepared.call_args.kwargs['application'], 'nuke')

    def test_prepared_nuke_controller_never_constructs_a_houdini_client_or_graph_job(self):
        from prepare_workbuddy_graph import prepare_graph
        from vfx_pipeline.workbuddy_assembly import prepared_graph_facade
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'prepared'
            prepare_graph(project, app=None, application='nuke', execution_profile=True,
                render_profile=True, production_nuke_config={'application': 'nuke', 'version': '17.0v1'})
            nuke = mock.Mock(backend_kind='production')
            with mock.patch('vfx_pipeline.workbuddy_assembly.production_nuke_client', return_value=nuke), \
                 mock.patch('vfx_pipeline.workbuddy_assembly.production_host_client', side_effect=AssertionError('Houdini must not be created')), \
                 mock.patch('vfx_pipeline.graph_jobs.GraphJobService', side_effect=AssertionError('Houdini graph jobs must not be created')):
                with prepared_graph_facade(project / 'control/run.json',
                        repo_root=project / 'control/snapshot', scheduler_root=root / 'scheduler') as facade:
                    self.assertIsNone(facade.host_client)
                    self.assertIsNone(facade.jobs_service)
                    self.assertIs(facade.nuke_client, nuke)
                    self.assertEqual(facade.application, 'nuke')
                    nuke.bind_task.assert_called_once_with(facade.pipeline_task_id)
                    from vfx_pipeline.workbuddy_graph_mcp import GraphMCP
                    mcp = GraphMCP(facade)
                    self.assertNotIn('graph_propose', {tool['name'] for tool in mcp.tools})
                    self.assertTrue(mcp._call({'name':'graph_propose', 'arguments':{}})['isError'])

    def test_composite_save_callback_drift_never_launches(self):
        import sys
        import test_nuke_software_snapshot as snapshots
        for knob, save_number in (("blur", 1), ("premult", 2), ("connection", 2), ("root", 2)):
            with self.subTest(drift=knob, save=save_number), tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules):
                root = Path(directory)
                api, addon, client, spec, step, task, adapter = snapshots.ActualPluginRetryTests()._fixture(root)
                params = {'task_id':task.name, 'inputs':list(spec.inputs), 'render':spec.render}
                client.call('agent.nuke.composite.apply_patch', {**params,
                    'step_params':{'patch':{'controls':{'blur_size':1.5, 'premult':True}}}})
                state = addon._COMPOSITES[task.name]
                write = api.toNode(state['write'])
                save = api.scriptSave
                count = {'value':0}
                def save_callback():
                    count['value'] += 1
                    if count['value'] == save_number:
                        if knob == 'blur':
                            api.toNode(state['graph_nodes']['effect_blur'])['size'].setValue(99.0)
                        elif knob == 'premult':
                            api.toNode(state['graph_nodes']['effect_premult'])['disable'].setValue(True)
                        elif knob == 'root':
                            api.root()['first_frame'].setValue(9)
                        else:
                            write.setInput(0, api.toNode(state['input_nodes']['effect_render']))
                    save()
                launcher = mock.Mock(side_effect=addon.RenderDispatchError('unexpected worker launch', started=False))
                with mock.patch.object(api, 'scriptSave', side_effect=save_callback), \
                     mock.patch.object(addon, '_NUKE_BACKGROUND_LAUNCHER', launcher):
                    with self.assertRaisesRegex((ValueError, RuntimeError), 'COMPOSITE_.*(DRIFT|MISMATCH|INVALID)|SCENE_STATE_DRIFT'):
                        client.call('render_write', {'node':write.name(), 'request_id':'save-drift',
                            'background':True, 'frame_set':[1], 'frame_range':[1,1], 'pattern':str(write['file'].value()),
                            'output_binding':{'source':'controller','task_id':task.name,'node':write.name(),
                                'pattern':str(write['file'].value()),'frames':[1],
                                'input_binding':{'kind':'artifact_read','owner_task_id':task.name}}})
                launcher.assert_not_called()
                self.assertFalse(list((root/'records').glob('*.worker-result.json')))
                self.assertFalse((addon._fx_graph_scheduler().snapshot() or {}).get('active'))
                self.assertFalse(list(root.rglob('final.0001.exr')))

    def test_composite_binding_requires_one_logical_owner_before_mutation(self):
        import sys
        import test_nuke_software_snapshot as snapshots
        from nuke_bridge.operation_receipts import freeze_agent_inputs
        for mode in ('missing_owner','wrong_owner','wrong_input_owner','wrong_host','foreign_graph','valid'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules):
                root = Path(directory)
                api, addon, client, spec, step, task, adapter = snapshots.ActualPluginRetryTests()._fixture(root)
                owner = task.name
                state = addon._COMPOSITES[owner]
                write = api.toNode(state['write'])
                if mode == 'foreign_graph':
                    for name in state['graph_nodes'].values():
                        api.toNode(name)['bridge_task_id'].setValue('foreign')
                    addon._COMPOSITES.pop(owner)
                    state['task_id'] = 'foreign'; addon._persist_composite_state(state)
                    self.assertTrue(addon._validate_composite_topology(state)['topology']['passed'])
                inputs = freeze_agent_inputs('foreign' if mode == 'wrong_input_owner' else owner,list(spec.inputs))
                pattern = str(write['file'].value())
                binding = {'source':'controller','task_id':owner,'node':write.name(),
                    'pattern':pattern,'frames':[1],'input_binding':inputs}
                if mode == 'missing_owner':binding.pop('task_id')
                elif mode == 'wrong_owner':binding['task_id'] = 'foreign'
                params = {'output_binding':binding,'pattern':pattern,'frame_set':[1],'frame_range':[1,1],
                    'background':True,'request_id':'logical-owner'}
                with mock.patch.object(addon,'_TASK_HOST_IDENTITY',{'task_id':'foreign' if mode == 'wrong_host' else owner}), \
                     mock.patch.object(addon,'_nuke_render_operation',return_value={'state':'RUNNING'}) as operation, \
                     mock.patch.object(api,'scriptSave') as save, mock.patch.object(addon,'_fx_graph_scheduler') as scheduler:
                    if mode == 'valid':
                        self.assertEqual(client.call('render_write',params)['state'],'RUNNING')
                        operation.assert_called_once()
                    else:
                        with self.assertRaisesRegex(ValueError,'OUTPUT_BINDING_OWNER_MISMATCH'):
                            client.call('render_write',params)
                        operation.assert_not_called()
                    save.assert_not_called(); scheduler.assert_not_called()
                    self.assertEqual(write['file'].value(),pattern)

    def test_composite_worker_rejects_load_and_execute_drift(self):
        import sys
        import test_nuke_software_snapshot as snapshots
        from nuke_bridge import owned_render_worker as worker
        from nuke_bridge.operation_receipts import worker_composite_readback_valid
        for phase, drift in (('load','blur'), ('load','premult'), ('load','connection'),
                             ('execute','blur'), ('execute','premult'), ('execute','connection'),
                             ('owner','missing'), ('owner','foreign')):
            with self.subTest(phase=phase, drift=drift), tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules):
                root = Path(directory)
                api, addon, client, spec, step, task, adapter = snapshots.ActualPluginRetryTests()._fixture(root)
                params = {'task_id':task.name, 'inputs':list(spec.inputs), 'render':spec.render}
                client.call('agent.nuke.composite.apply_patch', {**params,
                    'step_params':{'patch':{'controls':{'blur_size':1.5, 'premult':True}}}})
                state = addon._COMPOSITES[task.name]; write = api.toNode(state['write'])
                contract = addon._freeze_composite_consumption(write)
                api.scriptSave()
                path = root/'render-op.composite.json'
                content = json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                path.write_bytes(content); digest = hashlib.sha256(content).hexdigest()
                self.assertFalse(worker_composite_readback_valid({},contract,digest))
                fresh = worker._SoftwareNuke('unused')
                native_open, native_execute = fresh.scriptOpen, fresh.execute
                def mutate():
                    if drift == 'blur':
                        fresh.toNode(state['graph_nodes']['effect_blur'])['size'].setValue(99.0)
                    elif drift == 'premult':
                        fresh.toNode(state['graph_nodes']['effect_premult'])['disable'].setValue(True)
                    else:
                        fresh.toNode(state['write']).inputs[0] = fresh.toNode(state['input_nodes']['effect_render'])
                def open_script(path):
                    native_open(path)
                    if phase == 'load':mutate()
                def execute(node, first, last):
                    native_execute(node,first,last)
                    if phase == 'execute':mutate()
                environment = {'BRIDGE_NUKE_COMPOSITE_CONTRACT':str(path),
                    'BRIDGE_NUKE_COMPOSITE_CONTRACT_SHA256':digest, 'BRIDGE_NUKE_TASK_ID':'render-op',
                    'BRIDGE_NUKE_RESULT_FILE':str(root/'render-op.worker-result.json'),
                    'BRIDGE_NUKE_OWNER_TASK_ID':task.name}
                if phase == 'owner':
                    if drift == 'missing':environment.pop('BRIDGE_NUKE_OWNER_TASK_ID')
                    else:environment['BRIDGE_NUKE_OWNER_TASK_ID'] = 'foreign'
                with mock.patch.dict(os.environ,environment), mock.patch.object(worker,'_input_contract',return_value=None), \
                     mock.patch.object(worker,'_load_nuke_api',return_value=fresh), \
                     mock.patch.object(fresh,'scriptOpen',side_effect=open_script), \
                     mock.patch.object(fresh,'execute',side_effect=execute), mock.patch.object(worker,'_write_receipt') as receipt:
                    with self.assertRaisesRegex(ValueError,'COMPOSITE_(SNAPSHOT_MISMATCH|CONTRACT_INVALID)'):
                        worker.main(['worker',str(root/'scene.nk'),write.name(),'1','1',str(write['file'].value()),'[1]'])
                    receipt.assert_not_called()
                self.assertFalse((root/'render-op.worker-result.json').exists())

    def test_composite_preview_keeps_native_connections_and_persists_operation_route(self):
        from vfx_pipeline.workbuddy_graph_mcp import GraphRun
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.0001.exr'
            source.write_bytes(b'explicit unit boundary input')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            pattern = str(root / 'input.%04d.exr')
            output = root / 'saves'; output.mkdir()
            final = str(output / 'case' / 'final.%04d.exr')
            manifest = root / 'run.json'
            manifest.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0',
                'run_id':'nuke-composite', 'assets':[], 'construction_authorized':True,
                'execution_authorized':True, 'render_authorized':True}))
            snapshots = {'1': {'sha256': digest, 'bytes': source.stat().st_size}}
            registry = mock.Mock()
            registry.lookup.return_value = {'task_id':'owner', 'pattern':pattern,
                'payload':{'completion_snapshot':snapshots}}
            graph = {'write':'CompositeWrite', 'final_pattern':final,
                'input_nodes':{'effect_render':'CompositeRead'},
                'graph_nodes':{'effect_blur':'Blur', 'effect_premult':'Premult', 'final_write':'CompositeWrite'}}
            nodes = {'CompositeRead': {'class':'Read', 'knobs':{'file':pattern, 'colorspace':'linear', 'raw':False}},
                'Premult': {'class':'Premult', 'knobs':{'disable':False}},
                'Blur': {'class':'Blur', 'knobs':{'size':1.5}},
                'CompositeWrite': {'class':'Write', 'knobs':{'file':final,
                    'colorspace':'linear', 'premultiplied':False, 'raw':False}, 'inputs':['Blur']}}
            initial_nodes = json.loads(json.dumps(nodes))
            calls = []
            fault = {'mode':'normal'}
            def call(command, params):
                calls.append((command, params))
                if command == 'agent.nuke.composite.build_graph':
                    return {'graph':graph, 'gates':[{'name':'editable_native_composite_graph', 'passed':True}]}
                if command == 'agent.nuke.composite.audit_lineage':
                    count = sum(name == command for name, _ in calls)
                    return {'gates':[{'name':'reference_isolated_from_final_write',
                        'passed':not (fault['mode'] == 'audit_reject' and count == 2)}]}
                if command == 'get_node':
                    if (params['name'] == 'Premult' and fault['mode'] == 'premult_readback'
                            and sum(name == command and args.get('name') == 'Premult' for name, args in calls) == 2):
                        return {'class':'Premult', 'knobs':{'disable':True}}
                    return nodes[params['name']]
                if command == 'set_knob':
                    final_write = (params['node'], params['knob'], params['value']) == ('CompositeWrite', 'raw', False)
                    if final_write and fault['mode'] == 'setting_reject':
                        raise ValueError('explicit native color setting failure')
                    nodes[params['node']]['knobs'][params['knob']] = params['value']
                    if final_write and fault['mode'] == 'color_drift':
                        nodes['CompositeRead']['knobs']['colorspace'] = 'unexpected'
                    return {'value':params['value']}
                if command == 'render_write':
                    if fault['mode'] == 'submit_unknown':
                        raise TimeoutError('submission result unknown')
                    return {'operation_id':'native-owned-operation', 'state':'RUNNING'}
                if command == 'render_status':
                    return {'state':'RUNNING'}
                raise AssertionError(command)
            client = SimpleNamespace(call=call)
            facade = GraphRun(manifest, None, task_id='owner', nuke_client=client,
                artifact_registry=registry, save_root=str(output))
            facade.consume_artifact = mock.Mock(return_value={'artifact_id':'explicit-input',
                'pattern':pattern, 'usable_as_render_input':True, 'colorspace':'linear',
                'premultiplied':False, 'verification':{'frame_set':[1]}})
            spec = {'task_id':'owner', 'inputs':[{'role':'effect_render', 'artifact_id':'explicit-input',
                'path':pattern, 'frames':[{'frame':1, 'path':str(source), 'sha256':digest,
                    'bytes':source.stat().st_size}]}],
                'render':{'output_dir':str(output / 'case'), 'frame_range':{'start':1,'end':1,'step':1}}}
            result = facade.nuke_composite_render_bounded('bounded-preview', spec, [1])
            self.assertEqual(result['operation_id'], 'native-owned-operation')
            render = next(params for command, params in calls if command == 'render_write')
            self.assertTrue(render['background'])
            self.assertTrue(render['premultiplied'])
            self.assertEqual(render['node'], 'CompositeWrite')
            self.assertEqual(nodes['CompositeWrite']['inputs'], ['Blur'])
            self.assertNotIn('connect_nodes', [command for command, _ in calls])
            audits = [index for index, (command, _) in enumerate(calls)
                      if command == 'agent.nuke.composite.audit_lineage']
            self.assertEqual(len(audits), 2)
            self.assertGreater(audits[-1], max(index for index, (command, _) in enumerate(calls) if command == 'set_knob'))
            self.assertLess(audits[-1], next(index for index, (command, _) in enumerate(calls) if command == 'render_write'))
            restored = GraphRun(manifest, None, task_id='owner', nuke_client=client,
                artifact_registry=registry, save_root=str(output))
            self.assertEqual(restored.operation_query(result['operation_id'])['kind'], 'nuke-render')
            for mode in ('audit_reject', 'color_drift', 'premult_readback', 'setting_reject', 'submit_unknown'):
                with self.subTest(mode=mode):
                    nodes = json.loads(json.dumps(initial_nodes))
                    nodes['CompositeRead']['knobs'].update(colorspace='display', raw=True)
                    nodes['CompositeWrite']['knobs'].update(colorspace='display', raw=True)
                    before = json.loads(json.dumps(nodes))
                    calls.clear(); fault['mode'] = mode
                    expected = TimeoutError if mode == 'submit_unknown' else ValueError
                    message = {'audit_reject':'NUKE_COMPOSITE_GRAPH_UNVERIFIED',
                        'color_drift':'NUKE_COMPOSITE_NATIVE_COLOR_READBACK_FAILED',
                        'premult_readback':'NUKE_COMPOSITE_PREMULT_READBACK_REQUIRED',
                        'setting_reject':'explicit native color setting failure',
                        'submit_unknown':'submission result unknown'}[mode]
                    with self.assertRaisesRegex(expected, message):
                        facade.nuke_composite_render_bounded('preview-' + mode, spec, [1])
                    submitted = any(command == 'render_write' for command, _ in calls)
                    self.assertEqual(submitted, mode == 'submit_unknown')
                    self.assertEqual(nodes['Blur']['knobs']['size'], 1.5)
                    self.assertIs(nodes['Premult']['knobs']['disable'], False)
                    if mode == 'submit_unknown':
                        self.assertEqual(nodes['CompositeRead']['knobs']['colorspace'], 'linear')
                        self.assertEqual(nodes['CompositeWrite']['knobs']['colorspace'], 'linear')
                        self.assertIs(nodes['CompositeWrite']['knobs']['premultiplied'], True)
                    else:
                        self.assertEqual(nodes, before)
