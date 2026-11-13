# Approvals and experience

There are two independent trusted-human approvals.

## Simulation cache approval

The first grant authorizes one exact `houdini_simulation_cache` subject. The subject binds the scene and input hashes, reference hashes, pack and adapter versions, component, selected semantic patch and resolved parameters, seed, frame set, DCC version, cache dependencies, and output path. Any change revokes the grant. An identical retry may reuse the grant and existing verified artifact idempotently.

Material, lighting, render, procedural geometry, and Nuke-only changes are not simulation caches and must not request this grant. Ocean foam or another optional dynamic output is cacheable only when its domain pack declares it as a simulation artifact.

## Experience promotion approval

Only after technical verification and explicit artist acceptance may the system request a second grant. Promotion stores the issue, context, verified cause, semantic repair, resolved parameter diff, before/after evidence, and compatibility bounds. The cache grant cannot promote experience, and the experience grant cannot authorize a cache.

Unpromoted task-local repairs are not searchable. A promoted experience is a prior for a new preview, never permission to change a scene or cache. Cross-domain and incompatible-version reuse is rejected.
