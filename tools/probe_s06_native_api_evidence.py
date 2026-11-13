#!/usr/bin/env python3
"""Read-only SideFX HOM and node-definition evidence for S-06.

Run ``capture(hou)`` from Houdini's Python Shell, or pass the result to
``json.dumps`` yourself.  The probe does not create nodes, set parameters or
frames, cook, save, cache, render, or write any Houdini state.  It inspects
installed node-type definitions and existing network topology only.  Current
parameter values are read only when the caller supplies an explicit
``parameter_readbacks`` mapping; dynamic menu item evaluation additionally
requires ``read_dynamic_menus=True``.  No parameter name is guessed here.

This is a native SideFX evidence collector.  The project-specific
``hou.bridge_s06_native_adapter_v1`` object is reported separately and never
qualifies as a SideFX-native implementation.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections.abc import Iterable, Mapping
from typing import Any


SCHEMA = "bridge.f2.s06-native-api-evidence/1.0"
PROVIDER_ATTRIBUTE = "bridge_s06_native_adapter_v1"
PROVIDER_SCHEMA = "bridge.f2.s06-native-host-adapter/1.0"

# These names are taken from the Houdini 21.0.631 installed node-help
# definitions.  A missing entry is recorded as evidence; it is not replaced by
# a namespace guess or an unqualified type name.
DEFAULT_NODE_TYPE_QUERIES = (
    ("Dop", "pyrosolver::2.0"),
    ("Dop", "pyrosolver_sparse"),
    ("Dop", "volumesource"),
    ("Dop", "gasadvectfield::2.0"),
    ("Dop", "gasmatchfield"),
    ("Dop", "gascalculate"),
    ("Sop", "pyrosolver"),
    ("Sop", "pyrosource"),
)

HOM_CLASS_METHODS = {
    "Node": ("path", "type", "children", "allSubChildren", "inputs", "inputNames", "inputLabels", "inputConnections", "outputNames", "outputLabels"),
    "NodeType": ("name", "nameComponents", "category", "description", "parmTemplateGroup", "parmTemplates"),
    "NodeTypeCategory": ("name", "label", "nodeTypes", "nodeType"),
    "Parm": ("eval", "evalAsString", "menuItems", "parmTemplate"),
    "ParmTemplate": ("name", "label", "type", "dataType", "numComponents", "namingScheme", "tags"),
    "MenuParmTemplate": ("menuItems", "menuLabels", "menuUseToken", "defaultValueAsString", "itemGeneratorScript", "itemGeneratorScriptLanguage"),
    "ParmTemplateGroup": ("entries", "find", "findIndices"),
    "Geometry": ("prims", "prim", "primByName", "primTypeNames", "isReadOnly"),
    "Prim": ("type", "number", "intrinsicNames", "intrinsicValue", "intrinsicValueDict", "geometry"),
    "Volume": ("resolution", "voxelSize", "voxel", "sample", "allVoxels", "computeMin", "computeMax", "isSDF"),
    "DopNode": ("simulation",),
    "DopSimulation": ("findData", "findAllData", "objects", "time", "timestep"),
    "DopData": ("subData", "findSubData", "fieldGeometry", "geometry", "recordTypes", "record", "options"),
    "DopRecord": ("fieldNames", "field", "fieldAsString"),
    "NodeConnection": ("inputNode", "outputNode", "inputIndex", "outputIndex", "inputName", "outputName"),
    "OpNodeConnection": ("inputNode", "outputNode", "inputIndex", "outputIndex", "inputName", "outputName"),
}

HOM_FUNCTIONS = (
    "nodeTypeCategories",
    "nodeType",
    "node",
    "dopNodeTypeCategory",
    "sopNodeTypeCategory",
)


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _json_value(value: Any, *, depth: int = 0) -> Any:
    """Keep probe output bounded and JSON-compatible without executing hooks."""

    if depth > 5:
        return "<depth-limit>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item, depth=depth + 1)
            for key, item in list(value.items())[:256]
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item, depth=depth + 1) for item in list(value)[:256]]
    return _enum_text(value)


def _call(obj: Any, method: str, *args: Any) -> tuple[Any, str | None]:
    function = getattr(obj, method, None)
    if not callable(function):
        return None, "METHOD_MISSING"
    try:
        return function(*args), None
    except Exception as exc:  # pragma: no cover - Houdini-specific exceptions
        return None, type(exc).__name__


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_tags(template: Any) -> tuple[dict[str, Any] | None, str | None]:
    tags, error = _call(template, "tags")
    if error or not isinstance(tags, Mapping):
        return None, error
    blocked = {"script_callback", "script_callback_language", "item_generator_script"}
    output = {
        str(key): _json_value(value)
        for key, value in tags.items()
        if str(key).lower() not in blocked and "script" not in str(key).lower()
    }
    return output, None


def _capture_parm_template(template: Any, *, depth: int = 0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": None,
        "label": None,
        "type": None,
        "data_type": None,
        "num_components": None,
        "naming_scheme": None,
        "menu_items": None,
        "menu_labels": None,
        "menu_use_token": None,
        "default_value_as_string": None,
        "dynamic_menu": False,
        "item_generator_language": None,
        "item_generator_sha256": None,
        "tags": None,
    }
    for key, method in (
        ("name", "name"),
        ("label", "label"),
        ("type", "type"),
        ("data_type", "dataType"),
        ("num_components", "numComponents"),
        ("naming_scheme", "namingScheme"),
        ("menu_items", "menuItems"),
        ("menu_labels", "menuLabels"),
        ("menu_use_token", "menuUseToken"),
        ("default_value_as_string", "defaultValueAsString"),
    ):
        value, error = _call(template, method)
        if error is None:
            result[key] = _enum_text(value) if key in {"type", "data_type", "naming_scheme"} else _json_value(value)
    script, script_error = _call(template, "itemGeneratorScript")
    if script_error is None and isinstance(script, str) and script:
        result["dynamic_menu"] = True
        result["item_generator_sha256"] = _sha256_text(script)
    language, language_error = _call(template, "itemGeneratorScriptLanguage")
    if language_error is None:
        result["item_generator_language"] = _enum_text(language)
    tags, _tags_error = _safe_tags(template)
    result["tags"] = tags
    if depth >= 5:
        return result
    children, children_error = _call(template, "parmTemplates")
    if children_error is None and isinstance(children, Iterable) and not isinstance(children, (str, bytes, Mapping)):
        result["children"] = [
            _capture_parm_template(child, depth=depth + 1)
            for child in list(children)[:256]
        ]
    return result


def _capture_node_type(category: Any, category_name: str, type_name: str) -> dict[str, Any]:
    node_type, error = _call(category, "nodeType", type_name)
    result: dict[str, Any] = {
        "category_requested": category_name,
        "type_requested": type_name,
        "found": error is None and node_type is not None,
        "error": error,
        "name": None,
        "name_components": None,
        "category": None,
        "description": None,
        "parm_templates": [],
    }
    if node_type is None or error is not None:
        if error is None:
            result["error"] = "NODE_TYPE_NOT_FOUND"
        return result
    for key, method in (
        ("name", "name"),
        ("name_components", "nameComponents"),
        ("description", "description"),
    ):
        value, value_error = _call(node_type, method)
        if value_error is None:
            result[key] = _json_value(value)
    category_value, category_error = _call(node_type, "category")
    if category_error is None:
        result["category"] = _json_value(_call(category_value, "name")[0])
    group, group_error = _call(node_type, "parmTemplateGroup")
    if group_error is None:
        entries, entries_error = _call(group, "entries")
        if entries_error is None and isinstance(entries, Iterable) and not isinstance(entries, (str, bytes, Mapping)):
            result["parm_templates"] = [
                _capture_parm_template(template)
                for template in list(entries)[:512]
            ]
    if not result["parm_templates"]:
        templates, templates_error = _call(node_type, "parmTemplates")
        if templates_error is None and isinstance(templates, Iterable) and not isinstance(templates, (str, bytes, Mapping)):
            result["parm_templates"] = [
                _capture_parm_template(template)
                for template in list(templates)[:512]
            ]
    return result


def _connection_info(connection: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input_node": None,
        "output_node": None,
        "input_index": None,
        "output_index": None,
        "input_name": None,
        "output_name": None,
    }
    for key, method in (
        ("input_node", "inputNode"),
        ("output_node", "outputNode"),
        ("input_index", "inputIndex"),
        ("output_index", "outputIndex"),
        ("input_name", "inputName"),
        ("output_name", "outputName"),
    ):
        value, error = _call(connection, method)
        if error is not None:
            continue
        if key.endswith("_node"):
            path, path_error = _call(value, "path")
            result[key] = str(path) if path_error is None and path is not None else None
        else:
            result[key] = _json_value(value)
    return result


def _capture_node(node: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": None,
        "type": None,
        "category": None,
        "input_names": [],
        "input_labels": [],
        "output_names": [],
        "output_labels": [],
        "inputs": [],
        "input_connections": [],
    }
    path, error = _call(node, "path")
    if error is None:
        result["path"] = str(path)
    node_type, error = _call(node, "type")
    if error is None and node_type is not None:
        type_name, type_error = _call(node_type, "name")
        if type_error is None:
            result["type"] = str(type_name)
        category, category_error = _call(node_type, "category")
        if category_error is None:
            result["category"] = _json_value(_call(category, "name")[0])
    for key, method in (
        ("input_names", "inputNames"),
        ("input_labels", "inputLabels"),
        ("output_names", "outputNames"),
        ("output_labels", "outputLabels"),
    ):
        value, value_error = _call(node, method)
        if value_error is None and isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            result[key] = [_json_value(item) for item in list(value)[:256]]
    inputs, inputs_error = _call(node, "inputs")
    if inputs_error is None and isinstance(inputs, Iterable) and not isinstance(inputs, (str, bytes, Mapping)):
        input_paths = []
        for item in list(inputs)[:256]:
            item_path, item_error = _call(item, "path") if item is not None else (None, None)
            input_paths.append(str(item_path) if item_error is None and item_path is not None else None)
        result["inputs"] = input_paths
    connections, connections_error = _call(node, "inputConnections")
    if connections_error is None and isinstance(connections, Iterable) and not isinstance(connections, (str, bytes, Mapping)):
        result["input_connections"] = [_connection_info(item) for item in list(connections)[:256]]
    return result


def _discover_nodes(hou: Any, explicit_paths: Iterable[str], *, discover_obj: bool, max_nodes: int) -> tuple[list[Any], list[str]]:
    candidates: list[Any] = []
    requested = [str(path) for path in explicit_paths]
    for path in requested:
        node, error = _call(hou, "node", path)
        if error is None and node is not None:
            candidates.append(node)
    if discover_obj:
        obj, error = _call(hou, "node", "/obj")
        if error is None and obj is not None:
            children, children_error = _call(obj, "children")
            if children_error is None and isinstance(children, Iterable) and not isinstance(children, (str, bytes, Mapping)):
                for child in list(children)[:max_nodes]:
                    candidates.append(child)
                    subchildren, sub_error = _call(child, "allSubChildren")
                    if sub_error is None and isinstance(subchildren, Iterable) and not isinstance(subchildren, (str, bytes, Mapping)):
                        candidates.extend(list(subchildren)[:max_nodes])
    result: list[Any] = []
    seen: set[str] = set()
    for node in candidates:
        path, error = _call(node, "path")
        key = str(path) if error is None and path is not None else "<unaddressable:{}>".format(id(node))
        if key in seen:
            continue
        seen.add(key)
        result.append(node)
        if len(result) >= max_nodes:
            break
    return result, requested


def _capture_parameter_readbacks(
    hou: Any,
    parameter_readbacks: Mapping[str, Iterable[str]] | None,
    *,
    read_dynamic_menus: bool,
) -> list[dict[str, Any]]:
    if not isinstance(parameter_readbacks, Mapping):
        return []
    output: list[dict[str, Any]] = []
    for node_path, names in parameter_readbacks.items():
        node, node_error = _call(hou, "node", str(node_path))
        if node_error is not None or node is None:
            output.append({"node_path": str(node_path), "error": node_error or "NODE_NOT_FOUND", "parameters": []})
            continue
        rows: list[dict[str, Any]] = []
        for name in list(names)[:128]:
            parm, parm_error = _call(node, "parm", str(name))
            row: dict[str, Any] = {"name": str(name), "found": parm_error is None and parm is not None}
            if parm is None or parm_error is not None:
                row["error"] = parm_error or "PARM_NOT_FOUND"
                rows.append(row)
                continue
            methods = [("eval_as_string", "evalAsString"), ("eval", "eval")]
            if read_dynamic_menus:
                methods.append(("menu_items", "menuItems"))
            for key, method in methods:
                value, error = _call(parm, method)
                if error is None:
                    row[key] = _json_value(value)
            template, template_error = _call(parm, "parmTemplate")
            if template_error is None and template is not None:
                row["template"] = _capture_parm_template(template)
            rows.append(row)
        output.append({"node_path": str(node_path), "error": None, "parameters": rows})
    return output


def _api_surface(hou: Any) -> dict[str, Any]:
    classes: dict[str, Any] = {}
    for class_name, methods in HOM_CLASS_METHODS.items():
        cls = getattr(hou, class_name, None)
        classes[class_name] = {
            "available": cls is not None,
            "callable_methods": [method for method in methods if callable(getattr(cls, method, None))] if cls is not None else [],
            "missing_methods": [method for method in methods if not callable(getattr(cls, method, None))] if cls is not None else list(methods),
        }
    return {
        "module_functions": {
            name: {"available": callable(getattr(hou, name, None))}
            for name in HOM_FUNCTIONS
        },
        "classes": classes,
    }


def capture(
    hou: Any,
    *,
    node_type_queries: Iterable[tuple[str, str]] = DEFAULT_NODE_TYPE_QUERIES,
    node_paths: Iterable[str] = (),
    discover_obj: bool = True,
    max_nodes: int = 256,
    parameter_readbacks: Mapping[str, Iterable[str]] | None = None,
    read_dynamic_menus: bool = False,
) -> dict[str, Any]:
    """Capture native definitions and topology without any host mutation."""

    node_paths = tuple(node_paths)
    version_getter = getattr(hou, "applicationVersionString", None)
    version = str(version_getter()) if callable(version_getter) else None
    categories, categories_error = _call(hou, "nodeTypeCategories")
    category_map = categories if categories_error is None and isinstance(categories, Mapping) else {}
    definitions: list[dict[str, Any]] = []
    for category_name, type_name in list(node_type_queries)[:64]:
        category = category_map.get(category_name)
        if category is None:
            definitions.append({
                "category_requested": category_name,
                "type_requested": type_name,
                "found": False,
                "error": "NODE_TYPE_CATEGORY_NOT_FOUND",
                "parm_templates": [],
            })
            continue
        definitions.append(_capture_node_type(category, str(category_name), str(type_name)))
    nodes, requested_paths = _discover_nodes(
        hou, node_paths, discover_obj=bool(discover_obj), max_nodes=max(1, int(max_nodes)),
    )
    provider = getattr(hou, PROVIDER_ATTRIBUTE, None)
    provider_schema = getattr(provider, "schema", None) if provider is not None else None
    if callable(provider_schema):
        try:
            provider_schema = provider_schema()
        except Exception:
            provider_schema = None
    provider_interfaces = [
        name for name in (
            "field_snapshot",
            "apply_velocity_sentinel",
            "velocity_writer_inventory",
            "observe_sourcing_boundary",
        )
        if provider is not None and callable(getattr(provider, name, None))
    ]
    provider_capabilities = None
    provider_capabilities_error = None
    if provider is not None:
        capabilities_getter = getattr(provider, "capabilities", None)
        if not callable(capabilities_getter):
            provider_capabilities_error = "PROVIDER_CAPABILITIES_METHOD_MISSING"
        else:
            try:
                candidate = capabilities_getter()
                if isinstance(candidate, dict):
                    provider_capabilities = candidate
                else:
                    provider_capabilities_error = "PROVIDER_CAPABILITIES_NOT_OBJECT"
            except Exception as exc:
                provider_capabilities_error = "PROVIDER_CAPABILITIES_ERROR:{}".format(type(exc).__name__)
    mutation_ready = bool(
        provider_schema == PROVIDER_SCHEMA
        and len(provider_interfaces) == 4
        and isinstance(provider_capabilities, dict)
        and provider_capabilities.get("ready_for_mutation") is True
    )
    return {
        "schema": SCHEMA,
        "capture_state": "READ_ONLY_NATIVE_API_PROBE",
        "houdini_version": version,
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
        },
        "native_api_surface": _api_surface(hou),
        "node_type_definitions": definitions,
        "existing_nodes": [_capture_node(node) for node in nodes],
        "requested_node_paths": requested_paths,
        "parameter_readbacks": _capture_parameter_readbacks(
            hou, parameter_readbacks, read_dynamic_menus=bool(read_dynamic_menus),
        ),
        "dynamic_menu_readback_requested": bool(read_dynamic_menus),
        "custom_provider_observation": {
            "attribute": PROVIDER_ATTRIBUTE,
            "reported_schema": provider_schema if isinstance(provider_schema, str) else None,
            "available_interfaces": provider_interfaces,
            "provider_capabilities": provider_capabilities,
            "provider_capabilities_error": provider_capabilities_error,
            "mutation_ready": mutation_ready,
            "status": "OBSERVED_CUSTOM_SEAM_ONLY",
            "qualifies_as_sidefx_native": False,
        },
        "read_only_contract": {
            "creates_nodes": False,
            "writes_scene": False,
            "reads_existing_node_graph": bool(discover_obj or tuple(node_paths)),
            "reads_existing_scene_parameters": bool(parameter_readbacks),
            "reads_existing_simulation_data": False,
            "sets_parameters": False,
            "sets_frame": False,
            "cooks": False,
            "writes_cache": False,
            "renders": False,
            "saves": False,
        },
        "not_collected_by_design": {
            "sentinel_write_readback": "requires_explicit_construction_experiment",
            "writer_effect_inventory": "requires_existing_network_semantics_or_construction_experiment",
            "sourcing_boundary": "requires_write_refresh_and_before_after_readback_experiment",
            "smoke_capability": "not_proven_by_this_probe",
        },
    }


if __name__ == "__main__":
    try:
        import hou  # type: ignore
    except ImportError:
        raise SystemExit("Run this script from Houdini's Python Shell with hou available")
    print(json.dumps(capture(hou), ensure_ascii=False, indent=2, sort_keys=True))
