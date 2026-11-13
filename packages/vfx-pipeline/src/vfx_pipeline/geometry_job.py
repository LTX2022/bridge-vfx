"""几何创作的可信作业编排；复用正式图/宿主/登记核心，连接只读作业结果。"""
from __future__ import annotations
import copy, hashlib, importlib.util, json, math, os, re, secrets, signal, sqlite3, sys, time
from contextlib import contextmanager, closing, nullcontext
from pathlib import Path
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory
from dcc_task_runtime.native_scope import (NativeScope, GEOMETRY_SCOPE_SCHEMA, GEOMETRY_RESOURCE_PROFILE,
    GEOMETRY_SCENE_PROFILE, GEOMETRY_BUDGET, GEOMETRY_ROLE_SECONDS)
from houdini_bridge.official_karma_observation import file_record, checked_bytes

ROOT=Path(__file__).resolve().parents[4]


def _object(path):
    """控制文档只接收无重复键的JSON对象。"""
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('GEOMETRY_DUPLICATE_KEY')
            value[key]=item
        return value
    value=json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=unique)
    if not isinstance(value,dict):raise ValueError('GEOMETRY_OBJECT_REQUIRED')
    return value


def _write(path,value,*,new=False):
    """完整内容原子发布；正式结果和准备不覆盖。"""
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('GEOMETRY_PATH_LINK')
    if new and path.exists():raise ValueError('GEOMETRY_ALREADY_EXISTS')
    ensure_private_directory(path.parent)
    atomic_write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode(),owned_root=path.parent)
    return file_record(path)


def _binding(record):return {k:record[k] for k in ('path','sha256')}


def _tools():
    """工具只能从本安装runtime的固定目录导入，不使用开发PYTHONPATH。"""
    path=str(ROOT/'tools')
    if path not in sys.path:sys.path.insert(0,path)


def _backup_database(source,target):
    """复制已有任务的SQLite一致性快照，不重建任务身份或遗失WAL。"""
    source,target=Path(source),Path(target)
    if target.exists():raise ValueError('GEOMETRY_TASK_DATABASE_EXISTS')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old, closing(sqlite3.connect(target)) as new:
        old.backup(new)


def bound_pipeline_task(manifest,control):
    """正式装配复用准备者登记的同一任务；原接口没有此字段时保持原路线。"""
    from .service import ModelSafePipeline
    record=manifest.get('geometry_task_binding');binding=json.loads(checked_bytes(record))
    native=NativeScope(manifest['production_host']['native_scope']);control=Path(control)
    from dcc_task_runtime.geometry_feedback_scope import RESOURCE_PROFILE as FEEDBACK_PROFILE
    feedback=native.resource_profile==FEEDBACK_PROFILE
    source_binding=None
    if feedback:
        from .geometry_feedback import validate_authority
        authority=validate_authority(native.scope['feedback_authority'])
        source_binding=json.loads(checked_bytes(authority['source_preparation']))['task_binding']
    if ((native.scope.get('schema')!=GEOMETRY_SCOPE_SCHEMA and not feedback) or manifest.get('domain_pack')!='material_lookdev_v1'
            or manifest.get('application')!='pipeline' or binding.get('schema')!='bridge.geometry-task-binding/1'
            or binding.get('task_id')!=native.scope['task_id']
            or (record!=source_binding if feedback else Path(record['path'])!=native.root/'task-binding.json')
            or (not feedback and Path(binding.get('task_database',''))!=native.root/'task/pipeline.sqlite3')
            or not (control/'pipeline.sqlite3').is_file() or not control.is_relative_to(native.root)):
        raise ValueError('GEOMETRY_TASK_BINDING_INVALID')
    pipeline=ModelSafePipeline(control/'pipeline.sqlite3');task=pipeline.store.get_task(binding['task_id'])
    if (canonical_sha256(task['spec'])!=binding.get('spec_sha256')
            or task['spec']['domains']!=[{'identifier':'material_lookdev_v1','version':'1.0.0'}]):
        raise ValueError('GEOMETRY_TASK_SPEC_CHANGED')
    return pipeline,binding['task_id']


def _nuke_template_patterns(original):
    """准备时将已验证单帧产物与真实NK的Read/Write逐项绑定，兼容retry文件名。"""
    template=checked_bytes(original['files']['nk']).decode('utf-8')
    patterns={}
    for kind in ('main','nuke'):
        path=Path(original['files'][kind]['path'])
        if not path.name.endswith('.0001.exr'):raise ValueError('GEOMETRY_FRAME_ONE_TEMPLATE_REQUIRED')
        patterns[kind]=str(path.with_name(path.name[:-9]+'.%04d.exr'))
    reads=re.findall(r'^Read \{\n(.*?)^\}',template,re.M|re.S)
    writes=re.findall(r'^Write \{\n(.*?)^\}',template,re.M|re.S)
    roots=re.findall(r'^Root \{\n(.*?)^\}',template,re.M|re.S)
    if (len(reads)!=1 or len(writes)!=1 or len(roots)!=1
            or re.findall(r'^ file (.+)$',reads[0],re.M)!=[patterns['main']]
            or re.findall(r'^ file (.+)$',writes[0],re.M)!=[patterns['nuke']]
            or len(re.findall(r'^ name (.*\.nk)$',roots[0],re.M))!=1
            or template.count(patterns['main'])!=1 or template.count(patterns['nuke'])!=2):
        raise ValueError('GEOMETRY_NK_TEMPLATE_IDENTITY_REQUIRED')
    return patterns


