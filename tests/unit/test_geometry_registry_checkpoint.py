"""Component-only checkpoint recovery; no HIP lifecycle or deformation proof."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_program as program
from houdini_bridge import native_geometry_runtime_registry as runtime
import test_native_geometry_runtime_registry as fixtures


class GeometryRegistryCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.component = fixtures.NativeGeometryRuntimeRegistryTests()
        self.component.setUp()
        self.addCleanup(self.component.doCleanups)
        self.registry = self.component.registry
        self.fixture = self.component.fixture
        self.roles = self.component.roles
        self.pack = self.component.pack
        self.host = self.component.addon.__dict__

    def checkpoint(self):
        return self.registry.checkpoint(self.roles, self.pack)

    def initialize(self, value=0, commit=True):
        token, _, _ = self.component.initialize(commit=commit)
        if value:
            prepared = self.fixture.prepared(value)
            self.fixture.write(prepared)
            self.fixture.host.release(prepared)
        return token

    def authorize(self, expected):
        calls = []
        def authority(roles, pack, checkpoint):
            calls.append(copy.deepcopy(checkpoint))
            return roles == self.roles and pack == self.pack and checkpoint == expected
        self.host['_fx_geometry_reopen_authority'] = authority
        return calls

    def migrate(self, replace_nodes=False, pid=None):
        identity = dict(self.fixture.identity, launch_nonce='checkpoint-new-producer',
                        session_id='checkpoint-new-session', process_generation='checkpoint-new-generation')
        self.component.addon._TASK_HOST_IDENTITY = identity
        if pid is not None:
            identity['pid'] = pid
        self.component.addon._BRIDGE_SCENE_STATE.scene_epoch += 1
        self.component.addon._root_lease_issue(self.fixture.root, self.fixture.task, 'sop')
        if replace_nodes:
            self.fixture.root_node = copy.copy(self.fixture.root_node)
            self.fixture.root_node.session += 1000
            self.fixture.nodes = {role: copy.copy(node) for role, node in self.fixture.nodes.items()}
            for node in self.fixture.nodes.values():
                node.session += 1000
            for node in self.fixture.nodes.values():
                node.connections = [copy.copy(wire) for wire in node.connections]
                for wire in node.connections:
                    wire.source = self.fixture.nodes[next(role for role, old in self.roles.items()
                                                        if old == wire.inputNode().path())]
            self.fixture.carrier = self.fixture.nodes[program.ROLE]
            self.fixture.nodes['instance_source'].geometry = self.component.native_geometry

    def refused(self, callback):
        return self.component.refused(callback)

    def test_capture_requires_registration_and_is_bounded_deep_json(self):
        self.refused(self.checkpoint)
        token = self.component.begin()
        self.refused(self.checkpoint)
        self.registry.end(token, False)
        self.initialize(commit=False)
        checkpoint = self.checkpoint()
        self.assertEqual(checkpoint['schema'], 'bridge.geometry-registry-checkpoint/1')
        self.assertEqual(json.loads(json.dumps(checkpoint)), checkpoint)
        self.assertEqual([item['parm'] for item in checkpoint['parameters']], [*program.GATES, 'snippet'])
        checkpoint['manifest'].clear()
        checkpoint['basis']['content_sha256'] = '0' * 64
        self.assertTrue(self.checkpoint()['manifest'])
        self.assertNotEqual(self.checkpoint()['basis']['content_sha256'], '0' * 64)

    def test_current_cohort_cannot_be_replaced_even_with_authority(self):
        self.initialize()
        checkpoint = self.checkpoint()
        self.authorize(checkpoint)
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))

    def test_authorized_epoch_reopen_preserves_selected_value_without_writes(self):
        self.initialize(value=3)
        checkpoint = self.checkpoint()
        self.migrate()
        self.authorize(checkpoint)
        self.fixture.set_calls.clear()
        token = self.registry.reopen(self.roles, self.pack, checkpoint)
        self.registry.end(token, True)
        observed = self.fixture.host.observations(self.roles, self.pack)
        result = program.control_readback(self.fixture.version, observed['context'], observed['parameters'])
        self.assertEqual(result['value'], 3)
        self.assertEqual(result['evidence_scope'], 'parameters_only')
        self.assertFalse(self.fixture.set_calls)

    def test_new_producer_and_node_sessions_recover_both_builds_without_initialize(self):
        for version in program.VERSIONS:
            with self.subTest(version=version):
                self.component.cleanup_cohorts()
                self.fixture.version = version
                self.fixture.hou.applicationVersionString = lambda: version
                self.fixture.identity['version'] = version
                self.component.addon._TASK_HOST_IDENTITY = self.fixture.identity
                self.component.addon._root_lease_issue(self.fixture.root, self.fixture.task, 'sop')
                self.component.document['native_version'] = version
                self.component.params = self.component.write_input()
                self.fixture.carrier.userdata.clear()
                self.fixture.carrier.parameters['snippet'].value = ''
                self.initialize(value=2)
                checkpoint = self.checkpoint()
                self.component.cleanup_cohorts()
                with patch.object(runtime.os, 'getpid', return_value=checkpoint['binding']['host_identity']['pid'] + 1):
                    self.migrate(replace_nodes=True, pid=runtime.os.getpid())
                    self.authorize(checkpoint)
                    self.fixture.set_calls.clear()
                    with patch.object(self.fixture.host, 'initialize', side_effect=AssertionError('reinitialization')):
                        token = self.registry.reopen(self.roles, self.pack, checkpoint)
                        self.registry.end(token, True)
                    self.assertEqual(self.checkpoint()['basis'], checkpoint['basis'])
                    self.assertEqual(self.checkpoint()['parameters'], checkpoint['parameters'])
                    self.assertFalse(self.fixture.set_calls)

    def test_authority_missing_nonliteral_true_or_mutation_cannot_restore(self):
        self.initialize()
        checkpoint = self.checkpoint()
        self.migrate()
        old = dict(runtime._COHORTS)
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        for answer in (False, None, 1, 'true'):
            self.host['_fx_geometry_reopen_authority'] = lambda *args: answer
            self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
            self.assertEqual(runtime._COHORTS, old)
        def mutate(roles, pack, value):
            value['basis'].clear()
            return True
        self.host['_fx_geometry_reopen_authority'] = mutate
        token = self.registry.reopen(self.roles, self.pack, checkpoint)
        self.registry.end(token, False)
        self.assertEqual(runtime._COHORTS, old)

    def test_active_old_transaction_and_foreign_pack_roles_record_refused(self):
        self.initialize()
        checkpoint = self.checkpoint()
        active = self.component.begin(fresh=set())
        self.migrate()
        self.authorize(checkpoint)
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.registry.end(active, False)
        for field, changed in [('roles', dict(self.roles, instance_source='/obj/foreign/source')),
                               ('pack_sha256', '0' * 64),
                               ('record', dict(checkpoint['record'], task_id='foreign-task')),
                               ('binding', dict(checkpoint['binding'], task_root='/obj/foreign'))]:
            with self.subTest(field=field):
                altered = dict(checkpoint, **{field: changed})
                self.host['_fx_geometry_reopen_authority'] = lambda *args: True
                self.refused(lambda: self.registry.reopen(self.roles, self.pack, altered))

    def test_rollback_restores_only_stale_entry_and_preserves_unrelated_cohorts(self):
        self.initialize()
        checkpoint = self.checkpoint()
        old = dict(runtime._COHORTS)
        sentinel = dict(next(iter(old.values())), host={})
        runtime._COHORTS['checkpoint-unrelated-test'] = sentinel
        self.addCleanup(runtime._COHORTS.pop, 'checkpoint-unrelated-test', None)
        self.migrate()
        self.authorize(checkpoint)
        token = self.registry.reopen(self.roles, self.pack, checkpoint)
        self.registry.end(token, False)
        self.assertEqual({key: value for key, value in runtime._COHORTS.items()
                          if value['host'] is self.host}, old)
        self.assertIs(runtime._COHORTS['checkpoint-unrelated-test'], sentinel)
        self.refused(self.checkpoint)
        token = self.registry.reopen(self.roles, self.pack, checkpoint)
        self.registry.end(token, True)
        self.assertIs(runtime._COHORTS['checkpoint-unrelated-test'], sentinel)

    def test_input_geometry_basis_program_gates_and_drivers_are_revalidated(self):
        self.initialize(value=3)
        checkpoint = self.checkpoint()
        self.migrate()
        self.authorize(checkpoint)
        old = dict(runtime._COHORTS)
        carrier = self.fixture.carrier
        for name, field, value in [('snippet', 'value', 'foreign();'),
                                    ('class', 'value', 0), ('group', 'value', 'foreign'),
                                    ('vex_precision', 'value', '32'),
                                    ('snippet', 'driver', 'ch("foreign")'),
                                    ('group', 'keys', (object(),))]:
            with self.subTest(name=name, field=field):
                parameter = carrier.parameters[name]
                before = getattr(parameter, field)
                setattr(parameter, field, value)
                self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
                setattr(parameter, field, before)
                self.assertEqual(runtime._COHORTS, old)
                self.assertFalse(any(item['entry']['host'] is self.host for item in runtime._TRANSACTIONS.values()))
        for key in (runtime._BASIS_KEY, runtime._REGISTRATION_KEY):
            raw = carrier.userData(key)
            carrier.setUserData(key, '{}')
            self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
            carrier.setUserData(key, raw)
            self.assertEqual(runtime._COHORTS, old)
        original_geometry = copy.deepcopy(self.fixture.source)
        self.fixture.source['point_attributes']['P']['values'][0][0] += .1
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.fixture.source = original_geometry
        self.component.path.write_bytes(b'changed frozen input')
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.assertEqual(runtime._COHORTS, old)

    def test_checkpoint_shape_budget_and_extra_fields_refused(self):
        self.initialize()
        checkpoint = self.checkpoint()
        self.migrate()
        self.host['_fx_geometry_reopen_authority'] = lambda *args: True
        for changed in (dict(checkpoint, extra=True), dict(checkpoint, schema='foreign'),
                        dict(checkpoint, parameters=list(reversed(checkpoint['parameters']))),
                        dict(checkpoint, basis={'padding': 'x' * runtime.MAX_CHECKPOINT_BYTES}),
                        dict(checkpoint, record={'nonfinite': float('nan')})):
            self.refused(lambda: self.registry.reopen(self.roles, self.pack, changed))

    def test_reopen_readback_exception_restores_old_entry_and_cleans_token(self):
        self.initialize()
        checkpoint = self.checkpoint()
        old = dict(runtime._COHORTS)
        self.migrate()
        self.authorize(checkpoint)
        with patch.object(self.component.source, 'geometry', side_effect=RuntimeError('private secret')):
            error = self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.assertNotIn('private secret', str(error))
        self.assertEqual(runtime._COHORTS, old)
        self.assertFalse(any(item['entry']['host'] is self.host for item in runtime._TRANSACTIONS.values()))

    def test_node_replacement_with_same_identity_requires_explicit_scope(self):
        self.initialize(value=1)
        checkpoint = self.checkpoint()
        identity = copy.deepcopy(self.component.addon._TASK_HOST_IDENTITY)
        epoch = self.component.addon._BRIDGE_SCENE_STATE.scene_epoch
        self.migrate(replace_nodes=True)
        self.component.addon._TASK_HOST_IDENTITY = identity
        self.component.addon._BRIDGE_SCENE_STATE.scene_epoch = epoch
        self.component.addon._root_lease_issue(self.fixture.root, self.fixture.task, 'sop')
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.authorize(checkpoint)
        token = self.registry.reopen(self.roles, self.pack, checkpoint)
        self.registry.end(token, True)
        self.assertEqual(self.checkpoint()['parameters'], checkpoint['parameters'])

    def test_authority_revocation_before_return_cleans_temporary_entry(self):
        self.initialize()
        checkpoint = self.checkpoint()
        old = dict(runtime._COHORTS)
        self.migrate()
        calls = []
        def authorize(*args):
            calls.append(True)
            return len(calls) == 1
        self.host['_fx_geometry_reopen_authority'] = authorize
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.assertEqual(runtime._COHORTS, old)
        self.assertFalse(any(item['entry']['host'] is self.host for item in runtime._TRANSACTIONS.values()))

    def test_identity_drift_during_rest_read_cannot_publish_recovery(self):
        self.initialize()
        checkpoint = self.checkpoint()
        old = dict(runtime._COHORTS)
        self.migrate()
        self.authorize(checkpoint)
        original = self.component.addon._rehash_frozen_input_manifest
        def rehash(manifest):
            result = original(manifest)
            self.component.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'changed-during-rehash'
            return result
        with patch.object(self.component.addon, '_rehash_frozen_input_manifest', rehash):
            self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.assertEqual(runtime._COHORTS, old)

    def test_late_authority_callback_mutation_cannot_escape_readback(self):
        self.initialize()
        checkpoint = self.checkpoint()
        old = dict(runtime._COHORTS)
        self.migrate()
        calls = []
        def authorize(*args):
            calls.append(True)
            if len(calls) == 2:
                self.fixture.carrier.parameters['snippet'].value = 'foreign();'
            return True
        self.host['_fx_geometry_reopen_authority'] = authorize
        self.refused(lambda: self.registry.reopen(self.roles, self.pack, checkpoint))
        self.assertEqual(runtime._COHORTS, old)
        self.assertFalse(any(item['entry']['host'] is self.host for item in runtime._TRANSACTIONS.values()))

    def test_capture_bounds_userdata_before_parsing(self):
        self.initialize()
        self.fixture.carrier.setUserData(runtime._BASIS_KEY, ' ' * (runtime.MAX_REST_BYTES + 1))
        error = self.refused(self.checkpoint)
        self.assertEqual(error.code, 'GEOMETRY_CHECKPOINT_INVALID')

    def test_commit_revalidates_actual_native_state_and_caller_can_rollback(self):
        self.initialize()
        checkpoint = self.checkpoint()
        old = dict(runtime._COHORTS)
        self.migrate()
        self.authorize(checkpoint)
        token = self.registry.reopen(self.roles, self.pack, checkpoint)
        self.fixture.carrier.parameters['snippet'].value = 'foreign();'
        self.refused(lambda: self.registry.end(token, True))
        self.registry.end(token, False)
        self.assertEqual(runtime._COHORTS, old)
