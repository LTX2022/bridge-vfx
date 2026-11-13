#!/usr/bin/env python3
"""真实外部agent驱动的两轮DiskLight增量创作；本工具不代写模型计划。"""
from __future__ import annotations
import argparse,copy,ctypes,hashlib,importlib.util,json,os,secrets,sqlite3,sys,time,uuid
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from houdini_bridge.official_karma_observation import file_record,checked_bytes,write_new
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.canonical import canonical_sha256
from continue_official_karma import _runtime_environment,Journal,_poll
from vfx_pipeline.creative_preview import write_preview


def load(path):return json.loads(Path(path).read_text())
def publish_result(path,value):
 """只在内容完整后原子公布异步结果，避免查询者读到半份JSON。"""
 from dcc_task_runtime.platform_support import atomic_write
 if path.exists():raise ValueError('CREATIVE_RESULT_ALREADY_PUBLISHED')
 atomic_write(path,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode(),owned_root=path.parent)
 return file_record(path)


def binding(record):return {k:record[k] for k in ('path','sha256')}


def prepare(recovery_delivery,namespace,instruction,route="workbuddy-hy3"):
 if route not in ("workbuddy-hy3","gpt-luna-low"):raise ValueError("CREATIVE_AUTHORIZED_ROUTE_REQUIRED")
 selected_route={"route":"WorkBuddyDesktopRoute","selected_model":"Hy3","reasoning_effort":"UI_default","provider_identity":"unknown"} if route=="workbuddy-hy3" else {"route":"CodexDelegatedMCPRoute","selected_model":"gpt-6-luna","reasoning_effort":"low","provider_identity":"unknown"}
 """认证旧21票和有效v2，不启动DCC或调用模型。"""
 from prepare_workbuddy_graph import prepare_graph
 from nuke_bridge.task_host import input_artifact_registry
 from houdini_bridge.official_karma_display import _processor,_exposure
 from dcc_task_runtime.exr_codec import read_exr
 delivery_record=file_record(Path(recovery_delivery).resolve());delivery=json.loads(checked_bytes(delivery_record))
 result=json.loads(checked_bytes(delivery['result']));base=NativeScope(result['scope']);usage=base.snapshot()
 if delivery['state']!='NUKE_FRAME_ENTRY_RECOVERY_ACCEPTED' or any(t['stopped_at'] is None for t in usage['tickets']):raise ValueError('CREATIVE_ACCEPTED_STOPPED_SOURCE_REQUIRED')
 # 来源链中的反馈准备和输入来源均为上一轮已认证原件。
 recovery_prep=load(result['preparation']['path']);source_record=recovery_prep['source'];source=json.loads(checked_bytes(source_record))
 registry=input_artifact_registry(source,scope=base,task_id=delivery['task_id'])
 if not registry.verify(source['artifact_id'])['usable'] or registry.lookup(source['artifact_id'])['version']!=2:raise ValueError('CREATIVE_CURRENT_V2_REQUIRED')
 feedback_prep=load(recovery_prep['source_preparation']['path'])
 producer_prep=load(feedback_prep['feedback_preparation']['path'])
 producer_root=Path(feedback_prep['feedback_preparation']['path']).parent
 state=load(producer_root/'incremental-state.json')['stages']
 saved=state['save']['result'];latest_control=Path(producer_prep['control'])
 protected=load(producer_root/'delivery-manifest.json')['files']
 for item in protected.values():checked_bytes(item)
 root=base.root/'continuations'/namespace
 existing=None
 if root.exists():
  if (root/'creative-preparation.json').exists() or not (root/'scope.json').exists():raise ValueError('CREATIVE_FRESH_NAMESPACE_REQUIRED')
  existing=NativeScope(binding(file_record(root/'scope.json')))
  if existing.snapshot()['tickets']!=usage['tickets'] or existing.scope.get('creative_phase',{}).get('source_delivery')!=delivery_record:raise ValueError('CREATIVE_PARTIAL_PREPARATION_NOT_UNUSED')
  import shutil
  for name in ('runtime','frontend','workspace','media'):
   path=root/name
   if path.exists():
    if path.is_symlink():raise ValueError('CREATIVE_PARTIAL_SYMLINK')
    shutil.rmtree(path)
 else:root.mkdir(parents=True,mode=0o700)
 scope=copy.deepcopy(base.scope)
 for key in ('feedback_phase','feedback_nuke_replacement','feedback_extra_start_approval','recovery_phase'):scope.pop(key,None)
 key=secrets.token_bytes(32)
 scope.update(scope_id='hy3-creative-'+uuid.uuid4().hex,host_started=False,
   continuation_of=file_record(base.path),creative_phase={'schema':'bridge.disklight-creative-phase/1','task_id':delivery['task_id'],
   'prior_scope':file_record(base.path),'source_delivery':delivery_record,'input_source':source_record,'starts':10,'seconds':1200},
   authorization={'authority':'current_user_instruction','instruction':instruction},
   accounting={'namespace':namespace,'key_path':str(base.root/'.native-control'/namespace/'key'),'key_sha256':hashlib.sha256(key).hexdigest()},
   budget=dict(base.scope['budget'],max_dcc_starts=base.scope['budget']['max_dcc_starts']+10,total_seconds=base.scope['budget']['total_seconds']+1200))
 native=existing if existing is not None else NativeScope.initialize(binding(write_new(root/'scope.json',scope)),key=key)
 scope=native.scope
 # 保留21票族原件；前端没有私钥或通用宿主工具。
 control=root/'frontend/control';project=root/'workspace';control.mkdir(parents=True);project.mkdir()
 config=producer_prep['configuration'];oldmanifest=load(latest_control/'run.json');hosts={}
 for kind,name in (('houdini','production_host'),('nuke','production_nuke')):
  cfg=copy.deepcopy(oldmanifest[name])
  for k in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir','input_artifact_source'):cfg.pop(k,None)
  cfg.update(native_scope=native.binding,resource_budget={'roots':[str(native.root)],'max_bytes':scope['budget']['max_disk_bytes'],'native_scope':native.binding})
  hosts[kind]=cfg
 snapshot_project=root/'runtime'
 hosts['houdini']['alpha_calibration']['plugin_reuse']['active_plugin']['path']=str(snapshot_project/'control/snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
 construction=[{'index':0,'asset_id':'sealed-official-karma-disklight','semantic_role':'render_scene_configuration','source_uri':config['path'],'bytes':config['bytes'],'sha256':config['sha256']}]
 prepare_graph(snapshot_project,app=None,scheduler_root=root/'scheduler',execution_profile=True,render_profile=True,
  production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
 runtime=snapshot_project/'control/snapshot'
 original_scope=load(scope['reused_inputs']['scope']['path']);policy=original_scope['official_case']['display_policy']
 ctypes.CDLL(policy['module_files'][-1]['path'],mode=ctypes.RTLD_GLOBAL)
 _,cache=_processor(policy)
 reference=file_record(Path(scope['reused_inputs']['reference']['path']))
 # reference记录本身可能是EXR身份记录，不是图像字节；只接受最终实际EXR。
 if not reference['path'].endswith('.exr'):
  reference=file_record(Path(original_scope['official_case']['paths']['official_image']))
 display={'schema':'bridge.creative-display/1','policy':policy,'exposure_stops':_exposure(read_exr(reference['path'])),
  'processor_cache_id':cache,'exposure_source':reference,'alpha_display':'composite_over_black_opaque'}
 display['sha256']=canonical_sha256(display)
 previews=root/'media';previews.mkdir()
 official=write_preview(reference,previews/'reference.png',display)
 current=write_preview(protected['main_exr'],previews/'current.png',display)
 prep={'schema':'bridge.hy3-creative-preparation/1','model_route':selected_route,'scope':native.binding,'task_id':delivery['task_id'],
  'source_graph':producer_prep['source_graph'],'configuration':config,'base_delivery':delivery_record,
  'base_input_source':source_record,'ledger_root':source['producer_ledger'],'baseline_control':str(latest_control),
  'baseline_saved':saved,'baseline_feedback_version':1,'baseline_exposure':1.,'protected_files':protected,
  'feedback_preparation':file_record(Path(feedback_prep['feedback_preparation']['path'])),
  'baseline_sidecars':[file_record(p) for p in (latest_control/'houdini-instances/fx_operations').glob('*.saves.json')],
  'baseline_diagnostic':file_record(latest_control/'diagnostic.sqlite3'),
  'nuke_template':delivery['files']['nk'],'display':display,'media':{'reference':official,'current':current},
  'runtime_control':str(snapshot_project/'control'),'runtime_manifest':file_record(snapshot_project/'control/run.json'),
  'runtime_snapshot_manifest':file_record(snapshot_project/'control/snapshot-manifest.json'),
  'supervisor_python':scope['hosts']['supervisor_python']['path'],'worker':str(runtime/'tools/run_hy3_creative.py'),
  'environment':_runtime_environment(scope),'initial_starts':usage['dcc_starts'],'initial_seconds':usage['total_seconds']}
 record=write_new(root/'creative-preparation.json',prep)
 assets={k:{'asset_id':k,'file':v['preview'],'sha256':v['preview']['sha256'],'kind':'image','mime_type':'image/png','role':k} for k,v in prep['media'].items()}
 write_new(root/'creative-state.json',{'schema':'bridge.creative-session-state/1','assets':assets,'served':{},'observations':{},'plans':{},'jobs':{},'requests':{},'completed':[],'current_asset':'current','current_exposure':1.})
 launcher='''import sys\nfrom pathlib import Path\nroot=Path(__RUNTIME__)\nfor name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(root/'packages'/name/'src'))\nfrom vfx_pipeline.creative_session import CreativeSession,CreativeMCP\nfrom vfx_pipeline.workbuddy_mcp import serve\nserve(CreativeSession(__PREP__),adapter_class=CreativeMCP)\n'''.replace('__RUNTIME__',repr(str(runtime))).replace('__PREP__',repr(record['path']))
 (control/'server.py').write_text(launcher)
 mcp={'mcpServers':{'bridge-hy3-creative':{'command':prep['supervisor_python'],'args':['-I','-B',str(control/'server.py')]}}}
 (project/'.workbuddy').mkdir();(project/'.workbuddy/mcp.json').write_text(json.dumps(mcp,ensure_ascii=False,indent=2))
 (project/'任务说明.md').write_text('本轮仅使用bridge-hy3-creative连接器：实际查看reference和current，提交自己的观察、计划并执行两阶段曝光创作。不得使用文件/终端/其它agent直接修改工程。模型选择由creative-preparation中的model_route指定；provider身份未知。\n')
 return {'preparation':record,'workspace':str(project),'mcp_config':str(project/'.workbuddy/mcp.json'),'native_starts':0}


def _copy_feedback(source,facade):
 """按旧控制原件完整继承内容版本，不将新run误置为版本0。"""
 from vfx_pipeline.feedback_versions import FeedbackVersions
 FeedbackVersions(facade)
 path=Path(source)/'diagnostic.sqlite3'
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as old:
  rows=old.execute('SELECT graph_id,version,state,payload FROM feedback_versions').fetchall()
 with facade._connect() as db:
  for row in rows:
   prior=db.execute('SELECT state,payload FROM feedback_versions WHERE graph_id=? AND version=?',row[:2]).fetchone()
   if prior is not None and tuple(prior)!=tuple(row[2:]):raise ValueError('CREATIVE_FEEDBACK_HISTORY_CONFLICT')
   db.execute('INSERT OR IGNORE INTO feedback_versions VALUES(?,?,?,?)',row)


def _job_facade(prep,jobprep):
 """仍经正式GraphRun，只禁用不属于创作范围的重建及Nuke控制宿主。"""
 from contextlib import contextmanager
 from vfx_pipeline.official_graph_resume import resume_graph_facade
 from vfx_pipeline.artifact_registry import ArtifactRegistry
 @contextmanager
 def bound():
  control=Path(jobprep['control']);directory=control/'houdini-instances/fx_operations';directory.mkdir(parents=True,exist_ok=True)
  for record in jobprep['save_sidecars']:
   dest=directory/Path(record['path']).name
   if not dest.exists():dest.write_bytes(checked_bytes(record))
  with resume_graph_facade(control/'run.json',prep['source_graph'],repo_root=ROOT,scheduler_root=Path(prep['scope']['path']).parent/'scheduler') as f:
   registry=ArtifactRegistry(prep['ledger_root']);f.artifact_registry=registry
   f.host_client.bind_artifact_registry(registry)
   f.save_root=Path(jobprep['project'])/'saves';f.official_feedback_configuration=json.loads(checked_bytes(prep['configuration']))
   _copy_feedback(jobprep['history_control'],f);f._save_receipt(jobprep['saved_source'])
   yield f
 return bound()


def prepare_job(prep,job):
 """为已由模型提交的计划准备当前控制快照，不触发新的图构造。"""
 from prepare_workbuddy_graph import prepare_graph
 root=Path(job['directory']);path=root/'job-preparation.json'
 if path.exists():return load(path)
 revision=job['plan']['revision'];front=Path(job['preparation']['path']).parent;shape=prep.get('target_authority') is not None;session=load(front/('shape-state.json' if shape else 'creative-state.json'))
 if revision==1:
  previous=None;history=prep['baseline_control'];saved=prep['baseline_saved'];sidecars=prep['baseline_sidecars']
 else:
  prior_job=session['completed'][-1]
  from vfx_pipeline.creative_session import CreativeSession
  prior_directory=Path(session['jobs'][prior_job]['directory']) if shape else CreativeSession(job['preparation']['path'])._execution_directory(session['jobs'][prior_job])
  previous=json.loads(checked_bytes(session['jobs'][prior_job]['result']));
  if Path(session['jobs'][prior_job]['result']['path'])!=prior_directory/'result.json':raise ValueError('CREATIVE_PRIOR_RESULT_REQUIRED')
  history=previous['control'];saved=previous['saved'];sidecars=previous['save_sidecars']
 old=load(prep['runtime_manifest']['path']);hosts={};project=root/'project';control=project/'control';project.mkdir()
 for kind,key in (('houdini','production_host'),('nuke','production_nuke')):
  cfg=copy.deepcopy(prep['hosts'][kind] if shape else old[key])
  for name in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir','input_artifact_source'):cfg.pop(name,None)
  if kind=='houdini':cfg['alpha_calibration']['plugin_reuse']['active_plugin']['path']=str(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
  hosts[kind]=cfg
 config=prep['configuration'];construction=[{'index':0,'asset_id':prep.get('case_id','sealed-official-karma-disklight'),'semantic_role':'render_scene_configuration','source_uri':config['path'],'bytes':config['bytes'],'sha256':config['sha256']}]
 prepare_graph(project,app=None,scheduler_root=front/'scheduler',execution_profile=True,render_profile=True,production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
 result={'control':str(control),'project':str(project),'history_control':history,'saved_source':saved,'save_sidecars':sidecars,'previous':None if previous is None else session['jobs'][prior_job]['result']}
 write_new(path,result)
 return result


def run_job(job_path):
 """后台只消费真实MCP请求；固定工程步骤与模型参数分别记录。"""
 job=json.loads(checked_bytes(file_record(Path(job_path))));prep=json.loads(checked_bytes(job['preparation']));directory=Path(job['directory'])
 from run_alpha_calibration import ScopeBudget
 from run_controlled_engineering import _stop_host
 from vfx_pipeline.feedback_versions import FeedbackVersions
 from houdini_bridge.official_karma_feedback import EXPOSURE,GATE
 from vfx_pipeline.official_graph_resume import _snapshot
 for item in prep['protected_files'].values():checked_bytes(item)
 if ROOT!=Path(prep['runtime_control'])/'snapshot' or _snapshot(Path(prep['runtime_control']))!=prep['runtime_snapshot_manifest']:raise ValueError('CREATIVE_PREPARED_WORKER_REQUIRED')
 native=NativeScope(prep['scope']);native.check()
 plan=job['plan'];revision=plan['revision'];operation=job['operation_id']
 if plan['exposure']==plan['base_exposure']:raise ValueError('CREATIVE_EFFECTIVE_CHANGE_REQUIRED')
 os.environ.clear();os.environ.update(prep['environment'])
 # 每个作业的控制端使用当前准备源码，原生启动仍来自同一固定范围。
 jobprep=prepare_job(prep,job);control=Path(jobprep['control']);project=Path(jobprep['project']);(project/'saves').mkdir(exist_ok=True)
 # facade要求源码ROOT对应这份job快照；新控制器从本job快照接续，不重复准备。
 if ROOT!=control/'snapshot':
  child=__import__('subprocess').run([prep['supervisor_python'],'-I','-B',str(control/'snapshot/tools/run_hy3_creative.py'),'execute-job','--job',str(job_path)],cwd=str(directory))
  if child.returncode:raise RuntimeError('CREATIVE_JOB_EXECUTION_FAILED')
  return
 execute_job(job_path)


def execute_job(job_path):
 """正式改参、保存、冷重开、单帧Karma、登记与Nuke冷消费。"""
 from run_alpha_calibration import ScopeBudget
 from run_controlled_engineering import _stop_host
 from vfx_pipeline.feedback_versions import FeedbackVersions
 from houdini_bridge.official_karma_feedback import EXPOSURE,GATE
 from houdini_bridge.official_karma import compare_files
 from vfx_pipeline.official_graph_resume import _snapshot
 job=load(job_path);prep=json.loads(checked_bytes(job['preparation']));directory=Path(job['directory']);jobprep=load(directory/'job-preparation.json')
 control=Path(jobprep['control']);project=Path(jobprep['project']);native=NativeScope(prep['scope']);budget=ScopeBudget(prep['scope']['path']);budget.limits=dict(native.scope['budget']);budget.available(starts=4)
 if ROOT!=control/'snapshot':raise ValueError('CREATIVE_JOB_SNAPSHOT_REQUIRED')
 _snapshot(control)
 os.environ.clear();os.environ.update(prep['environment'])
 journal=Journal(directory,job_path)
 if journal.value['stages']:raise ValueError('CREATIVE_JOB_QUERY_EXISTING_INTENT_REQUIRED')
 data={'root':native.root,'project':project,'control':control,'scope_path':Path(prep['scope']['path']),'scope_sha256':prep['scope']['sha256']}
 graph=prep['source_graph']['graph_id'];plan=job['plan'];revision=plan['revision'];prefix=job['operation_id']
 try:
  with _job_facade(prep,jobprep) as f:
   def reopen_source():
    result=f.task_reopen(jobprep['saved_source']['saved_scene_id'])
    if prep.get('target_authority') is not None:
     roles={n['role']:n['path'] for n in jobprep['saved_source']['scene_contract']['nodes']}
     rebound=f.host_client.call('node.set_parms',{'task_id':prep['task_id'],'path':roles['light'],'parms':{EXPOSURE:-.25},'official_case_configuration':prep['configuration']})
     return {'reopen':result,'shape_rebind':rebound}
    return result
   journal.action('baseline_reopen',reopen_source)
   old=journal.action('version_before',lambda:f.graph_version(graph))
   changes=plan['rectlight_shape'] if prep.get('target_authority') is not None else {'exposure':plan['exposure']}
   changed=journal.action('feedback',lambda:f.feedback_edit(graph,'light',changes,prep['task_id']))
   if changed['state']!='COMPLETE' or changed['version']!=old['version']+1:raise ValueError('CREATIVE_NATIVE_CHANGE_MISMATCH')
   if prep.get('target_authority') is not None:
    from houdini_bridge.rectlight_shape_target import WIDTH,HEIGHT,WIDTH_GATE,HEIGHT_GATE
    for key,parm in [('width',WIDTH),('height',HEIGHT)]:
     if changed['before'][parm]!=plan['base_shape'][key] or changed['after'][parm]!=plan['rectlight_shape'][key]:raise ValueError('RECT_SHAPE_NATIVE_CHANGE_MISMATCH')
   elif changed['before'][EXPOSURE]!=plan['base_exposure'] or changed['after'][EXPOSURE]!=plan['exposure']:raise ValueError('CREATIVE_NATIVE_CHANGE_MISMATCH')
   saved=journal.action('save',f.task_save);roles={n['role']:n['path'] for n in saved['scene_contract']['nodes']}
   journal.action('edit_host_stop',lambda:_stop_host(data,'houdini'))
  with _job_facade(prep,jobprep) as f:
   f._save_receipt(saved)
   reopened=journal.action('cold_reopen',lambda:f.task_reopen(saved['saved_scene_id']))
   if prep.get('case_id')=='karma_lights_rectlight_v1':
    from houdini_bridge.official_case_variant import verified_reopen_parameters
    parms=journal.action('cold_readback',lambda:verified_reopen_parameters(reopened,saved,json.loads(checked_bytes(prep['configuration'])),f.host_client.production_config['expected_identity'],[WIDTH,HEIGHT,WIDTH_GATE,HEIGHT_GATE,EXPOSURE,GATE] if prep.get('target_authority') is not None else [EXPOSURE,GATE]))
   else:
    parms=journal.action('cold_readback',lambda:f.host_client.call('node.parms',{'path':roles['light'],'names':[EXPOSURE,GATE]}))
   if parms['parms']!=changed['after']:raise ValueError('CREATIVE_COLD_READBACK_MISMATCH')
   # USD路径由原生render场景锁内部受控绑定并恢复，保存场景合同保持有效。
   usd=str(project/'saves/main.0001.usd');pattern=str(project/'saves/main.%04d.exr')
   def render():
    result=f.host_client.call('render.start',{'task_id':prep['task_id'],'request_id':prefix+'_render','render_target':roles['render'],'output_pattern':pattern,'frames':[1],'budget_seconds':min(120,budget.remaining()),'dependencies':FeedbackVersions(f).dependencies()})
    identifier=result['operation_id'];f._register_operation(identifier,'houdini-render','houdini',prefix+'_render');return {'operation_id':identifier}
   rendered=journal.action('render',render)
   journal.action('render_completed',lambda:_poll(f,'operation_query',rendered['operation_id'],('operation','state'),budget))
   journal.action('render_host_stop',lambda:_stop_host(data,'houdini'))
   verified=journal.action('verify',lambda:f.verify_render_output(prefix+'_verify',rendered['operation_id']))
   image=verified['execution_fact']['metadata']['1']
   artifact=journal.action('register',lambda:f.register_render_artifact(prep.get('main_artifact_id','disklight_incremental_main'),'preview_temp',pattern,[1],image['colorspace'],image['premultiplied'],prefix+'_verify'))
   if artifact['version']!=prep.get('baseline_main_version',2)+revision:raise ValueError('CREATIVE_MAIN_VERSION_MISMATCH')
   # 当前控制端与共享账本的显式新版本来源；不借用v2或旧Nuke宿主。
   source={'schema':'bridge.creative-nuke-source/1','task_id':prep['task_id'],'artifact_id':artifact['artifact_id'],'artifact_version':artifact['version'],
    **({'shape_authority':prep['target_authority'],'creative_task_id':prep['creative_task_id']} if prep.get('target_authority') is not None else {'creative_phase':native.scope['creative_phase']}),'producer_scope':file_record(native.path),'producer_control':str(control),'producer_ledger':prep['ledger_root'],
    'producer_manifest':file_record(control/'run.json'),'producer_snapshot_manifest':file_record(control/'snapshot-manifest.json'),
    'producer_deployment':file_record(control/'production-hosts.json'),'producer_owners':file_record(control/'host-state/houdini-operation-owners.json'),
    'registry_operation_receipt':artifact['registry_operation_receipt'],'producer_fact_sha256':canonical_sha256(verified['execution_fact']),'case_id':prep.get('case_id','karma_lights_disklight_v1'),'case_variant':prep.get('case_variant')}
   if prep.get('target_authority') is not None:source['schema']='bridge.rectlight-shape-nuke-source/1'
   source_record=write_new(control/'creative-input-source.json',source)
   nuke=cold_consume(prep,job,jobprep,source_record,journal)
   compared=compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True)
   if compared['state']!='PASS':raise ValueError('CREATIVE_NUKE_PIXEL_MISMATCH')
   preview=write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview.png',prep['display'])
   for item in prep['protected_files'].values():checked_bytes(item)
   usage=native.snapshot()
   if any(t['stopped_at'] is None for t in usage['tickets']):raise ValueError('CREATIVE_ALL_NATIVE_STOPS_REQUIRED')
   result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':prefix,'revision':revision,'exposure':plan['exposure'],
    'plan':plan,'feedback':changed,'saved':saved,'artifact':artifact,'nuke':nuke,'comparison':compared,'preview':preview,'control':str(control),
    'save_sidecars':[file_record(p) for p in (control/'houdini-instances/fx_operations').glob('*.saves.json')],
    'files':{'hip':file_record(Path(saved['path'])),'main':file_record(project/'saves/main.0001.exr'),'nk':nuke['files']['nk'],'nuke':nuke['files']['exr']},
    'model_route':prep['model_route'],**({'creative_task_id':prep['creative_task_id'],'shape_authority':prep['target_authority'],'source_preparation':prep['source_preparation']} if prep.get('target_authority') is not None else {}),'scope':usage,'phase_starts':usage['dcc_starts']-prep['initial_starts'],'phase_seconds':usage['total_seconds']-prep['initial_seconds'],'provider_identity':'unknown','human_visual_acceptance':'PENDING','case_id':prep.get('case_id','karma_lights_disklight_v1'),'case_variant':prep.get('case_variant')}
   publish_result(directory/'result.json',result)
 finally:
  try:_stop_host(data,'houdini')
  except Exception:pass


def cold_consume(prep,job,jobprep,source_record,journal,*,prelaunch_recovery=None,prepare_only=False,prepared_context=None,retry_recovery=None):
 """仅一票实际Nuke冷renderer，复用正式状态处理和typed登记。"""
 from dcc_task_runtime.graph_scheduler import GraphScheduler
 from dcc_task_runtime import owned_process
 from nuke_bridge.task_host import input_artifact_registry
 from recover_disklight_nuke import cold_request_digest,cleanup_cold_attempt,assert_released_slot
 from nuke_bridge.operation_receipts import registered_input_contract
 control=Path(jobprep['control']);project=Path(jobprep['project']);native=NativeScope(prep['scope']);source=json.loads(checked_bytes(source_record))
 spec=importlib.util.spec_from_file_location('creative_cold_nuke',ROOT/'plugins/nuke/nuke_bridge_addon.py');addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
 addon._RENDER_RECORDS_DIR=native.root/'state/nuke_renders';addon._NUKE_SCHEDULER=GraphScheduler(Path(prep['scope']['path']).parent/'scheduler')
 registry=input_artifact_registry(source,scope=native,task_id=prep['task_id'],fallback=addon._nuke_operation_fact);addon._NUKE_ARTIFACT_REGISTRY=registry
 artifact=registry.lookup(source['artifact_id'])
 # 正式输入合同由现有注册输入工厂冻结，不从模型文本声明输入事实。
 from nuke_bridge.operation_receipts import freeze_agent_inputs
 from dcc_task_runtime.artifact_registry import frame_path
 actual_frame=file_record(Path(frame_path(artifact['pattern'],1)))
 input_binding=freeze_agent_inputs(prep['task_id'],[{'role':'registered_main','path':artifact['pattern'],'artifact_id':artifact['artifact_id'],
  'frames':[{'frame':1,'path':actual_frame['path'],'sha256':actual_frame['sha256'],'bytes':actual_frame['bytes']}]}])
 contract=registered_input_contract(input_binding,registry,task_id=prep['task_id'])
 template=checked_bytes(prep['nuke_template']).decode();oldbase=load(Path(prep['feedback_preparation']['path']).parent/'delivery-manifest.json')
 oldmain=str(Path(oldbase['files']['main_exr']['path']).parent/'main.%04d.exr')
 # 模板来自上一真实冷开工程，只替换三个已知路径。
 import re
 write_line=re.findall(r'^ file (.*recovered\.%04d\.exr)$',template,re.M)
 if len(write_line)!=1 or template.count(oldmain)!=1:raise ValueError('CREATIVE_NK_TEMPLATE_INVALID')
 oldout=write_line[0];oldname=re.findall(r'^ name (.*\.nk)$',template,re.M)
 if len(oldname)!=1 or template.count(oldout)!=2:raise ValueError('CREATIVE_NK_TEMPLATE_PATHS_INVALID')
 pattern=str(project/'saves/nuke.%04d.exr');script=project/'saves/composite.nk';retry=None
 if retry_recovery is not None:
  from vfx_pipeline.creative_results import validate_nuke_retry_recovery
  if prep.get('nuke_retry_recovery')!=retry_recovery:raise ValueError('RECT_NUKE_RETRY_PREPARATION_CONFLICT')
  retry=validate_nuke_retry_recovery(retry_recovery,native);contract_retry=retry['contract']
  if source_record!=contract_retry['source_input']:raise ValueError('RECT_NUKE_RETRY_EXISTING_SOURCE_REQUIRED')
  pattern=contract_retry['retry_pattern'];script=Path(contract_retry['retry_script'])
 context_path=control/'cold-context.json' if retry is None else Path(contract_retry['retry_context'])
 if any(p.is_symlink() for p in (context_path,*context_path.parents,script,*script.parents)):raise ValueError('RECT_NUKE_RETRY_PATH_LINK_FORBIDDEN')
 context_path.parent.mkdir(exist_ok=True)
 expected_script=template.replace(oldmain,artifact['pattern']).replace(oldout,pattern).replace(oldname[0],str(script))
 expected_context={'schema':'bridge.rectlight-shape-cold-context/1' if prep.get('target_authority') is not None else 'bridge.creative-cold-context/1','native_scope':native.binding,'task_id':prep['task_id'],'input_artifact_source':source_record}
 tail=prep.get('render_terminal_recovery') is not None
 if tail:expected_context['render_terminal_recovery']=prep['render_terminal_recovery']
 if retry is not None:expected_context['nuke_retry_recovery']=retry_recovery
 if (prepare_only or prepared_context is not None) and (not tail or job['operation_id']!='creative_bff6f898fafe1db03aae'):raise ValueError('RECT_RENDER_TAIL_PREFLIGHT_ONLY_REQUIRED')
 if prelaunch_recovery is None and prepared_context is None:
  if tail and script.exists():
   if script.read_text()!=expected_script:raise ValueError('RECT_RENDER_TAIL_SCRIPT_CHANGED')
  else:script.write_text(expected_script)
  if tail and context_path.exists():
   context=file_record(context_path)
   if json.loads(checked_bytes(context))!=expected_context:raise ValueError('RECT_RENDER_TAIL_CONTEXT_CHANGED')
  else:context=write_new(context_path,expected_context)
 elif prepared_context is not None:
  if script.read_text()!=expected_script:raise ValueError('RECT_RENDER_TAIL_SCRIPT_CHANGED')
  context=file_record(context_path)
  if json.loads(checked_bytes(context))!=expected_context:raise ValueError('RECT_RENDER_TAIL_CONTEXT_CHANGED')
 else:
  # 已认证启动前失败仅复用原NK和context，原文件和旧launch intent均不覆写。
  if prelaunch_recovery!=prep.get('nuke_prelaunch_recovery') or job['operation_id']!='creative_06679b9bba7ae49982f1' or script.read_text()!=expected_script:raise ValueError('RECT_NUKE_ORIGINAL_SCRIPT_REQUIRED')
  context=file_record(context_path)
  if json.loads(checked_bytes(context))!=expected_context:raise ValueError('RECT_NUKE_ORIGINAL_CONTEXT_REQUIRED')
 os.environ['BRIDGE_CREATIVE_COLD_CONTEXT']=context['path'];os.environ['BRIDGE_CREATIVE_COLD_CONTEXT_SHA256']=context['sha256'];os.environ.pop('BRIDGE_NUKE_HOST_CONFIG',None);os.environ.pop('BRIDGE_NUKE_HOST_CONFIG_SHA256',None)
 os.environ['BRIDGE_ARTIFACT_LEDGER_ROOT']=prep['ledger_root'];os.environ['PYTHONPATH']=os.pathsep.join(str(ROOT/'packages'/n/'src') for n in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'))
 for k in ('PYTHONEXECUTABLE','PYTHONHOME'):os.environ.pop(k,None)
 request=job['operation_id']+'_nuke' if retry is None else contract_retry['retry_request_id'];operation='nrend-'+hashlib.sha256(request.encode()).hexdigest()[:16];scene=file_record(script)['sha256'];owner='nuke:'+str(script)
 if tail:
  # 最后一票前真实重放受控输入和proof；预检不占资源槽、不启动原生进程。
  from nuke_bridge.operation_receipts import validate_registered_input_contract
  from nuke_bridge.task_host import creative_cold_context
  validate_registered_input_contract(contract);context_value,context_scope,context_source=creative_cold_context()
  if context_scope.binding!=native.binding or context_source!=source or not registry.verify(artifact['artifact_id'])['usable']:raise ValueError('RECT_RENDER_TAIL_INPUT_PREFLIGHT_REQUIRED')
  usage=native.snapshot()
  if usage['dcc_starts']!=(48 if retry is None else 49) or any(t['stopped_at'] is None for t in usage['tickets']):raise ValueError('RECT_RENDER_TAIL_LAST_TICKET_PREFLIGHT_REQUIRED')
  digest_task={'entry':'render_write','task_key':'render_write','node':'Write1','frame_set':[1],'pattern':pattern,'input_binding':input_binding,'background':True,'scene_fingerprint':scene,'project_color':artifact['project_color'],'output_verification':artifact['output_verification'],'input_contract':contract}
  preflight={'schema':'bridge.rectlight-nuke-tail-preflight/1' if retry is None else 'bridge.rectlight-nuke-retry-preflight/1','task_id':prep['task_id'],'operation_id':job['operation_id'],'nuke_operation_id':operation,'scope':native.binding,'source_record':source_record,'script':file_record(script),'context':context,'input_contract_sha256':canonical_sha256(contract),'registered_main_id':artifact['artifact_id'],'registered_main_version':artifact['version'],'native_starts':48 if retry is None else 49,'tickets_sha256':canonical_sha256(usage['tickets']),'request_sha256':cold_request_digest(digest_task),'render_terminal_recovery':prep['render_terminal_recovery']}
  if retry is not None:preflight['nuke_retry_recovery']=retry_recovery
  if prepare_only:return preflight
  expected_preflight=Path(job['directory'])/('render-tail-repair-01/nuke-preflight.json' if retry is None else 'nuke-retry01/nuke-preflight.json')
  if prepared_context is None or Path(prepared_context['path'])!=expected_preflight or json.loads(checked_bytes(prepared_context))!=preflight:raise ValueError('RECT_RENDER_TAIL_PREPARED_INPUTS_CHANGED')
 route=addon.configure_nuke_background_route(nuke_executable=native.scope['hosts']['nuke']['path'],worker_script=str(ROOT/'tools/nuke_owned_render_worker.py'),supervisor_executable=prep['supervisor_python'],software_api=False,
  resource_budget={'roots':[str(native.root)],'max_bytes':native.scope['budget']['max_disk_bytes'],'native_scope':native.binding})
 previous_attempt=None
 if prelaunch_recovery is not None:
  negative=json.loads(checked_bytes(prelaunch_recovery['reconciliation']));previous_attempt=json.loads(checked_bytes(negative['after_render_record']))
  live=file_record(native.root/'state/nuke_renders'/(operation+'.json'))
  if (live['sha256']!=negative['after_render_record']['sha256'] or previous_attempt.get('state')!='FAILED' or previous_attempt.get('dispatch_state')!='NOT_STARTED' or previous_attempt.get('supervisor_intent') is not None or previous_attempt.get('process') is not None or not previous_attempt.get('prelaunch_recovery') or not previous_attempt.get('history')):raise ValueError('RECT_NUKE_CLOSED_ATTEMPT_REQUIRED')
 if prep.get('target_authority') is not None:
  route['resource_budget']['roots']=list(prep['budget_roots'])
 handle=None;task=None;permit=None;unstarted=False
 try:
  permit=addon._NUKE_SCHEDULER.reserve(owner,operation);snapshot=addon._snapshot_nuke_script(operation,str(script))
  if previous_attempt is not None and permit['generation']<=previous_attempt['slot']['generation']:raise ValueError('RECT_NUKE_NEW_LAUNCH_GENERATION_REQUIRED')
  task={'task_id':operation,'owner_task_id':prep['task_id'],'request_id':request,'entry':'render_write','task_key':'render_write','node':'Write1','background':True,'frame_range':[1,1],'frame_set':[1],'stride':1,'active_frames':[1],
   'pattern':pattern,'scene_fingerprint':scene,'script_snapshot':snapshot,'input_contract':contract,'input_binding':input_binding,
   'project_color':artifact['project_color'],'output_verification':artifact['output_verification'],'dependencies':[scene]+artifact['dependencies'],
   'delivery_confirmations':{'colorspace_confirmed':True,'premultiplied_confirmed':True,'dependencies_confirmed':True},'started_at_epoch':time.time(),'cancel_requested':False,'cancel_requested_at':None,'stop_confirmed_at':None,
   'state':'RUNNING','background_backend':'owned','budget_seconds':120,'colorspace':artifact['colorspace'],'premultiplied':artifact['premultiplied'],
   'slot':{'owner_root':owner,'operation_id':operation,'token':permit['token'],'generation':permit['generation']}}
  task['request_sha256']=cold_request_digest(task)
  if previous_attempt is not None:
   if task['request_sha256']!=previous_attempt['request_sha256'] or any(task[k]!=previous_attempt[k] for k in ('input_contract','script_snapshot','scene_fingerprint','pattern')):raise ValueError('RECT_NUKE_ORIGINAL_REQUEST_REQUIRED')
   # 已闭合未启动attempt的历史沿用，新的真实启动用新generation，不抹去负面事实。
   task.update(state=previous_attempt['state'],history=copy.deepcopy(previous_attempt.get('history',[])),previous_attempt=negative['after_render_record'],prelaunch_recovery=copy.deepcopy(previous_attempt.get('prelaunch_recovery')))
   addon._render_history(task,'RUNNING','Continue the same RectLight request after authenticated prelaunch abort; new launch generation.')
  addon._RENDERS[operation]=task;addon._persist_render_record(task);addon._NUKE_SCHEDULER.arm(owner,operation,permit['token'])
  journal.action('nuke_launch_intent',lambda:{'operation_id':operation,'record':file_record(native.root/'state/nuke_renders'/(operation+'.json')),'context':context})
  try:
   launched=addon._launch_owned_render_subprocess(operation,snapshot,'Write1',1,1,pattern=pattern,route=route,frame_set=[1],budget_seconds=120);handle=launched.pop('handle');task['process']=launched
  except Exception as error:
   if getattr(error,'started',None) is False:unstarted=True;raise
   intent=task.get('supervisor_intent');deadline=time.monotonic()+min(40,native.remaining_seconds())
   if not intent:raise
   while time.monotonic()<deadline:
    try:handle=owned_process.OwnedProcessHandle(intent['directory'],intent['identity']);break
    except (ValueError,OSError):time.sleep(.05)
   if handle is None:raise ValueError('CREATIVE_COLD_START_UNKNOWN')
   task['process']={'pid':handle.pid,'kind':'owned_render_subprocess','supervisor_directory':intent['directory'],'supervisor_identity':intent['identity'],**{k:intent[k] for k in ('argv','argv0','worker_result','worker_script')}}
  task.update(backend='owned_subprocess',dispatch_state='launched');addon._RENDER_HANDLES[operation]=handle;addon._NUKE_SCHEDULER.bind_process(owner,operation,permit['token'],task['process']);addon._persist_render_record(task)
  deadline=time.monotonic()+min(120,native.remaining_seconds())
  while handle.poll() is None and time.monotonic()<deadline:time.sleep(.1)
  receipt=handle.receipt()
  if receipt is None or owned_process.execution_returncode(receipt)!=0 or receipt.get('stop_reason') is not None:raise ValueError('CREATIVE_COLD_NATIVE_FAILED')
  worker=addon._verify_owned_worker_receipt(task);actual=worker['write_readback']['settings']
  if actual!={'file':pattern,'colorspace':artifact['colorspace'],'premultiplied':artifact['premultiplied'],'raw':False}:raise ValueError('CREATIVE_COLD_SETTINGS_MISMATCH')
  task['native_output_settings']={'origin':'nuke_write_readback','class':'Write','node':'Write1','pattern':pattern,'scene_fingerprint':scene,'colorspace':actual['colorspace'],'premultiplied':actual['premultiplied'],'raw':False,'operation_id':operation,'request_id':request};addon._persist_render_record(task)
  completed=journal.action('nuke_completed',lambda:addon.nuke_render_status(operation))
  if completed['state']!='COMPLETED' or completed.get('ledger_state')!='REGISTERED':raise ValueError('CREATIVE_COLD_TYPED_REGISTRATION_REQUIRED')
  assert_released_slot(Path(prep['scope']['path']).parent/'scheduler',operation)
  result=registry.lookup('nuke-render-'+operation)
  if result is None or not registry.verify(result['artifact_id'])['usable']:raise ValueError('CREATIVE_NUKE_ARTIFACT_UNUSABLE')
  return {'operation_id':operation,'artifact':result,'formal_operation_receipt':addon._nuke_operation_fact(operation)['formal_receipt'],'files':{'nk':file_record(script),'exr':file_record(Path(pattern%1))}}
 finally:
  if permit is not None:cleanup_cold_attempt(native,operation,task,handle,addon._NUKE_SCHEDULER,dict(permit,owner_root=owner),unstarted)






def resume_nuke_retry(job_path,preparation_path,*,prepare_only=False):
 """49号失败保留；只消费已登记v2，独立输入预检后执行一次正常Nuke重试。"""
 from vfx_pipeline.creative_results import nuke_retry_inputs,validate_nuke_retry_result,completed_registry,validate_nuke_completion
 from houdini_bridge.official_karma import compare_files
 from run_alpha_calibration import ScopeBudget
 preparation=file_record(preparation_path);job_record=file_record(job_path);job=json.loads(checked_bytes(job_record));directory=Path(job['directory']);inputs=nuke_retry_inputs(directory,preparation);prep=inputs['preparation'];native=inputs['native'];before=inputs['usage'];contract=inputs['contract'];old=inputs['tail_inputs']
 if (ROOT!=Path(prep['runtime_control'])/'snapshot' or job_record!=contract['source_job'] or before['dcc_starts']!=49 or any(t['stopped_at'] is None for t in before['tickets']) or (directory/'result.json').exists()):raise ValueError('RECT_NUKE_RETRY_PREPARED_ENTRY_REQUIRED')
 native.check();os.environ.clear();os.environ.update(prep['environment']);control=directory/'project/control';project=directory/'project';source_record=contract['source_input'];source=json.loads(checked_bytes(source_record));tail=json.loads(checked_bytes(contract['source_tail_journal']));artifact=tail['stages']['register']['result']
 registry=completed_registry(source,native,prep['task_id']);registry.verify_operation_receipt(artifact['registry_operation_receipt'])
 if registry.lookup(artifact['artifact_id'])!=artifact or not registry.verify(artifact['artifact_id'])['usable']:raise ValueError('RECT_NUKE_RETRY_EXISTING_V2_REQUIRED')
 root=directory/'nuke-retry01';root.mkdir(exist_ok=True);journal=Journal(root,Path(preparation_path))
 if journal.value['stages']:raise ValueError('RECT_NUKE_RETRY_QUERY_EXISTING_ATTEMPT_REQUIRED')
 jobprep=load(directory/'job-preparation.json');preflight_path=root/'nuke-preflight.json'
 if prepare_only:
  preflight=cold_consume(prep,job,jobprep,source_record,journal,prepare_only=True,retry_recovery=prep['nuke_retry_recovery'])
  if preflight_path.exists():
   if json.loads(checked_bytes(file_record(preflight_path)))!=preflight:raise ValueError('RECT_NUKE_RETRY_PREFLIGHT_CHANGED')
   record=file_record(preflight_path)
  else:record=write_new(preflight_path,preflight)
  after=native.snapshot()
  if after['tickets']!=before['tickets']:raise ValueError('RECT_NUKE_RETRY_PREPARE_STARTED_NATIVE')
  print(json.dumps({'state':'PREFLIGHT_READY','preflight':record,'native_starts_added':0,'effective_phase_starts':native.effective_creative_starts()}));return
 budget=ScopeBudget(prep['scope']['path']);budget.limits=dict(native.scope['budget']);budget.available(starts=1)
 nuke=cold_consume(prep,job,jobprep,source_record,journal,prepared_context=file_record(preflight_path),retry_recovery=prep['nuke_retry_recovery'])
 compared=compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True)
 if compared['state']!='PASS':raise ValueError('RECT_NUKE_RETRY_PIXEL_MISMATCH')
 preview=write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview.png',prep['display'])
 for rec in prep['protected_files'].values():checked_bytes(rec)
 # 旧49的NK/EXR/context/stop保持同身份，不能用新输出覆盖旧失败。
 validate_retry=__import__('vfx_pipeline.creative_results',fromlist=['validate_nuke_retry_recovery']).validate_nuke_retry_recovery
 validate_retry(prep['nuke_retry_recovery'],native)
 usage=native.snapshot();saved=old['stages']['formal_save']['result'];changed=old['checkpoint_inputs']['stages']['feedback']['result'];original=directory.parent.parent;route=original/'execution-continuation-nuke-retry01.json';source_prep=old['source_preparation']
 result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],'revision':2,'exposure':job['plan']['exposure'],
  'plan':job['plan'],'feedback':changed,'saved':saved,'artifact':artifact,'nuke':nuke,'comparison':compared,'preview':preview,'control':str(control),
  'save_sidecars':[file_record(x) for x in (control/'houdini-instances/fx_operations').glob('*.saves.json')],
  'files':{'hip':file_record(saved['path']),'main':file_record(project/'saves/main.0001.exr'),'nk':nuke['files']['nk'],'nuke':nuke['files']['exr']},
  'model_route':prep['model_route'],'scope':usage,'phase_starts':usage['dcc_starts']-prep['initial_starts'],'phase_seconds':usage['total_seconds']-prep['initial_seconds'],'native_phase_limit':{'starts':native.effective_creative_starts(),'seconds':1800},'provider_identity':'unknown','human_visual_acceptance':'PENDING','case_id':prep['case_id'],'case_variant':prep['case_variant'],
  'saved_checkpoint_recovery':{'schema':'bridge.rectlight-saved-checkpoint-result/1','original_recovery':source_prep['saved_checkpoint_recovery'],'continuation':file_record(original/'execution-continuation-storage-repair.json'),'preparation':old['source_preparation_record'],'pre_native_storage_refusal':source_prep['pre_native_storage_refusal']},
  'render_terminal_recovery':{'schema':'bridge.rectlight-render-tail-source/1','proof':prep['render_terminal_recovery'],'source_preparation':contract['source_preparation'],'source_tail_journal':contract['source_tail_journal'],'source_job':contract['source_job'],'source_journal':old['source_journal']},
  'nuke_retry_recovery':{'schema':'bridge.rectlight-nuke-retry-result/1','contract':prep['nuke_retry_recovery'],'preparation':preparation,'retry_journal':file_record(journal.path),'source_tail_journal':contract['source_tail_journal'],'continuation':file_record(route),'failed_attempt':contract['failed_closure'],'native_reexecuted':['nuke-render']}}
 validate_nuke_retry_result(directory,result,preparation);validate_nuke_completion(registry,result,native);publish_result(directory/'result.json',result)
 print(json.dumps({'state':'COMPLETE','operation_id':job['operation_id'],'normal_retry_operation_id':nuke['operation_id'],'family_starts':usage['dcc_starts']}))

