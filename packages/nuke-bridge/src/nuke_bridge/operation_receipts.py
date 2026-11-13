"""Formal receipts for durable Nuke renders, separate from artifact lineage."""
from __future__ import annotations
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import os
import tempfile
from typing import Any

SCHEMA = 'bridge.nuke.render-operation/1.0'
COMMAND_STAGES = {
    'render_write': 'render', 'agent.nuke.render': 'render',
    'agent.nuke.render_final': 'render', 'agent.nuke.composite.render_final': 'render',
    'agent.nuke.render_preview': 'preview', 'agent.nuke.composite.render_preview': 'preview',
}
_SHA = re.compile(r'^[0-9a-f]{64}$')


AGENT_RENDER_COMMANDS = frozenset({'agent.nuke.render', 'agent.nuke.render_preview', 'agent.nuke.render_final',
    'agent.nuke.composite.render_preview', 'agent.nuke.composite.render_final'})
INPUT_SCHEMA = 'bridge.nuke.agent-input-binding/1.0'
REGISTERED_INPUT_SCHEMA = 'bridge.nuke.registered-input-contract/1.0'


def freeze_agent_inputs(task_id, inputs):
    """Bind declared controller input hashes to the local bytes consumed by Nuke."""
    if not isinstance(task_id, str) or not task_id or not isinstance(inputs, (list, tuple)) or not inputs or len(inputs) > 10000:
        raise ValueError('INPUT_SOURCE_IDENTITY_REQUIRED: agent render needs frozen inputs')
    manifest, dependencies = [], []
    def verify(uri, declared, size=None):
        if not isinstance(uri, str) or not uri or not isinstance(declared, str) or not _SHA.fullmatch(declared):
            raise ValueError('INPUT_SOURCE_IDENTITY_REQUIRED: local path and SHA-256 required')
        source = Path(uri).expanduser()
        if source.is_symlink() or not source.is_file():
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: local regular input required')
        source = source.resolve()
        digest, count = hashlib.sha256(), 0
        with source.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk); count += len(chunk)
        if not hmac.compare_digest(digest.hexdigest(), declared) or (size is not None and size != count):
            raise RuntimeError('INPUT_SOURCE_HASH_MISMATCH: frozen input bytes changed')
        return {'uri':str(source), 'sha256':declared, 'bytes':count}
    for index, item in enumerate(inputs):
        if not isinstance(item, dict) or not isinstance(item.get('role'), str) or not item['role']:
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: input role required')
        path = item.get('path') or item.get('uri')
        if not isinstance(path,str) or not path:
            raise ValueError('INPUT_SOURCE_IDENTITY_REQUIRED: input path required')
        if Path(path).expanduser().is_symlink():
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: symlink input path')
        path = str(Path(path).expanduser().resolve())
        record = {'index':index, 'role':item['role'], 'path':path}
        raw = item.get('frames')
        if raw is not None:
            if not isinstance(raw, (list, tuple)) or not raw or len(raw) > 10000:
                raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: bounded frame manifest required')
            frames, seen = [], set()
            for ordinal, frame in enumerate(raw):
                if not isinstance(frame, dict) or type(frame.get('frame')) is not int or frame['frame'] in seen:
                    raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: unique integer input frames required')
                seen.add(frame['frame'])
                identity = verify(frame.get('path') or frame.get('uri'), frame.get('sha256'),frame.get('bytes'))
                if frame_path(path, frame['frame']) != identity['uri']:
                    raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: frame path differs from frozen pattern')
                frames.append({'index':ordinal, 'frame':frame['frame'], **identity})
            digest = _canonical_digest(frames)
            if item.get('sha256') and not hmac.compare_digest(str(item['sha256']), digest):
                raise RuntimeError('INPUT_SOURCE_HASH_MISMATCH: sequence manifest changed')
            record.update(frames=frames, manifest_sha256=digest)
        else:
            identity = verify(path,item.get('sha256'),item.get('bytes'))
            record.update(path=identity.pop('uri'), **identity)
        for field in ('artifact_id', 'asset_id'):
            if item.get(field):
                record[field] = str(item[field])
                dependencies.append('artifact:'+str(item[field]))
        manifest.append(record)
    digest = _canonical_digest(manifest)
    return {'schema':INPUT_SCHEMA, 'owner_task_id':task_id, 'frozen_inputs_manifest':manifest,
        'frozen_inputs_sha256':digest, 'dependencies':['input-sha256:'+digest, *dict.fromkeys(dependencies)]}


