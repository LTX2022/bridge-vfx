from __future__ import annotations

import sqlite3
import hashlib
import hmac
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from dcc_task_runtime.knowledge import ClaimCandidate, HipIngestionContract, SourceIdentity, TrustTier, TrustedHumanApproval, VerificationRecord
from dcc_task_runtime.knowledge_store import KnowledgeIntegrityError, KnowledgePromotionError, KnowledgeStore


def source(version: str = "21.0") -> SourceIdentity:
    return SourceIdentity("official-h21", "official_document", "sidefx://docs/h21/pyro", "a" * 64, version, ("pyro/parameters#voxel-size",))


def candidate(version: str = "1.0.0", needs_dcc: bool = True) -> ClaimCandidate:
    return ClaimCandidate("claim-1", "pyro_smoke_v1", version, "Smaller voxels can preserve spatial detail.", source(), ("page:pyro/parameters#voxel-size",), needs_dcc)


def verification(item: ClaimCandidate, deterministic: bool = True, dcc: bool = True, human: bool = True, version: str | None = None) -> VerificationRecord:
    return VerificationRecord(item.candidate_id, item.content_hash, item.source.identity_hash, version or item.domain_version, deterministic, dcc, human, "artist", ("artifact:runtime-probe",))


class KnowledgePlaneTests(unittest.TestCase):
    SECRET = b"trusted-test-human-key"

    def make_store(self, directory: str) -> KnowledgeStore:
        return KnowledgeStore(Path(directory) / "knowledge.sqlite3", trusted_human_keys={"artist-key": self.SECRET})

    def approve(self, store: KnowledgeStore, item: ClaimCandidate, *, principal: str = "artist") -> TrustedHumanApproval:
        request = store.request_human_approval(item.candidate_id)
        values = {
            "approval_id": "approval-1", "request_id": request["request_id"],
            "candidate_id": item.candidate_id, "candidate_hash": item.content_hash,
            "principal_id": principal, "key_id": "artist-key", "approved_at": "2026-09-02T00:00:00+00:00",
        }
        signed = {**values, "scope": "knowledge_card_promotion"}
        signature = hmac.new(self.SECRET, json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        return store.put_human_approval(TrustedHumanApproval(**values, signature=signature))

    def test_source_hash_and_citation_are_mandatory(self) -> None:
        with self.assertRaises(ValueError):
            SourceIdentity("bad", "note", "file://note", "not-a-hash", "1", ("line:1",))
        with self.assertRaises(ValueError):
            SourceIdentity("bad", "note", "file://note", "a" * 64, "1", ())

    def test_promotion_requires_deterministic_dcc_and_human_gates(self) -> None:
        for deterministic, dcc in ((False, True), (True, False)):
            with self.subTest(deterministic=deterministic, dcc=dcc), tempfile.TemporaryDirectory() as directory:
                store = self.make_store(directory)
                item = store.put_candidate(candidate())
                store.put_verification(verification(item, deterministic, dcc, True))
                approval = self.approve(store, item)
                with self.assertRaises(KnowledgePromotionError):
                    store.promote(item.candidate_id, approval_id=approval.approval_id)

    def test_non_dcc_claim_still_requires_deterministic_and_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            item = store.put_candidate(candidate(needs_dcc=False))
            store.put_verification(verification(item, dcc=False))
            approval = self.approve(store, item)
            self.assertEqual(store.promote(item.candidate_id, approval_id=approval.approval_id).candidate_id, item.candidate_id)

    def test_cross_version_and_forged_source_verification_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            item = store.put_candidate(candidate())
            with self.assertRaises(KnowledgeIntegrityError):
                store.put_verification(verification(item, version="2.0.0"))
            forged = VerificationRecord(item.candidate_id, item.content_hash, "b" * 64, item.domain_version, True, True, True, "artist", ("artifact:x",))
            with self.assertRaises(KnowledgeIntegrityError):
                store.put_verification(forged)

    def test_writes_are_idempotent_but_identity_rebinding_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            item = candidate()
            self.assertEqual(store.put_candidate(item), store.put_candidate(item))
            changed = ClaimCandidate(item.candidate_id, item.domain_id, item.domain_version, "A different claim.", item.source, item.evidence_refs)
            with self.assertRaises(KnowledgeIntegrityError):
                store.put_candidate(changed)
            record = verification(item)
            store.put_verification(record)
            store.put_verification(record)
            approval = self.approve(store, item)
            first = store.promote(item.candidate_id, "card-1", approval_id=approval.approval_id)
            self.assertEqual(store.promote(item.candidate_id, "card-1", approval_id=approval.approval_id), first)

    def test_verifier_flags_cannot_forge_human_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            item = store.put_candidate(candidate())
            store.put_verification(verification(item, human=True))
            with self.assertRaises(KnowledgePromotionError):
                store.promote(item.candidate_id)

    def test_forged_or_untrusted_human_approval_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            item = store.put_candidate(candidate())
            request = store.request_human_approval(item.candidate_id)
            forged = TrustedHumanApproval("a1", request["request_id"], item.candidate_id, item.content_hash, "artist", "artist-key", "2026-09-02T00:00:00+00:00", "0" * 64)
            with self.assertRaises(KnowledgePromotionError):
                store.put_human_approval(forged)

    def test_database_payload_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.sqlite3"
            store = KnowledgeStore(path)
            item = store.put_candidate(candidate())
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE knowledge_candidates SET payload_json = replace(payload_json, 'Smaller', 'Larger') WHERE candidate_id = ?", (item.candidate_id,))
            with self.assertRaises(KnowledgeIntegrityError):
                store.get_candidate(item.candidate_id)

    def test_hip_contract_defaults_safe_and_never_allows_arbitrary_code(self) -> None:
        default = HipIngestionContract()
        self.assertEqual(default.trust_tier, TrustTier.METADATA_ONLY)
        self.assertFalse(default.permits_runtime_load)
        for tier in TrustTier:
            self.assertFalse(HipIngestionContract(tier).permits_arbitrary_code)
        self.assertTrue(HipIngestionContract(TrustTier.ISOLATED_RUNTIME).requires_disposable_runtime)
        self.assertTrue(HipIngestionContract(TrustTier.TRUSTED_LIVE).permits_runtime_load)

    def test_knowledge_schema_is_separate_from_repair_experience(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.sqlite3"
            KnowledgeStore(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual(tables, {"knowledge_candidates", "knowledge_verifications", "knowledge_cards", "knowledge_approval_requests", "knowledge_human_approvals"})


if __name__ == "__main__":
    unittest.main()