def resume_render_tail(job_path,preparation_path,*,prepare_only=False):
 """只续已验证原生终端后的verify/登记/Nuke；先零原生预检，再花最后一票。"""
 from vfx_pipeline.creative_results import render_tail_inputs,validate_render_tail_result
 from vfx_pipeline.official_graph_resume import resume_graph_facade,_snapshot
 from vfx_pipeline.artifact_registry import ArtifactRegistry
 from vfx_pipeline.feedback_versions import FeedbackVersions
 from houdini_bridge.official_karma import compare_files
 from run_alpha_calibration import ScopeBudget
 job_record=file_record(job_path);preparation=file_record(preparation_path);job=json.loads(checked_bytes(job_record));directory=Path(job['directory']);inputs=render_tail_inputs(directory,preparation);prep=inputs['preparation'];native=inputs['native'];before=inputs['usage']
 if (job_record!=inputs['job_record'] or ROOT!=Path(prep['runtime_control'])/'snapshot' or before['dcc_starts']!=48 or any(t['stopped_at'] is None for t in before['tickets'])):raise ValueError('RECT_RENDER_TAIL_PREPARED_ENTRY_REQUIRED')
 if (directory/'result.json').exists():raise ValueError('RECT_RENDER_TAIL_QUERY_EXISTING_RESULT_REQUIRED')
 native.check();os.environ.clear();os.environ.update(prep['environment'])
 control=directory/'project/control';project=directory/'project';source_prep=inputs['source_preparation'];source_native=inputs['source_native'];oldstages=inputs['stages'];saved=oldstages['formal_save']['result'];changed=inputs['checkpoint_inputs']['stages']['feedback']['result']
 journal_root=directory/'render-tail-repair-01';journal_root.mkdir(exist_ok=True);journal=Journal(journal_root,Path(preparation_path));verify_id='creative_bff6f898fafe1db03aae_terminal_verify'
 done=journal.value['stages']
 if any(v.get('state')!='DONE' for v in done.values()) or set(done) not in (set(),{'verify'},{'verify','register'}):raise ValueError('RECT_RENDER_TAIL_QUERY_EXISTING_JOURNAL_REQUIRED')
 if not prepare_only and set(done)!={'verify','register'}:raise ValueError('RECT_RENDER_TAIL_ZERO_NATIVE_PREFLIGHT_REQUIRED')
 owners=json.loads((control/'host-state/houdini-operation-owners.json').read_text());owner=owners.get(verify_id)
 if (not isinstance(owner,dict) or owner.get('render_terminal_recovery')!=prep['render_terminal_recovery'] or owner.get('historical_scope')!=file_record(source_native.path)):
  raise ValueError('RECT_RENDER_TAIL_TRUSTED_OWNER_INSTALL_REQUIRED')
 registry=ArtifactRegistry(prep['ledger_root']);pattern=str(project/'saves/main.%04d.exr')
 with resume_graph_facade(control/'run.json',prep['source_graph'],repo_root=control/'snapshot',scheduler_root=source_native.path.parent/'scheduler') as f:
  # 任何意外现场宿主调用都失败；允许的两个命令仅走正常detached verification分支。
  def no_host_activation():raise ValueError('RECT_RENDER_TAIL_NATIVE_HOST_FORBIDDEN')
  f.host_client._activate=no_host_activation;f.nuke_client._activate=no_host_activation
  f.artifact_registry=registry;f.host_client.bind_artifact_registry(registry);f.save_root=project/'saves'
  if FeedbackVersions(f).current(prep['source_graph']['graph_id']).get('version')!=2:raise ValueError('RECT_RENDER_TAIL_FEEDBACK_TWO_REQUIRED')
  if 'verify' in done:
   verified=f.operation_query(verify_id)
   previous=done['verify']['result']
   if verified.get('execution_fact')!=previous.get('execution_fact') or verified.get('verification_basis')!='controlled_output_v1':raise ValueError('RECT_RENDER_TAIL_VERIFICATION_CHANGED')
   verified=previous
  else:verified=journal.action('verify',lambda:f.verify_render_output(verify_id,oldstages['render']['result']['operation_id']))
  fact=verified['execution_fact']
  if fact.get('state')!='COMPLETED' or fact.get('render_terminal_recovery')!=prep['render_terminal_recovery']:raise ValueError('RECT_RENDER_TAIL_CONTROLLED_FACT_REQUIRED')
  image=fact['metadata']['1']
  if 'register' in done:
   artifact=done['register']['result'];registry.verify_operation_receipt(artifact['registry_operation_receipt'])
   if registry.lookup(artifact['artifact_id'])!=artifact or not registry.verify(artifact['artifact_id'])['usable']:raise ValueError('RECT_RENDER_TAIL_REGISTRATION_CHANGED')
  else:artifact=journal.action('register',lambda:f.register_render_artifact(prep['main_artifact_id'],'preview_temp',pattern,[1],image['colorspace'],image['premultiplied'],verify_id))
  if artifact['version']!=2:raise ValueError('RECT_RENDER_TAIL_MAIN_VERSION_TWO_REQUIRED')
  source={'schema':'bridge.creative-nuke-source/1','task_id':prep['task_id'],'artifact_id':artifact['artifact_id'],'artifact_version':artifact['version'],
   'creative_phase':source_native.scope['creative_phase'],'producer_scope':file_record(source_native.path),'producer_control':str(control),'producer_ledger':prep['ledger_root'],
   'producer_manifest':file_record(control/'run.json'),'producer_snapshot_manifest':file_record(control/'snapshot-manifest.json'),
   'producer_deployment':file_record(control/'production-hosts.json'),'producer_owners':file_record(control/'host-state/houdini-operation-owners.json'),
   'registry_operation_receipt':artifact['registry_operation_receipt'],'producer_fact_sha256':canonical_sha256(fact),'case_id':prep['case_id'],'case_variant':prep['case_variant'],'render_terminal_recovery':prep['render_terminal_recovery']}
  source_path=control/'creative-input-source.json'
  if source_path.exists():
   source_record=file_record(source_path)
   if json.loads(checked_bytes(source_record))!=source:raise ValueError('RECT_RENDER_TAIL_SOURCE_CHANGED')
  else:source_record=write_new(source_path,source)
 jobprep=load(directory/'job-preparation.json');preflight_path=journal_root/'nuke-preflight.json'
 if prepare_only:
  preflight=cold_consume(prep,job,jobprep,source_record,journal,prepare_only=True)
  if preflight_path.exists():
   if json.loads(checked_bytes(file_record(preflight_path)))!=preflight:raise ValueError('RECT_RENDER_TAIL_PREFLIGHT_CHANGED')
   record=file_record(preflight_path)
  else:record=write_new(preflight_path,preflight)
  after=native.snapshot()
  if after['tickets']!=before['tickets']:raise ValueError('RECT_RENDER_TAIL_PREPARE_STARTED_NATIVE')
  print(json.dumps({'state':'PREFLIGHT_READY','operation_id':job['operation_id'],'preflight':record,'native_starts_added':0}));return
 budget=ScopeBudget(prep['scope']['path']);budget.limits=dict(native.scope['budget']);budget.available(starts=1)
 nuke=cold_consume(prep,job,jobprep,source_record,journal,prepared_context=file_record(preflight_path))
 compared=compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True)
 if compared['state']!='PASS':raise ValueError('RECT_RENDER_TAIL_NUKE_PIXEL_MISMATCH')
 preview=write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview.png',prep['display'])
 for record in prep['protected_files'].values():checked_bytes(record)
 usage=native.snapshot()
 if usage['dcc_starts']!=49 or usage['tickets'][:48]!=before['tickets'] or usage['tickets'][-1]['role']!='nuke-render' or any(t['stopped_at'] is None for t in usage['tickets']):raise ValueError('RECT_RENDER_TAIL_ONLY_NUKE_STOP_REQUIRED')
 original=directory.parent.parent;route=original/'execution-continuation-render-tail.json'
 result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],'revision':2,'exposure':job['plan']['exposure'],
  'plan':job['plan'],'feedback':changed,'saved':saved,'artifact':artifact,'nuke':nuke,'comparison':compared,'preview':preview,'control':str(control),
  'save_sidecars':[file_record(x) for x in (control/'houdini-instances/fx_operations').glob('*.saves.json')],
  'files':{'hip':file_record(saved['path']),'main':file_record(project/'saves/main.0001.exr'),'nk':nuke['files']['nk'],'nuke':nuke['files']['exr']},
  'model_route':prep['model_route'],'scope':usage,'phase_starts':usage['dcc_starts']-prep['initial_starts'],'phase_seconds':usage['total_seconds']-prep['initial_seconds'],'provider_identity':'unknown','human_visual_acceptance':'PENDING','case_id':prep['case_id'],'case_variant':prep['case_variant'],
  'saved_checkpoint_recovery':{'schema':'bridge.rectlight-saved-checkpoint-result/1','original_recovery':source_prep['saved_checkpoint_recovery'],'continuation':file_record(original/'execution-continuation-storage-repair.json'),'preparation':inputs['source_preparation_record'],'pre_native_storage_refusal':source_prep['pre_native_storage_refusal']},
  'render_terminal_recovery':{'schema':'bridge.rectlight-render-tail-result/1','proof':prep['render_terminal_recovery'],'preparation':preparation,'source_job':inputs['job_record'],'source_journal':inputs['source_journal'],'tail_journal':file_record(journal.path),'continuation':file_record(route),'native_reexecuted':['nuke-render'],'source_scope':file_record(source_native.path)}}
 validate_render_tail_result(directory,result,preparation)
 from vfx_pipeline.creative_results import completed_registry,validate_nuke_completion
 final_registry=completed_registry(source,native,prep['task_id']);validate_nuke_completion(final_registry,result,native)
 publish_result(directory/'result.json',result)
 print(json.dumps({'state':'COMPLETE','operation_id':job['operation_id'],'only_native_role':'nuke-render','artifact_version':2}))

