# Independent G03 P2 closure — 2026-10-13

This separate closure supersedes the P2 disposition in the preserved [initial output/G03 review](output-and-geometry.md), whose original SHA-256 is `cb9e9433e302f44e1b4815fed2b6cd0b8b55ff35a48bb992ffd5dc4ca0516d93`. The original finding, reproduction and initial hashes remain unchanged there. This document records only the affected fix and previously completed independent recheck; no AOV suite was repeated.

The minimal source fix adds a copied current host identity to the existing sealed context. The unchanged planner seal and exact context comparison enforce it before prepare, without new registry logic or guessed rest provenance.

## Independent P2 closure — 2026-10-13 04:52 UTC

**P2 CLOSED on the final hashes below. No confirmed P1/P2 remains in this bounded component review.** This supersedes the initial open finding, not the component's missing production/native evidence.

Read-only inspected the minimal fix at `native_geometry_controls_host.py:161`: `_context()` includes `host_identity=copy.deepcopy(binding['host_identity'])`. The unchanged existing planner serializes/seals full context JSON and `validate_plan()` compares it exactly, so prepare cannot bind an old plan to a new identity. No registry or provenance fallback was introduced. The new host test at line 482 covers both versions × scene_epoch/launch_nonce/process_generation; each reissues the real addon current lease and asserts old prepare fails without writes, then exercises new-plan write/restore.

Independently reran the affected host+program suite: **28 methods (15 host + 13 program), no failures/errors/skips, exit 0, 9.791s**. Before/after SHA-256 values for host, tests, planner and addon match exactly. Independently exercised 10 cases (both versions × epoch, nonce, generation, PID, session ID), using the real existing addon lease/identity/channel helpers with explicit bottom HOM fixture: old prepare raises `GEOMETRY_CONTEXT_CHANGED`, zero native writes, no snapshot allocation; new plan writes 8 under `BLOCKED`, restores actual canonical amplitude 0 and releases its snapshot. Frozen plan identity remains unchanged.

| Final source/dependency | SHA-256 |
| --- | --- |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | 6075295624a2f5a80ce67ac7a746d155efab25872be493bbf6f388c205fd8327 |
| tests/unit/test_native_geometry_controls_host.py | 0e06a4b6fe03c60806c7ca1c86f5429df8a087ef86e4eb0b3264befea64d86f1 |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py | 6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf |
| plugins/houdini/_impl/houdini_bridge_addon.py | d81370c0fdc2b1287460b0eb9ef5349df08ef718fcddac50b9d893095ea59fbb |
| controller-entry/client/houdini_bridge/native_geometry_controls_host.py | 6075295624a2f5a80ce67ac7a746d155efab25872be493bbf6f388c205fd8327 |

The mirror is independently confirmed byte-identical. Collector/source/test hashes remain those from the initial accepted collector review; no collector revalidation was needed for this G03-only fix.

Main's affected run was independently inspected, not rerun through its wrapper:

```text
COMMAND: C:/Users/32200/Desktop/Agent/skill/Bridge/.venv/Scripts/python.exe -B outputs/all-domain-20261009/run_tests.py batch-20261013-g03-plan-identity test_native_geometry_controls_host test_native_geometry_controls_program
JSON: tests_run=28 failures=0 errors=0 skipped=[] exit_code=0 source_unchanged=true elapsed_seconds=9.85899999999674
LOG: Ran 28 tests in 9.606s / OK
JSON_SHA256: 47503311c2c04206fc1492959d126249d35dbd768210c11b7e7ce7a1738608ee
LOG_SHA256: c5d44f80164fcecdba806ab9e828477f031908197ef10fc4d37ee3d60b8d9fbc
```

All four relevant current file hashes match both maps in `outputs/all-domain-20261009/batch-20261013-g03-plan-identity.json`. Historical 85-method integration evidence below binds the pre-fix host/test hashes; the 28-method affected run binds this final fix. No whole-M1 or latest formal-runtime verdict is inferred from either.

Exact independent affected-suite command (repository cwd):

```powershell
@'
from pathlib import Path
import sys,unittest,hashlib
paths=('packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py','tests/unit/test_native_geometry_controls_host.py','packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py','plugins/houdini/_impl/houdini_bridge_addon.py')
before={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in paths}
print('SOURCE_BEFORE',before,flush=True)
loader=unittest.TestLoader()
suite=unittest.TestSuite(loader.discover('tests/unit',pattern=pattern) for pattern in ('test_native_geometry_controls_host.py','test_native_geometry_controls_program.py'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
after={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in paths}
print('SOURCE_AFTER',after,flush=True)
assert before==after,'SOURCE_CHANGED'
sys.exit(0 if result.wasSuccessful() and result.testsRun==28 and not result.skipped else 1)
'@ | .venv/Scripts/python.exe -B -
```

