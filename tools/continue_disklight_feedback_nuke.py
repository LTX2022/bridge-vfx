#!/usr/bin/env python3
"""继承本轮反馈总预算，仅续已登记v2的Nuke消费。"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,secrets,sys,uuid
from pathlib import Path
from contextlib import contextmanager
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from houdini_bridge.official_karma_observation import file_record,checked_bytes,write_new
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.canonical import canonical_sha256
from continue_official_karma import _binding,_runtime_environment,Journal,_poll

def load(p):return json.loads(Path(p).read_text())

def prepare(feedback_root,namespace):
    """先完整只读验证失败范围里的成功生产与登记，再准备唯一Nuke替换范围。"""
    from nuke_bridge.task_host import input_artifact_registry
    from prepare_workbuddy_graph import prepare_graph
    old=Path(feedback_root);prep=load(old/'feedback-preparation.json');stages=load(old/'incremental-state.json')['stages']
    for name in ('feedback','save','cold_reopen','cold_exposure','render_completed','render_host_stop','verify','register','consume'):
        if stages.get(name,{}).get('state')!='DONE':raise ValueError('FEEDBACK_NUKE_SUCCESSFUL_SOURCE_REQUIRED')
    registered=stages['register']['result'];producer=NativeScope(prep['scope']);state=producer.snapshot()
    if any(t.get('stopped_at') is None for t in state['tickets']):raise ValueError('FEEDBACK_NUKE_SOURCE_NOT_STOPPED')
    control=Path(prep['control']);scope_record=file_record(producer.path)
    source={'schema':'bridge.disklight-feedback-nuke-source/1','task_id':registered['task_id'],
        'artifact_id':registered['artifact_id'],'artifact_version':registered['version'],
        'producer_scope':scope_record,'producer_control':str(control),
        'producer_ledger':str(Path(registered['registry_operation_receipt']['registry_path']).parent),
        'producer_manifest':prep['manifest'],'producer_snapshot_manifest':prep['snapshot_manifest'],
        'producer_deployment':file_record(control/'production-hosts.json'),
        'producer_owners':file_record(control/'host-state/houdini-operation-owners.json'),
        'registry_operation_receipt':registered['registry_operation_receipt'],
        'producer_fact_sha256':canonical_sha256(stages['verify']['result']['execution_fact']),
        'producer_stopped_tickets_sha256':canonical_sha256(state['tickets']),
        'source_graph':prep['source_graph'],'feedback_delivery':prep['delivery'],
        'feedback_root':str(old),'usd_recovery':file_record(old/'usd-approved-recovery-result.json')}
    registry=input_artifact_registry(source,scope=producer,task_id=source['task_id'],require_continuation=False)
    if registry.lookup(source['artifact_id'])!=registered or not registry.verify(source['artifact_id']).get('usable'):
        raise ValueError('FEEDBACK_NUKE_REGISTERED_SOURCE_CHANGED')
    root=producer.root/'continuations'/namespace
    existing=None
    if root.exists():
        if (root/'feedback-nuke-preparation.json').exists() or (root/'incremental-state.json').exists():raise ValueError('FEEDBACK_NUKE_FRESH_NAMESPACE_REQUIRED')
        existing=NativeScope(_binding(file_record(root/'scope.json')))
        if (existing.snapshot()['tickets']!=state['tickets'] or existing.scope.get('continuation_of')!=scope_record
                or existing.scope.get('feedback_phase')!=producer.scope.get('feedback_phase')):
            raise ValueError('FEEDBACK_NUKE_PARTIAL_PREPARATION_CHANGED')
    else:root.mkdir(parents=True,mode=0o700)
    key=secrets.token_bytes(32);scope=copy.deepcopy(producer.scope)
    scope.update(scope_id='disklight-feedback-nuke-'+uuid.uuid4().hex,host_started=False,
      authorization={'authority':'current_user_instruction','instruction':'允许。去完成吧；复用已完成反馈与主图v2，只修Nuke共享账本输入并在本轮6启动/600秒内完成。'},
      accounting={'namespace':namespace,'key_path':str(producer.root/'.native-control'/namespace/'key'),'key_sha256':hashlib.sha256(key).hexdigest()},
      continuation_of=scope_record,feedback_nuke_replacement=1)
    native=existing if existing is not None else NativeScope.initialize(_binding(write_new(root/'scope.json',scope)),key=key)
    scope=native.scope
    (root/'frozen-inputs').mkdir(mode=0o700,exist_ok=True)
    pointer=write_new(root/'frozen-inputs/input-artifact-source.json',source)
    hosts={};oldmanifest=load(control/'run.json');newcontrol=root/'project/control'
    for kind,keyname in (('houdini','production_host'),('nuke','production_nuke')):
        config=copy.deepcopy(oldmanifest[keyname]);config.update(native_scope=native.binding,
          resource_budget={'roots':[str(native.root)],'max_bytes':scope['budget']['max_disk_bytes'],'native_scope':native.binding})
        for keyname in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir'):
            config.pop(keyname,None)
        if kind=='nuke':config['input_artifact_source']=pointer
        else:config['alpha_calibration']['plugin_reuse']['active_plugin']['path']=str(newcontrol/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
        hosts[kind]=config
    c=prep['configuration'];construction=[{'index':0,'asset_id':'sealed-official-karma-disklight','semantic_role':'render_scene_configuration',
      'source_uri':c['path'],'bytes':c['bytes'],'sha256':c['sha256']}]
    prepare_graph(root/'project',app=None,scheduler_root=root/'scheduler',execution_profile=True,render_profile=True,
      production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
    result={'schema':'bridge.feedback-nuke-continuation/1','scope':native.binding,'source':pointer,'feedback_preparation':file_record(old/'feedback-preparation.json'),
      'control':str(newcontrol),'project':str(old/'project'),'manifest':file_record(newcontrol/'run.json'),
      'snapshot_manifest':file_record(newcontrol/'snapshot-manifest.json'),'environment':_runtime_environment(scope),
      'inherited_starts':state['dcc_starts'],'phase_initial_starts':prep['initial_starts'],'phase_initial_seconds':prep['initial_seconds'],
      'source_validation':'FULL_INPUT_REGISTRY_PASS_ZERO_NATIVE_STARTS'}
    record=write_new(root/'feedback-nuke-preparation.json',result)
    return {'preparation':record,'inherited_starts':state['dcc_starts'],'remaining_phase_starts':14-state['dcc_starts'],
      'run_command':[scope['hosts']['supervisor_python']['path'],'-I','-B',str(newcontrol/'snapshot/tools/continue_disklight_feedback_nuke.py'),'run','--preparation',record['path']]}

def prepare_retry(preparation_path,namespace,approval_path):
    """追加启动必须有独立人类许可；旧消耗、失败范围和600秒总额保留。"""
    from nuke_bridge.task_host import input_artifact_registry
    from prepare_workbuddy_graph import prepare_graph
    oldprep=load(preparation_path);previous=NativeScope(oldprep['scope']);state=previous.snapshot()
    if any(t.get('stopped_at') is None for t in state['tickets']):raise ValueError('FEEDBACK_RETRY_PRIOR_NOT_STOPPED')
    approval_record=file_record(Path(approval_path));approval=json.loads(checked_bytes(approval_record))
    if (approval.get('schema')!='bridge.feedback-budget-approval/1' or approval.get('authority')!='current_human_user'
            or approval.get('previous_scope')!=file_record(previous.path)
            or approval.get('feedback_base_scope')!=previous.scope['feedback_phase']['prior_scope']
            or approval.get('max_phase_starts')!=7 or approval.get('max_phase_seconds')!=600):
        raise ValueError('FEEDBACK_RETRY_EXPLICIT_APPROVAL_REQUIRED')
    source=json.loads(checked_bytes(oldprep['source']))
    registry=input_artifact_registry(source,scope=previous,task_id=source['task_id'])
    if not registry.verify(source['artifact_id']).get('usable'):raise ValueError('FEEDBACK_RETRY_INPUT_CHANGED')
    root=previous.root/'continuations'/namespace
    if root.exists():raise ValueError('FEEDBACK_RETRY_FRESH_NAMESPACE_REQUIRED')
    root.mkdir(mode=0o700,parents=True);key=secrets.token_bytes(32);scope=copy.deepcopy(previous.scope)
    scope.update(scope_id='feedback-nuke-final-'+uuid.uuid4().hex,host_started=False,
      accounting={'namespace':namespace,'key_path':str(previous.root/'.native-control'/namespace/'key'),'key_sha256':hashlib.sha256(key).hexdigest()},
      continuation_of=file_record(previous.path),feedback_nuke_replacement=2,feedback_extra_start_approval=approval_record,
      authorization={'authority':'current_user_instruction','instruction':approval['instruction']},
      budget=dict(previous.scope['budget'],max_dcc_starts=15))
    native=NativeScope.initialize(_binding(write_new(root/'scope.json',scope)),key=key)
    control=root/'project/control';oldmanifest=load(Path(oldprep['control'])/'run.json');hosts={}
    for kind,keyname in (('houdini','production_host'),('nuke','production_nuke')):
        config=copy.deepcopy(oldmanifest[keyname]);config.update(native_scope=native.binding,
          resource_budget={'roots':[str(native.root)],'max_bytes':scope['budget']['max_disk_bytes'],'native_scope':native.binding})
        for name in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir'):config.pop(name,None)
        if kind=='houdini':config['alpha_calibration']['plugin_reuse']['active_plugin']['path']=str(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
        hosts[kind]=config
    baseline=load(oldprep['feedback_preparation']['path']);c=baseline['configuration'];construction=[{'index':0,'asset_id':'sealed-official-karma-disklight','semantic_role':'render_scene_configuration','source_uri':c['path'],'bytes':c['bytes'],'sha256':c['sha256']}]
    prepare_graph(root/'project',app=None,scheduler_root=root/'scheduler',execution_profile=True,render_profile=True,
      production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
    prep=dict(oldprep,scope=native.binding,control=str(control),manifest=file_record(control/'run.json'),
      snapshot_manifest=file_record(control/'snapshot-manifest.json'),environment=_runtime_environment(scope),
      inherited_starts=state['dcc_starts'],extra_start_approval=approval_record)
    record=write_new(root/'feedback-nuke-preparation.json',prep)
    return {'preparation':record,'phase_starts_spent':state['dcc_starts']-oldprep['phase_initial_starts'],
      'remaining_starts':15-state['dcc_starts'],'run_command':[scope['hosts']['supervisor_python']['path'],'-I','-B',str(control/'snapshot/tools/continue_disklight_feedback_nuke.py'),'run','--preparation',record['path']]}

@contextmanager
def facade_for(prep):
    """当前控制端只启动Nuke；成功Houdini生产端通过只读来源使用。"""
    from vfx_pipeline.service import ModelSafePipeline,TrustedExecutionControl
    from vfx_pipeline.production_hosts import validate_deployments,ensure_hosts
    from vfx_pipeline.workbuddy_assembly import build_graph_facade,_DeferredTaskBoundary,production_nuke_client
    from vfx_pipeline.official_graph_resume import _snapshot,_VerifiedCompiledGraph,_NoHoudiniContinuation
    from nuke_bridge.task_host import input_artifact_registry
    control=Path(prep['control']);manifest=load(control/'run.json');source=json.loads(checked_bytes(prep['source']));native=NativeScope(prep['scope'])
    if ROOT!=control/'snapshot':raise ValueError('FEEDBACK_NUKE_PREPARED_SNAPSHOT_REQUIRED')
    if _snapshot(control)!=prep['snapshot_manifest']:raise ValueError('FEEDBACK_NUKE_SNAPSHOT_CHANGED')
    configs=validate_deployments(manifest['production_host'],manifest['production_nuke'],controller_root=control,repo_root=ROOT,application='pipeline');hosts={x['application']:x for x in configs}
    registry=input_artifact_registry(source,scope=native,task_id=source['task_id'])
    pipeline=ModelSafePipeline(Path(source['source_graph']['control'])/'pipeline.sqlite3')
    def factory():
        _,bound=ensure_hosts(hosts['houdini'],hosts['nuke'],task_id=source['task_id'],controller_root=control,repo_root=ROOT,scheduler_root=control.parent.parent/'scheduler',application='pipeline',host_kinds={'nuke'})
        return production_nuke_client(bound,control/'nuke-state')
    def detached():
        p=control/'production-hosts.json'
        if not p.exists():return None
        bound=load(p).get('hosts',{}).get('nuke')
        return production_nuke_client(bound,control/'nuke-state') if bound else None
    nuke=_DeferredTaskBoundary('nuke',factory,detached)
    f=build_graph_facade(control/'run.json',trusted_execution=TrustedExecutionControl(pipeline),jobs=_VerifiedCompiledGraph(source['source_graph']),
       task_id=source['task_id'],session_id=manifest['session_id'],backend='production',repo_root=ROOT,host_client=_NoHoudiniContinuation(),
       nuke_client=nuke,registry=registry,host_config=hosts['houdini'],nuke_config=hosts['nuke'],save_root=Path(prep['project'])/'saves')
    f.controller_source={'manifest_path':str(control/'run.json'),'manifest_sha256':prep['manifest']['sha256'],
      'snapshot_manifest_sha256':prep['snapshot_manifest']['sha256'],'repo_root':str(ROOT),'backend':'production','software_processes':False}
    yield f

def run(path):
    """仅执行Nuke原生保存、冷渲染与RGBA比较。"""
    from run_alpha_calibration import ScopeBudget
    from run_controlled_engineering import _stop_host
    from houdini_bridge.official_karma import compare_files
    path=Path(path);prep=load(path);root=path.parent;project=Path(prep['project']);control=Path(prep['control'])
    for key in ('manifest','snapshot_manifest','source','feedback_preparation'):checked_bytes(prep[key])
    budget=ScopeBudget(root/'scope.json');budget.limits=dict(budget.native.scope['budget']);budget.available(starts=2)
    journal=Journal(root,path)
    if journal.value['stages']:raise ValueError('FEEDBACK_NUKE_EXISTING_INTENT_QUERY_REQUIRED')
    os.environ.clear();os.environ.update(prep['environment'])
    data={'root':budget.native.root,'project':project,'control':control,'manifest':load(control/'run.json'),'scope':budget.scope,'scope_path':root/'scope.json','scope_sha256':budget.binding['sha256']}
    cleanup={}
    try:
        with facade_for(prep) as f:
            source=json.loads(checked_bytes(prep['source']));consumed=journal.action('consume',lambda:f.consume_artifact(source['artifact_id']))
            if consumed['registry_operation_receipt']['version']!=source['artifact_version']:raise ValueError('FEEDBACK_NUKE_INPUT_VERSION_CHANGED')
            def prepare_script():
                client=f.nuke_client;output=str(project/'saves/nuke.%04d.exr');client.call('set_knob',{'node':'Write1','knob':'file_type','value':'exr'})
                binding=client.render_binding(f.pipeline_task_id,output,[1],consumed['colorspace'],consumed['premultiplied'],artifact_binding=consumed)
                for knob,value in (('channels','rgba'),('metadata','all metadata')):client.call('set_knob',{'node':'Write1','knob':knob,'value':value})
                p=project/'saves/composite.nk';client.call('save_script',{'path':str(p),'overwrite':False});return {'script':file_record(p),'binding':binding}
            journal.action('nuke_prepare',prepare_script)
            rendered=journal.action('nuke_render',lambda:f.nuke_render_bounded('disklight_feedback_nuke',str(project/'saves/nuke.%04d.exr'),[1],artifact_id=source['artifact_id']))
            journal.action('nuke_completed',lambda:_poll(f,'operation_query',rendered['operation_id'],('operation','state'),budget))
            journal.action('nuke_stop',lambda:_stop_host(data,'nuke'))
            compared=journal.action('compare',lambda:compare_files(str(project/'saves/main.0001.exr'),str(project/'saves/nuke.0001.exr'),require_identical=True))
            if compared['state']!='PASS':raise ValueError('FEEDBACK_NUKE_PIXEL_MISMATCH')
            state=budget.native.snapshot()
            if any(t.get('stopped_at') is None for t in state['tickets']):raise ValueError('FEEDBACK_NUKE_ALL_STOPS_REQUIRED')
            result={'schema':'bridge.feedback-nuke-result/1','state':'FEEDBACK_NUKE_COMPLETE','task_id':f.pipeline_task_id,
              'artifact_id':source['artifact_id'],'artifact_version':source['artifact_version'],'comparison':compared,
              'nuke_operation_id':rendered['operation_id'],'files':{'nk':file_record(project/'saves/composite.nk'),'exr':file_record(project/'saves/nuke.0001.exr')},
              'native_scope':state,'phase_new_starts':state['dcc_starts']-prep['phase_initial_starts'],
              'phase_seconds':state['total_seconds']-prep['phase_initial_seconds'],'upstream_reexecuted':False}
            journal.action('complete',lambda:result);write_new(root/'feedback-nuke-result.json',result)
            print(json.dumps({'state':result['state'],'result':str(root/'feedback-nuke-result.json'),'phase_new_starts':result['phase_new_starts']},ensure_ascii=False))
    finally:
        try:cleanup['nuke']=_stop_host(data,'nuke')
        except BaseException as exc:cleanup['nuke']={'error':str(exc)}
        write_new(root/'nuke-cleanup.json',cleanup)

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--feedback-root',required=True);p.add_argument('--namespace',required=True)
    p=sub.add_parser('prepare-retry');p.add_argument('--preparation',required=True);p.add_argument('--namespace',required=True);p.add_argument('--approval',required=True)
    p=sub.add_parser('run');p.add_argument('--preparation',required=True);args=parser.parse_args()
    if args.command=='prepare':result=prepare(args.feedback_root,args.namespace)
    elif args.command=='prepare-retry':result=prepare_retry(args.preparation,args.namespace,args.approval)
    else:result=run(args.preparation)
    if result is not None:print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
