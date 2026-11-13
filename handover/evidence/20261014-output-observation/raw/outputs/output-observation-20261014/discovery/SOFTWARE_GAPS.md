# Producer output observation — bounded read-only discovery

Reviewed 2026-10-14, starting 07:35:57 UTC, within the requested five-minute window. Read root AGENTS.md, README/current handover summaries, OUTPUT_PREFLIGHT_20261013.md and the previous output review/closure. No implementation participation, real DCC, model, render, fullsuite, signing or producer launch. Only this report is written. Two small diagnostic executions used the existing explicit bottom-level USD fixtures in memory and the actual collector, with `python -B -`; they did not run unittest or create EXR/HIP fixtures.

## Confirmed P2: raw USD observations lack an effective total payload budget

Source: `packages/houdini-bridge/src/houdini_bridge/render_color_facts.py:106` (unrestricted gap append), `:145` / `:147` (exception body capture), `:182`, `:211`, `:238` (other native exception capture), `:69` (array conversion), `:232` (filter attribute enumeration). The declared string bound is `MAX_STRING_LENGTH = 8192` at `:12`, but it is applied to normal attribute values, not diagnostics or the complete observation.

**Counterexample A, actually executed:** make the existing `/Vars/beauty.sourceName` bottom-level `Attribute.Get(frame)` raise `RuntimeError` with a synthetic message consisting of `explicit-native-error-fixture:` plus 131072 `X` characters. The real collector returns the whole message in `ATTRIBUTE_READ_FAILED.detail`: detail length **131116**, serialized observation **137510 bytes**, and `entire_native_error_retained=true`. Increasing this one native exception message increases the retained observation without a collector limit. The missing source value stays absent and the alpha gap remains present; this is a boundedness defect, not false readiness. No confidential error text was used.

**Counterexample B, actually executed:** one existing filter with only **4** attributes, each `token[]` containing **128** strings of exactly **8192** characters, returns a **4202955-byte** JSON observation with **no LIMIT gap**. Every individual value satisfies the existing bounds. At the allowed 64 attributes per filter, the corresponding character payload alone can reach 64 MiB; repeated filters/frames and detached copies amplify it. This is an arithmetic consequence of the current limits, not a measured memory-exhaustion claim. No stress run was performed.

The formal caller includes these observations in per-frame configuration at `plugins/houdini/_impl/houdini_bridge_addon.py:13670`. `client.py:172` serializes that configuration for the fingerprint; `:181` copies it into the producer binding; `:289` copies it into each output observation; `:316` serializes the terminal execution fact. `_read_render_store_snapshot` at `client.py:418` reads the complete store without a byte cap. None of these inspected boundaries supplies the missing observation budget. Thus a native read failure or legal filter data can inflate the frozen configuration, persisted operation and later software consumption. Actual producer exhaustion/store failure was **NOT_RUN**.

### Minimal reproduction

Run this from the repository root using `python -B -` with the script supplied on standard input. It reuses only bottom-level USD objects; the actual collector is neither patched nor replaced.

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path('tests/unit').resolve()))
import test_render_color_facts as fixtures
from houdini_bridge.render_color_facts import (
    collect_render_color_facts, MAX_STRING_LENGTH,
)

stage = fixtures.usd_stage()
message = 'explicit-native-error-fixture:' + 'X' * (MAX_STRING_LENGTH * 16)

def failed_get(frame):
    raise RuntimeError(message)

stage.prims['/Vars/beauty'].attributes['sourceName'].Get = failed_get
fact = collect_render_color_facts(stage, frame=1, settings_path='/Render/settings')
gap = next(item for item in fact['missing_facts']
           if item['code'] == 'ATTRIBUTE_READ_FAILED')
print(len(gap['detail']), len(json.dumps(fact).encode()))
assert gap['detail'] == 'RuntimeError: ' + message

