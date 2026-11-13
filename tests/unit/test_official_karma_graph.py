"""Registered official capability and bounded HIP policy; no DCC execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from dcc_task_runtime import native_scope
from dcc_task_runtime.render_profiles import OFFICIAL
from houdini_bridge import native_render_scene, official_karma_scene as case
from houdini_bridge import operation_receipts as receipts
from vfx_pipeline import graph_catalog
from vfx_pipeline.graph_job_worker import GraphJobWorker
from dcc_task_runtime.canonical import canonical_sha256
import test_native_scope as scope_fixture
import test_scene_contract_header as contract_fixture

ROOT=Path(__file__).resolve().parents[2]


class OfficialGraphTests(unittest.TestCase):
    def selector(self):
        return {'schema':'bridge.registered-domain-construction/1','domain_pack':case.DOMAIN,
                'houdini_version':'21.0.631','scene_profile':OFFICIAL}

    def configuration(self,root):
        return {'schema':case.SCHEMA,'profile':OFFICIAL,'supported_versions':['21.0.631'],
            'source_contract':{'path':str(root/'source.json'),'bytes':100,'sha256':'a'*64},
            'native_scope':{'path':str(root/'scope.json'),'sha256':'b'*64},
            'sealed_observation':{'directory':str(root/'cold'),'identity':{'task':'fixture'},'sha256':'c'*64},
            'scene':{'engine':'Karma CPU','resolution':[420,300],'frames':[1],
                     'output_image':str(root/'project/saves/main.0001.exr')}}

    def test_registered_case_contains_original_sops_and_has_no_material_fallback(self):
        graph=graph_catalog.compile_proposal(self.selector())
        self.assertEqual(len(graph.nodes),35)
        self.assertEqual(len(graph.connections),30)
        self.assertEqual(graph_catalog.registered_domain_identity(graph),self.selector())
        types={graph_catalog.native_binding(n.node_type).native_type for n in graph.nodes}
        self.assertFalse(types & {'sphere','materiallibrary','mtlxstandard_surface','assignmaterial'})
        self.assertIn('karmarenderproperties',types)
        self.assertIn('polyextrude::2.0',types)
        self.assertEqual(sum(n.context=='houdini_sop' for n in graph.nodes),22)
        schedule=graph_catalog.bounded_domain_schedule(graph)
        self.assertEqual(schedule['node_count'],35)
        self.assertEqual(graph_catalog.execution_diagnostics(graph),[])
        # The HDA's material-free chain is SOP import -> payload -> transform.
        _,wires=case.layout('21.0.631')
        pairs={(w['source_role'],w['destination_role']) for w in wires}
        self.assertTrue({('geometry_import','geometry_payloadinfo'),('geometry_payloadinfo','geometry_transform'),
                         ('geometry_transform','camera')} <= pairs)
        for mutate in ({'houdini_version':'22.0.459'},{'domain_pack':'material_lookdev_v1'},
                       {'nodes':[]}):
            selector=self.selector();selector.update(mutate)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError): graph_catalog.compile_proposal(selector)

    def test_schema_does_not_accept_a_relabelled_old_sphere_scene(self):
        old=json.loads((ROOT/'docs/official-baselines/karma/frozen-scene-v2.json').read_text())
        old['profile']=OFFICIAL
        with self.assertRaises(ValueError): native_render_scene.validate_configuration(old,'21.0.631')
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            config=self.configuration(Path(directory).resolve())
            self.assertEqual(native_render_scene.validate_configuration(config,'21.0.631'),config)
            with self.assertRaises(ValueError): native_render_scene.parameter_plan(config,'21.0.631')
            for mutate in (lambda c:c['scene'].update(resolution=[128,128]),
                           lambda c:c['scene'].update(frames=[True]),lambda c:c.pop('sealed_observation'),
                           lambda c:c.update(supported_versions=['21.0.631','22.0.459'])):
                bad=copy.deepcopy(config);mutate(bad)
                with self.assertRaises(ValueError): native_render_scene.validate_configuration(bad,'21.0.631')

    def test_worker_accepts_only_the_paired_sealed_case_domain_and_input(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            root=Path(directory).resolve();p=root/'case.json';p.write_text(json.dumps(self.configuration(root)))
            record={'index':0,'asset_id':'official-case','semantic_role':'render_scene_configuration',
                'source_uri':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for selector,inputs,accepted in ((self.selector(),[record],True),(self.selector(),[],False),
                  (dict(self.selector(),domain_pack='material_lookdev_v1'),[record],False),
                  (dict(self.selector(),scene_profile='sphere_ground_v2'),[record],False)):
                worker=GraphJobWorker.__new__(GraphJobWorker)
                worker.domain_schedule={'identity':selector}
                worker.job={'frozen_input_manifest':inputs,'frozen_inputs_sha256':canonical_sha256(inputs)}
                if accepted:
                    worker._construction_inputs(worker.job)
                    self.assertEqual(worker.frozen_input_manifest,inputs)
                else:
                    with self.assertRaises(ValueError): worker._construction_inputs(worker.job)


class OfficialCaptureLimitTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        self.binding=scope_fixture.software_scope(self.root,
            schema=native_scope.OFFICIAL_SCOPE_SCHEMA,resource_profile=native_scope.OFFICIAL_RESOURCE_PROFILE,
            scene_profile=OFFICIAL,budget=native_scope.OFFICIAL_BUDGET)

    def contract(self,count):
        contract=contract_fixture.locked_contract()
        boundary=contract['hda_boundaries'][0]
        boundary['internal_nodes']=[{'path':'/obj/root/asset/n'+str(i).zfill(4),'type':'Lop/null',
            'category':'Lop','definition_sha256':None} for i in range(count)]
        boundary['internal_node_count']=count
        boundary['static_fingerprint']['node_count']=count
        return contract

    def official(self,contract):
        return dict(contract,schema=receipts.OFFICIAL_CAPTURE_SCHEMA,capture_policy=receipts.OFFICIAL_CAPTURE_POLICY,
            capture_limits=dict(receipts.OFFICIAL_CAPTURE_LIMITS),native_scope=self.binding)

    def test_same_large_hda_is_rejected_by_old_policy_and_bounded_for_official(self):
        old=self.contract(200)
        with self.assertRaisesRegex(ValueError,'node limit'): receipts.validate_scene_contract_header(old)
        current=self.official(old)
        current['nodes'][0]['parameters']={str(i):1 for i in range(700)}
        current['nodes'][0]['parameter_channels']={str(i):{} for i in range(700)}
        self.assertEqual(receipts.validate_scene_contract_header(current),receipts.OFFICIAL_CAPTURE_POLICY)
        self.assertEqual(current['capture_limits']['max_bytes'],2*1024*1024)
        for bad in (self.official(self.contract(510)),
                    dict(current,capture_limits=dict(receipts.OFFICIAL_CAPTURE_LIMITS,total_nodes=10000)),
                    dict(current,native_scope=dict(self.binding,sha256='f'*64))):
            with self.assertRaises(ValueError): receipts.validate_scene_contract_header(bad)
        bad=copy.deepcopy(current);bad['nodes'][0]['parameters']={str(i):1 for i in range(1025)}
        with self.assertRaises(ValueError): receipts.validate_scene_contract_header(bad)

    def test_scope_is_required_and_old_policy_cannot_claim_official_limits(self):
        current=self.official(self.contract(10))
        del current['native_scope']
        with self.assertRaises(ValueError): receipts.validate_scene_contract_header(current)
        old=self.contract(10);old['capture_limits']=dict(receipts.OFFICIAL_CAPTURE_LIMITS)
        with self.assertRaises(ValueError): receipts.validate_scene_contract_header(old)
        ordinary=self.root/'ordinary'
        old_scope=scope_fixture.software_scope(ordinary)
        with self.assertRaises(ValueError): receipts.validate_scene_contract_header(dict(self.official(self.contract(10)),native_scope=old_scope))

    def test_initial_empty_boundary_contract_is_structural_only(self):
        current=self.official(self.contract(0)); current['hda_boundaries']=[]
        self.assertEqual(receipts.validate_scene_contract_header(current),receipts.OFFICIAL_CAPTURE_POLICY)
        current['schema']='houdini.task_scene_contract/2.1';current.pop('native_scope');current.pop('capture_limits')
        current['capture_policy']='locked-hda-definition/1'
        with self.assertRaises(ValueError): receipts.validate_scene_contract_header(current)


if __name__=='__main__': unittest.main()
