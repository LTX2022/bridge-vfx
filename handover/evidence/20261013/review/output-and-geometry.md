# Independent bounded output / G03 component review — 2026-10-13

Reviewed at 2026-10-13 04:43 UTC; repository HEAD `0a52552f5915375dfb0f3551e08928e9e624390d`.
Working-tree bytes, not HEAD alone, define the review. Only this report is written.
No implementation, tests, shared addon, mirrors or repository documentation changed by this reviewer.
No formal Python/TCP host, real DCC/native binding, simulation/cache/render, HY3 or model execution.
Crowd is excluded. G03 review began after its worker completion message and the explicit follow-up instruction.

## Decision and concrete finding

- Output collector increment: no confirmed P1/P2 in the two reviewed files. Installed/static declarations and the bounded software observations are verified.
- G03 host component: **one confirmed P2; component is not independently accepted without addressing it**. The existing 14 unit methods pass, but the additional counterexample below exposes a missing plan-time host-identity guard.
- G03 remains a partial `BLOCKED / parameters_only` component. The three required server hooks and formal graph integration are absent. Their absence is an acknowledged boundary, not a new claim that the component should invent registry/rest provenance.
- This review does not accept whole M1, installation, formal lifecycle, real host, HY3/model, visual or production behavior.

### [P2] Freeze host identity when issuing the plan, before prepare

Location: `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py:249` (plan) and `:254` (prepare).

`observations()` returns current `binding.host_identity`, but `plan()` passes only version, context and parameters to the sealed planner. The context contains node/source/basis facts, not PID, launch nonce, scene epoch or the complete host identity. `prepare()` accepts the old sealed plan against the current context and then records the **new** binding in its snapshot. Thus later snapshot checks correctly fence changes after prepare, but cannot detect a host identity change between plan and prepare.

Confirmed on both supported builds: initialize and issue a plan at scene_epoch 0; increment the actual addon scene epoch; issue the corresponding legitimate current lease; retain the same live source, registration and carrier; prepare/write the old plan. The old plan is accepted and snippet is changed to amplitude 8 under epoch 1. Reissuing the current lease ensures this is not merely an expired/stale-lease negative case. The fixture does not replace the real addon lease, identity or setter helpers.

A newly authenticated scene transaction must not inherit an old transaction's sealed intent solely because source bytes and node facts coincide. Bind the original complete host identity into the sealed plan or an equivalent trusted process-local host-plan record, and require it at prepare. Add coverage for identity changes before prepare; existing identity coverage changes identity only after a prepared handle exists. No implementation fix was performed here.

Exact reproduction command (repository cwd; Python 3.11.9; explicit bottom HOM fixture only):

```powershell
@'
from pathlib import Path
import sys
sys.path.insert(0, str(Path('tests/unit').resolve()))
from test_native_geometry_controls_host import Fixture, load_addon, program
addon = load_addon()
for version in program.VERSIONS:
    with Fixture(addon, version) as fixture:
        fixture.initialize()
        plan = fixture.host.plan(8, fixture.roles, fixture.pack)
        old_identity = fixture.host.binding(fixture.roles, fixture.pack)['host_identity']
        fixture.addon._BRIDGE_SCENE_STATE.scene_epoch += 1
        fixture.addon._root_lease_issue(fixture.root, fixture.task, 'sop')
        fixture.set_calls.clear()
        try:
            item = fixture.host.prepare(plan, fixture.roles, fixture.pack)
            result = fixture.write(item)
            print(version, 'old_epoch=' + str(old_identity['scene_epoch']),
                  'current_epoch=' + str(fixture.host.binding(fixture.roles, fixture.pack)['host_identity']['scene_epoch']),
                  'OLD_PLAN_ACCEPTED', result['value'], result['status'],
                  'writes=' + repr(fixture.set_calls))
            fixture.host.release(item)
        except Exception as error:
            print(version, 'REJECTED', type(error).__name__, str(error))
'@ | .venv/Scripts/python.exe -B -
```

Actual output, exec chunk `3f8a70`, exit 0 (the repro observes the defect; exit 0 is not an acceptance result):

