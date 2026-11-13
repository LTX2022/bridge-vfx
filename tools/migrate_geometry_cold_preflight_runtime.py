#!/usr/bin/env python3
"""045后继切换046准入前验源消费者；沿用同操作、同低许可和原044定稿证明。"""
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

def prepare(job_path,original_plugin,execution_plugin,readonly_failure,path_diagnostic,coverage_groups,coverage_evidence):
    from vfx_pipeline import geometry_seed_cold_resume as route
    from vfx_pipeline import geometry_cold_preflight_runtime as successor
    path=Path(job_path).resolve();old=_object(path);preparation=old['preparation'];session=GeometrySession(preparation);native=NativeScope(session.prep['scope']);root=native.root
    if json.loads((ROOT.parent/'plugin.json').read_text()).get('version')!='0.4.6' or path!=root/'jobs'/old['operation_id']/'job.json':raise ValueError('GEOMETRY_SEED_COLD_INSTALLED046_REQUIRED')
    with execution_lock(root,'geometry-session'):
        if (root/'geometry-seed-cold-resume-dispatch.json').exists():raise ValueError('GEOMETRY_SEED_COLD_QUERY_ORIGINAL_REQUIRED')
        existing=root/successor._AUTH
        if existing.exists():
            authority=file_record(existing);payload,source=successor.validate(preparation,authority,native);proof=_object(existing)['payload'];request=_object(payload['request']['path'])
            if proof['original_plugin_root']!=str(Path(original_plugin).resolve()) or proof['active_plugin_root']!=str(ROOT.parent) or payload['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve()) or source['failure_job']!=file_record(path):raise ValueError('GEOMETRY_SEED_COLD_RUNTIME_CHANGED')
        else:
            source_path=root/successor._SOURCE_NAME
            if source_path.exists():source_record=file_record(source_path)
            else:source_record=stable(source_path,successor.inspect_source(preparation,Path(original_plugin).resolve(),file_record(readonly_failure),file_record(path_diagnostic),file_record(coverage_groups),file_record(coverage_evidence)))
            source_value=_object(source_record['path'])
            if source_value['evidence']!={'readonly_failure':file_record(readonly_failure),'path_diagnostic':file_record(path_diagnostic)}:raise ValueError('GEOMETRY_SEED_COLD_RUNTIME_EVIDENCE_CHANGED')
            authority=successor.create_authorization(preparation,source_record,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve())
            payload,source=successor.validate(preparation,authority,native);request=_object(payload['request']['path'])
        if source['failure_job']!=file_record(path):raise ValueError('GEOMETRY_SEED_COLD_FAILED_SOURCE_CHANGED')
        _,_,closed=__import__('dcc_task_runtime.geometry_seed_cold_recovery',fromlist=['validate']).validate(native,source['budget_authority'])
        if native._read()!=closed or (root/'jobs'/request['new_operation_id']).exists():raise ValueError('GEOMETRY_SEED_COLD_PREPARED_BINDING_CHANGED')
        result={'state':'PREPARED_READ_ONLY','operation_id':request['new_operation_id'],'authority':authority,'finalization_authority':payload['finalization_authority'],'budget_authority':source['budget_authority'],'cold_context':file_record(Path(source['producer']['control'])/'cold-context.json'),'native_dispatch_attempted':False}
        print(json.dumps(result,ensure_ascii=False),flush=True);return result

def dispatch(job_path):
    from dcc_task_runtime import geometry_seed_cold_recovery as budget
    from vfx_pipeline import geometry_seed_cold_resume as route
    from vfx_pipeline import geometry_cold_preflight_runtime as successor
    path=Path(job_path).resolve();old=_object(path);preparation=old['preparation'];session=GeometrySession(preparation);native=NativeScope(session.prep['scope']);root=native.root
    if json.loads((ROOT.parent/'plugin.json').read_text()).get('version')!='0.4.6':raise ValueError('GEOMETRY_SEED_COLD_INSTALLED046_REQUIRED')
    dispatch_path=root/'geometry-seed-cold-resume-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if dispatch_path.exists():raise ValueError('GEOMETRY_SEED_COLD_QUERY_ORIGINAL_REQUIRED')
        authority=file_record(root/successor._AUTH);payload,source_value=route.validate(preparation,authority,native);request=_object(payload['request']['path'])
        permit=source_value['budget_authority'];_,_,closed=budget.validate(native,permit);state=session._read();plan=request['new_plan'];rid=request['request_id'];op=request['new_operation_id']
        if (source_value['failure_job']!=file_record(path) or native._read()!=closed or state['revision']!=1 or len(state['completed'])!=1
                or any(j['state'] not in ('COMPLETE','FAILED','CANCELLED') for j in state['jobs'].values())
                or plan['plan_id'] in state['plans'] or op in state['jobs'] or rid in state['execution_requests'] or plan['plan_id'] in state['plan_operations']
                or (root/'jobs'/op).exists()):raise ValueError('GEOMETRY_SEED_COLD_DISPATCH_STATE_CHANGED')
        route._verify_finalization(preparation,payload['finalization_authority'],source_value['nk_binding'])
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
    p.add_argument('--coverage-groups',type=Path);p.add_argument('--coverage-evidence',type=Path)
    p.add_argument('--job',type=Path,required=True);p.add_argument('--original-plugin',type=Path);p.add_argument('--execution-plugin',type=Path);p.add_argument('--readonly-failure',type=Path);p.add_argument('--path-diagnostic',type=Path);a=p.parse_args()
    if a.prepare_only:
        if any(value is None for value in (a.original_plugin,a.execution_plugin,a.readonly_failure,a.path_diagnostic,a.coverage_groups,a.coverage_evidence)):p.error('--prepare-only requires original/execution plugins and readonly/path evidence')
        prepare(a.job,a.original_plugin,a.execution_plugin,a.readonly_failure,a.path_diagnostic,a.coverage_groups,a.coverage_evidence)
    else:dispatch(a.job)
if __name__=='__main__':main()
