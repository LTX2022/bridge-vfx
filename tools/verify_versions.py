#!/usr/bin/env python3
"""Check Bridge Skills 2.0 package, dependency, and Skill version parity."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline")
SKILLS = ("houdini-bridge", "nuke-bridge", "vfx-visual-twin")


def _match(path: Path, pattern: str, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError(f"{path.relative_to(ROOT)}: cannot find {label}")
    return match.group(1)


def violations(version: str, display_version: str) -> list[str]:
    errors: list[str] = []
    for package in PACKAGES:
        pyproject = ROOT / "packages" / package / "pyproject.toml"
        setup = ROOT / "packages" / package / "setup.py"
        if not pyproject.is_file() or not setup.is_file():
            errors.append(f"missing package metadata for {package}")
            continue
        project_version = _match(pyproject, r'^version\s*=\s*"([^"]+)"', "project version")
        setup_version = _match(setup, r'version\s*=\s*"([^"]+)"', "setup version")
        if project_version != version:
            errors.append(f"{package}: pyproject version is {project_version}, expected {version}")
        if setup_version != version:
            errors.append(f"{package}: setup version is {setup_version}, expected {version}")
        text = pyproject.read_text(encoding="utf-8") + "\n" + setup.read_text(encoding="utf-8")
        for dependency in PACKAGES:
            if dependency == package or dependency not in text:
                continue
            wrong = [item for item in re.findall(rf'{re.escape(dependency)}==([0-9A-Za-z.]+)', text) if item != version]
            if wrong:
                errors.append(f"{package}: {dependency} dependency versions are {sorted(set(wrong))}, expected {version}")
    for skill in SKILLS:
        entry = ROOT / "skills" / skill / "SKILL.md"
        if not entry.is_file():
            errors.append(f"missing Skill: {skill}")
            continue
        actual = _match(entry, r'^\s*version:\s*"([^"]+)"', "Skill version")
        if actual != display_version:
            errors.append(f"{skill}: Skill version is {actual}, expected {display_version}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="2.0.0rc1")
    parser.add_argument("--display-version", default="2.0.0-rc.1")
    arguments = parser.parse_args()
    errors = violations(arguments.version, arguments.display_version)
    if errors:
        print("FAIL: version mismatch")
        print("\n".join(f"- {item}" for item in errors))
        return 1
    print(f"PASS: package and Skill versions match {arguments.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
