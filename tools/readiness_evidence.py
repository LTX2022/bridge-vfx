"""Shared evidence identity and non-vacuous readiness contracts."""
from __future__ import annotations
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import ast
import sys
import importlib.util
import tempfile
from functools import lru_cache

DOMAINS = ('pyro_smoke_v1','pyro_fire_v1','particles_v1','water_ocean_v1','water_flip_v1','crowd_agents_v1','swarm_flocking_v1','vellum_cloth_v1','vellum_softbody_grains_v1','hair_fur_v1','rbd_destruction_v1','procedural_geometry_v1','material_lookdev_v1','lighting_camera_render_v1','nuke_composite_v1','explosion_composite_v1')
LEGACY = ('C1-A','C1-B','C1-C','C2-A','C2-B','C2-C','C4-A','C4-B','C4-C','C4-D','C3-A','C3-B','C3-C','C5-A','C5-B','C6-A','C6-B')
EXTENDED = ('P0-INPUT','P1-RECOVERY','P1-TRANSACTIONS','P1-STOP-LEDGER','P2-PRODUCTION','P2-SAVE-REOPEN','P2-NUKE-BINDING','P2-OPERATION-ROUTING','P3-NATIVE-VERSIONS','P3-COMPOSITES','P4-VIDEO','P4-ATTACHMENTS','P4-FEEDBACK','P4-DYNAMIC','P4-DISK','P4-BOUNDS','P4-CACHE-CONSENT','P5-HY3','P5-LIFECYCLE','P5-OFFLINE','P5-LIVE-PREFLIGHT')
REQUIRED = LEGACY + EXTENDED + tuple('DOMAIN-' + domain for domain in DOMAINS)
_STATIC_ROWS = frozenset({'P3-NATIVE-VERSIONS'})
_INSTALLATION_ROWS = frozenset({'P5-LIFECYCLE', 'P5-OFFLINE'})
_PREFLIGHT_ROWS = frozenset({'P5-LIVE-PREFLIGHT'})
ROW_EVIDENCE_CLASSES = {
    identifier: ('static' if identifier in _STATIC_ROWS else
                 'installation' if identifier in _INSTALLATION_ROWS else
                 'preflight' if identifier in _PREFLIGHT_ROWS else 'functional')
    for identifier in REQUIRED
}
ROW_IDENTITY_KEYS = ('evidence_ref', 'build_id')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_ASSERTION_REF = re.compile(r'^tests/.+:[1-9][0-9]*$')
_PRODUCT_PREFIXES = ('packages/', 'plugins/', 'controller-entry/', 'skills/', 'agent-plugin/')
_RELEASE_PREFIXES = _PRODUCT_PREFIXES + ('outputs/',)
_RECEIPT_PREFIXES = ('outputs/',)
_STATIC_EVIDENCE_PREFIXES = ('packages/', 'plugins/', 'controller-entry/', 'docs/', 'skills/', 'tests/', 'tools/', 'agent-plugin/', 'handover/')
_TERMINAL_STATES = frozenset({'PASS', 'COMPLETED', 'STOP_CONFIRMED'})
_NEGATIVE_OPERATION_STATES = frozenset({'REJECTED', 'FAILED', 'CANCELLED', 'STOP_CONFIRMED', 'STOPPED', 'BUDGET_REACHED'})
_FORMAL_RECEIPT_SCHEMAS = frozenset({
    'bridge.readiness.formal_operation/1',
    'bridge.houdini.scene-transition-operation/1.0',
    'bridge.houdini.lifecycle_fact/1.0',
    'bridge.houdini.render.execution_fact/1.0',
    'bridge.nuke.render-operation/1.0',
})
_SYNTHETIC_OPERATION_PREFIXES = ('readiness-', 'synthetic-', 'fake-', 'fixture-', 'mapping-')
_EVIDENCE_TYPES = frozenset({'formal_operation', 'preflight_rejection', 'static_check'})
_SCENE_COMMANDS = frozenset({'scene.open_hip', 'scene.reopen_owned_hip', 'scene.reopen_task_hip'})
_DOMAIN_COMMAND_STAGES = {
    'agent.fx.build_preview': 'build', 'node.info': 'inspect',
    'agent.fx.apply_candidate': 'edit', 'scene.save_hip': 'save',
    'scene.reopen_task_hip': 'reopen', 'scene.reopen_owned_hip': 'reopen',
    'agent.fx.simulate_segment': 'preview', 'agent.fx.collect_evidence': 'output',
    'agent.nuke.composite.build_graph': 'build', 'agent.nuke.composite.audit_lineage': 'inspect',
    'agent.nuke.composite.apply_candidate': 'edit', 'scene.save_script': 'save',
    'scene.open_script': 'reopen', 'agent.nuke.composite.preview': 'preview',
    'agent.nuke.composite.render': 'output',
}


def domain_stage_errors(identifier, stages):
    if not isinstance(identifier, str) or not identifier.startswith('DOMAIN-'):
        return []
    required = {'build', 'inspect', 'edit', 'preview', 'save', 'reopen', 'output'}
    if identifier in {'DOMAIN-lighting_camera_render_v1', 'DOMAIN-material_lookdev_v1'}:
        required.add('render')
    missing = sorted(required - set(stages))
    return [identifier + ': missing actual producer stages: ' + ', '.join(missing)] if missing else []


def _diagnostic_marked(value):
    if isinstance(value, Mapping):
        if (value.get('schema') == 'bridge.houdini.software-boundary-fact/1.0'
                or value.get('formal_operation') is False
                or value.get('software_boundary_execution') == 'diagnostic_only'):
            return True
        return any(_diagnostic_marked(child) for child in value.values())
    return isinstance(value, list) and any(_diagnostic_marked(child) for child in value)


def _provider_fact(document):
    if document.get('schema') == 'bridge.readiness.formal_operation/1':
        provider = document.get('provider_fact')
        return provider if isinstance(provider, Mapping) else {}
    return document


