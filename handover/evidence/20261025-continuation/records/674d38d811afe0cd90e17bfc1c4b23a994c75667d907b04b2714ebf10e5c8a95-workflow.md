# Reference rebuild workflow

## Inputs

Classify every input by role: `reference`, `effect_render`, `plate`, `matte`, `depth`, or `vector`. Record an absolute path, content hash, media kind, frame mapping, declared color space, and the current task's component assignment. If an input role is ambiguous, resolve it before graph construction.

The reference may be a still, sequence, or video. A still can constrain spatial appearance but cannot prove speed, timing, forces, or temporal stability. For motion feedback, use the supplied sequence/video. If motion must be estimated, label it and record a diagnostic frame set and fps appropriate to the task; do not silently replace the source timing with fixed 48-frame/24-fps defaults.

## Build

1. Ask the vision gateway for structured components and perceptual observations.
2. Build a component graph, then resolve one versioned domain pack for each component.
3. Compose the selected packs' stage graphs and dependency edges.
4. Create editable Houdini networks and diagnostic outputs before any production cache.
5. If compositing is required, create Nuke effect, optional plate/AOV, and isolated reference-diagnostic branches.
6. For dynamic effects, provide a bounded sequential temporal preview covering the event and aftermath in the first creative iteration. A hero-frame inspection can diagnose appearance but cannot replace this preview. Record whether it is a viewport or rendered result and preserve the full final target.

Choose an opaque scene render or transparent effect layer from the user's target; absence of a plate alone does not decide this. Untagged display references default to sRGB only as a recorded inference; record and verify the task's working color space rather than silently changing an inherited project's configuration.
