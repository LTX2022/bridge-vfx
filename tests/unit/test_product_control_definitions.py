from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from houdini_bridge import native_flip_rbd_domains as flip_rbd
from houdini_bridge import native_particle_ocean_geometry_domains as particle_ocean_geometry
from houdini_bridge import native_pyro_domains as pyro


MODULES = (
    (pyro, (pyro.SMOKE, pyro.FIRE)),
    (flip_rbd, flip_rbd.DOMAIN_IDS),
    (particle_ocean_geometry, particle_ocean_geometry.DOMAIN_IDS),
)
APPROVED = {
    "pyro_fire_v1": {"flame_height": "A01"},
    "water_flip_v1": {"collision_separation": "A02", "collision_passes": "A03"},
    "rbd_destruction_v1": {
        "fracture_scale": "R01", "fracture_variance": "R02", "impact_spread": "R03",
        "piece_scale": "R04", "velocity_variance": "R05", "impulse_scale": "R06",
    },
    "particles_v1": {
        "emission_variance": "P01", "size_variance": "P02", "collision_radius": "P03",
        "trail_length": "P04", "motion_blur_scale": "P05",
    },
    "swarm_flocking_v1": {"target_noise": "S01", "noise_strength": "S02"},
    "water_ocean_v1": {"directional_spread": "O01"},
    "procedural_geometry_v1": {
        "scatter_variance": "G01", "rotation_variance": "G02", "deformation": "G03",
    },
}
BASELINE_NATIVE_CONTRACT_SHA256 = {
    "pyro_smoke_v1": "0d8a3752b8956437746c664c5340eb0ee842659b8a36f1693713822b8083e7c4",
    "pyro_fire_v1": "e1a27704e74ef723d2777794ecf1fa3462c2db3f1c209c0700cb293b67b29c3b",
    "water_flip_v1": "061498b095921e9f23269db07fd9ed6ceb64602eebd1e3e7c76d62f2eef1f44c",
    "rbd_destruction_v1": "06d86f8c4ac3e3b188bd5aa916316a3c6a03afb243f7fb4b47d7970f497b909c",
    "particles_v1": "2de45bc0987ae7456eb05629be561c6fccf200c467189202f36bf435c56f280a",
    "swarm_flocking_v1": "360b46a27eabb26dba892f884e9fda99880444acd3b85446acab3ee10014aae8",
    "water_ocean_v1": "696c8816f808182293ce0b054a8c28cac272c0f1439d407523fb2570ad70efb9",
    "procedural_geometry_v1": "09ad26e2dd809a5cf2bdb5403fedfe6a612b71d0338534c6f8035cfdbfa2f857",
}
IMPLEMENTED_DELTAS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" /
    "product-native-implemented-deltas.json").read_text(encoding="utf-8"))
BASELINE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" /
                       "product-control-baseline-a3e7734.json").read_text(encoding="utf-8"))
IMPLEMENTED = {
    ("pyro_fire_v1", "flame_height"): "PYRO_HEIGHT_BASIS_REQUIRED",
    ("particles_v1", "size_variance"): "ACTUAL_NATIVE_CONTEXT_REQUIRED",
    ("particles_v1", "emission_variance"): "PARTICLE_EMISSION_AUTHORITY_REQUIRED",
    ("procedural_geometry_v1", "deformation"): "GEOMETRY_BASIS_REQUIRED",
    ("swarm_flocking_v1", "target_noise"): "ACTUAL_TASK_OWNED_NATIVE_NODE_REQUIRED",
    ("swarm_flocking_v1", "noise_strength"): "ACTUAL_TASK_OWNED_NATIVE_NODE_REQUIRED",
}


