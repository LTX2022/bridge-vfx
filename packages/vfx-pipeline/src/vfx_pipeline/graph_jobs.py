"""Durable, construction-only graph jobs for a task-owned Houdini process.

The service in this module is deliberately small.  It owns the graph and job
records, launches one fresh worker for one registered graph, and exposes only
the safe public result written by that worker.  DCC execution itself lives in
``graph_job_worker`` so reconnecting a controller can never accidentally replay
an uncertain launch.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import sqlite3
import subprocess
import threading
import time
import re
import sys
from contextlib import contextmanager, closing
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from dcc_task_runtime.canonical import canonical_json, canonical_sha256
from dcc_task_runtime.graph_compiler import CompiledGraph, GraphProposal

from . import graph_catalog
from .graph_construction_inputs import freeze_construction_inputs
from .graph_job_evidence import (PROTOCOL, atomic_json, owned_file, read_json,
    file_sha256, runtime_fingerprint, process_identity, process_status, owned_group_status)
from .graph_scheduler import GraphScheduler, SchedulerBusy
from .paths import installation_scheduler_root


MAX_NODES = 8
MAX_CONNECTIONS = 16
MAX_OUTPUTS = 8
MAX_OPERATIONS = 3
REGISTERED_SOP_TYPES = graph_catalog.LEGACY_SOP_TYPES
REGISTERED_NATIVE_TYPES = graph_catalog.validate_catalog()
JOB_BUDGET_SECONDS = 120.0
STATES = frozenset({"PREPARED", "STARTING", "RUNNING", "SUCCEEDED", "FAILED", "RECONCILIATION_REQUIRED", "CANCELLED"})
ACTIVE_STATES = frozenset({"PREPARED", "STARTING", "RUNNING", "RECONCILIATION_REQUIRED"})
_PUBLIC_RESULT_KEYS = frozenset({
    "schema_version", "operation_id", "graph_id", "graph_hash", "construction_executed",
    "visual_verified", "reconciliation_required", "topology", "diagnostics", "artifact",
    "hip_path", "hip_sha256", "parameters", "verification", "native_operation_evidence",
})
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class GraphJobError(ValueError):
    """A caller-facing graph job error with no private process details."""


def _request_id(value: Any, name: str = "request_id") -> str:
    rendered = str(value or "").strip()
    if not _ID_PATTERN.fullmatch(rendered):
        raise GraphJobError(f"{name} must be a non-empty bounded identifier")
    return rendered


def _safe_json(value: Any) -> str:
    return canonical_json(value)


def _load_json(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _public_result(value: Any, *, root: Path, operation_id: str, graph_id: str,
                   root_task_id: str | None = None, attempt_token: str | None = None,
                   attempt_generation: int | None = None) -> dict[str, Any]:
    """Schema-bound output: no diagnostic text or arbitrary nested paths."""
    value = value if isinstance(value, Mapping) else {}
    safe: dict[str, Any] = {
        "schema_version": "bridge.graph_job/1.0",
        "operation_id": operation_id, "graph_id": graph_id,
        "visual_verified": False,
    }
    for key in ("construction_executed", "reconciliation_required"):
        if type(value.get(key)) is bool:
            safe[key] = value[key]
    graph_hash = value.get("graph_hash")
    if isinstance(graph_hash, str) and re.fullmatch(r"[0-9a-f]{64}", graph_hash):
        safe["graph_hash"] = graph_hash
    verification = value.get("verification")
    contract_digest = None
    if isinstance(verification, Mapping) and 'registered_scene_contract_sha256' in verification:
        contract_digest = verification['registered_scene_contract_sha256']
        if (type(contract_digest) is not str or re.fullmatch(r'[0-9a-f]{64}', contract_digest) is None
                or 'graph_hash' not in safe):
            raise GraphJobError('REGISTERED_SCENE_CONTRACT_INVALID')
    scope = value.get("validation_scope")
    safe["validation_scope"] = scope if isinstance(scope, str) and scope in {"software_test", "software_fake_host", "host_construction_only"} else "unverified"
    diagnostics = value.get("diagnostics")
    known_codes = {
        "GRAPH_EXECUTION_UNPROVEN", "GRAPH_RECOMPILE_REJECTED", "JOB_DEADLINE_EXCEEDED",
        "WORKER_RECONCILIATION_REQUIRED", "RECONCILIATION_REQUIRED", "EXECUTION_UNKNOWN",
    }
    if isinstance(diagnostics, list):
        safe["diagnostics"] = [{"code": d.get("code") if d.get("code") in known_codes else "WORKER_RECONCILIATION_REQUIRED"}
                               for d in diagnostics[:8] if isinstance(d, Mapping) and isinstance(d.get("code"), str)]
    # The only permitted filesystem artifact is this operation's named HIP.
    # Return a relative locator, never a machine-specific absolute path.
    artifact = value.get("artifact")
    if isinstance(artifact, Mapping):
        candidate = artifact.get("hip_path") or artifact.get("path")
        try:
            candidate_path = Path(str(candidate))
            path = owned_file(root, candidate_path if candidate_path.is_absolute() else root / candidate_path, required=False)
            relative = path.relative_to(root)
            if (relative.parts[:2] == ("graph-jobs", operation_id)
                    and path.name == operation_id + ".hip"):
                digest = artifact.get("hip_sha256") or artifact.get("sha256")
                if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                    safe["artifact"] = {"path": relative.as_posix(), "sha256": digest}
        except (OSError, RuntimeError, ValueError):
            pass
    # Host node paths are not filesystem paths. Accept only the generated root
    # for this exact operation/hash and bounded canonical node addresses.
    if "graph_hash" in safe:
        import hashlib
        root_task_id = str(root_task_id or operation_id)
        node_root = "/obj/BRIDGE_GRAPH_" + hashlib.sha256((root_task_id + ":" + safe["graph_hash"]).encode()).hexdigest()
        def node_path(item):
            return isinstance(item, str) and (item == node_root or (
                item.startswith(node_root + "/") and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}(?:/[A-Za-z_][A-Za-z0-9_]{0,99}){0,7}", item[len(node_root)+1:])))
        from vfx_pipeline.graph_catalog import descriptor
        known_reference_fields = {name for binding in descriptor()["native_bindings"] for name in binding.get("references",{}).values()}
        def connection(item):
            if not isinstance(item,Mapping) or not node_path(item.get("source")) or not node_path(item.get("destination")):
                return None
            kind = item.get("kind","wire")
            if kind in {"reference","container_dependency"}:
                field = item.get("field")
                if field not in known_reference_fields or (kind == "container_dependency") != str(field).startswith("@"):
                    return None
                return {"source":item["source"],"destination":item["destination"],"kind":kind,"field":field}
            if kind != "wire" or type(item.get("input_index")) is not int or not 0 <= item["input_index"] < 64:
                return None
            output_index = item.get("output_index",0)
            if type(output_index) is not int or not 0 <= output_index < 64:
                return None
            result = {"source":item["source"],"destination":item["destination"],"input_index":item["input_index"]}
            if output_index:
                result["output_index"] = output_index
            return result
        topology = value.get("topology")
        if isinstance(topology, Mapping) and topology.get("root") == node_root:
            nodes = topology.get("nodes", {})
            connections = topology.get("connections", [])
            safe["topology"] = {
                "root": node_root,
                "nodes": {k: v for k, v in list(nodes.items())[:max(MAX_NODES,graph_catalog.registered_domain_limits()["nodes"])]
                          if isinstance(k, str) and re.fullmatch(r"houdini_(?:sop|obj|dop|lop|vop|rop):/[A-Za-z_][A-Za-z0-9_]{0,99}(?:/[A-Za-z_][A-Za-z0-9_]{0,99}){0,7}", k) and node_path(v)} if isinstance(nodes, Mapping) else {},
                "connections": [result for item in connections[:max(MAX_CONNECTIONS,graph_catalog.registered_domain_limits()["connections"])] if (result := connection(item)) is not None] if isinstance(connections,list) else [],
            }
        verification = value.get("verification")
        if isinstance(verification, Mapping):
            safe["verification"] = {k: verification[k] for k in ("nodes_verified", "parameters_verified", "connections_verified")
                                    if type(verification.get(k)) is bool}
            if contract_digest is not None:
                safe['verification']['registered_scene_contract_sha256'] = contract_digest
    evidence = value.get("native_operation_evidence")
    if (isinstance(evidence, Mapping)
            and evidence.get("schema") == "bridge.houdini.native-command-evidence/2.0"
            and evidence.get("task_id") == str(root_task_id or operation_id)
            and evidence.get("operation_id") == operation_id
            and "graph_hash" in safe and evidence.get("graph_hash") == safe["graph_hash"]
            and isinstance(attempt_token, str) and _ID_PATTERN.fullmatch(attempt_token)
            and evidence.get("attempt_token") == attempt_token
            and type(attempt_generation) is int and attempt_generation > 0
            and type(evidence.get("attempt_generation")) is int
            and evidence["attempt_generation"] == attempt_generation
            and type(evidence.get("count")) is int and 0 < evidence["count"] <= 4096
            and type(evidence.get("bytes")) is int and 0 < evidence["bytes"] <= 64 * 1024 * 1024
            and isinstance(evidence.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])):
        try:
            candidate_path = Path(str(evidence.get("path")))
            path = owned_file(root, candidate_path if candidate_path.is_absolute() else root / candidate_path, required=False)
            relative = path.relative_to(root)
            expected = ("graph-jobs", operation_id, f"attempt-{attempt_generation}",
                        operation_id + ".native-operations.json")
            if relative.parts == expected:
                safe["native_operation_evidence"] = {key: evidence[key] for key in (
                    "schema", "task_id", "operation_id", "graph_hash", "attempt_token",
                    "attempt_generation", "count", "bytes", "sha256")}
                safe["native_operation_evidence"]["path"] = relative.as_posix()
        except (OSError, RuntimeError, ValueError):
            pass
    return safe


class GraphJobService:
    """Persistent controller for bounded graph construction trials.

    ``subprocess_factory`` is injectable for unit tests and follows the small
    subset of :class:`subprocess.Popen` used by this service.  ``worker_factory``
    is an optional test seam which receives a job dictionary and may return a
    result mapping or a process-like object.  Production always launches the
    repository worker through the supplied ``hython_path``.
    """

    def __init__(
        self,
        root: os.PathLike[str] | str,
        repo_root: os.PathLike[str] | str,
        hython_path: os.PathLike[str] | str,
        *,
        subprocess_factory: Optional[Callable[..., Any]] = None,
        worker_factory: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.time,
        scheduler_root: Optional[os.PathLike[str] | str] = None,
        task_id: Optional[str] = None,
        resource_budget: Optional[Mapping[str, Any]] = None,
        software_launch_script: Optional[os.PathLike[str] | str] = None,
        software_launch_script_sha256: Optional[str] = None,
        software_processes: bool = False,
        frozen_input_manifest: Any = None,
    ) -> None:
        try:
            manifest = freeze_construction_inputs(frozen_input_manifest)
        except ValueError as error:
            raise GraphJobError(str(error)) from error
        self._frozen_input_manifest_json = _safe_json(manifest)
        self._frozen_inputs_sha256 = canonical_sha256(manifest)
        self.software_launch_script = None
        self.software_launch_sha256 = None
        if software_launch_script is not None:
            script = Path(software_launch_script).expanduser()
            if software_processes is not True:
                raise GraphJobError("SOFTWARE_PROCESS_BOUNDARY_NOT_AUTHORIZED")
            if not script.is_absolute() or script.is_symlink() or not script.is_file():
                raise GraphJobError("SOFTWARE_LAUNCH_SCRIPT_INVALID")
            self.software_launch_script = str(script.resolve())
            self.software_launch_sha256 = file_sha256(script)
            if (software_launch_script_sha256 is not None
                    and software_launch_script_sha256 != self.software_launch_sha256):
                raise GraphJobError("SOFTWARE_LAUNCH_SCRIPT_CHANGED")
        self.root = Path(root).expanduser().resolve()
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.hython_path = str(hython_path)
        scoped_budget = dict(resource_budget) if resource_budget is not None else None
        self.job_budget_seconds = JOB_BUDGET_SECONDS
        if (scoped_budget or {}).get('native_scope') is not None:
            if scheduler_root is None:
                raise GraphJobError('PRODUCTION_NATIVE_SCOPE_SCHEDULER_REQUIRED')
            from .production_hosts import native_scope_budget
            scoped_budget = native_scope_budget(scoped_budget['native_scope'], scoped_budget, self.root, scheduler_root)
            from dcc_task_runtime.native_scope import NativeScope
            self.job_budget_seconds = NativeScope(scoped_budget['native_scope']).role_seconds('graph-worker')
        if scoped_budget is not None:
            configured_seconds = scoped_budget.get('max_seconds', self.job_budget_seconds)
            if (type(configured_seconds) not in (int, float) or not math.isfinite(configured_seconds)
                    or not 0 < configured_seconds <= self.job_budget_seconds):
                raise GraphJobError('OPERATION_BUDGET_INVALID')
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = self.root / "graph-jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "graph_jobs.sqlite3"
        self.clock = clock
        self.subprocess_factory = subprocess_factory or subprocess.Popen
        self._uses_default_subprocess = subprocess_factory is None
        self.worker_factory = worker_factory
        self.task_id = _request_id(task_id, "task_id") if task_id is not None else None
        self.resource_budget = scoped_budget
        self._budget_guards = {}
        self._lock = threading.RLock()
        self._processes: dict[str, Any] = {}
        self._process_tokens: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._all_threads: list[threading.Thread] = []
        self._thread_deadlines: dict[threading.Thread, float] = {}
        self._closed = threading.Event()
        self.scheduler = GraphScheduler(Path(scheduler_root) if scheduler_root is not None else installation_scheduler_root())
        self._test_mode = (worker_factory is not None or subprocess_factory is not None
                           or self.software_launch_script is not None)
        self._init_db()
        self._mark_ambiguous_after_reconnect()

    @property
    def frozen_input_manifest(self) -> list[dict[str, Any]]:
        return json.loads(self._frozen_input_manifest_json)

    @property
    def frozen_inputs_sha256(self) -> str:
        return self._frozen_inputs_sha256

    def _construction_inputs(self, intent, *, verify_files=True):
        if not isinstance(intent, dict):
            raise GraphJobError("construction input intent invalid")
        legacy = "frozen_input_manifest" not in intent and "frozen_inputs_sha256" not in intent
        value = [] if legacy else intent.get("frozen_input_manifest")
        if type(value) is not list:
            raise GraphJobError("construction input persisted manifest invalid")
        try:
            manifest = freeze_construction_inputs(value, verify_files=False)
            digest = canonical_sha256(manifest)
            if (not legacy and intent.get("frozen_inputs_sha256") != digest
                    or digest != self.frozen_inputs_sha256):
                raise GraphJobError("construction input manifest drift; original intent required")
            if verify_files:
                manifest = freeze_construction_inputs(manifest)
        except ValueError as error:
            raise GraphJobError(str(error)) from error
        return manifest, digest

    def bind_task(self, task_id: str) -> str:
        """Bind graph-owned roots to the controller's durable pipeline task."""
        value = _request_id(task_id, "task_id")
        if self.task_id is not None and self.task_id != value:
            raise GraphJobError("graph service is already bound to another task")
        self.task_id = value
        return value

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10, check_same_thread=False)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=10000")
            deadline = time.monotonic() + 10
            while True:
                try:
                    db.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                        raise
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS graph_requests (
                    request_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS graphs (
                    graph_id TEXT PRIMARY KEY,
                    proposal_json TEXT NOT NULL,
                    compiled_json TEXT NOT NULL,
                    catalog_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trial_requests (
                    request_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deadline_at REAL NOT NULL,
                    pid INTEGER,
                    process_token TEXT,
                    result_json TEXT,
                    error_code TEXT,
                    UNIQUE(graph_id, request_id)
                );
                CREATE INDEX IF NOT EXISTS operations_state ON operations(state);
                """
            )
            # Serialize upgrades of an existing operations table.  The schema
            # must be re-read *after* the write lock is acquired: two desktop
            # controllers may have inspected the same old schema concurrently.
            # SQLite ALTER TABLE is transactional here, so a mid-migration
            # failure rolls back the complete field set rather than publishing
            # a partially upgraded schedulable schema.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(operations)")}
            for name, definition in {
                "attempt_generation": "INTEGER NOT NULL DEFAULT 0",
                "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
                "stop_confirmed": "INTEGER NOT NULL DEFAULT 0",
                "process_identity_json": "TEXT",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE operations ADD COLUMN {name} {definition}")
                    columns.add(name)

    def _mark_ambiguous_after_reconnect(self) -> None:
        # PREPARED is written before a launch and STARTING before Popen.  If a
        # controller restarts before it can observe the child, either state is
        # ambiguous; RUNNING is ambiguous too because its PID may be reused.
        with self._connect() as db:
            db.execute(
                "UPDATE operations SET state='RECONCILIATION_REQUIRED', updated_at=?, error_code=? "
                "WHERE state IN ('PREPARED','STARTING','RUNNING')",
                (self.clock(), "RECONNECT_AMBIGUOUS_STARTUP"),
            )
            legacy = db.execute("SELECT operation_id FROM operations WHERE attempt_generation=0 AND state IN ('PREPARED','STARTING','RUNNING','RECONCILIATION_REQUIRED')").fetchall()
        for row in legacy:
            self.scheduler.register_legacy(str(self.root), str(row[0]))

    @staticmethod
    def _proposal_payload(proposal: Any) -> Any:
        if isinstance(proposal, GraphProposal):
            return proposal.to_dict()
        if isinstance(proposal, Mapping):
            return dict(proposal)
        return proposal

    def _strict_compile(self, proposal: Any) -> tuple[CompiledGraph, str]:
        # The common trusted catalog performs schema, context, native-parent
        # and port-binding checks before the unchanged per-job bounds.
        compiled = graph_catalog.compile_proposal(proposal)
        schedule = graph_catalog.bounded_domain_schedule(compiled)
        if schedule is None:
            if len(compiled.nodes) > MAX_NODES:
                raise GraphJobError(f"graph contains more than {MAX_NODES} nodes")
            if len(compiled.connections) > MAX_CONNECTIONS:
                raise GraphJobError(f"graph contains more than {MAX_CONNECTIONS} connections")
        elif any(len(stage['nodes']) > MAX_NODES or len(stage['connections']) > MAX_CONNECTIONS for stage in schedule['stages']):
            raise GraphJobError("registered domain exceeds a bounded construction stage")
        if not compiled.outputs:
            raise GraphJobError("graph must declare at least one output")
        if len(compiled.outputs) > MAX_OUTPUTS:
            raise GraphJobError(f"graph contains more than {MAX_OUTPUTS} outputs")
        if graph_catalog.validate_catalog() != REGISTERED_NATIVE_TYPES:
            raise GraphJobError("registered native catalogue is incomplete")
        blocked = graph_catalog.execution_diagnostics(compiled)
        if blocked:
            raise GraphJobError("unsupported native binding: " + str(blocked[0]["message"]))
        catalog_hash = str(graph_catalog.descriptor().get("catalog_hash") or "")
        return compiled, catalog_hash

    def controller_binding(self) -> dict[str, Any]:
        """Return a path-free controller identity for task-level binding.

        This is evidence about which durable job store/runtime/scheduler a
        trusted controller is using.  It deliberately exposes only digests,
        never local paths, and is not an authorization result.
        """
        return {
            "schema": "bridge.graph-controller-binding/1.0",
            "controller_root_sha256": canonical_sha256(str(self.root)),
            "repo_runtime_sha256": runtime_fingerprint(self.repo_root),
            "scheduler_root_sha256": canonical_sha256(str(self.scheduler.root)),
            "job_budget_seconds": self.job_budget_seconds,
            "software_test_mode": bool(self._test_mode),
            "software_launch_binding_sha256": canonical_sha256({
                "path": self.software_launch_script, "sha256": self.software_launch_sha256}),
        }

    def lookup_trial(self, request_id: str) -> Optional[str]:
        """Read the durable operation bound to a stable trial request.

        A missing row proves that the lower-level intent transaction did not
        commit.  Callers may then retry *the same request ID*; they must never
        mint a new ID to escape an unknown outcome.
        """
        request_id = _request_id(request_id)
        with self._connect() as db:
            row = db.execute("SELECT operation_id FROM trial_requests WHERE request_id=?", (request_id,)).fetchone()
        return str(row["operation_id"]) if row is not None else None

    def has_graph(self, graph_id: str) -> bool:
        graph_id = _request_id(graph_id, "graph_id")
        with self._connect() as db:
            row = db.execute("SELECT 1 FROM graphs WHERE graph_id=?", (graph_id,)).fetchone()
        return row is not None

    def propose(self, proposal: Any, request_id: str) -> str:
        """Compile and register one graph, with request-ID idempotency."""

        request_id = _request_id(request_id)
        payload = self._proposal_payload(proposal)
        try:
            payload_hash = canonical_sha256(payload)
        except (TypeError, ValueError) as exc:
            raise GraphJobError("proposal contains unsupported or non-finite values") from exc
        with self._lock:
            with self._connect() as db:
                existing = db.execute("SELECT * FROM graph_requests WHERE request_id=?", (request_id,)).fetchone()
                if existing:
                    if existing["payload_hash"] != payload_hash:
                        raise GraphJobError("request_id was reused with a different proposal")
                    return str(existing["graph_id"])
            compiled, catalog_hash = self._strict_compile(proposal)
            compiled_json = _safe_json(compiled.to_dict())
            graph_id = "graph_" + canonical_sha256({"compiled": compiled.to_dict(), "catalog_hash": catalog_hash})
            now = self.clock()
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT * FROM graph_requests WHERE request_id=?", (request_id,)).fetchone()
                if existing:
                    if existing["payload_hash"] != payload_hash:
                        raise GraphJobError("request_id was reused with a different proposal")
                    return str(existing["graph_id"])
                db.execute(
                    "INSERT OR IGNORE INTO graphs(graph_id,proposal_json,compiled_json,catalog_hash,created_at) VALUES(?,?,?,?,?)",
                    (graph_id, _safe_json(payload), compiled_json, catalog_hash, now),
                )
                db.execute(
                    "INSERT INTO graph_requests(request_id,payload_hash,graph_id,created_at) VALUES(?,?,?,?)",
                    (request_id, payload_hash, graph_id, now),
                )
            return graph_id

    def trial(self, graph_id: str, request_id: str) -> str:
        """Reserve installation ownership before durably scheduling one attempt."""
        graph_id = _request_id(graph_id, "graph_id")
        request_id = _request_id(request_id)
        payload_hash = canonical_sha256({"graph_id": graph_id, "request_id": request_id})
        operation_id = "op_" + payload_hash
        with self._lock:
            if self._closed.is_set():
                raise GraphJobError("graph job service is closed")
            reservation = None
            try:
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    prior = db.execute("SELECT * FROM trial_requests WHERE request_id=?", (request_id,)).fetchone()
                    if prior:
                        if prior["payload_hash"] != payload_hash or prior["operation_id"] != operation_id:
                            raise GraphJobError("request_id was reused with a different trial")
                        original = db.execute("SELECT * FROM operations WHERE operation_id=?",
                                              (operation_id,)).fetchone()
                        if original is None:
                            raise GraphJobError("original trial intent missing")
                        self._operation_budget(original)
                        self._construction_inputs(_load_json(original["intent_json"]), verify_files=False)
                        return str(prior["operation_id"])
                    graph = db.execute("SELECT * FROM graphs WHERE graph_id=?", (graph_id,)).fetchone()
                    if graph is None:
                        raise GraphJobError("graph_id is not registered")
                    if db.execute("SELECT 1 FROM operations WHERE state IN ('PREPARED','STARTING','RUNNING','RECONCILIATION_REQUIRED') LIMIT 1").fetchone():
                        raise GraphJobError("another graph trial is active or requires reconciliation")
                    if int(db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]) >= MAX_OPERATIONS:
                        raise GraphJobError(f"service root permits at most {MAX_OPERATIONS} graph trials")
                    compiled = _load_json(graph["compiled_json"], {})
                    fresh, catalog_hash = self._strict_compile(_load_json(graph["proposal_json"], {}))
                    if fresh.to_dict() != compiled or catalog_hash != graph["catalog_hash"]:
                        raise GraphJobError("registered graph or catalogue has changed")
                    now = self.clock()
                    intent = {
                        "schema_version": PROTOCOL, "operation_id": operation_id,
                        "graph_id": graph_id, "request_id": request_id,
                        "task_id": str(self.task_id or operation_id),
                        "graph_hash": compiled.get("graph_hash"),
                        "catalog_hash": catalog_hash, "runtime_sha256": runtime_fingerprint(self.repo_root),
                        "proposal_hash": canonical_sha256(_load_json(graph["proposal_json"], {})),
                        "repo_root": str(self.repo_root), "scheduler_root": str(self.scheduler.root),
                        "validation_scope": "software_test" if self._test_mode else "host_construction_only",
                        "software_launch_script": self.software_launch_script,
                        "software_launch_script_sha256": self.software_launch_sha256,
                        "frozen_input_manifest": self.frozen_input_manifest,
                        "frozen_inputs_sha256": self.frozen_inputs_sha256,
                        "budget_started_at": now, "job_budget_seconds": self.job_budget_seconds,
                        "deadline_at": now + self.job_budget_seconds,
                        "native_scope_budget": (self.resource_budget
                            if (self.resource_budget or {}).get('native_scope') is not None else None),
                    }
                    self._construction_inputs(intent)
                    reservation = self.scheduler.reserve(str(self.root), operation_id)
                    db.execute("INSERT INTO trial_requests VALUES(?,?,?,?)", (request_id, payload_hash, operation_id, now))
                    db.execute("""INSERT INTO operations(operation_id,graph_id,request_id,payload_hash,state,intent_json,
                        created_at,updated_at,deadline_at,process_token,attempt_generation)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (operation_id, graph_id, request_id, payload_hash, "PREPARED",
                        _safe_json(intent), now, now, intent['deadline_at'], reservation["token"], reservation["generation"]))
            except BaseException as exc:
                # No launch thread exists here. An ordinary rollback is safely
                # releasable; process death between commits leaves a durable
                # orphan which reconcile_orphan() must explicitly fence.
                if reservation is not None:
                    if self.scheduler.fence_unstarted(str(self.root), operation_id, reservation["token"]):
                        self.scheduler.release(str(self.root), operation_id, reservation["token"], unstarted=True)
                if isinstance(exc, SchedulerBusy):
                    raise GraphJobError(str(exc)) from exc
                raise
            self._schedule(operation_id, compiled, reservation["token"], reservation["generation"])
            return operation_id

    def _schedule(self, operation_id, graph_payload, token, generation):
        thread = threading.Thread(target=self._launch, args=(operation_id, graph_payload, token, generation),
                                  name="bridge-graph-monitor", daemon=True)
        self._threads[operation_id] = thread
        self._all_threads.append(thread)
        remaining = self._remaining_seconds(self._row(operation_id))
        self._thread_deadlines[thread] = time.monotonic() + remaining
        try:
            thread.start()
        except Exception:
            self._unknown(operation_id, token, "MONITOR_START_FAILED")
            raise GraphJobError("job remains prepared for explicit reconciliation") from None

    def compiled_graph(self, graph_id: str) -> dict[str, Any]:
        """Registered compiled graph payload (controller-owned, C3)."""
        with self._connect() as db:
            row = db.execute("SELECT compiled_json FROM graphs WHERE graph_id=?", (str(graph_id),)).fetchone()
        if row is None:
            raise GraphJobError("graph_id is not registered")
        return _load_json(row["compiled_json"], {})

    def _row(self, operation_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise GraphJobError("operation_id is not registered")
        return row

    def _operation_budget(self, row):
        intent = _load_json(row['intent_json'], {})
        scope_budget = intent.get('native_scope_budget')
        current_scope = (self.resource_budget
            if (self.resource_budget or {}).get('native_scope') is not None else None)
        legacy = 'job_budget_seconds' not in intent
        if legacy:
            if self.job_budget_seconds > JOB_BUDGET_SECONDS:
                raise GraphJobError('persisted native scope budget missing')
            seconds = JOB_BUDGET_SECONDS
        else:
            seconds = intent.get('job_budget_seconds')
            started = intent.get('budget_started_at')
            if (type(seconds) not in (int, float) or seconds != self.job_budget_seconds
                    or scope_budget != current_scope
                    or type(started) not in (int, float) or not math.isfinite(started)
                    or not row['created_at'] <= started <= max(row['created_at'], row['updated_at'])
                    or seconds > JOB_BUDGET_SECONDS and started != row['created_at']
                    or intent.get('deadline_at') != row['deadline_at']):
                raise GraphJobError('persisted operation budget changed')
        deadline = row['deadline_at']
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not row['created_at'] < deadline
                or legacy and deadline > max(row['created_at'], row['updated_at']) + seconds
                or not legacy and deadline != started + seconds):
            raise GraphJobError('persisted operation deadline exceeds budget')
        return seconds

    def operation_deadline(self, operation_id):
        """Trusted controller readback of the original durable deadline."""
        row = self._row(_request_id(operation_id, 'operation_id'))
        self._operation_budget(row)
        return float(row['deadline_at'])

    def _remaining_seconds(self, row):
        seconds = self._operation_budget(row)
        remaining = min(seconds, float(row['deadline_at']) - self.clock())
        thread = self._threads.get(row['operation_id'])
        if thread in self._thread_deadlines:
            remaining = min(remaining, self._thread_deadlines[thread] - time.monotonic())
        return max(0.0, remaining)

    def _prepare_fenced_retry(self, row, reservation):
        """Only an installation-fenced legacy attempt may receive a new clock."""
        fields = dict(process_token=reservation['token'], attempt_generation=reservation['generation'],
            pid=None, process_identity_json=None, result_json=None, error_code=None, stop_confirmed=0)
        if self.job_budget_seconds > JOB_BUDGET_SECONDS:
            return self._set_state(row['operation_id'], 'PREPARED',
                expected_state='RECONCILIATION_REQUIRED', expected_token=row['process_token'], **fields)
        started = self.clock()
        intent = _load_json(row['intent_json'], {})
        deadline = started + JOB_BUDGET_SECONDS
        if 'job_budget_seconds' in intent:
            intent.update(budget_started_at=started, deadline_at=deadline)
        with self._connect() as database:
            return database.execute("""UPDATE operations SET state='PREPARED',updated_at=?,
                process_token=?,attempt_generation=?,pid=NULL,process_identity_json=NULL,result_json=NULL,
                error_code=NULL,stop_confirmed=0,deadline_at=?,intent_json=?
                WHERE operation_id=? AND state='RECONCILIATION_REQUIRED' AND process_token=? AND cancel_requested=0""",
                (started, reservation['token'], reservation['generation'], deadline, _safe_json(intent),
                 row['operation_id'], row['process_token'])).rowcount == 1

    @staticmethod
    def _task_id_for_row(row) -> str:
        intent = _load_json(row["intent_json"], {})
        return str(intent.get("task_id") or row["operation_id"])

    def _worker_paths(self, operation_id: str, generation: Optional[int] = None) -> dict[str, Path]:
        if generation is None:
            generation = int(self._row(operation_id)["attempt_generation"])
        directory = self.jobs_dir / operation_id / f"attempt-{generation}"
        owned_file(self.root, directory, required=False)
        directory.mkdir(parents=True, exist_ok=True)
        return {"directory": directory, **{key: directory / name for key, name in {
            "proposal": "proposal.json", "graph": "compiled.json", "result": "result.json",
            "journal": "journal.sqlite3", "lease": "scene_lease.sqlite3", "error": "error.txt",
            "inputs": "inputs.json", "identity": "worker_identity.json", "completion": "completion.json",
        }.items()}}

    def _set_state(self, operation_id, state, *, expected_state=None, expected_token=None, **fields):
        if state not in STATES:
            raise ValueError("invalid graph job state")
        assignments, values = ["state=?", "updated_at=?"], [state, self.clock()]
        for key in ("pid", "process_token", "result_json", "error_code", "attempt_generation", "cancel_requested",
                    "stop_confirmed", "process_identity_json"):
            if key in fields:
                assignments.append(f"{key}=?"); values.append(fields[key])
        where = "operation_id=?"; values.append(operation_id)
        # Terminal states can never be overwritten by an unqualified caller.
        states = (expected_state,) if isinstance(expected_state, str) else tuple(expected_state or ACTIVE_STATES)
        where += " AND state IN (" + ",".join("?" for _ in states) + ")"; values.extend(states)
        if expected_token is not None:
            where += " AND process_token=?"; values.append(expected_token)
        with self._connect() as db:
            return db.execute(f"UPDATE operations SET {', '.join(assignments)} WHERE {where}", values).rowcount == 1

    def _unknown(self, operation_id, token, code):
        return self._set_state(operation_id, "RECONCILIATION_REQUIRED",
            expected_state=("PREPARED", "STARTING", "RUNNING"), expected_token=token, error_code=code)

    def _claim_start(self, operation_id, token):
        if self._closed.is_set():
            return False
        with self._connect() as db:
            cursor = db.execute("""UPDATE operations SET state='STARTING',updated_at=?
                WHERE operation_id=? AND state='PREPARED' AND process_token=? AND cancel_requested=0""",
                (self.clock(), operation_id, token))
            return cursor.rowcount == 1

    def _budget_guard(self, operation_id, token):
        if self.resource_budget is None:
            return None
        if operation_id not in self._budget_guards:
            from .controller_media import OperationBudgetGuard
            owner = {"task_id": self._task_id_for_row(self._row(operation_id)),
                     "operation_id": operation_id, "launch_nonce": token}
            seconds = self._operation_budget(self._row(operation_id))
            configured_seconds = self.resource_budget.get('max_seconds', seconds)
            if (type(configured_seconds) not in (int, float) or not math.isfinite(configured_seconds)
                    or not 0 < configured_seconds <= seconds):
                raise GraphJobError('OPERATION_BUDGET_INVALID')
            self._budget_guards[operation_id] = OperationBudgetGuard(
                [Path(item) for item in self.resource_budget["roots"]],
                max_bytes=self.resource_budget["max_bytes"], owner=owner,
                stop_callback=lambda bound: self.cancel(bound["operation_id"]),
                max_seconds=min(seconds, configured_seconds),
                **({'native_scope': self.resource_budget['native_scope'], 'scope_role': 'graph-worker'}
                   if self.resource_budget.get('native_scope') is not None else {}))
        return self._budget_guards[operation_id]

    def _launch(self, operation_id, graph_payload, token, generation):
        try:
            if not self._claim_start(operation_id, token):
                return
            paths = self._worker_paths(operation_id, generation)
            row = self._row(operation_id)
            self._operation_budget(row)
            intent = _load_json(row["intent_json"], {})
            frozen_manifest, frozen_digest = self._construction_inputs(intent)
            graph_record = self._graph_record_for_operation(operation_id)
            if graph_record is None or runtime_fingerprint(self.repo_root) != intent.get("runtime_sha256"):
                raise ValueError("runtime changed before launch")
            if (intent.get("software_launch_script") != self.software_launch_script
                    or intent.get("software_launch_script_sha256") != self.software_launch_sha256):
                raise ValueError("software launch configuration changed before launch")
            proposal = _load_json(graph_record["proposal_json"], {})
            atomic_json(paths["proposal"], proposal, root=self.root)
            atomic_json(paths["graph"], graph_payload, root=self.root)
            inputs = {**intent, "attempt_token": token, "attempt_generation": generation,
                      "frozen_input_manifest": frozen_manifest, "frozen_inputs_sha256": frozen_digest,
                      "proposal_sha256": file_sha256(paths["proposal"]), "compiled_sha256": file_sha256(paths["graph"])}
            atomic_json(paths["inputs"], inputs, root=self.root)
            job = {
                "schema_version": PROTOCOL, "operation_id": operation_id, "graph_id": str(row["graph_id"]),
                "root": str(self.root), "repo_root": str(self.repo_root),
                "task_id": self._task_id_for_row(row),
                **{key + "_path": str(paths[name]) for key, name in {
                    "graph": "graph", "proposal": "proposal", "result": "result", "journal": "journal",
                    "lease": "lease", "error": "error", "inputs": "inputs", "identity": "identity", "completion": "completion",
                }.items()},
                "deadline_at": float(row["deadline_at"]), "attempt_token": token, "attempt_generation": generation,
                "scheduler_root": str(self.scheduler.root), "validation_scope": intent["validation_scope"],
                "frozen_input_manifest": frozen_manifest, "frozen_inputs_sha256": frozen_digest,
                **{key: intent[key] for key in ('budget_started_at', 'job_budget_seconds',
                                               'deadline_at', 'native_scope_budget') if key in intent},
            }
            if self._closed.is_set():
                self._unknown(operation_id, token, "CLOSED_BEFORE_DISPATCH")
                return
            guard = self._budget_guard(operation_id, token)
            if guard is not None:
                budget = guard.check(owner=guard.owner, phase="preflight",
                    elapsed_seconds=self._operation_budget(row) - self._remaining_seconds(row))
                if budget["status"] != "PASS":
                    self._set_state(operation_id, "FAILED", expected_state="STARTING", expected_token=token,
                                    stop_confirmed=1, error_code="RESOURCE_PREFLIGHT_FAILED")
                    self.scheduler.release(str(self.root), operation_id, token, stopped=True)
                    return
            if self.worker_factory is None:
                worker = self.repo_root / "packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py"
                argv = [self.hython_path, str(worker), "--job", _safe_json(job)]
                if self.software_launch_script is not None:
                    if file_sha256(Path(self.software_launch_script)) != self.software_launch_sha256:
                        raise GraphJobError("SOFTWARE_LAUNCH_SCRIPT_CHANGED")
                    argv.insert(1, self.software_launch_script)
                if len(subprocess.list2cmdline(argv).encode('utf-16-le')) // 2 + 1 > 32767:
                    from .graph_job_worker import _parse_job_file
                    job_file = paths['directory'] / 'worker-job.json'
                    atomic_json(job_file, job, root=self.root)
                    job_digest = file_sha256(job_file)
                    if _parse_job_file(str(job_file), job_digest) != job:
                        raise GraphJobError('WORKER_JOB_FILE_CHANGED')
                    argv[-2:] = ['--job-file', str(job_file), '--job-file-sha256', job_digest]
                if len(subprocess.list2cmdline(argv).encode('utf-16-le')) // 2 + 1 > 32767:
                    raise GraphJobError('WORKER_COMMAND_LINE_TOO_LONG')
            self._construction_inputs(intent)
            if self._remaining_seconds(self._row(operation_id)) <= 0:
                self._set_state(operation_id, 'FAILED', expected_state='STARTING', expected_token=token,
                                stop_confirmed=1, error_code='JOB_DEADLINE_EXCEEDED')
                self.scheduler.release(str(self.root), operation_id, token, stopped=True)
                return
            self.scheduler.arm(str(self.root), operation_id, token)
            if self.worker_factory is not None:
                process = self.worker_factory(dict(job))
            else:
                if self._uses_default_subprocess:
                    from dcc_task_runtime.owned_process import launch
                    supervisor_directory = paths["directory"] / "owned-supervisor"
                    supervisor_identity = self._supervisor_identity(row)
                    environment = self._worker_env(paths["directory"])
                    environment["BRIDGE_OWNED_SUPERVISOR_DIR"] = str(supervisor_directory)
                    environment["BRIDGE_OWNED_SUPERVISOR_IDENTITY"] = _safe_json(supervisor_identity)
                    scope_options = ({"scope_role":"graph-worker", "scope_heavy":True}
                                     if (self.resource_budget or {}).get("native_scope") is not None else {})
                    remaining = self._remaining_seconds(self._row(operation_id))
                    if remaining <= 0:
                        raise TimeoutError('graph construction budget exceeded before launch')
                    process = launch(argv, directory=supervisor_directory,
                        identity=supervisor_identity,
                        supervisor_executable=str(Path(sys.executable).resolve()),
                        env=environment,
                        budget_seconds=remaining,
                        resource_budget=self.resource_budget, **scope_options)
                else:
                    process = self._invoke_subprocess(argv, paths["directory"])
            if isinstance(process, Mapping):
                # Explicit software seam, never durable host certification.
                result = {**dict(process), "validation_scope": "software_test", "visual_verified": False}
                if self._set_state(operation_id, "RUNNING", expected_state="STARTING", expected_token=token, stop_confirmed=1):
                    self._finish(operation_id, result, token=token)
                else:
                    self._record_stopped(operation_id, token)
                return
            if not callable(getattr(process, "poll", None)) or type(getattr(process, "pid", None)) is not int:
                raise RuntimeError("worker did not expose an owned process handle")
            with self._lock:
                self._processes[operation_id] = process
                self._process_tokens[operation_id] = token
            identity = process_identity(process.pid)
            identity.pop("state", None)
            # The worker may win this race by binding itself before its first
            # host call. Compare birth identity, not transient process state.
            self.scheduler.bind_process(str(self.root), operation_id, token, identity)
            with self._connect() as db:
                db.execute("UPDATE operations SET pid=?,process_identity_json=? WHERE operation_id=? AND process_token=?",
                           (process.pid, _safe_json(identity), operation_id, token))
            self._set_state(operation_id, "RUNNING", expected_state="STARTING", expected_token=token)
            if self._closed.is_set() or self._row(operation_id)["cancel_requested"]:
                self.cancel(operation_id)
            self._monitor(operation_id, process, token, paths)
        except Exception:
            self._unknown(operation_id, token, "LAUNCH_OUTCOME_UNKNOWN")

    def _operation_graph(self, operation_id):
        return str(self._row(operation_id)["graph_id"])

    def _graph_record_for_operation(self, operation_id):
        with self._connect() as db:
            return db.execute("SELECT g.* FROM graphs g JOIN operations o ON o.graph_id=g.graph_id WHERE o.operation_id=?", (operation_id,)).fetchone()

    def _worker_env(self, task_directory: Path) -> dict[str, str]:
        env = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "HOUDINI_PATH", "HSITE", "HOUDINI_OTLSCAN_PATH", "HOUDINI_PACKAGE_DIR", "HOUDINI_SCRIPT_PATH"):
            env.pop(key, None)
        for key in ("BRIDGE_OWNED_SUPERVISOR_DIR", "BRIDGE_OWNED_SUPERVISOR_IDENTITY"):
            env.pop(key, None)
        env["PYTHONNOUSERSITE"] = "1"
        control = self.root.parent
        env["HOUDINI_BRIDGE_STATE_DIR"] = str(control / "graph-houdini-instances")
        env["HOUDINI_BRIDGE_TASK_STATE_DIR"] = str(control / "houdini-instances")
        env["BRIDGE_SKILLS_STATE_ROOT"] = str(control / "graph-runtime-state")
        env["BRIDGE_ARTIFACT_LEDGER_ROOT"] = str(control / "artifact_ledger")
        pref = task_directory / "houdini-user-pref"
        pref.mkdir(parents=True, exist_ok=True)
        env["HOUDINI_USER_PREF_DIR"] = str(pref / "__HVER__")
        if (self.resource_budget or {}).get('native_scope') is not None:
            temporary = task_directory/'tmp'
            temporary.mkdir(parents=True, exist_ok=True)
            env.update(TMPDIR=str(temporary.resolve()), PYTHONDONTWRITEBYTECODE='1')
        return env

    def _invoke_subprocess(self, argv, task_directory):
        # Call exactly once. TypeError can happen AFTER a factory has spawned;
        # it is never a reason to retry with a different argument signature.
        return self.subprocess_factory(argv, cwd=str(task_directory), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env=self._worker_env(task_directory))

    def _owned_process(self, operation_id, process, token):
        with self._lock:
            return self._processes.get(operation_id) is process and self._process_tokens.get(operation_id) == token

    @staticmethod
    def _supervisor_identity(row):
        return {"operation_id": str(row["operation_id"]), "attempt_token": str(row["process_token"]),
                "generation": int(row["attempt_generation"])}

    def _supervised_handle(self, row):
        from dcc_task_runtime.owned_process import OwnedProcessHandle
        directory = self._worker_paths(row["operation_id"])["directory"] / "owned-supervisor"
        if not directory.is_dir():
            return None
        try:
            return OwnedProcessHandle(directory, self._supervisor_identity(row))
        except (ValueError, OSError, KeyError):
            return None

    def _record_stopped(self, operation_id, token):
        with self._connect() as db:
            changed = db.execute("UPDATE operations SET stop_confirmed=1 WHERE operation_id=? AND process_token=?", (operation_id, token)).rowcount
        if changed:
            # Completion/ledger validation may still require reconciliation.
            # Once the owned process stopped, that separate failure cannot
            # reserve a running-job slot indefinitely.
            self.scheduler.release(str(self.root), operation_id, token, stopped=True)

    def _monitor(self, operation_id, process, token, paths):
        row = self._row(operation_id)
        seconds = self._operation_budget(row)
        while True:
            try:
                code = process.poll()
            except Exception:
                self._unknown(operation_id, token, "PROCESS_OBSERVATION_FAILED")
                return
            if code is not None:
                break
            guard = self._budget_guard(operation_id, token)
            if guard is not None:
                guard.check(owner=guard.owner, elapsed_seconds=seconds - self._remaining_seconds(row))
            if self._closed.is_set() or self._remaining_seconds(row) <= 0:
                self.cancel(operation_id)
                self._unknown(operation_id, token, "SERVICE_CLOSED" if self._closed.is_set() else "JOB_DEADLINE_EXCEEDED")
                return
            time.sleep(0.02)
        if not self._observed_stopped(self._row(operation_id)):
            self._unknown(operation_id, token, "DESCENDANT_STOP_UNCONFIRMED")
            return
        self._record_stopped(operation_id, token)
        with self._lock:
            if self._owned_process(operation_id, process, token):
                self._processes.pop(operation_id, None)
                self._process_tokens.pop(operation_id, None)
        row = self._row(operation_id)
        if row["process_token"] != token:
            return
        if row["cancel_requested"]:
            self._cancelled_stopped(operation_id, token)
            return
        try:
            if code != 0:
                raise ValueError("worker exit cannot prove execution outcome")
            result = self._validated_result(row, paths)
            self._finish(operation_id, result, token=token)
        except Exception:
            self._unknown(operation_id, token, "RESULT_EVIDENCE_UNVERIFIED")
            return

    def _finish(self, operation_id, result, *, token, expected_state="RUNNING"):
        row = self._row(operation_id)
        safe = _public_result(result, root=self.root, operation_id=operation_id, graph_id=self._operation_graph(operation_id),
                              root_task_id=self._task_id_for_row(row), attempt_token=row["process_token"],
                              attempt_generation=row["attempt_generation"])
        state = "RECONCILIATION_REQUIRED" if result.get("reconciliation_required") is True else (
            "SUCCEEDED" if result.get("construction_executed") is True else "FAILED")
        changed = self._set_state(operation_id, state, expected_state=expected_state, expected_token=token,
                                  result_json=_safe_json(safe), error_code=None, stop_confirmed=1)
        if changed and state in {"SUCCEEDED", "FAILED"}:
            self.scheduler.release(str(self.root), operation_id, token, stopped=True)
        return changed

    def _validated_result(self, row, paths):
        from .graph_job_worker import validate_completion
        graph = self._graph_record_for_operation(row["operation_id"])
        return validate_completion(root=self.root, repo_root=self.repo_root, paths=paths,
            operation=dict(row), graph_record=dict(graph), scheduler=self.scheduler)

    def _observed_stopped(self, row):
        if row["stop_confirmed"]:
            return True
        identity = _load_json(row["process_identity_json"], None)
        if not isinstance(identity, Mapping):
            try:
                slot = self.scheduler.owned(str(self.root), row["operation_id"], row["process_token"])
                identity = _load_json(slot.get("process_json"), None)
            except SchedulerBusy:
                identity = None
        if not isinstance(identity, Mapping) and int(row["attempt_generation"]) == 0:
            # v1 kept only a numeric PID, not birth/session/descendant evidence.
            # Its absence cannot prove the whole job stopped. Upgrade needs a
            # trusted local quiescence review; do not invent a process identity.
            return False
        with self._lock:
            process = self._processes.get(row["operation_id"])
            token = self._process_tokens.get(row["operation_id"])
        if process is not None and token == row["process_token"]:
            try:
                if process.poll() is None:
                    return False
            except Exception:
                return False
            if isinstance(identity, Mapping) and identity.get("pgid") == identity.get("pid") and identity.get("sid") == identity.get("pid"):
                return owned_group_status(identity) == "stopped"
            # Only injected process-contract fixtures lack OS session data.
            # Production POSIX jobs without it remain blocked.
            if self.worker_factory is not None:
                return True
            supervised = self._supervised_handle(row)
            return supervised is not None and supervised.poll() is not None
        supervised = self._supervised_handle(row)
        if supervised is None:
            return False
        try:
            return supervised.poll() is not None
        except (ValueError, OSError, KeyError):
            return False

    @staticmethod
    def _status_row(root, row, operation_id):
        """执行器和只读消费者共用同一状态投影，不重复解释成功条件。"""
        state = str(row["state"])
        response = {"operation_id": operation_id, "graph_id": str(row["graph_id"]), "state": state,
            "reconciliation_required": state == "RECONCILIATION_REQUIRED",
            "cancellation_requested": bool(row["cancel_requested"]), "stop_confirmed": bool(row["stop_confirmed"])}
        result = _load_json(row["result_json"], None)
        if isinstance(result, Mapping):
            response["result"] = _public_result(result, root=root, operation_id=operation_id, graph_id=str(row["graph_id"]),
                                                  root_task_id=GraphJobService._task_id_for_row(row), attempt_token=row["process_token"],
                                                  attempt_generation=row["attempt_generation"])
        if row["error_code"]:
            # Database contents are not permission to expose arbitrary text.
            code = str(row["error_code"])
            response["error_code"] = code if re.fullmatch(r"[A-Z_]{1,64}", code) else "RECONCILIATION_REQUIRED"
        return response

    def status(self, operation_id):
        operation_id = _request_id(operation_id, "operation_id")
        return self._status_row(self.root, self._row(operation_id), operation_id)

    @classmethod
    def observe_status(cls, root, operation_id):
        """仅读取已存在的任务库，不初始化executor、调度器或迁移活动任务。"""
        operation_id = _request_id(operation_id, "operation_id")
        root = Path(root).absolute()
        path = root / "graph_jobs.sqlite3"
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise GraphJobError("GRAPH_OBSERVER_DATABASE_REQUIRED")
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            raise GraphJobError("GRAPH_OBSERVER_OPERATION_NOT_FOUND")
        return cls._status_row(root, row, operation_id)

    def _cancelled_stopped(self, operation_id, token):
        if self._set_state(operation_id, "CANCELLED", expected_token=token,
                error_code="CANCELLED_STOP_CONFIRMED_OUTCOME_NOT_ROLLED_BACK", stop_confirmed=1):
            if int(self._row(operation_id)["attempt_generation"]) == 0:
                self.scheduler.release_legacy(str(self.root), operation_id, stopped=True)
            self.scheduler.release(str(self.root), operation_id, token, stopped=True)

    def cancel(self, operation_id):
        """Request cancellation; never signal a PID reconstructed from disk."""
        operation_id = _request_id(operation_id, "operation_id")
        row = self._row(operation_id)
        if row["state"] not in ACTIVE_STATES:
            return self.status(operation_id)
        token = row["process_token"]
        with self._connect() as db:
            db.execute("""UPDATE operations SET cancel_requested=1 WHERE operation_id=? AND process_token IS ?
                AND state IN ('PREPARED','STARTING','RUNNING','RECONCILIATION_REQUIRED')""", (operation_id, token))
        # Signal only the exact Popen handle owned by this controller. Do this
        # before a DB fence which may be waiting on an in-flight host call.
        with self._lock:
            process = self._processes.get(operation_id)
            owned_token = self._process_tokens.get(operation_id)
        if process is None:
            process = self._supervised_handle(row)
            if process is not None:
                with self._lock:
                    self._processes[operation_id] = process
                    self._process_tokens[operation_id] = token
                owned_token = token
        if process is not None and owned_token == token and self._owned_process(operation_id, process, token):
            try:
                if process.poll() is None:
                    process.terminate()
            except Exception:
                pass
        try:
            self.scheduler.request_cancel(str(self.root), operation_id, token)
            unstarted = self.scheduler.fence_unstarted(str(self.root), operation_id, token)
        except (SchedulerBusy, sqlite3.Error):
            unstarted = False
        if unstarted or self._observed_stopped(self._row(operation_id)):
            self._cancelled_stopped(operation_id, token)
        else:
            self._unknown(operation_id, token, "CANCELLATION_STOP_UNCONFIRMED")
        return self.status(operation_id)

    def reconcile(self, operation_id, *, resume_not_started=False):
        """Trusted controller-only recovery. NOT an MCP method or proof input.

        Only an unarmed, atomically fenced permit may be retried. A dispatched
        job requires both stopped-process evidence and a validated completion
        bundle. Missing/changed/partial evidence never causes a replay.
        """
        operation_id = _request_id(operation_id, "operation_id")
        if type(resume_not_started) is not bool:
            raise GraphJobError("resume_not_started must be an explicit boolean")
        with self._lock:
            row = self._row(operation_id)
            self._operation_budget(row)
            self._construction_inputs(_load_json(row["intent_json"]), verify_files=False)
            token = row["process_token"]
            if row["state"] not in ACTIVE_STATES:
                if row["stop_confirmed"]:
                    if int(row["attempt_generation"]) == 0:
                        self.scheduler.release_legacy(str(self.root), operation_id, stopped=True)
                    self.scheduler.release(str(self.root), operation_id, token, stopped=True)
                return self.status(operation_id)
            if int(row["attempt_generation"]) <= 0:
                self._unknown(operation_id, token, "LEGACY_EVIDENCE_UNSUPPORTED")
                return self.status(operation_id)
            slot = self.scheduler.snapshot()
            if (row["state"] == "RECONCILIATION_REQUIRED" and slot and slot["active"]
                    and slot["owner_root"] == str(self.root) and slot["operation_id"] == operation_id
                    and slot["token"] != token):
                repaired = self.scheduler.fence_rotated_unstarted(str(self.root), operation_id,
                                                                 int(row["attempt_generation"]))
                if repaired:
                    self._set_state(operation_id, "RECONCILIATION_REQUIRED",
                        expected_state="RECONCILIATION_REQUIRED", expected_token=token,
                        process_token=repaired["token"], attempt_generation=repaired["generation"],
                        pid=None, process_identity_json=None, stop_confirmed=0,
                        cancel_requested=int(bool(row["cancel_requested"] or repaired["cancel_requested"])),
                        error_code="RETRY_ROTATION_FENCED_CONTROLLER_RESUME_REQUIRED")
                    row = self._row(operation_id)
                    token = row["process_token"]
            if self.scheduler.fence_unstarted(str(self.root), operation_id, token):
                self._set_state(operation_id, "RECONCILIATION_REQUIRED", expected_token=token,
                                error_code="NOT_DISPATCHED_CONTROLLER_RESUME_REQUIRED")
                if resume_not_started:
                    if self._closed.is_set() or row["cancel_requested"]:
                        raise GraphJobError("closed or cancelled jobs cannot resume")
                    if self.job_budget_seconds > JOB_BUDGET_SECONDS and self._remaining_seconds(row) <= 0:
                        raise GraphJobError('original graph job budget expired; resume refused')
                    graph = self._graph_record_for_operation(operation_id)
                    compiled, catalog_hash = self._strict_compile(_load_json(graph["proposal_json"], {}))
                    intent = _load_json(row["intent_json"], {})
                    self._construction_inputs(intent)
                    if (compiled.to_dict() != _load_json(graph["compiled_json"], {})
                            or catalog_hash != intent.get("catalog_hash")
                            or runtime_fingerprint(self.repo_root) != intent.get("runtime_sha256")):
                        raise GraphJobError("graph, catalogue or runtime changed; resume refused")
                    reservation = self.scheduler.retry_unstarted(str(self.root), operation_id, token)
                    if not self._prepare_fenced_retry(row, reservation):
                        raise GraphJobError("resume state changed; installation reservation remains blocked")
                    self._schedule(operation_id, compiled.to_dict(), reservation["token"], reservation["generation"])
                return self.status(operation_id)
            self._unknown(operation_id, token, "RECONCILIATION_REQUESTED")
            if not self._observed_stopped(row):
                return self.status(operation_id)
            self._record_stopped(operation_id, token)
            if row["cancel_requested"]:
                self._cancelled_stopped(operation_id, token)
                return self.status(operation_id)
            try:
                result = self._validated_result(row, self._worker_paths(operation_id))
            except Exception:
                self._set_state(operation_id, "RECONCILIATION_REQUIRED", expected_state="RECONCILIATION_REQUIRED",
                                expected_token=token, error_code="RESULT_EVIDENCE_UNVERIFIED")
                return self.status(operation_id)
            self._finish(operation_id, result, token=token, expected_state="RECONCILIATION_REQUIRED")
            return self.status(operation_id)

    def reconcile_orphan(self):
        """Fence a reservation whose local intention transaction never committed."""
        with self._lock:
            slot = self.scheduler.snapshot()
            if not slot or not slot["active"] or slot["owner_root"] != str(self.root):
                return {"released": False}
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                exists = db.execute("SELECT 1 FROM operations WHERE operation_id=?", (slot["operation_id"],)).fetchone()
            if exists:
                return {"released": False, "operation_id": slot["operation_id"]}
            fenced = self.scheduler.fence_unstarted(str(self.root), slot["operation_id"], slot["token"])
            released = fenced and self.scheduler.release(str(self.root), slot["operation_id"], slot["token"], unstarted=True)
            return {"released": bool(released), "reconciliation_required": not released}

    def close(self, *, drain_in_process=False, drain_timeout_seconds=None):
        """Cancel promptly, then optionally drain direct software worker threads.

        The default monitor join remains one second. Software drain uses the
        remaining original job budget, with a one-second cleanup allowance
        only when that budget has already expired. A caller may shorten it.
        Pending threads require retaining their API modules and directories.
        """
        if type(drain_in_process) is not bool:
            raise GraphJobError("drain_in_process must be an explicit boolean")
        if drain_timeout_seconds is not None:
            if (not drain_in_process or type(drain_timeout_seconds) not in (int, float)
                    or not math.isfinite(drain_timeout_seconds) or drain_timeout_seconds < 0):
                raise GraphJobError("software drain timeout must be finite and nonnegative")
        self._closed.set()
        with self._lock:
            operation_ids = tuple(self._threads)
            threads = tuple(self._all_threads)
            deadline = None
            if drain_in_process:
                started = time.monotonic()
                remaining = max((self._remaining_seconds(self._row(operation_id))
                                 for operation_id, thread in self._threads.items() if thread.is_alive()),
                                default=0.0)
                timeout = remaining if remaining > 0 else 1.0
                if drain_timeout_seconds is not None:
                    timeout = min(timeout, drain_timeout_seconds)
                deadline = started + timeout
        for operation_id in operation_ids:
            try:
                self.cancel(operation_id)
            except (GraphJobError, sqlite3.Error):
                pass
        if deadline is None:
            deadline = time.monotonic() + 1.0
        for thread in threads:
            if thread is not threading.current_thread() and thread.ident is not None:
                thread.join(max(0.0, deadline-time.monotonic()))
        snapshot = self.shutdown_snapshot()
        return {key: snapshot[key] for key in ("pending_monitors", "unconfirmed_workers")}

    def shutdown_snapshot(self):
        """Observe current shutdown facts without signalling or extending budgets."""
        with self._lock:
            threads = tuple(self._all_threads)
            rows = [self._row(operation_id) for operation_id in self._threads]
        return {"closed": self._closed.is_set(),
                "pending_monitors": sum(thread.is_alive() for thread in threads),
                "unconfirmed_workers": [row["operation_id"] for row in rows
                                        if not row["stop_confirmed"] and row["state"] in ACTIVE_STATES]}

    shutdown = close


__all__ = ["GraphJobError", "GraphJobService", "JOB_BUDGET_SECONDS", "MAX_CONNECTIONS", "MAX_NODES", "MAX_OPERATIONS", "MAX_OUTPUTS", "REGISTERED_SOP_TYPES", "STATES"]
