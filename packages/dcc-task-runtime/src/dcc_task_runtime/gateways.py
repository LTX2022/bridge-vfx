"""Capability-probed vision and bounded single-action planner gateways."""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

from .canonical import json_value
from .contracts import ModelCapabilities, ReferenceAsset
from .errors import RuntimeV2Error
from .models import ErrorCode


class VisionGateway(Protocol):
    def probe_capabilities(self) -> ModelCapabilities:
        ...

    def analyze(self, references: Sequence[ReferenceAsset], context: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class PlannerGateway(Protocol):
    def probe_capabilities(self) -> ModelCapabilities:
        ...


class DoubaoDesktopTransport(Protocol):
    """Trusted UI driver boundary; implementations live outside the model."""

    def probe(self) -> Mapping[str, Any]:
        ...

    def exchange(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def plan(self, context: Mapping[str, Any], tools: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        ...


class JSONTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> Mapping[str, Any]:
        ...


class UrllibJSONTransport:
    """Small injectable transport that never includes authorization in errors."""

    def post_json(self, url, headers, payload, timeout):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={**dict(headers), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeV2Error(ErrorCode.BRIDGE_UNREACHABLE, f"model endpoint request failed: {type(exc).__name__}") from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "model endpoint returned a non-object response")
        return decoded

@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    model_exposed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": json_value(self.input_schema)}


@dataclass(frozen=True)
class PlannerContext:
    task_summary: Mapping[str, Any]
    vision_analysis: Mapping[str, Any]
    scene_state: Mapping[str, Any]
    policy_state: Mapping[str, Any]
    prior_action_result: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_summary": json_value(self.task_summary),
            "vision_analysis": json_value(self.vision_analysis),
            "scene_state": json_value(self.scene_state),
            "policy_state": json_value(self.policy_state),
            "prior_action_result": json_value(self.prior_action_result) if self.prior_action_result is not None else None,
        }


@dataclass(frozen=True)
class PlannerAction:
    tool: Optional[str]
    arguments: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    request_user_input: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": json_value(self.arguments),
            "reason": self.reason,
            "request_user_input": self.request_user_input,
        }


def probe_capabilities(
    gateway: VisionGateway | PlannerGateway,
    required_modalities: Sequence[str] = (),
    require_strict_json: bool = False,
    require_tool_calls: bool = False,
    require_action_contract: bool = False,
) -> ModelCapabilities:
    capabilities = gateway.probe_capabilities()
    missing = sorted(set(required_modalities) - set(capabilities.input_modalities))
    if missing:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "model lacks required input modalities", {"missing": missing})
    if require_strict_json and not capabilities.strict_json:
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "model did not prove strict JSON output support")
    if require_tool_calls and (not capabilities.tool_calls or capabilities.max_tool_calls_per_turn < 1):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "model did not prove tool-calling support")
    if require_action_contract and not (
        capabilities.action_mode in {"native_tool_call", "structured_text_mediated"}
        or (capabilities.tool_calls and capabilities.max_tool_calls_per_turn >= 1)
    ):
        raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "model did not prove a bounded action contract")
    return capabilities


