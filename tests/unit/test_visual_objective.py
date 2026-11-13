from __future__ import annotations

import unittest

from dcc_task_runtime.errors import RuntimeV2Error
from dcc_task_runtime.models import ErrorCode
from dcc_task_runtime.visual_objective import (
    MediaAsset,
    MediaManifest,
    SemanticProvenance,
    SemanticValue,
    VisualObjective,
    validate_reference_analysis,
)


def manifest() -> MediaManifest:
    return MediaManifest(
        (
            MediaAsset(
                "reference",
                "image",
                "file:///private/reference.png",
                "a" * 64,
                width=528,
                height=960,
            ),
        )
    )


def semantic(value, provenance="observed", confidence=0.9, basis="component.smoke"):
    return SemanticValue(value, provenance, confidence, basis)


def complete_objective() -> VisualObjective:
    return VisualObjective(
        media_manifest=manifest(),
        emission_start=semantic(1, basis="component.observations.emission_start"),
        emission_end=semantic(120, basis="component.observations.emission_end"),
        direction=semantic([0.0, 1.0, 0.0], basis="component.observations.direction"),
        spread_angle=semantic(34.0, basis="component.observations.spread_angle"),
        speed_tier=semantic("fast", basis="component.observations.speed_tier"),
        body_scale=semantic(1.2, basis="component.observations.body_scale"),
        ground_spread=semantic(2.0, basis="component.observations.ground_spread"),
        protected_features=semantic(["尖刺根部", "地面轮廓"], basis="component.observations.protected_features"),
        roi=semantic([0.05, 0.1, 0.9, 0.85], basis="component.roi"),
        time_range=semantic({"start": 1, "end": 180, "step": 1}, basis="global.time_range"),
    )


def analysis(**observations):
    return {
        "components": [
            {
                "component_id": "smoke",
                "label": "smoke plume",
                "roi": [0.05, 0.1, 0.9, 0.85],
                "observations": observations,
                "confidence": 0.9,
            }
        ],
        "global_observations": {"time_range": {"start": 1, "end": 180, "step": 1}},
        "confidence": 0.95,
    }


