"""Shared, durable accounting for frozen native execution scopes."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import copy
import threading
from collections import OrderedDict
import hmac
import os
import re
import stat
import json
import math
from pathlib import Path
import time
import uuid

from .execution_lock import execution_lock
from .errors import RuntimeV2Error
from .models import ErrorCode
from .platform_support import atomic_write

_ROLES = {'alpha-husk': 1, 'alpha-nuke': 1, 'houdini-host': 2,
          'nuke-host': 1, 'graph-worker': 1, 'main-husk': 1, 'nuke-render': 1}
_BUDGET = {'per_operation_seconds': 120, 'total_seconds': 600, 'max_dcc_starts': 8,
           'max_disk_bytes': 536870912, 'max_heavy_operations': 1, 'automatic_retries': 0}
HIP_SCOPE_SCHEMA = 'bridge.hip-diagnostic-scope/2'
HIP_RESOURCE_PROFILE = 'h21_hip_graph_240_cold_120_v1'
HIP_BUDGET = {'per_operation_seconds': 240, 'total_seconds': 360, 'max_dcc_starts': 2,
              'max_disk_bytes': 536870912, 'max_heavy_operations': 1, 'automatic_retries': 0}
HIP_ROLE_SECONDS = {'graph-worker': 240, 'houdini-host': 120}
_HIP_ROLES = {'graph-worker': 1, 'houdini-host': 1}
# 有限几何创作使用独立范围，不借用旧灯光范围的票据、修订或资源上限。
GEOMETRY_SCOPE_SCHEMA = 'bridge.geometry-creative-scope/1'
GEOMETRY_RESOURCE_PROFILE = 'h21_geometry_creative_14_1800_v1'
GEOMETRY_SCENE_PROFILE = 'bounded_geometry_rig_v1'
GEOMETRY_BUDGET = {'per_operation_seconds': 240, 'total_seconds': 1800,
                   'max_dcc_starts': 14, 'max_disk_bytes': 1073741824,
                   'max_heavy_operations': 1, 'automatic_retries': 0}
GEOMETRY_ROLES = {'graph-worker': 2, 'houdini-host': 6, 'main-husk': 2,
                  'nuke-host': 2, 'nuke-render': 2}
GEOMETRY_ROLE_SECONDS = {'graph-worker': 240, 'houdini-host': 240,
                         'main-husk': 120, 'nuke-host': 120, 'nuke-render': 120}
OFFICIAL_SCOPE_SCHEMA = 'bridge.official-karma-comparison-scope/1'
OFFICIAL_RESOURCE_PROFILE = 'h21_official_disklight_comparison_v1'
OFFICIAL_BUDGET = dict(_BUDGET, max_dcc_starts=11)
OFFICIAL_INCREMENTAL_MODE = 'official_incremental_reuse_v1'
# 新增量预算明确区分建图与下游宿主；旧官方及既有增量 profile 保持原值。
OFFICIAL_INCREMENTAL_RESOURCE_PROFILE = 'h21_official_disklight_incremental_graph_240_v1'
OFFICIAL_INCREMENTAL_BUDGET = dict(OFFICIAL_BUDGET, per_operation_seconds=240, max_dcc_starts=6)
OFFICIAL_INCREMENTAL_ROLE_SECONDS = {'graph-worker': 240, 'houdini-host': 120,
                                     'nuke-host': 120, 'main-husk': 120, 'nuke-render': 120}
OFFICIAL_DIAGNOSTIC_MODE = 'official_first_stage_diagnostic_v1'
OFFICIAL_IDENTITY_DIAGNOSTIC_MODE = 'official_writer_identity_diagnostic_v1'
OFFICIAL_IDENTITY_SURVEY_MODE = 'official_writer_identity_survey_v1'
OFFICIAL_STARTUP_DIAGNOSTIC_MODE = 'official_writer_startup_diagnostic_v1'
OFFICIAL_WINDOW_DIAGNOSTIC_MODE = 'official_writer_window_diagnostic_v1'
OFFICIAL_IDENTITY_MODES = (OFFICIAL_WINDOW_DIAGNOSTIC_MODE,OFFICIAL_IDENTITY_DIAGNOSTIC_MODE,OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_STARTUP_DIAGNOSTIC_MODE)
OFFICIAL_DIAGNOSTIC_MODES = (OFFICIAL_DIAGNOSTIC_MODE,*OFFICIAL_IDENTITY_MODES)
OFFICIAL_IDENTITY_ROLES = ('official-identity-1','official-identity-2','official-identity-3')
OFFICIAL_DIAGNOSTIC_BUDGET = dict(OFFICIAL_BUDGET,max_dcc_starts=1,total_seconds=120)
OFFICIAL_IDENTITY_SURVEY_BUDGET = dict(OFFICIAL_DIAGNOSTIC_BUDGET,max_dcc_starts=3)
OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET = dict(OFFICIAL_DIAGNOSTIC_BUDGET,per_operation_seconds=60,total_seconds=60)
_OFFICIAL_ROLES = dict(_ROLES, **{'official-open-save': 1, 'official-cold-export': 1, 'official-husk': 1})
_OFFICIAL_PREFIX = ('official-open-save', 'official-cold-export', 'official-husk')
# 增量仅允许实际受影响的六次下游启动；官方前缀和 alpha 不能在此模式重跑。
_OFFICIAL_INCREMENTAL_ROLES = {name: count for name, count in _ROLES.items()
                               if name not in ('alpha-husk', 'alpha-nuke')}


def _plain(raw):
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts or path != path.resolve():
        raise ValueError('NATIVE_SCOPE_PATH_INVALID')
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('NATIVE_SCOPE_SYMLINK')
    return path


def _copy(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _reuse_record_bytes(record):
    """只读取已声明原件的确定字节；增量准入不接受路径替换或摘要漂移。"""
    if (type(record) is not dict or set(record) != {'path', 'bytes', 'sha256'}
            or type(record.get('bytes')) is not int or not 0 < record['bytes'] <= 8 * 1024 * 1024
            or type(record.get('sha256')) is not str or len(record['sha256']) != 64
            or any(ch not in '0123456789abcdef' for ch in record['sha256'])):
        raise ValueError('NATIVE_SCOPE_REUSE_RECORD_INVALID')
    path = _plain(record['path'])
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(record['bytes'] + 1)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if (not stat.S_ISREG(before.st_mode) or len(raw) != record['bytes']
            or any(getattr(before, name) != getattr(after, name) for name in fields)
            or hashlib.sha256(raw).hexdigest() != record['sha256']):
        raise ValueError('NATIVE_SCOPE_REUSE_SOURCE_CHANGED')
    _track_setup_source(path, after)
    return raw


def _validate_geometry_scope(scope, scope_path):
    """只接受独立根中的有限几何授权；来源证明由可信准备者冻结后按摘要读回。"""
    from .project_color import validate_project_color
    authority = scope.get('authorization')
    forbidden = {'execution_mode', 'continuation_of', 'creative_phase', 'feedback_phase',
                 'recovery_phase', 'replacement_host_allowance', 'replacement_nuke_host_allowance',
                 'feedback_nuke_replacement', 'feedback_extra_start_approval',
                 'case_nuke_retry_revision', 'case_storage_revision', 'role_limits', 'roles'}
    if (forbidden.intersection(scope)
            or scope.get('resource_profile') != GEOMETRY_RESOURCE_PROFILE
            or scope.get('scene_profile') != GEOMETRY_SCENE_PROFILE
            or scope.get('execution_authorized') is not True
            or scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or scope.get('evidence_source') not in ('real_host', 'software_test')
            or type(authority) is not dict or set(authority) != {'authority', 'instruction'}
            or authority.get('authority') != 'current_user_instruction'
            or type(authority.get('instruction')) is not str or not authority['instruction'].strip()):
        raise ValueError('NATIVE_GEOMETRY_SCOPE_AUTHORIZATION_REQUIRED')
    for name in ('task_id', 'scope_id'):
        value = scope.get(name)
        if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) is None:
            raise ValueError('NATIVE_GEOMETRY_SCOPE_ID_INVALID')
    root = _plain(scope['output_root'])
    accounting = scope.get('accounting')
    if (Path(scope_path) != root / 'scope.json' or type(accounting) is not dict
            or set(accounting) != {'key_path', 'key_sha256'}
            or accounting.get('key_path') != str(root / '.native-control' / 'key')):
        raise ValueError('NATIVE_GEOMETRY_SCOPE_ROOT_INVALID')
    if scope.get('versions') != {'houdini': '21.0.631', 'nuke': '17.0v1'}:
        raise ValueError('NATIVE_GEOMETRY_SCOPE_VERSION_INVALID')
    color = validate_project_color(scope.get('project_color'))
    if color['colorspace'] != 'ACEScg':
        raise ValueError('NATIVE_GEOMETRY_SCOPE_COLOR_INVALID')
    hosts = scope.get('hosts')
    if type(hosts) is not dict or set(hosts) != {'hython', 'husk', 'nuke', 'supervisor_python'}:
        raise ValueError('NATIVE_GEOMETRY_SCOPE_HOSTS_REQUIRED')
    for record in hosts.values():
        if (type(record) is not dict or set(record) != {'path', 'bytes', 'sha256'}
                or type(record.get('bytes')) is not int or not 0 < record['bytes'] <= 512 * 1024 * 1024
                or type(record.get('sha256')) is not str
                or re.fullmatch(r'[0-9a-f]{64}', record['sha256']) is None):
            raise ValueError('NATIVE_GEOMETRY_SCOPE_HOSTS_REQUIRED')
        _plain(record['path'])
    # 不调用旧范围的实时预算检查，也不为历史输入创建密钥或票据。
    source = json.loads(_reuse_record_bytes(scope.get('source_reuse')))
    if (type(source) is not dict or source.get('schema') != 'bridge.geometry-reuse-source/1'
            or source.get('task_id') != scope['task_id']):
        raise ValueError('NATIVE_GEOMETRY_SCOPE_REUSE_REQUIRED')


def _validate_official_incremental(scope, scope_path):
    """新范围绑定完整原官方来源；跳过的前缀只能复用原件，不能伪造启动票据。"""
    authority = scope.get('authorization')
    if (type(authority) is not dict or set(authority) != {'authority', 'instruction'}
            or authority.get('authority') != 'current_user_instruction'
            or type(authority.get('instruction')) is not str or not authority['instruction'].strip()
            or scope.get('execution_authorized') is not True
            or scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('NATIVE_SCOPE_INCREMENTAL_AUTHORIZATION_REQUIRED')
    records = scope.get('reused_inputs')
    required = {'scope', 'bindings', 'alpha', 'configuration', 'addon', 'reference', 'calibration_reader'}
    if type(records) is not dict or set(records) != required:
        raise ValueError('NATIVE_SCOPE_REUSED_INPUTS_REQUIRED')
    raw = {name: _reuse_record_bytes(record) for name, record in records.items()}
    source = json.loads(raw['scope'])
    if (source.get('schema') != OFFICIAL_SCOPE_SCHEMA
            or source.get('resource_profile') != OFFICIAL_RESOURCE_PROFILE
            or source.get('scene_profile') != 'official_karma_disklight_v1'
            or source.get('execution_mode') is not None
            or source.get('budget') != OFFICIAL_BUDGET
            or source.get('execution_authorized') is not True
            or source.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or source.get('evidence_source') != 'real_host'):
        raise ValueError('NATIVE_SCOPE_REUSE_FULL_OFFICIAL_SOURCE_REQUIRED')
    source_root, root = _plain(source['output_root']), _plain(scope['output_root'])
    if (records['scope']['path'] != str(source_root / 'scope.json')
            or Path(scope_path) == Path(records['scope']['path'])
            or scope.get('scope_id') == source.get('scope_id')
            or root.is_relative_to(source_root) or source_root.is_relative_to(root)):
        raise ValueError('NATIVE_SCOPE_REUSE_SCOPE_NOT_DISTINCT')
    case = source.get('official_case', {})
    expected_paths = {
        'bindings': source_root / 'runtime-bindings.json',
        'alpha': source_root / 'alpha-calibration-result.json',
        'configuration': source_root / 'frozen-inputs/official-scene.json',
        'addon': source_root / 'project/control/snapshot/plugins/houdini/_impl/houdini_bridge_addon.py',
        'reference': Path(case.get('paths', {}).get('official_image', '')),
        'calibration_reader': source_root / 'project/control/snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py',
    }
    if (any(records[name]['path'] != str(path) for name, path in expected_paths.items())
            or any(scope.get(name) != source.get(name) for name in
                   ('versions', 'hosts', 'project_color', 'native_color_tokens', 'alpha_fixture', 'official_case'))
            or scope.get('evidence_source') != 'real_host'):
        raise ValueError('NATIVE_SCOPE_REUSE_SOURCE_BINDING_MISMATCH')
    binding = {name: records['scope'][name] for name in ('path', 'sha256')}
    bindings, alpha, configuration = (json.loads(raw[name]) for name in
                                       ('bindings', 'alpha', 'configuration'))
    calibration = alpha.get('calibration', {})
    if (bindings.get('scope_sha256') != binding['sha256']
            or bindings.get('evidence_source') != 'real_host'
            or alpha.get('schema') != 'bridge.alpha-runner.result/1'
            or alpha.get('scope_sha256') != binding['sha256']
            or alpha.get('bindings_sha256') != records['bindings']['sha256']
            or alpha.get('evidence_source') != 'real_host'
            or calibration.get('version') != '21.0.631'
            or calibration.get('evidence_source') != 'real_host'
            or calibration.get('plugin_build') != records['addon']['sha256']
            or calibration.get('plugin_build') != bindings.get('plugin_build')
            or calibration.get('route_sha256') != bindings.get('route_sha256')
            or configuration.get('native_scope') != binding
            or configuration.get('observation_scope') is not None
            or configuration.get('profile') != 'official_karma_disklight_v1'
            or configuration.get('source_contract') != case.get('source_contract')
            or case.get('source_freeze', {}).get(records['calibration_reader']['path'])
               != records['calibration_reader']['sha256']
            or bindings.get('source_freeze', {}).get(records['addon']['path'])
               != records['addon']['sha256']):
        raise ValueError('NATIVE_SCOPE_REUSE_SOURCE_BINDING_MISMATCH')


@contextmanager
def _accounting_lock(path):
    """Allow the supervisor's short commit to finish before a controller resumes."""
    # 历史签名链的正常并发提交也可能超过一秒；等待不增加任何原生预算。
    deadline = time.monotonic() + 5.0
    while True:
        lock = execution_lock(path, 'native-scope')
        try:
            lock.__enter__()
            break
        except RuntimeV2Error as exc:
            if exc.code != ErrorCode.INVALID_TRANSITION or time.monotonic() >= deadline:
                raise
            time.sleep(.02)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


