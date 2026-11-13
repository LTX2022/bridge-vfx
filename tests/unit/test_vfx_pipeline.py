from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from windows_filesystem_fixture import fixture_approval_environment, fixture_denied_permissions, fixture_private_permissions

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.contracts import ArtifactRecord, DomainPackRef, ModelCapabilities, TaskSpecV2
from dcc_task_runtime.errors import PolicyDenied
from dcc_task_runtime.gateways import DeepSeekResponsesPlannerGateway, OpenAICompatibleVisionGateway
from dcc_task_runtime.models import TaskState
from vfx_pipeline.commands import MODEL_SAFE_COMMANDS, TRUSTED_CONTROL_COMMANDS
from vfx_pipeline.paths import load_approval_secret
from vfx_pipeline.planner import PipelinePlanner
from vfx_pipeline.router import BridgeRouter, RouteLeg, RoutingError
from vfx_pipeline.service import ModelSafePipeline, PipelineExecutionError, TrustedApprovalControl


def fake_router(houdini_client=None, nuke_client=None):
    return BridgeRouter(
        discoverers={
            "houdini": lambda: [SimpleNamespace(port=18180, data={"fake": True}, source="test")],
            "nuke": lambda: [SimpleNamespace(port=18190, data={"fake": True}, source="test")],
        },
        client_factories={
            "houdini": lambda _port: houdini_client or SimpleNamespace(),
            "nuke": lambda _port: nuke_client or SimpleNamespace(),
        },
    )


def raw_spec(domain, feedback, *, render=None, references=None, composite=False):
    return {
        "schema_version": "2.0",
        "task_type": "visual.reference_rebuild",
        "intent": "rebuild and causally repair the effect",
        "target": {"application": "pipeline", "scene_mode": "current"},
        "references": references or [],
        "domains": [{"identifier": domain, "version": "1.0.0"}],
        "feedback": feedback,
        "render": render or {},
        "delivery": {"composite": composite},
    }


def drive_to_candidates(pipeline, spec):
    task_id = pipeline.store.create_task(TaskSpecV2.from_mapping(spec))
    pipeline.store.transition(task_id, TaskState.ANALYZING, "test")
    pipeline.store.transition(task_id, TaskState.PREVIEWING, "test")
    pipeline.store.transition(task_id, TaskState.DIAGNOSING, "test")
    pipeline.store.transition(task_id, TaskState.CANDIDATES_READY, "test")
    return task_id


def issue_payload(domain="pyro_smoke_v1", candidate_id="candidate-1"):
    issue = {
        "issue_id": "issue-1",
        "raw_feedback": "烟太模糊",
        "domain": {"identifier": domain, "version": "1.0.0"},
        "component_id": "smoke",
        "dimension": "spatial_detail",
        "direction": "increase",
        "severity": 0.8,
        "confidence": 0.9,
        "roi": None,
        "frame_range": [1, 1, 1],
        "protected_attributes": [],
    }
    hypothesis = {
        "hypothesis_id": "hypothesis-1",
        "issue_id": issue["issue_id"],
        "cause_family": "insufficient_simulation_detail",
        "stage_node_id": "simulation",
        "explanation": "fixed diagnostic evidence supports insufficient detail",
        "evidence_signals": ["detail_frequency"],
        "confounders": [],
        "confidence": 0.8,
        "estimated_cost": "medium",
    }
    candidate = {
        "candidate_id": candidate_id,
        "issue_id": issue["issue_id"],
        "hypothesis_id": hypothesis["hypothesis_id"],
        "cause_family": hypothesis["cause_family"],
        "changes": [{"control": "voxel_size", "previous": 0.1, "proposed": 0.05}],
        "affected_stage_nodes": ["simulation"],
        "invalidates_components": ["smoke"],
        "fixed_seed": 1,
        "estimated_cost": "medium",
        "risk": "bounded",
        "preview_artifact_ids": [],
        "domain": {"identifier": domain, "version": "1.0.0"},
    }
    return issue, hypothesis, candidate


