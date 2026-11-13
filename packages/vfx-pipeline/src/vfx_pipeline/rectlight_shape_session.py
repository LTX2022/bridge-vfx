"""RectLight等面积软箱的两轮模型会话；只经已有受控图执行当前目标。"""
from __future__ import annotations
import base64,hashlib,json,os,re,subprocess,time
from pathlib import Path
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write,ensure_private_directory
from houdini_bridge.official_karma_observation import checked_bytes,file_record
from houdini_bridge.rectlight_shape_target import shape_values


def _write(path,value):atomic_write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n').encode(),owned_root=path.parent)
def _id(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',value):raise ValueError('RECT_SHAPE_REQUEST_ID_REQUIRED')
    return value

class RectlightShapeSession:
    """所有请求绑定隔离任务；原场景和过去50票仅作来源。"""
    def __init__(self,preparation,connection_id=None,*,state_directory=None,read_only=False):
        from dcc_task_runtime.native_scope import NativeScope
        self.preparation=file_record(Path(preparation));self.prep=json.loads(checked_bytes(self.preparation));self.root=Path(preparation).parent
        if self.prep.get('schema')!='bridge.rectlight-shape-preparation/1':raise ValueError('RECT_SHAPE_PREPARATION_REQUIRED')
        self.read_only=read_only;self.consumer=state_directory is not None
        if read_only and self.consumer:raise ValueError('RECT_SHAPE_STATE_MODE_CONFLICT')
        if read_only or self.consumer:
            from .rectlight_shape_execution import readonly_shape_scope
            self.native=readonly_shape_scope(self.prep['scope'])
        else:self.native=NativeScope(self.prep['scope'])
        self.source_state=self.root/'shape-state.json'
        self.state_path=self.source_state;self.log=self.root/'shape-events.jsonl'
        if self.native.root!=self.root or self.native.scope['shape_authority']!=self.prep['target_authority']:raise ValueError('RECT_SHAPE_TASK_BINDING_REQUIRED')
        if read_only or self.consumer:
            source=json.loads(checked_bytes(file_record(self.source_state)))
            if source.get('schema')!='bridge.rectlight-shape-state/1' or source.get('creative_task_id')!=self.prep['creative_task_id']:
                raise ValueError('RECT_SHAPE_STATE_BINDING_REQUIRED')
            if read_only:return
            # 已完成工程的接收状态只写包外消费者目录，原签名任务与事件不取写锁。
            directory=Path(state_directory).absolute()
            if directory.is_relative_to(self.root) or any(p.is_symlink() for p in (directory,*directory.parents)):
                raise ValueError('RECT_SHAPE_CONSUMER_DIRECTORY_REQUIRED')
            ensure_private_directory(directory);self.state_path=directory/'shape-state.json';self.log=directory/'shape-events.jsonl'
            with execution_lock(directory,'rectlight-shape-session'):
                if not self.state_path.exists():_write(self.state_path,source)
            self._read()
            return
        with execution_lock(self.root,'rectlight-shape-session'):
            if not self.state_path.exists():
                assets={k:{'asset_id':k,'file':v['preview'],'revision':0} for k,v in self.prep['media'].items()}
                _write(self.state_path,{'schema':'bridge.rectlight-shape-state/1','creative_task_id':self.prep['creative_task_id'],
                  'assets':assets,'served':{},'observations':{},'plans':{},'requests':{},'jobs':{},'completed':[],
                  'current_asset':'current','current_shape':{'width':.9,'height':.9}})
    def _read(self):
        value=json.loads(checked_bytes(file_record(self.state_path)))
        if value.get('schema')!='bridge.rectlight-shape-state/1' or value.get('creative_task_id')!=self.prep['creative_task_id']:
            raise ValueError('RECT_SHAPE_STATE_BINDING_REQUIRED')
        return value
    def _writable(self):
        if self.read_only:raise ValueError('RECT_SHAPE_READ_ONLY_SESSION')
    def _event(self,kind,payload):
        from dcc_task_runtime.canonical import canonical_sha256
        prior=json.loads(self.log.read_text().splitlines()[-1]) if self.log.exists() else None
        v={'sequence':0 if prior is None else prior['sequence']+1,'time':time.time(),'kind':kind,'payload':payload,'previous':None if prior is None else prior['sha256']};v['sha256']=canonical_sha256(v)
        with self.log.open('a',encoding='utf-8') as f:f.write(json.dumps(v,ensure_ascii=False,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
    def catalog(self):
        state=self._read()
        return {'creative_task_id':self.prep['creative_task_id'],'source_scene_task_id':self.prep['task_id'],'revision':len(state['completed']),
          'profile':'rectlight_equal_area_shape_v1','target':{'area':.81,'width':[.9,1.8],'height':[.45,.9],'ratio':[2,4],'exposure_frozen':-.25},
          'current_shape':state['current_shape'],'current_asset':state['current_asset'],'reference_id':'reference',
          'assets':[{k:v for k,v in a.items() if k!='file'} for a in state['assets'].values()],
          'model_controls':{'rectlight_shape':{'width':'float','height':'float'}},'required_revisions':2,
          'instructions':'View reference and current images, submit own observations, propose own equal-area width/height, execute once and query original ID. Keep fixed rig. No new background connection needed.'}
    def media(self,asset_id):
        from contextlib import nullcontext
        with (nullcontext() if self.read_only else execution_lock(self.state_path.parent,'rectlight-shape-session')):
            s=self._read();a=s['assets'].get(asset_id)
            if a is None:raise ValueError('RECT_SHAPE_REGISTERED_MEDIA_REQUIRED')
            data=checked_bytes(a['file'])
            if not self.read_only:
                s['served'][asset_id]=a['file']['sha256'];_write(self.state_path,s);self._event('media_served',{'asset_id':asset_id,'file':a['file']})
            return [{'type':'text','text':json.dumps({'asset_id':asset_id,'sha256':a['file']['sha256'],'revision':a['revision']})},
                    {'type':'image','mimeType':'image/png','data':base64.b64encode(data).decode()}]
    def observe(self,asset_id,request_id,observation):
        self._writable()
        _id(request_id)
        if type(observation) is not str or not 10<=len(observation)<=4000:raise ValueError('RECT_SHAPE_OBSERVATION_REQUIRED')
        with execution_lock(self.state_path.parent,'rectlight-shape-session'):
            s=self._read();asset=s['assets'].get(asset_id)
            if asset is None or s['served'].get(asset_id)!=asset['file']['sha256']:raise ValueError('RECT_SHAPE_VIEW_ACTUAL_MEDIA_FIRST')
            v={'observation_id':request_id,'asset_id':asset_id,'image_sha256':asset['file']['sha256'],'observation':observation}
            if request_id in s['observations'] and s['observations'][request_id]!=v:raise ValueError('RECT_SHAPE_OBSERVATION_CONFLICT')
            s['observations'][request_id]=v;_write(self.state_path,s);self._event('observation',v);return {'observation_id':request_id,'stored':True}
    def propose(self,request_id,base_revision,goal,rationale,observation_ids,rectlight_shape=None,model_graph=None,edits=None):
        self._writable()
        _id(request_id);dims=shape_values(rectlight_shape)
        if model_graph is not None or edits is not None:raise ValueError('RECT_SHAPE_NO_MODEL_OR_OTHER_EDITS')
        with execution_lock(self.state_path.parent,'rectlight-shape-session'):
            s=self._read();revision=len(s['completed'])
            if base_revision!=revision or revision>=2 or dims==s['current_shape']:raise ValueError('RECT_SHAPE_DISTINCT_CURRENT_REVISION_REQUIRED')
            obs=[s['observations'].get(k) for k in observation_ids]
            if not obs or any(x is None for x in obs) or not {'reference',s['current_asset']}.issubset({x['asset_id'] for x in obs}):raise ValueError('RECT_SHAPE_REFERENCE_CURRENT_OBSERVATIONS_REQUIRED')
            p={'plan_id':request_id,'request_id':request_id,'revision':revision+1,'base_revision':revision,'base_shape':s['current_shape'],
               'rectlight_shape':dims,'exposure':-.25,'base_exposure':-.25,'goal':goal,'rationale':rationale,'observation_ids':observation_ids}
            if request_id in s['plans'] and s['plans'][request_id]!=p:raise ValueError('RECT_SHAPE_PLAN_CONFLICT')
            s['plans'][request_id]=p;_write(self.state_path,s);self._event('plan',p);return {'plan_id':request_id,'ready':True,'revision':revision+1,'rectlight_shape':dims}
    def execute(self,plan_id,request_id):
        self._writable()
        if self.consumer:raise ValueError('RECT_SHAPE_COMPLETED_CONSUMER_NO_EXECUTION')
        _id(request_id)
        with execution_lock(self.root,'rectlight-shape-session'):
            s=self._read()
            if request_id in s['requests']:
                old=s['requests'][request_id]
                if old['plan_id']!=plan_id:raise ValueError('RECT_SHAPE_EXECUTION_CONFLICT')
                return {**old,'state':s['jobs'][old['operation_id']]['state'],'replayed':True}
            plan=s['plans'].get(plan_id)
            if plan is None or plan['base_revision']!=len(s['completed']) or plan['base_shape']!=s['current_shape'] or any(j['state']!='COMPLETE' for j in s['jobs'].values()):raise ValueError('RECT_SHAPE_PLAN_OR_ORIGINAL_QUERY_REQUIRED')
            self.native.check();operation='rshape_'+hashlib.sha256((self.prep['creative_task_id']+request_id).encode()).hexdigest()[:24]
            directory=self.root/'jobs'/operation;directory.mkdir(parents=True,exist_ok=False)
            job={'schema':'bridge.rectlight-shape-job/1','preparation':self.preparation,'operation_id':operation,'directory':str(directory),'plan':plan}
            path=directory/'job.json';_write(path,job)
            entry={'operation_id':operation,'plan_id':plan_id,'request_id':request_id,'revision':plan['revision'],'state':'QUEUED','directory':str(directory),'job':file_record(path)}
            s['jobs'][operation]=entry;s['requests'][request_id]=entry;_write(self.state_path,s);self._event('job_accepted',entry)
            command=[self.prep['supervisor_python'],'-I','-B',self.prep['worker'],'run-job','--job',str(path)]
            try:
                with (directory/'controller.stdout.log').open('xb') as out,(directory/'controller.stderr.log').open('xb') as err:
                    proc=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
            except OSError as error:
                _write(directory/'error.json',{'code':'CONTROLLER_START_FAILED','message':type(error).__name__,'native_success_claimed':False})
                return {'operation_id':operation,'state':'FAILED','next_step':'Query the original operation; do not redispatch.'}
            _write(directory/'controller-pid.json',{'pid':proc.pid,'started_at':time.time(),'command':command})
            return {'operation_id':operation,'state':'QUEUED','revision':plan['revision'],'next_poll_seconds':15,'job_dispatched':True}
    def tasks(self):return [{'operation_id':k,'state':v['state'],'revision':v['revision'],'task_id':self.prep['creative_task_id']} for k,v in self._read()['jobs'].items()]
    def query(self,operation_id):
        _id(operation_id);s=self._read();entry=s['jobs'].get(operation_id)
        if entry is None:raise ValueError('RECT_SHAPE_OPERATION_NOT_IN_TASK')
        directory=Path(entry['directory']);result_path=directory/'result.json'
        if directory!=self.root/'jobs'/operation_id:raise ValueError('RECT_SHAPE_JOB_ROOT_REQUIRED')
        if result_path.exists():
            from .rectlight_shape_execution import validate_result
            result_record=file_record(result_path);result=json.loads(checked_bytes(result_record))
            if self.consumer or self.read_only:
                source=json.loads(checked_bytes(file_record(self.source_state)));original=source.get('jobs',{}).get(operation_id)
                if (original!=entry or operation_id not in source.get('completed',[]) or entry.get('result')!=result_record
                        or source['completed'].index(operation_id)+1!=entry['revision']):
                    raise ValueError('RECT_SHAPE_ORIGINAL_COMPLETION_REQUIRED')
            validate_result(self.preparation,entry,result,read_only=self.consumer or self.read_only)
            if self.read_only:return self._result(operation_id,result,result_record)
            with execution_lock(self.state_path.parent,'rectlight-shape-session'):
                s=self._read();entry=s['jobs'][operation_id]
                if operation_id not in s['completed']:
                    if result['revision']!=len(s['completed'])+1:raise ValueError('RECT_SHAPE_COMPLETION_ORDER_REQUIRED')
                    entry.update(state='COMPLETE',result=file_record(result_path));s['completed'].append(operation_id)
                    asset='preview_'+str(result['revision']);s['assets'][asset]={'asset_id':asset,'file':result['preview']['preview'],'revision':result['revision']}
                    s['current_asset']=asset;s['current_shape']=result['plan']['rectlight_shape'];_write(self.state_path,s);self._event('job_complete',{'operation_id':operation_id,'result':entry['result']})
                elif entry['result']!=file_record(result_path):raise ValueError('RECT_SHAPE_COMPLETION_CHANGED')
            return self._result(operation_id,result,result_record)
        error=directory/'error.json'
        if error.exists():return {'state':'FAILED','operation_id':operation_id,'error':json.loads(error.read_text()),'next_step':'Inspect this original operation; never re-dispatch or change request ID.'}
        phase=None;journal=directory/'incremental-state.json'
        if journal.exists():
            stages=json.loads(journal.read_text()).get('stages',{});phase=[k for k,v in stages.items() if v.get('state')=='DONE']
        return {'state':'RUNNING','operation_id':operation_id,'completed_steps':phase,'next_poll_seconds':15,'native_dispatch_attempted':False}
    def _result(self,operation_id,result,record):
        """交付原作业的正式文件身份，不从目录或当前登记推断旧版本。"""
        value={'state':'COMPLETE','operation_id':operation_id,'task_id':self.prep['creative_task_id'],'source_scene_task_id':self.prep['task_id'],'revision':result['revision'],
          'rectlight_shape':result['plan']['rectlight_shape'],'artifact_id':result['artifact']['artifact_id'],'artifact_version':result['artifact']['version'],
          'files':{**result['files'],'preview':result['preview']['preview']},'original_result':record,'native_dispatch_attempted':False,'provider_identity':'unknown'}
        if self.consumer or self.read_only:
            source=json.loads(checked_bytes(file_record(self.source_state)))
            historical=result['revision']<len(source['completed'])
            value.update(historical=historical,result_view='immutable_history' if historical else 'original_completion',
                consumable_for_new_execution=False)
        return value
