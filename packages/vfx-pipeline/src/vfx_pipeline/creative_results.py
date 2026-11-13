"""真实创作完成事实的只读复核及临时USD清单错误的有限修复。"""
from __future__ import annotations
import hashlib,importlib.util,json
from pathlib import Path
from houdini_bridge.official_karma_observation import checked_bytes,file_record
from dcc_task_runtime.graph_scheduler import GraphScheduler

STAGES={'baseline_reopen','version_before','feedback','save','edit_host_stop','cold_reopen','cold_readback','render','render_completed','render_host_stop','verify','register','nuke_launch_intent','nuke_completed'}

def completed_registry(source,scope,task_id,*,historical=None):
 """使用本控制快照的已知Nuke插件，仅安装只读事实回调，不准入或启动。"""
 from nuke_bridge.task_host import _input_artifact_registry
 root=Path(__file__).resolve().parents[4]
 spec=importlib.util.spec_from_file_location('creative_completed_nuke',root/'plugins/nuke/nuke_bridge_addon.py')
 addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
 addon._RENDER_RECORDS_DIR=scope.root/'state/nuke_renders'
 addon._NUKE_SCHEDULER=GraphScheduler(Path(scope.path).parent/'scheduler')
 registry=_input_artifact_registry(source,scope=scope,task_id=task_id,fallback=addon._nuke_operation_fact,observe_completed=True,
     _read_only_binding=historical is not None,_historical_observation=historical)
 addon._NUKE_ARTIFACT_REGISTRY=registry
 return registry

def require_completed_journal(directory,job_record):
 value=json.loads((directory/'incremental-state.json').read_text())
 if value.get('preparation')!=job_record or set(value.get('stages',{}))!=STAGES or any(x.get('state')!='DONE' for x in value['stages'].values()):
  raise ValueError('CREATIVE_ALL_NATIVE_STAGES_REQUIRED')
 return value['stages']

def validate_postprocess_repair(directory,result,preparation):
 """只允许精确绑定原USD清单错误的新完成结果覆盖查询失败，旧记录保持。"""
 repair=result.get('postprocess_repair')
 fields={'schema','original_error','original_job','original_preparation','journal','finalize_preparation','native_reexecuted'}
 if type(repair) is not dict or set(repair)!=fields or repair['schema']!='bridge.creative-postprocess-repair/1' or repair['native_reexecuted'] is not False:
  raise ValueError('CREATIVE_POSTPROCESS_REPAIR_REQUIRED')
 if (repair['finalize_preparation']!=preparation or repair['original_error']!=file_record(directory/'error.json')
     or repair['original_job']!=file_record(directory/'job.json') or repair['journal']!=file_record(directory/'incremental-state.json')):
  raise ValueError('CREATIVE_POSTPROCESS_REPAIR_BINDING_REQUIRED')
 oldjob=json.loads(checked_bytes(repair['original_job']));oldprep=json.loads(checked_bytes(repair['original_preparation']));newprep=json.loads(checked_bytes(preparation))
 error=json.loads(checked_bytes(repair['original_error']))
 if (error.get('code')!='FileNotFoundError' or str(directory/'project/saves/main.0001.usd') not in error.get('message','')
     or oldjob.get('preparation')!=repair['original_preparation'] or oldjob.get('directory')!=str(directory)
     or result.get('operation_id')!=oldjob.get('operation_id') or result.get('plan')!=oldjob.get('plan')
     or oldprep.get('scope')!=newprep.get('scope') or oldprep.get('model_route')!=newprep.get('model_route')
     or newprep.get('postprocess_recovery')!={'original_job':repair['original_job'],'original_error':repair['original_error'],'native_reexecuted':False}
     or newprep.get('supersedes')!=repair['original_preparation']):
  raise ValueError('CREATIVE_POSTPROCESS_REPAIR_SOURCE_REQUIRED')
 allowed={'runtime_control','runtime_manifest','runtime_snapshot_manifest','worker','supersedes','postprocess_recovery'}
 if any(oldprep.get(key)!=newprep.get(key) for key in set(oldprep)|set(newprep) if key not in allowed):
  raise ValueError('CREATIVE_POSTPROCESS_INPUT_CHANGED')
 from .official_graph_resume import _snapshot
 if _snapshot(Path(newprep['runtime_control']))!=newprep['runtime_snapshot_manifest']:raise ValueError('CREATIVE_POSTPROCESS_SNAPSHOT_REQUIRED')
 require_completed_journal(directory,repair['original_job'])
 return repair


_RECT_RESUME_OPERATION='creative_06679b9bba7ae49982f1'
_RECT_RESUME_TASK='7c65a89096e84533b8f0ace596cfe1c2'
_RECT_RESUME_SCOPE_SHA='66ce89e945032b9dfbc6d3603e581b4ffa7b5fc028ac46a008f1ac3296b29983'

