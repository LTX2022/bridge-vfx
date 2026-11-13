"""Actual addon build/feedback transactions with explicit bottom HOM rest data."""
from contextlib import ExitStack
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_host as adapter
from houdini_bridge import native_geometry_controls_program as program
from houdini_bridge import native_geometry_runtime_registry as runtime
from vfx_pipeline.workbuddy_assembly import software_host_client
import test_native_geometry_controls_host as bottom
from test_native_geometry_controls_program import BottomGeometry

ROOT = Path(__file__).resolve().parents[2]


def load_boundary(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        self.client, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py',
                                                       self.directory / 'host')
        native = load_boundary('g03_schema_boundary', 'native_schema_test_boundary.py')
        api = load_boundary('g03_stage_boundary', 'software_render_api_boundary.py')
        interfaces, states, ports = api.interface_profiles(ROOT, self.version)
        states.setdefault('Sop/attribwrangle', {})['snippet'] = dict(
            origin='test_injected_native_api', value='', locked=False, disabled=False, hidden=False)
        native.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', self.version,
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        self.hou = sys.modules['hou']
        api.install_stage_api(self.hou)
        self.task = 'geometry-wiring-task'
        self.params = dict(task_id=self.task, constraints={'fx': {
            'domain_pack': 'procedural_geometry_v1', 'run_mode': 'diagnose', 'frames': [1, 2]}},
            render={'frame_range': {'start': 1, 'end': 2, 'step': 1}})
        self.root = self.addon._fx_task_paths(self.task, None)[0]
        self.source_path = self.root + '/' + self.addon._fx_node_name('geometry_network') + '/' + self.addon._fx_node_name('instance_source')
        self.source = BottomGeometry(self.source_path).observe()
        node_class = type(self.hou.node('/obj'))
        original_geometry = node_class.geometry

        def geometry(node, output_index=0):
            if node.path() == self.source_path:
                if output_index != 0:
                    raise ValueError('explicit bottom rest output is zero')
                return bottom.Geometry(self.source)
            return original_geometry(node, output_index=output_index)

        self.stack.enter_context(patch.object(node_class, 'geometry', geometry))

        def geometry_at_frame(node, frame, output_index=0):
            if node.path() != self.source_path or frame != 1. or output_index != 0:
                raise ValueError('explicit bottom rest frame/output unavailable')
            return bottom.Geometry(self.source)

        self.stack.enter_context(patch.object(node_class, 'geometryAtFrame', geometry_at_frame, create=True))
        self.stack.enter_context(patch.object(node_class, 'isBypassed', lambda node: False, create=True))
        identity = dict(task_id=self.task, version=self.version, pid=os.getpid(),
            launch_nonce='explicit-g03-software-boundary', session_id='g03-software-session',
            process_generation='g03-software-generation')
        self.stack.enter_context(patch.object(self.addon, '_TASK_HOST_IDENTITY', identity, create=True))
        self.input_path = self.directory / '冻结输入 with space.json'
        self.input_data = dict(schema='bridge.geometry-rest-input/1', task_id=self.task,
            task_root=self.root, native_version=self.version, input_version='explicit-rest-v1',
            source_node_path=self.source_path, output=0, frame=1., space='sop_local_rest', unit='SU',
            local_x_axis=[1., 0., 0.], source_geometry_sha256=program.source_geometry_sha256(self.source),
            geometry_observation='native_sop_read')
        self.input_path.write_text(json.dumps(self.input_data, ensure_ascii=False), encoding='utf-8')
        content = self.input_path.read_bytes()
        self.input_manifest = [dict(index=0, asset_id='g03-rest-input', semantic_role='geometry_rest_basis',
            source_uri=str(self.input_path), sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))]
        return self

    def __exit__(self, *args):
        adapter._SNAPSHOTS.clear()
        for token, entry in list(runtime._COHORTS.items()):
            if entry['host'] is self.addon.__dict__:
                runtime._COHORTS.pop(token)
        for token, transaction in list(runtime._TRANSACTIONS.items()):
            if transaction['entry']['host'] is self.addon.__dict__:
                runtime._TRANSACTIONS.pop(token)
        return self.stack.__exit__(*args)

    def build(self, *, basis=True):
        params = copy.deepcopy(self.params)
        if basis:
            params['frozen_input_manifest'] = copy.deepcopy(self.input_manifest)
        result = self.client.call('agent.fx.build_preview', params)
        self.roles = result['scene_manifest']['nodes']
        self.pack = self.addon._fx_pack(params)[1]
        self.carrier = self.hou.node(self.roles[program.ROLE])
        return result

    def apply(self, changes):
        params = copy.deepcopy(self.params)
        params['constraints']['fx']['changes'] = changes
        return self.client.call('agent.fx.apply_candidate', params)


