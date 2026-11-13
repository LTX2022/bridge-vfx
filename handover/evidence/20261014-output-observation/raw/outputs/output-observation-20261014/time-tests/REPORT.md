# Output configuration time tests — 2026-10-14

Owned writes: `tests/unit/test_render_configuration_time.py` and this evidence
directory only. No production/addon, existing boundary, formal test, or central
runner edits. Test file is finished and frozen for main's subsequent validation.
Test SHA-256: `d89cf9693dc657a25053d7360b85092706a54f178ad1e45906eeec5364a4487e`.

## Actual baseline

Central runner: `outputs/all-domain-20261009/run_tests.py`, with only its in-memory
`HERE` destination redirected to this owned directory. Selected tests belong only
to the new module, requested-time test first, `--failfast`; no imported TestCase
aliases, full suite, or formal process execution.

- `output-time-baseline-20261014.log/json`: exit 1, one error, 17.063 seconds;
  source unchanged. This is a test-authoring error, not a production defect:
  `KeyError: 'driver:parameters:husk:OpenEXR:storage'`. The color collector does
  not expose those OpenEXR attributes. Corrected the test to use its actual
  sampled `productName` observation and retained this original audit evidence.
- `output-time-baseline-20261014-corrected.log/json`: exit 1, one test / one
  assertion failure / zero errors or skips, 21.109 seconds. Both H21/H22 and
  lighting/material completed the requested-time observations before asserting.
  At frames 1 and 1.25, `exr_format.compression` was default-time `none` instead
  of sampled `zip` / `zips`; frame 2 remained `none`. Color `productName` correctly
  read its requested-frame sample. Exact failure: `AssertionError` at the
  `observations == expected` assertion, test file line 124. Failfast left the
  other three methods unexecuted in this baseline.

The corrected baseline is **not immutable-source evidence**: central report
`source_unchanged=false`, 445 source entries; only
`plugins/houdini/_impl/houdini_bridge_addon.py` changed during execution, due to
main's concurrent fix. Preserve the observed failure without promoting this run
to a frozen pre-fix acceptance result.

## Final scoped result

After main reported its addon fix, ran direct unittest only:

```powershell
.venv/Scripts/python.exe -B -c "import runpy; runpy.run_path('outputs/all-domain-20261009/run_tests.py'); import unittest; unittest.main(module=None)" -v test_render_configuration_time > outputs/output-observation-20261014/time-tests/scoped-final.log 2>&1
```

Actual exit 0: **4 methods PASS, 85.158 seconds, zero failures/errors/skips**.
All four methods cover both supported versions (`21.0.631`, `22.0.429`) and both
lighting/material. This run intentionally has no broad all-source hash-stability
claim while other agents work; main owns final centralized frozen verification.

Coverage: integer and fractional frame storage/compression/multipart reads;
valid default versus unsupported sampled tiled/multipart/PIZ refusal;
exact native value types including bool/float-as-int rejection; wrong USD type;
unhashable list/map and missing values; native Attribute.Get RuntimeError mapped
to `BridgeCommandError(RENDER_CONFIG_INVALID)`; a drifting getter proves the
validated compression value is stored after one requested-frame read.

The real `software_host_client`, `constrain_hou`, software render API boundary,
`agent.fx.build_preview`, and addon `_fx_render_configuration` execute. Only
bottom USD stage/attribute APIs are injected; the wrapper exposes its actual
static `.value` for the existing Stage exporter. Neither addon configuration,
upper receipts, graph results, nor color collector are replaced. New software
host state is isolated per fixture; no credentials or old signing keys copied.

Recommended fix, now reported implemented by main: call product Get(frame) once,
validate/store that same observation; require str for storage/compression and
int excluding bool for multipart; translate actual native product API exceptions
to RENDER_CONFIG_INVALID, without catching BaseException. Preserve caller HOM
frame. Main also owns collector ValueError normalization and formal time tests.

Software scoped tests only. Installation, real DCC, models/HY3, simulation/cache/
render, visual and production acceptance NOT_RUN. No full suite or formal process
tests executed by this agent. No further test-source writes or runs planned.