def nuke_prelaunch_inputs(directory,preparation):
 """只认证本任务已完成H/Karma的13步检查点及未启动Nuke的控制端负面事实。"""
 from dcc_task_runtime.native_scope import NativeScope
 from dcc_task_runtime.canonical import canonical_sha256
 from .official_graph_resume import _snapshot
 directory=Path(directory);newprep=json.loads(checked_bytes(preparation));repair=newprep.get('nuke_prelaunch_recovery')
 fields={'original_job','original_error','original_journal','original_trace','reconciliation','native_reexecuted'}
 if type(repair) is not dict or set(repair)!=fields or repair['native_reexecuted']!=['nuke-render']:
  raise ValueError('RECT_NUKE_PRELAUNCH_RECOVERY_REQUIRED')
 expected={'original_job':directory/'job.json','original_error':directory/'error.json','original_journal':directory/'incremental-state.json','original_trace':directory/'controller.stderr.log','reconciliation':directory/'nuke-prelaunch-reconciliation.json'}
 if any(repair[k]!=file_record(path) for k,path in expected.items()):raise ValueError('RECT_NUKE_RECOVERY_FILE_BINDING_REQUIRED')
 job=json.loads(checked_bytes(repair['original_job']));oldprep=json.loads(checked_bytes(job['preparation']));error=json.loads(checked_bytes(repair['original_error']))
 trace=checked_bytes(repair['original_trace']).decode();journal=json.loads(checked_bytes(repair['original_journal']));stages=journal.get('stages',{})
 negative=json.loads(checked_bytes(repair['reconciliation']))
 allowed={'runtime_control','runtime_manifest','runtime_snapshot_manifest','worker','supersedes','nuke_prelaunch_recovery'}
 if (job.get('operation_id')!=_RECT_RESUME_OPERATION or oldprep.get('task_id')!=_RECT_RESUME_TASK or job.get('directory')!=str(directory)
     or job.get('plan',{}).get('revision')!=1 or job['plan'].get('base_exposure')!=0. or job['plan'].get('exposure')!=-.5
     or newprep.get('case_id')!='karma_lights_rectlight_v1' or newprep.get('scope',{}).get('sha256')!=_RECT_RESUME_SCOPE_SHA
     or newprep.get('task_id')!=_RECT_RESUME_TASK or newprep.get('supersedes')!=job['preparation']
     or any(oldprep.get(k)!=newprep.get(k) for k in set(oldprep)|set(newprep) if k not in allowed)
     or error!={'code':'ValueError','message':'unstarted release requires a fenced launch permit','native_success_claimed':False}
     or 'CREATIVE_COLD_CONTEXT_BINDING_MISMATCH' not in trace or 'unstarted release requires a fenced launch permit' not in trace
     or journal.get('preparation')!=repair['original_job'] or set(stages)!=STAGES-{'nuke_completed'} or any(x.get('state')!='DONE' for x in stages.values())
     or negative.get('schema')!='bridge.rectlight-nuke-prelaunch-reconciliation/1' or negative.get('state')!='PRELAUNCH_ABORTED'
     or negative.get('nuke_started') is not False or negative.get('slot_released') is not True or negative.get('native_starts')!=43
     or negative.get('scope')!=newprep['scope'] or any(negative.get(k)!=repair[k] for k in ('original_job','original_error','original_journal','original_trace'))):
  raise ValueError('RECT_NUKE_PRELAUNCH_SOURCE_REQUIRED')
 native=NativeScope(newprep['scope'])
 from .rectlight_prelaunch import validate_prelaunch_reconciliation
 validate_prelaunch_reconciliation(repair['reconciliation'],native)
 usage=native.snapshot();phase=native.scope.get('creative_phase',{})
 if (phase.get('schema')!='bridge.official-case-creative-phase/1' or phase.get('starts')!=16 or phase.get('seconds')!=1800
     or directory!=Path(phase['case_contract']['path']).parent/'jobs'/_RECT_RESUME_OPERATION
     or negative.get('tickets')!=usage['tickets'][:43] or len(negative['tickets'])!=43 or any(t.get('stopped_at') is None for t in negative['tickets'])
     or [t['role'] for t in negative['tickets'][-3:]]!=['houdini-host','houdini-host','main-husk']):
  raise ValueError('RECT_NUKE_PRELAUNCH_ACCOUNTING_REQUIRED')
 original_record=negative.get('old_render_record',{});checked_bytes(original_record)
 closed=json.loads(checked_bytes(negative['after_render_record']))
 if closed.get('state')!='FAILED' or closed.get('dispatch_state')!='NOT_STARTED' or not closed.get('prelaunch_recovery') or not closed.get('history'):raise ValueError('RECT_NUKE_CLOSED_HISTORY_REQUIRED')
 launch=stages['nuke_launch_intent']['result'];expected_nuke='nrend-'+hashlib.sha256((_RECT_RESUME_OPERATION+'_nuke').encode()).hexdigest()[:16]
 record=json.loads(checked_bytes(original_record))
 if (original_record.get('sha256')!=launch['record']['sha256'] or original_record.get('bytes')!=launch['record']['bytes']
     or launch.get('operation_id')!=expected_nuke or record.get('task_id')!=expected_nuke or record.get('owner_task_id')!=_RECT_RESUME_TASK
     or record.get('supervisor_intent') is not None or record.get('process') is not None or record.get('state')!='RUNNING'):
  raise ValueError('RECT_NUKE_NEVER_LAUNCHED_RECORD_REQUIRED')
 control=directory/'project/control';source_record=file_record(control/'creative-input-source.json');source=json.loads(checked_bytes(source_record))
 saved=stages['save']['result'];artifact=stages['register']['result'];changed=stages['feedback']['result']
 if (source.get('artifact_id')!='rectlight_creative_main' or source.get('artifact_version')!=1 or source.get('producer_control')!=str(control)
     or source.get('registry_operation_receipt')!=artifact.get('registry_operation_receipt') or source.get('creative_phase')!=phase
     or source.get('case_id')!=newprep['case_id'] or source.get('case_variant')!=newprep['case_variant']
     or artifact.get('artifact_id')!=source['artifact_id'] or artifact.get('version')!=1
     or saved.get('sha256')!=file_record(saved['path'])['sha256'] or saved.get('scene_contract_sha256')!=canonical_sha256(saved['scene_contract'])
     or changed.get('after')!=stages['cold_readback']['result'].get('parms') or changed['after'].get('xn__inputsexposure_vya')!=-.5
     or stages['cold_readback']['result'].get('source')!='verified_native_reopen'
     or stages['cold_reopen']['result'].get('sha256')!=saved['sha256']
     or _snapshot(Path(newprep['runtime_control']))!=newprep['runtime_snapshot_manifest']):
  raise ValueError('RECT_NUKE_REUSED_NATIVE_RESULT_REQUIRED')
 for item in newprep['protected_files'].values():checked_bytes(item)
 return {'job':job,'old_preparation':oldprep,'preparation':newprep,'repair':repair,'stages':stages,'negative':negative,'native':native,'usage':usage,'source_record':source_record}

def validate_nuke_prelaunch_recovery(directory,result,preparation):
 """只接收原模型请求的一次Nuke续接；真实H/K结果和负面历史均不可替换。"""
 inputs=nuke_prelaunch_inputs(directory,preparation);prep=inputs['preparation'];repair=result.get('nuke_prelaunch_recovery')
 expected=dict(inputs['repair'],schema='bridge.rectlight-nuke-prelaunch-recovery/1',original_preparation=inputs['job']['preparation'],recovery_preparation=preparation,recovery_journal=file_record(Path(directory)/'nuke-resume-01/incremental-state.json'))
 if repair!=expected:raise ValueError('RECT_NUKE_RECOVERY_RECEIPT_REQUIRED')
 journal=json.loads(checked_bytes(repair['recovery_journal']));stages=journal.get('stages',{})
 job=inputs['job'];original=inputs['stages'];usage=inputs['usage'];reported=result.get('scope',{})
 if (journal.get('preparation')!=preparation or set(stages)!={'nuke_launch_intent','nuke_completed'} or any(x.get('state')!='DONE' for x in stages.values())
     or result.get('operation_id')!=job['operation_id'] or result.get('plan')!=job['plan'] or result.get('exposure')!=-.5 or result.get('revision')!=1
     or result.get('case_id')!=prep['case_id'] or result.get('case_variant')!=prep['case_variant'] or result.get('model_route')!=prep['model_route']
     or any(result.get(key)!=original[stage]['result'] for key,stage in (('saved','save'),('feedback','feedback'),('artifact','register')))
     or reported.get('dcc_starts')!=44 or reported.get('tickets')!=usage['tickets'][:44]
     or len(reported['tickets'])!=44 or reported['tickets'][-1]['role']!='nuke-render' or reported['tickets'][-1]['identity'].get('operation_id')!=result['nuke']['operation_id']
     or any(t.get('stopped_at') is None for t in reported['tickets'])
     or stages['nuke_completed']['result'].get('state')!='COMPLETED' or stages['nuke_completed']['result'].get('ledger_state')!='REGISTERED'
     or stages['nuke_launch_intent']['result'].get('operation_id')!=result['nuke']['operation_id']):
  raise ValueError('RECT_NUKE_RECOVERY_COMPLETION_REQUIRED')
 return repair


_RECT_SECOND_OPERATION='creative_bff6f898fafe1db03aae'
_RECT_CHECKPOINT_NAME='task-save-c76506b123c8440baf60dd7642a3a8f8.hip'
_RECT_CHECKPOINT_SHA='26cda35de033e0873701041df79e490b72ce36f29aa7f439183b309f4cad67e4'
_RECT_CHECKPOINT_CONTRACT_SHA='20adad32f8f8fb977a710ab3d4c21834ec7cdcab827f99c875c6b6157d51ae8b'


def _checkpoint_scope_chain(previous,native,storage=False):
 """只承认已审核的04→05，以及唯一磁盘512→640MiB的05→06。"""
 from dcc_task_runtime.native_scope import NativeScope
 root=previous.root
 if previous.binding.get('sha256')!=_RECT_RESUME_SCOPE_SHA:return False
 if storage:
  if native.path!=root/'continuations/luna-rectlight-06/scope.json' or not native.scope.get('case_storage_revision'):return False
  predecessor=native.scope.get('continuation_of',{});middle=NativeScope({k:predecessor[k] for k in ('path','sha256')})
  expected=dict(previous.scope['budget'],max_disk_bytes=640*1024*1024)
  if (middle.path!=root/'continuations/luna-rectlight-05/scope.json' or middle.scope.get('continuation_of')!=file_record(previous.path)
      or middle.scope.get('creative_phase')!=previous.scope.get('creative_phase') or middle.scope.get('budget')!=previous.scope.get('budget')
      or previous.scope['budget'].get('max_disk_bytes')!=512*1024*1024 or native.scope.get('budget')!=expected
      or native.scope.get('creative_phase')!=previous.scope.get('creative_phase')
      or middle.snapshot()['tickets']!=previous.snapshot()['tickets']):return False
 else:
  if (native.path!=root/'continuations/luna-rectlight-05/scope.json' or native.scope.get('continuation_of')!=file_record(previous.path)
      or native.scope.get('creative_phase')!=previous.scope.get('creative_phase') or native.scope.get('budget')!=previous.scope.get('budget')):return False
 return previous.snapshot()['dcc_starts']==45 and native.snapshot()['tickets'][:45]==previous.snapshot()['tickets']

