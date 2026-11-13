"""固定RectLight作业的可信未启动收束；不导出MCP，不把未知启动当作停止。"""
from __future__ import annotations
import ast,copy,hashlib,importlib.util,json,os,shlex,subprocess,time
from pathlib import Path
from dcc_task_runtime.graph_scheduler import GraphScheduler
from dcc_task_runtime.execution_lock import execution_lock
from houdini_bridge.official_karma_observation import checked_bytes,file_record

TASK='7c65a89096e84533b8f0ace596cfe1c2'
OP='nrend-d5ca418eb2942da9'
PID=77943
STAGES={'baseline_reopen','cold_readback','cold_reopen','edit_host_stop','feedback','nuke_launch_intent','register','render','render_completed','render_host_stop','save','verify','version_before'}
SOURCE_HASHES={
 'inner_runner':'bed6aafea8901a7db83a10d65b47fca279a606b6cdf90281555fde1a6d26f515',
 'outer_runner':'bed6aafea8901a7db83a10d65b47fca279a606b6cdf90281555fde1a6d26f515',
 'nuke_addon':'c7c57b863c57481c104d3aeb3c3c6be3da0d963ee7520eb65303a86cd3f9e2f1',
 'nuke_task_host':'c480faabb85f6335858dc4f83b4766bd33df1a38223ac168baf358b4dcc42607',
 'nuke_operation_receipts':'e799cce033151acac56b3a227c5cb0940d77c0386cd6b1960034591221ef2275',
 'cleanup':'6f2b2bafa3a9fdbd47b5904cfafb63a7e5dce8f9e8ed2d294e02e3720537ab44'}

def _fail():raise ValueError('RECT_NUKE_PRELAUNCH_UNPROVEN')
def _json(record):return json.loads(checked_bytes(record))
def _case_paths(native):
 """只从已认证范围确定该固定案例位置，保持全部旧源码和失败事实约束。"""
 case=Path(native.scope['creative_phase']['case_contract']['path']).parent
 if case!=native.root/'continuations/luna-rectlight-01':_fail()
 return case,case/'jobs/creative_06679b9bba7ae49982f1'

def _plain(path):
 path=Path(path)
 if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):_fail()
 return path

