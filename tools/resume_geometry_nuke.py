#!/usr/bin/env python3
"""只续已保存NK的独立冷消费；保留原失败、生产、登记和收费。"""
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
        if _object(path)!=value:raise ValueError('GEOMETRY_NUKE_RESUME_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)


def seal(native,path,payload,*,new=False):
    """记录唯一派发意图；中断后只观察，不自动重做或重置票据。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_NUKE_RESUME_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-nuke-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,native._canonical(value)+b'\n',owned_root=path.parent)
    return file_record(path)


def resume(job_path,original_plugin,instruction,approval_text):
    """签入明确补跑答复及来源；只恢复指定失败并补冷消费者。"""
    from dcc_task_runtime import geometry_nuke_recovery as budget
    from vfx_pipeline import geometry_nuke_resume as route
    job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation']
    session=GeometrySession(Path(preparation['path']));native=NativeScope(session.prep['scope']);root=native.root
    if (json.loads((ROOT.parent/'plugin.json').read_text())['version']!='0.3.8'
            or session.preparation!=preparation or job_path!=root/'jobs'/job['operation_id']/'job.json'):
        raise ValueError('GEOMETRY_NUKE_RESUME_INSTALLED_LAYOUT_REQUIRED')
    if not isinstance(approval_text,str) or not approval_text.strip():raise ValueError('GEOMETRY_BUDGET_APPROVAL_REQUIRED')
    intent_path=root/'geometry-nuke-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if intent_path.exists():raise ValueError('GEOMETRY_NUKE_RESUME_QUERY_ORIGINAL_REQUIRED')
        if session.query(job['operation_id']).get('state')!='FAILED':raise ValueError('GEOMETRY_NUKE_RESUME_FAILED_SOURCE_REQUIRED')
        state=session._read()
        if state['revision']!=0 or state['completed'] or any(v['state'] not in ('FAILED','CANCELLED') for v in state['jobs'].values()):
            raise ValueError('GEOMETRY_NUKE_RESUME_SESSION_STATE_REQUIRED')
        archive=root/'geometry-nuke-resume-audit/before-operation.json'
        closure_path=root/'geometry-nuke-resume-audit/negative-closure.json'
        if closure_path.exists():
            # 已完成的正式负终态不重放，inspect_source会重核原archive、签名停止和释放槽。
            if not archive.is_file():raise ValueError('GEOMETRY_NUKE_RESUME_ARCHIVE_REQUIRED')
            closure=file_record(closure_path)
        else:
            before=route.inspect_before(job_path)
            from dcc_task_runtime.platform_support import ensure_private_directory
            ensure_private_directory(archive.parent)
            raw=Path(before['cold_render']['path']).read_bytes()
            if len(raw)!=before['cold_render']['bytes'] or hashlib.sha256(raw).hexdigest()!=before['cold_render']['sha256']:
                raise ValueError('GEOMETRY_NUKE_RESUME_BEFORE_CHANGED')
            if archive.exists():
                if archive.read_bytes()!=raw:raise ValueError('GEOMETRY_NUKE_RESUME_BEFORE_CHANGED')
            else:atomic_write(archive,raw,owned_root=archive.parent)
            # 只通过正式status核对原签名负停止并释放原槽，不改SQL、不冒认成功。
            negative=route.close_failed_consumer(preparation,before,file_record(archive))
            closure=stable(closure_path,negative)
        budget_source=stable(root/'geometry-nuke-budget-source.json',budget.build_source(preparation,job_path))
        grant_path=root/'geometry-nuke-recovery-authorization.json'
        if grant_path.exists():
            grant=file_record(grant_path);payload,_,closed=budget.validate(native,grant)
            if (payload.get('source')!=budget_source or payload.get('preparation')!=preparation
                    or payload.get('authority',{}).get('approval_text')!=approval_text or native._read()!=closed):
                raise ValueError('GEOMETRY_NUKE_RESUME_GRANT_CHANGED')
        else:grant=budget.create_authorization(preparation,budget_source,approval_text)
        # 许可尚未激活，只允许以精确关闭前缀核验原成功生产；不开放原生执行。
        source=stable(root/'geometry-nuke-resume-source.json',route.inspect_source(job_path,file_record(archive),closure))
        plan=copy.deepcopy(job['plan']);plan['plan_id']+='_nuke_resume01'
        plan['operator_repair']={'schema':'bridge.geometry-nuke-resume/1','failed_operation_id':job['operation_id'],
            'authorization_path':str(root/'geometry-nuke-resume-authorization.json')}
        plan.pop('plan_sha256',None);plan['plan_sha256']=canonical_sha256(plan)
        request_id='operator_nuke_resume01_'+job['operation_id']
        operation_id='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
        request={'schema':'bridge.geometry-nuke-resume-request/1','preparation':preparation,'task_id':job['task_id'],
            'failed_operation_id':job['operation_id'],'failed_job':file_record(job_path),'nuke_source':source,
            'new_plan':plan,'request_id':request_id,'new_operation_id':operation_id,'original_plan_sha256':job['plan']['plan_sha256']}
        request_record=stable(root/'geometry-nuke-resume-request.json',request)
        authority=route.create_authorization(preparation,Path(original_plugin).resolve(),ROOT.parent,job_path,
            source,request_record,grant,instruction)
        if (plan['plan_id'] in state['plans'] or operation_id in state['jobs'] or request_id in state['execution_requests']
                or plan['plan_id'] in state['plan_operations']):raise ValueError('GEOMETRY_NUKE_RESUME_ALREADY_REGISTERED')
        transaction={'schema':'bridge.geometry-nuke-dispatch/1','state':'INTENT','preparation':preparation,
            'failed_job':file_record(job_path),'request':request_record,'authority':authority,'nuke_recovery':grant,
            'operation_id':operation_id,'created_at':time.time()}
        seal(native,intent_path,transaction,new=True)
        # 仅按已签许可恢复这一次closed10；原票据、收费及所有旧许可保持原样。
        native.authorize_geometry_nuke_recovery(grant);native.check()
        state['plans'][plan['plan_id']]=plan;session._write(state)
        accepted=session.execute(plan['plan_id'],request_id,_repair_authority=authority)
        if accepted.get('operation_id')!=operation_id:raise ValueError('GEOMETRY_NUKE_RESUME_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,intent_path,transaction)
        print(json.dumps({'source_operation_id':job['operation_id'],'operation_id':operation_id,
            'dispatch':file_record(intent_path),'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--original-plugin',type=Path,required=True);parser.add_argument('--instruction',required=True)
    parser.add_argument('--approval-text',required=True,help='用户对总16/NR3的本次明确答复原文')
    args=parser.parse_args();resume(args.job,args.original_plugin,args.instruction,args.approval_text)
if __name__=='__main__':main()
