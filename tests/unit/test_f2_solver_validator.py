"""Strict F2 planning and durable short-segment boundary tests.

The fake host below is deliberately limited to a deterministic observation
double. It exercises the real SQLite PipelineStore claim/receipt, SceneLease,
and GraphScheduler paths; it never imports Houdini, creates nodes, cooks a
real solver, writes a cache, renders, or claims smoke acceptance.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tools" / "validate_f2_solver_sourcing.py"
CAPTURE_PATH = ROOT / "tests" / "fixtures" / "pyro-sourcing-reviewed.json"
FAKE_HIP_PATH = str(Path(tempfile.gettempdir()) / "f2-test.hip")


def _install_packages():
    import sys

    for package in ("dcc-task-runtime", "vfx-pipeline", "houdini-bridge", "nuke-bridge"):
        path = ROOT / "packages" / package / "src"
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def load_validator():
    spec = importlib.util.spec_from_file_location("f2_solver_validator_under_test", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("validator module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_addon():
    addon_path = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
    spec = importlib.util.spec_from_file_location("f2_s06_addon_under_test", addon_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Houdini add-on module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeHost:
    def __init__(self, identity):
        self.identity = dict(identity)
        self.current_frame = 1

    def applicationVersionString(self):
        return "21.0.631"

    def bridge_scene_identity(self):
        return dict(self.identity)

    def setFrame(self, frame):
        self.current_frame = frame

    def frame(self):
        return self.current_frame


def _observation(root: str, frame: int, phase: str, *, active_frames=None, row2_active=None) -> dict:
    _install_packages()
    from vfx_pipeline import s06_velocity

    active_frames = {2} if active_frames is None else set(active_frames)
    row1_active = frame in active_frames
    row2_active = row1_active if row2_active is None else bool(row2_active)
    sentinel = s06_velocity.default_controller_sentinel()
    if row2_active:
        velocity_evidence = s06_velocity.not_applicable(frame=frame)
        before_snapshot = None
    else:
        velocity_evidence = s06_velocity.compare_inactive_velocity(
            sentinel,
            sentinel,
            frame=frame,
            before_frame=frame,
            after_frame=frame,
            row2_active_before=False,
            row2_active_after=False,
            source_effect_isolated=True,
            no_other_velocity_writers=True,
            sourcing_boundary={
                "schema": "bridge.f2.sourcing-boundary/1.0",
                "frame": frame,
                "before": {
                    "stage": "pre_sourcing_readback", "frame": frame,
                    "freshness_token": "before-{}".format(frame), "field_generation": 10 + frame,
                },
                "operation": {
                    "status": "performed", "operation_id": "op_f2_test",
                    "source_binding_write": True, "solver_refresh": True, "input_index": 0,
                },
                "after": {
                    "stage": "post_sourcing_readback", "frame": frame,
                    "freshness_token": "after-{}".format(frame), "field_generation": 20 + frame,
                },
            },
        )
        before_snapshot = sentinel
    return {
        "actual_frame": frame,
        "phase": phase,
        "solver_path": root + "/FX_SOLVER",
        "execution_root": root,
        "source_fields": ["density", "v"],
        "target_fields": ["density", "vel"],
        "active_source_windows": [
            {"row": 1, "active": row1_active, "source_volume": "density", "target_field": "density"},
            {"row": 2, "active": row2_active, "source_volume": "v", "target_field": "vel"},
        ],
        "velocity_preservation": velocity_evidence,
        "velocity_field_readback": {
            "field": "vel",
            "before_snapshot": before_snapshot,
            "after_snapshot": sentinel,
            "same_stop_frame": {"before_frame": frame if before_snapshot is not None else None, "after_frame": frame},
            "sourcing_boundary": {
                "schema": "bridge.f2.sourcing-boundary/1.0",
                "frame": frame,
                "before": {
                    "stage": "pre_sourcing_readback", "frame": frame,
                    "freshness_token": "before-{}".format(frame), "field_generation": 10 + frame,
                },
                "operation": {
                    "status": "performed", "operation_id": "op_f2_test",
                    "source_binding_write": True, "solver_refresh": True, "input_index": 0,
                },
                "after": {
                    "stage": "post_sourcing_readback", "frame": frame,
                    "freshness_token": "after-{}".format(frame), "field_generation": 20 + frame,
                },
            },
            "writer_inventory": {"status": "pass", "complete": True, "other_writers": []},
            "sentinel": {"status": "pass", "readback_verified": True, "readback": sentinel},
        },
        # Legacy compatibility only; the validator does not use this flag.
        "inactive_velocity_preserved": False,
        "output_nonempty": True,
        "cook_succeeded": True,
        "cook_errors": [],
    }


def _guarded_fake_executor(host, bundle, start, end, params):
    guard = bundle["frame_guard"]
    guard.run_host_call(lambda: None)
    for frame in guard.expected_frames:
        phase = "position-spoof-ignored"
        guard.run_frame(frame, lambda frame=frame, phase=phase: _observation(bundle["scene_lease"]["root"], frame, phase))
    return {"state": "EXECUTED_HOST_SHORT_SEGMENT", "execution_started": True}


def _independent_worker(capture_path, authorization_path, task_id, operation_id, calls_path, barrier):
    module = load_validator()
    host = _FakeHost({
        "session_id": "session_f2_test",
        "process_generation": "process_f2_test",
        "scene_id": "scene_f2_test",
        "hip_path": FAKE_HIP_PATH,
    })
    barrier.wait(timeout=10)

    def executor(_host, bundle, _start, _end, _params):
        with Path(calls_path).open("a", encoding="utf-8") as handle:
            handle.write("host-start\n")
        # Keep the first durable claim in RUNNING long enough for the peer to
        # arrive. The second process must return UNKNOWN without entering here.
        time.sleep(0.2)
        return _guarded_fake_executor(_host, bundle, _start, _end, _params)

    result = module.execute_short_segment(
        Path(capture_path), Path(authorization_path), task_id=task_id,
        operation_id=operation_id, frame_start=1, frame_end=3,
        params={"task_id": task_id, "candidate": 1}, hou_module=host, executor=executor,
    )
    Path(str(calls_path) + "." + str(result.get("state"))).write_text("1", encoding="utf-8")


class F2SolverValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator()
        _install_packages()
        from dcc_task_runtime.pipeline_store import PipelineStore
        from vfx_pipeline.graph_scheduler import GraphScheduler
        from vfx_pipeline.scene_lease import SceneLeaseStore
        from vfx_pipeline import s06_contracts, s06_velocity

        cls.PipelineStore = PipelineStore
        cls.GraphScheduler = GraphScheduler
        cls.SceneLeaseStore = SceneLeaseStore
        cls.s06_contracts = s06_contracts
        cls.s06_velocity = s06_velocity

    def _capture(self):
        return json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))

    def _write_capture(self, temporary, value):
        path = Path(temporary) / "capture.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _context(self, temporary, *, persist_record=True, ttl=60.0, frame_end=3, source_schedule=None):
        temporary = Path(temporary)
        store = self.PipelineStore(temporary / "pipeline.sqlite3")
        task_id = store.create_task({
            "schema_version": "2.0",
            "task_type": "visual.reference_rebuild",
            "intent": "F2 short segment durable claim test",
            "target": {"application": "pipeline"},
            "feedback": "software-only host observation",
            "idempotency_key": "f2-task-test",
        })
        operation_id = "op_f2_test"
        request_id = "req_f2_test"
        root = "/obj/BRIDGE_GRAPH_" + "a" * 64
        lease_store = self.SceneLeaseStore(temporary / "scene-lease.sqlite3")
        lease = lease_store.acquire(
            task_id=task_id, session_id="session_f2_test", process_generation="process_f2_test",
            scene_id="scene_f2_test", root=root, ttl=ttl,
        )
        scheduler = self.GraphScheduler(temporary / "scheduler")
        owner_root = str(temporary / "scheduler-owner")
        reservation = scheduler.reserve(owner_root, operation_id)
        scheduler.arm(owner_root, operation_id, reservation["token"])
        if source_schedule is None:
            source_schedule = {
                "schema": self.validator.SHORT_SEGMENT_SCHEDULE_SCHEMA,
                "frame_start": 1, "frame_end": frame_end, "step": 1,
                "rows": {"1": [{"start": 2, "end": 3}], "2": [{"start": 2, "end": 3}]},
            }
        max_frames = frame_end - 1 + 1
        bundle = {
                "schema": self.validator.SHORT_SEGMENT_AUTHORIZATION_SCHEMA,
                "task_id": task_id,
                "operation_id": operation_id,
                "request_id": request_id,
                "scope": self.validator.SHORT_SEGMENT_SCOPE,
            "authorized": True,
            "operation": {
                "task_id": task_id, "operation_id": operation_id, "state": "AUTHORIZED",
                "attempt_generation": 1, "unknown": False,
            },
            "scene_lease": dataclasses.asdict(lease),
            "lease_store": {"path": str(temporary / "scene-lease.sqlite3")},
            "heavy_budget": {
                "slot": 1, "active": True, "owner_root": owner_root,
                "operation_id": operation_id, "token": reservation["token"],
                "phase": "DISPATCHING", "max_frames": max_frames, "remaining_heavy_jobs": 1,
                "generation": reservation["generation"],
                "cache_allowed": False, "render_allowed": False,
                "scheduler_root": str(temporary / "scheduler"),
            },
            "frame_segment": {
                "start": 1, "end": frame_end, "step": 1, "preroll_frames": 0,
                "max_elapsed_seconds": 30.0, "max_cook_seconds_per_frame": 5.0,
            },
            "source_binding": {
                "capture_file_sha256": self.validator.EXPECTED_CAPTURE_FILE_SHA256,
                "snapshot_sha256": self.validator.EXPECTED_SNAPSHOT_SHA256,
                "capture_state": "CAPTURED_NOT_BOUND",
            },
            "source_schedule": source_schedule,
            "velocity_sentinel": self.s06_velocity.default_controller_sentinel(),
            "host_binding": {
                "schema": self.validator.HOST_BINDING_SCHEMA,
                "session_id": "session_f2_test", "process_generation": "process_f2_test",
                "scene_id": "scene_f2_test", "hip_path": FAKE_HIP_PATH, "root": root,
            },
            "execution_receipt": {
                "schema": self.validator.SHORT_SEGMENT_RECEIPT_SCHEMA,
                "store_path": str(temporary / "pipeline.sqlite3"),
                "idempotency_key": self.validator.SHORT_SEGMENT_RECEIPT_PREFIX + operation_id,
                "record_category": self.validator.SHORT_SEGMENT_OPERATION_CATEGORY,
                "record_id": operation_id,
            },
        }
        preparation = {
            "schema": self.validator.PREPARATION_SCHEMA,
            "status": "SAVED_HIP_VERIFIED",
            "saved_hip": {
                "path": FAKE_HIP_PATH, "sha256": "b" * 64, "has_unsaved_changes": False,
            },
            "ownership": {
                "owned_project": True, "fresh_project": True,
                "read_only_capture_session": False, "conflicting_nodes": [], "task_manifest_ids": [],
            },
            "first_graph_mutation": "not_started",
            "save_preparation_and_graph_mutation_are_separate": True,
        }
        bundle["controller_issuance"] = {
            "schema": self.validator.CONTROLLER_ISSUANCE_SCHEMA,
            "scene_preparation": preparation,
        }
        auth_hash = self.s06_contracts.authorization_hash(bundle)
        controller_request = self.s06_contracts.controller_request_core(
            task_id=task_id,
            operation_id=operation_id,
            request_id=request_id,
            execution_root=root,
            host_identity=bundle["host_binding"],
            frame_segment=bundle["frame_segment"],
            source_schedule=source_schedule,
            source_binding=bundle["source_binding"],
            velocity_sentinel=bundle["velocity_sentinel"],
            authorization_hash_value=auth_hash,
        )
        bundle["controller_issuance"] = {
            "schema": self.validator.CONTROLLER_ISSUANCE_SCHEMA,
            "status": "ISSUED", "issuer": "trusted_s06_controller",
            "controller_id": "test-s06-controller", "request_id": request_id,
            "authorization_hash": auth_hash,
            "controller_request_hash": self.s06_contracts.controller_request_hash(controller_request),
            "controller_request": controller_request,
            "scene_preparation": preparation,
            "preparation_record_id": request_id,
            "first_graph_mutation": "pending",
        }
        params = {"task_id": task_id, "candidate": 1}
        if persist_record:
            intent = self.validator._short_segment_intent(bundle, params)
            store.put_record(task_id, self.validator.SHORT_SEGMENT_OPERATION_CATEGORY, operation_id, {
                "schema": self.validator.SHORT_SEGMENT_OPERATION_SCHEMA,
                "task_id": task_id, "operation_id": operation_id,
                "scope": self.validator.SHORT_SEGMENT_SCOPE, "status": "AUTHORIZED",
                "unknown": False, "attempt_generation": 1,
                "controller_issued": True,
                "authorization_hash": auth_hash,
                "controller_request_hash": bundle["controller_issuance"]["controller_request_hash"],
                "preparation_record_id": request_id,
                "first_graph_mutation": "pending",
                "intent_hash": self.validator._intent_hash(intent), "intent": intent,
            })
        authorization_path = temporary / "authorization.json"
        authorization_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        return bundle, authorization_path, store, scheduler, lease, params

    def test_complete_capture_passes_with_independently_recomputed_digest(self):
        result = self.validator.plan(CAPTURE_PATH)
        self.assertEqual(result["state"], "PLAN_READY")
        self.assertEqual(result["canonical_snapshot_sha256"], self.validator.EXPECTED_SNAPSHOT_SHA256)
        self.assertEqual(result["reviewed_capture_file_sha256"], self.validator.EXPECTED_CAPTURE_FILE_SHA256)
        self.assertEqual(result["template_count"], 485)
        self.assertTrue(result["review_summary_verified"])

    def test_cleared_templates_cannot_keep_plan_ready_with_old_self_hash(self):
        capture = self._capture()
        capture["nodes"][0]["templates"] = []
        with tempfile.TemporaryDirectory() as temporary:
            result = self.validator.plan(self._write_capture(temporary, capture))
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("CAPTURE_CANONICAL_HASH_MISMATCH", result["failures"])
        self.assertIn("CAPTURE_FILE_HASH_MISMATCH", result["failures"])
        self.assertNotIn("Traceback", json.dumps(result, ensure_ascii=False))
        self.assertNotIn(temporary, json.dumps(result, ensure_ascii=False))

    def test_changed_static_menu_token_is_rejected(self):
        capture = self._capture()
        for row in capture["nodes"][0]["templates"]:
            if row["name"] == "folder1_3":
                for child in row["children"]:
                    if child["name"] == "folder28":
                        for parm in child["children"]:
                            if parm["name"] == "srcrangetype":
                                parm["menu_items"][1] = "invented_sequence"
        with tempfile.TemporaryDirectory() as temporary:
            result = self.validator.plan(self._write_capture(temporary, capture))
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("STATIC_MENU_TOKEN_MISMATCH:folder1_3/folder28/srcrangetype", result["failures"])

    def test_errors_and_warnings_are_structured_rejections(self):
        capture = self._capture()
        capture["errors"] = ["synthetic_error"]
        capture["warnings"] = [{"kind": "synthetic_warning"}]
        with tempfile.TemporaryDirectory() as temporary:
            result = self.validator.plan(self._write_capture(temporary, capture))
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("CAPTURE_HAS_NONEMPTY:errors", result["failures"])
        self.assertIn("CAPTURE_HAS_NONEMPTY:warnings", result["failures"])
        self.assertIn("REVIEW_CAPTURE_ERRORS_MISMATCH", result["failures"])
        self.assertIn("REVIEW_CAPTURE_WARNINGS_MISMATCH", result["failures"])

    def test_malformed_inputs_never_escape_as_arbitrary_exceptions(self):
        values = ["not-json", [], {"nodes": "not-a-list"}, {"nodes": [{}]}]
        with tempfile.TemporaryDirectory() as temporary:
            for index, value in enumerate(values):
                path = Path(temporary) / ("malformed-{}".format(index))
                if isinstance(value, str):
                    path.write_text(value, encoding="utf-8")
                else:
                    path.write_text(json.dumps(value), encoding="utf-8")
                result = self.validator.plan(path)
                self.assertEqual(result["state"], "INCOMPLETE")
                self.assertTrue(all(isinstance(item, str) for item in result["failures"]))
                rendered = json.dumps(result, ensure_ascii=False)
                self.assertNotIn("Traceback", rendered)
                self.assertNotIn(str(path), rendered)

    def test_supplied_review_summary_must_match_pinned_control_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary) / "review.json"
            review.write_text(json.dumps({"state": "CAPTURED_NOT_BOUND"}), encoding="utf-8")
            result = self.validator.plan(CAPTURE_PATH, review)
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("REVIEW_SUMMARY_MISMATCH", result["failures"])

    def test_default_cli_is_plan_only_and_never_loads_hou(self):
        output = io.StringIO()
        with patch.object(self.validator, "_load_hou", side_effect=AssertionError("must not load hou")):
            from contextlib import redirect_stdout
            with redirect_stdout(output):
                exit_code = self.validator.main(["--capture-json", str(CAPTURE_PATH)])
        self.assertEqual(exit_code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["state"], "PLAN_READY")
        self.assertFalse(result["execution_started"])

    def test_real_durable_claim_and_frame_fence_replay_without_second_host_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(temporary)
            calls = []

            def executor(host, signed_bundle, start, end, received_params):
                calls.append((start, end, received_params["candidate"]))
                return _guarded_fake_executor(host, signed_bundle, start, end, received_params)

            host = _FakeHost(bundle["host_binding"])
            first = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host, executor=executor,
            )
            second = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host, executor=executor,
            )
        self.assertEqual(first["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertTrue(first["output_verification"]["inactive_velocity_preserved_verified"])
        self.assertEqual([item["phase"] for item in first["frame_trace"]], ["before", "active", "after"])
        self.assertTrue(first["output_verification"]["source_schedule_verified"])
        self.assertEqual(first["output_verification"]["missing_event_phases"], [])
        self.assertEqual(second["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertTrue(second["replayed"])
        self.assertEqual(calls, [(1, 3, 1)])
        self.assertFalse(first["simulation_cache_written"])
        self.assertFalse(first["render_started"])

    def test_completed_receipt_releases_exact_slot_and_next_reservation_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, scheduler, _lease, params = self._context(temporary)
            host = _FakeHost(bundle["host_binding"])
            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host, executor=_guarded_fake_executor,
            )
            after = scheduler.snapshot()
            next_owner = str(Path(temporary) / "next-owner")
            next_reservation = scheduler.reserve(next_owner, "op_f2_next")
            next_released = scheduler.release(
                next_owner, "op_f2_next", next_reservation["token"], stopped=True,
            )
        self.assertEqual(result["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertEqual(after["active"], 0)
        self.assertEqual(after["phase"], "RELEASED")
        self.assertTrue(next_released)

    def test_completed_receipt_replay_repairs_interrupted_finalization_without_host_rerun(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, store, scheduler, _lease, params = self._context(temporary)
            calls = []

            def executor(host, signed_bundle, start, end, received_params):
                calls.append(True)
                return _guarded_fake_executor(host, signed_bundle, start, end, received_params)

            def interrupted_finalization():
                raise RuntimeError("simulated response loss after receipt commit")

            host = _FakeHost(bundle["host_binding"])
            first = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host, executor=executor,
                finalization_hook=interrupted_finalization,
            )
            receipt = store.skill_execution_receipt(bundle["task_id"], bundle["execution_receipt"]["idempotency_key"])
            held = scheduler.snapshot()
            old_token_release = scheduler.release(
                bundle["heavy_budget"]["owner_root"], bundle["operation_id"], "0" * 64, stopped=True,
            )
            replay = load_validator().execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host,
                executor=lambda *_args: self.fail("COMPLETED receipt must finalize without host rerun"),
            )
            released = scheduler.snapshot()
            record = store.records(bundle["task_id"], self.validator.SHORT_SEGMENT_OPERATION_CATEGORY)[0]
        self.assertEqual(first["state"], "UNKNOWN")
        self.assertEqual(first["reason"], "HEAVY_SLOT_FINALIZATION_UNCERTAIN")
        self.assertEqual(receipt["status"], "COMPLETED")
        self.assertEqual(held["active"], 1)
        self.assertFalse(old_token_release)
        self.assertEqual(replay["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertTrue(replay["replayed"])
        self.assertEqual(released["active"], 0)
        self.assertEqual(released["phase"], "RELEASED")
        self.assertEqual(record["finalization"]["token"], bundle["heavy_budget"]["token"])
        self.assertEqual(calls, [True])

    def test_schedule_bound_active_window_mismatches_never_become_technical_pass(self):
        cases = {
            "all_off": (set(), None),
            "all_on": ({1, 2, 3}, None),
            "early": ({1}, None),
            "late": ({3}, None),
            "row_mismatch": ({2}, False),
        }
        for name, (active_frames, row2_active) in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                bundle, _authorization, _store, _scheduler, _lease, _params = self._context(temporary)
                trace = [
                    _observation(
                        bundle["scene_lease"]["root"], frame, "mid",
                        active_frames=active_frames, row2_active=row2_active,
                    )
                    for frame in (1, 2, 3)
                ]
                guard = SimpleNamespace(expected_frames=(1, 2, 3), seen_frames=[1, 2, 3], frame_trace=trace)
                with self.assertRaises(ValueError) as raised:
                    self.validator._validated_host_result(
                        {"execution_started": True, "simulation_cache_written": False, "render_started": False},
                        guard, bundle, bundle["operation_id"],
                    )
                self.assertIn("FRAME_ACTIVE_WINDOW_MISMATCH", str(raised.exception))

        with tempfile.TemporaryDirectory() as temporary:
            bundle, _authorization, _store, _scheduler, _lease, _params = self._context(temporary)
            observation = _observation(bundle["scene_lease"]["root"], 2, "active")
            observation["active_source_windows"] = observation["active_source_windows"][:1]
            guard = SimpleNamespace(expected_frames=(1, 2, 3), seen_frames=[1, 2, 3], frame_trace=[
                _observation(bundle["scene_lease"]["root"], frame, "mid") for frame in (1, 2, 3)
            ])
            guard.frame_trace[1] = observation
            with self.assertRaises(ValueError) as raised:
                self.validator._validated_host_result(
                    {"execution_started": True, "simulation_cache_written": False, "render_started": False},
                    guard, bundle, bundle["operation_id"],
                )
            self.assertIn("FRAME_SOURCE_WINDOWS_INVALID", str(raised.exception))

    def test_multi_pulse_schedule_derives_gap_phase_from_event_windows(self):
        schedule = {
            "schema": self.validator.SHORT_SEGMENT_SCHEDULE_SCHEMA,
            "frame_start": 1, "frame_end": 7, "step": 1,
            "rows": {
                "1": [{"start": 2, "end": 3}, {"start": 5, "end": 6}],
                "2": [{"start": 2, "end": 3}, {"start": 5, "end": 6}],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(
                temporary, frame_end=7, source_schedule=schedule,
            )

            def executor(host, signed_bundle, start, end, received_params):
                guard = signed_bundle["frame_guard"]
                guard.run_host_call(lambda: None)
                for frame in guard.expected_frames:
                    guard.run_frame(
                        frame,
                        lambda frame=frame: _observation(
                            bundle["scene_lease"]["root"], frame, "mid", active_frames={2, 5},
                        ),
                    )
                return {"execution_started": True}

            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=7, params=params, hou_module=_FakeHost(bundle["host_binding"]),
                executor=executor,
            )
        self.assertEqual(result["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertEqual([item["phase"] for item in result["frame_trace"]], [
            "before", "active", "gap", "gap", "active", "after", "after",
        ])
        self.assertEqual(result["output_verification"]["event_phase_coverage"]["missing_phases"], [])

    def test_schedule_without_event_boundary_coverage_is_inconclusive(self):
        schedule = {
            "schema": self.validator.SHORT_SEGMENT_SCHEDULE_SCHEMA,
            "frame_start": 1, "frame_end": 3, "step": 1,
            "rows": {
                "1": [{"start": 1, "end": 4}],
                "2": [{"start": 1, "end": 4}],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(
                temporary, source_schedule=schedule,
            )

            def executor(host, signed_bundle, start, end, received_params):
                guard = signed_bundle["frame_guard"]
                guard.run_host_call(lambda: None)
                for frame in guard.expected_frames:
                    guard.run_frame(
                        frame,
                        lambda frame=frame: _observation(
                            bundle["scene_lease"]["root"], frame, "ignored", active_frames={1, 2, 3},
                        ),
                    )
                return {"execution_started": True}

            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]),
                executor=executor,
            )
        self.assertEqual(result["state"], "HOST_OUTPUT_INCONCLUSIVE")
        self.assertEqual(result["reason"], "HOST_VELOCITY_PRESERVATION_NOT_CHECKED")
        self.assertNotEqual(result["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertEqual(result["output_verification"]["missing_event_phases"], ["before", "after"])

    def test_schedule_range_row_and_subframe_boundaries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, _authorization, _store, _scheduler, _lease, _params = self._context(temporary)
            invalid = json.loads(json.dumps(bundle["source_schedule"]))
            invalid["rows"]["2"] = [{"start": 2, "end": 3.5}]
            failures = self.validator._validate_source_schedule(invalid, 1, 3, 1)
            self.assertIn("SOURCE_SCHEDULE_SUBFRAME_BOUNDARY_UNSUPPORTED", failures)
            invalid = json.loads(json.dumps(bundle["source_schedule"]))
            invalid["rows"]["2"] = [{"start": 1, "end": 2}]
            failures = self.validator._validate_source_schedule(invalid, 1, 3, 1)
            self.assertIn("SOURCE_SCHEDULE_ROW_MISMATCH", failures)

    def test_changed_source_schedule_is_rejected_by_durable_intent_before_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(temporary)
            changed_bundle = json.loads(authorization.read_text(encoding="utf-8"))
            changed_bundle["source_schedule"]["rows"]["1"] = [{"start": 1, "end": 2}]
            changed_bundle["source_schedule"]["rows"]["2"] = [{"start": 1, "end": 2}]
            authorization.write_text(json.dumps(changed_bundle, ensure_ascii=False), encoding="utf-8")
            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]),
                executor=lambda *_args: self.fail("changed schedule must not start a host"),
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("CONTROLLER_REQUEST_SCHEDULE_MISMATCH", result["failures"])

    def test_changed_params_are_rejected_by_durable_intent_before_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(temporary)
            calls = []

            def executor(*args):
                calls.append(True)
                return _guarded_fake_executor(*args)

            host = _FakeHost(bundle["host_binding"])
            first = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host, executor=executor,
            )
            changed = {"task_id": bundle["task_id"], "candidate": 2}
            second = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=changed, hou_module=host, executor=executor,
            )
        self.assertEqual(first["state"], "EXECUTED_HOST_SHORT_SEGMENT")
        self.assertEqual(second["state"], "BLOCKED")
        self.assertEqual(second["reason"], "DURABLE_OPERATION_NOT_READY")
        self.assertIn("OPERATION_INTENT_MISMATCH", second["failures"])
        self.assertEqual(calls, [True])

    def test_static_authorization_json_alone_cannot_enter_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(temporary, persist_record=False)
            host = _FakeHost(bundle["host_binding"])
            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=host,
                executor=lambda *_args: self.fail("static JSON must not start a host"),
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("DURABLE_OPERATION_RECORD_MISSING", result["failures"])

    def test_wrong_session_scene_or_root_is_blocked_even_with_correct_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(temporary)
            wrong_host = _FakeHost({**bundle["host_binding"], "scene_id": "other-scene"})
            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=wrong_host,
                executor=lambda *_args: self.fail("wrong live identity must not start a host"),
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "HOST_IDENTITY_MISMATCH")

    def test_missing_set_frame_never_counts_a_checked_frame(self):
        class NoFrameHost:
            def applicationVersionString(self):
                return "21.0.631"

            def bridge_scene_identity(self):
                return {
                    "session_id": "session_f2_test",
                    "process_generation": "process_f2_test",
                    "scene_id": "scene_f2_test",
                    "hip_path": FAKE_HIP_PATH,
                }

        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, store, _scheduler, _lease, params = self._context(temporary)
            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=NoFrameHost(),
            )
            receipt = store.skill_execution_receipt(bundle["task_id"], bundle["execution_receipt"]["idempotency_key"])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertNotIn("frames_checked", result)
        self.assertFalse(result["execution_started"])
        self.assertEqual(receipt["status"], "RUNNING")

    def test_scoped_addon_root_is_exact_and_rejects_fx_or_traversal_roots(self):
        addon = load_addon()
        root = "/obj/BRIDGE_GRAPH_" + "b" * 64
        binding = {"execution_root": root}
        self.assertEqual(addon._fx_execution_root({"bridge_execution_binding": binding}), root)
        self.assertEqual(addon._fx_task_paths("task_f2", root)[0], root)
        for invalid in ("/obj/BRIDGE_FX_task_f2", root.upper(), root + "/child", "/obj/BRIDGE_GRAPH_../x", None, 42):
            with self.assertRaises(addon.BridgeCommandError):
                addon._fx_execution_root({"bridge_execution_binding": {"execution_root": invalid}})

    def test_addon_identity_is_stable_across_loader_instances(self):
        class FakeHipFile:
            def __init__(self):
                self.callbacks = []

            def eventCallbacks(self):
                return list(self.callbacks)

            def addEventCallback(self, callback):
                self.callbacks.append(callback)

            def path(self):
                return "/tmp/f2-identity.hip"

        fake_hou = SimpleNamespace(
            hipFile=FakeHipFile(),
            hipFileEventType=SimpleNamespace(BeforeClear="BeforeClear", BeforeLoad="BeforeLoad", BeforeMerge="BeforeMerge"),
        )
        with patch.dict(sys.modules, {"hou": fake_hou}):
            first = load_addon().bridge_scene_identity()
            second = load_addon().bridge_scene_identity()
        self.assertEqual(first, second)

    def test_lease_revocation_during_segment_leaves_unknown_and_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, lease, params = self._context(temporary)
            calls = []

            def executor(host, signed_bundle, start, end, received_params):
                guard = signed_bundle["frame_guard"]
                guard.run_host_call(lambda: calls.append("build"))
                guard.run_frame(1, lambda: _observation(bundle["scene_lease"]["root"], 1, "before"))
                self.SceneLeaseStore(bundle["lease_store"]["path"]).revoke(lease, host_operations_reconciled=True)
                guard.run_frame(2, lambda: _observation(bundle["scene_lease"]["root"], 2, "mid"))
                return {}

            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]), executor=executor,
            )
            replay = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]), executor=executor,
            )
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIn("RECONCILIATION_REQUIRED", result["blockers"])
        self.assertEqual(replay["state"], "UNKNOWN")
        self.assertEqual(calls, ["build"])

    def test_lease_expiry_during_segment_leaves_unknown_and_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, store, _scheduler, _lease, params = self._context(temporary)
            calls = []

            def executor(host, signed_bundle, start, end, received_params):
                guard = signed_bundle["frame_guard"]
                guard.run_host_call(lambda: calls.append("build"))
                guard.run_frame(1, lambda: _observation(bundle["scene_lease"]["root"], 1, "before"))
                expired = dict(signed_bundle["scene_lease"])
                expired["expires_at"] = time.time() - 1.0
                with sqlite3.connect(signed_bundle["lease_store"]["path"]) as database:
                    database.execute(
                        "UPDATE scene_leases SET payload=? WHERE session_id=? AND scene_id=?",
                        (json.dumps(expired, sort_keys=True), expired["session_id"], expired["scene_id"]),
                    )
                signed_bundle["scene_lease"] = expired
                guard.run_frame(2, lambda: _observation(bundle["scene_lease"]["root"], 2, "mid"))
                return {}

            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]), executor=executor,
            )
            replay = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]), executor=executor,
            )
            receipt = store.skill_execution_receipt(bundle["task_id"], bundle["execution_receipt"]["idempotency_key"])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["reason"], "SCENE_LEASE_NOT_CURRENT")
        self.assertIn("PERSISTED_SCENE_LEASE_NOT_MATCHING", result["blockers"])
        self.assertEqual(replay["state"], "UNKNOWN")
        self.assertEqual(replay["reason"], "EXECUTION_ALREADY_IN_DOUBT")
        self.assertIn("RECONCILIATION_REQUIRED", replay["blockers"])
        self.assertEqual(receipt["status"], "RUNNING")
        self.assertEqual(calls, ["build"])

    def test_result_commit_interruption_leaves_running_claim_and_restart_is_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, store, _scheduler, _lease, params = self._context(temporary)
            calls = []

            def executor(host, signed_bundle, start, end, received_params):
                calls.append(True)
                return _guarded_fake_executor(host, signed_bundle, start, end, received_params)

            def interrupted_commit():
                raise RuntimeError("simulated response loss before receipt commit")

            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]),
                executor=executor, receipt_commit_hook=interrupted_commit,
            )
            restarted = load_validator().execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]),
                executor=lambda *_args: self.fail("RUNNING receipt must not be stolen after restart"),
            )
            receipt = store.skill_execution_receipt(bundle["task_id"], bundle["execution_receipt"]["idempotency_key"])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(restarted["state"], "UNKNOWN")
        self.assertEqual(restarted["reason"], "EXECUTION_ALREADY_IN_DOUBT")
        self.assertEqual(receipt["status"], "RUNNING")
        self.assertEqual(calls, [True])

    def test_scheduler_cancel_during_segment_leaves_unknown_and_keeps_claim_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, store, _scheduler, _lease, params = self._context(temporary)
            calls = []

            def executor(host, signed_bundle, start, end, received_params):
                guard = signed_bundle["frame_guard"]
                guard.run_host_call(lambda: calls.append("build"))
                guard.run_frame(1, lambda: _observation(bundle["scene_lease"]["root"], 1, "before"))
                cancelled = self.GraphScheduler(bundle["heavy_budget"]["scheduler_root"]).request_cancel(
                    bundle["heavy_budget"]["owner_root"],
                    bundle["heavy_budget"]["operation_id"],
                    bundle["heavy_budget"]["token"],
                )
                self.assertTrue(cancelled)
                guard.run_frame(2, lambda: _observation(bundle["scene_lease"]["root"], 2, "mid"))
                return {}

            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]), executor=executor,
            )
            receipt = store.skill_execution_receipt(bundle["task_id"], bundle["execution_receipt"]["idempotency_key"])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["reason"], "SHORT_SEGMENT_CANCELLED")
        self.assertIn("HEAVY_SLOT_CANCEL_REQUESTED", result["blockers"])
        self.assertIn("RECONCILIATION_REQUIRED", result["blockers"])
        self.assertEqual(receipt["status"], "RUNNING")
        self.assertEqual(calls, ["build"])

    def test_independent_process_claim_allows_one_fake_host_start(self):
        ctx = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, store, _scheduler, _lease, _params = self._context(temporary)
            calls_path = Path(temporary) / "host-starts.log"
            barrier = ctx.Barrier(2)
            processes = [ctx.Process(target=_independent_worker, args=(
                str(CAPTURE_PATH), str(authorization), bundle["task_id"], bundle["operation_id"], str(calls_path), barrier,
            )) for _ in range(2)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(15)
            self.assertTrue(all(process.exitcode == 0 for process in processes))
            states = sorted(path.name.rsplit(".", 1)[-1] for path in Path(temporary).glob("host-starts.log.*"))
            receipt = store.skill_execution_receipt(bundle["task_id"], bundle["execution_receipt"]["idempotency_key"])
            starts = calls_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(starts), 1)
        self.assertIn("EXECUTED_HOST_SHORT_SEGMENT", states)
        self.assertIn("UNKNOWN", states)
        self.assertEqual(receipt["status"], "COMPLETED")

    def test_unapproved_operation_is_rejected_before_persistent_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle, authorization, _store, _scheduler, _lease, params = self._context(temporary)
            bundle["operation"]["unknown"] = True
            authorization.write_text(json.dumps(bundle), encoding="utf-8")
            result = self.validator.execute_short_segment(
                CAPTURE_PATH, authorization, task_id=bundle["task_id"], operation_id=bundle["operation_id"],
                frame_start=1, frame_end=3, params=params, hou_module=_FakeHost(bundle["host_binding"]),
                executor=lambda *_args: self.fail("unknown operation must not start a host"),
            )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("OPERATION_NOT_RETRYABLE", result["failures"])


if __name__ == "__main__":
    unittest.main()
