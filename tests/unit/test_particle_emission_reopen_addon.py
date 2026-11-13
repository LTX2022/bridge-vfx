"""Actual P01 addon HIP recovery with persisted bottom HOM clocks, no DCC proof."""
import copy
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_particle_emission_program as program
from houdini_bridge import native_particle_emission_host as runtime
import test_particle_emission_addon as support
import test_native_particle_emission_host as bottom


CHECKPOINT_KEY = 'particle_emission_checkpoint'
CLOCK_STATE_KEY = 'bridge_test_native_particle_clock_snapshot_v1'
OPERATION_ID = 'p01-unit-reopen'


class Fixture(support.Fixture):
    def __enter__(self):
        try:
            return self._enter_native()
        except BaseException:
            self.stack.close()
            raise

    def _enter_native(self):
        super().__enter__()
        simulation = self.hou.node(self.roles['simulation'])
        initial = {name: simulation.parm(name) for name in ('native_offset', 'native_scale')}
        clocks = {simulation.sessionId(): initial}
        node_class = type(simulation)
        original_parm = node_class.parm
        original_templates = node_class.parmTemplateGroup

        def clock_parameters(node):
            if node.sessionId() not in clocks:
                saved = json.loads(node.userData(CLOCK_STATE_KEY))
                parameters = {}
                for name, state in saved.items():
                    owner = SimpleNamespace(path=node.path,
                        fixture=SimpleNamespace(hou=self.hou, write_calls=[]))
                    parameter = bottom.NativeParameter(owner, name, state['value'])
                    for field, value in state.items():
                        setattr(parameter, field, copy.deepcopy(value))
                    parameter.parmTemplate = initial[name].parmTemplate
                    parameters[name] = parameter
                clocks[node.sessionId()] = parameters
            return clocks[node.sessionId()]

        def native_parm(node, name):
            if node.path() == self.roles['simulation'] and name in initial:
                return clock_parameters(node)[name]
            return original_parm(node, name)

        def native_templates(node):
            if node.path() == self.roles['simulation']:
                return SimpleNamespace(entries=lambda: tuple(
                    parameter.parmTemplate() for parameter in clock_parameters(node).values()))
            return original_templates(node)

        self.stack.enter_context(patch.object(node_class, 'parm', native_parm))
        self.stack.enter_context(patch.object(node_class, 'parmTemplateGroup', native_templates))
        self.reopen_writes = []
        loaded = []
        parameter_class = type(self.parameter)
        for method_name in ('set', 'setExpression', 'deleteAllKeyframes', 'setKeyframes', 'setKeyframeExtrapolation'):
            original_method = getattr(parameter_class, method_name)

            def native_write(parameter, *args, original=original_method, method=method_name, **kwargs):
                if loaded and parameter.path().rsplit('/', 1)[0] in {
                        self.roles['emission'], self.roles['solver'], self.roles['simulation']}:
                    self.reopen_writes.append((method, parameter.path()))
                return original(parameter, *args, **kwargs)

            self.stack.enter_context(patch.object(parameter_class, method_name, native_write))
        original_save = self.hou.hipFile.save
        original_load = self.hou.hipFile.load

        def save_native_clock(*args, **kwargs):
            node = self.hou.node(self.roles['simulation'])
            state = {name: {field: copy.deepcopy(getattr(parameter, field)) for field in
                ('value', 'kind', 'label', 'size', 'source', 'language', 'keys', 'extrapolation',
                 'reference', 'locked', 'disabled', 'hidden', 'native_minimum', 'native_maximum',
                 'minimum_strict', 'maximum_strict')}
                for name, parameter in clock_parameters(node).items()}
            node.setUserData(CLOCK_STATE_KEY, json.dumps(state, sort_keys=True))
            return original_save(*args, **kwargs)

        def load_native_clock(*args, **kwargs):
            result = original_load(*args, **kwargs)
            self.root = self.hou.node(self.root.path())
            self.parameter = self.hou.node(self.roles['emission']).parm('constantrate')
            clock_parameters(self.hou.node(self.roles['simulation']))
            loaded.append(True)
            return result

        self.stack.enter_context(patch.object(self.hou.hipFile, 'save', save_native_clock))
        self.stack.enter_context(patch.object(self.hou.hipFile, 'load', load_native_clock))
        self.apply({'emission_variance': 45., 'birth_rate': 2300.})
        return self

    def save(self):
        path = self.directory / '保存 P01 scene with space.hip'
        receipt = self.client.call('scene.save_hip', {'task_id': self.task, 'path': str(path)})
        return path, receipt

    def discard_authority(self):
        for name in ('snapshots', 'builds', 'reopens'):
            if self.host.authority[name]:
                raise AssertionError('unexpected active private transaction: ' + name)
        self.host.authority['records'].clear()

    def reopen(self, path):
        return self.client.call('scene.reopen_task_hip', {
            'task_id': self.task, 'path': str(path),
            'operation_id': OPERATION_ID, 'request_id': OPERATION_ID,
            'scene_before_identity': self.addon._host_identity()})

    def corrupt_saved_contract(self, mutate, *, update_digest=True):
        path = self.addon._fx_task_saves_path(self.task)
        store = json.loads(path.read_text(encoding='utf-8'))
        receipt = store['saves'][-1]
        mutate(receipt['scene_contract'])
        if update_digest:
            receipt['scene_contract_sha256'] = self.addon._fx_scene_contract_digest(receipt['scene_contract'])
        path.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')


