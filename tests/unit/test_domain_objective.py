from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest
from dcc_task_runtime.domain_objective import (DomainVisualObjective, DomainControlPlan, REQUIRED_CONTROLS)
from dcc_task_runtime.domains import builtin_domain_registry
from dcc_task_runtime.errors import RuntimeV2Error
from dcc_task_runtime.visual_objective import MediaManifest, MediaAsset, SemanticValue, parse_visual_objective
from houdini_bridge.domain_packs import get_domain_pack, validate_candidate_patch

ROOT = Path(__file__).resolve().parents[2]

def objective(domain):
    pack = builtin_domain_registry().get(domain,'1.0.0')
    controls=[]
    for name in REQUIRED_CONTROLS[domain]:
        c=pack.control_map[name]
        value=max(c.minimum or 0,0.5)
        if c.value_type=='int':value=max(1,int(c.minimum or 1))
        elif c.value_type=='bool':value=True
        elif c.value_type=='color3':value=(0.5,0.5,0.5)
        controls.append((name,SemanticValue(value,'observed',0.9,'synthetic-reference.'+name)))
    return DomainVisualObjective(domain,MediaManifest((MediaAsset('synthetic-ref','image','file:///synthetic.png','a'*64),)),tuple(controls))

class DomainObjectiveTests(unittest.TestCase):
    def test_all_domains_roundtrip_unique_controls_and_provenance(self):
        for domain in REQUIRED_CONTROLS:
            with self.subTest(domain=domain):
                obj=objective(domain);plan=obj.source_plan().require_ready()
                self.assertEqual(parse_visual_objective(obj.to_dict()),obj)
                self.assertEqual(DomainControlPlan.from_mapping(plan.to_dict()).plan_sha256,plan.plan_sha256)
                self.assertEqual(set(c['name'] for c in plan.to_dict()['controls']),set(REQUIRED_CONTROLS[domain]))
                self.assertTrue(all(c['provenance']=='observed' for c in plan.to_dict()['controls']))
    def test_missing_values_are_unknown_and_block_execution(self):
        for domain in REQUIRED_CONTROLS:
            obj=objective(domain)
            missing=DomainVisualObjective(domain,obj.media_manifest,())
            self.assertFalse(missing.source_plan().ready)
            self.assertEqual(set(missing.missing_semantics),set(REQUIRED_CONTROLS[domain]))
            with self.assertRaises(RuntimeV2Error):missing.source_plan().require_ready()
    def test_tampered_plan_cannot_change_owner_value_or_invalidation(self):
        for field,value in [('ready',False),('domain_pack','water_flip_v1'),('objective_sha256','b'*64),('media_manifest_sha256','b'*64)]:
            raw=objective('procedural_geometry_v1').source_plan().to_dict();raw[field]=value
            with self.assertRaises(RuntimeV2Error):DomainControlPlan.from_mapping(raw)
        raw=objective('procedural_geometry_v1').source_plan().to_dict();raw['controls'][0]['invalidates_stage_nodes']=[]
        with self.assertRaises(RuntimeV2Error):DomainControlPlan.from_mapping(raw)
    def test_no_raw_parameter_or_unknown_control(self):
        obj=objective('procedural_geometry_v1');raw=obj.to_dict();raw['controls']['file']=SemanticValue('/tmp/evil','default').to_dict()
        with self.assertRaises(RuntimeV2Error):parse_visual_objective(raw)
    def test_native_and_runtime_reject_nonfinite_fractional_integer_and_boolean_numeric(self):
        runtime=builtin_domain_registry().get('procedural_geometry_v1','1.0.0')
        native=get_domain_pack('procedural_geometry_v1')
        for bad in (float('nan'),float('inf'),True,'0.3'):
            with self.assertRaises((RuntimeV2Error,ValueError)):runtime.control_map['scale'].validate(bad)
            with self.assertRaises(ValueError):validate_candidate_patch(native,{'scale':bad})
        for bad in (2.5,True,'2'):
            with self.assertRaises(ValueError):validate_candidate_patch(native,{'scatter_density':bad})
    def test_nuke_controls_keep_nuke_owner(self):
        plan=objective('nuke_composite_v1').source_plan()
        self.assertEqual(plan.controls_for_application('houdini'),{})
        self.assertEqual(set(plan.controls_for_application('nuke')),{'blur_size','premult'})
    def test_host_consumes_exact_domain_and_input_binding(self):
        spec=importlib.util.spec_from_file_location('_domain_objective_host',ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py')
        addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
        plan=objective('procedural_geometry_v1').source_plan()
        fx={'domain_pack':plan.domain_pack,'domain_control_plan':plan.to_dict(),'domain_control_plan_sha256':plan.plan_sha256}
        params={'constraints':{'fx':fx},'inputs':[{'asset_id':'synthetic-ref','sha256':'a'*64}]}
        result=addon._fx_domain_control_binding(params,plan.domain_pack,addon._FX_PACKS[plan.domain_pack])
        self.assertEqual(result['host_controls'],plan.controls_for_application('houdini'))
        fx['domain_control_plan_sha256']='b'*64
        with self.assertRaises(addon.BridgeCommandError):addon._fx_domain_control_binding(params,plan.domain_pack,addon._FX_PACKS[plan.domain_pack])
        fx['domain_control_plan_sha256']=plan.plan_sha256;params['inputs']=[]
        with self.assertRaises(addon.BridgeCommandError):addon._fx_domain_control_binding(params,plan.domain_pack,addon._FX_PACKS[plan.domain_pack])
