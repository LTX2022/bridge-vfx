"""Houdini package-file installation without touching houdini.env."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Iterable, List, Optional, Union

from dcc_task_runtime.platform_support import atomic_write, open_private_file, remove_owned_path, set_private_permissions
from .paths import approval_secret_path, package_directories


PACKAGE_FILENAME = "houdini_bridge.json"


def ensure_approval_secret(path: Optional[Union[Path, str]] = None) -> Path:
    """Create the shared HMAC key once with owner-only permissions."""
    target = Path(path).expanduser() if path is not None else approval_secret_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = open_private_file(target)
    except FileExistsError:
        if not target.is_file() or target.is_symlink():
            raise RuntimeError("approval secret path must be a regular file: {}".format(target))
    else:
        try:
            os.write(descriptor, (secrets.token_hex(32) + "\n").encode("ascii"))
        finally:
            os.close(descriptor)
    set_private_permissions(target)
    value = target.read_text(encoding="ascii").strip()
    if len(value) < 32:
        raise RuntimeError("approval secret file is empty or too short: {}".format(target))
    return target


def _write_package(source: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    package_file = target_dir / PACKAGE_FILENAME
    payload = {
        "path": str(source),
        "enable": True,
        "load_package_once": True,
        "env": [{"HOUDINI_BRIDGE_ROOT": str(source)}],
    }
    atomic_write(package_file, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode('utf-8'),
                 owned_root=target_dir)
    return package_file


def install_all(plugin_root: Union[Path, str], directories: Iterable[Union[Path, str]]) -> List[Path]:
    source = Path(plugin_root).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    ensure_approval_secret()
    return [_write_package(source, Path(directory).expanduser()) for directory in directories]


def install(plugin_root: Union[Path, str], packages_dir: Optional[Union[Path, str]] = None) -> Path:
    """Install one explicit package directory or both supported versions.

    The historical API returned one path, so this function keeps that contract
    and returns the first file.  ``install_all`` is used by the CLI when the
    default 21.0/22.0 matrix is requested.
    """
    directories = [Path(packages_dir).expanduser()] if packages_dir else package_directories()
    if not directories:
        raise RuntimeError("could not resolve a Houdini packages directory")
    return install_all(plugin_root, directories)[0]


def uninstall(packages_dir: Optional[Union[Path, str]] = None) -> bool:
    directories = [Path(packages_dir).expanduser()] if packages_dir else package_directories()
    removed = False
    for target_dir in directories:
        package_file = target_dir / PACKAGE_FILENAME
        if package_file.is_file():
            remove_owned_path(package_file, owned_root=target_dir)
            removed = True
    return removed