@lru_cache(maxsize=1)
def _nuke_receipt_module():
    path = Path(__file__).resolve().parents[1] / 'packages/nuke-bridge/src/nuke_bridge/operation_receipts.py'
    spec = importlib.util.spec_from_file_location('readiness_nuke_operation_receipts', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _owned_receipt_module():
    path = Path(__file__).resolve().parents[1] / 'packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py'
    spec = importlib.util.spec_from_file_location('readiness_owned_process', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _houdini_producer_module():
    path = Path(__file__).resolve().parents[1] / 'packages/houdini-bridge/src/houdini_bridge/operation_receipts.py'
    spec = importlib.util.spec_from_file_location('readiness_houdini_producer_receipts', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _producer_stage(document):
    provider = _provider_fact(document)
    if provider.get('schema') == 'bridge.houdini.scene-transition-operation/1.0':
        command = provider.get('command')
        return command if command in _SCENE_COMMANDS else None
    if provider.get('schema') == 'bridge.houdini.render.execution_fact/1.0':
        return 'render' if provider.get('command') == 'render.start' and provider.get('kind') == 'render' else None
    if provider.get('schema') == 'bridge.nuke.render-operation/1.0':
        command = provider.get('command')
        return (_nuke_receipt_module().COMMAND_STAGES.get(command)
                if provider.get('kind') == 'render' and isinstance(command, str) else None)
    return None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()



class PackageEvidenceResolver:
    """Resolve immutable evidence using a controller-authenticated package manifest.

    The caller supplies the manifest digest out of band. Receipt paths stay
    logical producer identities; this object controls only physical reads.
    """
    def __init__(self, package_root, *, manifest_sha256,
                 source_relative_root='source/bridge-skills',
                 manifest_path='package-manifest.json',
                 map_path='evidence/bound-files/path-map.json'):
        root = Path(package_root)
        if any(path.is_symlink() for path in (root, *root.parents)) or not root.is_dir():
            raise ValueError('package root must be a real directory')
        self.package_root = root.resolve()
        self.source_relative_root = self._relative(source_relative_root)
        self.source_root = self._physical(self.source_relative_root, file=False)
        manifest_file = self._physical(self._relative(manifest_path))
        if not _is_sha256(manifest_sha256) or digest(manifest_file) != manifest_sha256:
            raise ValueError('package manifest does not match controller digest')
        manifest = self._json(manifest_file)
        if (not isinstance(manifest, dict)
                or manifest.get('schema') != 'bridge.s06.package_manifest/1.0'
                or not isinstance(manifest.get('files'), list)
                or manifest.get('file_count') != len(manifest['files'])):
            raise ValueError('invalid package manifest')
        self.files = {}
        for item in manifest['files']:
            if not isinstance(item, dict):
                raise ValueError('invalid package manifest file')
            name = self._relative(item.get('path'))
            if name in self.files or not self._metadata(item):
                raise ValueError('duplicate or invalid package manifest binding')
            self.files[name] = dict(item)
        map_name = self._relative(map_path)
        path_map = self._json(self._manifest_file(map_name))
        if not isinstance(path_map, dict):
            raise ValueError('package path map must be an object')
        self.path_map = {}
        for logical, entry in path_map.items():
            if (not isinstance(logical, str) or not logical or not isinstance(entry, dict)
                    or entry.get('original_logical_path') != logical
                    or not self._metadata(entry)
                    or type(entry.get('modified_ns')) is not int or entry['modified_ns'] < 0):
                raise ValueError('invalid original logical path binding')
            target = self._relative(entry.get('package_relative_path'))
            # Historical logical aliases may share one target, but each must
            # independently match the same authenticated manifest bytes.
            expected = self.files.get(target)
            if expected is None or any(entry[key] != expected[key] for key in ('sha256', 'bytes')):
                raise ValueError('path map is not bound to authenticated package manifest')
            self._manifest_file(target)
            self.path_map[logical] = dict(entry)
        self.check_source(self.source_root)

    @staticmethod
    def _relative(value):
        if (not isinstance(value, str) or not value or '\\' in value or ':' in value
                or value.startswith('/') or any(part in ('', '.', '..') for part in value.split('/'))):
            raise ValueError('package path must be a strict relative path')
        return value

    @staticmethod
    def _metadata(value):
        return (isinstance(value.get('sha256'), str) and bool(_SHA256.fullmatch(value['sha256']))
                and type(value.get('bytes')) is int and value['bytes'] >= 0)

    @staticmethod
    def _json(path):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate JSON key in package verification configuration')
                result[key] = value
            return result
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)

    def _physical(self, relative, *, file=True):
        path = self.package_root
        for part in relative.split('/'):
            path = path / part
            if path.is_symlink():
                raise ValueError('package path traverses a symlink')
        if not path.is_relative_to(self.package_root) or (file and not path.is_file()):
            raise ValueError('package file is missing or outside package root')
        if not file and not path.is_dir():
            raise ValueError('package source root is missing')
        return path

    def _manifest_file(self, relative):
        bound = self.files.get(relative)
        if bound is None:
            raise ValueError('package file is not in authenticated manifest')
        actual = self._physical(relative)
        if actual.stat().st_size != bound['bytes'] or digest(actual) != bound['sha256']:
            raise ValueError('package file bytes or hash differ from authenticated manifest')
        return actual

    def package_input(self, path):
        path = Path(path)
        if path.is_absolute():
            try:
                name = path.relative_to(self.package_root).as_posix()
            except ValueError as exc:
                raise ValueError('package input must be inside configured package root') from exc
        else:
            name = path.as_posix()
        return self._manifest_file(self._relative(name))

    def check_source(self, root):
        if Path(root).absolute() != self.source_root:
            raise ValueError('validator root does not match configured package source root')
        for name in self.files:
            if name.startswith(self.source_relative_root + '/'):
                self._manifest_file(name)
        for path in self.source_root.rglob('*'):
            if path.is_symlink():
                raise ValueError('package source traverses a symlink')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                self._manifest_file(path.relative_to(self.package_root).as_posix())

    def source_file(self, logical, *, expected_sha256=None):
        raw = str(logical)
        if (not raw or raw.startswith('/') or '\\' in raw or ':' in raw
                or '..' in raw.split('/')):
            raise ValueError('source path must be a safe relative path')
        name = self._relative(PurePosixPath(raw).as_posix())
        actual = self._manifest_file(self.source_relative_root + '/' + name)
        if expected_sha256 is not None and digest(actual) != expected_sha256:
            raise ValueError('source hash differs from original evidence binding')
        return actual

    def resolve(self, logical, *, expected_sha256, expected_bytes=None, producer_modified_ns=None):
        if not isinstance(logical, str) or logical not in self.path_map:
            raise ValueError('original logical evidence path is not mapped')
        entry = self.path_map[logical]
        if not _is_sha256(expected_sha256) or entry['sha256'] != expected_sha256:
            raise ValueError('mapped hash differs from original producer evidence')
        if expected_bytes is not None and (type(expected_bytes) is not int or entry['bytes'] != expected_bytes):
            raise ValueError('mapped bytes differ from original producer evidence')
        # Package stat time describes copying, while this value is the original
        # producer fact authenticated as part of the unmodified raw receipt.
        if producer_modified_ns is not None and (type(producer_modified_ns) is not int or entry['modified_ns'] != producer_modified_ns):
            raise ValueError('mapped original time differs from producer evidence')
        return self._manifest_file(entry['package_relative_path'])

    def file(self, root, logical, *, expected_sha256):
        if Path(root).absolute() != self.source_root:
            raise ValueError('validator root does not match configured package source root')
        if isinstance(logical, str) and not Path(logical).is_absolute() and not logical.startswith('outputs/'):
            return self.source_file(logical, expected_sha256=expected_sha256)
        return self.resolve(logical, expected_sha256=expected_sha256)

    def read_supervisor(self, directory, identity):
        # Keep raw signed envelopes and identity unchanged while reusing the
        # original verifier, which requires sibling started/stopped/key files.
        owned = _owned_receipt_module()
        files = importlib.import_module(owned.open_private_file.__module__)
        names = ('started.json', 'stopped.json', 'receipt.key')
        with tempfile.TemporaryDirectory(prefix='bridge-read-receipt-') as temp:
            temporary_root = files.ensure_private_directory(temp)
            try:
                for name in names:
                    logical = str(Path(directory) / name)
                    entry = self.path_map.get(logical)
                    if entry is None:
                        raise ValueError('supervisor evidence is not mapped')
                    actual = self._manifest_file(entry['package_relative_path'])
                    snapshot = temporary_root / name
                    files.atomic_write(snapshot, actual.read_bytes(), owned_root=temporary_root)
                    snapshot.chmod(0o400)
                return owned.read_receipt(temp, 'stopped', identity=identity)
            finally:
                for name in names:
                    files.remove_owned_path(temporary_root / name, owned_root=temporary_root)


def _evidence_file(root, logical, checksum, resolver=None):
    if resolver is not None:
        return resolver.file(root, logical, expected_sha256=checksum)
    return Path(root) / logical if root is not None else Path(logical)


def build_id(root, *, resolver=None):
    if resolver is not None:
        resolver.check_source(root)
    root = Path(root)
    entries = []
    for name in ('packages', 'plugins', 'tools', 'skills', 'tests', 'docs', 'controller-entry', 'agent-plugin', 'handover'):
        for path in sorted((root / name).rglob('*'), key=lambda path: path.relative_to(root).as_posix()):
            if (path.is_file() and path.name != '.DS_Store' and '__pycache__' not in path.parts
                    and path.suffix not in ('.pyc', '.pyo')):
                entries.append((path.relative_to(root).as_posix(), digest(path)))
    for name in ('outputs/live-validation/index.json', 'pyproject.toml'):
        if (root / name).is_file():
            if name == 'outputs/live-validation/index.json':
                # Evidence records bind this build, so their append-only values
                # cannot recursively become part of the source build identity.
                # The declaration itself is still required and fingerprinted.
                declaration = json.loads((root / name).read_text())
                for field in ('entries', 'model_routes', 'workbuddy_runs'):
                    declaration[field] = []
                declaration['generated_at'] = None
                checksum = hashlib.sha256(json.dumps(declaration, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                entries.append((name, checksum))
            else:
                entries.append((name, digest(root / name)))
    return hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and bool(_SHA256.fullmatch(value.lower()))


def _valid_string_list(value, *, allow_empty=False):
    return (isinstance(value, list)
            and (allow_empty or bool(value))
            and all(isinstance(item, str) and item for item in value)
            and len(value) == len(set(value)))


def _contains_key(value, keys):
    if isinstance(value, Mapping):
        return any(key in value and key in keys for key in value) or any(
            _contains_key(child, keys) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, keys) for child in value)
    return False


def _safe_relative_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts:
        return None
    return path


def _path_allowed(path, prefixes):
    name = path.as_posix()
    return any(name.startswith(prefix) for prefix in prefixes)


def _file_binding(root, value, label, prefixes, *, check_files, resolver=None):
    """Validate a content-addressed repository file reference.

    Strings are deliberately not accepted.  A path without the observed hash
    is only a pointer supplied by the mapper, not evidence that the shipped
    file was the file executed.
    """
    errors = []
    if not isinstance(value, Mapping):
        return None, [label + ' must be a {path, sha256} file binding']
    path = _safe_relative_path(value.get('path'))
    if path is None:
        errors.append(label + ': path must be a safe relative path')
        return None, errors
    if not _path_allowed(path, prefixes):
        errors.append(label + ': path is not a production/release file')
    checksum = value.get('sha256')
    if not _is_sha256(checksum):
        errors.append(label + ': sha256 must be a lowercase 64-hex digest')
    if root is None:
        return path, errors
    if check_files:
        try:
            actual = _evidence_file(root, value['path'], checksum, resolver)
            if actual.is_symlink() or not actual.is_file():
                errors.append(label + ': file is missing or is a symlink ' + path.as_posix())
            elif _is_sha256(checksum) and digest(actual) != checksum.lower():
                errors.append(label + ': file hash does not match ' + path.as_posix())
        except (OSError, ValueError, TypeError) as exc:
            errors.append(label + ': file is not verifiable: ' + str(exc))
    return path, errors


def _canonical_sha256(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _receipt_digest(document):
    """Recompute a supported producer digest from the persisted receipt body."""
    provider_fact = document.get('provider_fact')
    if (document.get('schema') == 'bridge.readiness.formal_operation/1'
            and isinstance(provider_fact, Mapping)):
        provider_digest, provider_recomputed = _receipt_digest(provider_fact)
        if (not _is_sha256(provider_digest) or not _is_sha256(provider_recomputed)
                or provider_digest.lower() != provider_recomputed.lower()):
            return document.get('operation_receipt_sha256'), None
        return document.get('operation_receipt_sha256'), provider_digest
    schema = document.get('schema')
    if schema == 'bridge.houdini.lifecycle_fact/1.0' and 'fact_digest' in document:
        return document.get('fact_digest'), _canonical_sha256(
            {key: value for key, value in document.items() if key != 'fact_digest'})
    if isinstance(schema, str) and schema in {'bridge.houdini.scene-transition-operation/1.0',
                  'bridge.houdini.render.execution_fact/1.0', 'bridge.nuke.render-operation/1.0'} and 'operation_receipt_sha256' in document:
        return document.get('operation_receipt_sha256'), _canonical_sha256(
            {key: value for key, value in document.items() if key != 'operation_receipt_sha256'})
    if schema == 'bridge.houdini.software-boundary-fact/1.0' and 'operation_receipt_sha256' in document:
        body = json.loads(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':'), allow_nan=False))
        supplied = body.pop('operation_receipt_sha256', None)
        result = body.get('result')
        artifact = result.get('output_artifact') if isinstance(result, dict) else None
        if isinstance(artifact, dict):
            artifact.pop('operation_receipt_sha256', None)
        return supplied, _canonical_sha256(body)
    return None, None


def _formal_receipt_source_errors(document, label):
    errors = []
    if _diagnostic_marked(document):
        errors.append(label + ': recursive diagnostic schema/marker is not a formal-operation provider')
    schema = document.get('schema')
    if schema == 'bridge.houdini.software-boundary-fact/1.0':
        errors.append(label + ': software-boundary diagnostic schema is not a formal-operation provider')
    elif schema == 'bridge.readiness.formal_operation/1':
        provider = document.get('provider_fact')
        if not isinstance(provider, Mapping):
            errors.append(label + ': formal operation provider fact is missing')
        elif provider.get('schema') == 'bridge.houdini.software-boundary-fact/1.0':
            errors.append(label + ': diagnostic boundary fact cannot be wrapped as a formal operation')
        else:
            for field in ('operation_id', 'state'):
                if document.get(field) != provider.get(field):
                    errors.append(label + ': wrapper ' + field + ' does not match the provider fact')
            if document.get('operation_receipt_sha256') != provider.get('operation_receipt_sha256'):
                errors.append(label + ': wrapper digest does not match the formal provider receipt')
            errors.extend(_formal_receipt_source_errors(provider, label + '.provider_fact'))
    elif schema == 'bridge.houdini.scene-transition-operation/1.0':
        for field in ('task_id', 'operation_id', 'state', 'request_id', 'started_at', 'completed_at'):
            if not isinstance(document.get(field), str) or not document.get(field):
                errors.append(label + ': scene-transition provider fact missing ' + field)
        if document.get('command') not in _SCENE_COMMANDS or document.get('state') != 'COMPLETED':
            errors.append(label + ': unsupported scene-transition command/state')
        request = document.get('request')
        result = document.get('result')
        if (not isinstance(request, Mapping) or not isinstance(request.get('path'), str)
                or not Path(request.get('path', '')).is_absolute()
                or not _is_sha256(request.get('sha256'))):
            errors.append(label + ': scene-transition content-addressed HIP request is missing')
            request = {}
        basis = {key: document.get(key) for key in ('task_id', 'command', 'request_id')}
        basis['request'] = request
        if document.get('request_sha256') != _canonical_sha256(basis):
            errors.append(label + ': scene-transition request digest mismatch')
        if (not isinstance(result, Mapping) or result.get('path') != request.get('path')
                or result.get('sha256') != request.get('sha256')
                or result.get('snapshot_sha256') != request.get('sha256')
                or not isinstance(result.get('snapshot_path'), str)
                or not Path(result.get('snapshot_path', '')).is_absolute()):
            errors.append(label + ': scene-transition result/snapshot does not bind loaded HIP')
        before, after = document.get('before_identity'), document.get('after_identity')
        if (not isinstance(before, Mapping) or not isinstance(after, Mapping)
                or any(not isinstance(before.get(key), str) or not before.get(key)
                       or before.get(key) != after.get(key) for key in ('session_id', 'process_generation'))
                or type(document.get('before_scene_epoch')) is not int
                or type(document.get('after_scene_epoch')) is not int
                or before.get('scene_epoch') != document.get('before_scene_epoch')
                or after.get('scene_epoch') != document.get('after_scene_epoch')
                or document['after_scene_epoch'] <= document['before_scene_epoch']
                or type(document.get('store_cas')) is not int or document['store_cas'] < 2):
            errors.append(label + ': scene-transition host identity/epoch/CAS invariant failed')
    elif schema == 'bridge.houdini.lifecycle_fact/1.0':
        if not isinstance(document.get('source'), str) or not document.get('source'):
            errors.append(label + ': lifecycle fact source provider is missing')
    elif schema == 'bridge.nuke.render-operation/1.0':
        errors.extend(label + ': ' + error for error in _nuke_receipt_module().receipt_errors(document))
    elif schema == 'bridge.houdini.render.execution_fact/1.0':
        errors.extend(_houdini_render_errors(document, label))
    else:
        errors.append(label + ': unsupported formal-operation provider receipt schema')
    return errors


def _houdini_render_errors(document, label):
    try:
        return _houdini_render_source_errors(document, label)
    except (TypeError, ValueError, KeyError):
        return [label + ': invalid Houdini render receipt field types/content']


def _houdini_render_source_errors(document, label):
    errors = []
    def require(condition, message):
        if not condition: errors.append(label + ': ' + message)
    require(document.get('command') == 'render.start' and document.get('kind') == 'render'
            and document.get('execution_kind') == 'task_owned_host', 'invalid Houdini formal render producer')
    for field in ('task_id', 'operation_id', 'request_id', 'finished_at'):
        require(isinstance(document.get(field), str) and bool(document.get(field)), 'render missing ' + field)
    require(document.get('operation_id') == document.get('request_id'), 'render request/operation ID mismatch')
    frames = document.get('frame_set')
    valid_frames = (isinstance(frames, list) and bool(frames) and len(frames) <= 12
                    and all(type(f) is int and f > 0 for f in frames) and len(frames) == len(set(frames)))
    require(valid_frames, 'invalid render exact frame set')
    frames = frames if valid_frames else []
    snapshots = document.get('frame_snapshots')
    require(isinstance(snapshots, Mapping), 'render snapshots missing')
    snapshots = snapshots if isinstance(snapshots, Mapping) else {}
    completed = document.get('state') == 'COMPLETED'
    if completed:
        require(document.get('frames_done') == frames and set(snapshots) == {str(f) for f in frames},
                'completed render does not bind every frame')
    require(set(snapshots).issubset({str(f) for f in frames}), 'render snapshot frames exceed request')
    for snapshot in snapshots.values():
        require(isinstance(snapshot, Mapping) and isinstance(snapshot.get('path'), str)
                and Path(snapshot['path']).is_absolute() and _is_sha256(snapshot.get('sha256'))
                and type(snapshot.get('bytes')) is int and snapshot['bytes'] > 0
                and type(snapshot.get('modified_ns')) is int and snapshot['modified_ns'] > 0,
                'render snapshot content identity invalid')
    done = document.get('frames_done')
    require(isinstance(done, list) and all(type(f) is int and f in frames for f in done)
            and len(done) == len(set(done)), 'render completed frames invalid')
    done = done if isinstance(done, list) and all(type(f) is int for f in done) else []
    require(all(isinstance(snapshots.get(str(f)), Mapping)
                and snapshots[str(f)].get('path') == _nuke_receipt_module().frame_path(document.get('output_pattern'), f)
                for f in done), 'render frame path differs from output pattern')
    require(isinstance(document.get('output_pattern'), str)
            and Path(document['output_pattern']).is_absolute()
            and isinstance(document.get('render_target'), str) and document['render_target'].startswith('/')
            and type(document.get('budget_seconds')) in {int, float} and 0 < document['budget_seconds'] <= 120
            and type(document.get('started_at_epoch')) in {int, float} and document['started_at_epoch'] > 0
            and _valid_string_list(document.get('dependencies'), allow_empty=True), 'render request scope/budget invalid')
    scene = document.get('scene')
    scene = scene if isinstance(scene, Mapping) else {}
    require(_is_sha256(scene.get('snapshot_sha256')) and isinstance(scene.get('snapshot_path'), str)
            and Path(scene['snapshot_path']).is_absolute() and isinstance(scene.get('scene_contract'), Mapping),
            'render saved scene content/contract missing')
    identity = document.get('host_identity')
    identity = identity if isinstance(identity, Mapping) else {}
    require(identity.get('task_id') == document.get('task_id') and type(identity.get('pid')) is int
            and identity['pid'] > 0 and type(identity.get('scene_epoch')) is int
            and _is_sha256(identity.get('plugin_build'))
            and all(isinstance(identity.get(k), str) and identity[k] for k in
                    ('session_id', 'launch_nonce', 'process_generation')), 'render owned host identity invalid')
    contract = scene.get('scene_contract')
    contract = contract if isinstance(contract, Mapping) else {}
    nodes = contract.get('nodes')
    nodes = nodes if isinstance(nodes, list) else []
    by_path = {node.get('path'):node for node in nodes
               if isinstance(node, Mapping) and isinstance(node.get('path'), str)}
    target_node = by_path.get(document.get('render_target')) if isinstance(document.get('render_target'), str) else None
    try:
        _houdini_producer_module().validate_scene_contract_header(
            contract, task_id=document.get('task_id'), allow_legacy_v1=True)
        valid_contract = True
    except ValueError:
        valid_contract = False
    require(valid_contract and scene.get('identity') == identity
            and contract.get('task_id') == document.get('task_id') and bool(nodes)
            and scene.get('scene_contract_sha256') == _canonical_sha256(contract)
            and isinstance(target_node, Mapping) and target_node.get('type') == 'Driver/usdrender',
            'render saved task contract/target identity mismatch')
    if contract.get('schema') in {'houdini.task_scene_contract/2.0', 'houdini.task_scene_contract/2.1'}:
        for node in nodes:
            channels = node.get('parameter_channels') if isinstance(node, Mapping) else None
            parameters = node.get('parameters') if isinstance(node, Mapping) else None
            valid_channels = isinstance(channels, Mapping) and isinstance(parameters, Mapping)
            if valid_channels:
                available = set()
                for name, channel in channels.items():
                    valid = False
                    if isinstance(channel, Mapping):
                        valid = (isinstance(name, str) and type(channel.get('evaluated_available')) is bool
                            and (channel.get('expression') is None or isinstance(channel.get('expression'), str))
                            and (channel.get('reference_path') is None or isinstance(channel.get('reference_path'), str))
                            and isinstance(channel.get('keyframes'), list)
                            and all(isinstance(k, str) for k in channel['keyframes'])
                            and ('expression_language' not in channel or isinstance(channel['expression_language'], str))
                            and ('non_value_type' not in channel or channel.get('non_value_type') in {'Button','Label','Separator'})
                            and (channel.get('evaluated_available') or bool(channel.get('expression') or channel.get('keyframes'))
                                 or channel.get('non_value_type') in {'Button','Label','Separator'}))
                        if channel.get('evaluated_available'): available.add(name)
                    valid_channels = valid_channels and bool(valid)
                valid_channels = valid_channels and available == set(parameters)
            require(valid_channels, 'render saved channel contract malformed')
    supervisor = document.get('supervisor_binding')
    supervisor = supervisor if isinstance(supervisor, Mapping) else {}
    supervisor_identity = supervisor.get('identity') or {}
    require(isinstance(supervisor.get('directory'), str) and Path(supervisor['directory']).is_absolute()
            and isinstance(supervisor_identity, Mapping)
            and supervisor_identity.get('task_id') == document.get('task_id')
            and supervisor_identity.get('launch_nonce') == identity.get('launch_nonce'),
            'render supervisor identity mismatch')
    config = document.get('render_config')
    config = config if isinstance(config, Mapping) else {}
    require(set(config) == {str(f) for f in frames}, 'render configuration frame binding missing')
    for item in config.values():
        require(isinstance(item, Mapping) and _is_sha256(item.get('usd_sha256'))
                and all(isinstance(item.get(k), str) and item[k].startswith('/')
                        for k in ('loppath', 'rendersettings', 'camera'))
                and all(_valid_string_list(item.get(k)) for k in ('lights', 'products', 'aovs'))
                and len(item.get('products', [])) == 1
                and isinstance(item.get('renderer'), str) and bool(item.get('renderer')), 'render native USD configuration incomplete')
        output_format = item.get('exr_format') if isinstance(item, Mapping) else None
        require(isinstance(output_format, Mapping) and output_format.get('storage') == 'scanline'
                and type(output_format.get('multipart')) is int and output_format.get('multipart') == 0
                and output_format.get('compression') in {'none','zips','zip'},
                'render scanline EXR driver configuration missing')
        require(isinstance(item, Mapping) and item.get('loppath') in by_path,
                'render source LOP is outside saved task contract')
    require(document.get('scene_fingerprint') == _canonical_sha256(
        {'scene': scene.get('snapshot_sha256'), 'config': config}), 'render scene fingerprint mismatch')
    request = { 'task_id': document.get('task_id'), 'frames': frames,
        'budget_seconds': document.get('budget_seconds'), 'scene_sha256': scene.get('snapshot_sha256'),
        'render_target': document.get('render_target'), 'output_pattern': document.get('output_pattern'),
        'dependencies': document.get('dependencies') }
    if 'project_color' in document:
        from dcc_task_runtime.project_color import validate_project_color
        try:
            request['project_color'] = validate_project_color(document['project_color'])
        except ValueError:
            require(False, 'invalid human project color selection')
    require(document.get('request_sha256') == _canonical_sha256(request), 'render request content digest mismatch')
    stop = document.get('stop_basis')
    stop = stop if isinstance(stop, Mapping) else {}
    require(document.get('stop_confirmed') is True, 'render stop is unconfirmed')
    if stop.get('schema') == 'bridge.houdini.lifecycle_fact/1.0':
        supplied, computed = _receipt_digest(stop)
        require(stop.get('kind') == 'STOP_CONFIRMED' and stop.get('stop_confirmed') is True
                and stop.get('task_id') == document.get('task_id') and stop.get('request_id') == document.get('request_id')
                and stop.get('pid') == identity.get('pid') and supplied == computed
                and _is_sha256(supplied) and stop.get('source') == 'houdini/native_render_returned',
                'render native stop fact mismatch')
    else:
        observed = stop.get('operation') or {}
        require(not completed and stop.get('schema') == 'bridge.owned_process/1' and stop.get('event') == 'stopped'
                and stop.get('identity') == supervisor_identity and stop.get('pid') == identity.get('pid')
                and stop.get('observed_by') == 'owned_child_wait' and type(stop.get('exit_code')) is int
                and _is_sha256(stop.get('started_sha256')) and isinstance(observed, Mapping)
                and (not observed or (observed.get('operation_id') == document.get('operation_id')
                                     and observed.get('host_identity') == identity)),
                'render supervisor stop fact mismatch')
    return errors


def _render_file_errors(provider, label, *, resolver=None):
    errors = []
    snapshots = provider.get('frame_snapshots') or {}
    if isinstance(snapshots, Mapping):
        for frame, snapshot in snapshots.items():
            if not isinstance(snapshot, Mapping): continue
            raw = snapshot.get('path')
            actual = None
            try:
                actual = (resolver.resolve(raw, expected_sha256=snapshot.get('sha256'),
                            expected_bytes=snapshot.get('bytes'), producer_modified_ns=snapshot.get('modified_ns'))
                          if resolver is not None else Path(raw) if isinstance(raw, str) else None)
                if (actual is None or actual.is_symlink() or not actual.is_file()
                        or digest(actual) != snapshot.get('sha256')
                        or actual.stat().st_size != snapshot.get('bytes')
                        or resolver is None and actual.stat().st_mtime_ns != snapshot.get('modified_ns')):
                    errors.append(label + ': render frame snapshot content mismatch')
            except (OSError, ValueError, TypeError):
                errors.append(label + ': render frame snapshot content mismatch')
            if provider.get('schema') == 'bridge.houdini.render.execution_fact/1.0' and actual is not None and actual.is_file():
                try:
                    from dcc_task_runtime.exr_codec import read_exr
                    image = read_exr(actual, with_pixels=False)
                    expected = {'width':image['width'],'height':image['height'],
                                'channels':image['channels'],'compression':image['compression']}
                    config = (provider.get('render_config') or {}).get(str(frame), {}).get('exr_format') or {}
                    if (snapshot.get('exr') != expected or image['compression'] !=
                            {'none':0,'zips':2,'zip':3}.get(config.get('compression'))):
                        errors.append(label + ': render EXR payload differs from frozen driver format')
                except (OSError, ValueError, KeyError, TypeError, ImportError):
                    errors.append(label + ': render EXR payload is not verifiable')
    if provider.get('schema') == 'bridge.houdini.render.execution_fact/1.0':
        scene = provider.get('scene') or {}
        scene = scene if isinstance(scene, Mapping) else {}
        raw, checksum = scene.get('snapshot_path'), scene.get('snapshot_sha256')
        stop = provider.get('stop_basis') or {}
        if isinstance(stop, Mapping) and stop.get('schema') == 'bridge.owned_process/1':
            try:
                binding = provider.get('supervisor_binding') or {}
                observed = (resolver.read_supervisor(binding['directory'], binding['identity']) if resolver is not None
                            else _owned_receipt_module().read_receipt(binding['directory'], 'stopped', identity=binding['identity']))
                if observed != stop:
                    errors.append(label + ': render supervisor receipt content mismatch')
            except (OSError, ValueError, KeyError, TypeError, ImportError):
                errors.append(label + ': render supervisor receipt is not verifiable')
    else:
        fact = provider.get('execution_fact') or {}
        fact = fact if isinstance(fact, Mapping) else {}
        if fact.get('kind') != 'owned_subprocess': return errors
        worker = fact.get('worker_receipt') or {}
        worker = worker if isinstance(worker, Mapping) else {}
        raw, checksum = worker.get('snapshot'), worker.get('snapshot_sha256')
        process = fact.get('process_identity') or {}
        try:
            observed = (resolver.read_supervisor(process['supervisor_directory'], process['supervisor_identity']) if resolver is not None
                        else _owned_receipt_module().read_receipt(process['supervisor_directory'], 'stopped', identity=process['supervisor_identity']))
            if (observed is None or observed.get('pid') != process.get('pid')
                    or _owned_receipt_module().execution_returncode(observed) != 0):
                errors.append(label + ': Nuke owned worker stop receipt mismatch')
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(label + ': Nuke owned worker stop receipt is not verifiable')
    try:
        actual = (resolver.resolve(raw, expected_sha256=checksum) if resolver is not None
                  else Path(raw) if isinstance(raw, str) else None)
        if actual is None or actual.is_symlink() or not actual.is_file() or digest(actual) != checksum:
            errors.append(label + ': render saved scene snapshot content mismatch')
    except (OSError, ValueError, TypeError):
        errors.append(label + ': render saved scene snapshot content mismatch')
    return errors


def _prepared_file(root, logical, checksum, resolver):
    if not isinstance(logical, str) or not Path(logical).is_absolute() or not _is_sha256(checksum):
        raise ValueError('absolute content-addressed evidence file required')
    actual = _evidence_file(root, logical, checksum, resolver)
    if (any(path.is_symlink() for path in (actual, *actual.parents))
            or not actual.is_file() or digest(actual) != checksum):
        raise ValueError('evidence file bytes/hash mismatch: ' + logical)
    return actual


def _prepared_source(source, root, resolver):
    if not isinstance(source, Mapping):
        raise ValueError('frozen source binding missing')
    manifest = _prepared_file(root, source.get('manifest_path'), source.get('manifest_sha256'), resolver)
    PackageEvidenceResolver._json(manifest)
    control = Path(source['manifest_path']).parent
    snapshot = control / 'snapshot'
    if source.get('repo_root') != str(snapshot):
        raise ValueError('frozen repo_root does not bind control snapshot')
    index = _prepared_file(root, str(control / 'snapshot-manifest.json'),
                           source.get('snapshot_manifest_sha256'), resolver)
    entries = PackageEvidenceResolver._json(index).get('files')
    if not isinstance(entries, list) or not entries:
        raise ValueError('frozen source manifest is empty')
    hashes = {}
    stale = []
    for entry in entries:
        name = PackageEvidenceResolver._relative(entry.get('path'))
        if name in hashes:
            raise ValueError('duplicate frozen source path')
        checksum = entry.get('sha256')
        _prepared_file(root, str(snapshot / name), checksum, resolver)
        hashes[name] = checksum
        try:
            current = (resolver.source_file(name, expected_sha256=checksum) if resolver is not None
                       else Path(root) / name)
            if not current.is_file() or digest(current) != checksum:
                stale.append(name)
        except (OSError, ValueError):
            stale.append(name)
    if 'plugins/houdini/_impl/houdini_bridge_addon.py' not in hashes:
        raise ValueError('frozen native provider source missing')
    return hashes, stale


def _prepared_stop(host, source, resolver):
    identity = {key: host.get(key) for key in ('task_id', 'launch_nonce')}
    directory = str(Path(source['manifest_path']).parent / 'houdini-task-host'
                    / ('supervisor-' + str(host.get('launch_nonce'))))
    return _prepared_stop_at(host, directory, identity, resolver)


def _prepared_stop_at(host, directory, identity, resolver, *, require_success=True):
    observed = (resolver.read_supervisor(directory, identity) if resolver is not None
                else _owned_receipt_module().read_receipt(directory, 'stopped', identity=identity))
    if (not isinstance(observed, Mapping) or type(observed.get('pid')) is not int
            or observed['pid'] <= 0 or observed.get('pid') != host.get('pid')
            or observed.get('identity') != identity or observed.get('observed_by') != 'owned_child_wait'
            or type(observed.get('exit_code')) is not int
            or require_success and _owned_receipt_module().execution_returncode(observed) != 0
            or observed.get('platform') not in {'windows', 'posix'}):
        raise ValueError('authenticated owner stop/child wait proof missing')
    if (observed.get('platform') == 'windows'
            and (observed.get('child_wait_observed') is not True
                 or type(observed.get('job_active_processes')) is not int
                 or observed.get('job_active_processes') != 0)):
        raise ValueError('authenticated Windows Job stop proof missing')
    return {'directory': directory, 'identity': identity}


def _prepared_native_file(reference, root, resolver):
    if not isinstance(reference, Mapping) or type(reference.get('bytes')) is not int:
        raise ValueError('native evidence byte count missing')
    if not 0 < reference['bytes'] <= 64 * 1024 * 1024:
        raise ValueError('native evidence byte count exceeds bound')
    actual = _prepared_file(root, reference.get('path'), reference.get('sha256'), resolver)
    if actual.stat().st_size != reference['bytes']:
        raise ValueError('native evidence byte count mismatch')
    return PackageEvidenceResolver._json(actual)


def _prepared_native_commands(reference, root, source, *, owner, graph_id, graph_version,
                              graph_hash, operation_id, resolver=None):
    if isinstance(reference, Mapping) and isinstance(reference.get('path'), str):
        locator = Path(reference['path'])
        if not locator.is_absolute():
            generation = reference.get('attempt_generation')
            expected = ('graph-jobs', operation_id, f'attempt-{generation}',
                        str(operation_id) + '.native-operations.json')
            if type(generation) is not int or generation < 1 or locator.parts != expected:
                raise ValueError('native public locator does not bind operation/attempt')
            reference = dict(reference, path=str(Path(source['manifest_path']).parent / 'jobs' / locator))
    packet = _prepared_native_file(reference, root, resolver)
    schema = 'bridge.houdini.native-command-evidence/2.0'
    if (not isinstance(packet, Mapping) or packet.get('schema') != schema
            or reference.get('schema') != schema or not _is_sha256(graph_hash)
            or any(packet.get(key) != expected or reference.get(key) != expected
                   for key, expected in (('task_id', owner), ('operation_id', operation_id),
                                         ('graph_hash', graph_hash)))
            or not isinstance(operation_id, str) or not operation_id
            or operation_id.startswith(_SYNTHETIC_OPERATION_PREFIXES)):
        raise ValueError('native packet owner/graph/operation mismatch')
    nonce, generation = packet.get('attempt_token'), packet.get('attempt_generation')
    records = packet.get('receipts')
    if (not isinstance(nonce, str) or not nonce or type(generation) is not int or generation < 1
            or reference.get('attempt_token') != nonce or type(reference.get('attempt_generation')) is not int
            or reference.get('attempt_generation') != generation
            or not isinstance(records, list) or not records or len(records) > 4096
            or type(reference.get('count')) is not int or reference['count'] != len(records)
            or type(graph_version) is not int or graph_version < 0):
        raise ValueError('native packet attempt/count binding missing')
    hashes, stale = _prepared_source(source, root, resolver)
    required_sources = {'packages/houdini-bridge/src/houdini_bridge/operation_receipts.py',
                        'packages/houdini-bridge/src/houdini_bridge/operation_receipt_store.py',
                        'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'}
    if not required_sources.issubset(hashes):
        raise ValueError('native producer/worker frozen source binding missing')
    expected_root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((owner + ':' + graph_hash).encode()).hexdigest()
    validator = _houdini_producer_module()
    proofs, operation_ids = [], set()
    process_identity = None
    for descriptor in records:
        record = _prepared_native_file(descriptor, root, resolver)
        storage = descriptor.get('storage_format')
        if storage == 'legacy_task_store':
            record = (record.get('producer_operations') or {}).get(descriptor.get('operation_id'))
        elif storage != 'producer_record':
            raise ValueError('native producer storage format missing')
        validator.validate_operation_receipt(record)
        for name in ('schema', 'task_id', 'operation_id', 'request_id', 'command', 'kind', 'state',
                     'operation_receipt_sha256', 'request_sha256', 'host_identity'):
            if descriptor.get(name) != record[name]:
                raise ValueError('native descriptor differs from stored producer: ' + name)
        is_query = record['schema'] == validator.QUERY_SCHEMA
        record_root = (record['request']['root_path'] if is_query
                       else record['after_scene']['scene_contract'].get('execution_root'))
        expected_scopes = {'owned_root_children'} if is_query else {'native_command', 'task_scene'}
        if (descriptor.get('handler_result_sha256') != record['facts']['handler_result_sha256']
                or record['task_id'] != owner or record['operation_id'] in operation_ids
                or record['operation_id'].startswith(_SYNTHETIC_OPERATION_PREFIXES)
                or record_root != expected_root
                or record['facts'].get('proof_scope') not in expected_scopes):
            raise ValueError('native producer result/owner/root/unique operation mismatch')
        host = record['host_identity']
        actual_identity = {key: host.get(key) for key in ('task_id', 'pid', 'launch_nonce', 'session_id',
                                                        'process_generation', 'plugin_build')}
        if (host['launch_nonce'] != nonce or host['plugin_build'] != hashes['plugins/houdini/_impl/houdini_bridge_addon.py']
                or process_identity is not None and actual_identity != process_identity):
            raise ValueError('native producer actual process/frozen addon mismatch')
        process_identity = actual_identity
        if record['kind'] == 'save':
            saved = record['facts']['saved_scene']
            _prepared_file(root, saved.get('snapshot_path'), saved.get('snapshot_sha256'), resolver)
        operation_ids.add(record['operation_id'])
        proofs.append({'stage': record['stage'], 'proof_scope': record['facts'].get('proof_scope'),
                       'command': record['command'], 'operation_id': record['operation_id'],
                       'operation_receipt_sha256': record['operation_receipt_sha256'],
                       'task_id': owner, 'graph_id': graph_id, 'graph_version': graph_version,
                       'graph_hash': graph_hash, 'source': dict(source), 'current_source_matches': not stale})
    identity = {'operation_id': operation_id, 'attempt_token': nonce, 'generation': generation}
    directory = str(Path(reference['path']).parent / 'owned-supervisor')
    _prepared_stop_at(process_identity, directory, identity, resolver, require_success=False)
    return proofs, stale


def _prepared_current_save(save, saved, current, source, root, *, owner, graph_id,
                           graph_version, resolver=None):
    validator = _houdini_producer_module()
    record = save.get('operation_receipt')
    validator.validate_operation_receipt(record)
    if (record['command'] != 'scene.save_hip' or record['task_id'] != owner
            or record['operation_id'].startswith(_SYNTHETIC_OPERATION_PREFIXES)
            or save.get('operation_store_format') != 'producer_record'):
        raise ValueError('current SAVE typed producer owner/command/storage mismatch')
    version = current['result']
    if (version.get('task_id') != owner or version.get('state') != 'COMPLETE'
            or type(version.get('version')) is not int or version['version'] != graph_version
            or saved.get('source') != current.get('source') or source != saved.get('source')):
        raise ValueError('current SAVE owned graphversion/frozen source mismatch')
    host = record['host_identity']
    native_saved = record['facts']['saved_scene']
    actual = {key: value for key, value in save.items() if key not in {
        'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent',
        'feedback_dependencies', 'saved_scene_id'}}
    graph_hash = version['compiled']['graph_hash']
    contract = save['scene_contract']
    if (record['request'].get('path') != save['path'] or record['result'] != actual
            or record['after_scene']['scene_contract'] != contract
            or record['request'].get('graph_hash', graph_hash) != graph_hash
            or record['request'].get('root_path', contract.get('execution_root')) != contract.get('execution_root')
            or native_saved.get('path') != save['path']
            or native_saved.get('sha256') != save['sha256']
            or native_saved.get('snapshot_sha256') != save['sha256']):
        raise ValueError('current SAVE request/host/contract/saved HIP mismatch')
    hashes, stale = _prepared_source(source, root, resolver)
    required = {'packages/houdini-bridge/src/houdini_bridge/operation_receipts.py',
                'packages/houdini-bridge/src/houdini_bridge/operation_receipt_store.py',
                'packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py'}
    if not required.issubset(hashes) or host['plugin_build'] != hashes['plugins/houdini/_impl/houdini_bridge_addon.py']:
        raise ValueError('current SAVE native producer/controller frozen source mismatch')
    store_root = Path(source['manifest_path']).parent / 'houdini-instances' / 'fx_operations'
    stored_path = store_root / 'producer-records' / hashlib.sha256(owner.encode()).hexdigest() / (
        hashlib.sha256(record['operation_id'].encode()).hexdigest() + '.json')
    if save.get('operation_store_path') != str(stored_path):
        raise ValueError('current SAVE canonical producer storage path mismatch')
    raw = (json.dumps(record, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    stored = _prepared_file(root, str(stored_path), hashlib.sha256(raw).hexdigest(), resolver)
    if stored.read_bytes() != raw or PackageEvidenceResolver._json(stored) != record:
        raise ValueError('current SAVE canonical producer bytes mismatch')
    _prepared_file(root, native_saved.get('snapshot_path'), save['sha256'], resolver)
    return {'stage': 'save', 'proof_scope': 'current_task_save', 'command': record['command'],
            'operation_id': record['operation_id'], 'request_id': record['request_id'],
            'operation_receipt_sha256': record['operation_receipt_sha256'],
            'producer_path': str(stored_path), 'producer_sha256': hashlib.sha256(raw).hexdigest(),
            'task_id': owner, 'graph_id': graph_id, 'graph_version': graph_version,
            'graph_hash': graph_hash, 'host_identity': dict(host), 'source': dict(source),
            'current_source_matches': not stale, 'domain_lifecycle_verified': False}, stale


def inspect_prepared_case(case, root, *, resolver=None):
    """Adapt existing prepared receipts as partial, byte-verified software facts.

    Controller envelopes supply context, never producer authority. Unsupported
    stages and full domain semantics/recovery remain explicit missing proofs.
    """
    errors = []
    proofs = []
    support = {}
    label = str(case.get('case_id', 'prepared case')) if isinstance(case, Mapping) else 'prepared case'
    missing = [
        'build/inspect: typed native graph construction/readback producer missing',
        'edit/full_semantic: complete domain control/readback producer contract missing',
        'save: typed save producer missing (task_save summary is supporting evidence only)',
        'preview: typed preview/cache producer missing',
        'output: persisted registration/collection producer proof missing',
        'recovery: interruption/resume and lifecycle producer proof missing',
        'nuke: input binding is not a typed composite/render producer',
    ]
    if not isinstance(case, Mapping) or _diagnostic_marked(case):
        errors.append(label + ': diagnostic evidence cannot enter prepared stage adaptation')
        return {'stages': [], 'operation_ids': [], 'proofs': [], 'supporting_evidence': {},
                'errors': errors, 'missing_proofs': missing}
    owner, graph, version = (case.get(key) for key in ('controller_task_id', 'graph_id', 'graph_version'))
    receipts = case.get('stage_receipts')
    if (not isinstance(owner, str) or not owner or not isinstance(graph, str) or not graph
            or type(version) is not int or version < 0 or not isinstance(receipts, list)):
        errors.append(label + ': concrete owner/graphversion/stage receipts missing')
        return {'stages': [], 'operation_ids': [], 'proofs': [], 'supporting_evidence': {},
                'errors': errors, 'missing_proofs': missing}
    dependencies = [f'graph:{owner}:{graph}:output:domain_output', f'graph:{owner}:{graph}:version:{version}']
    versions = [receipt for receipt in receipts if isinstance(receipt, Mapping)
                and receipt.get('operation') == 'graph_version' and not receipt.get('error')
                and receipt.get('task_id') == owner and receipt.get('graph_id') == graph
                and isinstance(receipt.get('result'), Mapping)]
    current = versions[-1]['result'] if versions else {}
    compiled = current.get('compiled')
    compiled = compiled if isinstance(compiled, Mapping) else {}
    save = case.get('save_receipt')
    context_errors = []
    if type(current.get('version')) is not int or current.get('version') != version or not compiled:
        context_errors.append('current graphversion context missing or stale')
    if not isinstance(save, Mapping):
        save = {}
    contract = save.get('scene_contract') or {}
    if (not isinstance(contract, Mapping) or contract.get('task_id') != owner
            or not _is_sha256(compiled.get('graph_hash'))
            or contract.get('graph_hash') != compiled.get('graph_hash')
            or not _is_sha256(save.get('scene_contract_sha256'))
            or save.get('scene_contract_sha256') != _canonical_sha256(contract)
            or save.get('feedback_dependencies') != dependencies):
        context_errors.append('saved owner/hash/graphversion contract mismatch')
    saved = [receipt for receipt in receipts if isinstance(receipt, Mapping)
             and receipt.get('operation') == 'task_save' and not receipt.get('error')
             and receipt.get('task_id') == owner and receipt.get('graph_id') == graph
             and type(receipt.get('graph_version')) is int
             and receipt.get('graph_version') == version and receipt.get('result') == save]
    if not saved:
        context_errors.append('current task_save receipt does not bind saved scene')
    try:
        _prepared_file(root, save.get('path'), save.get('sha256'), resolver)
    except (OSError, ValueError, TypeError) as error:
        context_errors.append('current saved scene bytes missing: ' + str(error))
    errors.extend(label + ': ' + error for error in context_errors)
    if save.get('operation_receipt') is not None:
        try:
            latest_save = [receipt for receipt in receipts if isinstance(receipt, Mapping)
                           and receipt.get('operation') == 'task_save' and not receipt.get('error')
                           and receipt.get('task_id') == owner and receipt.get('graph_id') == graph][-1]
            if (context_errors or latest_save != saved[-1]
                    or type(latest_save.get('graph_version')) is not int
                    or latest_save.get('graph_version') != version):
                raise ValueError('current SAVE latest task_save context mismatch')
            source = latest_save.get('source')
            if case.get('controller_source', source) != source:
                raise ValueError('current SAVE controller frozen source mismatch')
            save_proof, stale = _prepared_current_save(save, latest_save, versions[-1], source, root,
                owner=owner, graph_id=graph, graph_version=version, resolver=resolver)
            proofs.append(save_proof)
            support['current_task_save'] = {'typed_save_verified': True, 'scope': 'current_task_save',
                'operation_id': save_proof['operation_id'], 'current_source_matches': not stale,
                'domain_lifecycle_verified': False}
            missing = [item for item in missing if not item.startswith('save:')]
            if stale:
                missing.append('save: typed producer verified against frozen source; current-source binding stale')
                errors.extend(label + ': frozen source differs from current build: ' + name for name in stale)
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            errors.append(label + ': prepared save proof rejected: ' + str(error))
    source_cache = {}
    native_packets = {}
    native_operation_ids = set()
    render = None
    for receipt in receipts:
        if not isinstance(receipt, Mapping) or receipt.get('error'):
            continue
        result = receipt.get('result')
        if not isinstance(result, Mapping):
            continue
        construction = (result.get('result') if receipt.get('operation') in {'graph_status', 'graph_trial'}
                        and isinstance(result.get('result'), Mapping) else result)
        if isinstance(construction, Mapping) and 'native_operation_evidence' in construction:
            reference = construction['native_operation_evidence']
            try:
                if (receipt.get('task_id') != owner or receipt.get('graph_id') != graph
                        or receipt.get('source') != saved[-1].get('source') or context_errors):
                    raise ValueError('native construction/save owner/source context mismatch')
                if not isinstance(reference, Mapping):
                    raise ValueError('native construction reference missing')
                packet_key = _canonical_sha256({key: reference.get(key) for key in
                    ('schema', 'task_id', 'operation_id', 'graph_hash', 'attempt_token', 'attempt_generation', 'sha256')})
                reference_binding = _canonical_sha256({key: reference.get(key) for key in
                    ('schema', 'path', 'bytes', 'sha256', 'task_id', 'operation_id', 'graph_hash',
                     'attempt_token', 'attempt_generation', 'count')})
                if packet_key in native_packets and native_packets[packet_key] != reference_binding:
                    raise ValueError('duplicate native packet has conflicting reference bindings')
                if packet_key not in native_packets:
                    graph_hash = reference.get('graph_hash')
                    graph_versions = [item['result']['version'] for item in versions
                                      if isinstance(item['result'].get('compiled'), Mapping)
                                      and item['result']['compiled'].get('graph_hash') == graph_hash
                                      and type(item['result'].get('version')) is int
                                      and item['result']['version'] >= 0
                                      and item['result'].get('state') == 'COMPLETE'
                                      and item.get('source') == receipt['source']]
                    if not graph_versions:
                        raise ValueError('native construction graph hash not bound to an owned graphversion')
                    native_proofs, stale = _prepared_native_commands(reference, root, receipt['source'],
                        owner=owner, graph_id=graph, graph_version=graph_versions[0], graph_hash=graph_hash,
                        operation_id=construction.get('operation_id'), resolver=resolver)
                    producer_ids = {proof['operation_id'] for proof in native_proofs}
                    if producer_ids & native_operation_ids:
                        raise ValueError('native producer operations overlap an already admitted packet')
                    proofs.extend(native_proofs)
                    native_operation_ids.update(producer_ids)
                    native_packets[packet_key] = reference_binding
                    errors.extend(label + ': frozen source differs from current build: ' + name for name in stale
                                  if label + ': frozen source differs from current build: ' + name not in errors)
                    support['native_command_scope'] = 'primitive stages only; full domain semantics remain unproven'
            except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
                errors.append(label + ': native construction proof rejected: ' + str(error))
        provider = result.get('scene_transition') or result.get('execution_fact')
        if not isinstance(provider, Mapping):
            continue
        schema = provider.get('schema')
        stage = ('reopen' if schema == 'bridge.houdini.scene-transition-operation/1.0'
                 and isinstance(provider.get('command'), str)
                 and provider.get('command') in {'scene.reopen_task_hip', 'scene.reopen_owned_hip'}
                 else 'render' if schema == 'bridge.houdini.render.execution_fact/1.0' else None)
        if stage is None:
            errors.append(label + ': unsupported prepared typed producer schema/command')
            continue
        if type(receipt.get('graph_version')) is not int or receipt.get('graph_version') != version:
            continue
        try:
            if context_errors:
                raise ValueError('current saved graph context is not verifiable')
            if receipt.get('task_id') != owner or receipt.get('graph_id') != graph or provider.get('task_id') != owner:
                raise ValueError('producer owner/graph mismatch')
            supplied, recomputed = _receipt_digest(provider)
            if not _is_sha256(supplied) or supplied != recomputed:
                raise ValueError('typed producer digest mismatch')
            source_errors = _formal_receipt_source_errors(provider, label)
            if source_errors:
                raise ValueError('; '.join(source_errors))
            if provider.get('state') != 'COMPLETED':
                raise ValueError('producer did not complete')
            source = receipt.get('source')
            if source != saved[-1].get('source') or source != versions[-1].get('source'):
                raise ValueError('producer/save/graphversion frozen source mismatch')
            source_key = _canonical_sha256(source)
            if source_key not in source_cache:
                source_cache[source_key] = _prepared_source(source, root, resolver)
            hashes, stale = source_cache[source_key]
            errors.extend(label + ': frozen source differs from current build: ' + name for name in stale
                          if label + ': frozen source differs from current build: ' + name not in errors)
            host = provider.get('after_identity') if stage == 'reopen' else provider.get('host_identity')
            if (not isinstance(host, Mapping) or host.get('task_id') != owner
                    or type(host.get('pid')) is not int or host['pid'] <= 0
                    or host.get('plugin_build') != hashes['plugins/houdini/_impl/houdini_bridge_addon.py']):
                raise ValueError('native provider owner/frozen plugin hash mismatch')
            if stage == 'reopen':
                before = provider.get('before_identity')
                if (not isinstance(before, Mapping) or any(before.get(key) != host.get(key) for key in
                        ('task_id', 'pid', 'session_id', 'launch_nonce', 'process_generation', 'plugin_build'))):
                    raise ValueError('reopen before/after owner/frozen host identity mismatch')
            supervisor = _prepared_stop(host, source, resolver)
            scene = provider.get('result') if stage == 'reopen' else provider.get('scene')
            if scene.get('path') != save.get('path') or scene.get('sha256') != save.get('sha256'):
                raise ValueError('producer current scene does not bind saved HIP')
            _prepared_file(root, scene.get('snapshot_path'), scene.get('snapshot_sha256'), resolver)
            if stage == 'render':
                if not scene.get('snapshot_sha256') == scene.get('sha256') == save.get('sha256'):
                    raise ValueError('render snapshot hash does not bind current saved HIP')
                if (provider != case.get('execution_fact') or provider.get('dependencies') != dependencies
                        or provider.get('supervisor_binding') != supervisor
                        or scene.get('identity') != host or scene.get('scene_contract') != contract
                        or scene.get('scene_contract_sha256') != save.get('scene_contract_sha256')):
                    raise ValueError('render current scene/graphversion/source binding mismatch')
                file_errors = _render_file_errors(provider, label, resolver=resolver)
                if file_errors:
                    raise ValueError('; '.join(file_errors))
            operation_id = provider.get('operation_id')
            if not isinstance(operation_id, str) or operation_id.startswith(_SYNTHETIC_OPERATION_PREFIXES):
                raise ValueError('concrete producer operation_id required')
            if stage == 'render':
                render = provider
            proofs.append({'stage': stage, 'operation_id': operation_id, 'operation_receipt_sha256': supplied,
                           'task_id': owner, 'graph_id': graph, 'graph_version': version,
                           'source': dict(source), 'current_source_matches': not stale})
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as error:
            errors.append(label + ': prepared ' + stage + ' proof rejected: ' + str(error))
    if render is not None:
        artifact = case.get('artifact')
        registrations = [receipt.get('result') for receipt in receipts if isinstance(receipt, Mapping)
                         and receipt.get('operation') == 'register_render_artifact' and not receipt.get('error')
                         and receipt.get('task_id') == owner and receipt.get('graph_id') == graph
                         and receipt.get('graph_version') == version]
        matching = isinstance(artifact, Mapping) and artifact in registrations
        matching = matching and all(artifact.get(key) == render.get(key) for key in
                                   ('task_id', 'operation_id', 'operation_receipt_sha256',
                                    'frame_set', 'dependencies', 'scene_fingerprint'))
        matching = matching and artifact.get('pattern') == render.get('output_pattern')
        payload = artifact.get('payload') if isinstance(artifact, Mapping) else None
        snapshots = payload.get('completion_snapshot') if isinstance(payload, Mapping) else None
        matching = matching and isinstance(snapshots, Mapping) and set(snapshots) == set(render['frame_snapshots'])
        matching = matching and payload.get('completion_dependencies') == render['dependencies']
        if matching:
            matching = all(isinstance(snapshots[frame], Mapping) and all(
                snapshots[frame].get(key) == snapshot.get(key) for key in ('path', 'sha256', 'bytes', 'modified_ns'))
                for frame, snapshot in render['frame_snapshots'].items())
        if matching:
            support['artifact_producer_linkage'] = {'artifact_id': artifact.get('artifact_id'),
                                                    'operation_id': render['operation_id']}
        else:
            errors.append(label + ': registered artifact owner/producer/completion bytes linkage mismatch')
    return {'stages': sorted({proof['stage'] for proof in proofs}),
            'operation_ids': sorted({proof['operation_id'] for proof in proofs}), 'proofs': proofs,
            'supporting_evidence': support, 'errors': errors, 'missing_proofs': missing}


def _static_argv_executes_script(argv, root, script_path, *, resolver=None, script_sha256=None):
    if (not isinstance(argv, list) or len(argv) < 2
            or any(not isinstance(arg, str) for arg in argv)
            or not argv[0]
            or Path(argv[0]).resolve() != Path(sys.executable).resolve()):
        return False
    # These options do not replace the script entry point with code or a module.
    supported_options = {'-I', '-u', '-B', '-E', '-s', '-S', '-O', '-OO', '-q'}
    script_index = 1
    while script_index < len(argv) and argv[script_index] in supported_options:
        script_index += 1
    if script_index < len(argv) and argv[script_index] == '--':
        script_index += 1
    if (script_index >= len(argv) or not argv[script_index]
            or argv[script_index].startswith('-')):
        return False
    if resolver is not None:
        try:
            wanted = resolver.source_file(script_path, expected_sha256=script_sha256)
            given = (resolver.resolve(argv[script_index], expected_sha256=script_sha256)
                     if Path(argv[script_index]).is_absolute()
                     else resolver.source_file(argv[script_index], expected_sha256=script_sha256))
            return given == wanted
        except (OSError, ValueError, TypeError):
            return False
    return ((Path(root) / argv[script_index]).resolve()
            == (Path(root) / script_path).resolve())


def _event_digest(document, field):
    supplied = document.get(field)
    body = {key: value for key, value in document.items() if key != field}
    return supplied, _canonical_sha256(body)


def _resolve_json_pointer(document, pointer):
    if pointer in (None, ''):
        return document
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('receipt pointer must be an RFC 6901 JSON pointer')
    current = document
    for raw in pointer[1:].split('/'):
        if re.search(r'~(?![01])', raw):
            raise ValueError('receipt pointer has an invalid escape')
        part = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(current, Mapping):
            if part not in current:
                raise ValueError('receipt pointer target is missing')
            current = current[part]
        elif isinstance(current, list) and part.isdecimal():
            index = int(part)
            if index >= len(current):
                raise ValueError('receipt pointer index is out of range')
            current = current[index]
        else:
            raise ValueError('receipt pointer traverses a non-container')
    return current


def _read_receipt(root, value, label, prefixes, *, check_files, pointer=None, resolver=None):
    path, errors = _file_binding(root, value, label, prefixes, check_files=check_files, resolver=resolver)
    document = None
    if path is not None and root is not None:
        try:
            actual = _evidence_file(root, value['path'], value.get('sha256'), resolver)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(label + ': JSON receipt is not verifiable: ' + str(exc))
            return None, path, errors
        if actual.is_file() and not actual.is_symlink():
            try:
                document = json.loads(actual.read_text(encoding='utf-8'))
                if pointer is not None:
                    document = _resolve_json_pointer(document, pointer)
                if not isinstance(document, dict):
                    errors.append(label + ': JSON receipt must be an object')
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(label + ': JSON receipt is unreadable: ' + str(exc))
        elif check_files:
            document = None
    return document, path, errors


def _identity_errors(document, expected, label, keys):
    errors = []
    if not isinstance(document, Mapping):
        return [label + ': receipt document is missing']
    for key in keys:
        actual = document.get(key)
        wanted = expected.get(key)
        if not isinstance(actual, str) or not actual:
            errors.append(label + ': receipt missing ' + key)
        elif wanted is not None and actual != wanted:
            errors.append(label + ': receipt ' + key + ' does not match bound evidence')
    return errors


def inspect_row_execution_artifacts(row, root=None, expected_build=None, *, check_files=True, resolver=None):
    """Inspect the actual files behind one contract row.

    This is intentionally stricter than checking that fields are truthy.  It
    makes the row status depend on executable product files and persisted
    operation/event receipts, so a global unittest result or a hand-written
    operation ID cannot promote a row.
    """
    errors = []
    operation_ids = set()
    case_ids = set()
    stages = set()
    receipt_paths = set()
    observed_evidence = []
    expected_build = expected_build or row.get('build_id')

    entry = row.get('production_entry')
    entry_path, entry_errors = _file_binding(
        root, entry, row.get('id', '<row>') + ': production_entry',
        _PRODUCT_PREFIXES, check_files=check_files, resolver=resolver)
    errors.extend(entry_errors)
    if isinstance(entry, Mapping) and (not isinstance(entry.get('symbol'), str) or not entry.get('symbol').strip()):
        errors.append(row.get('id', '<row>') + ': production_entry requires a concrete symbol')
    if entry_path is not None and entry_path.as_posix().startswith('tools/'):
        errors.append(row.get('id', '<row>') + ': evidence tooling cannot be production_entry')
    if isinstance(entry, Mapping) and isinstance(entry.get('symbol'), str) and root is not None and check_files:
        try:
            entry_file = (_evidence_file(root, entry['path'], entry.get('sha256'), resolver)
                          if entry_path is not None else None)
        except (OSError, ValueError, TypeError):
            entry_file = None
        if entry_file is not None and entry_file.is_file() and not entry_file.is_symlink():
            symbol_leaf = entry['symbol'].rsplit('.', 1)[-1].strip()
            try:
                source = entry_file.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                source = ''
            if not symbol_leaf or symbol_leaf not in source:
                errors.append(row.get('id', '<row>') + ': production_entry symbol is not present in the hashed file')

    for field, prefixes in (('implementation', _PRODUCT_PREFIXES), ('release_files', _RELEASE_PREFIXES)):
        values = row.get(field)
        if not isinstance(values, list) or not values:
            errors.append(row.get('id', '<row>') + ': ' + field + ' must contain file bindings')
            continue
        for index, value in enumerate(values):
            _path, file_errors = _file_binding(
                root, value, f"{row.get('id', '<row>')}: {field}[{index}]",
                prefixes, check_files=check_files, resolver=resolver)
            errors.extend(file_errors)

    card = row.get('live_card')
    label = row.get('id', '<row>') + ': live_card'
    if not isinstance(card, Mapping):
        errors.append(label + ' must be a content-addressed pending-execution card binding')
    else:
        card_document, card_path, card_errors = _read_receipt(
            root, card, label, _RECEIPT_PREFIXES, check_files=check_files,
            pointer=card.get('pointer'), resolver=resolver)
        errors.extend(card_errors)
        if card_path is not None:
            receipt_paths.add(card_path.as_posix())
        if isinstance(card_document, Mapping):
            if card_document.get('schema') != 'bridge.readiness.live_card/1':
                errors.append(label + ': unsupported live-card schema')
            if card.get('schema') != card_document.get('schema'):
                errors.append(label + ': schema binding does not match the live-card document')
            errors.extend(_identity_errors(card_document, {'build_id': expected_build}, label, ('build_id',)))
            if card_document.get('state') != 'PENDING_EXECUTION':
                errors.append(label + ': card must remain PENDING_EXECUTION, never PASS/COMPLETED')
            expected_card_values = {
                'content_version': row.get('content_version'),
                'case_id': None,
                'resource_id': row.get('resource_id'),
            }
            execution_binding = row.get('execution_binding')
            case_ids_declared = (execution_binding.get('case_ids')
                                 if isinstance(execution_binding, Mapping) else None)
            card_case = card_document.get('case_id')
            expected_card_values['case_id'] = card_case
            if not isinstance(card_case, str) or not card_case:
                errors.append(label + ': case_id is missing')
            elif isinstance(case_ids_declared, list) and card_case not in case_ids_declared:
                errors.append(label + ': case_id is not declared by the row')
            for field in ('content_version', 'resource_id'):
                value = expected_card_values[field]
                if not isinstance(value, str) or not value:
                    errors.append(label + ': row is missing ' + field)
                elif card_document.get(field) != value:
                    errors.append(label + ': ' + field + ' does not match the row')
            confirmations = card_document.get('confirmations')
            if not isinstance(confirmations, Mapping):
                errors.append(label + ': content/version/case/resource confirmation steps are missing')
            else:
                for field, expected_value in expected_card_values.items():
                    confirmation = confirmations.get(field)
                    if (not isinstance(confirmation, Mapping)
                            or confirmation.get('value') != expected_value
                            or not isinstance(confirmation.get('step'), str)
                            or not confirmation.get('step').strip()):
                        errors.append(label + ': ' + field + ' confirmation is missing or mismatched')
                    elif confirmation.get('confirmed') is True and (
                            not confirmation.get('confirmed_by') or not confirmation.get('confirmed_at')):
                        errors.append(label + ': confirmed ' + field + ' requires operator/time')
            if _contains_key(card_document, {
                    'operation_id', 'operation_receipt_sha256', 'receipt_sha256', 'fact_digest'}):
                errors.append(label + ': live cards are not operation receipts')

    bindings = row.get('evidence_bindings')
    if isinstance(bindings, list):
        for index, binding in enumerate(bindings):
            if not isinstance(binding, Mapping):
                continue
            evidence_type = binding.get('evidence_type')
            label = f"{row.get('id', '<row>')}: evidence_bindings[{index}]"
            if evidence_type not in _EVIDENCE_TYPES:
                errors.append(label + ': unsupported or missing evidence_type')
                continue
            document, path, receipt_errors = _read_receipt(
                root, binding.get('receipt'), label + '.receipt',
                _RECEIPT_PREFIXES, check_files=check_files,
                pointer=binding.get('receipt_pointer'), resolver=resolver)
            errors.extend(receipt_errors)
            if path is not None:
                receipt_paths.add(path.as_posix())
            if not isinstance(document, Mapping):
                continue
            if document.get('build_id') != expected_build:
                errors.append(label + ': receipt build_id does not match executed evidence')
            case_id = document.get('case_id')
            stage = document.get('stage')
            if not isinstance(case_id, str) or not case_id:
                errors.append(label + ': receipt missing case_id')
            else:
                case_ids.add(case_id)
            if not isinstance(stage, str) or not stage:
                errors.append(label + ': receipt missing stage')
            else:
                stages.add(stage)

            evidence_fact = {
                'test_id': binding.get('test_id'),
                'kind': binding.get('kind'),
                'evidence_type': evidence_type,
                'case_id': case_id,
                'stage': stage,
                'operation_id': None,
                'assertion_refs': binding.get('assertion_refs'),
            }

            if evidence_type == 'formal_operation':
                schema = document.get('schema')
                if not isinstance(schema, str) or schema not in _FORMAL_RECEIPT_SCHEMAS:
                    errors.append(label + ': unsupported formal-operation receipt schema')
                errors.extend(_formal_receipt_source_errors(document, label))
                producer_stage = _producer_stage(document)
                if producer_stage is None or stage != producer_stage:
                    errors.append(label + ': stage does not match the actual producer command/kind')
                provider = _provider_fact(document)
                evidence_fact['provider_schema'] = provider.get('schema')
                evidence_fact['provider_sha256'] = _canonical_sha256(provider)
                evidence_fact['operation_receipt_sha256'] = provider.get('operation_receipt_sha256')
                for field in ('case_id', 'build_id'):
                    if field in provider and document.get(field) != provider.get(field):
                        errors.append(label + ': wrapper ' + field + ' does not match producer context')
                if check_files and provider.get('schema') == 'bridge.houdini.scene-transition-operation/1.0':
                    result = provider.get('result') or {}
                    for field, checksum in (('path', 'sha256'), ('snapshot_path', 'snapshot_sha256')):
                        value = result.get(field) if isinstance(result, Mapping) else None
                        try:
                            actual = (resolver.resolve(value, expected_sha256=result.get(checksum))
                                      if resolver is not None else Path(value) if isinstance(value, str) else None)
                            if (actual is None or actual.is_symlink() or not actual.is_file()
                                    or digest(actual) != result.get(checksum)):
                                errors.append(label + ': scene-transition HIP snapshot content mismatch')
                        except (OSError, ValueError, TypeError):
                            errors.append(label + ': scene-transition HIP snapshot content mismatch')
                if check_files and provider.get('schema') in {
                        'bridge.nuke.render-operation/1.0', 'bridge.houdini.render.execution_fact/1.0'}:
                    errors.extend(_render_file_errors(provider, label, resolver=resolver))
                operation_id = document.get('operation_id')
                if not isinstance(operation_id, str) or not operation_id:
                    errors.append(label + ': formal operation receipt missing operation_id')
                elif operation_id.lower().startswith(_SYNTHETIC_OPERATION_PREFIXES):
                    errors.append(label + ': operation_id is synthetic-looking')
                else:
                    operation_ids.add(operation_id)
                kind = binding.get('kind')
                state = document.get('state') or document.get('status') or document.get('outcome')
                allowed_states = _TERMINAL_STATES if kind == 'positive' else _NEGATIVE_OPERATION_STATES
                if state not in allowed_states:
                    errors.append(label + ': operation terminal state does not match positive/negative evidence')
                receipt_digest = (document.get('operation_receipt_sha256')
                                  or document.get('receipt_sha256')
                                  or document.get('fact_digest'))
                if not _is_sha256(receipt_digest):
                    errors.append(label + ': operation fact lacks a verifiable digest')
                recomputed, observed_digest = _receipt_digest(document)
                if (not _is_sha256(recomputed) or not _is_sha256(observed_digest)
                        or recomputed.lower() != observed_digest.lower()
                        or receipt_digest != recomputed):
                    errors.append(label + ': operation receipt digest does not match canonical receipt content')
                if not any(isinstance(document.get(key), (dict, list))
                           for key in ('result', 'record', 'operation', 'execution', 'event', 'evidence', 'lifecycle_fact', 'provider_fact')):
                    errors.append(label + ': operation fact payload is missing')
                evidence_fact['operation_id'] = operation_id
            elif evidence_type == 'preflight_rejection':
                if binding.get('kind') != 'negative':
                    errors.append(label + ': preflight rejection can only prove negative behavior')
                if document.get('schema') not in {
                        'bridge.live_preflight/1', 'bridge.readiness.preflight_event/1'}:
                    errors.append(label + ': unsupported preflight rejection schema')
                if document.get('passed') is not False or not isinstance(document.get('errors'), list) or not document.get('errors'):
                    errors.append(label + ': rejection event must record an actual failed preflight reason')
                proof = document.get('no_operation_proof')
                if (not isinstance(proof, Mapping)
                        or proof.get('operation_created') is not False
                        or proof.get('launch_attempted') is not False
                        or proof.get('host_started') is not False
                        or not isinstance(document.get('request_id'), str)
                        or not document.get('request_id')
                        or proof.get('request_id') != document.get('request_id')):
                    errors.append(label + ': explicit no-operation proof is missing')
                before = proof.get('snapshot_before') if isinstance(proof, Mapping) else None
                after = proof.get('snapshot_after') if isinstance(proof, Mapping) else None
                snapshots_valid = True
                for snapshot in (before, after):
                    if (not isinstance(snapshot, Mapping)
                            or snapshot.get('request_id') != document.get('request_id')
                            or snapshot.get('source') != 'controller.operation_registry'
                            or not _valid_string_list(snapshot.get('operation_ids'), allow_empty=True)
                            or not _valid_string_list(snapshot.get('request_operation_ids'), allow_empty=True)):
                        snapshots_valid = False
                        continue
                    supplied_snapshot, computed_snapshot = _event_digest(snapshot, 'snapshot_sha256')
                    if (not _is_sha256(supplied_snapshot) or not _is_sha256(computed_snapshot)
                            or supplied_snapshot.lower() != computed_snapshot.lower()
                            or not set(snapshot.get('request_operation_ids', [])).issubset(
                                set(snapshot.get('operation_ids', [])))):
                        snapshots_valid = False
                if (not snapshots_valid or not isinstance(before, Mapping) or not isinstance(after, Mapping)
                        or set(before.get('operation_ids', [])) != set(after.get('operation_ids', []))
                        or set(before.get('request_operation_ids', [])) != set(after.get('request_operation_ids', []))):
                    errors.append(label + ': request-bound operation snapshots do not prove unchanged state')
                if any(key in document for key in ('operation_id', 'operation_receipt_sha256', 'receipt_sha256', 'fact_digest')):
                    errors.append(label + ': preflight rejection must not claim an operation receipt')
                if not isinstance(document.get('event_id'), str) or not document.get('event_id'):
                    errors.append(label + ': rejection event_id is missing')
                supplied_event, computed_event = _event_digest(document, 'event_id')
                if (not _is_sha256(supplied_event) or not _is_sha256(computed_event)
                        or supplied_event.lower() != computed_event.lower()):
                    errors.append(label + ': rejection event_id does not bind event content')
            else:
                if document.get('schema') != 'bridge.readiness.static_check/1':
                    errors.append(label + ': unsupported static-check receipt schema')
                if document.get('status') != 'PASS':
                    errors.append(label + ': static-check script result is not PASS')
                supplied_receipt, computed_receipt = _event_digest(document, 'receipt_sha256')
                if (not _is_sha256(supplied_receipt) or not _is_sha256(computed_receipt)
                        or supplied_receipt.lower() != computed_receipt.lower()):
                    errors.append(label + ': static-check receipt digest does not bind its content')
                if document.get('case_id') != case_id or document.get('stage') != stage:
                    errors.append(label + ': static-check case/stage does not match its receipt identity')
                script_path, script_errors = _file_binding(
                    root, document.get('script'), label + '.script',
                    _STATIC_EVIDENCE_PREFIXES, check_files=check_files, resolver=resolver)
                errors.extend(script_errors)
                inputs = document.get('inputs')
                if not isinstance(inputs, list) or not inputs:
                    errors.append(label + ': static-check inputs must be content-addressed')
                else:
                    for input_index, input_binding in enumerate(inputs):
                        _path, input_errors = _file_binding(
                            root, input_binding, f'{label}.inputs[{input_index}]',
                            _STATIC_EVIDENCE_PREFIXES, check_files=check_files, resolver=resolver)
                        errors.extend(input_errors)
                invocation = document.get('execution')
                evidence_fact['static_invocation'] = {
                    key: invocation.get(key) for key in ('argv', 'returncode', 'stdout', 'stderr')
                } if isinstance(invocation, Mapping) else None
                if (not isinstance(invocation, Mapping)
                        or not isinstance(invocation.get('argv'), list)
                        or not invocation.get('argv')
                        or any(not isinstance(arg, str) for arg in invocation.get('argv', []))
                        or invocation.get('returncode') != 0
                        or not _is_sha256(invocation.get('stdout_sha256'))
                        or not _is_sha256(invocation.get('stderr_sha256'))
                        or not isinstance(document.get('script'), Mapping)
                        or invocation.get('script_sha256') != document.get('script', {}).get('sha256')
                        or not isinstance(invocation.get('started_at'), str)
                        or not invocation.get('started_at')
                        or not isinstance(invocation.get('finished_at'), str)
                        or not invocation.get('finished_at')):
                    errors.append(label + ': actual static-check invocation result is incomplete')
                elif (not isinstance(invocation.get('stdout'), str)
                      or not isinstance(invocation.get('stderr'), str)
                      or hashlib.sha256(invocation['stdout'].encode('utf-8')).hexdigest()
                         != invocation.get('stdout_sha256')
                      or hashlib.sha256(invocation['stderr'].encode('utf-8')).hexdigest()
                         != invocation.get('stderr_sha256')):
                    errors.append(label + ': static-check output content does not match its observed hashes')
                if isinstance(invocation, Mapping) and script_path is not None and root is not None:
                    argv = invocation.get('argv')
                    if not _static_argv_executes_script(argv, root, script_path, resolver=resolver,
                            script_sha256=document.get('script', {}).get('sha256')):
                        errors.append(label + ': static-check argv does not execute the bound script')
                assertions = document.get('assertions')
                if (not isinstance(assertions, list)
                        or any(not isinstance(item, Mapping)
                               or not isinstance(item.get('assertion_ref'), str)
                               or not _ASSERTION_REF.fullmatch(item.get('assertion_ref'))
                               for item in assertions)
                        or len({item.get('assertion_ref') for item in assertions
                                if isinstance(item, Mapping)}) != len(assertions)):
                    errors.append(label + ': static-check assertions are missing or duplicated')
                assertion_results = {
                    item.get('assertion_ref'): item.get('outcome')
                    for item in assertions if isinstance(item, Mapping)
                } if isinstance(assertions, list) else {}
                mapped_assertions = binding.get('assertion_refs')
                if (not isinstance(mapped_assertions, list) or not mapped_assertions
                        or any(not isinstance(ref, str) or not _ASSERTION_REF.fullmatch(ref)
                               or assertion_results.get(ref) != 'PASS' for ref in mapped_assertions)):
                    errors.append(label + ': static-check assertion results do not cover mapped assertions')
                if root is not None:
                    for ref in mapped_assertions or []:
                        source_path = _safe_relative_path(ref.rsplit(':', 1)[0]) if isinstance(ref, str) else None
                        try:
                            assertion_file = (resolver.source_file(source_path) if resolver is not None
                                              else Path(root) / source_path) if source_path else None
                            tree = ast.parse(assertion_file.read_text(encoding='utf-8')) if assertion_file else None
                            lines = {node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)
                                     or isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                                     and node.func.attr.startswith('assert')} if tree else set()
                        except (OSError, SyntaxError, UnicodeError, ValueError):
                            lines = set()
                        if (not isinstance(ref, str) or not ref.rsplit(':', 1)[-1].isdigit()
                                or int(ref.rsplit(':', 1)[-1]) not in lines):
                            errors.append(label + ': static-check assertion is not an actual source assertion')
            observed_evidence.append(evidence_fact)

    errors.extend(domain_stage_errors(row.get('id'), stages))
    return {
        'errors': errors,
        'operation_ids': sorted(operation_ids),
        'case_ids': sorted(case_ids),
        'stages': sorted(stages),
        'receipt_paths': sorted(receipt_paths),
        'evidence': observed_evidence,
    }


def validate_contract_rows(payload, root=None, *, check_results=True, check_artifacts=True, resolver=None):
    """Validate actual row-local evidence without inventing per-row operations.

    A test may support several rows.  Its executed source and assertion lines
    are shared facts; receipt case/stage/operation sets remain row-specific and
    must exactly match the declarations.
    """
    rows = payload.get('rows', [])
    results = payload.get('test_results', {})
    executions = payload.get('test_executions', {})
    expected_build = payload.get('build_id')
    errors = {}
    evidence_refs = {}

    def add(identifier, message):
        errors.setdefault(identifier, []).append(message)

    string_list = _valid_string_list

    if not isinstance(rows, list):
        return {'<contract>': ['rows must be a list']}

    for row in rows:
        if not isinstance(row, dict):
            errors.setdefault('<contract>', []).append('row must be an object')
            continue
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier:
            errors.setdefault('<contract>', []).append('row id must be a non-empty string')
            continue

        for key in ROW_IDENTITY_KEYS:
            value = row.get(key)
            if not isinstance(value, str) or not value:
                add(identifier, 'missing ' + key)
            elif key == 'build_id' and value != expected_build:
                add(identifier, 'row build_id does not match executed evidence')
        evidence_ref = row.get('evidence_ref')
        if isinstance(evidence_ref, str) and evidence_ref:
            if evidence_ref in evidence_refs:
                add(identifier, 'evidence_ref is reused by ' + evidence_refs[evidence_ref])
            else:
                evidence_refs[evidence_ref] = identifier

        evidence_class = row.get('evidence_class')
        expected_class = ROW_EVIDENCE_CLASSES.get(identifier)
        if expected_class is None:
            add(identifier, 'row is not in the frozen 54-row evidence policy')
        elif evidence_class != expected_class:
            add(identifier, 'evidence_class does not match the frozen row policy')
            evidence_class = expected_class

        execution_binding = row.get('execution_binding')
        if not isinstance(execution_binding, dict):
            add(identifier, 'missing execution_binding')
            execution_binding = {}
        if not isinstance(execution_binding.get('kind'), str) or not execution_binding.get('kind'):
            add(identifier, 'execution_binding missing kind')
        if execution_binding.get('evidence_ref') != evidence_ref:
            add(identifier, 'execution_binding evidence_ref does not match row')
        if execution_binding.get('build_id') != expected_build:
            add(identifier, 'execution_binding build_id does not match executed evidence')
        for key in ('case_ids', 'stages', 'test_ids'):
            if not string_list(execution_binding.get(key)):
                add(identifier, 'execution_binding missing or invalid ' + key)
        if not string_list(execution_binding.get('operation_ids'), allow_empty=True):
            add(identifier, 'execution_binding missing or invalid operation_ids')

        names_by_kind = {}
        row_bindings = row.get('evidence_bindings')
        if not isinstance(row_bindings, list) or not row_bindings:
            add(identifier, 'missing evidence_bindings')
            row_bindings = []
        kinds_by_type = {'positive': [], 'negative': []}
        for kind in ('positive', 'negative'):
            field = kind + '_tests'
            names = row.get(field)
            if (not isinstance(names, list) or not names
                    or any(not isinstance(name, str) or not name for name in names)):
                add(identifier, 'missing or invalid ' + field)
                names = []
            if len(names) != len(set(names)):
                add(identifier, field + ' contains duplicate test IDs')
            names_by_kind[kind] = names
            for name in names:
                matches = [binding for binding in row_bindings
                           if isinstance(binding, dict)
                           and binding.get('kind') == kind
                           and binding.get('test_id') == name]
                if len(matches) != 1:
                    add(identifier, f'{kind} test {name} must have exactly one evidence binding')
                    continue
                binding = matches[0]
                evidence_type = binding.get('evidence_type')
                kinds_by_type[kind].append(evidence_type)
                if evidence_type not in _EVIDENCE_TYPES:
                    add(identifier, f'{kind} test {name} binding has an invalid evidence_type')
                if binding.get('evidence_ref') != evidence_ref:
                    add(identifier, f'{kind} test {name} binding evidence_ref does not match row')
                if binding.get('build_id') != expected_build:
                    add(identifier, f'{kind} test {name} binding build_id does not match executed evidence')
                assertion_refs = binding.get('assertion_refs')
                if (not string_list(assertion_refs)
                        or any(not _ASSERTION_REF.fullmatch(ref) for ref in assertion_refs or [])):
                    add(identifier, f'{kind} test {name} binding needs actual assertion source references')
                if binding.get('outcome') != 'PASS':
                    add(identifier, f'{kind} test {name} binding outcome is not PASS')
                if check_results:
                    execution = executions.get(name) if isinstance(executions, Mapping) else None
                    if (not isinstance(results, Mapping) or results.get(name) != 'PASS'
                            or not isinstance(execution, Mapping)
                            or execution.get('outcome') != 'PASS'):
                        add(identifier, f'missing or unsuccessful actual execution for {field} test {name}')
                    else:
                        sources = execution.get('source_files')
                        if not isinstance(sources, list) or not sources:
                            add(identifier, f'{kind} test {name} execution is missing source hashes')
                            source_paths = set()
                        else:
                            source_paths = set()
                            for source_index, source in enumerate(sources):
                                source_path, source_errors = _file_binding(
                                    root, source, f'{identifier}: test {name} source_files[{source_index}]',
                                    ('tests/',), check_files=(root is not None), resolver=resolver)
                                for message in source_errors:
                                    add(identifier, message)
                                if source_path is not None:
                                    source_paths.add(source_path.as_posix())
                        executed_assertions = execution.get('assertion_refs')
                        if not isinstance(executed_assertions, list):
                            executed_assertions = []
                        if (not assertion_refs
                                or any(ref not in executed_assertions
                                       or ref.rsplit(':', 1)[0] not in source_paths
                                       for ref in assertion_refs)):
                            add(identifier, f'{kind} test {name} assertion references were not observed during execution')
                if evidence_type == 'formal_operation' and kind == 'positive':
                    pass

        expected_tests = sorted(set(names_by_kind['positive'] + names_by_kind['negative']))
        if execution_binding.get('test_ids') != expected_tests:
            add(identifier, 'execution_binding test_ids do not match mapped tests')
        expected_binding_count = sum(len(names) for names in names_by_kind.values())
        if len(row_bindings) != expected_binding_count:
            add(identifier, 'evidence_bindings must contain exactly one binding per mapped test')
        if any(not isinstance(binding, dict) for binding in row_bindings):
            add(identifier, 'evidence_bindings contains a non-object')

        if evidence_class in {'static', 'installation'}:
            if (not kinds_by_type['positive'] or not kinds_by_type['negative']
                    or any(value != 'static_check'
                           for values in kinds_by_type.values() for value in values)):
                add(identifier, 'static/installation rows must bind every test to static_check receipts')
        elif evidence_class == 'preflight':
            if (not kinds_by_type['positive'] or not kinds_by_type['negative']
                    or any(value != 'static_check' for value in kinds_by_type['positive'])
                    or any(value != 'preflight_rejection' for value in kinds_by_type['negative'])):
                add(identifier, 'preflight row requires static positive checks and actual preflight rejection events')
        elif evidence_class == 'functional':
            if 'formal_operation' not in kinds_by_type['positive']:
                add(identifier, 'functional row requires a formal positive operation receipt')
            if (not kinds_by_type['negative']
                    or any(value not in {'preflight_rejection', 'formal_operation'}
                           for value in kinds_by_type['negative'])):
                add(identifier, 'functional row requires actual formal or preflight negative events')

        if check_artifacts:
            artifact_result = inspect_row_execution_artifacts(
                row, root, expected_build, check_files=(root is not None), resolver=resolver)
            for message in artifact_result['errors']:
                add(identifier, message)
            if check_results:
                for fact in artifact_result['evidence']:
                    execution = executions.get(fact.get('test_id'), {})
                    if fact.get('evidence_type') == 'formal_operation':
                        required_context = {key: fact.get(key) for key in
                                            ('case_id', 'provider_sha256', 'operation_receipt_sha256')}
                        required_context['build_id'] = expected_build
                        if required_context not in execution.get('provider_facts', []):
                            add(identifier, 'formal receipt case/build/provider were not observed by the actual test runner')
                    elif fact.get('evidence_type') == 'static_check':
                        if fact.get('static_invocation') not in execution.get('static_invocations', []):
                            add(identifier, 'static-check command/output were not observed by the actual test runner')
            declared = {
                'case_ids': execution_binding.get('case_ids'),
                'stages': execution_binding.get('stages'),
                'operation_ids': execution_binding.get('operation_ids'),
            }
            observed = {
                'case_ids': artifact_result['case_ids'],
                'stages': artifact_result['stages'],
                'operation_ids': artifact_result['operation_ids'],
            }
            for key in ('case_ids', 'stages', 'operation_ids'):
                value = declared[key]
                if (not isinstance(value, list) or len(value) != len(set(value))
                        or set(value) != set(observed[key])):
                    add(identifier, 'execution_binding ' + key + ' do not exactly match actual receipts')
            if not artifact_result['case_ids']:
                add(identifier, 'actual receipts have no case IDs')
            if not artifact_result['stages']:
                add(identifier, 'actual receipts have no stages')
            actual_types = [fact.get('evidence_type') for fact in artifact_result['evidence']]
            if evidence_class in {'static', 'installation'} and any(t != 'static_check' for t in actual_types):
                add(identifier, 'static/installation row contains non-static execution evidence')
            if evidence_class == 'preflight':
                positive_types = [fact.get('evidence_type') for fact in artifact_result['evidence']
                                  if fact.get('kind') == 'positive']
                negative_types = [fact.get('evidence_type') for fact in artifact_result['evidence']
                                  if fact.get('kind') == 'negative']
                if any(t != 'static_check' for t in positive_types):
                    add(identifier, 'preflight positive evidence must be an executed static check')
                if any(t != 'preflight_rejection' for t in negative_types):
                    add(identifier, 'preflight negative evidence must be an actual rejection event')
            if evidence_class == 'functional':
                positive_types = [fact.get('evidence_type') for fact in artifact_result['evidence']
                                  if fact.get('kind') == 'positive']
                negative_types = [fact.get('evidence_type') for fact in artifact_result['evidence']
                                  if fact.get('kind') == 'negative']
                if 'formal_operation' not in positive_types:
                    add(identifier, 'functional row has no verified formal positive operation')
                if any(t not in {'preflight_rejection', 'formal_operation'} for t in negative_types):
                    add(identifier, 'functional row has an unsupported negative evidence type')
    return errors


def validate_contract(payload, root, *, resolver=None):
    errors = []
    if payload.get('schema') != 'bridge.readiness.executed_contracts/2':
        errors.append('invalid executed contract evidence schema')
    if payload.get('build_id') != build_id(root, resolver=resolver):
        errors.append('source build does not match executed evidence')
    rows = payload.get('rows', [])
    if not isinstance(rows, list) or len(rows) != len(REQUIRED) or {r.get('id') for r in rows if isinstance(r, dict)} != set(REQUIRED):
        errors.append('contract IDs must exactly cover legacy 17 and all extended requirements')
        return errors
    for identifier, row_errors in validate_contract_rows(payload, root, resolver=resolver).items():
        errors.extend(identifier + ': ' + message for message in row_errors)
    if payload.get('returncode') != 0 or payload.get('test_count', 0) <= 0:
        errors.append('test execution failed or empty')
    test_results = payload.get('test_results')
    test_executions = payload.get('test_executions')
    if not isinstance(test_results, Mapping) or not isinstance(test_executions, Mapping):
        errors.append('actual test execution records are missing')
    else:
        mapped = {name for row in rows for field in ('positive_tests', 'negative_tests')
                  for name in (row.get(field) if isinstance(row.get(field), list) else [])
                  if isinstance(name, str)}
        if set(test_results) != mapped or set(test_executions) != mapped:
            errors.append('executed test IDs do not exactly match mapped positive/negative tests')
        if payload.get('test_count') != len(test_executions):
            errors.append('test_count does not match actual test execution records')
    log = payload.get('log', {})
    try:
        path = _evidence_file(root if resolver is not None else None, log['path'], log.get('sha256'), resolver)
        if digest(path) != log.get('sha256'):
            errors.append('execution log hash mismatch')
    except (OSError, KeyError, TypeError, ValueError):
        errors.append('execution log missing')
    return errors