stage = fixtures.usd_stage()
filter_prim = stage.prims['/Filters/first']
filter_prim.attributes = {}
for index in range(4):
    name = 'inputs:payload_' + str(index)
    filter_prim.attributes[name] = fixtures.Attribute(
        name, 'token[]', ['X' * MAX_STRING_LENGTH] * 128)
fact = collect_render_color_facts(stage, frame=1, settings_path='/Render/settings')
print(len(json.dumps(fact).encode()))
assert not any('LIMIT' in item['code'] for item in fact['missing_facts'])
```

Actual outputs: A `131116 137510`; B `4202955`. Both diagnostic commands exited 0 because they confirmed acceptance of excessive observation data. These exits are **defect reproduction**, not a software acceptance PASS.

### Small software-only repair suggestion

Bound diagnostics and native names/type strings before retaining them; prefer exception class plus fixed diagnostic rather than unconstrained native exception bodies. Add a shared observation byte/value budget enforced during capture, before building large arrays or serialization. On exhaustion retain an explicit budget gap and the mandatory unresolved writer/filter/alpha facts. Preserve the normal observations and existing fault cases; do not infer missing AOV values or writer semantics. The exact product budget is an implementation decision, not a new requirement guessed by this reviewer.

Extend the existing collector tests with the two bottom-API counterexamples rather than duplicating formal host tests. `tests/unit/test_render_color_facts.py:278` checks individual string limits; `:435` checks a short native error and currently expects its body to survive; `:540` checks filter enumeration failure; `:566` checks invalid individual arrays. None checks oversized native diagnostics or aggregate valid filter payload. Those tests were inspected, not rerun. Mirror changes, if implemented by the owner, must follow the existing package/controller synchronization process.

## Other requested checks and limits

- Missing alpha/filter/effective writer facts remain unconditional in `client.py:242`, `:265`, `:308`; execution metadata remains empty at `:315`. No new false AVAILABLE claim was found by this read-only inspection.
- Frame membership and snapshot/final override path are checked at `client.py:258` / `:262`; OCIO final-path equality is checked at `:269`. The raw color fact itself is copied at `:289` without checking its internal frame/settings/Product/Var association. This is a **static validation omission**, not a demonstrated formal-path defect: the current addon constructs it with the matching frame/settings at `:13670`. A wrong-frame initial-binding counterexample would be a useful owner test, but was NOT_RUN and is not counted as a confirmed finding here. Do not equate this with defeating a previously frozen binding.
- Binding rehash rejection is covered by the existing wrong-frame post-start test at `tests/unit/test_houdini_output_receipts.py:180`; actual signed-terminal comparison and file re-observation remain in `client.py:461`, `:491`, `:508`. These paths were inspected, not executed in this investigation.
- Filter connection traversal is absent from the raw collector, but the formal configuration also fingerprints `stage.ExportToString()` at addon `:13667`; omission alone does not establish a formal binding-drift bypass. No such bypass is claimed.
- Previous OCIO preflight, post-frame context comparison and 17-AOV request-budget findings are excluded: their existing closures are not reopened by this report. Effective husk/writer/filter/AOV/alpha execution facts remain the already documented native gap and are not reclassified as a new software defect.

Software status: one newly reproduced observation-budget defect; no fullsuite or full M1 result. Installation, real host, model route, visual and production acceptance: NOT_RUN.

## Inspected source binding

SHA-256 read during this investigation:

| Source | SHA-256 |
|---|---|
| packages/houdini-bridge/src/houdini_bridge/client.py | 74c309a4cd6fbdfd34174aab60af0b0472806774dffb3a3e6dbac6e2342a8b0c |
| packages/houdini-bridge/src/houdini_bridge/render_color_facts.py | 84754cd9d7d4119973d7f3cc40a6d66d008f8176e531b1e905124956c8e16bb2 |
| tests/unit/test_render_color_facts.py | 09be747edc0a685dbb1a1ae634807cff8285834a5c5b515f16c86a9e19442a6a |

These hashes identify the inspected files; they do not assert that concurrent implementers made no changes. No credentials, environment values or signing keys were collected.
