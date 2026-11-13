# P01 trusted reopen independent review — PHASE

Only this batch's frozen seed/fresh initialization, checkpoint handoff, completion and reconciliation are reviewed. No production/test/documentation sources were modified. No real DCC or formal OS workers ran. This is not final frozen-source acceptance.

## R01 — P1 terminal HIP drift accepted by Host.end (fixed, PHASE recheck)

`packages/houdini-bridge/src/houdini_bridge/native_particle_emission_host.py`, `Host.end`: originally the final native checkpoint followed the last artifact authorization, so native evaluation could change the HIP fact, yet consume the token and retain issued authority. Both builds reproduced this in `PHASE_PROBES.json` / `PHASE_PROBES_02.json`. Current extra authorization + opaque pointer check refuses it with `PARTICLE_EMISSION_REOPEN_AUTHORITY_REQUIRED`, clears only its issued record and token, and performs no native writes. Recheck in `PHASE_PROBES_04.json` is PHASE until main freezes source.

## R02 — P1 rehashed zero-amplitude checkpoint changes the seed of an unchanged HIP (OPEN)

`plugins/houdini/_impl/houdini_bridge_addon.py`, `_fx_particle_emission_reopen_transaction` (around line 3754), `_fx_particle_emission_reopen_authority` (around line 3728) and `_fx_verify_scene_contract` (around line 15075). The supplied contract checkpoint is registered as the private authority scope; the actual HIP manifest's previously frozen `particle_emission_checkpoint` is not compared to it. Node/parameter-only scene-contract verification does not detect a seed change at percentage 0, where the native rate is undriven and independent of seed.

Reproduction against actual addon `scene.save_hip` and `scene.reopen_task_hip` with explicit bottom HOM fixture, without forged normal receipts:

1. Save registered P01 with `emission_variance=0`, task seed 173.
2. In the negative-test save-record contract change checkpoint basis `task_seed` to 174; recompute basis `content_sha256` and `scene_contract_sha256`.
3. Leave HIP bytes/path and its embedded manifest untouched. Clear process-local authority to exercise actual saved-contract rebind.
4. Call public `scene.reopen_task_hip`.

Both 21.0.631 and 22.0.429 return `particle_emission_restored=true` and a durable `COMPLETED` transition. Actual privately registered basis seed becomes 174. See `PHASE_PROBES_04.json`; `hip_bytes_unchanged=true`, `previous_seed=173`, `authority_seed=174`.

Run `.venv/Scripts/python.exe -B outputs/particle-reopen-20261014/review/probes.py --probe addon_seed_contract_tamper --output FRESH_RECHECK.json` with a fresh output filename to preserve phase evidence. The zero-amplitude case is essential: existing nonzero-expression/hash tampering tests cannot detect this missing HIP-manifest checkpoint binding.

Suggested owner-side fix: compare the full supplied saved checkpoint against the checkpoint stored in the verified loaded HIP manifest before establishing the private reopen scope, and keep that old-manifest binding in authorization/end/reconciliation checks. Maintain missing-checkpoint legacy rules and CAS rollback of issued authority/completion.

## R03 — P1 final checkpoint node-state read can change an earlier birth gate (OPEN)

`packages/houdini-bridge/src/houdini_bridge/native_particle_emission_host.py`, `_checkpoint_capture` around line 502 and `Host.end` around line 638. Final `_checkpoint_nodes(binding)` is performed after the last gate/channel capture, then only `_binding` and the final artifact authorization remain. An actual bottom node-state read changes `constantactivate` to 0 after that earlier gate capture. The issued checkpoint still compares equal to the saved checkpoint, and end consumes the opaque token while retaining the registration.

`PHASE_NODE_DRIFT.json` reproduces the component case in both builds. `PHASE_ADDON_NODE_DRIFT.json` then reproduces both builds against the actual addon normal save/reopen and original `Host.end`/`checkpoint` implementations (passive entry markers only; the mutation is restricted to bottom `isBypassed` API). Both return `particle_emission_restored=true`, `COMPLETED`, but `actual_birth_gate=0`, `registration_retained=true`, `token_retained=false`. No formal OS or real DCC ran.

The concrete producer-side fix must recheck the full earlier native gate/channel/clock facts after final checkpoint node-state collection; preserve the final artifact/identity authorization and opaque pointer CAS. A final `observations()` after checkpoint node-state collection is a narrow candidate fix because it reads the complete earlier native state without another node-state collector after it. Any failure must revert only this issued registration and its exact completed transition back to INTENT.

## Graph handoff helper — PHASE inspected

`_fx_particle_emission_graph_checkpoint` now reads actual task-save records, matches exact HIP path/hash, task, root, graph and old contract digest, compares saved checkpoint against HIP embedded checkpoint, and verifies native scene nodes/channels/wires. `PHASE_GRAPH_HANDOFF.json` used original `run_job` construction/save logic (in-process injected bottom HOM, no OS workers). Both builds accept only the normal registered save case. Missing save, rehashed saved CP, rehashed embedded CP, wrong contract task and wrong contract graph all refuse with `PARTICLE_EMISSION_REOPEN_AUTHORITY_REQUIRED`. This helper-only review does not stand in for final cross-PID public `bind_graph_trial`/normal service evidence.

## Explicit evidence limits

The Host-only terminal-drift probe uses a bottom HOM component's private authorization fixture and is not real HIP/new-PID acceptance. The seed-tamper probe uses real addon normal save/reopen logic and receipts; only its negative corrupted contract is edited. The reopen fixture remains same PID with a new scene/native node generation, not OS-level new-PID proof. Main/formal agents own actual worker lifecycle validation. All runs are phase-specific, hashes are embedded in each JSON; sources can still be changing.
