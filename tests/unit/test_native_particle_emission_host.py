"""P01 bottom HOM channels and clocks; no simulation or formal producer proof.

The pre-change public candidate rejected both captured builds with
PARTICLE_EMISSION_VARIANCE_NATIVE_FIELD_NOT_CAPTURED on 2026-10-14.
"""
import copy
import json
import sys
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_particle_emission_program as program
from houdini_bridge import native_particle_emission_host as host_module
from houdini_bridge import native_particle_ocean_geometry_domains as core


class NativeTemplate:
    def __init__(self, parameter):
        self.parameter = parameter

    def type(self):
        return self.parameter.kind

    def name(self):
        return self.parameter.parameter_name

    def label(self):
        return self.parameter.label

    def numComponents(self):
        return self.parameter.size

    def minValue(self):
        return self.parameter.native_minimum

    def maxValue(self):
        return self.parameter.native_maximum

    def minIsStrict(self):
        return self.parameter.minimum_strict

    def maxIsStrict(self):
        return self.parameter.maximum_strict

    def menuItems(self):
        return (str(self.parameter.value),) if self.parameter.kind == 'ordinal' else ()

    def menuLabels(self):
        return self.menuItems()

    def menuUseToken(self):
        return self.parameter.kind == 'ordinal'


class NativeParameter:
    def __init__(self, node, name, value, kind='float'):
        self.node = node
        self.parameter_name = name
        self.value = value
        self.kind = kind
        self.label, self.size = name, 1
        self.native_minimum, self.native_maximum = 0., 20000000.
        self.minimum_strict = self.maximum_strict = True
        self.source = None
        self.language = None
        self.keys = ()
        self.extrapolation = ('constant', 'linear')
        self.reference = None
        self.locked = self.disabled = self.hidden = False
        self.fail_expression = False
        self.eval_hook = None

    def path(self):
        return self.node.path() + '/' + self.parameter_name

    def name(self):
        return self.parameter_name

    def parmTemplate(self):
        return NativeTemplate(self)

    def _components(self):
        return (self,)

    def eval(self):
        if self.eval_hook is not None:
            self.eval_hook()
        if self.reference is not None:
            return self.reference.eval()
        if self.source is None:
            return self.value
        namespace = {'time': self.node.fixture.hou.time, 'frame': self.node.fixture.hou.frame,
                     'fps': self.node.fixture.hou.fps}
        with patch.dict(sys.modules, {'hou': self.node.fixture.hou}):
            if '\n' in self.source:
                exec('def evaluate():\n' + textwrap.indent(self.source, '    '), namespace)
                return namespace['evaluate']()
            return eval(self.source, namespace)

    def expression(self):
        if self.source is None:
            raise RuntimeError('native parameter has no expression')
        return self.source

    def expressionLanguage(self):
        if self.source is None:
            raise RuntimeError('native parameter has no expression language')
        return self.language

    def setExpression(self, expression, language=None, replace_expression=True):
        self.source = expression
        self.language = language
        self.keys = ()
        self.reference = None
        self.node.fixture.write_calls.append(('expression', self.path(), expression))
        if self.fail_expression:
            self.extrapolation = ('cycle', 'cycleoffset')
            self.keys = ({'frame': 7., 'value': 13., 'slope': 2.},)
            raise OSError('bottom native expression write failed after mutation')

    def set(self, value, **kwargs):
        self.value = value
        self.source = self.language = self.reference = None
        self.keys = ()
        self.node.fixture.write_calls.append(('value', self.path(), value))

    def keyframes(self):
        return copy.deepcopy(self.keys)

    def deleteAllKeyframes(self):
        self.keys = ()
        self.source = self.language = None

    def setKeyframes(self, keys):
        self.keys = copy.deepcopy(tuple(keys))

    def keyframeExtrapolation(self, before):
        return self.extrapolation[0 if before else 1]

    def setKeyframeExtrapolation(self, before, value):
        values = list(self.extrapolation)
        values[0 if before else 1] = value
        self.extrapolation = tuple(values)

    def getReferencedParm(self):
        return self if self.reference is None else self.reference

    def isLocked(self):
        return self.locked

    def isDisabled(self):
        return self.disabled

    def isHidden(self):
        return self.hidden

    def isTimeDependent(self):
        return bool(self.source or self.keys or self.reference)

    def state(self):
        return dict(value=self.value, expression=self.source, expression_language=self.language,
                    keyframes=copy.deepcopy(self.keys), extrapolation=self.extrapolation,
                    reference=self.reference, locked=self.locked, disabled=self.disabled,
                    hidden=self.hidden)