```text
21.0.631 old_epoch=0 current_epoch=1 OLD_PLAN_ACCEPTED 8.0 BLOCKED writes=[('snippet', 'float deform_amplitude = 8;\nfloat deform_phase = ((@P.x - (-2)) / (4)) * 6.2831853071795862;\n@P += deform_amplitude * sin(deform_phase) * v@N;\n')]
22.0.429 old_epoch=0 current_epoch=1 OLD_PLAN_ACCEPTED 8.0 BLOCKED writes=[('snippet', 'float deform_amplitude = 8;\nfloat deform_phase = ((@P.x - (-2)) / (4)) * 6.2831853071795862;\n@P += deform_amplitude * sin(deform_phase) * v@N;\n')]
```

## Output collector checks

Reviewed implementation delta is exactly two table changes: native `driver:parameters:aov:husk:format` with type `token`, and native `driver:parameters:aov:karma:filter` with type `string`, replacing the documentation anchor `karma:plane:filter`.
Six additional test methods preserve all 26 original methods.

Independently read/hash-checked all ten installed sources in `output/collector-native-basis.json`: eight schema files and two `nodes.zip!lop/rendervar.txt` member bytes. Every SHA and all numbered declaration/excerpt lines matched. No installed executable or binding loaded.

| Installed build | Karma schema / generated filter line | Husk schema / generated format line |
| --- | --- | --- |
| 21.0.631 | 841 / 739: string | 44 / 25: token |
| 22.0.429 | 827 / 824: string | 49 / 36: token |

Installed source SHA-256 (absolute installation roots are `C:/Program Files/Side Effects Software/Houdini <build>`; paths and numbered excerpts remain in the verified manifest):

| Build | Relative file/member | SHA-256 |
| --- | --- | --- |
| 21.0.631 | houdini/dso/usd_plugins/usdKarma/resources/usdKarma/schema.usda | 7d970829be37d60c58d4474dc2e3d1d31f9515a3feb5a910bf28e6e57c70f951 |
| 21.0.631 | houdini/dso/usd_plugins/usdKarma/resources/generatedSchema.usda | cbf5c06d02be9ee1c5e60a1638a524a2da6f03deb4830657102ceaf93ebd6c52 |
| 21.0.631 | houdini/dso/usd_plugins/usdHusk/resources/usdHusk/schema.usda | 3fcfcc5846fcea161ca938a5c7a80b96a2acfd04dc359a432a4c41bc95332627 |
| 21.0.631 | houdini/dso/usd_plugins/usdHusk/resources/generatedSchema.usda | c17d9c9601cefcfcd4a0e154f8d27051b209dd25ed63ef9544549330a1e2e5ae |
| 21.0.631 | houdini/help/nodes.zip!lop/rendervar.txt | 8b89b47153c3da8f8fa2a173a4ee78f18582b91fc2547cb248900a757094d542 |
| 22.0.429 | houdini/dso/usd_plugins/usdKarma/resources/usdKarma/schema.usda | 0ad2f0bd8b57d3339cbafb237ae4604eaf319a9c2b69f159afad003674145ab8 |
| 22.0.429 | houdini/dso/usd_plugins/usdKarma/resources/generatedSchema.usda | eb042695a642a6aaedfade732945943b413b1ca7b54ae593b6df12cf58629f2b |
| 22.0.429 | houdini/dso/usd_plugins/usdHusk/resources/usdHusk/schema.usda | 3360753147a7f0ff1f29d8cda37a831660649b52fb0e62681212f7e73cea59f4 |
| 22.0.429 | houdini/dso/usd_plugins/usdHusk/resources/generatedSchema.usda | f8d861f754ba66b534eb49ac6a8f10af516d8aa7ef302e14e38caa2befcd556d |
| 22.0.429 | houdini/help/nodes.zip!lop/rendervar.txt | d8584b92a5816165bcdd613d4d34bdb25f514e6858c3e4026d4bd4a59cd8bb8b |

Filter payloads are captured unchanged, including malformed JSON; no parsing, execution or fabricated readiness claim is introduced. Attribute reads retain `Get(frame)`, separate RenderVar identity/frame samples, actual authored/fallback flag, strict declared type and payload checks, 8192-character bounds, distinct absent/None/empty gaps, and the existing shared 128-target traversal budget. Invalid documented-anchor/custom channel-layout aliases cannot stand in for native observations. Channel prefix/lower-RGB and format do not prove final EXR channels.

Collector's unconditional OCIO/runtime/filter-execution/alpha missing facts remain. Read-only downstream inspection confirms `client.py:293` still returns `BLOCKED_MISSING_NATIVE_FACTS` with empty completion metadata. This was code inspection, not a formal registration or render run.

