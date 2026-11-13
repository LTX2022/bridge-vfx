---
name: bridge-houdini-softbody
description: Diagnose Houdini Vellum tetrahedral soft-body and tearing failures from input and native-output evidence, and run authorized bounded repair trials. Use for inversion, surface penetration, deformation, seams and solver continuity; this is not a complete tutorial-reproduction or finished-shot service.
---

# Soft-body diagnosis and bounded repair

Identify the first failing stage and test a plausible repair without losing the
user's full visual target. This skill supports investigation and case-specific
experiments. It does not establish that arbitrary tutorials, coupled effects
or complete shots can be reproduced autonomously.

For tetrahedral inspection and native trials, read
[specialist simulations](../houdini-bridge/references/specialist-simulations.md).
Follow the active project's execution entrypoint and limits. Do not treat
generic Houdini APIs or this reference's examples as capabilities exposed by
the current Bridge route.

For host-entry, parameter-serialization or cold-output failures, consult
[native execution lessons](../houdini-bridge/references/native-execution-lessons.md).
Use the tested case's conditions; these observations do not prove solver
convergence or full tutorial reproduction.

## Select the work

- For diagnosis or capability review, inspect available geometry, frames,
  logs and receipts without starting hosts or changing the scene.
- For an authorized repair, recover the baseline, unresolved operations and
  remaining budget. Reuse valid inputs and fix the earliest failing producer.
- For full tutorial reconstruction, retain the complete target and identify
  the relevant reference-planning route. A local test may establish one
  component only; absent a broader route, report the missing capability.

## Make the trial informative

1. Inspect the selected region on the whole character and compare rest,
   deformed input and solved geometry at matching times. Track ordered stable
   point IDs and piece identity. Check shape, signed volumes, surface contact
   and intended motion separately before changing solver settings.
2. State the suspected cause, one main change, baseline and acceptance
   observation. Read actual parameters and check worker-side data handling
   before a costly launch. Follow the existing task budget, not a new allowance
   per script, request or handoff.
3. For topology changes, verify the interface, seam identities and affected
   neighbors, then rebuild dependent mass and constraints. For stateful work,
   distinguish geometry playback from validated checkpoint continuation.
4. Compare the measured output and playable motion with the baseline. Record
   improvement, regressions and what remains unknown. Repeated non-improvement
   without new evidence requires a different diagnosis, not more of the same
   parameter adjustment. Keep preparation errors separate from solver failures.

## State the boundary of the result

Report offline screening, native simulation, visual comparison and delivery
reopening separately. No inverted tetrahedra does not imply no surface
penetration, sufficient opening or resemblance to the tutorial. A smaller
stable cut is not completion of a multi-part tear. Preserve the first failure
and name every required untested downstream effect.

Stop new experiments at the task's limit or an unresolved-stop condition;
retain usable partial artifacts and their limitations. Promote only tested,
scoped observations into reusable guidance. A skill update is not a new
capability acceptance result.
