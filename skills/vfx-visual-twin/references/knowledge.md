# Knowledge and source promotion

Operational guidance is distilled from a tested condition, observation and
compatibility limit, not from the volume of saved logs. Use
[engineering lessons](engineering-lessons.md) or
[production and feedback lessons](production-feedback-lessons.md) when the
current problem matches. They are case-scoped instructions, not promoted
runtime KnowledgeCards or RepairExperiences. A preparation-only case and a
failed test may establish a boundary without establishing a successful method.

When the user requests consolidation and cleanup, retain the source-to-lesson
mapping and minimal supporting results. Retire only inactive execution copies
whose dependency and retention checks permit it. Keep the actual project,
required media, calibration, credentials and runtime dependencies separate
from the distilled text; a skill cannot replace those files. Mark historical
replay paths that have been retired instead of presenting them as runnable.

Official documentation, authorized notes and HIP files begin as immutable
sources with a URI, version, SHA-256 and concrete citations. A weak model may
extract a `ClaimCandidate`; it may not mark that claim true or reusable.

Promote a candidate to `KnowledgeCard` only when the candidate/source/domain
hashes still match, deterministic verification passed, required DCC evidence
passed, and a human promotion record exists. Keep KnowledgeCard storage
separate from RepairExperience.

HIP defaults to `metadata_only`. Use `isolated_runtime` only in a disposable
Houdini process with no arbitrary-code authority. `trusted_live` is an explicit
operator choice and still does not give a model script or approval capability.
