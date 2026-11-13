#!/usr/bin/env python3
"""Assemble and verify the frozen Bridge C1-C6 candidate delivery."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import verify_delivery as verifier


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_INPUT_SHA256 = verifier.EXPECTED_INPUT_SHA256
EXCLUDED = {"__pycache__", ".pytest_cache", ".git", ".DS_Store", "outputs", "delivery"}
GROUPS = {"C1", "C2", "C3", "C4", "C5", "C6"}
DOCS = (
    "CHANGES-C1C6.md",
    "REMAINING-C1C6.md",
    "C1-C6-contract-evidence.md",
    "安装与回退.md",
    "使用说明.md",
)
CONTRACT_FILES = (
    "README.md",
    "MANIFEST.json",
    "GLM精确修改合同-C1-C6.md",
    "Bugbot独立复审.md",
    "复核结论与本轮责任.md",
    "watchdog-entry.log",
    "full-python311.log",
    "package-check.json",
    "verify_delivery.py",
    "probe_generated_launcher.py",
    "probe_real_boundaries.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_build_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED for part in path.parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def tree_digest(entries: dict[str, str]) -> str:
    payload = json.dumps(sorted(entries.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_run_log(path: Path) -> tuple[dict[str, object], dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    start_marker = "=== RUN PROVENANCE (start) ===\n"
    output_marker = "\n=== OUTPUT ===\n"
    end_marker = "\n=== RUN PROVENANCE (end) ===\n"
    if start_marker not in text or output_marker not in text or end_marker not in text:
        raise ValueError(f"not a complete run_logged record: {path}")
    before_output, rest = text.split(output_marker, 1)
    header_text = before_output.split(start_marker, 1)[1]
    output_text, end_text = rest.rsplit(end_marker, 1)
    return json.loads(header_text), json.loads(end_text), output_text


def validate_run(path: Path, expected_hash: str, *, minimum_tests: int | None = None) -> dict[str, object]:
    start, end, output = parse_run_log(path)
    if start.get("build_sha256") != expected_hash:
        raise ValueError(f"build hash differs in {path.name}")
    if end.get("returncode") != 0:
        raise ValueError(f"non-zero exit in {path.name}: {end.get('returncode')}")
    if "OK" not in output.splitlines():
        raise ValueError(f"unittest OK marker missing in {path.name}")
    counts = re.findall(r"^Ran\s+(\d+)\s+tests?\s+in\s+", output, flags=re.MULTILINE)
    if not counts:
        raise ValueError(f"unittest count missing in {path.name}")
    count = int(counts[-1])
    if minimum_tests is not None and count < minimum_tests:
        raise ValueError(f"full-suite count {count} is below frozen baseline {minimum_tests}")
    return {
        "file": path.name,
        "build_sha256": start["build_sha256"],
        "returncode": end["returncode"],
        "tests": count,
        "utc_start": start.get("utc_start"),
        "utc_end": end.get("utc_end"),
        "argv": start.get("argv"),
    }


def copy_regular_file(source: Path, destination: Path) -> None:
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"expected a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_source_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not verifier.included_file(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"source contains a symbolic link: {relative.as_posix()}")
        if path.is_file():
            copy_regular_file(path, destination / relative)


def copy_original_contract(source: Path, destination: Path) -> None:
    for name in CONTRACT_FILES:
        copy_regular_file(source / name, destination / name)
    evidence_source = source / "evidence"
    for path in sorted(evidence_source.rglob("*")):
        relative = path.relative_to(evidence_source)
        if path.is_symlink():
            raise ValueError(f"original evidence contains a symbolic link: {relative.as_posix()}")
        if path.is_file() and path.name != ".DS_Store":
            copy_regular_file(path, destination / "evidence" / relative)


def create_patch(baseline: Path, candidate: Path, patch_path: Path, cwd: Path) -> None:
    args = [
        "git", "-c", "core.quotePath=false", "diff", "--no-index", "--binary",
        "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "--",
        "before/bridge-skills", "after/bridge-skills",
    ]
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if completed.returncode not in {0, 1}:
        raise RuntimeError(f"git diff failed: {completed.stderr}")
    text = completed.stdout
    text = text.replace("a/before/bridge-skills/", "a/")
    text = text.replace("b/after/bridge-skills/", "b/")
    if text and ("diff --git a/" not in text or " b/" not in text):
        raise ValueError("generated patch does not use relative Git paths")
    patch_path.write_text(text, encoding="utf-8", newline="\n")
    if not text:
        raise ValueError("empty changes.patch; input and candidate unexpectedly match")


def payload_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError(f"delivery contains a symbolic link: {relative.as_posix()}")
        if path.is_file() and relative.as_posix() != "MANIFEST.json":
            files[relative.as_posix()] = sha256_file(path)
    return files


def write_manifest(package: Path, source_files: dict[str, str], input_hash: str) -> dict[str, object]:
    patch_hash = sha256_file(package / "changes.patch")
    manifest = {
        "schema": "bridge-c1-c6-delivery/1",
        "input_archive": "input/bridge-skills-R01-R10集中返修候选-20260920.zip",
        "input_sha256": input_hash,
        "source_root": "bridge-skills",
        "patch_file": "changes.patch",
        "patch_sha256": patch_hash,
        "before_source_tree_sha256": tree_digest(
            {key: value for key, value in source_files["before"].items()}
        ),
        "after_source_tree_sha256": tree_digest(source_files["after"]),
        "source_files": source_files["after"],
        "payload_files": payload_hashes(package),
    }
    (package / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


class Utf8ZipInfo(zipfile.ZipInfo):
    def _encodeFilenameFlags(self) -> tuple[bytes, int]:  # noqa: N802 - stdlib override
        return self.filename.encode("utf-8"), self.flag_bits | 0x800


def write_archive(package: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
                         allowZip64=True) as archive:
        for path in sorted(package.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package).as_posix()
            info = Utf8ZipInfo(relative, time.localtime(max(path.stat().st_mtime, 315532800))[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.flag_bits = 0x800
            with path.open("rb") as source, archive.open(info, "w") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def normalized_verification(result: dict[str, object]) -> dict[str, object]:
    delivery = result.get("delivery")
    if not isinstance(delivery, dict):
        return {"ok": False, "outer_zip": result.get("outer_zip"), "delivery": delivery}
    return {
        "ok": bool(result.get("ok")),
        "outer_zip": result.get("outer_zip"),
        "delivery": {
            key: delivery.get(key)
            for key in ("ok", "input_sha256", "source_files", "patch_sha256", "patch_checks", "errors")
        },
    }


def verify_archive(archive_path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "delivery" / "verify_delivery.py"), "--archive", str(archive_path)],
        cwd=ROOT, text=True, capture_output=True,
    )
    try:
        result = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError(f"delivery verifier returned invalid JSON: {completed.stderr}\n{completed.stdout}") from exc
    if completed.returncode != 0 or not result.get("ok"):
        raise RuntimeError("delivery verification failed:\n" + completed.stdout + completed.stderr)
    return result


def parse_target_logs(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("target logs must use GROUP=PATH")
        group, raw_path = value.split("=", 1)
        group = group.upper()
        if group not in GROUPS or group in parsed:
            raise ValueError(f"invalid or duplicate target group: {group}")
        parsed[group] = Path(raw_path).resolve()
    if parsed.keys() != GROUPS:
        raise ValueError("one current-hash green targeted log is required for every C1-C6 group")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--full-log", required=True, type=Path)
    parser.add_argument("--target-log", action="append", default=[], metavar="GROUP=PATH")
    parser.add_argument("--extra-evidence", action="append", default=[], type=Path)
    parser.add_argument(
        "--input-zip",
        type=Path,
        default=Path("/Users/user/.zcode/workspace/default/bridge-c1-c6-20260920/合同包/input/bridge-skills-R01-R10集中返修候选-20260920.zip"),
    )
    parser.add_argument(
        "--contract-dir",
        type=Path,
        default=Path("/Users/user/.zcode/workspace/default/bridge-c1-c6-20260920/合同包"),
    )
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "outputs/c1-c6-evidence")
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing delivery: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    input_zip = args.input_zip.resolve()
    contract_dir = args.contract_dir.resolve()
    evidence_dir = args.evidence_dir.resolve()
    if not input_zip.is_file() or sha256_file(input_zip) != EXPECTED_INPUT_SHA256:
        raise ValueError("original input ZIP is missing or its frozen SHA256 changed")

    current_hash = run_build_hash(ROOT)
    full_log = args.full_log.resolve()
    full_record = validate_run(full_log, current_hash, minimum_tests=805)
    target_paths = parse_target_logs(args.target_log)
    target_records = {
        group: validate_run(path, current_hash)
        for group, path in sorted(target_paths.items())
    }

    source_snapshot_before = verifier.tree_hashes(ROOT)
    with tempfile.TemporaryDirectory(prefix="bridge-c1-c6-package-", dir=output.parent) as temporary:
        temporary_root = Path(temporary)
        baseline_extract = temporary_root / "input"
        nested_check = verifier.checked_extract(input_zip, baseline_extract, require_utf8=False)
        if not nested_check["ok"]:
            raise ValueError("frozen input ZIP failed its CRC/path checks: " + json.dumps(nested_check))
        baseline = baseline_extract / "bridge-skills"
        if not baseline.is_dir():
            raise ValueError("frozen input ZIP has no bridge-skills/ root")

        package = temporary_root / "package"
        package.mkdir()
        candidate_package_source = package / "bridge-skills"
        copy_source_tree(ROOT, candidate_package_source)
        source_snapshot_after = verifier.tree_hashes(ROOT)
        if source_snapshot_after != source_snapshot_before or verifier.tree_hashes(candidate_package_source) != source_snapshot_before:
            raise RuntimeError("candidate changed while the delivery snapshot was being copied")

        copy_regular_file(input_zip, package / "input" / input_zip.name)
        for name in DOCS:
            copy_regular_file(ROOT / "delivery" / name, package / name)
        copy_regular_file(ROOT / "delivery" / "verify_delivery.py", package / "delivery" / "verify_delivery.py")
        copy_original_contract(contract_dir, package / "evidence" / "original")

        run_dest = package / "evidence"
        for path in sorted(evidence_dir.rglob("*")):
            relative = path.relative_to(evidence_dir)
            if path.is_symlink():
                raise ValueError("C1-C6 evidence contains a symbolic link: " + relative.as_posix())
            if path.is_file():
                if path.name.startswith("green-final-") or path.name.startswith("green-c1-contract-single-"):
                    continue
                copy_regular_file(path, run_dest / relative)
        selected_logs = list(target_paths.values()) + [path.resolve() for path in args.extra_evidence]
        for path in dict.fromkeys([full_log, *selected_logs]):
            if path.resolve().is_relative_to(evidence_dir):
                copy_regular_file(path, run_dest / path.resolve().relative_to(evidence_dir))
                continue
            copy_regular_file(path, run_dest / "external" / path.name)

        source_files = {"before": verifier.tree_hashes(baseline), "after": source_snapshot_before}
        patch_workspace = temporary_root / "patch-work"
        before_tree, after_tree = patch_workspace / "before/bridge-skills", patch_workspace / "after/bridge-skills"
        verifier.copy_tree_clean(baseline, before_tree)
        verifier.copy_tree_clean(candidate_package_source, after_tree)
        create_patch(before_tree, after_tree, package / "changes.patch", patch_workspace)

        (package / "evidence" / "acceptance.json").write_text(
            json.dumps({
                "ok": True,
                "build_sha256": current_hash,
                "frozen_full_suite_baseline": 805,
                "full_suite": full_record,
                "targeted_groups": target_records,
                "real_dcc_launched": False,
                "domain_gate": "16 domains / 48 cases retained; no real-host acceptance claimed",
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        sha_lines = [
            f"input_archive_sha256  {EXPECTED_INPUT_SHA256}",
            f"before_source_tree_sha256  {tree_digest(source_files['before'])}",
            f"after_source_tree_sha256  {tree_digest(source_files['after'])}",
            f"changes_patch_sha256  {sha256_file(package / 'changes.patch')}",
            "",
        ]
        (package / "evidence" / "SHA256.txt").write_text("\n".join(sha_lines), encoding="utf-8")

        manifest = write_manifest(package, source_files, EXPECTED_INPUT_SHA256)
        baseline_forward = temporary_root / "forward-check"
        verifier.copy_tree_clean(baseline, baseline_forward)
        forward = verifier.apply_patch(baseline_forward, package / "changes.patch", reverse=False)
        forward_compare = verifier.compare_trees(baseline_forward, candidate_package_source)
        candidate_reverse = temporary_root / "reverse-check"
        verifier.copy_tree_clean(candidate_package_source, candidate_reverse)
        reverse = verifier.apply_patch(candidate_reverse, package / "changes.patch", reverse=True)
        reverse_compare = verifier.compare_trees(candidate_reverse, baseline)
        if not (forward["ok"] and forward_compare["ok"] and reverse["ok"] and reverse_compare["ok"]):
            raise RuntimeError("patch failed bidirectional file-for-file reconstruction")
        (package / "evidence" / "patch-check.json").write_text(
            json.dumps({
                "ok": True,
                "forward_apply": forward,
                "forward_compare": forward_compare,
                "reverse_apply": reverse,
                "reverse_compare": reverse_compare,
                "baseline_files": len(source_files["before"]),
                "candidate_files": len(source_files["after"]),
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # patch-check.json is part of the manifest, so regenerate it after writing the receipt.
        manifest = write_manifest(package, source_files, EXPECTED_INPUT_SHA256)

        archive_path = temporary_root / output.name
        write_archive(package, archive_path)
        first = verify_archive(archive_path)
        receipt = normalized_verification(first)
        (package / "evidence" / "verify_delivery-output.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest(package, source_files, EXPECTED_INPUT_SHA256)
        write_archive(package, archive_path)
        final_result = verify_archive(archive_path)
        final_normalized = normalized_verification(final_result)
        stored_receipt = json.loads((package / "evidence" / "verify_delivery-output.json").read_text(encoding="utf-8"))
        if final_normalized != stored_receipt:
            raise RuntimeError("embedded delivery verification receipt differs from final archive validation")
        if source_snapshot_after != verifier.tree_hashes(ROOT):
            raise RuntimeError("candidate source changed during archive validation")
        os.replace(archive_path, output)

    print(json.dumps({
        "ok": True,
        "archive": str(output),
        "zip_sha256": sha256_file(output),
        "zip_bytes": output.stat().st_size,
        "source_build_sha256": current_hash,
        "full_tests": full_record["tests"],
        "patch_bidirectional": True,
        "verification": final_result,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
