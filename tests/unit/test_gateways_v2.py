from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from dcc_task_runtime import (
    BoundedPlanner,
    DeepSeekResponsesPlannerGateway,
    DoubaoDesktopGateway,
    ErrorCode,
    ModelCapabilities,
    OpenAICompatibleVisionGateway,
    PlannerContext,
    RuntimeV2Error,
    ToolDescriptor,
    ReferenceAsset,
    ReferenceKind,
    probe_capabilities,
)


class FakePlanner:
    def __init__(self, response=None, capabilities=None):
        self.response = response or {"tool": "scene.inspect", "arguments": {}, "reason": "inspect first"}
        self.capabilities = capabilities or ModelCapabilities("deepseek", "deepseek-v4-flash", ("text",), True, True, 1)
        self.seen_context = None
        self.seen_tools = None

    def probe_capabilities(self):
        return self.capabilities

    def plan(self, context, tools):
        self.seen_context = context
        self.seen_tools = tools
        return self.response


class FakeVision:
    def probe_capabilities(self):
        return ModelCapabilities("vision-provider", "hy3", ("text", "image"), True, False, 0)


class ResponsesTransport:
    def __init__(self):
        self.requests = []

    def post_json(self, url, headers, payload, timeout):
        self.requests.append((url, headers, payload, timeout))
        name = payload["tools"][0]["name"]
        arguments = {"ok": True} if name == "capability_echo" else {}
        return {"output": [{"type": "function_call", "name": name, "arguments": arguments}]}


class VisionTransport:
    def __init__(self):
        self.requests = []

    def post_json(self, url, headers, payload, timeout):
        self.requests.append((url, headers, payload, timeout))
        content = {
            "components": [{"component_id": "fx", "label": "effect", "roi": [0.0, 0.0, 1.0, 1.0], "observations": {"detail": 0.5}, "confidence": 0.8}],
            "global_observations": {},
            "confidence": 0.8,
        }
        import json
        return {"choices": [{"message": {"content": json.dumps(content)}}]}


def context(**vision):
    return PlannerContext(
        task_summary={"intent": "match smoke"},
        vision_analysis=vision or {"components": [{"id": "smoke", "detail_score": 0.2}]},
        scene_state={"nodes": ["smoke_solver"]},
        policy_state={"phase": "ANALYZING"},
    )


def tool(name="scene.inspect"):
    return ToolDescriptor(name, "inspect structured scene state", {"type": "object", "properties": {}})


