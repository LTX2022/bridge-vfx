from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "tools" / "scan_node_types.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("_houdini_node_scan", SCANNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load node scanner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Category:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _NodeType:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _Node:
    def __init__(self, path: str, node_type: str = "network") -> None:
        self._path = path
        self._node_type = node_type

    def path(self) -> str:
        return self._path

    def type(self) -> _NodeType:
        return _NodeType(self._node_type)

    def isValid(self) -> bool:  # noqa: N802
        return True

    def destroy(self) -> None:
        return None

    def createNode(self, node_type: str, name: str, **_kwargs):  # noqa: N802
        if node_type == "geo" and self._path == "/obj":
            return _Node("/obj/" + name, "geo")
        if node_type == "dopnet" and self._path.startswith("/obj/"):
            return _Node(self._path + "/" + name, "dopnet")
        # The regression: category lookup says missing, but a real DOP parent
        # accepts the operator name.  The scan must record both observations.
        if node_type == "parent_only" and self._path.endswith("/DOP_PARENT"):
            return _Node(self._path + "/" + name, "parent_only")
        raise RuntimeError("not valid in this parent")


class _Hou:
    def __init__(self) -> None:
        self.categories = {name: _Category(name) for name in ("Sop", "Object", "Dop", "Lop", "Vop", "Top")}
        self.nodes = {
            "/obj": _Node("/obj"),
            "/stage": _Node("/stage"),
            "/mat": _Node("/mat"),
            "/tasks": _Node("/tasks"),
        }

    def nodeTypeCategories(self):  # noqa: N802
        return self.categories

    def node(self, path: str):
        return self.nodes.get(path)

    def nodeType(self, _category, _name):  # noqa: N802
        return None

    def applicationVersionString(self) -> str:  # noqa: N802
        return "unit-build"

    def __getattr__(self, name: str):
        if name.endswith("NodeTypeCategory"):
            short = name[: -len("NodeTypeCategory")]
            title = {"sop": "Sop", "obj": "Object", "dop": "Dop", "lop": "Lop", "vop": "Vop", "top": "Top"}[short]
            return lambda: self.categories[title]
        raise AttributeError(name)


class ParentCreateScannerTests(unittest.TestCase):
    def test_lookup_missing_name_is_still_tried_in_real_parents(self) -> None:
        scanner = _load_scanner()
        original = scanner.git_state
        scanner.git_state = lambda: ("a" * 40, "b" * 64)
        try:
            payload = scanner.scan_node_types(_Hou(), names=["parent_only"])
        finally:
            scanner.git_state = original
        observations = payload["node_types"]["parent_only"]
        dop = next(item for item in observations if item["context"] == "dop")
        self.assertFalse(dop["resolved"])
        self.assertTrue(dop["created"])
        self.assertEqual(dop["created_type"], "parent_only")
        self.assertEqual(len(observations), 6)
        self.assertEqual(payload["probe_level"], "node_type_scan")


if __name__ == "__main__":
    unittest.main()
