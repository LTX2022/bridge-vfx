#!/usr/bin/env python3
"""Run the Nuke 17 freshness and reference-lineage acceptance over TCP.

This is an operator-only validation harness.  It creates an isolated graph in
the selected Nuke instance, renders tiny deterministic EXRs, injects one stale
preview, saves/reopens the NK, and writes machine-readable evidence.  It does
not promote any domain support state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "nuke-bridge" / "src"))

from nuke_bridge.client import NukeClient  # noqa: E402


def _validated_evidence_output_path(value: str, label: str) -> Path:
    """Resolve evidence destinations without letting them dirty measured source."""

    repository = ROOT.resolve()
    lexical = Path(os.path.abspath(str(Path(value).expanduser())))
    try:
        lexical_relative = lexical.relative_to(repository)
    except ValueError:
        lexical_relative = None
    if lexical_relative is not None:
        current = repository
        for component in lexical_relative.parts:
            current = current / component
            if current.is_symlink():
                raise ValueError(f"{label} must not traverse a repository symlink")
    resolved = lexical.resolve()
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        if lexical_relative is not None:
            raise ValueError(f"{label} escapes the repository through a symlink")
        return resolved
    if lexical_relative is None:
        raise ValueError(f"{label} reaches the repository through an indirect path")
    if relative.parts[:2] != ("outputs", "live-validation"):
        raise ValueError(
            f"{label} inside the repository is allowed only under outputs/live-validation"
        )
    return resolved


def validated_output_directory(value: str) -> Path:
    return _validated_evidence_output_path(value, "output directory")


def validated_json_output_path(value: str) -> Path:
    return _validated_evidence_output_path(value, "JSON output path")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_identity() -> dict[str, str]:
    def run(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout

    pathspec = ("--", ".", ":(exclude)outputs/live-validation/**")
    status = run("status", "--porcelain=v1", "-z", "--untracked-files=all", *pathspec)
    diff = run("diff", "--binary", *pathspec)
    staged = run("diff", "--cached", "--binary", *pathspec)
    digest = hashlib.sha256(status + b"\0DIFF\0" + diff + b"\0STAGED\0" + staged)
    repository_root = ROOT.resolve()
    for record in status.split(b"\0"):
        if not record.startswith(b"?? "):
            continue
        relative = record[3:].decode("utf-8", errors="surrogateescape")
        candidate = repository_root / relative
        try:
            candidate.relative_to(repository_root)
        except ValueError:
            continue
        if candidate.is_symlink():
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0SYMLINK\0")
            digest.update(os.readlink(candidate).encode("utf-8", errors="surrogateescape"))
            continue
        candidate = candidate.resolve()
        try:
            candidate.relative_to(repository_root)
        except ValueError:
            continue
        if candidate.is_file():
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            digest.update(hashlib.sha256(candidate.read_bytes()).digest())
    return {
        "git_commit": run("rev-parse", "HEAD").decode("utf-8").strip(),
        "dirty_diff_digest": digest.hexdigest(),
    }


def _source_identity() -> dict[str, str]:
    return {
        **_git_identity(),
        "source_sha256": _sha256(Path(__file__).resolve()),
        "addon_source_sha256": _sha256(ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"),
        "catalog_source_sha256": _sha256(
            ROOT / "packages" / "dcc-task-runtime" / "src" / "dcc_task_runtime" / "domains.py"
        ),
    }


def _gate(result: dict[str, Any], name: str) -> dict[str, Any]:
    for gate in result.get("gates") or []:
        if gate.get("name") == name:
            return dict(gate)
    raise RuntimeError("missing gate {} in {}".format(name, result.get("gates")))


def _require(result: dict[str, Any], name: str, passed: bool = True) -> dict[str, Any]:
    gate = _gate(result, name)
    if bool(gate.get("passed")) is not passed:
        raise RuntimeError("gate {} expected passed={} but got {}".format(name, passed, gate))
    return gate


def _require_build_evidence(result: dict[str, Any]) -> None:
    """Require every independent build invariant used by the strict policy."""

    _require(result, "editable_native_composite_graph")
    _require(result, "composite_topology_intact")
    _require(result, "reference_isolated_from_final_write")


def _setup_sources(client: NukeClient, directory: Path, token: str) -> dict[str, Any]:
    effect_path = directory / "effect.0001.exr"
    reference_path = directory / "reference.0001.exr"
    code = """
