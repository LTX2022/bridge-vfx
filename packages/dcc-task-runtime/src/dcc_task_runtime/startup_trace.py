"""One external startup witness. Diagnostic data never supplies image authority."""
from __future__ import annotations
import hashlib,json,os,threading,time,math
from pathlib import Path
from .writer_tool_trace import (_capture,_state,cleanup_confirmed,file_record,sample_identity)

ENV = 'BRIDGE_OWNED_STARTUP_TRACE_DIR'
TRIGGER_SECONDS = 15.


def stage(directory,name,*,pid,extra=None):
    directory=Path(directory)
    if not name.replace('_','').isalnum() or len(name)>64:raise ValueError('STARTUP_STAGE_NAME')
    if any(p.is_symlink() for p in (directory,*directory.parents)):raise ValueError('STARTUP_STAGE_SYMLINK')
    value={'schema':'bridge.startup-stage/1','phase':name,'pid':pid,
        'monotonic':time.monotonic(),'observed_at':time.time()}
    if extra is not None:value['detail']=str(extra)[:256]
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    target=directory/(name+'.json');temporary=directory/(name+'.tmp')
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        if os.write(fd,raw)!=len(raw):raise OSError('STARTUP_STAGE_SHORT_WRITE')
    finally:os.close(fd)
    if target.exists():raise ValueError('STARTUP_STAGE_ALREADY_EXISTS')
    os.replace(temporary,target)


