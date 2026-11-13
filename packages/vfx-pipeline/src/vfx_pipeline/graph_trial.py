"""Fail-closed native Houdini SOP executor for trusted compiled graphs.

This trial intentionally has no DCC logic beyond the structured bridge commands
used by the existing Houdini registry.  The caller must establish a scene lease before invoking this low-level executor.
It does not provide scene isolation or visual acceptance.
"""
from __future__ import annotations

import hashlib
import re
from threading import Lock
from collections.abc import Mapping, MutableMapping
from types import MappingProxyType
from typing import Any, Protocol
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.graph_compiler import (
    CompiledGraph,
    GraphConnection,
    GraphNodeProposal,
    GraphOutput,
    GraphProposal,
)
from vfx_pipeline import graph_catalog
_CONTEXT = "houdini_sop"
# Copy the repository's trusted catalog once; callers cannot inject a native
# type mapping through a graph payload.
_NATIVE_TYPES = MappingProxyType(dict(graph_catalog.NATIVE_TYPES))
_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_ALLOWED = frozenset({"node.children", "node.create", "node.connect", "node.set_parms", "scene.create_task_root", "node.info"})
class JournalStore(Protocol):
    def read(self, operation_id: str) -> Mapping[str, Any] | None: ...
    def write(self, operation_id: str, value: Mapping[str, Any]) -> None: ...
class TaskGraphJournal:
    """Persist graph intents in the owning pipeline task's record store."""

    def __init__(self, store: Any, task_id: str, graph_id: str) -> None:
        store.get_task(task_id)
        self.store, self.task_id, self.graph_id = store, task_id, graph_id

    def _key(self, operation_id: str) -> str:
        return canonical_sha256({"graph_id": self.graph_id, "operation_id": operation_id})

    def read(self, operation_id: str) -> Mapping[str, Any] | None:
        key = self._key(operation_id)
        for row in self.store.records(self.task_id, "graph_operation"):
            if row.get("journal_key") == key:
                return dict(row["operation"])
        return None

    def write(self, operation_id: str, value: Mapping[str, Any]) -> None:
        key = self._key(operation_id)
        self.store.put_record(self.task_id, "graph_operation", key, {
            "journal_key": key, "graph_id": self.graph_id, "operation": dict(value),
        })