class GeometryAddonWiringTests(unittest.TestCase):
    def test_missing_input_build_records_blocker_and_write_refuses(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                result = fixture.build(basis=False)
                initialization = result['scene_manifest']['native_initialization']['geometry_deformation']
                self.assertEqual(initialization['status'], 'BLOCKED')
                self.assertEqual(fixture.carrier.parm('snippet').eval(), '')
                before = fixture.addon._fx_state_path(fixture.task).read_bytes()
                with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                    fixture.apply({'deformation': 1.})
                self.assertEqual(refused.exception.code, 'GEOMETRY_REGISTERED_COHORT_REQUIRED')
                self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), before)
                self.assertEqual(fixture.carrier.parm('snippet').eval(), '')

    def test_fresh_build_and_feedback_use_actual_registered_rest_and_program(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                built = fixture.build()
                initialization = built['scene_manifest']['native_initialization']['geometry_deformation']
                self.assertEqual(initialization['value'], 0.)
                self.assertEqual(initialization['evidence_scope'], 'parameters_only')
                for amplitude in (3., 0., 100.):
                    result = fixture.apply({'deformation': amplitude, 'scale': .5, 'rotation': 19.})
                    actual = fixture.addon._fx_geometry_host().observations(fixture.roles, fixture.pack)
                    observed = program.control_readback(version, actual['context'], actual['parameters'])
                    self.assertEqual(observed['value'], amplitude)
                    self.assertEqual(result['native_geometry_readback']['status'], 'BLOCKED')
                    self.assertEqual(result['native_geometry_readback']['evidence_scope'], 'parameters_only')
                    self.assertEqual(fixture.hou.node(fixture.roles['instance_transform']).parm('scale').eval(), .5)
                    self.assertEqual(fixture.carrier.inputConnections()[0].inputNode().path(), fixture.roles['instance_source'])
                    self.assertEqual(fixture.hou.node(fixture.roles['instance_transform']).inputConnections()[0].inputNode(), fixture.carrier)
                    self.assertEqual(adapter._SNAPSHOTS, {})

    def test_candidate_manifest_failure_restores_program_registration_and_state(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.build()
                before = fixture.carrier.parm('snippet').eval()
                registration = fixture.carrier.userData(adapter.REGISTRATION_KEY)
                state = fixture.addon._fx_state_path(fixture.task).read_bytes()
                with patch.object(fixture.addon, '_fx_store_manifest', side_effect=OSError('explicit manifest failure')):
                    with self.assertRaises(Exception):
                        fixture.apply({'deformation': 5.})
                self.assertEqual(fixture.carrier.parm('snippet').eval(), before)
                self.assertEqual(fixture.carrier.userData(adapter.REGISTRATION_KEY), registration)
                self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), state)
                self.assertEqual(adapter._SNAPSHOTS, {})

    def test_changed_input_or_rest_geometry_refuses_before_parameter_write(self):
        for version in program.VERSIONS:
            for changed in ('input', 'geometry', 'current_geometry'):
                with self.subTest(version=version, changed=changed), Fixture(version) as fixture:
                    fixture.build()
                    before = fixture.carrier.parm('snippet').eval()
                    if changed == 'input':
                        fixture.input_path.write_bytes(b'changed bytes')
                    elif changed == 'geometry':
                        fixture.source['point_attributes']['P']['values'][1][0] += .125
                    else:
                        fixture.hou.setFrame(2.)
                        current = copy.deepcopy(fixture.source)
                        current['point_attributes']['P']['values'][1][0] += .125
                        node_class = type(fixture.carrier)
                        original_geometry = node_class.geometry
                        def geometry(node, output_index=0):
                            if node.path() == fixture.source_path:
                                return bottom.Geometry(current)
                            return original_geometry(node, output_index=output_index)
                        fixture.stack.enter_context(patch.object(node_class, 'geometry', geometry))
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.apply({'deformation': 9.})
                    self.assertEqual(refused.exception.code, {
                        'input': 'GEOMETRY_REST_INPUT_CHANGED', 'geometry': 'GEOMETRY_BASIS_CHANGED',
                        'current_geometry': 'GEOMETRY_STATIC_SOURCE_REQUIRED'}[changed])
                    self.assertEqual(fixture.carrier.parm('snippet').eval(), before)
                    self.assertEqual(adapter._SNAPSHOTS, {})

    def test_unchanged_current_geometry_can_use_authenticated_rest_on_another_frame(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.build()
                fixture.hou.setFrame(2.)
                result = fixture.apply({'deformation': 9.})
                observed = fixture.addon._fx_geometry_host().observations(fixture.roles, fixture.pack)
                self.assertEqual(observed['context']['source_sampling']['rest_frame'], 1.)
                self.assertEqual(observed['context']['source_sampling']['current_frame'], 2.)
                self.assertEqual(result['native_geometry_readback']['value'], 9.)
                self.assertEqual(fixture.hou.frame(), 2.)
                self.assertEqual(adapter._SNAPSHOTS, {})

    def test_build_manifest_failure_discards_fresh_nodes_and_authority(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                with patch.object(fixture.addon, '_fx_store_manifest', side_effect=OSError('explicit build manifest failure')):
                    with self.assertRaises(Exception):
                        fixture.build()
                root = fixture.hou.node(fixture.root)
                self.assertEqual(root.allSubChildren(), ())
                self.assertIsNone(root.userData('bridge_fx_manifest_v1'))
                fixture.build()
                self.assertEqual(fixture.apply({'deformation': 1.})['native_geometry_readback']['value'], 1.)

    def test_final_registry_commit_failure_rolls_back_whole_fresh_build(self):
        original_end = runtime.Registry.end

        def fail_commit(registry, token, commit):
            if commit:
                raise program.GeometryControlsError('GEOMETRY_REST_INPUT_CHANGED', 'explicit final verification failure')
            return original_end(registry, token, commit)

        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                with patch.object(runtime.Registry, 'end', fail_commit):
                    with self.assertRaises(program.GeometryControlsError):
                        fixture.build()
                root = fixture.hou.node(fixture.root)
                self.assertEqual(root.allSubChildren(), ())
                self.assertIsNone(root.userData('bridge_fx_manifest_v1'))
                self.assertFalse(any(entry['host'] is fixture.addon.__dict__ for entry in runtime._COHORTS.values()))
                self.assertFalse(any(entry['entry']['host'] is fixture.addon.__dict__ for entry in runtime._TRANSACTIONS.values()))
                fixture.build()

    def test_registered_rebuild_keeps_selected_value_and_releases_snapshot(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.build()
                fixture.apply({'deformation': 2.})
                before = fixture.carrier.parm('snippet').eval()
                fixture.build()
                self.assertEqual(fixture.carrier.parm('snippet').eval(), before)
                self.assertEqual(adapter._SNAPSHOTS, {})
                for attempt in range(4):
                    fixture.addon._fx_preflight_existing_candidate_patch(
                        {'candidate_patch': {'deformation': 2.}}, fixture.roles, fixture.pack)
                    self.assertEqual(adapter._SNAPSHOTS, {}, 'read-only preflight retained a transaction')
                    self.assertEqual(fixture.carrier.parm('snippet').eval(), before)

    def test_input_drift_after_native_write_restores_prepared_state(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.build()
                parameter = fixture.carrier.parm('snippet')
                before = parameter.eval()
                userdata = fixture.carrier.userDataDict()
                state = fixture.addon._fx_state_path(fixture.task).read_bytes()
                parameter_class = type(parameter)
                original_set = parameter_class.set
                changed = []

                def set_with_input_drift(actual, value, **kwargs):
                    result = original_set(actual, value, **kwargs)
                    if actual.path() == parameter.path() and value != before and not changed:
                        fixture.input_path.write_bytes(b'explicit input drift after native snippet set')
                        changed.append(True)
                    return result

                with patch.object(parameter_class, 'set', set_with_input_drift):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.apply({'deformation': 5.})
                self.assertTrue(changed)
                self.assertEqual(refused.exception.code, 'GEOMETRY_REST_INPUT_CHANGED')
                self.assertIn('GEOMETRY_REST_INPUT_CHANGED', str(refused.exception))
                self.assertEqual(parameter.eval(), before)
                self.assertEqual(fixture.carrier.userDataDict(), userdata)
                self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), state)
                self.assertEqual(adapter._SNAPSHOTS, {})
                with self.assertRaises(fixture.addon.BridgeCommandError) as still_refused:
                    fixture.apply({'deformation': 5.})
                self.assertEqual(still_refused.exception.code, 'GEOMETRY_REST_INPUT_CHANGED')

    def test_frame_drift_during_lazy_point_observation_refuses_without_write(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.build()
                parameter = fixture.carrier.parm('snippet')
                before = parameter.eval()
                state = fixture.addon._fx_state_path(fixture.task).read_bytes()
                original_value = bottom.Point.attribValue
                changed = []

                def observed_at_changed_frame(point, name):
                    result = original_value(point, name)
                    if not changed:
                        fixture.hou.setFrame(2.)
                        changed.append(True)
                    return result

                with patch.object(bottom.Point, 'attribValue', observed_at_changed_frame):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.apply({'deformation': 5.})
                self.assertTrue(changed)
                self.assertEqual(refused.exception.code, 'GEOMETRY_SOURCE_FRAME_REQUIRED')
                self.assertEqual(parameter.eval(), before)
                self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), state)
                self.assertEqual(adapter._SNAPSHOTS, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
