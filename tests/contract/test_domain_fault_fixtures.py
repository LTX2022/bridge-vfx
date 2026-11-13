from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DomainFaultFixtureTests(unittest.TestCase):
    def test_every_first_party_pack_has_a_causal_fixture(self) -> None:
        payload = json.loads((ROOT / "tests" / "fixtures" / "domains" / "fault-cases.json").read_text(encoding="utf-8"))
        cases = payload["cases"]
        expected = {
            "pyro_smoke_v1",
            "pyro_fire_v1",
            "particles_v1",
            "water_ocean_v1",
            "water_flip_v1",
            "crowd_agents_v1",
            "swarm_flocking_v1",
            "vellum_cloth_v1",
            "vellum_softbody_grains_v1",
            "hair_fur_v1",
            "rbd_destruction_v1",
            "procedural_geometry_v1",
            "material_lookdev_v1",
            "lighting_camera_render_v1",
            "nuke_composite_v1",
            "explosion_composite_v1",
        }
        self.assertEqual({case["pack_id"] for case in cases}, expected)
        self.assertEqual(len(cases), len(expected))
        for case in cases:
            self.assertTrue(case["feedback"].strip())
            self.assertTrue(case["expected_dimensions"])
            self.assertTrue(case["possible_stages"])
            self.assertTrue(case["protected_dimensions"])
            self.assertIn(case["cache_kind"], {"none", "houdini_simulation_cache", "component_dependent"})


if __name__ == "__main__":
    unittest.main()
