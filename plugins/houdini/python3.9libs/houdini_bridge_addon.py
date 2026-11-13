"""Python 3.9 Houdini entry point for the shared Bridge implementation."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_IMPLEMENTATION = Path(__file__).resolve().parents[1] / "_impl" / "houdini_bridge_addon.py"
_MODULE_NAME = "_houdini_bridge_impl"
_module = sys.modules.get(_MODULE_NAME)
if _module is None:
    _spec = spec_from_file_location(_MODULE_NAME, _IMPLEMENTATION)
    if _spec is None or _spec.loader is None:
        raise ImportError("cannot load Houdini Bridge implementation")
    _module = module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _module
    _spec.loader.exec_module(_module)

for _name, _value in vars(_module).items():
    if _name not in {"__name__", "__file__", "__package__", "__spec__"}:
        globals()[_name] = _value
