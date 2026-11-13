"""Actual addon output evidence with fixed bottom HOM data, never VEX results."""
import copy
import json
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_program as program
import test_native_geometry_addon_wiring as wiring
import test_native_geometry_observation as bottom


OUTPUT_ROLES = ('geometry_deform', 'instance_transform', 'scatter', 'point_variation', 'instance')


class StaticOutputGeometry(bottom.NativeGeometry):
    def __init__(self, version):
        super().__init__(version)
        self.on_read = None
        self.attribute_reads = 0

    def pointAttribs(self):
        self.attribute_reads += 1
        callback, self.on_read = self.on_read, None
        if callback is not None:
            callback()
        return super().pointAttribs()


class RestReadablePoint(bottom.NativeElement):
    def attribValue(self, attribute):
        return self.values[attribute if isinstance(attribute, str) else attribute.name()]


class CompleteRestGeometry(StaticOutputGeometry):
    def __init__(self, fixture):
        super().__init__(fixture.version)
        self.rest = wiring.bottom.Geometry(fixture.source)
        self.attributes['point'][0].precision = 'Float64'
        self.point_elements = [RestReadablePoint(index * 7 + 10, {
            'P': tuple(fixture.source['point_attributes']['P']['values'][index]),
            'N': tuple(fixture.source['point_attributes']['N']['values'][index]),
            'id': fixture.source['point_attributes']['id']['values'][index],
            'label': ('rest first', 'rest second', 'rest third', 'rest fourth', 'rest fifth')[index],
        }) for index in range(fixture.source['points'])]
        vertices = [bottom.NativeVertex(index, self.point_elements[index], {'uv': (0., 0.)})
                    for index in fixture.source['polygons'][0]]
        self.primitive_elements = [bottom.NativePrimitive(0, vertices, {'pair': (3, -4)})]

    def findPointAttrib(self, name):
        return self.rest.findPointAttrib(name)


