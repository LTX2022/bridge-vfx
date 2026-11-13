"""Install the Nuke addon with an atomic, reversible init.py migration.

The installer only owns the marked ``nuke-bridge`` block. A legacy block from
the original bridge is recognized and replaced, while unrelated plugin lines
remain byte-for-byte intact. Every mutation gets a timestamped backup and a
SHA-256 manifest; a failed write restores the previous file automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from dcc_task_runtime.platform_support import atomic_write, remove_owned_path

BEGIN = "# >>> nuke-bridge >>>"
END = "# <<< nuke-bridge <<<"
LEGACY = "# nuke-bridge MCP addon"


def _nuke_dir(value: Optional[Path | str]) -> Path:
    return Path(value).expanduser() if value else Path(os.environ.get("NUKE_USER_DIR", Path.home() / ".nuke"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strip_marked_block(text: str) -> Tuple[str, bool]:
    """Remove one marked block and reject an unterminated marker."""
    start = text.find(BEGIN)
    if start < 0:
        return text, False
    end = text.find(END, start + len(BEGIN))
    if end < 0:
        raise RuntimeError("found an unterminated Nuke Bridge init.py block")
    end += len(END)
    return text[:start].rstrip() + "\n" + text[end:].lstrip("\n"), True


def _strip_legacy_block(text: str) -> Tuple[str, bool]:
    """Remove the old unmarked bridge block without eating later plugins."""
    lines = text.splitlines(keepends=True)
    # The pre-marker installer used a descriptive suffix ("- auto-starts ...")
    # after the legacy marker.  Match that prefix while keeping the marker
    # specific enough not to consume unrelated comments.
    start = next((index for index, line in enumerate(lines) if line.strip().startswith(LEGACY)), None)
    if start is None:
        return text, False
    end = start + 1
    control = ("if ", "elif ", "else:", "try:", "except", "finally:", "with ")
    bridge_token = re.compile(r"(?:nuke[-_]bridge|_nb_|_nuke_bridge|listener|nuke\.env|nuke\.tprint)", re.I)
    while end < len(lines):
        stripped = lines[end].strip()
        if not stripped:
            end += 1
            continue
        if lines[end][0].isspace():
            end += 1
            continue
        if stripped.startswith("#"):
            break
        if stripped.startswith(control) or bridge_token.search(stripped):
            end += 1
            continue
        break
    cleaned = "".join(lines[:start] + lines[end:])
    return cleaned, True


def _strip_block(text: str) -> str:
    """Compatibility helper retained for callers of the v1.3 installer."""
    cleaned, marked = _strip_marked_block(text)
    cleaned, legacy = _strip_legacy_block(cleaned)
    return cleaned if (marked or legacy) else text


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


def _backup_path(init_path: Path, backup_dir: Optional[Path | str], run_id: str) -> Path:
    root = Path(backup_dir).expanduser() if backup_dir else Path(os.environ.get("NUKE_BRIDGE_BACKUP_DIR", Path.cwd() / "outputs" / "backups"))
    return root / run_id / init_path.name


def _backup(init_path: Path, backup_dir: Optional[Path | str], run_id: str) -> Tuple[Path, Path]:
    destination = _backup_path(init_path, backup_dir, run_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    exists = init_path.is_file()
    if exists:
        destination.write_bytes(init_path.read_bytes())
        original_sha = _sha256(init_path)
    else:
        original_sha = None
    manifest = destination.parent / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "original_path": str(init_path),
                "original_exists": exists,
                "original_sha256": original_sha,
                "backup_path": str(destination) if exists else None,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination, manifest


def _atomic_write(path: Path, text: str) -> None:
    atomic_write(path, text.encode('utf-8'), owned_root=path.parent)


def install(plugin_root: Path | str, nuke_dir: Optional[Path | str] = None, backup_dir: Optional[Path | str] = None) -> Path:
    root = Path(plugin_root).expanduser().resolve()
    if not (root / "nuke_bridge_addon.py").is_file():
        raise FileNotFoundError(root / "nuke_bridge_addon.py")
    directory = _nuke_dir(nuke_dir)
    directory.mkdir(parents=True, exist_ok=True)
    init_path = directory / "init.py"
    original_bytes = init_path.read_bytes() if init_path.is_file() else b""
    original = original_bytes.decode("utf-8")
    cleaned, marked = _strip_marked_block(original)
    cleaned, legacy = _strip_legacy_block(cleaned)
    block = "\n".join(
        (
            BEGIN,
            "# Generated by nuke-bridge; only this block is managed by the installer.",
            "import sys as _nuke_bridge_sys",
            "import nuke as _nuke_bridge_nuke",
            f"_nuke_bridge_root = {str(root)!r}",
            "if _nuke_bridge_root not in _nuke_bridge_sys.path:",
            "    _nuke_bridge_sys.path.insert(0, _nuke_bridge_root)",
            "if _nuke_bridge_nuke.env.get('gui'):",
            "    import nuke_bridge_addon as _nuke_bridge_addon",
            "    _nuke_bridge_addon.autostart()",
            END,
            "",
        )
    )
    updated = cleaned.rstrip() + "\n\n" + block
    run_id = _run_id()
    backup, manifest = _backup(init_path, backup_dir, run_id)
    try:
        _atomic_write(init_path, updated)
        actual = _sha256(init_path)
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload.update({"new_sha256": actual, "marked_block_replaced": marked, "legacy_block_replaced": legacy})
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        if backup.is_file():
            _atomic_write(init_path, backup.read_text(encoding="utf-8"))
        elif init_path.exists():
            remove_owned_path(init_path, owned_root=init_path.parent)
        raise
    return init_path


def uninstall(nuke_dir: Optional[Path | str] = None, backup_dir: Optional[Path | str] = None) -> bool:
    init_path = _nuke_dir(nuke_dir) / "init.py"
    if not init_path.is_file():
        return False
    original = init_path.read_text(encoding="utf-8")
    cleaned, marked = _strip_marked_block(original)
    cleaned, legacy = _strip_legacy_block(cleaned)
    if not (marked or legacy):
        return False
    run_id = _run_id()
    backup, _manifest = _backup(init_path, backup_dir, run_id)
    try:
        _atomic_write(init_path, cleaned.rstrip() + "\n")
    except Exception:
        _atomic_write(init_path, backup.read_text(encoding="utf-8"))
        raise
    return True
