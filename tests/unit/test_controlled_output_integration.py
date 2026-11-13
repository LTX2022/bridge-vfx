"""Detached software integration only: signed Python producer, no native DCC."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'vfx-pipeline', 'nuke-bridge'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
from dcc_task_runtime import alpha_calibration, owned_process
from dcc_task_runtime.artifact_registry import ArtifactRegistry, ArtifactError
from houdini_bridge import controlled_output, client
from vfx_pipeline import workbuddy_assembly
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary, ProductionBoundaryError
from vfx_pipeline.workbuddy_graph_mcp import GraphRun
import test_alpha_calibration as alpha_fixtures
import test_controlled_output as controlled_fixtures


class ControlledOutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        canonical_temporary_root = mock.patch.object(tempfile, 'tempdir', '/private/tmp')
        canonical_temporary_root.start()
        self.addCleanup(canonical_temporary_root.stop)
        helper = controlled_fixtures.ControlledOutputTests()
        self.addCleanup(helper.doCleanups)
        self.fixture = helper.prepared_fixture()
        self.root = self.fixture.root
        authority, terminal = alpha_fixtures.signed_fixture(self.root / 'alpha')
        terminal['route_sha256'] = controlled_output.controlled_route_sha256(helper.readback())
        owned_process._signed_write(Path(authority['directory']), terminal)
        authority['terminal_sha256'] = alpha_calibration._sha(terminal)
        self.authority, self.terminal = authority, terminal
        self.config = {'application': 'houdini', 'version': '21.0.631', 'plugin_build': 'fixture-build',
            'transport': 'http', 'host': '127.0.0.1', 'port': 1,
            'task_root': str(self.root), 'executable': sys.executable,
            'output_acceptance': copy.deepcopy(controlled_output._POLICY),
            'alpha_calibration': authority, 'evidence_source': 'software_test'}
        self.state = self.root / 'configured-state'
        self.state.mkdir()
        self.boundary = self.boundary_instance()
        parent = dict(copy.deepcopy(self.fixture.binding), task_id='fixture-owner')
        self.boundary._store_operation_owner('fixture-operation', parent)
        self.manifest = self.root / 'graph-run.json'
        self.manifest.write_text(json.dumps({'schema': 'bridge.workbuddy.diagnostic_run/1.0',
            'run_id': 'controlled-output-software-integration', 'assets': [], 'construction_authorized': True}))
        self.registry = ArtifactRegistry(self.root / 'ledger')
        self.boundary.bind_artifact_registry(self.registry)
        self.run = self.graph_run(self.boundary, self.registry)
        self.run._register_operation('fixture-operation', 'houdini-render', 'houdini', 'fixture-operation')
        self.sources = {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (client, controlled_output, alpha_calibration, workbuddy_assembly)}

    def boundary_instance(self):
        transport = mock.Mock(name='forbidden-native-transport')
        transport.health.side_effect = AssertionError('detached output verification attempted host health')
        transport.call.side_effect = AssertionError('detached output verification attempted native dispatch')
        boundary = _ConfiguredBoundary(kind='houdini', transport=transport, config=self.config, state_dir=self.state)
        boundary.bind_task('fixture-owner')
        boundary._verify_identity = mock.Mock(side_effect=AssertionError('detached verification attempted live identity'))
        return boundary

    def graph_run(self, boundary, registry):
        return GraphRun(self.manifest, jobs=None, task_id='fixture-owner', host_client=boundary,
                        artifact_registry=registry, save_root=self.root)

    def register(self, registry, fact, **changes):
        options = dict(artifact_id='software-controlled-beauty', task_id='fixture-owner', artifact_class='preview_temp',
            pattern=fact['output_pattern'], frame_set=fact['frame_set'], colorspace='ACEScg', premultiplied=True,
            dependencies=fact['dependencies'], operation_id='verify-software',
            operation_receipt_sha256=fact['operation_receipt_sha256'], scene_fingerprint=fact['scene_fingerprint'],
            receipt_source_files=self.sources)
        options.update(changes)
        return registry.register(**options)

    def verified(self):
        return self.run.verify_render_output('verify-software', 'fixture-operation')['execution_fact']

    def nuke_consumer_fixture(self):
        from nuke_bridge import task_host
        from nuke_bridge.operation_receipts import freeze_agent_inputs, registered_input_contract
        from test_native_scope import software_scope
        executable = Path(sys.executable).resolve()
        binary = {'path':str(executable), 'bytes':executable.stat().st_size,
                  'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}
        color = self.fixture.record['project_color']
        scope = software_scope(self.root, versions={'houdini':'21.0.631','nuke':'17.0v1'}, project_color=color,
                               hosts={name:dict(binary) for name in ('hython','husk','nuke','supervisor_python')})
        budget = {'roots':[str(self.root)],'max_bytes':512*1024*1024,'native_scope':scope}
        identity = dict(self.fixture.binding['host_identity'], task_id='fixture-owner', session_id='fixture-session',
                        process_generation=1, plugin_build='fixture-build', scene_epoch=0, version='21.0.631')
        self.config.update(controller_root=str(self.root), ledger_root=str(self.root/'artifact_ledger'),
            expected_identity=identity, native_scope=scope, resource_budget=budget, project_color=color,
            executable=str(executable), supervisor_executable=str(executable))
        self.state.rename(self.root/'host-state');self.state=self.root/'host-state'
        self.boundary = self.boundary_instance()
        self.registry = ArtifactRegistry(self.root/'artifact_ledger')
        self.boundary.bind_artifact_registry(self.registry)
        self.run = self.graph_run(self.boundary, self.registry)
        fact = self.verified()
        self.register(self.registry, fact)
        deployment = self.root/'production-hosts.json'
        deployment.write_text(json.dumps({'task_id':'fixture-owner','hosts':{'houdini':self.config}}))
        work = self.root/'nuke-host-fixture';work.mkdir()
        config = {'identity':{'task_id':'fixture-owner','launch_nonce':'fixture'},'task_root':str(self.root),
            'controller_root':str(self.root),'ledger_root':str(self.registry.root),'resource_budget':budget,
            'software_api':True,'evidence_source':'software_test','version':'17.0v1',
            'nuke_executable':str(executable),'supervisor_executable':str(executable)}
        launch = work/'launch.json';launch.write_text(json.dumps(config))
        environment = {'BRIDGE_NUKE_HOST_CONFIG':str(launch),
            'BRIDGE_NUKE_HOST_CONFIG_SHA256':hashlib.sha256(launch.read_bytes()).hexdigest()}
        binding = freeze_agent_inputs('fixture-owner',[{'role':'effect_render','path':fact['output_pattern'],
            'artifact_id':'software-controlled-beauty','frames':[dict(frame=1, **fact['frame_snapshots']['1'])]}])
        contract = registered_input_contract(binding,self.registry,task_id='fixture-owner')
        return environment, deployment, contract

    def test_nuke_host_and_fixed_worker_reopen_the_same_detached_source(self):
        from nuke_bridge import task_host, owned_render_worker
        from nuke_bridge.operation_receipts import validate_registered_input_contract
        environment, _, contract = self.nuke_consumer_fixture()
        result = self.root/'worker-result.json'
        inputs = self.root/'worker.inputs.json';inputs.write_text(json.dumps(contract))
        environment.update(BRIDGE_NUKE_INPUT_CONTRACT=str(inputs),BRIDGE_NUKE_RESULT_FILE=str(result),
            BRIDGE_NUKE_TASK_ID='worker',BRIDGE_NUKE_INPUT_CONTRACT_SHA256=hashlib.sha256(inputs.read_bytes()).hexdigest())
        with mock.patch.dict(os.environ,environment), \
             mock.patch('houdini_bridge.client.HoudiniClient.call',side_effect=AssertionError('no live H RPC')), \
             mock.patch('houdini_bridge.client.HoudiniClient.health',side_effect=AssertionError('no live H health')), \
             mock.patch('vfx_pipeline.production_hosts.ensure_hosts',side_effect=AssertionError('no host launch')):
            registry = task_host.controlled_artifact_registry(fallback=lambda operation:None,
                registry_root=contract['registry_root'],task_id='fixture-owner')
            entry = registry.lookup('software-controlled-beauty')
            self.assertEqual(entry['output_verification']['evidence_source'],'software_test')
            self.assertTrue(registry.verify('software-controlled-beauty')['usable'])
            self.assertEqual(validate_registered_input_contract(contract),contract)
            self.assertEqual(owned_render_worker._input_contract(),contract)
            with self.assertRaises(ArtifactError):registry._operation_facts('unknown',task_id='fixture-owner',frames=[1],pattern='unknown')
            # A worker must reauthenticate the original alpha, even when its
            # frozen contract and registered EXR bytes have not changed.
            Path(self.terminal['sources']['houdini_raw']['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
                owned_render_worker._input_contract()

    def test_nuke_controlled_source_rejects_foreign_scope_and_source(self):
        from nuke_bridge.task_host import controlled_artifact_registry
        environment, deployment, contract = self.nuke_consumer_fixture()
        original = deployment.read_bytes()
        with mock.patch.dict(os.environ,environment):
            for field, value in (('native_scope',{'path':str(self.root/'foreign.json'),'sha256':'f'*64}),
                                 ('evidence_source','real_host'),('ledger_root',str(self.root/'foreign-ledger'))):
                changed=json.loads(original);changed['hosts']['houdini'][field]=value
                deployment.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError,'DEPLOYMENT_BINDING_MISMATCH'):
                    controlled_artifact_registry(registry_root=contract['registry_root'],task_id='fixture-owner')
            deployment.write_bytes(original)
            with self.assertRaisesRegex(ValueError,'HOST_BINDING_MISMATCH'):
                controlled_artifact_registry(registry_root=self.root/'foreign-ledger',task_id='fixture-owner')
            with self.assertRaisesRegex(ValueError,'HOST_BINDING_MISMATCH'):
                controlled_artifact_registry(registry_root=contract['registry_root'],task_id='foreign-task')
            changed=json.loads(original);changed['hosts']={};deployment.write_text(json.dumps(changed))
            self.assertIsNone(controlled_artifact_registry(registry_root=contract['registry_root'],task_id='fixture-owner'))
            from nuke_bridge.operation_receipts import validate_registered_input_contract
            with self.assertRaisesRegex(ValueError,'controlled producer deployment unavailable'):
                validate_registered_input_contract(contract)

    def test_detached_persistent_verification_typed_ledger_and_restart_retry(self):
        original = self.fixture.anchor_path.read_bytes()
        fact = self.verified()
        self.assertEqual(fact['evidence_source'], 'software_test')
        self.assertEqual(self.run._lookup_operation('verify-software')['kind'], 'houdini-output-verification')
        first = self.register(self.registry, fact)
        provenance = first['output_verification']
        self.assertEqual(provenance['verification_basis'], 'controlled_output_v1')
        self.assertEqual(provenance['native_internal_status'], 'NOT_OBSERVED')
        self.assertEqual(provenance['origin_render_operation_id'], 'fixture-operation')
        self.assertEqual(provenance['origin_verification_operation_id'], 'verify-software')
        self.assertEqual(provenance['evidence_source'], 'software_test')
        self.assertTrue(self.registry.verify('software-controlled-beauty')['usable'])
        restarted = self.boundary_instance()
        registry = ArtifactRegistry(self.root / 'ledger')
        restarted.bind_artifact_registry(registry)
        resumed = self.graph_run(restarted, registry)
        self.assertEqual(resumed.operation_query('verify-software')['execution_fact'], fact)
        self.assertEqual(resumed.verify_render_output('verify-software', 'fixture-operation')['execution_fact'], fact)
        second = self.register(registry, fact)
        self.assertEqual(second['version'], first['version'] + 1)
        self.assertEqual(second['output_verification'], provenance)
        self.assertTrue(registry.verify('software-controlled-beauty')['usable'])
        self.assertEqual(self.fixture.anchor_path.read_bytes(), original)
        self.assertEqual(self.fixture.read()['execution_fact']['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        for boundary in (self.boundary, restarted):
            boundary._verify_identity.assert_not_called()
            boundary._transport.health.assert_not_called()
            boundary._transport.call.assert_not_called()

    def test_source_drift_refuses_query_and_new_ledger_commit(self):
        fact = self.verified()
        first = self.register(self.registry, fact)
        Path(self.terminal['sources']['houdini_raw']['path']).write_text('{}')
        restarted = self.boundary_instance()
        with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
            restarted.call('output.verify.status', {'verification_id': 'verify-software'})
        registry = ArtifactRegistry(self.root / 'ledger')
        restarted.bind_artifact_registry(registry)
        with self.assertRaises(Exception):
            self.register(registry, fact)
        with self.assertRaises(ArtifactError):
            registry.lookup('software-controlled-beauty')
        self.assertEqual([entry['version'] for entry in registry.history('software-controlled-beauty')], [first['version']])

    def test_forged_caller_facts_and_rehashed_cached_result_are_refused(self):
        fact = self.verified()
        with self.assertRaisesRegex(ProductionBoundaryError, 'CALLER_FACTS_FORBIDDEN'):
            self.boundary.call('output.verify', {'operation_id': 'fixture-operation',
                'verification_id': 'verify-software', 'alpha_calibration': {'associated': True}})
        with self.assertRaisesRegex(ArtifactError, 'CALLER_PROVENANCE_FORBIDDEN'):
            self.register(self.registry, fact, payload={'output_verification': {'verification_basis': 'controlled_output_v1'}})
        result = self.state / 'verified-output-verify-software.json'
        forged = copy.deepcopy(fact)
        forged['metadata']['1']['premultiplied'] = False
        forged['operation_receipt_sha256'] = client.render_receipt_digest(forged)
        result.write_text(json.dumps(forged))
        with self.assertRaisesRegex(ProductionBoundaryError, 'VERIFICATION_CHANGED'):
            self.boundary_instance().call('output.verify.status', {'verification_id': 'verify-software'})
        self.assertIsNone(self.registry.lookup('software-controlled-beauty'))


if __name__ == '__main__':
    unittest.main()
