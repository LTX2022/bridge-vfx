"""几何任务的显式安装runtime续接；保留原准备和零原生启动失败来源。"""
from __future__ import annotations
import hashlib
import hmac
import types
import json
import os
from pathlib import Path
import re

from dcc_task_runtime.native_scope import NativeScope, GEOMETRY_RESOURCE_PROFILE
from dcc_task_runtime.platform_support import _owned_path, process_status
from houdini_bridge.official_karma_observation import file_record, checked_bytes

_SCHEMA = 'bridge.geometry-runtime-continuation/1'
_DOMAIN = b'bridge.geometry-runtime-continuation/1\x00'
_BASELINE = 'docs/official-baselines/karma/frozen-scene-v2.json'
_BASELINE_SHA = '59a9b54e5d201345dc7ac95487bb668a5c66f3ce8f2b573c4a7ccb209b9f56b6'
_CHANGED = {'runtime/tools/build_agent_plugin.py', 'runtime/tools/release_layout.json',
            'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_session.py'}
_ADDED = {'runtime/'+_BASELINE, 'runtime/tools/repair_geometry_preparation.py',
          'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_runtime_binding.py'}
_ARCHIVE = ('job.json','error.json','controller-launch-intent.json','controller-started.json',
            'controller-error.log','geometry-state.json')


def _fail():
    raise ValueError('GEOMETRY_RUNTIME_CONTINUATION_INVALID')


def _path(raw):
    path = Path(raw)
    if not path.is_absolute() or path != path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        _fail()
    return path


def _object(raw):
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result: _fail()
            result[key] = value
        return result
    value = json.loads(raw,object_pairs_hook=unique)
    if not isinstance(value,dict): _fail()
    return value


def _read(record):
    if not isinstance(record,dict) or set(record) != {'path','bytes','sha256'}:
        _fail()
    _path(record['path'])
    return checked_bytes(record)


def _prep(record):
    prep = _object(_read(record)); root = _path(record['path']).parent
    native = NativeScope(prep['scope'])
    if (Path(record['path']) != root/'geometry-preparation.json'
            or native.resource_profile != GEOMETRY_RESOURCE_PROFILE or native.root != root
            or prep.get('schema') != 'bridge.geometry-creative-preparation/1'
            or prep.get('task_id') != native.scope['task_id']
            or prep.get('source_reuse') != native.scope['source_reuse']):
        _fail()
    return prep,native


def _package(root,version):
    """沿用正式插件的完整包验证，额外固定插件版本与索引路径集合。"""
    root = _path(root)
    script = root/'scripts/bridge_mcp.py'
    module = types.ModuleType('_bridge_runtime_continuation_package');module.__file__=str(script)
    exec(compile(script.read_bytes(),str(script),'exec'),module.__dict__)
    module.verify_package(root)
    plugin = _object((root/'plugin.json').read_bytes())
    if plugin.get('name') != 'bridge-vfx' or plugin.get('version') != version:
        _fail()
    manifest = _object((root/'runtime-manifest.json').read_bytes())
    entries = {entry['path']:entry for entry in manifest['files']}
    if len(entries) != len(manifest['files']): _fail()
    sources = [file_record(root/name) for name in ('plugin.json','runtime-manifest.json','scripts/bridge_mcp.py')]
    return plugin,entries,sources


def _packages(original,active):
    """只接纳已审核的0.3.1→0.3.2差异；其他源码逐字保持。"""
    if (original/'scripts/bridge_mcp.py').read_bytes() != (active/'scripts/bridge_mcp.py').read_bytes(): _fail()
    old,oldfiles,oldsources = _package(original,'0.3.1')
    new,newfiles,newsources = _package(active,'0.3.2')
    if ({k:v for k,v in old.items() if k!='version'} != {k:v for k,v in new.items() if k!='version'}
            or set(oldfiles)-set(newfiles) or not set(newfiles)-set(oldfiles) <= _ADDED):
        _fail()
    changed = {name for name in oldfiles if oldfiles[name] != newfiles[name]}
    if not changed <= _CHANGED|{'plugin.json'}:
        _fail()
    # layout修订仅允许缺失baseline进入既有分发资源，不能改变其它包或配置。
    name = 'runtime/tools/release_layout.json'
    before = _object((original/name).read_bytes());after = _object((active/name).read_bytes())
    expected = json.loads(json.dumps(before))
    resources = expected['skills']['vfx-visual-twin']['deployment_resources']
    if _BASELINE in resources or not isinstance(resources,list): _fail()
    resources.append(_BASELINE)
    if after != expected: _fail()
    if file_record(active/('runtime/'+_BASELINE))['sha256'] != _BASELINE_SHA:
        _fail()
    differences=[]
    for name in sorted(changed | (set(newfiles)-set(oldfiles))):
        differences.append({'name':name,'before':file_record(original/name) if name in oldfiles else None,
                            'after':file_record(active/name)})
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),
            'package_sources':oldsources+newsources,'differences':differences,
            'original_worker':file_record(original/'runtime/tools/run_geometry_creative.py'),
            'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py')}


