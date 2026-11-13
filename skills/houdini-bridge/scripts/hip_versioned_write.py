"""Create a verified, versioned HIP copy without modifying the input file."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from _skill_runtime import DEFAULT_RUNS_DIR, selected_hython_path, write_log


UTC = timezone.utc
SUPPORTED_HIP_SUFFIXES = {".hip", ".hiplc", ".hipnc"}
APPROVAL_TOKEN = "APPROVED_CONTINUE_PROJECT"


def versioned_output_path(input_hip: Path) -> Path:
    stem = re.sub(r"_ai\d+$", "", input_hip.stem)
    index = 1
    while True:
        candidate = input_hip.with_name(f"{stem}_ai{index:02d}{input_hip.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def build_continue_script(input_hip: Path, output_hip: Path, user_goal: str) -> str:
    return "\n".join(
        (
            "import hou",
            f"INPUT_HIP = {str(input_hip)!r}",
            f"OUTPUT_HIP = {str(output_hip)!r}",
            f"USER_GOAL = {user_goal!r}",
            "hou.hipFile.load(INPUT_HIP, suppress_save_prompt=True)",
            "obj = hou.node('/obj')",
            "if obj is None: raise RuntimeError('/obj network missing')",
            "note = obj.createStickyNote()",
            "note.setText('Houdini Agent continuation note:\\n' + USER_GOAL)",
            "note.setPosition(hou.Vector2(-3.0, 2.0))",
            "hou.hipFile.save(OUTPUT_HIP)",
            "print('saved versioned HIP', OUTPUT_HIP)",
            "",
        )
    )


def build_verify_script(output_hip: Path) -> str:
    return "\n".join(
        (
            "import hou",
            f"OUTPUT_HIP = {str(output_hip)!r}",
            "hou.hipFile.load(OUTPUT_HIP, suppress_save_prompt=True)",
            "obj = hou.node('/obj')",
            "if obj is None: raise RuntimeError('/obj network missing')",
            "if not any('Houdini Agent continuation note' in note.text() for note in obj.stickyNotes()):",
            "    raise RuntimeError('continuation note missing')",
            "print('verified versioned HIP', OUTPUT_HIP)",
            "",
        )
    )


def build_continue_preview(hip_path: Path | str, user_goal: str) -> dict[str, Any]:
    input_hip = Path(hip_path).expanduser()
    if input_hip.suffix.lower() not in SUPPORTED_HIP_SUFFIXES:
        return {"status": "error", "errors": ["input path must be a Houdini .hip, .hiplc, or .hipnc file"]}
    if not input_hip.is_file():
        return {"status": "missing", "errors": ["input HIP file not found"]}
    output_hip = versioned_output_path(input_hip)
    return {
        "status": "preview",
        "hip_path": str(input_hip),
        "output_path": str(output_hip),
        "user_goal": user_goal,
        "approval_required": True,
        "approval_token": APPROVAL_TOKEN,
        "change_plan": [
            "Load the source HIP into hython.",
            "Add a continuation note only in memory.",
            "Save a new versioned HIP file.",
            "Re-open the output HIP and verify the note.",
        ],
    }


def _run(hython: Path, script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(hython), str(script)], capture_output=True, text=True, timeout=120, check=False)


def apply_continue_project(
    hip_path: Path | str,
    user_goal: str,
    *,
    confirmed: bool = False,
    approval_token: str | None = None,
    hython_path: Path | str | None = None,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> dict[str, Any]:
    if not confirmed and approval_token != APPROVAL_TOKEN:
        return {"status": "blocked", "errors": ["confirmed=true or the approval token is required"]}
    preview = build_continue_preview(hip_path, user_goal)
    if preview["status"] != "preview":
        return preview
    hython = Path(hython_path).expanduser() if hython_path else selected_hython_path()
    if hython is None or not hython.is_file():
        return {"status": "missing", "errors": ["hython executable not found; set HYTHON_PATH or add hython to PATH"]}
    source = Path(preview["hip_path"])
    output = Path(preview["output_path"])
    before = source.stat()
    run_dir = Path(runs_dir) / f"continue_project_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    create_script = run_dir / "continue_project.py"
    verify_script = run_dir / "verify_continue_project.py"
    create_script.write_text(build_continue_script(source, output, user_goal), encoding="utf-8")
    verify_script.write_text(build_verify_script(output), encoding="utf-8")
    create_result = _run(hython, create_script)
    verify_result = _run(hython, verify_script) if create_result.returncode == 0 and output.is_file() else None
    after = source.stat()
    source_changed = before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size
    errors: list[str] = []
    if create_result.returncode:
        errors.append("versioned HIP creation failed")
    if not output.is_file():
        errors.append("versioned output HIP was not created")
    if verify_result and verify_result.returncode:
        errors.append("versioned output HIP verification failed")
    if source_changed:
        errors.append("input HIP changed during versioned write")
    payload = {
        **preview,
        "status": "ok" if not errors else "error",
        "run_dir": str(run_dir),
        "hython": str(hython),
        "input_hip_modified": source_changed,
        "stdout": create_result.stdout + (verify_result.stdout if verify_result else ""),
        "stderr": create_result.stderr + (verify_result.stderr if verify_result else ""),
        "errors": errors,
    }
    write_log(run_dir / "run_log.json", payload)
    return payload
