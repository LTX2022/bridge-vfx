#!/usr/bin/env python3
"""Prepare or execute one bounded ordinary-Python stack qualification. No DCC entry."""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,shutil,sys,time,re,math
from pathlib import Path

BUDGET={'ordinary_python_targets':1,'dcc_starts':0,'total_seconds':20,'target_seconds':8,
        'max_disk_bytes':33554432,'sample_calls':1,'extra_ps_calls':2,'supervisor_identity_ps_calls':1,
        'sample_tool_seconds':2.5,'ps_tool_seconds':.35,'automatic_retries':0}
CONTROLLER_ENV={'PATH':'/usr/bin:/bin','LC_ALL':'C','LANG':'C','TZ':'UTC'}
SUPPORT=('owned_process.py','platform_support.py','writer_tool_trace.py')
TARGET_CODE='''import os,pathlib,sys,time
ready=pathlib.Path(sys.argv[1]);release=pathlib.Path(sys.argv[2])
def qualification_wait():
 ready.write_text(str(os.getpid()))
 end=time.monotonic()+7
 while not release.exists() and time.monotonic()<end:time.sleep(.01)
qualification_wait()
'''

def plain(path):
    path=Path(path)
    if not path.is_absolute() or path!=path.resolve() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('QUALIFICATION_PLAIN_ABSOLUTE_PATH_REQUIRED')
    return path

def record(path):
    path=plain(path);raw=path.read_bytes()
    return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def verify(item):
    if record(item['path'])!=item:raise ValueError('QUALIFICATION_FROZEN_INPUT_CHANGED')

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value

def prepare(candidate,target,*,target_image):
    candidate=plain(candidate);target=plain(target)
    if candidate.exists() or target.exists() or not candidate.parent.is_dir() or not target.parent.is_dir():
        raise ValueError('QUALIFICATION_FRESH_ROOT_REQUIRED')
    if candidate==target or target.is_relative_to(candidate) or candidate.is_relative_to(target):
        raise ValueError('QUALIFICATION_DISTINCT_ROOTS_REQUIRED')
    if sys.version_info[:2]!=(3,11):raise ValueError('QUALIFICATION_PYTHON311_REQUIRED')
    repo=Path(__file__).resolve().parents[1];source=repo/'packages/dcc-task-runtime/src/dcc_task_runtime'
    candidate.mkdir(mode=0o700);support=candidate/'support';support.mkdir(mode=0o700)
    for name in SUPPORT:shutil.copyfile(source/name,support/name)
    shutil.copyfile(__file__,support/'qualify_native_stack.py')
    value={'schema':'bridge.stack-qualification-review/1','state':'PREPARED_NOT_AUTHORIZED',
        'candidate':str(candidate),'target':str(target),'budget':BUDGET,'controller_environment':CONTROLLER_ENV,
        'target_runtime_image':record(target_image),
        'tools':{'python':record(Path(sys.executable).resolve()),'ps':record('/bin/ps'),'sample':record('/usr/bin/sample')},
        'sources':[record(support/name) for name in (*SUPPORT,'qualify_native_stack.py')],
        'sample_arguments':['TARGET_PID','0','1','-file','/dev/stdout'],
        'purpose':'ONE_ORDINARY_PYTHON_TARGET_ONLY_NO_DCC_NO_ROOT_NO_FALLBACK',
        'qualification_not_hython_or_slow_call_acceptance':True}
    review=candidate/'review.json';review.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    return {'state':'PREPARED_NOT_AUTHORIZED','review':record(review),'target':str(target),'budget':BUDGET}

