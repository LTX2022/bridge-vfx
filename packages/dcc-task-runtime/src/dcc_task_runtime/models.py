"""Stable, standard-library-only task data contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional


UTC = timezone.utc
MAX_FRAME_COUNT = 10_000


def _is_sha256(value: Any) -> bool:
    rendered = str(value or "").strip().lower()
    return len(rendered) == 64 and all(character in "0123456789abcdef" for character in rendered)


def validate_frame_range(
    start: int,
    end: int,
    step: int,
    name: str = "frame_range",
    *,
    max_count: Optional[int] = MAX_FRAME_COUNT,
) -> int:
    """Validate a declared frame range without allocating its frame values."""

    if start > end or step <= 0:
        raise ValueError(f"{name} must have start <= end and a positive step")
    count = ((end - start) // step) + 1
    if max_count is not None and count > max_count:
        raise ValueError(f"{name} may contain at most {max_count} frames")
    return count


class TaskState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    PREVIEWING = "PREVIEWING"
    DIAGNOSING = "DIAGNOSING"
    CANDIDATES_READY = "CANDIDATES_READY"
    AWAITING_CACHE_APPROVAL = "AWAITING_CACHE_APPROVAL"
    CACHING = "CACHING"
    VERIFYING = "VERIFYING"
    AWAITING_EXPERIENCE_APPROVAL = "AWAITING_EXPERIENCE_APPROVAL"
    COMPLETED = "COMPLETED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"
    AWAITING_INPUT = "AWAITING_INPUT"
    DIAGNOSIS_INCONCLUSIVE = "DIAGNOSIS_INCONCLUSIVE"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ErrorCode(str, Enum):
    INVALID_SPEC = "INVALID_SPEC"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    INVALID_STAGE_GRAPH = "INVALID_STAGE_GRAPH"
    UNSUPPORTED_DOMAIN = "UNSUPPORTED_DOMAIN"
    DIAGNOSIS_INCONCLUSIVE = "DIAGNOSIS_INCONCLUSIVE"
    AWAITING_INPUT = "AWAITING_INPUT"
    PARTIAL = "PARTIAL"
    POLICY_DENIED = "POLICY_DENIED"
    TRUSTED_HUMAN_REQUIRED = "TRUSTED_HUMAN_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_SCOPE_MISMATCH = "APPROVAL_SCOPE_MISMATCH"
    APPROVAL_SUBJECT_MISMATCH = "APPROVAL_SUBJECT_MISMATCH"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"
    EXPERIENCE_NOT_VERIFIED = "EXPERIENCE_NOT_VERIFIED"
    EXPERIENCE_SCOPE_MISMATCH = "EXPERIENCE_SCOPE_MISMATCH"
    MODEL_CAPABILITY_MISMATCH = "MODEL_CAPABILITY_MISMATCH"
    TOOL_BUDGET_EXCEEDED = "TOOL_BUDGET_EXCEEDED"
    IMAGE_INPUT_FORBIDDEN = "IMAGE_INPUT_FORBIDDEN"
    UNSUPPORTED_INPUT_DECODER = "UNSUPPORTED_INPUT_DECODER"
    BRIDGE_UNREACHABLE = "BRIDGE_UNREACHABLE"
    INSTANCE_NOT_FOUND = "INSTANCE_NOT_FOUND"
    RUNTIME_MISMATCH = "RUNTIME_MISMATCH"
    LICENSE_UNAVAILABLE = "LICENSE_UNAVAILABLE"
    OUTPUT_NOT_WRITABLE = "OUTPUT_NOT_WRITABLE"
    BUSY = "BUSY"
    UNSUPPORTED_NODE = "UNSUPPORTED_NODE"
    NODE_CREATE_FAILED = "NODE_CREATE_FAILED"
    COOK_FAILED = "COOK_FAILED"
    USD_EXPORT_FAILED = "USD_EXPORT_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    ARTIFACT_INVALID = "ARTIFACT_INVALID"
    VISUAL_GATE_FAILED = "VISUAL_GATE_FAILED"
    REPAIR_EXHAUSTED = "REPAIR_EXHAUSTED"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


V1_TERMINAL_STATES = frozenset({TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED})
V2_TERMINAL_STATES = frozenset(
    {
        TaskState.COMPLETED,
        TaskState.PARTIAL,
        TaskState.UNSUPPORTED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }
)
TERMINAL_STATES = V1_TERMINAL_STATES | V2_TERMINAL_STATES


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class TaskSpec:
    task_type: str
    intent: str
    target_application: str
    target_scene: str = "new"
    target_scene_path: Optional[str] = None
    inputs: tuple[dict[str, Any], ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    render: dict[str, Any] = field(default_factory=dict)
    delivery: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TaskSpec":
        task_type = str(value.get("task_type") or "").strip()
        intent = str(value.get("intent") or "").strip()
        target = value.get("target") if isinstance(value.get("target"), Mapping) else {}
        target_application = str(target.get("application") or value.get("target_application") or "").strip().lower()
        if not task_type:
            raise ValueError("task_type is required")
        if not intent:
            raise ValueError("intent is required")
        if not target_application:
            raise ValueError("target.application is required")
        expected_application = task_type.split(".", 1)[0].lower()
        if expected_application in {"houdini", "nuke"} and target_application != expected_application:
            raise ValueError(f"task_type {task_type} requires target.application={expected_application}")
        raw_inputs = value.get("inputs") or []
        if not isinstance(raw_inputs, list):
            raise ValueError("inputs must be a list")
        raw_render = dict(value.get("render") or {})
        renderer = str(raw_render.get("renderer") or "auto")
        if renderer not in {"auto", "karma_xpu", "karma_cpu"}:
            raise ValueError("render.renderer must be auto, karma_xpu, or karma_cpu")
        raw_resolution = raw_render.get("resolution") or [1280, 720]
        if not isinstance(raw_resolution, (list, tuple)) or len(raw_resolution) != 2 or any(int(item) <= 0 for item in raw_resolution):
            raise ValueError("render.resolution must be two positive integers")
        raw_range = raw_render.get("frame_range") or {"start": 1, "end": 1, "step": 1}
        if not isinstance(raw_range, Mapping):
            raise ValueError("render.frame_range must be an object")
        start = int(raw_range.get("start", 1))
        end = int(raw_range.get("end", start))
        step = int(raw_range.get("step", 1))
        # Preserve the accepted range of existing Houdini v1 recipes.  Nuke
        # recipes materialize per-frame steps and therefore enforce the
        # bounded planning contract here as well as at recipe execution.
        validate_frame_range(
            start,
            end,
            step,
            "render.frame_range",
            max_count=MAX_FRAME_COUNT if target_application == "nuke" else None,
        )
        render = {"enabled": bool(raw_render.get("enabled", True)), "renderer": renderer, "resolution": [int(raw_resolution[0]), int(raw_resolution[1])], "frame_range": {"start": start, "end": end, "step": step}, "format": str(raw_render.get("format") or "exr"), **raw_render}
        delivery = {"mode": "merge_current", **dict(value.get("delivery") or {})}
        if delivery["mode"] not in {"merge_current", "save_copy", "artifact_only"}:
            raise ValueError("delivery.mode must be merge_current, save_copy, or artifact_only")
        constraints = {"preserve_existing": True, "allow_destructive": False, **dict(value.get("constraints") or {})}
        schema_version = str(value.get("schema_version") or "1.0")
        target_scene = str(target.get("scene_mode") or value.get("target_scene") or "new")
        target_scene_path = (
            str(target.get("scene_path") or value.get("target_scene_path"))
            if target.get("scene_path") or value.get("target_scene_path")
            else None
        )
        if schema_version == "2.0":
            if target_scene not in {"current", "existing", "new", "untitled"}:
                raise ValueError("target.scene_mode must be current, existing, new, or untitled")
            if target_scene_path and not (
                "scene_mode" in target or "target_scene" in value
            ):
                raise ValueError("schema 2.0 scene_path requires an explicit target.scene_mode")
            if target_scene_path and target_scene in {"current", "existing"} and not _is_sha256(
                constraints.get("frozen_scene_sha256")
            ):
                raise ValueError(
                    "schema 2.0 existing/current scene_path requires constraints.frozen_scene_sha256"
                )
            if target_scene_path and target_scene in {"new", "untitled"}:
                raise ValueError("schema 2.0 new/untitled scene must not supply an existing scene_path")
        return cls(
            task_type=task_type,
            intent=intent,
            target_application=target_application,
            target_scene=target_scene,
            target_scene_path=target_scene_path,
            inputs=tuple(dict(item) for item in raw_inputs if isinstance(item, Mapping)),
            constraints=constraints,
            render=render,
            delivery=delivery,
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["target"] = {
            "application": result.pop("target_application"),
            "scene_mode": result.pop("target_scene"),
            "scene_path": result.pop("target_scene_path"),
        }
        result["inputs"] = list(result["inputs"])
        return result


@dataclass(frozen=True)
class TaskEvent:
    seq: int
    task_id: str
    phase: str
    step: str
    state: TaskState
    completed_units: int
    total_units: int
    percent: Optional[float]
    elapsed_ms: int
    message: str
    artifact: Optional[str] = None
    error_code: Optional[str] = None
    timestamp: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        return result


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    state: TaskState
    artifacts: tuple[dict[str, Any], ...] = ()
    gates: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    next_action: Optional[str] = None
    step_outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        result["artifacts"] = list(self.artifacts)
        result["gates"] = list(self.gates)
        result["warnings"] = list(self.warnings)
        result["step_outputs"] = {str(key): dict(value) for key, value in self.step_outputs.items()}
        return result
