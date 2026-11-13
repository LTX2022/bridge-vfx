"""Tamper-evident SQLite persistence for knowledge candidates and cards."""

from __future__ import annotations

import json
import sqlite3
from .pipeline_store import _ClosingSQLiteConnection
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .knowledge import (
    ClaimCandidate,
    KnowledgeCard,
    TrustedHumanApproval,
    VerificationRecord,
    _canonical,
    _digest,
    _require_digest,
)


class KnowledgeIntegrityError(ValueError):
    pass


class KnowledgePromotionError(ValueError):
    pass


class KnowledgeStore:
    """An immutable knowledge ledger, deliberately separate from RepairExperience."""

    # Retrieval is intentionally small because its result is consumed by a
    # planner.  Callers may ask for fewer cards, but never for an unbounded
    # result set.
    MAX_SEARCH_RESULTS = 4
    MAX_SEARCH_QUERY_LENGTH = 512

    def __init__(self, path: Path | str, *, trusted_human_keys: dict[str, bytes] | None = None) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._trusted_human_keys = dict(trusted_human_keys or {})
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_verifications (
                    candidate_id TEXT PRIMARY KEY,
                    record_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES knowledge_candidates(candidate_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_cards (
                    card_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES knowledge_candidates(candidate_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_approval_requests (
                    request_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    candidate_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES knowledge_candidates(candidate_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_human_approvals (
                    approval_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL UNIQUE,
                    approval_hash TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES knowledge_approval_requests(request_id),
                    FOREIGN KEY(candidate_id) REFERENCES knowledge_candidates(candidate_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0, factory=_ClosingSQLiteConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _insert_immutable(connection: sqlite3.Connection, table: str, key_name: str, key: str, hash_name: str, digest: str, payload: str) -> None:
        row = connection.execute(f"SELECT {hash_name}, payload_json FROM {table} WHERE {key_name} = ?", (key,)).fetchone()
        if row:
            if row[hash_name] != digest or row["payload_json"] != payload:
                raise KnowledgeIntegrityError(f"{table} identity is already bound to different content")
            return
        connection.execute(
            f"INSERT INTO {table}({key_name}, {hash_name}, payload_json) VALUES (?, ?, ?)",
            (key, digest, payload),
        )

    def put_candidate(self, candidate: ClaimCandidate) -> ClaimCandidate:
        payload = _canonical(candidate.to_dict())
        with self._lock, self._connect() as connection:
            self._insert_immutable(connection, "knowledge_candidates", "candidate_id", candidate.candidate_id, "content_hash", candidate.content_hash, payload)
        return candidate

    def get_candidate(self, candidate_id: str) -> ClaimCandidate:
        with self._connect() as connection:
            row = connection.execute("SELECT content_hash, payload_json FROM knowledge_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            raise KeyError(candidate_id)
        candidate = ClaimCandidate.from_dict(json.loads(row["payload_json"]))
        if candidate.content_hash != row["content_hash"]:
            raise KnowledgeIntegrityError("candidate payload failed content hash verification")
        return candidate

    def put_verification(self, record: VerificationRecord) -> VerificationRecord:
        candidate = self.get_candidate(record.candidate_id)
        self._validate_binding(candidate, record)
        payload = _canonical(record.to_dict())
        with self._lock, self._connect() as connection:
            self._insert_immutable(connection, "knowledge_verifications", "candidate_id", record.candidate_id, "record_hash", record.record_hash, payload)
        return record

    def get_verification(self, candidate_id: str) -> VerificationRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT record_hash, payload_json FROM knowledge_verifications WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            raise KeyError(candidate_id)
        record = VerificationRecord.from_dict(json.loads(row["payload_json"]))
        if record.record_hash != row["record_hash"]:
            raise KnowledgeIntegrityError("verification payload failed content hash verification")
        self._validate_binding(self.get_candidate(candidate_id), record)
        return record

    @staticmethod
    def _validate_binding(candidate: ClaimCandidate, record: VerificationRecord) -> None:
        if record.candidate_hash != candidate.content_hash:
            raise KnowledgeIntegrityError("verification candidate hash does not match stored candidate")
        if record.source_identity_hash != candidate.source.identity_hash:
            raise KnowledgeIntegrityError("verification source identity does not match stored source")
        if record.domain_version != candidate.domain_version:
            raise KnowledgeIntegrityError("verification domain version does not match candidate")

    def request_human_approval(self, candidate_id: str) -> dict[str, str]:
        candidate = self.get_candidate(candidate_id)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM knowledge_approval_requests WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            if existing:
                if existing["candidate_hash"] != candidate.content_hash:
                    raise KnowledgeIntegrityError("approval request candidate hash mismatch")
                return dict(existing)
            request = {
                "request_id": uuid4().hex,
                "candidate_id": candidate_id,
                "candidate_hash": candidate.content_hash,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            connection.execute(
                "INSERT INTO knowledge_approval_requests(request_id, candidate_id, candidate_hash, created_at) VALUES (?, ?, ?, ?)",
                tuple(request.values()),
            )
            return request

    def put_human_approval(self, approval: TrustedHumanApproval) -> TrustedHumanApproval:
        secret = self._trusted_human_keys.get(approval.key_id)
        if secret is None or not approval.verify(secret):
            raise KnowledgePromotionError("trusted-human approval signature is invalid or key is not trusted")
        with self._lock, self._connect() as connection:
            request = connection.execute(
                "SELECT * FROM knowledge_approval_requests WHERE request_id = ?", (approval.request_id,)
            ).fetchone()
            if not request:
                raise KnowledgePromotionError("trusted-human approval has no persisted request")
            if request["candidate_id"] != approval.candidate_id or request["candidate_hash"] != approval.candidate_hash:
                raise KnowledgeIntegrityError("trusted-human approval does not match its persisted request")
            payload = _canonical(approval.to_dict())
            approval_hash = _digest(approval.to_dict())
            row = connection.execute(
                "SELECT approval_hash, payload_json FROM knowledge_human_approvals WHERE approval_id = ? OR request_id = ? OR candidate_id = ?",
                (approval.approval_id, approval.request_id, approval.candidate_id),
            ).fetchone()
            if row:
                if row["approval_hash"] != approval_hash or row["payload_json"] != payload:
                    raise KnowledgeIntegrityError("human approval identity is already bound to different content")
                return approval
            connection.execute(
                "INSERT INTO knowledge_human_approvals(approval_id, request_id, candidate_id, approval_hash, payload_json) VALUES (?, ?, ?, ?, ?)",
                (approval.approval_id, approval.request_id, approval.candidate_id, approval_hash, payload),
            )
        return approval

    def _get_human_approval(self, candidate_id: str, approval_id: str) -> tuple[TrustedHumanApproval, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT approval_hash, payload_json FROM knowledge_human_approvals WHERE candidate_id = ? AND approval_id = ?",
                (candidate_id, approval_id),
            ).fetchone()
        if not row:
            raise KnowledgePromotionError("a separate persisted trusted-human approval is required")
        approval = TrustedHumanApproval.from_dict(json.loads(row["payload_json"]))
        digest = _digest(approval.to_dict())
        secret = self._trusted_human_keys.get(approval.key_id)
        if digest != row["approval_hash"] or secret is None or not approval.verify(secret):
            raise KnowledgeIntegrityError("trusted-human approval failed integrity verification")
        return approval, digest

    def promote(self, candidate_id: str, card_id: str | None = None, *, approval_id: str | None = None) -> KnowledgeCard:
        candidate = self.get_candidate(candidate_id)
        record = self.get_verification(candidate_id)
        if not record.deterministic_verified:
            raise KnowledgePromotionError("deterministic verification is required")
        if candidate.requires_dcc_verification and not record.dcc_verified:
            raise KnowledgePromotionError("DCC verification is required for this candidate")
        if not approval_id:
            raise KnowledgePromotionError("a separate persisted trusted-human approval is required")
        approval, approval_hash = self._get_human_approval(candidate_id, approval_id)
        if approval.candidate_hash != candidate.content_hash:
            raise KnowledgeIntegrityError("trusted-human approval candidate hash is stale")
        existing = self.card_for_candidate(candidate_id)
        if existing:
            if card_id is not None and card_id != existing.card_id:
                raise KnowledgeIntegrityError("candidate is already bound to a different card id")
            return existing
        card = KnowledgeCard(
            card_id=card_id or uuid4().hex,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.content_hash,
            source_identity_hash=candidate.source.identity_hash,
            domain_id=candidate.domain_id,
            domain_version=candidate.domain_version,
            claim=candidate.claim,
            verification_hash=record.record_hash,
            promoted_by=approval.principal_id,
            approval_hash=approval_hash,
        )
        payload = _canonical(card.to_dict())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT card_id, candidate_id, content_hash, payload_json FROM knowledge_cards WHERE card_id = ? OR candidate_id = ?",
                (card.card_id, candidate_id),
            ).fetchone()
            if row:
                if row["card_id"] != card.card_id or row["candidate_id"] != candidate_id or row["content_hash"] != card.content_hash or row["payload_json"] != payload:
                    raise KnowledgeIntegrityError("knowledge card identity is already bound to different content")
            else:
                connection.execute(
                    "INSERT INTO knowledge_cards(card_id, candidate_id, content_hash, payload_json) VALUES (?, ?, ?, ?)",
                    (card.card_id, candidate_id, card.content_hash, payload),
                )
        return card

    def card_for_candidate(self, candidate_id: str) -> KnowledgeCard | None:
        with self._connect() as connection:
            row = connection.execute("SELECT content_hash, payload_json FROM knowledge_cards WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            return None
        card = KnowledgeCard.from_dict(json.loads(row["payload_json"]))
        if card.content_hash != row["content_hash"]:
            raise KnowledgeIntegrityError("knowledge card payload failed content hash verification")
        candidate = self.get_candidate(candidate_id)
        record = self.get_verification(candidate_id)
        approval, approval_hash = self._get_human_approval(candidate_id, self._approval_id_for_candidate(candidate_id))
        if card.candidate_hash != candidate.content_hash or card.source_identity_hash != candidate.source.identity_hash or card.verification_hash != record.record_hash or card.approval_hash != approval_hash or card.promoted_by != approval.principal_id:
            raise KnowledgeIntegrityError("knowledge card provenance chain is invalid")
        return card

    def _approval_id_for_candidate(self, candidate_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT approval_id FROM knowledge_human_approvals WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            raise KnowledgeIntegrityError("knowledge card has no trusted-human approval")
        return str(row["approval_id"])

    @staticmethod
    def _create_revocation_table(connection: sqlite3.Connection) -> None:
        """Create the audit ledger only when the first revocation is recorded.

        The original knowledge schema is intentionally left unchanged for
        existing databases.  Revocations are additive state: once used, the
        separate table persists and is read on every subsequent retrieval.
        """

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_source_revocations (
                source_identity_hash TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                revoked_at TEXT NOT NULL,
                record_hash TEXT NOT NULL UNIQUE
            )
            """
        )

    @staticmethod
    def _revocation_hash(source_identity_hash: str, reason: str, revoked_at: str) -> str:
        return _digest(
            {
                "source_identity_hash": source_identity_hash,
                "reason": reason,
                "revoked_at": revoked_at,
            }
        )

    @classmethod
    def _validate_revocation_row(cls, row: sqlite3.Row) -> None:
        source_identity_hash = str(row["source_identity_hash"])
        reason = str(row["reason"])
        revoked_at = str(row["revoked_at"])
        record_hash = str(row["record_hash"])
        try:
            _require_digest(source_identity_hash, "source_identity_hash")
            _require_digest(record_hash, "record_hash")
        except ValueError as error:
            raise KnowledgeIntegrityError("source revocation ledger contains an invalid digest") from error
        if not reason.strip() or not revoked_at.strip():
            raise KnowledgeIntegrityError("source revocation ledger contains an empty field")
        if record_hash != cls._revocation_hash(source_identity_hash.lower(), reason, revoked_at):
            raise KnowledgeIntegrityError("source revocation ledger failed integrity verification")

    @staticmethod
    def _revocation_table_exists(connection: sqlite3.Connection) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_source_revocations'"
        ).fetchone() is not None

    @classmethod
    def _source_is_revoked(cls, connection: sqlite3.Connection, source_identity_hash: str) -> bool:
        if not cls._revocation_table_exists(connection):
            return False
        row = connection.execute(
            "SELECT source_identity_hash, reason, revoked_at, record_hash FROM knowledge_source_revocations WHERE source_identity_hash = ?",
            (source_identity_hash.lower(),),
        ).fetchone()
        if row is None:
            return False
        cls._validate_revocation_row(row)
        return True

    def revoke_source(self, source_identity_hash: str, reason: str) -> dict[str, str]:
        """Persist an immutable revocation for one source identity hash.

        ``source_identity_hash`` is the hash already carried by
        :class:`KnowledgeCard` and :class:`VerificationRecord`; the source
        payloads are not rewritten.  Repeating the same revocation is
        idempotent.  Binding the hash to a different reason is rejected so
        the ledger cannot silently change its audit meaning.
        """

        if not isinstance(source_identity_hash, str):
            raise ValueError("source_identity_hash must be a SHA-256 hex digest")
        try:
            _require_digest(source_identity_hash, "source_identity_hash")
        except ValueError as error:
            raise KnowledgeIntegrityError(str(error)) from error
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("source revocation reason must not be empty")
        normalized_hash = source_identity_hash.lower()
        normalized_reason = reason.strip()
        with self._lock, self._connect() as connection:
            self._create_revocation_table(connection)
            existing = connection.execute(
                "SELECT source_identity_hash, reason, revoked_at, record_hash FROM knowledge_source_revocations WHERE source_identity_hash = ?",
                (normalized_hash,),
            ).fetchone()
            if existing is not None:
                self._validate_revocation_row(existing)
                if str(existing["reason"]) != normalized_reason:
                    raise KnowledgeIntegrityError("source revocation identity is already bound to a different reason")
                return {key: str(existing[key]) for key in existing.keys()}

            revoked_at = datetime.now(timezone.utc).isoformat()
            entry = {
                "source_identity_hash": normalized_hash,
                "reason": normalized_reason,
                "revoked_at": revoked_at,
                "record_hash": self._revocation_hash(normalized_hash, normalized_reason, revoked_at),
            }
            connection.execute(
                "INSERT INTO knowledge_source_revocations(source_identity_hash, reason, revoked_at, record_hash) VALUES (?, ?, ?, ?)",
                tuple(entry.values()),
            )
            return entry

    @staticmethod
    def _search_terms(value: str, name: str) -> tuple[str, ...]:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        if len(value) > KnowledgeStore.MAX_SEARCH_QUERY_LENGTH:
            raise ValueError(f"{name} exceeds the {KnowledgeStore.MAX_SEARCH_QUERY_LENGTH}-character limit")
        return tuple(part.casefold() for part in value.split() if part)

    @staticmethod
    def _search_text(card: KnowledgeCard, candidate: ClaimCandidate) -> str:
        source = candidate.source
        fields: list[str] = [
            card.card_id,
            card.candidate_id,
            card.domain_id,
            card.domain_version,
            card.claim,
            card.promoted_by,
            candidate.candidate_id,
            candidate.domain_id,
            candidate.domain_version,
            candidate.claim,
            source.source_id,
            source.source_type,
            source.source_uri,
            source.source_version,
            *source.citations,
            *candidate.evidence_refs,
        ]
        return " ".join(fields).casefold()

    @staticmethod
    def _validate_card_scope(card: KnowledgeCard, candidate: ClaimCandidate) -> None:
        # card_for_candidate verifies hashes and approval provenance.  These
        # declarations are also part of the immutable card and must remain
        # consistent with the candidate before they are used as filters.
        if (
            card.candidate_id != candidate.candidate_id
            or card.domain_id != candidate.domain_id
            or card.domain_version != candidate.domain_version
            or card.claim != candidate.claim
        ):
            raise KnowledgeIntegrityError("knowledge card declarations do not match its candidate")

    def search(
        self,
        query: str = "",
        limit: int = MAX_SEARCH_RESULTS,
        *,
        task: str | None = None,
        task_id: str | None = None,
        domain: str | None = None,
        version: str | None = None,
        domain_id: str | None = None,
        domain_version: str | None = None,
    ) -> tuple[KnowledgeCard, ...]:
        """Return at most four integrity-validated cards in stable order.

        The immutable contracts have no separate task metadata.  ``task_id``
        therefore filters the existing candidate/card identifiers exactly;
        ``task`` is an additional text query over existing card, candidate,
        source, claim, domain/version, and evidence fields.  ``domain`` and
        ``version`` are concise aliases for ``domain_id`` and
        ``domain_version``.
        """

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_SEARCH_RESULTS:
            raise ValueError(f"search limit must be between 1 and {self.MAX_SEARCH_RESULTS}")
        query_terms = self._search_terms(query, "query")
        task_terms = self._search_terms(task, "task") if task is not None else ()
        if task_id is not None and not isinstance(task_id, str):
            raise ValueError("task_id must be a string")
        if task_id is not None and len(task_id) > self.MAX_SEARCH_QUERY_LENGTH:
            raise ValueError(f"task_id exceeds the {self.MAX_SEARCH_QUERY_LENGTH}-character limit")
        if domain is not None and not isinstance(domain, str):
            raise ValueError("domain must be a string")
        if domain_id is not None and not isinstance(domain_id, str):
            raise ValueError("domain_id must be a string")
        if version is not None and not isinstance(version, str):
            raise ValueError("version must be a string")
        if domain_version is not None and not isinstance(domain_version, str):
            raise ValueError("domain_version must be a string")
        if domain is not None and domain_id is not None and domain != domain_id:
            raise ValueError("domain and domain_id must match when both are provided")
        if version is not None and domain_version is not None and version != domain_version:
            raise ValueError("version and domain_version must match when both are provided")
        requested_domain = domain_id if domain_id is not None else domain
        requested_version = domain_version if domain_version is not None else version
        if requested_domain is not None and not requested_domain:
            raise ValueError("domain filter must not be empty")
        if requested_version is not None and not requested_version:
            raise ValueError("version filter must not be empty")
        if task_id == "":
            raise ValueError("task_id must not be empty")

        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT candidate_id FROM knowledge_cards ORDER BY candidate_id ASC"
                ).fetchall()

            validated: list[tuple[KnowledgeCard, ClaimCandidate]] = []
            for row in rows:
                candidate_id = str(row["candidate_id"])
                card = self.card_for_candidate(candidate_id)
                if card is None:
                    # The row was selected from knowledge_cards, so a missing
                    # card is an integrity error rather than an empty result.
                    raise KnowledgeIntegrityError("knowledge card disappeared during retrieval")
                candidate = self.get_candidate(candidate_id)
                self._validate_card_scope(card, candidate)
                if requested_domain is not None and candidate.domain_id != requested_domain:
                    continue
                if requested_version is not None and candidate.domain_version != requested_version:
                    continue
                if task_id is not None and task_id not in {card.card_id, card.candidate_id, candidate.candidate_id}:
                    continue
                searchable = self._search_text(card, candidate)
                if any(term not in searchable for term in query_terms + task_terms):
                    continue
                with self._connect() as connection:
                    if self._source_is_revoked(connection, card.source_identity_hash):
                        continue
                validated.append((card, candidate))

            validated.sort(
                key=lambda item: (
                    item[0].domain_id.casefold(),
                    item[0].domain_version.casefold(),
                    item[0].card_id.casefold(),
                    item[0].candidate_id.casefold(),
                )
            )
            return tuple(card for card, _candidate in validated[:limit])
