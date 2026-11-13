# Bridge Skills 2.0 architecture

## Trust and execution boundaries

Bridge Skills 2.0 separates media perception, planning, deterministic evidence, DCC execution, and human authority.

```text
reference media -> VisionGateway -> ReferenceAnalysis
                                      |
scene/capability probes --------------+-> PromptCard -> SkillIR -> one ID-only action
                                      |
                                      v
ComponentGraph -> versioned domain packs -> stage DAG -> Houdini/Karma/Nuke
                                      |
                                      v
                            MetricEngine + artist review

trusted human control plane -> cache grant / experience grant
```

The planner never receives an approval-signing capability. A model request may create an approval request, but only a trusted-human service can issue a grant. The runtime checks a grant before dispatch and the DCC cache action checks its assertion again.

`SkillCompiler` exposes at most four state-valid action IDs. `SkillExecutionVM`
resolves those IDs through trusted domain data, owns idempotency and recovery,
and rejects model-supplied paths, scripts, raw parameter names and numeric
arguments. API-native function calls and desktop-mediated strict JSON are
different capability modes and are never reported as equivalent.

`DccBackend` separates domain/causal logic from transport. The current Houdini
HTTP and Nuke Bridge adapters provide backend identities; a future SideFX MCP
adapter remains `UNSUPPORTED` until it proves its protocol, provider identity,
session and required capabilities. The user-reported SideFX roadmap informs
this boundary but is not current live evidence.

The knowledge plane stores cited `ClaimCandidate` records separately from
`RepairExperience`. Official documents and authorized notes/HIP files carry
source hashes and version scopes. Promotion to `KnowledgeCard` requires
deterministic verification, DCC verification when applicable, and an explicit
human promotion record. HIP ingestion defaults to metadata-only; an isolated
runtime is disposable and still cannot authorize arbitrary code.

## Core contracts

`TaskSpec` and the v1 `TaskEngine` remain available for existing recipes. `TaskSpecV2` and the pipeline service own reference rebuild and causal repair. V2 persists normalized references, components, stages, issues, evidence, candidates, approvals, artifacts, verification, and experience independently of DCC process memory.

An `EffectDomainPack` contains domain-specific semantics without changing the causal engine: component kinds, stage graph, perceptual issue vocabulary, diagnostic probes, public controls, DCC parameter adapters, cache declarations, metrics, compatibility, and maturity. Composite packs connect existing components; `explosion_composite_v1` does not duplicate Pyro, particles, RBD, lighting, or comp solvers.

The standard stage order is `source/layout/control -> generation/simulation -> shaping/meshing -> material -> lighting/camera -> render -> composite -> delivery`. Packs may omit stages or add parallel component branches. Cache invalidation follows downstream dependency edges from the changed component/stage.

## Causal loop

Feedback is normalized into perceptual issues before any parameter suggestion. The engine collects comparable stage evidence, constructs falsifiable cause hypotheses, chooses the cheapest discriminating probe, and creates at most three fixed-seed preview candidates with no more than five semantic controls each. A cause becomes verified only after its predicted evidence changes, protected dimensions remain valid, technical gates pass, and the artist accepts the result.

Still references constrain appearance only. Motion and dynamics require a sequence/video or the default 48-frame diagnostic clip. Missing decisive evidence produces `DIAGNOSIS_INCONCLUSIVE`.

## DCC graph invariants

Houdini work remains editable and uses structured high-level actions. A domain pack must resolve required node types and parameter aliases on the live DCC build; missing requirements are unsupported. Simulation cache artifacts require an exact cache grant. Static procedural, lookdev, lighting, render, and Nuke-only work never use that grant.

Nuke assigns every input an explicit role. Effect, plate, and AOV branches may feed final output. Reference branches are diagnostic-only. Graph build, patch, render, and delivery each audit the final Write's recursive upstream lineage and fail if a reference role or reference source path appears.
