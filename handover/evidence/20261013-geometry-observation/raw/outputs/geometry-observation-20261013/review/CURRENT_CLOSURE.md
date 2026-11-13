# Independent frozen-source review

Conclusion: **PASS_SCOPED**. All four reproduced blockers R01–R04 are closed on the frozen source below. This conclusion covers the new raw geometry observation helper/collector and software cross-frame context boundary. It does not certify actual VEX deformation, real downstream Copy to Points execution, real DCC or all-domain M1 completion.

The reviewer edited no production, unit-test implementation, fixture or handover files. Only independent probes and reports in this review directory were written. Probe normal paths run the existing wiring fixture's actual build/client/addon, lease, Registry and Host; only explicit bottom HOM geometry/error/parameter/identity APIs are injected. Static geometry never depends on the desired deformation amplitude. No normal success receipt or higher-layer authority was forged. No real DCC/HY3/model/simulation/cache/render was run.

## Frozen source binding

`FINAL_SOURCE_BINDING.json` binds 19 implementation, controller mirror, test fixture and local native-interface files. Final addon SHA256:

`3fc8dc8aac2abd7b6716bcd2f5c4ed7e65a4d69726c6012c9b76fc18c583f53a`

Host: `746d67950a12007461a4d5b4882eed071f41368bc7707254d2ef7ca930e26d9b`.

Registry: `3c1f762a54fbaff37b6c31c1987f84fb15fb79fa864abdc1fc0caa7e54c50e23`.

Collector: `787fe82c90487ecc57024ef5cf3a8f2057be744d0bcf8c65a7b58424ff5c8e9c`.

All three controller mirrors are byte-identical to the package modules. Independent probe production hashes were unchanged during execution, and the closure command verified the current files still match. Final probes started before the FINAL_FROZEN message but executed against this exact unchanged frozen implementation; no unchanged probe was repeated just to move its timestamp.

## Actual independent validation

Python 3.11.9 on Windows-10-10.0.26300-SP0. All commands ran with `.venv/Scripts/python.exe -B` and exited 0. Original command arrays, production SHA values and raw results are retained in the respective JSON logs.

1. `outputs/geometry-observation-20261013/review/probe_output_scope.py none late_bypass late_noneditable late_errors late_seed late_scale final_nonce`: 14 observations (seven on each build). Log `probe-output-scope-final-v1.json`. Both normal returns remain BLOCKED/raw_geometry_observations. All 12 hostile cases refuse; state/seed/scale give GEOMETRY_CONTEXT_CHANGED and the final lazy nonce case gives GEOMETRY_AUTHENTICATED_HOST_REQUIRED. Logged seed/scale and nonce before/after facts prove the injected drift actually happened.
2. `outputs/geometry-observation-20261013/review/probe_output_budget.py 690 12`: two complete 12-frame sequences. Log `probe-output-budget-final-v1.json`. Each complete serialized geometry_outputs is 2096589 bytes, below the configured 2097152-byte cumulative limit. All returned frame debits exactly equal the full JSON result plus frame-key/colon/comma reservation. Remaining=562; one extra comma byte is conservatively reserved overall. The final frame has explicit budget-missing entries; no absent observations become success or defaults.
3. `outputs/geometry-observation-20261013/review/probe_output_budget.py 690 1 2`: two zero-remaining helper calls, accounting for the parent's empty-envelope two bytes. Log `probe-output-budget-zero-final-v1.json`. Both refuse GEOMETRY_OUTPUT_BUDGET_EXCEEDED with remaining=0 and zero output acquisitions; no oversize result returns.
4. `outputs/geometry-observation-20261013/review/freeze_closure.py`: validates all 18 independent observations, exact byte accounting, current source bindings and mirrors, then writes FINAL_SOURCE_BINDING.json. Log `freeze-closure.log`; exit 0.

The implemented limits are **512 KiB per collector observation** and **2 MiB per complete cumulative native_geometry_outputs**. A separate 512 KiB whole-frame cap is not this batch's contract. The budget assertion excludes the pre-existing generic frame_nodes and other evidence bundle fields; this review does not claim a new global cap on the entire legacy RPC response.

## Defect closure

| Finding | Independent baseline | Frozen-source result |
|---|---|---|
| R01 late bypass/editability/error | Both builds returned stale coherent output facts | All six negative cases refuse |
| R02 full wrapper over budget | Both builds returned 2125863 bytes against 2097152 | Complete result <= cap; exact debits; zero budget refuses |
| R03 parameter fence read wrong pack field | Actual seed 0→1 / scale 1→2 unnoticed on both builds | Actual required_parms aliases resolved; all four mutation cases refuse |
| R04 final lazy API nonce drift | Both builds returned old binding after nonce changed | Both refuse authenticated identity failure |

Original failure reports/logs remain in FINDINGS_PRE_FREEZE.md and the versioned diagnostic JSON files. Their BLOCKED conclusions describe historical source, not this current closure. Initial parameter probe setup errors are explicitly distinguished there and are not production findings.

## Remaining evidence limits

No actual native deformed P or mathematical deformation correctness is proven. Observed equality of static input/output data is a data comparison, not proof of real transformation/copy execution. Private geometry attributes, groups and packed/volume internals are outside the collector's public polygon-attribute scope. Actual native cross-frame cooking, real saved-scene execution, visual/output acceptance and full-domain release remain separately BLOCKED/NOT_RUN. The centrally scheduled formal process regression belongs to the implementation owner's separate actual logs; the reviewer did not rerun its 100-second lifecycle.
