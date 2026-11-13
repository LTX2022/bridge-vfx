"""Bridge-owned HOM provider for the guarded S-06 solver evidence seam.

This module is intentionally independent from SideFX's node implementation.
It reads existing SOP geometry through the public HOM ``hou.Geometry`` /
``hou.Volume`` /
``hou.VDB`` interfaces and reports exactly which parts of the S-06 contract
are implemented.  It does not create nodes, set parameters, cook, write a
cache, render, or treat a custom attribute on a node as native evidence.

The provider is a partial implementation by design.  A writable volume path
for the controller sentinel and a real source/cook/readback boundary require
a separately authorized construction experiment in an owned HIP.  Until that
evidence exists those interfaces remain ``unimplemented`` and the add-on
cannot enter its mutation-ready state.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA = "bridge.f2.s06-native-host-adapter/1.0"
PROVIDER_VERSION = "1.0"
SUPPORTED_HOUDINI_BUILD = "21.0.631"
PROVIDER_ATTRIBUTE = "bridge_s06_native_adapter_v1"
PROVIDER_OWNER = "bridge-skills.s06-native-provider"
MAX_SAMPLES = 4096
MAX_PRIMITIVES_TO_SCAN = 10000

INTERFACE_NAMES = (
    "field_snapshot",
    "apply_velocity_sentinel",
    "velocity_writer_inventory",
    "observe_sourcing_boundary",
)

_VECTOR_COMPONENTS = ("x", "y", "z")
_FIELD_COMPONENT_NAMES = tuple("vel." + component for component in _VECTOR_COMPONENTS)
_GRAPH_ROLES = (
    "source",
    "source_points",
    "source_control",
    "source_volume",
    "solver",
    "output",
)
_GRAPH_TYPES = {
    "source": "sphere",
    "source_points": "pyrosource",
    "source_control": "attribwrangle",
    "source_volume": "volumerasterizeattributes",
    "solver": "pyrosolver",
    "output": "null",
}
_GRAPH_EDGES = (
    ("source_points", "source"),
    ("source_control", "source_points"),
    ("source_volume", "source_control"),
    ("solver", "source_volume"),
    ("output", "solver"),
)
_SOURCE_PROGRAM_REGISTRATION_SCHEMA = "bridge.pyro.point-source-program/1.0"
_SOURCE_PROGRAM_GENERATOR = "houdini_bridge_addon._fx_source_program"
_SOURCE_PROGRAM_GENERATOR_VERSION = 1
_SOURCE_PROGRAM_BINDING = {
    "role": "source_control",
    "parameter_aliases": ["snippet"],
}


class NativeProviderError(RuntimeError):
    """A fail-closed provider error with a stable diagnostic code."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__("{}: {}".format(self.code, message))


def _finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _as_sequence(value: Any) -> Optional[List[Any]]:
    """Convert HOM vector-like values without using a string representation."""

    if isinstance(value, (str, bytes, bytearray)) or value is None:
        return None
    as_tuple = getattr(value, "asTuple", None)
    if callable(as_tuple):
        try:
            value = as_tuple()
        except Exception:
            return None
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value)
    except Exception:
        pass
    components: List[Any] = []
    for name in ("x", "y", "z", "w"):
        attribute = getattr(value, name, None)
        if callable(attribute):
            try:
                components.append(attribute())
            except Exception:
                return None
        elif attribute is not None:
            components.append(attribute)
        else:
            break
    return components or None


def _json_value(value: Any) -> Any:
    """Return a bounded JSON value or raise rather than inventing metadata."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NativeProviderError("FIELD_METADATA_NONFINITE", "HOM metadata contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise NativeProviderError("FIELD_METADATA_INVALID", "HOM metadata keys must be strings")
            result[key] = _json_value(item)
        return result
    sequence = _as_sequence(value)
    if sequence is not None:
        return [_json_value(item) for item in sequence]
    name = getattr(value, "name", None)
    if callable(name):
        try:
            named = name()
        except Exception:
            named = None
        if isinstance(named, str) and named:
            return named
    raise NativeProviderError("FIELD_METADATA_UNSUPPORTED", "HOM metadata type is not JSON-readable")


def _label(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    name = getattr(value, "name", None)
    if callable(name):
        try:
            value = name()
        except Exception:
            value = None
    if isinstance(value, str):
        return value
    return None


def _positive_int_tuple(value: Any, code: str, label: str) -> Tuple[int, int, int]:
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) != 3:
        raise NativeProviderError(code, "{} must be a three-component sequence".format(label))
    if any(type(item) is bool or not isinstance(item, int) or item <= 0 for item in sequence):
        raise NativeProviderError(code, "{} must contain positive integers".format(label))
    return int(sequence[0]), int(sequence[1]), int(sequence[2])


def _integer_tuple(value: Any, code: str, label: str) -> Tuple[int, int, int]:
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) != 3:
        raise NativeProviderError(code, "{} must be a three-component sequence".format(label))
    converted: List[int] = []
    for item in sequence:
        if type(item) is bool or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise NativeProviderError(code, "{} must contain finite coordinates".format(label))
        integer = int(item)
        if float(item) != float(integer):
            raise NativeProviderError(code, "{} must contain integer coordinates".format(label))
        converted.append(integer)
    return converted[0], converted[1], converted[2]


def _vector3(value: Any, code: str, label: str) -> List[float]:
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) != 3 or not all(_finite_number(item) for item in sequence):
        raise NativeProviderError(code, "{} must be a finite three-component vector".format(label))
    return [float(item) for item in sequence]


def _primitive_name(primitive: Any) -> Optional[str]:
    """Read the primitive's native ``name`` intrinsic/attribute only."""

    for method_name in ("intrinsicValue", "stringAttribValue", "attribValue"):
        method = getattr(primitive, method_name, None)
        if not callable(method):
            continue
        try:
            value = method("name")
        except Exception:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    attribute = getattr(primitive, "name", None)
    if callable(attribute):
        try:
            value = attribute()
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _primitive_type_names(primitive: Any) -> List[str]:
    names = [type(primitive).__name__]
    type_method = getattr(primitive, "type", None)
    if callable(type_method):
        try:
            type_value = type_method()
        except Exception:
            type_value = None
        if type_value is not None:
            names.append(type(type_value).__name__)
            label = _label(type_value)
            if label:
                names.append(label)
    return [str(value).casefold() for value in names if value]


