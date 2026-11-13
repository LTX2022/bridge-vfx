# Runtime contract

The local runtime owns complete task execution. Atomic scene operations remain
available, but a full request must use the task interface.

## TaskSpec

Required fields are `task_type` and `intent`. The runtime fills safe defaults.
For Houdini, supported task types include `houdini.model_to_karma` and the
specialist simulation recipes registered by the installed runtime.

The render block accepts `renderer` (`auto`, `karma_xpu`, or `karma_cpu`),
`resolution`, `frame_range`, `output_dir`, and `format`. `auto` chooses XPU
only after a capability probe; otherwise it records a CPU fallback.

## States

`QUEUED`, `RUNNING`, `AWAITING_INPUT`, `PARTIAL`, `SUCCEEDED`, `FAILED`, and
`CANCELLED` describe this single-DCC task interface; do not apply this list to
the parent VFX pipeline or graph-operation protocol. Read the selected interface's
actual state and scope. `SUCCEEDED` means every required gate and
artifact verification passed. `PARTIAL` retains a checkpoint and names the
first incomplete gate.

A construction operation may succeed while its creative parent awaits further
input. Preserve both states. Distinguish cancellation requested from actual
stop confirmed; an unknown or still-running heavy operation retains its slot.

## Progress

Use `task.events(task_id, after_seq)` for incremental events. `task run
--watch` keeps the CLI attached until a terminal state; `--json-events` emits
one newline-delimited JSON object per event. Percentages come from known DAG
units and completed frames, never from elapsed-time guesses. If no true ratio
is known, the event reports `percent: null` with phase and elapsed time.

Each plan step may carry immutable `params` (for example `frame: 1001`). The
model-to-Karma recipe expands final rendering into one step per requested
frame, which makes cancellation and resume restart only the unfinished frame.

## Core execution chain (task-host/1.0)

- Launch: `houdini_bridge task-host start|stop`. The runner is generated into the task work directory; readiness and shutdown receipts are written beside it (`host.ready`, `host.ready.shutdown.json`). The serve loop drains requests and advances persistent operations one frame per tick; heavy cooks never run inside request dispatch.
- Build: `agent.fx.build_preview` validates the pack connection contract (`source_role`, `source_output`, `destination_role`, `destination_input`) before creating anything, applies the source polygon type from the node's own parm menu template, wires every declared connection and verifies them through native port readback. `build_state` is `BUILT_VERIFIED` (static) or `BUILD_FAILED`; failed builds keep their task-owned partial graph and are never reported as built.
- Execute: `agent.fx.simulate_segment` (frames or frame_range, `budget_seconds`, default 120) → `{operation_id}`; `operation.status` / `operation.cancel`. States: QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED, CANCEL_PENDING (uninterruptible cook observed at the next tick), BUDGET_REACHED (partial results kept), RECONCILE (RUNNING record from a dead generation — never auto-rerun). Per-frame evidence records frame, scene time, native cook seconds and geometry summary; static node facts are separate from dynamic evidence.
- Save/reopen: `scene.save_hip` (+`task_id`) records a receipt (sha256, per-role structure digest, generation). `scene.reopen_task_hip` (headless only) verifies the receipt and file hash, reports load warnings, re-verifies node types and takes over executor ownership; older generations get `STALE_EXECUTOR` on further writes.
- Cache: detection reads the real node state (e.g. vellumio `loadfromdisk`) rather than trusting node names; cache writes still require the signed human approval and are not part of the core-chain claims.
