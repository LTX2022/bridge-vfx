"""Explicit G03 bottom HOM fixture, never a VEX/deformation or lifecycle fake.

The addon ownership, persistent lease, field collector and parameter transaction
helpers run unchanged. Missing integration hooks receive explicit fixture input
and creation records; these tests do not certify production provenance services.
No HTTP/TCP server, task host, solver, model, render or Houdini is started.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_host as adapter
from houdini_bridge import native_geometry_controls_program as program
from test_native_geometry_controls_program import BottomGeometry
from test_native_particle_size_host import NativeAttribute, NativeName, NativeType, NativeVertex

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = json.loads((ROOT / 'docs/native-basis/w2-wrangle-convolve-static.json').read_text(encoding='utf-8'))


def load_addon():
    specification = importlib.util.spec_from_file_location(
        'g03_unit_addon', ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
    module = importlib.util.module_from_spec(specification)
    with patch.dict(sys.modules):
        specification.loader.exec_module(module)
    return module


class Template:
    def __init__(self, captured):
        self.captured = captured

    def type(self):
        return NativeName({'string': 'String', 'ordinal': 'Menu', 'toggle': 'Toggle',
                           'multiparm': 'Folder'}[self.captured['type']])

    def numComponents(self):
        return self.captured['size']

    def menuItems(self):
        return tuple(self.captured.get('menu_tokens', ())[::2])

    def menuLabels(self):
        return tuple(self.captured.get('menu_tokens', ())[1::2])

    def menuUseToken(self):
        return self.captured.get('menu_uses_token_value', False)


class Parameter:
    def __init__(self, node, name, captured, value):
        self.node, self.parameter_name = node, name
        self.template = Template(captured)
        self.value = value
        self.flags = dict(hidden=False, disabled=False, locked=False)
        self.driver = None
        self.keys = ()
        self.extrapolation = ['constant', 'constant']
        self.fail_once = False
        self.on_set = None

    def name(self):
        return self.parameter_name

    def path(self):
        return self.node.path() + '/' + self.parameter_name

    def parmTemplate(self):
        return self.template

    def menuItems(self):
        return self.template.menuItems()

    def eval(self):
        return self.value

    def evalAsString(self):
        tokens = self.menuItems()
        return tokens[self.value] if tokens and type(self.value) is int else str(self.value)

    def unexpandedString(self):
        if self.template.captured['type'] != 'string':
            raise ValueError('not a string parm')
        return self.value

    def expression(self):
        if self.driver is None:
            raise ValueError('no expression')
        return self.driver

    def getReferencedParm(self):
        return self

    def keyframes(self):
        return self.keys

    def deleteAllKeyframes(self):
        self.keys = ()
        self.driver = None

    def setKeyframes(self, keys):
        self.keys = tuple(keys)

    def keyframeExtrapolation(self, before):
        return self.extrapolation[0 if before else 1]

    def setKeyframeExtrapolation(self, before, value):
        self.extrapolation[0 if before else 1] = value

    def isHidden(self):
        return self.flags['hidden']

    def isDisabled(self):
        return self.flags['disabled']

    def isLocked(self):
        return self.flags['locked']

    def set(self, value, **kwargs):
        if any(self.flags.values()):
            raise ValueError('native parameter gate rejected write')
        tokens = self.menuItems()
        if tokens and isinstance(value, str) and not self.template.menuUseToken():
            value = tokens.index(value)
        self.value = value
        self.node.fixture.set_calls.append((self.parameter_name, value))
        if self.fail_once:
            self.fail_once = False
            raise ValueError('partial native setter failure')
        if self.on_set is not None:
            self.on_set()


class Point:
    def __init__(self, source, index):
        self.source, self.index = source, index

    def number(self):
        return self.index * 7 + 10

    def attribValue(self, name):
        value = self.source['point_attributes'][name]['values'][self.index]
        return tuple(value) if isinstance(value, list) else value


class Primitive:
    def __init__(self, source, polygon, kind):
        self.source, self.polygon, self.kind = source, polygon, kind

    def type(self):
        return NativeName(self.kind)

    def vertices(self):
        return (NativeVertex(Point(self.source, index)) for index in self.polygon)


class Geometry:
    def __init__(self, source):
        self.source = source

    def points(self):
        return (Point(self.source, index) for index in range(self.source['points']))

    def prims(self):
        return (Primitive(self.source, polygon, kind) for polygon, kind in
                zip(self.source['polygons'], self.source['primitive_types']))

    def findPointAttrib(self, name):
        fact = self.source['point_attributes'].get(name)
        return NativeAttribute(name, fact) if fact is not None else None


class Connection:
    def __init__(self, source, input_index=0, output_index=0):
        self.source, self.input_index, self.output_index = source, input_index, output_index

    def inputNode(self):
        return self.source

    def inputIndex(self):
        return self.input_index

    def outputIndex(self):
        return self.output_index


class Node:
    def __init__(self, fixture, path, kind, session):
        self.fixture, self.node_path, self.kind, self.session = fixture, path, kind, session
        self.userdata, self.parameters, self.connections = {}, {}, []
        self.editable, self.bypassed = True, False
        self.fail_userdata_once = None

    def path(self):
        return self.node_path

    def sessionId(self):
        return self.session

    def type(self):
        return NativeType(self.kind, 'Sop')

    def isEditable(self):
        return self.editable

    def isBypassed(self):
        return self.bypassed

    def inputConnections(self):
        return tuple(self.connections)

    def parm(self, name):
        return self.parameters.get(name)

    def updateParmStates(self):
        pass

    def userData(self, name):
        return self.userdata.get(name)

    def setUserData(self, name, value):
        self.userdata[name] = value
        if self.fail_userdata_once == name:
            self.fail_userdata_once = None
            raise ValueError('partial native userData failure')

    def destroyUserData(self, name):
        self.userdata.pop(name, None)


class Fixture:
    def __init__(self, addon, version):
        self.addon, self.version = addon, version
        self.root, self.task = '/obj/g03_unit', 'g03-unit-task'
        self.stack = ExitStack()
        self.set_calls, self.records = [], {}
        self.nodes = {role: Node(self, self.root + '/' + role, kind, index + 1)
                      for index, (role, kind) in enumerate((('instance_source', 'sphere'),
                          (program.ROLE, 'attribwrangle'), ('instance_transform', 'xform')))}
        self.roles = {role: node.path() for role, node in self.nodes.items()}
        self.pack = dict(native_domain_id='procedural_geometry_v1',
                         nodes=[dict(role=role, types=[node.kind]) for role, node in self.nodes.items()])
        self.root_node = Node(self, self.root, 'geo', 100)
        self.root_node.setUserData('bridge_fx_owned', '1')
        for destination, source in ((program.ROLE, 'instance_source'), ('instance_transform', program.ROLE)):
            self.nodes[destination].connections.append(Connection(self.nodes[source]))
        self.source = BottomGeometry(self.roles['instance_source']).observe()
        self.provenance = dict(task_id=self.task, task_root=self.root, native_version=version,
            input_version='fixture-input-v1', basis_input_sha256='a' * 64,
            source_geometry_sha256=program.source_geometry_sha256(self.source),
            source_node_path=self.roles['instance_source'], output=0, frame=1.,
            space='sop_local_rest', unit='SU', local_x_axis=[1., 0., 0.])
        self.identity = dict(task_id=self.task, version=version, pid=os.getpid(),
            launch_nonce='explicit-g03-unit-fixture', session_id='g03-unit-session',
            process_generation='g03-unit-generation')
        self.fresh = {program.ROLE}
        self.carrier = self.nodes[program.ROLE]
        captured = CAPTURE['versions'][version]['operators']['Sop/attribwrangle']['parameters']
        for name, (_, value) in dict(program.GATES, snippet=('string', '')).items():
            template = captured[name]
            if template['type'] == 'ordinal' and not template['menu_uses_token_value']:
                value = template['menu_tokens'][::2].index('detail')
            self.carrier.parameters[name] = Parameter(self.carrier, name, template, value)
        self.hou = SimpleNamespace(applicationVersionString=lambda: version,
            frame=lambda: self.provenance['frame'],
            node=lambda path: self.root_node if path == self.root else next(
                (node for node in self.nodes.values() if node.path() == path), None))
        self.hooks = dict(addon.__dict__, _fx_geometry_source_basis=self.source_basis,
            _fx_geometry_source_geometry=self.source_geometry, _fx_geometry_registration=self.registration)
        self.host = adapter.Host(self.hooks, hou_module=self.hou)

    def __enter__(self):
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, HOUDINI_BRIDGE_STATE_DIR=temporary + '/houdini'))
        self.stack.enter_context(patch.dict(sys.modules, hou=self.hou))
        self.stack.enter_context(patch.object(self.addon, '_TASK_HOST_IDENTITY', self.identity, create=True))
        self.stack.enter_context(patch.object(self.addon, '_BRIDGE_SCENE_STATE', SimpleNamespace(scene_epoch=0)))
        self.addon._root_lease_issue(self.root, self.task, 'sop')
        return self

    def __exit__(self, *args):
        adapter._SNAPSHOTS.clear()
        return self.stack.__exit__(*args)

    def source_basis(self, roles, pack, binding):
        self.addon._root_lease_check(self.root, task_id=self.task, scope='sop', renew=False)
        return copy.deepcopy(self.provenance)

    def source_geometry(self, node, provenance):
        if node is not self.nodes['instance_source'] or provenance != self.provenance:
            raise ValueError('fixture source association differs')
        return Geometry(self.source)

    def registration(self, action, roles, pack, record):
        self.addon._root_lease_check(self.root, task_id=self.task, scope='sop', renew=False)
        key = self.carrier.sessionId()
        if action == 'authorize_fresh':
            return program.ROLE in self.fresh and key not in self.records
        if action == 'register':
            if key in self.records or program.ROLE not in self.fresh:
                return False
            self.records[key] = copy.deepcopy(record)
        elif action in ('verify', 'authorize_restore'):
            return self.records.get(key) == record
        elif action == 'revoke':
            if key in self.records and self.records[key] != record:
                return False
            self.records.pop(key, None)
        else:
            raise AssertionError('unknown registry action')
        return True

    def initialize(self):
        with self.addon._root_lease_fence(self.root, task_id=self.task, scope='sop'):
            result = self.host.initialize({}, self.roles, self.pack, self.fresh)
        self.fresh.clear()
        return result

    def prepared(self, value):
        return self.host.prepare(self.host.plan(value, self.roles, self.pack), self.roles, self.pack)

    def write(self, item):
        with self.addon._root_lease_fence(self.root, task_id=self.task, scope='sop'):
            return self.host.write(item, self.roles, self.pack)

    def restore(self, item):
        with self.addon._root_lease_fence(self.root, task_id=self.task, scope='sop'):
            return self.host.restore(item, self.roles, self.pack)


class NativeGeometryControlsHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addon = load_addon()

    def test_static_cross_frame_parameter_read_write_and_restore_both_builds(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(self.addon, version) as fixture:
                fixture.initialize()
                frame = [2.]
                fixture.hou.frame = lambda: frame[0]
                fixture.hou.setFrame = lambda value: self.fail('must not change the native frame')
                source = fixture.nodes['instance_source']
                current_calls = []
                def current_geometry(*, output_index):
                    current_calls.append((frame[0], output_index))
                    return Geometry(fixture.source)
                source.geometry = current_geometry
                observed = fixture.host.observations(fixture.roles, fixture.pack)
                self.assertEqual(observed['context']['source']['frame'], 1.)
                sampling = observed['context']['source_sampling']
                self.assertEqual(sampling['rest_frame'], 1.)
                self.assertEqual(sampling['current_frame'], 2.)
                current = copy.deepcopy(fixture.source)
                current['frame'] = 2.
                self.assertEqual(sampling['current_source_geometry_sha256'], program.source_geometry_sha256(current))
                item = fixture.prepared(3)
                try:
                    result = fixture.write(item)
                    self.assertEqual(result['value'], 3)
                    self.assertEqual(result['status'], 'BLOCKED')
                    self.assertEqual(result['evidence_scope'], 'parameters_only')
                    self.assertEqual(fixture.restore(item)['status'], 'restored')
                finally:
                    fixture.host.release(item)
                self.assertEqual(frame[0], 2.)
                self.assertTrue(current_calls)
                self.assertEqual(set(current_calls), {(2., 0)})

    def test_cross_frame_animated_source_refuses_write_before_mutation(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(self.addon, version) as fixture:
                fixture.initialize()
                fixture.hou.frame = lambda: 2.
                current = copy.deepcopy(fixture.source)
                source = fixture.nodes['instance_source']
                source.geometry = lambda *, output_index: Geometry(current)
                item = fixture.prepared(3)
                before = fixture.carrier.parameters['snippet'].eval()
                current['point_attributes']['P']['values'][0][0] += .5
                fixture.set_calls.clear()
                try:
                    with self.assertRaisesRegex(ValueError, 'GEOMETRY_STATIC_SOURCE_REQUIRED'):
                        fixture.write(item)
                    self.assertEqual(fixture.carrier.parameters['snippet'].eval(), before)
                    self.assertFalse(fixture.set_calls)
                finally:
                    fixture.host.release(item)

    def test_cross_frame_delayed_read_must_not_change_sampling_frame(self):
        for stage in ('rest', 'current'):
            with self.subTest(stage=stage), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.initialize()
                frame = [2.]
                fixture.hou.frame = lambda: frame[0]
                class DelayedGeometry(Geometry):
                    def points(inner):
                        frame[0] = 3.
                        return super().points()
                source = fixture.nodes['instance_source']
                if stage == 'rest':
                    fixture.hooks['_fx_geometry_source_geometry'] = lambda node, provenance: DelayedGeometry(fixture.source)
                    source.geometry = lambda *, output_index: Geometry(fixture.source)
                else:
                    source.geometry = lambda *, output_index: DelayedGeometry(fixture.source)
                fixture.set_calls.clear()
                with self.assertRaisesRegex(ValueError, 'GEOMETRY_SOURCE_FRAME_REQUIRED'):
                    fixture.host.observations(fixture.roles, fixture.pack)
                self.assertFalse(fixture.set_calls)
                self.assertEqual(frame[0], 3.)

    def test_cross_frame_post_write_input_drift_keeps_rollback_authority(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            fixture.hou.frame = lambda: 2.
            source = fixture.nodes['instance_source']
            source.geometry = lambda *, output_index: Geometry(fixture.source)
            item = fixture.prepared(3)
            snippet = fixture.carrier.parameters['snippet']
            before = snippet.eval()
            current = copy.deepcopy(fixture.source)
            def drift():
                current['point_attributes']['P']['values'][0][0] += .5
                source.geometry = lambda *, output_index: Geometry(current)
                snippet.on_set = None
            snippet.on_set = drift
            try:
                with self.assertRaisesRegex(ValueError, 'GEOMETRY_STATIC_SOURCE_REQUIRED'):
                    fixture.write(item)
                self.assertNotEqual(snippet.eval(), before)
                self.assertEqual(fixture.restore(item)['status'], 'restored')
                self.assertEqual(snippet.eval(), before)
                with self.assertRaisesRegex(ValueError, 'GEOMETRY_STATIC_SOURCE_REQUIRED'):
                    fixture.host.observations(fixture.roles, fixture.pack)
            finally:
                fixture.host.release(item)

    def test_cross_frame_missing_current_geometry_has_no_default(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            fixture.hou.frame = lambda: 2.
            fixture.set_calls.clear()
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_CURRENT_SOURCE_REQUIRED'):
                fixture.host.observations(fixture.roles, fixture.pack)
            self.assertFalse(fixture.set_calls)

    def test_cross_frame_parameter_collector_frame_drift_is_refused(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            frame = [2.]
            fixture.hou.frame = lambda: frame[0]
            fixture.nodes['instance_source'].geometry = lambda *, output_index: Geometry(fixture.source)
            original = fixture.hooks['_fx_planned_observation']
            def observe(node, name):
                value = original(node, name)
                frame[0] = 3.
                return value
            fixture.hooks['_fx_planned_observation'] = observe
            fixture.set_calls.clear()
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_SOURCE_FRAME_REQUIRED'):
                fixture.host.observations(fixture.roles, fixture.pack)
            self.assertEqual(frame[0], 3.)
            self.assertFalse(fixture.set_calls)

    def test_cross_frame_prepared_plan_cannot_silently_change_sampling_frame(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            frame = [2.]
            fixture.hou.frame = lambda: frame[0]
            fixture.nodes['instance_source'].geometry = lambda *, output_index: Geometry(fixture.source)
            item = fixture.prepared(3)
            frame[0] = 3.
            fixture.set_calls.clear()
            try:
                with self.assertRaisesRegex(ValueError, 'GEOMETRY_CONTEXT_CHANGED'):
                    fixture.write(item)
                self.assertFalse(fixture.set_calls)
                self.assertEqual(frame[0], 3.)
            finally:
                fixture.host.release(item)

    def test_owned_initialization_parameter_write_zero_and_full_rollback_both_builds(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(self.addon, version) as fixture:
                result = fixture.initialize()
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(result['value'], 0)
                before = fixture.host.observations(fixture.roles, fixture.pack)
                self.assertEqual(before['context']['source'], fixture.source)
                for value in (.125, 100, 0):
                    item = fixture.prepared(value)
                    fixture.set_calls.clear()
                    result = fixture.write(item)
                    self.assertEqual(result['value'], value)
                    self.assertEqual(result['evidence_scope'], 'parameters_only')
                    self.assertEqual(result['missing_evidence'], list(program.MISSING_EVIDENCE))
                    self.assertEqual([name for name, value in fixture.set_calls], ['snippet'])
                    self.assertEqual(result['invalidates_from'], 'shaping_meshing')
                    fixture.restore(item)
                    self.assertEqual(fixture.host.observations(fixture.roles, fixture.pack), before)
                    fixture.host.release(item)
                    with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                        fixture.write(item)

    def test_recreated_adapter_authenticates_persisted_basis_without_reinitializing(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            item = fixture.prepared(3)
            fixture.write(item)
            fixture.host.release(item)
            persisted = dict(fixture.carrier.userdata)
            fixture.host = adapter.Host(fixture.hooks, hou_module=fixture.hou)
            fixture.set_calls.clear()
            result = fixture.host.initialize({}, fixture.roles, fixture.pack, set())
            self.assertEqual(result['value'], 3)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(fixture.carrier.userdata, persisted)
            self.assertFalse(fixture.set_calls)

    def test_foreign_empty_or_canonical_snippet_is_never_adopted(self):
        for value, fresh in (('', False), ('foreign();', True), ('float deform_amplitude = 0;\n', False)):
            with self.subTest(value=value, fresh=fresh), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.carrier.parameters['snippet'].value = value
                if not fresh:
                    fixture.fresh.clear()
                with self.assertRaises(ValueError):
                    fixture.initialize()
                self.assertFalse(fixture.records)
                self.assertIsNone(fixture.carrier.userData(adapter.BASIS_KEY))
                self.assertFalse(fixture.set_calls)

    def test_userdata_is_not_server_registration_and_malformed_records_fail_closed(self):
        for mutation in ('registry', 'malformed', 'partial', 'record'):
            with self.subTest(mutation=mutation), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.initialize()
                if mutation == 'registry':
                    fixture.records.clear()
                elif mutation == 'malformed':
                    fixture.carrier.setUserData(adapter.BASIS_KEY, '{')
                elif mutation == 'partial':
                    fixture.carrier.destroyUserData(adapter.REGISTRATION_KEY)
                else:
                    record = json.loads(fixture.carrier.userData(adapter.REGISTRATION_KEY))
                    record['initialized'] = False
                    fixture.carrier.setUserData(adapter.REGISTRATION_KEY, json.dumps(record))
                fixture.set_calls.clear()
                with self.assertRaisesRegex(ValueError, 'GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED'):
                    fixture.host.initialize({}, fixture.roles, fixture.pack, {program.ROLE})
                self.assertFalse(fixture.set_calls)

    def test_missing_provenance_hook_or_fact_has_no_default_or_cook(self):
        for missing in ('_fx_geometry_source_basis', '_fx_geometry_source_geometry',
                        '_fx_geometry_registration', 'space', 'local_x_axis', 'basis_input_sha256'):
            with self.subTest(missing=missing), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                if missing.startswith('_'):
                    fixture.hooks.pop(missing)
                else:
                    fixture.provenance.pop(missing)
                with self.assertRaises(ValueError):
                    fixture.initialize()
                self.assertIsNone(fixture.carrier.userData(adapter.BASIS_KEY))
                self.assertFalse(fixture.set_calls)

    def test_actual_attribute_storage_values_topology_and_budgets_are_checked(self):
        mutations = ('N', 'id', 'duplicate_ids', 'packed', 'point_budget', 'vertex_budget',
                     'zero_span', 'nonunit_N', 'precision', 'array')
        for mutation in mutations:
            with self.subTest(mutation=mutation), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                attributes = fixture.source['point_attributes']
                if mutation in ('N', 'id'):
                    attributes.pop(mutation)
                elif mutation == 'duplicate_ids':
                    attributes['id']['values'][1] = attributes['id']['values'][0]
                elif mutation == 'packed':
                    fixture.source['primitive_types'][0] = 'PackedGeometry'
                elif mutation == 'point_budget':
                    fixture.source['points'] = 8193
                elif mutation == 'vertex_budget':
                    fixture.source['polygons'][0] = [0, 1, 2] * 22000
                elif mutation == 'zero_span':
                    for position in attributes['P']['values']:
                        position[0] = 0
                elif mutation == 'nonunit_N':
                    attributes['N']['values'][0] = [0., 2., 0.]
                elif mutation == 'precision':
                    attributes['id']['precision'] = 'int64'
                else:
                    attributes['P']['is_array'] = True
                with self.assertRaises(ValueError):
                    fixture.initialize()
                self.assertFalse(fixture.set_calls)

    def test_stale_source_input_frame_and_graph_fail_before_feedback_mutation(self):
        for mutation in ('P', 'frame', 'input_version', 'basis_input_sha256', 'wire', 'bypass',
                         'editable', 'recreated_transform'):
            with self.subTest(mutation=mutation), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.initialize()
                item = fixture.prepared(10)
                if mutation == 'P':
                    fixture.source['point_attributes']['P']['values'][1][0] += .5
                elif mutation == 'frame':
                    fixture.provenance['frame'] = 2.
                elif mutation in ('input_version', 'basis_input_sha256'):
                    fixture.provenance[mutation] = 'changed'
                elif mutation == 'wire':
                    fixture.nodes['instance_transform'].connections[0].output_index = 1
                elif mutation == 'bypass':
                    fixture.carrier.bypassed = True
                elif mutation == 'recreated_transform':
                    fixture.nodes['instance_transform'].session += 1
                else:
                    fixture.carrier.editable = False
                fixture.set_calls.clear()
                with self.assertRaises(ValueError):
                    fixture.write(item)
                self.assertFalse(fixture.set_calls)

    def test_plan_rejects_reissued_host_identity_before_prepare(self):
        for version in program.VERSIONS:
            for mutation in ('scene_epoch', 'launch_nonce', 'process_generation'):
                with self.subTest(version=version, mutation=mutation), Fixture(self.addon, version) as fixture:
                    fixture.initialize()
                    plan = fixture.host.plan(8, fixture.roles, fixture.pack)
                    if mutation == 'scene_epoch':
                        fixture.addon._BRIDGE_SCENE_STATE.scene_epoch += 1
                    else:
                        fixture.identity[mutation] = 'new-authenticated-identity'
                    fixture.addon._root_lease_issue(fixture.root, fixture.task, 'sop')
                    fixture.set_calls.clear()
                    with self.assertRaisesRegex(ValueError, 'GEOMETRY_CONTEXT_CHANGED'):
                        fixture.host.prepare(plan, fixture.roles, fixture.pack)
                    self.assertFalse(fixture.set_calls)
                    item = fixture.prepared(8)
                    self.assertEqual(fixture.write(item)['value'], 8)
                    fixture.restore(item)
                    fixture.host.release(item)

    def test_lease_takeover_and_launch_epoch_changes_reject_writes_and_rollback(self):
        for mutation in ('task_id', 'launch_nonce', 'pid', 'scene_epoch', 'generation', 'recreated_node'):
            with self.subTest(mutation=mutation), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.initialize()
                item = fixture.prepared(10)
                if mutation == 'scene_epoch':
                    fixture.addon._BRIDGE_SCENE_STATE.scene_epoch += 1
                elif mutation == 'generation':
                    fixture.identity['process_generation'] = 'other-generation'
                elif mutation == 'recreated_node':
                    fixture.carrier.session += 1
                else:
                    fixture.identity[mutation] = 'foreign' if mutation != 'pid' else os.getpid() + 1
                fixture.set_calls.clear()
                with self.assertRaises((ValueError, self.addon.BridgeCommandError)):
                    fixture.host.write(item, fixture.roles, fixture.pack)
                with self.assertRaises((ValueError, self.addon.BridgeCommandError)):
                    fixture.host.restore(item, fixture.roles, fixture.pack)
                self.assertFalse(fixture.set_calls)

    def test_snippet_and_scope_channel_drift_reject_before_write(self):
        for name, drift in (('group', 'value'), ('snippet', 'foreign'), ('snippet', 'driver'),
                            ('snippet', 'locked'), ('snippet', 'extrapolation'),
                            ('exportlist', 'hidden'), ('vex_updatenmls', 'value')):
            with self.subTest(name=name, drift=drift), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.initialize()
                item = fixture.prepared(1)
                parameter = fixture.carrier.parameters[name]
                if drift == 'driver':
                    parameter.driver = 'ch("../other")'
                elif drift in ('locked', 'hidden'):
                    parameter.flags[drift] = True
                elif drift == 'extrapolation':
                    parameter.extrapolation[0] = 'cycle'
                else:
                    parameter.value = 1 if name == 'vex_updatenmls' else 'foreign'
                fixture.set_calls.clear()
                with self.assertRaises(ValueError):
                    fixture.write(item)
                self.assertFalse(fixture.set_calls)

    def test_partial_setter_and_postwrite_source_failures_restore_native_state(self):
        for mutation in ('partial_set', 'source', 'userdata', 'extrapolation'):
            with self.subTest(mutation=mutation), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                fixture.initialize()
                before = fixture.host.observations(fixture.roles, fixture.pack)
                item = fixture.prepared(7)
                parameter = fixture.carrier.parameters['snippet']
                if mutation == 'partial_set':
                    parameter.fail_once = True
                elif mutation == 'source':
                    parameter.on_set = lambda: fixture.source['point_attributes']['P']['values'][1].__setitem__(0, 123.)
                elif mutation == 'extrapolation':
                    parameter.on_set = lambda: parameter.extrapolation.__setitem__(0, 'cycle')
                else:
                    parameter.on_set = lambda: fixture.carrier.setUserData(adapter.BASIS_KEY, 'interrupted')
                with self.assertRaises((ValueError, self.addon.BridgeCommandError)):
                    fixture.write(item)
                parameter.on_set = None
                fixture.restore(item)
                fixture.source = copy.deepcopy(before['context']['source'])
                self.assertEqual(fixture.host.observations(fixture.roles, fixture.pack), before)

    def test_initialization_userdata_failure_revokes_and_leaves_no_registration(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.carrier.fail_userdata_once = adapter.REGISTRATION_KEY
            with self.assertRaisesRegex(ValueError, 'partial native userData failure'):
                fixture.initialize()
            self.assertFalse(fixture.records)
            self.assertIsNone(fixture.carrier.userData(adapter.BASIS_KEY))
            self.assertIsNone(fixture.carrier.userData(adapter.REGISTRATION_KEY))

    def test_plan_and_descriptor_tampering_and_value_only_snapshot_are_rejected(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            plan = fixture.host.plan(1, fixture.roles, fixture.pack)
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                fixture.host.prepare(replace(plan, value=2), fixture.roles, fixture.pack)
            item = fixture.prepared(1)
            item['native_write']['value'] = 'foreign();'
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_PLAN_CHANGED'):
                fixture.write(item)
            original = fixture.carrier.parameters['snippet'].setKeyframes
            fixture.carrier.parameters['snippet'].setKeyframes = None
            try:
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    fixture.prepared(1)
                self.assertEqual(caught.exception.code, 'PARAMETER_SNAPSHOT_FAILED')
            finally:
                fixture.carrier.parameters['snippet'].setKeyframes = original

    def test_rollback_failure_is_reported_but_userdata_restore_is_still_attempted(self):
        with Fixture(self.addon, program.VERSIONS[0]) as fixture:
            fixture.initialize()
            item = fixture.prepared(2)
            fixture.write(item)
            before = dict(fixture.carrier.userdata)
            fixture.carrier.setUserData(adapter.BASIS_KEY, 'interrupted')
            fixture.carrier.parameters['snippet'].flags['locked'] = True
            with self.assertRaisesRegex(ValueError, 'GEOMETRY_RESTORE_FAILED'):
                fixture.restore(item)
            self.assertEqual(fixture.carrier.userdata, before)

    def test_required_layout_and_explicit_rest_coordinates_are_not_inferred(self):
        for mutation in ('domain', 'missing_role', 'creation_record', 'space', 'unit', 'axis', 'output', 'input_version'):
            with self.subTest(mutation=mutation), Fixture(self.addon, program.VERSIONS[0]) as fixture:
                if mutation == 'domain':
                    fixture.pack['native_domain_id'] = 'particles_v1'
                elif mutation == 'missing_role':
                    fixture.roles.pop(program.ROLE)
                elif mutation == 'creation_record':
                    fixture.fresh.clear()
                    with self.assertRaisesRegex(ValueError, 'GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED'):
                        fixture.host.initialize({}, fixture.roles, fixture.pack, {program.ROLE})
                    self.assertFalse(fixture.set_calls)
                    continue
                else:
                    field, value = {'space': ('space', 'sop_local'), 'unit': ('unit', 'm'),
                        'axis': ('local_x_axis', [0., 1., 0.]), 'output': ('output', 1),
                        'input_version': ('input_version', '')}[mutation]
                    fixture.provenance[field] = value
                with self.assertRaises(ValueError):
                    fixture.initialize()
                self.assertFalse(fixture.set_calls)
