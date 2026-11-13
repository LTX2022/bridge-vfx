from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dcc_task_runtime.contracts import DomainPackRef, TaskSpecV2
from dcc_task_runtime.models import TaskState
from houdini_bridge.domain_packs import get_domain_pack, SemanticControl
from vfx_pipeline.service import ModelSafePipeline
from test_vfx_pipeline import raw_spec, drive_to_candidates, issue_payload
from windows_filesystem_fixture import fixture_approval_environment, fixture_private_permissions


class PipelineRepairTests(unittest.TestCase):
    def test_render_control_in_simulation_pack_does_not_invalidate_simulation(self):
        pack = get_domain_pack("pyro_smoke_v1")
        pack = replace(pack, controls=pack.controls + (
            SemanticControl("pixel_samples", "render", ("samples",), 1, 128, "render"),
        ))
        payload = issue_payload()[2]
        payload["changes"] = [{"control": "pixel_samples", "previous": 4, "proposed": 8}]
        candidate = ModelSafePipeline._candidate(payload)
        domain = DomainPackRef("pyro_smoke_v1", "1.0.0")
        with tempfile.TemporaryDirectory() as directory:
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3")
            with patch("vfx_pipeline.service.get_houdini_domain_pack", return_value=pack):
                values, requires_cache = pipeline._houdini_candidate_contract(domain, candidate)
                self.assertEqual(values, {"pixel_samples": 8})
                self.assertFalse(requires_cache)
                executable = pipeline._executable_candidate(candidate, domain, TaskSpecV2.from_mapping(raw_spec(domain.identifier, "detail")))
                self.assertEqual(executable.invalidates_components, ())

    def test_mixed_supported_and_unknown_patch_is_rejected_whole(self):
        payload = issue_payload()[2]
        payload["changes"].append({"control": "unknown_control", "previous": 1, "proposed": 2})
        with tempfile.TemporaryDirectory() as directory:
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3")
            result = pipeline._executable_candidate(
                pipeline._candidate(payload), DomainPackRef("pyro_smoke_v1", "1.0.0"),
                TaskSpecV2.from_mapping(raw_spec("pyro_smoke_v1", "detail")),
            )
            self.assertIsNone(result)

    def test_cache_transport_error_persists_reconciliation_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            pipeline = ModelSafePipeline(database)
            task_id = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail"))
            pipeline.store.transition(task_id, TaskState.AWAITING_CACHE_APPROVAL, "test")
            def interrupted(*args):
                pipeline.store.transition(task_id, TaskState.CACHING, "test")
                raise ConnectionError("host disconnected")
            with patch.object(pipeline, "_cache_run", side_effect=interrupted):
                with self.assertRaises(ConnectionError):
                    pipeline.cache_run(task_id, "grant")
            restarted = ModelSafePipeline(database)
            self.assertEqual(restarted.task_status(task_id)["state"], "PARTIAL")
            recovery = restarted.store.records(task_id, "recovery")[0]
            self.assertTrue(recovery["requires_host_reconciliation"])
            self.assertEqual(recovery["grant_id"], "grant")
            self.assertEqual(restarted.task_result(task_id)["state"], "PARTIAL")

    def test_restart_queries_completed_cache_without_restarting_it(self):
        import os
        from vfx_pipeline.service import TrustedApprovalControl
        from test_vfx_pipeline import FakeCacheClient, fake_router
        class InterruptedClient(FakeCacheClient):
            def call(self, command, params):
                response = super().call(command, params)
                if command == "agent.fx.cache":
                    raise ConnectionError("reply lost after host accepted cache")
                return response
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "cache.0001.vdb", root / "cache.0002.vdb"]
            for path in paths:
                path.write_bytes(b"test-only cache fixture")
            client = InterruptedClient(paths)
            router = fake_router(houdini_client=client)
            database = root / "state.sqlite3"
            pipeline = ModelSafePipeline(database, router=router)
            frames = {"start": 1, "end": 2, "step": 1}
            task_id = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail", render={"frame_range": frames}))
            candidate = issue_payload()[2]
            sub_spec = {
                "intent": "cache recovery test", "target": {"application": "houdini", "scene_mode": "current"},
                "inputs": [], "constraints": {"fx": {"domain_pack": "pyro_smoke_v1", "candidate_patch": {"voxel_size": 0.05}}},
                "render": {"frame_range": frames}, "delivery": {},
            }
            pipeline.store.put_record(task_id, "selection", "current", {
                "candidate": candidate, "requires_simulation_cache": True,
                "houdini_patch": {"voxel_size": 0.05},
                "dcc_preview": {"subtask_id": "child", "port": 18180, "backend_id": "houdini_legacy_http",
                    "protocol": "houdini.bridge.http", "session": "houdini_legacy_http:18180", "spec": sub_spec},
                "host_cache_subject": {"subject_hash": "host-hash", "subject": {
                    "input_digest": "inputs", "scene": {"fingerprint": "scene"}, "frame_range": frames,
                    "seed": 1, "houdini_version": "test-only", "cache_output": str(root / "cache.$F4.vdb"),
                    "related_nodes": ["/obj/smoke"],
                }},
            })
            TrustedApprovalControl(pipeline).configure_cache_resources(
                task_id, task_roots=[root], estimated_bytes=1024,
                max_disk_bytes=1024 * 1024, max_seconds=120, simulation_start_frame=1, invalidation_scope=["smoke.simulation", "render"])
            request = pipeline.approval_request_cache(task_id)
            key = root / "approval.key"
            key.write_text("s" * 64)
            fixture_private_permissions(key)
            with patch.dict(os.environ, fixture_approval_environment(key)):
                trusted = TrustedApprovalControl(pipeline)
                proof = trusted.sign_proof("artist", "houdini_simulation_cache", request["request_id"])
                grant = trusted.grant_cache(request["request_id"], "artist", proof)
                with self.assertRaises(ConnectionError):
                    pipeline.cache_run(task_id, grant["grant_id"])
                restarted = ModelSafePipeline(database, router=router)
                result = restarted.task_resume(task_id)
            self.assertEqual(result["status"]["state"], "VERIFYING")
            self.assertEqual([command for command, _ in client.calls], ["agent.fx.cache", "agent.fx.cache_status"])
            self.assertEqual(client.calls[1][1]["expected_subject_hash"], "host-hash")

    def test_model_turn_retries_replay_saved_result_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            pipeline = ModelSafePipeline(database)
            task_id = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail"))
            with patch.object(pipeline, "_model_step", return_value={"step_id": "one", "action_result": {"done": True}}) as execute:
                first = pipeline.model_step(task_id, {}, request_id="same-turn")
                second = pipeline.model_step(task_id, {}, request_id="same-turn")
                self.assertEqual(first, second)
                self.assertEqual(execute.call_count, 1)
            restarted = ModelSafePipeline(database)
            with patch.object(restarted, "_model_step", side_effect=AssertionError("must not execute again")):
                self.assertEqual(restarted.model_step(task_id, {}, request_id="same-turn"), first)

    def test_model_turn_crash_is_not_blindly_reexecuted(self):
        from vfx_pipeline.service import PipelineExecutionError
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            pipeline = ModelSafePipeline(database)
            task_id = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail"))
            with patch.object(pipeline, "_model_step", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    pipeline.model_step(task_id, {}, request_id="interrupted")
            restarted = ModelSafePipeline(database)
            with patch.object(restarted, "_model_step", side_effect=AssertionError("must not repeat uncertain action")):
                with self.assertRaises(PipelineExecutionError) as caught:
                    restarted.model_step(task_id, {}, request_id="interrupted")
                self.assertIn("in doubt", str(caught.exception))

    def test_wrong_grant_does_not_destroy_recovery(self):
        from vfx_pipeline.service import PipelineExecutionError
        with tempfile.TemporaryDirectory() as directory:
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3")
            task = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail"))
            pipeline.store.transition(task, TaskState.AWAITING_CACHE_APPROVAL, "test")
            pipeline.store.transition(task, TaskState.CACHING, "test")
            pipeline.store.transition(task, TaskState.PARTIAL, "test")
            original = {"phase": "cache", "grant_id": "original", "requires_host_reconciliation": True}
            pipeline.store.put_record(task, "recovery", "cache", original)
            with self.assertRaises(PipelineExecutionError):
                pipeline.cache_run(task, "wrong")
            self.assertEqual(pipeline.store.records(task, "recovery"), (original,))

    def test_process_crash_in_caching_resumes_saved_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            pipeline = ModelSafePipeline(database)
            task = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail"))
            pipeline.store.transition(task, TaskState.AWAITING_CACHE_APPROVAL, "test")
            pipeline.store.put_record(task, "recovery", "cache", {"phase": "cache", "grant_id": "original"})
            pipeline.store.transition(task, TaskState.CACHING, "test process exits now")
            restarted = ModelSafePipeline(database)
            with patch.object(restarted, "cache_run", return_value={"reconciled": True}) as resume:
                self.assertEqual(restarted.task_resume(task), {"reconciled": True})
                resume.assert_called_once_with(task, "original")

    def test_reference_analysis_precedes_construction_and_is_bound_to_subtask(self):
        import hashlib
        from dcc_task_runtime.canonical import canonical_sha256
        from test_vfx_pipeline import fake_router
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ref = root / "ref.png"
            ref.write_bytes(b"synthetic test bytes")
            raw = raw_spec("pyro_smoke_v1", "detail", references=[{
                "asset_id": "ref", "kind": "image", "uri": str(ref), "sha256": hashlib.sha256(ref.read_bytes()).hexdigest(),
            }])
            pipeline = ModelSafePipeline(root / "state.sqlite3", router=fake_router())
            with patch.object(pipeline, "_run_initial_previews", return_value=([], [])) as execute:
                result = pipeline.task_start(raw)
                execute.assert_not_called()
                task = result["task_id"]
                with self.assertRaises(Exception):
                    pipeline.task_resume(task)
                execute.assert_not_called()
                record = {"analysis_id": "real-route-test-fixture", "reference_hashes": [raw["references"][0]["sha256"]], "analysis": {"motion": "radial jets"}}
                record["analysis_hash"] = canonical_sha256(record)
                pipeline.store.put_record(task, "reference_analysis", record["analysis_id"], record)
                pipeline.task_resume(task)
                self.assertEqual(execute.call_args.args[1].metadata["reference_analysis"], {"motion": "radial jets"})
                changed = dict(record)
                changed["analysis"] = {"motion": "tampered"}
                pipeline.store.put_record(task, "reference_analysis", record["analysis_id"], changed)
                with self.assertRaises(Exception):
                    pipeline._spec_with_analysis(task, TaskSpecV2.from_mapping(raw))

    def test_skill_retry_replays_original_result_after_state_transition(self):
        from dcc_task_runtime import RuntimeV2Error
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            pipeline = ModelSafePipeline(database)
            task = drive_to_candidates(pipeline, raw_spec("pyro_smoke_v1", "detail"))
            first = pipeline.model_skill_step(task, {"action_id": "candidate.list"}, "stable-action")
            pipeline.store.transition(task, TaskState.AWAITING_CACHE_APPROVAL, "subsequent state")
            restarted = ModelSafePipeline(database)
            replay = restarted.model_skill_step(task, {"action_id": "candidate.list"}, "stable-action")
            self.assertTrue(replay.pop("replayed"))
            self.assertEqual(first, replay)
            with self.assertRaises(RuntimeV2Error):
                restarted.model_skill_step(task, {"action_id": "task.status"}, "stable-action")
