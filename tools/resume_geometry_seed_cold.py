#!/usr/bin/env python3
"""复用R2 seed完成最后一票NR17；同17上限、无NH保存、不重跑上游。"""
from pathlib import Path
import argparse,copy,hashlib,hmac,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.platform_support import atomic_write
from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_session import GeometrySession

def stable(path,value):
    path=Path(path)
    if path.exists():
        if _object(path)!=value:raise ValueError('GEOMETRY_SEED_COLD_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)

def seal(native,path,payload,*,new=False):
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_SEED_COLD_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-seed-cold-dispatch/1\x00',hashlib.sha256).digest();value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,native._canonical(value)+b'\n',owned_root=path.parent)

def prepare(job_path,original_plugin,execution_plugin):
    from dcc_task_runtime import geometry_seed_cold_recovery as budget
    from vfx_pipeline import geometry_seed_cold_resume as route
    path=Path(job_path).resolve();old=_object(path);preparation=old['preparation'];session=GeometrySession(preparation);native=NativeScope(session.prep['scope']);root=native.root
    if json.loads((ROOT.parent/'plugin.json').read_text()).get('version')!='0.4.4' or path!=root/'jobs'/old['operation_id']/'job.json':raise ValueError('GEOMETRY_SEED_COLD_INSTALLED044_REQUIRED')
    dispatch=root/'geometry-seed-cold-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if dispatch.exists():raise ValueError('GEOMETRY_SEED_COLD_QUERY_ORIGINAL_REQUIRED')
        if session.query(old['operation_id']).get('state')!='FAILED':raise ValueError('GEOMETRY_SEED_COLD_FAILED_SOURCE_REQUIRED')
        state=session._read()
        if state['revision']!=1 or len(state['completed'])!=1 or any(j['state'] not in ('COMPLETE','FAILED','CANCELLED') for j in state['jobs'].values()):raise ValueError('GEOMETRY_SEED_COLD_SESSION_REQUIRED')
        existing=root/route._AUTH
        if existing.exists():
            authority=file_record(existing);payload,source_value=route.validate(preparation,authority,native);request_value=_object(payload['request']['path'])
            if (source_value['failure_job']!=file_record(path) or payload['original_plugin_root']!=str(Path(original_plugin).resolve())
                    or payload['active_plugin_root']!=str(ROOT.parent) or payload['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve())
                    or request_value['new_operation_id'] in state['jobs'] or (root/'jobs'/request_value['new_operation_id']).exists()):raise ValueError('GEOMETRY_SEED_COLD_PREPARED_BINDING_CHANGED')
            final=route.finalize_authorized_nk(preparation,authority);context=route.prepare_cold_context(preparation,authority)
            return {'state':'PREPARED_READ_ONLY','operation_id':request_value['new_operation_id'],'authority':authority,'budget_authority':source_value['budget_authority'],'source':payload['source'],'finalization':final,'cold_context':context,'native_dispatch_attempted':False}
        low_source=stable(root/'geometry-seed-cold-budget-source.json',budget.build_source(preparation,path,file_record(path.parent/'late-stop-observation.json')))
        permit_path=root/'geometry-seed-cold-recovery-authorization.json'
        if permit_path.exists():
            permit=file_record(permit_path);payload,_,closed=budget.validate(native,permit)
            if payload['source']!=low_source or native._read()!=closed:raise ValueError('GEOMETRY_SEED_COLD_BUDGET_CHANGED')
        else:permit=budget.create_authorization(preparation,low_source)
        source_path=root/'geometry-seed-cold-resume-source.json'
        if source_path.exists():
            source=route.reuse_partial_source(preparation,path,permit,Path(original_plugin).resolve(),file_record(root/'geometry-seed-cold-resume-request.json'))
        else:
            source=stable(source_path,route.inspect_source(preparation,path,permit,Path(original_plugin).resolve()))
        plan=copy.deepcopy(old['plan']);plan['plan_id']+='_seed_cold_resume01';plan['operator_repair']={'schema':'bridge.geometry-seed-cold-resume/1','failed_operation_id':old['operation_id'],'authorization_path':str(root/route._AUTH)};plan['plan_sha256']=canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'});rid='operator_seed_cold_resume01_'+old['operation_id'];op='geo_'+hashlib.sha256((rid+plan['plan_sha256']).encode()).hexdigest()[:24]
        request=stable(root/'geometry-seed-cold-resume-request.json',{'schema':'bridge.geometry-seed-cold-request/1','preparation':preparation,'task_id':old['task_id'],'failed_job':file_record(path),'source':source,'new_plan':plan,'request_id':rid,'new_operation_id':op})
        authority_path=root/route._AUTH
        if authority_path.exists():
            authority=file_record(authority_path);payload,_=route.validate(preparation,authority,native)
            if payload['source']!=source or payload['request']!=request or payload['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve()):raise ValueError('GEOMETRY_SEED_COLD_AUTHORITY_CHANGED')
        else:authority=route.create_authorization(preparation,source,request,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve())
        if plan['plan_id'] in state['plans'] or op in state['jobs'] or rid in state['execution_requests'] or plan['plan_id'] in state['plan_operations']:raise ValueError('GEOMETRY_SEED_COLD_ALREADY_REGISTERED')
        final=route.finalize_authorized_nk(preparation,authority);context=route.prepare_cold_context(preparation,authority)
        result={'state':'PREPARED_READ_ONLY','operation_id':op,'authority':authority,'budget_authority':permit,'source':source,'finalization':final,'cold_context':context,'native_dispatch_attempted':False}
        print(json.dumps(result,ensure_ascii=False),flush=True);return result


def dispatch(job_path):
    from dcc_task_runtime import geometry_seed_cold_recovery as budget
    from vfx_pipeline import geometry_seed_cold_resume as route
    path=Path(job_path).resolve();old=_object(path);preparation=old['preparation'];session=GeometrySession(preparation);native=NativeScope(session.prep['scope']);root=native.root
    if json.loads((ROOT.parent/'plugin.json').read_text()).get('version')!='0.4.4':raise ValueError('GEOMETRY_SEED_COLD_INSTALLED044_REQUIRED')
    dispatch_path=root/'geometry-seed-cold-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if dispatch_path.exists():raise ValueError('GEOMETRY_SEED_COLD_QUERY_ORIGINAL_REQUIRED')
        authority=file_record(root/route._AUTH);payload,source_value=route.validate(preparation,authority,native);request=_object(payload['request']['path'])
        permit=source_value['budget_authority'];_,_,closed=budget.validate(native,permit);state=session._read();plan=request['new_plan'];rid=request['request_id'];op=request['new_operation_id']
        if (source_value['failure_job']!=file_record(path) or native._read()!=closed or state['revision']!=1 or len(state['completed'])!=1
                or any(j['state'] not in ('COMPLETE','FAILED','CANCELLED') for j in state['jobs'].values())
                or plan['plan_id'] in state['plans'] or op in state['jobs'] or rid in state['execution_requests'] or plan['plan_id'] in state['plan_operations']
                or (root/'jobs'/op).exists()):raise ValueError('GEOMETRY_SEED_COLD_DISPATCH_STATE_CHANGED')
        route._verify_finalization(preparation,authority,source_value['nk_binding'])
        context=Path(source_value['producer']['control'])/'cold-context.json'
        if not context.is_file():raise ValueError('GEOMETRY_SEED_COLD_PREFLIGHT_REQUIRED')
        route.prepare_cold_context(preparation,authority)
        transaction={'schema':'bridge.geometry-seed-cold-dispatch/1','state':'INTENT','preparation':preparation,'failure_job':file_record(path),'source':payload['source'],'request':payload['request'],'authority':authority,'budget_authority':permit,'operation_id':op,'created_at':time.time()};seal(native,dispatch_path,transaction,new=True)
        native.authorize_geometry_seed_cold_recovery(permit);native.check();state['plans'][plan['plan_id']]=plan;session._write(state)
        accepted=session.execute(plan['plan_id'],rid,_repair_authority=authority)
        if accepted.get('operation_id')!=op:raise ValueError('GEOMETRY_SEED_COLD_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,dispatch_path,transaction)
        print(json.dumps({'operation_id':op,'last_remaining_nr_only':True,'accepted':accepted},ensure_ascii=False),flush=True);return accepted


def main():
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--dispatch',action='store_true')
    p.add_argument('--job',type=Path,required=True);p.add_argument('--original-plugin',type=Path);p.add_argument('--execution-plugin',type=Path);a=p.parse_args()
    if a.prepare_only:
        if a.original_plugin is None or a.execution_plugin is None:p.error('--prepare-only requires --original-plugin and --execution-plugin')
        prepare(a.job,a.original_plugin,a.execution_plugin)
    else:dispatch(a.job)
if __name__=='__main__':main()
