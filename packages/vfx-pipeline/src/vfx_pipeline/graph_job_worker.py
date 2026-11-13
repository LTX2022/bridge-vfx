"""Fresh-process worker for a construction-only Houdini graph trial.

The controller passes a job description owned by the service as JSON.  This
worker accepts only service-owned files below the supplied job root, recompiles
the persisted proposal against the repository catalogue, and invokes the
trusted Houdini add-on's structured ``dispatch`` function.  固定官方增量范围使用同一租约内的原生分阶段构造与合并结构读回，
每阶段保留真实持久意图和完成记录；其余图继续使用结构化命令。
It never evaluates model supplied code and it never simulates, caches, or renders.

The module is also usable from a normal Python interpreter in unit tests when
``addon`` and ``clock`` are injected into :class:`GraphJobWorker`.
"""

from __future__ import annotations

import os
import time


_STARTUP_DIAGNOSTICS = (__name__ == "__main__"
                        and os.environ.get("BRIDGE_GRAPH_STARTUP_DIAGNOSTICS") == "1")


def _startup_checkpoint(stage):
    # The diagnostic controller opts in; the owned supervisor already owns fd 2.
    if _STARTUP_DIAGNOSTICS:
        try:
            wall_time_ns = time.time_ns()
            monotonic_ns = time.monotonic_ns()
            os.write(2, ("bridge.graph-worker.startup/1 stage=" + stage
                         + " monotonic_ns=" + str(monotonic_ns)
                         + " pid=" + str(os.getpid())
                         + " wall_time_ns=" + str(wall_time_ns) + "\n").encode("ascii"))
        except OSError:
            pass


_startup_checkpoint("python_entry")

import argparse
import hashlib
import importlib.util
import json
import math
import re
import secrets
import sqlite3
import sys
import traceback
from contextlib import contextmanager, nullcontext, closing
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

# A worker is invoked as an absolute script by ``hython``.  Its initial
# ``sys.path`` contains ``.../vfx_pipeline`` but not the sibling package
# sources, and the production launch intentionally clears PYTHONPATH.  Add
# only the four package roots implied by this trusted repository layout before
# importing runtime modules.
_WORKER_REPO_GUESS = Path(__file__).resolve().parents[4]
for _package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    _package_src = _WORKER_REPO_GUESS / "packages" / _package / "src"
    if _package_src.is_dir() and str(_package_src) not in sys.path:
        sys.path.insert(0, str(_package_src))

from dcc_task_runtime.canonical import canonical_json, canonical_sha256
from dcc_task_runtime.graph_compiler import CompiledGraph, GraphCompileError
from houdini_bridge.native_render_scene import SUPPORTED_PROFILES

from vfx_pipeline import graph_catalog
from vfx_pipeline.graph_trial import GraphExecutor
from vfx_pipeline.scene_lease import SceneLease, SceneLeaseGuard, SceneLeaseStore
from vfx_pipeline.graph_job_evidence import (PROTOCOL, atomic_json, owned_file,
    read_json, file_sha256, runtime_fingerprint, process_identity)
from vfx_pipeline.graph_scheduler import GraphScheduler

_startup_checkpoint("imports_complete")

MAX_NODES = 8
MAX_CONNECTIONS = 16
MAX_OUTPUTS = 8
REGISTERED_SOP_TYPES = graph_catalog.LEGACY_SOP_TYPES
_startup_checkpoint("catalog_validation_before")
REGISTERED_NATIVE_TYPES = graph_catalog.validate_catalog()
_startup_checkpoint("catalog_validation_after")
_ALLOWED_POST_COMMANDS = frozenset({"scene.save_hip", "scene.reopen_owned_hip", "node.children", "node.info", "node.parms"})
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _owned_path(root: Path, value: Any, *, must_exist: bool = False) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or not Path(value).is_absolute():
        raise ValueError("worker paths must be absolute and non-empty")
    return owned_file(root, Path(value), required=must_exist)


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    atomic_json(path, value, root=path.parent.resolve())


def _verify_native_dispatch_receipt(receipt, *, command, request, result, task_id,
                                    host_identity, launch_nonce, plugin_build):
    from houdini_bridge.operation_receipts import QUERY_SCHEMA, validate_operation_receipt

    validate_operation_receipt(receipt)
    if (receipt['schema'] == QUERY_SCHEMA
            and receipt['before_query']['hip_path'] != host_identity['hip_path']):
        raise ValueError("native producer query does not bind actual dispatch HIP")
    native_host = receipt['host_identity']
    actual_result = {key: value for key, value in result.items()
                     if key not in {'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent'}}
    if (receipt['task_id'] != task_id or receipt['command'] != command
            or receipt['operation_id'] != request['operation_id']
            or receipt['request_id'] != request['request_id']
            or receipt['request'] != request or receipt['result'] != actual_result
            or native_host['pid'] != os.getpid() or native_host['launch_nonce'] != launch_nonce
            or any(native_host[key] != host_identity[key]
                   for key in ('session_id', 'process_generation'))
            or native_host['plugin_build'] != plugin_build):
        raise ValueError("native producer does not bind actual dispatch/request/process/result")
    return json.loads(json.dumps(receipt, allow_nan=False))


