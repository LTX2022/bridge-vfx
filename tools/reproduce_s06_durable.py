#!/usr/bin/env python3
"""Reproduce the repaired S-06 durable boundary with a fake host only.

This is an executable software check, not a Houdini, simulation, cache, render,
or smoke-capability check. It creates temporary SQLite stores, reserves the
real SceneLease/GraphScheduler records, and proves that one completed claim is
replayed while changed parameters are rejected before a second host start.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tests" / "fixtures" / "pyro-sourcing-reviewed.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location("f2_s06_reproduction_validator", ROOT / "tools" / "validate_f2_solver_sourcing.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("validator could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHost:
    def __init__(self, identity):
        self._identity = dict(identity)

    def applicationVersionString(self):
        return "21.0.631"

    def bridge_scene_identity(self):
        return dict(self._identity)


def _observation(root, frame, phase):
    return {
        "actual_frame": frame,
        "phase": phase,
        "solver_path": root + "/FX_SOLVER",
        "execution_root": root,
        "source_fields": ["density", "v"],
        "target_fields": ["density", "vel"],
        "active_source_windows": [
            {"row": 1, "active": frame == 2, "source_volume": "density", "target_field": "density"},
            {"row": 2, "active": frame == 2, "source_volume": "v", "target_field": "vel"},
        ],
        "inactive_velocity_preserved": True,
        "output_nonempty": True,
        "cook_succeeded": True,
        "cook_errors": [],
    }


def main():
    validator = _load_validator()
    for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
        sys.path.insert(0, str(ROOT / "packages" / package / "src"))
    from dcc_task_runtime.pipeline_store import PipelineStore
    from vfx_pipeline.graph_scheduler import GraphScheduler
    from vfx_pipeline.scene_lease import SceneLeaseStore

    with tempfile.TemporaryDirectory(prefix="bridge-f2-s06-") as directory:
        root_dir = Path(directory)
        store = PipelineStore(root_dir / "pipeline.sqlite3")
        task_id = store.create_task({
            "schema_version": "2.0", "task_type": "visual.reference_rebuild",
            "intent": "S-06 durable fake-host reproduction", "target": {"application": "pipeline"},
            "feedback": "software-only", "idempotency_key": "s06-reproduction-task",
        })
        operation_id = "op_s06_reproduction"
        graph_root = "/obj/BRIDGE_GRAPH_" + "a" * 64
        leases = SceneLeaseStore(root_dir / "scene-lease.sqlite3")
        lease = leases.acquire(
            task_id=task_id, session_id="s06-session", process_generation="s06-process",
            scene_id="s06-scene", root=graph_root, ttl=60,
        )
        scheduler = GraphScheduler(root_dir / "scheduler")
        owner_root = str(root_dir / "scheduler-owner")
        reservation = scheduler.reserve(owner_root, operation_id)
        scheduler.arm(owner_root, operation_id, reservation["token"])
        bundle = {
            "schema": validator.SHORT_SEGMENT_AUTHORIZATION_SCHEMA,
            "task_id": task_id, "operation_id": operation_id,
            "scope": validator.SHORT_SEGMENT_SCOPE, "authorized": True,
            "operation": {
                "task_id": task_id, "operation_id": operation_id,
                "state": "AUTHORIZED", "attempt_generation": 1, "unknown": False,
            },
            "scene_lease": dataclasses.asdict(lease),
            "lease_store": {"path": str(root_dir / "scene-lease.sqlite3")},
            "heavy_budget": {
                "slot": 1, "active": True, "owner_root": owner_root,
                "operation_id": operation_id, "token": reservation["token"],
                "phase": "DISPATCHING", "max_frames": 3, "remaining_heavy_jobs": 1,
                "cache_allowed": False, "render_allowed": False,
                "scheduler_root": str(root_dir / "scheduler"),
            },
            "frame_segment": {
                "start": 1, "end": 3, "step": 1, "preroll_frames": 0,
                "max_elapsed_seconds": 30.0, "max_cook_seconds_per_frame": 5.0,
            },
            "source_binding": {
                "capture_file_sha256": validator.EXPECTED_CAPTURE_FILE_SHA256,
                "snapshot_sha256": validator.EXPECTED_SNAPSHOT_SHA256,
                "capture_state": "CAPTURED_NOT_BOUND",
            },
            "source_schedule": {
                "schema": validator.SHORT_SEGMENT_SCHEDULE_SCHEMA,
                "frame_start": 1, "frame_end": 3, "step": 1,
                "rows": {
                    "1": [{"start": 2, "end": 3}],
                    "2": [{"start": 2, "end": 3}],
                },
            },
            "host_binding": {
                "session_id": "s06-session", "process_generation": "s06-process",
                "scene_id": "s06-scene", "hip_path": "/tmp/s06-reproduction.hip", "root": graph_root,
            },
            "execution_receipt": {
                "schema": validator.SHORT_SEGMENT_RECEIPT_SCHEMA,
                "store_path": str(root_dir / "pipeline.sqlite3"),
                "idempotency_key": validator.SHORT_SEGMENT_RECEIPT_PREFIX + operation_id,
                "record_category": validator.SHORT_SEGMENT_OPERATION_CATEGORY,
                "record_id": operation_id,
            },
        }
        params = {"task_id": task_id, "candidate": 1}
        intent = validator._short_segment_intent(bundle, params)
        store.put_record(task_id, validator.SHORT_SEGMENT_OPERATION_CATEGORY, operation_id, {
            "schema": validator.SHORT_SEGMENT_OPERATION_SCHEMA, "task_id": task_id,
            "operation_id": operation_id, "scope": validator.SHORT_SEGMENT_SCOPE,
            "status": "AUTHORIZED", "unknown": False, "attempt_generation": 1,
            "intent_hash": validator._intent_hash(intent), "intent": intent,
        })
        authorization = root_dir / "authorization.json"
        authorization.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        starts = []

        def executor(_host, signed_bundle, _start, _end, _params):
            starts.append(True)
            guard = signed_bundle["frame_guard"]
            guard.run_host_call(lambda: None)
            for frame in guard.expected_frames:
                phase = "position-spoof-ignored"
                guard.run_frame(frame, lambda frame=frame, phase=phase: _observation(graph_root, frame, phase))
            return {"state": "EXECUTED_HOST_SHORT_SEGMENT", "execution_started": True}

        host = FakeHost(bundle["host_binding"])
        first = validator.execute_short_segment(CAPTURE, authorization, task_id=task_id, operation_id=operation_id,
                                                frame_start=1, frame_end=3, params=params, hou_module=host, executor=executor)
        second = validator.execute_short_segment(CAPTURE, authorization, task_id=task_id, operation_id=operation_id,
                                                 frame_start=1, frame_end=3, params=params, hou_module=host, executor=executor)
        changed = validator.execute_short_segment(CAPTURE, authorization, task_id=task_id, operation_id=operation_id,
                                                  frame_start=1, frame_end=3, params={"task_id": task_id, "candidate": 2},
                                                  hou_module=host, executor=executor)
        receipt = store.skill_execution_receipt(task_id, bundle["execution_receipt"]["idempotency_key"])
        print(json.dumps({
            "software_only": True,
            "states": [first["state"], second["state"], changed["state"]],
            "second_replayed": bool(second.get("replayed")),
            "changed_reason": changed.get("reason"),
            "fake_host_starts": len(starts),
            "durable_receipt_status": receipt["status"] if receipt else None,
            "smoke_capability_proven": bool(first.get("smoke_capability_proven", False)),
            "cache_written": bool(first.get("simulation_cache_written", False)),
            "render_started": bool(first.get("render_started", False)),
        }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
