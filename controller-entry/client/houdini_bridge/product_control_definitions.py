"""Approved product metadata, separate from native evidence and write plans."""
from __future__ import annotations

import copy

PROPOSAL_SHA256 = "7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e"
DECISION_RECORD = "handover/CONTROL_DECISIONS_20261004.md"
COMMON_RULES = {
    "units": "Lengths use current scene units (SU), velocities SU/s; read actual FPS and time scale. No SI conversion without explicit scale and mass bases.",
    "validation": "Require finite values and each control's zero policy; reject unsigned negatives, missing bases, incompatible combinations and budget excess. No clamping, rounding, implicit conversion or renaming.",
    "randomness": "Use fixed task seed, stable entity IDs and independent control sub-seeds; reopening reproduces samples and changing one control does not resample another. New percentages are bounded amplitudes, not statistical variance.",
    "basis": "Freeze bases, coordinate spaces, distributions, time scales and controlled stages. Missing axes, targets, events, source geometry or stable IDs remain explicit missing inputs; preserve unrelated artist fields.",
    "ranges": "Preserve existing names and validation ranges. Mathematical conditions, version-specific native hard limits, product limits and scene budgets remain distinct; unsupported endpoints stay blocked. Range, alias or endpoint changes require a specific decision.",
    "readback": "Observe actual parameters, attributes, channels, topology or semantic programs and their input SHA, not requested values. Cache/render authorization, 12-frame/120-second limits and total disk budget remain required; product approval does not authorize real jobs.",
    "existing_definitions": "Preserve particle life/velocity variance, Crowd path_variance and Geometry scale_variance; preserve the existing RBD activation_frame constant active step.",
}
COMMON_CAPTURE_REQUIREMENTS = {
    "versions": ["21.0.631", "22.0.429"],
    "interface": "For each version, capture raw definition/help/SDK sources and hashes, exact operators/machine parameters, types/tuples, menu tokens, defaults/expressions, hard/soft ranges, disable/hide state, indexed input/output roles, editable boundaries and downstream consumption.",
    "attributes": "Attribute routes additionally need class/storage/tuple, coordinate space, stable IDs and actual downstream consumption rules; labels, help anchors, sliders and other-version tokens are not machine interface proof.",
    "runtime": "Static evidence bounds pure contracts/native API substitutes. Instance state, geometry/fields, save/reopen and dynamic effects require separately authorized real-host evidence. Recovered JSON excerpts do not replace missing original HDA bytes.",
}
PREPARATION_CAPTURE_REQUIREMENTS = {
    **COMMON_CAPTURE_REQUIREMENTS,
    "versions": ["22.0.459"],
    "status": "PARTIAL_STATIC_BASIS_RUNTIME_FACTS_REQUIRED",
}

