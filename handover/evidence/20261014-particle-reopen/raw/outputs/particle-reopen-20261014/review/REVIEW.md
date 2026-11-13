# P01 trusted restore batch — independent read-only PHASE review

Current status supersedes the older OPEN text below: **R08 SCOPE_CORRECTED / PROCESS_PENDING**. Current explicit-P01 protocol gate is accepted without guard relaxation; no G03 new recovery interface is required. Routing61 passed with all 443 source hashes matching current; routing-formal4 compatibility result remains pending. Only actual completed latest reports can produce the final archive evidence gate. See the latest top sections of `CLOSURE_FINAL.md` and `R08_G03_HANDOFF_COHORT.md`.

Latest completed-run status: **P01 R01–R07 CLOSED; batch OPEN on R08**. Current formal exited 1 after P01/RBD passed and G03 H21 failed with `GEOMETRY_REGISTERED_COHORT_REQUIRED`; G03 H22/material/lighting/Crowd were not executed under failfast. See the latest top section of `CLOSURE_FINAL.md`, `R08_G03_HANDOFF_COHORT.md` and `R08_BATCH_EVIDENCE_01.json`. No pending-empty final archive approval is issued. The following pending wording/table is earlier PHASE history, not current unresolved P01 findings.

Current verdict: **R01–R07 CLOSED within P01 scope; related combined six-domain formal report pending**. See `CLOSURE_FINAL.md` and `R06_R07_P01_SOURCE_BINDING_01.json` for new two-version actual trusted handoff / new-PID evidence. `FINAL_SOURCE_BINDING_01.json` binds pre-R06 PHASE results. Earlier reports and the table below are historical scoped evidence. Only `outputs/particle-reopen-20261014/review/` was written; no whole-batch/project acceptance is claimed.

| Finding | Evidence | Current phase result |
| --- | --- | --- |
| R01 final native evaluation changes HIP after last authority check | `PHASE_PROBES.json`, `PHASE_PROBES_04.json` | Fixed by extra final authority + opaque pointer check; both builds refuse and clear issued token/registration, no native writes. Requires frozen-source binding for final closure. |
| R02 zero-amplitude CP seed 173→174, basis/contract self-rehashed, HIP unchanged | `PHASE_PROBES_04.json` | **OPEN P1**: actual public addon `scene.reopen_task_hip` restores seed 174 and writes `COMPLETED` in both builds. Supplied saved CP must bind the verified loaded HIP's original manifest CP before granting authority. |
| R03 last checkpoint node-state read changes earlier captured birth gate | `PHASE_ADDON_NODE_DRIFT.json` | **OPEN P1**: actual addon returns restored=true / `COMPLETED`; gate is 0, issued registration retained, token consumed in both builds. Recheck full earlier native facts after final node-state collection, retaining final artifact/identity/pointer guards and completion CAS rollback. |

`PHASE_GRAPH_HANDOFF.json` reviews the new verified-save helper using actual in-process registered `run_job` construction, save receipts and native channel/topology checks. Both builds accept the normal original save contract and reject missing save, rehashed saved CP, rehashed embedded CP, foreign task and foreign graph. No fabricated normal worker/stop receipts were used. This is helper-level proof, not final public cross-process graph handoff acceptance.

Static seed checks confirmed: one basis semantic role, explicit non-bool nonnegative int32, 4096-byte content ceiling, strict UTF-8 parsing and duplicate-key refusal, canonical Chinese/space file paths via existing file verifier, declared byte/hash and late file-identity checks. The worker calls frozen-input/domain validation before loading the addon, acquiring the scene lease or issuing GraphExecutor construction. Missing seed follows the existing no-default legacy path. Initializer re-reads the frozen file and passes only the exact validated seed configuration to fresh-owned P01 initialization.

Completion rollback captures the exact completed record before durable store save; wrapper uses exact-record CAS back to original INTENT and Host opaque-registration CAS. `finally` now checks whether the Host still holds the token before aborting, preserving the original auto-abort failure. Existing P01 checkpoint/addon tests remain owned/run by implementation agents; this reviewer did not rerun their broad suites.

Scope limits: no review of closed prior P01 math/ordinary write guards, no full16-domain audit, no real Houdini/Nuke/HY3/model/simulation/cache/render, no formal OS lifecycle execution by this reviewer, no OS-level new-PID claim from the same-process fixtures. Actual supervised cross-PID/nonce/stop receipts, public formal handoff and new-PID collection logs remain main/formal-agent verification. Final `CLOSURE.md` should be written only after R02/R03 fixes, explicit source freeze and affected probe recheck.

Commands (real project interpreter):

```powershell
.venv/Scripts/python.exe -B outputs/particle-reopen-20261014/review/probes.py --probe addon_seed_contract_tamper --probe addon_terminal_node_read_drift --probe host_terminal_artifact --output FRESH_FROZEN_RECHECK.json
```

All historical phase JSON outputs are preserved, including fixture setup failures. Each embeds exact production SHA-256 before/after. A setup failure or stale source is not PASS. The current graph helper script writes `PHASE_GRAPH_HANDOFF.json`; choose a new filename before rerunning it to preserve that existing evidence.
