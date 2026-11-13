# Independent review of frozen G03 addon wiring

Current conclusion: **one open P1 and one open P2; independent acceptance is not granted.** The snapshot-leak P2 and registry commit-failure cleanup are independently closed on the source below. User freeze authorization was received before this conclusion. No production/tests/docs were changed by the reviewer; all reviewer artifacts are confined to this review directory.

## P1 — Input drift after native write prevents rollback of the unchanged owned target

Location: `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py:324`, `Host.restore`. Its first registration verification re-authenticates external input via registry `registration -> _check -> _manifest` before attempting native restoration.

Counterexample on **both 21.0.631 and 22.0.429**, using project `.venv` Python 3.11.9 and the existing addon wiring fixture: initialize through the actual build entry; delegate the bottom native snippet setter to its original implementation, then change only the actual temporary frozen-input file immediately after the native set. Actual post-write validation refuses the changed input. Root/carrier authority and session remain unchanged.

Observed in `round3-venv-execution.log` for both versions:

```text
CANDIDATE_ROLLBACK_FAILED
program_restored=false
state_restored=true
same_node=true
same_session=true
snapshots=0
```

The rejected candidate leaves the amplitude-5 native program paired with the old persistent manifest. Registry verification in `restore` fails on the same changed input, so no native channel restoration is attempted. The restoration handle is then released. This is an avoidable partial write despite an honest rollback-failed error.

Required fix: separate exact-target rollback authorization from acceptance of the failed external source. Continue checking the prepared root lease, native node identity/session and immutable registration before restoring; refuse foreign/replaced targets. Attempt full native channel and initialization-userData restoration on the unchanged owned target even when source revalidation fails. Forward execution must still refuse input drift. Verify pre-write program/state recovery after post-set input drift without manufacturing source trust.

## P2 — Frame guard ends before actual source geometry extraction

Location: `packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py:81`, with unchecked return at `Host.observations:251`. Registry `source_geometry` checks the native frame around `node.geometry(output_index=0)` and returns a live geometry object. Host then extracts points, attributes and topology, labeling them with `provenance['frame']`. Its later registry verification checks identity/input/node sessions but does not check frame.

Actual bottom-HOM counterexample: delegate `Geometry.points()` to its original implementation and set the native fixture frame to 2 during that extraction. `Host.observations` succeeds and its trusted collector reads back value 0 while:

```text
FRAME_DRIFT_ACCEPTED {"claimed_frame": 1.0, "native_frame": 2.0, "trusted_readback": 0.0}
```

This leaves an authoritative rest observation at a frame the host is no longer on; planning/preparation consume that accepted observation. The existing native-read drift guard does not cover the subsequent extraction phase.

Required fix: keep a native frame/identity fence through the completed bounded geometry extraction and observation return, and verify it before a write can rely on that observation. Do not change the frame back silently. A frozen native geometry snapshot may help stabilize values but must not substitute for validating the currently required frame. Add the extraction-time drift counterexample. This finding concerns the explicitly authorized source-basis observation only, not downstream deformation/cook behavior.

Evidence for both open findings: `round3-venv-command.log` / `round3-venv-execution.log`; relevant production hashes were unchanged before and after.

## Independently closed on current production source

- **Registry end(commit=True) failure:** the bottom filesystem injection triggers real registry commit validation, without patching a high-level registry method or faking success. Rejection leaves 0 child nodes, no manifest/state file, 0 scopes/cohorts/transactions/snapshots. A subsequent actual fixture build initializes successfully. `round4-closure-execution.log` confirms this under `.venv`.
- **Rebuild and read-only preflight snapshots:** the revised `_fx_preflight_source_plan_targets` releases returned prepared handles. The enhanced existing rebuild method passed on both native-version subcases, including four successive read-only preflights with no retained snapshots or parameter changes. One targeted method, no broad run. Source before/after identical. The original failing counterexample logs remain intact.
- **No userdata-only trust reconstruction:** isolated existing `test_userdata_only_and_empty_registry_never_reconstitute_trust` passed in `.venv`; no fresh process proof was invented. The PID/nonce/version/scene/session rejection method passed in the earlier bounded run, and main's central fixture log independently records those refusals. Explicit new-PID/save-reopen G03 trust remains unsupported and must fail.
- **No-input behavior:** existing two-version missing-input method passed: build records G03 BLOCKED, snippet remains empty, deformation candidate refuses without changing persistent state. `graph_initialize_registered_domain` supplies no G03 basis and therefore takes that blocked initialization branch. Prior controls are not made dependent on G03 observations unless deformation is requested. Main owns the actual generated/new-PID formal normal-and-refusal process results. Final read of main's `outputs/all-domain-20261009/geometry-wiring-20261013-final-scoped.log` confirms its formal worker/feedback/new-instance-reopen method and three sync methods are `ok`. That 11-method run remains overall FAIL with two native-version failures in the commit-failure injection method (`GeometryControlsError not raised`); user identifies its stale imported fixture module and has corrected it. This review does not call that aggregate run PASS. The reviewer independently exercised actual commit validation via bottom filesystem failure, so its cleanup conclusion does not depend on that unapplied high-level patch.

