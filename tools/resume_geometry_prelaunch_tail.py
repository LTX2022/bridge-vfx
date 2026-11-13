#!/usr/bin/env python3
"""047只续同Geometry主任务未准入的冷消费；保留旧046错误与全部原件。"""
from pathlib import Path
import argparse,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import process_identity
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_registration_resume import _context
from vfx_pipeline import geometry_prelaunch_tail as tail


def _installed():
    if json.loads((ROOT.parent/'plugin.json').read_text()).get('version')!='0.4.7':raise ValueError('GEOMETRY_PRELAUNCH_INSTALLED047_REQUIRED')


def prepare(job_path,original_plugin,execution_plugin,metadata_stop):
    _installed();job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation'];_,native=_context(preparation)
    with execution_lock(native.root,'geometry-session'):
        path=native.root/tail._AUTH
        if path.exists():
            authority=file_record(path);p,_=tail.validate(preparation,authority,native);source=_object(json.loads(Path(authority['path']).read_text())['payload']['source']['path'])
            if source['job']!=file_record(job_path) or source['metadata_stop']!=file_record(metadata_stop) or p['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve()):raise ValueError('GEOMETRY_PRELAUNCH_PREPARED_SOURCE_CHANGED')
        else:
            source_path=native.root/tail._SOURCE_NAME
            if source_path.exists():record=file_record(source_path)
            else:record=_write(source_path,tail.inspect_source(preparation,Path(original_plugin).resolve(),file_record(metadata_stop)),new=True)
            source=_object(record['path'])
            if source['job']!=file_record(job_path) or source['metadata_stop']!=file_record(metadata_stop):raise ValueError('GEOMETRY_PRELAUNCH_PREPARED_SOURCE_CHANGED')
            authority=tail.create_authorization(preparation,record,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve());p,_=tail.validate(preparation,authority,native)
        result={'state':'PREPARED_READ_ONLY','operation_id':p['cold_attempt']['main_operation_id'],'authority':authority,'cold_attempt':p['cold_attempt'],'native_dispatch_attempted':False,'slot_reconciled':False}
        print(json.dumps(result,ensure_ascii=False),flush=True);return result


def dispatch(job_path):
    _installed();job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation'];_,native=_context(preparation);authority=file_record(native.root/tail._AUTH)
    with execution_lock(native.root,'geometry-session'):
        p,_=tail.validate(preparation,authority,native);source=_object(_object(authority['path'])['payload']['source']['path'])
        if (file_record(job_path)!=source['job'] or job_path!=native.root/'jobs'/p['cold_attempt']['main_operation_id']/'job.json'):
            raise ValueError('GEOMETRY_PRELAUNCH_JOB_CHANGED')
        attempt=p['cold_attempt'];directory=Path(attempt['journal_directory']);intent=directory/'dispatch.json'
        if intent.exists():raise ValueError('GEOMETRY_PRELAUNCH_QUERY_ORIGINAL_REQUIRED')
        release=tail.reconcile_slot(preparation,authority)
        from vfx_pipeline.geometry_session import GeometrySession
        session=GeometrySession(preparation);state=session._read();entry=state['jobs'][job['operation_id']]
        if entry.get('prelaunch_continuation') not in (None,authority):raise ValueError('GEOMETRY_PRELAUNCH_CONTINUATION_CONFLICT')
        command=[session.prep['supervisor_python'],'-I','-B',p['active_worker']['path'],'run-tail','--job',str(job_path),'--authority',authority['path']]
        payload={'schema':'bridge.geometry-prelaunch-dispatch/1','preparation':preparation,'job':file_record(job_path),'authority':authority,'cold_attempt':attempt,'slot_release':release,'command':command,'state':'INTENT','created_at':time.time()}
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        _write(intent,{'payload':payload,'signature':tail._sign(native,payload,b'bridge.geometry-prelaunch-dispatch/1\x00')},new=True)
        entry['prelaunch_continuation']=authority;entry['state']='RUNNING';session._write(state)
        with (directory/'controller.stdout.log').open('ab') as stdout,(directory/'controller.stderr.log').open('ab') as stderr:
            process=subprocess.Popen(command,cwd=directory,env=dict(session.prep['environment']),stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
        started={'schema':'bridge.geometry-prelaunch-controller/1','job':file_record(job_path),'authority':authority,'operation_id':job['operation_id'],'argv':command,'process_identity':process_identity(process.pid),'observed_at':time.time()}
        _write(directory/'controller-started.json',started,new=True)
        result={'operation_id':job['operation_id'],'state':'QUEUED','cold_attempt':attempt,'metadata_dispatch_attempted':True,'native_dispatch_attempted':False}
        print(json.dumps(result,ensure_ascii=False),flush=True);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',nargs='?',choices=('run-tail',));group=parser.add_mutually_exclusive_group();group.add_argument('--prepare-only',action='store_true');group.add_argument('--dispatch',action='store_true');parser.add_argument('--job',type=Path,required=True);parser.add_argument('--original-plugin',type=Path);parser.add_argument('--execution-plugin',type=Path);parser.add_argument('--metadata-stop',type=Path);parser.add_argument('--authority',type=Path);args=parser.parse_args()
    if sum((args.prepare_only,args.dispatch,args.mode=='run-tail'))!=1:parser.error('choose prepare-only, dispatch or run-tail')
    if args.prepare_only:
        if any(value is None for value in (args.original_plugin,args.execution_plugin,args.metadata_stop)):parser.error('prepare-only requires original/execution plugins and metadata stop evidence')
        prepare(args.job,args.original_plugin,args.execution_plugin,args.metadata_stop)
    elif args.dispatch:dispatch(args.job)
    else:
        if args.authority is None:parser.error('run-tail requires authority')
        _installed();tail.run_tail(args.job,file_record(args.authority))
if __name__=='__main__':main()
