"""Verified, separately approved repair-experience promotion and retrieval."""

from __future__ import annotations

from typing import Optional

from .approvals import ApprovalService, ExperienceApprovalSubject
from .contracts import ApprovalRequest, DomainPackRef, ExperienceMatch, PerceptualIssue, RepairExperience
from .errors import RuntimeV2Error
from .models import ErrorCode
from .pipeline_store import PipelineStore


class ExperienceService:
    def __init__(self, store: PipelineStore, approvals: ApprovalService) -> None:
        self.store = store
        self.approvals = approvals

    def request_promotion(self, experience: RepairExperience) -> ApprovalRequest:
        self._validate_experience(experience)
        return self.approvals.request_experience(ExperienceApprovalSubject.from_experience(experience))

    def promote(self, experience: RepairExperience, grant_id: str) -> dict:
        self._validate_experience(experience)
        subject = ExperienceApprovalSubject.from_experience(experience)
        grant = self.approvals.authorize_experience(grant_id, subject)
        acceptance = self.store.final_acceptance(experience.task_id, experience.verified_result_hash, experience.repair_case_hash)
        if acceptance is None or acceptance["approval_grant_id"] != grant.grant_id:
            raise RuntimeV2Error(ErrorCode.TRUSTED_HUMAN_REQUIRED, "persisted final human acceptance is required before experience promotion")
        return self.store.add_experience(
            experience.experience_id,
            experience.task_id,
            experience.domain.identifier,
            experience.domain.version,
            experience.issue.signature,
            experience.hypothesis.cause_family,
            experience.to_dict(),
        )

    def search(
        self,
        domain: DomainPackRef,
        issue: Optional[PerceptualIssue] = None,
        limit: int = 5,
    ) -> tuple[ExperienceMatch, ...]:
        if limit <= 0 or limit > 50:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "experience search limit must be between 1 and 50")
        if issue is not None and issue.domain != domain:
            raise RuntimeV2Error(ErrorCode.EXPERIENCE_SCOPE_MISMATCH, "issue and requested experience domain/version must match exactly")
        signature = issue.signature if issue else None
        rows = self.store.find_experiences(domain.identifier, domain.version, signature)
        matches = []
        for row in rows[:limit]:
            issue_payload = row.get("issue") or {}
            issue_signature = str(issue_payload.get("signature") or "")
            score = 1.0 if signature and issue_signature == signature else 0.5
            matches.append(
                ExperienceMatch(
                    experience_id=str(row["experience_id"]),
                    domain=domain,
                    issue_signature=issue_signature,
                    cause_family=str((row.get("hypothesis") or {}).get("cause_family") or ""),
                    score=score,
                    experience=row,
                )
            )
        return tuple(matches)

    @staticmethod
    def _validate_experience(experience: RepairExperience) -> None:
        if not experience.scorecard.verified:
            raise RuntimeV2Error(ErrorCode.EXPERIENCE_NOT_VERIFIED, "only a technically verified repair can be promoted")
        if experience.issue.domain != experience.domain:
            raise RuntimeV2Error(ErrorCode.EXPERIENCE_SCOPE_MISMATCH, "experience issue domain/version does not match its declared scope")
        if experience.issue.issue_id != experience.hypothesis.issue_id or experience.issue.issue_id != experience.candidate.issue_id:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "experience issue, hypothesis, and candidate are not linked")
        if experience.candidate.hypothesis_id != experience.hypothesis.hypothesis_id:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "experience candidate is linked to a different hypothesis")
        if experience.scorecard.candidate_id != experience.candidate.candidate_id:
            raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "experience scorecard is linked to a different candidate")
