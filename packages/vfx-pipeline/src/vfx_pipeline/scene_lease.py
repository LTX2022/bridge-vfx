"""Construction-time lease checks; host-side fencing is still required.

The controller supplies the current persisted lease and fresh host identity.
This module does not mint leases, launch hosts, or turn model fields into proof.
"""
from dataclasses import dataclass, asdict, replace
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
import math
import time
from typing import Callable, Mapping, Any


@dataclass(frozen=True)
class SceneLease:
    task_id: str
    session_id: str
    process_generation: str
    scene_id: str
    root: str
    generation: int
    expires_at: float

    def __post_init__(self):
        for name in ('task_id', 'session_id', 'process_generation', 'scene_id'):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError('lease identity fields are required')
        if (not isinstance(self.root, str) or not self.root.startswith('/obj/BRIDGE_GRAPH_')
                or '/' in self.root[len('/obj/'):] or '..' in self.root):
            raise ValueError('lease must own exactly one generated graph root')
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError('positive lease generation required')
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at):
            raise ValueError('finite lease expiry required')


class SceneLeaseGuard:
    def __init__(self, lease: SceneLease, current_lease: Callable[[], SceneLease],
                 host_identity: Callable[[], Mapping[str, Any]], *, clock=time.time):
        self.lease, self.current_lease, self.host_identity, self.clock = lease, current_lease, host_identity, clock

    def __call__(self, task_id: str, root: str, command: str, params: Mapping[str, Any]):
        lease = self.lease
        if task_id != lease.task_id or root != lease.root:
            raise ValueError('task or graph root differs from scene lease')
        current = self.current_lease()
        if not isinstance(current, SceneLease) or current != lease or self.clock() >= lease.expires_at:
            raise ValueError('scene lease expired, changed or was revoked')
        host = self.host_identity()
        if not isinstance(host, Mapping) or any(host.get(key) != getattr(lease, key)
                for key in ('session_id', 'process_generation', 'scene_id')):
            raise ValueError('host identity no longer matches scene lease')

        def owned(path):
            return isinstance(path, str) and '..' not in path.split('/') and (path == root or path.startswith(root + '/'))

        if command == 'node.children':
            allowed = params.get('path') == '/obj' or owned(params.get('path'))
        elif command == 'node.info':
            allowed = owned(params.get('path'))
        elif command == 'scene.create_task_root':
            # dedicated root creation: exact root name, parent and task
            layouts = {'geo': 'sop_geo/1', 'subnet': 'object_subnet/1'}
            allowed = (params.get('parent') == '/obj'
                       and params.get('type') in layouts
                       and params.get('root_layout', 'sop_geo/1') == layouts.get(params.get('type'))
                       and params.get('root_name') == root.rsplit('/', 1)[1]
                       and str(params.get('task_id') or '') == str(task_id))
        elif command == 'node.create':
            parent, name = params.get('parent'), params.get('name')
            allowed = isinstance(name, str) and bool(name) and '/' not in name and name not in ('.', '..') and (
                parent == '/obj' and name == root.rsplit('/', 1)[1] or owned(parent))
        elif command == 'node.set_parms':
            allowed = owned(params.get('path'))
        elif command == 'node.connect':
            allowed = owned(params.get('source')) and owned(params.get('destination'))
        else:
            allowed = False
        if not allowed:
            raise ValueError('command exceeds leased construction scope')


