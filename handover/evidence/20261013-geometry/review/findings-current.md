# Independent read-only review — earlier findings at addon 02c4e60

Superseded by `final-review.md` for current status. Preserve this report as audit context; its snapshot-leak P2 is closed on addon 66a09980. Its P1 remains reproducible on that source with the project .venv.

User freeze received 2026-10-13. This is an actionable findings report, not an acceptance statement. No production, test, documentation, controller mirror, real host, model, simulation or render was modified/run. Only this review directory was written. Main retains ownership of formal process validation.

## P1 — Restore must not depend on the input verification that just failed

Location: `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py:324` (`Host.restore`), called by addon's candidate rollback. Registry `registration('verify')` calls `_check`, which reopens and authenticates the rest input before any native parameter restoration occurs.

Actual bounded counterexample through `Fixture.build()` / `Fixture.apply({'deformation': 5.})`: delegate the bottom native snippet setter to its original implementation, then change the actual temporary frozen-input file immediately after that setter. The post-write observation correctly refuses with `GEOMETRY_REST_INPUT_CHANGED`. Rollback hits the same input failure at line 324 and never restores the snippet. The target node and root remain the same; this is source drift, not loss of target ownership.

Observed output: `CANDIDATE_ROLLBACK_FAILED`; `program_restored=false`, `state_restored=true`, `snapshots=0`, committed cohort remains. Thus a rejected operation leaves the new native program paired with the old persistent manifest, while the only restoration handle is released. The explicit rollback-failed error is honest but does not resolve the avoidable partial write.

Fix direction: authenticate rollback's exact prepared target, root lease, native session and immutable registration independently of re-reading failed external input; attempt native channel/userData restoration while that authority remains intact. Continue rejecting forward execution on changed input. Do not restore foreign/replaced nodes. Add a post-set source-input drift counterexample, including retry/state behavior.

Evidence: `round1-command.log`, `round1-execution.log`. That execution intentionally refused the candidate as expected, then aborted in an auxiliary post-input-restoration observation due to the descriptor/path signature guard; later cases in round1 were NOT_RUN. Do not call its whole command PASS. The partial-write observation preceded that auxiliary failure.

## P2 — Read-only preflight still leaks G03 snapshots

Location: `plugins/houdini/_impl/houdini_bridge_addon.py:7274` (`_fx_preflight_source_plan_targets`). It calls `_fx_planned_domain_prepared(...)` and discards the returned handles. For a persisted G03 candidate, each call allocates a global `native_geometry_controls_host._SNAPSHOTS` entry.

Actual frozen-source counterexample: build, apply deformation 3, successful rebuild. Snapshots go from 0 to 3. Calling `_fx_preflight_existing_candidate_patch` once afterward increases them by another 1. The new outer rebuild `finally` releases only its own `swarm_prepared` list, not handles discarded by preflight. The fixed 128-entry budget eventually rejects otherwise valid work with `GEOMETRY_SNAPSHOT_BUDGET_EXCEEDED`; unnecessary retained HOM references also persist.

Fix direction: release returned preflight handles in `finally`, or use a validation path that does not allocate transaction snapshots. Preserve the existing successful-rebuild test and add the read-only preflight path. No broad rerun is necessary.

Evidence: `round2-command.log`, `round2-execution.log`. Three bounded existing refusal methods followed: missing-input and PID/nonce/scene identity refusal passed; userdata-only/empty-registry method errored during initialization at `_read_file` line 93, so that local test did not reach its trust assertions and is not PASS. The command accurately exits nonzero. Main's centralized log separately shows that method passing, which does not erase this local failure.

## Confirmed limited closure

The revised geometry scope runs inside source-build rollback. A bottom `Path.lstat` error injected only while actual `Registry.end(commit=True)` validates yields refusal and complete cleanup: 0 child nodes, no root manifest, no state file, 0 cohorts/transactions/scopes/snapshots. A subsequent real fixture build succeeds. This counterexample delegates all trust hooks and actual registry logic; it does not fake a high-level success.

Source-basis acquisition remains the explicitly authorized bounded source geometry observation. It is not downstream deformation cook or output evidence. New PID/save-reopen trust remains unsupported and must refuse; it is not an acceptance requirement to invent new proof for that route. Default no-input graph must keep G03 BLOCKED while prior controls remain usable. No global M1, install, visual, real-host or production PASS is asserted.

## SHA256 binding

The values below match round2 before/after and the current read at freeze. Round1 began on the same relevant hashes. Exact execution entry commands:

```powershell
Invoke-Expression (Get-Content -LiteralPath outputs/geometry-wiring-20261013/review/round1-command.log -Raw)
Invoke-Expression (Get-Content -LiteralPath outputs/geometry-wiring-20261013/review/round2-command.log -Raw)
```

Payloads and full emitted before/after manifests are in the linked command/execution logs; Python executable was `C:\Users\32200\AppData\Local\Programs\Python\Python312\python.exe`, Python 3.12.10, `-B` (no bytecode writes). Temporary fixture data is isolated and cleaned by the existing fixtures.

| Source | SHA256 |
| --- | --- |
| native_geometry_controls_host.py | f3197c577d2ef6c2d5ebbe8138f68d171cfa85009ddf7296c13aa9de30ef227a |
| native_geometry_runtime_registry.py | d785815c1fddb14ca47fb85459f1d33f74a1463a0228732f107530ac71b628ac |
| native_geometry_controls_program.py | 6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf |
| native_particle_ocean_geometry_domains.py | 7a5724819b04929b99cf353b44f5a525343423f2289a7565fa786b2494933068 |
| plugins/houdini/_impl/houdini_bridge_addon.py | 02c4e60bca42535373f4c0a95305188222d2bb16c24250f5f54ff6c69fb70a2c |
| test_native_geometry_addon_wiring.py | ba97c89a18f5c741dd8b2e2ee95a54355857a862c3896d5b9734b03667411901 |
| test_native_geometry_runtime_registry.py | 61fe48eb49bafe1ce6de69751e6d8ec5d9dad98950ee3319ddc8a605662ca9dc |

Review remains open for narrowly scoped fixes/new-hash closure.
