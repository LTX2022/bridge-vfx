#!/usr/bin/env python3
"""Audit installed Houdini help archives without importing or launching Houdini.

Documentation facts identify documented operator names and parameter IDs only.
They are kept separate from HDA interface facts, port semantics, and execution.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import platform
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import native_install_paths as native_paths
if getattr(native_paths, '__file__', None) is None or Path(native_paths.__file__).resolve() != (TOOLS/'native_install_paths.py').resolve():
    raise ValueError('locator source does not match reviewed file')
SUPPORTED_BUILDS = native_paths.SUPPORTED_BUILDS
DEFAULT_BUILDS = native_paths.DEFAULT_BUILDS
resource_directory = native_paths.resource_directory
_REDIRECT = re.compile(r"^#redirect:\s*(\S+)\s*$", re.MULTILINE)
_INCLUDE = re.compile(r":include\s+([^\s#:]+)(?:#([^:\s]+))?:")
_VERSION_RE = re.compile(r"::\d+(?:\.\d+)*$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative_doc_path(reference: str) -> str | None:
    """Convert a help reference to an archive-relative path without traversal."""
    reference = reference.replace("\\", "/")
    if reference.startswith("/nodes/"):
        reference = reference[len("/nodes/"):]
    else:
        reference = reference.lstrip("/")
    parts = PurePosixPath(reference).parts
    if not parts or any(part in ("..", "") for part in parts):
        return None
    if any("\x00" in part for part in parts):
        return None
    path = "/".join(part for part in parts if part != ".")
    return path if path and not path.startswith("/") else None


def _resolve_doc_reference(current_entry: str, reference: str, docs: dict[str, bytes]) -> str | None:
    """Resolve a vendor help include/redirect only to a member in nodes.zip."""
    clean = _safe_relative_doc_path(reference)
    if clean is None:
        return None
    if not clean.endswith(".txt"):
        clean += ".txt"
    candidates = []
    if not reference.startswith("/"):
        candidates.append(f"{PurePosixPath(current_entry).parent}/{clean}")
    candidates.append(clean)
    for candidate in candidates:
        normalized = str(PurePosixPath(candidate))
        if normalized in docs:
            return normalized
    return None


def _extract_include_fragment(text: str, anchor: str) -> str | None:
    """Extract a #id, named heading, or parameters block used by a help include."""
    anchor = anchor.rstrip("/")
    lines = text.splitlines(keepends=True)
    start = None
    anchor_indent = 0
    end = len(lines)
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)#id:\s*(\S+)\s*$", line.rstrip("\r\n"))
        if match and match.group(2) == anchor:
            start = index
            anchor_indent = len(match.group(1).expandtabs(8))
            break
    if start is None:
        heading = re.compile(r"^(=+)\s+.*?\s+\(\s*" + re.escape(anchor) + r"\s*\)\s*$")
        for index, line in enumerate(lines):
            match = heading.match(line.rstrip("\r\n"))
            if match:
                start = index
                level = len(match.group(1))
                for end_index in range(index + 1, len(lines)):
                    next_heading = re.match(r"^(=+)\s+", lines[end_index])
                    if next_heading and len(next_heading.group(1)) <= level:
                        end = end_index
                        break
                break
    if start is None:
        parameter_block = re.compile(r"^\s*parameters\s+id=[\"']" + re.escape(anchor) + r"[\"']\s*>>\s*$")
        for index, line in enumerate(lines):
            if parameter_block.match(line.rstrip("\r\n")):
                start = index
                for end_index in range(index + 1, len(lines)):
                    if re.match(r"^\s*parameters\s+id=", lines[end_index]) or re.match(r"^=+\s+", lines[end_index]):
                        end = end_index
                        break
                break
    if start is None:
        return None
    if anchor_indent:
        for index in range(start + 1, end):
            line = lines[index]
            if line.strip() == ":box:":
                end = index
                break
            match = re.match(r"^(\s*)#id:\s*\S+\s*$", line.rstrip("\r\n"))
            if match and len(match.group(1).expandtabs(8)) <= anchor_indent:
                end = index
                break
    return "".join(lines[start:end])


