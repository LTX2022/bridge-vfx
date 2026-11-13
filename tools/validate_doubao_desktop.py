#!/usr/bin/env python3
"""Fail-closed preflight for the DoubaoDesktopRoute acceptance harness.

This tool never controls Doubao, sends a prompt, uploads media, or edits the
live-validation index.  It binds installed application identities and, when a
separately trusted UI driver supplies an event manifest, validates the minimum
five-cycle/isolation/synthetic-input contract before emitting a verification
gate candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROUTE_ID = "DoubaoDesktopRoute"
APP_CANDIDATES = (
    Path("/Applications/Doubao.app"),
    Path.home() / "Library" / "Application Support" / "Doubao" / "installed_versions" / "Doubao.app",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plist_value(app: Path, key: str) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/plutil", "-extract", key, "raw", str(app / "Contents" / "Info.plist")],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _signature(app: Path) -> str:
    executable = app / "Contents" / "MacOS" / "Doubao"
    try:
        result = subprocess.run(
            ["/usr/bin/codesign", "-dv", "--verbose=2", str(executable)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = [line.strip() for line in result.stderr.splitlines() if line.startswith(("Identifier=", "TeamIdentifier=", "Authority="))]
    return " | ".join(lines)


def installed_routes() -> list[dict[str, Any]]:
    rows = []
    for app in APP_CANDIDATES:
        executable = app / "Contents" / "MacOS" / "Doubao"
        if app.is_symlink() or executable.is_symlink() or not executable.is_file():
            continue
        rows.append(
            {
                "app_path": str(app),
                "executable_path": str(executable),
                "bundle_id": _plist_value(app, "CFBundleIdentifier"),
                "app_version": _plist_value(app, "CFBundleShortVersionString"),
                "executable_sha256": _sha256(executable),
                "code_signature": _signature(app),
            }
        )
    return rows


def validate_event_manifest(path: Path | None) -> tuple[bool, dict[str, Any]]:
    if path is None:
        return False, {"reason": "ui_event_manifest_not_supplied"}
    if path.is_symlink() or not path.is_file():
        return False, {"reason": "ui_event_manifest_missing_or_unsafe"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return False, {"reason": "ui_event_manifest_invalid_json"}
    missing: list[str] = []
    errors: list[str] = []
    cycles: dict[int, bool] = {}
    observations: dict[str, bool] = {}
    synthetic_only = True
    existing_touched = False
    session = str(payload.get("isolated_session_id") or "") if isinstance(payload, dict) else ""
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("schema") != "bridge.doubao_ui_events/2.0":
        errors.append("unknown_schema")
    if not session or payload.get("route_id") != ROUTE_ID:
        errors.append("route_or_session_mismatch")
    if not isinstance(events, list) or not events:
        errors.append("events_missing")
        events = []
    event_ids: set[str] = set()
    privacy_count = 0
    for event in events:
        if not isinstance(event, dict):
            errors.append("invalid_event")
            continue
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in event_ids or event.get("session_id") != session:
            errors.append("event_identity_mismatch")
            continue
        event_ids.add(event_id)
        if event.get("kind") == "read_cycle":
            cycle = event.get("cycle")
            if type(cycle) is not int or cycle < 1 or cycle > 5 or cycle in cycles:
                errors.append("invalid_read_cycle")
            else:
                cycles[cycle] = event.get("read_succeeded") is True
        elif event.get("kind") == "observation":
            subject = event.get("subject")
            if subject not in {"composer", "image_entry", "model_label"} or subject in observations:
                errors.append("invalid_observation")
            else:
                observations[str(subject)] = event.get("observed") is True
        elif event.get("kind") == "privacy":
            privacy_count += 1
            synthetic_only = synthetic_only and event.get("input_class") == "synthetic"
            existing_touched = existing_touched or event.get("existing_conversation_accessed") is not False
        else:
            errors.append("unknown_event_kind")
    if set(cycles) != set(range(1, 6)) or not all(cycles.values()):
        errors.append("five_successful_cycles_required")
    if privacy_count < 1 or not synthetic_only or existing_touched:
        errors.append("privacy_boundary_failed")
    if not all(observations.get(item) is True for item in ("composer", "image_entry", "model_label")):
        errors.append("required_observation_missing")
    passed = not errors
    return passed, {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "missing_fields": missing,
        "errors": errors,
        "derived": {
            "read_cycles": [cycles.get(index, False) for index in range(1, 6)],
            "synthetic_inputs_only": synthetic_only,
            "existing_conversations_touched": existing_touched,
            "composer_verified": observations.get("composer", False),
            "image_entry_verified": observations.get("image_entry", False),
            "model_label_observed": observations.get("model_label", False),
        },
        "payload": payload if isinstance(payload, dict) else None,
    }


def report(event_manifest: Path | None = None) -> dict[str, Any]:
    routes = installed_routes()
    event_passed, event = validate_event_manifest(event_manifest)
    exact_identity = len(routes) == 1
    if event_passed and exact_identity:
        manifest_route = (event.get("payload") or {}).get("route_identity")
        actual = routes[0]
        identity_fields = ("bundle_id", "app_version", "executable_path", "executable_sha256")
        if not isinstance(manifest_route, dict) or any(
            str(manifest_route.get(field) or "") != str(actual.get(field) or "")
            for field in identity_fields
        ) or manifest_route.get("route_id") != ROUTE_ID or len(str(manifest_route.get("driver_sha256") or "")) != 64:
            event_passed = False
            event.setdefault("errors", []).append("event_route_identity_mismatch")
    passed = exact_identity and event_passed
    return {
        "schema": "bridge.doubao_preflight/1.0",
        "route_id": ROUTE_ID,
        "status": "DOUBAO_UI_CONTROLLED" if passed else "DOUBAO_CONTROL_UNVERIFIED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "installed_routes": routes,
        "identity_unambiguous": exact_identity,
        "ui_event_manifest": event,
        "gates": [
            {
                "name": "doubao_ui_control_verified",
                "kind": "verification",
                "passed": passed,
                "reason": "verified" if passed else ("duplicate_or_missing_app_identity" if not exact_identity else event.get("reason", "ui_event_contract_failed")),
            }
        ],
        "support_promotion": False,
        "privacy": {"synthetic_inputs_only": True, "private_project_upload_allowed": False},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-event-manifest", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    payload = report(args.ui_event_manifest)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["gates"][0]["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