class RoutingAndTemporalTests(unittest.TestCase):
    def test_persisted_route_identity_must_match_exact_discovered_session(self):
        router = fake_router()
        leg = router.route(PipelinePlanner(router=router).registry.get("pyro_smoke_v1", "1.0.0"), include_composite=False)[0]
        self.assertIsNotNone(router.client_for_leg(leg))
        with self.assertRaises(RoutingError):
            router.client_for_leg(
                RouteLeg(
                    leg.application,
                    leg.domain_pack,
                    leg.domain_version,
                    leg.port,
                    leg.purpose,
                    leg.backend_id,
                    leg.protocol,
                    "stale-session",
                )
            )

    def test_persisted_route_without_complete_backend_identity_fails_closed(self):
        with self.assertRaises(RoutingError):
            fake_router().client_for_leg(RouteLeg("houdini", "pyro_smoke_v1", "1.0.0", 18180, "author"))

    def test_explosion_component_dag_is_deterministic(self):
        planner = PipelinePlanner(router=fake_router())
        spec = raw_spec("explosion_composite_v1", "爆炸没力量", composite=True)
        first = planner.plan(spec)
        second = planner.plan(spec)
        branches = first["domains"][0]["component_branches"]
        self.assertEqual([item["branch_id"] for item in branches], ["fire", "smoke", "shockwave", "particles", "rbd", "composite"])
        self.assertEqual(branches[-1]["dependencies"], ["fire", "smoke", "shockwave", "particles", "rbd"])
        self.assertEqual([item["branch_hash"] for item in branches], [item["branch_hash"] for item in second["domains"][0]["component_branches"]])
        self.assertEqual(branches[0]["route"][0]["domain_pack"], "pyro_fire_v1")
        self.assertEqual(branches[-1]["route"][0]["application"], "nuke")

    def test_temporal_feedback_defaults_to_48_frames_but_preserves_explicit_range(self):
        planner = PipelinePlanner(router=fake_router())
        implicit = planner.plan(raw_spec("crowd_agents_v1", "群集太机械"))
        self.assertEqual(implicit["spec"]["render"]["frame_range"], {"start": 1, "end": 48, "step": 1})
        self.assertEqual(implicit["spec"]["render"]["fps"], 24)
        explicit = planner.plan(raw_spec("crowd_agents_v1", "群集太机械", render={"frame_range": {"start": 10, "end": 20, "step": 2}}))
        self.assertEqual(explicit["spec"]["render"]["frame_range"], {"start": 10, "end": 20, "step": 2})