def validate_pre_native_storage_refusal(original,record,native):
 """确认旧续接在admit前被磁盘门拒绝；这不是原生停止或未知启动的恢复。"""
 from dcc_task_runtime.native_scope import NativeScope
 from .official_graph_resume import _snapshot
 original=Path(original);directory=original/'executions/save-repair-01';control=directory/'project/control';value=json.loads(checked_bytes(record))
 fields={'schema','state','task_id','operation_id','scope','preparation','execution_job','execution_journal','execution_error','execution_trace','source_snapshot_manifest','source_files','signed_state_before','signed_state_after','native_starts','native_starts_added','supervisor_started','controller_exit'}
 if (Path(record['path'])!=directory/'pre-native-storage-refusal.json' or set(value)!=fields
     or value.get('schema')!='bridge.rectlight-pre-native-storage-refusal/1' or value.get('state')!='PRE_NATIVE_REFUSED'
     or value.get('task_id')!=_RECT_RESUME_TASK or value.get('operation_id')!=_RECT_SECOND_OPERATION
     or value.get('native_starts')!=45 or value.get('native_starts_added')!=0 or value.get('supervisor_started') is not False):raise ValueError('RECT_PRE_NATIVE_STORAGE_REFUSAL_REQUIRED')
 paths={'execution_job':directory/'job.json','execution_journal':directory/'incremental-state.json','execution_error':directory/'error.json','source_snapshot_manifest':control/'snapshot-manifest.json'}
 if any(value[k]!=file_record(path) for k,path in paths.items()):raise ValueError('RECT_STORAGE_REFUSAL_FILES_REQUIRED')
 for key in ('preparation','execution_trace','signed_state_before','signed_state_after'):checked_bytes(value[key])
 job=json.loads(checked_bytes(value['execution_job']));prep=json.loads(checked_bytes(value['preparation']));journal=json.loads(checked_bytes(value['execution_journal']));error=json.loads(checked_bytes(value['execution_error']))
 prior=NativeScope(value['scope']);before=json.loads(checked_bytes(value['signed_state_before']));after=json.loads(checked_bytes(value['signed_state_after']));signed=prior._verify_envelope(before)['state'];prior._verify_envelope(after)
 if (job.get('directory')!=str(directory) or job.get('operation_id')!=_RECT_SECOND_OPERATION or job.get('preparation')!=value['preparation']
     or prep.get('scope')!=value['scope'] or prep.get('case_id')!='karma_lights_rectlight_v1'
     or prior.path!=native.root/'continuations/luna-rectlight-05/scope.json' or native.scope.get('continuation_of')!=file_record(prior.path)
     or journal.get('preparation')!=value['execution_job'] or journal.get('stages')!={'checkpoint_reopen':{'state':'INTENT'}}
     or error!={'code':'SupervisorNotStarted','message':'SUPERVISOR_DISK_BUDGET_EXCEEDED','native_success_claimed':False}
     or checked_bytes(value['signed_state_before'])!=checked_bytes(value['signed_state_after']) or len(signed.get('tickets',[]))!=45
     or signed.get('tickets')!=prior.snapshot()['tickets'] or native.snapshot()['tickets'][:45]!=signed['tickets'] or any(t['stopped_at'] is None for t in signed['tickets'])
     or value.get('controller_exit',{}).get('exit_code')!=1 or value['controller_exit'].get('matching_execution_processes')!=0):raise ValueError('RECT_STORAGE_REFUSAL_NO_NATIVE_ADMISSION_REQUIRED')
 relatives={'runner':'tools/run_hy3_creative.py','owned_process':'packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py','houdini_task_host':'packages/houdini-bridge/src/houdini_bridge/task_host.py'}
 if set(value['source_files'])!=set(relatives):raise ValueError('RECT_STORAGE_REFUSAL_SOURCE_REQUIRED')
 for key,relative in relatives.items():
  if value['source_files'][key]!=file_record(control/'snapshot'/relative):raise ValueError('RECT_STORAGE_REFUSAL_SOURCE_REQUIRED')
 if _snapshot(control)!=value['source_snapshot_manifest']:raise ValueError('RECT_STORAGE_REFUSAL_SNAPSHOT_REQUIRED')
 source=checked_bytes(value['source_files']['owned_process']).decode();start=source.index('def launch(');end=source.find('\ndef ',start+1);launch=source[start:end if end!=-1 else None]
 markers=['used = _disk_usage(resource_budget)',"raise ValueError('SUPERVISOR_DISK_BUDGET_EXCEEDED')",'scope_ticket = scope.admit','directory = ensure_private_directory','process = subprocess.Popen']
 positions=[launch.index(marker) for marker in markers]
 trace=checked_bytes(value['execution_trace']).decode()
 if positions!=sorted(positions) or 'SupervisorNotStarted: SUPERVISOR_DISK_BUDGET_EXCEEDED' not in trace or "raise ValueError('SUPERVISOR_DISK_BUDGET_EXCEEDED')" not in trace or str(control/'snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py') not in trace:raise ValueError('RECT_STORAGE_REFUSAL_BEFORE_ADMIT_REQUIRED')
 host=control/'houdini-task-host'
 if any(host.glob('supervisor-*')) or any((host/name).exists() for name in ('host.ready','supervisor-binding.json')) or any(host.rglob('started.json')):raise ValueError('RECT_STORAGE_REFUSAL_UNKNOWN_START_FORBIDDEN')
 return value

