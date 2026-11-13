# Final output-observation closure — scoped software evidence verified

Independent read-only closure, 2026-10-14 07:59:11 UTC. Only FINAL_CLOSURE.md and FINAL_BINDING.json were updated. No tests, host actions, production mutations or source writes were performed.

## Actual final reports and source binding

| Report | Methods | JSON capture seconds | Unittest log seconds | Exit / failures / errors / skips |
|---|---:|---:|---:|---|
| output-observation-unit-final-20261014 | 127 | 135.610 | 135.095 | 0 / 0 / 0 / 0 |
| output-observation-formal-final-20261014 | 2 | 80.266 | 79.816 | 0 / 0 / 0 / 0 |

Both actual JSONs report source_unchanged=true. Independently recomputed all 445 current source byte hashes: both source_before/source_after maps are identical to each other and the current files. The earlier enumeration also found exactly those 445 paths. FINAL_BINDING.json.source_sha256 preserves the exact complete source_after map. This is targeted 127-method regression plus two formal methods, not the full suite or full 16-domain M1 acceptance.

TIME_REVIEW.md and Planck's BUDGET_REVIEW.md record no scoped findings. Their owned source hashes match this final freeze; both review files and Planck's independent evidence are SHA-bound. The old formal baseline remains failure evidence, separately bound and excluded from final success directories.

## Generated sources and actual formal paths

The before-directory inventory identifies exactly three new recovery children:

| Directory suffix | Target version | Current matching generated .py files | Native render frames |
|---|---|---:|---|
| output-time-1791964359325179200 | H21 21.0.631 | 137 | [1] |
| output-time-1791964388412160700 | H22 22.0.429 | 137 | [1] |
| runner-1791964414703710200 | H21 normal recovery-c | 137 | [1,3] |

All 137 relative paths in each snapshot exist at the current root and match exact byte SHA256 and snapshot-manifest entries. Runtime .pyc files are excluded: observed counts were 85, 85 and 86. The earlier 132 figure was a prior-batch count. All 411 generated source entries are retained in the binding, with the root source map for these generated paths. Baseline output-time-1791963608995805300 is not one of the three final paths.

Frozen passing test assertions and inspected raw artifacts establish the generated production controller → graph trial/handoff → typed save/reopen → TCP render.start chain. Each host ready/shutdown record names the reviewed addon SHA, actual call PID and process generation. The native-call HIP paths exist and their bytes match logged HIP SHA256. Graph input/result/completion/worker identity artifacts are separately hash-bound for generation/snapshot provenance; this closure does not claim a new cryptographic verifier run.

## Negative and normal evidence

Both H21/H22 final negative cases reject unsupported frame 3 and oversized-observation frame 5 with RENDER_CONFIG_INVALID, as asserted in the successful frozen formal test. Their final stores contain neither rejected operation ID, their requested EXRs are absent, and their only native call is frame 1. Separate refusal-response JSONs were not persisted; the code assertions, completed report/log, store and native calls supply that evidence.

Post-frame drift is different: each case has one physical sampled-drift.001.exr and one native boundary call at frame 1, then FAILED with “native render configuration changed during frame.” Actual result/store has zero frames_done, zero frame_snapshots, zero output_facts and empty execution metadata with BLOCKED_MISSING_NATIVE_FACTS. No drift output was accepted as a producer fact. No .attempt.json remains; accepting the next frame-1 request after both refusals also demonstrates installation slot reuse.

All three cases have paired Houdini, graph-worker and Nuke started/stopped payloads: PID and identity match, child_wait_observed=true and job_active_processes=0. Houdini exits are 0; successful negative-case graph workers exit 0. The deliberately interrupted normal-recovery graph worker and cancelled Nuke helper hosts exit 1 with CANCEL_REQUESTED. Those expected helper exits are not concealed by the test runner's exit 0. Receipt signatures were not independently reverified and signing keys were neither read nor copied.

Normal recovery-c has tested=true and slot_released=true, one COMPLETED render operation with calls exactly [1,3], two raw output facts and empty completion metadata. It remains BLOCKED with FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED for effective OCIO, output/AOV/filter execution and beauty-alpha association; no register_render_artifact stage is present. Its bound successful assertions preserve the original graph recovery snapshot and native createNode count, while the two-call log shows no rerender in this exercised path. This does not prove a separately unexecuted registration-retry lifecycle.

## Collector limits and remaining acceptance

Planck's independently bound trace distinguishes the 2,097,152-byte whole returned color-fact cap from native allocations/full USD export: the four-array counterexample stops after 256 indexed reads with only 2/4 arrays started; the work-budget trace stops after 15,360 reads; the exact traversal normal probe returns 127 vars with 217,133-byte JSON. These are scoped Python collector observations. Known collector refusal occurs before full USD export; successful full-stage export, native API allocation/latency and all-frame/whole-producer memory are not claimed bounded.

No pending final unit/formal/source/snapshot check remains in this scope. FINAL_BINDING.json includes exact source, report, review and selected raw-evidence hashes plus this closure's hash; it does not self-hash. No credentials or signatures were copied into these reports.

Installation, actual Houdini/Nuke/HY3/models, macOS, visual and production acceptance remain NOT_RUN in this review. Live writer facts remain BLOCKED and full 16-domain M1 remains incomplete. Scoped software evidence verification must not be promoted to those missing acceptances.

