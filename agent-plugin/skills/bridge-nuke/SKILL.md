---
name: bridge-nuke
description: Use the Bridge graph MCP controller for Nuke composition, trusted artifact input and bounded output workflows. Applies to registered Bridge artifacts, not arbitrary media or unrelated Nuke scripting.
---

For a new task using the default installed entry, call `bridge_health`, then `bridge_connect` with one stable `request_id`. The agent supplies this ID; the user does not supply paths, ports, tokens or setup scripts. This starts at most one independent background Houdini 21.0.631 and Nuke 17.0v1 for that request, using the installed runtime and private host configuration. Use `bridge_connection_status` with the returned `connection_id`; report connected only when the overall state is `CONNECTED` after both real host health checks succeed. `bridge_health` returning `READY` means `entry_ready:true` and `dcc_connected:not_checked`; it neither launches nor probes DCCs.

The background connection has a fixed 120-second maximum lifetime, ending at the earlier signed host start time plus 120 seconds. Repeating the same request, checking status or reconnecting the MCP transport never renews it or restarts a host. An expired or failed connection is never restarted automatically; a new connection needs an explicit `bridge_connect` with a new request ID within the authorized task. Call `bridge_disconnect` when finished; it stops only this connection's owned background hosts. Closing MCP leaves the hosts to their existing lease. Connecting does not open an old project, recover failed work or authorize rendering.

For existing registered projects, call `bridge_projects`, explicitly select a project with `bridge_select_project`, then use `bridge_tasks` and `bridge_continue_task` with its project and original operation IDs. Reconnection requires an explicit selection again. Completed tasks return original verified files; running tasks are observed; failed or unknown work stays blocked without a new dispatch. The directly configured GraphMCP connection below remains available for graph editing.

Start with `health` and the actual MCP tool list. Use the existing artifact registry and Nuke tools; consume only registered, current upstream artifacts. Preserve scene, operation, frame, color and content bindings and controller authorization.

Read [render-delivery](references/render-delivery.md) for output handling and [failure-recovery](references/failure-recovery.md) before retrying uncertain operations. Same request ID requires identical input; successful registration retry must not repeat rendering.

See [plugin setup](../../docs/agent-plugin.md) for the separate prepared-controller route; default background connection uses the tools above. Report host and visual acceptance separately from software diagnostics; plugin installation does not authorize rendering.