def saved_checkpoint_inputs(original,preparation):
 """认证第二轮已写HIP检查点；原保存INTENT保持未完成，不作为正式保存回执。"""
 from dcc_task_runtime.native_scope import NativeScope
 from dcc_task_runtime import owned_process
 from dcc_task_runtime.canonical import canonical_sha256
 from houdini_bridge.operation_receipts import operation_receipt_sha256
 from .official_graph_resume import _snapshot
 original=Path(original);prep=json.loads(checked_bytes(preparation));repair=prep.get('saved_checkpoint_recovery')
 fields={'schema','original_job','original_error','original_journal','original_trace','checkpoint','save_sidecar','producer_intent','signed_stop','feedback_database'}
 if type(repair) is not dict or set(repair)!=fields or repair.get('schema')!='bridge.rectlight-saved-checkpoint-recovery/1':raise ValueError('RECT_SAVED_CHECKPOINT_RECOVERY_REQUIRED')
 expected={'original_job':original/'job.json','original_error':original/'error.json','original_journal':original/'incremental-state.json','original_trace':original/'controller.stderr.log','checkpoint':original/'project/saves'/_RECT_CHECKPOINT_NAME,'save_sidecar':original/'project/control/houdini-instances/fx_operations/ops_cf2729aec8a0b7f8.saves.json','feedback_database':original/'project/control/diagnostic.sqlite3'}
 if any(repair[k]!=file_record(path) for k,path in expected.items()):raise ValueError('RECT_CHECKPOINT_SOURCE_FILE_REQUIRED')
 for rec in repair.values():
  if isinstance(rec,dict) and 'path' in rec:checked_bytes(rec)
 job=json.loads(checked_bytes(repair['original_job']));old=json.loads(checked_bytes(job['preparation']));journal=json.loads(checked_bytes(repair['original_journal']));stages=journal.get('stages',{})
 error=json.loads(checked_bytes(repair['original_error']));intent=json.loads(checked_bytes(repair['producer_intent']));sidecar=json.loads(checked_bytes(repair['save_sidecar']))
 previous=NativeScope(old['scope']);prior_usage=previous.snapshot();native=NativeScope(prep['scope']);usage=native.snapshot()
 allowed={'scope','runtime_control','runtime_manifest','runtime_snapshot_manifest','worker','supersedes','environment','saved_checkpoint_recovery','pre_native_storage_refusal'}
 if (job.get('operation_id')!=_RECT_SECOND_OPERATION or job.get('directory')!=str(original) or job.get('plan',{}).get('revision')!=2 or job['plan'].get('base_exposure')!=-.5 or job['plan'].get('exposure')!=-.25
     or old.get('scope',{}).get('sha256')!=_RECT_RESUME_SCOPE_SHA or old.get('task_id')!=_RECT_RESUME_TASK or prep.get('case_id')!='karma_lights_rectlight_v1'
     or prep.get('supersedes')!=job['preparation'] or any(old.get(k)!=prep.get(k) for k in set(old)|set(prep) if k not in allowed)
     or error.get('code')!='BridgeError' or error.get('native_success_claimed') is not False or 'Remote end closed connection without response' not in error.get('message','')
     or journal.get('preparation')!=repair['original_job'] or set(stages)!={'baseline_reopen','version_before','feedback','save'}
     or any(stages[k].get('state')!='DONE' for k in ('baseline_reopen','version_before','feedback')) or stages['save']!={'state':'INTENT'}
     or repair['checkpoint']['sha256']!=_RECT_CHECKPOINT_SHA
     or not _checkpoint_scope_chain(previous,native,storage=prep.get('pre_native_storage_refusal') is not None)
     or prior_usage['dcc_starts']!=45 or usage['tickets'][:45]!=prior_usage['tickets'] or any(t.get('stopped_at') is None for t in prior_usage['tickets'])
     or previous.scope['creative_phase'].get('starts')!=16 or previous.scope['creative_phase'].get('seconds')!=1800
     or original!=Path(native.scope['creative_phase']['case_contract']['path']).parent/'jobs'/_RECT_SECOND_OPERATION
     or _snapshot(Path(prep['runtime_control']))!=prep['runtime_snapshot_manifest']):raise ValueError('RECT_CHECKPOINT_FAILURE_AND_SCOPE_REQUIRED')
 if prep.get('pre_native_storage_refusal') is not None:validate_pre_native_storage_refusal(original,prep['pre_native_storage_refusal'],native)
 # 环境只允许沿用原固定白名单；scope只改变会计命名空间，不增加环境能力。
 if prep.get('environment')!=old.get('environment'):raise ValueError('RECT_CHECKPOINT_ENVIRONMENT_CHANGED')
 candidates=[x for x in sidecar.get('saves',[]) if x.get('path')==repair['checkpoint']['path']]
 if len(candidates)!=1:raise ValueError('RECT_CHECKPOINT_EXACT_SIDECAR_REQUIRED')
 checkpoint=candidates[0];frozen=checkpoint.get('scene_contract',{}).get('frozen_scene_parameters',{})
 last=prior_usage['tickets'][-1];stop=owned_process.read_receipt(last['directory'],'stopped',identity=last['identity'])
 if (checkpoint.get('sha256')!=_RECT_CHECKPOINT_SHA or checkpoint.get('scene_contract_sha256')!=_RECT_CHECKPOINT_CONTRACT_SHA
     or canonical_sha256(checkpoint['scene_contract'])!=_RECT_CHECKPOINT_CONTRACT_SHA
     or frozen.get('fields',{}).get('light.xn__inputsexposure_vya')!=-.25 or frozen.get('fields',{}).get('light.lighttype')!=4
     or frozen.get('configuration_sha256')!=canonical_sha256(json.loads(checked_bytes(prep['configuration'])))
     or last['role']!='houdini-host' or repair['signed_stop']!=file_record(Path(last['directory'])/'stopped.json')
     or not stop or stop.get('stop_reason')!='TIME_BUDGET_EXCEEDED' or intent.get('host_identity',{}).get('pid')!=stop.get('pid')
     or intent.get('state')!='INTENT' or intent.get('command')!='scene.save_hip' or intent.get('operation_id')!=Path(_RECT_CHECKPOINT_NAME).stem
     or intent.get('task_id')!=_RECT_RESUME_TASK or intent.get('request',{}).get('path')!=repair['checkpoint']['path']
     or intent.get('operation_receipt_sha256')!=operation_receipt_sha256(intent)):raise ValueError('RECT_CHECKPOINT_INTENT_NOT_COMPLETION_REQUIRED')
 actual_records=list(Path(expected['save_sidecar']).parent.glob('producer-records/*/*.json'))
 if actual_records!=[Path(repair['producer_intent']['path'])]:raise ValueError('RECT_CHECKPOINT_UNIQUE_INTENT_REQUIRED')
 changed=stages['feedback']['result']
 if changed.get('state')!='COMPLETE' or changed.get('version')!=2 or changed.get('after',{}).get('xn__inputsexposure_vya')!=-.25 or changed.get('before',{}).get('xn__inputsexposure_vya')!=-.5:raise ValueError('RECT_CHECKPOINT_FEEDBACK_TWO_REQUIRED')
 return {'job':job,'old_preparation':old,'preparation':prep,'repair':repair,'stages':stages,'checkpoint':checkpoint,'intent':intent,'native':native,'usage':usage,'prior_usage':prior_usage}

def saved_checkpoint_execution_directory(original,value,preparation):
 """同一模型请求只指向这一个保存检查点续接目录。"""
 inputs=saved_checkpoint_inputs(original,preparation);job=inputs['job'];storage=inputs['preparation'].get('pre_native_storage_refusal');directory=Path(original)/('executions/save-repair-02' if storage is not None else 'executions/save-repair-01')
 expected={'schema':'bridge.rectlight-saved-checkpoint-continuation/1','original_job':inputs['repair']['original_job'],'execution_job':file_record(directory/'job.json'),'preparation':preparation,'scope':inputs['preparation']['scope'],'saved_checkpoint_recovery':inputs['repair']}
 if storage is not None:expected['pre_native_storage_refusal']=storage
 execution=json.loads(checked_bytes(expected['execution_job']))
 if (value!=expected or execution.get('directory')!=str(directory) or execution.get('preparation')!=preparation or execution.get('operation_id')!=job['operation_id'] or execution.get('plan')!=job['plan']):raise ValueError('RECT_SAVED_CHECKPOINT_CONTINUATION_REQUIRED')
 return directory

def validate_saved_checkpoint_result(directory,result,preparation):
 """新的正式保存与下游必须有真实完成事实；不得抹去原INTENT或重复曝光修改。"""
 directory=Path(directory);original=directory.parent.parent;inputs=saved_checkpoint_inputs(original,preparation);job=inputs['job']
 route=original/('execution-continuation-storage-repair.json' if inputs['preparation'].get('pre_native_storage_refusal') is not None else 'execution-continuation.json')
 continuation=json.loads(route.read_text())
 if saved_checkpoint_execution_directory(original,continuation,preparation)!=directory:raise ValueError('RECT_CHECKPOINT_RESULT_DIRECTORY_REQUIRED')
 value=json.loads((directory/'incremental-state.json').read_text());stages=value.get('stages',{})
 expected={'checkpoint_reopen','checkpoint_readback','formal_save','save_host_stop','cold_reopen','cold_readback','render','render_completed','render_host_stop','verify','register','nuke_launch_intent','nuke_completed'}
 saved=result.get('saved',{});formal=saved.get('operation_receipt',{});reported=result.get('scope',{});usage=inputs['usage']
 from houdini_bridge.operation_receipts import validate_operation_receipt
 from dcc_task_runtime.canonical import canonical_sha256
 validate_operation_receipt(formal)
 stored=Path(saved.get('operation_store_path',''))
 if (not stored.is_relative_to(directory/'project/control/houdini-instances/fx_operations/producer-records') or json.loads(stored.read_text())!=formal
     or saved.get('sha256')!=file_record(saved['path'])['sha256'] or saved.get('scene_contract_sha256')!=canonical_sha256(saved['scene_contract'])
     or result.get('files',{}).get('hip')!=file_record(saved['path'])):raise ValueError('RECT_CHECKPOINT_REAL_NEW_SAVE_RECEIPT_REQUIRED')
 if (value.get('preparation')!=file_record(directory/'job.json') or set(stages)!=expected or any(x.get('state')!='DONE' for x in stages.values())
     or result.get('feedback')!=inputs['stages']['feedback']['result'] or result.get('plan')!=job['plan'] or result.get('operation_id')!=job['operation_id']
     or result.get('revision')!=2 or result.get('exposure')!=-.25 or result.get('saved_checkpoint_recovery')!={'schema':'bridge.rectlight-saved-checkpoint-result/1','original_recovery':inputs['repair'],'continuation':file_record(route),'preparation':preparation,**({'pre_native_storage_refusal':inputs['preparation']['pre_native_storage_refusal']} if inputs['preparation'].get('pre_native_storage_refusal') is not None else {})}
     or saved!=stages['formal_save']['result'] or saved.get('path')==inputs['repair']['checkpoint']['path']
     or formal.get('state')!='COMPLETED' or formal.get('command')!='scene.save_hip'
     or stages['checkpoint_readback']['result'].get('parms')!=result['feedback']['after'] or stages['cold_readback']['result'].get('parms')!=result['feedback']['after']
     or result.get('artifact')!=stages['register']['result'] or result['artifact'].get('version')!=2
     or reported.get('dcc_starts')!=49 or reported.get('tickets')!=usage['tickets'][:49] or reported['tickets'][:45]!=inputs['prior_usage']['tickets']
     or [t['role'] for t in reported['tickets'][45:]]!=['houdini-host','houdini-host','main-husk','nuke-render'] or any(t.get('stopped_at') is None for t in reported['tickets'])):raise ValueError('RECT_CHECKPOINT_NEW_FORMAL_COMPLETION_REQUIRED')
 return inputs


