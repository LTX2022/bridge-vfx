# P01 scoped recheck — R02/R03 closed; R04/R05 open

Historical PHASE report, superseded by `CLOSURE.md`. R01–R05 are now CLOSED_SCOPED. Final namespace rule shares saves/snapshots and isolates mutable ops/leases; the old all-facts-shared recommendation below is superseded. Retained findings and old reproduction logs are audit history, not current open status or current-source PASS.

Original R02/R03 probes were rerun without modifying their fault placement or production/test code. See `R02_R03_RECHECK_01.json` (both versions).

* R02: the self-rehashed zero-amplitude seed 173→174 in the old save contract is refused with `PARTICLE_EMISSION_REOPEN_CHECKPOINT_REQUIRED` before private issue. HIP bytes are unchanged; registration/token are absent; durable state remains INTENT.
* R03: the original last-checkpoint native node-read birth-gate mutation is refused with `PARTICLE_EMISSION_GATE_CHANGED`; issued registration and token are absent. The final `observations()`/private pointer CAS is after the final checkpoint node collector.
* R01: terminal HIP reauthorization fix remains structurally present. Its last original probe passed in `PHASE_PROBES_04.json`; full-group rerun was not performed by this reviewer.

New authorization guard recheck in `AUTHORIZATION_ENV_RECHECK_01.json`: both versions allow actual normal `_fx_store_manifest` identity-only CP update and commit. Changing the actual root-embedded basis, removing actual embedded CP (sidecar unchanged), or replacing embedded identity with a foreign nonce refuses at final private authorization, cleans the issued registration/token and restores exact completion to INTENT. Original HIP bytes remain unchanged in all cases.

## R04 — P2 current P01 reconciliation validates a stale pre-contract checkpoint (OPEN)

`plugins/houdini/_impl/houdini_bridge_addon.py`, `_fx_particle_emission_reconcile_checkpoint` around 4104:

```python
checkpoint = _fx_particle_emission_checkpoint(root, manifest)
...
_fx_verify_scene_contract(contract, task_id)
# only compares the previously captured checkpoint to the saved contract
```

`PHASE_RECONCILE_GATE_DRIFT.json` uses original actual addon normal save, current private registration and original scene-contract verifier, with a mutation confined to the bottom native parameter `eval()` API. While the last parameter `/FX_GEOMETRY_NETWORK/FX_SOURCE/rz` is evaluated by the scene-contract verifier, `emission/constantactivate` changes from 1 to 0. Both builds return `True` from the actual reconciliation checkpoint function despite `actual_birth_gate=0`. No mock normal verification result or fabricated normal receipt was supplied.

This is a reconciliation component proof. It does **not** claim an executed public `scene.reconcile_transition` COMPLETED transition or real OS recovery. Nonetheless the predicate consumed by the public reconciliation completion path affirms particle restoration using facts that predate its final native contract evaluation.

Minimal owner-side correction: perform/reperform the actual complete private checkpoint collection after `_fx_verify_scene_contract` and before affirming equivalence to the saved CP. Preserve missing/checkpoint/legacy rejection and opaque authority; no broad domain changes needed. Recheck only the same `reconcile_probe.py` after assigning a fresh output filename.

## Worker namespace phase limitation

The earlier `AUTHORIZATION_ENV_RECHECK_01.json` equality assertions belong to the first namespace candidate and are now superseded for environment acceptance. Current design deliberately separates worker RPC discovery/runtime directories from primary while sharing the trusted task-contract root and artifact ledger. Do not count historical worker==primary discovery-directory equality as current PASS. Formal OS retry and final immutable-source binding belong to main's central validation.

## R05 — P2 separated discovery roots still separate task saves and leases (OPEN)

Current `GraphJobService._worker_env` correctly gives the worker `control/graph-houdini-instances`, while primary uses `control/houdini-instances`. However current addon `_state_dir()` still returns `Path(override)/instances`; `_fx_task_saves_path` and `_root_leases_dir` use `_state_dir().parent`. As a result shared task contracts remain below different per-process directory names rather than the common control root.

`PHASE_NAMESPACE_ROOTS_01.json` calls the actual worker env, primary env and addon helper implementations, no OS processes. SHA before/after is unchanged. It proves:

* Discovery and runtime are separate, artifact ledger is common (correct).
* Primary task save root: `control/houdini-instances/fx_operations`.
* Worker task save root: `control/graph-houdini-instances/fx_operations`.
* Primary and worker `scene_root_leases` roots are likewise distinct.

The user-described common `_state_dir().parent == control` fact-root adjustment was not present in the reviewed source. Align the actual shared task-contract/lease/operation root while keeping RPC discovery/runtime separate, and update `production_hosts._scene_transition_operation_store_path` consistently if its current hardcoded `control/houdini-instances/fx_operations` target changes. No weakening of saved-contract authorization is needed. Recheck the same `namespace_probe.py` with a new output filename, not a broad repeat.

No production/test/docs writes or real DCC/formal OS execution by this reviewer. All artifacts are restricted to this review directory. Final batch CLOSURE remains pending R04/R05 and the final source freeze, not a request to rerun unchanged 39-test coverage. No other concrete P1/P2 has been found within this batch's reviewed scope.