def _expand_doc_entry(entry: str, docs: dict[str, bytes], *, stack: tuple[str, ...] = ()) -> dict[str, object]:
    """Expand redirects/includes with cycle and path checks; return static source facts."""
    if entry in stack:
        return {
            "text": "",
            "sources": [],
            "unresolved": [{"code": "DOCUMENT_REFERENCE_CYCLE", "entry": entry, "chain": [*stack, entry]}],
        }
    if len(stack) >= 64:
        return {
            "text": "",
            "sources": [],
            "unresolved": [{"code": "DOCUMENT_REFERENCE_DEPTH_LIMIT", "entry": entry, "chain": list(stack)}],
        }
    raw = docs.get(entry)
    if raw is None:
        return {"text": "", "sources": [], "unresolved": [{"code": "DOCUMENT_ENTRY_MISSING", "entry": entry}]}
    text = raw.decode("utf-8", errors="replace")
    source = {"entry": entry, "sha256": _sha256(raw)}
    chain = (*stack, entry)

    redirect = _REDIRECT.search(text)
    if redirect:
        reference = redirect.group(1)
        target = _resolve_doc_reference(entry, reference, docs)
        if target is None:
            return {
                "text": "",
                "sources": [source],
                "unresolved": [{"code": "DOCUMENT_REDIRECT_TARGET_UNRESOLVED", "entry": entry, "reference": reference}],
            }
        expanded = _expand_doc_entry(target, docs, stack=chain)
        expanded["sources"] = [source, *expanded["sources"]]
        expanded["redirect_chain"] = [entry, *expanded.get("redirect_chain", [target])]
        return expanded

    sources: list[dict[str, str]] = [source]
    unresolved: list[dict[str, object]] = []
    pieces: list[str] = []
    cursor = 0
    for include in _INCLUDE.finditer(text):
        pieces.append(text[cursor:include.start()])
        cursor = include.end()
        reference, anchor = include.group(1), include.group(2)
        target = _resolve_doc_reference(entry, reference, docs)
        if target is None:
            unresolved.append({
                "code": "DOCUMENT_INCLUDE_TARGET_UNRESOLVED",
                "entry": entry,
                "reference": reference,
                "anchor": anchor,
            })
            continue
        target_text = docs[target].decode("utf-8", errors="replace")
        if anchor:
            fragment = _extract_include_fragment(target_text, anchor)
            if fragment is None:
                unresolved.append({
                    "code": "DOCUMENT_INCLUDE_ANCHOR_UNRESOLVED",
                    "entry": entry,
                    "reference": reference,
                    "resolved_entry": target,
                    "anchor": anchor.rstrip("/"),
                })
                continue
        else:
            fragment = target_text
        expanded = _expand_doc_text(target, fragment, docs, stack=chain)
        pieces.append(str(expanded["text"]))
        sources.extend(expanded["sources"])
        unresolved.extend(expanded["unresolved"])
    pieces.append(text[cursor:])
    return {
        "text": "".join(pieces),
        "sources": _unique_sources(sources),
        "unresolved": unresolved,
        "redirect_chain": [entry],
    }


def _expand_doc_text(entry: str, text: str, docs: dict[str, bytes], *, stack: tuple[str, ...]) -> dict[str, object]:
    """Expand includes in an already selected fragment, retaining the source entry."""
    marker = f"{entry}#fragment"
    if marker in stack:
        return {
            "text": "",
            "sources": [],
            "unresolved": [{"code": "DOCUMENT_REFERENCE_CYCLE", "entry": entry, "chain": [*stack, marker]}],
        }
    # Reuse the same include walker without re-reading or re-expanding the whole entry.
    return _expand_fragment_in_text(entry, text, docs, stack=(*stack, marker))


def _expand_fragment_in_text(entry: str, text: str, docs: dict[str, bytes], *, stack: tuple[str, ...]) -> dict[str, object]:
    sources: list[dict[str, str]] = []
    unresolved: list[dict[str, object]] = []
    pieces: list[str] = []
    cursor = 0
    for include in _INCLUDE.finditer(text):
        pieces.append(text[cursor:include.start()])
        cursor = include.end()
        reference, anchor = include.group(1), include.group(2)
        target = _resolve_doc_reference(entry, reference, docs)
        if target is None:
            unresolved.append({"code": "DOCUMENT_INCLUDE_TARGET_UNRESOLVED", "entry": entry, "reference": reference, "anchor": anchor})
            continue
        target_text = docs[target].decode("utf-8", errors="replace")
        if anchor:
            fragment = _extract_include_fragment(target_text, anchor)
            if fragment is None:
                unresolved.append({"code": "DOCUMENT_INCLUDE_ANCHOR_UNRESOLVED", "entry": entry, "reference": reference, "resolved_entry": target, "anchor": anchor.rstrip("/")})
                continue
        else:
            fragment = target_text
        expanded = _expand_doc_text(target, fragment, docs, stack=stack)
        pieces.append(str(expanded["text"]))
        sources.extend(expanded["sources"])
        unresolved.extend(expanded["unresolved"])
    pieces.append(text[cursor:])
    if entry in docs:
        sources.append({"entry": entry, "sha256": _sha256(docs[entry])})
    return {"text": "".join(pieces), "sources": _unique_sources(sources), "unresolved": unresolved}


