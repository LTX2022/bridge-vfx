"""P02 freeze regressions using the existing explicit bottom API boundary."""
import copy
from dataclasses import replace
import unittest

from houdini_bridge import native_particle_size_program as program
from houdini_bridge import native_particle_ocean_geometry_domains as core
from test_native_particle_size_program import BottomHost


def redigest(plan):
    return replace(plan, content_sha256=program._digest(program._plan_body(plan)))


class ParticleSizeGuardTests(unittest.TestCase):
    def test_staged_menu_sequences_preserve_native_contents_and_scalar_types(self):
        for version in core.VERSIONS:
            observed = BottomHost(version).observe()
            for fact in observed.values():
                for field in ('menu_tokens', 'menu_labels'):
                    if field in fact:
                        fact[field] = tuple(fact[field])
            plan = program.plan_size_variance(50, version, observations=observed, staged=True)
            program.validate_control_write_plan(plan, observed)
            decoded = copy.deepcopy(observed)
            for fact in decoded.values():
                for field in ('menu_tokens', 'menu_labels'):
                    if field in fact:
                        fact[field] = list(fact[field])
            program.validate_control_write_plan(plan, decoded)
            for field, value, code in (
                    ('menu_tokens', ('foreign',), 'PARTICLE_SIZE_NATIVE_TOKEN_REQUIRED'),
                    ('disabled', 0, 'PARTICLE_SIZE_PARAMETER_UNAVAILABLE')):
                changed = copy.deepcopy(observed)
                changed[program.ROLE, 'valuetype'][field] = value
                with self.subTest(version=version, field=field), self.assertRaisesRegex(
                        ValueError, code):
                    program.validate_control_write_plan(plan, changed)

    def test_redigested_written_parameter_guards_cannot_replace_frozen_values(self):
        for version in core.VERSIONS:
            for after_mutation in (False, True):
                host = BottomHost(version)
                plan = program.plan_size_variance(50, version, observations=host.observe())
                changed = copy.deepcopy(plan)
                for write in changed.writes:
                    guard = next(item for item in write['frozen_readback_guards']
                                 if item['parm'] == 'minvalue')
                    guard['value'] = .875
                if after_mutation:
                    host.apply(plan)
                else:
                    host.parameters['minvalue'].set(.875)
                with self.subTest(version=version, after_mutation=after_mutation):
                    with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
                        program.validate_control_write_plan(
                            redigest(changed), host.observe(), after_mutation=after_mutation)

    def test_redigested_identity_guard_cannot_adopt_a_different_observation(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            plan = program.plan_size_variance(50, version, observations=host.observe())
            host.points[0]['v'][0] += 1
            observed = host.observe()
            changed = copy.deepcopy(plan)
            for write in changed.writes:
                guard = next(item for item in write['frozen_readback_guards']
                             if item['role'] == 'simulation' and item['parm'] == '@geometry/0')
                guard['value'] = copy.deepcopy(observed['simulation', '@geometry/0'])
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
                    program.validate_control_write_plan(redigest(changed), observed)

    def test_replacing_snapshot_and_redigest_cannot_replace_host_freeze(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            plan = program.plan_size_variance(50, version, observations=host.observe())
            changed = copy.deepcopy(plan)
            for write in changed.writes:
                guard = next(item for item in write['frozen_readback_guards']
                             if item['parm'] == 'minvalue')
                guard['value'] = .875
            snapshot = program.json.dumps(changed.writes[0]['frozen_readback_guards'],
                                          sort_keys=True, separators=(',', ':'), allow_nan=False)
            changed = redigest(replace(changed, frozen_readback_json=snapshot))
            host.parameters['minvalue'].set(.875)
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
                    program.validate_control_write_plan(changed, host.observe())

    def test_all_topology_nodes_bind_the_basis_task_and_version(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            for field, value in (('task_id', 'foreign-task'), ('task_id', None),
                                 ('native_version', core.VERSIONS[1 - core.VERSIONS.index(version)]),
                                 ('native_version', None)):
                observed = host.observe()
                observed['simulation', '@node'][field] = value
                with self.subTest(version=version, field=field, value=value):
                    with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_FROZEN_BASIS_REQUIRED'):
                        program.plan_size_variance(50, version, observations=observed)

    def test_empty_stable_id_metadata_still_requires_integer_size(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            host.points.clear()
            for value in (True, 1.0):
                observed = host.observe()
                observed['simulation', '@geometry/0']['point_attributes']['id']['size'] = value
                with self.subTest(version=version, value=value):
                    with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_STABLE_IDS_REQUIRED'):
                        program.plan_size_variance(50, version, observations=observed)

    def test_plan_seed_requires_integer_even_after_redigest(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            plan = program.plan_size_variance(50, version, observations=host.observe())
            changed = redigest(replace(plan, native_seed=float(plan.native_seed)))
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
                    program.validate_control_write_plan(changed, host.observe())

    def test_after_mutation_requires_an_explicit_boolean(self):
        host = BottomHost(core.VERSIONS[0])
        plan = program.plan_size_variance(50, host.version, observations=host.observe())
        host.apply(plan)
        for value in (1, 'false'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'PARTICLE_SIZE_PLAN_CHANGED'):
                    program.validate_control_write_plan(plan, host.observe(), after_mutation=value)

    def test_normal_feedback_and_restored_bottom_parameters_preserve_freeze(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            for percentage in (100, 0, 50):
                before = host.observe()
                plan = program.plan_size_variance(percentage, version, observations=before)
                host.apply(plan)
                result = program.validate_applied_readback(plan, host.observe())
                self.assertEqual(result.evidence_scope, 'parameters_only')
                self.assertAlmostEqual(result.observed_percentage, percentage)
                for write in plan.writes:
                    host.parameters[write['parm']].set(before[program.ROLE, write['parm']]['value'])
                self.assertEqual(host.observe(), before)
                program.validate_control_write_plan(plan, host.observe())
                host.apply(plan)

    def test_partial_bottom_write_failure_restores_original_guard_values(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            before = host.observe()
            plan = program.plan_size_variance(50, version, observations=before)
            host.parameters['valuetype'].set('rand')
            host.parameters['minvalue'].flags['locked'] = True
            with self.assertRaisesRegex(ValueError, 'bottom parameter is unavailable'):
                host.parameters['minvalue'].set(.125)
            with self.assertRaises(ValueError):
                program.validate_applied_readback(plan, host.observe())
            host.parameters['minvalue'].flags['locked'] = False
            for write in plan.writes:
                host.parameters[write['parm']].set(before[program.ROLE, write['parm']]['value'])
            self.assertEqual(host.observe(), before)
            program.validate_control_write_plan(plan, host.observe())


if __name__ == '__main__':
    unittest.main(verbosity=2)
