#!/usr/bin/env python3
"""Reproduce the S-06 R3 closing checks with fake host observations only.

This entry point is opt-in.  It uses temporary SQLite stores and a fake
Houdini-shaped identity; it never imports Houdini, creates nodes, cooks a
solver, writes a cache, renders, or proves smoke capability.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tests" / "fixtures" / "pyro-sourcing-reviewed.json"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "f2_s06_r3_closing_validator", ROOT / "tools" / "validate_f2_solver_sourcing.py",
    )
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


def _observation(root: str, frame: int, active_frames: set[int]) -> dict:
    active = frame in active_frames
    return {
        "actual_frame": frame,
        # Deliberately position-shaped and ignored by the validator.  The
        # durable schedule is the only phase authority.
        "phase": "position-spoof",
        "solver_path": root + "/FX_SOLVER",
        "execution_root": root,
        "source_fields": ["density", "v"],
        "target_fields": ["density", "vel"],
        "active_source_windows": [
            {"row": 1, "active": active, "source_volume": "density", "target_field": "density"},
            {"row": 2, "active": active, "source_volume": "v", "target_field": "vel"},
        ],
        "inactive_velocity_preserved": True,
        "output_nonempty": True,
        "cook_succeeded": True,
        "cook_errors": [],
    }


def _schedule(validator, frame_end=3):
    return {
        "schema": validator.SHORT_SEGMENT_SCHEDULE_SCHEMA,
        "frame_start": 1,
        "frame_end": frame_end,
        "step": 1,
        "rows": {
            "1": [{"start": 2, "end": 3}],
            "2": [{"start": 2, "end": 3}],
        },
    }


def _make_context(validator, root_dir: Path, operation_id: str):
    from dcc_task_runtime.pipeline_store import PipelineStore
    from vfx_pipeline.graph_scheduler import GraphScheduler
    from vfx_pipeline.scene_lease import SceneLeaseStore

    store = PipelineStore(root_dir / "pipeline.sqlite3")
    task_id = store.create_task({
        "schema_version": "2.0",
        "task_type": "visual.reference_rebuild",
        "intent": "S-06 R3 durable close reproduction",
        "target": {"application": "pipeline"},
        "feedback": "software-only",
        "idempotency_key": "s06-r3-" + operation_id,
    })
    graph_root = "/obj/BRIDGE_GRAPH_" + "a" * 64
    leases = SceneLeaseStore(root_dir / "scene-lease.sqlite3")
    lease = leases.acquire(
        task_id=task_id, session_id="s06-r3-session", process_generation="s06-r3-process",
        scene_id="s06-r3-scene-" + operation_id, root=graph_root, ttl=60,
    )
    scheduler = GraphScheduler(root_dir / "scheduler")
    owner_root = str(root_dir / "scheduler-owner")
    reservation = scheduler.reserve(owner_root, operation_id)
    scheduler.arm(owner_root, operation_id, reservation["token"])
    schedule = _schedule(validator)
    bundle = {
        "schema": validator.SHORT_SEGMENT_AUTHORIZATION_SCHEMA,
        "task_id": task_id,
        "operation_id": operation_id,
        "scope": validator.SHORT_SEGMENT_SCOPE,
        "authorized": True,
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
        "source_schedule": schedule,
        "host_binding": {
            "session_id": "s06-r3-session", "process_generation": "s06-r3-process",
            "scene_id": "s06-r3-scene-" + operation_id,
            "hip_path": "/tmp/s06-r3-reproduction.hip", "root": graph_root,
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
        "schema": validator.SHORT_SEGMENT_OPERATION_SCHEMA,
        "task_id": task_id, "operation_id": operation_id,
        "scope": validator.SHORT_SEGMENT_SCOPE, "status": "AUTHORIZED",
        "unknown": False, "attempt_generation": 1,
        "intent_hash": validator._intent_hash(intent), "intent": intent,
    })
    authorization = root_dir / (operation_id + "-authorization.json")
    authorization.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle, authorization, params, store, scheduler


def _executor(active_frames, starts):
    def run(_host, signed_bundle, _start, _end, _params):
        starts.append(True)
        guard = signed_bundle["frame_guard"]
        guard.run_host_call(lambda: None)
        for frame in guard.expected_frames:
            guard.run_frame(
                frame,
                lambda frame=frame: _observation(
                    signed_bundle["scene_lease"]["root"], frame, active_frames,
                ),
            )
        return {"execution_started": True}

    return run


def _execute(validator, authorization, bundle, params, executor):
    return validator.execute_short_segment(
        CAPTURE, authorization,
        task_id=bundle["task_id"], operation_id=bundle["operation_id"],
        frame_start=1, frame_end=3, params=params,
        hou_module=FakeHost(bundle["host_binding"]), executor=executor,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-software-only", action="store_true",
        help="explicitly run temporary fake-host/SQLite checks; never starts Houdini",
    )
    args = parser.parse_args(argv)
    if not args.confirm_software_only:
        print(json.dumps({
            "software_only": True,
            "state": "BLOCKED",
            "reason": "EXPLICIT_SOFTWARE_ONLY_CONFIRMATION_REQUIRED",
            "real_houdini_started": False,
            "simulation_cache_written": False,
            "render_started": False,
            "smoke_capability_proven": False,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    validator = _load_validator()
    for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
        sys.path.insert(0, str(ROOT / "packages" / package / "src"))
    from vfx_pipeline.graph_scheduler import SchedulerBusy

    with tempfile.TemporaryDirectory(prefix="bridge-f2-s06-r3-") as directory:
        root_dir = Path(directory)

        normal_bundle, normal_auth, normal_params, _normal_store, normal_scheduler = _make_context(
            validator, root_dir / "normal", "op_s06_r3_normal",
        )
        normal_starts = []
        normal = _execute(
            validator, normal_auth, normal_bundle, normal_params,
            _executor({2}, normal_starts),
        )
        normal_slot = normal_scheduler.snapshot()
        next_owner = str(root_dir / "normal-next-owner")
        next_reservation = normal_scheduler.reserve(next_owner, "op_s06_r3_next")
        next_released = normal_scheduler.release(
            next_owner, "op_s06_r3_next", next_reservation["token"], stopped=True,
        )

        interrupted_bundle, interrupted_auth, interrupted_params, interrupted_store, interrupted_scheduler = _make_context(
            validator, root_dir / "interrupted", "op_s06_r3_interrupted",
        )
        interrupted_starts = []

        def lose_after_receipt():
            raise RuntimeError("simulated finalization response loss")

        interrupted_first = validator.execute_short_segment(
            CAPTURE, interrupted_auth,
            task_id=interrupted_bundle["task_id"], operation_id=interrupted_bundle["operation_id"],
            frame_start=1, frame_end=3, params=interrupted_params,
            hou_module=FakeHost(interrupted_bundle["host_binding"]),
            executor=_executor({2}, interrupted_starts), finalization_hook=lose_after_receipt,
        )
        interrupted_receipt = interrupted_store.skill_execution_receipt(
            interrupted_bundle["task_id"], interrupted_bundle["execution_receipt"]["idempotency_key"],
        )
        interrupted_held = interrupted_scheduler.snapshot()
        old_token_release = interrupted_scheduler.release(
            interrupted_bundle["heavy_budget"]["owner_root"],
            interrupted_bundle["operation_id"], "0" * 64, stopped=True,
        )
        interrupted_replay = _execute(
            validator, interrupted_auth, interrupted_bundle, interrupted_params,
            lambda *_args: (_ for _ in ()).throw(RuntimeError("host rerun is forbidden")),
        )
        interrupted_released = interrupted_scheduler.snapshot()

        alloff_bundle, alloff_auth, alloff_params, alloff_store, alloff_scheduler = _make_context(
            validator, root_dir / "all-off", "op_s06_r3_alloff",
        )
        alloff_starts = []
        alloff = _execute(
            validator, alloff_auth, alloff_bundle, alloff_params,
            _executor(set(), alloff_starts),
        )
        alloff_receipt = alloff_store.skill_execution_receipt(
            alloff_bundle["task_id"], alloff_bundle["execution_receipt"]["idempotency_key"],
        )
        alloff_slot = alloff_scheduler.snapshot()
        try:
            alloff_scheduler.reserve(str(root_dir / "all-off-next"), "op_s06_r3_alloff_next")
            alloff_next = "unexpectedly_reserved"
        except SchedulerBusy:
            alloff_next = "SchedulerBusy"

        print(json.dumps({
            "software_only": True,
            "real_houdini_started": False,
            "simulation_cache_written": False,
            "render_started": False,
            "smoke_capability_proven": False,
            "normal": {
                "state": normal["state"],
                "phases": [item["phase"] for item in normal["frame_trace"]],
                "slot_active_after_complete": normal_slot["active"],
                "next_reservation_succeeded": next_released,
                "host_starts": len(normal_starts),
            },
            "interrupted_finalization": {
                "first_state": interrupted_first["state"],
                "first_reason": interrupted_first.get("reason"),
                "receipt_status": interrupted_receipt["status"] if interrupted_receipt else None,
                "slot_active_before_replay": interrupted_held["active"],
                "old_token_release": old_token_release,
                "replay_state": interrupted_replay["state"],
                "replayed": bool(interrupted_replay.get("replayed")),
                "slot_active_after_replay": interrupted_released["active"],
                "host_starts": len(interrupted_starts),
            },
            "all_off": {
                "state": alloff["state"],
                "reason": alloff.get("reason"),
                "receipt_status": alloff_receipt["status"] if alloff_receipt else None,
                "slot_active_after_rejection": alloff_slot["active"],
                "next_reservation": alloff_next,
                "host_starts": len(alloff_starts),
            },
        }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
