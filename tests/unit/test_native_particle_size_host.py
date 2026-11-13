"""Native parameter, topology and geometry APIs only; no facade success substitutes."""
import copy
import hashlib
import json
import random
import unittest
from unittest.mock import patch

from houdini_bridge import native_particle_ocean_geometry_domains as core
from houdini_bridge import native_particle_size_program as program
from houdini_bridge import native_particle_size_host as host_module
from test_native_particle_size_program import BottomHost


class NativeName:
    def __init__(self, value):
        self.value = value

    def name(self):
        return self.value

    def __str__(self):
        return self.value


class NativeType(NativeName):
    def __init__(self, value, category):
        super().__init__(value)
        self.category_value = category

    def category(self):
        return NativeName(self.category_value)


class NativeAttribute:
    def __init__(self, name, fact):
        self.attribute_name = name
        self.fact = fact

    def name(self):
        return self.attribute_name

    def dataType(self):
        return NativeName(self.fact['type'])

    def numericDataType(self):
        return NativeName(self.fact['precision'])

    def size(self):
        return self.fact['size']

    def isArrayType(self):
        return self.fact['is_array']


class NativePoint:
    def __init__(self, geometry, index):
        self.geometry = geometry
        self.index = index

    def number(self):
        return self.index

    def position(self):
        return tuple(self.geometry['positions'][self.index])

    def attribValue(self, name):
        value = self.geometry['point_attributes'][name]['values'][self.index]
        return tuple(value) if isinstance(value, list) else value


class NativeVertex:
    def __init__(self, point):
        self.vertex_point = point

    def point(self):
        return self.vertex_point


class NativePrimitive:
    def __init__(self, geometry, record):
        self.geometry = geometry
        self.record = record

    def type(self):
        return NativeName(self.record['type'])

    def isClosed(self):
        return self.record['closed']

    def vertices(self):
        return tuple(NativeVertex(NativePoint(self.geometry, index)) for index in self.record['vertices'])


class NativeGeometry:
    def __init__(self, fact):
        self.fact = fact

    def points(self):
        return tuple(NativePoint(self.fact, index) for index in range(self.fact['points']))

    def prims(self):
        return tuple(NativePrimitive(self.fact, record) for record in self.fact['primitive_records'])

    def pointAttribs(self):
        return tuple(NativeAttribute(name, fact) for name, fact in self.fact['point_attributes'].items())


class NativeConnection:
    def __init__(self, fixture, destination, source, output):
        self.fixture, self.destination, self.source, self.output = fixture, destination, source, output

    def inputIndex(self):
        return self.destination

    def outputIndex(self):
        return self.output

    def inputNode(self):
        return self.fixture.native_nodes[self.source.role]


class NativeNode:
    def __init__(self, fixture, node):
        self.fixture, self.node = fixture, node
        self.userdata = {}

    def path(self):
        return self.node.path

    def type(self):
        return NativeType(self.node.kind, self.node.category)

    def parent(self):
        return NativeName(self.node.path.rsplit('/', 1)[0])

    def inputConnections(self):
        return tuple(NativeConnection(self.fixture, destination, source, output)
                     for destination, (source, output) in self.node.inputs.items())

    def geometry(self, output_index=0):
        if output_index != 0:
            raise AssertionError('collector must request exact output0')
        return NativeGeometry(self.fixture.geometry_fact(self.node.role))

    def userData(self, name):
        return self.userdata.get(name)

    def setUserData(self, name, value):
        self.userdata[name] = value

    def destroyUserData(self, name):
        self.userdata.pop(name, None)


class NativeParameter:
    def __init__(self, fixture, name):
        self.fixture, self.parameter_name = fixture, name

    def path(self):
        return self.fixture.nodes[program.ROLE].path + '/' + self.parameter_name


class NativeHou:
    def __init__(self, fixture):
        self.fixture = fixture

    def applicationVersionString(self):
        return self.fixture.version

    def node(self, path):
        return next((node for node in self.fixture.native_nodes.values() if node.path() == path), None)


