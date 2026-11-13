from __future__ import annotations

import copy
import hashlib
import json
import unittest

from houdini_bridge import native_flip_rbd_domains as rbd
from houdini_bridge import native_particle_ocean_geometry_domains as particles
from houdini_bridge import native_pyro_domains as pyro
from houdini_bridge.domain_packs import get_domain_pack, validate_candidate_patch
from houdini_bridge.product_composite_definitions import (
    ProductCompositeInputError,
    overlay_core_pack_dict,
    product_control_contract,
    validate_product_inputs,
)
from vfx_pipeline.service import EXPLOSION_BRANCH_CONTROL_MAP


def freeze(inputs):
    frozen = copy.deepcopy(inputs)
    frozen.pop("frozen_input_sha256", None)
    payload = json.dumps(frozen, sort_keys=True, separators=(",", ":"), allow_nan=False)
    frozen["frozen_input_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return frozen


def shell_inputs():
    return {
        "shockwave": {
            "source_reference": "owned-shell-input",
            "source_dimensions_su": [4, 4, 4], "center_su": [3, 2, 1],
            "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 2, 1, 1],
            "radius_trajectory": {
                "function_reference": "explicit-radius-function-input",
                "time_interval_seconds": [0, 2], "minimum_radius_su": 2,
            },
            "geometry_budget": 100, "estimated_geometry_elements": 64,
        },
    }


def debris_inputs():
    return {
        "debris": {
            "source_reference": "secondary-geometry-input", "source_dimensions_su": [0.1, 0.2, 0.3],
            "task_seed": 13, "control_subseed": 29, "instance_budget": 2,
            "parents": [
                {"id": "piece-a", "rest_surface_area_su2": 4, "transform_reference": "registered-parent-a"},
                {"id": "piece-b", "rest_surface_area_su2": 8, "transform_reference": "registered-parent-b"},
            ],
            "instances": [
                {"id": "chip-a", "parent_id": "piece-a", "local_anchor_su": [0, 1, 0]},
                {"id": "chip-b", "parent_id": "piece-b", "local_anchor_su": [1, 0, 0]},
            ],
        },
    }


class ProductCompositeDefinitionTests(unittest.TestCase):
    def assert_invalid(self, controls, inputs):
        with self.assertRaises(ProductCompositeInputError) as caught:
            validate_product_inputs(controls, freeze(inputs))
        self.assertEqual(caught.exception.code, "INVALID_COMPOSITE_PRODUCT_INPUT")

    def test_export_preserves_existing_controls_nodes_ranges_and_aliases(self):
        pack = get_domain_pack("explosion_composite_v1")
        exported = pack.to_dict()
        self.assertEqual(exported["nodes"], [node.to_dict() for node in pack.nodes])
        self.assertEqual(exported["connections"], pack.declared_connections())
        for original, control in zip(pack.controls, exported["controls"]):
            metadata = control.pop("product_definition")
            self.assertEqual(control.pop("product_status"), "approved")
            self.assertEqual(control, original.to_dict())
            self.assertEqual(metadata["decision_id"], "B")
            self.assertEqual(metadata["approved_sections"], [5])
            self.assertEqual(metadata["proposal_sha256"], "7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e")
            self.assertEqual(metadata["implementation_status"], "blocked")
        self.assertFalse(exported["product_input_contract"]["native_execution"])
        self.assertEqual(len(exported["controls"]), 11)

    def test_existing_routes_are_exact_and_missing_route_remains_missing(self):
        contracts = product_control_contract()
        for name, (branch, control) in EXPLOSION_BRANCH_CONTROL_MAP.items():
            self.assertEqual(contracts[name]["existing_route"], {"branch": branch, "control": control})
        self.assertIsNone(contracts["shockwave_thickness"]["existing_route"])
        self.assertEqual(contracts["comp_contrast"]["existing_route"]["operation"], "composite_patch")

    def test_inherited_contracts_and_r01_r05_semantics_in_both_versions(self):
        inheritance = {
            "fire_energy": (pyro, pyro.FIRE, "burn_rate"),
            "fire_scale": (pyro, pyro.FIRE, "fuel_rate"),
            "smoke_dissipation": (pyro, pyro.SMOKE, "dissipation"),
            "smoke_scale": (pyro, pyro.SMOKE, "density_scale"),
            "spark_rate": (particles, particles.PARTICLES, "birth_rate"),
            "debris_scale": (rbd, rbd.RBD, "fracture_scale"),
            "debris_energy": (rbd, rbd.RBD, "velocity_variance"),
        }
        for version in pyro.SUPPORTED_VERSIONS:
            contracts = product_control_contract(version)
            for name, (module, domain, control) in inheritance.items():
                self.assertEqual(contracts[name]["inherited_contract"], module.control_contract(domain, version)[control])
            self.assertEqual(contracts["debris_scale"]["unit"], "SU")
            self.assertEqual(contracts["debris_energy"]["unit"], "SU/s")
            self.assertIn("independent uniform [-1,1]", contracts["debris_energy"]["definition"])

    def test_metadata_is_detached_from_inputs_other_calls_and_twenty_definitions(self):
        expected = product_control_contract()
        actual = product_control_contract()
        actual["debris_scale"]["inherited_contract"]["product_definition"]["required_basis"].clear()
        actual["shockwave_scale"]["common_rules"].clear()
        actual["shockwave_scale"]["required_basis"].clear()
        self.assertEqual(product_control_contract(), expected)
        self.assertTrue(actual["shockwave_thickness"]["common_rules"])
        self.assertTrue(actual["shockwave_thickness"]["required_basis"])
        self.assertTrue(rbd.control_contract(rbd.RBD, "21.0.631")["fracture_scale"]["product_definition"]["required_basis"])
        original = {"id": "other", "controls": [{"id": "scale"}]}
        exported = overlay_core_pack_dict(original)
        exported["controls"][0]["id"] = "changed"
        self.assertEqual(original["controls"][0]["id"], "scale")

    def test_missing_shell_inputs_report_exact_paths(self):
        with self.assertRaises(ProductCompositeInputError) as caught:
            validate_product_inputs({"shockwave_thickness": 0}, {})
        missing = caught.exception.missing_inputs
        for path in ("shockwave.center_su", "shockwave.transform", "shockwave.source_dimensions_su",
                     "shockwave.radius_trajectory.function_reference", "shockwave.radius_trajectory.minimum_radius_su",
                     "controls.shockwave_scale", "shockwave.geometry_budget", "frozen_input_sha256"):
            self.assertIn(path, missing)
        self.assertEqual(caught.exception.code, "MISSING_COMPOSITE_PRODUCT_INPUT")

    def test_shell_surface_and_positive_inner_radius_are_product_valid_only(self):
        for version in pyro.SUPPORTED_VERSIONS:
            for thickness in (0, 3.999):
                result = validate_product_inputs({"shockwave_scale": 2, "shockwave_thickness": thickness}, freeze(shell_inputs()), version=version)
                self.assertEqual(result["product_input_status"], "validated")
                self.assertEqual(result["native_status"], "blocked")
                self.assertFalse(result["native_execution"])
                self.assertNotIn("writes", result)
                self.assertTrue(result["capture_blockers"]["shockwave_thickness"])
        for thickness in (4, 4.001, -1):
            self.assert_invalid({"shockwave_scale": 2, "shockwave_thickness": thickness}, shell_inputs())

    def test_scaled_shell_underflow_is_rejected_without_clamping(self):
        inputs = shell_inputs()
        inputs["shockwave"]["radius_trajectory"]["minimum_radius_su"] = 5e-324
        frozen = freeze(inputs)
        before = copy.deepcopy(frozen)
        controls = {"shockwave_scale": .001, "shockwave_thickness": 0}
        self.assertGreater(inputs["shockwave"]["radius_trajectory"]["minimum_radius_su"], 0)
        self.assertEqual(inputs["shockwave"]["radius_trajectory"]["minimum_radius_su"] * .001, 0)
        for version in pyro.SUPPORTED_VERSIONS:
            with self.assertRaises(ProductCompositeInputError) as caught:
                validate_product_inputs(controls, frozen, version=version)
            self.assertEqual(caught.exception.code, "INVALID_COMPOSITE_PRODUCT_INPUT")
        self.assertEqual(frozen, before)

    def test_finite_integer_transform_determinant_overflow_has_product_error(self):
        inputs = shell_inputs()
        inputs["shockwave"]["transform"] = [10 ** 300 if index % 5 == 0 else 0 for index in range(16)]
        frozen = freeze(inputs)
        before = copy.deepcopy(frozen)
        controls = {"shockwave_scale": 1, "shockwave_thickness": 0}
        for version in pyro.SUPPORTED_VERSIONS:
            with self.assertRaises(ProductCompositeInputError) as caught:
                validate_product_inputs(controls, frozen, version=version)
            self.assertEqual(caught.exception.code, "INVALID_COMPOSITE_PRODUCT_INPUT")
        self.assertEqual(frozen, before)

    def test_mixed_integer_float_transform_product_overflow_has_product_error(self):
        diagonal = [10 ** 300, 10 ** 300, 1.0, 1]
        inputs = shell_inputs()
        inputs["shockwave"]["transform"] = [diagonal[index // 5] if index % 5 == 0 else 0 for index in range(16)]
        frozen = freeze(inputs)
        before = copy.deepcopy(frozen)
        controls = {"shockwave_scale": 1, "shockwave_thickness": 0}
        for version in pyro.SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                with self.assertRaises(ProductCompositeInputError) as caught:
                    validate_product_inputs(controls, frozen, version=version)
                self.assertEqual(caught.exception.code, "INVALID_COMPOSITE_PRODUCT_INPUT")
                self.assertEqual(frozen, before)

    def test_shell_invalid_basis_and_budget_are_rejected(self):
        for field, value in (("center_su", [0, 0]), ("source_dimensions_su", [0, 1, 1]),
                             ("transform", [0] * 16), ("geometry_budget", 63),
                             ("estimated_geometry_elements", 1.2)):
            inputs = shell_inputs()
            inputs["shockwave"][field] = value
            self.assert_invalid({"shockwave_scale": 1, "shockwave_thickness": 0}, inputs)
        for field, value in (("function_reference", ""), ("minimum_radius_su", 0),
                             ("time_interval_seconds", [1, 1])):
            inputs = shell_inputs()
            inputs["shockwave"]["radius_trajectory"][field] = value
            self.assert_invalid({"shockwave_scale": 1, "shockwave_thickness": 0}, inputs)

    def test_shell_controls_require_each_other_without_default_thickness(self):
        for controls, missing in (({"shockwave_scale": 1}, "controls.shockwave_thickness"),
                                  ({"shockwave_thickness": 0}, "controls.shockwave_scale")):
            with self.assertRaises(ProductCompositeInputError) as caught:
                validate_product_inputs(controls, freeze(shell_inputs()))
            self.assertIn(missing, caught.exception.missing_inputs)

    def test_zero_debris_requires_no_generation_and_remains_native_blocked(self):
        result = validate_product_inputs({"debris_amount": 0}, {})
        self.assertEqual(result["controls"]["debris_amount"], 0)
        self.assertEqual(result["native_status"], "blocked")
        for amount in (-1, 1.0, True, 1000001, float("inf")):
            self.assert_invalid({"debris_amount": amount}, {})
        pack = get_domain_pack("explosion_composite_v1")
        self.assertEqual(validate_candidate_patch(pack, {"debris_amount": 1000000}), {"debris_amount": 1000000})

    def test_debris_exact_total_stable_id_parent_anchor_and_budget_checks(self):
        controls = {"debris_amount": 2}
        inputs = debris_inputs()
        before = copy.deepcopy(inputs)
        result = validate_product_inputs(controls, freeze(inputs))
        self.assertEqual(inputs, before)
        self.assertEqual(result["native_status"], "blocked")
        for field, value in (("instance_budget", 1), ("task_seed", 1.5),
                             ("source_dimensions_su", [1, 0, 1]), ("parents", []), ("instances", [])):
            invalid = debris_inputs()
            invalid["debris"][field] = value
            self.assert_invalid(controls, invalid)
        for field, value in (("id", "chip-a"), ("parent_id", "unknown"), ("local_anchor_su", [0, 1]), ("parent_id", [])):
            invalid = debris_inputs()
            invalid["debris"]["instances"][1][field] = value
            self.assert_invalid(controls, invalid)
        for field, value in (("id", "piece-a"), ("rest_surface_area_su2", 0), ("transform_reference", "")):
            invalid = debris_inputs()
            invalid["debris"]["parents"][1][field] = value
            self.assert_invalid(controls, invalid)

    def test_frozen_inputs_reject_tampering_and_nonfinite_values(self):
        frozen = freeze(shell_inputs())
        frozen["shockwave"]["center_su"][0] += 1
        with self.assertRaises(ProductCompositeInputError) as caught:
            validate_product_inputs({"shockwave_scale": 1, "shockwave_thickness": 0}, frozen)
        self.assertIn("frozen_input_sha256", str(caught.exception))
        frozen = freeze(shell_inputs())
        frozen["shockwave"]["center_su"][0] = float("nan")
        with self.assertRaises(ProductCompositeInputError):
            validate_product_inputs({"shockwave_scale": 1, "shockwave_thickness": 0}, frozen)

    def test_inherited_controls_require_frozen_branch_binding(self):
        for name in ("fire_energy", "fire_scale", "smoke_dissipation", "smoke_scale", "spark_rate", "debris_scale", "debris_energy"):
            with self.assertRaises(ProductCompositeInputError) as caught:
                validate_product_inputs({name: 1}, {})
            self.assertTrue(any(path.startswith("branch_bindings.") for path in caught.exception.missing_inputs))
        inputs = {"branch_bindings": {"fire": {"domain": pyro.FIRE, "task_reference": "explicit-fire-task"}}}
        result = validate_product_inputs({"fire_energy": 0}, freeze(inputs))
        self.assertEqual(result["native_status"], "blocked")
        inputs["branch_bindings"]["fire"]["domain"] = pyro.SMOKE
        self.assert_invalid({"fire_energy": 1}, inputs)

    def test_product_approval_preserves_writer_refusals_in_both_versions(self):
        for version in pyro.SUPPORTED_VERSIONS:
            get_domain_pack("explosion_composite_v1").to_dict(native_version=version)
            for name in ("fracture_scale", "velocity_variance"):
                native = rbd.control_contract(rbd.RBD, version)[name]
                with self.assertRaises(ValueError) as caught:
                    rbd.control_write_plan(rbd.RBD, name, 1, version)
                self.assertEqual(caught.exception.code, native["blocker"])
            with self.assertRaises(ValueError) as caught:
                rbd.control_write_plan(rbd.RBD, "debris_amount", 0, version)
            self.assertEqual(caught.exception.code, "UNKNOWN_NATIVE_CONTROL")
            with self.assertRaises(ValueError) as caught:
                pyro.control_write_plan(pyro.FIRE, "burn_rate", 0, version)
            self.assertEqual(caught.exception.code, "ZERO_FLAME_DEPLETION_NATIVE_TARGET_NOT_CAPTURED")

    def test_r01_product_basis_requires_positive_dimensions_volume_ids_and_budget(self):
        inputs = {
            "branch_bindings": {"rbd": {"domain": rbd.RBD, "task_reference": "rbd-task"}},
            "inherited_basis": {"debris_scale": {
                "source_dimensions_su": [3, 4, 5], "closed_source_volume_su3": 60,
                "piece_ids": ["piece-a", "piece-b"], "fragment_budget": 2,
                "estimated_fragment_count": 2, "material_reference": "material-input",
                "packing_reference": "packing-input", "constraints_reference": "constraints-input",
            }},
        }
        result = validate_product_inputs({"debris_scale": 1}, freeze(inputs))
        self.assertEqual(result["native_status"], "blocked")
        for field, value in (("source_dimensions_su", [0, 1, 1]), ("closed_source_volume_su3", 0),
                             ("piece_ids", ["piece-a", "piece-a"]), ("fragment_budget", 1),
                             ("material_reference", "")):
            invalid = copy.deepcopy(inputs)
            invalid["inherited_basis"]["debris_scale"][field] = value
            self.assert_invalid({"debris_scale": 1}, invalid)
        del inputs["inherited_basis"]["debris_scale"]["source_dimensions_su"]
        with self.assertRaises(ProductCompositeInputError) as caught:
            validate_product_inputs({"debris_scale": 1}, freeze(inputs))
        self.assertIn("inherited_basis.debris_scale.source_dimensions_su", caught.exception.missing_inputs)

    def test_r05_product_basis_preserves_explicit_velocity_identity_seed_and_time(self):
        inputs = {
            "branch_bindings": {"rbd": {"domain": rbd.RBD, "task_reference": "rbd-task"}},
            "inherited_basis": {"debris_energy": {
                "pieces": [{"id": "piece-a", "v_base_su_per_second": [1, 2, 3]}],
                "coordinate_space": "explicit-scene-space", "task_seed": 31, "control_subseed": 47,
                "activation_time_seconds": 0, "fps": 24, "time_scale": 1,
            }},
        }
        before = copy.deepcopy(inputs)
        for amplitude in (0, 1, 1000):
            result = validate_product_inputs({"debris_energy": amplitude}, freeze(inputs))
            self.assertEqual(result["native_status"], "blocked")
        self.assertEqual(inputs, before)
        for field, value in (("pieces", []), ("coordinate_space", ""), ("task_seed", 1.5),
                             ("fps", 0), ("time_scale", -1)):
            invalid = copy.deepcopy(inputs)
            invalid["inherited_basis"]["debris_energy"][field] = value
            self.assert_invalid({"debris_energy": 0}, invalid)

    def test_nuke_product_binding_does_not_claim_native_contrast_capture(self):
        result = validate_product_inputs({"comp_contrast": 0}, freeze({"composite_binding": "registered-composite-inputs"}))
        self.assertEqual(result["native_status"], "blocked")
        self.assertTrue(any("Nuke 17.0v1" in blocker for blocker in result["capture_blockers"]["comp_contrast"]))
        self.assert_invalid({"comp_contrast": 1}, {"composite_binding": ""})

    def test_unknown_versions_controls_and_malformed_values_are_rejected(self):
        with self.assertRaises(ValueError):
            product_control_contract("other-version")
        for controls in ({"unknown": 1}, {"shockwave_scale": 0}, {"debris_energy": -1},
                         {"shockwave_scale": 10 ** 10000}, {"debris_amount": False}, {}):
            self.assert_invalid(controls, {})


if __name__ == "__main__":
    unittest.main()
