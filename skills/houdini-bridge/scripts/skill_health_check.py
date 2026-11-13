#!/usr/bin/env python3
"""Portable integrity checks for repository skills or one released Skill."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ALLOWED_FRONTMATTER = {"name", "description", "license", "metadata", "allowed-tools"}
REQUIRED_SELF_TESTS = {
    "houdini-bridge": ("install_runtime.py", "skill_health_check.py"),
    "nuke-bridge": ("install_runtime.py",),
    "vfx-visual-twin": ("install_runtime.py",),
}
PORTABILITY_PATTERNS = (
    re.compile("C:/Users/" + "32200", re.I),
    re.compile(r"C:\\Users\\" + "32200", re.I),
    re.compile("/Users/" + "user(?:/|$)", re.I),
)


def frontmatter_keys(text: str) -> set[str]:
    if not text.startswith("---\n"):
        return set()
    closing = text.find("\n---", 4)
    if closing < 0:
        return set()
    return {match.group(1) for match in re.finditer(r"^([A-Za-z][\w-]*):", text[4:closing], re.MULTILINE)}


def frontmatter_name(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    closing = text.find("\n---", 4)
    if closing < 0:
        return ""
    match = re.search(r"^name:\s*[\"']?([^\"'\n]+)", text[4:closing], re.MULTILINE)
    return match.group(1).strip() if match else ""


def check_skill(root: Path) -> list[str]:
    errors: list[str] = []
    skill_md = root / "SKILL.md"
    if not skill_md.is_file() or skill_md.stat().st_size == 0:
        return [f"{root.name}: missing or empty SKILL.md"]
    text = skill_md.read_text(encoding="utf-8-sig")
    skill_name = frontmatter_name(text) or root.name
    keys = frontmatter_keys(text)
    if not {"name", "description"}.issubset(keys):
        errors.append(f"{root.name}: frontmatter needs name and description")
    illegal = keys - ALLOWED_FRONTMATTER
    if illegal:
        errors.append(f"{root.name}: unsupported frontmatter keys: {sorted(illegal)}")
    refs = set(re.findall(r"references/[\w./-]+\.(?:md|json|hip|nk)", text))
    for relative in refs:
        target = root / relative
        if not target.is_file() or target.stat().st_size == 0:
            errors.append(f"{root.name}: missing referenced file {relative}")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py", ".json", ".yaml", ".yml"} and path.stat().st_size == 0:
            errors.append(f"{root.name}: empty file {path.relative_to(root)}")
        if path.is_file() and path.suffix in {".md", ".py", ".json", ".yaml", ".yml", ".txt"} and "archive" not in path.parts:
            text_path = path.read_text(encoding="utf-8-sig", errors="replace")
            if any(pattern.search(text_path) for pattern in PORTABILITY_PATTERNS):
                errors.append(f"{root.name}: machine-specific user path in {path.relative_to(root)}")
    for script_name in REQUIRED_SELF_TESTS.get(skill_name, ()):
        script = root / "scripts" / script_name
        if not script.is_file() or "def self_test" not in script.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{root.name}: missing self_test in {script_name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", type=Path)
    args = parser.parse_args()
    if args.skills_root:
        roots = tuple(path for path in sorted(args.skills_root.iterdir()) if (path / "SKILL.md").is_file())
    else:
        current = Path(__file__).resolve().parents[1]
        siblings = tuple(path for path in sorted(current.parent.iterdir()) if (path / "SKILL.md").is_file())
        roots = siblings if len(siblings) > 1 else (current,)
    errors: list[str] = []
    for root in roots:
        errors.extend(check_skill(root))
    if not roots:
        errors.append("no Skill folders found")
    if errors:
        print("FAIL")
        print("\n".join(f"- {item}" for item in errors))
        return 1
    print("PASS: skill metadata, references, non-empty files, and self-test coverage are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
