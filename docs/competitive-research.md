# Competitive research for Bridge Skills 2.0

Research checked on 2026-08-29. Labels distinguish an official or upstream description from behavior reproduced in this repository.

## Evidence matrix

- DeepSeek's official [Responses API](https://api-docs.deepseek.com/api/create-response/) describes `deepseek-v4-flash`, structured JSON-schema output, function tools, stateless request history, and no image/file input support. **Design adopted:** keep VisionGateway separate, persist structured visual analysis, and send one constrained action surface to the planner. **Repository reproduction:** pending a user-supplied real endpoint/key; fake transports are contract evidence only.
- Foundry's [CopyCat overview](https://learn.foundry.com/nuke/17.0/content/comp_environment/air_tools/cc-intro.html) describes learning a shot-specific transformation from input/ground-truth pairs, while [BigCat](https://learn.foundry.com/nuke/content/comp_environment/air_tools/using-bigcat.html) adds larger-data generalization, augmentation, and validation. **Design adopted:** keep task-local fixes separate from explicitly promoted reusable experience and retain validation evidence. **Not copied:** Bridge Skills does not claim to train a neural image model.
- SideFX's [Houdini 22 Copernicus notes](https://www.sidefx.com/docs/houdini/news/22/copernicus.html) document image-derived depth/masks and image/volume processing, and the [Cache COP](https://www.sidefx.com/docs/houdini/nodes/cop/cache.html) documents change-sensitive caching. **Design adopted:** represent masks/depth as typed reference evidence and bind caches to upstream identity. **Repository reproduction:** domain-specific Copernicus execution is not a first-release requirement unless a pack declares it.
- ComfyUI's [ControlNet documentation](https://docs.comfy.org/tutorials/controlnet/controlnet) demonstrates explicit graph conditioning rather than an opaque prompt-only path. **Design adopted:** retain visible component/stage graphs and typed evidence inputs.
- [fxhoudinimcp](https://github.com/healkeiser/fxhoudinimcp) and [Blender MCP](https://github.com/ahujasid/blender-mcp) are upstream examples of model-to-DCC bridges. **Design adopted:** local scene inspection and high-level actions. **Safety difference:** visual-twin planners receive registered structured actions, not a general code-execution path.

## Product differentiation target

The intended differentiator is not the number of callable nodes. It is the cross-DCC causal loop: stage-localized hypotheses, fixed-context interventions, protected-dimension verification, exact simulation-cache approval, and separately approved experience reuse. This remains a target until live evidence for every declared first-party pack exists; documentation must not call it industry-leading based on architecture alone.
