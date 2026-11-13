#!/usr/bin/env python3
"""Inspect shipped Karma example bytes with Python only; never load a HIP in Houdini."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex


MAX_HIP_BYTES = 256 * 1024 * 1024
SELECTED_NODES = (
    "stage/sphere", "stage/backdrop", "stage/materiallibrary3",
    "stage/sphere1", "stage/camera3", "stage/light2",
    "stage/lights/backdrop_shallow", "stage/lights/camera1",
    "stage/lights/rectlight", "stage/lights/light1", "stage/lights/karmarendersettings",
    "stage/lights/OUT_karma_lights",
)
FIELDS = frozenset((
    "primpath", "primpattern", "lighttype", "camera", "focalLength",
    "t", "r", "s", "scale", "radius", "res", "resolution", "resolutionMenu",
    "picture", "outputimage", "lopoutput", "loppath", "renderer", "renderdelegate",
    "denoiser", "enablemblur", "pixelfiltersize", "pixelfilterscale",
    "matpathprefix", "matpath1", "matnode1", "matbinding1", "primpattern1",
    "intensity", "exposure", "base_color", "specular_roughness", "file",
    "xn__inputsintensity_i0a", "xn__inputsexposure_vya", "xn__inputscolor_zta",
    "xn__inputsradius_mva",
))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def member_index(data):
    """Read the exact old-ASCII CPIO layout, without extracting or executing entries."""
    if len(data) > MAX_HIP_BYTES:
        raise ValueError("HIP exceeds inspection byte limit")
    result = {}
    cursor = 0
    while cursor + 76 <= len(data):
        if len(result) >= 100000:
            raise ValueError("HIP member limit exceeded")
        header = data[cursor:cursor + 76]
        if header[:6] != b"070707":
            raise ValueError("Unsupported CPIO header at " + str(cursor))
        if any(value not in b"01234567" for value in header[6:]):
            raise ValueError("Non-octal CPIO header")
        name_size = int(header[59:65], 8)
        size = int(header[65:76], 8)
        if not 1 <= name_size <= 4096:
            raise ValueError("Invalid member name size")
        start = cursor + 76 + name_size
        end = start + size
        if end > len(data):
            raise ValueError("Truncated CPIO member")
        raw_name = data[cursor + 76:start]
        if not raw_name.endswith(b"\0") or b"\0" in raw_name[:-1]:
            raise ValueError("Invalid member name terminator")
        name = raw_name[:-1].decode("utf-8", errors="strict")
        if name == "TRAILER!!!":
            if size or end != len(data):
                raise ValueError("Unexpected trailer payload or trailing bytes")
            return result
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                or name in result):
            raise ValueError("Unsafe or duplicate member name")
        result[name] = {"offset": start, "size_bytes": size}
        cursor = end
    raise ValueError("Missing CPIO trailer")


def inspect(resources, installed_build):
    resources = resources.resolve(strict=True)
    example = resources / "houdini/help/files/karma_user_guide"
    hip = example / "karma_user_guide.hip"
    if hip.stat().st_size > MAX_HIP_BYTES:
        raise ValueError("HIP exceeds inspection byte limit")
    data = hip.read_bytes()
    index = member_index(data)

    def member(name):
        info = index.get(name)
        return data[info["offset"]:info["offset"] + info["size_bytes"]] if info else b""

    def reference(name):
        value = index.get(name)
        return {**value, "member": name, "sha256": digest(member(name))} if value else None

    nodes = {}
    for name in index:
        if name.endswith(".init"):
            match = re.search(rb"^type = ([^\r\n]+)$", member(name), re.M)
            if match:
                nodes[name[:-5]] = match.group(1).decode("utf-8", errors="strict")
    selected = {}
    for node in SELECTED_NODES:
        parm = member(node + ".parm").decode("utf-8", errors="strict")
        saved = {}
        for match in re.finditer(r"^(\w+)\t+\[[^\n]*\]\t+\(\t(.*?)\t\)\s*$", parm, re.M):
            if match.group(1) in FIELDS:
                saved[match.group(1)] = match.group(2)
        definition = member(node + ".def").decode("utf-8", errors="strict")
        block = re.search(r"^inputs\s*\n\{\n(.*?)^\}", definition, re.M | re.S)
        inputs = []
        for line in (block.group(1).splitlines() if block else []):
            tokens = shlex.split(line)
            if tokens:
                inputs.append(tokens)
        selected["/" + node] = {
            "native_type_saved": nodes.get(node),
            "members": [reference(node + suffix) for suffix in (".init", ".def", ".parm")],
            "saved_input_tokens_not_resolved": inputs,
            "saved_parameter_tokens_not_evaluated": saved,
            "descendant_native_types": dict(sorted(Counter(
                value for name, value in nodes.items() if name.startswith(node + "/")).items())),
        }
    inventory = []
    for path in sorted(example.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in official example inventory")
        if path.is_file():
            value = path.read_bytes()
            inventory.append({"path": path.relative_to(example).as_posix(),
                              "size_bytes": len(value), "sha256": digest(value)})
    libraries = []
    for token in member(".OPlibraries").decode("utf-8", errors="strict").splitlines():
        if not token:
            continue
        resolved = None
        for prefix, root in (("$HIP/", example), ("$HFS/", resources)):
            if token.startswith(prefix):
                resolved = (root / token[len(prefix):]).resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError("Library reference escapes its source root")
                break
        info = {"saved_reference": token, "static_file_present": bool(resolved and resolved.is_file()),
                "relative_to_resources": resolved.relative_to(resources).as_posix() if resolved else None}
        if resolved and resolved.is_file():
            value = resolved.read_bytes()
            info.update(size_bytes=len(value), sha256=digest(value))
        libraries.append(info)
    stage_version = re.search(rb"(\d+\.\d+\.\d+)$", member("stage.userdata"))
    return {
        "kind": "static_official_example_inspection_not_runtime_receipt",
        "native_execution": False, "runtime_version_verified": False,
        "installed_directory_build_label": installed_build,
        "resources_path": str(resources), "example_relative_to_resources":
        "houdini/help/files/karma_user_guide", "source_sha256": digest(data),
        "source_size_bytes": len(data), "archive_members": len(index),
        "archive_end_verified": True,
        "stage_userdata_version": stage_version.group(1).decode() if stage_version else None,
        "stage_userdata_reference": reference("stage.userdata"),
        "resource_inventory": inventory, "declared_library_files": libraries,
        "chapter_networks": sorted("/" + name for name, value in nodes.items()
                                  if name.startswith("stage/") and name.count("/") == 1
                                  and value == "lopnet"),
        "usdrender_rop_saved_nodes": sum(value == "usdrender_rop" for value in nodes.values()),
        "selected_nodes": selected,
        "dependency_closure": "NOT_VERIFIED: declarations and selected wire tokens only; "
        "expressions, assets, op references, callbacks and native consumers are not evaluated",
        "host_reopen": "NOT_RUN", "render": "NOT_RUN", "visual_acceptance": "NOT_RUN",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--installed-build", required=True,
                        help="Directory provenance label, not a runtime-version assertion")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.resources, args.installed_build)
    result["inspector_sha256"] = digest(Path(__file__).read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "source_sha256": result["source_sha256"],
                      "archive_members": result["archive_members"], "native_execution": False}))


if __name__ == "__main__":
    main()