def resume_saved_checkpoint_job(job_path):
 """第二轮只冷开已写检查点并重新正式保存；不重放曝光修改或原保存INTENT。"""
 from vfx_pipeline.creative_results import saved_checkpoint_inputs,validate_saved_checkpoint_result
 from vfx_pipeline.feedback_versions import FeedbackVersions
 from houdini_bridge.official_case_variant import verified_reopen_parameters
 from houdini_bridge.official_karma_feedback import EXPOSURE,GATE
 from houdini_bridge.official_karma import compare_files
 from vfx_pipeline.official_graph_resume import _snapshot
 from run_controlled_engineering import _stop_host
 from run_alpha_calibration import ScopeBudget
 job_record=file_record(job_path);job=json.loads(checked_bytes(job_record));directory=Path(job['directory']);preparation=job['preparation'];prep=json.loads(checked_bytes(preparation))
 original=directory.parent.parent;inputs=saved_checkpoint_inputs(original,preparation);native=inputs['native'];before=inputs['usage']
 if directory!=original/('executions/save-repair-02' if prep.get('pre_native_storage_refusal') is not None else 'executions/save-repair-01') or job.get('operation_id')!=inputs['job']['operation_id'] or job.get('plan')!=inputs['job']['plan'] or before['dcc_starts']!=45 or any(t['stopped_at'] is None for t in before['tickets']):raise ValueError('RECT_CHECKPOINT_EXECUTION_JOB_REQUIRED')
 jobprep=load(directory/'job-preparation.json');oldjobprep=load(original/'job-preparation.json');control=directory/'project/control';project=directory/'project'
 expected_sidecars=[file_record(x) for x in (original/'project/control/houdini-instances/fx_operations').glob('*.saves.json')]
 if (jobprep.get('control')!=str(control) or jobprep.get('project')!=str(project) or jobprep.get('history_control')!=str(original/'project/control')
     or jobprep.get('saved_source')!=oldjobprep.get('saved_source') or jobprep.get('previous')!=oldjobprep.get('previous') or jobprep.get('save_sidecars')!=expected_sidecars):raise ValueError('RECT_CHECKPOINT_EXECUTION_CONTROL_REQUIRED')
 _snapshot(control)
 if ROOT!=control/'snapshot':
  if ROOT!=Path(prep['runtime_control'])/'snapshot':raise ValueError('RECT_CHECKPOINT_PREPARED_WORKER_REQUIRED')
  child=__import__('subprocess').run([prep['supervisor_python'],'-I','-B',str(control/'snapshot/tools/run_hy3_creative.py'),'resume-saved-checkpoint-job','--job',str(job_path)],cwd=str(directory))
  if child.returncode:raise RuntimeError('RECT_CHECKPOINT_EXECUTION_FAILED')
  return
 budget=ScopeBudget(prep['scope']['path']);budget.limits=dict(native.scope['budget']);budget.available(starts=4)
 os.environ.clear();os.environ.update(prep['environment']);journal=Journal(directory,Path(job_path))
 if journal.value['stages']:raise ValueError('RECT_CHECKPOINT_QUERY_EXISTING_EXECUTION_REQUIRED')
 configuration=json.loads(checked_bytes(prep['configuration']));changed=inputs['stages']['feedback']['result'];prefix=job['operation_id']
 data={'root':native.root,'project':project,'control':control,'scope_path':native.path,'scope_sha256':native.binding['sha256']}
 try:
  with _job_facade(prep,jobprep) as f:
   current=FeedbackVersions(f).current(prep['source_graph']['graph_id'])
   if current.get('version')!=2 or current.get('state')!='COMPLETE' or current.get('after')!=changed['after']:raise ValueError('RECT_CHECKPOINT_FEEDBACK_DATABASE_REQUIRED')
   # 此描述携带真实旧INTENT，仅用于比较加载后的字节/合同和不同宿主nonce；不是正式保存收据。
   descriptor=dict(inputs['checkpoint'],operation_receipt=inputs['intent'])
   reopened=journal.action('checkpoint_reopen',lambda:f.host_client.call('scene.reopen_task_hip',{'path':descriptor['path'],'sha256':descriptor['sha256'],'task_id':prep['task_id']}))
   def checkpoint_readback():
    actual=verified_reopen_parameters(reopened,descriptor,configuration,f.host_client.production_config['expected_identity'],[EXPOSURE,GATE])
    return dict(actual,checkpoint_validation_only=True,source_save_state='INTENT')
   actual=journal.action('checkpoint_readback',checkpoint_readback)
   if actual['parms']!=changed['after']:raise ValueError('RECT_CHECKPOINT_ACTUAL_PARAMETER_MISMATCH')
   saved=journal.action('formal_save',f.task_save)
   if saved['path']==descriptor['path'] or saved.get('operation_receipt',{}).get('state')!='COMPLETED':raise ValueError('RECT_CHECKPOINT_NEW_FORMAL_SAVE_REQUIRED')
   journal.action('save_host_stop',lambda:_stop_host(data,'houdini'))
  with _job_facade(prep,jobprep) as f:
   f._save_receipt(saved);reopened=journal.action('cold_reopen',lambda:f.task_reopen(saved['saved_scene_id']))
   actual=journal.action('cold_readback',lambda:verified_reopen_parameters(reopened,saved,configuration,f.host_client.production_config['expected_identity'],[EXPOSURE,GATE]))
   if actual['parms']!=changed['after']:raise ValueError('RECT_CHECKPOINT_FORMAL_COLD_PARAMETER_MISMATCH')
   roles={n['role']:n['path'] for n in saved['scene_contract']['nodes']};pattern=str(project/'saves/main.%04d.exr')
   def render():
    value=f.host_client.call('render.start',{'task_id':prep['task_id'],'request_id':prefix+'_render','render_target':roles['render'],'output_pattern':pattern,'frames':[1],'budget_seconds':min(120,budget.remaining()),'dependencies':FeedbackVersions(f).dependencies()})
    f._register_operation(value['operation_id'],'houdini-render','houdini',prefix+'_render');return {'operation_id':value['operation_id']}
   rendered=journal.action('render',render);journal.action('render_completed',lambda:_poll(f,'operation_query',rendered['operation_id'],('operation','state'),budget))
   journal.action('render_host_stop',lambda:_stop_host(data,'houdini'))
   verified=journal.action('verify',lambda:f.verify_render_output(prefix+'_verify',rendered['operation_id']));image=verified['execution_fact']['metadata']['1']
   artifact=journal.action('register',lambda:f.register_render_artifact(prep['main_artifact_id'],'preview_temp',pattern,[1],image['colorspace'],image['premultiplied'],prefix+'_verify'))
   if artifact['version']!=2:raise ValueError('RECT_CHECKPOINT_MAIN_VERSION_TWO_REQUIRED')
   source={'schema':'bridge.creative-nuke-source/1','task_id':prep['task_id'],'artifact_id':artifact['artifact_id'],'artifact_version':artifact['version'],
    'creative_phase':native.scope['creative_phase'],'producer_scope':file_record(native.path),'producer_control':str(control),'producer_ledger':prep['ledger_root'],
    'producer_manifest':file_record(control/'run.json'),'producer_snapshot_manifest':file_record(control/'snapshot-manifest.json'),
    'producer_deployment':file_record(control/'production-hosts.json'),'producer_owners':file_record(control/'host-state/houdini-operation-owners.json'),
    'registry_operation_receipt':artifact['registry_operation_receipt'],'producer_fact_sha256':canonical_sha256(verified['execution_fact']),'case_id':prep['case_id'],'case_variant':prep['case_variant']}
   source_record=write_new(control/'creative-input-source.json',source);nuke=cold_consume(prep,job,jobprep,source_record,journal)
   compared=compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True)
   if compared['state']!='PASS':raise ValueError('RECT_CHECKPOINT_NUKE_PIXEL_MISMATCH')
   preview=write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview.png',prep['display'])
   for rec in prep['protected_files'].values():checked_bytes(rec)
   usage=native.snapshot()
   if usage['dcc_starts']!=49 or usage['tickets'][:45]!=before['tickets'] or any(t['stopped_at'] is None for t in usage['tickets']):raise ValueError('RECT_CHECKPOINT_EXACT_FOUR_NATIVE_STOPS_REQUIRED')
   result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':prefix,'revision':2,'exposure':job['plan']['exposure'],
    'plan':job['plan'],'feedback':changed,'saved':saved,'artifact':artifact,'nuke':nuke,'comparison':compared,'preview':preview,'control':str(control),
    'save_sidecars':[file_record(x) for x in (control/'houdini-instances/fx_operations').glob('*.saves.json')],
    'files':{'hip':file_record(saved['path']),'main':file_record(project/'saves/main.0001.exr'),'nk':nuke['files']['nk'],'nuke':nuke['files']['exr']},
    'model_route':prep['model_route'],'scope':usage,'phase_starts':usage['dcc_starts']-prep['initial_starts'],'phase_seconds':usage['total_seconds']-prep['initial_seconds'],'provider_identity':'unknown','human_visual_acceptance':'PENDING','case_id':prep['case_id'],'case_variant':prep['case_variant'],
    'saved_checkpoint_recovery':{'schema':'bridge.rectlight-saved-checkpoint-result/1','original_recovery':inputs['repair'],'continuation':file_record(original/('execution-continuation-storage-repair.json' if prep.get('pre_native_storage_refusal') is not None else 'execution-continuation.json')),'preparation':preparation,**({'pre_native_storage_refusal':prep['pre_native_storage_refusal']} if prep.get('pre_native_storage_refusal') is not None else {})}}
   validate_saved_checkpoint_result(directory,result,preparation);publish_result(directory/'result.json',result)
 finally:
  try:_stop_host(data,'houdini')
  except Exception:pass

