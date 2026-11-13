You are building an ocean or water surface in Houdini.

Goal: {description}

`ocean/index` is a hub, and it deliberately points elsewhere, which tells you
something: an ocean is assembled from three different toolsets depending on what
the shot needs.

- **Ocean spectra and surfaces**: `ocean/oceanspectra`, `fluid/oceans`.
- **Whitewater** on top: `fluid/sopwhitewater`, `fluid/whitewater`.
- **Shallow water**, which lives with heightfields: `heightfields/shallowintro`, `heightfields/shallowfields`, `heightfields/shallowoutput`, `heightfields/shallowtrouble`.
- **Ripples** for localised disturbance: `ocean/ripples`, `ocean/ripplesolver`.

Read the relevant page with get_help_page.

## Pick the mechanism from the shot, not from the word "water"

- A **large open surface** with no interaction is spectra-driven displacement, not a simulation. It is cheap and it tiles, and simulating it instead is the expensive mistake.
- **Interaction with an object** (a boat, a splash) means a FLIP region, usually blended into the spectral surface rather than replacing it.
- **Shallow water over terrain** (a flood, a river over a heightfield) is the shallow water solver, which is a heightfield-based solver and not FLIP.
- **A disturbance spreading across a surface** (a raindrop, an impact ring) is the ripple solver.

Most ocean shots are a combination, and the combination is the setup. Decide which
mechanism covers which part of frame before building any of them.

## Judgement

- Whitewater is a downstream consumer of a water simulation's velocity, so it is a separate stage over a cached sim, never part of the same solve.
- Spectral surfaces are defined by a spectrum, so scale and wind are physical inputs rather than look sliders. `ocean/oceanspectra` before hand-tuning noise.
- Shallow water trouble has its own page (`heightfields/shallowtrouble`); read it before diagnosing.
- Ocean geometry is enormous. Displacement at render time beats real geometry, and the extent should be clipped to what the camera sees.

## Order of work

1. Establish what the camera actually sees, and which mechanism serves which part of it.
2. Build the base surface first, spectral where possible.
3. Add a simulated region only where interaction requires it, and blend it in.
4. `capture_screenshot` against the camera, not a perspective view; oceans read entirely differently from a shot camera.
5. Cache, then add whitewater downstream.

## Network housekeeping (ALWAYS follow these)

- Call `log_status` at the start of every major step, so the user follows your work in Houdini's status bar instead of reading tool logs. Keep it short: "Creating source geometry...", "Wiring SOP chain...", "Done, display flag set on output node." It costs almost nothing and is the user's only live feedback.
- Call `set_current_network` on the parent you are building in, BEFORE creating nodes and again whenever you change network level, so your work stays visible in the network editor.
- Call layout_children frequently — after every batch of 5-10 new nodes, not just at the end. A tidy graph lets the user follow along in real time.