def contract_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class ProductControlDefinitionTests(unittest.TestCase):
    def test_exact_twenty_approved_controls_in_both_versions(self):
        for version in pyro.SUPPORTED_VERSIONS:
            approved = {}
            blocked = set()
            for module, domains in MODULES:
                for domain in domains:
                    for name, contract in module.control_contract(domain, version).items():
                        if contract["native_status"] == "blocked":
                            blocked.add((domain, name))
                        if contract.get("product_status") == "approved":
                            approved.setdefault(domain, {})[name] = contract["product_definition"]["decision_id"]
            self.assertEqual(approved, APPROVED)
            expected = {(domain, name) for domain, controls in APPROVED.items() for name in controls}
            self.assertEqual(blocked, expected - set(IMPLEMENTED))
            self.assertEqual(len(expected), 20)

    def test_metadata_contains_approved_definitions_and_capture_requirements(self):
        for module, domains in MODULES:
            for domain in domains:
                for name, contract in module.control_contract(domain, "21.0.631").items():
                    if name not in APPROVED.get(domain, {}):
                        self.assertNotIn("product_status", contract)
                        self.assertNotIn("product_definition", contract)
                        continue
                    metadata = contract["product_definition"]
                    with self.subTest(domain=domain, control=name):
                        self.assertEqual(metadata["proposal_sha256"], "7a5d8f699ee879c9d613832d9520ceb71580080f6ebadfd187fbd3b0389f4f9e")
                        self.assertEqual(metadata["decision_record"], "handover/CONTROL_DECISIONS_20261004.md")
                        self.assertEqual(metadata["approved_sections"], [2, 3])
                        for field in ("unit", "definition", "zero", "negative", "scope"):
                            self.assertIsInstance(metadata[field], str)
                            self.assertTrue(metadata[field])
                        for field in ("required_basis", "capture_blockers"):
                            self.assertIsInstance(metadata[field], list)
                            self.assertTrue(all(isinstance(item, str) and item for item in metadata[field]))
                        self.assertEqual(set(metadata["common_rules"]), {"units", "validation", "randomness", "basis", "ranges", "readback", "existing_definitions"})
                        capture = metadata["common_capture_requirements"]
                        self.assertEqual(capture["versions"], list(pyro.SUPPORTED_VERSIONS))
                        self.assertEqual(set(capture), {"versions", "interface", "attributes", "runtime"})

    def test_every_preexisting_native_contract_field_is_unchanged(self):
        self.assertEqual(BASELINE["source_revision"], "a3e7734e0f69b663be5bbd7d1f97bbdcb2d90b7d")
        self.assertEqual(IMPLEMENTED_DELTAS["source_revision"], BASELINE["source_revision"])
        self.assertEqual(IMPLEMENTED_DELTAS["source_sha256"], BASELINE["source_sha256"][
            "packages/houdini-bridge/src/houdini_bridge/native_particle_ocean_geometry_domains.py"])
        for version in pyro.SUPPORTED_VERSIONS:
            for module, domains in MODULES:
                for domain in domains:
                    native = module.control_contract(domain, version)
                    baseline = BASELINE["versions"][version][domain]
                    with self.subTest(version=version, domain=domain, scope="historical provenance"):
                        self.assertEqual(baseline["full_native_sha256"], BASELINE_NATIVE_CONTRACT_SHA256[domain])
                        self.assertEqual(sorted(native), baseline["control_names"])
                    products = {
                        name: {field: contract[field] for field in ("product_status", "product_definition") if field in contract}
                        for name, contract in native.items()
                    }
                    with self.subTest(version=version, domain=domain, scope="approved definitions"):
                        self.assertEqual(contract_digest(products), baseline["product_metadata_sha256"])
                    for name, fields in IMPLEMENTED_DELTAS["versions"][version].get(domain, {}).items():
                        for field, change in fields.items():
                            with self.subTest(version=version, domain=domain, control=name, field=field):
                                self.assertEqual(field in native[name], change["after_present"])
                                self.assertEqual(json.loads(json.dumps(native[name].get(field))), change["after"])
                            if change["before_present"]:
                                native[name][field] = change["before"]
                            else:
                                native[name].pop(field, None)
                    for name, contract in native.items():
                        contract.pop("product_status", None)
                        contract.pop("product_definition", None)
                        for field in BASELINE["mutable_native_fields"].get(domain, {}).get(name, []):
                            contract.pop(field, None)
                    with self.subTest(version=version, domain=domain):
                        self.assertEqual(contract_digest(native), baseline["unaffected_native_sha256"])

    def test_product_approval_does_not_unlock_native_writers(self):
        for version in pyro.SUPPORTED_VERSIONS:
            for module, domains in MODULES:
                for domain in domains:
                    contracts = module.control_contract(domain, version)
                    for name in APPROVED.get(domain, {}):
                        contract = contracts[name]
                        values = [contract["minimum"], contract["maximum"]]
                        if contract["minimum"] <= 0 <= contract["maximum"]:
                            values.append(0)
                        for value in values:
                            contexts = ({}, {"height_context": {}}, {"height_context": {"product_status": "approved"}}) if module is pyro else (
                                {}, {"observations": {}}, {"observations": {"product_status": "approved"}})
                            for context in contexts:
                                with self.subTest(version=version, domain=domain, control=name, value=value, context=context):
                                    with self.assertRaises(ValueError) as caught:
                                        module.control_write_plan(domain, name, value, version, **context)
                                    expected = IMPLEMENTED.get((domain, name), contract.get("blocker"))
                                    self.assertEqual(caught.exception.code, expected)

    def test_returned_product_metadata_cannot_mutate_other_controls_or_calls(self):
        first = particle_ocean_geometry.control_contract(particle_ocean_geometry.PARTICLES, "21.0.631")
        expected = particle_ocean_geometry.control_contract(particle_ocean_geometry.PARTICLES, "21.0.631")
        metadata = first["emission_variance"]["product_definition"]
        metadata["required_basis"].clear()
        metadata["common_rules"]["randomness"] = "changed"
        metadata["common_capture_requirements"]["versions"].clear()
        self.assertEqual(first["size_variance"], expected["size_variance"])
        self.assertEqual(particle_ocean_geometry.control_contract(particle_ocean_geometry.PARTICLES, "21.0.631"), expected)


if __name__ == "__main__":
    unittest.main()
