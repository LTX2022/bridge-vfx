"""C3 shared assembly: ONE facade construction path for generator and tests.

``build_graph_facade`` is the only sanctioned construction of the WorkBuddy
graph facade.  The formal generator (tools/prepare_workbuddy_graph.py) embeds
it in the generated control server; software tests call the same function
with explicit backend injections (fake HOM client, software worker).  Tests
may NOT replace GraphRun/GraphMCP/this assembly or the save/reopen services.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any
from datetime import datetime, timezone

from .graph_jobs import GraphJobService
from .workbuddy_graph_mcp import GraphRun

MAX_FRAMES_PER_OPERATION = 12
MAX_BUDGET_SECONDS = 120.0


import os
import sys


def _record_software_dispatch(kind: str, command: str) -> None:
    """Record fake-host calls only when a software acceptance test asks."""
    destination = os.environ.get("BRIDGE_SOFTWARE_{}_CALL_LOG".format(str(kind).upper()))
    if not destination:
        return
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"command": str(command)}, ensure_ascii=False) + "\n")


def software_host_client(addon_source: Path, state_dir: Path):
    """A host client backed by the REAL add-on dispatch; fake HOM only.

    Imports the shipped Houdini add-on (no DCC), injects a minimal fake
    ``hou`` namespace built here, and serves bridge commands through the real
    production dispatch/guards.  Used ONLY with backend='software'.
    """
    import importlib.util
    import types

    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    nodes = {}

    class _Parm:
        def __init__(self, name):
            self._name = name
            self.value = 0.0

        def name(self):
            return self._name

        def eval(self):
            return self.value

        def set(self, value):
            self.value = value

    _ALL_NODES: dict = {}

    class _Node:
        def __init__(self, path, node_type="null"):
            self._path = path
            self._type_name = str(node_type)
            self._children = []
            self._inputs = []
            self._input_output_indices = []
            self.parms_dict = {}
            self._data = {}
            _ALL_NODES[path] = self

        def path(self):
            return self._path

        def name(self):
            return self._path.rsplit("/", 1)[-1]

        def userData(self, key):
            return self._data.get(key)

        def setUserData(self, key, value):
            self._data[key] = value

        def type(self):
            parent_path=self._path.rsplit('/',1)[0] or '/'
            parent=_ALL_NODES.get(parent_path) if self._path!='/' else None
            category=({'root':'Manager','obj':'Obj','stage':'Lop','mat':'Vop',
                       'geo':'Sop','lopnet':'Lop','matnet':'Vop','ropnet':'Driver','dopnet':'Dop'}
                      .get(parent._type_name,parent.type().category().name()) if parent else 'Manager')
            return types.SimpleNamespace(
                name=lambda: self._type_name,
                nameWithCategory=lambda: "{}/{}".format(category,self._type_name),
                category=lambda: types.SimpleNamespace(name=lambda:category),
                definition=lambda: None,
            )

        # This explicit bottom-native software fixture models ordinary nodes,
        # not digital asset definitions or delayed asset contents.
        def isLockedHDA(self):
            return False

        def isDelayedDefinition(self):
            return False

        def children(self):
            return tuple(self._children)

        def allSubChildren(self, top_down=True, recurse_in_locked_nodes=True,
                           sync_delayed_definition=False):
            result = []
            for child in self._children:
                if top_down:
                    result.append(child)
                result.extend(child.allSubChildren(top_down=top_down,
                    recurse_in_locked_nodes=recurse_in_locked_nodes,
                    sync_delayed_definition=sync_delayed_definition))
                if not top_down:
                    result.append(child)
            return tuple(result)

        def setPosition(self, position):
            return None

        def createNode(self, node_type, name, *, exact_type_name=False):
            child_path = "/{}".format(name) if self._path == "/" else "{}/{}".format(self._path, name)
            child = _Node(child_path, node_type)
            self._children.append(child)
            return child

        def destroy(self):
            for child in tuple(self._children):
                child.destroy()
            parent = _ALL_NODES.get(self._path.rsplit("/", 1)[0])
            if parent is not None and self in parent._children:
                parent._children.remove(self)
            _ALL_NODES.pop(self._path, None)
            nodes.pop(self._path, None)
            for other in _ALL_NODES.values():
                for index, source in enumerate(other._inputs):
                    if source is self:
                        other._inputs[index] = None

        def setInput(self, index, source, output_index=0):
            index = int(index)
            if index < 0:
                raise ValueError("input index must be non-negative")
            while len(self._inputs) <= index:
                self._inputs.append(None)
                self._input_output_indices.append(0)
            self._inputs[index] = source
            self._input_output_indices[index] = int(output_index)

        def inputConnections(self):
            return tuple(types.SimpleNamespace(inputNode=lambda source=source: source,
                         outputNode=lambda: self, inputIndex=lambda index=index: index,
                         outputIndex=lambda index=index: self._input_output_indices[index])
                         for index, source in enumerate(self._inputs) if source is not None)

        def inputs(self):
            return tuple(self._inputs)

        def cook(self, force=False):
            self.cooked = True

        def errors(self):
            return []

        def warnings(self):
            return []

        def geometry(self):
            return types.SimpleNamespace(
                boundingBox=lambda: types.SimpleNamespace(sizevec=lambda: (1.0, 1.0, 1.0)),
                points=lambda: [], prims=lambda: [], pointAttribs=lambda: [])

        def parms(self):
            return list(self.parms_dict.values())

        def parm(self, name):
            # The catalog/feedback layer validates parameter names and ranges
            # before this fake HOM boundary.  Once a trusted graph reaches the
            # add-on, lazily materialize the corresponding HOM knob so the
            # real ``node.set_parms`` path can be exercised without a DCC.
            if name not in self.parms_dict:
                self.parms_dict[name] = _Parm(name)
            return self.parms_dict[name]

    for base in ("/", "/obj", "/stage", "/mat"):
        nodes[base] = _Node(base, "root" if base == "/" else base.lstrip("/"))
    nodes.update(_ALL_NODES)
    _callbacks = {"list": []}
    holder = {"path": str(state_dir / "software-task.hip")}
    current_frame = [1.0]

    def _set_frame(value):
        import math
        frame = float(value)
        if not math.isfinite(frame):
            raise ValueError("software native frame must be finite")
        current_frame[0] = frame

    def _expand_string(value):
        import re
        current = Path(fake_hou.hipFile.path()).expanduser().resolve()
        variables = {"HIP": str(current.parent), "HIPNAME": current.stem}
        def replace(match):
            key = match.group(1) or match.group(2)
            return variables.get(key, os.environ.get(key, match.group(0)))
        return re.sub(r"\$\{([A-Za-z_][A-Za-z_0-9]*)\}|\$([A-Za-z_][A-Za-z_0-9]*)", replace, str(value))

    def _scene_snapshot():
        records = []
        for path, node in sorted(_ALL_NODES.items(), key=lambda item: (item[0].count("/"), item[0])):
            if path in {"/", "/obj", "/stage", "/mat"}:
                continue
            records.append({
                "path": path,
                "type": node._type_name,
                "data": dict(node._data),
                "parms": {name: parm.value for name, parm in node.parms_dict.items()},
                "inputs": [{"path": item.path(), "output_index": node._input_output_indices[index]}
                           if item is not None else None for index, item in enumerate(node._inputs)],
            })
        return {"schema": "bridge.strict_fake_hom_scene/1.0", "nodes": records}

    def _restore_scene(path):
        raw = Path(path).read_bytes()
        header = b"bridge.software_hom_snapshot/1\n"
        if not raw.startswith(header):
            raise ValueError("SOFTWARE_SCENE_SNAPSHOT_INVALID")
        payload = json.loads(raw[len(header):].decode("utf-8"))
        records = payload.get("nodes") if isinstance(payload, dict) else None
        if payload.get("schema") != "bridge.strict_fake_hom_scene/1.0" or not isinstance(records, list):
            raise ValueError("SOFTWARE_SCENE_SNAPSHOT_INVALID")
        for stale in list(_ALL_NODES):
            if stale not in {"/", "/obj", "/stage", "/mat"}:
                _ALL_NODES.pop(stale, None)
                nodes.pop(stale, None)
        for root in ("/obj", "/stage", "/mat"):
            root_node = _ALL_NODES[root]
            root_node._children = []
            root_node._inputs = []
            root_node._input_output_indices = []
            root_node.parms_dict = {}
            root_node._data = {}
        loaded = {}
        for record in sorted(records, key=lambda item: (str(item.get("path") or "").count("/"), str(item.get("path") or ""))):
            node_path = str(record.get("path") or "")
            parent_path = node_path.rsplit("/", 1)[0]
            parent = _ALL_NODES.get(parent_path)
            if not node_path.startswith(("/obj/", "/stage/", "/mat/")) or parent is None:
                raise ValueError("fake-HOM scene sidecar contains an invalid node path")
            node = _Node(node_path, str(record.get("type") or "null"))
            parent._children.append(node)
            nodes[node_path] = node
            node._data = dict(record.get("data") or {})
            pending = dict(record.get("parms") or {})
            while pending:
                progress = False
                for name, value in tuple(pending.items()):
                    parm = node.parm(str(name))
                    if parm is None:
                        continue
                    parm.set(value)
                    del pending[name]
                    progress = True
                if not progress:
                    raise ValueError("saved native parameters are not addressable: " + repr(sorted(pending)))
            loaded[node_path] = node
        for record in records:
            node = loaded.get(str(record.get("path") or ""))
            if node is None:
                continue
            node._inputs = []
            node._input_output_indices = []
            for index, connection in enumerate(record.get("inputs") or []):
                if connection is not None:
                    if not isinstance(connection, dict) or type(connection.get("output_index")) is not int:
                        raise ValueError("SOFTWARE_SCENE_CONNECTION_INVALID")
                    source = _ALL_NODES.get(str(connection.get("path")))
                    if source is None:
                        raise ValueError("fake-HOM scene sidecar contains a missing input")
                    node.setInput(index, source, connection["output_index"])
        holder["path"] = str(path)

    def _hip_save(target=None):
        # faithful HOM: saving to a target makes that target the current file
        target_path = Path(target or holder["path"]).expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = json.dumps(_scene_snapshot(), ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8")
        temporary = target_path.with_name(target_path.name + ".saving")
        temporary.write_bytes(b"bridge.software_hom_snapshot/1\n" + snapshot)
        temporary.replace(target_path)
        if target:
            holder["path"] = str(target_path)

    def _hip_load(path, *args, **kwargs):
        target_path = Path(path).expanduser().resolve()
        if not target_path.is_file():
            raise FileNotFoundError(str(target_path))
        for callback in tuple(_callbacks["list"]):
            callback("BeforeLoad")
        for callback in tuple(_callbacks["list"]):
            callback("BeforeClear")
        _restore_scene(target_path)
        for callback in tuple(_callbacks["list"]):
            callback("AfterClear")
        for callback in tuple(_callbacks["list"]):
            callback("AfterLoad")

    def _children(path):
        parent = nodes.get(path)
        return [child for child in nodes.values()
                if parent is not None and child is not parent
                and child.path().rsplit("/", 1)[0] == path]

    fake_hou = types.SimpleNamespace(
        _bridge_software_boundary=True,
        node=lambda p: _ALL_NODES.get(p) or nodes.get(p), undos=None, isUIAvailable=lambda: False,
        setFrame=_set_frame, time=lambda: (current_frame[0] - 1.0) / 24.0, fps=lambda: 24.0,
        frame=lambda: current_frame[0],
        applicationVersionString=lambda: "21.0.631",
        licenseCategory=lambda: types.SimpleNamespace(name=lambda: "BaseEngine"),
        python_version=lambda: "3.11",
        expandString=_expand_string, _bridge_expand_string=_expand_string,
        getenv=lambda name: os.environ.get(str(name), ""),
        envName=lambda: lambda name: os.environ.get(str(name), ""),
        hipFile=types.SimpleNamespace(path=lambda: holder["path"], save=_hip_save,
                                      load=_hip_load,
                                      setName=lambda path: holder.update(path=str(Path(path).expanduser().resolve())),
                                      hasUnsavedChanges=lambda: False,
                                      eventCallbacks=lambda: _callbacks["list"],
                                      addEventCallback=lambda cb: _callbacks["list"].append(cb)),
        hipFileEventType=types.SimpleNamespace(
            BeforeClear="BeforeClear", BeforeLoad="BeforeLoad", BeforeMerge="BeforeMerge",
            AfterClear="AfterClear", AfterLoad="AfterLoad"),
        LoadWarning=type("LoadWarning", (Exception,), {}),
    )
    missing_module = object()
    scene_state_key = "_houdini_bridge_scene_identity_state"
    previous_hou = sys.modules.get("hou", missing_module)
    previous_scene_state = sys.modules.pop(scene_state_key, missing_module)
    sys.modules["hou"] = fake_hou
    try:
        # Each newly constructed HOM namespace models a separate host session.
        # Reloading the add-on within that namespace retains its own scene state.
        spec = importlib.util.spec_from_file_location("_assembly_houdini_addon", addon_source)
        addon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(addon)
    except BaseException:
        for name, previous in (("hou", previous_hou), (scene_state_key, previous_scene_state)):
            if previous is missing_module:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        raise
    sys.modules["hou"] = fake_hou

    class _Client:
        backend_kind = "software_fake_hou"

        def call(self, command, params):
            _record_software_dispatch("host", command)
            result = addon.dispatch(command, dict(params))
            # expose created nodes to the fake HOM graph
            for key in ("path",):
                value = result.get(key) if isinstance(result, dict) else None
                if (isinstance(value, str) and value.startswith("/obj/")
                        and value not in nodes and value not in _ALL_NODES):
                    nodes[value] = _Node(value)
            return result

        def mark_graph_trial_complete(self, task_id, result):
            """Bind a completed graph through the shipped add-on route.

            The controller supplies only the graph worker's persisted
            completion receipt.  The add-on validates the receipt against the
            live node topology and derives the operation manifest/lease; the
            assembly never seeds FX state or a synthetic replacement graph.
            """
            task_id = str(task_id or "")
            if not task_id or not isinstance(result, dict):
                raise ValueError("graph trial completion requires a task binding and receipt")
            from .graph_job_evidence import owned_file
            payload = result.get('result') or {}
            if (result.get('task_id') != task_id or result.get('state') != 'SUCCEEDED'
                    or result.get('stop_confirmed') is not True
                    or payload.get('construction_executed') is not True
                    or payload.get('reconciliation_required') is not False
                    or payload.get('validation_scope') != 'software_fake_host'):
                raise ValueError('SOFTWARE_GRAPH_HANDOFF_NOT_VERIFIED')
            operation_id = str(result.get('operation_id') or '')
            artifact = payload.get('artifact') or {}
            relative = Path(str(artifact.get('path') or ''))
            parts = relative.parts
            if (not operation_id or relative.is_absolute() or len(parts) != 4
                    or parts[:2] != ('graph-jobs', operation_id)
                    or not re.fullmatch(r'attempt-[1-9][0-9]*', parts[2])
                    or parts[3] != operation_id + '.hip' or '..' in parts):
                raise ValueError('SOFTWARE_GRAPH_ARTIFACT_PATH_INVALID')
            jobs_root = state_dir.parent / 'jobs'
            if any(parent.is_symlink() for parent in (jobs_root, *jobs_root.parents)):
                raise ValueError('SOFTWARE_GRAPH_ARTIFACT_ROOT_SYMLINK')
            path = owned_file(jobs_root, jobs_root / relative)
            digest = str(artifact.get('sha256') or '')
            if (not re.fullmatch(r'[0-9a-f]{64}', digest)
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise ValueError('SOFTWARE_GRAPH_ARTIFACT_CHANGED')
            root, manifest = addon._fx_manifest(task_id, required=False)
            if root is not None or manifest:
                evidence = manifest.get('graph_trial_evidence') or {}
                expected_root = (payload.get('topology') or {}).get('root')
                if (root is None or root.path() != expected_root
                        or manifest.get('task_id') != task_id
                        or manifest.get('execution_root') != expected_root
                        or manifest.get('graph_hash') != payload.get('graph_hash')
                        or manifest.get('graph_trial_operation_id') != operation_id
                        or evidence.get('hip_sha256') != digest
                        or any(evidence.get(name) is not True for name in
                               ('construction_executed', 'nodes_verified', 'parameters_verified', 'connections_verified'))
                        or root.userData('bridge_fx_owned') != '1'
                        or json.loads(root.userData('bridge_fx_manifest_v1') or '{}') != manifest):
                    raise ValueError('SOFTWARE_GRAPH_HANDOFF_CHANGED')
                addon._root_lease_check(expected_root, task_id=task_id, scope='sop', renew=False)
                return {'task_id': manifest['task_id'], 'execution_root': manifest['execution_root'],
                        'operation_id': manifest['graph_trial_operation_id'],
                        'graph_trial_evidence': json.loads(json.dumps(evidence)), 'replayed': True}
            if any(node_path not in {'/', '/obj', '/stage', '/mat'} for node_path in _ALL_NODES):
                raise ValueError('SOFTWARE_GRAPH_HANDOFF_SCENE_NOT_EMPTY')
            current = Path(fake_hou.hipFile.path())
            if (current != path or not current.is_file()
                    or hashlib.sha256(current.read_bytes()).hexdigest() != digest):
                fake_hou.hipFile.load(str(path), suppress_save_prompt=True)
            _record_software_dispatch("host", "agent.fx.bind_graph_trial")
            binding = addon.dispatch("agent.fx.bind_graph_trial", {
                "task_id": task_id, "trial_receipt": result,
            })
            if (binding.get('graph_ready') is not True or binding.get('nodes_verified') is not True
                    or binding.get('connections_verified') is not True):
                raise ValueError('SOFTWARE_GRAPH_HANDOFF_BINDING_UNVERIFIED')
            return binding

        def drain(self, task_id, operation_id):
            """Advance the in-process fake host to an observed terminal state.

            The formal software profile still dispatches through the add-on's
            public operation API.  This helper only supplies the host's event
            loop that a real Houdini process would normally own, so a test can
            issue a second request without relying on a timing race.
            """
            runner = addon.fx_operation_runner(str(task_id))
            for _ in range(32):
                status = runner.status(str(operation_id))
                if status.get("state") in {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_REACHED", "RECONCILE"}:
                    return status
                runner.advance()
            return runner.status(str(operation_id))

        def prepare_task(self, task_id):
            """Reopen the last controller save when a software host restarts.

            A real Houdini process requires the explicit task-reopen control
            action.  The generated software profile starts a fresh fake host
            subprocess for each formal test session, so this is the equivalent
            host-session bootstrap: it uses only the persisted controller save
            receipt and the shipped add-on's own reopen implementation.
            """
            save_path = addon._fx_task_saves_path(str(task_id))
            if not save_path.is_file():
                return None
            try:
                saved = json.loads(save_path.read_text(encoding="utf-8"))
                receipt = (saved.get("saves") or [])[-1]
            except (OSError, ValueError, IndexError):
                return None
            if not isinstance(receipt, dict) or not receipt.get("path") or not receipt.get("sha256"):
                return None
            return addon.scene_reopen_task_hip({
                "task_id": str(task_id), "path": str(receipt["path"]),
                "sha256": str(receipt["sha256"]),
            })

        def operation_fact(self, operation_id, task_id=None):
            return addon._fx_software_boundary_operation_fact(
                str(operation_id or ""), str(task_id or ""))

        def recover_owned_worker(self, task_id, domain=None, scene_path=None,
                                 scene_sha256=None, operation_id=None, spec=None,
                                 output_path=None, output_pattern=None):
            """Crash and resume the same task-owned Houdini software operation."""
            from dcc_task_runtime.owned_process import OwnedProcessHandle, launch

            if not scene_path or not scene_sha256 or not domain or not isinstance(spec, dict):
                raise ValueError("RECOVERY_INPUT_REQUIRED")
            worker = Path(addon_source).resolve().parents[3] / "tools" / "software_recovery_worker.py"
            operation = str(operation_id or ("recovery-" + str(task_id))).strip()
            safe_task = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in str(task_id))[:120]
            safe_operation = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in operation)[:120]
            root = state_dir / "owned-worker-recovery" / safe_task
            spec_payload = {**dict(spec), "domain_pack": str(domain),
                            "houdini_version": str(fake_hou.applicationVersionString()),
                            "output_path": str(output_path or spec.get("output_path") or ""),
                            "output_pattern": str(output_pattern or spec.get("output_pattern") or "")}
            if bool(spec_payload["output_path"]) == bool(spec_payload["output_pattern"]):
                raise ValueError("RECOVERY_OUTPUT_BINDING_REQUIRED")
            spec_path = root / (safe_operation + ".spec.json")
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")

            def run(attempt, phase):
                directory = root / (safe_operation + "-attempt-{}".format(attempt))
                event = directory / "worker-event.json"
                nonce = hashlib.sha256((str(task_id) + "\0" + operation + "\0" + str(attempt)).encode("utf-8")).hexdigest()[:24]
                identity = {"task_id": str(task_id), "operation_id": operation,
                            "launch_nonce": nonce, "phase": str(phase)}
                command = [sys.executable, str(worker), "--kind", "houdini", "--phase", phase,
                           "--task-id", str(task_id), "--operation-id", operation,
                           "--client-state-dir", str(state_dir), "--event", str(event),
                           "--spec", str(spec_path), "--addon-source", str(addon_source),
                           "--scene-path", str(scene_path), "--scene-sha256", str(scene_sha256)]
                handle = launch(command, directory=directory, identity=identity,
                                supervisor_executable=sys.executable, env=dict(os.environ), budget_seconds=30)
                started = dict(handle.started)
                del handle
                fresh = OwnedProcessHandle(directory, identity)
                exit_code = fresh.wait(15)
                stopped = fresh.receipt()
                if not isinstance(stopped, dict) or stopped.get("observed_by") != "owned_child_wait":
                    raise RuntimeError("RECOVERY_STOP_OBSERVATION_INVALID")
                event_payload = json.loads(event.read_text(encoding="utf-8")) if event.is_file() else {}
                return {"directory": str(directory), "command": command, "identity": identity,
                        "started": started, "stopped": stopped, "exit_code": exit_code,
                        "event": event_payload}

            crashed = run(1, "initial")
            if crashed["exit_code"] != 17 or crashed["event"].get("result", {}).get("status") != "CHECKPOINT_REACHED":
                raise RuntimeError("RECOVERY_CHECKPOINT_NOT_OBSERVED")
            resumed = run(2, "resume")
            if resumed["exit_code"] != 0 or resumed["event"].get("result", {}).get("status") != "COMPLETED":
                raise RuntimeError("RECOVERY_RESUME_NOT_COMPLETED")
            result = resumed["event"].get("result") or {}
            artifact = result.get("output_artifact") or {}
            if output_path and not Path(output_path).is_file():
                raise RuntimeError("RECOVERY_OUTPUT_NOT_WRITTEN")
            if output_pattern:
                from dcc_task_runtime.artifact_registry import frame_path
                if any(not frame_path(output_pattern, int(frame)).is_file() for frame in spec_payload.get("frames") or [1, 2]):
                    raise RuntimeError("RECOVERY_OUTPUT_NOT_WRITTEN")
            controller_reopen = self.prepare_task(task_id)
            if not isinstance(controller_reopen, dict) or controller_reopen.get("structure_verified", 0) <= 0:
                raise RuntimeError("RECOVERY_CONTROLLER_REOPEN_UNVERIFIED")
            return {
                "tested": True, "software_boundary_only": True,
                "worker_crash": {"exit_code": crashed["exit_code"], "pid": crashed["started"].get("pid"),
                                 "operation_id": operation, "command": crashed["command"],
                                 "checkpoint": crashed["event"]},
                "supervisor": {"directory": crashed["directory"], "started": crashed["started"],
                                "stopped": crashed["stopped"], "stop_confirmed": True},
                "resume": {"directory": resumed["directory"], "started": resumed["started"],
                            "stopped": resumed["stopped"], "stop_confirmed": True,
                            "operation_id": operation, "command": resumed["command"],
                            "result": result, "output_artifact": artifact},
                "controller_restart": {"fresh_handle_read": True, "same_operation_resumed": True,
                                       "task_reopen": controller_reopen},
                "domain_execution": result,
            }

    return _Client(), addon


def software_nuke_client(addon_source: Path, state_dir: Path, written: "list | None" = None,
                         worker_script: "Path | None" = None, *, background: bool = False):
    """A Nuke client backed by the REAL Nuke add-on dispatch (fake nuke module)."""
    import importlib.util
    import types

    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    class _Knob:
        def __init__(self, value, name=""):
            self._value = value
            self._name = str(name or "")
            self._animated = False
            self._expression = False
            self._visible = True

        def value(self):
            return self._value

        def setValue(self, value):
            self._value = value

        def setAnimated(self, *_args):
            self._animated = True

        def setValueAt(self, value, _frame, *_args):
            self._value = value

        def isAnimated(self, *_args):
            return self._animated

        def hasExpression(self, *_args):
            return self._expression

        def setVisible(self, visible):
            self._visible = bool(visible)

    class _Root:
        def __init__(self, name):
            self._name = name
            self._first = _Knob(1, "first_frame")
            self._last = _Knob(12, "last_frame")

        def name(self):
            return self._name

        def modified(self):
            return False

        def __getitem__(self, key):
            return self._first if key == "first_frame" else self._last

        def knob(self, key):
            return self[key] if key in {"first_frame", "last_frame"} else None

        def knobs(self):
            return {"first_frame": self._first, "last_frame": self._last}

    pattern = str(state_dir / "render.%03d.exr")

    node_by_name = {}
    nuke_nodes = []
    node_counter = {"value": 0}

    _NODE_KNOBS = {
        "Read": {"file": ""},
        "Copy": {"from0": "", "to0": ""},
        "Blur": {"size": 0.0, "disable": True},
        "Defocus": {"defocus": 0.0, "disable": True},
        "Denoise2": {"mix": 0.0, "disable": True},
        "Denoise": {"mix": 0.0, "disable": True},
        "Sharpen": {"size": 0.0, "amount": 0.0, "disable": True},
        "Glow": {"size": 0.0, "mix": 0.0, "brightness": 0.0, "disable": True},
        "ColorCorrect": {"contrast": 0.0, "disable": True},
        "EdgeBlur": {"size": 0.0, "disable": True},
        "Grain2": {"mix": 0.0, "intensity": 0.0, "disable": True},
        "Grain": {"mix": 0.0, "intensity": 0.0, "disable": True},
        "Premult": {"disable": True},
        "Merge2": {"operation": "over", "mix": 1.0, "disable": False},
        "NoOp": {},
        "Write": {"file": ""},
    }

    class _Node:
        def __init__(self, name, node_class, knobs=None, inputs=None):
            self._name = str(name)
            self._node_class = str(node_class)
            self._knobs = {
                str(key): _Knob(value, str(key))
                for key, value in dict(knobs or {}).items()
            }
            self._inputs = list(inputs or [])
            self._xpos = 0
            self._ypos = 0
            self._deleted = False

        def name(self):
            return self._name

        def fullName(self):
            return self._name

        def setName(self, name):
            old = self._name
            self._name = str(name)
            if node_by_name.get(old) is self:
                node_by_name.pop(old, None)
            if not self._deleted:
                node_by_name[self._name] = self

        def Class(self):
            return self._node_class

        def __getitem__(self, key):
            knob = self.knob(key)
            if knob is None:
                raise KeyError(key)
            return knob

        def knob(self, key):
            return self._knobs.get(str(key))

        def knobs(self):
            return dict(self._knobs)

        def addKnob(self, knob):
            name = str(getattr(knob, "_name", "") or "")
            if not name:
                raise ValueError("software Nuke knobs require a name")
            self._knobs[name] = knob

        def removeKnob(self, knob):
            for name, candidate in list(self._knobs.items()):
                if candidate is knob:
                    del self._knobs[name]

        def setInput(self, index, node):
            index = int(index)
            while len(self._inputs) <= index:
                self._inputs.append(None)
            self._inputs[index] = node

        def input(self, index):
            index = int(index)
            return self._inputs[index] if 0 <= index < len(self._inputs) else None

        def inputs(self):
            # Nuke returns the input count, not the input tuple.
            return len(self._inputs)

        def setXpos(self, value):
            self._xpos = int(value)

        def setYpos(self, value):
            self._ypos = int(value)

        def xpos(self):
            return self._xpos

        def ypos(self):
            return self._ypos

        def width(self):
            return 1

        def height(self):
            return 1

        def channels(self):
            return ["rgba.red", "rgba.green", "rgba.blue", "rgba.alpha"]

    def _register_node(node):
        nuke_nodes.append(node)
        node_by_name[node.name()] = node
        return node

    def _new_node(node_class, name=None, inputs=None, *, register=True):
        node_class = str(node_class)
        if node_class not in _NODE_KNOBS:
            raise ValueError("software Nuke node class is unavailable: " + node_class)
        if name is None:
            node_counter["value"] += 1
            name = f"{node_class}_{node_counter['value']}"
        if str(name) in node_by_name:
            raise ValueError("software Nuke node name already exists: " + str(name))
        node = _Node(name, node_class, _NODE_KNOBS[node_class], inputs)
        return _register_node(node) if register else node

    write_node = _new_node("Write", "Write1")
    read_node = _new_node("Read", "Read1")
    read_node["file"].setValue(pattern)
    write_node["file"].setValue(pattern)
    root_node = _Root(str(state_dir / "software.nk"))

    def _read_frame_path(pattern_value, frame):
        from dcc_task_runtime.artifact_registry import frame_path
        return frame_path(str(pattern_value), int(frame))

    def _upstream_reads(node, seen=None):
        seen = set() if seen is None else seen
        if node is None or id(node) in seen:
            return []
        seen.add(id(node))
        if node.Class() == "Read":
            return [node]
        reads = []
        for index in range(int(node.inputs())):
            reads.extend(_upstream_reads(node.input(index), seen))
        return reads

    def _execute(write, first, last, *rest):
        reads = _upstream_reads(write)
        if not reads:
            raise ValueError("Write node has no upstream Read source")
        for source in reads:
            source_pattern = str(source["file"].value() or "")
            for frame in range(int(first), int(last) + 1):
                if not _read_frame_path(source_pattern, frame).is_file():
                    raise ValueError("Read source frame is unavailable")
        for frame in range(int(first), int(last) + 1):
            output = _read_frame_path(str(write["file"].value() or ""), frame)
            output.parent.mkdir(parents=True, exist_ok=True)
            from dcc_task_runtime.exr_codec import encode_tiny_exr
            output.write_bytes(encode_tiny_exr(float(frame)))

    def _script_save():
        _script_save_as(root_node.name(), overwrite=True)

    def _script_save_as(path, overwrite=False):
        target = Path(path).expanduser().resolve()
        if target.exists() and not overwrite:
            raise FileExistsError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = {}
        for node in list(nuke_nodes):
            if node._deleted:
                continue
            serialized[node.name()] = {
                "class": node.Class(),
                "file": str(node.knob("file").value()) if node.knob("file") is not None else "",
                "knobs": {name: knob.value() for name, knob in node.knobs().items()},
                "inputs": [
                    node.input(index).name() if node.input(index) is not None else None
                    for index in range(int(node.inputs()))
                ],
                "xpos": int(node.xpos()),
                "ypos": int(node.ypos()),
            }
        payload = {"schema": "bridge.software_nuke_snapshot/1",
                   "root": {key: root_node[key].value() for key in ("first_frame", "last_frame")},
                   "nodes": serialized}
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        root_node._name = str(target)

    def _script_open(path):
        from nuke_bridge.owned_render_worker import _read_software_snapshot
        payload = _read_software_snapshot(Path(path))
        nodes = payload["nodes"]
        if nodes.get("Read1", {}).get("class") != "Read" or nodes.get("Write1", {}).get("class") != "Write":
            raise ValueError("software composition fixture requires Read1 and Write1")
        for node in list(nuke_nodes):
            if node not in (read_node, write_node):
                node._deleted = True
                node_by_name.pop(node.name(), None)
        nuke_nodes[:] = [read_node, write_node]
        objects = {"Read1": read_node, "Write1": write_node}
        for name, record in nodes.items():
            if name in objects:
                node = objects[name]
            else:
                node = _new_node(record["class"], name)
                objects[name] = node
        for name, record in nodes.items():
            node = objects[name]
            values = dict(record.get("knobs") or {})
            if "file" not in values:
                values["file"] = record.get("file", "")
            for knob_name, value in values.items():
                knob = node.knob(knob_name)
                if knob is None:
                    knob = _Knob(value, knob_name)
                    node.addKnob(knob)
                else:
                    knob.setValue(value)
            node._inputs = [objects[target] if target is not None else None for target in record.get("inputs", [])]
            node.setXpos(record.get("xpos", 0))
            node.setYpos(record.get("ypos", 0))
        for key in ("first_frame", "last_frame"):
            root_node[key].setValue(payload["root"][key])
        root_node._name = str(Path(path).resolve())

    class _Undo:
        def __init__(self, _label):
            self.label = str(_label)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    def _node_factory(node_class, **kwargs):
        inputs = kwargs.pop("inputs", None)
        name = kwargs.pop("name", None)
        node = _new_node(node_class, name, inputs)
        if "file" in kwargs and node.knob("file") is not None:
            node["file"].setValue(kwargs["file"])
        return node

    def _delete_node(node):
        if node is None or node in (read_node, write_node):
            return None
        node._deleted = True
        node_by_name.pop(node.name(), None)
        return None

    fake_nuke = types.SimpleNamespace(
        root=lambda: root_node,
        node=lambda name: node_by_name.get(str(name)),
        toNode=lambda name: node_by_name.get(str(name)),
        allNodes=lambda recurseGroups=False: [node for node in nuke_nodes if not node._deleted],
        createNode=lambda node_class, inpanel=False: _new_node(node_class),
        delete=lambda node: _delete_node(node),
        String_Knob=lambda name, label: _Knob("", str(name)),
        nodes=types.SimpleNamespace(
            Read=lambda **kwargs: _node_factory("Read", **kwargs),
            Write=lambda **kwargs: _node_factory("Write", **kwargs),
        ),
        NUKE_VERSION_STRING="17.0v1-software",
        GUI=False,
        scriptSave=_script_save,
        scriptSaveAs=_script_save_as,
        scriptOpen=_script_open,
        modified=lambda: False,
        Undo=_Undo,
        execute=_execute,
    )
    import sys as _sys
    previous = _sys.modules.get("nuke")
    _sys.modules["nuke"] = fake_nuke
    spec = importlib.util.spec_from_file_location("_assembly_nuke_addon", addon_source)
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    if worker_script is not None:
        addon.configure_nuke_background_route(nuke_executable=str(Path(sys.executable).resolve()),
                                              worker_script=str(worker_script), software_api=True)

    class _Client:
        backend_kind = "software_fake_nuke"
        _registry = None

        def bind_artifact_registry(self, registry):
            addon._NUKE_ARTIFACT_REGISTRY = registry
            registry.set_operation_source(addon._nuke_operation_fact)
            self._registry = registry

        def prepare_input_artifact(self, task_id, frames=(1, 2), dependencies=None):
            """Create a controller-owned software fixture through C2 itself.

            This is only the formal software backend's synthetic source.  The
            operation still goes through the shipped render entry and ledger;
            production hosts do not auto-create input artifacts.
            """
            if self._registry is None:
                raise ValueError("artifact registry is not bound")
            artifact_id = "formal-input-" + str(task_id)
            existing = self._registry.lookup(artifact_id)
            if existing is not None:
                return artifact_id
            from dcc_task_runtime.exr_codec import encode_tiny_exr
            from dcc_task_runtime.artifact_registry import frame_path
            source_pattern = str(state_dir / "formal-source.%03d.exr")
            output_pattern = str(state_dir / "formal-input.%03d.exr")
            for frame in frames:
                frame_path(source_pattern, frame).write_bytes(encode_tiny_exr(float(frame)))
            read_node["file"].setValue(source_pattern)
            write_node["file"].setValue(output_pattern)
            write_node.setInput(0, read_node)
            result = addon.dispatch("render_write", {
                "node": "Write1", "pattern": output_pattern,
                "frame_set": list(frames), "frame_range": [min(frames), max(frames)],
                "background": False, "request_id": "bootstrap-" + str(task_id)[:80],
                "colorspace": "scene_linear", "premultiplied": False,
                "output_binding": {
                    "source": "controller", "node": "Write1", "pattern": output_pattern,
                    "frames": list(frames), "input_binding": {"kind": "bootstrap_source", "owner_task_id": task_id},
                },
            })
            operation_id = str(result.get("operation_id") or result.get("task_id") or "")
            fact = addon._nuke_operation_fact(operation_id) or {}
            lineage_dependencies = ["software-formal-source"]
            lineage_dependencies.extend(str(item) for item in (dependencies or []) if str(item))
            self._registry.register(
                artifact_id=artifact_id, task_id=str(fact.get("task_id") or "nuke:render_write"),
                artifact_class="confirmed_cache", pattern=output_pattern,
                frame_set=list(frames), colorspace="scene_linear", premultiplied=False,
                dependencies=lineage_dependencies, operation_id=operation_id,
                operation_receipt_sha256=str(fact.get("operation_receipt_sha256") or ""),
            )
            return artifact_id

        def render_binding(self, task_id, output_pattern, frames, colorspace, premultiplied,
                           artifact_binding=None):
            _record_software_dispatch("nuke", "render_binding")
            artifact_binding = dict(artifact_binding or {})
            input_pattern = str(artifact_binding.get("pattern") or "")
            if not input_pattern or not artifact_binding.get("usable_as_render_input"):
                raise ValueError("a usable artifact is required for the Read node")
            read_node["file"].setValue(input_pattern)
            write_node["file"].setValue(str(output_pattern))
            write_node.setInput(0, read_node)
            verification = {
                "source": "Read1", "destination": "Write1", "input_index": 0,
                "read_path": input_pattern, "frame_set": list(frames),
                "connected": write_node.input(0) is read_node,
            }
            return {
                "source": "controller", "task_id": str(task_id or ""), "node": "Write1",
                "pattern": str(output_pattern), "frames": list(frames),
                "input_binding": {"kind": "artifact_read", "owner_task_id": task_id,
                                   "artifact_id": str(artifact_binding.get("artifact_id") or ""),
                                   "read_node": "Read1", "read_path": input_pattern,
                                   "frame_set": list(frames),
                                   "connection": verification,
                                   "connection_verified": bool(verification["connected"])},
                **({"project_color": json.loads(json.dumps(artifact_binding["project_color"]))}
                   if artifact_binding.get("project_color") is not None else {}),
                "background": bool(background),
            }

        def call(self, command, params=None):
            _record_software_dispatch("nuke", command)
            return addon.dispatch(command, dict(params or {}))

        def recover_owned_worker(self, task_id, script_path=None, script_sha256=None,
                                 spec=None, output_pattern=None, operation_id=None,
                                 write_node=None):
            """Crash and resume the same task-owned Nuke software operation."""
            from dcc_task_runtime.owned_process import OwnedProcessHandle, launch

            if not script_path or not script_sha256 or not isinstance(spec, dict) or not output_pattern:
                raise ValueError("RECOVERY_INPUT_REQUIRED")
            worker = Path(addon_source).resolve().parents[2] / "tools" / "software_recovery_worker.py"
            operation = str(operation_id or ("recovery-" + str(task_id))).strip()
            safe_task = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in str(task_id))[:120]
            safe_operation = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in operation)[:120]
            root = state_dir / "owned-worker-recovery" / safe_task
            spec_payload = {**dict(spec), "output_pattern": str(output_pattern),
                            "frames": list(spec.get("frames") or [1, 2]),
                            "write_node": str(write_node or spec.get("write_node") or "Write1")}
            spec_path = root / (safe_operation + ".spec.json")
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")

            def run(attempt, phase):
                directory = root / (safe_operation + "-attempt-{}".format(attempt))
                event = directory / "worker-event.json"
                nonce = hashlib.sha256((str(task_id) + "\0" + operation + "\0" + str(attempt)).encode("utf-8")).hexdigest()[:24]
                identity = {"task_id": str(task_id), "operation_id": operation,
                            "launch_nonce": nonce, "phase": str(phase)}
                command = [sys.executable, str(worker), "--kind", "nuke", "--phase", phase,
                           "--task-id", str(task_id), "--operation-id", operation,
                           "--client-state-dir", str(state_dir), "--event", str(event),
                           "--spec", str(spec_path), "--script-path", str(script_path),
                           "--script-sha256", str(script_sha256)]
                handle = launch(command, directory=directory, identity=identity,
                                supervisor_executable=sys.executable, env=dict(os.environ), budget_seconds=30)
                started = dict(handle.started)
                del handle
                fresh = OwnedProcessHandle(directory, identity)
                exit_code = fresh.wait(15)
                stopped = fresh.receipt()
                if not isinstance(stopped, dict) or stopped.get("observed_by") != "owned_child_wait":
                    raise RuntimeError("RECOVERY_STOP_OBSERVATION_INVALID")
                event_payload = json.loads(event.read_text(encoding="utf-8")) if event.is_file() else {}
                return {"directory": str(directory), "command": command, "identity": identity,
                        "started": started, "stopped": stopped, "exit_code": exit_code,
                        "event": event_payload}

            crashed = run(1, "initial")
            if crashed["exit_code"] != 17 or crashed["event"].get("executed_frames") != spec_payload["frames"][:1]:
                raise RuntimeError("RECOVERY_CHECKPOINT_NOT_OBSERVED")
            resumed = run(2, "resume")
            if resumed["exit_code"] != 0 or resumed["event"].get("executed_frames") != spec_payload["frames"][1:]:
                raise RuntimeError("RECOVERY_RESUME_NOT_COMPLETED")
            from dcc_task_runtime.artifact_registry import frame_path
            outputs = [{"frame": int(frame), "path": str(frame_path(output_pattern, int(frame))),
                        "sha256": hashlib.sha256(frame_path(output_pattern, int(frame)).read_bytes()).hexdigest()}
                       for frame in spec_payload["frames"]]
            if any(not Path(item["path"]).is_file() for item in outputs):
                raise RuntimeError("RECOVERY_OUTPUT_NOT_WRITTEN")
            result = {"status": "COMPLETED", "operation_id": operation, "task_id": str(task_id),
                      "frames": spec_payload["frames"], "outputs": outputs,
                      "software_boundary_only": True}
            return {
                "tested": True, "software_boundary_only": True,
                "worker_crash": {"exit_code": crashed["exit_code"], "pid": crashed["started"].get("pid"),
                                 "operation_id": operation, "command": crashed["command"],
                                 "checkpoint": crashed["event"]},
                "supervisor": {"directory": crashed["directory"], "started": crashed["started"],
                                "stopped": crashed["stopped"], "stop_confirmed": True},
                "resume": {"directory": resumed["directory"], "started": resumed["started"],
                            "stopped": resumed["stopped"], "stop_confirmed": True,
                            "operation_id": operation, "command": resumed["command"],
                            "result": result, "output_artifact": {"pattern": output_pattern, "frames": outputs}},
                "controller_restart": {"fresh_handle_read": True, "same_operation_resumed": True},
                "domain_execution": result,
            }

    return _Client()


def _persist_boundary_binding(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a controller-owned host boundary binding atomically."""
    from dcc_task_runtime.platform_support import atomic_write
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
                 .encode("utf-8"), owned_root=path.parent)
    return payload


