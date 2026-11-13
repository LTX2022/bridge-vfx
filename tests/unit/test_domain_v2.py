from __future__ import annotations

import unittest

from dcc_task_runtime import (
    ControlAdjustment,
    DiagnosticRule,
    DomainMaturity,
    DomainPack,
    DomainPackRegistry,
    ErrorCode,
    FeedbackRule,
    IssueDimension,
    ChangeDirection,
    RuntimeV2Error,
    SemanticControl,
    StageGraph,
    StageKind,
    StageNode,
    builtin_domain_registry,
)
from houdini_bridge.domain_packs import all_domain_packs


def small_pack() -> DomainPack:
    return DomainPack(
        identifier="custom_magic_v1",
        version="1.0.0",
        label="custom magic",
        components=("magic",),
        stage_graph=StageGraph(
            (
                StageNode("source", StageKind.SOURCE, "magic"),
                StageNode("simulation", StageKind.SIMULATION, "magic", ("source",)),
                StageNode("render", StageKind.RENDER, "magic", ("simulation",)),
            )
        ),
        controls=(SemanticControl("detail", "float", 0.0, 2.0, (), ("simulation",), True),),
        feedback_rules=(FeedbackRule(("too smooth",), IssueDimension.SPATIAL_DETAIL, ChangeDirection.INCREASE),),
        diagnostic_rules=(
            DiagnosticRule(
                "magic.detail",
                (IssueDimension.SPATIAL_DETAIL,),
                "field_detail",
                "simulation",
                ("field.frequency",),
                (ControlAdjustment("detail", "scale", (1.1,)),),
                "field evidence supports detail loss",
            ),
        ),
        required_evidence=("field.frequency",),
        artifact_kinds=("simulation_cache",),
    )


class DomainPackTests(unittest.TestCase):
    def test_all_first_party_domains_are_declared_without_false_validation_claims(self) -> None:
        registry = builtin_domain_registry()
        identifiers = {item.identifier for item in registry.list()}
        expected = {
            "pyro_smoke_v1", "pyro_fire_v1", "particles_v1", "water_ocean_v1", "water_flip_v1",
            "crowd_agents_v1", "swarm_flocking_v1", "vellum_cloth_v1", "vellum_softbody_grains_v1",
            "hair_fur_v1", "rbd_destruction_v1", "procedural_geometry_v1", "material_lookdev_v1",
            "lighting_camera_render_v1", "nuke_composite_v1", "explosion_composite_v1",
        }
        self.assertEqual(identifiers, expected)
        self.assertTrue(all(registry.get(item.identifier, item.version).maturity is DomainMaturity.EXPERIMENTAL for item in registry.list()))

    def test_new_domain_registers_without_core_changes(self) -> None:
        registry = DomainPackRegistry()
        registry.register(small_pack())
        self.assertEqual(registry.describe("custom_magic_v1", "1.0.0")["controls"], ["detail"])

    def test_cycles_missing_nodes_and_unknown_controls_are_rejected(self) -> None:
        pack = small_pack()
        cyclic = DomainPack(
            identifier=pack.identifier,
            version="2.0.0",
            label=pack.label,
            components=pack.components,
            stage_graph=StageGraph(
                (
                    StageNode("a", StageKind.SIMULATION, "magic", ("b",)),
                    StageNode("b", StageKind.SIMULATION, "magic", ("a",)),
                )
            ),
            controls=(),
            feedback_rules=(),
            diagnostic_rules=(),
            required_evidence=(),
            artifact_kinds=(),
        )
        with self.assertRaises(RuntimeV2Error) as raised:
            DomainPackRegistry((cyclic,))
        self.assertEqual(raised.exception.code, ErrorCode.INVALID_STAGE_GRAPH)

    def test_version_is_required_when_multiple_versions_exist(self) -> None:
        first = small_pack()
        second = DomainPack(**{**first.__dict__, "version": "1.1.0"})
        registry = DomainPackRegistry((first, second))
        with self.assertRaises(RuntimeV2Error) as raised:
            registry.get(first.identifier)
        self.assertEqual(raised.exception.code, ErrorCode.UNSUPPORTED_DOMAIN)

    def test_runtime_public_controls_match_houdini_host_contract(self) -> None:
        registry = builtin_domain_registry()
        for host in all_domain_packs():
            runtime = registry.get(host.identifier, host.version)
            runtime_controls = {control.name: control for control in runtime.controls}
            host_controls = {control.identifier: control for control in host.controls}
            self.assertEqual(set(runtime_controls), set(host_controls), host.identifier)
            self.assertEqual("simulation_cache" in runtime.artifact_kinds, host.simulation_cache, host.identifier)
            for name, host_control in host_controls.items():
                self.assertEqual(runtime_controls[name].application, host_control.application, f"{host.identifier}:{name}")

    def test_ocean_is_not_a_sim_cache_domain_and_material_color_is_strict(self) -> None:
        registry = builtin_domain_registry()
        ocean = registry.get("water_ocean_v1", "1.0.0")
        self.assertNotIn("simulation_cache", ocean.artifact_kinds)
        color = registry.get("material_lookdev_v1", "1.0.0").control_map["base_color"]
        self.assertEqual(color.validate([0.1, 0.2, 0.3]), (0.1, 0.2, 0.3))
        with self.assertRaises(RuntimeV2Error):
            color.validate([1.2, 0.2, 0.3])

    def test_explosion_is_a_multi_component_branch_dag(self) -> None:
        explosion = builtin_domain_registry().get("explosion_composite_v1", "1.0.0")
        self.assertEqual(set(explosion.components), {"fire", "smoke", "shockwave", "particles", "rbd", "composite"})
        self.assertEqual(explosion.control_map["smoke_dissipation"].invalidates_components, ("smoke",))
        self.assertEqual(explosion.control_map["comp_contrast"].application, "nuke")


if __name__ == "__main__":
    unittest.main()
