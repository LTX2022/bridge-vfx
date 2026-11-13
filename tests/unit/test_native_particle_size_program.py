"""P02 contract tests with explicit bottom parameter/topology/geometry APIs.

No facade, producer success, native random samples, or supervisor is replaced.
"""
import copy
from dataclasses import replace
import json
from pathlib import Path, PurePosixPath
import unittest

from houdini_bridge import native_particle_ocean_geometry_domains as core
from houdini_bridge import native_particle_size_program as program


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / 'docs/native-basis/hda-interface-capture.json'


class BottomParameter:
    def __init__(self, raw):
        self.kind, self.size = raw['type'], raw['size']
        self.tokens = raw.get('menu_tokens', [])[::2]
        self.token_value = raw.get('menu_uses_token_value', False)
        self.flags = dict(driven=False, locked=False, disabled=False, hidden=False)
        token = raw['default_tokens'][0]
        if self.kind == 'float':
            self.value = float(token)
        elif self.kind == 'integer':
            self.value = int(token)
        elif self.kind == 'toggle':
            self.value = {'off': 0, 'on': 1}.get(token, int(token) if token.isdigit() else None)
        else:
            self.value = token

    def set(self, value):
        if any(self.flags.values()) or not core._typed_value(value, self.kind, self.size):
            raise ValueError('bottom parameter is unavailable or value is invalid')
        if self.kind == 'ordinal' and value not in self.tokens:
            raise ValueError('bottom native menu token is unavailable')
        self.value = copy.deepcopy(value)

    def eval(self):
        return copy.deepcopy(self.value)

    def observe(self):
        observed = dict(origin='runtime_hom', type=self.kind, size=self.size,
                        value=self.eval(), **self.flags)
        if self.kind == 'ordinal':
            observed.update(menu_tokens=self.tokens[:], menu_uses_token_value=self.token_value)
        return observed


class BottomNode:
    def __init__(self, requirement, version):
        self.role, self.version = requirement['role'], version
        self.kind, self.category = requirement['types'][0], requirement['category']
        parent = '/obj/p02_api/simulation' if self.category == 'dop' else '/obj/p02_api'
        self.path, self.inputs = parent + '/' + self.role, {}

    def observe(self):
        return dict(origin='runtime_hom', task_owned=True, task_id='p02-api-task',
                    native_version=self.version, task_root='/obj/p02_api',
                    path=self.path, type=self.kind, category=self.category,
                    context_parent_path=str(PurePosixPath(self.path).parent))


class BottomHost:
    def __init__(self, version):
        self.version = version
        captured = json.loads(CAPTURE.read_text(encoding='utf-8'))
        record = captured['versions'][version]['operators']['Sop/attribadjustfloat']
        self.section_sha256 = record['section_sha256']
        names = set(program.COMMON_GATES) | {
            'valuetype', 'singlevalue', 'rangemethod', 'distribinrange', 'randmethod',
            'randattrib', 'randomseed', 'enablestepping', 'minvalue', 'rangevalue',
        }
        self.parameters = {name: BottomParameter(record['parameters'][name]) for name in names}
        for name, (_, value) in program.COMMON_GATES.items():
            self.parameters[name].set(value)
        self.parameters['valuetype'].set('const')
        self.parameters['singlevalue'].set(.25)
        self.nodes = {item['role']: BottomNode(item, version)
                      for item in core.node_requirements(core.PARTICLES, version)}
        for edge in core.connection_requirements(core.PARTICLES, version):
            self.nodes[edge['destination_role']].inputs[edge['destination_input']] = (
                self.nodes[edge['source_role']], edge['source_output'])
        self.points = [dict(id=identity, v=[.5, 0., 0.], age=.1, pscale=.25)
                       for identity in (7, 19, 31)]
        node = self.nodes[program.ROLE]
        self.basis = dict(schema=program.BASIS_SCHEMA, origin='runtime_hom', task_owned=True,
                          task_id='p02-api-task', task_root='/obj/p02_api', node_path=node.path,
                          native_version=version, size=self.parameters['singlevalue'].eval(),
                          task_seed=37, id_attribute='id')
        self.basis['content_sha256'] = program.basis_content_sha256(self.basis)

    def geometry(self):
        attributes = {}
        for name, kind, size, precision in (
            ('id', 'integer', 1, 'int32'), ('v', 'float', 3, 'float32'),
            ('age', 'float', 1, 'float32'), ('pscale', 'float', 1, 'float32'),
        ):
            attributes[name] = dict(type=kind, size=size, owner='point', precision=precision,
                                    is_array=False, values=[copy.deepcopy(point[name]) for point in self.points])
        return dict(origin='runtime_hom', points=len(self.points), primitives=0,
                    point_attributes=attributes)

    def observe(self):
        observed = {(role, '@node'): node.observe() for role, node in self.nodes.items()}
        for role, node in self.nodes.items():
            for destination, (source, output) in node.inputs.items():
                observed[role, '@input/' + str(destination)] = dict(
                    origin='runtime_hom', task_owned=True, source_path=source.path,
                    source_type=source.kind, source_output=output, destination_input=destination)
        for name, parameter in self.parameters.items():
            observed[program.ROLE, name] = parameter.observe()
        observed[program.ROLE, '@size_basis'] = copy.deepcopy(self.basis)
        for role in ('simulation', program.ROLE, 'output'):
            observed[role, '@geometry/0'] = self.geometry()
        return observed

    def apply(self, plan):
        for write in sorted(plan.writes, key=lambda item: item['phase'] != 'gates'):
            self.parameters[write['parm']].set(write['value'])


