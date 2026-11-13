"""R05 process authority and late HOM drift, with fixed native geometry."""
import copy
import json
import unittest

from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_program as program
from houdini_bridge.native_rbd_controls_host import BASIS_KEY, PROGRAM_KEY, Host
from test_native_rbd_controls_program import native_fixture


def fixed_fixture(version):
    host, nodes, roles, hou, identity = native_fixture(version)
    carrier = nodes[program.ROLE]
    carrier.geometryAtFrame = lambda frame, output_index=0: nodes['configure'].native_geometry.freeze()
    for index, node in enumerate(nodes.values()):
        node.native_session_id = index + 100
        node.sessionId = lambda node=node: node.native_session_id
        node.native_editable = True
        node.isEditable = lambda node=node: node.native_editable
        node.native_bypassed = False
        node.isBypassed = lambda node=node: node.native_bypassed
        node.native_errors = ()
        node.errors = lambda node=node: node.native_errors
        for parameter in node.parameters.values():
            parameter.native_driven = False
    original_observe = host.h['_fx_planned_observation']
    def observe(node, name, **kwargs):
        return dict(original_observe(node, name, **kwargs), driven=node.parm(name).native_driven)
    host.h['_fx_planned_observation'] = observe
    return host, nodes, roles, hou, identity


def prepare_zero(host, nodes, roles, version):
    observations = host.observations({'velocity_variance': 0.}, roles, {}, task_seed=123)
    write = core.candidate_write_plan(core.RBD, {'velocity_variance': 0.}, version,
                                     observations=observations)[0]
    item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
    host.prepare(item)
    return item


def public_registration(host, nodes, roles, version):
    item = prepare_zero(host, nodes, roles, version)
    basis = next(guard['value'] for guard in item['native_write']['frozen_readback_guards']
                 if (guard['role'], guard['parm']) == (program.ROLE, '@basis'))
    carrier = nodes[program.ROLE]
    carrier.setUserData(BASIS_KEY, json.dumps(basis, sort_keys=True))
    carrier.setUserData(PROGRAM_KEY, json.dumps(item['native_write']['registration'], sort_keys=True))
    carrier.parm('snippet').set(item['native_write']['value'])
    return item


