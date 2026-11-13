#!/usr/bin/env python3
"""同一登记 DiskLight 任务的曝光反馈与必要下游。"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, secrets, sys, uuid
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from houdini_bridge.official_karma_observation import file_record,load_record,checked_bytes,write_new
from dcc_task_runtime.native_scope import NativeScope
from continue_official_karma import _binding,_source,_runtime_environment,Journal,_poll,_registered_task_domain


def prepare(delivery_path, namespace, instruction, *, finish_preparation=False):
    """认证旧登记与新反馈授权，准备同任务独立阶段，零宿主启动。"""
    import re
    from vfx_pipeline.official_graph_resume import inspect_nuke_resume_source
    from prepare_workbuddy_graph import prepare_graph
    from houdini_bridge.alpha_reuse import make_reuse_binding
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',namespace) or not instruction.strip():
        raise ValueError('FEEDBACK_EXPLICIT_INSTRUCTION_REQUIRED')
    delivery_record=file_record(Path(delivery_path));delivery=load_record(delivery_record)
    base=Path(delivery['producer_preparation']['path'])
    origin=inspect_nuke_resume_source(base)
    if any(delivery[k]!=origin[k] for k in ('task_id','artifact_id','artifact_version','saved_scene_id')):
        raise ValueError('FEEDBACK_REGISTERED_BASELINE_CHANGED')
    for record in delivery['files'].values():checked_bytes(record)
    prior=load_record(file_record(base));source=_source(Path(prior['source']['scope']['path']).parent)
    predecessor=NativeScope(_binding(delivery['accounting']['scope']))
    state=predecessor.snapshot()
    if any(t.get('stopped_at') is None for t in state['tickets']):raise ValueError('FEEDBACK_PRIOR_STOPS_REQUIRED')
    # 控制端日志不是原生观测；只认证其文件身份，不套用观测数据的复杂度上限。
    baseline_journal=json.loads(checked_bytes(file_record(base.parent/'incremental-state.json')))
    root=predecessor.root/'continuations'/namespace
    existing = None
    if root.exists():
        if not finish_preparation or (root/'feedback-preparation.json').exists() or (root/'incremental-state.json').exists():
            raise ValueError('FEEDBACK_FRESH_NAMESPACE_REQUIRED')
        existing=NativeScope(_binding(file_record(root/'scope.json')))
        phase=existing.scope.get('feedback_phase',{})
        if (existing.snapshot()['tickets']!=state['tickets'] or phase.get('source_delivery')!=delivery_record
                or existing.scope['authorization']['instruction']!=instruction
                or existing.scope.get('continuation_of')!=file_record(predecessor.path)):
            raise ValueError('FEEDBACK_PARTIAL_PREPARATION_NOT_UNUSED')
        # 仅清理本工具尚未签发准备记录、零新增启动的半成品快照。
        import shutil
        if (root/'project').exists():
            if not (root/'project/control/snapshot-manifest.json').is_file():raise ValueError('FEEDBACK_PARTIAL_LAYOUT_UNKNOWN')
            shutil.rmtree(root/'project')
    else:
        root.mkdir(mode=0o700,parents=True)
    key=secrets.token_bytes(32);scope=copy.deepcopy(predecessor.scope)
    scope.update(scope_id='disklight-feedback-'+uuid.uuid4().hex,host_started=False,
        authorization={'authority':'current_user_instruction','instruction':instruction},
        continuation_of=file_record(predecessor.path),
        accounting={'namespace':namespace,'key_path':str(predecessor.root/'.native-control'/namespace/'key'),
                    'key_sha256':hashlib.sha256(key).hexdigest()},
        feedback_phase={'schema':'bridge.disklight-feedback-phase/1','task_id':origin['task_id'],
            'source_delivery':delivery_record,'prior_scope':file_record(predecessor.path),'starts':6,'seconds':600},
        budget=dict(scope['budget'],max_dcc_starts=scope['budget']['max_dcc_starts']+6,
                    total_seconds=scope['budget']['total_seconds']+600))
    # 执行前保存经旧交付摘要认证的 USD 原字节；ROP 导出可能沿用保存路径。
    baseline_usd=checked_bytes(delivery['files']['usd'])
    backup=root/'baseline-original.usd'
    if backup.exists():
        if backup.read_bytes()!=baseline_usd:raise ValueError('FEEDBACK_BASELINE_USD_BACKUP_CHANGED')
    else:
        with backup.open('xb') as stream:stream.write(baseline_usd)
    native=existing if existing is not None else NativeScope.initialize(_binding(write_new(root/'scope.json',scope)),key=key)
    scope=native.scope
    control=root/'project/control';project=root/'project';(project/'saves').mkdir(parents=True)
    active=file_record(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py')
    alpha=make_reuse_binding(source['alpha']['alpha_calibration'],source['addon'],active)
    alpha['plugin_reuse']['active_plugin']['path']=str(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
    hosts={}
    for kind,executable in (('houdini','hython'),('nuke','nuke')):
        hosts[kind]={'lifecycle':'task_owned','application':kind,'version':scope['versions'][kind],
            'executable':scope['hosts'][executable]['path'],'supervisor_executable':scope['hosts']['supervisor_python']['path'],
            'task_root':str(native.root),'session_seconds':120,'evidence_source':'real_host',
            'project_color':scope['project_color'],'native_scope':native.binding,
            'feedback_ledger_root':delivery['artifact_ledger'],
            'resource_budget':{'roots':[str(native.root)],'max_bytes':scope['budget']['max_disk_bytes'],'native_scope':native.binding}}
    from dcc_task_runtime.render_profiles import OFFICIAL,output_policy
    hosts['houdini'].update(output_acceptance=output_policy(OFFICIAL),alpha_calibration=alpha,
        writer_executable={'path':scope['hosts']['husk']['path'],'version':'21.0.631','sha256':scope['hosts']['husk']['sha256']})
    configuration=prior['configuration'];checked_bytes(configuration)
    construction=[{'index':0,'asset_id':'sealed-official-karma-disklight','semantic_role':'render_scene_configuration',
        'source_uri':configuration['path'],'bytes':configuration['bytes'],'sha256':configuration['sha256']}]
    prepare_graph(project,app=None,scheduler_root=root/'scheduler',execution_profile=True,render_profile=True,
        production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
    save=baseline_journal['stages']['save']['result']
    sidecars=[file_record(p) for p in (Path(prior['control'])/'houdini-instances/fx_operations').glob('*.saves.json')]
    if len(sidecars)!=1:raise ValueError('FEEDBACK_BASE_SAVE_SIDECAR_REQUIRED')
    prep={'schema':'bridge.disklight-feedback/1','scope':native.binding,'delivery':delivery_record,
        'source_graph':origin['source_graph'],'baseline':origin,'baseline_save':save,'baseline_sidecars':sidecars,
        'configuration':configuration,'project':str(project),'control':str(control),'alpha_calibration':alpha,
        'calibration':source['alpha']['calibration'],'source':source['records'],
        'manifest':file_record(control/'run.json'),'snapshot_manifest':file_record(control/'snapshot-manifest.json'),
        'environment':_runtime_environment(scope),'initial_starts':state['dcc_starts'],'initial_seconds':state['total_seconds'],
        'target':{'exposure':1.0},'baseline_exposure':0.0,'baseline_usd_backup':file_record(backup)}
    record=write_new(root/'feedback-preparation.json',prep)
    return {'preparation':record,'run_command':[scope['hosts']['supervisor_python']['path'],'-I','-B',
        str(control/'snapshot/tools/feedback_official_karma.py'),'run','--preparation',record['path']],'native_starts':0}


def feedback_facade(prep):
    """沿用已认证图及原任务，在本轮控制端使用原主产物账本。"""
    from contextlib import contextmanager
    from vfx_pipeline.official_graph_resume import resume_graph_facade
    from vfx_pipeline.feedback_versions import FeedbackVersions
    from vfx_pipeline.artifact_registry import ArtifactRegistry
    @contextmanager
    def bound():
        control=Path(prep['control'])
        directory=control/'houdini-instances/fx_operations';directory.mkdir(parents=True,exist_ok=True)
        for record in prep['baseline_sidecars']:
            target=directory/Path(record['path']).name
            if not target.exists():target.write_bytes(checked_bytes(record))
        with resume_graph_facade(control/'run.json',prep['source_graph'],repo_root=ROOT,
                scheduler_root=control.parent.parent/'scheduler') as facade:
            registry=ArtifactRegistry(load_record(prep['delivery'])['artifact_ledger'])
            facade.artifact_registry=registry
            for client in (facade.host_client,facade.nuke_client):client.bind_artifact_registry(registry)
            facade.save_root=Path(prep['project'])/'saves'
            facade.official_feedback_configuration=load_record(prep['configuration'])
            FeedbackVersions(facade).register_completed(prep['source_graph']['graph_id'],prep['source_graph']['compiled_graph'])
            facade._save_receipt(prep['baseline_save'])
            yield facade
    return bound()


def run(path):
    """只执行一次反馈事务及必要保存、渲染、登记和 Nuke 消费。"""
    from run_alpha_calibration import ScopeBudget
    from run_controlled_engineering import _stop_host
    from houdini_bridge.official_karma import compare_files
    from houdini_bridge.official_karma_feedback import EXPOSURE,GATE
    from vfx_pipeline.feedback_versions import FeedbackVersions
    path=Path(path);prep=load_record(file_record(path));root=path.parent
    if prep.get('schema')!='bridge.disklight-feedback/1' or ROOT!=Path(prep['control'])/'snapshot':
        raise ValueError('FEEDBACK_USE_PREPARED_ENTRY')
    for key in ('manifest','snapshot_manifest','configuration','delivery'):checked_bytes(prep[key])
    for record in prep['source'].values():checked_bytes(record)
    backup=prep.get('baseline_usd_backup')
    if not isinstance(backup,dict):raise ValueError('FEEDBACK_BASELINE_USD_BACKUP_REQUIRED')
    delivery_before=load_record(prep['delivery'])
    if backup['sha256']!=delivery_before['files']['usd']['sha256'] or backup['bytes']!=delivery_before['files']['usd']['bytes']:
        raise ValueError('FEEDBACK_BASELINE_USD_BACKUP_MISMATCH')
    checked_bytes(backup)
    budget=ScopeBudget(root/'scope.json');budget.limits=copy.deepcopy(budget.native.scope['budget']);budget.available(starts=5)
    journal=Journal(root,path)
    if journal.value['stages']:return {'state':'QUERY_REQUIRED','journal':str(journal.path)}
    os.environ.clear();os.environ.update(prep['environment'])
    project=Path(prep['project']);control=Path(prep['control']);delivery=load_record(prep['delivery'])
    data={'root':budget.native.root,'project':project,'control':control,'manifest':json.loads((control/'run.json').read_text()),
        'scope':budget.scope,'scope_path':root/'scope.json','scope_sha256':budget.binding['sha256']}
    cleanup={};graph_id=prep['source_graph']['graph_id']
    try:
        with feedback_facade(prep) as facade:
            journal.action('baseline_reopen',lambda:facade.task_reopen(prep['baseline']['saved_scene_id']))
            old=journal.action('version_before',lambda:facade.graph_version(graph_id))
            feedback=journal.action('feedback',lambda:facade.feedback_edit(graph_id,'light',prep['target'],prep['baseline']['task_id']))
            if feedback['state']!='COMPLETE' or feedback['version']!=old['version']+1:raise ValueError('FEEDBACK_CONTENT_VERSION_REQUIRED')
            if feedback['before'][EXPOSURE]!=prep['baseline_exposure'] or feedback['after'][EXPOSURE]!=1.0 or feedback['after'][GATE]!='set':
                raise ValueError('FEEDBACK_NATIVE_EXPOSURE_REQUIRED')
            journal.action('old_artifact_invalidated',lambda:{'usable':facade.artifact_registry.verify(delivery['artifact_id'])['usable']})
            if journal.value['stages']['old_artifact_invalidated']['result']['usable']:raise ValueError('FEEDBACK_OLD_OUTPUT_NOT_INVALIDATED')
            # 再次提交同值只读回已有完整版本，不重复原生写入或新增版本。
            repeated=journal.action('same_value_replay',lambda:facade.feedback_edit(graph_id,'light',prep['target'],prep['baseline']['task_id']))
            if not repeated.get('replayed') or repeated['version']!=feedback['version']:raise ValueError('FEEDBACK_IDEMPOTENCE_REQUIRED')
            saved=journal.action('save',facade.task_save)
            roles={n['role']:n['path'] for n in saved['scene_contract']['nodes']}
            journal.action('edit_host_stop',lambda:_stop_host(data,'houdini'))
        with feedback_facade(prep) as facade:
            journal.action('cold_reopen',lambda:facade.task_reopen(saved['saved_scene_id']))
            actual=journal.action('cold_exposure',lambda:facade.host_client.call('node.parms',{'path':roles['light'],'names':[EXPOSURE,GATE]}))
            if actual['parms']!=feedback['after']:raise ValueError('FEEDBACK_COLD_EXPOSURE_MISMATCH')
            rendered=journal.action('render',lambda:facade.houdini_render_bounded('disklight_feedback_render',saved['saved_scene_id'],roles['render'],
                str(project/'saves/main.%04d.exr'),[1],min(120,budget.remaining())))
            journal.action('render_completed',lambda:_poll(facade,'operation_query',rendered['operation_id'],('operation','state'),budget))
            journal.action('render_host_stop',lambda:_stop_host(data,'houdini'))
            # 只允许恢复执行前保存的相同 SHA 原字节，不接受语义等价替代件。
            original_usd=delivery['files']['usd'];raw=checked_bytes(backup)
            current_usd=Path(original_usd['path'])
            if file_record(current_usd)['sha256']!=original_usd['sha256']:
                exported=project/'saves/main.usd'
                if exported.exists():raise ValueError('FEEDBACK_USD_ARCHIVE_ALREADY_EXISTS')
                exported.write_bytes(current_usd.read_bytes())
                with current_usd.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            checked_bytes(original_usd)
            verified=journal.action('verify',lambda:facade.verify_render_output('disklight_feedback_verify',rendered['operation_id']))
            image=verified['execution_fact']['metadata']['1']
            artifact=journal.action('register',lambda:facade.register_render_artifact(delivery['artifact_id'],'preview_temp',str(project/'saves/main.%04d.exr'),[1],
                image['colorspace'],image['premultiplied'],'disklight_feedback_verify'))
            if artifact['version']!=delivery['artifact_version']+1:raise ValueError('FEEDBACK_ARTIFACT_VERSION_REQUIRED')
            consumed=journal.action('consume',lambda:facade.consume_artifact(delivery['artifact_id']))
            if not consumed.get('usable_as_render_input') or consumed['registry_operation_receipt']['version']!=artifact['version']:raise ValueError('FEEDBACK_NEW_INPUT_REQUIRED')
            def nuke_prepare():
                client=facade.nuke_client;output=str(project/'saves/nuke.%04d.exr')
                client.call('set_knob',{'node':'Write1','knob':'file_type','value':'exr'})
                binding=client.render_binding(facade.pipeline_task_id,output,[1],consumed['colorspace'],consumed['premultiplied'],artifact_binding=consumed)
                for knob,value in (('channels','rgba'),('metadata','all metadata')):client.call('set_knob',{'node':'Write1','knob':knob,'value':value})
                script=project/'saves/composite.nk';client.call('save_script',{'path':str(script),'overwrite':False})
                return {'script':file_record(script),'binding':binding}
            journal.action('nuke_prepare',nuke_prepare)
            nuke=journal.action('nuke_render',lambda:facade.nuke_render_bounded('disklight_feedback_nuke',str(project/'saves/nuke.%04d.exr'),[1],artifact_id=artifact['artifact_id']))
            journal.action('nuke_completed',lambda:_poll(facade,'operation_query',nuke['operation_id'],('operation','state'),budget))
            journal.action('nuke_stop',lambda:_stop_host(data,'nuke'))
            differences=journal.action('compare',lambda:{'old_to_new':compare_files(delivery['files']['main_exr']['path'],str(project/'saves/main.0001.exr')),
                'new_to_nuke':compare_files(str(project/'saves/main.0001.exr'),str(project/'saves/nuke.0001.exr'),require_identical=True)})
            if differences['old_to_new']['different_samples']==0 or differences['new_to_nuke']['state']!='PASS':raise ValueError('FEEDBACK_IMAGE_EFFECT_REQUIRED')
            for record in delivery['files'].values():checked_bytes(record)
            state=budget.native.snapshot()
            if any(t.get('stopped_at') is None for t in state['tickets']):raise ValueError('FEEDBACK_ALL_STOPS_REQUIRED')
            result={'schema':'bridge.disklight-feedback-result/1','state':'FEEDBACK_AND_DOWNSTREAM_COMPLETE',
                'task_id':facade.pipeline_task_id,'graph_id':graph_id,'feedback':feedback,'artifact':artifact,
                'saved_scene_id':saved['saved_scene_id'],'files':{'hip':file_record(saved['path']),
                    'nuke_script':file_record(project/'saves/composite.nk'),'main_exr':file_record(project/'saves/main.0001.exr'),
                    'nuke_exr':file_record(project/'saves/nuke.0001.exr')},'comparisons':differences,
                'nuke_operation_id':nuke['operation_id'],'scope':state,'initial_starts':prep['initial_starts'],
                'initial_seconds':prep['initial_seconds'],'historical_files_unchanged':True,'human_visual_review':'PENDING_USER'}
            journal.action('complete',lambda:result);write_new(root/'feedback-result.json',result)
            return {'state':result['state'],'result':str(root/'feedback-result.json'),'new_starts':state['dcc_starts']-prep['initial_starts']}
    except BaseException as exc:
        write_new(root/'feedback-error.json',{'error':type(exc).__name__,'detail':str(exc)})
        raise
    finally:
        for kind in ('nuke','houdini'):
            try:cleanup[kind]=_stop_host(data,kind)
            except BaseException as exc:cleanup[kind]={'error':str(exc)}
        write_new(root/'feedback-cleanup.json',cleanup)


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--delivery',required=True);p.add_argument('--namespace',required=True);p.add_argument('--instruction',required=True);p.add_argument('--finish-preparation',action='store_true')
    p=sub.add_parser('run');p.add_argument('--preparation',required=True)
    args=parser.parse_args()
    result=prepare(args.delivery,args.namespace,args.instruction,finish_preparation=args.finish_preparation) if args.command=='prepare' else run(args.preparation)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
