from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_program as program
from houdini_bridge.native_rbd_controls_host import Host, BASIS_KEY, PROGRAM_KEY
from test_native_flip_rbd_domains import fact

ROOT = Path(__file__).resolve().parents[2]


class EnumValue:
    def __init__(self, name):
        self.value = name

    def name(self):
        return self.value

    def __str__(self):
        return 'hou.enum.' + self.value


class Attribute:
    def __init__(self, name, kind, size, storage):
        self.spec = name, kind, size, storage

    def name(self):
        return self.spec[0]

    def dataType(self):
        return EnumValue(self.spec[1])

    def size(self):
        return self.spec[2]

    def numericDataType(self):
        return EnumValue(self.spec[3])

    def isArrayType(self):
        return False


class Point:
    def __init__(self, number, position, values):
        self.index, self.pos, self.values = number, position, values

    def number(self):
        return self.index

    def position(self):
        return self.pos

    def attribValue(self, name):
        return self.values[name]


class Primitive:
    def __init__(self, points, values, embedded=None):
        self.points, self.values, self.embedded = points, values, embedded
        self.pivot = (0., 0., 0.)
        self.matrix = (1., 0., 0., 0., 1., 0., 0., 0., 1.)

    def type(self):
        return EnumValue('PackedGeometry' if self.embedded else 'Polygon')

    def vertices(self):
        return [SimpleNamespace(point=lambda point=point: point) for point in self.points]

    def attribValue(self, name):
        return self.values[name]

    def transform(self):
        return SimpleNamespace(asTuple=lambda: self.matrix)

    def fullTransform(self):
        position = self.points[0].position()
        return SimpleNamespace(asTuple=lambda: (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., *position, 1.))

    def intrinsicValue(self, name):
        if name != 'pivot':
            raise ValueError(name)
        return self.pivot

    def getEmbeddedGeometry(self):
        return self.embedded

    def isClosed(self):
        return True


class Geometry:
    def __init__(self, points, primitives, point_attributes, primitive_attributes):
        self.point_list, self.primitive_list = points, primitives
        self.point_fields, self.primitive_fields = point_attributes, primitive_attributes

    def freeze(self, read_only=True):
        return copy.deepcopy(self)

    def points(self):
        return self.point_list

    def prims(self):
        return self.primitive_list

    def pointAttribs(self):
        return self.point_fields

    def primAttribs(self):
        return self.primitive_fields


def packed_geometry():
    inside_points = [Point(index, position, {}) for index, position in enumerate(
        ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)))]
    embedded = Geometry(inside_points, [Primitive(inside_points, {})], [], [])
    points = [Point(index, (float(index) * 3., 0., 0.),
        {'v': (2., -3., 4.), 'w': (0., 1., 0.), 'active': 1, 'temperature': 20.}) for index in range(2)]
    primitives = [Primitive([point], {'name': 'piece_' + str(index)}, embedded)
                  for index, point in enumerate(points)]
    return Geometry(points, primitives,
        [Attribute('v', 'Float', 3, 'Float64'), Attribute('w', 'Float', 3, 'Float64'),
         Attribute('active', 'Int', 1, 'Int32'), Attribute('temperature', 'Float', 1, 'Float64')],
        [Attribute('name', 'String', 1, 'string')])


class Parameter:
    def __init__(self, node, name, value):
        self.node, self.name, self.value = node, name, value

    def path(self):
        return self.node.path() + '/' + self.name

    def set(self, value, **kwargs):
        self.value = value


