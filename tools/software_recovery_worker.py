#!/usr/bin/env python3
"""Task-owned software boundary worker used by the recovery contract.

The worker executes one real shipped software route, persists a checkpoint, and
then exits with the observed crash code.  A fresh launch resumes the same task
and operation identity.  It is deliberately not a native Houdini or Nuke
claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "packages/vfx-pipeline/src",
    "packages/dcc-task-runtime/src",
    "packages/houdini-bridge/src",
    "packages/nuke-bridge/src",
    "tools",
):
    source = ROOT / relative
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_event(path: Path, payload: dict) -> None:
    path = path.expanduser().resolve()
    if path.is_symlink():
        raise ValueError("recovery event path is a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _load_spec(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("recovery spec must be an object")
    return value


def prepared_graph_worker(job: dict) -> int:
    """Run the shipped graph worker, then hold its own pre-exit process boundary.

    The launcher must already supply an explicit low-level hou API substitute.
    The controller interrupts this worker through its native owned supervisor.
    The older diagnostic software-boundary route remains separate.
    """
    from vfx_pipeline.graph_job_evidence import PROTOCOL, atomic_json, process_identity, owned_file
    from vfx_pipeline.graph_job_worker import run_job
    if job.get('schema_version') != PROTOCOL or job.get('validation_scope') != 'software_test':
        raise ValueError('FORMAL_RECOVERY_SOFTWARE_JOB_REQUIRED')
    hou = sys.modules.get('hou')
    if hou is None or not hasattr(hou, '_software_agent_api_state'):
        raise ValueError('FORMAL_RECOVERY_EXPLICIT_NATIVE_API_REQUIRED')
    proposal = _load_spec(Path(job['proposal_path']))
    if proposal.get('domain_pack') not in {'lighting_camera_render_v1', 'material_lookdev_v1'}:
        raise ValueError('FORMAL_RECOVERY_TRUSTED_DOMAIN_REQUIRED')
    result = run_job(job)
    if result.get('construction_executed') is not True or result.get('reconciliation_required') is not False:
        raise ValueError('FORMAL_RECOVERY_GRAPH_COMMIT_FAILED: ' + json.dumps(result))
    root = Path(job['root']).resolve()
    event = owned_file(root, Path(job['result_path']).with_name('formal-worker-active.json'), required=False)
    atomic_json(event, {'schema': 'bridge.formal-graph-worker-active/1.0',
        'task_id': job['task_id'], 'operation_id': job['operation_id'],
        'attempt_token': job['attempt_token'], 'attempt_generation': job['attempt_generation'],
        'process_identity': process_identity(os.getpid()),
        'window': 'committed_graph_before_worker_exit', 'software_boundary_only': True}, root=root)
    deadline = min(float(job['deadline_at']), time.time() + 120)
    while time.time() < deadline:
        time.sleep(.02)
    raise TimeoutError('FORMAL_RECOVERY_INTERRUPT_NOT_OBSERVED')


def _houdini(args, spec: dict) -> int:
    from vfx_pipeline.workbuddy_assembly import software_host_client

    client, _addon = software_host_client(Path(args.addon_source), Path(args.client_state_dir))
    from native_schema_test_boundary import constrain_hou
    constrain_hou(ROOT / "docs/native-basis/hda-interface-capture.json",
                  version=str(spec.get("houdini_version") or "21.0.631"))
    scene_path = Path(str(args.scene_path or "")).expanduser().resolve()
    if not scene_path.is_file():
        raise ValueError("task-owned HIP snapshot is required")
    scene_sha = str(args.scene_sha256 or _sha256(scene_path)).lower()
    reopened = client.call("scene.reopen_task_hip", {
        "task_id": args.task_id, "path": str(scene_path), "sha256": scene_sha,
    })
    execute = {
        "task_id": args.task_id,
        "operation_id": args.operation_id,
        "domain_pack": spec["domain_pack"],
        "constraints": dict(spec.get("constraints") or {}),
        "frames": list(spec.get("frames") or [1, 2]),
        "checkpoint_after_build": args.phase == "initial",
        "resume": args.phase == "resume",
    }
    for key in ("output_path", "output_pattern", "dependency_artifacts"):
        if key in spec:
            execute[key] = spec[key]
    result = client.call("agent.fx.software_boundary_execute", execute)
    expected = "CHECKPOINT_REACHED" if args.phase == "initial" else "COMPLETED"
    if result.get("status") != expected:
        raise ValueError("unexpected Houdini software boundary status: {}".format(result.get("status")))
    event = {
        "schema": "bridge.software-recovery-event/1.0",
        "kind": "houdini",
        "phase": args.phase,
        "task_id": args.task_id,
        "operation_id": args.operation_id,
        "command": "agent.fx.software_boundary_execute",
        "reopen": reopened,
        "result": result,
        "software_boundary_only": True,
    }
    _write_event(Path(args.event), event)
    return 17 if args.phase == "initial" else 0


def _nuke_execute(nuke, script: Path, node_name: str, frames: list[int], pattern: str) -> list[int]:
    from nuke_bridge.owned_render_worker import _frame_path

    nuke.scriptOpen(str(script))
    resolver = getattr(nuke, "toNode", None) or getattr(nuke, "node", None)
    node = resolver(node_name) if callable(resolver) else None
    if node is None or node.Class() != "Write":
        raise ValueError("task snapshot does not contain the owned Write node")
    if str(node["file"].value()) != pattern:
        raise ValueError("task snapshot Write pattern differs from the recovery spec")
    done = []
    for frame in frames:
        nuke.execute(node, int(frame), int(frame))
        output = _frame_path(pattern, int(frame))
        if not output.is_file() or output.stat().st_size <= 0:
            raise ValueError("Nuke worker output is missing for frame {}".format(frame))
        done.append(int(frame))
    return done


def _nuke(args, spec: dict) -> int:
    from nuke_bridge.owned_render_worker import _load_nuke_api

    script = Path(args.script_path).expanduser().resolve()
    if not script.is_file() or script.is_symlink():
        raise ValueError("task-owned NK snapshot is required")
    expected_sha = str(args.script_sha256 or _sha256(script)).lower()
    if _sha256(script) != expected_sha:
        raise ValueError("task-owned NK snapshot hash changed")
    frames = [int(frame) for frame in (spec.get("frames") or [1, 2])]
    pattern = str(spec.get("output_pattern") or "")
    if not pattern:
        raise ValueError("Nuke recovery output pattern is required")
    already = frames[:1] if args.phase == "resume" else []
    run_frames = [frame for frame in frames if frame not in already]
    if args.phase == "initial":
        run_frames = frames[:1]
    if args.phase == "resume" and not already:
        raise ValueError("Nuke recovery requires a checkpoint frame")
    os.environ["BRIDGE_NUKE_SOFTWARE_API"] = "1"
    nuke = _load_nuke_api(pattern)
    done = _nuke_execute(nuke, script, str(spec.get("write_node") or "Write1"), run_frames, pattern)
    event = {
        "schema": "bridge.software-recovery-event/1.0",
        "kind": "nuke",
        "phase": args.phase,
        "task_id": args.task_id,
        "operation_id": args.operation_id,
        "command": "nuke.execute",
        "script": str(script),
        "script_sha256": expected_sha,
        "executed_frames": done,
        "frame_set": frames,
        "software_boundary_only": True,
    }
    _write_event(Path(args.event), event)
    return 17 if args.phase == "initial" else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("houdini", "nuke"), required=True)
    parser.add_argument("--phase", choices=("initial", "resume"), required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--client-state-dir", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--addon-source", default="")
    parser.add_argument("--scene-path", default="")
    parser.add_argument("--scene-sha256", default="")
    parser.add_argument("--script-path", default="")
    parser.add_argument("--script-sha256", default="")
    args = parser.parse_args()
    spec = _load_spec(Path(args.spec).expanduser().resolve())
    if args.kind == "houdini":
        return _houdini(args, spec)
    return _nuke(args, spec)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
