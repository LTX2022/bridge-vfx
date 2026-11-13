# Independent review, pre-freeze

Current status: BLOCKED_SCOPED. No FINAL_FROZEN received. Production and test implementation files were not edited by this reviewer.

## R01 — late downstream state/cook-error drift is returned as coherent observations (P1)

Source: plugins/houdini/_impl/houdini_bridge_addon.py `_fx_geometry_output_evidence`, final validation around line 8789. Bound addon SHA256: `5d511b2ef0f1bbf024e6ad2913f294d483c0fca59ce38f9959c76eecb50debd3`.

Actual command: `.venv/Scripts/python.exe -B outputs/geometry-observation-20261013/review/probe_output_scope.py`. Exit 0. Raw log: `probe-output-scope-v1.json`, including all four production SHA256 values before/after; source_unchanged=true.

The probe runs the actual wiring fixture build/client/addon, actual ownership lease and registry, and actual new geometry collector. It injects only explicit static bottom HOM geometry, errors/editability/bypass and inputGeometry APIs. It predicts no deformation and creates no success receipt. Both 21.0.631 and 22.0.429 have one normal case and three negative cases.

Reproduction: during the final `instance.inputGeometry(1)` read, set previously captured scatter to bypassed, noneditable, or make `scatter.errors()` nonempty. Each negative case returns all six outputs, missing=[], and all five `matching_observed_data=true`. The fault remains active at return. The normal baseline also returns those facts with no active fault.

Cause: before/after `_fx_geometry_observations` checks the deformation trio, while the helper's final six-node validation checks identity/session and wiring but omits final bypass/editability and errors of previously captured nodes. The per-capture error check only inspects its current destination. Later lazy reads can invalidate earlier observations without refusal.

Required correction by implementation owner: fence final native type/editability/bypass/error facts for all six nodes, and ensure a late native error invalidates the affected output/consumption or refuses the operation. Keep status BLOCKED regardless of these software checks. Re-run only this short independent probe after correction, followed by final SHA-bound checks after FINAL_FROZEN.

Retest: same actual command, `probe-output-scope-v2.json`, exit 0, source_unchanged=true; addon `346f79a91fe4a001c205a0b45a9391b747bfbdbe078bc1b010f2834bc8306202`. Both normal cases return BLOCKED; all six negative cases now refuse with GEOMETRY_CONTEXT_CHANGED. R01 is closed for that source. Final-frozen source binding is still pending.

## Proven limits

The status remains BLOCKED/raw_geometry_observations even in the normal static probe. This is appropriate: identical injected geometry cannot prove an actual VEX deformation or real Copy to Points execution. No real DCC, HY3, model, solver, cache or render was started. Further collector, lazy-context, full budget and frozen-source checks are pending; this pre-freeze report is not final acceptance.

## R02 — complete frame/total geometry-output wrappers exceed declared byte budgets (P2)

Actual commands: `.venv/Scripts/python.exe -B outputs/geometry-observation-20261013/review/probe_output_budget.py` and the same command with `690 12`. Exit 0; raw logs `probe-output-budget-v1.json` and `probe-output-budget-v2.json`. The latter binds addon SHA `346f79a91fe4a001c205a0b45a9391b747bfbdbe078bc1b010f2834bc8306202`, unchanged during the probe. It uses actual helper, ownership, Host/Registry and collector, with only static bottom native geometry (four ordinary string point attributes; 5 points; no prediction).

Both builds with 4000-byte static strings return individual frames of 906672 bytes, exceeding the 512 KiB frame-bundle budget declared in agent-collector/RESULT.md. More importantly, both builds with 690-byte strings and 12 frames return complete geometry_outputs of 2125863 bytes, exceeding the actual 2097152-byte request budget; remaining=0. This excludes unrelated frame_nodes/native_geometry_readback, so it is a direct overrun of the new geometry-output collection alone.

Cause: capture subtracts serialized individual observations, but final wrappers include connections, input/output labels, consumption, deformation comparison, binding, missing and missing_evidence without accounting. No complete frame limit is applied.

Required correction: bound canonical serialization of the complete per-frame output and cumulative output envelope; include framing/metadata and reserve room for explicit missing/blockers. When budget is exhausted stop further raw output/input acquisition rather than append unbounded full records. Never fill absent observations with defaults or promote BLOCKED. A stricter per-frame requirement can be clarified in the implementation owner's final report, but the configured 2 MiB complete-output cap must be effective.

## R03 — actual host-pack parameter fence is empty (P1)

Source: helper `parameters()` uses `requirement.get('parms', ())`. The actual addon host overlay `native_domain_registry.overlay_host_pack` preserves `required_parms` lists of aliases; the separate core overlay translates them to `required_parameter_aliases`. Neither overlay declares `parms`.

Actual independent command: `.venv/Scripts/python.exe -B outputs/geometry-observation-20261013/review/probe_output_scope.py late_seed late_scale`; exit 0, raw log `probe-output-parameter-v3.json`. Addon SHA `47cd1f1f46c02afaadbff616603f56154d1c884bb037d1626a26bdebdb65feaa`; source_unchanged=true. Both builds demonstrate actual bottom parameter mutations on the last instance.inputGeometry(1): scatter.seed 0→1 and instance_transform.scale 1.0→2.0. All four cases nevertheless return six outputs, missing=[], five matching=true. The actual requirement shape and observed before/after values are in the log.

Required correction: resolve actual required_parms aliases with existing target resolution and collect their complete observed facts; compare after all lazy reads. Keep explicit unavailable markers and BLOCKED status. Verify seed/scale drift refuses, and a normal return includes nonempty observed declared parameter facts. Do not use core-pack alias spelling at this host boundary.

Probe audit: parameter-v1 and parameter-v2 initially tried incorrect declaration-key access before mutating anything; their mutation={} and GEOMETRY_NATIVE_OUTPUT_UNAVAILABLE show a probe setup error, not a valid seed/scale guard result. v3 corrects this using actual native parameter names and records the actual requirement. They remain original diagnostic logs and are not cited as production findings.

## R04 — final lazy node check runs after the last authenticated identity check (P1)

Actual independent command: `.venv/Scripts/python.exe -B outputs/geometry-observation-20261013/review/probe_output_scope.py final_nonce`, exit 0; raw log `probe-output-final-nonce-v1.json`. Addon SHA `47cd1f1f46c02afaadbff616603f56154d1c884bb037d1626a26bdebdb65feaa`; all four checked production source hashes unchanged.

On both builds, after the last inputGeometry observation, the final six-node state check's instance.errors() reads unchanged empty errors but triggers an explicit bottom-boundary launch_nonce change. This occurs after `after = _fx_geometry_observations(...)` has authenticated the old identity. The helper returns all six outputs, missing=[], and five matching=true under the old binding; the actual nonce has changed and remains changed. No forged normal receipt or mocked Host/Registry is involved.

Cause: the last lazy node state/connection/parameter APIs execute after the last whole-context observation; no concluding authenticated identity/lease/input/program/frame fence follows those calls.

Required correction: close the global authenticated context fence after the final lazy native reads, before returning data/charging the final envelope. Ensure final native reads cannot change the returned binding unnoticed; retain the complete latest original context refusal codes where appropriate. Re-run this two-case short probe. It is within the requested nonce/lazy drift review scope, not a new domain requirement.
