"""Contracts for a provenance-first, non-executing knowledge plane."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _require_digest(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower()):
        raise ValueError(f"{name} must be a SHA-256 hex digest")


class TrustTier(str, Enum):
    """Execution trust for user-supplied HIP knowledge sources."""

    METADATA_ONLY = "metadata_only"
    ISOLATED_RUNTIME = "isolated_runtime"
    TRUSTED_LIVE = "trusted_live"


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str
    source_type: str
    source_uri: str
    source_sha256: str
    source_version: str
    citations: tuple[str, ...]
    trust_tier: TrustTier = TrustTier.METADATA_ONLY

    def __post_init__(self) -> None:
        if not all((self.source_id, self.source_type, self.source_uri, self.source_version)):
            raise ValueError("source identity fields must not be empty")
        _require_digest(self.source_sha256, "source_sha256")
        if not self.citations or any(not citation.strip() for citation in self.citations):
            raise ValueError("at least one non-empty source citation is required")

    @property
    def identity_hash(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256.lower(),
            "source_version": self.source_version,
            "citations": list(self.citations),
            "trust_tier": self.trust_tier.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceIdentity":
        return cls(
            source_id=str(value["source_id"]),
            source_type=str(value["source_type"]),
            source_uri=str(value["source_uri"]),
            source_sha256=str(value["source_sha256"]),
            source_version=str(value["source_version"]),
            citations=tuple(str(item) for item in value["citations"]),
            trust_tier=TrustTier(str(value.get("trust_tier", TrustTier.METADATA_ONLY.value))),
        )


@dataclass(frozen=True)
class ClaimCandidate:
    candidate_id: str
    domain_id: str
    domain_version: str
    claim: str
    source: SourceIdentity
    evidence_refs: tuple[str, ...]
    requires_dcc_verification: bool = True
    created_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if not all((self.candidate_id, self.domain_id, self.domain_version, self.claim.strip())):
            raise ValueError("candidate identity, domain, version, and claim are required")
        if not self.evidence_refs or any(not item.strip() for item in self.evidence_refs):
            raise ValueError("candidate must cite at least one evidence reference")

    @property
    def content_hash(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "domain_id": self.domain_id,
            "domain_version": self.domain_version,
            "claim": self.claim,
            "source": self.source.to_dict(),
            "evidence_refs": list(self.evidence_refs),
            "requires_dcc_verification": self.requires_dcc_verification,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimCandidate":
        return cls(
            candidate_id=str(value["candidate_id"]),
            domain_id=str(value["domain_id"]),
            domain_version=str(value["domain_version"]),
            claim=str(value["claim"]),
            source=SourceIdentity.from_dict(value["source"]),
            evidence_refs=tuple(str(item) for item in value["evidence_refs"]),
            requires_dcc_verification=bool(value.get("requires_dcc_verification", True)),
            created_at=str(value["created_at"]),
        )


@dataclass(frozen=True)
class VerificationRecord:
    candidate_id: str
    candidate_hash: str
    source_identity_hash: str
    domain_version: str
    deterministic_verified: bool
    dcc_verified: bool
    human_promoted: bool
    verifier_id: str
    evidence_refs: tuple[str, ...]
    verified_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        _require_digest(self.candidate_hash, "candidate_hash")
        _require_digest(self.source_identity_hash, "source_identity_hash")
        if not self.candidate_id or not self.domain_version or not self.verifier_id:
            raise ValueError("verification identity fields are required")
        if not self.evidence_refs:
            raise ValueError("verification evidence is required")

    @property
    def record_hash(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "source_identity_hash": self.source_identity_hash,
            "domain_version": self.domain_version,
            "deterministic_verified": self.deterministic_verified,
            "dcc_verified": self.dcc_verified,
            "human_promoted": self.human_promoted,
            "verifier_id": self.verifier_id,
            "evidence_refs": list(self.evidence_refs),
            "verified_at": self.verified_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationRecord":
        return cls(
            candidate_id=str(value["candidate_id"]),
            candidate_hash=str(value["candidate_hash"]),
            source_identity_hash=str(value["source_identity_hash"]),
            domain_version=str(value["domain_version"]),
            deterministic_verified=bool(value["deterministic_verified"]),
            dcc_verified=bool(value["dcc_verified"]),
            human_promoted=bool(value["human_promoted"]),
            verifier_id=str(value["verifier_id"]),
            evidence_refs=tuple(str(item) for item in value["evidence_refs"]),
            verified_at=str(value["verified_at"]),
        )


@dataclass(frozen=True)
class TrustedHumanApproval:
    """Detached, authenticated human authorization for one immutable claim."""

    approval_id: str
    request_id: str
    candidate_id: str
    candidate_hash: str
    principal_id: str
    key_id: str
    approved_at: str
    signature: str

    def __post_init__(self) -> None:
        if not all((self.approval_id, self.request_id, self.candidate_id, self.principal_id, self.key_id, self.approved_at)):
            raise ValueError("trusted human approval identity fields are required")
        _require_digest(self.candidate_hash, "candidate_hash")
        _require_digest(self.signature, "signature")

    def signed_payload(self) -> dict[str, str]:
        return {
            "approval_id": self.approval_id,
            "request_id": self.request_id,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "principal_id": self.principal_id,
            "key_id": self.key_id,
            "approved_at": self.approved_at,
            "scope": "knowledge_card_promotion",
        }

    def verify(self, secret: bytes) -> bool:
        expected = hmac.new(secret, _canonical(self.signed_payload()).encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.signature.lower())

    def to_dict(self) -> dict[str, str]:
        return {**self.signed_payload(), "signature": self.signature.lower()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrustedHumanApproval":
        if value.get("scope") not in (None, "knowledge_card_promotion"):
            raise ValueError("invalid trusted human approval scope")
        return cls(**{name: str(value[name]) for name in (
            "approval_id", "request_id", "candidate_id", "candidate_hash",
            "principal_id", "key_id", "approved_at", "signature",
        )})


@dataclass(frozen=True)
class KnowledgeCard:
    card_id: str
    candidate_id: str
    candidate_hash: str
    source_identity_hash: str
    domain_id: str
    domain_version: str
    claim: str
    verification_hash: str
    promoted_by: str
    approval_hash: str = ""
    created_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        _require_digest(self.candidate_hash, "candidate_hash")
        _require_digest(self.source_identity_hash, "source_identity_hash")
        _require_digest(self.verification_hash, "verification_hash")
        if self.approval_hash:
            _require_digest(self.approval_hash, "approval_hash")

    @property
    def content_hash(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "source_identity_hash": self.source_identity_hash,
            "domain_id": self.domain_id,
            "domain_version": self.domain_version,
            "claim": self.claim,
            "verification_hash": self.verification_hash,
            "promoted_by": self.promoted_by,
            "approval_hash": self.approval_hash,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KnowledgeCard":
        fields = {key: str(value[key]) for key in (
            "card_id", "candidate_id", "candidate_hash", "source_identity_hash",
            "domain_id", "domain_version", "claim", "verification_hash", "promoted_by", "created_at",
        )}
        fields["approval_hash"] = str(value.get("approval_hash") or "")
        return cls(**fields)


@dataclass(frozen=True)
class HipIngestionContract:
    trust_tier: TrustTier = TrustTier.METADATA_ONLY

    @property
    def permits_runtime_load(self) -> bool:
        return self.trust_tier in {TrustTier.ISOLATED_RUNTIME, TrustTier.TRUSTED_LIVE}

    @property
    def requires_disposable_runtime(self) -> bool:
        return self.trust_tier is TrustTier.ISOLATED_RUNTIME

    @property
    def permits_arbitrary_code(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trust_tier": self.trust_tier.value,
            "permits_runtime_load": self.permits_runtime_load,
            "requires_disposable_runtime": self.requires_disposable_runtime,
            "permits_arbitrary_code": False,
        }
