---
name: bridge-houdini
description: Inspect and execute scoped Houdini edits and bounded trials through the actual Bridge graph MCP catalog. Distinguish available controls, native results and visual acceptance; applies to Bridge workflows, not unrelated Houdini scripting.
---

This skill provides execution and inspection guidance. Confirm each required operation in the current catalog; generic Houdini support or an earlier modeling success does not establish tutorial or complex simulation capability. For a tutorial's full effect and acceptance criteria, use the Bridge VFX route. An analysis-only request does not start hosts. Direct operator diagnostics and model-facing execution need separate evidence.

For parameter observation, cold output or writer failures, consult [native execution lessons](references/native-execution-lessons.md) and retain each case's evidence limits.

For a new specialist simulation or a repair involving Vellum or KineFX, read [specialist simulations](references/specialist-simulations.md) before spending a native attempt. Use a bounded upstream cook to prove the required operator, geometry and constraint outputs before a solver or cache run.

For a new task using the default installed entry, call `bridge_health`, then `bridge_connect` with one stable `request_id`. The agent supplies this ID; the user does not supply paths, ports, tokens or setup scripts. This starts at most one independent background Houdini 21.0.631 and Nuke 17.0v1 for that request, using the installed runtime and private host configuration. Use `bridge_connection_status` with the returned `connection_id`; report connected only when the overall state is `CONNECTED` after both real host health checks succeed. `bridge_health` returning `READY` means `entry_ready:true` and `dcc_connected:not_checked`; it neither launches nor probes DCCs.

The background connection has a fixed 120-second maximum lifetime, ending at the earlier signed host start time plus 120 seconds. Repeating the same request, checking status or reconnecting the MCP transport never renews it or restarts a host. An expired or failed connection is never restarted automatically; a new connection needs an explicit `bridge_connect` with a new request ID within the authorized task. Call `bridge_disconnect` when finished; it stops only this connection's owned background hosts. Closing MCP leaves the hosts to their existing lease. Connecting does not open an old project, recover failed work or authorize rendering.

For existing registered projects, call `bridge_projects`, explicitly select a project with `bridge_select_project`, then use `bridge_tasks` and `bridge_continue_task` with its project and original operation IDs. Reconnection requires an explicit selection again. Completed tasks return original verified files; running tasks are observed; failed or unknown work stays blocked without a new dispatch. The directly configured GraphMCP connection below remains available for graph editing.

Read `health` and `graph_catalog` from the configured Bridge MCP connection before choosing registered nodes or domain packs. Follow the actual returned tool schemas and existing controller approvals; plugin installation does not authorize DCC execution.

Use [runtime-contract](references/runtime-contract.md) for host boundaries and [failure-recovery](references/failure-recovery.md) for uncertain execution or recovery. Preserve stable request IDs when retrying identical content. Report missing scene configuration, unavailable controls and unverified native facts explicitly.

The default background connection is prepared by the agent through the tools above; see [plugin setup](../../docs/agent-plugin.md) for the separate prepared-controller route. Diagnostic mode permits inspection without a real DCC. Do not infer real Houdini or visual success from a catalog or software fixture.