class DurableJournal:
    """Small SQLite journal satisfying GraphExecutor's read/write protocol."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("journal path must not be a symlink")
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS entries(operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def read(self, operation_id: str) -> Optional[Mapping[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM entries WHERE operation_id=?", (str(operation_id),)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        return dict(value) if isinstance(value, Mapping) else None

    def claim(self, operation_id: str, value: Mapping[str, Any]) -> bool:
        if value.get("status") != "INTENT" or value.get("operation_id") != operation_id:
            raise ValueError("journal claim requires an exact operation intention")
        with self._connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO entries(operation_id,payload) VALUES(?,?)",
                                (operation_id, canonical_json(value)))
            return cursor.rowcount == 1

    def write(self, operation_id: str, value: Mapping[str, Any]) -> None:
        payload = canonical_json(value)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM entries WHERE operation_id=?", (operation_id,)).fetchone()
            prior = json.loads(row[0]) if row else None
            if prior == dict(value):
                return
            if (prior is None or prior.get("status") != "INTENT"
                    or prior.get("intent") != value.get("intent")
                    or value.get("status") not in {"UNKNOWN", "COMPLETE"}
                    or value.get("operation_id") != operation_id):
                raise ValueError("stale or inconsistent journal transition")
            db.execute("UPDATE entries SET payload=? WHERE operation_id=?", (payload, operation_id))


class _AddonClient:
    def __init__(self, addon: Any, dispatcher=None) -> None:
        self.addon = addon
        self.dispatcher = dispatcher or addon.dispatch

    def call(self, command: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if command not in {"node.children", "node.info", "node.create", "node.connect", "node.set_parms", "scene.create_task_root"}:
            raise ValueError("construction command outside worker allowlist")
        result = self.dispatcher(command, dict(params))
        if not isinstance(result, Mapping):
            raise ValueError("trusted add-on returned a non-object result")
        return dict(result)


class _PostClient:
    def __init__(self, addon: Any, dispatcher=None) -> None:
        self.addon = addon
        self.dispatcher = dispatcher or addon.dispatch

    def call(self, command: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if command not in _ALLOWED_POST_COMMANDS:
            raise ValueError("post-construction command outside worker allowlist")
        result = self.dispatcher(command, dict(params))
        if not isinstance(result, Mapping):
            raise ValueError("trusted add-on returned a non-object result")
        return dict(result)


def _load_addon(repo_root: Path) -> Any:
    source_candidate = repo_root / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
    if source_candidate.is_symlink() or not source_candidate.is_file():
        raise ValueError("trusted Houdini add-on is unavailable")
    source = source_candidate.resolve()
    module_name = "_bridge_graph_job_addon_" + hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(module_name, str(source))
    if spec is None or spec.loader is None:
        raise ValueError("trusted Houdini add-on cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "dispatch", None)):
        raise ValueError("trusted Houdini add-on has no dispatch function")
    return module


def _install_runtime_paths(repo_root: Path) -> None:
    for package in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
        path = repo_root / "packages" / package / "src"
        if path.is_dir():
            sys.path.insert(0, str(path))


def _native_type(node_type: str) -> str:
    try:
        return str(graph_catalog.NATIVE_TYPES[node_type])
    except KeyError as exc:
        raise ValueError("graph contains a node outside the trusted catalogue") from exc


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return abs(float(actual) - float(expected)) <= 1e-6
    return actual == expected


class GraphJobWorker:
    """Execute one immutable service-owned graph request."""

    def __init__(
        self,
        job: Mapping[str, Any],
        *,
        addon: Any = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(job, Mapping):
            raise ValueError("worker job must be an object")
        self.job = dict(job)
        self.clock = clock
        self.root = Path(str(self.job.get("root") or "")).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError("worker task root is unavailable")
        self.operation_id = str(self.job.get("operation_id") or "")
        self.graph_id = str(self.job.get("graph_id") or "")
        if not _ID_PATTERN.fullmatch(self.operation_id) or not _ID_PATTERN.fullmatch(self.graph_id):
            raise ValueError("worker operation identity is required")
        self.execution_task_id = str(self.job.get("task_id") or self.operation_id)
        self.native_operation_receipts = []
        self.native_operation_sequence = 0
        if not _ID_PATTERN.fullmatch(self.execution_task_id):
            raise ValueError("worker task identity is required")
        self.repo_root = Path(str(self.job.get("repo_root") or "")).expanduser().resolve()
        if not self.repo_root.is_dir():
            raise ValueError("trusted repository root is unavailable")
        self.graph_path = _owned_path(self.root, self.job.get("graph_path"), must_exist=True)
        self.proposal_path = _owned_path(self.root, self.job.get("proposal_path"), must_exist=True)
        self.result_path = _owned_path(self.root, self.job.get("result_path"))
        self.error_path = _owned_path(self.root, self.job.get("error_path") or str(self.result_path.parent / "error.txt"))
        self.journal_path = _owned_path(self.root, self.job.get("journal_path"))
        self.lease_path = _owned_path(self.root, self.job.get("lease_path"))
        self.addon = addon
        self.injected_addon = addon is not None
        self.managed = self.job.get("schema_version") == PROTOCOL
        if not self.managed and addon is None:
            raise ValueError("production worker requires controller-owned attempt evidence")
        deadline = self.job.get('deadline_at', self.clock() + 120.0)
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('worker deadline must be finite')
        self.deadline_at = float(deadline)
        self._budget_binding = None
        seconds = 120.0
        if self.managed:
            inputs = read_json(_owned_path(self.root, self.job.get('inputs_path'), must_exist=True), root=self.root)
            seconds = self._validate_budget(inputs)
        elif self.deadline_at > self.clock() + seconds:
            raise ValueError('worker deadline exceeds budget')
        self._deadline_monotonic = time.monotonic() + max(0.0, min(seconds, self.deadline_at - self.clock()))
        self.scheduler = None
        self.lease_store = None
        self.lease = None
        self.identity_record = None
        self.frozen_input_manifest = []

    def _validate_budget(self, inputs):
        """Bind launch timing to immutable controller inputs and the frozen scope."""
        keys = ('budget_started_at', 'job_budget_seconds', 'deadline_at', 'native_scope_budget')
        if not isinstance(inputs, Mapping):
            raise ValueError('worker persisted inputs must be an object')
        database_path = _owned_path(self.root, str(self.root / 'graph_jobs.sqlite3'), must_exist=True)
        with closing(sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True)) as database:
            database.row_factory = sqlite3.Row
            operation = database.execute('SELECT * FROM operations WHERE operation_id=?',
                                         (self.operation_id,)).fetchone()
        if operation is None:
            raise ValueError('worker persisted operation is missing')
        intent = json.loads(operation['intent_json'])
        if (operation['deadline_at'] != self.deadline_at
                or operation['graph_id'] != self.graph_id
                or operation['process_token'] != self.job.get('attempt_token')
                or operation['attempt_generation'] != self.job.get('attempt_generation')):
            raise ValueError('worker budget differs from original operation')
        if not any(key in inputs for key in keys):
            if (any(key in intent for key in keys)
                    or any(key in self.job for key in keys if key != 'deadline_at')
                    or not operation['created_at'] < self.deadline_at
                    or self.deadline_at > max(operation['created_at'], operation['updated_at']) + 120
                    or self.deadline_at > self.clock() + 120):
                raise ValueError('worker deadline exceeds legacy budget')
            return 120.0
        if (any(key not in inputs or key not in self.job for key in keys)
                or any(inputs[key] != self.job[key] for key in keys)):
            raise ValueError('worker budget differs from persisted intent')
        if any(inputs[key] != intent.get(key) for key in keys):
            raise ValueError('worker budget differs from original operation')
        scoped = inputs['native_scope_budget']
        seconds = 120.0
        if scoped is not None:
            if not isinstance(scoped, dict) or not isinstance(scoped.get('native_scope'), dict):
                raise ValueError('worker native scope budget invalid')
            from vfx_pipeline.production_hosts import native_scope_budget
            expected = native_scope_budget(scoped['native_scope'], scoped, self.root, self.job['scheduler_root'])
            if scoped != expected:
                raise ValueError('worker native scope budget drift')
            from dcc_task_runtime.native_scope import NativeScope
            scope = NativeScope(expected['native_scope'])
            seconds = scope.role_seconds('graph-worker')
            if seconds > 120:
                if (scope.scope.get('execution_authorized') is not True
                        or scope.scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
                    raise ValueError('worker native scope execution is not authorized')
        started, declared = inputs['budget_started_at'], inputs['job_budget_seconds']
        if (type(started) not in (int, float) or not math.isfinite(started)
                or not operation['created_at'] <= started <= max(operation['created_at'], operation['updated_at'])
                or seconds > 120 and started != operation['created_at']
                or type(declared) not in (int, float) or declared != seconds
                or self.deadline_at != started + seconds
                or self.deadline_at > self.clock() + seconds):
            raise ValueError('worker deadline exceeds bound budget')
        binding = canonical_json({key: inputs[key] for key in keys})
        if self._budget_binding is not None and self._budget_binding != binding:
            raise ValueError('worker budget changed before execution')
        self._budget_binding = binding
        return seconds

    def _construction_inputs(self, persisted):
        from vfx_pipeline.graph_construction_inputs import freeze_construction_inputs, particle_emission_configuration, render_scene_configuration

        manifest = persisted.get('frozen_input_manifest', [])
        if type(manifest) is not list:
            raise ValueError('worker construction inputs require an explicit manifest list')
        frozen = freeze_construction_inputs(manifest, verify_files=False)
        digest = persisted.get('frozen_inputs_sha256', canonical_sha256([]))
        if (canonical_sha256(frozen) != digest
                or self.job.get('frozen_input_manifest', []) != manifest
                or self.job.get('frozen_inputs_sha256', canonical_sha256([])) != digest):
            raise ValueError('worker construction inputs differ from persisted intent')
        frozen = freeze_construction_inputs(frozen)
        if any(item.get('semantic_role') == 'geometry_rest_basis' for item in frozen):
            if not self.domain_schedule or self.domain_schedule['identity']['domain_pack'] != 'procedural_geometry_v1':
                raise ValueError('geometry rest inputs require the registered geometry domain')
        if particle_emission_configuration(frozen) is not None:
            if not self.domain_schedule or self.domain_schedule['identity']['domain_pack'] != 'particles_v1':
                raise ValueError('particle emission inputs require the registered particles domain')
        identity = (self.domain_schedule or {}).get('identity', {})
        scene = render_scene_configuration(frozen, identity.get('houdini_version'))
        profile = identity.get('scene_profile')
        if profile is not None and profile not in SUPPORTED_PROFILES:
            raise ValueError('unsupported frozen render scene profile')
        if (scene is not None) != (profile in SUPPORTED_PROFILES):
            raise ValueError('frozen render scene and registered profile must be selected together')
        if scene is not None and scene['profile'] != profile:
            raise ValueError('frozen render scene configuration profile differs from registered profile')
        expected_domain = ('lighting_camera_render_v1' if profile == 'official_karma_disklight_v1' else 'material_lookdev_v1')
        if scene is not None and identity.get('domain_pack') != expected_domain:
            raise ValueError('frozen render scene requires its exact registered domain')
        self.frozen_input_manifest = frozen

    def _check_budget(self) -> None:
        if self.clock() >= self.deadline_at or time.monotonic() >= self._deadline_monotonic:
            raise TimeoutError("graph construction budget exceeded")

    def _record_error(self) -> None:
        """Keep a local operator traceback while public output stays fixed."""

        try:
            temporary = self.error_path.with_name(f".{self.error_path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
            temporary.write_text(traceback.format_exc(limit=20), encoding="utf-8")
            os.chmod(str(temporary), 0o600)
            os.replace(str(temporary), str(self.error_path))
        except OSError:
            pass

    def _compile_registered(self) -> CompiledGraph:
        proposal_payload = _json_file(self.proposal_path)
        persisted = _json_file(self.graph_path)
        compiled = graph_catalog.compile_proposal(proposal_payload)
        if graph_catalog.validate_catalog() != REGISTERED_NATIVE_TYPES:
            raise ValueError("trusted native catalogue differs from registration")
        if graph_catalog.execution_diagnostics(compiled):
            raise ValueError("native binding is blocked before construction")
        self.domain_schedule = graph_catalog.bounded_domain_schedule(compiled)
        if self.domain_schedule is None:
            if len(compiled.nodes) > MAX_NODES or len(compiled.connections) > MAX_CONNECTIONS:
                raise ValueError("graph exceeds the construction node limit")
        elif any(len(stage['nodes']) > MAX_NODES or len(stage['connections']) > MAX_CONNECTIONS for stage in self.domain_schedule['stages']):
            raise ValueError("registered domain exceeds a bounded construction stage")
        if not compiled.outputs or len(compiled.outputs) > MAX_OUTPUTS:
            raise ValueError("graph exceeds the construction output limit")
        if not isinstance(persisted, Mapping) or persisted != compiled.to_dict():
            raise ValueError("persisted graph differs from a fresh trusted compilation")
        catalog_hash = str(graph_catalog.descriptor().get("catalog_hash") or "")
        expected_graph_id = "graph_" + canonical_sha256({"compiled": compiled.to_dict(), "catalog_hash": catalog_hash})
        if self.graph_id != expected_graph_id:
            raise ValueError("graph identity does not match the trusted catalogue")
        return compiled

    def _host_identity(self):
        reader = getattr(self.addon, "graph_worker_identity", None)
        if not callable(reader):
            raise ValueError("host has no private graph identity provider")
        identity = reader()
        if not isinstance(identity, Mapping) or any(not isinstance(identity.get(key), str) or not identity[key]
                for key in ("session_id", "process_generation", "scene_id", "hip_path")):
            raise ValueError("private host identity is incomplete")
        return dict(identity)

    def _prepare_project_path(self) -> Path:
        # Establish $HIP/$HIPNAME before scene identity or parameter capture.
        # The scheduler transaction keeps ownership fenced across the native call.
        scheduling = self.scheduler.operation(str(self.root), self.operation_id,
            self.job["attempt_token"]) if self.scheduler else nullcontext()
        with scheduling:
            self._check_budget()
            hip_path = self.result_path.parent / (self.operation_id + ".hip")
            if (not _ID_PATTERN.fullmatch(self.operation_id) or not hip_path.is_absolute()
                    or hip_path.name != self.operation_id + ".hip"):
                raise ValueError("owned HIP name is invalid")
            hip_path = owned_file(self.root, hip_path, required=False)
            if not hip_path.parent.is_dir() or hip_path.exists() or hip_path.is_symlink():
                raise ValueError("owned HIP path is not fresh")
            import hou
            hou.hipFile.setName(str(hip_path))
            if hou.hipFile.path() != str(hip_path):
                raise ValueError("native HIP name differs from owned target")
            owned_file(self.root, hip_path, required=False)
            if hip_path.exists() or hip_path.is_symlink() or not hip_path.parent.is_dir():
                raise ValueError("native HIP naming created or changed the target")
            self._check_budget()
        return hip_path

    def _lease(self, compiled: CompiledGraph) -> tuple[SceneLeaseStore, SceneLease]:
        root_digest = hashlib.sha256((self.execution_task_id + ":" + compiled.graph_hash).encode()).hexdigest()
        identity = self._host_identity()
        store = SceneLeaseStore(self.lease_path, clock=self.clock)
        lease = store.acquire(task_id=self.execution_task_id, root=f"/obj/BRIDGE_GRAPH_{root_digest}",
            **{key: identity[key] for key in ("session_id", "process_generation", "scene_id")},
            ttl=max(1.0, self.deadline_at-self.clock()))
        return store, lease

    def _initialize_evidence(self, compiled):
        if not self.managed:
            self._construction_inputs(self.job)
            return
        inputs_path = _owned_path(self.root, self.job.get("inputs_path"), must_exist=True)
        inputs = read_json(inputs_path, root=self.root)
        self._validate_budget(inputs)
        for key in ("operation_id", "graph_id", "task_id", "attempt_token", "attempt_generation", "scheduler_root", "validation_scope"):
            if inputs.get(key) != self.job.get(key):
                raise ValueError("worker launch identity differs from persisted inputs")
        _startup_checkpoint("runtime_fingerprint_before")
        runtime_sha256 = runtime_fingerprint(self.repo_root)
        _startup_checkpoint("runtime_fingerprint_after")
        if (inputs.get("runtime_sha256") != runtime_sha256
                or inputs.get("catalog_hash") != graph_catalog.descriptor()["catalog_hash"]
                or inputs.get("graph_hash") != compiled.graph_hash
                or inputs.get("proposal_sha256") != file_sha256(self.proposal_path)
                or inputs.get("compiled_sha256") != file_sha256(self.graph_path)):
            raise ValueError("worker input hashes changed before execution")
        _startup_checkpoint("construction_inputs_before")
        self._construction_inputs(inputs)
        _startup_checkpoint("construction_inputs_after")
        self.scheduler = GraphScheduler(Path(self.job["scheduler_root"]))
        _startup_checkpoint("process_identity_before")
        identity = process_identity(os.getpid())
        _startup_checkpoint("process_identity_after")
        identity.pop("state", None)
        _startup_checkpoint("scheduler_bind_process_before")
        self.scheduler.bind_process(str(self.root), self.operation_id, self.job["attempt_token"], identity)
        _startup_checkpoint("scheduler_bind_process_after")
        self.identity_record = {
            "schema_version": PROTOCOL, "operation_id": self.operation_id, "graph_id": self.graph_id,
            "attempt_token": self.job["attempt_token"], "attempt_generation": self.job["attempt_generation"],
            "process_identity": identity, "inputs_sha256": file_sha256(inputs_path),
            "validation_scope": "software_fake_host" if self.injected_addon else self.job["validation_scope"],
        }
        atomic_json(_owned_path(self.root, self.job.get("identity_path")), self.identity_record, root=self.root)

    def _fenced_dispatch(self, command, params):
        lease, store = self.lease, self.lease_store
        if lease is None or store is None:
            raise ValueError("host call has no persisted scene owner")
        guard = SceneLeaseGuard(lease, lambda: store.current(lease.session_id, lease.scene_id),
                                self._host_identity, clock=self.clock)
        scheduling = self.scheduler.operation(str(self.root), self.operation_id, self.job["attempt_token"]) if self.scheduler else nullcontext()
        with scheduling, store.operation(lease):
            self._check_budget()
            if command in {"node.children", "node.create", "node.set_parms", "node.connect", "scene.create_task_root"}:
                guard(self.execution_task_id, lease.root, command, params)
            else:
                # Reuse the identity/expiry check, then apply the narrower
                # post-construction operation-specific path checks.
                guard(self.execution_task_id, lease.root, "node.children", {"path": lease.root})
                if command in {"scene.save_hip", "scene.reopen_owned_hip"}:
                    expected = self.result_path.parent / (self.operation_id + ".hip")
                    if params.get("path") != str(expected):
                        raise ValueError("post operation does not target the owned artifact")
                elif command in {"node.info", "node.parms"}:
                    path = params.get("path")
                    allowed_paths = {row["path"] for row in self._native_layout.values()}
                    if path not in allowed_paths:
                        raise ValueError("post query exceeds the compiled owned graph")
                else:
                    raise ValueError("post operation is not allowlisted")
            request = dict(params)
            producer_validator = None
            if self.managed:
                from houdini_bridge.operation_receipts import (
                    COMMAND_KINDS, CHILDREN_INSPECT_POLICY, validate_operation_receipt, validate_query_receipt,
                )
                target = params.get('path', params.get('parent', ''))
                parent_probe = (command == 'node.children' and isinstance(target, str)
                                and target != lease.root and not target.startswith(lease.root + '/'))
                if command in COMMAND_KINDS and not parent_probe:
                    self.native_operation_sequence += 1
                    native_id = "native-" + hashlib.sha256(json.dumps(
                        {"operation_id": self.operation_id, "attempt_token": self.job["attempt_token"],
                         "sequence": self.native_operation_sequence, "command": command, "params": request},
                        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
                    request.update(task_id=self.execution_task_id, operation_id=native_id,
                                   request_id=native_id, root_path=lease.root,
                                   frozen_input_manifest=request.get("frozen_input_manifest", []))
                    producer_validator = validate_operation_receipt
                    if command == "node.children":
                        request["inspect_policy"] = CHILDREN_INSPECT_POLICY
                        producer_validator = validate_query_receipt
            dispatch_identity = self._host_identity()
            result = self.addon.dispatch(command, request)
            if producer_validator is not None:
                receipt = result.get("operation_receipt") if isinstance(result, Mapping) else None
                producer_validator(receipt)
                verified = _verify_native_dispatch_receipt(receipt, command=command, request=request,
                    result=result, task_id=self.execution_task_id, host_identity=dispatch_identity,
                    launch_nonce=self.job['attempt_token'], plugin_build=hashlib.sha256(
                        (self.repo_root / 'plugins/houdini/_impl/houdini_bridge_addon.py').read_bytes()).hexdigest())
                from houdini_bridge.operation_receipt_store import record_path
                runner = self.addon.fx_operation_runner(self.execution_task_id)
                store_format = result.get('operation_store_format')
                if store_format == 'producer_record':
                    expected_path = record_path(runner.path, self.execution_task_id, native_id)
                elif store_format == 'legacy_task_store':
                    expected_path = runner.path
                else:
                    raise ValueError('native producer storage format is missing')
                actual_path = Path(result.get('operation_store_path') or '')
                if actual_path != expected_path:
                    raise ValueError('native producer storage does not belong to the actual task')
                payload = owned_file(runner.path.parent, actual_path).read_bytes()
                stored = json.loads(payload)
                if store_format == 'legacy_task_store':
                    stored = (stored.get('producer_operations') or {}).get(native_id)
                if stored != verified:
                    raise ValueError('native producer persisted record differs from dispatch')
                self.native_operation_receipts.append({
                    'schema': verified['schema'], 'task_id': self.execution_task_id,
                    'operation_id': native_id, 'request_id': native_id, 'command': command,
                    'kind': verified['kind'], 'state': verified['state'],
                    'operation_receipt_sha256': verified['operation_receipt_sha256'],
                    'request_sha256': verified['request_sha256'],
                    'handler_result_sha256': verified['facts']['handler_result_sha256'],
                    'host_identity': verified['host_identity'],
                    'storage_format': store_format, 'path': str(actual_path),
                    'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
            if not isinstance(result, Mapping):
                raise ValueError("host returned no structured result")
            after = self._host_identity()
            if command in {"scene.save_hip", "scene.reopen_owned_hip"}:
                if after["hip_path"] != params["path"] or result.get("path") != params["path"]:
                    raise ValueError("owned scene transition returned a different identity")
            elif any(after[key] != getattr(lease, key) for key in ("session_id", "process_generation", "scene_id")):
                raise ValueError("host scene changed during construction")
        if command in {"scene.save_hip", "scene.reopen_owned_hip"}:
            self.lease = store.rebind_owned_scene(lease, after)
        return dict(result)

    @contextmanager
    def _official_batch_fence(self):
        """批量仍持有调度、控制端场景租约和原生根租约；阶段前后重新核对身份与预算。"""
        lease, store = self.lease, self.lease_store
        if lease is None or store is None:
            raise ValueError('OFFICIAL_BATCH_SCENE_LEASE_REQUIRED')
        guard = SceneLeaseGuard(lease, lambda: store.current(lease.session_id, lease.scene_id),
                                self._host_identity, clock=self.clock)
        scheduling = self.scheduler.operation(str(self.root), self.operation_id,
            self.job['attempt_token']) if self.scheduler else nullcontext()
        with scheduling, store.operation(lease), self.addon._root_lease_fence(
                lease.root, task_id=self.execution_task_id, scope='sop'):
            from dcc_task_runtime.native_scope import NativeScope
            native = NativeScope(self.job['native_scope_budget']['native_scope'])
            native.check()
            self._check_budget()
            guard(self.execution_task_id, lease.root, 'node.children', {'path': lease.root})
            yield
            guard(self.execution_task_id, lease.root, 'node.children', {'path': lease.root})
            self.addon._root_lease_check(lease.root, task_id=self.execution_task_id, scope='sop', renew=False)
            native.check()
            self._check_budget()

    def _native_receipt_evidence(self, compiled):
        if not self.native_operation_receipts:
            return None
        runner = self.addon.fx_operation_runner(self.execution_task_id)
        for receipt in self.native_operation_receipts:
            payload = owned_file(runner.path.parent, Path(receipt['path'])).read_bytes()
            if len(payload) != receipt['bytes'] or hashlib.sha256(payload).hexdigest() != receipt['sha256']:
                raise ValueError('native producer evidence bytes changed before publication')
        path = _owned_path(self.root, str(self.result_path.parent / (self.operation_id + '.native-operations.json')))
        packet = {'schema': 'bridge.houdini.native-command-evidence/2.0',
                  'task_id': self.execution_task_id, 'operation_id': self.operation_id,
                  'attempt_token': self.job['attempt_token'],
                  'attempt_generation': self.job['attempt_generation'], 'graph_hash': compiled.graph_hash,
                  'receipts': self.native_operation_receipts}
        atomic_json(path, packet, root=self.root)
        payload = path.read_bytes()
        return {'schema': packet['schema'], 'path': str(path), 'bytes': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest(),
                'task_id': self.execution_task_id, 'operation_id': self.operation_id,
                'attempt_token': packet['attempt_token'], 'attempt_generation': packet['attempt_generation'],
                'graph_hash': compiled.graph_hash, 'count': len(self.native_operation_receipts)}

    def _verify(self, compiled: CompiledGraph, result: Mapping[str, Any], post: _PostClient, hip_path: Path, hip_sha256: str) -> dict[str, Any]:
        # 官方增量合并重复全场景采集，仍完整读回拓扑、引用和原封存参数。
        from vfx_pipeline.official_graph_batch import selected_plan, verify_reopened
        if selected_plan(self.job, compiled, self.lease.root) is not None:
            return verify_reopened(self, compiled, hip_path, hip_sha256)
        topology = result.get("topology")
        if not isinstance(topology, Mapping) or not isinstance(topology.get("root"), str):
            raise ValueError("construction returned no owned topology")
        graph_root = str(topology["root"])
        layout = graph_catalog.native_layout(compiled, graph_root)
        by_path = {}
        for parent in sorted({graph_root} | {row["parent"] for row in layout.values()}):
            children = post.call("node.children", {"path": parent}).get("nodes")
            if not isinstance(children, list):
                raise ValueError("reloaded graph topology is unavailable")
            by_path.update({str(item.get("path")): item for item in children if isinstance(item, Mapping)})
        port_interfaces = {}
        expected_nodes: dict[str, Any] = {}
        expected_inputs: dict[str, dict[int, str]] = {}
        expected_output_indices: dict[str, dict[int, int]] = {}
        expected_references: dict[str, dict[str, str]] = {}
        for connection in compiled.connections:
            target_path = layout[connection.target_node]["path"]
            source_path = layout[connection.source_node]["path"]
            binding = graph_catalog.connection_binding(compiled, connection)
            if binding.get('input_name') or binding.get('output_name'):
                source_info=post.call('node.info',{'path':source_path,'native_port_names':True})
                target_info=post.call('node.info',{'path':target_path,'native_port_names':True})
                port_interfaces[source_path]={key:source_info[key] for key in ('input_names','output_names')}
                port_interfaces[target_path]={key:target_info[key] for key in ('input_names','output_names')}
                binding = graph_catalog.resolve_connection_binding(binding,source_info,target_info)
            if binding["kind"] == "reference":
                if not binding["field"].startswith("@"):
                    expected_references.setdefault(target_path, {})[binding["field"]] = source_path
                continue
            expected_inputs.setdefault(target_path, {})[binding["input_index"]] = source_path
            expected_output_indices.setdefault(target_path, {})[binding["input_index"]] = binding["output_index"]
        for node in compiled.nodes:
            path = layout[node.address]["path"]
            item = by_path.get(path)
            if item is None or str(item.get("type")) != _native_type(node.node_type):
                raise ValueError("reloaded graph node topology differs from the compiled graph")
            expected_nodes[node.address] = path
            expected_parms = {**dict(node.parameters), **expected_references.get(path, {})}
            if expected_parms:
                parms = post.call("node.parms", {"path": path, "names": sorted(expected_parms)}).get("parms")
                if not isinstance(parms, Mapping) or any(not _same_value(parms.get(key), value) for key, value in expected_parms.items()):
                    raise ValueError("reloaded graph parameters differ from the compiled graph")
            info = post.call("node.info", {"path": path})
            expected_category = layout[node.address]["category"]
            if expected_category == "Obj":
                expected_category = "Object"
            if info.get("type") not in (None, _native_type(node.node_type),
                                        expected_category + "/" + _native_type(node.node_type)):
                raise ValueError("reloaded native node category differs from the compiled graph")
            if info.get("errors"):
                raise ValueError("reloaded graph contains node errors")
            actual_inputs = info.get("inputs", [])
            if not isinstance(actual_inputs, list):
                raise ValueError("reloaded graph input topology is unavailable")
            expected_for_node = expected_inputs.get(path, {})
            for index, source in enumerate(actual_inputs):
                expected_source = expected_for_node.get(index)
                if expected_source is None:
                    if source is not None:
                        raise ValueError("reloaded graph contains an unexpected input connection")
                elif source != expected_source:
                    raise ValueError("reloaded graph input topology differs from the compiled graph")
            if any(index >= len(actual_inputs) for index in expected_for_node):
                raise ValueError("reloaded graph is missing an expected input connection")
            # Path-only inputs cannot prove a multi-output constraint/proxy lane.
            # R must provide actual HOM inputConnections facts; never infer them.
            output_indices = expected_output_indices.get(path, {})
            facts = info.get("input_connections")
            if any(output_indices.values()) or facts is not None:
                if not isinstance(facts, list) or any(not isinstance(fact, Mapping) for fact in facts):
                    raise ValueError("R native source output-index readback interface is unavailable")
                actual = {(fact.get("input_index"), fact.get("source"), fact.get("output_index")) for fact in facts}
                expected = {(index, source, output_indices[index]) for index, source in expected_for_node.items()}
                if actual != expected or len(facts) != len(expected):
                    raise ValueError("reloaded native source output indices differ from the compiled graph")
        expected_paths = set(expected_nodes.values())
        if set(by_path) != expected_paths:
            raise ValueError("reloaded graph contains unexpected task nodes")
        return {
            "hip_path": str(hip_path),
            "hip_sha256": hip_sha256,
            **({'native_port_interfaces':port_interfaces} if port_interfaces else {}),
            "root": graph_root,
            "nodes_verified": True,
            "parameters_verified": True,
            "connections_verified": True,
        }

    def run(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "schema_version": "bridge.graph_job/1.0",
            "operation_id": self.operation_id,
            "graph_id": self.graph_id,
            "construction_executed": False,
            "visual_verified": False,
            "reconciliation_required": False,
            "validation_scope": "software_fake_host" if self.injected_addon else self.job["validation_scope"],
        }
        lease_store: Optional[SceneLeaseStore] = None
        lease: Optional[SceneLease] = None
        try:
            self._check_budget()
            _startup_checkpoint("run_compile_before")
            compiled = self._compile_registered()
            _startup_checkpoint("run_compile_after")
            _startup_checkpoint("initialize_evidence_before")
            self._initialize_evidence(compiled)
            _startup_checkpoint("initialize_evidence_after")
            if self.addon is None:
                _install_runtime_paths(self.repo_root)
                self.addon = _load_addon(self.repo_root)
            hip_path = self._prepare_project_path()
            lease_store, lease = self._lease(compiled)
            self.lease_store, self.lease = lease_store, lease
            guard = SceneLeaseGuard(lease, lambda: lease_store.current(lease.session_id, lease.scene_id),
                                    self._host_identity, clock=self.clock)
            self._native_layout = graph_catalog.native_layout(compiled, lease.root)
            journal = DurableJournal(self.journal_path)
            from vfx_pipeline.official_graph_batch import selected_plan, execute as execute_official_batch
            if selected_plan(self.job, compiled, lease.root) is not None:
                result = execute_official_batch(self, compiled, journal)
                base["construction_protocol"] = result["construction_protocol"]
            else:
                executor = GraphExecutor(_AddonClient(self.addon, self._fenced_dispatch), journal, lease_guard=guard)
                result = executor.execute(self.execution_task_id, compiled)
            if not isinstance(result, Mapping):
                raise ValueError("graph executor returned no result")
            # Only the graph hash and topology fields are candidates for the
            # public result.  Diagnostics from GraphExecutor may contain host
            # exception text, so they are replaced below with fixed messages.
            if result.get("graph_hash"):
                base["graph_hash"] = str(result["graph_hash"])
            if result.get("construction_executed") is not True:
                base.update({
                    "reconciliation_required": True,
                    "construction_executed": False,
                    "topology": None,
                    "diagnostics": [{"code": "GRAPH_EXECUTION_UNPROVEN", "message": "worker could not prove a completed construction"}],
                })
                return base
            # GraphExecutor has already issued and journaled the construction
            # commands at this point.  If saving, reopening, or host
            # reconciliation fails below, retain that fact while requiring
            # reconciliation; reporting it as unexecuted would invite a
            # caller to replay a graph whose nodes may already exist.
            base["construction_executed"] = True
            base["topology"] = result.get("topology")
            self._check_budget()
            if self.domain_schedule:
                op_id = compiled.graph_hash + ':domain:initialize'
                intent = dict(GraphExecutor._operations(compiled,self.lease.root))[op_id]
                if not journal.claim(op_id,{'operation_id':op_id,'status':'INTENT','intent':intent}):
                    raise ValueError('domain initialization requires reconciliation')
                initializer = getattr(self.addon,'graph_initialize_registered_domain',None)
                if not callable(initializer):raise ValueError('private registered domain initializer is unavailable')
                with self.scheduler.operation(str(self.root),self.operation_id,self.job['attempt_token']) if self.scheduler else nullcontext():
                    with self.lease_store.operation(self.lease):
                        self._check_budget()
                        initialized = initializer(self.execution_task_id,self.domain_schedule['identity'],result['topology'],
                            compiled.graph_hash,self.result_path.parent/'render-output',
                            **({'frozen_input_manifest': self.frozen_input_manifest} if self.frozen_input_manifest else {}))
                        if initialized.get('schedule_sha256') != self.domain_schedule['schedule_sha256']:
                            raise ValueError('registered domain initialization did not bind its schedule')
                        if (self.frozen_input_manifest and initialized.get('frozen_inputs_sha256') !=
                                canonical_sha256(self.frozen_input_manifest)):
                            raise ValueError('registered domain initialization did not bind its frozen inputs')
                        self._check_budget()
                journal.write(op_id,{'operation_id':op_id,'status':'COMPLETE','intent':intent,'result':initialized})
            owned_file(self.root, hip_path, required=False)
            if hip_path.exists() or hip_path.is_symlink():
                raise ValueError("owned HIP path is not fresh")
            post = _PostClient(self.addon, self._fenced_dispatch)
            saved = post.call("scene.save_hip", {"path": str(hip_path), **({"task_id":self.execution_task_id,"root_path":self.lease.root} if self.domain_schedule else {})})
            if str(saved.get("path") or "") != str(hip_path) or not hip_path.is_file():
                raise ValueError("trusted add-on did not save the owned HIP")
            hip_sha256 = hashlib.sha256(hip_path.read_bytes()).hexdigest()
            reopened = post.call("scene.reopen_owned_hip", {
                "path": str(hip_path),
                "sha256": hip_sha256,
                "task_id": self.execution_task_id,
                "root_path": self.lease.root,
            })
            if (
                str(reopened.get("path") or "") != str(hip_path)
                or reopened.get("sha256") != hip_sha256
                or reopened.get("owned_headless_reopen") is not True
            ):
                raise ValueError("owned HIP did not reopen cleanly")
            verification = self._verify(compiled, result, post, hip_path, hip_sha256)
            if (self.domain_schedule
                    and ((self.domain_schedule['identity']['domain_pack'] == 'particles_v1'
                    and any(item.get('semantic_role') == 'particle_emission_basis'
                            for item in self.frozen_input_manifest)) or
                         self.domain_schedule['identity'].get('scene_profile') in SUPPORTED_PROFILES)):
                contract_digest = saved.get('scene_contract_sha256')
                if (type(contract_digest) is not str or len(contract_digest) != 64
                        or any(char not in '0123456789abcdef' for char in contract_digest)):
                    raise ValueError('registered domain has no exact saved scene contract')
                verification['registered_scene_contract_sha256'] = contract_digest
            if self.domain_schedule and self.domain_schedule['identity'].get('scene_profile') in SUPPORTED_PROFILES:
                from vfx_pipeline.graph_construction_inputs import render_scene_configuration
                scene_readback = ((reopened.get('root_lease_rebind') or {}).get('verification') or {}).get('frozen_scene_parameters')
                configuration = render_scene_configuration(self.frozen_input_manifest, self.domain_schedule['identity']['houdini_version'])
                if (not isinstance(scene_readback, dict) or scene_readback.get('configuration_sha256') != canonical_sha256(configuration)):
                    raise ValueError('reopened render scene has no exact frozen parameter readback')
                verification['frozen_scene_parameters'] = scene_readback
            base.update({"construction_executed": True, "reconciliation_required": False, "visual_verified": False, "artifact": verification, "verification": verification})
            native_evidence = self._native_receipt_evidence(compiled)
            if native_evidence is not None:
                base['native_operation_evidence'] = native_evidence
            if lease_store is not None and lease is not None:
                lease_store.revoke(self.lease, host_operations_reconciled=True)
            return base
        except GraphCompileError:
            self._record_error()
            base.update({"reconciliation_required": True, "diagnostics": [{"code": "GRAPH_RECOMPILE_REJECTED", "message": "registered graph failed trusted recompilation"}]})
        except TimeoutError:
            self._record_error()
            base.update({"reconciliation_required": True, "diagnostics": [{"code": "JOB_DEADLINE_EXCEEDED", "message": "construction budget exceeded"}]})
        except Exception:
            # Never write process paths, argv, tracebacks, or exception text to
            # the model-facing result. Unknown host state is reconciliation.
            self._record_error()
            base.update({"reconciliation_required": True, "diagnostics": [{"code": "WORKER_RECONCILIATION_REQUIRED", "message": "worker could not prove a safe completed construction"}]})
        return base


def _journal_evidence(root: Path, path: Path):
    path = owned_file(root, path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        rows = db.execute("SELECT operation_id,payload FROM entries ORDER BY operation_id").fetchall()
    entries = {key: json.loads(value) for key, value in rows}
    if not entries or any(not isinstance(v, Mapping) or v.get("status") != "COMPLETE"
                          or v.get("operation_id") != k or not isinstance(v.get("result"), Mapping)
                          for k, v in entries.items()):
        raise ValueError("journal contains unknown or incomplete host operations")
    return entries, canonical_sha256(entries)


def _lease_evidence(root: Path, path: Path):
    path = owned_file(root, path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        rows = db.execute("SELECT session_id,scene_id,generation,active,payload FROM scene_leases ORDER BY session_id,scene_id").fetchall()
    if not rows or any(row[3] != 0 for row in rows):
        raise ValueError("scene ownership was not reconciled and revoked")
    return canonical_sha256([list(row) for row in rows])


def _seal_completion(worker, result):
    identity_path = _owned_path(worker.root, worker.job["identity_path"], must_exist=True)
    inputs_path = _owned_path(worker.root, worker.job["inputs_path"], must_exist=True)
    artifact = owned_file(worker.root, worker.result_path.parent / (worker.operation_id + ".hip"))
    _, journal_sha256 = _journal_evidence(worker.root, worker.journal_path)
    seal = {
        "schema_version": PROTOCOL, "operation_id": worker.operation_id, "graph_id": worker.graph_id,
        "attempt_token": worker.job["attempt_token"], "attempt_generation": worker.job["attempt_generation"],
        "inputs_sha256": file_sha256(inputs_path), "identity_sha256": file_sha256(identity_path),
        "result_sha256": file_sha256(worker.result_path), "artifact_sha256": file_sha256(artifact),
        "journal_sha256": journal_sha256, "leases_sha256": _lease_evidence(worker.root, worker.lease_path),
        "validation_scope": result["validation_scope"],
    }
    atomic_json(_owned_path(worker.root, worker.job["completion_path"]), seal, root=worker.root)


def validate_completion(*, root: Path, repo_root: Path, paths, operation, graph_record, scheduler, source_catalogue=None):
    """Read-only controller verification of a stopped attempt's durable bundle.

    This proves consistency/provenance for cooperating controller/worker code,
    not tamper resistance against arbitrary tools in the same user's account.
    It does not reopen a DCC or turn a software adapter into host certification.
    """
    # 历史只读复核使用原封存目录；正常执行仍使用当前目录定义。
    catalogue = graph_catalog if source_catalogue is None else source_catalogue
    if int(operation["attempt_generation"]) <= 0:
        raise ValueError("legacy result has no attempt-bound evidence")
    inputs = read_json(paths["inputs"], root=root)
    identity = read_json(paths["identity"], root=root)
    seal = read_json(paths["completion"], root=root)
    result = read_json(paths["result"], root=root)
    if any(not isinstance(item, Mapping) for item in (inputs, identity, seal, result)):
        raise ValueError("completion bundle is malformed")
    intent = json.loads(operation["intent_json"])
    for item in (inputs, identity, seal):
        if (item.get("schema_version") != PROTOCOL or item.get("operation_id") != operation["operation_id"]
                or item.get("graph_id") != operation["graph_id"]
                or item.get("attempt_token") != operation["process_token"]
                or item.get("attempt_generation") != operation["attempt_generation"]):
            raise ValueError("completion belongs to another operation or attempt")
    if any(inputs.get(key) != value for key, value in intent.items()):
        raise ValueError("persisted controller inputs changed")
    if inputs.get("scheduler_root") != str(scheduler.root):
        raise ValueError("completion belongs to a different installation")
    slot = scheduler.launched_fact(str(root), operation["operation_id"], operation["process_token"])
    if (slot["phase"] != "DISPATCHING" or slot["cancel_requested"]
            or not slot.get("process_json") or json.loads(slot["process_json"]) != identity.get("process_identity")):
        raise ValueError("completion has no matching launched-process provenance")
    proposal = read_json(paths["proposal"], root=root)
    graph = read_json(paths["graph"], root=root)
    compiled = catalogue.compile_proposal(proposal)
    if (proposal != json.loads(graph_record["proposal_json"]) or graph != json.loads(graph_record["compiled_json"])
            or graph != compiled.to_dict() or inputs.get("catalog_hash") != catalogue.descriptor()["catalog_hash"]
            or inputs.get("runtime_sha256") != runtime_fingerprint(repo_root)
            or inputs.get("proposal_hash") != canonical_sha256(proposal)
            or inputs.get("proposal_sha256") != file_sha256(paths["proposal"])
            or inputs.get("compiled_sha256") != file_sha256(paths["graph"])):
        raise ValueError("graph, catalogue or runtime inputs changed")
    if (seal.get("inputs_sha256") != file_sha256(paths["inputs"])
            or identity.get("inputs_sha256") != seal["inputs_sha256"]
            or seal.get("identity_sha256") != file_sha256(paths["identity"])
            or seal.get("result_sha256") != file_sha256(paths["result"])):
        raise ValueError("durable evidence hashes do not match")
    scope = seal.get("validation_scope")
    if (scope not in {"host_construction_only", "software_test", "software_fake_host"}
            or (intent.get("validation_scope") == "software_test" and scope not in {"software_test", "software_fake_host"})
            or (intent.get("validation_scope") == "host_construction_only" and scope != "host_construction_only")
            or identity.get("validation_scope") != scope or result.get("validation_scope") != scope):
        raise ValueError("worker validation scope is inconsistent")
    if (result.get("operation_id") != operation["operation_id"] or result.get("graph_id") != operation["graph_id"]
            or result.get("graph_hash") != compiled.graph_hash or result.get("visual_verified") is not False
            or result.get("construction_executed") is not True or result.get("reconciliation_required") is not False):
        raise ValueError("result does not prove completed construction")
    artifact_path = owned_file(root, paths["directory"] / (operation["operation_id"] + ".hip"))
    digest = file_sha256(artifact_path)
    artifact, verification = result.get("artifact"), result.get("verification")
    if not isinstance(artifact, Mapping) or not isinstance(verification, Mapping):
        raise ValueError("result has no artifact verification")
    for record in (artifact, verification):
        if (record.get("hip_path") != str(artifact_path) or record.get("hip_sha256") != digest
                or any(record.get(key) is not True for key in ("nodes_verified", "parameters_verified", "connections_verified"))):
            raise ValueError("owned project hash or verification does not match")
    if seal.get("artifact_sha256") != digest:
        raise ValueError("owned project changed after completion")
    task_id = str(intent.get("task_id") or operation["operation_id"])
    node_root = "/obj/BRIDGE_GRAPH_" + hashlib.sha256((task_id + ":" + compiled.graph_hash).encode()).hexdigest()
    topology = result.get("topology")
    layout=catalogue.native_layout(compiled,node_root)
    expected_nodes = {address:row['path'] for address,row in layout.items()}
    expected_connections=[]
    ports=verification.get('native_port_interfaces',{})
    for c in compiled.connections:
        source,target=expected_nodes[c.source_node],expected_nodes[c.target_node]
        binding=catalogue.connection_binding(compiled,c)
        if binding.get('input_name') or binding.get('output_name'):
            binding=catalogue.resolve_connection_binding(binding,ports.get(source,{}),ports.get(target,{}))
        if binding['kind']=='reference':
            expected_connections.append({'source':source,'destination':target,'kind':'container_dependency' if binding['field'].startswith('@') else 'reference','field':binding['field']})
        else:
            entry={'source':source,'destination':target,'input_index':binding['input_index']}
            if binding['output_index']:entry['output_index']=binding['output_index']
            expected_connections.append(entry)
    # Domain stages preserve their connection order within each fixed stage.
    schedule=catalogue.bounded_domain_schedule(compiled)
    if schedule:expected_connections=[expected_connections[i] for stage in schedule['stages'] for i in stage['connections']]
    if (not isinstance(topology, Mapping) or topology.get("root") != node_root
            or topology.get("nodes") != expected_nodes or topology.get("connections") != expected_connections
            or verification.get("root") != node_root or artifact.get("root") != node_root):
        raise ValueError("completed topology differs from the registered graph")
    entries, journal_sha256 = _journal_evidence(root, paths["journal"])
    # 协议由可信作业范围和重新编译结果确定，不能采信结果自述来降低验证。
    from vfx_pipeline.official_graph_batch import operations as construction_operations, validate_stage_evidence, PROTOCOL as BATCH_PROTOCOL
    expected_operations = {key: value for key, value in construction_operations(inputs, compiled, node_root)
                           if value.get("kind") != "node.set_parms" or value.get("parameters")}
    batch_scope = validate_stage_evidence(inputs, compiled, node_root, entries)
    if batch_scope is not None:
        if (result.get("construction_protocol") != BATCH_PROTOCOL
                or any(record.get("native_batch_scope") != batch_scope for record in (artifact, verification))):
            raise ValueError("official batch verification scope differs from the trusted job")
    elif result.get("construction_protocol") is not None:
        raise ValueError("unexpected construction protocol outside its trusted scope")
    if (set(entries) != set(expected_operations) or any(entries[key].get("intent") != value
            for key, value in expected_operations.items()) or seal.get("journal_sha256") != journal_sha256
            or seal.get("leases_sha256") != _lease_evidence(root, paths["lease"])):
        raise ValueError("operation journal or scene ownership differs from completion")
    return dict(result)


def run_job(job: Mapping[str, Any], *, addon: Any = None, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    worker = GraphJobWorker(job, addon=addon, clock=clock)
    # GraphJobService supplies this task-owned preference directory through the
    # subprocess environment.  The explicit software backend uses the same
    # shipped worker in-process, so reproduce that narrow launcher contract
    # only for the injected fake-host seam and restore the caller environment
    # after the worker exits.
    prior_pref = os.environ.get("HOUDINI_USER_PREF_DIR")
    if addon is not None:
        pref = worker.result_path.parent / "houdini-user-pref" / "__HVER__"
        pref.mkdir(parents=True, exist_ok=True)
        os.environ["HOUDINI_USER_PREF_DIR"] = str(pref)
    try:
        result = worker.run()
        atomic_json(worker.result_path, result, root=worker.root)
        if worker.managed and result.get("construction_executed") is True and result.get("reconciliation_required") is False:
            _seal_completion(worker, result)
        return result
    finally:
        if addon is not None:
            if prior_pref is None:
                os.environ.pop("HOUDINI_USER_PREF_DIR", None)
            else:
                os.environ["HOUDINI_USER_PREF_DIR"] = prior_pref


def _parse_job(value: str) -> Mapping[str, Any]:
    payload = json.loads(value)
    if not isinstance(payload, Mapping):
        raise ValueError("--job must contain an object")
    return payload


def _parse_job_file(value: str, expected_sha256: str) -> Mapping[str, Any]:
    from houdini_bridge.native_geometry_runtime_registry import _read_file
    from houdini_bridge.render_ocio_facts import _file_path
    from vfx_pipeline.graph_job_evidence import MAX_JSON_BYTES

    path = _file_path(value)
    raw, _ = _read_file(dict(source_uri=value, bytes=path.lstat().st_size,
                             sha256=expected_sha256), MAX_JSON_BYTES)
    job = _parse_job(raw.decode('utf-8'))
    root = Path(str(job.get('root') or ''))
    if (not root.is_absolute() or _owned_path(root, value, must_exist=True) != path
            or path != Path(str(job.get('result_path') or '')).parent / 'worker-job.json'):
        raise ValueError('worker job file must belong to its owned attempt directory')
    return job


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge construction graph worker")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--job", help="service-owned job JSON")
    transport.add_argument('--job-file', help='service-owned bounded job JSON file')
    parser.add_argument('--job-file-sha256', help='frozen job file SHA-256')
    args = parser.parse_args(argv)
    _startup_checkpoint("main_arguments_parsed")
    try:
        if args.job_file:
            job = _parse_job_file(args.job_file, args.job_file_sha256)
        else:
            if args.job_file_sha256 is not None:
                raise ValueError('job file digest requires the job-file transport')
            job = _parse_job(args.job)
        _startup_checkpoint("main_job_parsed")
        run_job(job)
    except Exception:
        # If inputs are malformed no safe result can be trusted. The parent
        # service will classify a missing result as reconciliation required.
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by hython
    raise SystemExit(main())


__all__ = ["DurableJournal", "GraphJobWorker", "main", "run_job", "REGISTERED_SOP_TYPES"]
