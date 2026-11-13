"""Verify superseded files for observation without making them live inputs."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from .artifact_registry import ArtifactError
from .canonical import canonical_json, canonical_sha256


def _rows(registry, receipt):
    with closing(sqlite3.connect(registry.path.as_uri() + '?mode=ro', uri=True)) as db:
        key = (receipt['artifact_id'], receipt['version'])
        history = db.execute('SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?', key).fetchone()
        stored = db.execute('SELECT payload_json FROM artifact_operation_receipts WHERE artifact_id=? AND version=?', key).fetchone()
        invalid = db.execute('SELECT reason FROM artifact_invalidations WHERE artifact_id=? AND version=?', key).fetchone()
        current = db.execute('SELECT payload_json FROM artifacts WHERE artifact_id=?', key[:1]).fetchone()
    if not history or not stored or json.loads(stored[0]) != receipt:
        raise ArtifactError('HISTORICAL_RECEIPT_DB_MISMATCH')
    return json.loads(history[0]), invalid[0] if invalid else None, json.loads(current[0]) if current else None


def _graph_version(entry):
    prefix = 'graph:' + entry['task_id'] + ':'
    values = [tag[len(prefix):].rsplit(':version:', 1) for tag in entry['dependencies']
              if tag.startswith(prefix) and ':version:' in tag]
    if len(values) != 1 or not values[0][1].isdigit():
        raise ArtifactError('HISTORICAL_GRAPH_VERSION_REQUIRED')
    return values[0][0], int(values[0][1])


def verify_historical_operation_receipt(registry, receipt, *, superseding=None):
    """Recheck an immutable receipt, producer and bytes, never a live admission.

    ``superseding`` carries the already live-verified same-task receipt and its
    exact completed feedback row. Other invalidations and artifact dependency
    closures are intentionally unsupported by this observation-only reader.
    """
    receipt = json.loads(canonical_json(receipt))
    unsigned = dict(receipt)
    digest = unsigned.pop('registry_operation_receipt_sha256', None)
    if (digest != canonical_sha256(unsigned)
            or receipt.get('schema') != 'bridge.registry.operation-receipt/1.0'
            or receipt.get('state') != 'COMPLETED' or receipt.get('command') != 'artifact.register'
            or receipt.get('stage') != 'persisted_output' or receipt.get('registry_path') != str(registry.path)
            or type(receipt.get('version')) is not int or receipt['version'] <= 0
            or receipt.get('dependency_records') != {}
            or any(tag.startswith('artifact:') for tag in receipt.get('dependencies', []))):
        raise ArtifactError('HISTORICAL_RECEIPT_BINDING_REQUIRED')
    entry, invalid, current = baseline = _rows(registry, receipt)
    if canonical_sha256(entry) != receipt['artifact_payload_sha256']:
        raise ArtifactError('HISTORICAL_RECEIPT_DB_MISMATCH')
    for key in ('artifact_id', 'version', 'task_id', 'operation_id', 'artifact_class', 'pattern',
                'frame_set', 'scene_fingerprint', 'colorspace', 'premultiplied', 'dependencies', 'registered_at_epoch'):
        if entry.get(key) != receipt.get(key):
            raise ArtifactError('HISTORICAL_RECEIPT_BINDING_REQUIRED', key)
    if invalid and (not isinstance(superseding, dict)
            or superseding['receipt']['artifact_id'] != receipt['artifact_id']
            or superseding['receipt']['version'] <= receipt['version']):
        raise ArtifactError('HISTORICAL_SUPERSESSION_REQUIRED')
    supersession = _supersession(registry, entry, invalid, superseding)
    if (entry['operation_receipt_sha256'] != receipt['producer_receipt_sha256']
            or entry['payload']['completion_snapshot'] != receipt['frame_snapshots']
            or entry['payload']['completion_metadata'] != receipt['completion_metadata']):
        raise ArtifactError('HISTORICAL_RECEIPT_BINDING_REQUIRED')
    fact = registry._operation_facts(receipt['operation_id'], task_id=receipt['task_id'],
        frames=receipt['frame_set'], pattern=receipt['pattern'], scene_fingerprint=receipt['scene_fingerprint'])
    if (canonical_sha256(fact) != receipt['producer_fact_sha256']
            or fact.get('operation_receipt_sha256') != receipt['producer_receipt_sha256']):
        raise ArtifactError('HISTORICAL_PRODUCER_CHANGED')
    metadata = registry._receipt_metadata(fact, receipt['frame_set'], receipt['colorspace'],
        receipt['premultiplied'], receipt['dependencies'], receipt['scene_fingerprint'], receipt['operation_id'])
    if (metadata != receipt['completion_metadata'] or entry.get('project_color') != registry._project_color(fact, receipt['colorspace'])
            or entry.get('output_verification') != registry._output_verification(fact)):
        raise ArtifactError('HISTORICAL_METADATA_CHANGED')
    with registry._receipt_source_admission(receipt['current_source']) as source, \
            registry._typed_admission(fact, receipt['pattern'], receipt['frame_set'], metadata=metadata) as admission:
        if source[0] != receipt['current_source'] or _rows(registry, receipt) != baseline:
            raise ArtifactError('HISTORICAL_RECEIPT_CHANGED_DURING_READ')
        # Invalidations remain on the actual ledger. This checks only the old
        # bytes; the return value below cannot be used as a live registry entry.
        if not registry._verify_entry(entry).get('usable'):
            raise ArtifactError('HISTORICAL_OUTPUT_CHANGED')
        registry._check_admission_identity(source[1])
        registry._check_admission_identity(admission)
    if _rows(registry, receipt) != baseline:
        raise ArtifactError('HISTORICAL_RECEIPT_CHANGED_DURING_READ')
    _check_supersession(supersession)
    return {'receipt': receipt, 'historical': True, 'consumable': False, 'invalidation_reason': invalid}

def _supersession(registry, entry, invalid, superseding):
    if invalid is None:
        return
    current = superseding['registry']._lookup_unchecked(superseding['receipt']['artifact_id']) if isinstance(superseding, dict) else None
    if not isinstance(superseding, dict):
        raise ArtifactError('HISTORICAL_INVALIDATION_UNSUPPORTED')
    later = superseding['receipt']
    if (later['registry_path'] != str(registry.path)
            or later['task_id'] != entry['task_id']
            or current is None
            or canonical_sha256(current) != later['artifact_payload_sha256']):
        raise ArtifactError('HISTORICAL_SUPERSESSION_REQUIRED')
    # Reuse a trusted producer-backed registry, not a success flag supplied
    # by the result JSON. The later receipt still has normal live rules.
    later = json.loads(canonical_json(later))
    later_rows = _rows(superseding['registry'], later)
    superseding['registry'].verify_operation_receipt(later)
    if _rows(superseding['registry'], later) != later_rows:
        raise ArtifactError('HISTORICAL_SUPERSESSION_CHANGED_DURING_READ')
    graph, old_version = _graph_version(entry)
    new_graph, new_version = _graph_version(current)
    feedback = superseding['feedback']
    if (graph != new_graph or new_version <= old_version
            or invalid != 'graph {} version {}'.format(graph, new_version)
            or feedback['task_id'] != entry['task_id'] or feedback['version'] != new_version
            or feedback['state'] != 'COMPLETE'):
        raise ArtifactError('HISTORICAL_SUPERSESSION_REQUIRED')
    path = superseding['control'] / 'diagnostic.sqlite3'
    if path.is_symlink() or not path.is_file():
        raise ArtifactError('HISTORICAL_GRAPH_SOURCE_REQUIRED')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT state,payload FROM feedback_versions WHERE graph_id=? AND version=?',
                         (graph, new_version)).fetchone()
    if (not row or row[0] != 'COMPLETE' or json.loads(row[1]).get('task_id') != entry['task_id']
            or any(feedback.get(k) != v for k, v in json.loads(row[1]).items())):
        raise ArtifactError('HISTORICAL_GRAPH_SOURCE_REQUIRED')
    return {'registry': superseding['registry'], 'receipt': later, 'rows': later_rows,
            'path': path, 'key': (graph, new_version), 'feedback_row': row}


def _check_supersession(evidence):
    if evidence is None:
        return
    path = evidence['path']
    if path.is_symlink() or not path.is_file():
        raise ArtifactError('HISTORICAL_GRAPH_CHANGED_DURING_READ')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT state,payload FROM feedback_versions WHERE graph_id=? AND version=?',
                         evidence['key']).fetchone()
    if row != evidence['feedback_row']:
        raise ArtifactError('HISTORICAL_GRAPH_CHANGED_DURING_READ')
    if _rows(evidence['registry'], evidence['receipt']) != evidence['rows']:
        raise ArtifactError('HISTORICAL_SUPERSESSION_CHANGED_DURING_READ')


def verify_historical_artifact(registry, entry, fact, *, superseding):
    """Observe the exact persisted Nuke entry with its signed producer fact."""
    if (any(tag.startswith('artifact:') for tag in entry['dependencies'])
            or entry['task_id'] != superseding['receipt']['task_id']):
        raise ArtifactError('HISTORICAL_DEPENDENCY_UNSUPPORTED')
    def rows():
        with closing(sqlite3.connect(registry.path.as_uri()+'?mode=ro', uri=True)) as db:
            key=(entry['artifact_id'],entry['version'])
            saved=db.execute('SELECT payload_json FROM artifact_versions WHERE artifact_id=? AND version=?',key).fetchone()
            invalid=db.execute('SELECT reason FROM artifact_invalidations WHERE artifact_id=? AND version=?',key).fetchone()
        if not saved or json.loads(saved[0]) != entry:
            raise ArtifactError('HISTORICAL_RECEIPT_DB_MISMATCH')
        return invalid[0] if invalid else None
    invalid=rows()
    supersession=_supersession(registry,entry,invalid,superseding)
    payload=entry['payload']
    if (fact.get('task_id')!=entry['task_id'] or fact.get('operation_receipt_sha256')!=entry['operation_receipt_sha256']
            or fact.get('metadata')!=payload.get('completion_metadata')
            or fact.get('frame_snapshots')!=payload.get('completion_snapshot')
            or fact.get('dependencies')!=payload.get('completion_dependencies')
            or sorted(fact.get('dependencies',[]))!=entry['dependencies']
            or fact.get('scene_fingerprint')!=entry['scene_fingerprint']):
        raise ArtifactError('HISTORICAL_PRODUCER_CHANGED')
    with registry._typed_admission(fact,entry['pattern'],entry['frame_set'],metadata=payload['completion_metadata']) as admission:
        if not registry._verify_entry(entry).get('usable') or rows()!=invalid:
            raise ArtifactError('HISTORICAL_OUTPUT_CHANGED')
        registry._check_admission_identity(admission)
    if rows()!=invalid:
        raise ArtifactError('HISTORICAL_RECEIPT_CHANGED_DURING_READ')
    _check_supersession(supersession)
    return {'historical':True,'consumable':False,'invalidation_reason':invalid}
