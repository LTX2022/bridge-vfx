# Production and feedback case lessons

Use these case observations when the current problem matches their conditions.
They are guidance distilled from recorded runs, not a claim that every route,
model or effect is supported. The source names below identify retained project
records under `outputs/`; their historical default versions are not current
configuration. Consult the active catalog and [verification](verification.md).

## Geometry semantics and feedback

- Measure the requested geometric quantity, not just the edited parameter.
  Net opening depends on both column positions and thickness. The
  `Bridge-Luna-production-20261106/README.md` case technically completed both
  versions but measured 0.80→0.92 m, only 15% rather than the requested 20%.
  Native cold geometry, goal evaluation and visual acceptance remain separate.
- Bind relative feedback to its named baseline. The verified supplemental
  revision in `Bridge-extra-feedback-20261107/README.md` continued from the
  latest HIP while evaluating 20% against the original 0.80 m baseline.
  Public revision number and a new local artifact-ledger version are different
  identities. Do not compound the percentage simply because another revision
  has been accepted.
- A new goal string does not change a task template's inputs or evaluator.
  `Bridge-autonomous-takeover-20261107/README.md` confirmed read-only discovery
  of PASS/FAIL/PASS for three versions, not new creative production. A new
  object needs an applicable template and evaluation contract; inheriting an
  old accepted geometry source does not supply them.

## Recovery without inventing success

- Recover a lost creation response using the exact original request fields.
  `Bridge-receipt-recovery-20261106/result.json` records a test-injected lost
  receipt followed by retrieval of the same task and a valid proposal. This
  proves that bounded response-recovery case, not a real DCC outage or complete
  film. The earlier `Bridge-creation-status-20261106/result.json` verified the
  read-only status API separately from model behavior.
- A usable independent repair must retain its own provenance.
  `Bridge-net-width-correction-20261106-03/README.md` delivered the corrected
  0.96 m opening through an operator route without changing the original
  failed V2 or claiming autonomous-model success. The later normal supplemental
  revision is a separate case, not a retrospective rewrite of that repair.
- Reuse a saved valid graph when repairing a downstream step.
  `Bridge-savedgraph-downstream-20261105/README.md` records actual HIP cold
  opening and independent Nuke consumption without repeating graph creation,
  reference rendering or alpha calibration. Its original failed operation was
  left failed; a separate registered-delivery route accepted the files.
- A warm saved edit is a graph checkpoint, not a finished revision or verified
  resumable simulation state.
  `Bridge-official-table-20261107/README.md` distinguishes its initial accepted
  table from an edited HIP whose cold-open stage failed. The successful
  `Bridge-official-table-cold-recovery-20261107/replacement/verification.json`
  is the later evidence for that second version's cold geometry and output.

## What a preview and a tool result establish

- Fix observation problems at the correct layer. The viewing derivatives in
  `Bridge-visual-delivery-20261104/view-manifest.json` and
  `Bridge-preview-goal-status-20261106/README.md` preserve linear EXR and scene
  lighting while applying a recorded display transform, exposure and scanline
  orientation. A bright PNG does not prove relighting, denoising or a changed
  model. An unregistered viewing file is not automatically available through
  the model's media catalog.
- Describe Nuke creation and verification accurately. A controller-frozen
  Read→Write template that was independently cold-opened and rendered is not
  the same fact as a new GUI Save operation. The saved-graph case above and
  `Bridge-learning-20261028/README.md` record those distinctions. Reference and
  difference branches serve inspection; the final Write consumes the actual
  effect render, with its color metadata preserved.
- Installing a candidate, executing a task-specific entry and enabling the
  default plugin are distinct. `Bridge-health-diagnostic-20261105/README.md`
  records an isolated health fix while the default stayed unchanged;
  `Bridge-regular-plugin-20261104/README.md` separately records fresh-consumer
  loading and existing-result retrieval. Already-loaded conversations do not
  prove the new default. Querying accepted work does not require a new DCC.

## Soft-body evidence already consolidated

Use Houdini's specialist-simulation reference for the diagnostic procedure.
The following case boundaries prevent incompatible evidence from being merged:

| Case records | Reusable observation and limit |
|---|---|
| `Bridge-softbody-stitch-f47-20261107`, `core-f60`, `core-pin`, `core-material` | Native port output and the active selection parameter determine actual constraints, pins and material. Later signed-volume analysis corrected an earlier absolute-volume inference; retain the correction, not the superseded claim. |
| `Bridge-softbody-production-supplement-20261107`, `production-resume` | Whole-frame input repair and observed stitch opening can pass while solved geometry still inverts. The old F60 opening result was not complete core acceptance. |
| `Bridge-softbody-core-quality-20261109`, `dynamic`, `substeps`, `integration`, `ramp`, `ramp-frontload`, `velocity-limit`, `repeat-shape` | Parameter and local-shape trials changed failure timing or distribution but did not establish a general cure. Use matching input/host evidence; do not infer causality from a changed count alone. |
| `Bridge-softbody-retet-gui-auto-20261110`, `retet-gui-contact`, `retet-gui-self`, `retet-gui-post4`, `waist-cavity`, `upstream-native`, `neighbor` | A local topology or shape improvement can transfer risk to untouched cells. Integer-frame positivity can hide negative intermediate position buffers. Neither buffer differences nor collision attributes identify a particular internal correction without direct evidence. |
| `Bridge-softbody-goal-20261112/结果与差距.md`, `final-surface-audit.json` | The narrower waist test reached F59 without inverted tetrahedra but had surface crossings from F52 and insufficient opening. It did not reproduce the multi-part reference or pass F60. Saving a `.sim` did not verify cold continuation. |
| `Bridge-softbody-capture-20261112`, `checkpoint` | An incorrect baseline assumption and raw `hou.Ramp` JSON serialization caused preparation failures. These consume real starts but are not experiments proving a solver technique ineffective. |

These source cases establish why the diagnostic gates exist. Preserve the
full requested character, frame range and downstream effects when staging
tests. Learning from a stopped trial is not completion of the creative goal.
