"""Read bounded composed USD observations, without deciding output metadata readiness."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Set
from typing import Any
from houdini_bridge.render_observation_budget import RenderObservationLimit as _ObservationLimit

SCHEMA = "bridge.houdini.render-color-facts/1.0"
MAX_TARGETS = 128
MAX_TRAVERSED_TARGETS = 128
MAX_FILTER_ATTRIBUTES = 64
MAX_STRING_LENGTH = 8192
MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
MAX_OBSERVATION_VALUES = 32768
INTEGER_RANGES = {
    "int": (-(2**31), 2**31 - 1), "int64": (-(2**63), 2**63 - 1),
    "uint": (0, 2**32 - 1), "uint64": (0, 2**64 - 1),
}
FLOAT_LIMITS = {"float": 3.4028234663852886e38, "double": 1.7976931348623157e308}
SCALAR_TYPES = {"string", "token", "asset", "bool", *INTEGER_RANGES, *FLOAT_LIMITS}

SETTINGS_ATTRIBUTES = {"renderingColorSpace": "token", "husk:delegate": None}
PRODUCT_ATTRIBUTES = {
    "productName": "token", "productType": "token",
    "driver:parameters:husk:source_colorspace": "string",
    "driver:parameters:husk:output_colorspace": "string",
}
VAR_ATTRIBUTES = {
    "sourceName": "string",
    "sourceType": ("token", "string"),
    "dataType": "token",
    "driver:parameters:aov:husk:name": "string",
    "driver:parameters:aov:husk:format": "token",
    "driver:parameters:aov:husk:source_colorspace": "string",
    "driver:parameters:aov:husk:output_colorspace": "string",
    "driver:parameters:aov:husk:channel_prefix": "string",
    "driver:parameters:aov:husk:channel_lower_rgb": "bool",
    "driver:parameters:aov:karma:filter": "string",
}


class _SequenceLimit(ValueError):
    pass


class _Budget:
    """Conservative capture charges bound work; final encoding checks the full fact."""
    def __init__(self, operation_budget=None):
        self.bytes = 0
        self.values = 0
        self.operation_budget = operation_budget

    def reserve(self, byte_count: int, value_count: int = 1) -> None:
        self.bytes += byte_count
        self.values += value_count
        if self.bytes > MAX_OBSERVATION_BYTES or self.values > MAX_OBSERVATION_VALUES:
            raise _ObservationLimit("render color observation budget exceeded")
        if self.operation_budget is not None:
            self.operation_budget.reserve_color(byte_count, value_count)

    def scalar(self, value: Any) -> Any:
        if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
            raise _ObservationLimit("render color observation budget exceeded: native text")
        self.reserve(len(json.dumps(value, allow_nan=False).encode("utf-8")))
        return value

    def finish(self, facts: dict[str, Any]) -> dict[str, Any]:
        size = 0
        for chunk in json.JSONEncoder(allow_nan=False).iterencode(facts):
            size += len(chunk.encode("utf-8"))
            if size > MAX_OBSERVATION_BYTES:
                raise _ObservationLimit("render color observation budget exceeded")
        return facts


def _native_error(error: Exception) -> str:
    name = type(error).__name__
    if len(name) > 128:
        name = "Exception"
    return name + ": native read failed; exception body omitted"


def _sequence(value: Any, limit: int) -> int:
    if isinstance(value, (str, bytes, bytearray, Mapping, Set)):
        raise ValueError("expected an ordered USD sequence")
    size = len(value)
    if size > limit:
        raise _SequenceLimit("oversized USD sequence")
    if not hasattr(value, "__getitem__"):
        raise ValueError("unsupported or oversized USD sequence")
    return size


def _path(value: Any, *, allow_property: bool = False, budget: _Budget | None = None) -> str:
    if isinstance(value, str):
        path = _value(value, "string", budget)
        prim_path, separator, property_name = path.partition(".")
        valid = (prim_path.startswith("/") and
                 all(component.isidentifier() for component in prim_path[1:].split("/")))
        if separator:
            valid = (valid and allow_property and
                     all(component.isidentifier() for component in property_name.split(":")))
    else:
        path = _value(str(value), "string", budget)
        valid = (value.IsAbsolutePath() and not value.ContainsPrimVariantSelection() and
                 (value.IsPrimPath() or (allow_property and value.IsPrimPropertyPath())))
    if not valid:
        raise ValueError("expected an absolute USD " + ("prim or property" if allow_property else "prim") + " path")
    return path


def _value(value: Any, type_name: str, budget: _Budget | None = None) -> Any:
    if type_name.endswith("[]"):
        element_type = type_name[:-2]
        if element_type not in SCALAR_TYPES:
            raise ValueError("unsupported USD array element type: " + element_type)
        size = _sequence(value, MAX_TARGETS)
        if budget is not None:
            budget.reserve(2 + 2 * size, size + 1)
        return [_value(value[index], element_type, budget) for index in range(size)]
    if type_name in {"string", "token"}:
        if not isinstance(value, str) or len(value) > MAX_STRING_LENGTH:
            raise ValueError("unsupported or oversized USD string")
        return budget.scalar(value) if budget is not None else value
    if type_name == "asset":
        if not isinstance(value.path, str) or not isinstance(value.resolvedPath, str):
            raise ValueError("invalid USD asset path")
        if budget is not None:
            budget.reserve(40, 3)
        return {"path": _value(value.path, "string", budget),
                "resolved_path": _value(value.resolvedPath, "string", budget)}
    if type_name == "bool" and type(value) is bool:
        return budget.scalar(value) if budget is not None else value
    if type_name in INTEGER_RANGES and type(value) is int:
        minimum, maximum = INTEGER_RANGES[type_name]
        if minimum <= value <= maximum:
            return budget.scalar(value) if budget is not None else value
    if type_name in FLOAT_LIMITS and type(value) in {int, float}:
        maximum = FLOAT_LIMITS[type_name]
        if -maximum <= value <= maximum and math.isfinite(value):
            return budget.scalar(value) if budget is not None else value
    raise ValueError("unsupported USD type/value: " + type_name)


def collect_render_color_facts(stage: Any, *, frame: float,
                               settings_path: str, operation_budget=None) -> dict[str, Any]:
    """Read the composed stage without mutation; over-budget capture raises ValueError.

    Native API return materialization (notably GetAttributes) occurs before Python
    can enforce these bounds. Only checked, bounded indexed capture follows it.
    """
    if type(frame) not in {int, float} or not math.isfinite(frame):
        raise ValueError("frame must be a finite USD time code")
    if not isinstance(settings_path, str):
        raise ValueError("settings_path must be an absolute USD prim path")
    budget = _Budget(operation_budget)
    _path(settings_path, budget=budget)
    budget.reserve(256, 10)
    facts: dict[str, Any] = {"schema": SCHEMA, "frame": frame,
                            "settings_path": settings_path, "settings": None,
                            "products": [], "missing_facts": []}
    missing = facts["missing_facts"]
    traversed_targets = 0

    def gap(code: str, path: str, detail: str) -> None:
        budget.reserve(48, 4)
        for text in (code, path, detail):
            budget.scalar(text)
        missing.append({"code": code, "path": path, "detail": detail})

    def attributes(prim: Any, names: dict[str, Any], path: str) -> dict[str, Any]:
        observations = {}
        for name, expected_type in names.items():
            budget.reserve(128, 8)
            budget.scalar(name)
            property_path = path + "." + name
            observation = {"present": False}
            observations[name] = observation
            try:
                attribute = prim.GetAttribute(name)
                if not attribute:
                    gap("ATTRIBUTE_MISSING", property_path, "no composed USD attribute")
                    continue
                observation["present"] = True
                if budget.scalar(str(attribute.GetName())) != name:
                    gap("ATTRIBUTE_PATH_MISMATCH", property_path, "resolved attribute name differs from requested name")
                    continue
                type_name = budget.scalar(str(attribute.GetTypeName()))
                observation["type_name"] = type_name
                observation["authored"] = _value(attribute.HasAuthoredValueOpinion(), "bool", budget)
                if expected_type is not None:
                    allowed = (expected_type,) if isinstance(expected_type, str) else expected_type
                    if type_name not in allowed:
                        gap("ATTRIBUTE_TYPE_UNSUPPORTED", property_path,
                            "expected " + "/".join(allowed) + "; observed " + type_name)
                        continue
                value = attribute.Get(frame)
                if value is None:
                    gap("ATTRIBUTE_VALUE_MISSING", property_path, "Get(frame) returned None")
                    continue
                if isinstance(value, str) and value == "":
                    gap("ATTRIBUTE_VALUE_EMPTY", property_path, "empty composed value")
                    continue
                observation["value"] = _value(value, type_name, budget)
            except _ObservationLimit:
                raise
            except (ValueError, TypeError, AttributeError) as error:
                gap("ATTRIBUTE_TYPE_UNSUPPORTED", property_path, _native_error(error))
            except Exception as error:
                gap("ATTRIBUTE_READ_FAILED", property_path, _native_error(error))
        return observations

    def target_paths(targets: Any, *, allow_property: bool) -> list[str]:
        size = _sequence(targets, MAX_TARGETS)
        budget.reserve(2 + 2 * size, size + 1)
        paths = [_path(targets[index], allow_property=allow_property, budget=budget)
                 for index in range(size)]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate composed relationship targets; traversal refused")
        return paths

    def relationship(prim: Any, name: str, path: str, *, required: bool = True) -> dict[str, Any]:
        budget.reserve(128, 8)
        observation: dict[str, Any] = {"present": False, "targets": [],
                                        "forwarded_targets": []}
        property_path = path + "." + name
        try:
            relation = prim.GetRelationship(name)
            if not relation:
                if required:
                    gap("RELATIONSHIP_MISSING", property_path, "no composed USD relationship")
                return observation
            observation["present"] = True
            raw_targets = relation.GetTargets()
            observation["targets"] = target_paths(raw_targets, allow_property=True)
            targets = relation.GetForwardedTargets()
            observation["forwarded_targets"] = target_paths(targets, allow_property=False)
            if not observation["forwarded_targets"] and required:
                gap("RELATIONSHIP_EMPTY", property_path, "no composed forwarded targets")
        except _ObservationLimit:
            raise
        except _SequenceLimit:
            gap("RELATIONSHIP_LIMIT", property_path, "more than 128 targets; traversal refused")
        except Exception as error:
            gap("RELATIONSHIP_READ_FAILED", property_path, _native_error(error))
        return observation

    def traversal_targets(relation: dict[str, Any], property_path: str):
        nonlocal traversed_targets
        for target in relation["forwarded_targets"]:
            if traversed_targets >= MAX_TRAVERSED_TARGETS:
                gap("TRAVERSAL_LIMIT", property_path, "128 total targets reached; remaining traversal refused")
                break
            traversed_targets += 1
            yield target

    def read_prim(path: str, expected_type: str | None) -> Any:
        budget.reserve(256, 10)
        budget.scalar(path)
        try:
            prim = stage.GetPrimAtPath(path)
            if not prim or not _value(prim.IsActive(), "bool"):
                gap("PRIM_MISSING", path, "target is absent or inactive")
                return None
            type_name = budget.scalar(str(prim.GetTypeName()))
            if expected_type is not None and type_name != expected_type:
                gap("PRIM_TYPE_UNSUPPORTED", path,
                    "expected " + expected_type + "; observed " + type_name)
                return None
            if budget.scalar(str(prim.GetPath())) != path:
                gap("PRIM_PATH_MISMATCH", path, "resolved prim path differs from relationship target")
                return None
            return prim, type_name
        except _ObservationLimit:
            raise
        except Exception as error:
            gap("PRIM_READ_FAILED", path, _native_error(error))
            return None

    def filters(prim: Any, path: str) -> dict[str, Any]:
        relation = relationship(prim, "husk:orderedImageFilters", path, required=False)
        result = {"relationship": relation, "ordered_filters": []}
        if not relation["present"]:
            result["attribute"] = attributes(prim, {"husk:orderedImageFilters": None}, path)["husk:orderedImageFilters"]
            if result["attribute"]["present"]:
                gap("FILTER_PROPERTY_SEMANTICS_UNRESOLVED", path + ".husk:orderedImageFilters",
                    "attribute value preserved; no undocumented conversion into prim targets")
            return result
        for target in traversal_targets(relation, path + ".husk:orderedImageFilters"):
            resolved_filter = read_prim(target, None)
            if resolved_filter is None:
                continue
            filter_prim, type_name = resolved_filter
            observation = {"path": target, "type_name": type_name}
            result["ordered_filters"].append(observation)
            try:
                native_attributes = filter_prim.GetAttributes()
                size = _sequence(native_attributes, MAX_FILTER_ATTRIBUTES)
                budget.reserve(2 + 2 * size, size + 1)
                names = {budget.scalar(str(native_attributes[index].GetName())): None
                         for index in range(size)}
                observation["attributes"] = attributes(filter_prim, names, target)
            except _ObservationLimit:
                raise
            except _SequenceLimit:
                gap("FILTER_ATTRIBUTE_LIMIT", target, "more than 64 attributes; readback refused")
                continue
            except Exception as error:
                gap("FILTER_READ_FAILED", target, _native_error(error))
            gap("FILTER_EFFECT_UNRESOLVED", target,
                "raw filter configuration does not prove its executed effect on output AOVs")
        return result

    resolved_settings = read_prim(settings_path, "RenderSettings")
    if resolved_settings is not None:
        settings, settings_type = resolved_settings
        product_relation = relationship(settings, "products", settings_path)
        camera_relation = relationship(settings, "camera", settings_path, required=False)
        facts["settings"] = {"type_name": settings_type,
                             "attributes": attributes(settings, SETTINGS_ATTRIBUTES, settings_path),
                             "products": product_relation,
                             "camera": camera_relation,
                             "image_filters": filters(settings, settings_path)}
        for product_path in traversal_targets(product_relation, settings_path + ".products"):
            resolved_product = read_prim(product_path, "RenderProduct")
            if resolved_product is None:
                continue
            product, product_type = resolved_product
            var_relation = relationship(product, "orderedVars", product_path)
            product_attributes = attributes(product, PRODUCT_ATTRIBUTES, product_path)
            observation = {"path": product_path, "type_name": product_type,
                           "attributes": product_attributes, "ordered_vars": var_relation,
                           "vars": []}
            facts["products"].append(observation)
            for var_path in traversal_targets(var_relation, product_path + ".orderedVars"):
                resolved_var = read_prim(var_path, "RenderVar")
                if resolved_var is not None:
                    render_var, var_type = resolved_var
                    observation["vars"].append({"path": var_path,
                        "type_name": var_type,
                        "attributes": attributes(render_var, VAR_ATTRIBUTES, var_path)})
            gap("OUTPUT_PATH_UNRESOLVED", product_path + ".productName",
                "authored productName is not the observed final path after CLI/ROP overrides")
    for code, detail in (
        ("OCIO_CONFIGURATION_UNRESOLVED", "active config bytes, LUTs, context, roles and file-rule evaluation unobserved"),
        ("RUNTIME_OVERRIDES_UNOBSERVED", "actual husk argv, renderer/driver, OCIO enablement and output overrides unobserved"),
        ("IMAGE_FILTER_EXECUTION_UNOBSERVED", "composed filter targets alone do not establish the final executed processing chain"),
        ("ALPHA_ASSOCIATION_UNPROVEN", "no documented native association fact for this output"),
    ):
        gap(code, settings_path, detail)
    return budget.finish(facts)