class StartupWitness:
    def __init__(self,scope,directory,identity,command,*,began,deadline):
        self.scope=scope;self.directory=Path(directory);self.root=self.directory/'startup-trace'
        self.identity=identity;self.command=command;self.began=began;self.deadline=deadline
        self.closed=threading.Event();self.thread=None;self.child=None;self.tools=[];self.reason=None
        self.state='INCOMPLETE';self.expected=scope.scope['hosts']['hython']['path'];self.sample_valid=False
        self.lock=threading.Lock()
        self.pinned=scope.scope['writer_trace_tools']
        for name in ('ps','sample'):
            if self.pinned[name]!=file_record(self.pinned[name]['path']):raise ValueError('STARTUP_TOOL_CHANGED')

    def start(self,supervisor):
        if supervisor is None:raise ValueError('STARTUP_OWNED_SUPERVISOR_REQUIRED')
        observed=_capture([self.pinned['ps']['path'],'-p',str(supervisor.pid),'-o','lstart=,stat='],
            min(self.deadline-1,time.monotonic()+1),self.closed.is_set)
        self._save('supervisor',observed,directory=self.directory)
        if not observed['complete'] or observed['stderr']:raise ValueError('STARTUP_SUPERVISOR_IDENTITY_UNKNOWN')
        birth,status=observed['stdout'].decode('utf-8',errors='strict').strip().rsplit(None,1)
        if status.startswith('Z'):raise ValueError('STARTUP_SUPERVISOR_STOPPED')
        self.supervisor_identity={'pid':supervisor.pid,'platform':'posix','birth':birth,'state':'alive'}
        self.thread=threading.Thread(target=self._run,name='external-startup-witness',daemon=True)
        self.thread.start()

    def _cancel(self):
        from . import owned_process
        if self.closed.is_set():return True
        if self.child is None:return False
        for event in ('runtime-ready','stopped'):
            payload=owned_process.read_receipt(self.directory,event,identity=self.identity)
            if payload is not None:
                if payload.get('pid')!=self.child['pid']:raise ValueError('STARTUP_READY_STOP_PID_CHANGED')
                if event=='runtime-ready':
                    owned_process._ready_payload(payload,identity=self.identity,pid=self.child['pid'],
                        command_hash=self.child['argv_sha256'],runtime=self.intent['writer_runtime'])
                return True
        return False

    def _save(self,name,result,*,directory=None):
        entry={k:v for k,v in result.items() if k not in ('stdout','stderr')}
        with self.lock:self.tools.append(entry)
        try:
            for stream in ('stdout','stderr'):
                path=(self.root if directory is None else Path(directory))/('startup-'+name+'.'+stream);path.write_bytes(result[stream]);entry[stream]=file_record(path)
        except BaseException as error:
            entry['persistence_error']=type(error).__name__+':'+str(error)[:256];raise

    def _run(self):
        from . import owned_process
        try:
            while not self.closed.is_set() and time.monotonic()<self.deadline-3:
                child=owned_process.read_receipt(self.directory,'diagnostic-child',identity=self.identity)
                if child is not None:break
                self.closed.wait(.02)
            else:raise ValueError('STARTUP_CHILD_FACT_UNAVAILABLE')
            intent=json.loads((self.directory/'intent.json').read_text())
            if (child.get('purpose')!='STARTUP_DIAGNOSTIC_ONLY_NO_IMAGE_PROOF' or child.get('scope_binding')!=self.scope.binding
                    or child.get('ticket_id')!=intent.get('native_scope_ticket',{}).get('id')
                    or child.get('runtime_nonce')!=intent.get('writer_runtime',{}).get('nonce')
                    or child.get('argv_sha256')!=hashlib.sha256(owned_process._canonical(self.command)).hexdigest()
                    or child.get('supervisor_identity')!=self.supervisor_identity or child.get('supervisor_pid')!=self.supervisor_identity['pid']
                    or child.get('collection_end_monotonic')!=intent.get('writer_runtime',{}).get('collection_end')
                    or type(child.get('popen_return_monotonic')) not in (int,float)
                    or not math.isfinite(child['popen_return_monotonic'])
                    or not child['popen_return_monotonic']<child['collection_end_monotonic']<=child['popen_return_monotonic']+22
                    or child.get('popen_time_origin')!='owned_popen_return' or type(child.get('pid')) is not int
                    or type(child.get('supervisor_pid')) is not int):
                raise ValueError('STARTUP_CHILD_FACT_MISMATCH')
            self.child=child;self.intent=intent
            end=min(self.deadline-1,child['collection_end_monotonic']-1)
            trigger=child['popen_return_monotonic']+TRIGGER_SECONDS
            while time.monotonic()<trigger:
                if self._cancel():self.state='SKIPPED_READY_OR_STOPPED';return
                self.closed.wait(min(.05,max(0.,trigger-time.monotonic())))
            if self._cancel():self.state='SKIPPED_READY_OR_STOPPED';return
            if end-time.monotonic()<3.3:raise ValueError('STARTUP_WITNESS_TIME_INSUFFICIENT')
            argv=[self.pinned['ps']['path'],'-p',str(child['pid']),'-o','pid=,ppid=,lstart=,stat=,comm=']
            before=_capture(argv,min(end,time.monotonic()+.35),self._cancel);self._save('before',before)
            if not before['complete'] or before['stderr']:raise ValueError('STARTUP_PRE_STATE_UNAVAILABLE')
            pre=_state(before['stdout'],child['pid'],child['supervisor_pid'],self.expected)
            sample=_capture([self.pinned['sample']['path'],str(child['pid']),'1','1','-file','/dev/stdout'],
                min(end-.35,time.monotonic()+2.5),self._cancel);self._save('sample',sample)
            after=_capture(argv,min(end,time.monotonic()+.35),self._cancel);self._save('after',after)
            if not after['complete'] or after['stderr']:raise ValueError('STARTUP_POST_STATE_UNAVAILABLE')
            post=_state(after['stdout'],child['pid'],child['supervisor_pid'],self.expected)
            self.sample_valid=(sample['complete'] and pre['birth']==post['birth'] and
                sample_identity(sample['stdout'],child['pid'],child['supervisor_pid'],pre['birth'],self.expected))
            self.state='CAPTURED' if self.sample_valid else 'INCOMPLETE'
            self.before=pre;self.after=post
        except BaseException as error:self.reason=type(error).__name__+':'+str(error)[:512]

    def finish(self):
        from . import owned_process
        self.closed.set()
        if self.thread is not None:self.thread.join(max(0.,min(.5,self.deadline-time.monotonic())))
        joined=self.thread is None or not self.thread.is_alive()
        with self.lock:tools=list(self.tools) if joined else []
        cleanup=joined and all(cleanup_confirmed(tool) for tool in tools)
        files=[];stage_errors=[]
        if joined and self.root.is_dir():
            for path in sorted(self.root.glob('*.json')):
                if time.monotonic()>=self.deadline:stage_errors.append('TOTAL_DEADLINE');break
                if len(files)>=32:stage_errors.append('STAGE_LIMIT');break
                try:
                    if path.stat().st_size>8192:raise ValueError('STARTUP_STAGE_LIMIT')
                    record=file_record(path)
                    if record['bytes']>8192:raise ValueError('STARTUP_STAGE_LIMIT')
                    value=json.loads(path.read_text())
                    if (value.get('schema')!='bridge.startup-stage/1' or value.get('phase')!=path.stem
                            or type(value.get('monotonic')) not in (int,float) or not math.isfinite(value['monotonic'])):raise ValueError('STARTUP_STAGE_SHAPE')
                    if self.child is None or value.get('pid') not in (self.child['pid'],self.child['supervisor_pid']):raise ValueError('STARTUP_STAGE_PID')
                    files.append(record)
                except Exception as error:stage_errors.append(type(error).__name__+':'+str(error)[:128])
        start=owned_process.read_receipt(self.directory,'started',identity=self.identity)
        stop=owned_process.read_receipt(self.directory,'stopped',identity=self.identity)
        child=owned_process.read_receipt(self.directory,'diagnostic-child',identity=self.identity)
        if child is not None and stop is not None and child.get('pid')!=stop.get('pid'):stage_errors.append('STARTUP_STOP_PID_MISMATCH')
        value={'schema':'bridge.external-startup-diagnostic/1','evidence_source':'external_controller_diagnostic',
            'not_host_image_proof':True,'scope_binding':self.scope.binding,'identity':self.identity,'state':self.state,
            'reason':self.reason,'thread_joined':joined,'cleanup_complete':bool(cleanup),'sample_identity_matches':self.sample_valid,
            'diagnostic_child':child,'started_sha256':None if start is None else hashlib.sha256(owned_process._canonical(start)).hexdigest(),
            'stopped_sha256':None if stop is None else hashlib.sha256(owned_process._canonical(stop)).hexdigest(),
            'stage_files':files,'stage_errors':stage_errors,'stage_evidence_is_prefix':True,
            'auxiliary_tools':tools,'native_stop_observed_at':None if stop is None else stop['observed_at'],
            'operation_began_monotonic':self.began,'operation_deadline_monotonic':self.deadline,
            'observer_effect':'INSTRUMENTED_DIAGNOSTIC_NOT_STABILITY_ACCEPTANCE'}
        if getattr(self,'window_report',None) is not None:value['window_capture_report']=self.window_report
        if not joined:value['auxiliary_tools']=[];value['reason']='AUXILIARY_THREAD_NOT_JOINED'
        path=self.directory/'startup-diagnostic.json'
        path.write_text(json.dumps(self.scope._envelope(value),sort_keys=True,separators=(',',':')))
        accounting={'schema':'bridge.startup-parent-accounting/1','scope_binding':self.scope.binding,'identity':self.identity,
            'diagnostic':file_record(path),'operation_wall_seconds':time.monotonic()-self.began,
            'budget_seconds':60,'includes_auxiliary_tail_and_diagnostic_sealing':True,'measurement_point':'before_final_accounting_write','native_stop_unchanged':True,
            'cleanup_complete':bool(cleanup),'native_stop_verified':stop is not None,'diagnostic_complete':stop is not None and bool(cleanup) and not stage_errors and self.reason is None and self.state in ('CAPTURED','SKIPPED_READY_OR_STOPPED'),'over_budget':time.monotonic()>self.deadline}
        target=self.directory/'startup-accounting.json';target.write_text(json.dumps(self.scope._envelope(accounting),sort_keys=True,separators=(',',':')))
        return accounting
