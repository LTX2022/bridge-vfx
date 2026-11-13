"""Cross-software artifact registry: one factual ledger for rendered output.

Artifact classes are SEPARATE and never interchangeable:

``raw_input``        reference material that entered the task (never an output);
``preview_temp``     quick look previews, may be overwritten at any time;
``confirmed_cache``  simulation/render caches approved by the control plane
                     for a specific object, frame range, location and
                     invalidation scope;
``final_delivery``   the deliverable, produced by a registered operation.

Verification is by EXACT frame set, per-frame size, SHA-256 and freshness
(not-before epoch): a file merely existing — even an old frame or a raw input
picture — can never satisfy a final-delivery check. Duplicate frames (two
frame indices with identical content hashes) are reported, not silently
accepted. Tests use explicitly synthetic artifacts; nothing here claims a
real render happened.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager

import hashlib
import json
import os
import re
import sqlite3
import time
import tempfile
import stat
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .exr_codec import ExrDecodeError, read_exr
from .canonical import canonical_json, canonical_sha256
from .pipeline_store import _ClosingSQLiteConnection
from .platform_support import remove_owned_path
from .project_color import validate_project_color

ARTIFACT_CLASSES = ("raw_input", "preview_temp", "confirmed_cache", "final_delivery")

_SEQUENCE_TOKEN = re.compile(r"%0?\d*d|#+")
_FRAME_TOKEN = re.compile(r"%0?\d*d|#+")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def frame_path(pattern: str, frame: int) -> Path:
    token = _FRAME_TOKEN.search(pattern)
    if token is None:
        return Path(pattern)
    placeholder = token.group(0)
    replacement = placeholder % frame if placeholder.startswith("%") else f"{frame:0{len(placeholder)}d}"
    return Path(pattern[: token.start()] + replacement + pattern[token.end():])


def _frame_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_RECEIPT_IMPLEMENTATION_SOURCES = {
    str(source_path.absolute()): _frame_hash(source_path)
    for source_path in (Path(__file__), Path(read_exr.__code__.co_filename),
        Path(canonical_sha256.__code__.co_filename), Path(_ClosingSQLiteConnection.__exit__.__code__.co_filename),
        Path(remove_owned_path.__code__.co_filename), Path(validate_project_color.__code__.co_filename))
}


def _exr_structural_probe(path: Path) -> tuple[bool, str]:
    """Decode the supported EXR subset, including one real pixel payload."""
    try:
        decoded = read_exr(path, with_pixels=False)
    except ExrDecodeError as exc:
        return False, str(exc)
    except OSError:
        return False, "read_error"
    if int(decoded.get("pixel_count") or 0) <= 0 or not decoded.get("structural_validated") or int(decoded.get("sample_count") or 0) <= 0:
        return False, "no_decoded_pixels"
    return True, "decoded_pixels"


class ArtifactError(ValueError):
    pass


def validate_feedback_revision_chain(chain, *, task_id, graph_id, from_version, to_version):
    """核验控制端原反馈行的连续编译补丁；裸调用方数据不能替代可信来源回调。"""
    def reject():
        raise ArtifactError('FEEDBACK_REVISION_CHAIN_INVALID')
    if (type(chain) is not dict or set(chain) != {'schema', 'task_id', 'graph_id',
            'from_version', 'to_version', 'registered_graph', 'rows', 'chain_sha256'}
            or chain.get('schema') != 'bridge.feedback-revision-chain/1'
            or chain.get('task_id') != task_id or chain.get('graph_id') != graph_id
            or type(from_version) is not int or type(to_version) is not int
            or from_version < 0 or to_version <= from_version
            or type(chain.get('from_version')) is not int or type(chain.get('to_version')) is not int
            or chain['from_version'] != from_version or chain['to_version'] != to_version):
        reject()
    unsigned = {key: value for key, value in chain.items() if key != 'chain_sha256'}
    if canonical_sha256(unsigned) != chain['chain_sha256']:
        reject()
    rows = chain.get('rows')
    if type(rows) is not list or len(rows) != to_version + 1:
        reject()
    registered = chain.get('registered_graph')
    if type(registered) is not dict or not _SHA256.fullmatch(str(registered.get('graph_hash', ''))):
        reject()
    previous = None
    native_after = {}
    for version, row in enumerate(rows):
        if (type(row) is not dict or set(row) != {'version', 'state', 'payload'}
                or type(row['version']) is not int or row['version'] != version or row['state'] != 'COMPLETE'):
            reject()
        payload = row['payload']
        if (type(payload) is not dict or payload.get('task_id') != task_id
                or payload.get('base_graph_hash') != registered['graph_hash']):
            reject()
        compiled = payload.get('compiled')
        if type(compiled) is not dict:
            reject()
        if version == 0:
            if (compiled != registered or payload.get('graph_hash') != registered['graph_hash']
                    or payload.get('invalidated_nodes') != [] or payload.get('invalidated_outputs') != []):
                reject()
        else:
            # 与 FeedbackVersions.apply 使用相同编码验证每次已完成的真实参数补丁。
            if payload.get('graph_hash') != hashlib.sha256(json.dumps(compiled,
                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest():
                reject()
            before, after = payload.get('before'), payload.get('after')
            if (type(before) is not dict or type(after) is not dict or set(before) != set(after)
                    or not isinstance(payload.get('path'), str) or not payload['path']):
                reject()
            edits = {key: value for key, value in after.items() if before[key] != value}
            if not edits:
                reject()
            expected = json.loads(json.dumps(previous, allow_nan=False))
            nodes = [node for node in expected.get('nodes', []) if node.get('node_id') == payload.get('node_id')]
            if len(nodes) != 1:
                reject()
            node = nodes[0]
            parameters = node.get('parameters', {})
            if (not set(parameters).issubset(before)
                    or any(parameters[key] != before[key] for key in parameters)
                    or (payload['node_id'] in native_after and native_after[payload['node_id']] != before)):
                reject()
            root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((task_id + ':' + registered['graph_hash']).encode()).hexdigest()
            if payload['path'] != root + '/' + '/'.join(tuple(node.get('subnet_path', [])) + (node['node_id'],)):
                reject()
            native_after[payload['node_id']] = after
            node['parameters'] = {**node.get('parameters', {}), **edits}
            if compiled != expected:
                reject()
            addresses = {str(node.get('address')): str(node['node_id']) for node in expected['nodes']}
            affected = {str(payload['node_id'])}
            while True:
                expanded = affected | {addresses.get(edge['target_node'], edge['target_node'])
                    for edge in expected.get('connections', [])
                    if addresses.get(edge['source_node'], edge['source_node']) in affected}
                if expanded == affected:
                    break
                affected = expanded
            outputs = sorted(output['output_id'] for output in expected.get('outputs', [])
                if addresses.get(output['node_id'], output['node_id']) in affected)
            if payload.get('invalidated_nodes') != sorted(affected) or payload.get('invalidated_outputs') != outputs:
                reject()
        previous = compiled
    return chain


class ArtifactRegistry:
    """SQLite-backed, controller-owned ledger (one per installation root).

    Registration is anchored to OPERATION FACTS (C4): a trusted operation
    source must confirm that the operation exists, finished, and matches the
    task/frames/output being registered.  A caller-supplied receipt hash is
    only COMPARED against the fact source — it is never proof on its own.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "artifacts.sqlite3"
        if self.path.is_symlink():
            raise ArtifactError("artifact registry must not be a symlink")
        self._operation_source = None  # callable(operation_id) -> fact dict | None
        self._feedback_revision_source = None
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, artifact_class TEXT NOT NULL,
                pattern TEXT NOT NULL, frame_set TEXT NOT NULL, colorspace TEXT,
                premultiplied INTEGER, dependencies TEXT NOT NULL,
                created_at_epoch REAL NOT NULL, payload_json TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS artifact_versions (
                artifact_id TEXT NOT NULL, version INTEGER NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY(artifact_id, version))""")
            db.execute("""CREATE TABLE IF NOT EXISTS artifact_invalidations (
                artifact_id TEXT NOT NULL, version INTEGER NOT NULL, reason TEXT NOT NULL,
                PRIMARY KEY(artifact_id, version))""")
            db.execute("""CREATE TABLE IF NOT EXISTS artifact_operation_receipts (
                artifact_id TEXT NOT NULL, version INTEGER NOT NULL, payload_json TEXT NOT NULL,
                PRIMARY KEY(artifact_id, version))""")

    def invalidate_dependencies(self, dependencies: Sequence[str], *, reason: str) -> list[str]:
        """Invalidate current artifact versions and their actual registered descendants."""
        affected = set(str(item) for item in dependencies)
        if not affected or not reason:
            raise ArtifactError("explicit invalidation dependencies and reason required")
        invalidated = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM artifacts")]
            changed = True
            while changed:
                changed = False
                for row in rows:
                    key = str(row['artifact_id'])
                    if key in invalidated or not set(row.get('dependencies') or []).intersection(affected):
                        continue
                    db.execute("INSERT OR IGNORE INTO artifact_invalidations VALUES(?,?,?)", (key, int(row['version']), reason))
                    invalidated.append(key)
                    affected.update((key, 'artifact:' + key))
                    changed = True
        return invalidated

    def set_operation_source(self, source) -> None:
        """Inject the trusted operation-fact query (controller-provided).

        ``source(operation_id)`` returns a fact dict with keys ``task_id``,
        ``scene_fingerprint``, ``frame_set``, ``output_pattern``, ``state``
        and ``started_at_epoch`` — or None when the operation is unknown.
        """
        self._operation_source = source

    def set_feedback_revision_source(self, source) -> None:
        """仅控制器注入原反馈库查询；MCP登记字段不能提交或替换证明。"""
        if not callable(source):
            raise ArtifactError('FEEDBACK_REVISION_SOURCE_REQUIRED')
        self._feedback_revision_source = source

    def _operation_facts(self, operation_id: str, *, task_id: str, frames: list[int],
                         pattern: str, scene_fingerprint: str = "") -> dict[str, Any]:
        if self._operation_source is None:
            raise ArtifactError("OPERATION_SOURCE_REQUIRED",
                                "no trusted operation source is configured for this ledger")
        fact = self._operation_source(str(operation_id))
        if not fact:
            raise ArtifactError("OPERATION_NOT_FOUND",
                                "operation {} is unknown to the trusted source".format(operation_id))
        if str(fact.get("state")) != "COMPLETED":
            raise ArtifactError("OPERATION_NOT_COMPLETE",
                                "operation {} is {}, not a completed run".format(operation_id, fact.get("state")))
        if str(fact.get("task_id") or "") != str(task_id):
            raise ArtifactError("OPERATION_TASK_MISMATCH",
                                "operation {} belongs to task {}, not {}".format(operation_id, fact.get("task_id"), task_id))
        fact_frames = sorted({int(f) for f in fact.get("frame_set") or []})
        if frames != fact_frames:
            raise ArtifactError("OPERATION_FRAME_MISMATCH",
                                "registered frame set differs from the operation's frame set")
        if str(fact.get("output_pattern") or "") != str(pattern):
            raise ArtifactError("OPERATION_OUTPUT_MISMATCH",
                                "registered output pattern differs from the operation's output")
        if scene_fingerprint and str(fact.get("scene_fingerprint") or "") and                 str(fact.get("scene_fingerprint")) != str(scene_fingerprint):
            raise ArtifactError("OPERATION_SCENE_MISMATCH",
                                "registered scene fingerprint differs from the operation's scene version")
        if str(fact.get('completion_metadata_status') or '').startswith('INVALID'):
            raise ArtifactError('COMPLETION_METADATA_UNVERIFIED', 'producer typed completion is unavailable')
        return fact

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10, factory=_ClosingSQLiteConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        return db

    def register(self, *, artifact_id: str, task_id: str, artifact_class: str, pattern: str,
                 frame_set: Sequence[int], colorspace: str = "",
                 premultiplied: bool | None = None, dependencies: Iterable[str] = (),
                 payload: Mapping[str, Any] | None = None,
                 operation_id: str = "", operation_receipt_sha256: str = "",
                 scene_fingerprint: str = "",
                 receipt_source_files: Mapping[str, str] | None = None,
                 expected_previous_version: int | None = None) -> dict[str, Any]:
        """Optionally persist a typed registry receipt with the version commit.

        receipt_source_files binds explicit producer implementation paths to
        current SHA-256 values; registry and EXR reader sources are also bound.
        This proves registration of verified output, not native rendering.
        Missing typed producer metadata or source bytes fails before commit.
        """
        dependencies = tuple(str(item) for item in dependencies)
        if artifact_class not in ARTIFACT_CLASSES:
            raise ArtifactError("artifact_class must be one of {}".format(ARTIFACT_CLASSES))
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", str(artifact_id)):
            raise ArtifactError("artifact_id must be a stable identifier")
        frames = sorted({int(f) for f in frame_set})
        if not frames:
            raise ArtifactError("frame_set must not be empty")
        if artifact_class == "final_delivery":
            # A direct final_delivery registration is forbidden: the label is
            # earned only through promote() with a real operation receipt.
            raise ArtifactError(
                "FINAL_DELIVERY_REQUIRES_OPERATION",
                "final_delivery cannot be registered directly; promote a verified artifact with its operation receipt",
                "Only a completed registered operation (operation_id + receipt hash) may earn the final label.")
        fact = self._operation_facts(str(operation_id), task_id=str(task_id), frames=frames,
                                     pattern=str(pattern), scene_fingerprint=str(scene_fingerprint or ""))
        if str(operation_receipt_sha256 or "") and str(fact.get("operation_receipt_sha256") or ""):
            # the caller-supplied hash is only ever COMPARED with the fact source
            if str(operation_receipt_sha256) != str(fact.get("operation_receipt_sha256")):
                raise ArtifactError("RECEIPT_MISMATCH",
                                    "the supplied receipt hash does not match the operation fact source")
        # Freeze source facts before file validation; callbacks stay outside the
        # SQL transaction and cannot later replace the validated snapshot map.
        fact = json.loads(json.dumps(fact, ensure_ascii=False, sort_keys=True))
        if (fact.get('schema') in {'bridge.houdini.render.execution_fact/1.0', 'bridge.houdini.controlled-output/1.0'}
                and receipt_source_files is None):
            raise ArtifactError('REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED')
        project_color = self._project_color(fact, str(colorspace or ""))
        output_verification = self._output_verification(fact)
        if payload and 'output_verification' in payload:
            raise ArtifactError('CONTROLLED_OUTPUT_CALLER_PROVENANCE_FORBIDDEN')
        if payload and 'project_color' in payload:
            raise ArtifactError('PROJECT_COLOR_CALLER_PAYLOAD_FORBIDDEN')
        receipt_metadata = None
        if receipt_source_files is not None:
            if artifact_class == 'raw_input':
                raise ArtifactError('RAW_SOURCE_CAN_NEVER_RENDER')
            receipt_metadata = self._receipt_metadata(fact, frames, str(colorspace or ""),
                premultiplied, sorted(dependencies), str(fact.get('scene_fingerprint') or scene_fingerprint or ''),
                str(operation_id))
        # Identity check, version allocation, current-row replacement and
        # immutable history append are one SQLite write transaction.  A
        # second process therefore observes either the prior version or the
        # complete next version; it can never calculate the same version from
        # a stale read and overwrite history with INSERT OR REPLACE.
        with self._receipt_source_admission(receipt_source_files) as source_admission, \
                self._typed_admission(fact, str(pattern), frames, metadata=receipt_metadata) as admission, \
                self._receipt_dependency_admission(sorted(dependencies) if receipt_source_files is not None else None) as dependency_admission, \
                self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_receipt_dependency_rows(db, dependency_admission[0])
            prior_row = db.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?",
                                   (str(artifact_id),)).fetchone()
            entry_prior = json.loads(prior_row["payload_json"]) if prior_row else None
            if entry_prior is not None:
                invalid = db.execute("SELECT 1 FROM artifact_invalidations WHERE artifact_id=? AND version=?",
                                     (str(artifact_id), int(entry_prior['version']))).fetchone()
                if invalid and str(entry_prior.get('operation_id') or '') == str(operation_id or ''):
                    raise ArtifactError("invalidated artifact requires a new producing operation")
            for dependency in dependencies:
                dependency_id = str(dependency).removeprefix('artifact:')
                dependency_row = db.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (dependency_id,)).fetchone()
                if dependency_row:
                    dependency_version = json.loads(dependency_row[0])['version']
                    if db.execute("SELECT 1 FROM artifact_invalidations WHERE artifact_id=? AND version=?",
                                  (dependency_id, int(dependency_version))).fetchone():
                        raise ArtifactError("cannot register a descendant of an invalidated artifact")
            revision_parent = self._feedback_revision_parent(entry_prior, expected_previous_version,
                task_id=str(task_id), artifact_class=artifact_class, frames=frames,
                colorspace=str(colorspace or ''), premultiplied=premultiplied,
                operation_id=str(operation_id), dependencies=dependencies,
                typed=receipt_source_files is not None, invalidated=bool(invalid) if entry_prior is not None else False,
                revision_source=self._feedback_revision_source)
            if entry_prior is not None:
                changed_identity = (str(entry_prior.get("task_id") or "") != str(task_id)
                                    or entry_prior.get("artifact_class") != artifact_class
                                    or (str(entry_prior.get("pattern") or "") != str(pattern) and revision_parent is None))
                if changed_identity:
                    raise ArtifactError(
                        "ARTIFACT_IDENTITY_CONFLICT",
                        "artifact {} already exists as {} of task {}; identity changes are never overwritten".format(
                            artifact_id, entry_prior.get("artifact_class"), entry_prior.get("task_id")),
                        "Register a NEW artifact id for different content; the ledger keeps provenance intact.")
                version = int(entry_prior.get("version") or 1) + 1
            else:
                version = 1
            body = {
                "artifact_id": str(artifact_id), "task_id": str(task_id), "artifact_class": artifact_class,
                "pattern": str(pattern), "frame_set": frames, "colorspace": str(colorspace or ""),
                "premultiplied": None if premultiplied is None else bool(premultiplied),
                "dependencies": sorted(str(d) for d in dependencies),
                "created_at_epoch": time.time(),
                "registered_at_epoch": time.time(),
                "production_started_at_epoch": float(fact.get("started_at_epoch") or 0.0),
                "version": version,
                "supersedes_version": None if entry_prior is None else entry_prior.get("version"),
                "operation_id": str(operation_id or "") or None,
                "operation_receipt_sha256": str(operation_receipt_sha256 or "") or None,
                "scene_fingerprint": str(fact.get("scene_fingerprint") or scene_fingerprint or "") or None,
                "lineage": list(entry_prior.get("lineage") or []) if entry_prior else [],
                "payload": dict(payload or {}),
            }
            if project_color is not None:
                body['project_color'] = project_color
            if output_verification is not None:
                body['output_verification'] = output_verification
            if receipt_source_files is not None:
                body['operation_receipt_sha256'] = fact['operation_receipt_sha256']
            body['payload'].pop('completion_metadata_status', None)
            # The operation fact is authoritative for completion binding.  A
            # caller may compare a receipt hash, but cannot invent the file
            # snapshot, frozen visual objective, or dependency evidence.
            fact_snapshots = fact.get("frame_snapshots") or fact.get("output_snapshot") or {}
            if fact_snapshots:
                body["payload"]["completion_snapshot"] = json.loads(
                    json.dumps(fact_snapshots, ensure_ascii=False, sort_keys=True)
                )
            for fact_key, payload_key in (
                ("visual_objective", "visual_objective"),
                ("active_frames", "active_frames"),
                ("metadata", "completion_metadata"),
                ("dependencies", "completion_dependencies"),
                ("completion_metadata_status", "completion_metadata_status"),
            ):
                if fact.get(fact_key) is not None:
                    body["payload"][payload_key] = json.loads(
                        json.dumps(fact[fact_key], ensure_ascii=False, sort_keys=True)
                    )
            if revision_parent is not None:
                body['payload']['feedback_revision_parent'] = revision_parent
            # Full hash/decode ran before BEGIN. Only descriptor/path identity
            # checks accompany the short version allocation and history append.
            self._check_admission_identity(admission)
            encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
            db.execute("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (body["artifact_id"], body["task_id"], body["artifact_class"], body["pattern"],
                        json.dumps(frames), body["colorspace"],
                        None if body["premultiplied"] is None else int(body["premultiplied"]),
                        json.dumps(body["dependencies"]), body["created_at_epoch"], encoded))
            db.execute("INSERT INTO artifact_versions VALUES(?,?,?)",
                       (body["artifact_id"], version, encoded))
            if receipt_source_files is not None:
                receipt = {
                    'schema': 'bridge.registry.operation-receipt/1.0',
                    'command': 'artifact.register', 'stage': 'persisted_output', 'state': 'COMPLETED',
                    'registry_path': str(self.path), 'artifact_id': body['artifact_id'],
                    'version': version, 'task_id': body['task_id'], 'operation_id': body['operation_id'],
                    'artifact_class': body['artifact_class'], 'pattern': body['pattern'],
                    'frame_set': frames, 'scene_fingerprint': body['scene_fingerprint'],
                    'frame_snapshots': body['payload']['completion_snapshot'],
                    'colorspace': body['colorspace'], 'premultiplied': body['premultiplied'],
                    'dependencies': body['dependencies'], 'completion_metadata': receipt_metadata,
                    'dependency_records': dependency_admission[0],
                    'producer_receipt_sha256': fact['operation_receipt_sha256'],
                    'producer_fact_sha256': canonical_sha256(fact),
                    'artifact_payload_sha256': canonical_sha256(body),
                    'current_source': source_admission[0], 'registered_at_epoch': body['registered_at_epoch'],
                }
                receipt['registry_operation_receipt_sha256'] = canonical_sha256(receipt)
                db.execute('INSERT INTO artifact_operation_receipts VALUES(?,?,?)',
                    (body['artifact_id'], version, canonical_json(receipt)))
            self._check_admission_identity(admission)
            self._check_admission_identity(source_admission[1])
            self._check_receipt_dependency_rows(db, dependency_admission[0])
            self._check_admission_identity(dependency_admission[1])
        if self._is_typed(body):
            self._check_typed_current(body, invalidate=True)
        if receipt_source_files is not None:
            body['registry_operation_receipt'] = self.lookup_operation_receipt(body['artifact_id'], version)
        return body

    @staticmethod
    def _output_verification(fact):
        provenance = fact.get('output_verification')
        if fact.get('schema') == 'bridge.houdini.controlled-output/1.0':
            provenance = {'schema': 'bridge.output-verification-provenance/1.0',
                'verification_basis': fact.get('verification_basis'),
                'native_internal_status': fact.get('native_internal_status'),
                'native_internal_unknowns': fact.get('native_internal_unknowns'),
                'origin_verification_operation_id': fact.get('operation_id'),
                'origin_render_operation_id': fact.get('parent_operation_id'),
                'source_receipt_sha256': fact.get('source_receipt_sha256'),
                'stopped_receipt_sha256': fact.get('stopped_receipt_sha256'),
                'evidence_source': fact.get('evidence_source')}
        if provenance is None:
            return None
        if (not isinstance(provenance, dict)
                or provenance.get('schema') != 'bridge.output-verification-provenance/1.0'
                or provenance.get('verification_basis') != 'controlled_output_v1'
                or provenance.get('native_internal_status') != 'NOT_OBSERVED'
                or provenance.get('evidence_source') not in {'real_host', 'software_test'}
                or not isinstance(provenance.get('native_internal_unknowns'), list)
                or not provenance['native_internal_unknowns']
                or any(not isinstance(v, str) or not v for v in provenance['native_internal_unknowns'])
                or any(not isinstance(provenance.get(key), str) or not provenance[key]
                       for key in ('origin_verification_operation_id', 'origin_render_operation_id'))
                or provenance['origin_verification_operation_id'] == provenance['origin_render_operation_id']
                or any(not isinstance(provenance.get(key), str) or not _SHA256.fullmatch(provenance[key])
                       for key in ('source_receipt_sha256', 'stopped_receipt_sha256'))):
            raise ArtifactError('CONTROLLED_OUTPUT_PROVENANCE_INVALID')
        if fact.get('completion_metadata_status') != 'AVAILABLE':
            raise ArtifactError('REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED')
        return json.loads(json.dumps(provenance, ensure_ascii=False, allow_nan=False))

    @staticmethod
    def _project_color(fact, colorspace):
        value = fact.get('project_color')
        metadata = fact.get('metadata') or {}
        values = list(metadata.values()) if isinstance(metadata, dict) else []
        if value is None:
            if any(isinstance(image, dict) and 'project_color' in image for image in values):
                raise ArtifactError('PROJECT_COLOR_PRODUCER_MISMATCH')
            return None
        if fact.get('completion_metadata_status') != 'AVAILABLE':
            raise ArtifactError('REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED')
        value = validate_project_color(value)
        if value['colorspace'] != colorspace or not values or any(
                not isinstance(image, dict) or image.get('project_color') != value for image in values):
            raise ArtifactError('PROJECT_COLOR_PRODUCER_MISMATCH')
        return value

    @staticmethod
    def _receipt_metadata(fact, frames, colorspace, premultiplied, dependencies, scene, operation_id):
        ArtifactRegistry._project_color(fact, colorspace)
        receipt_sha = fact.get('operation_receipt_sha256')
        metadata = fact.get('metadata')
        snapshots = fact.get('frame_snapshots') or fact.get('output_snapshot') or {}
        if (fact.get('completion_metadata_status') != 'AVAILABLE'
                or not isinstance(receipt_sha, str) or not _SHA256.fullmatch(receipt_sha)
                or fact.get('frame_set') != frames or any(type(frame) is not int for frame in fact.get('frame_set') or [])
                or type(fact.get('started_at_epoch')) not in (int, float) or fact['started_at_epoch'] <= 0
                or not scene or fact.get('scene_fingerprint') != scene
                or fact.get('operation_id', operation_id) != operation_id
                or not colorspace.strip() or type(premultiplied) is not bool
                or fact.get('dependencies') != dependencies
                or not isinstance(metadata, dict) or set(metadata) != {str(frame) for frame in frames}):
            raise ArtifactError('REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED')
        for frame in frames:
            image, snapshot = metadata[str(frame)], snapshots.get(str(frame))
            if (not isinstance(image, dict) or not isinstance(snapshot, dict)
                    or any(image.get(key) != snapshot.get(key) for key in ('path', 'bytes', 'modified_ns', 'sha256'))
                    or image.get('colorspace') != colorspace or type(image.get('premultiplied')) is not bool
                    or image['premultiplied'] != premultiplied or 'rows' in image):
                raise ArtifactError('REGISTRY_RECEIPT_METADATA_MISMATCH')
        return metadata

    @contextmanager
    def _receipt_source_admission(self, source_files):
        admission = []
        if source_files is None:
            yield ({}, admission)
            return
        try:
            if not isinstance(source_files, Mapping) or not 0 < len(source_files) <= 256:
                raise ArtifactError('explicit producer source files required')
            sources = dict(source_files)
            for name, actual in _RECEIPT_IMPLEMENTATION_SOURCES.items():
                if name in sources and sources[name] != actual:
                    raise ArtifactError('current registry/EXR implementation changed')
                sources[name] = actual
            if len(sources) > 256:
                raise ArtifactError('receipt source file budget exceeded')
            for name, digest in sources.items():
                path = Path(name)
                if (not path.is_absolute() or str(path) != name or not isinstance(digest, str)
                        or not _SHA256.fullmatch(digest)):
                    raise ArtifactError('absolute source path and SHA-256 required')
                for component in (path, *path.parents):
                    info = component.lstat()
                    if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0)
                            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
                        raise ArtifactError('source traverses a symlink or reparse point')
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
                stream = os.fdopen(descriptor, 'rb')
                info = os.fstat(stream.fileno())
                admission.append((path, stream, self._file_identity(info)))
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 8*1024*1024:
                    raise ArtifactError('bounded regular source file required')
                data = stream.read(8*1024*1024 + 1)
                if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != digest:
                    raise ArtifactError('source bytes changed')
            self._check_admission_identity(admission)
        except (OSError, ValueError, TypeError) as exc:
            raise ArtifactError('REGISTRY_RECEIPT_SOURCE_UNAVAILABLE', str(exc)) from exc
        else:
            yield (sources, admission)
        finally:
            for _, stream, _ in admission:
                if not stream.closed:
                    stream.close()

    @staticmethod
    def _receipt_dependency_records(db, dependencies):
        records = {}
        for dependency in dependencies:
            key = dependency.removeprefix('artifact:')
            row = db.execute('SELECT payload_json FROM artifacts WHERE artifact_id=?', (key,)).fetchone()
            if row is None:
                if dependency.startswith('artifact:'):
                    raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_UNAVAILABLE', key)
                continue
            entry = json.loads(row[0])
            if db.execute('SELECT 1 FROM artifact_invalidations WHERE artifact_id=? AND version=?',
                    (key, entry['version'])).fetchone():
                raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_INVALIDATED', key)
            records[key] = {'version': entry['version'], 'payload_sha256': canonical_sha256(entry)}
        return records

    @contextmanager
    def _receipt_dependency_admission(self, dependencies):
        """Verify the registered dependency closure before taking SQL locks."""
        records, admission, entries, receipts = {}, [], {}, {}
        if dependencies is None:
            yield (records, admission)
            return
        pending = [(dependency, ()) for dependency in dependencies]
        with ExitStack() as contexts:
            while pending:
                dependency, ancestors = pending.pop()
                key = dependency.removeprefix('artifact:')
                if key in ancestors:
                    raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_CYCLE', key)
                if key in records:
                    continue
                entry = self._lookup_unchecked(key)
                if entry is None:
                    if dependency.startswith('artifact:'):
                        raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_UNAVAILABLE', key)
                    continue
                if len(records) >= 64 or not self._is_typed(entry):
                    raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_PROOF_REQUIRED', key)
                fact = self._operation_facts(entry['operation_id'], task_id=entry['task_id'],
                    frames=entry['frame_set'], pattern=entry['pattern'], scene_fingerprint=entry['scene_fingerprint'])
                fact = json.loads(canonical_json(fact))
                payload = entry['payload']
                producer_sha = fact.get('operation_receipt_sha256')
                if (fact.get('completion_metadata_status') != 'AVAILABLE'
                        or not isinstance(producer_sha, str) or not _SHA256.fullmatch(producer_sha)
                        or not isinstance(fact.get('metadata'), dict)
                        or any(not isinstance(fact['metadata'].get(str(frame)), dict) for frame in entry['frame_set'])
                        or not isinstance(fact.get('dependencies'), list)
                        or fact.get('frame_set') != entry['frame_set']
                        or any(type(frame) is not int for frame in fact.get('frame_set') or [])
                        or (entry.get('operation_receipt_sha256') and entry['operation_receipt_sha256'] != producer_sha)
                        or fact.get('scene_fingerprint') != entry['scene_fingerprint']
                        or (fact.get('frame_snapshots') or fact.get('output_snapshot')) != payload.get('completion_snapshot')
                        or fact.get('metadata') != payload.get('completion_metadata')
                        or fact.get('dependencies') != payload.get('completion_dependencies')
                        or sorted(fact.get('dependencies') or []) != entry['dependencies']):
                    raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_PRODUCER_CHANGED', key)
                metadata = {str(frame): fact['metadata'][str(frame)] for frame in entry['frame_set']}
                admission.extend(contexts.enter_context(self._typed_admission(
                    fact, entry['pattern'], entry['frame_set'], metadata=metadata)))
                with self._connect() as db:
                    row = db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',
                        (key, entry['version'])).fetchone()
                parent_receipt = json.loads(row[0]) if row else None
                receipt_sha = None
                if parent_receipt is not None:
                    receipt_sha = parent_receipt.get('registry_operation_receipt_sha256')
                    basis = {name: value for name, value in parent_receipt.items() if name != 'registry_operation_receipt_sha256'}
                    if (receipt_sha != canonical_sha256(basis)
                            or parent_receipt.get('schema') != 'bridge.registry.operation-receipt/1.0'
                            or parent_receipt.get('state') != 'COMPLETED'
                            or parent_receipt.get('command') != 'artifact.register'
                            or parent_receipt.get('stage') != 'persisted_output'
                            or parent_receipt.get('registry_path') != str(self.path)
                            or parent_receipt.get('artifact_payload_sha256') != canonical_sha256(entry)
                            or parent_receipt.get('producer_fact_sha256') != canonical_sha256(fact)
                            or parent_receipt.get('producer_receipt_sha256') != producer_sha):
                        raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_PRODUCER_CHANGED', key)
                    for name in ('artifact_id', 'version', 'task_id', 'operation_id', 'artifact_class', 'pattern',
                                 'frame_set', 'scene_fingerprint', 'colorspace', 'premultiplied', 'dependencies'):
                        if parent_receipt.get(name) != entry.get(name):
                            raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_PRODUCER_CHANGED', key)
                    sources, source_admission = contexts.enter_context(
                        self._receipt_source_admission(parent_receipt['current_source']))
                    if sources != parent_receipt['current_source']:
                        raise ArtifactError('REGISTRY_RECEIPT_SOURCE_UNAVAILABLE')
                    admission.extend(source_admission)
                    receipts[key] = parent_receipt
                entries[key] = entry
                records[key] = {'version': entry['version'], 'payload_sha256': canonical_sha256(entry),
                    'producer_fact_sha256': canonical_sha256(fact), 'producer_receipt_sha256': producer_sha,
                    'registry_operation_receipt_sha256': receipt_sha}
                pending.extend((item, (*ancestors, key)) for item in entry['dependencies'])
            for key, parent_receipt in receipts.items():
                subset, remaining = {}, list(entries[key]['dependencies'])
                while remaining:
                    parent_key = remaining.pop().removeprefix('artifact:')
                    if parent_key in records and parent_key not in subset:
                        subset[parent_key] = records[parent_key]
                        remaining.extend(entries[parent_key]['dependencies'])
                if parent_receipt.get('dependency_records') != subset:
                    raise ArtifactError('REGISTRY_RECEIPT_DEPENDENCY_PRODUCER_CHANGED', key)
            self._check_admission_identity(admission)
            yield (records, admission)

    def _check_receipt_dependency_rows(self, db, records):
        actual = self._receipt_dependency_records(db, ['artifact:' + key for key in records])
        for key, record in records.items():
            expected = {name: record[name] for name in ('version', 'payload_sha256')}
            history = db.execute('SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?',
                (key, record['version'])).fetchone()
            row = db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',
                (key, record['version'])).fetchone()
            parent_receipt = json.loads(row[0]) if row else None
            receipt_sha = None
            if parent_receipt is not None:
                receipt_sha = parent_receipt.pop('registry_operation_receipt_sha256', None)
                if receipt_sha != canonical_sha256(parent_receipt):
                    raise ArtifactError('REGISTRY_RECEIPT_DB_READBACK_MISMATCH', key)
            if (actual.get(key) != expected or history is None
                    or canonical_sha256(json.loads(history[0])) != record['payload_sha256']
                    or receipt_sha != record['registry_operation_receipt_sha256']):
                raise ArtifactError('REGISTRY_RECEIPT_DB_READBACK_MISMATCH', key)

    def lookup_operation_receipt(self, artifact_id: str, version: int) -> dict[str, Any]:
        """Read and revalidate a committed receipt against current facts/bytes.

        A historical receipt remains audit data after supersession, invalidation
        or byte/source changes; it cannot be consumed as current completion.
        """
        if type(version) is not int or version <= 0:
            raise ArtifactError('REGISTRY_RECEIPT_VERSION_REQUIRED')
        with self._connect() as db:
            row = db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',
                (str(artifact_id), version)).fetchone()
        if row is None:
            raise ArtifactError('REGISTRY_RECEIPT_NOT_FOUND')
        return self.verify_operation_receipt(json.loads(row[0]))

    def verify_operation_receipt(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Verify DB identity, immutable row, producer, sources and exact EXRs.

        SHA values are comparisons with the configured trusted source and actual
        SQLite rows, never authentication of a caller-created success document.
        File hashing, decoding and producer callbacks run outside SQL locks.
        """
        try:
            receipt = json.loads(canonical_json(receipt))
            digest = receipt.pop('registry_operation_receipt_sha256')
            if (digest != canonical_sha256(receipt)
                    or receipt['schema'] != 'bridge.registry.operation-receipt/1.0'
                    or receipt['state'] != 'COMPLETED' or receipt['command'] != 'artifact.register'
                    or receipt['stage'] != 'persisted_output' or receipt['registry_path'] != str(self.path)
                    or type(receipt['version']) is not int or receipt['version'] <= 0):
                raise ArtifactError('REGISTRY_RECEIPT_BINDING_MISMATCH')
            receipt['registry_operation_receipt_sha256'] = digest
            entry = self._lookup_unchecked(receipt['artifact_id'])
            if entry is None or canonical_sha256(entry) != receipt['artifact_payload_sha256']:
                raise ArtifactError('REGISTRY_RECEIPT_CURRENT_VERSION_CHANGED')
            for key in ('artifact_id', 'version', 'task_id', 'operation_id', 'artifact_class', 'pattern',
                        'frame_set', 'scene_fingerprint', 'colorspace', 'premultiplied', 'dependencies', 'registered_at_epoch'):
                if entry[key] != receipt[key]:
                    raise ArtifactError('REGISTRY_RECEIPT_BINDING_MISMATCH', key)
            if (entry['operation_receipt_sha256'] != receipt['producer_receipt_sha256']
                    or entry['payload']['completion_snapshot'] != receipt['frame_snapshots']
                    or entry['payload']['completion_metadata'] != receipt['completion_metadata']):
                raise ArtifactError('REGISTRY_RECEIPT_BINDING_MISMATCH')
            fact = self._operation_facts(receipt['operation_id'], task_id=receipt['task_id'],
                frames=receipt['frame_set'], pattern=receipt['pattern'], scene_fingerprint=receipt['scene_fingerprint'])
            fact = json.loads(canonical_json(fact))
            if (canonical_sha256(fact) != receipt['producer_fact_sha256']
                    or fact.get('operation_receipt_sha256') != receipt['producer_receipt_sha256']):
                raise ArtifactError('REGISTRY_RECEIPT_PRODUCER_CHANGED')
            metadata = self._receipt_metadata(fact, receipt['frame_set'], receipt['colorspace'],
                receipt['premultiplied'], receipt['dependencies'], receipt['scene_fingerprint'], receipt['operation_id'])
            if entry.get('project_color') != self._project_color(fact, receipt['colorspace']):
                raise ArtifactError('PROJECT_COLOR_PRODUCER_MISMATCH')
            if entry.get('output_verification') != self._output_verification(fact):
                raise ArtifactError('CONTROLLED_OUTPUT_PROVENANCE_CHANGED')
            if metadata != receipt['completion_metadata']:
                raise ArtifactError('REGISTRY_RECEIPT_METADATA_MISMATCH')
            with self._receipt_source_admission(receipt['current_source']) as source_admission, \
                    self._typed_admission(fact, receipt['pattern'], receipt['frame_set'], metadata=metadata) as admission, \
                    self._receipt_dependency_admission(receipt['dependencies']) as dependency_admission, \
                    self._connect() as db:
                if source_admission[0] != receipt['current_source']:
                    raise ArtifactError('REGISTRY_RECEIPT_SOURCE_UNAVAILABLE')
                if dependency_admission[0] != receipt['dependency_records']:
                    raise ArtifactError('REGISTRY_RECEIPT_DB_READBACK_MISMATCH')
                db.execute('BEGIN')
                stored = db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',
                    (receipt['artifact_id'], receipt['version'])).fetchone()
                current = db.execute('SELECT * FROM artifacts WHERE artifact_id=?', (receipt['artifact_id'],)).fetchone()
                history = db.execute('SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?',
                    (receipt['artifact_id'], receipt['version'])).fetchone()
                invalid = db.execute('SELECT 1 FROM artifact_invalidations WHERE artifact_id=? AND version=?',
                    (receipt['artifact_id'], receipt['version'])).fetchone()
                if (stored is None or json.loads(stored[0]) != receipt or current is None or history is None
                        or current['payload_json'] != history[0] or json.loads(history[0]) != entry or invalid):
                    raise ArtifactError('REGISTRY_RECEIPT_DB_READBACK_MISMATCH')
                for key in ('task_id', 'artifact_class', 'pattern', 'colorspace', 'created_at_epoch'):
                    if current[key] != entry[key]:
                        raise ArtifactError('REGISTRY_RECEIPT_DB_READBACK_MISMATCH', key)
                if (json.loads(current['frame_set']) != entry['frame_set']
                        or json.loads(current['dependencies']) != entry['dependencies']
                        or current['premultiplied'] != int(entry['premultiplied'])):
                    raise ArtifactError('REGISTRY_RECEIPT_DB_READBACK_MISMATCH')
                self._check_admission_identity(admission)
                self._check_admission_identity(source_admission[1])
                self._check_receipt_dependency_rows(db, dependency_admission[0])
                self._check_admission_identity(dependency_admission[1])
            return receipt
        except (OSError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, ArtifactError):
                raise
            raise ArtifactError('REGISTRY_RECEIPT_INVALID', str(exc)) from exc

    def lookup_version(self, artifact_id: str, version: int) -> "dict[str, Any] | None":
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?",
                             (str(artifact_id), int(version))).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def history(self, artifact_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT version, payload_json FROM artifact_versions WHERE artifact_id=? ORDER BY version",
                              (str(artifact_id),)).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def _lookup_unchecked(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (str(artifact_id),)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    @staticmethod
    def _is_typed(entry):
        return (entry.get('payload') or {}).get('completion_metadata_status') == 'AVAILABLE'

    @staticmethod
    def _file_identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    @classmethod
    def _check_admission_identity(cls, admission):
        """Bounded stat/fstat only: no decode/hash/callback/SQL in this gate."""
        try:
            for path, stream, identity in admission:
                descriptor = os.fstat(stream.fileno())
                current = os.stat(path, follow_symlinks=False)
                if (not stat.S_ISREG(descriptor.st_mode) or not stat.S_ISREG(current.st_mode)
                        or cls._file_identity(descriptor) != identity
                        or cls._file_identity(current) != identity):
                    raise ArtifactError('verified completion descriptor/path changed')
        except (OSError, ValueError) as exc:
            raise ArtifactError('COMPLETION_BYTES_UNAVAILABLE', str(exc)) from exc

    @contextmanager
    def _typed_admission(self, fact, pattern, frames, *, metadata=None):
        """Hash and decode one SHA-bound readonly copy outside SQL write locks.

        At most 12 original descriptors survive through the short admission
        transaction; each temporary frame copy is discarded after decoding.
        Descriptors are observations, not external file locks. Postcommit and
        actual-consumption byte verification remain necessary.
        """
        if fact.get('completion_metadata_status') != 'AVAILABLE':
            yield (); return
        admission = []
        prepared = False
        try:
            snapshots = fact.get('frame_snapshots') or fact.get('output_snapshot') or {}
            if not 0 < len(frames) <= 12 or set(snapshots) != {str(f) for f in frames}:
                raise ArtifactError('typed completion snapshot/frame budget missing')
            temporary_parent = Path(tempfile.gettempdir()).resolve()
            with tempfile.TemporaryDirectory(prefix='artifact-admission-frame-',
                                             dir=temporary_parent) as directory:
                for frame in frames:
                    expected = snapshots[str(frame)]
                    path = frame_path(pattern,frame)
                    if (expected.get('path') != str(path)
                            or type(expected.get('bytes')) is not int
                            or not 0 < expected['bytes'] <= 512*1024*1024
                            or type(expected.get('modified_ns')) is not int
                            or not _SHA256.fullmatch(str(expected.get('sha256') or ''))):
                        raise ArtifactError('typed completion snapshot identity missing')
                    fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0))
                    stream = os.fdopen(fd,'rb')
                    before = os.fstat(stream.fileno())
                    identity = self._file_identity(before)
                    admission.append((path,stream,identity))
                    if (not stat.S_ISREG(before.st_mode) or before.st_size != expected['bytes']
                            or before.st_mtime_ns != expected['modified_ns']
                            or before.st_mtime < float(fact.get('started_at_epoch') or 0.0)):
                        raise ArtifactError('current completion snapshot changed or stale')
                    copy = Path(directory)/'frame.exr'
                    digest,size=hashlib.sha256(),0
                    with copy.open('wb') as target:
                        for chunk in iter(lambda:stream.read(1024*1024),b''):
                            size+=len(chunk)
                            if size > 512*1024*1024:raise ArtifactError('typed completion byte budget exceeded')
                            digest.update(chunk);target.write(chunk)
                    if size!=expected['bytes'] or digest.hexdigest()!=expected['sha256']:
                        raise ArtifactError('current bytes differ from producing completion')
                    self._check_admission_identity(admission)
                    copy.chmod(0o400)
                    readable,reason=_exr_structural_probe(copy)
                    if not readable:raise ArtifactError('completion EXR unreadable: '+reason)
                    if metadata is not None:
                        actual = read_exr(copy, with_pixels=False)
                        for key in ('width', 'height', 'channels', 'channel_layout', 'header_fields',
                                    'compression', 'structural_validated', 'pixel_count', 'sample_count'):
                            if canonical_json(metadata[str(frame)].get(key)) != canonical_json(actual.get(key)):
                                raise ArtifactError('REGISTRY_RECEIPT_PHYSICAL_METADATA_MISMATCH', key)
                    self._check_admission_identity(admission)
                    remove_owned_path(copy, owned_root=directory)
                prepared = True
                yield tuple(admission)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            if prepared: raise
            if isinstance(exc,ArtifactError) and exc.args and exc.args[0]=='COMPLETION_BYTES_UNAVAILABLE':raise
            raise ArtifactError('COMPLETION_BYTES_UNAVAILABLE',str(exc)) from exc
        finally:
            for _,stream,_ in admission:stream.close()

    def _invalidate_version(self, entry, reason):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO artifact_invalidations VALUES(?,?,?)',
                       (entry['artifact_id'], int(entry['version']), reason))
        self.invalidate_dependencies([entry['artifact_id'], 'artifact:' + entry['artifact_id']], reason=reason)

    def _check_typed_current(self, entry, *, invalidate=False):
        invalidation = None
        if invalidate:
            with self._connect() as db:
                invalidation = db.execute('SELECT reason FROM artifact_invalidations WHERE artifact_id=? AND version=?',
                    (entry['artifact_id'], int(entry['version']))).fetchone()
        try:
            snapshots = (entry.get('payload') or {}).get('completion_snapshot') or {}
            if (len(entry['frame_set']) > 12 or set(snapshots) != {str(f) for f in entry['frame_set']}
                    or any(type(item.get('bytes')) is not int or not 0 < item['bytes'] <= 512*1024*1024
                           for item in snapshots.values())):
                raise ArtifactError('typed completion byte/frame budget or snapshot missing')
            report = self._verify_entry(entry, min_size_kb=0, active_frames=[], invalidation=invalidation)
            if not report['ok'] or not report['fresh']:
                raise ArtifactError('current bytes differ from producing completion')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            if invalidate: self._invalidate_version(entry, 'COMPLETION_BYTES_UNAVAILABLE')
            raise ArtifactError('COMPLETION_BYTES_UNAVAILABLE', str(exc)) from exc

    @staticmethod
    def _feedback_revision_parent(prior, expected, *, task_id, artifact_class, frames,
                                  colorspace, premultiplied, operation_id, dependencies, typed, invalidated, revision_source=None):
        """仅允许已失效的同任务反馈修订换输出路径，旧版本与原回执不改写。"""
        if expected is None:
            return None
        if (type(expected) is not int or expected < 1 or not typed or not invalidated
                or prior is None or prior.get('version') != expected
                or prior.get('task_id') != task_id or prior.get('artifact_class') != artifact_class
                or prior.get('frame_set') != frames or prior.get('colorspace') != colorspace
                or prior.get('premultiplied') is not premultiplied
                or prior.get('operation_id') == operation_id):
            raise ArtifactError('FEEDBACK_REVISION_PARENT_MISMATCH')
        def split(items):
            versions, other = {}, set()
            for item in items:
                match = re.fullmatch(r'graph:' + re.escape(task_id) + r':([^:]+):version:([0-9]+)', item)
                if match:
                    if match[1] in versions:raise ArtifactError('FEEDBACK_REVISION_GRAPH_CONFLICT')
                    versions[match[1]] = int(match[2])
                else:other.add(item)
            return versions, other
        old, old_other = split(prior.get('dependencies') or [])
        new, new_other = split(dependencies)
        if len(old) != 1 or set(new) != set(old) or old_other != new_other:
            raise ArtifactError('FEEDBACK_REVISION_CONTENT_VERSION_REQUIRED')
        graph_id, before = next(iter(old.items()))
        after = new[graph_id]
        chain = None
        if after != before + 1:
            if after <= before or not callable(revision_source):
                raise ArtifactError('FEEDBACK_REVISION_CONTENT_VERSION_REQUIRED')
            # 证明从控制器读取，不能由登记payload或客户端提供自证字典。
            chain = revision_source(task_id=task_id, graph_id=graph_id,
                from_version=before, to_version=after)
            chain = json.loads(json.dumps(chain, allow_nan=False))
            validate_feedback_revision_chain(chain, task_id=task_id, graph_id=graph_id,
                from_version=before, to_version=after)
        parent = {'artifact_version':expected,'pattern':prior['pattern'],
                  'operation_id':prior['operation_id'],'artifact_sha256':canonical_sha256(prior),
                  'graph_versions':old}
        if chain is not None:
            parent['feedback_revision_chain'] = chain
        return parent

    def registration_head(self, artifact_id: str, *, task_id: str) -> dict[str, Any] | None:
        """为新修订读取同任务历史头；历史失效不妨碍新生产操作登记。"""
        entry = self._lookup_unchecked(str(artifact_id))
        if entry is not None and entry.get('task_id') != str(task_id):
            raise ArtifactError('registration head belongs to another task')
        return entry

    def lookup(self, artifact_id: str) -> dict[str, Any] | None:
        """Current typed metadata is available only while its bytes verify.

        Lookup is an observation, not a file lock. A pixel consumer must use
        read_frame's verified content instead of opening the returned path.
        Immutable history remains available through history/lookup_version.
        """
        entry = self._lookup_unchecked(artifact_id)
        if entry is not None and self._is_typed(entry):
            self._check_typed_current(entry, invalidate=True)
            with self._connect() as db:
                receipt_row = db.execute('SELECT 1 FROM artifact_operation_receipts WHERE artifact_id=? AND version=?',
                    (entry['artifact_id'], entry['version'])).fetchone()
            if receipt_row:
                entry['registry_operation_receipt'] = self.lookup_operation_receipt(entry['artifact_id'], entry['version'])
        return entry

    def read_frame(self, artifact_id: str, frame: int) -> dict[str, Any]:
        """Decode one bounded, SHA-bound readonly copy for actual consumption.

        The returned image was decoded from the verified copy. Consume that
        content; a subsequent open of the original path is a new observation.
        No sequence-wide byte copies or perpetual external file lock are held.
        """
        entry = self.lookup(artifact_id)
        if entry is None or not self._is_typed(entry) or type(frame) is not int or frame not in entry['frame_set']:
            raise ArtifactError('COMPLETION_BYTES_UNAVAILABLE', 'typed registered frame required')
        expected = entry['payload']['completion_snapshot'][str(frame)]
        source = frame_path(entry['pattern'], frame)
        try:
            if source.is_symlink() or not source.is_file() or str(source) != expected['path']:
                raise ArtifactError('regular completion frame required')
            with tempfile.TemporaryDirectory(prefix='artifact-frame-consume-') as directory:
                copy = Path(directory) / 'frame.exr'
                digest, size = hashlib.sha256(), 0
                fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
                with os.fdopen(fd, 'rb') as original, copy.open('wb') as target:
                    before = os.fstat(original.fileno())
                    if not stat.S_ISREG(before.st_mode): raise ArtifactError('regular completion bytes required')
                    for chunk in iter(lambda: original.read(1024*1024), b''):
                        size += len(chunk)
                        if size > 512*1024*1024: raise ArtifactError('consumer byte budget exceeded')
                        digest.update(chunk); target.write(chunk)
                    after = os.fstat(original.fileno())
                current = source.stat()
                identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
                if (size != expected['bytes'] or digest.hexdigest() != expected['sha256']
                        or before.st_mtime_ns != expected['modified_ns']
                        or identity(before) != identity(after) or identity(before) != identity(current)):
                    raise ArtifactError('consumed bytes differ from producing completion')
                copy.chmod(0o400)
                image = read_exr(copy, with_pixels=True)
                # Recheck registry/dependency invalidation after decoding, without
                # substituting a new producer fact or re-reading mutable pixels.
                with self._connect() as db:
                    invalid = db.execute('SELECT 1 FROM artifact_invalidations WHERE artifact_id=? AND version=?',
                        (entry['artifact_id'], int(entry['version']))).fetchone()
                    row = db.execute('SELECT payload_json FROM artifacts WHERE artifact_id=?', (entry['artifact_id'],)).fetchone()
                if invalid or row is None or json.loads(row[0])['version'] != entry['version']:
                    raise ArtifactError('registered version changed or invalidated during consumption')
                result = {'artifact_id':entry['artifact_id'], 'version':entry['version'],
                    'operation_id':entry['operation_id'], 'frame':frame, 'sha256':digest.hexdigest(),
                    'bytes':size, 'image':image}
                if 'registry_operation_receipt' in entry:
                    result['registry_operation_receipt'] = self.verify_operation_receipt(entry['registry_operation_receipt'])
                return result
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._invalidate_version(entry, 'COMPLETION_BYTES_UNAVAILABLE')
            raise ArtifactError('COMPLETION_BYTES_UNAVAILABLE', str(exc)) from exc

    def promote(self, artifact_id: str, to_class: str, *, verified_by: str,
                observed_sha256: "Mapping[int, str] | None" = None) -> dict[str, Any]:
        """Move an artifact to a stricter class (control-plane action).

        ``raw_input`` can never become ``final_delivery``: reference material
        is not produced by a registered operation.  A promotion to
        ``final_delivery`` additionally requires the operator to supply the
        observed per-frame hashes, which must match a fresh verification.
        """
        entry = self.lookup(artifact_id)
        if entry is None:
            raise ArtifactError("unknown artifact {}".format(artifact_id))
        with self._connect() as db:
            invalidation = db.execute("SELECT reason FROM artifact_invalidations WHERE artifact_id=? AND version=?",
                                      (str(artifact_id), int(entry['version']))).fetchone()
        if invalidation:
            raise ArtifactError("artifact dependency version was invalidated")
        if to_class not in ARTIFACT_CLASSES:
            raise ArtifactError("artifact_class must be one of {}".format(ARTIFACT_CLASSES))
        if not str(verified_by or "").strip():
            raise ArtifactError("verified_by must name the control operator and evidence")
        order = {name: index for index, name in enumerate(ARTIFACT_CLASSES)}
        if order[to_class] <= order[entry["artifact_class"]]:
            raise ArtifactError("artifact {} is already {}".format(artifact_id, entry["artifact_class"]))
        lineage = list(entry.get("lineage") or [])
        if "raw_input" in lineage or entry["artifact_class"] == "raw_input":
            # raw material is never produced output: no promotion at all, so
            # no raw -> preview -> final chain can ever launder the source
            raise ArtifactError("RAW_SOURCE_CAN_NEVER_RENDER",
                                "artifact {} has raw_input provenance; reference material is not render output".format(artifact_id))
        if to_class == "final_delivery":
            fact = self._operation_facts(str(entry.get("operation_id") or ""),
                                         task_id=str(entry.get("task_id")),
                                         frames=list(entry["frame_set"]),
                                         pattern=str(entry.get("pattern")),
                                         scene_fingerprint=str(entry.get("scene_fingerprint") or ""))
            receipt = str(entry.get("operation_receipt_sha256") or "")
            if not entry.get("operation_id") or not re.fullmatch(r"[0-9a-f]{64}", receipt):
                raise ArtifactError(
                    "FINAL_DELIVERY_REQUIRES_OPERATION",
                    "final_delivery promotion requires a completed operation id and receipt hash",
                    "Register the artifact FROM the completing operation; the receipt ties the label to real work.")
            # confirmation fields come from the HOST RECEIPT payload, not defaults
            confirmations = (entry.get("payload") or {}).get("delivery_confirmations") or {}
            for flag in ("colorspace_confirmed", "premultiplied_confirmed", "dependencies_confirmed"):
                if confirmations.get(flag) is not True:
                    raise ArtifactError("DELIVERY_CONFIRMATION_MISSING",
                                        "final_delivery requires {} from the host receipt".format(flag))
            if not str(entry.get("colorspace") or "").strip() or entry.get("premultiplied") is None:
                raise ArtifactError("final_delivery requires colorspace and premultiplied metadata")
            if not observed_sha256:
                raise ArtifactError("final_delivery promotion requires observed per-frame hashes")
            report = self.verify(artifact_id)
            if (not report["ok"] or not report["fresh"] or not report.get("readable")
                    or not report.get("no_duplicates") or not report.get("dependencies_present")
                    or not str(report.get("colorspace") or "").strip()
                    or report.get("premultiplied") is None):
                raise ArtifactError("final_delivery promotion requires a complete, fresh, readable verification")
            for frame in entry["frame_set"]:
                observed = str(observed_sha256.get(frame) or "")
                if not _SHA256.fullmatch(observed) or observed != report["frames"][frame]["sha256"]:
                    raise ArtifactError("observed hash mismatch at frame {}".format(frame))
        entry["artifact_class"] = to_class
        entry["promoted_by"] = str(verified_by)
        entry["promoted_at_epoch"] = time.time()
        entry["lineage"] = sorted(set(lineage + [entry["artifact_class"]]))
        old_version = int(entry.get("version") or 0)
        new_version = old_version + 1
        entry["version"] = new_version
        entry["supersedes_version"] = old_version
        entry.pop('registry_operation_receipt', None)
        encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        # Re-read, CAS-check and append a new immutable version under the
        # same write transaction. Promotion never rewrites the version that
        # was verified and never uses INSERT OR REPLACE for history.
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?",
                             (str(artifact_id),)).fetchone()
            current = json.loads(row["payload_json"]) if row else None
            if current is None or int(current.get("version") or 0) != old_version:
                actual = None if current is None else current.get("version")
                raise ArtifactError("PROMOTE_CAS_CONFLICT",
                                    "artifact {} changed (now version {}) during promotion".format(artifact_id, actual))
            try:
                db.execute("INSERT INTO artifact_versions VALUES(?,?,?)",
                           (str(artifact_id), new_version, encoded))
            except sqlite3.IntegrityError as exc:
                raise ArtifactError("PROMOTE_CAS_CONFLICT",
                                    "artifact {} already has version {}".format(artifact_id, new_version)) from exc
            changed = db.execute(
                "UPDATE artifacts SET artifact_class=?, payload_json=? WHERE artifact_id=? AND payload_json=?",
                (to_class, encoded, str(artifact_id), row["payload_json"])).rowcount
            if changed != 1:
                raise ArtifactError("PROMOTE_CAS_CONFLICT", "artifact current row changed during promotion")
        return entry

    def verify(self, artifact_id: str, *, not_before: float | None = None,
               min_size_kb: int = 1, active_frames: "Sequence[int] | None" = None) -> dict[str, Any]:
        """Exact-frame-set verification with freshness and staged duplicates.

        ``active_frames`` names the frames where motion is expected.  Byte
        identical frames INSIDE the active stage are a failure (a frozen
        sequence cannot pass on noise or file existence); identical still
        pre-roll/tail frames or single-frame artifacts are legitimate.
        """
        entry = self._lookup_unchecked(artifact_id)
        if entry is None:
            raise ArtifactError("unknown artifact {}".format(artifact_id))
        # freshness is anchored to PRODUCTION START (the operation's start /
        # pre-artifact snapshot), never to the registration or promotion time
        with self._connect() as db:
            invalidation = db.execute("SELECT reason FROM artifact_invalidations WHERE artifact_id=? AND version=?",
                                      (str(artifact_id), int(entry['version']))).fetchone()
        return self._verify_entry(entry, not_before=not_before, min_size_kb=min_size_kb,
                                  active_frames=active_frames, invalidation=invalidation)

    def _verify_entry(self, entry, *, not_before=None, min_size_kb=1,
                      active_frames=None, invalidation=None):
        effective_not_before = float(
            entry.get("production_started_at_epoch") or entry["created_at_epoch"]
            if not_before is None else not_before)
        frames: dict[int, Any] = {}
        hashes: dict[str, int] = {}
        duplicate_frames: list[int] = []
        missing: list[int] = []
        too_small: list[int] = []
        stale: list[int] = []
        unreadable_frames: list[int] = []
        content_changed: list[int] = []
        for frame in entry["frame_set"]:
            path = frame_path(entry["pattern"], int(frame))
            if not path.is_file() or (self._is_typed(entry) and path.is_symlink()):
                missing.append(int(frame))
                continue
            # content check FIRST: a fake file padded past min_size_kb must
            # still fail — real EXR files carry the magic number
            readable = True
            validation = "not_applicable"
            if path.suffix.lower() == ".exr":
                readable, validation = _exr_structural_probe(path)
                if not readable:
                    unreadable_frames.append(int(frame))
                    continue
            before = path.stat()
            size = before.st_size
            if self._is_typed(entry) and (not stat.S_ISREG(before.st_mode) or size > 512*1024*1024):
                content_changed.append(int(frame))
                continue
            if size < min_size_kb * 1024:
                too_small.append(int(frame))
                continue
            if path.stat().st_mtime < effective_not_before:
                stale.append(int(frame))
                continue
            digest = _frame_hash(path)
            after = path.stat()
            if self._is_typed(entry) and ((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)
                    != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)):
                content_changed.append(int(frame))
            completion_snapshot = (entry.get("payload") or {}).get("completion_snapshot") or {}
            expected = completion_snapshot.get(str(frame), completion_snapshot.get(int(frame), {}))
            if expected:
                if self._is_typed(entry) and after.st_mtime_ns != expected.get('modified_ns'):
                    if int(frame) not in content_changed: content_changed.append(int(frame))
                expected_sha = str(expected.get("sha256") or "")
                expected_bytes = expected.get("bytes")
                expected_mtime = expected.get("mtime")
                if expected_mtime is None and expected.get("modified_ns") is not None:
                    expected_mtime = float(expected.get("modified_ns")) / 1_000_000_000.0
                if expected_sha and digest != expected_sha:
                    content_changed.append(int(frame))
                if expected_bytes is not None and int(expected_bytes) != size:
                    if int(frame) not in content_changed:
                        content_changed.append(int(frame))
                # The completion snapshot is taken before registration.  A
                # later mtime is evidence that the registered result was
                # replaced after the operation, even when a test restores the
                # same bytes.
                if expected_mtime is not None and path.stat().st_mtime > float(expected_mtime) + 1e-6:
                    if int(frame) not in content_changed:
                        content_changed.append(int(frame))
            if digest in hashes:
                duplicate_frames.append(int(frame))  # a later frame duplicating an earlier one
            else:
                hashes[digest] = int(frame)
            frames[int(frame)] = {"sha256": digest, "bytes": size,
                                  "mtime": path.stat().st_mtime}
        payload_active = (entry.get("payload") or {}).get("active_frames")
        selected_active = active_frames if active_frames is not None else payload_active
        active = sorted({int(f) for f in (selected_active if selected_active is not None else entry["frame_set"])})
        active_duplicates = [f for f in duplicate_frames if f in set(active)]
        dependencies = list(entry["dependencies"])
        metadata_present = bool(str(entry.get("colorspace") or "").strip()) and entry.get("premultiplied") is not None
        dependencies_present = bool(dependencies)
        usable = bool(
            not missing and not too_small and not unreadable_frames
            and not stale and not active_duplicates and not content_changed
            and metadata_present and dependencies_present and not invalidation
        )
        return {
            "artifact_id": entry["artifact_id"], "artifact_class": entry["artifact_class"],
            "ok": (not missing and not too_small and not unreadable_frames
                   and not active_duplicates and not content_changed and not invalidation),
            "invalidated": bool(invalidation),
            "invalidation_reason": invalidation[0] if invalidation else None,
            "readable": not unreadable_frames,
            "fresh": not stale,
            "no_duplicates": not active_duplicates,
            "metadata_present": metadata_present,
            "usable": usable,
            "active_frames": active,
            "missing": missing, "too_small": too_small, "stale_frames": stale,
            "unreadable_frames": unreadable_frames,
            "content_changed_frames": sorted(content_changed),
            "content_bound": not content_changed,
            "duplicate_frames": duplicate_frames,
            "active_duplicate_frames": active_duplicates,
            "frames": frames,
            "frame_set": entry["frame_set"],
            "colorspace": entry["colorspace"], "premultiplied": entry["premultiplied"],
            "dependencies": dependencies,
            "dependencies_present": dependencies_present,
        }
