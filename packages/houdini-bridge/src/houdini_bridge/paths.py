"""Cross-platform state and Houdini package discovery helpers."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Iterable, List, Optional


def user_state_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HoudiniBridge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HoudiniBridge"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "houdini-bridge"


def manifests_dir() -> Path:
    return user_state_dir() / "instances"


def bridge_tokens_for_port(port: int) -> tuple[str, ...]:
    """Return all valid private tokens referenced by manifests for ``port``.

    Legacy manifests have no ``token_file`` and contribute no token candidate.
    The instances directory, manifest, and sidecar must not be symlinks.  On
    POSIX the files must be owned by the current user with mode ``0600``.  A
    crashed DCC can leave a stale but otherwise valid manifest for a port that
    a later DCC reuses, so callers need every candidate instead of whichever
    directory entry happens to be visited first.
    """

    directory = manifests_dir()
    try:
        directory_stat = directory.lstat()
    except OSError:
        return ()
    if not stat.S_ISDIR(directory_stat.st_mode) or directory.is_symlink():
        return ()
    if os.name != "nt" and (
        directory_stat.st_uid != os.getuid() or stat.S_IMODE(directory_stat.st_mode) & 0o022
    ):
        return ()
    candidates: list[tuple[int, str, str]] = []
    for manifest in directory.glob("*.json"):
        try:
            manifest_stat = manifest.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(manifest_stat.st_mode) or manifest.is_symlink():
            continue
        if os.name != "nt" and (
            manifest_stat.st_uid != os.getuid() or stat.S_IMODE(manifest_stat.st_mode) != 0o600
        ):
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if int(payload.get("port")) != int(port):
                continue
            token_file = str(payload.get("token_file") or "").strip()
        except (ValueError, OSError, TypeError, json.JSONDecodeError):
            continue
        if not token_file:
            continue
        relative = Path(token_file)
        if relative.is_absolute() or relative.name != token_file:
            continue
        candidate = directory / relative
        try:
            candidate_stat = candidate.lstat()
            if not stat.S_ISREG(candidate_stat.st_mode) or candidate.is_symlink():
                continue
            if os.name != "nt" and (
                candidate_stat.st_uid != os.getuid() or stat.S_IMODE(candidate_stat.st_mode) != 0o600
            ):
                continue
            token = candidate.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        if len(token) >= 32:
            candidates.append((manifest_stat.st_mtime_ns, manifest.name, token))
    # Prefer the newest manifest deterministically, but retain every distinct
    # candidate so a stale token cannot make a reused port undiscoverable.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    tokens: list[str] = []
    for _modified_ns, _manifest_name, token in candidates:
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def bridge_token_for_port(port: int) -> Optional[str]:
    """Return the preferred valid token for ``port``, preserving the old API."""

    tokens = bridge_tokens_for_port(port)
    return tokens[0] if tokens else None


def approval_secret_path() -> Path:
    """Shared control-plane signing key path; the key value is never exposed."""
    explicit = os.environ.get("BRIDGE_SKILLS_APPROVAL_SECRET_FILE")
    return Path(explicit).expanduser() if explicit else Path.home() / ".bridge-skills" / "approval.key"


def package_directory() -> Optional[Path]:
    explicit = os.environ.get("HOUDINI_PACKAGES_DIR")
    if explicit:
        return Path(explicit).expanduser()
    preference = os.environ.get("HOUDINI_USER_PREF_DIR")
    if preference:
        return Path(preference).expanduser() / "packages"
    return None


def preferences_root() -> Path:
    """Return the per-user Houdini preferences root for this platform.

    The root can be overridden for tests or studio layouts with
    ``HOUDINI_USER_PREF_ROOT``.  No ``houdini.env`` file is read or modified.
    """
    explicit = os.environ.get("HOUDINI_USER_PREF_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "houdini"
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "houdini"
    return Path.home() / "houdini"


def package_directories(versions: Iterable[str] = ("21.0", "22.0")) -> List[Path]:
    """Resolve package directories, honoring an explicit single directory.

    ``HOUDINI_PACKAGES_DIR`` is intentionally highest priority so CI and studio
    launchers can install one version.  With no override, both supported
    Houdini generations receive a package file.
    """
    explicit = package_directory()
    if explicit is not None:
        return [explicit]
    configured = os.environ.get("HOUDINI_BRIDGE_VERSIONS")
    selected = [item.strip() for item in (configured.split(",") if configured else versions) if item.strip()]
    return [preferences_root() / version / "packages" for version in selected]