class NativeHostFixture(BottomHost):
    def __init__(self, version):
        super().__init__(version)
        self.native_nodes = {role: NativeNode(self, node) for role, node in self.nodes.items()}
        self.roles = {role: node.path() for role, node in self.native_nodes.items()}
        self.pack = {'native_domain_id': core.PARTICLES}
        self.nodes[program.ROLE].path = self.roles[program.ROLE]
        self.native_nodes[program.ROLE].setUserData(host_module.BASIS_KEY, json.dumps(self.basis))
        self.copy_multiplier = 1.
        self.pscale_multiplier = 1.
        self.copy_ids_missing = False
        self.geometry_mutation = None
        self.fail_parameter = None
        self.set_calls = []
        self.parameters_api = {name: NativeParameter(self, name) for name in self.parameters}
        self.callbacks = {
            '_fx_planned_owned_root': lambda roles, pack: '/obj/p02_api',
            '_root_lease_check': lambda root, **kwargs: {'task_id': 'p02-api-task'},
            '_host_identity': lambda: dict(task_id='p02-api-task', pid=123, launch_nonce='unit-native-boundary', version=self.version),
            '_fx_configuration': lambda params: params.get('configuration', {}),
            '_fx_planned_observation': self.observe_parameter,
            '_resolve_parm_target': lambda node, names: self.parameters_api.get(names[0]),
            '_snapshot_parm_state': self.snapshot,
            '_restore_parm_snapshot': self.restore_parameter,
            '_set_parm_verified': self.set_parameter,
            '_keyframe_identity': lambda frame: frame,
        }
        self.host = host_module.Host(self.callbacks, hou_module=NativeHou(self))

    def observe_parameter(self, node, name):
        fact = self.parameters[name].observe()
        mode = self.parameters['valuetype'].value
        hidden = (name == 'singlevalue' and mode != 'const')
        if name in ('rangemethod', 'randomseed', 'randmethod', 'distribinrange', 'enablestepping'):
            hidden = mode != 'rand'
        if name in ('minvalue', 'rangevalue'):
            hidden = mode != 'rand' or self.parameters['rangemethod'].value != 'minplusrange'
        if name == 'randattrib':
            hidden = mode != 'rand' or self.parameters['randmethod'].value != 'custom'
        fact['hidden'] = fact['hidden'] or hidden
        fact['disabled'] = fact['disabled'] or hidden
        return fact

    def snapshot(self, parameter, **kwargs):
        bottom = self.parameters[parameter.parameter_name]
        return dict(mode='hom_channels', evaluated=bottom.eval(), components=[dict(
            component=parameter, mode='value', value=bottom.eval(), expression=None,
            reference_path=None, extrapolation=(NativeName('constant'), NativeName('constant')))])

    def restore_parameter(self, parameter, snapshot):
        actual = self.observe_parameter(self.native_nodes[program.ROLE], parameter.parameter_name)
        if any(actual[flag] for flag in ('driven', 'locked', 'disabled', 'hidden')):
            raise ValueError('native rollback setter rejected unavailable ' + parameter.parameter_name)
        self.parameters[parameter.parameter_name].value = copy.deepcopy(snapshot['evaluated'])

    def set_parameter(self, parameter, value):
        name = parameter.parameter_name
        actual = self.observe_parameter(self.native_nodes[program.ROLE], name)
        if any(actual[flag] for flag in ('driven', 'locked', 'disabled', 'hidden')):
            raise ValueError('native staged setter rejected unavailable ' + name)
        if self.fail_parameter == name:
            raise ValueError('injected native setter failure ' + name)
        self.parameters[name].set(value)
        self.set_calls.append((name, value))
        return dict(after=self.parameters[name].eval(), readback_verified=True)

    def geometry_fact(self, role):
        fact = super().geometry()
        fact['positions'] = [[float(index * 3), 0., 0.] for index in range(len(self.points))]
        fact['primitive_records'] = []
        if role == program.ROLE:
            if self.parameters['valuetype'].value == 'const':
                scales = [self.parameters['singlevalue'].value for point in self.points]
            else:
                seed = self.parameters['randomseed'].value
                scales = [self.parameters['minvalue'].value + self.parameters['rangevalue'].value *
                          random.Random(str(seed) + ':' + str(point['id'])).random() for point in self.points]
            fact['point_attributes']['pscale']['values'] = [scale * self.pscale_multiplier for scale in scales]
        if role == 'instance_source':
            return dict(origin='runtime_hom', points=3, primitives=1,
                        positions=[[-1., 0., 0.], [1., 0., 0.], [0., 1., 0.]],
                        point_attributes={}, primitive_records=[dict(type='Polygon', closed=True, vertices=[0, 1, 2])])
        if role in ('instances', 'output'):
            particles = self.geometry_fact(program.ROLE)
            source = self.geometry_fact('instance_source')
            positions, identities, records = [], [], []
            for index, point in enumerate(self.points):
                scale = particles['point_attributes']['pscale']['values'][index] * self.copy_multiplier
                target = particles['positions'][index]
                start = len(positions)
                positions.extend([[coordinate * scale + target[axis] for axis, coordinate in enumerate(position)]
                                  for position in source['positions']])
                identities.extend([point['id']] * len(source['positions']))
                records.append(dict(type='Polygon', closed=True, vertices=[start, start + 1, start + 2]))
            fact = dict(origin='runtime_hom', points=len(positions), primitives=len(records), positions=positions,
                        primitive_records=records, point_attributes={'id': dict(
                            owner='point', type='integer', size=1, precision='int32', is_array=False, values=identities)})
            if self.copy_ids_missing:
                fact['point_attributes'].clear()
        if self.geometry_mutation is not None:
            self.geometry_mutation(role, fact)
        return fact

    def observe(self):
        return self.host.observations(self.roles, self.pack)

    def prepared(self, changes):
        observations = self.observe()
        writes = core.candidate_write_plan(core.PARTICLES, changes, self.version, observations=observations)
        self.test_write_count(writes)
        write = writes[0]
        item = dict(native_write=write, node=self.native_nodes[program.ROLE],
                    parm=self.parameters_api[write['parm']])
        self.host.prepare(item)
        return item

    def test_write_count(self, writes):
        if len(writes) != 1:
            raise AssertionError('P02 must dispatch one complete atomic program')


