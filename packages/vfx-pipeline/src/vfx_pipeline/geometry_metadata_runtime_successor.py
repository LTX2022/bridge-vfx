"""049仅签已完成metadata验证代码后继；原048数据授权和Native票据不改。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os
from pathlib import Path
from houdini_bridge.official_karma_observation import file_record
from .geometry_registration_resume import _context
from .geometry_render_resume import _path
_AUTH='geometry-metadata-runtime-successor-authorization.json'
_SOURCE_NAME='geometry-metadata-runtime-successor-source.json'
_SCHEMA='bridge.geometry-metadata-runtime-successor/1'
_SOURCE='bridge.geometry-metadata-runtime-successor-source/1'
_DOMAIN=b'bridge.geometry-metadata-runtime-successor/1\x00'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_metadata_runtime_successor.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_metadata_completion','geometry_job','geometry_session','geometry_seed_cold_resume','geometry_registration_resume','geometry_runtime_binding','geometry_prelaunch_tail')}
_CHANGED|={'runtime/tools/complete_geometry_metadata.py'}

def _fail():raise ValueError('GEOMETRY_METADATA_RUNTIME_SUCCESSOR_INVALID')
def _sign(native,p):return hmac.new(hmac.new(native._key(),_DOMAIN,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()
def _read(record):
    from .geometry_metadata_completion import _read
    return _read(record)
def _packages(original,active):
    from .geometry_runtime_binding import _package
    a,af,ars=_package(original,'0.4.8');b,bf,brs=_package(active,'0.4.9');changed={name for name in af if name in bf and af[name]!=bf[name]}
    if ({k:v for k,v in a.items() if k!='version'}!={k:v for k,v in b.items() if k!='version'} or set(af)-set(bf) or set(bf)-set(af)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':ars+brs,'active_worker':file_record(active/'runtime/tools/complete_geometry_metadata.py'),
            'differences':[{'name':name,'before':file_record(original/name) if name in af else None,'after':file_record(active/name)} for name in sorted(changed|_ADDED)]}

def _source(source,native):
    from . import geometry_metadata_completion as data
    from .geometry_runtime_binding import _package
    fields={'schema','preparation','task_id','data_authority','data_source','formal048','formal048_manifest','job','execution_proof','scope_state','scope_journal','scope_anchor','interrupted_inspect'}
    if type(source) is not dict or set(source)!=fields or source['schema']!=_SOURCE or source['task_id']!=native.scope['task_id']:_fail()
    authority=source['data_authority'];v=_read(authority);p=v.get('payload')
    if (authority['path']!=str(native.root/data._AUTH) or set(v)!={'payload','signature'} or type(p) is not dict or p.get('schema')!=data._SCHEMA or p.get('native_scope')!=native.binding
            or p.get('preparation')!=source['preparation'] or p.get('task_id')!=source['task_id'] or p.get('source')!=source['data_source'] or not hmac.compare_digest(str(v['signature']),data._sign(native,p))):_fail()
    original=_read(source['data_source']);formal=_path(source['formal048']);_,_,indices=_package(formal,'0.4.8')
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':indices} or source['formal048_manifest']!=file_record(formal/'runtime-manifest.json'):_fail()
    if (source['job']!=original['job'] or source['execution_proof']!=original['execution_proof'] or source['preparation']!=original['preparation']
            or any(source[key]!=original['records'][key] for key in ('scope_state','scope_journal','scope_anchor'))):_fail()
    for name in ('job','execution_proof','scope_state','scope_journal','scope_anchor','interrupted_inspect'):data._bytes(source[name])
    usage=original['native_snapshot']
    if usage.get('dcc_starts')!=17 or len(usage.get('tickets',[]))!=17 or any(t.get('stopped_at') is None for t in usage['tickets']):_fail()
    report=_read(source['interrupted_inspect'])
    if (report.get('state')!='FAIL' or report.get('native_starts')!=0 or report.get('canonical_published') is not False or report.get('accepted_sealed') is not False or 'KeyboardInterrupt' not in json.dumps(report.get('error'),ensure_ascii=False)):_fail()
    return p,original

def inspect_source(preparation,formal048,interrupted_inspect):
    """仅代码后继准备；不重跑048事实工厂，不产生新预算或结果。"""
    from . import geometry_metadata_completion as data
    _,native=_context(preparation);authority=file_record(native.root/data._AUTH);p=_read(authority)['payload'];old=_read(p['source']);formal=_path(formal048)
    source={'schema':_SOURCE,'preparation':preparation,'task_id':native.scope['task_id'],'data_authority':authority,'data_source':p['source'],'formal048':str(formal),'formal048_manifest':file_record(formal/'runtime-manifest.json'),
            'job':old['job'],'execution_proof':old['execution_proof'],'scope_state':old['records']['scope_state'],'scope_journal':old['records']['scope_journal'],'scope_anchor':old['records']['scope_anchor'],'interrupted_inspect':interrupted_inspect}
    _source(source,native)
    if any((Path(old['job']['path']).parent/name).exists() for name in ('result.json','accepted-result.json')):_fail()
    return source

def create_authorization(preparation,source_record,formal048,active049,formal049):
    from . import geometry_metadata_completion as data
    from .geometry_runtime_binding import _package
    prep,native=_context(preparation);source=_read(source_record);original=_path(formal048);active=_path(active049);formal=_path(formal049)
    if source_record['path']!=str(native.root/_SOURCE_NAME) or source['preparation']!=preparation or source['formal048']!=str(original) or active!=Path(prep['worker']).parents[2].with_name('0.4.9'):_fail()
    _source(source,native);packages=_packages(original,active);a,af,_=_package(active,'0.4.9');b,bf,indices=_package(formal,'0.4.9')
    if a!=b or af!=bf or active==formal or formal.is_relative_to(native.root):_fail()
    p={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':native.scope['task_id'],'source':source_record,'consumer_runtime':{'package_root':str(formal),'package_sources':indices},**packages}
    return data._write(native.root/_AUTH,{'payload':p,'signature':_sign(native,p)})

def resolve(preparation,authority,native):
    """049认证独立消费者身份；原048的package/hash仍按formal048完整保留。"""
    from .geometry_runtime_binding import _package,_rebase_package
    if authority['path']!=str(native.root/_AUTH) or _path(authority['path']).stat().st_mode&0o077:_fail()
    v=_read(authority);p=v.get('payload');fields={'schema','preparation','native_scope','task_id','source','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(v)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or p.get('schema')!=_SCHEMA or p.get('preparation')!=preparation or p.get('native_scope')!=native.binding
            or p.get('task_id')!=native.scope['task_id'] or p['source']['path']!=str(native.root/_SOURCE_NAME) or not hmac.compare_digest(str(v['signature']),_sign(native,p))):_fail()
    source=_read(p['source']);_source(source,native);formal=_path(p['consumer_runtime']['package_root']);_,_,indices=_package(formal,'0.4.9');packages=_packages(_path(p['original_plugin_root']),formal)
    if source['formal048']!=p['original_plugin_root'] or p['consumer_runtime']!={'package_root':str(formal),'package_sources':indices} or any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=value for k,value in packages.items()):_fail()
    return p,source
