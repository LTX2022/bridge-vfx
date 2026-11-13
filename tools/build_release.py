#!/usr/bin/env python3
"""Create reproducible standalone Skill ZIPs and a checksum manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterable, Mapping
import re


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
DEFAULT_OUTPUT = ROOT / "outputs" / "releases"
LAYOUT_PATH = ROOT / "tools" / "release_layout.json"
RUNTIME_SOURCE = ROOT / "packages" / "dcc-task-runtime" / "src"
if str(RUNTIME_SOURCE) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SOURCE))

from dcc_task_runtime.runtime_resources import locate_package_source


EXCLUDED_PARTS = {"__pycache__", ".git", "downloads", ".pytest_cache", "evidence", "output", "outputs"}
MANIFEST_NAMES = {"release-manifest.json", "runtime-manifest.json"}
EXCLUDED_NAMES = {".DS_Store", *MANIFEST_NAMES}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
PERSONAL_PATH_PATTERNS = (
    re.compile("C:/Users/" + "32200", re.I),
    re.compile(r"C:\\Users\\" + "32200", re.I),
    re.compile("/Users/" + "user(?:/|$)", re.I),
)


def iter_release_files(skill_root: Path) -> Iterable[Path]:
    for path in sorted(skill_root.rglob("*"), key=lambda path: path.relative_to(skill_root).as_posix()):
        if not path.is_file():
            continue
        if path.name in EXCLUDED_NAMES or any(part in EXCLUDED_PARTS for part in path.relative_to(skill_root).parts) or path.suffix in EXCLUDED_SUFFIXES:
            continue
        yield path


def assert_portable(staging: Path) -> None:
    """Keep standalone ZIPs free from the author's machine paths."""
    from verify_portability import TEXT_SUFFIXES
    for path in iter_release_files(staging):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            if path.suffix.lower() in TEXT_SUFFIXES:
                raise ValueError("invalid UTF-8 text: {} (decode byte offset {})".format(
                    path.relative_to(staging), error.start)) from error
            continue
        relative = path.relative_to(staging).as_posix()
        if relative in {"deploy/docs/native-basis/hda-interface-capture.json",
                         "deploy/docs/native-basis/native-boundary-metadata-supplement.json",
                         "deploy/docs/native-basis/hda-interface-22.0.459.json",
                         "deploy/docs/native-basis/supporting-sources-22.0.459.json"}:
            payload = json.loads(text)
            if payload.get("native_execution") is not False:
                raise ValueError("deployment native metadata must be static evidence")
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PERSONAL_PATH_PATTERNS):
                raise ValueError(f"non-portable path in release: {path}:{line_number}")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def shipped_file_manifest(staging: Path, *, archive_root: Path | None = None) -> list[dict[str, object]]:
    """Describe shipped bytes using paths relative to the ZIP's root.

    Evidence/output directories and manifest files are excluded by
    ``iter_release_files``.  The resulting list is sorted by the same walk
    order used by the ZIP writer, making its digest stable and independent of
    the developer checkout's absolute path.
    """

    staging = Path(staging)
    root = Path(archive_root) if archive_root is not None else staging
    entries: list[dict[str, object]] = []
    for path in iter_release_files(staging):
        try:
            relative = path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"manifest root does not contain shipped file: {path}") from error
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
        )
    return entries