def resume_nuke_job(job_path,preparation_path):
 """原Rect首轮只续一次尚未启动的Nuke；HIP、Karma及主登记直接沿用真实完成检查点。"""
 from vfx_pipeline.creative_results import nuke_prelaunch_inputs,validate_nuke_prelaunch_recovery,completed_registry,validate_nuke_completion
 from houdini_bridge.official_karma import compare_files
 from vfx_pipeline.official_graph_resume import _snapshot
 job_record=file_record(job_path);preparation=file_record(preparation_path);directory=Path(job_path).parent
 inputs=nuke_prelaunch_inputs(directory,preparation);prep=inputs['preparation'];job=inputs['job'];native=inputs['native'];before=inputs['usage']
 if job_record!=inputs['repair']['original_job'] or ROOT!=Path(prep['runtime_control'])/'snapshot' or before['dcc_starts']!=43:
  raise ValueError('RECT_NUKE_RESUME_PREPARED_WORKER_REQUIRED')
 if (directory/'result.json').exists():raise ValueError('RECT_NUKE_QUERY_EXISTING_RESULT_REQUIRED')
 native.check();jobprep=load(directory/'job-preparation.json');control=Path(jobprep['control']);project=Path(jobprep['project']);_snapshot(control)
 source=json.loads(checked_bytes(inputs['source_record']));registry=completed_registry(source,native,prep['task_id'])
 artifact=inputs['stages']['register']['result'];registry.verify_operation_receipt(artifact['registry_operation_receipt'])
 if registry.lookup(artifact['artifact_id'])!=artifact or not registry.verify(artifact['artifact_id'])['usable']:raise ValueError('RECT_NUKE_REUSED_MAIN_UNUSABLE')
 os.environ.clear();os.environ.update(prep['environment'])
 recovery_root=directory/'nuke-resume-01';recovery_root.mkdir(exist_ok=True);journal=Journal(recovery_root,Path(preparation_path))
 if journal.value['stages']:raise ValueError('RECT_NUKE_QUERY_EXISTING_RESUME_REQUIRED')
 nuke=cold_consume(prep,job,jobprep,inputs['source_record'],journal,prelaunch_recovery=inputs['repair'])
 compared=compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True)
 if compared['state']!='PASS':raise ValueError('RECT_NUKE_RESUME_PIXEL_MISMATCH')
 preview=write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview.png',prep['display'])
 for item in prep['protected_files'].values():checked_bytes(item)
 after=native.snapshot();saved=inputs['stages']['save']['result'];changed=inputs['stages']['feedback']['result']
 if after['dcc_starts']!=44 or after['tickets'][:43]!=before['tickets'] or any(t['stopped_at'] is None for t in after['tickets']):raise ValueError('RECT_NUKE_ONLY_ONE_NATIVE_START_REQUIRED')
 result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],'revision':1,'exposure':job['plan']['exposure'],
  'plan':job['plan'],'feedback':changed,'saved':saved,'artifact':artifact,'nuke':nuke,'comparison':compared,'preview':preview,'control':str(control),
  'save_sidecars':[file_record(p) for p in (control/'houdini-instances/fx_operations').glob('*.saves.json')],
  'files':{'hip':file_record(saved['path']),'main':file_record(project/'saves/main.0001.exr'),'nk':nuke['files']['nk'],'nuke':nuke['files']['exr']},
  'model_route':prep['model_route'],'scope':after,'phase_starts':after['dcc_starts']-prep['initial_starts'],'phase_seconds':after['total_seconds']-prep['initial_seconds'],'provider_identity':'unknown','human_visual_acceptance':'PENDING',
  'case_id':prep['case_id'],'case_variant':prep['case_variant'],
  'nuke_prelaunch_recovery':dict(inputs['repair'],schema='bridge.rectlight-nuke-prelaunch-recovery/1',original_preparation=job['preparation'],recovery_preparation=preparation,recovery_journal=file_record(journal.path))}
 validate_nuke_prelaunch_recovery(directory,result,preparation);validate_nuke_completion(registry,result,native)
 publish_result(directory/'result.json',result)
 print(json.dumps({'state':'COMPLETE','operation_id':job['operation_id'],'only_native_role':'nuke-render','artifact_version':1}))

