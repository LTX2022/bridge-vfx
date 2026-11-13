# Independent output-time review — 2026-10-14

## Scope and source binding

Read-only independent reviewer; no corresponding implementation performed. Read root AGENTS.md and current README.md, handover/STATUS.md, handover/REMAINING.md and handover/NEXT_AGENT.md. No additional scoped AGENTS.md found under the reviewed plugins/tests/output subtree. Only this report was written. No real DCC/model/simulation/cache/render, new formal OS/process test, full suite, installation or production mutation was run.

Reviewed only the current `_fx_render_configuration` EXR loop (13643–13657), collector ValueError translation (13674–13678), final successful-collector-before-USD-export ordering (13669–13679), and the two named tests. Other accumulated addon hunks and the other agent's collector-budget implementation are explicitly excluded. Supporting existing callers were read only to establish the chain and cleanup, without reviewing their unrelated changes.

Exact SHA256 of the frozen owned files, after the user's final export-order update:

| Repository-relative file | SHA256 |
|---|---|
| plugins/houdini/_impl/houdini_bridge_addon.py | 72d2f3074a869f738d5da0c4a24f61d1f4dbf3053e3467e916c224328b907c61 |
| tests/unit/test_render_configuration_time.py | d89cf9693dc657a25053d7360b85092706a54f178ad1e45906eeec5364a4487e |
| tests/unit/test_render_time_process.py | 36f36633c5935b91723bdaebdd6db178355baad9d4caf959720300df99fe1bfd |

Git HEAD for context: `0a52552f5915375dfb0f3551e08928e9e624390d`. HEAD is not the reviewed working-tree build.

## Findings

No actionable defect found in the explicitly reviewed current hunks or named tests. This is scoped review acceptance, not full-build/formal-runtime acceptance.

## Checks and evidence limits

- Compared the named function with the earlier frozen formal source at `outputs/all-domain-20261009/formal/recovery/output-time-1791963608995805300/project/control/snapshot/plugins/houdini/_impl/houdini_bridge_addon.py`, SHA256 `ac7e6b1f4c56785539d176eba38c9ac91745dc2f241088962cd7cb188dd5e304`. That hash matches the supplied formal baseline's before/after addon binding. Old code called default-time `Get()` twice, permitting a valid default to hide an unsupported sample and allowing a second read to differ from the checked value. Comparison was restricted to the named function, rather than treating the accumulated Git diff as this batch.
- `outputs/all-domain-20261009/output-time-formal-baseline-20261014.json` reports source_unchanged=true, one test, one failure, no errors/skips, exit 1. Its log records H21's `BridgeError not raised` for frame 3. The archived native-render call log independently shows a frame-3 call for `invalid-time.003.exr`. This is a valid old-source failure reproduction; H22 is not established by this failfast baseline. Baseline test SHA was `962973c03cba709488a245052bba99592d5fbc2c1fedda3ffdad78b951f11a3a`, not the later test SHA above.
- Current EXR validation calls `Get(frame)` exactly once per field and stores that same value. Exact `type(actual)` rejects bool/float masquerading as integer zero and rejects containers before set-membership evaluation. Missing/wrong USD attribute type and native acquisition/type/Get exceptions become `RENDER_CONFIG_INVALID` with a fixed message and chained cause. Collector ValueError is translated to the same public error code; this does not assert that every possible stage/export/native exception is covered by the new collector handler.
- These changes introduce no `hou.setFrame` or authoring operation: parameters retain `evalAtFrame(frame)` and stage reads retain `stage(frame=frame, ...)`. The existing explicit native parameter boundary restores its temporary frame in `finally` (`tools/native_schema_test_boundary.py:678`). No new global-frame restore is necessary for these hunks. The named tests do not directly assert real-host frame restoration; no real-host result is claimed.
- The four configuration tests cover both target versions and lighting/material, integer/fractional sample reads, default-versus-sample disagreement, native Get failure, exact Python value types, and second-read drift. Existing `time-tests/scoped-final.log` reports four methods OK in 85.158s. That standalone log has no adjacent final source-binding JSON and is not promoted to proof of the final export-order build.
- Static chain verification: `recovery.facade_for` explicitly selects backend=production with allow_software_processes=True; `setup_case` prepares generated control/snapshot and configured Python host launchers. The new process test uses catalog observations → graph propose/trial → completed graph handoff → typed task_save → saved-scene task_reopen → host client's TCP `render.start`. It does not replace the production facade/runner with a success stub. Its substitutions are the explicit native USD stage/attribute and render API boundary. Frame 3 checks preflight refusal without render/file; frame 5 checks collector-budget refusal without render/file; frame 1 checks post-native drift, one actual boundary render/file, FAILED state, and empty accepted snapshots/output/completion metadata. Frame-5 collector-budget correctness itself is excluded from this review.
- Invalid-start cleanup is present in the existing runner: addon 14455–14460 releases the acquired slot, finishes budget accounting and removes `.attempt.json` on preflight exceptions. The two rejected submissions followed by a queued frame-1 submission exercise slot reuse if the formal test completes successfully. Harness cleanups are registered on the test, stop owned hosts and restore environment even after assertions fail; normal per-version completion calls `doCleanups`. The test does not directly assert the absence of `.attempt.json`; no cleanup defect was found from the inspected paths.
- Latest final main hunk retains the successful configuration's USD hash while moving full `ExportToString()` after successful collector return. Thus known collector refusal precedes full export. Neither whole-stage construction/native API reads nor full USD serialization are claimed memory bounded by this ordering.

Independent bounded probe performed in-memory with `.venv/Scripts/python.exe -B -`: extracted the exact current `_fx_render_configuration` AST and supplied explicit native/API and collector boundary objects. Exit 0; asserted sampled single reads, exact integer rejection, collector ValueError translation, and zero USD exports on collector refusal. It imported no live collector-budget implementation, launched no task hosts, and wrote no files. This is a narrow function probe, not the production-chain test.

At review time only the new formal *baseline* JSON/log were available in the named all-domain output location; final repaired formal process results remain pending/unverified here. Do not count missing/running results as PASS. Installation, real Houdini/Nuke/HY3/models, macOS, visual and production acceptance are NOT_RUN by this reviewer. Same-build live writer/backend, resolved output/AOV processor, applied filter and alpha association facts remain BLOCKED as documented in `handover/REMAINING.md` and `outputs/output-observation-20261014/discovery/NATIVE_OBSERVATION.md`; authored EXR/preflight observations do not supply them.

Evidence hashes: formal baseline JSON `e6398f38146ce107633359950cd3195d73c4200f7d3361f078370ae3b2b2ede2`; formal baseline log `94da5cc228160252ae3b9b5fdc091f546d1435031595ef32c619dbb649e0180d`; inspected scoped unit log `b33ade1853e6798341a9cb773600e350f62302bccb16dcebbea800e4186075232`.
