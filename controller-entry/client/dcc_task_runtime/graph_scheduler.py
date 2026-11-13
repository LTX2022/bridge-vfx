"""Installation-wide cooperative heavy-job ownership.

Reservations never expire. A crash between databases may leave a blocked
reservation, not an available slot. This is deliberately NOT isolation from
other tools available to the same Full Access user.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any, Mapping

from dcc_task_runtime.canonical import canonical_json


class SchedulerBusy(ValueError):
    pass


class GraphScheduler:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "graph_scheduler.sqlite3"
        if self.path.is_symlink():
            raise ValueError("scheduler database must not be a symlink")
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS heavy_slot (
                slot INTEGER PRIMARY KEY CHECK(slot=1), generation INTEGER NOT NULL,
                active INTEGER NOT NULL, owner_root TEXT NOT NULL,
                operation_id TEXT NOT NULL, token TEXT NOT NULL, phase TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                process_json TEXT, updated_at REAL NOT NULL)""")

            db.execute("""CREATE TABLE IF NOT EXISTS stopped_attempts (
                owner_root TEXT NOT NULL, operation_id TEXT NOT NULL, token TEXT NOT NULL,
                fact_json TEXT NOT NULL, PRIMARY KEY(owner_root,operation_id,token))""")

            db.execute("""CREATE TABLE IF NOT EXISTS legacy_blockers (
                owner_root TEXT NOT NULL, operation_id TEXT NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY(owner_root,operation_id))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
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

    def reserve(self, owner_root: str, operation_id: str) -> dict[str, Any]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM legacy_blockers WHERE active=1 LIMIT 1").fetchone():
                raise SchedulerBusy("installation has an unreconciled legacy graph worker")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if row and row["active"]:
                raise SchedulerBusy("installation has an active or unreconciled graph job")
            generation = int(row["generation"]) + 1 if row else 1
            token = secrets.token_hex(32)
            db.execute("INSERT OR REPLACE INTO heavy_slot VALUES(1,?,1,?,?,?,'RESERVED',0,NULL,?)",
                       (generation, owner_root, operation_id, token, time.time()))
            return {"generation": generation, "token": token}

    @staticmethod
    def _match(row, owner_root, operation_id, token):
        return (row is not None and row["active"] and row["owner_root"] == owner_root
                and row["operation_id"] == operation_id and row["token"] == token)

    def snapshot(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
        return dict(row) if row else None

    def owned(self, owner_root, operation_id, token):
        row = self.snapshot()
        if not self._match(row, owner_root, operation_id, token):
            raise SchedulerBusy("graph executor no longer owns the installation slot")
        return row

    def launched_fact(self, owner_root, operation_id, token):
        """Read exact launch provenance even after its own slot was released."""
        with self.connect() as db:
            active = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if self._match(active, owner_root, operation_id, token):
                return dict(active)
            row = db.execute("SELECT fact_json FROM stopped_attempts WHERE owner_root=? AND operation_id=? AND token=?",
                             (owner_root, operation_id, token)).fetchone()
        if row is None:
            raise SchedulerBusy("no matching durable launched attempt")
        return json.loads(row[0])

    def arm(self, owner_root, operation_id, token, *, identity: Mapping[str, Any] | None = None):
        process_json = canonical_json(dict(identity)) if identity is not None else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""UPDATE heavy_slot SET phase='DISPATCHING',updated_at=?,
                process_json=CASE WHEN ? IS NULL THEN process_json ELSE ? END
                WHERE slot=1 AND active=1 AND owner_root=? AND operation_id=? AND token=?
                AND phase='RESERVED' AND cancel_requested=0""",
                (time.time(), process_json, process_json, owner_root, operation_id, token))
            if cursor.rowcount != 1:
                raise SchedulerBusy("launch permit was fenced before dispatch")

    def bind_process(self, owner_root, operation_id, token, identity: Mapping[str, Any]):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if not self._match(row, owner_root, operation_id, token) or row["phase"] != "DISPATCHING":
                raise SchedulerBusy("process cannot bind to a stale launch permit")
            prior = json.loads(row["process_json"]) if row["process_json"] else None
            if prior is not None and prior != dict(identity):
                raise SchedulerBusy("launch already has a different process identity")
            db.execute("UPDATE heavy_slot SET process_json=?,updated_at=? WHERE slot=1",
                       (canonical_json(dict(identity)), time.time()))

    @contextmanager
    def operation(self, owner_root, operation_id, token):
        """Fence every cooperative host call, including save/reopen/verification.

        Revocation waits for an in-flight call. It does not claim to undo or
        interrupt it; after revocation no next call can enter this boundary.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if (db.execute("SELECT 1 FROM legacy_blockers WHERE active=1 LIMIT 1").fetchone()
                    or not self._match(row, owner_root, operation_id, token)
                    or row["phase"] != "DISPATCHING" or row["cancel_requested"]):
                raise SchedulerBusy("host operation was fenced")
            yield

    def request_cancel(self, owner_root, operation_id, token) -> bool:
        with self.connect() as db:
            cursor = db.execute("""UPDATE heavy_slot SET cancel_requested=1,updated_at=?
                WHERE slot=1 AND active=1 AND owner_root=? AND operation_id=? AND token=?""",
                (time.time(), owner_root, operation_id, token))
            return cursor.rowcount == 1

    def fence_unstarted(self, owner_root, operation_id, token) -> bool:
        """CAS proves no dispatch can have happened under this permit."""
        with self.connect() as db:
            cursor = db.execute("""UPDATE heavy_slot SET phase='FENCED_UNSTARTED',updated_at=?
                WHERE slot=1 AND active=1 AND owner_root=? AND operation_id=? AND token=?
                AND phase IN ('RESERVED','FENCED_UNSTARTED')""",
                (time.time(), owner_root, operation_id, token))
            return cursor.rowcount == 1

    def _fence_verified_prelaunch_dispatch(self, owner_root, operation_id, token, generation, validator):
        """仅可信控制端在锁内重验完整未启动证据；普通未启动门保持不变。"""
        if not callable(validator):
            raise ValueError("prelaunch dispatch requires a trusted evidence validator")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if (not self._match(row, owner_root, operation_id, token)
                    or row["phase"] != "DISPATCHING" or row["process_json"] is not None
                    or int(row["generation"]) != generation or row["cancel_requested"]):
                raise SchedulerBusy("prelaunch dispatch evidence no longer matches")
            if validator(dict(row)) is not None:
                raise ValueError("trusted prelaunch validator must raise on unproved evidence")
            cursor = db.execute("""UPDATE heavy_slot SET phase='FENCED_UNSTARTED',updated_at=?
                WHERE slot=1 AND active=1 AND owner_root=? AND operation_id=? AND token=?
                AND generation=? AND phase='DISPATCHING' AND process_json IS NULL AND cancel_requested=0""",
                (time.time(), owner_root, operation_id, token, generation))
            if cursor.rowcount != 1:
                raise SchedulerBusy("prelaunch dispatch CAS failed")
            return True

    def release(self, owner_root, operation_id, token, *, stopped=False, unstarted=False) -> bool:
        # These facts are supplied only by controller code after observation,
        # never through graph MCP arguments or a user/model assertion.
        if stopped is not True and unstarted is not True:
            raise ValueError("release requires observed stop or fenced non-dispatch")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if not self._match(row, owner_root, operation_id, token):
                return False
            if not stopped and row["phase"] != "FENCED_UNSTARTED":
                raise ValueError("unstarted release requires a fenced launch permit")
            if stopped:
                fact = dict(row)
                fact["observed_stopped"] = True
                db.execute("INSERT OR IGNORE INTO stopped_attempts VALUES(?,?,?,?)",
                           (owner_root, operation_id, token, json.dumps(fact, sort_keys=True)))
            db.execute("UPDATE heavy_slot SET active=0,phase='RELEASED',updated_at=? WHERE slot=1",
                       (time.time(),))
            return True

    def retry_unstarted(self, owner_root, operation_id, token) -> dict[str, Any]:
        """Rotate an explicitly fenced, never-dispatched attempt atomically."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if (not self._match(row, owner_root, operation_id, token)
                    or row["phase"] != "FENCED_UNSTARTED" or row["cancel_requested"]):
                raise SchedulerBusy("only a proven unstarted attempt may resume")
            generation, new_token = int(row["generation"]) + 1, secrets.token_hex(32)
            db.execute("""UPDATE heavy_slot SET generation=?,token=?,phase='RESERVED',
                cancel_requested=0,process_json=NULL,updated_at=? WHERE slot=1""",
                (generation, new_token, time.time()))
            return {"generation": generation, "token": new_token}

    def fence_rotated_unstarted(self, owner_root, operation_id, old_generation):
        """Repair only a retry-permit commit whose local token write was lost.

        A dispatched/newer-unrelated permit is never adopted or replayed.
        Fencing precedes local adoption, so a racing old launcher cannot run.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heavy_slot WHERE slot=1").fetchone()
            if (not row or not row["active"] or row["owner_root"] != owner_root
                    or row["operation_id"] != operation_id
                    or int(row["generation"]) != old_generation + 1
                    or row["phase"] not in {"RESERVED", "FENCED_UNSTARTED"}
                    or row["process_json"] is not None):
                return None
            db.execute("UPDATE heavy_slot SET phase='FENCED_UNSTARTED',updated_at=? WHERE slot=1", (time.time(),))
            return {"generation": row["generation"], "token": row["token"],
                    "cancel_requested": row["cancel_requested"]}

    def register_legacy(self, owner_root, operation_id):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO legacy_blockers VALUES(?,?,1)", (owner_root, operation_id))

    def release_legacy(self, owner_root, operation_id, *, stopped=False):
        if stopped is not True:
            raise ValueError("legacy release requires observed process stop")
        with self.connect() as db:
            db.execute("UPDATE legacy_blockers SET active=0 WHERE owner_root=? AND operation_id=?",
                       (owner_root, operation_id))
