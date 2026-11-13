# Domain support status

This file states software maturity, not artistic quality. Status may advance only when matching machine-readable evidence exists in `outputs/live-validation/index.json` and every non-empty entry has a valid independent trusted-operator attestation; self-recomputed hashes are not sufficient.

| Domain pack | Contract | Live H21 | Live H22 | Live Nuke 17 | Current status |
| --- | --- | --- | --- | --- | --- |
| pyro_smoke_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| pyro_fire_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| particles_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| water_ocean_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| water_flip_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| crowd_agents_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| swarm_flocking_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| vellum_cloth_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| vellum_softbody_grains_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| hair_fur_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| rbd_destruction_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| procedural_geometry_v1 | interface implemented; software tests only | missing | missing | not required | experimental |
| material_lookdev_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| lighting_camera_render_v1 | interface implemented; software tests only | missing | missing | optional comp missing | experimental |
| nuke_composite_v1 | interface implemented; software tests only | not required | not required | missing | experimental |
| explosion_composite_v1 | interface implemented; software tests only | missing | missing | missing | experimental |

Maturity values are `experimental`, `contract-tested`, `live-validated`, and `supported`. "Interface implemented; software tests only" records the current source/test surface; it is not machine-readable contract evidence and does not advance maturity. A bridge health response, static node-name list, mocked client, or successful software unit test cannot advance a pack to `live-validated` or `supported`.

The existing v1.4 evidence covers only `houdini.model_to_karma` on Houdini 21/22 and `nuke.render_delivery` on Nuke 17. It is intentionally not reused as evidence for these packs.