def _unique_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for source in sources:
        identity = (source.get("entry", ""), source.get("sha256", ""))
        if identity not in seen:
            seen.add(identity)
            result.append(source)
    return result


def _load_help_docs(archive: zipfile.ZipFile) -> tuple[dict[str, bytes], dict[tuple[str, str], list[str]]]:
    docs: dict[str, bytes] = {}
    index: dict[tuple[str, str], list[str]] = {}
    for name in archive.namelist():
        if not name.endswith(".txt"):
            continue
        raw = archive.read(name)
        docs[name] = raw
        text = raw.decode("utf-8", errors="replace")
        internal = re.search(r"^#internal:\s*(\S+)", text, re.MULTILINE)
        context = re.search(r"^#context:\s*(\S+)", text, re.MULTILINE)
        if internal and context:
            index.setdefault((context.group(1), internal.group(1)), []).append(name)
    return docs, index


def _matching_doc_entries_for(category: str, candidate: str, doc_index: dict[tuple[str, str], list[str]]) -> list[str]:
    entries: set[str] = set()
    for key in (candidate, _VERSION_RE.sub("", candidate)):
        entries.update(doc_index.get((category, key), []))
    return sorted(entries)


def _documented_control_ids(aliases: tuple[str, ...], candidate_ids: dict[str, set[str]], candidate_has_docs: dict[str, bool]) -> dict[str, object]:
    by_candidate = {candidate: sorted(set(aliases) & ids) for candidate, ids in candidate_ids.items()}
    common = set.intersection(*(set(values) for values in by_candidate.values())) if by_candidate else set()
    all_documented = bool(by_candidate) and all(candidate_has_docs.get(candidate, False) for candidate in by_candidate)
    documented = sorted(common) if all_documented else []
    status = "EXACT_ID_DOCUMENTED_FOR_ALL_CANDIDATES" if documented else (
        "CANDIDATE_SPECIFIC_ONLY" if any(by_candidate.values()) else "EXACT_ID_NOT_FOUND"
    )
    return {
        "documented_aliases": documented,
        "documented_aliases_by_candidate": by_candidate,
        "status": status,
    }