class NativeNode:
    def __init__(self, fixture, role, kind, category, session):
        self.fixture, self.role = fixture, role
        self.kind, self.category_name = kind, category
        self.native_session = session
        self.parameters, self.data = {}, {}
        self.inputs = {}
        self.editable, self.bypassed, self.native_errors = True, False, ()

    def path(self):
        return '/obj/p01_api/' + ('simulation/' + self.role if self.category_name.lower() == 'dop' else self.role)

    def type(self):
        return SimpleNamespace(name=lambda: self.kind,
                               category=lambda: SimpleNamespace(name=lambda: self.category_name))

    def sessionId(self):
        return self.native_session

    def parent(self):
        path = self.path().rsplit('/', 1)[0]
        return SimpleNamespace(path=lambda: path)

    def isEditable(self):
        return self.editable

    def isBypassed(self):
        return self.bypassed

    def errors(self):
        return self.native_errors

    def parm(self, name):
        return self.parameters.get(name)

    def parmTemplateGroup(self):
        entries = tuple(parameter.parmTemplate() for parameter in self.parameters.values())
        if self.role == 'simulation' and self.fixture.clock_templates is not None:
            entries = self.fixture.clock_templates
        return SimpleNamespace(entries=lambda: entries)

    def setInput(self, index, source, output_index=0):
        self.inputs[index] = (source, output_index)

    def inputConnections(self):
        return tuple(SimpleNamespace(inputIndex=lambda index=index: index,
                                     outputIndex=lambda output=output: output,
                                     inputNode=lambda source=source: source)
                     for index, (source, output) in self.inputs.items())

    def userData(self, name):
        return self.data.get(name)

    def setUserData(self, name, value):
        self.data[name] = value

    def destroyUserData(self, name):
        self.data.pop(name, None)


