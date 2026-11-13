# Detailed independent closure audit: construction inputs, transport, identity and retry

2026-10-13. **Limited closure granted for the reviewed fixes on the exact source below. The original Windows transport P2 is CLOSED. No additional concrete defect was demonstrated in the new identity hook or retry cache. This is not full16 M1, native G03 output or new-PID authority acceptance.**

## Authorization correction and preserved audit

The original `REVIEW.md` incorrectly said the production batch was frozen by the user and described a separate review request. Correct attribution: **coordinator main issued the production freeze under the user's ongoing repair authorization; independent review is part of that authorized repair. The user did not issue the freeze or a separate review request.** Original report and logs remain preserved as historical audit; this closure supersedes their open-P2 verdict and attribution. No reviewer production edits, commits or pushes occurred. Reviewer writes stayed in this review directory; test state used temporary directories. Reviewer formal-process runs: zero.

## Verified changes

Transport: outgoing `--job` remains for commands at or below 32,767 UTF-16 units including NUL. Larger payloads use the owned attempt's `worker-job.json`, a short `--job-file` argument and SHA256. Actual source performs the bounded stable/hash/ownership verification before scheduler arming and repeats it in the worker parser. The two CLI transports are mutually exclusive. The original independent 40,300-byte counterexample now preserves its complete manifest and produces a **383-unit command**. Changed bytes and an actual hardlink are rejected. An injected filesystem refusal on the job file prevents both arm and dispatch. The original managed-carrier tamper checks still reject before process binding. Existing small-job and old worker paths pass.

Identity: actual Host and Registry now use the optional private geometry identity hook. On the graph-worker branch the addon obtains missing task/PID/nonce facts from the existing producer's supervised-start/PID-birth validation. It retains the root-lease identity's session, generation and epoch; it does not replace them with the graph producer's separate scene identity. The independent test calls the actual producer and identity functions, substituting only the supervisor receipt transport and the explicit bottom HOM fixture. Missing receipt, wrong PID and stale birth refuse in both H21/H22 versions. Existing task-host and adapter paths pass. Package and controller mirrors have identical hashes.

Retry: `_ConfiguredBoundary` records a process-local handoff only after the initial actual open and verified bind. Reuse rehashes the artifact, compares the completion's graph/artifact/verification/topology hash and checks the actual current host identity. The independent actual-addon test performs the first open/bind and then confirms identical retry results, no additional open/bind command, unchanged epoch, and detached return values. Modified graph/topology/verification facts, changed artifact bytes, a changed additional identity field and nonce drift refuse. A fresh boundary starts with no cached handoff. This retains a previous completion fact; it does not attest that feedback parameters are unchanged or grant a new host G03 registry authority.

The first independent handoff fixture run failed because it reused the worker's root-lease storage for the task host; the initial adoption then encountered an old epoch. That failed log is retained (`20261013T082848390492Z.log`). The corrected fixture explicitly separates the task-host filesystem boundary, runs the same actual addon/lease/transition logic, and passes. No ownership, lease, initializer or completion validator was replaced to obtain the result.

## Actual verification and final formal evidence

Independent runs used project Python 3.11.9 with bytecode disabled:

- `20261013T081525124362Z`: 75 transport/worker/service/Host/Registry methods, exit 0, zero failures/errors/skips; source stable during the run.
- `20261013T082010017038Z`: seven independent transport/identity/carrier and legacy-worker methods, exit 0, zero failures/errors/skips; source stable. These two runs precede the subsequent retry-only facade edit and are not presented as whole-current-source runs.
- `20261013T083143409123Z`: actual-addon handoff and three existing scene-transition methods on the revised facade, four methods, exit 0, zero failures/errors/skips; source stable.
- `20261013T083329289132Z`: augmented handoff method including an additional identity-field change, two native-version subtests, exit 0, zero failures/errors/skips; source stable.

Exact independent commands, from the repository root:

```powershell
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/run_review.py test_graph_job_file_transport test_geometry_registered_worker test_graph_job_frozen_inputs test_native_geometry_controls_host test_native_geometry_runtime_registry
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/run_review.py test_review_fixed.FixedBatchReviewTests test_review_boundaries.ReviewBoundaries.test_managed_inputs_reject_carrier_tamper_before_scheduler_binding test_graph_jobs.GraphJobWorkerTests
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/run_review.py test_review_handoff.HandoffReviewTests test_scene_transition_contract.ConfiguredBoundarySceneEpochTests
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/run_review.py test_review_handoff.HandoffReviewTests
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/audit_fixed_evidence.py
```

Main's final evidence was read independently, not rerun by the reviewer:

