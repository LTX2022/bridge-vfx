# R05 checkpoint/reopen independent review — final closure

Status: **PASS_SCOPED**, verification exit code **0**. All three findings are closed for the fixed-zero software scope. `SOURCE_BINDING.json` binds the exact final runner source list, actual lifecycle and probe evidence. No open P1/P2 remains in this scope.

The reviewer did not implement or modify production or project tests. Review artifacts and probes are confined to this directory. Scope is fixed-zero controlled software HOM, actual addon save/contract/graph handoff/reopen/collection paths, private registration and rollback, Windows controlled process lifecycle. No real DCC, VEX, simulation, cache or render ran.

## Final finding IDs

| ID | Finding | Repair and current evidence |
| --- | --- | --- |
| R01 / P2 — CLOSED | Completed scene transition survived failed final RBD registration | RBD private scope now records completion and operation ID; the actual completion hook populates it; exact-record CAS restores INTENT on failure. Frozen `probe_completion_final_source.json` rejects both post-persistence exception and late native identity drift on both versions; the save store restores and private records/tokens/scopes clear. Final addon regressions also pass. |
| R02 / P1 — CLOSED | Public graph handoff could mint RBD authority from caller-controlled trial envelope, embedded checkpoint and rehashed HIP | Graph handoff no longer opens an RBD restore scope; it requires existing current private authority and exact embedded checkpoint. Frozen `probe_graph_authority_final_source.json` executes actual H21 graph setup, public rehashed seed/data/HIP and deliberately forged abnormal trial receipt, with no matching task save receipt: rejected with RBD_VELOCITY_AUTHORITY_REQUIRED and no authority/token/scope. Initial acceptance was identified by code inspection, not a completed old-source process exploit. The final formal test verifies fresh graph and registered new-PID recovery on both versions. |
| R03 / P2 — CLOSED | Final native reads could invalidate earlier gate/geometry observations before successful end | Host.end now repeats the **complete checkpoint**, including actual configure/carrier/solver-input geometry, then performs final private artifact/identity authorization before token removal. The intermediate fix caught gate and writable-HIP changes but omitted geometry; `probe_final_reads_complete_geometry.json` reproduced successful restore followed by actual direct-read refusal on both versions. Frozen `probe_native_geometry_closure.json` rejects geometry, gate and genuinely writable HIP byte changes on both versions; records/tokens/scopes clear, scene-transition cases revert to INTENT. Three permanent end-guard methods pass on the final source. |

Earlier `EARLY_FINDINGS.md` uses chronological diagnostic IDs: its R01 maps to final R01; its R03 maps to final R02; its R02 and R04 map to final R03. This consolidates the actual repair gates without hiding the intermediate geometry omission.

## Evidence and limits

`formal-final` already passed one method covering both version profiles, 98.563 seconds, with 428 stable source hashes. It records actual PID/nonce changes, prior worker exit and empty owned Windows Job, saved basis/seed/program retained, direct new-PID zero readback without writes/reapply, and missing/tampered checkpoint refusal. Each generated snapshot has 135 rows. **That result precedes the final complete-geometry repair and is retained as stage evidence; it cannot bind the newer source.**

`verify_binding.py` has independently checked both final-v2 JSON reports and raw logs, all 428 current source hashes, the scoped closure probes, and each lifecycle/snapshot row. `SOURCE_BINDING.json` records PASS_SCOPED and verification_exit_code=0. The review did not rerun the central suites or formal OS processes.

Replacement labels are `rbd-reopen-20261013-integration-final-v2` and `rbd-reopen-20261013-formal-final-v2`, with lifecycle under `outputs/rbd-reopen-20261013/formal-final-v2`. The affected integration selection has 15 checkpoint, 13 actual addon, 3 permanent end guards and 3 mirror tests (34 methods). Existing unchanged earlier RBD and G03 groups are not rerun as part of this repair; current formal evidence cannot be broadened to claim a fresh complete all-domain suite.

- Integration final-v2: **34 method runs / 34 unique IDs**, zero repeated runs, zero failures/errors/skips, exit 0, source unchanged.
- Formal final-v2: **1 method / 1 unique ID**, covering both version profiles, zero failures/errors/skips, exit 0, source unchanged, 93.078 seconds including runner overhead.
- H21: actual old PID **5648** → new PID **28908**; H22: **6132** → **33204**. Each changes launch nonce/generation, observes prior direct-child wait and owned Job count zero, verifies the saved contract and directly reads velocity_variance=0 with unchanged basis/program/seed. Each generated snapshot has **135 current-matching code rows**.
- Each version rejects a missing checkpoint and a tampered checkpoint whose outer scene-contract digest was recomputed, in separately launched actual hosts, and confirms those owned hosts stopped. The trace records parameter restoration only between the explicit bottom HIP-load begin/end markers; after load, no candidate reapply or registration write occurs. Direct successful readback itself has only userdata-read events.
- Old integration-final: **170 runs / 157 unique IDs**, including 13 duplicate imported TestCase runs; exit **1** because source changed during R03 repair. It remains diagnostic and is **not** a current PASS. The v2 module import eliminates that duplication.

Final Host/mirror SHA: `251902f45558a06eacc06533c7e2fb73ab289a3d74893111965d30a6ac3b1779`. Addon SHA: `ad9b3f66ce3c4561d46576a842d569719bb780f1a81041bd2b7e3ede5e02f6cd`. Complete source and evidence SHA maps are in SOURCE_BINDING.json. The external native-schema boundary is recorded as current-only because it is outside the central runner's before/after list.

HOM does not expose a cross-node atomic snapshot for this sequence. The checked behavior detects the actual finite late read changes reproduced here. No guarantee is claimed against an adversary mutating forever at arbitrary nth native calls, native allocation/blocking inside synchronous APIs, or external writes after an authorized transaction completes.

Real nonzero VEX/velocity effects, simulation, production rendering/output, installation, macOS and full 16-domain M1 remain unverified. A normal fixed-zero software recovery result does not promote those scopes. Private signature keys are not copied or replayed by the reviewer; the actual test uses OwnedProcessHandle.receipt and the reviewer checks its implementation plus archived stop facts.