def _bind_strict_boundary(client, *, state_dir: Path, addon: Any, kind: str):
    """Attach durable task binding to the strict fake host/process boundary.

    Explicit software tests use this seam. The shipped add-on and operation/ledger
    contracts remain the code under test; the boundary records which task
    owns the fake session and rejects calls for another task.
    """
    binding_path = Path(state_dir) / ("production-" + str(kind) + "-binding.json")
    client.boundary_kind = "strict_fake_" + str(kind)
    client.real_host_bound = False
    client.real_nuke_bound = False
    client.real_process_bound = False
    client.bound_task_id = None
    client.boundary_binding_path = str(binding_path)
    client.boundary_binding = None
    original_call = client.call

    def bind_task(task_id):
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("production boundary task binding requires task_id")
        prior = None
        if binding_path.is_file():
            try:
                loaded = json.loads(binding_path.read_text(encoding="utf-8"))
                prior = loaded if isinstance(loaded, dict) else None
            except (OSError, ValueError):
                raise ValueError("production boundary binding is unreadable")
        if prior is not None and str(prior.get("task_id") or "") != task_id:
            raise ValueError("production boundary is already bound to another task")
        identity = {}
        identity_reader = getattr(addon, "graph_worker_identity", None)
        if callable(identity_reader):
            identity = dict(identity_reader())
        elif kind == "nuke":
            import nuke
            identity = {"script": str(nuke.root().name() or ""),
                        "version": str(getattr(nuke, "NUKE_VERSION_STRING", ""))}
        payload = {
            "schema": "bridge.production.boundary-binding/1.0",
            "kind": str(kind), "task_id": task_id,
            "boundary": str(getattr(client, "boundary_kind", "")),
            "identity": identity,
            "rebind_count": int((prior or {}).get("rebind_count") or 0) + 1,
        }
        client.boundary_binding = _persist_boundary_binding(binding_path, payload)
        client.bound_task_id = task_id
        return dict(payload)

    def call(command, params):
        params = dict(params or {})
        requested = str(params.get("task_id") or "").strip()
        if requested and client.bound_task_id != requested:
            raise ValueError("production boundary task binding does not match request")
        if requested and client.bound_task_id is None:
            raise ValueError("production boundary is not bound to a task")
        return original_call(command, params)

    client.bind_task = bind_task
    client.call = call
    return client


