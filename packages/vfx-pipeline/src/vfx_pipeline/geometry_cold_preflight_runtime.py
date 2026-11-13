"""046准入前验源消费者后继；旧044定稿、045证明、同操作和原预算均保留。"""
from __future__ import annotations
import copy,hashlib,hmac,os
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_karma_observation import file_record
from .geometry_render_resume import _path,_read,_object,_load
from .geometry_registration_resume import _context
_SCHEMA='bridge.geometry-cold-preflight-runtime/1'
_SOURCE='bridge.geometry-cold-preflight-runtime-source/1'
_AUTH='geometry-cold-preflight-runtime-authorization.json'
_SOURCE_NAME='geometry-cold-preflight-runtime-source.json'
_DOMAIN=b'bridge.geometry-cold-preflight-runtime/1\x00'
_ORIGIN=b'bridge.geometry-cold-preflight-origin/1\x00'
_ADDED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_cold_preflight_runtime.py','runtime/tools/migrate_geometry_cold_preflight_runtime.py'}
_CHANGED={'runtime/packages/vfx-pipeline/src/vfx_pipeline/'+n+'.py' for n in ('geometry_seed_cold_resume','geometry_session','geometry_runtime_binding','geometry_job')}
_CHANGED|={'runtime/packages/nuke-bridge/src/nuke_bridge/'+n+'.py' for n in ('task_host','operation_receipts','owned_render_worker')}
_CHANGED.add('runtime/plugins/nuke/nuke_bridge_addon.py')

def _fail():raise ValueError('GEOMETRY_COLD_PREFLIGHT_RUNTIME_INVALID')
def _sign(native,p,domain=_DOMAIN):return hmac.new(hmac.new(native._key(),domain,hashlib.sha256).digest(),native._canonical(p),hashlib.sha256).hexdigest()

def _packages(original,active):
    from .geometry_runtime_binding import _package
    a,af,ars=_package(original,'0.4.5');b,bf,brs=_package(active,'0.4.6');changed={n for n in af if n in bf and af[n]!=bf[n]}
    if ((original/'scripts/bridge_mcp.py').read_bytes()!=(active/'scripts/bridge_mcp.py').read_bytes()
            or {k:v for k,v in a.items() if k!='version'}!={k:v for k,v in b.items() if k!='version'}
            or set(af)-set(bf) or set(bf)-set(af)!=_ADDED or not changed<=_CHANGED|{'plugin.json'}):_fail()
    return {'original_plugin_root':str(original),'active_plugin_root':str(active),'package_sources':ars+brs,'active_worker':file_record(active/'runtime/tools/run_geometry_creative.py'),
            'differences':[{'name':n,'before':file_record(original/n) if n in af else None,'after':file_record(active/n)} for n in sorted(changed|_ADDED)]}

