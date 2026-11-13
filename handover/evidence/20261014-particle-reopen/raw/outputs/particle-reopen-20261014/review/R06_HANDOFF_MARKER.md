# R06 — P2 registered saved-contract marker lost before production handoff

Historical OPEN finding, now **FIXED_SCOPED / final process validation pending**. See `R06_FILTER_RECHECK.md` and `R06_MARKER_PROBE_02.json`. The original reproduction below remains audit history. It does not invalidate the later successful new-PID task restore/direct readback.

Exact current paths:

- `packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py:669` appends the actual save's `registered_scene_contract_sha256` to verification.
- `packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py:161` `_public_result` retains only three boolean verification fields, dropping that SHA.
- `graph_jobs.py:876` `_finish` persists the filtered value; `graph_jobs.py:942` status filters it again.
- `packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py:397` passes actual job status to `_mark_graph_trial_complete`.
- `packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py:1517` uses the SHA's presence to choose trusted `scene.reopen_task_hip`; absent SHA follows `scene.open_hip`.

Actual `formal-current-root/21.0.631/lifecycle.json` and `22.0.429/lifecycle.json` both contain only `{nodes_verified:true, parameters_verified:true, connections_verified:true}` in trial.result.verification. Their successful host_binding therefore cannot establish that this initial handoff used the intended trusted saved-contract reopen branch. The subsequent explicit task_reopen, new PID/nonce, direct readback and stops remain independent valid evidence.

Owner-side minimal correction: retain the exact strictly typed lowercase 64-hex registered save-contract SHA through both schema filters and persistence; invalid present values must not silently downgrade a registered handoff to ordinary open. Preserve receipt sealing and addon actual save-store / immutable CP / native verification. Do not relax embedded guards. Recheck filter retention and the affected formal handoff only; no old full-group rerun by this reviewer.

Both sites call the same `_public_result`, so correcting its schema must survive both `_finish` persistence and `status` replay. Status receives the already-filtered result_json; repairing status alone cannot recover a marker already lost on the write path. Actual `R06_MARKER_PROBE_01.json` uses registered run_job/save, service-owned graph-jobs/operation/attempt paths and two actual filter calls: raw SHA present; first=false; second=false. Production SHA before/after is unchanged. No extra normal-return mock was used.

Post-fix formal evidence must check the returned actual handoff transition command is `scene.reopen_task_hip`, with the exact requested registered contract digest, rather than only `scene_open_verified` or later unrelated task_reopen success. Current client handoff result exposes only operation_id/artifact_sha256/scene_open_verified/graph_binding; normal return of the actual opened transition may be surfaced for this assertion without fabricating a receipt. Ordinary no-registered-save graph remains on its open route. Keep the old 79/82 component results as their original source PHASE; the filter change requires its directed tests and affected P01/material/lighting/Crowd formal routes, not rerunning unchanged CP components.

The explicit-root/sidecar increment itself passed both versions in `EXPLICIT_ROOT_INCREMENT_01.json`: actual registered run_job/save/public task-reopen, normal stale-sidecar sync, after-write file-boundary failure restoring exact sidecar/save bytes and INTENT, and both foreign geometry/RBD CP refusals. No normal receipts or validation return values were fabricated. Those are same-process bottom-HOM component facts, not formal OS lifecycle proof.

The failed assertion in reviewer `check_final_evidence.py` (`KeyError` on the required marker) exposed this evidence gap; no final binding or PASS was produced by that attempt. Earlier CLOSURE/source binding predates this final increment and is not final batch acceptance.
