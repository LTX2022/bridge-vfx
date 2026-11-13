"""Exact 459 preparation contracts and raw static sources; no host execution."""
import hashlib
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
for package in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from houdini_bridge import native_459_basis as basis
from houdini_bridge import native_domain_registry as registry, native_render_domains as render


class Houdini459NativeCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = json.loads((ROOT / basis.BASIS_PATH).read_text())
        cls.support = json.loads((ROOT / 'docs/native-basis/supporting-sources-22.0.459.json').read_text())

    def test_compact_runtime_fields_match_independent_459_originals(self):
        self.assertEqual(self.capture['version'], '22.0.459')
        self.assertFalse(self.capture['native_execution'])
        originals = ROOT / 'docs/native-basis/h22-459-originals'
        for operator, compact in basis._HDA_FIELDS.items():
            with self.subTest(operator=operator):
                actual = self.capture['operators'][operator]
                self.assertEqual(actual['status'], 'CAPTURED_STATIC_DIALOG')
                self.assertEqual(compact['section_sha256'], actual['section_sha256'])
                self.assertEqual(compact['archive_sha256'], actual['source_archive']['sha256'])
                self.assertEqual(hashlib.sha256((originals / actual['raw_section']).read_bytes()).hexdigest(),
                                 compact['section_sha256'])
                for parameter, record in compact['parameters'].items():
                    self.assertEqual(record, {key: actual['parameters'][parameter][key] for key in record})
        from native_schema_test_boundary import capture_catalog
        catalog = capture_catalog(ROOT / 'docs/native-basis/hda-interface-capture.json', '22.0.459')
        self.assertEqual(len(catalog), 55)
        self.assertIn(('Sop', 'attribwrangle'), catalog)
        self.assertNotIn(('Driver', 'usdrender'), catalog)
        self.assertNotIn(('Obj', 'geo'), catalog)

    def test_explicit_preparation_does_not_expand_legacy_contract_versions(self):
        self.assertEqual(basis.PREPARATION_VERSIONS, ('22.0.459',))
        for name in ('native_pyro_domains', 'native_vellum_domains', 'native_crowd_hair_domains',
                     'native_flip_rbd_domains', 'native_particle_ocean_geometry_domains', 'native_render_domains',
                     'native_geometry_controls_program', 'native_particle_emission_program',
                     'native_ocean_mask_program', 'native_cloth_wrinkle_program', 'native_swarm_controls',
                     'native_crowd_route_contract', 'crowd_helpers'):
            module = importlib.import_module('houdini_bridge.' + name)
            versions = getattr(module, 'SUPPORTED_VERSIONS', getattr(module, 'VERSIONS', None))
            self.assertEqual(versions, ('21.0.631', '22.0.429'), name)
            self.assertEqual(module.PREPARATION_VERSIONS, ('22.0.459',), name)
        legacy = render.control_contract(pack_id=render.LIGHTING, version='22.0.429')
        self.assertNotIn('native_basis', legacy['filter_width'])
        with self.assertRaises(render.NativeRenderDomainError):
            render.control_contract(render.LIGHTING, '22.0.460')

    def test_all_domain_contracts_bind_459_and_missing_interfaces_refuse(self):
        for domain in registry.DOMAIN_IDS:
            module = registry.module_for(domain)
            for branch in registry.branches(domain):
                args = (domain, '22.0.459') + ((branch,) if branch else ())
                for name, control in module.control_contract(*args).items():
                    with self.subTest(domain=domain, branch=branch, control=name):
                        proof = control['native_basis']
                        self.assertEqual(proof['version'], '22.0.459')
                        self.assertFalse(proof['native_execution'])
                        if control['native_status'] == 'mapped':
                            self.assertTrue(proof['observed'])
                            self.assertEqual(proof['missing'], [])
        from houdini_bridge import native_pyro_domains as pyro
        from houdini_bridge import native_particle_ocean_geometry_domains as geometry
        self.assertEqual(pyro.control_write_plan(pyro.SMOKE, 'density_scale', 1.5, '22.0.459')[0]['value'], 1.5)
        for module, domain, control, value in ((pyro, pyro.SMOKE, 'source_scale', 1.),
                                              (geometry, geometry.GEOMETRY, 'density', 1.),
                                              (render, render.LIGHTING, 'filter_width', 2.5)):
            with self.subTest(refusal=control), self.assertRaises(ValueError) as caught:
                module.control_write_plan(domain, control, value, '22.0.459')
            self.assertEqual(caught.exception.code, 'H22_459_NATIVE_TEMPLATE_REQUIRED')
        with mock.patch.object(Path, 'open', side_effect=AssertionError('runtime contract read developer resources')):
            self.assertEqual(render.control_contract(render.LIGHTING, '22.0.459')['exposure']['native_status'], 'mapped')

    def test_route_and_transition_459_hashes_have_exact_same_build_sources(self):
        from houdini_bridge import native_crowd_route_contract as route, native_crowd_transition_contract as transition
        documents = {row['member']: row['sha256'] for row in self.support['documents']}
        files = {Path(row['path']).name: row['sha256'] for row in self.support['files']}
        self.assertEqual(route._ROUTE_DIALOG['22.0.459'], self.capture['operators']['Dop/popsteerpath']['section_sha256'])
        self.assertEqual(route._GEOMETRY_DOC['22.0.459'], documents['hou/Geometry.txt'])
        self.assertEqual(route._PARM_DOC['22.0.459'], documents['hou/Parm.txt'])
        self.assertEqual(route._RECIPE_SHA256['22.0.459'], files['crowdstoolutils.py'])
        actual = transition.native_basis('22.0.459')
        self.assertEqual(actual['perform_transition_sha256'], self.support['crowd_transition_consumer']['sha256'])
        self.assertEqual(actual['ramp_doc_sha256'], documents['hou/Ramp.txt'])
        self.assertEqual(actual['native_execution'], 'NOT_RUN')

    def test_459_writer_fixed_hook_observation_keeps_effective_writer_blocked(self):
        from test_render_writer_facts import RenderWriterFactsTests
        from houdini_bridge import client
        fixture = RenderWriterFactsTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.hou.applicationVersionString = lambda: '22.0.459'
        observation = fixture.observed()
        self.assertEqual(observation['body']['houdini_version'], '22.0.459')
        fixture.record['frame_snapshots']['1'] = fixture.fixture.snapshot()
        fixture.record['output_facts'] = {'1': client.collect_render_output_fact(fixture.record, 1)}
        fact = client.render_execution_fact(fixture.record)
        self.assertEqual(fact['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(fact['metadata'], {})


if __name__ == '__main__':
    unittest.main()
