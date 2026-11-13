"""Phase-scoped exposure and enforceable v2 action policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .approvals import ApprovalService, CacheApprovalSubject, ExperienceApprovalSubject
from .contracts import ActorKind, ArtifactRecord
from .errors import PolicyDenied, RuntimeV2Error
from .models import ErrorCode


PHASE_COMMANDS = {
    "ROUTE": {"capabilities.get", "task.plan"},
    "PROBE": {"capabilities.get", "scene.info", "node.children", "node.info", "nuke_ping", "get_project_settings"},
    "AUTHOR": {"task.start"},
    "EXECUTE": {"task.status", "task.events", "task.cancel"},
    "PREVIEW_RENDER": {"task.status", "task.events", "task.cancel"},
    "FINAL_RENDER": {"task.status", "task.events", "task.cancel"},
    "TECH_VERIFY": {"task.status", "task.events", "task.resume"},
    "ARTIFACT_VERIFY": {"task.result", "task.resume"},
    "DELIVER": {"task.result"},
    "ANALYZING": {"capabilities.get", "reference.analyze", "scene.inspect", "task.status", "task.events"},
    "PREVIEWING": {"preview.create", "preview.status", "task.status", "task.events", "task.cancel"},
    "DIAGNOSING": {"feedback.interpret", "evidence.collect", "causal.diagnose", "task.status", "task.events"},
    "CANDIDATES_READY": {"candidate.list", "candidate.select", "preview.render", "approval.request.cache", "verification.start", "task.status", "task.events"},
    "AWAITING_CACHE_APPROVAL": {"approval.request.cache", "task.status", "task.events", "task.cancel"},
    "CACHING": {"cache.run", "task.status", "task.events", "task.cancel"},
    "VERIFYING": {"metrics.compare", "verification.record", "approval.request.experience", "task.status", "task.events"},
    "AWAITING_EXPERIENCE_APPROVAL": {"approval.request.experience", "experience.promote", "task.status", "task.events"},
}


MODEL_FORBIDDEN_COMMANDS = frozenset(
    {
        "approval.grant",
        "approval.grant.cache",
        "approval.grant.experience",
        "python.exec",
        "hscript.exec",
        "nuke_run",
        "houdini.run_code",
        "nuke.run_code",
        "shell.exec",
    }
)

CACHE_COMMANDS = frozenset({"cache.run", "houdini.cache.run", "simulation.cache.run"})
EXPERIENCE_COMMANDS = frozenset({"experience.promote"})


def allowed_commands(phase: str) -> set[str]:
    return set(PHASE_COMMANDS.get(phase, {"task.status", "task.events"}))


def is_allowed(phase: str, command: str) -> bool:
    return command in allowed_commands(phase)


def compact_context(status: dict, result: dict | None = None) -> dict:
    """Return the small, stable context an agent needs for its next action."""
    return {
        "task_id": status.get("task_id"),
        "state": status.get("state"),
        "phase": status.get("phase"),
        "step": status.get("step"),
        "percent": status.get("percent"),
        "allowed_commands": sorted(allowed_commands(str(status.get("phase") or ""))),
        "next_action": (result or {}).get("next_action"),
        "error_code": (result or {}).get("error_code"),
    }


@dataclass(frozen=True)
class ActionRequest:
    phase: str
    command: str
    actor_kind: ActorKind
    task_id: Optional[str] = None
    grant_id: Optional[str] = None
    approval_subject: Optional[CacheApprovalSubject | ExperienceApprovalSubject] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    command: str
    reason: str
    grant_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "command": self.command, "reason": self.reason, "grant_id": self.grant_id}


class PolicyEngine:
    """A mandatory authorization boundary, not an advisory tool list."""

    def __init__(self, approvals: Optional[ApprovalService] = None) -> None:
        self.approvals = approvals

    def authorize_action(self, action: ActionRequest) -> PolicyDecision:
        if action.actor_kind is ActorKind.MODEL and action.command in MODEL_FORBIDDEN_COMMANDS:
            raise PolicyDenied(ErrorCode.POLICY_DENIED, "models may not grant approvals or execute arbitrary code", {"command": action.command})
        if action.actor_kind is ActorKind.MODEL and not is_allowed(action.phase, action.command):
            raise PolicyDenied(ErrorCode.POLICY_DENIED, "command is not exposed in the current phase", {"phase": action.phase, "command": action.command})
        if action.command in CACHE_COMMANDS:
            if self.approvals is None or not action.grant_id or not isinstance(action.approval_subject, CacheApprovalSubject):
                raise PolicyDenied(ErrorCode.APPROVAL_REQUIRED, "an exact cache approval is required")
            grant = self.approvals.authorize_cache(action.grant_id, action.approval_subject)
            if action.task_id and action.task_id != grant.task_id:
                raise PolicyDenied(ErrorCode.APPROVAL_SUBJECT_MISMATCH, "cache action task does not match its approval")
            return PolicyDecision(True, action.command, "exact cache subject is approved", grant.grant_id)
        if action.command in EXPERIENCE_COMMANDS:
            if self.approvals is None or not action.grant_id or not isinstance(action.approval_subject, ExperienceApprovalSubject):
                raise PolicyDenied(ErrorCode.APPROVAL_REQUIRED, "a separate exact experience-promotion approval is required")
            grant = self.approvals.authorize_experience(action.grant_id, action.approval_subject)
            if action.task_id and action.task_id != grant.task_id:
                raise PolicyDenied(ErrorCode.APPROVAL_SUBJECT_MISMATCH, "experience action task does not match its approval")
            return PolicyDecision(True, action.command, "exact experience subject is approved", grant.grant_id)
        return PolicyDecision(True, action.command, "command is allowed in the current phase")

    def authorize_action_batch(self, actions: Sequence[ActionRequest]) -> tuple[PolicyDecision, ...]:
        if len(actions) > 1 and any(action.actor_kind is ActorKind.MODEL for action in actions):
            raise PolicyDenied(ErrorCode.TOOL_BUDGET_EXCEEDED, "a model turn may authorize at most one action")
        return tuple(self.authorize_action(action) for action in actions)

    def validate_artifact_lineage(
        self,
        artifact: ArtifactRecord,
        all_artifacts: Sequence[ArtifactRecord | Mapping[str, Any]],
    ) -> None:
        if not artifact.final_delivery:
            return
        lookup: dict[str, ArtifactRecord | Mapping[str, Any]] = {}
        for item in all_artifacts:
            item_id = item.artifact_id if isinstance(item, ArtifactRecord) else str(item.get("artifact_id") or "")
            if item_id:
                lookup[item_id] = item
        lookup[artifact.artifact_id] = artifact
        visiting: set[str] = set()
        visited: set[str] = set()

        def inspect(artifact_id: str) -> None:
            if artifact_id in visiting:
                raise PolicyDenied(ErrorCode.POLICY_DENIED, "artifact lineage contains a cycle", {"artifact_id": artifact_id})
            if artifact_id in visited:
                return
            item = lookup.get(artifact_id)
            if item is None:
                raise PolicyDenied(ErrorCode.ARTIFACT_MISSING, "artifact lineage dependency is missing", {"artifact_id": artifact_id})
            reference = item.reference_asset if isinstance(item, ArtifactRecord) else bool(item.get("reference_asset"))
            if reference:
                raise PolicyDenied(ErrorCode.POLICY_DENIED, "a reference asset may not be upstream of final delivery", {"artifact_id": artifact_id})
            dependencies = item.dependencies if isinstance(item, ArtifactRecord) else tuple(item.get("dependencies") or ())
            visiting.add(artifact_id)
            for dependency in dependencies:
                inspect(str(dependency))
            visiting.remove(artifact_id)
            visited.add(artifact_id)

        inspect(artifact.artifact_id)
