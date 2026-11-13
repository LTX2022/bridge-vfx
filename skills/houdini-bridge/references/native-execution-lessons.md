# Native execution lessons from checked Bridge cases

Use this when a host, scene observation, save/export or output-registration
step fails. These are bounded case observations from H21.0.631 and the recorded
Nuke route, not proof that another build, model route or full shot is supported.
Use [failure recovery](failure-recovery.md) for operation identity and stopping;
use [specialist simulations](specialist-simulations.md) for solver diagnosis.

## Observe the real parameter representation

- **Parameter observation can cause an error.** A hidden SOPCreate UI expression
  called `inputs()[0]` on an unconnected node; a later camera message carried
  that upstream error. Trace the actual field and expression before changing
  the camera or source geometry. A narrowly justified UI-only field may be
  recorded as `NOT_EVALUATED`; do not suppress arbitrary cook errors or replace
  construction values with defaults. The recorded fix checks path, type,
  template and unevaluated driver together.
  Evidence: diagnosed native failure and scoped software checks in
  official observation report (`handover/OFFICIAL_KARMA_LIVE_RESULT_20261027.md`).
- **Native types are not interchangeable JSON values.** Read the actual menu
  ordinal/token and ramp keys, values and basis for the installed definition.
  Do not compare a menu ordinal with a USD schema string or dump every host
  object with generic JSON serialization. The DiskLight case observed `Menu[2]`
  where the validator expected a string; Nuke `Format` serialization also
  failed before rendering. A preparation exception is not a failed render.
  Evidence: native mismatch followed by software correction in
  axis report (`handover/EXPORT_AXIS_FULL_CHAIN_RESULT_20261027.md`);
  `engineering-chain-20261026-authorized-22/23` driver failure receipts.

## Compare cold output without hiding drift

- **Host-temporary expressions change across processes.** Even a disabled
  output processor can expose a parameter whose evaluated value contains a
  PID/session directory. Freeze a task-owned deterministic destination before
  saving when the contract requires equal observations; cold loading verifies
  it rather than rewriting it. Preserve raw expressions and observed values.
  Evidence: the sole warm/cold difference in the
  ramp trial (`handover/RAMP_FULL_CHAIN_RESULT_20261027.md`), then
  actual warm/cold equality in the
  directory trial (`handover/EXPORT_DIRECTORY_FULL_CHAIN_RESULT_20261027.md`).
- **The composed export is the consumer's input.** A correct adapter node does
  not prove the ROP consumes it. Trace the actual ROP input and inspect the
  emitted USD's product, channels, camera, resolution and relevant metadata.
  The Beauty attribute was absent until export topology used the adapter.
  Evidence: native failure and corrected export in the
  topology report (`handover/EXPORT_TOPOLOGY_FULL_CHAIN_RESULT_20261027.md`).
- **Representation equivalence needs a narrow policy.** H21's exported
  effective upAxis Y could become explicitly authored while preserving its
  effective value. That case allowed only the recorded fallback-Y export
  transition, retaining raw facts and rejecting other differences. Never
  generalize it into ignoring all authored flags or all USD differences.
  Evidence: topology report above and the subsequent native axis trial.

## Keep observation, execution and delivery separate

- **Cheap queries need their own evidence contract.** Repeated `node.children`
  queries captured full scene parameters before and after each request, adding
  substantial work outside the timed mutation interval. A scoped query can
  preserve ownership, host/lease identities and result hashes while explicitly
  declaring that full-scene identity was not verified. It cannot stand in for
  a save or mutation receipt. Lease owner identity and graph-worker producer
  identity may legitimately differ; bind each to its actual role.
  Evidence: native timing and query rejection, plus scoped software correction
  in query progress (`handover/PRODUCER_QUERY_PROGRESS_20261027.md`).
  That report alone does not prove the whole graph subsequently completed.
- **A complete EXR can have a narrower acceptance basis than an internal
  writer trace.** The `controlled_output_v1` case separately verified the
  stopped writer, frozen configuration, complete EXR, matching native alpha
  calibration, registration and Nuke consumption. Internal processor/LUT,
  writer/filter and flush/close facts remained `NOT_OBSERVED`. Preserve that
  provenance and the human color choice; do not upgrade it to strict internal
  writer observation or visual approval.
  Evidence: `engineering-chain-20261026-authorized-28/29` final driver stage,
  `AWAITING_HUMAN_REVIEW` with native technical completion.
- **Reserve time for observing and stopping.** A per-operation deadline may
  include completion-record and shutdown headroom, so a stop before the outer
  limit is not automatically a timer bug. Attribute latency to measured phases;
  a gap between receipt timestamps is not proof of a particular function's
  cost. Reuse completed stages and diagnose the next failing consumer.
  Evidence: native menu trial (`handover/NATIVE_MENU_FULL_CHAIN_RESULT_20261027.md`)
  and `engineering-chain-20261026-authorized-12` budget rejection.

## State what diagnostics and packaging establish

- **A non-reproduced timeout remains unresolved.** Successful process samples
  and normal-call stacks can describe those calls, not the earlier timeout's
  cause. Keep host startup, process-image acquisition, worker entry and HIP
  business separate; a diagnostic exit 0 does not complete the scene task.
  Evidence: late-window native diagnostic (`handover/VMMAP_LATE_WINDOW_RESULT_20261027.md`).
- **Use the contract's digest object.** A signed envelope file hash is not the
  canonical payload hash stored by its ledger. Check the defined object with
  the verifier; a verifier's wrong comparison does not justify rewriting old
  receipts. Evidence: sample-header audit (`handover/SAMPLE_HEADER_FULL_CHAIN_RESULT_20261027.md`).
- **Clean software installation is a software result.** Verify wheels and skill
  payloads with development paths cleared and imports rooted in the isolated
  install. Keep release bytes, result summaries and necessary reproduction
  metadata; disposable build/install environments are not knowledge. Successful
  installation, rollback and archive validation do not establish native-host,
  model or visual acceptance. Evidence: `current-source-release-20261016-s78f3h42`
  and `process-identity-release-20261016-796h9zrr` software result files.

Prepared candidate directories with zero tickets contribute no additional
native success claim. Duplicate runtime copies can be retired only after
current dependencies and the small retained evidence set are identified;
do not remove a calibration, signature key, accepted artifact or current
runtime merely because its failure or success has been summarized here.
