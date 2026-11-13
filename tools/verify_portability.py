#!/usr/bin/env python3
"""Fail when release-facing text contains a machine-specific user path."""

from __future__ import annotations

import argparse
import json
import re
import stat
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterable, List


PATTERNS = (
    re.compile("C:/Users/" + "32200", re.I),
    re.compile(r"C:\\Users\\" + "32200", re.I),
    re.compile("/Users/" + "user(?:/|$)", re.I),
)
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".txt", ".toml"}
# delivery/ 携带原始运行日志与历史溯源（其内容必须保持原样，属证据而非
# 发布面文本）；发布布局（skills/packages/plugins）仍逐字扫描。
EXCLUDED_PARTS = {".git", "__pycache__", "outputs", "downloads", "archive", "delivery"}


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        yield path


def violations(root: Path) -> List[str]:
    if not root.is_dir():
        raise ValueError("source root must be an existing directory: " + str(root))
    errors: List[str] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("invalid UTF-8 text: {} (decode byte offset {})".format(
                path.relative_to(root), error.start)) from error
        for line_number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                errors.append("{}:{}:{}".format(path.relative_to(root), line_number, line.strip()))
    return errors


def release_violations(release: Path) -> List[str]:
    """Inspect the exact manifested ZIP bytes, excluding checkout-only evidence."""
    from build_release import validate_release_manifest

    manifest = release / "release-manifest.json"
    validate_release_manifest(manifest)
    artifacts = json.loads(manifest.read_text(encoding="utf-8"))["artifacts"]
    if not artifacts:
        raise ValueError("release manifest must contain artifacts")
    errors: List[str] = []
    static_resources = {
        "docs/native-basis/hda-interface-capture.json",
        "docs/native-basis/native-boundary-metadata-supplement.json",
        "docs/native-basis/hda-interface-22.0.459.json",
        "docs/native-basis/supporting-sources-22.0.459.json",
    }
    for artifact in artifacts:
        archive = release / artifact["archive"]
        seen = set()
        with zipfile.ZipFile(archive) as package:
            for info in package.infolist():
                normalized = unicodedata.normalize("NFC", info.filename).casefold()
                if normalized in seen:
                    raise ValueError("duplicate or colliding ZIP member: " + info.filename)
                seen.add(normalized)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("ZIP symlink is not allowed: " + info.filename)
                if info.is_dir() or Path(info.filename).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                payload = package.read(info)
                try:
                    text = payload.decode("utf-8-sig")
                except UnicodeDecodeError as error:
                    raise ValueError("invalid UTF-8 text: {}:{} (decode byte offset {})".format(
                        archive.name, info.filename, error.start)) from error
                if any(info.filename.endswith("/deploy/" + name)
                       or info.filename == "runtime/" + name for name in static_resources):
                    if json.loads(text).get("native_execution") is not False:
                        raise ValueError("native metadata must be static evidence: " + info.filename)
                    continue
                for line_number, line in enumerate(text.splitlines(), 1):
                    if any(pattern.search(line) for pattern in PATTERNS):
                        errors.append("{}:{}:{}".format(archive.name, info.filename, line_number))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--source-root", "--root", dest="source_root", type=Path,
                       help="scan source text, including its documentation and historical evidence")
    scope.add_argument("--release-dir", type=Path,
                       help="validate and scan only the manifested release ZIP bytes")
    args = parser.parse_args()
    try:
        found = (release_violations(args.release_dir.resolve()) if args.release_dir else
                 violations((args.source_root or Path(__file__).resolve().parents[1]).resolve()))
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, TypeError) as error:
        print("FAIL: " + str(error))
        return 1
    if found:
        print("FAIL: {} machine-specific user path occurrences found".format(len(found)))
        print("\n".join(found[:50]))
        if len(found) > 50:
            print("{} additional occurrences omitted".format(len(found) - 50))
        return 1
    print("PASS: {} text is portable".format("manifested release" if args.release_dir else "source"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
