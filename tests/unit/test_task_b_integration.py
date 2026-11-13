from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from dcc_task_runtime.contracts import TaskSpecV2
from dcc_task_runtime.models import ErrorCode
from dcc_task_runtime.visual_objective import MediaManifest, VisualObjective
from houdini_bridge.recipes import ReferenceEffectRecipe
from vfx_pipeline.graph_jobs import GraphJobService
from vfx_pipeline.router import RouteLeg
from vfx_pipeline.service import ModelSafePipeline, PipelineExecutionError, TrustedExecutionControl
from vfx_pipeline.task_graph import TaskGraphCoordinator
from vfx_pipeline.workbuddy_graph_mcp import GraphRun
from test_vfx_pipeline import fake_router, raw_spec


REPO = Path(__file__).resolve().parents[2]


def proposal(radius: float = 1.0) -> dict:
    return {
        "schema_version": "1.0",
        "nodes": [{
            "node_id": "sphere",
            "node_type": "sop.sphere",
            "context": "houdini_sop",
            "parameters": {"radx": radius, "rady": 1.0, "radz": 1.0},
        }],
        "outputs": [{"output_id": "out", "node_id": "sphere", "port": "geometry"}],
    }


def ready_analysis(spread: float) -> dict:
    return {
        "components": [{
            "component_id": "smoke",
            "label": "smoke",
            "roi": [0, 0, 1, 1],
            "confidence": 0.9,
            "observations": {
                "emission_start": 1,
                "emission_end": 60,
                "direction": [0, 1, 0],
                "spread_angle": spread,
                "speed_tier": "fast",
                "body_scale": 1,
                "ground_spread": 2,
                "protected_features": ["outline"],
            },
        }],
        "global_observations": {"time_range": {"start": 1, "end": 180, "step": 1}},
        "confidence": 0.9,
    }


