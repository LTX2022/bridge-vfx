"""A01 observations and bottom HOM API fixtures; no solver or native cook."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_pyro_domains as pyro
from houdini_bridge import native_pyro_height_program as height
from houdini_bridge.native_pyro_height_host import Host, BASIS_KEY, PROGRAM_KEY
from vfx_pipeline.workbuddy_assembly import software_host_client

ROOT = Path(__file__).resolve().parents[2]
SOURCE_INPUT = {'emission_windows': [(1, 2)], 'direction': [0, 1, 0],
                'spread': 30, 'speed': 2, 'particle_separation': .1}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_height_source_api(hou, roles, source_vertices):
    """Install explicit bottom geometry/flag API for an already built graph.

    Source vertices are native API fixture inputs, never flame output, solver
    results or operation receipts. Any request for solver geometry is rejected.
    """
    node_class = type(hou.node(roles['source']))
    node_class.isBypassed = lambda node: False
    node_class.destroyUserData = lambda node, key: node._data.pop(key, None)
    node_class.userDataDict = lambda node: copy.deepcopy(node._data)
    def geometry_at_frame(node, frame, output_index=0):
        if node.path() != roles['source'] or output_index != 0:
            raise AssertionError('height host must never request solver geometry')
        vertices = [SimpleNamespace(point=lambda position=position: SimpleNamespace(position=lambda: tuple(position)))
                    for position in source_vertices]
        primitive = SimpleNamespace(type=lambda: SimpleNamespace(name=lambda: 'Polygon'), vertices=lambda: vertices)
        return SimpleNamespace(prims=lambda: [primitive])
    node_class.geometryAtFrame = geometry_at_frame


def make_context(version):
    root = '/obj/pyro_task'
    source = {'origin': 'runtime_hom', 'node_path': root + '/source', 'output': 0,
              'space': 'sop_local', 'frame': 1., 'point_positions': [[-1, -1, 0], [1, 1, 0], [0, 0, 1]]}
    registration = pyro.source_program(pyro.FIRE, version, SOURCE_INPUT)
    basis = height.freeze_basis(version, 5., [0., 1., 0.], source, task_id='pyro_task', task_root=root,
        input_version='v1', basis_input_sha256='a' * 64, source_program_sha256=registration['sha256'])
    nodes = {}
    for role, kind in (('source', 'sphere'), ('solver', 'pyrosolver'), ('flame_height', 'volumewrangle'), ('output', 'null')):
        nodes[role] = {'origin': 'runtime_hom', 'task_owned': True, 'task_id': 'pyro_task',
            'task_root': root, 'native_version': version, 'input_version': 'v1',
            'category': 'sop', 'path': root + '/' + role, 'type': kind,
            'editable': True, 'bypassed': False, 'space': 'sop_local', 'inputs': []}
    for downstream, upstream in (('flame_height', 'solver'), ('output', 'flame_height')):
        nodes[downstream]['inputs'] = [{'input_index': 0, 'output_index': 0, 'node_path': nodes[upstream]['path']}]
    production = {'origin': 'runtime_hom', 'node_path': nodes['solver']['path'],
        'addflamefield': {'origin': 'runtime_hom', 'type': 'toggle', 'size': 1, 'value': 1, 'driven': False},
        'conv_vdb': {'origin': 'runtime_hom', 'type': 'toggle', 'size': 1, 'value': 0, 'driven': False},
        'exports': [{'enable': {'origin': 'runtime_hom', 'type': 'toggle', 'value': 1, 'driven': False},
                     'name': {'origin': 'runtime_hom', 'type': 'string', 'value': name, 'driven': False}}
                    for name in ('density', 'temperature', 'vel', 'flame')]}
    return {'basis': basis, 'source': source, 'source_input': copy.deepcopy(SOURCE_INPUT), 'production': production,
            'source_program': registration, 'source_program_observation': {'origin': 'runtime_hom',
                'type': 'string', 'size': 1, 'value': registration['program'], 'driven': False}, 'nodes': nodes}


def make_parameters():
    values = dict(height.GATES, snippet=('string', ''))
    return {(height.ROLE, name): {'origin': 'runtime_hom', 'type': kind, 'size': 1,
            'value': value, 'locked': False, 'disabled': False, 'hidden': False, 'driven': False}
            for name, (kind, value) in values.items()}


class NativePyroHeightProgramTests(unittest.TestCase):
    def test_signed_offsets_and_basis_zero_nonpositive_programs_both_versions(self):
        for version in pyro.SUPPORTED_VERSIONS:
            context = make_context(version)
            for value in (-100, -5, -2, 0, 2, 1000):
                with self.subTest(version=version, value=value):
                    parameters = make_parameters()
                    candidate = height.plan_control(version, value, context, parameters)
                    writes = height.validate_plan(candidate, context, parameters)
                    self.assertEqual(len(writes), 1)
                    self.assertEqual(writes[0]['role'], height.ROLE)
                    self.assertNotIn('buoyancy', writes[0]['value'])
                    self.assertNotIn('@density', writes[0]['value'])
                    self.assertNotIn('@temperature', writes[0]['value'])
                    self.assertIn('height_upper <= 0', writes[0]['value'])
                    parameters[height.ROLE, 'snippet']['value'] = writes[0]['value']
                    height.validate_plan(candidate, context, parameters, after_mutation=True)
                    self.assertEqual(height.control_readback(version, context, parameters)['value'], value)
                    self.assertEqual(height.rollback_plan(candidate, context, parameters)[0]['value'], '')
                    self.assertEqual(pyro.control_readback(pyro.FIRE, 'flame_height', parameters, version,
                                                           height_context=context), value)
                    self.assertEqual(height._hash(pyro.control_write_plan(pyro.FIRE, 'flame_height', value, version,
                                                             height_context=context)), height._hash(writes))

    def test_missing_invalid_baseline_numeric_and_graph_facts_refuse(self):
        version = pyro.SUPPORTED_VERSIONS[0]
        for context in (None, {}, {'basis': {}}):
            with self.assertRaises(pyro.NativePyroDomainError):
                height.source_program(version, 0, context)
        context = make_context(version)
        for value in (True, '2', float('nan'), float('inf'), -101, 1001):
            with self.assertRaises(pyro.NativePyroDomainError):
                height.source_program(version, value, context)
        for key, value in (('h_base', 0), ('h_base', -1), ('axis', [0, 0, 0]),
                           ('source_top', 2), ('native_version', '22.0.429'), ('space', 'world')):
            changed = copy.deepcopy(context)
            changed['basis'][key] = value
            changed['basis']['content_sha256'] = height.basis_content_sha256(changed['basis'])
            with self.assertRaises(pyro.NativePyroDomainError):
                height.source_program(version, 1, changed)
        for role, key, value in (('flame_height', 'type', 'staticvolumewrangle'),
            ('flame_height', 'editable', False), ('flame_height', 'bypassed', True),
            ('flame_height', 'task_owned', False), ('solver', 'native_version', '22.0.429'),
            ('source', 'path', '/obj/foreign/source'), ('output', 'inputs', [])):
            changed = copy.deepcopy(context)
            changed['nodes'][role][key] = value
            with self.assertRaises(pyro.NativePyroDomainError):
                height.source_program(version, 1, changed)
        for name in ('source_program_observation', 'source_input'):
            changed = copy.deepcopy(context)
            changed.pop(name)
            with self.assertRaises(pyro.NativePyroDomainError):
                height.source_program(version, 1, changed)

    def test_runtime_channels_scope_and_local_seal_reject_rehash_tampering(self):
        version = pyro.SUPPORTED_VERSIONS[0]
        context, parameters = make_context(version), make_parameters()
        plan = height.plan_control(version, -2, context, parameters)
        for name, key, value in (('snippet', 'origin', 'requested'), ('snippet', 'driven', True),
                ('snippet', 'size', True), ('group', 'value', ''), ('exportlist', 'value', '*'),
                ('vex_precision', 'value', '32'), ('bindeach', 'value', False)):
            changed = copy.deepcopy(parameters)
            changed[height.ROLE, name][key] = value
            with self.assertRaises(pyro.NativePyroDomainError):
                height.validate_plan(plan, context, changed)
        for changed in (replace(plan, value=3), replace(plan, writes_json='[]'), replace(plan, seal='0' * 64)):
            with self.assertRaisesRegex(pyro.NativePyroDomainError, 'INVALID_PLAN'):
                height.validate_plan(changed, context, parameters)
        changed = copy.deepcopy(context)
        changed['basis']['h_base'] = 10.
        changed['basis']['content_sha256'] = height.basis_content_sha256(changed['basis'])
        with self.assertRaisesRegex(pyro.NativePyroDomainError, 'BASIS_CHANGED'):
            height.validate_plan(plan, changed, parameters)
        with self.assertRaisesRegex(pyro.NativePyroDomainError, 'INVALID_PLAN'):
            height.validate_plan(plan, context, parameters, after_mutation=1)

    def test_independent_readback_refuses_program_replacement_and_missing_runtime(self):
        version = pyro.SUPPORTED_VERSIONS[0]
        context = make_context(version)
        parameters = make_parameters()
        parameters[height.ROLE, 'snippet']['value'] = height.source_program(version, 1, context)['program']
        with self.assertRaisesRegex(pyro.NativePyroDomainError, 'RUNTIME_REQUIRED'):
            height.control_readback(version, context, {})
        for content in ('', 'f@flame = 0;', parameters[height.ROLE, 'snippet']['value'] + 'f@density=0;\n',
                        parameters[height.ROLE, 'snippet']['value'].replace('height_from_source >', 'height_from_source <')):
            changed = copy.deepcopy(parameters)
            changed[height.ROLE, 'snippet']['value'] = content
            with self.assertRaisesRegex(pyro.NativePyroDomainError, 'READBACK_MISMATCH'):
                height.control_readback(version, context, changed)

    def test_dense_volume_reads_actual_native_centers_and_values_preserves_other_fields(self):
        context = make_context(pyro.SUPPORTED_VERSIONS[0])
        names = ('flame', 'density', 'temperature', 'vel.x', 'vel.y', 'vel.z')
        class Volume:
            def __init__(self, name, values):
                self.name, self.values = name, values
            def type(self): return SimpleNamespace(name=lambda: 'Volume')
            def channelCount(self): return 1
            def isSDF(self): return False
            def attribValue(self, name): return self.name
            def resolution(self): return (1, 3, 1)
            def indexToPos(self, index): return (0., float(index[1] * 3), 0.)
            def voxel(self, index): return self.values[index[1]]
        parameters = make_parameters()
        for value, expected in ((-100, [0., 0., 0.]), (-5, [0., 0., 0.]),
                                (-2, [1., 2., 0.]), (0, [1., 2., 3.]), (1000, [1., 2., 3.])):
            parameters[height.ROLE, 'snippet']['value'] = height.source_program('21.0.631', value, context)['program']
            original = [Volume(name, [1., 2., 3.]) for name in names]
            masked = [Volume(name, expected if name == 'flame' else [1., 2., 3.]) for name in names]
            before = height.collect_volume_fields(SimpleNamespace(prims=lambda: original),
                node_path=context['nodes']['solver']['path'], frame=1.)
            after = height.collect_volume_fields(SimpleNamespace(prims=lambda: masked),
                node_path=context['nodes']['flame_height']['path'], frame=1.)
            result = height.validate_volume_readback('21.0.631', context, parameters, before, after)
            self.assertEqual(result['evidence_scope'], 'observed_dense_volume_comparison')
            changed = copy.deepcopy(after)
            changed['fields']['density']['values'][0] = 10.
            with self.assertRaisesRegex(pyro.NativePyroDomainError, 'VOLUME_READBACK_MISMATCH'):
                height.validate_volume_readback('21.0.631', context, parameters, before, changed)
            with self.assertRaisesRegex(pyro.NativePyroDomainError, 'BUDGET_EXCEEDED'):
                height.collect_volume_fields(SimpleNamespace(prims=lambda: original),
                    node_path=context['nodes']['solver']['path'], frame=1., max_voxels=1)

    def test_public_topology_preserves_all_smoke_fire_control_targets(self):
        for version in pyro.SUPPORTED_VERSIONS:
            nodes = {node['role']: node for node in pyro.node_requirements(pyro.FIRE, version)}
            self.assertEqual(nodes[height.ROLE]['types'], ['volumewrangle'])
            self.assertEqual(nodes[height.ROLE]['input_role'], 'solver')
            self.assertEqual(nodes['output']['input_role'], height.ROLE)
            self.assertEqual(len(pyro.control_contract(pyro.FIRE, version)), 12)
            for domain in (pyro.SMOKE, pyro.FIRE):
                for name, contract in pyro.control_contract(domain, version).items():
                    if contract['native_status'] == 'external' or name in ('flame_height', 'burn_rate'):
                        continue
                    value = max(contract['minimum'], 1.)
                    writes = pyro.control_write_plan(domain, name, value, version)
                    self.assertEqual(pyro.control_readback(domain, name,
                        {(write['role'], write['parm']): write['value'] for write in writes}, version), value)

    def test_core_preflight_binds_height_context_and_rejects_program_and_basis_replacement(self):
        version = '21.0.631'
        context = make_context(version)
        writes = pyro.candidate_write_plan(pyro.FIRE, {'flame_height': -2}, version, height_context=context)
        parameters = make_parameters()
        parameters[height.ROLE, '@height_context'] = context
        pyro.validate_control_write_plan(writes, parameters)
        changed = copy.deepcopy(writes)
        changed[0]['value'] = 'f@flame = 0;'
        changed[0]['trusted_program']['program'] = changed[0]['value']
        changed[0]['trusted_program']['sha256'] = hashlib.sha256(changed[0]['value'].encode()).hexdigest()
        with self.assertRaisesRegex(pyro.NativePyroDomainError, 'INVALID_PLAN'):
            pyro.validate_control_write_plan(changed, parameters)
        parameters[height.ROLE, '@height_context']['basis']['h_base'] = 6.
        parameters[height.ROLE, '@height_context']['basis']['content_sha256'] = height.basis_content_sha256(context['basis'])
        with self.assertRaisesRegex(pyro.NativePyroDomainError, 'INVALID_PLAN'):
            pyro.validate_control_write_plan(writes, parameters)

    def test_windows_installed_public_hda_gates_and_hom_coordinate_sources_both_versions(self):
        native = load_module('pyro_height_capture_reader', ROOT / 'tools/capture_native_schema.py')
        missing = []
        for version in pyro.SUPPORTED_VERSIONS:
            install = Path('C:/Program Files/Side Effects Software') / ('Houdini ' + version)
            archive = install / 'houdini/otls/OPlibSop.hda'
            if not archive.is_file():
                missing.append(str(archive))
                continue
            operator = native.index_sections(archive.read_bytes())['Sop/volumewrangle']
            sections = native.index_sections(operator)
            fields = native.dialog_parameters(sections['DialogScript'])
            for name, (kind, value) in height.GATES.items():
                self.assertEqual(fields[name]['type'], kind)
                self.assertEqual(fields[name]['size'], 1)
                self.assertEqual(fields[name]['disable_when'], '{ bindeach == 1 }' if name == 'autobind' else '')
                self.assertEqual(fields[name]['hide_when'], '')
                if fields[name]['menu_tokens']:
                    self.assertIn(value, fields[name]['menu_tokens'][::2])
            self.assertEqual(fields['snippet']['type'], 'string')
            toolkit = install / 'toolkit/include/HOM'
            volume = (toolkit / 'HOM_Volume.h').read_text(encoding='utf-8')
            for signature in ('indexToPos(', 'voxel(', 'resolution()', 'channelCount()', 'isSDF()'):
                self.assertIn(signature, volume)
            sop = (toolkit / 'HOM_SopNode.h').read_text(encoding='utf-8')
            self.assertIn('geometryAtFrame(double frame, int output_index=0)', sop)
        if missing:
            self.skipTest('NOT_RUN: local installed originals missing: ' + ';'.join(missing))


class NativePyroHeightHostTests(unittest.TestCase):
    def test_missing_basis_diagnostic_initializer_never_authenticates_or_cooks(self):
        hou = SimpleNamespace(node=lambda path: None)
        with patch.dict(sys.modules, {'hou': hou}):
            host = Host({'_fx_configuration': lambda params: {},
                         'BridgeCommandError': RuntimeError})
            result = host.initialize({}, {}, {}, set())
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['code'], 'PYRO_HEIGHT_BASIS_REQUIRED')

    def make_host(self, directory, version):
        client, addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', directory / 'host')
        native = load_module('pyro_height_schema', ROOT / 'tools/native_schema_test_boundary.py')
        api = load_module('pyro_height_render_api', ROOT / 'tools/software_render_api_boundary.py')
        interfaces, states, ports = api.interface_profiles(ROOT, version)
        native.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', version,
                             instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        hou = sys.modules['hou']
        addon._TASK_HOST_IDENTITY = dict(addon._host_identity(), task_id='pyro-height-task',
            pid=os.getpid(), launch_nonce='pyro-height-local-unit', version=version,
            plugin_build=addon._FX_LOADED_ADDON_SHA256)
        root_path = client.call('scene.create_task_root', {'task_id': 'pyro-height-task',
            'root_name': 'BRIDGE_GRAPH_' + hashlib.sha256(b'pyro-height-task').hexdigest()})['path']
        root = hou.node(root_path)
        root.setUserData('bridge_fx_owned', '1')
        pack = {'native_domain_id': pyro.FIRE, 'nodes': pyro.node_requirements(pyro.FIRE, version)}
        roles = {}
        for requirement in pack['nodes']:
            node = root.createNode(requirement['types'][0], requirement['role'])
            roles[requirement['role']] = node.path()
        for connection in pyro.connection_requirements(pyro.FIRE, version):
            hou.node(roles[connection['destination_role']]).setInput(connection['destination_input'],
                hou.node(roles[connection['source_role']]), connection['source_output'])
        registration = pyro.source_program(pyro.FIRE, version, SOURCE_INPUT)
        hou.node(roles['source_control']).parm('snippet').set(registration['program'])
        solver = hou.node(roles['solver'])
        solver.parm('numfields').set(4)
        solver.parm('addflamefield').set(1)
        solver.parm('conv_vdb').set(0)
        for index, name in enumerate(('density', 'temperature', 'vel', 'flame'), 1):
            solver.parm('export_enable' + str(index)).set(1)
            solver.parm('export_fieldname' + str(index)).set(name)
        source_vertices = [[-1., -1., 0.], [1., 1., 0.], [0., 0., 1.]]
        install_height_source_api(hou, roles, source_vertices)
        return Host(vars(addon)), addon, hou, roles, pack, source_vertices

    def run_host_case(self, version, check):
        with tempfile.TemporaryDirectory(prefix='bridge-pyro-height-') as temp, patch.dict(sys.modules):
            directory = Path(temp)
            with patch.dict(os.environ, {'BRIDGE_SKILLS_STATE_ROOT': str(directory / 'state'),
                'HOUDINI_BRIDGE_STATE_DIR': str(directory / 'houdini'),
                'BRIDGE_SKILLS_SCHEDULER_ROOT': str(directory / 'scheduler')}):
                host, addon, hou, roles, pack, vertices = self.make_host(directory, version)
                supplied = {'h_base': 5., 'axis': [0., 1., 0.], 'source_input': copy.deepcopy(SOURCE_INPUT),
                            'input_version': 'v1', 'basis_input_sha256': 'b' * 64}
                params = {'constraints': {'fx': {'domain_pack': pyro.FIRE, 'pyro_height_basis': supplied}}}
                check(host, addon, hou, roles, pack, vertices, params)

    def test_actual_host_carrier_initialize_signed_edit_readback_and_restore_two_versions(self):
        def check(host, addon, hou, roles, pack, vertices, params):
            node = hou.node(roles[height.ROLE])
            blocked = host.initialize({'constraints': {'fx': {}}}, roles, pack, set(roles))
            self.assertEqual(blocked['status'], 'blocked')
            self.assertIsNone(node.userData(BASIS_KEY))
            initial = host.initialize(params, roles, pack, set(roles))
            self.assertEqual(initial['value'], 0.)
            self.assertEqual(initial['evidence_scope'], 'parameters_only')
            candidate = host.plan(-2., roles, pack)
            after = host.write(candidate, roles, pack)
            self.assertEqual(after['value'], -2.)
            self.assertIn('height_upper = 5 + (-2)', node.parm('snippet').eval())
            self.assertEqual(host.readback(roles, pack)['value'], -2.)
            host.restore(candidate['snapshot'], roles, pack)
            self.assertEqual(host.readback(roles, pack)['value'], 0.)
            for value in (-100., -5., 1000.):
                self.assertEqual(host.write(host.plan(value, roles, pack), roles, pack)['value'], value)
            self.assertEqual(host.initialize(params, roles, pack, set())['value'], 1000.)
            changed = copy.deepcopy(params)
            changed['constraints']['fx']['pyro_height_basis']['h_base'] = 6.
            with self.assertRaises(addon.BridgeCommandError) as error:
                host.initialize(changed, roles, pack, set())
            self.assertEqual(error.exception.code, 'PYRO_HEIGHT_BASIS_CHANGED')
        for version in pyro.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                self.run_host_case(version, check)

    def test_actual_host_channel_source_topology_registration_and_owner_drift_reject(self):
        def check(host, addon, hou, roles, pack, vertices, params):
            host.initialize(params, roles, pack, set(roles))
            candidate = host.plan(-2., roles, pack)
            node = hou.node(roles[height.ROLE])
            snippet = node.parm('snippet')
            saved = snippet.eval()
            snippet.set('f@flame=0;')
            with self.assertRaises(pyro.NativePyroDomainError):
                host.write(candidate, roles, pack)
            snippet.set(saved)
            vertices[0][1] = 100.
            with self.assertRaises(addon.BridgeCommandError) as error:
                host.readback(roles, pack)
            self.assertEqual(error.exception.code, 'PYRO_HEIGHT_BASIS_CHANGED')
            vertices[0][1] = -1.
            output = hou.node(roles['output'])
            output.setInput(0, hou.node(roles['solver']))
            with self.assertRaises(addon.BridgeCommandError) as error:
                host.write(candidate, roles, pack)
            self.assertEqual(error.exception.code, 'PYRO_HEIGHT_CONNECTION_REQUIRED')
            output.setInput(0, node)
            saved_registration = node.userData(PROGRAM_KEY)
            node.setUserData(PROGRAM_KEY, '{}')
            with self.assertRaises(addon.BridgeCommandError) as error:
                host.readback(roles, pack)
            self.assertEqual(error.exception.code, 'PYRO_HEIGHT_READBACK_MISMATCH')
            node.setUserData(PROGRAM_KEY, saved_registration)
            addon._TASK_HOST_IDENTITY['task_id'] = 'foreign'
            with self.assertRaises(addon.BridgeCommandError) as error:
                host.write(candidate, roles, pack)
            self.assertEqual(error.exception.code, 'PYRO_HEIGHT_OWNED_GRAPH_REQUIRED')
            self.assertEqual(snippet.eval(), saved)
        for version in pyro.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                self.run_host_case(version, check)

    def test_actual_host_write_failure_restores_channel_and_registrations(self):
        def check(host, addon, hou, roles, pack, vertices, params):
            host.initialize(params, roles, pack, set(roles))
            candidate = host.plan(-2., roles, pack)
            node = hou.node(roles[height.ROLE])
            before = node.parm('snippet').eval(), node.userDataDict()
            original = type(node).setUserData
            failed = [False]
            def fail_registration(current, key, value):
                if current is node and key == PROGRAM_KEY and not failed[0]:
                    failed[0] = True
                    raise RuntimeError('bottom HOM userdata write failed')
                return original(current, key, value)
            with patch.object(type(node), 'setUserData', fail_registration):
                with self.assertRaisesRegex(RuntimeError, 'bottom HOM'):
                    host.write(candidate, roles, pack)
            self.assertEqual((node.parm('snippet').eval(), node.userDataDict()), before)
            self.assertEqual(host.readback(roles, pack)['value'], 0.)
        for version in pyro.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                self.run_host_case(version, check)

    def test_actual_host_initializer_failure_restores_original_blank_carrier(self):
        def check(host, addon, hou, roles, pack, vertices, params):
            node = hou.node(roles[height.ROLE])
            before = node.userDataDict()
            original = type(node).setUserData
            failed = [False]
            def fail_basis(current, key, value):
                if current is node and key == BASIS_KEY and not failed[0]:
                    failed[0] = True
                    raise RuntimeError('bottom HOM basis storage failed')
                return original(current, key, value)
            with patch.object(type(node), 'setUserData', fail_basis):
                with self.assertRaisesRegex(RuntimeError, 'basis storage'):
                    host.initialize(params, roles, pack, set(roles))
            self.assertEqual(node.userDataDict(), before)
            self.assertIsNone(node.userData(BASIS_KEY))
            self.assertIsNone(node.userData(PROGRAM_KEY))
            self.assertEqual(node.parm('snippet').eval(), '')
        for version in pyro.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                self.run_host_case(version, check)

    def test_actual_host_rollback_token_cannot_replace_original_channel_snapshot(self):
        def check(host, addon, hou, roles, pack, vertices, params):
            host.initialize(params, roles, pack, set(roles))
            candidate = host.plan(-2., roles, pack)
            host.write(candidate, roles, pack)
            changed = copy.deepcopy(candidate['snapshot'])
            changed['channels'] = {'snippet': {'value': 'f@flame=0;'}}
            with self.assertRaises(addon.BridgeCommandError) as error:
                host.restore(changed, roles, pack)
            self.assertEqual(error.exception.code, 'PYRO_HEIGHT_ROLLBACK_OWNER_CHANGED')
            changed = copy.deepcopy(candidate['snapshot'])
            changed['token'] = 'different'
            with self.assertRaises(addon.BridgeCommandError):
                host.restore(changed, roles, pack)
            host.restore(candidate['snapshot'], roles, pack)
            host.restore(candidate['snapshot'], roles, pack)
            host.release_snapshot(candidate['snapshot'])
            self.assertEqual(host.readback(roles, pack)['value'], 0.)
        for version in pyro.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                self.run_host_case(version, check)


if __name__ == '__main__':
    unittest.main()
