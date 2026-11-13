from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from dcc_task_runtime.knowledge import ClaimCandidate, KnowledgeCard, SourceIdentity, TrustedHumanApproval, VerificationRecord
from dcc_task_runtime.knowledge_store import KnowledgeIntegrityError, KnowledgeStore


SECRET = b"retrieval-test-human-key"


def _source(index: int) -> SourceIdentity:
    return SourceIdentity(
        source_id=f"source-{index}",
        source_type="official_document",
        source_uri=f"sidefx://docs/pyro/{index}",
        source_sha256=f"{index:064x}",
        source_version="1.0",
        citations=(f"pyro/section/{index}",),
    )


def _candidate(index: int, *, source: SourceIdentity | None = None, domain: str = "pyro", version: str = "1.0") -> ClaimCandidate:
    return ClaimCandidate(
        candidate_id=f"task-{index}",
        domain_id=domain,
        domain_version=version,
        claim=f"Smoke plume detail {index}",
        source=source or _source(index),
        evidence_refs=(f"evidence:{index}",),
        requires_dcc_verification=False,
    )


def _promote(store: KnowledgeStore, item: ClaimCandidate) -> KnowledgeCard:
    store.put_candidate(item)
    record = VerificationRecord(
        candidate_id=item.candidate_id,
        candidate_hash=item.content_hash,
        source_identity_hash=item.source.identity_hash,
        domain_version=item.domain_version,
        deterministic_verified=True,
        dcc_verified=False,
        human_promoted=True,
        verifier_id="deterministic-test",
        evidence_refs=(f"artifact:{item.candidate_id}",),
    )
    store.put_verification(record)
    request = store.request_human_approval(item.candidate_id)
    values = {
        "approval_id": f"approval-{item.candidate_id}",
        "request_id": request["request_id"],
        "candidate_id": item.candidate_id,
        "candidate_hash": item.content_hash,
        "principal_id": "artist",
        "key_id": "artist-key",
        "approved_at": "2026-09-07T00:00:00+00:00",
    }
    signed = {**values, "scope": "knowledge_card_promotion"}
    signature = hmac.new(
        SECRET,
        json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    store.put_human_approval(TrustedHumanApproval(**values, signature=signature))
    return store.promote(item.candidate_id, card_id=f"card-{item.candidate_id}", approval_id=f"approval-{item.candidate_id}")


class KnowledgeRetrievalTests(unittest.TestCase):
    def make_store(self, directory: str) -> KnowledgeStore:
        return KnowledgeStore(Path(directory) / "knowledge.sqlite3", trusted_human_keys={"artist-key": SECRET})

    def test_search_is_validated_bounded_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            for index in (4, 2, 5, 1, 3):
                _promote(store, _candidate(index))
            _promote(store, _candidate(20, domain="material", version="2.0"))

            cards = store.search("smoke", limit=4, domain="pyro", version="1.0")
            self.assertEqual(tuple(card.card_id for card in cards), tuple(f"card-task-{index}" for index in (1, 2, 3, 4)))
            self.assertEqual(store.search("plume", limit=1, task="detail 5")[0].candidate_id, "task-5")
            self.assertEqual(store.search("", limit=1, task_id="task-20")[0].domain_id, "material")
            self.assertEqual(
                tuple(card.candidate_id for card in store.search("smoke", limit=4, domain_id="material", domain_version="2.0")),
                ("task-20",),
            )
            with self.assertRaises(ValueError):
                store.search("smoke", limit=5)
            with self.assertRaises(ValueError):
                store.search("smoke", limit=0)
            with self.assertRaises(ValueError):
                store.search("smoke", domain="pyro", domain_id="material")

    def test_revocation_is_explicit_idempotent_and_excludes_future_and_existing_cards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            source = _source(31)
            revoked_card = _promote(store, _candidate(31, source=source))
            kept_card = _promote(store, _candidate(32))
            before = store.card_for_candidate(revoked_card.candidate_id)
            self.assertIsNotNone(before)

            entry = store.revoke_source(source.identity_hash, "source was withdrawn")
            self.assertEqual(entry["source_identity_hash"], source.identity_hash)
            self.assertEqual(tuple(card.candidate_id for card in store.search("smoke", limit=4)), (kept_card.candidate_id,))
            self.assertEqual(store.card_for_candidate(revoked_card.candidate_id), before)

            future = _promote(store, _candidate(33, source=source))
            self.assertEqual(tuple(card.candidate_id for card in store.search("smoke", limit=4)), (kept_card.candidate_id,))
            repeated = store.revoke_source(source.identity_hash.upper(), "  source was withdrawn  ")
            self.assertEqual(repeated, entry)
            with self.assertRaises(KnowledgeIntegrityError):
                store.revoke_source(source.identity_hash, "a different reason")
            self.assertEqual(store.card_for_candidate(future.candidate_id), future)

            with closing(sqlite3.connect(Path(directory) / "knowledge.sqlite3")) as connection, connection:
                row = connection.execute(
                    "SELECT source_identity_hash, reason, revoked_at, record_hash FROM knowledge_source_revocations"
                ).fetchone()
            self.assertEqual(row[0], source.identity_hash)
            self.assertEqual(row[1], "source was withdrawn")
            self.assertEqual(len(row[3]), 64)

            restarted = self.make_store(directory)
            self.assertEqual(tuple(card.candidate_id for card in restarted.search("smoke", limit=4)), (kept_card.candidate_id,))

    def test_tampered_revocation_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            source = _source(41)
            _promote(store, _candidate(41, source=source))
            store.revoke_source(source.identity_hash, "bad citation")
            with closing(sqlite3.connect(Path(directory) / "knowledge.sqlite3")) as connection, connection:
                connection.execute(
                    "UPDATE knowledge_source_revocations SET reason = ? WHERE source_identity_hash = ?",
                    ("changed after the fact", source.identity_hash),
                )
            with self.assertRaises(KnowledgeIntegrityError):
                store.search("smoke", limit=4)


if __name__ == "__main__":
    unittest.main()
