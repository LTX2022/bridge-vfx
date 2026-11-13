#!/usr/bin/env python3
"""Validate the current Houdini add-on through a fresh loopback HTTP server.

Run this file with the target build's ``hython``.  It imports the add-on from
the checkout, starts a new server on the first free Bridge port, makes only
read-only HTTP requests, and shuts down only that server.  Existing Houdini GUI
processes and their manifests are never selected or stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
CATALOG_PATH = ROOT / "packages" / "houdini-bridge" / "src" / "houdini_bridge" / "domain_packs.py"


def validated_json_output_path(value: str) -> Path:
    """Keep evidence writes out of the measured checkout except its excluded index tree."""

    repository = ROOT.resolve()
    lexical = Path(os.path.abspath(str(Path(value).expanduser())))
    try:
        lexical_relative = lexical.relative_to(repository)
    except ValueError:
        lexical_relative = None
    if lexical_relative is not None:
        current = repository
        for component in lexical_relative.parts:
            current = current / component
            if current.is_symlink():
                raise ValueError("JSON output path must not traverse a repository symlink")
    resolved = lexical.resolve()
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        if lexical_relative is not None:
            raise ValueError("JSON output path escapes the repository through a symlink")
        return resolved
    if lexical_relative is None:
        raise ValueError("JSON output path reaches the repository through an indirect path")
    if relative.parts[:2] != ("outputs", "live-validation"):
        raise ValueError(
            "JSON output inside the repository is allowed only under outputs/live-validation"
        )
    return resolved


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> tuple[str, str]:
    def run(*args: str) -> bytes:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return completed.stdout

    try:
        commit = run("rev-parse", "HEAD").decode("ascii").strip()
        status = run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".", ":(exclude)outputs/live-validation/**")
        diff = run("diff", "--binary", "--", ".", ":(exclude)outputs/live-validation/**")
        staged = run("diff", "--cached", "--binary", "--", ".", ":(exclude)outputs/live-validation/**")
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return "", ""
    digest = hashlib.sha256()
    digest.update(status)
    digest.update(b"\0DIFF\0")
    digest.update(diff)
    digest.update(b"\0STAGED\0")
    digest.update(staged)
    repository_root = ROOT.resolve()
    for record in status.split(b"\0"):
        if not record.startswith(b"?? "):
            continue
        relative = record[3:].decode("utf-8", errors="surrogateescape")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return "", ""
        unresolved = repository_root / relative_path
        encoded_relative = relative.encode("utf-8", errors="surrogateescape")
        if unresolved.is_symlink():
            try:
                link_target = os.readlink(unresolved)
            except OSError:
                return "", ""
            digest.update(encoded_relative)
            digest.update(b"\0SYMLINK\0")
            digest.update(link_target.encode("utf-8", errors="surrogateescape"))
            continue
        try:
            path = unresolved.resolve()
            path.relative_to(repository_root)
        except ValueError:
            return "", ""
        if not path.is_file():
            return "", ""
        digest.update(encoded_relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return commit, digest.hexdigest()


def _source_identity() -> dict[str, str]:
    commit, dirty_digest = _git_state()
    return {
        "git_commit": commit,
        "dirty_diff_digest": dirty_digest,
        "source_sha256": _sha256(Path(__file__).resolve()),
        "addon_source_sha256": _sha256(ADDON_PATH),
        "catalog_source_sha256": _sha256(CATALOG_PATH),
    }


def _load_addon():
    spec = importlib.util.spec_from_file_location("_validate_houdini_http_addon", ADDON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Houdini add-on")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rpc(
    port: int,
    method: str,
    kwargs: dict[str, Any],
    *,
    token: str | None = None,
    origin: str | None = None,
    require_success: bool = True,
) -> dict[str, Any]:
    body = urllib.parse.urlencode({"json": json.dumps([method, [], kwargs], ensure_ascii=False)}).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(
        "http://127.0.0.1:{}/api".format(port),
        data=body,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
    payload = json.loads(raw)
    if require_success and payload.get("status") != "success":
        raise RuntimeError("HTTP RPC failed: {}".format(payload))
    return payload


def _validate(addon, port: int, token: str) -> dict[str, Any]:
    health = _rpc(port, "mcp.health", {}, token=token)
    capabilities = _rpc(
        port,
        "mcp.execute",
        {"command": "capabilities.get", "params": {}, "request_id": "fresh-http-capabilities"},
        token=token,
    )
    probe = _rpc(
        port,
        "mcp.execute",
        {
            "command": "agent.fx.probe",
            "params": {"step_params": {"domain_pack": "pyro_smoke_v1"}},
            "request_id": "fresh-http-fx-probe",
        },
        token=token,
    )
    blocked_command = _rpc(
        port,
        "mcp.execute",
        {"command": "code.exec_python", "params": {"code": "result = 1"}, "request_id": "blocked-command"},
        token=token,
        require_success=False,
    )
    missing_token = _rpc(
        port,
        "mcp.health",
        {},
        require_success=False,
    )
    cross_site_origin = _rpc(
        port,
        "mcp.health",
        {},
        token=token,
        origin="https://cross-site.invalid",
        require_success=False,
    )
    health_data = health["data"]
    capability_data = capabilities["data"]
    probe_data = probe["data"]
    gates = probe_data.get("gates") or []
    packs = capability_data.get("fx_domain_packs") or []
    checks = {
        "fresh_process_pid": int(health_data.get("pid") or -1) == os.getpid(),
        "reported_port_matches": int(health_data.get("port") or -1) == port,
        "headless_instance": health_data.get("gui") is False,
        "all_first_party_packs_reported": len(packs) == 15,
        "no_pack_supported": not any(bool(item.get("supported_by_current_installation")) for item in packs),
        "probe_gate_exact": len(gates) == 1
        and gates[0].get("name") == "fx_node_contract_probe"
        and gates[0].get("kind") == "capability"
        and type(gates[0].get("passed")) is bool,
        "probe_source_matches_loaded_addon": probe_data.get("domain_pack", {}).get("source_sha256") == _sha256(ADDON_PATH),
        "code_exec_python_rejected": (blocked_command.get("error") or {}).get("code") == "COMMAND_NOT_ALLOWED",
        "missing_token_rejected": (missing_token.get("error") or {}).get("code") == "AUTH_REQUIRED",
        "cross_site_origin_rejected": (cross_site_origin.get("error") or {}).get("code") == "CROSS_SITE_ORIGIN_REJECTED",
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "health": health,
        "capabilities": capabilities,
        "fx_probe": probe,
        "negative_probes": {
            "code_exec_python": blocked_command,
            "missing_token": missing_token,
            "cross_site_origin": cross_site_origin,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", required=True)
    args = parser.parse_args()

    try:
        json_output_path = validated_json_output_path(args.json_path)
    except ValueError as exc:
        print("invalid JSON output path: {}".format(exc), file=sys.stderr)
        return 2

    source_identity_before = _source_identity()
    addon = _load_addon()
    token = secrets.token_urlsafe(32)
    allowed_commands = frozenset({"ping", "capabilities.get", "agent.fx.probe"})
    server = addon.HoudiniBridgeServer(token=token, allowed_commands=allowed_commands)
    port = server.start()
    holder: dict[str, Any] = {}

    def worker() -> None:
        try:
            holder["validation"] = _validate(addon, port, token)
        except Exception as exc:
            holder["error"] = "{}: {}".format(type(exc).__name__, exc)

    thread = threading.Thread(target=worker, name="houdini-http-live-validator")
    thread.start()
    deadline = time.monotonic() + 60.0
    try:
        while thread.is_alive() and time.monotonic() < deadline:
            server.pump()
            thread.join(0.01)
        thread.join(0.1)
        if thread.is_alive():
            holder["error"] = "validation timed out"
    finally:
        server.stop()

    import hou

    source_identity_after = _source_identity()
    source_identity_stable = bool(
        all(source_identity_before.values())
        and source_identity_before == source_identity_after
    )
    validation = holder.get("validation") or {}
    checks = validation.setdefault("checks", {})
    checks["source_identity_stable"] = source_identity_stable
    validation["passed"] = bool(holder.get("validation") and checks and all(checks.values()))
    payload = {
        "schema": "houdini.http_live_validation/1.0",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "execution_entrypoint": "tools/validate_houdini_http.py",
        "probe_level": "fresh_loopback_http",
        "git_commit": source_identity_before["git_commit"],
        "dirty_diff_digest": source_identity_before["dirty_diff_digest"],
        "houdini_build": hou.applicationVersionString(),
        "process_pid": os.getpid(),
        "port": port,
        "server_policy": {
            "token_required": True,
            "allowed_commands": sorted(allowed_commands),
            "cross_site_origin_rejected": True,
        },
        "source_path": "tools/validate_houdini_http.py",
        "source_sha256": source_identity_before["source_sha256"],
        "addon_source_path": "plugins/houdini/_impl/houdini_bridge_addon.py",
        "addon_source_sha256": source_identity_before["addon_source_sha256"],
        "catalog_source_path": "packages/houdini-bridge/src/houdini_bridge/domain_packs.py",
        "catalog_source_sha256": source_identity_before["catalog_source_sha256"],
        "source_identity_before": source_identity_before,
        "source_identity_after": source_identity_after,
        "source_identity_stable": source_identity_stable,
        "validation": validation,
        "error": holder.get("error"),
    }
    identity_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload["evidence_identity"] = hashlib.sha256(identity_payload).hexdigest()
    path = json_output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    print("HOUDINI", payload["houdini_build"])
    print("FRESH HTTP", "PASS" if validation.get("passed") and not payload["error"] else "FAIL", "pid", os.getpid(), "port", port)
    for name, passed in sorted((validation.get("checks") or {}).items()):
        print("{}={}".format(name, "PASS" if passed else "FAIL"))
    print("wrote", path, _sha256(path))
    return 0 if validation.get("passed") and not payload["error"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
