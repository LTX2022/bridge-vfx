"""Read-only HIP scene inspector."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from _skill_runtime import DEFAULT_RUNS_DIR, selected_hython_path, write_log


UTC = timezone.utc
SUPPORTED_HIP_SUFFIXES = {".hip", ".hiplc", ".hipnc"}


def write_inspector_script(script_path: Path, hip_path: Path, output_json: Path) -> None:
    body = f'''
import json
from pathlib import Path

import hou

HIP_PATH = r"{hip_path}"
OUTPUT_JSON = r"{output_json}"


def json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {{str(key): json_safe(item) for key, item in value.items()}}
    return str(value)


def collect_key_parameters(node, limit=16):
    parameters = []
    for parm in node.parms():
        try:
            raw_value = parm.rawValue()
        except Exception:
            raw_value = None
        try:
            value = parm.eval()
        except Exception as exc:
            value = None
            eval_error = str(exc)
        else:
            eval_error = None

        include = False
        if raw_value not in (None, "", "0", "0.0"):
            include = True
        try:
            default_value = parm.parmTemplate().defaultValue()
        except Exception:
            default_value = None
        if default_value is not None and value != default_value:
            include = True

        if include:
            parameters.append({{
                "name": parm.name(),
                "label": parm.description(),
                "value": json_safe(value),
                "raw_value": raw_value,
                "eval_error": eval_error,
            }})
        if len(parameters) >= limit:
            break
    return parameters


def node_messages(node):
    try:
        errors = list(node.errors())
    except Exception:
        errors = []
    try:
        warnings = list(node.warnings())
    except Exception:
        warnings = []
    return errors, warnings


def collect_nodes():
    root = hou.node("/")
    if root is None:
        return []
    pending = list(root.children())
    nodes = []
    while pending:
        node = pending.pop(0)
        errors, warnings = node_messages(node)
        nodes.append({{
            "path": node.path(),
            "type": node.type().nameWithCategory(),
            "name": node.name(),
            "key_parameters": collect_key_parameters(node),
            "errors": errors,
            "warnings": warnings,
        }})
        try:
            pending.extend(node.children())
        except Exception:
            pass
    return nodes


def collect_external_references():
    references = []
    try:
        file_references = hou.fileReferences()
    except Exception:
        return references
    for parm, path in file_references:
        try:
            node_path = parm.node().path() if parm is not None else None
            parm_name = parm.name() if parm is not None else None
        except Exception:
            node_path = None
            parm_name = None
        references.append({{
            "node_path": node_path,
            "parameter": parm_name,
            "path": str(path),
        }})
    return references


def main():
    payload = {{
        "status": "ok",
        "hip_path": HIP_PATH,
        "nodes": [],
        "external_file_references": [],
        "errors": [],
        "warnings": [],
    }}
    try:
        hou.hipFile.load(HIP_PATH, suppress_save_prompt=True)
        payload["nodes"] = collect_nodes()
        payload["external_file_references"] = collect_external_references()
    except Exception as exc:
        payload["status"] = "error"
        payload["errors"].append(str(exc))

    Path(OUTPUT_JSON).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if payload["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
'''
    script_path.write_text(body.strip() + "\n", encoding="utf-8")


def run_inspector_process(hython_path: Path, script_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(hython_path), str(script_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _error_payload(status: str, hip_path: Path, errors: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "hip_path": str(hip_path),
        "nodes": [],
        "external_file_references": [],
        "stdout": "",
        "stderr": "",
        "errors": errors,
    }


def analyze_hip_scene(
    hip_path: Path | str,
    hython_path: Path | str | None = None,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> dict[str, Any]:
    resolved_hip = Path(hip_path)
    if resolved_hip.suffix.lower() not in SUPPORTED_HIP_SUFFIXES:
        return _error_payload("error", resolved_hip, ["input path must be a Houdini .hip file"])
    if not resolved_hip.exists():
        return _error_payload("missing", resolved_hip, ["input HIP file not found"])
    if not resolved_hip.is_file():
        return _error_payload("error", resolved_hip, ["input HIP path is not a file"])

    resolved_hython = Path(hython_path) if hython_path else selected_hython_path()
    if not resolved_hython or not resolved_hython.exists():
        return _error_payload("missing", resolved_hip, ["hython executable not found; set HYTHON_PATH or add hython to PATH"])

    before_stat = resolved_hip.stat()
    run_id = f"hip_analyze_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    script_path = run_dir / "inspect_hip.py"
    output_json = run_dir / "scene.json"
    write_inspector_script(script_path, resolved_hip, output_json)

    result = run_inspector_process(resolved_hython, script_path)
    after_stat = resolved_hip.stat()
    input_changed = (
        before_stat.st_mtime_ns != after_stat.st_mtime_ns
        or before_stat.st_size != after_stat.st_size
    )

    payload: dict[str, Any]
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            payload = _error_payload("error", resolved_hip, [f"invalid inspector JSON: {exc}"])
    else:
        payload = _error_payload("error", resolved_hip, ["inspector did not produce scene JSON"])

    errors = list(payload.get("errors", []))
    if result.returncode != 0 and not errors:
        errors.append("hython inspector failed")
    if input_changed:
        errors.append("input HIP changed during read-only analysis")

    status = payload.get("status", "error")
    if result.returncode != 0 or input_changed:
        status = "error"

    payload.update(
        {
            "status": status,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "hython": str(resolved_hython),
            "hip_path": str(resolved_hip),
            "scene_json": str(output_json),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "input_hip_modified": input_changed,
            "errors": errors,
        }
    )
    write_log(run_dir / "run_log.json", payload)
    return payload
