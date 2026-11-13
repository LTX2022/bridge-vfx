"""Plain-data preparation rules for one initially frozen official scope."""
from __future__ import annotations
import copy
from pathlib import Path
import shlex

from .official_karma_observation import file_record,checked_bytes,load_record
from .official_karma_inputs import derivation_rule
from .official_karma_native import SETTINGS
from dcc_task_runtime.render_profiles import OFFICIAL,SOURCE_HIP_SHA256


def case_spec(root,hosts,source_preparation,static_review,source_root,ocio_config):
    root=Path(root)
    source=load_record(source_preparation);review=load_record(static_review)
    contract=source['source_contract']; checked_bytes(contract)
    original=Path(source['source_root'])
    files=[file_record(original/row['path']) for row in source['resource_inventory']]
    if (source.get('state')!='SOURCE_VERIFIED_RUNTIME_NOT_PREPARED'
            or review.get('state')!='REVIEWED_NO_UNEXPLAINED_EXECUTABLE_SOURCE'
            or review.get('source_contract')!=contract or review.get('source_files')!=files):
        raise ValueError('OFFICIAL_PREPARATION_STATIC_REVIEW_REQUIRED')
    vendor=review.get('vendor_sources')
    if type(vendor) is not list or not vendor:
        raise ValueError('OFFICIAL_PREPARATION_VENDOR_REVIEW_REQUIRED')
    for record in vendor:checked_bytes(record)
    originals=files
    files=[dict(row,path=str(root/'official-inputs'/Path(row['path']).relative_to(original))) for row in originals]
    source_hip=next(row for row in files if row['sha256']==SOURCE_HIP_SHA256)
    import sys
    sys.path.insert(0,str(Path(source_root)/'tools'))
    from prepare_workbuddy_graph import snapshot_python_sources
    snapshot=root/'project/control/snapshot'
    records=[(path,file_record(path)) for path in snapshot_python_sources()]
    freeze={str(snapshot/path.relative_to(source_root)):record['sha256'] for path,record in records}
    from .official_karma_display import policy
    display=policy(hosts['hython']['path'],ocio_config)
    freeze.update({record['path']:record['sha256'] for record in (*vendor,*display['module_files'])})
    worker=Path('packages/houdini-bridge/src/houdini_bridge/official_karma_worker.py')
    observer=dict(file_record(Path(source_root)/worker),path=str(snapshot/worker))
    paths={'official_hip':str(root/'official/official-cpu.hip'),
        'official_usd':str(root/'official/official.usd'),'official_image':str(root/'official/official.0001.exr'),
        'warm_supervisor':str(root/'supervisor-official-open-save'),
        'cold_supervisor':str(root/'supervisor-official-cold-export'),
        'official_husk_supervisor':str(root/'supervisor-official-husk')}
    commands=case_commands(root,hosts,observer,paths)
    return {'profile':OFFICIAL,'observer':observer,'source_contract':contract,'source_hip':source_hip,
        'source_files':files,'original_files':originals,'static_review':static_review,'source_preparation':source_preparation,
        'source_freeze':freeze,'paths':paths,'commands':commands,'derivation':derivation_rule(root),'display_policy':display}


def relocate_case(value,source_root,target_root):
    """Review-time relocation only; the activated scope stays immutable after use."""
    source_root,target_root=Path(source_root),Path(target_root)
    def path(raw):
        p=Path(raw)
        return str(target_root/p.relative_to(source_root)) if p.is_relative_to(source_root) else raw
    result=copy.deepcopy(value)
    result['observer']['path']=path(result['observer']['path'])
    result['source_hip']['path']=path(result['source_hip']['path'])
    for record in result['source_files']:record['path']=path(record['path'])
    result['source_freeze']={path(p):digest for p,digest in result['source_freeze'].items()}
    result['paths']={key:path(p) for key,p in result['paths'].items()}
    result['derivation']=derivation_rule(target_root)
    # Recreate argv from exact declared fields, including the quoted husk script.
    for role,argv in result['commands'].items():
        result['commands'][role]=[path(v) if v.startswith('/') else v for v in argv]
        if role=='official-husk':
            adapter=target_root/'project/control/snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'
            result['commands'][role][2]=shlex.quote(str(adapter))
    return result


def case_commands(root,hosts,observer,paths):
    snapshot=Path(root)/'project/control/snapshot'
    adapter=snapshot/'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'
    commands={role:[hosts['hython']['path'],observer['path'],'--scope',str(root/'scope.json'),'--phase',role]
        for role in ('official-open-save','official-cold-export')}
    commands['official-husk']=[hosts['husk']['path'],'--prerender-script',shlex.quote(str(adapter)),
        '--renderer','BRAY_HdKarma','--settings',SETTINGS,'--lock-random','1',
        '--frame','1','--frame-count','1',paths['official_usd']]
    return commands
