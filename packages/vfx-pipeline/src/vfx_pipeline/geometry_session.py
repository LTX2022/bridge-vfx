"""有限几何创作前端：纯提案与独立作业提交，MCP断线不拥有或取消执行器。"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory, process_identity, process_status
from houdini_bridge.official_karma_observation import checked_bytes, file_record
from .workbuddy_mcp import _text_content
from . import geometry_graph

PREPARATION = 'bridge.geometry-creative-preparation/1'
STATE = 'bridge.geometry-session-state/1'
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
_REQUIRED = {'schema','task_id','scope','configuration','source_reuse','worker','supervisor_python',
             'environment','media','public_brief','feedback','ledger_root'}


def _fail(code):
    raise ValueError('GEOMETRY_' + code)


def _plain(raw):
    path = Path(raw)
    if not path.is_absolute() or path != path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        _fail('PATH_INVALID')
    return path


def _id(value):
    if not isinstance(value,str) or not IDENTIFIER.fullmatch(value):
        _fail('IDENTIFIER_REQUIRED')
    return value


def _text(value, minimum, maximum):
    if not isinstance(value,str) or not minimum <= len(value) <= maximum:
        _fail('BOUNDED_TEXT_REQUIRED')
    return value


def _record(value, *, root=None):
    if (not isinstance(value,dict) or set(value) != {'path','bytes','sha256'}
            or type(value['bytes']) is not int or value['bytes'] < 0):
        _fail('FILE_RECORD_REQUIRED')
    path = _plain(value['path'])
    if root is not None and not path.is_relative_to(root):
        _fail('FILE_OUTSIDE_ROOT')
    return checked_bytes(value)


def _object(path):
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                _fail('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    value = json.loads(_plain(path).read_text(encoding='utf-8'), object_pairs_hook=unique)
    if not isinstance(value,dict):
        _fail('OBJECT_REQUIRED')
    return value


def _runtime_root():
    return Path(__file__).resolve().parents[4]


def _goal_view(result,validation):
    """只投影已验证的目标评估；技术完成不能代替几何或人工视觉接收。"""
    status=validation.get('case_geometry') if isinstance(validation,dict) and validation.get('state')=='VERIFIED' else None
    if status not in ('PASS','FAIL'):
        return {'goal_status':'UNKNOWN','goal_evaluation':None}
    evaluation=result.get('evaluation')
    if not isinstance(evaluation,dict) or evaluation.get('state')!=status:_fail('GOAL_EVALUATION_CHANGED')
    return {'goal_status':status,'goal_evaluation':copy.deepcopy(evaluation)}


def _validate_preparation(record, *, for_execution=True, resolved_worker=None):
    """观察保留原准备身份；只有新派发才要求当前安装的原执行文件仍可使用。"""
    _record(record)
    path = _plain(record['path'])
    if path.name != 'geometry-preparation.json':
        _fail('PREPARATION_PATH_REQUIRED')
    prep = _object(path)
    root = path.parent
    if not _REQUIRED <= set(prep) or prep.get('schema') != PREPARATION:
        _fail('PREPARATION_REQUIRED')
    _id(prep['task_id'])
    binding = prep['scope']
    if not isinstance(binding,dict) or set(binding) != {'path','sha256'} or _plain(binding['path']) != root/'scope.json':
        _fail('SCOPE_BINDING_REQUIRED')
    if hashlib.sha256((root/'scope.json').read_bytes()).hexdigest() != binding['sha256']:
        _fail('SCOPE_CHANGED')
    scope = _object(root/'scope.json')
    if (scope.get('schema') != 'bridge.geometry-creative-scope/1'
            or scope.get('task_id') != prep['task_id'] or scope.get('output_root') != str(root)
            or scope.get('source_reuse') != prep['source_reuse']):
        _fail('SCOPE_TASK_MISMATCH')
    if (scope.get('execution_authorized') is not True or scope.get('status')!='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'
            or (scope.get('authorization') or {}).get('authority')!='current_user_instruction'
            or not isinstance((scope.get('authorization') or {}).get('instruction'),str)
            or not scope['authorization']['instruction'].strip()):_fail('EXECUTION_AUTHORIZATION_REQUIRED')
    worker = _plain(prep['worker'])
    if for_execution:
        if worker==_runtime_root()/'tools/run_geometry_creative.py':
            if not worker.is_file():_fail('INSTALLED_WORKER_REQUIRED')
        else:
            # 跨runtime只有操作者已认证的有限续接可准入，原准备身份仍不可改写。
            if resolved_worker is None:
                from .geometry_runtime_binding import resolve_worker
                resolve_worker(record,_runtime_root())
            else:_record(resolved_worker)
    supervisor = _plain(prep['supervisor_python'])
    supervisor_record=scope.get('hosts',{}).get('supervisor_python') or {}
    if (set(supervisor_record)!={'path','bytes','sha256'} or supervisor_record.get('path')!=str(supervisor)
            or type(supervisor_record.get('bytes')) is not int or supervisor_record['bytes']<0
            or not isinstance(supervisor_record.get('sha256'),str)
            or not re.fullmatch('[0-9a-f]{64}',supervisor_record['sha256'])):
        _fail('SUPERVISOR_BINDING_REQUIRED')
    if for_execution:
        if not supervisor.is_file() or not os.access(supervisor,os.X_OK):_fail('SUPERVISOR_BINDING_REQUIRED')
        _record(supervisor_record)
    if _plain(prep['ledger_root']) != root/'artifact_ledger':
        _fail('LEDGER_ROOT_REQUIRED')
    env = prep['environment']
    if (not isinstance(env,dict) or len(env)>128 or any(not isinstance(k,str) or not k or '=' in k or '\0' in k
            or not isinstance(v,str) or '\0' in v or len(v)>8192 for k,v in env.items())
            or sum(len(k)+len(v) for k,v in env.items()) > 65536):
        _fail('ENVIRONMENT_REQUIRED')
    _text(prep['public_brief'],10,16000);_text(prep['feedback'],10,8000)
    _record(prep['configuration'],root=root);_record(prep['source_reuse'],root=root)
    if (not isinstance(prep['media'],dict) or not {'reference_front','reference_perspective'} <= set(prep['media'])
            or len(prep['media'])>8):
        _fail('REFERENCE_MEDIA_REQUIRED')
    for asset,source in prep['media'].items():
        _id(asset);_record(source,root=root)
    # 历史观察仍验签原范围记账身份；不检查可执行文件存活、不准入或刷新预算。
    from dcc_task_runtime.native_scope import NativeScope
    NativeScope(binding)
    return prep


def validate_preparation(record, *, for_execution=True):
    """公开准备验证不接收已验证对象；所有旧调用沿原解析合同。"""
    return _validate_preparation(record,for_execution=for_execution)


def _validate_preparation_dispatch(record,dispatch):
    """042执行调用栈私有上下文只替代worker重复解析，其余准入逐项保留。"""
    from .geometry_seed_cold_resume import _Dispatch as ColdDispatch,dispatch_worker as cold_worker
    if type(dispatch) is ColdDispatch:worker=cold_worker(record,dispatch)
    else:
        from .geometry_nuke_save_runtime_successor import dispatch_worker
        worker=dispatch_worker(record,dispatch)
    return _validate_preparation(record,for_execution=True,resolved_worker=worker)


class GeometrySession:
    """持久前端状态属于新工程；后台控制进程与连接生命周期完全分开。"""
    def __init__(self, preparation, *, connection_id=None):
        self.preparation = copy.deepcopy(preparation) if isinstance(preparation,dict) else file_record(_plain(preparation))
        self.prep = validate_preparation(self.preparation,for_execution=False)
        self.root = Path(self.preparation['path']).parent
        worker=Path(self.prep['worker'])
        self.worker_record = (file_record(worker) if worker==_runtime_root()/'tools/run_geometry_creative.py'
                              and worker.is_file() else None)
        self.state_path = self.root/'geometry-state.json'
        self.log = self.root/'geometry-events.jsonl'
        self.connection_id = connection_id or uuid.uuid4().hex

    def close(self):
        """MCP退出不持有后台进程句柄，不能取消原任务。"""
        return None

    def _initial(self):
        return {'schema':STATE,'preparation':self.preparation,'task_id':self.prep['task_id'],'revision':0,
                'assets':{key:{'asset_id':key,'file':copy.deepcopy(record),'kind':'image','role':'reference','revision':0}
                          for key,record in self.prep['media'].items()},
                'served':{},'observations':{},'plans':{},'plan_operations':{},'execution_requests':{},
                'jobs':{},'completed':[],'current_model_graph':None}

    def _read(self):
        _record(self.preparation)
        if not self.state_path.exists():
            return self._initial()
        state = _object(self.state_path)
        if (state.get('schema') != STATE or state.get('preparation') != self.preparation
                or state.get('task_id') != self.prep['task_id'] or type(state.get('revision')) is not int
                or not 0 <= state['revision'] <= 2
                or any(not isinstance(state.get(k),dict) for k in ('assets','served','observations','plans','plan_operations','execution_requests','jobs'))
                or not isinstance(state.get('completed'),list) or len(state['completed']) != state['revision']):
            _fail('SESSION_STATE_INVALID')
        return state

    def _write(self,state):
        atomic_write(self.state_path,(json.dumps(state,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode(),owned_root=self.root)

    def _event(self,kind,payload):
        """前端操作审计与原生生产回执分开；不记录图片base64或环境内容。"""
        _plain(self.log)
        previous=None;seq=0
        if self.log.exists():
            old=json.loads(self.log.read_text().splitlines()[-1]);previous=old['sha256'];seq=old['seq']+1
        value={'schema':'bridge.geometry-frontend-event/1','seq':seq,'previous':previous,'kind':kind,'payload':payload,'time':time.time()}
        value['sha256']=canonical_sha256(value)
        with self.log.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())

    def _authenticated_current_model(self,state):
        if not state['revision']:return None
        entry=state['jobs'].get(state['completed'][-1])
        if not isinstance(entry,dict):_fail('ACCEPTANCE_RECEIPT_REQUIRED')
        job=json.loads(_record(entry['job_file'],root=self.root))
        self._observe_accepted(state,entry,job)
        current_model=job['plan']['model_graph']
        if current_model!=state['current_model_graph']:_fail('ACCEPTED_MODEL_CHANGED')
        return current_model

    def catalog(self):
        state=self._read();current_model=self._authenticated_current_model(state)
        return {'task_id':self.prep['task_id'],'revision':state['revision'],'public_brief':self.prep['public_brief'],
                'feedback':self.prep['feedback'] if state['revision'] else None,'model_catalog':geometry_graph.model_catalog(),
                'current_model_graph':copy.deepcopy(current_model),
                'execution_requires_current_runtime_validation':True,'current_runtime_worker_bound':self.worker_record is not None,
                'assets':[{k:v for k,v in asset.items() if k!='file'} for asset in state['assets'].values()],
                'native_dispatch_attempted':False}

    def media(self,asset_id):
        """返回真正登记的PNG图像块；同连接实际送达摘要才可用于观察提交。"""
        _id(asset_id)
        with execution_lock(self.root,'geometry-session'):
            state=self._read();asset=state['assets'].get(asset_id)
            if not isinstance(asset,dict):_fail('REGISTERED_MEDIA_REQUIRED')
            raw=_record(asset['file'],root=self.root)
            if len(raw)>4*1024*1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):_fail('PNG_MEDIA_REQUIRED')
            from .controller_media import FixedPngDecoder
            image=FixedPngDecoder(max_dimension=2048).decode(Path(asset['file']['path']))
            if image['sha256'] != asset['file']['sha256']:_fail('MEDIA_CHANGED')
            state['served'].setdefault(self.connection_id,{})[asset_id]=copy.deepcopy(asset['file'])
            self._write(state);self._event('media_served',{'connection_id':self.connection_id,'asset_id':asset_id,'file':asset['file']})
            return [{'type':'image','mimeType':'image/png','data':base64.b64encode(raw).decode()},
                    _text_content({'asset_id':asset_id,'revision':asset['revision'],'sha256':asset['file']['sha256'],
                                   'width':image['width'],'height':image['height']})]

    def observe(self,asset_id,request_id,observation):
        _id(asset_id);_id(request_id);_text(observation,10,4000)
        with execution_lock(self.root,'geometry-session'):
            state=self._read();asset=state['assets'].get(asset_id)
            if (not isinstance(asset,dict) or state['served'].get(self.connection_id,{}).get(asset_id) != asset['file']):
                _fail('VIEW_ACTUAL_MEDIA_FIRST')
            _record(asset['file'],root=self.root)
            body={'asset_id':asset_id,'file':asset['file'],'observation':observation}
            digest=canonical_sha256(body);old=state['observations'].get(request_id)
            if old is not None:
                if old['request_sha256']!=digest:_fail('REQUEST_CONFLICT')
                return {'observation_id':request_id,'idempotent':True}
            state['observations'][request_id]={'observation_id':request_id,**copy.deepcopy(body),
                                             'connection_id':self.connection_id,'request_sha256':digest}
            self._write(state);self._event('observation_submitted',{'observation_id':request_id,'asset_id':asset_id,'image_sha256':asset['file']['sha256']})
            return {'observation_id':request_id,'accepted':True}

    def propose(self,request_id,base_revision,goal,rationale,observation_ids,model_graph=None,edits=None):
        """纯数据补丁和编译不进入feedback_edit，更不装配真实执行器。"""
        _id(request_id);_text(goal,10,2000);_text(rationale,20,4000)
        if type(base_revision) is not int or base_revision not in (0,1):_fail('BASE_REVISION_REQUIRED')
        if (not isinstance(observation_ids,list) or not 2<=len(observation_ids)<=8
                or len(set(observation_ids))!=len(observation_ids)):_fail('OBSERVATIONS_REQUIRED')
        for oid in observation_ids:_id(oid)
        body={'base_revision':base_revision,'goal':goal,'rationale':rationale,'observation_ids':observation_ids,'model_graph':model_graph,'edits':edits}
        request_sha=canonical_sha256(body)
        with execution_lock(self.root,'geometry-session'):
            state=self._read();old=state['plans'].get(request_id)
            if old is not None:
                if old['request_sha256']!=request_sha:_fail('REQUEST_CONFLICT')
                return {'plan_id':request_id,'revision':old['revision'],'plan_sha256':old['plan_sha256'],'idempotent':True}
            if state['revision']!=base_revision:_fail('PLAN_BASE_STALE')
            if any(job['state'] not in ('COMPLETE','FAILED','CANCELLED') for job in state['jobs'].values()):_fail('JOB_STILL_ACTIVE')
            observed=[]
            for oid in observation_ids:
                item=state['observations'].get(oid)
                if not item:_fail('OBSERVATION_NOT_FOUND')
                asset=state['assets'].get(item['asset_id'])
                if not asset or item['file']!=asset['file']:_fail('OBSERVATION_STALE')
                _record(item['file'],root=self.root);observed.append(item['asset_id'])
            required={'reference_front','reference_perspective'} if base_revision==0 else {'preview_1','local_1'}
            if not required <= set(observed):_fail('REQUIRED_VIEWS_MISSING')
            if base_revision==0:
                if edits is not None or model_graph is None:_fail('BUILD_MODEL_REQUIRED')
                model=geometry_graph.model_proposal(model_graph).to_dict();patch=[]
            else:
                if model_graph is not None or not isinstance(edits,list) or not 1<=len(edits)<=8:_fail('FEEDBACK_EDITS_REQUIRED')
                model=copy.deepcopy(self._authenticated_current_model(state));by_id={n['node_id']:n for n in model['nodes']};touched=set()
                for edit in edits:
                    if (not isinstance(edit,dict) or set(edit)!={'node_id','parms'} or edit['node_id'] not in by_id
                            or edit['node_id'] in touched or not isinstance(edit['parms'],dict) or not 1<=len(edit['parms'])<=6):_fail('EDIT_NODE_REQUIRED')
                    touched.add(edit['node_id'])
                    if any(type(v) not in (int,float) or not math.isfinite(v) for v in edit['parms'].values()):_fail('FINITE_EDIT_REQUIRED')
                    by_id[edit['node_id']]['parameters'].update(edit['parms'])
                model=geometry_graph.model_proposal(model).to_dict();patch=copy.deepcopy(edits)
                if model==state['current_model_graph']:_fail('DISTINCT_GEOMETRY_CHANGE_REQUIRED')
            selection=geometry_graph.selector(model)
            plan={'schema':'bridge.geometry-plan/1','task_id':self.prep['task_id'],'plan_id':request_id,'base_revision':base_revision,
                  'revision':base_revision+1,'goal':goal,'rationale':rationale,'observation_ids':list(observation_ids),
                  'model_graph':model,'edits':patch,'selector':selection,'request_sha256':request_sha}
            plan['plan_sha256']=canonical_sha256(plan)
            state['plans'][request_id]=plan;self._write(state);self._event('plan_accepted',{'plan_id':request_id,'revision':plan['revision'],'plan_sha256':plan['plan_sha256']})
            return {'plan_id':request_id,'revision':plan['revision'],'plan_sha256':plan['plan_sha256'],'ready':True}

    def _scope_check(self):
        from dcc_task_runtime.native_scope import NativeScope
        return NativeScope(self.prep['scope']).check()

    def execute(self,plan_id,request_id,*,_repair_authority=None):
        """接受一次后台作业；连接不持有子进程句柄，未知派发不自动重做。"""
        _id(plan_id);_id(request_id)
        body={'plan_id':plan_id};digest=canonical_sha256(body)
        with execution_lock(self.root,'geometry-session'):
            state=self._read();old=state['execution_requests'].get(request_id)
            if old is not None:
                if old['request_sha256']!=digest:_fail('REQUEST_CONFLICT')
                job=state['jobs'][old['operation_id']]
                return {'operation_id':job['operation_id'],'state':job['state'],'idempotent':True}
            plan=state['plans'].get(plan_id)
            if not plan:_fail('ACCEPTED_PLAN_REQUIRED')
            if plan_id in state['plan_operations']:
                job=state['jobs'][state['plan_operations'][plan_id]]
                return {'operation_id':job['operation_id'],'state':job['state'],'idempotent':True}
            source_checkpoint=None;render_source=None;nuke_source=None;registration_source=None;nuke_save_source=None;seed_cold_source=None;resolved_dispatch=None
            if 'operator_repair' in plan or plan_id.endswith(('_float_repair01','_host_resume01','_host_resume02','_render_resume01','_nuke_resume01','_registration_resume01','_nuke_save_resume01','_seed_cold_resume01')):
                # 操作者签名INTENT与计划已落盘时，公开MCP不能抢先派发修复专用作业。
                marker=plan.get('operator_repair')
                if (isinstance(marker,dict) and marker.get('schema')=='bridge.geometry-seed-cold-resume/1'
                        and _runtime_root()==Path(self.prep['worker']).parents[2].with_name('0.4.6')/'runtime'):
                    from .geometry_seed_cold_resume import resolve_dispatch
                    resolved_dispatch=resolve_dispatch(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    seed_cold_source=resolved_dispatch.source;_record(seed_cold_source,root=self.root)
                elif (isinstance(marker,dict) and marker.get('schema')=='bridge.geometry-nuke-save-resume/1'
                        and _runtime_root()==Path(self.prep['worker']).parents[2].with_name('0.4.2')/'runtime'):
                    from .geometry_nuke_save_runtime_successor import resolve_dispatch
                    resolved_dispatch=resolve_dispatch(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    nuke_save_source=resolved_dispatch.source;_record(nuke_save_source,root=self.root)
                else:
                    from .geometry_runtime_binding import verify_operator_dispatch
                    verify_operator_dispatch(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                if isinstance(marker,dict) and marker.get('schema') in ('bridge.geometry-operator-checkpoint-recovery/1',
                                                                               'bridge.geometry-operator-checkpoint-recovery/2'):
                    from dcc_task_runtime.geometry_recovery import checkpoint_record
                    source_checkpoint=checkpoint_record(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    _record(source_checkpoint,root=self.root)
                elif isinstance(marker,dict) and marker.get('schema')=='bridge.geometry-render-resume/1':
                    from .geometry_render_resume import source_record_for_job
                    render_source=source_record_for_job(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    _record(render_source,root=self.root)
                elif isinstance(marker,dict) and marker.get('schema')=='bridge.geometry-nuke-resume/1':
                    from .geometry_nuke_resume import source_record_for_job
                    nuke_source=source_record_for_job(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    _record(nuke_source,root=self.root)
                elif resolved_dispatch is None and isinstance(marker,dict) and marker.get('schema')=='bridge.geometry-nuke-save-resume/1':
                    from .geometry_nuke_save_resume import source_record_for_job
                    nuke_save_source=source_record_for_job(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    _record(nuke_save_source,root=self.root)
                elif isinstance(marker,dict) and marker.get('schema')=='bridge.geometry-registration-resume/1':
                    from .geometry_registration_resume import source_record_for_job
                    registration_source=source_record_for_job(self.preparation,plan,request_id,_repair_authority,_runtime_root())
                    _record(registration_source,root=self.root)
            if plan['base_revision']!=state['revision'] or state['revision']>=2:_fail('PLAN_BASE_STALE')
            signed_plan={k:v for k,v in plan.items() if k!='plan_sha256'}
            if (canonical_sha256(signed_plan)!=plan.get('plan_sha256') or plan.get('task_id')!=self.prep['task_id']
                    or geometry_graph.selector(plan['model_graph'])!=plan.get('selector')):_fail('PLAN_CHANGED')
            if any(job['state'] not in ('COMPLETE','FAILED','CANCELLED') for job in state['jobs'].values()):_fail('JOB_STILL_ACTIVE')
            if plan['base_revision']:self._authenticated_current_model(state)
            if resolved_dispatch is not None:
                _validate_preparation_dispatch(self.preparation,resolved_dispatch)
                active_worker=resolved_dispatch.worker;runtime_continuation=resolved_dispatch.authority
            else:
                validate_preparation(self.preparation)
                from .geometry_runtime_binding import resolve_worker, continuation_record
                active_worker=resolve_worker(self.preparation,_runtime_root())
                runtime_continuation=continuation_record(self.preparation,_runtime_root())
            if self.worker_record is not None:
                _record(self.worker_record)
                if active_worker!=self.worker_record:_fail('EXECUTION_WORKER_CHANGED')
            elif Path(self.prep['worker'])==_runtime_root()/'tools/run_geometry_creative.py':
                _fail('EXECUTION_RUNTIME_REBIND_REQUIRED')
            _record(active_worker)
            if runtime_continuation is not None:_record(runtime_continuation,root=self.root)
            self._scope_check()
            operation='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
            directory=self.root/'jobs'/operation;_plain(directory);ensure_private_directory(directory)
            jobfile=directory/'job.json'
            if jobfile.exists():_fail('EXISTING_JOB_REQUIRES_QUERY')
            job={'schema':'bridge.geometry-job/1','preparation':self.preparation,'operation_id':operation,'task_id':self.prep['task_id'],
                 'revision':plan['revision'],'directory':str(directory),'plan':copy.deepcopy(plan),'execution_worker':active_worker}
            if runtime_continuation is not None:job['runtime_continuation']=runtime_continuation
            if source_checkpoint is not None:job['source_checkpoint']=source_checkpoint
            if render_source is not None:job['render_source']=render_source
            if nuke_source is not None:job['nuke_source']=nuke_source
            if registration_source is not None:job['registration_source']=registration_source
            if nuke_save_source is not None:job['nuke_save_source']=nuke_save_source
            if seed_cold_source is not None:job['seed_cold_source']=seed_cold_source
            atomic_write(jobfile,json.dumps(job,ensure_ascii=False,indent=2,allow_nan=False).encode(),owned_root=directory)
            entry={'operation_id':operation,'revision':plan['revision'],'plan_id':plan_id,'directory':str(directory),
                   'job_file':file_record(jobfile),'state':'QUEUED','accepted_at':time.time()}
            state['jobs'][operation]=entry;state['plan_operations'][plan_id]=operation
            state['execution_requests'][request_id]={'request_sha256':digest,'operation_id':operation};self._write(state)
            command=[self.prep['supervisor_python'],'-I','-B',active_worker['path'],'run-job','--job',str(jobfile)]
            intent={'schema':'bridge.geometry-controller-launch/1','operation_id':operation,'job':entry['job_file'],
                    'argv':command,'accepted_at':entry['accepted_at'],'launch_intent_at':time.time()}
            atomic_write(directory/'controller-launch-intent.json',json.dumps(intent,ensure_ascii=False,indent=2).encode(),owned_root=directory)
            self._event('job_accepted',{'operation_id':operation,'job':entry['job_file'],'plan_sha256':plan['plan_sha256']})
            process=None
            try:
                with (directory/'controller.stdout.log').open('xb') as stdout,(directory/'controller.stderr.log').open('xb') as stderr:
                    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                                             cwd=str(directory),env=dict(self.prep['environment']),start_new_session=True)
            except OSError as error:
                if process is not None:
                    return {'operation_id':operation,'state':'UNKNOWN','error_code':'CONTROLLER_LAUNCH_RECORD_PENDING','controller_dispatch_attempted':True}
                failed={'schema':'bridge.geometry-controller-start-failure/1','code':'CONTROLLER_START_FAILED',
                        'error_type':type(error).__name__,'state':'FAILED','native_started':False,'stop_confirmed':True}
                atomic_write(directory/'error.json',json.dumps(failed).encode(),owned_root=directory)
                entry['state']='FAILED';self._write(state)
                return {'operation_id':operation,'state':'FAILED','error_code':'CONTROLLER_START_FAILED'}
            # 只读取实际OS出生身份；观察失败保留unknown，不把已启动进程误报为未派发。
            try:
                identity=process_identity(process.pid)
            except (OSError,ValueError,RuntimeError):
                identity={'pid':process.pid,'birth':None,'state':'unknown'}
            launched={**intent,'pid':process.pid,'process_identity':identity,'observed_at':time.time(),'state':'STARTED'}
            try:
                atomic_write(directory/'controller-started.json',json.dumps(launched,ensure_ascii=False,indent=2).encode(),owned_root=directory)
                entry['controller']=file_record(directory/'controller-started.json');self._write(state)
            except (OSError,ValueError):
                return {'operation_id':operation,'state':'UNKNOWN','error_code':'CONTROLLER_LAUNCH_RECORD_PENDING','controller_dispatch_attempted':True}
            return {'operation_id':operation,'state':'QUEUED','controller_dispatch_attempted':True,'next_poll_seconds':10}

    def tasks(self):
        state=self._read()
        return [{'operation_id':key,'state':job['state'],'revision':job['revision'],'task_id':self.prep['task_id']}
                for key,job in state['jobs'].items()]

    def _acceptance_native(self,*,_metadata_context=None):
        if _metadata_context is not None:
            from .geometry_metadata_completion import checked_context
            return checked_context(_metadata_context,preparation=self.preparation).native
        from dcc_task_runtime.native_scope import NativeScope
        return NativeScope(self.prep['scope'])

    @staticmethod
    def _acceptance_signature(native,payload):
        """与原生记账域分离派生认证密钥；模型接口不能提交或重签接收回执。"""
        key=hmac.new(native._key(),b'bridge.geometry-accepted-result.key/1',hashlib.sha256).digest()
        return hmac.new(key,json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),hashlib.sha256).hexdigest()

    def _result_binding(self,entry,job,result,record,*,_metadata_context=None):
        """历史观察保留原文件与原计划身份，不用当前登记头代替历史产物。"""
        operation=entry['operation_id'];directory=self.root/'jobs'/operation
        if (entry['directory']!=str(directory) or job.get('schema')!='bridge.geometry-job/1'
                or job.get('preparation')!=self.preparation or job.get('task_id')!=self.prep['task_id']
                or job.get('operation_id')!=operation or job.get('directory')!=str(directory)
                or type(job.get('revision')) is not int or job['revision'] not in (1,2)
                or entry.get('revision')!=job['revision'] or record.get('path')!=str(directory/'result.json')
                or result.get('schema')!='bridge.geometry-revision/1' or result.get('state')!='COMPLETE'
                or result.get('preparation')!=self.preparation
                or any(result.get(k)!=job[k] for k in ('task_id','operation_id','revision','plan'))):
            _fail('ACCEPTED_RESULT_BINDING_REQUIRED')
        plan=copy.deepcopy(job['plan']);claimed=plan.pop('plan_sha256',None)
        if (canonical_sha256(plan)!=claimed or plan.get('task_id')!=self.prep['task_id']
                or plan.get('revision')!=job['revision'] or plan.get('plan_id')!=entry['plan_id']
                or geometry_graph.selector(plan['model_graph'])!=plan.get('selector')):_fail('ACCEPTED_PLAN_CHANGED')
        files=result.get('files')
        if not isinstance(files,dict) or not {'hip','main','nk','nuke','preview','local_preview'}<=set(files):
            _fail('ACCEPTED_FILES_REQUIRED')
        source_hip=None
        if 'render_source' in job:
            from .geometry_render_resume import verify_job
            details=verify_job(job,self._acceptance_native(_metadata_context=_metadata_context))
            source_hip=file_record(Path(details['save']['path']))
            if result.get('render_source')!=job['render_source'] or result.get('parent_operation_id')!=details['operation_id']:
                _fail('ACCEPTED_RENDER_SOURCE_CHANGED')
        nuke_details=None
        if 'nuke_source' in job:
            from .geometry_nuke_resume import verify_job
            nuke_details=verify_job(job,self._acceptance_native(_metadata_context=_metadata_context))
            if (result.get('nuke_source')!=job['nuke_source'] or result.get('parent_operation_id')!=nuke_details['operation_id']
                    or result.get('parent_nuke_operation_id')!=nuke_details['failed_consumer']):_fail('ACCEPTED_NUKE_SOURCE_CHANGED')
        registration_details=None
        if 'seed_cold_source' in job:
            if (result.get('prelaunch_continuation') or {}).get('schema') in ('bridge.geometry-prelaunch-metadata-result/1','bridge.geometry-prelaunch-metadata-result/2'):
                from .geometry_metadata_completion import verify_job_details
                registration_details=verify_job_details(self._acceptance_native(_metadata_context=_metadata_context),job,result,_metadata_context=_metadata_context)
            else:
                from .geometry_seed_cold_resume import verify_job
                registration_details=verify_job(job,self._acceptance_native(_metadata_context=_metadata_context))
            if (result.get('seed_cold_source')!=job['seed_cold_source'] or result.get('parent_operation_id')!=registration_details['operation_id']
                    or result.get('parent_failure_operation_id')!=registration_details['failure_operation_id']):_fail('ACCEPTED_SEED_COLD_SOURCE_CHANGED')
        elif 'nuke_save_source' in job:
            from .geometry_nuke_save_resume import verify_job
            registration_details=verify_job(job,self._acceptance_native(_metadata_context=_metadata_context))
            if (result.get('nuke_save_source')!=job['nuke_save_source'] or result.get('parent_operation_id')!=registration_details['operation_id']
                    or result.get('parent_save_operation_id')!=registration_details['failed_save_operation_id']):
                _fail('ACCEPTED_NUKE_SAVE_SOURCE_CHANGED')
        elif 'registration_source' in job:
            from .geometry_registration_resume import verify_job
            registration_details=verify_job(job,self._acceptance_native(_metadata_context=_metadata_context))
            if (result.get('registration_source')!=job['registration_source'] or result.get('parent_operation_id')!=registration_details['operation_id']):
                _fail('ACCEPTED_REGISTRATION_SOURCE_CHANGED')
        for name,source in files.items():
            registration_file=(registration_details is not None and ((name in ('hip','main') and source==registration_details['files'][name])
                or name=='nk' and source['path']==str(Path(registration_details['project'])/'saves/composite.nk')
                or name=='nuke' and source['path']==str(Path(registration_details['project'])/'saves/nuke.0001.exr')))
            inherited=(nuke_details is not None and ((name in ('hip','main','nk') and source==nuke_details['files'][name])
                       or (name=='nuke' and source['path']==nuke_details['output_pattern']%1)))
            if registration_file or inherited or (name=='hip' and source_hip is not None and source==source_hip):_record(source,root=self.root)
            else:_record(source,root=directory)
        binding={'schema':'bridge.geometry-accepted-result/1','preparation':self.preparation,'scope':self.prep['scope'],
                'task_id':self.prep['task_id'],'operation_id':operation,'revision':job['revision'],
                'job':entry['job_file'],'result':record,'files':files}
        if 'prelaunch_continuation' in result:
            from .geometry_prelaunch_tail import verify_result_extension
            verify_result_extension(self._acceptance_native(_metadata_context=_metadata_context),job,result,_metadata_context=_metadata_context);binding['prelaunch_continuation']=result['prelaunch_continuation']
        return binding

    def _verify_acceptance(self,entry,job,result,record,acceptance_record,*,_metadata_context=None):
        expected=self._result_binding(entry,job,result,record,_metadata_context=_metadata_context)
        directory=Path(entry['directory'])
        if acceptance_record.get('path')!=str(directory/'accepted-result.json'):_fail('ACCEPTANCE_RECEIPT_REQUIRED')
        receipt=json.loads(_record(acceptance_record,root=directory));native=self._acceptance_native(_metadata_context=_metadata_context)
        if (not isinstance(receipt,dict) or set(receipt)!={'payload','signature'}
                or not isinstance(receipt.get('payload'),dict) or not isinstance(receipt.get('signature'),str)
                or not hmac.compare_digest(receipt['signature'],self._acceptance_signature(native,receipt['payload']))):
            _fail('ACCEPTANCE_SIGNATURE_INVALID')
        payload=receipt['payload'];snapshot=payload.get('native_snapshot')
        if (set(payload)!=set(expected)|{'native_snapshot','validation'}
                or any(payload.get(key)!=value for key,value in expected.items())
                or not isinstance(snapshot,dict) or snapshot.get('scope_sha256')!=self.prep['scope']['sha256']
                or not isinstance(snapshot.get('tickets'),list) or snapshot.get('dcc_starts')!=len(snapshot['tickets'])
                or any(not isinstance(ticket,dict) or ticket.get('stopped_at') is None for ticket in snapshot['tickets'])):
            _fail('ACCEPTANCE_BINDING_CHANGED')
        return payload

    def _seal_acceptance(self,entry,job,result,record,validation,*,_metadata_context=None):
        path=Path(entry['directory'])/'accepted-result.json'
        if path.exists():
            existing=file_record(_plain(path));self._verify_acceptance(entry,job,result,record,existing,_metadata_context=_metadata_context)
            return existing
        payload=self._result_binding(entry,job,result,record,_metadata_context=_metadata_context);native=self._acceptance_native(_metadata_context=_metadata_context)
        payload.update(native_snapshot=(native.completed_snapshot() if _metadata_context is None else copy.deepcopy(_metadata_context.usage)),validation=validation)
        receipt={'payload':payload,'signature':self._acceptance_signature(native,payload)}
        if _metadata_context is not None:_metadata_context.finish()
        atomic_write(path,(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode(),owned_root=Path(entry['directory']))
        return file_record(path)

    def _observe_accepted(self,state,entry,job,*,_metadata_context=None):
        if (entry.get('state')!='COMPLETE' or not isinstance(entry.get('result'),dict)
                or not isinstance(entry.get('acceptance'),dict)
                or state['completed'].index(entry['operation_id'])+1!=job['revision']):
            _fail('ACCEPTANCE_RECEIPT_REQUIRED')
        record=entry['result'];result=json.loads(_record(record,root=Path(entry['directory'])))
        accepted=self._verify_acceptance(entry,job,result,record,entry['acceptance'],_metadata_context=_metadata_context)
        return {'operation_id':entry['operation_id'],'task_id':self.prep['task_id'],'state':'COMPLETE','revision':job['revision'],
                **_goal_view(result,accepted['validation']),
                'action':'ACCEPTED_RESULT_OBSERVED','result_view':'accepted_immutable','historical':job['revision']<state['revision'],
                'observation_only':True,'consumable_for_new_execution':False,'fresh_consumption_verified':False,
                'acceptance_receipt':entry['acceptance'],'original_result':record,'files':result['files'],'native_dispatch_attempted':False}

    @staticmethod
    def _late_stop_signature(native,payload):
        """延迟停止观察与产物接收、原生账本使用不同认证域。"""
        key=hmac.new(native._key(),b'bridge.geometry-late-stop.key/1',hashlib.sha256).digest()
        return hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()

    def _late_stop_binding(self,entry,job,error_record):
        return {'schema':'bridge.geometry-late-stop-observation/1','preparation':self.preparation,
                'scope':self.prep['scope'],'task_id':self.prep['task_id'],'operation_id':entry['operation_id'],
                'revision':job['revision'],'job':entry['job_file'],'error':error_record}

    def _late_stop_snapshot(self,native,snapshot,accounting,current,prefix):
        """历史证据必须是完整签名链的原停止前缀，不能借用恢复后的活动票据。"""
        value=native._verify_envelope(accounting);closed=value.get('state');lines=prefix.splitlines()
        if (set(value)!={'seq','previous','state'} or type(value.get('seq')) is not int
                or not prefix.endswith(b'\n') or len(lines)!=value['seq']+1
                or not lines or lines[-1]!=native._canonical(accounting)
                or not isinstance(closed,dict) or closed.get('schema')!='bridge.native-scope-state/1'
                or closed.get('scope_sha256')!=self.prep['scope']['sha256']
                or closed.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'):
            _fail('LATE_STOP_ACCOUNTING_INVALID')
        tickets=closed.get('tickets')
        if (not isinstance(tickets,list) or not tickets or tickets!=current['tickets'][:len(tickets)]
                or any(not isinstance(ticket,dict) or ticket.get('stopped_at') is None for ticket in tickets)):
            _fail('LATE_STOP_ACCOUNTING_PREFIX_INVALID')
        charges=[max(ticket['charged_seconds'],ticket['stopped_at']-ticket['admitted_at']) for ticket in tickets]
        expected={'dcc_starts':len(tickets),'total_seconds':sum(charges),'closed_reason':closed['closed_reason'],
                  'scope_sha256':self.prep['scope']['sha256'],'tickets':tickets}
        if (not isinstance(snapshot,dict) or type(snapshot.get('dcc_starts')) is not int
                or snapshot!=expected or sum(charges)>native.scope['budget']['total_seconds']
                or any(charge>native.role_seconds(ticket['role']) for ticket,charge in zip(tickets,charges))):
            _fail('LATE_STOP_SNAPSHOT_INVALID')

    def _verify_late_stop(self,entry,job,error_record,record):
        """纯历史核验不要求当前宿主停止；仍认证当前账本和原错误、原票据前缀。"""
        from dcc_task_runtime.native_scope import _accounting_lock
        directory=Path(entry['directory'])
        if not isinstance(record,dict) or record.get('path')!=str(directory/'late-stop-observation.json'):_fail('LATE_STOP_RECEIPT_REQUIRED')
        receipt=json.loads(_record(record,root=directory));native=self._acceptance_native()
        if (not isinstance(receipt,dict) or set(receipt)!={'payload','signature'}
                or not isinstance(receipt.get('payload'),dict) or not isinstance(receipt.get('signature'),str)
                or not hmac.compare_digest(receipt['signature'],self._late_stop_signature(native,receipt['payload']))):
            _fail('LATE_STOP_SIGNATURE_INVALID')
        payload=receipt['payload'];expected=self._late_stop_binding(entry,job,error_record)
        if (set(payload)!=set(expected)|{'native_accounting','native_snapshot','journal_prefix'}
                or any(payload.get(key)!=value for key,value in expected.items())):_fail('LATE_STOP_BINDING_CHANGED')
        prefix_record=payload['journal_prefix']
        if (not isinstance(prefix_record,dict) or set(prefix_record)!={'path','bytes','sha256'}
                or prefix_record.get('path')!=str(native.journal_path)
                or type(prefix_record.get('bytes')) is not int or not 0<prefix_record['bytes']<=8*1024*1024
                or not isinstance(prefix_record.get('sha256'),str)
                or not re.fullmatch('[0-9a-f]{64}',prefix_record['sha256'])):_fail('LATE_STOP_PREFIX_REQUIRED')
        with _accounting_lock(native.state_path):
            current=native._read()
            with native.journal_path.open('rb') as stream:prefix=stream.read(prefix_record['bytes'])
            if len(prefix)!=prefix_record['bytes'] or hashlib.sha256(prefix).hexdigest()!=prefix_record['sha256']:
                _fail('LATE_STOP_PREFIX_CHANGED')
            self._late_stop_snapshot(native,payload['native_snapshot'],payload['native_accounting'],current,prefix)
        return payload

    def _seal_late_stop(self,entry,job,error_record):
        """会话锁与会计锁内一致封存原失败停止事实；后续恢复不覆盖此观察。"""
        from dcc_task_runtime.native_scope import _accounting_lock
        directory=Path(entry['directory']);path=directory/'late-stop-observation.json'
        if path.exists():
            record=file_record(_plain(path));self._verify_late_stop(entry,job,error_record,record);return record
        native=self._acceptance_native()
        with _accounting_lock(native.state_path):
            try:usage=native.completed_snapshot()
            except ValueError as failure:
                if str(failure)!='NATIVE_SCOPE_COMPLETED_STOP_REQUIRED':raise
                return None
            tickets=usage.get('tickets')
            if (usage.get('scope_sha256')!=self.prep['scope']['sha256']
                    or usage.get('closed_reason')!='NATIVE_SCOPE_EXECUTION_FAILED'
                    or not isinstance(tickets,list) or not tickets
                    or type(usage.get('dcc_starts')) is not int or usage['dcc_starts']!=len(tickets)
                    or any(not isinstance(ticket,dict) or ticket.get('stopped_at') is None for ticket in tickets)):
                return None
            accounting=json.loads(native.state_path.read_bytes());prefix=native.journal_path.read_bytes();current=native._read()
            self._late_stop_snapshot(native,usage,accounting,current,prefix)
            payload={**self._late_stop_binding(entry,job,error_record),'native_accounting':accounting,
                     'native_snapshot':usage,'journal_prefix':{'path':str(native.journal_path),
                     'bytes':len(prefix),'sha256':hashlib.sha256(prefix).hexdigest()}}
            receipt={'payload':payload,'signature':self._late_stop_signature(native,payload)}
            atomic_write(path,native._canonical(receipt)+b'\n',owned_root=directory)
        return file_record(path)

    def query(self,operation_id,*,_metadata_context=None):
        """首次接收完整生产验证；已认证历史只观察原件，不重新声明当前可消费性。"""
        _id(operation_id);state=self._read();entry=state['jobs'].get(operation_id)
        if not entry:_fail('TASK_NOT_IN_PROJECT')
        directory=_plain(entry['directory']);job=json.loads(_record(entry['job_file'],root=self.root))
        if (directory!=self.root/'jobs'/operation_id or entry.get('operation_id')!=operation_id
                or entry['job_file'].get('path')!=str(directory/'job.json')
                or job.get('schema')!='bridge.geometry-job/1' or job.get('preparation')!=self.preparation
                or job.get('operation_id')!=operation_id or job.get('task_id')!=self.prep['task_id']
                or job.get('directory')!=str(directory) or job.get('revision')!=entry.get('revision')):
            _fail('TASK_BINDING_REQUIRED')
        result_path=directory/'result.json'
        if _metadata_context is None and result_path.exists():
            candidate_record=file_record(_plain(result_path));candidate=json.loads(_record(candidate_record,root=self.root))
            extension=candidate.get('prelaunch_continuation') or {}
            if extension.get('schema')=='bridge.geometry-prelaunch-metadata-result/2':
                from .geometry_metadata_completion import metadata_validation
                with metadata_validation(self.preparation,extension['payload']['runtime_authority'],result=candidate,result_record=candidate_record) as context:
                    return self.query(operation_id,_metadata_context=context)
        if _metadata_context is not None:
            from .geometry_metadata_completion import checked_context
            checked_context(_metadata_context,preparation=self.preparation,job=job)
        if operation_id in state['completed']:
            return self._observe_accepted(state,entry,job,_metadata_context=_metadata_context)

        if result_path.exists():
            record=file_record(_plain(result_path));result=json.loads(_record(record,root=self.root))
            from .geometry_job import validate_result
            validation=validate_result(self.preparation,job,result,_metadata_context=_metadata_context)
            if not isinstance(validation,dict) or validation.get('state')!='VERIFIED':_fail('RESULT_VERIFICATION_REQUIRED')
            _goal_view(result,validation)
            with execution_lock(self.root,'geometry-session'):
                state=self._read();entry=state['jobs'][operation_id]
                if operation_id in state['completed']:
                    return self._observe_accepted(state,entry,job,_metadata_context=_metadata_context)
                if job['revision']!=state['revision']+1:_fail('COMPLETION_ORDER_INVALID')
                if file_record(result_path)!=record:_fail('COMPLETION_CHANGED')
                acceptance=self._seal_acceptance(entry,job,result,record,validation,_metadata_context=_metadata_context)
                accepted=self._verify_acceptance(entry,job,result,record,acceptance,_metadata_context=_metadata_context)
                goal=_goal_view(result,accepted['validation'])
                files=result['files']
                for asset_id,key in ((f"preview_{job['revision']}",'preview'),(f"local_{job['revision']}",'local_preview')):
                    state['assets'][asset_id]={'asset_id':asset_id,'file':copy.deepcopy(files[key]),'kind':'image',
                                               'role':'actual_render_preview' if key=='preview' else 'actual_render_local_preview','revision':job['revision']}
                entry.update(state='COMPLETE',result=record,acceptance=acceptance);state['completed'].append(operation_id)
                state['revision']=job['revision'];state['current_model_graph']=copy.deepcopy(job['plan']['model_graph'])
                self._write(state);self._event('job_complete',{'operation_id':operation_id,'revision':job['revision'],'result':record,'acceptance':acceptance})
            return {'operation_id':operation_id,'task_id':self.prep['task_id'],'state':'COMPLETE','revision':job['revision'],
                    **goal,'action':'ORIGINAL_RESULT_RETURNED','original_result':record,'files':result['files'],
                    'acceptance_receipt':acceptance,'native_dispatch_attempted':False}
        if entry.get('prelaunch_continuation') is not None:
            from .geometry_prelaunch_tail import observe_continuation
            return observe_continuation(self._acceptance_native(),entry,job)
        error_path=directory/'error.json'
        if error_path.exists():
            error_record=file_record(_plain(error_path));error=json.loads(_record(error_record,root=directory));terminal='UNKNOWN';late_stop_observed=False
            start_failure=(error.get('schema')=='bridge.geometry-controller-start-failure/1'
                           and error.get('code')=='CONTROLLER_START_FAILED' and error.get('native_started') is False
                           and not (directory/'controller-started.json').exists())
            if start_failure:
                terminal='FAILED'
            else:
                if (error.get('schema')!='bridge.geometry-job-error/1' or error.get('task_id')!=self.prep['task_id']
                        or error.get('operation_id')!=operation_id or error.get('revision')!=job['revision']
                        or error.get('preparation_record')!=self.preparation):_fail('ERROR_BINDING_REQUIRED')
                if error.get('stop_confirmed') is True:
                    from dcc_task_runtime.native_scope import NativeScope
                    usage=NativeScope(self.prep['scope']).completed_snapshot()
                    if all(ticket['stopped_at'] is not None for ticket in usage['tickets']):
                        terminal='CANCELLED' if error.get('state')=='CANCELLED' else 'FAILED'
            with execution_lock(self.root,'geometry-session'):
                # 操作者可在同锁内归档原失败并继续准备；锁外旧错误不能覆盖正在运行的修复状态。
                if not error_path.exists() or file_record(_plain(error_path))!=error_record:
                    return {'operation_id':operation_id,'state':'UNKNOWN','action':'BLOCKED',
                            'error_code':'ERROR_OBSERVATION_STALE','native_dispatch_attempted':False}
                # 错误发布早于监督器收尾时，只观察同范围稍后已签名的停止事实；不改写原错误。
                # 必须在会话锁内重读，避免将恢复授权前的关闭快照用于授权后的新状态。
                state=self._read();entry=state['jobs'][operation_id]
                record=entry.get('late_stop_observation')
                if record is not None:
                    self._verify_late_stop(entry,job,error_record,record);terminal='FAILED';late_stop_observed=True
                elif error.get('state')=='FAILED' and error.get('stop_confirmed') is False:
                    record=self._seal_late_stop(entry,job,error_record)
                    if record is not None:
                        entry['late_stop_observation']=record;terminal='FAILED';late_stop_observed=True
                entry['state']=terminal;self._write(state)
            code=error.get('code','UNKNOWN')
            if not isinstance(code,str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,99}',code):code='UNKNOWN'
            observation=({'late_stop_observed':True,'stop_confirmation_source':'signed_native_scope_history'}
                         if late_stop_observed else {})
            return {'operation_id':operation_id,'state':terminal,'action':'BLOCKED','error_code':code,
                    'native_dispatch_attempted':False,**observation}
        # 派发父进程可能已经退出，而执行子进程仍在工作；只读核对两者的实际出生身份。
        # 两者都无法确认时保留UNKNOWN，不推断失败，也不重派已有operation。
        alive=False
        try:
            controller=entry.get('controller')
            if isinstance(controller,dict) and controller.get('path')==str(directory/'controller-started.json'):
                launched=json.loads(_record(controller,root=directory))
                # 观察只使用原job内冻结的worker记录，不读当前runtime或续接授权来迁移任务。
                worker=job.get('execution_worker');worker_path=self.prep['worker']
                if worker is not None:
                    if (not isinstance(worker,dict) or set(worker)!={'path','bytes','sha256'}
                            or type(worker.get('bytes')) is not int or worker['bytes']<=0
                            or not isinstance(worker.get('sha256'),str)
                            or not re.fullmatch('[0-9a-f]{64}',worker['sha256'])):_fail('JOB_EXECUTION_WORKER_REQUIRED')
                    worker_path=str(_plain(worker['path']))
                continuation=job.get('runtime_continuation')
                if continuation is not None:
                    frozen_worker=Path(worker_path)
                    version=frozen_worker.parents[2].name if len(frozen_worker.parents)>2 else None
                    authority_name={'0.3.2':'runtime-continuation.json','0.3.3':'runtime-continuation-v033.json',
                                    '0.3.4':'geometry-recovery-authorization.json',
                                    '0.3.5':'geometry-recovery-authorization-v2.json',
                                    '0.3.6':'geometry-render-resume-authorization.json',
                                    '0.3.7':'geometry-nuke-resume-authorization.json',
                                    '0.3.8':'geometry-nuke-resume-authorization.json','0.3.9':'geometry-registration-resume-authorization.json',
                                    '0.4.1':'geometry-nuke-save-resume-authorization.json',
                                    '0.4.2':'geometry-nuke-save-runtime-successor-authorization.json',
                                    '0.4.3':'geometry-seed-cold-resume-authorization.json',
                                    '0.4.4':'geometry-seed-cold-resume-authorization.json',
                                    '0.4.5':'geometry-seed-cold-runtime-successor-authorization.json',
                                    '0.4.6':'geometry-cold-preflight-runtime-authorization.json'}.get(version)
                    if (worker is None or frozen_worker.name!='run_geometry_creative.py'
                            or frozen_worker.parent.name!='tools' or len(frozen_worker.parents)<2
                            or frozen_worker.parents[1].name!='runtime'
                            or authority_name is None or not isinstance(continuation,dict)
                            or set(continuation)!={'path','bytes','sha256'}
                            or continuation.get('path')!=str(self.root/authority_name)
                            or type(continuation.get('bytes')) is not int or continuation['bytes']<=0
                            or not isinstance(continuation.get('sha256'),str)
                            or not re.fullmatch('[0-9a-f]{64}',continuation['sha256'])):_fail('JOB_RUNTIME_CONTINUATION_REQUIRED')
                command=[self.prep['supervisor_python'],'-I','-B',worker_path,'run-job','--job',str(directory/'job.json')]
                if (launched.get('schema')=='bridge.geometry-controller-launch/1'
                        and launched.get('operation_id')==operation_id and launched.get('job')==entry['job_file']
                        and launched.get('argv')==command and launched.get('accepted_at')==entry['accepted_at']
                        and launched.get('pid')==(launched.get('process_identity') or {}).get('pid')):
                    alive=process_status(launched['process_identity'])=='alive'
        except (OSError,ValueError,TypeError,KeyError):
            alive=False
        try:
            owner_path=directory/'execute-owner.json'
            if not alive and owner_path.exists():
                owner=_object(owner_path)
                if (owner.get('schema')=='bridge.geometry-execute-owner/1'
                        and owner.get('task_id')==self.prep['task_id'] and owner.get('operation_id')==operation_id
                        and owner.get('job')==entry['job_file']):
                    alive=process_status(owner.get('process_identity'))=='alive'
        except (OSError,ValueError,TypeError,KeyError):
            alive=False
        if alive:
            return {'operation_id':operation_id,'state':'RUNNING','action':'OBSERVE_ORIGINAL','next_poll_seconds':10,'native_dispatch_attempted':False}
        code='CONTROLLER_OWNER_NOT_CONFIRMED' if (directory/'controller-started.json').exists() else 'CONTROLLER_LAUNCH_NOT_CONFIRMED'
        return {'operation_id':operation_id,'state':'UNKNOWN','action':'BLOCKED','error_code':code,'native_dispatch_attempted':False}

    def cancel(self,operation_id):
        """只向本作业写取消请求；可信停止前不宣称CANCELLED或释放资源。"""
        _id(operation_id)
        with execution_lock(self.root,'geometry-session'):
            state=self._read();entry=state['jobs'].get(operation_id)
            if not entry:_fail('TASK_NOT_IN_PROJECT')
            if entry['state'] in ('COMPLETE','FAILED','CANCELLED'):
                return {'operation_id':operation_id,'state':entry['state'],'cancel_requested':False}
            directory=_plain(entry['directory']);path=directory/'cancel-request.json'
            if not path.exists():
                value={'schema':'bridge.geometry-cancel-request/1','task_id':self.prep['task_id'],
                       'operation_id':operation_id,'job':entry['job_file'],'requested_at':time.time()}
                atomic_write(path,json.dumps(value,ensure_ascii=False,indent=2).encode(),owned_root=directory)
                self._event('cancel_requested',{'operation_id':operation_id})
            return {'operation_id':operation_id,'state':entry['state'],'cancel_requested':True,'stop_confirmed':False}
