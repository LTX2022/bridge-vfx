from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
VERIFIER_PATH = ROOT / "tools" / "verify_support_claims.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _EvidenceFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.attestation_key = b"bridge-skills-test-attestation-key-v1"
        self.files = {
            "houdini_addon": root / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py",
            "nuke_addon": root / "plugins" / "nuke" / "nuke_bridge_addon.py",
            "houdini_catalog": root
            / "packages"
            / "houdini-bridge"
            / "src"
            / "houdini_bridge"
            / "domain_packs.py",
            "nuke_catalog": root
            / "packages"
            / "dcc-task-runtime"
            / "src"
            / "dcc_task_runtime"
            / "domains.py",
            "source": root / "evidence" / "source.json",
            "artifact": root / "evidence" / "result.json",
            "output": root / "evidence" / "output.bin",
            "index": root / "outputs" / "live-validation" / "index.json",
        }
        for name, path in self.files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if name != "index":
                path.write_text(f"fixture:{name}\n", encoding="utf-8")

    def relative(self, name: str) -> str:
        return self.files[name].relative_to(self.root).as_posix()

    def entry(
        self,
        identity,
        *,
        pack_id: str = "pyro_smoke_v1",
        contract_sha256: str = "c" * 64,
        evidence_kind: str = "contract",
        application: str = "houdini",
    ) -> dict:
        addon_name = "nuke_addon" if application == "nuke" else "houdini_addon"
        catalog_name = "nuke_catalog" if pack_id == "nuke_composite_v1" else "houdini_catalog"
        artifact_kind = {
            "contract": "contract_probe",
            "real_reference": "real_reference_case",
            "fault_injection": "fault_injection_case",
            "live_model": "model_endpoint_probe",
        }.get(evidence_kind)
        if evidence_kind == "live_dcc":
            artifact_kind = "nuke_end_to_end" if application == "nuke" else "houdini_end_to_end"
        required_gates = {
            "contract": ["domain_contract_verified"],
            "real_reference": ["reference_case_validated"],
            "fault_injection": ["fault_injection_validated"],
            "live_dcc": ["dcc_execution_verified", "render_artifact_verified"],
            "live_model": ["model_identity_verified", "provider_response_verified"],
        }[evidence_kind]
        output_kind = {
            "contract": "contract_report",
            "real_reference": "comparison_preview",
            "fault_injection": "fault_report",
            "live_dcc": "render_output",
            "live_model": "provider_response",
        }[evidence_kind]
        entry = {
            "evidence_id": f"{pack_id}-{evidence_kind}-{application}",
            "domain_pack": pack_id,
            "pack_version": "1.0.0",
            "evidence_kind": evidence_kind,
            "status": "passed",
            "git_commit": "a" * 40,
            "dirty_diff_digest": "b" * 64,
            "executed_at": "2026-08-30T00:00:00+00:00",
            "probe_level": "contract" if evidence_kind == "contract" else "runtime",
            "execution_entrypoint": "tests/unit/test_support_evidence_edges_v2.py",
            "domain_contract_sha256": contract_sha256,
            "source_path": self.relative("source"),
            "source_sha256": _sha256(self.files["source"]),
            "application": application,
            "addon_source_path": self.relative(addon_name),
            "addon_source_sha256": _sha256(self.files[addon_name]),
            "catalog_source_path": self.relative(catalog_name),
            "catalog_source_sha256": _sha256(self.files[catalog_name]),
            "artifact_kind": artifact_kind,
            "primary_artifact_path": self.relative("artifact"),
        }
        if evidence_kind == "live_dcc":
            entry["application_build"] = "17.0v1" if application == "nuke" else "21.0.631"
            entry["semantic_control_coverage"] = {}
            if application == "houdini":
                entry.update({"renderer": "karma", "render_validated": True})
        if evidence_kind == "live_model":
            entry.update(
                {
                    "model_role": "planner",
                    "model_name": "deepseek-v4-flash",
                    "identity_verified": True,
                    "provider_response_sha256": _sha256(self.files["output"]),
                }
            )
        harness = {
            "schema": "bridge.support_harness/1.0",
            "artifact_kind": artifact_kind,
            "evidence_kind": evidence_kind,
            "domain_pack": pack_id,
            "pack_version": entry["pack_version"],
            "status": entry["status"],
            "probe_level": entry["probe_level"],
            "execution_entrypoint": entry["execution_entrypoint"],
            "git_commit": entry["git_commit"],
            "dirty_diff_digest": entry["dirty_diff_digest"],
            "domain_contract_sha256": entry["domain_contract_sha256"],
            "source_path": entry["source_path"],
            "source_sha256": entry["source_sha256"],
            "addon_source_path": entry["addon_source_path"],
            "addon_source_sha256": entry["addon_source_sha256"],
            "catalog_source_path": entry["catalog_source_path"],
            "catalog_source_sha256": entry["catalog_source_sha256"],
            "source_identity_stable": True,
            "support_promotion": False,
            "validation": {"passed": True},
            "gates": [
                {"name": name, "kind": "verification", "passed": True}
                for name in required_gates
            ],
            "artifacts": [
                {
                    "kind": output_kind,
                    "path": self.relative("output"),
                    "sha256": _sha256(self.files["output"]),
                }
            ],
        }
        if evidence_kind == "contract":
            harness["contract_available"] = True
        if evidence_kind in {"real_reference", "fault_injection"}:
            harness["case_validated"] = True
        if evidence_kind == "live_dcc":
            harness.update(
                {
                    "application": application,
                    "application_build": entry["application_build"],
                    "renderer": entry.get("renderer"),
                    "render_validated": True,
                    "semantic_control_coverage": entry["semantic_control_coverage"],
                }
            )
        if evidence_kind == "live_model":
            harness.update(
                {
                    "model_role": entry["model_role"],
                    "model_name": entry["model_name"],
                    "identity_verified": True,
                    "provider_response_sha256": entry["provider_response_sha256"],
                }
            )
        harness["evidence_identity"] = identity(harness)
        self.files["artifact"].write_text(
            json.dumps(harness, sort_keys=True), encoding="utf-8"
        )
        entry["artifact_paths"] = [
            self.relative("artifact"),
            self.relative("output"),
        ]
        entry["artifact_sha256"] = {
            self.relative("artifact"): _sha256(self.files["artifact"]),
            self.relative("output"): _sha256(self.files["output"]),
        }
        self.sign_entry(entry, identity)
        return entry

    def sign_entry(self, entry: dict, identity) -> None:
        entry["evidence_identity"] = identity(entry)
        entry["evidence_attestation"] = {
            "scheme": "hmac-sha256-v1",
            "key_id": hashlib.sha256(self.attestation_key).hexdigest(),
            "signature": hmac.new(
                self.attestation_key,
                b"bridge-skills-live-evidence-v1\0" + entry["evidence_identity"].encode("ascii"),
                hashlib.sha256,
            ).hexdigest(),
        }

    def rewrite_primary(self, entry: dict, identity, mutate, *, valid_identity: bool = True) -> None:
        payload = json.loads(self.files["artifact"].read_text(encoding="utf-8"))
        mutate(payload)
        payload["evidence_identity"] = identity(payload) if valid_identity else "0" * 64
        self.files["artifact"].write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        entry["artifact_sha256"][self.relative("artifact")] = _sha256(
            self.files["artifact"]
        )
        self.sign_entry(entry, identity)

    def write_index(self, entry: dict) -> None:
        self.files["index"].write_text(
            json.dumps({"schema_version": 1, "entries": [entry]}),
            encoding="utf-8",
        )


class SupportEvidenceVerifierNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = _load_module("_support_evidence_edge_verifier", VERIFIER_PATH)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = _EvidenceFixture(Path(self.temporary.name))
        self.contract_hashes = {
            "pyro_smoke_v1": "c" * 64,
            "explosion_composite_v1": "d" * 64,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _validate(self, entry: dict):
        with mock.patch.object(
            self.verifier,
            "_git_state",
            return_value=("a" * 40, "b" * 64),
        ):
            return self.verifier._validated_entries(
                {"schema_version": 1, "entries": [entry]},
                self.fixture.root,
                self.contract_hashes,
                self.fixture.attestation_key,
            )

    def test_valid_entry_passes_before_independent_mutations(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        valid, errors = self._validate(entry)
        self.assertEqual(errors, [])
        self.assertEqual([item["evidence_id"] for item in valid], [entry["evidence_id"]])

    def test_recomputed_identity_without_operator_attestation_is_rejected(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        entry["probe_level"] = "runtime"
        entry["evidence_identity"] = self.verifier.evidence_identity(entry)
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("evidence attestation" in item for item in errors), errors)

    def test_identity_and_contract_hash_mutations_are_rejected(self) -> None:
        original = self.fixture.entry(self.verifier.evidence_identity)

        bad_identity = copy.deepcopy(original)
        bad_identity["evidence_identity"] = "0" * 64
        valid, errors = self._validate(bad_identity)
        self.assertEqual(valid, [])
        self.assertTrue(any("evidence_identity mismatch" in item for item in errors), errors)

        bad_contract = copy.deepcopy(original)
        bad_contract["domain_contract_sha256"] = "0" * 64
        bad_contract["evidence_identity"] = self.verifier.evidence_identity(bad_contract)
        valid, errors = self._validate(bad_contract)
        self.assertEqual(valid, [])
        self.assertTrue(any("domain_contract_sha256 mismatch" in item for item in errors), errors)

    def test_source_and_artifact_hash_mutations_are_rejected(self) -> None:
        original = self.fixture.entry(self.verifier.evidence_identity)

        bad_source = copy.deepcopy(original)
        bad_source["source_sha256"] = "0" * 64
        bad_source["evidence_identity"] = self.verifier.evidence_identity(bad_source)
        valid, errors = self._validate(bad_source)
        self.assertEqual(valid, [])
        self.assertTrue(any("source_sha256 mismatch" in item for item in errors), errors)

        bad_artifact = copy.deepcopy(original)
        artifact_path = self.fixture.relative("artifact")
        bad_artifact["artifact_sha256"][artifact_path] = "0" * 64
        bad_artifact["evidence_identity"] = self.verifier.evidence_identity(bad_artifact)
        valid, errors = self._validate(bad_artifact)
        self.assertEqual(valid, [])
        self.assertTrue(any("artifact hash mismatch" in item for item in errors), errors)

    def test_nuke_evidence_cannot_bind_the_houdini_addon(self) -> None:
        entry = self.fixture.entry(
            self.verifier.evidence_identity,
            pack_id="explosion_composite_v1",
            contract_sha256="d" * 64,
            evidence_kind="live_dcc",
            application="nuke",
        )
        valid, errors = self._validate(entry)
        self.assertEqual(errors, [])
        self.assertEqual(len(valid), 1)

        entry["addon_source_path"] = self.fixture.relative("houdini_addon")
        entry["addon_source_sha256"] = _sha256(self.fixture.files["houdini_addon"])
        entry["evidence_identity"] = self.verifier.evidence_identity(entry)
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("addon_source_path mismatch" in item for item in errors), errors)

    def test_live_model_identity_and_response_artifact_are_both_required(self) -> None:
        entry = self.fixture.entry(
            self.verifier.evidence_identity,
            evidence_kind="live_model",
        )
        valid, errors = self._validate(entry)
        self.assertEqual(errors, [])
        self.assertEqual(len(valid), 1)

        entry["identity_verified"] = False
        entry["provider_response_sha256"] = "f" * 64
        entry["evidence_identity"] = self.verifier.evidence_identity(entry)
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("identity_verified must be true" in item for item in errors), errors)
        self.assertTrue(any("must name a hashed artifact" in item for item in errors), errors)

    def test_primary_harness_must_report_a_real_passing_validation(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        self.fixture.rewrite_primary(
            entry,
            self.verifier.evidence_identity,
            lambda payload: payload["validation"].update({"passed": False}),
        )
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("validation.passed must be true" in item for item in errors), errors)

    def test_primary_harness_requires_kind_specific_gates_and_output(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        self.fixture.rewrite_primary(
            entry,
            self.verifier.evidence_identity,
            lambda payload: (
                payload.update(
                    {
                        "gates": [
                            {
                                "name": "generic_validation",
                                "kind": "verification",
                                "passed": True,
                            }
                        ]
                    }
                ),
                payload["artifacts"][0].update({"kind": "generic_output"}),
            ),
        )
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("missing required harness gates" in item for item in errors), errors)
        self.assertTrue(any("missing required output kind" in item for item in errors), errors)

    def test_primary_harness_must_bind_a_stable_source_identity(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        self.fixture.rewrite_primary(
            entry,
            self.verifier.evidence_identity,
            lambda payload: payload.update({"source_identity_stable": False}),
        )
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("source_identity_stable must be true" in item for item in errors), errors)

    def test_primary_harness_internal_identity_is_not_replaceable_by_outer_signature(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        self.fixture.rewrite_primary(
            entry,
            self.verifier.evidence_identity,
            lambda _payload: None,
            valid_identity=False,
        )
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("primary artifact evidence_identity mismatch" in item for item in errors), errors)

    def test_primary_harness_cannot_self_report_a_different_checkout(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        self.fixture.rewrite_primary(
            entry,
            self.verifier.evidence_identity,
            lambda payload: payload.update({"domain_contract_sha256": "0" * 64}),
        )
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("primary artifact domain_contract_sha256 mismatch" in item for item in errors), errors)

    def test_unknown_or_cross_application_artifact_kind_fails_closed(self) -> None:
        entry = self.fixture.entry(self.verifier.evidence_identity)
        entry["artifact_kind"] = "raw_probe_dump"
        self.fixture.sign_entry(entry, self.verifier.evidence_identity)
        valid, errors = self._validate(entry)
        self.assertEqual(valid, [])
        self.assertTrue(any("artifact_kind is missing, unknown" in item for item in errors), errors)


class RuntimeSupportEvidenceNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.addon = _load_module("_runtime_support_evidence_edges", ADDON_PATH)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.fixture = _EvidenceFixture(Path(self.temporary.name))
        self.original_paths = (
            self.addon._FX_ADDON_SOURCE,
            self.addon._FX_NUKE_ADDON_SOURCE,
            self.addon._FX_CATALOG_SOURCE,
        )
        self.original_index = os.environ.get(self.addon._FX_SUPPORT_INDEX_ENV)
        self.original_attestation_key = os.environ.get(self.addon._FX_EVIDENCE_ATTESTATION_KEY_ENV)
        self.addon._FX_ADDON_SOURCE = self.fixture.files["houdini_addon"]
        self.addon._FX_NUKE_ADDON_SOURCE = self.fixture.files["nuke_addon"]
        self.addon._FX_CATALOG_SOURCE = self.fixture.files["houdini_catalog"]
        os.environ[self.addon._FX_SUPPORT_INDEX_ENV] = str(self.fixture.files["index"])
        self.attestation_key_path = self.fixture.root / "private" / "evidence-attestation.key"
        self.attestation_key_path.parent.mkdir(parents=True, exist_ok=True)
        self.attestation_key_path.write_bytes(self.fixture.attestation_key)
        if os.name != "nt":
            self.attestation_key_path.chmod(0o600)
        os.environ[self.addon._FX_EVIDENCE_ATTESTATION_KEY_ENV] = str(self.attestation_key_path)
        self.git_state_patcher = mock.patch.object(
            self.addon,
            "_fx_git_state",
            return_value=("a" * 40, "b" * 64),
        )
        self.git_state_patcher.start()
        self.pack_id = "pyro_smoke_v1"
        self.pack = self.addon._FX_PACKS[self.pack_id]
        self.semantic_contract_patcher = mock.patch.object(
            self.addon,
            "_fx_host_semantic_contract",
            return_value=(self.addon._fx_pack_semantic_contract(self.pack), None),
        )
        self.semantic_contract_patcher.start()

    def tearDown(self) -> None:
        self.semantic_contract_patcher.stop()
        self.git_state_patcher.stop()
        (
            self.addon._FX_ADDON_SOURCE,
            self.addon._FX_NUKE_ADDON_SOURCE,
            self.addon._FX_CATALOG_SOURCE,
        ) = self.original_paths
        if self.original_index is None:
            os.environ.pop(self.addon._FX_SUPPORT_INDEX_ENV, None)
        else:
            os.environ[self.addon._FX_SUPPORT_INDEX_ENV] = self.original_index
        if self.original_attestation_key is None:
            os.environ.pop(self.addon._FX_EVIDENCE_ATTESTATION_KEY_ENV, None)
        else:
            os.environ[self.addon._FX_EVIDENCE_ATTESTATION_KEY_ENV] = self.original_attestation_key
        self.temporary.cleanup()

    def _entry(self) -> dict:
        return self.fixture.entry(
            self.addon._fx_entry_identity,
            contract_sha256=self.addon._fx_pack_contract_sha256(self.pack),
        )

    def test_runtime_accepts_bound_entry_then_rejects_identity_mutation(self) -> None:
        entry = self._entry()
        self.fixture.write_index(entry)
        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(len(valid), 1, diagnostics)

        entry["evidence_identity"] = "0" * 64
        self.fixture.write_index(entry)
        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(valid, [])
        self.assertIn(
            "evidence_identity_mismatch",
            diagnostics["rejected_entries"][0]["reasons"],
        )

    def test_runtime_rejects_recomputed_identity_without_valid_attestation(self) -> None:
        entry = self._entry()
        entry["probe_level"] = "runtime"
        entry["evidence_identity"] = self.addon._fx_entry_identity(entry)
        self.fixture.write_index(entry)
        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(valid, [])
        self.assertIn(
            "evidence_attestation_invalid_or_unavailable",
            diagnostics["rejected_entries"][0]["reasons"],
        )

    def test_runtime_rejects_signed_entry_when_private_key_is_unavailable(self) -> None:
        entry = self._entry()
        self.fixture.write_index(entry)
        os.environ.pop(self.addon._FX_EVIDENCE_ATTESTATION_KEY_ENV, None)
        with mock.patch.object(Path, "home", return_value=self.fixture.root / "missing-home"):
            valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(valid, [])
        self.assertFalse(diagnostics["attestation_key_available"])
        self.assertIn(
            "evidence_attestation_invalid_or_unavailable",
            diagnostics["rejected_entries"][0]["reasons"],
        )

    def test_runtime_rejects_artifact_bytes_changed_after_index_was_signed(self) -> None:
        entry = self._entry()
        self.fixture.write_index(entry)
        self.fixture.files["artifact"].write_text("tampered artifact\n", encoding="utf-8")

        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(valid, [])
        reasons = diagnostics["rejected_entries"][0]["reasons"]
        self.assertTrue(any(item.startswith("artifact_sha256_mismatch:") for item in reasons), reasons)

    def test_runtime_rejects_host_addon_semantic_contract_drift(self) -> None:
        entry = self._entry()
        self.fixture.write_index(entry)
        self.semantic_contract_patcher.stop()
        self.semantic_contract_patcher = mock.patch.object(
            self.addon,
            "_fx_host_semantic_contract",
            return_value=({"different": True}, None),
        )
        self.semantic_contract_patcher.start()

        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)

        self.assertEqual(valid, [])
        self.assertIn(
            "host_addon_semantic_contract_mismatch",
            diagnostics["rejected_entries"][0]["reasons"],
        )

    def test_runtime_rejects_failed_primary_harness_validation(self) -> None:
        entry = self._entry()
        self.fixture.rewrite_primary(
            entry,
            self.addon._fx_entry_identity,
            lambda payload: payload["validation"].update({"passed": False}),
        )
        self.fixture.write_index(entry)
        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(valid, [])
        self.assertIn(
            "primary_artifact_validation_not_passed",
            diagnostics["rejected_entries"][0]["reasons"],
        )

    def test_runtime_rejects_primary_harness_internal_identity_mismatch(self) -> None:
        entry = self._entry()
        self.fixture.rewrite_primary(
            entry,
            self.addon._fx_entry_identity,
            lambda _payload: None,
            valid_identity=False,
        )
        self.fixture.write_index(entry)
        valid, diagnostics = self.addon._fx_valid_evidence_entries(self.pack_id, self.pack)
        self.assertEqual(valid, [])
        self.assertIn(
            "primary_artifact_evidence_identity_mismatch",
            diagnostics["rejected_entries"][0]["reasons"],
        )

class DoubaoAtomicEvidenceVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = _load_module("_doubao_atomic_support", VERIFIER_PATH)

    def test_ui_outer_pass_cannot_override_failed_cycle(self) -> None:
        events = [
            {"event_id": f"r-{i}", "session_id": "s", "kind": "read_cycle", "cycle": i, "read_succeeded": i != 4}
            for i in range(1, 6)
        ] + [
            {"event_id": f"o-{subject}", "session_id": "s", "kind": "observation", "subject": subject, "observed": True}
            for subject in ("composer", "image_entry", "model_label")
        ] + [{"event_id": "p", "session_id": "s", "kind": "privacy", "input_class": "synthetic", "existing_conversation_accessed": False}]
        payload = {
            "schema": "bridge.doubao_ui_events/2.0", "route_id": "DoubaoDesktopRoute",
            "isolated_session_id": "s", "route_identity": {}, "events": events, "passed": True, "read_cycles": [True] * 5,
        }
        self.assertTrue(self.verifier._doubao_ui_manifest_errors(payload))

    def test_conformance_outer_pass_cannot_override_forbidden_trace(self) -> None:
        cases = []
        scenarios = ("build_inspect", "causal_candidate", "approval_recovery")
        for pack in self.verifier.PACKS:
            for scenario in scenarios:
                cases.append({
                    "case_id": f"{pack}-{scenario}", "domain_pack": pack, "scenario": scenario,
                    "input_class": "synthetic",
                    "expected_first_action_id": "a", "actions": [{"action_id": "a", "allowed": True}],
                    "expected_final_state": "done", "observed_final_state": "done", "corrections": [],
                    "reference_media": {"provided": scenario == "causal_candidate", "synthetic": True},
                })
        cases[0]["actions"][0]["allowed"] = False
        payload = {
            "schema": "bridge.doubao_skill_conformance/1.0", "cases": cases,
            "passed": True, "all_required_cases_passed": True, "forbidden_action_count": 0,
            "first_action_accuracy": 1.0,
        }
        errors = self.verifier._doubao_conformance_report_errors(payload)
        self.assertTrue(any("forbidden" in error for error in errors), errors)

    def test_conformance_recomputes_first_action_rate_and_corrections(self) -> None:
        cases = []
        for pack in self.verifier.PACKS:
            for scenario in ("build_inspect", "causal_candidate", "approval_recovery"):
                cases.append({
                    "case_id": f"{pack}-{scenario}", "domain_pack": pack, "scenario": scenario,
                    "input_class": "synthetic", "expected_first_action_id": "a",
                    "actions": [{"action_id": "a", "allowed": True}], "expected_final_state": "done",
                    "observed_final_state": "done", "corrections": [],
                    "reference_media": {"provided": scenario == "causal_candidate", "synthetic": True},
                })
        for case in cases[:3]:
            case["actions"][0]["action_id"] = "wrong"
        cases[3]["corrections"] = [{}, {}, {}]
        errors = self.verifier._doubao_conformance_report_errors({
            "schema": "bridge.doubao_skill_conformance/1.0", "cases": cases,
            "first_action_accuracy": 1.0, "all_required_cases_passed": True,
        })
        self.assertTrue(any("95" in error for error in errors), errors)
        self.assertTrue(any("correction" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