class SceneLeaseStore:
    """Controller-only persistent ownership; expiry never authorizes takeover.

    Revocation requires the controller to have reconciled outstanding host work.
    This store is not exposed as an MCP tool or an authorization issuer.
    """
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS scene_leases (session_id TEXT NOT NULL, scene_id TEXT NOT NULL, generation INTEGER NOT NULL, active INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(session_id,scene_id))')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _encode(lease):
        return json.dumps(asdict(lease), sort_keys=True, allow_nan=False)

    def acquire(self, *, task_id, session_id, process_generation, scene_id, root, ttl=120):
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError('positive finite lease TTL required')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT generation,active FROM scene_leases WHERE session_id=? AND scene_id=?', (session_id, scene_id)).fetchone()
            if row and row[1]:
                raise ValueError('scene already leased; expired owners require explicit reconciliation')
            generation = row[0] + 1 if row else 1
            lease = SceneLease(task_id, session_id, process_generation, scene_id, root, generation, self.clock()+ttl)
            db.execute('INSERT OR REPLACE INTO scene_leases VALUES (?,?,?,?,?)', (session_id, scene_id, generation, 1, self._encode(lease)))
            return lease

    def current(self, session_id, scene_id):
        with self._connect() as db:
            row = db.execute('SELECT active,payload FROM scene_leases WHERE session_id=? AND scene_id=?', (session_id, scene_id)).fetchone()
        return SceneLease(**json.loads(row[1])) if row and row[0] else None

    def _matching(self, db, lease):
        row = db.execute('SELECT active,payload FROM scene_leases WHERE session_id=? AND scene_id=?', (lease.session_id, lease.scene_id)).fetchone()
        if not row or not row[0] or SceneLease(**json.loads(row[1])) != lease:
            raise ValueError('stale or revoked lease cannot be changed')

    def renew(self, lease, *, ttl=120):
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError('positive finite lease TTL required')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._matching(db, lease)
            if self.clock() >= lease.expires_at:
                raise ValueError('expired lease requires reconciliation, not renewal')
            renewed = replace(lease, expires_at=self.clock()+ttl)
            db.execute('UPDATE scene_leases SET payload=? WHERE session_id=? AND scene_id=?', (self._encode(renewed), lease.session_id, lease.scene_id))
            return renewed

    def revoke(self, lease, *, host_operations_reconciled=False):
        if host_operations_reconciled is not True:
            raise ValueError('host operations must be reconciled before releasing ownership')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._matching(db, lease)
            db.execute('UPDATE scene_leases SET active=0 WHERE session_id=? AND scene_id=?', (lease.session_id, lease.scene_id))


    @contextmanager
    def operation(self, lease):
        """Serialize a host call against cooperative renew/revoke/rebind.

        A call already in flight is not undone. After revoke returns, a stale
        holder cannot start another call through this boundary.
        """
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._matching(db, lease)
            if self.clock() >= lease.expires_at:
                raise ValueError('expired scene lease cannot dispatch a host operation')
            yield

    def rebind_owned_scene(self, lease, identity):
        """Controller-only, after a verified owned save/reopen changed identity."""
        if (not isinstance(identity, Mapping)
                or identity.get('session_id') != lease.session_id
                or identity.get('process_generation') != lease.process_generation
                or not isinstance(identity.get('scene_id'), str) or not identity['scene_id']):
            raise ValueError('scene transition changed the host process identity')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._matching(db, lease)
            if self.clock() >= lease.expires_at:
                raise ValueError('expired lease cannot authorize a new scene generation')
            scene_id = identity['scene_id']
            if scene_id == lease.scene_id:
                return lease
            prior = db.execute('SELECT generation,active FROM scene_leases WHERE session_id=? AND scene_id=?',
                               (lease.session_id, scene_id)).fetchone()
            if prior and prior[1]:
                raise ValueError('new scene identity is already leased')
            generation = max(lease.generation, prior[0] if prior else 0) + 1
            rebound = replace(lease, scene_id=scene_id, generation=generation)
            db.execute('UPDATE scene_leases SET active=0 WHERE session_id=? AND scene_id=?',
                       (lease.session_id, lease.scene_id))
            db.execute('INSERT OR REPLACE INTO scene_leases VALUES (?,?,?,?,?)',
                       (rebound.session_id, rebound.scene_id, generation, 1, self._encode(rebound)))
            return rebound