def prepare_project(directory,source_preparation,reference_front,reference_perspective,criteria,*,instruction):
    """零DCC准备：核验旧完成事实，新任务/新范围仅引用旧rig、校准和模板。"""
    _tools()
    from .creative_session import CreativeSession
    from .service import ModelSafePipeline
    from .artifact_registry import ArtifactRegistry
    from houdini_bridge.geometry_render_scene import from_source
    from houdini_bridge.alpha_reuse import make_reuse_binding
    from dcc_task_runtime.render_profiles import output_policy
    from continue_official_karma import _runtime_environment
    root=Path(directory)
    if root!=root.resolve() or root.exists() or not root.is_absolute() or not root.parent.is_dir():
        raise ValueError('GEOMETRY_FRESH_ROOT_REQUIRED')
    source=CreativeSession(Path(source_preparation));oldstate=source._read()
    op=oldstate['completed'][-1];oldjob=oldstate['jobs'][op];old_directory=source._execution_directory(oldjob)
    original=_object(old_directory/'result.json');source._validate_completion(old_directory,original)
    template_patterns=_nuke_template_patterns(original)
    oldnative=NativeScope(source.prep['scope']);oldnative.completed_snapshot()
    if root.is_relative_to(oldnative.root) or oldnative.root.is_relative_to(root):raise ValueError('GEOMETRY_SOURCE_ROOT_OVERLAP')
    # 旧rig身份由操作者提供的评审准备记录指定，内容不包含模型的预期节点图。
    assessment=_object(criteria);rig_record=assessment['source_rig'];checked_bytes(rig_record)
    configuration=from_source(rig_record)
    ensure_private_directory(root);ensure_private_directory(root/'media');ensure_private_directory(root/'task')
    media={}
    for name,path in [('reference_front',reference_front),('reference_perspective',reference_perspective)]:
        raw=Path(path).read_bytes()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw)>2*1024*1024:raise ValueError('GEOMETRY_REFERENCE_PNG_REQUIRED')
        target=root/'media'/(name+'.png');target.write_bytes(raw);media[name]=file_record(target)
    criteria_record=_write(root/'private-evaluation.json',assessment,new=True)
    public_brief=('Bridge测试参考，不是官方教程。制作三件式门架：两根直立方柱和一根水平横梁；'
        '参考正视和三分之四图自行决定部件比例、节点、参数及连接。单位metres、Y-up，地面Y=0，门架正面为X/Y、深度沿Z，'
        '原点在门洞地面中心。整体高度与外宽各约1.2。组件左右对称、柱脚接地、梁柱接合，中间留净空；'
        '保留独立可编辑节点。相机、灯光、地面、材质和曝光由固定rig提供，不修改。')
    pipeline=ModelSafePipeline(root/'task/pipeline.sqlite3')
    refs=[{'asset_id':k,'kind':'image','uri':v['path'],'sha256':v['sha256']} for k,v in media.items()]
    spec={'schema_version':'2.0','task_type':'visual.reference_rebuild','intent':public_brief,
        'target':{'application':'pipeline','scene_mode':'current'},'references':refs,
        'domains':[{'identifier':'material_lookdev_v1','version':'1.0.0'}],
        'feedback':'bounded geometry test','render':{},'delivery':{'composite':False}}
    task_id=pipeline.reference_task_start(spec,idempotency_key='geometry:'+root.name,purpose='graph_construction')['task_id']
    reuse=_write(root/'source-reuse.json',{'schema':'bridge.geometry-reuse-source/1','task_id':task_id,
        'source_preparation':source.preparation,'source_result':file_record(old_directory/'result.json'),
        'source_scope':file_record(oldnative.path),'source_hip':original['files']['hip'],
        'source_rig':rig_record,'source_nk':original['files']['nk'],
        'source_accounting_state':file_record(oldnative.state_path),'source_completed_tickets':len(oldnative.completed_snapshot()['tickets'])},new=True)
    key=secrets.token_bytes(32)
    scope={'schema':GEOMETRY_SCOPE_SCHEMA,'resource_profile':GEOMETRY_RESOURCE_PROFILE,'scene_profile':GEOMETRY_SCENE_PROFILE,
        'scope_id':'geometry-'+secrets.token_hex(12),'task_id':task_id,'output_root':str(root),
        'budget':copy.deepcopy(GEOMETRY_BUDGET),'role_seconds':copy.deepcopy(GEOMETRY_ROLE_SECONDS),
        'versions':{'houdini':'21.0.631','nuke':'17.0v1'},'hosts':copy.deepcopy(oldnative.scope['hosts']),
        'project_color':copy.deepcopy(oldnative.scope['project_color']),'native_color_tokens':copy.deepcopy(oldnative.scope['native_color_tokens']),
        'evidence_source':'real_host','execution_authorized':True,'status':'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION',
        'authorization':{'authority':'current_user_instruction','instruction':instruction},'source_reuse':reuse,
        'accounting':{'key_path':str(root/'.native-control/key'),'key_sha256':hashlib.sha256(key).hexdigest()}}
    if 'process_image_policy' in oldnative.scope:scope['process_image_policy']=copy.deepcopy(oldnative.scope['process_image_policy'])
    scope_record=_write(root/'scope.json',scope,new=True);native=NativeScope.initialize(_binding(scope_record),key=key)
    config_record=_write(root/'geometry-configuration.json',configuration,new=True)
    task_binding=_write(root/'task-binding.json',{'schema':'bridge.geometry-task-binding/1','task_id':task_id,
        'task_database':str(root/'task/pipeline.sqlite3'),'spec_sha256':canonical_sha256(pipeline.store.get_task(task_id)['spec'])},new=True)
    old_manifest=json.loads(checked_bytes(source.prep['runtime_manifest']));hosts={}
    for kind,field in [('houdini','production_host'),('nuke','production_nuke')]:
        cfg=copy.deepcopy(old_manifest[field])
        for name in ('plugin_build','controller_root','expected_identity','port','transport','host','work_dir','input_artifact_source','snapshot'):
            cfg.pop(name,None)
        cfg.update(task_root=str(root),native_scope=native.binding,session_seconds=240 if kind=='houdini' else 120,
            resource_budget={'roots':[str(root)],'max_bytes':GEOMETRY_BUDGET['max_disk_bytes'],'native_scope':native.binding},
            feedback_ledger_root=str(root/'artifact_ledger'))
        if kind=='houdini':
            alpha=cfg['alpha_calibration'];proof=alpha.pop('plugin_reuse');alpha.pop('calibration_source',None)
            cfg['alpha_calibration']=make_reuse_binding(alpha,proof['source_plugin'],file_record(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py'))
            cfg['output_acceptance']=output_policy(GEOMETRY_SCENE_PROFILE)
        hosts[kind]=cfg
    ArtifactRegistry(root/'artifact_ledger')
    environment=_runtime_environment(scope)
    prep={'schema':'bridge.geometry-creative-preparation/1','task_id':task_id,'scope':native.binding,
        'configuration':config_record,'source_reuse':reuse,'worker':str(ROOT/'tools/run_geometry_creative.py'),
        'supervisor_python':scope['hosts']['supervisor_python']['path'],'environment':environment,'media':media,
        'public_brief':public_brief,'feedback':'门洞净宽增加20%；总高度和立柱粗细保持；横梁随门洞加宽；柱脚接地并继续与横梁接合。',
        'ledger_root':str(root/'artifact_ledger'),'hosts':hosts,'task_binding':task_binding,'criteria':criteria_record,
        'nuke_template':original['files']['nk'],'template_main_pattern':template_patterns['main'],
        'template_nuke_pattern':template_patterns['nuke'],
        'display':source.prep['display'],'model_route':{'route':'CodexDelegatedMCPRoute','selected_model':'gpt-6-luna','reasoning_effort':'low','provider_identity':'unknown'}}
    return _write(root/'geometry-preparation.json',prep,new=True)


class _Cancelled(ValueError):pass


class JobJournal:
    """每阶段先写INTENT；完成阶段只读取原结果，不自动重放未知副作用。"""
    def __init__(self,directory,job_record):
        self.directory=Path(directory);self.path=self.directory/'incremental-state.json';self.started=time.monotonic()
        self.value=_object(self.path) if self.path.exists() else {'schema':'bridge.geometry-job-journal/1','job':job_record,'stages':{}}
        if self.value.get('job')!=job_record:raise ValueError('GEOMETRY_JOB_IDENTITY_CHANGED')
    def checkpoint(self):
        if (self.directory/'cancel-request.json').exists():raise _Cancelled('GEOMETRY_CANCEL_REQUESTED')
        if time.monotonic()-self.started>900:raise TimeoutError('GEOMETRY_CONTROLLER_DEADLINE')
    def action(self,name,fn):
        self.checkpoint();stage=self.value['stages'].get(name)
        if stage is not None:
            if stage.get('state')=='DONE':return copy.deepcopy(stage['result'])
            raise ValueError('GEOMETRY_UNCONFIRMED_STAGE_'+name.upper())
        self.value['stages'][name]={'state':'INTENT','started_at':time.time()};_write(self.path,self.value)
        result=fn();self.value['stages'][name].update(state='DONE',finished_at=time.time(),result=result);_write(self.path,self.value)
        return result


def _poll_graph(facade,operation,journal):
    """仅观察原GraphRun；等待不增加模型请求或重派。"""
    while True:
        journal.checkpoint();result=facade.graph_status(operation)
        if result.get('completed') or result.get('terminal'):
            if result.get('success') is not True or result.get('stop_confirmed') is not True:
                raise ValueError('GEOMETRY_GRAPH_NOT_SUCCEEDED')
            return result
        if result.get('state') in ('FAILED','CANCELLED','RECONCILIATION_REQUIRED'):raise ValueError('GEOMETRY_GRAPH_FAILED')
        time.sleep(.2)


def _poll_render(facade,operation,journal):
    """实际renderer仍由原受监督宿主拥有，调用端只查原操作。"""
    while True:
        journal.checkpoint();result=facade.operation_query(operation);state=(result.get('operation') or result).get('state')
        if state=='COMPLETED':return result
        if state in ('FAILED','CANCELLED','UNKNOWN','RECONCILE'):raise ValueError('GEOMETRY_RENDER_'+state)
        time.sleep(.2)


def prepare_execution(prep,job):
    """每轮采用最终runtime的新控制快照，任务身份和账本延续同一新几何任务。"""
    _tools()
    directory=Path(job['directory']);root=Path(prep['scope']['path']).parent
    if 'feedback_authority' in job:
        from .geometry_feedback import verify_job
        verify_job(job,NativeScope(prep['scope']),for_execution=True,runtime_root=ROOT,require_dispatch=False)
    if 'seed_cold_source' in job:
        from .geometry_seed_cold_resume import verify_job,validate
        native=NativeScope(prep['scope']);details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        authority,_=validate(job['preparation'],job['runtime_continuation'],native)
        value={'schema':'bridge.geometry-job-preparation/1','job':file_record(directory/'job.json'),
            'project':details['project'],'control':details['control'],'seed_cold_source':job['seed_cold_source'],'consumer_runtime':authority['consumer_runtime']}
        path=directory/'job-preparation.json'
        if path.exists():
            saved=_object(path)
            if saved!=value:raise ValueError('GEOMETRY_JOB_PREPARATION_CHANGED')
            return saved
        _write(path,value,new=True);return value
    if 'nuke_save_source' in job:
        from .geometry_nuke_save_resume import verify_job,validate
        native=NativeScope(prep['scope']);details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        authority,_=validate(job['preparation'],job['runtime_continuation'],native)
        value={'schema':'bridge.geometry-job-preparation/1','job':file_record(directory/'job.json'),
            'project':details['project'],'control':details['control'],'nuke_save_source':job['nuke_save_source'],
            'consumer_runtime':authority['consumer_runtime']}
        path=directory/'job-preparation.json'
        if path.exists():
            saved=_object(path)
            if saved!=value:raise ValueError('GEOMETRY_JOB_PREPARATION_CHANGED')
            return saved
        _write(path,value,new=True);return value
    if 'registration_source' in job:
        from .geometry_registration_resume import verify_job,validate
        native=NativeScope(prep['scope']);details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        authority,_=validate(job['preparation'],job['runtime_continuation'],native)
        value={'schema':'bridge.geometry-job-preparation/1','job':file_record(directory/'job.json'),
            'project':details['project'],'control':details['control'],'registration_source':job['registration_source'],
            'consumer_runtime':authority['registration_runtime']}
        path=directory/'job-preparation.json'
        if path.exists():
            saved=_object(path)
            if saved!=value:raise ValueError('GEOMETRY_JOB_PREPARATION_CHANGED')
            return saved
        _write(path,value,new=True);return value
    if 'nuke_source' in job:
        from .geometry_nuke_resume import verify_job
        details=verify_job(job,NativeScope(prep['scope']),for_execution=True,runtime_root=ROOT)
        path=directory/'job-preparation.json'
        if path.exists():
            saved=_object(path)
            if saved.get('job')!=file_record(directory/'job.json') or saved.get('nuke_source')!=job['nuke_source']:
                raise ValueError('GEOMETRY_JOB_PREPARATION_CHANGED')
            return saved
        value={'schema':'bridge.geometry-job-preparation/1','job':file_record(directory/'job.json'),
               'project':details['project'],'control':details['control'],'nuke_source':job['nuke_source']}
        _write(path,value,new=True);return value
    from prepare_workbuddy_graph import prepare_graph
    project=directory/'project';control=project/'control'
    if 'source_checkpoint' in job:
        from dcc_task_runtime.geometry_recovery import verify_checkpoint_job
        verify_checkpoint_job(job,NativeScope(prep['scope']))
    if 'render_source' in job:
        from .geometry_render_resume import verify_job
        verify_job(job,NativeScope(prep['scope']))
    path=directory/'job-preparation.json'
    if path.exists():
        saved=_object(path)
        if saved['job']!=file_record(directory/'job.json'):raise ValueError('GEOMETRY_JOB_PREPARATION_CHANGED')
        return saved
    if project.exists():raise ValueError('GEOMETRY_PARTIAL_PREPARATION_REQUIRES_RECONCILIATION')
    hosts=copy.deepcopy(prep['hosts'])
    if 'feedback_authority' in job:
        hosts['houdini']['controller_root']=str(control)
    hosts['houdini']['alpha_calibration']['plugin_reuse']['active_plugin']['path']=str(control/'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
    config=prep['configuration'];construction=[{'index':0,'asset_id':'geometry-rig','semantic_role':'render_scene_configuration',
        'source_uri':config['path'],'bytes':config['bytes'],'sha256':config['sha256']}]
    prepare_graph(project,app=None,scheduler_root=root/'scheduler',execution_profile=True,render_profile=True,
        production_host_config=hosts['houdini'],production_nuke_config=hosts['nuke'],construction_input_manifest=construction)
    manifest=_object(control/'run.json');manifest.update(domain_pack='material_lookdev_v1',
        requested_route=prep['model_route']['route'],requested_model=prep['model_route']['selected_model'],geometry_task_binding=prep['task_binding'])
    assets=[]
    for name,record in prep['media'].items():
        target=control/'assets'/(name+'.png');target.write_bytes(checked_bytes(record))
        from .media_readiness import FixedPngDecoder
        decoded=FixedPngDecoder().decode(target)
        assets.append({'asset_id':name,'file':'assets/'+name+'.png','sha256':record['sha256'],
            'classification':'controller_generated_synthetic','mime_type':'image/png',
            'width':decoded['width'],'height':decoded['height']})
    # 生成器默认图只用于软件示例；正式几何作业只登记本题真实测试参考字节。
    for p in (control/'assets').glob('*.png'):
        if p.name not in {x['asset_id']+'.png' for x in assets}:p.unlink()
    manifest['assets']=assets;_write(control/'run.json',manifest)
    binding=json.loads(checked_bytes(prep['task_binding']));_backup_database(binding['task_database'],control/'pipeline.sqlite3')
    value={'schema':'bridge.geometry-job-preparation/1','job':file_record(directory/'job.json'),'project':str(project),'control':str(control),
        'manifest':file_record(control/'run.json'),'snapshot_manifest':file_record(control/'snapshot-manifest.json')}
    if 'source_checkpoint' in job:value['source_checkpoint']=copy.deepcopy(job['source_checkpoint'])
    if 'render_source' in job:value['render_source']=copy.deepcopy(job['render_source'])
    _write(path,value,new=True);return value


def _source_receipt(directory,prep,jobprep,receipt,native):
    """固定建图完成时的原签名票据前缀，后续同任务新增票据不改此来源。"""
    from .official_graph_resume import inspect_resume_source
    directory=Path(directory);native.completed_snapshot()
    state=directory/'graph-source-accounting.json';state.write_bytes(native.state_path.read_bytes());state.chmod(0o600)
    execution={'schema':'bridge.geometry-execution-preparation/1','state':'PREPARED','project':jobprep['project'],
        'scope':native.binding,'manifest':jobprep['manifest'],'snapshot_manifest':jobprep['snapshot_manifest'],
        'configuration':prep['configuration'],'scheduler_root':str(native.root/'scheduler'),'accounting_snapshot':file_record(state)}
    record=_write(directory/'geometry-execution-preparation.json',execution,new=True)
    _write(directory/'graph-source-journal.json',{'preparation':record,'stages':{'build_completed':{'state':'DONE','result':receipt}}},new=True)
    return {'preparation':record,'operation_id':receipt['operation_id']}


def _copy_feedback(source,facade):
    """仅继承本新任务原内容版本行，禁止生成器把反馈基线重置为零。"""
    from .feedback_versions import FeedbackVersions
    FeedbackVersions(facade);path=Path(source)/'diagnostic.sqlite3'
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as old:
        rows=old.execute('SELECT graph_id,version,state,payload FROM feedback_versions').fetchall()
    with facade._connect() as db:
        for row in rows:
            existing=db.execute('SELECT state,payload FROM feedback_versions WHERE graph_id=? AND version=?',row[:2]).fetchone()
            if existing is not None and tuple(existing)!=tuple(row[2:]):raise ValueError('GEOMETRY_FEEDBACK_SOURCE_CHANGED')
            db.execute('INSERT OR IGNORE INTO feedback_versions VALUES(?,?,?,?)',row)


def _data(prep,jobprep):
    return {'root':Path(prep['scope']['path']).parent,'project':Path(jobprep['project']),'control':Path(jobprep['control']),
        'scope_path':Path(prep['scope']['path']),'scope_sha256':prep['scope']['sha256']}


def _stop(prep,jobprep,kind):
    _tools();from run_controlled_engineering import _stop_host
    return _stop_host(_data(prep,jobprep),kind)


@contextmanager
def _resume(prep,jobprep,source,saved,history):
    """复用同核恢复装配；只有执行控制器可持有该上下文。"""
    from .official_graph_resume import resume_graph_facade
    from .artifact_registry import ArtifactRegistry
    control=Path(jobprep['control']);root=Path(prep['scope']['path']).parent
    # 复制本任务新增保存旁车，原条目保留；原保存文件本身不改写。
    destination=control/'houdini-instances/fx_operations';destination.mkdir(parents=True,exist_ok=True)
    for path in (Path(history)/'houdini-instances/fx_operations').glob('*.saves.json'):
        target=destination/path.name
        if target!=path and not target.exists():target.write_bytes(path.read_bytes())
    checkpoint_copy=('source_checkpoint' in jobprep or 'render_source' in jobprep or prep.get('feedback_authority') is not None
                     or (Path(history)/'checkpoint-task-source.json').is_file())
    authority=prep.get('feedback_authority')
    with resume_graph_facade(control/'run.json',source,repo_root=control/'snapshot',scheduler_root=root/'scheduler',
            checkpoint_task_copy=checkpoint_copy,**({'feedback_authority':authority} if authority is not None else {})) as facade:
        facade.save_root=Path(jobprep['project'])/'saves';facade.save_root.mkdir(exist_ok=True)
        facade.artifact_registry=ArtifactRegistry(prep['ledger_root']);facade.host_client.bind_artifact_registry(facade.artifact_registry)
        _copy_feedback(history,facade);facade._save_receipt(saved)
        yield facade


def _accepted_result(preparation_record,operation_id):
    """反馈测量只读取已认证原结果，前端state的新摘要不能替代接纳凭据。"""
    from .geometry_session import GeometrySession
    session=GeometrySession(Path(preparation_record['path']))
    if session.preparation!=preparation_record:raise ValueError('GEOMETRY_ACCEPTED_PREPARATION_CHANGED')
    entry=session._read()['jobs'].get(operation_id)
    if not isinstance(entry,dict) or entry.get('state')!='COMPLETE':
        raise ValueError('GEOMETRY_ACCEPTED_BASE_REQUIRED')
    observed=session.query(operation_id)
    if (observed.get('action')!='ACCEPTED_RESULT_OBSERVED' or observed.get('native_dispatch_attempted') is not False):
        raise ValueError('GEOMETRY_ACCEPTED_BASE_REQUIRED')
    return json.loads(checked_bytes(observed['original_result']))


def _geometry(facade,saved,prep,job,phase,transition=None):
    """真实原生观测经控制器认证；接纳时可脱离宿主独立复验。"""
    from .geometry_native_evidence import capture
    return capture(facade,saved,prep['scope'],job['operation_id']+'_'+phase,phase,transition=transition)


def _verify_cold_geometry(value,reopened):
    """观测必须来自本次独立冷开后同一宿主世代与场景epoch。"""
    actual=value.get('operation_receipt',{}).get('host_identity')
    expected=(reopened.get('scene_transition') or {}).get('after_identity')
    if not isinstance(actual,dict) or not isinstance(expected,dict) or actual!=expected:
        raise ValueError('GEOMETRY_COLD_HOST_IDENTITY_REQUIRED')


def _cold_reopen(facade,saved,configuration):
    """独立进程原生冷开须验证节点、参数、连接及完全相同的冻结配置。"""
    from houdini_bridge.operation_receipts import operation_receipt_sha256
    value=facade.task_reopen(saved['saved_scene_id']);transition=value.get('scene_transition') or {}
    if (any(value.get(k) is not True for k in ('nodes_verified','parameters_verified','connections_verified'))
            or value.get('load_warnings')!=[] or value.get('sha256')!=saved['sha256']
            or value.get('scene_contract_sha256')!=saved['scene_contract_sha256']
            or transition.get('state')!='COMPLETED' or transition.get('load_count')!=1
            or transition.get('operation_receipt_sha256')!=operation_receipt_sha256(transition)
            or value.get('frozen_scene_parameters')!=saved['scene_contract'].get('frozen_scene_parameters')
            or (value.get('frozen_scene_parameters') or {}).get('configuration_sha256')!=canonical_sha256(configuration)
            or transition.get('after_identity',{}).get('launch_nonce')==saved.get('operation_receipt',{}).get('host_identity',{}).get('launch_nonce')):
        raise ValueError('GEOMETRY_ACTUAL_COLD_REOPEN_REQUIRED')
    return value


def _load_nuke(prep):
    """使用当前控制快照的原Nuke插件/调度器和既有事实回调。"""
    from dcc_task_runtime.graph_scheduler import GraphScheduler
    spec=importlib.util.spec_from_file_location('_geometry_cold_nuke',ROOT/'plugins/nuke/nuke_bridge_addon.py')
    addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
    root=Path(prep['scope']['path']).parent;addon._RENDER_RECORDS_DIR=root/'state/nuke_renders'
    addon._NUKE_SCHEDULER=GraphScheduler(root/'scheduler')
    return addon


def _input_source(prep,jobprep,artifact,verified,registration_implementation=None):
    """只从原正式登记生成Nuke来源，模型不能提交输入来源或成功事实。"""
    control=Path(jobprep['control']);native=NativeScope(prep['scope'])
    source={'schema':'bridge.geometry-nuke-source/1','task_id':prep['task_id'],'artifact_id':artifact['artifact_id'],
        'artifact_version':artifact['version'],'producer_scope':file_record(native.path),'producer_control':str(control),
        'producer_ledger':prep['ledger_root'],'producer_manifest':file_record(control/'run.json'),
        'producer_snapshot_manifest':file_record(control/'snapshot-manifest.json'),
        'producer_deployment':file_record(control/'production-hosts.json'),
        'producer_owners':file_record(control/'host-state/houdini-operation-owners.json'),
        'registry_operation_receipt':artifact['registry_operation_receipt'],
        'producer_fact_sha256':canonical_sha256(verified['execution_fact'])}
    if registration_implementation is not None:
        source.update(schema='bridge.geometry-nuke-source/2',registration_implementation=registration_implementation)
    return _write(control/'geometry-input-source.json',source,new=True)


def _save_nuke(prep,job,jobprep,source_record,journal):
    """复用已冷开NK模板，仅替换本例路径，再由真实Nuke原生保存新工程。"""
    from .production_hosts import ensure_hosts
    from .workbuddy_assembly import production_nuke_client
    project=Path(jobprep['project']);control=Path(jobprep['control']);root=Path(prep['scope']['path']).parent
    template=checked_bytes(prep['nuke_template']).decode('utf-8');script=project/'saves/composite.nk';pattern=str(project/'saves/nuke.%04d.exr')
    oldname=re.findall(r'^ name (.*\.nk)$',template,re.M)
    if len(oldname)!=1 or template.count(prep['template_main_pattern'])!=1 or template.count(prep['template_nuke_pattern'])!=2:
        raise ValueError('GEOMETRY_NK_TEMPLATE_IDENTITY_REQUIRED')
    text=template.replace(prep['template_main_pattern'],str(project/'saves/main.%04d.exr')).replace(prep['template_nuke_pattern'],pattern).replace(oldname[0],str(script))
    seed=project/'saves/composite-seed.nk';seed.write_text(text,encoding='utf-8')
    nuke_control=Path(job['directory'])/'nuke-save-control';ensure_private_directory(nuke_control)
    cfg=copy.deepcopy(prep['hosts']['nuke']);cfg['input_artifact_source']=source_record
    consumer=(Path(jobprep['consumer_runtime']['package_root'])/'runtime' if 'consumer_runtime' in jobprep else control/'snapshot')
    _,bound=ensure_hosts(None,cfg,task_id=prep['task_id'],controller_root=nuke_control,repo_root=consumer,
        scheduler_root=root/'scheduler',application='nuke',host_kinds={'nuke'})
    boundary=production_nuke_client(bound,nuke_control/'nuke-state');boundary.bind_task(prep['task_id'])
    try:
        opened=boundary.call('open_script',{'path':str(seed),'sha256':file_record(seed)['sha256']})
        saved=boundary.call('save_script',{'path':str(script),'overwrite':False})
        if saved.get('path')!=str(script) or not script.is_file():raise ValueError('GEOMETRY_NK_NATIVE_SAVE_REQUIRED')
        return {'opened':opened,'saved':saved,'file':file_record(script),'pattern':pattern}
    finally:
        from nuke_bridge.task_host import stop
        ended=stop(bound['work_dir'])
        from dcc_task_runtime.owned_process import execution_returncode
        if not ended.get('stopped') or execution_returncode(ended['receipt'])!=0:raise ValueError('GEOMETRY_NUKE_SAVE_STOP_REQUIRED')


def _cold_nuke(prep,job,jobprep,source_record,saved,journal):
    """046只在controller验源一次；旧消费者入口保持原执行路径。"""
    authority=job.get('runtime_continuation') or {}
    if Path(authority.get('path','')).name not in ('geometry-cold-preflight-runtime-authorization.json','geometry-prelaunch-tail-authorization.json'):
        return _cold_nuke_execute(prep,job,jobprep,source_record,saved,journal)
    from nuke_bridge.task_host import _controller_cold_inputs
    native=NativeScope(prep['scope']);addon=_load_nuke(prep)
    with _controller_cold_inputs(source_record,scope=native,task_id=prep['task_id'],fallback=addon._nuke_operation_fact) as capability:
        return _cold_nuke_execute(prep,job,jobprep,source_record,saved,journal,_controller_cap=capability,_addon=addon)


def _cold_nuke_execute(prep,job,jobprep,source_record,saved,journal,*,_controller_cap=None,_addon=None):
    """原typed消费者的单票独立冷渲染，保持输入回执、颜色、停止和登记合同。"""
    _tools()
    from dcc_task_runtime import owned_process
    from nuke_bridge.task_host import input_artifact_registry
    from nuke_bridge.operation_receipts import freeze_agent_inputs,registered_input_contract
    from dcc_task_runtime.artifact_registry import frame_path
    from recover_disklight_nuke import cold_request_digest,cleanup_cold_attempt,assert_released_slot
    native=NativeScope(prep['scope']);root=native.root;control=Path(jobprep['control']);script=Path(saved['file']['path']);pattern=saved['pattern']
    source=json.loads(checked_bytes(source_record));addon=_load_nuke(prep) if _addon is None else _addon
    registry=(_controller_cap.registry if _controller_cap is not None else input_artifact_registry(source,scope=native,task_id=prep['task_id'],fallback=addon._nuke_operation_fact))
    addon._NUKE_ARTIFACT_REGISTRY=registry;artifact=registry.lookup(source['artifact_id'])
    actual=file_record(Path(frame_path(artifact['pattern'],1)))
    input_binding=freeze_agent_inputs(prep['task_id'],[{'role':'registered_main','path':artifact['pattern'],'artifact_id':artifact['artifact_id'],
        'frames':[{'frame':1,**actual}]}]);contract=registered_input_contract(input_binding,registry,task_id=prep['task_id'])
    if _controller_cap is not None:_controller_cap.freeze_contract(contract)
    context_value={'schema':'bridge.geometry-cold-context/1','native_scope':native.binding,
        'task_id':prep['task_id'],'input_artifact_source':source_record}
    if 'nuke_source' in job or ('seed_cold_source' in job and (control/'cold-context.json').exists()):
        # 原消费者续接及043已认证只读预检复用完全相同的上下文，不能覆盖不同输入。
        if _object(control/'cold-context.json')!=context_value:raise ValueError('GEOMETRY_COLD_CONTEXT_CHANGED')
        context=file_record(control/'cold-context.json')
    else:context=_write(control/'cold-context.json',context_value,new=True)
    os.environ['BRIDGE_CREATIVE_COLD_CONTEXT']=context['path'];os.environ['BRIDGE_CREATIVE_COLD_CONTEXT_SHA256']=context['sha256']
    if Path((job.get('runtime_continuation') or {}).get('path','')).name=='geometry-prelaunch-tail-authorization.json':
        from .geometry_prelaunch_tail import attempt_for
        attempt=attempt_for(job['preparation'],job['runtime_continuation'],native);request=attempt['request_id'];operation=attempt['operation_id']
    else:request=job['operation_id']+'_nuke';operation='nrend-'+hashlib.sha256(request.encode()).hexdigest()[:16]
    scene=file_record(script)['sha256'];owner='nuke:'+str(script)
    route=addon.configure_nuke_background_route(nuke_executable=native.scope['hosts']['nuke']['path'],
        worker_script=str(ROOT/'tools/nuke_owned_render_worker.py'),supervisor_executable=prep['supervisor_python'],software_api=False,
        resource_budget={'roots':[str(root)],'max_bytes':native.scope['budget']['max_disk_bytes'],'native_scope':native.binding})
    handle=task=permit=None;unstarted=False
    try:
        permit=addon._NUKE_SCHEDULER.reserve(owner,operation);snapshot=addon._snapshot_nuke_script(operation,str(script))
        task={'task_id':operation,'owner_task_id':prep['task_id'],'request_id':request,'entry':'render_write','task_key':'render_write',
            'node':'Write1','background':True,'frame_range':[1,1],'frame_set':[1],'stride':1,'active_frames':[1],
            'pattern':pattern,'scene_fingerprint':scene,'script_snapshot':snapshot,'input_contract':contract,'input_binding':input_binding,
            'project_color':artifact['project_color'],'output_verification':artifact['output_verification'],'dependencies':[scene]+artifact['dependencies'],
            'delivery_confirmations':{'colorspace_confirmed':True,'premultiplied_confirmed':True,'dependencies_confirmed':True},
            'started_at_epoch':time.time(),'cancel_requested':False,'cancel_requested_at':None,'stop_confirmed_at':None,
            'state':'RUNNING','background_backend':'owned','budget_seconds':120,'colorspace':artifact['colorspace'],'premultiplied':artifact['premultiplied'],
            'slot':{'owner_root':owner,'operation_id':operation,'token':permit['token'],'generation':permit['generation']}}
        task['request_sha256']=cold_request_digest(task);addon._RENDERS[operation]=task;addon._persist_render_record(task)
        addon._NUKE_SCHEDULER.arm(owner,operation,permit['token'])
        journal.action('nuke_launch_intent',lambda:{'operation_id':operation,'record':file_record(root/'state/nuke_renders'/(operation+'.json')),'context':context})
        try:
            launched=addon._launch_owned_render_subprocess(operation,snapshot,'Write1',1,1,pattern=pattern,route=route,frame_set=[1],budget_seconds=120,**({'_cold_input_capability':_controller_cap} if _controller_cap is not None else {}))
            handle=launched.pop('handle');task['process']=launched
        except Exception as error:
            if getattr(error,'started',None) is False:unstarted=True;raise
            intent=task.get('supervisor_intent')
            if not intent:raise
            deadline=time.monotonic()+min(40,native.remaining_seconds())
            while time.monotonic()<deadline:
                try:handle=owned_process.OwnedProcessHandle(intent['directory'],intent['identity']);break
                except (ValueError,OSError):time.sleep(.05)
            if handle is None:raise ValueError('GEOMETRY_COLD_START_UNKNOWN')
            task['process']={'pid':handle.pid,'kind':'owned_render_subprocess','supervisor_directory':intent['directory'],
                'supervisor_identity':intent['identity'],**{k:intent[k] for k in ('argv','argv0','worker_result','worker_script')}}
        task.update(backend='owned_subprocess',dispatch_state='launched');addon._RENDER_HANDLES[operation]=handle
        addon._NUKE_SCHEDULER.bind_process(owner,operation,permit['token'],task['process']);addon._persist_render_record(task)
        while handle.poll() is None:journal.checkpoint();time.sleep(.1)
        stopped=handle.receipt()
        if stopped is None or owned_process.execution_returncode(stopped)!=0 or stopped.get('stop_reason') is not None:
            raise ValueError('GEOMETRY_COLD_NUKE_FAILED')
        worker=addon._verify_owned_worker_receipt(task);actual=worker['write_readback']['settings']
        if actual!={'file':pattern,'colorspace':artifact['colorspace'],'premultiplied':artifact['premultiplied'],'raw':False}:
            raise ValueError('GEOMETRY_NUKE_SETTINGS_MISMATCH')
        task['native_output_settings']={'origin':'nuke_write_readback','class':'Write','node':'Write1','pattern':pattern,
            'scene_fingerprint':scene,'colorspace':actual['colorspace'],'premultiplied':actual['premultiplied'],'raw':False,
            'operation_id':operation,'request_id':request};addon._persist_render_record(task)
        completed=journal.action('nuke_completed',lambda:addon.nuke_render_status(operation))
        if completed.get('state')!='COMPLETED' or completed.get('ledger_state')!='REGISTERED':raise ValueError('GEOMETRY_NUKE_TYPED_REGISTRATION_REQUIRED')
        assert_released_slot(root/'scheduler',operation);entry=registry.lookup('nuke-render-'+operation)
        if entry is None or registry.verify(entry['artifact_id']).get('usable') is not True:raise ValueError('GEOMETRY_NUKE_OUTPUT_UNUSABLE')
        return {'operation_id':operation,'artifact':entry,'formal_operation_receipt':addon._nuke_operation_fact(operation)['formal_receipt'],
            'files':{'nk':file_record(script),'exr':file_record(Path(pattern%1))}}
    finally:
        # 清理失败不得盖掉签名/准入首因；未知启动仍由原清理门阻止释放。
        primary=sys.exc_info()[1]
        if permit is not None:
            try:cleanup_cold_attempt(native,operation,task,handle,addon._NUKE_SCHEDULER,dict(permit,owner_root=owner),unstarted)
            except Exception as cleanup_error:
                if primary is None:raise
                note='GEOMETRY_CLEANUP_FAILED: '+type(cleanup_error).__name__+': '+str(cleanup_error)
                if callable(getattr(primary,'add_note',None)):primary.add_note(note)
                else:primary.__notes__=[*getattr(primary,'__notes__',[]),note]


def _finish_outputs(prep,job,jobprep,saved,warm,source_graph,journal,previous=None,render_source_details=None,checkpoint=None):
    """两轮共用的独立冷开、真实渲染、登记和Nuke消费直接下游。"""
    from .feedback_versions import FeedbackVersions
    from .official_graph_resume import inspect_resume_source
    from .geometry_evaluation import evaluate_initial,evaluate_feedback
    from .creative_preview import write_preview
    from houdini_bridge.official_karma import compare_files
    native=NativeScope(prep['scope']);project=Path(jobprep['project']);control=Path(jobprep['control']);prefix=job['operation_id']
    configuration=json.loads(checked_bytes(prep['configuration']))
    history=(checkpoint['history'] if checkpoint is not None else
             render_source_details['control'] if render_source_details is not None else jobprep['control'])
    with _resume(prep,jobprep,source_graph,saved,history) as f:
        if render_source_details is not None:
            # 这些是原作业已认证的观测，保留原operation身份，不重签为本轮warm/cold。
            reopened=copy.deepcopy(render_source_details['cold_reopen']);cold=copy.deepcopy(render_source_details['cold_geometry'])
            evaluation=copy.deepcopy(render_source_details['evaluate'])
        else:
            reopened=journal.action('cold_reopen',lambda:_cold_reopen(f,saved,configuration))
            cold=journal.action('cold_geometry',lambda:_geometry(f,saved,prep,job,'cold',transition=reopened))
            _verify_cold_geometry(cold,reopened)
            if cold['geometry_observation']!=warm['geometry_observation']:raise ValueError('GEOMETRY_COLD_WORLD_DATA_CHANGED')
            criteria=json.loads(checked_bytes(prep['criteria']))
            evaluation=journal.action('evaluate',lambda:evaluate_initial(cold['geometry_observation'],criteria) if previous is None
                else evaluate_feedback(previous['geometry']['geometry_observation'],cold['geometry_observation'],criteria))
        # 渲染目标只能从已保存的真实角色合同取出，调用方不能传新目标或配置。
        roles={n['role']:n['path'] for n in saved['scene_contract']['nodes']}
        rendered=journal.action('render',lambda:f.houdini_render_bounded(request_id=prefix+'_render',saved_scene_id=saved['saved_scene_id'],
            render_target=roles['render'],pattern=str(project/'saves/main.%04d.exr'),frames=[1],budget_seconds=120))
        operation=rendered.get('operation_id') or (rendered.get('operation') or {}).get('operation_id')
        if not operation:raise ValueError('GEOMETRY_RENDER_OPERATION_REQUIRED')
        journal.action('render_completed',lambda:_poll_render(f,operation,journal));journal.action('render_host_stop',lambda:_stop(prep,jobprep,'houdini'))
        verified=journal.action('verify',lambda:f.verify_render_output(prefix+'_verify',operation))
        image=verified['execution_fact']['metadata']['1']
        artifact=journal.action('register',lambda:f.register_render_artifact('geometry_main','preview_temp',str(project/'saves/main.%04d.exr'),[1],
            image['colorspace'],image['premultiplied'],prefix+'_verify'))
        expected_version=1 if 'feedback_authority' in job else job['revision']
        if artifact['version']!=expected_version:raise ValueError('GEOMETRY_ARTIFACT_VERSION_REQUIRED')
        source_record=journal.action('input_source',lambda:_input_source(prep,jobprep,artifact,verified))
    nk=journal.action('nuke_save',lambda:_save_nuke(prep,job,jobprep,source_record,journal))
    nuke=journal.action('nuke_cold',lambda:_cold_nuke(prep,job,jobprep,source_record,nk,journal))
    comparison=journal.action('compare',lambda:compare_files(str(project/'saves/main.0001.exr'),nuke['files']['exr']['path'],require_identical=True))
    if comparison.get('state')!='PASS':raise ValueError('GEOMETRY_NUKE_PIXEL_MISMATCH')
    preview=journal.action('preview',lambda:write_preview(file_record(project/'saves/main.0001.exr'),project/'saves/preview.png',prep['display']))
    # 局部是同一次实际渲染的无重采样裁剪，另开DCC不构成必要下游。
    local=journal.action('local_preview',lambda:_crop_preview(preview['preview'],project/'saves/local-preview.png'))
    source_graph=inspect_resume_source(source_graph['preparation']['path'],source_graph['operation_id'])
    usage=native.completed_snapshot()
    reused=({'render_source':job['render_source'],'parent_operation_id':render_source_details['operation_id']}
            if render_source_details is not None else {})
    if checkpoint is not None:
        reused={'checkpoint_operation_id':checkpoint['operation_id']}
    return {'schema':'bridge.geometry-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':prefix,**reused,
        'revision':job['revision'],'plan':job['plan'],'preparation':job['preparation'],'saved':saved,'geometry':cold,'warm_geometry':warm,
        'cold_reopen':reopened,'evaluation':evaluation,'artifact':artifact,'nuke':nuke,'comparison':comparison,'preview':preview,
        'source_record':source_record,'graph_source':source_graph,'control':str(control),'scope':usage,'model_route':prep['model_route'],
        'human_visual_acceptance':'PENDING','files':{'hip':file_record(Path(saved['path'])),'main':file_record(project/'saves/main.0001.exr'),
            'nk':nk['file'],'nuke':nuke['files']['exr'],'preview':preview['preview'],'local_preview':local}}


def _finish_nuke_resume(prep,job,jobprep,details,journal):
    """唯一消费者尾部：复用原EXR/登记/NK，只生成本次NR正式事实与观看预览。"""
    from .creative_preview import write_preview
    from houdini_bridge.official_karma import compare_files
    base=copy.deepcopy(details['base']);native=NativeScope(prep['scope']);directory=Path(job['directory'])
    previews=directory/'saves';ensure_private_directory(previews)
    nuke=journal.action('nuke_cold',lambda:_cold_nuke(prep,job,jobprep,details['source_record'],details['nuke_save'],journal))
    compared=journal.action('compare',lambda:compare_files(details['files']['main']['path'],nuke['files']['exr']['path'],require_identical=True))
    if compared.get('state')!='PASS':raise ValueError('GEOMETRY_NUKE_PIXEL_MISMATCH')
    preview=journal.action('preview',lambda:write_preview(details['files']['main'],previews/'preview.png',prep['display']))
    local=journal.action('local_preview',lambda:_crop_preview(preview['preview'],previews/'local-preview.png'))
    return {**base,'schema':'bridge.geometry-revision/1','state':'COMPLETE','task_id':prep['task_id'],
        'operation_id':job['operation_id'],'revision':1,'plan':job['plan'],'preparation':job['preparation'],
        'nuke_source':job['nuke_source'],'parent_operation_id':details['operation_id'],
        'parent_nuke_operation_id':details['failed_consumer'],'control':details['control'],
        'nuke':nuke,'comparison':compared,'preview':preview,'scope':native.completed_snapshot(),
        'model_route':prep['model_route'],'human_visual_acceptance':'PENDING',
        'files':{'hip':details['files']['hip'],'main':details['files']['main'],'nk':details['files']['nk'],
                 'nuke':nuke['files']['exr'],'preview':preview['preview'],'local_preview':local}}


def _finish_registration_resume(prep,job,jobprep,details,journal):
    """只登记原成功图并补两票Nuke；不打开、保存或重渲染Houdini。"""
    from .geometry_registration_resume import implementation,registration_registry_class,metadata_facade
    from .creative_preview import write_preview
    from houdini_bridge.official_karma import compare_files
    from nuke_bridge.task_host import input_artifact_registry
    native=NativeScope(prep['scope']);impl=implementation(job['preparation'],job['runtime_continuation'],native)
    registry=registration_registry_class(impl,native,prep['task_id'])(prep['ledger_root'])
    before=native.completed_snapshot();verified=details['verify'];image=verified['execution_fact']['metadata']['1'];project=Path(details['project'])
    with metadata_facade(prep,details,registry) as f:
        artifact=journal.action('register',lambda:f.register_render_artifact('geometry_main','preview_temp',str(project/'saves/main.%04d.exr'),[1],
            image['colorspace'],image['premultiplied'],details['operation_id']+'_verify'))
        if artifact['version']!=2:raise ValueError('GEOMETRY_ARTIFACT_VERSION_REQUIRED')
        source=journal.action('input_source',lambda:_input_source(prep,jobprep,artifact,verified,impl))
    if native.completed_snapshot()!=before:raise ValueError('GEOMETRY_REGISTRATION_NATIVE_DISPATCH_FORBIDDEN')
    # 真实输入登记兼容先验通过才准消耗最后两票。
    addon=_load_nuke(prep)
    def preflight():
        input_registry=input_artifact_registry(json.loads(checked_bytes(source)),scope=native,task_id=prep['task_id'],fallback=addon._nuke_operation_fact,observe_completed=True)
        receipt=input_registry.verify_operation_receipt(artifact['registry_operation_receipt'])
        if receipt!=artifact['registry_operation_receipt'] or not input_registry.verify('geometry_main').get('usable'):
            raise ValueError('GEOMETRY_REGISTRATION_NUKE_PREFLIGHT_REQUIRED')
        return {'state':'PASS','registry_operation_receipt':receipt}
    journal.action('input_preflight',preflight)
    nk=journal.action('nuke_save',lambda:_save_nuke(prep,job,jobprep,source,journal))
    nuke=journal.action('nuke_cold',lambda:_cold_nuke(prep,job,jobprep,source,nk,journal))
    comparison=journal.action('compare',lambda:compare_files(details['files']['main']['path'],nuke['files']['exr']['path'],require_identical=True))
    if comparison.get('state')!='PASS':raise ValueError('GEOMETRY_NUKE_PIXEL_MISMATCH')
    previews=Path(job['directory'])/'saves';ensure_private_directory(previews)
    preview=journal.action('preview',lambda:write_preview(details['files']['main'],previews/'preview.png',prep['display']))
    local=journal.action('local_preview',lambda:_crop_preview(preview['preview'],previews/'local-preview.png'))
    return {'schema':'bridge.geometry-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],
        'revision':2,'plan':job['plan'],'preparation':job['preparation'],'registration_source':job['registration_source'],
        'parent_operation_id':details['operation_id'],'control':details['control'],'saved':details['save'],'warm_geometry':details['warm_geometry'],
        'geometry':details['cold_geometry'],'cold_reopen':details['cold_reopen'],'evaluation':details['evaluate'],'graph_source':details['graph_source'],
        'artifact':artifact,'source_record':source,'nuke':nuke,'comparison':comparison,'preview':preview,'scope':native.completed_snapshot(),
        'model_route':prep['model_route'],'human_visual_acceptance':'PENDING','files':{'hip':details['files']['hip'],'main':details['files']['main'],
        'nk':nk['file'],'nuke':nuke['files']['exr'],'preview':preview['preview'],'local_preview':local}}



def _finish_nuke_save_resume(prep,job,jobprep,details,journal):
    """复用已登记artifact2/source2，只执行NH保存及NR冷渲染两票。"""
    from .creative_preview import write_preview
    from houdini_bridge.official_karma import compare_files
    native=NativeScope(prep['scope']);source=details['source_record'];artifact=details['artifact']
    nk=journal.action('nuke_save',lambda:_save_nuke(prep,job,jobprep,source,journal))
    nuke=journal.action('nuke_cold',lambda:_cold_nuke(prep,job,jobprep,source,nk,journal))
    comparison=journal.action('compare',lambda:compare_files(details['files']['main']['path'],nuke['files']['exr']['path'],require_identical=True))
    if comparison.get('state')!='PASS':raise ValueError('GEOMETRY_NUKE_PIXEL_MISMATCH')
    previews=Path(job['directory'])/'saves';ensure_private_directory(previews)
    preview=journal.action('preview',lambda:write_preview(details['files']['main'],previews/'preview.png',prep['display']))
    local=journal.action('local_preview',lambda:_crop_preview(preview['preview'],previews/'local-preview.png'))
    return {'schema':'bridge.geometry-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],
        'revision':2,'plan':job['plan'],'preparation':job['preparation'],'nuke_save_source':job['nuke_save_source'],
        'parent_operation_id':details['operation_id'],'parent_save_operation_id':details['failed_save_operation_id'],
        'control':details['control'],'saved':details['save'],'warm_geometry':details['warm_geometry'],
        'geometry':details['cold_geometry'],'cold_reopen':details['cold_reopen'],'evaluation':details['evaluate'],'graph_source':details['graph_source'],
        'artifact':artifact,'source_record':source,'nuke':nuke,'comparison':comparison,'preview':preview,'scope':native.completed_snapshot(),
        'model_route':prep['model_route'],'human_visual_acceptance':'PENDING','files':{'hip':details['files']['hip'],'main':details['files']['main'],
        'nk':nk['file'],'nuke':nuke['files']['exr'],'preview':preview['preview'],'local_preview':local}}


def _finish_seed_cold_resume(prep,job,jobprep,details,journal):
    """只定稿已存在seed并执行最后一票NR，保存宿主失败事实不改写。"""
    from .geometry_seed_cold_resume import finalize_nk
    from .creative_preview import write_preview
    from houdini_bridge.official_karma import compare_files
    native=NativeScope(prep['scope']);source=details['input_source']
    nk=journal.action('text_finalize',lambda:finalize_nk(details))
    nuke=journal.action('nuke_cold',lambda:_cold_nuke(prep,job,jobprep,source,nk,journal))
    comparison=journal.action('compare',lambda:compare_files(details['files']['main']['path'],nuke['files']['exr']['path'],require_identical=True))
    if comparison.get('state')!='PASS':raise ValueError('GEOMETRY_NUKE_PIXEL_MISMATCH')
    previews=Path(job['directory'])/'saves';ensure_private_directory(previews)
    preview=journal.action('preview',lambda:write_preview(details['files']['main'],previews/'preview.png',prep['display']))
    local=journal.action('local_preview',lambda:_crop_preview(preview['preview'],previews/'local-preview.png'))
    return {'schema':'bridge.geometry-revision/1','state':'COMPLETE','task_id':prep['task_id'],'operation_id':job['operation_id'],
        'revision':2,'plan':job['plan'],'preparation':job['preparation'],'seed_cold_source':job['seed_cold_source'],
        'parent_operation_id':details['operation_id'],'parent_failure_operation_id':details['failure_operation_id'],'control':details['control'],
        'saved':details['save'],'warm_geometry':details['warm_geometry'],'geometry':details['cold_geometry'],'cold_reopen':details['cold_reopen'],
        'evaluation':details['evaluate'],'graph_source':details['graph_source'],'artifact':details['artifact'],'source_record':source,
        'nk_finalization':nk,'nuke_save_status':'FAILED','delivery_method':'controller_text_finalization+native_cold_open_render',
        'nuke':nuke,'comparison':comparison,'preview':preview,'scope':native.completed_snapshot(),'model_route':prep['model_route'],
        'human_visual_acceptance':'PENDING','files':{'hip':details['files']['hip'],'main':details['files']['main'],'nk':nk['file'],
            'nuke':nuke['files']['exr'],'preview':preview['preview'],'local_preview':local}}

def _crop_preview(source,target):
    """只裁剪本控制器生成的RGBA PNG；不对比图做归一化或改色。"""
    import zlib,struct
    raw=checked_bytes(source)
    if raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('GEOMETRY_PREVIEW_PNG_REQUIRED')
    offset=8;data=b'';width=height=None
    while offset<len(raw):
        length=struct.unpack('>I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8];body=raw[offset+8:offset+8+length];offset+=length+12
        if kind==b'IHDR':
            width,height,depth,color,_,_,interlace=struct.unpack('>IIBBBBB',body)
            if depth!=8 or color!=6 or interlace!=0:raise ValueError('GEOMETRY_PREVIEW_LAYOUT_REQUIRED')
        elif kind==b'IDAT':data+=body
    unpacked=zlib.decompress(data);stride=width*4
    if len(unpacked)!=(stride+1)*height:raise ValueError('GEOMETRY_PREVIEW_ROWS_REQUIRED')
    rows=[]
    for y in range(height):
        row=unpacked[y*(stride+1):(y+1)*(stride+1)]
        if row[0]!=0:raise ValueError('GEOMETRY_PREVIEW_FILTER_REQUIRED')
        rows.append(row[1:])
    x0,x1=int(width*.2),int(width*.8);y0,y1=int(height*.12),int(height*.65)
    from houdini_bridge.official_karma_display import _png
    return _png(Path(target),x1-x0,y1-y0,[list(row[x0*4:x1*4]) for row in rows[y0:y1]])


def execute_job(job_path):
    """仅独立控制器调用；提案先验证，实际副作用在此受正式核心管理。"""
    from .workbuddy_assembly import prepared_graph_facade
    from .official_graph_resume import inspect_resume_source
    from .artifact_registry import ArtifactRegistry
    from .feedback_versions import FeedbackVersions
    job_path=Path(job_path);job=_object(job_path);prep=json.loads(checked_bytes(job['preparation']));native=NativeScope(prep['scope'])
    directory=Path(job['directory']);jobprep=_object(directory/'job-preparation.json');control=Path(jobprep['control'])
    nuke_details=None;registration_details=None;nuke_save_details=None;seed_cold_details=None
    if 'seed_cold_source' in job:
        from .geometry_seed_cold_resume import verify_job,validate as validate_seed_cold
        seed_cold_details=registration_details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        authority,_=validate_seed_cold(job['preparation'],job['runtime_continuation'],native)
        if (jobprep.get('seed_cold_source')!=job['seed_cold_source'] or str(control)!=seed_cold_details['control']
                or jobprep.get('project')!=seed_cold_details['project'] or jobprep.get('consumer_runtime')!=authority['consumer_runtime']):raise ValueError('GEOMETRY_SEED_COLD_SOURCE_BINDING_REQUIRED')
    elif 'nuke_save_source' in job:
        from .geometry_nuke_save_resume import verify_job,validate as validate_nuke_save
        nuke_save_details=registration_details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        authority,_=validate_nuke_save(job['preparation'],job['runtime_continuation'],native)
        if (jobprep.get('nuke_save_source')!=job['nuke_save_source'] or str(control)!=nuke_save_details['control']
                or jobprep.get('project')!=nuke_save_details['project']
                or jobprep.get('consumer_runtime')!=authority['consumer_runtime']):raise ValueError('GEOMETRY_NUKE_SAVE_SOURCE_BINDING_REQUIRED')
    elif 'registration_source' in job:
        from .geometry_registration_resume import verify_job,validate as validate_registration
        registration_details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        authority,_=validate_registration(job['preparation'],job['runtime_continuation'],native)
        if (jobprep.get('registration_source')!=job['registration_source'] or str(control)!=registration_details['control']
                or jobprep.get('project')!=registration_details['project']
                or jobprep.get('consumer_runtime')!=authority['registration_runtime']):raise ValueError('GEOMETRY_REGISTRATION_SOURCE_BINDING_REQUIRED')
    elif 'nuke_source' in job:
        from .geometry_nuke_resume import verify_job
        nuke_details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
        if (jobprep.get('nuke_source')!=job['nuke_source'] or str(control)!=nuke_details['control']
                or jobprep.get('project')!=nuke_details['project']):raise ValueError('GEOMETRY_NUKE_SOURCE_BINDING_REQUIRED')
    elif ROOT!=control/'snapshot':raise ValueError('GEOMETRY_CURRENT_JOB_SNAPSHOT_REQUIRED')
    feedback_details=None
    if 'feedback_authority' in job:
        from .geometry_feedback import verify_job
        feedback_details=verify_job(job,native,for_execution=True,runtime_root=ROOT)
    if (directory!=native.root/'jobs'/job['operation_id'] or job_path!=directory/'job.json'
            or job['task_id']!=native.scope['task_id'] or jobprep['job']!=file_record(job_path)):
        raise ValueError('GEOMETRY_JOB_BINDING_REQUIRED')
    os.environ.clear();os.environ.update(prep['environment']);journal=JobJournal(directory,file_record(job_path));project=Path(jobprep['project']);(project/'saves').mkdir(exist_ok=True)
    native.check();previous=None;source_graph=None;render_source_details=None
    checkpoint=feedback_details.get('checkpoint') if feedback_details is not None else None
    try:
        if job['revision']==2 and seed_cold_details is not None:
            journal.action('reuse_seed_cold_source',lambda:{'seed_cold_source':job['seed_cold_source'],'parent_operation_id':seed_cold_details['operation_id'],'parent_failure_operation_id':seed_cold_details['failure_operation_id']})
            result=_finish_seed_cold_resume(prep,job,jobprep,seed_cold_details,journal)
            validate_result(job['preparation'],job,result);_write(directory/'result.json',result,new=True);return
        elif job['revision']==2 and nuke_save_details is not None:
            journal.action('reuse_nuke_save_source',lambda:{'nuke_save_source':job['nuke_save_source'],'parent_operation_id':nuke_save_details['operation_id'],
                'parent_save_operation_id':nuke_save_details['failed_save_operation_id']})
            result=_finish_nuke_save_resume(prep,job,jobprep,nuke_save_details,journal)
            validate_result(job['preparation'],job,result);_write(directory/'result.json',result,new=True);return
        elif job['revision']==2 and registration_details is not None:
            journal.action('reuse_registration_source',lambda:{'registration_source':job['registration_source'],'parent_operation_id':registration_details['operation_id']})
            result=_finish_registration_resume(prep,job,jobprep,registration_details,journal)
            validate_result(job['preparation'],job,result);_write(directory/'result.json',result,new=True);return
        elif job['revision']==1 and nuke_details is not None:
            journal.action('reuse_nuke_source',lambda:{'nuke_source':job['nuke_source'],
                'parent_operation_id':nuke_details['operation_id'],'parent_nuke_operation_id':nuke_details['failed_consumer']})
            result=_finish_nuke_resume(prep,job,jobprep,nuke_details,journal)
            validate_result(job['preparation'],job,result);_write(directory/'result.json',result,new=True);return
        elif job['revision']==1 and 'render_source' in job:
            from .geometry_render_resume import verify_job
            if 'source_checkpoint' in job or jobprep.get('render_source')!=job['render_source']:
                raise ValueError('GEOMETRY_RENDER_SOURCE_BINDING_REQUIRED')
            render_source_details=verify_job(job,native)
            journal.action('reuse_source',lambda:{'render_source':job['render_source'],
                'parent_operation_id':render_source_details['operation_id']})
            saved=copy.deepcopy(render_source_details['save']);warm=copy.deepcopy(render_source_details['warm_geometry'])
            source_graph=copy.deepcopy(render_source_details['graph_source'])
        elif job['revision']==1 and 'source_checkpoint' in job:
            # 只承接认证的旧SUCCEEDED图；本分支不装配GraphJobService、不调用propose/trial。
            from dcc_task_runtime.geometry_recovery import verify_checkpoint_job
            from .official_graph_resume import resume_graph_facade
            if jobprep.get('source_checkpoint')!=job['source_checkpoint']:raise ValueError('GEOMETRY_CHECKPOINT_BINDING_REQUIRED')
            verified_source=verify_checkpoint_job(job,native)
            source_graph=journal.action('graph_source',lambda:inspect_resume_source(verified_source['preparation']['path'],verified_source['operation_id']))
            if source_graph!=verified_source:raise ValueError('GEOMETRY_CHECKPOINT_SOURCE_CHANGED')
            with resume_graph_facade(control/'run.json',source_graph,repo_root=ROOT,scheduler_root=native.root/'scheduler',checkpoint_task_copy=True) as f:
                if f.pipeline_task_id!=prep['task_id']:raise ValueError('GEOMETRY_PIPELINE_TASK_CHANGED')
                f.save_root=project/'saves';f.artifact_registry=ArtifactRegistry(prep['ledger_root'])
                f.host_client.bind_artifact_registry(f.artifact_registry)
                journal.action('host_bind',lambda:f._mark_graph_trial_complete(source_graph['receipt']))
                saved=journal.action('save',f.task_save);warm=journal.action('warm_geometry',lambda:_geometry(f,saved,prep,job,'warm'))
                journal.action('edit_host_stop',lambda:_stop(prep,jobprep,'houdini'))
        elif job['revision']==1:
            with prepared_graph_facade(control/'run.json',repo_root=ROOT,scheduler_root=native.root/'scheduler',backend='production') as f:
                if f.pipeline_task_id!=prep['task_id']:raise ValueError('GEOMETRY_PIPELINE_TASK_CHANGED')
                f.wait_for_formal_trial=False;f.save_root=project/'saves';f.artifact_registry=ArtifactRegistry(prep['ledger_root'])
                f.host_client.bind_artifact_registry(f.artifact_registry)
                state=_object(native.root/'geometry-state.json')
                for identifier in job['plan']['observation_ids']:
                    obs=state['observations'][identifier]
                    f.submit_observation(obs['asset_id'],{'description':obs['observation']},job['operation_id']+'_'+identifier)
                proposed=journal.action('graph_propose',lambda:f.graph_propose(job['plan']['selector'],job['operation_id']+'_plan'))
                graph_id=proposed['graph_id'];started=journal.action('graph_trial',lambda:f.graph_trial(graph_id,job['operation_id']+'_build'))
                operation=started['operation_id'];receipt=journal.action('build_completed',lambda:_poll_graph(f,operation,journal))
                source_ref=journal.action('graph_source_prepare',lambda:_source_receipt(directory,prep,jobprep,receipt,native))
                journal.action('host_bind',lambda:f._mark_graph_trial_complete(receipt))
                saved=journal.action('save',f.task_save);warm=journal.action('warm_geometry',lambda:_geometry(f,saved,prep,job,'warm'))
                journal.action('edit_host_stop',lambda:_stop(prep,jobprep,'houdini'))
            source_graph=journal.action('graph_source',lambda:inspect_resume_source(source_ref['preparation']['path'],source_ref['operation_id']))
        elif feedback_details is not None:
            parent=feedback_details['parent'];previous=feedback_details['baseline']
            source_graph=inspect_resume_source(parent['graph_source']['preparation']['path'],parent['graph_source']['operation_id'])
            journal.action('feedback_source',lambda:{'feedback_authority':job['feedback_authority'],'parent_operation_id':parent['operation_id'],
                'baseline_operation_id':previous['operation_id']})
            if checkpoint is not None:
                saved=journal.action('save',lambda:copy.deepcopy(checkpoint['saved']))
                warm=journal.action('warm_geometry',lambda:copy.deepcopy(checkpoint['warm']))
            else:
                with _resume(prep,jobprep,source_graph,parent['saved'],parent['control']) as f:
                    journal.action('baseline_reopen',lambda:f.task_reopen(parent['saved']['saved_scene_id']))
                    for i,edit in enumerate(job['plan']['edits']):
                        journal.action('feedback_'+str(i),lambda edit=edit:f.feedback_edit(source_graph['graph_id'],'m_'+edit['node_id'],edit['parms'],prep['task_id']))
                    saved=journal.action('save',f.task_save);warm=journal.action('warm_geometry',lambda:_geometry(f,saved,prep,job,'warm'))
                    journal.action('edit_host_stop',lambda:_stop(prep,jobprep,'houdini'))
        elif job['revision']==2:
            state=_object(native.root/'geometry-state.json')
            if len(state['completed'])!=1:raise ValueError('GEOMETRY_FEEDBACK_BASE_REQUIRED')
            previous=_accepted_result(job['preparation'],state['completed'][0])
            source_graph=inspect_resume_source(previous['graph_source']['preparation']['path'],previous['graph_source']['operation_id'])
            history=previous['control'];saved_before=previous['saved']
            with _resume(prep,jobprep,source_graph,saved_before,history) as f:
                journal.action('baseline_reopen',lambda:f.task_reopen(saved_before['saved_scene_id']))
                for i,edit in enumerate(job['plan']['edits']):
                    journal.action('feedback_'+str(i),lambda edit=edit:f.feedback_edit(source_graph['graph_id'],'m_'+edit['node_id'],edit['parms'],prep['task_id']))
                saved=journal.action('save',f.task_save);warm=journal.action('warm_geometry',lambda:_geometry(f,saved,prep,job,'warm'))
                journal.action('edit_host_stop',lambda:_stop(prep,jobprep,'houdini'))
        else:raise ValueError('GEOMETRY_REVISION_REQUIRED')
        result=_finish_outputs(prep,job,jobprep,saved,warm,source_graph,journal,previous,render_source_details,checkpoint)
        # 发布前采用与消费者相同的只读正式验证；不能仅靠控制端COMPLETE字样。
        validate_result(job['preparation'],job,result)
        _write(directory/'result.json',result,new=True)
    finally:
        _cleanup_job_hosts(prep,job)


def _cleanup_job_hosts(prep,job):
    """只处理此作业已登记的自有宿主；不创建宿主，不触碰桌面用户实例。"""
    for control in (Path(job['directory'])/'project/control',Path(job['directory'])/'nuke-save-control'):
        file=control/'production-hosts.json'
        if not file.exists():continue
        saved=_object(file)
        if saved.get('task_id')!=prep['task_id']:raise ValueError('GEOMETRY_CLEANUP_TASK_MISMATCH')
        for kind,config in saved.get('hosts',{}).items():
            if config.get('native_scope')!=prep['scope']:raise ValueError('GEOMETRY_CLEANUP_SCOPE_MISMATCH')
            _tools();from run_controlled_engineering import _stop_host
            _stop_host({'control':control,'scope_path':Path(prep['scope']['path']),'scope_sha256':prep['scope']['sha256']},kind)


def run_job(job_path,*,execute=False):
    """最终安装入口启动的独立控制器；客户端断开不拥有此进程。"""
    job_path=Path(job_path).resolve();job=_object(job_path);prep=json.loads(checked_bytes(job['preparation']));directory=Path(job['directory'])
    if job_path!=directory/'job.json' or directory!=Path(prep['scope']['path']).parent/'jobs'/job['operation_id']:
        raise ValueError('GEOMETRY_JOB_LAYOUT_REQUIRED')
    # 未取得所有权的重复进程不得写错误或清理正在运行的原作业。
    with execution_lock(directory,'geometry-job-owner' if execute else 'geometry-job-dispatcher'):
        if (directory/'result.json').exists() or (directory/'error.json').exists():raise ValueError('GEOMETRY_JOB_QUERY_ORIGINAL_REQUIRED')
        def deadline(_signum,_frame):raise TimeoutError('GEOMETRY_CONTROLLER_DEADLINE')
        if execute:signal.signal(signal.SIGALRM,deadline);signal.alarm(900)
        try:
            if not execute:
                from .geometry_session import validate_preparation
                if 'feedback_authority' in job:
                    from .geometry_feedback import verify_job
                    verify_job(job,NativeScope(prep['scope']),for_execution=True,runtime_root=ROOT)
                else:
                    validate_preparation(job['preparation'])
                jobprep=prepare_execution(prep,job)
                # 独立执行器从本轮正式控制快照启动；与安装runtime的来源身份可逐字核对。
                import subprocess
                worker=(job['execution_worker']['path'] if 'nuke_source' in job or 'registration_source' in job or 'nuke_save_source' in job or 'seed_cold_source' in job
                        else str(Path(jobprep['control'])/'snapshot/tools/run_geometry_creative.py'))
                if ('nuke_source' in job or 'registration_source' in job or 'nuke_save_source' in job or 'seed_cold_source' in job) and file_record(Path(worker))!=job['execution_worker']:
                    raise ValueError('GEOMETRY_EXECUTION_WORKER_CHANGED')
                command=[prep['supervisor_python'],'-I','-B',worker,'execute-job','--job',str(job_path)]
                child=subprocess.run(command,cwd=directory,env=dict(prep['environment']),timeout=930)
                if child.returncode!=0:raise RuntimeError('GEOMETRY_JOB_CHILD_FAILED')
            else:
                from dcc_task_runtime.platform_support import process_identity
                _write(directory/'execute-owner.json',{'schema':'bridge.geometry-execute-owner/1','task_id':prep['task_id'],
                    'operation_id':job['operation_id'],'job':file_record(job_path),'process_identity':process_identity(os.getpid()),
                    'observed_at':time.time()},new=True)
                execute_job(job_path)
        except BaseException as error:
            import traceback
            (directory/'controller-error.log').write_text(traceback.format_exc(),encoding='utf-8')
            if not (directory/'error.json').exists() and not (directory/'result.json').exists():
                stopped=False
                try:
                    _cleanup_job_hosts(prep,job);usage=NativeScope(prep['scope']).completed_snapshot();stopped=all(t['stopped_at'] is not None for t in usage['tickets'])
                except Exception:usage=None
                code=str(error).split(':',1)[0]
                if not re.fullmatch('[A-Z][A-Z0-9_]{0,99}',code):code=type(error).__name__.upper()
                _write(directory/'error.json',{'schema':'bridge.geometry-job-error/1','task_id':prep['task_id'],'operation_id':job['operation_id'],
                    'revision':job['revision'],'preparation_record':job['preparation'],'state':'CANCELLED' if isinstance(error,_Cancelled) else 'FAILED',
                    'stop_confirmed':stopped,'code':code,'message':str(error)[:2000],'native_snapshot':usage},new=True)
            raise
        finally:
            if execute:signal.alarm(0)


def validate_result(preparation_record,job,result,*,_metadata_context=None):
    """消费者只读复验原正式生产/登记/冷消费及文件；不启动或重新准入。"""
    from .official_graph_resume import inspect_resume_source
    from .geometry_evaluation import evaluate_initial,evaluate_feedback
    from nuke_bridge.task_host import _input_artifact_registry
    from houdini_bridge.official_karma import compare_files
    prep=json.loads(checked_bytes(preparation_record))
    if _metadata_context is None:native=NativeScope(prep['scope'])
    else:
        from .geometry_metadata_completion import checked_context
        native=checked_context(_metadata_context,preparation=preparation_record,job=job,result=result).native
    feedback_details=None
    if 'feedback_authority' in job:
        from .geometry_feedback import verify_job
        feedback_details=verify_job(job,native)
    directory=native.root/'jobs'/job['operation_id']
    phase=lambda name:nullcontext() if _metadata_context is None else _metadata_context.phase(name)
    nuke_details=None;registration_details=None;nuke_save_details=None;seed_cold_details=None
    if 'seed_cold_source' in job:
        if (result.get('prelaunch_continuation') or {}).get('schema') in ('bridge.geometry-prelaunch-metadata-result/1','bridge.geometry-prelaunch-metadata-result/2'):
            from .geometry_metadata_completion import verify_job_details
            seed_cold_details=registration_details=verify_job_details(native,job,result,_metadata_context=_metadata_context)
        else:
            from .geometry_seed_cold_resume import verify_job
            seed_cold_details=registration_details=verify_job(job,native)
    elif 'nuke_save_source' in job:
        from .geometry_nuke_save_resume import verify_job
        nuke_save_details=registration_details=verify_job(job,native)
    elif 'registration_source' in job:
        from .geometry_registration_resume import verify_job
        registration_details=verify_job(job,native)
    if 'nuke_source' in job:
        from .geometry_nuke_resume import verify_job
        nuke_details=verify_job(job,native)
    expected_control=(registration_details['control'] if registration_details is not None else nuke_details['control'] if nuke_details is not None else str(directory/'project/control'))
    if (job.get('schema')!='bridge.geometry-job/1' or job.get('preparation')!=preparation_record
            or job.get('task_id')!=native.scope['task_id'] or job.get('directory')!=str(directory)
            or result.get('schema')!='bridge.geometry-revision/1' or result.get('state')!='COMPLETE'
            or any(result.get(k)!=job[k] for k in ('task_id','operation_id','revision','plan'))
            or result.get('preparation')!=preparation_record or result.get('control')!=expected_control
            or result.get('model_route')!=prep['model_route']):
        raise ValueError('GEOMETRY_RESULT_BINDING_REQUIRED')
    if _object(directory/'job.json')!=job:raise ValueError('GEOMETRY_JOB_CHANGED')
    plan=copy.deepcopy(job['plan']);claimed=plan.pop('plan_sha256',None)
    if canonical_sha256(plan)!=claimed:raise ValueError('GEOMETRY_MODEL_PLAN_CHANGED')
    render_source_details=None
    if seed_cold_details is not None:
        if (result.get('seed_cold_source')!=job['seed_cold_source'] or result.get('parent_operation_id')!=seed_cold_details['operation_id']
                or result.get('parent_failure_operation_id')!=seed_cold_details['failure_operation_id']
                or result.get('artifact')!=seed_cold_details['artifact'] or result.get('source_record')!=seed_cold_details['input_source']
                or result.get('delivery_method')!='controller_text_finalization+native_cold_open_render' or result.get('nuke_save_status')!='FAILED'
                or result.get('nk_finalization',{}).get('method')!='controller_text_finalization' or result['nk_finalization'].get('native_save_performed') is not False
                or result['files']['nk']!=seed_cold_details['nk_binding']['final_nk']
                or any(result.get(key)!=seed_cold_details[original] for key,original in (('saved','save'),('warm_geometry','warm_geometry'),('geometry','cold_geometry'),('cold_reopen','cold_reopen'),('evaluation','evaluate'),('graph_source','graph_source')))):
            raise ValueError('GEOMETRY_SEED_COLD_SOURCE_RESULT_CHANGED')
    elif nuke_save_details is not None:
        if (result.get('nuke_save_source')!=job['nuke_save_source'] or result.get('parent_operation_id')!=nuke_save_details['operation_id']
                or result.get('parent_save_operation_id')!=nuke_save_details['failed_save_operation_id']
                or result.get('artifact')!=nuke_save_details['artifact'] or result.get('source_record')!=nuke_save_details['source_record']
                or any(result.get(key)!=nuke_save_details[original] for key,original in (('saved','save'),('warm_geometry','warm_geometry'),('geometry','cold_geometry'),('cold_reopen','cold_reopen'),('evaluation','evaluate'),('graph_source','graph_source')))):
            raise ValueError('GEOMETRY_NUKE_SAVE_SOURCE_RESULT_CHANGED')
    elif registration_details is not None:
        if (result.get('registration_source')!=job['registration_source'] or result.get('parent_operation_id')!=registration_details['operation_id']
                or any(result.get(key)!=registration_details[original] for key,original in (('saved','save'),('warm_geometry','warm_geometry'),('geometry','cold_geometry'),('cold_reopen','cold_reopen'),('evaluation','evaluate'),('graph_source','graph_source')))):
            raise ValueError('GEOMETRY_REGISTRATION_SOURCE_RESULT_CHANGED')
    elif 'render_source' in job:
        from .geometry_render_resume import verify_job
        render_source_details=verify_job(job,native)
        if (result.get('render_source')!=job['render_source'] or result.get('parent_operation_id')!=render_source_details['operation_id']
                or any(result.get(key)!=render_source_details[original] for key,original in
                       (('saved','save'),('warm_geometry','warm_geometry'),('geometry','cold_geometry'),
                        ('cold_reopen','cold_reopen'),('evaluation','evaluate'),('graph_source','graph_source')))):
            raise ValueError('GEOMETRY_RENDER_SOURCE_RESULT_CHANGED')
    elif nuke_details is not None:
        if (result.get('nuke_source')!=job['nuke_source'] or result.get('parent_operation_id')!=nuke_details['operation_id']
                or result.get('parent_nuke_operation_id')!=nuke_details['failed_consumer']
                or any(result.get(key)!=value for key,value in nuke_details['base'].items())):
            raise ValueError('GEOMETRY_NUKE_SOURCE_RESULT_CHANGED')
    elif 'render_source' in result or 'parent_operation_id' in result or 'nuke_source' in result or 'registration_source' in result or 'nuke_save_source' in result or 'seed_cold_source' in result:raise ValueError('GEOMETRY_RENDER_SOURCE_UNAUTHORIZED')
    checkpoint=feedback_details.get('checkpoint') if feedback_details is not None else None
    if checkpoint is not None:
        if (result.get('checkpoint_operation_id')!=checkpoint['operation_id']
                or result['saved']!=checkpoint['saved'] or result['warm_geometry']!=checkpoint['warm']
                or result['files']['hip']!=checkpoint['hip']):
            raise ValueError('GEOMETRY_COLD_CHECKPOINT_RESULT_CHANGED')
    elif 'checkpoint_operation_id' in result:
        raise ValueError('GEOMETRY_COLD_CHECKPOINT_UNAUTHORIZED')
    for name,record in result['files'].items():
        checked_bytes(record)
        source_hip=(render_source_details is not None and name=='hip'
                    and record==file_record(Path(render_source_details['save']['path']))) or (checkpoint is not None and name=='hip' and record==checkpoint['hip'])
        nuke_source_file=(nuke_details is not None and ((name in ('hip','main','nk') and record==nuke_details['files'][name])
                          or (name=='nuke' and record['path']==nuke_details['output_pattern']%1)))
        registration_file=(registration_details is not None and ((name in ('hip','main') and record==registration_details['files'][name])
                           or (name=='nk' and record['path']==str(Path(registration_details['project'])/'saves/composite.nk'))
                           or (name=='nuke' and record['path']==str(Path(registration_details['project'])/'saves/nuke.0001.exr'))))
        if not source_hip and not nuke_source_file and not registration_file and not Path(record['path']).is_relative_to(directory):raise ValueError('GEOMETRY_RESULT_OUTSIDE_JOB')
    source_graph=result['graph_source']
    if inspect_resume_source(source_graph['preparation']['path'],source_graph['operation_id'])!=source_graph:
        raise ValueError('GEOMETRY_SOURCE_GRAPH_CHANGED')
    saved=result['saved'];configuration=json.loads(checked_bytes(prep['configuration']))
    if (file_record(Path(saved['path']))!=result['files']['hip']
            or saved['sha256']!=result['files']['hip']['sha256']
            or canonical_sha256(saved['scene_contract'])!=saved['scene_contract_sha256']
            or saved['scene_contract']['task_id']!=prep['task_id']):raise ValueError('GEOMETRY_SAVED_CONTRACT_REQUIRED')
    reopened=result['cold_reopen'];transition=reopened.get('scene_transition') or {}
    from houdini_bridge.operation_receipts import operation_receipt_sha256
    if (reopened.get('sha256')!=saved['sha256'] or reopened.get('load_warnings')!=[]
            or reopened.get('scene_contract_sha256')!=saved['scene_contract_sha256']
            or any(reopened.get(k) is not True for k in ('nodes_verified','parameters_verified','connections_verified'))
            or reopened.get('frozen_scene_parameters')!=saved['scene_contract'].get('frozen_scene_parameters')
            or (reopened.get('frozen_scene_parameters') or {}).get('configuration_sha256')!=canonical_sha256(configuration)
            or transition.get('state')!='COMPLETED' or transition.get('load_count')!=1
            or transition.get('operation_receipt_sha256')!=operation_receipt_sha256(transition)
            or transition.get('after_identity',{}).get('launch_nonce')==saved.get('operation_receipt',{}).get('host_identity',{}).get('launch_nonce')):
        raise ValueError('GEOMETRY_RESULT_COLD_REOPEN_REQUIRED')
    with phase('geometry_hom'):
        from .geometry_native_evidence import verify as verify_native_geometry
        observation_operation=(registration_details['operation_id'] if registration_details is not None else nuke_details['observation_operation_id'] if nuke_details is not None else
                               render_source_details['operation_id'] if render_source_details is not None else job['operation_id'])
        if nuke_save_details is not None or seed_cold_details is not None:
            from .geometry_native_evidence import verify_historical
            inherited=nuke_save_details if nuke_save_details is not None else seed_cold_details
            history={'accounting_prefix':inherited['accounting_prefix'],'accounting_envelope':inherited['accounting_envelope']}
            verify_historical(result['warm_geometry'],saved,prep['scope'],observation_operation+'_warm','warm',**history)
            verify_historical(result['geometry'],saved,prep['scope'],observation_operation+'_cold','cold',transition=reopened,**history)
        else:
            verify_native_geometry(result['warm_geometry'],saved,
                checkpoint['scope'] if checkpoint is not None else prep['scope'],
                (checkpoint['operation_id'] if checkpoint is not None else observation_operation)+'_warm','warm')
            verify_native_geometry(result['geometry'],saved,prep['scope'],observation_operation+'_cold','cold',transition=reopened)
        _verify_cold_geometry(result['geometry'],reopened)
        if result['geometry']['geometry_observation']!=result['warm_geometry']['geometry_observation']:
            raise ValueError('GEOMETRY_RESULT_COLD_DATA_CHANGED')
    criteria=json.loads(checked_bytes(prep['criteria']))
    if feedback_details is not None:
        evaluation=evaluate_feedback(feedback_details['baseline']['geometry']['geometry_observation'],result['geometry']['geometry_observation'],criteria)
    elif job['revision']==1:evaluation=evaluate_initial(result['geometry']['geometry_observation'],criteria)
    else:
        session=_object(native.root/'geometry-state.json')
        # 与反馈执行入口一致，只取唯一已接纳的首版；早期失败的同revision尝试不能充当基线。
        if (len(session['completed']) not in (1,2) or len(session['completed'])==2 and session['completed'][1]!=job['operation_id']):raise ValueError('GEOMETRY_FEEDBACK_BASE_REQUIRED')
        with phase('accepted_base'):
            previous=_accepted_result(preparation_record,session['completed'][0]);evaluation=evaluate_feedback(previous['geometry']['geometry_observation'],result['geometry']['geometry_observation'],criteria)
    if evaluation!=result['evaluation']:raise ValueError('GEOMETRY_CASE_EVALUATION_CHANGED')
    addon=_load_nuke(prep);source=json.loads(checked_bytes(result['source_record']))
    with phase('registry_source'):
        registry=_input_artifact_registry(source,scope=native,task_id=prep['task_id'],fallback=addon._nuke_operation_fact,observe_completed=True,_read_only_binding=True)
    addon._NUKE_ARTIFACT_REGISTRY=registry
    with phase('typed_main'):
        checked=registry.verify_operation_receipt(result['artifact']['registry_operation_receipt'])
    expected_version=1 if feedback_details is not None else job['revision']
    if checked['artifact_id']!='geometry_main' or checked['version']!=expected_version or checked['task_id']!=prep['task_id']:
        raise ValueError('GEOMETRY_RESULT_ARTIFACT_VERSION_REQUIRED')
    nuke=result['nuke']
    with phase('typed_nuke'):
        entry=registry.lookup(nuke['artifact']['artifact_id'])
        if entry!=nuke['artifact'] or not registry.verify(entry['artifact_id']).get('usable'):
            raise ValueError('GEOMETRY_RESULT_NUKE_RECEIPT_REQUIRED')
    if (entry['frame_set']!=[1] or entry['colorspace']!='ACEScg' or result['files']['nk']!=nuke['files']['nk']
            or result['files']['nuke']!=nuke['files']['exr']):raise ValueError('GEOMETRY_RESULT_NUKE_BINDING_REQUIRED')
    with phase('pixels'):
        compared=compare_files(result['files']['main']['path'],result['files']['nuke']['path'],require_identical=True)
    if compared.get('state')!='PASS' or compared!=result['comparison']:raise ValueError('GEOMETRY_RESULT_PIXELS_CHANGED')
    usage=native.completed_snapshot() if _metadata_context is None else copy.deepcopy(_metadata_context.usage)
    if any(t['stopped_at'] is None for t in usage['tickets']):raise ValueError('GEOMETRY_RESULT_ALL_STOPS_REQUIRED')
    if checkpoint is not None:
        roles=sorted(t['role'] for t in usage['tickets'])
        if usage['closed_reason'] is not None or roles!=['houdini-host','main-husk','nuke-host','nuke-render']:
            raise ValueError('GEOMETRY_COLD_CHECKPOINT_NATIVE_ROLES_REQUIRED')
    journal_path=directory/'incremental-state.json'
    if 'prelaunch_continuation' in result:
        from .geometry_prelaunch_tail import verify_result_extension
        journal_path=verify_result_extension(native,job,result,_metadata_context=_metadata_context)
    journal=_object(journal_path)
    required={'render','render_completed','render_host_stop','verify','register','input_source',
              'nuke_save','nuke_launch_intent','nuke_completed','nuke_cold','compare','preview','local_preview'}
    if seed_cold_details is not None:
        required={'reuse_seed_cold_source','text_finalize','nuke_cold','nuke_launch_intent','nuke_completed','compare','preview','local_preview'}
        if set(journal.get('stages',{}))!=required or journal['stages']['reuse_seed_cold_source'].get('result')!={'seed_cold_source':job['seed_cold_source'],'parent_operation_id':seed_cold_details['operation_id'],'parent_failure_operation_id':seed_cold_details['failure_operation_id']}:raise ValueError('GEOMETRY_SEED_COLD_SOURCE_JOURNAL_REQUIRED')
    elif nuke_save_details is not None:
        required={'reuse_nuke_save_source','nuke_save','nuke_cold','nuke_launch_intent','nuke_completed','compare','preview','local_preview'}
        if (set(journal.get('stages',{}))!=required or journal['stages']['reuse_nuke_save_source'].get('result')!=
                {'nuke_save_source':job['nuke_save_source'],'parent_operation_id':nuke_save_details['operation_id'],'parent_save_operation_id':nuke_save_details['failed_save_operation_id']}):
            raise ValueError('GEOMETRY_NUKE_SAVE_SOURCE_JOURNAL_REQUIRED')
    elif registration_details is not None:
        required={'reuse_registration_source','register','input_source','input_preflight','nuke_save','nuke_cold','nuke_launch_intent','nuke_completed','compare','preview','local_preview'}
        if journal.get('stages',{}).get('reuse_registration_source',{}).get('result')!={'registration_source':job['registration_source'],'parent_operation_id':registration_details['operation_id']}:
            raise ValueError('GEOMETRY_REGISTRATION_SOURCE_JOURNAL_REQUIRED')
    elif nuke_details is not None:
        required={'reuse_nuke_source','nuke_cold','nuke_launch_intent','nuke_completed','compare','preview','local_preview'}
        if journal.get('stages',{}).get('reuse_nuke_source',{}).get('result')!={'nuke_source':job['nuke_source'],
                'parent_operation_id':nuke_details['operation_id'],'parent_nuke_operation_id':nuke_details['failed_consumer']}:
            raise ValueError('GEOMETRY_NUKE_SOURCE_JOURNAL_REQUIRED')
    elif render_source_details is None:required|={'save','warm_geometry','cold_reopen','cold_geometry'}
    else:
        required.add('reuse_source')
        if journal.get('stages',{}).get('reuse_source',{}).get('result')!={'render_source':job['render_source'],
                'parent_operation_id':render_source_details['operation_id']}:raise ValueError('GEOMETRY_RENDER_SOURCE_JOURNAL_REQUIRED')
    if (journal.get('job')!=file_record(directory/'job.json') or any(v.get('state')!='DONE' for v in journal.get('stages',{}).values())
            or not required<=set(journal.get('stages',{}))):
        raise ValueError('GEOMETRY_RESULT_PHASE_JOURNAL_REQUIRED')
    return {'state':'VERIFIED','case_geometry':evaluation['state'],'native_starts':usage['dcc_starts']}
