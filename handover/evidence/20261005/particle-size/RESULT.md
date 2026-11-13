# P02 bounded module delivery

Completed only the two assigned new root files; paths were absent before writing.
Shared domain/add-on sources, producer states and operation receipts were not
modified. Current missing-facts route still refuses with
`PARTICLE_SIZE_RANDOM_RANGE_AND_BASE_SIZE_CONTRACT_REQUIRED` (audit.log).

`native_particle_size_program.py` returns a frozen typed `ParticleSizePlan` with
existing native write dictionaries and exact guards. It derives size/a and
size*(a-1/a), uses the captured const/rand/uniform/minplusrange/custom-id fields and
P02-specific integer sub-seed, verifies current task/build/node/basis/source IDs,
and refuses unknown/duplicate IDs, driven/unavailable fields, changed topology,
menu representations or plan execution markers. Source geometry/basis stay
frozen through parameter mutation. Zero restores actual constant size.

Actual parameter readback uses freshly collected facts, derives percentage from
the observed range, and returns `ParticleSizeParameterReadback` with
`evidence_scope='parameters_only'` and explicit missing evidence. Native random
samples are not predicted or supplied. Complete P02 remains BLOCKED pending
actual ID-to-pscale, copy consumption and cross-frame/reopen evidence.

Final validation: **8 tests, 1.153s, exit 0**, in unit-02.log. Coverage includes both
captured H21/H22 interfaces, numeric endpoints, actual bottom set/eval readback,
zero restoration, ID reorder/sub-seed binding, missing/invalid basis/IDs,
driver/gate/type/token/representation rejection, identity/topology/source drift,
wrong readback and rehashed plan/guard/dispatch-marker tampering. The test boundary
is explicit bottom parameter/node/geometry API only; no facade success, supervisor,
native random geometry or formal process is substituted. No full/managed/DCC run.

Main integration contract is in interface.md. Reuse the existing host fenced
transaction and rollback; invoke P02 validation before writes and after fresh
collection. Do not relabel the shared blocked control or combine its old
constant-only size write without adding the authenticated basis/ID collection.

Artifacts: commands.json contains actual argv/exit and source/log SHA;
modified-files.sha256 lists exactly the two product additions; delta.patch has
only those additions and passed `git apply --reverse --check` (exit 0).
The two no-index whitespace checks returned 1 for new-file differences, with no
diagnostics. Initial unit-01 log is retained as superseded audit evidence.

Delivered; release the two-file implementation write grant. No further product
modification is planned.