def _private_new(path,content):
 """证据只写新文件，包含槽令牌的字节不输出到聊天或日志。"""
 path=_plain(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  with os.fdopen(fd,'wb') as out:out.write(content);out.flush();os.fsync(out.fileno())
 except BaseException:
  raise
 return file_record(path)

def _private_json(path,value):return _private_new(path,json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())

def _source_wait_and_prelaunch(files):
 """固定旧源码哈希后再核等待关系、校验调用和持久化意图的相对顺序。"""
 text={k:checked_bytes(v).decode() for k,v in files.items()}
 for key,digest in SOURCE_HASHES.items():
  if files[key]['sha256']!=digest:_fail()
 addon=text['nuke_addon'];start=addon.index('def _launch_owned_render_subprocess(');end=addon.index('\ndef _render_supervisor_stop_reason',start);body=addon[start:end]
 if not body.index('validate_registered_input_contract(contract)')<body.index("temporary.write_bytes(content)")<body.index('task["supervisor_intent"]')<body.index('proc = launch('):_fail()
 tree=ast.parse(text['outer_runner']);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_job')
 segment=ast.get_source_segment(text['outer_runner'],fn)
 if "child=__import__('subprocess').run(" not in segment or "if child.returncode:raise RuntimeError('CREATIVE_JOB_EXECUTION_FAILED')" not in segment:_fail()
 if 'raise ValueError(\'CREATIVE_COLD_CONTEXT_BINDING_MISMATCH\')' not in text['nuke_task_host']:_fail()
 if 'registry = controlled_artifact_registry(' not in text['nuke_operation_receipts']:_fail()
 return True

def _controller_exit(proof):
 """未知进程状态拒绝；同步子进程须已返回且没有相同真实runner作业参数。"""
 from dcc_task_runtime.native_scope import NativeScope
 CASE,JOB=_case_paths(NativeScope(proof['scope']))
 if _json(proof['controller_pid']).get('pid')!=PID:_fail()
 try:os.kill(PID,0)
 except ProcessLookupError:pass
 except (PermissionError,OSError):_fail()
 else:_fail()
 ps=subprocess.run(['/bin/ps','-axo','pid=,ppid=,command='],capture_output=True,text=True,check=True,timeout=10)
 runners={proof['source_files'][k]['path'] for k in ('inner_runner','outer_runner')}
 for line in ps.stdout.splitlines():
  try:argv=shlex.split(line.split(None,2)[2])
  except (IndexError,ValueError):continue
  if any(r in argv for r in runners) and '--job' in argv:
   index=argv.index('--job')
   if index+1<len(argv) and argv[index+1]==str(JOB/'job.json'):_fail()
 return {'controller_pid':PID,'controller_exited':True,'synchronous_child_return_observed':True,'matching_runner_processes':0,'process_inventory_returncode':ps.returncode,'process_inventory_sha256':hashlib.sha256(ps.stdout.encode()).hexdigest(),'observed_at_epoch':time.time()}

def _validate_proof(preparation,native,original_record):
 """只接受这一固定失败的原字节、原快照、原13阶段与真实范围。"""
 CASE,JOB=_case_paths(native)
 proof=_json(preparation)
 fields={'schema','scope','original_job','error','journal','trace','controller_pid','job_preparation','creative_preparation','inner_snapshot_manifest','outer_snapshot_manifest','source_files','old_render_record'}
 if set(proof)!=fields or proof['schema']!='bridge.rectlight-nuke-prelaunch-proof/1' or proof['scope']!=native.binding:_fail()
 inner=JOB/'project/control';outer=CASE/'runtime-repair06/project/control'
 paths={'original_job':JOB/'job.json','error':JOB/'error.json','journal':JOB/'incremental-state.json','trace':JOB/'controller.stderr.log','controller_pid':JOB/'controller-pid.json','job_preparation':JOB/'job-preparation.json','creative_preparation':CASE/'creative-preparation.json','inner_snapshot_manifest':inner/'snapshot-manifest.json','outer_snapshot_manifest':outer/'snapshot-manifest.json'}
 for key,path in paths.items():
  if _plain(proof[key]['path'])!=path:_fail()
  checked_bytes(proof[key])
 job=_json(proof['original_job']);prep=_json(proof['creative_preparation']);journal=_json(proof['journal']);jobprep=_json(proof['job_preparation'])
 if (job.get('operation_id')!=JOB.name or job.get('directory')!=str(JOB) or job.get('preparation')!=proof['creative_preparation']
     or prep.get('task_id')!=TASK or prep.get('scope')!=native.binding or prep.get('case_id')!='karma_lights_rectlight_v1'
     or jobprep.get('control')!=str(inner) or journal.get('preparation')!=proof['original_job']
     or set(journal.get('stages',{}))!=STAGES or any(v.get('state')!='DONE' for v in journal['stages'].values())):_fail()
 if _json(proof['error'])!={'code':'ValueError','message':'unstarted release requires a fenced launch permit','native_success_claimed':False}:_fail()
 intent=journal['stages']['nuke_launch_intent']['result']
 if (intent.get('operation_id')!=OP or intent.get('record')!=proof['old_render_record']
     or proof['old_render_record'].get('sha256')!='450a4c827071f70abb10b6a7527e970603c8806a6befc1e53bb04064a605dc45'
     or proof['old_render_record'].get('bytes')!=6292
     or Path(proof['old_render_record']['path'])!=native.root/'state/nuke_renders'/(OP+'.json')):_fail()
 raw=checked_bytes(original_record)
 if len(raw)!=6292 or hashlib.sha256(raw).hexdigest()!=proof['old_render_record']['sha256']:_fail()
 record=json.loads(raw)
 if (record.get('task_id')!=OP or record.get('owner_task_id')!=TASK or record.get('state')!='RUNNING'
     or any(key in record for key in ('process','supervisor_intent','dispatch_state'))
     or record.get('stop_confirmed_at') is not None or record.get('slot',{}).get('generation')!=3
     or record.get('slot',{}).get('operation_id')!=OP
     or record.get('slot',{}).get('owner_root')!='nuke:'+str(JOB/'project/saves/composite.nk')):_fail()
 from vfx_pipeline.official_graph_resume import _snapshot
 if _snapshot(inner)!=proof['inner_snapshot_manifest'] or _snapshot(outer)!=proof['outer_snapshot_manifest'] or prep.get('runtime_snapshot_manifest')!=proof['outer_snapshot_manifest']:_fail()
 relatives={'inner_runner':'tools/run_hy3_creative.py','outer_runner':'tools/run_hy3_creative.py','nuke_addon':'plugins/nuke/nuke_bridge_addon.py','nuke_task_host':'packages/nuke-bridge/src/nuke_bridge/task_host.py','nuke_operation_receipts':'packages/nuke-bridge/src/nuke_bridge/operation_receipts.py','cleanup':'tools/recover_disklight_nuke.py'}
 if set(proof['source_files'])!=set(relatives):_fail()
 for key,relative in relatives.items():
  path=(outer if key=='outer_runner' else inner)/'snapshot'/relative
  if proof['source_files'][key]!=file_record(path):_fail()
 _source_wait_and_prelaunch(proof['source_files'])
 trace=checked_bytes(proof['trace']).decode()
 for marker in ('validate_registered_input_contract(contract)','creative_context = creative_cold_context()',"raise ValueError('CREATIVE_COLD_CONTEXT_BINDING_MISMATCH')",'ValueError: CREATIVE_COLD_CONTEXT_BINDING_MISMATCH',"if child.returncode:raise RuntimeError('CREATIVE_JOB_EXECUTION_FAILED')",'RuntimeError: CREATIVE_JOB_EXECUTION_FAILED'):
  if marker not in trace:_fail()
 return proof,record

def _no_launch_files(native,record):
 CASE,JOB=_case_paths(native)
 directory=native.root/'state/nuke_renders'
 for suffix in ('.inputs.json','.worker-result.json','.supervisor','.composite.json'):
  path=directory/(OP+suffix)
  if path.exists() or path.is_symlink():_fail()
 if any((JOB/'project/saves').glob('nuke.*.exr')):_fail()
 if Path(record['pattern']%1).exists():_fail()

def _slot_matches(slot,record):
 expected=record['slot']
 if (not slot or slot.get('active')!=1 or slot.get('phase')!='DISPATCHING' or slot.get('process_json') is not None
     or slot.get('generation')!=3 or slot.get('cancel_requested')!=0
     or any(slot.get(k)!=expected[k] for k in ('owner_root','operation_id','token','generation'))):_fail()

def _load_addon(proof):
 path=Path(proof['source_files']['nuke_addon']['path']);spec=importlib.util.spec_from_file_location('_rectlight_prelaunch_control_addon',path);addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
 addon._RENDER_RECORDS_DIR=Path(proof['old_render_record']['path']).parent
 return addon

def abort_prelaunch_dispatch(preparation,authorization):
 """可信控制入口：签名授权加锁重验后仅关闭固定的未启动尝试。"""
 from dcc_task_runtime.native_scope import NativeScope
 proof=_json(preparation);native=NativeScope(proof['scope']);live=proof['old_render_record']
 CASE,JOB=_case_paths(native)
 proof,record=_validate_proof(preparation,native,live);addon=_load_addon(proof)
 verified=addon._verify_control_authorization('abort_prelaunch_dispatch',{'preparation':preparation},authorization)
 target=JOB/'nuke-prelaunch-reconciliation.json';audit=JOB/'nuke-prelaunch-reconciliation'
 if target.exists() or audit.exists():raise ValueError('RECT_PRELAUNCH_QUERY_EXISTING_REQUIRED')
 scheduler=GraphScheduler(Path(native.binding['path']).parent/'scheduler')
 with execution_lock(Path(live['path']),OP):
  before=scheduler.snapshot();_slot_matches(before,record)
  def validate(slot):
   _slot_matches(slot,record)
   checked_bytes(live);_validate_proof(preparation,native,live);_no_launch_files(native,record)
   usage=native.snapshot()
   if usage['dcc_starts']!=43 or len(usage['tickets'])!=43 or any(t['stopped_at'] is None for t in usage['tickets']) or any(t['role']=='nuke-render' for t in usage['tickets'][33:]):_fail()
   process=_controller_exit(proof)
   checked_bytes(live);_no_launch_files(native,record)
   observations.update(usage=usage,process=process)
  observations={};validate(before)
  old=_private_new(audit/'render-before.json',checked_bytes(live));before_record=_private_json(audit/'slot-before.json',before)
  state=_private_new(audit/'native-signed-state.json',native.state_path.read_bytes())
  scheduler._fence_verified_prelaunch_dispatch(before['owner_root'],OP,before['token'],3,validate)
  closed=copy.deepcopy(record);closed['dispatch_state']='NOT_STARTED';closed['slot_released']=True;closed['prelaunch_recovery']=preparation
  addon._render_history(closed,'FAILED',note='Trusted control verified validation failure before input intent or process dispatch; original attempt not started.')
  addon._persist_render_record(closed);Path(live['path']).chmod(0o600)
  after_record=_private_new(audit/'render-after.json',Path(live['path']).read_bytes())
  if not scheduler.release(before['owner_root'],OP,before['token'],unstarted=True):_fail()
  after=scheduler.snapshot()
  if after.get('phase')!='RELEASED' or after.get('active')!=0 or after.get('process_json') is not None:_fail()
  result={'schema':'bridge.rectlight-nuke-prelaunch-reconciliation/1','state':'PRELAUNCH_ABORTED','nuke_started':False,'slot_released':True,'native_starts':43,'scope':native.binding,
   'proof_preparation':preparation,'original_job':proof['original_job'],'original_error':proof['error'],'original_journal':proof['journal'],'original_trace':proof['trace'],
   'tickets':observations['usage']['tickets'],'old_render_record':old,'after_render_record':after_record,'live_render_record':file_record(Path(live['path'])),
   'before_slot':before_record,'after_slot':_private_json(audit/'slot-after.json',after),'controller_exit':observations['process'],
   'source_files':proof['source_files'],'original_signed_state':state,'verified_by':verified,'control_implementation':file_record(Path(__file__))}
  return _private_json(target,result)

def validate_prelaunch_reconciliation(negative_record,native):
 """只读重验可信收束的可持久事实；不声称能重验已销毁的临时授权密钥。"""
 CASE,JOB=_case_paths(native)
 if Path(negative_record['path'])!=JOB/'nuke-prelaunch-reconciliation.json':_fail()
 result=_json(negative_record)
 if (result.get('schema')!='bridge.rectlight-nuke-prelaunch-reconciliation/1' or result.get('state')!='PRELAUNCH_ABORTED'
     or result.get('nuke_started') is not False or result.get('slot_released') is not True or result.get('native_starts')!=43 or result.get('scope')!=native.binding):_fail()
 checked_bytes(result['control_implementation'])
 proof,old=_validate_proof(result['proof_preparation'],native,result['old_render_record'])
 for key,source in (('original_job','original_job'),('original_error','error'),('original_journal','journal'),('original_trace','trace'),('source_files','source_files')):
  if result.get(key)!=proof[source]:_fail()
 closed=_json(result['after_render_record']);before=_json(result['before_slot']);after=_json(result['after_slot']);_slot_matches(before,old)
 if (closed.get('state')!='FAILED' or closed.get('dispatch_state')!='NOT_STARTED' or closed.get('slot_released') is not True
     or closed.get('prelaunch_recovery')!=result['proof_preparation'] or any(k in closed for k in ('process','supervisor_intent','execution_fact'))
     or closed.get('stop_confirmed_at') is not None or closed.get('slot')!=old['slot']
     or closed.get('history',[])[-1].get('from')!='RUNNING' or closed['history'][-1].get('to')!='FAILED'
     or after.get('active')!=0 or after.get('phase')!='RELEASED' or after.get('process_json') is not None
     or any(after.get(k)!=before.get(k) for k in ('owner_root','operation_id','token','generation'))):_fail()
 envelope=_json(result['original_signed_state']);signed=native._verify_envelope(envelope)['state']
 usage=native.snapshot();tickets=result['tickets']
 if (len(tickets)!=43 or usage['tickets'][:43]!=tickets or signed.get('tickets')!=tickets
     or signed.get('scope_sha256')!=native.binding['sha256']
     or any(t['stopped_at'] is None for t in tickets) or any(t['role']=='nuke-render' for t in tickets[33:])
     or result.get('controller_exit',{}).get('controller_pid')!=PID or result['controller_exit'].get('controller_exited') is not True
     or result['controller_exit'].get('matching_runner_processes')!=0 or not str(result.get('verified_by') or '').strip()):_fail()
 return result
