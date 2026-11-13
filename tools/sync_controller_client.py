#!/usr/bin/env python3
"""Check or synchronize controller clients from their authoritative packages."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {'dcc_task_runtime': 'dcc-task-runtime', 'houdini_bridge': 'houdini-bridge'}


def synchronize(root: Path, *, write: bool = False) -> list[dict[str, str]]:
    root = Path(root).resolve()
    changes = []
    for module, package in PACKAGES.items():
        source = root / 'packages' / package / 'src' / module
        target = root / 'controller-entry' / 'client' / module
        if not source.is_dir():
            raise ValueError('missing source package: ' + str(source))
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('controller client must not traverse a symlink')
        wanted = {p.relative_to(source): p for p in source.rglob('*.py')}
        present = {p.relative_to(target): p for p in target.rglob('*.py')}
        for name in sorted(set(wanted) | set(present)):
            src = wanted.get(name); dst = target / name
            if dst.is_symlink() or (src is not None and src.is_symlink()):
                raise ValueError('client module must not be a symlink')
            if src is None:
                changes.append({'path': dst.relative_to(root).as_posix(), 'action': 'remove_extra'})
                if write: dst.unlink()
            elif not dst.is_file() or dst.read_bytes() != src.read_bytes():
                changes.append({'path': dst.relative_to(root).as_posix(), 'action': 'copy_source'})
                if write:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='apply changes; default only checks')
    args = parser.parse_args()
    changes = synchronize(ROOT, write=args.write)
    remaining = synchronize(ROOT) if args.write else changes
    print(json.dumps({'mode': 'write' if args.write else 'check', 'changes': changes,
                      'synchronized': not remaining}, indent=2))
    return 1 if remaining else 0

if __name__ == '__main__':
    raise SystemExit(main())