def file_manifest_sha256(entries: Iterable[Mapping[str, object]]) -> str:
    canonical = json.dumps(list(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return digest_bytes(canonical)


def _validate_archive_member(name: str) -> None:
    if not name or "\\" in name or ":" in name:
        raise ValueError(f"unsafe packaged path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError(f"unsafe packaged path: {name!r}")


def validate_packaged_bytes(
    archive: Path,
    expected: Iterable[Mapping[str, object]] | Mapping[str, object],
) -> None:
    """Validate ZIP members against a file manifest without consulting Git.

    ``expected`` may be the artifact mapping returned by ``build_skill`` or
    its ``files`` list.  ZIP member names are checked for traversal and the
    exact non-manifest member set must match the manifest.
    """

    artifact: Mapping[str, object] | None = expected if isinstance(expected, Mapping) else None
    raw_entries = artifact.get("files") if artifact is not None else expected
    if not isinstance(raw_entries, Iterable) or isinstance(raw_entries, (str, bytes, Mapping)):
        raise ValueError("packaged byte manifest must contain a files iterable")
    entries: list[dict[str, object]] = []
    seen_expected: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ValueError("packaged byte manifest entry must be an object")
        name = raw.get("path")
        size = raw.get("bytes")
        checksum = raw.get("sha256")
        if not isinstance(name, str) or not name:
            raise ValueError("packaged byte manifest path must be non-empty text")
        _validate_archive_member(name)
        if name in seen_expected:
            raise ValueError(f"duplicate packaged byte manifest path: {name}")
        seen_expected.add(name)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"invalid packaged byte count for {name}")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.lower()):
            raise ValueError(f"invalid packaged SHA-256 for {name}")
        entries.append({"path": name, "bytes": size, "sha256": checksum.lower()})

    if not entries:
        raise ValueError("packaged byte manifest must not be empty")
    if artifact is not None and artifact.get("file_manifest_sha256") is not None:
        declared_manifest_hash = artifact.get("file_manifest_sha256")
        if not isinstance(declared_manifest_hash, str) or declared_manifest_hash.lower() != file_manifest_sha256(entries):
            raise ValueError("packaged file manifest digest does not match its entries")

    archive = Path(archive)
    actual: dict[str, dict[str, object]] = {}
    with zipfile.ZipFile(archive, "r") as package:
        for info in package.infolist():
            _validate_archive_member(info.filename.rstrip("/")) if info.filename.endswith("/") else _validate_archive_member(info.filename)
            if info.filename.endswith("/"):
                continue
            if info.filename in actual:
                raise ValueError(f"duplicate packaged member: {info.filename}")
            if Path(info.filename).name in MANIFEST_NAMES:
                continue
            payload = package.read(info)
            actual[info.filename] = {
                "path": info.filename,
                "bytes": len(payload),
                "sha256": digest_bytes(payload),
            }

    expected_names = {str(entry["path"]) for entry in entries}
    if set(actual) != expected_names:
        missing = sorted(expected_names - set(actual))
        unexpected = sorted(set(actual) - expected_names)
        raise ValueError(f"packaged member set differs from manifest: missing={missing}, unexpected={unexpected}")
    for entry in entries:
        name = str(entry["path"])
        observed = actual[name]
        if observed["bytes"] != entry["bytes"] or observed["sha256"] != entry["sha256"]:
            raise ValueError(f"packaged bytes differ from manifest: {name}")

    if artifact is not None:
        declared_size = artifact.get("bytes")
        if declared_size is not None and (isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size != archive.stat().st_size):
            raise ValueError("packaged archive size differs from manifest")
        declared_archive_hash = artifact.get("sha256")
        if declared_archive_hash is not None and (not isinstance(declared_archive_hash, str) or declared_archive_hash.lower() != digest(archive)):
            raise ValueError("packaged archive hash differs from manifest")


def validate_release_manifest(manifest_path: Path) -> None:
    """Validate every artifact in an already-built release directory."""

    manifest_path = Path(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts") if isinstance(payload, Mapping) else None
    if not isinstance(artifacts, list):
        raise ValueError("release manifest artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("archive"), str):
            raise ValueError("release manifest artifact is malformed")
        archive_name = artifact["archive"]
        _validate_archive_member(archive_name)
        validate_packaged_bytes(manifest_path.parent / archive_name, artifact)


def load_layout() -> dict[str, dict[str, object]]:
    value = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    if int(value.get("schema_version") or 0) != 1 or not isinstance(value.get("skills"), dict):
        raise ValueError("unsupported release layout")
    return dict(value["skills"])


def copy_relative(source: Path, destination: Path, relative: str) -> None:
    requested = Path(relative)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError(f"unsafe release path: {relative}")
    origin = source / requested
    if not origin.is_file():
        raise FileNotFoundError(origin)
    target = destination / requested
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origin, target)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".DS_Store", "*.pyc", "*.pyo", "downloads"),
    )


