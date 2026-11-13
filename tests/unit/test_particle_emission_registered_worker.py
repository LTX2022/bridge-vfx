"""Fresh worker must consume the explicit frozen P01 seed without late init."""
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest

from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge import native_particle_emission_host as adapter
from houdini_bridge import native_particle_emission_program as program
from vfx_pipeline import graph_catalog
from vfx_pipeline.graph_job_worker import run_job
import particle_emission_process_boundary as boundary


def registered_job(fixture, domain_pack='particles_v1'):
    selector = dict(schema='bridge.registered-domain-construction/1',
                    domain_pack=domain_pack, houdini_version=fixture.version)
    compiled = graph_catalog.compile_proposal(selector)
    directory = fixture.directory / 'registered-worker'
    directory.mkdir()
    (directory / 'proposal.json').write_text(json.dumps(selector), encoding='utf-8')
    (directory / 'compiled.json').write_text(json.dumps(compiled.to_dict()), encoding='utf-8')
    fixture.root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(
        (fixture.task + ':' + compiled.graph_hash).encode()).hexdigest()
    return dict(operation_id='op_particle_emission_input', task_id=fixture.task,
                graph_id='graph_' + canonical_sha256(dict(compiled=compiled.to_dict(),
                    catalog_hash=graph_catalog.descriptor()['catalog_hash'])),
                root=str(fixture.directory), repo_root=str(boundary.ROOT),
                proposal_path=str(directory / 'proposal.json'), graph_path=str(directory / 'compiled.json'),
                result_path=str(directory / 'result.json'), journal_path=str(directory / 'journal.sqlite3'),
                lease_path=str(directory / 'lease.sqlite3'), deadline_at=time.time() + 120,
                frozen_input_manifest=copy.deepcopy(fixture.input_manifest),
                frozen_inputs_sha256=canonical_sha256(fixture.input_manifest))


class ParticleEmissionRegisteredWorkerTests(unittest.TestCase):
    def test_invalid_frozen_seed_refuses_before_creating_native_root(self):
        for version in program.SUPPORTED_VERSIONS:
            for corruption in ('file_drift', 'duplicate_role', 'malformed_document'):
                with self.subTest(version=version, corruption=corruption), boundary.RegisteredFixture(version) as fixture:
                    job = registered_job(fixture)
                    if corruption == 'file_drift':
                        path = Path(fixture.input_manifest[0]['source_uri'])
                        path.write_bytes(b'x' * fixture.input_manifest[0]['bytes'])
                    elif corruption == 'duplicate_role':
                        extra = copy.deepcopy(job['frozen_input_manifest'][0])
                        extra.update(index=1, asset_id='duplicate-p01-task-seed')
                        job['frozen_input_manifest'].append(extra)
                        job['frozen_inputs_sha256'] = canonical_sha256(job['frozen_input_manifest'])
                    else:
                        path = Path(fixture.input_manifest[0]['source_uri'])
                        path.write_text(json.dumps({'task_seed': 173, 'extra': True}), encoding='utf-8')
                        content = path.read_bytes()
                        job['frozen_input_manifest'][0].update(
                            bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
                        job['frozen_inputs_sha256'] = canonical_sha256(job['frozen_input_manifest'])
                    result = run_job(job, addon=fixture.addon)
                    self.assertFalse(result['construction_executed'], result)
                    self.assertTrue(result['reconciliation_required'], result)
                    self.assertIsNone(fixture.hou.node(fixture.root))
                    self.assertEqual(fixture.hou.node('/obj').children(), ())

    def test_particle_seed_cannot_be_ignored_by_other_registered_domain(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), boundary.RegisteredFixture(version) as fixture:
                job = registered_job(fixture, domain_pack='lighting_camera_render_v1')
                result = run_job(job, addon=fixture.addon)
                self.assertFalse(result['construction_executed'], result)
                self.assertTrue(result['reconciliation_required'], result)
                self.assertIsNone(fixture.hou.node(fixture.root))
                self.assertEqual(fixture.hou.node('/obj').children(), ())

    def test_no_seed_retains_legacy_birth_rate_without_particle_authority(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), boundary.RegisteredFixture(version) as fixture:
                fixture.input_manifest = []
                job = registered_job(fixture)
                result = run_job(job, addon=fixture.addon)
                error = Path(job['result_path']).parent / 'error.txt'
                detail = error.read_text(encoding='utf-8') if error.exists() else result
                self.assertTrue(result['construction_executed'], detail)
                self.assertFalse(result['reconciliation_required'], detail)
                self.assertNotIn('registered_scene_contract_sha256', result['verification'])
                root = fixture.hou.node(fixture.root)
                manifest = json.loads(root.userData('bridge_fx_manifest_v1'))
                host = fixture.addon._fx_particle_emission_host()
                self.assertEqual(host.authority['records'], {})
                self.assertNotIn('particle_emission_checkpoint', manifest)
                applied = fixture.client.call('agent.fx.apply_candidate', dict(task_id=fixture.task,
                    constraints={'fx': dict(domain_pack='particles_v1', run_mode='diagnose',
                        changes={'birth_rate': 1800.})}))
                self.assertTrue(applied['gates'][0]['passed'], applied)
                self.assertEqual(fixture.hou.node(manifest['nodes']['emission']).parm('constantrate').eval(), 1800.)
                self.assertEqual(host.authority['records'], {})

    def test_fresh_registered_worker_consumes_explicit_frozen_seed(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), boundary.RegisteredFixture(version) as fixture:
                job = registered_job(fixture)
                result = run_job(job, addon=fixture.addon)
                error = Path(job['result_path']).parent / 'error.txt'
                detail = error.read_text(encoding='utf-8') if error.exists() else result
                self.assertTrue(result['construction_executed'], detail)
                self.assertFalse(result['reconciliation_required'], detail)
                self.assertRegex(result['verification']['registered_scene_contract_sha256'], r'^[0-9a-f]{64}$')
                root = fixture.hou.node(fixture.root)
                manifest = json.loads(root.userData('bridge_fx_manifest_v1'))
                roles = manifest['nodes']
                pack = fixture.addon._fx_pack({'constraints': {'fx': {'domain_pack': 'particles_v1'}}})[1]
                current = fixture.addon._fx_particle_emission_host().observations(roles, pack)[adapter.CONTEXT]
                self.assertEqual(current['basis']['task_seed'], 173)
                self.assertEqual(current['basis']['birth_rate'], 1200.)
                self.assertEqual(current['percentage'], 0.)
                self.assertEqual(current['expression'], None)
                self.assertEqual(current['gates']['emission/seed']['value'], 17.)
                applied = fixture.client.call('agent.fx.apply_candidate', dict(task_id=fixture.task,
                    constraints={'fx': dict(domain_pack='particles_v1', run_mode='diagnose',
                        changes={'emission_variance': 45., 'birth_rate': 2300.})}))
                readback = applied['native_geometry_readback']
                self.assertEqual(readback['status'], 'BLOCKED')
                self.assertEqual(readback['evidence_scope'], 'native_parameter_expression_only')
                self.assertEqual(readback['percentage'], 45.)
                self.assertEqual(readback['birth_rate'], 2300.)
                self.assertEqual(readback['context']['basis']['task_seed'], 173)


if __name__ == '__main__':
    unittest.main()
