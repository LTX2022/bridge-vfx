# Independent OCIO integration review — 2026-10-13

Disposition: **two confirmed P2 findings; no confirmed P1; not accepted as defect-free**. This reviewer did not implement the collector, client, addon or corresponding tests. Source was read only. Only this directory's report, counterexample and log were written. No real Houdini/Nuke/HY3/model, formal host, renderer, simulation, install or commit was run by this reviewer. G03 was not changed. Full 16-domain M1 remains incomplete.

## P2-1: post-cook live parent configuration/context drift is not checked

Location: `plugins/houdini/_impl/houdini_bridge_addon.py:13612`, `:13616`, `:13637`; `packages/houdini-bridge/src/houdini_bridge/client.py:274`.

The sole `_fx_render_configuration` call in `_advance_render` occurs before `node.render`. After the cook, `collect_render_output_fact` validates only frozen configuration/LUT file bytes. A persistent change to the observed native context/cache/search/working-dir, HOM configuration selection, or raw USD source/destination pair during the cook is never compared against the start configuration. Even a fresh parent collector returning a different documented Context.getCacheID with identical config/LUT files passes the postframe client collection with the old context. Seal/consumer repeat that frozen-file validation; signing preserves the old observation rather than checking the missing post-cook live observation.

Minimal reproduction: run `.venv/Scripts/python.exe -B outputs/output-followup-20261013/review/counterexamples.py`. `persistent_context_cache_drift_after_precook` changes only bottom-level native Config/Context cache API values, leaves all file facts identical, confirms a fresh actual collector differs, and confirms actual validator/client output collection accepts the frozen context. `actual_addon_postcook_call_order` reads the actual addon AST and confirms the only live configuration read precedes the cook. This does not run a cook/host or claim a full signed-terminal race reproduction. The resulting completion metadata correctly remains BLOCKED; this finding concerns the specified pre/postframe drift guard, not false native metadata readiness.

Fix rationale: re-read `_fx_render_configuration(node, [frame], output_pattern=record['output_pattern'])` after `node.render` within the same root lease fence and compare against the original frozen frame before recording its snapshot/output fact or appending frames_done. Keep the existing frozen binding and failure/owner/scheduler handling; do not rebase the expected configuration. This proves only stability of the parent observations, never effective writer processing.

## P2-2: optional preflight aborts previously accepted 17-AOV configurations

Location: `plugins/houdini/_impl/houdini_bridge_addon.py:12788`, `:12799`; `packages/houdini-bridge/src/houdini_bridge/render_ocio_facts.py:53`.

The addon collects every nonempty raw Product/Var source/destination pair without bounding that list. The collector rejects more than 16 requests by raising ValueError before producing any honest missing-fact observation. The existing single-product render validator and bounded USD observation allow 17 distinct RenderVars. Supplying both raw color attributes on each therefore turns a previously accepted configuration into a submission failure solely because optional parent preflight was enabled. This happens even when HOM/OCIO is unavailable and no processor could be reconstructed. A product pair plus 16 Var pairs has the same issue.

Minimal reproduction: the same script's `existing_17_aov_stage_optional_preflight_regression` executes the exact addon function extracted read-only from the source AST, with explicit bottom-level HOM/USD API substitutes, 17 distinct named RenderVars and correctly named attributes. Without output_pattern it accepts all 17; with output_pattern it raises `ValueError: bounded explicit transform requests required`. The collector, USD collector and client are not mocked. No formal host or operation is launched.

Fix rationale: keep collector input bounds, but make automatically generated optional requests honor that budget while explicitly recording that unexamined pairs remain unobserved. Do not silently truncate or claim closure. Alternatively provide a deliberate supported-render limit with a clear product contract; the current unadvertised ValueError is an integration regression. Add only the missing boundary regression to the owner's existing tests.

## Verified behavior and boundaries