def _signature(native,payload):
    key = hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _original(preparation_record,prep,native,job_path,*,creation):
    """固定归档保留原失败字节；以后续作业推进不改写历史身份。"""
    job_path = _path(job_path);job = _object(job_path.read_bytes());root=native.root
    operation=job.get('operation_id')
    if (not isinstance(operation,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',operation)
            or job_path != root/'jobs'/operation/'job.json' or job.get('directory') != str(job_path.parent)
            or job.get('preparation') != preparation_record or job.get('task_id') != prep['task_id']
            or job.get('schema') != 'bridge.geometry-job/1' or job.get('revision') != 1):
        _fail()
    archive=root/'runtime-continuation-source'/operation
    records={name:file_record(_owned_path(archive/name,root)) for name in (*_ARCHIVE,'original-worker.py')}
    if _read(records['job.json']) != job_path.read_bytes(): _fail()
    state=_object(_read(records['geometry-state.json']));entry=state.get('jobs',{}).get(operation)
    if (state.get('schema')!='bridge.geometry-session-state/1' or state.get('task_id')!=prep['task_id']
            or state.get('preparation')!=preparation_record or state.get('revision')!=0 or state.get('completed')!=[]
            or not isinstance(entry,dict) or entry.get('state')!='QUEUED'
            or entry.get('job_file')!=file_record(job_path) or entry.get('revision')!=1
            or entry.get('directory')!=str(job_path.parent) or 'acceptance_receipt' in entry
            or set(state.get('jobs',{}))!={operation}
            or not isinstance(entry.get('plan_id'),str)
            or state.get('plans',{}).get(entry['plan_id'])!=job.get('plan')
            or state.get('plan_operations',{}).get(entry['plan_id'])!=operation):
        _fail()
    intent=_object(_read(records['controller-launch-intent.json']))
    started=_object(_read(records['controller-started.json']))
    argv=[prep['supervisor_python'],'-I','-B',prep['worker'],'run-job','--job',str(job_path)]
    if (intent.get('schema')!='bridge.geometry-controller-launch/1' or intent.get('operation_id')!=operation
            or intent.get('job')!=file_record(job_path) or intent.get('argv')!=argv
            or any(started.get(k)!=v for k,v in intent.items()) or started.get('state')!='STARTED'
            or started.get('pid')!=(started.get('process_identity') or {}).get('pid')
            or (creation and process_status(started['process_identity'])!='stopped')):
        _fail()
    error=_object(_read(records['error.json']))
    message="[Errno 2] No such file or directory: '"+str(Path(prep['worker']).parents[1]/_BASELINE)+"'"
    if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='FILENOTFOUNDERROR' or error.get('message')!=message
            or error.get('task_id')!=prep['task_id'] or error.get('operation_id')!=operation
            or error.get('revision')!=1 or error.get('preparation_record')!=preparation_record
            or error.get('stop_confirmed') is not True
            or error.get('native_snapshot')!={'dcc_starts':0,'total_seconds':0,'closed_reason':None,
                'scope_sha256':prep['scope']['sha256'],'tickets':[]}):
        _fail()
    if message not in _read(records['controller-error.log']).decode('utf-8'):
        _fail()
    if creation:
        for name in _ARCHIVE:
            live=root/'geometry-state.json' if name=='geometry-state.json' else job_path.parent/name
            if live.read_bytes()!=_read(records[name]):_fail()
        usage=native.completed_snapshot()
        if (usage['tickets'] or usage['dcc_starts']!=0 or usage['total_seconds']!=0
                or usage['closed_reason'] is not None): _fail()
        if any((job_path.parent/name).exists() for name in ('execute-owner.json','job-preparation.json',
                    'incremental-state.json','graph-source-journal.json','result.json')): _fail()
        for path in job_path.parent.rglob('*'):
            if path.is_symlink(): _fail()
            if path.is_file() and (path.suffix.lower() in {'.hip','.hiplc','.hipnc','.sqlite','.sqlite3','.db'}
                                  or path.name.endswith(('.sqlite3-wal','.sqlite3-shm'))): _fail()
    return {'job':file_record(job_path),'archive':records,'original_state':records['geometry-state.json']}


