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

## Before a solver or cache run

- **Check the worker environment.** Compare the actual launch environment with the dependencies of the planned node types. A definition on disk can be excluded from an isolated worker. When package scanning is disabled, check that approved vendor dependencies such as KineFX are on the effective Houdini path. Keep package isolation and verify the exact required type in the authorized worker, for example `kinefx::jointdeform`.
- **Measure the geometry at its producer.** Cook the smallest relevant upstream section in the authorized scope. Record the actual primitive counts by type, the accepted range, and cook warnings before applying the gate. For tetrahedral soft bodies, keep the animated/render mesh as the source of motion and use a separately sized solve proxy. Measure the tetrahedra again after cutting and verify the required piece and point IDs survived. Treat missing, empty and out-of-budget outputs as distinct findings.
- **Locate tetrahedral inversion before changing solver settings.** At the same frame, compare ordered tetrahedra at rest, after cutting, and after deformation. Match by stable source point IDs and retain the piece identity. For Houdini's tetrahedron order, compute `-dot(P1-P0, cross(P2-P0, P3-P0))/6` using double precision. Count inverted, degenerate and nonfinite elements separately; absolute volume hides inversions that can yield negative varying mass. Fix the first failing stage, then check every frame consumed by the solver. Four representative poses can pass while a turning pose between them still folds. Rebuild only caches whose dependencies changed, and check seam alignment and motion against the original driver. FEM Deform can be a candidate for volume-aware deformation; its output needs the same checks. [Tetrahedron orientation](https://www.sidefx.com/docs/houdini/model/primitive_spaces.html#tetrahedra) · [FEM Deform](https://www.sidefx.com/docs/houdini/nodes/sop/femdeform.html)

Preview variants may cook without a production cache. The structured cache
action must reject a request unless a trusted approval assertion binds the exact
scene/input/reference hashes, pack version, component, selected patch, resolved
parameters, seed, frames, DCC version, dependencies, and output path. Lookdev,
lighting, render, procedural geometry, and Nuke-only work never use a Houdini
simulation-cache grant.

For a bounded native trial, log the start and elapsed time of scene load,
cached-input checks, topology cook, constraint rebuild, and the first solver
advance. Write the phase marker before each potentially blocking cook so
a supervisor stop still leaves diagnostic stage evidence. A phase marker is
not a resumable simulation checkpoint. Compare the time available to
solve after initialization with a measured baseline. If the run expires before
the rebuilt input is read back, record the last observed phase and leave
solver acceptance pending.

If Hython never reaches the first line of the worker, verify the exact
host executable and framework against vendor provenance first. Match the
version, architecture, file digest, and macOS signature. Confirm sandbox
verification errors under normal host permissions with a signed system
control. Check the executable and framework resource seal separately.
A digest from a prior successful run identifies the same local bytes.
An integrity failure confirmed on the host requires verified vendor
media before another native run.