def render_tail_inputs(directory,preparation):
 """仅认证已同步完成渲染后owner超时的固定尾部，不重写原BLOCKED事实。"""
 from dcc_task_runtime.native_scope import NativeScope
 from .official_graph_resume import _snapshot
 directory=Path(directory);original=directory.parent.parent;prep=json.loads(checked_bytes(preparation));job_record=file_record(directory/'job.json');job=json.loads(checked_bytes(job_record));source_record=job['preparation'];source=json.loads(checked_bytes(source_record))
 # 原scope06的检查点路线仍用原准备认证，不能拿当前07冒称原生生产来源。
 checkpoint=saved_checkpoint_inputs(original,source_record);source_native=checkpoint['native'];source_usage=source_native.snapshot();native=NativeScope(prep['scope']);usage=native.snapshot()
 allowed={'scope','runtime_control','runtime_manifest','runtime_snapshot_manifest','worker','render_terminal_recovery'}
 if (prep.get('render_terminal_recovery') is None or any(prep.get(k)!=source.get(k) for k in set(prep)|set(source) if k not in allowed)
     or directory!=original/'executions/save-repair-02' or original!=Path(source_native.scope['creative_phase']['case_contract']['path']).parent/'jobs'/_RECT_SECOND_OPERATION
     or job.get('operation_id')!=_RECT_SECOND_OPERATION or job.get('directory')!=str(directory) or job.get('plan')!=checkpoint['job']['plan']
     or source_native.path!=native.root/'continuations/luna-rectlight-06/scope.json' or native.path!=native.root/'continuations/luna-rectlight-07/scope.json'
     or native.scope.get('continuation_of')!=file_record(source_native.path) or native.scope.get('creative_phase')!=source_native.scope.get('creative_phase') or native.scope.get('budget')!=source_native.scope.get('budget')
     or source_usage['dcc_starts']!=48 or usage['tickets'][:48]!=source_usage['tickets'] or any(t['stopped_at'] is None for t in source_usage['tickets'])
     or _snapshot(Path(prep['runtime_control']))!=prep['runtime_snapshot_manifest']):raise ValueError('RECT_RENDER_TAIL_EXACT_SOURCE_REQUIRED')
 journal_record=file_record(directory/'incremental-state.json');journal=json.loads(checked_bytes(journal_record));stages=journal.get('stages',{})
 error_record=file_record(directory/'error.json');error=json.loads(checked_bytes(error_record))
 expected={'checkpoint_reopen','checkpoint_readback','formal_save','save_host_stop','cold_reopen','cold_readback','render','render_completed'}
 if (journal.get('preparation')!=job_record or set(stages)!=expected or stages['render_completed']!={'state':'INTENT'}
     or any(v.get('state')!='DONE' for k,v in stages.items() if k!='render_completed')
     or error!={'code':'ValueError','message':'NATIVE_SCOPE_EXECUTION_FAILED','native_success_claimed':False}
     or stages['cold_readback']['result'].get('parms')!=checkpoint['stages']['feedback']['result']['after']
     or stages['formal_save']['result'].get('operation_receipt',{}).get('state')!='COMPLETED'
     or stages['cold_reopen']['result'].get('sha256')!=stages['formal_save']['result'].get('sha256')):raise ValueError('RECT_RENDER_TAIL_COMPLETED_CHECKPOINT_REQUIRED')
 from .rectlight_render_terminal_recovery import validate_render_terminal_recovery
 proof=validate_render_terminal_recovery(prep['render_terminal_recovery'],native)
 return {'job':job,'job_record':job_record,'source_preparation_record':source_record,'source_preparation':source,'preparation':prep,'checkpoint_inputs':checkpoint,'stages':stages,'source_journal':journal_record,'source_error':error_record,'source_native':source_native,'source_usage':source_usage,'native':native,'usage':usage,'proof':proof,'preparation_record':preparation}

def render_tail_execution_directory(original,value,preparation,*,_validated_inputs=None):
 """新尾部路由只指向真实旧exec02，原job与原storage路由保持。"""
 directory=Path(original)/'executions/save-repair-02';inputs=render_tail_inputs(directory,preparation) if _validated_inputs is None else _validated_inputs
 if inputs.get('preparation_record')!=preparation:raise ValueError('RECT_RENDER_TAIL_VALIDATION_BINDING_CHANGED')
 expected={'schema':'bridge.rectlight-render-tail-continuation/1','original_job':file_record(Path(original)/'job.json'),'source_execution_job':inputs['job_record'],'source_preparation':inputs['source_preparation_record'],'preparation':preparation,'scope':inputs['preparation']['scope'],'execution_directory':str(directory),'render_terminal_recovery':inputs['preparation']['render_terminal_recovery']}
 if value!=expected:raise ValueError('RECT_RENDER_TAIL_CONTINUATION_REQUIRED')
 return directory

