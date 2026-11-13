# Model to Karma

Use `houdini.model_to_karma` for supported static or procedural assets. The
runtime follows this order:

1. Probe Houdini version, node types, renderer, output permissions, and inputs.
2. Build editable SOP geometry and an `OUT_MODEL` output.
3. Cook and validate geometry before look development.
4. Create MaterialX, camera, and basic lighting.
5. Build a Solaris stage with SOP Import, material binding, camera, lights, and
   Karma settings.
6. Render a 1280x720 preview, verify it, then render each requested final
   frame as its own progress unit (CPU is the acceptance fallback).
7. Deliver through one Undo group or a versioned HIP copy after validation.

The standard recipe does not claim automatic character, grooming, or complex
simulation production. Those use specialist recipes with their own multi-frame
gates.
