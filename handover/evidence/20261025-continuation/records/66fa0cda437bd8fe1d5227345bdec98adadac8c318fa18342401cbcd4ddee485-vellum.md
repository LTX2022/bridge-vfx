You are setting up a Vellum simulation in Houdini (cloth, softbody, grains, hair).

Goal: the user-requested Vellum effect.

For tutorial reconstruction or inherited failed scenes, read the sibling
`vfx-visual-twin/references/tutorial-reconstruction.md` and preserve the full
tutorial target. Commands below are workflow vocabulary: use them only when
advertised by the live runtime. Do not fabricate missing tools or bypass the
structured execution boundary.

`vellum/vellumtips` is SideFX's own tips and troubleshooting page and most of
what follows is from it. `vellum/mass_thickness`, `vellum/paneling_draping`,
`vellum/collisions` and `vellum/lowreshighres` cover the rest. Read the relevant
page with get_help_page, and use setup_vellum_sim to build the network.

## Check the input before blaming the solver

Vellum uses continuous collision detection, which is what stops fast geometry
teleporting through cloth. It is **useless if point numbering changes every
frame**, and a surprising amount of "the solver is broken" is really that.

Test the input rather than assuming: drop a timeshift at `$F+1`, wire it and the
original into a sequence blend, and see whether it blends. If it does not, look
at point `id` attributes, which override point numbers and often fix matching, or
use matchtopology to make numbering consistent frame to frame.

The trap on top of that trap: **a good source can still break after a
subdivide.** Vellum only cares about the previous frame's points, so randomised
primitive numbers are harmless, but subdivide derives new point numbers from
primitive numbers, and `id` attributes that matched before a subdivide usually do
not after it.

## pscale is not a detail

The default is small, and **any `pscale` on the input overrides it**, so an
incoming sequence may already carry a surprising value.

- Too small gives hard collisions. Vellum wants enough thickness to float the cloth on the collider.
- Larger than your edge length invites self intersections.
- Too large rarely explodes anything, but collision tests run at that size and the cloth **crawls to a stop**. A mysteriously slow sim is often pscale, not resolution.
- Sanity check it: the vellumsolver's Visualize tab draws a sphere per point. At defaults it may be too small to see, which is itself the answer.

## The four speed-versus-quality levers, and how they trade

1. **Substeps** break the frame down and are essential for fast cloth. Smaller substeps give tighter collision bounds, so the cost is often lower than expected.
2. **Constraint Iterations** are what make stretch and bend constraints actually hold. Stiff, non-stretching cloth needs large numbers, and they are usually cheaper than people assume. A rough minimum is the "diameter" of the cloth: the longest shortest path in edges between its two farthest points, or in practice how many edges tall the piece is. Raising substeps lowers effective forces, so iterations can come down.
3. **Collision Passes** handle external and self collisions, interleaved between constraint iterations. With 50 iterations and 5 collision passes you get 10 iterations between each. The exchange rate matters: 2 substeps with 10 collision passes costs about the same as 1 substep with 20, and the first is better.
4. **Post Collision Passes** run after all iterations and do not interact with constraints, so they push cloth out in the shape of the collider instead of letting it tent. Last resort only.

## Failure signatures

Treat these as candidate causes, not diagnoses. First verify input identity,
time window, active constraints and live/cache output provenance. Use a small
discriminating probe before changing solver controls.

- **Cloth stretches.** XPBD failing to converge. Raise constraint iterations first, they are cheaper than substeps.
- **Cloth crawls to a stop.** pscale far too large, so every collision test is oversized.
- **Sharp collider pokes through high-resolution cloth.** Collision resolution is entirely local: only colliding points move, the rest stays put. Resolution and collider shape are the fix, not more passes.
- **Geometry teleports through cloth.** Continuous collision detection defeated by inconsistent point numbering. Test the sequence as above.
- **Protrusions shaped like the collider.** Post collision passes doing the work that constraints should.

## Order of work

1. Validate the input sequence, before building anything.
2. Use drape/pre-roll only when the target requires a settled initial state and the selected domain supports it. Do not insert cloth draping into every softbody or grains task; preserve the intended animated/rest state and event start.
3. setup_vellum_sim, then sanity check pscale visually.
4. Use the advertised bounded sequential preview operation over the recorded short range, watching per-frame cook time and output validity. Keep playable temporal evidence as well as diagnostic screenshots. Investigate stretch/penetration before choosing iteration or substep changes; query the same operation after timeout, never submit another cook blindly.
5. Before any cache write, obtain the required subject-specific approval. Use the registered writer and verify the required geometry/constraint streams, exact frames, dependencies and output freshness. Explicitly inspect whether the displayed node reads live simulation or disk; a changed parameter does not invalidate a disk reader by itself. A surface-only export may be a deliverable, but must not be represented as a complete resumable Vellum cache.

## Vellum node vocabulary

<!-- BEGIN GENERATED: vellum nodes -->
Generated by `tools/gen_prompt_vocab.py` from tools/prompt_vocab.json.
Do not hand-edit: edit that file and regenerate.

A name with a version range exists only in those versions of the
20.5-22.0 range this server supports. Unannotated names exist
throughout. Check `get_scene_info` before relying on an annotated name.

| Stage | Types |
|---|---|
| Constraints and setup | vellumconstraints, vellumdrape, vellumrestblend |
| Solve | vellumsolver |
| Pack and unpack | vellumpack, vellumunpack |
| Cache | vellumio |
| Post | vellumpostprocess |
| Fixing bad input | matchtopology, timeshift |
<!-- END GENERATED: vellum nodes -->

## Network housekeeping

Use UI helpers only when the current runtime advertises them. Keep the user
informed through normal progress messages when status-bar helpers are absent.
If available, select the task-owned network and lay out newly created nodes
without disturbing another task's scene. Missing log_status,
set_current_network or layout_children is not a reason to invent a call,
bypass structured execution or abort an otherwise supported operation.
