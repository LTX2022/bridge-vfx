"""只复用已停止历史来源的认证观察；当前执行预算始终由原NativeScope实时核验。"""
from __future__ import annotations
import copy,json,os,stat,threading
from collections import OrderedDict
from pathlib import Path
from .official_karma_observation import checked_bytes
from .official_karma import canonical_sha256

_MAX_ENTRIES=8192
_MAX_BYTES=2*1024*1024*1024
_CACHE_LIMIT=4
_CACHE=OrderedDict()
_GUARD=threading.Lock()

class _NotCacheable(Exception):pass

def _stamp(path,strict_directory=False):
    """不跟随末级链接；父目录也各自列入依赖，包含ctime以识别同大小改写。"""
    s=os.stat(path,follow_symlinks=False)
    if not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):raise _NotCacheable()
    if stat.S_ISDIR(s.st_mode) and not strict_directory:return (s.st_dev,s.st_ino,s.st_mode,0,0,0,0)
    return (s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)

def _stable(stamps):
    try:return all(_stamp(name,value[1])==value[0] for name,value in stamps.items())
    except (OSError,ValueError,_NotCacheable):return False

def _dependencies(configuration):
    """限定实际来源/冻结包/历史账本；不遍历共享输出根或当前执行目录。"""
    from dcc_task_runtime.native_scope import NativeScope
    source=NativeScope(configuration['native_scope'])
    observation=NativeScope(configuration.get('observation_scope',configuration['native_scope']))
    snapshots=[source.snapshot(),observation.snapshot()]
    active=os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')
    if active:
        try:active=json.loads(active)
        except ValueError:raise _NotCacheable()
        if active in (source.binding,observation.binding):raise _NotCacheable()
    if any(any(t.get('stopped_at') is None for t in s['tickets']) for s in snapshots):raise _NotCacheable()
    if source.root==observation.root or observation.root.is_relative_to(source.root):raise _NotCacheable()
    paths=set();strict_directories=set();budget=[400000]
    def add(raw,tree=False):
        p=Path(raw)
        if not p.is_absolute() or p!=p.resolve() or any(x.is_symlink() for x in (p,*p.parents)):raise _NotCacheable()
        if not p.exists():raise _NotCacheable()
        paths.add(str(p));paths.update(str(x) for x in p.parents)
        if tree:
            if p.is_dir():strict_directories.add(str(p))
            for x in p.rglob('*'):
                if len(paths)>=_MAX_ENTRIES:raise _NotCacheable()
                if x.is_symlink():raise _NotCacheable()
                paths.add(str(x))
                if x.is_dir():strict_directories.add(str(x))
        if len(paths)>_MAX_ENTRIES:raise _NotCacheable()
    seen_text=set()
    def walk(value):
        budget[0]-=1
        if budget[0]<0:raise _NotCacheable()
        if isinstance(value,dict):
            for k,v in value.items():walk(k);walk(v)
        elif isinstance(value,(list,tuple)):
            for v in value:walk(v)
        elif isinstance(value,str) and value.startswith('/') and len(value)<4096 and '\0' not in value and '\n' not in value and value not in seen_text:
            seen_text.add(value)
            try:
                p=Path(value)
                if p.is_file():add(p)
            except OSError:pass
    walk(configuration)
    # 原观察范围是独立只读旧根，里面含全部冻结源码、原观测与签名原件。
    add(observation.root,tree=True)
    for observed_file in observation.root.rglob('observation.json'):
        if observed_file.stat().st_size>8*1024*1024:raise _NotCacheable()
        walk(json.loads(observed_file.read_text()))
    case=observation.scope['official_case'];walk(case);walk(observation.scope.get('hosts',{}))
    if isinstance(case.get('static_review'),dict):walk(json.loads(checked_bytes(case['static_review'])))
    sealed=Path(configuration['sealed_observation']['directory'])/'official-sealed-observation.json'
    payload=json.loads(sealed.read_text())['payload'];walk(payload)
    if isinstance(payload.get('observation'),dict):walk(json.loads(checked_bytes(payload['observation'])))
    variant=json.loads(checked_bytes(configuration['case_variant']));walk(variant)
    contract=json.loads(checked_bytes(variant['contract']));walk(contract)
    walk(json.loads(checked_bytes(variant['observation'])))
    old_directories={t['directory'] for t in snapshots[0]['tickets']}
    for directory in (variant['directory'],variant['reference_render']['directory']):
        if directory not in old_directories:raise _NotCacheable()
        add(directory,tree=True)
    # NativeScope已验证的静态闭包与每层历史账本/停止凭据一并绑定。
    for initial,snapshot in ((source,snapshots[0]),(observation,snapshots[1])):
        current=initial;seen=set()
        while current is not None:
            if str(current.path) in seen:raise _NotCacheable()
            seen.add(str(current.path))
            for raw in current._setup_file_stats:add(raw)
            for attr in ('path','state_path','key_path','journal_path','anchor_path','_continuation_claim_path'):
                raw=getattr(current,attr,None)
                if raw is not None:add(raw)
            current=getattr(current,'_continuation_previous',None)
        for ticket in snapshot['tickets']:add(ticket['directory'],tree=True)
    # 当前未隔离的验证器运行库也须保持；不能因暖命中忽略其漂移。
    import importlib
    from .official_karma_templates import SOURCE_RUNTIME_MODULES
    for name in SOURCE_RUNTIME_MODULES:
        add(Path(importlib.import_module('dcc_task_runtime.'+name).__file__))
    for name in ('official_karma','official_karma_native','official_karma_observation','official_karma_templates','official_karma_scene','official_case_variant','case_source_cache'):
        add(Path(importlib.import_module('houdini_bridge.'+name).__file__))
    result={name:(_stamp(name,name in strict_directories),name in strict_directories) for name in sorted(paths,key=lambda x:(len(Path(x).parts),x))}
    if len(result)>_MAX_ENTRIES or sum(v[0][3] for v in result.values() if stat.S_ISREG(v[0][2]))>_MAX_BYTES:raise _NotCacheable()
    return result

