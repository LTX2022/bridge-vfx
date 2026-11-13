# Independent G03 wiring closure — 2026-10-13

**P1 post-write input-drift rollback and P2 extraction-time frame drift are CLOSED on the production hashes below.** Original reviewer counterexamples were re-executed against actual addon/registry authority with project `.venv`, for both 21.0.631 and 22.0.429. No remaining confirmed P1/P2 in this reviewed scope. This is limited software closure, not all-domain, real-host, installation, visual, model-route or production acceptance.

The source-freeze notice before execution was issued by **coordinator main**, under the existing human authorization for this read-only review. It was a coordination notice, not a new direct human freeze approval. Earlier reports' wording attributing that freeze to the user should be read with this correction; those initial reports remain preserved. Reviewer modified no production, tests, docs or controller mirrors, and started no real Houdini/Nuke/model, cook, simulation, cache or render. Only review reports/command logs/execution logs were written here. Formal process validation stays centralized with main. Original `final-review.md`, earlier reports and all failure logs are preserved as the initial findings/audit record; this file supplies their closure status.

## P1 — Restored owned target despite failed external input

`Host.restore` now uses registry `authorize_restore`. The actual registry authenticates its retained cohort, current lease/host, root and every exact native node instance/session, plus its immutable stored registration record. This operation reads no failed external input and grants no source validation or fresh-registration authority. Normal `verify`, `register`, `authorize_fresh`, source observation and forward writes still validate the input.

Independent original counterexample, both versions: actual build, delegate native snippet setter to its original implementation, then alter the actual frozen-input file immediately after the amplitude-5 program is set. Post-write validation rejects with `GEOMETRY_REST_INPUT_CHANGED`. Native rollback succeeds:

```text
program_restored=true
userdata_restored=true
state_restored=true
same_node=true
same_session=true
snapshots=0
UNTRUSTED_SOURCE_RETRY GEOMETRY_REST_INPUT_CHANGED
```

The prior program, complete initialization userData, persistent manifest bytes and target identity are preserved. Retrying against the changed input remains refused; restoration does not reconstitute source trust.

Follow-up requested by the user: `round7-p1-exact-execution.log` independently reruns P1 on both versions with the **exact** public-code assertion `GEOMETRY_REST_INPUT_CHANGED`. Both pass. It additionally confirms the exact root object/session, root manifest userData, target object/session and immutable registry record remain unchanged; the cohort remains committed, with zero snapshots and zero active registry transactions. Forward retry again returns exactly `GEOMETRY_REST_INPUT_CHANGED`. Production before/after hashes remain identical. This run does not repeat the 53-method suite.

Actual registry/component refusal coverage passed for replaced root, replaced actual carrier, changed session, foreign basis/record/task, PID/nonce/session/process-generation/version/scene-epoch drift, revoked registration and userdata-only/absent process registry. Existing host takeover/replaced-node tests also confirm no parameter setters run after authority loss. Missing external input and damaged carrier userData can authorize restoration only through retained exact process trust, never by adopting userData.

## P2 — Rejected frame drift during lazy extraction

`Host._context` checks the actual native frame after enumerating source points/attributes/topology, then rechecks binding and actual authenticated basis before freezing the context. The exact original independent `Geometry.points()` drift counterexample was re-executed on both versions. It now raises `GEOMETRY_SOURCE_FRAME_REQUIRED`; native frame remains 2, so no silent rewind occurs. Native snippet and persistent state are unchanged, with zero snapshots retained.

The added addon method that drifts the frame inside bottom `Point.attribValue` also passed on both version subcases. It exercises the actual candidate entry and confirms refusal before native program mutation, unchanged persistent state and released snapshots. No downstream deformation/cook evidence is claimed: registry source geometry acquisition remains only the explicitly authorized bounded basis observation.

## Executed validation and exact evidence

Independent successful execution: **53 unittest methods, 0 failures, 0 errors, 0 skips**, plus four independent original counterexample scenarios (P1 and P2 on both native versions). Methods comprise 15 Host component methods, 37 actual Registry methods, and 1 two-version lazy-attribute-frame addon method. Component Host fixtures do not replace the separate actual-addon/actual-registry counterexamples as integration evidence.

Before/after SHA manifests in `round6-fix-closure-execution.log` are identical for every listed production/mirror/test file: `source_unchanged=true`. Python executable: `C:\Users\32200\Desktop\Agent\skill\Bridge\.venv\Scripts\python.exe`; version 3.11.9; execution uses `-B` to avoid bytecode writes.

Exact shell entry:

```powershell
Invoke-Expression (Get-Content -LiteralPath outputs/geometry-wiring-20261013/review/round6-fix-closure-command.log -Raw)
Invoke-Expression (Get-Content -LiteralPath outputs/geometry-wiring-20261013/review/round7-p1-exact-command.log -Raw)
```

The complete payload is in `round5-fix-closure-command.log`; `round6-fix-closure-command.log` explicitly changes only the reviewer's expected refusal-code assertion and output-log filename before executing that retained payload. Original round5 execution stopped at an overly narrow reviewer error-code assertion (`CANDIDATE_APPLY_FAILED` expected, actual existing typed error `GEOMETRY_REST_INPUT_CHANGED`). It did not finish restoration assertions or later cases, so it remains a failed reviewer attempt, not PASS and not evidence of a production rollback regression. Round6 accepts the preserved specific input-change refusal and independently asserts every restoration/retry condition. Production behavior was not changed to suit the test.

