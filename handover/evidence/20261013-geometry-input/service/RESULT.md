# Frozen construction input service checks

Scope: authorized full16 M1 software preparation, limited to the graph service and construction-input helper. This is not full16 acceptance, installation proof, geometry proof, or native-host proof.

API: `freeze_construction_inputs(value, *, verify_files=True)` returns a detached JSON manifest list; `None` becomes `[]`. `GraphJobService(..., frozen_input_manifest=None)` stores the bounded validated configuration as an immutable canonical JSON string and returns detached snapshots. The trial intent, `inputs.json`, and dispatch dictionary carry `frozen_input_manifest` and canonical `frozen_inputs_sha256`. No MCP or proposal fields were added.

The original persisted manifest and digest are checked against the configured snapshot before dispatch or recovery rotation. Files are verified before a new intent, at launch, and after preflight immediately before arming dispatch. Same-request retries validate persisted metadata and return the original operation without replay or requiring file bytes again. Legacy intents missing both fields retain empty-input behavior and cannot acquire newly configured inputs.

Bounds: 32 records; rest basis 64 KiB; other files 8 MiB; cumulative declared/verified file bytes 32 MiB. Metadata is bounded to 64 KiB, depth 16 and 4096 JSON nodes. Local-file path/ancestor/stat helpers are reused from `houdini_bridge.render_ocio_facts`. Descriptor reads are at most 65536 bytes; size/hash, descriptor/path signatures, ancestors and link counts are checked. No file contents or geometry observations are synthesized.

Verification used Python 3.11.9 and only `test_graph_job_frozen_inputs`. The tests run the actual service/compiler/SQLite/scheduler/filesystem code. A deferred thread-start boundary and dispatch callback prevent real launches. The dispatch callback reports `construction_executed=False`; it never certifies construction. Runtime fingerprint tests use an explicitly empty on-disk package/addon fixture. Reparse/symlink status and the file-read mutation are injected at filesystem boundaries; the hardlink is a real local test file.

- Baseline: constructor rejected the requested keyword, exit 1 (`baseline.command.txt`, `baseline.log`, `baseline.exit.txt`). Baseline interpreter was the available default Python; final targeted tests use the project Python.
- Targeted run 01: 13 tests, 3 errors, exit 1. Test-only errors: a guessed scheduler snapshot key and cleanup after deleting operation rows. Original log retained.
- Targeted run 02: 13 tests, 1 error, exit 1. Test-only error: a second incorrect scheduler snapshot key. Original log retained.
- Targeted run 03: 13 tests, no failures/errors/skips, exit 0 (`targeted.command.txt`, `targeted-03.log`, `targeted-03.exit.txt`). The preflight test now verifies the actual scheduler's ability to fence the never-dispatched permit.

Coverage: empty/legacy inputs; deep mutation isolation; Chinese/spaced paths; intent/inputs/dispatch persistence; same-request idempotence; persisted manifest/digest tampering; configured-manifest drift; prelaunch and preflight file drift; original-intent recovery without replay; invalid/nonfinite metadata; local identity restrictions; item/total/metadata budgets; bounded descriptor race detection; hardlink/reparse/symlink-ancestor rejection.

Real Houdini/Nuke/WorkBuddy/HY3/models/simulation/cache/render: NOT_RUN. Formal process tests: NOT_RUN, reserved for main scheduler. Installation, actual geometry/deformation, registry reopen, visual and production acceptance: NOT_RUN. Existing uncommitted changes preserved; no commit or push.
