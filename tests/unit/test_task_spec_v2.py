from __future__ import annotations

import unittest

from dcc_task_runtime import (
    ErrorCode,
    RuntimeV2Error,
    TaskSpec,
    TaskSpecV2,
    TaskState,
    V1_TERMINAL_STATES,
    V2_TERMINAL_STATES,
    parse_task_spec,
)


def valid_spec() -> dict:
    return {
        "schema_version": "2.0",
        "task_type": "visual.reference_rebuild",
        "intent": "match the reference smoke",
        "target": {"application": "pipeline", "scene_mode": "current"},
        "references": [
            {
                "asset_id": "reference_a",
                "kind": "image",
                "uri": "/tmp/reference.png",
                "sha256": "reference-hash",
            }
        ],
        "domains": [{"identifier": "pyro_smoke_v1", "version": "1.0.0"}],
    }


class TaskSpecV2Tests(unittest.TestCase):
    def test_strict_v2_contract_and_defaults(self) -> None:
        spec = TaskSpecV2.from_mapping(valid_spec())
        self.assertEqual(spec.target_application, "pipeline")
        self.assertEqual(spec.render["color_space"], "ACEScg")
        self.assertEqual(spec.render["resolution"], [1280, 720])
        self.assertFalse(spec.render["frame_range_explicit"])
        self.assertEqual(spec.render["fps"], 24.0)
        self.assertEqual(spec.references[0].kind.value, "image")
        self.assertEqual(len(spec.subject_hash), 64)

        explicit = valid_spec()
        explicit["render"] = {"resolution": ["1920", "1080"], "frame_range": {"start": "1", "end": "48", "step": "1"}}
        normalized = TaskSpecV2.from_mapping(explicit)
        self.assertEqual(normalized.render["resolution"], [1920, 1080])
        self.assertEqual(normalized.render["frame_range"], {"start": 1, "end": 48, "step": 1})
        self.assertTrue(normalized.render["frame_range_explicit"])

    def test_text_feedback_can_be_used_without_reference(self) -> None:
        raw = valid_spec()
        raw["references"] = []
        raw["feedback"] = "布料太硬"
        self.assertEqual(TaskSpecV2.from_mapping(raw).feedback, "布料太硬")

    def test_unknown_fields_wrong_target_and_missing_inputs_are_rejected(self) -> None:
        raw = valid_spec()
        raw["unexpected"] = True
        with self.assertRaises(RuntimeV2Error) as unknown:
            TaskSpecV2.from_mapping(raw)
        self.assertEqual(unknown.exception.code, ErrorCode.INVALID_SPEC)

        raw = valid_spec()
        raw["target"] = {"application": "houdini"}
        with self.assertRaises(RuntimeV2Error):
            TaskSpecV2.from_mapping(raw)

    def test_existing_scene_requires_frozen_hash_but_v1_and_explicit_new_remain_valid(self) -> None:
        existing = valid_spec()
        existing["target"] = {
            "application": "pipeline",
            "scene_mode": "existing",
            "scene_path": "/show/shot.hip",
        }
        with self.assertRaises(RuntimeV2Error) as caught:
            TaskSpecV2.from_mapping(existing)
        self.assertEqual(caught.exception.code, ErrorCode.AWAITING_INPUT)

        existing["constraints"] = {"frozen_scene_sha256": "a" * 64}
        self.assertEqual(
            TaskSpecV2.from_mapping(existing).target_scene_path, "/show/shot.hip"
        )

        new_scene = valid_spec()
        new_scene["target"] = {"application": "pipeline", "scene_mode": "new"}
        self.assertEqual(TaskSpecV2.from_mapping(new_scene).target_scene, "new")

        legacy = TaskSpec.from_mapping(
            {
                "task_type": "houdini.model_to_karma",
                "intent": "legacy existing scene",
                "target": {
                    "application": "houdini",
                    "scene_mode": "existing",
                    "scene_path": "/show/legacy.hip",
                },
            }
        )
        self.assertEqual(legacy.target_scene_path, "/show/legacy.hip")

        with self.assertRaisesRegex(ValueError, "frozen_scene_sha256"):
            TaskSpec.from_mapping(
                {
                    "schema_version": "2.0",
                    "task_type": "houdini.reference_effect",
                    "intent": "strict existing scene",
                    "target": {
                        "application": "houdini",
                        "scene_mode": "existing",
                        "scene_path": "/show/strict.hip",
                    },
                }
            )

        raw = valid_spec()
        raw["references"] = []
        with self.assertRaises(RuntimeV2Error):
            TaskSpecV2.from_mapping(raw)

    def test_parser_preserves_v1(self) -> None:
        parsed = parse_task_spec({"task_type": "houdini.model_to_karma", "intent": "crate", "target": {"application": "houdini"}})
        self.assertIsInstance(parsed, TaskSpec)
        parsed_v2 = parse_task_spec(valid_spec())
        self.assertIsInstance(parsed_v2, TaskSpecV2)

    def test_nuke_v1_and_v2_render_ranges_share_the_10000_frame_limit(self) -> None:
        v1 = {
            "task_type": "nuke.render_delivery",
            "intent": "render a bounded sequence",
            "target": {"application": "nuke"},
            "render": {"frame_range": {"start": 1, "end": 10_000, "step": 1}},
        }
        self.assertEqual(TaskSpec.from_mapping(v1).render["frame_range"]["end"], 10_000)
        v1["render"]["frame_range"]["end"] = 10_001
        with self.assertRaisesRegex(ValueError, "at most 10000 frames"):
            TaskSpec.from_mapping(v1)

        v2 = valid_spec()
        v2["render"] = {"frame_range": {"start": 1, "end": 10_000, "step": 1}}
        self.assertEqual(TaskSpecV2.from_mapping(v2).render["frame_range"]["end"], 10_000)
        v2["render"]["frame_range"]["end"] = 10_001
        with self.assertRaisesRegex(RuntimeV2Error, "at most 10000 frames") as oversized:
            TaskSpecV2.from_mapping(v2)
        self.assertEqual(oversized.exception.code, ErrorCode.INVALID_SPEC)

        legacy_houdini = {
            "task_type": "houdini.model_to_karma",
            "intent": "preserve an existing long v1 render contract",
            "target": {"application": "houdini"},
            "render": {"frame_range": {"start": 1, "end": 10_001, "step": 1}},
        }
        self.assertEqual(
            TaskSpec.from_mapping(legacy_houdini).render["frame_range"]["end"],
            10_001,
        )

    def test_terminal_sets_are_explicit(self) -> None:
        self.assertIn(TaskState.SUCCEEDED, V1_TERMINAL_STATES)
        self.assertIn(TaskState.COMPLETED, V2_TERMINAL_STATES)
        self.assertNotIn(TaskState.AWAITING_INPUT, V2_TERMINAL_STATES)


if __name__ == "__main__":
    unittest.main()