def agent_input_binding_valid(binding, *, task_id=None, revalidate=False):
    if not isinstance(binding, dict) or set(binding) != {'schema','owner_task_id',
            'frozen_inputs_manifest','frozen_inputs_sha256','dependencies'}:
        return False
    if binding.get('schema') != INPUT_SCHEMA or not isinstance(binding.get('owner_task_id'), str) or not binding['owner_task_id']:
        return False
    if task_id is not None and binding['owner_task_id'] != task_id:
        return False
    manifest = binding.get('frozen_inputs_manifest')
    if not isinstance(manifest, list) or not manifest or len(manifest) > 10000:
        return False
    inputs = []
    for index, record in enumerate(manifest):
        if not isinstance(record,dict) or record.get('index') != index or not isinstance(record.get('role'),str) or not record['role']:
            return False
        item = {'role':record['role'],'path':record.get('path')}
        if 'frames' in record:
            frames = record['frames']
            if not isinstance(frames,list) or not frames or len(frames) > 10000:
                return False
            if record.get('manifest_sha256') != _canonical_digest(frames):
                return False
            item.update(frames=frames,sha256=record['manifest_sha256'])
            if any(not isinstance(frame,dict) or frame.get('index') != ordinal or type(frame.get('frame')) is not int
                    or frame_path(record.get('path'),frame['frame']) != frame.get('uri') for ordinal,frame in enumerate(frames)):
                return False
            if len({frame['frame'] for frame in frames}) != len(frames):
                return False
            identities = frames
        else:
            item.update(sha256=record.get('sha256'),bytes=record.get('bytes'))
            identities = [record]
        for identity in identities:
            uri = identity.get('uri') if 'frames' in record else identity.get('path')
            if (not isinstance(uri,str) or not Path(uri).is_absolute() or type(identity.get('bytes')) is not int
                    or identity['bytes'] <= 0 or not isinstance(identity.get('sha256'),str) or not _SHA.fullmatch(identity['sha256'])):
                return False
        for field in ('artifact_id','asset_id'):
            if field in record: item[field] = record[field]
        inputs.append(item)
    digest = _canonical_digest(manifest)
    if not isinstance(binding.get('frozen_inputs_sha256'),str) or not hmac.compare_digest(binding['frozen_inputs_sha256'],digest):
        return False
    dependencies = ['input-sha256:'+digest]
    dependencies.extend(dict.fromkeys('artifact:'+str(record[field]) for record in manifest for field in ('artifact_id','asset_id') if record.get(field)))
    if binding.get('dependencies') != dependencies:
        return False
    if revalidate:
        try:
            return freeze_agent_inputs(binding['owner_task_id'],inputs) == binding
        except (ValueError, RuntimeError, OSError):
            return False
    return True



COMPOSITE_SCHEMA = 'bridge.nuke.composite-consumption/1'


def native_format_readback(nuke, value):
    """Freeze Format geometry rather than the process-local native object."""
    format_type = getattr(nuke, 'Format', None)
    if not isinstance(format_type, type) or not isinstance(value, format_type):
        return value
    result = {'native_type': 'nuke.Format'}
    for name in ('name', 'width', 'height', 'x', 'y', 'r', 't', 'pixelAspect'):
        actual = getattr(value, name)()
        expected = str if name == 'name' else float if name == 'pixelAspect' else int
        if type(actual) is not expected and not (name == 'name' and actual is None):
            raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: invalid Format field ' + name)
        if ((type(actual) is float and not math.isfinite(actual))
                or (type(actual) is int and actual.bit_length() > 64)
                or (type(actual) is str and len(actual) > 65536)):
            raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: unbounded Format field ' + name)
        result[name] = actual
    return result


