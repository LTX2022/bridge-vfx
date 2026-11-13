# R05 checkpoint/reopen — early independent findings

Scope: read-only production/tests review, explicit fixed-zero packed HOM boundary only. No source/test implementation edits or real DCC. Final frozen source binding and formal evidence are pending.

## R01 — P2: failed final RBD registration leaves a durable COMPLETED transition

Affected implementation at initial inspection:

- `plugins/houdini/_impl/houdini_bridge_addon.py`: `_fx_rbd_reopen_transaction` creates `_FX_RBD_REOPEN_SCOPES` without `completion` / `transition_operation_id`.
- `_fx_registered_rebind_saved_contract` passes these only to the geometry wrapper. For an RBD manifest, that wrapper yields immediately without opening a geometry scope.
- `_fx_scene_transition_complete` fills `completion['record']` only for `_FX_GEOMETRY_REOPEN_SCOPES`.
- `_fx_geometry_restore_transition_intent` safely requires that exact completion record before reverting a durable completed result. It therefore does nothing for RBD failures after completion.

Actual addon/HOM probes: `probe_completion.py`, `probe_completion.json`. Both Houdini version profiles fail the caller, restore the save store, revoke RBD records/tokens/scopes, **but retain `scene_transitions['rbd-unit-reopen']['state'] == 'COMPLETED'`**:

1. The real completion routine persists its result, followed by an injected OSError.
2. `Host.end(commit=True)` executes the real method; a bottom `Node.userData(PROGRAM_KEY)` read changes the explicit current host nonce. Final native checks reject with `RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED` after completion has already persisted.

This creates contradictory recovery facts: durable completion claims a handoff whose private RBD authority was rolled back. A controller can treat it as successfully completed rather than requiring controlled recovery.

Repair gate: propagate RBD completion context and operation ID into its private scope, capture the actual persisted completion under the same identity checks, then use the existing exact-record CAS restoration on final registration failures. Cover a post-persistence error and late native identity/lease failure. Preserve a concurrently replaced successor completion.

Initial probe process exit: 0. Source changed during concurrent implementation (`unchanged=false`); this is diagnostic reproduction, **not frozen acceptance evidence**. Final verification must bind new hashes after fixes.

## R02 — P2: final native wire read can invalidate an earlier gate while commit succeeds

Actual addon probe: `probe_final_reads.py`, `probe_final_reads.json`, both version profiles.

The probe executes the actual `Host.end(commit=True)` inside the actual saved-HIP wrapper. It marks return from the real `Host.checkpoint`, then injects a one-shot bottom `Node.inputConnections()` side effect on the solver during the final `_capture`: the carrier's actual `exportlist` parameter changes from `v` to `w`. The captured parameter observation was read earlier in that same `_capture`, so `_checkpoint_context(context) == actual` still holds.

Observed outcome: no exception, `rbd_velocity_restored=True`, durable `COMPLETED`, one issued authority record, no token/scope, but actual `exportlist == 'w'`. No expected geometry or private authority callback was fabricated; the fixed bottom geometry is unchanged amplitude zero. Gate validation on a subsequent direct read would fail, contradicting the already issued restore success.

Affected `native_rbd_controls_host.py`: the last single `_capture` in `Host.end` after `_reopen_authorized` lacks another complete current-fact comparison. This is separate from the fixed final authority-callback mutation test, which happens *before* `_capture` and is already rejected.

Repair gate: make final registration check reobserve the complete native facts after later dependency reads, preserving current geometry, parameter/gate, identity/lease and CAS protections. Add a permanent one-shot bottom wire-read mutation regression. No claim of impossible cross-node atomic HOM observations is required.

The same probe's attempted direct write to the immutable transition HIP snapshot was denied by Windows file permissions, followed by refusal, `INTENT`, and empty registration. That attempt is **not** an additional finding. Initial probe test-file SHA changed during concurrent implementation; production hashes were stable; final frozen rerun remains required.

R01 follow-up `probe_completion_after_r01.json`: both failures now restore `INTENT` and clear records/tokens/scopes. Production SHA was unchanged; the concurrently edited test fixture makes that run diagnostic pending final freeze.

## Pending review

- Public save/graph handoff authority, content rehash impersonation.
- Checkpoint/end final context changes, bounded native reads and rollback CAS.
- Direct collection readback, old activation/G03 coexistence and owned-root reopen.
- Final controlled-process lifecycle, exact generated snapshot, two final runner labels.

