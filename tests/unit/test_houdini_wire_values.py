import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_houdini_http_security import _load, ADDON


class Ramp:
    def keys(self): return (0.0, 1.0)
    def values(self): return (0.2, 0.8)
    def basis(self): return ("Linear", "Linear")


class HoudiniWireValueTests(unittest.TestCase):
    def test_parameter_ramps_are_json_data_not_connection_failures(self):
        addon = _load("_houdini_wire_values", ADDON)
        node = SimpleNamespace(path=lambda: "/obj/test/pyro", parms=lambda: [
            SimpleNamespace(name=lambda: "ramp", eval=lambda: Ramp()),
        ])
        with patch.dict("sys.modules", {"hou": SimpleNamespace()}), patch.object(addon, "_node", return_value=node):
            payload = addon.dispatch("node.parms", {"path": node.path()})
        wire = json.loads(json.dumps(payload))
        self.assertEqual(wire["parms"]["ramp"]["type"], "ramp")
        self.assertEqual(wire["parms"]["ramp"]["values"], [0.2, 0.8])
