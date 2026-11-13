# Runtime contract

Nuke uses the shared task runtime. Full deliveries use `task.plan` and
`task run --watch`; individual edits use structured Nuke node tools.

Valid task states are `QUEUED`, `RUNNING`, `AWAITING_INPUT`, `PARTIAL`,
`SUCCEEDED`, `FAILED`, and `CANCELLED`. `SUCCEEDED` is allowed only after every
required rendered frame is present, non-empty, and readable.

Use `task.events` for phase and frame progress. Final frames are separate
durable steps, so `task run --json-events` can drive a real progress bar and
`task run --resume <task_id> --watch` skips already verified frames. If Nuke
cannot report a real ratio, show an indeterminate progress indicator and
elapsed time.
