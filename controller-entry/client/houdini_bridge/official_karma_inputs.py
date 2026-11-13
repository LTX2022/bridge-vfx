"""Derive sealed case inputs under the first frozen controller manifest.

Only declared files are created. The scope, runtime bindings and initial run.json
are never rewritten. Every consumer reauthenticates the signed native originals.
"""
from __future__ import annotations
import copy
from pathlib import Path

from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_RESOURCE_PROFILE
from dcc_task_runtime.render_profiles import OFFICIAL
from .official_karma import VERSION, canonical_sha256
from .official_karma_observation import (file_record, checked_bytes, load_record, write_new, read_sealed,
                                         require_frozen_sources)
from .official_karma_scene import SCHEMA as SCENE_SCHEMA, DOMAIN, validate_configuration

SCHEMA='bridge.official-karma-derived-inputs/1'
RULE_SCHEMA='bridge.official-karma-derivation-rule/1'


def derivation_rule(root):
    root=Path(root)
    control=root/'project/control'
    return {'schema':RULE_SCHEMA,'configuration_path':str(root/'frozen-inputs/official-scene.json'),
        'manifest_path':str(control/'official-run.json'),'seal_path':str(control/'official-seal.json'),
        'binding_path':str(control/'official-derived-inputs.json'),
        'output_image':str(root/'project/saves/main.0001.exr')}


def frozen_context(template_path, runtime_bindings):
    bindings=load_record(runtime_bindings)
    scope=NativeScope({'path':str(Path(template_path).parents[2]/'scope.json'),
                       'sha256':bindings['scope_sha256']})
    root=scope.root
    if (scope.resource_profile!=OFFICIAL_RESOURCE_PROFILE
            or scope.scope.get('scene_profile')!=OFFICIAL or scope.scope.get('evidence_source')!='real_host'
            or bindings.get('evidence_source')!='real_host' or 'software_native_boundaries' in scope.scope
            or runtime_bindings['path']!=str(root/'runtime-bindings.json')
            or Path(template_path)!=root/'project/control/run.json'):
        raise ValueError('OFFICIAL_DERIVATION_FROZEN_SCOPE_REQUIRED')
    case=scope.scope['official_case']
    require_frozen_sources(case)
    for name in ('source_contract','static_review','source_hip'): checked_bytes(case[name])
    for record in case['source_files']: checked_bytes(record)
    expected=bindings['project_files']['manifest']
    if expected['path']!=str(template_path):
        raise ValueError('OFFICIAL_DERIVATION_TEMPLATE_PATH_MISMATCH')
    template=load_record(expected)
    rule=derivation_rule(root)
    if (case.get('derivation')!=rule or template.get('official_case_derivation')!=rule
            or template.get('domain_pack')!=DOMAIN or 'construction_input_manifest' in template
            or template.get('application')!='pipeline'
            or template.get('construction_authorized') is not True
            or template.get('execution_authorized') is not True
            or template.get('render_authorized') is not True
            or template.get('simulation_authorized') is not False
            or template.get('cache_authorized') is not False):
        raise ValueError('OFFICIAL_DERIVATION_TEMPLATE_INVALID')
    for path in rule.values():
        if path==RULE_SCHEMA: continue
        candidate=Path(path)
        if candidate!=candidate.resolve() or any(p.is_symlink() for p in (candidate,*candidate.parents)):
            raise ValueError('OFFICIAL_DERIVATION_PATH_INVALID')
    return scope,bindings,expected,template,rule


def derived_values(scope,template,seal):
    case=scope.scope['official_case']; rule=derivation_rule(scope.root)
    observed=read_sealed(seal,expected_scope=scope.binding)
    configuration=validate_configuration({'schema':SCENE_SCHEMA,'profile':OFFICIAL,
        'supported_versions':[VERSION],'source_contract':case['source_contract'],
        'native_scope':scope.binding,'sealed_observation':seal,
        'scene':{'engine':'Karma CPU','resolution':[420,300],'frames':[1],
                 'output_image':rule['output_image']}},VERSION)
    return configuration,canonical_sha256(observed)


def _manifest(template,record):
    value=copy.deepcopy(template)
    value['construction_input_manifest']=[{'index':0,'asset_id':'sealed-official-karma-disklight',
        'semantic_role':'render_scene_configuration','source_uri':record['path'],
        'bytes':record['bytes'],'sha256':record['sha256']}]
    return value


def materialize(template_path,runtime_bindings,seal):
    scope,bindings,template_record,template,rule=frozen_context(template_path,runtime_bindings)
    if (scope.scope.get('execution_authorized') is not True
            or scope.scope.get('status')!='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION'):
        raise ValueError('OFFICIAL_DERIVATION_EXECUTION_AUTHORIZATION_REQUIRED')
    scope.check()
    state=scope.snapshot()
    expected={'official-open-save','official-cold-export','official-husk'}
    if (len(state['tickets'])!=3 or {t['role'] for t in state['tickets']}!=expected
            or any(t.get('stopped_at') is None for t in state['tickets'])):
        raise ValueError('OFFICIAL_DERIVATION_THREE_STOPPED_ORIGINALS_REQUIRED')
    configuration,observation_sha=derived_values(scope,template,seal)
    for name in ('configuration_path','manifest_path','seal_path','binding_path'):
        if Path(rule[name]).exists():
            raise ValueError('OFFICIAL_DERIVATION_ALREADY_EXISTS_QUERY_REQUIRED')
    # A partial write is deliberately not replayed. The stage journal keeps INTENT.
    seal_record=write_new(rule['seal_path'],seal)
    configuration_record=write_new(rule['configuration_path'],configuration)
    manifest_record=write_new(rule['manifest_path'],_manifest(template,configuration_record))
    result={'schema':SCHEMA,'scope_binding':scope.binding,'runtime_bindings':runtime_bindings,
        'template':template_record,'seal':seal_record,'configuration':configuration_record,
        'manifest':manifest_record,'observation_sha256':observation_sha}
    result_record=write_new(rule['binding_path'],result)
    resolve_manifest(template_path,runtime_bindings)
    return result_record


def resolve_manifest(template_path,runtime_bindings):
    scope,bindings,template_record,template,rule=frozen_context(template_path,runtime_bindings)
    result=load_record(file_record(rule['binding_path']))
    if (type(result) is not dict or set(result)!={'schema','scope_binding','runtime_bindings','template',
            'seal','configuration','manifest','observation_sha256'} or result['schema']!=SCHEMA
            or result['scope_binding']!=scope.binding or result['runtime_bindings']!=runtime_bindings
            or result['template']!=template_record):
        raise ValueError('OFFICIAL_DERIVED_INPUT_BINDING_MISMATCH')
    for name in ('seal','configuration','manifest'):
        if result[name]['path']!=rule[name+'_path']:
            raise ValueError('OFFICIAL_DERIVED_INPUT_PATH_MISMATCH')
    seal=load_record(result['seal'])
    expected,observation_sha=derived_values(scope,template,seal)
    configuration=load_record(result['configuration'])
    manifest=load_record(result['manifest'])
    if (configuration!=expected or observation_sha!=result['observation_sha256']
            or manifest!=_manifest(template,result['configuration'])):
        raise ValueError('OFFICIAL_DERIVED_INPUT_CONTENT_MISMATCH')
    return Path(result['manifest']['path'])