class Node:
    def __init__(self, role, kind, hou):
        self.role, self.kind, self.hou = role, kind, hou
        self.parameters, self.data, self.connections = {}, {}, []
        self.native_geometry = packed_geometry() if role == 'configure' else None
        self.break_output = False
        self.input_reads = 0

    def path(self):
        return '/obj/task/' + self.role

    def type(self):
        return SimpleNamespace(name=lambda: self.kind, category=lambda: EnumValue('Sop'))

    def isEditable(self):
        return True

    def sessionId(self):
        return id(self)

    def isBypassed(self):
        return False

    def errors(self):
        return ()

    def userData(self, key):
        return self.data.get(key)

    def setUserData(self, key, value):
        self.data[key] = value

    def destroyUserData(self, key):
        self.data.pop(key, None)

    def parm(self, name):
        return self.parameters[name]

    def inputConnections(self):
        return self.connections

    def setInput(self, input_index, source, output_index=0):
        self.connections = [SimpleNamespace(inputIndex=lambda: input_index, outputIndex=lambda: output_index,
                                           inputNode=lambda: source)]

    def inputGeometry(self, input_index):
        self.input_reads += 1
        return next(connection.inputNode().geometryAtFrame(self.hou.frame()) for connection in self.connections
                    if connection.inputIndex() == input_index)

    def geometryAtFrame(self, frame, output_index=0):
        if self.role == 'configure':
            return self.native_geometry.freeze()
        if self.role == program.ROLE:
            geometry = self.connections[0].inputNode().geometryAtFrame(frame)
            snippet = self.parm('snippet').value
            if snippet:
                names = json.loads('[' + re.search(r'piece_ids\[\] = array\((.*?)\);', snippet).group(1) + ']')
                vectors = [tuple(float(value) for value in vector.split(',')) for vector in
                           re.findall(r'set\(([^()]*)\)', snippet)]
                for primitive in geometry.prims():
                    name = primitive.attribValue('name')
                    if name in names:
                        primitive.points[0].values['v'] = vectors[names.index(name)]
            if self.break_output:
                geometry.points()[0].values['v'] = (999., 999., 999.)
            return geometry
        return self.inputGeometry(0)


def native_fixture(version):
    hou = SimpleNamespace(current_frame=12., version=version)
    hou.frame = lambda: hou.current_frame
    hou.setFrame = lambda frame: setattr(hou, 'current_frame', frame)
    hou.fps = lambda: 24.
    hou.applicationVersionString = lambda: hou.version
    nodes = {role: Node(role, kind, hou) for role, kind in
             (('configure', 'rbdconfigure'), (program.ROLE, 'attribwrangle'), ('solver', 'rbdbulletsolver'))}
    hou.node = lambda path: next((node for node in nodes.values() if node.path() == path), None)
    nodes[program.ROLE].setInput(0, nodes['configure'])
    nodes['solver'].setInput(0, nodes[program.ROLE])
    fields = {name: fact(value, kind) for name, (kind, value) in program.GATES.items()}
    fields['class'].update(menu_tokens=['detail', 'primitive', 'point'], menu_uses_token_value=False)
    fields['snippet'] = fact('', 'string')
    solver_fields = dict(startframe=fact(1, 'integer'), overwriteattributes=fact('active animated deforming', 'string'),
                         usescale=fact(0, 'toggle'), timescale=fact(1.))
    for node, parameters in ((nodes[program.ROLE], fields), (nodes['solver'], solver_fields)):
        for name, record in parameters.items():
            node.parameters[name] = Parameter(node, name, record['value'])
    nodes['configure'].parameters['createpackedfragments'] = Parameter(nodes['configure'], 'createpackedfragments', 1)
    identity = dict(task_id='task', version=version, pid=123, launch_nonce='nonce', session_id='session',
                    process_generation='generation', plugin_build='f' * 64, scene_epoch=0)
    def observe(node, name, **kwargs):
        template = fields[name] if node.role == program.ROLE else solver_fields[name]
        return dict(copy.deepcopy(template), value=copy.deepcopy(node.parm(name).value))
    def write(parm, value):
        before = copy.deepcopy(parm.value)
        parm.set(value)
        return dict(before=before, after=parm.value)
    globals_map = {'_fx_planned_owned_root': lambda roles, pack: '/obj/task',
        '_root_lease_check': lambda root, **kwargs: {'task_id': 'task'},
        '_host_identity': lambda: copy.deepcopy(identity), '_fx_planned_observation': observe,
        '_set_parm_verified': write,
        '_fx_apply_fresh_domain_plan': lambda writes, roles, fresh: [write(nodes[item['role']].parm(item['parm']), item['value']) for item in writes]}
    roles = {role: node.path() for role, node in nodes.items()}
    return Host(globals_map, hou), nodes, roles, hou, identity