class NativeEmissionFixture:
    def __init__(self, version, *, birth_start=-.25, birth_rate=1200.):
        self.version, self.current_frame, self.current_fps = version, 12., 24.
        self.write_calls = []
        self.clock_templates = None
        self.hou = SimpleNamespace(
            applicationVersionString=lambda: self.version,
            fps=lambda: self.current_fps, frame=lambda: self.current_frame,
            time=lambda: self.frame_to_time(self.current_frame),
            frameToTime=self.frame_to_time,
            timeToFrame=lambda time: time * self.current_fps + 1.,
            setFrame=lambda frame: setattr(self, 'current_frame', frame),
            exprLanguage=SimpleNamespace(Python='exprLanguage.Python', Hscript='exprLanguage.Hscript'),
        )
        self.nodes = {
            'emission': NativeNode(self, 'emission', 'popsource::2.0', 'Dop', 101),
            'simulation': NativeNode(self, 'simulation', 'dopnet', 'Sop', 102),
            'solver': NativeNode(self, 'solver', 'popsolver::2.0', 'Dop', 103),
        }
        self.hou.node = lambda path: next((node for node in self.nodes.values() if node.path() == path), None)
        self.roles = {role: node.path() for role, node in self.nodes.items()}
        self.pack = dict(native_domain_id=core.PARTICLES)
        self.identity = dict(task_id='p01-api-task', pid=123, launch_nonce='p01-native-boundary',
                             session_id='p01-session', process_generation='p01-generation',
                             plugin_build='f' * 64, scene_epoch=0, version=version)
        for role, name, value in core._BIRTH_GATES:
            kind, _ = core._gate_spec(role, name)
            self.nodes[role].parameters[name] = NativeParameter(self.nodes[role], name, value, kind)
        self.rate = NativeParameter(self.nodes['emission'], 'constantrate', birth_rate)
        self.nodes['emission'].parameters['constantrate'] = self.rate
        for name, label, value in (('native_offset_time', 'Offset Time', birth_start),
                                   ('native_scale_time', 'Scale Time', 1.)):
            parameter = NativeParameter(self.nodes['simulation'], name, value)
            parameter.label = label
            self.nodes['simulation'].parameters[name] = parameter
        self.nodes['simulation'].parm('native_offset_time').source = repr(birth_start)
        self.nodes['simulation'].parm('native_offset_time').language = self.hou.exprLanguage.Python
        self.nodes['solver'].parameters['timescale'] = NativeParameter(self.nodes['solver'], 'timescale', 1.)
        for name, value, kind in (('probemit', 0, 'toggle'), ('seed', 17., 'float'),
                                   ('jitterbirthtime', 'none', 'ordinal')):
            self.nodes['emission'].parameters[name] = NativeParameter(self.nodes['emission'], name, value, kind)
        self.callbacks = {
            '_fx_planned_owned_root': lambda roles, pack: '/obj/p01_api',
            '_root_lease_check': lambda root, **kwargs: {'task_id': 'p01-api-task'},
            '_host_identity': lambda: copy.deepcopy(self.identity),
            '_fx_configuration': lambda params: params.get('configuration', {}),
            '_fx_planned_observation': self.observe,
            '_resolve_parm_target': lambda node, names: node.parm(names[0]),
            '_snapshot_parm_state': self.snapshot,
            '_restore_parm_snapshot': self.restore,
            '_keyframe_identity': lambda key: copy.deepcopy(key),
        }
        self.host = host_module.Host(self.callbacks, hou_module=self.hou)

    def frame_to_time(self, frame):
        return (frame - 1.) / self.current_fps

    def observe(self, node, name, *, observe_value=True):
        parameter = node.parm(name)
        result = dict(origin='runtime_hom', type=parameter.kind, size=parameter.size,
                      driven=bool(parameter.source is not None or parameter.keys or parameter.reference),
                      locked=parameter.locked, disabled=parameter.disabled, hidden=parameter.hidden,
                      menu_tokens=list(parameter.parmTemplate().menuItems()),
                      menu_labels=list(parameter.parmTemplate().menuLabels()),
                      menu_uses_token_value=parameter.parmTemplate().menuUseToken())
        if observe_value:
            result['value'] = parameter.eval()
        return result

    def snapshot(self, parameter, *, capture_extrapolation=False):
        state = parameter.state()
        return dict(mode='hom_channels', evaluated=parameter.eval(), components=[
            dict(component=parameter, mode='keyframes' if parameter.keys else 'value',
                 value=parameter.eval() if parameter.source is not None else parameter.value,
                 expression=(parameter.source, parameter.language)
                 if parameter.source is not None else None,
                 reference_path=None if parameter.reference is None else parameter.reference.path(),
                 keyframes=copy.deepcopy(parameter.keys), identity=copy.deepcopy(parameter.keys),
                 extrapolation=parameter.extrapolation, native_state=state)])

    def restore(self, parameter, snapshot):
        state = snapshot['components'][0]['native_state']
        parameter.value = state['value']
        parameter.source = state['expression']
        parameter.language = state['expression_language']
        parameter.keys = copy.deepcopy(state['keyframes'])
        parameter.extrapolation = state['extrapolation']
        parameter.reference = state['reference']
        parameter.locked, parameter.disabled, parameter.hidden = (
            state['locked'], state['disabled'], state['hidden'])
        return parameter.eval()

    def initialize(self, seed=173, fresh_roles=None):
        return self.host.initialize(
            {'configuration': {'particle_emission_basis': {'task_seed': seed}}},
            self.roles, self.pack, {'emission'} if fresh_roles is None else fresh_roles)

    def observations(self):
        return self.host.observations(self.roles, self.pack)

    def context(self):
        return self.observations()['emission', '@emission_context']

    def prepared(self, percentage, birth_rate_override=None):
        write = host_module.routed_write(percentage, self.observations(), birth_rate_override)
        item = dict(native_write=write, node=self.nodes['emission'], parm=self.rate)
        self.host.prepare(item, self.roles, self.pack)
        return item

    def applied(self, percentage, birth_rate_override=None):
        item = self.prepared(percentage, birth_rate_override)
        self.host.write(item, self.roles, self.pack)
        self.host.release(item)
        return item

    def add_particle_topology(self):
        for index, requirement in enumerate(core.node_requirements(core.PARTICLES, self.version)):
            role = requirement['role']
            if role not in self.nodes:
                self.nodes[role] = NativeNode(self, role, requirement['types'][0],
                                              requirement['category'], 200 + index)
        for edge in core.connection_requirements(core.PARTICLES, self.version):
            self.nodes[edge['destination_role']].setInput(
                edge['destination_input'], self.nodes[edge['source_role']], edge['source_output'])
        self.roles = {role: node.path() for role, node in self.nodes.items()}

    def candidate_observations(self):
        result = self.observations()
        for role, node in self.nodes.items():
            result[role, '@node'] = dict(origin='runtime_hom', task_owned=True,
                task_root='/obj/p01_api', path=node.path(), type=node.type().name(),
                category=node.type().category().name().lower(), context_parent_path=node.parent().path())
            for connection in node.inputConnections():
                source = connection.inputNode()
                result[role, '@input/' + str(connection.inputIndex())] = dict(
                    origin='runtime_hom', task_owned=True, source_path=source.path(),
                    source_type=source.type().name(), source_output=connection.outputIndex(),
                    destination_input=connection.inputIndex())
        return result


