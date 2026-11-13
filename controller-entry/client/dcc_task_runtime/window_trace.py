"""Controller-owned, serial snapshot windows; signed supervisor events select OS tools."""
from __future__ import annotations
import hashlib,importlib.util,json,math,os,time
from pathlib import Path
from . import owned_process
from .startup_trace import StartupWitness
from .writer_tool_trace import file_record,_capture,_state,cleanup_confirmed
from .process_image import (scope_collector_policy, validate_collector_policy,
    collector_vmmap_count, collector_vmmap_argv, SAMPLE_COLLECTOR_POLICY, FORK_CORPSE_COLLECTOR_POLICY)
MODE='official_writer_window_diagnostic_v1'
POINTS=(2.,8.,14.)
WINDOW_SECONDS=3.3
VMMAP_DELAY_SECONDS=1.2

class SignedToolEvents:
    def __init__(self,directory,*,identity,scope_binding,writer_pid,spec,collector_policy=None):
        self.policy=scope_collector_policy({}) if collector_policy is None else validate_collector_policy(collector_policy)
        self.directory=Path(directory);self.identity=identity;self.binding=scope_binding;self.writer_pid=writer_pid
        self.spec=spec;self.rows=[];self.errors=[]
    def _write(self,event,**values):
        payload={'schema':owned_process.SCHEMA,'event':event,'identity':self.identity,'scope_binding':self.binding,
            'writer_pid':self.writer_pid,'supervisor_pid':os.getpid(),'ticket_id':self.spec['native_scope_ticket']['id'],
            'runtime_nonce':self.spec['writer_runtime']['nonce'],'observed_at':time.time(),**values}
        if self.policy['policy'] in (SAMPLE_COLLECTOR_POLICY,FORK_CORPSE_COLLECTOR_POLICY):payload['process_image_policy']=self.policy
        owned_process._signed_write(self.directory,payload);return payload
    def spawned(self,process,argv,began,deadline):
        if argv[0]!='/usr/bin/vmmap':return None
        if len(self.rows)>=collector_vmmap_count(self.policy):raise ValueError('WINDOW_ORIGINAL_VMMAP_LIMIT')
        if not collector_vmmap_argv(self.policy,self.writer_pid,argv,len(self.rows)):raise ValueError('WINDOW_UNEXPECTED_VMMAP')
        index=len(self.rows);self.rows.append({'index':index,'pid':process.pid,'finished':False})
        start=self._write('window-tool-start-'+str(index),index=index,pid=process.pid,argv=list(argv),
            started_monotonic=began,popen_monotonic=time.monotonic(),effective_deadline_monotonic=deadline)
        self.rows[index]['start']=start;return index
    def finished(self,index,exit_code,diagnostic):
        if index is None:return
        row=self.rows[index]
        if diagnostic is not None and len(owned_process._canonical(diagnostic))>16384:
            diagnostic={'reason':diagnostic.get('reason'),'oversize_sha256':hashlib.sha256(owned_process._canonical(diagnostic)).hexdigest()}
        row['done']=self._write('window-tool-finish-'+str(index),index=index,pid=row['pid'],exit_code=exit_code,
            diagnostic=diagnostic,finished_monotonic=time.monotonic(),
            started_sha256=hashlib.sha256(owned_process._canonical(row['start'])).hexdigest())
        row['finished']=True
    def observer_error(self,error):
        if len(self.errors)<16:self.errors.append(str(error)[:512])
    def close(self):
        complete=not self.errors and all(row['finished'] and type(row['done']['exit_code']) is int and
            (row['done']['diagnostic'] is None or (row['done']['diagnostic'].get('cleanup',{}).get('leader_reaped') is True and not row['done']['diagnostic'].get('cleanup',{}).get('errors'))) for row in self.rows)
        self._write('window-tool-summary',count=len(self.rows),errors=self.errors,complete=complete)
        return {'record':file_record(self.directory/'window-tool-summary.json'),'cleanup_complete':complete,
            'purpose':'SIGNED_ORIGINAL_TOOL_EVENTS_NOT_IMAGE_PROOF'}

