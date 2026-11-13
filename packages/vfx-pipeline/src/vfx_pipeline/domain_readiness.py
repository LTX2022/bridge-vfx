"""Replay readiness cases through production domain commands.

A successful RPC or an editable scaffold does not satisfy a domain lifecycle.
Receipts retain executed stages and concrete blockers; missing evidence cannot
be promoted to PASS by a scenario name or by another domain's result.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from dcc_task_runtime.domain_objective import DomainVisualObjective, REQUIRED_CONTROLS
from dcc_task_runtime.domains import builtin_domain_registry
from dcc_task_runtime.visual_objective import MediaManifest, MediaAsset, SemanticValue

DOMAIN_IDS = tuple(REQUIRED_CONTROLS)
SCENARIOS = ('build_inspect', 'causal_candidate', 'approval_recovery')

class DomainReadinessError(ValueError):
    pass

@dataclass(frozen=True)
class ReadinessCase:
    case_id: str
    domain_pack: str
    scenario: str
    application: str
    boundary_kind: str
    result: Mapping[str, Any]
    def to_dict(self):
        return dict(case_id=self.case_id,domain_pack=self.domain_pack,scenario=self.scenario,
                    application=self.application,boundary_kind=self.boundary_kind,**self.result)

class DomainReadinessRunner:
    def __init__(self, *, host_client=None, nuke_client=None, task_id, output_root,
                 repo_root=None, houdini_versions=('21.0.631','22.0.459'), registry=None,
                 case_specs=None, artifact_registry=None, case_facade_factory=None):
        self.host_client,self.nuke_client=host_client,nuke_client
        self.task_id=str(task_id).strip()
        if not self.task_id:raise DomainReadinessError('task_id is required')
        self.output_root=Path(output_root).resolve();self.output_root.mkdir(parents=True,exist_ok=True)
        self.repo_root=Path(repo_root).resolve() if repo_root else None
        self.houdini_versions=houdini_versions
        self.registry=registry or builtin_domain_registry()
        self.artifact_registry=artifact_registry
        self.case_facade_factory = case_facade_factory
        self._formal_owners = {}
        self.case_specs=dict(case_specs or {})
        self.boundary_kind=str(getattr(host_client or nuke_client,'boundary_kind','configured'))

    def _spec(self, domain, case_id):
        """Explicit synthetic controls carry default provenance, never observation."""
        if case_id in self.case_specs:return dict(self.case_specs[case_id])
        pack=self.registry.get(domain,'1.0.0');controls=[]
        for name in REQUIRED_CONTROLS[domain]:
            c=pack.control_map[name];value=max(c.minimum or 0,0.5)
            if c.value_type=='int':value=max(1,int(c.minimum or 1))
            elif c.value_type=='bool':value=True
            elif c.value_type=='color3':value=(0.5,0.5,0.5)
            controls.append((name,SemanticValue(value,'default',basis='synthetic-case-fixture')))
        media=self.output_root/(case_id+'.reference.ppm')
        media.write_bytes(b'P6\n1 1\n255\n\x80\x80\x80')
        digest=hashlib.sha256(media.read_bytes()).hexdigest()
        manifest=MediaManifest((MediaAsset('synthetic-reference','image',media.as_uri(),digest,width=1,height=1),))
        plan=DomainVisualObjective(domain,manifest,tuple(controls)).source_plan().require_ready()
        return {'task_id':self.task_id+'-'+case_id,'inputs':[{'asset_id':'synthetic-reference','role':'reference','sha256':digest,'path':str(media)}],
                'constraints':{'fx':{'domain_pack':domain,'run_mode':'diagnose',
                    'domain_control_plan':plan.to_dict(),'domain_control_plan_sha256':plan.plan_sha256,'frames':[1,2]}},
                'render':{'frame_range':{'start':1,'end':2,'step':1}}}

    @staticmethod
    def _call(client, command, params, receipts):
        if client is None or not callable(getattr(client,'call',None)):
            raise DomainReadinessError('configured '+command+' boundary is missing')
        response=client.call(command,params)
        if not isinstance(response,dict):raise DomainReadinessError(command+' returned a non-object')
        receipts.append({'command':command,'result':response})
        return response

    @staticmethod
    def _candidate_value(control, value):
        value_type = str(control.value_type)
        if value_type == 'bool':
            return not bool(value)
        if value_type == 'int':
            current = int(value)
            delta = 1
            candidate = current + delta
            if control.maximum is not None and candidate > control.maximum:
                candidate = current - delta
            return control.validate(candidate)
        if value_type == 'float':
            current = float(value)
            delta = max(abs(current) * 0.1, 0.01)
            candidate = current + delta
            if control.maximum is not None and candidate > control.maximum:
                candidate = current - delta
            return control.validate(candidate)
        if value_type == 'color3':
            return control.validate(tuple(max(0.0, min(1.0, float(item) * 0.9)) for item in value))
        if value_type == 'enum':
            choices = tuple(control.choices)
            return control.validate(choices[(choices.index(str(value)) + 1) % len(choices)])
        return control.validate(str(value) + '-candidate')

    def _control_contract(self, domain, plan, scene, nodes):
        expected_names = tuple(REQUIRED_CONTROLS[domain])
        controls = list(plan.get('controls') or [])
        if {item.get('name') for item in controls if isinstance(item, dict)} != set(expected_names):
            raise DomainReadinessError('domain control plan does not cover every required semantic control')
        readback = scene.get('domain_control_readback')
        if not isinstance(readback, dict):
            raise DomainReadinessError('scene has no domain control readback')
        pack = self.registry.get(domain, '1.0.0')
        entries = []
        for item in controls:
            name = str(item.get('name') or '')
            control = pack.control_map.get(name)
            observed = readback.get(name)
            if control is None or not isinstance(observed, dict):
                raise DomainReadinessError('native control mapping is missing: ' + name)
            expected_scope = sorted(set(control.invalidates_stage_nodes) | set(control.invalidates_components))
            if (observed.get('readback_verified') is not True
                    or 'readback' not in observed
                    or not str(observed.get('invalidates_from') or '').strip()):
                raise DomainReadinessError('native control readback is incomplete: ' + name)
            entries.append({
                'name': name,
                'application': str(item.get('application') or control.application),
                'node_role': str((pack.control_map[name]).name),
                'expected_value': item.get('value'),
                'readback': observed.get('readback'),
                'readback_verified': True,
                'invalidates_stage_nodes': list(control.invalidates_stage_nodes),
                'invalidates_components': list(control.invalidates_components),
                'expected_invalidation_scope': expected_scope,
                'observed_invalidation_scope': str(observed['invalidates_from']),
            })
        coupling = {}
        if domain == 'water_flip_v1':
            initialization = scene.get('native_initialization') or {}
            coupling = {
                'fluid_source_particlesep': (initialization.get('fluid_source.particlesep') or {}).get('readback_verified') is True,
                'surface_particlesep': (initialization.get('surface.particlesep') or {}).get('readback_verified') is True,
            }
            if not all(coupling.values()):
                raise DomainReadinessError('FLIP particle separation coupling readback is incomplete')
        return {'controls': entries, 'coupling': coupling, 'all_controls_verified': True}

    def _wait_for_construction(self, facade, graph_id, request_id, trial, deadline):
        operation_id = trial.get('operation_id')
        if not isinstance(operation_id, str) or not operation_id:
            raise DomainReadinessError('FORMAL_GRAPH_OPERATION_MISSING')
        if trial.get('graph_id') != graph_id:
            raise DomainReadinessError('FORMAL_GRAPH_OPERATION_MISMATCH')
        polled = False
        while trial.get('state') in {'QUEUED', 'PREPARED', 'STARTING', 'RUNNING'}:
            if time.monotonic() >= deadline:
                break
            time.sleep(.05)
            trial = facade.graph_status(operation_id)
            if (trial.get('operation_id') != operation_id
                    or trial.get('graph_id') != graph_id):
                raise DomainReadinessError('FORMAL_GRAPH_OPERATION_MISMATCH')
            polled = True
        if trial.get('state') != 'SUCCEEDED' or trial.get('stop_confirmed') is not True:
            raise DomainReadinessError('FORMAL_GRAPH_INCOMPLETE: construction has no confirmed terminal receipt')
        if polled:
            trial = facade.graph_trial(graph_id, request_id)
            if (trial.get('operation_id') != operation_id or trial.get('graph_id') != graph_id
                    or trial.get('state') != 'SUCCEEDED' or trial.get('stop_confirmed') is not True):
                raise DomainReadinessError('FORMAL_GRAPH_OPERATION_MISMATCH')
        return trial

    @staticmethod
    def _formal_output_encoding(fact, frames):
        if fact.get('completion_metadata_status') != 'AVAILABLE':
            missing = fact.get('completion_metadata_missing_facts')
            detail = ','.join(missing) if isinstance(missing, list) and missing and all(
                isinstance(item, str) and item for item in missing) else 'typed native output metadata unavailable'
            raise DomainReadinessError('FORMAL_OUTPUT_NATIVE_FACTS_REQUIRED: ' + detail)
        metadata = fact.get('metadata')
        producer_frames = fact.get('frame_set')
        if (not frames or any(type(frame) is not int for frame in frames) or len(set(frames)) != len(frames)
                or not isinstance(producer_frames, list) or any(type(frame) is not int for frame in producer_frames)
                or producer_frames != frames or not isinstance(metadata, Mapping)
                or set(metadata) != {str(frame) for frame in frames}):
            raise DomainReadinessError('FORMAL_OUTPUT_ENCODING_MISMATCH: exact producer frame set required')
        encoding = None
        for frame in frames:
            image = metadata[str(frame)]
            if (not isinstance(image, Mapping) or not isinstance(image.get('colorspace'), str)
                    or not image['colorspace'].strip() or type(image.get('premultiplied')) is not bool):
                raise DomainReadinessError('FORMAL_OUTPUT_ENCODING_MISMATCH: native color and alpha facts required')
            observed = (image['colorspace'], image['premultiplied'])
            if encoding is not None and observed != encoding:
                raise DomainReadinessError('FORMAL_OUTPUT_ENCODING_MISMATCH: frame encodings differ')
            encoding = observed
        return encoding

    @staticmethod
    def _formal_registration_retry(register):
        for attempt in (1, 2):
            try:
                return register(attempt)
            except sqlite3.OperationalError as error:
                code = getattr(error, 'sqlite_errorcode', None)
                if attempt == 2 or type(code) is not int or code & 255 not in {
                        sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    raise
            except OSError:
                if attempt == 2:
                    raise

    @staticmethod
    def _formal_saved_scene(saved, current, *, owner, graph_id, source, host_identity=None):
        from houdini_bridge.operation_receipts import canonical_sha256, validate_operation_receipt

        version = current.get('version')
        compiled = current.get('compiled') or {}
        contract = saved.get('scene_contract') or {}
        dependencies = [f'graph:{owner}:{graph_id}:output:domain_output',
                        f'graph:{owner}:{graph_id}:version:{version}']
        if (type(version) is not int or version < 0 or current.get('task_id') != owner
                or current.get('state') != 'COMPLETE' or not compiled.get('graph_hash')
                or not saved.get('saved_scene_id') or not saved.get('path') or not saved.get('sha256')
                or saved.get('feedback_dependencies') != dependencies
                or contract.get('task_id') != owner or contract.get('graph_hash') != compiled['graph_hash']
                or saved.get('scene_contract_sha256') != canonical_sha256(contract)):
            raise DomainReadinessError('FORMAL_SAVE_INCOMPLETE: current owned graph and HIP contract are required')
        path = Path(saved['path'])
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != saved['sha256']):
            raise DomainReadinessError('FORMAL_SAVE_STALE: current HIP bytes differ from saved content')
        record = saved.get('operation_receipt')
        if record is None:
            return {'typed_save_verified': False, 'blocker': 'FORMAL_TYPED_TASK_SAVE_MISSING'}
        validate_operation_receipt(record)
        if (not isinstance(host_identity, Mapping) or any(record['host_identity'].get(key) != host_identity.get(key)
                for key in ('task_id', 'pid', 'session_id', 'launch_nonce', 'process_generation',
                            'plugin_build', 'scene_epoch'))):
            raise DomainReadinessError('FORMAL_TYPED_SAVE_HOST_MISMATCH')
        actual = {key: value for key, value in saved.items() if key not in {
            'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent',
            'feedback_dependencies', 'saved_scene_id'}}
        native_saved = record['facts'].get('saved_scene') or {}
        if (record['command'] != 'scene.save_hip' or record['task_id'] != owner
                or record['result'] != actual or record['after_scene']['scene_contract'] != contract
                or native_saved.get('path') != saved['path'] or native_saved.get('sha256') != saved['sha256']
                or saved.get('operation_store_format') != 'producer_record'):
            raise DomainReadinessError('FORMAL_TYPED_SAVE_BINDING_MISMATCH')
        stored = Path(saved.get('operation_store_path') or '')
        if not stored.is_absolute() or stored.is_symlink() or json.loads(stored.read_bytes()) != record:
            raise DomainReadinessError('FORMAL_TYPED_SAVE_STORAGE_MISMATCH')
        snapshot = Path(native_saved['snapshot_path'])
        if (not snapshot.is_absolute() or snapshot.is_symlink()
                or hashlib.sha256(snapshot.read_bytes()).hexdigest() != saved['sha256']):
            raise DomainReadinessError('FORMAL_TYPED_SAVE_SNAPSHOT_MISMATCH')
        manifest = Path(source.get('manifest_path') or '')
        index = manifest.parent / 'snapshot-manifest.json'
        if (not manifest.is_absolute()
                or hashlib.sha256(manifest.read_bytes()).hexdigest() != source.get('manifest_sha256')
                or hashlib.sha256(index.read_bytes()).hexdigest() != source.get('snapshot_manifest_sha256')):
            raise DomainReadinessError('FORMAL_TYPED_SAVE_SOURCE_MISMATCH')
        addon = 'plugins/houdini/_impl/houdini_bridge_addon.py'
        entries = [item for item in json.loads(index.read_bytes()).get('files', []) if item.get('path') == addon]
        frozen = Path(source.get('repo_root') or '') / addon
        if (len(entries) != 1 or entries[0].get('sha256') != record['host_identity']['plugin_build']
                or hashlib.sha256(frozen.read_bytes()).hexdigest() != entries[0]['sha256']):
            raise DomainReadinessError('FORMAL_TYPED_SAVE_SOURCE_MISMATCH')
        return {'typed_save_verified': True, 'operation_id': record['operation_id'],
                'operation_receipt_sha256': record['operation_receipt_sha256'],
                'scope': 'current_task_save', 'domain_lifecycle_verified': False}

    @staticmethod
    def _formal_producer_fact(queried, *, operation_id, owner, frames, pattern, target, saved):
        fact = queried.get('execution_fact') or {}
        if (queried.get('operation', {}).get('state') != 'COMPLETED'
                or queried.get('kind') != 'houdini-render'
                or fact.get('schema') != 'bridge.houdini.render.execution_fact/1.0'
                or fact.get('state') != 'COMPLETED' or fact.get('command') != 'render.start'
                or fact.get('operation_id') != operation_id or fact.get('stop_confirmed') is not True
                or fact.get('task_id') != owner or fact.get('frame_set') != frames
                or fact.get('frames_done') != frames or fact.get('output_pattern') != pattern
                or fact.get('render_target') != target
                or (fact.get('scene') or {}).get('sha256') != saved['sha256']
                or (fact.get('scene') or {}).get('snapshot_sha256') != saved['sha256']
                or (fact.get('scene') or {}).get('path') != saved['path']
                or (fact.get('scene') or {}).get('scene_contract') != saved['scene_contract']
                or (fact.get('scene') or {}).get('scene_contract_sha256') != saved['scene_contract_sha256']
                or not fact.get('operation_receipt_sha256')
                or fact.get('dependencies') != saved['feedback_dependencies']):
            raise DomainReadinessError('FORMAL_RENDER_INCOMPLETE: current saved producer fact is required')
        return fact

    def _formal_feedback_controls(self, facade, domain, graph_id, topology, version, saved, stage, context=None):
        from houdini_bridge.native_render_domains import (
            control_contract, control_readback, candidate_write_plan, SHUTTER_CONTRACT,
        )
        native_version = self.houdini_versions[0]
        contract = control_contract(domain, native_version)
        pack = self.registry.get(domain, '1.0.0')
        if set(contract) != set(pack.control_map):
            raise DomainReadinessError('FORMAL_CONTROL_CONTRACT_INCOMPLETE: ' + domain)
        paths, fields = {}, {}
        for name, item in contract.items():
            role = item['role']
            matches = [path for address, path in topology['nodes'].items() if address.endswith('/' + role)]
            if len(matches) != 1 or not matches[0].startswith(topology['root'] + '/'):
                raise DomainReadinessError('FORMAL_FEEDBACK_TARGET_MISSING: ' + role)
            paths[role] = matches[0]
            fields.setdefault(role, set()).update(item['aliases'])
            for gate_role, field, expected in item['required_gates']:
                fields.setdefault(gate_role, set()).add(field)
            if name == 'shutter':
                fields[role].add('xn__shutterclose_nva')
            if name in {'pixel_samples', 'sample_quality'}:
                fields[role].update(('engine', 'convergence_mode'))
            if name == 'filter_width' and native_version in ('22.0.429', '22.0.459'):
                fields[role].add('pixelfilterscale')

        def snapshot():
            values = {}
            for role, names in fields.items():
                try:
                    result = stage('node.parms', lambda role=role, names=names: facade.host_client.call(
                        'node.parms', {'path': paths[role], 'names': sorted(names)}), graph_version=version)
                except Exception as exc:
                    tuples = [name for name, item in contract.items()
                        if item['role'] == role and item['value_type'] == 'color3']
                    if getattr(exc, 'code', None) == 'UNSUPPORTED_PARAMETER' and tuples:
                        raise DomainReadinessError('FORMAL_CONTROL_TUPLE_READBACK_REQUIRED: ' + ','.join(tuples) +
                            ' requires the shared registered feedback tuple readback interface') from exc
                    raise
                actual = result.get('parms')
                if result.get('path') != paths[role] or not isinstance(actual, dict) or set(actual) != names:
                    raise DomainReadinessError('FORMAL_CONTROL_READBACK_INCOMPLETE: ' + role)
                values.update({(role, name): value for name, value in actual.items()})
            return values

        controls = []
        for name, item in contract.items():
            before = snapshot()
            semantic_before = control_readback(domain, name, before, native_version, shutter_contract=SHUTTER_CONTRACT)
            semantic_candidate = (float(1 - semantic_before) if name == 'denoise_mix' else
                self._candidate_value(pack.control_map[name], semantic_before))
            if semantic_candidate == semantic_before:
                raise DomainReadinessError('FORMAL_CONTROL_CANDIDATE_UNCHANGED: ' + name)
            candidate = json.loads(json.dumps(semantic_candidate, allow_nan=False))
            writes = json.loads(json.dumps(candidate_write_plan(domain, {name: candidate}, native_version,
                shutter_contract=SHUTTER_CONTRACT)))
            expected = {**before, **{(write['role'], write['parm']): write['value'] for write in writes}}
            feedback = stage('feedback_edit', lambda: facade.feedback_edit(graph_id, item['role'],
                {name: candidate}, facade.pipeline_task_id), semantic_control=name, graph_version=version)
            diffs = feedback.get('parameter_diff') or []
            frozen = feedback.get('domain_candidate') or {}
            if (not diffs or {entry.get('semantic_control') for entry in diffs} != {name}
                    or any(entry.get('readback_verified') is not True or entry.get('node') != paths[item['role']]
                           for entry in diffs)
                    or frozen.get('controls') != {name: candidate} or frozen.get('writes') != writes
                    or frozen.get('task_id') != facade.pipeline_task_id):
                raise DomainReadinessError('FORMAL_CONTROL_FEEDBACK_UNVERIFIED: ' + name)
            after = snapshot()
            semantic_after = control_readback(domain, name, after, native_version, shutter_contract=SHUTTER_CONTRACT)
            if after != expected or semantic_after != semantic_candidate:
                raise DomainReadinessError('FORMAL_CONTROL_READBACK_MISMATCH: ' + name)
            current = stage('graph_version', lambda: facade.graph_version(graph_id), graph_version=version + 1)
            if (current.get('version') != version + 1 or current.get('state') != 'COMPLETE'
                    or current.get('task_id') != facade.pipeline_task_id):
                raise DomainReadinessError('FORMAL_FEEDBACK_VERSION_MISSING: ' + name)
            nodes = [node for node in current['compiled']['nodes'] if node['node_id'] == item['role']]
            if len(nodes) != 1 or any(nodes[0]['parameters'].get(write['parm']) != write['value'] for write in writes):
                raise DomainReadinessError('FORMAL_CONTROL_GRAPH_PARAMETERS_STALE: ' + name)
            version = current['version']
            if context is not None:
                context['graph_version'] = version
            previous_saved = saved
            saved = stage('task_save', facade.task_save, semantic_control=name, graph_version=version)
            if (not saved.get('saved_scene_id') or not saved.get('sha256') or not saved.get('feedback_dependencies')
                    or 'graph:{}:{}:version:{}'.format(facade.pipeline_task_id, graph_id, version)
                        not in saved['feedback_dependencies']
                    or any(saved[key] == previous_saved[key] for key in
                           ('saved_scene_id', 'sha256', 'feedback_dependencies'))):
                raise DomainReadinessError('FORMAL_FEEDBACK_SAVE_STALE: ' + name)
            save_evidence = self._formal_saved_scene(saved, current, owner=facade.pipeline_task_id,
                graph_id=graph_id, source=facade.controller_source,
                host_identity=getattr(facade.host_client, 'expected_identity', None))
            if context is not None:
                context.update(save_receipt=saved, typed_save_evidence=save_evidence)
                if not save_evidence['typed_save_verified'] and 'typed_task_save' not in context['explicit_stage_gaps']:
                    context['explicit_stage_gaps'].append('typed_task_save')
                elif save_evidence['typed_save_verified'] and 'typed_task_save' in context['explicit_stage_gaps']:
                    context['explicit_stage_gaps'].remove('typed_task_save')
            reopened_scene = stage('task_reopen', lambda: facade.task_reopen(saved['saved_scene_id']), semantic_control=name,
                graph_version=version, saved_scene_id=saved['saved_scene_id'])
            if reopened_scene.get('path') != saved['path'] or reopened_scene.get('sha256') != saved['sha256']:
                raise DomainReadinessError('FORMAL_REOPEN_CURRENT_HIP_MISMATCH: ' + name)
            reopened = snapshot()
            if reopened != after:
                raise DomainReadinessError('FORMAL_CONTROL_REOPEN_MISMATCH: ' + name)
            controls.append({'name': name, 'before': semantic_before, 'after': semantic_after,
                'reopened': control_readback(domain, name, reopened, native_version, shutter_contract=SHUTTER_CONTRACT),
                'native_before': [{'role': role, 'parm': field, 'value': value} for (role, field), value in before.items()],
                'feedback': feedback, 'graph_version': version, 'save_receipt': saved})
            if context is not None:
                context.update(reopen_receipt=reopened_scene, feedback_controls=list(controls),
                    semantic_control_coverage=[item['name'] for item in controls])
        return {'controls': controls, 'semantic_control_coverage': [item['name'] for item in controls],
            'graph_version': version, 'save_receipt': saved,
            'semantic_blockers': ['EXTERNAL_DENOISE_BLEND_REQUIRED: denoise_mix interval needs raw/denoised producer and Nuke blend evidence']
                if domain == 'lighting_camera_render_v1' else []}

    def _formal_nuke(self, domain, scenario, case_id, receipts, context=None):
        """Run Nuke's own registered-input route without a Houdini prerequisite."""
        context = context if context is not None else {}
        with self.case_facade_factory(case_id=case_id, domain=domain, scenario=scenario) as facade:
            owner = str(facade.pipeline_task_id or '')
            client = getattr(facade, 'nuke_client', None)
            if (not owner or getattr(facade, 'backend_kind', None) != 'production'
                    or getattr(client, 'bound_task_id', None) != owner
                    or getattr(client, 'backend_kind', None) != 'production'):
                raise DomainReadinessError('FORMAL_CASE_OWNER_MISMATCH: Nuke must bind the controller owner')
            if owner in self._formal_owners and self._formal_owners[owner] != case_id:
                raise DomainReadinessError('FORMAL_CASE_OWNER_REUSED: each case requires its own controller')
            self._formal_owners[owner] = case_id
            source = dict(getattr(facade, 'controller_source', {}))
            if source.get('backend') != 'production' or not source.get('snapshot_manifest_sha256'):
                raise DomainReadinessError('FORMAL_SOURCE_MISSING: prepared source snapshot is required')
            if (getattr(client, 'production_config', {}) or {}).get('version') != '17.0v1':
                raise DomainReadinessError('FORMAL_CASE_VERSION_MISMATCH: Nuke 17.0v1 is required')
            context.update(controller_task_id=owner, controller_source=source,
                formal_domain_lifecycle_verified=False, boundary_kind=str(getattr(client, 'boundary_kind', 'configured')),
                explicit_stage_gaps=['full_semantic', 'preview', 'persisted_output', 'domain_recovery', 'delivery'])

            def stage(name, callback, **provenance):
                receipt = {'operation': name, 'task_id': owner, 'source': source, **provenance}
                try:
                    result = callback()
                except Exception as exc:
                    receipts.append({**receipt, 'error': str(exc), 'error_type': type(exc).__name__})
                    raise
                receipts.append({**receipt, 'result': result})
                return result

            supplied = dict(self.case_specs.get(case_id) or {})
            artifact_id = supplied.get('formal_input_artifact_id') or facade.manifest.get('nuke_input_artifact_id')
            if not isinstance(artifact_id, str) or not artifact_id:
                raise DomainReadinessError('NUKE_INPUT_ARTIFACT_NOT_BOUND: explicitly register and select a trusted effect input')
            entry = facade.artifact_registry.lookup(artifact_id) if facade.artifact_registry is not None else None
            if not isinstance(entry, dict) or entry.get('task_id') != owner:
                raise DomainReadinessError('NUKE_INPUT_ARTIFACT_OWNER_MISMATCH')
            consumed = stage('consume_artifact', lambda: facade.consume_artifact(artifact_id))
            frames = list(entry.get('frame_set') or [])
            if (consumed.get('usable_as_render_input') is not True or not frames or len(frames) > 12
                    or any(type(frame) is not int or frame < 1 for frame in frames)
                    or frames != sorted(set(frames))
                    or (consumed.get('verification') or {}).get('frame_set') != frames):
                raise DomainReadinessError('NUKE_INPUT_ARTIFACT_NOT_USABLE')
            stride = frames[1] - frames[0] if len(frames) > 1 else 1
            if frames != list(range(frames[0], frames[-1] + 1, stride)):
                raise DomainReadinessError('NUKE_INPUT_FRAME_RANGE_UNSUPPORTED: composite requires an exact arithmetic frame set')
            from dcc_task_runtime.artifact_registry import frame_path
            snapshots = (entry.get('payload') or {}).get('completion_snapshot') or {}
            frame_manifest = []
            canonical_frames = []
            for ordinal, frame in enumerate(frames):
                snapshot = snapshots.get(str(frame)) or {}
                path = str(Path(frame_path(entry['pattern'], frame)).resolve())
                if (not isinstance(snapshot.get('sha256'), str) or len(snapshot['sha256']) != 64
                        or type(snapshot.get('bytes')) is not int or snapshot['bytes'] <= 0):
                    raise DomainReadinessError('NUKE_INPUT_SNAPSHOT_MISSING')
                frame_manifest.append({'frame': frame, 'path': path,
                    'sha256': snapshot['sha256'], 'bytes': snapshot['bytes']})
                canonical_frames.append({'index': ordinal, 'frame': frame, 'uri': path,
                    'sha256': snapshot['sha256'], 'bytes': snapshot['bytes']})
            digest = hashlib.sha256(json.dumps(canonical_frames, ensure_ascii=False, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            controls = dict((supplied.get('constraints') or {}).get('composite_controls')
                or {'blur_size': 0.5, 'premult': False})
            spec = {'schema_version': '2.0', 'task_id': owner,
                'inputs': [{'artifact_id': artifact_id, 'asset_id': artifact_id, 'role': 'effect_render',
                    'path': entry['pattern'], 'frames': frame_manifest, 'sha256': digest}],
                'constraints': {'composite_controls': controls},
                'render': {'output_dir': str(Path(facade.save_root) / case_id),
                    'frame_range': {'start': frames[0], 'end': frames[-1], 'step': stride}}}
            built = stage('nuke_composite_build', lambda: facade.nuke_composite_action(
                'agent.nuke.composite.build_graph', spec))
            self._require_gate(built, 'editable_native_composite_graph')
            if (not isinstance(built.get('graph'), dict) or built['graph'].get('task_id') != owner
                    or not built['graph'].get('graph_nodes') or not built['graph'].get('write')):
                raise DomainReadinessError('NUKE_GRAPH_INCOMPLETE: owned editable graph readback is required')
            audit = stage('nuke_composite_audit', lambda: facade.nuke_composite_action(
                'agent.nuke.composite.audit_lineage', spec))
            self._require_gate(audit, 'reference_isolated_from_final_write')
            context.update(formal_controller_verified=True, input_artifact_id=artifact_id,
                input_operation_id=entry.get('operation_id'), native_graph=built.get('graph'))
            script = Path(facade.save_root) / (case_id + '.nk')
            saved = stage('nuke_save', lambda: client.call('save_script', {'path': str(script), 'overwrite': True}))
            if script.is_symlink() or not script.is_file() or saved.get('path') != str(script):
                raise DomainReadinessError('NUKE_SAVE_MISSING')
            saved = {**saved, 'sha256': hashlib.sha256(script.read_bytes()).hexdigest(), 'bytes': script.stat().st_size}
            context['save_receipt'] = saved
            opened = stage('nuke_reopen', lambda: client.call('open_script',
                {'path': str(script), 'sha256': saved['sha256']}))
            if (opened.get('path') != str(script) or opened.get('sha256') != saved['sha256']
                    or opened.get('registry_cache_invalidated') is not True):
                raise DomainReadinessError('NUKE_REOPEN_STATE_NOT_RESTORED')
            restored = stage('nuke_reopen_graph', lambda: facade.nuke_composite_action(
                'agent.nuke.composite.build_graph', spec))
            self._require_gate(restored, 'editable_native_composite_graph')
            if restored.get('restored') is not True or restored.get('graph') != built.get('graph'):
                raise DomainReadinessError('NUKE_REOPEN_GRAPH_MISMATCH')
            context['reopen_receipt'] = opened
            if scenario == 'approval_recovery':
                raise DomainReadinessError('FORMAL_NUKE_RECOVERY_NOT_EXECUTED: actual composite worker interruption is required')
            if scenario == 'causal_candidate':
                feedback = stage('nuke_composite_feedback', lambda: facade.nuke_composite_action(
                    'agent.nuke.composite.apply_patch', {**spec,
                        'step_params': {'patch': {'controls': {'blur_size': 1.5, 'premult': True}}}}))
                self._require_gate(feedback, 'composite_patch_applied')
                self._require_gate(feedback, 'reference_isolated_from_final_write')
                context['feedback_receipt'] = feedback
            submitted = stage('nuke_composite_preview', lambda: facade.nuke_composite_render_bounded(
                case_id + '-preview', spec, [frames[0]]))
            operation_id = submitted['operation_id']
            deadline = time.monotonic() + 25.0
            while True:
                queried = facade.operation_query(operation_id)
                if queried.get('operation', {}).get('state') not in {'QUEUED', 'PREPARED', 'STARTING', 'RUNNING', 'CANCEL_PENDING'} or time.monotonic() >= deadline:
                    break
                time.sleep(.05)
            stage('operation_query', lambda: queried, operation_id=operation_id)
            fact = stage('nuke_render_fact', lambda: client.call('render_fact', {'operation_id': operation_id}),
                operation_id=operation_id)
            context.update(preview_operation=queried.get('operation'), execution_fact=fact)
            if (queried.get('kind') != 'nuke-render' or fact.get('operation_id') != operation_id
                    or fact.get('task_id') != owner or fact.get('state') != 'COMPLETED'
                    or fact.get('execution_kind') != 'owned_subprocess' or fact.get('stop_confirmed') is not True
                    or fact.get('frame_set') != [frames[0]] or fact.get('output_pattern') != submitted.get('pattern')
                    or not fact.get('formal_receipt')):
                raise DomainReadinessError('FORMAL_NUKE_PREVIEW_INCOMPLETE: owned-worker completion is required')
            context['explicit_stage_gaps'].remove('preview')
            return {'status': 'BLOCKED', 'blocker': 'FORMAL_NUKE_LIFECYCLE_INCOMPLETE: '
                + ', '.join(context['explicit_stage_gaps']), 'recovery': {'tested': False},
                'stage_receipts': receipts}

    def _formal_domain(self, domain, scenario, case_id, receipts, context=None):
        """Exercise the shared prepared controller and its persisted render facts."""
        context = context if context is not None else {}
        with self.case_facade_factory(case_id=case_id, domain=domain, scenario=scenario) as facade:
            owner = str(facade.pipeline_task_id or '')
            if (not owner or getattr(facade, 'backend_kind', None) != 'production'
                    or any(getattr(client, 'bound_task_id', None) != owner
                           or getattr(client, 'backend_kind', None) != 'production'
                           for client in (facade.host_client, facade.nuke_client))):
                raise DomainReadinessError('FORMAL_CASE_OWNER_MISMATCH: configured clients must bind the controller owner')
            if owner in self._formal_owners and self._formal_owners[owner] != case_id:
                raise DomainReadinessError('FORMAL_CASE_OWNER_REUSED: each case requires its own controller')
            self._formal_owners[owner] = case_id
            source = dict(getattr(facade, 'controller_source', {}))
            if source.get('backend') != 'production' or not source.get('snapshot_manifest_sha256'):
                raise DomainReadinessError('FORMAL_SOURCE_MISSING: prepared source snapshot is required')
            context.update(controller_task_id=owner, controller_source=source,
                formal_domain_lifecycle_verified=False,
                explicit_stage_gaps=['full_semantic', 'typed_task_save', 'preview',
                    'persisted_output', 'domain_recovery', 'nuke_producer'],
                boundary_kind=str(getattr(facade.host_client, 'boundary_kind', 'configured')))
            from .graph_catalog import registered_domain_ids
            if domain not in registered_domain_ids():
                raise DomainReadinessError('FORMAL_DOMAIN_CONSTRUCTION_UNAVAILABLE: ' + domain)
            if domain == 'vellum_softbody_grains_v1':
                raise DomainReadinessError('FORMAL_NATIVE_BRANCH_COVERAGE_REQUIRED: softbody and grains need separate evidence')
            version = None
            graph_id = None

            def stage(name, callback, **provenance):
                receipt = {'operation': name, 'task_id': owner, 'graph_id': graph_id,
                    'graph_version': version, 'source': source, **provenance}
                try:
                    result = callback()
                except Exception as exc:
                    receipts.append({**receipt, 'error': str(exc), 'error_type': type(exc).__name__})
                    raise
                receipts.append({**receipt, 'result': result})
                return result

            recovery_input = self.case_specs.get(case_id, {}).get('formal_recovery')
            if scenario == 'approval_recovery' and recovery_input is not None:
                from .graph_job_evidence import reconcile_prepared_graph_job
                graph_id = recovery_input['graph_id']
                context['graph_id'] = graph_id
                recovery = stage('owned_worker_recovery', lambda: reconcile_prepared_graph_job(
                    facade, **recovery_input), operation_id=recovery_input['operation_id'])
                context['recovery'] = recovery
                if recovery.get('tested') is not True:
                    raise DomainReadinessError(recovery.get('blocker') or 'FORMAL_RECOVERY_NOT_EXECUTED')
                trial = stage('graph_status', lambda: recovery['trial'], operation_id=recovery['operation_id'])
            else:
                catalog = stage('catalog', facade.catalog)
                for index, asset in enumerate(catalog['assets']):
                    stage('submit_observation', lambda asset=asset, index=index: facade.submit_observation(
                        asset['asset_id'], {'description': 'controller-generated synthetic readiness reference',
                        'dominant_colors': ['grey']}, case_id + '-observation-' + str(index)))
                proposed = stage('graph_propose', lambda: facade.graph_propose({
                    'schema': 'bridge.registered-domain-construction/1', 'domain_pack': domain,
                    'houdini_version': self.houdini_versions[0]}, case_id + '-proposal'))
                graph_id = proposed['graph_id']
                context['graph_id'] = graph_id
                trial = None
            budget = facade.manifest.get('trial_budget_seconds')
            if (type(budget) not in (int, float) or not math.isfinite(budget)
                    or not 0 < budget <= 120):
                raise DomainReadinessError('FORMAL_GRAPH_BUDGET_INVALID')
            deadline = time.monotonic() + budget
            if trial is None:
                trial = stage('graph_trial', lambda: facade.graph_trial(graph_id, case_id + '-trial'))
                trial = stage('graph_status', lambda: self._wait_for_construction(
                    facade, graph_id, case_id + '-trial', trial, deadline), operation_id=trial.get('operation_id'))
            construction = trial.get('result') or {}
            topology = construction.get('topology') or {}
            verification = construction.get('verification') or {}
            if (trial.get('graph_id') != graph_id
                    or construction.get('construction_executed') is not True
                    or construction.get('reconciliation_required') is not False
                    or not topology.get('root') or not topology.get('nodes')
                    or any(verification.get(name) is not True for name in
                           ('nodes_verified', 'parameters_verified', 'connections_verified'))):
                raise DomainReadinessError('FORMAL_GRAPH_TOPOLOGY_INCOMPLETE: verified construction readback is required')
            current = stage('graph_version', lambda: facade.graph_version(graph_id))
            version = current['version']
            if (type(version) is not int or version < 0 or current.get('state') != 'COMPLETE'
                    or current.get('task_id') != owner):
                raise DomainReadinessError('FORMAL_GRAPH_VERSION_MISSING: completed owned content is required')
            from .graph_catalog import compile_proposal
            registered = compile_proposal({'schema': 'bridge.registered-domain-construction/1',
                'domain_pack': domain, 'houdini_version': self.houdini_versions[0]}).to_dict()
            original = stage('compiled_graph', lambda: facade.jobs_service.compiled_graph(graph_id))
            if original != registered:
                raise DomainReadinessError('FORMAL_GRAPH_DOMAIN_VERSION_MISMATCH')
            context.update(graph_version=version, formal_controller_verified=True)
            saved = stage('task_save', facade.task_save)
            save_evidence = self._formal_saved_scene(saved, current, owner=owner, graph_id=graph_id, source=source,
                host_identity=getattr(facade.host_client, 'expected_identity', None))
            context.update(save_receipt=saved, initial_save_receipt=saved, typed_save_evidence=save_evidence)
            if save_evidence['typed_save_verified']:
                context['explicit_stage_gaps'].remove('typed_task_save')
            reopened = stage('task_reopen', lambda: facade.task_reopen(saved['saved_scene_id']))
            if reopened.get('path') != saved['path'] or reopened.get('sha256') != saved['sha256']:
                raise DomainReadinessError('FORMAL_REOPEN_CURRENT_HIP_MISMATCH')
            context['reopen_receipt'] = reopened
            initial_saved = saved
            feedback = None
            if scenario == 'approval_recovery' and recovery_input is None:
                raise DomainReadinessError('FORMAL_RECOVERY_NOT_EXECUTED: worker recovery requires its own evidence')
            if scenario == 'causal_candidate':
                if domain not in {'lighting_camera_render_v1', 'material_lookdev_v1'}:
                    raise DomainReadinessError('FORMAL_SEMANTIC_FEEDBACK_UNAVAILABLE: ' + domain)
                feedback = self._formal_feedback_controls(facade, domain, graph_id, topology, version, saved, stage, context)
                version, saved = feedback['graph_version'], feedback['save_receipt']
                context.update(feedback=feedback, graph_version=version, save_receipt=saved,
                    semantic_control_coverage=feedback['semantic_control_coverage'])
            targets = [path for address, path in topology['nodes'].items() if address.endswith('/render')]
            if len(targets) != 1:
                raise DomainReadinessError('FORMAL_RENDER_TARGET_MISSING: ' + domain)
            frames = [1, 3]
            pattern = str(Path(facade.save_root) / (case_id + '.%03d.exr'))
            submitted = stage('houdini_render_bounded', lambda: facade.houdini_render_bounded(
                case_id + '-render', saved['saved_scene_id'], targets[0], pattern, frames, 20.0),
                saved_scene_id=saved['saved_scene_id'])
            operation_id = submitted['operation_id']
            deadline = time.monotonic() + 25.0
            while True:
                queried = facade.operation_query(operation_id)
                if queried.get('operation', {}).get('state') not in {'QUEUED', 'PREPARED', 'STARTING', 'RUNNING'} or time.monotonic() >= deadline:
                    break
                time.sleep(.05)
            stage('operation_query', lambda: queried, operation_id=operation_id)
            fact = self._formal_producer_fact(queried, operation_id=operation_id, owner=owner,
                frames=frames, pattern=pattern, target=targets[0], saved=saved)
            context.update(execution_fact=fact, preview_operation=queried['operation'])
            context['output_metadata_status'] = fact.get('completion_metadata_status', 'NOT_RUN')
            context['output_metadata_missing_facts'] = fact.get('completion_metadata_missing_facts', [])
            colorspace, premultiplied = self._formal_output_encoding(fact, frames)
            artifact_id = case_id + '-input'
            artifact = self._formal_registration_retry(lambda attempt: stage(
                'register_render_artifact', lambda: facade.register_render_artifact(
                    artifact_id, 'confirmed_cache', pattern, frames, colorspace, premultiplied, operation_id),
                operation_id=operation_id, attempt=attempt))
            context['artifact'] = artifact
            consumed = stage('consume_artifact', lambda: facade.consume_artifact(artifact_id), operation_id=operation_id)
            if (artifact.get('operation_id') != operation_id or artifact.get('task_id') != owner
                    or artifact.get('dependencies') != saved['feedback_dependencies']
                    or consumed.get('usable_as_render_input') is not True
                    or consumed.get('artifact_id') != artifact_id
                    or consumed.get('operation_id') != operation_id
                    or consumed.get('pattern') != pattern
                    or (consumed.get('verification') or {}).get('frame_set') != frames
                    or consumed.get('operation_receipt_sha256') != fact['operation_receipt_sha256']):
                raise DomainReadinessError('FORMAL_ARTIFACT_UNUSABLE')
            binding = stage('nuke_input_binding', lambda: facade.nuke_client.render_binding(owner,
                str(Path(facade.save_root) / (case_id + '.comp.%03d.exr')), frames, colorspace, premultiplied,
                artifact_binding=consumed), operation_id=operation_id)
            if ((binding.get('input_binding') or {}).get('connection_verified') is not True
                    or binding.get('source') != 'controller' or binding.get('task_id') != owner
                    or binding.get('frames') != frames
                    or (binding.get('input_binding') or {}).get('owner_task_id') != owner
                    or (binding.get('input_binding') or {}).get('artifact_id') != artifact_id
                    or (binding.get('input_binding') or {}).get('read_path') != pattern
                    or (binding.get('input_binding') or {}).get('frame_set') != frames):
                raise DomainReadinessError('FORMAL_NUKE_INPUT_UNBOUND')
            return {'status': 'BLOCKED', 'formal_controller_verified': True, 'controller_task_id': owner,
                'formal_domain_lifecycle_verified': False,
                'blocker': 'FORMAL_SEMANTIC_CONTROL_COVERAGE_INCOMPLETE: ' + domain +
                    ' requires all semantic controls and applicable lifecycle evidence; render and binding alone are insufficient' +
                    ('; ' + '; '.join(feedback['semantic_blockers']) if feedback else ''),
                'graph_id': graph_id, 'graph_version': version, 'initial_save_receipt': initial_saved,
                'save_receipt': saved, 'feedback': feedback, 'preview_operation': queried['operation'],
                'execution_fact': fact, 'artifact': artifact, 'nuke_input_binding': binding,
                'semantic_control_coverage': feedback['semantic_control_coverage'] if feedback else [],
                'semantic_blockers': feedback['semantic_blockers'] if feedback else [],
                'recovery': context.get('recovery', {'tested': False}), 'stage_receipts': receipts,
                'boundary_kind': str(facade.host_client.boundary_kind)}

    def _houdini(self, domain, scenario, case_id, receipts):
        spec=self._spec(domain,case_id)
        recovery = {'tested': False}
        built=self._call(self.host_client,'agent.fx.build_preview',spec,receipts)
        scene=built.get('scene_manifest')
        if not isinstance(scene,dict) or scene.get('domain_pack')!=domain or scene.get('task_id')!=spec['task_id']:
            raise DomainReadinessError('build lacks exact task/domain manifest')
        nodes=scene.get('nodes')
        if not isinstance(nodes,dict) or not nodes:raise DomainReadinessError('build has no editable nodes')
        inspected={}
        for role,path in nodes.items():
            inspected[role]=self._call(self.host_client,'node.info',{'task_id':spec['task_id'],'path':path,'root_path':scene['execution_root']},receipts)
        connection_report=scene.get('connections',{})
        connections=connection_report.get('verified',[])
        declared_connections=connection_report.get('declared',[])
        if (declared_connections and not connections) or any(c.get('verified') is not True for c in connections):
            raise DomainReadinessError('declared connections have no complete native readback')
        plan=spec['constraints']['fx']['domain_control_plan']
        control_contract=self._control_contract(domain, plan, scene, nodes)
        saved=self._call(self.host_client,'scene.save_hip',{'task_id':spec['task_id'],'path':str(self.output_root/(case_id+'.hip')),'root_path':scene['execution_root']},receipts)
        if not saved.get('sha256'):raise DomainReadinessError('save has no content digest')
        reopened=self._call(self.host_client,'scene.reopen_task_hip',{'task_id':spec['task_id'],'path':saved.get('path'),'sha256':saved['sha256']},receipts)
        for role,path in nodes.items():
            after=self._call(self.host_client,'node.info',{'task_id':spec['task_id'],'path':path,'root_path':scene['execution_root']},receipts)
            if after!=inspected[role]:raise DomainReadinessError('reopened editable structure differs: '+role)
        feedback=None
        if scenario=='causal_candidate':
            pack=self.registry.get(domain,'1.0.0')
            changes={item['name']: self._candidate_value(pack.control_map[item['name']], item['value'])
                     for item in plan['controls']}
            changed=json.loads(json.dumps(spec))
            changed['constraints']['fx']['changes']=changes
            patched=self._call(self.host_client,'agent.fx.apply_candidate',changed,receipts)
            diffs=patched.get('parameter_diff')
            expected_names=set(changes)
            if (not isinstance(diffs,list) or {item.get('semantic_control') for item in diffs} != expected_names
                    or any(item.get('readback_verified') is not True for item in diffs)
                    or not patched.get('invalidates_from')):
                raise DomainReadinessError('feedback does not read back every semantic control')
            observed_scopes={item['name']: item['observed_invalidation_scope'] for item in control_contract['controls']}
            for diff in diffs:
                name=str(diff.get('semantic_control') or '')
                if str(diff.get('node') or '') == '' or not str(diff.get('node')).startswith('/'):
                    raise DomainReadinessError('feedback lacks native parameter path: ' + name)
                if str(diff.get('invalidates_from') or '') != observed_scopes.get(name):
                    raise DomainReadinessError('feedback invalidation scope drifted: ' + name)
            feedback={'parameter_diff':diffs,'invalidates_from':sorted(set(observed_scopes.values())),
                      'all_controls_verified':True,'control_contract':control_contract}
        if scenario=='approval_recovery':
            recover=getattr(self.host_client,'recover_owned_worker',None)
            if not callable(recover):
                raise DomainReadinessError('RECOVERY_NOT_EXECUTED: requires owned-worker crash and supervised restart fixture')
            recovery_output=self.output_root/(case_id+'.recovery.json')
            recovery=recover(spec['task_id'], domain=domain, scene_path=saved.get('path'),
                             scene_sha256=saved.get('sha256'), operation_id=case_id+'.recovery',
                             spec=spec, output_path=recovery_output)
            receipts.append({'operation':'owned_worker_recovery','result':recovery})
            if not isinstance(recovery,dict) or recovery.get('tested') is not True:
                raise DomainReadinessError('RECOVERY_NOT_EXECUTED: supervised restart evidence is incomplete')
        assessment=scene.get('execution_assessment',{})
        if assessment.get('domain_graph_constructed') is not True:
            raise DomainReadinessError('DOMAIN_GRAPH_INCOMPLETE: no verified native domain graph contract')
        # The lighting pack is a Solaris/LOP graph.  Its software boundary
        # verifies the editable render chain and persistence, but does not
        # pretend that a LOP node is a SOP simulation output.  Real Karma
        # execution remains a separate host/visual gate.
        if domain in {'lighting_camera_render_v1','material_lookdev_v1'}:
            terminal_role = 'render' if domain == 'lighting_camera_render_v1' else 'material'
            terminal_path = str(nodes.get(terminal_role) or '')
            if not terminal_path or terminal_role not in inspected:
                raise DomainReadinessError('DOMAIN_GRAPH_INCOMPLETE: terminal node readback is missing')
            boundary_output=self.output_root/(case_id+'.software-boundary.json')
            if scenario == 'approval_recovery':
                diagnostic_execution=recovery.get('domain_execution')
            else:
                diagnostic_execution=self._call(self.host_client,'agent.fx.software_boundary_execute',{
                    'task_id':spec['task_id'], 'operation_id':case_id+'.diagnostic',
                    'domain_pack':domain, 'constraints':dict(spec.get('constraints') or {}),
                    'frames':[1,2], 'output_path':str(boundary_output),
                },receipts)
            preparation = {
                'terminal_node':terminal_path,
                'terminal_node_readback':inspected[terminal_role],
                'software_boundary_execution':'diagnostic_only',
                'diagnostic_execution':diagnostic_execution,
                'formal_render_entry':'not_available',
                'real_native_execution_verified':False,
            }
            if domain == 'lighting_camera_render_v1':
                preparation['real_karma_verified']=False
            raise DomainReadinessError('FORMAL_RENDER_OUTPUT_ENTRY_UNAVAILABLE: material/lighting software diagnostic is not a render acceptance')
        preview=dict(spec,request_id=case_id+'.preview',budget_seconds=120)
        submitted=self._call(self.host_client,'agent.fx.simulate_segment',preview,receipts)
        operation_id=submitted.get('operation_id')
        if not operation_id:raise DomainReadinessError('preview did not persist an operation')
        drain=getattr(self.host_client,'drain',None)
        if callable(drain):drain(spec['task_id'],operation_id)
        status=self._call(self.host_client,'operation.status',{'task_id':spec['task_id'],'operation_id':operation_id},receipts)
        operation=status.get('operation',{})
        fact=operation.get('lifecycle_fact',{})
        if operation.get('state')!='COMPLETED' or operation.get('frames_done')!=[1,2]:
            raise DomainReadinessError('bounded preview did not complete both frames')
        if fact.get('kind')!='STOP_CONFIRMED' or fact.get('stop_confirmed') is not True:
            raise DomainReadinessError('preview has no trusted terminal stop fact')
        if [item.get('frame') for item in operation.get('evidence',[])]!=[1,2]:
            raise DomainReadinessError('preview lacks per-frame native boundary evidence')
        evidence=self._call(self.host_client,'agent.fx.collect_evidence',spec,receipts)
        return {'status':'PASS','save_receipt':saved,'reopen_receipt':reopened,'stage_receipts':receipts,
                'domain_output_evidence':evidence,'preview_operation':operation,'recovery':recovery}

    @staticmethod
    def _require_gate(response, name):
        gates = response.get('gates') if isinstance(response, dict) else None
        matching = [gate for gate in gates or [] if isinstance(gate, dict) and gate.get('name') == name]
        if not matching or any(gate.get('passed') is not True for gate in matching):
            raise DomainReadinessError('NUKE_GATE_FAILED: ' + str(name))

    def _nuke_lifecycle(self, spec, scenario, case_id, receipts):
        """Run one composite through graph, persistence, feedback and render gates."""
        constraints = dict(spec.get('constraints') or {})
        controls = dict(constraints.get('composite_controls') or {})
        controls.setdefault('blur_size', 0.5)
        constraints['composite_controls'] = controls
        spec = dict(spec)
        spec['constraints'] = constraints
        spec['schema_version'] = '2.0'
        render = dict(spec.get('render') or {})
        render['output_dir'] = str(self.output_root / (case_id + '-nuke'))
        render.setdefault('frame_range', {'start': 1, 'end': 2, 'step': 1})
        spec['render'] = render

        built = self._call(self.nuke_client, 'agent.nuke.composite.build_graph', spec, receipts)
        if not isinstance(built.get('graph'), dict):
            raise DomainReadinessError('NUKE_GRAPH_INCOMPLETE: composite graph receipt is missing')
        self._require_gate(built, 'editable_native_composite_graph')
        audit = self._call(self.nuke_client, 'agent.nuke.composite.audit_lineage', spec, receipts)
        self._require_gate(audit, 'reference_isolated_from_final_write')

        script_path = self.output_root / (case_id + '.nk')
        saved = self._call(self.nuke_client, 'save_script', {
            'path': str(script_path), 'overwrite': True,
        }, receipts)
        if not script_path.is_file():
            raise DomainReadinessError('NUKE_SAVE_MISSING: saved software snapshot is unavailable')
        script_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
        saved = {**saved, 'sha256': script_sha256, 'bytes': script_path.stat().st_size}
        try:
            snapshot_payload=json.loads(script_path.read_text(encoding='utf-8'))
            output_pattern=str((built.get('graph') or {}).get('final_pattern') or '')
            if not output_pattern:
                output_pattern=next(
                    (str(node.get('file') or '') for node in (snapshot_payload.get('nodes') or {}).values()
                     if isinstance(node, dict) and node.get('class') == 'Write' and node.get('file')),
                    '',
                )
        except (OSError, ValueError, AttributeError):
            output_pattern=''
        if not output_pattern:
            raise DomainReadinessError('NUKE_OUTPUT_BINDING_MISSING: saved Write pattern is unavailable')
        reopened = self._call(self.nuke_client, 'open_script', {
            'path': str(script_path), 'sha256': script_sha256,
        }, receipts)
        if reopened.get('registry_cache_invalidated') is not True:
            raise DomainReadinessError('NUKE_REOPEN_CACHE_NOT_INVALIDATED')
        rebuilt = self._call(self.nuke_client, 'agent.nuke.composite.build_graph', spec, receipts)
        if rebuilt.get('restored') is not True or not isinstance(rebuilt.get('graph'), dict):
            raise DomainReadinessError('NUKE_REOPEN_STATE_NOT_RESTORED')

        feedback = None
        if scenario == 'causal_candidate':
            patch = dict(spec)
            patch['step_params'] = {'patch': {'controls': {'blur_size': 1.5}}}
            feedback = self._call(self.nuke_client, 'agent.nuke.composite.apply_patch', patch, receipts)
            self._require_gate(feedback, 'composite_patch_applied')
            self._require_gate(feedback, 'reference_isolated_from_final_write')

        recovery = {'tested': False, 'software_boundary_only': True}
        if scenario == 'approval_recovery':
            recover = getattr(self.nuke_client, 'recover_owned_worker', None)
            if not callable(recover):
                raise DomainReadinessError('RECOVERY_NOT_EXECUTED: requires owned-worker crash and supervised Nuke reopen')
            write_node = str(((rebuilt.get('graph') or {}).get('graph_nodes') or {}).get('final_write') or '')
            recovery = recover(spec['task_id'], str(script_path), script_sha256,
                               spec=spec, output_pattern=output_pattern,
                               operation_id=case_id+'.recovery', write_node=write_node)
            receipts.append({'operation': 'owned_worker_recovery', 'result': recovery})
            if not isinstance(recovery, dict) or recovery.get('tested') is not True:
                raise DomainReadinessError('RECOVERY_NOT_EXECUTED: supervised Nuke restart evidence is incomplete')
            recovered = self._call(self.nuke_client, 'agent.nuke.composite.build_graph', spec, receipts)
            if recovered.get('restored') is not True:
                raise DomainReadinessError('NUKE_RECOVERY_STATE_NOT_RESTORED')
            rebuilt = recovered

        preview_params = dict(spec)
        preview_params['step_params'] = {'frame': 1, 'variant_id': 'base'}
        preview = self._call(self.nuke_client, 'agent.nuke.composite.render_preview', preview_params, receipts)
        self._require_gate(preview, 'composite_preview_rendered')
        preview_verification = self._call(self.nuke_client, 'agent.nuke.composite.verify_preview', spec, receipts)
        self._require_gate(preview_verification, 'composite_preview_artifact')

        final = self._call(self.nuke_client, 'agent.nuke.composite.render_final', spec, receipts)
        self._require_gate(final, 'composite_final_rendered')
        final_verification = self._call(self.nuke_client, 'agent.nuke.composite.verify_final', spec, receipts)
        self._require_gate(final_verification, 'composite_final_artifacts')
        self._require_gate(final_verification, 'reference_isolated_from_final_write')
        delivered = self._call(self.nuke_client, 'agent.nuke.composite.deliver', spec, receipts)
        self._require_gate(delivered, 'editable_composite_script')
        self._require_gate(delivered, 'reference_isolated_from_final_write')
        return {
            'status': 'PASS',
            'save_receipt': saved,
            'reopen_receipt': reopened,
            'reopened_graph': rebuilt,
            'feedback_receipt': feedback,
            'preview': {'render': preview, 'verification': preview_verification},
            'final': {'render': final, 'verification': final_verification},
            'delivery': delivered,
            'recovery': recovery,
            'stage_receipts': receipts,
            'software_boundary_execution': 'completed',
            'real_native_execution_verified': False,
            'visual_verified': False,
        }

    def _nuke(self, domain, scenario, case_id, receipts):
        # Use the production graph builder, which validates registered input
        # lineage and native colors/knobs. Never assume Read1/Write1 exist.
        spec = self._spec(domain, case_id)
        prepare = getattr(self.nuke_client, 'prepare_input_artifact', None)
        if not callable(prepare) or self.artifact_registry is None:
            # Preserve the negative transport proof: an empty success response
            # still reaches the real graph command before being rejected.
            self._call(self.nuke_client, 'agent.nuke.composite.build_graph', spec, receipts)
            raise DomainReadinessError('NUKE_INPUT_ARTIFACT_NOT_BOUND: controller artifact registry is required')
        artifact_id = prepare(spec['task_id'], frames=[1, 2])
        entry = self.artifact_registry.lookup(str(artifact_id)) if callable(getattr(self.artifact_registry, 'lookup', None)) else None
        if not isinstance(entry, dict):
            raise DomainReadinessError('NUKE_INPUT_ARTIFACT_NOT_REGISTERED: controller ledger has no input')
        from dcc_task_runtime.artifact_registry import frame_path
        frame_manifest = []
        snapshots = (entry.get('payload') or {}).get('completion_snapshot') or {}
        for frame in entry.get('frame_set') or []:
            snapshot = snapshots.get(str(frame), snapshots.get(int(frame), {}))
            frame_manifest.append({'frame': int(frame), 'path': str(frame_path(entry['pattern'], int(frame))),
                                   'sha256': str(snapshot.get('sha256') or '')})
        manifest_payload = [{'index': index, 'frame': item['frame'], 'uri': str(Path(item['path']).resolve()),
                            'sha256': item['sha256'], 'bytes': Path(item['path']).stat().st_size}
                           for index, item in enumerate(frame_manifest)]
        manifest_sha = hashlib.sha256(json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True,
                                                 separators=(',', ':')).encode('utf-8')).hexdigest()
        spec = dict(spec)
        spec['inputs'] = [{'asset_id': str(artifact_id), 'role': 'effect_render', 'path': entry['pattern'],
                           'frames': frame_manifest, 'sha256': manifest_sha}]
        return self._nuke_lifecycle(spec, scenario, case_id, receipts)

    def _composite_dataflow(self, identifier, dependencies):
        receipts = []
        upstream_attempts = []
        try:
            if self.case_facade_factory is not None:
                raise DomainReadinessError('FORMAL_COMPOSITE_DATAFLOW_UNAVAILABLE: ' + identifier +
                    ' requires registered upstream producers in a shared downstream controller')
            if self.artifact_registry is None or not callable(getattr(self.host_client, 'call', None)):
                raise DomainReadinessError('COMPOSITE_INPUT_NOT_BOUND: controller artifact route is required')
            produced = []
            upstream_dependencies = [name for name in dependencies if name != 'nuke_composite_v1']
            for index, domain in enumerate(upstream_dependencies):
                upstream_task = self.task_id + '-' + identifier + '-upstream-' + domain
                upstream_case = identifier + '-upstream-' + domain
                upstream_spec = self._spec(domain, upstream_case)
                upstream_spec['task_id'] = upstream_task
                output_pattern = str(self.output_root / (upstream_case + '.%03d.exr'))
                upstream_spec['render'] = {'frame_range': {'start': 1, 'end': 2, 'step': 1}}
                build = self._call(self.host_client, 'agent.fx.build_preview', upstream_spec, receipts)
                attempt = {'domain': domain, 'task_id': upstream_task,
                           'operation_id': upstream_case + '.upstream',
                           'build': build}
                upstream_attempts.append(attempt)
                execution = self._call(self.host_client, 'agent.fx.software_boundary_execute', {
                    'task_id': upstream_task, 'operation_id': upstream_case + '.upstream',
                    'domain_pack': domain, 'constraints': dict(upstream_spec.get('constraints') or {}),
                    'frames': [1, 2], 'output_pattern': output_pattern,
                    'dependency_artifacts': list(produced),
                }, receipts)
                attempt['execution'] = execution
                if execution.get('formal_operation') is not True:
                    raise DomainReadinessError('COMPOSITE_FORMAL_UPSTREAM_OUTPUT_UNAVAILABLE: ' + domain)
                fact_reader = getattr(self.host_client, 'operation_fact', None)
                fact = fact_reader(upstream_case + '.upstream', upstream_task) if callable(fact_reader) else None
                if not isinstance(fact, dict) or fact.get('state') != 'COMPLETED':
                    raise DomainReadinessError('COMPOSITE_UPSTREAM_OPERATION_FACT_MISSING: ' + domain)
                attempt['operation_fact'] = fact
                artifact_id = 'upstream-' + ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in upstream_case)
                old_source = getattr(self.artifact_registry, '_operation_source', None)
                self.artifact_registry.set_operation_source(lambda operation_id, _fact=fact: _fact if operation_id == fact.get('operation_id') else (old_source(operation_id) if callable(old_source) else None))
                entry = self.artifact_registry.register(
                    artifact_id=artifact_id, task_id=upstream_task, artifact_class='confirmed_cache',
                    pattern=output_pattern, frame_set=[1, 2], colorspace='scene_linear',
                    premultiplied=False, dependencies=[str(item.get('artifact_id')) for item in produced],
                    operation_id=upstream_case + '.upstream',
                    operation_receipt_sha256=str(fact.get('operation_receipt_sha256') or ''),
                    payload={'producer_domain': domain, 'formal_operation': True},
                )
                produced.append({'artifact_id': artifact_id, 'version': entry.get('version'),
                                 'operation_id': upstream_case + '.upstream',
                                 'pattern': output_pattern})
            raise DomainReadinessError('COMPOSITE_FORMAL_RENDER_OUTPUT_ENTRY_UNAVAILABLE')
        except Exception as exc:
            return {
                'case_id': identifier,
                'status': 'BLOCKED',
                'execution': None,
                'blocker': str(exc),
                'dependencies': list(dependencies),
                'upstream_attempts': upstream_attempts,
                'stage_receipts': receipts,
                'dataflow': {'declared_dependencies': list(dependencies),
                             'registered_upstream_artifacts': list(produced) if 'produced' in locals() else [],
                             'formal_route_required': True, 'software_boundary_only': True},
                'real_dcc_verified': False,
                'visual_verified': False,
            }

    def run_case(self, domain, scenario):
        if domain not in DOMAIN_IDS or scenario not in SCENARIOS:raise DomainReadinessError('unknown readiness case')
        case_id=domain+'__'+scenario;receipts=[];context={}
        app='nuke' if domain=='nuke_composite_v1' else 'houdini'
        try:
            if self.case_facade_factory is not None:
                result = (self._formal_nuke if app == 'nuke' else self._formal_domain)(
                    domain, scenario, case_id, receipts, context)
            else:
                result=(self._nuke if app=='nuke' else self._houdini)(domain,scenario,case_id,receipts)
        except Exception as exc:
            result={'status':'BLOCKED','blocker':str(exc),'error_type':type(exc).__name__,'stage_receipts':receipts,
                    'recovery':context.get('recovery', {'tested':False})}
        result = {**context, **result}
        result.setdefault('formal_controller_verified', False)
        if self.case_facade_factory is None and result.get('status') == 'PASS':
            result.update(status='BLOCKED', diagnostic_status='PASS',
                blocker='FORMAL_CASE_FACADE_REQUIRED: diagnostic execution is not domain acceptance')
        result.update(real_dcc_verified=False,visual_verified=False,case_execution=(
            'prepared_production_controller' if self.case_facade_factory is not None
            else 'diagnostic_domain_dispatch'))
        return ReadinessCase(case_id,domain,scenario,app,result.pop('boundary_kind',self.boundary_kind),result)

    def run_all(self):
        cases=[self.run_case(domain,scenario).to_dict() for domain in DOMAIN_IDS for scenario in SCENARIOS]
        composites=[self._composite_dataflow(identifier, deps) for identifier, deps in [
            ('composite__explosion_components', ['pyro_smoke_v1', 'pyro_fire_v1', 'particles_v1', 'nuke_composite_v1']),
            ('composite__nuke_delivery', ['rbd_destruction_v1', 'procedural_geometry_v1', 'material_lookdev_v1',
                                          'lighting_camera_render_v1', 'nuke_composite_v1']),
        ]]
        return {'schema':'bridge.full_readiness.domain_cases/2.0','boundary_kind':self.boundary_kind,
                'case_count':len(cases),'cases':cases,'composites':composites,'required_case_count':48,
                'required_composite_count':2,'real_dcc_verified':False,'visual_verified':False,
                'software_preparation_status':'PASS' if all(c['status']=='PASS' for c in cases+composites) else 'NOT_READY'}
