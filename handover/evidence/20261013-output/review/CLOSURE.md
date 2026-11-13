# Independent affected closure — 2026-10-13

**P2-1 and P2-2 CLOSED for this bounded software integration. No remaining confirmed P1/P2 within the reviewed batch.** Original findings and failing counterexamples remain in [REPORT.md](REPORT.md) and [counterexamples.log](counterexamples.log), bound to the original addon `e3d221d...`. They have not been replaced with a success narrative. This closure applies to the owner's final addon `c38c5d...` and evidence below; it is not full 16-domain M1 acceptance.

This reviewer made no implementation edits, ran no real DCC/model/render or formal host, and made no commit. Only review artifacts were written. Owner tests supplied the actual supervised software producer execution; the reviewer independently inspected their raw logs, frozen sources, retained runtime results and generated source bytes. No additional full test groups were run by this reviewer.

## P2-1 closure: producer refuses context drift after cook

The addon now re-reads `_fx_render_configuration(node, [frame], output_pattern=record['output_pattern'])` immediately after `node.render`, inside the same root lease fence. It compares the complete original frozen frame, including observed context/cache and raw USD pair values, and raises SCENE_STATE_DRIFT before collecting a frame snapshot/output observation or appending frames_done. It does not replace the start binding. Existing failure handling retains the original task/operation/owner path.

The independent [bounded closure script](closure_counterexamples.py) and [final log](closure_counterexamples_final.log) inspect the actual addon AST to confirm exact frame/override, ordering, same lease and frozen comparison. They are structural checks, not a substitute for producer execution.

The owner's successful [D log](../../all-domain-20261009/output-followup-20261013-context-drift-adopted.log) and [JSON](../../all-domain-20261009/output-followup-20261013-context-drift-adopted.json) run `test_d_parent_ocio_context_drift_during_native_frame_rejects_completion`: **1 method with both H21.0.631/H22.0.429 subcases, zero failures/errors/skips, exit 0, source_unchanged=true, 53.375s wrapper / 52.930s unittest**.

I read both retained `context-drift-result.json` files independently. Each actual prepared/supervised software producer wrote one EXR via its bottom-level RopNode substitute, then changed only the observed Context cache. Both finished FAILED with `native render configuration changed during frame`, frames_done=[], frame_snapshots={}, output_facts={}, completion_metadata_status=BLOCKED_MISSING_NATIVE_FACTS and metadata={}. The frozen cache remains before-native-frame; there is one native-render-call record and an actual frame file. Refusal therefore occurs after the simulated native return and before producer completion proof, rather than before any frame activity.

The adopted test polls public graph_status and repeats graph_trial with the same request/operation to perform the normal adoption before save/reopen/render. It does not relax producer node/readback gates. The earlier pure-client counterexample remains intentionally file-only: a consumer cannot query a live parent HOM/Context. Producer post-cook validation closes the missing boundary; signing and consumer rehashing keep their original role.

## P2-2 closure: bounded optional requests preserve 17 AOVs

The addon passes at most MAX_TRANSFORM_REQUESTS=16 to the unchanged strict collector. It records an observed integer omitted count at `api_facts['raw_usd.transform_requests.omitted']` and inserts PROCESSOR_REQUEST_BUDGET_EXCEEDED into bounded missing_facts. All raw USD observations remain in color_configuration_fact. The four required scope gaps survive the gap cap. Neither budget omission nor an empty dependency list claims closure or writer metadata.

The independent final closure log executes the exact current addon function with explicit bottom-level HOM/USD fixtures for **both version branches**. Both preserve all 17 distinct AOVs, collect 16 requests, record omitted=1, retain required gaps, and pass the actual public validator. The harness reuses only native fixture construction from the original counterexample; the product function and collectors are not mocked. Source hashes are stable during those checks.

The owner's `test_native_render_domains` extension also covers H21/H22 × material/lighting using its normal source/feedback/save/reopen path, correctly named native attributes, all 17 Vars, 16 processors, omitted count/gap and actual validator. All 14 native-render methods and existing formal C passed on the final addon in [review-fixes.log](../../all-domain-20261009/output-followup-20261013-review-fixes.log). Formal C preserves exact override/preflight/output copies, the same recovered operation and native-facts refusal without rebuilding.