def finalize_job(job_path,preparation_path):
 """只修复全部原生已完成后的临时USD清单错误，绝不重跑原生操作。"""
 from vfx_pipeline.creative_results import completed_registry,require_completed_journal,validate_postprocess_repair,validate_nuke_completion
 from vfx_pipeline.official_graph_resume import _snapshot
 from houdini_bridge.official_karma import compare_files
 job_record=file_record(job_path);job=json.loads(checked_bytes(job_record));oldprep=json.loads(checked_bytes(job['preparation']))
 preparation=file_record(preparation_path);prep=json.loads(checked_bytes(preparation));directory=Path(job['directory']);jobprep=load(directory/'job-preparation.json')
 if ROOT!=Path(prep['runtime_control'])/'snapshot' or _snapshot(Path(prep['runtime_control']))!=prep['runtime_snapshot_manifest']:
  raise ValueError('CREATIVE_FINALIZE_SNAPSHOT_REQUIRED')
 stages=require_completed_journal(directory,job_record);native=NativeScope(prep['scope']);before=native.snapshot()
 if any(t['stopped_at'] is None for t in before['tickets']):raise ValueError('CREATIVE_FINALIZE_STOPS_REQUIRED')
 control=Path(jobprep['control']);project=Path(jobprep['project']);_snapshot(control)
 source=load(control/'creative-input-source.json');registry=completed_registry(source,native,prep['task_id'])
 artifact=registry.lookup(source['artifact_id']);registry.verify_operation_receipt(stages['register']['result']['registry_operation_receipt'])
 if artifact['version']!=2+job['plan']['revision'] or not registry.verify(artifact['artifact_id'])['usable']:raise ValueError('CREATIVE_FINALIZE_MAIN_REQUIRED')
 saved=stages['save']['result'];changed=stages['feedback']['result'];hip=file_record(Path(saved['path']))
 if hip['sha256']!=saved['sha256'] or stages['cold_readback']['result']['parms']!=changed['after']:raise ValueError('CREATIVE_FINALIZE_SAVED_REQUIRED')
 operation=stages['nuke_launch_intent']['result']['operation_id'];nuke_artifact=registry.lookup('nuke-render-'+operation)
 nuke={'operation_id':operation,'artifact':nuke_artifact,'files':{'nk':file_record(project/'saves/composite.nk'),'exr':file_record(project/'saves/nuke.0001.exr')}}
 compared=compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True)
 if compared['state']!='PASS':raise ValueError('CREATIVE_FINALIZE_PIXELS_REQUIRED')
 preview=write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview-finalized.png',prep['display'])
 if file_record(project/'saves/preview.png')['sha256']!=preview['preview']['sha256']:raise ValueError('CREATIVE_FINALIZE_DISPLAY_REQUIRED')
 for item in prep['protected_files'].values():checked_bytes(item)
 after=native.snapshot()
 if {k:v for k,v in after.items() if k!='disk_bytes'}!={k:v for k,v in before.items() if k!='disk_bytes'}:raise ValueError('CREATIVE_FINALIZE_ACCOUNTING_CHANGED')
 result={'schema':'bridge.hy3-creative-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],'revision':job['plan']['revision'],'exposure':job['plan']['exposure'],
  'plan':job['plan'],'feedback':changed,'saved':saved,'artifact':artifact,'nuke':nuke,'comparison':compared,'preview':preview,'control':str(control),
  'save_sidecars':[file_record(p) for p in (control/'houdini-instances/fx_operations').glob('*.saves.json')],
  'files':{'hip':hip,'main':file_record(project/'saves/main.0001.exr'),'nk':nuke['files']['nk'],'nuke':nuke['files']['exr']},
  'model_route':prep['model_route'],'scope':after,'phase_starts':after['dcc_starts']-prep['initial_starts'],'phase_seconds':after['total_seconds']-prep['initial_seconds'],'provider_identity':'unknown','human_visual_acceptance':'PENDING',
  'postprocess_repair':{'schema':'bridge.creative-postprocess-repair/1','original_error':file_record(directory/'error.json'),'original_job':job_record,'original_preparation':job['preparation'],'journal':file_record(directory/'incremental-state.json'),'finalize_preparation':preparation,'native_reexecuted':False}}
 validate_postprocess_repair(directory,result,preparation);result['nuke']['formal_operation_receipt']=validate_nuke_completion(registry,result,native)
 publish_result(directory/'result.json',result)
 print(json.dumps({'state':'COMPLETE','operation_id':job['operation_id'],'native_reexecuted':False,'artifact_version':artifact['version']}))