def _discard(key,entry=None):
    with _GUARD:
        if entry is None or _CACHE.get(key) is entry:_CACHE.pop(key,None)

def _historical_environment(configuration):
    """暖命中也不能把已切换成当前执行范围的来源当历史缓存。"""
    raw=os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')
    if not raw:return True
    try:active=json.loads(raw)
    except (TypeError,ValueError):return False
    if (type(active) is not dict or set(active)!={'path','sha256'}
            or type(active['path']) is not str or not active['path'].startswith('/')
            or type(active['sha256']) is not str or len(active['sha256'])!=64
            or any(x not in '0123456789abcdef' for x in active['sha256'])):return False
    sources=[configuration.get('native_scope',{}),configuration.get('observation_scope',configuration.get('native_scope',{}))]
    return all(active['path']!=source.get('path') for source in sources)

def cached_case_observation(configuration,version,loader):
    """完整验证前后保持同一依赖身份才存入；任何不确定均回原验证。"""
    key=canonical_sha256({'configuration':configuration,'version':version})
    if not _historical_environment(configuration):
        _discard(key);return loader(configuration,version)
    with _GUARD:
        entry=_CACHE.get(key)
        if entry is not None:_CACHE.move_to_end(key)
    if entry is not None:
        if _stable(entry['dependencies']):
            value=copy.deepcopy(entry['value'])
            if _stable(entry['dependencies']) and _historical_environment(configuration):return value
        _discard(key,entry)
    try:before=_dependencies(configuration)
    except (OSError,ValueError,KeyError,TypeError,_NotCacheable):return loader(configuration,version)
    value=loader(configuration,version)
    # 再发现一遍，新增/消失依赖和目录清单变化均不获缓存接收。
    try:after=_dependencies(configuration)
    except (OSError,ValueError,KeyError,TypeError,_NotCacheable):return loader(configuration,version)
    if before!=after or not _stable(before) or not _historical_environment(configuration):return loader(configuration,version)
    entry={'dependencies':before,'value':copy.deepcopy(value)}
    with _GUARD:
        _CACHE[key]=entry;_CACHE.move_to_end(key)
        while len(_CACHE)>_CACHE_LIMIT:_CACHE.popitem(last=False)
    return value