- HOM roles/active views/displays are tuples of strings. No dictionary adaptation is needed. [SideFX official Color documentation](https://www.sidefx.com/docs/houdini/hom/hou/Color.html) matches the reported H21/H22 installed-static shapes.
- [Official OCIO v2.4.2 Python Config binding](https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/v2.4.2/src/bindings/python/PyConfig.cpp#L608) returns `(spaceName, ruleIndex)` and supports the context/source/destination overload. [Official ProcessorMetadata binding](https://github.com/AcademySoftwareFoundation/OpenColorIO/blob/v2.4.2/src/bindings/python/PyProcessorMetadata.cpp#L40) exposes getFiles with len/index support. Current conversions match these shapes; actual target-host bindings remain NOT_RUN.
- Parent source, reloaded_config and explicit_reconstructed_processors_only are explicit. File rules use the final frame override path. Raw source/destination pairs are not promoted to effective precedence, writer color or alpha facts. Legacy material calls omit OCIO collection.
- Three native completion gaps remain required, including Karma/husk beauty alpha association; completion metadata is BLOCKED_MISSING_NATIVE_FACTS and metadata is empty. The independent context counterexample also verifies this.
- File hashing checks regular files, absolute local paths, ancestor symlink/reparse state, descriptor/path identity and read budgets, with cross-platform stat fallback. Existing tests cover config/LUT same-size restored-mtime changes, unsafe paths and growth/reconstruction races. Those tests do not cover live post-cook context drift or the 17-request integration boundary above.
- Frozen start configuration remains inside scene_fingerprint/producer_binding. Existing producer-only signing, terminal exclusive claim, signed original and consumer comparison remain intact. A collector fact/rehashed binding alone does not replace a signed original. Existing B tests cover failed reads keeping scheduler reservations and original-byte restoration allowing release. This reviewer did not repeat those process tests.
- No newly introduced full environment enumeration, exception-message dumping, key copying or credential collection was found. Only bounded API values and exception class names are collected. Synchronous native parser/getProcessor internal IO/time/memory is not bounded by Python hash budgets; that declared limitation remains, not a new readiness claim.

## Actual evidence

Independent bounded counterexamples: [script](counterexamples.py), [raw log](counterexamples.log). Exit 0; three diagnostic cases above; pre/post source hashes identical. This is confirmation of defects, not a PASS for the integration. It imports receipt fixture setup for local EXR/scene files only, not its producer/signing methods. No source edits or formal test duplication.

Main's [components log](../../all-domain-20261009/output-followup-20261013-components-final.log) and [JSON](../../all-domain-20261009/output-followup-20261013-components-final.json): 110 actual methods passed, zero actual method failures; one unittest loader import error for nonexistent test_controller_client_sync. Recorded tests_run=111, failures=0, errors=1, exit_code=1, source_unchanged=true, elapsed=38.032s. **The command failed and is not an overall PASS.** It includes current collector 26, binding 10 and affected old receipt/native/raw-USD/snapshot/retry groups. Earlier B ten-test success used an older collector hash and is not inherited by current source.

Main's corrected [formal-and-sync log](../../all-domain-20261009/output-followup-20261013-formal-and-sync.log) and [JSON](../../all-domain-20261009/output-followup-20261013-formal-and-sync.json): correct controller-entry sync module plus formal C; 4 actual methods, zero failures/errors/skips, exit 0, source_unchanged=true, elapsed=28.938s. Formal C checks exact final override, detached perframe preflight/output copy, native-facts refusal, preserved completed stages/same operation and no rebuilding. This is a bounded software PASS, not closure of the two new counterexamples or full M1.

## Final source binding

These SHA-256 values match the independent counterexample pre/post freeze and main's formal-and-sync source_before/source_after:

| Source | SHA-256 |
|---|---|
| packages/houdini-bridge/src/houdini_bridge/render_ocio_facts.py | dcb6f361cf5452ffdab51e82a8b48f13d1d1df142ce81845f1d25fcdd60244a8 |
| packages/houdini-bridge/src/houdini_bridge/client.py | 74c309a4cd6fbdfd34174aab60af0b0472806774dffb3a3e6dbac6e2342a8b0c |
| plugins/houdini/_impl/houdini_bridge_addon.py | e3d221d76665ff92a642885db99d240e8df552c0abefa4f52f15f8ceb26d87d9 |
| tests/unit/test_render_ocio_facts.py | c67e5085582194860104b7b5f1bd8b501580869b677407202708071acca0c51f |
| tests/unit/test_render_ocio_binding.py | 80431a55cc942c7a1166825455e8c78b7ba01243b29e7a467d8710eff0838bb3 |
| tests/unit/test_native_render_domains.py | 2d75a66ebc0db15ac65fcebfcbceaa37144d9c4cef6f01456416502deaca20bb |
| tests/unit/test_formal_domain_recovery.py | bc71af93738678edf8731e50f66db7cea77b8f1020e414eb6719a42427e8ca76 |
| controller-entry/client/houdini_bridge/render_ocio_facts.py | dcb6f361cf5452ffdab51e82a8b48f13d1d1df142ce81845f1d25fcdd60244a8 |
| controller-entry/client/houdini_bridge/client.py | 74c309a4cd6fbdfd34174aab60af0b0472806774dffb3a3e6dbac6e2342a8b0c |

Bundled collector/client match current package source. Formal C retains its generated controller and input snapshot under `outputs/all-domain-20261009/formal/recovery/runner-1791870025554434200/project/control/`; this reviewer located that retained case after the initial report. Its exact generated-server binding, plus any subsequent owner fixes, will be appended in the affected closure review. Initial findings remain preserved against the hashes above.

Software observation/binding evidence is limited as above. Installation, real host, model route, visual and production acceptance remain NOT_RUN; no full 16-domain M1 PASS.

## Delivery

An authorized attempt to send findings directly to main via send_message_to_thread was rejected because main is this native subagent's ancestor. No native collaboration messaging tool is exposed here. Findings are delivered to main through this report and the final subagent result; no source was patched.