validation_format = nuke.addFormat({format_spec})
effect = nuke.nodes.Constant(name={effect_name})
effect["color"].setValue([0.18, 0.42, 0.85, 1.0])
effect["format"].setValue(validation_format.name())
effect_write = nuke.nodes.Write(name={effect_write_name}, inputs=[effect])
effect_write["file"].setValue({effect_path})
effect_write["file_type"].setValue("exr")
nuke.execute(effect_write, 1, 1)
reference = nuke.nodes.Constant(name={reference_name})
reference["color"].setValue([0.72, 0.16, 0.08, 1.0])
reference["format"].setValue(validation_format.name())
reference_write = nuke.nodes.Write(name={reference_write_name}, inputs=[reference])
reference_write["file"].setValue({reference_path})
reference_write["file_type"].setValue("exr")
nuke.execute(reference_write, 1, 1)
result = {{"effect": {effect_path}, "reference": {reference_path}}}
""".format(
        format_spec=json.dumps("64 64 0 0 64 64 1 bridge_live_" + token),
        effect_name=json.dumps("BRIDGE_LIVE_EFFECT_" + token),
        effect_write_name=json.dumps("BRIDGE_LIVE_EFFECT_WRITE_" + token),
        effect_path=json.dumps(str(effect_path)),
        reference_name=json.dumps("BRIDGE_LIVE_REFERENCE_" + token),
        reference_write_name=json.dumps("BRIDGE_LIVE_REFERENCE_WRITE_" + token),
        reference_path=json.dumps(str(reference_path)),
    )
    setup = client.call("nuke_run", {"code": code})
    if not effect_path.is_file() or not reference_path.is_file():
        raise RuntimeError("Nuke did not create the isolated validation inputs")
    return {
        "result": setup,
        "effect_path": str(effect_path),
        "reference_path": str(reference_path),
        "effect_sha256": _sha256(effect_path),
        "reference_sha256": _sha256(reference_path),
    }


def run(port: int, output_dir: Path) -> dict[str, Any]:
    output_dir = validated_output_directory(str(output_dir))
    source_identity_before = _source_identity()
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    client = NukeClient(port, timeout_seconds=120.0)
    health = client.health()
    if str(health.get("nuke_version") or "") != "17.0v1":
        raise RuntimeError("this acceptance requires Nuke 17.0v1")
    capabilities = client.call("capabilities.get")
    expected_addon_path = ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py"
    expected_addon_sha256 = _sha256(expected_addon_path)
    loaded_addon_path = str(capabilities.get("loaded_addon_path") or "")
    loaded_addon_sha256 = str(capabilities.get("loaded_addon_sha256") or "")
    if not loaded_addon_path or loaded_addon_sha256 != expected_addon_sha256:
        raise RuntimeError(
            "the live Nuke instance is not running the current repository addon: "
            "loaded_path={} loaded_sha256={} expected_sha256={}".format(
                loaded_addon_path,
                loaded_addon_sha256,
                expected_addon_sha256,
            )
        )

    token = uuid4().hex[:12]
    task_id = "bridge-nuke-live-" + token
    sources = _setup_sources(client, output_dir, token)
    params: dict[str, Any] = {
        "task_id": task_id,
        "schema_version": "2.0",
        "inputs": [
            {
                "role": "effect_render",
                "path": sources["effect_path"],
                "sha256": sources["effect_sha256"],
            },
            {
                "role": "reference",
                "path": sources["reference_path"],
                "sha256": sources["reference_sha256"],
            },
        ],
        "constraints": {"composite_controls": {}},
        "render": {
            "output_dir": str(output_dir / "composite"),
            "frame_range": {"start": 1, "end": 1, "step": 1},
        },
        "step_params": {},
    }
    results: dict[str, Any] = {"capabilities": capabilities}
    for key, command in (
        ("probe", "agent.nuke.composite.probe"),
        ("inspect", "agent.nuke.composite.inspect_inputs"),
        ("build", "agent.nuke.composite.build_graph"),
    ):
        results[key] = client.call(command, params)
    _require(results["probe"], "nuke_composite_available")
    _require(results["inspect"], "composite_inputs_exist")
    _require_build_evidence(results["build"])
    if results["build"].get("restored") is not False:
        raise RuntimeError("fresh live task unexpectedly reused a composite registry entry")

    patch_params = dict(params)
    patch_params["step_params"] = {"patch": {"controls": {"blur_size": 1.5}}}
    results["patch"] = client.call("agent.nuke.composite.apply_patch", patch_params)
    _require(results["patch"], "composite_patch_applied")
    _require(results["patch"], "reference_isolated_from_final_write")

    preview_params = dict(params)
    preview_params["step_params"] = {"frame": 1, "variant_id": "live"}
    results["preview_render_initial"] = client.call("agent.nuke.composite.render_preview", preview_params)
    _require(results["preview_render_initial"], "composite_preview_rendered")
    results["preview_verify_initial"] = client.call("agent.nuke.composite.verify_preview", params)
    _require(results["preview_verify_initial"], "composite_preview_artifact")

    results["preview_render_for_stale"] = client.call("agent.nuke.composite.render_preview", preview_params)
    _require(results["preview_render_for_stale"], "composite_preview_rendered")
    old = (results["preview_render_for_stale"].get("before") or {}).get("1") or {}
    preview_path = Path(str(results["preview_render_for_stale"]["output_pattern"]) % 1)
    old_ns = int(old.get("modified_ns") or 0)
    if old_ns <= 0:
        raise RuntimeError("the stale injection requires an existing pre-render preview")
    os.utime(preview_path, ns=(old_ns, old_ns))
    results["preview_verify_stale"] = client.call("agent.nuke.composite.verify_preview", params)
    stale_gate = _require(results["preview_verify_stale"], "composite_preview_artifact", passed=False)
    if stale_gate.get("stale_frames") != [1]:
        raise RuntimeError("stale preview did not report frame 1")

    results["preview_render_fresh"] = client.call("agent.nuke.composite.render_preview", preview_params)
    _require(results["preview_render_fresh"], "composite_preview_rendered")
    results["preview_verify_fresh"] = client.call("agent.nuke.composite.verify_preview", params)
    _require(results["preview_verify_fresh"], "composite_preview_artifact")

    final_params = dict(params)
    final_params["step_params"] = {"frame": 1}
    results["final_render"] = client.call("agent.nuke.composite.render_final", final_params)
    _require(results["final_render"], "composite_final_rendered")
    results["final_verify"] = client.call("agent.nuke.composite.verify_final", params)
    _require(results["final_verify"], "reference_isolated_from_final_write")
    _require(results["final_verify"], "composite_final_artifacts")

    results["deliver"] = client.call("agent.nuke.composite.deliver", params)
    _require(results["deliver"], "reference_isolated_from_final_write")
    delivery_gate = _require(results["deliver"], "editable_composite_script")
    script_path = Path(str(delivery_gate["script"]))
    script_hash = _sha256(script_path)
    results["reopen"] = client.call("open_script", {"path": str(script_path), "sha256": script_hash})
    registry_entries = results["reopen"].get("registry_entries") or {}
    registry_before = registry_entries.get("before") or {}
    registry_after = registry_entries.get("after") or {}
    if not results["reopen"].get("registry_cache_invalidated"):
        raise RuntimeError("open_script did not attest registry invalidation")
    if int(registry_before.get("composites") or 0) < 1:
        raise RuntimeError("live reopen did not begin with a populated composite registry")
    if any(int(registry_after.get(name) or 0) != 0 for name in ("composites", "deliveries", "renders")):
        raise RuntimeError("open_script retained script-bound registry entries: {}".format(registry_after))

    # Re-run build only to force a cache miss and hidden-state recovery.  It
    # must not create or trust a new graph from request parameters.
    results["build_after_reopen"] = client.call("agent.nuke.composite.build_graph", params)
    _require_build_evidence(results["build_after_reopen"])
    if results["build_after_reopen"].get("restored") is not True:
        raise RuntimeError("composite graph was not restored from hidden NK state after reopen")
    expected_state = dict(results["deliver"].get("delivery") or {})
    restored_state = dict(results["build_after_reopen"].get("graph") or {})
    persisted_fields = (
        "output_dir",
        "final_pattern",
        "frame_range",
        "final_range",
        "expected_frame_stride",
        "input_source_paths",
        "input_source_bindings",
        "input_source_identities",
        "input_identity_policy",
        "reference_source_paths",
        "reference_source_bindings",
        "final_write_binding",
        "final_verification",
    )
    mismatched_fields = [
        field for field in persisted_fields
        if restored_state.get(field) != expected_state.get(field)
    ]
    if mismatched_fields:
        raise RuntimeError(
            "hidden composite state changed across reopen: {}".format(
                ", ".join(mismatched_fields)
            )
        )
    reference_binding = dict(
        (restored_state.get("reference_source_bindings") or {}).get("reference") or {}
    )
    if (
        reference_binding.get("frozen_path") != sources["reference_path"]
        or reference_binding.get("readback_path") != sources["reference_path"]
    ):
        raise RuntimeError(
            "restored reference binding does not match the frozen live input: {}".format(
                reference_binding
            )
        )
    restored_topology = _require(
        results["build_after_reopen"],
        "composite_topology_intact",
    )
    expected_live_sources = {
        "effect_render": sources["effect_path"],
        "reference": sources["reference_path"],
    }
    for role, expected_path in expected_live_sources.items():
        binding = dict((restored_topology.get("input_bindings") or {}).get(role) or {})
        identity = dict(binding.get("identity") or {})
        if (
            binding.get("actual_readback") != expected_path
            or not binding.get("matched")
            or identity.get("status") != "frozen"
            or not identity.get("matched")
        ):
            raise RuntimeError(
                "restored {} input is not bound to its frozen live source: {}".format(
                    role,
                    binding,
                )
            )
    final_write_binding = dict(restored_topology.get("final_write_binding") or {})
    if (
        final_write_binding.get("phase") != "final"
        or final_write_binding.get("actual_readback") != restored_state.get("final_pattern")
        or not final_write_binding.get("matched")
    ):
        raise RuntimeError(
            "restored final Write is not bound to final_pattern: {}".format(
                final_write_binding
            )
        )
    results["registry_restore_validation"] = {
        "fresh_build_registry_miss": True,
        "reopen_registry_miss": True,
        "persisted_fields": list(persisted_fields),
        "reference_readback": reference_binding.get("readback_path"),
        "input_readbacks": {
            role: (restored_topology.get("input_bindings") or {}).get(role, {}).get("actual_readback")
            for role in sorted(expected_live_sources)
        },
        "final_write_readback": final_write_binding.get("actual_readback"),
    }
    results["lineage_after_reopen"] = client.call("agent.nuke.composite.audit_lineage", params)
    lineage = _require(results["lineage_after_reopen"], "reference_isolated_from_final_write")
    if lineage.get("violations"):
        raise RuntimeError("reference lineage changed after NK reopen")

    artifact_paths = [
        Path(sources["effect_path"]),
        Path(sources["reference_path"]),
        Path(str((results["preview_verify_fresh"].get("artifacts") or [{}])[0].get("path") or "")),
        Path(str((results["final_verify"].get("artifacts") or [{}])[0].get("path") or "")),
        script_path,
    ]
    artifacts = [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "is_symlink": path.is_symlink(),
        }
        for path in artifact_paths
        if str(path) and path.is_file()
    ]
    source_identity_after = _source_identity()
    source_identity_stable = bool(
        all(source_identity_before.values())
        and source_identity_before == source_identity_after
    )
    payload = {
        "schema_version": 1,
        "status": "passed" if source_identity_stable else "failed",
        "support_promotion": False,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "execution_entrypoint": "tools/validate_nuke_live.py",
        "execution_command": list(sys.argv),
        "probe_level": "end_to_end",
        "application": "nuke",
        "application_build": str(health["nuke_version"]),
        "bridge_port": port,
        "bridge_pid": health.get("pid"),
        "loaded_addon_path": loaded_addon_path,
        "loaded_addon_sha256": loaded_addon_sha256,
        "task_id": task_id,
        "source_path": "tools/validate_nuke_live.py",
        "source_sha256": source_identity_before["source_sha256"],
        "addon_source_path": "plugins/nuke/nuke_bridge_addon.py",
        "addon_source_sha256": source_identity_before["addon_source_sha256"],
        "catalog_source_path": "packages/dcc-task-runtime/src/dcc_task_runtime/domains.py",
        "catalog_source_sha256": source_identity_before["catalog_source_sha256"],
        "git_commit": source_identity_before["git_commit"],
        "dirty_diff_digest": source_identity_before["dirty_diff_digest"],
        "source_identity_before": source_identity_before,
        "source_identity_after": source_identity_after,
        "source_identity_stable": source_identity_stable,
        "artifacts": artifacts,
        "inputs": sources,
        "nk_path": str(script_path),
        "nk_sha256": script_hash,
        "results": results,
    }
    identity_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload["evidence_identity"] = hashlib.sha256(identity_payload).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int, help="fresh/reloaded Nuke Bridge port")
    parser.add_argument("--output-dir", required=True, help="isolated output directory")
    parser.add_argument("--json", required=True, dest="json_path", help="evidence JSON path")
    args = parser.parse_args()
    try:
        output_dir = validated_output_directory(args.output_dir)
        json_path = validated_json_output_path(args.json_path)
    except ValueError as exc:
        print("invalid evidence output path: {}".format(exc), file=sys.stderr)
        return 2
    evidence = run(args.port, output_dir)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = json_path.with_suffix(json_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(json_path)
    print(json.dumps({"status": evidence["status"], "application_build": evidence["application_build"], "json": str(json_path)}, ensure_ascii=False))
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
