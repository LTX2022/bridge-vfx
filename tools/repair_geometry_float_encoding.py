#!/usr/bin/env python3
"""操作者为已停止的首版类型编码失败授权一次修复；复用原会话执行器。"""
from pathlib import Path
import argparse,copy,hashlib,hmac,json,os,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.platform_support import atomic_write
from houdini_bridge.official_karma_observation import file_record,checked_bytes
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_session import GeometrySession
from vfx_pipeline import geometry_graph


def seal(native,path,payload,*,new=False):
    """修复派发事务有独立签名域；既有INTENT一律查询，不自动重派。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_TYPED_REPAIR_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-typed-repair-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode(),owned_root=path.parent)
    return file_record(path)


def repair(job_path,original_plugin,instruction):
    """不修改原模型选择；为等值float编码登记唯一受认证的新attempt。"""
    from vfx_pipeline.geometry_runtime_binding import create_successor_binding
    job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation']
    session=GeometrySession(Path(preparation['path']));native=NativeScope(session.prep['scope']);root=native.root
    if (ROOT!=Path(__file__).resolve().parents[1] or json.loads((ROOT.parent/'plugin.json').read_text())['version']!='0.3.3'
            or session.preparation!=preparation or job_path!=root/'jobs'/job['operation_id']/'job.json'):
        raise ValueError('GEOMETRY_TYPED_REPAIR_INSTALLED_LAYOUT_REQUIRED')
    intent_path=root/'typed-repair-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if intent_path.exists():raise ValueError('GEOMETRY_TYPED_REPAIR_QUERY_ORIGINAL_REQUIRED')
        prior=session.query(job['operation_id'])
        if prior.get('state')!='FAILED':raise ValueError('GEOMETRY_TYPED_REPAIR_ORIGINAL_FAILED_REQUIRED')
        state=session._read();old=state['jobs'][job['operation_id']]
        if (old.get('state')!='FAILED' or state['revision']!=0 or state['completed']
                or any(v['state'] not in ('FAILED','CANCELLED') for v in state['jobs'].values())):
            raise ValueError('GEOMETRY_TYPED_REPAIR_STATE_REQUIRED')
        plan=copy.deepcopy(job['plan']);plan['plan_id']+='_float_repair01'
        plan['model_graph']=geometry_graph.model_proposal(plan['model_graph']).to_dict()
        plan['selector']=geometry_graph.selector(plan['model_graph'])
        plan['operator_repair']={'schema':'bridge.geometry-operator-repair/1','failed_operation_id':job['operation_id'],
            'authorization_path':str(root/'runtime-continuation-v033.json')}
        plan.pop('plan_sha256',None);plan['plan_sha256']=canonical_sha256(plan)
        request_id='operator_float_repair01_'+job['operation_id']
        operation_id='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
        request={'schema':'bridge.geometry-typed-repair-request/1','preparation':preparation,'task_id':job['task_id'],
            'failed_operation_id':job['operation_id'],'failed_job':file_record(job_path),
            'original_plan_sha256':job['plan']['plan_sha256'],'new_plan':plan,'request_id':request_id,'new_operation_id':operation_id}
        request_path=root/'runtime-v033-repair-request.json'
        if request_path.exists():
            if _object(request_path)!=request:raise ValueError('GEOMETRY_TYPED_REPAIR_REQUEST_CHANGED')
            request_record=file_record(request_path)
        else:request_record=_write(request_path,request,new=True)
        authority=create_successor_binding(preparation,file_record(root/'runtime-continuation.json'),
            Path(original_plugin).resolve(),ROOT.parent,job_path,request_record,instruction)
        if (plan['plan_id'] in state['plans'] or operation_id in state['jobs']
                or request_id in state['execution_requests'] or plan['plan_id'] in state['plan_operations']):
            raise ValueError('GEOMETRY_TYPED_REPAIR_ALREADY_REGISTERED')
        receipt={'schema':'bridge.geometry-typed-repair-dispatch/1','state':'INTENT','task_id':job['task_id'],
            'failed_job':file_record(job_path),'request':request_record,'authority':authority,
            'operation_id':operation_id,'created_at':time.time()}
        seal(native,intent_path,receipt,new=True)
        state['plans'][plan['plan_id']]=plan;session._write(state)
        # session锁在原execute事务结束前不释放；公开MCP没有这个内部授权参数。
        accepted=session.execute(plan['plan_id'],request_id,_repair_authority=authority)
        if accepted.get('operation_id')!=operation_id:raise ValueError('GEOMETRY_TYPED_REPAIR_OPERATION_CHANGED')
        receipt.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,intent_path,receipt)
        print(json.dumps({'original_operation_id':job['operation_id'],'repair_operation_id':operation_id,
            'dispatch':file_record(intent_path),'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--job',type=Path,required=True)
    p.add_argument('--original-plugin',type=Path,required=True);p.add_argument('--instruction',required=True)
    a=p.parse_args();repair(a.job,a.original_plugin,a.instruction)
if __name__=='__main__':main()