def read_review(path,digest):
    path=plain(path);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('QUALIFICATION_REVIEW_HASH_CHANGED')
    value=json.loads(raw)
    if value.get('schema')!='bridge.stack-qualification-review/1' or value.get('budget')!=BUDGET or value.get('controller_environment')!=CONTROLLER_ENV:
        raise ValueError('QUALIFICATION_POLICY_CHANGED')
    if value.get('sample_arguments')!=['TARGET_PID','0','1','-file','/dev/stdout']:
        raise ValueError('QUALIFICATION_COMMAND_CHANGED')
    if path!=plain(value['candidate'])/'review.json':raise ValueError('QUALIFICATION_REVIEW_LOCATION')
    support=path.parent/'support'
    if value.get('sources')!=[record(support/name) for name in (*SUPPORT,'qualify_native_stack.py')]:
        raise ValueError('QUALIFICATION_SOURCE_CHANGED')
    verify(value['target_runtime_image'])
    for item in value['tools'].values():verify(item)
    if value['tools']['ps']['path']!='/bin/ps' or value['tools']['sample']['path']!='/usr/bin/sample':
        raise ValueError('QUALIFICATION_TOOLS_CHANGED')
    if str(Path(sys.executable).resolve())!=value['tools']['python']['path']:
        raise ValueError('QUALIFICATION_PYTHON_CHANGED')
    return value

def single_snapshot_frames(data,*,pid,expected):
    """Parse the observed single-snapshot format; birth/path remain OS-side evidence."""
    text=data.decode('utf-8',errors='strict');lines=text.splitlines()
    headers=[line for line in lines if line.startswith('Analysis of sampling ')]
    if len(headers)!=1:raise ValueError('QUALIFICATION_STACK_IDENTITY_OR_FRAMES_INVALID')
    match=re.fullmatch(r'Analysis of sampling (.+) \(pid ([1-9][0-9]*)\) every ([1-9][0-9]*) milliseconds?',headers[0])
    if (match is None or int(match[2])!=pid or match[1]!=Path(expected).name
            or text.count('Call graph:')!=1
            or any(line.startswith(('Process:','Path:','Parent Process:','Launch Time:')) for line in lines)):
        raise ValueError('QUALIFICATION_STACK_IDENTITY_OR_FRAMES_INVALID')
    graph=text.split('Call graph:',1)[1].split('Total number in stack',1)[0]
    in_thread=False;frames=[]
    for line in graph.splitlines():
        if re.match(r'\s+[1-9][0-9]*\s+Thread_[0-9]+',line):in_thread=True
        elif in_thread:
            frame=re.fullmatch(r'[ \t]+(?:\+[ \t]*)?[1-9][0-9]*[ \t]+.+\(in [^)]+\).*\[0x([0-9a-fA-F]+)\][ \t]*',line)
            if frame is not None and int(frame[1],16)>0:frames.append(line.strip())
    if not frames:raise ValueError('QUALIFICATION_STACK_IDENTITY_OR_FRAMES_INVALID')
    return frames


def assess(trace,before,sample,after,*,pid,parent,expected):
    if not all(trace.cleanup_confirmed(t) for t in (before,sample,after)):
        raise ValueError('QUALIFICATION_AUXILIARY_CLEANUP_UNKNOWN')
    if not all(t.get('complete') is True for t in (before,sample,after)):
        raise ValueError('QUALIFICATION_CAPTURE_INCOMPLETE')
    if before['stderr'] or after['stderr']:raise ValueError('QUALIFICATION_PS_ERROR')
    pre=trace._state(before['stdout'],pid,parent,expected);post=trace._state(after['stdout'],pid,parent,expected)
    if pre['birth']!=post['birth']:raise ValueError('QUALIFICATION_STACK_IDENTITY_OR_FRAMES_INVALID')
    wanted_ps=['/bin/ps','-p',str(pid),'-o','pid=,ppid=,lstart=,stat=,comm=']
    if before['argv']!=wanted_ps or after['argv']!=wanted_ps or sample['argv']!=['/usr/bin/sample',str(pid),'0','1','-file','/dev/stdout']:
        raise ValueError('QUALIFICATION_CAPTURE_COMMAND_CHANGED')
    for tool in (before,sample,after):
        values=[tool[k] for k in ('started_monotonic','ended_monotonic','deadline_monotonic')]
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or not values[0]<=values[1]<=values[2]:
            raise ValueError('QUALIFICATION_CAPTURE_LATE')
    if before['ended_monotonic']>sample['started_monotonic'] or sample['ended_monotonic']>after['started_monotonic']:
        raise ValueError('QUALIFICATION_CAPTURE_ORDER_INVALID')
    frames=single_snapshot_frames(sample['stdout'],pid=pid,expected=expected)
    return {'pid':pid,'parent_pid':parent,'birth':pre['birth'],'path':expected,
        'format':'single_snapshot_analysis_header','native_frames':frames,
        'identity_binding':{'pid':'fixed owned sample argv and report analysis header',
            'parent_birth_path':'matching OS process state before and after capture'},
        'not_host_image_proof':True}

