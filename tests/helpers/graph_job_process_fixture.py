"""Controlled SOFTWARE ONLY subprocess with explicit native APIs; no DCC."""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for name in ("dcc-task-runtime", "houdini-bridge", "nuke-bridge", "vfx-pipeline"):
    sys.path.insert(0, str(ROOT / "packages" / name / "src"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))

from test_graph_jobs import _proposal
from source_host_fixture import FakeSourceHost
from vfx_pipeline.graph_job_worker import DurableJournal, run_job
from vfx_pipeline.graph_jobs import GraphJobService, GraphJobError
from dcc_task_runtime.owned_process import launch
from dcc_task_runtime import owned_process


def python_command(*arguments):
    return [getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', *map(str, arguments)]


class SoftwareProcessHandle:
    """Native supervision with an explicit lost-cancellation transport fault."""

    def __init__(self, handle, *, drop_cancellation=False):
        self.handle = handle
        self.pid = handle.pid
        self.started = handle.started
        self.drop_cancellation = drop_cancellation

    @property
    def returncode(self):
        return self.handle.returncode

    def poll(self):
        return self.handle.poll()

    def wait(self, timeout=None):
        return self.handle.wait(timeout)

    def terminate(self):
        if not self.drop_cancellation:
            self.handle.terminate()

    def kill(self):
        self.handle.kill()


class SoftwareChildWaitHandle(SoftwareProcessHandle):
    """Direct child wait observation; group quiescence remains the controller's check."""

    @property
    def returncode(self):
        return self.poll()

    def poll(self):
        path = self.handle.directory / 'software-child-wait.json'
        if not path.exists():
            return None
        observation = json.loads(path.read_text(encoding='utf-8'))
        if (observation.get('pid') != self.pid or observation.get('identity') != self.handle.identity
                or observation.get('observed_by') != 'software_native_child_wait'
                or type(observation.get('exit_code')) is not int):
            raise ValueError('SOFTWARE_CHILD_WAIT_MISMATCH')
        return observation['exit_code']

    def wait(self, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('software child wait', timeout)
            time.sleep(.01)
        remaining = max(0, deadline - time.monotonic()) if deadline is not None else None
        self.handle._supervisor.wait(timeout=remaining)
        return self.poll()


def supervise_child_wait(directory):
    """Run the shipped supervisor, observing its actual native child wait."""
    directory = Path(directory)
    native_process = owned_process.WindowsJobProcess if os.name == 'nt' else subprocess.Popen

    class ObservedChild(native_process):
        def _publish_child_wait(self, code):
            if code is None or getattr(self, '_software_wait_published', False):
                return code
            binding = json.loads(os.environ['BRIDGE_SOFTWARE_WAIT_IDENTITY'])
            started = owned_process.read_receipt(directory, 'started', identity=binding)
            if not started or started['pid'] != self.pid:
                raise ValueError('SOFTWARE_CHILD_WAIT_START_MISMATCH')
            owned_process._atomic(directory / 'software-child-wait.json', {
                'identity': binding, 'pid': self.pid, 'exit_code': code,
                'observed_by': 'software_native_child_wait',
            })
            self._software_wait_published = True
            return code

        def poll(self):
            # Native poll observes/reaps the direct child before the supervisor
            # can finish waiting for the whole owned group.
            return self._publish_child_wait(super().poll())

        def wait(self, timeout=None):
            return self._publish_child_wait(super().wait(timeout=timeout))

    if os.name == 'nt':
        with patch.object(owned_process, 'WindowsJobProcess', ObservedChild):
            return owned_process.supervise(directory)
    boundary = SimpleNamespace(**vars(subprocess))
    boundary.Popen = ObservedChild
    with patch.object(owned_process, 'subprocess', boundary):
        return owned_process.supervise(directory)


def launch_worker(job_json, *, fault='none', env=None, observe_child_wait=False):
    job = json.loads(job_json)
    directory = Path(job['inputs_path']).parent
    identity = {'operation_id': job['operation_id'], 'attempt_token': job['attempt_token'],
                'generation': job['attempt_generation']}
    worker_env = dict(os.environ if env is None else env)
    worker_env.update(BRIDGE_OWNED_SUPERVISOR_DIR=str(directory / 'owned-supervisor'),
                      BRIDGE_OWNED_SUPERVISOR_IDENTITY=json.dumps(identity))
    command = python_command(Path(__file__).resolve(), 'worker', '--job', job_json, '--fault', fault)
    options = dict(directory=directory / 'owned-supervisor', identity=identity,
                   supervisor_executable=getattr(sys, '_base_executable', sys.executable), env=worker_env)
    if observe_child_wait or (fault == 'same_session_descendant' and os.name != 'nt'):
        def spawn_supervisor(argv, **process_options):
            if argv[1:] != ['-B', str(Path(owned_process.__file__).resolve()), '--supervise', str(options['directory'])]:
                raise ValueError('SOFTWARE_SUPERVISOR_COMMAND_MISMATCH')
            environment = dict(process_options.get('env') or os.environ)
            environment['BRIDGE_SOFTWARE_WAIT_IDENTITY'] = json.dumps(identity)
            return subprocess.Popen(python_command(Path(__file__).resolve(), 'supervisor', '--job',
                                                  json.dumps(str(options['directory']))),
                                    **{**process_options, 'env': environment})
        boundary = SimpleNamespace(**vars(subprocess))
        boundary.Popen = spawn_supervisor
        with patch.object(owned_process, 'subprocess', boundary):
            handle = launch(command, **options)
        return SoftwareChildWaitHandle(handle)
    handle = launch(command, **options)
    return SoftwareProcessHandle(handle, drop_cancellation=fault == 'ignore_terminate')


def directory_alias(path, target):
    """Use real directory links; Windows junctions need no symlink privilege."""
    path, target = Path(path), Path(os.path.abspath(target))
    if os.name != 'nt':
        path.symlink_to(target, target_is_directory=True)
        return
    from ctypes import wintypes
    library = ctypes.WinDLL('kernel32', use_last_error=True)
    library.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    library.CreateFileW.restype = wintypes.HANDLE
    library.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    library.DeviceIoControl.restype = wintypes.BOOL
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    library.CloseHandle.restype = wintypes.BOOL
    substitute = ('\\??\\' + str(target)).encode('utf-16-le')
    printable = str(target).encode('utf-16-le')
    names = substitute + b'\0\0' + printable + b'\0\0'
    buffer = ctypes.create_string_buffer(struct.pack('<IHHHHHH', 0xa0000003, len(names) + 8, 0,
                                                     0, len(substitute), len(substitute) + 2, len(printable)) + names)
    path.mkdir()
    handle = library.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x02000000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        path.rmdir()
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        returned = wintypes.DWORD()
        if not library.DeviceIoControl(handle, 0x900a4, buffer, len(buffer) - 1,
                                       None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        library.CloseHandle(handle)


def append_event(path, value):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def wait_file(path, timeout=12):
    deadline = time.monotonic() + timeout
    while not Path(path).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test controller gate was not released")
        time.sleep(0.01)


def worker(job, fault):
    directory = Path(job["result_path"]).parent
    if fault == "ignore_terminate":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    if fault == "crash_before_journal_commit":
        original = DurableJournal.write
        def write(self, operation_id, value):
            # Keep the original crash window: AFTER a node.create host effect,
            # BEFORE its journal commit. (Root creation is a different op.)
            if value.get("status") == "COMPLETE" and value.get("intent", {}).get("kind") == "node.create":
                os._exit(93)  # Durable INTENT survives, host effect log already fsynced.
            return original(self, operation_id, value)
        DurableJournal.write = write
    spec = importlib.util.spec_from_file_location(
        "_graph_recovery_addon", ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py")
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    state_directory = addon._state_dir
    state_path = addon._fx_state_path
    with FakeSourceHost(addon), patch.dict(os.environ, {
        "HOUDINI_BRIDGE_STATE_DIR": str(directory / "native-state" / "houdini"),
        "BRIDGE_SKILLS_STATE_ROOT": str(directory / "native-state" / "runtime"),
        "BRIDGE_SKILLS_SCHEDULER_ROOT": str(directory / "native-state" / "scheduler"),
    }), patch.object(addon, "_state_dir", state_directory), patch.object(addon, "_fx_state_path", state_path):
        original_dispatch = addon.dispatch

        def dispatch(command, params):
            result = original_dispatch(command, params)
            if command in {"node.create", "node.set_parms", "node.connect", "scene.create_task_root", "scene.save_hip", "scene.reopen_owned_hip"}:
                append_event(directory / "software_host_effects.jsonl", {"command": command, "params": params})
            if fault == "drop_reply" and command == "node.create":
                raise RuntimeError("SOFTWARE fault: effect happened, reply was lost")
            return result

        with patch.object(addon, "dispatch", dispatch):
            result = run_job(job, addon=addon)
    if fault == "same_session_descendant":
        # Deliberately do not detach: this tests the owned group, not a claim
        # of containing arbitrary Full Access tools or new-session children.
        script = "import json,os,pathlib,sys,time; p=pathlib.Path(sys.argv[1]); (p/'descendant_waiting').write_text(json.dumps({'pid':os.getpid()})); end=time.monotonic()+20\nwhile not (p/'release_descendant').exists() and time.monotonic()<end: time.sleep(.01)"
        subprocess.Popen(python_command('-c', script, directory),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_file(directory / "descendant_waiting")
    if fault in {"ignore_terminate", "hang_after_completion"}:
        (directory / "worker_waiting").write_text("software process remains alive\n")
        wait_file(directory / "release_worker")
    return result


def controller(payload):
    root, scheduler, gates = map(Path, (payload["root"], payload["scheduler"], payload["gates"]))
    def execute(job):
        append_event(gates / "invocations.jsonl", {"pid": os.getpid(), "operation_id": job["operation_id"]})
        wait_file(gates / "release")
        return {"construction_executed": True, "visual_verified": False}
    service = GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=scheduler, worker_factory=execute)
    graph_id = service.propose(_proposal(), "same-proposal")
    (gates / ("ready-" + payload["name"])).write_text("ready\n")
    wait_file(gates / "start")
    try:
        operation_id = service.trial(graph_id, payload["request"])
        report = {"accepted": True, "operation_id": operation_id}
    except GraphJobError:
        report = {"accepted": False}
    (gates / ("report-" + payload["name"])).write_text(json.dumps(report))
    wait_file(gates / "release")
    for thread in tuple(service._threads.values()):
        thread.join(5)
    service.close()


def orphan(payload):
    root, scheduler, marker = map(Path, (payload["root"], payload["scheduler"], payload["marker"]))
    service = GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=scheduler,
                              worker_factory=lambda job: (_ for _ in ()).throw(AssertionError("must not dispatch")))
    graph_id = service.propose(_proposal(), "same-proposal")
    original = service.scheduler.reserve
    def reserve(*args):
        result = original(*args)
        marker.write_text("global reservation committed; local transaction will be rolled back\n")
        os._exit(75)
    service.scheduler.reserve = reserve
    service.trial(graph_id, "same-trial")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("worker", "controller", "orphan", "supervisor"))
    parser.add_argument("--job", required=True)
    parser.add_argument("--fault", default="none")
    args = parser.parse_args()
    payload = json.loads(args.job)
    if args.mode == "worker":
        result = worker(payload, args.fault)
        raise SystemExit(0 if result.get("construction_executed") is True
                         and result.get("reconciliation_required") is False else 2)
    elif args.mode == "supervisor":
        raise SystemExit(supervise_child_wait(payload))
    elif args.mode == "controller":
        controller(payload)
    else:
        orphan(payload)
