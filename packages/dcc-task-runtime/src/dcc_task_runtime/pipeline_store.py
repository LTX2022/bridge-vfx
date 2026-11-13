"""SQLite persistence for v2 tasks, artifacts, approvals, and experiences."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Optional
from uuid import uuid4

from .canonical import canonical_json, canonical_sha256, json_value
from .contracts import ArtifactRecord, TaskSpecV2
from .errors import RuntimeV2Error
from .models import ErrorCode, TaskState, now_iso


V2_STATE_TRANSITIONS: Mapping[TaskState, frozenset[TaskState]] = {
    TaskState.QUEUED: frozenset({TaskState.ANALYZING, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.ANALYZING: frozenset({TaskState.PREVIEWING, TaskState.DIAGNOSING, TaskState.AWAITING_INPUT, TaskState.UNSUPPORTED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.PREVIEWING: frozenset({TaskState.DIAGNOSING, TaskState.CANDIDATES_READY, TaskState.DIAGNOSIS_INCONCLUSIVE, TaskState.AWAITING_INPUT, TaskState.PARTIAL, TaskState.UNSUPPORTED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.DIAGNOSING: frozenset({TaskState.CANDIDATES_READY, TaskState.DIAGNOSIS_INCONCLUSIVE, TaskState.AWAITING_INPUT, TaskState.UNSUPPORTED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.CANDIDATES_READY: frozenset({TaskState.PREVIEWING, TaskState.AWAITING_CACHE_APPROVAL, TaskState.VERIFYING, TaskState.APPROVAL_REVOKED, TaskState.PARTIAL, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.AWAITING_CACHE_APPROVAL: frozenset({TaskState.CACHING, TaskState.APPROVAL_REVOKED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.CACHING: frozenset({TaskState.VERIFYING, TaskState.APPROVAL_REVOKED, TaskState.PARTIAL, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.VERIFYING: frozenset({TaskState.AWAITING_EXPERIENCE_APPROVAL, TaskState.COMPLETED, TaskState.CANDIDATES_READY, TaskState.DIAGNOSING, TaskState.APPROVAL_REVOKED, TaskState.PARTIAL, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.AWAITING_EXPERIENCE_APPROVAL: frozenset({TaskState.COMPLETED, TaskState.APPROVAL_REVOKED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.APPROVAL_REVOKED: frozenset({TaskState.CANDIDATES_READY, TaskState.AWAITING_CACHE_APPROVAL, TaskState.AWAITING_EXPERIENCE_APPROVAL, TaskState.CANCELLED}),
    TaskState.AWAITING_INPUT: frozenset({TaskState.ANALYZING, TaskState.PREVIEWING, TaskState.DIAGNOSING, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.DIAGNOSIS_INCONCLUSIVE: frozenset({TaskState.DIAGNOSING, TaskState.AWAITING_INPUT, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.PARTIAL: frozenset({TaskState.CACHING, TaskState.APPROVAL_REVOKED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.UNSUPPORTED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class _ClosingSQLiteConnection(sqlite3.Connection):
    """Make the existing ``with self._connect()`` calls close file handles."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class PipelineStore:
    """A restart-safe store with idempotent task and approval writes."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0, factory=_ClosingSQLiteConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pipeline_tasks (
                    task_id TEXT PRIMARY KEY,
                    spec_json TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pipeline_events (
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    message TEXT NOT NULL,
                    error_code TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, seq),
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS pipeline_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS pipeline_records (
                    task_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, category, record_id),
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS skill_execution_claims (
                    task_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    owner_token TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'COMPLETED')),
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (task_id, idempotency_key),
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    subject_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (task_id, scope, subject_hash),
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS approval_grants (
                    grant_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (request_id) REFERENCES approval_requests(request_id) ON DELETE CASCADE,
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS approval_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    grant_id TEXT,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE,
                    FOREIGN KEY (request_id) REFERENCES approval_requests(request_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS final_acceptances (
                    task_id TEXT NOT NULL,
                    verified_result_hash TEXT NOT NULL,
                    repair_case_hash TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    approval_grant_id TEXT NOT NULL UNIQUE,
                    accepted_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, verified_result_hash, repair_case_hash),
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE,
                    FOREIGN KEY (approval_grant_id) REFERENCES approval_grants(grant_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS repair_experiences (
                    experience_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    domain_id TEXT NOT NULL,
                    domain_version TEXT NOT NULL,
                    issue_signature TEXT NOT NULL,
                    cause_family TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES pipeline_tasks(task_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_experience_exact_domain
                    ON repair_experiences(domain_id, domain_version, issue_signature);
                """
            )

    def skill_execution_receipt(self, task_id: str, idempotency_key: str) -> Optional[dict[str, Any]]:
        """Read a durable result without exposing the execution owner's token."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, request_hash, result_json FROM skill_execution_claims WHERE task_id = ? AND idempotency_key = ?",
                (task_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return {"status": row["status"], "request_hash": row["request_hash"], "result": json.loads(row["result_json"]) if row["result_json"] else None}

    def claim_skill_execution(self, task_id: str, idempotency_key: str, request_hash: str, owner_token: str) -> dict[str, Any]:
        """Atomically reserve a model action before any side effect is dispatched.

        A leftover RUNNING claim is deliberately not stealable: after a crash we
        cannot know whether the external DCC accepted the request, so retrying it
        would risk duplicating a side effect.
        """
        timestamp = now_iso()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM skill_execution_claims WHERE task_id = ? AND idempotency_key = ?",
                (task_id, idempotency_key),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO skill_execution_claims(task_id, idempotency_key, request_hash, owner_token, status, created_at) VALUES (?, ?, ?, ?, 'RUNNING', ?)",
                    (task_id, idempotency_key, request_hash, owner_token, timestamp),
                )
                return {"outcome": "ACQUIRED", "status": "RUNNING"}
            if row["request_hash"] != request_hash:
                raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "idempotency key is bound to a different SkillIR selection")
            if row["status"] == "COMPLETED":
                return {"outcome": "COMPLETED", "status": "COMPLETED", "result": json.loads(row["result_json"])}
            return {"outcome": "IN_DOUBT", "status": "RUNNING"}

    def complete_skill_execution(
        self,
        task_id: str,
        idempotency_key: str,
        request_hash: str,
        owner_token: str,
        result: Mapping[str, Any],
    ) -> None:
        """CAS a reservation to COMPLETED; only its original owner may commit."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE skill_execution_claims SET status = 'COMPLETED', result_json = ?, completed_at = ? "
                "WHERE task_id = ? AND idempotency_key = ? AND request_hash = ? AND owner_token = ? AND status = 'RUNNING'",
                (canonical_json(result), now_iso(), task_id, idempotency_key, request_hash, owner_token),
            )
            if cursor.rowcount != 1:
                raise RuntimeV2Error(ErrorCode.POLICY_DENIED, "skill execution reservation was lost or already completed")

    def create_task(self, spec: TaskSpecV2 | Mapping[str, Any], idempotency_key: Optional[str] = None) -> str:
        parsed = spec if isinstance(spec, TaskSpecV2) else TaskSpecV2.from_mapping(spec)
        key = idempotency_key or parsed.idempotency_key
        payload = parsed.to_dict()
        spec_hash = canonical_sha256(payload)
        timestamp = now_iso()
        with self._lock, self._connect() as connection:
            if key:
                existing = connection.execute("SELECT task_id, spec_hash FROM pipeline_tasks WHERE idempotency_key = ?", (key,)).fetchone()
                if existing:
                    if existing["spec_hash"] != spec_hash:
                        raise RuntimeV2Error(ErrorCode.INVALID_SPEC, "idempotency key is already bound to a different task spec")
                    return str(existing["task_id"])
            task_id = uuid4().hex
            connection.execute(
                "INSERT INTO pipeline_tasks(task_id, spec_json, spec_hash, state, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, canonical_json(payload), spec_hash, TaskState.QUEUED.value, key, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO pipeline_events(task_id, seq, state, message, error_code, payload_json, created_at) VALUES (?, 1, ?, ?, NULL, ?, ?)",
                (task_id, TaskState.QUEUED.value, "task created", "{}", timestamp),
            )
            return task_id

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM pipeline_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        return {
            "task_id": row["task_id"],
            "spec": json.loads(row["spec_json"]),
            "spec_hash": row["spec_hash"],
            "state": row["state"],
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def status(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        event_rows = self.events(task_id)
        latest = event_rows[-1] if event_rows else {}
        return {
            "task_id": task_id,
            "state": task["state"],
            "seq": latest.get("seq", 0),
            "message": latest.get("message"),
            "error_code": latest.get("error_code"),
            "updated_at": task["updated_at"],
        }

    def transition(
        self,
        task_id: str,
        state: TaskState | str,
        message: str = "",
        error_code: Optional[ErrorCode | str] = None,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        refresh_message: bool = False,
    ) -> dict[str, Any]:
        target = state if isinstance(state, TaskState) else TaskState(state)
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT state FROM pipeline_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            current = TaskState(row["state"])
            if current == target:
                if not refresh_message:
                    return self.status(task_id)
                # A changed construction projection can have the same state
                # (e.g. unknown -> failed candidate). Keep its diagnosis durable
                # without inventing an otherwise illegal state transition.
                latest = connection.execute(
                    "SELECT message, error_code, payload_json FROM pipeline_events WHERE task_id=? ORDER BY seq DESC LIMIT 1",
                    (task_id,),
                ).fetchone()
                rendered_error = error_code.value if isinstance(error_code, ErrorCode) else error_code
                if latest and tuple(latest) == (message or target.value, rendered_error, canonical_json(payload or {})):
                    return self.status(task_id)
            allowed = V2_STATE_TRANSITIONS.get(current, frozenset())
            if target != current and target not in allowed:
                raise RuntimeV2Error(
                    ErrorCode.INVALID_TRANSITION,
                    f"invalid task transition: {current.value} -> {target.value}",
                    {"current": current.value, "target": target.value},
                )
            seq = int(connection.execute("SELECT COALESCE(MAX(seq), 0) FROM pipeline_events WHERE task_id = ?", (task_id,)).fetchone()[0]) + 1
            timestamp = now_iso()
            rendered_error = error_code.value if isinstance(error_code, ErrorCode) else error_code
            connection.execute("UPDATE pipeline_tasks SET state = ?, updated_at = ? WHERE task_id = ?", (target.value, timestamp, task_id))
            connection.execute(
                "INSERT INTO pipeline_events(task_id, seq, state, message, error_code, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, seq, target.value, message or target.value, rendered_error, canonical_json(payload or {}), timestamp),
            )
        return self.status(task_id)

    def events(self, task_id: str, after_seq: int = 0) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT seq, state, message, error_code, payload_json, created_at FROM pipeline_events WHERE task_id = ? AND seq > ? ORDER BY seq",
                (task_id, int(after_seq)),
            ).fetchall()
        return tuple(
            {
                "seq": int(row["seq"]),
                "state": row["state"],
                "message": row["message"],
                "error_code": row["error_code"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def save_result(self, task_id: str, result: Mapping[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            if not connection.execute("SELECT 1 FROM pipeline_tasks WHERE task_id = ?", (task_id,)).fetchone():
                raise KeyError(task_id)
            connection.execute(
                "UPDATE pipeline_tasks SET result_json = ?, updated_at = ? WHERE task_id = ?",
                (canonical_json(result), now_iso(), task_id),
            )

    def result(self, task_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT result_json FROM pipeline_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        return json.loads(row["result_json"]) if row["result_json"] else None

    def add_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO pipeline_artifacts(artifact_id, task_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (artifact.artifact_id, artifact.task_id, canonical_json(artifact.to_dict()), artifact.created_at),
            )
        return artifact

    def artifacts(self, task_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload_json FROM pipeline_artifacts WHERE task_id = ? ORDER BY created_at, artifact_id", (task_id,)).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    def put_record(self, task_id: str, category: str, record_id: str, payload: Mapping[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO pipeline_records(task_id, category, record_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id, category, record_id) DO UPDATE SET payload_json = excluded.payload_json",
                (task_id, category, record_id, canonical_json(payload), now_iso()),
            )

    def records(self, task_id: str, category: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM pipeline_records WHERE task_id = ? AND category = ? ORDER BY created_at, record_id",
                (task_id, category),
            ).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    # Approval and experience services use the following persistence primitives.

    def create_approval_request(self, task_id: str, scope: str, subject_hash: str, subject: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM approval_requests WHERE task_id = ? AND scope = ? AND subject_hash = ?",
                (task_id, scope, subject_hash),
            ).fetchone()
            if existing:
                rendered = self._approval_request_row(existing)
                if rendered["status"] == "REVOKED":
                    timestamp = now_iso()
                    connection.execute(
                        "UPDATE approval_requests SET status = 'PENDING', created_at = ? WHERE request_id = ?",
                        (timestamp, rendered["request_id"]),
                    )
                    connection.execute(
                        "INSERT INTO approval_events(event_id, task_id, request_id, grant_id, action, payload_json, created_at) VALUES (?, ?, ?, NULL, 'REQUEST_REOPENED', ?, ?)",
                        (uuid4().hex, task_id, rendered["request_id"], canonical_json({"subject_hash": subject_hash}), timestamp),
                    )
                    rendered.update({"status": "PENDING", "created_at": timestamp})
                return rendered
            request_id = uuid4().hex
            timestamp = now_iso()
            connection.execute(
                "INSERT INTO approval_requests(request_id, task_id, scope, subject_hash, subject_json, status, created_at) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)",
                (request_id, task_id, scope, subject_hash, canonical_json(subject), timestamp),
            )
            connection.execute(
                "INSERT INTO approval_events(event_id, task_id, request_id, grant_id, action, payload_json, created_at) VALUES (?, ?, ?, NULL, 'REQUEST_CREATED', ?, ?)",
                (uuid4().hex, task_id, request_id, canonical_json({"subject_hash": subject_hash}), timestamp),
            )
            return {
                "request_id": request_id,
                "task_id": task_id,
                "scope": scope,
                "subject_hash": subject_hash,
                "subject": json_value(subject),
                "status": "PENDING",
                "created_at": timestamp,
            }

    def get_approval_request(self, request_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not row:
            raise KeyError(request_id)
        return self._approval_request_row(row)

    def approval_requests(self, task_id: str, scope: Optional[str] = None) -> tuple[dict[str, Any], ...]:
        query = "SELECT * FROM approval_requests WHERE task_id = ?"
        params: tuple[Any, ...] = (task_id,)
        if scope is not None:
            query += " AND scope = ?"
            params += (scope,)
        query += " ORDER BY created_at, request_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(self._approval_request_row(row) for row in rows)

    def create_approval_grant(self, request: Mapping[str, Any], principal_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT * FROM approval_grants WHERE request_id = ?", (request["request_id"],)).fetchone()
            if existing:
                return self._approval_grant_row(existing)
            grant_id = uuid4().hex
            timestamp = now_iso()
            connection.execute(
                "INSERT INTO approval_grants(grant_id, request_id, task_id, scope, subject_hash, principal_id, status, granted_at) VALUES (?, ?, ?, ?, ?, ?, 'GRANTED', ?)",
                (grant_id, request["request_id"], request["task_id"], request["scope"], request["subject_hash"], principal_id, timestamp),
            )
            connection.execute("UPDATE approval_requests SET status = 'GRANTED' WHERE request_id = ?", (request["request_id"],))
            connection.execute(
                "INSERT INTO approval_events(event_id, task_id, request_id, grant_id, action, payload_json, created_at) VALUES (?, ?, ?, ?, 'GRANT_CREATED', ?, ?)",
                (uuid4().hex, request["task_id"], request["request_id"], grant_id, canonical_json({"principal_id": principal_id}), timestamp),
            )
            return {
                "grant_id": grant_id,
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "scope": request["scope"],
                "subject_hash": request["subject_hash"],
                "principal_id": principal_id,
                "status": "GRANTED",
                "granted_at": timestamp,
                "revoked_at": None,
            }

    def reactivate_approval_grant(self, grant_id: str, principal_id: str) -> dict[str, Any]:
        """Re-authorize a previously revoked exact subject after a new proof.

        The stable request/grant identifiers remain idempotent, while the
        append-only approval event preserves the fact that this is a separate
        human authorization after revocation.
        """

        timestamp = now_iso()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT request_id, task_id, status FROM approval_grants WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
            if not row:
                raise KeyError(grant_id)
            if row["status"] != "REVOKED":
                return self.get_approval_grant(grant_id)
            connection.execute(
                "UPDATE approval_grants SET status = 'GRANTED', principal_id = ?, granted_at = ?, revoked_at = NULL WHERE grant_id = ?",
                (principal_id, timestamp, grant_id),
            )
            connection.execute(
                "UPDATE approval_requests SET status = 'GRANTED' WHERE request_id = ?",
                (row["request_id"],),
            )
            connection.execute(
                "INSERT INTO approval_events(event_id, task_id, request_id, grant_id, action, payload_json, created_at) VALUES (?, ?, ?, ?, 'GRANT_REAUTHORIZED', ?, ?)",
                (uuid4().hex, row["task_id"], row["request_id"], grant_id, canonical_json({"principal_id": principal_id}), timestamp),
            )
        return self.get_approval_grant(grant_id)

    def get_approval_grant(self, grant_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM approval_grants WHERE grant_id = ?", (grant_id,)).fetchone()
        if not row:
            raise KeyError(grant_id)
        return self._approval_grant_row(row)

    def grant_for_request(self, request_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM approval_grants WHERE request_id = ?", (request_id,)).fetchone()
        return self._approval_grant_row(row) if row else None

    def active_grants(self, task_id: str, scope: Optional[str] = None) -> tuple[dict[str, Any], ...]:
        query = "SELECT * FROM approval_grants WHERE task_id = ? AND status = 'GRANTED'"
        params: tuple[Any, ...] = (task_id,)
        if scope is not None:
            query += " AND scope = ?"
            params += (scope,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(self._approval_grant_row(row) for row in rows)

    def revoke_grant(self, grant_id: str) -> dict[str, Any]:
        timestamp = now_iso()
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT request_id, task_id FROM approval_grants WHERE grant_id = ?", (grant_id,)).fetchone()
            if not row:
                raise KeyError(grant_id)
            connection.execute("UPDATE approval_grants SET status = 'REVOKED', revoked_at = ? WHERE grant_id = ?", (timestamp, grant_id))
            connection.execute("UPDATE approval_requests SET status = 'REVOKED' WHERE request_id = ?", (row["request_id"],))
            connection.execute(
                "INSERT INTO approval_events(event_id, task_id, request_id, grant_id, action, payload_json, created_at) VALUES (?, ?, ?, ?, 'GRANT_REVOKED', '{}', ?)",
                (uuid4().hex, row["task_id"], row["request_id"], grant_id, timestamp),
            )
        return self.get_approval_grant(grant_id)

    def approval_events(self, task_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT request_id, grant_id, action, payload_json, created_at FROM approval_events WHERE task_id = ? ORDER BY created_at, event_id",
                (task_id,),
            ).fetchall()
        return tuple(
            {
                "request_id": row["request_id"],
                "grant_id": row["grant_id"],
                "action": row["action"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def record_final_acceptance(
        self,
        task_id: str,
        verified_result_hash: str,
        repair_case_hash: str,
        principal_id: str,
        approval_grant_id: str,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO final_acceptances(task_id, verified_result_hash, repair_case_hash, principal_id, approval_grant_id, accepted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, verified_result_hash, repair_case_hash, principal_id, approval_grant_id, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM final_acceptances WHERE task_id = ? AND verified_result_hash = ? AND repair_case_hash = ?",
                (task_id, verified_result_hash, repair_case_hash),
            ).fetchone()
        return dict(row)

    def final_acceptance(self, task_id: str, verified_result_hash: str, repair_case_hash: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM final_acceptances WHERE task_id = ? AND verified_result_hash = ? AND repair_case_hash = ?",
                (task_id, verified_result_hash, repair_case_hash),
            ).fetchone()
        return dict(row) if row else None

    def add_experience(
        self,
        experience_id: str,
        task_id: str,
        domain_id: str,
        domain_version: str,
        issue_signature: str,
        cause_family: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        content_hash = canonical_sha256(payload)
        with self._lock, self._connect() as connection:
            existing = connection.execute("SELECT payload_json FROM repair_experiences WHERE content_hash = ?", (content_hash,)).fetchone()
            if existing:
                return json.loads(existing["payload_json"])
            connection.execute(
                "INSERT INTO repair_experiences(experience_id, task_id, domain_id, domain_version, issue_signature, cause_family, content_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (experience_id, task_id, domain_id, domain_version, issue_signature, cause_family, content_hash, canonical_json(payload), now_iso()),
            )
        return json.loads(canonical_json(payload))

    def find_experiences(self, domain_id: str, domain_version: str, issue_signature: Optional[str] = None) -> tuple[dict[str, Any], ...]:
        query = "SELECT payload_json FROM repair_experiences WHERE domain_id = ? AND domain_version = ?"
        params: tuple[Any, ...] = (domain_id, domain_version)
        if issue_signature:
            query += " AND issue_signature = ?"
            params += (issue_signature,)
        query += " ORDER BY created_at DESC, experience_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    @staticmethod
    def _approval_request_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "task_id": row["task_id"],
            "scope": row["scope"],
            "subject_hash": row["subject_hash"],
            "subject": json.loads(row["subject_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _approval_grant_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "grant_id": row["grant_id"],
            "request_id": row["request_id"],
            "task_id": row["task_id"],
            "scope": row["scope"],
            "subject_hash": row["subject_hash"],
            "principal_id": row["principal_id"],
            "status": row["status"],
            "granted_at": row["granted_at"],
            "revoked_at": row["revoked_at"],
        }
