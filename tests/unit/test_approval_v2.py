from __future__ import annotations

from cache_resource_fixture import cache_output_path, resource_metadata

import tempfile
import unittest
from pathlib import Path

from dcc_task_runtime import (
    ActorKind,
    ApprovalScope,
    ApprovalService,
    CacheApprovalSubject,
    DomainPackRef,
    ErrorCode,
    ExperienceApprovalSubject,
    PipelineStore,
    PolicyDenied,
    TaskState,
)


class Verifier:
    def verify(self, principal_id, proof, scope, request_id):
        return principal_id == "artist-1" and proof == f"confirmed:{request_id}" and scope in set(ApprovalScope)


def task_spec() -> dict:
    return {
        "schema_version": "2.0",
        "task_type": "visual.reference_rebuild",
        "intent": "repair smoke",
        "target": {"application": "pipeline"},
        "feedback": "烟太模糊",
    }


def ready_task(store: PipelineStore) -> str:
    task_id = store.create_task(task_spec())
    store.transition(task_id, TaskState.ANALYZING)
    store.transition(task_id, TaskState.DIAGNOSING)
    store.transition(task_id, TaskState.CANDIDATES_READY)
    return task_id


def cache_subject(task_id: str, voxel_size: float = 0.1) -> CacheApprovalSubject:
    return CacheApprovalSubject(
        task_id=task_id,
        scene_hash="scene-hash",
        input_hashes=("source-hash",),
        reference_hashes=("reference-hash",),
        domain=DomainPackRef("pyro_smoke_v1", "1.0.0"),
        component_id="smoke",
        parameters={"disturbance": 1.0, "voxel_size": voxel_size},
        seed=41,
        frame_range=(1, 48, 1),
        dcc_versions={"houdini": "21.0"},
        output_path=cache_output_path("smoke.$F4.vdb"),
        dependencies=("source-hash",),
        metadata=resource_metadata(cache_output_path("smoke.$F4.vdb"), "scene-hash"),
    )


class ApprovalTests(unittest.TestCase):
    def test_preflight_never_self_grants_and_model_cannot_grant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = ready_task(store)
            service = ApprovalService(store, Verifier())
            request = service.request_cache(cache_subject(task_id))
            self.assertEqual(request.status.value, "PENDING")
            self.assertEqual(store.active_grants(task_id), ())
            with self.assertRaises(PolicyDenied) as raised:
                service.grant(request.request_id, "artist-1", f"confirmed:{request.request_id}", ActorKind.MODEL)
            self.assertEqual(raised.exception.code, ErrorCode.TRUSTED_HUMAN_REQUIRED)

    def test_exact_human_grant_is_idempotent_restart_safe_and_scope_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipeline.sqlite3"
            store = PipelineStore(path)
            task_id = ready_task(store)
            service = ApprovalService(store, Verifier())
            subject = cache_subject(task_id)
            request = service.request_cache(subject)
            grant = service.grant(request.request_id, "artist-1", f"confirmed:{request.request_id}", ActorKind.TRUSTED_HUMAN)
            duplicate = service.grant(request.request_id, "artist-1", f"confirmed:{request.request_id}", ActorKind.TRUSTED_HUMAN)
            self.assertEqual(duplicate.grant_id, grant.grant_id)

            restarted = ApprovalService(PipelineStore(path), Verifier())
            self.assertEqual(restarted.authorize_cache(grant.grant_id, subject).grant_id, grant.grant_id)
            wrong_scope = ExperienceApprovalSubject(task_id, "case-hash", subject.domain, "result-hash")
            with self.assertRaises(PolicyDenied) as raised:
                restarted.authorize_experience(grant.grant_id, wrong_scope)
            self.assertEqual(raised.exception.code, ErrorCode.APPROVAL_SCOPE_MISMATCH)

    def test_any_subject_change_revokes_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = ready_task(store)
            service = ApprovalService(store, Verifier())
            original = cache_subject(task_id)
            request = service.request_cache(original)
            grant = service.grant(request.request_id, "artist-1", f"confirmed:{request.request_id}", ActorKind.TRUSTED_HUMAN)
            changed = cache_subject(task_id, 0.05)
            revoked = service.invalidate_changed(task_id, ApprovalScope.HOUDINI_SIMULATION_CACHE, changed.subject_hash)
            self.assertEqual(revoked, (grant.grant_id,))
            self.assertEqual(store.status(task_id)["state"], "APPROVAL_REVOKED")
            with self.assertRaises(PolicyDenied) as raised:
                service.authorize_cache(grant.grant_id, original)
            self.assertEqual(raised.exception.code, ErrorCode.APPROVAL_REVOKED)

    def test_revoked_exact_subject_requires_and_accepts_a_fresh_human_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = ready_task(store)
            service = ApprovalService(store, Verifier())
            original = cache_subject(task_id)
            request = service.request_cache(original)
            grant = service.grant(
                request.request_id,
                "artist-1",
                f"confirmed:{request.request_id}",
                ActorKind.TRUSTED_HUMAN,
            )
            service.invalidate_changed(
                task_id,
                ApprovalScope.HOUDINI_SIMULATION_CACHE,
                cache_subject(task_id, 0.05).subject_hash,
            )

            reopened = service.request_cache(original)
            self.assertEqual(reopened.request_id, request.request_id)
            self.assertEqual(reopened.status.value, "PENDING")
            reauthorized = service.grant(
                reopened.request_id,
                "artist-1",
                f"confirmed:{reopened.request_id}",
                ActorKind.TRUSTED_HUMAN,
            )
            self.assertEqual(reauthorized.grant_id, grant.grant_id)
            self.assertEqual(service.authorize_cache(reauthorized.grant_id, original).status.value, "GRANTED")
            self.assertEqual(
                [item["action"] for item in store.approval_events(task_id)],
                ["REQUEST_CREATED", "GRANT_CREATED", "GRANT_REVOKED", "REQUEST_REOPENED", "GRANT_REAUTHORIZED"],
            )

    def test_canonical_subject_hash_does_not_depend_on_mapping_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = ready_task(store)
            first = cache_subject(task_id)
            second = CacheApprovalSubject(**{**first.__dict__, "parameters": {"voxel_size": 0.1, "disturbance": 1.0}})
            self.assertEqual(first.subject_hash, second.subject_hash)


if __name__ == "__main__":
    unittest.main()