Implementer's captured command:
`.venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_render_color_facts.py -v`.

- Before: 32 methods; failures=1, errors=21; exit 1; unittest 0.017s; captured build SHA `0ad0d2401f9d981a43c9e45ea6b6eb888c1323bfb057bf6494d5ab60a0e6de09`.
- After: 32 methods; OK; exit 0; unittest 0.014s; captured build SHA `0c1c498e06897f92be3bb69b0056ed51eeb9958d1cc7c3fc171a596eda2404e2`.
- Independently reran the same bounded test command: 32 OK, no skips, exit 0, unittest 0.014s; raw output is embedded below.
- Scoped `git diff --check -- packages/houdini-bridge/src/houdini_bridge/render_color_facts.py tests/unit/test_render_color_facts.py` exited 0 with no output.
- Before logs were inspected, not rerun by reverting implementation. Concurrent unrelated source edits mean whole-tree before/after hashes are historical run identifiers, not this review's final whole-build acceptance.

## G03 component checks and boundaries

Reviewed only `native_geometry_controls_host.py` and its own unit module; read the existing pure planner/addon helpers and fixture dependencies to assess the interface. No production hook, creation registry or rest provenance was fabricated.

Actual collector checks leased root plus task/build identity; accepts only expected source/deform/transform types under the same owned SOP root; samples session IDs, actual wires and P/N/id storage/values/polygon connectivity; limits points/primitives to 8192 and total vertices to 65536; validates explicit authenticated rest output/frame/space/SU/local +X/input version/hash before mutation. Missing hooks/basis, foreign or unregistered snippets, malformed userData and server-registry rejection fail closed in tested paths.

Plan seals reject altered plan content. Prepare rejects value-only snapshots and retains full native snippet channel state including raw string, keys, expression/reference identity and extrapolation. Write checks pre/post parameter state, source/context, current prepared binding and initialization userData. Restore reuses complete native channel restoration and attempts userData restoration even if channel rollback fails; errors remain failures. Old prepared handles reject identity/takeover/node recreation. These protections do not cover the plan-to-prepare gap in the P2 finding.

Fresh initialization intentionally relies on the enclosing leased build transaction to destroy new nodes after failure. Feedback relies on the enclosing root lease fence and calls restore/release after failures. The adapter does not supply an independent transaction/lifecycle mechanism. New-instance adapter recreation in the unit test is in-process persistence inspection, not save/reopen/new-PID evidence.

Required missing hooks:
`_fx_geometry_source_basis`, `_fx_geometry_source_geometry`, `_fx_geometry_registration`.
The addon currently has no production definitions/wiring for them. Formal source graph still needs the authorized `instance_source:0 -> geometry_deform:0 -> instance_transform:0` carrier and authenticated input/creation services. This review does not request inventing these facts.

Actual VEX/deformed P, preservation of output N/topology/unrelated attributes, downstream consumption, instance point identity/pscale/count/seed, and save/reopen/cross-frame rest stability remain unverified. Returned `readback_verified` proves parameters only; `status=BLOCKED` and all six `missing_evidence` entries remain.

Worker log `geometry/host-unit-python311-channel-guards.log` records Python 3.11.9, 14 methods OK, exit 0, 14.549s, matching before/after host/test/planner/addon SHA values. Its command header uses module name and omits its import-path setup, so the independently reproducible command used here is:
`.venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_native_geometry_controls_host.py -v`.
Independent result: 14 OK, no skips, exit 0, 10.135s. Full terminal output is embedded below. Historical first run retains 13 methods/errors=4/exit 1; final intermediate run retains 14 OK/exit 0. Neither replaces the final channel-guard log.

## Exact byte bindings

