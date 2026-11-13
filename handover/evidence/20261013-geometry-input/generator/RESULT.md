# Trusted construction inputs: generator scope

Completed only `tools/prepare_workbuddy_graph.py` and the new
`tests/unit/test_graph_construction_inputs.py`. Existing uncommitted work was
preserved. No commits, pushes, real hosts, applications, models, simulation,
cache or render were run. Temporary generated projects were removed by the
tests; this evidence contains no run signing keys or credentials.

The trusted keyword `construction_input_manifest=None` now validates and
deep-freezes explicitly configured inputs through
`vfx_pipeline.graph_construction_inputs.freeze_construction_inputs(value,
verify_files=True)` before destination changes. Only configured inputs add
the field to `control/run.json`; omitted/None inputs leave the old layout,
and explicit `[]` is accepted and recorded. Bundle hashing binds the generated
run manifest. Existing all-Python snapshot copying includes the actual helper.
The model MCP schema, selector and defaults are unchanged.

CLI `--construction-input-manifest` reads an existing JSON file. Syntax errors,
missing files, invalid metadata/content/paths and explicit JSON null fail before
preparation. The shared helper enforces the agreed 32-item, 64-KiB basis,
8-MiB other-file and 32-MiB total limits; generator validation delegates to it.

## Actual validation

Interpreter: project `.venv/Scripts/python.exe`, Python 3.11.9.

- `baseline-20261013-153940.log`: actual pre-edit formal generator invocation
  reproduced the unsupported construction-input keyword without creating the
  destination or parent. The reproduction harness exits 0 only for that failure.
- `pure-group-20261013-154245.log`: **8 tests passed, zero failures/errors/skips**;
  unittest 11.177 seconds, logging wrapper 11.575 seconds, actual exit code 0.
  Command: `.venv/Scripts/python.exe -B tools/run_logged.py --log-dir
  outputs/geometry-input-20261013/generator --name pure-group --
  .venv/Scripts/python.exe -B -m unittest discover -s tests/unit -p
  test_graph_construction_inputs.py -v`.
- The group runs the real `app=None` generator, verifies run/bundle content,
  imports the helper from the actual generated snapshot in an isolated Python
  process, checks compatibility, and rejects metadata, changed content/size,
  unsafe/missing/hard-linked paths, budgets and CLI errors before new-parent
  creation or existing-destination alteration. It uses no trust-hook mocks.
- Scoped `git diff --check` passed.

Current source SHA256 after the pure group, excluding collaborators' later work:

| File | SHA256 |
| --- | --- |
| `tools/prepare_workbuddy_graph.py` | `7ec064b9f320954c942ddd5e9a7200af24c68ce7b893af4a597a3fe772505ddd` |
| `tests/unit/test_graph_construction_inputs.py` | `4c3e146e5aa9ef0ec41352cfea096e814e6290c2392754db3cc68163d9d3fb57` |
| Read-only helper `packages/vfx-pipeline/src/vfx_pipeline/graph_construction_inputs.py` | `b0b52c4776439f6727bb371d80dd5a9989e5dc8a4a922d5c92213f8b31bad4f8` |

No full16 M1, installation, real-host, model-route, visual or production
acceptance is claimed. Main owns facade/service/worker/addon integration.
The available app messaging tool rejected messaging the native ancestor; no
native collaboration messaging tool was exposed. The actual helper was then
read directly to resolve the fixture interface (`asset_id`, ordered `index`,
local identity, bytes, SHA256 and semantic role), with no user question needed.

## Files produced

- `tools/prepare_workbuddy_graph.py`
- `tests/unit/test_graph_construction_inputs.py`
- `outputs/geometry-input-20261013/generator/reproduce.py`
- `outputs/geometry-input-20261013/generator/baseline-20261013-153940.log`
- `outputs/geometry-input-20261013/generator/pure-group-20261013-154245.log`
- `outputs/geometry-input-20261013/generator/RESULT.md`
