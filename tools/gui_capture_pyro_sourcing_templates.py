"""One-shot read-only GUI capture wrapper for a reviewed probe copy.

Paste the body into the Python Shell of an already authorized, empty Houdini
session only after the reviewed probe has been placed at PROBE_PATH. This
wrapper does not create nodes, read scene parameters, cook, cache, or render.
"""
from __future__ import annotations

import json
import os
import pathlib
import runpy

import hou


# Defaults resolve beside this script's repository; both may be overridden
# with GUI_CAPTURE_PROBE_PATH / GUI_CAPTURE_OUTPUT_PATH.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE_PATH = pathlib.Path(os.environ.get(
    'GUI_CAPTURE_PROBE_PATH', str(_REPO_ROOT / 'tools' / 'probe_pyro_sourcing_templates.py')))
OUTPUT_PATH = pathlib.Path(os.environ.get(
    'GUI_CAPTURE_OUTPUT_PATH', str(_REPO_ROOT / 'outputs' / 'gui-pyro-templates.json')))


probe = runpy.run_path(str(PROBE_PATH))
result = probe['capture'](hou)
OUTPUT_PATH.write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(result['capture_state'], str(OUTPUT_PATH))
