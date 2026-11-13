from __future__ import annotations

from cache_resource_fixture import cache_output_path, resource_metadata

import tempfile
import unittest
from pathlib import Path

from dcc_task_runtime import (
    ActorKind,
    ApprovalService,
    CacheApprovalSubject,
    CandidatePatch,
    CauseHypothesis,
    ChangeDirection,
    DomainPackRef,
    ErrorCode,
    ExperienceService,
    IssueDimension,
    ParameterChange,
    PerceptualIssue,
    PipelineStore,
    PolicyDenied,
    RepairExperience,
    RuntimeV2Error,
    TaskState,
    VisualScorecard,
)


class Verifier:
    def verify(self, principal_id, proof, scope, request_id):
        return principal_id == "artist" and proof == f"yes:{request_id}"


def task_spec() -> dict:
    return {"schema_version": "2.0", "task_type": "visual.reference_rebuild", "intent": "repair smoke", "target": {"application": "pipeline"}, "feedback": "烟太模糊"}


def ready_for_cache(store: PipelineStore) -> str:
    task_id = store.create_task(task_spec())
    store.transition(task_id, TaskState.ANALYZING)
    store.transition(task_id, TaskState.DIAGNOSING)
    store.transition(task_id, TaskState.CANDIDATES_READY)
    return task_id


def cache_subject(task_id: str, domain=None) -> CacheApprovalSubject:
    return CacheApprovalSubject(task_id, "scene", ("input",), ("reference",), domain or DomainPackRef("pyro_smoke_v1", "1.0.0"), "smoke", {"voxel_size": 0.1}, 1, (1, 48, 1), {"houdini": "21"}, cache_output_path(), metadata=resource_metadata())


def experience(task_id: str, accepted_payload=True, improved=True) -> RepairExperience:
    domain = DomainPackRef("pyro_smoke_v1", "1.0.0")
    issue = PerceptualIssue("issue", "烟太模糊", domain, "smoke", IssueDimension.SPATIAL_DETAIL, ChangeDirection.INCREASE, 0.8, 0.9)
    hypothesis = CauseHypothesis("hypothesis", issue.issue_id, "simulation_field", "simulation", "field lost detail", ("density.frequency",), (), 0.8, "medium")
    candidate = CandidatePatch("candidate", issue.issue_id, hypothesis.hypothesis_id, hypothesis.cause_family, (ParameterChange("voxel_size", 0.1, 0.05),), ("simulation",), ("smoke",), 1, "medium", "low")
    scorecard = VisualScorecard(issue.issue_id, candidate.candidate_id, {"detail": 0.2}, {"detail": 0.8}, improved)
    return RepairExperience("experience", task_id, domain, issue.raw_feedback, issue, hypothesis, candidate, scorecard, {"houdini": "21"}, "verified-result", accepted_payload)


class ExperienceTests(unittest.TestCase):
    def test_cache_and_experience_grants_are_non_interchangeable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = ready_for_cache(store)
            approvals = ApprovalService(store, Verifier())
            cache_request = approvals.request_cache(cache_subject(task_id))
            cache_grant = approvals.grant(cache_request.request_id, "artist", f"yes:{cache_request.request_id}", ActorKind.TRUSTED_HUMAN)
            store.transition(task_id, TaskState.CACHING)
            store.transition(task_id, TaskState.VERIFYING)
            service = ExperienceService(store, approvals)
            repair = experience(task_id)
            with self.assertRaises(PolicyDenied) as raised:
                service.promote(repair, cache_grant.grant_id)
            self.assertEqual(raised.exception.code, ErrorCode.APPROVAL_SCOPE_MISMATCH)
            self.assertEqual(service.search(repair.domain), ())

    def test_second_human_grant_persists_acceptance_then_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipeline.sqlite3"
            store = PipelineStore(path)
            task_id = ready_for_cache(store)
            store.transition(task_id, TaskState.VERIFYING)
            approvals = ApprovalService(store, Verifier())
            service = ExperienceService(store, approvals)
            repair = experience(task_id, accepted_payload=False)
            request = service.request_promotion(repair)
            self.assertIsNone(store.final_acceptance(task_id, repair.verified_result_hash, repair.repair_case_hash))
            grant = approvals.grant(request.request_id, "artist", f"yes:{request.request_id}", ActorKind.TRUSTED_HUMAN)

            restarted_store = PipelineStore(path)
            restarted_service = ExperienceService(restarted_store, ApprovalService(restarted_store, Verifier()))
            persisted = restarted_store.final_acceptance(task_id, repair.verified_result_hash, repair.repair_case_hash)
            self.assertEqual(persisted["approval_grant_id"], grant.grant_id)
            restarted_service.promote(repair, grant.grant_id)
            self.assertEqual(len(restarted_service.search(repair.domain, repair.issue)), 1)
            self.assertEqual(restarted_service.search(DomainPackRef(repair.domain.identifier, "2.0.0")), ())

    def test_unverified_result_and_non_sim_cache_request_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = ready_for_cache(store)
            approvals = ApprovalService(store, Verifier())
            service = ExperienceService(store, approvals)
            with self.assertRaises(RuntimeV2Error) as raised:
                service.request_promotion(experience(task_id, improved=False))
            self.assertEqual(raised.exception.code, ErrorCode.EXPERIENCE_NOT_VERIFIED)
            material = cache_subject(task_id, DomainPackRef("material_lookdev_v1", "1.0.0"))
            with self.assertRaises(PolicyDenied) as cache_denied:
                approvals.request_cache(material)
            self.assertEqual(cache_denied.exception.code, ErrorCode.APPROVAL_SCOPE_MISMATCH)


if __name__ == "__main__":
    unittest.main()
