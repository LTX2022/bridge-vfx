"""从已接收几何工程准备独立任务；创建和原生执行使用分开的操作者许可。"""
from __future__ import annotations
import copy,hashlib,hmac,json,os,secrets,stat,time
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write,ensure_private_directory
from houdini_bridge.official_karma_observation import checked_bytes,file_record

PROFILE='geometry_from_existing_v1'
KIND='geometry_task'
VERSION='0.4.23'
MAX_TASKS=60
MAX_DISPATCHES=2
ROOT=Path(__file__).resolve().parents[4]

def _fail(code):raise ValueError('TASK_CREATION_'+code)
def _plain(value):
 p=Path(value).absolute()
 if p!=p.resolve() or any(x.is_symlink() for x in (p,*p.parents)):_fail('PATH_INVALID')
 return p

def _object(path):
 def unique(pairs):
  value={}
  for k,v in pairs:
   if k in value:_fail('DUPLICATE_KEY')
   value[k]=v
  return value
 value=json.loads(_plain(path).read_text(encoding='utf-8'),object_pairs_hook=unique)
 if type(value) is not dict:_fail('OBJECT_REQUIRED')
 return value

def _write(path,value):
 ensure_private_directory(path.parent)
 atomic_write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode(),owned_root=path.parent)
 return file_record(path)

def _runtime():
 """信任当前正式安装的完整索引，不把开发检出或未来版本当作发行包。"""
 if ROOT.name!='runtime':_fail('INSTALLED_RUNTIME_REQUIRED')
 if __spec__ is None or not __spec__.origin or Path(__spec__.origin).resolve()!=Path(__file__).resolve() or Path(create.__code__.co_filename).resolve()!=Path(__file__).resolve():_fail('RUNTIME_ORIGIN_CHANGED')
 package=ROOT.parent;plugin=_object(package/'plugin.json');manifest=_object(package/'runtime-manifest.json')
 if plugin.get('name')!='bridge-vfx' or plugin.get('version')!=VERSION:_fail('RUNTIME_VERSION_REQUIRED')
 if canonical_sha256(manifest.get('files'))!=manifest.get('file_manifest_sha256'):_fail('RUNTIME_MANIFEST_INVALID')
 own=file_record(Path(__file__));relative='runtime/packages/vfx-pipeline/src/vfx_pipeline/task_creation.py'
 if own['path']!=str(package/relative) or {'path':relative,'bytes':own['bytes'],'sha256':own['sha256']} not in manifest['files']:_fail('RUNTIME_SOURCE_CHANGED')
 return file_record(package/'runtime-manifest.json')

def _policy_path(registry):return _plain(registry).parent/('task-creation-policy-'+VERSION+'.json')
def _key(registry,*,create=False):
 p=_plain(registry).parent/'.task-creation-control/key'
 if create and not p.exists():
  ensure_private_directory(p.parent);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32));f.flush();os.fsync(f.fileno())
 st=_plain(p).stat()
 if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_uid!=os.getuid():_fail('PRIVATE_OPERATOR_KEY_REQUIRED')
 key=p.read_bytes()
 if len(key)!=32:_fail('OPERATOR_KEY_INVALID')
 return key

def _signed(registry,payload):
 return {'payload':payload,'signature':hmac.new(_key(registry),b'bridge.task-creation/1\0'+json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),hashlib.sha256).hexdigest()}
def _verified(registry,path):
 value=_object(path)
 if set(value)!={'payload','signature'} or not hmac.compare_digest(str(value['signature']),_signed(registry,value['payload'])['signature']):_fail('OPERATOR_SIGNATURE_INVALID')
 return value['payload']

def configure(registry,source_project_ids,instruction,*,template_record=None):
 """非MCP操作者配置只开放创建；不签发任何任务的原生执行许可。"""
 from .project_entry import read_projects
 if type(instruction) is not str or len(instruction.strip())<20:_fail('OPERATOR_INSTRUCTION_REQUIRED')
 registry=_plain(registry);runtime=_runtime();projects=read_projects(registry)['projects']
 ids=sorted(set(source_project_ids))
 if not ids or any(i not in projects or projects[i]['kind']!='geometry' for i in ids):_fail('SUPPORTED_SOURCE_REQUIRED')
 from .geometry_task_templates import load
 load(template_record)
 _key(registry,create=True)
 payload={'schema':'bridge.task-creation-policy/1','registry':str(registry),'runtime':runtime,
  'profile':PROFILE,'sources':{i:copy.deepcopy(projects[i]['preparation']) for i in ids},
  'task_root':str(registry.parent/'created-tasks'),'max_tasks':MAX_TASKS,'instruction':instruction,
  'native_execution_authorized_by_creation':False}
 if template_record is not None:payload['template']=copy.deepcopy(template_record)
 path=_policy_path(registry)
 if path.exists():
  if _verified(registry,path)!=payload:_fail('POLICY_CONFLICT')
 else:_write(path,_signed(registry,payload))
 return {'state':'CREATION_ENABLED','sources':ids,'profile':PROFILE,'native_execution_authorized':False}

