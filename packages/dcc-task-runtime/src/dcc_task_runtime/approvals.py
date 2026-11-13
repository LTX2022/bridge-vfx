"""Trusted-human approval boundaries for caches and repair experiences."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any, Mapping, Protocol

from .canonical import canonical_sha256, json_value
from .contracts import (
    ActorKind,
    ApprovalGrant,
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    DomainPackRef,
    RepairExperience,
)
from .errors import PolicyDenied, RuntimeV2Error
from .domains import DomainPackRegistry, builtin_domain_registry
from .models import ErrorCode, TaskState
from .pipeline_store import PipelineStore, V2_STATE_TRANSITIONS


def _required_text(value: Any, name: str) -> str:
    rendered = str(value or "").strip()
    if not rendered:
        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, f"{name} is required")
    return rendered


class HumanVerifier(Protocol):
    """Implemented by the trusted UI/control plane, never by a model adapter."""

    def verify(self, principal_id: str, proof: str, scope: ApprovalScope, request_id: str) -> bool:
        ...


@dataclass(frozen=True)
class CacheApprovalSubject:
    task_id: str
    scene_hash: str
    input_hashes: tuple[str, ...]
    reference_hashes: tuple[str, ...]
    domain: DomainPackRef
    component_id: str
    parameters: Mapping[str, Any]
    seed: int
    frame_range: tuple[int, int, int]
    dcc_versions: Mapping[str, str]
    output_path: str
    dependencies: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, name in (
            (self.task_id, "cache.task_id"),
            (self.scene_hash, "cache.scene_hash"),
            (self.component_id, "cache.component_id"),
            (self.output_path, "cache.output_path"),
        ):
            _required_text(value, name)
        if not self.input_hashes:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "cache.input_hashes must not be empty")
        if not self.parameters:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "cache.parameters must not be empty")
        if not self.dcc_versions:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "cache.dcc_versions must not be empty")
        if (len(self.frame_range) != 3 or any(type(frame) is not int for frame in self.frame_range) or
                self.frame_range[0] > self.frame_range[1] or self.frame_range[2] <= 0):
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "cache.frame_range is invalid")
        resource = self.metadata.get("resource_contract") or {}
        for name in ("estimated_bytes", "max_disk_bytes"):
            if type(resource.get(name)) is not int or resource[name] <= 0:
                raise RuntimeV2Error(ErrorCode.APPROVAL_REQUIRED, "cache resource contract requires positive " + name)
        seconds = resource.get("max_seconds")
        if type(resource.get("simulation_start_frame")) is not int or resource["simulation_start_frame"] > self.frame_range[0]:
            raise RuntimeV2Error(ErrorCode.APPROVAL_REQUIRED, "cache resource contract requires the solver history start frame")
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or
                not math.isfinite(seconds) or not 0 < seconds <= 120 or
                resource["estimated_bytes"] > resource["max_disk_bytes"]):
            raise RuntimeV2Error(ErrorCode.APPROVAL_SCOPE_MISMATCH, "cache resource budget is invalid")
        if (resource.get("output_path") != self.output_path or
                resource.get("frame_range") != list(self.frame_range) or
                resource.get("content_version") != self.scene_hash or
                not isinstance(resource.get("invalidation_scope"), list) or
                not resource["invalidation_scope"] or
                not all(isinstance(item, str) and item.strip() for item in resource["invalidation_scope"])):
            raise RuntimeV2Error(ErrorCode.APPROVAL_SCOPE_MISMATCH, "cache resources do not bind frames/path/version/invalidation")
        roots = resource.get("task_roots")
        if (not isinstance(roots, list) or not roots or
                any(not isinstance(root, str) or not Path(root).is_absolute() for root in roots) or
                not Path(self.output_path).is_absolute() or
                not any(Path(self.output_path).resolve().is_relative_to(Path(root).resolve()) for root in roots)):
            raise RuntimeV2Error(ErrorCode.APPROVAL_SCOPE_MISMATCH, "cache output is outside trusted budget roots")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scene_hash": self.scene_hash,
            "input_hashes": list(self.input_hashes),
            "reference_hashes": list(self.reference_hashes),
            "domain": self.domain.to_dict(),
            "component_id": self.component_id,
            "parameters": json_value(self.parameters),
            "seed": self.seed,
            "frame_range": {"start": self.frame_range[0], "end": self.frame_range[1], "step": self.frame_range[2]},
            "dcc_versions": json_value(self.dcc_versions),
            "output_path": self.output_path,
            "dependencies": list(self.dependencies),
            "metadata": json_value(self.metadata),
        }

    @property
    def subject_hash(self) -> str:
        return canonical_sha256({"scope": ApprovalScope.HOUDINI_SIMULATION_CACHE.value, "subject": self.to_dict()})


@dataclass(frozen=True)
class ExperienceApprovalSubject:
    task_id: str
    repair_case_hash: str
    domain: DomainPackRef
    verified_result_hash: str

    def __post_init__(self) -> None:
        _required_text(self.task_id, "experience.task_id")
        _required_text(self.repair_case_hash, "experience.repair_case_hash")
        _required_text(self.verified_result_hash, "experience.verified_result_hash")

    @classmethod
    def from_experience(cls, experience: RepairExperience) -> "ExperienceApprovalSubject":
        if not experience.scorecard.verified:
            raise RuntimeV2Error(ErrorCode.EXPERIENCE_NOT_VERIFIED, "repair result has not passed technical verification")
        return cls(experience.task_id, experience.repair_case_hash, experience.domain, experience.verified_result_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "repair_case_hash": self.repair_case_hash,
            "domain": self.domain.to_dict(),
            "verified_result_hash": self.verified_result_hash,
        }

    @property
    def subject_hash(self) -> str:
        return canonical_sha256({"scope": ApprovalScope.REPAIR_EXPERIENCE_PROMOTION.value, "subject": self.to_dict()})


class ApprovalService:
    def __init__(
        self,
        store: PipelineStore,
        human_verifier: HumanVerifier,
        domains: DomainPackRegistry | None = None,
    ) -> None:
        self.store = store
        self.human_verifier = human_verifier
        self.domains = domains or builtin_domain_registry()

    def request_cache(self, subject: CacheApprovalSubject) -> ApprovalRequest:
        self._ensure_task(subject.task_id)
        domain_pack = self.domains.get(subject.domain.identifier, subject.domain.version)
        supports_simulation_cache = "simulation_cache" in domain_pack.artifact_kinds or any(
            control.requires_simulation_cache for control in domain_pack.controls
        )
        if not supports_simulation_cache:
            raise PolicyDenied(
                ErrorCode.APPROVAL_SCOPE_MISMATCH,
                "this domain has no Houdini simulation cache and may not request simulation-cache approval",
                {"domain": subject.domain.to_dict()},
            )
        row = self.store.create_approval_request(
            subject.task_id,
            ApprovalScope.HOUDINI_SIMULATION_CACHE.value,
            subject.subject_hash,
            subject.to_dict(),
        )
        self._move_if_possible(subject.task_id, TaskState.AWAITING_CACHE_APPROVAL, "cache approval requested")
        return self._request(row)

    def request_experience(self, subject: ExperienceApprovalSubject) -> ApprovalRequest:
        self._ensure_task(subject.task_id)
        row = self.store.create_approval_request(
            subject.task_id,
            ApprovalScope.REPAIR_EXPERIENCE_PROMOTION.value,
            subject.subject_hash,
            subject.to_dict(),
        )
        self._move_if_possible(subject.task_id, TaskState.AWAITING_EXPERIENCE_APPROVAL, "experience promotion approval requested")
        return self._request(row)

    def grant(
        self,
        request_id: str,
        principal_id: str,
        proof: str,
        actor_kind: ActorKind,
    ) -> ApprovalGrant:
        request = self.store.get_approval_request(request_id)
        scope = ApprovalScope(request["scope"])
        if actor_kind is not ActorKind.TRUSTED_HUMAN:
            raise PolicyDenied(ErrorCode.TRUSTED_HUMAN_REQUIRED, "only the trusted human control plane may grant approvals")
        if not self.human_verifier.verify(principal_id, proof, scope, request_id):
            raise PolicyDenied(ErrorCode.TRUSTED_HUMAN_REQUIRED, "human approval proof could not be verified")
        existing = self.store.grant_for_request(request_id)
        if existing:
            if existing["status"] == ApprovalStatus.GRANTED.value and existing["principal_id"] != principal_id:
                raise PolicyDenied(ErrorCode.POLICY_DENIED, "approval request is already granted to a different principal")
            if existing["status"] == ApprovalStatus.REVOKED.value:
                grant = self._grant(self.store.reactivate_approval_grant(str(existing["grant_id"]), principal_id))
            else:
                grant = self._grant(existing)
        else:
            grant = self._grant(self.store.create_approval_grant(request, principal_id))
        if scope is ApprovalScope.REPAIR_EXPERIENCE_PROMOTION:
            subject = request["subject"]
            self.store.record_final_acceptance(
                request["task_id"],
                str(subject["verified_result_hash"]),
                str(subject["repair_case_hash"]),
                principal_id,
                grant.grant_id,
            )
        return grant

    def authorize_cache(self, grant_id: str, subject: CacheApprovalSubject) -> ApprovalGrant:
        return self._authorize(grant_id, ApprovalScope.HOUDINI_SIMULATION_CACHE, subject.task_id, subject.subject_hash)

    def authorize_experience(self, grant_id: str, subject: ExperienceApprovalSubject) -> ApprovalGrant:
        return self._authorize(grant_id, ApprovalScope.REPAIR_EXPERIENCE_PROMOTION, subject.task_id, subject.subject_hash)

    def invalidate_changed(
        self,
        task_id: str,
        scope: ApprovalScope,
        current_subject_hash: str,
    ) -> tuple[str, ...]:
        revoked: list[str] = []
        for grant in self.store.active_grants(task_id, scope.value):
            if grant["subject_hash"] != current_subject_hash:
                self.store.revoke_grant(grant["grant_id"])
                revoked.append(str(grant["grant_id"]))
        if revoked:
            self._move_if_possible(task_id, TaskState.APPROVAL_REVOKED, "approval revoked because its exact subject changed")
        return tuple(revoked)

    def _authorize(self, grant_id: str, scope: ApprovalScope, task_id: str, subject_hash: str) -> ApprovalGrant:
        row = self.store.get_approval_grant(grant_id)
        if row["scope"] != scope.value:
            raise PolicyDenied(ErrorCode.APPROVAL_SCOPE_MISMATCH, "approval scope does not authorize this action")
        if row["task_id"] != task_id or row["subject_hash"] != subject_hash:
            raise PolicyDenied(ErrorCode.APPROVAL_SUBJECT_MISMATCH, "approval is bound to a different exact subject")
        if row["status"] != ApprovalStatus.GRANTED.value:
            raise PolicyDenied(ErrorCode.APPROVAL_REVOKED, "approval is no longer active")
        return self._grant(row)

    def _ensure_task(self, task_id: str) -> None:
        self.store.get_task(task_id)

    def _move_if_possible(self, task_id: str, target: TaskState, message: str) -> None:
        current = TaskState(self.store.status(task_id)["state"])
        if current == target:
            return
        if target in V2_STATE_TRANSITIONS.get(current, frozenset()):
            self.store.transition(task_id, target, message)

    @staticmethod
    def _request(row: Mapping[str, Any]) -> ApprovalRequest:
        return ApprovalRequest(
            request_id=str(row["request_id"]),
            task_id=str(row["task_id"]),
            scope=ApprovalScope(str(row["scope"])),
            subject_hash=str(row["subject_hash"]),
            subject=dict(row["subject"]),
            status=ApprovalStatus(str(row["status"])),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _grant(row: Mapping[str, Any]) -> ApprovalGrant:
        return ApprovalGrant(
            grant_id=str(row["grant_id"]),
            request_id=str(row["request_id"]),
            task_id=str(row["task_id"]),
            scope=ApprovalScope(str(row["scope"])),
            subject_hash=str(row["subject_hash"]),
            principal_id=str(row["principal_id"]),
            status=ApprovalStatus(str(row["status"])),
            granted_at=str(row["granted_at"]),
            revoked_at=str(row["revoked_at"]) if row.get("revoked_at") else None,
        )