from contextvars import ContextVar

# 仅一次顶层构造的结构复用；账本和来源摘要仍在每次命中时实时核验。
_SCOPE_CONSTRUCTION = ContextVar('bridge_scope_construction', default=None)


_SETUP_SOURCES = ContextVar('bridge_scope_setup_sources', default=None)
_SETUP_CACHE = OrderedDict()
_SETUP_CACHE_GUARD = threading.Lock()
_SETUP_CACHE_LIMIT = 16
_SETUP_STAT_FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def _setup_stamp(metadata):
    return tuple(getattr(metadata, field) for field in _SETUP_STAT_FIELDS)


def _merge_setup_sources(sources):
    """父缓存的传递依赖闭包必须进入子缓存；同路径观测冲突即拒绝。"""
    target = _SETUP_SOURCES.get()
    if target is None:
        return
    for name, stamp in sources.items():
        if name in target and target[name] != stamp:
            raise ValueError('NATIVE_SCOPE_SETUP_SOURCE_CHANGED')
        target[name] = stamp


def _track_setup_source(path, metadata):
    _merge_setup_sources({str(path): _setup_stamp(metadata)})


def _setup_cache_discard(key, entry=None):
    with _SETUP_CACHE_GUARD:
        if entry is None or _SETUP_CACHE.get(key) is entry:
            _SETUP_CACHE.pop(key, None)


def _setup_cache_get(key):
    # guard仅保护字典，不在持有它时做IO、复制或账本核验。
    with _SETUP_CACHE_GUARD:
        entry = _SETUP_CACHE.get(key)
        if entry is not None:
            _SETUP_CACHE.move_to_end(key)
    if entry is None:
        return None
    try:
        unchanged = all(_setup_stamp(_plain(name).stat()) == stamp
                        for name, stamp in entry['sources'].items())
    except (OSError, ValueError):
        unchanged = False
    if not unchanged:
        _setup_cache_discard(key, entry)
        return None
    return copy.deepcopy(entry['attributes'])


def _setup_cache_put(key, scope):
    if getattr(scope, '_resource_profile', None) == 'h21_geometry_feedback_5_900_v1':
        # 反馈authority包含签名及来源停止事实，每次构造必须重新认证。
        return
    sources = getattr(scope, '_setup_file_stats', {})
    # 无实际来源闭包的测试替身/不完整构造不进入进程缓存。
    if str(getattr(scope, 'path', '')) not in sources:
        return
    entry = {'sources': dict(sources), 'attributes': copy.deepcopy(scope.__dict__)}
    with _SETUP_CACHE_GUARD:
        _SETUP_CACHE[key] = entry
        _SETUP_CACHE.move_to_end(key)
        while len(_SETUP_CACHE) > _SETUP_CACHE_LIMIT:
            _SETUP_CACHE.popitem(last=False)


def _parent_scope(binding):
    if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
        raise ValueError('NATIVE_SCOPE_BINDING_INVALID')
    key = (str(_plain(binding['path'])), binding['sha256'])
    cache = _SCOPE_CONSTRUCTION.get()
    if cache is not None and key in cache:
        scope = cache[key]
        if scope is None:
            raise ValueError('NATIVE_SCOPE_ANCESTRY_CYCLE')
        with _accounting_lock(scope.state_path):
            scope._read()
        _merge_setup_sources(getattr(scope, '_setup_file_stats', {}))
        return scope
    return NativeScope(binding)


_CASE_NUKE_RETRY_PINS={
 'previous_scope':'0c457b385de1be601c35f10bc9a92ec2b07a5c861764ce191b760fcd557ac93c',
 'previous_state':'bd773e3eef13aa2cedc8b261286bda5daa5278b96cad865cee60a49e710aca08',
 'failed_attempt_closure':'40234dd92be452ea6bf855dc913fd8bbca0426f62c3101eecc746daeb2b21b39',
 'performance':'01b19d6929ba062c39e7c8791d4e198e981f09464f73255b313f8c894c1567b9',
 'review':'b813b64dd928a43235aadbfe31024409f263d534c4ac75b6ec2816268aa7de75'}
_CASE_NUKE_RETRY_OPERATION='nrend-cd8fc492bb4b1171'

