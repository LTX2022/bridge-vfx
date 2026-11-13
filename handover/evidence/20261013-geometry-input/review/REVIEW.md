# Independent read-only review: frozen construction inputs

Review date: 2026-10-13. Baseline Git HEAD: `0a52552f5915375dfb0f3551e08928e9e624390d`.
Authority is the user's review request. The production batch is frozen by the user; no coordinator freeze or further authorization is inferred.

Verdict: **one P2 finding remains open; limited closure is NOT_GRANTED pending correction and source-bound re-review.** This report reviews only the new frozen-input batch. Existing uncommitted G03 and other production changes were preserved. All reviewer writes are under this review directory. No production source changes, commit, push, real DCC, WorkBuddy/HY3, model, simulation, cache or render execution occurred.

## P2: accepted metadata exceeds the Windows worker launch transport

Locations: `packages/vfx-pipeline/src/vfx_pipeline/graph_jobs.py:696` adds the entire manifest to the worker dictionary; `graph_jobs.py:715` serializes that dictionary into a single `--job` argument. The helper allows 64 KiB of metadata (`graph_construction_inputs.py:21`). The actual Windows boundary converts the command list with `subprocess.list2cmdline` and calls `CreateProcessW` (`packages/dcc-task-runtime/src/dcc_task_runtime/windows_process.py:400`).

Concrete reproduction: one valid, verified local-file record with five 8,000-character strings in its metadata is accepted by `freeze_construction_inputs` and the real service, then persisted and armed by the real scheduler. Its canonical-ish manifest serialization is **40,300 UTF-8 bytes**, below the supported 65,536-byte limit. Capturing the actual service-generated argv at the explicit subprocess boundary yields **43,032 UTF-16 code units including the terminating null**, above Windows' maximum of 32,767. Microsoft documents that maximum in [CreateProcessW](https://learn.microsoft.com/en-us/windows/desktop/api/processthreadsapi/nf-processthreadsapi-createprocessw).

This is a new failure introduced by placing the newly accepted metadata in argv. It occurs before the worker can verify its frozen inputs or initialize any domain. The default supervisor writes the command to its intent file but ultimately passes this same command to `WindowsJobProcess`; the supervisor does not eliminate the worker command-line limit. Changing input bytes, digest, domain controls or retrying the same intent does not make the command launchable.

The reviewer did **not** start a formal controlled process. The proof uses the actual service/compiler/SQLite/scheduler/file checks and intercepts only the subprocess transport, computes the same Windows command-line encoding, and raises an explicit no-launch boundary error. The reported `RECONCILIATION_REQUIRED` state belongs to that intentional injected error; it is not presented as an observed Windows native error code. The argv length and documented Windows refusal are sufficient to demonstrate that this accepted payload cannot launch on the actual boundary. A native process refusal/success check, if needed, remains owned by main's central formal scheduler.

Minimal correction: transport the bounded service-owned job through an owned JSON file and pass its short absolute path to the worker, reusing existing owned-file/bounded-JSON validation. Keep the existing `--job` parser as a compatibility path for existing callers. Preserve manifest/digest checks between job and persisted inputs, and verify the file before arming launch. An early Windows argv-size guard can instead reject this payload safely, but would narrow the currently accepted 64-KiB input contract and must be explicitly documented; it is not evidence that the stated upper range is supported. Do not change the original manifest merely to shorten a retry.

Proof: `test_review_boundaries.py`, method `ReviewBoundaries.test_accepted_manifest_exceeds_windows_launch_limit`; original output `20261013T075801750164Z.log`.

## Verification and remaining review scope

- Independent new groups: `test_graph_job_frozen_inputs` (13), `test_graph_construction_inputs` (8), and `test_geometry_registered_worker` (1 method with H21/H22 subtests): **22 methods, zero failures/errors/skips**. The registered-worker group executes the actual addon in-process with explicit bottom HOM/schema/rest-geometry substitutes; it is not a managed formal-process or native-Houdini run.
- Independent managed-carrier checks: seven job/input manifest and digest changes, separately rehashed carrier changes, and file-content drift all fail in the actual managed `_initialize_evidence` path before scheduler construction/process binding. The process bind boundary was never invoked. The second review method covers these seven subtests. Together the two reviewer methods passed; the first asserts the demonstrated transport defect and therefore is not a product success test.
- Read the generator, facade, service, worker, completion validator and private initializer as one path. The private initializer receives explicit verified frozen metadata, checks its registered identity/topology, and returns the input digest; the worker checks that digest. The positive two-version addon test shows frozen rest initialization while retaining `BLOCKED` / `parameters_only`. It does not certify actual deformation.
- Existing targeted cases cover immutable cloning, the original intent on idempotent retry, missing-file retry without replay, configured/persisted metadata drift refusal, original-intent recovery, legacy empty-input recovery, limits before reads, descriptor byte races, actual hardlink refusal and explicit reparse/symlink observations. No additional concrete defect was demonstrated in those paths.
- Omitted/None/empty generator arguments and legacy empty service inputs retain their tested behavior. Worker only supplies the optional initializer keyword for nonempty inputs; the addon retains the five positional arguments plus the optional keyword. CLI `--job` backward compatibility must remain intact in the transport correction.
- The CLI currently reads the newly supplied manifest JSON with `read_text` before semantic validation. This report does not expand the batch into a generic trusted-configuration-reader hardening project. Supported manifest metadata and referenced asset hashing remain bounded by the helper; this review does not claim the raw CLI configuration-file read itself is bounded.

## Exact commands and source binding

Executed from `C:\Users\32200\Desktop\Agent\skill\Bridge`, using project Python 3.11.9:

```powershell
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/run_review.py
& .venv/Scripts/python.exe -B outputs/geometry-input-20261013/review/run_review.py test_review_boundaries.ReviewBoundaries
```

Both commands exited 0. Each run captured interpreter, argv, cwd, timestamps, actual unittest results, and before/after SHA256 values for every Python file in the four runtime packages, the addon, generator, reviewed tests and bottom schema/interface dependencies. Both source sets remained identical during their runs. Full per-file hashes are in `20261013T075420774590Z.json` and `20261013T075801750164Z.json`. The second run's source-set SHA256 is `6b353aebc40c289224fdeee100ccd764e15972bc96018e60707f553166c04d79` (SHA256 of the sorted compact JSON file-to-SHA256 mapping). Git HEAD alone does not bind these uncommitted inputs.

## Limited closure after correction

Closure is still pending. An implementer must correct the transport and identify the exact revised source hashes. Independent re-review must verify that the original supported 40,300-byte metadata crosses the corrected transport unchanged, that carrier/digest tampering still fails before native initialization, and that the old `--job` API still works. Reuse the affected core groups and unique boundary checks; no unchanged full-suite rerun is required. Main must provide exact commands, exits, source binding and actual centrally scheduled controlled-Python formal evidence for the changed transport. No such after-fix evidence exists at the time of this report.

Separate limits: full 16-domain M1 **NOT_ACCEPTED**; new-batch installation **NOT_RUN**; actual Houdini/Nuke **NOT_RUN**; WorkBuddy/HY3/model route **NOT_RUN**; actual G03 deformation/native output **UNPROVEN**; new-PID registry lifecycle **UNPROVEN**; visual and production acceptance **NOT_RUN**. The last two G03 implementation gaps are recorded limitations, not newly reported bugs in this frozen-input batch.