- `outputs/all-domain-20261009/geometry-input-20261013-final-core-v2.{json,log}`: **95 methods, zero failures/errors/skips, exit 0, source_unchanged true**. Its production and bootstrap hashes match current reviewed files. Log SHA256: `abe2cb87133c25554cc761632ceb3b8b5c9d219778eb46643c9312d806b2b686`.
- `outputs/all-domain-20261009/geometry-input-20261013-formal-final.{json,log}`: **one method with H21/H22 cases, zero failures/errors/skips, exit 0, source_unchanged true**, wrapper elapsed 57.468 seconds (unittest 57.028 seconds). Log SHA256: `cae756ebd73b5b27595f3c092420997582fa29acd187a21b08572ab602975d2a`.
- Both formal-final trials are `SUCCEEDED`, `stop_confirmed=true`, `construction_executed=true`, `visual_verified=false`, and `validation_scope=software_test`. Each carries a 40,317-byte manifest in `worker-job.json`, matching persisted inputs and a COMPLETE initialization journal whose frozen input digest matches. Worker PIDs are 32804 and 24116; preserved stopped payloads report exit 0 and child wait observed. Their linkage to the canonical started payload hashes matches. Each generated snapshot has 134 file records; reviewed runtime hashes match current production source.
- The actual final test asserts worker PID differs from the task-host PID, repeats the same MCP operation, checks actual ping identity/epoch equality and unchanged scene-transition raw bytes, and verifies exactly one worker input attempt. It uses a live TCP task host and actual controlled Python workers with explicitly substituted bottom HOM/rest APIs. This is software evidence.

Main's exact final formal command:

```powershell
& .venv/Scripts/python.exe -B outputs/all-domain-20261009/run_tests.py geometry-input-20261013-formal-final test_geometry_construction_process
```

The exact core command and its full module list are preserved in `fixed-evidence-audit-final.json` and main's original JSON. Historical formal-v4/v5 aggregate failures are not treated as PASS; the final evidence above supersedes them for this limited closure.

## Exact source binding

`fixed-evidence-audit-final.json` contains all reviewed runtime per-file SHA256 values, the matching main commands and evidence hashes, reviewer harness hashes, and mirror checks. Source-set SHA256 is **`b5a7d4cdeb3e35a8df05d2626253863ced601a3f49282a91493bb30e9f0192bb`**: SHA256 of the sorted compact JSON file-to-SHA256 mapping. Relevant production hashes:

| File | SHA256 |
| --- | --- |
| `packages/vfx-pipeline/src/vfx_pipeline/graph_construction_inputs.py` | `b0b52c4776439f6727bb371d80dd5a9989e5dc8a4a922d5c92213f8b31bad4f8` |
| `packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py` | `5020996a71cee8a1857609d77ac13e6adaea61517926650e3c8c30820bc983f6` |
| `packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py` | `8915444ffebf8b5b67753175f42d50a39593f0e6f6ce2f58f97bc868cf8cc92f` |
| `packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py` | `d8c4560f68e67f53ace29c914c16289114c5dd42bceced5cebbb281dfae17b53` |
| `plugins/houdini/_impl/houdini_bridge_addon.py` | `8c193f8070010898193439f5d34a4f1a40a957cd8d0cc0ffdc5489cb15fd4761` |
| `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py` and its controller mirror | `f826519d323fef99564a56f9cff38c7487fa08882ebb17196b4de891ac1adc4e` |
| `packages/houdini-bridge/src/houdini_bridge/native_geometry_runtime_registry.py` and its controller mirror | `4c2a5c3b1018d763bbb3cde8b77c7cb3f1f6755ab054999c22b825c4d2fcf0ba` |
| `tools/prepare_workbuddy_graph.py` | `7ec064b9f320954c942ddd5e9a7200af24c68ce7b893af4a597a3fe772505ddd` |
| `tests/unit/software_host_bootstrap.py` | `990fc6188c2ebf8b1f620bdcdfd8964bf1b08176cf7dbc0a5800a2c754f169d6` |

Privacy: no credentials, signing keys or supervisor environment copies were copied into review evidence. The final archive omits `receipt.key` and supervisor `intent.json`. Consequently the independent sanitized audit records the missing launch intent as unavailable, not a successful offline launch-hash/signature verification. Original signed started/stopped files were verified by the runtime during the actual main run; the reviewer checks their surviving fields and hash linkage without reusing a key. Preliminary audit v2 compared the wrong whole-file hash for the started linkage; the final audit uses the canonical started payload and both checks pass. Preliminary audit files are historical diagnostics, not final closure evidence.

Limits: this closure concerns only the input batch, Windows transport repair, private geometry identity supplement and same-operation handoff retry. Full16 M1 remains unaccepted. Actual G03 deformation/native output and new-PID G03 registry authority remain unproven. Installation, real Houdini/Nuke, WorkBuddy/HY3/model route, visual, macOS and production acceptance remain NOT_RUN. No broad known G03 lifecycle/output gap is reported as a new batch defect.
