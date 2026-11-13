# R05 bounded packed geometry collector — software-only result

Source and owned test writing stopped after the `final` run. No Host, addon, old fixture, formal process test, handover, or other shared file was modified by this task.

## Files and frozen SHA-256

- `packages/houdini-bridge/src/houdini_bridge/native_rbd_controls_program.py`: `39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a`
- `controller-entry/client/houdini_bridge/native_rbd_controls_program.py`: `39a548042e63796998722d6439ba40b0fa86482c6b96c954c13ff84b1f741c5a`
- `tests/unit/test_rbd_geometry_collection_bounds.py`: `4015ffc377a68b616647c6eb7a07ed13d4fa43f6e2726deca7a317fa67d664f5`

The two production copies are byte-identical. Before/after hashes for each actual test run are recorded in its JSON file; only owned files are bound, so unrelated parallel edits do not invalidate this scoped result. Existing fixture imports are not frozen by this runner; formal integration acceptance belongs to the central runner.

## Reproduction and validation

Working directory: `C:/Users/32200/Desktop/Agent/skill/Bridge`.

Actual command template:

```powershell
.venv/Scripts/python.exe -B outputs/rbd-host-20261013/collector/bounds-20261013-v1/run_owned.py PHASE
```

| PHASE | Methods | Failures | Errors / skips | Exit | Meaning |
| --- | ---: | ---: | --- | ---: | --- |
| baseline | 22 | 26 failing methods/subtests | 0 / 0 | 1 | Prior-source reproduction; normal samples retained their original digest |
| repair-v1 | 22 | 0 | 0 / 0 | 0 | Intermediate source, not final acceptance |
| repair-v2 | 30 | 0 | 0 / 0 | 0 | Intermediate source, not final acceptance |
| final | 33 | 0 | 0 / 0 | 0 | Frozen source acceptance; 0.141 s unittest time |

Each phase has the full actual log and JSON command, exit code, elapsed time, interpreter, operating system, and before/after SHA. Python is 3.11.9; Windows reports `Windows-10-10.0.26300-SP0`. An initial evidence-runner root calculation was corrected before the baseline run; that setup failure did not execute project tests and is not the collector reproduction.

## Interface and changes

`collect_packed_geometry(node, frame, hou_module, *, output_index=0, input_index=None)` and `GEOMETRY_SCHEMA = bridge.rbd-packed-geometry/1` remain unchanged. Pure velocity basis/plan code remains unchanged. Fixed normal facts have their pre-repair digests on both versions:

- 21.0.631: `07bde8182e30bb0530ef673ea0ae094e6cce0021dc0944ac4434f2e82f9ba2f2`
- 22.0.429: `beec93c86cd0b92b356e81ccbd7fdb010fa31563b472ffd5e3b1f09ff61fdffa`

The collector now preflights live geometry before `freeze(read_only=True)`, then checks frozen geometry independently. Native `pointCount()` / `primCount()` are checked before enumeration. `iterPoints()` / `iterPrims()` are preferred; legacy fixtures lacking them retain bounded consumption of `points()` / `prims()` results. Enumeration stops after at most the remaining allowance plus one sentinel. Attribute metadata is preflighted before native value reads and before freeze; duplicate names within an owner, arrays, unsupported storage, invalid flat tuple values, cycles, invalid point indices, and nonfinite data refuse.

Budgets are shared across root and embedded geometry: 8192 points + primitives; 65536 vertices; 4096 attributes; 1048576 scalar values; 4096 UTF-8 bytes per string; conservative incremental serialized-data accounting and a final exact 2 MiB limit for the entire fact including context and digest. The original root-packed / embedded-polygons restriction is retained; geometry depth is explicitly limited to two levels. String JSON escaping contributes to the serialized byte budget. Values are actual fixed bottom-API facts, never computed from requested velocity controls.

`RBD_NATIVE_SAMPLE_FRAME_CHANGED` is raised for sampling-frame drift. On the input route, native acquisition, freeze, enumeration and all lazy native reads occur while the frame remains the requested frame; restoration is in the outer `finally`. On the direct `geometryAtFrame` route, all native reads must preserve the original global frame, and normal calls never invoke global `setFrame`. Drift, ordinary native exceptions and restoration failures all refuse; restoration is attempted on failure. Host identity/gates/node/wire end checks remain the main implementation owner's responsibility.

## Native documentation and limitations

`same-build-hom.json` records read-only extraction from the installed 21.0.631 and 22.0.429 `houdini/help/hom.zip`, with archive/member SHA and method text/line numbers for Geometry, Prim, PackedGeometry, Attrib, and SopNode. No Houdini or native Python runtime was launched.

HOM attribute enumeration returns an already allocated native tuple. A legacy `points()` / `prims()` fallback also cannot prevent allocations inside the native API itself. Native `freeze`, geometry acquisition, and an individual blocked native call are not preempted by this Python budget; OS process supervision remains necessary for execution time/native memory containment. This result proves bounded Python consumption and rejection paths with explicit bottom APIs, not arbitrary native API execution resource bounds.

The stricter limits intentionally refuse large otherwise valid geometry, very long string attributes, unsupported storage, nested packed geometry, duplicate attribute metadata, or drift. API return shape and normal fact format remain compatible. Real geometry effect, native simulation, formal server lifecycle, installation, real DCC, visual quality, macOS and production acceptance are NOT_RUN by this task. No code commit or push was performed.
