"""Focused PP-01/02/03 checks with real addon code and bottom HOM fixtures.

No DCC, facade results, producer receipts, or domain validation is substituted.
Temporary software state stays under the assigned review-tests output directory.
"""
from contextlib import contextmanager
import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_particle_ocean_geometry_domains as particles
from houdini_bridge import native_particle_size_host as size_host
from houdini_bridge import native_pyro_domains as pyro
from houdini_bridge import native_pyro_height_host as height_host
from houdini_bridge import native_rbd_controls_host as rbd_host
from vfx_pipeline.workbuddy_assembly import software_host_client
from test_native_particle_size_host import NativeGeometry, NativeHostFixture
import test_native_pyro_height_program as pyro_fixture


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'outputs/all-domain-20261009/review-tests'
ADDON = ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py'


class NativeCandidateReviewRepairTests(unittest.TestCase):
    @contextmanager
    def isolated_state(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='hom-', dir=OUTPUT) as temporary:
            directory = Path(temporary)
            with patch.dict(sys.modules), patch.dict(os.environ, {
                'BRIDGE_SKILLS_STATE_ROOT': str(directory / 'state'),
                'HOUDINI_BRIDGE_STATE_DIR': str(directory / 'houdini'),
                'BRIDGE_SKILLS_SCHEDULER_ROOT': str(directory / 'scheduler'),
            }):
                yield directory

    @contextmanager
    def pyro_graph(self, version=pyro.SUPPORTED_VERSIONS[0]):
        with self.isolated_state() as directory:
            baseline_tokens = set(height_host._SNAPSHOTS)
            host, addon, hou, roles, pack, vertices = pyro_fixture.NativePyroHeightHostTests().make_host(directory, version)
            pack.update(controls=pyro.control_contract(pyro.FIRE, version),
                        shared_render_schema='bridge.native-render-domains/1')
            params = {'task_id': 'pyro-height-task', 'constraints': {'fx': {
                'domain_pack': pyro.FIRE, 'run_mode': 'diagnose', 'frames': [1, 2],
                'pyro_height_basis': {'h_base': 5., 'axis': [0., 1., 0.],
                    'source_input': copy.deepcopy(pyro_fixture.SOURCE_INPUT), 'input_version': 'v1',
                    'basis_input_sha256': hashlib.sha256(b'review-source-input').hexdigest()},
            }}, 'render': {'frame_range': {'start': 1, 'end': 2, 'step': 1}}}
            try:
                host.initialize(params, roles, pack, set(roles))
                root = hou.node(host.binding(roles, pack)['task_root'])
                addon._fx_store_manifest(root, {'task_id': params['task_id'], 'domain_pack': pyro.FIRE,
                    'execution_root': root.path(), 'nodes': roles, 'revision': 1})
                yield host, addon, hou, roles, pack, params, root
            finally:
                for token in set(height_host._SNAPSHOTS) - baseline_tokens:
                    original = height_host._SNAPSHOTS[token]
                    host.release_snapshot({'token': token, 'binding': original['binding']})

    def scalar_item(self, addon, node, name, value):
        parameter = addon._resolve_parm_target(node, [name])
        return {'name': name, 'node': node, 'parm': parameter,
                'snapshot': addon._snapshot_parm_state(parameter), 'value': value}

    @contextmanager
    def particle_graph(self, version):
        with self.isolated_state() as directory:
            client, addon = software_host_client(ADDON, directory / 'host')
            native = pyro_fixture.load_module('review_native_schema', ROOT / 'tools/native_schema_test_boundary.py')
            api = pyro_fixture.load_module('review_render_api', ROOT / 'tools/software_render_api_boundary.py')
            interfaces, states, ports = api.interface_profiles(ROOT, version)
            native.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', version,
                instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
            hou = sys.modules['hou']
            api.install_stage_api(hou)
            task_id = 'review-particle-task'
            addon._TASK_HOST_IDENTITY = dict(addon._host_identity(), task_id=task_id,
                pid=os.getpid(), launch_nonce='review-bottom-hom', version=version,
                plugin_build=addon._FX_LOADED_ADDON_SHA256)
            params = {'task_id': task_id, 'constraints': {'fx': {
                'domain_pack': particles.PARTICLES, 'run_mode': 'diagnose', 'frames': [1, 2],
                'particle_size_basis': {'size': .05, 'task_seed': 37},
            }}, 'render': {'frame_range': {'start': 1, 'end': 2, 'step': 1}}}
            roles = client.call('agent.fx.build_preview', params)['scene_manifest']['nodes']
            pack_id, pack = addon._fx_pack(params)
            fixture = NativeHostFixture(version)
            node_class = type(hou.node(roles['particle_size']))
            original_geometry = node_class.geometry
            particle_node = hou.node(roles['particle_size'])

            def geometry(node, output_index=0):
                role = next((role for role in size_host.GEOMETRY_ROLES if roles[role] == node.path()), None)
                if role is None:
                    return original_geometry(node, output_index=output_index)
                if output_index != 0:
                    raise AssertionError('P02 fixture only supplies output zero')
                for name in fixture.parameters:
                    fixture.parameters[name].value = addon._fx_planned_observation(particle_node, name)['value']
                return NativeGeometry(fixture.geometry_fact(role))

            with patch.object(node_class, 'geometry', geometry):
                yield addon, hou, roles, pack, params

    def test_rollback_continues_after_particle_size_restore_error(self):
        with self.particle_graph(particles.VERSIONS[0]) as (addon, hou, roles, pack, params):
            drag = self.scalar_item(addon, hou.node(roles['drag']), 'airresist', .7)
            fixture = NativeHostFixture(particles.VERSIONS[0])
            descriptor = fixture.prepared({'size_variance': 50.})['native_write']
            node = hou.node(roles['particle_size'])
            particle = self.scalar_item(addon, node, 'singlevalue', .1)
            particle.update(name='size_variance', native_write=descriptor)
            addon._fx_particle_size_host().prepare(particle)
            addon._fx_write_planned_item(drag, roles, pack)
            node.parm('singlevalue').set(.1)
            bottom_parameter = hou.node(roles['particle_size']).parm('singlevalue')
            original_set = type(bottom_parameter).set
            restore_calls = []

            def fail_size_restore(parameter, value, **kwargs):
                restore_calls.append(parameter.path())
                if parameter.path() == bottom_parameter.path():
                    raise RuntimeError('injected bottom P02 restore failure')
                return original_set(parameter, value, **kwargs)

            with patch.object(type(bottom_parameter), 'set', fail_size_restore):
                errors = addon._fx_rollback_planned_items([drag, particle], [drag, particle], roles, pack)
            self.assertEqual(errors, ['size_variance:PARTICLE_SIZE_RESTORE_FAILED'])
            self.assertEqual(drag['parm'].eval(), drag['snapshot']['evaluated'])
            self.assertLess(restore_calls.index(bottom_parameter.path()), restore_calls.index(drag['parm'].path()))

    def test_rollback_reverse_order_continues_after_native_flip_rbd_error(self):
        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            solver = hou.node(roles['solver'])
            first = self.scalar_item(addon, solver, 'tempcooling', 2.)
            last = self.scalar_item(addon, solver, 'flames_lifespan', 3.)
            middle = self.scalar_item(addon, hou.node(roles['source_control']), 'snippet', 'temporary source')
            middle['node'].setUserData(rbd_host.PROGRAM_KEY, 'original registration')
            addon._fx_rbd_velocity_host().prepare(middle)
            for item in (first, middle, last):
                addon._set_parm_verified(item['parm'], item['value'])
            middle['node'].setUserData(rbd_host.PROGRAM_KEY, 'changed registration')
            node_class = type(middle['node'])
            original_userdata = node_class.setUserData
            parameter_class = type(solver.parm('tempcooling'))
            original_set = parameter_class.set
            restore_order = []

            def lose_userdata_write(node, key, value):
                if node is middle['node'] and key == rbd_host.PROGRAM_KEY:
                    return
                return original_userdata(node, key, value)

            def record_set(parameter, value, **kwargs):
                if parameter.path() in {item['parm'].path() for item in (first, middle, last)}:
                    restore_order.append(parameter.path())
                return original_set(parameter, value, **kwargs)

            with patch.object(node_class, 'setUserData', lose_userdata_write), patch.object(parameter_class, 'set', record_set):
                errors = addon._fx_rollback_planned_items([first, middle, last], [first, middle, last], roles, pack)
            self.assertEqual(errors, ['snippet:PARAMETER_RESTORE_MISMATCH'])
            self.assertEqual(restore_order, [item['parm'].path() for item in (last, middle, first)])
            self.assertEqual(first['parm'].eval(), first['snapshot']['evaluated'])
            self.assertEqual(last['parm'].eval(), last['snapshot']['evaluated'])
            self.assertEqual(middle['node'].userData(rbd_host.PROGRAM_KEY), 'changed registration')

    def test_rollback_releases_unattempted_pyro_token_and_keeps_failed_restore_token(self):
        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            baseline_tokens = set(height_host._SNAPSHOTS)
            attempted = addon._fx_planned_domain_prepared(pyro.FIRE, {'flame_height': -2.}, roles, pack)[0]
            unattempted = addon._fx_planned_domain_prepared(pyro.FIRE, {'flame_height': 2.}, roles, pack)[0]
            addon._fx_write_planned_item(attempted, roles, pack)
            attempted_snapshot = attempted['pyro_height_candidate']['snapshot']
            unused_snapshot = unattempted['pyro_height_candidate']['snapshot']
            scalar = self.scalar_item(addon, hou.node(roles['solver']), 'tempcooling', 2.)
            addon._fx_write_planned_item(scalar, roles, pack)
            snippet = hou.node(roles['flame_height']).parm('snippet')
            original_set = type(snippet).set

            def fail_restore(parameter, value, **kwargs):
                if parameter.path() == snippet.path():
                    raise RuntimeError('injected bottom A01 restore failure')
                return original_set(parameter, value, **kwargs)

            with patch.object(type(snippet), 'set', fail_restore):
                errors = addon._fx_rollback_planned_items([scalar, attempted], [scalar, attempted, unattempted], roles, pack)
            self.assertEqual(errors, ['flame_height:PARAMETER_RESTORE_FAILED'])
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens | {attempted_snapshot['token']})
            self.assertNotIn(unused_snapshot['token'], height_host._SNAPSHOTS)
            self.assertEqual(scalar['parm'].eval(), scalar['snapshot']['evaluated'])
            self.assertEqual(host.readback(roles, pack)['value'], -2.)
            self.assertEqual(addon._fx_rollback_planned_items([attempted], [attempted], roles, pack), [])
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)
            self.assertEqual(host.readback(roles, pack)['value'], 0.)

    def test_registered_particle_rebuild_preserves_random_and_changed_constant_state(self):
        cases = ({'size': .08, 'size_variance': 50.}, {'size': .09, 'size_variance': 0.})
        for version, changes in ((version, changes) for version in particles.VERSIONS for changes in cases):
            with self.subTest(version=version, changes=changes), self.particle_graph(version) as (addon, hou, roles, pack, params):
                node = hou.node(roles['particle_size'])
                basis_before = node.userData(size_host.BASIS_KEY)
                fixture = NativeHostFixture(version)
                item = fixture.prepared(changes)
                fixture.host.write(item, fixture.roles, fixture.pack)
                node.parm('valuetype').set('const')
                node.parm('singlevalue').set(fixture.parameters['singlevalue'].eval())
                if changes['size_variance']:
                    node.parm('valuetype').set('rand')
                    for name in ('randmethod', 'randattrib', 'rangemethod', 'distribinrange',
                                 'enablestepping', 'randomseed', 'minvalue', 'rangevalue'):
                        node.parm(name).set(fixture.parameters[name].eval())
                state_before = {name: addon._snapshot_parm_state(addon._resolve_parm_target(node, [name]),
                                capture_extrapolation=True) for name in size_host.PARAMETERS}
                original_set = type(node.parm('valuetype')).set
                size_writes = []

                def record_set(parameter, value, **kwargs):
                    if parameter.node() is node:
                        size_writes.append((parameter.name(), value))
                    return original_set(parameter, value, **kwargs)

                with patch.object(type(node.parm('valuetype')), 'set', record_set):
                    result = addon._fx_initialize_particle_ocean_geometry_domain(params, roles, pack, set())
                self.assertEqual(size_writes, [])
                self.assertEqual(node.userData(size_host.BASIS_KEY), basis_before)
                self.assertEqual({name: addon._snapshot_parm_state(addon._resolve_parm_target(node, [name]),
                                 capture_extrapolation=True) for name in size_host.PARAMETERS}, state_before)
                self.assertIn('particle_size_preserved', result)
                observed = addon._fx_particle_size_host().observations(roles, pack)
                mode = observed['particle_size', 'valuetype']['value']
                self.assertEqual(mode, 'rand' if changes['size_variance'] else 'const')

    def test_feedback_manifest_persistence_failure_restores_parameters_and_releases_pyro_token(self):
        from dcc_task_runtime import platform_support

        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            baseline_tokens = set(height_host._SNAPSHOTS)
            changes = {'cooling_rate': 2., 'flame_height': -2.}
            state_path = addon._fx_state_path(params['task_id'])
            before_bytes = state_path.read_bytes()
            before_manifest = root.userData('bridge_fx_manifest_v1')
            cooling = hou.node(roles['solver']).parm('tempcooling')
            before_cooling = cooling.eval()
            original_atomic_write = platform_support.atomic_write
            failed = []

            def fail_after_write(path, *args, **kwargs):
                result = original_atomic_write(path, *args, **kwargs)
                if Path(path) == state_path and not failed:
                    failed.append(str(path))
                    raise OSError('injected sidecar persistence failure after write')
                return result

            with patch.object(platform_support, 'atomic_write', fail_after_write):
                with self.assertRaises(addon.BridgeCommandError) as error:
                    addon._fx_apply_candidate_unfenced(params, pyro.FIRE, pack, changes)
            self.assertEqual(error.exception.code, 'CANDIDATE_PERSIST_FAILED')
            self.assertEqual(failed, [str(state_path)])
            self.assertEqual(state_path.read_bytes(), before_bytes)
            self.assertEqual(root.userData('bridge_fx_manifest_v1'), before_manifest)
            self.assertEqual(cooling.eval(), before_cooling)
            self.assertEqual(host.readback(roles, pack)['value'], 0.)
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)

    def test_feedback_prewrite_persistence_snapshot_failure_does_not_allocate_pyro_token(self):
        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            baseline_tokens = set(height_host._SNAPSHOTS)
            state_path = addon._fx_state_path(params['task_id'])
            original_read = Path.read_bytes
            reads = []

            def fail_read(path):
                if path == state_path:
                    reads.append(set(height_host._SNAPSHOTS))
                    raise OSError('injected persistence snapshot read failure')
                return original_read(path)

            with patch.object(Path, 'read_bytes', fail_read), self.assertRaises(addon.BridgeCommandError) as error:
                addon._fx_apply_candidate_unfenced(params, pyro.FIRE, pack, {'flame_height': -2.})
            self.assertEqual(error.exception.code, 'CANDIDATE_PERSIST_SNAPSHOT_FAILED')
            self.assertEqual(reads, [baseline_tokens])
            self.assertEqual(host.readback(roles, pack)['value'], 0.)
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)

    def test_domain_preparation_failure_after_pyro_allocation_releases_token(self):
        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            baseline_tokens = set(height_host._SNAPSHOTS)
            solver = hou.node(roles['solver'])
            original_path = type(solver).path
            allocated_at_failure = []

            def fail_after_allocation(node):
                if node is solver and set(height_host._SNAPSHOTS) != baseline_tokens:
                    allocated_at_failure.extend(set(height_host._SNAPSHOTS) - baseline_tokens)
                    raise RuntimeError('injected bottom path failure after A01 prepare')
                return original_path(node)

            before_manifest = root.userData('bridge_fx_manifest_v1')
            before_bytes = addon._fx_state_path(params['task_id']).read_bytes()
            with patch.object(type(solver), 'path', fail_after_allocation):
                with self.assertRaisesRegex(addon.BridgeCommandError, 'after A01 prepare'):
                    addon._fx_planned_domain_prepared(pyro.FIRE, {'flame_height': -2., 'cooling_rate': 2.}, roles, pack)
            self.assertEqual(len(allocated_at_failure), 1)
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)
            self.assertEqual(host.readback(roles, pack)['value'], 0.)
            self.assertEqual(root.userData('bridge_fx_manifest_v1'), before_manifest)
            self.assertEqual(addon._fx_state_path(params['task_id']).read_bytes(), before_bytes)

    def pyro_native_state(self, addon, hou, roles, params, root):
        solver = hou.node(roles['solver'])
        mask = hou.node(roles['flame_height'])
        parameters = [(solver, 'tempcooling')] + [(mask, name) for name in (*height_host.program.GATES, 'snippet')]
        return {
            'parameters': {(node.path(), name): addon._snapshot_parm_state(addon._resolve_parm_target(node, [name]))
                           for node, name in parameters},
            'mask_userdata': mask.userDataDict(),
            'root_userdata': root.userDataDict(),
            'sidecar': addon._fx_state_path(params['task_id']).read_bytes(),
        }

    def test_feedback_undo_constructor_enter_and_exit_failures_restore_all_state(self):
        for stage in ('constructor', 'enter', 'exit'):
            with self.subTest(stage=stage), self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
                baseline_tokens = set(height_host._SNAPSHOTS)
                before = self.pyro_native_state(addon, hou, roles, params, root)
                failures = []
                test_case = self

                def fail(where):
                    if where == stage:
                        failures.append(where)
                        test_case.assertEqual(len(set(height_host._SNAPSHOTS) - baseline_tokens), 1)
                        if stage == 'exit':
                            test_case.assertEqual(host.readback(roles, pack)['value'], -2.)
                            test_case.assertEqual(hou.node(roles['solver']).parm('tempcooling').eval(), 2.)
                            test_case.assertNotEqual(hou.node(roles['flame_height']).userDataDict(), before['mask_userdata'])
                            test_case.assertEqual(root.userDataDict(), before['root_userdata'])
                        raise RuntimeError('injected HOM undo ' + where + ' failure')

                class FaultGroup:
                    def __init__(self, label):
                        fail('constructor')

                    def __enter__(self):
                        fail('enter')
                        return self

                    def __exit__(self, error_type, error, traceback):
                        test_case.assertIsNone(error_type)
                        fail('exit')
                        return False

                with patch.object(hou, 'undos', SimpleNamespace(group=FaultGroup)):
                    with self.assertRaisesRegex(RuntimeError, 'injected HOM undo ' + stage + ' failure'):
                        addon._fx_apply_candidate_unfenced(params, pyro.FIRE, pack,
                            {'cooling_rate': 2., 'flame_height': -2.})
                self.assertEqual(failures, [stage])
                self.assertEqual(self.pyro_native_state(addon, hou, roles, params, root), before)
                self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)

    def test_feedback_undo_exit_restore_failure_keeps_original_pyro_token_for_retry(self):
        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            baseline_tokens = set(height_host._SNAPSHOTS)
            before = self.pyro_native_state(addon, hou, roles, params, root)
            mask = hou.node(roles['flame_height'])
            snippet = mask.parm('snippet')
            original_set = type(snippet).set
            exiting = []
            snapshot_at_exit = []
            test_case = self

            class FaultGroup:
                def __init__(self, label):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, error_type, error, traceback):
                    test_case.assertIsNone(error_type)
                    test_case.assertEqual(host.readback(roles, pack)['value'], -2.)
                    tokens = set(height_host._SNAPSHOTS) - baseline_tokens
                    test_case.assertEqual(len(tokens), 1)
                    token = next(iter(tokens))
                    snapshot_at_exit.append({'token': token, 'binding': height_host._SNAPSHOTS[token]['binding']})
                    exiting.append(True)
                    raise RuntimeError('injected HOM undo exit failure')

            def fail_restore(parameter, value, **kwargs):
                if exiting and parameter.path() == snippet.path():
                    raise RuntimeError('injected A01 restore failure after undo exit')
                return original_set(parameter, value, **kwargs)

            with patch.object(hou, 'undos', SimpleNamespace(group=FaultGroup)), patch.object(type(snippet), 'set', fail_restore):
                with self.assertRaises(addon.BridgeCommandError) as error:
                    addon._fx_apply_candidate_unfenced(params, pyro.FIRE, pack,
                        {'cooling_rate': 2., 'flame_height': -2.})
            self.assertEqual(error.exception.code, 'CANDIDATE_ROLLBACK_FAILED')
            self.assertIn('flame_height:PARAMETER_RESTORE_FAILED', str(error.exception))
            self.assertEqual(len(snapshot_at_exit), 1)
            snapshot = snapshot_at_exit[0]
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens | {snapshot['token']})
            after = self.pyro_native_state(addon, hou, roles, params, root)
            self.assertEqual(after['sidecar'], before['sidecar'])
            self.assertEqual(after['root_userdata'], before['root_userdata'])
            self.assertEqual(hou.node(roles['solver']).parm('tempcooling').eval(),
                             before['parameters'][roles['solver'], 'tempcooling']['evaluated'])
            self.assertEqual(host.readback(roles, pack)['value'], -2.)
            host.restore(snapshot, roles, pack)
            host.release_snapshot(snapshot)
            self.assertEqual(self.pyro_native_state(addon, hou, roles, params, root), before)
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)

    def test_feedback_body_and_undo_exit_failures_do_not_restore_twice(self):
        """The setter and transaction restore once each; undo exit adds none."""
        with self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
            baseline_tokens = set(height_host._SNAPSHOTS)
            before = self.pyro_native_state(addon, hou, roles, params, root)
            cooling = hou.node(roles['solver']).parm('tempcooling')
            original_set = type(cooling).set
            writes = []
            test_case = self

            def fail_first_set(parameter, value, **kwargs):
                if parameter.path() == cooling.path():
                    writes.append(value)
                    if len(writes) == 1:
                        raise RuntimeError('injected candidate body setter failure')
                return original_set(parameter, value, **kwargs)

            class FaultGroup:
                def __init__(self, label):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, error_type, error, traceback):
                    test_case.assertIs(error_type, addon.BridgeCommandError)
                    test_case.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)
                    raise RuntimeError('injected undo exit after body failure')

            with patch.object(hou, 'undos', SimpleNamespace(group=FaultGroup)), patch.object(type(cooling), 'set', fail_first_set):
                with self.assertRaisesRegex(RuntimeError, 'undo exit after body failure'):
                    addon._fx_apply_candidate_unfenced(params, pyro.FIRE, pack,
                        {'cooling_rate': 2., 'flame_height': -2.})
            previous = before['parameters'][roles['solver'], 'tempcooling']['evaluated']
            self.assertEqual(writes, [2., previous, previous])
            self.assertEqual(self.pyro_native_state(addon, hou, roles, params, root), before)
            self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)

    def test_source_and_feedback_early_setter_failure_release_unattempted_pyro_token(self):
        for entry in ('source', 'feedback'):
            with self.subTest(entry=entry), self.pyro_graph() as (host, addon, hou, roles, pack, params, root):
                baseline_tokens = set(height_host._SNAPSHOTS)
                changes = {'cooling_rate': 2., 'flame_height': -2.}
                parameter = hou.node(roles['solver']).parm('tempcooling')
                before = parameter.eval()
                original_set = type(parameter).set
                failed = []

                def fail_once(target, value, **kwargs):
                    if target.path() == parameter.path() and not failed:
                        failed.append(target.path())
                        raise RuntimeError('injected first setter failure')
                    return original_set(target, value, **kwargs)

                with patch.object(type(parameter), 'set', fail_once), self.assertRaises(addon.BridgeCommandError):
                    if entry == 'source':
                        addon._fx_apply_source_plan_targets({'host_controls': changes}, roles, pack)
                    else:
                        addon._fx_apply_candidate_unfenced(params, pyro.FIRE, pack, changes)
                self.assertEqual(failed, [parameter.path()])
                self.assertEqual(parameter.eval(), before)
                self.assertEqual(host.readback(roles, pack)['value'], 0.)
                self.assertEqual(set(height_host._SNAPSHOTS), baseline_tokens)


if __name__ == '__main__':
    unittest.main()