class MediaManifestTests(unittest.TestCase):
    def test_manifest_hash_is_deterministic_and_round_trips(self):
        original = manifest()
        restored = MediaManifest.from_mapping(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(original.content_sha256, original.to_dict()["manifest_sha256"])

    def test_manifest_rejects_model_privacy_or_synthetic_claims(self):
        raw = manifest().to_dict()
        raw["assets"][0]["synthetic"] = True
        with self.assertRaises(RuntimeV2Error) as caught:
            MediaManifest.from_mapping(raw)
        self.assertEqual(caught.exception.code, ErrorCode.MODEL_CAPABILITY_MISMATCH)

    def test_manifest_requires_real_sha256_and_unique_asset_ids(self):
        with self.assertRaises(RuntimeV2Error):
            MediaAsset("reference", "image", "file:///reference.png", "not-a-sha")
        duplicate = MediaAsset("reference", "image", "file:///other.png", "b" * 64)
        with self.assertRaises(RuntimeV2Error):
            MediaManifest((manifest().assets[0], duplicate))


class ReferenceAnalysisTests(unittest.TestCase):
    def test_external_analysis_is_typed_with_exact_public_shape(self):
        typed = validate_reference_analysis(analysis(direction=[0.0, 1.0, 0.0]))
        self.assertEqual(typed.components[0].component_id, "smoke")
        self.assertEqual(typed.to_dict()["components"][0]["roi"], [0.05, 0.1, 0.9, 0.85])
        self.assertIs(validate_reference_analysis(typed), typed)

    def test_external_analysis_rejects_unknown_fields_and_privacy_self_attestation(self):
        unknown = analysis()
        unknown["extra"] = "not in the contract"
        with self.assertRaises(RuntimeV2Error):
            validate_reference_analysis(unknown)

        privacy = analysis()
        privacy["global_observations"]["input_class"] = "synthetic"
        with self.assertRaises(RuntimeV2Error) as caught:
            validate_reference_analysis(privacy)
        self.assertEqual(caught.exception.code, ErrorCode.MODEL_CAPABILITY_MISMATCH)

    def test_external_analysis_rejects_nonfinite_confidence(self):
        malformed = analysis()
        malformed["confidence"] = float("nan")
        with self.assertRaises(RuntimeV2Error):
            validate_reference_analysis(malformed)


class VisualObjectiveTests(unittest.TestCase):
    def test_typed_objective_round_trip_and_source_plan_bounds(self):
        objective = complete_objective()
        restored = VisualObjective.from_mapping(objective.to_dict())
        self.assertEqual(restored, objective)
        plan = restored.source_plan()
        self.assertTrue(plan.ready)
        self.assertEqual(plan.recipe_id, "pyro_smoke_burst_v1")
        controls = {item.name: item for item in plan.controls}
        self.assertEqual(controls["spread_angle_deg"].value, 34.0)
        self.assertEqual(controls["spread_angle_deg"].maximum, 180.0)
        self.assertEqual(controls["estimated_speed_magnitude"].provenance, SemanticProvenance.ESTIMATED)
        self.assertNotIn("script", plan.to_dict())
        self.assertNotIn("path", plan.to_dict())

    def test_old_analysis_missing_semantics_is_incomplete_and_does_not_use_feedback(self):
        old = analysis(motion_clues="unknown_from_still")
        objective = VisualObjective.from_reference_analysis(manifest(), old)
        self.assertIn("direction", objective.missing_semantics)
        self.assertIn("speed_tier", objective.missing_semantics)
        self.assertFalse(objective.is_sufficient)
        plan = objective.source_plan()
        self.assertFalse(plan.ready)
        with self.assertRaises(RuntimeV2Error) as caught:
            plan.require_ready()
        self.assertEqual(caught.exception.code, ErrorCode.AWAITING_INPUT)
        self.assertEqual(plan.defaults[0].provenance, SemanticProvenance.DEFAULT)
        self.assertNotIn("motion_clues", [item.name for item in plan.controls])

    def test_explicit_image_observations_change_the_source_plan_even_with_same_text(self):
        first = analysis(
            emission_start=1,
            emission_end=100,
            direction=[0.0, 1.0, 0.0],
            spread_angle=20.0,
            speed_tier="medium",
            body_scale=1.0,
            ground_spread=1.0,
            protected_features=["base"],
        )
        second = analysis(
            emission_start=1,
            emission_end=100,
            direction=[1.0, 0.0, 0.0],
            spread_angle=60.0,
            speed_tier="fast",
            body_scale=1.8,
            ground_spread=4.0,
            protected_features=["base"],
        )
        first_plan = VisualObjective.from_reference_analysis(manifest(), first).source_plan().to_dict()
        second_plan = VisualObjective.from_reference_analysis(manifest(), second).source_plan().to_dict()
        self.assertNotEqual(first_plan["controls"], second_plan["controls"])
        self.assertNotEqual(first_plan["objective_hash"], second_plan["objective_hash"])

    def test_missing_physics_is_default_or_unknown_never_observed(self):
        raw = analysis(
            emission_start=1,
            emission_end=100,
            direction=[0.0, 1.0, 0.0],
            spread_angle=20.0,
            speed_tier="medium",
            body_scale=1.0,
            ground_spread=1.0,
            protected_features=[],
        )
        plan = VisualObjective.from_reference_analysis(manifest(), raw).source_plan()
        self.assertTrue(all(item.provenance is not SemanticProvenance.OBSERVED for item in plan.defaults))
        estimated = next(item for item in plan.controls if item.name == "estimated_speed_magnitude")
        self.assertEqual(estimated.provenance, SemanticProvenance.ESTIMATED)
        self.assertNotIn("pulse_count", {item.name for item in plan.controls})

    def test_invalid_visual_ranges_and_untyped_raw_values_fail_closed(self):
        with self.assertRaises(RuntimeV2Error):
            VisualObjective(
                media_manifest=manifest(),
                emission_start=semantic(1),
                emission_end=semantic(2),
                direction=semantic([0.0, 0.0, 0.0]),
                spread_angle=semantic(20.0),
                speed_tier=semantic("fast"),
                body_scale=semantic(1.0),
                ground_spread=semantic(1.0),
                protected_features=semantic([]),
                roi=semantic([0.0, 0.0, 1.0, 1.0]),
                time_range=semantic({"start": 1, "end": 2, "step": 1}),
            )

        raw = complete_objective().to_dict()
        raw["spread_angle"] = 30.0
        with self.assertRaises(RuntimeV2Error):
            VisualObjective.from_mapping(raw)


if __name__ == "__main__":
    unittest.main()
