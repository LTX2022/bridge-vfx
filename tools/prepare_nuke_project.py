#!/usr/bin/env python3
"""Save the existing, bound engineering Nuke graph without starting a host."""
from __future__ import annotations
import argparse
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


def _plain(raw, *, within=None):
    path = Path(raw)
    if (not path.is_absolute() or path != path.resolve()
            or any(p.is_symlink() for p in (path, *path.parents))
            or within is not None and not path.is_relative_to(within)):
        raise ValueError('ENGINEERING_HANDOFF_PATH_INVALID')
    return path


def _file(path, limit):
    path = _plain(path)
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError('ENGINEERING_HANDOFF_FILE_INVALID')
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    fields = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
    if (not 0 < len(data) <= limit or len(data) != before.st_size
            or any(getattr(before,key) != getattr(after,key) for key in fields)):
        raise ValueError('ENGINEERING_HANDOFF_FILE_INVALID')
    return data


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def _load_project(project):
    project = _plain(project)
    control = _plain(project/'control')
    if ROOT != _plain(control/'snapshot'):
        raise ValueError('ENGINEERING_HANDOFF_USE_FROZEN_PROJECT_ENTRY')
    config_path = control/'production-hosts.json'
    config_data = _file(config_path, 1024*1024)
    saved = json.loads(config_data)
    return project, control, saved, hashlib.sha256(config_data).hexdigest()



def _ensure_initial_nuke(project, control, saved, scope):
    """Start only the first Nuke host, from the frozen controller deployment."""
    from vfx_pipeline.production_hosts import ensure_hosts
    manifest = json.loads(_file(control/'run.json', 8*1024*1024))
    hconfig, nconfig = manifest.get('production_host'), manifest.get('production_nuke')
    if (not isinstance(hconfig, dict) or not isinstance(nconfig, dict)
            or any(config.get('native_scope') != scope.binding for config in (hconfig, nconfig))
            or any(config.get('evidence_source') != saved['hosts']['houdini']['evidence_source']
                   for config in (hconfig, nconfig))):
        raise ValueError('ENGINEERING_NUKE_FROZEN_DEPLOYMENT_REQUIRED')
    _, bound = ensure_hosts(hconfig, nconfig, task_id=saved['task_id'], controller_root=control,
        repo_root=ROOT, scheduler_root=scope.root/'scheduler', host_kinds={'nuke'},
        allow_software_processes=nconfig['evidence_source']=='software_test')
    _, _, current, digest = _load_project(project)
    if current.get('task_id') != saved['task_id'] or current['hosts'].get('nuke') != bound:
        raise ValueError('ENGINEERING_NUKE_INITIAL_BINDING_MISMATCH')
    return current, digest



def _live_nuke_for_reconcile(config, scope):
    from dcc_task_runtime import owned_process
    from dcc_task_runtime.platform_support import process_identity
    work = _plain(config['work_dir'],within=scope.root)
    launch = json.loads(_file(work/'launch.json',1024*1024))
    tickets = [ticket for ticket in scope.snapshot()['tickets'] if ticket['role']=='nuke-host']
    if (len(tickets)!=1 or tickets[0].get('stopped_at') is not None
            or tickets[0]['directory']!=str(work/'supervisor') or tickets[0]['identity']!=launch['identity']
            or any(config['expected_identity'].get(key)!=value for key,value in launch['identity'].items())):
        raise ValueError('ENGINEERING_NUKE_RECONCILE_HOST_REQUIRED')
    started = owned_process.read_receipt(tickets[0]['directory'],'started',identity=tickets[0]['identity'])
    stopped = owned_process.read_receipt(tickets[0]['directory'],'stopped',identity=tickets[0]['identity'])
    if not started or stopped is not None or started['pid']!=config['expected_identity'].get('pid'):
        raise ValueError('ENGINEERING_NUKE_RECONCILE_HOST_REQUIRED')
    observed=process_identity(started['pid'])
    if (observed.get('state')!='alive' or (started.get('process_birth') is not None
            and observed.get('birth')!=started['process_birth'])):
        raise ValueError('ENGINEERING_NUKE_RECONCILE_HOST_REQUIRED')


