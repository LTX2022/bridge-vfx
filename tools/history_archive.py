#!/usr/bin/env python3
"""Operator-managed, content-deduplicated history storage; never grants execution.

The gateway forwards the original MCP protocol to a pinned, unmodified consumer.
Stores contain frozen sources or explicitly admitted terminal producer receipts,
never live databases or credentials. New receipt writes retain the expanded tree.
"""
from __future__ import annotations
import argparse
import contextlib
import select
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zlib

READ_ONLY = {'bridge_health', 'bridge_projects', 'bridge_select_project',
             'bridge_current_project', 'bridge_tasks', 'bridge_continue_task',
             'bridge_catalog', 'bridge_media', 'bridge_observe', 'bridge_propose', 'bridge_creation_status'}
PRIVATE_SUFFIXES = {'.key', '.pem', '.token', '.secret', '.sqlite', '.sqlite3', '.db'}
MAX_FILE = 64 * 1024 * 1024
TERMINAL_RECORDS = 'terminal_producer_records'
PRIVATE_FIELD = re.compile(r'token|secret|password|private_key|signing_key|hmac_key|api_key|credential|authorization', re.I)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def plain(path):
    p = Path(path).absolute()
    if any(x.is_symlink() for x in (p, *p.parents)):
        raise ValueError('HISTORY_ARCHIVE_LINKED_PATH')
    return p


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def file_bytes(path):
    p = plain(path)
    with p.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE:
            raise ValueError('HISTORY_ARCHIVE_FILE_INVALID')
        raw = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(before, k) != getattr(after, k) or getattr(after, k) != getattr(p.stat(), k) for k in keys):
            raise ValueError('HISTORY_ARCHIVE_FILE_CHANGED')
    return raw