Actual independent transcript, chunks `3c9560` + `0663f8`, exit 0:

```text
SOURCE_BEFORE {'packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py': '6075295624a2f5a80ce67ac7a746d155efab25872be493bbf6f388c205fd8327', 'tests/unit/test_native_geometry_controls_host.py': '0e06a4b6fe03c60806c7ca1c86f5429df8a087ef86e4eb0b3264befea64d86f1', 'packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py': '6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf', 'plugins/houdini/_impl/houdini_bridge_addon.py': 'd81370c0fdc2b1287460b0eb9ef5349df08ef718fcddac50b9d893095ea59fbb'}
test_actual_attribute_storage_values_topology_and_budgets_are_checked (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_actual_attribute_storage_values_topology_and_budgets_are_checked) ... ok
test_foreign_empty_or_canonical_snippet_is_never_adopted (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_foreign_empty_or_canonical_snippet_is_never_adopted) ... ok
test_initialization_userdata_failure_revokes_and_leaves_no_registration (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_initialization_userdata_failure_revokes_and_leaves_no_registration) ... ok
test_lease_takeover_and_launch_epoch_changes_reject_writes_and_rollback (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_lease_takeover_and_launch_epoch_changes_reject_writes_and_rollback) ... ok
test_missing_provenance_hook_or_fact_has_no_default_or_cook (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_missing_provenance_hook_or_fact_has_no_default_or_cook) ... ok
test_owned_initialization_parameter_write_zero_and_full_rollback_both_builds (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_owned_initialization_parameter_write_zero_and_full_rollback_both_builds) ... ok
test_partial_setter_and_postwrite_source_failures_restore_native_state (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_partial_setter_and_postwrite_source_failures_restore_native_state) ... ok
test_plan_and_descriptor_tampering_and_value_only_snapshot_are_rejected (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_plan_and_descriptor_tampering_and_value_only_snapshot_are_rejected) ... ok
test_plan_rejects_reissued_host_identity_before_prepare (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_plan_rejects_reissued_host_identity_before_prepare) ... ok
test_recreated_adapter_authenticates_persisted_basis_without_reinitializing (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_recreated_adapter_authenticates_persisted_basis_without_reinitializing) ... ok
test_required_layout_and_explicit_rest_coordinates_are_not_inferred (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_required_layout_and_explicit_rest_coordinates_are_not_inferred) ... ok
test_rollback_failure_is_reported_but_userdata_restore_is_still_attempted (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_rollback_failure_is_reported_but_userdata_restore_is_still_attempted) ... ok
test_snippet_and_scope_channel_drift_reject_before_write (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_snippet_and_scope_channel_drift_reject_before_write) ... ok
test_stale_source_input_frame_and_graph_fail_before_feedback_mutation (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_stale_source_input_frame_and_graph_fail_before_feedback_mutation) ... ok
test_userdata_is_not_server_registration_and_malformed_records_fail_closed (test_native_geometry_controls_host.NativeGeometryControlsHostTests.test_userdata_is_not_server_registration_and_malformed_records_fail_closed) ... ok
test_actual_parameter_gates_drivers_menu_and_types_refused (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_actual_parameter_gates_drivers_menu_and_types_refused) ... ok
test_basis_graph_ownership_and_connection_drift_refused (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_basis_graph_ownership_and_connection_drift_refused) ... ok
test_collectors_require_independent_inputs_and_never_acquire_or_cook_geometry (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_collectors_require_independent_inputs_and_never_acquire_or_cook_geometry) ... ok
test_empty_or_unregistered_owned_driver_is_never_adopted (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_empty_or_unregistered_owned_driver_is_never_adopted) ... ok
test_formal_controls_still_blocked_both_versions (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_formal_controls_still_blocked_both_versions) ... ok
test_invalid_control_values_and_missing_basis_refused (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_invalid_control_values_and_missing_basis_refused) ... ok
test_observed_value_not_request_echo_and_program_tampering_refused (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_observed_value_not_request_echo_and_program_tampering_refused) ... ok
test_positive_endpoints_only_write_owned_snippet_and_read_actual_parameter (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_positive_endpoints_only_write_owned_snippet_and_read_actual_parameter) ... ok
test_same_build_operator_fields_ports_and_approved_original_digest (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_same_build_operator_fields_ports_and_approved_original_digest) ... ok
test_seal_context_and_snapshot_mutation_block_apply_and_rollback (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_seal_context_and_snapshot_mutation_block_apply_and_rollback) ... ok
test_source_normals_ids_storage_topology_and_axes_refused (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_source_normals_ids_storage_topology_and_axes_refused) ... ok
test_token_and_index_menu_representations (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_token_and_index_menu_representations) ... ok
test_zero_uses_upstream_rest_not_previous_output_and_guarded_rollback (test_native_geometry_controls_program.NativeGeometryControlsProgramTests.test_zero_uses_upstream_rest_not_previous_output_and_guarded_rollback) ... ok

----------------------------------------------------------------------
Ran 28 tests in 9.791s

OK
SOURCE_AFTER {'packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py': '6075295624a2f5a80ce67ac7a746d155efab25872be493bbf6f388c205fd8327', 'tests/unit/test_native_geometry_controls_host.py': '0e06a4b6fe03c60806c7ca1c86f5429df8a087ef86e4eb0b3264befea64d86f1', 'packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py': '6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf', 'plugins/houdini/_impl/houdini_bridge_addon.py': 'd81370c0fdc2b1287460b0eb9ef5349df08ef718fcddac50b9d893095ea59fbb'}
EXIT_CODE: 0
```

