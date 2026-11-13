#!/usr/bin/env python3
"""Probe every Houdini FX domain pack against a real Houdini build.

Run it with ``hython`` so the probe executes inside Houdini rather than against
a mocked module::

    /Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/\\
        Versions/21.0/Resources/bin/hython tools/probe_domain_packs.py
    /Applications/Houdini/Houdini22.0.368/Frameworks/Houdini.framework/\\
        Versions/22.0/Resources/bin/hython tools/probe_domain_packs.py

``--level contract`` performs the cheap node-type/template check.
``--level runtime`` additionally creates a disposable graph, verifies every
public control with snapshot/set/readback/restore, and cooks its nodes.  Neither
level renders or promotes support; the JSON is only one hashed input to a later
end-to-end evidence entry.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
CATALOG_PATH = ROOT / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "domain_packs.py"


def validated_json_output_path(value: str) -> Path:
    """Keep evidence writes out of the measured checkout except its excluded index tree."""

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
                raise ValueError("JSON output path must not traverse a repository symlink")
    resolved = lexical.resolve()
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        if lexical_relative is not None:
            raise ValueError("JSON output path escapes the repository through a symlink")
        return resolved
    if lexical_relative is None:
        raise ValueError("JSON output path reaches the repository through an indirect path")
    if relative.parts[:2] != ("outputs", "live-validation"):
        raise ValueError(
            "JSON output inside the repository is allowed only under outputs/live-validation"
        )
    return resolved


def git_state() -> tuple[str, str]:
    def run(*args: str) -> bytes:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return completed.stdout

    try:
        commit = run("rev-parse", "HEAD").decode("ascii").strip()
        status = run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".", ":(exclude)outputs/live-validation/**")
        diff = run("diff", "--binary", "--", ".", ":(exclude)outputs/live-validation/**")
        staged = run("diff", "--cached", "--binary", "--", ".", ":(exclude)outputs/live-validation/**")
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return "", ""
    digest = hashlib.sha256()
    digest.update(status)
    digest.update(b"\0DIFF\0")
    digest.update(diff)
    digest.update(b"\0STAGED\0")
    digest.update(staged)
    # Git diff does not include untracked bytes.  Bind every untracked regular
    # file named by status so an evidence run cannot hide source changes there.
    repository_root = ROOT.resolve()
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


def load_addon():
    spec = importlib.util.spec_from_file_location("_probe_domain_packs_addon", ADDON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Houdini add-on")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_identity() -> dict[str, str]:
    commit, dirty_digest = git_state()
    return {
        "git_commit": commit,
        "dirty_diff_digest": dirty_digest,
        "source_sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        "addon_source_sha256": hashlib.sha256(ADDON_PATH.read_bytes()).hexdigest(),
        "catalog_source_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
    }


def probe_all(addon, level: str = "contract") -> dict[str, dict]:
    results = {}
    for pack_id, pack in sorted(addon._FX_PACKS.items()):
        probe = addon._fx_probe_pack(pack_id, pack)
        runtime = addon._fx_runtime_probe_pack(pack_id, pack) if level == "runtime" else None
        nodes = probe["nodes"]
        controls = probe["control_probes"]
        results[pack_id] = {
            "state": runtime["runtime_probe_state"] if runtime is not None else probe["probe_state"],
            "probe_level": level,
            "node_contract_available": probe["node_contract_available"],
            "semantic_control_contract_available": probe["semantic_control_contract_available"],
            "contract_available": probe["contract_available"],
            "nodes_available": sum(1 for node in nodes if node["available"]),
            "nodes_total": len(nodes),
            "controls_available": sum(1 for control in controls if control["available"]),
            "controls_total": len(controls),
            "missing_node_roles": [str(node["role"]) for node in nodes if not node["available"]],
            "missing_node_types": ["/".join(node["requested_types"]) for node in nodes if node["resolved_type"] is None],
            "missing_parameter_roles": [str(node["role"]) for node in nodes if node["resolved_type"] is not None and not node["available"]],
            "missing_semantic_controls": [str(control["name"]) for control in controls if control["application"] == "houdini" and not control["available"]],
            # Pass the catalog key explicitly.  Relying on the optional ``id``
            # field made a future catalog migration silently turn every
            # evidence-backed flag false when that redundant field was absent.
            "validation_flags": addon._fx_validation_flags(pack, pack_id=pack_id),
            "source_sha256": probe["source_sha256"],
            "domain_contract_sha256": probe["domain_contract_sha256"],
            "contract_probe_identity": probe["probe_identity"],
            "runtime_probe": runtime,
        }
    return results


def probe_resolver_targets(addon) -> dict[str, object]:
    """Exercise representative scalar-component and tuple addresses in HOM.

    Domain controls already exercise the shared resolver, but their current
    catalog only happens to reach ``radx`` and ``base_color``.  Keep this small
    runtime smoke probe so the other common component spelling, ``sizex``,
    cannot regress back to template-name-only detection unnoticed.
    """

    import hou

    obj = hou.node("/obj")
    material_parent = hou.node("/mat")
    if obj is None or material_parent is None:
        return {
            "all_verified": False,
            "results": [],
            "failure_reasons": ["required_parent_network_missing"],
        }
    suffix = uuid4().hex[:12]
    root = obj.createNode("geo", "BRIDGE_RESOLVER_PROBE_{}".format(suffix))
    created = [root]
    results: list[dict[str, object]] = []
    failures: list[str] = []
    specifications = (
        (root, "sphere", "radx", 1.25),
        (root, "grid", "sizex", 1.25),
        (material_parent, "mtlxstandard_surface", "base_color", (0.23, 0.41, 0.67)),
    )
    try:
        for parent, node_type, alias, requested in specifications:
            item: dict[str, object] = {
                "node_type": node_type,
                "alias": alias,
                "addressable": False,
                "writable": False,
                "readback_verified": False,
                "restore_verified": False,
            }
            try:
                node = parent.createNode(node_type, "resolver_{}_{}".format(alias, suffix))
                created.append(node)
                target = addon._resolve_parm_target(node, [alias])
                if target is None:
                    item["error_code"] = "UNSUPPORTED_PARAMETER"
                    failures.append("{}:UNSUPPORTED_PARAMETER".format(alias))
                else:
                    item["addressable"] = True
                    verification = addon._set_parm_verified(target, requested, restore=True)
                    item.update(
                        {
                            "writable": True,
                            "readback_verified": True,
                            "restore_verified": True,
                            **verification,
                        }
                    )
            except Exception as exc:
                code = str(getattr(exc, "code", "PARAMETER_PROBE_FAILED"))
                item["error_code"] = code
                item["error"] = str(exc)
                failures.append("{}:{}".format(alias, code))
            results.append(item)
    finally:
        for node in reversed(created[1:]):
            try:
                if node is not None and node.isValid():
                    node.destroy()
            except Exception:
                pass
        try:
            if root.isValid():
                root.destroy()
        except Exception:
            pass
    return {
        "all_verified": not failures,
        "results": results,
        "failure_reasons": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", help="write machine-readable results here")
    parser.add_argument("--level", choices=("contract", "runtime"), default="contract")
    args = parser.parse_args()

    try:
        json_output_path = validated_json_output_path(args.json_path) if args.json_path else None
    except ValueError as exc:
        print("invalid JSON output path: {}".format(exc), file=sys.stderr)
        return 2

    source_identity_before = source_identity() if args.json_path else None
    addon = load_addon()
    try:
        import hou

        version = hou.applicationVersionString()
    except Exception:  # pragma: no cover - the probe needs a real Houdini
        print("this probe must run inside Houdini (use hython)", file=sys.stderr)
        return 2

    results = probe_all(addon, level=args.level)
    resolver_targets = probe_resolver_targets(addon) if args.level == "runtime" else None
    print("HOUDINI", version)
    print()
    header = f"{'pack':<30} {'nodes':<8} {'controls':<10} {'state':<13} missing"
    print(header)
    print("-" * len(header))
    for pack_id, row in results.items():
        missing = list(row["missing_node_roles"])
        if row["missing_semantic_controls"]:
            missing.append("controls=" + ",".join(row["missing_semantic_controls"]))
        print(
            f"{pack_id:<30} "
            f"{row['nodes_available']}/{row['nodes_total']:<6} "
            f"{row['controls_available']}/{row['controls_total']:<8} "
            f"{row['state']:<13} "
            f"{';'.join(missing) or '-'}"
        )
    counts: dict[str, int] = {}
    for row in results.values():
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    print()
    print("summary:", ", ".join(f"{state}={count}" for state, count in sorted(counts.items())))
    if resolver_targets is not None:
        print(
            "resolver targets:",
            ", ".join(
                "{}={}".format(item["alias"], "PASS" if item.get("restore_verified") else "FAIL")
                for item in resolver_targets["results"]
            ),
        )

    if args.json_path:
        source_identity_after = source_identity()
        source_identity_stable = bool(
            source_identity_before
            and all(source_identity_before.values())
            and source_identity_before == source_identity_after
        )
        payload = {
            "schema": "houdini.domain_pack_probe/2.0",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "execution_entrypoint": "tools/probe_domain_packs.py --level {}".format(args.level),
            "probe_level": args.level,
            "git_commit": source_identity_before["git_commit"],
            "dirty_diff_digest": source_identity_before["dirty_diff_digest"],
            "houdini_build": version,
            "source_path": "tools/probe_domain_packs.py",
            "source_sha256": source_identity_before["source_sha256"],
            "addon_source_path": "plugins/houdini/_impl/houdini_bridge_addon.py",
            "addon_source_sha256": source_identity_before["addon_source_sha256"],
            "catalog_source_path": "packages/houdini-bridge/src/houdini_bridge/domain_packs.py",
            "catalog_source_sha256": source_identity_before["catalog_source_sha256"],
            "source_identity_before": source_identity_before,
            "source_identity_after": source_identity_after,
            "source_identity_stable": source_identity_stable,
            # This catalog/probing dump is diagnostic input only.  It is not a
            # per-pack support harness artifact and must never be indexed as a
            # promotion record by itself.
            "support_promotion": False,
            "resolver_target_probes": resolver_targets,
            "packs": results,
        }
        identity_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload["evidence_identity"] = hashlib.sha256(identity_payload).hexdigest()
        path = json_output_path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        print("wrote", path, hashlib.sha256(path.read_bytes()).hexdigest())
    resolver_failed = args.level == "runtime" and not bool(
        isinstance(resolver_targets, dict) and resolver_targets.get("all_verified") is True
    )
    identity_failed = bool(args.json_path and not source_identity_stable)
    if resolver_failed:
        print("resolver target probe failed", file=sys.stderr)
    if identity_failed:
        print("source identity changed during probe", file=sys.stderr)
    return 1 if resolver_failed or identity_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