def composite_graph_readback(nuke, contract):
    """Read the effect-bearing fields of the existing editable composite."""
    nodes = contract.get('nodes') if isinstance(contract, dict) else None
    if (not isinstance(contract,dict) or contract.get('schema') != COMPOSITE_SCHEMA or not isinstance(nodes, dict)
            or not 1 <= len(nodes) <= 64 or contract.get('write') not in nodes):
        raise ValueError('COMPOSITE_CONTRACT_INVALID: node contract required')
    resolver = getattr(nuke, 'toNode', None) or getattr(nuke, 'node', None)
    actual = {}
    for name, expected in nodes.items():
        if (not isinstance(name, str) or not isinstance(expected, dict)
                or not isinstance(expected.get('knobs'), dict) or len(expected['knobs']) > 64):
            raise ValueError('COMPOSITE_CONTRACT_INVALID: invalid node fields')
        node = resolver(name)
        if node is None:
            raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: missing node ' + name)
        count = node.inputs() if callable(node.inputs) else len(node.inputs)
        knobs = {}
        for key in expected['knobs']:
            knob = node.knob(key)
            if (knob is None or not callable(getattr(knob, 'isAnimated', None))
                    or not callable(getattr(knob, 'hasExpression', None))
                    or knob.isAnimated() or knob.hasExpression()):
                raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: non-static knob ' + name + '.' + key)
            knobs[key] = native_format_readback(nuke, knob.value())
        if (not isinstance(contract.get('task_id'),str) or not contract['task_id']
                or knobs.get('bridge_task_id') != contract['task_id']):
            raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: actual node belongs to another task')
        actual[name] = {'class':node.Class(), 'knobs':knobs,
            'inputs':[node.input(i).name() if node.input(i) is not None else None for i in range(count)]}
    encoded = json.dumps(actual, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > 2*1024*1024:
        raise ValueError('COMPOSITE_CONTRACT_INVALID: readback exceeds budget')
    return json.loads(encoded)


def verify_composite_graph(nuke, contract):
    if _canonical_digest(composite_graph_readback(nuke, contract)) != _canonical_digest(contract['nodes']):
        raise ValueError('COMPOSITE_SNAPSHOT_MISMATCH: graph changed after approval')


def worker_composite_readback_valid(worker, contract, expected_sha):
    proof = worker.get('composite_readback') if isinstance(worker, dict) else None
    return bool(isinstance(proof, dict) and isinstance(contract,dict)
        and isinstance(contract.get('task_id'),str) and bool(contract['task_id'])
        and isinstance(contract.get('nodes'),dict) and bool(contract['nodes'])
        and all(record.get('knobs',{}).get('bridge_task_id') == contract['task_id'] for record in contract['nodes'].values())
        and proof.get('owner_task_id') == contract['task_id'] and expected_sha == _canonical_digest(contract)
        and proof.get('contract_sha256') == expected_sha
        and proof.get('before_verified') is True and proof.get('after_verified') is True)

def registered_input_contract(binding, registry, *, task_id):
    """Freeze current controller-ledger identities, never caller-declared success."""
    if not agent_input_binding_valid(binding, task_id=task_id, revalidate=True):
        raise ValueError('INPUT_SOURCE_HASH_MISMATCH: frozen input bytes/owner changed')
    manifest = binding['frozen_inputs_manifest']
    if len(manifest) > 16:
        raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: input role budget exceeded')
    entries, pending = {}, []
    for item in manifest:
        artifact_id = item.get('artifact_id') or item.get('asset_id')
        if (not isinstance(artifact_id, str) or not artifact_id
                or item.get('artifact_id', artifact_id) != artifact_id
                or item.get('asset_id', artifact_id) != artifact_id
                or not isinstance(item.get('frames'), list) or not 0 < len(item['frames']) <= 12):
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: registered sequence input required')
        pending.append(artifact_id)
    while pending:
        artifact_id = pending.pop()
        if artifact_id in entries:continue
        if len(entries) >= 64:raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: dependency budget exceeded')
        entry = registry._lookup_unchecked(artifact_id)
        if (not isinstance(entry,dict) or entry.get('task_id') != task_id
                or entry.get('artifact_class') == 'raw_input' or not entry.get('operation_id')
                or not registry.verify(artifact_id).get('usable')):
            raise ValueError('INPUT_SOURCE_HASH_MISMATCH: registered input is missing, changed or foreign')
        entries[artifact_id] = entry
        for dependency in entry.get('dependencies') or []:
            if dependency.startswith('artifact:'):
                pending.append(dependency.removeprefix('artifact:'))
    for item in manifest:
        artifact_id = item.get('artifact_id') or item['asset_id']
        entry = entries[artifact_id]
        snapshots = (entry.get('payload') or {}).get('completion_snapshot') or {}
        if item['path'] != entry.get('pattern'):
            raise ValueError('INPUT_SOURCE_HASH_MISMATCH: registered Read pattern changed')
        for frame in item['frames']:
            saved = snapshots.get(str(frame['frame'])) or {}
            if (frame['frame'] not in entry.get('frame_set', [])
                    or any(frame.get(key) != saved.get(key) for key in ('sha256','bytes'))
                    or frame.get('uri') != saved.get('path')):
                raise ValueError('INPUT_SOURCE_HASH_MISMATCH: input differs from registered completion')
    return {'schema':REGISTERED_INPUT_SCHEMA, 'owner_task_id':task_id,
        'registry_root':str(registry.root), 'input_binding':json.loads(json.dumps(binding)),
        'registry_inputs':{key:{'version':entry['version'], 'operation_id':entry['operation_id'],
            'operation_receipt_sha256':entry.get('operation_receipt_sha256'),
            'dependencies':entry['dependencies'], 'payload_sha256':_canonical_digest(entry)}
            for key,entry in sorted(entries.items())}}


def validate_registered_input_contract(contract):
    """纯验证重建完整可信登记上下文，只观察既有生产绑定，不接收外部认证对象。"""
    if (not isinstance(contract,dict) or contract.get('schema') != REGISTERED_INPUT_SCHEMA
            or set(contract) != {'schema','owner_task_id','registry_root','input_binding','registry_inputs'}):
        raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: registered contract required')
    root = Path(str(contract['registry_root']))
    if not root.is_absolute() or root.is_symlink() or not (root/'artifacts.sqlite3').is_file():
        raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: controller ledger unavailable')
    from nuke_bridge.task_host import controlled_artifact_registry
    registry = controlled_artifact_registry(registry_root=root, task_id=contract['owner_task_id'], _read_only_binding=True)
    return _validate_registered_input_contract_with_registry(contract, registry)


def _validate_registered_input_contract_with_registry(contract, registry):
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    if (not isinstance(contract,dict) or contract.get('schema') != REGISTERED_INPUT_SCHEMA
            or set(contract) != {'schema','owner_task_id','registry_root','input_binding','registry_inputs'}):
        raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: registered contract required')
    root = Path(str(contract['registry_root']))
    if not root.is_absolute() or root.is_symlink() or not (root/'artifacts.sqlite3').is_file():
        raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: controller ledger unavailable')
    if registry is None and os.environ.get('BRIDGE_NUKE_HOST_CONFIG'):
        legacy = ArtifactRegistry(root)
        if any((legacy._lookup_unchecked(artifact_id) or {}).get('output_verification') is not None
               for artifact_id in contract['registry_inputs']):
            raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: controlled producer deployment unavailable')
    if registry is not None:
        # Requery the detached signed producer and original sources at each
        # consumption fence; the input contract alone proves no completion.
        for artifact_id in contract['registry_inputs']:
            entry = registry._lookup_unchecked(artifact_id)
            if entry is None:
                raise ValueError('INPUT_SOURCE_IDENTITY_INVALID: registered producer unavailable')
            registry.lookup_operation_receipt(artifact_id,entry['version'])
    current = registered_input_contract(contract['input_binding'], registry or ArtifactRegistry(root), task_id=contract['owner_task_id'])
    if current != contract:
        raise ValueError('INPUT_SOURCE_HASH_MISMATCH: registered version/dependencies changed')
    return current


def worker_input_readback_valid(worker, binding):
    if not agent_input_binding_valid(binding):return False
    proof = worker.get('input_readback') if isinstance(worker,dict) else None
    if (not isinstance(proof,dict) or proof.get('owner_task_id') != binding.get('owner_task_id')
            or proof.get('frozen_inputs_sha256') != binding.get('frozen_inputs_sha256')
            or proof.get('before_verified') is not True or proof.get('after_verified') is not True
            or not isinstance(proof.get('contract_sha256'),str) or not _SHA.fullmatch(proof['contract_sha256'])
            or not isinstance(proof.get('consumed'),list) or not 0 < len(proof['consumed']) <= 16*12):return False
    expected = {(item['index'], frame['frame']):(frame['sha256'],frame['bytes'])
        for item in binding['frozen_inputs_manifest'] for frame in item.get('frames',[])
        if frame['frame'] in worker.get('frames',[])}
    consumed = {}
    for item in proof['consumed']:
        if (not isinstance(item,dict) or item.get('readonly_copy') is not True
                or type(item.get('input_index')) is not int or type(item.get('frame')) is not int):return False
        key=(item.get('input_index'),item.get('frame'))
        if key in consumed:return False
        consumed[key]=(item.get('sha256'),item.get('bytes'))
    return consumed == expected


def receipt_digest(receipt: dict[str, Any]) -> str:
    body = {key: value for key, value in receipt.items() if key != 'operation_receipt_sha256'}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _canonical_digest(body):
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def frame_path(pattern, frame):
    if not isinstance(pattern, str): return None
    if '%' in pattern:
        try: return str(Path(pattern % frame))
        except (TypeError, ValueError): return None
    if '#' in pattern:
        marker = re.search(r'#+', pattern)
        return str(Path(pattern[:marker.start()] + str(frame).zfill(len(marker.group())) + pattern[marker.end():]))
    return str(Path(pattern))


def _receipt_errors(receipt: dict[str, Any]) -> list[str]:
    errors = []
    def require(condition, message):
        if not condition: errors.append(message)
    require(receipt.get('schema') == SCHEMA, 'unsupported Nuke formal receipt schema')
    require(isinstance(receipt.get('command'), str) and receipt.get('command') in COMMAND_STAGES, 'unsupported Nuke render command')
    require(receipt.get('kind') == 'render' and receipt.get('state') == 'COMPLETED', 'Nuke render is not completed')
    for field in ('operation_id', 'task_id', 'request_id', 'completed_at'):
        require(isinstance(receipt.get(field), str) and bool(receipt.get(field)), 'missing Nuke ' + field)
    require(isinstance(receipt.get('node'), str) and bool(receipt['node']), 'missing Nuke Write node identity')
    for field in ('request_sha256', 'scene_fingerprint', 'artifact_operation_receipt_sha256'):
        require(isinstance(receipt.get(field), str) and bool(_SHA.fullmatch(receipt[field])), 'invalid Nuke ' + field)
    frames = receipt.get('frame_set')
    valid_frames = (isinstance(frames, list) and bool(frames) and len(frames) <= 12
        and all(type(frame) is int and frame > 0 for frame in frames)
        and len(frames) == len(set(frames)))
    require(valid_frames, 'invalid Nuke exact frame set')
    frames = frames if valid_frames else []
    snapshots = receipt.get('frame_snapshots')
    require(isinstance(snapshots, dict) and isinstance(frames, list)
        and set(snapshots) == {str(frame) for frame in frames}, 'incomplete Nuke frame snapshots')
    if isinstance(snapshots, dict):
        for item in snapshots.values():
            require(isinstance(item, dict) and isinstance(item.get('path'), str)
                and Path(item['path']).is_absolute() and type(item.get('bytes')) is int and item['bytes'] > 0
                and type(item.get('modified_ns')) is int and item['modified_ns'] > 0
                and isinstance(item.get('sha256'), str) and bool(_SHA.fullmatch(item['sha256'])),
                'invalid Nuke frame snapshot identity')
    else:
        snapshots = {}
    require(all(isinstance(snapshots.get(str(frame)), dict)
                and snapshots[str(frame)].get('path') == frame_path(receipt.get('output_pattern'), frame)
                for frame in frames), 'Nuke frame snapshot path differs from output pattern')
    require(isinstance(receipt.get('output_pattern'), str) and Path(receipt.get('output_pattern') or '.').is_absolute(),
        'invalid Nuke output pattern')
    fact = receipt.get('execution_fact')
    if not isinstance(fact, dict):
        errors.append('missing Nuke execution fact'); fact = {}
    require(fact.get('schema') == 'bridge.nuke.execution_fact/1.0'
        and isinstance(fact.get('kind'), str) and fact.get('kind') in {'synchronous_nuke_execute', 'owned_subprocess'}
        and fact.get('state') == 'COMPLETED' and fact.get('stop_confirmed') is True
        and type(fact.get('exit_code')) is int and fact['exit_code'] == 0,
        'invalid Nuke execution/stop fact')
    for outer, inner in (('operation_id','task_id'), ('request_id','request_id'),
                         ('frame_set','frame_set'), ('output_pattern','pattern'),
                         ('frame_snapshots','frame_snapshots'), ('completed_at','completed_at')):
        require(receipt.get(outer) == fact.get(inner), 'Nuke execution fact mismatch: ' + outer)
    request = receipt.get('request')
    request = request if isinstance(request, dict) else {}
    require(set(request) == ({'command', 'task_key', 'node', 'frames', 'pattern', 'input_binding', 'background', 'scene'}
            | ({'project_color'} if fact.get('project_color') is not None else set())
            | ({'output_verification'} if fact.get('output_verification') is not None else set())
            | ({'input_contract_sha256'} if fact.get('input_contract_sha256') is not None else set()))
            and request.get('project_color') == fact.get('project_color')
            and request.get('output_verification') == fact.get('output_verification')
            and request.get('input_contract_sha256') == fact.get('input_contract_sha256')
            and (fact.get('input_contract_sha256') is None or isinstance(fact['input_contract_sha256'], str)
                 and _SHA.fullmatch(fact['input_contract_sha256']))
            and isinstance(request.get('task_key'), str) and bool(request['task_key'])
            and isinstance(request.get('input_binding'), dict) and type(request.get('background')) is bool
            and request.get('command') == receipt.get('command') and request.get('node') == receipt.get('node')
            and request.get('frames') == frames and request.get('pattern') == receipt.get('output_pattern')
            and request.get('scene') == receipt.get('scene_fingerprint')
            and request.get('background') == (fact.get('kind') == 'owned_subprocess')
            and receipt.get('request_sha256') == _canonical_digest(request), 'Nuke frozen request content mismatch')
    frozen_registered = (receipt.get('command') == 'render_write'
        and isinstance(request.get('input_binding'),dict) and request['input_binding'].get('schema') == INPUT_SCHEMA)
    if receipt.get('command') in AGENT_RENDER_COMMANDS or frozen_registered:
        require(agent_input_binding_valid(request.get('input_binding'), task_id=receipt.get('task_id')),
                'Nuke agent frozen input binding missing or invalid')
    artifact_basis = {'task_id':receipt.get('operation_id'), 'pattern':receipt.get('output_pattern'),
        'frame_set':frames, 'scene_fingerprint':receipt.get('scene_fingerprint'), 'frame_snapshots':snapshots,
        'state':receipt.get('state'), 'execution_kind':fact.get('kind')}
    require(receipt.get('artifact_operation_receipt_sha256') == _canonical_digest(artifact_basis),
            'Nuke artifact operation digest mismatch')
    require(receipt.get('process_identity') == fact.get('process_identity') and bool(fact.get('process_identity')),
        'Nuke process identity mismatch')
    if fact.get('kind') == 'owned_subprocess':
        worker = fact.get('worker_receipt')
        process = fact.get('process_identity')
        require(isinstance(process, dict) and type(process.get('pid')) is int and process['pid'] > 0,
            'Nuke owned process identity missing')
        process = process if isinstance(process, dict) else {}
        supervisor = process.get('supervisor_identity') or {}
        require(process.get('kind') == 'owned_render_subprocess' and isinstance(supervisor, dict)
            and supervisor.get('task_id') == receipt.get('operation_id')
            and supervisor.get('operation_id') == receipt.get('operation_id')
            and isinstance(supervisor.get('launch_nonce'), str) and bool(supervisor['launch_nonce'])
            and isinstance(process.get('supervisor_directory'), str) and Path(process['supervisor_directory']).is_absolute()
            and isinstance(process.get('worker_script'), str) and Path(process['worker_script']).is_absolute()
            and Path(process['worker_script']).name in {'owned_render_worker.py', 'nuke_owned_render_worker.py'},
            'Nuke owned worker/supervisor identity missing')
        require(isinstance(worker, dict) and worker.get('task_id') == receipt.get('operation_id')
            and worker.get('frames') == frames and worker.get('execute_calls') == frames
            and worker.get('script_opened') is True and worker.get('node_resolved') is True
            and worker.get('node') == receipt.get('node')
            and worker.get('snapshot') == receipt.get('script_snapshot')
            and isinstance(worker.get('snapshot_sha256'), str) and bool(_SHA.fullmatch(worker['snapshot_sha256']))
            and worker.get('snapshot_sha256') == supervisor.get('snapshot_sha256')
            and worker.get('outputs') == [snapshots.get(str(frame), {}).get('path') for frame in frames or []],
            'Nuke owned worker receipt mismatch')
        composite = receipt.get('composite_contract')
        if composite is not None or supervisor.get('composite_contract_sha256') is not None:
            require(isinstance(composite,dict) and composite.get('schema') == COMPOSITE_SCHEMA
                and composite.get('write') == receipt.get('node')
                and composite.get('task_id') == receipt.get('task_id')
                and supervisor.get('owner_task_id') == receipt.get('task_id')
                and worker_composite_readback_valid(worker,composite,supervisor.get('composite_contract_sha256')),
                'Nuke owned composite snapshot consumption mismatch')
        if frozen_registered:
            require(worker_input_readback_valid(worker,request['input_binding'])
                and (worker.get('input_readback') or {}).get('contract_sha256') == supervisor.get('input_contract_sha256'),
                'Nuke owned worker frozen input consumption mismatch')
        if isinstance(worker,dict) and 'write_readback' in worker:
            require(worker_write_readback_valid(worker, operation_id=receipt.get('operation_id'),
                node=receipt.get('node'), frames=frames, snapshot_sha256=worker.get('snapshot_sha256'))
                and worker['write_readback']['settings']['file'] == receipt.get('output_pattern'),
                'Nuke owned native Write readback identity mismatch')
    else:
        verification = fact.get('verification')
        require(isinstance(verification, dict) and verification.get('ok') is True
            and verification.get('fresh') is True and isinstance(fact.get('process_identity'), str)
            and fact['process_identity'].startswith('nuke-main:'), 'Nuke synchronous verification missing')
    result = receipt.get('result')
    require(isinstance(result, dict) and result == {
        'operation_id': receipt.get('operation_id'), 'task_id': receipt.get('task_id'),
        'request_id': receipt.get('request_id'), 'state': receipt.get('state'),
        'frame_set': frames, 'frame_snapshots': snapshots, 'output_pattern': receipt.get('output_pattern')},
        'Nuke result does not bind operation output')
    try:
        require(receipt.get('operation_receipt_sha256') == receipt_digest(receipt), 'Nuke formal receipt digest mismatch')
    except (TypeError, ValueError):
        errors.append('Nuke formal receipt is not canonical JSON')
    return errors


def receipt_errors(receipt: dict[str, Any]) -> list[str]:
    try:
        return _receipt_errors(receipt)
    except (TypeError, ValueError, KeyError):
        return ['invalid Nuke formal receipt field types/content']


def finalize_render_operation(task: dict[str, Any], artifact_fact: dict[str, Any]) -> dict[str, Any] | None:
    """Emit a formal provider only from the controller's recorded completion.

    Mutable ledger retry fields stay in the artifact record; the full native
    execution fact and its immutable output identity bind this receipt.
    """
    fact = task.get('execution_fact')
    if not isinstance(fact, dict) or fact.get('state') != 'COMPLETED': return None
    fact = json.loads(json.dumps({k: v for k, v in fact.items() if k not in {'ledger_state', 'registered_at'}}))
    receipt = {
        'schema': SCHEMA, 'kind': 'render', 'command': task.get('entry'),
        'operation_id': task.get('task_id'), 'task_id': artifact_fact.get('task_id'),
        'request_id': task.get('request_id'), 'request_sha256': task.get('request_sha256'),
        'state': fact.get('state'), 'scene_fingerprint': task.get('scene_fingerprint'),
        'frame_set': task.get('frame_set'), 'output_pattern': task.get('pattern'),
        'frame_snapshots': artifact_fact.get('frame_snapshots'), 'completed_at': fact.get('completed_at'),
        'process_identity': fact.get('process_identity'), 'node': task.get('node'),
        'script_snapshot': task.get('script_snapshot'), 'execution_fact': fact,
        'artifact_operation_receipt_sha256': artifact_fact.get('operation_receipt_sha256'),
        'request': { 'command':task.get('entry'), 'task_key':task.get('task_key'), 'node':task.get('node'),
            'frames':task.get('frame_set'), 'pattern':task.get('pattern'), 'input_binding':task.get('input_binding') or {},
            'background':task.get('background'), 'scene':task.get('scene_fingerprint') },
    }
    if task.get('input_contract') is not None:
        receipt['request']['input_contract_sha256'] = _canonical_digest(task['input_contract'])
    if task.get('project_color') is not None:
        receipt['request']['project_color'] = json.loads(json.dumps(task['project_color']))
    if task.get('output_verification') is not None:
        receipt['request']['output_verification'] = json.loads(json.dumps(task['output_verification']))
    if task.get('composite_contract') is not None:receipt['composite_contract'] = task['composite_contract']
    expected_task_id = task.get('owner_task_id') or ('nuke:' + str(task.get('entry') or 'render'))
    if (artifact_fact.get('task_id') != expected_task_id
            or artifact_fact.get('scene_fingerprint') != task.get('scene_fingerprint')
            or artifact_fact.get('frame_set') != task.get('frame_set')
            or artifact_fact.get('output_pattern') != task.get('pattern')): return None
    receipt['result'] = {key: receipt[key] for key in (
        'operation_id', 'task_id', 'request_id', 'state', 'frame_set', 'frame_snapshots', 'output_pattern')}
    receipt['operation_receipt_sha256'] = receipt_digest(receipt)
    if receipt_errors(receipt): return None
    return json.loads(json.dumps(receipt))


def native_write_readback(write):
    """Read only documented static Write knobs; raw is a transform bypass.

    The returned values are native knob observations, not EXR physical
    metadata. Color semantics are usable only for explicit non-raw settings.
    """
    if write.Class() != 'Write' or not callable(getattr(write, 'knob', None)):
        raise ValueError('native Write readback unavailable')
    values = {}
    for name in ('file', 'colorspace', 'premultiplied', 'raw'):
        knob = write.knob(name)
        if knob is None or not all(callable(getattr(knob, gate, None)) for gate in ('isAnimated', 'hasExpression')):
            raise ValueError('native static Write knob unavailable: ' + name)
        if knob.isAnimated() or knob.hasExpression():
            raise ValueError('native Write knob is animated or expressed: ' + name)
        values[name] = knob.value()
    if (not isinstance(values['file'], str) or not isinstance(values['colorspace'], str)
            or type(values['premultiplied']) is not bool or type(values['raw']) is not bool):
        raise ValueError('native Write readback types unavailable')
    return {'origin':'nuke_write_readback', 'class':'Write', 'node':str(write.name()),
            'settings':values, 'static_knobs':True}


def worker_write_readback_valid(worker, *, operation_id, node, frames, snapshot_sha256):
    readback = worker.get('write_readback') if isinstance(worker,dict) else None
    return bool(isinstance(readback,dict) and readback.get('operation_id') == operation_id
        and readback.get('snapshot_sha256') == snapshot_sha256 and readback.get('frames') == frames
        and readback.get('origin') == 'nuke_write_readback' and readback.get('class') == 'Write'
        and readback.get('node') == node and readback.get('static_knobs') is True
        and isinstance(readback.get('settings'),dict)
        and set(readback['settings']) == {'file','colorspace','premultiplied','raw'}
        and isinstance(readback['settings']['file'],str)
        and isinstance(readback['settings']['colorspace'],str)
        and type(readback['settings']['premultiplied']) is bool
        and type(readback['settings']['raw']) is bool)


def capture_completion_metadata(task, snapshots):
    """Read a temporary immutable byte copy, bound to the original completion.

    Physical metadata comes only from read_exr. Color semantics come from the
    controller's static Write readback bound to this same execution graph.
    """
    from dcc_task_runtime.exr_codec import read_exr
    settings = task['native_output_settings']
    result = {}
    with tempfile.TemporaryDirectory(prefix='nuke-completion-exr-') as directory:
        for frame in task['frame_set']:
            expected = snapshots[str(frame)]; source = Path(expected['path'])
            if source.is_symlink() or not source.is_file() or str(source) != frame_path(task['pattern'], frame):
                raise ValueError('COMPLETION_OUTPUT_CHANGED: regular original frame required')
            copy = Path(directory) / (str(frame) + '.exr'); digest = hashlib.sha256(); size = 0
            with source.open('rb') as original, copy.open('wb') as target:
                before = os.fstat(original.fileno())
                for chunk in iter(lambda: original.read(1024 * 1024), b''):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024: raise ValueError('COMPLETION_EXR_BYTE_BUDGET')
                    digest.update(chunk); target.write(chunk)
                after = os.fstat(original.fileno())
            current = source.stat()
            if (size != expected['bytes'] or digest.hexdigest() != expected['sha256']
                    or before.st_mtime_ns != expected['modified_ns']
                    or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) !=
                       (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)
                    or (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns) !=
                       (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)):
                raise ValueError('COMPLETION_OUTPUT_CHANGED: bytes differ from immutable execution snapshot')
            copy.chmod(0o400)
            physical = read_exr(copy, with_pixels=False)
            physical.pop('rows', None)
            result[str(frame)] = {**physical, **expected,
                'physical_metadata_source':'read_exr', 'color_metadata_source':'verified_native_write',
                'colorspace':settings['colorspace'], 'premultiplied':settings['premultiplied']}
            if task.get('project_color') is not None:
                from dcc_task_runtime.project_color import validate_project_color
                project_color = validate_project_color(task['project_color'])
                if project_color['colorspace'] != settings['colorspace']:
                    raise ValueError('PROJECT_COLOR_OUTPUT_MISMATCH')
                result[str(frame)]['project_color'] = project_color
                result[str(frame)]['color_metadata_source'] = 'human_project_selection'
    if task.get('output_verification') is not None:
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        grade = ArtifactRegistry._output_verification({
            'output_verification': task['output_verification'], 'completion_metadata_status': 'AVAILABLE'})
        for image in result.values(): image['output_verification'] = json.loads(json.dumps(grade))
    json.dumps(result, allow_nan=False)
    return result


