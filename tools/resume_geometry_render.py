#!/usr/bin/env python3
"""仅从已认证首版HIP和冷开证据续接未派发的渲染；预算增补另需用户明确答复。"""
from pathlib import Path
import argparse,copy,hashlib,hmac,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write
from dcc_task_runtime.native_scope import NativeScope
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_session import GeometrySession


def stable(path,value):
    """固定来源只在首次写入，已有内容必须逐项相同。"""
    if Path(path).exists():
        if _object(path)!=value:raise ValueError('GEOMETRY_RENDER_RESUME_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)


def seal(native,path,payload,*,new=False):
    """记录唯一派发意图；中断后只观察，不自动重做或重置票据。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_RENDER_RESUME_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-render-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,native._canonical(value)+b'\n',owned_root=path.parent)
    return file_record(path)


def resume(job_path,original_plugin,instruction,approval_text):
    """签入明确增补答复及来源；保留全部旧scope、收费、失败和已完成阶段。"""
    from dcc_task_runtime import geometry_budget_addendum as budget
    from vfx_pipeline import geometry_render_resume as route
    job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation']
    session=GeometrySession(Path(preparation['path']));native=NativeScope(session.prep['scope']);root=native.root
    if (json.loads((ROOT.parent/'plugin.json').read_text())['version']!='0.3.6'
            or session.preparation!=preparation or job_path!=root/'jobs'/job['operation_id']/'job.json'):
        raise ValueError('GEOMETRY_RENDER_RESUME_INSTALLED_LAYOUT_REQUIRED')
    if not isinstance(approval_text,str) or not approval_text.strip():raise ValueError('GEOMETRY_BUDGET_APPROVAL_REQUIRED')
    intent_path=root/'geometry-render-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if intent_path.exists():raise ValueError('GEOMETRY_RENDER_RESUME_QUERY_ORIGINAL_REQUIRED')
        if session.query(job['operation_id']).get('state')!='FAILED':raise ValueError('GEOMETRY_RENDER_RESUME_FAILED_SOURCE_REQUIRED')
        state=session._read()
        if state['revision']!=0 or state['completed'] or any(v['state'] not in ('FAILED','CANCELLED') for v in state['jobs'].values()):
            raise ValueError('GEOMETRY_RENDER_RESUME_SESSION_STATE_REQUIRED')
        source=stable(root/'geometry-render-resume-source.json',route.inspect_source(job_path))
        budget_source=stable(root/'geometry-render-source.json',budget.build_source(preparation,job_path))
        plan=copy.deepcopy(job['plan']);plan['plan_id']+='_render_resume01'
        plan['operator_repair']={'schema':'bridge.geometry-render-resume/1','failed_operation_id':job['operation_id'],
            'authorization_path':str(root/'geometry-render-resume-authorization.json')}
        plan.pop('plan_sha256',None);plan['plan_sha256']=canonical_sha256(plan)
        request_id='operator_render_resume01_'+job['operation_id']
        operation_id='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
        request={'schema':'bridge.geometry-render-resume-request/1','preparation':preparation,'task_id':job['task_id'],
            'failed_operation_id':job['operation_id'],'failed_job':file_record(job_path),'render_source':source,
            'new_plan':plan,'request_id':request_id,'new_operation_id':operation_id,'original_plan_sha256':job['plan']['plan_sha256']}
        request_record=stable(root/'geometry-render-resume-request.json',request)
        grant=budget.create_authorization(preparation,budget_source,approval_text)
        authority=route.create_authorization(preparation,Path(original_plugin).resolve(),ROOT.parent,job_path,
            source,request_record,grant,instruction)
        if (plan['plan_id'] in state['plans'] or operation_id in state['jobs'] or request_id in state['execution_requests']
                or plan['plan_id'] in state['plan_operations']):raise ValueError('GEOMETRY_RENDER_RESUME_ALREADY_REGISTERED')
        transaction={'schema':'bridge.geometry-render-dispatch/1','state':'INTENT','preparation':preparation,
            'failed_job':file_record(job_path),'request':request_record,'authority':authority,'budget_addendum':grant,
            'operation_id':operation_id,'created_at':time.time()}
        seal(native,intent_path,transaction,new=True)
        # 仅追加额度增补，不清除closed或票据；原六票收费和原许可保持原样。
        native.authorize_geometry_budget_addendum(grant);native.check()
        state['plans'][plan['plan_id']]=plan;session._write(state)
        accepted=session.execute(plan['plan_id'],request_id,_repair_authority=authority)
        if accepted.get('operation_id')!=operation_id:raise ValueError('GEOMETRY_RENDER_RESUME_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,intent_path,transaction)
        print(json.dumps({'source_operation_id':job['operation_id'],'render_operation_id':operation_id,
            'dispatch':file_record(intent_path),'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--original-plugin',type=Path,required=True);parser.add_argument('--instruction',required=True)
    parser.add_argument('--approval-text',required=True,help='用户对总15/H7的本次明确答复原文')
    args=parser.parse_args();resume(args.job,args.original_plugin,args.instruction,args.approval_text)
if __name__=='__main__':main()