def _coverage(native,inventory_record,crosswalk_record,trace_record,predecessor_effective):
    """固定本次实测清单的完整保守补集；分类来自已审核证据，不接受路径前缀豁免。"""
    from nuke_bridge.task_host import _cold_bytes,_cold_record
    inventory=_object(_read(inventory_record));table=_object(_read(crosswalk_record))
    if (inventory.get('schema')!='bridge.nuke045-authority-readset-inventory/1'
            or table.get('schema')!='bridge.cold-authority-coverage-crosswalk/1'
            or inventory.get('different_records') or inventory.get('native_started')!=0):_fail()
    traces=_object(_read(trace_record));extra=inventory['extra_actual_reads'];rows=table['rows']
    if type(extra) is not dict or type(rows) is not dict or set(extra)!=set(rows) or len(extra)>4096:_fail()
    groups={'fixed_authority_required':{'CASE_native_key','CASE_other_persistent','CASE_owned_receipts_keys_intents','CASE_hip_exr_nk','outside_other','CASE_snapshot_modules','official_alpha_source'},
            'discovery_only':{'global_discovery'},'verified_derived_temporary':{'validator_derived_temporary'}}
    fixed={};counts={key:0 for key in groups};rebases=[]
    from .geometry_seed_cold_runtime_successor import _AUTH as old_auth
    old=_object(_read(file_record(native.root/old_auth)))['payload'];formal=_path(predecessor_effective['consumer_runtime']['package_root']);former=_path(old['active_plugin_root'])
    alpha=Path('runtime/packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py')
    source=_object(_read(predecessor_effective['source']));main=source['producer']['artifact']['payload']['completion_snapshot']['1']
    source2=_object(_read(source['input_source']));typed=source2['registration_implementation']['files']['artifact_registry']
    _cold_bytes(typed)
    derived_roles=set()
    def ambient_trace(path):
        item=traces.get(path) or {};stack=item.get('caller_stack') or []
        required=(('runtime/packages/houdini-bridge/src/houdini_bridge/paths.py','bridge_tokens_for_port'),('runtime/packages/houdini-bridge/src/houdini_bridge/client.py','__init__'),('runtime/packages/vfx-pipeline/src/vfx_pipeline/workbuddy_assembly.py','production_host_client'))
        if len(stack)<3:return False
        for frame,(relative,function) in zip(stack,required):
            if frame.get('function')!=function or Path(frame.get('file',''))!=former/relative:return False
            _cold_record(formal/relative)
        return True

    for path,row in rows.items():
        if (type(row) is not dict or row.get('category') not in groups or row.get('group') not in groups[row['category']]
                or not isinstance(row.get('basis'),str) or not row['basis'] or row.get('record')!=extra[path].get('record') or row['record'].get('path')!=path):_fail()
        counts[row['category']]+=1
        if row['category']=='discovery_only':
            if not ambient_trace(path):_fail()
            continue
        if row['category']=='verified_derived_temporary':
            item=extra[path];record=item['record']
            if item.get('at_collect',{}).get('exists') is not False or any(record[key]!=main[key] for key in ('bytes','sha256')):_fail()
            lineage=item.get('decoder_lineage') or []
            if lineage:
                observed=lineage[0];stack=observed.get('caller_stack') or [];before=observed.get('before_decode') or {}
                if not stack or before.get('exists') is not True or before.get('is_file') is not True:_fail()
                function=stack[0].get('function');relative={'_render_file_observation':'runtime/packages/houdini-bridge/src/houdini_bridge/client.py','_decode_snapshot':'runtime/packages/houdini-bridge/src/houdini_bridge/controlled_output.py'}.get(function)
                if relative is None or Path(stack[0].get('file',''))!=former/relative:_fail()
                _cold_record(formal/relative);derived_roles.add(function)
            else:
                # 039原实现固定先验源SHA/身份再复制解码；该已审第三项没有当前模块decoder hook。
                text=_cold_bytes(typed).decode('utf-8')
                if "prefix='artifact-admission-frame-'" not in text or 'def _typed_admission(' not in text or Path(path).name!='frame.exr':_fail()
                derived_roles.add('_typed_admission')
            continue
        record=copy.deepcopy(row['record'])
        if Path(path)==former/alpha:
            actual=_cold_record(formal/alpha)
            if any(record[key]!=actual[key] for key in ('bytes','sha256')):_fail()
            rebases.append({'original':record,'permanent':actual,'basis':'signed045consumer same relative alpha module'});record=actual
        else:_cold_bytes(record)
        prior=fixed.get(record['path'])
        if prior is not None and prior!=record:_fail()
        fixed[record['path']]=record
    if counts['verified_derived_temporary'] and derived_roles!={'_render_file_observation','_decode_snapshot','_typed_admission'}:_fail()
    declared={record['path']:record for record in table['required_fixed_records']}
    if declared!={path:row['record'] for path,row in rows.items() if row['category']=='fixed_authority_required'}:_fail()
    if any(table['counts'].get(key)!=value for key,value in counts.items()) or table['counts'].get('classification_unknown')!=0:_fail()
    return {'schema':'bridge.cold-fixed-authority-supplement/1','inventory':inventory_record,'crosswalk':crosswalk_record,'trace_evidence':trace_record,'fixed_records':[fixed[key] for key in sorted(fixed)],'rebases':rebases,'counts':counts,'unknown':0}

