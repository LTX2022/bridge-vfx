"""固定RectLight单帧已签名同步完成后的受控输出核验；不改变原生失败或停止事实。"""
from __future__ import annotations
import copy,hashlib,importlib.util,json,math,os,stat,threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.owned_process import read_receipt,execution_returncode
from houdini_bridge.official_karma_observation import checked_bytes,file_record
from houdini_bridge import client
TASK='7c65a89096e84533b8f0ace596cfe1c2'
OP='creative_bff6f898fafe1db03aae_render'
VERIFY='creative_bff6f898fafe1db03aae_terminal_verify'
PINS={'source_scope':'3e1db4088448f6410bb5b38b659ec1254c834e31e7356e0c1e5a8e040110e5b1',
 'source_signed_state':'d17eb5e9ecd65bc24173c59f57e36099eb15a153af091a8273bb7d985dc17614',
 'source_journal':'5f09470f8ceb2b25a21481b4fb98248a92d8a3b56c87a25bdc41199aba8e5d7f',
 'operation_store':'b8c3ef7690db4604ab9a8e2600398141e0d5fb067cbccbb5464f4bd35fd61550',
 'original_owners':'75ec65e2d688843b8d25719f96449372ae92bae9f8ab8331e188d913192c5838',
 'frame':'a86b52dc0d2fd9132f026bf590b9ed28a6038f5f4e9e6635a370451dea624a22'}
STAGES={'checkpoint_readback','checkpoint_reopen','cold_readback','cold_reopen','formal_save','render','render_completed','save_host_stop'}
def _fail():raise ValueError('RECT_SIGNED_RENDER_TERMINAL_RECOVERY_UNPROVEN')
def _json(record):return json.loads(checked_bytes(record))
def _case_paths(proof_record):
 """位置只能来自原固定摘要的已认证范围，不把开发机器目录写入发行包。"""
 from dcc_task_runtime.native_scope import NativeScope
 proof=_json(proof_record);record=proof.get('source_scope',{})
 if record.get('sha256')!=PINS['source_scope']:_fail()
 scope=NativeScope({k:record[k] for k in ('path','sha256')})
 case=Path(scope.scope['creative_phase']['case_contract']['path']).parent
 if case!=scope.root/'continuations/luna-rectlight-01':_fail()
 execution=case/'jobs/creative_bff6f898fafe1db03aae/executions/save-repair-02'
 return case,execution,execution/'project/control'

def _epoch(value):
 result=datetime.fromisoformat(value).timestamp()
 if not math.isfinite(result):_fail()
 return result

def _terminal_shape(record,fact,started,stopped,writer):
 """只接受同步返回和完整快照先于所有者超时；writer退出码继续未知。"""
 life=record.get('lifecycle_fact') or {};snapshots=fact.get('frame_snapshots') or {}
 if (record.get('state')!='COMPLETED' or record.get('stage')!='render_all_frames_collected'
     or record.get('frames')!=[1] or record.get('frames_done')!=[1] or fact.get('state')!='COMPLETED'
     or fact.get('frame_set')!=[1] or fact.get('frames_done')!=[1] or set(snapshots)!={'1'}
     or fact.get('completion_metadata_status')!='BLOCKED_MISSING_NATIVE_FACTS'
     or life.get('kind')!='STOP_CONFIRMED' or life.get('source')!='houdini/native_render_returned'
     or life.get('stop_confirmed') is not True or life.get('process_exited') is not False or life.get('exit_code') is not None
     or fact.get('stop_basis')!=life or stopped.get('stop_reason')!='TIME_BUDGET_EXCEEDED'
     or execution_returncode(stopped)!=-15 or started.get('pid')!=24872 or stopped.get('pid')!=24872):_fail()
 snapshot=snapshots['1'];finished=_epoch(record['finished_at']);stop=stopped['observed_at'];observed=snapshot['observed_at_epoch']
 if (fact.get('finished_at')!=record['finished_at'] or not all(type(x) in (int,float) and math.isfinite(x) for x in (stop,observed))
     or not started['observed_at']<=record['started_at_epoch']<=observed<=finished<stop
     or snapshot['modified_ns']/1e9>observed or snapshot.get('sha256')!=PINS['frame']):_fail()
 process=writer.get('process_observation') or {}
 if (process.get('identity_verification')!='OS_IMAGE_AND_ANCESTRY_BOUND' or process.get('pid')!=25403 or process.get('parent_pid')!=24872):_fail()
 return {'schema':'bridge.rectlight-render-terminal-basis/1','basis':'signed_synchronous_render_completed_before_owner_timeout',
  'native_return_complete':True,'owner_exit_code':-15,'owner_stop_reason':'TIME_BUDGET_EXCEEDED',
  'writer_exit_code':None,'writer_exit_status':'NOT_OBSERVED','writer_pid':25403,'owner_pid':24872,
  'finished_at':record['finished_at'],'snapshot_observed_at_epoch':observed,'owner_stopped_at_epoch':stop}