Hython initializes Houdini and imports `hou` during startup. An absent
script marker leaves that whole interval open, including library loading
and license checkout. Use a short startup-only probe with an immediate
script marker. If needed, sample its verified child PID and collect
loader diagnostics within the same budget. Record acquisition failures
separately. A running license service shows availability of that process.
Successful checkout requires separate evidence.
[SideFX command-line scripting](https://www.sidefx.com/docs/houdini/hom/commandline)
· [Apple process sampling](https://support.apple.com/guide/activity-monitor/run-system-diagnostics-actmntr2225/mac)
· [Apple code signing verification](https://developer.apple.com/library/archive/technotes/tn2206/)

In a GUI worker, read back the update mode, frame, node cook count and
primitive counts before accepting an input. An empty geometry handle can
precede the actual cook in Manual mode. Try Auto Update with a disk-only
display branch, then compare the original input SOP. If necessary, force
one cook of that non-simulation SOP and measure the result. Read the
solver outputs at the same frame and advance stateful frames in order.
Treat exported geometry and a resumable solver checkpoint as distinct
artifacts.
[SideFX Cooking](https://www.sidefx.com/docs/houdini/basics/cooking.html)
· [SideFX OpNode](https://www.sidefx.com/docs/houdini/hom/hou/OpNode.html#cookCount)
· [SideFX Vellum I/O](https://www.sidefx.com/docs/houdini/nodes/sop/vellumio.html)
· [SideFX simulation checkpoints](https://www.sidefx.com/docs/houdini/dyno/cache)

## Repair animated tetrahedra

When the rest and cut meshes are valid and the animated proxy develops
inversions, repair the deformation upstream of velocity, material and
constraint generation. Keep the ordered topology and piece IDs. If two seam
points share a rest origin and are intended to coincide before release,
correct their position together and copy it back to both point IDs.

Before tuning a tear simulation, view the selected region on the complete
character in rest and animated poses from more than one angle. Spatial bounds
can include a nearby limb as well as the intended torso region. Match the
selection to the current stage's anatomical intent and the reference shot.
A stable local cut is a diagnostic milestone, not acceptance of a reference
that requires several body parts to separate.

Positive signed tetrahedral volumes do not prove that the embedded surface
is free of self-intersections. Check nonadjacent exterior triangles at rest,
after deformation and after conditioning, both within a piece and between
pieces. Distinguish strict crossings from shared vertices, tangencies and
the intentionally coincident faces of an unopened seam. Preserve the actual
triangle IDs and crossing geometry. If the input boundary already crosses
itself, repair the deformation or the incorrectly selected region before
interpreting solver parameter experiments as a complete fix. A volume-floor
projection can remove local inversions while leaving surface crossings.

For sparse inversions, try local signed-volume projection. Set a positive
floor based on each rest volume and a numerical tolerance appropriate to the
scene scale. Group constraints so tetrahedra within a group share no movable
point. Apply those groups in a deterministic sequence, using the updated
positions for each group. Average simultaneous corrections only if the
result converges on the full frame range. Include every tetrahedron incident
on a movable point in the check. Re-read the stored positions in their actual
precision and check signed volumes across the whole mesh. Compare the minimum
volume relative to rest, maximum position correction and frame-to-frame
change in correction. Verify seam alignment, and recheck derived velocities,
mass, thickness and Stitch identities at the trigger.
[Constraint partitioning](https://diglib.eg.org/items/b0331fca-e9fb-40a9-9981-7c00da6c0605)

Read the actual parameter names and current values before preparing a
capture experiment. A proposed maximum point count is not an increase unless
it exceeds the installed node's current value. Keep parameter-discovery
failures separate from completed geometric experiments. Record only the
parameters needed for that experiment. HOM values such as `hou.Ramp` are not
plain JSON values; encode their keys, values and basis deliberately when they
are needed, instead of dumping every parameter's raw `eval()` result.
[Point Deform capture](https://www.sidefx.com/docs/houdini/nodes/sop/pointdeform.html)

If the input is positive and the first advancing frame inverts, join the
rest, initialization and first advanced frames by ordered point IDs and
piece. Compare signed volume, volume relative to rest and shape quality
(for example, normalized mean ratio or minimum altitude). Count recurrent
failures across controlled runs. Set separate limits for shape and relative
volume from the shot's scale and baseline. A FEM Validate shape threshold
uses a different metric from a volume fraction.
[FEM Validate](https://www.sidefx.com/docs/houdini/nodes/sop/femvalidate.html)
· [Near-flat and inverted tetrahedra](https://www.sidefx.com/docs/houdini/nodes/sop/tissuesolidify.html#visualization-guides)

When conditioning a recurrent cluster, join the baseline and candidate by
stable cell ID after rounding to cache precision. Include every tetrahedron
incident to a point whose position or recomputed velocity changed. For each
cell, compare signed volume and signed minimum altitude (six times signed
volume divided by the largest face cross-product magnitude). Record the
worst cells and their IDs. Protect thin neighbors with a declared per-cell
floor so a gain on the target or an unchanged global minimum cannot hide a
local loss. Apply this check again after combining multiple pose corrections.
Continuous free motion and frozen displacement replays are input screens.
Use the same native host, topology and solver settings for a causal A/B, and
check for new failures beyond the target list. If fixing the boundary leaves
too few movable points, screen local connectivity swaps.
For each cavity, require the same oriented interface triangles and total
signed volume. Check the replacement in rest and every reused animated pose,
then recheck the combined swaps for duplicate cells, connectivity and seam
identity. Keep source and revised tetrahedral caches in distinct namespaces.
Rebuild affected mass and constraints. Preserve the consumer's surface point
and face order by writing solved positions by stable ID into the accepted
surface layout. Verify the rebuilt input before advancing the native solver.
After a connectivity change, compare failed cells by their stable point ID
sets and keep vertex order for the signed volume calculation. Count
failures in retained and replacement cells separately. Check whether newly
failed retained cells share points with the changed cavities.
[Simulation mesh quality](https://www.sidefx.com/docs/houdini/finiteelements/geometry.html)
· [SideFX Tet Conform](https://www.sidefx.com/docs/houdini/nodes/sop/tetconform.html)
· [Freitag and Ollivier-Gooch on tetrahedral swapping and smoothing](https://onlinelibrary.wiley.com/doi/10.1002/%28SICI%291097-0207%2819971115%2940%3A21%3C3979%3A%3AAID-NME251%3E3.0.CO%3B2-9)
· [Local worst-element optimization study](https://digital.library.unt.edu/ark%3A/67531/metadc682377/m2/1/high_res_d/414383.pdf)

For a local initialization correction, freeze pin and seam endpoints and
cap displacement relative to the shot scale. Check incident tetrahedra and
the full mesh at cache precision. Recompute the finite-difference velocity
from the corrected pose and its actual predecessor, preserving the authored
impulse. If the correction is for initialization only, place it on that
input and check the next frame's animated target and velocity. A shared
previous-pose TimeShift can otherwise carry the edit into that frame.
Rebuild any material values and rest constraints that depend on the pose.
Verify the pin membership, seam pairs and upstream frame reuse. A
half-step or full-step free-motion check can catch velocity regressions
before a native solve. Solver advancement still requires its own readback.

Profile constraint grouping separately from projection. A single first-fit scan
with a mask of used colors per point can replace repeated scans of the
remaining constraints. Preserve the group and update order, and compare
stored positions frame by frame before adopting the optimization. Report
kernel time separately from end-to-end Houdini cook and cache time.

If corrections spread widely or many cells remain near the floor, inspect
rest mesh quality and how the surface driver captures the volume. In Point
Deform, the minimum and maximum capture counts can introduce discontinuities.
Test a revised driver or a volume-aware deformation against the same poses
and displacement limits. For difficult untangling, an optimizer with a
Jacobian barrier can be evaluated against the same motion and volume criteria.
[Point Deform capture](https://www.sidefx.com/docs/houdini/nodes/sop/pointdeform.html#parameters)
· [Simulation mesh quality](https://www.sidefx.com/docs/houdini/finiteelements/geometry.html)
· [Locally Injective Mappings](https://users.cs.utah.edu/~ladislav/schuller13local/schuller13local.html)

## Vellum material, pins and tearing

Check all affected inputs on one reference pose before caching a sequence.
At the trigger, read the material output, pin output and solver inputs using the
same point and piece identities. Save both the geometry and constraint streams
when a check fails so the first faulty stage is identifiable.

1. **Set the material on the solve proxy.** Record the scene units, density
   source and thickness method. The H21.0.631 **Vellum Configure Tetrahedral
   Softbody** preset in `$HH/toolbar/ExtraTools.shelf` uses
   `domass=calcvarying`, `dothickness=calcuniform` and a density of
   `100 * hou.scaleFromMKS("kg1m-3")`. The generic node's `0.1` is a cloth
   default. Use the tet preset as a reference and validate the choice on the
   shot's scale. `Mass: Unchanged` preserves upstream values. For varying
   tet mass with no additional scaling, each point receives density times one
   quarter of each incident tet's signed volume. Compare the per-piece mass
   sum with density times signed volume before pinning. When the geometry
   accounts for negative mass, repair it before tuning density.
   [SideFX material tutorial](https://www.sidefx.com/docs/houdini/vellum/mass_thickness.html)
   · [Mass modes](https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraints.html#geometry)
   · [Unit conversion](https://www.sidefx.com/docs/houdini/hom/hou/scaleFromMKS.html)
2. **Read the collision radius on the actual mesh.** Inspect `pscale` and its
   range relative to nearby edges, especially at coincident seam points. Use
   **Visualize Thickness** to spot overlap or uneven coverage on the reference
   pose. The solver's Default Thickness fills a missing attribute. A present
   zero value can bypass that default. Report missing, zero, negative and
   nonfinite material values distinctly before changing solver settings.
   Around flattened cells, compare the radius with local altitude as well as
   edge length. Record the provenance of `overlap_self` and
   `overlap_external` when rebuilding the start pose. Treat overlap values
   and `disableself` flags as solver state. `hitnum` alone cannot establish
   which interactions affected an interior tetrahedron.
   [Visualize thickness](https://www.sidefx.com/docs/houdini/vellum/mass_thickness.html)
   · [Collision attributes](https://www.sidefx.com/docs/houdini/vellum/vellumattributes.html#collision)
   · [Solver defaults](https://www.sidefx.com/docs/houdini/nodes/dop/vellumsolver.html#advanced)
3. **Prove the pin membership.** For H21.0.631 `Pin to Target`, set the
   geometry `group` and `grouptype` explicitly. This mode hides `pingroup`.
   Compare before and after by point ID. Permanent pins set `mass=0`, so
   confirm the intended anchors are the points that lost their mass. Free
   points should keep positive finite mass and their intended `pscale`,
   without a position lock or an animation binding. Read those flags
   separately from mass. `stopped & 1` locks position and `stopped & 2`
   locks orientation. Verify that the anchors follow the target during the solve.
   [SideFX soft body exercise](https://www.sidefx.com/tutorials/an-introduction-to-vellum-soft-bodies/)
   · [Point attributes](https://www.sidefx.com/docs/houdini/vellum/vellumattributes.html)
   · [Paul Esteves node lessons](https://www.paulesteves.com/tutorials/vellum-nodes)
4. **Identify the stitches on the constraint output.** Check source and target
   group classes, search mode and distance limit. For closest-point Stitch
   between tet seam groups, use point groups and `useclosestpt=1`,
   `useclosestprim=0` on H21.0.631. The primitive-location mode supports
   polylines, triangles and quads as targets. Enable a dedicated Stretch
   Output Group (`dostretchgrp=1`, `stretchgrp`) and read its primitive
   `type` and endpoints. A point-to-point `stitch` acts as a distance
   constraint. A `ptprim` references a primitive location. Verify that the
   streams share the same IDs. If the constraint stream drops `id`, prove
   correspondence with topology and unique positions within each piece.
   Equal point counts and coincident positions across the cut leave identity
   unresolved. Save raw endpoints and the resolved pair set.
   [Stitch parameters](https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraints.html#closest-point)
   · [Matt Estela's constraint stream example](https://tokeru.com/cgwiki/HoudiniVellum.html#stitch-constraint)
5. **Separate initialization from advancement.** Use Full mode for animated
   pins and breaking. At the solver start frame record the mass, pin state,
   initial `v` and expected pair set on the actual inputs. When using a saved
   input baseline, compare the rebuilt geometry and constraint streams by ID
   and ordered topology. Save the raw geometry and constraint outputs from
   initialization and the first advancing frame before applying readback
   gates. Measure the moving piece's displacement and the anchors' response.
   For a later event in an active simulation, read back the force or property
   change inside the solve at that frame.
   [Vellum Solver SOP](https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html)
   · [Matt Estela's initial velocity example](https://tokeru.com/cgwiki/HoudiniVellum.html#spinning-rigid-shapes)
6. **Prove the break on the original pairs.** Confirm that the solver tests
   for breaking. Read the actual break type, threshold and rest length on
   the intended constraints. A stretch ratio depends on the rest length.
   For coincident seam points, use a distance threshold if the intended
   event is an absolute separation. Track which original pairs disappear
   on the solver's constraint output, measure the resulting gap and verify
   the anchored body stays stable. `stitch` is a native alias for `distance`.
   Identify the original pairs by their constraint role and verified
   endpoint IDs. Record the first output sample that loses a pair and save
   the raw streams on both sides of that sample. Report substep timing only
   if the solve recorded it. A lost tag or endpoint mapping leaves the
   readback unresolved.
   [Vellum attributes](https://www.sidefx.com/docs/houdini/vellum/vellumattributes.html)
   · [Breaking frequency](https://www.sidefx.com/docs/houdini/nodes/dop/vellumsolver.html)
   · [Break settings](https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraints.html#breaking)
   · [Stitch lesson](https://www.sidefx.com/tutorials/vellum-constraints-masterclass/)
7. **Check the solved volume.** Read back signed volumes after initialization
   and advancement, with the same ordered topology and piece identities.
   Record the first failing frame and piece, the minimum signed volume and
   inversion count. Keep these results separate from the authored target
   quality, stitch break and gap measurements. Resolve inversions in the solved
   volume before extending a production cache that depends on it.

Change one family per solve when isolating first-frame inversions. When
testing Preserve Volume, confirm the realized ARAP constraint on the native
output and check the advanced geometry. When evidence points to a thin input,
qualify the local shape repair before changing collision settings or
substeps. For a self-collision toggle, compare the identities and signed
volumes of failing cells as well as the total. A different set of failures
can persist after the toggle. Read back the collision settings and relevant
state attributes, and use the production collision settings for the next
time-step test.

**Vellum Substeps** divides the advance into shorter solves. **Constraint
Iterations** applies within each of those steps. Holding iterations fixed
while increasing substeps also raises the number of constraint passes per
frame. Describe the result as sensitivity to the substep setting. To study
constraint convergence separately, hold substeps fixed and compare a change
to iterations. Read back **Breaking Frequency**, since **Per Substep**
changes the number of tests per frame as substeps change. Record surviving
pairs, gap and frame cost. Stress normalization and absolute distance
thresholds use different break measures.

**Global Substeps** changes simulation-level sampling and can retain
intermediate global states. Treat any change to it as a separate experiment.
A fractional playback sample can be interpolated and provides no evidence
of the original Vellum internal substeps. If you add a substep recorder,
check that integer-frame positions, velocities and constraint identities
still match the uninstrumented solve before attributing a failure to an
internal step.

For a contact sensitivity test, distinguish interleaved Collision Passes
from Post Collision Passes after constraint enforcement. Change one pass
count and read it back on the SOP and active DOP. Compare the same stable
cells at the last passing frame and first failing frame. A changed
trajectory identifies sensitivity to that setting. Attributing an
inversion to an individual correction requires separate phase evidence.
If reducing the cleanup count makes the solve fail earlier, restore the
baseline count before isolating another collision control. Preserve the
failed frame's solved geometry and constraints to allow readback of stitch
IDs and collision flags after the signed-volume gate stops the solve.
[Vellum troubleshooting](https://www.sidefx.com/docs/houdini/vellum/vellumtips)
· [Vellum Solver](https://www.sidefx.com/docs/houdini/nodes/dop/vellumsolver.html)

For a frame that recovers by its output sample, check any saved
previous-position buffer using the actual step size and velocity rule on
the same point IDs. Count transient and final inversions separately. One
verified position buffer locates an event relative to that buffer. It gives
no per-constraint or collision impulse history. Compare the original
constraint IDs at adjacent output frames before relating a fold to a break.

Read the effective integration order, acceleration threshold and fallback
on the active DOP solver. A point-level fallback during a second-order solve
and a global first-order solve can have different motion. Compare the same
inputs, solved signed volumes, local relative velocity, stitch survival and
opening when testing the integration order. If a later test spreads an
initial velocity kick over time, measure the actual application interval and
integrate the applied acceleration over the solver steps. With varying mass,
verify the acceleration received by the intended points. Recheck the tear
timing after changing the force profile.

For a direct velocity schedule in Vellum Full, verify the installed build's
editable force path and its execution frequency. Use the DOP simulation
clock and time increment to identify the application steps. Read back the
starting animation velocity, exact affected point IDs, per-step velocity
differences and cumulative increment. Compare schedule delivery separately
from solve quality. When comparing weights with the same total increment,
record both the weights and their application times. The time distribution
can change the path and tear even when the cumulative increment matches.

Treat the velocity-update acceleration limit and the collision displacement
limit as separate controls. Read back the active threshold and time step on
the installed solver. A saved previous velocity can precede the actual
update input, so its difference from the output is only a screening signal
for the cap. When velocity is capped, verify which velocity is stored before
using a position-difference identity. Compare per-frame volume, seam IDs,
gap and surface penetration with the same uncapped inputs.
[ARAP](https://www.sidefx.com/docs/houdini/vellum/arap.html)
· [Breaking and tearing](https://www.sidefx.com/docs/houdini/vellum/breaking_tearing.html)
· [Vellum Solver SOP](https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html)
· [Solver substeps and breaking](https://www.sidefx.com/docs/houdini/nodes/dop/vellumsolver.html)
· [Vellum integration lesson](https://www.sidefx.com/tutorials/advanced-vellum-workflows-h17-masterclass/)
· [POP Force](https://www.sidefx.com/docs/houdini/nodes/dop/popforce.html)
· [DOP clock bindings in VEX](https://www.sidefx.com/docs/houdini/vex/snippets.html)
· [Vellum acceleration and displacement limits](https://www.sidefx.com/docs/houdini/nodes/dop/vellumsolver.html#motion)

Advance only the smallest approved frame segment that can prove the change.
Reuse pre-trigger caches whose dependencies stayed the same. Report the saved
graph, verified simulation and independently read cache as separate results.

Measure the time for the actual cook, verification and cache write on a short
sample before budgeting the full frame range. Track the cost of branches that
request another time, such as a previous-pose TimeShift for velocity, and reuse
verified pose samples where the graph permits it. Compare velocity by stable
point ID and include the frame rate, trigger impulse, first predecessor and
any subframes requested by the consumer. For a stable tetrahedral boundary,
reuse the ordered exterior faces and update their positions. Key that reuse
on the ordered topology, orientation and piece IDs. Persist a per-frame result
with its required cache files. After a confirmed stop, reuse complete frames
only after checking the frame IDs, unchanged input and graph hashes, topology
and saved positions. Fill the exact missing set and run the remaining gates.
This applies to stateless inputs. To qualify solver continuation, cold-load
a compatible checkpoint and compare an overlapping interval with a continuous
solve. Starting a new solve from geometry requires its own acceptance.
[TimeShift](https://www.sidefx.com/docs/houdini/nodes/sop/timeshift.html)
· [Houdini performance monitoring](https://www.sidefx.com/docs/houdini/hom/hou/perfMon.html)

## Layered soft-body shots

Use tutorials to identify the inputs, frame events and outputs of each layer.
Confirm node types and parameters on the approved Houdini build; the current
online manual may show nodes from a newer release.

- **Character and tear.** Keep the rest skin, animation and render surface distinct from the tetrahedral solve proxy. Point Deform uses `id` for correspondence when present and expects connected rest and deformed lattices to keep their connectivity. Its Piece Attribute must be a matching point attribute on the render mesh and rest lattice. For a pre-cut proxy, split the render surface along the intended seam as well, or use a separate transfer per piece. On a diagnostic capture, check for uncaptured seam vertices and cross-piece weights. Inspect the deformed seam before and after separation for faces bridging the opening. [Soft bodies](https://www.sidefx.com/docs/houdini/vellum/softbody) · [Point Deform](https://www.sidefx.com/docs/houdini/nodes/sop/pointdeform.html)
- **Strands and fur.** Record the owning piece and surface anchor for each
  strand endpoint. Track the same strand's length before the event, while
  stretched and at break. For a deforming surface with stable face topology,
  capture roots on the split rest surface with a piece, persistent primitive
  identity and parametric UVW. If primitive numbers change, resolve each
  identity to its current number before Attribute Interpolate. Verify that the
  face's vertex order still gives the same UVW mapping. Check unresolved roots
  and distance to the owning piece after the split. For H21, probe the
  object-level Guide Deform route or an equivalent piece-aware capture. The
  Guide Deform SOP in the current manual was introduced in H22.
  [Attribute Interpolate](https://www.sidefx.com/docs/houdini/nodes/sop/attribinterpolate.html)
  · [Guide Deform object](https://www.sidefx.com/docs/houdini/nodes/obj/guidedeform.html)
  · [Guide Deform SOP](https://www.sidefx.com/docs/houdini/nodes/sop/guidedeform.html)
- **Fluid.** Derive the emitter from the verified opening and use one emission path per source. Record the actual Activation and Emission Type. Each Frame emits on active frames, while Each Substep can emit more than once per frame. Check no births before the opening, then read back the first births and their positions and velocities relative to the moving source. For substep comparisons, measure births per simulation second and account for the resulting particle load. Keep fur and fluid as separately verifiable branches; the documented Vellum setup does not support hair–fluid interaction. A cached collision surface can drive the fluid but cannot receive fluid feedback. Check the particle cache and the surfaced result separately. [Vellum Source](https://www.sidefx.com/docs/houdini/nodes/dop/vellumsource.html) · [Fluid setups](https://www.sidefx.com/docs/houdini/vellum/fluidsetups.html) · [Surfacing](https://www.sidefx.com/docs/houdini/vellum/fluidsurfacing.html)
- **Cache and resume.** Record the input versions, expected frames, fps, cache
  files and attributes each consumer needs. Read back the cache from a fresh
  session without recooking it. To resume the same solve in another session,
  configure the DOP checkpoint interval and retention before running and
  confirm a state file exists at the intended handoff. Include any existing
  checkpoint files in the disk budget. Vellum's trail setting prunes files
  created by the current session. Bind the handoff to the solver build, graph,
  inputs and simulation time. After a cold load, compare the state frame and
  the next advancing samples against a continuous solve, including positions,
  velocities, active constraints and the next event. Playback mode and
  geometry-only Vellum I/O cannot establish this. If the solve stopped without
  a compatible checkpoint, recompute from its start and compare the earlier
  accepted samples before extending it.
  [Vellum I/O](https://www.sidefx.com/docs/houdini/nodes/sop/vellumio.html)
  · [Solver checkpoints](https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html#checkpoints)
  · [DOP Network](https://www.sidefx.com/docs/houdini/nodes/obj/dopnet.html)
- **USD and render.** Validate the exported USD across the frame range, including relative dependencies, time samples, camera and render settings. Check visibility immediately before and after each layer transition. In SOP Import, author animated topology for layers whose connectivity or element counts change, such as a remeshed fluid surface, and verify the topology samples on the saved stage. Keep export separate from the supervised renderer; check the explicit frame range and per-frame output token. Verify the image sequence and encoded clip, including the frame count and timing, before calling the shot complete. [SOP Import](https://www.sidefx.com/docs/houdini/nodes/lop/sopimport.html) · [USD export](https://www.sidefx.com/docs/houdini/nodes/out/usd.html) · [husk](https://www.sidefx.com/docs/houdini/ref/utils/husk.html)
