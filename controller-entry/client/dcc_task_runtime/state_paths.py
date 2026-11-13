"""Per-user installation state roots shared by every host adapter (R05).

Houdini, Nuke and the controller-side graph flow must resolve the SAME
installation root so a single heavy-job slot and one artifact ledger exist
per installation.  ``BRIDGE_SKILLS_STATE_ROOT`` / ``BRIDGE_SKILLS_SCHEDULER_ROOT``
are explicit process-local overrides for tests and standalone validators;
production adapters never set them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def installation_state_root() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return Path(os.environ.get("BRIDGE_SKILLS_STATE_ROOT") or root / "HoudiniBridge")
    if sys.platform == "darwin":
        override = os.environ.get("BRIDGE_SKILLS_STATE_ROOT")
        return Path(override) if override else Path.home() / "Library" / "Application Support" / "HoudiniBridge"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "houdini-bridge"
    return Path(os.environ.get("BRIDGE_SKILLS_STATE_ROOT") or base)


def installation_scheduler_root() -> Path:
    configured = os.environ.get("BRIDGE_SKILLS_SCHEDULER_ROOT")
    if configured:
        return Path(configured).expanduser()
    return installation_state_root() / "graph_scheduler"