class SourceFreezeTests(unittest.TestCase):
    def test_reference_bytes_are_frozen_and_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.png"
            path.write_bytes(b"reference-v1")
            spec = raw_spec(
                "pyro_smoke_v1",
                "烟太模糊",
                references=[{
                    "asset_id": "ref",
                    "kind": "image",
                    "uri": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }],
            )
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3", router=fake_router())
            task_id = pipeline.store.create_task(TaskSpecV2.from_mapping(spec))
            frozen = pipeline._assert_frozen_sources(task_id)
            self.assertEqual(frozen["references"][0]["sha256"], hashlib.sha256(b"reference-v1").hexdigest())
            path.write_bytes(b"reference-v2")
            with self.assertRaises(PipelineExecutionError):
                pipeline._assert_frozen_sources(task_id)

    def test_explicit_scene_path_is_forwarded_with_its_frozen_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "shot.hip"
            scene.write_bytes(b"hip-bytes")
            scene_hash = hashlib.sha256(scene.read_bytes()).hexdigest()
            spec = TaskSpecV2.from_mapping(
                {
                    **raw_spec("procedural_geometry_v1", "分布太均匀"),
                    "target": {"application": "pipeline", "scene_mode": "existing", "scene_path": str(scene)},
                    "constraints": {"frozen_scene_sha256": scene_hash},
                }
            )
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3", router=fake_router())
            pipeline._freeze_task_sources(spec)
            sub_spec = pipeline._subtask_spec(
                spec,
                RouteLeg("houdini", "procedural_geometry_v1", "1.0.0", 18180, "author", "houdini_legacy_http", "houdini.bridge.http", "houdini_legacy_http:18180"),
                None,
            )
            self.assertEqual(sub_spec["target"]["scene_path"], str(scene))
            self.assertEqual(sub_spec["constraints"]["frozen_scene_sha256"], scene_hash)

    def test_sequence_reference_frames_are_frozen_into_nuke_subtask_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"reference.{frame:04d}.exr" for frame in (1, 2)]
            raw_frames = []
            frozen_reference_frames = []
            for index, (frame, path) in enumerate(zip((1, 2), paths)):
                path.write_bytes(f"reference-{frame}".encode("utf-8"))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                raw_frames.append({"frame": frame, "uri": str(path), "sha256": digest})
                frozen_reference_frames.append(
                    {
                        "index": index,
                        "uri": str(path.resolve()),
                        "sha256": digest,
                        "bytes": path.stat().st_size,
                    }
                )
            reference_manifest_sha = canonical_sha256(frozen_reference_frames)
            spec = TaskSpecV2.from_mapping(
                {
                    **raw_spec(
                        "pyro_smoke_v1",
                        "参考这段烟雾运动",
                        references=[
                            {
                                "asset_id": "sequence-reference",
                                "kind": "sequence",
                                "uri": str(root / "reference.%04d.exr"),
                                "sha256": reference_manifest_sha,
                                "metadata": {"frames": raw_frames},
                            }
                        ],
                        render={"frame_range": {"start": 1, "end": 2, "step": 1}},
                        composite=True,
                    ),
                    "inputs": [
                        {
                            "role": "effect_render",
                            "path": str(paths[0]),
                            "sha256": hashlib.sha256(paths[0].read_bytes()).hexdigest(),
                        }
                    ],
                }
            )
            pipeline = ModelSafePipeline(root / "state.sqlite3", router=fake_router())
            frozen = pipeline._freeze_task_sources(spec)
            self.assertEqual(frozen["references"][0]["sha256"], reference_manifest_sha)
            sub_spec = pipeline._subtask_spec(
                spec,
                RouteLeg("nuke", "nuke_composite_v1", "1.0.0", 18190, "composite", "nuke_bridge", "nuke.bridge.tcp", "nuke_bridge:18190"),
                None,
            )

            reference_input = next(
                item for item in sub_spec["inputs"] if item["role"] == "reference"
            )
            self.assertEqual(reference_input["source_reference_sha256"], reference_manifest_sha)
            self.assertEqual(
                [item["path"] for item in reference_input["frames"]],
                [str(path.resolve()) for path in paths],
            )
            self.assertEqual(
                [item["sha256"] for item in reference_input["frames"]],
                [item["sha256"] for item in raw_frames],
            )
            self.assertTrue(all(item["bytes"] > 0 for item in reference_input["frames"]))
            nuke_manifest = [
                {
                    "index": item["index"],
                    "frame": item["frame"],
                    "uri": item["uri"],
                    "sha256": item["sha256"],
                    "bytes": item["bytes"],
                }
                for item in reference_input["frames"]
            ]
            self.assertEqual(reference_input["sha256"], canonical_sha256(nuke_manifest))

    def test_real_houdini_frames_promote_to_a_nuke_effect_sequence_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for frame in (1, 2, 3):
                path = Path(directory) / f"final.{frame:04d}.exr"
                path.write_bytes(f"frame-{frame}".encode("utf-8"))
                paths.append(path)
            promoted = ModelSafePipeline._effect_input_from_subtask(
                {"result": {"artifacts": [{"path": str(path)} for path in paths]}}
            )
            self.assertIsNotNone(promoted)
            self.assertEqual(promoted["role"], "effect_render")
            self.assertEqual(promoted["path"], str(Path(directory) / "final.%04d.exr"))
            self.assertEqual(promoted["source"], "generated_houdini_artifact")
            self.assertEqual([item["frame"] for item in promoted["frames"]], [1, 2, 3])
            self.assertEqual(
                [item["path"] for item in promoted["frames"]],
                [str(path.resolve()) for path in paths],
            )
            manifest = [
                {
                    "index": item["index"],
                    "frame": item["frame"],
                    "uri": item["uri"],
                    "sha256": item["sha256"],
                    "bytes": item["bytes"],
                }
                for item in promoted["frames"]
            ]
            self.assertEqual(promoted["sha256"], canonical_sha256(manifest))


class FakeTaskService:
    def __init__(self):
        self.specs = []

    def start(self, spec, background=False):
        self.specs.append(spec)
        return {"task_id": f"subtask-{len(self.specs)}", "status": {"state": "SUCCEEDED"}}

    def result(self, _task_id):
        return {
            "state": "SUCCEEDED",
            "artifacts": [],
            "gates": [
                {
                    "name": "bounded_semantic_patch",
                    "passed": True,
                    "cache_subject_hash": "host-subject-hash",
                    "cache_approval_subject": {
                        "cache_output": str(Path(tempfile.gettempdir()).resolve() / "fire.$F4.vdb"),
                        "frame_range": {"start": 1, "end": 48, "step": 1},
                        "seed": 1,
                    },
                }
            ],
        }


class InconclusiveCandidateService:
    def __init__(self):
        self.specs = []

    def start(self, spec, background=False):
        self.specs.append(spec)
        return {"task_id": "b" * 32, "status": {"state": "DIAGNOSIS_INCONCLUSIVE"}}

    def result(self, _task_id):
        return {
            "state": "DIAGNOSIS_INCONCLUSIVE",
            "artifacts": [],
            "gates": [],
            "step_outputs": {
                "fx_build_preview": {
                    "outcome_state": "DIAGNOSIS_INCONCLUSIVE",
                    "output": {"visual_validation": "INCONCLUSIVE"},
                }
            },
        }


