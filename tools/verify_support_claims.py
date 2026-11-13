#!/usr/bin/env python3
"""Reject domain maturity claims that are not backed by live evidence.

The evidence index is intentionally empty for a fresh checkout.  Contract
tests may prove the software surface exists, but only immutable live evidence
may advance a domain to ``live-validated`` or ``supported``.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
SUPPORT_PATH = ROOT / "docs" / "domain-support.md"
EVIDENCE_PATH = ROOT / "outputs" / "live-validation" / "index.json"
REQUIRED_HOUDINI_BUILDS = ("21.0.631", "22.0.459")
SUPPORTED_HOUDINI_BUILDS = ("21.0.631", "22.0.429", "22.0.459")
REQUIRED_NUKE_BUILD = "17.0v1"
PACKS = {
    "pyro_smoke_v1",
    "pyro_fire_v1",
    "particles_v1",
    "water_ocean_v1",
    "water_flip_v1",
    "crowd_agents_v1",
    "swarm_flocking_v1",
    "vellum_cloth_v1",
    "vellum_softbody_grains_v1",
    "hair_fur_v1",
    "rbd_destruction_v1",
    "procedural_geometry_v1",
    "material_lookdev_v1",
    "lighting_camera_render_v1",
    "nuke_composite_v1",
    "explosion_composite_v1",
}
MATURITY = {"experimental", "contract-tested", "live-validated", "supported"}
EVIDENCE_KINDS = {"contract", "real_reference", "fault_injection", "live_dcc", "live_model", "model_skill_conformance"}
ROW = re.compile(r"^\|\s*([a-z0-9_]+)\s*\|.*\|\s*([a-z-]+)\s*\|\s*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
EVIDENCE_ATTESTATION_KEY_ENV = "BRIDGE_SKILLS_EVIDENCE_ATTESTATION_KEY_FILE"
EVIDENCE_ATTESTATION_SCHEME = "hmac-sha256-v1"
EVIDENCE_ATTESTATION_CONTEXT = b"bridge-skills-live-evidence-v1\0"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_identity(entry: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in entry.items()
        if key not in {"evidence_identity", "evidence_attestation"}
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evidence_attestation(entry: dict[str, Any], key: bytes) -> dict[str, str]:
    """Create the detached operator attestation expected by the verifier."""

    identity = str(entry.get("evidence_identity") or "")
    if not SHA256.fullmatch(identity):
        raise ValueError("evidence_identity must be calculated before attestation")
    return {
        "scheme": EVIDENCE_ATTESTATION_SCHEME,
        "key_id": hashlib.sha256(key).hexdigest(),
        "signature": hmac.new(key, EVIDENCE_ATTESTATION_CONTEXT + identity.encode("ascii"), hashlib.sha256).hexdigest(),
    }


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    parts = absolute.parts
    if not parts:
        return False
    current = Path(parts[0])
    for component in parts[1:]:
        current = current / component
        if current.is_symlink():
            return True
    return False


def _load_evidence_attestation_key() -> Optional[bytes]:
    configured = str(os.environ.get(EVIDENCE_ATTESTATION_KEY_ENV) or "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / ".bridge-skills" / "evidence-attestation.key"
    try:
        info = path.lstat()
        parent_info = path.parent.stat()
        if path.is_symlink() or _path_has_symlink(path) or not stat.S_ISREG(info.st_mode):
            return None
        if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            return None
        if os.name != "nt" and (
            parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o022
        ):
            return None
        key = path.read_bytes().strip()
    except OSError:
        return None
    return key if len(key) >= 32 else None


def _attestation_valid(entry: dict[str, Any], key: Optional[bytes]) -> bool:
    if key is None:
        return False
    supplied = entry.get("evidence_attestation")
    if not isinstance(supplied, dict):
        return False
    try:
        expected = evidence_attestation(entry, key)
    except ValueError:
        return False
    return (
        supplied.get("scheme") == expected["scheme"]
        and hmac.compare_digest(str(supplied.get("key_id") or ""), expected["key_id"])
        and hmac.compare_digest(str(supplied.get("signature") or ""), expected["signature"])
    )


def _load_module(name: str, path: Path):
    package_name = name + "_package" if (path.parent / "__init__.py").is_file() else None
    module_name = package_name + "." + path.stem if package_name else name
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load {}".format(path))
    module = importlib.util.module_from_spec(spec)
    owned_names = lambda key: key == module_name or (
        package_name is not None and (key == package_name or key.startswith(package_name + ".")))
    previous = {key: value for key, value in sys.modules.items() if owned_names(key)}
    try:
        if package_name:
            package = ModuleType(package_name)
            package.__path__ = [str(path.parent)]
            package.__package__ = package_name
            package.__spec__ = importlib.util.spec_from_file_location(
                package_name, path.parent / "__init__.py",
                submodule_search_locations=package.__path__)
            sys.modules[package_name] = package
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key in tuple(sys.modules):
            if owned_names(key):
                sys.modules.pop(key, None)
        sys.modules.update(previous)


def _host_semantic_contract(host_pack: Any) -> dict[str, Any]:
    """Normalize a host-side pack to the canonical public execution fields.

    Mirrors ``houdini_bridge_addon._fx_pack_semantic_contract``: the connection
    wires (source role/output -> destination role/input) are part of the
    semantic contract and participate in comparison and digest alike.
    """
    return {
        "version": str(host_pack.version),
        "nodes": [
            {
                "role": str(node.role),
                "category": str(node.category),
                "types": [str(item) for item in node.type_candidates],
                "required_parms": [
                    [str(alias) for alias in aliases]
                    for aliases in node.required_parameter_aliases
                ],
                "input_role": str(node.input_role or "") or None,
            }
            for node in host_pack.nodes
        ],
        "controls": {
            str(control.identifier): {
                "role": str(control.node_role),
                "aliases": [str(item) for item in control.parameter_aliases],
                "minimum": float(control.minimum),
                "maximum": float(control.maximum),
                "value_type": str(control.value_type),
                "invalidates_from": str(control.invalidates_from),
                "application": str(control.application),
            }
            for control in sorted(host_pack.controls, key=lambda item: item.identifier)
        },
        "evidence": sorted(str(item) for item in host_pack.evidence),
        "simulation_cache": bool(host_pack.simulation_cache),
        "connections": [
            {
                "source_role": str(item.get("source_role") or ""),
                "source_output": int(item.get("source_output") or 0),
                "destination_role": str(item.get("destination_role") or ""),
                "destination_input": int(item.get("destination_input") or 0),
            }
            for item in (
                [connection.to_dict() for connection in getattr(host_pack, "connections", ()) or ()]
                or host_pack.declared_connections()
            )
        ],
    }


def _pack_semantic_drift(addon_module: Any, addon_pack: dict[str, Any], host_pack: Any) -> list[str]:
    """Drift reasons between one add-on pack dict and one host pack object."""
    if addon_module._fx_pack_semantic_contract(addon_pack) != _host_semantic_contract(host_pack):
        return ["Houdini host/add-on semantic contract mismatch"]
    return []


def _domain_contract_hashes(
    root: Path,
) -> tuple[
    dict[str, str],
    list[str],
    dict[str, dict[str, set[str]]],
    list[str],
]:
    addon = _load_module(
        "_support_claims_houdini_addon",
        root / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py",
    )
    hashes = {
        pack_id: addon._fx_pack_contract_sha256(pack)
        for pack_id, pack in addon._FX_PACKS.items()
    }
    legacy = [
        pack_id
        for pack_id, pack in addon._FX_PACKS.items()
        if pack.get("validated_houdini_versions") or pack.get("karma_render_validated")
    ]
    controls: dict[str, dict[str, set[str]]] = {
        pack_id: {
            application: {
                name
                for name, control in pack.get("controls", {}).items()
                if str(control.get("application") or "houdini") == application
            }
            for application in {str(control.get("application") or "houdini") for control in pack.get("controls", {}).values()}
        }
        for pack_id, pack in addon._FX_PACKS.items()
    }
    host_catalog = _load_module(
        "_support_claims_houdini_host_catalog",
        root / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "domain_packs.py",
    )
    semantic_drift: list[str] = []
    host_packs = {pack.identifier: pack for pack in host_catalog.all_domain_packs()}
    if set(host_packs) != set(addon._FX_PACKS):
        semantic_drift.append(
            "Houdini host/add-on pack ids differ: host={} addon={}".format(
                sorted(host_packs), sorted(addon._FX_PACKS)
            )
        )
    for pack_id in sorted(set(host_packs) & set(addon._FX_PACKS)):
        host_pack = host_packs[pack_id]
        host_contract = _host_semantic_contract(host_pack)
        if addon._fx_pack_semantic_contract(addon._FX_PACKS[pack_id]) != host_contract:
            semantic_drift.append(
                "{}: Houdini host/add-on semantic contract mismatch".format(pack_id)
            )
    runtime_src = root / "packages" / "dcc-task-runtime" / "src"
    inserted = False
    if str(runtime_src) not in sys.path:
        sys.path.insert(0, str(runtime_src))
        inserted = True
    try:
        from dcc_task_runtime import builtin_domain_registry

        nuke_pack = builtin_domain_registry().get("nuke_composite_v1", "1.0.0")
        summary = nuke_pack.to_summary()
    finally:
        if inserted:
            try:
                sys.path.remove(str(runtime_src))
            except ValueError:
                pass
    hashes["nuke_composite_v1"] = hashlib.sha256(
        json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    controls["nuke_composite_v1"] = {
        "nuke": {control.name for control in nuke_pack.controls if control.application == "nuke"}
    }
    return hashes, legacy, controls, semantic_drift


def _resolve_repo_file(root: Path, value: Any) -> Path | None:
    root = Path(root).absolute()
    # Check the caller-provided root before resolving it; resolving first would
    # erase the fact that the repository itself was reached through a symlink.
    if root.is_symlink():
        return None
    text = str(value or "").strip()
    if not text:
        return None
    relative = Path(text)
    if relative.is_absolute():
        return None
    candidate = root / relative
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            return None
    path = candidate.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _doubao_ui_manifest_errors(payload: Any, expected_route: Optional[Mapping[str, Any]] = None) -> list[str]:
    """Recompute UI acceptance from atomic events; summaries are ignored."""
    if not isinstance(payload, dict) or payload.get("schema") != "bridge.doubao_ui_events/2.0":
        return ["Doubao UI event manifest schema mismatch"]
    session = str(payload.get("isolated_session_id") or "")
    events = payload.get("events")
    if payload.get("route_id") != "DoubaoDesktopRoute" or not session or not isinstance(events, list):
        return ["Doubao UI route, session, or events are invalid"]
    errors: list[str] = []
    identity = payload.get("route_identity")
    if not isinstance(identity, dict):
        errors.append("Doubao UI exact route identity is missing")
    elif expected_route is not None:
        if identity.get("route_id") != "DoubaoDesktopRoute":
            errors.append("Doubao UI route identity mismatch: route_id")
        for field in ("bundle_id", "app_version", "executable_path", "executable_sha256", "driver_sha256"):
            if str(identity.get(field) or "") != str(expected_route.get(field) or ""):
                errors.append("Doubao UI route identity mismatch: {}".format(field))
    ids: set[str] = set()
    cycles: dict[int, bool] = {}
    observations: dict[str, bool] = {}
    privacy = 0
    for event in events:
        if not isinstance(event, dict):
            errors.append("Doubao UI event must be an object")
            continue
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in ids or event.get("session_id") != session:
            errors.append("Doubao UI event identity/session mismatch")
            continue
        ids.add(event_id)
        kind = event.get("kind")
        if kind == "read_cycle":
            cycle = event.get("cycle")
            if type(cycle) is not int or cycle < 1 or cycle > 5 or cycle in cycles:
                errors.append("Doubao UI read cycles must be unique 1..5")
            else:
                cycles[cycle] = event.get("read_succeeded") is True
        elif kind == "observation":
            subject = event.get("subject")
            if subject not in {"composer", "image_entry", "model_label"} or subject in observations:
                errors.append("Doubao UI observation is invalid or duplicated")
            else:
                observations[str(subject)] = event.get("observed") is True
        elif kind == "privacy":
            privacy += 1
            if event.get("input_class") != "synthetic" or event.get("existing_conversation_accessed") is not False:
                errors.append("Doubao UI privacy boundary failed")
        else:
            errors.append("unknown Doubao UI event kind")
    if set(cycles) != set(range(1, 6)) or not all(cycles.values()):
        errors.append("five successful atomic UI read cycles are required")
    if privacy < 1:
        errors.append("Doubao UI privacy event is required")
    if not all(observations.get(item) is True for item in ("composer", "image_entry", "model_label")):
        errors.append("Doubao UI composer/image/model observations are incomplete")
    return errors


def _doubao_conformance_report_errors(payload: Any) -> list[str]:
    """Recompute the 48-case gate from traces; report summary flags are ignored."""
    if not isinstance(payload, dict) or payload.get("schema") != "bridge.doubao_skill_conformance/1.0":
        return ["Doubao conformance report schema mismatch"]
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return ["Doubao conformance cases must be a list"]
    required = {(pack, scenario) for pack in PACKS for scenario in ("build_inspect", "causal_candidate", "approval_recovery")}
    seen: set[tuple[str, str]] = set()
    ids: set[str] = set()
    first_correct = 0
    forbidden = 0
    errors: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            errors.append("Doubao conformance case must be an object")
            continue
        case_id = str(case.get("case_id") or "")
        key = (str(case.get("domain_pack") or ""), str(case.get("scenario") or ""))
        if not case_id or case_id in ids or key in seen or key not in required:
            errors.append("Doubao conformance case identity is duplicate or unknown")
            continue
        ids.add(case_id)
        seen.add(key)
        actions = case.get("actions")
        corrections = case.get("corrections")
        if not isinstance(actions, list) or not actions or not all(isinstance(action, dict) for action in actions):
            errors.append("Doubao conformance action trace is missing")
            continue
        if not isinstance(corrections, list) or len(corrections) > 2:
            errors.append("Doubao conformance correction bound exceeded")
        if case.get("input_class") != "synthetic":
            errors.append("Doubao conformance input must be synthetic")
        if str(actions[0].get("action_id") or "") == str(case.get("expected_first_action_id") or "") and case.get("expected_first_action_id"):
            first_correct += 1
        case_forbidden = sum(action.get("allowed") is not True for action in actions)
        forbidden += case_forbidden
        if case_forbidden:
            errors.append("Doubao conformance attempted a forbidden action")
        if not case.get("expected_final_state") or case.get("observed_final_state") != case.get("expected_final_state"):
            errors.append("Doubao conformance case did not reach its expected final state")
        media = case.get("reference_media")
        if key[1] == "causal_candidate" and not (
            isinstance(media, dict) and media.get("provided") is True and media.get("synthetic") is True
        ):
            errors.append("Doubao causal candidate lacks synthetic reference-media evidence")
    if seen != required:
        errors.append("Doubao report must contain exactly 16 domains x 3 scenarios")
    if len(cases) != 48:
        errors.append("Doubao report case count must be exactly 48")
    if cases and first_correct / 48 < 0.95:
        errors.append("Doubao first-action accuracy is below 95 percent")
    if forbidden != 0:
        errors.append("Doubao forbidden-action count must be zero")
    return errors


def _support_harness_errors(entry: dict[str, Any], root: Path) -> list[str]:
    """Validate the signed entry against a known structured harness artifact."""

    errors: list[str] = []
    expected_kinds = {
        "contract": {"contract_probe"},
        "real_reference": {"real_reference_case"},
        "fault_injection": {"fault_injection_case"},
        "live_model": {"model_endpoint_probe"},
        "model_skill_conformance": {"doubao_skill_conformance"},
    }
    evidence_kind = str(entry.get("evidence_kind") or "")
    if evidence_kind == "live_dcc":
        expected_kinds["live_dcc"] = {
            "nuke_end_to_end"
            if str(entry.get("application") or "") == "nuke"
            else "houdini_end_to_end"
        }
    artifact_kind = str(entry.get("artifact_kind") or "")
    if artifact_kind not in expected_kinds.get(evidence_kind, set()):
        return ["artifact_kind is missing, unknown, or incompatible with evidence_kind"]
    primary_text = str(entry.get("primary_artifact_path") or "")
    primary = _resolve_repo_file(root, primary_text)
    if primary is None or not primary.is_file() or primary.is_symlink():
        return ["primary_artifact_path is missing or unsafe"]
    if primary_text not in (entry.get("artifact_paths") or []):
        errors.append("primary artifact is absent from artifact_paths")
    try:
        payload = json.loads(primary.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return errors + ["primary artifact is not valid UTF-8 JSON"]
    if not isinstance(payload, dict) or payload.get("schema") != "bridge.support_harness/1.0":
        return errors + ["primary artifact has an unknown harness schema"]
    if str(payload.get("evidence_identity") or "") != evidence_identity(payload):
        errors.append("primary artifact evidence_identity mismatch")
    if payload.get("artifact_kind") != artifact_kind:
        errors.append("primary artifact_kind mismatch")
    for field in (
        "evidence_kind",
        "domain_pack",
        "pack_version",
        "probe_level",
        "execution_entrypoint",
        "git_commit",
        "dirty_diff_digest",
        "domain_contract_sha256",
        "source_path",
        "source_sha256",
        "addon_source_path",
        "addon_source_sha256",
        "catalog_source_path",
        "catalog_source_sha256",
    ):
        if str(payload.get(field) or "") != str(entry.get(field) or ""):
            errors.append("primary artifact {} mismatch".format(field))
    if payload.get("source_identity_stable") is not True:
        errors.append("primary artifact source_identity_stable must be true")
    if payload.get("support_promotion") is not False:
        errors.append("primary artifact must explicitly forbid automatic support promotion")
    if str(payload.get("status") or "") != str(entry.get("status") or ""):
        errors.append("primary artifact status mismatch")
    validation = payload.get("validation")
    if not isinstance(validation, dict) or validation.get("passed") is not True:
        errors.append("primary artifact validation.passed must be true")
    gates = payload.get("gates")
    verification_gates = [
        gate
        for gate in gates or []
        if isinstance(gate, dict) and gate.get("kind") == "verification"
    ] if isinstance(gates, list) else []
    if not verification_gates:
        errors.append("primary artifact has no verification gate")
    elif entry.get("status") == "passed" and not all(gate.get("passed") is True for gate in verification_gates):
        errors.append("primary artifact contains a failed verification gate")
    required_gate_names = {
        "contract": {"domain_contract_verified"},
        "real_reference": {"reference_case_validated"},
        "fault_injection": {"fault_injection_validated"},
        "live_dcc": {"dcc_execution_verified", "render_artifact_verified"},
        "live_model": {"model_identity_verified", "provider_response_verified"},
        "model_skill_conformance": {"doubao_skill_conformance_verified"},
    }.get(evidence_kind, set())
    passed_gate_names = {
        str(gate.get("name") or "")
        for gate in verification_gates
        if gate.get("passed") is True
    }
    missing_gates = sorted(required_gate_names - passed_gate_names)
    if missing_gates:
        errors.append(
            "primary artifact is missing required harness gates: {}".format(
                ",".join(missing_gates)
            )
        )
    declared_artifacts = payload.get("artifacts")
    declared_artifact_kinds: set[str] = set()
    if not isinstance(declared_artifacts, list) or not declared_artifacts:
        errors.append("primary artifact contains no concrete artifact records")
    else:
        entry_paths = set(str(item) for item in entry.get("artifact_paths") or [])
        entry_hashes = entry.get("artifact_sha256") if isinstance(entry.get("artifact_sha256"), dict) else {}
        for record in declared_artifacts:
            if not isinstance(record, dict):
                errors.append("primary artifact contains an invalid artifact record")
                continue
            path_text = str(record.get("path") or "")
            digest = str(record.get("sha256") or "")
            record_kind = str(record.get("kind") or "")
            if not record_kind:
                errors.append("primary artifact record has no kind: {}".format(path_text))
            else:
                declared_artifact_kinds.add(record_kind)
            artifact = _resolve_repo_file(root, path_text)
            if path_text not in entry_paths or digest != str(entry_hashes.get(path_text) or ""):
                errors.append("primary artifact record is not bound by the entry: {}".format(path_text))
            if artifact is None or not artifact.is_file() or artifact.is_symlink() or not SHA256.fullmatch(digest):
                errors.append("primary artifact record is missing or unsafe: {}".format(path_text))
            elif digest != _sha256_file(artifact):
                errors.append("primary artifact record hash mismatch: {}".format(path_text))
    required_artifact_kind = {
        "contract": "contract_report",
        "real_reference": "comparison_preview",
        "fault_injection": "fault_report",
        "live_dcc": "render_output",
        "live_model": "provider_response",
        "model_skill_conformance": "skill_conformance_report",
    }.get(evidence_kind)
    if required_artifact_kind and required_artifact_kind not in declared_artifact_kinds:
        errors.append(
            "primary artifact is missing required output kind: {}".format(
                required_artifact_kind
            )
        )

    if evidence_kind == "contract" and payload.get("contract_available") is not True:
        errors.append("contract harness did not pass the domain contract")
    if evidence_kind in {"real_reference", "fault_injection"} and payload.get("case_validated") is not True:
        errors.append("case harness did not validate the declared case")
    if evidence_kind == "live_dcc":
        for field in ("application", "application_build"):
            if str(payload.get(field) or "") != str(entry.get(field) or ""):
                errors.append("primary artifact {} mismatch".format(field))
        if payload.get("render_validated") is not True:
            errors.append("live DCC harness did not validate a render")
        if str(payload.get("renderer") or "").lower() != str(entry.get("renderer") or "").lower():
            errors.append("live DCC harness renderer mismatch")
        if payload.get("semantic_control_coverage") != entry.get("semantic_control_coverage"):
            errors.append("live DCC semantic-control coverage mismatch")
    if evidence_kind == "live_model":
        for field in ("model_role", "model_name", "provider_response_sha256"):
            if str(payload.get(field) or "") != str(entry.get(field) or ""):
                errors.append("model harness {} mismatch".format(field))
        if payload.get("identity_verified") is not True:
            errors.append("model harness identity is not verified")
    if evidence_kind == "model_skill_conformance":
        for field in (
            "route_id", "ui_control_evidence_id", "ui_control_evidence_identity",
            "suite_id", "suite_version", "suite_sha256", "driver_sha256",
            "conformance_report_sha256",
        ):
            if str(payload.get(field) or "") != str(entry.get(field) or ""):
                errors.append("Doubao conformance harness {} mismatch".format(field))
        report_path = next(
            (str(record.get("path") or "") for record in declared_artifacts or []
             if isinstance(record, dict) and record.get("kind") == "skill_conformance_report"),
            "",
        )
        report = _resolve_repo_file(root, report_path)
        if report is None or not report.is_file():
            errors.append("Doubao conformance report artifact is missing")
        else:
            if _sha256_file(report) != str(payload.get("conformance_report_sha256") or ""):
                errors.append("Doubao conformance report digest mismatch")
            try:
                report_payload = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                errors.append("Doubao conformance report is not valid UTF-8 JSON")
            else:
                bindings = {
                    "evidence_id": "evidence_id",
                    "ui_control_subject_hash": "ui_control_evidence_identity",
                    "suite_id": "suite_id",
                    "suite_version": "suite_version",
                    "suite_sha256": "suite_sha256",
                    "driver_sha256": "driver_sha256",
                }
                for report_field, harness_field in bindings.items():
                    if str(report_payload.get(report_field) or "") != str(payload.get(harness_field) or ""):
                        errors.append("Doubao conformance report {} mismatch".format(report_field))
                errors.extend(_doubao_conformance_report_errors(report_payload))
    return errors


def _git_state(root: Path) -> tuple[str, str]:
    def run(*args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout

    repository_root = root.resolve()
    reported_root = os.fsdecode(run("rev-parse", "--show-toplevel")).strip()
    if not reported_root or Path(reported_root).resolve() != repository_root:
        raise OSError("git repository root does not match evidence source root")
    commit = run("rev-parse", "HEAD").decode("ascii").strip()
    status = run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".", ":(exclude)outputs/live-validation/**")
    diff = run("diff", "--binary", "--", ".", ":(exclude)outputs/live-validation/**")
    staged = run("diff", "--cached", "--binary", "--", ".", ":(exclude)outputs/live-validation/**")
    digest = hashlib.sha256()
    digest.update(status)
    digest.update(b"\0DIFF\0")
    digest.update(diff)
    digest.update(b"\0STAGED\0")
    digest.update(staged)
    for record in status.split(b"\0"):
        if not record.startswith(b"?? "):
            continue
        relative = record[3:].decode("utf-8", errors="surrogateescape")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return "", ""
        unresolved = repository_root / relative_path
        encoded_relative = relative.encode("utf-8", errors="surrogateescape")
        if unresolved.is_symlink():
            try:
                link_target = os.readlink(unresolved)
            except OSError:
                return "", ""
            digest.update(encoded_relative)
            digest.update(b"\0SYMLINK\0")
            digest.update(link_target.encode("utf-8", errors="surrogateescape"))
            continue
        try:
            path = unresolved.resolve()
            path.relative_to(repository_root)
        except ValueError:
            return "", ""
        if not path.is_file():
            return "", ""
        digest.update(encoded_relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return commit, digest.hexdigest()


def _rows(path: Path = SUPPORT_PATH) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match and match.group(1) in PACKS:
            rows[match.group(1)] = match.group(2)
    return rows


def _validated_entries(
    payload: dict[str, Any],
    root: Path,
    contract_hashes: dict[str, str],
    attestation_key: Optional[bytes] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    valid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    entries = payload.get("entries")
    if payload.get("schema_version") != 1 or not isinstance(entries, list):
        return [], ["outputs/live-validation/index.json has an unsupported schema"]
    try:
        current_commit, current_dirty_digest = _git_state(root)
        git_unavailable_reason: Optional[str] = None
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        # Delivery trees carry no .git: HEAD re-verification is deferred and
        # reported as its own item. Every other protection still runs.
        current_commit, current_dirty_digest = "", ""
        git_unavailable_reason = str(exc)
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            errors.append("live-validation entry {} must be an object".format(index))
            continue
        entry_id = str(raw.get("evidence_id") or "").strip()
        label = entry_id or "entry-{}".format(index)
        entry_errors: list[str] = []
        pack = str(raw.get("domain_pack") or "")
        if pack not in PACKS:
            entry_errors.append("unknown domain_pack")
        if not entry_id or entry_id in seen_ids:
            entry_errors.append("missing or duplicate evidence_id")
        if entry_id:
            seen_ids.add(entry_id)
        if raw.get("status") not in {"passed", "failed"}:
            entry_errors.append("status must be passed or failed")
        if raw.get("evidence_kind") not in EVIDENCE_KINDS:
            entry_errors.append("unknown evidence_kind")
        if str(raw.get("pack_version") or "") != "1.0.0":
            entry_errors.append("pack_version must be 1.0.0")
        git_commit = str(raw.get("git_commit") or "")
        dirty_digest = str(raw.get("dirty_diff_digest") or "")
        if not GIT_COMMIT.fullmatch(git_commit) or (git_unavailable_reason is None and git_commit != current_commit):
            entry_errors.append("git_commit mismatch")
        if not SHA256.fullmatch(dirty_digest) or (git_unavailable_reason is None and dirty_digest != current_dirty_digest):
            entry_errors.append("dirty_diff_digest mismatch")
        executed_at = str(raw.get("executed_at") or "")
        try:
            parsed_time = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
            if parsed_time.tzinfo is None:
                raise ValueError("timezone missing")
        except ValueError:
            entry_errors.append("executed_at must be timezone-aware ISO-8601")
        if str(raw.get("probe_level") or "") not in {"contract", "runtime", "render", "end_to_end"}:
            entry_errors.append("probe_level is missing or invalid")
        if not str(raw.get("execution_entrypoint") or "").strip():
            entry_errors.append("execution_entrypoint is required")
        if str(raw.get("domain_contract_sha256") or "") != str(contract_hashes.get(pack) or ""):
            entry_errors.append("domain_contract_sha256 mismatch")
        if str(raw.get("evidence_identity") or "") != evidence_identity(raw):
            entry_errors.append("evidence_identity mismatch")
        if not _attestation_valid(raw, attestation_key):
            entry_errors.append("evidence attestation is missing, invalid, or unavailable")

        source = _resolve_repo_file(root, raw.get("source_path"))
        source_hash = str(raw.get("source_sha256") or "")
        if source is None or not source.is_file() or source.is_symlink():
            entry_errors.append("source_path is missing, unsafe, or not a regular file")
        elif not SHA256.fullmatch(source_hash) or source_hash != _sha256_file(source):
            entry_errors.append("source_sha256 mismatch")

        application = str(raw.get("application") or "")
        expected_addon = (
            root / "plugins" / "nuke" / "nuke_bridge_addon.py"
            if application == "nuke" or pack == "nuke_composite_v1"
            else root / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
        ).resolve()
        expected_catalog = (
            root / "packages" / "dcc-task-runtime" / "src" / "dcc_task_runtime" / "domains.py"
            if pack == "nuke_composite_v1"
            else root / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "domain_packs.py"
        ).resolve()
        addon_source = _resolve_repo_file(root, raw.get("addon_source_path"))
        catalog_source = _resolve_repo_file(root, raw.get("catalog_source_path"))
        if addon_source is None or addon_source != expected_addon or not addon_source.is_file():
            entry_errors.append("addon_source_path mismatch")
        elif str(raw.get("addon_source_sha256") or "") != _sha256_file(addon_source):
            entry_errors.append("addon_source_sha256 mismatch")
        if catalog_source is None or catalog_source != expected_catalog or not catalog_source.is_file():
            entry_errors.append("catalog_source_path mismatch")
        elif str(raw.get("catalog_source_sha256") or "") != _sha256_file(catalog_source):
            entry_errors.append("catalog_source_sha256 mismatch")

        artifacts = raw.get("artifact_paths")
        hashes = raw.get("artifact_sha256")
        if not isinstance(artifacts, list) or not artifacts or not isinstance(hashes, dict):
            entry_errors.append("artifact_paths and artifact_sha256 are required")
        else:
            for item in artifacts:
                artifact = _resolve_repo_file(root, item)
                expected = str(hashes.get(str(item)) or "")
                if artifact is None or not artifact.is_file() or artifact.is_symlink():
                    entry_errors.append("artifact is missing or unsafe: {}".format(item))
                elif not SHA256.fullmatch(expected) or expected != _sha256_file(artifact):
                    entry_errors.append("artifact hash mismatch: {}".format(item))
        entry_errors.extend(_support_harness_errors(raw, root))

        if raw.get("evidence_kind") == "live_dcc":
            build = str(raw.get("application_build") or "")
            if str(raw.get("probe_level") or "") not in {"runtime", "render", "end_to_end"}:
                entry_errors.append("live_dcc evidence requires runtime-or-higher probe_level")
            if application == "houdini":
                if build not in SUPPORTED_HOUDINI_BUILDS:
                    entry_errors.append("unrecognized exact Houdini build")
                if not bool(raw.get("render_validated")) or str(raw.get("renderer") or "").lower() != "karma":
                    entry_errors.append("Houdini live evidence requires a verified Karma render")
            elif application == "nuke":
                if build != REQUIRED_NUKE_BUILD:
                    entry_errors.append("unrecognized exact Nuke build")
            else:
                entry_errors.append("live_dcc application must be houdini or nuke")
        if raw.get("evidence_kind") == "live_model":
            provider_digest = str(raw.get("provider_response_sha256") or "")
            artifact_hashes = raw.get("artifact_sha256") if isinstance(raw.get("artifact_sha256"), dict) else {}
            if raw.get("identity_verified") is not True:
                entry_errors.append("live_model identity_verified must be true")
            if not SHA256.fullmatch(provider_digest) or provider_digest not in {str(value) for value in artifact_hashes.values()}:
                entry_errors.append("provider_response_sha256 must name a hashed artifact")
        if raw.get("evidence_kind") == "model_skill_conformance":
            artifact_hashes = raw.get("artifact_sha256") if isinstance(raw.get("artifact_sha256"), dict) else {}
            report_digest = str(raw.get("conformance_report_sha256") or "")
            if str(raw.get("route_id") or "") != "DoubaoDesktopRoute":
                entry_errors.append("model_skill_conformance requires DoubaoDesktopRoute")
            for field in ("ui_control_evidence_id", "suite_id", "suite_version"):
                if not str(raw.get(field) or "").strip():
                    entry_errors.append("{} is required for model_skill_conformance".format(field))
            for field in ("ui_control_evidence_identity", "suite_sha256", "driver_sha256"):
                if not SHA256.fullmatch(str(raw.get(field) or "")):
                    entry_errors.append("{} must be SHA-256".format(field))
            if not SHA256.fullmatch(report_digest) or report_digest not in {str(value) for value in artifact_hashes.values()}:
                entry_errors.append("conformance_report_sha256 must name a hashed artifact")

        if entry_errors:
            errors.extend("{}: {}".format(label, message) for message in entry_errors)
            continue
        if raw.get("status") == "passed":
            valid.append(dict(raw))
    if git_unavailable_reason is not None:
        errors.append(
            "git_state_unavailable: {} ({} entries deferred HEAD re-verification; "
            "all other entry protections ran)".format(git_unavailable_reason, len(entries))
        )
    return valid, errors


def _passed(entries: Iterable[dict[str, Any]], pack: str, kind: str, **fields: str) -> bool:
    for entry in entries:
        if entry.get("domain_pack") != pack or entry.get("evidence_kind") != kind:
            continue
        if entry.get("status") != "passed":
            continue
        if all(str(entry.get(name) or "") == value for name, value in fields.items()):
            return True
    return False


def _validated_doubao_routes(
    payload: Mapping[str, Any],
    root: Path,
    attestation_key: Optional[bytes],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate global UI-control evidence without pretending it is a domain run."""

    rows = payload.get("model_routes") or []
    if not isinstance(rows, list):
        return [], ["outputs/live-validation index model_routes must be a list"]
    if not rows:
        return [], []
    try:
        current_commit, current_dirty_digest = _git_state(root)
        git_unavailable_reason: Optional[str] = None
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        current_commit, current_dirty_digest = "", ""
        git_unavailable_reason = str(exc)
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append("model route entry {} must be an object".format(index))
            continue
        entry_id = str(raw.get("evidence_id") or "")
        label = entry_id or "model-route-{}".format(index)
        reasons: list[str] = []
        if not entry_id or entry_id in seen:
            reasons.append("missing or duplicate evidence_id")
        seen.add(entry_id)
        if raw.get("status") != "passed":
            reasons.append("model route status must be passed")
        if raw.get("route_id") != "DoubaoDesktopRoute":
            reasons.append("route_id must be DoubaoDesktopRoute")
        if raw.get("bundle_id") != "com.bot.pc.doubao":
            reasons.append("bundle_id mismatch")
        if not str(raw.get("app_version") or "").strip() or not str(raw.get("code_signature") or "").strip():
            reasons.append("Doubao application version/signature is incomplete")
        if not GIT_COMMIT.fullmatch(str(raw.get("git_commit") or "")) or (
            git_unavailable_reason is None and str(raw.get("git_commit") or "") != current_commit
        ):
            reasons.append("git_commit mismatch")
        if not SHA256.fullmatch(str(raw.get("dirty_diff_digest") or "")) or (
            git_unavailable_reason is None and str(raw.get("dirty_diff_digest") or "") != current_dirty_digest
        ):
            reasons.append("dirty_diff_digest mismatch")
        if str(raw.get("evidence_identity") or "") != evidence_identity(raw):
            reasons.append("evidence_identity mismatch")
        if not _attestation_valid(raw, attestation_key):
            reasons.append("evidence attestation is missing, invalid, or unavailable")
        executable = Path(str(raw.get("executable_path") or "")).expanduser()
        if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
            reasons.append("exact Doubao executable is missing or unsafe")
        elif str(raw.get("executable_sha256") or "") != _sha256_file(executable):
            reasons.append("Doubao executable_sha256 mismatch")
        driver = _resolve_repo_file(root, raw.get("driver_source_path"))
        if driver is None or not driver.is_file() or driver.is_symlink():
            reasons.append("driver_source_path is missing or unsafe")
        elif str(raw.get("driver_sha256") or "") != _sha256_file(driver):
            reasons.append("driver_sha256 mismatch")
        # read_cycles/privacy/observations and any outer gate booleans are only
        # caches for presentation.  The hashed atomic event manifest below is
        # the sole source of truth and is always recomputed.
        artifacts = raw.get("artifact_paths")
        hashes = raw.get("artifact_sha256")
        event_digest = str(raw.get("event_manifest_sha256") or "")
        if not isinstance(artifacts, list) or not artifacts or not isinstance(hashes, dict):
            reasons.append("model route artifact manifest is required")
        else:
            for item in artifacts:
                artifact = _resolve_repo_file(root, item)
                digest = str(hashes.get(str(item)) or "")
                if artifact is None or not artifact.is_file() or artifact.is_symlink() or digest != _sha256_file(artifact):
                    reasons.append("model route artifact missing or hash mismatch: {}".format(item))
            if not SHA256.fullmatch(event_digest) or event_digest not in {str(value) for value in hashes.values()}:
                reasons.append("event_manifest_sha256 must name a hashed artifact")
            event_path = next(
                (str(item) for item in artifacts if str(hashes.get(str(item)) or "") == event_digest),
                "",
            )
            event_artifact = _resolve_repo_file(root, event_path)
            if event_artifact is None or not event_artifact.is_file():
                reasons.append("UI event manifest artifact is missing")
            else:
                try:
                    event_payload = json.loads(event_artifact.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError):
                    reasons.append("UI event manifest is not valid UTF-8 JSON")
                else:
                    reasons.extend(_doubao_ui_manifest_errors(event_payload, raw))
        if reasons:
            errors.extend("{}: {}".format(label, reason) for reason in reasons)
        else:
            valid.append(dict(raw))
    if git_unavailable_reason is not None:
        errors.append(
            "git_state_unavailable: {} ({} model routes deferred HEAD re-verification; "
            "all other route protections ran)".format(git_unavailable_reason, len(rows))
        )
    return valid, errors