def _policy(registry):
 registry=_plain(registry);path=_policy_path(registry);p=_verified(registry,path)
 if (p.get('schema')!='bridge.task-creation-policy/1' or p.get('registry')!=str(registry)
     or p.get('runtime')!=_runtime() or p.get('profile')!=PROFILE or p.get('max_tasks')!=MAX_TASKS
     or p.get('task_root')!=str(registry.parent/'created-tasks') or p.get('native_execution_authorized_by_creation') is not False):_fail('POLICY_INVALID')
 from .geometry_task_templates import load
 load(p.get('template'))
 return p

def _index(registry):
 path=_plain(registry).parent/'task-creation-requests.json'
 return path,(_object(path) if path.exists() else {'schema':'bridge.task-creation-requests/1','requests':{}})

def _receipt(registry,preparation):
 """新类型始终核来源回执；可省略marker不能让通用登记将其降成旧geometry。"""
 p=_plain(preparation['path']);origin=p.parent/'creation-origin.json';receipt=p.parent/'creation-receipt.json'
 data=_verified(registry,receipt);prep=json.loads(checked_bytes(preparation))
 # 历史创建按原签名策略和原安装manifest验签；升级不重签旧任务或绑定新worker。
 runtime=data.get('runtime');manifest=json.loads(checked_bytes(runtime));package=_plain(runtime['path']).parent
 version=_object(package/'plugin.json').get('version')
 if version not in ('0.4.13','0.4.14','0.4.15','0.4.16','0.4.17','0.4.18','0.4.19','0.4.20','0.4.21','0.4.22',VERSION) or canonical_sha256(manifest.get('files'))!=manifest.get('file_manifest_sha256'):_fail('HISTORICAL_RUNTIME_INVALID')
 policy=_verified(registry,_plain(registry).parent/('task-creation-policy-'+version+'.json'))
 if (policy.get('schema')!='bridge.task-creation-policy/1' or policy.get('registry')!=str(_plain(registry))
     or policy.get('runtime')!=runtime or policy.get('profile')!=PROFILE
     or policy.get('native_execution_authorized_by_creation') is not False):_fail('HISTORICAL_POLICY_INVALID')
 if (data.get('schema')!='bridge.created-task/1' or data.get('preparation')!=preparation
     or data.get('origin')!=file_record(origin) or prep.get('task_creation')!=data['origin']
     or data.get('task_id')!=prep.get('task_id') or data.get('profile')!=PROFILE
     or data.get('runtime')!=policy['runtime'] or p.parent.parent!=Path(policy['task_root'])
     or data.get('execution_plugin_source')!=prep.get('execution_plugin_source')
     or data.get('root')!=str(p.parent) or prep.get('worker')!=str(package/'runtime/tools/run_geometry_creative.py')):_fail('CREATED_TASK_BINDING_INVALID')
 if data.get('template')!=policy.get('template') or prep.get('task_template')!=policy.get('template'):_fail('TASK_TEMPLATE_BINDING_INVALID')
 return data

def registration_kind(registry,preparation):
 """固定创建目录或来源标记均要求新kind；不修改旧geometry准备合同。"""
 p=_plain(preparation['path']);prep=json.loads(checked_bytes(preparation))
 owned=p.is_relative_to(_plain(registry).parent/'created-tasks')
 if owned or prep.get('task_creation') is not None or (p.parent/'creation-origin.json').exists():
  _receipt(registry,preparation);return KIND
 return 'geometry'

def validate_created(registry,item):
 if item.get('kind')!=KIND:_fail('NEW_KIND_REQUIRED')
 return _receipt(registry,item['preparation'])

def _source_row(source_item,operation):
 """在创建INTENT前拒绝不存在或未接收版本；完整事实随后仍由原查询核心验证。"""
 prep=json.loads(checked_bytes(source_item['preparation']));root=Path(source_item['preparation']['path']).parent
 state=_object(root/'geometry-state.json');entry=state.get('jobs',{}).get(operation)
 if (state.get('preparation')!=source_item['preparation'] or state.get('task_id')!=prep.get('task_id')
     or not entry or entry.get('state')!='COMPLETE' or operation not in state.get('completed',[])
     or not entry.get('result') or not entry.get('acceptance')):_fail('ACCEPTED_SOURCE_REQUIRED')
 checked_bytes(entry['result']);checked_bytes(entry['acceptance']);return entry