class ParticleSizeProgramTests(unittest.TestCase):
    def hosts(self):
        return (BottomHost(version) for version in core.VERSIONS)

    def test_current_route_and_missing_host_facts_refused(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    core.control_write_plan(core.PARTICLES, 'size_variance', 100, version, observations={})
                with self.assertRaisesRegex(ValueError, 'ACTUAL_TASK_OWNED_NATIVE_NODE_REQUIRED'):
                    program.plan_size_variance(100, version, observations={})

    def test_zero_restores_actual_constant_without_changing_random_or_other_data(self):
        for host in self.hosts():
            with self.subTest(version=host.version):
                randomized = program.plan_size_variance(100, host.version, observations=host.observe())
                host.apply(randomized)
                before = host.observe()
                plan = program.plan_size_variance(0, host.version, observations=before)
                self.assertEqual(len(plan.writes), 2)
                host.apply(plan)
                result = program.validate_applied_readback(plan, host.observe())
                self.assertEqual(result.observed_percentage, 0)
                self.assertEqual(result.parameters['singlevalue'], .25)
                self.assertEqual(result.evidence_scope, 'parameters_only')
                self.assertIn('actual_random_pscale_by_stable_id', result.missing_evidence)
                after = host.observe()
                for key in before:
                    if key not in {(program.ROLE, 'valuetype'), (program.ROLE, 'singlevalue')}:
                        self.assertEqual(before[key], after[key])

    def test_both_captured_interfaces_numeric_endpoints_and_actual_parameter_readback(self):
        for host in self.hosts():
            self.assertEqual(host.section_sha256, '23de8cbbf6748d8d9dd96b8ffdf2fda6b3717909f60b57aa51d3e56ecaaffd89')
            for percentage in (1., 50., 100.):
                with self.subTest(version=host.version, percentage=percentage):
                    before = host.observe()
                    plan = program.plan_size_variance(percentage, host.version, observations=before)
                    self.assertEqual(host.observe(), before)
                    host.apply(plan)
                    result = program.validate_applied_readback(plan, host.observe())
                    self.assertAlmostEqual(result.observed_percentage, percentage)
                    self.assertEqual(result.parameters['randmethod'], 'custom')
                    self.assertEqual(result.parameters['randattrib'], 'id')
                    factor = 1 + percentage / 100
                    self.assertAlmostEqual(result.parameters['minvalue'], .25 / factor)
                    self.assertAlmostEqual(result.parameters['rangevalue'], .25 * (factor - 1 / factor))

    def test_stable_ids_subseed_and_point_reorder_preserve_parameter_plan(self):
        for host in self.hosts():
            first = program.plan_size_variance(100, host.version, observations=host.observe())
            host.points.reverse()
            second = program.plan_size_variance(100, host.version, observations=host.observe())
            self.assertEqual(first.native_seed, second.native_seed)
            self.assertEqual([(item['parm'], item['value']) for item in first.writes],
                             [(item['parm'], item['value']) for item in second.writes])
            self.assertNotEqual(first.content_sha256, second.content_sha256)
            with self.assertRaisesRegex(ValueError, 'NATIVE_CONTROL_CONTEXT_CHANGED'):
                program.validate_control_write_plan(first, host.observe())
            host.basis['task_seed'] = 38
            host.basis['content_sha256'] = program.basis_content_sha256(host.basis)
            third = program.plan_size_variance(100, host.version, observations=host.observe())
            self.assertNotEqual(second.native_seed, third.native_seed)

    def test_invalid_values_basis_and_actual_ids_refused(self):
        host = BottomHost(core.VERSIONS[0])
        for value in (True, -1, 101, float('nan'), float('inf'), 10 ** 1000, '10', 1e-20):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                program.plan_size_variance(value, host.version, observations=host.observe())
        for mutation in ('missing_basis', 'basis_digest', 'seed_bool', 'size_zero', 'duplicate_id', 'missing_id', 'id_bool', 'wrong_precision'):
            observed = host.observe()
            if mutation == 'missing_basis':
                observed.pop((program.ROLE, '@size_basis'))
            elif mutation == 'basis_digest':
                observed[program.ROLE, '@size_basis']['size'] = .5
            elif mutation in {'seed_bool', 'size_zero'}:
                basis = observed[program.ROLE, '@size_basis']
                basis['task_seed' if mutation == 'seed_bool' else 'size'] = True if mutation == 'seed_bool' else 0
                basis['content_sha256'] = program.basis_content_sha256(basis)
            else:
                attribute = observed['simulation', '@geometry/0']['point_attributes']['id']
                if mutation == 'duplicate_id': attribute['values'][1] = attribute['values'][0]
                if mutation == 'missing_id': attribute.pop('values')
                if mutation == 'id_bool': attribute['values'][0] = True
                if mutation == 'wrong_precision': attribute['precision'] = 'float32'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                program.plan_size_variance(50, host.version, observations=observed)

    def test_drivers_gates_types_native_tokens_and_representation_refused(self):
        host = BottomHost(core.VERSIONS[0])
        for field, name, replacement in (
            ('driven', 'minvalue', True), ('locked', 'randomseed', True),
            ('disabled', 'rangevalue', True), ('hidden', 'randmethod', True),
            ('type', 'randomseed', 'float'), ('size', 'minvalue', True),
            ('value', 'group', 'artist_group'), ('menu_tokens', 'randmethod', ['ppnum']),
            ('menu_uses_token_value', 'randmethod', None),
        ):
            observed = host.observe()
            observed[program.ROLE, name][field] = replacement
            with self.subTest(field=field, name=name), self.assertRaises(ValueError):
                program.plan_size_variance(50, host.version, observations=observed)
        host.parameters['randmethod'].token_value = False
        host.parameters['randmethod'].value = host.parameters['randmethod'].tokens.index('custom')
        plan = program.plan_size_variance(50, host.version, observations=host.observe())
        host.apply(plan)
        host.parameters['randmethod'].value = host.parameters['randmethod'].tokens.index('custom')
        program.validate_applied_readback(plan, host.observe())

    def test_identity_topology_basis_and_geometry_drift_rejected_before_or_after(self):
        host = BottomHost(core.VERSIONS[0])
        plan = program.plan_size_variance(50, host.version, observations=host.observe())
        host.apply(plan)
        for key, field, value in (
            ((program.ROLE, '@node'), 'task_id', 'other-task'),
            ((program.ROLE, '@node'), 'native_version', core.VERSIONS[1]),
            ((program.ROLE, '@input/0'), 'source_path', '/obj/foreign'),
            ((program.ROLE, '@node'), 'task_owned', False),
        ):
            observed = host.observe()
            observed[key][field] = value
            with self.subTest(key=key, field=field), self.assertRaises(ValueError):
                program.validate_applied_readback(plan, observed)
        host.points[0]['v'][0] += 1
        with self.assertRaisesRegex(ValueError, 'NATIVE_CONTROL_CONTEXT_CHANGED'):
            program.validate_applied_readback(plan, host.observe())

    def test_wrong_actual_readback_and_mutable_plan_tampering_rejected(self):
        host = BottomHost(core.VERSIONS[0])
        plan = program.plan_size_variance(50, host.version, observations=host.observe())
        host.apply(plan)
        host.parameters['rangevalue'].set(.5)
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PARAMETER_READBACK_MISMATCH'):
            program.validate_applied_readback(plan, host.observe())
        host.apply(plan)
        modified = copy.deepcopy(plan)
        modified.writes[-1]['value'] = .5
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
            program.validate_applied_readback(modified, host.observe())
        modified = replace(modified, content_sha256=program._digest(program._plan_body(modified)))
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
            program.validate_applied_readback(modified, host.observe())
        for alteration in ('extra_dispatch_marker', 'remove_identity_guard', 'remove_menu_guard'):
            modified = copy.deepcopy(plan)
            if alteration == 'extra_dispatch_marker':
                modified.writes[0]['value_kind'] = 'trusted_swarm_goal_channels'
            else:
                for write in modified.writes:
                    if alteration == 'remove_identity_guard':
                        write['frozen_readback_guards'] = [guard for guard in write['frozen_readback_guards']
                                                          if guard['parm'] != '@size_basis']
                    else:
                        next(guard for guard in write['frozen_readback_guards']
                             if guard['parm'] == 'valuetype').pop('menu_tokens')
            modified = replace(modified, content_sha256=program._digest(program._plan_body(modified)))
            with self.subTest(alteration=alteration), self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
                program.validate_applied_readback(modified, host.observe())
        host.parameters['randmethod'].tokens.append('different_native_entry')
        with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_NATIVE_MENU_CHANGED'):
            program.validate_applied_readback(plan, host.observe())


if __name__ == '__main__':
    unittest.main(verbosity=2)
