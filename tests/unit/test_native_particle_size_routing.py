"""P02 regressions through the existing domain plan and readback entrypoints."""
import unittest

from houdini_bridge import native_particle_ocean_geometry_domains as core
from test_native_particle_size_program import BottomHost


class ParticleSizeRoutingTests(unittest.TestCase):
    def test_control_route_accepts_actual_frozen_basis(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            writes = core.control_write_plan(core.PARTICLES, 'size_variance', 50,
                                             version, observations=host.observe())
            self.assertTrue(writes)
            self.assertEqual({write['public_control'] for write in writes}, {'size_variance'})

    def test_candidate_route_accepts_actual_frozen_basis(self):
        for version in core.VERSIONS:
            host = BottomHost(version)
            writes = core.candidate_write_plan(core.PARTICLES, {'size_variance': 100},
                                               version, observations=host.observe())
            from houdini_bridge import native_particle_size_program as program
            plan = program.plan_from_routed_writes(writes)
            self.assertEqual(next(write['value'] for write in plan.writes
                                  if write['parm'] == 'minvalue'), .125)

    def test_actual_collector_route_recovers_percentage(self):
        from test_native_particle_size_host import NativeHostFixture
        for version in core.VERSIONS:
            host = NativeHostFixture(version)
            item = host.prepared({'size_variance': 50})
            host.host.write(item, host.roles, host.pack)
            observed = host.observe()
            values = {key: fact['value'] for key, fact in observed.items() if 'value' in fact}
            percentage = core.control_readback(core.PARTICLES, 'size_variance', values,
                                               version, observations=observed)
            self.assertAlmostEqual(percentage, 50)