def _source_alpha(result):
 """从已接收结果绑定的实际producer读取校准/插件，不依赖已淘汰安装cache。"""
 from houdini_bridge.alpha_reuse import validate_plugin_reuse
 source=json.loads(checked_bytes(result['source_record']));control=_plain(result['control'])
 if source.get('producer_control')!=str(control):_fail('SOURCE_PRODUCER_CONTROL_CHANGED')
 manifest=json.loads(checked_bytes(source['producer_manifest']))
 snapshot=json.loads(checked_bytes(source['producer_snapshot_manifest']))
 alpha=copy.deepcopy(manifest['production_host']['alpha_calibration']);plugin=alpha['plugin_reuse']['active_plugin']
 actual=file_record(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
 if (plugin!=actual or len([x for x in snapshot['files'] if x.get('path')=='plugins/houdini/_impl/houdini_bridge_addon.py' and x.get('sha256')==actual['sha256']])!=1):_fail('SOURCE_EXECUTION_PLUGIN_CHANGED')
 validate_plugin_reuse(alpha['plugin_reuse'],actual['sha256']);return alpha

def _prepare(registry,policy,source_id,source_item,operation,goal,request_id,root,project_id):
 from .geometry_task_templates import load as load_template, bind as bind_template
 template=load_template(policy.get('template'))
 """真实新建任务数据库、空会计和宿主根；大文件及校准只引用原件。"""
 from .geometry_session import GeometrySession
 from .service import ModelSafePipeline
 from dcc_task_runtime.native_scope import NativeScope,GEOMETRY_BUDGET,GEOMETRY_ROLE_SECONDS,GEOMETRY_SCOPE_SCHEMA,GEOMETRY_RESOURCE_PROFILE,GEOMETRY_SCENE_PROFILE
 from dcc_task_runtime.artifact_registry import ArtifactRegistry
 from houdini_bridge.alpha_reuse import validate_plugin_reuse
 from . import geometry_graph
 source=GeometrySession(source_item['preparation'])
 try:
  state=source._read();entry=state['jobs'].get(operation)
  if (not entry or entry.get('state')!='COMPLETE' or operation not in state['completed']
      or not entry.get('result') or not entry.get('acceptance')):_fail('ACCEPTED_SOURCE_REQUIRED')
  checked_bytes(entry['result']);checked_bytes(entry['acceptance'])
  view=source.query(operation)
  if view.get('state')!='COMPLETE' or view.get('result_view')!='accepted_immutable':_fail('ACCEPTED_SOURCE_REQUIRED')
  state=source._read();entry=state['jobs'].get(operation)
  if not entry or entry.get('result')!=view.get('original_result'):_fail('SOURCE_RESULT_CHANGED')
  original=json.loads(checked_bytes(entry['result']));parent=source.prep
  model=geometry_graph.model_proposal(original['plan']['model_graph']).to_dict()
  oldscope=json.loads(checked_bytes(file_record(Path(parent['scope']['path']))))
  ensure_private_directory(root)
  origin={'schema':'bridge.task-creation-origin/1','source_project_id':source_id,'source_operation_id':operation,
   'source_preparation':source_item['preparation'],'source_result':entry['result'],'goal':goal,'request_id':request_id,'profile':PROFILE,'registry':str(registry)}
  if template is not None:origin['template']=copy.deepcopy(policy['template'])
  origin_record=_write(root/'creation-origin.json',origin)
  media={}
  for name,record in (template['media'] if template is not None else parent['media']).items():
   raw=checked_bytes(record)
   if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw)>2*1024*1024:_fail('REFERENCE_PNG_REQUIRED')
   path=root/'media'/(name+'.png');ensure_private_directory(path.parent);path.write_bytes(raw);media[name]=file_record(path)
  for name,key in (('source_preview','preview'),):
   record=original['files'][key];path=root/'media'/(name+'.png');path.write_bytes(checked_bytes(record));media[name]=file_record(path)
  brief=(template['public_brief'] if template is not None else parent['public_brief'])+'\n本独立任务目标：'+goal+'\n源模型只作基线，新的提案仍由当前agent提交。'
  feedback=template['feedback'] if template is not None else parent['feedback']
  ensure_private_directory(root/'task')
  pipeline=ModelSafePipeline(root/'task/pipeline.sqlite3')
  spec={'schema_version':'2.0','task_type':'visual.reference_rebuild','intent':brief,
   'target':{'application':'pipeline','scene_mode':'current'},
   'references':[{'asset_id':k,'kind':'image','uri':v['path'],'sha256':v['sha256']} for k,v in media.items()],
   'domains':[{'identifier':'material_lookdev_v1','version':'1.0.0'}],'feedback':feedback,'render':{},'delivery':{'composite':False}}
  task_id=pipeline.reference_task_start(spec,idempotency_key='created:'+project_id,purpose='graph_construction')['task_id']
  config=_write(root/'geometry-configuration.json',json.loads(checked_bytes(parent['configuration'])))
  criteria=_write(root/'private-evaluation.json',json.loads(checked_bytes(template['criteria'] if template is not None else parent['criteria'])))
  oldreuse=json.loads(checked_bytes(parent['source_reuse']))
  source_scope_record=file_record(parent['scope']['path'])
  source_state=file_record(Path(parent['scope']['path']).parent/'native-scope-state.json')
  reuse=_write(root/'source-reuse.json',{'schema':'bridge.geometry-reuse-source/1','task_id':task_id,
   'source_preparation':source_item['preparation'],'source_result':entry['result'],'source_scope':source_scope_record,
   'source_hip':original['files']['hip'],'source_rig':oldreuse['source_rig'],'source_nk':original['files']['nk'],
   'source_accounting_state':source_state,'task_creation_origin':origin_record})
  key=secrets.token_bytes(32)
  # 原kernel要求的授权位仅表示准备结构兼容；新kind另有强制、默认关闭的执行grant。
  scope={'schema':GEOMETRY_SCOPE_SCHEMA,'resource_profile':GEOMETRY_RESOURCE_PROFILE,'scene_profile':GEOMETRY_SCENE_PROFILE,
   'scope_id':'geometry-'+secrets.token_hex(12),'task_id':task_id,'output_root':str(root),
   'budget':copy.deepcopy(GEOMETRY_BUDGET),'role_seconds':copy.deepcopy(GEOMETRY_ROLE_SECONDS),
   'versions':copy.deepcopy(oldscope['versions']),'hosts':copy.deepcopy(oldscope['hosts']),
   'project_color':copy.deepcopy(oldscope['project_color']),'native_color_tokens':copy.deepcopy(oldscope['native_color_tokens']),
   'evidence_source':'real_host','execution_authorized':True,'status':'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION',
   'authorization':{'authority':'current_user_instruction','instruction':policy['instruction']+'; preparation only; created-task execution requires separate operator grant'},
   'source_reuse':reuse,'accounting':{'key_path':str(root/'.native-control/key'),'key_sha256':hashlib.sha256(key).hexdigest()}}
  from .geometry_task_templates import collector_policy
  selected_collector=collector_policy(oldscope,template)
  if selected_collector is not None:scope['process_image_policy']=selected_collector
  scope_record=_write(root/'scope.json',scope);native=NativeScope.initialize({k:scope_record[k] for k in ('path','sha256')},key=key)
  if native._read()['tickets']:_fail('NEW_ACCOUNTING_NOT_EMPTY')
  task_binding=_write(root/'task-binding.json',{'schema':'bridge.geometry-task-binding/1','task_id':task_id,
   'task_database':str(root/'task/pipeline.sqlite3'),'spec_sha256':canonical_sha256(pipeline.store.get_task(task_id)['spec'])})
  # 从来源原始Creative配置重建宿主设置，避免复制旧controller/恢复阶段或已用槽身份。
  creative=json.loads(checked_bytes(oldreuse['source_preparation']));old_manifest=json.loads(checked_bytes(creative['runtime_manifest']))
  hosts={}
  for kind,field in (('houdini','production_host'),('nuke','production_nuke')):
   cfg=copy.deepcopy(old_manifest[field])
   for name in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir','input_artifact_source','snapshot'):cfg.pop(name,None)
   cfg.update(task_root=str(root),native_scope=native.binding,session_seconds=240 if kind=='houdini' else 120,
    resource_budget={'roots':[str(root)],'max_bytes':GEOMETRY_BUDGET['max_disk_bytes'],'native_scope':native.binding},feedback_ledger_root=str(root/'artifact_ledger'))
   if kind=='houdini':
    alpha=_source_alpha(original)
    cfg['alpha_calibration']=alpha
    cfg['task_creation_origin']=origin_record
    from dcc_task_runtime.render_profiles import output_policy
    cfg['output_acceptance']=output_policy(GEOMETRY_SCENE_PROFILE)
   hosts[kind]=cfg
  ArtifactRegistry(root/'artifact_ledger')
  environment=copy.deepcopy(parent['environment'])
  for name in ('TMPDIR','TMP','TEMP','HOUDINI_TEMP_DIR','NUKE_TEMP_DIR'):environment[name]=str(root/'runtime/tmp')
  for name,rel in (('HOUDINI_USER_PREF_DIR','runtime/houdini-prefs'),('XDG_CACHE_HOME','runtime/cache'),('XDG_CONFIG_HOME','runtime/config')):environment[name]=str(root/rel)
  ensure_private_directory(root/'runtime/tmp')
  prep={'schema':'bridge.geometry-creative-preparation/1','task_id':task_id,'scope':native.binding,'configuration':config,
   'source_reuse':reuse,'worker':str(ROOT/'tools/run_geometry_creative.py'),'supervisor_python':scope['hosts']['supervisor_python']['path'],
   'environment':environment,'media':media,'public_brief':brief,'feedback':feedback,'ledger_root':str(root/'artifact_ledger'),
   'hosts':hosts,'task_binding':task_binding,'criteria':criteria,'nuke_template':original['files']['nk'],
   'template_main_pattern':parent['template_main_pattern'],'template_nuke_pattern':parent['template_nuke_pattern'],
   'display':copy.deepcopy(parent['display']),'model_route':copy.deepcopy(parent['model_route']),
   'task_creation':origin_record,'source_model_graph':model,'execution_plugin_source':copy.deepcopy(hosts['houdini']['alpha_calibration']['plugin_reuse']['active_plugin'])}
  # 模板输出必须绑定这份选定NK；不同源版本不能沿用另一个NK的路径字面量。
  from .geometry_job import _nuke_template_patterns
  patterns=_nuke_template_patterns(original);prep.update(template_main_pattern=patterns['main'],template_nuke_pattern=patterns['nuke'])
  if template is not None:prep=bind_template(prep,template,policy['template'],root,policy['instruction'])
  preparation=_write(root/'geometry-preparation.json',prep)
  receipt={'schema':'bridge.created-task/1','project_id':project_id,'task_id':task_id,'profile':PROFILE,
   'request_id':request_id,'root':str(root),'source_project_id':source_id,'source_operation_id':operation,
   'source_preparation':source_item['preparation'],'source_result':entry['result'],'runtime':policy['runtime'],
   'preparation':preparation,'origin':origin_record,'execution_plugin_source':prep['execution_plugin_source'],'native_execution_authorized_by_creation':False}
  if template is not None:receipt['template']=copy.deepcopy(policy['template'])
  _write(root/'creation-receipt.json',_signed(registry,receipt));return receipt
 finally:source.close()

