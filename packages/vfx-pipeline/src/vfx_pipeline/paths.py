"""Host-side state locations for the cross-DCC orchestrator."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from dcc_task_runtime.errors import PolicyDenied
from dcc_task_runtime.models import ErrorCode
from dcc_task_runtime.platform_support import private_permissions_valid


def installation_state_root() -> Path:
    """Per-user installation state root shared by every host adapter.

    Mirrors the Houdini add-on's ``_state_dir().parent`` layout so Houdini,
    Nuke and the controller-side graph flow resolve the SAME installation
    root — a precondition for ONE installation-wide heavy-job slot.
    """
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "HoudiniBridge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HoudiniBridge"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "houdini-bridge"


def installation_scheduler_root() -> Path:
    """Canonical heavy-slot scheduler database root (ONE per installation).

    ``BRIDGE_SKILLS_SCHEDULER_ROOT`` is an explicit process-local override
    used by software tests and standalone validators; production adapters
    never set it, so they all share the same GraphScheduler database.
    """
    configured = os.environ.get("BRIDGE_SKILLS_SCHEDULER_ROOT")
    if configured:
        return Path(configured).expanduser()
    return installation_state_root() / "graph_scheduler"


def state_database() -> Path:
    configured = os.environ.get("VFX_PIPELINE_STATE_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".bridge-skills" / "vfx-pipeline" / "pipeline.sqlite3"


def approval_secret_file() -> Path:
    """Return the shared host/control-plane key path without reading the key."""

    configured = os.environ.get("BRIDGE_SKILLS_APPROVAL_SECRET_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".bridge-skills" / "approval.key"


def load_approval_secret() -> str:
    """Load the cache assertion key using the same convention as Houdini.

    A direct environment value is an explicit process-local override.  The
    normal GUI/CLI integration uses one per-user private file created by the
    bridge installer.  The value is intentionally never returned by any public
    capability or health endpoint.
    """

    direct = os.environ.get("HOUDINI_BRIDGE_APPROVAL_SECRET")
    if direct:
        if len(direct) < 32:
            raise PolicyDenied(ErrorCode.POLICY_DENIED, "approval secret must contain at least 32 characters")
        return direct
    path = approval_secret_file()
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise PolicyDenied(
            ErrorCode.POLICY_DENIED,
            "the shared approval key is missing; run the Bridge installer before cache.run",
        ) from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & 0x400 or info.st_nlink != 1):
        raise PolicyDenied(ErrorCode.POLICY_DENIED, "the shared approval key must be a regular non-symlink file")
    try:
        with path.open('r', encoding='utf-8') as stream:
            if not private_permissions_valid(path, file_descriptor=stream.fileno()):
                raise PolicyDenied(ErrorCode.POLICY_DENIED, "the shared approval key must have private current-user permissions")
            secret = stream.read().strip()
    except OSError as exc:
        raise PolicyDenied(ErrorCode.POLICY_DENIED, "the shared approval key permissions could not be verified") from exc
    if len(secret) < 32:
        raise PolicyDenied(ErrorCode.POLICY_DENIED, "the shared approval key must contain at least 32 characters")
    return secret


# Shared installation roots now live in the low-level runtime package so
# standalone Houdini/Nuke installs resolve the same scheduler and state
# roots without importing this orchestrator package (R05).
from dcc_task_runtime.state_paths import (  # noqa: E401,F401
    installation_scheduler_root,
    installation_state_root,
)

__all__ = ["installation_scheduler_root", "installation_state_root"]