def _typed_completion_valid(receipt):
    fact = receipt.get('execution_fact') or {}; settings = fact.get('native_output_settings')
    metadata = fact.get('completion_metadata'); frames = receipt.get('frame_set') or []
    if (not isinstance(settings,dict) or settings.get('origin') != 'nuke_write_readback'
            or settings.get('operation_id') != receipt.get('operation_id')
            or settings.get('request_id') != receipt.get('request_id')
            or settings.get('scene_fingerprint') != receipt.get('scene_fingerprint')
            or settings.get('node') != receipt.get('node') or settings.get('class') != 'Write'
            or settings.get('pattern') != receipt.get('output_pattern') or settings.get('raw') is not False
            or not isinstance(settings.get('colorspace'),str) or not settings['colorspace'].strip()
            or 'default' in settings['colorspace'].lower() or type(settings.get('premultiplied')) is not bool
            or not isinstance(metadata,dict) or set(metadata) != {str(frame) for frame in frames}): return False
    grade = fact.get('output_verification')
    if grade is not None:
        from dcc_task_runtime.artifact_registry import ArtifactRegistry
        grade = ArtifactRegistry._output_verification({
            'output_verification': grade, 'completion_metadata_status': 'AVAILABLE'})
        if any(not isinstance(image, dict) or image.get('output_verification') != grade for image in metadata.values()):
            return False
    elif any(isinstance(image, dict) and 'output_verification' in image for image in metadata.values()):
        return False
    project_color = fact.get('project_color')
    if project_color is not None:
        from dcc_task_runtime.project_color import validate_project_color
        project_color = validate_project_color(project_color)
        if project_color['colorspace'] != settings['colorspace'] or any(
                not isinstance(image, dict) or image.get('project_color') != project_color for image in metadata.values()):
            return False
    elif any(isinstance(image, dict) and 'project_color' in image for image in metadata.values()):
        return False
    if fact.get('kind') == 'owned_subprocess':
        worker = fact.get('worker_receipt') or {}
        if not worker_write_readback_valid(worker, operation_id=receipt.get('operation_id'),
                node=receipt.get('node'), frames=frames, snapshot_sha256=worker.get('snapshot_sha256')):
            return False
        actual = worker['write_readback']['settings']
        if (actual != {'file':settings['pattern'], 'colorspace':settings['colorspace'],
                'premultiplied':settings['premultiplied'], 'raw':settings['raw']}
                or settings.get('snapshot_sha256') != worker.get('snapshot_sha256')):
            return False
    for frame in frames:
        image = metadata[str(frame)]; snapshot = receipt['frame_snapshots'][str(frame)]
        if not isinstance(image,dict): return False
        width,height,names,layout = (image.get(k) for k in ('width','height','channels','channel_layout'))
        if (type(width) is not int or type(height) is not int or min(width,height) <= 0
                or not isinstance(names,list) or not names or len(set(names)) != len(names)
                or not isinstance(layout,dict) or len(layout.get('channels') or []) != len(names)
                or image.get('structural_validated') is not True
                or type(image.get('pixel_count')) is not int or image['pixel_count'] != width*height
                or type(image.get('sample_count')) is not int or image['sample_count'] != width*height*len(names)
                or any(image.get(k) != snapshot.get(k) for k in ('path','bytes','modified_ns','sha256'))
                or image.get('physical_metadata_source') != 'read_exr'
                or image.get('color_metadata_source') != ('human_project_selection' if project_color is not None else 'verified_native_write')
                or image.get('colorspace') != settings['colorspace']
                or type(image.get('premultiplied')) is not bool or image['premultiplied'] != settings['premultiplied']
                or 'rows' in image): return False
        for name, channel in zip(names,layout['channels']):
            if (not isinstance(name,str) or not name or not isinstance(channel,dict) or channel.get('name') != name
                    or type(channel.get('pixel_type')) is not int or channel['pixel_type'] not in (0,1,2)
                    or type(channel.get('p_linear')) is not int or channel['p_linear'] not in (0,1)
                    or type(channel.get('x_sampling')) is not int or channel['x_sampling'] != 1
                    or type(channel.get('y_sampling')) is not int or channel['y_sampling'] != 1): return False
        for key in ('data_window','display_window'):
            box=layout.get(key)
            if (not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box)
                    or box[2]<box[0] or box[3]<box[1]):return False
        box=layout['data_window']
        if width!=box[2]-box[0]+1 or height!=box[3]-box[1]+1:return False
    return True