def _finish_published(registry,row,index,path,goal):
 """仅补已签名且已登记的同一发布事务；绝不重跑准备或再造scope。"""
 from .project_entry import read_projects
 if row['state']=='READY':return
 receipt=Path(row['root'])/'creation-receipt.json'
 if not receipt.is_file():return
 data=_verified(registry,receipt)
 item={'kind':KIND,'label':goal[:100],'preparation':data.get('preparation')}
 with execution_lock(_plain(registry).parent,'bridge-projects'):
  if (data.get('project_id')!=row['project_id'] or data.get('request_id')!=row['request_id']
      or read_projects(registry)['projects'].get(row['project_id'])!=item):return
  _receipt(registry,item['preparation']);row.update(state='READY',preparation=item['preparation']);_write(path,index)

def execution_status(registry,item):
 """只展示已核精确绑定的许可；创建不会使该值变为真。"""
 from dcc_task_runtime.native_scope import GEOMETRY_BUDGET
 data=validate_created(registry,item);path=Path(data['root'])/'execution-grant.json'
 if not path.exists():return False
 grant=_verified(registry,path)
 expected={'schema':'bridge.created-task-execution-grant/1','task_id':data['task_id'],'project_id':data['project_id'],
  'preparation':data['preparation'],'runtime':data['runtime'],'profile':PROFILE,'budget':GEOMETRY_BUDGET,'max_dispatches':MAX_DISPATCHES}
 if any(grant.get(k)!=v for k,v in expected.items()) or type(grant.get('instruction')) is not str or len(grant['instruction'].strip())<20:_fail('EXECUTION_GRANT_BINDING_INVALID')
 return data['runtime']==_runtime()

