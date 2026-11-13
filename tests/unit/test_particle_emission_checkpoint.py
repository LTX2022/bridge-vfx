"""Trusted P01 checkpoint guards using bottom HOM state, without DCC execution."""
import copy
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import test_native_particle_emission_host as fixture_module
from houdini_bridge import native_particle_emission_host as host_module
from houdini_bridge import native_particle_emission_program as program
from houdini_bridge import native_particle_ocean_geometry_domains as core


class ParticleEmissionCheckpointTests(unittest.TestCase):
    def refused(self, callback, *args, **kwargs):
        with self.assertRaises((program.ParticleEmissionError, core.NativeParticleOceanGeometryDomainError)) as caught:
            callback(*args, **kwargs)
        return caught.exception.code

    def saved(self, version, percentage=37.):
        fixture = fixture_module.NativeEmissionFixture(version)
        fixture.initialize()
        fixture.applied(percentage, 2300.)
        return fixture, fixture.host.checkpoint(fixture.roles, fixture.pack)

    def loaded(self, source, checkpoint, *, new_process=True):
        fixture = fixture_module.NativeEmissionFixture(source.version)
        for role, node in source.nodes.items():
            for name, parameter in node.parameters.items():
                fixture.restore(fixture.nodes[role].parm(name), source.snapshot(parameter))
            fixture.nodes[role].native_session += 900
        if new_process:
            fixture.identity.update(pid=456, launch_nonce='p01-reopened-nonce',
                session_id='p01-reopened-session', process_generation='p01-reopened-generation', scene_epoch=2)
        fixture.current_frame = -24.5
        fixture.artifact_digest = fixture.expected_artifact_digest = 'verified-hip-digest'
        fixture.authority_calls = []
        frozen = copy.deepcopy(checkpoint)

        def authorize(roles, pack, value):
            fixture.authority_calls.append(copy.deepcopy(value))
            return (roles == source.roles and pack == source.pack and value == frozen
                    and fixture.artifact_digest == fixture.expected_artifact_digest)

        fixture.callbacks['_fx_particle_emission_reopen_authority'] = authorize
        fixture.write_calls.clear()
        return fixture

    def test_unregistered_checkpoint_refuses(self):
        for version in core.VERSIONS:
            fixture = fixture_module.NativeEmissionFixture(version)
            self.assertEqual(self.refused(fixture.host.checkpoint, fixture.roles, fixture.pack),
                             'PARTICLE_EMISSION_AUTHORITY_REQUIRED')

    def test_native_tuple_menu_facts_survive_json_checkpoint_reopen(self):
        def native_menu_facts(fixture):
            original = fixture.callbacks['_fx_planned_observation']
            def observe(*args, **kwargs):
                result = original(*args, **kwargs)
                result['menu_labels'] = ('explicit native menu',)
                return result
            fixture.callbacks['_fx_planned_observation'] = observe
        for version in core.VERSIONS:
            with self.subTest(version=version):
                source = fixture_module.NativeEmissionFixture(version)
                native_menu_facts(source)
                source.initialize()
                source.applied(45., 2300.)
                checkpoint = source.host.checkpoint(source.roles, source.pack)
                loaded = self.loaded(source, checkpoint)
                native_menu_facts(loaded)
                token = loaded.host.reopen(loaded.roles, loaded.pack, checkpoint)
                loaded.host.end(token, True)
                current = loaded.host.checkpoint(loaded.roles, loaded.pack)
                self.assertEqual({key: value for key, value in current.items() if key != 'identity'},
                                 {key: value for key, value in checkpoint.items() if key != 'identity'})

    def test_checkpoint_allows_verified_pending_write_and_fresh_build_scope(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                fixture = fixture_module.NativeEmissionFixture(version)
                with fixture.host.build_transaction('/obj/p01_api'):
                    fixture.initialize()
                    fresh = fixture.host.checkpoint(fixture.roles, fixture.pack)
                    self.assertEqual(fresh['percentage'], 0.)
                    self.assertEqual(set(fresh['binding']), {'task_id', 'task_root', 'native_version'})
                item = fixture.prepared(45., 2500.)
                fixture.host.write(item, fixture.roles, fixture.pack)
                checkpoint = fixture.host.checkpoint(fixture.roles, fixture.pack)
                self.assertEqual(checkpoint['percentage'], 45.)
                self.assertEqual(checkpoint['birth_rate'], 2500.)
                self.assertTrue(fixture.host.authority['snapshots'])
                fixture.nodes['emission'].parm('constantactivate').value = 0.
                self.refused(fixture.host.checkpoint, fixture.roles, fixture.pack)
                fixture.nodes['emission'].parm('constantactivate').value = 1.
                fixture.host.release(item)
                fixture.callbacks['_fx_particle_emission_reopen_authority'] = lambda *args: True
                token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
                fixture.host.end(token, True)
                committed = fixture.host.checkpoint(fixture.roles, fixture.pack)
                self.assertEqual(committed, checkpoint)
                self.assertNotIn('checkpoint_reopen', committed)

    def test_checkpoint_rejects_late_channel_evaluation_changes(self):
        for fault in ('gate', 'limits', 'node'):
            with self.subTest(fault=fault):
                fixture, _ = self.saved(core.VERSIONS[0])
                original = fixture.host._checkpoint_capture
                captures = []

                def late_capture(*args):
                    captures.append(True)
                    if len(captures) == 3:
                        evaluations = []

                        def late_eval():
                            evaluations.append(True)
                            if len(evaluations) == 2:
                                if fault == 'gate':
                                    fixture.nodes['emission'].parm('constantactivate').value = 0.
                                elif fault == 'limits':
                                    fixture.rate.native_maximum = 21000000.
                                else:
                                    fixture.nodes['solver'].bypassed = True

                        fixture.rate.eval_hook = late_eval
                    return original(*args)

                with patch.object(fixture.host, '_checkpoint_capture', side_effect=late_capture):
                    self.refused(fixture.host.checkpoint, fixture.roles, fixture.pack)

    def test_complete_checkpoint_is_frame_independent_and_copied(self):
        for version in core.VERSIONS:
            for percentage in (0., 37., 100.):
                with self.subTest(version=version, percentage=percentage):
                    fixture, checkpoint = self.saved(version, percentage)
                    self.assertEqual(checkpoint['schema'], host_module.CHECKPOINT_SCHEMA)
                    self.assertEqual(checkpoint['identity'], fixture.identity)
                    self.assertTrue(all('session_id' not in fact for fact in checkpoint['nodes'].values()))
                    self.assertFalse({'frame', 'time', 'actual_rate'} & set(checkpoint['native']))
                    for frame in (-50., 0., 1., 24.5, 130.):
                        fixture.current_frame = frame
                        self.assertEqual(fixture.host.checkpoint(fixture.roles, fixture.pack), checkpoint)
                    checkpoint['basis']['task_seed'] = 999
                    self.assertEqual(fixture.context()['basis']['task_seed'], 173)

    def test_new_identity_reopen_and_commit_never_write_or_apply(self):
        for version in core.VERSIONS:
            for percentage in (0., 37., 100.):
                with self.subTest(version=version, percentage=percentage):
                    source, checkpoint = self.saved(version, percentage)
                    fixture = self.loaded(source, checkpoint)
                    with ExitStack() as stack:
                        for node in fixture.nodes.values():
                            for parameter in node.parameters.values():
                                for method in ('set', 'setExpression', 'deleteAllKeyframes',
                                               'setKeyframes', 'setKeyframeExtrapolation'):
                                    stack.enter_context(patch.object(parameter, method,
                                        side_effect=AssertionError('reopen must not mutate native parameters')))
                        stack.enter_context(patch.object(fixture.host, 'initialize',
                            side_effect=AssertionError('reopen must not initialize')))
                        stack.enter_context(patch.object(fixture.host, 'write',
                            side_effect=AssertionError('reopen must not apply')))
                        token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
                        self.assertIsInstance(token, str)
                        self.assertIn('verified_new_PID_checkpoint_reopen',
                                      fixture.host.readback(fixture.roles, fixture.pack)['missing_evidence'])
                        fixture.current_frame = 78.25
                        fixture.host.end(token, True)
                        readback = fixture.host.readback(fixture.roles, fixture.pack)
                    self.assertEqual(readback['status'], 'BLOCKED')
                    self.assertEqual(readback['percentage'], percentage)
                    self.assertEqual(readback['birth_rate'], 2300.)
                    self.assertTrue(readback['checkpoint_reopen']['new_pid_and_nonce'])
                    self.assertFalse(readback['checkpoint_reopen']['native_writes'])
                    self.assertNotIn('verified_new_PID_checkpoint_reopen', readback['missing_evidence'])
                    self.assertIn('same_build_POP_substep_emission_integration', readback['missing_evidence'])
                    self.assertIn('real_host_new_PID_checkpoint_reopen', readback['missing_evidence'])
                    self.assertGreaterEqual(len(fixture.authority_calls), 4)
                    self.assertEqual(fixture.write_calls, [])
                    self.assertFalse(fixture.host.authority['reopens'])
                    self.refused(fixture.host.end, token, True)

    def test_same_process_commit_keeps_new_pid_gap(self):
        source, checkpoint = self.saved(core.VERSIONS[0])
        fixture = self.loaded(source, checkpoint, new_process=False)
        token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
        fixture.host.end(token, True)
        self.assertIn('verified_new_PID_checkpoint_reopen',
                      fixture.host.readback(fixture.roles, fixture.pack)['missing_evidence'])

    def test_private_authority_must_return_actual_true(self):
        for returned in (None, False, 1, 'true', {'verified': True}, 'missing'):
            with self.subTest(returned=returned):
                source, checkpoint = self.saved(core.VERSIONS[0])
                fixture = self.loaded(source, checkpoint)
                if returned == 'missing':
                    fixture.callbacks.pop('_fx_particle_emission_reopen_authority')
                else:
                    fixture.callbacks['_fx_particle_emission_reopen_authority'] = lambda *args: returned
                self.assertEqual(self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint),
                                 'PARTICLE_EMISSION_REOPEN_AUTHORITY_REQUIRED')
                self.assertFalse(fixture.host.authority['records'])
                self.assertFalse(fixture.host.authority['reopens'])
                self.assertEqual(fixture.write_calls, [])

    def test_old_identity_and_immutable_build_task_version_refuse(self):
        faults = {'pid': 0, 'launch_nonce': '', 'session_id': '', 'process_generation': '',
                  'scene_epoch': -1, 'plugin_build': 'e' * 64, 'task_id': 'foreign', 'version': '22.0.0'}
        for name, changed in faults.items():
            with self.subTest(name=name):
                source, checkpoint = self.saved(core.VERSIONS[0])
                fixture = self.loaded(source, checkpoint)
                checkpoint['identity'][name] = changed
                self.assertEqual(self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint),
                                 'PARTICLE_EMISSION_CHECKPOINT_INVALID')
                self.assertFalse(fixture.authority_calls)
                self.assertFalse(fixture.host.authority['records'])
        for fault in ('missing', 'extra'):
            source, checkpoint = self.saved(core.VERSIONS[0])
            fixture = self.loaded(source, checkpoint)
            if fault == 'missing':
                checkpoint['identity'].pop('session_id')
            else:
                checkpoint['identity']['foreign'] = 'unapproved'
            self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)

    def test_basis_seed_expression_and_schema_tampering_refuse(self):
        for fault in ('seed_digest', 'seed_rehashed', 'seed_zero_rehashed', 'fps_rehashed',
                      'root_rehashed', 'expression', 'schema', 'extra', 'missing'):
            with self.subTest(fault=fault):
                source, checkpoint = self.saved(core.VERSIONS[0], 0. if fault == 'seed_zero_rehashed' else 37.)
                fixture = self.loaded(source, checkpoint)
                if fault.startswith('seed'):
                    checkpoint['basis']['task_seed'] += 1
                elif fault == 'fps_rehashed':
                    checkpoint['basis']['fps'] = 25.
                elif fault == 'root_rehashed':
                    checkpoint['basis']['task_root'] = '/obj/foreign'
                    checkpoint['basis']['node_path'] = '/obj/foreign/simulation/emission'
                elif fault == 'expression':
                    checkpoint['expression'] = '2300.'
                elif fault == 'schema':
                    checkpoint['schema'] = 'foreign/1'
                elif fault == 'extra':
                    checkpoint['foreign'] = 1
                else:
                    checkpoint.pop('channel')
                if fault.endswith('rehashed'):
                    checkpoint['basis']['content_sha256'] = program._digest(
                        {name: value for name, value in checkpoint['basis'].items() if name != 'content_sha256'})
                self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)
                self.assertFalse(fixture.host.authority['records'])
                self.assertFalse(fixture.host.authority['reopens'])

    def test_actual_native_channels_gates_clocks_limits_and_nodes_are_exact(self):
        faults = ('expression', 'language', 'keys', 'extrapolation', 'foreign_reference',
                  'gate', 'gate_keys', 'probemit', 'seed', 'jitter', 'fps', 'offset',
                  'offset_channel', 'scale', 'solver_scale', 'limit', 'bypass', 'locked_node')
        for version in core.VERSIONS:
            for fault in faults:
                with self.subTest(version=version, fault=fault):
                    source, checkpoint = self.saved(version)
                    fixture = self.loaded(source, checkpoint)
                    if fault == 'expression':
                        fixture.rate.source = '2300.'
                    elif fault == 'language':
                        fixture.rate.language = fixture.hou.exprLanguage.Hscript
                    elif fault == 'keys':
                        fixture.rate.keys = ({'frame': 1., 'value': 2300.},)
                    elif fault == 'extrapolation':
                        fixture.rate.extrapolation = ('cycle', 'cycleoffset')
                    elif fault == 'foreign_reference':
                        fixture.rate.reference = fixture.nodes['emission'].parm('seed')
                    elif fault == 'gate':
                        fixture.nodes['emission'].parm('constantactivate').value = 0.
                    elif fault == 'gate_keys':
                        fixture.nodes['emission'].parm('constantactivate').keys = ({'frame': 1., 'value': 1.},)
                    elif fault in ('probemit', 'seed'):
                        fixture.nodes['emission'].parm(fault).value += 1
                    elif fault == 'jitter':
                        fixture.nodes['emission'].parm('jitterbirthtime').value = 'changed'
                    elif fault == 'fps':
                        fixture.current_fps = 25.
                    elif fault == 'offset':
                        fixture.nodes['simulation'].parm('native_offset_time').source = '1.'
                    elif fault == 'offset_channel':
                        fixture.nodes['simulation'].parm('native_offset_time').extrapolation = ('cycle', 'cycle')
                    elif fault == 'scale':
                        fixture.nodes['simulation'].parm('native_scale_time').value = 2.
                    elif fault == 'solver_scale':
                        fixture.nodes['solver'].parm('timescale').value = 2.
                    elif fault == 'limit':
                        fixture.rate.native_maximum = 21000000.
                    elif fault == 'bypass':
                        fixture.nodes['simulation'].bypassed = True
                    else:
                        fixture.nodes['emission'].editable = False
                    self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)
                    self.assertFalse(fixture.host.authority['records'])
                    self.assertFalse(fixture.host.authority['reopens'])
                    self.assertEqual(fixture.write_calls, [])

    def test_bounded_json_refuses_bytes_depth_values_cycles_and_nonfinite(self):
        nested = None
        for _ in range(34):
            nested = [nested]
        cycle = []
        cycle.append(cycle)
        faults = [('bytes', '中' * (host_module.MAX_CHECKPOINT_BYTES // 2)),
                  ('string', 'x' * (host_module.MAX_CHECKPOINT_BYTES + 1)),
                  ('depth', nested), ('cycle', cycle),
                  ('values', [None] * (host_module.MAX_CHECKPOINT_VALUES + 1)),
                  ('number', float('nan')), ('infinity', float('inf')),
                  ('integer', 1 << 4097), ('object', object()), ('key', {1: 'invalid'}),
                  ('encoding', '\ud800')]
        source, checkpoint = self.saved(core.VERSIONS[0])
        for fault, changed in faults:
            with self.subTest(fault=fault):
                fixture = self.loaded(source, checkpoint)
                supplied = dict(checkpoint, invalid=changed)
                self.refused(fixture.host.reopen, fixture.roles, fixture.pack, supplied)
                self.assertFalse(fixture.authority_calls)
                self.assertFalse(fixture.host.authority['records'])

    def test_authority_callbacks_cannot_replace_registration_or_change_native_facts(self):
        for fault in ('first_identity', 'first_gate', 'second_fps', 'second_cas', 'second_clear', 'second_artifact'):
            with self.subTest(fault=fault):
                source, checkpoint = self.saved(core.VERSIONS[0])
                fixture = self.loaded(source, checkpoint)
                original = fixture.callbacks['_fx_particle_emission_reopen_authority']
                calls = []
                foreign = {'foreign': True}

                def changed_authority(*args):
                    calls.append(True)
                    phase = 1 if fault.startswith('first') else 2
                    if len(calls) == phase:
                        if fault == 'first_identity':
                            fixture.identity['launch_nonce'] = 'changed-again'
                        elif fault == 'first_gate':
                            fixture.nodes['emission'].parm('constantactivate').value = 0.
                        elif fault == 'second_fps':
                            fixture.current_fps = 25.
                        elif fault == 'second_cas':
                            fixture.host.authority['records']['/obj/p01_api'] = foreign
                        elif fault == 'second_clear':
                            fixture.host.invalidate_scene()
                        else:
                            fixture.artifact_digest = 'changed-hip'
                    return original(*args)

                fixture.callbacks['_fx_particle_emission_reopen_authority'] = changed_authority
                self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)
                self.assertFalse(fixture.host.authority['reopens'])
                if fault == 'second_cas':
                    self.assertIs(fixture.host.authority['records']['/obj/p01_api'], foreign)
                else:
                    self.assertFalse(fixture.host.authority['records'])

    def test_abort_restores_exact_previous_record_and_preserves_successor(self):
        for fault in ('abort', 'authority', 'cas'):
            with self.subTest(fault=fault):
                fixture, checkpoint = self.saved(core.VERSIONS[0])
                root = '/obj/p01_api'
                previous = fixture.host.authority['records'][root]
                fixture.callbacks['_fx_particle_emission_reopen_authority'] = lambda *args: True
                token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
                foreign = {'successor': True}
                if fault == 'abort':
                    fixture.host.end(token, False)
                else:
                    if fault == 'authority':
                        fixture.callbacks['_fx_particle_emission_reopen_authority'] = lambda *args: False
                    else:
                        fixture.host.authority['records'][root] = foreign
                    self.refused(fixture.host.end, token, True)
                self.assertIs(fixture.host.authority['records'][root], foreign if fault == 'cas' else previous)
                self.assertFalse(fixture.host.authority['reopens'])
                if fault != 'cas':
                    self.assertEqual(fixture.context()['percentage'], 37.)

    def test_commit_rechecks_late_channels_context_identity_and_artifact(self):
        for fault in ('keys', 'extrapolation', 'gate', 'fps', 'identity', 'artifact', 'clear'):
            with self.subTest(fault=fault):
                source, checkpoint = self.saved(core.VERSIONS[0])
                fixture = self.loaded(source, checkpoint)
                token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
                original = fixture.callbacks['_fx_particle_emission_reopen_authority']

                def late_authority(*args):
                    if fault == 'keys':
                        fixture.rate.keys = ({'frame': 5., 'value': 2300.},)
                    elif fault == 'extrapolation':
                        fixture.rate.extrapolation = ('cycle', 'cycle')
                    elif fault == 'gate':
                        fixture.nodes['emission'].parm('constantactivate').value = 0.
                    elif fault == 'fps':
                        fixture.current_fps = 25.
                    elif fault == 'identity':
                        fixture.identity['scene_epoch'] += 1
                    elif fault == 'artifact':
                        fixture.artifact_digest = 'drifted'
                    else:
                        fixture.host.invalidate_scene()
                    return original(*args)

                fixture.callbacks['_fx_particle_emission_reopen_authority'] = late_authority
                self.refused(fixture.host.end, token, True)
                self.assertFalse(fixture.host.authority['records'])
                self.assertFalse(fixture.host.authority['reopens'])
                self.assertEqual(fixture.write_calls, [])

    def test_pending_write_build_and_reopen_are_exclusive(self):
        fixture, checkpoint = self.saved(core.VERSIONS[0])
        fixture.callbacks['_fx_particle_emission_reopen_authority'] = lambda *args: True
        item = fixture.prepared(20.)
        self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)
        fixture.host.release(item)
        with fixture.host.build_transaction('/obj/p01_api'):
            self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)
        token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
        self.refused(fixture.host.reopen, fixture.roles, fixture.pack, checkpoint)
        self.refused(fixture.initialize)
        self.refused(fixture.prepared, 20.)
        self.refused(fixture.host.build_transaction('/obj/p01_api').__enter__)
        fixture.host.end(token, False)

    def test_invalidate_clears_reopen_without_restoring_old_scene(self):
        fixture, checkpoint = self.saved(core.VERSIONS[0])
        fixture.callbacks['_fx_particle_emission_reopen_authority'] = lambda *args: True
        token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
        fixture.host.invalidate_scene()
        self.refused(fixture.host.end, token, False)
        self.assertFalse(fixture.host.authority['records'])
        self.assertFalse(fixture.host.authority['reopens'])

    def test_reopen_input_copy_token_types_and_transaction_budget(self):
        source, checkpoint = self.saved(core.VERSIONS[0])
        fixture = self.loaded(source, checkpoint)
        token = fixture.host.reopen(fixture.roles, fixture.pack, checkpoint)
        checkpoint['identity']['launch_nonce'] = 'caller-mutated'
        fixture.host.end(token, True)
        self.assertEqual(fixture.context()['checkpoint_reopen']['previous_identity']['launch_nonce'],
                         source.identity['launch_nonce'])
        for supplied_token, commit in ((None, True), ([], True), (token, 1), (token, 'true')):
            self.refused(fixture.host.end, supplied_token, commit)
        fresh = self.loaded(source, source.host.checkpoint(source.roles, source.pack))
        fresh.host.authority['reopens'].update({str(index): {'root': '/obj/foreign' + str(index)}
            for index in range(host_module.MAX_REOPEN_TRANSACTIONS)})
        self.assertEqual(self.refused(fresh.host.reopen, fresh.roles, fresh.pack,
            source.host.checkpoint(source.roles, source.pack)), 'PARTICLE_EMISSION_CHECKPOINT_BUDGET_EXCEEDED')


if __name__ == '__main__':
    unittest.main()
