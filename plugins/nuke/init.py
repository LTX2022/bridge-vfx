"""Nuke startup hook for the local bridge addon."""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import nuke_bridge_addon

nuke_bridge_addon.autostart()