class NativeScope:
    def __init__(self, binding):
        if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
            raise ValueError('NATIVE_SCOPE_BINDING_INVALID')
        key = (str(_plain(binding['path'])), binding['sha256'])
        cache = _SCOPE_CONSTRUCTION.get()
        token = _SCOPE_CONSTRUCTION.set({}) if cache is None else None
        cache = _SCOPE_CONSTRUCTION.get()
        if key in cache and cache[key] is None:
            if token is not None:
                _SCOPE_CONSTRUCTION.reset(token)
            raise ValueError('NATIVE_SCOPE_ANCESTRY_CYCLE')
        cache[key] = None
        outer_sources = _SETUP_SOURCES.get()
        sources = {}
        source_token = _SETUP_SOURCES.set(sources)
        try:
            cached = _setup_cache_get(key)
            if cached is None:
                self._setup(binding)
            else:
                self.__dict__.update(cached)
                _merge_setup_sources(self._setup_file_stats)
            # 实时账本、签名、前驱前缀、停止事实和scope摘要从不进入静态缓存。
            with _accounting_lock(self.state_path):
                self._read()
            if not all(_setup_stamp(_plain(name).stat()) == stamp for name, stamp in sources.items()):
                raise ValueError('NATIVE_SCOPE_SETUP_SOURCE_CHANGED')
            self._setup_file_stats = dict(sources)
            _setup_cache_put(key, self)
            cache[key] = self
        except BaseException:
            cache.pop(key, None)
            _setup_cache_discard(key)
            raise
        finally:
            _SETUP_SOURCES.reset(source_token)
            if token is not None:
                _SCOPE_CONSTRUCTION.reset(token)
        if outer_sources is not None:
            _merge_setup_sources(self._setup_file_stats)

    def _setup(self, binding):
        if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
            raise ValueError('NATIVE_SCOPE_BINDING_INVALID')
        self.binding = _copy(binding)
        self.path = _plain(binding['path'])
        with self.path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read()
            after = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or _setup_stamp(before) != _setup_stamp(after)
                or hashlib.sha256(raw).hexdigest() != binding['sha256']):
            raise ValueError('NATIVE_SCOPE_CHANGED')
        _track_setup_source(self.path, after)
        self.scope = json.loads(raw)
        budget = self.scope.get('budget')
        schema = self.scope.get('schema')
        self._resource_profile = None
        if schema == 'bridge.engineering-closure-scope/1':
            if 'resource_profile' in self.scope or 'role_seconds' in self.scope:
                raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
            self._budget, self._roles = _copy(_BUDGET), _copy(_ROLES)
            self._role_seconds = {role: 120 for role in _ROLES}
        elif schema == OFFICIAL_SCOPE_SCHEMA:
            profile = self.scope.get('resource_profile')
            mode = self.scope.get('execution_mode')
            if self.scope.get('scene_profile') != 'official_karma_disklight_v1':
                raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
            if profile == OFFICIAL_INCREMENTAL_RESOURCE_PROFILE:
                # 只对新显式增量 profile 分配 240 秒建图；完整来源仍须原官方预算。
                role_seconds = self.scope.get('role_seconds')
                if (mode != OFFICIAL_INCREMENTAL_MODE or type(role_seconds) is not dict
                        or role_seconds != OFFICIAL_INCREMENTAL_ROLE_SECONDS
                        or any(type(value) is not int for value in role_seconds.values())):
                    raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
                _validate_official_incremental(self.scope, self.path)
                self._resource_profile = profile
                self._budget = _copy(OFFICIAL_INCREMENTAL_BUDGET)
                self._roles = _copy(_OFFICIAL_INCREMENTAL_ROLES)
                self._role_seconds = _copy(OFFICIAL_INCREMENTAL_ROLE_SECONDS)
                if 'replacement_host_allowance' in self.scope:
                    allowance = self.scope['replacement_host_allowance']
                    if (type(allowance) is not int or allowance != 1
                            or type(self.scope.get('accounting')) is not dict
                            or 'namespace' not in self.scope['accounting']):
                        raise ValueError('NATIVE_SCOPE_REPLACEMENT_HOST_ALLOWANCE_INVALID')
                    # 仅替换已花掉的首次启动失败；绝对上限为七票及三个宿主，不逐代累加。
                    self._budget['max_dcc_starts'] = 7
                    self._roles['houdini-host'] = 3
                if 'replacement_nuke_host_allowance' in self.scope:
                    allowance = self.scope['replacement_nuke_host_allowance']
                    if (type(allowance) is not int or allowance != 1
                            or type(self.scope.get('accounting')) is not dict
                            or 'namespace' not in self.scope['accounting']):
                        raise ValueError('NATIVE_SCOPE_REPLACEMENT_NUKE_HOST_ALLOWANCE_INVALID')
                    # Nuke 写准备仅获一次控制宿主替换；累计绝对八票，不随续范围累加。
                    self._budget['max_dcc_starts'] = 8
                    self._roles['nuke-host'] = 2
            else:
                # 保留既有官方及增量 v1 范围的原始读取与准入合同。
                if (profile != OFFICIAL_RESOURCE_PROFILE or 'role_seconds' in self.scope
                        or mode is not None and mode not in (*OFFICIAL_DIAGNOSTIC_MODES, OFFICIAL_INCREMENTAL_MODE)):
                    raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
                self._resource_profile = OFFICIAL_RESOURCE_PROFILE
                self._budget,self._roles=(_copy(OFFICIAL_DIAGNOSTIC_BUDGET),{'official-open-save':1}) if mode in OFFICIAL_DIAGNOSTIC_MODES else (_copy(OFFICIAL_BUDGET),_copy(_OFFICIAL_ROLES))
                if mode == OFFICIAL_INCREMENTAL_MODE:
                    _validate_official_incremental(self.scope, self.path)
                    self._roles = _copy(_OFFICIAL_INCREMENTAL_ROLES)
                if mode==OFFICIAL_IDENTITY_SURVEY_MODE:
                    self._budget,self._roles=_copy(OFFICIAL_IDENTITY_SURVEY_BUDGET),dict.fromkeys(OFFICIAL_IDENTITY_ROLES,1)
                if mode in (OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE):self._budget=_copy(OFFICIAL_STARTUP_DIAGNOSTIC_BUDGET)
                self._role_seconds = {role:self._budget['per_operation_seconds'] for role in self._roles}
        elif schema == GEOMETRY_SCOPE_SCHEMA:
            _validate_geometry_scope(self.scope, self.path)
            role_seconds = self.scope.get('role_seconds')
            if (type(role_seconds) is not dict or role_seconds != GEOMETRY_ROLE_SECONDS
                    or any(type(value) is not int for value in role_seconds.values())):
                raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
            self._resource_profile = GEOMETRY_RESOURCE_PROFILE
            self._budget, self._roles = _copy(GEOMETRY_BUDGET), _copy(GEOMETRY_ROLES)
            self._role_seconds = _copy(GEOMETRY_ROLE_SECONDS)
        elif schema == 'bridge.geometry-feedback-scope/1':
            from .geometry_feedback_scope import validate_scope, RESOURCE_PROFILE, limits, ROLE_SECONDS
            authority = validate_scope(self.scope, self.path)
            BUDGET, ROLES = limits('checkpoint' in authority)
            self._resource_profile = RESOURCE_PROFILE
            self._budget, self._roles = _copy(BUDGET), _copy(ROLES)
            self._role_seconds = _copy(ROLE_SECONDS)
        elif schema == 'bridge.rectlight-shape-scope/1':
            # 新软箱任务独立从0计账；不进入旧Rect追加阶段，也不继承其50张票据。
            from .rectlight_shape_scope import validate_scope,RESOURCE_PROFILE,BUDGET,ROLES,ROLE_SECONDS
            validate_scope(self.scope,self.path)
            self._resource_profile = RESOURCE_PROFILE
            self._budget,self._roles = _copy(BUDGET),_copy(ROLES)
            self._role_seconds = _copy(ROLE_SECONDS)
        elif schema == 'bridge.softbody-shot-scope/1':
            from .softbody_shot_scope import validate_scope, PROFILE
            _, self._budget, self._roles, self._role_seconds = validate_scope(self.scope, self.path)
            self._resource_profile = PROFILE
        elif schema == HIP_SCOPE_SCHEMA:
            role_seconds = self.scope.get('role_seconds')
            if (type(self.scope.get('resource_profile')) is not str
                    or self.scope['resource_profile'] != HIP_RESOURCE_PROFILE
                    or type(role_seconds) is not dict or role_seconds != HIP_ROLE_SECONDS
                    or any(type(value) is not int for value in role_seconds.values())):
                raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
            self._resource_profile = HIP_RESOURCE_PROFILE
            self._budget, self._roles = _copy(HIP_BUDGET), _copy(_HIP_ROLES)
            self._role_seconds = _copy(HIP_ROLE_SECONDS)
        else:
            raise ValueError('NATIVE_SCOPE_BUDGET_INVALID')
        if 'feedback_phase' in self.scope:
            self._setup_feedback_phase()
        if 'recovery_phase' in self.scope:
            self._setup_recovery_phase()
        if 'creative_phase' in self.scope:
            self._setup_creative_phase()
        if ('case_nuke_retry_revision' in self.scope and (self.scope.get('creative_phase') or {}).get('schema')!='bridge.official-case-creative-phase/1'):
            raise ValueError('NATIVE_CASE_NUKE_RETRY_INVALID')
        if ('case_storage_revision' in self.scope
                and (self.scope.get('creative_phase') or {}).get('schema')!='bridge.official-case-creative-phase/1'):
            raise ValueError('NATIVE_CASE_STORAGE_REVISION_INVALID')
        if ('replacement_host_allowance' in self.scope
                and self.resource_profile != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE):
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_HOST_ALLOWANCE_INVALID')
        if ('replacement_nuke_host_allowance' in self.scope
                and self.resource_profile != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE):
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_NUKE_HOST_ALLOWANCE_INVALID')
        if 'process_image_policy' in self.scope:
            from .process_image import validate_collector_policy
            validate_collector_policy(self.scope['process_image_policy'])
        if self.scope.get('execution_mode')==OFFICIAL_WINDOW_DIAGNOSTIC_MODE:
            item=self.scope.get('stack_qualification')
            if (not isinstance(item,dict) or set(item)!={'path','bytes','sha256'} or type(item.get('path')) is not str or type(item.get('bytes')) is not int or item['bytes']<=0 or type(item.get('sha256')) is not str or len(item['sha256'])!=64):raise ValueError('NATIVE_WINDOW_QUALIFICATION_REQUIRED')
        trace_tools=self.scope.get('writer_trace_tools')
        if self.scope.get('execution_mode') in OFFICIAL_IDENTITY_MODES:
            expected_trace_tools={'ps':'/bin/ps','sample':'/usr/bin/sample'}
            if self.scope.get('execution_mode')==OFFICIAL_WINDOW_DIAGNOSTIC_MODE:expected_trace_tools['vmmap']='/usr/bin/vmmap'
            if (not isinstance(trace_tools,dict) or set(trace_tools)!=set(expected_trace_tools) or any(
                    not isinstance(trace_tools[name],dict) or set(trace_tools[name])!={'path','bytes','sha256'}
                    or trace_tools[name].get('path')!=path or type(trace_tools[name].get('bytes')) is not int
                    or trace_tools[name]['bytes']<=0 or type(trace_tools[name].get('sha256')) is not str
                    or len(trace_tools[name]['sha256'])!=64
                    for name,path in expected_trace_tools.items())):
                raise ValueError('NATIVE_SCOPE_TRACE_TOOLS_INVALID')
        elif trace_tools is not None:raise ValueError('NATIVE_SCOPE_TRACE_MODE_REQUIRED')
        if schema!=OFFICIAL_SCOPE_SCHEMA and 'execution_mode' in self.scope:
            raise ValueError('NATIVE_SCOPE_PROFILE_INVALID')
        if (type(budget) is not dict or budget != self._budget
                or any(type(value) is not int for value in budget.values())):
            raise ValueError('NATIVE_SCOPE_BUDGET_INVALID')
        self.root = _plain(self.scope['output_root'])
        if not self.path.is_relative_to(self.root) or not self.root.is_dir():
            raise ValueError('NATIVE_SCOPE_ROOT_INVALID')
        self.state_path = self.root / 'native-scope-state.json'
        self._continuation_previous = None
        self._continuation_state = None
        self._continuation_claim_path = None
        accounting = self.scope.get('accounting')
        if not isinstance(accounting, dict):
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_REQUIRED')
        namespaced = set(accounting) == {'key_path', 'key_sha256', 'namespace'}
        if not namespaced and set(accounting) != {'key_path', 'key_sha256'}:
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_REQUIRED')
        accounting_root = self.root / '.native-control'
        if namespaced:
            namespace = accounting['namespace']
            if (self.resource_profile != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
                    or self.scope.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE
                    or type(namespace) is not str
                    or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', namespace) is None
                    or self.path != self.root / 'continuations' / namespace / 'scope.json'):
                raise ValueError('NATIVE_SCOPE_CONTINUATION_NAMESPACE_INVALID')
            accounting_root = accounting_root / namespace
            self.state_path = accounting_root / 'native-scope-state.json'
        elif 'continuation_of' in self.scope:
            raise ValueError('NATIVE_SCOPE_CONTINUATION_NAMESPACE_REQUIRED')
        self.key_path = _plain(accounting['key_path'])
        if (self.key_path.parent != accounting_root
                or namespaced and self.key_path != accounting_root / 'key'
                or not isinstance(accounting['key_sha256'], str)
                or len(accounting['key_sha256']) != 64):
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_INVALID')
        self.journal_path = self.key_path.parent / 'accounting-journal.jsonl'
        self.anchor_path = self.key_path.parent / 'accounting-anchor.json'
        if namespaced:
            self._prepare_continuation()

    def _setup_feedback_phase(self):
        """只允许显式授权的单次反馈阶段，保留旧预算与签名消耗前缀。"""
        phase = self.scope['feedback_phase']
        if (self.resource_profile != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
                or type(phase) is not dict or set(phase) != {'schema','task_id','source_delivery','prior_scope','starts','seconds'}
                or phase.get('schema') != 'bridge.disklight-feedback-phase/1'
                or phase.get('starts') != 6 or phase.get('seconds') != 600
                or type(phase.get('task_id')) is not str or not phase['task_id']):
            raise ValueError('NATIVE_SCOPE_FEEDBACK_PHASE_INVALID')
        prior = json.loads(_reuse_record_bytes(phase['prior_scope']))
        predecessor = json.loads(_reuse_record_bytes(self.scope.get('continuation_of')))
        continuation = phase.get('prior_scope') != self.scope.get('continuation_of')
        replacement=self.scope.get('feedback_nuke_replacement')
        if continuation and (predecessor.get('feedback_phase') != phase
                or type(replacement) is not int or replacement not in (1,2)
                or replacement != (predecessor.get('feedback_nuke_replacement') or 0)+1):
            raise ValueError('NATIVE_SCOPE_FEEDBACK_CONTINUATION_INVALID')
        base = _parent_scope({k:phase['prior_scope'][k] for k in ('path','sha256')})
        with _accounting_lock(base.state_path):
            self._feedback_base_state = _copy(base._read())
        delivery = json.loads(_reuse_record_bytes(phase['source_delivery']))
        if (prior.get('feedback_phase') is not None or prior.get('resource_profile') != self.resource_profile
                or delivery.get('state') != 'TASK_AND_ARTIFACT_REGISTERED'
                or delivery.get('task_id') != phase['task_id']
                or delivery.get('accounting',{}).get('scope') != phase['prior_scope']):
            raise ValueError('NATIVE_SCOPE_FEEDBACK_SOURCE_INVALID')
        self._feedback_start_limit=6
        extra=self.scope.get('feedback_extra_start_approval')
        if extra is not None:
            approval=json.loads(_reuse_record_bytes(extra))
            if (approval.get('schema')!='bridge.feedback-budget-approval/1'
                    or approval.get('authority')!='current_human_user'
                    or not isinstance(approval.get('instruction'),str) or not approval['instruction'].strip()
                    or approval.get('feedback_base_scope')!=phase['prior_scope']
                    or approval.get('previous_scope')!=self.scope.get('continuation_of')
                    or approval.get('max_phase_starts')!=7 or approval.get('max_phase_seconds')!=600
                    or replacement!=2):
                raise ValueError('NATIVE_SCOPE_FEEDBACK_EXTRA_START_APPROVAL_REQUIRED')
            self._feedback_start_limit=7
        if replacement==2 and extra is None:
            raise ValueError('NATIVE_SCOPE_FEEDBACK_EXTRA_START_APPROVAL_REQUIRED')
        self._budget['max_dcc_starts'] = prior['budget']['max_dcc_starts'] + self._feedback_start_limit
        self._budget['total_seconds'] = prior['budget']['total_seconds'] + 600
        for role,count in {'houdini-host':2,'main-husk':1,'nuke-host':1,'nuke-render':1}.items():
            self._roles[role] += count
        self._feedback_phase = phase
        if self.scope.get('feedback_nuke_replacement') is not None:
            if not continuation or type(replacement) is not int or replacement not in (1,2):
                raise ValueError('NATIVE_SCOPE_FEEDBACK_NUKE_REPLACEMENT_INVALID')
            previous = _parent_scope({k:self.scope['continuation_of'][k] for k in ('path','sha256')})
            previous_state = previous.snapshot()
            added = previous_state['tickets'][len(self._feedback_base_state['tickets']):]
            hosts = [t for t in added if t['role']=='nuke-host']
            if (len(hosts)!=replacement or any(t['role']=='nuke-render' for t in added)
                    or any(t.get('stopped_at') is None for t in added)):
                raise ValueError('NATIVE_SCOPE_FEEDBACK_NUKE_REPLACEMENT_PROOF_REQUIRED')
            from . import owned_process
            stopped=previous._stop(hosts[0])
            if stopped is None or owned_process.execution_returncode(stopped)==0:
                raise ValueError('NATIVE_SCOPE_FEEDBACK_NUKE_REPLACEMENT_PROOF_REQUIRED')
            self._roles['nuke-host'] += replacement

    def _setup_recovery_phase(self):
        """显式恢复阶段固定增加六票/600秒，原反馈及失败消耗完整继承。"""
        phase = self.scope['recovery_phase']
        fields = {'schema', 'task_id', 'prior_scope', 'source_delivery', 'source_preparation',
                  'input_source', 'starts', 'seconds', 'interrupt_request_id'}
        if (self.resource_profile != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
                or 'feedback_phase' in self.scope or type(phase) is not dict or set(phase) != fields
                or phase.get('schema') != 'bridge.disklight-recovery-phase/1'
                or type(phase.get('starts')) is not int or phase['starts'] != 6
                or type(phase.get('seconds')) is not int or phase['seconds'] != 600
                or not isinstance(phase.get('task_id'), str) or not phase['task_id']
                or not isinstance(phase.get('interrupt_request_id'), str)
                or re.fullmatch(r'[A-Za-z0-9_-]{2,100}', phase['interrupt_request_id']) is None):
            raise ValueError('NATIVE_SCOPE_RECOVERY_PHASE_INVALID')
        base = _parent_scope({k: phase['prior_scope'][k] for k in ('path', 'sha256')})
        previous = json.loads(_reuse_record_bytes(self.scope.get('continuation_of')))
        prep = json.loads(_reuse_record_bytes(phase['source_preparation']))
        delivery = json.loads(_reuse_record_bytes(phase['source_delivery']))
        source = json.loads(_reuse_record_bytes(phase['input_source']))
        if (base.scope.get('recovery_phase') is not None or base.scope.get('feedback_phase', {}).get('task_id') != phase['task_id']
                or prep.get('scope') != base.binding or prep.get('source') != phase['input_source']
                or delivery.get('state') != 'FEEDBACK_AND_DOWNSTREAM_COMPLETE'
                or delivery.get('task_id') != phase['task_id'] or delivery.get('artifact_version') != 2
                or source.get('task_id') != phase['task_id'] or source.get('artifact_id') != delivery.get('artifact_id')
                or source.get('artifact_version') != 2
                or phase['prior_scope'] != self.scope.get('continuation_of') and previous.get('recovery_phase') != phase):
            raise ValueError('NATIVE_SCOPE_RECOVERY_SOURCE_INVALID')
        with _accounting_lock(base.state_path):
            self._recovery_base_state = _copy(base._read())
        if any(t.get('stopped_at') is None for t in self._recovery_base_state['tickets']):
            raise ValueError('NATIVE_SCOPE_RECOVERY_BASE_NOT_STOPPED')
        self._budget = dict(base._budget, max_dcc_starts=base._budget['max_dcc_starts'] + 6,
                            total_seconds=base._budget['total_seconds'] + 600)
        self._roles = dict(base._roles)
        for role in ('nuke-host', 'nuke-render'):
            self._roles[role] += 3
        self._role_seconds = dict(base._role_seconds)
        self._recovery_phase = phase

    def _creative_start_limit(self, phase):
        """仅接受本任务已独立审定的一次10→12修订；不能按后继重复增额。"""
        if type(phase) is not dict:
            raise ValueError('NATIVE_SCOPE_CREATIVE_PHASE_INVALID')
        starts = phase.get('starts')
        if starts == 10 and type(starts) is int:
            if 'creative_budget_revision' in self.scope:
                raise ValueError('NATIVE_SCOPE_CREATIVE_REVISION_UNEXPECTED')
            return 10, False
        if starts != 12 or type(starts) is not int:
            raise ValueError('NATIVE_SCOPE_CREATIVE_PHASE_INVALID')
        revision = json.loads(_reuse_record_bytes(self.scope.get('creative_budget_revision')))
        expected = {'schema': 'bridge.creative-budget-revision/1',
                    'authority': 'existing_user_authorization_and_independent_plan_review',
                    'task_id': '7c65a89096e84533b8f0ace596cfe1c2',
                    'source_phase_sha256': '900411ab42c6b255abb1895d670f96ad17a0221c250c9545e751d12c131d2155', 'starts': 12, 'seconds': 1200}
        if (set(revision) != set(expected) | {'previous_scope', 'review'}
                or any(revision.get(k) != v for k, v in expected.items())
                or phase.get('task_id') != expected['task_id']
                or revision['previous_scope'].get('sha256') != '43bd5ecbef4c7b97c28a22fac1eec1597fd4a3d2b372e6065a6cdc7e6f06d36a'
                or revision['review'].get('sha256') != 'c154c3ce78bfb53daa8bde8f9db4e287e117f0b2dc701a920c2d5a65f895b460'):
            raise ValueError('NATIVE_SCOPE_CREATIVE_REVISION_INVALID')
        prior = json.loads(_reuse_record_bytes(revision['previous_scope']))
        _reuse_record_bytes(revision['review'])
        original = dict(phase, starts=10)
        digest = hashlib.sha256(self._canonical(original)).hexdigest()
        if digest != expected['source_phase_sha256'] or prior.get('creative_phase') != original:
            raise ValueError('NATIVE_SCOPE_CREATIVE_REVISION_SOURCE_INVALID')
        previous = json.loads(_reuse_record_bytes(self.scope.get('continuation_of')))
        mapped = (self.scope.get('continuation_of') == revision['previous_scope']
                  and previous.get('creative_phase') == original)
        if not mapped and (previous.get('creative_phase') != phase
                           or previous.get('creative_budget_revision') != self.scope['creative_budget_revision']):
            raise ValueError('NATIVE_SCOPE_CREATIVE_REVISION_CHAIN_INVALID')
        return 12, mapped

    def _setup_creative_phase(self):
        """外部agent创作固定十票/1200秒；模型不能改变预算或原任务历史。"""
        phase = self.scope['creative_phase']
        if phase.get('schema') == 'bridge.official-case-creative-phase/1':
            return self._setup_case_creative_phase()
        fields = {'schema', 'task_id', 'prior_scope', 'source_delivery', 'input_source', 'starts', 'seconds'}
        start_limit, budget_mapped = self._creative_start_limit(phase)
        if (self.resource_profile != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
                or any(k in self.scope for k in ('feedback_phase', 'recovery_phase'))
                or type(phase) is not dict or set(phase) != fields
                or phase.get('schema') != 'bridge.disklight-creative-phase/1'
                or type(phase.get('starts')) is not int or phase['starts'] != start_limit
                or type(phase.get('seconds')) is not int or phase['seconds'] != 1200):
            raise ValueError('NATIVE_SCOPE_CREATIVE_PHASE_INVALID')
        base = _parent_scope({k: phase['prior_scope'][k] for k in ('path', 'sha256')})
        delivery = json.loads(_reuse_record_bytes(phase['source_delivery']))
        input_source = json.loads(_reuse_record_bytes(phase['input_source']))
        previous = json.loads(_reuse_record_bytes(self.scope.get('continuation_of')))
        if (base.scope.get('creative_phase') is not None
                or base.scope.get('recovery_phase', {}).get('task_id') != phase.get('task_id')
                or delivery.get('state') != 'NUKE_FRAME_ENTRY_RECOVERY_ACCEPTED'
                or delivery.get('task_id') != phase.get('task_id')
                or delivery.get('input_artifact_version') != 2
                or input_source.get('task_id') != phase.get('task_id')
                or input_source.get('artifact_id') != delivery.get('input_artifact_id')
                or input_source.get('artifact_version') != 2
                or phase['prior_scope'] != self.scope.get('continuation_of') and previous.get('creative_phase') != phase and not budget_mapped):
            raise ValueError('NATIVE_SCOPE_CREATIVE_SOURCE_INVALID')
        with _accounting_lock(base.state_path):
            self._creative_base_state = _copy(base._read())
        if (any(t.get('stopped_at') is None for t in self._creative_base_state['tickets'])
                or len(self._creative_base_state['tickets']) != delivery.get('accounting', {}).get('family_starts')):
            raise ValueError('NATIVE_SCOPE_CREATIVE_PRIOR_STOPS_REQUIRED')
        self._budget = dict(base._budget, max_dcc_starts=base._budget['max_dcc_starts'] + start_limit,
                            total_seconds=base._budget['total_seconds'] + 1200)
        self._roles = dict(base._roles)
        for role, count in {'houdini-host': 6 + start_limit - 10, 'main-husk': 3, 'nuke-render': 3}.items():
            self._roles[role] += count
        self._role_seconds = dict(base._role_seconds)

    def _setup_case_creative_phase(self):
        """第二官方分支只追加一次固定预算，完整继承已验收的三十三次历史。"""
        phase=self.scope['creative_phase']
        fields={'schema','task_id','prior_scope','source_delivery','input_source','case_contract','ledger_root','starts','seconds'}
        start_limit,budget_mapped=self._case_start_limit(phase)
        if (self.resource_profile!=OFFICIAL_INCREMENTAL_RESOURCE_PROFILE or set(phase)!=fields
                or type(phase['starts']) is not int or phase['starts']!=start_limit
                or type(phase['seconds']) is not int or phase['seconds']!=1800
                or any(k in self.scope for k in ('feedback_phase','recovery_phase'))):
            raise ValueError('NATIVE_CASE_PHASE_INVALID')
        base=_parent_scope({k:phase['prior_scope'][k] for k in ('path','sha256')})
        delivery=json.loads(_reuse_record_bytes(phase['source_delivery']))
        source=json.loads(_reuse_record_bytes(phase['input_source']))
        contract=json.loads(_reuse_record_bytes(phase['case_contract']))
        previous=json.loads(_reuse_record_bytes(self.scope['continuation_of']))
        contract_corrected=self._case_contract_correction_valid(dict(phase,starts=14) if budget_mapped else phase,previous)
        if (base.scope.get('creative_phase',{}).get('schema')!='bridge.disklight-creative-phase/1'
                or base.scope['creative_phase'].get('starts')!=12
                or delivery.get('state')!='TWO_REVISION_CREATIVE_ACCEPTED'
                or delivery.get('independent_review',{}).get('verdict')!='PASS'
                or delivery.get('accounting',{}).get('family_starts')!=33
                or delivery.get('task_id')!=phase['task_id'] or source.get('task_id')!=phase['task_id']
                or source.get('producer_scope')!=phase['prior_scope']
                or source.get('artifact_version')!=4 or source.get('artifact_id')!='disklight_incremental_main'
                or contract.get('schema')!='bridge.official-rectlight-source/1'
                or contract.get('case_id')!='karma_lights_rectlight_v1'
                or phase['prior_scope']!=self.scope['continuation_of'] and previous.get('creative_phase')!=phase and not contract_corrected):
            raise ValueError('NATIVE_CASE_SOURCE_INVALID')
        for record in delivery['results']:_reuse_record_bytes(record)
        _reuse_record_bytes(delivery['independent_review']['record'])
        ledger=_plain(phase['ledger_root'])
        if ledger!=Path(phase['case_contract']['path']).parent/'artifact_ledger' or not ledger.is_relative_to(self.path.parent):
            # 后继只允许原阶段同一目录，不向别的案例借登记账本。
            if ledger!=Path(phase['case_contract']['path']).parent/'artifact_ledger' or previous.get('creative_phase')!=phase and not contract_corrected:
                raise ValueError('NATIVE_CASE_LEDGER_INVALID')
        with _accounting_lock(base.state_path):self._creative_base_state=_copy(base._read())
        if len(self._creative_base_state['tickets'])!=33 or any(t.get('stopped_at') is None for t in self._creative_base_state['tickets']):
            raise ValueError('NATIVE_CASE_PRIOR_STOPS_REQUIRED')
        self._budget=dict(base._budget,max_dcc_starts=base._budget['max_dcc_starts']+start_limit,total_seconds=base._budget['total_seconds']+1800)
        self._budget['max_disk_bytes']=self._case_storage_limit(phase,previous)
        self._roles=dict(base._roles)
        for role,count in {'houdini-host':8+start_limit-14,'main-husk':5,'nuke-render':3}.items():self._roles[role]+=count
        self._role_seconds=dict(base._role_seconds)
        self._roles['official-case-husk']=1
        self._role_seconds['official-case-husk']=120
        self._creative_effective_starts=start_limit+self._case_nuke_retry_allowance(phase,previous)
        self._budget['max_dcc_starts']+=self._creative_effective_starts-start_limit

    def _case_nuke_retry_allowance(self,phase,previous):
        """只为49号已真实失败并释放槽的Nuke追加一次正常重试，不增加时间或角色。"""
        record=self.scope.get('case_nuke_retry_revision')
        if record is None:
            if previous.get('case_nuke_retry_revision') is not None:raise ValueError('NATIVE_CASE_NUKE_RETRY_CHAIN_INVALID')
            return 0
        revision=json.loads(_reuse_record_bytes(record))
        expected={'schema':'bridge.rectlight-nuke-retry-revision/1','task_id':'7c65a89096e84533b8f0ace596cfe1c2','authority':'current_user_completion_instruction_and_independent_plan_review',
          'base_phase_starts':16,'additional_starts':1,'effective_phase_starts':17,'family_starts':50,'phase_seconds':1800,'family_seconds':4800,'disk_bytes':671088640,
          'retry_request_id':'creative_bff6f898fafe1db03aae_nuke_retry01','retry_operation_id':_CASE_NUKE_RETRY_OPERATION}
        if (set(revision)!=set(expected)|set(_CASE_NUKE_RETRY_PINS) or any(revision.get(k)!=v for k,v in expected.items())
                or any(not isinstance(revision.get(k),dict) or revision[k].get('sha256')!=v for k,v in _CASE_NUKE_RETRY_PINS.items())
                or phase.get('schema')!='bridge.official-case-creative-phase/1' or phase.get('task_id')!=expected['task_id'] or phase.get('starts')!=16 or phase.get('seconds')!=1800):raise ValueError('NATIVE_CASE_NUKE_RETRY_INVALID')
        original=json.loads(_reuse_record_bytes(revision['previous_scope']));envelope=json.loads(_reuse_record_bytes(revision['previous_state']))
        closure=json.loads(_reuse_record_bytes(revision['failed_attempt_closure']));_reuse_record_bytes(revision['performance']);_reuse_record_bytes(revision['review'])
        source=_parent_scope({k:revision['previous_scope'][k] for k in ('path','sha256')})
        with _accounting_lock(source.state_path):state=_copy(source._read())
        from . import owned_process
        tickets=state.get('tickets',[])
        if (Path(revision['previous_state']['path'])!=source.state_path or source._verify_envelope(envelope).get('state')!=state
                or len(tickets)!=49 or any(t.get('stopped_at') is None for t in tickets)
                or original.get('creative_phase')!=phase or original.get('case_nuke_retry_revision') is not None
                or original.get('budget')!=dict(self._budget,max_dcc_starts=49)
                or closure.get('schema')!='bridge.rectlight-nuke49-negative-closure/1' or closure.get('state')!='FAILED' or closure.get('stop_confirmed') is not True or closure.get('slot_released') is not True
                or closure.get('native_starts')!=49 or closure.get('native_starts_added')!=0 or closure.get('completed_native_render_claimed') is not False
                or closure.get('operation_id')!='nrend-8c28ece78d32bc97' or closure.get('scope')!=source.binding):raise ValueError('NATIVE_CASE_NUKE_RETRY_SOURCE_INVALID')
        last=tickets[-1];stop=owned_process.read_receipt(last['directory'],'stopped',identity=last['identity'])
        failed=json.loads(_reuse_record_bytes(closure['render_after']));slot=json.loads(_reuse_record_bytes(closure['after_slot']))
        _reuse_record_bytes(closure['render_before']);_reuse_record_bytes(closure['before_slot']);_reuse_record_bytes(closure['worker_result'])
        if (last.get('role')!='nuke-render' or last['identity'].get('operation_id')!=closure['operation_id']
                or closure['signed_stopped']['path']!=str(Path(last['directory'])/'stopped.json') or not stop or stop.get('stop_reason')!='TIME_BUDGET_EXCEEDED' or owned_process.execution_returncode(stop)!=2
                or failed.get('state')!='FAILED' or failed.get('task_id')!=closure['operation_id'] or failed.get('stop_confirmed_at') is None
                or slot.get('active')!=0 or slot.get('phase')!='RELEASED' or slot.get('operation_id')!=closure['operation_id']):raise ValueError('NATIVE_CASE_NUKE_RETRY_FAILED_STOP_REQUIRED')
        _reuse_record_bytes(closure['signed_stopped'])
        first=self.scope.get('continuation_of')==revision['previous_scope']
        if first:
            if (previous!=original or self.path!=source.root/'continuations/luna-rectlight-08/scope.json' or self.scope.get('accounting',{}).get('namespace')!='luna-rectlight-08'):raise ValueError('NATIVE_CASE_NUKE_RETRY_CHAIN_INVALID')
        elif (previous.get('creative_phase')!=phase or previous.get('case_nuke_retry_revision')!=record or previous.get('budget')!=dict(self._budget,max_dcc_starts=50)):
            raise ValueError('NATIVE_CASE_NUKE_RETRY_CHAIN_INVALID')
        return 1

    def effective_creative_starts(self):
        """运行上限与原生产phase身份分开：唯一获准重试使用17，其余仍原值。"""
        return getattr(self,'_creative_effective_starts',(self.scope.get('creative_phase') or {}).get('starts'))

    def _case_storage_limit(self,phase,previous):
        """只允许固定45票原件的一次512→640 MiB修订；后继沿用同一记录。"""
        record=self.scope.get('case_storage_revision')
        if record is None:
            if previous.get('case_storage_revision') is not None:
                raise ValueError('NATIVE_CASE_STORAGE_REVISION_CHAIN_INVALID')
            return 536870912
        revision=json.loads(_reuse_record_bytes(record))
        expected={'schema':'bridge.rectlight-storage-revision/1',
          'task_id':'7c65a89096e84533b8f0ace596cfe1c2',
          'authority':'current_user_completion_instruction_and_independent_plan_review',
          'from_bytes':536870912,'to_bytes':671088640}
        pins={'previous_scope':'759c16b13b818de3cd630539eb0577765f9afd30431941e485ca676eb763e40d',
          'previous_state':'98fcbcbb6bf9d4255dcf293f3d591d7080aaf571c102b59e4f3a0718d48f82ce',
          'inventory':'e53c128d8fb522cb2f87672f5bf7157906404e384f9f98a419bb6c780d1f198f',
          'review':'7562bfe5fc38d4b98ccec2afe29e6fc4774bdba8a96660273b738dbcec241bf7'}
        if (set(revision)!=set(expected)|set(pins) or any(revision.get(k)!=v for k,v in expected.items())
                or any(not isinstance(revision.get(k),dict) or revision[k].get('sha256')!=v for k,v in pins.items())
                or phase.get('schema')!='bridge.official-case-creative-phase/1'
                or phase.get('task_id')!=expected['task_id'] or phase.get('starts')!=16 or phase.get('seconds')!=1800):
            raise ValueError('NATIVE_CASE_STORAGE_REVISION_INVALID')
        original=json.loads(_reuse_record_bytes(revision['previous_scope']))
        envelope=json.loads(_reuse_record_bytes(revision['previous_state']))
        inventory=json.loads(_reuse_record_bytes(revision['inventory']));_reuse_record_bytes(revision['review'])
        source=_parent_scope({k:revision['previous_scope'][k] for k in ('path','sha256')})
        with _accounting_lock(source.state_path):state=_copy(source._read())
        if (Path(revision['previous_state']['path'])!=source.state_path
                or source._verify_envelope(envelope).get('state')!=state
                or len(state.get('tickets',[]))!=45 or any(t.get('stopped_at') is None for t in state['tickets'])
                or original.get('creative_phase')!=phase or original.get('case_storage_revision') is not None
                or original.get('output_root')!=self.scope.get('output_root')
                or original.get('budget',{}).get('max_disk_bytes')!=536870912
                or original['budget'].get('max_dcc_starts')!=49 or original['budget'].get('total_seconds')!=4800
                or inventory.get('schema')!='bridge.rectlight-storage-inventory/1'
                or inventory.get('previous_scope')!=revision['previous_scope'] or inventory.get('previous_state')!=revision['previous_state']
                or inventory.get('output_root')!=original['output_root'] or inventory.get('native_starts')!=45
                or inventory.get('new_native_starts')!=0 or inventory.get('measured_bytes')!=537738557
                or inventory.get('target_bytes')!=671088640 or inventory.get('estimated_peak_bytes')!=638401853
                or inventory.get('planned_additional_peak_bytes')!=100663296):
            raise ValueError('NATIVE_CASE_STORAGE_REVISION_SOURCE_INVALID')
        first=self.scope.get('continuation_of')==revision['previous_scope']
        if first:
            if (previous!=original or (self.scope.get('accounting') or {}).get('namespace')!='luna-rectlight-06'
                    or self.path!=source.root/'continuations/luna-rectlight-06/scope.json'):
                raise ValueError('NATIVE_CASE_STORAGE_REVISION_CHAIN_INVALID')
        elif (previous.get('creative_phase')!=phase or previous.get('case_storage_revision')!=record
                or previous.get('budget',{}).get('max_disk_bytes')!=671088640):
            raise ValueError('NATIVE_CASE_STORAGE_REVISION_CHAIN_INVALID')
        return 671088640

    def _case_start_limit(self,phase):
        """只承认本任务在38票失败停止后的一次14→16修订，时间上限不变。"""
        revision_record=self.scope.get('case_budget_revision')
        if type(phase) is not dict:raise ValueError('NATIVE_CASE_PHASE_INVALID')
        starts=phase.get('starts')
        if type(starts) is int and starts==14 and revision_record is None:return 14,False
        if type(starts) is not int or starts!=16 or revision_record is None:raise ValueError('NATIVE_CASE_PHASE_INVALID')
        revision=json.loads(_reuse_record_bytes(revision_record))
        expected={'schema':'bridge.rectlight-budget-revision/1','task_id':'7c65a89096e84533b8f0ace596cfe1c2',
          'authority':'current_user_completion_instruction_and_independent_plan_review','starts':16,'seconds':1800,
          'source_phase_sha256':'ced9fdd30547f5716661ba06c8eb45c74d900f007b129f4e835010b19b5924a2'}
        if (set(revision)!=set(expected)|{'previous_scope','previous_state','review'} or any(revision.get(k)!=v for k,v in expected.items())
                or phase.get('task_id')!=expected['task_id']
                or revision['previous_scope'].get('sha256')!='2154999ac7a329bd499ae5e8854f932d8f0eaf25065591cfea0587b06da0cc82'
                or revision['previous_state'].get('sha256')!='5132609c197c15e6ba93116ceea0da82e042e33a4b83312e11f889c44812ec5d'
                or revision['review'].get('sha256')!='77fdfb005e029823c291b1b2f9cc51b500ddc894df9283a6085231e08eff2923'):
            raise ValueError('NATIVE_CASE_BUDGET_REVISION_INVALID')
        original=json.loads(_reuse_record_bytes(revision['previous_scope']))
        state=json.loads(_reuse_record_bytes(revision['previous_state']))['payload']['state'];_reuse_record_bytes(revision['review'])
        canonical=dict(phase,starts=14)
        if (hashlib.sha256(self._canonical(canonical)).hexdigest()!=expected['source_phase_sha256'] or original.get('creative_phase')!=canonical
                or len(state.get('tickets',[]))!=38 or any(t.get('stopped_at') is None for t in state['tickets'])):
            raise ValueError('NATIVE_CASE_BUDGET_REVISION_SOURCE_INVALID')
        previous=json.loads(_reuse_record_bytes(self.scope['continuation_of']))
        mapped=self.scope['continuation_of']==revision['previous_scope'] and previous.get('creative_phase')==canonical
        if not mapped and (previous.get('creative_phase')!=phase or previous.get('case_budget_revision')!=revision_record):
            raise ValueError('NATIVE_CASE_BUDGET_REVISION_CHAIN_INVALID')
        return 16,mapped

    def _case_contract_correction_valid(self,phase,previous):
        """只承认同版封存菜单已证明的一次1→4纠错，预算、案例与来源不变。"""
        correction_record=self.scope.get('case_contract_correction')
        if correction_record is None:return False
        correction=json.loads(_reuse_record_bytes(correction_record))
        fields={'schema','prior_scope','old_contract','new_contract','menu_template','stopped','identity','parameter_differences'}
        if (set(correction)!=fields or correction['schema']!='bridge.rectlight-menu-correction/1'
                or correction['new_contract']!=phase['case_contract']):raise ValueError('NATIVE_CASE_CORRECTION_INVALID')
        original=json.loads(_reuse_record_bytes(correction['old_contract']));updated=json.loads(_reuse_record_bytes(correction['new_contract']))
        normalized=_copy(updated);tokens=normalized.pop('light_menu_tokens',None);template=normalized.pop('menu_template',None)
        if tokens!=['UsdLuxCylinderLight','UsdLuxDistantLight','UsdLuxDiskLight','point','UsdLuxRectLight','UsdLuxSphereLight'] or template!=correction['menu_template'] or normalized['transition_parameters']['lighttype']!=4:
            raise ValueError('NATIVE_CASE_CORRECTION_MENU_INVALID')
        normalized['transition_parameters']['lighttype']=1
        config=json.loads(_reuse_record_bytes(updated['base_configuration']))
        _reuse_record_bytes(correction['menu_template']);_reuse_record_bytes(correction['parameter_differences'])
        if normalized!=original or config['parameter_templates']!=correction['menu_template']:
            raise ValueError('NATIVE_CASE_CORRECTION_SOURCE_INVALID')
        prior_phase=dict(phase,case_contract=correction['old_contract'])
        if self.scope['continuation_of']==correction['prior_scope']:
            if previous.get('creative_phase')!=prior_phase:raise ValueError('NATIVE_CASE_CORRECTION_CHAIN_INVALID')
        elif previous.get('creative_phase')!=phase or previous.get('case_contract_correction')!=correction_record:
            raise ValueError('NATIVE_CASE_CORRECTION_CHAIN_INVALID')
        from . import owned_process
        _reuse_record_bytes(correction['stopped'])
        directory=Path(correction['stopped']['path']).parent
        stopped=owned_process.read_receipt(directory,'stopped',identity=correction['identity'])
        started=owned_process.read_receipt(directory,'started',identity=correction['identity'])
        if (not stopped or not started or owned_process.execution_returncode(stopped)!=1
                or correction['identity'].get('operation_id')!='rectlight-reference-observation'
                or (started.get('resource_budget') or {}).get('native_scope')!={k:correction['prior_scope'][k] for k in ('path','sha256')}):
            raise ValueError('NATIVE_CASE_CORRECTION_STOP_REQUIRED')
        return True

    def _prepare_continuation(self):
        """只读认证前驱及全部停止事实；新范围继承消耗，绝不改写前驱账本。"""
        record = self.scope.get('continuation_of')
        try:
            previous_value = json.loads(_reuse_record_bytes(record))
        except (TypeError, KeyError):
            raise ValueError('NATIVE_SCOPE_CONTINUATION_SOURCE_REQUIRED') from None
        if (previous_value.get('schema') != OFFICIAL_SCOPE_SCHEMA
                or previous_value.get('resource_profile') != OFFICIAL_INCREMENTAL_RESOURCE_PROFILE
                or previous_value.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE
                or previous_value.get('output_root') != str(self.root)
                or not isinstance(self.scope.get('scope_id'), str) or not self.scope['scope_id']
                or self.scope.get('scope_id') == previous_value.get('scope_id')
                or record['path'] == str(self.path)
                or previous_value.get('reused_inputs') != self.scope.get('reused_inputs')
                or previous_value.get('accounting', {}).get('key_path') == str(self.key_path)
                or previous_value.get('accounting', {}).get('key_sha256') == self.scope['accounting']['key_sha256']):
            raise ValueError('NATIVE_SCOPE_CONTINUATION_SOURCE_MISMATCH')
        previous = _parent_scope({name: record[name] for name in ('path', 'sha256')})
        with _accounting_lock(previous.state_path):
            state = previous._read()
        if any(ticket.get('stopped_at') is None for ticket in state['tickets']):
            raise ValueError('NATIVE_SCOPE_CONTINUATION_PRIOR_NOT_STOPPED')
        if self.scope.get('replacement_host_allowance') == 1:
            self._validate_replacement_host_allowance(state)
        elif previous.scope.get('replacement_host_allowance') is not None:
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_HOST_ALLOWANCE_MISMATCH')
        if self.scope.get('replacement_nuke_host_allowance') == 1:
            if previous.scope.get('replacement_nuke_host_allowance') != 1:
                self._validate_replacement_nuke_host_allowance(previous, state)
        elif previous.scope.get('replacement_nuke_host_allowance') is not None:
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_NUKE_HOST_ALLOWANCE_MISMATCH')
        self._continuation_previous = previous
        self._continuation_state = _copy(state)
        self._continuation_claim_path = _plain(self.root / '.native-control' / 'successors'
                                               / (record['sha256'] + '.json'))

    def _validate_replacement_host_allowance(self, previous_state):
        """只凭首次宿主的原签名启动超时与停止事实允许一次替换，不清零旧票据。"""
        from . import owned_process
        hosts = [ticket for ticket in previous_state['tickets'] if ticket['role'] == 'houdini-host']
        if not hosts:
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_HOST_PROOF_REQUIRED')
        ticket = hosts[0]
        directory = _plain(ticket['directory'])
        started = owned_process.read_receipt(directory, 'started', identity=ticket['identity'])
        stopped = self._stop(ticket)
        ready = owned_process.read_receipt(directory, 'runtime-ready', identity=ticket['identity'])
        if (not started or not stopped or ready is not None
                or started.get('writer_process_binding_error')
                   != 'ValueError:SUPERVISOR_WRITER_RUNTIME_READY_TIMEOUT'
                or stopped.get('stop_reason') != 'SUPERVISOR_WRITER_COLLECTION_FAILED'):
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_HOST_PROOF_REQUIRED')

    def _validate_replacement_nuke_host_allowance(self, previous, previous_state):
        """仅在已认证续范围的一个控制宿主正常停止且尚未渲染时补一次 Nuke 宿主票。"""
        from . import owned_process
        hosts = [ticket for ticket in previous_state['tickets'] if ticket['role'] == 'nuke-host']
        if (not previous.scope['accounting'].get('namespace') or len(hosts) != 1
                or any(ticket['role'] == 'nuke-render' for ticket in previous_state['tickets'])):
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_NUKE_HOST_PROOF_REQUIRED')
        stopped = self._stop(hosts[0])
        if (stopped is None or owned_process.execution_returncode(stopped) != 0
                or stopped.get('execution_result') != 'succeeded'):
            raise ValueError('NATIVE_SCOPE_REPLACEMENT_NUKE_HOST_PROOF_REQUIRED')

    def _continuation_claim_payload(self):
        """唯一后继声明只携带已绑定的前驱、当前范围和命名空间。"""
        return {'predecessor': _copy(self.scope['continuation_of']),
                'successor': _copy(self.binding),
                'namespace': self.scope['accounting']['namespace']}

    def _claim_continuation_successor(self):
        """在写新密钥前原子占用前驱；冲突或不完整声明均不得并列放行。"""
        path = self._continuation_claim_path
        if path is None:
            return
        _plain(path.parent)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        _plain(path.parent)
        try:
            descriptor = os.open(_plain(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except FileExistsError:
            raise ValueError('NATIVE_SCOPE_CONTINUATION_SUCCESSOR_ALREADY_CLAIMED') from None
        # 写入失败保留占位，后续只能查询处理，不能悄悄创建第二个分支。
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(self._canonical(self._continuation_claim_payload()))
            stream.flush()
            os.fsync(stream.fileno())

    def _validate_continuation_claim(self):
        """每次读账本都核对固定声明路径及内容；删除、替换或软链接均拒绝。"""
        raw = self._canonical(self._continuation_claim_payload())
        record = {'path': str(self._continuation_claim_path), 'bytes': len(raw),
                  'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            _reuse_record_bytes(record)
        except (OSError, ValueError):
            raise ValueError('NATIVE_SCOPE_CONTINUATION_SUCCESSOR_CLAIM_INVALID') from None

    def _validate_continuation_state(self, state):
        """每次读取都核对继承前缀和前驱签名事实，防止续范围重置启动或时间消耗。"""
        previous = self._continuation_previous
        if previous is None:
            return
        self._validate_continuation_claim()
        with _accounting_lock(previous.state_path):
            expected = previous._read()
        if expected != self._continuation_state:
            raise ValueError('NATIVE_SCOPE_CONTINUATION_SOURCE_CHANGED')
        if self.scope.get('replacement_host_allowance') == 1:
            self._validate_replacement_host_allowance(expected)
        if (self.scope.get('replacement_nuke_host_allowance') == 1
                and previous.scope.get('replacement_nuke_host_allowance') != 1):
            self._validate_replacement_nuke_host_allowance(previous, expected)
        inherited = expected['tickets']
        if (state.get('continuation_of') != self.scope['continuation_of']
                or state.get('prior_closed_reason') != expected['closed_reason']
                or state['tickets'][:len(inherited)] != inherited):
            raise ValueError('NATIVE_SCOPE_CONTINUATION_ACCOUNTING_MISMATCH')

    @property
    def resource_profile(self):
        return self._resource_profile

    def role_seconds(self, role):
        if type(role) is not str or role not in self._role_seconds:
            raise ValueError('NATIVE_SCOPE_ROLE_INVALID')
        return self._role_seconds[role]

    @classmethod
    def initialize(cls, binding, *, key):
        """Prepare accounting exactly once, before any native operation is admitted."""
        scope = cls.__new__(cls)
        scope._setup(binding)
        if (not isinstance(key, bytes) or len(key) != 32
                or hashlib.sha256(key).hexdigest() != scope.scope['accounting']['key_sha256']):
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_KEY_INVALID')
        with _accounting_lock(scope.state_path):
            protected = (scope.key_path, scope.state_path, scope.journal_path, scope.anchor_path)
            if any(path.exists() or path.is_symlink() for path in protected):
                raise ValueError('NATIVE_SCOPE_ALREADY_INITIALIZED_OR_INCOMPLETE')
            scope._claim_continuation_successor()
            scope.key_path.parent.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(scope.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(key); stream.flush(); os.fsync(stream.fileno())
            state = {'schema': 'bridge.native-scope-state/1', 'scope_sha256': binding['sha256'],
                     'tickets': [], 'closed_reason': None}
            if scope._continuation_state is not None:
                # 当前用户授权新范围继续；旧失败原因单独保留，所有已花票据和时间完整继承。
                state.update(tickets=_copy(scope._continuation_state['tickets']),
                    continuation_of=_copy(scope.scope['continuation_of']),
                    prior_closed_reason=scope._continuation_state['closed_reason'])
            scope._commit(state, sequence=0, previous=None)
        return cls(binding)

    @staticmethod
    def _canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')

    def _key(self):
        try:
            path = _plain(self.key_path)
            metadata = path.stat()
            key = path.read_bytes()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                    or len(key) != 32 or hashlib.sha256(key).hexdigest()
                    != self.scope['accounting']['key_sha256']):
                raise ValueError('NATIVE_SCOPE_ACCOUNTING_KEY_INVALID')
            return key
        except OSError as exc:
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_MISSING') from exc

    def _envelope(self, payload):
        return {'payload': payload, 'signature': hmac.new(self._key(), self._canonical(payload),
                                                        hashlib.sha256).hexdigest()}

    def _verify_envelope(self, value):
        if (not isinstance(value, dict) or set(value) != {'payload', 'signature'}
                or not hmac.compare_digest(str(value['signature']),
                    hmac.new(self._key(), self._canonical(value['payload']), hashlib.sha256).hexdigest())):
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_SIGNATURE_INVALID')
        return value['payload']

    def _load_accounted(self):
        try:
            for path in (self.state_path, self.journal_path, self.anchor_path):
                _plain(path)
                if not path.is_file() or path.stat().st_size > 8*1024*1024:
                    raise ValueError('NATIVE_SCOPE_ACCOUNTING_MISSING')
            lines = self.journal_path.read_bytes().splitlines()
            previous = None
            if not lines:
                raise ValueError('NATIVE_SCOPE_ACCOUNTING_MISSING')
            for sequence, line in enumerate(lines):
                record = json.loads(line)
                payload = self._verify_envelope(record)
                if (type(payload.get('seq')) is not int or payload['seq'] != sequence
                        or payload.get('previous') != previous):
                    raise ValueError('NATIVE_SCOPE_ACCOUNTING_ROLLBACK')
                previous = hashlib.sha256(self._canonical(record)).hexdigest()
            anchor = self._verify_envelope(json.loads(self.anchor_path.read_bytes()))
            state_record = json.loads(self.state_path.read_bytes())
            self._verify_envelope(state_record)
            if (anchor != {'seq': sequence, 'head': previous} or state_record != record):
                raise ValueError('NATIVE_SCOPE_ACCOUNTING_ROLLBACK')
            return payload['state'], sequence, previous
        except (OSError, KeyError, TypeError, OverflowError) as exc:
            raise ValueError('NATIVE_SCOPE_ACCOUNTING_INVALID') from exc

    def _commit(self, state, *, sequence, previous):
        envelope = self._envelope({'seq': sequence, 'previous': previous, 'state': state})
        data = self._canonical(envelope)
        descriptor = os.open(_plain(self.journal_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT
                             | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(descriptor, 'ab') as stream:
            stream.write(data + b'\n'); stream.flush(); os.fsync(stream.fileno())
        anchor = self._envelope({'seq': sequence, 'head': hashlib.sha256(data).hexdigest()})
        atomic_write(self.anchor_path, self._canonical(anchor), owned_root=self.root)
        atomic_write(self.state_path, data, owned_root=self.root)

    def _read(self):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.binding['sha256']:
            raise ValueError('NATIVE_SCOPE_CHANGED')
        state, _, _ = self._load_accounted()
        if self.resource_profile == GEOMETRY_RESOURCE_PROFILE:
            # 动态预算每次从原合同重置后重验，不能从setup缓存继承旧加成。
            self._budget,self._roles=_copy(GEOMETRY_BUDGET),_copy(GEOMETRY_ROLES)
            from .geometry_budget_addendum import effective_limits
            limits=effective_limits(self,state)
            if limits is not None:self._budget,self._roles=limits
            from .geometry_nuke_recovery import effective_limits as nuke_limits
            limits=nuke_limits(self,state)
            if limits is not None:self._budget,self._roles=limits
            from .geometry_nuke_save_recovery import effective_limits as save_limits
            limits=save_limits(self,state)
            if limits is not None:self._budget,self._roles=limits
            from .geometry_seed_cold_recovery import verify_state as cold_state
            cold_state(self,state)
        elif self.resource_profile == 'h21_geometry_feedback_5_900_v1':
            if set(state) != {'schema', 'scope_sha256', 'tickets', 'closed_reason'}:
                raise ValueError('NATIVE_SCOPE_STATE_INVALID')
        if (state.get('schema') != 'bridge.native-scope-state/1'
                or state.get('scope_sha256') != self.binding['sha256']
                or not isinstance(state.get('tickets'), list)):
            raise ValueError('NATIVE_SCOPE_STATE_INVALID')
        self._validate_continuation_state(state)
        try:
            identifiers = set()
            for ticket in state['tickets']:
                if (not isinstance(ticket, dict) or not isinstance(ticket['id'], str)
                        or ticket['id'] in identifiers or ticket['role'] not in self._roles
                        or type(ticket['heavy']) is not bool
                        or ticket['heavy'] != (ticket['role'] not in ('houdini-host', 'nuke-host'))
                        or not isinstance(ticket['identity'], dict) or not ticket['identity']
                        or not _plain(ticket['directory']).is_relative_to(self.root)):
                    raise ValueError('NATIVE_SCOPE_STATE_INVALID')
                identifiers.add(ticket['id'])
                for field in ('admitted_at', 'charged_seconds'):
                    value = ticket[field]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError('NATIVE_SCOPE_STATE_INVALID')
                stopped = ticket['stopped_at']
                if stopped is not None and (type(stopped) not in (int, float)
                        or not math.isfinite(stopped) or stopped < ticket['admitted_at']):
                    raise ValueError('NATIVE_SCOPE_STATE_INVALID')
            if len(state['tickets']) > self._budget['max_dcc_starts']:
                raise ValueError('NATIVE_SCOPE_STATE_INVALID')
            for role, limit in self._roles.items():
                if sum(t['role'] == role for t in state['tickets']) > limit:
                    raise ValueError('NATIVE_SCOPE_STATE_INVALID')
            if (self.resource_profile == OFFICIAL_RESOURCE_PROFILE
                    and self.scope.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE):
                for index, ticket in enumerate(state['tickets']):
                    prefix=OFFICIAL_IDENTITY_ROLES if self.scope.get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE else _OFFICIAL_PREFIX
                    if ((index < 3 and ticket['role'] != prefix[index])
                            or (index >= 3 and ticket['role'] in prefix)):
                        raise ValueError('NATIVE_SCOPE_STATE_INVALID')
                    if index <= 3 and any(previous['stopped_at'] is None
                                          for previous in state['tickets'][:index]):
                        raise ValueError('NATIVE_SCOPE_STATE_INVALID')
            if self.resource_profile == HIP_RESOURCE_PROFILE:
                for index, ticket in enumerate(state['tickets']):
                    if ticket['role'] == 'houdini-host' and (index != 1
                            or state['tickets'][0]['role'] != 'graph-worker'
                            or state['tickets'][0]['stopped_at'] is None):
                        raise ValueError('NATIVE_SCOPE_STATE_INVALID')
            for ticket in state['tickets']:
                if ticket['role'] == 'main-husk':
                    parents = [t for t in state['tickets'] if t['id'] == ticket['parent']]
                    if (len(parents) != 1 or parents[0]['role'] != 'houdini-host'
                            or parents[0]['directory'] != ticket['directory']
                            or parents[0]['identity'] != ticket['identity']):
                        raise ValueError('NATIVE_SCOPE_STATE_INVALID')
                elif ticket['parent'] is not None:
                    raise ValueError('NATIVE_SCOPE_STATE_INVALID')
            for ticket in state['tickets']:
                if ticket['stopped_at'] is not None:
                    source = ticket if ticket['parent'] is None else next(
                        t for t in state['tickets'] if t['id'] == ticket['parent'])
                    stopped = self._stop(source)
                    if (stopped is None or stopped.get('observed_at') != ticket['stopped_at']
                            or hashlib.sha256(self._canonical(stopped)).hexdigest()
                            != ticket.get('stopped_sha256')):
                        raise ValueError('NATIVE_SCOPE_STOP_INVALID')
            if state.get('closed_reason') is not None and (not isinstance(state['closed_reason'], str)
                    or not state['closed_reason']):
                raise ValueError('NATIVE_SCOPE_STATE_INVALID')
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError('NATIVE_SCOPE_STATE_INVALID') from exc
        if ('geometry_recovery_authorization' in state
                or self.resource_profile == GEOMETRY_RESOURCE_PROFILE):
            from .geometry_recovery import verify_state
            verify_state(self,state)
        return state

    def authorize_geometry_recovery(self, permit_record):
        """仅追加一次已认证恢复；原关闭历史、三张票和费用保持原样。"""
        from .geometry_recovery import authorized_state
        with _accounting_lock(self.state_path):
            state=self._read()
            updated=authorized_state(self,state,permit_record)
            self._save(updated)
            return _copy(updated)

    def authorize_geometry_recovery_successor(self, permit_record):
        """只追加最后一次独立许可，首许可、四张停止票据和累计费用保持。"""
        from .geometry_recovery_successor import authorized_state
        with _accounting_lock(self.state_path):
            state=self._read()
            updated=authorized_state(self,state,permit_record)
            self._save(updated)
            return _copy(updated)

    def authorize_geometry_budget_addendum(self, permit_record):
        """只追加用户明确同意的一次宿主预算加成，原scope与六票收费不改。"""
        from .geometry_budget_addendum import authorized_state
        with _accounting_lock(self.state_path):
            state=self._read()
            updated=authorized_state(self,state,permit_record)
            self._save(updated)
            return _copy(updated)

    def authorize_geometry_nuke_recovery(self, permit_record):
        """按本轮真人答复只续接首次Nuke导入失败；十票和旧许可不改。"""
        from .geometry_nuke_recovery import authorized_state
        with _accounting_lock(self.state_path):
            state=self._read()
            updated=authorized_state(self,state,permit_record)
            self._save(updated)
            return _copy(updated)

    def authorize_geometry_nuke_save_recovery(self, permit_record):
        """只按新增17/NH3的明确授权恢复指定NH15失败，原十五票与收费保持。"""
        from .geometry_nuke_save_recovery import authorized_state
        with _accounting_lock(self.state_path):
            state=self._read();updated=authorized_state(self,state,permit_record);self._save(updated)
            return _copy(updated)

    def authorize_geometry_seed_cold_recovery(self, permit_record):
        """仅清除精确closed16以执行原17上限内最后一票NR，票据和费用不变。"""
        from .geometry_seed_cold_recovery import authorized_state
        with _accounting_lock(self.state_path):
            state=self._read();updated=authorized_state(self,state,permit_record);self._save(updated)
            return _copy(updated)

    def collector_policy(self):
        """有效恢复许可提供已封存采样策略；其它范围保持原静态选择。"""
        from .process_image import scope_collector_policy
        with _accounting_lock(self.state_path):
            state=self._read()
            if 'geometry_recovery_authorization' in state:
                from .geometry_recovery import collector_policy
                return collector_policy(self,state)
        return scope_collector_policy(self.scope)

    @staticmethod
    def _stop(source):
        from . import owned_process
        directory = _plain(source['directory'])
        stopped = owned_process.read_receipt(directory, 'stopped', identity=source['identity'])
        if stopped is None:
            return None
        start = owned_process.read_receipt(directory, 'started', identity=source['identity'])
        if (not start or stopped.get('observed_by') != 'owned_child_wait'
                or stopped.get('pid') != start.get('pid')
                or stopped.get('started_sha256') != hashlib.sha256(owned_process._canonical(start)).hexdigest()
                or type(start.get('execution_protocol')) is not int or start['execution_protocol'] != 1
                or type(stopped.get('execution_protocol')) is not int or stopped['execution_protocol'] != 1):
            raise ValueError('NATIVE_SCOPE_STOP_INVALID')
        observed = stopped.get('observed_at')
        if type(observed) not in (int, float) or not math.isfinite(observed):
            raise ValueError('NATIVE_SCOPE_STOP_TIME_INVALID')
        return stopped

    def _save(self, state):
        _, sequence, previous = self._load_accounted()
        self._commit(state, sequence=sequence + 1, previous=previous)

    def validate_host(self, kind, version, executable, supervisor, project_color=None,
                      writer=None, allow_missing_writer=False):
        if kind not in ('houdini', 'nuke') or version != self.scope.get('versions', {}).get(kind):
            raise ValueError('PRODUCTION_NATIVE_SCOPE_VERSION_MISMATCH')
        if project_color is not None and (not project_color or project_color != self.scope.get('project_color')):
            raise ValueError('PRODUCTION_NATIVE_SCOPE_PROJECT_COLOR_MISMATCH')
        files = self.scope.get('hosts') or {}
        selected = [('hython' if kind == 'houdini' else 'nuke', executable), ('supervisor_python', supervisor)]
        if kind == 'houdini':
            if writer is None and not allow_missing_writer:
                raise ValueError('PRODUCTION_NATIVE_SCOPE_WRITER_REQUIRED')
            if writer is not None:
                if not isinstance(writer, dict):
                    raise ValueError('PRODUCTION_NATIVE_SCOPE_EXECUTABLE_MISMATCH:husk')
                image = writer.get('image', writer)
                if not isinstance(image, dict) or image.get('sha256') != (files.get('husk') or {}).get('sha256'):
                    raise ValueError('PRODUCTION_NATIVE_SCOPE_EXECUTABLE_MISMATCH:husk')
                selected.append(('husk', image.get('path')))
        for name, raw in selected:
            try:
                actual = _plain(raw)
                expected = files.get(name) or {}
                size = actual.stat().st_size
                if (str(actual) != expected.get('path') or size != expected.get('bytes')
                        or not actual.is_file() or not 0 < size <= 512*1024*1024):
                    raise ValueError('PRODUCTION_NATIVE_SCOPE_EXECUTABLE_MISMATCH:' + name)
                digest = hashlib.sha256()
                with actual.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024*1024), b''):
                        digest.update(block)
                if digest.hexdigest() != expected.get('sha256'):
                    raise ValueError('PRODUCTION_NATIVE_SCOPE_EXECUTABLE_MISMATCH:' + name)
            except (OSError, TypeError) as exc:
                raise ValueError('PRODUCTION_NATIVE_SCOPE_EXECUTABLE_MISMATCH:' + name) from exc
        return self

    def _disk_usage(self):
        from . import owned_process
        # Writers do not share the accounting lock; observe disk outside the
        # transaction so recursive traversal cannot block another accountant.
        return owned_process._disk_usage({'roots': [str(self.root)], 'max_bytes': self._budget['max_disk_bytes']})

    def _refresh(self, state, *, disk_bytes, reconcile=True, persist=True):
        from . import owned_process
        before = _copy(state)
        now = time.time()
        for ticket in state['tickets']:
            if ticket.get('stopped_at') is not None or not reconcile:
                continue
            source = ticket
            if ticket['parent'] is not None:
                source = next(t for t in state['tickets'] if t['id'] == ticket['parent'])
            try:
                stopped = self._stop(source)
                if stopped is not None:
                    observed = stopped.get('observed_at')
                    if (type(observed) not in (int, float) or observed < ticket['admitted_at']
                            or observed > now + 1):
                        raise ValueError('NATIVE_SCOPE_STOP_TIME_INVALID')
                    ticket['stopped_sha256'] = hashlib.sha256(self._canonical(stopped)).hexdigest()
                    ticket['stopped_at'] = observed
                    ticket['charged_seconds'] = max(ticket['charged_seconds'], observed - ticket['admitted_at'])
                    if owned_process.execution_returncode(stopped) != 0:
                        state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_EXECUTION_FAILED'
            except (ValueError, OSError, KeyError, TypeError):
                state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_STOP_INVALID'
        if self.scope.get('feedback_phase') is not None and self._continuation_previous is not None:
            inherited = self._feedback_base_state['tickets']
            added = state['tickets'][len(inherited):]
            charges_new = sum(max(t['charged_seconds'], now-t['admitted_at'], 0) if t.get('stopped_at') is None else t['charged_seconds'] for t in added)
            if len(added)>self._feedback_start_limit or charges_new>600:
                state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_FEEDBACK_EXHAUSTED'
        if self.scope.get('recovery_phase') is not None:
            added = state['tickets'][len(self._recovery_base_state['tickets']):]
            elapsed_new = sum(max(t['charged_seconds'], now - t['admitted_at'], 0)
                              if t.get('stopped_at') is None else t['charged_seconds'] for t in added)
            if len(added) > 6 or elapsed_new > 600:
                state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_RECOVERY_EXHAUSTED'
        if self.scope.get('creative_phase') is not None:
            added = state['tickets'][len(self._creative_base_state['tickets']):]
            spent = sum(max(t['charged_seconds'], now - t['admitted_at'], 0)
                        if t.get('stopped_at') is None else t['charged_seconds'] for t in added)
            if len(added) > self.effective_creative_starts() or spent > self.scope['creative_phase']['seconds']:
                state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_CREATIVE_EXHAUSTED'
        used = disk_bytes
        charges = [max(ticket['charged_seconds'], now - ticket['admitted_at'], 0)
                      if ticket.get('stopped_at') is None else ticket['charged_seconds']
                      for ticket in state['tickets']]
        elapsed = sum(charges)
        if any(now < ticket['admitted_at'] for ticket in state['tickets']):
            state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_CLOCK_INVALID'
        if (elapsed > self._budget['total_seconds']
                or (self.resource_profile is not None and any(
                    charge > self.role_seconds(ticket['role'])
                    for ticket, charge in zip(state['tickets'], charges)))):
            state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_TIME_EXHAUSTED'
        if used > self._budget['max_disk_bytes']:
            state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_DISK_EXHAUSTED'
        if persist and state != before:
            self._save(state)
        result={'dcc_starts': len(state['tickets']), 'total_seconds': elapsed,
                'disk_bytes': used, 'closed_reason': state['closed_reason']}
        if self.scope.get('case_nuke_retry_revision') is not None:result['effective_creative_starts']=self.effective_creative_starts()
        return result

    def snapshot(self):
        """Read budget usage with verified stop observations, without persisting changes."""
        disk_bytes = self._disk_usage()
        with _accounting_lock(self.state_path):
            state = self._read()
            result = self._refresh(state, disk_bytes=disk_bytes, reconcile=True, persist=False)
            return dict(result, scope_sha256=self.binding['sha256'], tickets=_copy(state['tickets']))

    def completed_snapshot(self):
        """只读验签已停止范围的原记账事实；此视图不能授权新执行。"""
        with _accounting_lock(self.state_path):
            state = self._read()
            tickets = state['tickets']
            if any(ticket['stopped_at'] is None for ticket in tickets):
                raise ValueError('NATIVE_SCOPE_COMPLETED_STOP_REQUIRED')
            now = time.time()
            if any(ticket['admitted_at'] > now or ticket['stopped_at'] > now + 1
                   for ticket in tickets):
                raise ValueError('NATIVE_SCOPE_COMPLETED_CLOCK_INVALID')
            charges = [max(ticket['charged_seconds'], ticket['stopped_at'] - ticket['admitted_at'])
                       for ticket in tickets]
            if (sum(charges) > self._budget['total_seconds']
                    or any(charge > self.role_seconds(ticket['role'])
                           for ticket, charge in zip(tickets, charges))):
                raise ValueError('NATIVE_SCOPE_COMPLETED_TIME_EXCEEDED')
            # 阶段额度沿用原执行门；仅以已验签停止收费计算，不刷新任何历史记录。
            phases = []
            if self.scope.get('feedback_phase') is not None and self._continuation_previous is not None:
                phases.append((self._feedback_base_state, self._feedback_start_limit, 600))
            if self.scope.get('recovery_phase') is not None:
                phases.append((self._recovery_base_state, 6, 600))
            if self.scope.get('creative_phase') is not None:
                phases.append((self._creative_base_state, self.effective_creative_starts(),
                               self.scope['creative_phase']['seconds']))
            for base, start_limit, seconds_limit in phases:
                inherited = base['tickets']
                if tickets[:len(inherited)] != inherited:
                    raise ValueError('NATIVE_SCOPE_COMPLETED_PHASE_PREFIX_INVALID')
                if len(tickets) - len(inherited) > start_limit or sum(charges[len(inherited):]) > seconds_limit:
                    raise ValueError('NATIVE_SCOPE_COMPLETED_PHASE_EXCEEDED')
            # 不扫描当前目录或刷新关闭状态，保留生产时已签名的预算与停止事实。
            return {'dcc_starts': len(tickets), 'total_seconds': sum(charges),
                    'closed_reason': state['closed_reason'],
                    'scope_sha256': self.binding['sha256'], 'tickets': _copy(tickets)}

    def fail(self, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('NATIVE_SCOPE_FAILURE_INVALID')
        with _accounting_lock(self.state_path):
            state = self._read()
            state['closed_reason'] = state['closed_reason'] or reason
            self._save(state)
        return state['closed_reason']

    def check(self):
        disk_bytes = self._disk_usage()
        with _accounting_lock(self.state_path):
            state = self._read()
            result = self._refresh(state, disk_bytes=disk_bytes)
            if result['closed_reason']:
                raise ValueError(result['closed_reason'])
            return result

    def remaining_seconds(self, ticket=None):
        """Derive remaining time from admission and verified stops in the journal."""
        disk_bytes = self._disk_usage()
        with _accounting_lock(self.state_path):
            state = self._read()
            result = self._refresh(state, disk_bytes=disk_bytes)
            if result['closed_reason']:
                raise ValueError(result['closed_reason'])
            remaining = max(0, self._budget['total_seconds'] - result['total_seconds'])
            if self.scope.get('feedback_phase') is not None:
                spent = sum(t['charged_seconds'] for t in self._feedback_base_state['tickets'])
                remaining = min(remaining, max(0, 600 - (result['total_seconds'] - spent)))
            if self.scope.get('recovery_phase') is not None:
                spent = sum(t['charged_seconds'] for t in self._recovery_base_state['tickets'])
                remaining = min(remaining, max(0, 600 - (result['total_seconds'] - spent)))
            if self.scope.get('creative_phase') is not None:
                spent = sum(t['charged_seconds'] for t in self._creative_base_state['tickets'])
                remaining = min(remaining, max(0, self.scope['creative_phase']['seconds'] - (result['total_seconds'] - spent)))
            if ticket is None:
                return remaining
            current = self._select_ticket(state, ticket)
            if current['stopped_at'] is not None:
                return 0.0
            charged = max(current['charged_seconds'], time.time() - current['admitted_at'], 0)
            return max(0, min(remaining, self.role_seconds(current['role']) - charged))

    @staticmethod
    def _select_ticket(state, ticket):
        ticket_id = ticket.get('id') if isinstance(ticket, dict) else ticket
        selected = [value for value in state['tickets'] if value['id'] == ticket_id]
        if len(selected) != 1:
            raise ValueError('NATIVE_SCOPE_TICKET_UNKNOWN')
        current = selected[0]
        if isinstance(ticket, dict) and any(
                field in ticket and ticket[field] != current[field]
                for field in ('role', 'directory', 'identity', 'heavy', 'parent', 'admitted_at')):
            raise ValueError('NATIVE_SCOPE_IDENTITY_CONFLICT')
        return current


    def _check_case_nuke_retry_admission(self,state,role,directory,identity,parent_id):
        """额度50只供固定独立Nuke操作使用；纯校验不分配或写入票据。"""
        if self.scope.get('case_nuke_retry_revision') is None or len(state['tickets'])<49:return
        expected=self.root/'state/nuke_renders'/(_CASE_NUKE_RETRY_OPERATION+'.supervisor')
        if (len(state['tickets'])!=49 or role!='nuke-render' or directory!=expected or parent_id is not None
                or identity.get('task_id')!=_CASE_NUKE_RETRY_OPERATION or identity.get('operation_id')!=_CASE_NUKE_RETRY_OPERATION):
            raise ValueError('NATIVE_CASE_NUKE_RETRY_ONLY_ADMISSION')

    def admit(self, role, directory, identity, heavy=True, parent=None):
        if (self.scope.get('execution_authorized') is not True
                or self.scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
            raise ValueError('NATIVE_SCOPE_EXECUTION_NOT_AUTHORIZED')
        directory = _plain(directory)
        if self.scope.get('recovery_phase') is not None and role not in ('nuke-host', 'nuke-render'):
            raise ValueError('NATIVE_SCOPE_RECOVERY_ROLE_FORBIDDEN')
        allowed_creative=('houdini-host','main-husk','nuke-render')
        if self.scope.get('creative_phase',{}).get('schema')=='bridge.official-case-creative-phase/1':allowed_creative+=('official-case-husk',)
        if self.scope.get('creative_phase') is not None and role not in allowed_creative:
            raise ValueError('NATIVE_SCOPE_CREATIVE_ROLE_FORBIDDEN')
        if (type(role) is not str or role not in self._roles or type(heavy) is not bool or not isinstance(identity, dict)
                or not identity or not directory.is_relative_to(self.root)
                or heavy != (role not in ('houdini-host', 'nuke-host'))):
            raise ValueError('NATIVE_SCOPE_ADMISSION_INVALID')
        identity = _copy(identity)
        parent_id = parent.get('id') if isinstance(parent, dict) else parent
        disk_bytes = self._disk_usage()
        with _accounting_lock(self.state_path):
            state = self._read()
            if 'geometry_seed_cold_recovery' in state and role!='nuke-render':
                raise ValueError('NATIVE_SCOPE_SEED_COLD_NR_ONLY')
            result = self._refresh(state, disk_bytes=disk_bytes)
            if result['closed_reason']:
                raise ValueError(result['closed_reason'])
            if role == 'main-husk':
                parents = [t for t in state['tickets'] if t['id'] == parent_id]
                if (len(parents) != 1 or parents[0]['role'] != 'houdini-host'
                        or parents[0].get('stopped_at') is not None
                        or parents[0]['directory'] != str(directory)
                        or parents[0]['identity'] != identity):
                    raise ValueError('NATIVE_SCOPE_PARENT_INVALID')
            elif parent_id is not None:
                raise ValueError('NATIVE_SCOPE_PARENT_INVALID')
            for ticket in state['tickets']:
                if (ticket['role'] == role and ticket['directory'] == str(directory)
                        and ticket['identity'] == identity):
                    if ticket['heavy'] != heavy or ticket['parent'] != parent_id:
                        raise ValueError('NATIVE_SCOPE_IDENTITY_CONFLICT')
                    return dict(_copy(ticket), reused=True)
                if ((ticket['directory'] == str(directory) or ticket['identity'] == identity)
                        and not (role == 'main-husk' and ticket['id'] == parent_id)):
                    raise ValueError('NATIVE_SCOPE_IDENTITY_CONFLICT')
            self._check_case_nuke_retry_admission(state,role,directory,identity,parent_id)
            if result['total_seconds'] >= self._budget['total_seconds']:
                raise ValueError('NATIVE_SCOPE_TIME_EXHAUSTED')
            if (self.resource_profile == OFFICIAL_RESOURCE_PROFILE
                    and self.scope.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE):
                position = len(state['tickets'])
                prefix=OFFICIAL_IDENTITY_ROLES if self.scope.get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE else _OFFICIAL_PREFIX
                expected = prefix[position] if position < 3 else None
                if ((expected is not None and role != expected)
                        or (position >= 3 and role in prefix)):
                    raise ValueError('NATIVE_SCOPE_OFFICIAL_ORDER_REQUIRED')
                if position < 3 and any(t.get('stopped_at') is None for t in state['tickets']):
                    raise ValueError('NATIVE_SCOPE_OFFICIAL_PRIOR_STOP_REQUIRED')
                if position == 3 and any(t.get('stopped_at') is None for t in state['tickets']):
                    raise ValueError('NATIVE_SCOPE_OFFICIAL_PRIOR_STOP_REQUIRED')
            if role != 'main-husk' and directory.exists():
                raise ValueError('NATIVE_SCOPE_DIRECTORY_NOT_FRESH')
            if (len(state['tickets']) >= self._budget['max_dcc_starts']
                    or sum(t['role'] == role for t in state['tickets']) >= self._roles[role]):
                raise ValueError('NATIVE_SCOPE_STARTS_EXHAUSTED')
            if self.resource_profile == HIP_RESOURCE_PROFILE:
                graph = [t for t in state['tickets'] if t['role'] == 'graph-worker']
                if role == 'houdini-host' and (len(graph) != 1 or graph[0]['stopped_at'] is None):
                    raise ValueError('NATIVE_SCOPE_GRAPH_STOP_REQUIRED')
                if any(t['stopped_at'] is None for t in state['tickets']):
                    raise ValueError('NATIVE_SCOPE_HEAVY_BUSY')
            if heavy and any(t['heavy'] and t.get('stopped_at') is None for t in state['tickets']):
                raise ValueError('NATIVE_SCOPE_HEAVY_BUSY')
            ticket = {'id': uuid.uuid4().hex, 'role': role, 'directory': str(directory),
                      'identity': identity, 'heavy': heavy, 'parent': parent_id,
                      'admitted_at': time.time(), 'charged_seconds': 0.0, 'stopped_at': None}
            state['tickets'].append(ticket)
            self._save(state)
            return dict(_copy(ticket), reused=False)

    def finish(self, ticket):
        disk_bytes = self._disk_usage()
        with _accounting_lock(self.state_path):
            state = self._read()
            current = self._select_ticket(state, ticket)
            source = current
            if current['parent'] is not None:
                source = next(t for t in state['tickets'] if t['id'] == current['parent'])
            from . import owned_process
            stopped = self._stop(source)
            if stopped is None:
                self._refresh(state, disk_bytes=disk_bytes)
                raise ValueError('NATIVE_SCOPE_STOP_UNKNOWN')
            observed = stopped.get('observed_at')
            if (type(observed) not in (int, float) or observed < current['admitted_at']
                    or observed > time.time() + 1):
                raise ValueError('NATIVE_SCOPE_STOP_TIME_INVALID')
            # A parent owns the complete process tree, including its admitted husk.
            targets = [current] + [t for t in state['tickets'] if t['parent'] == current['id']]
            for child in targets:
                child['stopped_sha256'] = hashlib.sha256(self._canonical(stopped)).hexdigest()
                child['stopped_at'] = observed
                child['charged_seconds'] = max(child['charged_seconds'], observed - child['admitted_at'])
            current['stopped_at'] = observed
            current['charged_seconds'] = max(current['charged_seconds'], observed - current['admitted_at'])
            current['stopped_sha256'] = hashlib.sha256(json.dumps(stopped, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            if owned_process.execution_returncode(stopped) != 0:
                state['closed_reason'] = state['closed_reason'] or 'NATIVE_SCOPE_EXECUTION_FAILED'
            self._save(state)
            result = self._refresh(state, disk_bytes=disk_bytes)
            if result['closed_reason']:
                raise ValueError(result['closed_reason'])
            return _copy(current)
