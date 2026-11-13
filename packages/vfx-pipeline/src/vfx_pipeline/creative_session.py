"""外部agent真实观察、计划及异步创作会话；不接受任意脚本或路径。"""
from __future__ import annotations
import base64,hashlib,json,math,os,subprocess,time,uuid
from pathlib import Path
from datetime import datetime,timezone
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_karma_observation import checked_bytes,file_record
from .workbuddy_mcp import DiagnosticMCP,_schema,_text_content,OBSERVATION,IDENTIFIER
from .workbuddy_graph_mcp import _schema_error

TOOLS=[
 {'name':'health','description':'Read the authorized task, current exposure and bounded workflow. No native startup.','inputSchema':_schema()},
 {'name':'catalog','description':'List actual registered reference/current/preview image IDs.','inputSchema':_schema()},
 {'name':'media','description':'Read actual PNG pixels for one registered image ID. You must inspect both reference and current preview before planning.','inputSchema':_schema({'asset_id':IDENTIFIER},('asset_id',))},
 {'name':'submit_observation','description':'Submit your own actual image observations; do not copy instructions as observations.','inputSchema':_schema({'asset_id':IDENTIFIER,'request_id':IDENTIFIER,'observation':OBSERVATION},('asset_id','request_id','observation'))},
 {'name':'submit_plan','description':'Plan one actual lighting adjustment from observed images. Choose exposure yourself within [-1,3] and at most 2 stops from current exposure. Existing camera/geometry/material stay fixed.','inputSchema':_schema({'request_id':IDENTIFIER,'goal':{'type':'string','minLength':10,'maxLength':2000},'rationale':{'type':'string','minLength':20,'maxLength':4000},'exposure':{'type':'number','minimum':-1,'maximum':3},'observation_ids':{'type':'array','minItems':2,'maxItems':8,'uniqueItems':True,'items':IDENTIFIER}},('request_id','goal','rationale','exposure','observation_ids'))},
 {'name':'create_preview','description':'Execute your submitted plan once, asynchronously. Returns a durable operation_id. After timeout/reconnect query that ID; never create another request to retry.','inputSchema':_schema({'plan_id':IDENTIFIER,'request_id':IDENTIFIER},('plan_id','request_id'))},
 {'name':'operation_query','description':'Query the same durable creative job. Waits at most 20 seconds, never starts or repeats DCC. On COMPLETE inspect returned new image then plan feedback.','inputSchema':_schema({'operation_id':IDENTIFIER},('operation_id',))},
 {'name':'delivery','description':'Read final completion after two distinct model-selected, native-verified changes and previews.','inputSchema':_schema()},
]
for tool in TOOLS:
 tool['annotations']={'readOnlyHint':tool['name'] in ('health','catalog','operation_query','delivery'), 'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}

class CreativeSession:
 """所有会话共用持久任务状态；模型不能注册媒体、改变预算或直接执行宿主。"""
 def __init__(self,preparation,*,state_directory=None):
  self.preparation=file_record(Path(preparation));self.prep=json.loads(checked_bytes(self.preparation));self.root=Path(preparation).parent
  # 插件消费者可独立接收原任务结果，原执行路径与准备身份保持不变。
  state_root=self.root if state_directory is None else Path(state_directory)
  self.state_root=state_root
  self.state_path=state_root/'creative-state.json';self.log=state_root/'creative-events.jsonl'
  if not self.state_path.exists():raise ValueError('CREATIVE_PREPARED_STATE_REQUIRED')
 def _read(self):return json.loads(self.state_path.read_text())
 def _write(self,value):atomic_write(self.state_path,json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode(),owned_root=self.state_root)
 def _event(self,kind,payload):
  previous=None;seq=0
  if self.log.exists():
   last=json.loads(self.log.read_text().splitlines()[-1]);previous=last['sha256'];seq=last['seq']+1
  body={'seq':seq,'time':datetime.now(timezone.utc).isoformat(),'kind':kind,'payload':payload,'previous':previous}
  body['sha256']=canonical_sha256(body)
  with self.log.open('a',encoding='utf-8') as f:f.write(json.dumps(body,ensure_ascii=False,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
 def record_event(self,kind,payload):
  with execution_lock(self.state_root,'creative-session'):self._event(kind,payload)
 def health(self):
  state=self._read()
  if self.prep.get('nuke_retry_recovery') is not None:
   from dcc_task_runtime.native_scope import NativeScope
   native=NativeScope(self.prep['scope'])
   if self.prep.get('native_phase_limit')!={'starts':native.effective_creative_starts(),'seconds':1800}:raise ValueError('CREATIVE_EFFECTIVE_RETRY_LIMIT_MISMATCH')
  return {'task_id':self.prep['task_id'],**self.prep.get('model_route',{'route':'UNSELECTED','selected_model':'UNSELECTED','provider_identity':'unknown'}),
    'domain':'lighting_camera_render_v1','source':self.prep.get('case_id','existing_registered_DiskLight'),'completed_revisions':len(state['completed']),
    'active_operations':[{'operation_id':key,'state':value['state'],'request_id':value['request_id']} for key,value in state['jobs'].items() if value['state'] not in ('COMPLETE','FAILED')],
    'current_exposure':state['current_exposure'],'current_image_id':state['current_asset'],'reference_id':'reference',
    'allowed_exposure':[-1,3],'maximum_exposure_delta':2,'preserve':['camera','geometry','materials','frame1','420x300','ACEScg'],
    'required_revisions':2,'native_phase_limit':self.prep.get('native_phase_limit',{'starts':10,'seconds':1200}),'backend_instructions':'Inspect media, submit your own observations and plan, create once, poll original operation ID. Tools never ask you to run terminal commands.'}
 def catalog(self):return [{k:v for k,v in item.items() if k!='file'} for item in self._read()['assets'].values()]
 def media(self,asset_id):
  with execution_lock(self.state_root,'creative-session'):
   state=self._read();asset=state['assets'].get(asset_id)
   if not asset:raise ValueError('CREATIVE_REGISTERED_MEDIA_REQUIRED')
   raw=checked_bytes(asset['file']);state['served'][asset_id]=asset['file']['sha256'];self._write(state)
   self._event('media_served',{'asset_id':asset_id,'sha256':asset['file']['sha256'],'bytes':len(raw),'display_sha256':self.prep['display']['sha256']})
   return {'type':'image','mimeType':'image/png','data':base64.b64encode(raw).decode()}
 def submit_observation(self,asset_id,observation,request_id):
  with execution_lock(self.state_root,'creative-session'):
   state=self._read();asset=state['assets'].get(asset_id)
   if not asset or state['served'].get(asset_id)!=asset['file']['sha256']:raise ValueError('CREATIVE_VIEW_ACTUAL_MEDIA_FIRST')
   body={'observation_id':request_id,'asset_id':asset_id,'image_sha256':asset['file']['sha256'],'observation':observation}
   old=state['observations'].get(request_id)
   if old and old!=body:raise ValueError('CREATIVE_OBSERVATION_REQUEST_CONFLICT')
   state['observations'][request_id]=body;self._write(state);self._event('observation_submitted',body)
   return {'observation_id':request_id,'asset_id':asset_id,'stored':True,'provider_identity':'unknown'}
 def submit_plan(self,**arguments):
  with execution_lock(self.state_root,'creative-session'):
   state=self._read()
   if len(state['completed'])>=2:raise ValueError('CREATIVE_TWO_REVISIONS_COMPLETE')
   observations=[state['observations'].get(k) for k in arguments['observation_ids']]
   if any(x is None for x in observations) or not {'reference',state['current_asset']}.issubset({x['asset_id'] for x in observations}):raise ValueError('CREATIVE_REFERENCE_AND_CURRENT_OBSERVATIONS_REQUIRED')
   value=arguments['exposure']
   if type(value) not in (int,float) or not math.isfinite(value) or not -1<=value<=3 or value==state['current_exposure'] or abs(value-state['current_exposure'])>2:raise ValueError('CREATIVE_DISTINCT_BOUNDED_CHANGE_REQUIRED')
   identifier=arguments['request_id'];body={'plan_id':identifier,'revision':len(state['completed'])+1,'base_exposure':state['current_exposure'],'current_asset':state['current_asset'],**arguments}
   old=state['plans'].get(identifier)
   if old and old!=body:raise ValueError('CREATIVE_PLAN_REQUEST_CONFLICT')
   state['plans'][identifier]=body;self._write(state);self._event('plan_submitted',body)
   return {'plan_id':identifier,'revision':body['revision'],'exposure':value,'ready':True}
 def create_preview(self,plan_id,request_id):
  with execution_lock(self.state_root,'creative-session'):
   state=self._read();plan=state['plans'].get(plan_id)
   if not plan:raise ValueError('CREATIVE_VALID_PLAN_REQUIRED')
   prior=state['requests'].get(request_id)
   if prior:
    if prior['plan_id']!=plan_id:raise ValueError('CREATIVE_OPERATION_REQUEST_CONFLICT')
    return {**prior,'replayed':True}
   if any(x['state']!='COMPLETE' for x in state['jobs'].values()):raise ValueError('CREATIVE_QUERY_OR_CONTROLLER_REPAIR_REQUIRED')
   if plan['revision']!=len(state['completed'])+1 or plan['base_exposure']!=state['current_exposure']:raise ValueError('CREATIVE_PLAN_IS_STALE')
   operation='creative_'+hashlib.sha256(request_id.encode()).hexdigest()[:20]
   directory=self.root/'jobs'/operation;directory.mkdir(parents=True)
   job={'operation_id':operation,'plan_id':plan_id,'request_id':request_id,'revision':plan['revision'],'state':'QUEUED','directory':str(directory)}
   state['jobs'][operation]=job;state['requests'][request_id]=job;self._write(state)
   launch={'schema':'bridge.creative-job/1','preparation':self.preparation,'plan':plan,'operation_id':operation,'directory':str(directory)}
   jobfile=directory/'job.json'
   with jobfile.open('x') as f:json.dump(launch,f,ensure_ascii=False,indent=2)
   self._event('creative_job_accepted',{'operation_id':operation,'plan':plan,'job':file_record(jobfile)})
   command=[self.prep['supervisor_python'],'-I','-B',self.prep['worker'],'run-job','--job',str(jobfile)]
   try:
    with (directory/'controller.stdout.log').open('xb') as out,(directory/'controller.stderr.log').open('xb') as err:
     child=subprocess.Popen(command,cwd=str(directory),stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
   except OSError as error:
    atomic_write(directory/'error.json',json.dumps({'code':'CONTROLLER_START_FAILED','message':type(error).__name__,'native_success_claimed':False}).encode(),owned_root=directory)
    self._event('creative_controller_start_failed',{'operation_id':operation,'code':type(error).__name__})
    return {'operation_id':operation,'state':'FAILED','instruction':'Controller repair required; query the same operation ID.'}
   (directory/'controller-pid.json').write_text(json.dumps({'pid':child.pid,'command_sha256':canonical_sha256(command)}))
   return {'operation_id':operation,'state':'QUEUED','next_poll_seconds':10,'instruction':'Poll operation_query with this ID. Never resend create_preview.'}
 def _execution_directory(self,job):
  """只接受绑定原模型请求的控制端修复入口；模型不能换ID或改写原作业。"""
  original=Path(job['directory'])
  if self.prep.get('nuke_retry_recovery') is not None and job['operation_id']=='creative_bff6f898fafe1db03aae':
   from .creative_results import nuke_retry_execution_directory
   value=json.loads((original/'execution-continuation-nuke-retry01.json').read_text());directory=nuke_retry_execution_directory(original,value,self.preparation)
   if json.loads(checked_bytes(value['source_execution_job']))['plan']!=self._read()['plans'][job['plan_id']]:raise ValueError('RECT_NUKE_RETRY_MODEL_PLAN_REQUIRED')
   return directory
  if self.prep.get('render_terminal_recovery') is not None and job['operation_id']=='creative_bff6f898fafe1db03aae':
   from .creative_results import render_tail_execution_directory
   receipt=original/'execution-continuation-render-tail.json'
   value=json.loads(receipt.read_text());directory=render_tail_execution_directory(original,value,self.preparation)
   if json.loads(checked_bytes(value['source_execution_job']))['plan']!=self._read()['plans'][job['plan_id']]:raise ValueError('RECT_RENDER_TAIL_MODEL_PLAN_REQUIRED')
   return directory
  receipt=original/('execution-continuation-storage-repair.json' if self.prep.get('pre_native_storage_refusal') is not None and job['operation_id']=='creative_bff6f898fafe1db03aae' else 'execution-continuation.json')
  if not receipt.exists():return original
  value=json.loads(receipt.read_text())
  if value.get('schema')=='bridge.rectlight-saved-checkpoint-continuation/1':
   from .creative_results import saved_checkpoint_execution_directory
   directory=saved_checkpoint_execution_directory(original,value,self.preparation)
   execution=json.loads(checked_bytes(value['execution_job']))
   if execution.get('plan')!=self._read()['plans'][job['plan_id']]:raise ValueError('RECT_SAVED_CHECKPOINT_MODEL_PLAN_REQUIRED')
   return directory
  newprep=json.loads(checked_bytes(value['preparation']))
  old=json.loads(checked_bytes(value['original_job']));execution=json.loads(checked_bytes(value['execution_job']))
  directory=original/'executions'/'repair-01'
  if (value.get('schema')!='bridge.creative-execution-continuation/1'
      or Path(value['original_job']['path'])!=original/'job.json'
      or value['preparation']!=self.preparation or value.get('scope')!=self.prep['scope']
      or newprep.get('scope')!=self.prep['scope']
      or Path(value['execution_job']['path'])!=directory/'job.json'
      or execution.get('directory')!=str(directory) or execution.get('preparation')!=self.preparation
      or old.get('operation_id')!=job['operation_id'] or execution.get('operation_id')!=job['operation_id']
      or old.get('plan')!=execution.get('plan') or old.get('plan')!=self._read()['plans'][job['plan_id']]
      or old.get('plan',{}).get('request_id')!=job['plan_id']):
   raise ValueError('CREATIVE_CONTROLLER_CONTINUATION_BINDING_REQUIRED')
  stopped=json.loads(checked_bytes(value['pre_native_stop']))
  if stopped.get('state')!='STOPPED_BEFORE_NATIVE' or stopped.get('operation_id')!=job['operation_id'] or stopped.get('native_starts_added')!=0:
   raise ValueError('CREATIVE_CONTROLLER_PRE_NATIVE_STOP_REQUIRED')
  return directory
 def operation_query(self,operation_id):
  state=self._read();job=state['jobs'].get(operation_id)
  if not job:raise ValueError('CREATIVE_OPERATION_NOT_FOUND')
  directory=self._execution_directory(job);end=time.monotonic()+20
  while not (directory/'result.json').exists() and not (directory/'error.json').exists() and time.monotonic()<end:time.sleep(.25)
  with execution_lock(self.state_root,'creative-session'):
   state=self._read();job=state['jobs'][operation_id]
   if (directory/'error.json').exists() and not (directory/'result.json').exists():
    job['state']='FAILED';self._write(state)
    return {'operation_id':operation_id,'state':'FAILED','error':json.loads((directory/'error.json').read_text()),'instruction':'Controller repair required; do not create another job.'}
   if not (directory/'result.json').exists():return {'operation_id':operation_id,'state':'RUNNING','next_poll_seconds':10}
   result=json.loads((directory/'result.json').read_text())
   if operation_id in state['completed'] and file_record(directory/'result.json')!=job['result']:raise ValueError('CREATIVE_COMPLETION_CHANGED')
   repair_validated=False
   if (directory/'error.json').exists():
    try:
     from .creative_results import validate_postprocess_repair,validate_nuke_prelaunch_recovery,validate_render_tail_result,validate_nuke_retry_result
     is_retry=result.get('nuke_retry_recovery') is not None
     is_render_tail=result.get('render_terminal_recovery') is not None
     is_nuke_recovery=result.get('nuke_prelaunch_recovery') is not None
     validate_repair=validate_nuke_retry_result if is_retry else validate_render_tail_result if is_render_tail else validate_nuke_prelaunch_recovery if is_nuke_recovery else validate_postprocess_repair
     validation_preparation=self.preparation
     if operation_id in state['completed']:
      validation_preparation=result['nuke_retry_recovery']['preparation'] if is_retry else result['render_terminal_recovery']['preparation'] if is_render_tail else result['nuke_prelaunch_recovery']['recovery_preparation'] if is_nuke_recovery else result['postprocess_repair']['finalize_preparation']
      historical=json.loads(checked_bytes(validation_preparation))
      from .creative_results import historical_rect_preparation_compatible
      if not historical_rect_preparation_compatible(historical,self.prep):raise ValueError('CREATIVE_HISTORICAL_PREPARATION_MISMATCH')
     validate_repair(directory,result,validation_preparation)
     if operation_id not in state['completed']:self._validate_completion(directory,result,_tail_validated=is_render_tail,_retry_validated=is_retry)
     repair_validated=True
    except (ValueError,KeyError,TypeError,OSError):
     job['state']='FAILED';self._write(state)
     return {'operation_id':operation_id,'state':'FAILED','error':json.loads((directory/'error.json').read_text()),'instruction':'Controller postprocess repair is not authenticated; do not create another job.'}
   if (result.get('schema')!='bridge.hy3-creative-revision/1' or result.get('state')!='COMPLETE'
       or result.get('task_id')!=self.prep['task_id'] or result.get('operation_id')!=operation_id
       or result.get('model_route')!=self.prep.get('model_route') or result.get('plan')!=state['plans'][job['plan_id']] or result.get('exposure')!=state['plans'][job['plan_id']]['exposure']):
    raise ValueError('CREATIVE_NATIVE_RESULT_BINDING_REQUIRED')
   if operation_id not in state['completed']:
    if not repair_validated:self._validate_completion(directory,result)
    if result['revision']!=len(state['completed'])+1:raise ValueError('CREATIVE_COMPLETION_ORDER_INVALID')
    asset='preview_'+str(result['revision']);record=result['preview']['preview'];checked_bytes(record)
    state['assets'][asset]={'asset_id':asset,'file':record,'sha256':record['sha256'],'kind':'image','mime_type':'image/png','role':'actual_render_preview','revision':result['revision']}
    state['current_asset']=asset;state['current_exposure']=result['exposure'];state['completed'].append(operation_id)
    job['state']='COMPLETE';job['result']=file_record(directory/'result.json');self._write(state)
    self._event('creative_job_complete',{'operation_id':operation_id,'result':job['result'],'asset_id':asset,'exposure':result['exposure'],'artifact':result['artifact']['artifact_id'],'version':result['artifact']['version']})
   return {'operation_id':operation_id,'state':'COMPLETE','preview_id':'preview_'+str(result['revision']),'exposure':result['exposure'],'artifact_id':result['artifact']['artifact_id'],'artifact_version':result['artifact']['version'],'revision':result['revision'],'next_step':'Inspect new preview media and submit your own observation; feedback revision needs another effective change.' if result['revision']==1 else 'Inspect final preview and report the result. Backend provider identity remains unknown.'}
 def _validate_completion(self,directory,result,*,_tail_validated=False,_retry_validated=False,_historical=None):
  # 前端不以可写JSON的COMPLETE字样接收：重验正式主产物来源及真实文件身份。
  from dcc_task_runtime.native_scope import NativeScope
  from .creative_results import completed_registry,validate_nuke_completion
  if result.get('nuke_retry_recovery') is not None:
   if not _retry_validated:
    from .creative_results import validate_nuke_retry_result
    validate_nuke_retry_result(directory,result,self.preparation)
  elif result.get('render_terminal_recovery') is not None:
   if not _tail_validated:
    from .creative_results import validate_render_tail_result
    validate_render_tail_result(directory,result,self.preparation)
  elif result.get('saved_checkpoint_recovery') is not None:
   from .creative_results import validate_saved_checkpoint_result
   validate_saved_checkpoint_result(directory,result,self.preparation)
  control=directory/'project/control'
  if Path(result.get('control',''))!=control or result['revision'] not in (1,2):raise ValueError('CREATIVE_NATIVE_CONTROL_REQUIRED')
  source=json.loads((control/'creative-input-source.json').read_text())
  scope=NativeScope(self.prep['scope'])
  if self.prep.get('case_variant') is not None:
   if any(result.get(k)!=self.prep[k] or source.get(k)!=self.prep[k] for k in ('case_id','case_variant')):raise ValueError('CREATIVE_CASE_BINDING_REQUIRED')
   from houdini_bridge.official_case_variant import variant_payload
   variant_payload(json.loads(checked_bytes(self.prep['configuration'])))
  historical=None
  state=self._read();completed=state['completed'];operation=result['operation_id']
  if _historical is not False and operation in completed and completed[-1]!=operation:
   own=state['jobs'][operation]
   if own.get('state')!='COMPLETE' or own.get('result')!=file_record(directory/'result.json'):
    raise ValueError('CREATIVE_HISTORICAL_RESULT_REQUIRED')
   latest=state['jobs'][completed[-1]];later_directory=self._execution_directory(latest)
   if latest.get('state')!='COMPLETE' or latest.get('result')!=file_record(later_directory/'result.json'):
    raise ValueError('CREATIVE_HISTORICAL_SUCCESSOR_REQUIRED')
   later=json.loads(checked_bytes(latest['result']))
   if (later.get('schema')!='bridge.hy3-creative-revision/1' or later.get('operation_id')!=completed[-1]
       or later.get('task_id')!=result['task_id'] or later.get('model_route')!=self.prep.get('model_route')
       or later.get('plan')!=state['plans'][latest['plan_id']] or later.get('state')!='COMPLETE'
       or later.get('exposure')!=state['plans'][latest['plan_id']]['exposure']
       or later.get('revision')<=result['revision']):raise ValueError('CREATIVE_HISTORICAL_SUCCESSOR_REQUIRED')
   historical=self._validate_completion(later_directory,later,_historical=False)
   historical=dict(historical,completed_result=own['result'])
  registry=completed_registry(source,scope,self.prep['task_id'],historical=historical)
  if historical is None:
   receipt=registry.verify_operation_receipt(result['artifact']['registry_operation_receipt'])
  else:
   from dcc_task_runtime.historical_artifacts import verify_historical_operation_receipt
   observation=verify_historical_operation_receipt(registry,result['artifact']['registry_operation_receipt'],superseding=historical)
   receipt=observation.pop('receipt')
  if receipt['version']!=self.prep.get('baseline_main_version',2)+result['revision'] or receipt['task_id']!=self.prep['task_id'] or receipt['artifact_id']!=self.prep.get('main_artifact_id','disklight_incremental_main'):raise ValueError('CREATIVE_NATIVE_ARTIFACT_VERSION_REQUIRED')
  validate_nuke_completion(registry,result,scope,historical=historical)
  for record in result['files'].values():checked_bytes(record)
  if any(t.get('stopped_at') is None for t in scope.snapshot()['tickets']):raise ValueError('CREATIVE_NATIVE_STOPS_REQUIRED')
  return {'registry':registry,'receipt':receipt,'feedback':result['feedback'],'control':control,
      'observation':observation if historical is not None else {}}
 def delivery(self):
  state=self._read()
  return {'state':'COMPLETE' if len(state['completed'])==2 else 'INCOMPLETE','task_id':self.prep['task_id'],'completed_operations':state['completed'],'current_exposure':state['current_exposure'],'final_preview_id':state['current_asset'],'model_route':self.prep.get('model_route'),'provider_identity':'unknown','human_visual_acceptance':'PENDING'}

class CreativeMCP(DiagnosticMCP):
 """复用现有stdio协议，仅公布有限创作工具，不暴露通用宿主或Shell。"""
 def __init__(self,facade):
  super().__init__(facade);self.tools=TOOLS;self.server_name='bridge-hy3-creative';self.connection_id=uuid.uuid4().hex;self.rpc_id=None
  self.instructions='Actual bounded creative workflow. Use only registered images. Observe reference and current image, submit your own plan, create once then poll the same operation ID. After revision1 view its actual preview before feedback. Never use terminal/files/other agents to implement artwork. Provider identity is unknown.'
 def dispatch(self,request):
  # 每个stdio连接和JSONRPC调用可关联；客户端自报信息不作为模型身份认证。
  self.rpc_id=request.get('id') if isinstance(request,dict) and type(request.get('id')) in (int,str) else None
  response=super().dispatch(request)
  if isinstance(request,dict) and request.get('method')=='initialize' and isinstance(response,dict) and 'result' in response:
   client=request.get('params',{}).get('clientInfo',{})
   declared={key:str(client[key])[:100] for key in ('name','version') if key in client}
   self.facade.record_event('external_connection',{'connection_id':self.connection_id,'rpc_id':self.rpc_id,'declared_client':declared,'identity_authenticated':False})
  return response
 def _call(self,params):
  name=params.get('name');args=params.get('arguments',{});tool=next((t for t in self.tools if t['name']==name),None)
  if set(params)-{'name','arguments','_meta'} or tool is None or _schema_error(args,tool['inputSchema']):return {'isError':True,'content':[_text_content({'code':'INVALID_CREATIVE_TOOL_ARGUMENTS'})]}
  self.facade.record_event('external_tool_requested',{'connection_id':self.connection_id,'rpc_id':self.rpc_id,'tool':name,'arguments':args})
  try:
   value=getattr(self.facade,name)(**args)
   self.facade.record_event('external_tool_completed',{'connection_id':self.connection_id,'rpc_id':self.rpc_id,'tool':name,'result_sha256':canonical_sha256(value)})
   return {'isError':False,'content':[value if name=='media' else _text_content(value)]}
  except (ValueError,KeyError,TypeError) as exc:
   self.facade.record_event('external_tool_rejected',{'connection_id':self.connection_id,'rpc_id':self.rpc_id,'tool':name,'code':str(exc).split(':')[0]})
   return {'isError':True,'content':[_text_content({'code':str(exc).split(':')[0],'instruction':'Use documented schemas and registered IDs; do not invent missing facts or rerun an unknown operation.'})]}
