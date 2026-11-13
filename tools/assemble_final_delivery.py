#!/usr/bin/env python3
"""Package a current M1 candidate only after the existing readiness gates pass."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from build_readiness_report import assess, check_review
from readiness_evidence import REQUIRED, build_id


IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
SOURCE_TREES = ("packages", "plugins", "tools", "skills", "tests", "docs", "controller-entry", "agent-plugin", "handover")
SOURCE_FILES = ("README.md", "CHANGELOG.md", "RELEASES.json", "接口文档.md", "AGENTS.md",
                ".gitattributes", ".gitignore", "pyproject.toml", "requirements.txt", "uv.lock", "LICENSE")
LIVE_INDEX = "outputs/live-validation/index.json"
TEXT_SUFFIXES = {
    ".json", ".md", ".py", ".toml", ".txt", ".log", ".patch", ".yaml", ".yml",
    ".ini", ".cfg", ".sh", ".js", ".ts", ".tsx", ".html", ".css", ".xml",
}


def _is_ignored(path: Path) -> bool:
    return (any(part in IGNORED_PARTS for part in path.parts)
            or path.suffix in IGNORED_SUFFIXES or path.name == ".DS_Store")


def _files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()):
        if path.is_symlink():
            raise RuntimeError(f"symlink is not allowed: {path}")
        if path.is_file() and not _is_ignored(path.relative_to(root)):
            yield path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(source: Path, target: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise NotADirectoryError(source)
    target.mkdir(parents=True, exist_ok=True)
    for item in _files(source):
        _copy_file(item, target / item.relative_to(source))


def _copy_source(source: Path, target: Path) -> None:
    """Copy the declared source layout, keeping the required live declaration."""
    if not source.is_dir() or source.is_symlink():
        raise NotADirectoryError(source)
    target.mkdir(parents=True, exist_ok=True)
    for name in SOURCE_TREES:
        if (source / name).exists():
            _copy_tree(source / name, target / name)
    for name in (*SOURCE_FILES, LIVE_INDEX):
        if (source / name).exists():
            _copy_file(source / name, target / name)


def _manifest(root: Path) -> list[dict[str, object]]:
    result = []
    for path in _files(root):
        result.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return result


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _make_patch(original: Path, current: Path, output: Path) -> dict[str, object]:
    old_map = {p.relative_to(original).as_posix(): p for p in _files(original)}
    new_map = {p.relative_to(current).as_posix(): p for p in _files(current)}
    names = sorted(set(old_map) | set(new_map))
    binary: list[dict[str, object]] = []
    chunks: list[str] = []
    changed = 0
    for name in names:
        old_path = old_map.get(name)
        new_path = new_map.get(name)
        old_bytes = old_path.read_bytes() if old_path else b""
        new_bytes = new_path.read_bytes() if new_path else b""
        if old_bytes == new_bytes and bool(old_path) == bool(new_path):
            continue
        changed += 1
        try:
            if (b"\0" in old_bytes + new_bytes
                    or old_path is not None and not old_bytes
                    or new_path is not None and not new_bytes):
                raise UnicodeDecodeError("utf-8", b"\0", 0, 1, "binary or empty-file delta")
            old_lines = old_bytes.decode("utf-8").splitlines(keepends=True) if old_path else []
            new_lines = new_bytes.decode("utf-8").splitlines(keepends=True) if new_path else []
        except UnicodeDecodeError:
            change = {
                "path": name,
                "old_sha256": hashlib.sha256(old_bytes).hexdigest() if old_path else None,
                "new_sha256": hashlib.sha256(new_bytes).hexdigest() if new_path else None,
                "old_bytes": len(old_bytes) if old_path else 0,
                "new_bytes": len(new_bytes) if new_path else 0,
            }
            for kind, data, present in (("old", old_bytes, old_path), ("new", new_bytes, new_path)):
                if present:
                    checksum = hashlib.sha256(data).hexdigest()
                    blob = output.parent / "blobs" / (checksum + ".bin")
                    blob.parent.mkdir(parents=True, exist_ok=True)
                    blob.write_bytes(data)
                    change[kind + "_payload"] = "blobs/" + blob.name
            binary.append(change)
            continue
        from_name = f"a/{name}" if old_path else "/dev/null"
        to_name = f"b/{name}" if new_path else "/dev/null"
        for line in difflib.unified_diff(old_lines, new_lines, fromfile=from_name, tofile=to_name, lineterm="\n"):
            chunks.append(line)
            if not line.endswith("\n"):
                chunks.append("\n\\ No newline at end of file\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes("".join(chunks).encode("utf-8"))
    return {"changed_files": changed, "binary_changes": binary, "patch_bytes": output.stat().st_size}


def _safe_member(name: str) -> bool:
    path = Path(name)
    return (not path.is_absolute() and not any(part in {"", ".", ".."} for part in name.split("/"))
            and "\\" not in name and ":" not in name and name != "")


def _zip_audit(archive: Path, stage: Path, expected_manifest: list[dict[str, object]]) -> dict[str, object]:
    manifest_map = {str(item["path"]): item for item in expected_manifest}
    with zipfile.ZipFile(archive) as handle:
        infos = handle.infolist()
        names = [info.filename for info in infos]
        duplicate_names = len(names) != len(set(names))
        unsafe_names = [name for name in names if not _safe_member(name)]
        symlink_names = [
            info.filename for info in infos
            if ((info.external_attr >> 16) & 0o170000) == 0o120000
        ]
        utf8_failures = []
        for name in names:
            try:
                name.encode("utf-8")
            except UnicodeEncodeError:
                utf8_failures.append(name)
        crc_error = handle.testzip()
        stage_names = sorted(item["path"] for item in expected_manifest)
        archive_names = sorted(names)
        manifest_consistent = archive_names == stage_names
        hash_mismatches = []
        for item in expected_manifest:
            member = str(item["path"])
            data = handle.read(member)
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                hash_mismatches.append(member)
    text_decode_failures = []
    for item in expected_manifest:
        name = str(item["path"])
        if Path(name).suffix.lower() in TEXT_SUFFIXES:
            try:
                (stage / name).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text_decode_failures.append(name)
    return {
        "archive": archive.name,
        "member_count": len(names),
        "crc_error": crc_error,
        "duplicate_names": duplicate_names,
        "unsafe_names": unsafe_names,
        "symlink_names": symlink_names,
        "utf8_name_failures": utf8_failures,
        "text_decode_failures": text_decode_failures,
        "manifest_consistent": manifest_consistent,
        "hash_mismatches": hash_mismatches,
        "passed": not any((crc_error, duplicate_names, unsafe_names, symlink_names,
                            utf8_failures, text_decode_failures, not manifest_consistent,
                            hash_mismatches)),
    }


def _run_patch(patch_path: Path, baseline: Path, expected: Path, binary_changes=()) -> dict[str, object]:
    """Apply to a clean copy and compare all resulting bytes to the target."""
    with tempfile.TemporaryDirectory(prefix="bridge-m1-patch-") as temp:
        work = Path(temp) / "work"
        _copy_tree(baseline, work)
        argv = ["patch", "--batch", "--forward", "-E", "-p1"]
        if os.name == 'nt':
            argv.append('--binary')
        patch_bytes = patch_path.read_bytes()
        patch_text = patch_bytes.decode("utf-8")
        if patch_text:
            result = subprocess.run(argv, cwd=work, input=patch_bytes,
                                    capture_output=True, check=False)
            returncode = result.returncode
            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')
        else:
            returncode, stdout, stderr = 0, "No text changes.\n", ""
        binary_errors = []
        if returncode == 0:
            for change in binary_changes:
                try:
                    name = change["path"]
                    if not _safe_member(name):
                        raise ValueError("unsafe binary delta path")
                    target = work / name
                    old_sha = change["old_sha256"]
                    new_sha = change["new_sha256"]
                    for checksum in (old_sha, new_sha):
                        if checksum is not None and (not isinstance(checksum, str) or len(checksum) != 64
                                                    or any(c not in "0123456789abcdef" for c in checksum)):
                            raise ValueError("invalid binary delta hash")
                    if target.is_symlink() or (old_sha is None and target.exists()):
                        raise ValueError("unexpected binary delta pre-state")
                    if old_sha is not None and (not target.is_file() or _sha256(target) != old_sha):
                        raise ValueError("binary delta pre-state hash mismatch")
                    if new_sha is None:
                        target.unlink()
                    else:
                        payload_name = change["new_payload"]
                        if payload_name != "blobs/" + new_sha + ".bin":
                            raise ValueError("invalid binary payload address")
                        payload = patch_path.parent / payload_name
                        if _sha256(payload) != new_sha or payload.stat().st_size != change["new_bytes"]:
                            raise ValueError("binary payload hash/size mismatch")
                        _copy_file(payload, target)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    binary_errors.append(str(exc))
        actual_manifest = _manifest(work)
        expected_manifest = _manifest(expected)
    return {
        "patch": patch_path.name,
        "argv": argv, "applied": bool(patch_text),
        "returncode": returncode,
        "manifest_equal": actual_manifest == expected_manifest,
        "binary_delta_count": len(binary_changes), "binary_errors": binary_errors,
        "passed": returncode == 0 and not binary_errors and actual_manifest == expected_manifest,
        "stdout": stdout, "stderr": stderr,
    }


def _read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _readiness_gate(args, source: Path) -> tuple[dict, dict[str, Path], dict]:
    paths = {"matrix": args.readiness_dir / "acceptance_matrix.json"}
    for name, filename in (("contract_evidence", "executed-contracts.json"),
                           ("domain_cases", "domain-cases.json"), ("media", "media-readiness.json"),
                           ("skill_lifecycle", "skill-lifecycle.json"), ("audit", "independent-review.json")):
        paths[name] = getattr(args, name) or args.readiness_dir / filename
    values, errors = {}, []
    for name, path in paths.items():
        try:
            values[name] = _read_object(path)
        except (OSError, ValueError) as exc:
            values[name] = {}
            errors.append(f"{name}: {exc}")
    # Raw receipts, source bindings and independent reviewer identity are
    # evaluated by the same gate that creates the readiness matrix.
    try:
        matrix = assess(values["contract_evidence"], values["domain_cases"], values["media"],
                        values["skill_lifecycle"], values["audit"], root=source)
        errors.extend(matrix["errors"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        matrix = {}
        errors.append(f"readiness evidence validation failed: {exc}")
    recorded = values["matrix"]
    if (recorded.get("schema") != "bridge.full_readiness.contract_matrix/2.0"
            or recorded.get("build_id") != build_id(source)
            or recorded.get("software_preparation_status") != "PASS"
            or recorded.get("software_preparation_status") != matrix.get("software_preparation_status")
            or recorded.get("errors") != []
            or recorded.get("row_count") != len(REQUIRED)
            or recorded.get("rows") != matrix.get("rows")):
        errors.append("recorded acceptance matrix is missing, NOT_READY, stale, or differs from validated evidence")
    # Also retain explicit review errors if malformed contract data aborted assess.
    errors.extend(check_review(values["audit"], source))
    try:
        _read_object(source / LIVE_INDEX)
    except (OSError, ValueError) as exc:
        errors.append(f"required live-validation declaration: {exc}")
    if errors or matrix.get("software_preparation_status") != "PASS":
        raise ValueError("M1 delivery rejected: " + json.dumps(sorted(set(errors)), ensure_ascii=False))
    return matrix, paths, values


def _validate_release(release: Path, source: Path, lifecycle: dict) -> list[Path]:
    from build_release import iter_release_files, validate_release_manifest
    from verify_skill_lifecycle import _extract
    manifest_path = release / "release-manifest.json"
    validate_release_manifest(manifest_path)
    manifest = _read_object(manifest_path)
    artifacts = manifest["artifacts"]
    expected_skills = {"houdini-bridge", "nuke-bridge", "vfx-visual-twin"}
    if len(artifacts) != 3 or {item.get("skill") for item in artifacts} != expected_skills:
        raise ValueError("exactly three release Skill artifacts required")
    if {(a.get("skill"), a.get("archive")) for a in artifacts} != {
            (a.get("skill"), a.get("archive")) for a in lifecycle.get("artifacts", [])}:
        raise ValueError("Skill lifecycle evidence does not identify the packaged archives")
    layout = _read_object(source / "tools/release_layout.json")["skills"]
    for artifact in artifacts:
        with tempfile.TemporaryDirectory(prefix="bridge-m1-release-audit-") as temp:
            _extract(release / artifact["archive"], Path(temp) / "extracted")
        skill = artifact["skill"]
        config = layout[skill]
        expected = {}
        for name in config["files"]:
            path = source / "skills" / skill / name
            expected[name] = (_sha256(path), path.stat().st_size)
        trees = [(source / "packages" / name, "runtime/" + name) for name in config.get("runtime_packages", [])]
        trees += [(source / "plugins" / name, "plugins/" + name) for name in config.get("plugins", [])]
        trees += [(source / name, "deploy/" + name) for name in config.get("deployment_trees", [])]
        for root, prefix in trees:
            for path in iter_release_files(root):
                expected[prefix + "/" + path.relative_to(root).as_posix()] = (_sha256(path), path.stat().st_size)
        for name in config.get("deployment_resources", []):
            path = source / name
            expected["deploy/" + name] = (_sha256(path), path.stat().st_size)
        actual = {item["path"].split("/", 1)[1]: (item["sha256"], item["bytes"]) for item in artifact["files"]}
        if actual != expected:
            raise ValueError(f"{skill}: release bytes do not match the current frozen source/layout")
    return [manifest_path] + [release / item["archive"] for item in artifacts]


def _copy_bound_evidence(values, source: Path, destination: Path) -> None:
    """Retain hash-bound external/outputs files without copying old output trees."""
    source = source.resolve()
    copied = {}
    visited = set()
    def retain(name, checksum):
        path = Path(name)
        path = path if path.is_absolute() else source / path
        if path.is_symlink() or not path.is_file() or _sha256(path) != checksum:
            raise ValueError(f"bound evidence file is missing or changed: {name}")
        path = path.resolve()
        identity = (name, checksum)
        if identity in visited:
            return
        visited.add(identity)
        local = path.relative_to(source) if path.is_relative_to(source) else None
        shipped = local is not None and not _is_ignored(local) and (
            local.parts[0] in SOURCE_TREES or local.as_posix() in (*SOURCE_FILES, LIVE_INDEX))
        if not shipped:
            logical_key = hashlib.sha256(name.encode("utf-8")).hexdigest()
            relative = ("source-paths/" + path.relative_to(source).as_posix() if path.is_relative_to(source)
                        else "external/" + checksum + "/" + path.name)
            if any(entry["package_relative_path"] == "evidence/bound-files/" + relative
                   for entry in copied.values()):
                relative = "logical-aliases/" + logical_key + "/" + path.name
            if name in copied and copied[name]["sha256"] != checksum:
                raise ValueError("conflicting original logical evidence path")
            _copy_file(path, destination / relative)
            copied[name] = {"original_logical_path": name,
                            "package_relative_path": "evidence/bound-files/" + relative,
                            "path": relative, "sha256": checksum,
                            "bytes": path.stat().st_size, "modified_ns": path.stat().st_mtime_ns}
            if path.suffix == ".json":
                walk(json.loads(path.read_text(encoding="utf-8")))
    def walk(value):
        if isinstance(value, dict):
            if value.get("schema") == "bridge.readiness.static_check/1":
                from readiness_evidence import _static_argv_executes_script
                script = value.get("script") or {}
                argv = (value.get("execution") or {}).get("argv")
                script_path, checksum = script.get("path"), script.get("sha256")
                if (isinstance(script_path, str) and isinstance(checksum, str)
                        and _static_argv_executes_script(argv, source, script_path)):
                    # The verified Python argv points to this exact hashed source
                    # script. Preserve argv bytes and map only its physical read.
                    option_index = 1
                    while option_index < len(argv) and argv[option_index].startswith("-"):
                        option = argv[option_index]
                        option_index += 1
                        if option == "--":
                            break
                    logical = argv[option_index]
                    if Path(logical).is_absolute():
                        actual = source / script_path
                        if _sha256(actual) != checksum:
                            raise ValueError("static argv source script changed")
                        copied[logical] = {"original_logical_path": logical,
                            "package_relative_path": "source/bridge-skills/" + actual.relative_to(source).as_posix(),
                            "sha256": checksum, "bytes": actual.stat().st_size,
                            "modified_ns": actual.stat().st_mtime_ns}
            for field, hash_field in (("path", "sha256"), ("uri", "sha256"),
                                      ("snapshot_path", "snapshot_sha256"), ("snapshot", "snapshot_sha256")):
                name, checksum = value.get(field), value.get(hash_field)
                if isinstance(name, str) and isinstance(checksum, str):
                    retain(name, checksum)
            for field, identity in (("directory", "identity"), ("supervisor_directory", "supervisor_identity")):
                if isinstance(value.get(field), str) and isinstance(value.get(identity), dict):
                    directory = Path(value[field])
                    stopped = directory / "stopped.json"
                    for name in (directory / "started.json", stopped, directory / "receipt.key"):
                        retain(str(name), _sha256(name))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(values)
    _write_json(destination / "path-map.json", copied)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--original-zip", type=Path, required=True)
    parser.add_argument("--review-zip", type=Path, required=True)
    parser.add_argument("--review-report", type=Path, required=True)
    parser.add_argument("--review-evidence-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--original-contract", type=Path, required=True)
    parser.add_argument("--readiness-dir", type=Path, required=True)
    for name in ("contract-evidence", "domain-cases", "media", "skill-lifecycle", "audit"):
        parser.add_argument("--" + name, type=Path,
                            help="Executed evidence JSON; defaults to the matching file in --readiness-dir")
    parser.add_argument("--evidence-file", type=Path, action="append", default=[],
                        help="Additional necessary raw evidence file to retain outside the source tree")
    parser.add_argument("--full-log", type=Path, required=True)
    parser.add_argument("--targeted-log", type=Path, required=True)
    parser.add_argument("--build-log", type=Path, required=True)
    parser.add_argument("--lifecycle-log", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--package-name", required=True)
    args = parser.parse_args()

    if not _safe_member(args.package_name) or "/" in args.package_name:
        raise ValueError("package-name must be a single safe path component")
    for key, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, key, value.expanduser().resolve())

    source = args.source.expanduser().resolve()
    original_source = args.original_source.expanduser().resolve()
    target_dir = args.target_dir.expanduser().resolve()
    archive = target_dir / f"{args.package_name}.zip"
    sidecar = target_dir / f"{args.package_name}.sha256"
    if archive.exists() or sidecar.exists():
        raise FileExistsError(f"refusing to overwrite existing delivery: {archive}")
    sys.path.insert(0, str(source / "packages/dcc-task-runtime/src"))
    matrix, evidence_paths, validated_evidence = _readiness_gate(args, source)
    ready_build = matrix["build_id"]
    release_files = _validate_release(args.release_dir, source, _read_object(evidence_paths["skill_lifecycle"]))

    temp_parent = Path(tempfile.mkdtemp(prefix="bridge-m1-delivery-"))
    stage = temp_parent / args.package_name
    try:
        clean_source = stage / "source" / "bridge-skills"
        _copy_source(source, clean_source)
        clean_original = temp_parent / "original-source"
        _copy_source(original_source, clean_original)
        if build_id(clean_source) != ready_build or build_id(source) != ready_build:
            raise ValueError("source changed while readiness evidence/source were frozen")
        _copy_file(args.original_zip, stage / "input" / args.original_zip.name)
        _copy_file(args.review_zip, stage / "input" / args.review_zip.name)
        _copy_file(args.review_report, stage / "input" / args.review_report.name)
        _copy_tree(args.review_evidence_dir, stage / "evidence" / "original-r3-review")
        _copy_file(args.contract, stage / "input" / "contracts" / "执行交接合同.md")
        _copy_file(args.original_contract, stage / "input" / "contracts" / "原始C1-C6执行合同.md")
        for name, path in evidence_paths.items():
            destination = stage / "evidence" / "readiness" / (name + ".json")
            _copy_file(path, destination)
            if _read_object(destination) != validated_evidence[name]:
                raise ValueError(f"validated {name} evidence changed while being frozen")
        _copy_bound_evidence(list(validated_evidence.values()), source, stage / "evidence" / "bound-files")
        for index, path in enumerate(args.evidence_file):
            _copy_file(path, stage / "evidence" / "additional" / str(index) / path.name)
        _copy_file(args.full_log, stage / "evidence" / "full-suite-final.log")
        _copy_file(args.targeted_log, stage / "evidence" / "targeted" / "remaining-handoff.log")
        _copy_file(args.build_log, stage / "evidence" / "package-build.log")
        _copy_file(args.lifecycle_log, stage / "evidence" / "skill-lifecycle.log")
        for path in release_files:
            _copy_file(path, stage / "release" / args.release_dir.name / path.name)
        _validate_release(stage / "release" / args.release_dir.name, clean_source,
                          validated_evidence["skill_lifecycle"])

        patch_dir = stage / "patch"
        forward_info = _make_patch(clean_original, clean_source, patch_dir / "forward.patch")
        reverse_info = _make_patch(clean_source, clean_original, patch_dir / "reverse.patch")
        _write_json(patch_dir / "BINARY-CHANGES.json", {
            "schema": "bridge.m1.patch_binary_changes/2.0",
            "forward": forward_info,
            "reverse": reverse_info,
            "note": "Apply the text patch, then each binary delta after validating old_sha256; new_payload is hash-addressed. Compare the complete source manifest after replay.",
        })
        patch_checks = {
            "schema": "bridge.m1.patch_replay/2.0",
            "forward": _run_patch(patch_dir / "forward.patch", clean_original, clean_source, forward_info["binary_changes"]),
            "reverse": _run_patch(patch_dir / "reverse.patch", clean_source, clean_original, reverse_info["binary_changes"]),
        }
        patch_checks["passed"] = bool(patch_checks["forward"]["passed"] and patch_checks["reverse"]["passed"])
        _write_json(stage / "evidence" / "patch-replay.json", patch_checks)
        if not patch_checks["passed"]:
            raise ValueError("M1 delivery rejected: source patch replay failed: " + json.dumps(patch_checks, ensure_ascii=False))

        _write_json(stage / "hashes" / "source-current.json", {
            "root": "source/bridge-skills",
            "file_count": len(_manifest(stage / "source" / "bridge-skills")),
            "files": _manifest(stage / "source" / "bridge-skills"),
        })
        _write_json(stage / "hashes" / "source-original-r3.json", {
            "root": "original-r3-source-reference",
            "file_count": len(_manifest(clean_original)),
            "files": _manifest(clean_original),
        })
        _write_json(stage / "hashes" / "frozen-inputs.json", {
            "schema": "bridge.s06.frozen_inputs/1.0",
            "original_r3_zip": {"name": args.original_zip.name, "sha256": _sha256(args.original_zip), "bytes": args.original_zip.stat().st_size},
            "r3_review_zip": {"name": args.review_zip.name, "sha256": _sha256(args.review_zip), "bytes": args.review_zip.stat().st_size},
            "source_current": {"file_count": len(_manifest(stage / "source" / "bridge-skills"))},
            "source_original_r3": {"file_count": len(_manifest(clean_original))},
        })

        readme = "# Bridge M1 delivery\n\n"
        readme += f"Software preparation status: {matrix['software_preparation_status']}. Build: {ready_build}. The existing readiness validator has accepted all 54 required rows (including the 17 C1-C6 contracts), 48 domain cases, two composite chains, media evidence, three Skill lifecycles, and the closed independent review. Evidence is under `evidence/`.\n\n"
        readme += "Real Houdini/Nuke/WorkBuddy/HY3 reachability, native readback, simulation/cache/render/composite execution, model calls, and visual acceptance remain UNVERIFIED_NOT_RUN_BY_CONTRACT. The package must not be used to claim those gates are passed.\n\n"
        readme += "`source/bridge-skills/` contains the declared source layout and unchanged live-validation index. `input/` preserves the frozen inputs. `patch/` contains text patches and hash-addressed binary deltas validated by actual forward and reverse replay. `release/` contains the three Skill ZIPs and release manifest. `hashes/` and `package-manifest.json` provide file integrity records.\n"
        (stage / "README.md").parent.mkdir(parents=True, exist_ok=True)
        (stage / "README.md").write_text(readme, encoding="utf-8")

        pre_manifest = _manifest(stage)
        audit = {
            "schema": "bridge.m1.package_audit/2.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_source_clean": True,
            "source_trees": list(SOURCE_TREES), "source_files": list(SOURCE_FILES) + [LIVE_INDEX],
            "build_id": ready_build, "software_preparation_status": matrix["software_preparation_status"],
            "excluded_parts": sorted(IGNORED_PARTS | IGNORED_SUFFIXES),
            "forward_patch_replay": patch_checks["forward"],
            "reverse_patch_replay": patch_checks["reverse"],
            "frozen_input_sha256": _sha256(args.original_zip),
            "release_manifest_present": (stage / "release" / args.release_dir.name / "release-manifest.json").is_file(),
            "expected_final_member_count": len(pre_manifest) + 2,
            "archive_checks": "The final archive is re-opened and checked for CRC, duplicate names, safe paths, UTF-8 names/text, symlinks, manifest equality, and member SHA-256 before delivery.",
        }
        _write_json(stage / "package-audit.json", audit)
        manifest = _manifest(stage)
        _write_json(stage / "package-manifest.json", {
            "schema": "bridge.s06.package_manifest/1.0",
            "package_root": args.package_name,
            "file_count": len(manifest),
            "files": manifest,
        })

        staged_archive = temp_parent / archive.name
        with zipfile.ZipFile(staged_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
            for path in _files(stage):
                handle.write(path, path.relative_to(stage).as_posix())
        final_manifest = _manifest(stage)
        zip_result = _zip_audit(staged_archive, stage, final_manifest)
        if not zip_result["passed"]:
            raise RuntimeError(json.dumps(zip_result, ensure_ascii=False))
        # The manifest is deliberately excluded from its own hash list; the archive audit above still checks every member.
        _readiness_gate(args, source)
        current_check = temp_parent / "current-source-check"
        _copy_source(source, current_check)
        if build_id(source) != ready_build or _manifest(clean_source) != _manifest(current_check):
            raise ValueError("source changed before delivery publication")
        if archive.exists() or sidecar.exists():
            raise FileExistsError(f"refusing to overwrite existing delivery: {archive}")
        target_dir.mkdir(parents=True, exist_ok=True)
        package_sha = _sha256(staged_archive)
        os.replace(staged_archive, archive)
        sidecar.write_text(f"{package_sha}  {archive.name}\n", encoding="utf-8")
        _write_json(stage / "evidence" / "final-archive-audit.json", {
            "schema": "bridge.s06.final_archive_audit/1.0",
            "archive": archive.name,
            "sha256": package_sha,
            "bytes": archive.stat().st_size,
            "passed": True,
            "checks": zip_result,
        })
        # Add the audit as an external sidecar as well; changing the staged file after zipping would invalidate the archive.
        external_audit = target_dir / f"{args.package_name}.package-audit.json"
        external_audit.write_text(json.dumps({"archive": archive.name, "sha256": package_sha, "checks": zip_result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "archive": str(archive),
            "sidecar": str(sidecar),
            "package_audit": str(external_audit),
            "sha256": package_sha,
            "bytes": archive.stat().st_size,
            "member_count": zip_result["member_count"],
            "patch_checks_passed": patch_checks["passed"],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(temp_parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
