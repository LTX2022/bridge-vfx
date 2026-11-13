from __future__ import annotations

import unittest

from dcc_task_runtime import ErrorCode, RuntimeV2Error, TaskSpecV2, parse_task_spec
from dcc_task_runtime.contracts import SceneBinding


def valid_v21() -> dict:
    return {
        "schema_version": "2.1",
        "task_type": "visual.reference_rebuild",
        "intent": "build an editable smoke effect",
        "target": {"application": "pipeline"},
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


class TaskSpecV21Tests(unittest.TestCase):
    def test_missing_scene_map_defaults_to_two_new_isolated_bindings(self) -> None:
        spec = TaskSpecV2.from_mapping(valid_v21())

        houdini = spec.scene_for("houdini")
        nuke = spec.scene_for("nuke")
        self.assertEqual(houdini, SceneBinding())
        self.assertEqual(nuke, SceneBinding())
        self.assertEqual(spec.to_dict()["target"]["scenes"]["houdini"]["scene_mode"], "new")
        self.assertEqual(spec.to_dict()["target"]["scenes"]["nuke"]["scene_mode"], "new")
        self.assertNotIn("scene_path", spec.to_dict()["target"])

    def test_explicit_bindings_are_independent_and_round_trip(self) -> None:
        raw = valid_v21()
        raw["target"]["scenes"] = {
            "houdini": {
                "scene_mode": "existing",
                "scene_path": "/show/smoke.HIP",
                "frozen_scene_sha256": "A" * 64,
                "instance_identity": "houdini-8100",
            },
            "nuke": {
                "scene_mode": "existing",
                "scene_path": "/show/comp.NK",
                "frozen_scene_sha256": "B" * 64,
                "instance_identity": "nuke-5653",
            },
        }

        spec = TaskSpecV2.from_mapping(raw)
        self.assertEqual(spec.scene_for("houdini").scene_path, "/show/smoke.HIP")
        self.assertEqual(spec.scene_for("houdini").frozen_scene_sha256, "a" * 64)
        self.assertEqual(spec.scene_for("houdini").instance_identity, "houdini-8100")
        self.assertEqual(spec.scene_for("nuke").scene_path, "/show/comp.NK")
        self.assertEqual(spec.scene_for("nuke").frozen_scene_sha256, "b" * 64)
        self.assertEqual(spec.scene_for("nuke").instance_identity, "nuke-5653")

        restored = TaskSpecV2.from_mapping(spec.to_dict())
        self.assertEqual(restored.scene_for("houdini"), spec.scene_for("houdini"))
        self.assertEqual(restored.scene_for("nuke"), spec.scene_for("nuke"))
        self.assertEqual(restored.to_dict()["target"], spec.to_dict()["target"])

    def test_partial_scene_map_fills_only_missing_host_with_new_binding(self) -> None:
        raw = valid_v21()
        raw["target"]["scenes"] = {
            "houdini": {
                "scene_mode": "existing",
                "scene_path": "/show/smoke.hip",
                "frozen_scene_sha256": "c" * 64,
            }
        }
        spec = TaskSpecV2.from_mapping(raw)

        self.assertEqual(spec.scene_for("houdini").scene_mode, "existing")
        self.assertEqual(spec.scene_for("houdini").scene_path, "/show/smoke.hip")
        self.assertEqual(spec.scene_for("nuke"), SceneBinding())

    def test_v20_serialization_is_unchanged_and_legacy_hip_path_is_not_sent_to_nuke(self) -> None:
        raw = {
            "schema_version": "2.0",
            "task_type": "visual.reference_rebuild",
            "intent": "preserve a legacy houdini scene",
            "target": {
                "application": "pipeline",
                "scene_mode": "existing",
                "scene_path": "/show/legacy.HIP",
            },
            "constraints": {"frozen_scene_sha256": "d" * 64},
            "feedback": "smoke",
        }
        spec = TaskSpecV2.from_mapping(raw)

        target = spec.to_dict()["target"]
        self.assertEqual(set(target), {"application", "scene_mode", "scene_path"})
        self.assertEqual(spec.scene_for("houdini").scene_path, "/show/legacy.HIP")
        self.assertEqual(spec.scene_for("houdini").frozen_scene_sha256, "d" * 64)
        self.assertEqual(spec.scene_for("nuke"), SceneBinding())

        nuke_raw = dict(raw)
        nuke_raw["target"] = {
            "application": "pipeline",
            "scene_mode": "existing",
            "scene_path": "/show/legacy.nk",
        }
        nuke_spec = TaskSpecV2.from_mapping(nuke_raw)
        self.assertEqual(nuke_spec.scene_for("nuke").scene_path, "/show/legacy.nk")
        self.assertEqual(nuke_spec.scene_for("houdini"), SceneBinding())

    def test_ambiguous_legacy_path_fails_closed_in_v21_and_getter(self) -> None:
        raw = valid_v21()
        raw["target"] = {
            "application": "pipeline",
            "scene_mode": "existing",
            "scene_path": "/show/shot.scene",
        }
        raw["constraints"] = {"frozen_scene_sha256": "e" * 64}
        with self.assertRaises(RuntimeV2Error) as caught:
            TaskSpecV2.from_mapping(raw)
        self.assertEqual(caught.exception.code, ErrorCode.AWAITING_INPUT)

        legacy = dict(raw)
        legacy["schema_version"] = "2.0"
        spec = TaskSpecV2.from_mapping(legacy)
        for application in ("houdini", "nuke"):
            with self.subTest(application=application), self.assertRaises(RuntimeV2Error) as ambiguous:
                spec.scene_for(application)
            self.assertEqual(ambiguous.exception.code, ErrorCode.AWAITING_INPUT)

    def test_binding_requires_its_own_frozen_hash_and_rejects_mixed_legacy_fields(self) -> None:
        raw = valid_v21()
        raw["target"]["scenes"] = {
            "houdini": {
                "scene_mode": "existing",
                "scene_path": "/show/smoke.hip",
            }
        }
        with self.assertRaises(RuntimeV2Error) as missing_hash:
            TaskSpecV2.from_mapping(raw)
        self.assertEqual(missing_hash.exception.code, ErrorCode.AWAITING_INPUT)

        mixed = valid_v21()
        mixed["target"] = {
            "application": "pipeline",
            "scene_mode": "current",
            "scenes": {},
        }
        with self.assertRaises(RuntimeV2Error):
            TaskSpecV2.from_mapping(mixed)

    def test_parse_task_spec_dispatches_v21_and_rejects_unknown_host_or_application(self) -> None:
        parsed = parse_task_spec(valid_v21())
        self.assertIsInstance(parsed, TaskSpecV2)
        with self.assertRaises(RuntimeV2Error):
            parsed.scene_for("pipeline")

        unknown_host = valid_v21()
        unknown_host["target"]["scenes"] = {"blender": {"scene_mode": "new"}}
        with self.assertRaises(RuntimeV2Error):
            TaskSpecV2.from_mapping(unknown_host)


if __name__ == "__main__":
    unittest.main()
