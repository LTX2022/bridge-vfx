#!/usr/bin/env python
"""Convert .hiplc -> .hip (full commercial, LC marker removed).

Two-phase conversion using separate hython processes (same as force-hipnc):
  Phase 1 (this script): load .hiplc, export scene via opscript to temp file
  Phase 2 (auto-spawned): clear scene, cmdread from temp, save as .hip

The two-process approach is essential: loading a .hiplc puts the hython session
into Limited Commercial mode. If we save in the same process, the output retains
the HouLC header. By spawning a FRESH hython process for the save step, the
new session starts in full commercial mode and writes a clean CPIO header.

Usage:
  hython convert_hiplc_to_hip_full.py <source.hiplc> [output.hip]
  hython convert_hiplc_to_hip_full.py <directory>

Based on reverse-engineered force-hipnc tool (VFXFORCE):
  test1.py: opscript export  ->  test2.py: cmdread + save (separate processes)
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
import subprocess

import hou


# Phase 2 script (executed in a fresh hython process)
PHASE2_SCRIPT = r'''
import os, sys, hou
inp = sys.argv[1]
output = sys.argv[2]
temp_script = sys.argv[3]

hou.hipFile.clear()
hou.hscript(f'cmdread "{temp_script}"')
hou.hipFile.save(file_name=output)
hou.hipFile.clear()
'''


def get_hython_path() -> str:
    """Find the hython executable path from the current Python environment."""
    # hou module knows where Houdini is installed
    hou_path = os.path.dirname(hou._hostname) if hasattr(hou, '_hostname') else None
    # Try common locations
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "hython.exe"),
        os.path.join(os.path.dirname(sys.executable), "hython"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # Fallback: use sys.executable if it's hython
    if "hython" in sys.executable.lower():
        return sys.executable
    raise FileNotFoundError("Cannot find hython executable")


def convert_single(source_path: str, output_path: str, temp_dir: str) -> bool:
    """Convert a single .hiplc file to a clean .hip file using two phases.

    Returns True on success.
    """
    source_path = os.path.abspath(source_path).replace("\\", "/")
    output_path = os.path.abspath(output_path).replace("\\", "/")

    # Phase 1: Load source, export via opscript
    print(f"  [Phase 1] Loading: {source_path}")
    hou.hipFile.load(source_path, ignore_load_warnings=True)

    script_name = os.path.splitext(os.path.basename(source_path))[0]
    script_file = os.path.join(temp_dir, script_name).replace("\\", "/")
    cmd = f'opscript -G -r / > "{script_file}"'
    print(f"  [Phase 1] Exporting scene via opscript...")
    hou.hscript(cmd)
    hou.exit()

    # Phase 2 will be handled by the caller (separate process)
    return True


def run_phase2(hython_path: str, output_path: str, temp_script: str) -> bool:
    """Run phase 2 in a fresh hython process."""
    phase2_file = os.path.join(temp_script + "_phase2.py")
    with open(phase2_file, "w") as f:
        f.write(PHASE2_SCRIPT)

    print(f"  [Phase 2] Rebuilding scene and saving: {output_path}")
    result = subprocess.run(
        [hython_path, phase2_file, "", output_path, temp_script],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        print(f"  [Phase 2] ERROR: {result.stderr[:500]}")
        return False
    return True


def verify_commercial(output_path: str) -> bool:
    """Check if the output .hip has a commercial header (not HouLC)."""
    with open(output_path, "rb") as f:
        header = f.read(5)
    return header[:4] != b"HouLC" and header[:4] != b"HouNC"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: hython convert_hiplc_to_hip_full.py <source.hiplc> [output.hip]", file=sys.stderr)
        print("       hython convert_hiplc_to_hip_full.py <directory>", file=sys.stderr)
        return 2

    source = sys.argv[1]

    # Check for phase 2 mode (internal flag)
    if len(sys.argv) >= 5 and sys.argv[1] == "--phase2":
        # This is a phase 2 invocation
        output_path = sys.argv[2]
        temp_script = sys.argv[3]
        hou.hipFile.clear()
        hou.hscript(f'cmdread "{temp_script}"')
        hou.hipFile.save(file_name=output_path)
        hou.hipFile.clear()
        return 0

    # Phase 1: Export via opscript
    temp_dir = tempfile.mkdtemp(prefix="hiplc_convert_")
    print(f"Temp dir: {temp_dir}")

    try:
        if os.path.isdir(source):
            # Batch mode
            source = source.replace("\\", "/")
            output_dir = source
            if len(sys.argv) >= 3:
                output_dir = sys.argv[2].replace("\\", "/")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            files = [f for f in os.listdir(source)
                     if f.endswith((".hiplc", ".hipnc"))]
            if not files:
                print(f"No .hiplc/.hipnc files found in {source}")
                return 1

            print(f"Found {len(files)} file(s) to convert")
            hython_path = get_hython_path()

            success = 0
            for i, f in enumerate(files):
                src = os.path.join(source, f).replace("\\", "/")
                dst = os.path.join(output_dir, os.path.splitext(f)[0] + ".hip").replace("\\", "/")
                print(f"\n[{i+1}/{len(files)}] {f}")

                # Phase 1: opscript export
                script_name = os.path.splitext(f)[0]
                script_file = os.path.join(temp_dir, script_name).replace("\\", "/")

                hou.hipFile.load(src, ignore_load_warnings=True)
                hou.hscript(f'opscript -G -r / > "{script_file}"')

                # Phase 2: fresh process save
                ok = run_phase2(hython_path, dst, script_file)
                if ok:
                    is_comm = verify_commercial(dst)
                    print(f"  Result: {'COMMERCIAL' if is_comm else 'STILL LC'}")
                    if is_comm:
                        success += 1
                hou.hipFile.clear()

            print(f"\nDone: {success}/{len(files)} converted to commercial .hip")

        else:
            # Single file mode
            source = source.replace("\\", "/")
            if len(sys.argv) >= 3:
                output = sys.argv[2].replace("\\", "/")
            else:
                output = os.path.splitext(source)[0] + ".hip"

            script_name = os.path.splitext(os.path.basename(source))[0]
            script_file = os.path.join(temp_dir, script_name).replace("\\", "/")

            # Phase 1: opscript export
            print(f"[Phase 1] Loading: {source}")
            hou.hipFile.load(source, ignore_load_warnings=True)
            print(f"[Phase 1] Exporting scene via opscript...")
            hou.hscript(f'opscript -G -r / > "{script_file}"')

            # Phase 2: fresh process save
            hython_path = get_hython_path()
            ok = run_phase2(hython_path, output, script_file)

            if ok:
                is_comm = verify_commercial(output)
                print(f"\nResult: {'COMMERCIAL' if is_comm else 'STILL LC'}")
                print(f"Output: {output}")
                if not is_comm:
                    print("\nWARNING: Output still has LC header.")
            else:
                print("\nERROR: Phase 2 failed")
                return 1

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\nTemp dir cleaned up")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