def _graph(client, config):
    names = [str(config.get('read_node') or 'Read1'), str(config.get('write_node') or 'Write1')]
    result = []
    for name, kind in zip(names, ('Read','Write')):
        node = client.call('get_node', {'name':name})
        knobs = node.get('knobs')
        if (node.get('name') != name or node.get('class') != kind
                or not isinstance(node.get('inputs'), list) or not isinstance(knobs, dict)
                or not isinstance(knobs.get('file'), str) or not knobs['file']):
            raise ValueError('ENGINEERING_NUKE_GRAPH_READBACK_INVALID')
        result.append({'name':name,'class':kind,'inputs':node['inputs'],
                       'knobs':{key:knobs[key] for key in ('file','colorspace','raw','premultiplied','channels') if key in knobs}})
    if result[1]['knobs'].get('channels') != 'rgba':
        raise ValueError('ENGINEERING_NUKE_RGBA_WRITE_REQUIRED')
    if not result[1]['inputs'] or result[1]['inputs'][0] != names[0]:
        raise ValueError('ENGINEERING_NUKE_GRAPH_READBACK_INVALID')
    return result


def prepare_nuke_project(project, script_path, *, artifact_id='engineering_h21_main',
                         output_pattern=None, frames=None, alpha_result_path=None, reconcile_saved=False):
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime.execution_lock import execution_lock
    from vfx_pipeline.workbuddy_assembly import production_nuke_client, production_host_client
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    from vfx_pipeline.workbuddy_graph_mcp import GraphRun
    project, control, saved, config_sha = _load_project(project)
    config = saved['hosts'].get('nuke')
    basis = config if config is not None else saved['hosts']['houdini']
    scope = NativeScope(basis.get('native_scope'))
    if (not project.is_relative_to(scope.root) or scope.scope.get('execution_authorized') is not True
            or scope.scope.get('status') != 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('ENGINEERING_NUKE_SCOPE_NOT_AUTHORIZED')
    scope.check()
    path = _plain(script_path,within=scope.root)
    expected_output = project/'saves/nuke.%04d.exr'
    output_pattern = expected_output if output_pattern is None else _plain(output_pattern,within=scope.root)
    frames = [1] if frames is None else frames
    if (artifact_id != 'engineering_h21_main' or output_pattern != expected_output
            or frames != [1] or any(type(frame) is not int for frame in frames)):
        raise ValueError('ENGINEERING_NUKE_INPUT_OUTPUT_NOT_FROZEN')
    if path != project/'saves/composite.nk':
        raise ValueError('ENGINEERING_NUKE_SCRIPT_PATH_NOT_FROZEN')
    source = basis.get('evidence_source')
    if source not in ('software_test','real_host'):
        raise ValueError('ENGINEERING_NUKE_SOURCE_INVALID')
    if source == 'real_host':
        activation_path = ROOT/'tools/activate_controlled_engineering.py'
        spec = importlib.util.spec_from_file_location('_frozen_engineering_activation',activation_path)
        activation = importlib.util.module_from_spec(spec);spec.loader.exec_module(activation)
        approved = activation.validate_activation(scope,scope.root/'runtime-bindings.json')
        if approved.get('authorization') not in ('explicit_local_terminal_controller','explicit_agent_controller'):
            raise ValueError('ENGINEERING_NUKE_TRUSTED_ACTIVATION_REQUIRED')
    if config is not None and (not isinstance(config.get('expected_identity'),dict) or not config['expected_identity']):
        raise ValueError('ENGINEERING_NUKE_IDENTITY_REQUIRED')
    receipt_path = _plain(control/'nuke-save-receipt.json',within=scope.root)
    key = _file(scope.key_path,32)
    if hashlib.sha256(key).hexdigest() != scope.scope['accounting']['key_sha256']:
        raise ValueError('ENGINEERING_NUKE_RECEIPT_KEY_INVALID')
    with execution_lock(receipt_path, saved['task_id']):
        _, _, current_saved, current_sha = _load_project(project)
        if (current_saved.get('task_id')!=saved['task_id']
                or current_saved['hosts']['houdini'].get('native_scope')!=scope.binding):
            raise ValueError('ENGINEERING_NUKE_INITIAL_BINDING_MISMATCH')
        saved,config_sha=current_saved,current_sha
        config=saved['hosts'].get('nuke')
        scope=NativeScope(scope.binding)
        if receipt_path.exists():
            envelope = json.loads(_file(receipt_path,1024*1024))
            fact = envelope.get('payload')
            signature = hmac.new(key,_canonical(fact),hashlib.sha256).hexdigest()
            if (not hmac.compare_digest(signature,str(envelope.get('signature','')))
                    or fact.get('schema') != 'bridge.engineering-nuke-save/1'
                    or fact.get('path') != str(path) or fact.get('task_id') != saved['task_id']
                    or fact.get('config_sha256') != config_sha
                    or fact.get('scope_sha256') != scope.binding['sha256']
                    or fact.get('tool_sha256') != hashlib.sha256(_file(ROOT/'tools/prepare_nuke_project.py',1024*1024)).hexdigest()
                    or fact.get('sha256') != hashlib.sha256(_file(path,16*1024*1024)).hexdigest()
                    or fact.get('bytes') != path.stat().st_size):
                raise ValueError('ENGINEERING_NUKE_SAVE_RECEIPT_MISMATCH')
            return fact
        intent_path=_plain(control/'nuke-save-intent.json',within=scope.root)
        if path.is_symlink() or (path.exists() and not reconcile_saved):
            raise ValueError('ENGINEERING_NUKE_SCRIPT_ALREADY_EXISTS')
        if reconcile_saved and (config is None or not intent_path.is_file() or not path.is_file()):
            raise ValueError('ENGINEERING_NUKE_SAVE_RECONCILE_UNRESOLVED')
        spec = importlib.util.spec_from_file_location('_frozen_verify_controlled_output',ROOT/'tools/verify_controlled_output.py')
        verifier = importlib.util.module_from_spec(spec); spec.loader.exec_module(verifier)
        hconfig = verifier._alpha_configuration(saved['hosts']['houdini'],
            scope.root/'alpha-calibration-result.json' if alpha_result_path is None else alpha_result_path)
        host = production_host_client(hconfig,control/'host-state')
        host.bind_task(saved['task_id'])
        registry = ArtifactRegistry(control/'artifact_ledger')
        host.bind_artifact_registry(registry)
        facade = GraphRun(control/'run.json',None,task_id=saved['task_id'],host_client=host,
                          artifact_registry=registry,save_root=str(project/'saves'))
        artifact = facade.consume_artifact(artifact_id)
        provenance = artifact.get('output_verification') or {}
        if (artifact.get('usable_as_render_input') is not True
                or provenance.get('verification_basis') != 'controlled_output_v1'
                or provenance.get('evidence_source') != source):
            raise ValueError('ENGINEERING_NUKE_VERIFIED_INPUT_REQUIRED')
        if config is None:
            saved, config_sha = _ensure_initial_nuke(project, control, saved, scope)
            config = saved['hosts']['nuke']
        if (config.get('native_scope') != scope.binding or config.get('evidence_source') != source
                or not isinstance(config.get('expected_identity'), dict)):
            raise ValueError('ENGINEERING_NUKE_INITIAL_BINDING_MISMATCH')
        client = production_nuke_client(config,control/'nuke-state')
        client.bind_task(saved['task_id'])
        client.bind_artifact_registry(registry)
        # Recheck the registered input immediately before editing the live graph.
        artifact = facade.consume_artifact(artifact_id)
        intent_base={'schema':'bridge.engineering-nuke-save-intent/1','task_id':saved['task_id'],
            'path':str(path),'scope_sha256':scope.binding['sha256'],'config_sha256':config_sha,
            'host_identity':dict(client.expected_identity),'input_artifact':artifact,
            'tool_sha256':hashlib.sha256(_file(ROOT/'tools/prepare_nuke_project.py',1024*1024)).hexdigest()}
        if reconcile_saved:
            _live_nuke_for_reconcile(config,scope)
            envelope=json.loads(_file(intent_path,1024*1024))
            intent=envelope.get('payload')
            if (not isinstance(intent,dict) or not hmac.compare_digest(str(envelope.get('signature','')),
                    hmac.new(key,_canonical(intent),hashlib.sha256).hexdigest())
                    or any(intent.get(name)!=value for name,value in intent_base.items())):
                raise ValueError('ENGINEERING_NUKE_SAVE_RECONCILE_UNRESOLVED')
            nodes=_graph(client,config)
            if nodes!=intent.get('nodes'):
                raise ValueError('ENGINEERING_NUKE_SAVE_RECONCILE_UNRESOLVED')
            output_binding=intent['output_binding']
        else:
            if intent_path.exists():
                raise ValueError('ENGINEERING_NUKE_SAVE_RECONCILE_REQUIRED')
            output_binding = client.render_binding(saved['task_id'],str(output_pattern),frames,
                artifact['colorspace'],artifact['premultiplied'],artifact_binding=artifact)
            client.call('set_knob', {'node':str(config.get('write_node') or 'Write1'),
                'knob':'channels', 'value':'rgba'})
            nodes = _graph(client,config)
            intent=dict(intent_base,nodes=nodes,output_binding=output_binding)
            envelope={'payload':intent,'signature':hmac.new(key,_canonical(intent),hashlib.sha256).hexdigest()}
            with intent_path.open('xb') as stream:stream.write(_canonical(envelope))
            result = client.call('save_script',{'path':str(path),'overwrite':False})
            if result.get('path') != str(path):
                raise ValueError('ENGINEERING_NUKE_SAVE_RESULT_MISMATCH')
        data = _file(path,16*1024*1024)
        info = client.call('script.info',{})
        if (info.get('script') != str(path) or info.get('modified') is not False or _graph(client,config) != nodes
                or _file(path,16*1024*1024)!=data):
            raise ValueError('ENGINEERING_NUKE_SAVE_READBACK_MISMATCH')
        fact = {'schema':'bridge.engineering-nuke-save/1','task_id':saved['task_id'],
                'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
                'nodes':nodes,'input_artifact':artifact,'output_binding':output_binding,'evidence_source':source,'scope_sha256':scope.binding['sha256'],
                'config_sha256':config_sha,'host_identity':dict(client.expected_identity),
                'tool_sha256':hashlib.sha256(_file(ROOT/'tools/prepare_nuke_project.py',1024*1024)).hexdigest(),
                'observed_by':('trusted_controller_reconciled_current_task_script' if reconcile_saved
                               else 'trusted_controller_after_bound_save_script_and_readback')}
        envelope = {'payload':fact,'signature':hmac.new(key,_canonical(fact),hashlib.sha256).hexdigest()}
        with receipt_path.open('xb') as stream: stream.write(_canonical(envelope))
        return fact


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--script',type=Path,required=True)
    parser.add_argument('--artifact-id',default='engineering_h21_main')
    parser.add_argument('--output-pattern',type=Path)
    parser.add_argument('--alpha-result',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare_nuke_project(args.project,args.script,artifact_id=args.artifact_id,output_pattern=args.output_pattern,alpha_result_path=args.alpha_result),ensure_ascii=False,sort_keys=True,allow_nan=False))
    return 0

if __name__=='__main__': raise SystemExit(main())
