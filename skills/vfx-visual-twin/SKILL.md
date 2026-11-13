---
name: vfx-visual-twin
description: Assess and assist tutorial or reference VFX reconstruction with capability-checked Houdini, Karma and Nuke workflows, bounded experiments and visual comparison. Use for tutorial breakdown, image/video matching and cross-stage diagnosis; use individual bridge skills for ordinary one-DCC edits.
metadata:
  version: "2.0.0-rc.1"
  short-description: "Assess, attempt and verify reference VFX"
---

# VFX Visual Twin

Assist reference reconstruction; commit to a bounded method and evidence-based delivery, not guaranteed reproduction of an arbitrary tutorial. A demonstrated modeling or render case establishes that case only. This skill describes how to work; it is not proof of artistic competence, solver convergence or complete-shot support.

Use the bundled `vfx-pipeline` runtime with running Houdini and, when compositing is requested, Nuke. Before execution, check the actual exposed capabilities. A missing check is unverified; a confirmed missing required node, parameter, pass or adapter is unsupported on that route. Distinguish missing assets/configuration from a failed experiment. Documentation examples and tool names below do not establish their availability in the active installation.

## Choose the scope

- **Analysis:** inspect the tutorial, target, dependencies and existing evidence. Do not start a host or change a scene for an analysis-only request.
- **Established workflow:** reuse an authorized route with matching case evidence; verify the requested result instead of inferring it from earlier cases.
- **Experimental reconstruction:** identify the unproven component, propose a discriminating bounded trial and preserve the full requested result. Label partial outputs and remaining gaps explicitly.

For tutorials, use [tutorial reconstruction](references/tutorial-reconstruction.md) to distinguish visible steps from hidden systems and to select a useful first result. Apply [verification](references/verification.md) before making capability or completion claims. Missing capability limits the promised scope; it does not authorize substituting a simpler goal.

Install the bundled runtime offline with `python scripts/install_runtime.py --target <explicit-install-directory> --action install`. Use `--action rollback` or `--action uninstall` for targeted lifecycle actions. See [installation lifecycle](references/installation-lifecycle.md).

## Route the request

- For a reference image, sequence, or video, read [workflow](references/workflow.md) and [model routing](references/model-routing.md).
- For feedback such as “烟太糊”, “火苗太钝”, “浪太平”, “粒子太均匀”, “群集太机械”, “布料太硬”, or “材质像塑料”, read [causal diagnosis](references/causal-diagnosis.md).
- Before simulation caching or reusable learning, read [approvals and experience](references/approvals-and-experience.md).
- Before declaring a result or domain supported, read [verification](references/verification.md).
- Before using official docs, notes, or HIP-derived knowledge, read [knowledge](references/knowledge.md).
- For geometry goals, incremental feedback, receipt recovery or display derivatives, consult [production and feedback lessons](references/production-feedback-lessons.md). For packaging, controller recovery or cross-stage artifact handoff failures, consult [engineering lessons](references/engineering-lessons.md). These historical case observations supplement current evidence; they do not expand support claims.
- When selecting the Houdini/Nuke transport or future SideFX MCP, read [backend routing](references/backend-routing.md).
- Read [the domain index](references/domains/INDEX.md), then only the files for components selected in the current component graph.
- For a tutorial-based reconstruction or an inherited failed scene, read [tutorial reconstruction](references/tutorial-reconstruction.md) before defining milestones or modifying the scene.

## Required behavior

1. Freeze source/reference hashes, scene, camera, seed, frame range, color assumptions, selected pack versions, and protected attributes.
2. Keep vision and planning separable. Give image bytes only to a capability-probed vision gateway; give the planner the persisted structured analysis.
3. Convert feedback into perceptual issues before proposing parameters. Text creates hypotheses, never proof of a cause.
4. Collect evidence across the selected stage graph and use the cheapest discriminating probe first. If causes remain indistinguishable, record `DIAGNOSIS_INCONCLUSIVE`. Obtain the next decisive evidence yourself when available within scope; ask only for information or authorization that requires the user.
5. Test one cause family at a time with a fixed seed and camera. Return at most three candidates and at most five public semantic controls per candidate.
6. Build candidates in reversible preview variants. Do not use `code.exec_python` or `nuke_run` anywhere in a visual-twin task.
7. A human cache grant may authorize only the exact current Houdini simulation subject. A separate human grant is required after final verification before promoting an experience.
8. Reference inputs may feed diagnostic nodes only. They must never be upstream of the final Nuke Write.
9. Preserve editable Houdini and Nuke graphs plus artifact lineage. A render, button press, model response, or metric alone is not final acceptance.

The runtime is the source of truth for concrete node types, parameter aliases, cache writers, approval hashes, and domain maturity. Skill references describe decision rules and evidence boundaries; do not substitute their examples for a runtime capability probe.
