"""G03 bottom parameter and input geometry fixtures, never a VEX cook.

The candidate planner, readback parser, context guards and rollback are real.
No facade, registry, solver, producer receipt or downstream output is replaced.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from houdini_bridge import native_geometry_controls_program as program
from houdini_bridge import native_particle_ocean_geometry_domains as domains

ROOT = Path(__file__).resolve().parents[2]
NATIVE_ROOT = ROOT / 'docs/native-basis'


class BottomParameter:
    def __init__(self, captured, value):
        self.captured = copy.deepcopy(captured)
        self.value = copy.deepcopy(value)
        self.flags = dict(driven=False, locked=False, disabled=False, hidden=False)

    def eval(self):
        return copy.deepcopy(self.value)

    def set(self, value):
        if self.captured['type'] != 'string' or type(value) is not str or any(self.flags.values()):
            raise ValueError('only the writable string bottom parameter is used')
        self.value = value

    def observe(self):
        result = dict(origin='runtime_hom', type=self.captured['type'], size=self.captured['size'],
                      value=self.eval(), **self.flags)
        if self.captured['type'] == 'ordinal':
            result.update(menu_tokens=self.captured['menu_tokens'][::2],
                          menu_uses_token_value=self.captured['menu_uses_token_value'])
        return result


class BottomGeometry:
    def __init__(self, node_path):
        self.snapshot = dict(origin='runtime_hom', node_path=node_path, output=0, frame=1.,
                             space='sop_local_rest', unit='SU', points=5,
                             primitive_types=['Polygon'], polygons=[[0, 1, 2, 3, 4]],
                             point_attributes={})
        positions = [[-2., 0., 0.], [-1., 0., 0.], [0., 0., 0.], [1., 0., 0.], [2., 0., 0.]]
        for name, kind, size, precision, values in (
            ('P', 'float', 3, 'float64', positions),
            ('N', 'float', 3, 'float64', [[0., 1., 0.] for _ in positions]),
            ('id', 'integer', 1, 'int32', [5, 19, 31, 44, 71]),
        ):
            self.snapshot['point_attributes'][name] = dict(owner='point', type=kind, size=size,
                precision=precision, is_array=False, values=copy.deepcopy(values))

    def observe(self):
        return copy.deepcopy(self.snapshot)


class BottomHost:
    def __init__(self, version):
        self.version = version
        self.root = '/obj/g03_task'
        capture = json.loads((NATIVE_ROOT / 'w2-wrangle-convolve-static.json').read_text(encoding='utf-8'))
        self.operator = capture['versions'][version]['operators']['Sop/attribwrangle']
        self.nodes = {}
        for role, kind in (('instance_source', 'sphere'), (program.ROLE, 'attribwrangle'),
                           ('instance_transform', 'xform')):
            self.nodes[role] = dict(origin='runtime_hom', task_owned=True, task_id='g03_task',
                task_root=self.root, input_version='v1', native_version=version, category='sop',
                path=self.root + '/' + role, type=kind, editable=True, bypassed=False, inputs=[],
                space='sop_local_rest')
        for downstream, upstream in ((program.ROLE, 'instance_source'), ('instance_transform', program.ROLE)):
            self.nodes[downstream]['inputs'] = [dict(input_index=0, output_index=0,
                                                   node_path=self.nodes[upstream]['path'])]
        self.geometry = BottomGeometry(self.nodes['instance_source']['path'])
        self.source = program.collect_source_geometry(self.geometry, lambda geometry: geometry.observe())
        self.basis = program.freeze_basis(version, self.source, local_x_axis=[1, 0, 0],
            task_id='g03_task', task_root=self.root, input_version='v1', basis_input_sha256='a' * 64)
        self.parameters = {}
        for name, (kind, value) in dict(program.GATES, snippet=('string', '')).items():
            captured = self.operator['parameters'][name]
            if kind == 'ordinal' and not captured['menu_uses_token_value']:
                value = captured['menu_tokens'][::2].index(value)
            self.parameters[name] = BottomParameter(captured, value)
        self.initialization = None
        zero = program.source_program(version, 0, self.context())['program']
        self.parameters['snippet'].set(zero)
        self.initialization = dict(schema=program.REGISTRATION_SCHEMA, origin='runtime_hom',
            initialized=True, registered=True, generator=program.GENERATOR, task_id='g03_task',
            task_root=self.root, input_version='v1', native_version=version,
            node_path=self.nodes[program.ROLE]['path'], basis_sha256=self.basis['content_sha256'],
            initial_program_sha256=hashlib.sha256(self.parameters['snippet'].eval().encode()).hexdigest(),
            gates_sha256=program._hash(program.GATES))

    def context(self):
        return copy.deepcopy(dict(basis=self.basis, source=self.source, nodes=self.nodes,
                                  initialization=self.initialization))

    def observe(self):
        return program.collect_parameters(self, lambda node, name: node.parameters[name].observe())

    def apply(self, plan):
        for write in program.validate_plan(plan, self.context(), self.observe()):
            self.parameters[write['parm']].set(write['value'])


class NativeGeometryControlsProgramTests(unittest.TestCase):
    def hosts(self):
        return (BottomHost(version) for version in program.VERSIONS)

    def test_formal_controls_still_blocked_both_versions(self):
        for version in program.VERSIONS:
            for name, blocker in (('rotation_variance', 'INSTANCE_RANDOM_ROTATION_ATTRIBUTE_GRAPH_REQUIRED'),
                                  ('deformation', 'GEOMETRY_BASIS_REQUIRED')):
                with self.subTest(version=version, control=name):
                    with self.assertRaisesRegex(ValueError, blocker):
                        domains.control_write_plan(domains.GEOMETRY, name, 1, version, observations={})

    def test_same_build_operator_fields_ports_and_approved_original_digest(self):
        proposal = ROOT / 'handover/evidence/20261005/product/control-decisions-proposal.md'
        self.assertEqual(hashlib.sha256(proposal.read_bytes()).hexdigest(),
                         '7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e')
        for host in self.hosts():
            with self.subTest(version=host.version):
                self.assertEqual(host.operator['source']['section_sha256'],
                                 'b47a35a99cfd15f0c85143a3fed309c1a2f30704183ef7565bd52af1f7306c77')
                for name, (kind, _) in program.GATES.items():
                    self.assertEqual(host.operator['parameters'][name]['type'], kind)
                    self.assertEqual(host.operator['parameters'][name]['size'], 1)
                self.assertEqual(host.operator['interface']['input_labels'][0]['api_index'], 0)
                self.assertIsNone(host.operator['interface']['port_signature']['full_node_port_arity'])
                self.assertEqual(len(program.initialization_plan()), len(program.GATES))

    def test_positive_endpoints_only_write_owned_snippet_and_read_actual_parameter(self):
        for host in self.hosts():
            for value in (.125, 1, 100):
                with self.subTest(version=host.version, value=value):
                    before, context = host.observe(), host.context()
                    plan = program.plan_control(host.version, value, context, before)
                    self.assertEqual(host.observe(), before)
                    self.assertEqual(host.context(), context)
                    writes = program.validate_plan(plan, context, before)
                    self.assertEqual([(write['role'], write['parm']) for write in writes],
                                     [(program.ROLE, 'snippet')])
                    self.assertIn('(@P.x - (-2)) / (4)', writes[0]['value'])
                    self.assertIn('sin(deform_phase) * v@N', writes[0]['value'])
                    host.apply(plan)
                    program.validate_plan(plan, host.context(), host.observe(), after_mutation=True)
                    result = program.control_readback(host.version, host.context(), host.observe())
                    self.assertEqual(result['value'], value)
                    self.assertEqual(result['status'], 'BLOCKED')
                    self.assertEqual(result['evidence_scope'], 'parameters_only')
                    self.assertIn('downstream_transform_and_copytopoints_consumption', result['missing_evidence'])
                    self.assertEqual({key: fact for key, fact in before.items() if key[1] != 'snippet'},
                                     {key: fact for key, fact in host.observe().items() if key[1] != 'snippet'})

    def test_zero_uses_upstream_rest_not_previous_output_and_guarded_rollback(self):
        for host in self.hosts():
            first = program.plan_control(host.version, 10, host.context(), host.observe())
            host.apply(first)
            previous = host.parameters['snippet'].eval()
            plan = program.plan_control(host.version, 0, host.context(), host.observe())
            host.apply(plan)
            self.assertEqual(host.parameters['snippet'].eval(), 'float deform_amplitude = 0;\n')
            self.assertNotIn('@P', host.parameters['snippet'].eval())
            self.assertEqual(program.control_readback(host.version, host.context(), host.observe())['value'], 0)
            rollback = program.rollback_plan(plan, host.context(), host.observe())
            self.assertEqual(rollback[0]['value'], previous)
            host.parameters['snippet'].set(rollback[0]['value'])
            self.assertEqual(program.control_readback(host.version, host.context(), host.observe())['value'], 10)

    def test_invalid_control_values_and_missing_basis_refused(self):
        host = BottomHost(program.VERSIONS[0])
        for value in (True, '1', -1, 101, float('nan'), float('inf'), 10 ** 1000):
            with self.subTest(value=repr(value)), self.assertRaises(program.GeometryControlsError):
                program.plan_control(host.version, value, host.context(), host.observe())
        for context in (None, {}, {'basis': {}}):
            with self.subTest(context=context), self.assertRaises(program.GeometryControlsError):
                program.source_program(host.version, 0, context)
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_NATIVE_VERSION'):
            program.source_program('22.0.430', 1, host.context())

    def test_source_normals_ids_storage_topology_and_axes_refused(self):
        host = BottomHost(program.VERSIONS[0])
        mutations = ('no_N', 'zero_N', 'non_unit_N', 'vertex_N', 'no_id', 'duplicate_id', 'bool_id',
                     'float_id', 'array_N', 'bool_size', 'packed', 'invalid_polygon', 'empty', 'no_attributes',
                     'world', 'wrong_output', 'foreign_source', 'zero_span', 'nonfinite_P')
        for mutation in mutations:
            source = copy.deepcopy(host.source)
            attributes = source['point_attributes']
            if mutation == 'no_N': attributes.pop('N')
            if mutation == 'zero_N': attributes['N']['values'][0] = [0., 0., 0.]
            if mutation == 'non_unit_N': attributes['N']['values'][0] = [0., 2., 0.]
            if mutation == 'vertex_N': attributes['N']['owner'] = 'vertex'
            if mutation == 'no_id': attributes.pop('id')
            if mutation == 'duplicate_id': attributes['id']['values'][1] = 5
            if mutation == 'bool_id': attributes['id']['values'][0] = True
            if mutation == 'float_id': attributes['id']['precision'] = 'float32'
            if mutation == 'array_N': attributes['N']['is_array'] = True
            if mutation == 'bool_size': attributes['N']['size'] = True
            if mutation == 'packed': source['primitive_types'] = ['PackedGeometry']
            if mutation == 'invalid_polygon': source['polygons'][0][0] = 100
            if mutation == 'empty': source['points'] = 0
            if mutation == 'no_attributes': source['point_attributes'] = None
            if mutation == 'world': source['space'] = 'world'
            if mutation == 'wrong_output': source['output'] = True
            if mutation == 'foreign_source': source['node_path'] = '/obj/other/source'
            if mutation == 'zero_span':
                for position in attributes['P']['values']: position[0] = 1.
            if mutation == 'nonfinite_P': attributes['P']['values'][0][0] = float('nan')
            with self.subTest(mutation=mutation), self.assertRaises(program.GeometryControlsError):
                program.freeze_basis(host.version, source, local_x_axis=[1, 0, 0], task_id='g03_task',
                    task_root=host.root, input_version='v1', basis_input_sha256='a' * 64)
        for axis in (None, [0, 1, 0], [True, 0, 0], [1, 0], [2, 0, 0]):
            with self.subTest(axis=axis), self.assertRaisesRegex(ValueError, 'GEOMETRY_LOCAL_X_AXIS_REQUIRED'):
                program.freeze_basis(host.version, host.source, local_x_axis=axis, task_id='g03_task',
                    task_root=host.root, input_version='v1', basis_input_sha256='a' * 64)

    def test_basis_graph_ownership_and_connection_drift_refused(self):
        host = BottomHost(program.VERSIONS[0])
        for role, key, value in ((program.ROLE, 'editable', False), (program.ROLE, 'task_owned', False),
                                (program.ROLE, 'type', 'custom_wrangle'), (program.ROLE, 'bypassed', True),
                                (program.ROLE, 'path', '/obj/foreign/wrangle'),
                                (program.ROLE, 'native_version', program.VERSIONS[1]),
                                ('instance_transform', 'task_id', 'other'),
                                ('instance_transform', 'inputs', []), ('instance_source', 'input_version', 'v2'),
                                (program.ROLE, 'space', 'world'),
                                ('instance_source', 'inputs', [dict(input_index=0, output_index=0,
                                    node_path=host.nodes[program.ROLE]['path'])])):
            context = host.context()
            context['nodes'][role][key] = value
            with self.subTest(role=role, key=key), self.assertRaises(program.GeometryControlsError):
                program.plan_control(host.version, 1, context, host.observe())
        for field, value in (('span_x', 8.), ('phase', 1.), ('unit', 'meters'), ('content_sha256', 'b' * 64)):
            context = host.context()
            context['basis'][field] = value
            if field != 'content_sha256':
                context['basis']['content_sha256'] = program.basis_content_sha256(context['basis'])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'GEOMETRY_BASIS_CHANGED'):
                program.plan_control(host.version, 1, context, host.observe())
        context = host.context()
        context['nodes'][program.ROLE]['inputs'][0]['input_index'] = False
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_SOURCE_CONNECTION_REQUIRED'):
            program.plan_control(host.version, 1, context, host.observe())

    def test_actual_parameter_gates_drivers_menu_and_types_refused(self):
        host = BottomHost(program.VERSIONS[0])
        for name, field, value in (('snippet', 'driven', True), ('snippet', 'locked', True),
            ('snippet', 'disabled', True), ('snippet', 'hidden', True), ('snippet', 'size', True),
            ('snippet', 'type', 'float'), ('group', 'value', 'artist'), ('bindings', 'value', 1),
            ('vex_outputmask', 'value', '*'), ('vex_updatenmls', 'value', 1), ('class', 'value', True),
            ('class', 'menu_tokens', ['point']), ('class', 'menu_uses_token_value', None)):
            observed = host.observe()
            observed[program.ROLE, name][field] = value
            with self.subTest(name=name, field=field), self.assertRaises(program.GeometryControlsError):
                program.plan_control(host.version, 1, host.context(), observed)
        observed = host.observe()
        observed[program.ROLE, 'snippet']['value'] = '@P *= 2;'
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_PROGRAM_READBACK_MISMATCH'):
            program.plan_control(host.version, 1, host.context(), observed)

    def test_token_and_index_menu_representations(self):
        for host in self.hosts():
            host.parameters['class'].captured['menu_uses_token_value'] = True
            host.parameters['class'].value = 'point'
            plan = program.plan_control(host.version, 1, host.context(), host.observe())
            host.apply(plan)
            self.assertEqual(program.control_readback(host.version, host.context(), host.observe())['value'], 1)
            observed = host.observe()
            observed[program.ROLE, 'class'].update(menu_uses_token_value=False,
                menu_tokens=tuple(observed[program.ROLE, 'class']['menu_tokens']), value='point')
            plan = program.plan_control(host.version, 2, host.context(), observed)
            writes = program.validate_plan(plan, host.context(), observed)
            observed[program.ROLE, 'snippet']['value'] = writes[0]['value']
            program.validate_plan(plan, host.context(), observed, after_mutation=True)
            self.assertEqual(program.control_readback(host.version, host.context(), observed)['value'], 2)

    def test_observed_value_not_request_echo_and_program_tampering_refused(self):
        host = BottomHost(program.VERSIONS[0])
        plan = program.plan_control(host.version, 100, host.context(), host.observe())
        host.parameters['snippet'].set(program.source_program(host.version, 1, host.context())['program'])
        self.assertEqual(program.control_readback(host.version, host.context(), host.observe())['value'], 1)
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_PARAMETER_READBACK_MISMATCH'):
            program.validate_plan(plan, host.context(), host.observe(), after_mutation=True)
        for text in ('float deform_amplitude = nan;\n', 'float deform_amplitude = 1;\n',
                     program.source_program(host.version, 1, host.context())['program'] + '@P *= 2;\n'):
            host.parameters['snippet'].set(text)
            with self.subTest(text=text), self.assertRaises(program.GeometryControlsError):
                program.control_readback(host.version, host.context(), host.observe())

    def test_seal_context_and_snapshot_mutation_block_apply_and_rollback(self):
        host = BottomHost(program.VERSIONS[0])
        plan = program.plan_control(host.version, 1, host.context(), host.observe())
        for modified in (replace(plan, value=100), replace(plan, writes_json='[]'), replace(plan, seal='0' * 64)):
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                program.validate_plan(modified, host.context(), host.observe())
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
            program.validate_plan(plan, host.context(), host.observe(), after_mutation='yes')
        context = host.context()
        context['nodes']['instance_transform']['extra_artist_setting'] = 2.
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_CONTEXT_CHANGED'):
            program.validate_plan(plan, context, host.observe())
        context = host.context()
        context['source']['frame'] = 2.
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_BASIS_CHANGED'):
            program.validate_plan(plan, context, host.observe())
        observed = host.observe()
        observed[program.ROLE, 'snippet']['expression'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_PARAMETER_READBACK_MISMATCH'):
            program.validate_plan(plan, host.context(), observed)
        host.apply(plan)
        host.parameters['snippet'].set('artist override')
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_PARAMETER_READBACK_MISMATCH'):
            program.rollback_plan(plan, host.context(), host.observe())

    def test_collectors_require_independent_inputs_and_never_acquire_or_cook_geometry(self):
        host = BottomHost(program.VERSIONS[0])
        fact = program.collect_source_geometry(host.geometry, lambda geometry: geometry.observe())
        self.assertEqual(fact, host.source)
        fact['point_attributes']['P']['values'][0][0] = 20.
        self.assertNotEqual(fact, host.geometry.observe())
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_REST_SOURCE_REQUIRED'):
            program.collect_source_geometry(None, lambda geometry: self.fail('must not invoke collector'))
        with self.assertRaisesRegex(ValueError, 'GEOMETRY_REST_SOURCE_REQUIRED'):
            program.collect_source_geometry(host.geometry, lambda geometry: {'requested_deformation': 100})


    def test_empty_or_unregistered_owned_driver_is_never_adopted(self):
        for host in self.hosts():
            host.parameters['snippet'].set('')
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PROGRAM_READBACK_MISMATCH'):
                program.plan_control(host.version, 1, host.context(), host.observe())
            host.parameters['snippet'].set(program.source_program(host.version, 0, host.context())['program'])
            for mutation in ('missing', 'caller_origin', 'uninitialized', 'unregistered', 'foreign_basis',
                             'foreign_task', 'wrong_initial_program', 'wrong_gates'):
                context = host.context()
                if mutation == 'missing': context.pop('initialization')
                if mutation == 'caller_origin': context['initialization']['origin'] = 'caller_json'
                if mutation == 'uninitialized': context['initialization']['initialized'] = False
                if mutation == 'unregistered': context['initialization']['registered'] = False
                if mutation == 'foreign_basis': context['initialization']['basis_sha256'] = 'b' * 64
                if mutation == 'foreign_task': context['initialization']['task_id'] = 'other'
                if mutation == 'wrong_initial_program': context['initialization']['initial_program_sha256'] = 'b' * 64
                if mutation == 'wrong_gates': context['initialization']['gates_sha256'] = 'b' * 64
                with self.subTest(version=host.version, mutation=mutation), self.assertRaisesRegex(
                        ValueError, 'GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED'):
                    program.plan_control(host.version, 1, context, host.observe())


if __name__ == '__main__':
    unittest.main(verbosity=2)