Main's new addon post-set test had the same narrow error-code expectation at the frozen test hash used here. Main subsequently corrected that assertion to the existing public `GEOMETRY_REST_INPUT_CHANGED` code and reran that single method successfully on both version subcases; the later binding is recorded below. The reviewer did not alter production/tests or convert the original failing aggregate into PASS. The independent production closure rests on restored state and rejected forward retry.

| Evidence | SHA256 |
| --- | --- |
| round5-fix-closure-command.log | 3c87a9bf58bf818b2b53f437789cb8da54bca16aa68b3e790b37eff3db317ca1 |
| round5-fix-closure-execution.log (failed reviewer assertion; preserved) | 90a9edaac8eec9d1712a25b814b42193413c7fb26180a05a5fb0a34d90106486 |
| round6-fix-closure-command.log | b128bfb197661a841e653dbb12c33018217730d6fa5a39000e6dbe49a9689b8e |
| round6-fix-closure-execution.log | cb0b25f1c09429cd33f39366b78bc97cf0dbac5d5717a7fdbe8a1c98d74d5ea5 |
| round7-p1-exact-command.log | db76b60f4fe50369265bc912563bb6ffa357ce6cc81eb1eccee894f1a92259c2 |
| round7-p1-exact-execution.log | bb769932d06361e1a27a2a6e23d415249c00520decb8cbd9669c742377be9384 |

## Final reviewed source binding

| Production file | SHA256 |
| --- | --- |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | f7138aa825b72a98e9e7e1d28abd2373df769e3f724e6d9118619690fcc12686 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_runtime_registry.py | 13f0905b8b7de2d3e1d0af11235d880ae1f43c4dfccce6c6f29269d8ecfda020 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py | 6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf |
| packages/houdini-bridge/src/houdini_bridge/native_particle_ocean_geometry_domains.py | 7a5724819b04929b99cf353b44f5a525343423f2289a7565fa786b2494933068 |
| plugins/houdini/_impl/houdini_bridge_addon.py | 66a099801e077bba0175267634589a9eed341f72a943e13c5e9867e10f7a8e46 |

The three controller mirrors (host/program/particle-ocean-geometry domains) have exactly the corresponding package hashes, confirmed in the same before/after manifest. The registry remains addon-side; no nonexistent controller registry mirror is asserted.

| Test fixture/file used in this execution | SHA256 |
| --- | --- |
| tests/unit/test_native_geometry_addon_wiring.py | 55d66e8de4b0481ac8030181d3a08255cd279fca3354a87054b41a76f2a402fc |
| tests/unit/test_native_geometry_controls_host.py | 2ade2862131c0c3a0ac1a5172b4d8f0cab1adf097967fe5faede9cf72a881750 |
| tests/unit/test_native_geometry_runtime_registry.py | d3ff33eeb0200016e31f91cef2b41aabb37a8e11ce413b6e46ee784b9d486c5e |

### Later test-only binding refresh

Main changed only the public-error-code expectation at `tests/unit/test_native_geometry_addon_wiring.py:254` from `CANDIDATE_APPLY_FAILED` to the existing `GEOMETRY_REST_INPUT_CHANGED`. Current addon-test SHA256 is **176d20b0e1c48f22004af052f010966c83636e03042cde2cf329a79b3b40b2e0**. The table above intentionally preserves the fixture hashes used by the independent 53-method execution and original-counterexample reruns. Host `f7138aa8`, registry `13f0905b` and addon `66a09980` were read again and match the production binding above; no production semantics changed.

Read-only inspection of main's `geometry-wiring-20261013-input-drift-corrected` receipt/log confirms **1 method PASS, 0 failures, 0 errors, no skips, exit 0, source_unchanged=true**. This existing method contains both native-version subcases. Recorded command:

```powershell
C:\Users\32200\Desktop\Agent\skill\Bridge\.venv\Scripts\python.exe -B outputs/all-domain-20261009/run_tests.py geometry-wiring-20261013-input-drift-corrected test_native_geometry_addon_wiring.GeometryAddonWiringTests.test_input_drift_after_native_write_restores_prepared_state
```

The reviewer only read this receipt/log and hashes; the reviewer did not execute that central runner or repeat the already-passed 53 methods. The prior central 65-method raw result remains FAIL with two original wrong-code assertions, and the separate corrected single-method result closes those assertions. No combined total or whole-M1 PASS is invented.

| Later central evidence read by reviewer | SHA256 |
| --- | --- |
| outputs/all-domain-20261009/geometry-wiring-20261013-input-drift-corrected.json | 2c1f827fe152c6b57392f899167465b1376930d7ec9d7519182cab253def1243 |
| outputs/all-domain-20261009/geometry-wiring-20261013-input-drift-corrected.log | 9990c0d768e4371ffcdbcf846029108626f348b37f7e0353861edea5b1deef1d |

Previous snapshot-leak closure remains applicable to unchanged addon `66a09980`: read-only preflights release prepared handles and successful rebuilds release their retained snapshots. Previous bottom-filesystem commit-validation cleanup closure is preserved in round4 logs; current registry commit/rollback unit paths passed after its identity-check refactor, and main's corrected addon commit-failure method is reported `ok` in the current centralized log. These are bounded closures, not a fresh broad run.

New PID/save-reopen G03 trust remains deliberately unsupported and refused. The current registry suite confirms identity and empty-registry/userdata-only refusal, including restore authorization. No-input graphs retain G03 BLOCKED and normal prior controls remain separately usable; no missing input, not_run, stale source or partial evidence is promoted to G03 PASS. Main alone owns the generated two-version process normal/refusal proof and final aggregate status. Installation, actual-host/model routes, visual and production acceptance remain unverified by this review.
