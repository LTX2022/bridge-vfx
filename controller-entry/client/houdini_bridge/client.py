"""HTTP client and safe multi-instance discovery for Houdini Bridge."""

from __future__ import annotations

import errno
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import uuid4

from .paths import bridge_tokens_for_port, manifests_dir
from .registry import canonical_command
from .render_observation_budget import (
    FileReadBudget, RenderObservationLimit, read_store_payload,
    validate_render_record, validate_store,
)


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str, hint: Optional[str] = None, *, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.details = dict(details or {})
        self.indeterminate = bool(self.details.get("indeterminate", False))


@dataclass(frozen=True)
class HoudiniInstance:
    port: int
    data: dict[str, Any]
    source: str
    token: Optional[str] = field(default=None, repr=False)


class HoudiniClient:
    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        timeout_seconds: float = 60.0,
        token: Optional[str] = None,
    ) -> None:
        self.port = int(port)
        self.host = host
        self.timeout_seconds = timeout_seconds
        self._loopback = self.host in {"127.0.0.1", "localhost", "::1"}
        supplied = str(token or "") or None
        if self._loopback and token != "":
            discovered = bridge_tokens_for_port(self.port)
        else:
            discovered = ()
        candidates = ([supplied] if supplied else []) + [item for item in discovered if item != supplied]
        self._token_candidates = tuple(candidates)
        self.token = self._token_candidates[0] if self._token_candidates else supplied

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/api"

    def health(self) -> dict[str, Any]:
        return self._rpc("mcp.health", [], {})

    def call(self, command: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        canonical = canonical_command(command)
        return self._rpc("mcp.execute", [], {"command": canonical, "params": params or {}, "request_id": uuid4().hex})

    def _rpc(self, method: str, args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
        payload = urllib.parse.urlencode({"json": json.dumps([method, args, kwargs], ensure_ascii=False)}).encode("utf-8")
        candidates: tuple[Optional[str], ...] = self._token_candidates or (None,)
        result: Any = None
        for index, candidate in enumerate(candidates):
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if candidate:
                headers["Authorization"] = "Bearer " + candidate
            request = urllib.request.Request(self.endpoint, data=payload, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read().decode("utf-8")
                except Exception as read_exc:
                    raise BridgeError("BRIDGE_HTTP_ERROR", f"Houdini Bridge returned HTTP {exc.code}") from read_exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise BridgeError("BRIDGE_UNREACHABLE", f"Houdini Bridge is unreachable at {self.endpoint}: {exc}") from exc
            try:
                result = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BridgeError("INVALID_RESPONSE", "Houdini Bridge returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise BridgeError("INVALID_RESPONSE", "Houdini Bridge returned a non-object JSON response")
            error = result.get("error") if result.get("status") != "success" else None
            if (
                isinstance(error, dict)
                and error.get("code") == "AUTH_REQUIRED"
                and index + 1 < len(candidates)
            ):
                continue
            if result.get("status") == "success":
                self.token = candidate
                if candidate:
                    self._token_candidates = (candidate,) + tuple(
                        item for item in self._token_candidates if item != candidate
                    )
            break
        if result.get("status") != "success":
            error = result.get("error") or {}
            raise BridgeError(str(error.get("code") or "BRIDGE_ERROR"), str(error.get("message") or "Houdini Bridge command failed"), error.get("hint"), details={key: error[key] for key in ("indeterminate", "operation_state") if key in error})
        data = result.get("data")
        return data if isinstance(data, dict) else {"value": data}


def _candidate_ports() -> Iterable[int]:
    yielded: set[int] = set()
    directory = manifests_dir()
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                port = int(json.loads(path.read_text(encoding="utf-8")).get("port"))
            except (ValueError, OSError, json.JSONDecodeError, TypeError):
                continue
            if 8100 <= port <= 8199 and port not in yielded:
                yielded.add(port)
                yield port
    for port in range(8100, 8200):
        if port not in yielded:
            yield port


def _probe(port: int) -> Optional[HoudiniInstance]:
    client = HoudiniClient(port, timeout_seconds=0.35)
    try:
        data = client.health()
    except BridgeError:
        return None
    return HoudiniInstance(port=port, data=data, source="health", token=client.token)


def discover_instances() -> list[HoudiniInstance]:
    instances: list[HoudiniInstance] = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_probe, port): port for port in _candidate_ports()}
        for future in as_completed(futures):
            instance = future.result()
            if instance is not None:
                instances.append(instance)
    return sorted(instances, key=lambda item: item.port)


def render_receipt_digest(fact: dict[str, Any]) -> str:
    import hashlib
    return hashlib.sha256(json.dumps({k: v for k, v in fact.items() if k != "operation_receipt_sha256"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def render_producer_binding(record: dict[str, Any]) -> dict[str, Any]:
    """Freeze this at render.start in the controller, never from a later status.

    The digest is an integrity check, not a signature. Trust comes from the
    controller retaining the original task-owned host's start response.
    """
    try:
        validate_render_record(record)
    except RenderObservationLimit as error:
        raise BridgeError("RENDER_OBSERVATION_BUDGET_EXCEEDED", str(error)) from error
    request = {"task_id": record["task_id"], "frames": record["frames"],
               "budget_seconds": float(record["budget_seconds"]),
               "scene_sha256": record["scene"]["snapshot_sha256"],
               "render_target": record["render_target"], "output_pattern": record["output_pattern"],
               "dependencies": record["dependencies"]}
    if "project_color" in record:
        from dcc_task_runtime.project_color import validate_project_color
        request["project_color"] = validate_project_color(record["project_color"])
    if "output_acceptance" in record:
        from .controlled_output import validate_controlled_policy
        request["output_acceptance"] = validate_controlled_policy(record["output_acceptance"])
    fingerprint = render_receipt_digest({"scene": record["scene"]["snapshot_sha256"],
                                         "config": record["render_config"]})
    if (render_receipt_digest(request) != record["request_sha256"]
            or fingerprint != record["scene_fingerprint"]):
        raise BridgeError("OPERATION_BINDING_MISMATCH", "render request, saved scene or configuration changed")
    result = {key: record[key] for key in (
        "task_id", "request_id", "request_sha256", "host_identity", "supervisor_binding",
        "scene", "scene_fingerprint", "render_target", "render_config", "frames", "output_pattern",
        "dependencies", "budget_seconds", "started_at_epoch")}
    if "project_color" in request:
        result["project_color"] = request["project_color"]
    if "output_acceptance" in request:
        result["output_acceptance"] = request["output_acceptance"]
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def _render_file_observation(path, expected, *, decode=False, read_budget=None):
    """Decode exactly the bytes hashed, then check descriptor and path identity.

    This is an immutable observation, not a lock on an external renderer's file.
    The controller and registry must verify bytes again at each trust boundary.
    """
    import hashlib
    import os
    import stat
    import tempfile
    from dcc_task_runtime.exr_codec import read_exr

    path = Path(path)

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def check_path():
        for component in (path, *path.parents):
            info = component.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
                raise ValueError("output or save traverses a symlink/reparse point")

    try:
        if not path.is_absolute() or str(path) != expected.get("path"):
            raise ValueError("absolute frozen file path required")
        check_path()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as source, tempfile.TemporaryDirectory(prefix="houdini-output-observation-") as directory:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_size <= 0
                    or (decode and before.st_size > 512 * 1024 * 1024)
                    or any(key in expected and expected[key] != value for key, value in (
                        ("bytes", before.st_size), ("modified_ns", before.st_mtime_ns)))):
                raise ValueError("frozen file size/time differs or exceeds EXR byte budget")
            if read_budget is not None:
                read_budget.reserve(before.st_size+1)
            digest, size = hashlib.sha256(), 0
            copy_path = Path(directory) / "frame.exr"
            with copy_path.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > before.st_size:
                        raise ValueError("file grew while observing bytes")
                    digest.update(chunk)
                    if decode:
                        target.write(chunk)
            if size != before.st_size or digest.hexdigest() != expected.get("sha256"):
                raise ValueError("actual bytes differ from producer snapshot")
            metadata = read_exr(copy_path, with_pixels=False) if decode else {}
            check_path()
            if identity(before) != identity(os.fstat(source.fileno())) or identity(before) != identity(path.stat()):
                raise ValueError("file replaced or changed during observation")
            metadata.pop("rows", None)
            return metadata
    except RenderObservationLimit as exc:
        raise BridgeError("RENDER_OBSERVATION_BUDGET_EXCEEDED", str(exc)) from exc
    except (OSError, ValueError, TypeError) as exc:
        raise BridgeError("RENDER_OUTPUT_BYTES_UNVERIFIED", str(exc)) from exc


_RENDER_MISSING_NATIVE_FACTS = (
    "OUTPUT_OVERRIDE_AOV_AND_ORDERED_FILTER_EXECUTION_REQUIRED",
    "KARMA_HUSK_BEAUTY_ALPHA_ASSOCIATION_REQUIRED",
)


_COLOR_TRACE_GAPS = frozenset({
    "EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED",
    "OCIO_PREFLIGHT_OBSERVATION_REQUIRED",
    "PXL_EFFECTIVE_WRITER_OCIO_INSTANCE_UNOBSERVED",
    "WRITER_AOV_EFFECTIVE_COLOR_COVERAGE_UNOBSERVED",
})


def _legacy_color_receipt(record):
    # Reproduce immutable pre-policy signed receipts without upgrading them.
    return ("project_color" not in record and
            "EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED" in
            (record.get("execution_fact") or {}).get("completion_metadata_missing_facts", []))


def _project_color(record):
    if "project_color" not in record:
        return None
    from dcc_task_runtime.project_color import validate_project_color
    return validate_project_color(record["project_color"])


def collect_render_output_fact(record: dict[str, Any], frame: int, *, read_budget=None) -> dict[str, Any]:
    """Called after native frame return and snapshot, before frames_done append.

    Physical EXR metadata and composed USD configuration are observations only.
    Neither EXR channels nor USD tokens establish color space or alpha association.
    """
    from dcc_task_runtime.artifact_registry import frame_path

    read_budget = read_budget if read_budget is not None else FileReadBudget()
    producer = render_producer_binding(record)
    if type(frame) is not int or frame not in record["frames"]:
        raise BridgeError("RENDER_OUTPUT_BINDING_MISMATCH", "frame is not in the frozen request")
    snapshot = record["frame_snapshots"][str(frame)]
    path = frame_path(record["output_pattern"], frame)
    if snapshot.get("path") != str(path):
        raise BridgeError("RENDER_OUTPUT_BINDING_MISMATCH", "frame path differs from frozen output pattern")
    ocio = record["render_config"][str(frame)].get("ocio_configuration_fact")
    missing = list(_RENDER_MISSING_NATIVE_FACTS)
    selection = _project_color(record)
    legacy = _legacy_color_receipt(record)
    if legacy:
        missing.insert(0, "EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED")
        if ocio is None:
            missing.append("OCIO_PREFLIGHT_OBSERVATION_REQUIRED")
    elif selection is None:
        missing.append("PROJECT_COLOR_SELECTION_REQUIRED")
    # Existing snapshots retain their recorded configuration integrity checks.
    # Human-selected operations do not collect or require this trace.
    if selection is None and ocio is not None:
        if not isinstance(ocio, dict) or ocio.get("final_output_path") != str(path):
            raise BridgeError("RENDER_OUTPUT_BINDING_MISMATCH", "OCIO preflight differs from the final output path")
        from houdini_bridge.render_ocio_facts import validate_ocio_configuration
        try:
            validate_ocio_configuration(ocio, read_budget=read_budget)
        except RenderObservationLimit as error:
            raise BridgeError("RENDER_OBSERVATION_BUDGET_EXCEEDED", str(error)) from error
        except (OSError, ValueError, TypeError) as error:
            raise BridgeError("RENDER_OCIO_CONFIGURATION_CHANGED", str(error)) from error
    metadata = _render_file_observation(path, snapshot, decode=True, read_budget=read_budget)
    compression = {"none": 0, "zips": 2, "zip": 3}.get(
        record["render_config"][str(frame)]["exr_format"]["compression"])
    if metadata.get("compression") != compression:
        raise BridgeError("RENDER_OUTPUT_BINDING_MISMATCH", "EXR compression differs from frozen config")
    if snapshot.get("exr") is not None and snapshot["exr"] != {
            key: metadata[key] for key in ("width", "height", "channels", "compression")}:
        raise BridgeError("RENDER_OUTPUT_BINDING_MISMATCH", "EXR header differs from producer snapshot")
    metadata.update({key: snapshot[key] for key in ("path", "bytes", "modified_ns", "sha256")})
    if selection is not None:
        metadata.update(colorspace=selection["colorspace"], project_color=selection)
    writer = record.get("writer_observations", {}).get(str(frame))
    if writer is None:
        missing.append("HUSK_POSTFRAME_OBSERVATION_REQUIRED")
    else:
        from houdini_bridge.render_writer_facts import validate_writer_observation, writer_root
        try:
            writer_body = validate_writer_observation(
                writer, render_receipt_digest(producer), frame, snapshot,
                expected_root=writer_root(record), read_budget=read_budget,
                host_identity=producer['host_identity'], supervisor_binding=producer['supervisor_binding'])
        except RenderObservationLimit as error:
            raise BridgeError("RENDER_OBSERVATION_BUDGET_EXCEEDED", str(error)) from error
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise BridgeError("RENDER_WRITER_OBSERVATION_INVALID", str(error)) from error
        missing.extend(gap for gap in writer_body["missing_facts"] if legacy or gap not in _COLOR_TRACE_GAPS)
    return {"schema": "bridge.houdini.render-output-observation/1.0", "frame": frame,
            "producer_binding_sha256": render_receipt_digest(producer),
            "metadata": metadata,
            **({"project_color": selection} if selection is not None else {}),
            "color_configuration_fact": json.loads(json.dumps(
                record["render_config"][str(frame)].get("color_configuration_fact"), allow_nan=False)),
            "ocio_configuration_fact": json.loads(json.dumps(ocio, allow_nan=False)),
            "writer_observation": json.loads(json.dumps(writer, allow_nan=False)),
            "missing_facts": missing}


def render_execution_fact(record):
    fact = {"schema": "bridge.houdini.render.execution_fact/1.0", "command": "render.start", "kind": "render",
            "execution_kind": "task_owned_host", "operation_id": record["request_id"], "request_id": record["request_id"],
            "task_id": record["task_id"], "request_sha256": record["request_sha256"], "state": record["state"],
            "host_identity": record["host_identity"], "scene": record["scene"], "scene_fingerprint": record["scene_fingerprint"],
            "render_target": record["render_target"], "render_config": record["render_config"],
            "frame_set": record["frames"], "frames_done": record["frames_done"], "output_pattern": record["output_pattern"],
            "budget_seconds": record["budget_seconds"], "started_at_epoch": record["started_at_epoch"],
            "finished_at": record.get("finished_at"), "frame_snapshots": record["frame_snapshots"],
            "dependencies": record["dependencies"], "stop_confirmed": True,
            "stop_basis": record.get("stop_receipt") or record["lifecycle_fact"], "supervisor_binding": record["supervisor_binding"]}
    # The queued scene stays a byte-stable reference (it is frozen inside the
    # controller's producer binding); the terminal record carries the contract
    # beside it, and only the execution fact embeds the two together.
    evidence = record.get("scene_contract_evidence")
    if (isinstance(evidence, dict) and isinstance(fact["scene"], dict)
            and not isinstance(fact["scene"].get("scene_contract"), dict)):
        fact["scene"] = {**fact["scene"], "scene_contract": evidence}
    fact["producer_binding_sha256"] = render_receipt_digest(render_producer_binding(record))
    fact["output_facts"] = record.get("output_facts", {})
    fact["completion_metadata_status"] = "BLOCKED_MISSING_NATIVE_FACTS"
    fact["completion_metadata_missing_facts"] = list(_RENDER_MISSING_NATIVE_FACTS)
    selection = _project_color(record)
    legacy = _legacy_color_receipt(record)
    if legacy:
        fact["completion_metadata_missing_facts"].insert(0, "EFFECTIVE_OCIO_CONFIG_LUT_CONTEXT_FILE_RULE_REQUIRED")
        if any(record["render_config"].get(str(frame), {}).get("ocio_configuration_fact") is None
               for frame in record["frames"]):
            fact["completion_metadata_missing_facts"].append("OCIO_PREFLIGHT_OBSERVATION_REQUIRED")
    elif selection is None:
        fact["completion_metadata_missing_facts"].append("PROJECT_COLOR_SELECTION_REQUIRED")
    else:
        fact["project_color"] = selection
    if set(fact["output_facts"]) != {str(frame) for frame in record["frames"]}:
        fact["completion_metadata_missing_facts"].append("FRAME_OUTPUT_OBSERVATION_REQUIRED")
    for frame in record["frames"]:
        output = fact["output_facts"].get(str(frame), {})
        if output.get("writer_observation") is None:
            if "HUSK_POSTFRAME_OBSERVATION_REQUIRED" not in fact["completion_metadata_missing_facts"]:
                fact["completion_metadata_missing_facts"].append("HUSK_POSTFRAME_OBSERVATION_REQUIRED")
        for gap in output.get("missing_facts", []):
            if (legacy or gap not in _COLOR_TRACE_GAPS) and gap not in fact["completion_metadata_missing_facts"]:
                fact["completion_metadata_missing_facts"].append(gap)
    fact["metadata"] = {}
    fact = json.loads(json.dumps(fact, ensure_ascii=False, allow_nan=False))
    fact["operation_receipt_sha256"] = render_receipt_digest(fact)
    return fact


def _render_terminal_event(producer):
    return "render-terminal-" + render_receipt_digest({
        "task_id": producer["task_id"], "operation_id": producer["request_id"]})


def render_terminal_pending_record(record: dict[str, Any]) -> dict[str, Any]:
    """Publish prepaid reads without exposing an unsealed terminal result.

    The producer retains its completed candidate while each durable quota
    reservation publishes this active projection. A crashed producer therefore
    follows the existing stale RUNNING reconciliation path.
    """
    import copy
    validate_render_record(record)
    if record.get("kind") != "render" or record.get("state") != "COMPLETED":
        raise ValueError("terminal sealing projection requires a completed render candidate")
    pending = copy.deepcopy(record)
    pending["state"] = "RUNNING"
    pending["stage"] = "render_terminal_sealing"
    for key in ("execution_fact", "lifecycle_fact", "finished_at"):
        pending.pop(key, None)
    history = pending.get("history")
    if history and history[-1].get("to") == "COMPLETED":
        history[-1]["to"] = "RUNNING"
        history[-1]["note"] = "render_terminal_sealing"
    return pending


def seal_render_terminal(record: dict[str, Any], *, read_budget=None) -> dict[str, Any]:
    """Producer-only hook after the COMPLETED execution_fact, before store save.

    Uses this live owned child's freshly generated supervisor runtime key through
    owned_process. The permanent exclusive claim prevents replacement/re-signing;
    an identical retry returns the original authenticated event without writing.
    A crash after claiming leaves a specific failure, never permission to reseal.
    """
    import hashlib
    import os
    from dcc_task_runtime.owned_process import SCHEMA, _canonical, _signed_write, read_receipt
    from dcc_task_runtime.platform_support import open_private_file, process_identity

    producer = render_producer_binding(record)
    supervisor = producer["supervisor_binding"]
    directory = Path(supervisor["directory"])
    try:
        started = read_receipt(directory, "started", identity=supervisor["identity"])
        current = process_identity(os.getpid())
        if (not started or started["pid"] != os.getpid()
                or producer["host_identity"].get("pid") != os.getpid()
                or supervisor["identity"].get("task_id") != producer["task_id"]
                or not supervisor["identity"].get("launch_nonce")
                or supervisor["identity"]["launch_nonce"] != producer["host_identity"].get("launch_nonce")
                or current.get("state") != "alive"
                or (started.get("platform") == "windows" and current.get("birth") != started.get("process_birth"))
                or read_receipt(directory, "stopped", identity=supervisor["identity"]) is not None):
            raise BridgeError("RENDER_TERMINAL_PRODUCER_REQUIRED", "only the current authenticated owned child can seal outputs")
        fact = render_execution_fact(record)
        if (record.get("state") != "COMPLETED" or record.get("execution_fact") != fact
                or fact["frames_done"] != fact["frame_set"]
                or set(fact["output_facts"]) != {str(frame) for frame in fact["frame_set"]}
                or set(fact["frame_snapshots"]) != {str(frame) for frame in fact["frame_set"]}):
            raise BridgeError("RENDER_TERMINAL_INCOMPLETE", "complete producer frame observations and execution fact required")
        event = _render_terminal_event(producer)
        payload = {"schema": SCHEMA, "event": event, "identity": supervisor["identity"],
                   "pid": started["pid"], "started_sha256": hashlib.sha256(_canonical(started)).hexdigest(),
                   "producer_binding_sha256": render_receipt_digest(producer), "execution_fact": fact}
        original = read_receipt(directory, event, identity=supervisor["identity"])
        if original is not None:
            if original != payload:
                raise BridgeError("RENDER_TERMINAL_ANCHOR_MISMATCH", "terminal original cannot be replaced or re-signed")
            return original
        _render_file_observation(record["scene"]["snapshot_path"], {
            "path": record["scene"]["snapshot_path"], "sha256": record["scene"]["snapshot_sha256"]})
        read_budget = read_budget if read_budget is not None else FileReadBudget()
        for frame in fact["frame_set"]:
            if collect_render_output_fact(record, frame, read_budget=read_budget) != fact["output_facts"][str(frame)]:
                raise BridgeError("RENDER_TERMINAL_ANCHOR_MISMATCH", "producer observation differs from terminal bytes")
        claim = directory / (event + ".claim")
        try:
            descriptor = open_private_file(claim)
        except FileExistsError as exc:
            raise BridgeError("RENDER_TERMINAL_ALREADY_CLAIMED", "incomplete terminal seal cannot be retried with new bytes") from exc
        os.close(descriptor)
        if (directory / (event + ".json")).exists():
            raise BridgeError("RENDER_TERMINAL_ALREADY_CLAIMED", "terminal original already exists")
        _signed_write(directory, payload)
        if read_receipt(directory, event, identity=supervisor["identity"]) != payload:
            raise BridgeError("RENDER_TERMINAL_ANCHOR_MISMATCH", "terminal original could not be authenticated")
        return payload
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BridgeError("RENDER_TERMINAL_ANCHOR_INVALID", str(exc)) from exc


def _verify_render_terminal(binding, fact):
    import hashlib
    from dcc_task_runtime.owned_process import _canonical, read_receipt

    producer = binding["producer_binding"]
    supervisor = producer["supervisor_binding"]
    try:
        event = _render_terminal_event(producer)
        original = read_receipt(supervisor["directory"], event, identity=supervisor["identity"])
        if original is None:
            raise BridgeError("RENDER_TERMINAL_ANCHOR_REQUIRED", "COMPLETED requires its original producer terminal event; status cannot seal it")
        started = read_receipt(supervisor["directory"], "started", identity=supervisor["identity"])
        if (not started or original.get("pid") != producer["host_identity"].get("pid")
                or started.get("pid") != original.get("pid")
                or original.get("started_sha256") != hashlib.sha256(_canonical(started)).hexdigest()
                or original.get("producer_binding_sha256") != render_receipt_digest(producer)
                or original.get("execution_fact") != fact):
            raise BridgeError("RENDER_TERMINAL_ANCHOR_MISMATCH", "receipt differs from authenticated producer terminal original")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BridgeError("RENDER_TERMINAL_ANCHOR_INVALID", str(exc)) from exc


def _read_render_store_snapshot(path: Path) -> dict[str, Any]:
    deadline = time.monotonic() + .5
    for attempt in range(20):
        if path.is_symlink():
            raise BridgeError('OPERATION_STORE_INVALID', 'render store is a symlink')
        try:
            payload = read_store_payload(path)
        except RenderObservationLimit as error:
            raise BridgeError('RENDER_OBSERVATION_BUDGET_EXCEEDED', str(error)) from error
        except OSError as error:
            remaining = deadline - time.monotonic()
            winerror = getattr(error, 'winerror', None)
            sharing_denied = winerror in (5, 32, 33) or winerror is None and error.errno == errno.EACCES
            if (os.name != 'nt' or not sharing_denied
                    or remaining <= 0 or attempt == 19):
                raise
            time.sleep(min(.01 * 2 ** min(attempt, 3), .05, remaining))
            continue
        try:
            store = json.loads(payload)
        except RecursionError as error:
            raise BridgeError('OPERATION_STORE_INVALID', 'operation store nesting exceeds parser limits') from error
        try:
            validate_store(store)
        except RenderObservationLimit as error:
            raise BridgeError('RENDER_OBSERVATION_BUDGET_EXCEEDED', str(error)) from error
        except ValueError as error:
            raise BridgeError('OPERATION_STORE_INVALID', str(error)) from error
        return store


def read_render_operation(binding: dict[str, Any], *, task_id: str, operation_id: str,
                          cancel: bool = False) -> dict[str, Any]:
    """Read the persisted formal runner, even while HOM blocks or the host exited.

    Binding is obtained only from render.start and kept by the configured
    controller. A stop transition uses the original supervisor's signed wait
    observation. It never starts native work or registers an artifact.
    """
    from dcc_task_runtime.execution_lock import execution_lock
    from dcc_task_runtime.owned_process import read_receipt, _atomic
    from dcc_task_runtime.graph_scheduler import GraphScheduler
    path = Path(binding["operation_store_path"])
    if path.is_symlink():
        raise BridgeError("OPERATION_STORE_INVALID", "render store is a symlink")
    from contextlib import contextmanager, nullcontext
    supervisor = binding["supervisor_binding"]
    pre_stopped = read_receipt(supervisor["directory"], "stopped", identity=supervisor["identity"])
    verified_stopped_record = None

    @contextmanager
    def release_verified_stop_on_error():
        try:
            yield
        except Exception as error:
            if verified_stopped_record is not None:
                try:
                    slot = verified_stopped_record["slot"]
                    if slot.get("owner_root") != str(path) or slot.get("operation_id") != operation_id:
                        raise BridgeError("OPERATION_BINDING_MISMATCH", "render slot belongs to another operation")
                    GraphScheduler(Path(verified_stopped_record["scheduler_root"])).release(
                        slot["owner_root"], slot["operation_id"], slot["token"], stopped=True)
                except Exception as release_error:
                    error.args = (str(error) + "; verified stop slot release failed: " + str(release_error),)
            raise

    # Atomic runner snapshots are safe to read while native render holds the
    # execution lock. Only a stopped worker can be reconciled and rewritten.
    with (execution_lock(path.parent, task_id) if pre_stopped is not None else nullcontext()), release_verified_stop_on_error():
        store = _read_render_store_snapshot(path)
        from .operation_store import resolve_record, write_snapshot
        try:
            record = resolve_record(path, store, operation_id)
        except (ValueError, OSError, RecursionError) as error:
            raise BridgeError("OPERATION_ARCHIVE_INVALID", str(error)) from error
        if (not isinstance(record, dict) or record.get("kind") != "render"
                or record.get("task_id") != task_id or record.get("request_id") != operation_id
                or record.get("request_sha256") != binding.get("request_sha256")
                or record.get("host_identity") != binding.get("host_identity")
                or record.get("supervisor_binding") != binding.get("supervisor_binding")):
            raise BridgeError("OPERATION_BINDING_MISMATCH", "render record differs from controller's frozen binding")
        if not isinstance(binding.get("producer_binding"), dict):
            raise BridgeError("OPERATION_PRODUCER_BINDING_REQUIRED", "controller must freeze producer_binding at render.start; old status cannot supply it")
        if render_producer_binding(record) != binding["producer_binding"]:
            raise BridgeError("OPERATION_BINDING_MISMATCH", "render configuration/save differs from controller's frozen start")
        supervisor = record["supervisor_binding"]
        stopped = read_receipt(supervisor["directory"], "stopped", identity=supervisor["identity"])
        active = record.get("state") in {"QUEUED", "RUNNING", "CANCEL_PENDING", "RECONCILE"}
        recovered_terminal = False
        if active and cancel and stopped is None:
            _atomic(Path(supervisor["directory"]) / "operation-cancel.json", {
                "identity": supervisor["identity"], "pid": record["host_identity"]["pid"],
                "operation_id": operation_id, "token": record["budget_token"], "host_identity": record["host_identity"]})
        if stopped is not None:
            observed = stopped.get("operation") or {}
            if (stopped.get("pid") != record["host_identity"]["pid"]
                    or (observed and (observed.get("operation_id") != operation_id
                                     or observed.get("token") != record["budget_token"]
                                     or observed.get("host_identity") != record["host_identity"]))):
                raise BridgeError("SUPERVISOR_STOP_NOT_BOUND", "stop belongs to another render")
            verified_stopped_record = record
        if active and stopped is not None:
            original = None
            if record.get("stage") == "render_terminal_sealing":
                try:
                    original = read_receipt(supervisor["directory"], _render_terminal_event(binding["producer_binding"]),
                                            identity=supervisor["identity"])
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise BridgeError("RENDER_TERMINAL_ANCHOR_INVALID", str(error)) from error
            if original is not None:
                import copy
                sealed = original.get("execution_fact")
                _verify_render_terminal(binding, sealed)
                if not isinstance(sealed, dict) or sealed.get("state") != "COMPLETED":
                    raise BridgeError("RENDER_TERMINAL_ANCHOR_MISMATCH", "terminal original is not a completed producer fact")
                # Restore only fields intentionally omitted by the pending
                # projection. All retained observations still must match below.
                record = copy.deepcopy(record)
                record.update(state="COMPLETED", finished_at=sealed.get("finished_at"),
                              lifecycle_fact=copy.deepcopy(sealed.get("stop_basis")),
                              execution_fact=copy.deepcopy(sealed))
                recovered_terminal = True
            else:
                reason = str(stopped.get("stop_reason") or "")
                record["state"] = ("BUDGET_REACHED" if "BUDGET" in reason else
                                   "CANCELLED" if "CANCEL" in reason else "FAILED")
                record["stop_receipt"] = stopped
                record["finished_at"] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
                record["history"] = list(record.get("history") or []) + [{"at": record["finished_at"],
                    "to": record["state"], "note": "original supervisor observed owned worker exit"}]
                record["stage"] = "owned_host_stop_observed"
                record["execution_fact"] = render_execution_fact(record)
                # Known process stop is durable before release. A completed
                # fact is never invented from partial or unrecorded files.
                try:
                    write_snapshot(path, store)
                except RenderObservationLimit as error:
                    raise BridgeError('RENDER_OBSERVATION_BUDGET_EXCEEDED', str(error)) from error
        fact = record.get("execution_fact")
        if record.get("state") == "COMPLETED":
            _verify_render_terminal(binding, fact)
        if fact is not None:
            if (not isinstance(fact, dict) or fact != render_execution_fact(record)
                    or fact.get("schema") != "bridge.houdini.render.execution_fact/1.0"
                    or fact.get("operation_id") != operation_id or fact.get("task_id") != task_id
                    or fact.get("operation_receipt_sha256") != render_receipt_digest(fact)
                    or fact.get("host_identity") != binding["host_identity"]
                    or fact.get("request_sha256") != binding["request_sha256"]
                    or fact.get("state") != record.get("state")
                    or (fact.get("state") == "COMPLETED" and (
                        fact.get("frames_done") != fact.get("frame_set")
                        or set(fact.get("frame_snapshots") or {}) != {str(f) for f in fact.get("frame_set", [])}))):
                raise BridgeError("RECEIPT_MISMATCH", "formal render receipt is not intact or bound")
            if fact.get("state") == "COMPLETED":
                _render_file_observation(record["scene"]["snapshot_path"], {
                    "path": record["scene"]["snapshot_path"], "sha256": record["scene"]["snapshot_sha256"]})
                read_budget = FileReadBudget()
                for frame in record["frames"]:
                    observed = collect_render_output_fact(record, frame, read_budget=read_budget)
                    saved = fact["output_facts"].get(str(frame))
                    if saved is not None and observed != saved:
                        raise BridgeError("RECEIPT_MISMATCH", "frame observation differs from actual bytes/configuration")
            if fact.get("stop_confirmed") is True:
                slot = record["slot"]
                if slot.get("owner_root") != str(path) or slot.get("operation_id") != operation_id:
                    raise BridgeError("OPERATION_BINDING_MISMATCH", "render slot belongs to another operation")
                if recovered_terminal:
                    record["stage"] = "render_terminal_original_recovered"
                    record["terminal_recovery_stop_receipt"] = stopped
                    record["history"] = list(record.get("history") or []) + [{
                        "at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                        "to": "COMPLETED", "note": "original producer terminal verified after supervisor-observed exit"}]
                    store["operations"][operation_id] = record
                    try:
                        write_snapshot(path, store)
                    except RenderObservationLimit as error:
                        raise BridgeError('RENDER_OBSERVATION_BUDGET_EXCEEDED', str(error)) from error
                # Durable stop and scheduler release are separate commits. A
                # failed release is retried from the same fact, without any
                # native execution or artifact registration.
                GraphScheduler(Path(record["scheduler_root"])).release(
                    slot["owner_root"], slot["operation_id"], slot["token"], stopped=True)
        return {"operation": record, "execution_fact": fact}
