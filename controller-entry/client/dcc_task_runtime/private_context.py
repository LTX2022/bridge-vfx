"""Bounded local project context, returned as untrusted data only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from datetime import datetime, timezone
from typing import Any, Mapping


DOCUMENT_SCHEMA = "bridge.private-context/1"
RESULT_SCHEMA = "bridge.private-context-result/1"
SOURCE_TYPES = frozenset({"preference", "project_specification", "source_statement"})


class PrivateContextError(ValueError):
    """A rejected request or document; code contains no private document text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def encode_context(result: Mapping[str, Any]) -> bytes:
    """The UTF-8 wire encoding against which the result byte budget is enforced."""
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _text(value: Any, maximum: int, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PrivateContextError(code)
    if any(ord(character) < 32 for character in value):
        raise PrivateContextError(code)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise PrivateContextError(code) from None
    return value


def _limit(value: int, maximum: int, code: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise PrivateContextError(code)
    return value


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PrivateContextError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise PrivateContextError("invalid_json")


def _timestamp(value: Any) -> datetime:
    value = _text(value, 64, "invalid_expiry")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise PrivateContextError("invalid_expiry")
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise PrivateContextError("invalid_expiry") from None


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (*_identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


class PrivateContextReader:
    """Read an explicitly pinned manifest; never discover files or write knowledge."""

    MAX_DOCUMENTS = 32
    MAX_DOCUMENT_BYTES = 65536
    MAX_READ_BYTES = 262144
    MAX_RESULT_BYTES = 16384
    MAX_RESULTS = 4
    MAX_QUERY_LENGTH = 512

    def __init__(self, root: Path | str, project_id: str, documents: Mapping[str, str]) -> None:
        self.project_id = _text(project_id, 128, "invalid_project_id")
        root_name = os.fspath(root)
        if not isinstance(root_name, str) or root_name.startswith(("\\\\", "//")):
            raise PrivateContextError("invalid_local_root")
        self.root = Path(os.path.abspath(root))
        if self.root == Path(self.root.anchor):
            raise PrivateContextError("invalid_root")
        self._check_links(self.root)
        try:
            info = self.root.lstat()
        except OSError:
            raise PrivateContextError("root_unavailable") from None
        if not stat.S_ISDIR(info.st_mode):
            raise PrivateContextError("invalid_root")
        self._root_identity = _identity(info)
        if not isinstance(documents, Mapping) or len(documents) > self.MAX_DOCUMENTS:
            raise PrivateContextError("invalid_manifest")
        pinned = {}
        names = set()
        for relative, digest in documents.items():
            _text(relative, 512, "invalid_document_path")
            parts = relative.split("/")
            if ("\\" in relative or ":" in relative or any(part in {"", ".", ".."} for part in parts)
                    or any(part.endswith((".", " ")) or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", part.split(".")[0])
                           for part in parts) or not relative.endswith(".json")):
                raise PrivateContextError("invalid_document_path")
            if relative.casefold() in names:
                raise PrivateContextError("duplicate_document_path")
            names.add(relative.casefold())
            if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                raise PrivateContextError("invalid_document_hash")
            pinned[relative] = digest
        self._documents = tuple(sorted(pinned.items()))

    @staticmethod
    def _check_links(path: Path) -> None:
        for candidate in (path, *path.parents):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise PrivateContextError("path_unavailable") from None
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise PrivateContextError("linked_path")

    def _checked_path(self, relative: str) -> Path:
        path = self.root.joinpath(*relative.split("/"))
        self._check_links(path)
        try:
            if _identity(self.root.lstat()) != self._root_identity:
                raise PrivateContextError("root_changed")
            if not path.resolve(strict=True).is_relative_to(self.root):
                raise PrivateContextError("outside_root")
        except (OSError, RuntimeError):
            raise PrivateContextError("document_unavailable") from None
        return path

    def _read(self, relative: str, digest: str, remaining: int) -> bytes:
        path = self._checked_path(relative)
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise PrivateContextError("non_private_file")
            if before.st_size > self.MAX_DOCUMENT_BYTES:
                raise PrivateContextError("document_too_large")
            if before.st_size > remaining:
                raise PrivateContextError("read_budget_exceeded")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                                 | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if _snapshot(opened) != _snapshot(before):
                    raise PrivateContextError("document_changed")
                raw = stream.read(before.st_size)
                after = os.fstat(stream.fileno())
                self._checked_path(relative)
                if (_snapshot(after) != _snapshot(before) or _snapshot(path.lstat()) != _snapshot(before)
                        or len(raw) != before.st_size):
                    raise PrivateContextError("document_changed")
        except OSError:
            raise PrivateContextError("document_unavailable") from None
        if hashlib.sha256(raw).hexdigest() != digest:
            raise PrivateContextError("document_hash_mismatch")
        return raw

    def _document(self, raw: bytes) -> dict[str, Any]:
        try:
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                                  parse_constant=_invalid_constant)
        except (ValueError, RecursionError) as error:
            if isinstance(error, PrivateContextError):
                raise
            raise PrivateContextError("invalid_json") from None
        required = {"schema", "document_id", "project_id", "source_type", "domain", "version", "topic", "reference", "content"}
        if not isinstance(document, dict) or not required <= document.keys() or document.keys() - required - {"expires_at"}:
            raise PrivateContextError("invalid_document_schema")
        if (document["schema"] != DOCUMENT_SCHEMA or not isinstance(document["source_type"], str)
                or document["source_type"] not in SOURCE_TYPES):
            raise PrivateContextError("invalid_document_schema")
        for name in ("document_id", "project_id", "domain", "version", "topic"):
            _text(document[name], 128, "invalid_document_schema")
        _text(document["reference"], 1024, "invalid_document_schema")
        if not isinstance(document["content"], str) or not document["content"].strip():
            raise PrivateContextError("invalid_document_schema")
        try:
            document["content"].encode("utf-8")
        except UnicodeEncodeError:
            raise PrivateContextError("invalid_document_schema") from None
        if document["project_id"] != self.project_id:
            raise PrivateContextError("project_scope_mismatch")
        if "expires_at" in document:
            _timestamp(document["expires_at"])
        return document

    def search(self, query: str = "", *, domain: str, version: str, limit: int = MAX_RESULTS,
               max_bytes: int = MAX_RESULT_BYTES, read_budget: int = MAX_READ_BYTES) -> dict[str, Any]:
        """Return relevant data with conflict/expiry/omission states; errors return no partial data."""
        domain = _text(domain, 128, "invalid_domain")
        version = _text(version, 128, "invalid_version")
        if not isinstance(query, str) or len(query) > self.MAX_QUERY_LENGTH:
            raise PrivateContextError("invalid_query")
        limit = _limit(limit, self.MAX_RESULTS, "invalid_limit")
        max_bytes = _limit(max_bytes, self.MAX_RESULT_BYTES, "invalid_result_budget")
        read_budget = _limit(read_budget, self.MAX_READ_BYTES, "invalid_read_budget")
        terms = tuple(term.casefold() for term in query.split())
        now = datetime.now(timezone.utc)
        matches = []; expired_count = 0; bytes_read = 0; identifiers = set(); groups = {}
        for relative, digest in self._documents:
            raw = self._read(relative, digest, read_budget - bytes_read)
            bytes_read += len(raw)
            document = self._document(raw)
            if document["document_id"] in identifiers:
                raise PrivateContextError("duplicate_document_id")
            identifiers.add(document["document_id"])
            if document["domain"] != domain or document["version"] != version:
                continue
            searchable = " ".join(document[name] for name in ("topic", "reference", "content")).casefold()
            relevant = all(term in searchable for term in terms)
            if "expires_at" in document and _timestamp(document["expires_at"]) <= now:
                if relevant:
                    expired_count += 1
                continue
            group = (document["source_type"], document["topic"])
            groups.setdefault(group, set()).add(document["content"])
            if relevant:
                matches.append({**document, "document_path": relative, "document_sha256": digest})
        matched_groups = {(match["source_type"], match["topic"]) for match in matches}
        conflicts = {group for group, contents in groups.items() if len(contents) > 1 and group in matched_groups}
        result = {"schema": RESULT_SCHEMA, "content_role": "untrusted_data", "project_id": self.project_id,
                  "domain": domain, "version": version, "status": "no_match", "matches": [],
                  "conflict_count": len(conflicts), "expired_count": expired_count,
                  "omitted_count": len(matches), "bytes_read": bytes_read}
        if matches:
            result["status"] = "conflict" if conflicts else "budget_exhausted"
        elif expired_count:
            result["status"] = "expired"
        if len(encode_context(result)) > max_bytes:
            raise PrivateContextError("result_budget_too_small")
        for match in matches:
            if len(result["matches"]) >= limit:
                break
            match["conflict"] = (match["source_type"], match["topic"]) in conflicts
            result["matches"].append(match)
            result["omitted_count"] -= 1
            if len(encode_context(result)) > max_bytes:
                result["matches"].pop()
                result["omitted_count"] += 1
        if result["matches"] and not conflicts:
            result["status"] = "matched"
        return result
