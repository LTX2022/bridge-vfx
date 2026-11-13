#!/usr/bin/env python3
"""仅续R2已登记图的Nuke保存和冷渲染；签名预检通过才激活17/NH3许可。"""
from pathlib import Path
import argparse,copy,hashlib,hmac,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write
from dcc_task_runtime.native_scope import NativeScope
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_session import GeometrySession


def stable(path,value):
    if Path(path).exists():
        if _object(path)!=value:raise ValueError('GEOMETRY_NUKE_SAVE_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)


def seal(native,path,payload,*,new=False):
    """派发前持久化唯一意图；中断后必须查询同一operation，不重新消耗票据。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_NUKE_SAVE_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-nuke-save-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,native._canonical(value)+b'\n',owned_root=path.parent)


def resume(job_path,original_plugin,execution_plugin,instruction):
    """原closed15先只读认证，再唯一append；不修改原失败及登记工程。"""
    from vfx_pipeline import geometry_nuke_save_resume as route
    from dcc_task_runtime import geometry_nuke_save_recovery as budget
    job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation'];session=GeometrySession(Path(preparation['path']))
    native=NativeScope(session.prep['scope']);root=native.root
    if (json.loads((ROOT.parent/'plugin.json').read_text())['version']!='0.4.1' or session.preparation!=preparation
            or job_path!=root/'jobs'/job['operation_id']/'job.json'):raise ValueError('GEOMETRY_NUKE_SAVE_INSTALLED_LAYOUT_REQUIRED')
    intent=root/'geometry-nuke-save-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if intent.exists():raise ValueError('GEOMETRY_NUKE_SAVE_QUERY_ORIGINAL_REQUIRED')
        if session.query(job['operation_id']).get('state')!='FAILED':raise ValueError('GEOMETRY_NUKE_SAVE_FAILED_SOURCE_REQUIRED')
        state=session._read()
        if (state['revision']!=1 or len(state['completed'])!=1 or any(e['state'] not in ('COMPLETE','FAILED','CANCELLED') for e in state['jobs'].values())):
            raise ValueError('GEOMETRY_NUKE_SAVE_SESSION_STATE_REQUIRED')
        # 先签低层许可，仍不清闭；source2/typed2完整历史检查必须在旧closed15上通过。
        low_source=stable(root/'geometry-nuke-save-budget-source.json',budget.build_source(preparation,job_path))
        low_path=root/'geometry-nuke-save-recovery-authorization.json'
        if low_path.exists():
            low=file_record(low_path);payload,_,closed=budget.validate(native,low)
            if payload['source']!=low_source or payload['authority']['approval_text']!=instruction or native._read()!=closed:
                raise ValueError('GEOMETRY_NUKE_SAVE_AUTHORITY_CHANGED')
        else:low=budget.create_authorization(preparation,low_source,instruction)
        source=stable(root/'geometry-nuke-save-resume-source.json',route.inspect_source(job_path,budget_authority=low))
        plan=copy.deepcopy(job['plan']);plan['plan_id']+='_nuke_save_resume01'
        plan['operator_repair']={'schema':'bridge.geometry-nuke-save-resume/1','failed_operation_id':job['operation_id'],
            'authorization_path':str(root/'geometry-nuke-save-resume-authorization.json')}
        plan.pop('plan_sha256',None);plan['plan_sha256']=canonical_sha256(plan)
        request_id='operator_nuke_save_resume01_'+job['operation_id'];operation='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
        request={'schema':'bridge.geometry-nuke-save-resume-request/1','preparation':preparation,'task_id':job['task_id'],
            'failed_operation_id':job['operation_id'],'failed_job':file_record(job_path),'nuke_save_source':source,
            'new_plan':plan,'request_id':request_id,'new_operation_id':operation,'original_plan_sha256':job['plan']['plan_sha256']}
        request_record=stable(root/'geometry-nuke-save-resume-request.json',request);authority_path=root/'geometry-nuke-save-resume-authorization.json'
        if authority_path.exists():
            authority=file_record(authority_path);payload,_=route.validate(preparation,authority,native)
            if (payload['source']!=source or payload['request']!=request_record or payload['authority']['instruction']!=instruction
                    or payload['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve())):
                raise ValueError('GEOMETRY_NUKE_SAVE_AUTHORITY_CHANGED')
        else:authority=route.create_authorization(preparation,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve(),job_path,source,request_record,instruction)
        if (plan['plan_id'] in state['plans'] or operation in state['jobs'] or request_id in state['execution_requests']
                or plan['plan_id'] in state['plan_operations']):raise ValueError('GEOMETRY_NUKE_SAVE_ALREADY_REGISTERED')
        transaction={'schema':'bridge.geometry-nuke-save-dispatch/1','state':'INTENT','preparation':preparation,'failed_job':file_record(job_path),
            'request':request_record,'authority':authority,'budget_authority':low,'operation_id':operation,'created_at':time.time()}
        seal(native,intent,transaction,new=True)
        native.authorize_geometry_nuke_save_recovery(low);native.check()
        state['plans'][plan['plan_id']]=plan;session._write(state)
        accepted=session.execute(plan['plan_id'],request_id,_repair_authority=authority)
        if accepted.get('operation_id')!=operation:raise ValueError('GEOMETRY_NUKE_SAVE_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,intent,transaction)
        print(json.dumps({'source_operation_id':job['operation_id'],'operation_id':operation,'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--original-plugin',type=Path,required=True);parser.add_argument('--execution-plugin',type=Path,required=True)
    parser.add_argument('--instruction',required=True);args=parser.parse_args();resume(args.job,args.original_plugin,args.execution_plugin,args.instruction)
if __name__=='__main__':main()