class TaskB1GraphIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pipeline = ModelSafePipeline(self.root / "pipeline.sqlite3")
        self.task_a = self.pipeline.store.create_task(raw_spec("pyro_smoke_v1", "synthetic graph A"))
        self.task_b = self.pipeline.store.create_task(raw_spec("pyro_smoke_v1", "synthetic graph B"))
        self.starts = 0

        def fake_host(_job):
            self.starts += 1
            return {"construction_executed": True}

        self.jobs = GraphJobService(
            self.root / "jobs-a", REPO, "FAKE_HOST_ONLY",
            scheduler_root=self.root / "installation-slot", worker_factory=fake_host,
        )
        self.addCleanup(self.jobs.close)
        self.coordinator = TaskGraphCoordinator(
            self.pipeline, self.task_a, self.jobs,
            run_id="synthetic-run-a", session_id="synthetic-session-a", construction_authorized=True,
        )

    def test_main_and_lower_registry_share_canonical_graph_id_and_cross_task_is_rejected(self):
        result = self.coordinator.propose(proposal(), "proposal-1")
        self.assertTrue(self.jobs.has_graph(result["graph_id"]))
        main = self.pipeline._registered_graph(self.task_a, result["graph_id"])
        self.assertEqual(result["graph_id"], main["graph_id"])
        self.assertTrue(main["legacy_graph_ids"])
        other = TaskGraphCoordinator(
            self.pipeline, self.task_b, self.jobs,
            run_id="synthetic-run-b", construction_authorized=True,
        )
        with self.assertRaises(PipelineExecutionError):
            other.trial(result["graph_id"], "trial-cross-task")

    def test_same_graph_accepts_distinct_request_ids_but_each_request_is_content_immutable(self):
        first = self.coordinator.propose(proposal(), "proposal-a")
        second = self.coordinator.propose(proposal(), "proposal-b")
        replay = self.coordinator.propose(proposal(), "proposal-a")
        self.assertEqual(first["graph_id"], second["graph_id"])
        self.assertEqual(first["graph_id"], replay["graph_id"])
        with self.assertRaises(PipelineExecutionError):
            self.coordinator.propose(proposal(radius=2.0), "proposal-a")

    def test_success_semantics_parent_stage_and_cold_restart_are_consistent(self):
        graph_id = self.coordinator.propose(proposal(), "proposal-status")["graph_id"]
        result = self.coordinator.trial(graph_id, "trial-status")
        operation_id = result["operation_id"]
        deadline = time.time() + 3
        while not result["terminal"] and time.time() < deadline:
            time.sleep(0.01)
            result = self.coordinator.status(operation_id)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertTrue(result["success"])
        self.assertTrue(result["completed"])
        self.assertTrue(result["terminal"])
        self.assertEqual(result["stopped"], result["stop_confirmed"])
        self.assertEqual(result["parent_status"]["state"], "AWAITING_INPUT")
        before_events = len(self.pipeline.store.records(self.task_a, "graph_construction_event"))
        replay = self.coordinator.status(operation_id)
        self.assertEqual(replay["state"], "SUCCEEDED")
        self.assertEqual(len(self.pipeline.store.records(self.task_a, "graph_construction_event")), before_events)

        reopened = ModelSafePipeline(self.root / "pipeline.sqlite3")
        restarted = TaskGraphCoordinator(
            reopened, self.task_a, self.jobs, run_id="synthetic-run-a",
            session_id="synthetic-session-a", construction_authorized=True,
        )
        cold = restarted.status(operation_id)
        self.assertEqual(cold["state"], "SUCCEEDED")
        self.assertEqual(cold["parent_status"]["state"], "AWAITING_INPUT")
        self.assertEqual(len(reopened.store.records(self.task_a, "graph_construction_event")), before_events)

    def test_late_lower_result_advances_persistent_stage_without_resubmission(self):
        gate = threading.Event()
        starts = {"count": 0}
        def delayed(_job):
            starts["count"] += 1
            gate.wait(timeout=3)
            return {"construction_executed": True}
        jobs = GraphJobService(
            self.root / "jobs-late", REPO, "FAKE_HOST_ONLY",
            scheduler_root=self.root / "installation-slot-late", worker_factory=delayed,
        )
        self.addCleanup(gate.set); self.addCleanup(jobs.close)
        coordinator = TaskGraphCoordinator(
            self.pipeline, self.task_b, jobs, run_id="synthetic-run-late",
            session_id="synthetic-session-late", construction_authorized=True,
        )
        graph_id = coordinator.propose(proposal(), "proposal-late")["graph_id"]
        first = coordinator.trial(graph_id, "trial-late")
        self.assertFalse(first["terminal"])
        self.assertFalse(first["success"])
        self.assertFalse(first["completed"])
        self.assertEqual(first["parent_status"]["state"], "ANALYZING")
        operation_id = first["operation_id"]
        gate.set()
        result = first
        deadline = time.time() + 3
        while not result["terminal"] and time.time() < deadline:
            time.sleep(0.01)
            result = coordinator.status(operation_id)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(result["parent_status"]["state"], "AWAITING_INPUT")
        self.assertEqual(starts["count"], 1)
        replay = coordinator.status(operation_id)
        self.assertEqual(replay["operation_id"], operation_id)
        self.assertEqual(starts["count"], 1)

    def test_cancel_not_stopped_remains_reconciliation_required_in_parent(self):
        gate = threading.Event()
        def delayed(_job):
            gate.wait(timeout=3)
            return {"construction_executed": True}
        jobs = GraphJobService(
            self.root / "jobs-cancel", REPO, "FAKE_HOST_ONLY",
            scheduler_root=self.root / "installation-slot-cancel", worker_factory=delayed,
        )
        self.addCleanup(gate.set); self.addCleanup(jobs.close)
        coordinator = TaskGraphCoordinator(
            self.pipeline, self.task_b, jobs, run_id="synthetic-run-cancel",
            session_id="synthetic-session-cancel", construction_authorized=True,
        )
        graph_id = coordinator.propose(proposal(), "proposal-cancel")["graph_id"]
        first = coordinator.trial(graph_id, "trial-cancel")
        operation_id = first["operation_id"]
        original_cancel = jobs.cancel
        def unconfirmed(op):
            current = dict(jobs.status(op))
            current.update({
                "state": "RECONCILIATION_REQUIRED", "cancellation_requested": True,
                "stop_confirmed": False, "reconciliation_required": True,
                "error_code": "STOP_UNCONFIRMED",
            })
            return current
        jobs.cancel = unconfirmed
        try:
            cancelled = coordinator.cancel(operation_id)
        finally:
            jobs.cancel = original_cancel
        self.assertEqual(cancelled["state"], "RECONCILIATION_REQUIRED")
        self.assertFalse(cancelled["success"])
        self.assertFalse(cancelled["completed"])
        self.assertFalse(cancelled["terminal"])
        self.assertFalse(cancelled["stopped"])
        self.assertEqual(cancelled["parent_status"]["state"], "DIAGNOSING")
        gate.set()
        result = cancelled
        deadline = time.time() + 3
        while result["state"] != "SUCCEEDED" and time.time() < deadline:
            time.sleep(0.01)
            result = coordinator.status(operation_id)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(result["parent_status"]["state"], "AWAITING_INPUT")

    def test_duplicate_trial_reuses_operation_and_request_content_is_immutable(self):
        first_graph = self.coordinator.propose(proposal(), "proposal-1")["graph_id"]
        first = self.coordinator.trial(first_graph, "trial-1")
        replay = self.coordinator.trial(first_graph, "trial-1")
        self.assertEqual(first["operation_id"], replay["operation_id"])
        deadline = time.time() + 2
        while self.starts < 1 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.starts, 1)
        second_graph = self.coordinator.propose(proposal(radius=2.0), "proposal-2")["graph_id"]
        with self.assertRaises(PipelineExecutionError):
            self.coordinator.trial(second_graph, "trial-1")

    def test_concurrent_same_trial_request_executes_at_most_once(self):
        graph_id = self.coordinator.propose(proposal(), "proposal-concurrent")["graph_id"]
        barrier = threading.Barrier(2)
        operations = []
        failures = []

        def invoke():
            try:
                barrier.wait(timeout=2)
                operations.append(self.coordinator.trial(graph_id, "trial-concurrent")["operation_id"])
            except Exception as exc:  # one caller may lose the non-blocking task lock
                failures.append(exc)

        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertTrue(operations)
        if len(operations) == 2:
            self.assertEqual(operations[0], operations[1])
        deadline = time.time() + 2
        while self.starts < 1 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.starts, 1)
        self.assertLessEqual(len(set(operations)), 1)
        self.assertLessEqual(len(failures), 1)

    def test_recovery_finds_lower_commit_without_minting_new_operation(self):
        graph_id = self.coordinator.propose(proposal(), "proposal-1")["graph_id"]
        request_id = "trial-crash-window"
        graph = self.pipeline._registered_graph(self.task_a, graph_id)
        binding = self.coordinator._binding_record(graph_id)
        request_hash = __import__("dcc_task_runtime.canonical", fromlist=["canonical_sha256"]).canonical_sha256({
            "task_id": self.task_a,
            "graph_id": graph_id,
            "graph_digest": graph["graph_digest"],
            "source_manifest_hash": graph["source_manifest_hash"],
            "binding_hash": binding["binding_hash"],
            "run_id": self.coordinator.run_id,
            "session_id": self.coordinator.session_id,
            "request_id": request_id,
        })
        intent_id = "intent_" + __import__("dcc_task_runtime.canonical", fromlist=["canonical_sha256"]).canonical_sha256({"task_id": self.task_a, "request_id": request_id})
        # Simulate crash point 1: main intent committed, lower submission absent.
        self.pipeline.store.put_record(self.task_a, "graph_trial_intent", intent_id, {
            "schema": "bridge.task-graph-trial-intent/1.0", "intent_id": intent_id,
            "task_id": self.task_a, "graph_id": graph_id, "graph_digest": graph["graph_digest"],
            "request_id": request_id, "request_hash": request_hash, "run_id": self.coordinator.run_id,
            "session_id": self.coordinator.session_id, "source_manifest_hash": graph["source_manifest_hash"],
            "binding_hash": binding["binding_hash"], "operation_id": None,
            "lower_trial_request_sha256": __import__("dcc_task_runtime.canonical", fromlist=["canonical_sha256"]).canonical_sha256(self.coordinator._lower_trial_request(request_id)),
            "state": "INTENT_RECORDED", "created_at": "software-test",
        })
        first = self.coordinator.trial(graph_id, request_id)
        # Simulate crash point 2 by erasing only the main receipt pointer while
        # leaving the lower durable request committed; recovery must discover it.
        row = next(row for row in self.pipeline.store.records(self.task_a, "graph_trial_intent") if row["intent_id"] == intent_id)
        row = dict(row); row["operation_id"] = None; row["state"] = "INTENT_RECORDED"
        self.pipeline.store.put_record(self.task_a, "graph_trial_intent", intent_id, row)
        recovered = self.coordinator.trial(graph_id, request_id)
        self.assertEqual(first["operation_id"], recovered["operation_id"])
        # Crash point 3: a normal replay after the main receipt also keeps ID.
        replay = self.coordinator.trial(graph_id, request_id)
        self.assertEqual(first["operation_id"], replay["operation_id"])

    def test_controller_directory_drift_is_fail_closed(self):
        graph_id = self.coordinator.propose(proposal(), "proposal-1")["graph_id"]
        other_jobs = GraphJobService(
            self.root / "jobs-drift", REPO, "FAKE_HOST_ONLY",
            scheduler_root=self.root / "installation-slot", worker_factory=lambda job: {},
        )
        self.addCleanup(other_jobs.close)
        drifted = TaskGraphCoordinator(
            self.pipeline, self.task_a, other_jobs,
            run_id="synthetic-run-a", session_id="synthetic-session-a", construction_authorized=True,
        )
        with self.assertRaises(PipelineExecutionError):
            drifted.trial(graph_id, "trial-drift")