No conclusion about nonzero VEX, native simulation, macOS, installation or full 16-domain completion.

## R03 — graph handoff cannot mint saved velocity authority from caller-rehashed public data

Code inspection found that the initial graph binding accepted a caller-supplied successful trial receipt plus current HIP hash and opened a private RBD reopen scope from the loaded embedded checkpoint. It did not bind this minting step to an actual registered save receipt or persisted worker completion. The implementation author removed RBD authority issuance from graph handoff: it now requires existing current private RBD authority and exact embedded checkpoint; fresh graphs with no velocity registration remain allowed.

`probe_graph_authority.py` / `probe_graph_authority.json`: actual graph worker constructs/saves/reopens a registered RBD graph; real addon applies zero and issues a legitimate basis. The rejection probe changes the public seed, recomputes basis and program digests and embedded checkpoint, saves through the public unregistered save path, clears current authority, and supplies a deliberately forged successful trial envelope with the new HIP hash. There are **zero task save receipts for that modified HIP**. The public `agent.fx.bind_graph_trial` rejects with `RBD_VELOCITY_AUTHORITY_REQUIRED`. Both inspected production hashes and fixture hash stayed unchanged. This is an abnormal-receipt rejection test, not positive producer evidence.

Old-source end-to-end acceptance was not executed: preliminary setup attempts failed at the fixture's legacy-only carrier-name check before handoff. Thus the initial issue is supported by code inspection; only the repaired-path refusal has frozen execution proof. Final process evidence must show fresh graph construction and registered save/new-PID restoration remain valid.

## R04 — P2 on intermediate source: late native source geometry absent from final captures

Frozen actual addon probe `probe_final_reads_complete_geometry.json`, `unchanged=true`:

- Host SHA `1f3d2f763a5f46bb57e73c7062e05030b7f3791a8f782238b99dc90ea5853ba3`.
- Addon SHA `ad9b3f66ce3c4561d46576a842d569719bb780f1a81041bd2b7e3ede5e02f6cd`.
- Both Houdini 21.0.631 / 22.0.429: the real final checkpoint finishes; a one-shot bottom solver `inputConnections()` call changes a persistent native configure geometry's unrelated `temperature` attribute from 20 to 21 during the final `_capture`.
- The fixed native geometry does not depend on requested control values, uses amplitude zero, and is the same source for configure/carrier/solver input. The live changed native source is precisely what readback later collects. No forged normal authority or expected-output geometry is used.
- `Host.end` / actual addon succeeds: `rbd_velocity_restored=True`, durable transition `COMPLETED`, 1 authority record, zero tokens/scopes.
- Immediately afterward actual `Host.readback` rejects with `RBD_VELOCITY_BASE_GEOMETRY_CHANGED`.

Root cause: the R02 fix adds two `_capture` passes, but `_capture` observes gates/parameters/identity/nodes/wires/userData and never recollects packed geometry. The complete geometry was validated only by the checkpoint preceding those final native wire reads. Thus neither added pass can detect a one-shot source/carrier/consumer geometry change caused during those reads.

Repair gate: after the late native dependency reads, reobserve bounded actual configure, carrier and solver-input geometry and validate it against the authorized saved basis/registration. Preserve identity/lease/frame/gates and final artifact authority checks; rollback the issued private record and durable completion on rejection. Add a permanent bottom native wire-read geometry-change regression. This is a finite observable late change, not a demand for cross-node atomic HOM guarantees.

R02 fixed-gate replay and writable-HIP late byte change are rejected on the same frozen source: gate error `RBD_CHECKPOINT_CHANGED`, transition `INTENT`, empty authority; writable HIP actually changes SHA and fails `RBD_REOPEN_AUTHORITY_REQUIRED`, empty authority. Read-only snapshot writes remain PermissionError diagnostics and are not counted as artifact-change proof.

Final disposition: this chronological R04 is consolidated with the earlier end-capture R02 as final **R03 — CLOSED** in `CLOSURE.md`. New Host SHA `251902f45558a06eacc06533c7e2fb73ab289a3d74893111965d30a6ac3b1779` repeats full geometry checkpoints; `probe_native_geometry_closure.json` rejects the actual one-shot geometry change on both versions, rolls back private authority, and restores INTENT. The intermediate success above is retained as historical reproduction, not evidence of failure on the repaired source.
