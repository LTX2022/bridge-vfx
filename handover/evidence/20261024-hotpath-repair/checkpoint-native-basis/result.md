# Fresh source checkpoint defaults: H21 native interface facts

Scope: the current registered source build's FX_SOLVER only. No Sphere role, other domain, native process, cook, simulation or cache execution. No repository changes.

Actual explicit software build: FakeSourceHost.build() returns a node at FX_GEOMETRY_NETWORK/FX_SOLVER whose full type is Sop/pyrosolver, version 21.0.631. The probe then attempted rawValue(), which this fake Parm does not implement, so it stopped; it supplies type evidence only, not a new successful raw/default readback. The prior manifest-save-diff.json probe uses unexpandedString and already records both actual fake raw strings and before/after evaluation changes. These are software facts, not a new native run.

Independent installed source confirmation: directly read the installed OPlibSop.hda INDX and nested Sop/pyrosolver/DialogScript without executing HOM. Current library SHA256 is 5018624a3f850b498df5696e7294dae8d442a847b6c61b9717025495d76bf5e2, matching the original metadata supplement. DialogScript member SHA256 c01a9fb6e18a72863555dd6e0b03754acdc696f3196c5c077e1140d8f05ae755.

| Field | Installed DialogScript | Native semantics |
|---|---|---|
| checkpoint_basedir | lines 4527-4532; type directory; default `$HIP/geo` | Base Folder: checkpoint directory location. May be frozen to the fresh owned project directory's geo subdirectory, without creating it or executing caching. |
| checkpoint_basename | lines 4511-4515; type string; default `$HIPNAME.$OS` | Base Name: checkpoint file name/base stem, not an absolute directory or full path. Preserve the fresh scene/network naming identity; do not pass through Path.resolve or prepend an absolute root. |
| savecheckpoints | lines 4503-4506; type toggle; default off | Native default only. Do not infer actual state from this, and do not enable it as part of preparation. |

Both fields have disablewhen `{ savecheckpoints == 0 }`. This is native parameter UI metadata, not by itself proof that no existing cache is consumed or that a particular instance is inactive. The initial hda-interface-capture.json lost the basedir default (empty tokens); the complete metadata supplement and current direct DialogScript extraction both establish `$HIP/geo`, so do not use the incomplete first capture for that fact.

Official help chain: H21 nodes.zip sop/pyrosolver.txt:1206-1210 includes the checkpoint descriptions from sop/mpmsolver. mpmsolver.txt:300-310 describes Save Checkpoints as saving DOP checkpoints to resume a crashed simulation or ensure shot continuity, Base Name as name of the checkpoint file on disk, and Base Folder as location of its directory. These parameters can affect restart input/output continuity once checkpoints exist; they are not generic harmless metadata.

Recommendation to the implementation owner: for a fresh registered source instance only, bind exactly Sop/pyrosolver plus these exact fields/defaults and verify actual raw/channel/default and checkpoint state at preparation time. Stabilize the directory and basename according to their distinct native types before any save/capture context change; retain full readback and ownership evidence. Do not change savecheckpoints, version controls or future explicit cache policy; do not auto-migrate, reuse or rewrite existing checkpoint data. Custom values, drivers, existing checkpoint intent/data, wrong type or missing fresh-default proof must remain blocked. No arbitrary fields/other solver types are authorized by this evidence.

All file/member hashes and exact excerpts are under this directory. No claim is made about native runtime caching or inactive state from the static default alone.
