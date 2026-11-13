"""The only source of truth for publicly documented Nuke commands."""

from __future__ import annotations


COMMANDS = {
    "nuke_ping",
    "list_instances",
    "list_nodes",
    "get_node",
    "create_node",
    "connect_nodes",
    "delete_node",
    "set_knob",
    "batch_set_knobs",
    "open_script",
    "script.info",
    "save_script",
    "get_project_settings",
    "set_project_settings",
    "render_write",
    "render_status",
    "render_cancel",
    "render_fact",
    "verify_render",
    "screenshot",
    "nuke_run",
    "capabilities.get",
    "task.plan",
    "task.start",
    "task.status",
    "task.events",
    "task.cancel",
    "task.resume",
    "task.result",
    "render.start",
    "render.status",
    "render.cancel",
    "render.verify",
    "agent.nuke.probe",
    "agent.nuke.inspect_input",
    "agent.nuke.build_graph",
    "agent.nuke.render_preview",
    "agent.nuke.verify_preview",
    "agent.nuke.render_final",
    "agent.nuke.verify_final",
    "agent.nuke.deliver",
    "agent.nuke.composite.probe",
    "agent.nuke.composite.inspect_inputs",
    "agent.nuke.composite.build_graph",
    "agent.nuke.composite.audit_lineage",
    "agent.nuke.composite.apply_patch",
    "agent.nuke.composite.render_preview",
    "agent.nuke.composite.verify_preview",
    "agent.nuke.composite.render_final",
    "agent.nuke.composite.verify_final",
    "agent.nuke.composite.deliver",
}

LEGACY_ALIASES = {"health": "nuke_ping"}


def canonical_command(command: str) -> str:
    value = LEGACY_ALIASES.get(command, command)
    if value not in COMMANDS:
        raise ValueError(f"unsupported Nuke command: {command}")
    return value
