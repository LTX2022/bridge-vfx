from __future__ import annotations

from cache_resource_fixture import cache_output_path, resource_metadata

import tempfile
import unittest
from pathlib import Path

from dcc_task_runtime import (
    ActionRequest,
    ActorKind,
    ApprovalService,
    ArtifactRecord,
    CacheApprovalSubject,
    DomainPackRef,
    ErrorCode,
    PipelineStore,
    PolicyDenied,
    PolicyEngine,
    TaskState,
)


class Verifier:
    def verify(self, principal_id, proof, scope, request_id):
        return proof == request_id and principal_id == "artist"


def create_task(store):
    task_id = store.create_task({"schema_version": "2.0", "task_type": "visual.reference_rebuild", "intent": "repair", "target": {"application": "pipeline"}, "feedback": "烟太模糊"})
    store.transition(task_id, TaskState.ANALYZING)
    store.transition(task_id, TaskState.DIAGNOSING)
    store.transition(task_id, TaskState.CANDIDATES_READY)
    return task_id


def subject(task_id):
    return CacheApprovalSubject(task_id, "scene", ("input",), ("reference",), DomainPackRef("pyro_smoke_v1", "1.0.0"), "smoke", {"voxel_size": 0.1}, 1, (1, 48, 1), {"houdini": "21"}, cache_output_path(), metadata=resource_metadata())


class PolicyTests(unittest.TestCase):
    def test_model_cannot_execute_raw_code_or_multi_action(self) -> None:
        policy = PolicyEngine()
        with self.assertRaises(PolicyDenied) as raw:
            policy.authorize_action(ActionRequest("ANALYZING", "python.exec", ActorKind.MODEL))
        self.assertEqual(raw.exception.code, ErrorCode.POLICY_DENIED)
        with self.assertRaises(PolicyDenied) as batch:
            policy.authorize_action_batch((ActionRequest("ANALYZING", "scene.inspect", ActorKind.MODEL), ActionRequest("ANALYZING", "task.status", ActorKind.MODEL)))
        self.assertEqual(batch.exception.code, ErrorCode.TOOL_BUDGET_EXCEEDED)

    def test_cache_action_requires_exact_active_grant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = create_task(store)
            approvals = ApprovalService(store, Verifier())
            cache = subject(task_id)
            request = approvals.request_cache(cache)
            grant = approvals.grant(request.request_id, "artist", request.request_id, ActorKind.TRUSTED_HUMAN)
            policy = PolicyEngine(approvals)
            decision = policy.authorize_action(ActionRequest("CACHING", "cache.run", ActorKind.MODEL, task_id, grant.grant_id, cache))
            self.assertTrue(decision.allowed)
            changed = CacheApprovalSubject(**{**cache.__dict__, "parameters": {"voxel_size": 0.05}})
            with self.assertRaises(PolicyDenied):
                policy.authorize_action(ActionRequest("CACHING", "cache.run", ActorKind.MODEL, task_id, grant.grant_id, changed))

    def test_reference_asset_cannot_be_upstream_of_final_delivery(self) -> None:
        policy = PolicyEngine()
        reference = ArtifactRecord("reference", "task", "reference", "/tmp/ref.png", "hash", None, None, "source", (), True, False)
        diagnostic = ArtifactRecord("diagnostic", "task", "preview", "/tmp/diag.exr", "hash2", None, None, "composite", ("reference",), False, False)
        final = ArtifactRecord("final", "task", "delivery", "/tmp/final.exr", "hash3", None, None, "delivery", ("diagnostic",), False, True)
        with self.assertRaises(PolicyDenied):
            policy.validate_artifact_lineage(final, (reference, diagnostic, final))
        clean = ArtifactRecord("effect", "task", "render", "/tmp/effect.exr", "hash4", None, None, "render")
        final_clean = ArtifactRecord("final_clean", "task", "delivery", "/tmp/final2.exr", "hash5", None, None, "delivery", ("effect",), False, True)
        policy.validate_artifact_lineage(final_clean, (clean, final_clean))


if __name__ == "__main__":
    unittest.main()
