# Specialist simulations

The standard `houdini.model_to_karma` recipe deliberately covers editable
procedural/static assets and simple animation only. Visual-twin work routes
through a versioned runtime domain pack. Pyro, FLIP, particles, Ocean, RBD,
Vellum, Crowd, swarm, hair/fur, and composite simulations require pack-level
capability evidence and multi-frame verification.

Before using a specialist pack, probe its exact node types and parameter aliases,
plug-ins, cache writer, diagnostic passes, frame set, and available memory. If
the required adapter is unavailable, return `AWAITING_INPUT` or
`UNSUPPORTED_NODE`; do not substitute a generic SOP network and claim the
simulation completed.

Preview variants may cook without a production cache. The structured cache
action must reject a request unless a trusted approval assertion binds the exact
scene/input/reference hashes, pack version, component, selected patch, resolved
parameters, seed, frames, DCC version, dependencies, and output path. Lookdev,
lighting, render, procedural geometry, and Nuke-only work never use a Houdini
simulation-cache grant.
