#!/usr/bin/env python
"""Convert .hdalc → .hda via Houdini hython (Houdini_agent asset_tools 同款).

Usage:
  hython convert_hdalc_to_hda.py <source.hdalc> <output.hda>
"""
from __future__ import annotations

import sys

import hou


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: hython convert_hdalc_to_hda.py <source.hdalc> <output.hda>", file=sys.stderr)
        return 2
    source_path, output_path = sys.argv[1], sys.argv[2]
    print("loading definitions from", source_path)
    definitions = hou.hda.definitionsInFile(source_path)
    if not definitions:
        raise RuntimeError("No HDA definitions found in source file")
    print("saving", output_path, "from", definitions[0].nodeTypeName())
    definitions[0].save(file_name=output_path, template_node=None, options=hou.hdaSaveOptions())
    print("done", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