## Source binding and command record

Final production hashes, identical in rounds 3 and 4:

| File | SHA256 |
| --- | --- |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_host.py | f3197c577d2ef6c2d5ebbe8138f68d171cfa85009ddf7296c13aa9de30ef227a |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_runtime_registry.py | d785815c1fddb14ca47fb85459f1d33f74a1463a0228732f107530ac71b628ac |
| packages/houdini-bridge/src/houdini_bridge/native_geometry_controls_program.py | 6a1c6a325aa6376a6ada9ecd3954e12e6465f394f906211e7f246501964309bf |
| packages/houdini-bridge/src/houdini_bridge/native_particle_ocean_geometry_domains.py | 7a5724819b04929b99cf353b44f5a525343423f2289a7565fa786b2494933068 |
| plugins/houdini/_impl/houdini_bridge_addon.py | 66a099801e077bba0175267634589a9eed341f72a943e13c5e9867e10f7a8e46 |

Round4 also verifies the three controller mirrors have the same hashes as their corresponding package host/program/domain sources. Registry is an addon-side module; this does not claim an extra controller registry mirror exists.

Final read after main's test-only fixture correction: addon remains `66a099801e077bba0175267634589a9eed341f72a943e13c5e9867e10f7a8e46`; current addon-test file is `2483d70825d60f477d4821ba3c8f4caa454ba10d695e060f80d4b5dbb73bc09d`. Independent round3/round4 executions bind the earlier test hash in the table below, not this later fixture revision. Production conclusions remain bound to the unchanged production hashes. Main's corrected single-method rerun was pending at this report's delivery.

Fixture/test hashes used in final independent execution:

| File | SHA256 |
| --- | --- |
| tests/unit/test_native_geometry_addon_wiring.py | 3be640c6d6eb583c1e02538f65db1350f569bc40f1bb2c60ebae18e73fbb3b79 |
| tests/unit/test_native_geometry_runtime_registry.py | 61fe48eb49bafe1ce6de69751e6d8ec5d9dad98950ee3319ddc8a605662ca9dc |
| tests/unit/test_native_geometry_controls_host.py | 6440346f892bb4152980c7bcafc0ccdefcc3311216de4516ac3742979eb6c8de |

Exact shell entry commands (full executable Python payloads retained in each command log):

```powershell
Invoke-Expression (Get-Content -LiteralPath outputs/geometry-wiring-20261013/review/round3-venv-command.log -Raw)
Invoke-Expression (Get-Content -LiteralPath outputs/geometry-wiring-20261013/review/round4-closure-command.log -Raw)
```

Both use `C:\Users\32200\Desktop\Agent\skill\Bridge\.venv\Scripts\python.exe -B -`, Python 3.11.9. No process-formal tests, DCC executables, models, simulation, caching or rendering were started by this reviewer. The native geometry and parameter APIs are explicitly replaced only at the existing bottom fixture boundaries. Round4 imports registry before entering Fixture and injects only bottom `Path.lstat`; its trigger flag proves the failure injection actually applied.

Original round1/round2 ran global Python 3.12.10 and exited nonzero. Their raw logs remain: round1's auxiliary post-restoration input observation failed at a filesystem signature guard; round2's userdata-only test failed during initialization and did not reach its trust assertions. Those failures are not relabeled PASS or used as project-interpreter acceptance evidence. Round3 isolates userdata-only on `.venv` and passes. Main's earlier diagnostic `source_unchanged=false` run and failing central/final-scoped logs are not accepted as final all-pass evidence.

Software findings only. Installation, actual host, model route, visual and production acceptance remain separate and unproven. Review is available for narrowly scoped fix/new-hash closure of the two remaining findings.
