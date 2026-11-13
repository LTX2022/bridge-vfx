from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dcc_task_runtime import ArtifactRecord, DomainPackRef, ErrorCode, PipelineStore, RuntimeV2Error, TaskState


def spec(key: str = "stable-key") -> dict:
    return {
        "schema_version": "2.0",
        "task_type": "visual.reference_rebuild",
        "intent": "diagnose current effect",
        "target": {"application": "pipeline"},
        "feedback": "烟太模糊",
        "idempotency_key": key,
    }


class PipelineStoreTests(unittest.TestCase):
    def test_tasks_are_restart_safe_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipeline.sqlite3"
            first = PipelineStore(path)
            task_id = first.create_task(spec())
            self.assertEqual(first.create_task(spec()), task_id)
            first.transition(task_id, TaskState.ANALYZING, "analysis started")
            first.put_record(task_id, "candidate", "candidate_a", {"candidate_id": "candidate_a"})
            first.save_result(task_id, {"partial": True})

            restarted = PipelineStore(path)
            self.assertEqual(restarted.status(task_id)["state"], "ANALYZING")
            self.assertEqual(restarted.records(task_id, "candidate")[0]["candidate_id"], "candidate_a")
            self.assertEqual(restarted.result(task_id), {"partial": True})
            self.assertEqual([event["seq"] for event in restarted.events(task_id)], [1, 2])

    def test_idempotency_key_cannot_change_subject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            store.create_task(spec())
            changed = spec()
            changed["feedback"] = "火苗太钝"
            with self.assertRaises(RuntimeV2Error):
                store.create_task(changed)

    def test_invalid_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = store.create_task(spec())
            with self.assertRaises(RuntimeV2Error) as raised:
                store.transition(task_id, TaskState.CACHING)
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_TRANSITION)

    def test_artifact_and_result_evidence_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = store.create_task(spec())
            artifact = ArtifactRecord(
                "artifact_a",
                task_id,
                "diagnostic_preview",
                "/tmp/preview.exr",
                "preview-hash",
                DomainPackRef("pyro_smoke_v1", "1.0.0"),
                "smoke",
                "render",
            )
            store.add_artifact(artifact)
            store.add_artifact(artifact)
            self.assertEqual(len(store.artifacts(task_id)), 1)

    def test_skill_execution_claim_is_atomic_and_completed_result_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = store.create_task(spec())
            self.assertEqual(store.claim_skill_execution(task_id, "step-1", "a" * 64, "owner-1")["outcome"], "ACQUIRED")
            self.assertEqual(store.claim_skill_execution(task_id, "step-1", "a" * 64, "owner-2")["outcome"], "IN_DOUBT")
            store.complete_skill_execution(task_id, "step-1", "a" * 64, "owner-1", {"ok": True})
            replay = PipelineStore(store.path).claim_skill_execution(task_id, "step-1", "a" * 64, "owner-3")
            self.assertEqual(replay, {"outcome": "COMPLETED", "status": "COMPLETED", "result": {"ok": True}})

    def test_skill_execution_claim_cannot_be_rebound_or_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PipelineStore(Path(directory) / "pipeline.sqlite3")
            task_id = store.create_task(spec())
            store.claim_skill_execution(task_id, "step-1", "a" * 64, "owner-1")
            with self.assertRaises(RuntimeV2Error):
                store.claim_skill_execution(task_id, "step-1", "b" * 64, "owner-2")
            with self.assertRaises(RuntimeV2Error):
                store.complete_skill_execution(task_id, "step-1", "a" * 64, "owner-2", {"ok": True})


if __name__ == "__main__":
    unittest.main()