def _entry_covers_controls(entry: dict[str, Any], controls: set[str]) -> bool:
    coverage = entry.get("semantic_control_coverage")
    if not isinstance(coverage, dict):
        return False
    required_flags = ("addressable", "writable", "readback_verified", "restore_verified")
    return all(
        isinstance(coverage.get(control), dict)
        and all(coverage[control].get(flag) is True for flag in required_flags)
        for control in controls
    )


def _has_control_coverage(
    entries: Iterable[dict[str, Any]],
    pack: str,
    application: str,
    build: str,
    controls: set[str],
) -> bool:
    return any(
        entry.get("domain_pack") == pack
        and entry.get("evidence_kind") == "live_dcc"
        and entry.get("application") == application
        and entry.get("application_build") == build
        and _entry_covers_controls(entry, controls)
        for entry in entries
    )


def _validated_workbuddy_runs(payload: dict[str, Any], root: Path, attestation_key: Optional[bytes]) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate operator-attested current WorkBuddy traces, never summary flags.

    The operator attests the full manifest and separate route/provider witness
    bindings after real acceptance. Synthetic/software receipts cannot promote
    support. Historical Doubao artifacts remain readable through their parser.
    """
    runtime = root / "packages/dcc-task-runtime/src"
    if str(runtime) not in sys.path: sys.path.insert(0, str(runtime))
    from dcc_task_runtime.workbuddy_acceptance import ModelRunManifest, verify_workbuddy_release_gate
    tools_path = str(Path(__file__).resolve().parent)
    if tools_path not in sys.path: sys.path.insert(0, tools_path)
    from readiness_evidence import build_id
    valid, errors = [], []
    rows = payload.get("workbuddy_runs", [])
    if not isinstance(rows, list): return [], ["workbuddy_runs must be a list"]
    seen = set()
    for index, raw in enumerate(rows):
        try:
            if not isinstance(raw, dict): raise ValueError("entry must be object")
            identity = raw.get("evidence_id")
            if not identity or identity in seen: raise ValueError("missing or duplicate evidence_id")
            seen.add(identity)
            if raw.get("schema") != "bridge.workbuddy.release_attestation/1" or raw.get("route_id") != "WorkBuddyDesktopRoute":
                raise ValueError("current route must be WorkBuddyDesktopRoute")
            if raw.get("source") != "real_host" or raw.get("status") != "passed":
                raise ValueError("only real-host evidence can promote support")
            if raw.get("build_id") != build_id(root): raise ValueError("WorkBuddy evidence build mismatch")
            if raw.get("evidence_identity") != evidence_identity(raw) or not _attestation_valid(raw, attestation_key):
                raise ValueError("WorkBuddy operator attestation invalid or unavailable")
            path = _resolve_repo_file(root, raw.get("manifest_path"))
            if path is None or not path.is_file() or _sha256_file(path) != raw.get("manifest_sha256"):
                raise ValueError("WorkBuddy manifest missing or hash mismatch")
            manifest = ModelRunManifest.from_mapping(json.loads(path.read_text(encoding="utf-8")))
            route = manifest.route
            observations = raw.get("witness_bindings", {})
            route_binding = observations.get("route", {})
            provider_binding = observations.get("provider", {})
            route_ok = route_binding == {"session_id":route.session_id,
                "manifest_sha256":manifest.manifest_sha256,"selected_model":"hy3",
                "executable_sha256":route.app.executable_sha256}
            provider = route.provider_evidence
            provider_ok = provider is not None and provider_binding == {
                "session_id":route.session_id,"exchange_id":provider.exchange_id,
                "model":"hy3","witness_sha256":provider.witness_sha256,
                "provider_response_sha256":provider.provider_response_sha256}
            result = verify_workbuddy_release_gate(manifest,
                route_witness_verifier=lambda _r,_m: route_ok,
                provider_witness_verifier=lambda _r,_m: provider_ok)
            if not result["release_passed"]:
                raise ValueError("WorkBuddy route, provider identity or 48-case behavior not verified")
            valid.append({**raw, "evaluation":result})
        except Exception as exc:
            errors.append("workbuddy-run-{}: {}".format(index, exc))
    return valid, errors


def violations(root: Path | str = ROOT) -> list[str]:
    unresolved_root = Path(root).absolute()
    if unresolved_root.is_symlink():
        return ["repository root must not be a symlink"]
    root = unresolved_root.resolve()
    support_path = root / "docs" / "domain-support.md"
    evidence_path = _resolve_repo_file(root, "outputs/live-validation/index.json")
    errors: list[str] = []
    rows = _rows(support_path)
    if set(rows) != PACKS:
        missing = sorted(PACKS - set(rows))
        extra = sorted(set(rows) - PACKS)
        errors.append(f"domain-support table mismatch; missing={missing}, extra={extra}")
    for pack, status in rows.items():
        if status not in MATURITY:
            errors.append(f"{pack}: unknown maturity {status}")

    try:
        if evidence_path is None or not evidence_path.is_file():
            raise OSError("evidence index is missing, unsafe, or traverses a symlink")
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return errors + ["could not read live-validation index: {}".format(exc)]
    try:
        contract_hashes, legacy_claims, required_controls, semantic_drift = _domain_contract_hashes(root)
    except Exception as exc:
        return errors + ["could not calculate current domain contracts: {}".format(exc)]
    if legacy_claims:
        errors.append("static validated_houdini_versions/karma claims are forbidden: {}".format(sorted(legacy_claims)))
    errors.extend(semantic_drift)
    attestation_key = _load_evidence_attestation_key() if (payload.get("entries") or payload.get("model_routes") or payload.get("workbuddy_runs")) else None
    domain_payload = {**payload, "entries": [
        entry for entry in payload.get("entries") or []
        if not isinstance(entry, dict) or entry.get("evidence_kind") != "model_route_ui_control"
    ]}
    entries, entry_errors = _validated_entries(
        domain_payload,
        root,
        contract_hashes,
        attestation_key,
    )
    errors.extend(entry_errors)
    doubao_routes, route_errors = _validated_doubao_routes(payload, root, attestation_key)
    errors.extend(route_errors)
    workbuddy_runs, workbuddy_errors = _validated_workbuddy_runs(payload, root, attestation_key)
    errors.extend(workbuddy_errors)

    for pack, status in rows.items():
        if status in {"contract-tested", "live-validated", "supported"} and not _passed(entries, pack, "contract"):
            errors.append(f"{pack}: {status} requires a passing contract evidence entry")
        if status in {"live-validated", "supported"}:
            for kind in ("real_reference", "fault_injection"):
                if not _passed(entries, pack, kind):
                    errors.append(f"{pack}: {status} requires passing {kind} evidence")
            if pack != "nuke_composite_v1":
                for build in REQUIRED_HOUDINI_BUILDS:
                    if not _passed(entries, pack, "live_dcc", application="houdini", application_build=build):
                        errors.append(f"{pack}: {status} requires live Houdini {build} evidence")
            if pack in {"nuke_composite_v1", "explosion_composite_v1"}:
                if not _passed(entries, pack, "live_dcc", application="nuke", application_build=REQUIRED_NUKE_BUILD):
                    errors.append(f"{pack}: {status} requires live Nuke {REQUIRED_NUKE_BUILD} evidence")
        if status == "supported":
            if not workbuddy_runs:
                errors.append(f"{pack}: supported requires current operator-attested WorkBuddyDesktopRoute/HY3 provider and 48-case evidence")
            for application, controls in sorted(required_controls.get(pack, {}).items()):
                builds = REQUIRED_HOUDINI_BUILDS if application == "houdini" else (REQUIRED_NUKE_BUILD,)
                for build in builds:
                    if controls and not _has_control_coverage(entries, pack, application, build, controls):
                        errors.append(
                            "{}: supported requires full {} semantic-control readback/restore coverage on {}".format(
                                pack, application, build
                            )
                        )
    return errors


def main() -> int:
    errors = violations()
    git_only = [item for item in errors if item.startswith("git_state_unavailable")]
    others = [item for item in errors if not item.startswith("git_state_unavailable")]
    if others:
        print("FAIL: unsupported maturity claims")
        print("\n".join(f"- {item}" for item in others))
        return 1
    if git_only:
        # Release/delivery identity: no .git tree defers HEAD re-verification.
        # This is reported explicitly and nothing else may be wrong.
        if len(git_only) != 1:
            print("FAIL: git_state_unavailable must be a single labelled item")
            return 1
        print("PASS (release tree: HEAD re-verification deferred; all other protections ran)")
        print("\n".join(f"- {item}" for item in git_only))
        return 0
    print("PASS: domain support claims match machine-readable evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