def validate_render_tail_result(directory,result,preparation):
 """只有新受控verify/正式登记及唯一Nuke冷输出完成后才接收固定尾部结果。"""
 directory=Path(directory);original=directory.parent.parent;inputs=render_tail_inputs(directory,preparation);prep=inputs['preparation'];source=inputs['source_preparation'];stages=inputs['stages']
 route=original/'execution-continuation-render-tail.json';value=json.loads(route.read_text())
 if render_tail_execution_directory(original,value,preparation,_validated_inputs=inputs)!=directory:raise ValueError('RECT_RENDER_TAIL_RESULT_ROUTE_REQUIRED')
 tail_record=file_record(directory/'render-tail-repair-01/incremental-state.json');tail=json.loads(checked_bytes(tail_record));actions=tail.get('stages',{})
 expected_recovery={'schema':'bridge.rectlight-render-tail-result/1','proof':prep['render_terminal_recovery'],'preparation':preparation,'source_job':inputs['job_record'],'source_journal':inputs['source_journal'],'tail_journal':tail_record,'continuation':file_record(route),'native_reexecuted':['nuke-render'],'source_scope':file_record(inputs['source_native'].path)}
 checkpoint_result={'schema':'bridge.rectlight-saved-checkpoint-result/1','original_recovery':source['saved_checkpoint_recovery'],'continuation':file_record(original/'execution-continuation-storage-repair.json'),'preparation':inputs['source_preparation_record'],'pre_native_storage_refusal':source['pre_native_storage_refusal']}
 usage=inputs['usage'];reported=result.get('scope',{});saved=result.get('saved',{});fact=actions.get('verify',{}).get('result',{}).get('execution_fact',{})
 if (result.get('render_terminal_recovery')!=expected_recovery or result.get('saved_checkpoint_recovery')!=checkpoint_result
     or tail.get('preparation')!=preparation or set(actions)!={'verify','register','nuke_launch_intent','nuke_completed'} or any(x.get('state')!='DONE' for x in actions.values())
     or result.get('operation_id')!=inputs['job']['operation_id'] or result.get('plan')!=inputs['job']['plan'] or result.get('revision')!=2 or result.get('exposure')!=-.25
     or result.get('feedback')!=inputs['checkpoint_inputs']['stages']['feedback']['result'] or saved!=stages['formal_save']['result']
     or result.get('artifact')!=actions['register']['result'] or result['artifact'].get('version')!=2
     or fact.get('state')!='COMPLETED' or actions['verify']['result'].get('verification_basis')!='controlled_output_v1'
     or fact.get('render_terminal_recovery')!=prep['render_terminal_recovery']
     or result.get('comparison',{}).get('state')!='PASS' or result['comparison'].get('different_samples')!=0 or result['comparison'].get('samples_compared')!=504000
     or reported.get('dcc_starts')!=49 or reported.get('tickets')!=usage['tickets'][:49] or reported['tickets'][:48]!=inputs['source_usage']['tickets']
     or len(reported['tickets'])!=49 or reported['tickets'][-1]['role']!='nuke-render' or any(t.get('stopped_at') is None for t in reported['tickets'])
     or actions['nuke_completed']['result'].get('state')!='COMPLETED' or actions['nuke_completed']['result'].get('ledger_state')!='REGISTERED'):raise ValueError('RECT_RENDER_TAIL_TRUE_COMPLETION_REQUIRED')
 from houdini_bridge.operation_receipts import validate_operation_receipt
 validate_operation_receipt(saved['operation_receipt'])
 if json.loads(Path(saved['operation_store_path']).read_text())!=saved['operation_receipt'] or file_record(saved['path'])!=result['files']['hip']:raise ValueError('RECT_RENDER_TAIL_FORMAL_SAVE_CHANGED')
 return inputs

def historical_rect_preparation_compatible(historical,current):
 """只为已完成首轮查询承认准确04→05、同预算同案例的历史准备。"""
 if historical.get('task_id')!=current.get('task_id') or historical.get('model_route')!=current.get('model_route'):return False
 if historical.get('scope')==current.get('scope'):return True
 if current.get('nuke_retry_recovery') is not None:
  from dcc_task_runtime.native_scope import NativeScope
  retry=validate_nuke_retry_recovery(current['nuke_retry_recovery'],NativeScope(current['scope']))
  return historical_rect_preparation_compatible(historical,retry['source_preparation'])
 if current.get('render_terminal_recovery') is not None:
  from dcc_task_runtime.native_scope import NativeScope
  native=NativeScope(current['scope']);directory=Path(native.scope['creative_phase']['case_contract']['path']).parent/'jobs'/_RECT_SECOND_OPERATION/'executions/save-repair-02'
  # 当前准备的文件身份由会话入口固定；递归只回到原06准备，不开放任意祖先。
  source_job=json.loads((directory/'job.json').read_text());source=json.loads(checked_bytes(source_job['preparation']))
  old_native=NativeScope(source['scope'])
  if (native.path!=native.root/'continuations/luna-rectlight-07/scope.json' or native.scope.get('continuation_of')!=file_record(old_native.path) or native.scope.get('budget')!=old_native.scope.get('budget') or native.scope.get('creative_phase')!=old_native.scope.get('creative_phase') or old_native.snapshot()['dcc_starts']!=48 or native.snapshot()['tickets'][:48]!=old_native.snapshot()['tickets']):return False
  from .rectlight_render_terminal_recovery import validate_render_terminal_recovery
  validate_render_terminal_recovery(current['render_terminal_recovery'],native)
  return historical_rect_preparation_compatible(historical,source)
 if historical.get('scope')==current.get('scope'):return True
 from dcc_task_runtime.native_scope import NativeScope
 old=NativeScope(historical['scope']);new=NativeScope(current['scope'])
 if (historical.get('case_id')!='karma_lights_rectlight_v1' or current.get('case_id')!=historical.get('case_id')
     or not _checkpoint_scope_chain(old,new,storage=current.get('pre_native_storage_refusal') is not None)):return False
 if current.get('pre_native_storage_refusal') is not None:
  original=Path(new.scope['creative_phase']['case_contract']['path']).parent/'jobs'/_RECT_SECOND_OPERATION
  validate_pre_native_storage_refusal(original,current['pre_native_storage_refusal'],new)
 return all(historical.get(k)==current.get(k) for k in ('configuration','case_variant','ledger_root','task_id','model_route'))


_RECT_NUKE_RETRY='nrend-cd8fc492bb4b1171'
_RECT_NUKE_RETRY_REQUEST='creative_bff6f898fafe1db03aae_nuke_retry01'

