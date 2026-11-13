#!/usr/bin/env python3
"""048已完成047结果的纯metadata准备/发布；无Native、Stage或新请求入口。"""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))
from dcc_task_runtime.execution_lock import execution_lock
from houdini_bridge.official_karma_observation import file_record
from vfx_pipeline.geometry_registration_resume import _context
from vfx_pipeline import geometry_metadata_completion as completion

def _installed(expected=None):
    version=json.loads((ROOT.parent/'plugin.json').read_text()).get('version')
    if version not in ('0.4.8','0.4.9') or expected is not None and version!=expected:raise ValueError('GEOMETRY_METADATA_INSTALLED_RUNTIME_REQUIRED')
    return version

def prepare(job_path,original_plugin,execution_plugin,diagnosis,cache_audit,metadata_stop):
    """准备证据和048签权；canonical/accepted/GeometryState均保持。"""
    _installed('0.4.8');job_record=file_record(Path(job_path).resolve());job=completion._read(job_record);preparation=job['preparation'];_,native=_context(preparation)
    with execution_lock(native.root,'geometry-session'):
        auth_path=native.root/completion._AUTH;source_path=native.root/completion._SOURCE_NAME
        if auth_path.exists():
            authority=file_record(auth_path);p,s,*_=completion.validate(preparation,authority,native)
            if s['job']!=job_record or s['diagnosis']!=file_record(diagnosis) or s['cache_audit']!=file_record(cache_audit) or s['metadata_stop']!=file_record(metadata_stop) or p['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve()):completion._fail()
        else:
            if source_path.exists():source_record=file_record(source_path);source=completion._read(source_record)
            else:
                source=completion.inspect_source(preparation,Path(original_plugin).resolve(),file_record(diagnosis),file_record(cache_audit),file_record(metadata_stop))
                if source['job']!=job_record:completion._fail()
                transition=source['binding_transition']
                for key,text in (('before_snapshot','before_text'),('after_snapshot','after_text')):
                    record=transition[key];path=Path(record['path'])
                    if path.exists():
                        if completion._record(path)!=record:completion._fail()
                    elif completion._raw(path,transition[text].encode())!=record:completion._fail()
                source_record=completion._write(source_path,source)
            if source['job']!=job_record or source['diagnosis']!=file_record(diagnosis) or source['cache_audit']!=file_record(cache_audit) or source['metadata_stop']!=file_record(metadata_stop):completion._fail()
            authority=completion.create_authorization(preparation,source_record,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve())
        value={'state':'PREPARED_METADATA_ONLY','operation_id':job['operation_id'],'authority':authority,'source':completion._read(authority)['payload']['source'],'native_dispatch_attempted':False,'canonical_published':False,'accepted_sealed':False}
        print(json.dumps(value,ensure_ascii=False),flush=True);return value

def prepare_runtime_successor(job_path,original_plugin,execution_plugin,interrupted_inspect):
    """049只签本次代码差异；原048数据证书与17票一律复用。"""
    from vfx_pipeline import geometry_metadata_runtime_successor as successor
    _installed('0.4.9');job_record=file_record(Path(job_path).resolve());job=completion._read(job_record);preparation=job['preparation'];root=Path(preparation['path']).parent
    with execution_lock(root,'geometry-session'):
        path=root/successor._AUTH
        if path.exists():
            authority=file_record(path);_,native=_context(preparation);p,s=successor.resolve(preparation,authority,native)
            if s['job']!=job_record or s['formal048']!=str(Path(original_plugin).resolve()) or s['interrupted_inspect']!=file_record(interrupted_inspect) or p['consumer_runtime']['package_root']!=str(Path(execution_plugin).resolve()):successor._fail()
        else:
            source_path=root/successor._SOURCE_NAME
            if source_path.exists():source_record=file_record(source_path);source=completion._read(source_record)
            else:
                source=successor.inspect_source(preparation,Path(original_plugin).resolve(),file_record(interrupted_inspect))
                if source['job']!=job_record:successor._fail()
                source_record=completion._write(source_path,source)
            if source['job']!=job_record or source['interrupted_inspect']!=file_record(interrupted_inspect):successor._fail()
            authority=successor.create_authorization(preparation,source_record,Path(original_plugin).resolve(),ROOT.parent,Path(execution_plugin).resolve())
        result={'state':'PREPARED_METADATA_RUNTIME_SUCCESSOR','operation_id':job['operation_id'],'authority':authority,'data_authority':completion._read(completion._read(authority)['payload']['source'])['data_authority'],'native_dispatch_attempted':False,'canonical_published':False,'accepted_sealed':False}
        print(json.dumps(result,ensure_ascii=False),flush=True);return result


def publish(job_path):
    version=_installed();job_record=file_record(Path(job_path).resolve());job=completion._read(job_record);root=Path(job['preparation']['path']).parent
    if version=='0.4.9':
        from vfx_pipeline.geometry_metadata_runtime_successor import _AUTH
    else:_AUTH=completion._AUTH
    authority=file_record(root/_AUTH);value=completion.publish(job['preparation'],authority);print(json.dumps(value,ensure_ascii=False),flush=True);return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);m=parser.add_mutually_exclusive_group(required=True);m.add_argument('--prepare-only',action='store_true');m.add_argument('--publish',action='store_true');m.add_argument('--prepare-runtime-successor',action='store_true');parser.add_argument('--job',type=Path,required=True)
    for name in ('original-plugin','execution-plugin','diagnosis','cache-audit','metadata-stop','interrupted-inspect'):parser.add_argument('--'+name,type=Path)
    a=parser.parse_args()
    if a.prepare_runtime_successor:
        if any(x is None for x in (a.original_plugin,a.execution_plugin,a.interrupted_inspect)):parser.error('runtime successor requires original/execution packages and interrupted inspect')
        prepare_runtime_successor(a.job,a.original_plugin,a.execution_plugin,a.interrupted_inspect)
    elif a.prepare_only:
        if any(x is None for x in (a.original_plugin,a.execution_plugin,a.diagnosis,a.cache_audit,a.metadata_stop)):parser.error('prepare-only requires original/execution packages and exact diagnosis/audit/stop records')
        prepare(a.job,a.original_plugin,a.execution_plugin,a.diagnosis,a.cache_audit,a.metadata_stop)
    else:publish(a.job)
if __name__=='__main__':main()
