"""Owned H21 official open/save or cold/export entry; no standalone authority.

Native execution requires the initial reviewed scope, its complete source/file
freeze, exact admitted role, original supervisor intent and runtime image proof.
"""
from __future__ import annotations
import os
import time
if os.environ.get('BRIDGE_OWNED_WINDOW_MODE')=='1':
    try:
        _base=os.environ.get('BRIDGE_OWNED_SUPERVISOR_DIR','');_folder=os.environ.get('BRIDGE_OWNED_STARTUP_TRACE_DIR','')
        if not os.path.isabs(_base) or _folder!=_base+'/startup-trace' or os.path.realpath(_folder)!=_folder:raise ValueError('EARLY_TRACE_PATH')
        _raw=('{{"schema":"bridge.startup-stage/1","phase":"worker_minimal_python_entry","pid":{},"monotonic":{},"observed_at":{}}}'.format(os.getpid(),time.monotonic(),time.time())).encode()
        _target=_folder+'/worker_minimal_python_entry.json';_temporary=_folder+'/worker_minimal_python_entry.tmp'
        _fd=os.open(_temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            if os.write(_fd,_raw)!=len(_raw):raise OSError('EARLY_TRACE_SHORT_WRITE')
        finally:os.close(_fd)
        if os.path.lexists(_target):raise ValueError('EARLY_TRACE_EXISTS')
        os.replace(_temporary,_target)
    except BaseException:
        try:os.write(2,b'EARLY_WINDOW_CHECKPOINT_FAILED\n')
        except BaseException:pass
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

def _startup_checkpoint(name):
    raw=os.environ.get('BRIDGE_OWNED_STARTUP_TRACE_DIR')
    if not raw:return
    try:
        base=Path(os.environ.get('BRIDGE_OWNED_SUPERVISOR_DIR',''));folder=base/'startup-trace'
        if not base.is_absolute() or raw!=str(folder) or any(p.is_symlink() for p in (folder,*folder.parents)):
            raise ValueError('STARTUP_CHECKPOINT_DIRECTORY')
        value={'schema':'bridge.startup-stage/1','phase':'worker_'+name,'pid':os.getpid(),
            'monotonic':time.monotonic(),'observed_at':time.time()}
        target=folder/('worker_'+name+'.json');temporary=target.with_suffix('.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            data=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
            if os.write(fd,data)!=len(data):raise OSError('STARTUP_CHECKPOINT_SHORT_WRITE')
        finally:os.close(fd)
        if target.exists():raise ValueError('STARTUP_CHECKPOINT_ALREADY_EXISTS')
        os.replace(temporary,target)
    except BaseException:
        try:sys.stderr.write('STARTUP_WORKER_CHECKPOINT_FAILED\n')
        except BaseException:pass


_startup_checkpoint('python_entry')

_REPO = Path(__file__).resolve().parents[4]
for _package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(_REPO/'packages'/_package/'src'))
from dcc_task_runtime import owned_process
from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_RESOURCE_PROFILE
from houdini_bridge.official_karma import SOURCE_HIP_SHA256, canonical_sha256
from houdini_bridge.official_karma_native import (scalar_write,configure_output,capture_observation,
    configure_beauty,beauty_author_readback,BEAUTY_ADAPTER)
from houdini_bridge.official_karma_observation import checked_bytes, file_record, load_record, write_new
_startup_checkpoint('bridge_imports_complete')


def check_frozen_case(scope):
    from houdini_bridge.official_karma_observation import require_frozen_sources
    case = scope.scope.get('official_case')
    if not isinstance(case,dict):
        raise ValueError('OFFICIAL_FROZEN_CASE_REQUIRED')
    require_frozen_sources(case)
    for record in scope.scope.get('process_image_policy',{}).get('tools',{}).values():checked_bytes(record)
    for name in ('observer','source_contract','static_review'):
        checked_bytes(case[name])
    required = [Path(__file__).resolve(), Path(__file__).with_name('official_karma_native.py'),
                Path(__file__).with_name('official_karma_observation.py'),
                Path(__file__).with_name('official_karma.py'),
                _REPO/'packages/dcc-task-runtime/src/dcc_task_runtime/native_scope.py',
                _REPO/'packages/dcc-task-runtime/src/dcc_task_runtime/owned_process.py']
    freeze = case.get('source_freeze')
    if type(freeze) is not dict or any(str(p) not in freeze for p in required):
        raise ValueError('OFFICIAL_SOURCE_FREEZE_INCOMPLETE')
    for path,digest in freeze.items():
        if file_record(path)['sha256'] != digest:
            raise ValueError('OFFICIAL_FROZEN_SOURCE_CHANGED')
    if case['observer'] != file_record(Path(__file__).resolve()):
        raise ValueError('OFFICIAL_FROZEN_OBSERVER_CHANGED')
    for record in (*case['source_files'],*case['original_files']):
        checked_bytes(record)
    if (len(case['source_files'])!=len(case['original_files']) or any(
            source['bytes']!=copied['bytes'] or source['sha256']!=copied['sha256']
            or not Path(copied['path']).is_relative_to(scope.root/'official-inputs')
            for source,copied in zip(case['original_files'],case['source_files']))):
        raise ValueError('OFFICIAL_FROZEN_SOURCE_COPY_MISMATCH')
    for record in load_record(case['static_review']).get('vendor_sources',[]): checked_bytes(record)
    review = load_record(case['static_review'])
    if (review.get('state') != 'REVIEWED_NO_UNEXPLAINED_EXECUTABLE_SOURCE'
            or review.get('source_contract') != case['source_contract']
            or review.get('source_files') != case['original_files']):
        raise ValueError('OFFICIAL_STATIC_REVIEW_REQUIRED')
    for path in case['paths'].values():
        p=Path(path)
        if (not p.is_absolute() or p != p.resolve() or not p.is_relative_to(scope.root)
                or any(v.is_symlink() for v in (p,*p.parents))):
            raise ValueError('OFFICIAL_FROZEN_PATH_OUTSIDE_SCOPE')
    if case['source_hip']['sha256'] != SOURCE_HIP_SHA256:
        raise ValueError('OFFICIAL_FROZEN_SOURCE_HIP_REQUIRED')
    checked_bytes(case['source_hip'])
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_MODES
    if scope.scope.get('execution_mode') in OFFICIAL_IDENTITY_MODES:
        for record in scope.scope['writer_trace_tools'].values():checked_bytes(record)
        trace_source=_REPO/'packages/dcc-task-runtime/src/dcc_task_runtime/writer_tool_trace.py'
        if str(trace_source) not in freeze:raise ValueError('OFFICIAL_TRACE_SOURCE_NOT_FROZEN')
        from dcc_task_runtime.native_scope import OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE
        if scope.scope.get('execution_mode')==OFFICIAL_STARTUP_DIAGNOSTIC_MODE and str(_REPO/'packages/dcc-task-runtime/src/dcc_task_runtime/startup_trace.py') not in freeze:
            raise ValueError('OFFICIAL_STARTUP_TRACE_SOURCE_NOT_FROZEN')
    if scope.scope.get('execution_mode')=='official_writer_window_diagnostic_v1':
        for name in ('packages/dcc-task-runtime/src/dcc_task_runtime/window_trace.py','tools/qualify_native_stack.py'):
            if str(_REPO/name) not in freeze:raise ValueError('OFFICIAL_WINDOW_SOURCE_NOT_FROZEN')
        from houdini_bridge.official_karma_observation import validate_stack_qualification
        validate_stack_qualification(scope.scope['stack_qualification'],scope.scope['writer_trace_tools'])
    return case


def current_authority(scope_path, role):
    _startup_checkpoint("authority_entry")
    directory=Path(os.environ.get('BRIDGE_OWNED_SUPERVISOR_DIR',''))
    if (not directory.is_absolute() or directory != directory.resolve()
            or any(p.is_symlink() for p in (directory,*directory.parents))):
        raise ValueError('OFFICIAL_OWNED_SUPERVISOR_REQUIRED')
    intent=json.loads((directory/'intent.json').read_text())
    _startup_checkpoint('intent_read')
    binding=intent.get('resource_budget',{}).get('native_scope')
    scope=NativeScope(binding)
    _startup_checkpoint("scope_loaded")
    if (scope.path != Path(scope_path) or scope.resource_profile != OFFICIAL_RESOURCE_PROFILE
            or scope.scope.get('evidence_source') != 'real_host' or 'software_native_boundaries' in scope.scope
            or scope.scope.get('execution_authorized') is not True
            or scope.scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('OFFICIAL_EXPLICIT_LIVE_SCOPE_REQUIRED')
    _startup_checkpoint("frozen_validation_start")
    case=check_frozen_case(scope)
    _startup_checkpoint("frozen_validation_done")
    if intent.get('command') != case['commands'][role]:
        raise ValueError('OFFICIAL_FROZEN_COMMAND_REQUIRED')
    identity=intent['identity']
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_SURVEY_MODE,OFFICIAL_IDENTITY_ROLES
    admitted_role=role
    if scope.scope.get('execution_mode')==OFFICIAL_IDENTITY_SURVEY_MODE:
        admitted_role=intent.get('native_scope_ticket',{}).get('role')
        if (role!='official-open-save' or admitted_role not in OFFICIAL_IDENTITY_ROLES
                or identity.get('operation_id')!=admitted_role):
            raise ValueError('OFFICIAL_IDENTITY_SAMPLE_ROLE_REQUIRED')
    tickets=[t for t in scope.snapshot()['tickets'] if t['role']==admitted_role and t['directory']==str(directory)
             and t['identity']==identity and t['stopped_at'] is None]
    if len(tickets)!=1:
        raise ValueError('OFFICIAL_ADMITTED_ROLE_REQUIRED')
    _startup_checkpoint("admission_verified")
    _startup_checkpoint("runtime_ready_enter")
    owned_process.runtime_ready_and_wait()
    _startup_checkpoint("runtime_binding_received")
    start=owned_process.read_receipt(directory,'started',identity=identity)
    if not start or start['pid'] != os.getpid():
        raise ValueError('OFFICIAL_ORIGINAL_PROCESS_REQUIRED')
    return scope,case,directory,identity,start


def verify_fixed_state(hou,case):
    switch=hou.node('/stage/lights/switch3')
    rop=hou.node('/stage/lights/OUT_karma_lights')
    author=hou.node('/stage/lights/update_output_image_path')
    settings=hou.node('/stage/lights/karmarendersettings')
    if any(n is None for n in (switch,rop,author,settings)):
        raise ValueError('OFFICIAL_SELECTED_BRANCH_MISSING')
    if switch.parm('input').keyframes() or switch.parm('input').eval()!=1:
        raise ValueError('OFFICIAL_STATIC_DISKLIGHT_REQUIRED')
    if switch.input(1).path()!='/stage/lights/render_disklight':
        raise ValueError('OFFICIAL_DISKLIGHT_TOPOLOGY_MISMATCH')
    for node,fields in ((rop,{'runcommand':0,'renderer':'BRAY_HdKarma','soho_foreground':1,
                              'lopoutput':case['paths']['official_usd'],'loppath':BEAUTY_ADAPTER,
                              'enableoutputprocessor_savetodirectory':0,
                              'savetodirectory_directory':str(Path(case['paths']['official_usd']).parent)}),
                        (author,{'productName_control':'set','productName':case['paths']['official_image']}),
                        (settings,{'engine':'cpu','enablemblur':0,'denoiser':'off'})):
        for name,value in fields.items():
            parm=node.parm(name)
            if parm is None or parm.keyframes() or type(parm.eval()) is not type(value) or parm.eval()!=value:
                raise ValueError('OFFICIAL_FIXED_STATE_DRIFT:'+name)
    if tuple(settings.parmTuple('resolution').eval())!=(420,300):
        raise ValueError('OFFICIAL_RESOLUTION_DRIFT')
    if [(c.inputIndex(),c.inputNode().path(),c.outputIndex()) for c in rop.inputConnections()]!=[(0,BEAUTY_ADAPTER,0)]:
        raise ValueError('OFFICIAL_EXPORT_CONNECTION_DRIFT')
    beauty_author_readback(hou,hou.node(BEAUTY_ADAPTER),'/stage/lights/update_output_image_path')
    return rop


def export_only(rop,usd,image):
    """Use the native LOP's execute button, guarded by its export-only switch.

    H21 nodes.zip: lop/usdrender_rop redirects to out/usdrender; disabling
    runcommand still writes USD and does not run the external command. The LOP
    is not a hou.RopNode and does not have RopNode.render().
    """
    if (rop.type().name() != 'usdrender_rop' or rop.parm('runcommand').eval()!=0
            or rop.parm('runcommand').keyframes() or Path(usd).exists() or Path(image).exists()):
        raise ValueError('OFFICIAL_EXPORT_ONLY_REQUIRED')
    execute=rop.parm('execute')
    if (execute is None or execute.parmTemplate().type().name()!='Button'
            or execute.isLocked() or execute.isDisabled()):
        raise ValueError('OFFICIAL_NATIVE_EXPORT_BUTTON_REQUIRED')
    execute.pressButton()
    if Path(image).exists() or not Path(usd).is_file() or rop.parm('runcommand').eval()!=0:
        raise ValueError('OFFICIAL_EXPORT_ONLY_BEHAVIOUR_MISMATCH')


def run(scope_path,role):
    if role not in ('official-open-save','official-cold-export'):
        raise ValueError('OFFICIAL_WORKER_ROLE_INVALID')
    scope,case,directory,identity,start=current_authority(scope_path,role)
    from dcc_task_runtime.native_scope import OFFICIAL_IDENTITY_MODES
    if scope.scope.get('execution_mode') in OFFICIAL_IDENTITY_MODES:
        if role!='official-open-save':raise ValueError('OFFICIAL_IDENTITY_ROLE_REQUIRED')
        from dcc_task_runtime.native_scope import OFFICIAL_STARTUP_DIAGNOSTIC_MODE,OFFICIAL_WINDOW_DIAGNOSTIC_MODE
        startup=scope.scope.get('execution_mode')==OFFICIAL_STARTUP_DIAGNOSTIC_MODE
        trace=start.get('writer_tool_trace')
        if not startup and (not isinstance(trace,dict) or trace.get('cleanup_complete') is not True or not trace.get('record')):
            raise ValueError('OFFICIAL_IDENTITY_TRACE_REQUIRED')
        if not startup:checked_bytes(trace['record'])
        if any(Path(case['paths'][key]).exists() for key in ('official_hip','official_usd','official_image')):
            raise ValueError('OFFICIAL_IDENTITY_BUSINESS_OUTPUT_FORBIDDEN')
        result={'schema':owned_process.SCHEMA,'event':'official-identity-diagnostic','identity':identity,
            'scope_binding':scope.binding,'started_sha256':canonical_sha256(start),'captured_pid':os.getpid(),
            'writer_tool_trace':trace,'acceptance':'IDENTITY_DIAGNOSTIC_ONLY','hip_business':'NOT_RUN'}
        _startup_checkpoint("diagnostic_exit")
        owned_process._signed_write(directory,result)
        return result
    try:
        result=_run_owned(scope,case,directory,identity,start,role)
        from dcc_task_runtime.native_scope import OFFICIAL_DIAGNOSTIC_MODE
        if scope.scope.get('execution_mode')==OFFICIAL_DIAGNOSTIC_MODE:
            _record_diagnostic(scope,case,directory,identity,start,role,None)
        return result
    except Exception as error:
        _record_diagnostic(scope,case,directory,identity,start,role,error)
        raise


def _record_diagnostic(scope,case,directory,identity,start,role,error):
    # This receipt records failure facts only and cannot satisfy read_sealed.
    try:
        import hou
        import traceback
        from houdini_bridge.official_karma_native import cached_node_diagnostics, validate_ramp_failure_context
        diagnostic=cached_node_diagnostics(hou)
        context=getattr(error,'official_ramp_context',None)
        if context is not None:
            diagnostic['ramp_failure']=validate_ramp_failure_context(context)
        diagnostic.update(role=role,pid=os.getpid(),identity=identity,scope_binding=scope.binding,
            started_sha256=canonical_sha256(start),observer=case['observer'],source_contract=case['source_contract'],
            exception=None if error is None else {'type':type(error).__name__,'message':str(error)[:8192],
                'traceback':''.join(traceback.format_exception(type(error),error,error.__traceback__))[-12000:]})
        hip=Path(case['paths']['official_hip'])
        diagnostic['saved_hip']=file_record(hip) if hip.exists() else None
        record=write_new(directory/'native-diagnostic-details.json',diagnostic)
        payload={'schema':owned_process.SCHEMA,'event':'official-diagnostic','identity':identity,
            'scope_binding':scope.binding,'started_sha256':canonical_sha256(start),'captured_pid':os.getpid(),
            'role':role,'observer':case['observer'],'source_contract':case['source_contract'],
            'diagnostic':record,'diagnostics_incomplete':diagnostic['diagnostics_incomplete'],
            'evidence_source':'real_host','acceptance':'FAILED_NOT_ACCEPTED' if error is not None else 'DIAGNOSTIC_ONLY_NOT_ACCEPTED'}
        if owned_process.read_receipt(directory,payload['event'],identity=identity) is not None:
            raise ValueError('OFFICIAL_DIAGNOSTIC_ORIGINAL_EXISTS')
        owned_process._signed_write(directory,payload)
        print(json.dumps({'state':'FAILED_NOT_ACCEPTED','diagnostic':record,
            'diagnostics_incomplete':diagnostic['diagnostics_incomplete']}),file=sys.stderr,flush=True)
    except Exception as diagnostic_error:
        print('OFFICIAL_DIAGNOSTICS_INCOMPLETE:'+type(diagnostic_error).__name__+':'+str(diagnostic_error)[:2048],
              file=sys.stderr,flush=True)


def _run_owned(scope,case,directory,identity,start,role):
    import hou
    from houdini_bridge.official_karma_native import VERSION
    if hou.applicationVersionString()!=VERSION:
        raise ValueError('OFFICIAL_NATIVE_VERSION_MISMATCH')
    hip=Path(case['paths']['official_hip'])
    usd=Path(case['paths']['official_usd'])
    image=Path(case['paths']['official_image'])
    if usd.exists() or image.exists():
        raise ValueError('OFFICIAL_FRESH_EXPORT_AND_IMAGE_REQUIRED')
    if role=='official-open-save':
        if hip.exists():
            raise ValueError('OFFICIAL_FRESH_HIP_REQUIRED')
        hou.hipFile.load(case['source_hip']['path'],suppress_save_prompt=True,ignore_load_warnings=False)
        hou.setFrame(1)
        switch=hou.node('/stage/lights/switch3')
        settings=hou.node('/stage/lights/karmarendersettings')
        rop=hou.node('/stage/lights/OUT_karma_lights')
        author=hou.node('/stage/lights/update_output_image_path')
        scalar_write(switch,'input',1)
        for node,fields in ((settings,{'engine':'cpu','enablemblur':0,'denoiser':'off'}),
                           (author,{'productName_control':'set','productName':str(image)}),
                           (rop,{'renderer':'BRAY_HdKarma','runcommand':0,'soho_foreground':1,
                                  'lopoutput':str(usd),'enableoutputprocessor_savetodirectory':0,
                                  'savetodirectory_directory':str(usd.parent),'husk_tpostframe':0})):
            for name,value in fields.items(): scalar_write(node,name,value)
        # Keep the named render command inert: runcommand is read back off.
        if rop.parm('rendercommand').eval()!='husk':
            raise ValueError('OFFICIAL_RENDER_COMMAND_UNEXPLAINED')
        configure_output(hou,author)
        if hou.node(BEAUTY_ADAPTER) is not None:
            raise ValueError('OFFICIAL_FRESH_BEAUTY_ADAPTER_REQUIRED')
        adapter=author.parent().createNode('editproperties',node_name=BEAUTY_ADAPTER.rsplit('/',1)[1])
        if adapter.path()!=BEAUTY_ADAPTER:raise ValueError('OFFICIAL_BEAUTY_ADAPTER_PATH_MISMATCH')
        adapter.setInput(0,author)
        configure_beauty(hou,adapter)
        rop.setInput(0,adapter)
        scalar_write(rop,'loppath',BEAUTY_ADAPTER)
        verify_fixed_state(hou,case)
        hip.parent.mkdir(parents=True,exist_ok=True)
        hou.hipFile.save(file_name=str(hip),save_to_recent_files=False)
        if Path(hou.hipFile.path())!=hip:
            raise ValueError('OFFICIAL_SAVED_HIP_PATH_MISMATCH')
    else:
        warm_dir=Path(case['paths']['warm_supervisor'])
        warm_intent=json.loads((warm_dir/'intent.json').read_text())
        warm=owned_process.read_receipt(warm_dir,'official-observation',identity=warm_intent['identity'])
        warm_stop=owned_process.read_receipt(warm_dir,'stopped',identity=warm_intent['identity'])
        if not warm or not warm_stop or owned_process.execution_returncode(warm_stop)!=0:
            raise ValueError('OFFICIAL_WARM_ORIGINAL_STOP_REQUIRED')
        checked_bytes(warm['hip'])
        hou.hipFile.load(str(hip),suppress_save_prompt=True,ignore_load_warnings=False)
        hou.setFrame(1)
    rop=verify_fixed_state(hou,case)
    contract=load_record(case['source_contract'])
    observation=capture_observation(hou,contract,output=str(image),scope_sha256=scope.binding['sha256'],
        source_contract_sha256=case['source_contract']['sha256'],
        allowed_resource_roots=[scope.root,Path(scope.scope['hosts']['hython']['path']).parents[1]])
    result={'schema':owned_process.SCHEMA,'event':'official-observation','identity':identity,
        'scope_binding':scope.binding,'observer':case['observer'],'source_contract':case['source_contract'],
        'role':role,'captured_pid':os.getpid(),'started_sha256':canonical_sha256(start),
        'hip':file_record(hip),'observation':write_new(directory/'observation.json',observation),
        'evidence_source':'real_host'}
    if role=='official-cold-export':
        warm_observation=load_record(warm['observation'])
        if observation!=warm_observation:
            raise ValueError('OFFICIAL_COLD_OBSERVATION_MISMATCH')
        # The reviewed original ROP remains the sole USD export path.
        # It is invoked only after its runcommand=off guard is rechecked.
        if rop.parm('runcommand').eval()!=0:
            raise ValueError('OFFICIAL_EXPORT_ONLY_REQUIRED')
        export_only(rop,usd,image)
        from pxr import Usd
        from houdini_bridge.official_karma_native import capture_stage,verify_output_stage,semantic_compare
        exported=Usd.Stage.Open(str(usd))
        if exported is None:
            raise ValueError('OFFICIAL_EXPORTED_USD_UNREADABLE')
        verify_output_stage(exported,str(image))
        compared=semantic_compare(observation['stage'],capture_stage(exported),reference_output=str(image),actual_output=str(image),
                                  export_up_axis_policy='h21_export_fallback_y_v1')
        result['export_semantic_comparison']=compared
        if compared['state']!='PASS':
            raise ValueError('OFFICIAL_EXPORTED_USD_SEMANTIC_MISMATCH:'+json.dumps(compared['differences']))
        result['usd']=file_record(usd)
    check_frozen_case(scope)
    scope.check()
    if owned_process.read_receipt(directory,result['event'],identity=identity) is not None:
        raise ValueError('OFFICIAL_OBSERVATION_ORIGINAL_ALREADY_EXISTS')
    owned_process._signed_write(directory,result)
    return {'state':'OBSERVED_NOT_ACCEPTED','role':role,'observation':result['observation']}


def argument_parser():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',required=True)
    parser.add_argument('--phase',choices=['official-open-save','official-cold-export'],required=True)
    return parser


def main():
    args=argument_parser().parse_args()
    print(json.dumps(run(args.scope,args.phase),allow_nan=False))


if __name__=='__main__':
    main()