NativeName.path = NativeName.name


class ParticleSizeHostTests(unittest.TestCase):
    def test_untrusted_legacy_build_returns_advisory_without_registering_basis(self):
        for version in core.VERSIONS:
            fixture = NativeHostFixture(version)
            node = fixture.native_nodes[program.ROLE]
            node.destroyUserData(host_module.BASIS_KEY)
            fixture.callbacks['_host_identity'] = lambda: dict(task_id=None, version=version)
            with patch.object(host_module.secrets, 'randbelow') as rng:
                result = fixture.host.initialize({}, fixture.roles, fixture.pack, {program.ROLE})
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['code'], 'PARTICLE_SIZE_AUTHENTICATED_HOST_REQUIRED')
                self.assertIsNone(node.userData(host_module.BASIS_KEY))
                rng.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_AUTHENTICATED_HOST_REQUIRED'):
                fixture.host.initialize({'configuration': {'particle_size_basis': dict(size=.25, task_seed=5)}},
                                        fixture.roles, fixture.pack, {program.ROLE})
            node.setUserData(host_module.BASIS_KEY, json.dumps(fixture.basis))
            with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_AUTHENTICATED_HOST_REQUIRED'):
                fixture.host.initialize({}, fixture.roles, fixture.pack, set())

    def test_native_staged_roundtrip_and_combined_semantic_mapping(self):
        for version in core.VERSIONS:
            fixture = NativeHostFixture(version)
            for changes in ({'size_variance': 100}, {'size': .6, 'size_variance': 50},
                            {'size': .4}, {'size_variance': 0}, {'size_variance': 25}):
                with self.subTest(version=version, changes=changes):
                    before = fixture.observe()
                    item = fixture.prepared(changes)
                    mapping = core.semantic_write_map([item['native_write']], changes)
                    self.assertEqual(set(mapping[program.ROLE, 'singlevalue']), set(changes))
                    result = fixture.host.write(item, fixture.roles, fixture.pack)
                    after = fixture.observe()
                    core.validate_applied_readback([item['native_write']], after)
                    self.assertEqual(result['evidence_scope'], 'actual_pscale_and_unpacked_copy_geometry')
                    self.assertEqual(result['missing_evidence'], ['cross_frame_and_reopen_stability',
                        'native_random_distribution_verification', 'full_copy_transform_and_connectivity'])
                    values = {key: fact['value'] for key, fact in after.items() if 'value' in fact}
                    for name, value in changes.items():
                        self.assertAlmostEqual(core.control_readback(core.PARTICLES, name, values, version, observations=after), value)
                    self.assertEqual(after['simulation', '@geometry/0'], before['simulation', '@geometry/0'])
                    fixture.host.restore(item)
                    self.assertEqual(fixture.observe(), before)
                    fixture.host.write(item, fixture.roles, fixture.pack)
            self.assertEqual(fixture.set_calls[0], ('valuetype', 'const'))

    def test_registered_constant_size_still_uses_legacy_single_parameter_path(self):
        fixture = NativeHostFixture(core.VERSIONS[0])
        writes = core.control_write_plan(core.PARTICLES, 'size', .4,
                                         fixture.version, observations=fixture.observe())
        self.assertEqual([(write['parm'], write['value']) for write in writes], [('singlevalue', .4)])
        self.assertNotIn('particle_size_plan', writes[0])

    def test_fresh_basis_generates_seed_once_and_preserves_legacy_without_basis(self):
        for version in core.VERSIONS:
            fixture = NativeHostFixture(version)
            node = fixture.native_nodes[program.ROLE]
            node.destroyUserData(host_module.BASIS_KEY)
            with patch.object(host_module.secrets, 'randbelow', side_effect=(927, 928)) as rng:
                first = fixture.host.initialize({}, fixture.roles, fixture.pack, {program.ROLE})
                second = fixture.host.initialize({}, fixture.roles, fixture.pack, set())
                self.assertEqual(first, second)
                self.assertEqual(first['task_seed'], 927)
                self.assertEqual(rng.call_count, 1)
            node.destroyUserData(host_module.BASIS_KEY)
            result = fixture.host.initialize({}, fixture.roles, fixture.pack, set())
            self.assertEqual(result['status'], 'blocked')
            self.assertIsNone(node.userData(host_module.BASIS_KEY))
            observed = BottomHost(version).observe()
            observed.pop((program.ROLE, '@size_basis'))
            writes = core.control_write_plan(core.PARTICLES, 'size', .4, version, observations=observed)
            self.assertEqual(writes[0]['value'], .4)
            self.assertNotIn('particle_size_plan', writes[0])

    def test_explicit_basis_must_match_native_singlevalue_and_is_immutable(self):
        fixture = NativeHostFixture(core.VERSIONS[0])
        node = fixture.native_nodes[program.ROLE]
        node.destroyUserData(host_module.BASIS_KEY)
        for supplied in ({'size': .5, 'task_seed': 1}, {'size': .25, 'task_seed': True}):
            with self.assertRaises(ValueError):
                fixture.host.initialize({'configuration': {'particle_size_basis': supplied}},
                                        fixture.roles, fixture.pack, {program.ROLE})
            self.assertIsNone(node.userData(host_module.BASIS_KEY))
        valid = dict(size=.25, task_seed=71)
        fixture.host.initialize({'configuration': {'particle_size_basis': valid}}, fixture.roles, fixture.pack, {program.ROLE})
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_BASIS_CHANGED'):
            fixture.host.initialize({'configuration': {'particle_size_basis': dict(size=.25, task_seed=72)}},
                                    fixture.roles, fixture.pack, {program.ROLE})

    def test_partial_native_write_failure_restores_every_field_and_userdata(self):
        for version in core.VERSIONS:
            for name in ('singlevalue', 'randmethod', 'rangemethod', 'minvalue', 'rangevalue'):
                fixture = NativeHostFixture(version)
                before = fixture.observe()
                item = fixture.prepared({'size': .5, 'size_variance': 100})
                fixture.fail_parameter = name
                with self.subTest(version=version, name=name), self.assertRaises(ValueError):
                    fixture.host.write(item, fixture.roles, fixture.pack)
                fixture.fail_parameter = None
                fixture.native_nodes[program.ROLE].setUserData(host_module.BASIS_KEY, 'changed during interruption')
                fixture.host.restore(item)
                self.assertEqual(fixture.observe(), before)

    def test_actual_bad_pscale_copy_ids_or_copy_scale_are_rejected(self):
        for mutation, code in (('pscale', 'PSCALE_READBACK_MISMATCH'),
                               ('copy_scale', 'COPY_CONSUMPTION_MISMATCH'),
                               ('copy_id', 'ATTRIBUTE_VALUES_REQUIRED')):
            fixture = NativeHostFixture(core.VERSIONS[0])
            item = fixture.prepared({'size_variance': 50})
            if mutation == 'pscale':
                fixture.pscale_multiplier = 20.
            elif mutation == 'copy_scale':
                fixture.copy_multiplier = 3.
            else:
                fixture.copy_ids_missing = True
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, code):
                fixture.host.write(item, fixture.roles, fixture.pack)
            fixture.pscale_multiplier = fixture.copy_multiplier = 1.
            fixture.copy_ids_missing = False
            fixture.host.restore(item)

    def test_locked_or_driven_target_never_bypasses_real_staged_gates(self):
        fixture = NativeHostFixture(core.VERSIONS[0])
        for flag in ('locked', 'driven'):
            fixture.parameters['minvalue'].flags[flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                fixture.prepared({'size_variance': 50})
            fixture.parameters['minvalue'].flags[flag] = False
        item = fixture.prepared({'size_variance': 50})
        fixture.parameters['minvalue'].flags['disabled'] = True
        with self.assertRaisesRegex(ValueError, 'PARAMETER_UNAVAILABLE'):
            fixture.host.write(item, fixture.roles, fixture.pack)
        fixture.parameters['minvalue'].flags['disabled'] = False
        fixture.host.restore(item)

    def test_snapshot_or_descriptor_tampering_cannot_reissue_original_seal(self):
        fixture = NativeHostFixture(core.VERSIONS[0])
        item = fixture.prepared({'size_variance': 50})
        item['particle_size_snapshot']['parameters']['minvalue']['evaluated'] = .9
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
            fixture.host.write(item, fixture.roles, fixture.pack)
        item = fixture.prepared({'size_variance': 50})
        item['native_write']['value_kind'] = 'trusted_swarm_goal_channels'
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
            fixture.host.write(item, fixture.roles, fixture.pack)

    def test_missing_empty_or_packed_geometry_cannot_become_consumption_pass(self):
        for mutation in ('empty', 'missing_values', 'packed'):
            fixture = NativeHostFixture(core.VERSIONS[0])
            if mutation == 'empty':
                fixture.points.clear()
            item = fixture.prepared({'size_variance': 50})
            if mutation == 'missing_values':
                fixture.geometry_mutation = lambda role, fact: fact['point_attributes'].pop('pscale', None) if role == program.ROLE else None
            elif mutation == 'packed':
                fixture.geometry_mutation = lambda role, fact: fact['primitive_records'][0].update(type='PackedGeometry') if role in ('instances', 'output') else None
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                fixture.host.write(item, fixture.roles, fixture.pack)

    def test_recreated_host_reads_saved_seed_and_resigns_new_local_plan(self):
        fixture = NativeHostFixture(core.VERSIONS[0])
        item = fixture.prepared({'size_variance': 100})
        first = fixture.host.write(item, fixture.roles, fixture.pack)
        persisted = fixture.native_nodes[program.ROLE].userData(host_module.BASIS_KEY)
        second_host = host_module.Host(fixture.callbacks, hou_module=NativeHou(fixture))
        self.assertEqual(second_host.basis(fixture.roles, fixture.pack)['task_seed'], 37)
        second = program.collect_control_readback(fixture.version, second_host.observations(fixture.roles, fixture.pack))
        self.assertEqual(first['actual_pscale_by_id'], second.pscale_by_id)
        self.assertEqual(fixture.native_nodes[program.ROLE].userData(host_module.BASIS_KEY), persisted)
        self.assertIn('cross_frame_and_reopen_stability', second.missing_evidence)

    def test_actual_active_gate_drift_is_rejected_by_collector_after_application(self):
        fixture = NativeHostFixture(core.VERSIONS[0])
        item = fixture.prepared({'size_variance': 50})
        fixture.host.write(item, fixture.roles, fixture.pack)
        for flag in ('hidden', 'disabled'):
            fixture.parameters['minvalue'].flags[flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PARAMETER_UNAVAILABLE'):
                program.collect_control_readback(fixture.version, fixture.observe())
            fixture.parameters['minvalue'].flags[flag] = False