def create_binding(preparation_record,original_plugin_root,active_plugin_root,job_path,instruction):
    """一次新建显式续接证明；不修改旧准备、作业、错误、预算与包文件。"""
    if not isinstance(instruction,str) or not 10<=len(instruction)<=16000 or not instruction.strip(): _fail()
    prep,native=_prep(preparation_record)
    original,active=_path(original_plugin_root),_path(active_plugin_root)
    oldworker=_path(prep['worker'])
    if active != oldworker.parents[2].with_name('0.3.2'): _fail()
    packages=_packages(original,active)
    if (oldworker.name!='run_geometry_creative.py' or oldworker.parent.name!='tools'
            or oldworker.parents[1].name!='runtime' or oldworker.parents[2].name!='0.3.1'): _fail()
    # 原安装与正式0.3.1来源须同一完整索引，不能只凭未改动的启动脚本冒充旧运行时。
    if oldworker.parents[2].exists():
        _package(oldworker.parents[2],'0.3.1')
        if (oldworker.read_bytes()!=_read(packages['original_worker'])
                or any((oldworker.parents[2]/name).read_bytes() != (original/name).read_bytes()
                       for name in ('runtime-manifest.json','plugin.json'))): _fail()
    source=_original(preparation_record,prep,native,job_path,creation=True)
    if _read(source['archive']['original-worker.py'])!=_read(packages['original_worker']): _fail()
    initial=_object(native.state_path.read_bytes());state=native._verify_envelope(initial)['state']
    if state['tickets']: _fail()
    payload={'schema':_SCHEMA,'preparation':preparation_record,'native_scope':prep['scope'],
             'task_id':prep['task_id'],'original_worker_path':prep['worker'],
             'authority':{'authority':'current_user_instruction','instruction':instruction},
             'original_source':source,'initial_accounting':initial,**packages}
    value={'payload':payload,'signature':_signature(native,payload)}
    path=native.root/'runtime-continuation.json'
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(native._canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
    return file_record(path)


def _resolve(preparation_record,runtime_root):
    prep,native=_prep(preparation_record);runtime=_path(runtime_root)
    expected=runtime/'tools/run_geometry_creative.py'
    if _path(prep['worker'])==expected:
        return file_record(expected),None
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.9')/'runtime':
        from .geometry_metadata_runtime_successor import _AUTH,resolve
        authority=file_record(native.root/_AUTH);p,_=resolve(preparation_record,authority,native)
        if Path(p['active_worker']['path']).parents[1]!=runtime:_fail()
        return p['active_worker'],authority
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.8')/'runtime':
        from .geometry_metadata_completion import _AUTH,validate,_accepted
        authority=file_record(native.root/_AUTH);source=_object(_read(_object(_read(authority))['payload']['source']));job=_object(_read(source['job']))
        p,*_=validate(preparation_record,authority,native,historical=_accepted(native,job,authority))
        if Path(p['active_worker']['path']).parents[1]!=runtime:_fail()
        return p['active_worker'],authority
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.7')/'runtime':
        from .geometry_prelaunch_tail import _AUTH,effective
        authority=file_record(native.root/_AUTH);p,_=effective(preparation_record,runtime,authority)
        return p['active_worker'],authority
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.6')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from .geometry_seed_cold_resume import resolve_runtime
        return resolve_runtime(preparation_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.2')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from .geometry_nuke_save_runtime_successor import resolve_runtime
        return resolve_runtime(preparation_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.1')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from . import geometry_nuke_save_resume
        return geometry_nuke_save_resume.resolve_worker(preparation_record,runtime),geometry_nuke_save_resume.authorization_record(preparation_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.9')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from . import geometry_registration_resume
        return geometry_registration_resume.resolve_worker(preparation_record,runtime),geometry_registration_resume.authorization_record(preparation_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.8')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from . import geometry_nuke_resume
        return geometry_nuke_resume.resolve_worker(preparation_record,runtime),geometry_nuke_resume.authorization_record(preparation_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.6')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from . import geometry_render_resume
        return geometry_render_resume.resolve_worker(preparation_record,runtime),geometry_render_resume.authorization_record(preparation_record,runtime)
    if runtime in (Path(prep['worker']).parents[2].with_name(version)/'runtime' for version in ('0.3.4','0.3.5')):
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from dcc_task_runtime import geometry_recovery
        return geometry_recovery.resolve_worker(preparation_record,runtime),geometry_recovery.authorization_record(preparation_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.3')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        return _resolve_v033(preparation_record,prep,native,runtime)
    path=_owned_path(native.root/'runtime-continuation.json',native.root)
    if path.stat().st_mode&0o077: _fail()
    value=_object(path.read_bytes());payload=value.get('payload')
    if (set(value)!={'payload','signature'} or not isinstance(payload,dict)
            or not hmac.compare_digest(str(value['signature']),_signature(native,payload))
            or payload.get('schema')!=_SCHEMA or payload.get('preparation')!=preparation_record
            or payload.get('native_scope')!=prep['scope'] or payload.get('task_id')!=prep['task_id']
            or payload.get('original_worker_path')!=prep['worker']
            or payload.get('authority',{}).get('authority')!='current_user_instruction'
            or not isinstance(payload.get('authority',{}).get('instruction'),str)
            or payload.get('active_plugin_root')!=str(runtime.parent) or runtime.name!='runtime'):
        _fail()
    original=_path(payload['original_plugin_root']);active=_path(payload['active_plugin_root'])
    if active != Path(prep['worker']).parents[2].with_name('0.3.2'): _fail()
    packages=_packages(original,active)
    if any(payload.get(k)!=v for k,v in packages.items()): _fail()
    if packages['active_worker']['path']!=str(expected):_fail()
    source=_original(preparation_record,prep,native,payload['original_source']['job']['path'],creation=False)
    if (source!=payload['original_source']
            or _read(source['archive']['original-worker.py'])!=_read(packages['original_worker'])): _fail()
    state=native._verify_envelope(payload['initial_accounting'])['state']
    if state.get('tickets')!=[] or state.get('scope_sha256')!=prep['scope']['sha256']: _fail()
    # 初始零票证明须仍在当前完整签名链内；后续合法票据不会失效此授权。
    if not any(_object(line)==payload['initial_accounting'] for line in native.journal_path.read_bytes().splitlines()):
        _fail()
    native.check()
    return packages['active_worker'],file_record(path)


def resolve_worker(preparation_record,runtime_root):
    """新派发严格选择当前worker；跨安装只接受完整显式续接合同。"""
    return _resolve(preparation_record,runtime_root)[0]


def continuation_record(preparation_record,runtime_root):
    """返回已完整复核的续接记录；同一原runtime返回None。"""
    return _resolve(preparation_record,runtime_root)[1]

# 仅为已审核的一次float编码修复增加后继域；原0.3.2合同保持原语义。
_V033_SCHEMA = 'bridge.geometry-runtime-continuation-v033/1'
_V033_DOMAIN = b'bridge.geometry-runtime-continuation-v033/1\x00'
_V033_CHANGED = {'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_graph.py',
                 'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_session.py',
                 'runtime/packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py',
                 'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_runtime_binding.py'}
_V033_ADDED = {'runtime/tools/repair_geometry_float_encoding.py'}


def _signature_v033(native,payload):
    key=hmac.new(native._key(),_V033_DOMAIN,hashlib.sha256).digest()
    return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()


def _v033_packages(original,active):
    """固定0.3.2至0.3.3的四个源码修订与一个operator入口。"""
    if (original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes(): _fail()
    old,oldfiles,oldsources=_package(original,'0.3.2')
    new,newfiles,newsources=_package(active,'0.3.3')
    changed={name for name in oldfiles if name in newfiles and oldfiles[name]!=newfiles[name]}
    if ({k:v for k,v in old.items() if k!='version'}!={k:v for k,v in new.items() if k!='version'}
            or set(oldfiles)-set(newfiles) or set(newfiles)-set(oldfiles)!=_V033_ADDED
            or not changed<=_V033_CHANGED|{'plugin.json'}): _fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),
            'package_sources':oldsources+newsources,
            'differences':[{'name':name,'before':file_record(original/name) if name in oldfiles else None,
                            'after':file_record(active/name)} for name in sorted(changed|_V033_ADDED)],
            'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py')}


def _rebase_package(value,source,target):
    """只在比较视图映射已卸载cache记录；不改写历史证明里的原路径。"""
    if isinstance(value,dict):return {k:_rebase_package(v,source,target) for k,v in value.items()}
    if isinstance(value,list):return [_rebase_package(v,source,target) for v in value]
    if isinstance(value,str) and value.startswith(str(source)+'/'):
        return str(target/Path(value).relative_to(source))
    if value==str(source):return str(target)
    return value


def _historical_v032(preparation_record,prep,native,previous_binding_record,formal):
    """认证已签旧绑定与正式旧包；不要求被官方卸载的旧cache仍存在。"""
    if Path(previous_binding_record['path'])!=native.root/'runtime-continuation.json':_fail()
    path=_path(previous_binding_record['path'])
    if path.stat().st_mode&0o077:_fail()
    envelope=_object(_read(previous_binding_record));payload=envelope.get('payload')
    if (set(envelope)!={'payload','signature'} or not isinstance(payload,dict)
            or not hmac.compare_digest(str(envelope['signature']),_signature(native,payload))
            or payload.get('schema')!=_SCHEMA or payload.get('preparation')!=preparation_record
            or payload.get('native_scope')!=prep['scope'] or payload.get('task_id')!=prep['task_id']
            or payload.get('original_worker_path')!=prep['worker']
            or payload.get('active_plugin_root')!=str(Path(prep['worker']).parents[2].with_name('0.3.2'))):_fail()
    packages=_packages(_path(payload['original_plugin_root']),formal)
    former_cache=_path(payload['active_plugin_root'])
    if any(_rebase_package(payload.get(k),former_cache,formal)!=v for k,v in packages.items()):_fail()
    source=_original(preparation_record,prep,native,payload['original_source']['job']['path'],creation=False)
    if (source!=payload['original_source']
            or _read(source['archive']['original-worker.py'])!=_read(packages['original_worker'])):_fail()
    state=native._verify_envelope(payload['initial_accounting'])['state']
    if (state.get('tickets')!=[] or state.get('scope_sha256')!=prep['scope']['sha256']
            or not any(_object(line)==payload['initial_accounting'] for line in native.journal_path.read_bytes().splitlines())):_fail()
    return {'previous_binding':previous_binding_record,'initial_accounting':payload['initial_accounting'],
            'formal_sources':[file_record(formal/name) for name in ('plugin.json','runtime-manifest.json','scripts/bridge_mcp.py')]}


def _repair_request(record,preparation_record,prep,native,failed_job):
    """只接受原Luna计划的同值float编码，不创造新观察或扩大模型意图。"""
    from dcc_task_runtime.canonical import canonical_sha256
    from . import geometry_graph as g
    if Path(record['path'])!=native.root/'runtime-v033-repair-request.json':_fail()
    request=_object(_read(record));oldplan=failed_job['plan']
    fields={'schema','preparation','task_id','failed_operation_id','failed_job','original_plan_sha256',
            'new_plan','request_id','new_operation_id'}
    if (set(request)!=fields or request['schema']!='bridge.geometry-typed-repair-request/1'
            or request['preparation']!=preparation_record or request['task_id']!=prep['task_id']
            or request['failed_operation_id']!=failed_job['operation_id']
            or request['failed_job']!=file_record(Path(failed_job['directory'])/'job.json')
            or request['original_plan_sha256']!=oldplan.get('plan_sha256')
            or canonical_sha256({k:v for k,v in oldplan.items() if k!='plan_sha256'})!=oldplan.get('plan_sha256')):_fail()
    expected=json.loads(json.dumps(oldplan));expected['plan_id']=oldplan['plan_id']+'_float_repair01'
    expected['model_graph']=g.model_proposal(oldplan['model_graph']).to_dict();expected['selector']=g.selector(expected['model_graph'])
    expected['operator_repair']={'schema':'bridge.geometry-operator-repair/1','failed_operation_id':failed_job['operation_id'],
                                 'authorization_path':str(native.root/'runtime-continuation-v033.json')}
    expected['plan_sha256']=canonical_sha256({k:v for k,v in expected.items() if k!='plan_sha256'})
    identifier='operator_float_repair01_'+failed_job['operation_id']
    operation='geo_'+hashlib.sha256((identifier+expected['plan_sha256']).encode()).hexdigest()[:24]
    if (native._canonical(request['new_plan'])!=native._canonical(expected)
            or request['request_id']!=identifier or request['new_operation_id']!=operation):_fail()
    return request


def _failure_v033(preparation_record,prep,native,failed_job_path,formal,accounting_record):
    """只读复核已取消且未回滚的第一次真实参数类型失败，不套成功bundle。"""
    from dcc_task_runtime.canonical import canonical_sha256
    from dcc_task_runtime import owned_process
    from houdini_bridge.operation_receipts import validate_operation_receipt
    from houdini_bridge.operation_receipt_store import load_record,record_path
    from .official_graph_resume import _ReadOnlyJobs,_snapshot,_geometry_accounting_snapshot,_read_database
    from .production_hosts import native_scope_budget
    from .graph_job_worker import runtime_fingerprint
    from . import graph_catalog
    failed_job_path=_path(failed_job_path);job=_object(failed_job_path.read_bytes());directory=failed_job_path.parent
    if (job.get('preparation')!=preparation_record or job.get('task_id')!=prep['task_id']
            or job.get('revision')!=1 or job.get('schema')!='bridge.geometry-job/1'
            or directory!=native.root/'jobs'/job.get('operation_id','')
            or failed_job_path!=directory/'job.json' or job.get('directory')!=str(directory)):_fail()
    state=_geometry_accounting_snapshot(native,accounting_record)
    if (len(state['tickets'])!=1 or state['tickets'][0]['role']!='graph-worker'
            or state['tickets'][0].get('parent') is not None or state.get('closed_reason') is not None):_fail()
    ticket=state['tickets'][0]
    error=_object((directory/'error.json').read_bytes())
    usage={'dcc_starts':1,'total_seconds':max(ticket['charged_seconds'],ticket['stopped_at']-ticket['admitted_at']),
           'closed_reason':None,'scope_sha256':prep['scope']['sha256'],'tickets':state['tickets']}
    if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('state')!='FAILED'
            or error.get('code')!='GEOMETRY_GRAPH_FAILED' or error.get('message')!='GEOMETRY_GRAPH_FAILED'
            or error.get('stop_confirmed') is not True or error.get('preparation_record')!=preparation_record
            or error.get('task_id')!=prep['task_id'] or error.get('operation_id')!=job['operation_id']
            or error.get('revision')!=1 or error.get('native_snapshot')!=usage):_fail()
    jobprep=_object((directory/'job-preparation.json').read_bytes());control=directory/'project/control'
    if (jobprep.get('job')!=file_record(failed_job_path) or jobprep.get('control')!=str(control)
            or jobprep.get('project')!=str(directory/'project')
            or jobprep.get('manifest')!=file_record(control/'run.json')
            or jobprep.get('snapshot_manifest')!=_snapshot(control)):_fail()
    manifest=_object(_read(jobprep['manifest']))
    if (manifest.get('domain_pack')!='material_lookdev_v1'
            or manifest.get('geometry_task_binding')!=prep.get('task_binding')
            or manifest['production_host'].get('native_scope')!=prep['scope']):_fail()
    index=_object(_read(jobprep['snapshot_manifest']))
    for row in index['files']:
        if file_record(formal/'runtime'/row['path'])['sha256']!=row['sha256']:_fail()
    journal=_object((directory/'incremental-state.json').read_bytes())
    stage=journal.get('stages',{}).get('graph_trial',{})
    operation=stage.get('result',{}).get('operation_id')
    if (journal.get('job')!=file_record(failed_job_path) or stage.get('state')!='DONE'
            or journal.get('stages',{}).get('build_completed',{}).get('state')!='INTENT'
            or not isinstance(operation,str)):_fail()
    budget=native_scope_budget(prep['scope'],manifest['production_host']['resource_budget'],control/'jobs',native.root/'scheduler')
    jobs=_ReadOnlyJobs(control/'jobs',control/'snapshot',native.root/'scheduler',budget,240)
    row=dict(jobs._row(operation));jobs._operation_budget(row);intent=json.loads(row['intent_json'])
    if (row['state']!='CANCELLED' or row['cancel_requested']!=1 or row['stop_confirmed']!=1
            or row['error_code']!='CANCELLED_STOP_CONFIRMED_OUTCOME_NOT_ROLLED_BACK'
            or row['attempt_generation']!=1 or row['result_json'] is not None
            or intent.get('task_id')!=prep['task_id'] or intent.get('repo_root')!=str(control/'snapshot')
            or intent.get('scheduler_root')!=str(native.root/'scheduler') or intent.get('native_scope_budget')!=budget):_fail()
    paths=jobs._worker_paths(operation);identity=jobs._supervisor_identity(row);supervisor=paths['directory']/'owned-supervisor'
    started=owned_process.read_receipt(supervisor,'started',identity=identity)
    stopped=owned_process.read_receipt(supervisor,'stopped',identity=identity)
    if (ticket['directory']!=str(supervisor) or ticket['identity']!=identity or not started or not stopped
            or stopped!=native._stop(ticket) or owned_process.execution_returncode(stopped)!=0
            or ticket['stopped_at']!=stopped['observed_at']
            or ticket['stopped_sha256']!=hashlib.sha256(native._canonical(stopped)).hexdigest()
            or (started.get('resource_budget') or {}).get('native_scope')!=prep['scope']):_fail()
    inputs=_object(paths['inputs'].read_bytes());worker=_object(paths['identity'].read_bytes())
    raw=_object(paths['result'].read_bytes());proposal=_object(paths['proposal'].read_bytes());compiled=_object(paths['graph'].read_bytes())
    from .graph_construction_inputs import freeze_construction_inputs
    frozen=freeze_construction_inputs(inputs.get('frozen_input_manifest',[]))
    command=_object((supervisor/'intent.json').read_bytes()).get('command')
    native_job={'schema_version':'bridge.graph_job_evidence/2.0','operation_id':operation,'graph_id':row['graph_id'],
        'root':str(control/'jobs'),'repo_root':str(control/'snapshot'),'task_id':prep['task_id'],
        **{name+'_path':str(paths[key]) for name,key in {'graph':'graph','proposal':'proposal','result':'result',
            'journal':'journal','lease':'lease','error':'error','inputs':'inputs','identity':'identity','completion':'completion'}.items()},
        'deadline_at':row['deadline_at'],'attempt_token':row['process_token'],'attempt_generation':1,
        'scheduler_root':str(native.root/'scheduler'),'validation_scope':'host_construction_only',
        'frozen_input_manifest':frozen,'frozen_inputs_sha256':canonical_sha256(frozen),
        **{key:intent[key] for key in ('budget_started_at','job_budget_seconds','deadline_at','native_scope_budget') if key in intent}}
    if (not isinstance(command,list) or len(command)!=4
            or command[:3]!=[native.scope['hosts']['hython']['path'],str(control/'snapshot/packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'),'--job']
            or native._canonical(_object(command[3]))!=native._canonical(native_job)
            or canonical_sha256(command)!=started.get('argv_sha256')
            or inputs.get('frozen_inputs_sha256')!=canonical_sha256(frozen)):_fail()
    graphrecord=dict(jobs._graph_record_for_operation(operation))
    for value in (inputs,worker):
        if (value.get('schema_version')!='bridge.graph_job_evidence/2.0' or value.get('operation_id')!=operation
                or value.get('graph_id')!=row['graph_id'] or value.get('attempt_token')!=row['process_token']
                or value.get('attempt_generation')!=1):_fail()
    if (any(inputs.get(k)!=v for k,v in intent.items())
            or worker.get('inputs_sha256')!=file_record(paths['inputs'])['sha256']
            or worker.get('process_identity')!=json.loads(row['process_identity_json'])
            or worker['process_identity'].get('pid')!=started['pid']
            or compiled.get('graph_hash')!=canonical_sha256({k:v for k,v in compiled.items() if k!='graph_hash'})
            or native._canonical(proposal)!=native._canonical(job['plan']['selector'])
            or compiled!=json.loads(graphrecord['compiled_json']) or proposal!=json.loads(graphrecord['proposal_json'])
            or inputs.get('catalog_hash')!=graph_catalog.descriptor()['catalog_hash']
            or inputs.get('runtime_sha256')!=runtime_fingerprint(control/'snapshot')
            or inputs.get('proposal_hash')!=canonical_sha256(proposal)
            or inputs.get('proposal_sha256')!=file_record(paths['proposal'])['sha256']
            or inputs.get('compiled_sha256')!=file_record(paths['graph'])['sha256']
            or raw.get('operation_id')!=operation or raw.get('graph_id')!=row['graph_id']
            or raw.get('graph_hash')!=compiled['graph_hash'] or raw.get('construction_executed') is not False
            or raw.get('reconciliation_required') is not True or raw.get('visual_verified') is not False
            or raw.get('validation_scope')!='host_construction_only' or paths['completion'].exists()
            or any((directory/'project').rglob('*.hip')) or (directory/'result.json').exists()):_fail()
    runner=control/'graph-houdini-instances/fx_operations'/('ops_'+hashlib.sha256(prep['task_id'].encode()).hexdigest()[:16]+'.json')
    taskdir=record_path(runner,prep['task_id'],'placeholder').parent
    producers=[];failed=[]
    for path in sorted(taskdir.glob('*.json')):
        receipt=_object(path.read_bytes());validate_operation_receipt(receipt,require_completed=False)
        if load_record(runner,prep['task_id'],receipt['operation_id'])!=receipt:_fail()
        producers.append(file_record(path))
        if receipt['state']!='COMPLETED':failed.append(receipt)
    if len(failed)!=1:_fail()
    receipt=failed[0];host=receipt['host_identity'];request=receipt['request']
    left=[n for n in job['plan']['model_graph']['nodes'] if n['node_id']=='left_post']
    if (len(left)!=1 or receipt['state']!='FAILED' or receipt['command']!='node.set_parms'
            or receipt.get('execution_boundary')!='native_hom'
            or receipt.get('error')!={'code':'PARAMETER_READBACK_MISMATCH','message':'native parameter result differs from requested edit'}
            or request.get('path')!=request.get('root_path','')+'/geometry_network/m_left_post'
            or native._canonical(request.get('parms'))!=native._canonical(left[0]['parameters'])
            or not any(type(v) is int for v in request['parms'].values())
            or host.get('pid')!=started['pid'] or host.get('launch_nonce')!=row['process_token']
            or host.get('supervisor_identity')!=identity or host.get('task_id')!=prep['task_id']
            or host.get('plugin_build')!=file_record(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')['sha256']):_fail()
    with _read_database(paths['journal']) as db:
        entries={k:json.loads(v) for k,v in db.execute('SELECT operation_id,payload FROM entries')}
    unknown=[v for v in entries.values() if v.get('status')!='COMPLETE']
    if (len(unknown)!=1 or unknown[0].get('status')!='UNKNOWN'
            or unknown[0].get('intent')!={'address':'houdini_sop:/geometry_network/m_left_post','kind':'node.set_parms','parameters':request['parms']}
            or unknown[0].get('error')!='native parameter result differs from requested edit'):_fail()
    files=[file_record(path) for path in [failed_job_path,directory/'error.json',directory/'job-preparation.json',
        directory/'incremental-state.json',control/'run.json',control/'snapshot-manifest.json',
        paths['inputs'],paths['identity'],paths['result'],paths['proposal'],paths['graph'],paths['journal'],
        supervisor/'intent.json',supervisor/'started.json',supervisor/'stopped.json']]+producers
    return {'job':file_record(failed_job_path),'operation_id':operation,'operation_row':row,
            'graph_record':graphrecord,'journal_entries_sha256':canonical_sha256(entries),
            'accounting':accounting_record,'source_files':files},job


def _frozen_copy(path,raw):
    """后继来源只可首次写入或重读同字节，不覆盖历史记录。"""
    from dcc_task_runtime.platform_support import ensure_private_directory
    path=_path(path);ensure_private_directory(path.parent)
    if path.exists():
        if path.read_bytes()!=raw:_fail()
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return file_record(path)


def create_successor_binding(preparation_record,previous_binding_record,original_v032_plugin_root,
        active_v033_plugin_root,failed_job_path,repair_request_record,instruction):
    """一次性签署原预算内的已知float编码修复后继，不重派原失败operation。"""
    if not isinstance(instruction,str) or not 10<=len(instruction)<=16000 or not instruction.strip():_fail()
    prep,native=_prep(preparation_record);formal=_path(original_v032_plugin_root);active=_path(active_v033_plugin_root)
    if (Path(prep['worker']).parents[2].name!='0.3.1'
            or active!=Path(prep['worker']).parents[2].with_name('0.3.3')):_fail()
    history=_historical_v032(preparation_record,prep,native,previous_binding_record,formal)
    packages=_v033_packages(formal,active);usage=native.completed_snapshot()
    if len(usage['tickets'])!=1 or usage['closed_reason'] is not None:_fail()
    source=native.root/'runtime-continuation-v033-source'
    accounting=_frozen_copy(source/'accounting.json',native.state_path.read_bytes())
    failure,job=_failure_v033(preparation_record,prep,native,failed_job_path,formal,accounting)
    request=_repair_request(repair_request_record,preparation_record,prep,native,job)
    state=_object((native.root/'geometry-state.json').read_bytes());entry=state.get('jobs',{}).get(job['operation_id'],{})
    if (state.get('preparation')!=preparation_record or state.get('task_id')!=prep['task_id']
            or state.get('revision')!=0 or state.get('completed')!=[] or entry.get('state')!='FAILED'
            or entry.get('job_file')!=failure['job'] or 'acceptance' in entry
            or request['new_operation_id'] in state.get('jobs',{})):_fail()
    session=_frozen_copy(source/'session-state.json',(native.root/'geometry-state.json').read_bytes())
    payload={'schema':_V033_SCHEMA,'preparation':preparation_record,'native_scope':prep['scope'],'task_id':prep['task_id'],
        'authority':{'authority':'current_user_instruction','instruction':instruction},'history':history,
        'failure':failure,'repair_request':repair_request_record,'source_session':session,**packages}
    value={'payload':payload,'signature':_signature_v033(native,payload)}
    path=native.root/'runtime-continuation-v033.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(native._canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
    return file_record(path)


def _resolve_v033(preparation_record,prep,native,runtime):
    """当前安装0.3.3只接纳此唯一后继，随后继续使用原范围剩余额度。"""
    if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
    path=_path(native.root/'runtime-continuation-v033.json')
    if path.stat().st_mode&0o077:_fail()
    value=_object(path.read_bytes());payload=value.get('payload')
    if (set(value)!={'payload','signature'} or not isinstance(payload,dict)
            or not hmac.compare_digest(str(value['signature']),_signature_v033(native,payload))
            or payload.get('schema')!=_V033_SCHEMA or payload.get('preparation')!=preparation_record
            or payload.get('native_scope')!=prep['scope'] or payload.get('task_id')!=prep['task_id']
            or payload.get('active_plugin_root')!=str(runtime.parent)
            or runtime.parent!=Path(prep['worker']).parents[2].with_name('0.3.3')):_fail()
    formal=_path(payload['original_plugin_root']);active=runtime.parent
    packages=_v033_packages(formal,active)
    if any(payload.get(k)!=v for k,v in packages.items()):_fail()
    history=_historical_v032(preparation_record,prep,native,payload['history']['previous_binding'],formal)
    if history!=payload['history']:_fail()
    failure,job=_failure_v033(preparation_record,prep,native,payload['failure']['job']['path'],formal,payload['failure']['accounting'])
    if failure!=payload['failure']:_fail()
    request=_repair_request(payload['repair_request'],preparation_record,prep,native,job)
    state=_object(_read(payload['source_session']));entry=state.get('jobs',{}).get(job['operation_id'],{})
    if (state.get('preparation')!=preparation_record or state.get('task_id')!=prep['task_id']
            or state.get('revision')!=0 or state.get('completed')!=[] or entry.get('state')!='FAILED'
            or entry.get('job_file')!=failure['job'] or 'acceptance' in entry
            or request['new_operation_id'] in state.get('jobs',{})):_fail()
    native.check()
    return packages['active_worker'],file_record(path)


def verify_operator_dispatch(preparation_record,plan,request_id,authority_record,runtime_root):
    """仅内部operator携精确后继authority可派发repair计划；公共MCP不能凭猜ID重派。"""
    if not isinstance(authority_record,dict):_fail()
    prep,native=_prep(preparation_record);runtime=_path(runtime_root)
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.6')/'runtime':
        from .geometry_seed_cold_resume import resolve_dispatch
        return resolve_dispatch(preparation_record,plan,request_id,authority_record,runtime).authority
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.2')/'runtime':
        from .geometry_nuke_save_runtime_successor import resolve_dispatch
        return resolve_dispatch(preparation_record,plan,request_id,authority_record,runtime).authority
    if runtime==Path(prep['worker']).parents[2].with_name('0.4.1')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from .geometry_nuke_save_resume import verify_operator_dispatch as verify_nuke_save
        return verify_nuke_save(preparation_record,plan,request_id,authority_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.9')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from .geometry_registration_resume import verify_operator_dispatch as verify_registration
        return verify_registration(preparation_record,plan,request_id,authority_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.8')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from .geometry_nuke_resume import verify_operator_dispatch as verify_nuke_resume
        return verify_nuke_resume(preparation_record,plan,request_id,authority_record,runtime)
    if runtime==Path(prep['worker']).parents[2].with_name('0.3.6')/'runtime':
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from .geometry_render_resume import verify_operator_dispatch as verify_render_resume
        return verify_render_resume(preparation_record,plan,request_id,authority_record,runtime)
    if runtime in (Path(prep['worker']).parents[2].with_name(version)/'runtime' for version in ('0.3.4','0.3.5')):
        if Path(prep['worker']).parents[2].name!='0.3.1':_fail()
        from dcc_task_runtime.geometry_recovery import verify_operator_dispatch as verify_recovery
        return verify_recovery(preparation_record,plan,request_id,authority_record,runtime)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.3.3')/'runtime':_fail()
    _,actual=_resolve_v033(preparation_record,prep,native,runtime)
    if authority_record!=actual:_fail()
    payload=_object(_read(actual))['payload'];request=_object(_read(payload['repair_request']))
    if (native._canonical(plan)!=native._canonical(request['new_plan'])
            or request_id!=request['request_id']):_fail()
    return actual