def validate_nuke_retry_recovery(record,active_scope):
 """正常冷消费前现验固定重试合同；不递归整链，不缓存当前范围或账本。"""
 from dcc_task_runtime.native_scope import NativeScope
 from dcc_task_runtime import owned_process
 from dcc_task_runtime.canonical import canonical_sha256
 native=active_scope if hasattr(active_scope,'snapshot') else NativeScope(active_scope)
 directory=Path(native.scope['creative_phase']['case_contract']['path']).parent/'jobs'/_RECT_SECOND_OPERATION/'executions/save-repair-02';control=directory/'project/control'
 contract=json.loads(checked_bytes(record));fields={'schema','task_id','operation_id','scope','revision','source_preparation','source_job','source_tail_journal','failed_closure','failed_script','failed_output','failed_context','source_input','retry_request_id','retry_operation_id','retry_script','retry_pattern','retry_context'}
 if (Path(record['path'])!=directory/'nuke-retry01/recovery-contract.json' or set(contract)!=fields or contract.get('schema')!='bridge.rectlight-nuke-retry-recovery/1'
     or contract.get('task_id')!=_RECT_RESUME_TASK or contract.get('operation_id')!=_RECT_SECOND_OPERATION or contract.get('scope')!=native.binding
     or contract.get('revision')!=native.scope.get('case_nuke_retry_revision') or native.effective_creative_starts()!=17
     or native.scope.get('budget',{}).get('max_dcc_starts')!=50 or native.scope['creative_phase'].get('starts')!=16
     or contract.get('retry_request_id')!=_RECT_NUKE_RETRY_REQUEST or contract.get('retry_operation_id')!=_RECT_NUKE_RETRY
     or contract.get('retry_script')!=str(directory/'project/saves/composite-retry01.nk') or contract.get('retry_pattern')!=str(directory/'project/saves/nuke-retry01.%04d.exr')
     or contract.get('retry_context')!=str(control/'nuke-retry01/cold-context.json')):raise ValueError('RECT_NUKE_RETRY_FIXED_CONTRACT_REQUIRED')
 paths={'source_job':directory/'job.json','source_tail_journal':directory/'render-tail-repair-01/incremental-state.json','failed_closure':directory/'nuke-timeout49/negative-closure.json','failed_script':directory/'project/saves/composite.nk','failed_output':directory/'project/saves/nuke.0001.exr','failed_context':control/'cold-context.json','source_input':control/'creative-input-source.json'}
 if any(contract[k]!=file_record(path) for k,path in paths.items()):raise ValueError('RECT_NUKE_RETRY_ORIGINAL_IDENTITY_REQUIRED')
 for key in ('revision','source_preparation'):checked_bytes(contract[key])
 revision=json.loads(checked_bytes(contract['revision']));closure=json.loads(checked_bytes(contract['failed_closure']));tail=json.loads(checked_bytes(contract['source_tail_journal']));prep=json.loads(checked_bytes(contract['source_preparation']));source=json.loads(checked_bytes(contract['source_input']))
 historical=native._continuation_previous;producer=historical._continuation_previous;usage=native.snapshot();historical_tickets=native._continuation_state['tickets']
 if (historical.path!=native.root/'continuations/luna-rectlight-07/scope.json' or producer.path!=native.root/'continuations/luna-rectlight-06/scope.json'
     or native.scope.get('continuation_of')!=file_record(historical.path) or historical.scope.get('continuation_of')!=file_record(producer.path)
     or native.scope.get('creative_phase')!=historical.scope.get('creative_phase') or historical.scope.get('creative_phase')!=producer.scope.get('creative_phase')
     or native.scope.get('budget')!=dict(historical.scope['budget'],max_dcc_starts=50) or historical.scope['budget']!=producer.scope['budget']
     or revision.get('previous_scope')!=file_record(historical.path) or revision.get('failed_attempt_closure')!=contract['failed_closure']
     or prep.get('scope')!=historical.binding or prep.get('render_terminal_recovery')!=source.get('render_terminal_recovery')
     or tail.get('preparation')!=contract['source_preparation'] or set(tail.get('stages',{}))!={'verify','register','nuke_launch_intent'} or any(x.get('state')!='DONE' for x in tail['stages'].values())
     or len(historical_tickets)!=49 or usage['tickets'][:49]!=historical_tickets or any(t['stopped_at'] is None for t in historical_tickets)
     or len(usage['tickets']) not in (49,50)):raise ValueError('RECT_NUKE_RETRY_EXACT_49_PREFIX_REQUIRED')
 extra=usage['tickets'][49:]
 if any(t.get('role')!='nuke-render' or t.get('identity',{}).get('operation_id')!=_RECT_NUKE_RETRY or t.get('directory')!=str(native.root/'state/nuke_renders'/(_RECT_NUKE_RETRY+'.supervisor')) for t in extra):raise ValueError('RECT_NUKE_RETRY_ONLY_CONSUMER_REQUIRED')
 last=historical_tickets[-1];stop=owned_process.read_receipt(last['directory'],'stopped',identity=last['identity']);failed=json.loads(checked_bytes(closure['render_after']));slot=json.loads(checked_bytes(closure['after_slot']))
 if (closure.get('schema')!='bridge.rectlight-nuke49-negative-closure/1' or closure.get('state')!='FAILED' or closure.get('stop_confirmed') is not True or closure.get('slot_released') is not True or closure.get('scope')!=historical.binding
     or closure.get('operation_id')!='nrend-8c28ece78d32bc97' or last['identity'].get('operation_id')!=closure['operation_id']
     or not stop or stop.get('stop_reason')!='TIME_BUDGET_EXCEEDED' or owned_process.execution_returncode(stop)!=2
     or failed.get('state')!='FAILED' or slot.get('active')!=0 or slot.get('phase')!='RELEASED' or closure.get('completed_native_render_claimed') is not False):raise ValueError('RECT_NUKE_RETRY_FAILED_NOT_UPGRADED_REQUIRED')
 for key in ('render_before','before_slot','signed_stopped','worker_result','live_render'):checked_bytes(closure[key])
 artifact=tail['stages']['register']['result'];fact=tail['stages']['verify']['result']['execution_fact']
 if (source.get('task_id')!=_RECT_RESUME_TASK or source.get('artifact_id')!='rectlight_creative_main' or source.get('artifact_version')!=2
     or source.get('producer_scope')!=file_record(producer.path) or source.get('producer_control')!=str(control) or source.get('creative_phase')!=native.scope['creative_phase']
     or source.get('producer_fact_sha256')!=canonical_sha256(fact) or source.get('registry_operation_receipt')!=artifact.get('registry_operation_receipt')
     or tail['stages']['nuke_launch_intent']['result'].get('operation_id')!=closure['operation_id']):raise ValueError('RECT_NUKE_RETRY_SAME_MAIN_V2_REQUIRED')
 return {'contract':contract,'source_native':producer,'source_scope':file_record(producer.path),'historical_native':historical,'historical_scope':file_record(historical.path),'native':native,'source_preparation':prep,'source_preparation_record':contract['source_preparation'],'closure':closure,'retry_operation_id':_RECT_NUKE_RETRY,'retry_request_id':_RECT_NUKE_RETRY_REQUEST,'usage':usage,'historical_usage':{'dcc_starts':49,'tickets':historical_tickets}}

def nuke_retry_inputs(directory,preparation):
 """控制端/最终接收完整认证一次历史尾部；冷消费使用上面的实时轻量合同门。"""
 from dcc_task_runtime.native_scope import NativeScope
 from .official_graph_resume import _snapshot
 directory=Path(directory);prep=json.loads(checked_bytes(preparation));native=NativeScope(prep['scope']);recovery=validate_nuke_retry_recovery(prep['nuke_retry_recovery'],native)
 source=recovery['source_preparation'];allowed={'scope','runtime_control','runtime_manifest','runtime_snapshot_manifest','worker','native_phase_limit','nuke_retry_recovery'}
 if (any(prep.get(k)!=source.get(k) for k in set(prep)|set(source) if k not in allowed) or prep.get('native_phase_limit')!={'starts':17,'seconds':1800}
     or _snapshot(Path(prep['runtime_control']))!=prep['runtime_snapshot_manifest']):raise ValueError('RECT_NUKE_RETRY_PREPARATION_REQUIRED')
 old=render_tail_inputs(directory,recovery['source_preparation_record'])
 return dict(recovery,preparation=prep,preparation_record=preparation,tail_inputs=old)

def nuke_retry_execution_directory(original,value,preparation):
 directory=Path(original)/'executions/save-repair-02';inputs=nuke_retry_inputs(directory,preparation);contract=inputs['contract']
 expected={'schema':'bridge.rectlight-nuke-retry-continuation/1','original_job':file_record(Path(original)/'job.json'),'source_execution_job':contract['source_job'],'source_tail_preparation':contract['source_preparation'],'preparation':preparation,'scope':inputs['preparation']['scope'],'execution_directory':str(directory),'nuke_retry_recovery':inputs['preparation']['nuke_retry_recovery']}
 if value!=expected:raise ValueError('RECT_NUKE_RETRY_CONTINUATION_REQUIRED')
 return directory