class BoundedPlanner:
    """Expose a small tool set and accept at most one tool action per turn."""

    _FORBIDDEN_MEDIA_KEYS = {
        "image",
        "images",
        "image_url",
        "video",
        "videos",
        "video_url",
        "uri",
        "path",
        "bytes",
        "base64",
        "raw_media",
        "references",
    }

    def __init__(self, gateway: PlannerGateway, max_exposed_tools: int = 12) -> None:
        if max_exposed_tools <= 0:
            raise ValueError("max_exposed_tools must be positive")
        self.gateway = gateway
        self.max_exposed_tools = max_exposed_tools
        self.capabilities = probe_capabilities(
            gateway,
            required_modalities=("text",),
            require_strict_json=True,
            require_action_contract=True,
        )

    def plan(self, context: PlannerContext, tools: Sequence[ToolDescriptor]) -> PlannerAction:
        visible = tuple(tool for tool in tools if tool.model_exposed)
        if len(visible) > self.max_exposed_tools:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "too many tools were exposed to the planner", {"maximum": self.max_exposed_tools})
        names = [tool.name for tool in visible]
        if len(names) != len(set(names)):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "planner tool names must be unique")
        raw_context = {
            "task_summary": context.task_summary,
            "vision_analysis": context.vision_analysis,
            "scene_state": context.scene_state,
            "policy_state": context.policy_state,
            "prior_action_result": context.prior_action_result,
        }
        if "image" not in self.capabilities.input_modalities and self._contains_media(raw_context):
            raise RuntimeV2Error(ErrorCode.IMAGE_INPUT_FORBIDDEN, "raw image/video inputs may not be sent to a text-only planner")
        payload = context.to_dict()
        raw = self.gateway.plan(payload, [tool.to_dict() for tool in visible])
        if not isinstance(raw, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "planner response must be one strict JSON object")
        unknown = sorted(set(raw) - {"tool", "arguments", "reason", "request_user_input"})
        if unknown or "actions" in raw or "tool_calls" in raw:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "planner response violates the single-action contract", {"unknown_fields": unknown})
        tool_name = raw.get("tool")
        request_input = raw.get("request_user_input")
        if tool_name is None and not request_input:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "planner must choose one tool or request one user input")
        if tool_name is not None and request_input:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "planner may not call a tool and request input in the same turn")
        if tool_name is not None and str(tool_name) not in names:
            raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "planner selected a tool that was not exposed", {"tool": tool_name})
        arguments = raw.get("arguments") or {}
        if not isinstance(arguments, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "planner arguments must be an object")
        return PlannerAction(
            str(tool_name) if tool_name is not None else None,
            dict(arguments),
            str(raw.get("reason") or ""),
            str(request_input) if request_input else None,
        )

    @classmethod
    def _contains_media(cls, value: Any, key: Optional[str] = None) -> bool:
        if isinstance(value, (bytes, bytearray, memoryview, ReferenceAsset)):
            return True
        if key and key.casefold() in cls._FORBIDDEN_MEDIA_KEYS and value not in (None, "", [], {}, ()):
            return True
        if isinstance(value, str):
            lowered = value.strip().casefold()
            return lowered.startswith(("data:image/", "data:video/"))
        if isinstance(value, Mapping):
            return any(cls._contains_media(item, str(item_key)) for item_key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(cls._contains_media(item) for item in value)
        return False


class DeepSeekResponsesPlannerGateway:
    """Concrete Responses-style gateway with a probed, one-tool contract."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        transport: Optional[JSONTransport] = None,
        timeout: float = 30.0,
    ) -> None:
        if not str(api_key).strip():
            raise ValueError("api_key is required")
        self._api_key = str(api_key)
        self.model = str(model)
        self.base_url = str(base_url).rstrip("/")
        self.transport = transport or UrllibJSONTransport()
        self.timeout = float(timeout)
        self._capabilities: Optional[ModelCapabilities] = None

    def __repr__(self) -> str:
        return f"DeepSeekResponsesPlannerGateway(model={self.model!r}, base_url={self.base_url!r}, api_key='***')"

    def probe_capabilities(self) -> ModelCapabilities:
        if self._capabilities is not None:
            return self._capabilities
        probe_tool = {
            "name": "capability_echo",
            "description": "Return the required strict capability probe payload.",
            "input_schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        }
        response = self._post_response(
            {"probe": "Call capability_echo exactly once with ok=true."},
            (probe_tool,),
        )
        action = self._extract_action(response)
        proven = action.get("tool") == "capability_echo" and action.get("arguments") == {"ok": True}
        if not proven:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "DeepSeek endpoint did not prove strict single-tool output")
        self._capabilities = ModelCapabilities(
            "deepseek",
            self.model,
            ("text",),
            strict_json=True,
            tool_calls=True,
            max_tool_calls_per_turn=1,
            action_mode="native_tool_call",
            evidence={"probe": "responses_single_tool", "endpoint": self.base_url, "live_probe": True},
        )
        return self._capabilities

    def plan(self, context: Mapping[str, Any], tools: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        if BoundedPlanner._contains_media(context):
            raise RuntimeV2Error(ErrorCode.IMAGE_INPUT_FORBIDDEN, "DeepSeek planner accepts structured text context only")
        if not tools:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "at least one bounded tool must be exposed")
        response = self._post_response(context, tools)
        return self._extract_action(response)

    def _post_response(self, context: Mapping[str, Any], tools: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        rendered_tools = []
        for tool in tools:
            rendered_tools.append(
                {
                    "type": "function",
                    "name": str(tool["name"]),
                    "description": str(tool.get("description") or ""),
                    "parameters": json_value(tool.get("input_schema") or {"type": "object"}),
                    "strict": True,
                }
            )
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Choose exactly one provided tool. Structured context:\n" + json.dumps(json_value(context), ensure_ascii=False, sort_keys=True),
                        }
                    ],
                }
            ],
            "tools": rendered_tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
        }
        return self.transport.post_json(
            self.base_url + "/responses",
            {"Authorization": "Bearer " + self._api_key},
            payload,
            self.timeout,
        )

    @staticmethod
    def _extract_action(response: Mapping[str, Any]) -> dict[str, Any]:
        calls = []
        for item in response.get("output") or ():
            if isinstance(item, Mapping) and item.get("type") in {"function_call", "tool_call"}:
                calls.append(item)
        if len(calls) != 1:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "planner endpoint must return exactly one function call", {"count": len(calls)})
        call = calls[0]
        arguments = call.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "planner tool arguments are not strict JSON") from exc
        if not isinstance(arguments, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "planner tool arguments must be an object")
        return {"tool": str(call.get("name") or ""), "arguments": dict(arguments), "reason": "single function call"}


class DoubaoDesktopGateway:
    """Planner gateway mediated by a separately trusted Doubao desktop driver.

    The desktop route does not pretend to expose native function calling.  The
    driver presents one PromptCard, reads one strict JSON object from an
    isolated conversation, and returns that object for the same BoundedPlanner
    validation used by API providers.
    """

    REQUIRED_ROUTE_ID = "DoubaoDesktopRoute"

    def __init__(self, transport: DoubaoDesktopTransport) -> None:
        self.transport = transport
        self._capabilities: Optional[ModelCapabilities] = None

    def probe_capabilities(self) -> ModelCapabilities:
        if self._capabilities is not None:
            return self._capabilities
        probe = self.transport.probe()
        if not isinstance(probe, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "Doubao desktop probe returned a non-object")
        required = {
            "route_id",
            "bundle_id",
            "app_version",
            "executable_sha256",
            "driver_sha256",
            "ui_control_verified",
            "strict_json_verified",
            "isolated_session_verified",
        }
        missing = sorted(required - set(probe))
        if missing:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "Doubao desktop route identity is incomplete", {"missing": missing})
        if str(probe.get("route_id")) != self.REQUIRED_ROUTE_ID:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "unexpected Doubao desktop route id")
        for digest_name in ("executable_sha256", "driver_sha256"):
            digest = str(probe.get(digest_name) or "")
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, f"{digest_name} is invalid")
        if not all(probe.get(name) is True for name in ("ui_control_verified", "strict_json_verified", "isolated_session_verified")):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "Doubao UI control gate is not verified")
        modalities = ["text"]
        if probe.get("image_input_verified") is True:
            modalities.append("image")
        self._capabilities = ModelCapabilities(
            provider="doubao-desktop",
            model=str(probe.get("observed_model_label") or self.REQUIRED_ROUTE_ID),
            input_modalities=tuple(modalities),
            strict_json=True,
            tool_calls=False,
            max_tool_calls_per_turn=1,
            action_mode="structured_text_mediated",
            route_identity=dict(probe),
            evidence={
                "live_probe": True,
                "route_id": self.REQUIRED_ROUTE_ID,
                "model_revision_verified": bool(probe.get("model_revision_verified", False)),
            },
        )
        return self._capabilities

    def plan(self, context: Mapping[str, Any], tools: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        self.probe_capabilities()
        if not 1 <= len(tools) <= 4:
            raise RuntimeV2Error(ErrorCode.TOOL_BUDGET_EXCEEDED, "Doubao desktop PromptCard requires one to four actions")
        payload = {
            "schema": "bridge.skill_prompt_card/1.0",
            "route_id": self.REQUIRED_ROUTE_ID,
            "context": json_value(context),
            "actions": json_value(tools),
            "instruction": "Return one JSON object with tool, arguments, reason, and optional request_user_input.",
        }
        response = self.transport.exchange(payload)
        if not isinstance(response, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "Doubao desktop response must be one JSON object")
        return dict(response)


class OpenAICompatibleVisionGateway:
    """Configurable image/video analyzer with conservative live capability probes."""

    def __init__(
        self,
        api_key: str,
        model: str = "hy3",
        base_url: str = "http://127.0.0.1:8000/v1",
        transport: Optional[JSONTransport] = None,
        timeout: float = 60.0,
        probe_references: Sequence[ReferenceAsset] = (),
    ) -> None:
        if not str(api_key).strip():
            raise ValueError("api_key is required")
        self._api_key = str(api_key)
        self.model = str(model)
        self.base_url = str(base_url).rstrip("/")
        self.transport = transport or UrllibJSONTransport()
        self.timeout = float(timeout)
        self.probe_references = tuple(probe_references)
        self._capabilities: Optional[ModelCapabilities] = None

    def __repr__(self) -> str:
        return f"OpenAICompatibleVisionGateway(model={self.model!r}, base_url={self.base_url!r}, api_key='***')"

    def probe_capabilities(self) -> ModelCapabilities:
        if self._capabilities is not None:
            return self._capabilities
        images = [item for item in self.probe_references if item.kind.value in {"image", "mask", "depth", "plate"}]
        videos = [item for item in self.probe_references if item.kind.value == "video"]
        sequences = [item for item in self.probe_references if item.kind.value == "sequence"]
        evidence: dict[str, Any] = {"live_probe": bool(self.probe_references), "single_image": False, "multi_image": False, "video": False, "sequence": False, "strict_json": False}
        modalities = ["text"]
        strict_json_proven = False
        if images:
            result = self._analyze_request(images[:1], {"probe": "single_image"})
            evidence["single_image"] = isinstance(result, Mapping)
            strict_json_proven = strict_json_proven or evidence["single_image"]
            if evidence["single_image"]:
                modalities.append("image")
        if len(images) >= 2:
            result = self._analyze_request(images[:2], {"probe": "multi_image"})
            evidence["multi_image"] = isinstance(result, Mapping)
            strict_json_proven = strict_json_proven or evidence["multi_image"]
        if videos:
            result = self._analyze_request(videos[:1], {"probe": "video"})
            evidence["video"] = isinstance(result, Mapping)
            strict_json_proven = strict_json_proven or evidence["video"]
            if evidence["video"]:
                modalities.append("video")
        if sequences:
            result = self._analyze_request(sequences[:1], {"probe": "sequence"})
            evidence["sequence"] = isinstance(result, Mapping)
            strict_json_proven = strict_json_proven or evidence["sequence"]
            if evidence["sequence"] and "image" not in modalities:
                modalities.append("image")
        evidence["strict_json"] = strict_json_proven
        self._capabilities = ModelCapabilities(
            "openai-compatible-vision",
            self.model,
            tuple(modalities),
            strict_json=bool(evidence["strict_json"]),
            tool_calls=False,
            max_tool_calls_per_turn=0,
            evidence=evidence,
        )
        return self._capabilities

    def analyze(self, references: Sequence[ReferenceAsset], context: Mapping[str, Any]) -> Mapping[str, Any]:
        if not references:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "vision analysis requires at least one reference asset")
        capabilities = self.probe_capabilities()
        requested = {"video" if item.kind.value == "video" else "image" for item in references}
        missing = sorted(requested - set(capabilities.input_modalities))
        if missing:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision model did not prove requested media support", {"missing": missing})
        if len(references) > 1 and not bool(capabilities.evidence.get("multi_image")):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision model did not prove multi-image support")
        if any(item.kind.value == "sequence" for item in references) and not bool(capabilities.evidence.get("sequence")):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision model did not prove frozen image-sequence support")
        return self._analyze_request(references, context)

    def _analyze_request(self, references: Sequence[ReferenceAsset], context: Mapping[str, Any]) -> Mapping[str, Any]:
        content = [
            {
                "type": "text",
                "text": "Return one JSON object describing components, ROI, shape, spatial detail, material, motion clues, and confidence. Context: "
                + json.dumps(json_value(context), ensure_ascii=False, sort_keys=True),
            }
        ]
        for reference in references:
            content.extend(self._media_parts(reference))
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        response = self.transport.post_json(
            self.base_url + "/chat/completions",
            {"Authorization": "Bearer " + self._api_key},
            payload,
            self.timeout,
        )
        try:
            raw_content = response["choices"][0]["message"]["content"]
            decoded = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision endpoint did not return strict JSON content") from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision analysis must be one JSON object")
        return self._validate_vision_analysis(decoded)

    @staticmethod
    def _validate_vision_analysis(value: Mapping[str, Any]) -> dict[str, Any]:
        if set(value) != {"components", "global_observations", "confidence"}:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision analysis does not match the strict public schema")
        components = value.get("components")
        confidence = value.get("confidence")
        if not isinstance(components, list) or not isinstance(value.get("global_observations"), Mapping):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision analysis components and observations are invalid")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision analysis confidence is invalid")
        for component in components:
            if not isinstance(component, Mapping) or set(component) != {"component_id", "label", "roi", "observations", "confidence"}:
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision component does not match the strict public schema")
            roi = component.get("roi")
            component_confidence = component.get("confidence")
            if roi is not None and (not isinstance(roi, list) or len(roi) != 4 or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not 0.0 <= float(item) <= 1.0 for item in roi)):
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision component ROI is invalid")
            if not isinstance(component.get("observations"), Mapping) or isinstance(component_confidence, bool) or not isinstance(component_confidence, (int, float)) or not 0.0 <= float(component_confidence) <= 1.0:
                raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "vision component observations or confidence are invalid")
        return dict(value)

    @classmethod
    def _media_parts(cls, reference: ReferenceAsset) -> list[dict[str, Any]]:
        if reference.kind.value == "sequence":
            raw_frames = reference.metadata.get("frames")
            if not isinstance(raw_frames, (list, tuple)) or len(raw_frames) < 2:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_SPEC,
                    "sequence references require metadata.frames with at least two frozen frame URIs",
                    {"asset_id": reference.asset_id},
                )
            parts = []
            for index, frame in enumerate(raw_frames):
                uri = frame.get("uri") if isinstance(frame, Mapping) else frame
                if not isinstance(uri, str) or not uri.strip():
                    raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "every sequence frame must provide a URI", {"asset_id": reference.asset_id, "frame_index": index})
                parts.append({"type": "image_url", "image_url": {"url": cls._encode_uri(reference.asset_id, uri)}})
            return parts
        media_type = "video_url" if reference.kind.value == "video" else "image_url"
        return [{"type": media_type, media_type: {"url": cls._encode_uri(reference.asset_id, reference.uri)}}]

    @staticmethod
    def _encode_uri(asset_id: str, uri: str) -> str:
        if uri.startswith(("http://", "https://", "data:")):
            return uri
        path = Path(uri).expanduser()
        if not path.is_file():
            raise RuntimeV2Error(ErrorCode.ARTIFACT_MISSING, "vision probe media does not exist", {"asset_id": asset_id})
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