def audit(install_root=Path('/Applications/Houdini'), *, layout="macos", versions=DEFAULT_BUILDS):
    native_paths.require_local_module(native_paths, TOOLS/'native_install_paths.py')
    source = ROOT/'packages/houdini-bridge/src/houdini_bridge/domain_packs.py'
    package_root = str(source.parent.parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    from houdini_bridge import domain_packs as catalog
    native_paths.require_local_module(catalog, source)
    result = {
        'schema': 'bridge.native_documentation_audit/2.0',
        'source_sha256': _sha256(source.read_bytes()),
        'source_path': str(Path(catalog.__file__).resolve()),
        'evidence_kind': 'installed_vendor_documentation',
        'capture_metadata': {
            'captured_at_utc': datetime.now(timezone.utc).isoformat(),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'tool_path': str(Path(__file__).resolve()),
            'tool_sha256': _sha256(Path(__file__).read_bytes()),
            'install_root': str(install_root),
            'install_layout': layout,
            'requested_builds': list(versions),
            'locator_sha256': _sha256((TOOLS/'native_install_paths.py').read_bytes()),
            'locator_path': str(Path(native_paths.__file__).resolve()),
            'scope': 'read-only parsing of installed Houdini help/nodes.zip; no Houdini process or native operation was executed',
        },
        'real_dcc_executed': False,
        'native_execution': False,
        'versions': {},
    }
    for version in versions:
        archive = resource_directory(install_root,version,layout=layout)/'help/nodes.zip'
        if not archive.is_file():
            result['versions'][version] = {'status': 'BLOCKED', 'reason': 'DOCUMENT_ARCHIVE_MISSING', 'path': str(archive)}
            continue
        archive_bytes = archive.read_bytes()
        with zipfile.ZipFile(BytesIO(archive_bytes)) as zf:
            docs, doc_index = _load_help_docs(zf)
        domains = {}
        for pack in catalog.all_domain_packs():
            nodes = []
            unresolved = []
            for node in pack.nodes:
                candidate_facts = []
                candidate_ids: dict[str, set[str]] = {}
                candidate_has_docs: dict[str, bool] = {}
                node_unresolved = []
                for candidate in node.type_candidates:
                    entries = _matching_doc_entries_for(node.category, candidate, doc_index)
                    candidate_has_docs[candidate] = bool(entries)
                    ids_for_candidate: set[str] = set()
                    documents = []
                    for entry in entries:
                        expanded = _expand_doc_entry(entry, docs)
                        text = str(expanded['text'])
                        resolved_sources = expanded['sources']
                        ids = set(re.findall(r'^\s*#id:\s*(\S+)', text, re.MULTILINE))
                        ids_for_candidate.update(ids)
                        documents.append({
                            'entry': entry,
                            'sha256': _sha256(docs[entry]),
                            'resolved_sources': resolved_sources,
                            'redirect_chain': expanded.get('redirect_chain', [entry]),
                            'documented_ids': sorted(ids),
                        })
                        node_unresolved.extend(expanded['unresolved'])
                    candidate_ids[candidate] = ids_for_candidate
                    candidate_facts.append({
                        'candidate': candidate,
                        'node_fact_status': 'DOCUMENTED_NAME' if entries else 'NOT_FOUND_IN_DOCUMENTATION',
                        'documents': documents,
                        'documented_ids': sorted(ids_for_candidate),
                    })
                    if not entries:
                        unresolved.append({
                            'role': node.role,
                            'candidate': candidate,
                            'category': node.category,
                            'code': 'DOCUMENTED_NODE_CANDIDATE_NOT_FOUND',
                        })
                documents = [doc for candidate in candidate_facts for doc in candidate['documents']]
                every_candidate_documented = bool(candidate_facts) and all(candidate_has_docs.values())
                all_ids = set.intersection(*(ids for ids in candidate_ids.values())) if every_candidate_documented else set()
                controls = []
                for control in pack.controls:
                    if control.node_role != node.role or control.application != 'houdini':
                        continue
                    control_fact = _documented_control_ids(control.parameter_aliases, candidate_ids, candidate_has_docs)
                    matched = control_fact['documented_aliases']
                    controls.append({
                        'control': control.identifier,
                        'aliases': list(control.parameter_aliases),
                        **control_fact,
                    })
                    if not matched:
                        unresolved.append({
                            'role': node.role,
                            'control': control.identifier,
                            'aliases': list(control.parameter_aliases),
                            'documented_aliases_by_candidate': control_fact['documented_aliases_by_candidate'],
                            'code': 'PARAMETER_ID_NOT_COMMON_TO_ALL_CANDIDATES',
                        })
                unresolved.extend({**item, 'role': node.role} for item in node_unresolved)
                nodes.append({
                    'role': node.role,
                    'category': node.category,
                    'type_candidates': list(node.type_candidates),
                    'node_fact_status': 'DOCUMENTED_NAME' if every_candidate_documented else ('DOCUMENTED_NAME_PARTIAL_CANDIDATE_COVERAGE' if any(candidate_has_docs.values()) else 'NOT_FOUND_IN_DOCUMENTATION'),
                    'candidate_facts': candidate_facts,
                    'documents': documents,
                    'documented_ids': sorted(all_ids),
                    'controls': controls,
                })
            domains[pack.identifier] = {
                'status': 'DOCUMENTED_NODE_FACTS_WITH_GAPS' if unresolved else 'DOCUMENTED_NAMES_AND_IDS',
                'nodes': nodes,
                'unresolved': unresolved,
                'topology_validated': False,
                'parameter_values_validated': False,
                'port_semantics_validated': False,
                'native_execution': False,
            }
        result['versions'][version] = {
            'archive': str(archive),
            'archive_size_bytes': len(archive_bytes),
            'archive_sha256': _sha256(archive_bytes),
            'domains': domains,
        }
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--install-root',type=Path,default=Path('/Applications/Houdini'))
    p.add_argument('--install-layout',choices=('macos','windows'),default='macos')
    p.add_argument('--build',choices=SUPPORTED_BUILDS,action='append')
    a=p.parse_args()
    native_paths.validate_output_path(a.output)
    r=audit(a.install_root,layout=a.install_layout,versions=tuple(a.build or DEFAULT_BUILDS))
    native_paths.write_new_output(a.output,r)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