class CandidateStateRecoveryTests(unittest.TestCase):
    def test_inconclusive_candidate_preview_returns_parent_to_candidates_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            router = fake_router()
            fake_service = InconclusiveCandidateService()
            planner = PipelinePlanner(router=router)
            pipeline = ModelSafePipeline(
                Path(directory) / "state.sqlite3",
                planner=planner,
                router=router,
                service_factories={"houdini": lambda _client, _root: fake_service},
            )
            spec = raw_spec("pyro_smoke_v1", "烟太模糊")
            task_id = drive_to_candidates(pipeline, spec)
            pipeline.store.put_record(task_id, "plan", "main", planner.plan(spec))
            issue, hypothesis, candidate = issue_payload()
            pipeline.store.put_record(task_id, "issue", issue["issue_id"], issue)
            pipeline.store.put_record(task_id, "hypothesis", hypothesis["hypothesis_id"], hypothesis)
            pipeline.store.put_record(task_id, "candidate", candidate["candidate_id"], candidate)

            with self.assertRaises(PipelineExecutionError) as caught:
                pipeline.candidate_select(task_id, candidate["candidate_id"])

            self.assertEqual(caught.exception.code, "DIAGNOSIS_INCONCLUSIVE")
            self.assertEqual(pipeline.task_status(task_id)["state"], "CANDIDATES_READY")
            selection = pipeline.store.records(task_id, "selection")[-1]
            self.assertEqual(selection["preview_error"]["code"], "DIAGNOSIS_INCONCLUSIVE")
            self.assertEqual(fake_service.specs[0]["constraints"]["fx"]["run_mode"], "candidate_preview")


class ExplosionExecutionTests(unittest.TestCase):
    def test_only_impacted_fire_branch_is_recomputed(self):
        with tempfile.TemporaryDirectory() as directory:
            router = fake_router()
            fake_service = FakeTaskService()
            planner = PipelinePlanner(router=router)
            pipeline = ModelSafePipeline(
                Path(directory) / "state.sqlite3",
                planner=planner,
                router=router,
                service_factories={"houdini": lambda _client, _root: fake_service},
            )
            spec = raw_spec("explosion_composite_v1", "爆炸没力量")
            task_id = drive_to_candidates(pipeline, spec)
            pipeline.store.put_record(task_id, "plan", "main", planner.plan(spec))
            issue, hypothesis, candidate = issue_payload("explosion_composite_v1", "explosion-candidate")
            candidate["changes"] = [{"control": "fire_energy", "previous": 1.0, "proposed": 1.25}]
            candidate["invalidates_components"] = ["fire"]
            pipeline.store.put_record(task_id, "issue", issue["issue_id"], issue)
            pipeline.store.put_record(task_id, "hypothesis", hypothesis["hypothesis_id"], hypothesis)
            pipeline.store.put_record(task_id, "candidate", candidate["candidate_id"], candidate)
            result = pipeline.candidate_select(task_id, candidate["candidate_id"])
            self.assertTrue(result["selection"]["branch_local_recompute"])
            self.assertEqual(result["selection"]["executed_branch_ids"], ["fire"])
            self.assertEqual(len(fake_service.specs), 1)
            fx = fake_service.specs[0]["constraints"]["fx"]
            self.assertEqual(fx["domain_pack"], "pyro_fire_v1")
            self.assertEqual(fx["candidate_patch"], {"burn_rate": 1.25})
            self.assertEqual(pipeline.store.records(task_id, "branch_execution")[-1]["branch_id"], "fire")

    def test_shockwave_uses_its_non_simulation_branch_without_cache_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            router = fake_router()
            fake_service = FakeTaskService()
            planner = PipelinePlanner(router=router)
            pipeline = ModelSafePipeline(
                Path(directory) / "state.sqlite3",
                planner=planner,
                router=router,
                service_factories={"houdini": lambda _client, _root: fake_service},
            )
            spec = raw_spec("explosion_composite_v1", "爆炸没力量")
            task_id = drive_to_candidates(pipeline, spec)
            pipeline.store.put_record(task_id, "plan", "main", planner.plan(spec))
            issue, hypothesis, candidate = issue_payload("explosion_composite_v1", "shockwave-candidate")
            candidate["changes"] = [{"control": "shockwave_scale", "previous": 1.0, "proposed": 1.5}]
            pipeline.store.put_record(task_id, "candidate", candidate["candidate_id"], candidate)
            result = pipeline.candidate_select(task_id, candidate["candidate_id"])
            self.assertEqual(result["status"]["state"], "VERIFYING")
            self.assertTrue(result["selection"]["branch_local_recompute"])
            self.assertFalse(result["selection"]["requires_simulation_cache"])
            self.assertEqual(result["selection"]["executed_branch_ids"], ["shockwave"])
            self.assertEqual(fake_service.specs[0]["constraints"]["fx"]["candidate_patch"], {"scale": 1.5})

    def test_partially_mapped_explosion_candidate_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            router = fake_router()
            fake_service = FakeTaskService()
            planner = PipelinePlanner(router=router)
            pipeline = ModelSafePipeline(
                Path(directory) / "state.sqlite3",
                planner=planner,
                router=router,
                service_factories={"houdini": lambda _client, _root: fake_service},
            )
            spec = raw_spec("explosion_composite_v1", "爆炸没力量")
            task_id = drive_to_candidates(pipeline, spec)
            pipeline.store.put_record(task_id, "plan", "main", planner.plan(spec))
            _issue, _hypothesis, candidate = issue_payload("explosion_composite_v1", "partial-candidate")
            candidate["changes"] = [
                {"control": "fire_energy", "previous": 1.0, "proposed": 1.25},
                {"control": "shockwave_thickness", "previous": 1.0, "proposed": 2.0},
            ]
            pipeline.store.put_record(task_id, "candidate", candidate["candidate_id"], candidate)
            result = pipeline.candidate_select(task_id, candidate["candidate_id"])
            self.assertEqual(result["status"]["state"], "PARTIAL")
            self.assertFalse(result["selection"]["branch_local_recompute"])
            self.assertEqual(result["selection"]["unrouted_controls"], ["shockwave_thickness"])
            self.assertEqual(fake_service.specs, [])