def _primitive_kind(primitive: Any) -> Optional[str]:
    names = _primitive_type_names(primitive)
    if any("nanovdb" in value for value in names):
        return None
    if any("vdb" in value for value in names):
        return "VDB"
    if any("volume" in value for value in names):
        return "Volume"
    return None


def _node_path(node: Any) -> str:
    path_method = getattr(node, "path", None)
    if not callable(path_method):
        return "<unaddressable-node>"
    try:
        value = path_method()
    except Exception:
        return "<unaddressable-node>"
    return str(value)


def _bbox_corner(bbox: Any, names: Sequence[str], code: str) -> Tuple[int, int, int]:
    for name in names:
        getter = getattr(bbox, name, None)
        if not callable(getter):
            continue
        try:
            return _integer_tuple(getter(), code, "active voxel bounding-box corner")
        except NativeProviderError:
            raise
        except Exception:
            continue
    raise NativeProviderError(code, "active voxel bounding box has no readable corner")


def _primitive_metadata(primitive: Any, primitive_name: str, kind: str) -> Dict[str, Any]:
    resolution_getter = getattr(primitive, "resolution", None)
    if not callable(resolution_getter):
        raise NativeProviderError("FIELD_RESOLUTION_UNAVAILABLE", "{} has no HOM resolution()".format(primitive_name))
    try:
        resolution = _positive_int_tuple(
            resolution_getter(), "FIELD_RESOLUTION_INVALID", "{} resolution".format(primitive_name)
        )
    except NativeProviderError:
        raise
    except Exception as exc:
        raise NativeProviderError("FIELD_RESOLUTION_UNAVAILABLE", "{} resolution() failed".format(primitive_name)) from exc
    total = resolution[0] * resolution[1] * resolution[2]
    if total <= 0 or total > 10**15:
        raise NativeProviderError("FIELD_RESOLUTION_UNSAFE", "{} voxel domain exceeds the bounded reader".format(primitive_name))

    transform_getter = getattr(primitive, "transform", None)
    if not callable(transform_getter):
        raise NativeProviderError("FIELD_TRANSFORM_UNAVAILABLE", "{} has no HOM transform()".format(primitive_name))
    try:
        transform = _json_value(transform_getter())
    except NativeProviderError:
        raise
    except Exception as exc:
        raise NativeProviderError("FIELD_TRANSFORM_UNAVAILABLE", "{} transform() failed".format(primitive_name)) from exc

    voxel_size_getter = getattr(primitive, "voxelSize", None)
    if not callable(voxel_size_getter):
        raise NativeProviderError("FIELD_VOXEL_SIZE_UNAVAILABLE", "{} has no HOM voxelSize()".format(primitive_name))
    try:
        voxel_size = _vector3(voxel_size_getter(), "FIELD_VOXEL_SIZE_INVALID", "{} voxel size".format(primitive_name))
    except NativeProviderError:
        raise
    except Exception as exc:
        raise NativeProviderError("FIELD_VOXEL_SIZE_UNAVAILABLE", "{} voxelSize() failed".format(primitive_name)) from exc

    active_offset = (0, 0, 0)
    active_bbox: Optional[Dict[str, Any]] = None
    if kind == "VDB":
        bbox_getter = getattr(primitive, "activeVoxelBoundingBox", None)
        if not callable(bbox_getter):
            raise NativeProviderError(
                "FIELD_ACTIVE_BBOX_UNAVAILABLE",
                "VDB {} has no activeVoxelBoundingBox(); global voxel indices are unsafe to infer".format(primitive_name),
            )
        try:
            bbox = bbox_getter()
            active_offset = _bbox_corner(bbox, ("minvec", "min"), "FIELD_ACTIVE_BBOX_INVALID")
            maximum = _bbox_corner(bbox, ("maxvec", "max"), "FIELD_ACTIVE_BBOX_INVALID")
        except NativeProviderError:
            raise
        except Exception as exc:
            raise NativeProviderError("FIELD_ACTIVE_BBOX_UNAVAILABLE", "VDB active voxel bounding box could not be read") from exc
        differences = tuple(maximum[index] - active_offset[index] for index in range(3))
        resolution_matches = differences == resolution
        inclusive_matches = tuple(value + 1 for value in differences) == resolution
        if not resolution_matches and not inclusive_matches:
            raise NativeProviderError(
                "FIELD_ACTIVE_BBOX_MISMATCH",
                "VDB active bounding-box extent does not match resolution()",
            )
        active_bbox = {
            "min": list(active_offset),
            "max": list(maximum),
            "max_is_inclusive": bool(inclusive_matches and not resolution_matches),
        }

    optional_values: Dict[str, Any] = {}
    for method_name in ("dataType", "vdbType", "storage"):
        getter = getattr(primitive, method_name, None)
        if not callable(getter):
            continue
        try:
            raw_value = getter()
            optional_values[method_name] = _label(raw_value) or _json_value(raw_value)
        except Exception:
            optional_values[method_name] = None
    active_count_getter = getattr(primitive, "activeVoxelCount", None)
    if callable(active_count_getter):
        try:
            active_count = active_count_getter()
            if type(active_count) is int and active_count >= 0:
                optional_values["activeVoxelCount"] = active_count
        except Exception:
            pass

    return {
        "primitive_name": primitive_name,
        "primitive_type": kind,
        "resolution": list(resolution),
        "active_index_offset": list(active_offset),
        "active_voxel_bounding_box": active_bbox,
        "transform": transform,
        "voxel_size": voxel_size,
        "storage": optional_values,
    }


