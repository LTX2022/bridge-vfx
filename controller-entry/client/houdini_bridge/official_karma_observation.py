"""Frozen official observations and their original owned-process authority.

This module admits no process and creates no accounting root. It reuses the
shared NativeScope and signed supervisor records; JSON claims alone are refused.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from dcc_task_runtime import owned_process
from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_RESOURCE_PROFILE
from dcc_task_runtime.alpha_calibration import validate_native_process_binding
from dcc_task_runtime.render_profiles import OFFICIAL, SOURCE_HIP_SHA256
from .official_karma import SELECTED_TYPES, canonical_sha256
from .official_karma_native import (OBSERVATION_SCHEMA, MAX_OBSERVATION_BYTES, bounded_json,
                                    semantic_compare, VERSION,BEAUTY,BEAUTY_ADAPTER,BEAUTY_ATTRIBUTES,UI_PROBE_NODE,UI_PROBE_PARM,UI_PROBE_EXPRESSION,UI_PROBE_REASON,
                                    output_topology,observation_inputs)


def checked_bytes(record, limit=64*1024*1024):
    if (type(record) is not dict or set(record) != {'path', 'bytes', 'sha256'}
            or type(record['bytes']) is not int or not 0 < record['bytes'] <= limit
            or type(record['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
        raise ValueError('OFFICIAL_FILE_RECORD_INVALID')
    path = Path(record['path'])
    if (not path.is_absolute() or path != path.resolve()
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError('OFFICIAL_FILE_PATH_INVALID')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != record['bytes']:
            raise ValueError('OFFICIAL_FILE_IDENTITY_INVALID')
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, record['bytes'] - size + 1))
            if not chunk: break
            size += len(chunk)
            if size > record['bytes']:
                raise ValueError('OFFICIAL_FILE_CHANGED')
            chunks.append(chunk)
        raw = b''.join(chunks)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        if (len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']
                or any(getattr(before,k) != getattr(os.fstat(fd),k) or getattr(before,k) != getattr(path.stat(),k) for k in fields)
                or any(p.is_symlink() for p in (path, *path.parents))):
            raise ValueError('OFFICIAL_FILE_CHANGED')
        return raw
    finally:
        os.close(fd)


def file_record(path, limit=64*1024*1024):
    path = Path(path)
    size = path.stat().st_size
    if not 0 < size <= limit:
        raise ValueError('OFFICIAL_FILE_BYTE_LIMIT')
    # The second bounded read also rejects symlinks, hardlinks and identity drift.
    with path.open('rb') as stream:
        raw = stream.read(size + 1)
    record = {'path': str(path), 'bytes': size, 'sha256': hashlib.sha256(raw).hexdigest()}
    checked_bytes(record, limit)
    return record


def load_record(record, limit=MAX_OBSERVATION_BYTES):
    def unique(pairs):
        result = {}
        for k,v in pairs:
            if k in result:
                raise ValueError('OFFICIAL_JSON_DUPLICATE_FIELD')
            result[k] = v
        return result
    return bounded_json(json.loads(checked_bytes(record, limit), object_pairs_hook=unique))


def write_new(path, value):
    path = Path(path)
    if (not path.is_absolute() or path != path.resolve()
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError('OFFICIAL_FILE_PATH_INVALID')
    raw = owned_process._canonical(bounded_json(value))
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return file_record(path, MAX_OBSERVATION_BYTES)


def validate_observation(value, *, scope_binding, source_contract):
    value = bounded_json(value)
    keys = {'schema','profile','version','frame','scope_sha256','source_sha256',
            'source_contract_sha256','nodes','capture_policy','sopcreate_import','output_adapter','output_topology','stage','output','resources'}
    if (set(value) != keys or value['schema'] != OBSERVATION_SCHEMA
            or value['profile'] != OFFICIAL or value['version'] != VERSION
            or type(value['frame']) is not int or value['frame'] != 1
            or value['scope_sha256'] != scope_binding['sha256']
            or value['source_sha256'] != SOURCE_HIP_SHA256
            or value['source_contract_sha256'] != source_contract['sha256']
            or not isinstance(value['output'], str) or not Path(value['output']).is_absolute()):
        raise ValueError('OFFICIAL_OBSERVATION_BINDING_MISMATCH')
    policy=value['capture_policy']
    if (type(policy) is not dict or set(policy)!={'schema','ui_disabled','omissions'}
            or policy['schema']!='bridge.official-karma-parameter-capture/1'
            or policy['ui_disabled']!='NOT_EVALUATED' or type(policy['omissions']) is not list
            or len(policy['omissions'])!=1):
        raise ValueError('OFFICIAL_PARAMETER_CAPTURE_POLICY_INVALID')
    omitted=policy['omissions'][0]
    expected_omitted={'node':UI_PROBE_NODE,'parameter':UI_PROBE_PARM,'kind':'Toggle','components':1,
        'hidden':True,'expression_language':'Python','source_expression':UI_PROBE_EXPRESSION,'reason':UI_PROBE_REASON,'input_count':0,'value_status':'NOT_EVALUATED'}
    if (type(omitted) is not dict or set(omitted)!=set(expected_omitted)|{'template_sha256'}
            or any(type(omitted.get(k)) is not type(v) or omitted[k]!=v for k,v in expected_omitted.items())
            or not re.fullmatch('[0-9a-f]{64}',str(omitted['template_sha256']))
            or value['nodes'].get(UI_PROBE_NODE,{}).get('inputs')!=[]
            or UI_PROBE_PARM in value['nodes'][UI_PROBE_NODE]['parameters']):
        raise ValueError('OFFICIAL_UI_PROBE_OMISSION_INVALID')
    expected_adapter={'path':BEAUTY_ADAPTER,'type':'editproperties','input':'/stage/lights/update_output_image_path',
        'primpattern':BEAUTY,'createprims':'off','attributes':{p:{'type':t,'value':v,'control':'set'}
            for p,(_k,t,v) in BEAUTY_ATTRIBUTES.items()}}
    if value['output_adapter']!=expected_adapter:
        raise ValueError('OFFICIAL_OBSERVATION_BEAUTY_ADAPTER_MISMATCH')
    if value['output_topology']!=output_topology():
        raise ValueError('OFFICIAL_OBSERVATION_OUTPUT_TOPOLOGY_MISMATCH')
    contract = load_record(source_contract)
    if (contract.get('profile') != OFFICIAL or contract.get('source_sha256') != SOURCE_HIP_SHA256
            or set(value['nodes']) != {'/'+p for p in SELECTED_TYPES}
            or set(contract.get('nodes', {})) != set(value['nodes'])
            or set(value['sopcreate_import']) != {'sopimport','xform','loftpayloadinfo1'}):
        raise ValueError('OFFICIAL_OBSERVATION_NODE_SET_MISMATCH')
    for path, row in value['nodes'].items():
        if type(row) is not dict or set(row) != {'type','parameters','inputs','flags'} or row['type'] != SELECTED_TYPES[path[1:]]:
            raise ValueError('OFFICIAL_OBSERVATION_NODE_TYPE_MISMATCH')
        expected = contract['nodes'][path]
        wires = observation_inputs(path,expected)
        if row['inputs'] != wires:
            raise ValueError('OFFICIAL_OBSERVATION_CONNECTION_MISMATCH')
        if '/sopnet/create/' in path and row['flags'] != {k:expected[k] for k in ('display','render')}:
            raise ValueError('OFFICIAL_OBSERVATION_FLAG_MISMATCH')
    expected_types = {'sopimport': 'sopimport', 'xform': 'xform', 'loftpayloadinfo1': 'loftpayloadinfo'}
    for name,row in value['sopcreate_import'].items():
        if set(row) != {'type','parameters'} or row['type'] != expected_types[name]:
            raise ValueError('OFFICIAL_OBSERVATION_IMPORT_TYPE_MISMATCH')
    for row in (*value['nodes'].values(), *value['sopcreate_import'].values()):
        if type(row['parameters']) is not dict or len(row['parameters']) > 1024:
            raise ValueError('OFFICIAL_OBSERVATION_PARAMETERS_INVALID')
        for name, parm in row['parameters'].items():
            if (not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,199}',name)
                    or type(parm) is not dict or set(parm) != {'kind','multiparm','components','value','template_sha256',
                        'locked','disabled','raw_channels','keyframe_counts'}
                    or parm['kind'] not in ('Float','Int','Menu','Toggle','String','Ramp','Folder')
                    or type(parm['multiparm']) is not bool or type(parm['components']) is not int
                    or not 1 <= parm['components'] <= 16
                    or not re.fullmatch('[0-9a-f]{64}', str(parm['template_sha256']))):
                raise ValueError('OFFICIAL_OBSERVATION_PARAMETER_TEMPLATE_INVALID')
            size = parm['components']
            if (type(parm['value']) is not list or len(parm['value']) != size
                    or any(type(parm[k]) is not list or len(parm[k]) != size
                           for k in ('locked','disabled','raw_channels','keyframe_counts'))
                    or any(type(v) is not bool for v in parm['locked'])
                    or any(v is not None for v in parm['disabled'])
                    or any(type(v) is not int or not 0 <= v <= 128 for v in parm['keyframe_counts'])):
                raise ValueError('OFFICIAL_OBSERVATION_PARAMETER_VALUE_INVALID')
            vals = parm['value']
            if parm['kind'] == 'String' and any(type(v) is not str for v in vals):
                raise ValueError('OFFICIAL_OBSERVATION_PARAMETER_VALUE_INVALID')
            if parm['kind'] in ('Int','Toggle','Menu','Folder') and any(type(v) is not int for v in vals):
                raise ValueError('OFFICIAL_OBSERVATION_PARAMETER_VALUE_INVALID')
            if parm['kind'] == 'Float' and any(type(v) is not float for v in vals):
                raise ValueError('OFFICIAL_OBSERVATION_PARAMETER_VALUE_INVALID')
            if parm['kind'] == 'Ramp':
                ramp=vals[0] if size==1 else None
                if (parm['multiparm'] or type(ramp) is not dict or set(ramp)!={'ramp_basis','keys','values'}
                        or not 2<=len(ramp['keys'])<=64 or len(ramp['ramp_basis'])!=len(ramp['keys'])
                        or len(ramp['values'])!=len(ramp['keys'])
                        or any(type(v) is not float for v in ramp['keys']) or ramp['keys']!=sorted(ramp['keys'])
                        or any(v not in {'Constant','Linear','CatmullRom','MonotoneCubic','Bezier','BSpline','Hermite'}
                               for v in ramp['ramp_basis'])):
                    raise ValueError('OFFICIAL_OBSERVATION_RAMP_INVALID')
            if parm['multiparm'] and (size != 1 or type(vals[0]) is not int or not 0 <= vals[0] <= 64):
                raise ValueError('OFFICIAL_OBSERVATION_MULTIPARM_LIMIT')
    if type(value['stage']) is not dict or set(value['stage']) != {'metadata','prims'} or not value['stage']['prims']:
        raise ValueError('OFFICIAL_OBSERVATION_USD_REQUIRED')
    prims = value['stage']['prims']
    if (len(prims) > 512 or sum(row.get('type') == 'DiskLight' for row in prims.values()) != 1
            or sum(row.get('type') == 'Camera' for row in prims.values()) != 1
            or not any(row.get('type') == 'Mesh' for row in prims.values())):
        raise ValueError('OFFICIAL_OBSERVATION_SCENE_IDENTITY_REQUIRED')
    for path,row in prims.items():
        if (not isinstance(path,str) or not path.startswith('/') or '..' in path.split('/')
                or type(row) is not dict or set(row) != {'type','attributes','relationships','world_matrix',
                    'material_binding','active','instanceable','kind'}
                or row['type'] in ('Shader','Material','NodeGraph') or row['material_binding'] is not None
                or type(row['attributes']) is not dict or type(row['relationships']) is not dict):
            raise ValueError('OFFICIAL_OBSERVATION_USD_PROPERTY_INVALID')
        if any(name.startswith('material:binding') and targets for name,targets in row['relationships'].items()):
            raise ValueError('OFFICIAL_OBSERVATION_MATERIAL_BINDING_UNEXPLAINED')
    required = {
        '/stage/lights/switch3': {'input': ('Int', [1])},
        '/stage/lights/karmarendersettings': {'engine': ('String',['cpu']), 'resolution': ('Int',[420,300]),
            'denoiser': ('String',['off']), 'enablemblur': ('Toggle',[0])},
        '/stage/lights/disklight': {'lighttype': ('Menu',[2])},
    }
    for path,fields in required.items():
        parms = value['nodes'][path]['parameters']
        for name,(kind,expected) in fields.items():
            row = parms.get(name,{})
            if row.get('kind') != kind or row.get('value') != expected:
                raise ValueError('OFFICIAL_OBSERVATION_CRITICAL_FIELD_MISMATCH:' + path + '/' + name)
    if type(value['resources']) is not list or len(value['resources']) > 128:
        raise ValueError('OFFICIAL_OBSERVATION_RESOURCES_INVALID')
    for record in value['resources']: checked_bytes(record)
    return value


def required_source_paths():
    """The complete actual runtime snapshot is the minimum official freeze."""
    base=Path(__file__).resolve().parent
    repo=base.parents[3]
    required=set()
    for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
        required.update((repo/'packages'/package/'src').rglob('*.py'))
    required.update((repo/'plugins/houdini').rglob('*.py'))
    required.update((repo/'plugins/nuke').glob('*.py'))
    required.update((repo/'tools').glob('*.py'))
    return sorted(required)


def require_frozen_sources(case):
    base=Path(__file__).resolve().parent
    required=required_source_paths()
    freeze=case.get('source_freeze')
    if (type(freeze) is not dict or any(str(path) not in freeze for path in required)
            or case.get('observer') != file_record(base/'official_karma_worker.py')):
        raise ValueError('OFFICIAL_SOURCE_FREEZE_INCOMPLETE')
    for path,digest in freeze.items():
        if file_record(path)['sha256'] != digest:
            raise ValueError('OFFICIAL_FROZEN_SOURCE_CHANGED')


def native_original(scope, role, binding):
    from dcc_task_runtime import process_image
    if (scope.scope.get('evidence_source') != 'real_host' or 'software_native_boundaries' in scope.scope):
        raise ValueError('OFFICIAL_NATIVE_EVIDENCE_SCOPE_REQUIRED')
    state = scope.snapshot()
    tickets = [t for t in state['tickets'] if t['role'] == role]
    if (len(tickets) != 1 or tickets[0]['directory'] != binding.get('directory')
            or tickets[0]['identity'] != binding.get('identity') or tickets[0]['stopped_at'] is None):
        raise ValueError('OFFICIAL_ORIGINAL_SCOPE_TICKET_REQUIRED')
    directory, identity = Path(binding['directory']), binding['identity']
    start = owned_process.read_receipt(directory,'started',identity=identity)
    stop = owned_process.read_receipt(directory,'stopped',identity=identity)
    intent = json.loads((directory/'intent.json').read_text())
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_ROLES
    command_role=role
    if scope.scope.get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE:
        if role not in OFFICIAL_IDENTITY_ROLES:raise ValueError('OFFICIAL_IDENTITY_SAMPLE_ROLE_REQUIRED')
        command_role='official-open-save'
    if intent.get('command') != scope.scope['official_case']['commands'][command_role]:
        raise ValueError('OFFICIAL_ORIGINAL_FROZEN_COMMAND_REQUIRED')
    host = 'husk' if role == 'official-husk' else 'hython'
    expected = scope.scope['hosts'][host]
    checked_bytes(expected)
    if Path(expected['path']).name != host:
        raise ValueError('OFFICIAL_NATIVE_HOST_EXECUTABLE_REQUIRED')
    frozen = process_image.freeze_executable(expected['path'], VERSION, expected['sha256'])
    validate_native_process_binding(start,stop,expected_executable=frozen,identity=identity,command=intent['command'])
    return directory, identity, start, stop, intent


def _observed_original(scope, role, binding):
    directory, identity, start, stop, intent = native_original(scope, role, binding)
    payload = owned_process.read_receipt(directory,'official-observation',identity=identity)
    case = scope.scope['official_case']
    if (not payload or payload.get('scope_binding') != scope.binding
            or payload.get('started_sha256') != canonical_sha256(start)
            or payload.get('observer') != case['observer']
            or payload.get('source_contract') != case['source_contract']
            or payload.get('role') != role or payload.get('captured_pid') != start['pid']
            or payload.get('evidence_source') != 'real_host'):
        raise ValueError('OFFICIAL_ORIGINAL_OBSERVER_REQUIRED')
    require_frozen_sources(case)
    if payload['observation'].get('path') != str(directory/'observation.json'):
        raise ValueError('OFFICIAL_OBSERVATION_PATH_MISMATCH')
    observation = validate_observation(load_record(payload['observation']),
        scope_binding=scope.binding,source_contract=case['source_contract'])
    expected_path = Path(case['paths']['official_hip'])
    if (payload.get('hip', {}).get('path') != str(expected_path)
            or observation['output'] != case['paths']['official_image']):
        raise ValueError('OFFICIAL_ORIGINAL_HIP_OR_OUTPUT_MISMATCH')
    checked_bytes(payload['hip'])
    return payload, observation


def seal_observations(scope_binding, warm_binding, cold_binding, render_binding):
    """Seal only actual stopped native originals under the initial scope binding."""
    scope = NativeScope(scope_binding)
    if scope.resource_profile != OFFICIAL_RESOURCE_PROFILE:
        raise ValueError('OFFICIAL_OBSERVATION_SCOPE_REQUIRED')
    scope.check()
    warm, a = _observed_original(scope,'official-open-save',warm_binding)
    cold, b = _observed_original(scope,'official-cold-export',cold_binding)
    if warm['hip'] != cold['hip'] or a != b:
        raise ValueError('OFFICIAL_COLD_OBSERVATION_MISMATCH')
    case = scope.scope['official_case']
    if cold.get('usd',{}).get('path') != case['paths']['official_usd']:
        raise ValueError('OFFICIAL_COLD_USD_REQUIRED')
    checked_bytes(cold['usd'])
    directory, identity, start, stop, intent = native_original(scope,'official-husk',render_binding)
    if intent['command'] != case['commands']['official-husk']:
        raise ValueError('OFFICIAL_RENDER_COMMAND_MISMATCH')
    from .official_karma import compare_files
    comparison = compare_files(case['paths']['official_image'],case['paths']['official_image'],require_identical=True)
    output = file_record(case['paths']['official_image'])
    payload = {'schema':owned_process.SCHEMA,'event':'official-sealed-observation',
        'identity':cold_binding['identity'],'scope_binding':scope_binding,
        'source_contract':case['source_contract'],'observer':case['observer'],
        'warm':warm_binding,'cold':cold_binding,'render':render_binding,
        'warm_payload_sha256':canonical_sha256(warm),'cold_payload_sha256':canonical_sha256(cold),
        'observation':cold['observation'],'observation_sha256':canonical_sha256(b),
        'hip':cold['hip'],'usd':cold['usd'],'official_image':output,
        'comparison':comparison,'evidence_source':'real_host'}
    target = Path(cold_binding['directory'])
    if owned_process.read_receipt(target,payload['event'],identity=payload['identity']) is not None:
        raise ValueError('OFFICIAL_OBSERVATION_ALREADY_SEALED')
    owned_process._signed_write(target,payload)
    return {'directory':str(target),'identity':payload['identity'],'sha256':canonical_sha256(payload)}


def read_sealed(binding, *, expected_scope):
    """Reauthenticate the original observations; no supplied PASS flags are trusted."""
    if (type(binding) is not dict or set(binding) != {'directory','identity','sha256'}
            or type(binding.get('sha256')) is not str or not re.fullmatch('[0-9a-f]{64}',binding['sha256'])):
        raise ValueError('OFFICIAL_SEALED_BINDING_REQUIRED')
    scope = NativeScope(expected_scope)
    if scope.resource_profile != OFFICIAL_RESOURCE_PROFILE:
        raise ValueError('OFFICIAL_OBSERVATION_SCOPE_REQUIRED')
    payload = owned_process.read_receipt(binding['directory'],'official-sealed-observation',identity=binding['identity'])
    if not payload or canonical_sha256(payload) != binding.get('sha256') or payload.get('scope_binding') != expected_scope:
        raise ValueError('OFFICIAL_SEALED_OBSERVATION_MISMATCH')
    warm,a = _observed_original(scope,'official-open-save',payload['warm'])
    cold,b = _observed_original(scope,'official-cold-export',payload['cold'])
    native_original(scope,'official-husk',payload['render'])
    if (a != b or warm['hip'] != cold['hip'] or canonical_sha256(warm) != payload['warm_payload_sha256']
            or canonical_sha256(cold) != payload['cold_payload_sha256']
            or cold['observation'] != payload['observation']
            or canonical_sha256(b) != payload['observation_sha256']
            or payload['source_contract'] != scope.scope['official_case']['source_contract']):
        raise ValueError('OFFICIAL_SEALED_ORIGINALS_CHANGED')
    for key in ('hip','usd','official_image','observer','source_contract'):
        checked_bytes(payload[key])
    return copy.deepcopy(b)


def checked_capture_stream(record):
    """Diagnostic streams may be empty; rendered/business artifacts still may not."""
    if (type(record) is not dict or set(record)!={'path','bytes','sha256'} or type(record['bytes']) is not int
            or not 0<=record['bytes']<=1024*1024 or type(record['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',record['sha256'])):
        raise ValueError('CAPTURE_STREAM_RECORD_INVALID')
    path=Path(record['path'])
    if not path.is_absolute() or path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('CAPTURE_STREAM_PATH_INVALID')
    limit=16384 if path.name.endswith('.stderr') else 1024*1024
    if record['bytes']>limit:raise ValueError('CAPTURE_STREAM_LIMIT')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=record['bytes']:raise ValueError('CAPTURE_STREAM_IDENTITY_CHANGED')
        raw=os.read(fd,record['bytes']+1);after=os.fstat(fd)
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')
        if len(raw)!=record['bytes'] or any(getattr(before,k)!=getattr(after,k) for k in fields) or hashlib.sha256(raw).hexdigest()!=record['sha256']:
            raise ValueError('CAPTURE_STREAM_CHANGED')
        return raw
    finally:os.close(fd)


def validate_stack_qualification(record,trace_tools):
    """Verify a reviewed ordinary-target capture; this grants no native execution."""
    qualification=load_record(record)
    if (qualification.get('state')!='VERIFIED_ORDINARY_TARGET_STACK_EVIDENCE_ONLY'
            or qualification.get('H21_authorized') is not False
            or qualification.get('offline_verifier_observed_exit_code')!=0
            or qualification.get('new_targets_or_sample_or_ps_calls')!=0):
        raise ValueError('OFFICIAL_CAPTURE_QUALIFICATION_REQUIRED')
    if (type(qualification.get('raw_inputs')) is not list or len(qualification['raw_inputs'])!=6
            or {Path(item.get('path','')).name for item in qualification['raw_inputs']}!={name+'.'+stream for name in ('before','sample','after') for stream in ('stdout','stderr')}):raise ValueError('CAPTURE_STREAM_SET_INVALID')
    for item in qualification['raw_inputs']:checked_capture_stream(item)
    for key in ('parser_source','verifier','original_result','original_signed_started','original_signed_stopped','original_live_evidence','review','offline_verification'):
        checked_bytes(qualification[key])
    reviewed=load_record(qualification['review']);reviewed_tools=reviewed['tools']
    binding=qualification.get('binding',{})
    if (not qualification.get('original_native_stop_and_all_auxiliary_cleanup_verified')
            or type(qualification.get('sample_seconds')) not in (int,float) or not 0<qualification['sample_seconds']<=2.5
            or type(qualification.get('total_measured_before_original_final_write')) not in (int,float)
            or not 0<qualification['total_measured_before_original_final_write']<20
            or type(binding.get('pid')) is not int or binding['pid']<=0 or type(binding.get('parent_pid')) is not int or binding['parent_pid']<=0
            or type(binding.get('birth')) is not str or not binding['birth']
            or type(binding.get('native_frames')) is not list or not binding['native_frames']
            or any(type(frame) is not str or not re.fullmatch(r'[1-9][0-9]*\s+.+\(in [^)]+\).*\[0x[0-9a-fA-F]+\]\s*',frame) for frame in binding['native_frames'])
            or binding.get('not_host_image_proof') is not True
            or binding.get('path')!=reviewed['target_runtime_image']['path']):
        raise ValueError('OFFICIAL_CAPTURE_QUALIFICATION_EVIDENCE_INCOMPLETE')
    if any(trace_tools.get(name)!=reviewed_tools[name] for name in ('ps','sample')):
        raise ValueError('OFFICIAL_CAPTURE_QUALIFIED_TOOLS_CHANGED')
    return qualification
