---
name: nuke-bridge
description: Drive one running Foundry Nuke session through structured local commands. Use for direct editable graph work, render delivery, EXR validation, and single-DCC tasks; route reference-driven cross-Houdini/Nuke reconstruction and causal repair to vfx-visual-twin.
metadata:
  version: "2.0.0-rc.1"
  short-description: "Control Nuke and verify render delivery"
---

# Nuke Bridge

Install only from an extracted release ZIP with `python scripts/install_runtime.py --target <explicit-install-directory> --action install`. Installation is offline and does not change global Python, Houdini, Nuke, or WorkBuddy preferences. The directory contains `houdini-packages` and/or `nuke` registration files and an installed `run_runtime.py` launcher. Use that launcher for the packaged runtime: `python -I <explicit-install-directory>/run_runtime.py <module> <arguments>`. Installing a newer extracted release into the same target switches both runtime and plugin registrations. `--action rollback` restores the previous generation; `--action uninstall` removes owned runtime/registrations while preserving other plugin settings. See [installation lifecycle](references/installation-lifecycle.md).

## Route the request

- For a small graph edit, use structured node tools: `list_nodes`, `get_node`, `create_node`, `connect_nodes`, `set_knob`, and `batch_set_knobs`.
- For reference matching, causal repair, or a Houdini-to-Nuke component graph, use the sibling `vfx-visual-twin` Skill. Reference inputs remain diagnostic-only and must pass the final Write lineage gate.
- For Karma EXR hand-off and output delivery, run `nuke_bridge task plan --spec <spec.json>` then `nuke_bridge task run --spec <spec.json> --watch` with `nuke.render_delivery`. Add `--json-events` to stream NDJSON records for a UI progress bar; final frames are rendered and counted one at a time, and `Ctrl-C` followed by `task run --resume <task_id> --watch` resumes from the durable checkpoint.
- Use `render_write(background=true)` for long renders; poll `render_status(task_id)` or `task.events`.
- Use `nuke_run` only when structured tools cannot express the operation. It remains subject to the dual AST guard.
- Never expose `nuke_run` to a `visual.reference_rebuild` planner. Visual-twin tasks use only registered structured `agent.comp.*` actions.

## Required behavior

1. Inspect the target Nuke instance, project settings, node names, and output paths before mutating.
2. State the change set and wait for confirmation before delete, overwrite, broad graph cleanup, or final rendering unless an approved task plan covers it.
3. Build three-or-more-node graphs in a single plan with explicit input indices. `Merge2` input 0 is A and input 1 is B.
4. Every final render must call `verify_render` or `render.verify`; a background process finishing is not proof that all frames exist.
5. Keep progress tied to completed frames or known work units. Use indeterminate progress with elapsed time when Nuke cannot report a ratio.
6. Resume interrupted work with `task.resume`; preserve previously verified output frames.
7. Keep weak models on the golden path: plan once, start one registered recipe, then use only status/events/result until a gate fails.

8. Installing the add-on replaces only the marked `nuke-bridge` block in `~/.nuke/init.py` (or `NUKE_USER_DIR`), preserves other plugin lines, and writes a timestamped backup plus SHA-256 manifest. Uninstall removes only that block.

## Main interfaces

- `capabilities.get`, `task.plan`, `task.start`, `task.status`, `task.events`, `task.cancel`, `task.resume`, `task.result`
- `render.start`, `render.status`, `render.cancel`, `render.verify`
- `nuke_ping`, `list_instances`, `list_nodes`, `get_node`, `create_node`, `connect_nodes`, `delete_node`, `set_knob`, `batch_set_knobs`, `render_write`, `render_status`, `verify_render`, `screenshot`, `nuke_run`

Read [runtime contract](references/runtime-contract.md) for task states and [render delivery](references/render-delivery.md) before processing Karma output. Read [failure recovery](references/failure-recovery.md) after a failed gate and [version compatibility](references/version-compatibility.md) before relying on an untested Nuke build.
