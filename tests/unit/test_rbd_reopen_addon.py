"""Actual R05 addon save/reopen; fixed bottom HOM, no process or VEX proof."""
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from houdini_bridge import native_rbd_controls_host as adapter
from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_program as program
from test_native_geometry_addon_wiring import load_boundary
from test_native_rbd_controls_program import packed_geometry
from vfx_pipeline.workbuddy_assembly import software_host_client


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_KEY = 'rbd_velocity_checkpoint'


class Fixture:
    def __init__(self, version):
        self.version = version
        self.stack = ExitStack()

    def __enter__(self):
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {
            'HOUDINI_BRIDGE_STATE_DIR': str(self.directory / 'houdini'),
            'BRIDGE_SKILLS_STATE_ROOT': str(self.directory / 'state'),
            'BRIDGE_SKILLS_SCHEDULER_ROOT': str(self.directory / 'scheduler')}))
        self.stack.enter_context(patch.dict(sys.modules))
        self.client, self.addon = software_host_client(
            ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.directory / 'host')
        native = load_boundary('rbd_reopen_schema_boundary', 'native_schema_test_boundary.py')
        api = load_boundary('rbd_reopen_stage_boundary', 'software_render_api_boundary.py')
        interfaces, states, ports = api.interface_profiles(ROOT, self.version)
        states.setdefault('Sop/attribwrangle', {})['snippet'] = dict(
            origin='test_injected_native_api', value='', locked=False, disabled=False, hidden=False)
        native.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', self.version,
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        self.hou = sys.modules['hou']
        api.install_stage_api(self.hou)
        self.hou.expandString = lambda value: value
        self.hou.isUIAvailable = lambda: False
        node_class = type(self.hou.node('/obj'))
        original_input_geometry = node_class.inputGeometry

        def fixed_output(node, frame, output_index=0):
            if (node.type().name() != 'rbdconfigure' and node.name() != self.addon._fx_node_name('rbd_velocity')) or output_index != 0:
                raise ValueError('fixed packed source supports configure/carrier output zero only')
            return packed_geometry()

        def fixed_input(node, input_index):
            if node.type().name() != 'rbdbulletsolver' or input_index != 0:
                return original_input_geometry(node, input_index)
            connections = [connection for connection in node.inputConnections()
                           if connection.inputIndex() == input_index]
            if len(connections) != 1:
                raise ValueError('actual packed input unavailable')
            connection = connections[0]
            return connection.inputNode().geometryAtFrame(
                self.hou.frame(), output_index=connection.outputIndex())

        self.stack.enter_context(patch.object(node_class, 'geometryAtFrame', fixed_output, create=True))
        self.stack.enter_context(patch.object(node_class, 'inputGeometry', fixed_input))
        self.stack.enter_context(patch.object(node_class, 'isBypassed', lambda node: False, create=True))
        self.task = 'rbd-reopen-unit-task'
        identity = dict(task_id=self.task, version=self.version, pid=os.getpid(),
            launch_nonce='explicit-rbd-reopen-unit', session_id='rbd-unit-session',
            process_generation='rbd-unit-generation', plugin_build=hashlib.sha256(
                (ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py').read_bytes()).hexdigest())
        self.stack.enter_context(patch.object(self.addon, '_TASK_HOST_IDENTITY', identity, create=True))
        self.params = dict(task_id=self.task, constraints={'fx': {
            'domain_pack': 'rbd_destruction_v1', 'run_mode': 'diagnose', 'frames': [1, 2]}},
            render={'frame_range': {'start': 1, 'end': 2, 'step': 1}})
        built = self.client.call('agent.fx.build_preview', self.params)
        self.roles = built['scene_manifest']['nodes']
        self.pack = self.addon._fx_pack(self.params)[1]
        self.root = built['scene_manifest']['execution_root']
        self.client.call('node.set_parms', dict(path=self.roles['solver'], parms={'usescale': 0}))
        self.apply_zero()
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def carrier(self):
        return self.hou.node(self.roles[program.ROLE])

    def host(self):
        return self.addon._fx_rbd_velocity_host()

    def apply_zero(self):
        params = copy.deepcopy(self.params)
        params['constraints']['fx']['changes'] = {'velocity_variance': 0.}
        return self.client.call('agent.fx.apply_candidate', params)

    def manifest(self):
        return json.loads(self.hou.node(self.root).userData('bridge_fx_manifest_v1'))

    def save(self):
        path = self.directory / '保存 RBD scene with space.hip'
        receipt = self.client.call('scene.save_hip', {'task_id': self.task, 'path': str(path)})
        return path, receipt

    def discard_authority(self):
        if self.host().authority['transactions']:
            raise AssertionError('unexpected active transaction before simulated fresh host')
        self.host().authority['records'].clear()

    def reopen(self, path):
        return self.client.call('scene.reopen_task_hip', {
            'task_id': self.task, 'path': str(path),
            'operation_id': 'rbd-unit-reopen', 'request_id': 'rbd-unit-reopen',
            'scene_before_identity': self.addon._host_identity()})

    def corrupt_saved_contract(self, mutate, *, update_digest):
        path = self.addon._fx_task_saves_path(self.task)
        store = json.loads(path.read_text(encoding='utf-8'))
        receipt = store['saves'][-1]
        mutate(receipt['scene_contract'])
        if update_digest:
            receipt['scene_contract_sha256'] = self.addon._fx_scene_contract_digest(receipt['scene_contract'])
        path.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')


class RbdReopenAddonTests(unittest.TestCase):
    def assert_no_authority(self, fixture):
        self.assertEqual(fixture.addon.__dict__.get('_FX_RBD_REOPEN_SCOPES', {}), {})
        self.assertEqual(fixture.addon.__dict__.get('_FX_GEOMETRY_REOPEN_SCOPES', {}), {})
        self.assertEqual(fixture.host().authority['transactions'], {})
        self.assertEqual(fixture.host().authority['records'], {})
        with self.assertRaises((fixture.addon.BridgeCommandError, ValueError)):
            fixture.host().readback(fixture.roles, fixture.pack, {'velocity_variance': 0.})

    def assert_refused_reopen(self, fixture, path):
        fixture.discard_authority()
        with self.assertRaises((fixture.addon.BridgeCommandError, ValueError)) as caught:
            fixture.reopen(path)
        self.assertTrue(getattr(caught.exception, 'code', ''), str(caught.exception))
        self.assert_no_authority(fixture)
        return caught.exception

    def test_public_collect_reads_velocity_and_refuses_tampered_registration(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                fixture.discard_authority()
                fixture.reopen(path)
                original_frame = fixture.hou.frame()
                result = fixture.client.call('agent.fx.collect_evidence', fixture.params)
                readbacks = result['evidence']['native_geometry_readback']
                self.assertEqual(set(readbacks), {'1', '2'})
                for readback in readbacks.values():
                    self.assertEqual(readback['controls'], {'velocity_variance': 0.})
                    self.assertEqual(readback['native_simulation'], 'NOT_RUN')
                self.assertEqual(fixture.hou.frame(), original_frame)
                inspect_request = {'task_id': fixture.task,
                    'bridge_execution_binding': {'execution_root': fixture.root},
                    'constraints': {'fx': {'domain_pack': core.RBD, 'run_mode': 'diagnose'}},
                    'controls': ['velocity_variance']}
                inspected = fixture.client.call('agent.fx.inspect_controls', inspect_request)
                self.assertEqual(inspected['controls'], {'velocity_variance': 0.})
                self.assertIs(inspected['readback_verified'], True)
                basis = json.loads(fixture.carrier().userData(adapter.BASIS_KEY))
                self.assertEqual(basis['task_seed'], fixture.manifest()['seed'])
                root_node = fixture.hou.node(fixture.root)
                before_manifest = root_node.userData('bridge_fx_manifest_v1')
                changed = json.loads(before_manifest)
                changed['seed'] += 1
                root_node.setUserData('bridge_fx_manifest_v1', json.dumps(changed))
                try:
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.client.call('agent.fx.inspect_controls', inspect_request)
                    self.assertEqual(refused.exception.code, 'RBD_TRUSTED_TASK_SEED_REQUIRED')
                finally:
                    root_node.setUserData('bridge_fx_manifest_v1', before_manifest)
                parameter = fixture.carrier().parm('snippet').eval()
                fixture.carrier().setUserData(adapter.PROGRAM_KEY, '{}')
                with self.assertRaises((fixture.addon.BridgeCommandError, ValueError)) as caught:
                    fixture.client.call('agent.fx.collect_evidence', fixture.params)
                self.assertIn('RBD_VELOCITY_AUTHORITY_REQUIRED', str(caught.exception))
                self.assertEqual(fixture.carrier().parm('snippet').eval(), parameter)
                self.assertEqual(fixture.hou.frame(), original_frame)

    def test_saved_checkpoint_rebinds_new_nodes_and_identity_without_reapply(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                before = fixture.host().checkpoint(fixture.roles, fixture.pack)
                original_node = fixture.carrier()
                original_session = original_node.sessionId()
                original_identity = fixture.addon._host_identity()
                path, receipt = fixture.save()
                checkpoint = receipt['scene_contract'][CHECKPOINT_KEY]
                self.assertEqual(checkpoint, before)
                self.assertEqual(checkpoint, fixture.addon._fx_rbd_checkpoint(
                    fixture.hou.node(fixture.root), fixture.manifest()))
                self.assertEqual(checkpoint['data'], {
                    key: original_node.userData(key) for key in (adapter.BASIS_KEY, adapter.PROGRAM_KEY)})
                self.assertEqual(receipt['sha256'], fixture.addon._fx_sha256_file(path))
                self.assertEqual(receipt['scene_contract_sha256'],
                    fixture.addon._fx_scene_contract_digest(receipt['scene_contract']))
                fixture.discard_authority()
                result = fixture.reopen(path)
                self.assertIs(result['rbd_velocity_restored'], True)
                self.assertTrue(result['parameters_verified'])
                self.assertTrue(result['connections_verified'])
                self.assertIsNot(fixture.carrier(), original_node)
                self.assertNotEqual(fixture.carrier().sessionId(), original_session)
                self.assertGreater(fixture.addon._host_identity()['scene_epoch'], original_identity['scene_epoch'])
                after = fixture.host().checkpoint(fixture.roles, fixture.pack)
                self.assertEqual({key: value for key, value in after.items() if key != 'identity'},
                                 {key: value for key, value in before.items() if key != 'identity'})
                readback = fixture.host().readback(fixture.roles, fixture.pack, {'velocity_variance': 0.})
                self.assertEqual(readback['controls'], {'velocity_variance': 0.})
                self.assertEqual(readback['native_simulation'], 'NOT_RUN')
                self.assertEqual(fixture.host().authority['transactions'], {})
                self.assertEqual(fixture.addon._FX_RBD_REOPEN_SCOPES, {})

    def test_saved_userdata_without_checkpoint_cannot_be_adopted(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                fixture.corrupt_saved_contract(lambda contract: contract.pop(CHECKPOINT_KEY), update_digest=True)
                error = self.assert_refused_reopen(fixture, path)
                self.assertEqual(error.code, 'RBD_REOPEN_CHECKPOINT_REQUIRED')

    def test_wrong_saved_contract_digest_is_refused(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                fixture.corrupt_saved_contract(
                    lambda contract: contract[CHECKPOINT_KEY].update(fps=99.), update_digest=False)
                self.assert_refused_reopen(fixture, path)

    def test_loaded_parameter_or_gate_corruption_is_refused(self):
        for version in core.VERSIONS:
            for parameter, value in (('snippet', 's@foreign = "foreign";'), ('exportlist', 'w')):
                with self.subTest(version=version, parameter=parameter), Fixture(version) as fixture:
                    path, _ = fixture.save()
                    original_load = fixture.hou.hipFile.load

                    def load_corrupted(*args, **kwargs):
                        result = original_load(*args, **kwargs)
                        fixture.carrier().parm(parameter).set(value)
                        return result

                    with patch.object(fixture.hou.hipFile, 'load', load_corrupted):
                        self.assert_refused_reopen(fixture, path)

    def test_loaded_basis_or_program_userdata_corruption_is_refused(self):
        for version in core.VERSIONS:
            for key in (adapter.BASIS_KEY, adapter.PROGRAM_KEY):
                with self.subTest(version=version, key=key), Fixture(version) as fixture:
                    path, _ = fixture.save()
                    original_load = fixture.hou.hipFile.load

                    def load_corrupted(*args, **kwargs):
                        result = original_load(*args, **kwargs)
                        fixture.carrier().setUserData(key, '{}')
                        return result

                    with patch.object(fixture.hou.hipFile, 'load', load_corrupted):
                        self.assert_refused_reopen(fixture, path)

    def test_wrapper_wrong_hip_digest_cannot_open_scope(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, receipt = fixture.save()
                fixture.discard_authority()
                before = fixture.carrier().parm('snippet').eval()
                with self.assertRaises(fixture.addon.BridgeCommandError) as caught:
                    with fixture.addon._fx_registered_rebind_saved_contract(
                            fixture.task, receipt['scene_contract'], path, '0' * 64):
                        self.fail('invalid HIP digest yielded a registered scope')
                self.assertEqual(caught.exception.code, 'ARTIFACT_MISMATCH')
                self.assertEqual(fixture.carrier().parm('snippet').eval(), before)
                self.assert_no_authority(fixture)

    def test_wrapper_body_failure_discards_registration_and_scopes(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, receipt = fixture.save()
                fixture.discard_authority()
                before = fixture.carrier().parm('snippet').eval()
                with self.assertRaisesRegex(OSError, 'explicit caller failure'):
                    with fixture.addon._fx_registered_rebind_saved_contract(
                            fixture.task, receipt['scene_contract'], path, receipt['sha256']) as restored:
                        self.assertIs(restored['rbd_velocity_restored'], True)
                        raise OSError('explicit caller failure')
                self.assertEqual(fixture.carrier().parm('snippet').eval(), before)
                self.assert_no_authority(fixture)

    def test_candidate_manifest_failure_preserves_previous_checkpoint(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                before = fixture.host().checkpoint(fixture.roles, fixture.pack)
                state_path = fixture.addon._fx_state_path(fixture.task)
                state_bytes = state_path.read_bytes()
                with patch.object(fixture.addon, '_fx_write_state', side_effect=OSError('explicit manifest failure')) as fault:
                    with self.assertRaises(Exception):
                        fixture.apply_zero()
                self.assertTrue(fault.called)
                self.assertEqual(state_path.read_bytes(), state_bytes)
                self.assertEqual(fixture.host().checkpoint(fixture.roles, fixture.pack), before)
                self.assertEqual(fixture.host().authority['transactions'], {})
                self.assertEqual(fixture.addon.__dict__.get('_FX_RBD_REOPEN_SCOPES', {}), {})

    def test_reopen_completion_failure_discards_new_authority(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                state_path = fixture.addon._fx_task_saves_path(fixture.task)
                state_bytes = state_path.read_bytes()
                fixture.discard_authority()
                with patch.object(fixture.addon, '_fx_scene_transition_complete',
                                  side_effect=OSError('explicit completion failure')):
                    with self.assertRaises(OSError):
                        fixture.reopen(path)
                self.assertEqual(state_path.read_bytes(), state_bytes)
                self.assert_no_authority(fixture)
                transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']['rbd-unit-reopen']
                self.assertEqual(transition['state'], 'INTENT')

    def test_identity_drift_during_restore_performs_no_native_writes(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                node_class = type(fixture.carrier())
                parameter_class = type(fixture.carrier().parm('snippet'))
                original_load = fixture.hou.hipFile.load
                original_read = node_class.userData
                original_data_write = node_class.setUserData
                original_parameter_write = parameter_class.set
                loaded, drifted, writes = [], [], []

                def load(*args, **kwargs):
                    result = original_load(*args, **kwargs)
                    loaded.append(True)
                    return result

                def read_with_drift(node, key):
                    result = original_read(node, key)
                    if loaded and not drifted and node.path() == fixture.roles[program.ROLE] and key == adapter.PROGRAM_KEY:
                        fixture.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'explicit-read-drift'
                        drifted.append(True)
                    return result

                def write_data(node, key, value):
                    if drifted and key in (adapter.BASIS_KEY, adapter.PROGRAM_KEY):
                        writes.append(('userdata', node.path(), key))
                    return original_data_write(node, key, value)

                def write_parameter(parameter, value, **kwargs):
                    if drifted:
                        writes.append(('parameter', parameter.path()))
                    return original_parameter_write(parameter, value, **kwargs)

                with patch.object(fixture.hou.hipFile, 'load', load), \
                        patch.object(node_class, 'userData', read_with_drift), \
                        patch.object(node_class, 'setUserData', write_data), \
                        patch.object(parameter_class, 'set', write_parameter):
                    self.assert_refused_reopen(fixture, path)
                self.assertTrue(drifted)
                self.assertEqual(writes, [])

    def test_completion_persisted_then_raised_restores_intent_and_discards_authority(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                fixture.discard_authority()
                original_complete = fixture.addon._fx_scene_transition_complete
                completed = []

                def complete_then_raise(*args, **kwargs):
                    result = original_complete(*args, **kwargs)
                    completed.append(result)
                    raise OSError('failure after completion persistence')

                with patch.object(fixture.addon, '_fx_scene_transition_complete', complete_then_raise):
                    with self.assertRaisesRegex(OSError, 'failure after completion persistence'):
                        fixture.reopen(path)
                self.assertEqual(len(completed), 1)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_no_authority(fixture)
                transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']['rbd-unit-reopen']
                self.assertEqual(transition['state'], 'INTENT')
                self.assertNotIn('after_identity', transition)
                self.assertEqual(transition['operation_receipt_sha256'],
                                 fixture.addon._fx_scene_transition_digest(transition))
                with self.assertRaises(fixture.addon.BridgeCommandError):
                    fixture.client.call('scene.reconcile_transition', {
                        'task_id': fixture.task, 'operation_id': 'rbd-unit-reopen'})

    def test_identity_drift_after_completion_restores_intent_and_discards_authority(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                path, _ = fixture.save()
                saved_path = fixture.addon._fx_task_saves_path(fixture.task)
                saved_bytes = saved_path.read_bytes()
                fixture.discard_authority()
                original_complete = fixture.addon._fx_scene_transition_complete
                completed = []

                def complete_then_drift(*args, **kwargs):
                    result = original_complete(*args, **kwargs)
                    completed.append(result)
                    fixture.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'after-completion-drift'
                    return result

                with patch.object(fixture.addon, '_fx_scene_transition_complete', complete_then_drift):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as caught:
                        fixture.reopen(path)
                self.assertEqual(caught.exception.code, 'SCENE_STATE_DRIFT')
                self.assertEqual(len(completed), 1)
                self.assertEqual(saved_path.read_bytes(), saved_bytes)
                self.assert_no_authority(fixture)
                transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']['rbd-unit-reopen']
                self.assertEqual(transition['state'], 'INTENT')
                self.assertNotIn('after_identity', transition)
                self.assertEqual(transition['operation_receipt_sha256'],
                                 fixture.addon._fx_scene_transition_digest(transition))
                with self.assertRaises(fixture.addon.BridgeCommandError):
                    fixture.client.call('scene.reconcile_transition', {
                        'task_id': fixture.task, 'operation_id': 'rbd-unit-reopen'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