## Evidence status; failures preserved

- Original central command: 110 actual methods passed plus one nonexistent sync-module import error; recorded 111 tests, errors=1, exit 1. **The command remains FAIL**, as recorded in REPORT.md.
- Corrected sync plus original formal C: 4 methods, exit 0, source unchanged. This belonged to the pre-fix addon and is not used as post-fix producer proof.
- Post-fix review-fixes command: native-render 14 and formal C passed; D had two startup subcase errors because its generated fixture lacked types import. Recorded 16 tests, errors=2, exit 1; **overall command remains FAIL**. The successful individual affected methods are retained without rerunning them.
- First corrected D command, context-drift-final: two save/readback subcase errors because the new test omitted the normal graph adoption step; 1 method, errors=2, exit 1. This also remains FAIL and is not evidence of post-cook refusal.
- Final adopted D command: successful two-build producer refusal, as detailed above. Only fixture imports/adoption changed between D attempts; implementation and the already-passing native14/C code stayed unchanged.

All relevant owner runs report source_unchanged=true. The collector, client, binding tests and their signed-terminal/byte-validation implementation remain byte-identical to the earlier 110-method run; no unaffected full-group replication was needed.

## Final source and generated-source binding

[final_binding.json](final_binding.json) contains current source hashes, comparisons against the final adopted run's source_before/source_after, retained generated-server hashes, snapshot counts/comparisons, sanitized runtime refusal facts and evidence-file digests. All nine scoped current files match the adopted run before/after. Collector/client mirrors match their package sources.

| Source | Final SHA-256 |
|---|---|
| plugins/houdini/_impl/houdini_bridge_addon.py | c38c5d7257ff51f37a39f0b1f91a531fd85c546117ab775b2e4d918f0778a727 |
| packages/houdini-bridge/src/houdini_bridge/render_ocio_facts.py | dcb6f361cf5452ffdab51e82a8b48f13d1d1df142ce81845f1d25fcdd60244a8 |
| packages/houdini-bridge/src/houdini_bridge/client.py | 74c309a4cd6fbdfd34174aab60af0b0472806774dffb3a3e6dbac6e2342a8b0c |
| tests/unit/test_native_render_domains.py | e1b2f66bfade6f1e1b3d9b31bf3bbed8d6117a70e961218813f995700fadc3f9 |
| tests/unit/test_formal_domain_recovery.py | f7bd2b38f53ab4096fff241deda6e01f971701b933e9542e91a162637bca843c |

The retained final generated `project/control/server.py` files are independently hashed:

| Retained formal case under outputs/all-domain-20261009/formal/recovery | Server SHA-256 |
|---|---|
| runner-1791870654309326600 — post-fix formal C | 389e780575ba19f9edb4bf6012916f19d0e4a50f3b6689ec2841767f0b7d604d |
| ocio-drift-1791871162448760600 — final D H21 | eba26ce016ddec4027625a7ed446c1a4eadd13227cc55cf882281f2c8f17aa25 |
| ocio-drift-1791871188928854600 — final D H22 | 1cdd734eaa64910814d8821ed7ea9db535f273f19bb3c71b4cd248cf647b0140 |

Each retained snapshot contains exactly **132 Python source files**, independently compared byte-for-byte with current repository files; all match. Scoped snapshot addon/collector/client hashes also match the table above. Runtime pycache files are excluded from that source count. No signing keys, credentials or full environment were copied into review evidence.

Software closure is limited to these two findings and the inspected affected paths. Effective writer configuration, full LUT/context closure, processing/AOV override execution and beauty alpha association still lack native facts. Completion remains BLOCKED with empty metadata. Installation, real Houdini/Nuke, HY3/model, visual and production acceptance remain NOT_RUN. Full 16-domain M1 is not PASS. No G03 change was made by this reviewer.