def _response(registry,row,*,idempotent=False):
 if row['state']!='READY':return {'state':'UNKNOWN','request_id':row['request_id'],'project_id':row['project_id'],'native_dispatch_attempted':False,'next_step':'Inspect original creation request; do not allocate another task.'}
 data=_receipt(registry,row['preparation'])
 return {'state':'PREPARED','request_id':row['request_id'],'task_id':data['task_id'],'project_id':data['project_id'],
  'profile':PROFILE,'source_project_id':data['source_project_id'],'source_operation_id':data['source_operation_id'],
  'native_execution_authorized':execution_status(registry,{'kind':KIND,'preparation':data['preparation']}),'native_dispatch_attempted':False,'idempotent':idempotent,
  'next_step':'Select the new project, inspect catalog/media and propose; native execution needs an independent operator grant.'}

def creation_status(registry,source_id,operation,goal,request_id):
 """只观察原创建事务的原子快照；不取创建锁、不完成登记、不重放创建。"""
 from .project_entry import _identifier,read_projects
 for value in (source_id,operation,request_id):_identifier(value)
 if type(goal) is not str or not 10<=len(goal)<=2000:_fail('GOAL_REQUIRED')
 registry=_plain(registry);_,index=_index(registry);row=index['requests'].get(request_id)
 if row is None:
  return {'state':'NOT_FOUND','request_id':request_id,'native_dispatch_attempted':False,
   'action':'OBSERVE_ONLY','next_step':'No recorded request. Check original identifiers; do not allocate a replacement automatically.'}
 digest=canonical_sha256({'source_project_id':source_id,'source_operation_id':operation,'goal':goal})
 if row.get('request_sha256')!=digest:_fail('REQUEST_CONFLICT')
 identity='created_'+hashlib.sha256((str(registry)+'\0'+request_id).encode()).hexdigest()[:24]
 if row.get('request_id')!=request_id or row.get('project_id')!=identity:_fail('CREATION_INDEX_INVALID')
 if row['state']!='READY':
  return {'state':'UNKNOWN','creation_state':row['state'] if row['state']=='INTENT' else 'UNKNOWN',
   'request_id':request_id,'project_id':identity,'native_dispatch_attempted':False,'action':'OBSERVE_ONLY',
   'next_step':'Observe the same original request. This query never retries creation or completes registration.'}
 item=read_projects(registry)['projects'].get(identity)
 if not item or item.get('kind')!=KIND or item.get('preparation')!=row.get('preparation'):_fail('CREATION_REGISTRATION_CHANGED')
 data=validate_created(registry,item)
 if data['project_id']!=identity:_fail('PROJECT_BINDING_INVALID')
 return {**_response(registry,row,idempotent=True),'creation_state':'READY','action':'ORIGINAL_CREATION_RETURNED'}