class NativeParticleEmissionHostTests(unittest.TestCase):
    def assert_refused(self, callback, *args, **kwargs):
        with self.assertRaises((program.ParticleEmissionError, core.NativeParticleOceanGeometryDomainError)) as caught:
            callback(*args, **kwargs)
        self.assertTrue(caught.exception.code.startswith(('PARTICLE_EMISSION_', 'NATIVE_', 'ACTUAL_')))
        return caught.exception.code

    def test_public_core_without_actual_context_refuses(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                self.assert_refused(core.candidate_write_plan, core.PARTICLES,
                                    {'emission_variance': 25.}, version)

    def test_public_candidate_combines_birth_rate_and_variance_into_one_native_write(self):
        for version in core.VERSIONS:
            for percentage in (0., 30., 100.):
                with self.subTest(version=version, percentage=percentage):
                    fixture = NativeEmissionFixture(version)
                    fixture.add_particle_topology()
                    fixture.initialize()
                    basis = copy.deepcopy(fixture.context()['basis'])
                    changes = {'birth_rate': 2400., 'emission_variance': percentage}
                    observations = fixture.candidate_observations()
                    writes = core.candidate_write_plan(core.PARTICLES, changes, version,
                                                       observations=observations)
                    self.assertEqual(len(writes), 1)
                    self.assertEqual((writes[0]['role'], writes[0]['parm']), ('emission', 'constantrate'))
                    self.assertEqual(writes[0]['birth_rate'], 2400.)
                    self.assertEqual(writes[0]['percentage'], percentage)
                    self.assertEqual(core.semantic_write_map(writes, changes),
                                     {('emission', 'constantrate'): ['birth_rate', 'emission_variance']})
                    core.validate_control_write_plan(writes, observations)
                    item = dict(native_write=writes[0], node=fixture.nodes['emission'], parm=fixture.rate)
                    fixture.host.prepare(item, fixture.roles, fixture.pack)
                    fixture.host.write(item, fixture.roles, fixture.pack)
                    core.validate_applied_readback(writes, fixture.candidate_observations())
                    fixture.host.release(item)
                    fixture.hou.setFrame(44.)
                    self.assertEqual(fixture.context()['actual_rate'], program.rate_at_time(
                        basis, percentage, fixture.hou.time(), 2400.))
                    self.assertEqual(fixture.context()['basis'], basis)
                    observed = fixture.candidate_observations()
                    self.assertEqual(core.control_readback(core.PARTICLES, 'birth_rate', {}, version,
                                                           observations=observed), 2400.)
                    self.assertEqual(core.control_readback(core.PARTICLES, 'emission_variance', {}, version,
                                                           observations=observed), percentage)
                    fixture.nodes['simulation'].setInput(0, fixture.nodes['instance_source'])
                    self.assertEqual(self.assert_refused(core.control_readback, core.PARTICLES,
                        'emission_variance', {}, version, observations=fixture.candidate_observations()),
                        'ACTUAL_NATIVE_CONNECTION_REQUIRED')

    def test_optional_missing_basis_is_blocked_and_does_not_write(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            before = fixture.rate.state()
            result = fixture.host.initialize({}, fixture.roles, fixture.pack, {'emission'})
            self.assertEqual(result['status'].lower(), 'blocked')
            self.assertEqual(fixture.rate.state(), before)
            self.assertEqual(fixture.write_calls, [])
            self.assertEqual(fixture.nodes['emission'].data, {})
            self.assert_refused(fixture.observations)

    def test_registration_requires_fresh_owned_node_and_exact_native_basis(self):
        for version in core.VERSIONS:
            for fault in ('fresh', 'identity', 'seed', 'timescale', 'artist_expression', 'driven_gate'):
                with self.subTest(version=version, fault=fault):
                    fixture = NativeEmissionFixture(version)
                    seed, fresh = 173, {'emission'}
                    if fault == 'fresh':
                        fresh = set()
                    elif fault == 'identity':
                        fixture.identity['task_id'] = 'foreign-task'
                    elif fault == 'seed':
                        seed = True
                    elif fault == 'timescale':
                        fixture.nodes['simulation'].parm('native_scale_time').value = .5
                    elif fault == 'artist_expression':
                        fixture.rate.setExpression('1200.0', fixture.hou.exprLanguage.Python)
                    else:
                        fixture.nodes['emission'].parm('constantactivate').setExpression(
                            '1.0', fixture.hou.exprLanguage.Python)
                    before = fixture.rate.state()
                    self.assert_refused(fixture.initialize, seed, fresh)
                    self.assertEqual(fixture.rate.state(), before)

    def test_actual_python_expression_zero_positive_full_percentage_and_override(self):
        for version in core.VERSIONS:
            for percentage, override in ((0., None), (30., None), (100., None), (30., 2400.)):
                with self.subTest(version=version, percentage=percentage, override=override):
                    fixture = NativeEmissionFixture(version)
                    fixture.initialize()
                    basis = copy.deepcopy(fixture.context()['basis'])
                    fixture.applied(percentage, override)
                    if percentage:
                        self.assertEqual(fixture.rate.expressionLanguage(), fixture.hou.exprLanguage.Python)
                    else:
                        self.assertIsNone(fixture.rate.source)
                    for frame in (-30., -5., -4.75, 1., 12.5, 44.):
                        fixture.hou.setFrame(frame)
                        self.assertEqual(fixture.rate.eval(), program.rate_at_time(
                            basis, percentage, fixture.hou.time(), override))
                        self.assertEqual(fixture.context()['actual_rate'], fixture.rate.eval())
                    self.assertEqual(fixture.context()['basis'], basis)
                    self.assertEqual(fixture.nodes['simulation'].parm('native_scale_time').eval(), 1.)
                    self.assertEqual(fixture.nodes['solver'].parm('timescale').eval(), 1.)

    def test_negative_birth_start_and_subframes_use_one_second_buckets(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version, birth_start=-.25)
            fixture.initialize()
            fixture.applied(100.)
            basis = fixture.context()['basis']
            self.assertEqual(basis['birth_start_time'], -.25)
            observed = []
            for frame in (-5., -4.5, 1., 18.999):
                fixture.hou.setFrame(frame)
                observed.append(fixture.rate.eval())
                self.assertEqual(fixture.context()['actual_rate'], observed[-1])
            self.assertEqual(len(set(observed)), 1)
            fixture.hou.setFrame(19.)
            self.assertNotEqual(fixture.rate.eval(), observed[0])
            self.assertEqual(fixture.context()['actual_rate'], fixture.rate.eval())
            fixture.hou.setFrame(-5.001)
            self.assertNotEqual(fixture.rate.eval(), observed[0])

    def test_identity_pid_nonce_node_session_and_fps_drift_refuse(self):
        for version in core.VERSIONS:
            for fault in ('task_id', 'pid', 'launch_nonce', 'scene_epoch', 'plugin_build',
                          'session', 'fps', 'artist_expression', 'keys', 'extrapolation'):
                with self.subTest(version=version, fault=fault):
                    fixture = NativeEmissionFixture(version)
                    fixture.initialize()
                    fixture.applied(30.)
                    before = fixture.rate.state()
                    if fault == 'fps':
                        fixture.current_fps = 30.
                    elif fault == 'session':
                        fixture.nodes['emission'].native_session += 1
                    elif fault == 'artist_expression':
                        fixture.rate.source = '1200.0'
                    elif fault == 'keys':
                        fixture.rate.keys = ({'frame': 7., 'value': 13., 'slope': 2.},)
                    elif fault == 'extrapolation':
                        fixture.rate.extrapolation = ('cycle', 'cycle')
                    else:
                        fixture.identity[fault] = 456 if fault == 'pid' else (
                            1 if fault == 'scene_epoch' else 'different-private-identity')
                    mutated = fixture.rate.state()
                    self.assert_refused(fixture.observations)
                    self.assertEqual(fixture.rate.state(), mutated)
                    if fault not in ('artist_expression', 'keys', 'extrapolation'):
                        self.assertEqual(mutated, before)

    def test_copied_or_rehashed_userdata_cannot_grant_authority(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            fixture.initialize()
            fixture.applied(30.)
            other = NativeEmissionFixture(version)
            other.nodes['emission'].data = copy.deepcopy(fixture.nodes['emission'].data)
            other.rate.source, other.rate.language = fixture.rate.source, fixture.rate.language
            self.assert_refused(other.observations)
            self.assert_refused(other.initialize)
            basis = copy.deepcopy(fixture.context()['basis'])
            fixture.nodes['emission'].setUserData('bridge_particle_emission_basis_v1', json.dumps(
                program.freeze_basis(version, task_id='p01-api-task', task_root='/obj/p01_api',
                                     node_path=fixture.roles['emission'], birth_rate=1200., task_seed=174,
                                     birth_start_time=-.25, fps=24.)))
            self.assertEqual(fixture.context()['basis'], basis)

    def test_tampered_prepared_plan_and_late_native_context_refuse_without_writes(self):
        for version in core.VERSIONS:
            for fault in ('write', 'before', 'gate', 'frame', 'session', 'tampered_prepare'):
                with self.subTest(version=version, fault=fault):
                    fixture = NativeEmissionFixture(version)
                    fixture.initialize()
                    item = fixture.prepared(30.)
                    before, writes = fixture.rate.state(), len(fixture.write_calls)
                    if fault == 'write':
                        item['native_write']['value'] = '99999.0'
                    elif fault == 'before':
                        item['native_write']['emission_before']['basis']['task_seed'] = 999
                    elif fault == 'gate':
                        fixture.nodes['emission'].parm('constantactivate').value = 0.
                    elif fault == 'frame':
                        fixture.current_frame += .25
                    else:
                        if fault == 'session':
                            fixture.nodes['emission'].native_session += 1
                        else:
                            fixture.host.release(item)
                            item['native_write']['value'] = '0.0'
                            self.assert_refused(fixture.host.prepare, item, fixture.roles, fixture.pack)
                    self.assert_refused(fixture.host.write, item, fixture.roles, fixture.pack)
                    self.assertEqual(fixture.rate.state(), before)
                    self.assertEqual(len(fixture.write_calls), writes)

    def test_native_write_failure_restores_full_channels_and_prior_private_registration(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            fixture.initialize()
            fixture.applied(30.)
            before = fixture.rate.state()
            data = copy.deepcopy(fixture.nodes['emission'].data)
            item = fixture.prepared(100.)
            fixture.rate.fail_expression = True
            with self.assertRaises(OSError):
                fixture.host.write(item, fixture.roles, fixture.pack)
            fixture.rate.fail_expression = False
            fixture.host.restore(item, fixture.roles, fixture.pack)
            fixture.host.release(item)
            self.assertEqual(fixture.rate.state(), before)
            self.assertEqual(fixture.nodes['emission'].data, data)
            self.assertEqual(fixture.context()['percentage'], 30.)

    def test_restore_first_write_and_released_token_cannot_be_reused(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            fixture.initialize()
            before = fixture.rate.state()
            item = fixture.prepared(30.)
            fixture.host.write(item, fixture.roles, fixture.pack)
            fixture.host.restore(item, fixture.roles, fixture.pack)
            fixture.host.release(item)
            self.assertEqual(fixture.rate.state(), before)
            self.assertEqual(fixture.context()['percentage'], 0.)
            self.assert_refused(fixture.host.write, item, fixture.roles, fixture.pack)

    def test_readback_is_actual_parameter_expression_only_and_never_native_pass(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            fixture.initialize()
            fixture.applied(30.)
            result = fixture.host.readback(fixture.roles, fixture.pack)
            self.assertEqual(result['status'].lower(), 'blocked')
            self.assertEqual(result['evidence_scope'], 'native_parameter_expression_only')
            self.assertIn('same_build_POP_substep_emission_integration', result['missing_evidence'])
            observed = fixture.context()
            self.assertEqual(observed['actual_rate'], fixture.rate.eval())
            self.assertEqual(observed['frame'], fixture.hou.frame())
            self.assertEqual(observed['time'], fixture.hou.time())
            equivalent = host_module.Host(fixture.callbacks, hou_module=fixture.hou)
            self.assertEqual(equivalent.readback(fixture.roles, fixture.pack), result)

    def test_late_gate_drift_during_actual_evaluation_refuses_and_restores_channels(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            fixture.initialize()
            item = fixture.prepared(30.)
            before = fixture.rate.state()
            gate = fixture.nodes['emission'].parm('constantactivate')
            def mutate_after_expression_write():
                if fixture.rate.source is not None:
                    fixture.rate.eval_hook = None
                    gate.value = 0.
            fixture.rate.eval_hook = mutate_after_expression_write
            self.assert_refused(fixture.host.write, item, fixture.roles, fixture.pack)
            fixture.rate.eval_hook = None
            gate.value = 1.
            fixture.host.restore(item, fixture.roles, fixture.pack)
            self.assertEqual(fixture.rate.state(), before)
            self.assertEqual(fixture.context()['percentage'], 0.)

    def test_clock_templates_missing_ambiguous_wrong_size_or_driven_scale_refuse(self):
        for version in core.VERSIONS:
            for fault in ('missing', 'duplicate', 'vector', 'type', 'driven_scale', 'solver_scale'):
                with self.subTest(version=version, fault=fault):
                    fixture = NativeEmissionFixture(version)
                    simulation = fixture.nodes['simulation']
                    offset = simulation.parm('native_offset_time')
                    scale = simulation.parm('native_scale_time')
                    if fault == 'missing':
                        fixture.clock_templates = (scale.parmTemplate(),)
                    elif fault == 'duplicate':
                        fixture.clock_templates = (offset.parmTemplate(), offset.parmTemplate(), scale.parmTemplate())
                    elif fault == 'vector':
                        offset.size = 2
                    elif fault == 'type':
                        offset.kind = 'string'
                    elif fault == 'driven_scale':
                        scale.source, scale.language = '1.0', fixture.hou.exprLanguage.Python
                    else:
                        fixture.nodes['solver'].parm('timescale').value = .5
                    code = self.assert_refused(fixture.initialize)
                    if fault in ('missing', 'duplicate'):
                        self.assertEqual(code, 'PARTICLE_EMISSION_CLOCK_INTERFACE_REQUIRED')
                    self.assertEqual(fixture.write_calls, [])

    def test_actual_offset_factory_expression_and_extra_birth_facts_are_preserved(self):
        for version in core.VERSIONS:
            fixture = NativeEmissionFixture(version)
            offset = fixture.nodes['simulation'].parm('native_offset_time')
            before = offset.state()
            fixture.initialize()
            fixture.applied(30.)
            self.assertEqual(offset.state(), before)
            context = fixture.context()
            self.assertEqual(context['birth_start_time'], -.25)
            for name in ('probemit', 'seed', 'jitterbirthtime'):
                old = fixture.nodes['emission'].parm(name).value
                fixture.nodes['emission'].parm(name).value = 1. if name == 'seed' else (
                    1 if name == 'probemit' else 'positive')
                self.assert_refused(fixture.observations)
                fixture.nodes['emission'].parm(name).value = old
            self.assertEqual(fixture.context()['percentage'], 30.)

    def test_review_guards_table_preserves_limits_identity_and_initialization_authority(self):
        cases = ('incomplete_identity', 'rollback_identity_drift', 'strict_minimum',
                 'strict_maximum', 'soft_bound', 'strict_bound_changed', 'initialization_retry',
                 'initialization_successor_CAS', 'final_channel_replacement', 'final_native_context')
        for version in core.VERSIONS:
            for case in cases:
                with self.subTest(version=version, case=case):
                    fixture = NativeEmissionFixture(version)
                    if case == 'incomplete_identity':
                        for field in ('session_id', 'process_generation', 'plugin_build'):
                            value = fixture.identity.pop(field)
                            self.assertEqual(self.assert_refused(fixture.initialize),
                                             'PARTICLE_EMISSION_AUTHENTICATED_HOST_REQUIRED')
                            self.assertEqual(fixture.host.authority['records'], {})
                            fixture.identity[field] = value
                    elif case in ('strict_minimum', 'strict_maximum', 'soft_bound'):
                        if case == 'strict_minimum':
                            fixture.rate.native_minimum = 900.
                        else:
                            fixture.rate.native_maximum = 1300.
                            fixture.rate.maximum_strict = case != 'soft_bound'
                        fixture.initialize()
                        if case == 'soft_bound':
                            fixture.applied(30.)
                            result = fixture.host.readback(fixture.roles, fixture.pack)
                            self.assertIsNone(result['rate_range']['native_maximum'])
                            self.assertFalse(result['rate_range']['native_hard_limits_proven'])
                        else:
                            before = fixture.rate.state()
                            self.assertEqual(self.assert_refused(fixture.prepared, 30.),
                                             'PARTICLE_EMISSION_NATIVE_RANGE_EXCEEDED')
                            self.assertEqual(fixture.rate.state(), before)
                            self.assertEqual(fixture.write_calls, [])
                    elif case == 'strict_bound_changed':
                        fixture.initialize()
                        item = fixture.prepared(30.)
                        before = fixture.rate.state()
                        fixture.rate.native_maximum = 1300.
                        self.assertEqual(self.assert_refused(fixture.host.write, item, fixture.roles, fixture.pack),
                                         'PARTICLE_EMISSION_CONTEXT_CHANGED')
                        self.assertEqual(fixture.rate.state(), before)
                        self.assertEqual(fixture.write_calls, [])
                        fixture.host.release(item)
                    elif case == 'rollback_identity_drift':
                        fixture.initialize()
                        item = fixture.prepared(30.)
                        fixture.host.write(item, fixture.roles, fixture.pack)
                        before = fixture.rate.state()
                        restores = []
                        restore = fixture.callbacks['_restore_parm_snapshot']
                        def capture_restore(*args):
                            restores.append(True)
                            return restore(*args)
                        def drift_identity():
                            fixture.rate.eval_hook = None
                            fixture.identity['launch_nonce'] = 'new-host-before-rollback'
                        fixture.callbacks['_restore_parm_snapshot'] = capture_restore
                        fixture.rate.eval_hook = drift_identity
                        self.assertEqual(self.assert_refused(fixture.host.restore, item, fixture.roles, fixture.pack),
                                         'PARTICLE_EMISSION_TRANSACTION_REQUIRED')
                        self.assertEqual(restores, [])
                        self.assertEqual(fixture.rate.state(), before)
                        fixture.host.release(item)
                    elif case in ('initialization_retry', 'initialization_successor_CAS'):
                        observe = fixture.callbacks['_fx_planned_observation']
                        gate = fixture.nodes['emission'].parm('constantactivate')
                        calls, successor = [], []
                        def initialization_fault(node, name, **kwargs):
                            if node is fixture.nodes['emission'] and name == 'constantactivate':
                                calls.append(True)
                                if len(calls) == 2:
                                    gate.value = 0.
                                    if case == 'initialization_successor_CAS':
                                        root = '/obj/p01_api'
                                        replacement = copy.deepcopy(fixture.host.authority['records'][root])
                                        fixture.host.authority['records'][root] = replacement
                                        successor.append(replacement)
                            return observe(node, name, **kwargs)
                        fixture.callbacks['_fx_planned_observation'] = initialization_fault
                        self.assertEqual(self.assert_refused(fixture.initialize), 'PARTICLE_EMISSION_GATE_CHANGED')
                        fixture.callbacks['_fx_planned_observation'] = observe
                        gate.value = 1.
                        if case == 'initialization_successor_CAS':
                            self.assertEqual(len(successor), 1)
                            self.assertIs(fixture.host.authority['records']['/obj/p01_api'], successor[0])
                        else:
                            self.assertEqual(fixture.host.authority['records'], {})
                            fixture.nodes['emission'].native_session += 1
                            fixture.initialize()
                            self.assertEqual(fixture.context()['percentage'], 0.)
                        self.assertEqual(fixture.write_calls, [])
                    else:
                        faults = ('channel',) if case == 'final_channel_replacement' else (
                            'launch_nonce', 'fps', 'constantactivate', 'strict_maximum')
                        for fault in faults:
                            with self.subTest(fault=fault):
                                fixture = NativeEmissionFixture(version)
                                fixture.initialize()
                                fixture.applied(30.)
                                observe = fixture.callbacks['_fx_planned_observation']
                                calls, changed = [], []
                                def late_native_mutation():
                                    fixture.rate.eval_hook = None
                                    changed.append(True)
                                    if fault == 'launch_nonce':
                                        fixture.identity['launch_nonce'] = 'late-final-channel-nonce'
                                    elif fault == 'fps':
                                        fixture.current_fps = 30.
                                    elif fault == 'constantactivate':
                                        fixture.nodes['emission'].parm('constantactivate').value = 0.
                                    else:
                                        fixture.rate.native_maximum = 1300.
                                def observe_late_channel(node, name, **kwargs):
                                    if node is fixture.nodes['emission'] and name == 'constantactivate':
                                        calls.append(True)
                                        if len(calls) == 2:
                                            if fault == 'channel':
                                                fixture.rate.source = '99999.0'
                                                changed.append(True)
                                            else:
                                                fixture.rate.eval_hook = late_native_mutation
                                    return observe(node, name, **kwargs)
                                fixture.callbacks['_fx_planned_observation'] = observe_late_channel
                                self.assertEqual(self.assert_refused(fixture.observations),
                                    'PARTICLE_EMISSION_GATE_CHANGED' if fault == 'constantactivate'
                                    else 'PARTICLE_EMISSION_CONTEXT_CHANGED')
                                self.assertEqual(changed, [True])


if __name__ == '__main__':
    unittest.main()
