#!/usr/bin/env python3
"""迁移未派发的041保存尾段到042；复用同plan/request/op，不改预算或旧INTENT。"""
from pathlib import Path
import argparse,hashlib,hmac,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.platform_support import atomic_write
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_job import _object,_write
from vfx_pipeline.geometry_session import GeometrySession


def stable(path,value):
    path=Path(path)
    if path.exists():
        if _object(path)!=value:raise ValueError('GEOMETRY_SAVE_RUNTIME_SOURCE_CHANGED')
        return file_record(path)
    return _write(path,value,new=True)


def seal(native,path,payload,*,new=False):
    path=Path(path)
    if new and path.exists():raise ValueError('GEOMETRY_SAVE_RUNTIME_QUERY_ORIGINAL_REQUIRED')
    key=hmac.new(native._key(),b'bridge.geometry-nuke-save-runtime-dispatch/1\x00',hashlib.sha256).digest()
    value={'payload':payload,'signature':hmac.new(key,native._canonical(payload),hashlib.sha256).hexdigest()}
    atomic_write(path,native._canonical(value)+b'\n',owned_root=path.parent)


def migrate(preparation_path,metadata_stop_path,original_plugin,execution_plugin):
    """只接已证明NO_JOB的原041意图；任何未知派发都保留同operation供查询。"""
    from vfx_pipeline import geometry_nuke_save_runtime_successor as route
    preparation=file_record(Path(preparation_path).resolve());session=GeometrySession(preparation);native=NativeScope(session.prep['scope']);root=native.root
    if json.loads((ROOT.parent/'plugin.json').read_text()).get('version')!='0.4.2':raise ValueError('GEOMETRY_SAVE_RUNTIME_INSTALLED042_REQUIRED')
    dispatch=root/'geometry-nuke-save-runtime-successor-dispatch.json'
    with execution_lock(root,'geometry-session'):
        if dispatch.exists():raise ValueError('GEOMETRY_SAVE_RUNTIME_QUERY_ORIGINAL_REQUIRED')
        source_value=route.inspect_source(preparation,file_record(Path(metadata_stop_path).resolve()),Path(original_plugin).resolve())
        source=stable(root/'geometry-nuke-save-runtime-successor-source.json',source_value)
        authority_path=root/route._AUTH
        if authority_path.exists():
            authority=file_record(authority_path);proof=_object(authority_path)['payload']
            if (proof.get('source')!=source or proof.get('original_plugin_root')!=str(Path(original_plugin).resolve())
                    or proof.get('active_plugin_root')!=str(ROOT.parent)
                    or proof.get('consumer_runtime',{}).get('package_root')!=str(Path(execution_plugin).resolve())):
                raise ValueError('GEOMETRY_SAVE_RUNTIME_AUTHORITY_CHANGED')
            route.validate(preparation,authority,native)
        else:authority=route.create_authorization(preparation,source,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve())
        # 本调用inspect已认证此固定request；不再次重读整条原生来源链。
        if file_record(source_value['request']['path'])!=source_value['request']:raise ValueError('GEOMETRY_SAVE_RUNTIME_REQUEST_CHANGED')
        request=_object(source_value['request']['path']);plan=request['new_plan'];operation=request['new_operation_id']
        state=session._read()
        if (state['plans'].get(plan['plan_id'])!=plan or operation in state['jobs'] or request['request_id'] in state['execution_requests']
                or plan['plan_id'] in state['plan_operations'] or (root/'jobs'/operation).exists()):
            raise ValueError('GEOMETRY_SAVE_RUNTIME_NO_JOB_REQUIRED')
        transaction={'schema':'bridge.geometry-nuke-save-runtime-dispatch/1','state':'INTENT','preparation':preparation,
            'source':source,'authority':authority,'predecessor_dispatch':source_value['dispatch'],'operation_id':operation,
            'request_id':request['request_id'],'plan_sha256':plan['plan_sha256'],'created_at':time.time()}
        seal(native,dispatch,transaction,new=True)
        # 原17次许可已激活；此工具不调用任何authorize/clear或登记API。
        accepted=session.execute(plan['plan_id'],request['request_id'],_repair_authority=authority)
        if accepted.get('operation_id')!=operation:raise ValueError('GEOMETRY_SAVE_RUNTIME_OPERATION_CHANGED')
        transaction.update(state='ACCEPTED',accepted=accepted,accepted_at=time.time());seal(native,dispatch,transaction)
        print(json.dumps({'operation_id':operation,'same_operation_reused':True,'accepted':accepted},ensure_ascii=False),flush=True)
        return accepted


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);p.add_argument('--metadata-stop',type=Path,required=True)
    p.add_argument('--original-plugin',type=Path,required=True);p.add_argument('--execution-plugin',type=Path,required=True);a=p.parse_args()
    migrate(a.preparation,a.metadata_stop,a.original_plugin,a.execution_plugin)
if __name__=='__main__':main()
