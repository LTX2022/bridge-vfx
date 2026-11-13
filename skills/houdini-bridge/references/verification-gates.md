# Verification gates

Do not report success until all applicable gates pass.

- Geometry: output is non-empty, cooks without errors, has finite values, a
  non-zero bounding box, and required normals/UVs.
- USD: expected prims, material bindings, camera, and render settings exist.
- Render: the output is newly written, non-empty, readable, at the requested
  dimensions, has no NaN or Inf pixels, and is not fully black or transparent.
- Animation: required frames exist; at minimum inspect first, middle, and last
  samples for simulation or animated tasks.
- Delivery: the artifact manifest names the output files, hashes, timestamps,
  actual renderer, and all gate results.