class NativeRbdControlsProgramTests(unittest.TestCase):
    def test_conditional_runtime_route_defers_only_r05_to_actual_host_guards(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                for value in (0., 1000.):
                    self.assertEqual(core.conditional_runtime_route(core.RBD, 'velocity_variance', value, version),
                                     'bridge.rbd-velocity-program/1')
                self.assertEqual(core.control_contract(core.RBD, version)['velocity_variance']['native_status'], 'blocked')
                with self.assertRaisesRegex(core.NativeFlipRbdDomainError, 'RBD_VELOCITY_VARIANCE_ATTRIBUTE_CONTRACT_REQUIRED'):
                    core.control_write_plan(core.RBD, 'velocity_variance', 0., version, observations={})
                for name in ('fracture_scale', 'fracture_variance', 'impact_spread', 'piece_scale', 'impulse_scale'):
                    contract = core.control_contract(core.RBD, version)[name]
                    with self.subTest(control=name), self.assertRaisesRegex(core.NativeFlipRbdDomainError, contract['blocker']):
                        core.conditional_runtime_route(core.RBD, name, contract['minimum'], version)
                for name in ('collision_separation', 'collision_passes'):
                    contract = core.control_contract(core.FLIP, version)[name]
                    with self.subTest(control=name), self.assertRaisesRegex(core.NativeFlipRbdDomainError, contract['blocker']):
                        core.conditional_runtime_route(core.FLIP, name, contract['minimum'], version)
                self.assertIsNone(core.conditional_runtime_route(core.RBD, 'substeps', 1, version))
                for invalid in (True, -1, 1001, float('inf'), float('nan')):
                    with self.subTest(value=invalid), self.assertRaisesRegex(core.NativeFlipRbdDomainError, 'INVALID_NATIVE_CONTROL_VALUE'):
                        core.conditional_runtime_route(core.RBD, 'velocity_variance', invalid, version)
        for value in (0., 1000.):
            self.assertEqual(core.conditional_runtime_route(core.RBD, 'velocity_variance', value, '22.0.459'),
                             'bridge.rbd-velocity-program/1')
        self.assertEqual(core.control_contract(core.RBD, '22.0.459')['velocity_variance']['native_status'], 'blocked')
        with self.assertRaisesRegex(core.NativeFlipRbdDomainError, 'UNSUPPORTED_NATIVE_VERSION'):
            core.conditional_runtime_route(core.RBD, 'velocity_variance', 0., '22.0.999')
        with self.assertRaisesRegex(core.NativeFlipRbdDomainError, 'UNKNOWN_NATIVE_CONTROL'):
            core.conditional_runtime_route(core.RBD, 'foreign', 0., core.VERSIONS[0])

    def test_unregistered_optional_carrier_identity_gap_is_advisory_but_registered_gap_rejects(self):
        for version in core.VERSIONS:
            host, nodes, roles, hou, identity = native_fixture(version)
            identity['task_id'] = 'foreign-task'
            before = {role: {name: copy.deepcopy(parm.value) for name, parm in node.parameters.items()}
                      for role, node in nodes.items()}
            result = host.initialize({}, roles, {}, {'configure', program.ROLE})
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['code'], 'RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED')
            self.assertEqual(nodes[program.ROLE].data, {})
            self.assertEqual({role: {name: parm.value for name, parm in node.parameters.items()}
                              for role, node in nodes.items()}, before)
            with self.assertRaisesRegex(ValueError, 'RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED'):
                host.observations({'velocity_variance': 1.}, roles, {})
            for key in (BASIS_KEY, PROGRAM_KEY):
                nodes[program.ROLE].setUserData(key, 'foreign-registration')
                with self.subTest(version=version, key=key), self.assertRaisesRegex(
                        ValueError, 'RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED'):
                    host.initialize({}, roles, {}, {'configure', program.ROLE})
                nodes[program.ROLE].destroyUserData(key)

    def test_non_velocity_changes_do_not_collect_and_mixed_activation_rejects_before_mutation(self):
        host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
        nodes['configure'].native_geometry = None
        self.assertEqual(host.observations({'activation_frame': 17}, roles, {}), {})
        changes = {'activation_frame': 17, 'velocity_variance': 3.}
        for call in (lambda: host.observations(changes, roles, {}),
                     lambda: core.candidate_write_plan(core.RBD, changes, core.VERSIONS[0])):
            with self.assertRaisesRegex(ValueError, 'RBD_INITIAL_VELOCITY_ACTIVATION_COMBINATION_UNSUPPORTED'):
                call()
        self.assertEqual(nodes[program.ROLE].data, {})
        self.assertEqual(nodes[program.ROLE].parm('snippet').value, '')

    def test_passthrough_initialization_preserves_missing_basis_and_activation(self):
        for version in core.VERSIONS:
            host, nodes, roles, hou, identity = native_fixture(version)
            before = copy.deepcopy(nodes['configure'].native_geometry.points()[0].values)
            host.initialize({}, roles, {}, {'configure', program.ROLE})
            self.assertEqual(nodes[program.ROLE].parm('snippet').value, '')
            self.assertEqual(nodes[program.ROLE].data, {})
            self.assertEqual(nodes['configure'].parm('createpackedfragments').value, 0)
            self.assertEqual(nodes['configure'].native_geometry.points()[0].values, before)

    def test_real_host_collector_candidate_carrier_and_native_input_consumption(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = native_fixture(version)
                before = copy.deepcopy(nodes['configure'].native_geometry)
                observations = host.observations({'velocity_variance': 3.}, roles, {})
                self.assertTrue(set(map(tuple, core.control_contract(core.RBD, version)['velocity_variance']['context_parms'])) <= set(observations))
                self.assertEqual(nodes[program.ROLE].data, {})
                self.assertEqual(hou.frame(), 12.)
                writes = core.candidate_write_plan(core.RBD, {'velocity_variance': 3.}, version, observations=observations)
                write = writes[0]
                item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
                host.prepare(item)
                result = host.write(item, roles, {})
                self.assertEqual(result['after'], 3.)
                self.assertGreater(nodes['solver'].input_reads, 0)
                self.assertEqual(nodes['configure'].native_geometry.points()[0].values, before.points()[0].values)
                self.assertNotEqual(nodes[program.ROLE].geometryAtFrame(1).points()[0].values['v'], (2., -3., 4.))
                self.assertEqual(core.control_readback(core.RBD, 'velocity_variance', {}, version,
                    observations=host.observations({'velocity_variance': 3.}, roles, {})), 3.)
                saved_data = copy.deepcopy(nodes[program.ROLE].data)
                saved_snippet = nodes[program.ROLE].parm('snippet').value
                identity.update(pid=456, launch_nonce='new-nonce', process_generation='new-generation', session_id='new-session')
                with self.assertRaisesRegex(ValueError, 'RBD_VELOCITY_AUTHORITY_REQUIRED'):
                    host.readback(roles, {}, {'velocity_variance': 3.})
                self.assertEqual(nodes[program.ROLE].data, saved_data)
                self.assertEqual(nodes[program.ROLE].parm('snippet').value, saved_snippet)

    def test_zero_restores_frozen_base_and_feedback_does_not_accumulate(self):
        for version in core.VERSIONS:
            host, nodes, roles, hou, identity = native_fixture(version)
            first_seed = None
            for value in (5., 8., 0.):
                observations = host.observations({'velocity_variance': value}, roles, {}, task_seed=123)
                writes = core.candidate_write_plan(core.RBD, {'velocity_variance': value}, version, observations=observations)
                item = dict(native_write=writes[0], node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
                host.prepare(item)
                host.write(item, roles, {})
                basis = json.loads(nodes[program.ROLE].userData(BASIS_KEY))
                first_seed = basis['task_seed'] if first_seed is None else first_seed
                self.assertEqual(basis['task_seed'], first_seed)
            self.assertEqual(nodes[program.ROLE].geometryAtFrame(1).points()[0].values['v'], (2., -3., 4.))
            with self.assertRaisesRegex(ValueError, 'FROZEN_VELOCITY_BASIS_REQUIRED'):
                host.observations({'velocity_variance': 1.}, roles, {}, task_seed=124)

    def test_forged_plan_original_guard_replacement_and_basis_mutation_reject(self):
        host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
        observations = host.observations({'velocity_variance': 3.}, roles, {}, task_seed=4)
        writes = core.candidate_write_plan(core.RBD, {'velocity_variance': 3.}, core.VERSIONS[0], observations=observations)
        for change in ('public_value', 'value', 'guards', 'missing_kind'):
            mutated = copy.deepcopy(writes)
            if change == 'guards':
                mutated[0]['frozen_readback_guards'] = []
            elif change == 'missing_kind':
                mutated[0].pop('value_kind')
            else:
                mutated[0][change] = 20 if change == 'public_value' else ''
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'UNTRUSTED_RBD_VELOCITY_WRITE'):
                core.validate_control_write_plan(mutated, observations)
        changed = copy.deepcopy(observations)
        changed[(program.ROLE, '@basis')]['task_seed'] = 7
        with self.assertRaises(ValueError):
            core.validate_control_write_plan(writes, changed)

    def test_missing_packed_active_owner_timing_and_continuous_overwrite_reject(self):
        for mutation in ('active', 'v', 'duplicate_name', 'timing', 'world_scale', 'overwrite', 'owner', 'wrong_wire'):
            host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
            if mutation == 'active':
                nodes['configure'].native_geometry.points()[0].values['active'] = 0
            elif mutation == 'v':
                nodes['configure'].native_geometry.points()[0].values['v'] = (float('nan'), 0., 0.)
            elif mutation == 'duplicate_name':
                nodes['configure'].native_geometry.prims()[1].values['name'] = 'piece_0'
            elif mutation == 'timing':
                nodes['solver'].parm('timescale').set(.5)
            elif mutation == 'world_scale':
                nodes['solver'].parm('usescale').set(1)
            elif mutation == 'overwrite':
                nodes['solver'].parm('overwriteattributes').set('active v*')
            elif mutation == 'owner':
                identity['task_id'] = 'foreign'
            else:
                nodes['solver'].setInput(0, nodes['configure'])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                host.observations({'velocity_variance': 1.}, roles, {})
            self.assertEqual(nodes[program.ROLE].data, {})
            self.assertEqual(nodes[program.ROLE].parm('snippet').value, '')

    def test_native_output_failure_restores_seed_registration_and_snippet(self):
        host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
        observations = host.observations({'velocity_variance': 2.}, roles, {})
        write = core.candidate_write_plan(core.RBD, {'velocity_variance': 2.}, core.VERSIONS[0], observations=observations)[0]
        item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
        host.prepare(item)
        nodes[program.ROLE].break_output = True
        with self.assertRaisesRegex(ValueError, 'VELOCITY_CONSUMPTION_MISMATCH'):
            host.write(item, roles, {})
        item['parm'].set('')
        host.restore(item)
        self.assertEqual(nodes[program.ROLE].data, {})
        self.assertEqual(item['parm'].value, '')

    def test_late_geometry_and_userdata_drift_are_rejected_before_write(self):
        for change in ('upstream', 'userdata'):
            host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
            observations = host.observations({'velocity_variance': 2.}, roles, {}, task_seed=123)
            write = core.candidate_write_plan(core.RBD, {'velocity_variance': 2.}, core.VERSIONS[0], observations=observations)[0]
            item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
            host.prepare(item)
            if change == 'upstream':
                nodes['configure'].native_geometry.points()[0].values['temperature'] = 42.
            else:
                nodes[program.ROLE].setUserData(PROGRAM_KEY, '{}')
            with self.subTest(change=change), self.assertRaises(ValueError):
                host.write(item, roles, {})
            self.assertEqual(item['parm'].value, '')

    def test_embedded_shape_and_solver_consumer_output_drift_are_not_parameter_success(self):
        host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
        observations = host.observations({'velocity_variance': 1.}, roles, {})
        write = core.candidate_write_plan(core.RBD, {'velocity_variance': 1.}, core.VERSIONS[0], observations=observations)[0]
        item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
        host.prepare(item)
        host.write(item, roles, {})
        actual = host.observations({'velocity_variance': 1.}, roles, {})
        corrupted = copy.deepcopy(actual)
        geometry = corrupted[('solver', '@input_geometry/0')]
        geometry['geometry']['primitives'][0]['embedded']['positions'][0][0] = 999.
        geometry['content_sha256'] = program._digest({key: value for key, value in geometry.items() if key != 'content_sha256'})
        with self.assertRaisesRegex(ValueError, 'VELOCITY_CONSUMPTION_MISMATCH'):
            core.validate_applied_readback([write], corrupted)

    def test_failed_feedback_rolls_back_prior_registered_basis_program_and_value(self):
        host, nodes, roles, hou, identity = native_fixture(core.VERSIONS[0])
        observations = host.observations({'velocity_variance': 1.}, roles, {}, task_seed=123)
        write = core.candidate_write_plan(core.RBD, {'velocity_variance': 1.}, core.VERSIONS[0], observations=observations)[0]
        item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
        host.prepare(item)
        host.write(item, roles, {})
        original_snippet = item['parm'].value
        original_data = copy.deepcopy(nodes[program.ROLE].data)
        observations = host.observations({'velocity_variance': 4.}, roles, {})
        write = core.candidate_write_plan(core.RBD, {'velocity_variance': 4.}, core.VERSIONS[0], observations=observations)[0]
        item = dict(native_write=write, node=nodes[program.ROLE], parm=nodes[program.ROLE].parm('snippet'))
        host.prepare(item)
        nodes[program.ROLE].break_output = True
        with self.assertRaises(ValueError):
            host.write(item, roles, {})
        item['parm'].set(original_snippet)
        host.restore(item)
        nodes[program.ROLE].break_output = False
        self.assertEqual(nodes[program.ROLE].data, original_data)
        self.assertEqual(host.readback(roles, {}, {'velocity_variance': 1.})['controls']['velocity_variance'], 1.)

    def test_current_installed_same_version_carrier_fields_match_and_default_is_passthrough(self):
        import importlib.util
        tool_spec = importlib.util.spec_from_file_location('rbd_static_capture', ROOT / 'tools/capture_native_schema.py')
        capture_tool = importlib.util.module_from_spec(tool_spec)
        tool_spec.loader.exec_module(capture_tool)
        for version in core.VERSIONS:
            path = Path('C:/Program Files/Side Effects Software') / ('Houdini ' + version) / 'houdini/otls/OPlibSop.hda'
            if not path.exists():
                self.skipTest('NOT_RUN: same-build installed Windows HDA unavailable: ' + str(path))
            records = capture_tool.index_sections(path.read_bytes())
            sections = capture_tool.index_sections(records['Sop/attribwrangle'])
            fields = capture_tool.dialog_parameters(sections['DialogScript'])
            self.assertEqual(fields['snippet']['type'], 'string')
            self.assertEqual(fields['snippet']['default_tokens'], [''])
            self.assertEqual(fields['class']['menu_tokens'][::2], ['detail', 'primitive', 'point', 'vertex', 'number'])
            self.assertEqual(fields['vex_precision']['type'], 'string')
            solver_fields = capture_tool.dialog_parameters(capture_tool.index_sections(records['Sop/rbdbulletsolver'])['DialogScript'])
            self.assertEqual(solver_fields['startframe']['type'], 'integer')


if __name__ == '__main__':
    unittest.main()