def run_staged_self_tests(staging: Path, scripts: list[str]) -> None:
    for relative in scripts:
        path = staging / relative
        subprocess.run([sys.executable, str(path), "--self-test"], cwd=staging, check=True)


def build_skill(skill_name: str, config: dict[str, object], version: str, output_dir: Path) -> dict[str, object]:
    source = SKILLS_ROOT / skill_name
    if not source.is_dir():
        raise FileNotFoundError(source)
    archive = output_dir / f"{skill_name}-skill-v{version}.zip"
    top_level = f"{skill_name}-skill-v{version}"
    with tempfile.TemporaryDirectory(prefix="bridge-skill-release-") as temporary_directory:
        staging = Path(temporary_directory) / top_level
        staging.mkdir(parents=True)
        files = config.get("files") or []
        if not isinstance(files, list) or not files:
            raise ValueError(f"{skill_name}: release files must be a non-empty list")
        for relative in files:
            copy_relative(source, staging, str(relative))
        runtime = staging / "runtime"
        runtime.mkdir()
        for package_name in config.get("runtime_packages") or []:
            distribution_name = str(package_name)
            source_root = locate_package_source(distribution_name, start=ROOT, allow_installed=False)
            copy_tree(source_root.parent, runtime / distribution_name)
        for plugin_name in config.get("plugins") or []:
            copy_tree(ROOT / "plugins" / str(plugin_name), staging / "plugins" / str(plugin_name))
        deployment = staging / "deploy"
        deployment.mkdir()
        for relative in config.get("deployment_trees") or []:
            requested = Path(str(relative))
            if requested.is_absolute() or ".." in requested.parts:
                raise ValueError("unsafe deployment tree")
            copy_tree(ROOT / requested, deployment / requested)
        for relative in config.get("deployment_resources") or []:
            copy_relative(ROOT,deployment,str(relative))
        assert_portable(staging)
        run_staged_self_tests(staging, [str(item) for item in config.get("self_tests") or []])
        file_entries = shipped_file_manifest(staging, archive_root=staging.parent)
        file_manifest_hash = file_manifest_sha256(file_entries)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for path in iter_release_files(staging):
                package.write(path, path.relative_to(staging.parent))
    result = {
        "skill": skill_name,
        "archive": archive.name,
        "bytes": archive.stat().st_size,
        "sha256": digest(archive),
        "files": file_entries,
        "file_manifest_sha256": file_manifest_hash,
    }
    validate_packaged_bytes(archive, result)
    return result


def _git_state() -> dict[str, object]:
    """Development-state identity when a checkout is present.

    Delivery/install trees carry no ``.git``: the build must succeed there and
    record an explicit ``vcs_absent`` identity instead of failing (the
    file-manifest hashes remain the integrity authority in that case).
    """
    import hashlib
    try:
        revision = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip())
        return {"git_revision": revision, "git_dirty": dirty}
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        digest = hashlib.sha256()
        for path in sorted(ROOT.rglob("*"), key=lambda path: path.relative_to(ROOT).as_posix()):
            if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts):
                continue
            digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        return {"git_revision": "vcs_absent", "git_dirty": None, "vcs_absent_tree_sha256": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skill", action="append", dest="skills", help="build only a named Skill; repeatable")
    args = parser.parse_args()
    final_output_dir = args.output / f"v{args.version}"
    if final_output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing release directory: {final_output_dir}")
    layout = load_layout()
    selected = args.skills or list(layout)
    unknown = sorted(set(selected) - set(layout))
    if unknown:
        raise SystemExit("unknown Skill(s): " + ", ".join(unknown))
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"bridge-release-v{args.version}-", dir=args.output) as temporary:
        staging_output = Path(temporary) / f"v{args.version}"
        staging_output.mkdir()
        entries = [build_skill(name, dict(layout[name]), args.version, staging_output) for name in selected]
        manifest = {"schema_version": 2, "version": args.version, **_git_state(), "artifacts": entries}
        manifest_path = staging_output / "release-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_release_manifest(manifest_path)
        staging_output.replace(final_output_dir)
    print(final_output_dir / "release-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