class VerificationSecurityTests(unittest.TestCase):
    def _pipeline(self, directory):
        pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3", router=fake_router())
        spec = raw_spec("pyro_smoke_v1", "烟太模糊")
        task_id = drive_to_candidates(pipeline, spec)
        issue, hypothesis, candidate = issue_payload()
        pipeline.store.put_record(task_id, "issue", issue["issue_id"], issue)
        pipeline.store.put_record(task_id, "hypothesis", hypothesis["hypothesis_id"], hypothesis)
        pipeline.store.put_record(task_id, "candidate", candidate["candidate_id"], candidate)
        pipeline.store.put_record(task_id, "selection", "current", {"candidate": candidate})
        pipeline.store.transition(task_id, TaskState.VERIFYING, "test verification")
        return pipeline, task_id

    @staticmethod
    def _artifact(pipeline, task_id, path, artifact_id):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pipeline.store.add_artifact(
            ArtifactRecord(
                artifact_id=artifact_id,
                task_id=task_id,
                kind="diagnostic_metric_json",
                uri=str(path),
                sha256=digest,
                domain=DomainPackRef("pyro_smoke_v1", "1.0.0"),
                component_id="smoke",
                stage_node_id="verification",
            )
        )

    def test_accept_result_only_consumes_existing_untampered_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline, task_id = self._pipeline(directory)
            before = Path(directory) / "before.json"
            after = Path(directory) / "after.json"
            before.write_text(json.dumps({"raster": [[0, 0], [0, 0]]}), encoding="utf-8")
            after.write_text(json.dumps({"raster": [[0, 1], [1, 0]]}), encoding="utf-8")
            self._artifact(pipeline, task_id, before, "before")
            self._artifact(pipeline, task_id, after, "after")
            record = pipeline.verification_record(task_id, {"before_artifact_id": "before", "after_artifact_id": "after", "metric_kind": "raster"})
            trusted = TrustedApprovalControl(pipeline)
            with patch.dict(os.environ, {"HOUDINI_BRIDGE_APPROVAL_SECRET": "v" * 64}, clear=True):
                proof = trusted.sign_proof(
                    "artist",
                    "final_result_acceptance",
                    f"{task_id}:{record['verification_id']}",
                )
                with self.assertRaises(PipelineExecutionError):
                    trusted.accept_result(task_id, "artist", proof, record["verification_id"], "forged")
                acceptance = trusted.accept_result(task_id, "artist", proof, record["verification_id"], record["verification_hash"])
            self.assertEqual(acceptance["technical_verification_id"], record["verification_id"])
            self.assertTrue(acceptance["experience"]["user_confirmed"])

    def test_missing_and_tampered_artifacts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline, task_id = self._pipeline(directory)
            with self.assertRaises(PipelineExecutionError):
                pipeline.verification_record(task_id, {"before_artifact_id": "missing", "after_artifact_id": "missing"})
            before = Path(directory) / "before.json"
            after = Path(directory) / "after.json"
            before.write_text(json.dumps({"raster": [[0, 0], [0, 0]]}), encoding="utf-8")
            after.write_text(json.dumps({"raster": [[0, 1], [1, 0]]}), encoding="utf-8")
            self._artifact(pipeline, task_id, before, "before")
            self._artifact(pipeline, task_id, after, "after")
            record = pipeline.verification_record(task_id, {"before_artifact_id": "before", "after_artifact_id": "after"})
            after.write_text(json.dumps({"raster": [[9, 9], [9, 9]]}), encoding="utf-8")
            trusted = TrustedApprovalControl(pipeline)
            with patch.dict(os.environ, {"HOUDINI_BRIDGE_APPROVAL_SECRET": "v" * 64}, clear=True):
                proof = trusted.sign_proof(
                    "artist",
                    "final_result_acceptance",
                    f"{task_id}:{record['verification_id']}",
                )
                with self.assertRaises(PipelineExecutionError):
                    trusted.accept_result(task_id, "artist", proof, record["verification_id"], record["verification_hash"])

    @unittest.skipUnless(shutil.which("magick"), "ImageMagick is required for the real raster decoder test")
    def test_real_raster_artifacts_are_sampled_without_json_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline, task_id = self._pipeline(directory)
            before = Path(directory) / "before.png"
            after = Path(directory) / "after.png"
            before.write_text("P2\n4 4\n255\n" + " ".join(["0"] * 16) + "\n", encoding="ascii")
            after.write_text(
                "P2\n4 4\n255\n" + " ".join("255" if (index + index // 4) % 2 else "0" for index in range(16)) + "\n",
                encoding="ascii",
            )
            self._artifact(pipeline, task_id, before, "before-raster")
            self._artifact(pipeline, task_id, after, "after-raster")
            record = pipeline.verification_record(
                task_id,
                {
                    "before_artifact_id": "before-raster",
                    "after_artifact_id": "after-raster",
                    "metric_kind": "raster",
                    "minimum_delta": 0.001,
                },
            )
            self.assertTrue(record["scorecard"]["target_improved"])
            self.assertIn("imagemagick_txt_gray_v1", record["scorecard"]["notes"][0])


class FakePlannerGateway:
    def __init__(self):
        self.plan_calls = 0
        self.last_tools = []

    def probe_capabilities(self):
        return ModelCapabilities("fake-deepseek", "deepseek-v4-flash", ("text",), True, True, 1)

    def plan(self, _context, tools):
        self.plan_calls += 1
        self.last_tools = [item["name"] for item in tools]
        return {"tool": "task.status", "arguments": {}, "reason": "inspect durable state"}


class FakeVisionGateway:
    def __init__(self):
        self.analyze_calls = 0

    def probe_capabilities(self):
        return ModelCapabilities("fake-vision", "hy3", ("text", "image"), True, False, 0)

    def analyze(self, references, _context):
        self.analyze_calls += 1
        return {"components": [{"label": "smoke", "confidence": 0.9}], "reference_count": len(references)}


class FakeDeepSeekTransport:
    def __init__(self):
        self.calls = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        names = [item["name"] for item in payload.get("tools") or []]
        name = "capability_echo" if "capability_echo" in names else "task.status"
        arguments = {"ok": True} if name == "capability_echo" else {}
        return {"output": [{"type": "function_call", "name": name, "arguments": json.dumps(arguments)}]}


class FakeVisionTransport:
    def __init__(self):
        self.calls = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        analysis = {
            "components": [{
                "component_id": "smoke",
                "label": "smoke",
                "roi": [0.0, 0.0, 1.0, 1.0],
                "observations": {"spatial_detail": "soft"},
                "confidence": 0.9,
            }],
            "global_observations": {"motion_clues": "unknown_from_still"},
            "confidence": 0.9,
        }
        return {"choices": [{"message": {"content": json.dumps(analysis)}}]}


class ModelIntegrationTests(unittest.TestCase):
    def test_model_probe_accepts_bounded_mediated_action_contract_without_native_tools(self):
        gateway = SimpleNamespace(
            probe_capabilities=lambda: ModelCapabilities(
                provider="doubao-desktop",
                model="DoubaoDesktopRoute",
                input_modalities=("text",),
                strict_json=True,
                tool_calls=False,
                max_tool_calls_per_turn=1,
                action_mode="structured_text_mediated",
                route_identity={"route_id": "DoubaoDesktopRoute"},
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            result = ModelSafePipeline(Path(directory) / "state.sqlite3", router=fake_router()).model_probe(
                {}, planner_gateway=gateway
            )
        self.assertFalse(result["planner"]["tool_calls"])
        self.assertEqual(result["planner"]["action_mode"], "structured_text_mediated")

    def test_model_step_persists_reference_analysis_and_executes_one_safe_action(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3", router=fake_router())
            reference_path = Path(directory) / "reference.png"
            reference_path.write_bytes(b"fake-image")
            spec = raw_spec(
                "pyro_smoke_v1",
                "烟太模糊",
                references=[{
                    "asset_id": "ref",
                    "kind": "image",
                    "uri": str(reference_path),
                    "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                }],
            )
            task_id = pipeline.store.create_task(TaskSpecV2.from_mapping(spec))
            pipeline.store.transition(task_id, TaskState.ANALYZING, "test")
            pipeline.store.transition(task_id, TaskState.AWAITING_INPUT, "test")
            planner, vision = FakePlannerGateway(), FakeVisionGateway()
            result = pipeline.model_step(task_id, {}, planner_gateway=planner, vision_gateway=vision, request_id="turn-1")
            self.assertEqual(planner.plan_calls, 1)
            self.assertEqual(vision.analyze_calls, 1)
            self.assertEqual(result["action"]["tool"], "task.status")
            self.assertEqual(result["action"]["executed_via"], "SkillIR")
            self.assertEqual(result["action_result"]["state"], "AWAITING_INPUT")
            self.assertTrue(pipeline.store.records(task_id, "reference_analysis"))
            self.assertFalse(set(planner.last_tools) & TRUSTED_CONTROL_COMMANDS)
            self.assertEqual(len(pipeline.store.records(task_id, "model_step")), 1)
            self.assertEqual(len(pipeline.store.records(task_id, "skill_vm")), 1)

    def test_model_probe_and_step_use_concrete_gateways_with_fake_transports(self):
        with tempfile.TemporaryDirectory() as directory:
            reference_path = Path(directory) / "reference.png"
            reference_path.write_bytes(b"fake-image")
            spec = raw_spec(
                "pyro_smoke_v1",
                "烟太模糊",
                references=[{
                    "asset_id": "ref",
                    "kind": "image",
                    "uri": str(reference_path),
                    "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                }],
            )
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3", router=fake_router())
            task_id = pipeline.store.create_task(TaskSpecV2.from_mapping(spec))
            pipeline.store.transition(task_id, TaskState.ANALYZING, "test")
            pipeline.store.transition(task_id, TaskState.AWAITING_INPUT, "test")
            stored_spec = TaskSpecV2.from_mapping(pipeline.store.get_task(task_id)["spec"])
            deep_transport, vision_transport = FakeDeepSeekTransport(), FakeVisionTransport()
            planner_gateway = DeepSeekResponsesPlannerGateway("planner-secret", transport=deep_transport)
            vision_gateway = OpenAICompatibleVisionGateway(
                "vision-secret", transport=vision_transport, probe_references=stored_spec.references
            )
            capabilities = pipeline.model_probe(
                {}, task_id, planner_gateway=planner_gateway, vision_gateway=vision_gateway
            )
            result = pipeline.model_step(
                task_id, {}, planner_gateway=planner_gateway, vision_gateway=vision_gateway, request_id="turn-1"
            )
            self.assertEqual(capabilities["planner"]["model"], "deepseek-v4-flash")
            self.assertEqual(result["action"]["tool"], "task.status")
            self.assertGreaterEqual(len(deep_transport.calls), 2)
            self.assertGreaterEqual(len(vision_transport.calls), 2)
            persisted = json.dumps(
                {
                    "caps": pipeline.store.records(task_id, "model_capabilities"),
                    "steps": pipeline.store.records(task_id, "model_step"),
                    "analysis": pipeline.store.records(task_id, "reference_analysis"),
                }
            )
            self.assertNotIn("planner-secret", persisted)
            self.assertNotIn("vision-secret", persisted)

    def test_trusted_commands_are_disjoint_from_model_surface(self):
        self.assertFalse(MODEL_SAFE_COMMANDS & TRUSTED_CONTROL_COMMANDS)
        self.assertNotIn("approval.accept-result", MODEL_SAFE_COMMANDS)
        self.assertNotIn("model.step", MODEL_SAFE_COMMANDS)


class SharedSecretTests(unittest.TestCase):
    def test_private_shared_key_and_direct_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "approval.key"
            path.write_text("a" * 64, encoding="utf-8")
            fixture_private_permissions(path)
            with patch.dict(os.environ, {"BRIDGE_SKILLS_APPROVAL_SECRET_FILE": str(path)}, clear=True):
                self.assertEqual(load_approval_secret(), "a" * 64)
            with patch.dict(os.environ, {"HOUDINI_BRIDGE_APPROVAL_SECRET": "b" * 64}, clear=True):
                self.assertEqual(load_approval_secret(), "b" * 64)
            if os.name != "nt":
                path.chmod(0o644)
            with fixture_denied_permissions(path), patch.dict(os.environ, {"BRIDGE_SKILLS_APPROVAL_SECRET_FILE": str(path)}, clear=True):
                with self.assertRaises(PolicyDenied):
                    load_approval_secret()


class FakeCacheClient:
    def __init__(self, artifacts):
        self.calls = []
        self.artifacts = list(artifacts)

    def call(self, command, params):
        self.calls.append((command, params))
        return {
            "cached": True,
            "cache": {"state": "COMPLETE"},
            "artifacts": [{"path": str(path)} for path in self.artifacts],
            "gates": [{"name": "approved_simulation_cache", "passed": True, "kind": "verification"}],
        }


class CacheAssertionTests(unittest.TestCase):
    def test_cache_dispatch_requires_grant_and_uses_signature_not_boolean_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_pattern = str(Path(directory) / "fake-cache.$F4.vdb")
            cache_paths = []
            for frame in range(1, 49):
                path = Path(cache_pattern.replace("$F4", f"{frame:04d}"))
                path.write_bytes(f"cache-{frame}".encode("utf-8"))
                cache_paths.append(path)
            client = FakeCacheClient(cache_paths)
            router = fake_router(houdini_client=client)
            pipeline = ModelSafePipeline(Path(directory) / "state.sqlite3", router=router)
            spec = raw_spec("pyro_smoke_v1", "烟太模糊")
            task_id = drive_to_candidates(pipeline, spec)
            _issue, _hypothesis, candidate = issue_payload()
            sub_spec = {
                "intent": "smoke cache",
                "target": {"application": "houdini", "scene_mode": "current"},
                "inputs": [],
                "constraints": {"fx": {"domain_pack": "pyro_smoke_v1", "candidate_patch": {"voxel_size": 0.05}}},
                "render": {"frame_range": {"start": 1, "end": 48, "step": 1}},
                "delivery": {},
            }
            selection = {
                "candidate": candidate,
                "requires_simulation_cache": True,
                "houdini_patch": {"voxel_size": 0.05},
                "dcc_preview": {
                    "subtask_id": "houdini-subtask",
                    "port": 18180,
                    "backend_id": "houdini_legacy_http",
                    "protocol": "houdini.bridge.http",
                    "session": "houdini_legacy_http:18180",
                    "spec": sub_spec,
                },
                "host_cache_subject": {
                    "subject_hash": "exact-host-subject",
                    "subject": {
                        "input_digest": "input-hash",
                        "scene": {"fingerprint": "scene"},
                        "frame_range": {"start": 1, "end": 48, "step": 1},
                        "seed": 1,
                        "houdini_version": "fake-21",
                        "cache_output": cache_pattern,
                        "related_nodes": ["/obj/smoke"],
                    },
                },
            }
            pipeline.store.put_record(task_id, "selection", "current", selection)
            TrustedApprovalControl(pipeline).configure_cache_resources(
                task_id, task_roots=[Path(directory)], estimated_bytes=1024,
                max_disk_bytes=1024 * 1024, max_seconds=120, simulation_start_frame=1, invalidation_scope=["smoke.simulation", "render"])
            request = pipeline.approval_request_cache(task_id)
            with self.assertRaises((PolicyDenied, KeyError)):
                pipeline.cache_run(task_id, "forged-grant")
            secret_file = Path(directory) / "approval.key"
            secret_file.write_text("s" * 64, encoding="utf-8")
            fixture_private_permissions(secret_file)
            with patch.dict(os.environ, fixture_approval_environment(secret_file), clear=True):
                trusted = TrustedApprovalControl(pipeline)
                proof = trusted.sign_proof(
                    "artist",
                    "houdini_simulation_cache",
                    request["request_id"],
                )
                grant = trusted.grant_cache(request["request_id"], "artist", proof)
                result = pipeline.cache_run(task_id, grant["grant_id"])
            self.assertEqual(result["status"]["state"], "VERIFYING")
            sent = client.calls[-1][1]["constraints"]["fx"]
            self.assertNotIn("trusted", sent)
            self.assertNotIn("trusted_control_plane", sent)
            assertion = sent["approval"]
            self.assertEqual(assertion["purpose"], "houdini_simulation_cache")
            self.assertEqual(assertion["subject_hash"], "exact-host-subject")
            self.assertTrue(assertion["signature"])
            cached = [item for item in pipeline.store.artifacts(task_id) if item["kind"] == "houdini_simulation_cache"]
            self.assertEqual(len(cached), 48)
            self.assertTrue(all(item["sha256"] for item in cached))


if __name__ == "__main__":
    unittest.main()