_DEFINITIONS = {
    "pyro_fire_v1": {
        "flame_height": {
            "decision_id": "A01", "unit": "SU",
            "definition": "Signed flame-height offset along the trusted emission up axis: envelope upper bound H_base + value, with explicitly frozen positive H_base. Shape the owned flame field; increased allowance does not promise taller flame generation.",
            "zero": "Preserve H_base; if the resulting upper bound is nonpositive, the controlled flame envelope is empty.",
            "negative": "Allowed within the existing signed range; lower the upper bound.",
            "scope": "Owned flame-field height envelope from the source-top projection; preserve density, temperature, vel and fire-light material. Subsequent simulation effects still require verification.",
            "required_basis": ["positive frozen H_base", "trusted emission up axis", "source-top projection", "volume coordinate space"],
            "capture_blockers": ["versioned flame production/consumption boundaries", "editable field-mask operators, parameters and ports", "basis provenance and legal nonpositive-envelope output"],
        },
    },
    "water_flip_v1": {
        "collision_separation": {
            "decision_id": "A02", "unit": "SU",
            "definition": "Collision-field voxel edge length, not collision clearance; positive values specify absolute resolution. Zero follows the actual native default for this version/graph, freezing and reading back the effective edge length.",
            "zero": "Follow the actual native default; keep collisions enabled.",
            "negative": "Reject.",
            "scope": "Owned FLIP collision SDF/velocity fields; preserve particle_separation, surface mesh and collision padding. Record absolute override versus default-following behavior and actual grid budget.",
            "required_basis": ["version/graph default and effective edge length", "field units and grid transform", "SDF/velocity inputs", "actual domain resource budget"],
            "capture_blockers": ["legal editable SOP boundary; internal/DOP fields alone are insufficient", "override/default expression consumption", "zero-to-default restoration mechanism"],
        },
        "collision_passes": {
            "decision_id": "A03", "unit": "dimensionless integer count per FLIP substep",
            "definition": "Number of complete collision-projection loops per FLIP substep; each loop includes SDF sampling and Move-to-Iso position correction. Preserve solver substep count.",
            "zero": "Reject; the existing range starts at one complete loop.",
            "negative": "Reject; do not round floating-point counts.",
            "scope": "Owned FLIP particle collision-iteration branch; independent of solver substeps and particle separation iterations.",
            "required_basis": ["FLIP substep timing", "bound SDF and particle positions", "definition of one complete loop"],
            "capture_blockers": ["versioned Gas Repeat/Move-to-Iso operators, count/stop fields and ports", "legal editable entry and actual per-substep loop consumption"],
        },
    },
    "rbd_destruction_v1": {
        "fracture_scale": {
            "decision_id": "R01", "unit": "SU",
            "definition": "Target fragment characteristic edge length for fracture sampling/cutting; read back closed-piece scale as V^(1/3). This is a creative target, not a guarantee of equal actual pieces or a whole-object scale.",
            "zero": "Reject.", "negative": "Reject.",
            "scope": "Owned fracture generation; preserve input outline and total dimensions. Open surfaces without a volume basis remain missing inputs.",
            "required_basis": ["closed source volume and dimensions", "piece/name identity", "fragment and resource budget", "material, packing and constraint relationships"],
            "capture_blockers": ["versioned general sampling/cutting operators, seeds/density and consuming ports", "actual closed-volume and piece readback; no generic piecesize inferred from HDA labels"],
        },
        "fracture_variance": {
            "decision_id": "R02", "unit": "percent bounded random amplitude",
            "definition": "For each stable sampling cell, target scale L*q with q uniform in [1/(1+p/100), 1+p/100]; p=100 gives [L/2, 2L]. Not actual fragment statistical variance.",
            "zero": "Use the same target L for every cell.", "negative": "Reject; L remains positive.",
            "scope": "R01 target scales/seed generation with fixed seed; preserve constraint-strength variance and glass crack counts.",
            "required_basis": ["positive R01 target L", "stable sampling-cell IDs", "fixed task seed and independent control sub-seed"],
            "capture_blockers": ["versioned variable-scale sampling/cutting graph and actual consumption", "clipped piece volume/topology readback; concrete strength variance is not a substitute"],
        },
        "impact_spread": {
            "decision_id": "R03", "unit": "SU",
            "definition": "Impulse distribution radius r: use actual piece-centroid distance d and weight max(0, 1-d/r) for r>0, multiplying the shared J0 vector. Not glass-specific crack spread.",
            "zero": "Give only the explicitly hit piece weight one and every other piece zero; missing hit ID is rejected, not replaced by a nearest-piece guess.",
            "negative": "Reject.",
            "scope": "One radial impulse event shared with R06; preserve fracture topology, glue strength and Bullet world scale.",
            "required_basis": ["trusted impact center", "explicit hit piece ID and actual centroids", "shared J0 vector and activation time", "stable impact event identity"],
            "capture_blockers": ["versioned editable packed-attribute impulse injection fields/nodes", "event timing and per-piece solver consumption"],
        },
        "piece_scale": {
            "decision_id": "R04", "unit": "dimensionless multiplier",
            "definition": "Uniform geometry multiplier about each actual piece's rest centroid; one preserves geometry. Keep collision shape consistent, preserve density, and update mass/inertia from actual new volume.",
            "zero": "Reject.", "negative": "Reject.",
            "scope": "After fracture and before configure; preserve centroid position, rebuild attached constraint anchors and collision shapes. Not Exploded Scale or World Scale; overlaps/resource excess remain explicit failures.",
            "required_basis": ["actual pieces and rest centroids", "packed pivots/full transforms", "density and actual volume", "attached constraint anchors and collision shapes"],
            "capture_blockers": ["versioned packed geometry/intrinsic editing and collision consumption", "density-to-mass/inertia rules and editable constraint-anchor rebuilding"],
        },
        "velocity_variance": {
            "decision_id": "R05", "unit": "SU/s",
            "definition": "Initial linear-velocity per-axis random amplitude: v=v_base+a*(u_x,u_y,u_z), with independent uniform [-1,1] samples; preserve angular velocity w. Not energy or statistical variance.",
            "zero": "Preserve v_base.", "negative": "Reject.",
            "scope": "Owned pieces once at initial/activation event; fixed piece IDs and seed, no per-frame accumulation. Preserve baseline motion, drag and gravity.",
            "required_basis": ["frozen v_base and coordinate space", "stable piece IDs", "fixed task seed and independent control sub-seed", "initial/activation timing and actual time scale"],
            "capture_blockers": ["versioned rbdconfigure v write path and attribute class/storage/tuple", "Bullet read/overwrite timing and reopening without resampling; POP var is not RBD evidence"],
        },
        "impulse_scale": {
            "decision_id": "R06", "unit": "dimensionless multiplier",
            "definition": "Scale trusted baseline impulse J0: J=value*weight(R03)*J0 per piece. Velocity injection requires actual mass and verified delta_v=J/m; J0 uses actual mass units*SU/s, not force or impact threshold.",
            "zero": "No controlled impulse; preserve baseline velocity and other forces. One reuses J0.",
            "negative": "Reject.",
            "scope": "Shared R03 impact event consumed once at activation; no inferred impact event, J0 or mass.",
            "required_basis": ["trusted J0 vector and mass units", "actual piece masses", "R03 weights", "shared impact event identity, hit piece, center and activation time"],
            "capture_blockers": ["versioned legal instantaneous impulse entry/attributes and units", "mass readback, substep integration, event deduplication and reload consumption"],
        },
    },
    "particles_v1": {
        "emission_variance": {
            "decision_id": "P01", "unit": "percent bounded random amplitude",
            "definition": "Constant birth-rate modulation: rate(t)=birth_rate*(1+p/100*u), u uniform in [-1,1], one fixed-seed sample per scene-second bucket anchored at birth start. Native substeps integrate this rate without resampling.",
            "zero": "Preserve birth_rate; birth_rate=0 always remains zero. At p=100 the rate can approach zero to twice the baseline.",
            "negative": "Reject.",
            "scope": "Existing constant/continuous emission only; preserve lifetime, velocity, area mode, impulse birth and seed.",
            "required_basis": ["actual birth_rate", "birth start, FPS and time scale", "fixed task seed and independent control sub-seed", "native rate hard limits and resource budget"],
            "capture_blockers": ["versioned dynamic rate/expression consumption and emission gates", "subframe sampling/integration and random seed API; multiplied native rate limits"],
        },
        "size_variance": {
            "decision_id": "P02", "unit": "percent bounded random amplitude",
            "definition": "Instance pscale=size*q with q uniform in [1/(1+p/100), 1+p/100]; p=100 gives [size/2, 2*size]. Preserve the independent size basis; do not bind physical collision radius.",
            "zero": "Restore exactly the baseline size.", "negative": "Reject; all legal multipliers stay positive.",
            "scope": "Fixed at birth by stable particle ID; instance size only, no per-frame jitter or collision_radius changes. Preserve Geometry's existing [1,1+value] definition.",
            "required_basis": ["independent baseline size", "stable particle IDs", "fixed task seed and independent control sub-seed", "size/variation composition order"],
            "capture_blockers": ["versioned random-attribute/legal VEX route, ID/seed and pscale class/type", "actual copytopoints consumption and reopen readback"],
        },
        "collision_radius": {
            "decision_id": "P03", "unit": "SU",
            "definition": "Physical particle collision radius in a separate radius carrier, independent of instance pscale; valid only for collision modes that support the convention.",
            "zero": "Point-particle collision with radius zero; collision detection remains enabled. Native representability still needs evidence.",
            "negative": "Reject.",
            "scope": "POP physical collision branch; preserve instance size and baseline velocity. Hair/Vellum radius evidence is not interchangeable.",
            "required_basis": ["supported collision mode and radius convention", "independent physical radius and render pscale carriers", "solver/object gates and SDF inputs"],
            "capture_blockers": ["versioned POP shape/mode and radius/pscale consumption", "radius attribute class/storage, zero endpoint and independent render-size route"],
        },
        "trail_length": {
            "decision_id": "P04", "unit": "scene frames",
            "definition": "Historical time-window length L, including fractions: connect same-ID trajectories in [f-L,f] from integer-frame positions plus linear interpolation at the window start. Not spatial length; never round L.",
            "zero": "Output original particles/instances only, without degenerate curves.", "negative": "Reject.",
            "scope": "Owned trail geometry; preserve simulation v. Use registered/traceable real history only, start at birth when later than the window start, omit dead particles. Missing history/authorization or budget excess is rejected without fabricated samples or silent truncation.",
            "required_basis": ["stable particle IDs and current frame", "registered/traceable historical positions", "birth/death and trajectory continuity", "history authorization and budget"],
            "capture_blockers": ["versioned Trail/history operators, ports and curve output types", "ID association, trajectory gaps, time sampling/interpolation and prehistory registration"],
        },
        "motion_blur_scale": {
            "decision_id": "P05", "unit": "dimensionless multiplier",
            "definition": "Render-only velocity multiplier render_v=value*simulation_v, explicitly bound by the actual renderer; preserve shutter, simulation v and particle positions.",
            "zero": "No contribution from this velocity blur; other deformation/time-sample blur may remain. One preserves render velocity.",
            "negative": "Reject.",
            "scope": "Particle-to-USD/Karma velocity blur; not a pure deformation-blur mode, solver velocity alias or shutter alias.",
            "required_basis": ["actual simulation_v", "FPS and time scale", "supported point/instance representation", "actual renderer velocity-blur binding"],
            "capture_blockers": ["versioned SOP Import velocity attribute to USD velocities mapping", "renderer gates/final bound fields and motion-vector readback"],
        },
    },
    "swarm_flocking_v1": {
        "target_noise": {
            "decision_id": "S01", "unit": "SU",
            "definition": "Target-position perturbation radius a: uniform samples inside a 3D ball centered on actual goal_base, updated each scene second with linear interpolation between samples; one shared moving goal for the whole swarm.",
            "zero": "Exactly goal_base.", "negative": "Reject.",
            "scope": "Seek target position only; preserve particle source, initial v and goal_attraction; add no force. Protect existing drivers.",
            "required_basis": ["actual goal_base and reference space", "fixed seed and independent control sub-seed", "time origin, actual FPS and time scale"],
            "capture_blockers": ["versioned legal goal-animation/noise graph, seed/time and vector types", "goal input/expression consumption, existing-driver protection and reopening"],
        },
        "noise_strength": {
            "decision_id": "S02", "unit": "native POP noise amplitude with Ignore Mass; SI conversion not captured",
            "definition": "Owned POP noise-force native amplitude scalar, using the existing particle force_noise interpretation with Ignore Mass; no claim of SI acceleration. Preserve frequency, seed and roughness, freezing explicit bases when their context is missing.",
            "zero": "This new noise-force contribution is zero.", "negative": "Reject.",
            "scope": "Independent editable swarm noise-force branch; preserve flock, seek and their weights. Existing particle force_noise is a design basis, not proof of a swarm graph.",
            "required_basis": ["explicit frequency, seed and roughness", "actual time-noise context", "Ignore Mass convention"],
            "capture_blockers": ["versioned legal swarm POP Force branch and connections", "amplitude/gates/time-noise context and actual solver external-force consumption"],
        },
    },
    "water_ocean_v1": {
        "directional_spread": {
            "decision_id": "O01", "unit": "degrees",
            "definition": "Full directional support width centered on actual wind_direction, with uniform weights inside the support and normalization preserving total energy of the existing radial spectrum; not half-angle or standard deviation.",
            "zero": "Exact ideal single direction; 360 means uniform all directions. No unapproved epsilon for the zero endpoint.",
            "negative": "Reject.",
            "scope": "Direction distribution only; preserve radial spectrum, wave-height basis, seed and spectrum type. Native dirbias requires a proven exact conversion, otherwise a legal owned directional-spectrum graph.",
            "required_basis": ["actual wind_direction", "existing radial spectrum, type and total energy", "wave-height basis and seed"],
            "capture_blockers": ["versioned spectrum formula, directional weights and exact endpoint representability", "parameter-to-spectrum consumption and editable angular-spectrum ports; no linear bias conversion or silent spectrum switch"],
        },
    },
    "procedural_geometry_v1": {
        "scatter_variance": {
            "decision_id": "G01", "unit": "SU",
            "definition": "Maximum positional perturbation radius of existing scattered points: uniform disk sampling in the local tangent plane, then projection onto the same connected source surface. Edge-projected results are not claimed strictly uniform.",
            "zero": "Preserve original points.", "negative": "Reject.",
            "scope": "Change P only; preserve count/density mode, count, seed and stable point IDs. Not point-count variance, seed or relax iterations; ambiguous same-surface projection is rejected.",
            "required_basis": ["stable point IDs", "source connected surface and normals", "local tangent-plane basis", "fixed seed and independent control sub-seed"],
            "capture_blockers": ["versioned legal projection/nearest-point API and connections", "edge/hole/multiple-surface selection and unique same-surface projection"],
        },
        "rotation_variance": {
            "decision_id": "G02", "unit": "degrees",
            "definition": "Full random angular width about trusted local Z: each instance independently samples delta uniformly in [-value/2,+value/2], added along that local axis after the source instance transform; 360 covers one full circle.",
            "zero": "Preserve baseline orientation.", "negative": "Reject; 360 does not mean plus/minus 360.",
            "scope": "Instance orient perturbation only; preserve existing global X/Y/Z rotation bases, scale and point P, with fixed point IDs and seed.",
            "required_basis": ["trusted local Z axis", "baseline orient and source instance transform", "stable point IDs", "fixed seed and independent control sub-seed"],
            "capture_blockers": ["versioned orient quaternion class/tuple and angle/transform order", "copytopoints consumption and existing orient/transform composition graph"],
        },
        "deformation": {
            "decision_id": "G03", "unit": "SU",
            "definition": "Rest-space instance-source sinusoidal normal displacement amplitude: P'=P+d*sin(2*pi*x/Lx)*N_base; x is relative to frozen source bbox origin, Lx its local X span, phase zero. Deform before existing scale/rotation.",
            "zero": "Restore upstream source geometry.", "negative": "Reject; reject zero Lx or missing N rather than inventing a wavelength.",
            "scope": "Owned instance_source geometry before copy; preserve topology, instance positions, count, seed and pscale. Existing instance scale also scales this local amplitude; self-intersection safety is not guaranteed.",
            "required_basis": ["frozen rest-space source and bbox origin", "nonzero local X span Lx", "actual baseline normals N_base", "local coordinate/packing basis"],
            "capture_blockers": ["versioned legal wrangle/VEX or equivalent deformer parameters and ports", "actual P/N/bbox attributes/units, pack expansion, exact zero restoration and reopen readback"],
        },
    },
}


def annotate_control_contract(pack_id: str, controls: dict) -> dict:
    for name, definition in _DEFINITIONS.get(pack_id, {}).items():
        controls[name]["product_status"] = "approved"
        controls[name]["product_definition"] = copy.deepcopy({
            **definition,
            "proposal_sha256": PROPOSAL_SHA256,
            "decision_record": DECISION_RECORD,
            "approved_sections": [2, 3],
            "common_rules": COMMON_RULES,
            "common_capture_requirements": COMMON_CAPTURE_REQUIREMENTS,
        })
    return controls
