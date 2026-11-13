"""Read-only native HOM probe tests using a non-Houdini fixture."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_probe():
    path = ROOT / "tools" / "probe_s06_native_api_evidence.py"
    spec = importlib.util.spec_from_file_location("s06_native_api_probe_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("probe could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ParmTemplate:
    def __init__(self, name, *, menu_items=(), children=(), dynamic=False):
        self._name = name
        self._menu_items = tuple(menu_items)
        self._children = tuple(children)
        self._dynamic = dynamic

    def name(self):
        return self._name

    def label(self):
        return self._name.title()

    def type(self):
        return "hou.parmTemplateType.Menu" if self._menu_items else "hou.parmTemplateType.String"

    def dataType(self):
        return "hou.parmData.String"

    def numComponents(self):
        return 1

    def namingScheme(self):
        return "hou.parmNamingScheme.Base1"

    def menuItems(self):
        return self._menu_items

    def menuLabels(self):
        return tuple(item.title() for item in self._menu_items)

    def menuUseToken(self):
        return True

    def defaultValueAsString(self):
        return self._menu_items[0] if self._menu_items else ""

    def itemGeneratorScript(self):
        return "return dynamic_items()" if self._dynamic else ""

    def itemGeneratorScriptLanguage(self):
        return "hou.scriptLanguage.Python"

    def tags(self):
        return {"units": "seconds", "item_generator_script": "must not be emitted"}

    def parmTemplates(self):
        return self._children


class _ParmTemplateGroup:
    def __init__(self, entries):
        self._entries = tuple(entries)

    def entries(self):
        return self._entries


class _NodeType:
    def __init__(self, name, category, entries):
        self._name = name
        self._category = category
        self._group = _ParmTemplateGroup(entries)

    def name(self):
        return self._name

    def nameComponents(self):
        return ("", "", self._name.split("::", 1)[0], self._name.split("::", 1)[1] if "::" in self._name else "")

    def category(self):
        return self._category

    def description(self):
        return "fixture native definition"

    def parmTemplateGroup(self):
        return self._group


class _Category:
    def __init__(self, name, node_types):
        self._name = name
        self._node_types = dict(node_types)

    def name(self):
        return self._name

    def nodeType(self, name):
        return self._node_types.get(name)


class _Connection:
    def __init__(self, input_node, output_node):
        self._input_node = input_node
        self._output_node = output_node

    def inputNode(self):
        return self._input_node

    def outputNode(self):
        return self._output_node

    def inputIndex(self):
        return 0

    def outputIndex(self):
        return 0

    def inputName(self):
        return "sourcing"

    def outputName(self):
        return "output"


class _Parm:
    def __init__(self):
        self._template = _ParmTemplate("operation", menu_items=("copy", "add"), dynamic=True)

    def evalAsString(self):
        return "add"

    def eval(self):
        return 1

    def menuItems(self):
        return ("copy", "add")

    def parmTemplate(self):
        return self._template


class _Node:
    def __init__(self, path, node_type):
        self._path = path
        self._type = node_type
        self._inputs = []
        self._connections = []
        self._parms = {"operation": _Parm()}

    def path(self):
        return self._path

    def type(self):
        return self._type

    def inputNames(self):
        return ("sourcing",)

    def inputLabels(self):
        return ("Sourcing",)

    def outputNames(self):
        return ("output",)

    def outputLabels(self):
        return ("Output",)

    def inputs(self):
        return tuple(self._inputs)

    def inputConnections(self):
        return tuple(self._connections)

    def parm(self, name):
        return self._parms.get(name)


class _Obj:
    def __init__(self, children):
        self._children = tuple(children)

    def children(self):
        return self._children


class _Hou:
    def __init__(self):
        self.dop = _Category("Dop", {})
        menu = _ParmTemplate("operation", menu_items=("copy", "add"), dynamic=True)
        solver_type = _NodeType("pyrosolver::2.0", self.dop, (menu,))
        self.dop._node_types["pyrosolver::2.0"] = solver_type
        self.solver = _Node("/obj/dopnet/solver", solver_type)
        source = _Node("/obj/dopnet/source", solver_type)
        self.solver._inputs = [source]
        self.solver._connections = [_Connection(source, self.solver)]
        self.obj = _Obj((self.solver,))

    def applicationVersionString(self):
        return "21.0.631"

    def nodeTypeCategories(self):
        return {"Dop": self.dop}

    def node(self, path):
        return {"/obj": self.obj, "/obj/dopnet/solver": self.solver, "/obj/dopnet/source": self.solver._inputs[0]}.get(path)


class NativeApiProbeTests(unittest.TestCase):
    def test_probe_collects_native_definitions_and_topology_without_mutation(self):
        probe = _load_probe()
        hou = _Hou()
        result = probe.capture(
            hou,
            node_type_queries=(("Dop", "pyrosolver::2.0"), ("Dop", "missing_type")),
            node_paths=("/obj/dopnet/solver",),
            parameter_readbacks={"/obj/dopnet/solver": ("operation",)},
            read_dynamic_menus=True,
        )
        definition, missing = result["node_type_definitions"]
        self.assertTrue(definition["found"])
        self.assertEqual(definition["name"], "pyrosolver::2.0")
        template = definition["parm_templates"][0]
        self.assertEqual(template["menu_items"], ["copy", "add"])
        self.assertTrue(template["dynamic_menu"])
        self.assertTrue(template["item_generator_sha256"])
        self.assertFalse(template["tags"].get("item_generator_script", False))
        self.assertFalse(missing["found"])
        self.assertEqual(missing["error"], "NODE_TYPE_NOT_FOUND")
        node = result["existing_nodes"][0]
        self.assertEqual(node["path"], "/obj/dopnet/solver")
        self.assertEqual(node["input_connections"][0]["input_index"], 0)
        self.assertEqual(node["input_connections"][0]["input_node"], "/obj/dopnet/source")
        self.assertEqual(result["parameter_readbacks"][0]["parameters"][0]["eval_as_string"], "add")
        self.assertEqual(result["parameter_readbacks"][0]["parameters"][0]["menu_items"], ["copy", "add"])
        self.assertEqual(result["custom_provider_observation"]["qualifies_as_sidefx_native"], False)
        self.assertFalse(result["read_only_contract"]["creates_nodes"])
        self.assertFalse(result["read_only_contract"]["sets_parameters"])
        self.assertFalse(result["read_only_contract"]["sets_frame"])
        self.assertFalse(result["read_only_contract"]["cooks"])


if __name__ == "__main__":
    unittest.main()
