"""Read-only process observations and task-scoped filesystem primitives."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time

WINDOWS_REPLACE_RETRY_SECONDS = .5


def _windows():
    if __package__:
        from . import windows_process
    else:
        import windows_process
    return windows_process


def process_identity(pid):
    """Observe a PID without signaling it; birth is an opaque creation token."""
    platform = 'windows' if os.name == 'nt' else 'posix'
    result = {'pid': pid, 'platform': platform, 'birth': None, 'state': 'unknown'}
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        return result
    if os.name == 'nt':
        return _windows().query_process(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return {**result, 'state': 'stopped'}
    except (PermissionError, OSError):
        return result
    try:
        if Path('/proc/self/stat').exists():
            fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
            birth = fields[19]
            state = 'stopped' if fields[0] in ('Z', 'X') else 'alive'
        else:
            observed = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'stat='],
                                      capture_output=True, text=True, timeout=5,
                                      env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})
            if observed.returncode or not observed.stdout.strip():
                return result
            birth, status = observed.stdout.strip().rsplit(None, 1)
            state = 'stopped' if status.startswith('Z') else 'alive'
        return {**result, 'birth': birth, 'state': state}
    except FileNotFoundError:
        return {**result, 'state': 'stopped'}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return result


def process_status(identity):
    """Return alive, stopped, or unknown for the exact observed creation."""
    platform = 'windows' if os.name == 'nt' else 'posix'
    if (not isinstance(identity, dict) or identity.get('platform') != platform
            or type(identity.get('pid')) is not int or not isinstance(identity.get('birth'), str)
            or not identity['birth']):
        return 'unknown'
    current = process_identity(identity['pid'])
    if current['birth'] is not None and current['birth'] != identity['birth']:
        return 'unknown'
    return current['state']


def pid_alive(pid):
    """Unknown observations conservatively retain the caller's reservation."""
    return process_identity(pid)['state'] != 'stopped'


def lock_file(fd, blocking=True):
    """Acquire an exclusive crash-released lock without changing the cursor."""
    if os.name != 'nt':
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if not blocking or exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(.01)
    finally:
        os.lseek(fd, position, os.SEEK_SET)


def unlock_file(fd):
    if os.name != 'nt':
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    import msvcrt
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.lseek(fd, position, os.SEEK_SET)


def _plain_path(path):
    path = Path(os.path.abspath(path))
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('TASK_PATH_LINK')
    return path


def _owned_path(path, owned_root):
    root = _plain_path(owned_root)
    path = _plain_path(path)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError('TASK_ROOT_INVALID')
    if path != root and root not in path.parents:
        raise ValueError('TASK_PATH_OUTSIDE_ROOT')
    if path.exists() and path.is_file() and path.stat().st_nlink != 1:
        raise ValueError('TASK_PATH_HARDLINK')
    return path


def set_private_permissions(path):
    """Restrict to the current user (and SYSTEM on Windows)."""
    path = _plain_path(path)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise ValueError('TASK_PRIVATE_PATH_INVALID')
    if os.name == 'nt':
        _windows().set_private_permissions(path, directory=path.is_dir())
    else:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def _private_posix_stat_valid(information):
    return (stat.S_ISREG(information.st_mode) and information.st_nlink == 1
            and information.st_uid == os.getuid()
            and not information.st_mode & (stat.S_IRWXG | stat.S_IRWXO))


def private_permissions_valid(path, *, file_descriptor=None):
    """Validate existing private files without changing their permissions."""
    try:
        path = _plain_path(path)
        if os.name == 'nt':
            return _windows().private_permissions_valid(path, file_descriptor=file_descriptor)
        information = path.lstat()
        if not _private_posix_stat_valid(information):
            return False
        if file_descriptor is not None:
            opened = os.fstat(file_descriptor)
            return (_private_posix_stat_valid(opened)
                    and (opened.st_dev, opened.st_ino) == (information.st_dev, information.st_ino))
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def ensure_private_directory(path, *, parents=True, exist_ok=True):
    path = _plain_path(path)
    path.mkdir(mode=0o700, parents=parents, exist_ok=exist_ok)
    set_private_permissions(path)
    return path


def open_private_file(path, flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL):
    path = _plain_path(path)
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('TASK_PRIVATE_PATH_INVALID')
    descriptor = os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('TASK_PRIVATE_PATH_INVALID')
        set_private_permissions(path)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _retry_readonly(action, path):
    try:
        return action()
    except PermissionError:
        info = path.stat()
        if os.name != 'nt' or not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_READONLY:
            raise
        os.chmod(path, info.st_mode | stat.S_IWRITE)
        try:
            return action()
        except BaseException:
            os.chmod(path, info.st_mode)
            raise


def atomic_replace(source, destination, *, owned_root):
    """Replace within a verified task root, including owned read-only files."""
    source = _owned_path(source, owned_root)
    destination = _owned_path(destination, owned_root)
    if not source.is_file() or (destination.exists() and not destination.is_file()):
        raise ValueError('TASK_REPLACE_NOT_FILE')
    deadline = time.monotonic() + WINDOWS_REPLACE_RETRY_SECONDS
    for attempt in range(20):
        try:
            return _retry_readonly(lambda: os.replace(source, destination), destination)
        except OSError as exc:
            remaining = deadline - time.monotonic()
            if (os.name != 'nt' or getattr(exc, 'winerror', None) not in (5, 32, 33)
                    or remaining <= 0 or attempt == 19):
                raise
            time.sleep(min(.01 * 2 ** min(attempt, 3), .05, remaining))
            source = _owned_path(source, owned_root)
            destination = _owned_path(destination, owned_root)


def remove_owned_path(path, *, owned_root):
    """Remove a task-owned tree, rejecting links and paths outside its root."""
    path = _owned_path(path, owned_root)
    if not path.exists():
        return
    if path.is_dir():
        children = [_owned_path(child, owned_root) for child in path.iterdir()]
        for child in children:
            remove_owned_path(child, owned_root=owned_root)
        _retry_readonly(path.rmdir, path)
    else:
        _retry_readonly(path.unlink, path)


def atomic_write(path, data, *, owned_root):
    path = _owned_path(path, owned_root)
    temporary = path.with_name(path.name + '.tmp-' + secrets.token_hex(8))
    descriptor = open_private_file(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(temporary, path, owned_root=owned_root)
    finally:
        if temporary.exists():
            remove_owned_path(temporary, owned_root=owned_root)
