#!/usr/bin/env python3
"""操作者仅续接零原生的已知准备资源缺失；保留原任务和失败，不开放模型重派。"""
from pathlib import Path
import argparse,hashlib,hmac,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.platform_support import atomic_write,ensure_private_directory,process_identity
from houdini_bridge.official_karma_observation import file_record,checked_bytes
from vfx_pipeline.geometry_job import _object,prepare_execution


def copy_once(source,target):
    """原始准备失败的稳定副本只可重复读取，不能覆盖历史字节。"""
    source,target=Path(source),Path(target);raw=source.read_bytes()
    if any(p.is_symlink() for p in (source,*source.parents,target,*target.parents)):
        raise ValueError('GEOMETRY_REPAIR_LINK_REFUSED')
    if target.exists():
        if target.read_bytes()!=raw:raise ValueError('GEOMETRY_REPAIR_ARCHIVE_CHANGED')
    else:atomic_write(target,raw,owned_root=target.parent)
    return file_record(target)


def seal(native,path,payload,*,new=False):
    """修复意图独立认证；不改写原生记账或模型提案的签名域。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_REPAIR_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-preparation-repair/1\x00',hashlib.sha256).digest()
    body={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,(json.dumps(body,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode(),owned_root=path.parent)
    return file_record(path)


def repair(job_path,original_plugin,instruction):
    """唯一已审核修复：原0.3.1任务还未生成执行准备、原生票据或HIP。"""
    from vfx_pipeline.geometry_runtime_binding import create_binding,resolve_worker,continuation_record
    job_path=Path(job_path).resolve();job=_object(job_path);prep_record=job['preparation'];prep=json.loads(checked_bytes(prep_record))
    native=NativeScope(prep['scope']);directory=Path(job['directory']);archive=native.root/'runtime-continuation-source'/job['operation_id']
    if (job_path!=directory/'job.json' or directory!=native.root/'jobs'/job['operation_id']
            or ROOT!=Path(__file__).resolve().parent.parent
            or json.loads((ROOT.parent/'plugin.json').read_text())['version']!='0.3.2'):
        raise ValueError('GEOMETRY_REPAIR_INSTALLED_LAYOUT_REQUIRED')
    progress=directory/'preparation-repair.json'
    with execution_lock(directory,'geometry-job-dispatcher'):
        # 子进程只在离开owner锁后启动；整个修复仍由dispatcher唯一持有。
        with execution_lock(directory,'geometry-job-owner'):
            with execution_lock(native.root,'geometry-session'):
                if progress.exists():raise ValueError('GEOMETRY_REPAIR_QUERY_ORIGINAL_REQUIRED')
                ensure_private_directory(archive)
                records={}
                for name in ('job.json','error.json','controller-launch-intent.json','controller-started.json','controller-error.log'):
                    records[name]=copy_once(directory/name,archive/name)
                records['geometry-state.json']=copy_once(native.root/'geometry-state.json',archive/'geometry-state.json')
                oldworker=Path(prep['worker'])
                if oldworker.is_file():records['original-worker.py']=copy_once(oldworker,archive/'original-worker.py')
                elif (archive/'original-worker.py').is_file():records['original-worker.py']=file_record(archive/'original-worker.py')
                else:raise ValueError('GEOMETRY_REPAIR_ORIGINAL_WORKER_ARCHIVE_REQUIRED')
                binding=create_binding(prep_record,Path(original_plugin).resolve(),ROOT.parent,job_path,instruction)
                worker=resolve_worker(prep_record,ROOT)
                if worker['path']!=str(ROOT/'tools/run_geometry_creative.py'):
                    raise ValueError('GEOMETRY_REPAIR_ACTIVE_WORKER_REQUIRED')
                state={'schema':'bridge.geometry-preparation-repair/1','state':'INTENT','task_id':job['task_id'],
                    'operation_id':job['operation_id'],'job':file_record(job_path),'preparation':prep_record,
                    'runtime_continuation':continuation_record(prep_record,ROOT),'archive':records,
                    'authorization':{'authority':'current_user_instruction','instruction':instruction},'started_at':time.time()}
                seal(native,progress,state,new=True)
                # 已有partial快照没有执行资格，保存原字节后只重做未完成的准备步骤。
                partial=directory/'project';historical=archive/'partial-project'
                if historical.exists() or not partial.is_dir():raise ValueError('GEOMETRY_REPAIR_PARTIAL_LAYOUT_REQUIRED')
                partial.rename(historical)
                if file_record(directory/'error.json')['sha256']!=records['error.json']['sha256']:
                    raise ValueError('GEOMETRY_REPAIR_ERROR_CHANGED')
                (directory/'error.json').unlink()
                prepared=prepare_execution(prep,job)
                state.update(state='PREPARED',job_preparation=file_record(directory/'job-preparation.json'))
                seal(native,progress,state)
        command=[prep['supervisor_python'],'-I','-B',str(Path(prepared['control'])/'snapshot/tools/run_geometry_creative.py'),
                 'execute-job','--job',str(job_path)]
        state.update(state='LAUNCH_INTENT',argv=command);seal(native,progress,state)
        with (directory/'repair-01.stdout.log').open('xb') as stdout,(directory/'repair-01.stderr.log').open('xb') as stderr:
            child=subprocess.Popen(command,cwd=directory,env=dict(prep['environment']),stdin=subprocess.DEVNULL,
                stdout=stdout,stderr=stderr,start_new_session=True)
            state.update(state='RUNNING',controller_identity=process_identity(os.getpid()),execute_identity=process_identity(child.pid))
            seal(native,progress,state)
            try:code=child.wait(timeout=930)
            except subprocess.TimeoutExpired:
                # 不能因等待结束就假称已停止；原child自己的900秒有界控制保持独立。
                state.update(state='UNKNOWN',observed_at=time.time());seal(native,progress,state)
                raise ValueError('GEOMETRY_REPAIR_CHILD_STOP_UNCONFIRMED')
        state.update(state='CHILD_EXITED',returncode=code,finished_at=time.time());seal(native,progress,state)
        print(json.dumps({'operation_id':job['operation_id'],'repair':file_record(progress),'child_returncode':code},ensure_ascii=False),flush=True)
        if code!=0:raise ValueError('GEOMETRY_REPAIR_CHILD_FAILED_QUERY_ORIGINAL')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--original-plugin',type=Path,required=True);parser.add_argument('--instruction',required=True)
    args=parser.parse_args();repair(args.job,args.original_plugin,args.instruction)
if __name__=='__main__':main()
