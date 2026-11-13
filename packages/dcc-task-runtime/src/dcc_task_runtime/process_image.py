"""Bounded macOS process-image observations, independent of process_identity.

Expected executable identities must originate at the trusted controller. A proof
is unsigned evidence: validate_process_proof checks its offline consistency only;
callers must authenticate the original capture (for example in a producer HMAC).
No boolean/``verified`` field supplied by a caller can authorize a process.

freeze_executable, observe_process and capture_ancestry accept read_budget=None.
If supplied, its reserve(n) is called before each image hash read for the maximum
requested bytes, including EOF probes. Capture shares it across both full chains.
Budget rejection propagates; already reserved bytes are never refunded here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import threading

EXECUTABLE_SCHEMA = 'bridge.process-image.executable/1'
OBSERVATION_SCHEMA = 'bridge.process-image.observation/1'
PROOF_SCHEMA = 'bridge.process-image.proof/1'
MAX_IMAGE_BYTES = 512 * 1024 * 1024
MAX_STDOUT_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_DIAGNOSTIC_STDERR_BYTES = 4096
MAX_DIAGNOSTIC_ARGV_BYTES = 1024
MAX_ANCESTRY_DEPTH = 8  # Includes the current process and the strict ancestor.
TOOL_TIMEOUT_SECONDS = 5.0
SAMPLE_HEADER_TOOL_TIMEOUT_SECONDS = 8.0
FREEZE_TIMEOUT_SECONDS = 5.0
OBSERVE_TIMEOUT_SECONDS = 16.0
CAPTURE_TIMEOUT_SECONDS = 60.0
_STAT_KEYS = {'device', 'inode', 'size', 'mtime_ns', 'ctime_ns', 'mode', 'uid', 'gid', 'links'}
_ENV = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C', 'LANG': 'C', 'TZ': 'UTC'}

_TOOL_TRACE = threading.local()
LEGACY_COLLECTOR_POLICY = 'legacy_vmmap_summary_v1'
SAMPLE_COLLECTOR_POLICY = 'sample_header_v1'
FORK_CORPSE_COLLECTOR_POLICY = 'fork_corpse_vmmap_v1'
_COLLECTOR_PATHS = {'sample': '/usr/bin/sample', 'vmmap': '/usr/bin/vmmap'}


def validate_collector_policy(value):
    """Validate a scope-owned policy without adopting identities from evidence."""
    _keys(value, {'policy', 'tools'})
    policy = value['policy']
    if type(policy) is not str or policy not in (LEGACY_COLLECTOR_POLICY, SAMPLE_COLLECTOR_POLICY, FORK_CORPSE_COLLECTOR_POLICY):
        _fail('UNKNOWN_COLLECTOR_POLICY')
    tools = value['tools']
    paths = (_COLLECTOR_PATHS if policy == SAMPLE_COLLECTOR_POLICY else
             {'vmmap': _COLLECTOR_PATHS['vmmap']} if policy == FORK_CORPSE_COLLECTOR_POLICY else {})
    _keys(tools, set(paths))
    for name, path in paths.items():
        record = tools[name]
        _keys(record, {'path', 'bytes', 'sha256'})
        if (record['path'] != path or type(record['bytes']) is not int
                or not 0 < record['bytes'] <= MAX_IMAGE_BYTES
                or type(record['sha256']) is not str
                or re.fullmatch('[0-9a-f]{64}', record['sha256']) is None):
            _fail('COLLECTOR_TOOL_BINDING_INVALID')
    return value


def scope_collector_policy(scope):
    value = scope.get('process_image_policy',
                      {'policy': LEGACY_COLLECTOR_POLICY, 'tools': {}})
    return validate_collector_policy(value)


def _authenticated_collector_policy():
    # Owned children inherit only the scope binding, never a caller-selected
    # collector name. NativeScope verifies its frozen bytes and accounting.
    raw = os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')
    if raw is None:
        return None  # Unscoped API keeps the global sample-header default.
    import json
    from .native_scope import NativeScope
    return NativeScope(json.loads(raw)).collector_policy()


def check_collector_tools(policy, deadline):
    validate_collector_policy(policy)
    for record in policy['tools'].values():
        with _opened_image(record['path'], deadline) as (descriptor, information):
            if (information['size'] != record['bytes']
                    or _hash(descriptor, information['size'], deadline) != record['sha256']):
                _fail('COLLECTOR_TOOL_CHANGED')


def collector_vmmap_count(policy):
    return 2 if validate_collector_policy(policy)['policy'] == SAMPLE_COLLECTOR_POLICY else 4


def collector_vmmap_argv(policy, pid, argv, index):
    """旧命令保持原合同；forkCorpse策略精确绑定两组头信息与地址查询的顺序。"""
    count = collector_vmmap_count(policy)
    if type(index) is not int or not 0 <= index < count:
        return False
    if policy['policy'] == FORK_CORPSE_COLLECTOR_POLICY:
        header = ['/usr/bin/vmmap', '-forkCorpse', '-w', '-interleaved', str(pid)]
        if index in (0, 2):
            return argv == header
        return (type(argv) is list and len(argv) == 6 and argv[:5] == header
                and type(argv[5]) is str and re.fullmatch(r'0x[0-9a-fA-F]{1,16}', argv[5]) is not None
                and int(argv[5], 16) > 0)
    if count == 4 and argv == ['/usr/bin/vmmap', '-w', '-interleaved', '-summary', str(pid)]:
        return True
    return (type(argv) is list and len(argv) == 5
            and argv[:4] == ['/usr/bin/vmmap', '-w', '-interleaved', str(pid)]
            and type(argv[4]) is str and re.fullmatch(r'0x[0-9a-fA-F]{1,16}', argv[4]) is not None
            and int(argv[4], 16) > 0)


@contextmanager
def diagnostic_tool_observer(observer):
    """Scope an optional diagnostic witness to this collector thread only."""
    previous=getattr(_TOOL_TRACE,'observer',None)
    _TOOL_TRACE.observer=observer
    try:yield
    finally:_TOOL_TRACE.observer=previous


def _diagnostic_callback(observer,method,*args):
    if observer is None:return None
    try:return getattr(observer,method)(*args)
    except BaseException as error:
        # Optional diagnostics must never replace an image result or failure.
        try:observer.observer_error(type(error).__name__+':'+str(error)[:512])
        except BaseException:pass
        return None



class ProcessImageError(ValueError):
    """Unavailable, ambiguous, changed or inconsistent process-image evidence."""


def _fail(reason):
    raise ProcessImageError('PROCESS_IMAGE_' + reason)


def _supported():
    if sys.platform != 'darwin':
        _fail('UNSUPPORTED_PLATFORM')


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _fail('TIMEOUT')
    return remaining


def _keys(value, keys):
    if (type(value) is not dict or any(type(key) is not str for key in value)
            or set(value) != keys):
        _fail('INVALID_STRUCTURE')


def _tag(value, expected):
    return type(value) is str and value == expected


def _pid(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 0x7fffffff:
        _fail('INVALID_PID')


def _path(value):
    if isinstance(value, Path):
        value = str(value)
    if (type(value) is not str or not 1 < len(value) <= 4096 or not value.startswith('/')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in ('', '.', '..') for part in value[1:].split('/'))
            or len(value.split('/')) > 128):
        _fail('INVALID_PATH')
    return value


def _signature(info):
    return dict(device=info.st_dev, inode=info.st_ino, size=info.st_size,
                mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
                mode=info.st_mode, uid=info.st_uid, gid=info.st_gid, links=info.st_nlink)


def _walk(path, deadline):
    """Open every component relative to a held directory; never follow a link."""
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    chain = []
    try:
        for part in path[1:].split('/')[:-1]:
            _remaining(deadline)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
            info = os.fstat(directory)
            chain.append((info.st_dev, info.st_ino, info.st_mode))
        _remaining(deadline)
        descriptor = os.open(path.rsplit('/', 1)[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        return descriptor, chain
    finally:
        os.close(directory)


@contextmanager
def _opened_image(path, deadline):
    descriptor = None
    try:
        descriptor, chain = _walk(path, deadline)
        before = _signature(os.fstat(descriptor))
        _validate_stat(before)
        yield descriptor, before
        _remaining(deadline)
        reopened, current_chain = _walk(path, deadline)
        try:
            if (chain != current_chain or _signature(os.fstat(reopened)) != before
                    or _signature(os.fstat(descriptor)) != before):
                _fail('FILE_CHANGED')
        finally:
            os.close(reopened)
        _remaining(deadline)
    except OSError as error:
        raise ProcessImageError('PROCESS_IMAGE_FILE_UNAVAILABLE') from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _hash(descriptor, size, deadline, read_budget=None):
    digest = hashlib.sha256()
    used = 0
    while True:
        _remaining(deadline)
        requested = min(1024 * 1024, size - used + 1)
        if read_budget is not None:
            # Reserve before IO, including the final EOF probe. The caller may
            # persist this charge; never roll it back after failure or retry.
            read_budget.reserve(requested)
            _remaining(deadline)
        data = os.read(descriptor, requested)
        if not data:
            break
        used += len(data)
        if used > size:
            _fail('FILE_CHANGED')
        digest.update(data)
    if used != size:
        _fail('FILE_CHANGED')
    _remaining(deadline)
    return digest.hexdigest()


def _validate_stat(value):
    _keys(value, _STAT_KEYS)
    if (any(type(v) is not int or v < 0 or v >= 2**64 for v in value.values())
            or value['inode'] == 0 or not 0 < value['size'] <= MAX_IMAGE_BYTES
            or not stat.S_ISREG(value['mode']) or not value['mode'] & 0o111
            or value['links'] != 1):
        _fail('INVALID_FILE_IDENTITY')


def _validate_image(value):
    _keys(value, {'path', 'sha256', 'stat'})
    if type(value['path']) is not str:
        _fail('INVALID_PATH')
    _path(value['path'])
    _validate_stat(value['stat'])
    if type(value['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        _fail('INVALID_SHA256')


def _validate_expected(value):
    _keys(value, {'schema', 'platform', 'version', 'image'})
    if (not _tag(value['schema'], EXECUTABLE_SCHEMA) or not _tag(value['platform'], 'darwin')
            or type(value['version']) is not str or not 0 < len(value['version']) <= 128
            or value['version'].strip() != value['version']
            or any(ord(c) < 32 or ord(c) == 127 for c in value['version'])):
        _fail('EXPECTED_EXECUTABLE_REQUIRED')
    _validate_image(value['image'])


def freeze_executable(path, version, sha256, *, read_budget=None):
    """Freeze an explicit absolute, link-free executable and exact expected SHA-256.

    version is a trusted deployment label, not a version inferred from file names.
    Returns {schema, platform: 'darwin', version, image: {path, sha256, stat}}.
    """
    _supported()
    deadline = time.monotonic() + FREEZE_TIMEOUT_SECONDS
    path = _path(path)
    result = {'schema': EXECUTABLE_SCHEMA, 'platform': 'darwin', 'version': version,
              'image': {'path': path, 'sha256': sha256, 'stat': {}}}
    # Validate explicit inputs before any file IO.
    placeholder = dict(device=0, inode=1, size=1, mtime_ns=0, ctime_ns=0,
                       mode=stat.S_IFREG | 0o500, uid=0, gid=0, links=1)
    _validate_expected({**result, 'image': {**result['image'], 'stat': placeholder}})
    with _opened_image(path, deadline) as (descriptor, information):
        if _hash(descriptor, information['size'], deadline, read_budget) != sha256:
            _fail('SHA256_MISMATCH')
        result['image']['stat'] = information
    return result



def _darwin_boot_epoch():
    """只读内核启动时间；历史校验不启动sysctl子进程或观察新PID。"""
    import ctypes
    import math
    _supported()
    class Timeval(ctypes.Structure):
        _fields_ = [('seconds', ctypes.c_long), ('microseconds', ctypes.c_int)]
    value = Timeval()
    length = ctypes.c_size_t(ctypes.sizeof(value))
    libc = ctypes.CDLL(None, use_errno=True)
    sysctl = libc.sysctlbyname
    sysctl.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                       ctypes.c_void_p, ctypes.c_size_t]
    sysctl.restype = ctypes.c_int
    if (sysctl(b'kern.boottime', ctypes.byref(value), ctypes.byref(length), None, 0) != 0
            or length.value != ctypes.sizeof(value) or value.seconds <= 0
            or not 0 <= value.microseconds < 1000000):
        _fail('HISTORICAL_BOOT_UNAVAILABLE')
    epoch = value.seconds + value.microseconds / 1000000
    if not math.isfinite(epoch) or epoch > time.time():
        _fail('HISTORICAL_BOOT_UNAVAILABLE')
    return epoch


def verify_historical_executable(signed_expected, *, path, version, sha256, completed_at):
    """互证旧文件身份与当前完整字节；仅重启后可忽略旧卷的临时设备号。"""
    import math
    _validate_expected(signed_expected)
    if (type(completed_at) not in (int, float) or not math.isfinite(completed_at)
            or not 0 < completed_at <= time.time()):
        _fail('HISTORICAL_STOP_TIME_INVALID')
    current = freeze_executable(path, version, sha256)
    _validate_expected(current)
    # SHA覆盖完整Mach-O架构字节；不添加旧结构中并不存在的architecture字段。
    if (any(signed_expected[key] != current[key] for key in ('schema', 'platform', 'version'))
            or any(signed_expected['image'][key] != current['image'][key] for key in ('path', 'sha256'))
            or any(signed_expected['image']['stat'][key] != current['image']['stat'][key]
                   for key in _STAT_KEYS - {'device'})):
        _fail('HISTORICAL_EXECUTABLE_CHANGED')
    if signed_expected['image']['stat']['device'] != current['image']['stat']['device']:
        boot = _darwin_boot_epoch()
        if (type(boot) not in (int, float) or not math.isfinite(boot)
                or not completed_at < boot <= time.time()):
            _fail('HISTORICAL_BOOT_NOT_AFTER_STOP')
    return current


def _historical_source_snapshot(path, expected_sha256=None):
    """小源码的首末封口：安全打开、完整哈希、重开同一文件与目录链。"""
    path = _path(str(path));deadline = time.monotonic() + FREEZE_TIMEOUT_SECONDS
    descriptor = None
    try:
        descriptor, chain = _walk(path, deadline)
        before = _signature(os.fstat(descriptor))
        if (not stat.S_ISREG(before['mode']) or before['links'] != 1
                or not 0 < before['size'] <= 2 * 1024 * 1024):
            _fail('HISTORICAL_SOURCE_INVALID')
        digest = _hash(descriptor, before['size'], deadline)
        reopened, later_chain = _walk(path, deadline)
        try:
            if (chain != later_chain or _signature(os.fstat(descriptor)) != before
                    or _signature(os.fstat(reopened)) != before):
                _fail('HISTORICAL_SOURCE_CHANGED')
        finally:
            os.close(reopened)
        if expected_sha256 is not None and digest != expected_sha256:
            _fail('HISTORICAL_SOURCE_CHANGED')
        return {'path': path, 'bytes': before['size'], 'sha256': digest}, before
    except OSError as error:
        raise ProcessImageError('PROCESS_IMAGE_HISTORICAL_SOURCE_UNAVAILABLE') from error
    finally:
        if descriptor is not None:os.close(descriptor)




_HISTORICAL_VIEW_SCHEMA = 'bridge.rectlight-shape-runtime-view/1'
_HISTORICAL_VIEW_DOMAIN = b'bridge.rectlight-shape-runtime-view/1\x00'

# These readers authenticate their own package separately from the original
# signed production package. An unlisted version must not inherit admission.
_HISTORICAL_READER_VERSIONS = (
    '0.4.12', '0.4.13', '0.4.14', '0.4.15', '0.4.16', '0.4.17',
    '0.4.18', '0.4.19', '0.4.20', '0.4.21', '0.4.22', '0.4.23',
)
_CREATED_GEOMETRY_ALPHA_VERSIONS = (
    '0.4.14', '0.4.15', '0.4.16', '0.4.17', '0.4.18',
    '0.4.19', '0.4.20', '0.4.21', '0.4.22', '0.4.23',
)

_HISTORICAL_SHAPE_MODULES = (
    ('dcc_task_runtime.process_image','dcc-task-runtime','process_image.py','_historical_package_sources'),
    ('dcc_task_runtime.alpha_calibration','dcc-task-runtime','alpha_calibration.py','validate_historical_alpha_calibration'),
    ('houdini_bridge.alpha_reuse','houdini-bridge','alpha_reuse.py','validate_output_calibration'),
    ('dcc_task_runtime.native_scope','dcc-task-runtime','native_scope.py','NativeScope._setup'),
    ('dcc_task_runtime.rectlight_shape_scope','dcc-task-runtime','rectlight_shape_scope.py','validate_scope'),
    ('dcc_task_runtime.project_color','dcc-task-runtime','project_color.py','validate_project_color'),
    ('houdini_bridge.rectlight_shape_target','houdini-bridge','rectlight_shape_target.py','plugin_shape_update'),
)


def _historical_document(record, baselines):
    """从精确FileRecord读小型身份元数据，读回字节和首封保持一致。"""
    import json
    if (type(record) is not dict or set(record) not in ({'path','sha256'},{'path','bytes','sha256'})
            or type(record.get('sha256')) is not str
            or re.fullmatch('[0-9a-f]{64}',record['sha256']) is None):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    first = _historical_source_snapshot(record['path'],record['sha256'])
    if 'bytes' in record and first[0] != record:_fail('HISTORICAL_SOURCE_CHANGED')
    previous = baselines.get(record['path'])
    if previous is not None and previous != first:_fail('HISTORICAL_SOURCE_CHANGED')
    baselines[record['path']] = first
    raw = Path(record['path']).read_bytes()
    if len(raw) != first[0]['bytes'] or hashlib.sha256(raw).hexdigest() != first[0]['sha256']:
        _fail('HISTORICAL_SOURCE_CHANGED')
    def unique(pairs):
        value = {}
        for key,item in pairs:
            if key in value:_fail('HISTORICAL_RUNTIME_VIEW_INVALID')
            value[key] = item
        return value
    value = json.loads(raw,object_pairs_hook=unique)
    if type(value) is not dict:_fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    return value


def _historical_view_bootstrap(binding, baselines):
    if type(binding) is not dict or set(binding) != {'path','sha256'}:
        _fail('HISTORICAL_SHAPE_SCOPE_REQUIRED')
    scope = _historical_document(binding,baselines)
    authority = _historical_document(scope.get('shape_authority'),baselines)
    return scope,authority


def _historical_view_key(scope, baselines):
    """只读本新scope原会计key，不复制、不另造运行授权。"""
    accounting = scope.get('accounting') or {}
    path = accounting.get('key_path')
    expected = accounting.get('key_sha256')
    if type(path) is not str or type(expected) is not str:_fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    snapshot = _historical_source_snapshot(path,expected)
    key = Path(path).read_bytes()
    if len(key) != 32 or snapshot[0]['bytes'] != 32 or hashlib.sha256(key).hexdigest() != expected:
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    prior = baselines.get(path)
    if prior is not None and prior != snapshot:_fail('HISTORICAL_SOURCE_CHANGED')
    baselines[path] = snapshot
    return key


def _historical_view_canonical(value):
    import json
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _historical_runtime_view(scope_binding, scope, authority, snapshot, baselines, *, payload=None):
    """只接受本task当前job的签名视图；未签manifest与同字节任意clone均不是身份。"""
    import hmac
    snapshot = Path(_path(str(snapshot)))
    control = snapshot.parent
    directory = control.parent.parent
    operation = directory.name
    root = Path(scope_binding['path']).parent
    if (snapshot != control/'snapshot' or not operation or '/' in operation
            or control != root/'jobs'/operation/'project/control'):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    target = control/'rectlight-shape-runtime-view.json'
    key = _historical_view_key(scope,baselines)
    if payload is None:
        view = _historical_document(_historical_source_snapshot(target)[0],baselines)
        payload = view.get('payload')
        expected = hmac.new(key,_HISTORICAL_VIEW_DOMAIN+_historical_view_canonical(payload),hashlib.sha256).hexdigest()
        if set(view) != {'payload','signature'} or not hmac.compare_digest(str(view['signature']),expected):
            _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    fields = {'schema','scope','task_id','creative_task_id','operation_id','job','preparation',
              'control','snapshot_manifest','run','formal_manifest','sources','source_job'}
    if (type(payload) is not dict or set(payload) != fields or payload['schema'] != _HISTORICAL_VIEW_SCHEMA
            or payload['scope'] != scope_binding or payload['task_id'] != scope.get('task_id')
            or payload['creative_task_id'] != scope.get('creative_task_id') or payload['operation_id'] != operation
            or payload['control'] != str(control) or payload['job']['path'] != str(directory/'execution-job.json')
            or payload['source_job']['path'] != str(directory/'job.json')
            or payload['run']['path'] != str(control/'run.json')
            or payload['snapshot_manifest']['path'] != str(control/'snapshot-manifest.json')
            or payload['formal_manifest'] != authority['runtime_requirements']['manifest']):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    job = _historical_document(payload['job'],baselines)
    source_job = _historical_document(payload['source_job'],baselines)
    prep = _historical_document(payload['preparation'],baselines)
    source_preparation = _historical_document(source_job['preparation'],baselines)
    run = _historical_document(payload['run'],baselines)
    manifest = _historical_document(payload['snapshot_manifest'],baselines)
    if (job.get('schema') != 'bridge.rectlight-shape-job/1' or job.get('operation_id') != operation
            or job.get('directory') != str(directory) or job.get('preparation') != payload['preparation']
            or prep.get('scope') != scope_binding or prep.get('task_id') != scope.get('task_id')
            or prep.get('creative_task_id') != scope.get('creative_task_id')
            or job != {**source_job,'preparation':payload['preparation'],'source_job':payload['source_job']}
            or prep.get('original_preparation') != source_job.get('preparation')
            or source_preparation.get('scope') != scope_binding
            or source_preparation.get('task_id') != scope.get('task_id')
            or source_preparation.get('creative_task_id') != scope.get('creative_task_id')):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    host = run.get('production_host')
    if (type(host) is not dict or host.get('native_scope') != scope_binding
            or (host.get('resource_budget') or {}).get('native_scope') != scope_binding
            or host.get('task_root') != str(root) or host.get('controller_root') != str(control)):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    rows = manifest.get('files')
    if type(rows) is not list or not 1 <= len(rows) <= 2048:_fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    index = {}
    for row in rows:
        name = row.get('path') if isinstance(row,dict) else None
        if (type(row) is not dict or set(row) != {'path','sha256'} or type(name) is not str
                or not name or name.startswith('/') or '\\' in name
                or any(part in ('','.','..') for part in name.split('/')) or name in index):
            _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
        index[name] = row
    expected_sources = authority['runtime_requirements']['historical_sources']
    if type(payload['sources']) is not dict or set(payload['sources']) != set(expected_sources):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    for relative,formal in expected_sources.items():
        name = relative.removeprefix('runtime/')
        actual = payload['sources'][relative]
        if (actual != {'path':str(snapshot/name),'bytes':formal['bytes'],'sha256':formal['sha256']}
                or index.get(name) != {'path':name,'sha256':formal['sha256']}):
            _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
        first = _historical_source_snapshot(actual['path'],actual['sha256'])
        if first[0] != actual:_fail('HISTORICAL_SOURCE_CHANGED')
        previous = baselines.get(actual['path'])
        if previous is not None and previous != first:_fail('HISTORICAL_SOURCE_CHANGED')
        baselines[actual['path']] = first
    return payload



def verify_runtime_view(scope_binding, control):
    """子控制器首次调用view的NS前做只读bootstrap，不构造任何NativeScope。"""
    baselines = {}
    scope, authority = _historical_view_bootstrap(scope_binding,baselines)
    requirements = authority.get('runtime_requirements')
    relatives = {f"runtime/packages/{distribution}/src/{module.rsplit('.',1)[0]}/{filename}"
                 for module,distribution,filename,_ in _HISTORICAL_SHAPE_MODULES}
    if (type(requirements) is not dict
            or set(requirements) != {'version','formal_root','plugin','manifest','historical_sources'}
            or requirements.get('version') != '0.4.11'
            or type(requirements.get('historical_sources')) is not dict
            or set(requirements['historical_sources']) != relatives
            or scope.get('schema') != 'bridge.rectlight-shape-scope/1'
            or scope.get('resource_profile') != 'h21_rectlight_shape_12_1800_v1'):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    formal = Path(_path(requirements['formal_root']))
    manifest = _historical_document(requirements['manifest'],baselines)
    plugin = _historical_document(requirements['plugin'],baselines)
    if (requirements['manifest']['path'] != str(formal/'runtime-manifest.json')
            or requirements['plugin']['path'] != str(formal/'plugin.json')
            or plugin.get('name') != 'bridge-vfx' or plugin.get('version') != '0.4.11'
            or manifest.get('schema_version') != 1
            or type(manifest.get('files')) is not list
            or hashlib.sha256(_historical_view_canonical(manifest['files'])).hexdigest() != manifest.get('file_manifest_sha256')):
        _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    entries = {}
    for entry in manifest['files']:
        if type(entry) is not dict or entry.get('path') in entries:_fail('HISTORICAL_RUNTIME_VIEW_INVALID')
        entries[entry.get('path')] = entry
    for relative,record in requirements['historical_sources'].items():
        if (record['path'] != str(formal/relative)
                or entries.get(relative) != {'path':relative,'bytes':record['bytes'],'sha256':record['sha256']}
                or _historical_source_snapshot(record['path'],record['sha256'])[0] != record):
            _fail('HISTORICAL_RUNTIME_VIEW_INVALID')
    payload = _historical_runtime_view(scope_binding,scope,authority,Path(control)/'snapshot',baselines)
    for path,first in baselines.items():
        if _historical_source_snapshot(path) != first:_fail('HISTORICAL_SOURCE_CHANGED')
    return payload

def seal_runtime_view(scope_binding, job_record, control):
    """prepare_graph定稿后且Native前，为本轮一个job封存唯一加载视图。"""
    import hmac
    # 签前认证正式包/作用域闭包，不把未认证snapshot用作签名者。
    baselines = _historical_package_sources(shape_scope_binding=scope_binding)
    scope,authority = _historical_view_bootstrap(scope_binding,baselines)
    control = Path(_path(str(control)))
    job = _historical_document(job_record,baselines)
    from dcc_task_runtime.native_scope import NativeScope
    state = NativeScope(scope_binding).completed_snapshot()
    directory = control.parent.parent
    if any(ticket.get('stopped_at') is None
           or Path(ticket['directory']).is_relative_to(directory)
           or str(ticket['identity'].get('operation_id','')).startswith(job['operation_id'])
           for ticket in state['tickets']):
        _fail('HISTORICAL_RUNTIME_VIEW_PRE_NATIVE_REQUIRED')
    sources = {relative:_historical_source_snapshot(control/'snapshot'/relative.removeprefix('runtime/'))[0]
               for relative in authority['runtime_requirements']['historical_sources']}
    payload = {'schema':_HISTORICAL_VIEW_SCHEMA,'scope':scope_binding,'task_id':scope['task_id'],
        'creative_task_id':scope['creative_task_id'],'operation_id':job['operation_id'],'job':job_record,
        'preparation':job['preparation'],'control':str(control),
        'snapshot_manifest':_historical_source_snapshot(control/'snapshot-manifest.json')[0],
        'run':_historical_source_snapshot(control/'run.json')[0],
        'formal_manifest':authority['runtime_requirements']['manifest'],'sources':sources,'source_job':job['source_job']}
    _historical_runtime_view(scope_binding,scope,authority,control/'snapshot',baselines,payload=payload)
    for path,first in baselines.items():
        if _historical_source_snapshot(path) != first:_fail('HISTORICAL_SOURCE_CHANGED')
    key = _historical_view_key(scope,baselines)
    envelope = {'payload':payload,'signature':hmac.new(key,
        _HISTORICAL_VIEW_DOMAIN+_historical_view_canonical(payload),hashlib.sha256).hexdigest()}
    target = control/'rectlight-shape-runtime-view.json'
    descriptor = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(_historical_view_canonical(envelope));stream.flush();os.fsync(stream.fileno())
    return _historical_source_snapshot(target)[0]

def _historical_reader_sources(package, index, baselines, modules):
    """0412读取器只使用本正式包的固定模块；文件、模块与函数来源必须一致。"""
    import importlib
    plugin = baselines[str(package/'plugin.json')][0]
    if index.get('plugin.json') != {'path':'plugin.json','bytes':plugin['bytes'],'sha256':plugin['sha256']}:
        _fail('HISTORICAL_PACKAGE_INVALID')
    for module_name, distribution, filename, function in modules:
        relative = f"runtime/packages/{distribution}/src/{module_name.rsplit('.',1)[0]}/{filename}"
        entry = index.get(relative)
        if (type(entry) is not dict or set(entry) != {'path','bytes','sha256'}
                or entry.get('path') != relative or type(entry.get('bytes')) is not int or entry['bytes'] <= 0
                or type(entry.get('sha256')) is not str or re.fullmatch('[0-9a-f]{64}',entry['sha256']) is None):
            _fail('HISTORICAL_PACKAGE_INVALID')
        path = package/relative
        first = _historical_source_snapshot(path,entry['sha256'])
        if first[0] != {'path':str(path),'bytes':entry['bytes'],'sha256':entry['sha256']}:
            _fail('HISTORICAL_SOURCE_CHANGED')
        previous = baselines.get(str(path))
        if previous is not None and previous != first:_fail('HISTORICAL_SOURCE_CHANGED')
        baselines[str(path)] = first
        module = importlib.import_module(module_name)
        implementation = module
        for part in function.split('.'):implementation = getattr(implementation,part,None)
        code = getattr(implementation,'__code__',None)
        spec = getattr(module,'__spec__',None)
        if (module.__name__ != module_name or not getattr(module,'__file__',None)
                or Path(module.__file__).resolve() != path
                or spec is None or not spec.origin or Path(spec.origin).resolve() != path
                or code is None or Path(code.co_filename).resolve() != path):
            _fail('HISTORICAL_RUNTIME_SOURCE_MISMATCH')
    for path, first in baselines.items():
        if _historical_source_snapshot(path) != first:_fail('HISTORICAL_SOURCE_CHANGED')
    return baselines


def _historical_shape_package_sources(package, index, baselines, binding, verifier_source=None):
    """分开认证当前读取器与原0411生产闭包，旧scope不为新模块签发身份。"""
    import importlib
    import json
    if (type(binding) is not dict or set(binding) != {'path', 'sha256'}
            or type(binding.get('sha256')) is not str
            or re.fullmatch('[0-9a-f]{64}', binding['sha256']) is None):
        _fail('HISTORICAL_SHAPE_SCOPE_REQUIRED')

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:_fail('HISTORICAL_SHAPE_AUTHORITY_INVALID')
            value[key] = item
        return value

    def freeze(record, *, exact_path=None):
        if (type(record) is not dict or set(record) not in ({'path','sha256'}, {'path','bytes','sha256'})
                or type(record.get('sha256')) is not str
                or re.fullmatch('[0-9a-f]{64}', record['sha256']) is None
                or ('bytes' in record and (type(record['bytes']) is not int or record['bytes'] <= 0))
                or exact_path is not None and record['path'] != str(exact_path)):
            _fail('HISTORICAL_SHAPE_AUTHORITY_INVALID')
        current = _historical_source_snapshot(record['path'], record['sha256'])
        if 'bytes' in record and current[0] != record:_fail('HISTORICAL_SOURCE_CHANGED')
        previous = baselines.get(record['path'])
        if previous is not None and previous != current:_fail('HISTORICAL_SOURCE_CHANGED')
        baselines[record['path']] = current
        return current

    def document(record):
        first = freeze(record)
        raw = Path(record['path']).read_bytes()
        if len(raw) != first[0]['bytes'] or hashlib.sha256(raw).hexdigest() != first[0]['sha256']:
            _fail('HISTORICAL_SOURCE_CHANGED')
        value = json.loads(raw, object_pairs_hook=unique)
        if type(value) is not dict:_fail('HISTORICAL_SHAPE_AUTHORITY_INVALID')
        return value

    scope = document(binding)
    root = Path(binding['path']).parent
    authority = document(scope.get('shape_authority'))
    allowed_sources = authority.get('sources')
    if verifier_source is not None and (type(allowed_sources) is not dict
            or verifier_source != allowed_sources.get('alpha_source')):
        _fail('HISTORICAL_SHAPE_VERIFIER_REQUIRED')
    requirements = authority.get('runtime_requirements')
    if (type(requirements) is not dict
            or set(requirements) != {'version','formal_root','plugin','manifest','historical_sources'}
            or requirements.get('version') != '0.4.11'):
        _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
    formal = Path(_path(requirements['formal_root']))
    if formal != formal.resolve():_fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
    reader = document(baselines[str(package/'plugin.json')][0])
    current_reader = reader.get('version') in _HISTORICAL_READER_VERSIONS
    if current_reader:
        _historical_reader_sources(package,index,baselines,_HISTORICAL_SHAPE_MODULES)
    for name, field in (('plugin.json','plugin'), ('runtime-manifest.json','manifest')):
        authenticated = freeze(requirements[field], exact_path=formal/name)[0]
        installed = baselines[str(package/name)][0]
        if not current_reader and any(authenticated[key] != installed[key] for key in ('bytes','sha256')):
            _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
    if current_reader:
        # 旧生产索引来自scope固定的0411 manifest，不能拿0412读取器索引替代。
        producer = document(requirements['plugin'])
        manifest = document(requirements['manifest'])
        if (producer.get('name') != 'bridge-vfx' or producer.get('version') != '0.4.11'
                or manifest.get('schema_version') != 1 or type(manifest.get('files')) is not list
                or hashlib.sha256(_historical_view_canonical(manifest['files'])).hexdigest()
                    != manifest.get('file_manifest_sha256')):
            _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
        index = {}
        for entry in manifest['files']:
            if type(entry) is not dict or type(entry.get('path')) is not str or entry['path'] in index:
                _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
            index[entry['path']] = entry
        if index.get('plugin.json') != {'path':'plugin.json','bytes':requirements['plugin']['bytes'],
                                       'sha256':requirements['plugin']['sha256']}:
            _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')

    modules = _HISTORICAL_SHAPE_MODULES
    relatives = {f"runtime/packages/{distribution}/src/{module.rsplit('.',1)[0]}/{filename}"
                 for module, distribution, filename, _ in modules}
    authorized = requirements['historical_sources']
    if type(authorized) is not dict or set(authorized) != relatives:
        _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
    # 原七源始终核旧生产索引；0412实际加载身份已由本包索引独立认证。
    for module_name, distribution, filename, function in modules:
        relative = f"runtime/packages/{distribution}/src/{module_name.rsplit('.',1)[0]}/{filename}"
        expected = authorized[relative]
        formal_record = freeze(expected, exact_path=formal/relative)[0]
        entry = index.get(relative)
        if (type(entry) is not dict or set(entry) != {'path','bytes','sha256'}
                or entry != {'path':relative,'bytes':formal_record['bytes'],'sha256':formal_record['sha256']}):
            _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
        if current_reader:
            continue
        module = importlib.import_module(module_name)
        actual_path = Path(module.__file__).resolve()
        if actual_path not in (package/relative, formal/relative):
            snapshot = actual_path.parents[4]
            view = _historical_runtime_view(binding,scope,authority,snapshot,baselines)
            if actual_path != Path(view['sources'][relative]['path']):
                _fail('HISTORICAL_RUNTIME_SOURCE_MISMATCH')
        freeze({'path':str(actual_path),'bytes':formal_record['bytes'],'sha256':formal_record['sha256']})
        implementation = module
        for part in function.split('.'):implementation = getattr(implementation, part, None)
        code = getattr(implementation, '__code__', None)
        spec = getattr(module, '__spec__', None)
        if (module.__name__ != module_name or Path(module.__file__).resolve() != actual_path
                or spec is None or not spec.origin or Path(spec.origin).resolve() != actual_path
                or code is None or Path(code.co_filename).resolve() != actual_path):
            _fail('HISTORICAL_RUNTIME_SOURCE_MISMATCH')

    # 读取器与原生产身份各自封口后，重验原生记账和原任务语义。
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime import rectlight_shape_scope
    if current_reader:
        # 已固定shape授权只读原签账本，不能由构造器在原工程创建会计锁。
        if (scope.get('schema') != rectlight_shape_scope.SCHEMA
                or scope.get('resource_profile') != rectlight_shape_scope.RESOURCE_PROFILE):
            _fail('HISTORICAL_SHAPE_SCOPE_REQUIRED')
        native = NativeScope.__new__(NativeScope)
        native._setup(binding)
        native._read()
    else:
        native = NativeScope(binding)
    verified = rectlight_shape_scope.validate_scope(native.scope, native.path)
    if (native.scope != scope or native.root != root
            or native.resource_profile != rectlight_shape_scope.RESOURCE_PROFILE
            or native.scope.get('schema') != rectlight_shape_scope.SCHEMA
            or verified != authority or native.scope.get('creative_task_id') != authority.get('creative_task_id')):
        _fail('HISTORICAL_SHAPE_SCOPE_REQUIRED')
    for path, first in baselines.items():
        if _historical_source_snapshot(path) != first:_fail('HISTORICAL_SOURCE_CHANGED')
    return baselines

_CREATED_GEOMETRY_ALPHA = threading.local()


def _geometry_alpha_module_sources(package, index, baselines, snapshot_root, modules, *, error_code):
    """Keep original production bytes separate from an independently verified reader."""
    runtime = Path(__file__).resolve().parents[4]
    records = {}
    for name, part, filename, attribute in modules:
        relative = 'packages/'+part+'/src/'+name.split('.')[0]+'/'+filename
        expected = index.get('runtime/'+relative)
        if (type(expected) is not dict or set(expected) != {'path','bytes','sha256'}
                or expected.get('path') != 'runtime/'+relative
                or type(expected.get('bytes')) is not int or expected['bytes'] <= 0
                or type(expected.get('sha256')) is not str
                or re.fullmatch('[0-9a-f]{64}',expected['sha256']) is None):
            _fail(error_code)
        for original_root in (package/'runtime', snapshot_root):
            path = original_root/relative
            first = _historical_source_snapshot(path, expected['sha256'])
            if first[0] != {**expected,'path':str(path)}:_fail(error_code)
            previous = baselines.get(str(path))
            if previous is not None and previous != first:_fail('HISTORICAL_SOURCE_CHANGED')
            baselines[str(path)] = first
        records[relative] = expected
    if runtime in (package/'runtime', snapshot_root):
        for name, part, filename, attribute in modules:
            path = runtime/'packages'/part/'src'/name.split('.')[0]/filename
            module = sys.modules.get(name);function = module
            for segment in attribute.split('.'):
                function = getattr(function,segment,None)
            spec = getattr(module,'__spec__',None);code = getattr(function,'__code__',None)
            if (module is None or module.__name__ != name or not getattr(module,'__file__',None)
                    or Path(module.__file__).resolve() != path or spec is None or not spec.origin
                    or Path(spec.origin).resolve() != path or code is None
                    or Path(code.co_filename).resolve() != path):
                _fail(error_code)
        return records
    if runtime.name != 'runtime':_fail(error_code)
    reader_package = runtime.parent
    reader_baselines = {}
    def document(path):
        return _historical_document(_historical_source_snapshot(path)[0],reader_baselines)
    plugin = document(reader_package/'plugin.json')
    manifest = document(reader_package/'runtime-manifest.json')
    if (plugin.get('name') != 'bridge-vfx' or plugin.get('version') != '0.4.23'
            or manifest.get('schema_version') != 1 or type(manifest.get('files')) is not list
            or hashlib.sha256(_historical_view_canonical(manifest['files'])).hexdigest()
                != manifest.get('file_manifest_sha256')):
        _fail(error_code)
    reader_index = {}
    for entry in manifest['files']:
        if type(entry) is not dict or type(entry.get('path')) is not str or entry['path'] in reader_index:
            _fail(error_code)
        reader_index[entry['path']] = entry
    _historical_reader_sources(reader_package,reader_index,reader_baselines,modules)
    for path,first in reader_baselines.items():
        previous = baselines.get(path)
        if previous is not None and previous != first:_fail('HISTORICAL_SOURCE_CHANGED')
        baselines[path] = first
    return records


def _created_geometry_sources(binding, alpha):
    """只认证操作者签名的新几何任务与精确正式包；不接纳任意snapshot。"""
    import copy, hmac, json
    baselines = {}
    def document(record):
        return _historical_document(record, baselines)
    def at(path):
        first = _historical_source_snapshot(path)
        return document(first[0])
    if type(binding) is not dict or set(binding) != {'path','sha256'}:
        _fail('GEOMETRY_ALPHA_SCOPE_REQUIRED')
    scope = document(binding);root = Path(_path(scope.get('output_root')))
    if Path(binding['path']) != root/'scope.json':_fail('GEOMETRY_ALPHA_SCOPE_CHANGED')
    reuse = document(scope.get('source_reuse'));origin_record = reuse.get('task_creation_origin')
    origin = document(origin_record);registry = Path(_path(origin.get('registry')))
    key_path = registry.parent/'.task-creation-control/key'
    key_first = _historical_source_snapshot(key_path);baselines[str(key_path)] = key_first
    info = key_path.stat();key = key_path.read_bytes()
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or len(key)!=32:
        _fail('GEOMETRY_ALPHA_OPERATOR_KEY_REQUIRED')
    def signed(path):
        envelope = at(path)
        if set(envelope)!={'payload','signature'}:_fail('GEOMETRY_ALPHA_SIGNATURE_INVALID')
        raw = json.dumps(envelope['payload'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        signature = hmac.new(key,b'bridge.task-creation/1\0'+raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(envelope['signature']),signature):_fail('GEOMETRY_ALPHA_SIGNATURE_INVALID')
        return envelope['payload']
    receipt = signed(root/'creation-receipt.json')
    grant = signed(root/'execution-grant.json')
    formal_record = receipt.get('runtime');manifest = document(formal_record)
    package = Path(formal_record['path']).parent
    plugin = at(package/'plugin.json')
    # 只扩展已维护的正式版本；各版本仍按自身原策略和manifest认证。
    if plugin.get('version') not in _CREATED_GEOMETRY_ALPHA_VERSIONS:_fail('GEOMETRY_ALPHA_PACKAGE_REQUIRED')
    policy = signed(registry.parent/('task-creation-policy-'+plugin['version']+'.json'))
    if (plugin.get('name')!='bridge-vfx' or plugin.get('version') not in _CREATED_GEOMETRY_ALPHA_VERSIONS
            or Path(formal_record['path'])!=package/'runtime-manifest.json'
            or manifest.get('schema_version')!=1
            or hashlib.sha256(json.dumps(manifest.get('files'),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=manifest.get('file_manifest_sha256')):
        _fail('GEOMETRY_ALPHA_PACKAGE_REQUIRED')
    index={entry['path']:entry for entry in manifest['files']}
    if len(index)!=len(manifest['files']):_fail('GEOMETRY_ALPHA_PACKAGE_REQUIRED')
    # 此处只用当前PI的安全读取函数；调用其它模块前先验其实际加载来源与代码位置。
    active = alpha.get('plugin_reuse',{}).get('active_plugin',{})
    active_path = Path(_path(active.get('path')));control = active_path.parents[4]
    if (active_path!=control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py'
            or control.name!='control' or control.parent.name!='project' or control.parents[2]!=root/'jobs'):
        _fail('GEOMETRY_ALPHA_CONTROL_CHANGED')
    modules = _HISTORICAL_SHAPE_MODULES[:4] + (('houdini_bridge.controlled_output','houdini-bridge','controlled_output.py','verify_controlled_output'),)
    _geometry_alpha_module_sources(package,index,baselines,control/'snapshot',modules,
                                   error_code='GEOMETRY_ALPHA_MODULE_CHANGED')
    prep_record = receipt.get('preparation');prep = document(prep_record)
    profile='geometry_from_existing_v1'
    if (receipt.get('schema')!='bridge.created-task/1' or receipt.get('origin')!=origin_record
            or receipt.get('root')!=str(root) or Path(prep_record['path'])!=root/'geometry-preparation.json'
            or receipt.get('task_id')!=scope.get('task_id') or prep.get('task_id')!=scope.get('task_id')
            or prep.get('scope')!=binding or prep.get('task_creation')!=origin_record
            or prep.get('source_reuse')!=scope.get('source_reuse')
            or receipt.get('profile')!=profile or origin.get('profile')!=profile
            or policy.get('schema')!='bridge.task-creation-policy/1' or policy.get('registry')!=str(registry)
            or policy.get('runtime')!=formal_record or policy.get('profile')!=profile
            or policy.get('task_root')!=str(root.parent) or root.parent!=registry.parent/'created-tasks'
            or policy.get('native_execution_authorized_by_creation') is not False
            or grant.get('schema')!='bridge.created-task-execution-grant/1'
            or any(grant.get(k)!=receipt.get(k) for k in ('task_id','project_id','preparation','runtime','profile'))
            or grant.get('budget')!=scope.get('budget') or grant.get('max_dispatches')!=2
            or type(grant.get('instruction')) is not str or len(grant['instruction'].strip())<20):
        _fail('GEOMETRY_ALPHA_TASK_CHANGED')
    from .native_scope import NativeScope,GEOMETRY_BUDGET
    native=NativeScope(binding)
    if native.resource_profile!='h21_geometry_creative_14_1800_v1' or scope.get('budget')!=GEOMETRY_BUDGET:
        _fail('GEOMETRY_ALPHA_SCOPE_CHANGED')
    registered=at(registry).get('projects',{}).get(receipt.get('project_id'))
    if not registered or registered.get('kind')!='geometry_task' or registered.get('preparation')!=prep_record:
        _fail('GEOMETRY_ALPHA_REGISTRATION_CHANGED')
    job=at(control.parents[1]/'job.json');jobprep=at(control.parents[1]/'job-preparation.json')
    operation=control.parents[1].name
    state=at(root/'geometry-state.json');requests=at(root/'execution-requests.json')
    matching=[key for key,value in state.get('execution_requests',{}).items() if value.get('operation_id')==operation]
    if (state.get('task_id')!=scope['task_id'] or state.get('preparation')!=prep_record
            or state.get('jobs',{}).get(operation,{}).get('job_file')!=baselines[str(control.parents[1]/'job.json')][0]
            or not any(requests.get('requests',{}).get(key,{}).get('plan_id')==job.get('plan',{}).get('plan_id') for key in matching)
            or sum(v.get('state')!='ALIAS' for v in requests.get('requests',{}).values())>2):
        _fail('GEOMETRY_ALPHA_JOB_CHANGED')
    if (job.get('task_id')!=scope['task_id'] or job.get('preparation')!=prep_record
            or job.get('operation_id')!=operation or job.get('directory')!=str(control.parents[1])
            or jobprep.get('job')!=baselines[str(control.parents[1]/'job.json')][0]
            or jobprep.get('control')!=str(control)):_fail('GEOMETRY_ALPHA_JOB_CHANGED')
    run=document(jobprep.get('manifest'));snapshot=document(jobprep.get('snapshot_manifest'))
    if (jobprep['manifest']['path']!=str(control/'run.json')
            or jobprep['snapshot_manifest']['path']!=str(control/'snapshot-manifest.json')
            or run.get('geometry_task_binding')!=prep.get('task_binding')
            or run.get('production_host',{}).get('alpha_calibration')!=alpha):_fail('GEOMETRY_ALPHA_MANIFEST_CHANGED')
    expected=copy.deepcopy(prep['hosts']['houdini']['alpha_calibration'])
    if expected['plugin_reuse']['active_plugin']!=receipt.get('execution_plugin_source'):
        _fail('GEOMETRY_ALPHA_SOURCE_CHANGED')
    expected['plugin_reuse']['active_plugin']['path']=str(active_path)
    if expected!=alpha:_fail('GEOMETRY_ALPHA_SOURCE_CHANGED')
    actual=_historical_source_snapshot(active_path)
    if actual[0]!=active:_fail('GEOMETRY_ALPHA_PLUGIN_CHANGED')
    baselines[str(active_path)]=actual
    snapshot_index={entry['path']:entry['sha256'] for entry in snapshot['files']}
    if len(snapshot_index)!=len(snapshot['files']):_fail('GEOMETRY_ALPHA_MANIFEST_CHANGED')
    for name,part,filename,_ in modules:
        relative='packages/'+part+'/src/'+name.split('.')[0]+'/'+filename
        if snapshot_index.get(relative)!=index['runtime/'+relative]['sha256']:_fail('GEOMETRY_ALPHA_MODULE_CHANGED')
    if snapshot_index.get('plugins/houdini/_impl/houdini_bridge_addon.py')!=active['sha256']:
        _fail('GEOMETRY_ALPHA_PLUGIN_CHANGED')
    for path,first in baselines.items():
        if _historical_source_snapshot(path)!=first:_fail('HISTORICAL_SOURCE_CHANGED')
    return baselines


@contextmanager
def created_geometry_alpha_context(binding, alpha):
    """只在本次认证校准调用内传递几何来源；异常与嵌套均恢复原线程状态。"""
    baselines=_created_geometry_sources(binding,alpha)
    previous=getattr(_CREATED_GEOMETRY_ALPHA,'value',None)
    _CREATED_GEOMETRY_ALPHA.value=(binding,alpha)
    try:yield
    finally:
        _CREATED_GEOMETRY_ALPHA.value=previous
        if _created_geometry_sources(binding,alpha)!=baselines:_fail('HISTORICAL_SOURCE_CHANGED')


_FEEDBACK_GEOMETRY_ALPHA = threading.local()


def _feedback_source_snapshot(path, expected_sha256=None):
    """仅反馈授权的两个结果FileRecord可用8 MiB封口，其余源码仍限2 MiB。"""
    path = _path(str(path));deadline = time.monotonic() + FREEZE_TIMEOUT_SECONDS
    descriptor = None
    try:
        descriptor, chain = _walk(path, deadline)
        before = _signature(os.fstat(descriptor))
        if (not stat.S_ISREG(before['mode']) or before['links'] != 1
                or not 0 < before['size'] <= 8 * 1024 * 1024):
            _fail('HISTORICAL_SOURCE_INVALID')
        digest = _hash(descriptor, before['size'], deadline)
        reopened, later_chain = _walk(path, deadline)
        try:
            if (chain != later_chain or _signature(os.fstat(descriptor)) != before
                    or _signature(os.fstat(reopened)) != before):
                _fail('HISTORICAL_SOURCE_CHANGED')
        finally:
            os.close(reopened)
        if expected_sha256 is not None and digest != expected_sha256:
            _fail('HISTORICAL_SOURCE_CHANGED')
        return {'path':path,'bytes':before['size'],'sha256':digest}, before
    except OSError as error:
        raise ProcessImageError('PROCESS_IMAGE_HISTORICAL_SOURCE_UNAVAILABLE') from error
    finally:
        if descriptor is not None:os.close(descriptor)


class _FeedbackGeometryBaselines(dict):
    def __init__(self):
        super().__init__()
        self.result_paths = set()

    def snapshot(self, path):
        reader = _feedback_source_snapshot if path in self.result_paths else _historical_source_snapshot
        return reader(path)


def _feedback_geometry_sources(binding, alpha):
    """只读认证补充反馈的新授权、当前读取器与本作业的原校准插件。"""
    import copy
    baselines = _FeedbackGeometryBaselines()

    def document(record):
        return _historical_document(record, baselines)

    def freeze(record, *, result=False):
        if (type(record) is not dict or set(record) != {'path','bytes','sha256'}
                or type(record.get('bytes')) is not int or record['bytes'] <= 0):
            _fail('GEOMETRY_FEEDBACK_ALPHA_SOURCE_INVALID')
        reader = _feedback_source_snapshot if result else _historical_source_snapshot
        first = reader(record['path'], record['sha256'])
        if first[0] != record:_fail('HISTORICAL_SOURCE_CHANGED')
        previous = baselines.get(record['path'])
        if previous is not None and previous != first:_fail('HISTORICAL_SOURCE_CHANGED')
        baselines[record['path']] = first
        if result:baselines.result_paths.add(record['path'])
        return first

    def at(path):
        return document(_historical_source_snapshot(path)[0])

    if type(binding) is not dict or set(binding) != {'path','sha256'} or type(alpha) is not dict:
        _fail('GEOMETRY_FEEDBACK_ALPHA_SCOPE_REQUIRED')
    scope = document(binding)
    root = Path(_path(scope.get('output_root')))
    if (binding['path'] != str(root/'scope.json')
            or scope.get('schema') != 'bridge.geometry-feedback-scope/1'
            or scope.get('resource_profile') != 'h21_geometry_feedback_5_900_v1'):
        _fail('GEOMETRY_FEEDBACK_ALPHA_SCOPE_CHANGED')
    authority_record = scope.get('feedback_authority')
    authority_envelope = document(authority_record)
    # 新操作者授权自行验签；不借旧creation grant或旧scope为新源码背书。
    # 惰性导入允许geometry_feedback反向导入process_image，验证器不得进入本context。
    from vfx_pipeline.geometry_feedback import validate_authority, _verified
    authority = validate_authority(authority_record)
    if (type(authority) is not dict or authority_envelope.get('payload') != authority
            or authority.get('schema') != 'bridge.geometry-feedback-authority/1'
            or authority.get('scope_root') != str(root)
            or authority_record['path'] != str(root/'authorization.json')
            or authority.get('task_id') != scope.get('task_id')
            or scope.get('budget') != authority.get('budget')
            or scope.get('execution_authorized') is not True
            or scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or scope.get('authorization') != {'authority':'current_user_instruction','instruction':authority.get('instruction')}):
        _fail('GEOMETRY_FEEDBACK_ALPHA_AUTHORITY_CHANGED')
    execution_path = root/'execution-binding.json'
    execution_envelope = at(execution_path)
    execution = _verified(Path(_path(authority.get('registry'))), execution_path)
    if (type(execution) is not dict or execution_envelope.get('payload') != execution
            or set(execution) != {'schema','authority','preparation','scope'}
            or execution.get('schema') != 'bridge.geometry-feedback-execution-binding/1'
            or execution.get('authority') != authority_record
            or execution.get('scope') != baselines[binding['path']][0]):
        _fail('GEOMETRY_FEEDBACK_ALPHA_EXECUTION_CHANGED')
    prep_record = execution['preparation']
    prep = document(prep_record)
    if (prep_record['path'] != str(root/'geometry-preparation.json')
            or prep.get('schema') != 'bridge.geometry-feedback-preparation/1'
            or prep.get('scope') != binding or prep.get('feedback_authority') != authority_record
            or prep.get('task_id') != authority['task_id']):
        _fail('GEOMETRY_FEEDBACK_ALPHA_PREPARATION_CHANGED')

    # 原结果和会计快照是不可变FileRecord；可追加journal前缀只由新授权验证器核验。
    source_prep = document(authority.get('source_preparation'))
    for field in ('source_result','baseline_result'):
        freeze(authority.get(field), result=True)
    for field in ('source_acceptance','source_job','baseline_acceptance','baseline_job',
                  'source_scope','source_accounting','runtime'):
        document(authority.get(field))
    if authority.get('source_execution_grant') is not None:
        document(authority['source_execution_grant'])
    freeze(authority.get('worker'))
    source_scope = authority['source_scope']
    if (source_prep.get('task_id') != authority['task_id']
            or source_prep.get('scope') != {key:source_scope[key] for key in ('path','sha256')}):
        _fail('GEOMETRY_FEEDBACK_ALPHA_SOURCE_CHANGED')
    formal_record = authority['runtime']
    package = Path(_path(formal_record['path'])).parent
    manifest = document(formal_record)
    plugin = at(package/'plugin.json')
    if (formal_record['path'] != str(package/'runtime-manifest.json')
            or plugin.get('name') != 'bridge-vfx' or plugin.get('version') not in ('0.4.20','0.4.21','0.4.22','0.4.23')
            or manifest.get('schema_version') != 1 or type(manifest.get('files')) is not list
            or hashlib.sha256(_historical_view_canonical(manifest['files'])).hexdigest() != manifest.get('file_manifest_sha256')):
        _fail('GEOMETRY_FEEDBACK_ALPHA_PACKAGE_CHANGED')
    index = {}
    for entry in manifest['files']:
        name = entry.get('path') if type(entry) is dict else None
        if (type(entry) is not dict or set(entry) != {'path','bytes','sha256'}
                or type(name) is not str or not name or name.startswith('/') or '\\' in name
                or any(part in ('','.','..') for part in name.split('/')) or name in index
                or type(entry.get('bytes')) is not int or entry['bytes'] < 0
                or type(entry.get('sha256')) is not str or re.fullmatch('[0-9a-f]{64}',entry['sha256']) is None):
            _fail('GEOMETRY_FEEDBACK_ALPHA_PACKAGE_CHANGED')
        index[name] = entry
    plugin_record = baselines[str(package/'plugin.json')][0]
    if index.get('plugin.json') != {**plugin_record,'path':'plugin.json'}:
        _fail('GEOMETRY_FEEDBACK_ALPHA_PACKAGE_CHANGED')

    plan = authority.get('plan')
    request_id = authority.get('request_id')
    if (type(plan) is not dict or type(plan.get('plan_sha256')) is not str
            or type(request_id) is not str or not request_id):
        _fail('GEOMETRY_FEEDBACK_ALPHA_JOB_CHANGED')
    operation = 'geo_feedback_' + hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
    directory = root/'jobs'/operation
    control = directory/'project/control'
    snapshot_root = control/'snapshot'
    proof = alpha.get('plugin_reuse')
    active = proof.get('active_plugin') if type(proof) is dict else None
    active_path = snapshot_root/'plugins/houdini/_impl/houdini_bridge_addon.py'
    if type(active) is not dict or active.get('path') != str(active_path):
        _fail('GEOMETRY_FEEDBACK_ALPHA_CONTROL_CHANGED')
    modules = _HISTORICAL_SHAPE_MODULES[:4] + (('houdini_bridge.controlled_output','houdini-bridge','controlled_output.py','verify_controlled_output'),)
    module_records = _geometry_alpha_module_sources(package,index,baselines,snapshot_root,modules,
                                                    error_code='GEOMETRY_FEEDBACK_ALPHA_MODULE_CHANGED')

    job = at(directory/'job.json')
    jobprep = at(directory/'job-preparation.json')
    if (job.get('schema') != 'bridge.geometry-job/1' or job.get('task_id') != authority['task_id']
            or job.get('preparation') != prep_record or job.get('feedback_authority') != authority_record
            or job.get('plan') != plan or job.get('revision') != plan.get('revision')
            or job.get('execution_worker') != authority['worker']
            or job.get('operation_id') != operation or job.get('directory') != str(directory)
            or jobprep.get('schema') != 'bridge.geometry-job-preparation/1'
            or jobprep.get('job') != baselines[str(directory/'job.json')][0]
            or jobprep.get('project') != str(directory/'project') or jobprep.get('control') != str(control)):
        _fail('GEOMETRY_FEEDBACK_ALPHA_JOB_CHANGED')
    run = document(jobprep.get('manifest'))
    snapshot = document(jobprep.get('snapshot_manifest'))
    host = run.get('production_host')
    if (jobprep['manifest']['path'] != str(control/'run.json')
            or jobprep['snapshot_manifest']['path'] != str(control/'snapshot-manifest.json')
            or run.get('geometry_task_binding') != prep.get('task_binding')
            or prep.get('task_binding') != source_prep.get('task_binding')
            or type(host) is not dict or host.get('native_scope') != binding
            or (host.get('resource_budget') or {}).get('native_scope') != binding
            or host.get('task_root') != str(root) or host.get('controller_root') != str(control)
            or host.get('geometry_feedback_authority') != authority_record
            or host.get('alpha_calibration') != alpha):
        _fail('GEOMETRY_FEEDBACK_ALPHA_MANIFEST_CHANGED')
    expected = copy.deepcopy(source_prep.get('hosts',{}).get('houdini',{}).get('alpha_calibration'))
    if (type(expected) is not dict or prep.get('hosts',{}).get('houdini',{}).get('alpha_calibration') != expected
            or type(expected.get('plugin_reuse')) is not dict):
        _fail('GEOMETRY_FEEDBACK_ALPHA_SOURCE_CHANGED')
    freeze(expected['plugin_reuse'].get('active_plugin'))
    freeze(expected['plugin_reuse'].get('source_plugin'))
    freeze(expected.get('calibration_source'))
    expected['plugin_reuse']['active_plugin']['path'] = str(active_path)
    if expected != alpha:_fail('GEOMETRY_FEEDBACK_ALPHA_SOURCE_CHANGED')
    freeze(active)
    rows = snapshot.get('files')
    if type(rows) is not list or not rows:_fail('GEOMETRY_FEEDBACK_ALPHA_MANIFEST_CHANGED')
    snapshot_index = {}
    for row in rows:
        name = row.get('path') if type(row) is dict else None
        if (type(row) is not dict or set(row) != {'path','sha256'} or type(name) is not str
                or not name or name.startswith('/') or '\\' in name
                or any(part in ('','.','..') for part in name.split('/')) or name in snapshot_index
                or type(row.get('sha256')) is not str or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None):
            _fail('GEOMETRY_FEEDBACK_ALPHA_MANIFEST_CHANGED')
        snapshot_index[name] = row['sha256']
    for relative, expected in module_records.items():
        if snapshot_index.get(relative) != expected['sha256']:
            _fail('GEOMETRY_FEEDBACK_ALPHA_MODULE_CHANGED')
        freeze({**expected,'path':str(snapshot_root/relative)})
    if snapshot_index.get('plugins/houdini/_impl/houdini_bridge_addon.py') != active['sha256']:
        _fail('GEOMETRY_FEEDBACK_ALPHA_PLUGIN_CHANGED')
    for path, first in baselines.items():
        if baselines.snapshot(path) != first:_fail('HISTORICAL_SOURCE_CHANGED')
    return baselines


@contextmanager
def feedback_geometry_alpha_context(binding, alpha):
    """仅本线程本次历史校准复用新反馈授权；首末封口并恢复嵌套状态。"""
    import copy
    original_binding, original_alpha = binding, alpha
    binding, alpha = copy.deepcopy((binding, alpha))
    baselines = _feedback_geometry_sources(binding, alpha)
    previous = getattr(_FEEDBACK_GEOMETRY_ALPHA,'value',None)
    _FEEDBACK_GEOMETRY_ALPHA.value = (binding, alpha)
    try:
        yield
    finally:
        _FEEDBACK_GEOMETRY_ALPHA.value = previous
        if (_feedback_geometry_sources(binding, alpha) != baselines
                or original_binding != binding or original_alpha != alpha):
            _fail('HISTORICAL_SOURCE_CHANGED')


def _historical_package_sources(*, shape_scope_binding=None, _verifier_source=None):
    """0410/0411保持原合同；0412读取器与旧生产闭包分别精确认证。"""
    import json
    feedback = getattr(_FEEDBACK_GEOMETRY_ALPHA,'value',None)
    if feedback is not None and shape_scope_binding is None:
        return _feedback_geometry_sources(*feedback)
    created = getattr(_CREATED_GEOMETRY_ALPHA,'value',None)
    if created is not None and shape_scope_binding is None:
        return _created_geometry_sources(*created)
    runtime = Path(__file__).resolve().parents[4]
    if runtime.name == 'runtime':
        package = runtime.parent
    else:
        # 控制快照没有plugin/index；只从外部scope摘要确定正式包，稍后逐源核签名view。
        if runtime.name != 'snapshot' or shape_scope_binding is None:
            _fail('HISTORICAL_RUNTIME_PACKAGE_REQUIRED')
        _, authority = _historical_view_bootstrap(shape_scope_binding,{})
        package = Path(_path(authority['runtime_requirements']['formal_root']))
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:_fail('HISTORICAL_PACKAGE_INVALID')
            value[key] = item
        return value
    result = {}
    for name in ('plugin.json', 'runtime-manifest.json'):
        path = package / name;result[str(path)] = _historical_source_snapshot(path)
    # 首次读取已记录身份；下面的JSON读取及最终退出都必须与同一首封一致。
    plugin = json.loads((package/'plugin.json').read_bytes(), object_pairs_hook=unique)
    manifest = json.loads((package/'runtime-manifest.json').read_bytes(), object_pairs_hook=unique)
    if (plugin.get('name') != 'bridge-vfx' or plugin.get('version') not in ('0.4.10', '0.4.11') + _HISTORICAL_READER_VERSIONS
            or manifest.get('schema_version') != 1 or type(manifest.get('files')) is not list):
        _fail('HISTORICAL_PACKAGE_INVALID')
    entries = manifest['files']
    raw = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(raw).hexdigest() != manifest.get('file_manifest_sha256'):
        _fail('HISTORICAL_PACKAGE_INVALID')
    index = {}
    for item in entries:
        if type(item) is not dict or type(item.get('path')) is not str or item['path'] in index:
            _fail('HISTORICAL_PACKAGE_INVALID')
        index[item['path']] = item
    if plugin['version'] == '0.4.11':
        return _historical_shape_package_sources(package, index, result, shape_scope_binding, _verifier_source)
    if plugin['version'] in _HISTORICAL_READER_VERSIONS:
        # 新读取器只从自身正式runtime加载；旧snapshot仍须走原0411签名view。
        if runtime != package/'runtime':_fail('HISTORICAL_RUNTIME_SOURCE_MISMATCH')
        if shape_scope_binding is not None:
            return _historical_shape_package_sources(package,index,result,shape_scope_binding,_verifier_source)
        return _historical_reader_sources(package,index,result,_HISTORICAL_SHAPE_MODULES[:3])
    if shape_scope_binding is not None:
        _fail('HISTORICAL_SHAPE_RUNTIME_REQUIRED')
    relatives = ('runtime/packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py',
                 'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py',
                 'runtime/packages/houdini-bridge/src/houdini_bridge/alpha_reuse.py')
    for name in relatives:
        entry = index.get(name)
        if (entry is None or set(entry) != {'path', 'bytes', 'sha256'}
                or type(entry.get('bytes')) is not int or entry['bytes'] <= 0
                or type(entry.get('sha256')) is not str
                or re.fullmatch('[0-9a-f]{64}', entry['sha256']) is None):
            _fail('HISTORICAL_PACKAGE_INVALID')
        path = package/name;record, stamp = _historical_source_snapshot(path, entry['sha256'])
        if record['bytes'] != entry['bytes']:
            _fail('HISTORICAL_PACKAGE_INVALID')
        result[str(path)] = record, stamp
    # 实际加载的模块不得来自另一个目录或另一份同名运行时。
    for name, relative in (('dcc_task_runtime.process_image',relatives[0]),
                           ('dcc_task_runtime.alpha_calibration',relatives[1]),
                           ('houdini_bridge.alpha_reuse',relatives[2])):
        module = sys.modules.get(name)
        if module is not None and Path(module.__file__).resolve() != package/relative:
            _fail('HISTORICAL_RUNTIME_SOURCE_MISMATCH')
    for path, baseline in result.items():
        if _historical_source_snapshot(path) != baseline:_fail('HISTORICAL_SOURCE_CHANGED')
    return result


@contextmanager
def _historical_validation_sources(verifier_source, *, shape_scope_binding=None):
    """同次历史验源的固定小闭包；正常和异常退出都核同一首封，不缓存。"""
    if (type(verifier_source) is not dict or set(verifier_source) != {'path','bytes','sha256'}
            or type(verifier_source.get('bytes')) is not int or verifier_source['bytes'] <= 0):
        _fail('HISTORICAL_VERIFIER_SOURCE_REQUIRED')
    baselines = (_historical_package_sources() if shape_scope_binding is None else
                 _historical_package_sources(shape_scope_binding=shape_scope_binding, _verifier_source=verifier_source))
    path = verifier_source['path'];snapshot = _historical_source_snapshot(path, verifier_source['sha256'])
    if snapshot[0] != verifier_source:_fail('HISTORICAL_SOURCE_CHANGED')
    if path in baselines and baselines[path] != snapshot:_fail('HISTORICAL_SOURCE_CHANGED')
    baselines[path] = snapshot
    try:
        yield
    finally:
        reader = baselines.snapshot if type(baselines) is _FeedbackGeometryBaselines else _historical_source_snapshot
        for path, baseline in baselines.items():
            if reader(path) != baseline:_fail('HISTORICAL_SOURCE_CHANGED')

def _tool_diagnostic(argv, process, output, stderr_complete, stage, error, *, timing):
    # Raw stderr is hex encoded so malformed UTF-8 is preserved without a
    # second decoding failure. Byte counts describe data actually read; a
    # timeout or stream cap cannot establish the unread stream's total size.
    remaining = MAX_DIAGNOSTIC_ARGV_BYTES
    arguments = []
    argv_truncated = False
    for item in argv[:16]:
        raw = str(item).encode('utf-8', errors='replace')
        arguments.append(raw[:remaining].decode('utf-8', errors='replace'))
        argv_truncated = argv_truncated or len(raw) > remaining
        remaining = max(0, remaining - len(raw))
    argv_truncated = argv_truncated or len(argv) > 16
    stderr = output[1]
    return {'schema': 'bridge.process-image.tool-diagnostic/1',
            'reason': str(error), 'stage': stage, 'tool_argv': arguments,
            'tool_argv_truncated': argv_truncated,
            'tool_pid': None if process is None else process.pid,
            'timing': timing,
            'exit_code': None if process is None else process.returncode,
            'stderr_hex': bytes(stderr[:MAX_DIAGNOSTIC_STDERR_BYTES]).hex(),
            'stderr_observed_bytes': len(stderr),
            'stderr_truncated': len(stderr) > MAX_DIAGNOSTIC_STDERR_BYTES,
            'stderr_complete': stderr_complete,
            'stdout_observed_bytes': len(output[0]),
            'os_errno': getattr(error.__cause__, 'errno', None)}


def _sample_header_command(argv):
    """只有既定头信息命令可分配较多局部时间；观察整体截止仍为16秒。"""
    return (len(argv) == 6 and argv[0] == '/usr/bin/sample'
            and argv[2:] == ['1', '1000', '-file', '/dev/stdout']
            and re.fullmatch(r'[1-9][0-9]{0,9}', argv[1]) is not None
            and int(argv[1]) <= 0x7fffffff)


def _tool_timeout(argv):
    return SAMPLE_HEADER_TOOL_TIMEOUT_SECONDS if _sample_header_command(argv) else TOOL_TIMEOUT_SECONDS


def _sample_header_progress(argv, data):
    """Accept only the pinned header command's observed successful progress."""
    if (len(argv)!=6 or argv[0]!='/usr/bin/sample'
            or argv[2:]!=['1','1000','-file','/dev/stdout']
            or re.fullmatch(r'[1-9][0-9]{0,9}',argv[1]) is None
            or int(argv[1])>0x7fffffff):
        return False
    pid=argv[1]
    return data==(f'Sampling process {pid} for 1 second with 1000 milliseconds of run time between samples\n'
                  'Sampling completed, processing symbols...\n'
                  f'Sample analysis of process {pid} written to file /dev/stdout\n').encode()