class GatewayTests(unittest.TestCase):
    def test_doubao_desktop_is_mediated_not_native_tool_calling(self) -> None:
        class Transport:
            def probe(self):
                return {
                    "route_id": "DoubaoDesktopRoute",
                    "bundle_id": "com.bot.pc.doubao",
                    "app_version": "2.27.10",
                    "executable_sha256": "a" * 64,
                    "driver_sha256": "b" * 64,
                    "ui_control_verified": True,
                    "strict_json_verified": True,
                    "isolated_session_verified": True,
                    "image_input_verified": True,
                    "observed_model_label": "豆包",
                }

            def exchange(self, payload):
                self.payload = payload
                return {"tool": "task.status", "arguments": {}, "reason": "inspect"}

        transport = Transport()
        gateway = DoubaoDesktopGateway(transport)
        capabilities = gateway.probe_capabilities()
        self.assertFalse(capabilities.tool_calls)
        self.assertEqual(capabilities.action_mode, "structured_text_mediated")
        planner = BoundedPlanner(gateway, max_exposed_tools=4)
        action = planner.plan(
            PlannerContext({}, {}, {}, {}),
            [ToolDescriptor("task.status", "status", {"type": "object"})],
        )
        self.assertEqual(action.tool, "task.status")
        self.assertEqual(transport.payload["schema"], "bridge.skill_prompt_card/1.0")

    def test_doubao_desktop_refuses_unverified_ui_or_more_than_four_actions(self) -> None:
        class Transport:
            def __init__(self, verified=True):
                self.verified = verified

            def probe(self):
                return {
                    "route_id": "DoubaoDesktopRoute",
                    "bundle_id": "com.bot.pc.doubao",
                    "app_version": "2.27.10",
                    "executable_sha256": "a" * 64,
                    "driver_sha256": "b" * 64,
                    "ui_control_verified": self.verified,
                    "strict_json_verified": True,
                    "isolated_session_verified": True,
                }

            def exchange(self, payload):
                return {"tool": "a", "arguments": {}}

        with self.assertRaises(RuntimeV2Error):
            DoubaoDesktopGateway(Transport(False)).probe_capabilities()
        gateway = DoubaoDesktopGateway(Transport(True))
        gateway.probe_capabilities()
        with self.assertRaises(RuntimeV2Error):
            gateway.plan({}, [{"name": str(index)} for index in range(5)])

    def test_text_only_planner_receives_structured_analysis_and_one_tool(self) -> None:
        gateway = FakePlanner()
        planner = BoundedPlanner(gateway)
        action = planner.plan(context(), (tool(),))
        self.assertEqual(action.tool, "scene.inspect")
        self.assertNotIn("references", gateway.seen_context)
        self.assertEqual([item["name"] for item in gateway.seen_tools], ["scene.inspect"])

    def test_raw_media_is_never_sent_to_text_only_planner(self) -> None:
        planner = BoundedPlanner(FakePlanner())
        with self.assertRaises(RuntimeV2Error) as raised:
            planner.plan(context(image_url="file:///tmp/reference.png"), (tool(),))
        self.assertEqual(raised.exception.code, ErrorCode.IMAGE_INPUT_FORBIDDEN)

    def test_unproven_json_and_tool_capabilities_are_rejected(self) -> None:
        capabilities = ModelCapabilities("deepseek", "unknown", ("text",), False, False, 0)
        with self.assertRaises(RuntimeV2Error) as raised:
            BoundedPlanner(FakePlanner(capabilities=capabilities))
        self.assertEqual(raised.exception.code, ErrorCode.MODEL_CAPABILITY_MISMATCH)

    def test_tool_budget_and_single_action_contract_are_enforced(self) -> None:
        planner = BoundedPlanner(FakePlanner(), max_exposed_tools=1)
        with self.assertRaises(RuntimeV2Error) as too_many:
            planner.plan(context(), (tool("one"), tool("two")))
        self.assertEqual(too_many.exception.code, ErrorCode.TOOL_BUDGET_EXCEEDED)

        multiple = FakePlanner({"tool_calls": [{"tool": "one"}, {"tool": "two"}]})
        with self.assertRaises(RuntimeV2Error):
            BoundedPlanner(multiple).plan(context(), (tool("one"), tool("two")))

    def test_visual_capabilities_are_probed_instead_of_inferred_from_model_name(self) -> None:
        capabilities = probe_capabilities(FakeVision(), required_modalities=("image",))
        self.assertIn("image", capabilities.input_modalities)

    def test_concrete_deepseek_gateway_probes_and_redacts_secret(self) -> None:
        transport = ResponsesTransport()
        gateway = DeepSeekResponsesPlannerGateway("super-secret", transport=transport)
        planner = BoundedPlanner(gateway)
        action = planner.plan(context(), (tool(),))
        self.assertEqual(action.tool, "scene.inspect")
        self.assertNotIn("super-secret", repr(gateway))
        self.assertTrue(all(request[0].endswith("/responses") for request in transport.requests))
        self.assertTrue(all(request[2]["parallel_tool_calls"] is False for request in transport.requests))

    def test_concrete_vision_gateway_probes_image_multi_video_and_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_a = root / "a.png"
            image_b = root / "b.png"
            video = root / "clip.mp4"
            image_a.write_bytes(b"image-a")
            image_b.write_bytes(b"image-b")
            video.write_bytes(b"video")
            references = (
                ReferenceAsset("a", ReferenceKind.IMAGE, str(image_a), "hash-a"),
                ReferenceAsset("b", ReferenceKind.IMAGE, str(image_b), "hash-b"),
                ReferenceAsset("video", ReferenceKind.VIDEO, str(video), "hash-video"),
                ReferenceAsset("sequence", ReferenceKind.SEQUENCE, "manifest://sequence", "hash-sequence", metadata={"frames": [str(image_a), str(image_b)]}),
            )
            transport = VisionTransport()
            gateway = OpenAICompatibleVisionGateway("vision-secret", transport=transport, probe_references=references)
            capabilities = gateway.probe_capabilities()
            self.assertEqual(capabilities.evidence["single_image"], True)
            self.assertEqual(capabilities.evidence["multi_image"], True)
            self.assertEqual(capabilities.evidence["video"], True)
            self.assertEqual(capabilities.evidence["sequence"], True)
            self.assertEqual(capabilities.evidence["strict_json"], True)
            analysis = gateway.analyze((references[-1],), {"task": "sequence"})
            self.assertEqual(analysis["components"][0]["component_id"], "fx")
            self.assertNotIn("vision-secret", repr(gateway))

    def test_sequence_without_frozen_frame_manifest_is_rejected(self) -> None:
        sequence = ReferenceAsset("sequence", ReferenceKind.SEQUENCE, "manifest://missing", "hash")
        gateway = OpenAICompatibleVisionGateway("key", transport=VisionTransport(), probe_references=(sequence,))
        with self.assertRaises(RuntimeV2Error) as raised:
            gateway.probe_capabilities()
        self.assertEqual(raised.exception.code, ErrorCode.INVALID_SPEC)


if __name__ == "__main__":
    unittest.main()