def create(registry,source_id,source_item,operation,goal,request_id):
 """单请求先持久化INTENT；未知不重放，登记发布与request完成在同一锁内。"""
 from .project_entry import _identifier,read_projects,register_project
 for value in (source_id,operation,request_id):_identifier(value)
 if type(goal) is not str or not 10<=len(goal)<=2000:_fail('GOAL_REQUIRED')
 registry=_plain(registry);policy=_policy(registry)
 body={'source_project_id':source_id,'source_operation_id':operation,'goal':goal};digest=canonical_sha256(body)
 with execution_lock(registry.parent,'bridge-task-creation'):
  path,index=_index(registry);old=index['requests'].get(request_id)
  if old:
   if old.get('request_sha256')!=digest:_fail('REQUEST_CONFLICT')
   _finish_published(registry,old,index,path,goal)
   return _response(registry,old,idempotent=True)
  if len(index['requests'])>=policy['max_tasks']:_fail('CREATION_LIMIT')
  if source_item.get('kind')!='geometry' or policy['sources'].get(source_id)!=source_item.get('preparation'):_fail('SOURCE_PROFILE_UNSUPPORTED')
  if read_projects(registry)['projects'].get(source_id)!=source_item:_fail('SOURCE_REGISTRATION_CHANGED')
  _source_row(source_item,operation)
  identity=hashlib.sha256((str(registry)+'\0'+request_id).encode()).hexdigest()[:24];project_id='created_'+identity
  parent=_plain(policy['task_root']);ensure_private_directory(parent);root=parent/identity
  if root.exists():_fail('UNTRACKED_ROOT_EXISTS')
  row={'state':'INTENT','request_id':request_id,'request_sha256':digest,'project_id':project_id,'root':str(root)}
  index['requests'][request_id]=row;_write(path,index)
  try:
   receipt=_prepare(registry,policy,source_id,source_item,operation,goal,request_id,root,project_id)
   # 同一物理登记锁内先核source与目标；register_project支持同线程重入。
   with execution_lock(registry.parent,'bridge-projects'):
    if read_projects(registry)['projects'].get(source_id)!=source_item:_fail('SOURCE_REGISTRATION_CHANGED')
    register_project(registry,project_id,goal[:100],preparation=Path(receipt['preparation']['path']))
    row.update(state='READY',preparation=receipt['preparation']);_write(path,index)
  except BaseException as error:
   row['last_error']=type(error).__name__+':'+str(error);_write(path,index);raise
  return _response(registry,row)

