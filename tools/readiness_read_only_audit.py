#!/usr/bin/env python3
"""Automated read-only evidence integrity checks, not an independent review."""
import argparse
import json
from pathlib import Path
from readiness_evidence import build_id, validate_contract
ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--contract-evidence', type=Path)
    parser.add_argument('--full-log', type=Path, help='retained as an attachment only; log text cannot establish passing tests')
    args = parser.parse_args()
    errors = []
    if args.contract_evidence:
        try: errors.extend(validate_contract(json.loads(args.contract_evidence.read_text()), ROOT))
        except (OSError, ValueError) as exc: errors.append(str(exc))
    else: errors.append('executed contract evidence missing')
    index = ROOT/'outputs/live-validation/index.json'
    if not index.is_file(): errors.append('required live declaration missing')
    symlinks = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_symlink()]
    if symlinks: errors.append('source contains symlinks')
    payload = {'schema':'bridge.readiness.automated_checks/1','build_id':build_id(ROOT),
               'independent_review':False,'checks_passed':not errors,'errors':errors,
               'note':'A separate uninvolved reviewer must review behavior, native basis and test assertions.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    return 0 if not errors else 1

if __name__ == '__main__': raise SystemExit(main())
