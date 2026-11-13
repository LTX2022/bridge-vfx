#!/usr/bin/env python3
"""Prepare the shipped DiskLight source contract using ordinary Python only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT/'packages'/name/'src'))
from houdini_bridge.official_karma import inspect_source, canonical_sha256


def inventory(example, expected):
    example = Path(example)
    if (not example.is_absolute() or example != example.resolve()
            or any(p.is_symlink() for p in (example, *example.parents)) or not example.is_dir()):
        raise ValueError('OFFICIAL_SOURCE_PLAIN_DIRECTORY_REQUIRED')
    actual = []
    for path in sorted(example.rglob('*')):
        if path.is_symlink():
            raise ValueError('OFFICIAL_SOURCE_SYMLINK_REFUSED')
        if path.is_file():
            before = path.stat()
            if before.st_size > 64*1024*1024:
                raise ValueError('OFFICIAL_SOURCE_BYTE_LIMIT')
            raw = path.read_bytes()
            after = path.stat()
            if (len(raw) != before.st_size or (before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError('OFFICIAL_SOURCE_CHANGED_DURING_READ')
            actual.append({'path': path.relative_to(example).as_posix(), 'size_bytes': len(raw),
                           'sha256': hashlib.sha256(raw).hexdigest()})
    if actual != expected:
        raise ValueError('OFFICIAL_SOURCE_INVENTORY_MISMATCH')
    return actual


def prepare(example, output_root):
    root = Path(output_root)
    if (not root.is_absolute() or root != root.resolve() or root.exists()
            or any(p.is_symlink() for p in (root, *root.parents))):
        raise ValueError('OFFICIAL_PREPARATION_FRESH_PLAIN_ROOT_REQUIRED')
    baseline = ROOT/'docs/official-baselines/karma/karma-21.0.631.json'
    original = json.loads(baseline.read_text(encoding='utf-8'))
    files = inventory(example, original['resource_inventory'])
    hip = Path(example)/'karma_user_guide.hip'
    contract = inspect_source(hip.read_bytes())
    root.mkdir(parents=True, mode=0o700)
    contract_raw = json.dumps(contract, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode()
    contract_path = root/'source-contract.json'
    with contract_path.open('xb') as stream:
        stream.write(contract_raw)
    report = {'schema': 'bridge.official-karma-source-preparation/1',
        'state': 'SOURCE_VERIFIED_RUNTIME_NOT_PREPARED', 'native_execution_status': 'NOT_RUN',
        'source_root': str(Path(example)), 'resource_inventory': files,
        'source_contract': {'path': str(contract_path), 'bytes': len(contract_raw),
                            'sha256': hashlib.sha256(contract_raw).hexdigest()},
        'source_contract_content_sha256': canonical_sha256(contract),
        'source_nodes': len(contract['nodes']), 'sop_nodes': contract['sop_count'],
        'execution_authorized': False, 'native_start_count': 0,
        'readiness': {'callback_review': 'REQUIRED', 'official_native_observer': 'NOT_IMPLEMENTED',
            'registered_graph_and_host': 'NOT_IMPLEMENTED', 'derived_input_sealing': 'NOT_IMPLEMENTED',
            'full_chain_runner': 'NOT_IMPLEMENTED', 'independent_implementation_review': 'PENDING'}}
    with (root/'preparation.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example-root', required=True)
    parser.add_argument('--output-root', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.example_root, args.output_root), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