def _static_source(source,native):
    """祖先已在无job阶段完整认证；之后只验原签名/原件，不要求旧runtime仍拥有新job。"""
    from . import geometry_seed_cold_resume as base,geometry_seed_cold_runtime_successor as previous
    fields={'schema','preparation','task_id','predecessor_authorization','predecessor_source','predecessor_effective','original_source','finalization_authority','finalization','cold_context','session_state','accounting_envelope','journal_prefix','evidence','authority_coverage','origin_attestation'}
    if set(source)!=fields or source.get('schema')!=_SOURCE or source.get('task_id')!=native.scope['task_id']:_fail()
    frozen=copy.deepcopy(source);attestation=frozen.pop('origin_attestation')
    expected={'schema':'bridge.geometry-cold-preflight-origin/1','source_sha256':canonical_sha256(frozen)}
    if set(attestation)!={'payload','signature'} or attestation['payload']!=expected or not hmac.compare_digest(str(attestation['signature']),_sign(native,expected,_ORIGIN)):_fail()
    record=source['predecessor_authorization'];value=_object(_read(record));p=value.get('payload')
    if (record['path']!=str(native.root/previous._AUTH) or set(value)!={'payload','signature'} or type(p) is not dict
            or not hmac.compare_digest(str(value['signature']),previous._sign(native,p)) or p.get('schema')!=previous._SCHEMA
            or p.get('preparation')!=source['preparation'] or p.get('native_scope')!=native.binding or p.get('task_id')!=source['task_id']
            or p.get('source')!=source['predecessor_source']):_fail()
    prior=_object(_read(source['predecessor_source']));effective=source['predecessor_effective']
    if (source['predecessor_source']['path']!=str(native.root/previous._SOURCE_NAME)
            or prior.get('predecessor_authorization')!=source['finalization_authority'] or prior.get('request')!=effective['request']
            or effective['finalization_authority']!=source['finalization_authority'] or effective['source']!=source['original_source']
            or effective['preparation']!=source['preparation'] or effective['native_scope']!=native.binding
            or effective['active_worker']!=p['active_worker'] or effective['consumer_runtime']!=p['consumer_runtime']):_fail()
    original,details=base._validate_original(source['preparation'],source['finalization_authority'],native)
    if original['source']!=source['original_source'] or original['request']!=effective['request']:_fail()
    base._verify_finalization(source['preparation'],source['finalization_authority'],details['nk_binding'])
    if source['finalization']!=file_record(native.root/'geometry-seed-cold-finalization.json') or source['cold_context']!=file_record(Path(details['producer']['control'])/'cold-context.json'):_fail()
    if _load(source['cold_context']['path'])!={'schema':'bridge.geometry-cold-context/1','native_scope':native.binding,'task_id':source['task_id'],'input_artifact_source':details['input_source']}:_fail()
    for item in effective['readset']:_read(item)
    if type(source['evidence']) is not dict or set(source['evidence'])!={'readonly_failure','path_diagnostic'}:_fail()
    for item in source['evidence'].values():_read(item)
    coverage=source['authority_coverage']
    if coverage!=_coverage(native,coverage['inventory'],coverage['crosswalk'],coverage['trace_evidence'],effective):_fail()
    return effective,details

def _source(source,native,*,creation=False):
    from dcc_task_runtime import geometry_seed_cold_recovery as low
    from dcc_task_runtime.geometry_budget_addendum import _prefix
    effective,original=_static_source(source,native);frozen=_prefix(native,source['journal_prefix'],source['accounting_envelope'])['state'];_,_,closed=low.validate(native,original['budget_authority'])
    if frozen!=closed or len(frozen['tickets'])!=16 or 'geometry_seed_cold_recovery' in frozen:_fail()
    request=_object(_read(effective['request']));state=source['session_state'];live=_load(native.root/'geometry-state.json');current=native._read();op=request['new_operation_id'];rid=request['request_id'];plan=request['new_plan'];pid=plan['plan_id'];directory=native.root/'jobs'/op
    if (state.get('preparation')!=source['preparation'] or state.get('task_id')!=source['task_id'] or state.get('revision')!=1 or len(state.get('completed',[]))!=1
            or op in state.get('jobs',{}) or pid in state.get('plans',{}) or rid in state.get('execution_requests',{}) or pid in state.get('plan_operations',{})
            or any(j.get('state') not in ('COMPLETE','FAILED','CANCELLED') for j in state.get('jobs',{}).values()) or current['tickets'][:16]!=closed['tickets']):_fail()
    if creation:
        absent=(directory,native.root/'geometry-seed-cold-resume-dispatch.json',_path(original['nk_binding']['output_pattern']%1))
        if current!=closed or live!=state or any(path.exists() or path.is_symlink() for path in absent):_fail()
    else:
        for section in ('plans','jobs','execution_requests','plan_operations'):
            if any(live.get(section,{}).get(k)!=v for k,v in state[section].items()):_fail()
        if live.get('preparation')!=source['preparation'] or live.get('task_id')!=source['task_id'] or live.get('revision') not in (1,2) or live.get('completed') not in (state['completed'],state['completed']+[op]):_fail()
        if op not in live['jobs']:
            expected=copy.deepcopy(state)
            if pid in live['plans']:expected['plans'][pid]=plan
            open16=dict(closed,closed_reason=None,geometry_seed_cold_recovery=original['budget_authority'])
            if live!=expected or directory.exists() or current not in (closed,open16):_fail()
        elif (set(live['jobs'])!=set(state['jobs'])|{op} or set(live['plans'])!=set(state['plans'])|{pid} or live['plans'][pid]!=plan
                or set(live['execution_requests'])!=set(state['execution_requests'])|{rid} or set(live['plan_operations'])!=set(state['plan_operations'])|{pid}
                or live['execution_requests'][rid]!={'request_sha256':canonical_sha256({'plan_id':pid}),'operation_id':op} or live['plan_operations'][pid]!=op):_fail()
    return effective,original

