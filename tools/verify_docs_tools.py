#!/usr/bin/env python3
"""Ensure public documentation only names registered bridge commands."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / name / "src")
    for name in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline")
]

from houdini_bridge.registry import COMMANDS as HOUDINI_COMMANDS, LEGACY_ALIASES as HOUDINI_ALIASES
from nuke_bridge.registry import COMMANDS as NUKE_COMMANDS, LEGACY_ALIASES as NUKE_ALIASES
from vfx_pipeline.__main__ import _parser as pipeline_parser
from vfx_pipeline.commands import MODEL_SAFE_COMMANDS, TRUSTED_CONTROL_COMMANDS


COMMAND_PATTERN = re.compile(r"`([a-z][a-z0-9_-]*(?:[._][a-z][a-z0-9_-]*)+)`")
PIPELINE_CLI_PATTERN = re.compile(
    r"\bvfx-pipeline(?:\s+--state-db\s+\S+)?\s+([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?"
)
PIPELINE_PREFIXES = (
    "domain.",
    "model.",
    "task.",
    "feedback.",
    "candidate.",
    "approval.",
    "cache.",
    "verification.",
    "experience.",
    "graph.",
    "execution.",
)
CURATED_REFERENCES = {
    "houdini-bridge": {"bridge-protocol.md", "runtime-contract.md", "model-to-karma.md", "verification-gates.md", "specialist-simulations.md", "failure-recovery.md", "version-compatibility.md"},
    "nuke-bridge": {"runtime-contract.md", "render-delivery.md", "failure-recovery.md", "version-compatibility.md"},
}


def validate(skill: str, commands: set[str], aliases: dict[str, str]) -> list[str]:
    root = ROOT / "skills" / skill
    files = [root / "SKILL.md", *sorted(path for path in (root / "references").glob("*.md") if path.name in CURATED_REFERENCES[skill])]
    errors: list[str] = []
    allowed = commands | set(aliases)
    for path in files:
        for command in COMMAND_PATTERN.findall(path.read_text(encoding="utf-8")):
            if "*" in command or command in {"houdini_bridge", "nuke_bridge"}:
                continue
            command_like = command.startswith(("scene.", "node.", "viewport.", "help.", "code.", "debug.", "capabilities.", "task.", "render.", "agent.", "nuke_", "list_", "get_", "create_", "connect_", "delete_", "set_", "open_", "save_", "verify_", "screenshot"))
            if command_like and command not in allowed:
                errors.append(f"{path.relative_to(ROOT)}: unregistered command {command}")
    return errors


def _pipeline_cli_commands(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> set[str]:
    subparsers = next(
        (action for action in parser._actions if isinstance(action, argparse._SubParsersAction)),
        None,
    )
    if subparsers is None:
        return {".".join(prefix)} if prefix else set()
    result: set[str] = set()
    for name, child in subparsers.choices.items():
        result.update(_pipeline_cli_commands(child, (*prefix, name)))
    return result


def _visual_twin_files() -> list[Path]:
    root = ROOT / "skills" / "vfx-visual-twin"
    return [root / "SKILL.md", *sorted((root / "references").rglob("*.md"))]


def validate_pipeline_docs() -> list[str]:
    """Check the CLI, public command sets, root interface, and Visual Twin refs together."""

    errors: list[str] = []
    registered = set(MODEL_SAFE_COMMANDS) | set(TRUSTED_CONTROL_COMMANDS)
    actual_cli = _pipeline_cli_commands(pipeline_parser())
    if actual_cli != registered:
        errors.append(
            "vfx-pipeline CLI/public command mismatch: "
            f"missing_from_cli={sorted(registered - actual_cli)}, "
            f"unregistered_cli={sorted(actual_cli - registered)}"
        )

    interface = ROOT / "接口文档.md"
    if not interface.is_file():
        return [*errors, "接口文档.md: missing root interface documentation"]
    interface_text = interface.read_text(encoding="utf-8")
    documented = {
        token
        for token in COMMAND_PATTERN.findall(interface_text)
        if token.startswith(PIPELINE_PREFIXES)
    }
    if "`capabilities`" in interface_text:
        documented.add("capabilities")
    if documented != registered:
        errors.append(
            "接口文档.md: command coverage mismatch: "
            f"missing={sorted(registered - documented)}, unknown={sorted(documented - registered)}"
        )

    for path in [interface, *_visual_twin_files()]:
        text = path.read_text(encoding="utf-8")
        for token in COMMAND_PATTERN.findall(text):
            if (token == "capabilities" or token.startswith(PIPELINE_PREFIXES)) and token not in registered:
                errors.append(f"{path.relative_to(ROOT)}: unregistered pipeline command {token}")
        for first, second in PIPELINE_CLI_PATTERN.findall(text):
            rendered = first if not second or second.startswith("-") else f"{first}.{second}"
            if rendered not in registered:
                errors.append(f"{path.relative_to(ROOT)}: invalid vfx-pipeline invocation {rendered}")
    return errors


def main() -> int:
    errors = validate("houdini-bridge", HOUDINI_COMMANDS, HOUDINI_ALIASES)
    errors.extend(validate("nuke-bridge", NUKE_COMMANDS, NUKE_ALIASES))
    errors.extend(validate_pipeline_docs())
    if errors:
        print("\n".join(errors))
        return 1
    print("PASS: public documentation commands match bridge registries and vfx-pipeline CLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
