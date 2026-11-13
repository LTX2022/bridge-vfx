"""Bounded diagnostic witnesses of owned vmmap calls, never image-proof evidence."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime,timezone
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
from .process_image import (scope_collector_policy, validate_collector_policy,
    collector_vmmap_count, collector_vmmap_argv, SAMPLE_COLLECTOR_POLICY, FORK_CORPSE_COLLECTOR_POLICY)

MODE = 'official_writer_identity_diagnostic_v1'
SCHEMA = 'bridge.writer-tool-trace/1'
MAX_CALLS = 4
MAX_STDOUT = 1024*1024
MAX_STDERR = 16384
TRIGGER_SECONDS = .5
SAMPLE_SECONDS = 2.5


def file_record(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('TRACE_SYMLINK')
    data=path.read_bytes()
    return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def _tool_environment(*,inherit_timezone=False):
    environment={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C','LANG':'C','TZ':'UTC'}
    if inherit_timezone:
        # Supervisor birth tokens use platform_support's inherited timezone.
        environment.pop('TZ')
        if 'TZ' in os.environ:environment['TZ']=os.environ['TZ']
    return environment


def _capture(argv, deadline, cancel, *, inherit_timezone=False):
    """Diagnostic tools may write progress on stderr; preserve both capped streams."""
    work_end=deadline-.15
    began=time.monotonic();process=None;output=[bytearray(),bytearray()];eof=[False,False]
    result={'argv':argv,'started_monotonic':began,'deadline_monotonic':deadline,'complete':False}
    def boundary():
        if time.monotonic()>=work_end:
            result['termination_reason']='DEADLINE';raise TimeoutError('TRACE_DEADLINE')
        if cancel():
            result['termination_reason']='CANCELLED';raise TimeoutError('TRACE_CANCELLED')
    try:
        boundary()
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=True,env=_tool_environment(inherit_timezone=inherit_timezone))
        result['pid']=process.pid
        with selectors.DefaultSelector() as selector:
            for index,stream in enumerate((process.stdout,process.stderr)):
                os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,index)
            while selector.get_map():
                boundary()
                for key,_ in selector.select(min(.02,max(0.,work_end-time.monotonic()))):
                    index=key.data;cap=MAX_STDOUT if index==0 else MAX_STDERR
                    chunk=os.read(key.fileobj.fileno(),min(65536,cap-len(output[index])+1))
                    if not chunk:eof[index]=True;selector.unregister(key.fileobj)
                    else:
                        output[index].extend(chunk)
                        if len(output[index])>cap:raise ValueError('TRACE_OUTPUT_LIMIT')
            process.wait(timeout=max(.001,work_end-time.monotonic()))
            result['complete']=time.monotonic()<deadline and process.returncode==0
    except BaseException as error:
        result.setdefault('termination_reason','DEADLINE' if isinstance(error,subprocess.TimeoutExpired) else 'ERROR')
        result['error']=type(error).__name__+':'+str(error)[:256]
    finally:
        result.setdefault('termination_reason','RETURNED')
        result['spawned']=process is not None
        cleanup={'leader_reaped':False if process is not None else None,'group_absent':process is None,'errors':[]}
        if process is not None:
            try:
                # The group belongs only to this diagnostic child.
                try:os.killpg(process.pid,0)
                except ProcessLookupError:pass
                else:os.killpg(process.pid,signal.SIGKILL)
            except Exception as error:cleanup['errors'].append(type(error).__name__)
            try:
                process.wait(timeout=max(.001,min(.15,deadline-time.monotonic())))
                cleanup['leader_reaped']=True
            except Exception as error:cleanup['errors'].append(type(error).__name__)
            try:os.killpg(process.pid,0)
            except ProcessLookupError:cleanup['group_absent']=True
            except Exception as error:cleanup['errors'].append(type(error).__name__)
            for stream in (process.stdout,process.stderr):
                try:stream.close()
                except Exception as error:cleanup['errors'].append(type(error).__name__)
            result['exit_code']=process.returncode
        result.update(cleanup=cleanup,ended_monotonic=time.monotonic(),eof=eof,
            stdout=bytes(output[0][:MAX_STDOUT]),stderr=bytes(output[1][:MAX_STDERR]))
        result['complete']=result['complete'] and cleanup_confirmed(result)
    return result


def _state(data,pid,parent,expected_path="/usr/bin/vmmap"):
    lines=data.decode('utf-8',errors='strict').splitlines()
    if len(lines)!=1:raise ValueError('TRACE_PROCESS_STATE_AMBIGUOUS')
    fields=lines[0].split(None,8)
    if (len(fields)!=9 or fields[0]!=str(pid) or fields[1]!=str(parent)
            or fields[8]!=expected_path or fields[7].startswith('Z')):
        raise ValueError('TRACE_PROCESS_STATE_MISMATCH')
    return {'pid':pid,'ppid':parent,'birth':' '.join(fields[2:7]),'state':fields[7],'path':fields[8]}


def cleanup_confirmed(tool):
    cleanup=tool.get('cleanup',{})
    return (tool.get('spawned') in (True,False) and cleanup.get('group_absent') is True
        and cleanup.get('errors')==[] and (cleanup.get('leader_reaped') is True
            if tool.get('spawned') is True else cleanup.get('leader_reaped') is None))


def nonempty_call_graph(data,pid):
    text=data.decode('utf-8',errors='replace')
    processes=[line for line in text.splitlines() if line.startswith('Process:')]
    if len(processes)!=1 or not processes[0].rstrip().endswith('['+str(pid)+']'):return False
    if 'Call graph:' not in text:return False
    graph=text.split('Call graph:',1)[1].split('Total number in stack',1)[0]
    in_thread=False
    for line in graph.splitlines():
        if re.match(r'\s+\d+\s+Thread_\d+',line):in_thread=True
        elif in_thread and re.search(r'\(in [^)]+\).*\[0x[0-9a-fA-F]+[^]]*\]\s*$',line):return True
    return False


def sample_identity(data,pid,parent,birth,expected_path="/usr/bin/vmmap"):
    text=data.decode('utf-8',errors='strict');fields={}
    for line in text.splitlines():
        for key in ('Path','Parent Process','Launch Time'):
            if line.startswith(key+':'):
                if key in fields:return False
                fields[key]=line.split(':',1)[1].strip()
    try:
        launched=datetime.strptime(fields['Launch Time'],'%Y-%m-%d %H:%M:%S.%f %z').astimezone(timezone.utc).replace(tzinfo=None,microsecond=0)
        observed=datetime.strptime(birth,'%a %b %d %H:%M:%S %Y')
        return (fields['Path']==expected_path and fields['Parent Process'].endswith('['+str(parent)+']')
            and launched==observed and nonempty_call_graph(data,pid))
    except (KeyError,ValueError):return False


class ToolTrace:
    def __init__(self,directory,*,writer_pid,identity,scope_binding,collection_end,tools,collector_policy=None):
        self.policy=validate_collector_policy(collector_policy) if collector_policy is not None else scope_collector_policy({})
        self.root=Path(directory);self.root.mkdir(mode=0o700,exist_ok=False)
        self.writer_pid=writer_pid;self.identity=identity;self.binding=scope_binding
        self.collection_end=collection_end;self.tools=tools;self.rows=[];self.errors=[]
        self.lock=threading.Lock();self.closing=threading.Event();self.slot=threading.Semaphore(1)
        for name,path in (('ps','/bin/ps'),('sample','/usr/bin/sample')):
            if tools[name]!=file_record(path):raise ValueError('TRACE_TOOL_BINDING_CHANGED')

    def observer_error(self,error):
        with self.lock:self.errors.append(str(error)[:512])

    def spawned(self,process,argv,began,deadline):
        if argv[0]!='/usr/bin/vmmap':return None
        with self.lock:
            if len(self.rows)>=collector_vmmap_count(self.policy):raise ValueError('TRACE_CALL_LIMIT')
            if not collector_vmmap_argv(self.policy,self.writer_pid,argv,len(self.rows)):raise ValueError('TRACE_UNEXPECTED_VMMAP')
            row={'index':len(self.rows),'tool_pid':process.pid,'parent_pid':os.getpid(),'argv':list(argv),
                'started_monotonic':began,'spawned_monotonic':time.monotonic(),'effective_deadline_monotonic':deadline,'witness_state':'INCOMPLETE',
                'auxiliary_tools':[],'done':threading.Event(),'process':process}
            self.rows.append(row)
        thread=threading.Thread(target=self._watch,args=(row,),name='vmmap-witness-'+str(row['index']),daemon=True)
        row['thread']=thread;thread.start();return row

    def finished(self,row,exit_code,diagnostic):
        if row is None:return
        with self.lock:row.update(tool_exit_code=exit_code,tool_diagnostic=diagnostic,finished_monotonic=time.monotonic())
        row['done'].set()

    def _save_capture(self,row,name,result):
        entry={k:v for k,v in result.items() if k not in ('stdout','stderr')}
        row['auxiliary_tools'].append(entry)
        try:
            for stream in ('stdout','stderr'):
                path=self.root/(str(row['index'])+'-'+name+'.'+stream)
                path.write_bytes(result[stream]);entry[stream]=file_record(path)
        except BaseException as error:
            entry['persistence_error']=type(error).__name__+':'+str(error)[:256]
            raise
        return entry

    def _watch(self,row):
        try:
            delay=max(0.,row['started_monotonic']+TRIGGER_SECONDS-time.monotonic())
            if row['done'].wait(delay) or self.closing.is_set():
                row['reason']='TOOL_FINISHED_BEFORE_TRIGGER';return
            deadline=min(row['effective_deadline_monotonic'],self.collection_end)-.15
            if deadline-time.monotonic()<3.3:
                row['reason']='INSUFFICIENT_WITNESS_TIME';return
            if not self.slot.acquire(blocking=False):row['reason']='WITNESS_SLOT_BUSY';return
            try:
                cancel=lambda:self.closing.is_set() or row['done'].is_set()
                argv=[self.tools['ps']['path'],'-p',str(row['tool_pid']),'-o','pid=,ppid=,lstart=,stat=,comm=']
                before=_capture(argv,min(deadline,time.monotonic()+.35),cancel);self._save_capture(row,'before',before)
                if not before['complete'] or before['stderr']:raise ValueError('TRACE_PRE_STATE_UNAVAILABLE')
                pre=_state(before['stdout'],row['tool_pid'],row['parent_pid']);row['before_state']=pre
                if cancel() or row['process'].returncode is not None:raise ValueError('TRACE_TOOL_ALREADY_FINISHED')
                sample=_capture([self.tools['sample']['path'],str(row['tool_pid']),'1','1','-mayDie','-file','/dev/stdout'],
                    min(deadline-.35,time.monotonic()+SAMPLE_SECONDS),cancel)
                self._save_capture(row,'sample',sample)
                row['nonempty_call_graph']=nonempty_call_graph(sample['stdout'],row['tool_pid'])
                row['sample_identity_matches']=sample_identity(sample['stdout'],row['tool_pid'],row['parent_pid'],pre['birth'])
                if sample['complete'] and (not row['nonempty_call_graph'] or not row['sample_identity_matches']):
                    raise ValueError('TRACE_SAMPLE_INVALID')
                after=_capture(argv,min(deadline,time.monotonic()+.35),cancel);self._save_capture(row,'after',after)
                if not after['complete'] or after['stderr']:raise ValueError('TRACE_POST_STATE_UNAVAILABLE')
                post=_state(after['stdout'],row['tool_pid'],row['parent_pid']);row['after_state']=post
                row['nonempty_call_graph']=nonempty_call_graph(sample['stdout'],row['tool_pid'])
                row['sample_identity_matches']=sample_identity(sample['stdout'],row['tool_pid'],row['parent_pid'],pre['birth'])
                row['witness_state']='CAPTURED' if (pre['birth']==post['birth'] and sample['complete']
                    and sample['ended_monotonic']<row['effective_deadline_monotonic'] and row['nonempty_call_graph'] and row['sample_identity_matches']) else 'INCOMPLETE'
            finally:self.slot.release()
        except BaseException as error:row['reason']=type(error).__name__+':'+str(error)[:512]
        finally:row['witness_ended_monotonic']=time.monotonic()

    def close(self):
        self.closing.set();end=min(self.collection_end,time.monotonic()+.5)
        for row in self.rows:
            row['done'].set()
            if 'thread' in row:row['thread'].join(max(0.,end-time.monotonic()))
        rows=[];cleanup_ok=True
        for row in self.rows:
            alive=row.get('thread') is not None and row['thread'].is_alive()
            cleanup_ok=cleanup_ok and not alive
            copy=({'index':row['index'],'tool_pid':row['tool_pid'],'witness_state':'INCOMPLETE','reason':'TRACE_THREAD_NOT_JOINED','auxiliary_tools':[]} if alive else {k:v for k,v in row.items() if k not in ('done','process','thread')});copy['thread_joined']=not alive
            for tool in copy['auxiliary_tools']:
                cleanup_ok=cleanup_ok and cleanup_confirmed(tool)
            rows.append(copy)
        captured=[row['index'] for row in rows if row.get('tool_diagnostic',{} ) and row['tool_diagnostic'].get('reason')=='PROCESS_IMAGE_TIMEOUT' and row['witness_state']=='CAPTURED']
        result={'same_timeout_stacks_captured':captured,'schema':SCHEMA,'scope_binding':self.binding,'identity':self.identity,'writer_pid':self.writer_pid,
            'observer_effect':'INSTRUMENTED_DIAGNOSTIC_NOT_STABILITY_ACCEPTANCE','calls':rows,'observer_errors':self.errors,
            'cleanup_complete':bool(cleanup_ok),'diagnostics_incomplete':bool(self.errors) or not cleanup_ok or any(row['witness_state']!='CAPTURED' for row in rows)}
        if self.policy['policy'] in (SAMPLE_COLLECTOR_POLICY,FORK_CORPSE_COLLECTOR_POLICY):
            result['process_image_policy']=self.policy
        path=self.root/'summary.json';path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))
        return {'record':file_record(path),'cleanup_complete':bool(cleanup_ok)}


def survey_next_allowed(summary, *, collector_policy=None, scope_binding=None):
    """The controller supplies policy from its authenticated scope, never summary."""
    try:
        policy=scope_collector_policy({}) if collector_policy is None else validate_collector_policy(collector_policy)
        if scope_binding is not None and summary.get('scope_binding')!=scope_binding:return False
        if summary.get('process_image_policy',scope_collector_policy({}))!=policy:return False
        if (summary.get('cleanup_complete') is not True or summary.get('observer_errors')!=[]
                or summary.get('same_timeout_stacks_captured')!=[] or len(summary['calls'])!=collector_vmmap_count(policy)):return False
        for index,row in enumerate(summary['calls']):
            # Archived legacy reports keep their original shape; new policy
            # always binds both exact addressed argv and their ordered indices.
            if policy['policy'] in (SAMPLE_COLLECTOR_POLICY,FORK_CORPSE_COLLECTOR_POLICY) and (row.get('index')!=index or
                    not collector_vmmap_argv(policy,summary['writer_pid'],row.get('argv'),index)):return False
            if row.get('tool_exit_code')!=0 or row.get('tool_diagnostic') is not None or row.get('thread_joined') is not True:return False
            tools=row['auxiliary_tools']
            if any(not cleanup_confirmed(tool) or 'persistence_error' in tool for tool in tools):return False
            if any(tool.get('argv',[])[:1]==['/usr/bin/sample'] and tool.get('complete') is True for tool in tools):
                if row.get('sample_identity_matches') is not True or row.get('nonempty_call_graph') is not True:return False
            if row['witness_state']=='CAPTURED':
                if row.get('sample_identity_matches') is not True or row.get('nonempty_call_graph') is not True:return False
                continue
            if row.get('reason')=='TOOL_FINISHED_BEFORE_TRIGGER' and not tools:continue
            if row.get('reason') not in ('ValueError:TRACE_POST_STATE_UNAVAILABLE','ValueError:TRACE_PRE_STATE_UNAVAILABLE'):return False
            skipped=[tool for tool in tools if tool.get('complete') is not True]
            if not skipped or any(tool.get('termination_reason')!='CANCELLED'
                    or row['finished_monotonic']>tool['ended_monotonic'] for tool in skipped):return False
        return True
    except (KeyError,TypeError,ValueError):return False