def main():
 parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
 p=sub.add_parser('prepare');p.add_argument('--recovery-delivery',required=True);p.add_argument('--namespace',required=True);p.add_argument('--instruction',required=True);p.add_argument('--route',choices=('workbuddy-hy3','gpt-luna-low'),default='workbuddy-hy3')
 for name in ('finalize-job','resume-nuke-job'):
  p=sub.add_parser(name);p.add_argument('--job',required=True);p.add_argument('--preparation',required=True)
 for name in ('resume-render-tail','resume-nuke-retry'):
  p=sub.add_parser(name);p.add_argument('--job',required=True);p.add_argument('--preparation',required=True);p.add_argument('--prepare-only',action='store_true')
 for name in ('run-job','execute-job','resume-saved-checkpoint-job'):
  p=sub.add_parser(name);p.add_argument('--job',required=True)
 args=parser.parse_args()
 if args.command=='prepare':print(json.dumps(prepare(args.recovery_delivery,args.namespace,args.instruction,args.route),ensure_ascii=False,indent=2))
 else:
  try:
   if args.command=='finalize-job':finalize_job(Path(args.job),Path(args.preparation))
   elif args.command=='resume-nuke-job':resume_nuke_job(Path(args.job),Path(args.preparation))
   elif args.command=='resume-saved-checkpoint-job':resume_saved_checkpoint_job(Path(args.job))
   elif args.command=='resume-render-tail':resume_render_tail(Path(args.job),Path(args.preparation),prepare_only=args.prepare_only)
   elif args.command=='resume-nuke-retry':resume_nuke_retry(Path(args.job),Path(args.preparation),prepare_only=args.prepare_only)
   else:(run_job if args.command=='run-job' else execute_job)(Path(args.job))
  except BaseException as error:
   path=Path(args.job).parent/'error.json'
   if not path.exists():publish_result(path,{'code':type(error).__name__,'message':str(error),'native_success_claimed':False})
   raise
if __name__=='__main__':main()
