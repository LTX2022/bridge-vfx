#!/usr/bin/env python
"""Convert .hiplc → .hip via Houdini hython (Houdini_agent asset_tools 同款).

Usage:
  hython convert_hiplc_to_hip.py <source.hiplc> <output.hip>
"""
from __future__ import annotations

import sys

import hou


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: hython convert_hiplc_to_hip.py <source.hiplc> <output.hip>", file=sys.stderr)
        return 2
    source_path, output_path = sys.argv[1], sys.argv[2]
    print("loading", source_path)
    hou.hipFile.load(source_path, suppress_save_prompt=True)
    print("saving", output_path)
    hou.hipFile.save(file_name=output_path)
    print("done", hou.hipFile.path())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
