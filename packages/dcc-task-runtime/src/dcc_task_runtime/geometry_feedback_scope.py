"""Fixed native authorization for one bounded geometry feedback operation."""
from __future__ import annotations

import json
from pathlib import Path
import re

SCHEMA = 'bridge.geometry-feedback-scope/1'
RESOURCE_PROFILE = 'h21_geometry_feedback_5_900_v1'
SCENE_PROFILE = 'bounded_geometry_rig_v1'
BUDGET = {'per_operation_seconds': 240, 'total_seconds': 900,
          'max_dcc_starts': 5, 'max_disk_bytes': 536870912,
          'max_heavy_operations': 1, 'automatic_retries': 0}
ROLES = {'houdini-host': 2, 'main-husk': 1, 'nuke-host': 1, 'nuke-render': 1}
ROLE_SECONDS = {'houdini-host': 240, 'main-husk': 120, 'nuke-host': 120, 'nuke-render': 120}

_FIELDS = {'schema', 'resource_profile', 'scene_profile', 'scope_id', 'task_id', 'output_root',
           'budget', 'role_seconds', 'versions', 'hosts', 'project_color', 'native_color_tokens',
           'evidence_source', 'execution_authorized', 'status', 'authorization',
           'feedback_authority', 'accounting'}


def limits(checkpoint):
    if checkpoint:
        return dict(BUDGET, max_dcc_starts=4), dict(ROLES, **{'houdini-host': 1})
    return BUDGET, ROLES


def _fail():
    raise ValueError('GEOMETRY_FEEDBACK_SCOPE_INVALID')


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail()
        value[key] = item
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def validate_scope(scope, path):
    """Authenticate the operator authority and original identity without inheriting tickets."""
    from .native_scope import _plain, _reuse_record_bytes, GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE
    from .project_color import validate_project_color
    try:
        from vfx_pipeline.geometry_feedback import validate_authority
    except ModuleNotFoundError as error:
        if error.name!='vfx_pipeline':
            raise
        # 固定监督器直接运行时只装配了同目录的别名包；仅从同一快照导入完整包根。
        import sys
        runtime=Path(__file__).resolve().parents[4]
        for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
            package_src=runtime/'packages'/name/'src'
            if not package_src.is_dir() or package_src.is_symlink():
                _fail()
            sys.path.insert(0,str(package_src))
        from vfx_pipeline.geometry_feedback import validate_authority

    if (type(scope) is not dict or not _FIELDS <= set(scope)
            or set(scope) - _FIELDS - {'process_image_policy'}
            or scope.get('schema') != SCHEMA or scope.get('resource_profile') != RESOURCE_PROFILE
            or scope.get('scene_profile') != SCENE_PROFILE
            or scope.get('evidence_source') != 'real_host'
            or scope.get('execution_authorized') is not True
            or scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        _fail()
    root = _plain(scope['output_root'])
    if (_plain(path) != root / 'scope.json'
            or type(scope['budget']) is not dict or any(type(v) is not int for v in scope['budget'].values())
            or scope['role_seconds'] != ROLE_SECONDS or type(scope['role_seconds']) is not dict
            or any(type(v) is not int for v in scope['role_seconds'].values())):
        _fail()
    for name in ('task_id', 'scope_id'):
        if type(scope[name]) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', scope[name]) is None:
            _fail()
    accounting = scope['accounting']
    if (type(accounting) is not dict or set(accounting) != {'key_path', 'key_sha256'}
            or accounting.get('key_path') != str(root / '.native-control/key')
            or type(accounting.get('key_sha256')) is not str
            or re.fullmatch(r'[0-9a-f]{64}', accounting['key_sha256']) is None):
        _fail()
    _plain(accounting['key_path'])
    # Track the signed authority and original scope in NativeScope's static read set.
    # The authority deliberately has no circular binding to this scope file.
    record = json.loads(_canonical(scope['feedback_authority']))
    _reuse_record_bytes(record)
    payload = validate_authority(record)
    if (type(payload) is not dict or payload.get('scope_root') != str(Path(path).parent)
            or scope['feedback_authority'] != record or payload.get('task_id') != scope['task_id']
            or type(payload.get('instruction')) is not str or not payload['instruction'].strip()
            or scope['authorization'] != {'authority': 'current_user_instruction',
                                          'instruction': payload['instruction']}):
        _fail()
    budget, roles = limits('checkpoint' in payload)
    if scope['budget'] != budget or payload.get('budget') != budget or payload.get('roles') != roles:
        _fail()
    source_record = payload.get('source_scope')
    source = json.loads(_reuse_record_bytes(source_record), object_pairs_hook=_unique)
    if (type(source) is not dict
            or (source.get('schema'), source.get('resource_profile')) not in
               ((GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE), (SCHEMA, RESOURCE_PROFILE))
            or source.get('scene_profile') != SCENE_PROFILE or source.get('task_id') != scope['task_id']
            or source.get('scope_id') == scope['scope_id']):
        _fail()
    source_root = _plain(source['output_root'])
    if (_plain(source_record['path']) != source_root / 'scope.json' or root == source_root
            or source_root.is_relative_to(root)
            or accounting['key_sha256'] == source.get('accounting', {}).get('key_sha256')):
        _fail()
    for name in ('versions', 'hosts', 'project_color', 'native_color_tokens'):
        if name not in source or _canonical(scope[name]) != _canonical(source[name]):
            _fail()
    if scope['versions'] != {'houdini': '21.0.631', 'nuke': '17.0v1'}:
        _fail()
    if validate_project_color(scope['project_color'])['colorspace'] != 'ACEScg':
        _fail()
    hosts = scope['hosts']
    if type(hosts) is not dict or set(hosts) != {'hython', 'husk', 'nuke', 'supervisor_python'}:
        _fail()
    for host in hosts.values():
        if (type(host) is not dict or set(host) != {'path', 'bytes', 'sha256'}
                or type(host.get('bytes')) is not int or not 0 < host['bytes'] <= 512 * 1024 * 1024
                or type(host.get('sha256')) is not str
                or re.fullmatch(r'[0-9a-f]{64}', host['sha256']) is None):
            _fail()
        _plain(host['path'])
    if 'checkpoint' in payload:
        from vfx_pipeline.geometry_task_templates import collector_policy
        expected = collector_policy(source, True)
        if expected is None or scope.get('process_image_policy') != expected:
            _fail()
    elif (('process_image_policy' in scope) != ('process_image_policy' in source)
            or _canonical(scope.get('process_image_policy')) != _canonical(source.get('process_image_policy'))):
        _fail()
    return payload