def authorize(registry,project_id,instruction):
 """仅操作者CLI可签独立执行许可；不重写Native账或重置已用额度。"""
 from .project_entry import read_projects
 from dcc_task_runtime.native_scope import GEOMETRY_BUDGET
 if type(instruction) is not str or len(instruction.strip())<20:_fail('EXECUTION_INSTRUCTION_REQUIRED')
 item=read_projects(registry)['projects'].get(project_id)
 if not item or item['kind']!=KIND:_fail('NEW_KIND_REQUIRED')
 data=validate_created(registry,item)
 if data['project_id']!=project_id:_fail('PROJECT_BINDING_INVALID')
 # 跨版本只读旧许可；不能为旧worker签当前runtime的执行权。
 if data['runtime']!=_runtime():_fail('CURRENT_TASK_RUNTIME_REQUIRED')
 payload={'schema':'bridge.created-task-execution-grant/1','task_id':data['task_id'],'project_id':project_id,
  'preparation':data['preparation'],'runtime':_runtime(),'profile':PROFILE,'budget':copy.deepcopy(GEOMETRY_BUDGET),
  'max_dispatches':MAX_DISPATCHES,'instruction':instruction}
 path=Path(data['root'])/'execution-grant.json'
 if path.exists():
  if _verified(registry,path)!=payload:_fail('EXECUTION_GRANT_CONFLICT')
 else:_write(path,_signed(registry,payload))
 return {'state':'EXECUTION_AUTHORIZED','task_id':data['task_id'],'budget':GEOMETRY_BUDGET,'max_dispatches':MAX_DISPATCHES}