class GeometryOutputAddonTests(unittest.TestCase):
    def install_outputs(self, fixture):
        outputs = {role: StaticOutputGeometry(fixture.version) for role in OUTPUT_ROLES}
        node_class = type(fixture.carrier)
        original_geometry = node_class.geometry
        paths = {fixture.roles[role]: role for role in OUTPUT_ROLES}
        acquisitions = []

        def geometry(node, output_index=0):
            role = paths.get(node.path())
            if role is not None:
                if output_index != 0:
                    raise ValueError('explicit static bottom output is zero')
                acquisitions.append(role)
                return outputs[role]
            return original_geometry(node, output_index=output_index)

        fixture.stack.enter_context(patch.object(node_class, 'geometry', geometry))
        return outputs, acquisitions

    def install_complete_source(self, fixture):
        source = CompleteRestGeometry(fixture)
        node_class = type(fixture.carrier)
        original_geometry = node_class.geometry

        def geometry(node, output_index=0):
            if node.path() == fixture.source_path:
                if output_index != 0:
                    raise ValueError('explicit static rest output is zero')
                return source
            return original_geometry(node, output_index=output_index)

        fixture.stack.enter_context(patch.object(node_class, 'geometry', geometry))
        return source

    def collect(self, fixture, frames=(1,)):
        params = copy.deepcopy(fixture.params)
        params['constraints']['fx']['frames'] = list(frames)
        params['render']['frame_range'] = dict(start=frames[0], end=frames[-1], step=1)
        return fixture.client.call('agent.fx.collect_evidence', params)

    def helper(self, fixture, budget=2 * 1024 * 1024):
        return fixture.addon._fx_geometry_output_evidence(
            fixture.roles, fixture.pack, fixture.hou.frame(), {'remaining': budget})

    def assert_blocked(self, evidence):
        self.assertEqual(evidence['schema'], 'bridge.geometry-output-observations/1')
        self.assertEqual(evidence['status'], 'BLOCKED')
        self.assertEqual(evidence['evidence_scope'], 'raw_geometry_observations')
        self.assertTrue(evidence['missing_evidence'])
        self.assertNotIn('available', evidence)

    def test_private_helper_preserves_fixed_native_values_all_attribute_owners_and_topology(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                fixture.apply({'deformation': 3.})
                outputs, acquisitions = self.install_outputs(fixture)
                original_source = copy.deepcopy(fixture.source)
                evidence = self.helper(fixture)
                self.assert_blocked(evidence)
                self.assertEqual(evidence['native_version'], version)
                self.assertEqual(set(evidence['outputs']), set(OUTPUT_ROLES))
                self.assertIsNone(evidence['deformation'])
                observed = evidence['outputs']['geometry_deform']
                self.assertEqual(observed['attributes']['point']['P']['values'],
                                 [[0., 0., 0.], [2., 0., 0.], [0., 0., 2.]])
                self.assertEqual(observed['attributes']['point']['N']['values'], [[0., 1., 0.]] * 3)
                self.assertEqual(observed['attributes']['point']['id']['values'], [101, 103, 102])
                self.assertEqual(observed['attributes']['point']['label']['values'], ['first', '第二点', 'third'])
                self.assertEqual(observed['attributes']['primitive']['pair']['values'], [[3, -4]])
                self.assertEqual(observed['attributes']['vertex']['uv']['values'],
                                 [[1., 0.], [0., 1.], [0., 0.]])
                self.assertEqual(observed['attributes']['detail']['title']['values'], ['静态 HOM 几何'])
                self.assertEqual(observed['point_numbers'], [10, 30, 20])
                self.assertEqual(observed['primitive_numbers'], [7])
                self.assertEqual(observed['vertex_numbers'], [2, 0, 1])
                self.assertEqual(observed['polygons'], [[1, 2, 0]])
                self.assertEqual(observed['polygon_vertices'], [[0, 1, 2]])
                self.assertEqual(observed['primitive_closed'], [True])
                self.assertEqual(observed['attributes']['point']['N']['precision'], 'float64')
                self.assertEqual(fixture.source, original_source)
                self.assertTrue(acquisitions)
                self.assertGreater(outputs['geometry_deform'].attribute_reads, 0)

    def test_actual_input_geometry_matching_data_does_not_grant_native_pass(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                self.install_outputs(fixture)
                evidence = self.helper(fixture)
                self.assert_blocked(evidence)
                consumption = {item['destination_role'] + '/input' + str(item['input_index']): item
                               for item in evidence['consumption']}
                for label in ('instance_transform/input0', 'point_variation/input0',
                              'instance/input0', 'instance/input1'):
                    self.assertTrue(consumption[label]['matching_observed_data'])
                    source = consumption[label]['source_role']
                    self.assertEqual(evidence['inputs'][label]['geometry_sha256'],
                                     evidence['outputs'][source]['geometry_sha256'])
                self.assertFalse(consumption['geometry_deform/input0']['matching_observed_data'])

    def test_actual_input_geometry_with_different_native_data_remains_mismatched_and_blocked(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                self.install_outputs(fixture)
                node_class = type(fixture.carrier)
                original_input = node_class.inputGeometry
                changed = StaticOutputGeometry(version)
                changed.point_elements[0].values['P'] = (9., 8., 7.)

                def input_geometry(node, index):
                    if node.path() == fixture.roles['instance_transform'] and index == 0:
                        return changed
                    return original_input(node, index)

                with patch.object(node_class, 'inputGeometry', input_geometry):
                    evidence = self.helper(fixture)
                self.assert_blocked(evidence)
                observed = evidence['inputs']['instance_transform/input0']
                self.assertEqual(observed['attributes']['point']['P']['values'][0], [9., 8., 7.])
                self.assertNotEqual(observed['geometry_sha256'],
                                    evidence['outputs']['geometry_deform']['geometry_sha256'])
                result = next(item for item in evidence['consumption']
                              if item['destination_role'] == 'instance_transform')
                self.assertFalse(result['matching_observed_data'])

    def test_deformation_fields_compare_actual_static_data_without_mathematical_correctness_claim(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                fixture.apply({'deformation': 3.})
                original_source = copy.deepcopy(fixture.source)
                outputs, _ = self.install_outputs(fixture)
                source = self.install_complete_source(fixture)
                for change in ('same', 'P', 'N', 'topology'):
                    with self.subTest(change=change):
                        deformed = copy.deepcopy(source)
                        if change == 'P':
                            deformed.point_elements[0].values['P'] = (9., 8., 7.)
                        elif change == 'N':
                            deformed.point_elements[0].values['N'] = (1., 0., 0.)
                        elif change == 'topology':
                            deformed.primitive_elements[0].vertex_elements.reverse()
                        outputs['geometry_deform'] = deformed
                        evidence = self.helper(fixture)
                        self.assert_blocked(evidence)
                        self.assertEqual(evidence['deformation'], {
                            'required_point_attributes_observed': True,
                            'topology_matches_source': change != 'topology',
                            'attributes_except_point_P_match_source': change != 'N',
                            'point_P_matches_source': change != 'P',
                        })
                        self.assertEqual(fixture.source, original_source)

    def test_missing_required_deformed_attribute_records_specific_blocker(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                outputs, _ = self.install_outputs(fixture)
                source = self.install_complete_source(fixture)
                for missing_name in ('P', 'N', 'id'):
                    with self.subTest(missing_name=missing_name):
                        deformed = copy.deepcopy(source)
                        deformed.attributes['point'] = [attribute for attribute in deformed.attributes['point']
                                                         if attribute.name() != missing_name]
                        outputs['geometry_deform'] = deformed
                        evidence = self.helper(fixture)
                        self.assert_blocked(evidence)
                        self.assertFalse(evidence['deformation']['required_point_attributes_observed'])
                        self.assertIsNone(evidence['deformation']['point_P_matches_source'])
                        self.assertIn({'location': 'geometry_deform',
                                       'code': 'GEOMETRY_OUTPUT_ATTRIBUTES_UNOBSERVED'}, evidence['missing'])

    def test_formal_collect_evidence_reads_fixed_outputs_across_frames_without_predicting_deformation(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                fixture.apply({'deformation': 3.})
                self.install_outputs(fixture)
                original_frame = fixture.hou.frame()
                original_program = fixture.carrier.parm('snippet').eval()
                result = self.collect(fixture, (-1, 0, 1, 2))
                self.assertEqual(result['diagnosis_state'], 'DIAGNOSIS_INCONCLUSIVE')
                evidence = result['evidence']
                self.assertEqual(set(evidence['native_geometry_outputs']), {'-1', '0', '1', '2'})
                hashes = set()
                for frame, actual in evidence['native_geometry_outputs'].items():
                    self.assert_blocked(actual)
                    self.assertEqual(actual['frame'], int(frame))
                    observed = actual['outputs']['geometry_deform']
                    self.assertEqual(observed['attributes']['point']['P']['values'][1], [2., 0., 0.])
                    hashes.add(observed['geometry_sha256'])
                    self.assertEqual(evidence['native_geometry_readback'][frame]['value'], 3.)
                    self.assertEqual(evidence['native_geometry_readback'][frame]['status'], 'BLOCKED')
                self.assertEqual(len(hashes), 1)
                self.assertEqual(fixture.hou.frame(), original_frame)
                self.assertEqual(fixture.carrier.parm('snippet').eval(), original_program)
                stored = json.loads(fixture.hou.node(fixture.root).userData('bridge_fx_manifest_v1'))
                self.assertEqual(stored['last_evidence']['native_geometry_outputs'],
                                 evidence['native_geometry_outputs'])

    def test_fixed_output_does_not_follow_requested_control_amplitude(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                self.install_outputs(fixture)
                observed = []
                for amplitude in (0., 3., 100.):
                    fixture.apply({'deformation': amplitude})
                    evidence = self.collect(fixture)['evidence']
                    self.assertEqual(evidence['native_geometry_readback']['1']['value'], amplitude)
                    actual = evidence['native_geometry_outputs']['1']
                    self.assert_blocked(actual)
                    observed.append(actual['outputs']['geometry_deform']['geometry_sha256'])
                self.assertEqual(len(set(observed)), 1)

    def test_source_transform_and_copy_port_tampering_refuses_and_restores_original_frame(self):
        changes = (('geometry_deform', 0, 'scatter', 0),
                   ('instance_transform', 0, 'instance_source', 0),
                   ('instance', 0, 'scatter', 0),
                   ('instance', 1, 'scatter', 0),
                   ('instance', 0, 'instance_transform', 1))
        for version in program.VERSIONS:
            for destination, index, source, output in changes:
                with self.subTest(version=version, destination=destination, index=index, output=output), \
                        wiring.Fixture(version) as fixture:
                    fixture.build()
                    self.install_outputs(fixture)
                    fixture.hou.node(fixture.roles[destination]).setInput(
                        index, fixture.hou.node(fixture.roles[source]), output)
                    original_frame = fixture.hou.frame()
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        self.collect(fixture, (0, 1))
                    self.assertEqual(refused.exception.code, 'GEOMETRY_SOURCE_CONNECTION_REQUIRED')
                    self.assertEqual(fixture.hou.frame(), original_frame)

    def test_drift_during_observation_refuses_without_persisting_evidence_and_restores_frame(self):
        for version in program.VERSIONS:
            for drift in ('nonce', 'session', 'frame', 'input', 'program'):
                with self.subTest(version=version, drift=drift), wiring.Fixture(version) as fixture:
                    fixture.build()
                    outputs, _ = self.install_outputs(fixture)
                    original_frame = fixture.hou.frame()
                    original_state = fixture.addon._fx_state_path(fixture.task).read_bytes()
                    node_class = type(fixture.carrier)
                    original_session = node_class.sessionId

                    def session_id(node):
                        return original_session(node) + getattr(node, '_explicit_geometry_session_drift', 0)

                    fixture.stack.enter_context(patch.object(node_class, 'sessionId', session_id))

                    def change_context():
                        if drift == 'nonce':
                            fixture.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'changed-during-output'
                        elif drift == 'session':
                            fixture.carrier._explicit_geometry_session_drift = 1000
                        elif drift == 'frame':
                            fixture.hou.setFrame(37.)
                        elif drift == 'input':
                            fixture.input_path.write_bytes(b'explicit changed rest input bytes')
                        else:
                            fixture.carrier.parm('snippet').set('explicit foreign program')

                    outputs['geometry_deform'].on_read = change_context
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        self.collect(fixture, (0, 1))
                    self.assertTrue(refused.exception.code.startswith('GEOMETRY_'))
                    self.assertIsNone(outputs['geometry_deform'].on_read)
                    self.assertGreater(outputs['geometry_deform'].attribute_reads, 0)
                    self.assertEqual(fixture.hou.frame(), original_frame)
                    self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), original_state)

    def test_last_copy_input_read_detects_late_carrier_state_changes_and_restores_frame(self):
        for version in program.VERSIONS:
            for state in ('bypass', 'editable', 'errors', 'type'):
                with self.subTest(version=version, state=state), wiring.Fixture(version) as fixture:
                    fixture.build()
                    self.install_outputs(fixture)
                    scatter = fixture.hou.node(fixture.roles['scatter'])
                    node_class = type(scatter)
                    original_input = node_class.inputGeometry
                    original_bypass = node_class.isBypassed
                    original_editable = node_class.isEditable
                    original_errors = node_class.errors
                    changed = []
                    original_frame = fixture.hou.frame()
                    original_state = fixture.addon._fx_state_path(fixture.task).read_bytes()

                    def input_geometry(node, index):
                        observed = original_input(node, index)
                        if node.path() == fixture.roles['instance'] and index == 1:
                            changed.append(True)
                            scatter._explicit_late_state = state
                            if state == 'type':
                                scatter._type_name = 'sphere'
                        return observed

                    with patch.object(node_class, 'inputGeometry', input_geometry), \
                            patch.object(node_class, 'isBypassed', lambda node: (
                                getattr(node, '_explicit_late_state', None) == 'bypass' or original_bypass(node))), \
                            patch.object(node_class, 'isEditable', lambda node: (
                                getattr(node, '_explicit_late_state', None) != 'editable' and original_editable(node))), \
                            patch.object(node_class, 'errors', lambda node: (
                                ('explicit late native cook error',) if getattr(node, '_explicit_late_state', None)
                                == 'errors' else original_errors(node))):
                        with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                            self.collect(fixture, (0, 1))
                    self.assertTrue(changed)
                    self.assertEqual(refused.exception.code, 'SCENE_OWNERSHIP_REQUIRED'
                                     if state == 'type' else 'GEOMETRY_CONTEXT_CHANGED')
                    self.assertEqual(fixture.hou.frame(), original_frame)
                    self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), original_state)

    def assert_late_parameter_drift(self, fixture, role, name, changed_value):
        self.install_outputs(fixture)
        node_class = type(fixture.carrier)
        original_input = node_class.inputGeometry
        parameter = fixture.hou.node(fixture.roles[role]).parm(name)
        original_value = parameter.eval()
        original_frame = fixture.hou.frame()
        original_state = fixture.addon._fx_state_path(fixture.task).read_bytes()
        changed = []

        def input_geometry(node, index):
            observed = original_input(node, index)
            if node.path() == fixture.roles['instance'] and index == 1:
                parameter.set(changed_value)
                changed.append(True)
            return observed

        with patch.object(node_class, 'inputGeometry', input_geometry):
            with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                self.collect(fixture, (0, 1))
        self.assertTrue(changed)
        self.assertNotEqual(parameter.eval(), original_value)
        self.assertEqual(refused.exception.code, 'GEOMETRY_CONTEXT_CHANGED')
        self.assertEqual(fixture.hou.frame(), original_frame)
        self.assertEqual(fixture.addon._fx_state_path(fixture.task).read_bytes(), original_state)

    def test_last_copy_input_seed_drift_refuses_and_restores_frame(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                self.assert_late_parameter_drift(fixture, 'scatter', 'seed', 123)

    def test_last_copy_input_scale_drift_refuses_and_restores_frame(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                self.assert_late_parameter_drift(fixture, 'instance_transform', 'scale', 7.)

    def test_exhausted_total_budget_stops_further_output_and_input_native_acquisition(self):
        for version in program.VERSIONS:
            for available in (0, 1):
                with self.subTest(version=version, available=available), wiring.Fixture(version) as fixture:
                    fixture.build()
                    outputs, acquisitions = self.install_outputs(fixture)
                    budget = {'remaining': available}
                    original_frame = fixture.hou.frame()
                    with self.assertRaises(fixture.addon.BridgeCommandError) as refused:
                        fixture.addon._fx_geometry_output_evidence(
                            fixture.roles, fixture.pack, fixture.hou.frame(), budget)
                    self.assertEqual(refused.exception.code, 'GEOMETRY_OUTPUT_BUDGET_EXCEEDED')
                    self.assertEqual(budget['remaining'], 0)
                    self.assertEqual(acquisitions, [] if available == 0 else ['geometry_deform'])
                    self.assertEqual(sum(item.attribute_reads for item in outputs.values()),
                                     0 if available == 0 else 1)
                    self.assertEqual(fixture.hou.frame(), original_frame)

    def test_original_fixture_missing_native_api_is_specific_and_blocked(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                evidence = self.collect(fixture)['evidence']['native_geometry_outputs']['1']
                self.assert_blocked(evidence)
                missing = {item['location']: item['code'] for item in evidence['missing']}
                self.assertEqual(missing['instance_source'], 'GEOMETRY_OBSERVATION_NATIVE_READ_FAILED')
                self.assertNotIn('instance_source', evidence['outputs'])
                self.assertIsNone(evidence['deformation'])
                self.assertFalse(next(item for item in evidence['consumption']
                                      if item['destination_role'] == 'geometry_deform')['matching_observed_data'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