def terminal_record(root, name, raw):
    """Admit unchanged terminal records using their producer-owned path identity."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:raise ValueError('HISTORY_ARCHIVE_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    record = json.loads(raw, object_pairs_hook=unique_object)
    if (Path(root).name != 'producer-records' or not isinstance(record, dict)
            or record.get('schema') not in ('bridge.houdini.producer-operation/1.0', 'bridge.houdini.producer-query/2')
            or record.get('state') not in ('COMPLETED', 'FAILED')
            or not isinstance(record.get('task_id'), str)
            or not record.get('task_id')
            or not isinstance(record.get('operation_id'), str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', record['operation_id'])):
        raise ValueError('HISTORY_ARCHIVE_TERMINAL_RECORD_REQUIRED')
    expected = digest(record['task_id'].encode()) + '/' + digest(record['operation_id'].encode()) + '.json'
    if name != expected:
        raise ValueError('HISTORY_ARCHIVE_RECORD_IDENTITY_MISMATCH')
    def private(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (isinstance(item, str) and item and not item.startswith(('/', '$'))
                        and key != 'attempt_token' and not key.endswith(('sha256', 'digest', 'path'))
                        and PRIVATE_FIELD.search(key)):
                    return True
                if isinstance(item, (dict, list)) and private(item):return True
        elif isinstance(value, list):
            return any(private(item) for item in value if isinstance(item, (dict, list)))
        return False
    if private(record):raise ValueError('HISTORY_ARCHIVE_PRIVATE_STATE')


def build(destination, roots, *, consumer, registry, legacy_guard=True, terminal_record_roots=()):
    destination = plain(destination)
    if destination.exists():
        raise ValueError('HISTORY_ARCHIVE_STORE_EXISTS')
    roots = sorted(plain(p) for p in roots)
    record_roots = {plain(p) for p in terminal_record_roots}
    if not record_roots <= set(roots):raise ValueError('HISTORY_ARCHIVE_RECORD_ROOT_INVALID')
    if len(set(roots)) != len(roots) or any(a in b.parents for a in roots for b in roots):
        raise ValueError('HISTORY_ARCHIVE_OVERLAPPING_ROOTS')
    if any(destination == p or p in destination.parents or destination in p.parents for p in roots):
        raise ValueError('HISTORY_ARCHIVE_STORE_OVERLAP')
    consumer = plain(consumer)
    destination.mkdir(mode=0o700, parents=True)
    db = destination / 'contents.sqlite3'
    entries = []
    try:
        with sqlite3.connect(db) as con:
            con.execute('CREATE TABLE objects (hash TEXT PRIMARY KEY, data BLOB NOT NULL)')
            for root in roots:
                if not root.is_dir():
                    raise ValueError('HISTORY_ARCHIVE_ROOT_MISSING')
                files = []
                for p in sorted(root.rglob('*')):
                    if p.is_symlink():
                        raise ValueError('HISTORY_ARCHIVE_LINKED_PATH')
                    if p.is_dir():
                        continue
                    if p.suffix in PRIVATE_SUFFIXES or p.name.startswith('.env'):
                        raise ValueError('HISTORY_ARCHIVE_PRIVATE_STATE')
                    raw = file_bytes(p); h = digest(raw); info = p.stat()
                    if root in record_roots:terminal_record(root, str(p.relative_to(root)), raw)
                    con.execute('INSERT OR IGNORE INTO objects VALUES (?, ?)', (h, zlib.compress(raw)))
                    files.append({'path': str(p.relative_to(root)), 'sha256': h,
                                  'bytes': len(raw), 'mode': stat.S_IMODE(info.st_mode),
                                  'mtime_ns': info.st_mtime_ns})
                if not files:
                    raise ValueError('HISTORY_ARCHIVE_EMPTY_ROOT')
                entry = {'root': str(root), 'files': files}
                if root in record_roots:
                    entry['kind'] = TERMINAL_RECORDS
                    parents = {'.', *(str(PurePosixPath(r['path']).parent) for r in files)}
                    entry['directory_modes'] = {name: stat.S_IMODE((root/name).stat().st_mode) for name in sorted(parents)}
                entries.append(entry)
        os.chmod(db, 0o600)
        config = {'schema': 'bridge.history-archive/1', 'database_sha256': digest(db.read_bytes()),
                  'consumer': str(consumer), 'consumer_sha256': digest(file_bytes(consumer)),
                  'registry': str(plain(registry)), 'legacy_guard': legacy_guard, 'roots': entries}
        (destination / 'catalog.json').write_bytes(canonical(config));os.chmod(destination / 'catalog.json', 0o600)
        store = Store(destination);store.verify_archive();store.verify_expanded()
        return {'roots': len(entries), 'files': sum(len(x['files']) for x in entries),
                'unique_contents': store.unique_contents(), 'archive_bytes': db.stat().st_size}
    except BaseException:
        shutil.rmtree(destination)
        raise


class Store:
    def __init__(self, directory):
        self.directory = plain(directory)
        self.config = json.loads(file_bytes(self.directory / 'catalog.json'))
        c = self.config
        if c.get('schema') != 'bridge.history-archive/1' or type(c.get('legacy_guard')) is not bool:
            raise ValueError('HISTORY_ARCHIVE_CONFIG_INVALID')
        self.roots = c['roots'];all_roots = []
        for entry in self.roots:
            root = plain(entry['root']);all_roots.append(root);seen = set()
            kind = entry.get('kind', 'source')
            if kind not in ('source', TERMINAL_RECORDS) or (kind == TERMINAL_RECORDS and root.name != 'producer-records'):
                raise ValueError('HISTORY_ARCHIVE_ROOT_KIND_INVALID')
            for r in entry['files']:
                name = r['path'];p = PurePosixPath(name)
                if not name or p.is_absolute() or '\\' in name or any(x in ('', '.', '..') for x in name.split('/')) or name.casefold() in seen:
                    raise ValueError('HISTORY_ARCHIVE_MEMBER_INVALID')
                seen.add(name.casefold())
                if not 0 <= r['bytes'] <= MAX_FILE or not 0 <= r['mode'] <= 0o777:
                    raise ValueError('HISTORY_ARCHIVE_MEMBER_INVALID')
                if kind == TERMINAL_RECORDS and not re.fullmatch(r'[0-9a-f]{64}/[0-9a-f]{64}\.json', name):
                    raise ValueError('HISTORY_ARCHIVE_RECORD_IDENTITY_MISMATCH')
            if kind == TERMINAL_RECORDS:
                directories = entry.get('directory_modes', {})
                expected = {'.', *(str(PurePosixPath(r['path']).parent) for r in entry['files'])}
                if (not isinstance(directories, dict) or set(directories) != expected
                        or any(type(mode) is not int or not 0 <= mode <= 0o777 for mode in directories.values())):
                    raise ValueError('HISTORY_ARCHIVE_DIRECTORY_MODES_INVALID')
        if len(set(all_roots)) != len(all_roots) or any(a in b.parents for a in all_roots for b in all_roots):
            raise ValueError('HISTORY_ARCHIVE_OVERLAPPING_ROOTS')
        self.database = plain(self.directory / 'contents.sqlite3')
        self.all_roots = self.roots
        projects = c.get('projects', {})
        if not isinstance(projects, dict) or any(not isinstance(v, list) or not set(v) <= {e['root'] for e in self.all_roots} for v in projects.values()):
            raise ValueError('HISTORY_ARCHIVE_PROJECT_MAP_INVALID')

    @contextlib.contextmanager
    def scope(self, project_id=None, *, control_only=False):
        previous = self.roots
        projects = self.config.get('projects')
        if projects:
            selected = [] if control_only else projects.get(project_id, [e['root'] for e in self.all_roots])
            consumer = Path(self.config['consumer'])
            self.roots = [e for e in self.all_roots if e['root'] in selected or Path(e['root']) in consumer.parents]
        try:yield
        finally:self.roots = previous

    @contextlib.contextmanager
    def database_reader(self):
        if digest(self.database.read_bytes()) != self.config['database_sha256']:
            raise ValueError('HISTORY_ARCHIVE_DIGEST_MISMATCH')
        with contextlib.closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as con:
            yield con

    def unique_contents(self):
        with self.database_reader() as con:
            return con.execute('SELECT count(*) FROM objects').fetchone()[0]

    def _raw(self, con, record):
        row = con.execute('SELECT data FROM objects WHERE hash=?', (record['sha256'],)).fetchone()
        if row is None:
            raise ValueError('HISTORY_ARCHIVE_MEMBER_MISSING')
        decoder = zlib.decompressobj();raw = decoder.decompress(row[0], record['bytes'] + 1)
        if len(raw) != record['bytes'] or not decoder.eof or decoder.unused_data or digest(raw) != record['sha256']:
            raise ValueError('HISTORY_ARCHIVE_MEMBER_CHANGED')
        return raw

    def verify_archive(self):
        with self.database_reader() as con:
            for e in self.roots:
                for r in e['files']:
                    raw = self._raw(con, r)
                    if e.get('kind') == TERMINAL_RECORDS:terminal_record(e['root'], r['path'], raw)

    def verify_expanded(self):
        for e in self.roots:
            root = plain(e['root']);expected = {r['path']: r for r in e['files']}
            if not root.is_dir():
                raise ValueError('HISTORY_ARCHIVE_ROOT_MISSING')
            actual = {str(p.relative_to(root)) for p in root.rglob('*') if not p.is_dir() or p.is_symlink()}
            pinned_records = (e.get('kind') == TERMINAL_RECORDS
                              and plain(self.directory/'pins'/digest(e['root'].encode())).exists())
            if any(p.is_symlink() for p in root.rglob('*')):
                raise ValueError('HISTORY_ARCHIVE_LINKED_PATH')
            if ((not pinned_records and actual != set(expected))
                    or (pinned_records and not set(expected) <= actual)):
                raise ValueError('HISTORY_ARCHIVE_TREE_CHANGED')
            if e.get('kind') == TERMINAL_RECORDS:
                for name, mode in e['directory_modes'].items():
                    if stat.S_IMODE(plain(root/name).stat().st_mode) != mode:
                        raise ValueError('HISTORY_ARCHIVE_DIRECTORY_MODE_CHANGED')
            for name, r in expected.items():
                p = root / name
                if digest(file_bytes(p)) != r['sha256'] or stat.S_IMODE(p.stat().st_mode) != r['mode']:
                    raise ValueError('HISTORY_ARCHIVE_FILE_CHANGED')

    @contextlib.contextmanager
    def lock(self, exclusive=False, nonblocking=False):
        import fcntl
        path = plain(self.directory / 'access.lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_nlink != 1:
                raise ValueError('HISTORY_ARCHIVE_LOCK_INVALID')
            flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(fd, flags | (fcntl.LOCK_NB if nonblocking else 0))
            yield fd
        finally:
            os.close(fd)

    def _restore(self):
        with self.database_reader() as con:
            for e in self.roots:
                root = plain(e['root'])
                if root.exists():
                    continue  # Never repair or overwrite an existing tree.
                if (e.get('kind') == TERMINAL_RECORDS
                        and plain(self.directory/'pins'/digest(e['root'].encode())).exists()):
                    raise ValueError('HISTORY_ARCHIVE_PINNED_RECORD_ROOT_MISSING')
                plain(root.parent).mkdir(parents=True, exist_ok=True)
                temp = Path(tempfile.mkdtemp(prefix='.bridge-restore-', dir=root.parent))
                try:
                    for r in e['files']:
                        p = temp / r['path'];p.parent.mkdir(parents=True, exist_ok=True)
                        with p.open('xb') as stream:
                            stream.write(self._raw(con, r))
                        os.chmod(p, r['mode']);os.utime(p, ns=(r['mtime_ns'], r['mtime_ns']))
                    if e.get('kind') == TERMINAL_RECORDS:
                        for name, mode in e['directory_modes'].items():os.chmod(temp/name, mode)
                    if root.exists() or root.is_symlink():
                        raise ValueError('HISTORY_ARCHIVE_DESTINATION_CHANGED')
                    os.rename(temp, root)
                finally:
                    if temp.exists():shutil.rmtree(temp)
        self.verify_expanded()

    @contextlib.contextmanager
    def lease(self):
        import fcntl
        # Acquire shared first so concurrent readers do not wait for each other.
        with self.lock() as fd:
            if any(not plain(e['root']).is_dir() for e in self.roots):
                fcntl.flock(fd, fcntl.LOCK_UN)
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._restore()
                fcntl.flock(fd, fcntl.LOCK_SH)
            else:
                self.verify_expanded()
            yield

    def pin(self):
        directory = plain(self.directory / 'pins');directory.mkdir(exist_ok=True)
        for e in self.roots:
            path = plain(directory / digest(e['root'].encode()))
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            try:os.fsync(fd)
            finally:os.close(fd)

    def legacy_readers(self, exclude=()):
        try:
            result = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True, timeout=5)
            if result.returncode:
                return ['process_inventory_unavailable']
        except (OSError, subprocess.TimeoutExpired):
            return ['process_inventory_unavailable']
        own = {os.getpid(), *exclude};found = [];rows = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3:rows.append((int(parts[0]), int(parts[1]), parts[2]))
        gateways = set()
        for pid, parent, command in rows:
            try:tokens = shlex.split(command)
            except ValueError:continue
            if tokens and Path(tokens[0]).name.startswith('python') and '--history-archive-gateway' in tokens:
                gateways.add(pid)
        for pid, parent, command in rows:
            if ('bridge_mcp.py' in command or 'workbuddy_graph_mcp' in command) and pid not in own | gateways and parent not in gateways:
                found.append(pid)
        return found

    def _remove_retired(self, tomb, entry):
        expected = {r['path']: r for r in entry['files']}
        for p in tomb.rglob('*'):
            if p.is_symlink():raise ValueError('HISTORY_ARCHIVE_RETIREMENT_CHANGED')
            if p.is_dir():continue
            record = expected.get(str(p.relative_to(tomb)))
            if record is None or digest(file_bytes(p)) != record['sha256']:
                raise ValueError('HISTORY_ARCHIVE_RETIREMENT_CHANGED')
        shutil.rmtree(tomb)

    def compact(self, *, exclude=()):
        try:
            with self.lock(exclusive=True, nonblocking=True):
                if (self.directory / 'keep-expanded').exists():return {'state': 'PINNED'}
                pinned = [e for e in self.roots if (self.directory/'pins'/digest(e['root'].encode())).exists()]
                if self.roots and len(pinned) == len(self.roots):
                    return {'state': 'PINNED', 'removed_files': 0, 'pinned_roots': len(pinned)}
                legacy = self.legacy_readers(exclude) if self.config['legacy_guard'] else []
                if legacy:return {'state': 'LEGACY_READERS_ACTIVE', 'readers': legacy}
                self.verify_archive()
                # Check all existing roots before removing any. Changed data is retained.
                pinned = [e for e in self.roots if (self.directory/'pins'/digest(e['root'].encode())).exists()]
                existing = [e for e in self.roots if e not in pinned and plain(e['root']).exists()]
                previous = self.roots
                try:self.roots = existing;self.verify_expanded()
                finally:self.roots = previous
                retired = plain(self.directory / 'retiring');retired.mkdir(exist_ok=True)
                for e in self.roots:
                    tomb = plain(retired / digest(e['root'].encode()))
                    if tomb.exists():self._remove_retired(tomb, e)
                for e in existing:
                    root = plain(e['root']);tomb = retired / digest(e['root'].encode())
                    os.rename(root, tomb)  # A crash never leaves a half-deleted canonical root.
                    self._remove_retired(tomb, e)
                return {'state': ('PARTIALLY_PINNED' if existing else 'PINNED') if pinned else 'COMPACT',
                        'removed_files': sum(len(e['files']) for e in existing), 'pinned_roots': len(pinned)}
        except BlockingIOError:
            return {'state': 'IN_USE'}


def input_lines(stream, idle_seconds=10):
    """Preserve pipelined JSON lines; release idle caches without another service."""
    try:fd = stream.fileno()
    except (AttributeError, OSError):
        yield from stream
        return
    pending = b''
    while True:
        if b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            yield line.decode() + '\n'
            continue
        if not select.select([fd], [], [], idle_seconds)[0]:
            yield None
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            if pending:yield pending.decode()
            return
        pending += chunk
        if len(pending) > 16 * 1024 * 1024:
            raise ValueError('HISTORY_GATEWAY_REQUEST_SIZE_LIMIT')


def gateway(store, *, registry=None, stdin=sys.stdin, stdout=sys.stdout):
    """Keep a selected project's source lease through a query burst, then expire it."""
    if registry is not None and str(plain(registry)) != store.config['registry']:
        store.config = dict(store.config, registry=str(plain(registry)))
        store.config.pop('projects', None)
    proc = None;selected = None;active = None;stack = contextlib.ExitStack()
    def release():
        nonlocal active, stack
        if active is None:return
        project, control = active
        stack.close();stack = contextlib.ExitStack();active = None
        with store.scope(project, control_only=control):
            store.compact(exclude=(() if proc is None else (proc.pid,)))
    try:
        for line in input_lines(stdin):
            if line is None:
                release()
                continue
            request = json.loads(line)
            params = request.get('params', {})
            if not isinstance(params, dict):params = {}
            tool = params.get('name') if request.get('method') == 'tools/call' else None
            arguments = params.get('arguments', {})
            if not isinstance(arguments, dict):arguments = {}
            if tool == 'bridge_select_project':selected = arguments.get('project_id')
            project = arguments.get('project_id', selected)
            if not isinstance(project, (str, type(None))):project = None
            control = tool in ('bridge_health', 'bridge_projects', 'bridge_connect', 'bridge_connection_status', 'bridge_disconnect') or request.get('method') != 'tools/call'
            key = (project, control)
            if active != key:
                release()
                stack.enter_context(store.scope(project, control_only=control))
                stack.enter_context(store.lease());active = key
            if digest(file_bytes(store.config['consumer'])) != store.config['consumer_sha256']:
                raise ValueError('HISTORY_ARCHIVE_CONSUMER_CHANGED')
            if proc is None:
                proc = subprocess.Popen([sys.executable, '-I', '-B', store.config['consumer'], 'serve',
                                         '--projects', store.config['registry']],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
            if tool is not None and (tool not in READ_ONLY or (
                    tool in ('bridge_observe', 'bridge_propose')
                    and any(e.get('kind') == TERMINAL_RECORDS for e in store.roots))):
                store.pin()  # Async work keeps only this project's restored roots.
            proc.stdin.write(line);proc.stdin.flush()
            if 'id' in request:
                while True:
                    answer = proc.stdout.readline()
                    if not answer:raise RuntimeError('HISTORY_ARCHIVE_CONSUMER_EXITED')
                    stdout.write(answer);stdout.flush()
                    if json.loads(answer).get('id') == request['id']:break
    finally:
        if proc is not None:
            try:proc.stdin.close()
            except BrokenPipeError:pass
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
            proc.stdout.close()
        release();stack.close();store.compact()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify', 'restore', 'compact', 'serve'))
    parser.add_argument('store', type=Path)
    parser.add_argument('--roots-file', type=Path)
    parser.add_argument('--consumer', type=Path)
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--terminal-record-roots-file', type=Path)
    args = parser.parse_args()
    if args.action == 'build':
        print(json.dumps(build(args.store, json.loads(args.roots_file.read_text()), consumer=args.consumer, registry=args.registry,
                               terminal_record_roots=(() if args.terminal_record_roots_file is None else json.loads(args.terminal_record_roots_file.read_text())))))
        return
    store = Store(args.store)
    if args.action == 'verify':store.verify_archive();print('VERIFIED')
    elif args.action == 'restore':
        with store.lease():pass
        print('RESTORED')
    elif args.action == 'compact':print(json.dumps(store.compact()))
    else:gateway(store, registry=args.registry)


if __name__ == '__main__':
    main()
