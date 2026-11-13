#!/usr/bin/env python3
"""Compare real linear EXRs; this tool never renders or promotes visual acceptance."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT/'packages'/name/'src'))
from houdini_bridge.official_karma import compare_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--require-identical', action='store_true')
    args = parser.parse_args()
    result = compare_files(args.reference, args.candidate, require_identical=args.require_identical)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['state'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