def validate_nuke_retry_result(directory,result,preparation):
 directory=Path(directory);original=directory.parent.parent;inputs=nuke_retry_inputs(directory,preparation);prep=inputs['preparation'];old=inputs['tail_inputs'];contract=inputs['contract'];route=original/'execution-continuation-nuke-retry01.json'
 if nuke_retry_execution_directory(original,json.loads(route.read_text()),preparation)!=directory:raise ValueError('RECT_NUKE_RETRY_RESULT_ROUTE_REQUIRED')
 journal_record=file_record(directory/'nuke-retry01/incremental-state.json');journal=json.loads(checked_bytes(journal_record));stages=journal.get('stages',{});tail=json.loads(checked_bytes(contract['source_tail_journal']));reported=result.get('scope',{})
 marker={'schema':'bridge.rectlight-nuke-retry-result/1','contract':prep['nuke_retry_recovery'],'preparation':preparation,'retry_journal':journal_record,'source_tail_journal':contract['source_tail_journal'],'continuation':file_record(route),'failed_attempt':contract['failed_closure'],'native_reexecuted':['nuke-render']}
 provenance={'schema':'bridge.rectlight-render-tail-source/1','proof':prep['render_terminal_recovery'],'source_preparation':contract['source_preparation'],'source_tail_journal':contract['source_tail_journal'],'source_job':contract['source_job'],'source_journal':old['source_journal']}
 if (result.get('render_terminal_recovery')!=provenance or result.get('nuke_retry_recovery')!=marker or journal.get('preparation')!=preparation or set(stages)!={'nuke_launch_intent','nuke_completed'} or any(x.get('state')!='DONE' for x in stages.values())
     or result.get('operation_id')!=_RECT_SECOND_OPERATION or result.get('plan')!=old['job']['plan'] or result.get('revision')!=2 or result.get('exposure')!=-.25
     or result.get('saved')!=old['stages']['formal_save']['result'] or result.get('feedback')!=old['checkpoint_inputs']['stages']['feedback']['result'] or result.get('artifact')!=tail['stages']['register']['result']
     or result.get('nuke',{}).get('operation_id')!=_RECT_NUKE_RETRY or result['nuke']['artifact'].get('pattern')!=contract['retry_pattern']
     or result['nuke']['files'].get('nk')!=file_record(contract['retry_script']) or result['nuke']['files'].get('exr')!=file_record(contract['retry_pattern']%1)
     or result.get('files',{}).get('nk')!=result['nuke']['files']['nk'] or result['files'].get('nuke')!=result['nuke']['files']['exr']
     or stages['nuke_launch_intent']['result'].get('operation_id')!=_RECT_NUKE_RETRY
     or stages['nuke_completed']['result'].get('state')!='COMPLETED' or stages['nuke_completed']['result'].get('ledger_state')!='REGISTERED'
     or reported.get('dcc_starts')!=50 or reported.get('tickets')!=inputs['usage']['tickets'][:50] or reported['tickets'][:49]!=inputs['historical_usage']['tickets']
     or len(reported['tickets'])!=50 or any(t['stopped_at'] is None for t in reported['tickets'])
     or result.get('native_phase_limit')!={'starts':17,'seconds':1800} or result.get('comparison',{}).get('state')!='PASS' or result['comparison'].get('different_samples')!=0 or result['comparison'].get('samples_compared')!=504000):raise ValueError('RECT_NUKE_RETRY_NORMAL_COMPLETION_REQUIRED')
 from dcc_task_runtime import owned_process
 last=reported['tickets'][-1];stop=owned_process.read_receipt(last['directory'],'stopped',identity=last['identity'])
 if not stop or stop.get('stop_reason') is not None or owned_process.execution_returncode(stop)!=0:raise ValueError('RECT_NUKE_RETRY_NORMAL_SIGNED_ZERO_REQUIRED')
 return inputs

def validate_nuke_completion(registry,result,scope,*,historical=None):
 """确认相同模型作业的Nuke派生正式收据与已释放槽，不凭结果文字接收。"""
 expected='nrend-'+hashlib.sha256((result['operation_id']+'_nuke').encode()).hexdigest()[:16]
 if result.get('nuke_retry_recovery') is not None:
  validate_nuke_retry_recovery(result['nuke_retry_recovery']['contract'],scope);expected=_RECT_NUKE_RETRY
 item=result['nuke'];artifact=item['artifact']
 if item['operation_id']!=expected or artifact['artifact_id']!='nuke-render-'+expected:
  raise ValueError('CREATIVE_NUKE_OPERATION_BINDING_REQUIRED')
 from nuke_bridge.operation_receipts import completed_operation_projection,receipt_errors
 fact=registry._operation_facts(expected,task_id=result['task_id'],frames=[1],pattern=artifact['pattern'],scene_fingerprint=artifact['scene_fingerprint'])
 formal=fact.get('formal_receipt');projection=completed_operation_projection(formal,fact)
 if (not isinstance(formal,dict) or receipt_errors(formal) or not projection
     or projection.get('completion_metadata_status')!='AVAILABLE' or projection.get('stop_confirmed') is not True
     or artifact.get('task_id')!=result['task_id']
     or artifact.get('operation_receipt_sha256')!=fact.get('operation_receipt_sha256')
     or item.get('formal_operation_receipt',formal)!=formal
     or historical is None and not registry.verify(artifact['artifact_id'])['usable']):
  raise ValueError('CREATIVE_NUKE_TYPED_RECEIPT_REQUIRED')
 if historical is not None:
  from dcc_task_runtime.historical_artifacts import verify_historical_artifact
  verify_historical_artifact(registry,artifact,fact,superseding=historical)
  validate_historical_nuke_stop(result,scope,formal)
  return formal
 row=GraphScheduler(Path(scope.path).parent/'scheduler').snapshot()
 if row is None or row.get('active')!=0 or row.get('phase')!='RELEASED' or row.get('operation_id')!=expected:
  raise ValueError('CREATIVE_NUKE_SLOT_RELEASE_REQUIRED')
 return formal


def validate_historical_nuke_stop(result,scope,formal):
 """Bind the original released attempt after the scheduler has advanced."""
 import sqlite3
 from contextlib import closing
 from dcc_task_runtime import owned_process
 operation=result['nuke']['operation_id']
 path=scope.root/'state/nuke_renders'/(operation+'.json')
 task_record=file_record(path);task=json.loads(checked_bytes(task_record));slot=task.get('slot',{})
 identity=task.get('supervisor_intent',{}).get('identity')
 if (task.get('task_id')!=operation or task.get('owner_task_id')!=result['task_id']
     or task.get('slot_released') is not True or slot.get('operation_id')!=operation
     or task.get('state')!='COMPLETED' or task.get('ledger_state')!='REGISTERED'):
  raise ValueError('CREATIVE_HISTORICAL_NUKE_STOP_REQUIRED')
 started=owned_process.read_receipt(task['supervisor_intent']['directory'],'started',identity=identity)
 started_bytes=owned_process._canonical(started)
 native_binding=(started.get('resource_budget') or {}).get('native_scope') if started else None
 original=scope
 for _ in range(16):
  if original is None or original.binding==native_binding:break
  original=getattr(original,'_continuation_previous',None)
 if (not started or started.get('identity')!=identity or original is None or original.binding!=native_binding
     or original.root!=scope.root or (original.scope.get('creative_phase') or {}).get('task_id')!=result['task_id']
     or original.scope.get('creative_phase')!=scope.scope.get('creative_phase')):
  raise ValueError('CREATIVE_HISTORICAL_NUKE_SCOPE_REQUIRED')
 scheduler=Path(original.path).parent/'scheduler/graph_scheduler.sqlite3'
 def read_attempt():
  if scheduler.is_symlink() or not scheduler.is_file():raise ValueError('CREATIVE_HISTORICAL_NUKE_STOP_REQUIRED')
  with closing(sqlite3.connect(scheduler.as_uri()+'?mode=ro',uri=True)) as db:
   return db.execute('SELECT fact_json FROM stopped_attempts WHERE owner_root=? AND operation_id=? AND token=?',
       (slot['owner_root'],operation,slot['token'])).fetchone()
 saved=read_attempt()
 if not saved:raise ValueError('CREATIVE_HISTORICAL_NUKE_STOP_REQUIRED')
 attempt=json.loads(saved[0]);process=json.loads(attempt['process_json'])
 if (attempt.get('observed_stopped') is not True or attempt.get('generation')!=slot['generation']
     or any(attempt.get(k)!=slot[k] for k in ('owner_root','operation_id','token'))
     or process.get('supervisor_identity')!=identity
     or process.get('supervisor_directory')!=task['supervisor_intent']['directory']):
  raise ValueError('CREATIVE_HISTORICAL_NUKE_STOP_REQUIRED')
 stopped=owned_process.read_receipt(task['supervisor_intent']['directory'],'stopped',identity=identity)
 stopped_bytes=owned_process._canonical(stopped)
 if (not stopped or stopped.get('stop_reason') is not None or owned_process.execution_returncode(stopped)!=0
     or stopped.get('pid')!=started.get('pid')
     or stopped.get('started_sha256')!=hashlib.sha256(owned_process._canonical(started)).hexdigest()
     or formal.get('operation_id')!=operation):
  raise ValueError('CREATIVE_HISTORICAL_NUKE_STOP_REQUIRED')
 if (owned_process._canonical(owned_process.read_receipt(task['supervisor_intent']['directory'],'stopped',identity=identity))!=stopped_bytes
     or owned_process._canonical(owned_process.read_receipt(task['supervisor_intent']['directory'],'started',identity=identity))!=started_bytes
     or read_attempt()!=saved or file_record(path)!=task_record):
  raise ValueError('CREATIVE_HISTORICAL_NUKE_CHANGED_DURING_READ')