def _validate_historical_render_terminal_recovery(proof_record):
 """每次派生、登记和Nuke历史重验均读取同一签名原件；不启动或修补原宿主。"""
 from dcc_task_runtime.native_scope import NativeScope
 from vfx_pipeline.official_graph_resume import _snapshot
 from houdini_bridge.operation_receipts import validate_operation_receipt
 from houdini_bridge.official_case_variant import verified_reopen_parameters,CHANGES
 from houdini_bridge.render_writer_facts import validate_writer_observation,writer_root
 CASE,EXEC,CONTROL=_case_paths(proof_record)
 proof=_json(proof_record)
 keys={'schema','source_job','source_preparation','source_journal','source_error','source_scope','source_signed_state','source_snapshot_manifest','producer_deployment','original_owners','operation_store','terminal_receipt','owner_started','owner_stopped','writer_context','writer_receipt','formal_save_record','hip','scene_snapshot','frame','configuration'}
 if (set(proof)!=keys or proof.get('schema')!='bridge.rectlight-render-terminal-recovery/1'
     or Path(proof_record['path'])!=EXEC/'render-terminal-proof.json'
     or any(proof[k].get('sha256')!=v for k,v in PINS.items())):_fail()
 scope=NativeScope({k:proof['source_scope'][k] for k in ('path','sha256')});usage=scope.snapshot()
 if (Path(proof['source_scope']['path'])!=scope.root/'continuations/luna-rectlight-06/scope.json'
     or Path(proof['source_signed_state']['path'])!=scope.state_path
     or scope._verify_envelope(_json(proof['source_signed_state']))['state']['tickets']!=usage['tickets']
     or len(usage['tickets'])!=48 or any(t['stopped_at'] is None for t in usage['tickets'])
     or usage.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'):_fail()
 job=_json(proof['source_job']);prep=_json(proof['source_preparation']);journal=_json(proof['source_journal'])
 if (Path(proof['source_job']['path'])!=EXEC/'job.json' or Path(proof['source_journal']['path'])!=EXEC/'incremental-state.json'
     or job.get('directory')!=str(EXEC) or job.get('operation_id')!='creative_bff6f898fafe1db03aae'
     or job.get('preparation')!=proof['source_preparation'] or prep.get('scope')!=scope.binding
     or prep.get('task_id')!=TASK or prep.get('case_id')!='karma_lights_rectlight_v1'
     or journal.get('preparation')!=proof['source_job'] or set(journal.get('stages',{}))!=STAGES
     or any(v.get('state')!=('INTENT' if k=='render_completed' else 'DONE') for k,v in journal['stages'].items())
     or _json(proof['source_error'])!={'code':'ValueError','message':'NATIVE_SCOPE_EXECUTION_FAILED','native_success_claimed':False}
     or Path(proof['source_error']['path'])!=EXEC/'error.json' or proof['configuration']!=prep['configuration']):_fail()
 if (Path(proof['original_owners']['path'])!=EXEC/'render-terminal-recovery/original-owners.json'
     or Path(proof['producer_deployment']['path'])!=CONTROL/'production-hosts.json'
     or _snapshot(CONTROL)!=proof['source_snapshot_manifest']):_fail()
 owners=_json(proof['original_owners']);original_binding=owners.get(OP)
 if not isinstance(original_binding,dict):_fail()
 source=client.read_render_operation(original_binding,task_id=TASK,operation_id=OP);record=source['operation'];fact=source['execution_fact']
 if (Path(proof['operation_store']['path'])!=Path(original_binding['operation_store_path'])
     or _json(proof['operation_store'])['operations'][OP]!=record
     or client.render_producer_binding(record)!=original_binding['producer_binding']):_fail()
 client._verify_render_terminal(original_binding,fact)
 supervisor=original_binding['supervisor_binding'];event=client._render_terminal_event(original_binding['producer_binding']);directory=Path(supervisor['directory'])
 if (Path(proof['terminal_receipt']['path'])!=directory/(event+'.json')
     or Path(proof['owner_started']['path'])!=directory/'started.json' or Path(proof['owner_stopped']['path'])!=directory/'stopped.json'):_fail()
 for key in ('terminal_receipt','owner_started','owner_stopped'):checked_bytes(proof[key])
 started=read_receipt(directory,'started',identity=supervisor['identity']);stopped=read_receipt(directory,'stopped',identity=supervisor['identity'])
 if not started or not stopped or (started.get('resource_budget') or {}).get('native_scope')!=scope.binding:_fail()
 matching=[t for t in usage['tickets'] if t['role']=='houdini-host' and t.get('parent') is None and t['directory']==str(directory) and t['identity']==supervisor['identity']]
 delegated=[t for t in usage['tickets'] if t['role']=='main-husk' and t.get('parent') is not None and t['directory']==str(directory)]
 if len(matching)!=1 or len(delegated)!=1 or usage['tickets'][-1]!=delegated[0] or matching[0]['stopped_at']!=stopped['observed_at']:_fail()
 writer=record.get('writer_observations',{}).get('1')
 if not isinstance(writer,dict):_fail()
 writer_directory=Path(writer['directory'])
 if (Path(proof['writer_context']['path'])!=writer_directory/'context.json' or Path(proof['writer_receipt']['path'])!=writer_directory/'observation.json'):_fail()
 checked_bytes(proof['writer_context']);checked_bytes(proof['writer_receipt'])
 body=validate_writer_observation(writer,client.render_receipt_digest(original_binding['producer_binding']),1,fact['frame_snapshots']['1'],expected_root=writer_root(record),host_identity=record['host_identity'],supervisor_binding=record['supervisor_binding'])
 basis=_terminal_shape(record,fact,started,stopped,body)
 saved=journal['stages']['formal_save']['result'];formal=saved['operation_receipt'];validate_operation_receipt(formal)
 if (formal.get('command')!='scene.save_hip' or formal.get('task_id')!=TASK
     or proof['formal_save_record']!=file_record(Path(saved['operation_store_path'])) or _json(proof['formal_save_record'])!=formal
     or saved['scene_contract_sha256']!=canonical_sha256(saved['scene_contract'])
     or proof['hip']!=file_record(Path(saved['path'])) or proof['hip']['sha256']!=saved['sha256']
     or proof['scene_snapshot']!=file_record(Path(record['scene']['snapshot_path'])) or proof['scene_snapshot']['sha256']!=saved['sha256']
     or record['scene']['scene_contract_sha256']!=saved['scene_contract_sha256']):_fail()
 configuration=_json(proof['configuration']);cold=journal['stages']['cold_reopen']['result']
 readback=journal['stages']['cold_readback']['result']
 if set(readback.get('parms',{}))!={'xn__inputsexposure_control_wcb','xn__inputsexposure_vya'}:_fail()
 actual=verified_reopen_parameters(cold,saved,configuration,record['host_identity'],list(readback['parms']))
 if (actual!=journal['stages']['cold_readback']['result'] or actual['parms']['xn__inputsexposure_vya']!=-0.25
     or saved['scene_contract']!=record['scene_contract_evidence']
     or proof['frame']!=file_record(Path(record['output_pattern']%1))):_fail()
 save_identity=formal['host_identity'];save_tickets=[t for t in usage['tickets'] if t['role']=='houdini-host' and t['identity'].get('launch_nonce')==save_identity.get('launch_nonce')]
 if len(save_tickets)!=1 or execution_returncode(scope._stop(save_tickets[0]))!=0:_fail()
 deployment=_json(proof['producer_deployment']);host=deployment.get('hosts',{}).get('houdini',{})
 if (host.get('native_scope')!=scope.binding or host.get('controller_root')!=str(CONTROL)
     or any(host.get('expected_identity',{}).get(k)!=record['host_identity'].get(k) for k in ('task_id','pid','launch_nonce','plugin_build','process_generation','session_id'))
     or host.get('output_acceptance')!=record['output_acceptance']):_fail()
 basis.update(proof=copy.deepcopy(proof_record),proof_sha256=proof_record['sha256'],terminal_receipt_sha256=proof['terminal_receipt']['sha256'],source_scope=proof['source_scope'])
 return {'control':str(CONTROL),'basis':basis,'binding':copy.deepcopy(original_binding),'source_scope':copy.deepcopy(proof['source_scope']),
  'policy':copy.deepcopy(record['output_acceptance']),'alpha_calibration':copy.deepcopy(host['alpha_calibration']),
  'saved':saved,'original_fact':fact,'started':started,'stopped':stopped,'source_preparation':prep,
  '_historical_tickets':copy.deepcopy(usage['tickets']),'_historical_scope':copy.deepcopy(scope.scope)}

_HISTORY_CACHE=OrderedDict()
_HISTORY_GUARD=threading.Lock()
_HISTORY_LIMIT=2


def _historical_environment(proof_record=None):
 """历史来源若成为当前执行范围则不缓存；目标消费者状态始终另行实时读取。"""
 raw=os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')
 if raw is None:return True
 try:value=json.loads(raw)
 except (TypeError,ValueError):return False
 return (type(value) is dict and set(value)=={'path','sha256'} and type(value.get('path')) is str
  and type(value.get('sha256')) is str and len(value['sha256'])==64
  and all(ch in '0123456789abcdef' for ch in value['sha256'])
  and proof_record is not None and value['path']!=_json(proof_record)['source_scope']['path'])


def _historical_dependencies(proof_record):
 """只枚举已停止source06、原校准和源码；不纳入当前消费者、ledger或模型结果。"""
 from dcc_task_runtime.native_scope import NativeScope
 from houdini_bridge import case_source_cache as dependency
 import importlib
 if not _historical_environment(proof_record):raise dependency._NotCacheable()
 CASE,EXEC,CONTROL=_case_paths(proof_record)
 proof=_json(proof_record);source=NativeScope({k:proof['source_scope'][k] for k in ('path','sha256')});usage=source.snapshot()
 if len(usage['tickets'])!=48 or any(t['stopped_at'] is None for t in usage['tickets']):raise dependency._NotCacheable()
 configuration=_json(proof['configuration'])
 result=dependency._dependencies(configuration)
 paths=set(result);strict={name for name,value in result.items() if value[1]};seen_json=set();queue=[];walk_budget=[600000]
 def add(raw,tree=False):
  path=Path(raw)
  if not path.is_absolute() or path!=path.resolve() or any(x.is_symlink() for x in (path,*path.parents)):raise dependency._NotCacheable()
  if not path.exists():raise dependency._NotCacheable()
  paths.add(str(path));paths.update(str(x) for x in path.parents)
  if tree:
   if path.is_dir():strict.add(str(path))
   for item in path.rglob('*'):
    if len(paths)>20000 or item.is_symlink():raise dependency._NotCacheable()
    paths.add(str(item))
    if item.is_dir():strict.add(str(item))
  if len(paths)>20000:raise dependency._NotCacheable()
 def walk(value):
  walk_budget[0]-=1
  if walk_budget[0]<0:raise dependency._NotCacheable()
  if isinstance(value,dict):
   for key,item in value.items():walk(key);walk(item)
  elif isinstance(value,(list,tuple)):
   for item in value:walk(item)
  elif isinstance(value,str) and value.startswith('/') and len(value)<4096 and '\0' not in value and '\n' not in value:
   path=Path(value)
   try:
    if path.is_file():add(path)
   except OSError:raise dependency._NotCacheable()
 def json_file(path):
  path=Path(path)
  if str(path) in seen_json:return
  seen_json.add(str(path));add(path)
  if path.stat().st_size>8*1024*1024:raise dependency._NotCacheable()
  walk(json.loads(path.read_text()))
 add(proof_record['path']);walk(proof)
 for record in proof.values():
  if isinstance(record,dict) and str(record.get('path','')).endswith('.json'):json_file(record['path'])
 # 历史fx原件与整份不可变生产快照含writer key、正式save/cold、终态签名与源模块。
 add(CONTROL/'snapshot',tree=True);add(CONTROL/'houdini-instances/fx_operations',tree=True);add(EXEC/'render-terminal-recovery',tree=True)
 for path in (CONTROL/'run.json',CONTROL/'production-hosts.json',CONTROL/'snapshot-manifest.json',
              CONTROL/'host-state/houdini-operation-owners.json',CONTROL/'host-state'/('verified-output-'+VERIFY+'.json')):
  json_file(path)
 current=source;seen=set()
 while current is not None:
  if str(current.path) in seen:raise dependency._NotCacheable()
  seen.add(str(current.path))
  for path in current._setup_file_stats:add(path)
  for name in ('path','state_path','key_path','journal_path','anchor_path','_continuation_claim_path'):
   path=getattr(current,name,None)
   if path is not None:add(path)
  current=getattr(current,'_continuation_previous',None)
 for ticket in usage['tickets']:add(ticket['directory'],tree=True)
 for name in ('vfx_pipeline.rectlight_render_terminal_recovery','vfx_pipeline.official_graph_resume','vfx_pipeline.workbuddy_assembly','vfx_pipeline.creative_results',
              'nuke_bridge.task_host','nuke_bridge.operation_receipts','houdini_bridge.controlled_output','houdini_bridge.client',
              'houdini_bridge.render_writer_facts','houdini_bridge.render_observation_budget','houdini_bridge.operation_receipts',
              'houdini_bridge.alpha_reuse','houdini_bridge.official_case_variant','houdini_bridge.official_karma_observation',
              'dcc_task_runtime.native_scope','dcc_task_runtime.owned_process','dcc_task_runtime.process_image'):
  add(Path(importlib.import_module(name).__file__))
 result={name:(dependency._stamp(name,name in strict),name in strict) for name in sorted(paths,key=lambda x:(len(Path(x).parts),x))}
 if len(result)>20000 or sum(value[0][3] for value in result.values() if stat.S_ISREG(value[0][2]))>2*1024*1024*1024:raise dependency._NotCacheable()
 return result


def _cached_historical(proof_record):
 """进程内至多两份历史认证；冷验前后完整依赖一致，暖读前后均检查。"""
 from houdini_bridge import case_source_cache as dependency
 key=canonical_sha256(proof_record)
 def discard(entry=None):
  with _HISTORY_GUARD:
   if entry is None or _HISTORY_CACHE.get(key) is entry:_HISTORY_CACHE.pop(key,None)
 if not _historical_environment(proof_record):discard();return _validate_historical_render_terminal_recovery(proof_record)
 with _HISTORY_GUARD:
  entry=_HISTORY_CACHE.get(key)
  if entry is not None:_HISTORY_CACHE.move_to_end(key)
 if entry is not None:
  if dependency._stable(entry['dependencies']):
   result=copy.deepcopy(entry['value'])
   if dependency._stable(entry['dependencies']) and _historical_environment(proof_record):return result
  discard(entry)
 try:before=_historical_dependencies(proof_record)
 except (OSError,ValueError,KeyError,TypeError,dependency._NotCacheable):return _validate_historical_render_terminal_recovery(proof_record)
 result=_validate_historical_render_terminal_recovery(proof_record)
 try:after=_historical_dependencies(proof_record)
 except (OSError,ValueError,KeyError,TypeError,dependency._NotCacheable):return _validate_historical_render_terminal_recovery(proof_record)
 if before!=after or not dependency._stable(before) or not _historical_environment(proof_record):return _validate_historical_render_terminal_recovery(proof_record)
 with _HISTORY_GUARD:
  _HISTORY_CACHE[key]={'dependencies':before,'value':copy.deepcopy(result)};_HISTORY_CACHE.move_to_end(key)
  while len(_HISTORY_CACHE)>_HISTORY_LIMIT:_HISTORY_CACHE.popitem(last=False)
 return result


def _validate_consumer_target(continuation_scope,result,nuke_retry_recovery=None):
 """实时认证目标身份、当前签名票据；这些值不进入历史缓存。"""
 from dcc_task_runtime.native_scope import NativeScope
 target=continuation_scope if hasattr(continuation_scope,'snapshot') else NativeScope(continuation_scope)
 historical=result['_historical_scope'];source=result['source_scope'];root=Path(historical['output_root'])
 if nuke_retry_recovery is not None:
  from .creative_results import validate_nuke_retry_recovery
  retry=validate_nuke_retry_recovery(nuke_retry_recovery,target);usage=retry['usage'];prior=retry['historical_usage']
  if (target.path!=root/'continuations/luna-rectlight-08/scope.json' or retry['source_scope']!=source
      or prior.get('dcc_starts')!=49 or prior['tickets'][:48]!=result['_historical_tickets']
      or usage['tickets'][:49]!=prior['tickets'] or any(t.get('stopped_at') is None for t in prior['tickets'])
      or retry.get('retry_operation_id')!='nrend-cd8fc492bb4b1171'):_fail()
  extra=usage['tickets'][49:];operation=retry['retry_operation_id']
  if (len(extra)>1 or any(t.get('role')!='nuke-render' or t.get('identity',{}).get('operation_id')!=operation
       or t.get('directory')!=str(root/'state/nuke_renders'/(operation+'.supervisor')) for t in extra)):_fail()
  return copy.deepcopy(retry['contract'])
 usage=target.snapshot()
 if (target.scope.get('continuation_of')!=source or target.scope.get('creative_phase')!=historical['creative_phase']
     or target.scope.get('budget')!=historical['budget'] or target.root!=root
     or target.path!=root/'continuations/luna-rectlight-07/scope.json' or usage['tickets'][:48]!=result['_historical_tickets']):_fail()
 extra=usage['tickets'][48:];operation='nrend-'+hashlib.sha256(b'creative_bff6f898fafe1db03aae_nuke').hexdigest()[:16]
 if (len(extra)>1 or any(t.get('role')!='nuke-render' or t.get('identity',{}).get('operation_id')!=operation
         or t.get('directory')!=str(root/'state/nuke_renders'/(operation+'.supervisor')) for t in extra)):_fail()


def validate_render_terminal_recovery(proof_record,continuation_scope=None,*,binding=None,verification_id=VERIFY,nuke_retry_recovery=None):
 """历史core可缓存；目标消费者与调用绑定每次现验，受控像素政策不缓存。"""
 if verification_id!=VERIFY:_fail()
 result=_cached_historical(proof_record)
 if binding is not None and binding!=result['binding']:_fail()
 if nuke_retry_recovery is not None and continuation_scope is None:_fail()
 if continuation_scope is not None:
  retry=_validate_consumer_target(continuation_scope,result,nuke_retry_recovery)
  if retry is not None:result['_consumer_retry_contract']=retry
 return result

def install_render_terminal_verification_owner(proof_record,authorization,*,active_scope=None):
 """可信控制端安装独立核验owner；不改原render owner或COMPLETED原件。"""
 result=validate_render_terminal_recovery(proof_record,active_scope)
 CASE,EXEC,CONTROL=_case_paths(proof_record)
 source_path=CONTROL/'snapshot/plugins/nuke/nuke_bridge_addon.py';spec=importlib.util.spec_from_file_location('_rectlight_terminal_control',source_path);addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
 verified=addon._verify_control_authorization('install_render_terminal_verification_owner',{'preparation':proof_record,'verification_id':VERIFY},authorization)
 path=CONTROL/'host-state/houdini-operation-owners.json'
 from vfx_pipeline.workbuddy_assembly import _persist_boundary_binding
 with execution_lock(CONTROL/'host-state',TASK):
  owners=json.loads(path.read_text());original=_json(_json(proof_record)['original_owners'])
  if owners!=original or VERIFY in owners:raise ValueError('RECT_TERMINAL_OWNER_QUERY_EXISTING_REQUIRED')
  owner={'task_id':TASK,'operation_kind':'output-verification','parent_operation_id':OP,'producer_binding':result['binding']['producer_binding'],
   'policy':result['policy'],'alpha_calibration':result['alpha_calibration'],'evidence_source':'real_host',
   'historical_scope':result['source_scope'],'render_terminal_recovery':proof_record}
  owners[VERIFY]=owner;_persist_boundary_binding(path,owners)
  if json.loads(path.read_text()).get(OP)!=original[OP]:_fail()
 return {'verification_id':VERIFY,'owner':owner,'verified_by':verified,'native_starts_added':0}