def execute(review,digest,instruction):
    value=read_review(review,digest)
    if not isinstance(instruction,str) or not instruction.strip():raise ValueError('QUALIFICATION_EXPLICIT_GRANT_REQUIRED')
    support=Path(review).parent/'support'
    if Path(__file__).resolve()!=support/'qualify_native_stack.py':raise ValueError('QUALIFICATION_FROZEN_ENTRY_REQUIRED')
    if any(k.startswith(('BRIDGE_NATIVE_SCOPE','BRIDGE_OWNED_')) for k in os.environ):
        raise ValueError('QUALIFICATION_EXISTING_NATIVE_AUTHORITY_FORBIDDEN')
    if any(os.environ.get(k)!=v for k,v in CONTROLLER_ENV.items()):raise ValueError('QUALIFICATION_CONTROLLER_ENVIRONMENT_CHANGED')
    root=plain(value['target'])
    if root.exists():raise ValueError('QUALIFICATION_RETRY_FORBIDDEN')
    root.mkdir(mode=0o700)
    owned=module('_qualification_owned',support/'owned_process.py');trace=module('_qualification_trace',support/'writer_tool_trace.py')
    began=time.monotonic();deadline=began+BUDGET['total_seconds']
    (root/'authorization.json').write_text(json.dumps({'review_sha256':digest,'instruction':instruction,
        'authority':'explicit_agent_carried_user_grant','budget':BUDGET},ensure_ascii=False,indent=2)+'\n')
    identity={'task_id':'stack-qualification','operation_id':digest[:24]};directory=root/'owned'
    handle=None;tools=[];failure=None;stack=None;stopped=None;supervisor_reaped=False
    try:
        handle=owned.launch([value['tools']['python']['path'],'-I','-B','-c',TARGET_CODE,
            str(root/'target-ready'),str(root/'target-release')],directory=directory,identity=identity,
            supervisor_executable=value['tools']['python']['path'],budget_seconds=BUDGET['target_seconds'],
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','LANG':'C','TZ':'UTC','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'},
            resource_budget={'roots':[str(root)],'max_bytes':BUDGET['max_disk_bytes']})
        while not (root/'target-ready').exists():
            if time.monotonic()>=min(began+12,deadline-6):raise ValueError('QUALIFICATION_TARGET_READY_TIMEOUT')
            if handle.poll() is not None:raise ValueError('QUALIFICATION_TARGET_EXITED')
            time.sleep(.01)
        if (root/'target-ready').read_text()!=str(handle.pid):raise ValueError('QUALIFICATION_READY_PID_CHANGED')
        def capture(label,argv,cap):
            result=trace._capture(argv,min(deadline-4,time.monotonic()+cap),lambda:handle.poll() is not None)
            entry={k:v for k,v in result.items() if k not in ('stdout','stderr')};tools.append(entry)
            for stream in ('stdout','stderr'):
                path=root/(label+'.'+stream);path.write_bytes(result[stream]);entry[stream]=record(path)
            return result
        parent=handle.started['supervisor_identity']['pid']
        argv=[value['tools']['ps']['path'],'-p',str(handle.pid),'-o','pid=,ppid=,lstart=,stat=,comm=']
        before=capture('before',argv,BUDGET['ps_tool_seconds'])
        if not before['complete'] or before['stderr']:raise ValueError('QUALIFICATION_PRE_STATE_UNAVAILABLE')
        trace._state(before['stdout'],handle.pid,parent,value['target_runtime_image']['path'])
        sample=capture('sample',[value['tools']['sample']['path'],str(handle.pid),'0','1','-file','/dev/stdout'],BUDGET['sample_tool_seconds'])
        after=capture('after',argv,BUDGET['ps_tool_seconds'])
        stack=assess(trace,before,sample,after,pid=handle.pid,parent=parent,expected=value['target_runtime_image']['path'])
    except BaseException as error:failure=type(error).__name__+':'+str(error)[:512]
    finally:
        if handle is not None:
            try:
                (root/'target-release').write_text('release\n')
                handle.wait(timeout=max(.01,min(3.,deadline-time.monotonic()-1)))
            except BaseException:
                failure=failure or "QUALIFICATION_TARGET_RELEASE_FAILED"
                try:handle.terminate();handle.wait(timeout=max(.01,min(3.,deadline-time.monotonic()-1)))
                except BaseException as error:failure=failure or 'QUALIFICATION_STOP_UNKNOWN:'+str(error)[:256]
            stopped=owned.read_receipt(directory,'stopped',identity=identity)
            supervisor_reaped=handle._supervisor is not None and handle._supervisor.poll() is not None
        elif directory.is_dir():
            # An ambiguous start retains its directory and stops here; never attach another target.
            owned._atomic(directory/'cancel.json',{'identity':identity})
            while time.monotonic()<deadline-1:
                stopped=owned.read_receipt(directory,'stopped',identity=identity)
                if stopped is not None:break
                time.sleep(.01)
    trusted_stop=(stopped is not None and stopped.get('observed_by')=='owned_child_wait'
        and stopped.get('descendant_result_unobserved') is False)
    if trusted_stop:
        started=owned.read_receipt(directory,'started',identity=identity)
        trusted_stop=(started is not None and stopped.get('pid')==started.get('pid') and
            stopped['started_sha256']==hashlib.sha256(owned._canonical(started)).hexdigest())
    if trusted_stop and (stopped.get("exit_code")!=0 or stopped.get("stop_reason") is not None):
        failure=failure or "QUALIFICATION_TARGET_DID_NOT_EXIT_NORMALLY"
    cleanup=all(trace.cleanup_confirmed(t) for t in tools) and trusted_stop and supervisor_reaped
    if not cleanup:failure=failure or 'QUALIFICATION_CLEANUP_NOT_CONFIRMED'
    if owned._disk_usage({'roots':[str(root)],'max_bytes':BUDGET['max_disk_bytes']})>BUDGET['max_disk_bytes']:
        failure=failure or 'QUALIFICATION_DISK_BUDGET'
    if time.monotonic()>deadline:failure=failure or 'QUALIFICATION_TOTAL_DEADLINE'
    result={'schema':'bridge.stack-qualification-result/1','state':'QUALIFIED_ORDINARY_TARGET_ONLY' if stack and not failure else 'FAILED_STOPPED',
        'review_sha256':digest,'evidence_source':'external_controller_diagnostic_not_host_image_proof',
        'budget':BUDGET,'dcc_starts':0,'ordinary_targets_started':1 if handle is not None else 'UNKNOWN' if directory.exists() else 0,
        'sample_calls':sum(t['argv'][0]=='/usr/bin/sample' for t in tools),'auxiliary_tools':tools,
        'failure':failure,'stack':stack,'trusted_native_stop':trusted_stop,'supervisor_reaped':supervisor_reaped,
        'cleanup_complete':cleanup,'wall_seconds_before_final_write':time.monotonic()-began,
        'measurement_point':'before_final_result_write','deadline_monotonic':deadline,
        'hython_capability_proven':False,'slow_call_root_cause_proven':False,'H21_authorized':False,
        'provisional_until_controller_exit_zero':True,'standalone_result_file_is_not_a_gate':True}
    (root/'result.json').write_text(json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    if time.monotonic()>deadline:raise ValueError('QUALIFICATION_FINAL_SEAL_DEADLINE')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare',action='store_true');modes.add_argument('--execute',action='store_true')
    parser.add_argument('--candidate');parser.add_argument('--target');parser.add_argument('--target-image');parser.add_argument('--review');parser.add_argument('--expected-review-sha256');parser.add_argument('--instruction')
    args=parser.parse_args()
    if args.prepare and not args.target_image:parser.error('--prepare requires --target-image')
    result=prepare(args.candidate,args.target,target_image=args.target_image) if args.prepare else execute(args.review,args.expected_review_sha256,args.instruction)
    print(json.dumps(result,ensure_ascii=False));return 0 if result['state'] in ('PREPARED_NOT_AUTHORIZED','QUALIFIED_ORDINARY_TARGET_ONLY') else 2
if __name__=='__main__':raise SystemExit(main())