def _run_tool(argv, deadline):
    """Drain both pipes with byte caps; never communicate() unbounded output."""
    began = time.monotonic()
    tool_limit = _tool_timeout(argv)
    end = min(deadline, began + tool_limit)
    phase_began = began
    spawn_seconds = None
    process = None
    completed = False
    failure = None
    output = [bytearray(), bytearray()]
    stderr_complete = False
    stage = 'before_spawn'
    observer=getattr(_TOOL_TRACE,'observer',None);trace_token=None

    def diagnostic(error, phase=None):
        now = time.monotonic()
        return _tool_diagnostic(argv, process, output, stderr_complete, phase or stage, error,
            timing={'elapsed_seconds': max(0., now-began),
                    'phase_seconds': max(0., now-phase_began),
                    'spawn_seconds': spawn_seconds,
                    'tool_limit_seconds': tool_limit,
                    'outer_budget_seconds': max(0., deadline-began),
                    'effective_budget_seconds': max(0., end-began),
                    'deadline_source': 'tool' if began+tool_limit <= deadline else 'observation'})

    try:
        _remaining(end)
        stage = 'spawn'; phase_began = time.monotonic()
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=_ENV, start_new_session=True)
        spawn_seconds = time.monotonic()-phase_began
        trace_token=_diagnostic_callback(observer,'spawned',process,argv,began,end)
        stage = 'read_pipes'; phase_began = time.monotonic()
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate((process.stdout, process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map():
                for key, _ in selector.select(_remaining(end)):
                    index = key.data
                    limit = MAX_STDOUT_BYTES if index == 0 else MAX_STDERR_BYTES
                    chunk = os.read(key.fileobj.fileno(), min(65536, limit - len(output[index]) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        if index == 1:
                            stderr_complete = True
                    else:
                        output[index].extend(chunk)
                        if len(output[index]) > limit:
                            _fail('TOOL_OUTPUT_LIMIT')
            stage = 'wait'; phase_began = time.monotonic()
            process.wait(timeout=_remaining(end))
        stage = 'exit_status'; phase_began = time.monotonic()
        if process.returncode != 0 or (output[1] and not _sample_header_progress(argv, output[1])):
            _fail('TOOL_FAILED')
        _remaining(end)
        completed = True
        return bytes(output[0])
    except (ProcessImageError, subprocess.TimeoutExpired, TimeoutError, OSError) as cause:
        if isinstance(cause, ProcessImageError):
            error = cause
        else:
            error = ProcessImageError('PROCESS_IMAGE_' + (
                'TIMEOUT' if isinstance(cause, (subprocess.TimeoutExpired, TimeoutError)) else 'TOOL_UNAVAILABLE'))
            error.__cause__ = cause
        error.diagnostic = diagnostic(error)
        failure = error
        if error is cause:
            raise
        raise error from cause
    finally:
        if process is not None:
            phase_began = time.monotonic()
            # Cleanup failures cannot replace the primary tool failure. A
            # failed one-second wait leaves leader_reaped explicitly false;
            # this is diagnostic evidence, never a stopped-process receipt.
            cleanup = {'leader_reaped': False, 'errors': []}
            cleanup_cause = None
            def cleanup_failed(phase, cause):
                nonlocal cleanup_cause
                if cleanup_cause is None:
                    cleanup_cause = cause
                number = getattr(cause, 'errno', None)
                cleanup['errors'].append({'phase': phase,
                    'exception_type': type(cause).__name__[:64],
                    'errno': number if type(number) is int and 0 <= number <= 2**31 else None})
            # Tool groups are created by this call, never the observed process.
            if not completed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception as cause:
                    cleanup_failed('kill_group', cause)
            try:
                if process.poll() is None:
                    process.wait(timeout=1)
                cleanup['leader_reaped'] = process.returncode is not None
            except Exception as cause:
                cleanup_failed('wait', cause)
            for name in ('stdout', 'stderr'):
                try:
                    getattr(process, name).close()
                except Exception as cause:
                    cleanup_failed(name + '_close', cause)
            cleanup['leader_exit_code'] = process.returncode
            if failure is not None:
                failure.diagnostic['cleanup'] = cleanup
            if cleanup['errors']:
                if failure is None and sys.exc_info()[0] is None:
                    # Even an otherwise successful tool is refused if cleanup
                    # cannot be completed. Do not silently return its output.
                    error = ProcessImageError('PROCESS_IMAGE_TOOL_CLEANUP_FAILED')
                    error.__cause__ = cleanup_cause
                    error.diagnostic = diagnostic(error, 'cleanup')
                    error.diagnostic['cleanup'] = cleanup
                    _diagnostic_callback(observer,'finished',trace_token,process.returncode,error.diagnostic)
                    raise error from cleanup_cause
            _diagnostic_callback(observer,'finished',trace_token,process.returncode,
                failure.diagnostic if failure is not None else None)


def _text(data):
    try:
        return data.decode('utf-8', errors='strict')
    except UnicodeError as error:
        raise ProcessImageError('PROCESS_IMAGE_INVALID_TOOL_TEXT') from error


def _ps(pid, deadline):
    text = _text(_run_tool(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,lstart=,stat='], deadline))
    match = re.fullmatch(r'\s*(\d+)\s+(\d+)\s+([A-Z][a-z]{2} [A-Z][a-z]{2}\s+\d{1,2} '
                         r'\d{2}:\d{2}:\d{2} \d{4})\s+([A-Za-z+<>=-]+)\s*', text)
    if not match or int(match[1]) != pid or match[4][0] in 'ZX':
        _fail('INVALID_PS')
    parent = int(match[2]); _pid(parent, zero=True)
    try:
        birth = datetime.strptime(match[3], '%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ProcessImageError('PROCESS_IMAGE_INVALID_BIRTH') from error
    return parent, int(birth.timestamp())


def _birth(value):
    if (type(value) is not str or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3,6} [+-]\d{4}', value)):
        _fail('INVALID_BIRTH')
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f %z')
    except ValueError as error:
        raise ProcessImageError('PROCESS_IMAGE_INVALID_BIRTH') from error


def _vmmap(pid, deadline):
    # 显式策略只选择采集命令；头字段、地址映射及原有身份核验不变。
    policy = getattr(_TOOL_TRACE, 'collector_policy', None)
    legacy = policy is not None and policy['policy'] == LEGACY_COLLECTOR_POLICY
    fork_corpse = policy is not None and policy['policy'] == FORK_CORPSE_COLLECTOR_POLICY
    argv = (['/usr/bin/vmmap', '-forkCorpse', '-w', '-interleaved', str(pid)] if fork_corpse else
            ['/usr/bin/vmmap', '-w', '-interleaved', '-summary', str(pid)] if legacy else
            ['/usr/bin/sample', str(pid), '1', '1000', '-file', '/dev/stdout'])
    text = _text(_run_tool(argv, deadline))
    fields = {}
    names = ('Process', 'Parent Process', 'Load Address', 'Launch Time', 'Target Type')
    lines = text.splitlines()
    for line in lines:
        for name in names:
            if line.startswith(name + ':'):
                if name in fields:
                    _fail('AMBIGUOUS_VMMAP')
                fields[name] = line.split(':', 1)[1].strip()
    # vmmap may automatically inspect a corpse snapshot of a *live* task.
    # Liveness and unchanged birth/PPID are independently bracketed by ps/lsof.
    if set(fields) != set(names) or fields['Target Type'] not in ('live task', 'corpse'):
        _fail('INVALID_VMMAP')
    def process_number(name):
        match = re.fullmatch(r'.+ \[(\d+)\]', fields[name])
        if not match:
            _fail('INVALID_VMMAP')
        return int(match[1])
    if process_number('Process') != pid:
        _fail('PID_MISMATCH')
    parent = process_number('Parent Process'); _pid(parent, zero=True)
    address = fields['Load Address']
    if not re.fullmatch(r'0x[0-9a-fA-F]{1,16}', address) or int(address, 16) == 0:
        _fail('INVALID_LOAD_ADDRESS')
    _birth(fields['Launch Time'])
    region_argv = (['/usr/bin/vmmap', '-forkCorpse', '-w', '-interleaved', str(pid), address]
                   if fork_corpse else ['/usr/bin/vmmap', '-w', '-interleaved', str(pid), address])
    regions = _text(_run_tool(region_argv, deadline))
    candidates = []
    for line in regions.splitlines():
        match = re.fullmatch(r'[ \t]*(?:--->[ \t]+)?__TEXT\s+([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+'
                             r'\[[^\]]+\]\s+r-x/[r-][w-][x-]\s+SM=[A-Z]+\s+(/.*)', line)
        if match and int(match[1], 16) == int(address, 16):
            if int(match[2], 16) <= int(address, 16):
                _fail('INVALID_VMMAP')
            candidates.append(_path(match[3]))
    if len(candidates) != 1:
        _fail('AMBIGUOUS_MAIN_IMAGE')
    return {'parent_pid': parent, 'birth': fields['Launch Time'],
            'load_address': hex(int(address, 16)), 'path': candidates[0]}


def _lsof(pid, path, deadline):
    data = _run_tool(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid), '-d', 'txt',
                      '-F', 'pRfDint0'], deadline)
    lines = data.split(b'\n')
    if not lines or lines[-1] != b'':
        _fail('INVALID_LSOF')
    records = []
    for line in lines[:-1]:
        values = line.split(b'\0')
        if values[-1] != b'' or not all(values[:-1]):
            _fail('INVALID_LSOF')
        record = {}
        for field in values[:-1]:
            key, value = chr(field[0]), _text(field[1:])
            if key in record:
                _fail('AMBIGUOUS_LSOF')
            record[key] = value
        records.append(record)
    if not records:
        _fail('INVALID_LSOF')
    _keys(records[0], {'p', 'R'})
    if records[0]['p'] != str(pid) or not re.fullmatch(r'\d+', records[0]['R']):
        _fail('PID_MISMATCH')
    parent = int(records[0]['R']); _pid(parent, zero=True)
    matches = []
    for record in records[1:]:
        _keys(record, {'f', 't', 'D', 'i', 'n'})
        if (record['f'] != 'txt' or record['t'] != 'REG'
                or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}', record['D'])
                or not re.fullmatch(r'\d{1,20}', record['i'])):
            _fail('INVALID_LSOF')
        if record['n'] == path:
            matches.append((int(record['D'], 16), int(record['i'])))
    if len(matches) != 1:
        _fail('AMBIGUOUS_IMAGE_VNODE')
    return parent, matches[0]


@contextmanager
def collector_policy_scope(policy):
    validate_collector_policy(policy)
    previous = getattr(_TOOL_TRACE, 'collector_policy', None)
    _TOOL_TRACE.collector_policy = policy
    try:
        yield
    finally:
        _TOOL_TRACE.collector_policy = previous


def _observe(pid, deadline, read_budget=None, *, before_image=None, collector_policy=None):
    deadline = min(deadline, time.monotonic() + OBSERVE_TIMEOUT_SECONDS)
    previous = getattr(_TOOL_TRACE, 'collector_policy', None)
    collector_policy = previous if collector_policy is None else collector_policy
    if collector_policy is not None:
        validate_collector_policy(collector_policy)
        check_collector_tools(collector_policy, deadline)
    _TOOL_TRACE.collector_policy = collector_policy
    try:
        return _observe_image(pid, deadline, read_budget, before_image=before_image)
    finally:
        _TOOL_TRACE.collector_policy = previous


def _observe_image(pid, deadline, read_budget=None, *, before_image=None):
    deadline = min(deadline, time.monotonic() + OBSERVE_TIMEOUT_SECONDS)
    parent, start = _ps(pid, deadline)
    if before_image is not None:
        before_image(deadline)
        _remaining(deadline)
    first = _vmmap(pid, deadline)
    if first['parent_pid'] != parent or int(_birth(first['birth']).timestamp()) != start:
        _fail('PROCESS_CHANGED')
    vnode = _lsof(pid, first['path'], deadline)
    with _opened_image(first['path'], deadline) as (descriptor, information):
        if vnode != (parent, (information['device'], information['inode'])):
            _fail('IMAGE_VNODE_MISMATCH')
        image = {'path': first['path'], 'stat': information,
                 'sha256': _hash(descriptor, information['size'], deadline, read_budget)}
        if (_lsof(pid, first['path'], deadline) != vnode or _vmmap(pid, deadline) != first
                or _ps(pid, deadline) != (parent, start)):
            _fail('PROCESS_CHANGED')
    _remaining(deadline)
    return {'schema': OBSERVATION_SCHEMA, 'platform': 'darwin', 'pid': pid,
            'parent_pid': parent, 'birth': first['birth'],
            'load_address': first['load_address'], 'image': image}


def observe_process(pid, *, read_budget=None):
    """Observe a live PID's OS birth, parent, main load address and file identity.

    Returns {schema, platform: 'darwin', pid, parent_pid, birth, load_address,
    image: {path, sha256, stat}}. birth is the header's timezone-qualified Launch Time.
    ps supplies only PID/PPID/start-time cross-checks, never an executable name.
    """
    _supported(); _pid(pid)
    policy = _authenticated_collector_policy()
    options = {} if policy is None else {'collector_policy': policy}
    return _observe(pid, time.monotonic() + OBSERVE_TIMEOUT_SECONDS, read_budget, **options)


def _validate_observation(value):
    _keys(value, {'schema', 'platform', 'pid', 'parent_pid', 'birth', 'load_address', 'image'})
    if not _tag(value['schema'], OBSERVATION_SCHEMA) or not _tag(value['platform'], 'darwin'):
        _fail('INVALID_OBSERVATION')
    _pid(value['pid']); _pid(value['parent_pid'], zero=True)
    if value['pid'] == value['parent_pid']:
        _fail('ANCESTRY_CYCLE')
    _birth(value['birth'])
    address = value['load_address']
    if (type(address) is not str or not re.fullmatch(r'0x[0-9a-f]{1,16}', address)
            or int(address, 16) == 0 or hex(int(address, 16)) != address):
        _fail('INVALID_LOAD_ADDRESS')
    _validate_image(value['image'])


def capture_ancestry(expected_executable, host_anchor, pid=None, *, read_budget=None):
    """Capture the current process through a strict, exact observed host ancestor.

    Explicit pid, if present, must equal os.getpid(). The anchor must come from
    observe_process and be retained by the trusted host/controller. Both complete
    chains are sampled, first child-to-host then host-to-child, under one deadline.
    """
    _supported(); _validate_expected(expected_executable); _validate_observation(host_anchor)
    pid = os.getpid() if pid is None else pid
    _pid(pid)
    if pid != os.getpid():
        _fail('CURRENT_PROCESS_REQUIRED')
    if pid == host_anchor['pid']:
        _fail('STRICT_ANCESTOR_REQUIRED')
    deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS
    policy = _authenticated_collector_policy()
    options = {} if policy is None else {'collector_policy': policy}
    chain = []
    visited = set()
    while len(chain) < MAX_ANCESTRY_DEPTH:
        if pid in visited:
            _fail('ANCESTRY_CYCLE')
        visited.add(pid)
        current = _observe(pid, deadline, read_budget, **options)
        if not chain and current['image'] != expected_executable['image']:
            _fail('EXECUTABLE_MISMATCH')
        chain.append(current)
        if pid == host_anchor['pid']:
            if current != host_anchor:
                _fail('HOST_ANCHOR_MISMATCH')
            break
        pid = current['parent_pid']
        if pid == 0:
            _fail('HOST_NOT_ANCESTOR')
    else:
        _fail('ANCESTRY_DEPTH_LIMIT')
    rechecked = []
    for prior in reversed(chain):
        current = _observe(prior['pid'], deadline, read_budget, **options)
        if current != prior:
            _fail('PROCESS_CHANGED')
        rechecked.append(current)
    proof = {'schema': PROOF_SCHEMA, 'platform': 'darwin',
             'expected_executable': expected_executable, 'host_anchor': host_anchor,
             'chain': chain, 'rechecked_chain': list(reversed(rechecked))}
    validate_process_proof(proof, expected_executable, host_anchor)
    _remaining(deadline)
    return proof


def validate_process_proof(proof, expected_executable, host_anchor):
    """Offline structure/binding checks; returns None, raises ProcessImageError.

    This neither authenticates unsigned JSON nor observes a current OS process.
    The expected identity and anchor are external trusted inputs, never values
    adopted from proof. Authenticate the captured proof before relying on it.
    """
    _supported(); _validate_expected(expected_executable); _validate_observation(host_anchor)
    _keys(proof, {'schema', 'platform', 'expected_executable', 'host_anchor', 'chain', 'rechecked_chain'})
    if not _tag(proof['schema'], PROOF_SCHEMA) or not _tag(proof['platform'], 'darwin'):
        _fail('INVALID_PROOF')
    _validate_expected(proof['expected_executable']); _validate_observation(proof['host_anchor'])
    if proof['expected_executable'] != expected_executable or proof['host_anchor'] != host_anchor:
        _fail('TRUSTED_BINDING_MISMATCH')
    chain, rechecked = proof['chain'], proof['rechecked_chain']
    if (type(chain) is not list or type(rechecked) is not list
            or not 2 <= len(chain) <= MAX_ANCESTRY_DEPTH or len(rechecked) != len(chain)):
        _fail('INVALID_CHAIN')
    visited = set()
    for index, (observation, again) in enumerate(zip(chain, rechecked)):
        _validate_observation(observation); _validate_observation(again)
        if observation != again:
            _fail('PROCESS_CHANGED')
        if observation['pid'] in visited:
            _fail('ANCESTRY_CYCLE')
        visited.add(observation['pid'])
        if index:
            child = chain[index - 1]
            if (child['parent_pid'] != observation['pid']
                    or _birth(child['birth']) < _birth(observation['birth'])):
                _fail('INVALID_ANCESTRY')
    if chain[0]['image'] != expected_executable['image']:
        _fail('EXECUTABLE_MISMATCH')
    if chain[-1] != host_anchor:
        _fail('HOST_ANCHOR_MISMATCH')
