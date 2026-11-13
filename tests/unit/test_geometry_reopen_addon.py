"""Actual addon save/reopen with bottom HOM only; no process/VEX proof."""
import json
import os
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_host as adapter
from houdini_bridge import native_geometry_controls_program as program
from houdini_bridge import native_geometry_runtime_registry as runtime
import test_native_geometry_addon_wiring as wiring


CHECKPOINT_KEY = 'geometry_registry_checkpoint'
CHECKPOINT_SCHEMA = 'bridge.geometry-registry-checkpoint/1'


class GeometryReopenAddonTests(unittest.TestCase):
    def registered_roles(self, fixture):
        return {item['role']: fixture.roles[item['role']] for item in fixture.pack['nodes']}

    def save_selected(self, fixture):
        fixture.hou.expandString = lambda value: value
        fixture.hou.isUIAvailable = lambda: False
        fixture.build()
        fixture.apply({'deformation': .3})
        observed = fixture.addon._fx_geometry_host().observations(self.registered_roles(fixture), fixture.pack)
        self.assertEqual(program.control_readback(fixture.version, observed['context'],
                                                observed['parameters'])['value'], .3)
        path = fixture.directory / '保存场景 with space.hip'
        receipt = fixture.client.call('scene.save_hip', {'task_id': fixture.task, 'path': str(path)})
        self.assertEqual(receipt['sha256'], fixture.addon._fx_sha256_file(path))
        self.assertTrue(receipt['scene_contract'])
        self.assertEqual(receipt['scene_contract_sha256'],
                         fixture.addon._fx_scene_contract_digest(receipt['scene_contract']))
        return path, receipt, observed

    def discard_old_process_registry(self, fixture):
        self.assertFalse(any(item['entry']['host'] is fixture.addon.__dict__
                             for item in runtime._TRANSACTIONS.values()))
        for token, entry in list(runtime._COHORTS.items()):
            if entry['host'] is fixture.addon.__dict__:
                runtime._COHORTS.pop(token)

    def reopen(self, fixture, path):
        return fixture.client.call('scene.reopen_task_hip', {
            'task_id': fixture.task, 'path': str(path),
            'operation_id': 'g03-checkpoint-reopen', 'request_id': 'g03-checkpoint-reopen',
            'scene_before_identity': fixture.addon._host_identity()})

    def manifest(self, fixture):
        return json.loads(fixture.hou.node(fixture.root).userData('bridge_fx_manifest_v1'))

    def corrupt_saved_contract(self, fixture, mutate, *, update_digest):
        store_path = fixture.addon._fx_task_saves_path(fixture.task)
        store = json.loads(store_path.read_text(encoding='utf-8'))
        receipt = store['saves'][-1]
        mutate(receipt['scene_contract'])
        if update_digest:
            receipt['scene_contract_sha256'] = fixture.addon._fx_scene_contract_digest(receipt['scene_contract'])
        store_path.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')

    def assert_no_current_authority(self, fixture):
        self.assertEqual(fixture.addon.__dict__.get('_FX_GEOMETRY_REOPEN_SCOPES', {}), {})
        self.assertFalse(any(item['entry']['host'] is fixture.addon.__dict__
                             for item in runtime._TRANSACTIONS.values()))
        for entry in runtime._COHORTS.values():
            if entry['host'] is not fixture.addon.__dict__:
                continue
            identity_matches = entry['binding']['host_identity'] == fixture.addon._host_identity()
            nodes_match = all(fixture.hou.node(fixture.roles[role]) is entry['nodes'][role][0]
                              for role in self.registered_roles(fixture))
            self.assertFalse(identity_matches and nodes_match and entry['committed'])
        with self.assertRaises((fixture.addon.BridgeCommandError, program.GeometryControlsError)):
            fixture.addon._fx_geometry_host().observations(self.registered_roles(fixture), fixture.pack)
        self.assertEqual(adapter._SNAPSHOTS, {})

    def assert_refused_reopen(self, fixture, path):
        self.discard_old_process_registry(fixture)
        with self.assertRaises((fixture.addon.BridgeCommandError, program.GeometryControlsError)) as caught:
            self.reopen(fixture, path)
        self.assertTrue(getattr(caught.exception, 'code', ''), str(caught.exception))
        self.assert_no_current_authority(fixture)

    def test_baseline_userdata_without_reopen_cannot_restore_authority(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                _, _, observed = self.save_selected(fixture)
                before = fixture.carrier.parm('snippet').eval()
                self.discard_old_process_registry(fixture)
                self.assert_no_current_authority(fixture)
                self.assertEqual(fixture.carrier.parm('snippet').eval(), before)
                self.assertEqual(json.loads(fixture.carrier.userData(adapter.BASIS_KEY)),
                                 observed['context']['basis'])

    def test_save_and_reopen_rebinds_fresh_nodes_without_reapplying_selected_value(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, receipt, before = self.save_selected(fixture)
                original_node = fixture.carrier
                original_session = original_node.sessionId()
                original_identity = fixture.addon._host_identity()
                checkpoint = self.manifest(fixture)[CHECKPOINT_KEY]
                self.assertEqual(checkpoint['schema'], CHECKPOINT_SCHEMA)
                self.assertEqual(checkpoint['manifest'], fixture.input_manifest)
                self.assertEqual(checkpoint['roles'], self.registered_roles(fixture))
                self.assertEqual(checkpoint['pack_sha256'], program._hash(fixture.pack))
                self.assertEqual(checkpoint['binding'], before['binding'])
                self.assertEqual(checkpoint['basis'], before['context']['basis'])
                self.assertEqual(checkpoint['record'], before['context']['initialization'])
                self.assertTrue(checkpoint['parameters'])
                self.assertEqual(receipt['scene_contract'][CHECKPOINT_KEY], checkpoint)
                self.discard_old_process_registry(fixture)
                result = self.reopen(fixture, path)
                self.assertIs(result['geometry_registry_restored'], True)
                self.assertTrue(result['nodes_verified'])
                self.assertTrue(result['parameters_verified'])
                self.assertTrue(result['connections_verified'])
                self.assertIn(fixture.root, result['leases_transferred'])
                carrier = fixture.hou.node(fixture.roles[program.ROLE])
                self.assertIsNot(carrier, original_node)
                self.assertNotEqual(carrier.sessionId(), original_session)
                self.assertEqual(carrier.parm('snippet').eval(), before['parameters'][program.ROLE, 'snippet']['value'])
                self.assertEqual(carrier.userData(adapter.BASIS_KEY), original_node.userData(adapter.BASIS_KEY))
                self.assertEqual(carrier.userData(adapter.REGISTRATION_KEY),
                                 original_node.userData(adapter.REGISTRATION_KEY))
                actual = fixture.addon._fx_geometry_host().observations(self.registered_roles(fixture), fixture.pack)
                self.assertEqual(actual['parameters'], before['parameters'])
                self.assertEqual(actual['context']['basis'], before['context']['basis'])
                self.assertEqual(actual['context']['initialization'], before['context']['initialization'])
                self.assertEqual(actual['binding']['host_identity'], fixture.addon._host_identity())
                self.assertGreater(actual['binding']['host_identity']['scene_epoch'], original_identity['scene_epoch'])
                self.assertEqual(actual['binding']['host_identity']['pid'], os.getpid())
                readback = program.control_readback(version, actual['context'], actual['parameters'])
                self.assertEqual(readback['value'], .3)
                self.assertEqual(readback['status'], 'BLOCKED')
                self.assertEqual(readback['evidence_scope'], 'parameters_only')
                self.assertTrue(readback['missing_evidence'])
                self.assertEqual(adapter._SNAPSHOTS, {})

    def test_forged_checkpoint_record_in_saved_contract_does_not_authorize_reopen(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                def corrupt_record(contract):
                    contract[CHECKPOINT_KEY]['record']['basis_sha256'] = '0' * 64

                self.corrupt_saved_contract(fixture, corrupt_record, update_digest=True)
                self.assert_refused_reopen(fixture, path)

    def test_loaded_program_corruption_does_not_authorize_reopen(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                original_load = fixture.hou.hipFile.load

                def load_corrupted_program(*args, **kwargs):
                    result = original_load(*args, **kwargs)
                    snippet = fixture.hou.node(fixture.roles[program.ROLE]).parm('snippet')
                    snippet.set(snippet.eval() + '\n@P += set(1, 0, 0);')
                    return result

                with patch.object(fixture.hou.hipFile, 'load', load_corrupted_program):
                    self.assert_refused_reopen(fixture, path)

    def test_rest_input_drift_does_not_leave_reopen_authority(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                before = fixture.input_path.read_bytes()
                changed = bytearray(before)
                changed[-1] ^= 1
                fixture.input_path.write_bytes(changed)
                self.assertEqual(fixture.input_path.stat().st_size, len(before))
                self.assert_refused_reopen(fixture, path)

    def test_saved_existing_carrier_without_checkpoint_is_not_adopted(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                self.corrupt_saved_contract(fixture, lambda contract: contract.pop(CHECKPOINT_KEY),
                                            update_digest=True)
                self.assert_refused_reopen(fixture, path)

    def test_node_session_drift_during_reopen_does_not_leave_authority(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                node_class = type(fixture.carrier)
                original_session = node_class.sessionId
                observed_sessions = []

                def changing_session(node):
                    value = original_session(node)
                    if node.path() == fixture.roles[program.ROLE]:
                        observed_sessions.append(value)
                        return value + 1000000 * len(observed_sessions)
                    return value

                with patch.object(node_class, 'sessionId', changing_session):
                    self.assert_refused_reopen(fixture, path)
                self.assertGreaterEqual(len(observed_sessions), 2)
                self.assert_no_current_authority(fixture)

    def test_contract_checkpoint_tamper_after_save_is_rejected_before_authority(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                def corrupt_pack(contract):
                    contract[CHECKPOINT_KEY]['pack_sha256'] = '0' * 64

                self.corrupt_saved_contract(fixture, corrupt_pack, update_digest=False)
                self.assert_refused_reopen(fixture, path)

    def test_completion_persistence_failure_rolls_back_authority_and_active_save(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                self.discard_old_process_registry(fixture)
                with patch.object(fixture.addon, '_fx_scene_transition_complete', side_effect=OSError('completion write failure')):
                    with self.assertRaises(OSError):
                        self.reopen(fixture, path)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_no_current_authority(fixture)
                transitions = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']
                self.assertEqual(transitions['g03-checkpoint-reopen']['state'], 'INTENT')

    def test_final_registration_failure_removes_completed_transition_and_active_save(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                self.discard_old_process_registry(fixture)
                original = runtime.Registry.end
                def refuse_commit(registry, token, commit):
                    if commit:
                        raise program.GeometryControlsError('GEOMETRY_CHECKPOINT_CHANGED', 'final commit failure')
                    return original(registry, token, commit)
                with patch.object(runtime.Registry, 'end', refuse_commit):
                    with self.assertRaises(fixture.addon.BridgeCommandError):
                        self.reopen(fixture, path)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_no_current_authority(fixture)
                runner = fixture.addon.fx_operation_runner(fixture.task)
                transition = runner._load()['scene_transitions']['g03-checkpoint-reopen']
                self.assertEqual(transition['state'], 'INTENT')
                self.assertNotIn('after_identity', transition)
                self.assertEqual(transition['operation_receipt_sha256'],
                                 fixture.addon._fx_scene_transition_digest(transition))

    def test_reconcile_cannot_complete_a_refused_geometry_reopen(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                fixture.input_path.write_bytes(fixture.input_path.read_bytes() + b' ')
                self.assert_refused_reopen(fixture, path)
                with self.assertRaises(fixture.addon.BridgeCommandError):
                    fixture.client.call('scene.reconcile_transition', {
                        'task_id': fixture.task, 'operation_id': 'g03-checkpoint-reopen'})
                transitions = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']
                self.assertEqual(transitions['g03-checkpoint-reopen']['state'], 'INTENT')
                self.assert_no_current_authority(fixture)

    def test_identity_drift_after_completion_removes_only_this_completed_fact(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                self.discard_old_process_registry(fixture)
                original = fixture.addon._fx_scene_transition_complete
                def complete_then_drift(*arguments, **keywords):
                    result = original(*arguments, **keywords)
                    fixture.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'after-completion-drift'
                    return result
                with patch.object(fixture.addon, '_fx_scene_transition_complete', complete_then_drift):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as caught:
                        self.reopen(fixture, path)
                self.assertEqual(caught.exception.code, 'SCENE_STATE_DRIFT')
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_no_current_authority(fixture)
                runner = fixture.addon.fx_operation_runner(fixture.task)
                transition = runner._load()['scene_transitions']['g03-checkpoint-reopen']
                self.assertEqual(transition['state'], 'INTENT')
                self.assertNotIn('after_identity', transition)
                self.assertEqual(transition['operation_receipt_sha256'], fixture.addon._fx_scene_transition_digest(transition))
                with self.assertRaises(fixture.addon.BridgeCommandError):
                    fixture.client.call('scene.reconcile_transition', {
                        'task_id': fixture.task, 'operation_id': 'g03-checkpoint-reopen'})

    def test_completion_written_then_raised_cannot_leave_success_or_authority(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                self.discard_old_process_registry(fixture)
                original = fixture.addon._fx_scene_transition_complete
                def complete_then_raise(*arguments, **keywords):
                    original(*arguments, **keywords)
                    raise OSError('failure after completion persistence')
                with patch.object(fixture.addon, '_fx_scene_transition_complete', complete_then_raise):
                    with self.assertRaises(OSError):
                        self.reopen(fixture, path)
                self.assert_no_current_authority(fixture)
                transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']['g03-checkpoint-reopen']
                self.assertEqual(transition['state'], 'INTENT')

    def test_missing_current_manifest_cannot_disable_saved_geometry_reconcile_requirement(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                path, _, _ = self.save_selected(fixture)
                fixture.input_path.write_bytes(fixture.input_path.read_bytes() + b' ')
                self.assert_refused_reopen(fixture, path)
                fixture.hou.node(fixture.root).destroyUserData('bridge_fx_manifest_v1')
                state_path = fixture.addon._fx_state_path(fixture.task)
                self.assertTrue(state_path.resolve().is_relative_to(fixture.directory.resolve()))
                state_path.unlink()
                with self.assertRaises(fixture.addon.BridgeCommandError) as caught:
                    fixture.client.call('scene.reconcile_transition', {
                        'task_id': fixture.task, 'operation_id': 'g03-checkpoint-reopen'})
                self.assertEqual(caught.exception.code, 'GEOMETRY_REOPEN_RECONCILIATION_UNPROVEN')
                transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']['g03-checkpoint-reopen']
                self.assertEqual(transition['state'], 'INTENT')
                self.assert_no_current_authority(fixture)


if __name__ == '__main__':
    unittest.main()