def completed_operation_projection(receipt, artifact_fact):
    """Project helper facts only from a validated existing formal completion."""
    if (not isinstance(receipt,dict) or not isinstance(artifact_fact,dict)
            or not isinstance(artifact_fact.get('execution_fact'),dict) or receipt_errors(receipt)): return None
    if (receipt.get('operation_id') != artifact_fact.get('execution_fact',{}).get('task_id')
            or receipt.get('task_id') != artifact_fact.get('task_id')
            or receipt.get('scene_fingerprint') != artifact_fact.get('scene_fingerprint')
            or receipt.get('frame_set') != artifact_fact.get('frame_set')
            or receipt.get('output_pattern') != artifact_fact.get('output_pattern')
            or receipt.get('frame_snapshots') != artifact_fact.get('frame_snapshots')
            or receipt.get('artifact_operation_receipt_sha256') != artifact_fact.get('operation_receipt_sha256')): return None
    fact=receipt['execution_fact']
    status=fact.get('completion_metadata_status') or 'UNAVAILABLE_LEGACY'
    if fact.get('kind') == 'owned_subprocess' and 'write_readback' not in (fact.get('worker_receipt') or {}):
        status = 'UNAVAILABLE_LEGACY_WORKER_READBACK'
    try:
        typed = status=='AVAILABLE' and _typed_completion_valid(receipt)
    except (KeyError, TypeError, ValueError):
        typed = False
    result={'operation_id':receipt['operation_id'], 'execution_kind':fact['kind'], 'stop_confirmed':True,
        'completion_metadata_status': 'AVAILABLE' if typed else (status if status!='AVAILABLE' else 'INVALID_BINDING')}
    if typed:
        result['metadata']=json.loads(json.dumps(fact['completion_metadata']))
        if fact.get('project_color') is not None:
            result['project_color'] = json.loads(json.dumps(fact['project_color']))
        if fact.get('output_verification') is not None:
            result['output_verification'] = json.loads(json.dumps(fact['output_verification']))
    return result