class RbdHostAuthorityTests(unittest.TestCase):
    def assert_authority_refused(self, call):
        with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
            call()
        self.assertEqual(refused.exception.code, 'RBD_VELOCITY_AUTHORITY_REQUIRED')

    def assert_context_refused(self, call, codes=('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED',)):
        with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
            call()
        self.assertIn(refused.exception.code, codes)

    def test_public_valid_basis_and_registration_cannot_grant_authority(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                public_registration(host, nodes, roles, version)
                before = copy.deepcopy(nodes[program.ROLE].data)
                self.assert_authority_refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}))
                self.assertEqual(nodes[program.ROLE].data, before)
                self.assertEqual(hou.frame(), 12.)

    def test_public_basis_alone_cannot_become_pending_owned_basis(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = public_registration(host, nodes, roles, version)
                nodes[program.ROLE].destroyUserData(PROGRAM_KEY)
                nodes[program.ROLE].parm('snippet').set('')
                self.assert_authority_refused(lambda: host.observations(
                    {'velocity_variance': 0.}, roles, {}, [item['native_write']]))

    def test_rehashed_public_seed_cannot_replace_private_issued_basis(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = prepare_zero(host, nodes, roles, version)
                host.write(item, roles, {})
                carrier = nodes[program.ROLE]
                basis = json.loads(carrier.userData(BASIS_KEY))
                basis['task_seed'] += 1
                basis['content_sha256'] = program._digest(
                    {key: value for key, value in basis.items() if key != 'content_sha256'})
                registration = json.loads(carrier.userData(PROGRAM_KEY))
                registration['basis_sha256'] = basis['content_sha256']
                carrier.setUserData(BASIS_KEY, json.dumps(basis, sort_keys=True))
                carrier.setUserData(PROGRAM_KEY, json.dumps(registration, sort_keys=True))
                self.assert_authority_refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}))

    def test_owned_zero_write_and_new_host_same_actual_context_read_back(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                before = copy.deepcopy(nodes['configure'].native_geometry.points()[0].values)
                item = prepare_zero(host, nodes, roles, version)
                result = host.write(item, roles, {})
                self.assertEqual(result['after'], 0.)
                equivalent = Host(host.h, hou)
                result = equivalent.readback(roles, {}, {'velocity_variance': 0.})
                self.assertEqual(result['controls'], {'velocity_variance': 0.})
                self.assertEqual(result['native_simulation'], 'NOT_RUN')
                self.assertEqual(nodes[program.ROLE].geometryAtFrame(1).points()[0].values, before)
                self.assertEqual(hou.frame(), 12.)

    def test_copied_userdata_into_other_actual_context_is_not_authority(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = prepare_zero(host, nodes, roles, version)
                host.write(item, roles, {})
                other, other_nodes, other_roles, other_hou, other_identity = fixed_fixture(version)
                other_nodes[program.ROLE].data = copy.deepcopy(nodes[program.ROLE].data)
                other_nodes[program.ROLE].parm('snippet').set(item['parm'].value)
                self.assert_authority_refused(lambda: other.readback(
                    other_roles, {}, {'velocity_variance': 0.}))

    def test_other_actual_context_cannot_adopt_signed_pending_plan(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = prepare_zero(host, nodes, roles, version)
                other, other_nodes, other_roles, other_hou, other_identity = fixed_fixture(version)
                self.assert_authority_refused(lambda: other.observations(
                    {'velocity_variance': 0.}, other_roles, {}, [item['native_write']]))
                self.assertEqual(other_nodes[program.ROLE].data, {})
                self.assertEqual(other_nodes[program.ROLE].parm('snippet').value, '')

    def test_registered_identity_fields_cannot_adopt_old_public_registration(self):
        for version in core.VERSIONS:
            for field, replacement in (('pid', 456), ('launch_nonce', 'new-nonce'),
                                       ('session_id', 'new-session'), ('process_generation', 'new-generation'),
                                       ('scene_epoch', 1), ('plugin_build', 'e' * 64)):
                with self.subTest(version=version, field=field):
                    host, nodes, roles, hou, identity = fixed_fixture(version)
                    host.write(prepare_zero(host, nodes, roles, version), roles, {})
                    identity[field] = replacement
                    self.assert_authority_refused(lambda: Host(host.h, hou).readback(
                        roles, {}, {'velocity_variance': 0.}))

    def test_same_path_new_node_object_does_not_adopt_private_record(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                host.write(prepare_zero(host, nodes, roles, version), roles, {})
                original = nodes[program.ROLE]
                replacement = copy.copy(original)
                replacement.data = copy.deepcopy(original.data)
                nodes[program.ROLE] = replacement
                nodes['solver'].setInput(0, replacement)
                self.assert_authority_refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}))

    def test_same_node_changed_session_id_does_not_adopt_private_record(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                host.write(prepare_zero(host, nodes, roles, version), roles, {})
                nodes[program.ROLE].native_session_id += 1
                self.assert_authority_refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}))

    def test_rollback_restores_prior_private_registration(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                host.write(prepare_zero(host, nodes, roles, version), roles, {})
                item = prepare_zero(host, nodes, roles, version)
                previous_data = copy.deepcopy(nodes[program.ROLE].data)
                previous_snippet = item['parm'].value
                original_set = item['parm'].set
                def fail_after_native_write(value, **kwargs):
                    original_set(value, **kwargs)
                    raise OSError('explicit bottom native set failure')
                item['parm'].set = fail_after_native_write
                with self.assertRaises(OSError):
                    host.write(item, roles, {})
                item['parm'].set = original_set
                original_set(previous_snippet)
                Host(host.h, hou).restore(item)
                self.assertEqual(nodes[program.ROLE].data, previous_data)
                self.assertEqual(Host(host.h, hou).readback(
                    roles, {}, {'velocity_variance': 0.})['controls'], {'velocity_variance': 0.})

    def test_rollback_of_first_write_does_not_leave_registration_authority(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = prepare_zero(host, nodes, roles, version)
                host.write(item, roles, {})
                public_data = copy.deepcopy(nodes[program.ROLE].data)
                public_snippet = item['parm'].value
                item['parm'].set('')
                Host(host.h, hou).restore(item)
                self.assertEqual(nodes[program.ROLE].data, {})
                nodes[program.ROLE].data = public_data
                item['parm'].set(public_snippet)
                self.assert_authority_refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}))

    def test_late_solver_geometry_identity_drift_refuses(self):
        self.check_late_drift('identity')

    def test_late_solver_geometry_frame_drift_refuses(self):
        self.check_late_drift('frame')

    def test_late_solver_geometry_gate_drift_refuses(self):
        self.check_late_drift('gate')

    def test_late_solver_geometry_parameter_driver_drift_refuses(self):
        self.check_late_drift('driver')

    def test_late_solver_geometry_fps_drift_refuses(self):
        self.check_late_drift('fps')

    def test_late_solver_geometry_wire_drift_refuses(self):
        self.check_late_drift('wire')

    def test_late_solver_geometry_node_object_drift_refuses(self):
        self.check_late_drift('node')

    def test_late_solver_geometry_node_session_drift_refuses(self):
        self.check_late_drift('session')

    def test_late_solver_geometry_editability_drift_refuses(self):
        self.check_late_drift('editable')

    def test_late_solver_geometry_bypass_drift_refuses(self):
        self.check_late_drift('bypass')

    def test_late_solver_geometry_error_drift_refuses(self):
        self.check_late_drift('errors')

    def test_last_native_fps_read_cannot_hide_previously_observed_gate_drift(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                reads = []
                def fps():
                    reads.append(True)
                    if len(reads) == 3:
                        nodes[program.ROLE].parm('exportlist').set('w')
                    return 24.
                hou.fps = fps
                self.assert_context_refused(lambda: host.observations(
                    {'velocity_variance': 0.}, roles, {}, task_seed=123))
                self.assertEqual(nodes[program.ROLE].data, {})
                self.assertEqual(nodes[program.ROLE].parm('snippet').value, '')
                self.assertEqual(hou.frame(), 12.)

    def check_late_drift(self, mutation):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                original_input = nodes['solver'].inputGeometry
                called = []
                def changed_input(input_index):
                    geometry = original_input(input_index)
                    if not called:
                        called.append(True)
                        if mutation == 'identity':
                            identity['launch_nonce'] = 'late-nonce'
                        elif mutation == 'frame':
                            geometry.freeze = lambda read_only=True: change_frame(geometry)
                        elif mutation == 'gate':
                            nodes[program.ROLE].parm('exportlist').set('w')
                        elif mutation == 'driver':
                            nodes[program.ROLE].parm('snippet').native_driven = True
                        elif mutation == 'fps':
                            hou.fps = lambda: 30.
                        elif mutation == 'wire':
                            nodes['solver'].setInput(0, nodes['configure'])
                        elif mutation == 'node':
                            nodes[program.ROLE] = copy.copy(nodes[program.ROLE])
                        elif mutation == 'session':
                            nodes[program.ROLE].native_session_id += 1
                        elif mutation == 'editable':
                            nodes[program.ROLE].native_editable = False
                        elif mutation == 'bypass':
                            nodes[program.ROLE].native_bypassed = True
                        else:
                            nodes[program.ROLE].native_errors = ('explicit late cook error',)
                    return geometry
                def change_frame(geometry):
                    result = copy.deepcopy(geometry)
                    def late_freeze(read_only=True):
                        hou.setFrame(99.)
                        return result
                    result.freeze = late_freeze
                    hou.setFrame(99.)
                    return result
                nodes['solver'].inputGeometry = changed_input
                codes = ('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED',)
                if mutation in ('identity', 'editable', 'bypass', 'errors'):
                    codes += ('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED',)
                elif mutation in ('node', 'wire'):
                    codes += ('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED',)
                elif mutation == 'frame':
                    codes += ('RBD_NATIVE_SAMPLE_FRAME_CHANGED',)
                self.assert_context_refused(lambda: host.observations(
                    {'velocity_variance': 0.}, roles, {}, task_seed=123), codes)
                self.assertTrue(called)
                self.assertEqual(nodes[program.ROLE].data, {})
                self.assertEqual(nodes[program.ROLE].parm('snippet').value, '')
                self.assertEqual(hou.frame(), 12.)

    def test_trusted_seed_and_passthrough_inspection_do_not_mutate_native_scene(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                trusted = [123]
                host.h['_fx_rbd_task_seed'] = lambda actual_roles, pack: trusted[0]
                carrier = nodes[program.ROLE]
                before = copy.deepcopy(carrier.data), carrier.parm('snippet').value
                observed = host.inspect_controls(roles, {})
                self.assertEqual(observed['controls'], {'velocity_variance':0.})
                self.assertEqual(observed['native_simulation'], 'NOT_RUN')
                self.assertEqual((carrier.data,carrier.parm('snippet').value),before)
                for seed in (124, True):
                    with self.assertRaisesRegex(ValueError,'FROZEN_VELOCITY_BASIS_REQUIRED'):
                        host.observations({'velocity_variance':0.}, roles, {}, task_seed=seed)
                item = prepare_zero(host, nodes, roles, version)
                host.write(item,roles,{})
                self.assertEqual(host.inspect_controls(roles,{})['controls'],{'velocity_variance':0.})
                trusted[0] = 124
                with self.assertRaisesRegex(ValueError,'FROZEN_VELOCITY_BASIS_REQUIRED'):
                    host.inspect_controls(roles,{})
                trusted[0] = 123
                nodes['configure'].native_geometry.points()[0].values['active'] = 0
                with self.assertRaises(ValueError): host.inspect_controls(roles,{})


if __name__ == '__main__':
    unittest.main()
