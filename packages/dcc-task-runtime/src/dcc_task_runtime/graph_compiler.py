"""Bounded, deterministic compilation of model-proposed node graphs.

The graph compiler is deliberately a pure in-memory boundary. It knows about
an explicitly supplied catalogue and contexts, but it does not know how to
create or execute nodes in Houdini, Nuke, or another DCC. A proposal can
therefore be inspected and rejected before it reaches a bridge.

The public proposal surface contains node and port identifiers only. Node
types, ports, parameter declarations, subnet permissions, and cycle
boundaries come from the trusted catalogue supplied to GraphCompiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .canonical import canonical_json, canonical_sha256, json_value
from .errors import RuntimeV2Error
from .models import ErrorCode


GRAPH_SCHEMA_VERSION = "1.0"

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_FORBIDDEN_FIELDS = frozenset(
    {
        "code",
        "command",
        "eval",
        "exec",
        "expression",
        "python",
        "script",
        "scripts",
        "shell",
    }
)
_PARAMETER_TYPES = frozenset({"bool", "enum", "float", "int", "number", "path", "string"})
_MISSING = object()


def _stable_identifier(value: Any, name: str) -> str:
    rendered = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(rendered):
        raise ValueError(f"{name} must be a stable identifier")
    return rendered


def _identifier_is_valid(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value.strip()))


def _safe_path_segment(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    rendered = value.strip()
    return (
        value == rendered
        and rendered not in {".", ".."}
        and "/" not in rendered
        and "\\" not in rendered
        and _identifier_is_valid(rendered)
    )


def _render_address(context: str, subnet_path: Sequence[str], node_id: str) -> str:
    return f"{context}:/{'/'.join(tuple(subnet_path) + (node_id,))}"


def _json_default(value: Any) -> Any:
    """Return a JSON-compatible value while keeping diagnostics deterministic."""

    try:
        return json_value(value)
    except (TypeError, ValueError):
        return {"unsupported_type": type(value).__name__}


@dataclass(frozen=True)
class GraphDiagnostic:
    """One stable compiler diagnostic.

    path points into the untrusted proposal. details is deliberately kept as
    data so callers can present the error to a model or operator without
    parsing human text.
    """

    code: str
    message: str
    path: str = "$"
    severity: str = "error"
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = str(self.code or "").strip()
        message = str(self.message or "").strip()
        path = str(self.path or "$").strip()
        severity = str(self.severity or "error").strip().lower()
        if not code or not message or not path:
            raise ValueError("diagnostic code, message, and path are required")
        if severity not in {"error", "warning"}:
            raise ValueError("diagnostic severity must be error or warning")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "details", dict(self.details or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
            "details": _json_default(self.details),
        }


class GraphCompileError(RuntimeV2Error):
    """Raised when a proposal cannot be compiled into a safe graph."""

    def __init__(self, diagnostics: Sequence[GraphDiagnostic]) -> None:
        rendered = tuple(diagnostics)
        if not rendered:
            rendered = (
                GraphDiagnostic(
                    "INVALID_GRAPH",
                    "graph compilation failed without a diagnostic",
                ),
            )
        self.diagnostics = rendered
        summary = "; ".join(f"{item.code} at {item.path}: {item.message}" for item in rendered[:3])
        if len(rendered) > 3:
            summary += f"; and {len(rendered) - 3} more"
        super().__init__(
            ErrorCode.INVALID_STAGE_GRAPH,
            summary,
            {"diagnostics": [item.to_dict() for item in rendered]},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code.value,
            "message": str(self),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class PortSpec:
    """A named, typed port from the trusted node catalogue."""

    name: str
    value_type: str
    required: bool = False
    multiple: bool = False
    boundary: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _stable_identifier(self.name, "port.name"))
        object.__setattr__(self, "value_type", _stable_identifier(self.value_type, "port.value_type").lower())
        object.__setattr__(self, "required", bool(self.required))
        object.__setattr__(self, "multiple", bool(self.multiple))
        object.__setattr__(self, "boundary", bool(self.boundary))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value_type": self.value_type,
            "required": self.required,
            "multiple": self.multiple,
            "boundary": self.boundary,
        }


@dataclass(frozen=True)
class ParameterSpec:
    """A finite, typed, optionally ranged scalar parameter."""

    name: str
    value_type: str
    required: bool = False
    minimum: Optional[Union[int, float]] = None
    maximum: Optional[Union[int, float]] = None
    enum_values: Tuple[Any, ...] = ()
    default: Any = _MISSING

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _stable_identifier(self.name, "parameter.name"))
        value_type = _stable_identifier(self.value_type, "parameter.value_type").lower()
        if value_type not in _PARAMETER_TYPES:
            raise ValueError(f"unsupported parameter type: {value_type}")
        if self.name.casefold() in _FORBIDDEN_FIELDS:
            raise ValueError(f"parameter name is forbidden: {self.name}")
        object.__setattr__(self, "value_type", value_type)
        object.__setattr__(self, "required", bool(self.required))
        object.__setattr__(self, "enum_values", tuple(self.enum_values or ()))
        if self.minimum is not None and not _finite_number(self.minimum):
            raise ValueError("parameter minimum must be finite")
        if self.maximum is not None and not _finite_number(self.maximum):
            raise ValueError("parameter maximum must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("parameter minimum cannot exceed maximum")
        if value_type == "enum" and not self.enum_values:
            raise ValueError("enum parameter requires enum_values")
        if value_type != "enum" and self.enum_values:
            raise ValueError("enum_values are only valid for enum parameters")

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "value_type": self.value_type,
            "required": self.required,
        }
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        if self.enum_values:
            result["enum_values"] = [_json_default(item) for item in self.enum_values]
        if self.has_default:
            result["default"] = _json_default(self.default)
        return result


@dataclass(frozen=True)
class NodeSpec:
    """Trusted definition for one allowlisted node type."""

    node_type: str
    inputs: Tuple[PortSpec, ...] = ()
    outputs: Tuple[PortSpec, ...] = ()
    parameters: Tuple[ParameterSpec, ...] = ()
    allowed_contexts: Tuple[str, ...] = ()
    allow_subnet: bool = False
    cycle_boundary: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_type", _stable_identifier(self.node_type, "node_type"))
        inputs = tuple(self.inputs or ())
        outputs = tuple(self.outputs or ())
        parameters = tuple(self.parameters or ())
        for item in inputs + outputs:
            if not isinstance(item, PortSpec):
                raise ValueError("node ports must be PortSpec instances")
        for item in parameters:
            if not isinstance(item, ParameterSpec):
                raise ValueError("node parameters must be ParameterSpec instances")
        input_names = [item.name for item in inputs]
        output_names = [item.name for item in outputs]
        parameter_names = [item.name for item in parameters]
        if len(input_names) != len(set(input_names)):
            raise ValueError(f"duplicate input port in {self.node_type}")
        if len(output_names) != len(set(output_names)):
            raise ValueError(f"duplicate output port in {self.node_type}")
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError(f"duplicate parameter in {self.node_type}")
        allowed_contexts = tuple(_stable_identifier(item, "allowed_context") for item in (self.allowed_contexts or ()))
        if len(allowed_contexts) != len(set(allowed_contexts)):
            raise ValueError(f"duplicate allowed context in {self.node_type}")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "allowed_contexts", allowed_contexts)
        object.__setattr__(self, "allow_subnet", bool(self.allow_subnet))
        object.__setattr__(self, "cycle_boundary", bool(self.cycle_boundary))

    def input_port(self, name: str) -> Optional[PortSpec]:
        return next((item for item in self.inputs if item.name == name), None)

    def output_port(self, name: str) -> Optional[PortSpec]:
        return next((item for item in self.outputs if item.name == name), None)

    def parameter(self, name: str) -> Optional[ParameterSpec]:
        return next((item for item in self.parameters if item.name == name), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "parameters": [item.to_dict() for item in self.parameters],
            "allowed_contexts": list(self.allowed_contexts),
            "allow_subnet": self.allow_subnet,
            "cycle_boundary": self.cycle_boundary,
        }


@dataclass(frozen=True)
class GraphContext:
    """A compiler context and its explicit node/subnet allowlist."""

    context_id: str
    allowed_node_types: Tuple[str, ...] = ()
    allow_subnets: bool = False
    allowed_subnet_prefixes: Tuple[Tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_id", _stable_identifier(self.context_id, "context_id"))
        node_types = tuple(_stable_identifier(item, "allowed_node_type") for item in (self.allowed_node_types or ()))
        if len(node_types) != len(set(node_types)):
            raise ValueError(f"duplicate allowed node type in {self.context_id}")
        prefixes: List[Tuple[str, ...]] = []
        for prefix in self.allowed_subnet_prefixes or ():
            if isinstance(prefix, str):
                raise ValueError("subnet prefixes must be sequences of segments")
            rendered = tuple(_stable_identifier(item, "subnet_prefix") for item in prefix)
            if any(not _safe_path_segment(item) for item in rendered):
                raise ValueError("subnet prefix contains an unsafe segment")
            prefixes.append(rendered)
        object.__setattr__(self, "allowed_node_types", node_types)
        object.__setattr__(self, "allow_subnets", bool(self.allow_subnets))
        object.__setattr__(self, "allowed_subnet_prefixes", tuple(prefixes))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "allowed_node_types": list(self.allowed_node_types),
            "allow_subnets": self.allow_subnets,
            "allowed_subnet_prefixes": [list(item) for item in self.allowed_subnet_prefixes],
        }


@dataclass(frozen=True)
class NodeCatalog:
    """A named wrapper for an explicit allowlisted node catalogue."""

    nodes: Tuple[NodeSpec, ...]

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes or ())
        if any(not isinstance(item, NodeSpec) for item in nodes):
            raise ValueError("node catalogue entries must be NodeSpec instances")
        names = [item.node_type for item in nodes]
        if len(names) != len(set(names)):
            raise ValueError("node catalogue node types must be unique")
        object.__setattr__(self, "nodes", nodes)

    def as_mapping(self) -> Dict[str, NodeSpec]:
        return {item.node_type: item for item in self.nodes}

    def to_dict(self) -> Dict[str, Any]:
        return {"nodes": [item.to_dict() for item in sorted(self.nodes, key=lambda item: item.node_type)]}


@dataclass(frozen=True)
class GraphNodeProposal:
    """One untrusted node instance proposed by a model or planner."""

    node_id: str
    node_type: str
    context: str = "root"
    subnet_path: Tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subnet_path", tuple(self.subnet_path or ()))
        if isinstance(self.parameters, Mapping):
            object.__setattr__(self, "parameters", dict(self.parameters))

    @property
    def address(self) -> str:
        return _render_address(str(self.context), self.subnet_path, str(self.node_id))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "context": self.context,
            "subnet_path": list(self.subnet_path),
            "parameters": _json_default(self.parameters),
        }


@dataclass(frozen=True)
class GraphConnection:
    """One directed connection between two named ports."""

    source_node: str
    source_port: str
    target_node: str
    target_port: str
    target_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "source_node": self.source_node,
            "source_port": self.source_port,
            "target_node": self.target_node,
            "target_port": self.target_port,
        }
        if self.target_index is not None:
            result["target_index"] = self.target_index
        return result


@dataclass(frozen=True)
class GraphOutput:
    """A named graph output bound to one node output port."""

    output_id: str
    node_id: str
    port: str

    def to_dict(self) -> Dict[str, Any]:
        return {"output_id": self.output_id, "node_id": self.node_id, "port": self.port}


@dataclass(frozen=True)
class GraphProposal:
    """The complete model-facing graph proposal."""

    nodes: Tuple[GraphNodeProposal, ...]
    connections: Tuple[GraphConnection, ...] = ()
    outputs: Tuple[GraphOutput, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes or ()))
        object.__setattr__(self, "connections", tuple(self.connections or ()))
        object.__setattr__(self, "outputs", tuple(self.outputs or ()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "nodes": [item.to_dict() for item in self.nodes],
            "connections": [item.to_dict() for item in self.connections],
            "outputs": [item.to_dict() for item in self.outputs],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphProposal":
        diagnostics: List[GraphDiagnostic] = []
        if not isinstance(value, Mapping):
            raise GraphCompileError(
                [GraphDiagnostic("INVALID_PROPOSAL", "graph proposal must be an object", "$")]
            )
        _check_mapping_keys(value, {"schema_version", "nodes", "connections", "outputs"}, "$", diagnostics)
        schema_version = value.get("schema_version", GRAPH_SCHEMA_VERSION)
        if schema_version != GRAPH_SCHEMA_VERSION:
            diagnostics.append(
                GraphDiagnostic(
                    "SCHEMA_VERSION_UNSUPPORTED",
                    "graph proposal schema_version is unsupported",
                    "$.schema_version",
                    details={"expected": GRAPH_SCHEMA_VERSION, "actual": _json_default(schema_version)},
                )
            )
        nodes_value = value.get("nodes")
        connections_value = value.get("connections", ())
        outputs_value = value.get("outputs", ())
        nodes: List[GraphNodeProposal] = []
        connections: List[GraphConnection] = []
        outputs: List[GraphOutput] = []

        if not isinstance(nodes_value, (list, tuple)):
            diagnostics.append(GraphDiagnostic("INVALID_COLLECTION", "nodes must be an array", "$.nodes"))
        else:
            for index, item in enumerate(nodes_value):
                parsed = _parse_node(item, index, diagnostics)
                if parsed is not None:
                    nodes.append(parsed)

        if not isinstance(connections_value, (list, tuple)):
            diagnostics.append(GraphDiagnostic("INVALID_COLLECTION", "connections must be an array", "$.connections"))
        else:
            for index, item in enumerate(connections_value):
                parsed = _parse_connection(item, index, diagnostics)
                if parsed is not None:
                    connections.append(parsed)

        if not isinstance(outputs_value, (list, tuple)):
            diagnostics.append(GraphDiagnostic("INVALID_COLLECTION", "outputs must be an array", "$.outputs"))
        else:
            for index, item in enumerate(outputs_value):
                parsed = _parse_output(item, index, diagnostics)
                if parsed is not None:
                    outputs.append(parsed)

        if diagnostics:
            raise GraphCompileError(_sorted_diagnostics(diagnostics))
        return cls(tuple(nodes), tuple(connections), tuple(outputs))


@dataclass(frozen=True)
class CompiledNode:
    address: str
    node_id: str
    node_type: str
    context: str
    subnet_path: Tuple[str, ...]
    parameters: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "context": self.context,
            "subnet_path": list(self.subnet_path),
            "parameters": _json_default(self.parameters),
        }


@dataclass(frozen=True)
class CompiledConnection:
    source_node: str
    source_port: str
    target_node: str
    target_port: str
    target_index: Optional[int] = None
    crosses_boundary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "source_node": self.source_node,
            "source_port": self.source_port,
            "target_node": self.target_node,
            "target_port": self.target_port,
            "crosses_boundary": self.crosses_boundary,
        }
        if self.target_index is not None:
            result["target_index"] = self.target_index
        return result


@dataclass(frozen=True)
class CompiledOutput:
    output_id: str
    node_id: str
    port: str

    def to_dict(self) -> Dict[str, Any]:
        return {"output_id": self.output_id, "node_id": self.node_id, "port": self.port}


@dataclass(frozen=True)
class CompiledGraph:
    """Deterministic, still-DCC-neutral output of graph compilation."""

    nodes: Tuple[CompiledNode, ...]
    connections: Tuple[CompiledConnection, ...]
    outputs: Tuple[CompiledOutput, ...]
    execution_order: Tuple[str, ...]
    cycle_boundaries: Tuple[str, ...] = ()
    graph_hash: str = ""
    schema_version: str = GRAPH_SCHEMA_VERSION

    def _payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nodes": [item.to_dict() for item in self.nodes],
            "connections": [item.to_dict() for item in self.connections],
            "outputs": [item.to_dict() for item in self.outputs],
            "execution_order": list(self.execution_order),
            "cycle_boundaries": list(self.cycle_boundaries),
        }

    def to_dict(self) -> Dict[str, Any]:
        result = self._payload()
        result["graph_hash"] = self.graph_hash
        return result


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _check_mapping_keys(
    value: Mapping[str, Any],
    allowed: Iterable[str],
    path: str,
    diagnostics: List[GraphDiagnostic],
) -> None:
    allowed_set = set(allowed)
    unknown = sorted(str(key) for key in value.keys() if key not in allowed_set)
    if not unknown:
        return
    forbidden = [item for item in unknown if item.casefold() in _FORBIDDEN_FIELDS]
    if forbidden:
        diagnostics.append(
            GraphDiagnostic(
                "FORBIDDEN_FIELD",
                "proposal contains a script or command field",
                path,
                details={"fields": forbidden},
            )
        )
    remaining = [item for item in unknown if item not in forbidden]
    if remaining:
        diagnostics.append(
            GraphDiagnostic(
                "UNKNOWN_FIELD",
                "proposal contains unknown fields",
                path,
                details={"fields": remaining},
            )
        )


def _parse_node(value: Any, index: int, diagnostics: List[GraphDiagnostic]) -> Optional[GraphNodeProposal]:
    path = f"$.nodes[{index}]"
    if not isinstance(value, Mapping):
        diagnostics.append(GraphDiagnostic("INVALID_NODE", "node must be an object", path))
        return None
    _check_mapping_keys(value, {"node_id", "node_type", "context", "subnet_path", "parameters"}, path, diagnostics)
    node_id = value.get("node_id")
    node_type = value.get("node_type")
    context = value.get("context", "root")
    subnet_path = value.get("subnet_path", ())
    parameters = value.get("parameters", {})
    if not isinstance(node_id, str) or not node_id.strip():
        diagnostics.append(GraphDiagnostic("INVALID_NODE_ID", "node_id must be a non-empty string", f"{path}.node_id"))
    if not isinstance(node_type, str) or not node_type.strip():
        diagnostics.append(GraphDiagnostic("INVALID_NODE_TYPE", "node_type must be a non-empty string", f"{path}.node_type"))
    if not isinstance(context, str) or not context.strip():
        diagnostics.append(GraphDiagnostic("INVALID_CONTEXT", "context must be a non-empty string", f"{path}.context"))
    if not isinstance(subnet_path, (list, tuple)):
        diagnostics.append(GraphDiagnostic("INVALID_SUBNET_PATH", "subnet_path must be an array", f"{path}.subnet_path"))
        subnet_path = ()
    if not isinstance(parameters, Mapping):
        diagnostics.append(GraphDiagnostic("INVALID_PARAMETERS", "parameters must be an object", f"{path}.parameters"))
        parameters = {}
    if not isinstance(node_id, str) or not isinstance(node_type, str) or not isinstance(context, str):
        return None
    try:
        return GraphNodeProposal(
            node_id=node_id,
            node_type=node_type,
            context=context,
            subnet_path=tuple(subnet_path),
            parameters=dict(parameters),
        )
    except (TypeError, ValueError) as exc:
        diagnostics.append(GraphDiagnostic("INVALID_NODE", str(exc), path))
        return None


def _parse_connection(value: Any, index: int, diagnostics: List[GraphDiagnostic]) -> Optional[GraphConnection]:
    path = f"$.connections[{index}]"
    if not isinstance(value, Mapping):
        diagnostics.append(GraphDiagnostic("INVALID_CONNECTION", "connection must be an object", path))
        return None
    _check_mapping_keys(value, {"source_node", "source_port", "target_node", "target_port", "target_index"}, path, diagnostics)
    required = ("source_node", "source_port", "target_node", "target_port")
    if any(not isinstance(value.get(item), str) or not str(value.get(item)).strip() for item in required):
        diagnostics.append(GraphDiagnostic("INVALID_CONNECTION", "connection endpoints and ports must be non-empty strings", path))
        return None
    target_index = value.get("target_index")
    if target_index is not None and (isinstance(target_index, bool) or not isinstance(target_index, int)):
        diagnostics.append(GraphDiagnostic("INVALID_INPUT_INDEX", "target_index must be a non-negative integer", f"{path}.target_index"))
        return None
    return GraphConnection(
        source_node=str(value["source_node"]),
        source_port=str(value["source_port"]),
        target_node=str(value["target_node"]),
        target_port=str(value["target_port"]),
        target_index=target_index,
    )


def _parse_output(value: Any, index: int, diagnostics: List[GraphDiagnostic]) -> Optional[GraphOutput]:
    path = f"$.outputs[{index}]"
    if not isinstance(value, Mapping):
        diagnostics.append(GraphDiagnostic("INVALID_OUTPUT", "output must be an object", path))
        return None
    _check_mapping_keys(value, {"output_id", "node_id", "port"}, path, diagnostics)
    if any(not isinstance(value.get(item), str) or not str(value.get(item)).strip() for item in ("output_id", "node_id", "port")):
        diagnostics.append(GraphDiagnostic("INVALID_OUTPUT", "output_id, node_id, and port must be non-empty strings", path))
        return None
    return GraphOutput(str(value["output_id"]), str(value["node_id"]), str(value["port"]))


def _sorted_diagnostics(diagnostics: Iterable[GraphDiagnostic]) -> Tuple[GraphDiagnostic, ...]:
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (item.path, item.code, item.message, canonical_json(_json_default(item.details))),
        )
    )


class GraphCompiler:
    """Validate and compile an explicit graph proposal.

    node_catalog and contexts are mandatory. No node type or context is
    discovered dynamically, and this class never imports a DCC module.
    """

    def __init__(
        self,
        node_catalog: Union[NodeCatalog, Mapping[str, NodeSpec], Sequence[NodeSpec]],
        contexts: Union[Mapping[str, GraphContext], Sequence[GraphContext]],
        *,
        max_nodes: int = 512,
        max_connections: int = 1024,
    ) -> None:
        self.node_catalog = self._normalize_catalog(node_catalog)
        self.contexts = self._normalize_contexts(contexts)
        if max_nodes <= 0 or max_connections <= 0:
            raise ValueError("graph compiler limits must be positive")
        self.max_nodes = int(max_nodes)
        self.max_connections = int(max_connections)

    @staticmethod
    def _normalize_catalog(
        node_catalog: Union[NodeCatalog, Mapping[str, NodeSpec], Sequence[NodeSpec]],
    ) -> Dict[str, NodeSpec]:
        if isinstance(node_catalog, NodeCatalog):
            result = node_catalog.as_mapping()
        elif isinstance(node_catalog, Mapping):
            result = {}
            for key, value in node_catalog.items():
                if not isinstance(value, NodeSpec):
                    raise TypeError("node catalogue values must be NodeSpec instances")
                if str(key) != value.node_type:
                    raise ValueError("node catalogue key must match NodeSpec.node_type")
                result[str(key)] = value
        else:
            result = NodeCatalog(tuple(node_catalog)).as_mapping()
        return dict(sorted(result.items(), key=lambda item: item[0]))

    @staticmethod
    def _normalize_contexts(
        contexts: Union[Mapping[str, GraphContext], Sequence[GraphContext]],
    ) -> Dict[str, GraphContext]:
        if isinstance(contexts, Mapping):
            result = {}
            for key, value in contexts.items():
                if not isinstance(value, GraphContext):
                    raise TypeError("contexts values must be GraphContext instances")
                if str(key) != value.context_id:
                    raise ValueError("context key must match GraphContext.context_id")
                result[str(key)] = value
        else:
            values = tuple(contexts)
            if any(not isinstance(item, GraphContext) for item in values):
                raise TypeError("contexts entries must be GraphContext instances")
            result = {item.context_id: item for item in values}
            if len(result) != len(values):
                raise ValueError("context IDs must be unique")
        return dict(sorted(result.items(), key=lambda item: item[0]))

    def validate(self, proposal: Union[GraphProposal, Mapping[str, Any]]) -> Tuple[GraphDiagnostic, ...]:
        """Return all proposal diagnostics without raising."""

        try:
            normalized = self._coerce_proposal(proposal)
        except GraphCompileError as exc:
            return _sorted_diagnostics(exc.diagnostics)
        diagnostics, _ = self._analyze(normalized)
        return _sorted_diagnostics(diagnostics)

    def compile(self, proposal: Union[GraphProposal, Mapping[str, Any]]) -> CompiledGraph:
        """Compile a valid proposal or raise GraphCompileError."""

        normalized = self._coerce_proposal(proposal)
        diagnostics, analysis = self._analyze(normalized)
        errors = [item for item in diagnostics if item.severity == "error"]
        if errors:
            raise GraphCompileError(_sorted_diagnostics(errors))
        return self._build_compiled(analysis)

    @staticmethod
    def _coerce_proposal(proposal: Union[GraphProposal, Mapping[str, Any]]) -> GraphProposal:
        if isinstance(proposal, GraphProposal):
            return proposal
        if isinstance(proposal, Mapping):
            return GraphProposal.from_mapping(proposal)
        raise GraphCompileError([GraphDiagnostic("INVALID_PROPOSAL", "graph proposal must be an object", "$")])

    def _analyze(self, proposal: GraphProposal) -> Tuple[List[GraphDiagnostic], Dict[str, Any]]:
        diagnostics: List[GraphDiagnostic] = []
        if len(proposal.nodes) == 0:
            diagnostics.append(GraphDiagnostic("EMPTY_GRAPH", "graph must contain at least one node", "$.nodes"))
        if len(proposal.nodes) > self.max_nodes:
            diagnostics.append(
                GraphDiagnostic(
                    "GRAPH_LIMIT_EXCEEDED",
                    "graph contains too many nodes",
                    "$.nodes",
                    details={"maximum": self.max_nodes, "actual": len(proposal.nodes)},
                )
            )
        if len(proposal.connections) > self.max_connections:
            diagnostics.append(
                GraphDiagnostic(
                    "GRAPH_LIMIT_EXCEEDED",
                    "graph contains too many connections",
                    "$.connections",
                    details={"maximum": self.max_connections, "actual": len(proposal.connections)},
                )
            )

        nodes_by_address: Dict[str, GraphNodeProposal] = {}
        specs_by_address: Dict[str, NodeSpec] = {}
        ids_to_addresses: Dict[str, List[str]] = {}

        for index, node in enumerate(proposal.nodes):
            path = f"$.nodes[{index}]"
            if not isinstance(node, GraphNodeProposal):
                diagnostics.append(GraphDiagnostic("INVALID_NODE", "node must be a GraphNodeProposal", path))
                continue
            node_valid = True
            if not _safe_path_segment(node.node_id):
                diagnostics.append(GraphDiagnostic("INVALID_NODE_ID", "node_id contains an unsafe path segment", f"{path}.node_id"))
                node_valid = False
            if not _safe_path_segment(node.context):
                diagnostics.append(GraphDiagnostic("INVALID_CONTEXT", "context contains an unsafe path segment", f"{path}.context"))
                node_valid = False
            if not _identifier_is_valid(node.node_type):
                diagnostics.append(GraphDiagnostic("INVALID_NODE_TYPE", "node_type must be a stable identifier", f"{path}.node_type"))
                node_valid = False
            if not isinstance(node.subnet_path, (list, tuple)):
                diagnostics.append(GraphDiagnostic("INVALID_SUBNET_PATH", "subnet_path must be an array", f"{path}.subnet_path"))
                node_valid = False
            else:
                for segment_index, segment in enumerate(node.subnet_path):
                    if not _safe_path_segment(segment):
                        code = "PATH_TRAVERSAL" if str(segment).strip() in {".", ".."} or "/" in str(segment) or "\\" in str(segment) else "INVALID_SUBNET_PATH"
                        diagnostics.append(
                            GraphDiagnostic(
                                code,
                                "subnet_path contains an unsafe segment",
                                f"{path}.subnet_path[{segment_index}]",
                            )
                        )
                        node_valid = False
            context = self.contexts.get(str(node.context))
            if context is None:
                diagnostics.append(
                    GraphDiagnostic(
                        "UNKNOWN_CONTEXT",
                        "node context is not in the supplied context allowlist",
                        f"{path}.context",
                        details={"context": str(node.context)},
                    )
                )
                node_valid = False
            spec = self.node_catalog.get(str(node.node_type))
            if spec is None:
                diagnostics.append(
                    GraphDiagnostic(
                        "UNKNOWN_NODE_TYPE",
                        "node type is not in the supplied node catalogue",
                        f"{path}.node_type",
                        details={"node_type": str(node.node_type)},
                    )
                )
                node_valid = False
            if context is not None and context.allowed_node_types and str(node.node_type) not in context.allowed_node_types:
                diagnostics.append(
                    GraphDiagnostic(
                        "NODE_NOT_ALLOWED_IN_CONTEXT",
                        "node type is not allowed in this context",
                        f"{path}.node_type",
                        details={"context": context.context_id, "node_type": str(node.node_type)},
                    )
                )
                node_valid = False
            if spec is not None and spec.allowed_contexts and str(node.context) not in spec.allowed_contexts:
                diagnostics.append(
                    GraphDiagnostic(
                        "CONTEXT_NOT_ALLOWED_BY_NODE",
                        "node type does not allow this context",
                        f"{path}.context",
                        details={"context": str(node.context), "node_type": spec.node_type},
                    )
                )
                node_valid = False
            if node.subnet_path:
                if context is not None and not context.allow_subnets:
                    diagnostics.append(
                        GraphDiagnostic(
                            "SUBNET_NOT_ALLOWED",
                            "context does not allow subnet placement",
                            f"{path}.subnet_path",
                            details={"context": context.context_id},
                        )
                    )
                    node_valid = False
                if spec is not None and not spec.allow_subnet:
                    diagnostics.append(
                        GraphDiagnostic(
                            "SUBNET_NOT_ALLOWED",
                            "node type does not allow subnet placement",
                            f"{path}.subnet_path",
                            details={"node_type": spec.node_type},
                        )
                    )
                    node_valid = False
                if context is not None and context.allowed_subnet_prefixes:
                    path_tuple = tuple(node.subnet_path)
                    if not any(path_tuple[: len(prefix)] == prefix for prefix in context.allowed_subnet_prefixes):
                        diagnostics.append(
                            GraphDiagnostic(
                                "SUBNET_PATH_NOT_ALLOWED",
                                "subnet path is outside the context allowlist",
                                f"{path}.subnet_path",
                                details={"context": context.context_id},
                            )
                        )
                        node_valid = False
            if not isinstance(node.parameters, Mapping):
                diagnostics.append(GraphDiagnostic("INVALID_PARAMETERS", "parameters must be an object", f"{path}.parameters"))
                node_valid = False
            elif spec is not None:
                node_valid = self._validate_parameters(node.parameters, spec, path, diagnostics) and node_valid
            if not node_valid:
                continue
            address = node.address
            if address in nodes_by_address:
                diagnostics.append(
                    GraphDiagnostic(
                        "DUPLICATE_NODE",
                        "node address must be unique",
                        f"{path}.node_id",
                        details={"address": address},
                    )
                )
                continue
            nodes_by_address[address] = node
            specs_by_address[address] = spec  # type: ignore[assignment]
            ids_to_addresses.setdefault(node.node_id, []).append(address)

        valid_connections: List[Dict[str, Any]] = []
        seen_connections: set = set()
        incoming: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        adjacency: Dict[str, List[str]] = {address: [] for address in nodes_by_address}

        for index, connection in enumerate(proposal.connections):
            path = f"$.connections[{index}]"
            if not isinstance(connection, GraphConnection):
                diagnostics.append(GraphDiagnostic("INVALID_CONNECTION", "connection must be a GraphConnection", path))
                continue
            source_address = self._resolve_node_reference(
                connection.source_node,
                nodes_by_address,
                ids_to_addresses,
                f"{path}.source_node",
                diagnostics,
            )
            target_address = self._resolve_node_reference(
                connection.target_node,
                nodes_by_address,
                ids_to_addresses,
                f"{path}.target_node",
                diagnostics,
            )
            if source_address is None or target_address is None:
                continue
            if not _identifier_is_valid(connection.source_port):
                diagnostics.append(GraphDiagnostic("INVALID_PORT", "source_port must be a stable identifier", f"{path}.source_port"))
                continue
            if not _identifier_is_valid(connection.target_port):
                diagnostics.append(GraphDiagnostic("INVALID_PORT", "target_port must be a stable identifier", f"{path}.target_port"))
                continue
            source_spec = specs_by_address[source_address]
            target_spec = specs_by_address[target_address]
            source_port = source_spec.output_port(connection.source_port)
            target_port = target_spec.input_port(connection.target_port)
            valid = True
            if source_port is None:
                diagnostics.append(
                    GraphDiagnostic(
                        "UNKNOWN_OUTPUT_PORT",
                        "source output port is not declared by the node type",
                        f"{path}.source_port",
                        details={"node": source_address, "port": connection.source_port},
                    )
                )
                valid = False
            if target_port is None:
                diagnostics.append(
                    GraphDiagnostic(
                        "UNKNOWN_INPUT_PORT",
                        "target input port is not declared by the node type",
                        f"{path}.target_port",
                        details={"node": target_address, "port": connection.target_port},
                    )
                )
                valid = False
            crosses_boundary = False
            if source_port is not None and target_port is not None:
                if not _port_types_compatible(source_port.value_type, target_port.value_type):
                    diagnostics.append(
                        GraphDiagnostic(
                            "PORT_TYPE_MISMATCH",
                            "source and target port types are incompatible",
                            path,
                            details={
                                "source_type": source_port.value_type,
                                "target_type": target_port.value_type,
                                "source": f"{source_address}.{source_port.name}",
                                "target": f"{target_address}.{target_port.name}",
                            },
                        )
                    )
                    valid = False
                source_node = nodes_by_address[source_address]
                target_node = nodes_by_address[target_address]
                crosses_boundary = (
                    source_node.context != target_node.context
                    or tuple(source_node.subnet_path) != tuple(target_node.subnet_path)
                )
                if crosses_boundary and not (source_port.boundary and target_port.boundary):
                    diagnostics.append(
                        GraphDiagnostic(
                            "BOUNDARY_NOT_ALLOWLISTED",
                            "cross-context or cross-subnet connection requires boundary ports on both sides",
                            path,
                            details={"source": source_address, "target": target_address},
                        )
                    )
                    valid = False
            if connection.target_index is not None and (
                isinstance(connection.target_index, bool) or not isinstance(connection.target_index, int) or connection.target_index < 0
            ):
                diagnostics.append(GraphDiagnostic("INVALID_INPUT_INDEX", "target_index must be a non-negative integer", f"{path}.target_index"))
                valid = False
            if target_port is not None and not target_port.multiple and connection.target_index not in (None, 0):
                diagnostics.append(
                    GraphDiagnostic(
                        "INVALID_INPUT_INDEX",
                        "single-input ports may only use target_index zero",
                        f"{path}.target_index",
                    )
                )
                valid = False
            key = (source_address, connection.source_port, target_address, connection.target_port, connection.target_index)
            if key in seen_connections:
                diagnostics.append(GraphDiagnostic("DUPLICATE_CONNECTION", "connection is duplicated", path))
                valid = False
            seen_connections.add(key)
            if not valid:
                continue
            edge = {
                "source_node": source_address,
                "source_port": connection.source_port,
                "target_node": target_address,
                "target_port": connection.target_port,
                "target_index": connection.target_index,
                "crosses_boundary": bool(crosses_boundary),
                "proposal_index": index,
            }
            valid_connections.append(edge)
            incoming.setdefault((target_address, connection.target_port), []).append(edge)
            adjacency.setdefault(source_address, []).append(target_address)

        for (target_address, target_port_name), edges in sorted(incoming.items()):
            target_port = specs_by_address[target_address].input_port(target_port_name)
            if target_port is None:
                continue
            if not target_port.multiple and len(edges) > 1:
                diagnostics.append(
                    GraphDiagnostic(
                        "MULTIPLE_CONNECTIONS",
                        "single-input port has multiple incoming connections",
                        f"node[{target_address}].inputs.{target_port_name}",
                        details={"target": target_address, "count": len(edges)},
                    )
                )
            if target_port.multiple:
                indices = [item["target_index"] for item in edges if item["target_index"] is not None]
                missing_indices = len(edges) - len(indices)
                if len(edges) > 1 and missing_indices:
                    diagnostics.append(
                        GraphDiagnostic(
                            "AMBIGUOUS_INPUT_INDEX",
                            "multi-input ports with multiple incoming connections require explicit target_index values",
                            f"node[{target_address}].inputs.{target_port_name}",
                            details={"connections": len(edges), "missing": missing_indices},
                        )
                    )
                if len(indices) != len(set(indices)):
                    diagnostics.append(
                        GraphDiagnostic(
                            "DUPLICATE_INPUT_INDEX",
                            "multi-input connections must use unique target_index values",
                            f"node[{target_address}].inputs.{target_port_name}",
                        )
                    )
                if indices and sorted(indices) != list(range(len(indices))):
                    diagnostics.append(
                        GraphDiagnostic(
                            "INVALID_INPUT_INDEX",
                            "multi-input target_index values must be contiguous from zero",
                            f"node[{target_address}].inputs.{target_port_name}",
                            details={"indices": sorted(indices)},
                        )
                    )

        for address, spec in sorted(specs_by_address.items()):
            for port in spec.inputs:
                if port.required and not incoming.get((address, port.name)):
                    diagnostics.append(
                        GraphDiagnostic(
                            "MISSING_REQUIRED_INPUT",
                            "required input port is not connected",
                            f"node[{address}].inputs.{port.name}",
                            details={"node": address, "port": port.name},
                        )
                    )

        compiled_outputs: List[Dict[str, str]] = []
        output_ids: set = set()
        for index, output in enumerate(proposal.outputs):
            path = f"$.outputs[{index}]"
            if not isinstance(output, GraphOutput):
                diagnostics.append(GraphDiagnostic("INVALID_OUTPUT", "output must be a GraphOutput", path))
                continue
            if not _safe_path_segment(output.output_id):
                diagnostics.append(GraphDiagnostic("INVALID_OUTPUT_ID", "output_id must be a stable identifier", f"{path}.output_id"))
                continue
            if output.output_id in output_ids:
                diagnostics.append(GraphDiagnostic("DUPLICATE_OUTPUT", "output_id must be unique", f"{path}.output_id"))
                continue
            output_ids.add(output.output_id)
            address = self._resolve_node_reference(output.node_id, nodes_by_address, ids_to_addresses, f"{path}.node_id", diagnostics)
            if address is None:
                continue
            if not _identifier_is_valid(output.port):
                diagnostics.append(GraphDiagnostic("INVALID_PORT", "output port must be a stable identifier", f"{path}.port"))
                continue
            if specs_by_address[address].output_port(output.port) is None:
                diagnostics.append(
                    GraphDiagnostic(
                        "UNKNOWN_OUTPUT_PORT",
                        "graph output port is not declared by the node type",
                        f"{path}.port",
                        details={"node": address, "port": output.port},
                    )
                )
                continue
            compiled_outputs.append({"output_id": output.output_id, "node_id": address, "port": output.port})

        cyclic_components, execution_order = self._check_cycles(nodes_by_address, specs_by_address, adjacency, diagnostics)
        cycle_boundaries = sorted(
            address
            for component in cyclic_components
            for address in component
            if specs_by_address[address].cycle_boundary
        )
        return diagnostics, {
            "nodes": nodes_by_address,
            "specs": specs_by_address,
            "connections": valid_connections,
            "outputs": compiled_outputs,
            "execution_order": execution_order,
            "cycle_boundaries": tuple(cycle_boundaries),
        }

    def _validate_parameters(
        self,
        parameters: Mapping[str, Any],
        spec: NodeSpec,
        node_path: str,
        diagnostics: List[GraphDiagnostic],
    ) -> bool:
        valid = True
        declared = {item.name: item for item in spec.parameters}
        for key in parameters.keys():
            if not isinstance(key, str) or not _identifier_is_valid(key):
                diagnostics.append(
                    GraphDiagnostic(
                        "INVALID_PARAMETER_KEY",
                        "parameter keys must be stable identifiers",
                        f"{node_path}.parameters",
                        details={"key": _json_default(key)},
                    )
                )
                valid = False
                continue
            if key.casefold() in _FORBIDDEN_FIELDS:
                diagnostics.append(
                    GraphDiagnostic(
                        "FORBIDDEN_FIELD",
                        "script and command parameters are forbidden",
                        f"{node_path}.parameters.{key}",
                    )
                )
                valid = False
            if key not in declared:
                diagnostics.append(
                    GraphDiagnostic(
                        "UNKNOWN_PARAMETER",
                        "parameter is not declared by the node catalogue",
                        f"{node_path}.parameters.{key}",
                    )
                )
                valid = False
                continue
            if not _parameter_value_valid(declared[key], parameters[key]):
                diagnostics.append(
                    GraphDiagnostic(
                        "INVALID_PARAMETER",
                        "parameter value has the wrong type or is outside its finite range",
                        f"{node_path}.parameters.{key}",
                        details={"expected": declared[key].to_dict(), "actual": _json_default(parameters[key])},
                    )
                )
                valid = False
        for item in spec.parameters:
            if item.name not in parameters:
                if item.required and not item.has_default:
                    diagnostics.append(
                        GraphDiagnostic(
                            "MISSING_REQUIRED_PARAMETER",
                            "required parameter is not supplied",
                            f"{node_path}.parameters.{item.name}",
                        )
                    )
                    valid = False
                elif item.has_default and not _parameter_value_valid(item, item.default):
                    diagnostics.append(
                        GraphDiagnostic(
                            "INVALID_PARAMETER_DEFAULT",
                            "catalogue parameter default is invalid",
                            f"{node_path}.parameters.{item.name}",
                        )
                    )
                    valid = False
        return valid

    @staticmethod
    def _resolve_node_reference(
        value: Any,
        nodes_by_address: Mapping[str, GraphNodeProposal],
        ids_to_addresses: Mapping[str, Sequence[str]],
        path: str,
        diagnostics: List[GraphDiagnostic],
    ) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(GraphDiagnostic("INVALID_REFERENCE", "node reference must be a non-empty string", path))
            return None
        rendered = value.strip()
        if ".." in rendered or "\\" in rendered or rendered.startswith("/"):
            diagnostics.append(GraphDiagnostic("PATH_TRAVERSAL", "node reference contains an unsafe path", path))
            return None
        if rendered in nodes_by_address:
            return rendered
        if "/" in rendered or ":" in rendered:
            diagnostics.append(
                GraphDiagnostic(
                    "UNKNOWN_NODE_REFERENCE",
                    "fully-qualified node reference does not resolve",
                    path,
                    details={"reference": rendered},
                )
            )
            return None
        candidates = tuple(ids_to_addresses.get(rendered, ()))
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            diagnostics.append(
                GraphDiagnostic(
                    "AMBIGUOUS_NODE_REFERENCE",
                    "short node reference matches more than one subnet path",
                    path,
                    details={"reference": rendered, "candidates": sorted(candidates)},
                )
            )
        else:
            diagnostics.append(
                GraphDiagnostic(
                    "UNKNOWN_NODE_REFERENCE",
                    "node reference does not resolve",
                    path,
                    details={"reference": rendered},
                )
            )
        return None

    @staticmethod
    def _check_cycles(
        nodes_by_address: Mapping[str, GraphNodeProposal],
        specs_by_address: Mapping[str, NodeSpec],
        adjacency: Mapping[str, Sequence[str]],
        diagnostics: List[GraphDiagnostic],
    ) -> Tuple[List[Tuple[str, ...]], Tuple[str, ...]]:
        nodes = tuple(sorted(nodes_by_address))
        normalized_adjacency = {node: tuple(sorted(set(adjacency.get(node, ())))) for node in nodes}
        components = _strongly_connected_components(nodes, normalized_adjacency)
        cyclic: List[Tuple[str, ...]] = []
        for component in components:
            is_self_loop = len(component) == 1 and component[0] in normalized_adjacency.get(component[0], ())
            if len(component) <= 1 and not is_self_loop:
                continue
            cyclic.append(component)
            boundaries = [item for item in component if specs_by_address[item].cycle_boundary]
            if not boundaries:
                diagnostics.append(
                    GraphDiagnostic(
                        "CYCLE_DETECTED",
                        "graph contains a cycle without a catalogue-approved cycle boundary",
                        f"nodes[{component[0]}]",
                        details={"nodes": list(component)},
                    )
                )
        indegree = {node: 0 for node in nodes}
        for source in nodes:
            for target in normalized_adjacency[source]:
                indegree[target] += 1
        ready = [node for node, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        order: List[str] = []
        while ready:
            source = heapq.heappop(ready)
            order.append(source)
            for target in normalized_adjacency[source]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    heapq.heappush(ready, target)
        if len(order) != len(nodes):
            order.extend(sorted(set(nodes) - set(order)))
        return cyclic, tuple(order)

    def _build_compiled(self, analysis: Mapping[str, Any]) -> CompiledGraph:
        nodes: List[CompiledNode] = []
        for address, node in sorted(analysis["nodes"].items()):
            spec = analysis["specs"][address]
            values = dict(node.parameters)
            for parameter in spec.parameters:
                if parameter.name not in values and parameter.has_default:
                    values[parameter.name] = parameter.default
            nodes.append(
                CompiledNode(
                    address=address,
                    node_id=node.node_id,
                    node_type=node.node_type,
                    context=node.context,
                    subnet_path=tuple(node.subnet_path),
                    parameters={key: values[key] for key in sorted(values)},
                )
            )
        connections = tuple(
            CompiledConnection(
                source_node=item["source_node"],
                source_port=item["source_port"],
                target_node=item["target_node"],
                target_port=item["target_port"],
                target_index=item["target_index"],
                crosses_boundary=item["crosses_boundary"],
            )
            for item in sorted(
                analysis["connections"],
                key=lambda edge: (
                    edge["target_node"],
                    edge["target_port"],
                    edge["target_index"] is None,
                    edge["target_index"] if edge["target_index"] is not None else -1,
                    edge["source_node"],
                    edge["source_port"],
                ),
            )
        )
        outputs = tuple(
            CompiledOutput(**item)
            for item in sorted(analysis["outputs"], key=lambda item: (item["output_id"], item["node_id"], item["port"]))
        )
        provisional = CompiledGraph(
            nodes=tuple(nodes),
            connections=connections,
            outputs=outputs,
            execution_order=tuple(analysis["execution_order"]),
            cycle_boundaries=tuple(analysis["cycle_boundaries"]),
        )
        return CompiledGraph(
            nodes=provisional.nodes,
            connections=provisional.connections,
            outputs=provisional.outputs,
            execution_order=provisional.execution_order,
            cycle_boundaries=provisional.cycle_boundaries,
            graph_hash=canonical_sha256(provisional._payload()),
            schema_version=provisional.schema_version,
        )


def _port_types_compatible(source_type: str, target_type: str) -> bool:
    source = source_type.lower()
    target = target_type.lower()
    if source == target or target == "any":
        return True
    if source == "any":
        return False
    if target == "number" and source in {"int", "float", "number"}:
        return True
    if target == "float" and source == "int":
        return True
    return False


def _parameter_value_valid(spec: ParameterSpec, value: Any) -> bool:
    value_type = spec.value_type
    if value is None:
        return False
    if value_type == "bool":
        return isinstance(value, bool)
    if value_type == "int":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif value_type in {"float", "number"}:
        valid = _finite_number(value)
    elif value_type == "string":
        valid = isinstance(value, str)
    elif value_type == "path":
        valid = isinstance(value, str) and _safe_relative_path(value)
    elif value_type == "enum":
        valid = isinstance(value, str) and value in spec.enum_values
    else:
        valid = False
    if not valid:
        return False
    if value_type in {"int", "float", "number"}:
        if not _finite_number(value):
            return False
        if spec.minimum is not None and value < spec.minimum:
            return False
        if spec.maximum is not None and value > spec.maximum:
            return False
    return True


def _safe_relative_path(value: str) -> bool:
    rendered = value.strip()
    if (
        not rendered
        or "\x00" in rendered
        or rendered.startswith(("/", "\\"))
        or ":" in rendered
    ):
        return False
    if "\\" in rendered:
        return False
    return all(segment not in {"", ".", ".."} for segment in rendered.split("/"))


def _strongly_connected_components(
    nodes: Sequence[str],
    adjacency: Mapping[str, Sequence[str]],
) -> List[Tuple[str, ...]]:
    index = 0
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: set = set()
    components: List[Tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency.get(node, ())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: List[str] = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            components.append(tuple(sorted(component)))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return sorted(components)


__all__ = (
    "GRAPH_SCHEMA_VERSION",
    "CompiledConnection",
    "CompiledGraph",
    "CompiledNode",
    "CompiledOutput",
    "GraphCompileError",
    "GraphCompiler",
    "GraphConnection",
    "GraphContext",
    "GraphDiagnostic",
    "GraphNodeProposal",
    "GraphOutput",
    "GraphProposal",
    "NodeCatalog",
    "NodeSpec",
    "ParameterSpec",
    "PortSpec",
)
