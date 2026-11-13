# Model routing

`VisionGateway` may receive source media only after it proves the required single-image, multi-image, sequence, or video capability. Persist its output as a structured `ReferenceAnalysis` with uncertainty and evidence locations.

In ordinary mode, `PlannerGateway` receives the analysis, scene summary, current state, one compact PromptCard, and an ID-only response schema. The card exposes at most four state-valid actions. `SkillExecutionVM` resolves action, control and candidate IDs.

In explicitly enabled graph-extension mode, the model may propose registered nodes, typed connections and catalog-bounded numeric parameters. A server-side compiler checks types, units, ranges, context, version and ownership before execution. This does not authorize arbitrary paths, scripts, unregistered parameters or approvals. If the installed backend lacks the required extension capability, report the concrete missing binding; a prompt cannot add it.

Use the model route selected for the current task and record its app, session, visible model choice, media transport and tool evidence. For this project's current acceptance route, that is WorkBuddy desktop with HY3 selected; legacy Doubao or direct HY3 API results do not transfer pass status. Keep visible route selection separate from provider-verified identity. Manual response handoff records human assistance and cannot establish automatic route execution or unlock DCC acceptance. A Codex-assisted tutorial trial is its own route, not a WorkBuddy/HY3 or GLM acceptance result.

User-selected WorkBuddy Full Access is the operating condition, not proof of filesystem isolation. Do not change the user's permission settings or claim the Bridge tool allowlist constrains other tools. Preserve the task's material-sharing permissions across attachments, screenshots, logs and tool results.

The planner may inspect, plan, diagnose, propose a preview, or request approval. It cannot grant approval, execute arbitrary DCC code, write a production cache without a valid assertion, or promote experience.

On malformed structured output, perform a bounded schema-repair attempt without changing the task. On repeated failure, return a stable model error and preserve the latest valid state.
