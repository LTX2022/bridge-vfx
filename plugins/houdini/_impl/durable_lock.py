# -*- coding: utf-8 -*-
"""Vendored durable execution lock.

Verbatim semantics of ``dcc_task_runtime.execution_lock`` (flock-based,
crash-released, thread-registered). Used when the runtime package is not
importable inside the DCC host; the runtime original is preferred at runtime.
"""
from contextlib import contextmanager
from functools import wraps
import hashlib
import os
from pathlib import Path
import stat
import threading
import weakref

_registry_guard = threading.Lock()
_registry = weakref.WeakValueDictionary()
_local = threading.local()


@contextmanager
def execution_lock(database, task_id):
    identity = str(Path(database).resolve()) + "\0" + str(task_id)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    root = Path(database).resolve().parent / ".execution-locks"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise RuntimeError("POLICY_DENIED: execution lock directory cannot be a symlink")
    path = root / (digest + ".lock")
    with _registry_guard:
        mutex = _registry.setdefault(str(path), threading.RLock())
    if not mutex.acquire(blocking=False):
        raise RuntimeError("INVALID_TRANSITION: another executor is advancing this task")
    held = getattr(_local, "held", None)
    if held is None:
        held = _local.held = set()
    descriptor = None
    acquired = False
    nested = str(path) in held
    try:
        if not nested:
            descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RuntimeError("POLICY_DENIED: execution lock must be a regular file")
            try:
                if os.name == "nt":
                    import msvcrt
                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"\0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("INVALID_TRANSITION: another process is advancing this task") from exc
            acquired = True
            held.add(str(path))
        yield
    finally:
        if acquired:
            held.remove(str(path))
            if os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        if descriptor is not None:
            os.close(descriptor)
        mutex.release()
