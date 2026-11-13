# Independent output-color budget review

2026-10-14. Started 07:48:57 UTC; completed within four minutes. Independent reviewer; no participation in the corresponding implementation. Read root AGENTS.md, current README/handover state, discovery/SOFTWARE_GAPS.md, frozen collector/test sources, implementer budget evidence, and the scoped addon/client paths. Production sources were not modified. Writes are confined to this report and `review/budget-independent/`.

**Conclusion: limited software review — no concrete blocker or new finding in the reviewed budget change.** The confirmed discovery P2 (unbounded native exception bodies and aggregate individually legal arrays) is addressed at the Python collector boundary on the hashes below. This does not establish native API allocation/timing bounds, full producer boundedness, native output readiness, or production acceptance.

## Evidence and checks

- **Whole JSON, not only leaves:** collector lines 57–75 maintain a shared conservative byte/work counter and finally stream-encode the entire fact with `allow_nan=False`, counting UTF-8 bytes and refusing any result above 2,097,152 bytes. Default ASCII escaping is counted, including quotes, backslashes, control characters and non-ASCII. The final check includes repeated names/paths, dictionary keys, structure and missing-fact diagnostics. It does not allocate one complete serialized observation string. This cap concerns the returned color fact, not the complete addon configuration, all frames combined, signed receipts or USD stage export.
- **Shared 32,768 work/value charges:** arrays reserve structure and element work before indexed capture (lines 119–122); attributes, relations, prims, gaps and filter-name enumeration also charge the same budget. Scalars charge again, so this is a conservative capture-work budget, not a claim that exactly 32,768 JSON nodes are permitted. Independent bool-array probe aborted after **15,360 element reads**, with **120/128 arrays started**. No later array was copied after exhaustion.
- **Early byte refusal:** independent four-array reproduction of discovery counterexample B raised `_ObservationLimit` after **256 indexed reads**, with only **2/4 arrays started**. Checked sequence length and indexed capture replace unconstrained Python iteration; scalar encoding is bounded by the 8,192-character limit. Existing tests cover escaping/non-ASCII and checked filter enumeration. These checks occur after bottom native APIs return their values; no native allocation bound is inferred.
- **Budget exceptions propagate:** attribute, relationship, prim and filter catches explicitly rethrow `_ObservationLimit` at collector lines 207, 242, 276 and 305, before broader catches. Errors raised while charging gaps also escape. Oversized individual native sequences retain their distinct bounded LIMIT gaps; invalid individual typed values remain missing observations. Neither is confused with shared-budget exhaustion.
- **Metadata and diagnostics:** native names/type strings and retained prim/relationship paths are charged and bounded. Gaps charge code/path/detail before append. `_native_error` (lines 78–82) uses only a bounded exception class name and a fixed message; it never formats or retains the exception body. Existing scoped tests cover huge names/types/paths, all four native failure boundaries, and an exception whose `__str__` must never execute. Finite numeric/type validation and `allow_nan=False` remain intact.
- **Normal traversal preserved:** independent exact-limit probe captured **one product plus 127 RenderVars = 128 targets**, returned all 127 vars, and produced **217,133-byte** whole JSON with no TRAVERSAL_LIMIT. The existing 17-AOV normal-path test passed, as did the nested-target exhaustion test. The shared traversal limit remains 128.
- **Native gaps unchanged:** mandatory OCIO/runtime override/filter execution/alpha gaps remain at collector lines 344–350; raw filter effects and final output paths remain unresolved. Inspected client execution metadata still says `BLOCKED_MISSING_NATIVE_FACTS` and leaves completion metadata empty. No false AVAILABLE result was found in these scoped paths.
- **Addon integration:** actual `_fx_render_configuration` lines 13675–13679 catches collector `ValueError`, maps it to actual `BridgeCommandError` with `RENDER_CONFIG_INVALID`, and hashes USD only after collection succeeds. Independent H21/H22 bottom-API probes exercised both normal and oversized-native-type cases: normal calls exported once after sourceName collection; failure calls retained a ValueError cause and performed **zero ExportToString calls**.

## Actual scoped execution

Command from repository root:

```text
python -B outputs/output-observation-20261014/review/budget-independent/probe.py
```

Final exit **0**. Scoped collector module: **41 tests, 0 failures, 0 errors, 0 skips**. These are bottom USD object tests only, not the repository fullsuite. Additional independent probes verify exact 128 traversal, indexed byte/work early refusal, and four addon version/outcome combinations. The addon probe compiles the exact AST function and error class from the shipped addon; only bottom `hou`/USD APIs are explicit substitutes. It does not import/run the full addon startup, replace the collector, invoke a formal producer, launch a supervised process or claim an end-to-end formal integration result.

Evidence: [probe.py](budget-independent/probe.py), [evidence.json](budget-independent/evidence.json), [scoped-tests.log](budget-independent/scoped-tests.log). The implementer's `budget/final-run.json` and `final.stderr` also record 41 successes on matching three-file hashes; independent evidence above additionally binds the addon. Current package/controller bytes were directly compared and are **exactly equal**. All four reviewed source hashes were unchanged before/after the final probe.

## Actual source binding (SHA-256)

| File | SHA-256 |
|---|---|
| packages/houdini-bridge/src/houdini_bridge/render_color_facts.py | d8ad988cb32115366b68195f025f54ba25158403c187c53b1cbd2ccf4591801d |
| controller-entry/client/houdini_bridge/render_color_facts.py | d8ad988cb32115366b68195f025f54ba25158403c187c53b1cbd2ccf4591801d |
| tests/unit/test_render_color_facts.py | e129cdaa46e5949e715e2161198bc559d06cb5ed6892e14fcc3c282e4886c6ac |
| plugins/houdini/_impl/houdini_bridge_addon.py | 72d2f3074a869f738d5da0c4a24f61d1f4dbf3053e3467e916c224328b907c61 |

## Explicit limits

Native API return allocation, `GetAttributes`/`GetTargets`/`Attribute.Get` materialization, native call latency and production peak memory are **NOT PROVED**. Earlier addon relationship/light preflight and successful `ExportToString` are outside the collector budget; this review makes no whole-stage/whole-producer resource guarantee. Installation, actual Houdini/Nuke host behavior, model route, visual and production acceptance are **NOT_RUN**. No real DCC, model, simulation, cache, render, formal process or fullsuite ran. Full 16-domain M1 and effective writer/filter/AOV/alpha facts remain incomplete.