def _metadata_signature(metadata: Mapping[str, Any]) -> str:
    comparable = {
        key: metadata.get(key)
        for key in (
            "primitive_type",
            "resolution",
            "active_index_offset",
            "active_voxel_bounding_box",
            "transform",
            "voxel_size",
        )
    }
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sample_indices(resolution: Tuple[int, int, int], offset: Tuple[int, int, int]) -> Tuple[List[List[int]], str]:
    nx, ny, nz = resolution
    total = nx * ny * nz
    if total <= 0:
        raise NativeProviderError("FIELD_SAMPLE_DOMAIN_INVALID", "field has no voxels")
    if total <= MAX_SAMPLES:
        flat_indices = range(total)
        order = "z_y_x_with_x_fastest"
    else:
        # Evenly spaced flat indices preserve the x-fastest mapping while
        # bounding both memory and HOM calls for a large dense volume.
        count = MAX_SAMPLES
        flat_indices = [int(index * (total - 1) / float(count - 1)) for index in range(count)]
        order = "even_flat_x_fastest_bounded_4096"
    indices: List[List[int]] = []
    for flat in flat_indices:
        x = flat % nx
        y = (flat // nx) % ny
        z = flat // (nx * ny)
        indices.append([x + offset[0], y + offset[1], z + offset[2]])
    return indices, order


def _read_voxel(primitive: Any, index: Sequence[int], primitive_name: str) -> Any:
    getter = getattr(primitive, "voxel", None)
    if not callable(getter):
        raise NativeProviderError("FIELD_VOXEL_READ_UNAVAILABLE", "{} has no HOM voxel()".format(primitive_name))
    try:
        return getter(tuple(index))
    except TypeError:
        # A few synthetic HOM doubles accept a list while HOM accepts a
        # three-int sequence.  This is only an argument-shape retry, never a
        # fallback to a custom node method or generated value.
        try:
            return getter(list(index))
        except Exception as exc:
            raise NativeProviderError("FIELD_VOXEL_READ_FAILED", "{} voxel() failed".format(primitive_name)) from exc
    except Exception as exc:
        raise NativeProviderError("FIELD_VOXEL_READ_FAILED", "{} voxel() failed".format(primitive_name)) from exc


def _scalar_value(value: Any, primitive_name: str) -> float:
    if not _finite_number(value):
        raise NativeProviderError(
            "FIELD_COMPONENT_SHAPE_INVALID",
            "{} did not return a finite scalar voxel value".format(primitive_name),
        )
    return float(value)


def _vector_value(value: Any, primitive_name: str) -> List[float]:
    sequence = _as_sequence(value)
    if sequence is None or len(sequence) != 3 or not all(_finite_number(item) for item in sequence):
        raise NativeProviderError(
            "FIELD_COMPONENT_SHAPE_INVALID",
            "{} did not return a finite three-component voxel value".format(primitive_name),
        )
    return [float(item) for item in sequence]


def _expected_node_name(role: str) -> str:
    return "FX_{}".format("".join(character if character.isalnum() else "_" for character in role.upper())[:48])


def _node_type_name(node: Any) -> Optional[str]:
    type_method = getattr(node, "type", None)
    if not callable(type_method):
        return None
    try:
        type_value = type_method()
    except Exception:
        return None
    name_method = getattr(type_value, "name", None)
    if callable(name_method):
        try:
            value = name_method()
        except Exception:
            value = None
    else:
        value = type_value
    return str(value) if isinstance(value, (str, int)) else None


def _read_parm(node: Any, name: str, label: str) -> Any:
    parm_getter = getattr(node, "parm", None)
    parm = parm_getter(name) if callable(parm_getter) else None
    if parm is None:
        raise NativeProviderError("WRITER_PARAMETER_MISSING", "{} is missing {}".format(_node_path(node), label))
    evaluator = getattr(parm, "eval", None)
    if not callable(evaluator):
        raise NativeProviderError("WRITER_PARAMETER_UNREADABLE", "{} has no eval() for {}".format(_node_path(node), label))
    try:
        return evaluator()
    except Exception as exc:
        raise NativeProviderError("WRITER_PARAMETER_UNREADABLE", "{} could not read {}".format(_node_path(node), label)) from exc


def _read_menu_token(node: Any, name: str, label: str) -> str:
    parm_getter = getattr(node, "parm", None)
    parm = parm_getter(name) if callable(parm_getter) else None
    if parm is None:
        raise NativeProviderError("WRITER_PARAMETER_MISSING", "{} is missing {}".format(_node_path(node), label))
    value = _read_parm(node, name, label)
    if isinstance(value, str):
        return value
    if type(value) is int:
        template_getter = getattr(parm, "parmTemplate", None)
        template = template_getter() if callable(template_getter) else None
        generator = getattr(template, "itemGeneratorScript", None) if template is not None else None
        if callable(generator):
            try:
                if generator():
                    raise NativeProviderError("WRITER_DYNAMIC_MENU_UNVERIFIED", "{} is dynamic".format(label))
            except NativeProviderError:
                raise
            except Exception as exc:
                raise NativeProviderError("WRITER_MENU_UNREADABLE", "{} generator state is unreadable".format(label)) from exc
        items_getter = getattr(template, "menuItems", None) if template is not None else None
        items = items_getter() if callable(items_getter) else ()
        items = tuple(items or ())
        if 0 <= value < len(items) and isinstance(items[value], str):
            return items[value]
    as_string = getattr(parm, "evalAsString", None)
    if callable(as_string):
        try:
            result = as_string()
        except Exception as exc:
            raise NativeProviderError("WRITER_MENU_UNREADABLE", "{} evalAsString() failed".format(label)) from exc
        if isinstance(result, str) and result:
            return result
    raise NativeProviderError("WRITER_MENU_TOKEN_UNAVAILABLE", "{} did not read back a token".format(label))


def _normalize_toggle(value: Any, label: str) -> bool:
    """Normalize HOM toggle readback without accepting truthy look-alikes."""

    if type(value) is bool:
        return value
    if type(value) is int:
        if value in (0, 1):
            return bool(value)
        raise NativeProviderError(
            "WRITER_TOGGLE_VALUE_INVALID",
            "{} returned integer {}; expected exactly 0 or 1".format(label, value),
        )
    if type(value) is float:
        if not math.isfinite(value):
            raise NativeProviderError(
                "WRITER_TOGGLE_NONFINITE",
                "{} returned a non-finite floating-point value".format(label),
            )
        if value in (0.0, 1.0):
            return bool(int(value))
        raise NativeProviderError(
            "WRITER_TOGGLE_VALUE_INVALID",
            "{} returned floating-point {}; expected exactly 0.0 or 1.0".format(label, value),
        )
    raise NativeProviderError(
        "WRITER_TOGGLE_TYPE_INVALID",
        "{} returned {}; expected bool or numeric 0/1".format(label, type(value).__name__),
    )


def _read_inputs(node: Any, label: str) -> Tuple[Any, ...]:
    inputs_getter = getattr(node, "inputs", None)
    if not callable(inputs_getter):
        raise NativeProviderError("WRITER_CONNECTION_UNREADABLE", "{} has no inputs()".format(label))
    try:
        return tuple(inputs_getter())
    except Exception as exc:
        raise NativeProviderError("WRITER_CONNECTION_UNREADABLE", "{} inputs() failed".format(label)) from exc


def _read_source_program_registration(manifest: Mapping[str, Any]) -> str:
    """Require the controller's registered source program and legal binding."""

    registration = manifest.get("source_program_registration")
    if not isinstance(registration, Mapping):
        raise NativeProviderError(
            "WRITER_SOURCE_PROGRAM_DEFINITION_MISSING",
            "manifest has no trusted source program registration",
        )
    if (
        registration.get("schema") != _SOURCE_PROGRAM_REGISTRATION_SCHEMA
        or registration.get("generator") != _SOURCE_PROGRAM_GENERATOR
        or registration.get("generator_version") != _SOURCE_PROGRAM_GENERATOR_VERSION
        or registration.get("source_contract") != "bridge.pyro.point-source/1.0"
        or registration.get("binding") != _SOURCE_PROGRAM_BINDING
    ):
        raise NativeProviderError(
            "WRITER_SOURCE_PROGRAM_DEFINITION_UNKNOWN",
            "source program registration is not the registered controller definition",
        )
    program = registration.get("program")
    if not isinstance(program, str) or not program.strip():
        raise NativeProviderError(
            "WRITER_SOURCE_PROGRAM_DEFINITION_INVALID",
            "registered source program is missing or not text",
        )
    host_controls = manifest.get("source_plan_host_controls")
    if not isinstance(host_controls, Mapping) or host_controls.get("source_program") != program:
        raise NativeProviderError(
            "WRITER_SOURCE_PROGRAM_BINDING_MISMATCH",
            "registered source program does not match the builder host-control registration",
        )
    return program


def _input_path(node: Any, index: int, label: str) -> str:
    inputs_getter = getattr(node, "inputs", None)
    if not callable(inputs_getter):
        raise NativeProviderError("WRITER_CONNECTION_UNREADABLE", "{} has no inputs()".format(label))
    try:
        inputs = tuple(inputs_getter())
    except Exception as exc:
        raise NativeProviderError("WRITER_CONNECTION_UNREADABLE", "{} inputs() failed".format(label)) from exc
    if index >= len(inputs) or inputs[index] is None:
        raise NativeProviderError("WRITER_CONNECTION_MISSING", "{} input {} is not connected".format(label, index))
    return _node_path(inputs[index])


def _inventory_failure(error: NativeProviderError, *, scope: str = "task_owned_fixed_graph") -> Dict[str, Any]:
    return {
        "status": "unknown",
        "complete": False,
        "scope": scope,
        "global_inventory": False,
        "other_writers": [],
        "other_writers_complete": False,
        "graph_topology_verified": False,
        "source_rows_verified": False,
        "source_program_verified": False,
        "field_writer_scope_complete": False,
        "internal_writer_scope_complete": False,
        "source_effect_isolated": False,
        "owned_writers": [],
        "reason": error.code,
        "detail": str(error),
    }


class S06NativeProvider:
    """The Bridge-owned, read-mostly S-06 provider installed by the plugin."""

    schema = SCHEMA
    provider_version = PROVIDER_VERSION
    _bridge_provider_owner = PROVIDER_OWNER

    def __init__(self, hou_module: Any):
        self._hou = hou_module
        self._authorized_frames: List[int] = []

    def _host_build(self) -> str:
        getter = getattr(self._hou, "applicationVersionString", None)
        if not callable(getter):
            return ""
        try:
            return str(getter())
        except Exception:
            return ""

    def _require_supported_build(self) -> None:
        build = self._host_build()
        if build != SUPPORTED_HOUDINI_BUILD:
            raise NativeProviderError(
                "HOST_BUILD_UNSUPPORTED",
                "provider is bound only to Houdini {}; observed {}".format(SUPPORTED_HOUDINI_BUILD, build or "<unreadable>"),
            )

    @contextmanager
    def authorized_frame(self, frame: int):
        """Guard formal sampling against an accidental wrong-frame read."""

        self._require_supported_build()
        if type(frame) is not int:
            raise NativeProviderError("FRAME_GUARD_INVALID", "authorized frame must be an integer")
        getter = getattr(self._hou, "frame", None)
        if not callable(getter):
            raise NativeProviderError("FRAME_GUARD_UNAVAILABLE", "hou.frame() is unavailable")
        try:
            actual = int(round(float(getter())))
        except Exception as exc:
            raise NativeProviderError("FRAME_GUARD_UNAVAILABLE", "hou.frame() could not be read") from exc
        if actual != frame:
            raise NativeProviderError(
                "FRAME_GUARD_MISMATCH",
                "current Houdini frame {} differs from authorized frame {}".format(actual, frame),
            )
        self._authorized_frames.append(frame)
        try:
            yield self
        finally:
            if self._authorized_frames and self._authorized_frames[-1] == frame:
                self._authorized_frames.pop()
            else:
                try:
                    self._authorized_frames.remove(frame)
                except ValueError:
                    pass

    frame_guard = authorized_frame

    def _require_frame_guard(self, frame: int) -> None:
        if not self._authorized_frames or self._authorized_frames[-1] != frame:
            raise NativeProviderError(
                "FRAME_GUARD_REQUIRED",
                "field sampling is allowed only inside authorized_frame({})".format(frame),
            )

    def sourcing_contract(self) -> Dict[str, Any]:
        """Return the fixed source/target contract without reading dynamic menus."""

        return {
            "schema": "bridge.pyro.solver-sourcing/21.0.631",
            "houdini_build": SUPPORTED_HOUDINI_BUILD,
            "rows": [
                {
                    "row": 1,
                    "source_field": "density",
                    "target_field": "density",
                    "source_rank": "scalar",
                    "merge": "add",
                    "parameters": {
                        "source_volume": "source_volume1",
                        "target_field": "source_vfield1",
                        "rank": "source_rank1",
                        "operator": "source_voperator1",
                        "scale": "source_vscale1",
                        "use_timestep": "source_vnormalize1",
                    },
                    "menu_tokens": {"source_voperator1": "add", "source_rank1": "scalar"},
                },
                {
                    "row": 2,
                    "source_field": "v",
                    "target_field": "vel",
                    "source_rank": "vector",
                    "merge": "copy",
                    "parameters": {
                        "source_volume": "source_volume2",
                        "target_field": "source_vfield2",
                        "rank": "source_rank2",
                        "operator": "source_voperator2",
                        "scale": "source_vscale2",
                        "use_timestep": "source_vnormalize2",
                    },
                    "menu_tokens": {"source_voperator2": "copy", "source_rank2": "vector"},
                },
            ],
            "global_parameters": {
                "range_type": {"parameter": "srcrangetype", "token": "sequence"},
                "start_frame": "startframe",
                "frame_range": "srcframerange",
                "cycle_enabled": {"parameter": "srcdocycle", "value": False},
                "cycle_length": "srccyclelength",
                "timescale": "timescale",
            },
            "dynamic_fields": [
                "source_volume#",
                "source_vfield#",
                "source_weightvolume#",
                "source_vweightfield#",
            ],
            "dynamic_menus_executed": False,
            "units": {
                "velocity": "scene_units_per_second",
                "source_scale": "dimensionless",
                "timestep": "timescale / hou.fps()",
                "unit_evidence": "solver_contract; per-grid unit metadata is not exposed by the public HOM reader",
            },
            "frame_window": "controller-owned source_activate# constant keyframes; frame step is 1",
            "inactive_behavior": "row activation is off; v is not replaced with a zero vector and Copy does not run",
        }

    def capabilities(self) -> Dict[str, Any]:
        """Report implementation state without touching scene geometry."""

        build = self._host_build()
        supported = build == SUPPORTED_HOUDINI_BUILD
        if supported:
            interfaces = {
                "field_snapshot": {
                    "status": "implemented",
                    "reason": "public HOM Volume/VDB voxel read with metadata and a frame guard",
                    "live_verified": False,
                },
                "apply_velocity_sentinel": {
                    "status": "unimplemented",
                    "reason": "no proven writable task-volume path; solver.geometry() is read-only for this seam",
                    "live_verified": False,
                },
                "velocity_writer_inventory": {
                    "status": "implemented",
                    "reason": "read-only inventory for the exact task-owned six-node graph only",
                    "live_verified": False,
                },
                "observe_sourcing_boundary": {
                    "status": "unimplemented",
                    "reason": "requires an authorized source-write, solver-refresh, and distinct pre/post readback experiment",
                    "live_verified": False,
                },
            }
        else:
            interfaces = {
                name: {
                    "status": "unsupported",
                    "reason": "provider is fixed to Houdini {}".format(SUPPORTED_HOUDINI_BUILD),
                    "live_verified": False,
                }
                for name in INTERFACE_NAMES
            }
        return {
            "schema": SCHEMA,
            "provider_version": PROVIDER_VERSION,
            "provider_owner": PROVIDER_OWNER,
            "houdini_build": build or None,
            "supported_houdini_build": SUPPORTED_HOUDINI_BUILD,
            "interfaces": interfaces,
            "required_interfaces": list(INTERFACE_NAMES),
            "ready_for_mutation": False,
            "live_verified": False,
            "sourcing_contract": self.sourcing_contract(),
            "evidence_boundary": "software_provider_only; no live DCC/simulation/cache/render acceptance",
        }

    def field_snapshot(self, node: Any, field: str, stage: str, frame: int) -> Dict[str, Any]:
        """Read ``vel`` from scalar component grids or one vector grid."""

        self._require_supported_build()
        self._require_frame_guard(frame)
        if field != "vel":
            raise NativeProviderError("FIELD_UNSUPPORTED", "only the target velocity field vel is in this contract")
        if not isinstance(stage, str) or not stage.strip() or type(frame) is not int:
            raise NativeProviderError("FIELD_REQUEST_INVALID", "field stage/frame is invalid")
        geometry_getter = getattr(node, "geometry", None)
        if not callable(geometry_getter):
            raise NativeProviderError("FIELD_GEOMETRY_UNAVAILABLE", "node has no geometry()")
        try:
            geometry = geometry_getter()
            primitives_getter = getattr(geometry, "prims", None)
            if not callable(primitives_getter):
                raise NativeProviderError("FIELD_GEOMETRY_UNAVAILABLE", "geometry has no prims()")
            primitives = tuple(primitives_getter())
        except NativeProviderError:
            raise
        except Exception as exc:
            raise NativeProviderError("FIELD_GEOMETRY_UNAVAILABLE", "node.geometry().prims() failed") from exc
        if len(primitives) > MAX_PRIMITIVES_TO_SCAN:
            raise NativeProviderError("FIELD_GEOMETRY_UNSAFE", "geometry primitive count exceeds the bounded reader")

        named: Dict[str, List[Any]] = {}
        for primitive in primitives:
            name = _primitive_name(primitive)
            if name in _FIELD_COMPONENT_NAMES or name == "vel":
                if name is None:
                    continue
                named.setdefault(name, []).append(primitive)
        component_counts = [len(named.get(name, ())) for name in _FIELD_COMPONENT_NAMES]
        vector_count = len(named.get("vel", ()))
        if vector_count > 0 and any(count > 0 for count in component_counts):
            raise NativeProviderError("FIELD_BINDING_AMBIGUOUS", "component and vector vel representations are both present")
        if vector_count != 1 and any(count != 1 for count in component_counts):
            present = sorted(name for name in named if name in _FIELD_COMPONENT_NAMES or name == "vel")
            raise NativeProviderError(
                "FIELD_BINDING_INCOMPLETE",
                "expected exactly vel.x/vel.y/vel.z or one vector vel; observed {}".format(",".join(present) or "none"),
            )
        component_representation = vector_count == 0 and all(count == 1 for count in component_counts)
        vector_representation = vector_count == 1

        if component_representation:
            primitives_by_component = {name: named[name][0] for name in _FIELD_COMPONENT_NAMES}
            metadata_by_component = {
                name: _primitive_metadata(primitive, name, _primitive_kind(primitive) or "")
                for name, primitive in primitives_by_component.items()
            }
            if any(not metadata["primitive_type"] for metadata in metadata_by_component.values()):
                raise NativeProviderError("FIELD_PRIMITIVE_UNSUPPORTED", "a velocity component is not a Volume or VDB primitive")
            signatures = {_metadata_signature(metadata) for metadata in metadata_by_component.values()}
            if len(signatures) != 1:
                raise NativeProviderError("FIELD_GRID_MISMATCH", "velocity components do not share one grid transform/domain")
            metadata = dict(metadata_by_component["vel.x"])
            primitive_order = [primitives_by_component[name] for name in _FIELD_COMPONENT_NAMES]
            primitive_names = list(_FIELD_COMPONENT_NAMES)
        else:
            primitive = named["vel"][0]
            kind = _primitive_kind(primitive)
            if kind is None:
                raise NativeProviderError("FIELD_PRIMITIVE_UNSUPPORTED", "vector vel is not a Volume or VDB primitive")
            metadata = _primitive_metadata(primitive, "vel", kind)
            primitive_order = [primitive]
            primitive_names = ["vel"]

        resolution = tuple(int(value) for value in metadata["resolution"])
        offset = tuple(int(value) for value in metadata["active_index_offset"])
        indices, sampling_order = _sample_indices(resolution, offset)
        values: List[List[float]] = []
        for index in indices:
            if component_representation:
                values.append([
                    _scalar_value(_read_voxel(primitive, index, name), name)
                    for primitive, name in zip(primitive_order, primitive_names)
                ])
            else:
                values.append(_vector_value(_read_voxel(primitive_order[0], index, "vel"), "vel"))

        velocity = _load_velocity_module()
        sample_domain = {
            "kind": "hom_volume_voxels",
            "space": "object",
            "resolution": list(resolution),
            "active_index_offset": list(offset),
            "indices": indices,
            "sampling_order": sampling_order,
            "primitive_names": primitive_names,
            "representation": "scalar_components" if component_representation else "vector",
            "grid_metadata": [
                _metadata_for_sample(metadata_by_component[name], name)
                for name in _FIELD_COMPONENT_NAMES
            ] if component_representation else [_metadata_for_sample(metadata, "vel")],
        }
        units = {
            "velocity": "scene_units_per_second",
            "unit_source": "bridge.f2.solver-sourcing/21.0.631 contract",
            "verified": False,
        }
        snapshot = velocity.make_snapshot(
            field="vel",
            sample_domain=sample_domain,
            coordinate_space="object",
            units=units,
            component_order=list(_VECTOR_COMPONENTS),
            values=values,
        )
        node_path = _node_path(node)
        token_input = "{}|{}|{}|{}".format(node_path, stage, frame, snapshot["digest_sha256"])
        token = "hom-read-" + hashlib.sha256(token_input.encode("utf-8")).hexdigest()
        generation = int(hashlib.sha256(snapshot["digest_sha256"].encode("ascii")).hexdigest()[:8], 16)
        return {
            "snapshot": snapshot,
            "freshness": {
                "stage": stage,
                "frame": frame,
                "freshness_token": token,
                "field_generation": generation,
                "basis": "single guarded HOM read; not a sourcing-boundary proof",
            },
            "readback": {
                "node_path": node_path,
                "representation": "scalar_components" if component_representation else "vector",
                "primitive_names": primitive_names,
                "hom_reader": "hou.Geometry.prims -> hou.Volume/VDB.voxel",
            },
        }

    def apply_velocity_sentinel(self, root_node: Any, sentinel: Mapping[str, Any]) -> Dict[str, Any]:
        """Remain explicit until a writable, task-owned volume path is proven."""

        return {
            "status": "unimplemented",
            "applied": False,
            "readback_verified": False,
            "reason": "WRITABLE_VELOCITY_GEOMETRY_UNPROVEN",
            "scope": "task_owned_fixed_graph",
            "missing_evidence": [
                "a writable task-owned Volume/VDB geometry handle",
                "an explicit pre-write snapshot and rollback path",
                "a native readback after the write without modifying solver.geometry()",
            ],
            "experiment_required": "independent owned HIP; bounded velocity sentinel write/readback; no cache or render",
        }

    def velocity_writer_inventory(self, root_node: Any, manifest: Mapping[str, Any]) -> Dict[str, Any]:
        """Inspect only the exact Bridge-owned six-node source/solver graph."""

        try:
            self._require_supported_build()
            if not isinstance(manifest, Mapping):
                raise NativeProviderError("WRITER_MANIFEST_INVALID", "task manifest is not an object")
            if manifest.get("domain_pack") != "pyro_smoke_v1":
                raise NativeProviderError("WRITER_SCOPE_INVALID", "writer inventory is registered only for pyro_smoke_v1")
            if manifest.get("short_segment_scoped") is not True:
                raise NativeProviderError("WRITER_SCOPE_INVALID", "writer inventory requires a short-segment owned graph")
            root_path = _node_path(root_node)
            if root_path != str(manifest.get("execution_root") or ""):
                raise NativeProviderError("WRITER_SCOPE_INVALID", "root node differs from the manifest execution_root")
            nodes = manifest.get("nodes")
            if not isinstance(nodes, Mapping) or set(nodes) != set(_GRAPH_ROLES):
                raise NativeProviderError("WRITER_GRAPH_INCOMPLETE", "manifest must contain exactly the six fixed graph roles")
            for role in _GRAPH_ROLES:
                expected_path = root_path + "/" + _expected_node_name(role)
                if nodes.get(role) != expected_path:
                    raise NativeProviderError("WRITER_GRAPH_SCOPE_INVALID", "{} path is not the fixed child path".format(role))
            children_getter = getattr(root_node, "children", None)
            if not callable(children_getter):
                raise NativeProviderError("WRITER_GRAPH_UNREADABLE", "root has no children()")
            children = tuple(children_getter())
            expected_paths = {root_path + "/" + _expected_node_name(role) for role in _GRAPH_ROLES}
            actual_paths = {_node_path(child) for child in children}
            if actual_paths != expected_paths:
                raise NativeProviderError("WRITER_GRAPH_CHILDREN_MISMATCH", "fixed graph has missing or extra child nodes")
            node_getter = getattr(root_node, "node", None)
            if not callable(node_getter):
                raise NativeProviderError("WRITER_GRAPH_UNREADABLE", "root has no child node lookup")
            graph: Dict[str, Any] = {}
            for role in _GRAPH_ROLES:
                node = node_getter(_expected_node_name(role))
                if node is None or _node_path(node) != nodes[role]:
                    raise NativeProviderError("WRITER_GRAPH_NODE_MISSING", "fixed graph node {} is missing".format(role))
                actual_type = _node_type_name(node)
                if actual_type != _GRAPH_TYPES[role]:
                    raise NativeProviderError(
                        "WRITER_GRAPH_TYPE_MISMATCH",
                        "{} has type {}, expected {}".format(role, actual_type or "<unknown>", _GRAPH_TYPES[role]),
                    )
                graph[role] = node
            expected_inputs = {role: None for role in _GRAPH_ROLES}
            for destination, source_role in _GRAPH_EDGES:
                expected_inputs[destination] = source_role
            for role, node in graph.items():
                inputs = _read_inputs(node, role)
                source_role = expected_inputs[role]
                connected_indices = [index for index, item in enumerate(inputs) if item is not None]
                if source_role is None:
                    if connected_indices:
                        raise NativeProviderError(
                            "WRITER_GRAPH_EXTRA_INPUT",
                            "{} has an unexpected connected input".format(role),
                        )
                    continue
                if not inputs or inputs[0] is None:
                    raise NativeProviderError(
                        "WRITER_GRAPH_CONNECTION_MISMATCH",
                        "{} input 0 is not connected to {}".format(role, source_role),
                    )
                expected_input = _node_path(graph[source_role])
                actual_input = _node_path(inputs[0])
                if actual_input != expected_input:
                    raise NativeProviderError(
                        "WRITER_GRAPH_CONNECTION_MISMATCH",
                        "{} input 0 is not {}".format(role, source_role),
                    )
                extra_indices = [index for index in connected_indices if index != 0]
                if extra_indices:
                    raise NativeProviderError(
                        "WRITER_GRAPH_EXTRA_INPUT",
                        "{} has extra connected inputs at {}".format(role, extra_indices),
                    )

            attributes = _read_parm(graph["source_volume"], "attributes", "source volume attributes")
            if not isinstance(attributes, str):
                raise NativeProviderError("WRITER_SOURCE_FIELDS_UNREADABLE", "source volume attributes are not text")
            attribute_names = attributes.split()
            if "density" not in attribute_names or "v" not in attribute_names:
                raise NativeProviderError("WRITER_SOURCE_FIELDS_MISSING", "source volume does not rasterize both density and v")
            source_count = _read_parm(graph["solver"], "numsources", "solver source row count")
            if type(source_count) is not int or source_count != 2:
                raise NativeProviderError(
                    "WRITER_SOLVER_SOURCE_COUNT_INVALID",
                    "solver numsources returned {}; fixed inventory requires exactly 2".format(source_count),
                )
            registered_program = _read_source_program_registration(manifest)
            snippet = _read_parm(graph["source_control"], "snippet", "source control program")
            if not isinstance(snippet, str):
                raise NativeProviderError("WRITER_SOURCE_PROGRAM_UNREADABLE", "source control program is not text")
            if snippet != registered_program:
                raise NativeProviderError(
                    "WRITER_SOURCE_PROGRAM_BINDING_MISMATCH",
                    "source control program does not match the registered builder program",
                )

            expected_rows = (
                (1, "density", "density", "scalar", "add"),
                (2, "v", "vel", "vector", "copy"),
            )
            rows: List[Dict[str, Any]] = []
            for index, source_field, target_field, rank, operation in expected_rows:
                source_value = _read_parm(graph["solver"], "source_volume{}".format(index), "source volume row {}".format(index))
                target_value = _read_parm(graph["solver"], "source_vfield{}".format(index), "target field row {}".format(index))
                rank_value = _read_menu_token(graph["solver"], "source_rank{}".format(index), "source rank row {}".format(index))
                operation_value = _read_menu_token(graph["solver"], "source_voperator{}".format(index), "source operator row {}".format(index))
                scale = _read_parm(graph["solver"], "source_vscale{}".format(index), "source scale row {}".format(index))
                use_timestep = _read_parm(graph["solver"], "source_vnormalize{}".format(index), "Use Timestep row {}".format(index))
                normalized_use_timestep = _normalize_toggle(use_timestep, "Use Timestep row {}".format(index))
                if source_value != source_field or target_value != target_field or rank_value != rank or operation_value != operation:
                    raise NativeProviderError("WRITER_SOLVER_BINDING_MISMATCH", "solver source row {} is not the fixed {} -> {} binding".format(index, source_field, target_field))
                if not _finite_number(scale) or abs(float(scale) - 1.0) > 1.0e-12 or normalized_use_timestep is not False:
                    raise NativeProviderError("WRITER_SOLVER_UNITS_MISMATCH", "solver row {} does not preserve scale 1.0 and Use Timestep false".format(index))
                rows.append({
                    "row": index,
                    "source_field": source_value,
                    "target_field": target_value,
                    "rank": rank_value,
                    "operation": operation_value,
                    "source_scale": float(scale),
                    "use_timestep": normalized_use_timestep,
                })
            return {
                "status": "implemented",
                "complete": True,
                "scope": "task_owned_fixed_graph",
                "global_inventory": False,
                "other_writers": [],
                "other_writers_complete": False,
                "graph_topology_verified": True,
                "source_rows_verified": True,
                "source_program_verified": True,
                "source_count": source_count,
                "source_count_parameter": "numsources",
                "inventory_scope_complete": True,
                "field_writer_scope_complete": False,
                "internal_writer_scope_complete": False,
                "source_effect_isolated": False,
                "owned_writers": [
                    _node_path(graph["source_control"]),
                    _node_path(graph["source_volume"]),
                    _node_path(graph["solver"]),
                ],
                "verification": "implemented_unverified_live_h21",
                "source_attributes": attribute_names,
                "solver_rows": rows,
                "connections": {
                    destination: _node_path(graph[source_role])
                    for destination, source_role in _GRAPH_EDGES
                },
                "scope_note": "Source rows and fixed graph topology are verified; solver internal field writers and graph-outside writers are not observable here, so this is not source-effect isolation.",
            }
        except NativeProviderError as error:
            return _inventory_failure(error)
        except Exception as exc:
            return _inventory_failure(
                NativeProviderError("WRITER_INVENTORY_ERROR", type(exc).__name__ + ": " + str(exc)),
            )

    def observe_sourcing_boundary(
        self,
        solver: Any,
        source: Any,
        frame: int,
        rows: Iterable[Mapping[str, Any]],
        request: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Keep real source/cook/readback evidence unimplemented and explicit."""

        return {
            "status": "unimplemented",
            "sourcing_boundary": None,
            "before_snapshot": None,
            "after_snapshot": None,
            "cook_succeeded": False,
            "cook_errors": ["SOURCING_BOUNDARY_EXPERIMENT_REQUIRED"],
            "output_nonempty": False,
            "reason": "SOURCING_BOUNDARY_EXPERIMENT_REQUIRED",
            "missing_evidence": [
                "a task-owned source binding write with operation receipt",
                "a solver refresh/cook under the authorized frame guard",
                "distinct pre/post HOM velocity snapshots and generations",
                "a controlled no-other-writer condition",
            ],
            "experiment_required": "independent owned HIP; pulse/gap; bounded frames; no cache or render",
        }


def _metadata_for_sample(metadata: Mapping[str, Any], name: str) -> Dict[str, Any]:
    result = dict(metadata)
    result["primitive_name"] = name
    return result


def _load_velocity_module() -> Any:
    repository_root = Path(__file__).resolve().parents[3]
    # vfx_pipeline's package initializer imports the shared contract package;
    # both sibling source roots must therefore be available in a standalone
    # Houdini plugin process as well as in the repository test runner.
    for package_root in (
        repository_root / "packages" / "dcc-task-runtime" / "src",
        repository_root / "packages" / "vfx-pipeline" / "src",
        repository_root / "packages" / "houdini-bridge" / "src",
        repository_root / "packages" / "nuke-bridge" / "src",
    ):
        if package_root.is_dir() and str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))
    try:
        from vfx_pipeline import s06_velocity
    except ImportError as exc:
        raise NativeProviderError("VELOCITY_CONTRACT_UNAVAILABLE", "reviewed velocity snapshot contract is not installed") from exc
    return s06_velocity


def install(hou_module: Any) -> Dict[str, Any]:
    """Install idempotently without replacing an unknown host provider."""

    existing = getattr(hou_module, PROVIDER_ATTRIBUTE, None)
    if existing is not None:
        if isinstance(existing, S06NativeProvider) and existing._hou is hou_module:
            return {
                "state": "already_installed",
                "provider": existing,
                "schema": SCHEMA,
                "provider_version": PROVIDER_VERSION,
            }
        return {
            "state": "conflict",
            "provider": existing,
            "schema": _label(getattr(existing, "schema", None)),
            "reason": "existing provider attribute was not replaced",
        }
    provider = S06NativeProvider(hou_module)
    try:
        setattr(hou_module, PROVIDER_ATTRIBUTE, provider)
    except Exception as exc:
        return {
            "state": "error",
            "provider": None,
            "reason": "PROVIDER_ATTRIBUTE_WRITE_FAILED:{}".format(type(exc).__name__),
        }
    return {
        "state": "installed",
        "provider": provider,
        "schema": SCHEMA,
        "provider_version": PROVIDER_VERSION,
        "capabilities": provider.capabilities(),
    }


ensure_installed = install


__all__ = [
    "INTERFACE_NAMES",
    "NativeProviderError",
    "PROVIDER_ATTRIBUTE",
    "PROVIDER_OWNER",
    "SCHEMA",
    "S06NativeProvider",
    "SUPPORTED_HOUDINI_BUILD",
    "ensure_installed",
    "install",
]
