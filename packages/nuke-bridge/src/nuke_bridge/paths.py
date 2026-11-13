"""Nuke bridge state directory and manifest discovery helpers."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional


_MIN_TOKEN_LENGTH = 32


def _nuke_root() -> Path:
    explicit = os.environ.get("NUKE_BRIDGE_INSTANCES_DIR")
    if explicit:
        return Path(explicit).expanduser()

    # NUKE_PATH is a search path.  The addon and the client must agree on one
    # deterministic state root; use its first real entry and ignore Nuke's
    # ``&`` placeholder for the built-in defaults.
    configured = os.environ.get("NUKE_PATH", "")
    for entry in configured.split(os.pathsep):
        entry = entry.strip()
        if entry and entry != "&":
            return Path(entry).expanduser()
    return Path.home() / ".nuke"


def manifests_dir() -> Path:
    return _nuke_root() / "nuke_bridge_instances"


def _path_has_symlink(path: Path) -> bool:
    current = path.absolute()
    while True:
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _secure_file(path: Path, *, mode: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        return False
    if os.name != "nt" and (
        info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode
    ):
        return False
    return True


def _secure_instances_dir(directory: Path) -> bool:
    if _path_has_symlink(directory):
        return False
    try:
        info = directory.lstat()
    except OSError:
        return False
    if directory.is_symlink() or not stat.S_ISDIR(info.st_mode):
        return False
    if os.name != "nt" and (
        info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022
    ):
        return False
    return True


def _valid_token(value: str) -> bool:
    if len(value) < _MIN_TOKEN_LENGTH or any(character.isspace() for character in value):
        return False
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def bridge_tokens_for_port(port: int) -> tuple[str, ...]:
    """Return valid private token candidates for one local Nuke port.

    Manifests and token sidecars are accepted only from the owner-controlled
    instances directory and only when both are regular, non-symlink files.
    Stale manifests can remain after a crash, so retain every distinct token
    in newest-manifest-first order for the client to try.
    """

    directory = manifests_dir()
    if not _secure_instances_dir(directory):
        return ()
    candidates: list[tuple[int, str, str]] = []
    for manifest in directory.glob("*.json"):
        if not _secure_file(manifest, mode=0o600):
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if int(payload.get("port")) != int(port):
                continue
            token_file = str(payload.get("token_file") or "").strip()
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            continue
        if not token_file:
            continue
        relative = Path(token_file)
        if relative.is_absolute() or relative.name != token_file:
            continue
        sidecar = directory / relative
        if not _secure_file(sidecar, mode=0o600):
            continue
        try:
            token = sidecar.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        if _valid_token(token):
            try:
                modified_ns = manifest.lstat().st_mtime_ns
            except OSError:
                continue
            candidates.append((modified_ns, manifest.name, token))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    tokens: list[str] = []
    for _modified_ns, _manifest_name, token in candidates:
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def bridge_token_for_port(port: int) -> Optional[str]:
    """Return the newest valid private token for one local Nuke port."""

    tokens = bridge_tokens_for_port(port)
    return tokens[0] if tokens else None