class GraphExecutor:
    """Construct a trusted compiled graph in a task-owned SOP network."""
    def __init__(self, client: Any, journal: JournalStore | MutableMapping[str, Any], *, lease_guard=None) -> None:
        self.client = client
        self.journal = journal
        self.lease_guard = lease_guard
        self._execution_lock = Lock()
    def execute(self, task_id: str, graph: CompiledGraph) -> dict[str, Any]:
        with self._execution_lock:
            return self._execute(task_id, graph)
    def _execute(self, task_id: str, graph: CompiledGraph) -> dict[str, Any]:
        diagnostics = self._validate_graph(graph)
        digest = self._digest(graph) if isinstance(graph, CompiledGraph) else "unknown"
        root_digest = hashlib.sha256((str(task_id) + ":" + digest).encode()).hexdigest()
        root = f"/obj/BRIDGE_GRAPH_{root_digest}"
        base = {
            "task_id": str(task_id), "graph_hash": digest, "root": root,
            "construction_executed": False, "visual_verified": False,
            "reconciliation_required": bool(diagnostics),
        }
        if diagnostics:
            return {**base, "topology": None, "diagnostics": diagnostics}
        if self.lease_guard is None:
            return {**base, "reconciliation_required": True, "topology": None,
                    "diagnostics": [{"code": "SCENE_LEASE_REQUIRED", "message": "controller scene lease guard required before construction"}]}
        self._task_id, self._root = str(task_id), root
        root_type = graph_catalog.native_root_type(graph)
        operations = self._operations(graph, root)
        operation_map = dict(operations)
        try:
            blocked = self._journal_preflight(operations)
        except Exception as exc:
            blocked = [{"code": "RECONCILIATION_REQUIRED", "message": f"journal cannot be read: {exc}"}]
        if blocked:
            return {**base, "reconciliation_required": True, "topology": None, "diagnostics": blocked}
        # Queries happen before each create, and every command is from the
        # allowlist.  No cook/cache/render/python operation can reach client.
        try:
            parent_nodes = self._children("/obj")
            root_item = self._exact(parent_nodes, root)
            root_id = f"{graph.graph_hash}:root:create"
            root_intent = operation_map[root_id]
            if root_item is None:
                root_result = self._run(root_id, root_intent, "scene.create_task_root", {
                    "task_id": str(task_id), "parent": "/obj", "type": root_type,
                    "root_layout": "object_subnet/1" if root_type == "subnet" else "sop_geo/1",
                    "root_name": root.rsplit("/", 1)[1],
                })
                self._expect_path(root_result, root, root_type)
            elif str(root_item.get("type")) != root_type:
                raise ValueError("task root exists with an unexpected type")
            elif self._journal_state(root_id) != "COMPLETE":
                raise ValueError("pre-existing task root has no completed journal record")
            paths: dict[str, str] = {}
            by_address = {node.address: node for node in graph.nodes}
            layout = graph_catalog.native_layout(graph, root)
            # Parent containers precede their children even when a boundary
            # dependency runs from a child output back to its container.
            schedule = graph_catalog.bounded_domain_schedule(graph)
            creation_parameters = schedule.get('creation_parameters', {}) if schedule else {}
            ordered = sorted(graph.execution_order, key=lambda a: (layout[a]["path"].count("/"), graph.execution_order.index(a)))
            stages = schedule['stages'] if schedule else [{'nodes':ordered,'connections':list(range(len(graph.connections)))}]
            topology_connections = []
            for stage in stages:
                for address in stage['nodes']:
                    node = by_address[address]
                    parent = layout[address]["parent"]
                    children = self._children(parent)
                    expected_path = layout[address]["path"]
                    item = self._exact(children, expected_path)
                    native = layout[address]["type"]
                    create_id = f"{graph.graph_hash}:node:{node.address}:create"
                    create_intent = operation_map[create_id]
                    if item is None:
                        create_params = {
                            "parent": parent, "type": native, "name": node.node_id,
                            "task_id": str(task_id), "exact_type_name": True,
                        }
                        if address in creation_parameters:
                            create_params['parms'] = dict(creation_parameters[address])
                        result = self._run(create_id, create_intent, "node.create", create_params)
                        self._expect_path(result, expected_path, native)
                    elif str(item.get("type")) != native:
                        raise ValueError(f"node exists with unexpected type: {expected_path}")
                    elif self._journal_state(create_id) != "COMPLETE":
                        raise ValueError(f"pre-existing node has no completed journal record: {expected_path}")
                    paths[address] = expected_path
                for node in (by_address[a] for a in stage['nodes']):
                    if not node.parameters:
                        continue
                    op_id = f"{graph.graph_hash}:node:{node.address}:parms"
                    intent = operation_map[op_id]
                    result = self._run(op_id, intent, "node.set_parms", {
                        "path": paths[node.address], "parms": dict(node.parameters),
                        "task_id": str(task_id),
                    })
                    self._expect_path(result, paths[node.address])
                for conn in (graph.connections[i] for i in stage['connections']):
                    op_id = self._connection_id(graph, conn)
                    intent = operation_map[op_id]
                    source = paths[conn.source_node]
                    target = paths[conn.target_node]
                    binding = graph_catalog.connection_binding(graph, conn)
                    if binding.get('input_name') or binding.get('output_name'):
                        binding = graph_catalog.resolve_connection_binding(binding,
                            self._query('node.info',{'path':source,'native_port_names':True}),
                            self._query('node.info',{'path':target,'native_port_names':True}))
                    if binding["kind"] == "reference":
                        field = binding["field"]
                        if field.startswith("@"):
                            topology_connections.append({"source": source, "destination": target,
                                                         "kind": "container_dependency", "field": field})
                            continue
                        result = self._run(op_id, intent, "node.set_parms", {
                            "path": target, "parms": {field: source}, "task_id": str(task_id),
                        })
                        self._expect_path(result, target)
                        topology_connections.append({"source": source, "destination": target,
                                                     "kind": "reference", "field": field})
                        continue
                    input_index = binding["input_index"]
                    params = {"source": source, "destination": target, "input_index": input_index,
                              "task_id": str(task_id)}
                    if binding["output_index"]:
                        params["output_index"] = binding["output_index"]
                    result = self._run(op_id, intent, "node.connect", params)
                    if str(result.get("source")) != source or str(result.get("destination")) != target:
                        raise ValueError("node.connect returned an unexpected topology")
                    entry = {"source": source, "destination": target, "input_index": input_index}
                    if binding["output_index"]:
                        entry["output_index"] = binding["output_index"]
                    topology_connections.append(entry)
        except Exception as exc:
            return {**base, "reconciliation_required": True, "topology": None,
                    "diagnostics": [{"code": "EXECUTION_UNKNOWN", "message": str(exc)}]}
        return {**base, "construction_executed": True, "reconciliation_required": False,
                "topology": {"root": root, "nodes": paths, "connections": topology_connections}}
    def _validate_graph(self, graph: Any) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        if not isinstance(graph, CompiledGraph):
            return [{"code": "INCOMPLETE_GRAPH", "message": "a CompiledGraph is required"}]
        if graph.schema_version != "1.0":
            errors.append({"code": "UNKNOWN_SCHEMA", "message": "compiled graph schema is unsupported"})
        try:
            supplied = graph.to_dict()
            if graph.graph_hash != canonical_sha256({key: value for key, value in supplied.items() if key != "graph_hash"}):
                errors.append({"code": "GRAPH_HASH_MISMATCH", "message": "compiled graph hash is not self-consistent"})
            if graph.graph_hash and len(graph.graph_hash) != 64:
                errors.append({"code": "INVALID_GRAPH_HASH", "message": "compiled graph hash is malformed"})
            if any(node.node_type not in _NATIVE_TYPES for node in graph.nodes):
                errors.append({"code": "NATIVE_TYPE_UNALLOWLISTED", "message": "node type has no fixed native binding"})
            if any(node.address != f"{node.context}:/{'/'.join(tuple(node.subnet_path) + (node.node_id,))}" or not _SAFE_ID.fullmatch(str(node.node_id)) for node in graph.nodes):
                errors.append({"code": "ADDRESS_INVALID", "message": "compiled node address is not canonical"})
            expected_order = {node.address for node in graph.nodes}
            if len(graph.execution_order) != len(set(graph.execution_order)) or set(graph.execution_order) != expected_order:
                errors.append({"code": "EXECUTION_ORDER_INVALID", "message": "execution order does not cover nodes exactly once"})
            address_to_id = {n.address: n.address for n in graph.nodes}
            proposal = GraphProposal(
                nodes=tuple(GraphNodeProposal(n.node_id, n.node_type, n.context, tuple(n.subnet_path), dict(n.parameters)) for n in graph.nodes),
                connections=tuple(GraphConnection(address_to_id.get(c.source_node, c.source_node), c.source_port, address_to_id.get(c.target_node, c.target_node), c.target_port, c.target_index) for c in graph.connections),
                outputs=tuple(GraphOutput(o.output_id, address_to_id.get(o.node_id, o.node_id), o.port) for o in graph.outputs),
            )
            trusted = graph_catalog.compiler().compile(proposal)
            if trusted.to_dict() != supplied:
                errors.append({"code": "CATALOG_MISMATCH", "message": "compiled graph differs from the trusted graph catalog"})
            errors.extend(graph_catalog.execution_diagnostics(trusted))
        except Exception as exc:
            errors.append({"code": "GRAPH_INVALID", "message": str(exc)})
        return errors
    @staticmethod
    def _digest(graph: CompiledGraph) -> str:
        return str(graph.graph_hash or "unknown")
    @staticmethod
    def _connection_id(graph: CompiledGraph, conn: Any) -> str:
        # Keep the original ID for unambiguous legacy wires. Distinct named
        # port lanes must not share a journal key (constraints output 0/1/2).
        base = f"{graph.graph_hash}:connect:{conn.source_node}:{conn.target_node}:{conn.target_index}"
        collisions = sum((c.source_node, c.target_node, c.target_index) ==
                         (conn.source_node, conn.target_node, conn.target_index) for c in graph.connections)
        return base if collisions == 1 else f"{base}:{conn.source_port}:{conn.target_port}"
    @staticmethod
    def _operations(graph: CompiledGraph, root: str) -> list[tuple[str, dict[str, Any]]]:
        digest = graph.graph_hash
        result = [(f"{digest}:root:create", {"kind": "root.create", "path": root, "type": graph_catalog.native_root_type(graph)})]
        layout = graph_catalog.native_layout(graph, root)
        schedule = graph_catalog.bounded_domain_schedule(graph)
        creation_parameters = schedule.get('creation_parameters', {}) if schedule else {}
        for node in graph.nodes:
            intent = {"kind": "node.create", "address": node.address, "path": layout[node.address]["path"], "type": layout[node.address]["type"], "exact_type_name": True}
            if node.address in creation_parameters:
                intent['parameters'] = dict(creation_parameters[node.address])
            result.append((f"{digest}:node:{node.address}:create", intent))
        for node in graph.nodes:
            result.append((f"{digest}:node:{node.address}:parms", {"kind": "node.set_parms", "address": node.address, "parameters": dict(node.parameters)}))
        for conn in graph.connections:
            result.append((GraphExecutor._connection_id(graph, conn), {"kind": "node.connect", "source": conn.source_node, "target": conn.target_node, "index": conn.target_index, "source_port": conn.source_port, "target_port": conn.target_port}))
        if schedule:
            result.append((f"{digest}:domain:initialize",{'kind':'domain.initialize','identity':schedule['identity'],
                'schedule_sha256':schedule['schedule_sha256']}))
        return result
    def _journal_preflight(self, operations: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        entries = [(op_id, intent, self._read(op_id)) for op_id, intent in operations]
        blocked = []
        for op_id, intent, entry in entries:
            if entry is None:
                continue
            if entry.get("intent") != intent or entry.get("status") != "COMPLETE" or not isinstance(entry.get("result"), Mapping):
                blocked.append({"code": "RECONCILIATION_REQUIRED", "message": f"journal operation is incomplete or inconsistent: {op_id}"})
        # The structured bridge cannot read SOP input wiring or prove parameter
        # state.  Never replay completed results and claim the host still has
        # the same topology; an operator/reconciler must inspect it first.
        if not blocked and any(entry is not None for _, _, entry in entries):
            blocked.append({"code": "RECONCILIATION_REQUIRED", "message": "completed graph operations require host topology revalidation before reuse"})
        return blocked
    def _run(self, op_id: str, intent: dict[str, Any], command: str, params: dict[str, Any]) -> Mapping[str, Any]:
        if command not in _ALLOWED:
            raise ValueError(f"command is outside the construction allowlist: {command}")
        entry = self._read(op_id)
        if entry is not None:
            if entry.get("intent") != intent or entry.get("status") != "COMPLETE" or not isinstance(entry.get("result"), Mapping):
                raise ValueError(f"operation requires reconciliation: {op_id}")
            return dict(entry["result"])
        pending = {"operation_id": op_id, "status": "INTENT", "intent": intent}
        if callable(getattr(self.journal, "claim", None)):
            if not self.journal.claim(op_id, pending):
                raise ValueError("operation was claimed by another executor; reconciliation required")
        else:
            self._write(op_id, pending)
        try:
            self.lease_guard(self._task_id, self._root, command, params)
            result = self.client.call(command, params)
            if not isinstance(result, Mapping):
                raise ValueError("bridge returned a non-object result")
            result = dict(result)
        except Exception as exc:
            self._write(op_id, {"operation_id": op_id, "status": "UNKNOWN", "intent": intent, "error": str(exc)})
            raise
        self._write(op_id, {"operation_id": op_id, "status": "COMPLETE", "intent": intent, "result": result})
        return result
    def _children(self, path: str) -> list[dict[str, Any]]:
        result = self._query("node.children", {"path": path})
        nodes = result.get("nodes")
        if not isinstance(nodes, list):
            raise ValueError("node.children returned no node list")
        return [dict(item) for item in nodes if isinstance(item, Mapping)]
    def _query(self, command: str, params: dict[str, Any]) -> Mapping[str, Any]:
        if command not in _ALLOWED:
            raise ValueError("query command is outside the construction allowlist")
        self.lease_guard(self._task_id, self._root, command, params)
        result = self.client.call(command, params)
        if not isinstance(result, Mapping):
            raise ValueError("bridge returned a non-object result")
        return result
    @staticmethod
    def _exact(nodes: list[dict[str, Any]], path: str) -> dict[str, Any] | None:
        return next((node for node in nodes if str(node.get("path")) == path), None)
    @staticmethod
    def _expect_path(result: Mapping[str, Any], path: str, node_type: str | None = None) -> None:
        if str(result.get("path")) != path or (node_type is not None and str(result.get("type")) != node_type):
            raise ValueError(f"bridge returned an unexpected path or type for {path}")
    def _journal_state(self, op_id: str) -> str | None:
        entry = self._read(op_id)
        return str(entry.get("status")) if entry else None
    def _read(self, op_id: str) -> Mapping[str, Any] | None:
        if isinstance(self.journal, MutableMapping):
            value = self.journal.get(op_id)
        elif hasattr(self.journal, "read"):
            value = self.journal.read(op_id)
        else:
            value = self.journal.get(op_id)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("journal entry is malformed")
        return value
    def _write(self, op_id: str, value: Mapping[str, Any]) -> None:
        if isinstance(self.journal, MutableMapping):
            self.journal[op_id] = dict(value)
        elif hasattr(self.journal, "write"):
            self.journal.write(op_id, dict(value))
        else:
            self.journal.put(op_id, dict(value))
__all__ = ["GraphExecutor", "JournalStore", "TaskGraphJournal"]
