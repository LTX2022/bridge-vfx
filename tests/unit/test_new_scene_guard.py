from __future__ import annotations

import unittest
from pathlib import Path

from dcc_task_runtime import TaskSpec, TaskSpecV2
from houdini_bridge.client import BridgeError
from houdini_bridge.tasks import HoudiniCommandAdapter
from nuke_bridge.tasks import NukeCommandAdapter


def _v21_spec(application: str, *, instance_identity: str | None = None) -> TaskSpecV2:
    binding = {"scene_mode": "new"}
    if instance_identity is not None:
        binding["instance_identity"] = instance_identity
    return TaskSpecV2.from_mapping(
        {
            "schema_version": "2.1",
            "task_type": "visual.reference_rebuild",
            "intent": "build an isolated scene",
            "target": {
                "application": "pipeline",
                "scenes": {application: binding},
            },
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
    )


class _HoudiniInspectClient:
    def __init__(self, info: dict) -> None:
        self.info = info
        self.calls: list[str] = []
        self.port = 8100

    def call(self, command: str, _params=None) -> dict:
        self.calls.append(command)
        if command == "scene.info":
            return dict(self.info)
        if command == "capabilities.get":
            return {"session_id": self.info.get("session_id")}
        raise AssertionError(f"mutating or unsupported command called: {command}")


class _NukeInspectClient:
    def __init__(self, info: dict) -> None:
        self.info = info
        self.calls: list[str] = []
        self.port = 59555

    def call(self, command: str, _params=None) -> dict:
        self.calls.append(command)
        if command == "script.info":
            return dict(self.info)
        if command == "capabilities.get":
            return {"session_id": self.info.get("session_id")}
        raise AssertionError(f"mutating or unsupported command called: {command}")


class NewSceneGuardTests(unittest.TestCase):
    def test_houdini_v21_dirty_current_scene_is_awaiting_input_without_open(self) -> None:
        client = _HoudiniInspectClient(
            {
                "hip_path": "/show/user-scene.hip",
                "has_unsaved_changes": True,
                "scene_graph_identity_complete": True,
                "session_id": "houdini-session-a",
            }
        )
        adapter = HoudiniCommandAdapter(client)

        with self.assertRaises(BridgeError) as caught:
            adapter._ensure_target_scene(
                _v21_spec("houdini", instance_identity="houdini-session-a"),
                "task-a",
                Path("/private/tmp/task-a"),
            )

        self.assertEqual(caught.exception.code, "AWAITING_INPUT")
        self.assertIn("clean/dirty", str(caught.exception))
        self.assertEqual(client.calls, ["scene.info"])

    def test_houdini_v21_identity_switch_is_rejected_before_any_mutation(self) -> None:
        client = _HoudiniInspectClient(
            {
                "hip_path": "",
                "has_unsaved_changes": False,
                "scene_graph_identity_complete": True,
                "session_id": "houdini-session-b",
            }
        )
        adapter = HoudiniCommandAdapter(client)

        with self.assertRaises(BridgeError) as caught:
            adapter._ensure_target_scene(
                _v21_spec("houdini", instance_identity="houdini-session-a"),
                "task-a",
                Path("/private/tmp/task-a"),
            )

        self.assertEqual(caught.exception.code, "AWAITING_INPUT")
        self.assertIn("does not match", str(caught.exception))
        self.assertEqual(client.calls, ["scene.info"])

    def test_houdini_v21_clean_untitled_scene_still_needs_isolated_creation_handshake(self) -> None:
        client = _HoudiniInspectClient(
            {
                "hip_path": "",
                "has_unsaved_changes": False,
                "scene_graph_identity_complete": True,
            }
        )
        adapter = HoudiniCommandAdapter(client)

        with self.assertRaises(BridgeError) as caught:
            adapter._ensure_target_scene(_v21_spec("houdini"), "task-a")

        self.assertEqual(caught.exception.code, "AWAITING_INPUT")
        self.assertIn("isolated blank-scene", str(caught.exception))
        self.assertEqual(client.calls, ["scene.info"])

    def test_houdini_route_identity_can_bind_host_session_id_to_client_port(self) -> None:
        client = _HoudiniInspectClient(
            {
                "hip_path": "",
                "has_unsaved_changes": False,
                "scene_graph_identity_complete": True,
                "session_id": "session-a",
            }
        )
        adapter = HoudiniCommandAdapter(client)

        with self.assertRaises(BridgeError) as caught:
            adapter._ensure_target_scene(
                _v21_spec("houdini", instance_identity="legacy-http:8100:session-a"),
                "task-a",
            )

        self.assertEqual(caught.exception.code, "AWAITING_INPUT")
        self.assertIn("isolated blank-scene", str(caught.exception))
        self.assertEqual(client.calls, ["scene.info"])

    def test_nuke_v21_dirty_current_script_is_awaiting_input_without_open(self) -> None:
        client = _NukeInspectClient(
            {
                "script": "/show/user-scene.nk",
                "modified": True,
                "scene_fingerprint": "a" * 64,
                "fingerprint_complete": True,
                "session_id": "nuke-session-a",
            }
        )
        adapter = NukeCommandAdapter(client)

        with self.assertRaisesRegex(RuntimeError, r"^AWAITING_INPUT:.*modified"):
            adapter._ensure_target_scene(
                _v21_spec("nuke", instance_identity="nuke-session-a"),
                Path("/private/tmp/task-a"),
            )

        self.assertEqual(client.calls, ["script.info"])

    def test_nuke_v21_identity_switch_is_rejected_before_any_mutation(self) -> None:
        client = _NukeInspectClient(
            {
                "script": "",
                "modified": False,
                "scene_fingerprint": "b" * 64,
                "fingerprint_complete": True,
                "session_id": "nuke-session-b",
            }
        )
        adapter = NukeCommandAdapter(client)

        with self.assertRaisesRegex(RuntimeError, r"^AWAITING_INPUT:.*does not match"):
            adapter._ensure_target_scene(
                _v21_spec("nuke", instance_identity="nuke-session-a"),
                Path("/private/tmp/task-a"),
            )

        self.assertEqual(client.calls, ["script.info"])

    def test_nuke_v21_clean_untitled_script_still_needs_isolated_creation_handshake(self) -> None:
        client = _NukeInspectClient(
            {
                "script": "",
                "modified": False,
                "scene_fingerprint": "c" * 64,
                "fingerprint_complete": True,
            }
        )
        adapter = NukeCommandAdapter(client)

        with self.assertRaisesRegex(RuntimeError, r"^AWAITING_INPUT:.*isolated blank-script"):
            adapter._ensure_target_scene(_v21_spec("nuke"), Path("/private/tmp/task-a"))

        self.assertEqual(client.calls, ["script.info"])

    def test_nuke_route_identity_can_bind_host_session_id_to_client_port(self) -> None:
        client = _NukeInspectClient(
            {
                "script": "",
                "modified": False,
                "scene_fingerprint": "d" * 64,
                "fingerprint_complete": True,
                "session_id": "session-a",
            }
        )
        adapter = NukeCommandAdapter(client)

        with self.assertRaisesRegex(RuntimeError, r"^AWAITING_INPUT:.*isolated blank-script"):
            adapter._ensure_target_scene(
                _v21_spec("nuke", instance_identity="nuke-bridge:59555:session-a"),
                Path("/private/tmp/task-a"),
            )

        self.assertEqual(client.calls, ["script.info"])

    def test_lowered_v21_binding_marker_is_guarded_without_changing_legacy_new_mode(self) -> None:
        client = _HoudiniInspectClient(
            {
                "hip_path": "/show/user-scene.hip",
                "has_unsaved_changes": True,
                "scene_graph_identity_complete": True,
            }
        )
        adapter = HoudiniCommandAdapter(client)
        lowered = TaskSpec(
            task_type="houdini.reference_effect",
            intent="guard a lowered v2.1 leg",
            target_application="houdini",
            target_scene="new",
            constraints={
                "bridge_scene_binding": {
                    "scene_mode": "new",
                }
            },
        )

        with self.assertRaises(BridgeError) as caught:
            adapter._ensure_target_scene(lowered, "task-a")

        self.assertEqual(caught.exception.code, "AWAITING_INPUT")
        self.assertEqual(client.calls, ["scene.info"])

        class NoCallClient:
            def call(self, command, _params=None):
                raise AssertionError(command)

        # A legacy v2.0 explicit-new request remains the existing authorized
        # current-scene behavior until its caller opts into the v2.1 binding.
        self.assertIsNone(
            HoudiniCommandAdapter(NoCallClient())._ensure_target_scene(
                TaskSpec(
                    task_type="houdini.reference_effect",
                    intent="legacy explicit new scene",
                    target_application="houdini",
                    target_scene="new",
                    schema_version="2.0",
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