| Reviewed source / read dependency | SHA-256 |
| --- | --- |
| packages/houdini-bridge/src/houdini_bridge/render_color_facts.py | 84754cd9d7d4119973d7f3cc40a6d66d008f8176e531b1e905124956c8e16bb2 |
| tests/unit/test_render_color_facts.py | 09be747edc0a685dbb1a1ae634807cff8285834a5c5b515f16c86a9e19442a6a |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | fd803b19c6039daa7094102488c62bd1c553f728e922d5c33f7e337e76549392 |
| tests/unit/test_native_geometry_controls_host.py | c5d4a19953e74cd383daa59a49a48dc4a6e8948377fc632ddb00c3c59bdc6b3f |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py | 6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf |
| plugins/houdini/_impl/houdini_bridge_addon.py | d81370c0fdc2b1287460b0eb9ef5349df08ef718fcddac50b9d893095ea59fbb |
| tests/unit/test_native_geometry_controls_program.py | 3e1e7ca6ecaf31363427d08a759b68af7b6cc52bf00b2b203963979e5d4d8460 |
| tests/unit/test_native_particle_size_host.py | d71be424cdd56fe1afef66917d6d1d15d3a146e4439ae701ecb7490b1d9956ad |
| docs/native-basis/w2-wrangle-convolve-static.json | 5a10fa158ae7e153cbc62054da2895fab32fc8a1a1c527d42d80a9853b05a3f6 |

| Evidence under outputs/batch-repair-20261013 | SHA-256 |
| --- | --- |
| output/COLLECTOR_REPORT.md | ae7e2e3c63cc61ed7d23bb8c0dc8acf7a76e8f1aa8add118244ce58be17b7544 |
| output/collector-native-basis.json | c63fc28565bc1702e51d0ad52dcf5b657c839c02656a2b91b10fbda089799e3a |
| output/collector-before-20261013-122057.log | bc23e37a40d0af323bf3c7ac86fc606b40d0cd52ca18b6ddbbb305dcbaae1e18 |
| output/collector-after-20261013-122223.log | 5e9d230f19dae2b98206c3fc3f9a6bcf1f6d15a4506223c80b05d36e4587effe |
| geometry/host-unit-first.log | c9515abcdd86418021b7833c0cb83a951e2709f8acc17d1244f2ed6bf2b8362a |
| geometry/host-unit-final.log | 99566817f63ef57cdaea9ec2cb55991757b0820410c68a11203f5a059df0d927 |
| geometry/host-unit-python311-channel-guards.log | 66692e0e5b2dec9d5a6a0fa803c2aab14fbe7213104d874a8753f7de179ec4d0 |

## Final frozen component integration evidence

After the final instruction, read-only checked `outputs/all-domain-20261009/batch-20261013-components-final.json` and `.log`. JSON records 85 methods, failures=0, errors=0, skipped=[], exit_code=0, source_unchanged=true, wall time 30.109s. Raw log records `Ran 85 tests in 29.553s` / `OK`. All six reviewed source/test/planner/addon hashes match both `source_before` and `source_after` and the current files. Both collector and geometry host mirrors are byte-identical to their reviewed source files. This was evidence inspection, not another 85-method run.

Exact recorded command:

```text
C:/Users/32200/Desktop/Agent/skill/Bridge/.venv/Scripts/python.exe -B outputs/all-domain-20261009/run_tests.py batch-20261013-components-final test_graph_trial test_native_creation_initialization test_native_geometry_controls_program test_native_geometry_controls_host test_render_color_facts test_intermediate_stash_readback
```

Evidence SHA-256:

- JSON: `14f2de7783f02ebbaaefbbf1258b84688f90b45784cc4cc4e9b3cad49aab6820`.
- Log: `fda84ce43e662d012d2ff1e90b04bdfd00ff354a83e1e96d2d398e3dfb59e48b`.

The 85 passing existing methods do not cover the independently reproduced plan-before-prepare epoch change. The G03 P2 remains open on these exact final bytes. No formal wiring or authenticated production rest-input/registry services are added or assumed.

## Independent command transcripts

Cwd for both commands: `C:/Users/32200/Desktop/Agent/skill/Bridge`; interpreter `.venv/Scripts/python.exe`, Python 3.11.9.
No separate log file was written: only the authorized review report receives these terminal transcripts.

