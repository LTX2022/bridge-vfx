"""SW01/SW02 regression tests using production dispatch and explicit bottom API.

All host instances run in the test's Python PID. No DCC, simulation, renderer or
controlled worker is launched, including during save/reopen verification.
"""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from vfx_pipeline.workbuddy_assembly import software_host_client

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py'
TASK = 'swarm-regression'


def load_fixture(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = load_fixture('swarm_render_api', ROOT / 'tools/software_render_api_boundary.py')
fixture = load_fixture('swarm_api_fixture', ROOT / 'tests/helpers/swarm_api_fixture.py')


class NativeSwarmControlTests(unittest.TestCase):
    def make_host(self, tmp, version, instance):
        client, addon = software_host_client(ADDON, tmp / instance)
        native = load_fixture('swarm_native_api', ROOT / 'tools/native_schema_test_boundary.py')
        interfaces, states, ports = api.interface_profiles(ROOT, version)
        native.constrain_hou(
            ROOT / 'docs/native-basis/hda-interface-capture.json', version,
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports,
        )
        hou = sys.modules['hou']
        api.install_stage_api(hou)
        fixture.install_time_api(hou)
        addon._TASK_HOST_IDENTITY = dict(
            addon._host_identity(), task_id=TASK, pid=os.getpid(),
            launch_nonce=instance + '-' + tmp.name,
            plugin_build=addon._FX_LOADED_ADDON_SHA256, version=version,
        )
        return client, addon, hou, native

    def snapshot(self, hou, addon):
        nodes = {}
        for root in ('/obj', '/stage', '/mat'):
            for node in hou.node(root).allSubChildren():
                nodes[node.path()] = {
                    'data': node.userDataDict(),
                    'parms': {name: (parm.value, parm._native_state)
                              for name, parm in node.parms_dict.items()},
                    'inputs': [source.path() if source else None for source in node.inputs()],
                    'wires': [(wire.inputIndex(), wire.inputNode().path(), wire.outputIndex())
                              for wire in node.inputConnections()],
                }
        return copy.deepcopy({
            'nodes': nodes, 'manifest': addon._fx_state_path(TASK).read_bytes(),
            'frame': hou.frame(),
        })

    def run_case(self, version, case):
        with tempfile.TemporaryDirectory(prefix='bridge-swarm-') as directory, patch.dict(sys.modules):
            tmp = Path(directory)
            environment = {
                'BRIDGE_SKILLS_STATE_ROOT': str(tmp / 'state'),
                'HOUDINI_BRIDGE_STATE_DIR': str(tmp / 'houdini'),
                'BRIDGE_SKILLS_SCHEDULER_ROOT': str(tmp / 'scheduler'),
            }
            with patch.dict(os.environ, environment):
                client, addon, hou, native = self.make_host(tmp, version, 'first-api')
                params = {
                    'task_id': TASK,
                    'constraints': {'fx': {
                        'domain_pack': 'swarm_flocking_v1', 'run_mode': 'diagnose',
                        'frames': [1, 2], 'swarm_basis': fixture.swarm_basis(),
                    }},
                    'render': {'frame_range': {'start': 1, 'end': 2, 'step': 1}},
                }
                built = client.call('agent.fx.build_preview', params)
                roles = built['scene_manifest']['nodes']
                if case == 'presolve':
                    self.check_presolve(client, addon, hou, params, roles)
                else:
                    self.check_bindgeo(client, addon, hou, native, params, roles)
                    self.check_reopen(tmp, version, client, addon, hou, params, built)

    def check_presolve(self, client, addon, hou, params, roles):
        self.assertFalse(addon._fx_manifest(TASK)[1].get('candidate_patch'))
        self.assertNotIn('source_plan', params['constraints']['fx'])
        self.assertNotIn('domain_control_plan', params['constraints']['fx'])
        solver, noise = hou.node(roles['solver']), hou.node(roles['noise_force'])
        foreign = noise.parent().createNode('popforce', 'foreign_force')
        for source, output in ((foreign, 0), (noise, 1)):
            with self.subTest(source=source.path(), output=output):
                solver.setInput(1, source, output)
                before = self.snapshot(hou, addon)
                node_type = type(solver)
                with patch.object(node_type, 'createNode') as create, patch.object(node_type, 'setInput') as connect:
                    with self.assertRaises(addon.BridgeCommandError) as error:
                        client.call('agent.fx.build_preview', params)
                    self.assertEqual(error.exception.code, 'SWARM_PRESOLVE_CONFLICT')
                    create.assert_not_called()
                    connect.assert_not_called()
                self.assertEqual(self.snapshot(hou, addon), before)
        for source in (None, noise):
            with self.subTest(normal_source=None if source is None else source.path()):
                solver.setInput(1, source)
                client.call('agent.fx.build_preview', params)
                connection = next(wire for wire in solver.inputConnections() if wire.inputIndex() == 1)
                self.assertEqual(connection.inputNode().path(), noise.path())
                self.assertEqual(connection.outputIndex(), 0)

    def assert_binding_rejected(self, client, addon, hou, params, roles, parm):
        _, pack = addon._fx_pack(params)
        before = self.snapshot(hou, addon)
        for control in ('noise_strength', 'target_noise'):
            with self.subTest(control=control):
                params['constraints']['fx']['changes'] = {control: 1.}
                with patch.object(type(parm), 'set') as set_value, patch.object(type(parm), 'setKeyframes') as set_keys:
                    with self.assertRaises(addon.BridgeCommandError) as error:
                        client.call('agent.fx.apply_candidate', params)
                    self.assertEqual(error.exception.code, 'SWARM_GEOMETRY_BINDING_CHANGED')
                    set_value.assert_not_called()
                    set_keys.assert_not_called()
                self.assertEqual(self.snapshot(hou, addon), before)
                with self.assertRaises(addon.BridgeCommandError) as error:
                    addon._fx_swarm_host().readback(roles, pack, {control: 1.})
                self.assertEqual(error.exception.code, 'SWARM_GEOMETRY_BINDING_CHANGED')
                self.assertEqual(self.snapshot(hou, addon), before)

    def check_bindgeo(self, client, addon, hou, native, params, roles):
        for role in ('seek', 'noise_force'):
            node = hou.node(roles[role])
            parm = node.parm('bindgeo')
            self.assertEqual(parm.eval(), 'Geometry')
            for drift in ('literal', 'expression', 'reference', 'keyframe'):
                with self.subTest(role=role, drift=drift), patch.object(parm, '_native_state', copy.deepcopy(parm._native_state)):
                    original_value = parm.value
                    try:
                        if drift == 'literal':
                            parm.set('OtherGeometry')
                        elif drift == 'expression':
                            parm.setExpression('"Geometry"', hou.exprLanguage.Hscript)
                        elif drift == 'reference':
                            other = 'noise_force' if role == 'seek' else 'seek'
                            native.set_parm_state(parm, reference=hou.node(roles[other]).parm('bindgeo'))
                        else:
                            key = hou.StringKeyframe()
                            key.setFrame(1.)
                            key.setValue('Geometry')
                            parm.setKeyframes([key])
                        self.assert_binding_rejected(client, addon, hou, params, roles, parm)
                    finally:
                        parm.value = original_value
            node_type = type(node)
            original_parm, original_tuple = node_type.parm, node_type.parmTuple

            def missing_parm(candidate, name):
                return None if candidate is node and name == 'bindgeo' else original_parm(candidate, name)

            def missing_tuple(candidate, name):
                return None if candidate is node and name == 'bindgeo' else original_tuple(candidate, name)

            with self.subTest(role=role, drift='missing'), patch.object(node_type, 'parm', missing_parm), patch.object(node_type, 'parmTuple', missing_tuple):
                self.assert_binding_rejected(client, addon, hou, params, roles, parm)
            params['constraints']['fx'].pop('changes', None)
            parm.set('OtherGeometry')
            before = self.snapshot(hou, addon)
            with self.assertRaises(addon.BridgeCommandError) as error:
                client.call('agent.fx.build_preview', params)
            self.assertEqual(error.exception.code, 'SWARM_GEOMETRY_BINDING_CHANGED')
            self.assertEqual(self.snapshot(hou, addon), before)
            parm.set('Geometry')

    def check_reopen(self, tmp, version, client, addon, hou, params, built):
        roles = built['scene_manifest']['nodes']
        _, pack = addon._fx_pack(params)
        changes = {'target_noise': 2., 'noise_strength': 8.}
        params['constraints']['fx']['changes'] = changes
        client.call('agent.fx.apply_candidate', params)
        expected = addon._fx_swarm_host().readback(roles, pack, changes)
        self.assertEqual(expected['controls'], changes)

        def save(name):
            return client.call('scene.save_hip', {
                'task_id': TASK, 'path': str(tmp / name),
                'root_path': built['scene_manifest']['execution_root'],
            })

        saved = save('normal.hip')
        drift_saves = []
        for role in ('seek', 'noise_force'):
            parm = hou.node(roles[role]).parm('bindgeo')
            parm.set('OtherGeometry')
            drift_saves.append(save(role + '-drift.hip'))
            parm.set('Geometry')
        client2, addon2, hou2, _ = self.make_host(tmp, version, 'second-api')
        self.assertIsNot(hou2, hou)
        self.assertEqual(addon2._host_identity()['pid'], addon._host_identity()['pid'])

        def reopen(record):
            client2.call('scene.reopen_task_hip', {
                'task_id': TASK, 'path': record['path'], 'sha256': record['sha256'],
            })

        reopen(saved)
        self.assertEqual(addon2._fx_swarm_host().readback(roles, pack, changes), expected)
        for record in drift_saves:
            reopen(record)
            before = self.snapshot(hou2, addon2)
            with self.assertRaises(addon2.BridgeCommandError) as error:
                addon2._fx_swarm_host().readback(roles, pack, changes)
            self.assertEqual(error.exception.code, 'SWARM_GEOMETRY_BINDING_CHANGED')
            self.assertEqual(self.snapshot(hou2, addon2), before)
        reopen(saved)
        self.assertEqual(addon2._fx_swarm_host().readback(roles, pack, changes), expected)

    def test_presolve_conflict_houdini21(self):
        self.run_case('21.0.631', 'presolve')

    def test_presolve_conflict_houdini22(self):
        self.run_case('22.0.429', 'presolve')

    def test_geometry_binding_houdini21(self):
        self.run_case('21.0.631', 'bindgeo')

    def test_geometry_binding_houdini22(self):
        self.run_case('22.0.429', 'bindgeo')


if __name__ == '__main__':
    unittest.main()
