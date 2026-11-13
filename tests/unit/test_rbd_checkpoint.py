"""R05 component recovery only; private unit authority is not HIP proof."""
import copy
import json
import unittest
from unittest.mock import patch

from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_host as runtime
from houdini_bridge import native_rbd_controls_program as program
from test_rbd_host_authority import fixed_fixture, prepare_zero


class RbdCheckpointTests(unittest.TestCase):
    def registered(self, version=core.VERSIONS[0]):
        host, nodes, roles, hou, identity = fixed_fixture(version)
        host.write(prepare_zero(host, nodes, roles, version), roles, {})
        return host, nodes, roles, hou, identity

    def migrated(self, version=core.VERSIONS[0], retain_private=False):
        old, old_nodes, roles, old_hou, old_identity = self.registered(version)
        checkpoint = old.checkpoint(roles, {})
        if retain_private:
            host, nodes, hou, identity = old, old_nodes, old_hou, old_identity
        else:
            host, nodes, roles, hou, identity = fixed_fixture(version)
            for role, node in nodes.items():
                node.data = copy.deepcopy(old_nodes[role].data)
                for name, parameter in node.parameters.items():
                    parameter.value = copy.deepcopy(old_nodes[role].parameters[name].value)
        identity.update(pid=456, launch_nonce='new-nonce', session_id='new-session',
                        process_generation='new-generation', scene_epoch=1)
        for node in nodes.values():
            node.native_session_id += 1000
        return host, nodes, roles, hou, identity, checkpoint

    def authorize(self, host, roles, checkpoint, pack=None):
        expected = copy.deepcopy(checkpoint)
        expected_roles = copy.deepcopy(roles)
        expected_pack = copy.deepcopy({} if pack is None else pack)
        calls = []

        def private_authority(actual_roles, actual_pack, actual_checkpoint):
            calls.append(copy.deepcopy(actual_checkpoint))
            return (actual_roles == expected_roles and actual_pack == expected_pack
                    and actual_checkpoint == expected)

        host.h['_fx_rbd_reopen_authority'] = private_authority
        return calls

    def refused(self, call, codes=None):
        with self.assertRaises(core.NativeFlipRbdDomainError) as error:
            call()
        if codes is not None:
            self.assertIn(error.exception.code, codes)
        return error.exception

    def native_snapshot(self, nodes):
        return {role: dict(data=copy.deepcopy(node.data), parameters={
            name: copy.deepcopy(parameter.value) for name, parameter in node.parameters.items()})
            for role, node in nodes.items()}

    def block_native_writes(self, nodes):
        for node in nodes.values():
            for name in ('setUserData', 'destroyUserData', 'setInput'):
                context = patch.object(node, name, side_effect=AssertionError('native write during recovery'))
                context.start()
                self.addCleanup(context.stop)
            for parameter in node.parameters.values():
                context = patch.object(parameter, 'set', side_effect=AssertionError('parameter write during recovery'))
                context.start()
                self.addCleanup(context.stop)

    def test_checkpoint_requires_owned_complete_registration_and_returns_detached_json(self):
        host, nodes, roles, hou, identity = fixed_fixture(core.VERSIONS[0])
        self.refused(lambda: host.checkpoint(roles, {}), ('RBD_REOPEN_CHECKPOINT_REQUIRED',))
        prepare_zero(host, nodes, roles, core.VERSIONS[0])
        self.refused(lambda: host.checkpoint(roles, {}), ('RBD_REOPEN_CHECKPOINT_REQUIRED',))
        host.write(prepare_zero(host, nodes, roles, core.VERSIONS[0]), roles, {})
        checkpoint = host.checkpoint(roles, {})
        self.assertEqual(checkpoint['schema'], runtime.CHECKPOINT_SCHEMA)
        self.assertEqual(checkpoint, json.loads(json.dumps(checkpoint)))
        self.assertEqual({(item['role'], item['parm']) for item in checkpoint['parameters']},
                         {(program.ROLE, name) for name in (*program.GATES, 'snippet')}
                         | {('solver', name) for name in ('startframe', 'overwriteattributes', 'usescale', 'timescale')})
        self.assertTrue(all('session_id' not in fact for fact in checkpoint['nodes'].values()))
        original = copy.deepcopy(checkpoint)
        checkpoint['roles'].clear()
        checkpoint['parameters'][0]['observation'].clear()
        checkpoint['data'].clear()
        self.assertEqual(host.checkpoint(roles, {}), original)

    def test_new_identity_and_node_sessions_restore_both_versions_without_writes(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity, checkpoint = self.migrated(version)
                self.refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}),
                             ('RBD_VELOCITY_AUTHORITY_REQUIRED',))
                calls = self.authorize(host, roles, checkpoint)
                before = self.native_snapshot(nodes)
                self.block_native_writes(nodes)
                with patch.object(host, 'initialize', side_effect=AssertionError('reinitialization')):
                    token = host.reopen(roles, {}, checkpoint)
                    host.end(token, True)
                self.assertIsInstance(token, str)
                self.assertTrue(token)
                result = host.readback(roles, {}, {'velocity_variance': 0.})
                self.assertEqual(result['controls'], {'velocity_variance': 0.})
                self.assertEqual(result['native_simulation'], 'NOT_RUN')
                self.assertEqual(host.checkpoint(roles, {})['data'], checkpoint['data'])
                self.assertEqual(host.checkpoint(roles, {})['identity'], identity)
                self.assertEqual(self.native_snapshot(nodes), before)
                self.assertGreaterEqual(len(calls), 2)
                self.assertEqual(hou.frame(), 12.)

    def test_public_checkpoint_without_literal_private_authority_refused(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        before = self.native_snapshot(nodes)
        self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_REOPEN_AUTHORITY_REQUIRED',))
        for answer in (False, None, 1, 'true'):
            with self.subTest(answer=answer):
                host.h['_fx_rbd_reopen_authority'] = lambda *args: answer
                self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_REOPEN_AUTHORITY_REQUIRED',))
                self.assertFalse(host.authority['records'])
                self.assertFalse(host.authority['transactions'])
        self.assertEqual(self.native_snapshot(nodes), before)

    def test_wrong_shape_extra_fields_nonfinite_and_utf8_budget_refused(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        host.h['_fx_rbd_reopen_authority'] = lambda *args: True
        malformed = (None, [], dict(checkpoint, extra=True), dict(checkpoint, schema='foreign'),
                     dict(checkpoint, frame=float('nan')), dict(checkpoint, nodes=object()),
                     dict(checkpoint, parameters=list(reversed(checkpoint['parameters']))))
        for value in malformed:
            with self.subTest(kind=type(value).__name__):
                self.refused(lambda: host.reopen(roles, {}, value), ('RBD_CHECKPOINT_INVALID',))
        padding = '中' * (runtime.MAX_CHECKPOINT_BYTES // 3 + 1)
        self.refused(lambda: host.reopen(roles, {}, dict(checkpoint, extra=padding)),
                     ('RBD_CHECKPOINT_BUDGET_EXCEEDED',))
        nested = []
        for depth in range(34):
            nested = [nested]
        self.refused(lambda: host.reopen(roles, {}, dict(checkpoint, extra=nested)),
                     ('RBD_CHECKPOINT_BUDGET_EXCEEDED',))
        self.assertFalse(host.authority['records'])
        self.assertFalse(host.authority['transactions'])

    def test_foreign_task_root_version_roles_pack_and_build_refused(self):
        for field, value in (('task_id', 'foreign'), ('version', core.VERSIONS[1]),
                             ('plugin_build', 'e' * 64), ('pid', 0), ('scene_epoch', -1),
                             ('launch_nonce', ''), ('session_id', ''), ('process_generation', '')):
            with self.subTest(identity_field=field):
                host, nodes, roles, hou, identity, checkpoint = self.migrated()
                changed = copy.deepcopy(checkpoint)
                changed['identity'][field] = value
                host.h['_fx_rbd_reopen_authority'] = lambda *args: True
                self.refused(lambda: host.reopen(roles, {}, changed), ('RBD_CHECKPOINT_INVALID',))
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        host.h['_fx_rbd_reopen_authority'] = lambda *args: True
        for field, value in (('binding', {'task_id': 'task', 'task_root': '/obj/foreign'}),
                             ('roles', dict(roles, solver='/obj/foreign/solver')),
                             ('native_version', core.VERSIONS[1]), ('pack_sha256', '0' * 64)):
            with self.subTest(field=field):
                self.refused(lambda: host.reopen(roles, {}, dict(checkpoint, **{field: value})),
                             ('RBD_CHECKPOINT_INVALID',))
        self.refused(lambda: host.reopen(roles, {'foreign': True}, checkpoint), ('RBD_CHECKPOINT_INVALID',))

    def test_userdata_and_every_gate_solver_parameter_or_driver_drift_refused(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        self.authorize(host, roles, checkpoint)
        for key in (runtime.BASIS_KEY, runtime.PROGRAM_KEY):
            before = nodes[program.ROLE].data[key]
            nodes[program.ROLE].data[key] = '{}'
            self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_CHECKPOINT_INVALID',))
            nodes[program.ROLE].data[key] = before
        for item in checkpoint['parameters']:
            parameter = nodes[item['role']].parm(item['parm'])
            with self.subTest(role=item['role'], parameter=item['parm']):
                before = parameter.value
                parameter.value = 'foreign' if type(before) is str else before + 1
                self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_CHECKPOINT_INVALID',))
                parameter.value = before
                parameter.native_driven = True
                self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_CHECKPOINT_INVALID',))
                parameter.native_driven = False
                self.assertFalse(host.authority['records'])
                self.assertFalse(host.authority['transactions'])

    def test_full_parameter_observation_metadata_drift_refused(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        self.authorize(host, roles, checkpoint)
        original = host.h['_fx_planned_observation']

        def drift(node, name, **kwargs):
            result = original(node, name, **kwargs)
            if node.role == program.ROLE and name == 'snippet':
                result['late_native_metadata'] = {'expression': 'foreign', 'keys': [1, 2]}
            return result

        host.h['_fx_planned_observation'] = drift
        self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_CHECKPOINT_INVALID',))
        self.assertFalse(host.authority['records'])

    def test_frame_fps_wire_and_actual_geometry_drift_refused(self):
        for kind in ('frame', 'fps', 'wire', 'geometry'):
            with self.subTest(kind=kind):
                host, nodes, roles, hou, identity, checkpoint = self.migrated()
                self.authorize(host, roles, checkpoint)
                if kind == 'frame':
                    hou.current_frame += 1
                elif kind == 'fps':
                    hou.fps = lambda: 30.
                elif kind == 'wire':
                    nodes['solver'].setInput(0, nodes['configure'])
                else:
                    nodes['configure'].native_geometry.points()[0].values['temperature'] += 1
                before = self.native_snapshot(nodes)
                self.block_native_writes(nodes)
                self.refused(lambda: host.reopen(roles, {}, checkpoint))
                self.assertEqual(self.native_snapshot(nodes), before)
                self.assertFalse(host.authority['records'])
                self.assertFalse(host.authority['transactions'])

    def test_rollback_restores_only_previous_record_and_preserves_unrelated_root(self):
        for retain_private in (False, True):
            with self.subTest(retain_private=retain_private):
                host, nodes, roles, hou, identity, checkpoint = self.migrated(retain_private=retain_private)
                previous = host.authority['records'].get('/obj/task')
                sentinel = object()
                host.authority['records']['/obj/unrelated'] = sentinel
                self.authorize(host, roles, checkpoint)
                before = self.native_snapshot(nodes)
                token = host.reopen(roles, {}, checkpoint)
                host.end(token, False)
                self.assertIs(host.authority['records'].get('/obj/task'), previous)
                self.assertIs(host.authority['records']['/obj/unrelated'], sentinel)
                self.assertEqual(self.native_snapshot(nodes), before)
                self.assertFalse(host.authority['transactions'])
                self.refused(lambda: host.readback(roles, {}, {'velocity_variance': 0.}),
                             ('RBD_VELOCITY_AUTHORITY_REQUIRED',))

    def test_cas_replacement_cannot_be_overwritten_by_commit_or_rollback(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        self.authorize(host, roles, checkpoint)
        token = host.reopen(roles, {}, checkpoint)
        issued = host.authority['records']['/obj/task']
        successor = host._copy_record(issued)
        host.authority['records']['/obj/task'] = successor
        for commit in (True, False):
            self.refused(lambda: host.end(token, commit), ('RBD_CHECKPOINT_CHANGED',))
            self.assertIs(host.authority['records']['/obj/task'], successor)
        host.authority['records']['/obj/task'] = issued
        host.end(token, False)

    def test_same_root_active_token_invalid_token_and_double_end_refused(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        self.authorize(host, roles, checkpoint)
        token = host.reopen(roles, {}, checkpoint)
        self.refused(lambda: host.reopen(roles, {}, checkpoint), ('RBD_TRANSACTION_ACTIVE',))
        for invalid in ('foreign-token', None):
            self.refused(lambda: host.end(invalid, False), ('RBD_TRANSACTION_REQUIRED',))
        for invalid in (1, None, 'true'):
            self.refused(lambda: host.end(token, invalid), ('RBD_TRANSACTION_REQUIRED',))
        host.end(token, True)
        self.refused(lambda: host.end(token, False), ('RBD_TRANSACTION_REQUIRED',))

    def test_authority_callback_cannot_mutate_input_checkpoint_or_current_context(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        original = copy.deepcopy(checkpoint)

        def isolated(roles_value, pack_value, value):
            roles_value.clear()
            pack_value['foreign'] = True
            value.clear()
            return True

        host.h['_fx_rbd_reopen_authority'] = isolated
        token = host.reopen(roles, {}, checkpoint)
        host.end(token, True)
        self.assertEqual(checkpoint, original)
        self.assertEqual(roles, original['roles'])
        host, nodes, roles, hou, identity, checkpoint = self.migrated()

        def drift(*args):
            identity['launch_nonce'] = 'late-authority-nonce'
            return True

        host.h['_fx_rbd_reopen_authority'] = drift
        self.refused(lambda: host.reopen(roles, {}, checkpoint))
        self.assertFalse(host.authority['records'])
        self.assertFalse(host.authority['transactions'])

    def test_late_geometry_identity_failure_cleans_provisional_registration(self):
        host, nodes, roles, hou, identity, checkpoint = self.migrated()
        self.authorize(host, roles, checkpoint)
        original = nodes['solver'].inputGeometry

        def drift(index):
            result = original(index)
            identity['launch_nonce'] = 'late-native-nonce'
            return result

        nodes['solver'].inputGeometry = drift
        before = self.native_snapshot(nodes)
        self.refused(lambda: host.reopen(roles, {}, checkpoint))
        self.assertFalse(host.authority['records'])
        self.assertFalse(host.authority['transactions'])
        self.assertEqual(self.native_snapshot(nodes), before)

    def test_end_rechecks_authority_identity_and_facts_before_commit(self):
        for kind in ('authority', 'identity', 'gate'):
            with self.subTest(kind=kind):
                host, nodes, roles, hou, identity, checkpoint = self.migrated()
                self.authorize(host, roles, checkpoint)
                token = host.reopen(roles, {}, checkpoint)
                if kind == 'authority':
                    host.h['_fx_rbd_reopen_authority'] = lambda *args: False
                elif kind == 'identity':
                    identity['launch_nonce'] = 'late-end-nonce'
                else:
                    nodes[program.ROLE].parm('exportlist').value = 'w'
                before = self.native_snapshot(nodes)
                self.refused(lambda: host.end(token, True))
                self.assertIn(token, host.authority['transactions'])
                self.assertEqual(self.native_snapshot(nodes), before)
                host.end(token, False)
                self.assertFalse(host.authority['records'])
                self.assertFalse(host.authority['transactions'])

    def test_end_late_authority_identity_drift_cannot_commit_registration(self):
        for kind in ('identity', 'gate', 'fps', 'frame'):
            with self.subTest(kind=kind):
                host, nodes, roles, hou, identity, checkpoint = self.migrated()
                self.authorize(host, roles, checkpoint)
                token = host.reopen(roles, {}, checkpoint)

                def late_authority(*args):
                    if kind == 'identity':
                        identity['launch_nonce'] = 'late-commit-authority-nonce'
                    elif kind == 'gate':
                        nodes[program.ROLE].parm('exportlist').value = 'w'
                    elif kind == 'fps':
                        hou.fps = lambda: 30.
                    else:
                        hou.current_frame += 1
                    return True

                host.h['_fx_rbd_reopen_authority'] = late_authority
                self.refused(lambda: host.end(token, True))
                self.assertIn(token, host.authority['transactions'])
                host.end(token, False)
                self.assertFalse(host.authority['records'])


if __name__ == '__main__':
    unittest.main()
