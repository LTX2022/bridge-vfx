"""The only source of truth for publicly documented Houdini commands."""

from __future__ import annotations


COMMANDS = {
    "ping",
    "scene.info",
    "scene.open_hip",
    "scene.save_hip",
    "scene.reopen_task_hip",    "node.children",
    "node.info",
    "node.parms",
    "node.subtree",
    "node.find",
    "node.create",
    "node.create_batch",
    "node.connect",
    "node.set_parm",
    "node.set_parms",
    "node.cook",
    "node.press_button",
    "node.delete",
    "node.bypass",
    "node.unlock_contents",
    "node.layout",
    "viewport.screenshot",
    "help.query",
    "help.list",
    "help.search",
    "help.stats",
    "code.exec_python",
    "debug.list",
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
    "agent.model.probe",
    "agent.model.build",
    "agent.model.validate_geometry",
    "agent.model.lookdev",
    "agent.model.solaris",
    "agent.model.render_preview",
    "agent.model.verify_preview",
    "agent.model.render_final",
    "agent.model.verify_final",
    "agent.model.deliver",
    "agent.fx.probe",
    "agent.fx.bind_graph_trial",
    "agent.fx.build_preview",
    "agent.fx.collect_evidence",
    "agent.fx.inspect_controls",
    "agent.fx.operation_receipt",
    "agent.fx.apply_candidate",
    "agent.fx.verify",
    "agent.fx.cache",
    "agent.fx.cache_status",
    "agent.fx.deliver",
    "operation.cancel",
    "operation.status",
    "agent.fx.simulate_segment",
    "bridge.s06.inspect_scene",
    "bridge.s06.short_segment",
}

LEGACY_ALIASES = {
    "scene_info": "scene.info",
    "node_create": "node.create",
    "node_create_batch": "node.create_batch",
    "node_press_button": "node.press_button",
    "viewport_screenshot": "viewport.screenshot",
    "exec_python": "code.exec_python",
    "health": "ping",
}


def canonical_command(command: str) -> str:
    value = LEGACY_ALIASES.get(command, command)
    if value not in COMMANDS:
        raise ValueError(f"unsupported Houdini command: {command}")
    return value
