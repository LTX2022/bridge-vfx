#!/usr/bin/env python3
"""R09 logging wrapper: capture run provenance at START, returncode at END.

Every invocation records interpreter path/version, UTC timestamps, argv, cwd
and the input tree build hash into a provenance header, runs the target as a
child, appends the REAL shell returncode at the end, and never overwrites a
previous log (logs rotate with a timestamp suffix).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"__pycache__", ".pytest_cache", ".git", ".venv", ".DS_Store", "outputs", "delivery"}
BUILD_HASH_ALGORITHM = "sha256-posix-logical-path-v2"


def _scan_error(error):
    if not isinstance(error, PermissionError):
        raise error


def _source_files(root):
    if not isinstance(root, (str, os.PathLike)):
        yield from root.rglob("*")
        return
    for directory, children, names in os.walk(root, onerror=_scan_error):
        children[:] = [name for name in children if name not in EXCLUDED]
        for name in names:
            if name not in EXCLUDED:
                yield Path(directory) / name


def build_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(_source_files(root), key=lambda path: path.relative_to(root).as_posix()):
        if not path.is_file() or any(part in EXCLUDED for part in path.relative_to(root).parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--name", required=True, help="base name for the log file")
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"{args.name}-{stamp}.log"
    if log_path.exists():  # never overwrite a previous log
        log_path = log_dir / f"{args.name}-{stamp}-{os.getpid()}.log"

    started = datetime.now(timezone.utc)
    header = json.dumps({
        "provenance": "captured-at-start (R09); not reconstructed afterwards",
        "interpreter": sys.executable,
        "python_version": sys.version,
        "system": platform.platform(),
        "machine": platform.machine(),
        "utc_start": started.isoformat(),
        "argv": args.command,
        "cwd": os.getcwd(),
        "build_sha256": build_hash(ROOT),
        "build_sha256_algorithm": BUILD_HASH_ALGORITHM,
    }, ensure_ascii=False, indent=1)

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write("=== RUN PROVENANCE (start) ===\n")
        handle.write(header + "\n")
        handle.write("=== OUTPUT ===\n")
        handle.flush()
        completed = subprocess.run(args.command, stdout=handle, stderr=subprocess.STDOUT)
        ended = datetime.now(timezone.utc)
        handle.write("=== RUN PROVENANCE (end) ===\n")
        handle.write(json.dumps({
            "utc_end": ended.isoformat(),
            "wall_seconds": round((ended - started).total_seconds(), 3),
            "returncode": completed.returncode,
        }, ensure_ascii=False, indent=1) + "\n")
    print(log_path)
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
