#!/usr/bin/env python3
"""仅续R2原成功渲染的登记与两票Nuke下游；不启动Houdini或重渲染。"""
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
        if _object(path)!=value:raise ValueError('GEOMETRY_REGISTRATION_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)


def seal(native,path,payload,*,new=False):
    """一次独立派发意图，中断后只查同一操作，不重复原生执行。"""
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_REGISTRATION_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-registration-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,native._canonical(value)+b'\n',owned_root=path.parent)


def resume(job_path,original_plugin,registration_plugin,instruction):
    """范围沿用原16/1800，不清闭、不加票，只完成已通过源验证的直接下游。"""
    from vfx_pipeline import geometry_registration_resume as route
    job_path=Path(job_path).resolve();job=_object(job_path);preparation=job['preparation'];session=GeometrySession(Path(preparation['path']))
    native=NativeScope(session.prep['scope']);root=native.root
    if (json.loads((ROOT.parent/'plugin.json').read_text())['version']!='0.3.9' or session.preparation!=preparation
            or job_path!=root/'jobs'/job['operation_id']/'job.json'):raise ValueError('GEOMETRY_REGISTRATION_INSTALLED_LAYOUT_REQUIRED')
    intent=root/'geometry-registration-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if intent.exists():raise ValueError('GEOMETRY_REGISTRATION_QUERY_ORIGINAL_REQUIRED')
        if session.query(job['operation_id']).get('state')!='FAILED':raise ValueError('GEOMETRY_REGISTRATION_FAILED_SOURCE_REQUIRED')
        state=session._read()
        if (state['revision']!=1 or len(state['completed'])!=1 or any(e['state'] not in ('COMPLETE','FAILED','CANCELLED') for e in state['jobs'].values())):
            raise ValueError('GEOMETRY_REGISTRATION_SESSION_STATE_REQUIRED')
        source=stable(root/'geometry-registration-resume-source.json',route.inspect_source(job_path))
        plan=copy.deepcopy(job['plan']);plan['plan_id']+='_registration_resume01'
        plan['operator_repair']={'schema':'bridge.geometry-registration-resume/1','failed_operation_id':job['operation_id'],
            'authorization_path':str(root/'geometry-registration-resume-authorization.json')}
        plan.pop('plan_sha256',None);plan['plan_sha256']=canonical_sha256(plan)
        request_id='operator_registration_resume01_'+job['operation_id'];operation='geo_'+hashlib.sha256((request_id+plan['plan_sha256']).encode()).hexdigest()[:24]
        request={'schema':'bridge.geometry-registration-request/1','preparation':preparation,'task_id':job['task_id'],
            'failed_operation_id':job['operation_id'],'failed_job':file_record(job_path),'registration_source':source,
            'new_plan':plan,'request_id':request_id,'new_operation_id':operation,'original_plan_sha256':job['plan']['plan_sha256']}
        request_record=stable(root/'geometry-registration-resume-request.json',request);authority_path=root/'geometry-registration-resume-authorization.json'
        if authority_path.exists():
            authority=file_record(authority_path);payload,_=route.validate(preparation,authority,native)
            if (payload['source']!=source or payload['request']!=request_record or payload['authority']['instruction']!=instruction
                    or payload['registration_runtime']['package_root']!=str(Path(registration_plugin).resolve())):
                raise ValueError('GEOMETRY_REGISTRATION_AUTHORITY_CHANGED')
        else:authority=route.create_authorization(preparation,Path(original_plugin).resolve(),ROOT.parent,Path(registration_plugin).resolve(),job_path,source,request_record,instruction)
        if (plan['plan_id'] in state['plans'] or operation in state['jobs'] or request_id in state['execution_requests']
                or plan['plan_id'] in state['plan_operations']):raise ValueError('GEOMETRY_REGISTRATION_ALREADY_REGISTERED')
        transaction={'schema':'bridge.geometry-registration-dispatch/1','state':'INTENT','preparation':preparation,'failed_job':file_record(job_path),
            'request':request_record,'authority':authority,'operation_id':operation,'created_at':time.time()}
        seal(native,intent,transaction,new=True);native.check();state['plans'][plan['plan_id']]=plan;session._write(state)
        accepted=session.execute(plan['plan_id'],request_id,_repair_authority=authority)
        if accepted.get('operation_id')!=operation:raise ValueError('GEOMETRY_REGISTRATION_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,intent,transaction)
        print(json.dumps({'source_operation_id':job['operation_id'],'operation_id':operation,'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--original-plugin',type=Path,required=True);parser.add_argument('--registration-plugin',type=Path,required=True)
    parser.add_argument('--instruction',required=True);args=parser.parse_args();resume(args.job,args.original_plugin,args.registration_plugin,args.instruction)
if __name__=='__main__':main()
