"""Portable helpers shared by standalone Houdini skill scripts.

The v1.0.0 package imported application-only modules that were not shipped with
the skill. This module deliberately uses the standard library so scripts can
run from any installed copy of the skill.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.robotparser
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_RUNS_DIR = Path(os.environ.get("DCC_AGENT_RUNS_DIR", Path.home() / ".dcc-agent-runs"))
DOCS_USER_AGENT = "HoudiniBridgeDocs/1.0 (+local skill utility)"


def selected_hython_path() -> Path | None:
    """Return an explicitly configured or discoverable hython executable."""
    configured = os.environ.get("HYTHON_PATH")
    candidates = [configured] if configured else []
    candidates.extend([shutil.which("hython"), shutil.which("hython.exe")])
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            if path.exists() and path.is_file():
                return path
    return None


def write_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_record(record: dict[str, Any]) -> str | None:
    required = ("id", "title", "source_url", "content", "metadata")
    missing = [field for field in required if not record.get(field)]
    return f"missing required document fields: {', '.join(missing)}" if missing else None


def docs_base_url_for_version(version: str | None) -> str:
    suffix = (version or "").strip()
    return f"https://www.sidefx.com/docs/houdini{suffix}/" if suffix else "https://www.sidefx.com/docs/houdini/"


def fetch_url(url: str, timeout_seconds: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": DOCS_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def check_robots_allowed(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except OSError as exc:
        return {"status": "unknown", "allowed": None, "robots_url": robots_url, "error": str(exc)}
    return {"status": "ok", "allowed": parser.can_fetch(DOCS_USER_AGENT, url), "robots_url": robots_url}

