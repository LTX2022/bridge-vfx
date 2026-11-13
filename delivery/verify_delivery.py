#!/usr/bin/env python3
"""Verify a Bridge C1-C6 delivery tree or ZIP without changing either one."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", "outputs", "delivery"}
IGNORED_FILES = {".DS_Store"}
EXPECTED_INPUT_SHA256 = "d87a7eb922924afd3f9f0d37fc506bea6aa9c6a588c62af9a932b10aebcb620d"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_archive_members(archive: zipfile.ZipFile, *, require_utf8: bool) -> tuple[list[zipfile.ZipInfo], list[str]]:
    infos = archive.infolist()
    errors: list[str] = []
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        trimmed = name[:-1] if info.is_dir() and name.endswith("/") else name
        parts = trimmed.split("/")
        if (not name or name.startswith("/") or "\\" in name or "\x00" in name
                or any(part in {"", ".", ".."} for part in parts)
                or (parts and ":" in parts[0])
                or PurePosixPath(name).is_absolute()):
            errors.append("unsafe path: " + repr(name))
        canonical = trimmed
        if canonical in seen:
            errors.append("duplicate path: " + repr(name))
        seen.add(canonical)
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            errors.append("symbolic link: " + repr(name))
        if require_utf8 and not (info.flag_bits & 0x800):
            errors.append("missing UTF-8 filename flag: " + repr(name))
    return infos, errors


def checked_extract(archive_path: Path, destination: Path, *, require_utf8: bool) -> dict[str, object]:
    with zipfile.ZipFile(archive_path) as archive:
        infos, errors = safe_archive_members(archive, require_utf8=require_utf8)
        corrupt = archive.testzip()
        if corrupt is not None:
            errors.append("CRC failure: " + corrupt)
        if errors:
            return {"ok": False, "entries": len(infos), "errors": errors}
        destination.mkdir(parents=True, exist_ok=True)
        base = destination.resolve()
        for info in infos:
            relative = PurePosixPath(info.filename)
            target = base.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(base):
                errors.append("extraction escaped root: " + info.filename)
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
        return {"ok": not errors, "entries": len(infos), "errors": errors}


def included_file(relative: Path) -> bool:
    parts = relative.parts
    if not parts or relative.name in IGNORED_FILES:
        return False
    if parts[0] in {".git", "outputs", "delivery"}:
        return False
    return not any(part in {"__pycache__", ".pytest_cache"} for part in parts)


def tree_hashes(root: Path) -> dict[str, str]:
    root = Path(root)
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not included_file(relative):
            continue
        if path.is_symlink():
            raise ValueError("symbolic link in source tree: " + relative.as_posix())
        if path.is_file():
            result[relative.as_posix()] = sha256_file(path)
    return result


def compare_trees(left: Path, right: Path) -> dict[str, object]:
    a, b = tree_hashes(left), tree_hashes(right)
    missing = sorted(b.keys() - a.keys())
    extra = sorted(a.keys() - b.keys())
    changed = sorted(key for key in a.keys() & b.keys() if a[key] != b[key])
    return {"ok": not (missing or extra or changed), "left_files": len(a), "right_files": len(b),
            "missing_from_left": missing, "extra_in_left": extra, "changed": changed}


def copy_tree_clean(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(source).rglob("*")):
        relative = path.relative_to(source)
        if not included_file(relative):
            continue
        if path.is_symlink():
            raise ValueError("symbolic link in source tree: " + relative.as_posix())
        if path.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def package_path(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(label + " must be a non-empty relative path")
    if "\\" in relative or "\x00" in relative:
        raise ValueError(label + " contains an invalid path separator")
    posix = PurePosixPath(relative)
    if (posix.is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/"))
            or (posix.parts and ":" in posix.parts[0])):
        raise ValueError(label + " is not a safe relative path")
    root = Path(root).resolve()
    target = root.joinpath(*posix.parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError(label + " escapes the package root")
    current = root
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(label + " traverses a symbolic link")
    return target


def apply_patch(cwd: Path, patch: Path, *, reverse: bool) -> dict[str, object]:
    args = ["git", "apply", "--check", "-p1"]
    if reverse:
        args.append("-R")
    args.append(str(patch))
    check = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check.returncode != 0:
        return {"ok": False, "phase": "check", "returncode": check.returncode,
                "stdout": check.stdout, "stderr": check.stderr}
    args.remove("--check")
    applied = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    return {"ok": applied.returncode == 0, "phase": "apply", "returncode": applied.returncode,
            "stdout": applied.stdout, "stderr": applied.stderr}


def verify_tree(root: Path) -> dict[str, object]:
    root = Path(root).resolve()
    errors: list[str] = []
    manifest_path = root / "MANIFEST.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return {"ok": False, "root": str(root), "errors": ["MANIFEST.json is missing"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "root": str(root), "errors": ["invalid MANIFEST.json: " + str(exc)]}

    payload_expected = manifest.get("payload_files")
    if not isinstance(payload_expected, dict):
        errors.append("manifest payload_files must be a path-to-SHA256 object")
        payload_expected = {}
    payload_actual: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            errors.append("symbolic link in delivery tree: " + path.relative_to(root).as_posix())
        elif path.is_file() and path != manifest_path:
            payload_actual[path.relative_to(root).as_posix()] = sha256_file(path)
    if payload_actual != payload_expected:
        errors.append("payload manifest mismatch")

    try:
        input_path = package_path(root, manifest.get("input_archive"), "input_archive")
    except ValueError as exc:
        input_path = root / "__invalid_input_archive__"
        errors.append(str(exc))
    if not input_path.is_file():
        errors.append("original input archive is missing")
        input_hash = None
    else:
        input_hash = sha256_file(input_path)
        if input_hash != EXPECTED_INPUT_SHA256 or input_hash != manifest.get("input_sha256"):
            errors.append("original input archive SHA256 mismatch")

    try:
        source_root = package_path(root, manifest.get("source_root") or "bridge-skills", "source_root")
    except ValueError as exc:
        source_root = root / "__invalid_source_root__"
        errors.append(str(exc))
    source_expected = manifest.get("source_files")
    if not source_root.is_dir():
        errors.append("candidate source root is missing")
        source_actual = {}
    else:
        try:
            source_actual = tree_hashes(source_root)
        except ValueError as exc:
            errors.append(str(exc))
            source_actual = {}
    if not isinstance(source_expected, dict) or source_actual != source_expected:
        errors.append("candidate source manifest mismatch")

    try:
        patch_path = package_path(root, manifest.get("patch_file") or "changes.patch", "patch_file")
    except ValueError as exc:
        patch_path = root / "__invalid_changes.patch"
        errors.append(str(exc))
    patch_hash = sha256_file(patch_path) if patch_path.is_file() else None
    if patch_hash is None or patch_hash != manifest.get("patch_sha256"):
        errors.append("changes.patch SHA256 mismatch or missing")

    patch_results: dict[str, object] = {}
    if input_path.is_file() and source_root.is_dir() and patch_hash is not None:
        with tempfile.TemporaryDirectory(prefix="bridge-delivery-verify-") as temporary:
            temp = Path(temporary)
            baseline_extract = temp / "input"
            nested = checked_extract(input_path, baseline_extract, require_utf8=False)
            if not nested["ok"]:
                errors.append("original input ZIP failed safety/CRC checks")
                patch_results["input_zip"] = nested
            else:
                baseline_root = baseline_extract / "bridge-skills"
                if not baseline_root.is_dir():
                    errors.append("original input ZIP has no bridge-skills/ source root")
                else:
                    forward = temp / "forward"
                    copy_tree_clean(baseline_root, forward)
                    patch_results["forward_apply"] = apply_patch(forward, patch_path, reverse=False)
                    patch_results["forward_compare"] = compare_trees(forward, source_root)
                    if not patch_results["forward_apply"]["ok"] or not patch_results["forward_compare"]["ok"]:
                        errors.append("forward patch reconstruction failed")

                    reverse = temp / "reverse"
                    copy_tree_clean(source_root, reverse)
                    patch_results["reverse_apply"] = apply_patch(reverse, patch_path, reverse=True)
                    patch_results["reverse_compare"] = compare_trees(reverse, baseline_root)
                    if not patch_results["reverse_apply"]["ok"] or not patch_results["reverse_compare"]["ok"]:
                        errors.append("reverse patch reconstruction failed")

    return {"ok": not errors, "root": str(root), "input_sha256": input_hash,
            "source_files": len(source_actual), "patch_sha256": patch_hash,
            "patch_checks": patch_results, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="validate and safely inspect a final ZIP")
    parser.add_argument("--root", type=Path, help="validate an already extracted package root")
    args = parser.parse_args()
    result: dict[str, object]
    if args.archive:
        with tempfile.TemporaryDirectory(prefix="bridge-delivery-zip-") as temporary:
            extracted = Path(temporary) / "package"
            outer = checked_extract(args.archive.resolve(), extracted, require_utf8=True)
            result = {"outer_zip": outer}
            if outer["ok"]:
                result["delivery"] = verify_tree(extracted)
                result["zip_sha256"] = sha256_file(args.archive)
                result["zip_bytes"] = args.archive.stat().st_size
            result["ok"] = bool(outer["ok"] and result.get("delivery", {}).get("ok"))
    else:
        root = args.root.resolve() if args.root else Path(__file__).resolve().parent.parent
        result = verify_tree(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
