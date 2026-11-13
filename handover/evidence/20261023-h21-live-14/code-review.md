# Bridge H21 live-14 remediation code review

## Conclusion

No P1/P2 findings.

This is a read-only static review of the four files frozen by `handover/evidence/20261023-h21-live-14/remediation/after-sha256.json`. It is not a post-fix real Husk, DCC, project, render, or end-to-end acceptance result.

## Scope identity

- Manifest SHA-256: `92adc53d7c85eee71d0bb93918009a4507f20c4ac4c0739e7d0dc96adc8224f1`
- Patch SHA-256: `2225a83be385d67ab3b17e7b8d248fca2a45a996abb94e6bb3966ba4b5a473b2`
- All four current file hashes match the manifest.
- The two adapter mirrors are byte-identical.
- Comparing all 159 files in the failed live-14 frozen snapshot manifest to current authoritative sources found exactly one changed snapshot source: `packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py`. The runtime-owned, identity, state, admission, deadline, and budget sources remain byte-identical to the failed live-14 freeze.

## Code paths examined

- `packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py:8-28`
- `controller-entry/client/dcc_task_runtime/husk_runtime_ready.py:8-28`
- `tests/unit/engineering_houdini_api_fixture.py:131-165`
- `tests/unit/test_engineering_preparation.py:69-110`
- Formal command and source-freeze admission in `tools/run_alpha_calibration.py`
- Adapter inclusion and command construction in `tools/prepare_native_alpha_scene.py`
- Snapshot copy and immutable-source binding in `tools/prepare_controlled_engineering.py` and `tools/prepare_workbuddy_graph.py`
- Existing runtime-ready/HMAC/PID/nonce/binding implementation in `packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py`
- Original live-14 traceback in `handover/evidence/20261023-h21-live-14/execution/raw-alpha/child.stderr.log`

## Review result

The repair is causally limited to the observed failure. The adapter obtains its source from its own executing code object using `sys._getframe().f_code.co_filename`, so it does not depend on Husk supplying `__file__` and does not inspect an arbitrary caller frame.

Before loading anything, it rejects non-string, relative, empty/pseudo, non-canonical, control-character, wrong-basename, missing, symlinked-parent/source, and multiply-linked adapter or neighboring owned-runtime paths. It derives only the exact neighboring `owned_process.py`; it has no cwd, `PYTHONPATH`, argv, namespace, or caller-path fallback. The existing `runpy.run_path` helper and `runtime_ready_and_wait()` authority remain unchanged.

The software Husk fixture now reproduces the native execution property that caused live-14 to fail: it executes bytes compiled with the actual hook path in a namespace without `__file__`. The focused regression covers one valid absolute source plus nine rejected contexts. It stubs only the already-existing `runpy` helper call and does not synthesize runtime-ready receipts or bypass the formal helper.

## Validation boundary

No tests, native probe, DCC, or full chain were run by this reviewer. The post-fix real Husk path remains unverified at the native/runtime layer and requires a separately frozen review and resource authorization before any real rerun.
