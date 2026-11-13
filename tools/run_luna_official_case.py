#!/usr/bin/env python3
"""受控复用既有DiskLight工程，准备官方RectLight基线并交由真实Luna创作。"""
from __future__ import annotations
import argparse,copy,ctypes,hashlib,json,os,secrets,sys,time,uuid
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from houdini_bridge.official_karma_observation import checked_bytes,file_record,write_new
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_case_variant import CASE_ID,CHANGES,LIGHT,USD,inspect_contract,validate_contract
from continue_official_karma import _runtime_environment,Journal,_poll

def load(path):return json.loads(Path(path).read_text())
def bind(record):return {k:record[k] for k in ('path','sha256')}
def resource(native):return {'roots':[str(native.root)],'max_bytes':native.scope['budget']['max_disk_bytes'],'native_scope':native.binding}

def prepare(delivery_path,namespace,instruction):
    """零DCC创建固定案例、来源和范围；旧工程及账本完全只读。"""
    from prepare_workbuddy_graph import prepare_graph
    from houdini_bridge.official_karma_templates import sealed_source_hip
    from houdini_bridge.alpha_reuse import make_reuse_binding
    from vfx_pipeline.artifact_registry import ArtifactRegistry
    delivery_record=file_record(Path(delivery_path));delivery=json.loads(checked_bytes(delivery_record))
    latest=json.loads(checked_bytes(delivery['results'][-1]));previous=NativeScope({'path':str(Path(delivery_path).parent/'scope.json'),'sha256':latest['scope']['scope_sha256']})
    if delivery['state']!='TWO_REVISION_CREATIVE_ACCEPTED' or latest['artifact']['version']!=4:raise ValueError('RECT_ACCEPTED_SOURCE_REQUIRED')
    usage=previous.snapshot()
    if usage['dcc_starts']!=33 or any(t.get('stopped_at') is None for t in usage['tickets']):raise ValueError('RECT_PRIOR_ALL_STOPS_REQUIRED')
    # 使用最终真实作业记录中的准备，不依赖历史命名来选择模型或场景。
    execution=Path(delivery['results'][-1]['path']).parent
    oldjob=load(execution/'job.json');oldprep=json.loads(checked_bytes(oldjob['preparation']))
    config_record=oldprep['configuration'];configuration=json.loads(checked_bytes(config_record))
    root=previous.root/'continuations'/namespace
    if root.exists():raise ValueError('RECT_FRESH_NAMESPACE_REQUIRED')
    root.mkdir(parents=True,mode=0o700)
    original_scope=load(previous.scope['reused_inputs']['scope']['path'])
    contract=inspect_contract(original_scope['official_case']['source_hip'],config_record,latest['files']['hip'],sealed_source_hip(configuration))
    contract_record=write_new(root/'case-contract.json',contract)
    scope=copy.deepcopy(previous.scope);scope.pop('creative_budget_revision',None)
    key=secrets.token_bytes(32)
    phase={'schema':'bridge.official-case-creative-phase/1','task_id':delivery['task_id'],'prior_scope':file_record(previous.path),
      'source_delivery':delivery_record,'input_source':file_record(Path(latest['control'])/'creative-input-source.json'),
      'case_contract':contract_record,'ledger_root':str(root/'artifact_ledger'),'starts':14,'seconds':1800}
    scope.update(scope_id='rectlight-creative-'+uuid.uuid4().hex,host_started=False,creative_phase=phase,
      continuation_of=file_record(previous.path),authorization={'authority':'current_user_instruction','instruction':instruction},
      accounting={'namespace':namespace,'key_path':str(previous.root/'.native-control'/namespace/'key'),'key_sha256':hashlib.sha256(key).hexdigest()},
      budget=dict(scope['budget'],max_dcc_starts=previous.scope['budget']['max_dcc_starts']+14,total_seconds=previous.scope['budget']['total_seconds']+1800))
    native=NativeScope.initialize(bind(write_new(root/'scope.json',scope)),key=key)
    ArtifactRegistry(phase['ledger_root'])
    oldmanifest=load(Path(oldprep['runtime_control'])/'run.json');hosts={}
    # 原alpha校准及兼容证明继续由原校准验证器、相同路线摘要严格认证。
    original_alpha=json.loads(checked_bytes(previous.scope['reused_inputs']['alpha']))['alpha_calibration']
    alpha=make_reuse_binding(original_alpha,previous.scope['reused_inputs']['addon'],file_record(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py'))
    project=root/'baseline/project';control=project/'control'
    for kind,name in (('houdini','production_host'),('nuke','production_nuke')):
        cfg=copy.deepcopy(oldmanifest[name])
        for k in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir','input_artifact_source'):cfg.pop(k,None)
        cfg.update(native_scope=native.binding,resource_budget=resource(native),feedback_ledger_root=phase['ledger_root'])
        hosts[kind]=cfg
    alpha['plugin_reuse']['active_plugin']['path']=str(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py');hosts['houdini']['alpha_calibration']=alpha
    construction=[{'index':0,'asset_id':'sealed-official-karma-disklight','semantic_role':'render_scene_configuration','source_uri':config_record['path'],'bytes':config_record['bytes'],'sha256':config_record['sha256']}]
    prepare_graph(project,app=None,scheduler_root=root/'scheduler',execution_profile=True,render_profile=True,production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
    for directory in (root/'official',root/'reference',project/'saves'):directory.mkdir(parents=True)
    protected={f'final_{name}':record for name,record in latest['files'].items()}
    protected.update({f'original_{name}':record for name,record in oldprep['protected_files'].items()})
    prep={'schema':'bridge.rectlight-preparation/1','scope':native.binding,'case_id':CASE_ID,'case_contract':contract_record,
      'source_delivery':delivery_record,'source_result':delivery['results'][-1],'source_preparation':oldjob['preparation'],
      'source_graph':oldprep['source_graph'],'old_configuration':config_record,'task_id':delivery['task_id'],
      'project':str(project),'control':str(control),'snapshot_manifest':file_record(control/'snapshot-manifest.json'),
      'manifest':file_record(control/'run.json'),'environment':_runtime_environment(native.scope),'protected_files':protected,
      'display_policy':original_scope['official_case']['display_policy'],'initial_starts':usage['dcc_starts'],'initial_seconds':usage['total_seconds'],
      'official':{'hip':str(root/'official/rectlight-cpu.hip'),'usd':str(root/'official/rectlight.usd'),'image':str(root/'official/rectlight.0001.exr')}}
    record=write_new(root/'case-preparation.json',prep)
    return {'preparation':record,'entry':str(control/'snapshot/tools/run_luna_official_case.py'),'native_starts':0}

def reference_worker(path):
    """只加载认证官方工作副本、选择真实Rect分支、观察并导出，不渲染。"""
    from dcc_task_runtime import owned_process
    from houdini_bridge.official_case_variant import expected_light_parameters,common_stage
    from houdini_bridge.official_karma_scene import load_observation
    from houdini_bridge.official_karma_native import scalar_write,capture_parameters,capture_stage,verify_output_stage,semantic_compare
    import hou
    prep=load(path);native=NativeScope(prep['scope']);contract=validate_contract(prep['case_contract'])
    directory=Path(os.environ['BRIDGE_OWNED_SUPERVISOR_DIR']);intent=load(directory/'intent.json');identity=intent['identity']
    if intent['resource_budget']['native_scope']!=native.binding or intent['native_scope_ticket']['role']!='houdini-host':raise ValueError('RECT_ADMITTED_REFERENCE_REQUIRED')
    owned_process.runtime_ready_and_wait();started=owned_process.read_receipt(directory,'started',identity=identity)
    if not started or started['pid']!=os.getpid():raise ValueError('RECT_ORIGINAL_PROCESS_REQUIRED')
    baseconfig=json.loads(checked_bytes(contract['base_configuration']));base=load_observation(baseconfig)
    hou.hipFile.load(contract['official_work_hip']['path'],suppress_save_prompt=True,ignore_load_warnings=False);hou.setFrame(1)
    node=hou.node(LIGHT);params=capture_parameters(node)
    if params!=expected_light_parameters(base):
        diffs={k:{'expected':expected_light_parameters(base).get(k),'actual':params.get(k)} for k in set(params)|set(expected_light_parameters(base)) if params.get(k)!=expected_light_parameters(base).get(k)}
        write_new(directory/'parameter-differences.json',diffs)
        raise ValueError('RECT_OFFICIAL_NATIVE_PARAMETER_DIFFERENCE:'+','.join(diffs))
    switch=hou.node('/stage/lights/switch3');scalar_write(switch,'input',0)
    if switch.input(0).path()!='/stage/lights/render_rectlight':raise ValueError('RECT_OFFICIAL_BRANCH_REQUIRED')
    image=prep['official']['image'];usd=prep['official']['usd'];hip=prep['official']['hip']
    author=hou.node('/stage/lights/update_output_image_path');scalar_write(author,'productName',image)
    rop=hou.node('/stage/lights/OUT_karma_lights')
    for name,value in {'runcommand':0,'lopoutput':usd,'enableoutputprocessor_savetodirectory':0,'savetodirectory_directory':str(Path(usd).parent)}.items():scalar_write(rop,name,value)
    adapter=hou.node('/stage/lights/bridge_rgba_output');stage=adapter.stage(frame=1,apply_viewport_overrides=False,ignore_errors=False)
    verify_output_stage(stage,image);captured=capture_stage(stage,case_id=CASE_ID)
    common=semantic_compare(common_stage(base['stage']),common_stage(captured),reference_output=base['output'],actual_output=image)
    if common['state']!='PASS':raise ValueError('RECT_REFERENCE_COMMON_UPSTREAM:'+str(common['differences']))
    if Path(usd).exists() or Path(image).exists():raise ValueError('RECT_FRESH_OUTPUT_REQUIRED')
    hou.hipFile.save(file_name=hip,save_to_recent_files=False)
    rop.parm('execute').pressButton()
    if rop.parm('runcommand').eval()!=0 or not Path(usd).is_file() or Path(image).exists():raise ValueError('RECT_EXPORT_ONLY_REQUIRED')
    from pxr import Usd
    exported=Usd.Stage.Open(usd);verify_output_stage(exported,image)
    comparison=semantic_compare(captured,capture_stage(exported,case_id=CASE_ID),reference_output=image,actual_output=image,export_up_axis_policy='h21_export_fallback_y_v1')
    if comparison['state']!='PASS':raise ValueError('RECT_EXPORT_STAGE_MISMATCH')
    observation=write_new(directory/'observation.json',{'schema':'bridge.official-rectlight-observation/1','case_id':CASE_ID,'source_contract':prep['case_contract'],'switch_input':0,
      'light_parameters':params,'stage':captured,'output':image,'common_upstream':common,'export_comparison':comparison})
    owned_process._signed_write(directory,{'schema':owned_process.SCHEMA,'event':'official-rectlight-observation','identity':identity,'scope_binding':native.binding,
      'captured_pid':os.getpid(),'started_sha256':canonical_sha256(started),'case_contract':prep['case_contract'],'observation':observation,'hip':file_record(Path(hip)),'usd':file_record(Path(usd))})

def wait_owned(handle,limit=120):
    """等待已签发进程的可信停止；超时先停止，不重复派发。"""
    from dcc_task_runtime import owned_process
    end=time.monotonic()+limit
    while handle.poll() is None and time.monotonic()<end:time.sleep(.25)
    if handle.poll() is None:
        handle.terminate()
        handle.wait(timeout=15)
    receipt=handle.receipt()
    if not receipt or owned_process.execution_returncode(receipt)!=0 or receipt.get('stop_reason') is not None:raise ValueError('RECT_NATIVE_ATTEMPT_FAILED')
    return receipt

def frozen_writer(native,host):
    """沿用已有监督器的完整可执行映像身份，不传入简化的安装文件记录。"""
    from dcc_task_runtime.process_image import freeze_executable
    item=native.scope['hosts'][host]
    return freeze_executable(item['path'],'21.0.631',item['sha256'])

def run_reference(path):
    """新分支必要的官方H观察和一次独立Karma；从不重跑旧参考或alpha。"""
    from dcc_task_runtime import owned_process
    from houdini_bridge.official_karma import compare_files
    prep=load(path);native=NativeScope(prep['scope']);root=Path(path).parent
    if ROOT!=Path(prep['control'])/'snapshot':raise ValueError('RECT_USE_PREPARED_ENTRY')
    reference_root=Path(prep.get('reference_root',str(root/'reference')))
    native_repair=prep.get('reference_native_repair')
    if native_repair is not None:
        from dcc_task_runtime import owned_process
        usage=native.snapshot();old_native=NativeScope(bind(native_repair['prior_scope']))
        old_usage=old_native.snapshot();fact=native_repair['failed_stopped']
        stopped=owned_process.read_receipt(Path(fact['path']).parent,'stopped',identity=native_repair['identity'])
        checked_bytes(fact)
        if (native.scope.get('continuation_of')!=native_repair['prior_scope']
                or native.scope.get('case_contract_correction')!=native_repair['correction']
                or usage['tickets']!=old_usage['tickets'] or usage['dcc_starts']!=prep['initial_starts']+1
                or any(t['stopped_at'] is None for t in usage['tickets'])
                or not stopped or owned_process.execution_returncode(stopped)!=1
                or reference_root!=root/'reference-repair02'
                or any(Path(v).exists() for v in prep['official'].values())):
            raise ValueError('RECT_STOPPED_NATIVE_REPAIR_REQUIRED')
    repair=prep.get('reference_preflight_repair')
    if repair is not None:
        old=json.loads(checked_bytes(repair['preparation']));prior=json.loads(checked_bytes(repair['journal']))
        usage=native.snapshot()
        old_reference=root/'reference'
        if (repair.get('native_starts_added')!=0 or old.get('scope')!=prep['scope']
                or usage['dcc_starts']!=prep['initial_starts'] or any(t['stopped_at'] is None for t in usage['tickets'])
                or set(prior['stages'])!={'observation_intent'} or prior['stages']['observation_intent']['state']!='DONE'
                or prior['preparation']!=repair['preparation']
                or (old_reference/'supervisor-houdini').exists() or (old_reference/'supervisor-husk').exists()
                or reference_root!=root/'reference-repair01'):
            raise ValueError('RECT_PRE_NATIVE_REPAIR_REQUIRED')
    reference_root.mkdir(exist_ok=True)
    journal=Journal(reference_root,Path(path))
    if journal.value['stages']:raise ValueError('RECT_REFERENCE_QUERY_EXISTING_REQUIRED')
    env=prep['environment'];python=native.scope['hosts']['supervisor_python']['path']
    command=[native.scope['hosts']['hython']['path'],'-B',str(ROOT/'tools/run_luna_official_case.py'),'reference-worker','--preparation',str(path)]
    identity={'task_id':prep['task_id'],'operation_id':'rectlight-reference-observation','launch_nonce':uuid.uuid4().hex};directory=reference_root/'supervisor-houdini'
    journal.action('observation_intent',lambda:{'command':command,'directory':str(directory),'identity':identity})
    handle=owned_process.launch(command,directory=directory,identity=identity,supervisor_executable=python,env=env,budget_seconds=120,resource_budget=resource(native),writer_executable=frozen_writer(native,'hython'),scope_role='houdini-host',scope_heavy=False)
    journal.action('observation_stop',lambda:wait_owned(handle))
    fact=owned_process.read_receipt(directory,'official-rectlight-observation',identity=identity)
    if not fact:raise ValueError('RECT_OFFICIAL_OBSERVATION_REQUIRED')
    command=[native.scope['hosts']['husk']['path'],'--prerender-script',str(ROOT/'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'),'--renderer','BRAY_HdKarma','--settings','/Render/rendersettings','--lock-random','1','--frame','1','--frame-count','1',prep['official']['usd']]
    rid={'task_id':prep['task_id'],'operation_id':'rectlight-reference-render','launch_nonce':uuid.uuid4().hex};render_dir=reference_root/'supervisor-husk'
    journal.action('render_intent',lambda:{'command':command,'directory':str(render_dir),'identity':rid})
    handle=owned_process.launch(command,directory=render_dir,identity=rid,supervisor_executable=python,env=env,budget_seconds=120,resource_budget=resource(native),writer_executable=frozen_writer(native,'husk'),scope_role='official-case-husk',scope_heavy=True)
    journal.action('render_stop',lambda:wait_owned(handle))
    journal.action('image_verified',lambda:compare_files(prep['official']['image'],prep['official']['image'],require_identical=True))
    variant={'schema':'bridge.official-case-variant/1','case_id':CASE_ID,'contract':prep['case_contract'],'scope':native.binding,
      'directory':str(directory),'identity':identity,**{k:fact[k] for k in ('observation','hip','usd')},
      'reference':file_record(Path(prep['official']['image'])),'reference_render':{'directory':str(render_dir),'identity':rid}}
    variant_record=write_new(root/'case-variant.json',variant)
    configuration=json.loads(checked_bytes(prep['old_configuration']));configuration.update(native_scope=native.binding,case_variant=variant_record)
    configuration['scene']['output_image']=str(Path(prep['project'])/'saves/main.0001.exr')
    record=write_new(root/'rectlight-scene.json',configuration)
    from houdini_bridge.official_karma_scene import load_observation
    observed=load_observation(configuration)
    write_new(root/'reference-result.json',{'state':'RECT_REFERENCE_READY','configuration':record,'variant':variant_record,'light_type':observed['stage']['prims'][USD]['type'],'accounting':native.snapshot()})
    return {'state':'RECT_REFERENCE_READY','configuration':record,'native_starts':2}

def publish_baseline(prep,path,saved,compared,native,control,project,config_record):
    """只整理已实际保存/验证的基线与有限MCP会话，不启动任何原生进程。"""
    from vfx_pipeline.creative_preview import write_preview
    from houdini_bridge.official_karma_display import _processor,_exposure
    from dcc_task_runtime.exr_codec import read_exr
    root=Path(path).parent
    policy=prep['display_policy'];ctypes.CDLL(policy['module_files'][-1]['path'],mode=ctypes.RTLD_GLOBAL);_,cache=_processor(policy)
    reference=file_record(Path(prep['official']['image']));display={'schema':'bridge.creative-display/1','policy':policy,'exposure_stops':_exposure(read_exr(reference['path'])),'processor_cache_id':cache,'exposure_source':reference,'alpha_display':'composite_over_black_opaque'};display['sha256']=canonical_sha256(display)
    media=root/'media';media.mkdir();reference_media=write_preview(reference,media/'reference.png',display);current_media=write_preview(file_record(project/'saves/main.0001.exr'),media/'current.png',display)
    oldprep=json.loads(checked_bytes(prep['source_preparation']));template=checked_bytes(oldprep['nuke_template']).decode()
    oldscope=load(native.scope['reused_inputs']['scope']['path']);oldref=oldscope['official_case']['paths']['official_image']
    # 复用真实Read/Write模板；若模板另带官方参考，则只替换该已知路径。
    if template.count(oldref)>1:raise ValueError('RECT_NUKE_REFERENCE_TEMPLATE_AMBIGUOUS')
    template_path=root/'rectlight-nuke-template.nk';template_path.write_text(template.replace(oldref,reference['path']));template_record=file_record(template_path)
    protected=copy.deepcopy(prep['protected_files'])
    protected.update(rect_reference=reference,rect_baseline_exr=file_record(project/'saves/main.0001.exr'),rect_baseline_hip=file_record(Path(saved['path'])),rect_configuration=config_record,rect_case_variant=file_record(root/'case-variant.json'))
    creative={'schema':'bridge.hy3-creative-preparation/1','case_id':CASE_ID,'case_variant':file_record(root/'case-variant.json'),
      'model_route':{'route':'CodexDelegatedMCPRoute','selected_model':'gpt-6-luna','reasoning_effort':'low','provider_identity':'unknown'},
      'scope':native.binding,'task_id':prep['task_id'],'source_graph':prep['source_graph'],'configuration':config_record,
      'base_delivery':prep['source_delivery'],'base_input_source':native.scope['creative_phase']['input_source'],'ledger_root':native.scope['creative_phase']['ledger_root'],
      'baseline_control':str(control),'baseline_saved':saved,'baseline_feedback_version':0,'baseline_exposure':0.,'main_artifact_id':'rectlight_creative_main','baseline_main_version':0,
      'protected_files':protected,'feedback_preparation':oldprep['feedback_preparation'],
      'baseline_sidecars':[file_record(p) for p in (control/'houdini-instances/fx_operations').glob('*.saves.json')],'baseline_diagnostic':file_record(control/'diagnostic.sqlite3'),
      'nuke_template':template_record,'display':display,'media':{'reference':reference_media,'current':current_media},
      'runtime_control':str(control),'runtime_manifest':file_record(control/'run.json'),'runtime_snapshot_manifest':file_record(control/'snapshot-manifest.json'),
      'supervisor_python':native.scope['hosts']['supervisor_python']['path'],'worker':str(ROOT/'tools/run_hy3_creative.py'),'environment':prep['environment'],
      'initial_starts':prep['initial_starts'],'initial_seconds':prep['initial_seconds'],'native_phase_limit':{k:native.scope['creative_phase'][k] for k in ('starts','seconds')}}
    # 新内容版本零是已经迁移并真实读回的Rect基线，不伪造新的建图回执。
    record=write_new(root/'creative-preparation.json',creative)
    assets={k:{'asset_id':k,'file':v['preview'],'sha256':v['preview']['sha256'],'kind':'image','mime_type':'image/png','role':k,'case_id':CASE_ID} for k,v in creative['media'].items()}
    write_new(root/'creative-state.json',{'schema':'bridge.creative-session-state/1','assets':assets,'served':{},'observations':{},'plans':{},'jobs':{},'requests':{},'completed':[],'current_asset':'current','current_exposure':0.})
    frontend=root/'frontend';frontend.mkdir();workspace=root/'workspace/.workbuddy';workspace.mkdir(parents=True)
    server="import sys\nfrom pathlib import Path\nr=Path("+repr(str(ROOT))+")\nfor n in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(r/'packages'/n/'src'))\nfrom vfx_pipeline.creative_session import CreativeSession,CreativeMCP\nfrom vfx_pipeline.workbuddy_mcp import serve\nserve(CreativeSession("+repr(record['path'])+"),adapter_class=CreativeMCP)\n"
    (frontend/'server.py').write_text(server)
    write_new(workspace/'mcp.json',{'mcpServers':{'bridge-hy3-creative':{'command':creative['supervisor_python'],'args':['-I','-B',str(frontend/'server.py')]}}})
    result={'state':'RECT_BASELINE_READY','case_id':CASE_ID,'configuration':config_record,'creative_preparation':record,'saved':saved,'comparison':compared,'media':creative['media'],'accounting':native.snapshot()}
    write_new(root/'baseline-result.json',result)
    return {'state':'RECT_BASELINE_READY','preparation':record,'starts_used':native.snapshot()['dcc_starts']-prep['initial_starts']}


def run_baseline(path):
    """原GraphRun只提供已验收几何；新案例迁移保存/渲染并建立独立内容零版。"""
    from run_controlled_engineering import _stop_host
    from run_alpha_calibration import ScopeBudget
    from vfx_pipeline.official_graph_resume import resume_graph_facade
    from vfx_pipeline.artifact_registry import ArtifactRegistry
    from vfx_pipeline.feedback_versions import FeedbackVersions
    from vfx_pipeline.creative_preview import write_preview
    from houdini_bridge.official_karma import compare_files
    from houdini_bridge.official_karma_display import _processor,_exposure
    from dcc_task_runtime.exr_codec import read_exr
    prep=load(path)
    if prep.get('baseline_resume') is not None:return resume_baseline(path)
    native=NativeScope(prep['scope']);root=Path(path).parent
    if ROOT!=Path(prep['control'])/'snapshot':raise ValueError('RECT_USE_PREPARED_ENTRY')
    config_record=file_record(root/'rectlight-scene.json');configuration=json.loads(checked_bytes(config_record));latest=json.loads(checked_bytes(prep['source_result']))
    project=Path(prep['project']);control=Path(prep['control']);journal=Journal(root/'baseline',Path(path));budget=ScopeBudget(path.parent/'scope.json');budget.limits=dict(native.scope['budget'])
    if journal.value['stages']:raise ValueError('RECT_BASELINE_QUERY_EXISTING_REQUIRED')
    for record in latest['save_sidecars']:
        p=control/'houdini-instances/fx_operations'/Path(record['path']).name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(checked_bytes(record))
    data={'root':native.root,'project':project,'control':control,'scope_path':native.path,'scope_sha256':native.binding['sha256']}
    os.environ.clear();os.environ.update(prep['environment'])
    f=None;case_database=None
    try:
        with resume_graph_facade(control/'run.json',prep['source_graph'],repo_root=ROOT,scheduler_root=root/'scheduler') as f:
            registry=ArtifactRegistry(native.scope['creative_phase']['ledger_root']);f.artifact_registry=registry;f.host_client.bind_artifact_registry(registry);f.save_root=project/'saves'
            # 迁移源依赖和Rect内容零版分属两个数据库；旧收据不改写依赖。
            import sqlite3
            from contextlib import closing
            from run_hy3_creative import _copy_feedback
            case_database=f.database;migration=control/'migration/diagnostic.sqlite3';migration.parent.mkdir()
            with closing(sqlite3.connect(case_database)) as source_db,closing(sqlite3.connect(migration)) as target_db:source_db.backup(target_db)
            f.database=migration;_copy_feedback(latest['control'],f)
            if latest['saved']['feedback_dependencies']!=FeedbackVersions(f).dependencies():raise ValueError('RECT_SOURCE_FEEDBACK_DEPENDENCIES_REQUIRED')
            f._save_receipt(latest['saved']);journal.action('reopen_source',lambda:f.task_reopen(latest['saved']['saved_scene_id']))
            roles={n['role']:n['path'] for n in latest['saved']['scene_contract']['nodes']}
            transition=journal.action('case_transition',lambda:f.host_client.call('node.set_parms',{'task_id':prep['task_id'],'path':roles['light'],'parms':CHANGES,'official_case_configuration':config_record}))
            if transition.get('values')!=CHANGES:raise ValueError('RECT_TRANSITION_READBACK_REQUIRED')
            transition_event={'case_id':CASE_ID,'source_saved_scene':latest['saved']['saved_scene_id'],'source_dependencies':latest['saved']['feedback_dependencies'],'configuration':config_record,'typed_transition':canonical_sha256(transition)}
            f.record_event('official_case_source_migrated',transition_event)
            f.database=case_database;f.official_feedback_configuration=configuration
            f.record_event('official_case_baseline_adopted',dict(transition_event,migration_database=file_record(migration)))
            FeedbackVersions(f).register_completed(prep['source_graph']['graph_id'],prep['source_graph']['compiled_graph'])
            saved=journal.action('save',f.task_save)
            journal.action('reopen_saved_for_render',lambda:f.task_reopen(saved['saved_scene_id']))
            pattern=str(project/'saves/main.%04d.exr')
            def render():
                value=f.host_client.call('render.start',{'task_id':prep['task_id'],'request_id':'rectlight_baseline_render','render_target':roles['render'],'output_pattern':pattern,'frames':[1],'budget_seconds':min(120,budget.remaining()),'dependencies':FeedbackVersions(f).dependencies()})
                f._register_operation(value['operation_id'],'houdini-render','houdini','rectlight_baseline_render');return value
            rendered=journal.action('render',render);journal.action('render_complete',lambda:_poll(f,'operation_query',rendered['operation_id'],('operation','state'),budget))
            journal.action('host_stop',lambda:_stop_host(data,'houdini'))
            verified=journal.action('verify',lambda:f.verify_render_output('rectlight_baseline_verify',rendered['operation_id']))
            compared=journal.action('official_comparison',lambda:compare_files(prep['official']['image'],str(project/'saves/main.0001.exr'),require_identical=True))
            if compared['state']!='PASS':raise ValueError('RECT_BASELINE_REFERENCE_DIFFERENCE')
        return publish_baseline(prep,path,saved,compared,native,control,project,config_record)
    finally:
        if f is not None and case_database is not None:f.database=case_database
        try:_stop_host(data,'houdini')
        except Exception:pass

def _verified_baseline_reconciliation(repair,prep,root,native,old,old_usage,usage):
    """仅接续已正常归档的这一份Rect渲染失败；保留其负面事实与原保存检查点。"""
    from dcc_task_runtime.graph_scheduler import GraphScheduler
    record=repair['reconciliation']
    if Path(record['path'])!=root/'baseline-stopped-reconciliation.json':raise ValueError('RECT_FIXED_BASELINE_RECONCILIATION_REQUIRED')
    evidence=json.loads(checked_bytes(record));previous=json.loads(checked_bytes(evidence['prior_preparation']))
    prior=NativeScope(bind(evidence['prior_scope']));previous_usage=prior.snapshot()
    for key in ('before_operation_store','before_runner_journal','before_slot','after_operation_store','after_runner_journal','signed_stop'):
        checked_bytes(evidence[key])
    expected_store=Path(previous['control'])/'houdini-instances/fx_operations'/Path(repair['operation_store']['path']).name
    operation_store=json.loads(checked_bytes(evidence['after_operation_store']))
    operation=operation_store.get('operations',{}).get('rectlight_baseline_render',{})
    rows=[json.loads(line) for line in checked_bytes(evidence['after_runner_journal']).decode().splitlines()]
    phase=copy.deepcopy(native.scope['creative_phase']);phase['starts']=14
    slot=GraphScheduler(prior.path.parent/'scheduler').snapshot()
    if (evidence.get('schema')!='bridge.rectlight-stopped-baseline-reconciliation/1'
            or evidence.get('task_id')!=prep['task_id'] or evidence.get('operation_id')!='rectlight_baseline_render'
            or evidence.get('state')!='SUPERSEDED' or evidence.get('result_complete') is not False
            or evidence.get('slot_released') is not True or evidence.get('renderer_ticket_observed') is not False
            or evidence.get('output_exists') is not False or evidence.get('new_native_starts')!=0
            or previous.get('scope')!={k:evidence['prior_scope'][k] for k in ('path','sha256')}
            or previous.get('baseline_resume',{}).get('preparation')!=repair['preparation']
            or previous.get('task_id')!=prep['task_id'] or previous.get('project')!=prep['project']
            or evidence['after_operation_store']!=file_record(expected_store)
            or evidence['after_runner_journal']!=file_record(expected_store.with_suffix('.jsonl'))
            or operation_store.get('task_id')!=prep['task_id'] or operation.get('task_id')!=prep['task_id']
            or operation.get('request_id')!='rectlight_baseline_render' or operation.get('state')!='SUPERSEDED'
            or operation.get('frames_done')!=[] or operation.get('lifecycle_fact',{}).get('stop_confirmed') is not True
            or operation.get('lifecycle_fact',{}).get('kind')!='STOP_CONFIRMED'
            or not rows or rows[-1].get('active')!=[]
            or slot.get('active')!=0 or slot.get('phase')!='RELEASED'
            or usage['tickets']!=previous_usage['tickets'] or usage['dcc_starts']!=prep['initial_starts']+5
            or previous_usage['tickets'][:-1]!=old_usage['tickets']
            or any(t['stopped_at'] is None for t in previous_usage['tickets'])
            or native.scope['continuation_of']!=file_record(prior.path)
            or native.scope['creative_phase'].get('starts')!=16
            or phase!=NativeScope(old['scope']).scope['creative_phase']
            or prior.scope['creative_phase']!=NativeScope(old['scope']).scope['creative_phase']):
        raise ValueError('RECT_STOPPED_BASELINE_RECONCILIATION_REQUIRED')
    last=usage['tickets'][-1]
    if (evidence['signed_stop']!=repair['stopped']
            or evidence['signed_stop']!=file_record(Path(last['directory'])/'stopped.json')
            or operation.get('supervisor_binding')!={'directory':last['directory'],'identity':last['identity']}):
        raise ValueError('RECT_RECONCILIATION_SUPERVISOR_MISMATCH')
    from dcc_task_runtime import owned_process
    stop=owned_process.read_receipt(last['directory'],'stopped',identity=last['identity'])
    if not stop or operation.get('host_identity',{}).get('pid')!=stop.get('pid'):
        raise ValueError('RECT_RECONCILIATION_SIGNED_STOP_REQUIRED')
    return prior

def resume_baseline(path):
    """只从已完成的正式保存检查点冷开/渲染，不重复原迁移与保存。"""
    from run_controlled_engineering import _stop_host
    from run_alpha_calibration import ScopeBudget
    from vfx_pipeline.official_graph_resume import resume_graph_facade,_snapshot
    from vfx_pipeline.artifact_registry import ArtifactRegistry
    from vfx_pipeline.feedback_versions import FeedbackVersions
    from run_hy3_creative import _copy_feedback
    from houdini_bridge.official_karma import compare_files
    from dcc_task_runtime import owned_process
    prep=load(path);native=NativeScope(prep['scope']);root=Path(path).parent;repair=prep['baseline_resume']
    if ROOT!=Path(prep['control'])/'snapshot':raise ValueError('RECT_USE_PREPARED_ENTRY')
    _snapshot(Path(prep['control']))
    old=json.loads(checked_bytes(repair['preparation']));original=json.loads(checked_bytes(repair['journal']));store=json.loads(checked_bytes(repair['operation_store']))
    checked_bytes(repair['feedback_database']);checked_bytes(repair['stopped'])
    runner_rows=[json.loads(line) for line in checked_bytes(repair['runner_journal']).decode().splitlines()]
    if any(row.get('active') for row in runner_rows):raise ValueError('RECT_RENDER_PRIOR_ACTIVITY_UNKNOWN')
    expected_sidecars=list(Path(old['control']).joinpath('houdini-instances/fx_operations').glob('*.saves.json'))
    if [file_record(p) for p in expected_sidecars]!=repair['save_sidecars']:raise ValueError('RECT_CHECKPOINT_SIDECAR_CHANGED')
    stages=original['stages'];usage=native.snapshot();prior=NativeScope(old['scope']);old_usage=prior.snapshot()
    reconciled=repair.get('reconciliation') is not None
    if reconciled:
        prior=_verified_baseline_reconciliation(repair,prep,root,native,old,old_usage,usage)
    expected_roles=['houdini-host','houdini-host','official-case-husk','houdini-host']+(['houdini-host'] if reconciled else [])
    expected_phase=copy.deepcopy(native.scope['creative_phase'])
    if reconciled:expected_phase['starts']=14
    if (set(stages)!={'reopen_source','case_transition','save','render'} or original['preparation']!=repair['preparation']
            or any(stages[k]['state']!='DONE' for k in ('reopen_source','case_transition','save')) or stages['render']['state']!='INTENT'
            or (not reconciled and usage['tickets']!=old_usage['tickets']) or usage['dcc_starts']!=prep['initial_starts']+len(expected_roles)
            or any(t['stopped_at'] is None for t in usage['tickets']) or expected_phase!=prior.scope['creative_phase']
            or native.scope['continuation_of']!=file_record(prior.path)
            or [t['role'] for t in usage['tickets'][prep['initial_starts']:]]!=expected_roles
            or set(store)-{'scene_transition_cas','scene_transitions','task_id'} or store['task_id']!=prep['task_id']
            or old['project']!=prep['project'] or old['case_contract']!=prep['case_contract']
            or (Path(prep['project'])/'saves/main.0001.exr').exists()):
        raise ValueError('RECT_SAVED_BASELINE_REPAIR_REQUIRED')
    last=usage['tickets'][-1];stop=owned_process.read_receipt(last['directory'],'stopped',identity=last['identity'])
    if repair['stopped']!=file_record(Path(last['directory'])/'stopped.json') or last['role']!='houdini-host' or not stop or stop.get('stop_reason')!='TIME_BUDGET_EXCEEDED':raise ValueError('RECT_CHECKPOINT_PRIOR_STOP_REQUIRED')
    saved=stages['save']['result'];record=file_record(Path(saved['path']))
    if record['sha256']!=saved['sha256'] or saved.get('scene_contract_sha256')!=canonical_sha256(saved['scene_contract']):raise ValueError('RECT_SAVED_BASELINE_CHANGED')
    config_record=file_record(root/'rectlight-scene.json');configuration=json.loads(checked_bytes(config_record));project=Path(prep['project']);control=Path(prep['control'])
    directory=control/'houdini-instances/fx_operations';directory.mkdir(parents=True,exist_ok=True)
    for source in Path(old['control']).joinpath('houdini-instances/fx_operations').glob('*.saves.json'):
        (directory/source.name).write_bytes(checked_bytes(file_record(source)))
    journal_root=root/('baseline-render-repair01' if reconciled else 'baseline-render-resume')
    if reconciled and prep.get('baseline_journal_root')!=str(journal_root):raise ValueError('RECT_FIXED_RESUME_JOURNAL_REQUIRED')
    journal_root.mkdir(exist_ok=True);journal=Journal(journal_root,Path(path))
    if journal.value['stages']:raise ValueError('RECT_QUERY_BASELINE_RESUME_REQUIRED')
    budget=ScopeBudget(native.path);budget.limits=dict(native.scope['budget']);budget.available(starts=10)
    os.environ.clear();os.environ.update(prep['environment'])
    data={'root':native.root,'project':project,'control':control,'scope_path':native.path,'scope_sha256':native.binding['sha256']}
    try:
        with resume_graph_facade(control/'run.json',prep['source_graph'],repo_root=ROOT,scheduler_root=native.path.parent/'scheduler') as f:
            registry=ArtifactRegistry(native.scope['creative_phase']['ledger_root']);f.artifact_registry=registry;f.host_client.bind_artifact_registry(registry);f.save_root=project/'saves';f.official_feedback_configuration=configuration
            if repair['feedback_database']!=file_record(Path(old['control'])/'diagnostic.sqlite3'):raise ValueError('RECT_CHECKPOINT_DATABASE_CHANGED')
            _copy_feedback(old['control'],f)
            if saved['feedback_dependencies']!=FeedbackVersions(f).dependencies():raise ValueError('RECT_CHECKPOINT_FEEDBACK_MISMATCH')
            f._save_receipt(saved);reopened=journal.action('cold_reopen',lambda:f.task_reopen(saved['saved_scene_id']))
            roles={n['role']:n['path'] for n in saved['scene_contract']['nodes']};pattern=str(project/'saves/main.%04d.exr')
            from houdini_bridge.official_case_variant import verified_reopen_parameters
            actual=journal.action('cold_rect_parameters',lambda:verified_reopen_parameters(reopened,saved,configuration,f.host_client.production_config['expected_identity'],list(CHANGES)))
            if actual['parms']!=CHANGES:raise ValueError('RECT_CHECKPOINT_NATIVE_PARAMETERS_MISMATCH')
            def render():
                value=f.host_client.call('render.start',{'task_id':prep['task_id'],'request_id':'rectlight_baseline_render','render_target':roles['render'],'output_pattern':pattern,'frames':[1],'budget_seconds':min(120,budget.remaining()),'dependencies':FeedbackVersions(f).dependencies()})
                f._register_operation(value['operation_id'],'houdini-render','houdini','rectlight_baseline_render');return value
            rendered=journal.action('render',render);journal.action('render_complete',lambda:_poll(f,'operation_query',rendered['operation_id'],('operation','state'),budget))
            journal.action('host_stop',lambda:_stop_host(data,'houdini'))
            journal.action('verify',lambda:f.verify_render_output('rectlight_baseline_verify',rendered['operation_id']))
            compared=journal.action('official_comparison',lambda:compare_files(prep['official']['image'],str(project/'saves/main.0001.exr'),require_identical=True))
            if compared['state']!='PASS':raise ValueError('RECT_BASELINE_REFERENCE_DIFFERENCE')
        return publish_baseline(prep,path,saved,compared,native,control,project,config_record)
    finally:
        try:_stop_host(data,'houdini')
        except Exception:pass


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','reference','reference-worker','baseline']);p.add_argument('--preparation');p.add_argument('--delivery');p.add_argument('--namespace',default='luna-rectlight-01');p.add_argument('--instruction');a=p.parse_args()
    if a.mode=='prepare':value=prepare(a.delivery,a.namespace,a.instruction)
    elif a.mode=='reference-worker':reference_worker(Path(a.preparation));return
    else:value=run_reference(Path(a.preparation)) if a.mode=='reference' else run_baseline(Path(a.preparation))
    print(json.dumps(value,ensure_ascii=False))
if __name__=='__main__':main()