class TaskB2ReferenceEvidenceTests(unittest.TestCase):
    def make_pipeline(self, name: str, data: bytes):
        root = self.root / name
        root.mkdir()
        ref = root / "synthetic.png"
        ref.write_bytes(data)
        spec = raw_spec("pyro_smoke_v1", "same fixed text", references=[{
            "asset_id": "ref", "kind": "image", "uri": str(ref),
            "sha256": hashlib.sha256(data).hexdigest(),
        }])
        pipeline = ModelSafePipeline(root / "state.sqlite3", router=fake_router())
        task = pipeline.task_start(spec)["task_id"]
        return pipeline, task, spec, ref

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def register(self, pipeline, task, analysis, run_id="run-1", session_id="session-1"):
        control = TrustedExecutionControl(pipeline)
        observation = {"description": "synthetic connector observation"}
        connector = control.register_connector_observation(
            task, run_id=run_id, session_id=session_id, asset_id="ref", observation=observation,
            connector_receipt={
                "run_id": run_id, "asset_id": "ref", "request_id": "observe-ref",
                "receipt": {"seq": 1, "event_hash": "a" * 64},
                "observation_recorded": True, "dcc_dispatched": False,
            },
        )
        envelope = {
            "schema": "bridge.workbuddy.reference_analysis_response/1.0",
            "route_id": "WorkBuddyDesktopRoute", "selected_model": "HY3",
            "run_id": run_id, "session_id": session_id, "tool_call_id": "fake-host-tool-1",
            "observation_record_ids": [connector["record_id"]], "analysis": analysis,
        }
        capture = control.capture_reference_analysis_response(
            task, run_id=run_id, session_id=session_id, raw_response=json.dumps(envelope, sort_keys=True),
            config={"route": "synthetic-test"},
        )
        registered = control.register_reference_analysis_run(
            task, run_id=run_id, session_id=session_id, analysis=analysis,
            capture_id=capture["capture_id"], config={"route": "synthetic-test"},
        )
        return control, registered, capture

    def test_trusted_controller_receipt_unlocks_route_but_not_provider_identity(self):
        pipeline, task, spec, _ = self.make_pipeline("one", b"reference-one")
        analysis = ready_analysis(30)
        control, registered, capture = self.register(pipeline, task, analysis)
        self.assertTrue(registered["route_execution_verified"])
        self.assertFalse(registered["provider_identity_verified"])
        replay = control.register_reference_analysis_run(
            task, run_id="run-1", session_id="session-1", analysis=analysis,
            capture_id=capture["capture_id"], config={"route":"synthetic-test"},
        )
        self.assertTrue(replay["replayed"])
        pipeline.reference_analysis_submit(task, analysis, run_id="run-1", request_id="obs-1")
        bound = pipeline._spec_with_analysis(task, TaskSpecV2.from_mapping(spec))
        self.assertTrue(bound.metadata["external_analysis_execution_verified"])
        self.assertFalse(bound.metadata["provider_identity_verified"])

    def test_forged_receipt_and_reference_drift_are_rejected(self):
        pipeline, task, spec, ref = self.make_pipeline("one", b"reference-one")
        analysis = ready_analysis(30)
        control = TrustedExecutionControl(pipeline)
        contract = control.reference_analysis_receipt_contract(task, run_id="run-1", session_id="session-1", analysis=analysis)
        with self.assertRaises(PipelineExecutionError):
            control.register_reference_analysis_run(task, run_id="run-1", session_id="session-1", analysis=analysis, tool_receipt={
                "tool_call_id": "fake-host-tool-1", "input_sha256": "0" * 64,
                "output_sha256": contract["output_sha256"], "provider_response_sha256": "1" * 64,
            })
        self.register(pipeline, task, analysis)
        pipeline.reference_analysis_submit(task, analysis, run_id="run-1", request_id="obs-1")
        ref.write_bytes(b"changed-reference")
        with self.assertRaises(PipelineExecutionError):
            pipeline._spec_with_analysis(task, TaskSpecV2.from_mapping(spec))

    def test_graph_run_connector_observation_requires_controlled_capture_before_route_verification(self):
        png = b"\x89PNG\r\n\x1a\nsynthetic-reference"
        pipeline, task, spec, ref = self.make_pipeline("graph-run", png)
        run_id, session_id = "run-graph", "session-graph"
        manifest = {
            "schema": "bridge.workbuddy.diagnostic_run/1.0",
            "run_id": run_id, "session_id": session_id, "construction_authorized": True,
            "assets": [{
                "asset_id": "ref", "file": ref.name,
                "classification": "controller_generated_synthetic",
                "sha256": hashlib.sha256(png).hexdigest(),
            }],
        }
        manifest_path = ref.parent / "run.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        control = TrustedExecutionControl(pipeline)
        facade = GraphRun(
            manifest_path, object(), trusted_execution=control, task_id=task, session_id=session_id
        )
        observed = facade.submit_observation(
            "ref", {"description": "synthetic smoke rises vertically"}, "observe-ref"
        )
        self.assertTrue(observed["observation_recorded"])
        self.assertFalse(observed["reference_analysis_route_verified"])
        self.assertTrue(observed["controller_observation_record_id"].startswith("connectorobs_"))

        analysis = ready_analysis(35)
        contract = control.reference_analysis_receipt_contract(
            task, run_id=run_id, session_id=session_id, analysis=analysis, config={"route": "synthetic-test"}
        )
        unverified = control.register_reference_analysis_run(
            task, run_id=run_id, session_id=session_id, analysis=analysis,
            config={"route": "synthetic-test"}, tool_receipt={
                "tool_call_id": "forged-digest-only",
                "input_sha256": contract["input_sha256"],
                "output_sha256": contract["output_sha256"],
                "provider_response_sha256": "f" * 64,
            },
        )
        self.assertFalse(unverified["route_execution_verified"])
        self.assertEqual(unverified["evidence_missing"], "controlled_response_capture")

        envelope = {
            "schema": "bridge.workbuddy.reference_analysis_response/1.0",
            "route_id": "WorkBuddyDesktopRoute", "selected_model": "HY3",
            "run_id": run_id, "session_id": session_id, "tool_call_id": "fake-host-tool-graph",
            "observation_record_ids": [observed["controller_observation_record_id"]],
            "analysis": analysis,
        }
        handoff = facade.capture_reference_analysis(
            json.dumps(envelope, sort_keys=True), {"route": "synthetic-test"}, "analysis-submit-1"
        )
        self.assertTrue(handoff["registration"]["route_execution_verified"])
        self.assertFalse(handoff["provider_identity_verified"])
        self.assertFalse(handoff["real_workbuddy_acceptance"])
        bound = pipeline._spec_with_analysis(task, TaskSpecV2.from_mapping(spec))
        self.assertTrue(bound.metadata["external_analysis_execution_verified"])
        self.assertFalse(bound.metadata["provider_identity_verified"])

    def test_different_synthetic_references_reach_different_actual_build_parameters(self):
        a_pipeline, a_task, a_spec, _ = self.make_pipeline("a", b"reference-a")
        b_pipeline, b_task, b_spec, _ = self.make_pipeline("b", b"reference-b")
        plans = []
        for pipeline, task, spec, analysis in (
            (a_pipeline, a_task, a_spec, ready_analysis(25)),
            (b_pipeline, b_task, b_spec, ready_analysis(70)),
        ):
            self.register(pipeline, task, analysis)
            pipeline.reference_analysis_submit(task, analysis, run_id="run-1", request_id="obs-1")
            bound = pipeline._spec_with_analysis(task, TaskSpecV2.from_mapping(spec))
            child = pipeline._subtask_spec(bound, RouteLeg("houdini", "pyro_smoke_v1", "1.0.0", 18180, "preview"), None, "diagnose")
            from dcc_task_runtime.contracts import TaskSpec
            steps = ReferenceEffectRecipe("houdini.reference_effect").steps(TaskSpec.from_mapping(child), {})
            build = next(step for step in steps if step.identifier == "fx_build_preview")
            plans.append(build.params)
        self.assertNotEqual(plans[0]["source_plan_sha256"], plans[1]["source_plan_sha256"])
        self.assertNotEqual(plans[0]["source_controls"], plans[1]["source_controls"])


if __name__ == "__main__":
    unittest.main()
