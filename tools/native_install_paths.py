"""Exact static vendor resource paths; never discover or execute a host."""
from pathlib import Path
import json
import re


DEFAULT_BUILDS = ("21.0.631", "22.0.459")
SUPPORTED_BUILDS = ("21.0.631", "22.0.429", "22.0.459")


def require_local_module(module, source):
    origin = getattr(module, "__file__", None)
    if origin is None or Path(origin).resolve() != Path(source).resolve():
        raise ValueError("module source does not match reviewed file: " + str(source))


def validate_output_path(output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing existing output or link: " + str(output))


def write_new_output(output, result):
    output = Path(output)
    validate_output_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def resource_directory(install_root, version, *, layout="macos"):
    if version not in SUPPORTED_BUILDS:
        raise ValueError("unsupported contract build: " + str(version))
    if layout not in ("macos", "windows"):
        raise ValueError("unsupported install layout: " + str(layout))
    root = Path(install_root)
    build_name = ("Houdini " if layout == "windows" else "Houdini") + version
    if re.fullmatch(r"Houdini ?\d+\.\d+\.\d+", root.name):
        if root.name != build_name:
            raise ValueError("install directory does not match layout/build: " + str(root))
        build_root = root
    else:
        build_root = root / build_name
    if layout == "windows":
        return build_root / "houdini"
    return build_root / "Frameworks/Houdini.framework/Versions" / version[:4] / "Resources/houdini"