class WindowWitness(StartupWitness):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.rows=[];self.events={};self.source_summary=None;self.slot=0
        self.policy=self.scope.collector_policy()
        for name in ('vmmap',):
            if self.pinned[name]!=file_record(self.pinned[name]['path']):raise ValueError('WINDOW_TOOL_CHANGED')
        repo=Path(__file__).resolve().parents[4]
        path=repo/'tools/qualify_native_stack.py';spec=importlib.util.spec_from_file_location('_window_snapshot_adapter',path)
        self.adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.adapter)
    def _receipt(self,event):return owned_process.read_receipt(self.directory,event,identity=self.identity)
    def _stopped(self):
        if self.closed.is_set():return True
        value=self._receipt('stopped')
        if value is not None and value.get('pid')!=self.child['pid']:raise ValueError('WINDOW_STOP_PID_CHANGED')
        return value is not None
    def _ready(self):
        value=self._receipt('runtime-ready')
        if value is not None:owned_process._ready_payload(value,identity=self.identity,pid=self.child['pid'],command_hash=self.child['argv_sha256'],runtime=self.intent['writer_runtime'])
        return value is not None
    def _phase(self):
        phase=None
        for path in self.root.glob('worker_*.json'):
            if path.stat().st_size>8192:raise ValueError('WINDOW_STAGE_LIMIT')
            value=json.loads(path.read_text())
            if value.get('pid')!=self.child['pid'] or value.get('schema')!='bridge.startup-stage/1' or value.get('phase')!=path.stem:raise ValueError('WINDOW_STAGE_IDENTITY')
            if type(value.get('monotonic')) not in (int,float) or not math.isfinite(value['monotonic']):raise ValueError('WINDOW_STAGE_CLOCK')
            if phase is None or value['monotonic']>=phase['monotonic']:phase=value
        return phase or {'phase':'owned_popen','monotonic':self.child['popen_return_monotonic']}
    def _common_event(self,value):
        return (value.get('process_image_policy',scope_collector_policy({}))==self.policy
            and value.get('scope_binding')==self.scope.binding and value.get('writer_pid')==self.child['pid']
            and value.get('supervisor_pid')==self.child['supervisor_pid'] and value.get('ticket_id')==self.child['ticket_id']
            and value.get('runtime_nonce')==self.child['runtime_nonce'])
    def _refresh(self):
        record_summary=self._receipt('window-tool-summary')
        for index in range(4):
            start=self._receipt('window-tool-start-'+str(index))
            if start is None:continue
            if (not self._common_event(start) or start.get('index')!=index):
                raise ValueError('WINDOW_TOOL_EVENT_IDENTITY')
            argv=start.get('argv',[])
            if not collector_vmmap_argv(self.policy,self.child['pid'],argv,index):raise ValueError('WINDOW_TOOL_EVENT_COMMAND')
            if (type(start.get('pid')) is not int or not 0<start['pid']<=0xffffffff
                    or any(type(start.get(k)) not in (int,float) or not math.isfinite(start[k]) for k in ('started_monotonic','popen_monotonic','effective_deadline_monotonic'))
                    or not start['started_monotonic']<=start['popen_monotonic']<start['effective_deadline_monotonic']
                    or start['effective_deadline_monotonic']>min(start['started_monotonic']+5,self.child['collection_end_monotonic'])):
                raise ValueError('WINDOW_TOOL_EVENT_CLOCK')
            event=self.events.setdefault(index,{'start':start,'handled':False})
            if event['start']!=start:raise ValueError('WINDOW_TOOL_EVENT_CHANGED')
            done=self._receipt('window-tool-finish-'+str(index))
            if done is not None:
                if (not self._common_event(done) or done.get('pid')!=start['pid'] or done.get('index')!=index or done.get('scope_binding')!=self.scope.binding
                        or done.get('started_sha256')!=hashlib.sha256(owned_process._canonical(start)).hexdigest()
                        or type(done.get('finished_monotonic')) not in (int,float) or not math.isfinite(done['finished_monotonic'])
                        or done['finished_monotonic']<start['popen_monotonic']):raise ValueError('WINDOW_TOOL_FINISH_CHANGED')
                event['done']=done
        if record_summary is not None:
            if (not self._common_event(record_summary) or record_summary.get('scope_binding')!=self.scope.binding or record_summary.get('writer_pid')!=self.child['pid']
                    or record_summary.get('count')!=len(self.events) or record_summary.get('complete') is not True or record_summary.get('errors')):
                raise ValueError('WINDOW_TOOL_SUMMARY_INCOMPLETE')
            self.source_summary=record_summary
    def _normal_done(self,index):
        self._refresh();done=self.events.get(index,{}).get('done')
        return done is not None and done.get('exit_code')==0 and done.get('diagnostic') is None
    def _capture_window(self,kind,index,pid,expected,end):
        row={'kind':kind,'index':index,'pid':pid,'expected_path':expected,'valid_stack':False,
            'phase_before':self._phase(),'tools':[]};self.rows.append(row)
        def cancel():return self._stopped() or (kind=='vmmap' and self._receipt('window-tool-finish-'+str(index)) is not None)
        def take(label,argv,cap):
            value=_capture(argv,min(end,time.monotonic()+cap),cancel)
            self._save(kind+'-'+str(index)+'-'+label,value)
            row['tools'].append(self.tools[-1]);return value
        argv=[self.pinned['ps']['path'],'-p',str(pid),'-o','pid=,ppid=,lstart=,stat=,comm=']
        before=take('before',argv,.35)
        if not cleanup_confirmed(before):raise ValueError('WINDOW_AUXILIARY_CLEANUP_UNKNOWN')
        if not before['complete'] or before['stderr']:
            if kind=='vmmap' and before['termination_reason']=='CANCELLED' and not before['stderr'] and cleanup_confirmed(before) and self._normal_done(index):row['state']='NORMAL_TOOL_ENDED';return
            raise ValueError('WINDOW_PRE_IDENTITY_UNAVAILABLE')
        _state(before['stdout'],pid,self.child['supervisor_pid'],expected)
        sample=take('sample',[self.pinned['sample']['path'],str(pid),'0','1','-file','/dev/stdout'],2.5)
        if not cleanup_confirmed(sample):raise ValueError('WINDOW_AUXILIARY_CLEANUP_UNKNOWN')
        if kind=='vmmap' and not sample['complete'] and sample['termination_reason']=='CANCELLED' and cleanup_confirmed(sample) and self._normal_done(index):
            row['state']='NORMAL_TOOL_ENDED';return
        if not sample['complete']:raise ValueError('WINDOW_SAMPLE_INCOMPLETE')
        after=take('after',argv,.35)
        if kind=='vmmap' and not after['complete'] and after['termination_reason']=='CANCELLED' and cleanup_confirmed(after) and self._normal_done(index):
            row['state']='NORMAL_TOOL_ENDED';return
        row['binding']=self.adapter.assess(__import__(__package__+'.writer_tool_trace',fromlist=['cleanup_confirmed']),before,sample,after,pid=pid,parent=self.child['supervisor_pid'],expected=expected)
        row.update(valid_stack=True,state='CAPTURED',capture_started_monotonic=before['started_monotonic'],
            capture_ended_monotonic=after['ended_monotonic'],phase_after=self._phase())
        row['phase_consistent']=row['phase_before']['phase']==row['phase_after']['phase']
        if kind=='vmmap' and row['capture_ended_monotonic']>=end:raise ValueError('WINDOW_CAPTURE_LATE')
    def _run(self):
        try:
            while not self.closed.is_set() and time.monotonic()<self.deadline-4:
                child=self._receipt('diagnostic-child')
                if child is not None:break
                self.closed.wait(.01)
            else:raise ValueError('WINDOW_CHILD_FACT_UNAVAILABLE')
            self.intent=json.loads((self.directory/'intent.json').read_text())
            if (type(child.get('pid')) is not int or not 0<child['pid']<=0xffffffff
                    or child.get('scope_binding')!=self.scope.binding or child.get('supervisor_identity')!=self.supervisor_identity
                    or child.get('supervisor_pid')!=self.supervisor_identity['pid'] or child.get('ticket_id')!=self.intent.get('native_scope_ticket',{}).get('id')
                    or child.get('runtime_nonce')!=self.intent.get('writer_runtime',{}).get('nonce')
                    or child.get('argv_sha256')!=hashlib.sha256(owned_process._canonical(self.command)).hexdigest()
                    or child.get('popen_time_origin')!='owned_popen_return' or child.get('purpose')!='STARTUP_DIAGNOSTIC_ONLY_NO_IMAGE_PROOF'
                    or child.get('collection_end_monotonic')!=self.intent.get('writer_runtime',{}).get('collection_end')
                    or any(type(child.get(k)) not in (int,float) or not math.isfinite(child[k]) for k in ('popen_return_monotonic','collection_end_monotonic'))
                    or not child['popen_return_monotonic']<child['collection_end_monotonic']<=child['popen_return_monotonic']+22):raise ValueError('WINDOW_CHILD_FACT_MISMATCH')
            self.child=child;end=min(self.deadline-1,child['collection_end_monotonic']-.5)
            while not self._stopped() and time.monotonic()<end:
                self._refresh();now=time.monotonic();selected=None
                for index,event in sorted(self.events.items()):
                    if event['handled']:continue
                    if event.get('done') is not None:event['handled']=True;continue
                    if now>=event['start']['popen_monotonic']+VMMAP_DELAY_SECONDS:
                        selected=('vmmap',index,event['start']['pid'],self.pinned['vmmap']['path'],min(end,event['start']['effective_deadline_monotonic']-.25));event['handled']=True;break
                ready=self._ready()
                if selected is None and not ready and self.slot<len(POINTS) and now>=child['popen_return_monotonic']+POINTS[self.slot]:
                    index=self.slot;self.slot+=1
                    # First point establishes a live control stack; later points require a stalled phase.
                    if index==0 or now-self._phase()['monotonic']>=2:selected=('hython',index,child['pid'],self.expected,end)
                if selected is not None:
                    if selected[-1]-time.monotonic()<WINDOW_SECONDS:raise ValueError('WINDOW_EFFECTIVE_TIME_INSUFFICIENT')
                    self._capture_window(*selected)
                self.closed.wait(.01)
        except BaseException as error:self.reason=type(error).__name__+':'+str(error)[:512]
        finally:
            try:
                if self.child is not None:
                    self._refresh()
                    if self._ready() and self.source_summary is None:raise ValueError('WINDOW_ORIGINAL_TOOL_SOURCE_UNFINISHED')
                    if any('done' not in item for item in self.events.values()):raise ValueError('WINDOW_ORIGINAL_TOOL_FINISH_MISSING')
            except BaseException as error:self.reason=self.reason or type(error).__name__+':'+str(error)[:512]
            self.sample_valid=any(row['valid_stack'] for row in self.rows)
            self.state='INCOMPLETE' if self.reason else 'CAPTURED' if self.sample_valid else 'SKIPPED_READY_OR_STOPPED'
    def finish(self):
        self.closed.set()
        if self.thread is not None:self.thread.join(max(0.,min(.5,self.deadline-time.monotonic())))
        joined=self.thread is None or not self.thread.is_alive()
        stop=self._receipt('stopped');start=self._receipt('started');ready=self._receipt('runtime-ready')
        rows=self.rows if joined else []
        for row in rows:
            if row['kind']=='vmmap':
                event=self.events.get(row['index'],{});done=event.get('done');diagnostic={} if done is None else done.get('diagnostic') or {}
                row['same_timeout_window']=bool(row['valid_stack'] and done is not None and diagnostic.get('reason')=='PROCESS_IMAGE_TIMEOUT'
                    and row['capture_ended_monotonic']<=min(done['finished_monotonic'],event['start']['effective_deadline_monotonic']))
            else:
                row['same_timeout_window']=bool(row['valid_stack'] and row.get('phase_consistent') and ready is None and start is not None
                    and any(word in start.get('writer_process_binding_error','') for word in ('COLLECTION_TIMEOUT','RUNTIME_READY_TIMEOUT'))
                    and row['capture_ended_monotonic']<self.child['collection_end_monotonic'])
        value={'schema':'bridge.window-capture-report/1','scope_binding':self.scope.binding,'identity':self.identity,
            'evidence_source':'external_controller_diagnostic_not_image_proof',
            'capture_policy':{'startup_points_seconds':list(POINTS),'vmmap_delay_seconds':VMMAP_DELAY_SECONDS,
                'minimum_window_seconds':WINDOW_SECONDS,'sample_cap_seconds':2.5},'rows':rows,'events':self.events if joined else {},
            'reason':self.reason,'thread_joined':joined,'qualification':self.scope.scope['stack_qualification'],
            'same_timeout_stack_count':sum(row.get('same_timeout_window',False) for row in rows),
            'valid_stack_count':sum(row['valid_stack'] for row in rows),'new_business_or_full_chain_acceptance':False,
            'stopped_sha256':None if stop is None else hashlib.sha256(owned_process._canonical(stop)).hexdigest()}
        path=self.directory/'window-captures.json';path.write_text(json.dumps(self.scope._envelope(value),sort_keys=True,separators=(',',':')))
        self.window_report=file_record(path)
        return super().finish()