class ParticleEmissionReopenAddonTests(unittest.TestCase):
    def assert_no_authority(self, fixture):
        for name in ('records', 'snapshots', 'builds', 'reopens'):
            self.assertEqual(fixture.host.authority[name], {}, name)
        for name in ('_FX_PARTICLE_EMISSION_REOPEN_SCOPES', '_FX_RBD_REOPEN_SCOPES',
                     '_FX_GEOMETRY_REOPEN_SCOPES'):
            self.assertEqual(fixture.addon.__dict__.get(name, {}), {}, name)
        with self.assertRaises((fixture.addon.BridgeCommandError, ValueError)):
            fixture.host.readback(fixture.roles, fixture.pack)

    def assert_intent(self, fixture):
        transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions'][OPERATION_ID]
        self.assertEqual(transition['state'], 'INTENT')
        self.assertNotIn('after_identity', transition)
        self.assertEqual(transition['operation_receipt_sha256'],
                         fixture.addon._fx_scene_transition_digest(transition))
        return transition

    def assert_refused_reopen(self, fixture, path):
        fixture.discard_authority()
        with self.assertRaises((fixture.addon.BridgeCommandError, ValueError)) as caught:
            fixture.reopen(path)
        self.assertTrue(getattr(caught.exception, 'code', ''), str(caught.exception))
        self.assert_no_authority(fixture)
        return caught.exception

    def test_graph_checkpoint_requires_actual_registered_save_without_issuing_authority(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, receipt = fixture.save()
                manifest = copy.deepcopy(fixture.addon._fx_manifest(fixture.task)[1])
                manifest['graph_hash'] = receipt['scene_contract']['graph_hash']
                embedded = copy.deepcopy(manifest)
                checkpoint = receipt['scene_contract'][CHECKPOINT_KEY]
                self.assertEqual(embedded[CHECKPOINT_KEY], checkpoint)
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                channel = copy.deepcopy(fixture.parameter._native_state)
                fixture.discard_authority()
                actual = fixture.addon._fx_particle_emission_graph_checkpoint(
                    fixture.task, manifest, embedded, path.resolve(), receipt['sha256'])
                self.assertEqual(actual, checkpoint)
                self.assert_no_authority(fixture)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                for fault in ('missing_receipt', 'rehashed_different_checkpoint'):
                    with self.subTest(fault=fault):
                        saved_path.write_bytes(saved_bytes)
                        store = json.loads(saved_bytes)
                        if fault == 'missing_receipt':
                            store['saves'] = []
                        else:
                            saved = store['saves'][-1]
                            saved['scene_contract'][CHECKPOINT_KEY]['percentage'] = 60.
                            saved['scene_contract_sha256'] = fixture.addon._fx_scene_contract_digest(
                                saved['scene_contract'])
                            self.assertNotEqual(saved['scene_contract'][CHECKPOINT_KEY], embedded[CHECKPOINT_KEY])
                        saved_path.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')
                        with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                            fixture.addon._fx_particle_emission_graph_checkpoint(
                                fixture.task, manifest, embedded, path.resolve(), receipt['sha256'])
                        self.assertEqual(refused.exception.code, 'PARTICLE_EMISSION_REOPEN_AUTHORITY_REQUIRED')
                        self.assert_no_authority(fixture)
                        self.assertEqual(fixture.parameter._native_state, channel)
                saved_path.write_bytes(saved_bytes)

    def test_actual_save_load_rebinds_new_native_nodes_without_reapply(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                before = fixture.host.checkpoint(fixture.roles, fixture.pack)
                original_node = fixture.hou.node(fixture.roles['emission'])
                original_session = original_node.sessionId()
                original_identity = fixture.addon._host_identity()
                channel = copy.deepcopy(fixture.parameter._native_state)
                path, receipt = fixture.save()
                self.assertEqual(receipt['scene_contract'][CHECKPOINT_KEY], before)
                self.assertEqual(receipt['sha256'], fixture.addon._fx_sha256_file(path))
                self.assertEqual(receipt['scene_contract_sha256'],
                    fixture.addon._fx_scene_contract_digest(receipt['scene_contract']))
                fixture.discard_authority()
                result = fixture.reopen(path)
                self.assertIs(result['particle_emission_restored'], True)
                self.assertTrue(result['parameters_verified'])
                self.assertTrue(result['connections_verified'])
                node = fixture.hou.node(fixture.roles['emission'])
                self.assertIsNot(node, original_node)
                self.assertNotEqual(node.sessionId(), original_session)
                self.assertGreater(fixture.addon._host_identity()['scene_epoch'], original_identity['scene_epoch'])
                self.assertEqual(fixture.parameter._native_state, channel)
                self.assertEqual(fixture.reopen_writes, [])
                after = fixture.host.checkpoint(fixture.roles, fixture.pack)
                self.assertEqual({name: value for name, value in before.items() if name != 'identity'},
                                 {name: value for name, value in after.items() if name != 'identity'})
                readback = fixture.host.readback(fixture.roles, fixture.pack)
                self.assertEqual((readback['percentage'], readback['birth_rate']), (45., 2300.))
                self.assertEqual(readback['status'], 'BLOCKED')
                self.assertEqual(readback['evidence_scope'], 'native_parameter_expression_only')
                self.assertIs(readback['checkpoint_reopen']['native_writes'], False)
                self.assertIs(readback['checkpoint_reopen']['new_pid_and_nonce'], False)
                self.assertIn('verified_new_PID_checkpoint_reopen', readback['missing_evidence'])
                self.assertEqual(fixture.host.authority['reopens'], {})
                self.assertEqual(fixture.addon._FX_PARTICLE_EMISSION_REOPEN_SCOPES, {})

    def test_public_collect_reads_restored_controls_and_restores_frame(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                fixture.discard_authority()
                fixture.reopen(path)
                fixture.hou.setFrame(-6.5)
                original_frame = fixture.hou.frame()
                result = fixture.client.call('agent.fx.collect_evidence', fixture.params)
                readbacks = result['evidence']['native_geometry_readback']
                self.assertEqual(set(readbacks), {'1', '2'})
                for readback in readbacks.values():
                    self.assertEqual((readback['percentage'], readback['birth_rate']), (45., 2300.))
                    self.assertEqual(readback['status'], 'BLOCKED')
                    self.assertEqual(readback['evidence_scope'], 'native_parameter_expression_only')
                self.assertEqual(fixture.hou.frame(), original_frame)
                self.assertEqual(fixture.host.authority['snapshots'], {})

    def test_missing_checkpoint_refuses_even_when_saved_contract_is_rehashed(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                fixture.corrupt_saved_contract(lambda contract: contract.pop(CHECKPOINT_KEY))
                error = self.assert_refused_reopen(fixture, path)
                self.assertEqual(error.code, 'PARTICLE_EMISSION_REOPEN_CHECKPOINT_REQUIRED')

    def test_checkpoint_expression_basis_or_hash_tampering_cannot_grant_authority(self):
        mutations = {
            'expression': lambda checkpoint: checkpoint.update(expression=checkpoint['expression'] + '\nreturn 0.'),
            'basis_hash': lambda checkpoint: checkpoint['basis'].update(content_sha256='0' * 64),
            'basis_seed': lambda checkpoint: checkpoint['basis'].update(task_seed=174),
            'percentage': lambda checkpoint: checkpoint.update(percentage=60.),
        }
        for version in program.SUPPORTED_VERSIONS:
            for name, mutation in mutations.items():
                with self.subTest(version=version, mutation=name), Fixture(version) as fixture:
                    path, _ = fixture.save()
                    fixture.corrupt_saved_contract(lambda contract: mutation(contract[CHECKPOINT_KEY]))
                    self.assert_refused_reopen(fixture, path)

    def test_wrong_saved_contract_digest_refuses_before_registration(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                fixture.corrupt_saved_contract(lambda contract: contract[CHECKPOINT_KEY].update(percentage=60.),
                                              update_digest=False)
                error = self.assert_refused_reopen(fixture, path)
                self.assertEqual(error.code, 'ARTIFACT_CONTRACT_INVALID')

    def test_zero_variance_rehashed_saved_seed_cannot_replace_loaded_hip_checkpoint(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.apply({'emission_variance': 0.})
                path, receipt = fixture.save()
                original = receipt['scene_contract'][CHECKPOINT_KEY]
                self.assertEqual(original['percentage'], 0.)
                self.assertIsNone(original['expression'])
                self.assertEqual(original['basis']['task_seed'], 173)

                def change_seed(contract):
                    basis = contract[CHECKPOINT_KEY]['basis']
                    contract[CHECKPOINT_KEY]['basis'] = program.freeze_basis(
                        basis['native_version'], task_seed=174, **{name: basis[name] for name in
                            ('task_id', 'task_root', 'node_path', 'birth_rate', 'birth_start_time', 'fps')})

                fixture.corrupt_saved_contract(change_seed)
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                corrupted_bytes = saved_path.read_bytes()
                saved = json.loads(corrupted_bytes)['saves'][-1]
                changed = saved['scene_contract'][CHECKPOINT_KEY]
                self.assertEqual(program.validate_basis(changed['basis'])['task_seed'], 174)
                self.assertNotEqual(changed['basis']['content_sha256'], original['basis']['content_sha256'])
                self.assertIsNone(changed['expression'])
                self.assertEqual(saved['scene_contract_sha256'],
                                 fixture.addon._fx_scene_contract_digest(saved['scene_contract']))
                self.assertEqual(fixture.addon._fx_sha256_file(path), receipt['sha256'])
                error = self.assert_refused_reopen(fixture, path)
                self.assertEqual(error.code, 'PARTICLE_EMISSION_REOPEN_CHECKPOINT_REQUIRED')
                self.assert_intent(fixture)
                self.assertEqual(saved_path.read_bytes(), corrupted_bytes)
                self.assertEqual(fixture.reopen_writes, [])

    def test_terminal_native_node_read_gate_drift_refuses_and_restores_intent(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                fixture.discard_authority()
                original_end = runtime.Host.end
                original_checkpoint = runtime.Host.checkpoint
                node_class = type(fixture.root)
                original_bypassed = node_class.isBypassed
                active, checkpoints, node_reads, mutations = [], [], [], []

                def observe_end(host, token, commit):
                    if commit:
                        active.append(True)
                    try:
                        return original_end(host, token, commit)
                    finally:
                        active.clear()

                def observe_checkpoint(host, roles, pack):
                    if active:
                        checkpoints.append(True)
                    return original_checkpoint(host, roles, pack)

                def read_bypassed(node):
                    if active and len(checkpoints) == 4 and node.path() == fixture.roles['solver']:
                        node_reads.append(True)
                        if len(node_reads) == 6:
                            fixture.hou.node(fixture.roles['emission']).parm('constantactivate').set(0.)
                            mutations.append('terminal native solver flag read changed birth gate')
                    return original_bypassed(node)

                with patch.object(runtime.Host, 'end', observe_end), \
                        patch.object(runtime.Host, 'checkpoint', observe_checkpoint), \
                        patch.object(node_class, 'isBypassed', read_bypassed):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.reopen(path)
                self.assertEqual(refused.exception.code, 'PARTICLE_EMISSION_GATE_CHANGED')
                self.assertEqual(len(checkpoints), 4)
                self.assertEqual(len(node_reads), 6)
                self.assertEqual(mutations, ['terminal native solver flag read changed birth gate'])
                self.assertEqual(fixture.hou.node(fixture.roles['emission']).parm('constantactivate').eval(), 0.)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_intent(fixture)
                self.assert_no_authority(fixture)

    def test_reconcile_final_native_parameter_read_gate_drift_is_refused(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, receipt = fixture.save()
                request = dict(path=str(path), sha256=receipt['sha256'])
                self.assertIs(fixture.addon._fx_particle_emission_reconcile_checkpoint(
                    fixture.task, request, 'scene.reopen_task_hip'), True)
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                target = next(fixture.hou.node(record['path']).parms()[-1]
                    for record in reversed(receipt['scene_contract']['nodes'])
                    if fixture.hou.node(record['path']).parms())
                target_path = target.path()
                self.assertEqual(target_path, fixture.roles['source'] + '/rz')
                parameter_class = type(target)
                original_eval = parameter_class.eval
                original_verify = fixture.addon._fx_verify_scene_contract
                active, mutations, verifications = [], [], []

                def observe_verify(*args, **kwargs):
                    active.append(True)
                    verifications.append(True)
                    try:
                        return original_verify(*args, **kwargs)
                    finally:
                        active.clear()

                def evaluate(parameter):
                    result = original_eval(parameter)
                    if active and not mutations and parameter.path() == target_path:
                        fixture.hou.node(fixture.roles['emission']).parm('constantactivate').set(0.)
                        mutations.append(target_path)
                    return result

                with patch.object(fixture.addon, '_fx_verify_scene_contract', observe_verify), \
                        patch.object(parameter_class, 'eval', evaluate):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.addon._fx_particle_emission_reconcile_checkpoint(
                            fixture.task, request, 'scene.reopen_task_hip')
                self.assertEqual(refused.exception.code, 'PARTICLE_EMISSION_GATE_CHANGED')
                self.assertEqual(verifications, [True])
                self.assertEqual(mutations, [target_path])
                self.assertEqual(fixture.hou.node(fixture.roles['emission']).parm('constantactivate').eval(), 0.)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assertEqual(fixture.addon._fx_sha256_file(path), receipt['sha256'])
                for name in ('snapshots', 'builds', 'reopens'):
                    self.assertEqual(fixture.host.authority[name], {}, name)
                self.assertEqual(fixture.addon.__dict__.get('_FX_PARTICLE_EMISSION_REOPEN_SCOPES', {}), {})
                with self.assertRaises(ValueError) as readback_refused:
                    fixture.host.readback(fixture.roles, fixture.pack)
                self.assertEqual(readback_refused.exception.code, 'PARTICLE_EMISSION_GATE_CHANGED')

    def test_completion_save_then_exception_restores_exact_intent_and_no_authority(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                fixture.discard_authority()
                runner = fixture.addon.fx_operation_runner(fixture.task)
                original_save = runner._save
                intents, failures = [], []

                def save_then_fail(store):
                    transition = store.get('scene_transitions', {}).get(OPERATION_ID)
                    if transition and transition['state'] == 'INTENT' and not failures:
                        intents.append(copy.deepcopy(transition))
                    result = original_save(store)
                    if transition and transition['state'] == 'COMPLETED' and not failures:
                        failures.append(True)
                        raise OSError('explicit disk failure after completion write')
                    return result

                with patch.object(runner, '_save', save_then_fail):
                    with self.assertRaisesRegex(OSError, 'after completion write'):
                        fixture.reopen(path)
                self.assertEqual(failures, [True])
                self.assertTrue(intents)
                restored = self.assert_intent(fixture)
                self.assertGreater(restored['store_cas'], intents[-1]['store_cas'])
                expected = dict(intents[-1], store_cas=restored['store_cas'])
                expected['operation_receipt_sha256'] = fixture.addon._fx_scene_transition_digest(expected)
                self.assertEqual(restored, expected)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_no_authority(fixture)

    def test_final_gate_or_artifact_identity_drift_revokes_completion(self):
        for version in program.SUPPORTED_VERSIONS:
            for kind in ('gate', 'hip', 'identity'):
                with self.subTest(version=version, fault=kind), Fixture(version) as fixture:
                    path, _ = fixture.save()
                    saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                    saved_bytes = saved_path.read_bytes()
                    fixture.discard_authority()
                    original_complete = fixture.addon._fx_scene_transition_complete
                    events = []

                    def complete_then_drift(*args, **kwargs):
                        result = original_complete(*args, **kwargs)
                        if kind == 'gate':
                            fixture.hou.node(fixture.roles['emission']).parm('constantactivate').set(0.)
                        elif kind == 'hip':
                            loaded = Path(fixture.hou.hipFile.path())
                            loaded.chmod(loaded.stat().st_mode | stat.S_IWRITE)
                            loaded.write_bytes(loaded.read_bytes() + b'\nexplicit final HIP drift\n')
                        else:
                            fixture.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'explicit-final-identity-drift'
                        events.append(kind)
                        return result

                    with patch.object(fixture.addon, '_fx_scene_transition_complete', complete_then_drift):
                        with self.assertRaises((fixture.addon.BridgeCommandError, ValueError)):
                            fixture.reopen(path)
                    self.assertEqual(events, [kind])
                    self.assertEqual(saved_path.read_bytes(), saved_bytes)
                    self.assert_intent(fixture)
                    self.assert_no_authority(fixture)


if __name__ == '__main__':
    unittest.main(verbosity=2)