class ProductionBoundaryError(ValueError):
    """A production route is unavailable without an explicit host config."""

    def __init__(self, message: str):
        value = str(message)
        code = value.split(":", 1)[0]
        self.code = code if (code.startswith("PRODUCTION_") and len(code) <= 64
                             and all(char.isupper() or char.isdigit() or char == "_" for char in code)) else None
        super().__init__(value)


def _production_config(config: Any, *, kind: str) -> dict[str, Any]:
    """Validate controller-supplied production transport configuration.

    Production assembly never creates a fake HOM/Nuke object.  The config is
    a deployment input, not evidence that the host is currently reachable;
    reachability is established only after the configured client receives a
    successful health/call response.
    """
    if not isinstance(config, dict):
        raise ProductionBoundaryError(
            "PRODUCTION_{}_CONFIG_REQUIRED".format(str(kind).upper()),
        )
    application = str(config.get("application") or "").strip().lower()
    expected = "houdini" if kind == "houdini" else "nuke"
    if application != expected:
        raise ProductionBoundaryError("PRODUCTION_{}_APPLICATION_INVALID".format(str(kind).upper()))
    version = str(config.get("version") or "").strip()
    if version not in ({"21.0.631", "22.0.429", "22.0.459"} if kind == "houdini" else {"17.0v1"}):
        raise ProductionBoundaryError("PRODUCTION_{}_VERSION_REQUIRED".format(str(kind).upper()))
    plugin_build = str(config.get("plugin_build") or "").strip()
    if not plugin_build:
        raise ProductionBoundaryError("PRODUCTION_{}_PLUGIN_BUILD_REQUIRED".format(str(kind).upper()))
    task_root = Path(str(config.get("task_root") or "")).expanduser()
    if not task_root.is_absolute() or task_root.is_symlink():
        raise ProductionBoundaryError("PRODUCTION_{}_TASK_ROOT_INVALID".format(str(kind).upper()))
    executable = Path(str(config.get("executable") or "")).expanduser()
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        raise ProductionBoundaryError("PRODUCTION_{}_EXECUTABLE_INVALID".format(str(kind).upper()))
    try:
        port = int(config.get("port"))
    except (TypeError, ValueError) as exc:
        raise ProductionBoundaryError("PRODUCTION_{}_PORT_REQUIRED".format(str(kind).upper())) from exc
    if not 1 <= port <= 65535:
        raise ProductionBoundaryError("PRODUCTION_{}_PORT_INVALID".format(str(kind).upper()))
    transport = str(config.get("transport") or "").strip().lower()
    expected_transport = "http" if kind == "houdini" else "tcp"
    if transport != expected_transport:
        raise ProductionBoundaryError("PRODUCTION_{}_TRANSPORT_INVALID".format(str(kind).upper()))
    host = str(config.get("host") or "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ProductionBoundaryError("PRODUCTION_{}_HOST_INVALID".format(str(kind).upper()))
    identity = config.get("expected_identity")
    required_identity = {"task_id", "session_id", "launch_nonce", "pid", "process_generation", "plugin_build", "scene_epoch", "version"}
    if (not isinstance(identity, dict) or not required_identity.issubset(identity)
            or any(identity.get(key) in (None, "") for key in required_identity)
            or type(identity.get("pid")) is not int or identity["pid"] <= 0
            or type(identity.get("scene_epoch")) is not int or identity["scene_epoch"] < 0
            or identity.get("version") != version or identity.get("plugin_build") != plugin_build):
        raise ProductionBoundaryError("PRODUCTION_HOST_IDENTITY_REQUIRED")
    if config.get("evidence_source") not in {"real_host", "software_test"}:
        raise ProductionBoundaryError("PRODUCTION_EVIDENCE_SOURCE_REQUIRED")
    if config.get("evidence_source") == "real_host" and any(
            field in config for field in ("software_launch_script", "software_api_dir")):
        raise ProductionBoundaryError("SOFTWARE_API_IN_PRODUCTION")
    budget = config.get("resource_budget")
    if (not isinstance(budget, dict) or type(budget.get("max_bytes")) is not int
            or budget["max_bytes"] <= 0 or not isinstance(budget.get("roots"), list)
            or not budget["roots"]):
        raise ProductionBoundaryError("PRODUCTION_RESOURCE_BUDGET_REQUIRED")
    scope_binding = config.get('native_scope')
    if scope_binding is not None:
        from .production_hosts import native_scope_budget, native_scope_host_binding
        try:
            budget = native_scope_budget(scope_binding, budget, task_root)
            native_scope_host_binding(scope_binding, kind, version, executable, config.get('supervisor_executable'),
                project_color=config.get('project_color'), writer=config.get('writer_executable'),
                allow_missing_writer=config.get('evidence_source') == 'software_test')
            if kind == 'houdini':
                from houdini_bridge.controlled_output import validate_controlled_policy
                validate_controlled_policy(config.get('output_acceptance'))
        except ValueError as error:
            raise ProductionBoundaryError(str(error)) from error
    elif budget.get('native_scope') is not None:
        raise ProductionBoundaryError('PRODUCTION_NATIVE_SCOPE_BINDING_REQUIRED')
    for root in ([] if scope_binding is not None else budget["roots"]):
        if not isinstance(root, str) or not Path(root).is_absolute() or Path(root).is_symlink():
            raise ProductionBoundaryError("PRODUCTION_RESOURCE_ROOT_INVALID")
        try:
            Path(root).resolve().relative_to(task_root.resolve())
        except ValueError as exc:
            raise ProductionBoundaryError("PRODUCTION_RESOURCE_ROOT_OUTSIDE_TASK") from exc
    return {
        **config,
        "application": application,
        "version": version,
        "plugin_build": plugin_build,
        "task_root": str(task_root.resolve()),
        "executable": str(executable),
        "port": port,
        "transport": transport,
        "host": host,
        "resource_budget": budget,
    }


class _ConfiguredBoundary:
    """Task-bound adapter over the shipped Houdini/Nuke transport clients."""

    def __init__(self, *, kind: str, transport: Any, config: dict[str, Any], state_dir: Path):
        self._kind = str(kind)
        self._transport = transport
        self.production_config = dict(config)
        self.backend_kind = "production"
        self.boundary_kind = "configured_{}_{}".format(self._kind, config["transport"])
        self.real_host_bound = None
        self.real_nuke_bound = None
        self.real_process_bound = None
        self.bound_task_id = None
        self.boundary_binding_path = str(Path(state_dir) / ("configured-{}-binding.json".format(self._kind)))
        self.boundary_binding = None
        self.expected_identity = dict(config.get("expected_identity") or {})
        controller_root = config.get("controller_root") or Path(state_dir).resolve().parent
        self.scene_transition_path = Path(controller_root).resolve() / "scene-transitions.json"
        self._graph_handoffs = {}

    def _store_operation_owner(self, operation_id, binding):
        from dcc_task_runtime.execution_lock import execution_lock
        with execution_lock(Path(self.boundary_binding_path).parent, self.bound_task_id):
            owners = self._load_operation_owners()
            prior = owners.get(operation_id)
            if prior is not None and prior != binding:
                raise ProductionBoundaryError('PRODUCTION_OPERATION_OWNER_MISMATCH')
            owners[operation_id] = binding
            _persist_boundary_binding(self._operation_owners_path(), owners)

    def _controlled_output_fact(self, owner, verification_id):
        from houdini_bridge.controlled_output import verify_controlled_output
        parent_id = owner['parent_operation_id']
        parent = self._load_operation_owners().get(parent_id)
        if (not isinstance(parent, dict) or parent.get('task_id') != self.bound_task_id
                or parent.get('producer_binding') != owner.get('producer_binding')):
            raise ProductionBoundaryError('CONTROLLED_OUTPUT_PARENT_BINDING_CHANGED')
        fact = verify_controlled_output(parent, task_id=self.bound_task_id,
            operation_id=parent_id, verification_id=verification_id,
            policy=owner['policy'], alpha_calibration=owner['alpha_calibration'],
            evidence_source=owner['evidence_source'],historical_scope=owner.get('historical_scope'),
            render_terminal_recovery=owner.get('render_terminal_recovery'))
        return fact

    def _verify_controlled_output(self, params, *, query=False):
        from houdini_bridge.controlled_output import validate_controlled_policy
        verification_id = str(params.get('verification_id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', verification_id):
            raise ProductionBoundaryError('CONTROLLED_OUTPUT_VERIFICATION_ID_INVALID')
        from dcc_task_runtime.execution_lock import execution_lock
        with execution_lock(Path(self.boundary_binding_path).parent, self.bound_task_id):
            owners = self._load_operation_owners()
            owner = owners.get(verification_id)
            if owner is None:
                if query:
                    raise ProductionBoundaryError('PRODUCTION_OPERATION_OWNER_MISMATCH')
                policy = validate_controlled_policy(self.production_config.get('output_acceptance'))
                calibration = self.production_config.get('alpha_calibration')
                if not isinstance(calibration, dict):
                    raise ProductionBoundaryError('CONTROLLED_OUTPUT_ALPHA_CALIBRATION_REQUIRED')
                parent_id = str(params.get('operation_id') or '')
                parent = owners.get(parent_id)
                if (not isinstance(parent, dict) or parent.get('task_id') != self.bound_task_id
                        or not isinstance(parent.get('producer_binding'), dict)):
                    raise ProductionBoundaryError('CONTROLLED_OUTPUT_PARENT_BINDING_REQUIRED')
                if parent['producer_binding'].get('output_acceptance') != policy:
                    raise ProductionBoundaryError('CONTROLLED_OUTPUT_POLICY_MISMATCH')
                owner = {'task_id': self.bound_task_id, 'operation_kind': 'output-verification',
                    'parent_operation_id': parent_id, 'producer_binding': parent['producer_binding'],
                    'policy': policy, 'alpha_calibration': calibration,
                    'evidence_source': self.production_config.get('evidence_source')}
                owner = json.loads(json.dumps(owner, allow_nan=False))
                owners[verification_id] = owner
                _persist_boundary_binding(self._operation_owners_path(), owners)
            if (not isinstance(owner, dict) or owner.get('operation_kind') != 'output-verification'
                    or owner.get('task_id') != self.bound_task_id
                    or (not query and owner['parent_operation_id'] != params.get('operation_id'))):
                raise ProductionBoundaryError('PRODUCTION_OPERATION_OWNER_MISMATCH')
            fact = self._controlled_output_fact(owner, verification_id)
            result_path = Path(self.boundary_binding_path).with_name('verified-output-' + verification_id + '.json')
            if result_path.exists():
                if result_path.is_symlink() or json.loads(result_path.read_text(encoding='utf-8')) != fact:
                    raise ProductionBoundaryError('CONTROLLED_OUTPUT_VERIFICATION_CHANGED')
            else:
                _persist_boundary_binding(result_path, fact)
            return {'operation_id': verification_id, 'execution_fact': fact,
                    'operation': {'state': 'COMPLETED', 'kind': 'output-verification'},
                    'verification_basis': 'controlled_output_v1'}

    def _scene_transition_records(self):
        if not self.scene_transition_path.is_file():
            return []
        try:
            payload = json.loads(self.scene_transition_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_STORE_INVALID") from exc
        if (not isinstance(payload, dict)
                or payload.get("schema") != "bridge.production.scene-transitions/1.0"
                or not isinstance(payload.get("records"), list)):
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_STORE_INVALID")
        return list(payload["records"])

    def _persist_scene_transition(self, record):
        payload = {
            "schema": "bridge.production.scene-transitions/1.0",
            "task_id": str(self.bound_task_id or ""),
            "records": self._scene_transition_records() + [record],
        }
        _persist_boundary_binding(self.scene_transition_path, payload)

    def _scene_transition_snapshot(self, record):
        request = dict(record.get("request") or {})
        source = Path(str(request.get("path") or "")).expanduser().resolve()
        digest = str(request.get("sha256") or "").lower()
        task_root = Path(self.production_config["task_root"]).resolve()
        if (source.is_symlink() or not source.is_file()
                or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_BINDING_INVALID")
        if not source.is_relative_to(task_root):
            # 外部HIP仅接受当前shape授权中精确绑定的只读源，不扩展任务写入根。
            from .production_hosts import _rect_shape_readonly_source
            controller_root = Path(self.production_config.get("controller_root")
                                   or self.scene_transition_path.parent).resolve()
            if not _rect_shape_readonly_source(controller_root, record, source, digest, task_root):
                raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_BINDING_INVALID")
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_SOURCE_CHANGED")
        safe_task = "".join(char if char.isalnum() or char in ".-_" else "_"
                             for char in str(record.get("task_id") or ""))[:120] or "unbound"
        directory = self.scene_transition_path.parent / "scene-transition-snapshots" / safe_task
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / (digest + ".hip")
        if snapshot.is_symlink():
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_SNAPSHOT_INVALID")
        if snapshot.is_file():
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
                raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_SNAPSHOT_INVALID")
        else:
            temporary = snapshot.with_name("." + snapshot.name + ".tmp")
            temporary.write_bytes(source.read_bytes())
            temporary.chmod(0o400)
            temporary.replace(snapshot)
        return {"path": str(source), "sha256": digest,
                "snapshot_path": str(snapshot), "snapshot_sha256": digest}

    def _start_scene_transition(self, command, params, before):
        path = str(params.get("path") or "").strip()
        digest = str(params.get("sha256") or "").strip().lower()
        if not path or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_BINDING_INVALID")
        request = {"path": str(Path(path).expanduser().resolve()), "sha256": digest}
        request_id = str(params.get("request_id") or "").strip()
        operation_id = str(params.get("operation_id") or "").strip()
        if not operation_id:
            operation_id = "scene-" + hashlib.sha256(json.dumps(
                {"task_id": str(self.bound_task_id or ""), "command": str(command),
                 "request": request, "before_identity": {key: before.get(key) for key in
                     ("task_id", "session_id", "launch_nonce", "pid", "process_generation", "plugin_build", "scene_epoch")}},
                ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:48]
        if not request_id:
            request_id = operation_id
        if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", operation_id)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", request_id)):
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_BINDING_INVALID")
        request_sha256 = hashlib.sha256(json.dumps(
            {"task_id": str(self.bound_task_id or ""), "command": str(command),
             "request": request, "request_id": request_id},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        record = {
            "schema": "bridge.production.scene-transition/1.0",
            "status": "INTENT",
            "kind": "houdini",
            "task_id": str(self.bound_task_id or ""),
            "operation_id": operation_id,
            "request_id": request_id,
            "request_sha256": request_sha256,
            "command": str(command),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "before_scene_epoch": before.get("scene_epoch"),
            "before_identity": dict(before),
            "request": request,
        }
        self._persist_scene_transition(record)
        return record

    def _complete_scene_transition(self, record, result, after):
        expected_path = str(record["request"]["path"])
        expected_sha = str(record["request"]["sha256"])
        if (not isinstance(result, dict) or str(result.get("path") or "") != expected_path
                or str(result.get("sha256") or "").lower() != expected_sha):
            record.update({"status": "FAILED", "error": "scene result did not match the persisted HIP intent"})
            self._persist_scene_transition(record)
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_RESULT_MISMATCH")
        formal = result.get("scene_transition")
        if (not isinstance(formal, dict) or formal.get("state") != "COMPLETED"
                or formal.get("operation_id") != record.get("operation_id")
                or formal.get("request_id") != record.get("request_id")
                or formal.get("request_sha256") != record.get("request_sha256")):
            record.update({"status": "FAILED", "error": "formal scene operation receipt is missing or mismatched"})
            self._persist_scene_transition(record)
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_OPERATION_UNVERIFIED")
        snapshot = self._scene_transition_snapshot(record)
        before_epoch = record.get("before_scene_epoch")
        after_epoch = after.get("scene_epoch") if isinstance(after, dict) else None
        if (type(before_epoch) is not int or type(after_epoch) is not int
                or after_epoch <= before_epoch):
            record.update({"status": "FAILED", "error": "scene epoch did not advance for the requested load"})
            self._persist_scene_transition(record)
            raise ProductionBoundaryError("PRODUCTION_SCENE_TRANSITION_EPOCH_INVALID")
        record.update({
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "after_scene_epoch": after_epoch,
            "after_identity": dict(after),
            "result": snapshot,
            "operation_store_cas": formal.get("store_cas"),
            "operation_receipt_sha256": formal.get("operation_receipt_sha256"),
            "formal_operation": dict(formal),
        })
        self._persist_scene_transition(record)
        # The live host epoch is trusted only after the controller's completed
        # transition fact is durable.  A successful load followed by a source,
        # snapshot, or persistence failure must leave the old expected epoch in
        # memory so the next call is forced through durable reconciliation.
        self.expected_identity["scene_epoch"] = after_epoch
        return record

    def _verify_identity(self, *, allow_new_epoch=False, commit_epoch=True):
        if not self.expected_identity:
            raise ProductionBoundaryError("PRODUCTION_HOST_IDENTITY_REQUIRED")
        result = self._transport.health()
        actual = result.get("task_host_identity") if isinstance(result, dict) else None
        if not isinstance(actual, dict):
            raise ProductionBoundaryError("PRODUCTION_HOST_IDENTITY_MISSING")
        epoch_advance = None
        for key, value in self.expected_identity.items():
            if key == "scene_epoch":
                if type(actual.get(key)) is not int or actual[key] < value:
                    raise ProductionBoundaryError("PRODUCTION_SCENE_EPOCH_INVALID")
                if actual[key] > value:
                    if not allow_new_epoch:
                        from .production_hosts import _scene_epoch_transition_is_authorized
                        control_root = Path(self.scene_transition_path).resolve().parent
                        authorized = _scene_epoch_transition_is_authorized(
                            control_root,
                            task_id=str(self.bound_task_id or ""),
                            from_epoch=value,
                            to_epoch=actual[key],
                            task_root=Path(self.production_config["task_root"]).resolve(),
                            expected_identity=self.expected_identity,
                            actual_identity=actual,
                        )
                        if not authorized:
                            raise ProductionBoundaryError("PRODUCTION_HOST_IDENTITY_MISMATCH:scene_epoch")
                    epoch_advance = actual[key]
            elif actual.get(key) != value:
                raise ProductionBoundaryError("PRODUCTION_HOST_IDENTITY_MISMATCH:" + key)
        if actual.get("task_id") != self.bound_task_id:
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_TASK_CONFLICT")
        if epoch_advance is not None and commit_epoch:
            self.expected_identity["scene_epoch"] = epoch_advance
        self.transport_reachable = True
        verified_real = self.production_config.get("evidence_source") == "real_host"
        self.real_process_bound = verified_real
        self.real_host_bound = verified_real if self._kind == "houdini" else self.real_host_bound
        self.real_nuke_bound = verified_real if self._kind == "nuke" else self.real_nuke_bound
        return result

    def _task_binding_payload(self, task_id: str) -> dict[str, Any]:
        """共用任务归属检查；读取原绑定事实但不改变磁盘状态。"""
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ProductionBoundaryError("PRODUCTION_TASK_BINDING_REQUIRED")
        if self.bound_task_id is not None and self.bound_task_id != task_id:
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_TASK_CONFLICT")
        path = Path(self.boundary_binding_path)
        prior = None
        if path.is_file():
            try:
                prior = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ProductionBoundaryError("PRODUCTION_BOUNDARY_BINDING_UNREADABLE") from exc
            if isinstance(prior, dict) and str(prior.get("task_id") or "") not in {"", task_id}:
                raise ProductionBoundaryError("PRODUCTION_BOUNDARY_TASK_CONFLICT")
        payload = {
            "schema": "bridge.production.configured-boundary-binding/1.0",
            "kind": self._kind,
            "task_id": task_id,
            "boundary": self.boundary_kind,
            "config": {
                "application": self.production_config["application"],
                "version": self.production_config["version"],
                "plugin_build": self.production_config["plugin_build"],
                "transport": self.production_config["transport"],
                "host": self.production_config["host"],
                "port": self.production_config["port"],
                "task_root": self.production_config["task_root"],
                "executable": self.production_config["executable"],
            },
            "rebind_count": int((prior or {}).get("rebind_count") or 0) + 1,
        }
        return payload

    def bind_task(self, task_id: str) -> dict[str, Any]:
        """绑定执行任务并保留原有持久化及重绑计数行为。"""
        payload = self._task_binding_payload(task_id)
        self.boundary_binding = _persist_boundary_binding(Path(self.boundary_binding_path), payload)
        self.bound_task_id = payload["task_id"]
        return dict(payload)

    def observe_task(self, task_id: str) -> dict[str, Any]:
        """历史输入核验只在内存绑定；完整读取同一归属事实而不重写诊断索引。"""
        payload = self._task_binding_payload(task_id)
        self.boundary_binding = payload
        self.bound_task_id = payload["task_id"]
        return dict(payload)

    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.bound_task_id is None:
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_NOT_BOUND")
        params = dict(params or {})
        if "native_scope" in params or "resource_budget" in params:
            raise ProductionBoundaryError("PRODUCTION_CALLER_BUDGET_FORBIDDEN")
        if self._kind == 'houdini' and command in {'output.verify', 'output.verify.status'}:
            if set(params) - {'task_id', 'operation_id', 'verification_id'}:
                raise ProductionBoundaryError('CONTROLLED_OUTPUT_CALLER_FACTS_FORBIDDEN')
            if params.get('task_id') not in (None, self.bound_task_id):
                raise ProductionBoundaryError('PRODUCTION_BOUNDARY_TASK_CONFLICT')
            return self._verify_controlled_output(params, query=command == 'output.verify.status')
        if self._kind == "houdini" and command == "render.start":
            from dcc_task_runtime.project_color import validate_project_color
            try:
                selection = validate_project_color(self.production_config.get("project_color"))
            except ValueError as error:
                raise ProductionBoundaryError(str(error)) from error
            if "project_color" in params and params["project_color"] != selection:
                raise ProductionBoundaryError("PROJECT_COLOR_SELECTION_MISMATCH")
            params["project_color"] = selection
            configured_policy = self.production_config.get('output_acceptance')
            if 'output_acceptance' in params and params['output_acceptance'] != configured_policy:
                raise ProductionBoundaryError('CONTROLLED_OUTPUT_CALLER_POLICY_FORBIDDEN')
            if configured_policy is not None:
                from houdini_bridge.controlled_output import validate_controlled_policy
                params['output_acceptance'] = validate_controlled_policy(configured_policy)
        # Nuke render query/cancel/recovery uses task_id for an operation, not the
        # pipeline owner. Resolve it from our durable launch records.
        operation_commands = {"render_status", "render_cancel", "render.status", "render.cancel", "control.render_resolve"}
        if self._kind == "nuke" and command in operation_commands:
            operation_id = str(params.get("task_id") or "")
            operations = self._load_operation_owners()
            if operations.get(operation_id) != self.bound_task_id:
                raise ProductionBoundaryError("PRODUCTION_OPERATION_OWNER_MISMATCH")
        elif params.get("task_id") not in (None, "", self.bound_task_id):
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_TASK_CONFLICT")
        if self._kind == "houdini" and command in {"render.status", "render.cancel", "render.verify"}:
            operation_id = str(params.get("operation_id") or "")
            binding = self._load_operation_owners().get(operation_id)
            if not isinstance(binding, dict) or binding.get("task_id") != self.bound_task_id:
                raise ProductionBoundaryError("PRODUCTION_OPERATION_OWNER_MISMATCH")
            from houdini_bridge.client import read_render_operation
            return read_render_operation(binding, task_id=self.bound_task_id, operation_id=operation_id,
                                         cancel=command == "render.cancel")
        before_health = self._verify_identity()
        before_identity = before_health.get("task_host_identity") if isinstance(before_health, dict) else None
        transition = None
        scene_commands = {"scene.open_hip", "scene.reopen_task_hip", "scene.reopen_owned_hip"}
        if self._kind == "houdini" and command in scene_commands:
            if not isinstance(before_identity, dict):
                raise ProductionBoundaryError("PRODUCTION_HOST_IDENTITY_MISSING")
            transition = self._start_scene_transition(command, params, before_identity)
            params.update({"task_id": self.bound_task_id,
                           "operation_id": transition["operation_id"],
                           "request_id": transition["request_id"],
                           "scene_before_identity": dict(before_identity)})
        if self.production_config.get('lifecycle') == 'task_owned' and (
                self._kind == 'houdini' and command == 'render.start'
                or self._kind == 'nuke' and command in {'render_write', 'render.start'}):
            from .production_hosts import host_phase_budget
            params['budget_seconds'] = host_phase_budget(self.production_config,
                requested_seconds=params.get('budget_seconds', 120.0))
        try:
            result = self._transport.call(command, params)
            after_health = None
            if transition is not None:
                after_health = self._verify_identity(
                    allow_new_epoch=True, commit_epoch=False)
            elif command == "open_script":
                after_health = self._verify_identity(allow_new_epoch=True)
            if transition is not None:
                after_identity = after_health.get("task_host_identity") if isinstance(after_health, dict) else None
                self._complete_scene_transition(transition, result, after_identity)
        except Exception as exc:
            if transition is not None and transition.get("status") == "INTENT":
                transition.update({"status": "FAILED", "error": str(exc),
                                   "failed_at": datetime.now(timezone.utc).isoformat()})
                try:
                    self._persist_scene_transition(transition)
                except Exception:
                    pass
            raise
        if not isinstance(result, dict):
            raise ProductionBoundaryError("PRODUCTION_RESPONSE_INVALID")
        self.transport_reachable = True
        if self._kind == "houdini" and command == "render.start":
            from houdini_bridge.client import render_producer_binding

            operation_id = str(result.get("operation_id") or "")
            record = result.get("record") or {}
            if record.get("project_color") != params["project_color"]:
                raise ProductionBoundaryError("PROJECT_COLOR_SELECTION_MISMATCH")
            if (not operation_id or record.get("task_id") != self.bound_task_id
                    or record.get("host_identity") != before_identity):
                raise ProductionBoundaryError("PRODUCTION_OPERATION_OWNER_MISMATCH")
            if record.get('output_acceptance') != params.get('output_acceptance'):
                raise ProductionBoundaryError('CONTROLLED_OUTPUT_POLICY_MISMATCH')
            binding = {"task_id": self.bound_task_id, "operation_store_path": result.get("operation_store_path"),
                       "request_sha256": record.get("request_sha256"), "host_identity": record.get("host_identity"),
                       "supervisor_binding": record.get("supervisor_binding"),
                       "producer_binding": render_producer_binding(record)}
            self._store_operation_owner(operation_id, binding)
        if self._kind == "nuke" and command in {"render_write", "render.start"}:
            operation_id = str(result.get("operation_id") or result.get("task_id") or "")
            if not operation_id:
                raise ProductionBoundaryError("PRODUCTION_OPERATION_ID_MISSING")
            owners = self._load_operation_owners()
            if operation_id in owners and owners[operation_id] != self.bound_task_id:
                raise ProductionBoundaryError("PRODUCTION_OPERATION_OWNER_MISMATCH")
            owners[operation_id] = self.bound_task_id
            _persist_boundary_binding(self._operation_owners_path(), owners)
        return result

    def mark_graph_trial_complete(self, task_id: str, receipt: dict[str, Any], *, verified_jobs_root=None) -> dict[str, Any]:
        """Adopt the controller-verified worker HIP into the task-owned host.

        Graph construction runs in its own bounded Houdini worker.  This
        controller-only handoff opens only that operation's sealed HIP, then
        asks the host add-on to derive its task lease and manifest from the
        live topology.  The model-facing MCP surface never accepts a path or
        completion receipt for this transition.
        """
        task_id = str(task_id or "").strip()
        if self._kind != "houdini" or task_id != self.bound_task_id or not isinstance(receipt, dict):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_HANDOFF_INVALID")
        if receipt.get("state") != "SUCCEEDED" or receipt.get("stop_confirmed") is not True:
            raise ProductionBoundaryError("PRODUCTION_GRAPH_RESULT_NOT_TERMINAL")
        result = receipt.get("result")
        if (not isinstance(result, dict) or result.get("construction_executed") is not True
                or result.get("reconciliation_required") is not False):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_RESULT_INVALID")
        verification = result.get("verification")
        if (not isinstance(verification, dict)
                or any(verification.get(key) is not True for key in
                       ("nodes_verified", "parameters_verified", "connections_verified"))):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_VERIFICATION_MISSING")
        operation_id = str(receipt.get("operation_id") or "")
        artifact = result.get("artifact")
        if not operation_id or not isinstance(artifact, dict):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_ARTIFACT_MISSING")
        relative = Path(str(artifact.get("path") or ""))
        parts = relative.parts
        if (relative.is_absolute() or len(parts) != 4 or parts[:2] != ("graph-jobs", operation_id)
                or not parts[2].startswith("attempt-") or not parts[2][8:].isdigit()
                or parts[3] != operation_id + ".hip" or ".." in parts):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_ARTIFACT_PATH_INVALID")
        control_root = Path(self.boundary_binding_path).resolve().parent.parent
        jobs_root = control_root / "jobs"
        # 同任务续接只能使用控制端预先认证的唯一旧操作，模型工具不能指定来源目录。
        bound_source = getattr(self, '_verified_graph_source', None)
        configured_root = getattr(self, 'verified_jobs_root', None)
        if verified_jobs_root is not None or configured_root is not None:
            selected = Path(verified_jobs_root if verified_jobs_root is not None else configured_root)
            if (not isinstance(bound_source, dict) or str(selected) != bound_source.get('jobs_root')
                    or str(configured_root) != str(selected)
                    or bound_source.get('task_id') != task_id
                    or bound_source.get('operation_id') != operation_id
                    or bound_source.get('receipt_sha256') != hashlib.sha256(json.dumps(
                        receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                        allow_nan=False).encode('utf-8')).hexdigest()):
                raise ProductionBoundaryError('PRODUCTION_GRAPH_RESUME_SOURCE_MISMATCH')
            jobs_root = selected
        artifact_path = jobs_root / relative
        checked = (jobs_root, jobs_root / "graph-jobs", jobs_root / "graph-jobs" / operation_id, artifact_path)
        if any(path.is_symlink() for path in checked):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_ARTIFACT_SYMLINK")
        if (not artifact_path.is_file() or not artifact_path.resolve().is_relative_to(jobs_root.resolve())
                or artifact_path.name != operation_id + ".hip"):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_ARTIFACT_UNAVAILABLE")
        digest = str(artifact.get("sha256") or "")
        if (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
                or hashlib.sha256(artifact_path.read_bytes()).hexdigest() != digest):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_ARTIFACT_HASH_MISMATCH")
        receipt_hash = hashlib.sha256(json.dumps({key: result.get(key) for key in
            ('graph_hash', 'artifact', 'verification', 'topology')}, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        identity = self._verify_identity()['task_host_identity']
        previous = self._graph_handoffs.get(operation_id)
        if previous is not None:
            if previous['receipt_hash'] != receipt_hash or previous['identity'] != identity:
                raise ProductionBoundaryError('PRODUCTION_GRAPH_HANDOFF_CHANGED')
            return json.loads(json.dumps(previous['result'], allow_nan=False))
        contract_digest = verification.get('registered_scene_contract_sha256')
        if contract_digest is not None:
            if (type(contract_digest) is not str or len(contract_digest) != 64
                    or any(char not in '0123456789abcdef' for char in contract_digest)):
                raise ProductionBoundaryError('PRODUCTION_GRAPH_SAVE_CONTRACT_INVALID')
            opened = self.call('scene.reopen_task_hip', dict(task_id=task_id, path=str(artifact_path), sha256=digest,
                operation_id=operation_id + '-handoff', request_id=operation_id + '-handoff',
                scene_before_identity=identity, scene_contract_sha256=contract_digest))
        else:
            opened = self.call("scene.open_hip", {"path": str(artifact_path), "sha256": digest})
        binding = self.call("agent.fx.bind_graph_trial", {"task_id": task_id, "trial_receipt": receipt})
        if (binding.get("graph_ready") is not True or binding.get("nodes_verified") is not True
                or binding.get("connections_verified") is not True):
            raise ProductionBoundaryError("PRODUCTION_GRAPH_HOST_BINDING_UNVERIFIED")
        handoff = {"operation_id": operation_id, "artifact_sha256": digest,
                "scene_open_verified": opened.get("sha256") == digest,
                "graph_binding": binding}
        self._graph_handoffs[operation_id] = dict(receipt_hash=receipt_hash,
            identity=json.loads(json.dumps(self._verify_identity()['task_host_identity'], allow_nan=False)),
            result=json.loads(json.dumps(handoff, allow_nan=False)))
        return handoff

    def bind_artifact_registry(self, registry):
        self._registry = registry
        prior = registry._operation_source
        def operation_source(operation_id):
            owner = self._load_operation_owners().get(operation_id)
            if self._kind == "houdini" and isinstance(owner, dict) and owner.get("task_id") == self.bound_task_id:
                if owner.get('operation_kind') == 'output-verification':
                    return self.call('output.verify.status', {'verification_id': operation_id}).get('execution_fact')
                return self.call("render.verify", {"task_id": self.bound_task_id, "operation_id": operation_id}).get("execution_fact")
            if self._kind == "nuke" and owner == self.bound_task_id:
                fact = self.call("render_fact", {"operation_id": operation_id})
                if fact.get("task_id") != self.bound_task_id:
                    raise ProductionBoundaryError("PRODUCTION_OPERATION_OWNER_MISMATCH")
                return fact
            return prior(operation_id) if prior is not None else None
        registry.set_operation_source(operation_source)

    def _operation_owners_path(self):
        return Path(self.boundary_binding_path).with_name(self._kind + "-operation-owners.json")

    def _load_operation_owners(self):
        path = self._operation_owners_path()
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ProductionBoundaryError("PRODUCTION_OPERATION_STORE_INVALID")
        return value

    def health(self) -> dict[str, Any]:
        if self.bound_task_id is None:
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_NOT_BOUND")
        return self._verify_identity()

    def render_binding(self, task_id: str, output_pattern: str, frames: list[int],
                       colorspace: str, premultiplied: bool, *, artifact_binding: dict[str, Any]):
        if self._kind != "nuke":
            raise ProductionBoundaryError("PRODUCTION_NUKE_BOUNDARY_REQUIRED")
        if task_id != self.bound_task_id:
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_TASK_CONFLICT")
        artifact_id = str(artifact_binding.get("artifact_id") or "")
        read_path = str(artifact_binding.get("pattern") or "")
        available = (artifact_binding.get("verification") or {}).get("frame_set", [])
        if (artifact_binding.get("usable_as_render_input") is not True
                or not artifact_id or not read_path or not frames
                or len(frames) > MAX_FRAMES_PER_OPERATION
                or any(type(frame) is not int for frame in frames)
                or len(set(frames)) != len(frames) or not set(frames).issubset(set(available))):
            raise ProductionBoundaryError("PRODUCTION_INPUT_ARTIFACT_INVALID")
        if type(premultiplied) is not bool or not isinstance(colorspace, str) or not colorspace:
            raise ProductionBoundaryError("PRODUCTION_INPUT_METADATA_INVALID")
        try:
            Path(output_pattern).resolve().relative_to(Path(self.production_config["task_root"]).resolve())
        except ValueError as exc:
            raise ProductionBoundaryError("PRODUCTION_OUTPUT_OUTSIDE_TASK") from exc
        read_name = str(self.production_config.get("read_node") or "Read1")
        write_name = str(self.production_config.get("write_node") or "Write1")
        before = [self.call("get_node", {"name": name}) for name in (read_name, write_name)]
        if [node.get("class") for node in before] != ["Read", "Write"]:
            raise ProductionBoundaryError("PRODUCTION_NUKE_READ_WRITE_NODES_INVALID")
        input_color = artifact_binding.get("colorspace")
        input_premult = artifact_binding.get("premultiplied")
        if input_color is None or type(input_premult) is not bool:
            raise ProductionBoundaryError("PRODUCTION_INPUT_METADATA_MISSING")
        if input_color != colorspace or input_premult != premultiplied:
            raise ProductionBoundaryError("PRODUCTION_COLOR_CONVERSION_REQUIRED")
        targets = ((read_name, {"file": read_path, "colorspace": colorspace, "raw": False}),
                   (write_name, {"file": str(output_pattern), "colorspace": colorspace,
                                 "raw": False, "premultiplied": premultiplied}))
        snapshots = {}
        for observed, (name, values) in zip(before, targets):
            knobs = observed.get("knobs")
            if (not isinstance(knobs, dict)
                    or any(key not in knobs or type(knobs[key]) is not type(value)
                           for key, value in values.items())):
                raise ProductionBoundaryError("PRODUCTION_NUKE_NATIVE_COLOR_KNOBS_REQUIRED")
            snapshots[name] = {key: knobs[key] for key in values}
        original_inputs = before[1].get("inputs")
        if (not isinstance(original_inputs, list)
                or original_inputs and original_inputs[0] is not None
                and (not isinstance(original_inputs[0], str) or not original_inputs[0])):
            raise ProductionBoundaryError("PRODUCTION_NUKE_BINDING_READBACK_FAILED")
        original_source = original_inputs[0] if original_inputs else None

        def matches(observed, values):
            knobs = observed.get("knobs", {})
            return all(type(knobs.get(key)) is type(value) and knobs[key] == value
                       for key, value in values.items())

        try:
            # 同一登记输入的重复请求只读核验；原值不重复写入，避免耗尽宿主会话。
            changed = False
            for name, values in targets:
                for knob, value in values.items():
                    if snapshots[name][knob] != value:
                        self.call("set_knob", {"node": name, "knob": knob, "value": value})
                        changed = True
            observed = ([self.call("get_node", {"name": name}) for name, _ in targets]
                        if changed else before)
            if ([node.get("class") for node in observed] != ["Read", "Write"]
                    or any(not matches(node, values) for node, (_, values) in zip(observed, targets))):
                raise ProductionBoundaryError("PRODUCTION_NUKE_BINDING_READBACK_FAILED")
            if original_source != read_name:
                self.call("connect_nodes", {"src": read_name, "dst": write_name, "input_index": 0})
                observed = [self.call("get_node", {"name": name}) for name, _ in targets]
            inputs = observed[1].get("inputs")
            if ([node.get("class") for node in observed] != ["Read", "Write"]
                    or any(not matches(node, values) for node, (_, values) in zip(observed, targets))
                    or not isinstance(inputs, list) or not inputs or inputs[0] != read_name):
                raise ProductionBoundaryError("PRODUCTION_NUKE_BINDING_READBACK_FAILED")
        except Exception as error:
            restored = True
            for name, _ in reversed(targets):
                for knob, value in reversed(tuple(snapshots[name].items())):
                    try:
                        self.call("set_knob", {"node": name, "knob": knob, "value": value})
                    except Exception:
                        restored = False
            try:
                try:
                    current = self.call("get_node", {"name": write_name}).get("inputs")
                except Exception:
                    current = None
                if (not isinstance(current, list)
                        or (current[0] if current else None) != original_source):
                    self.call("connect_nodes", {"src": original_source, "dst": write_name, "input_index": 0})
                observed = [self.call("get_node", {"name": name}) for name, _ in targets]
                inputs = observed[1].get("inputs")
                if ([node.get("class") for node in observed] != ["Read", "Write"]
                        or any(not matches(node, snapshots[name]) for node, (name, _) in zip(observed, targets))
                        or not isinstance(inputs, list)
                        or (inputs[0] if inputs else None) != original_source):
                    restored = False
            except Exception:
                restored = False
            if not restored:
                raise ProductionBoundaryError("PRODUCTION_NUKE_BINDING_ROLLBACK_UNCONFIRMED") from error
            raise
        return {
            "source": "controller", "task_id": task_id, "node": write_name,
            "pattern": str(output_pattern), "frames": list(frames),
            "input_binding": {
                "kind": "artifact_read", "owner_task_id": task_id, "artifact_id": artifact_id,
                "read_node": read_name, "read_path": read_path, "frame_set": list(frames),
                "connection": {"source": read_name, "destination": write_name,
                               "input_index": 0, "connected": True},
                "connection_verified": True,
            },
            **({"project_color": json.loads(json.dumps(artifact_binding["project_color"]))}
               if artifact_binding.get("project_color") is not None else {}),
            "colorspace": colorspace, "premultiplied": premultiplied, "background": True,
        }


def production_host_client(config: dict[str, Any], state_dir: Path):
    """Bind production to a configured Houdini HTTP task-host client."""
    config = _production_config(config, kind="houdini")
    from houdini_bridge.client import HoudiniClient
    transport = HoudiniClient(
        config["port"], host=config["host"],
        timeout_seconds=float(config.get("timeout_seconds") or 60.0),
        token=config.get("token"),
    )
    return _ConfiguredBoundary(kind="houdini", transport=transport,
                               config=config, state_dir=Path(state_dir))


def production_nuke_client(config: dict[str, Any], state_dir: Path):
    """Bind production to a configured Nuke loopback TCP client."""
    config = _production_config(config, kind="nuke")
    from nuke_bridge.client import NukeClient
    transport = NukeClient(
        config["port"], host=config["host"],
        timeout_seconds=float(config.get("timeout_seconds") or 30.0),
        token=config.get("token"),
    )
    return _ConfiguredBoundary(kind="nuke", transport=transport,
                               config=config, state_dir=Path(state_dir))



class _DeferredTaskBoundary:
    """Start a task host only when a host operation needs its live session."""

    backend_kind = "production"

    def __init__(self, kind, factory, detached_factory=None):
        self._kind, self._factory = kind, factory
        self._detached_factory = detached_factory
        self._boundary = None
        self._task_id = self._registry = None
        self._lock = __import__('threading').RLock()
        self.boundary_kind = "configured_{}_{}".format(kind, "http" if kind == "houdini" else "tcp")

    @property
    def real_host_bound(self):
        return self._boundary.real_host_bound if self._boundary is not None else None

    @property
    def real_nuke_bound(self):
        return self._boundary.real_nuke_bound if self._boundary is not None else None

    @property
    def real_process_bound(self):
        return self._boundary.real_process_bound if self._boundary is not None else None

    def prepare_task(self, task_id):
        self.bind_task(task_id)

    def bind_task(self, task_id):
        if self._task_id is not None and self._task_id != task_id:
            raise ProductionBoundaryError("PRODUCTION_BOUNDARY_TASK_CONFLICT")
        self._task_id = task_id
        if self._boundary is not None:
            return self._boundary.bind_task(task_id)

    def bind_artifact_registry(self, registry):
        self._registry = registry
        prior = registry._operation_source
        def operation_source(operation_id):
            if self._detached_factory is not None:
                boundary = self._detached_factory()
                if boundary is not None and operation_id in boundary._load_operation_owners():
                    boundary.bind_task(self._task_id)
                    if self._kind == 'houdini':
                        owner = boundary._load_operation_owners()[operation_id]
                        if isinstance(owner, dict) and owner.get('operation_kind') == 'output-verification':
                            return boundary.call('output.verify.status', {'verification_id': operation_id}).get('execution_fact')
                    if self._kind == 'houdini' and isinstance(owner, dict) and owner.get('task_id') == self._task_id:
                        return boundary.call('render.verify', {'task_id': self._task_id, 'operation_id': operation_id}).get('execution_fact')
                    if self._kind == 'nuke' and boundary._load_operation_owners()[operation_id] == self._task_id:
                        fact = boundary.call('render_fact', {'operation_id': operation_id})
                        if fact.get('task_id') != self._task_id:
                            raise ProductionBoundaryError('PRODUCTION_OPERATION_OWNER_MISMATCH')
                        return fact
            return prior(operation_id) if prior is not None else None
        registry.set_operation_source(operation_source)

    def call(self, command, params=None):
        if self._kind == 'houdini' and command in {'output.verify', 'output.verify.status'} and self._detached_factory is not None:
            boundary = self._detached_factory()
            if boundary is None:
                raise ProductionBoundaryError('PRODUCTION_OPERATION_OWNER_MISSING')
            boundary.bind_task(self._task_id)
            return boundary.call(command, params)
        return self._activate().call(command, params)

    def _activate(self):
        with self._lock:
            if self._boundary is None:
                boundary = self._factory()
                boundary.bind_task(self._task_id)
                self._boundary = boundary
            return self._boundary

    def mark_graph_trial_complete(self, task_id, receipt):
        # GraphRun discovers this method even while the worker is pending.
        return self._activate().mark_graph_trial_complete(task_id, receipt)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return getattr(self._activate(), name)


def build_graph_facade(manifest_path, *, coordinator=None, jobs=None, trusted_execution=None,
                       task_id: str, session_id: str, backend: str = "production",
                       host_client=None, nuke_client=None, registry=None, save_root=None,
                       repo_root: "Path | None" = None,
                       host_config: dict[str, Any] | None = None,
                       nuke_config: dict[str, Any] | None = None,
                       media_config: dict[str, Any] | None = None, application=None):
    """THE single facade assembly (C3).

    Production: the formal generator's server passes the coordinator and real
    host bindings.  Software tests pass backend='software' with explicit fake
    host clients; everything else (GraphRun, MCP surface, save/reopen
    services, ledger) is the shipped production code.
    """
    from .artifact_registry import ArtifactRegistry

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    application = application or manifest.get('application', 'pipeline')
    if application not in {'pipeline', 'nuke'}:
        raise ValueError('PRODUCTION_APPLICATION_MISMATCH')
    if registry is None:
        registry_root = Path(manifest_path).resolve().parent / "artifact_ledger"
        registry = ArtifactRegistry(registry_root)
    if save_root is None:
        # ``run.json`` lives under ``control``; the controller-owned output
        # root is the project-level sibling used by the formal server and its
        # artifact ledger, not an input/control directory.
        save_root = Path(manifest_path).resolve().parent.parent / "saves"
    save_root = Path(save_root)
    save_root.mkdir(parents=True, exist_ok=True)
    if jobs is not None and callable(getattr(jobs, "bind_task", None)):
        jobs.bind_task(task_id)
    software_addon = None
    boundary_addon = None
    if backend in {"software", "production"} and (repo_root is not None or host_client is None or nuke_client is None):
        if backend == "software" and repo_root is None:
            raise ValueError("software boundary requires repo_root (shipped add-on sources)")
        host_state = Path(manifest_path).resolve().parent / "host-state"
        nuke_state = Path(manifest_path).resolve().parent / "nuke-state"
        if host_client is None and application != 'nuke':
            if backend == "software":
                addon_source = repo_root / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py"
                host_client, software_addon = software_host_client(addon_source, host_state)
            else:
                host_client = production_host_client(host_config or manifest.get("production_host"), host_state)
        if nuke_client is None:
            if backend == "software":
                nuke_source = repo_root / "plugins" / "nuke" / "nuke_bridge_addon.py"
                worker_source = repo_root / "tools" / "nuke_owned_render_worker.py"
                nuke_client = software_nuke_client(nuke_source, nuke_state, worker_script=worker_source)
            else:
                nuke_client = production_nuke_client(nuke_config or manifest.get("production_nuke"), nuke_state)
        prepare_task = getattr(host_client, "prepare_task", None)
        if callable(prepare_task):
            prepare_task(task_id)
        for bound_client in (host_client, nuke_client):
            bind_task = getattr(bound_client, "bind_task", None)
            if callable(bind_task):
                bind_task(task_id)
    facade = GraphRun(manifest_path, coordinator, trusted_execution=trusted_execution,
                      task_id=task_id, session_id=session_id,
                      host_client=host_client, nuke_client=nuke_client,
                      artifact_registry=registry, save_root=str(save_root))
    facade.jobs_service = jobs
    facade.software_addon = software_addon
    facade.boundary_addon = boundary_addon or software_addon
    facade.production_addon = boundary_addon
    for producer in (nuke_client, host_client):
        bind_registry = getattr(producer, "bind_artifact_registry", None)
        if callable(bind_registry):
            bind_registry(registry)
    if backend == "software" and manifest.get("render_authorized") is True:
        prepare_input = getattr(nuke_client, "prepare_input_artifact", None)
        if callable(prepare_input):
            facade.software_input_artifact_id = prepare_input(task_id)
    facade.backend_kind = getattr(host_client or nuke_client, "backend_kind", "production")
    facade.application = application
    facade.wait_for_formal_trial = backend in {"software", "production"} and host_client is not None
    facade.max_frames_per_operation = MAX_FRAMES_PER_OPERATION
    facade.max_budget_seconds = MAX_BUDGET_SECONDS
    from .controller_media import ControllerMediaService, FixedVideoDecoder
    media_policy = dict(media_config or manifest.get("controller_media") or {})
    decoder_path = media_policy.get("ffmpeg_executable")
    video_decoder = FixedVideoDecoder(decoder_path) if decoder_path else None
    facade.media_service = ControllerMediaService(facade, video_decoder=video_decoder,
        **dict(media_policy.get("attachment_limits") or {}))
    facade.media_diagnostics_policy = dict(media_policy.get("sequence_diagnostics") or {})
    return facade


from contextlib import contextmanager
import threading


_SOFTWARE_RESOURCES_LOCK = threading.RLock()
_SOFTWARE_RESOURCES_OWNER = None


class SoftwareGraphResources:
    """Own software API globals, explicit environment and optional temp directory.

    Transfer TemporaryDirectory ownership here instead of entering it separately.
    A pending exit retains the owner; cleanup is a nonblocking retry after real
    monitor completion. No other software context may replace held API globals.
    """
    _modules = ("hou", "nuke", "_houdini_bridge_scene_identity_state")

    def __init__(self, *, environment=None, temporary_directory=None):
        self.environment = dict(environment or {})
        if any(not isinstance(name, str) or not name or not isinstance(value, str)
               for name, value in self.environment.items()):
            raise ValueError("software environment requires string names and values")
        self.temporary_directory = temporary_directory
        self._jobs = []
        self._entered = self._exited = self._released = False

    def __enter__(self):
        global _SOFTWARE_RESOURCES_OWNER
        from .graph_jobs import GraphJobError

        with _SOFTWARE_RESOURCES_LOCK:
            if _SOFTWARE_RESOURCES_OWNER is not None or self._entered:
                raise GraphJobError("SOFTWARE_RESOURCES_BUSY: existing API owner must finish cleanup")
            self._prior_modules = {name: sys.modules.get(name) for name in self._modules}
            self._prior_environment = {name: os.environ.get(name) for name in self.environment}
            os.environ.update(self.environment)
            self._entered = True
            _SOFTWARE_RESOURCES_OWNER = self
        return self

    def bind(self, jobs):
        from .graph_jobs import GraphJobError

        with _SOFTWARE_RESOURCES_LOCK:
            if _SOFTWARE_RESOURCES_OWNER is not self or self._exited:
                raise GraphJobError("software resources must have an active owner")
            summaries = [service.shutdown_snapshot() for service in self._jobs]
            if any(not item["closed"] or item["pending_monitors"] or item["unconfirmed_workers"]
                   for item in summaries):
                raise GraphJobError("SOFTWARE_RESOURCES_BUSY: controller already owns the native API")
            self._jobs.append(jobs)
            jobs.software_resources = self

    def snapshot(self):
        with _SOFTWARE_RESOURCES_LOCK:
            summaries = [jobs.shutdown_snapshot() for jobs in self._jobs]
            return {"retained": self._exited and not self._released,
                    "pending_monitors": sum(item["pending_monitors"] for item in summaries),
                    "unconfirmed_workers": [operation for item in summaries for operation in item["unconfirmed_workers"]]}

    def cleanup(self):
        global _SOFTWARE_RESOURCES_OWNER

        with _SOFTWARE_RESOURCES_LOCK:
            if self._released:
                return True
            if not self._entered or not self._exited:
                return False
            summaries = [jobs.shutdown_snapshot() for jobs in self._jobs]
            if any(not item["closed"] or item["pending_monitors"] or item["unconfirmed_workers"]
                   for item in summaries):
                return False
            if self.temporary_directory is not None:
                self.temporary_directory.cleanup()
            for name, module in self._prior_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            for name, value in self._prior_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            self._released = True
            _SOFTWARE_RESOURCES_OWNER = None
            return True

    def __exit__(self, error_type, error, traceback):
        from .graph_jobs import GraphJobError

        self._exited = True
        original_error = error
        try:
            cleaned = self.cleanup()
        except Exception as cleanup_error:
            error = cleanup_error if error is None else error
            error.resource_cleanup_error = cleanup_error
            error.add_note("SOFTWARE_RESOURCE_CLEANUP_FAILED: " + type(cleanup_error).__name__)
            cleaned = False
        if not cleaned:
            error = error if error is not None else GraphJobError("SOFTWARE_RESOURCES_RETAINED")
            error.software_resources = self
            try:
                error.resource_cleanup = self.snapshot()
            except Exception as observation_error:
                error.resource_observation_error = observation_error
                error.resource_cleanup = {"retained": not self._released, "pending_monitors": None,
                                          "unconfirmed_workers": None,
                                          "observation_error_type": type(observation_error).__name__}
                error.add_note("SOFTWARE_RESOURCE_OBSERVATION_FAILED: " + type(observation_error).__name__)
            error.add_note("SOFTWARE_RESOURCES_RETAINED: cleanup requires actual worker exit")
            if original_error is None:
                raise error
        return False


def _prepared_task_domain(manifest, application):
    """按已知领域登记任务；应用不匹配或未知标识不能悄悄退回默认烟雾域。"""
    from dcc_task_runtime.domains import builtin_domain_registry
    from dcc_task_runtime.errors import RuntimeV2Error
    default = 'nuke_composite_v1' if application == 'nuke' else 'pyro_smoke_v1'
    domain = manifest.get('domain_pack', default)
    if application not in {'pipeline', 'nuke'} or type(domain) is not str or not domain:
        raise ValueError('PRODUCTION_DOMAIN_PACK_INVALID')
    try:
        pack = builtin_domain_registry().get(domain, '1.0.0')
    except RuntimeV2Error as error:
        raise ValueError('PRODUCTION_DOMAIN_PACK_INVALID') from error
    if ((application == 'nuke' and domain != 'nuke_composite_v1')
            or (application == 'pipeline' and 'houdini' not in pack.dcc_applications)):
        raise ValueError('PRODUCTION_DOMAIN_APPLICATION_MISMATCH')
    return {'identifier': pack.identifier, 'version': pack.version}


@contextmanager
def prepared_graph_facade(manifest_path, *, repo_root, scheduler_root,
                          backend="production", allow_software_processes=False, software_resources=None,
                          application=None):
    """Assemble the prepared controller used by the generated server and probes.

    Jobs belong to this context. Task hosts retain their durable ownership and
    are stopped by the existing host lifecycle controller, including reconnects.
    """
    from .graph_jobs import GraphJobService
    from .service import ModelSafePipeline, TrustedExecutionControl
    from .task_graph import TaskGraphCoordinator
    from .workbuddy_project import media_descriptor

    manifest_path = Path(manifest_path).resolve()
    root, snapshot = manifest_path.parent, Path(repo_root).resolve()
    snapshot_manifest = root / "snapshot-manifest.json"
    if snapshot_manifest.is_file():
        for item in json.loads(snapshot_manifest.read_text())["files"]:
            path = snapshot / item["path"]
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Construction runtime changed; controller rebuild required")
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    application = application or manifest.get('application', 'pipeline')
    if application not in {'pipeline', 'nuke'}:
        raise ValueError('PRODUCTION_APPLICATION_MISMATCH')
    if manifest.get("construction_authorized") is not True:
        raise ValueError("controller construction authorization required")
    from .graph_construction_inputs import freeze_construction_inputs
    construction_inputs = freeze_construction_inputs(manifest.get('construction_input_manifest'))
    task_domain = _prepared_task_domain(manifest, application)
    if manifest.get('geometry_task_binding') is not None:
        # 几何两轮保持准备者登记的同一任务；装配不重新生成任务或解除原权限。
        from .geometry_job import bound_pipeline_task
        pipeline, task_id = bound_pipeline_task(manifest, root)
    else:
        pipeline = ModelSafePipeline(root / "pipeline.sqlite3")
        references = [{"asset_id": item["asset_id"], "kind": media_descriptor(item)["kind"],
                       "uri": str((root / item["file"]).resolve()), "sha256": item["sha256"]}
                      for item in manifest["assets"]]
        spec = {"schema_version": "2.0", "task_type": "visual.reference_rebuild",
                "intent": "synthetic bounded graph construction trial",
                "target": {"application": "pipeline", "scene_mode": "current"},
                "references": references, "domains": [task_domain],
                "feedback": "synthetic graph construction trial only", "render": {}, "delivery": {"composite": False}}
        task_id = pipeline.reference_task_start(spec, idempotency_key="graph-run:" + manifest["run_id"],
                                                purpose="graph_construction")["task_id"]
    trusted = TrustedExecutionControl(pipeline)
    jobs = None
    body_error = None
    owned_resources = None
    deferred_host = deferred_nuke = None
    try:
        if backend == "production":
            host_config, nuke_config = manifest.get("production_host"), manifest.get("production_nuke")
            if application == 'nuke':
                host_config = None
            if not isinstance(nuke_config, dict) or (application != 'nuke' and not isinstance(host_config, dict)):
                raise ValueError("PRODUCTION_CONFIG_REQUIRED: prepare_graph must receive production_host_config and production_nuke_config")
            if (host_config or {}).get("lifecycle") == "task_owned" or nuke_config.get("lifecycle") == "task_owned":
                from .production_hosts import ensure_hosts, validate_deployments
                configs = validate_deployments(host_config, nuke_config, controller_root=root,
                    repo_root=snapshot, allow_software_processes=allow_software_processes, application=application)
                validated = {config['application']: config for config in configs}
                host_config, nuke_config = validated.get('houdini'), validated['nuke']
                def host_factory(kind):
                    bound_h, bound_n = ensure_hosts(host_config, nuke_config, task_id=task_id,
                        controller_root=root, repo_root=snapshot, scheduler_root=Path(scheduler_root),
                        allow_software_processes=allow_software_processes, application=application,
                        host_kinds={kind})
                    factory = production_host_client if kind == 'houdini' else production_nuke_client
                    return factory(bound_h if kind == 'houdini' else bound_n,
                        root / ('host-state' if kind == 'houdini' else 'nuke-state'))
                def detached_factory(kind):
                    state_file = root / 'production-hosts.json'
                    if not state_file.is_file():
                        return None
                    saved = json.loads(state_file.read_text(encoding='utf-8'))
                    if saved.get('task_id') != task_id:
                        raise ProductionBoundaryError('PRODUCTION_BOUNDARY_TASK_CONFLICT')
                    fingerprint = hashlib.sha256(json.dumps(configs, ensure_ascii=False, sort_keys=True,
                        allow_nan=False).encode('utf-8')).hexdigest()
                    if saved.get('config_sha256') != fingerprint:
                        raise ProductionBoundaryError('PRODUCTION_DEPLOYMENT_CHANGED')
                    config = saved.get('hosts', {}).get(kind)
                    if config is None:
                        return None
                    factory = production_host_client if kind == 'houdini' else production_nuke_client
                    return factory(config, root / ('host-state' if kind == 'houdini' else 'nuke-state'))
                if application != 'nuke':
                    deferred_host = _DeferredTaskBoundary('houdini', lambda: host_factory('houdini'),
                        lambda: detached_factory('houdini'))
                deferred_nuke = _DeferredTaskBoundary('nuke', lambda: host_factory('nuke'),
                    lambda: detached_factory('nuke'))
            if application != 'nuke':
                jobs = GraphJobService(root / "jobs", snapshot, host_config["executable"],
                    frozen_input_manifest=construction_inputs,
                    scheduler_root=Path(scheduler_root), resource_budget=host_config.get("resource_budget"),
                    software_launch_script=host_config.get("software_launch_script"),
                    software_launch_script_sha256=host_config.get("software_launch_script_sha256"),
                    software_processes=allow_software_processes and host_config.get("evidence_source") == "software_test")
        elif backend == "software":
            if manifest.get("execution_authorized") is not True:
                raise ValueError("software backend requires a controller-authorized execution profile")
            if software_resources is None:
                owned_resources = SoftwareGraphResources()
                software_resources = owned_resources.__enter__()
            host_config = nuke_config = None
            if application != 'nuke':
                launcher = snapshot / 'tools/software_graph_worker.py'
                jobs = GraphJobService(root / "jobs", snapshot, str(Path(sys.executable).resolve()),
                    scheduler_root=Path(scheduler_root), frozen_input_manifest=construction_inputs,
                    software_launch_script=launcher,
                    software_launch_script_sha256=hashlib.sha256(launcher.read_bytes()).hexdigest(),
                    software_processes=True)
                software_resources.bind(jobs)
        elif backend == "diagnostic":
            host_config = nuke_config = None
            (root / "jobs" / "graph-jobs").mkdir(parents=True, exist_ok=True)
        else:
            raise ValueError("unknown prepared graph backend")
        coordinator = (TaskGraphCoordinator(pipeline, task_id, jobs, run_id=manifest["run_id"],
            session_id=manifest["session_id"], construction_authorized=manifest.get("construction_authorized") is True)
            if jobs is not None else None)
        facade = build_graph_facade(manifest_path, coordinator=coordinator, jobs=jobs,
            trusted_execution=trusted, task_id=task_id, session_id=manifest["session_id"],
            backend=backend, repo_root=snapshot, host_config=host_config, nuke_config=nuke_config,
            host_client=deferred_host, nuke_client=deferred_nuke, application=application)
        if backend == "diagnostic":
            facade.backend_kind = "diagnostic"
            facade.wait_for_formal_trial = False
        facade.controller_source = {"manifest_path": str(manifest_path),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "snapshot_manifest_sha256": hashlib.sha256(snapshot_manifest.read_bytes()).hexdigest() if snapshot_manifest.is_file() else None,
            "repo_root": str(snapshot), "backend": backend,
            "software_processes": bool(allow_software_processes)}
        yield facade
    except BaseException as original_error:
        if backend == "software":
            body_error = original_error
        raise
    finally:
        try:
            if jobs is not None:
                _close_prepared_jobs(jobs, backend, body_error)
        finally:
            if owned_resources is not None:
                owned_resources.__exit__(*sys.exc_info())


def _close_prepared_jobs(jobs, backend, body_error):
    try:
        summary = jobs.close(drain_in_process=True) if backend == "software" else jobs.close()
    except Exception as cleanup_error:
        if body_error is None:
            raise
        body_error.cleanup_issue = "SOFTWARE_WORKER_CLOSE_FAILED"
        body_error.cleanup_error = cleanup_error
        body_error.add_note("SOFTWARE_WORKER_CLOSE_FAILED: close raised " + type(cleanup_error).__name__)
    else:
        if backend == "software" and (summary["pending_monitors"] or summary["unconfirmed_workers"]):
            from .graph_jobs import GraphJobError

            issue = "SOFTWARE_WORKER_DRAIN_UNCONFIRMED: retain API modules and task directories"
            error = body_error if body_error is not None else GraphJobError(issue)
            error.close_summary = summary
            error.cleanup_issue = "SOFTWARE_WORKER_DRAIN_UNCONFIRMED"
            error.add_note(issue)
            if body_error is None:
                raise error