def resolve_execution_plugin(native_binding,control,alpha,*,origin):
 """新任务执行快照采用原已校准插件原字节；只在独立签名许可下选择来源。"""
 scope_record=file_record(_plain(native_binding['path']))
 if {k:scope_record[k] for k in ('path','sha256')}!=native_binding:_fail('SCOPE_CHANGED')
 scope=json.loads(checked_bytes(scope_record));root=_plain(scope['output_root']);reuse=json.loads(checked_bytes(scope['source_reuse']))
 origin_record=reuse.get('task_creation_origin')
 if not origin_record or origin_record!=origin:_fail('EXECUTION_ORIGIN_REQUIRED')
 origin=json.loads(checked_bytes(origin_record));registry=_plain(origin['registry'])
 preparation=file_record(root/'geometry-preparation.json');data=_receipt(registry,preparation)
 if (data['origin']!=origin_record or data['task_id']!=scope['task_id']
     or json.loads(checked_bytes(preparation))['scope']!=native_binding):_fail('EXECUTION_ORIGIN_CHANGED')
 from .project_entry import read_projects
 item=read_projects(registry)['projects'].get(data['project_id'])
 if not item or item['kind']!=KIND or item['preparation']!=preparation:_fail('EXECUTION_REGISTRATION_CHANGED')
 if not execution_status(registry,item):_fail('EXECUTION_AUTHORIZATION_REQUIRED')
 control=_plain(control)
 if control.name!='control' or control.parent.name!='project' or control.parents[2]!=root/'jobs':_fail('EXECUTION_CONTROL_ROOT_INVALID')
 job=json.loads(checked_bytes(file_record(control.parents[1]/'job.json')))
 state=_object(root/'geometry-state.json');book=_object(root/'execution-requests.json')
 if (job.get('preparation')!=preparation or job.get('task_id')!=data['task_id']
     or job.get('operation_id')!=control.parents[1].name or state.get('preparation')!=preparation
     or sum(v.get('state')!='ALIAS' for v in book.get('requests',{}).values())>MAX_DISPATCHES):_fail('EXECUTION_JOB_BINDING_INVALID')
 requests=[key for key,value in state.get('execution_requests',{}).items() if value.get('operation_id')==job['operation_id']]
 if not any(book.get('requests',{}).get(key,{}).get('plan_id')==job['plan']['plan_id'] for key in requests):_fail('EXECUTION_JOB_AUTHORIZATION_REQUIRED')
 source_result=json.loads(checked_bytes(data['source_result']))
 expected=_source_alpha(source_result);plugin=copy.deepcopy(expected['plugin_reuse']['active_plugin'])
 if plugin!=data['execution_plugin_source']:_fail('EXECUTION_PLUGIN_SOURCE_CHANGED')
 from houdini_bridge.alpha_reuse import validate_plugin_reuse
 validate_plugin_reuse(expected['plugin_reuse'],plugin['sha256']);checked_bytes(plugin)
 # 原kernel只将active插件路径重定位到新snapshot，其余证明/终态字节必须完全一致。
 expected['plugin_reuse']['active_plugin']['path']=str(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
 if alpha!=expected:_fail('EXECUTION_ALPHA_BINDING_CHANGED')
 return copy.deepcopy(plugin)

def _unknown_dispatch(data,plan_id,result=None):
 """派发收尾失败仍交出已知原operation；只观察现有前端映射，不重放。"""
 answer={'state':'UNKNOWN','blocked':True,'native_dispatch_attempted':'unknown',
  'controller_dispatch_attempted':'unknown','next_step':'Inspect original operation/jobs; never redispatch automatically.'}
 if isinstance(result,dict):
  answer['dispatch_result']=copy.deepcopy(result)
  if result.get('operation_id'):answer['operation_id']=result['operation_id']
  if 'controller_dispatch_attempted' in result:answer['controller_dispatch_attempted']=result['controller_dispatch_attempted']
 if 'operation_id' not in answer:
  try:
   state=_object(Path(data['root'])/'geometry-state.json')
   if state.get('task_id')==data['task_id'] and state.get('preparation')==data['preparation']:
    matches=[j for j in state.get('jobs',{}).values() if j.get('plan_id')==plan_id]
    if len(matches)==1:answer['operation_id']=matches[0]['operation_id']
  except (OSError,ValueError,KeyError,TypeError):pass
 return answer

def execute(registry,project_id,item,plan_id,request_id,dispatch):
 """新kind所有派发在job/Popen前验许可；未知INTENT占次数，不因换ID刷新额度。"""
 from dcc_task_runtime.native_scope import GEOMETRY_BUDGET
 data=validate_created(registry,item)
 if data['project_id']!=project_id:_fail('PROJECT_BINDING_INVALID')
 if data['runtime']!=_runtime():_fail('CURRENT_TASK_RUNTIME_REQUIRED')
 root=Path(data['root']);path=root/'execution-grant.json'
 if not path.is_file():_fail('EXECUTION_AUTHORIZATION_REQUIRED')
 grant=_verified(registry,path)
 expected={'schema':'bridge.created-task-execution-grant/1','task_id':data['task_id'],'project_id':project_id,
  'preparation':data['preparation'],'runtime':_runtime(),'profile':PROFILE,'budget':GEOMETRY_BUDGET,'max_dispatches':MAX_DISPATCHES}
 if any(grant.get(k)!=v for k,v in expected.items()) or type(grant.get('instruction')) is not str or len(grant['instruction'].strip())<20:_fail('EXECUTION_GRANT_BINDING_INVALID')
 with execution_lock(root,'created-task-execution'):
  path=root/'execution-requests.json';book=_object(path) if path.exists() else {'requests':{}}
  old=book['requests'].get(request_id)
  if old:
   if old['plan_id']!=plan_id:_fail('EXECUTION_REQUEST_CONFLICT')
   if old['state']=='INTENT':return _unknown_dispatch(data,plan_id)
   return copy.deepcopy(old['result'])
  for prior in list(book['requests'].values()):
   if prior['plan_id']==plan_id:
    if prior['state']=='INTENT':return _unknown_dispatch(data,plan_id)
    if len(book['requests'])>=64:_fail('EXECUTION_REQUEST_LIMIT')
    book['requests'][request_id]={'state':'ALIAS','plan_id':plan_id,'result':prior['result']};_write(path,book)
    return {**copy.deepcopy(prior['result']),'idempotent':True}
  if sum(v['state']!='ALIAS' for v in book['requests'].values())>=MAX_DISPATCHES:_fail('EXECUTION_DISPATCH_LIMIT')
  # 明确的缺计划/陈旧计划在预留派发次数前拒绝；实际执行器仍重验完整合同。
  state=_object(root/'geometry-state.json');plan=state.get('plans',{}).get(plan_id)
  if not plan or plan.get('task_id')!=data['task_id'] or state.get('task_id')!=data['task_id'] or state.get('preparation')!=data['preparation']:_fail('ACCEPTED_PLAN_REQUIRED')
  if plan.get('base_revision')!=state.get('revision') or canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'})!=plan.get('plan_sha256'):_fail('PLAN_CHANGED')
  row={'state':'INTENT','plan_id':plan_id};book['requests'][request_id]=row;_write(path,book)
  result=None
  try:
   result=dispatch();row.update(state='DISPATCHED',result=result);_write(path,book);return result
  except Exception:
   # 调用执行器后不能用元数据收尾错误断言未派发；原INTENT占用次数且禁止重派。
   return _unknown_dispatch(data,plan_id,result)
