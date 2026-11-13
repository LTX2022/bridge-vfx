"""Strict public contracts for the Bridge Skills 2.0 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from .canonical import canonical_sha256, json_value
from .errors import RuntimeV2Error
from .models import ErrorCode, TaskSpec, now_iso, validate_frame_range


def _nonempty(value: Any, name: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"{name} is required")
    return rendered


def _strict_keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"{name} contains unknown fields", {"fields": unknown})


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"{name} must be a list")
    result = tuple(_nonempty(item, name) for item in value)
    if len(set(result)) != len(result):
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"{name} must not contain duplicates")
    return result


def _validate_v2_frame_range(start: int, end: int, step: int, name: str) -> int:
    try:
        return validate_frame_range(start, end, step, name)
    except ValueError as exc:
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, str(exc)) from exc


def _is_sha256(value: Any) -> bool:
    rendered = str(value or "").strip().lower()
    return len(rendered) == 64 and all(character in "0123456789abcdef" for character in rendered)


class ReferenceKind(str, Enum):
    IMAGE = "image"
    SEQUENCE = "sequence"
    VIDEO = "video"
    MASK = "mask"
    DEPTH = "depth"
    PLATE = "plate"


class StageKind(str, Enum):
    SOURCE = "source"
    LAYOUT = "layout"
    CONTROL = "control"
    GENERATION = "generation"
    SIMULATION = "simulation"
    SHAPING = "shaping"
    MESHING = "meshing"
    MATERIAL = "material"
    LIGHTING = "lighting"
    CAMERA = "camera"
    RENDER = "render"
    COMPOSITE = "composite"
    DELIVERY = "delivery"


class IssueDimension(str, Enum):
    MORPHOLOGY = "morphology"
    SCALE = "scale"
    DISTRIBUTION = "distribution"
    SPATIAL_DETAIL = "spatial_detail"
    MOTION = "motion"
    TIMING = "timing"
    ENERGY = "energy"
    INTERACTION = "interaction"
    MATERIAL = "material"
    LIGHTING = "lighting"
    RENDER = "render"
    COMPOSITE = "composite"
    OTHER = "other"


class ChangeDirection(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    MATCH = "match"
    PRESERVE = "preserve"
    UNKNOWN = "unknown"


class EvidenceVerdict(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    UNKNOWN = "unknown"


class ApprovalScope(str, Enum):
    HOUDINI_SIMULATION_CACHE = "houdini_simulation_cache"
    REPAIR_EXPERIENCE_PROMOTION = "repair_experience_promotion"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class ActorKind(str, Enum):
    MODEL = "model"
    SYSTEM = "system"
    TRUSTED_HUMAN = "trusted_human"


class GateKind(str, Enum):
    """The only gate kinds accepted at a strict DCC boundary.

    Operation/progress/capability records describe execution state.  Only a
    verification gate is evidence that a declared invariant was checked.
    Evidence carriers are persistence records and can never satisfy a gate
    policy by themselves.
    """

    VERIFICATION = "verification"
    OPERATION = "operation"
    PROGRESS = "progress"
    CAPABILITY = "capability"
    NOT_APPLICABLE = "not_applicable"
    EVIDENCE_CARRIER = "evidence_carrier"


@dataclass(frozen=True)
class ReferenceAsset:
    asset_id: str
    kind: ReferenceKind
    uri: str
    sha256: str
    color_space: str = "sRGB"
    frame_range: Optional[tuple[int, int, int]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty(self.asset_id, "reference.asset_id")
        _nonempty(self.uri, "reference.uri")
        _nonempty(self.sha256, "reference.sha256")
        _nonempty(self.color_space, "reference.color_space")
        if self.frame_range is not None:
            start, end, step = self.frame_range
            _validate_v2_frame_range(start, end, step, "reference.frame_range")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReferenceAsset":
        _strict_keys(value, {"asset_id", "kind", "uri", "sha256", "color_space", "frame_range", "metadata"}, "reference")
        raw_range = value.get("frame_range")
        frame_range = None
        if raw_range is not None:
            if not isinstance(raw_range, Mapping):
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "reference.frame_range must be an object")
            frame_range = (int(raw_range.get("start", 1)), int(raw_range.get("end", 1)), int(raw_range.get("step", 1)))
        try:
            kind = ReferenceKind(str(value.get("kind") or ""))
        except ValueError as exc:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "reference.kind is unsupported") from exc
        return cls(
            asset_id=_nonempty(value.get("asset_id"), "reference.asset_id"),
            kind=kind,
            uri=_nonempty(value.get("uri"), "reference.uri"),
            sha256=_nonempty(value.get("sha256"), "reference.sha256"),
            color_space=str(value.get("color_space") or "sRGB"),
            frame_range=frame_range,
            metadata=dict(value.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "asset_id": self.asset_id,
            "kind": self.kind.value,
            "uri": self.uri,
            "sha256": self.sha256,
            "color_space": self.color_space,
            "metadata": json_value(self.metadata),
        }
        if self.frame_range is not None:
            result["frame_range"] = {"start": self.frame_range[0], "end": self.frame_range[1], "step": self.frame_range[2]}
        return result


@dataclass(frozen=True)
class DomainPackRef:
    identifier: str
    version: str

    def __post_init__(self) -> None:
        _nonempty(self.identifier, "domain.identifier")
        _nonempty(self.version, "domain.version")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DomainPackRef":
        _strict_keys(value, {"identifier", "version"}, "domain")
        return cls(_nonempty(value.get("identifier"), "domain.identifier"), _nonempty(value.get("version"), "domain.version"))

    def to_dict(self) -> dict[str, str]:
        return {"identifier": self.identifier, "version": self.version}


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model: str
    input_modalities: tuple[str, ...] = ("text",)
    strict_json: bool = False
    tool_calls: bool = False
    max_tool_calls_per_turn: int = 0
    action_mode: str = "none"
    route_identity: Mapping[str, Any] = field(default_factory=dict)
    probed_at: str = field(default_factory=now_iso)
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty(self.provider, "capabilities.provider")
        _nonempty(self.model, "capabilities.model")
        allowed = {"text", "image", "video"}
        if not self.input_modalities or any(item not in allowed for item in self.input_modalities):
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "input_modalities are invalid")
        if self.max_tool_calls_per_turn < 0:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "max_tool_calls_per_turn must be non-negative")
        if self.action_mode not in {"none", "native_tool_call", "structured_text_mediated"}:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "action_mode is invalid")
        if self.action_mode == "native_tool_call" and not self.tool_calls:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "native_tool_call requires tool_calls=true")
        if self.action_mode == "structured_text_mediated" and not self.strict_json:
            raise RuntimeV2Error(ErrorCode.MODEL_CAPABILITY_MISMATCH, "structured_text_mediated requires strict_json=true")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_modalities": list(self.input_modalities),
            "strict_json": self.strict_json,
            "tool_calls": self.tool_calls,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "action_mode": self.action_mode,
            "route_identity": json_value(self.route_identity),
            "probed_at": self.probed_at,
            "evidence": json_value(self.evidence),
        }


@dataclass(frozen=True)
class Component:
    component_id: str
    domain: DomainPackRef
    label: str
    roi: Optional[tuple[float, float, float, float]] = None
    dependencies: tuple[str, ...] = ()
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _nonempty(self.component_id, "component.component_id")
        _nonempty(self.label, "component.label")
        if not 0.0 <= self.confidence <= 1.0:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "component.confidence must be between zero and one")
        if self.roi is not None and (len(self.roi) != 4 or any(item < 0.0 or item > 1.0 for item in self.roi)):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "component.roi must contain four normalized values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "domain": self.domain.to_dict(),
            "label": self.label,
            "roi": list(self.roi) if self.roi is not None else None,
            "dependencies": list(self.dependencies),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ComponentGraph:
    components: tuple[Component, ...]

    def __post_init__(self) -> None:
        identifiers = [item.component_id for item in self.components]
        if len(identifiers) != len(set(identifiers)):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "component ids must be unique")
        known = set(identifiers)
        for component in self.components:
            missing = sorted(set(component.dependencies) - known)
            if missing:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "component dependencies are missing", {"component_id": component.component_id, "missing": missing})

    def to_dict(self) -> dict[str, Any]:
        return {"components": [item.to_dict() for item in self.components]}


@dataclass(frozen=True)
class StageNode:
    node_id: str
    stage: StageKind
    component_id: str
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "stage": self.stage.value, "component_id": self.component_id, "dependencies": list(self.dependencies)}


@dataclass(frozen=True)
class StageGraph:
    nodes: tuple[StageNode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [item.to_dict() for item in self.nodes]}


@dataclass(frozen=True)
class PerceptualIssue:
    issue_id: str
    raw_feedback: str
    domain: DomainPackRef
    component_id: str
    dimension: IssueDimension
    direction: ChangeDirection
    severity: float
    confidence: float
    roi: Optional[tuple[float, float, float, float]] = None
    frame_range: Optional[tuple[int, int, int]] = None
    protected_attributes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.issue_id, "issue.issue_id")
        _nonempty(self.raw_feedback, "issue.raw_feedback")
        _nonempty(self.component_id, "issue.component_id")
        if not 0.0 <= self.severity <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "issue severity and confidence must be between zero and one")
        if self.frame_range is not None:
            _validate_v2_frame_range(*self.frame_range, "issue.frame_range")

    @property
    def signature(self) -> str:
        return canonical_sha256(
            {
                "domain": self.domain.to_dict(),
                "component_id": self.component_id,
                "dimension": self.dimension.value,
                "direction": self.direction.value,
                "protected_attributes": self.protected_attributes,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "raw_feedback": self.raw_feedback,
            "domain": self.domain.to_dict(),
            "component_id": self.component_id,
            "dimension": self.dimension.value,
            "direction": self.direction.value,
            "severity": self.severity,
            "confidence": self.confidence,
            "roi": list(self.roi) if self.roi is not None else None,
            "frame_range": list(self.frame_range) if self.frame_range is not None else None,
            "protected_attributes": list(self.protected_attributes),
            "signature": self.signature,
        }


@dataclass(frozen=True)
class EvidenceRecord:
    stage_node_id: str
    signal: str
    verdict: EvidenceVerdict
    value: Any = None
    observation: str = ""
    artifact_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_node_id": self.stage_node_id,
            "signal": self.signal,
            "verdict": self.verdict.value,
            "value": json_value(self.value),
            "observation": self.observation,
            "artifact_id": self.artifact_id,
        }


@dataclass(frozen=True)
class EvidenceBundle:
    task_id: str
    issue_id: str
    records: tuple[EvidenceRecord, ...]
    fixed_seed: int
    fixed_camera_hash: str
    fixed_frame_range: tuple[int, int, int]

    def __post_init__(self) -> None:
        _validate_v2_frame_range(*self.fixed_frame_range, "evidence.fixed_frame_range")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "issue_id": self.issue_id,
            "records": [item.to_dict() for item in self.records],
            "fixed_seed": self.fixed_seed,
            "fixed_camera_hash": self.fixed_camera_hash,
            "fixed_frame_range": list(self.fixed_frame_range),
        }


@dataclass(frozen=True)
class CauseHypothesis:
    hypothesis_id: str
    issue_id: str
    cause_family: str
    stage_node_id: str
    explanation: str
    evidence_signals: tuple[str, ...]
    confounders: tuple[str, ...]
    confidence: float
    estimated_cost: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "hypothesis confidence must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "issue_id": self.issue_id,
            "cause_family": self.cause_family,
            "stage_node_id": self.stage_node_id,
            "explanation": self.explanation,
            "evidence_signals": list(self.evidence_signals),
            "confounders": list(self.confounders),
            "confidence": self.confidence,
            "estimated_cost": self.estimated_cost,
        }


@dataclass(frozen=True)
class ParameterChange:
    control: str
    previous: Any
    proposed: Any

    def to_dict(self) -> dict[str, Any]:
        return {"control": self.control, "previous": json_value(self.previous), "proposed": json_value(self.proposed)}


@dataclass(frozen=True)
class CandidatePatch:
    candidate_id: str
    issue_id: str
    hypothesis_id: str
    cause_family: str
    changes: tuple[ParameterChange, ...]
    affected_stage_nodes: tuple[str, ...]
    invalidates_components: tuple[str, ...]
    fixed_seed: int
    estimated_cost: str
    risk: str
    preview_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.changes or len(self.changes) > 5:
            raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "a candidate must contain between one and five public control changes")
        controls = [item.control for item in self.changes]
        if len(controls) != len(set(controls)):
            raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "a candidate may change each public control once")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "issue_id": self.issue_id,
            "hypothesis_id": self.hypothesis_id,
            "cause_family": self.cause_family,
            "changes": [item.to_dict() for item in self.changes],
            "affected_stage_nodes": list(self.affected_stage_nodes),
            "invalidates_components": list(self.invalidates_components),
            "fixed_seed": self.fixed_seed,
            "estimated_cost": self.estimated_cost,
            "risk": self.risk,
            "preview_artifact_ids": list(self.preview_artifact_ids),
        }


@dataclass(frozen=True)
class VisualScorecard:
    issue_id: str
    candidate_id: str
    before: Mapping[str, float]
    after: Mapping[str, float]
    target_improved: bool
    protected_regressions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.target_improved and not self.protected_regressions

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "candidate_id": self.candidate_id,
            "before": dict(self.before),
            "after": dict(self.after),
            "target_improved": self.target_improved,
            "protected_regressions": list(self.protected_regressions),
            "notes": list(self.notes),
            "verified": self.verified,
        }


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    task_id: str
    kind: str
    uri: str
    sha256: str
    domain: Optional[DomainPackRef]
    component_id: Optional[str]
    stage_node_id: str
    dependencies: tuple[str, ...] = ()
    reference_asset: bool = False
    final_delivery: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "kind": self.kind,
            "uri": self.uri,
            "sha256": self.sha256,
            "domain": self.domain.to_dict() if self.domain else None,
            "component_id": self.component_id,
            "stage_node_id": self.stage_node_id,
            "dependencies": list(self.dependencies),
            "reference_asset": self.reference_asset,
            "final_delivery": self.final_delivery,
            "metadata": json_value(self.metadata),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    task_id: str
    scope: ApprovalScope
    subject_hash: str
    subject: Mapping[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "scope": self.scope.value,
            "subject_hash": self.subject_hash,
            "subject": json_value(self.subject),
            "status": self.status.value,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ApprovalGrant:
    grant_id: str
    request_id: str
    task_id: str
    scope: ApprovalScope
    subject_hash: str
    principal_id: str
    status: ApprovalStatus = ApprovalStatus.GRANTED
    granted_at: str = field(default_factory=now_iso)
    revoked_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "scope": self.scope.value,
            "subject_hash": self.subject_hash,
            "principal_id": self.principal_id,
            "status": self.status.value,
            "granted_at": self.granted_at,
            "revoked_at": self.revoked_at,
        }


@dataclass(frozen=True)
class RepairExperience:
    experience_id: str
    task_id: str
    domain: DomainPackRef
    raw_feedback: str
    issue: PerceptualIssue
    hypothesis: CauseHypothesis
    candidate: CandidatePatch
    scorecard: VisualScorecard
    context: Mapping[str, Any]
    verified_result_hash: str
    user_confirmed: bool
    created_at: str = field(default_factory=now_iso)

    @property
    def verified(self) -> bool:
        """Technical verification only; human acceptance is stored by ApprovalService."""
        return self.scorecard.verified

    @property
    def repair_case_hash(self) -> str:
        return canonical_sha256(
            {
                "task_id": self.task_id,
                "domain": self.domain.to_dict(),
                "issue": self.issue.to_dict(),
                "hypothesis": self.hypothesis.to_dict(),
                "candidate": self.candidate.to_dict(),
                "scorecard": self.scorecard.to_dict(),
                "context": self.context,
                "verified_result_hash": self.verified_result_hash,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "task_id": self.task_id,
            "domain": self.domain.to_dict(),
            "raw_feedback": self.raw_feedback,
            "issue": self.issue.to_dict(),
            "hypothesis": self.hypothesis.to_dict(),
            "candidate": self.candidate.to_dict(),
            "scorecard": self.scorecard.to_dict(),
            "context": json_value(self.context),
            "verified_result_hash": self.verified_result_hash,
            "user_confirmed": self.user_confirmed,
            "verified": self.verified,
            "repair_case_hash": self.repair_case_hash,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ExperienceMatch:
    experience_id: str
    domain: DomainPackRef
    issue_signature: str
    cause_family: str
    score: float
    experience: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "domain": self.domain.to_dict(),
            "issue_signature": self.issue_signature,
            "cause_family": self.cause_family,
            "score": self.score,
            "experience": json_value(self.experience),
        }


SCENE_APPLICATIONS = ("houdini", "nuke")
SCENE_MODES = frozenset({"current", "existing", "new", "untitled"})
_HOUDINI_SCENE_SUFFIXES = frozenset({".hip", ".hiplc", ".hipnc"})
_NUKE_SCENE_SUFFIXES = frozenset({".nk", ".nkp"})


def _legacy_scene_application(scene_path: str) -> Optional[str]:
    """Map an unqualified legacy scene path only when its suffix is decisive."""

    filename = str(scene_path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if any(filename.endswith(suffix) for suffix in _HOUDINI_SCENE_SUFFIXES):
        return "houdini"
    if any(filename.endswith(suffix) for suffix in _NUKE_SCENE_SUFFIXES):
        return "nuke"
    return None


@dataclass(frozen=True)
class SceneBinding:
    """One independently addressable Houdini or Nuke scene target.

    A binding owns its scene identity. In particular, a frozen hash is never
    borrowed from the other DCC host. TaskSpecV2.scene_for is the stable
    lookup surface used by host-specific adapters.
    """

    scene_mode: str = "new"
    scene_path: Optional[str] = None
    frozen_scene_sha256: Optional[str] = None
    instance_identity: Optional[str] = None

    def __post_init__(self) -> None:
        mode = str(self.scene_mode or "").strip().lower()
        if mode not in SCENE_MODES:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "scene_mode must be current, existing, new, or untitled",
            )
        object.__setattr__(self, "scene_mode", mode)

        path: Optional[str]
        if self.scene_path is None or str(self.scene_path).strip() == "":
            path = None
        elif isinstance(self.scene_path, str):
            path = self.scene_path
        else:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "scene_path must be a string or null")
        object.__setattr__(self, "scene_path", path)

        frozen: Optional[str]
        if self.frozen_scene_sha256 is None or str(self.frozen_scene_sha256).strip() == "":
            frozen = None
        else:
            frozen = str(self.frozen_scene_sha256).strip().lower()
            if not _is_sha256(frozen):
                raise RuntimeV2Error(
                    ErrorCode.AWAITING_INPUT,
                    "scene binding requires a 64-character frozen_scene_sha256",
                )
        object.__setattr__(self, "frozen_scene_sha256", frozen)

        identity: Optional[str]
        if self.instance_identity is None or str(self.instance_identity).strip() == "":
            identity = None
        elif isinstance(self.instance_identity, str):
            identity = self.instance_identity.strip()
        else:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "instance_identity must be a string or null")
        object.__setattr__(self, "instance_identity", identity)

        if path and mode in {"new", "untitled"}:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "new/untitled scene binding must not supply an existing scene_path",
            )
        if frozen and mode in {"new", "untitled"}:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "new/untitled scene binding must not supply frozen_scene_sha256",
            )
        if path and mode in {"current", "existing"} and not frozen:
            raise RuntimeV2Error(
                ErrorCode.AWAITING_INPUT,
                "current/existing scene binding with scene_path requires frozen_scene_sha256",
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], application: str) -> "SceneBinding":
        if not isinstance(value, Mapping):
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                f"target.scenes.{application} must be an object",
            )
        _strict_keys(
            value,
            {"scene_mode", "scene_path", "frozen_scene_sha256", "instance_identity"},
            f"target.scenes.{application}",
        )
        if value.get("scene_path") and "scene_mode" not in value:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                f"target.scenes.{application}.scene_path requires an explicit scene_mode",
            )
        return cls(
            scene_mode=str(value.get("scene_mode") or "new"),
            scene_path=str(value.get("scene_path")) if value.get("scene_path") else None,
            frozen_scene_sha256=(
                str(value.get("frozen_scene_sha256"))
                if value.get("frozen_scene_sha256")
                else None
            ),
            instance_identity=(
                str(value.get("instance_identity"))
                if value.get("instance_identity")
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_mode": self.scene_mode,
            "scene_path": self.scene_path,
            "frozen_scene_sha256": self.frozen_scene_sha256,
            "instance_identity": self.instance_identity,
        }


@dataclass(frozen=True)
class TaskSpecV2:
    intent: str
    references: tuple[ReferenceAsset, ...] = ()
    feedback: str = ""
    domains: tuple[DomainPackRef, ...] = ()
    inputs: tuple[Mapping[str, Any], ...] = ()
    target_scene: str = "current"
    target_scene_path: Optional[str] = None
    constraints: Mapping[str, Any] = field(default_factory=dict)
    render: Mapping[str, Any] = field(default_factory=dict)
    delivery: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    task_type: str = "visual.reference_rebuild"
    target_application: str = "pipeline"
    schema_version: str = "2.0"
    scene_bindings: Mapping[str, SceneBinding] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty(self.intent, "intent")
        if self.schema_version not in {"2.0", "2.1"}:
            raise RuntimeV2Error(
                ErrorCode.SCHEMA_VERSION_UNSUPPORTED,
                "TaskSpecV2 requires schema_version=2.0 or 2.1",
            )
        if self.task_type != "visual.reference_rebuild":
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "TaskSpecV2 requires task_type=visual.reference_rebuild")
        if self.target_application != "pipeline":
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "TaskSpecV2 requires target.application=pipeline")
        if not self.references and not self.feedback.strip():
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "at least one reference asset or textual feedback is required")
        if self.target_scene not in SCENE_MODES:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "target.scene_mode must be current, existing, new, or untitled",
            )
        if self.schema_version == "2.0":
            if self.target_scene_path and self.target_scene in {"current", "existing"} and not _is_sha256(
                (self.constraints or {}).get("frozen_scene_sha256")
            ):
                raise RuntimeV2Error(
                    ErrorCode.AWAITING_INPUT,
                    "existing/current target.scene_path requires constraints.frozen_scene_sha256",
                )
            if self.target_scene_path and self.target_scene in {"new", "untitled"}:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_SPEC,
                    "new/untitled target scene must not supply an existing scene_path",
                )
        raw_bindings = self.scene_bindings or {}
        if not isinstance(raw_bindings, Mapping):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "scene_bindings must be a mapping")
        normalized_bindings: dict[str, SceneBinding] = {}
        for application, binding in raw_bindings.items():
            if application not in SCENE_APPLICATIONS:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_SPEC,
                    "scene_bindings may only contain houdini and nuke",
                    {"application": str(application)},
                )
            if isinstance(binding, SceneBinding):
                normalized_bindings[application] = binding
            elif isinstance(binding, Mapping):
                normalized_bindings[application] = SceneBinding.from_mapping(binding, application)
            else:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_SPEC,
                    f"scene_bindings.{application} must be a SceneBinding",
                )
        if self.schema_version == "2.1":
            if self.target_scene_path:
                legacy_application = _legacy_scene_application(self.target_scene_path)
                if legacy_application is None:
                    raise RuntimeV2Error(
                        ErrorCode.AWAITING_INPUT,
                        "legacy scene_path suffix is ambiguous; provide target.scenes.houdini and target.scenes.nuke",
                    )
                if normalized_bindings:
                    existing = normalized_bindings.get(legacy_application)
                    if existing is None or existing.scene_path != self.target_scene_path:
                        raise RuntimeV2Error(
                            ErrorCode.INVALID_SPEC,
                            "schema 2.1 legacy scene_path conflicts with target.scenes",
                        )
                else:
                    normalized_bindings[legacy_application] = SceneBinding(
                        scene_mode=self.target_scene,
                        scene_path=self.target_scene_path,
                        frozen_scene_sha256=(self.constraints or {}).get("frozen_scene_sha256"),
                    )
            for application in SCENE_APPLICATIONS:
                normalized_bindings.setdefault(application, SceneBinding())
        object.__setattr__(self, "scene_bindings", dict(sorted(normalized_bindings.items())))
        raw_frame_range = (self.render or {}).get("frame_range") or {"start": 1, "end": 1, "step": 1}
        if not isinstance(raw_frame_range, Mapping):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "render.frame_range must be an object")
        _validate_v2_frame_range(
            int(raw_frame_range.get("start", 1)),
            int(raw_frame_range.get("end", raw_frame_range.get("start", 1))),
            int(raw_frame_range.get("step", 1)),
            "render.frame_range",
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TaskSpecV2":
        allowed = {
            "schema_version",
            "task_type",
            "intent",
            "target",
            "inputs",
            "references",
            "domains",
            "feedback",
            "constraints",
            "render",
            "delivery",
            "metadata",
            "idempotency_key",
        }
        _strict_keys(value, allowed, "TaskSpecV2")
        schema_version = str(value.get("schema_version") or "")
        if schema_version not in {"2.0", "2.1"}:
            raise RuntimeV2Error(
                ErrorCode.SCHEMA_VERSION_UNSUPPORTED,
                "TaskSpecV2 requires schema_version=2.0 or 2.1",
            )
        raw_target = value.get("target")
        if not isinstance(raw_target, Mapping):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "target must be an object")
        target_keys = {"application", "scene_mode", "scene_path"}
        if schema_version == "2.1":
            target_keys.add("scenes")
        _strict_keys(raw_target, target_keys, "target")
        if raw_target.get("scene_path") and "scene_mode" not in raw_target:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                f"schema {schema_version} scene_path requires an explicit target.scene_mode",
            )
        raw_constraints = dict(value.get("constraints") or {})
        target_scene = str(raw_target.get("scene_mode") or ("new" if schema_version == "2.1" else "current"))
        target_scene_path = str(raw_target.get("scene_path")) if raw_target.get("scene_path") else None
        scene_bindings: dict[str, SceneBinding] = {}
        if schema_version == "2.1":
            if "scenes" in raw_target:
                if "scene_mode" in raw_target or "scene_path" in raw_target:
                    raise RuntimeV2Error(
                        ErrorCode.INVALID_SPEC,
                        "schema 2.1 target.scenes cannot be combined with legacy scene_mode or scene_path",
                    )
                raw_scenes = raw_target.get("scenes")
                if not isinstance(raw_scenes, Mapping):
                    raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "target.scenes must be an object")
                _strict_keys(raw_scenes, set(SCENE_APPLICATIONS), "target.scenes")
                for application in SCENE_APPLICATIONS:
                    if application in raw_scenes:
                        scene_bindings[application] = SceneBinding.from_mapping(
                            raw_scenes[application],
                            application,
                        )
            elif target_scene_path:
                application = _legacy_scene_application(target_scene_path)
                if application is None:
                    raise RuntimeV2Error(
                        ErrorCode.AWAITING_INPUT,
                        "legacy scene_path suffix is ambiguous; provide target.scenes.houdini and target.scenes.nuke",
                    )
                scene_bindings[application] = SceneBinding(
                    scene_mode=target_scene,
                    scene_path=target_scene_path,
                    frozen_scene_sha256=raw_constraints.get("frozen_scene_sha256"),
                )
            elif "scene_mode" in raw_target:
                scene_bindings = {
                    application: SceneBinding(scene_mode=target_scene)
                    for application in SCENE_APPLICATIONS
                }
        raw_references = value.get("references") or []
        raw_domains = value.get("domains") or []
        raw_inputs = value.get("inputs") or []
        if not isinstance(raw_references, list) or not isinstance(raw_domains, list) or not isinstance(raw_inputs, list):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "references, domains, and inputs must be lists")
        references = tuple(ReferenceAsset.from_mapping(item) for item in raw_references if isinstance(item, Mapping))
        if len(references) != len(raw_references):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "every reference must be an object")
        domains = tuple(DomainPackRef.from_mapping(item) for item in raw_domains if isinstance(item, Mapping))
        if len(domains) != len(raw_domains):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "every domain must be an object")
        inputs = tuple(dict(item) for item in raw_inputs if isinstance(item, Mapping))
        if len(inputs) != len(raw_inputs):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "every input must be an object")
        raw_render = dict(value.get("render") or {})
        resolution = raw_render.get("resolution") or [1280, 720]
        if not isinstance(resolution, (list, tuple)) or len(resolution) != 2 or any(int(item) <= 0 for item in resolution):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "render.resolution must contain two positive integers")
        raw_frame_range = raw_render.get("frame_range") or {"start": 1, "end": 1, "step": 1}
        if not isinstance(raw_frame_range, Mapping):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "render.frame_range must be an object")
        start, end, step = int(raw_frame_range.get("start", 1)), int(raw_frame_range.get("end", 1)), int(raw_frame_range.get("step", 1))
        _validate_v2_frame_range(start, end, step, "render.frame_range")
        fps = float(raw_render.get("fps") or 24.0)
        if not math.isfinite(fps) or fps <= 0.0:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "render.fps must be a positive finite number")
        render = {
            **raw_render,
            "resolution": [int(resolution[0]), int(resolution[1])],
            "frame_range": {"start": start, "end": end, "step": step},
            "frame_range_explicit": "frame_range" in raw_render,
            "fps": fps,
            "color_space": str(raw_render.get("color_space") or "ACEScg"),
        }
        return cls(
            intent=_nonempty(value.get("intent"), "intent"),
            references=references,
            feedback=str(value.get("feedback") or ""),
            domains=domains,
            inputs=inputs,
            target_scene=target_scene,
            target_scene_path=target_scene_path if schema_version == "2.0" else None,
            constraints={"preserve_existing": True, "allow_arbitrary_code": False, **raw_constraints},
            render=render,
            delivery={"mode": "merge_current", **dict(value.get("delivery") or {})},
            metadata=dict(value.get("metadata") or {}),
            idempotency_key=str(value.get("idempotency_key")) if value.get("idempotency_key") else None,
            task_type=str(value.get("task_type") or ""),
            target_application=str(raw_target.get("application") or "").lower(),
            schema_version=schema_version,
            scene_bindings=scene_bindings,
        )

    @property
    def subject_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def scene_for(self, application: str) -> SceneBinding:
        """Return the host-specific scene binding without cross-DCC fallback."""

        host = str(application or "").strip().lower()
        if host not in SCENE_APPLICATIONS:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "scene_for application must be houdini or nuke",
            )
        if self.schema_version == "2.1":
            return self.scene_bindings[host]

        if self.target_scene_path:
            owner = _legacy_scene_application(self.target_scene_path)
            if owner is None:
                raise RuntimeV2Error(
                    ErrorCode.AWAITING_INPUT,
                    "legacy scene_path suffix is ambiguous; provide per-host scene bindings",
                )
            if owner == host:
                return SceneBinding(
                    scene_mode=self.target_scene,
                    scene_path=self.target_scene_path,
                    frozen_scene_sha256=(self.constraints or {}).get("frozen_scene_sha256"),
                )
            return SceneBinding()
        return SceneBinding(scene_mode=self.target_scene)

    def to_dict(self) -> dict[str, Any]:
        if self.schema_version == "2.1":
            target = {
                "application": self.target_application,
                "scenes": {
                    application: self.scene_bindings[application].to_dict()
                    for application in SCENE_APPLICATIONS
                },
            }
        else:
            target = {
                "application": self.target_application,
                "scene_mode": self.target_scene,
                "scene_path": self.target_scene_path,
            }
        return {
            "schema_version": self.schema_version,
            "task_type": self.task_type,
            "intent": self.intent,
            "target": target,
            "inputs": [json_value(item) for item in self.inputs],
            "references": [item.to_dict() for item in self.references],
            "domains": [item.to_dict() for item in self.domains],
            "feedback": self.feedback,
            "constraints": json_value(self.constraints),
            "render": json_value(self.render),
            "delivery": json_value(self.delivery),
            "metadata": json_value(self.metadata),
            "idempotency_key": self.idempotency_key,
        }


def parse_task_spec(value: Mapping[str, Any]) -> TaskSpec | TaskSpecV2:
    """Parse v1 or v2 without changing the established ``TaskSpec`` API."""

    version = str(value.get("schema_version") or "1.0")
    if version in {"2.0", "2.1"} or value.get("task_type") == "visual.reference_rebuild":
        return TaskSpecV2.from_mapping(value)
    return TaskSpec.from_mapping(value)


def new_identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


# ---------------------------------------------------------------------------
# DCC verification gates
# ---------------------------------------------------------------------------
#
# A DCC response that carries no gates is *absence of evidence*, never a
# passing verification.  Previous revisions of the bridge synthesised
# ``passed: True`` whenever the DCC stayed silent, which made every downstream
# gate decision rest on a fabrication: the orchestrator could not distinguish
# "verified" from "nothing was checked".  These helpers make silence fail.

GATE_REASON_NO_EVIDENCE = "dcc_returned_no_gates"
GATE_REASON_NOT_OBJECT = "gate_entry_not_object"
GATE_REASON_PASSED_NOT_BOOL = "gate_passed_not_boolean"
GATE_REASON_KIND_UNSUPPORTED = "gate_kind_unsupported"
GATE_REASON_UNEXPECTED = "gate_not_allowed_for_action"
GATE_REASON_REQUIRED_MISSING = "required_gate_missing"
GATE_REASON_DUPLICATE = "duplicate_gate"
GATE_KIND_VERIFICATION = GateKind.VERIFICATION.value
GATE_KIND_EVIDENCE_CARRIER = GateKind.EVIDENCE_CARRIER.value
_KNOWN_STEP_PHASES = frozenset(
    {
        "PROBE",
        "INSPECT",
        "AUTHOR",
        "PREVIEW_RENDER",
        "TECH_VERIFY",
        "FINAL_RENDER",
        "ARTIFACT_VERIFY",
        "DELIVER",
    }
)


@dataclass(frozen=True)
class GateRule:
    """One exact, action-bound gate contract.

    ``aliases`` and ``legacy_kinds`` are deliberately local to the owning
    action.  They provide a bounded migration path for first-party plug-ins
    without turning arbitrary caller-selected names into verification.
    """

    name: str
    kind: GateKind
    aliases: tuple[str, ...] = ()
    legacy_kinds: tuple[str, ...] = ()
    operation_success_states: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.name, "gate_rule.name")
        if self.name in self.aliases or len(set(self.aliases)) != len(self.aliases):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "gate rule aliases must be unique")

    def matches(self, name: str) -> bool:
        return name == self.name or name in self.aliases


def _normalized_outcome_state(*values: Any) -> Optional[str]:
    aliases = {
        "INCONCLUSIVE": "DIAGNOSIS_INCONCLUSIVE",
        "DIAGNOSIS_INCONCLUSIVE": "DIAGNOSIS_INCONCLUSIVE",
        "AWAITING_INPUT": "AWAITING_INPUT",
        "UNSUPPORTED": "UNSUPPORTED",
        "PARTIAL": "PARTIAL",
        # A later decisive evidence step may supersede an earlier scaffold's
        # provisional inconclusive state.
        "CANDIDATES_READY": "SUCCEEDED",
        "SUCCEEDED": "SUCCEEDED",
    }
    for value in values:
        rendered = str(value or "").strip().upper()
        if rendered in aliases:
            return aliases[rendered]
    return None


@dataclass(frozen=True)
class GatePolicy:
    """Exact gate policy for one registered DCC action.

    Each tuple in ``required_groups`` is an OR group; every group must have at
    least one member in the response.  Unknown actions never receive a policy
    in the bridge adapters and therefore fail closed.
    """

    action: str
    rules: tuple[GateRule, ...] = ()
    required_groups: tuple[tuple[str, ...], ...] = ()
    allow_additional: bool = False
    allow_silent_operation: bool = False
    silent_operation_name: Optional[str] = None
    allowed_phases: tuple[str, ...] = ()
    legacy_phases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonempty(self.action, "gate_policy.action")
        known: set[str] = set()
        for rule in self.rules:
            for name in (rule.name, *rule.aliases):
                if name in known:
                    raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "gate policy names and aliases must be unique", {"name": name})
                known.add(name)
        canonical = {rule.name for rule in self.rules}
        for group in self.required_groups:
            if not group or any(name not in canonical for name in group):
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "required gate groups must reference canonical rule names")
        if self.allow_silent_operation and not str(self.silent_operation_name or "").strip():
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "silent legacy operations require an exact synthetic gate name")
        if not self.allowed_phases:
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "gate policies must declare at least one exact step phase",
                {"action": self.action},
            )
        normalized_phases = tuple(str(value or "").strip().upper() for value in self.allowed_phases)
        if any(value not in _KNOWN_STEP_PHASES for value in normalized_phases):
            raise RuntimeV2Error(
                ErrorCode.INVALID_SPEC,
                "gate policy contains an unknown step phase",
                {"action": self.action, "allowed_phases": list(normalized_phases)},
            )
        if len(set(normalized_phases)) != len(normalized_phases):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "gate policy step phases must be unique", {"action": self.action})
        normalized_legacy = tuple(str(value or "").strip().upper() for value in self.legacy_phases)
        if any(not value for value in normalized_legacy) or len(set(normalized_legacy)) != len(normalized_legacy):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "legacy step phases must be non-empty and unique", {"action": self.action})
        if set(normalized_phases).intersection(normalized_legacy):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "legacy step phases must not duplicate exact phases", {"action": self.action})

    @classmethod
    def legacy_first_party(
        cls,
        action: str,
        *,
        allowed_phases: tuple[str, ...],
        legacy_phases: tuple[str, ...] = (),
        allow_silent_operation: bool = False,
        silent_operation_name: Optional[str] = None,
    ) -> "GatePolicy":
        """Migration policy for a registered legacy action only.

        Legacy results remain operation records; callers must opt into a strict
        action policy before a gate can satisfy v2 verification requirements.
        """

        return cls(
            action=action,
            allow_additional=True,
            allow_silent_operation=allow_silent_operation,
            silent_operation_name=silent_operation_name,
            allowed_phases=allowed_phases,
            legacy_phases=legacy_phases,
        )

    def normalize(
        self,
        step_identifier: str,
        data: Any,
        *,
        allow_omitted_kind: bool = False,
    ) -> list[dict[str, Any]]:
        raw = data.get("gates") if isinstance(data, Mapping) else None
        if (raw is None or raw == []) and self.allow_silent_operation:
            return [
                {
                    "name": str(self.silent_operation_name),
                    "passed": True,
                    "kind": GateKind.OPERATION.value,
                    "reason": "registered_first_party_legacy_operation_completed",
                    "legacy_action": self.action,
                }
            ]
        if self.allow_additional:
            gates = normalize_dcc_gates(step_identifier, data)
            for gate in gates:
                if gate.get("kind") == GateKind.VERIFICATION.value:
                    gate["kind"] = GateKind.OPERATION.value
                    gate["legacy_kind_migrated"] = True
                    gate["legacy_action"] = self.action
            if not any(
                gate.get("kind") in {GateKind.OPERATION.value, GateKind.VERIFICATION.value}
                for gate in gates
            ):
                gates.append(
                    _invalid_gate(
                        step_identifier,
                        GATE_REASON_REQUIRED_MISSING,
                        {"required_kind": GateKind.OPERATION.value},
                        action=self.action,
                    )
                )
            return gates
        if not isinstance(raw, list) or not raw:
            return [_missing_gate(step_identifier, data)]

        gates: list[dict[str, Any]] = []
        seen: set[str] = set()
        matched: set[str] = set()
        for index, item in enumerate(raw):
            fallback_name = f"{step_identifier}_gate_{index}"
            if not isinstance(item, Mapping):
                gates.append(_invalid_gate(fallback_name, GATE_REASON_NOT_OBJECT, item))
                continue
            raw_name = str(item.get("name") or fallback_name)
            rule = next((candidate for candidate in self.rules if candidate.matches(raw_name)), None)
            if rule is None:
                gates.append(_invalid_gate(raw_name, GATE_REASON_UNEXPECTED, dict(item), action=self.action))
                continue
            if rule.name in seen:
                gates.append(_invalid_gate(rule.name, GATE_REASON_DUPLICATE, dict(item), action=self.action))
                continue
            seen.add(rule.name)
            passed = item.get("passed")
            if not isinstance(passed, bool):
                gates.append(_invalid_gate(rule.name, GATE_REASON_PASSED_NOT_BOOL, dict(item), action=self.action))
                continue
            raw_kind = str(item.get("kind") or "")
            accepted_kinds = {rule.kind.value, *rule.legacy_kinds}
            if allow_omitted_kind:
                accepted_kinds.add("")
            if raw_kind not in accepted_kinds:
                gates.append(
                    _invalid_gate(
                        rule.name,
                        GATE_REASON_KIND_UNSUPPORTED,
                        dict(item),
                        action=self.action,
                        expected_kind=rule.kind.value,
                    )
                )
                continue
            gate = dict(item)
            gate["name"] = rule.name
            gate["kind"] = rule.kind.value
            if raw_name != rule.name:
                gate["legacy_name"] = raw_name
            if raw_kind != rule.kind.value:
                gate["legacy_kind"] = raw_kind or "omitted"
            state = _normalized_outcome_state(
                item.get("outcome_state"),
                item.get("status"),
                data.get("diagnosis_state") if isinstance(data, Mapping) else None,
                data.get("visual_validation") if isinstance(data, Mapping) else None,
            )
            accepted_states = {str(value).strip().upper() for value in rule.operation_success_states}
            if not passed and state and state in accepted_states:
                gate["reported_passed"] = False
                gate["passed"] = True
                gate["outcome_state"] = state
                gate["reason"] = str(gate.get("reason") or "operation_completed_without_verification")
            else:
                gate["passed"] = passed
                if state:
                    gate["outcome_state"] = state
            gates.append(gate)
            matched.add(rule.name)

        for group in self.required_groups:
            if not matched.intersection(group):
                gates.append(
                    _invalid_gate(
                        step_identifier,
                        GATE_REASON_REQUIRED_MISSING,
                        {"required_any_of": list(group)},
                        action=self.action,
                    )
                )
        return gates or [_missing_gate(step_identifier, data)]

    def validate_phase(self, phase: str, *, allow_legacy: bool = False) -> None:
        """Prevent a recipe from labeling an operation as a verification step.

        Exact action policies are necessary but not sufficient: without this
        cross-check a recipe could pair a render operation with ``TECH_VERIFY``
        and complete without any technical evidence.  Legacy first-party
        actions still use their exact action mapping; this invariant is not
        relaxed for old checkpoints.
        """

        normalized = str(phase or "").strip().upper()
        exact = {str(value).strip().upper() for value in self.allowed_phases}
        legacy = {str(value).strip().upper() for value in self.legacy_phases}
        if normalized not in exact and not (allow_legacy and normalized in legacy):
            raise RuntimeError(
                "STEP_PHASE_NOT_ALLOWED: {} cannot run in {}; allowed phases are {}".format(
                    self.action,
                    normalized or "<empty>",
                    ", ".join(sorted(exact)),
                )
            )
        if normalized not in {"TECH_VERIFY", "ARTIFACT_VERIFY", "DELIVER"}:
            return
        if not any(rule.kind is GateKind.VERIFICATION for rule in self.rules):
            raise RuntimeError(
                "{} phase requires an exact verification gate policy for {}".format(
                    normalized,
                    self.action,
                )
            )

    @staticmethod
    def outcome_state(data: Any, gates: Sequence[Mapping[str, Any]]) -> Optional[str]:
        if isinstance(data, Mapping):
            state = _normalized_outcome_state(
                data.get("outcome_state"),
                data.get("diagnosis_state"),
                data.get("visual_validation"),
                data.get("execution_state"),
            )
            if state:
                return state
        return next(
            (
                state
                for gate in gates
                for state in [_normalized_outcome_state(gate.get("outcome_state"), gate.get("status"))]
                if state
            ),
            None,
        )


def _invalid_gate(name: str, reason: str, details: Any, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": False,
        "kind": GateKind.VERIFICATION.value,
        "reason": reason,
        "details": details,
        **extra,
    }


def _missing_gate(step_identifier: str, data: Any) -> dict[str, Any]:
    return {
        "name": step_identifier,
        "passed": False,
        "kind": GateKind.VERIFICATION.value,
        "reason": GATE_REASON_NO_EVIDENCE,
        "hint": "the DCC returned no verification gates; silence is not evidence",
        "details": data if isinstance(data, Mapping) else {},
    }


def normalize_dcc_gates(step_identifier: str, data: Any) -> list[dict[str, Any]]:
    """Return the verification gates a DCC step actually produced.

    Never invents a passing gate.  Malformed entries are preserved as failing
    gates so the reason is machine-readable instead of being dropped.
    """

    raw = data.get("gates") if isinstance(data, Mapping) else None
    gates: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            fallback_name = f"{step_identifier}_gate_{index}"
            if not isinstance(item, Mapping):
                gates.append(_invalid_gate(fallback_name, GATE_REASON_NOT_OBJECT, item))
                continue
            passed = item.get("passed")
            if not isinstance(passed, bool):
                gates.append(_invalid_gate(str(item.get("name") or fallback_name), GATE_REASON_PASSED_NOT_BOOL, dict(item)))
                continue
            gate = dict(item)
            gate["name"] = str(item.get("name") or fallback_name)
            gate["passed"] = passed
            gate.setdefault("kind", GATE_KIND_VERIFICATION)
            try:
                gate["kind"] = GateKind(str(gate["kind"])).value
            except ValueError:
                gates.append(_invalid_gate(gate["name"], GATE_REASON_KIND_UNSUPPORTED, dict(item)))
                continue
            gates.append(gate)
    if not gates:
        gates.append(_missing_gate(step_identifier, data))
    return gates


def attach_evidence_carrier(
    gates: list[dict[str, Any]],
    step_identifier: str,
    structured: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Persist a structured payload without inventing a passing gate.

    This helper is retained only to read or produce bounded legacy results.
    New task execution persists structured payloads in ``step_outputs`` and
    must not attach a carrier to strict DCC responses.  When explicitly used
    for compatibility, its ``passed`` mirrors the substantive gates and its
    kind prevents it from satisfying verification policy.
    """

    if not structured:
        return gates
    substantive = [gate for gate in gates if gate.get("kind") != GATE_KIND_EVIDENCE_CARRIER]
    passed = bool(substantive) and all(bool(gate.get("passed")) for gate in substantive)
    return gates + [
        {
            "name": f"{step_identifier}_structured_payload",
            "passed": passed,
            "kind": GATE_KIND_EVIDENCE_CARRIER,
            "details": dict(structured),
        }
    ]


def verification_gates(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the gates that actually verify something."""

    return [gate for gate in gates if gate.get("kind") == GateKind.VERIFICATION.value]
