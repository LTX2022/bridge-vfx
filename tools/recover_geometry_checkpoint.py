#!/usr/bin/env python3
"""操作者从已认证HIP检查点续接一次宿主采集失败；不再建图或改历史票据。"""
from pathlib import Path
import argparse,copy,hashlib,hmac,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.platform_support import atomic_write,ensure_private_directory
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_session import GeometrySession
from vfx_pipeline.official_graph_resume import inspect_resume_source


def seal(native,path,payload,*,new=False):
    """唯一派发意图独立认证，已有意图只能查询原操作。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_CHECKPOINT_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-checkpoint-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode(),owned_root=path.parent)
    return file_record(path)


def stable(path,value):
    """无副作用的来源解析可重复核对，固定来源文件不覆盖。"""
    if Path(path).exists():
        if _object(path)!=value:raise ValueError('GEOMETRY_CHECKPOINT_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)


def recover(job_path,original_plugin,instruction):
    """仅追加明确授权并登记同预算检查点操作；原失败和上游工程保持原位。"""
    from dcc_task_runtime.geometry_recovery import create_authorization
    from dcc_task_runtime.geometry_recovery_successor import create_authorization_v2
    job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation']
    session=GeometrySession(Path(preparation['path']));native=NativeScope(session.prep['scope']);root=native.root
    version=json.loads((ROOT.parent/'plugin.json').read_text())['version']
    successor=version=='0.3.5'
    if (version not in ('0.3.4','0.3.5')
            or session.preparation!=preparation or job_path!=root/'jobs'/job['operation_id']/'job.json'):
        raise ValueError('GEOMETRY_CHECKPOINT_INSTALLED_LAYOUT_REQUIRED')
    intent_path=root/('checkpoint-recovery-dispatch-v2.json' if successor else 'checkpoint-recovery-dispatch.json')
    serial='02' if successor else '01'
    auth_name='geometry-recovery-authorization-v2.json' if successor else 'geometry-recovery-authorization.json'
    with execution_lock(root,'geometry-session'):
        if intent_path.exists():raise ValueError('GEOMETRY_CHECKPOINT_QUERY_ORIGINAL_REQUIRED')
        if session.query(job['operation_id']).get('state')!='FAILED':raise ValueError('GEOMETRY_CHECKPOINT_FAILED_SOURCE_REQUIRED')
        state=session._read()
        if state['revision']!=0 or state['completed'] or any(v['state'] not in ('FAILED','CANCELLED') for v in state['jobs'].values()):
            raise ValueError('GEOMETRY_CHECKPOINT_SESSION_STATE_REQUIRED')
        if successor:
            # 原成功建图检查点已固定在失败作业中，只读重核来源，不再次创建节点。
            checkpoint=job.get('source_checkpoint')
            if not isinstance(checkpoint,dict) or file_record(checkpoint['path'])!=checkpoint:
                raise ValueError('GEOMETRY_CHECKPOINT_SOURCE_REQUIRED')
            source=_object(checkpoint['path'])
            if source!=inspect_resume_source(source['preparation']['path'],source['operation_id']):
                raise ValueError('GEOMETRY_CHECKPOINT_SOURCE_CHANGED')
        else:
            stages=_object(job_path.parent/'incremental-state.json')['stages'];receipt=stages['build_completed']['result']
            if stages['build_completed'].get('state')!='DONE':raise ValueError('GEOMETRY_CHECKPOINT_BUILT_REQUIRED')
            source=inspect_resume_source(job_path.parent/'geometry-execution-preparation.json',receipt['operation_id'])
            directory=root/'geometry-recovery-source';ensure_private_directory(directory)
            checkpoint=stable(directory/'checkpoint.json',source)
        plan=copy.deepcopy(job['plan']);plan['plan_id']+='_host_resume'+serial
        plan['operator_repair']={'schema':'bridge.geometry-operator-checkpoint-recovery/'+('2' if successor else '1'),
            'failed_operation_id':job['operation_id'],'authorization_path':str(root/auth_name)}
        plan.pop('plan_sha256',None);plan['plan_sha256']=canonical_sha256(plan)
        request_id='operator_host_resume'+serial+'_'+job['operation_id']
        operation_id='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
        request={'schema':'bridge.geometry-checkpoint-recovery-request/'+('2' if successor else '1'),'preparation':preparation,'task_id':job['task_id'],
            'failed_operation_id':job['operation_id'],'failed_job':file_record(job_path),'source_checkpoint':checkpoint,
            'new_plan':plan,'request_id':request_id,'new_operation_id':operation_id,'original_plan_sha256':job['plan']['plan_sha256']}
        request_record=stable(root/('geometry-checkpoint-recovery-request-v2.json' if successor else 'geometry-checkpoint-recovery-request.json'),request)
        if successor:
            authority=create_authorization_v2(preparation,file_record(root/'geometry-recovery-authorization.json'),
                Path(original_plugin).resolve(),ROOT.parent,job_path,checkpoint,request_record,instruction)
        else:
            authority=create_authorization(preparation,file_record(root/'runtime-continuation-v033.json'),
                Path(original_plugin).resolve(),ROOT.parent,job_path,checkpoint,request_record,instruction)
        if (plan['plan_id'] in state['plans'] or operation_id in state['jobs'] or request_id in state['execution_requests']
                or plan['plan_id'] in state['plan_operations']):raise ValueError('GEOMETRY_CHECKPOINT_ALREADY_REGISTERED')
        transaction={'schema':'bridge.geometry-checkpoint-dispatch/1','state':'INTENT','preparation':preparation,
            'failed_job':file_record(job_path),'request':request_record,'authority':authority,'operation_id':operation_id,'created_at':time.time()}
        seal(native,intent_path,transaction,new=True)
        # 会计锁内的一次明确恢复授权；票据/费用/旧关闭记录不改，不自动重复清除新失败。
        if successor:native.authorize_geometry_recovery_successor(authority)
        else:native.authorize_geometry_recovery(authority)
        native.check()
        state['plans'][plan['plan_id']]=plan;session._write(state)
        accepted=session.execute(plan['plan_id'],request_id,_repair_authority=authority)
        if accepted.get('operation_id')!=operation_id:raise ValueError('GEOMETRY_CHECKPOINT_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,intent_path,transaction)
        print(json.dumps({'source_operation_id':job['operation_id'],'checkpoint_operation_id':operation_id,
            'dispatch':file_record(intent_path),'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',type=Path,required=True)
    p.add_argument('--original-plugin',type=Path,required=True);p.add_argument('--instruction',required=True)
    a=p.parse_args();recover(a.job,a.original_plugin,a.instruction)
if __name__=='__main__':main()
