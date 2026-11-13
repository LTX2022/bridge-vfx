#!/usr/bin/env python3
"""Record which node types a real Houdini build actually exposes.

Run it with ``hython``::

    /Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/\\
        Versions/21.0/Resources/bin/hython tools/scan_node_types.py

This is input for the domain-graph rebuild, not validation evidence.  It
answers only "does ``hou.nodeType`` resolve this name in some context", which
is known to be incomplete: some DOP solver types only resolve inside a
specific parent.  Anything reported MISSING here must be re-checked by
creating the node in a real parent before being treated as absent.
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
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
CATALOG_PATH = ROOT / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "domain_packs.py"

CONTEXTS = {
    "sop": "Sop",
    "obj": "Object",
    "dop": "Dop",
    "lop": "Lop",
    "vop": "Vop",
    "top": "Top",
}

NAMES = """
pyrosource pyrosource::2.0 volume vdb vdbfromparticlefluids vdbfromparticles convertvdb
dopnet dopimport dopimportfields dopimportrecords dopio dopfieldrecord
smokeobject pyrosolver pyrosolver::2.0 sourcevolume gasresizefluiddynamic volumesource
popnet popobject popsolver popsource popsteercohesion popsteerseparate popsteeralign
popsteerseek popsteerwander popsteeravoid popforce popdrag popwind popvop popkill
popreplicate popattract popaxisforce poplifedeath popcollide popcollision
popcollisionbehavior popmetaball popturbulence
vellumconstraints vellumsolver vellumobject vellumpack
rbdbulletsolver rbdmaterialfracture rbdconfigure constraintnetwork
constraintproperties constraintproperty rbdconstraintproperties
crowdsource crowdobject crowdsolver agent agentclip agentlayer
crowdstate crowdtransition motionpath crowdpath
flipsolver flipobject flipconfigure flipcollide flipsourcevolume particlefluidsurface
oceanspectrum oceanevaluate oceanfoam oceansample
hairgen guidegroom guideskin fur
mtlxstandard_surface mtlxhair mtlximage materiallibrary assignmaterial
sopimport karmarendersettings karmaresolveprimvars usdrender_rop usd_rop camera domelight
copytopoints scatter attribrandomize attribfrommap
""".split()


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


def context_categories(hou_module) -> dict[str, object]:
    available = hou_module.nodeTypeCategories()
    resolved: dict[str, object] = {}
    for short, key in CONTEXTS.items():
        factory = getattr(hou_module, "{}NodeTypeCategory".format(short), None)
        try:
            category = factory() if factory is not None else None
        except Exception:
            category = None
        if category is None:
            category = available.get(key)
        if category is not None:
            resolved[short] = category
    return resolved


def git_state() -> tuple[str, str]:
    def run(*args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout

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


def source_identity() -> dict[str, str]:
    commit, dirty_digest = git_state()
    return {
        "git_commit": commit,
        "dirty_diff_digest": dirty_digest,
        "source_sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest(),
        "addon_source_sha256": hashlib.sha256(ADDON_PATH.read_bytes()).hexdigest(),
        "catalog_source_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
    }


def _probe_parents(hou_module) -> tuple[dict[str, object], list[object]]:
    created: list[object] = []
    obj = hou_module.node("/obj")
    if obj is None:
        raise RuntimeError("/obj network is unavailable")
    token = uuid4().hex[:10]
    sop = obj.createNode("geo", "BRIDGE_TYPE_SCAN_{}".format(token))
    created.append(sop)
    dop = sop.createNode("dopnet", "DOP_PARENT")
    created.append(dop)

    stage = hou_module.node("/stage")
    if stage is None:
        stage = hou_module.node("/").createNode("lopnet", "stage")
        created.append(stage)
    mat = hou_module.node("/mat")
    if mat is None:
        mat = hou_module.node("/").createNode("mat", "mat")
        created.append(mat)
    tasks = hou_module.node("/tasks")
    if tasks is None:
        tasks = hou_module.node("/").createNode("topnet", "tasks")
        created.append(tasks)
    return {"sop": sop, "obj": obj, "dop": dop, "lop": stage, "vop": mat, "top": tasks}, created


def scan_node_types(hou_module, names: list[str] | tuple[str, ...] = tuple(NAMES)) -> dict[str, object]:
    source_identity_before = source_identity()
    categories = context_categories(hou_module)
    if not categories:
        raise RuntimeError("no Houdini node-type categories resolved")
    parents, created_parents = _probe_parents(hou_module)
    parent_paths = {name: str(parent.path()) for name, parent in parents.items()}
    rows: dict[str, list[dict[str, object]]] = {}
    try:
        for name in names:
            found: list[dict[str, object]] = []
            for context, category in categories.items():
                try:
                    node_type = hou_module.nodeType(category, name)
                except Exception as exc:
                    found.append({"context": context, "resolved": False, "created": False, "lookup_error": str(exc)})
                    continue
                item: dict[str, object] = {
                    "context": context,
                    "resolved": node_type is not None,
                    "resolved_type": node_type.name() if node_type is not None else None,
                    "created": False,
                }
                parent = parents.get(context)
                if parent is None:
                    item["create_error"] = "no real parent available"
                else:
                    node = None
                    try:
                        # A real parent creation is an independent observation:
                        # context aliases can create even when the category
                        # lookup returned None, while some globally resolved
                        # types cannot legally be parented in this network.
                        node = parent.createNode(
                            node_type.name() if node_type is not None else name,
                            "TYPE_SCAN_{}_{}".format(name.replace(":", "_"), uuid4().hex[:8]),
                            exact_type_name=True,
                        )
                        item["created"] = True
                        item["created_type"] = node.type().name()
                    except Exception as exc:
                        item["create_error"] = str(exc)
                    finally:
                        if node is not None:
                            try:
                                node.destroy()
                            except Exception:
                                pass
                found.append(item)
            rows[name] = found
    finally:
        for parent in reversed(created_parents):
            try:
                if parent is not None and parent.isValid():
                    parent.destroy()
            except Exception:
                pass
    source_identity_after = source_identity()
    source_identity_stable = bool(
        all(source_identity_before.values())
        and source_identity_before == source_identity_after
    )
    payload: dict[str, object] = {
        "schema": "houdini.node_type_parent_probe/1.0",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "execution_entrypoint": "tools/scan_node_types.py",
        "probe_level": "node_type_scan",
        "git_commit": source_identity_before["git_commit"],
        "dirty_diff_digest": source_identity_before["dirty_diff_digest"],
        "houdini_build": str(hou_module.applicationVersionString()),
        "contexts": {
            name: {
                "factory": "hou.{}NodeTypeCategory".format(name),
                "category_name": str(category.name()),
                "parent_path": parent_paths.get(name),
            }
            for name, category in sorted(categories.items())
        },
        "source_path": "tools/scan_node_types.py",
        "source_sha256": source_identity_before["source_sha256"],
        "addon_source_path": "plugins/houdini/_impl/houdini_bridge_addon.py",
        "addon_source_sha256": source_identity_before["addon_source_sha256"],
        "catalog_source_path": "packages/houdini-bridge/src/houdini_bridge/domain_packs.py",
        "catalog_source_sha256": source_identity_before["catalog_source_sha256"],
        "source_identity_before": source_identity_before,
        "source_identity_after": source_identity_after,
        "source_identity_stable": source_identity_stable,
        "node_types": rows,
    }
    identity_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload["evidence_identity"] = hashlib.sha256(identity_payload).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", help="write the full resolve/create evidence as JSON")
    args = parser.parse_args()
    try:
        json_output_path = validated_json_output_path(args.json_path) if args.json_path else None
    except ValueError as exc:
        print("invalid JSON output path: {}".format(exc), file=sys.stderr)
        return 2
    import hou

    print("HOUDINI", hou.applicationVersionString())
    try:
        payload = scan_node_types(hou)
    except Exception as exc:
        print("node type scan failed: {}".format(exc), file=sys.stderr)
        return 2
    print("CONTEXTS", " ".join(payload["contexts"]))
    print()
    print(f"{'node type':<30} result")
    print("-" * 60)
    for name in NAMES:
        found = payload["node_types"][name]
        details = []
        for item in found:
            if not item.get("resolved") and not item.get("created"):
                continue
            state = "create" if item.get("created") else "resolve-only"
            details.append("{}:{}".format(item["context"], state))
        print(f"{name:<30} {'OK  ' + ','.join(details) if details else 'MISSING'}")
    if args.json_path:
        path = json_output_path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        print("wrote", path, hashlib.sha256(path.read_bytes()).hexdigest())
    if not payload.get("source_identity_stable"):
        print("source identity changed during node scan", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