```text
COMMAND: .venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_render_color_facts.py -v
EXEC_CHUNK: d406c1
test_absent_product_color_fields_are_missing_without_inheritance_defaults (test_render_color_facts.RenderColorFactsTests.test_absent_product_color_fields_are_missing_without_inheritance_defaults) ... ok
test_aov_filter_format_and_channel_naming_are_sampled_per_var_and_frame (test_render_color_facts.RenderColorFactsTests.test_aov_filter_format_and_channel_naming_are_sampled_per_var_and_frame) ... ok
test_aov_output_properties_distinguish_absent_none_and_empty_without_defaults (test_render_color_facts.RenderColorFactsTests.test_aov_output_properties_distinguish_absent_none_and_empty_without_defaults) ... ok
test_aov_output_properties_reject_wrong_native_types_and_payload_types (test_render_color_facts.RenderColorFactsTests.test_aov_output_properties_reject_wrong_native_types_and_payload_types) ... ok
test_aov_output_strings_use_existing_bounded_capture (test_render_color_facts.RenderColorFactsTests.test_aov_output_strings_use_existing_bounded_capture) ... ok
test_api_failure_is_recorded_and_targets_are_bounded (test_render_color_facts.RenderColorFactsTests.test_api_failure_is_recorded_and_targets_are_bounded) ... ok
test_authored_flag_and_attribute_identity_are_not_coerced (test_render_color_facts.RenderColorFactsTests.test_authored_flag_and_attribute_identity_are_not_coerced) ... ok
test_corrupted_aov_filter_payload_is_preserved_raw_without_execution_claims (test_render_color_facts.RenderColorFactsTests.test_corrupted_aov_filter_payload_is_preserved_raw_without_execution_claims) ... ok
test_each_frame_reads_sample_and_new_composed_relationships (test_render_color_facts.RenderColorFactsTests.test_each_frame_reads_sample_and_new_composed_relationships) ... ok
test_filter_attribute_preserves_order_without_inventing_relationship (test_render_color_facts.RenderColorFactsTests.test_filter_attribute_preserves_order_without_inventing_relationship) ... ok
test_filter_enumeration_failure_retains_products_and_other_filter (test_render_color_facts.RenderColorFactsTests.test_filter_enumeration_failure_retains_products_and_other_filter) ... ok
test_forwarded_targets_preserve_raw_relationship_order (test_render_color_facts.RenderColorFactsTests.test_forwarded_targets_preserve_raw_relationship_order) ... ok
test_forwarding_failure_retains_raw_targets_and_does_not_traverse (test_render_color_facts.RenderColorFactsTests.test_forwarding_failure_retains_raw_targets_and_does_not_traverse) ... ok
test_help_anchor_and_unverified_channel_layout_are_not_native_usd_facts (test_render_color_facts.RenderColorFactsTests.test_help_anchor_and_unverified_channel_layout_are_not_native_usd_facts) ... ok
test_invalid_absolute_settings_paths_fail_before_native_access (test_render_color_facts.RenderColorFactsTests.test_invalid_absolute_settings_paths_fail_before_native_access) ... ok
test_invalid_boolean_numeric_and_array_values_are_not_facts (test_render_color_facts.RenderColorFactsTests.test_invalid_boolean_numeric_and_array_values_are_not_facts) ... ok
test_invalid_frame_and_settings_path_are_rejected_before_usd_access (test_render_color_facts.RenderColorFactsTests.test_invalid_frame_and_settings_path_are_rejected_before_usd_access) ... ok
test_malformed_and_duplicate_relationships_do_not_traverse (test_render_color_facts.RenderColorFactsTests.test_malformed_and_duplicate_relationships_do_not_traverse) ... ok
test_missing_relationship_and_wrong_target_type_do_not_invent_vars (test_render_color_facts.RenderColorFactsTests.test_missing_relationship_and_wrong_target_type_do_not_invent_vars) ... ok
test_missing_values_have_exact_paths_without_color_or_alpha_defaults (test_render_color_facts.RenderColorFactsTests.test_missing_values_have_exact_paths_without_color_or_alpha_defaults) ... ok
test_namespaced_forwarding_and_unicode_prim_paths_are_preserved (test_render_color_facts.RenderColorFactsTests.test_namespaced_forwarding_and_unicode_prim_paths_are_preserved) ... ok
test_native_karma_string_source_type_is_read_without_schema_coercion (test_render_color_facts.RenderColorFactsTests.test_native_karma_string_source_type_is_read_without_schema_coercion) ... ok
test_native_path_predicates_allow_forwarding_and_refuse_nonprim_targets (test_render_color_facts.RenderColorFactsTests.test_native_path_predicates_allow_forwarding_and_refuse_nonprim_targets) ... ok
test_native_prim_errors_and_identity_mismatch_preserve_other_observations (test_render_color_facts.RenderColorFactsTests.test_native_prim_errors_and_identity_mismatch_preserve_other_observations) ... ok
test_nested_targets_share_one_traversal_budget (test_render_color_facts.RenderColorFactsTests.test_nested_targets_share_one_traversal_budget) ... ok
test_prim_type_is_sampled_once_and_failures_leave_partial_receipt (test_render_color_facts.RenderColorFactsTests.test_prim_type_is_sampled_once_and_failures_leave_partial_receipt) ... ok
test_product_and_var_color_fields_require_native_string_schema (test_render_color_facts.RenderColorFactsTests.test_product_and_var_color_fields_require_native_string_schema) ... ok
test_product_color_fields_are_sampled_independently_of_aov_overrides (test_render_color_facts.RenderColorFactsTests.test_product_color_fields_are_sampled_independently_of_aov_overrides) ... ok
test_reads_actual_relations_types_values_and_filter_order (test_render_color_facts.RenderColorFactsTests.test_reads_actual_relations_types_values_and_filter_order) ... ok
test_unsupported_type_none_empty_and_fallback_are_distinct (test_render_color_facts.RenderColorFactsTests.test_unsupported_type_none_empty_and_fallback_are_distinct) ... ok
test_valid_numeric_boundaries_and_flat_arrays_remain_observable (test_render_color_facts.RenderColorFactsTests.test_valid_numeric_boundaries_and_flat_arrays_remain_observable) ... ok
test_wrong_declared_schema_types_have_no_value (test_render_color_facts.RenderColorFactsTests.test_wrong_declared_schema_types_have_no_value) ... ok

----------------------------------------------------------------------
Ran 32 tests in 0.014s

OK
EXIT_CODE: 0
```