def inspect_source(preparation,formal045,readonly_failure,path_diagnostic,coverage_groups,coverage_evidence):
    """无job/closed16阶段完整认证045祖先，封存精确静态证书；不重跑HOM或改旧证明。"""
    from . import geometry_seed_cold_runtime_successor as previous
    from .geometry_runtime_binding import _package
    _,native=_context(preparation);authority=file_record(native.root/previous._AUTH);effective,original=previous.validate(preparation,authority,native)
    proof=_object(_read(authority))['payload'];formal=_path(formal045);_,_,indices=_package(formal,'0.4.5')
    if effective['consumer_runtime']!={'package_root':str(formal),'package_sources':indices}:_fail()
    raw=native.journal_path.read_bytes();value={'schema':_SOURCE,'preparation':preparation,'task_id':native.scope['task_id'],'predecessor_authorization':authority,'predecessor_source':proof['source'],'predecessor_effective':effective,
        'original_source':effective['source'],'finalization_authority':effective['finalization_authority'],'finalization':file_record(native.root/'geometry-seed-cold-finalization.json'),
        'cold_context':file_record(Path(original['producer']['control'])/'cold-context.json'),'session_state':_load(native.root/'geometry-state.json'),'accounting_envelope':_load(native.state_path),
        'journal_prefix':{'path':str(native.journal_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'evidence':{'readonly_failure':readonly_failure,'path_diagnostic':path_diagnostic}}
    value['authority_coverage']=_coverage(native,path_diagnostic,coverage_groups,coverage_evidence,effective)
    certificate={'schema':'bridge.geometry-cold-preflight-origin/1','source_sha256':canonical_sha256(value)};value['origin_attestation']={'payload':certificate,'signature':_sign(native,certificate,_ORIGIN)}
    _source(value,native,creation=True);return value

def validate(preparation,record,native=None):
    _,n=_context(preparation);native=n if native is None else native
    if record.get('path')!=str(native.root/_AUTH) or _path(record['path']).stat().st_mode&0o077:_fail()
    value=_object(_read(record));p=value.get('payload');fields={'schema','preparation','native_scope','task_id','source','consumer_runtime','original_plugin_root','active_plugin_root','package_sources','active_worker','differences'}
    if (set(value)!={'payload','signature'} or type(p) is not dict or set(p)!=fields or not hmac.compare_digest(str(value['signature']),_sign(native,p))
            or p['schema']!=_SCHEMA or p['preparation']!=preparation or p['native_scope']!=native.binding or p['task_id']!=native.scope['task_id'] or p['source']['path']!=str(native.root/_SOURCE_NAME)):_fail()
    frozen=_object(_read(p['source']))
    if frozen.get('preparation')!=preparation or frozen.get('task_id')!=p['task_id']:_fail()
    old,original=_source(frozen,native)
    from .geometry_runtime_binding import _package,_rebase_package
    formal=_path(p['consumer_runtime']['package_root']);_,_,indices=_package(formal,'0.4.6')
    if p['consumer_runtime']!={'package_root':str(formal),'package_sources':indices}:_fail()
    packages=_packages(_path(p['original_plugin_root']),formal)
    if any(_rebase_package(p[k],_path(p['active_plugin_root']),formal)!=v for k,v in packages.items()):_fail()
    if old['consumer_runtime']['package_root']!=p['original_plugin_root']:_fail()
    request=_object(_read(old['request']));jobpath=native.root/'jobs'/request['new_operation_id']/'job.json'
    if jobpath.exists():
        job=_load(jobpath)
        if job.get('runtime_continuation')!=record or job.get('execution_worker')!=p['active_worker']:_fail()
    effective=copy.deepcopy(old);effective.update(active_worker=p['active_worker'],consumer_runtime=p['consumer_runtime'])
    effective['readset']=[*old['readset'],p['source'],frozen['predecessor_authorization'],frozen['predecessor_source'],frozen['finalization'],frozen['cold_context'],*frozen['evidence'].values(),frozen['authority_coverage']['inventory'],frozen['authority_coverage']['crosswalk'],frozen['authority_coverage']['trace_evidence'],*frozen['authority_coverage']['fixed_records'],*packages['package_sources']]
    return effective,original

def create_authorization(preparation,source_record,formal045,active046,formal046):
    """仅签046消费者和本操作的准入前proof路径；不签新预算或改044定稿。"""
    prep,native=_context(preparation);original=_path(formal045);active=_path(active046);formal=_path(formal046)
    if active!=Path(prep['worker']).parents[2].with_name('0.4.6') or source_record['path']!=str(native.root/_SOURCE_NAME):_fail()
    source=_object(_read(source_record))
    if source.get('preparation')!=preparation or source.get('task_id')!=prep['task_id']:_fail()
    old,_=_source(source,native,creation=True)
    if old['consumer_runtime']['package_root']!=str(original):_fail()
    packages=_packages(original,active)
    from .geometry_runtime_binding import _package
    a,af,_=_package(active,'0.4.6');b,bf,indices=_package(formal,'0.4.6')
    if a!=b or af!=bf or active==formal or formal.is_relative_to(native.root):_fail()
    payload={'schema':_SCHEMA,'preparation':preparation,'native_scope':native.binding,'task_id':prep['task_id'],'source':source_record,'consumer_runtime':{'package_root':str(formal),'package_sources':indices},**packages}
    path=native.root/_AUTH;fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(native._canonical({'payload':payload,'signature':_sign(native,payload)})+b'\n');stream.flush();os.fsync(stream.fileno())
    return file_record(path)

def effective(preparation,runtime,authority):
    prep,native=_context(preparation);runtime=_path(runtime)
    if runtime!=Path(prep['worker']).parents[2].with_name('0.4.6')/'runtime' or authority!=file_record(native.root/_AUTH):_fail()
    value,source=validate(preparation,authority,native);proof=_object(_read(authority))['payload'];packages=_packages(_path(proof['original_plugin_root']),runtime.parent)
    if any(proof[k]!=v for k,v in packages.items()):_fail()
    native.check();return value,source


def authoritative_input_records(native,source):
    """controller只接已签046 runtime；结果为完整固定原件FileRecords列表。"""
    preparation=file_record(native.root/'geometry-preparation.json');authority=file_record(native.root/_AUTH)
    from .geometry_prelaunch_tail import _AUTH as tail_auth,validate as tail_validate
    tail_record=file_record(native.root/tail_auth) if (native.root/tail_auth).exists() else None
    if tail_record is not None:p,original=tail_validate(preparation,tail_record,native)
    else:p,original=validate(preparation,authority,native)
    proof=_object(_read(authority))['payload'];sealed=_object(_read(proof['source']))
    supplied=_object(_read(source)) if isinstance(source,dict) and set(source)=={'path','bytes','sha256'} else source
    if supplied!=_object(_read(original['input_source'])):_fail()
    return _authoritative_records(native,sealed,p,original,supplied,[authority,proof['source'],*([tail_record] if tail_record else [])])


def inspect_authoritative_input_records(native,sealed):
    """构包前纯读检查；认证内存origin证书/closed16，不造046授权或执行proof。"""
    p,original=_source(sealed,native,creation=True);supplied=_object(_read(original['input_source']))
    return _authoritative_records(native,sealed,p,original,supplied,[])


def _authoritative_records(native,sealed,p,original,supplied,authority_records):
    from nuke_bridge.task_host import _cold_bytes,_cold_record
    dynamic={native.state_path,native.journal_path,native.anchor_path,native.root/'geometry-state.json',native.root/'artifact_ledger/artifacts.sqlite3'}
    records={};snapshots={}
    def add(record):
        if type(record) is not dict or set(record)!={'path','bytes','sha256'}:_fail()
        path=Path(record['path'])
        if path in dynamic:return
        prior=records.get(str(path))
        if prior is not None:
            if prior!=record:_fail()
            return
        if len(records)>=4096:_fail()
        _cold_bytes(record);records[str(path)]=copy.deepcopy(record)
        if path.name=='snapshot-manifest.json':snapshots[str(path)]=record
    def physical(path):
        record=_cold_record(Path(path));add(record);return record
    for record in authority_records:add(record)
    # 原044来源证书已认证042永久consumer索引；供既有manifest展开精确补齐祖先代码。
    add(original['origin_certificate']['payload']['formal042'])
    coverage=sealed['authority_coverage'];add(coverage['inventory']);add(coverage['crosswalk']);add(coverage['trace_evidence'])
    for record in coverage['fixed_records']:add(record)
    for record in p['readset']:add(record)
    for key in ('producer_scope','producer_manifest','producer_snapshot_manifest','producer_deployment','producer_owners'):add(supplied[key])
    physical(native.key_path)
    main=original['producer']['artifact']['payload']['completion_snapshot']['1'];add({key:main[key] for key in ('path','bytes','sha256')})
    closed=sealed['accounting_envelope']['payload']['state']
    for directory in sorted({ticket['directory'] for ticket in closed['tickets']}):
        for name in ('started.json','stopped.json','receipt.key','intent.json'):physical(Path(directory)/name)
    # 首版已接纳产物与图原件是明确schema依赖，不能只收producer第二版的source_files。
    initial=sealed['session_state'];first=initial['jobs'][initial['completed'][0]]
    if not isinstance(first.get('result'),dict) or not isinstance(first.get('acceptance'),dict):_fail()
    add(first['result']);add(first['acceptance']);accepted=_object(_cold_bytes(first['result']))
    if accepted.get('schema')!='bridge.geometry-revision/1' or not isinstance(accepted.get('files'),dict):_fail()
    for record in accepted['files'].values():add(record)
    graph=accepted.get('graph_source') or {}
    for record in graph.get('source_files',[]):add(record)
    if graph.get('snapshot_manifest'):add(graph['snapshot_manifest'])
    # 外部alpha只展开已验owners声明的terminal/sources/native_operations字段。
    owners=_object(_cold_bytes(supplied['producer_owners']))
    for owner in owners.values():
        if not isinstance(owner,dict) or not owner.get('alpha_calibration'):continue
        alpha=owner['alpha_calibration'];add(alpha['calibration_source'])
        reuse=alpha.get('plugin_reuse') or {}
        for key in ('active_plugin','source_plugin'):
            if key in reuse:add(reuse[key])
        terminal=physical(Path(alpha['directory'])/'alpha-calibration.json');wrapped=_object(_cold_bytes(terminal));payload=wrapped['payload']
        if not isinstance(payload.get('sources'),dict) or not isinstance(payload.get('native_operations'),dict):_fail()
        for record in payload['sources'].values():
            add(record);data=_object(_cold_bytes(record))
            if 'chart' in data:add(data['chart'])
            for image in data.get('images',[]):add(image)
        for operation in payload['native_operations'].values():
            directory=Path(operation['directory'])
            for name in ('started.json','stopped.json','receipt.key','intent.json'):physical(directory/name)
            output=physical(directory/'alpha-output.json');data=_object(_cold_bytes(output))['payload']
            for key in ('chart','executable','scene','source'):
                if key in data:add(data[key])
            for image in data.get('images',[]):add(image)
            for item in (data.get('sources') or {}).values():add(item)
    # snapshot索引只允许原相对路径+sha，不追随日志里的任意三元声明。
    for record in list(snapshots.values()):
        path=Path(record['path']);index=_object(_cold_bytes(record))
        if set(index)!={'files'} or not isinstance(index['files'],list):_fail()
        for item in index['files']:
            if type(item) is not dict or set(item)!={'path','sha256'}:_fail()
            relative=Path(item['path'])
            if relative.is_absolute() or '..' in relative.parts:_fail()
            actual=physical(path.parent/'snapshot'/relative)
            if actual['sha256']!=item['sha256']:_fail()
    return [records[key] for key in sorted(records)]