Exact independent identity-counterexample command:

```powershell
@'
from pathlib import Path
import sys, json, os
sys.path.insert(0, str(Path('tests/unit').resolve()))
from test_native_geometry_controls_host import Fixture, load_addon, program, adapter
addon = load_addon()
for version in program.VERSIONS:
    for field in ('scene_epoch', 'launch_nonce', 'process_generation', 'pid', 'session_id'):
        with Fixture(addon, version) as fixture:
            fixture.initialize()
            plan = fixture.host.plan(8, fixture.roles, fixture.pack)
            frozen_identity = json.loads(plan.frozen_context_json)['host_identity']
            snapshot_count = len(adapter._SNAPSHOTS)
            if field == 'scene_epoch':
                fixture.addon._BRIDGE_SCENE_STATE.scene_epoch += 1
            elif field == 'pid':
                fixture.identity[field] = os.getpid() + 1
            else:
                fixture.identity[field] = 'review-new-' + field
            fixture.addon._root_lease_issue(fixture.root, fixture.task, 'sop')
            fixture.set_calls.clear()
            try:
                fixture.host.prepare(plan, fixture.roles, fixture.pack)
            except program.GeometryControlsError as error:
                assert error.code == 'GEOMETRY_CONTEXT_CHANGED', error
            else:
                raise AssertionError('old identity plan accepted')
            assert fixture.set_calls == []
            assert len(adapter._SNAPSHOTS) == snapshot_count
            assert json.loads(plan.frozen_context_json)['host_identity'] == frozen_identity
            item = fixture.prepared(8)
            written = fixture.write(item)
            assert written['value'] == 8 and written['status'] == 'BLOCKED'
            fixture.restore(item)
            restored = fixture.host.observations(fixture.roles, fixture.pack)
            assert program.control_readback(version, restored['context'], restored['parameters'])['value'] == 0
            fixture.host.release(item)
            print(version, field, 'old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED')
'@ | .venv/Scripts/python.exe -B -
```

Actual transcript, chunk `e9c0c9`, exit 0:

```text
21.0.631 scene_epoch old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
21.0.631 launch_nonce old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
21.0.631 process_generation old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
21.0.631 pid old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
21.0.631 session_id old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
22.0.429 scene_epoch old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
22.0.429 launch_nonce old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
22.0.429 process_generation old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
22.0.429 pid old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
22.0.429 session_id old_prepare=GEOMETRY_CONTEXT_CHANGED writes=0 snapshots_added=0 new_write=8 restore=0 BLOCKED
EXIT_CODE: 0
```

Only this review report was edited. No implementation/test changes, formal host run, native DCC, Crowd duplicate review, real geometry cook or model/render operation was performed. G03's three production server hooks remain missing and formal wiring remains absent; `BLOCKED / parameters_only`, no inferred rest provenance and all six missing-evidence entries remain the acceptance boundary.

Software observations only; no formal or real DCC acceptance, Crowd duplicate review or whole-M1 conclusion.