```text
COMMAND: .venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p test_native_geometry_controls_host.py -v
EXEC_CHUNKS: 331694 + 87d12e
test_actual_attribute_storage_values_topology_and_budgets_are_checked (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_actual_attribute_storage_values_topology_and_budgets_are_checked) ... ok
test_foreign_empty_or_canonical_snippet_is_never_adopted (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_foreign_empty_or_canonical_snippet_is_never_adopted) ... ok
test_initialization_userdata_failure_revokes_and_leaves_no_registration (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_initialization_userdata_failure_revokes_and_leaves_no_registration) ... ok
test_lease_takeover_and_launch_epoch_changes_reject_writes_and_rollback (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_lease_takeover_and_launch_epoch_changes_reject_writes_and_rollback) ... ok
test_missing_provenance_hook_or_fact_has_no_default_or_cook (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_missing_provenance_hook_or_fact_has_no_default_or_cook) ... ok
test_owned_initialization_parameter_write_zero_and_full_rollback_both_builds (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_owned_initialization_parameter_write_zero_and_full_rollback_both_builds) ... ok
test_partial_setter_and_postwrite_source_failures_restore_native_state (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_partial_setter_and_postwrite_source_failures_restore_native_state) ... ok
test_plan_and_descriptor_tampering_and_value_only_snapshot_are_rejected (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_plan_and_descriptor_tampering_and_value_only_snapshot_are_rejected) ... ok
test_recreated_adapter_authenticates_persisted_basis_without_reinitializing (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_recreated_adapter_authenticates_persisted_basis_without_reinitializing) ... ok
test_required_layout_and_explicit_rest_coordinates_are_not_inferred (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_required_layout_and_explicit_rest_coordinates_are_not_inferred) ... ok
test_rollback_failure_is_reported_but_userdata_restore_is_still_attempted (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_rollback_failure_is_reported_but_userdata_restore_is_still_attempted) ... ok
test_snippet_and_scope_channel_drift_reject_before_write (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_snippet_and_scope_channel_drift_reject_before_write) ... ok
test_stale_source_input_frame_and_graph_fail_before_feedback_mutation (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_stale_source_input_frame_and_graph_fail_before_feedback_mutation) ... ok
test_userdata_is_not_server_registration_and_malformed_records_fail_closed (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_userdata_is_not_server_registration_and_malformed_records_fail_closed) ... ok

----------------------------------------------------------------------
Ran 14 tests in 10.135s

OK
EXIT_CODE: 0
```

Software unit observations only. Installed files were verified as static bytes; package installation acceptance, formal task-host lifecycle, real DCC, model route, visual and production acceptance are NOT_RUN. No result is promoted to whole M1.

