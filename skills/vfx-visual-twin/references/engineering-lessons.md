# Engineering lessons from retained execution evidence

Use these lessons when diagnosing packaging, controller boundaries or artifact
handoff. They are scoped observations, not a declaration that all Bridge
domains, tutorials, platforms or releases are supported. Source identifiers
below are repository-relative historical cases; current execution still needs
the active route's capability and authorization checks.

## Keep evidence levels attached to the result

- A software profile can exercise the real controller, supervisor, Python
  worker, persistence and artifact flow while substituting the DCC API.
  Preserve `evidence_source=software_test` and `native_execution_status=NOT_RUN`
  even when that flow technically completes. Do not infer a real render from
  EXR-shaped fixture bytes or a successful saved-scene receipt. **Software
  evidence:** `outputs/software-engineering-full-chain-20261020-12/activated/software-full-chain-result.json`.
- Separate successful graph creation, save, cold reopen, render, alpha and
  visual comparison. The HIP-only case reached save/reopen with 23 verified
  nodes while render, alpha and Nuke remained unrun; failed readback attempts
  also retained their terminal accounting errors. **Native stage evidence:**
  `outputs/hip-chain-20261025-authorized-21/result.json` and
  `outputs/render-readback-20261026-authorized-2/stages.json`.
- A successful process probe on an ordinary Python target does not establish
  Houdini image identity or explain its startup stall. Record the target and
  measurement route; invalid stack identity stays failed even when the sample
  command exits zero. **Ordinary-process diagnostics:**
  `outputs/sample-native-repair-20261023-05/result.json` and
  `outputs/stack-capture-qualification-20261027-02/result.json`.

## Preserve the current graph through recovery and feedback

- Before changing recovery logic, inspect whether the existing-graph branch
  validates and restores the current graph or reapplies initial controls.
  Rebuilding unnecessarily can erase feedback. An operation's owner and host
  generation belong to its identity; an operation ID alone is insufficient
  across tasks or restarts. **Code review and software evidence:**
  `outputs/review-20261015/FACTS.md`, `outputs/m1-next-20261015/RESULT.md`.
- After all color writes, perform the final lineage/topology/input audit and
  reread the complete Read/Write and premultiplication state before dispatch.
  A later setter can alter a value already checked. Roll back failed setting
  transactions without replaying prior feedback; an unknown dispatched render
  is not permission to roll back or submit it again. **Red/green software
  evidence:** `outputs/confirmed-fixes-20261015/color/RESULT.md`.
- A Nuke-only task does not need a Houdini owner, but it still needs a trusted
  input artifact. Resolve query/cancel through the persisted operation owner.
  Copy verified inputs to the worker's private input area and verify the
  current saved NK and consumed bytes before execution and registration.
  **Software/TCP evidence:** `outputs/m1-completion-20261015/nuke/SUMMARY.md`.

## Validate the consumer's actual input contract

- Follow forwarded USD relationships rather than treating an authored target
  as the resolved consumer input. Reject missing observations and over-budget
  AOV traversal instead of turning absent facts into defaults. **Software
  repair evidence:** `outputs/m1-next-20261015/RESULT.md`.
- Bind a media derivative to source asset identity, content and frame set.
  Equal bytes from distinct assets do not make their provenance identical;
  idempotent recovery must preserve a legitimate existing record. **Software
  evidence:** `outputs/m1-next-20261015/media/AUDIT.md` and `RESULT.md`.
- Bound serialized observations both per record and for the complete store.
  A terminal record that fits alone can still overflow the aggregate and
  prevent durable completion or slot release. Reject oversized writes
  atomically while preserving the previous store; do not use an unbounded
  recovery writer to bypass the limit. **Reproduction and software evidence:**
  `outputs/m1-completion-20261015/output-budget/README.md` and
  `outputs/m1-writer-controls-20261015/RESULT.md`.

## Bind the delivered package, not just the working tree

- Derive the expected release file set from its layout, then check missing,
  extra and changed members before installation. A self-consistent manifest
  can describe stale sources. Verify isolated import and install/upgrade/
  rollback/uninstall against actual package bytes, with development
  `PYTHONPATH` removed. These checks do not prove DCC or platform UI loading.
  **Software packaging evidence:** `outputs/m1-next-20261015/release/RESULT.md`.
- Preserve a legitimate empty file during reversible patching; a text patch
  utility may leave or remove an empty endpoint differently across systems.
  Verify both directions against complete file sets and byte hashes.
  **Software repair evidence:** `outputs/m1-next-20261015/RESULT.md`.
- Treat declared text as text and reject invalid encoding. Preserve a unique
  undecodable raw capture as opaque bytes with its encoding limitation and
  digest; do not silently transcode evidence or apply text checks to wheel/
  image binaries. **Archive and software evidence:**
  `outputs/m1-next-20261015/RESULT.md` and `release/RESULT.md`.
- A local FFmpeg executable and dependency inventory do not establish an
  offline package on another machine. Redistribution rights, library/resource
  closure, relocation and clean-target decoding remain separate checks.
  **Static dependency inventory; target decoding unverified:**
  `outputs/m1-next-20261015/release/RESULT.md`.

## Keep knowledge compact and retain the evidence that still matters

Distill the tested condition, observation, correction and compatibility limit;
do not copy complete execution logs, receipts, snapshots or databases into a
skill. A failed or preparation-only case may add a boundary without supplying
a successful recipe. Keep representative red/green results and unique native
artifacts separate from regenerated environments and repeated source copies.

Avoid recursively including old `outputs` in a fresh validation source tree.
Use an explicit source/dependency selection and separately list the minimum
evidence needed by the test. Before retiring a copied validation tree, confirm
that the needed code/evidence is retained in the canonical tree or verified
archive and that no active route depends on its path. Case summaries preserve
lessons; they do not replace a HIP, simulation checkpoint, signed receipt or
source snapshot when exact restoration or verification still requires it.
**Observed storage structure and existing archive selection:**
`outputs/m1-writer-controls-20261015/RESULT.md` and
`outputs/husk-entry-current-release-handoff-20261016/archive_helpers.py`.

Include dynamic task/feedback state, job records, authorities and accepted
results in cleanup dependency discovery; preparation files alone miss paths
that are only loaded when returning an old result. Preserve referenced package
trees even when an identical ZIP exists: signed validation can require their
original paths. Read actual completed results before and after cleanup; a
working project list or task list is insufficient. If a required copy was
retired, restore its exact archived bytes and verify result readback without
replaying production or rewriting receipts. Keep unrelated reader compatibility
errors distinct from missing cleanup dependencies. **Observed cleanup and
readback evidence:** `handover/output-consolidation-20261112/README.md`.
