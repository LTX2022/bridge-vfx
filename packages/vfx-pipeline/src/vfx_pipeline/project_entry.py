"""插件工程入口：显式选择已登记工程，沿原执行核心接续任务，不派生执行权限。"""
from __future__ import annotations
import copy, hashlib, json, os, re, uuid, sqlite3, sys
from contextlib import ExitStack, closing
from pathlib import Path
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory
from houdini_bridge.official_karma_observation import checked_bytes, file_record
from .workbuddy_mcp import DiagnosticMCP, _schema, _text_content
from .workbuddy_graph_mcp import _schema_error
from . import geometry_graph
from dcc_task_runtime.graph_compiler import GraphCompileError

ID = {'type':'string','minLength':1,'maxLength':100,'pattern':r'^[A-Za-z0-9][A-Za-z0-9_.-]*$'}
CONNECTION_ID = {'type':'string','minLength':43,'maxLength':43,'pattern':r'^connection-[0-9a-f]{32}$'}
ENTRY_TOOLS = [
 {'name':'bridge_health','description':'读取插件安装入口状态；READY仅表示入口可用，DCC连接未检查，不启动或探测DCC。','inputSchema':_schema()},
 {'name':'bridge_connect','description':'按稳定request_id创建一次独立Houdini/Nuke后台连接；仅双宿主真实健康检查通过才返回CONNECTED。连接最长120秒，同request重试不续期、不重启，不渲染。','inputSchema':_schema({'request_id':ID},('request_id',))},
 {'name':'bridge_connection_status','description':'按connection_id重验原后台连接和期限，不启动、重启或续期宿主。','inputSchema':_schema({'connection_id':CONNECTION_ID},('connection_id',))},
 {'name':'bridge_disconnect','description':'停止本连接自有后台宿主；不触碰原GUI、工程或其他连接。','inputSchema':_schema({'connection_id':CONNECTION_ID},('connection_id',))},
 {'name':'bridge_projects','description':'列出操作者已明确登记的工程；不扫描磁盘或猜测HIP。','inputSchema':_schema()},
 {'name':'bridge_select_project','description':'为当前连接明确选择project_id；返回实际工程与工具。不会打开或重建DCC场景。','inputSchema':_schema({'project_id':ID},('project_id',))},
 {'name':'bridge_current_project','description':'读取当前连接选中的工程；其他连接的选择不影响本连接。','inputSchema':_schema()},
 {'name':'bridge_tasks','description':'列出当前工程已存在的原任务ID及状态。目录状态不代替正式完成验收。','inputSchema':_schema({'project_id':ID},('project_id',))},
 {'name':'bridge_continue_task','description':'按原operation_id继续查询。完成时取回原正式产物，运行中观察原任务；失败/未知返回阻断，不重放或创建DCC任务。','inputSchema':_schema({'project_id':ID,'operation_id':ID},('project_id','operation_id'))},
]
ENTRY_TOOLS += [
 {'name':'bridge_create_task','description':'从当前明确选中的已完成几何工程和原operation创建独立新任务；同request同参数返回同任务，创建不启动DCC、不授予原生执行权限。首个模板为geometry_from_existing_v1。','inputSchema':_schema({'request_id':ID,'source_project_id':ID,'source_operation_id':ID,'goal':{'type':'string','minLength':10,'maxLength':2000}},('request_id','source_project_id','source_operation_id','goal'))},
]
ENTRY_TOOLS += [
 {'name':'bridge_creation_status','description':'只读查询原创建请求。原request_id及来源/operation/goal必须完全相同；已登记则返回原任务，进行中或未知只观察，不创建、不补登记、不启动DCC。','inputSchema':_schema({'request_id':ID,'source_project_id':ID,'source_operation_id':ID,'goal':{'type':'string','minLength':10,'maxLength':2000}},('request_id','source_project_id','source_operation_id','goal'))},
]
# 新创作能力固定注册；旧工程仍只有其原观察权限，选择不会激活宿主。
ENTRY_TOOLS += [
 {'name':'bridge_catalog','description':'读取几何或RectLight的有限目录，或已完成交付的只读能力；不启动DCC。','inputSchema':_schema({'project_id':ID},('project_id',))},
 {'name':'bridge_media','description':'取得当前几何或RectLight软箱工程的真实登记PNG图像块；先看图再提交观察。','inputSchema':_schema({'project_id':ID,'asset_id':ID},('project_id','asset_id'))},
 {'name':'bridge_observe','description':'提交自己对已实际发送图片的观察，绑定图片摘要。','inputSchema':_schema({'project_id':ID,'asset_id':ID,'request_id':ID,'observation':{'type':'string','minLength':10,'maxLength':4000}},('project_id','asset_id','request_id','observation'))},
 {'name':'bridge_propose','description':'纯验证有限方案。先按catalog.observation_requirements看完必看图并提交观察；首版用model_graph，反馈用edits [{node_id, parms}]。goal/rationale/observation_ids均必填；不会启动DCC。Rect软箱仍只用rectlight_shape宽高。','inputSchema':_schema({'project_id':ID,'request_id':ID,'base_revision':{'type':'integer','minimum':0,'maximum':98},'goal':{'type':'string','minLength':10,'maxLength':2000},'rationale':{'type':'string','minLength':20,'maxLength':4000},'observation_ids':{'type':'array','minItems':2,'maxItems':8,'uniqueItems':True,'items':ID},'rectlight_shape':_schema({'width':{'type':'number','minimum':.9,'maximum':1.8},'height':{'type':'number','minimum':.45,'maximum':.9}},('width','height')),'model_graph':geometry_graph.model_graph_schema(),'edits':{'type':'array','minItems':1,'maxItems':8,'items':_schema({'node_id':ID,'parms':{'type':'object','minProperties':1,'maxProperties':6,'additionalProperties':{'type':'number'}}},('node_id','parms'))}},('project_id','request_id','base_revision','goal','rationale','observation_ids'))},
 {'name':'bridge_execute','description':'将已接受的几何计划执行一次，异步返回持久operation_id；随后只查询同ID。','inputSchema':_schema({'project_id':ID,'plan_id':ID,'request_id':ID},('project_id','plan_id','request_id'))},
 {'name':'bridge_cancel_task','description':'请求取消当前工程原作业；可信停止前不宣称取消完成。','inputSchema':_schema({'project_id':ID,'operation_id':ID},('project_id','operation_id'))},
]
for t in ENTRY_TOOLS:
 t['annotations']={'readOnlyHint':t['name'] not in ('bridge_create_task','bridge_connect','bridge_disconnect','bridge_select_project','bridge_continue_task','bridge_media','bridge_observe','bridge_propose','bridge_execute','bridge_cancel_task'),'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}

def state_root():
 """安装包外的用户私有状态；可由操作者显式选择独立状态目录。"""
 raw=os.environ.get('BRIDGE_STATE_DIR')
 return Path(raw).absolute() if raw else Path.home()/'.local/share/bridge-vfx'

def default_projects_path():
 """新版登记独立于旧读取器文件，保留已加载旧插件的工程列表兼容。"""
 return state_root()/'projects-v3.json'

def _plain(path):
 path=Path(path).absolute()
 if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('BRIDGE_ENTRY_PATH_LINK')
 return path

def _object(path):
 def unique(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('BRIDGE_ENTRY_DUPLICATE_KEY')
   d[k]=v
  return d
 v=json.loads(_plain(path).read_text(encoding='utf-8'),object_pairs_hook=unique)
 if not isinstance(v,dict):raise ValueError('BRIDGE_ENTRY_OBJECT_REQUIRED')
 return v

def _identifier(value):
 if not isinstance(value,str) or not re.fullmatch(ID['pattern'],value) or len(value)>100:raise ValueError('BRIDGE_ENTRY_ID_REQUIRED')
 return value

def read_projects(path):
 """只读取受控登记，空配置仍能完成MCP握手和列目录。"""
 path=_plain(path)
 if not path.exists():return {'schema':'bridge.plugin-projects/1','projects':{}}
 if path.stat().st_size>1024*1024:raise ValueError('BRIDGE_PROJECTS_SIZE_LIMIT')
 v=_object(path)
 if set(v)!={'schema','projects'} or v['schema']!='bridge.plugin-projects/1' or not isinstance(v['projects'],dict) or len(v['projects'])>64:raise ValueError('BRIDGE_PROJECTS_INVALID')
 for key,item in v['projects'].items():
  _identifier(key)
  if not isinstance(item,dict) or not isinstance(item.get('label'),str) or not 1<=len(item['label'])<=120:raise ValueError('BRIDGE_PROJECT_INVALID')
  expected={'label','kind','preparation'} if item.get('kind') in ('creative','geometry','rectlight_shape','geometry_task','geometry_delivery') else {'label','kind','prepared_run','scheduler_root','backend'}
  if set(item)!=expected or item.get('kind') not in ('creative','geometry','rectlight_shape','geometry_task','geometry_delivery','graph'):raise ValueError('BRIDGE_PROJECT_INVALID')
 return v

def validate_project(item,*,registry=None):
 """准备文件身份变化必须重新由操作者登记，不使用用户目录中的任意脚本。"""
 record=item['preparation'] if item['kind'] in ('creative','geometry','rectlight_shape','geometry_task','geometry_delivery') else item['prepared_run']
 p=json.loads(checked_bytes(record))
 if item['kind']=='geometry_delivery':
  from .completed_geometry_delivery import CompletedGeometryDelivery
  return CompletedGeometryDelivery(record).prep
 if item['kind'] in ('geometry','geometry_task'):
  if item['kind']=='geometry':
   from .task_creation import registration_kind
   if registration_kind(registry or default_projects_path(),record)!='geometry':raise ValueError('TASK_CREATION_NEW_KIND_REQUIRED')
  if item['kind']=='geometry_task':
   from .task_creation import validate_created
   validate_created(registry or default_projects_path(),item)
  from .geometry_session import validate_preparation
  return validate_preparation(record,for_execution=False)
 if item['kind']=='rectlight_shape':
  from .rectlight_shape_session import RectlightShapeSession
  RectlightShapeSession(record['path'],read_only=True)
 elif item['kind']=='creative':
  if p.get('schema')!='bridge.hy3-creative-preparation/1' or not {'task_id','worker','scope','runtime_control','configuration','ledger_root'}<=p.keys():raise ValueError('BRIDGE_CREATIVE_PREPARATION_REQUIRED')
  if not (_plain(record['path']).parent/'creative-state.json').is_file():raise ValueError('BRIDGE_CREATIVE_STATE_REQUIRED')
 else:
  if p.get('schema')!='bridge.workbuddy.diagnostic_run/1.0' or not p.get('session_id') or item['backend'] not in ('diagnostic','production'):raise ValueError('BRIDGE_PREPARED_RUN_REQUIRED')
  if not Path(item['scheduler_root']).is_absolute():raise ValueError('BRIDGE_SCHEDULER_ROOT_REQUIRED')
 return p

def register_project(path,project_id,label,*,preparation=None,prepared_run=None,scheduler_root=None,backend='diagnostic'):
 """操作者显式登记工程，模型工具不接收任意工程路径。"""
 _identifier(project_id);path=_plain(path)
 if not isinstance(label,str) or not 1<=len(label)<=120:raise ValueError('BRIDGE_PROJECT_LABEL_REQUIRED')
 if (preparation is None)==(prepared_run is None):raise ValueError('BRIDGE_ONE_PREPARATION_REQUIRED')
 if preparation is not None:
  record=file_record(_plain(preparation));decoded=json.loads(checked_bytes(record))
  if not isinstance(decoded,dict):raise ValueError('BRIDGE_ENTRY_OBJECT_REQUIRED')
  schema=decoded.get('schema')
  kind='geometry' if schema=='bridge.geometry-creative-preparation/1' else 'rectlight_shape' if schema=='bridge.rectlight-shape-preparation/1' else 'creative'
  if kind=='geometry':
   from .task_creation import registration_kind
   kind=registration_kind(path,record)
  item={'label':label,'kind':kind,'preparation':record}
 else:
  item={'label':label,'kind':'graph','prepared_run':file_record(_plain(prepared_run)),'scheduler_root':str(_plain(scheduler_root)),'backend':backend}
 validate_project(item,registry=path)
 if item['kind']=='geometry_task':
  from .task_creation import validate_created
  if validate_created(path,item)['project_id']!=project_id:raise ValueError('TASK_CREATION_PROJECT_BINDING_INVALID')
 ensure_private_directory(path.parent)
 with execution_lock(path.parent,'bridge-projects'):
  v=read_projects(path);old=v['projects'].get(project_id)
  if old is not None and old!=item:raise ValueError('BRIDGE_PROJECT_ID_CONFLICT')
  if old is None and len(v['projects'])>=64:raise ValueError('BRIDGE_PROJECT_LIMIT')
  v['projects'][project_id]=item
  read_projects_shape={'schema':v['schema'],'projects':v['projects']}
  atomic_write(path,(json.dumps(read_projects_shape,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode(),owned_root=path.parent)
 return {'project_id':project_id,'registered':True,'kind':item['kind']}

class ProjectEntry:
 """选择仅属于本连接；后端沿原核心，消费者回执写本入口私有目录。"""
 def __init__(self,projects=None):
  self.path=_plain(projects or default_projects_path());self.selected=None;self.item=None;self.backend=None;self.stack=ExitStack();self.connection_id=uuid.uuid4().hex;self.connections=None
 def close(self):self.stack.close()
 def record_event(self,kind,payload):pass  # MCP握手不写入原工程审计或隐式创建状态。
 def _current(self,project_id=None):
  if self.selected is None:raise ValueError('BRIDGE_PROJECT_REQUIRED')
  if project_id is not None and project_id!=self.selected:raise ValueError('BRIDGE_WRONG_PROJECT')
  item=read_projects(self.path)['projects'].get(self.selected)
  if item!=self.item:raise ValueError('BRIDGE_PROJECT_REGISTRATION_CHANGED')
  validate_project(item,registry=self.path)
  return item
 def bridge_health(self):
  return {'state':'READY','entry_ready':True,'dcc_connected':'not_checked','selected_project':self.selected,'registered_projects':len(read_projects(self.path)['projects']),'python_version':sys.version.split()[0],'python_executable':sys.executable,'runtime_module':str(Path(__file__).resolve()),'native_dispatch_attempted':False,'next_step':'已有工程：bridge_projects → bridge_select_project → bridge_tasks → bridge_continue_task；仅新任务需要后台实例时：bridge_connect → bridge_connection_status'}
 def _connections(self):
  """连接管理器只在显式连接工具调用时装配，入口健康检查不创建状态或探测宿主。"""
  if self.connections is None:
   from .background_connections import BackgroundConnections
   self.connections=BackgroundConnections(runtime_root=Path(__file__).resolve().parents[4],state_root=self.path.parent/'connections')
  return self.connections
 def bridge_connect(self,request_id):
  """稳定请求只创建一次独立后台连接；宿主生命周期不绑定MCP传输关闭。"""
  return self._connections().connect(request_id)
 def bridge_connection_status(self,connection_id):
  """重验原连接事实，不隐式启动或延长已有宿主期限。"""
  return self._connections().status(connection_id)
 def bridge_disconnect(self,connection_id):
  """只终止该连接记录中的自有后台宿主。"""
  return self._connections().disconnect(connection_id)
 def bridge_projects(self):
  return {'projects':[{'project_id':k,'label':v['label'],'kind':v['kind']} for k,v in read_projects(self.path)['projects'].items()]}
 def bridge_select_project(self,project_id):
  item=read_projects(self.path)['projects'].get(project_id)
  if item is None:raise ValueError('BRIDGE_PROJECT_NOT_FOUND')
  prep=validate_project(item,registry=self.path)
  self.stack.close();self.stack=ExitStack();self.selected=project_id;self.item=copy.deepcopy(item);self.backend=None
  return {'project_id':project_id,'label':item['label'],'kind':item['kind'],'task_id':prep.get('creative_task_id',prep.get('task_id',prep.get('session_id'))),'native_dispatch_attempted':False,'next_step':'bridge_tasks with this project_id'}
 def bridge_create_task(self,request_id,source_project_id,source_operation_id,goal):
  """只从明确选中且已登记的源创建；不接受任意路径、worker或原生许可。"""
  from .task_creation import create
  source=self._current(source_project_id)
  return create(self.path,source_project_id,source,source_operation_id,goal,request_id)
 def bridge_creation_status(self,request_id,source_project_id,source_operation_id,goal):
  """必须显式选中原来源；查询不装配作业、不执行创建收尾。"""
  self._current(source_project_id)
  from .task_creation import creation_status
  return creation_status(self.path,source_project_id,source_operation_id,goal,request_id)
 def bridge_current_project(self):
  if self.selected is None:return {'project_id':None,'next_step':'bridge_projects then bridge_select_project'}
  item=self._current();return {'project_id':self.selected,'label':item['label'],'kind':item['kind']}
 def _creative(self):
  """只复制本工程前端接收状态；任务、准备、正式结果仍是原身份和原路径。"""
  from .creative_session import CreativeSession
  item=self._current();session=CreativeSession(item['preparation']['path']);source=session.state_path
  directory=self.path.parent/'consumers'/self.selected/self.connection_id
  _plain(directory);ensure_private_directory(directory)
  with execution_lock(session.root,'creative-session'):
   raw=source.read_bytes()
  atomic_write(directory/'creative-state.json',raw,owned_root=directory)
  return CreativeSession(item['preparation']['path'],state_directory=directory)
 def _geometry(self,project_id=None):
  from .geometry_entry import GeometryEntrySession
  item=self._current(project_id)
  if item['kind']=='geometry_delivery':
   from .completed_geometry_delivery import CompletedGeometryDelivery
   if self.backend is None:self.backend=CompletedGeometryDelivery(item['preparation'],connection_id=self.connection_id)
   return self.backend
  if item['kind'] not in ('geometry','geometry_task'):raise ValueError('BRIDGE_PROJECT_CAPABILITY_UNAVAILABLE')
  if self.backend is None:self.backend=GeometryEntrySession(item['preparation'],connection_id=self.connection_id)
  return self.backend
 def _editable(self,project_id):
  if self._current(project_id)['kind']=='rectlight_shape':
   if self.backend is None:
    from .rectlight_shape_session import RectlightShapeSession
    self.backend=RectlightShapeSession(self.item['preparation']['path'],connection_id=self.connection_id,
     state_directory=self.path.parent/'consumers'/self.selected/self.connection_id)
   return self.backend
  return self._geometry(project_id)
 def bridge_catalog(self,project_id):
  backend=self._editable(project_id);value=backend.catalog()
  if self.item['kind']=='geometry_task':
   from .task_creation import validate_created,execution_status
   creation=validate_created(self.path,self.item)
   value['creation']={'state':'PREPARED','profile':creation['profile'],'source_project_id':creation['source_project_id'],
    'source_operation_id':creation['source_operation_id'],'source_model_graph':backend.prep['source_model_graph'],
    'native_execution_authorized':execution_status(self.path,self.item),'authorization_status':'independent operator grant required for execution'}
  return value
 def bridge_media(self,project_id,asset_id):return self._editable(project_id).media(asset_id)
 def bridge_observe(self,project_id,asset_id,request_id,observation):return self._editable(project_id).observe(asset_id,request_id,observation)
 def bridge_propose(self,project_id,request_id,base_revision,goal,rationale,observation_ids,model_graph=None,edits=None,rectlight_shape=None):
  if self._current(project_id)['kind']=='rectlight_shape':return self._editable(project_id).propose(request_id,base_revision,goal,rationale,observation_ids,rectlight_shape,model_graph,edits)
  if rectlight_shape is not None:raise ValueError('RECT_SHAPE_PROJECT_REQUIRED')
  return self._geometry(project_id).propose(request_id,base_revision,goal,rationale,observation_ids,model_graph,edits)
 def bridge_execute(self,project_id,plan_id,request_id):
  item=self._current(project_id)
  if item['kind']=='geometry_task':
   backend=self._geometry(project_id)
   if plan_id in backend._read().get('plans',{}):
    from .task_creation import execute
    return execute(self.path,project_id,item,plan_id,request_id,lambda:backend.execute(plan_id,request_id))
   return backend.execute(plan_id,request_id)
  return self._editable(project_id).execute(plan_id,request_id)
 def bridge_cancel_task(self,project_id,operation_id):return self._geometry(project_id).cancel(operation_id)
 def _graph_operations(self):
  """观察者仅读取原目录身份和操作索引，绝不装配executor或接管任务。"""
  from .workbuddy_project import _sha
  item=self._current();manifest=validate_project(item);root=Path(item['prepared_run']['path']).parent;database=_plain(root/'diagnostic.sqlite3')
  if not database.is_file():raise ValueError('BRIDGE_GRAPH_OBSERVER_DATABASE_REQUIRED')
  with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
   identity=db.execute('SELECT id,manifest_hash FROM run_identity').fetchall()
   if identity!=[(manifest['run_id'],_sha(manifest))]:raise ValueError('BRIDGE_GRAPH_RUN_IDENTITY_CHANGED')
   rows=db.execute('SELECT operation_id,kind,request_id FROM operation_registry ORDER BY operation_id').fetchall()
  return root,[{'operation_id':r[0],'kind':r[1],'request_id':r[2]} for r in rows]
 def bridge_tasks(self,project_id):
  item=self._current(project_id)
  if item['kind']=='rectlight_shape':return {'project_id':project_id,'tasks':self._editable(project_id).tasks(),'native_dispatch_attempted':False}
  if item['kind'] in ('geometry','geometry_task','geometry_delivery'):return {'project_id':project_id,'tasks':self._geometry(project_id).tasks(),'task_id':self._geometry(project_id).prep['task_id'],'preparation_state':'REGISTERED_DELIVERY' if item['kind']=='geometry_delivery' else 'PREPARED','native_dispatch_attempted':False}
  if item['kind']=='creative':
   from .creative_session import CreativeSession
   s=CreativeSession(item['preparation']['path']);v=s._read()
   return {'project_id':project_id,'tasks':[{'operation_id':k,'state':q['state'],'revision':q['revision'],'task_id':s.prep['task_id']} for k,q in v['jobs'].items()],'native_dispatch_attempted':False}
  root,tasks=self._graph_operations()
  return {'project_id':project_id,'tasks':[{**t,'state':'QUERY_REQUIRED'} for t in tasks],'native_dispatch_attempted':False}
 def bridge_continue_task(self,project_id,operation_id):
  item=self._current(project_id)
  if item['kind']=='rectlight_shape':return {**self._editable(project_id).query(operation_id),'project_id':project_id}
  if item['kind'] in ('geometry','geometry_task','geometry_delivery'):return {**self._geometry(project_id).query(operation_id),'project_id':project_id}
  if item['kind']!='creative':
   from .graph_jobs import GraphJobService
   root,tasks=self._graph_operations();task=next((t for t in tasks if t['operation_id']==operation_id),None)
   if task is None:raise ValueError('BRIDGE_TASK_NOT_IN_PROJECT')
   if task['kind']!='graph':
    return {'project_id':project_id,'operation_id':operation_id,'state':'UNKNOWN','action':'BLOCKED','error_code':'BRIDGE_BOUND_HOST_OBSERVATION_REQUIRED','native_dispatch_attempted':False}
   result=GraphJobService.observe_status(root/'jobs',operation_id)
   return {'project_id':project_id,'operation_id':operation_id,'state':result['state'],'action':'OBSERVE_ORIGINAL','result':result,'native_dispatch_attempted':False}
  session=self._creative();job=session._read()['jobs'].get(operation_id)
  if job is None:raise ValueError('BRIDGE_TASK_NOT_IN_PROJECT')
  result=session.operation_query(operation_id);state=result.get('state')
  if state=='COMPLETE':
   directory=session._execution_directory(job);record=file_record(directory/'result.json');formal=json.loads(checked_bytes(record))
   validation=session._validate_completion(directory,formal)
   files=dict(formal['files']);files['preview']=formal['preview']['preview']
   for f in files.values():checked_bytes(f)
   return {**result,**validation.get('observation',{}),'project_id':project_id,'action':'ORIGINAL_RESULT_RETURNED','original_result':record,'files':files,'native_dispatch_attempted':False}
  error=result.get('error') or {};code=error.get('code','UNKNOWN') if isinstance(error,dict) else 'UNKNOWN'
  if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,99}',code):code='UNKNOWN'
  return {'error_code':code,'project_id':project_id,'operation_id':operation_id,'state':state or 'UNKNOWN','action':'OBSERVE_ORIGINAL' if state=='RUNNING' else 'BLOCKED','blocked':state!='RUNNING','native_dispatch_attempted':False,'next_step':'Query the same operation ID. Failed or unknown execution needs its original controller repair; do not resubmit.'}

class EntryMCP(DiagnosticMCP):
 """稳定小工具面；选择和继续只路由，执行能力仍由既有核心管理。"""
 def __init__(self,entry):
  super().__init__(entry);self.tools=ENTRY_TOOLS;self.server_name='bridge-vfx-plugin';self.instructions='Bridge工程入口：bridge_health的READY只表示入口可用；新任务显式bridge_connect(request_id)建立最长120秒独立后台连接，查询bridge_connection_status，仅双宿主真实健康通过才为CONNECTED。同request或重连不续期、不重启，到期不自动重启；结束用bridge_disconnect。已有工程先列已登记工程并明确选择，再列原任务/继续原ID。完成只返回既有正式产物，运行中观察，失败/未知不重放。几何工程先读catalog.observation_requirements，真实查看每个必看asset_id并提交自己的观察；提案包含所有必看观察ID。媒体ID和edits字段以目录为准；只有execute明确启动其独立作业，其余查询不启动DCC。'
 def _call(self,params):
  name=params.get('name');args=params.get('arguments',{});tool=next((t for t in self.tools if t['name']==name),None)
  if set(params)-{'name','arguments','_meta'} or tool is None:return {'isError':True,'content':[_text_content({'code':'BRIDGE_ENTRY_INVALID_ARGUMENTS'})]}
  if name=='bridge_propose' and isinstance(args,dict) and 'model_graph' in args:
   issue=geometry_graph.model_schema_issue(args['model_graph'])
   if issue:return {'isError':True,'content':[_text_content({**issue,'native_dispatch_attempted':False})]}
  if _schema_error(args,tool['inputSchema']):
   from .geometry_entry import schema_advice
   return {'isError':True,'content':[_text_content({'code':'BRIDGE_ENTRY_INVALID_ARGUMENTS',**schema_advice(args,tool['inputSchema']),'native_dispatch_attempted':False})]}
  try:
   value=getattr(self.facade,name)(**args)
   return {'isError':False,'content':value if name=='bridge_media' else [_text_content(value)]}
  except GraphCompileError as error:
   if name!='bridge_propose':return {'isError':True,'content':[_text_content({'code':'BRIDGE_ENTRY_VALIDATION_FAILED','native_dispatch_attempted':False})]}
   # 仅返回编译器有限代码和公开JSON字段位置；details/异常原文可能包含任意输入值。
   fields='nodes|connections|outputs|parameters|node_id|node_type|context|subnet_path|source_node|source_port|target_node|target_port|target_index|output_id|port|sizex|sizey|sizez|tx|ty|tz|sx|sy|sz'
   diagnostics=[]
   for item in error.diagnostics[:4]:
    code=item.code if re.fullmatch('[A-Z][A-Z0-9_]{0,79}',item.code) else 'INVALID_GRAPH'
    field=item.path if re.fullmatch(r'\$(?:\.(?:'+fields+r')|\[[0-9]{1,2}\])*',item.path) else '$'
    diagnostics.append({'code':code,'field':'$.model_graph'+field[1:]})
   return {'isError':True,'content':[_text_content({'code':'GEOMETRY_MODEL_COMPILE_REJECTED','diagnostics':diagnostics,
     'hint':'Use model_catalog.model_graph_schema. Merge inputs require distinct contiguous target_index values from 0; all nodes must reach model_output.',
     'native_dispatch_attempted':False})]}
  except (ValueError,KeyError,TypeError,OSError,RuntimeError) as error:
   from .geometry_entry import EntryGuidanceError
   if isinstance(error,EntryGuidanceError):return {'isError':True,'content':[_text_content(error.public)]}
   code=str(error).split(':',1)[0]
   if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,119}',code):code='BRIDGE_ENTRY_VALIDATION_FAILED'
   # 连接异常可能发生于派发后；仅公开安全代码，不把未知事实写成未启动。
   if name in ('bridge_connect','bridge_connection_status','bridge_disconnect'):
    from .background_connections import PUBLIC_ERROR_CODES
    if code not in PUBLIC_ERROR_CODES:code='BRIDGE_ENTRY_VALIDATION_FAILED'
    outcome={'code':code}
   else:outcome={'code':code,'native_dispatch_attempted':False}
   return {'isError':True,'content':[_text_content(outcome)]}
