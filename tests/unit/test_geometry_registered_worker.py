"""Registered graph worker with actual addon and explicit bottom rest geometry."""
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest

from dcc_task_runtime.canonical import canonical_sha256
from vfx_pipeline import graph_catalog
from vfx_pipeline.graph_job_worker import run_job
from vfx_pipeline.graph_job_evidence import PROTOCOL, runtime_fingerprint
from houdini_bridge import native_geometry_controls_program as program
from test_native_geometry_addon_wiring import Fixture, ROOT


def registered_job(fixture):
    fixture.hou.expandString = lambda value: value
    fixture.hou.isUIAvailable = lambda: False
    fixture.addon._TASK_HOST_IDENTITY['plugin_build'] = fixture.addon._FX_LOADED_ADDON_SHA256
    selector = dict(schema='bridge.registered-domain-construction/1',
                    domain_pack='procedural_geometry_v1', houdini_version=fixture.version)
    compiled = graph_catalog.compile_proposal(selector)
    fixture.root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(
        (fixture.task + ':' + compiled.graph_hash).encode()).hexdigest()
    layout = graph_catalog.native_layout(compiled, fixture.root)
    fixture.source_path = next(row['path'] for address, row in layout.items()
                               if address.rsplit('/', 1)[-1] == 'instance_source')
    fixture.source['node_path'] = fixture.source_path
    fixture.input_data.update(task_root=fixture.root, source_node_path=fixture.source_path,
                             source_geometry_sha256=program.source_geometry_sha256(fixture.source))
    fixture.input_path.write_text(json.dumps(fixture.input_data, ensure_ascii=False), encoding='utf-8')
    content = fixture.input_path.read_bytes()
    fixture.input_manifest[0].update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    directory = fixture.directory / 'registered-worker'
    directory.mkdir()
    (directory / 'proposal.json').write_text(json.dumps(selector), encoding='utf-8')
    (directory / 'compiled.json').write_text(json.dumps(compiled.to_dict()), encoding='utf-8')
    return dict(operation_id='op_geometry_input', task_id=fixture.task,
                graph_id='graph_' + canonical_sha256(dict(compiled=compiled.to_dict(),
                    catalog_hash=graph_catalog.descriptor()['catalog_hash'])),
                root=str(fixture.directory), repo_root=str(ROOT),
                proposal_path=str(directory / 'proposal.json'), graph_path=str(directory / 'compiled.json'),
                result_path=str(directory / 'result.json'), journal_path=str(directory / 'journal.sqlite3'),
                lease_path=str(directory / 'lease.sqlite3'), deadline_at=time.time() + 120,
                frozen_input_manifest=copy.deepcopy(fixture.input_manifest),
                frozen_inputs_sha256=canonical_sha256(fixture.input_manifest))


class GeometryRegisteredWorkerTests(unittest.TestCase):
    def test_registered_worker_consumes_frozen_rest_input(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                job = registered_job(fixture)
                result = run_job(job, addon=fixture.addon)
                error_path = Path(job['result_path']).parent / 'error.txt'
                detail = error_path.read_text(encoding='utf-8') if error_path.exists() else result
                self.assertTrue(result['construction_executed'], detail)
                manifest = json.loads(fixture.hou.node(fixture.root).userData('bridge_fx_manifest_v1'))
                initialized = manifest['native_initialization']['geometry_deformation']
                self.assertEqual(initialized.get('value'), 0., initialized)
                self.assertEqual(initialized['evidence_scope'], 'parameters_only')
                self.assertEqual(initialized['status'], 'BLOCKED')
                self.assertFalse(result['reconciliation_required'], detail)
                self.assertNotIn('registered_scene_contract_sha256', result['verification'])
                self.assertTrue(Path(job['result_path']).parent.joinpath(job['operation_id'] + '.hip').is_file())

    def test_file_drift_refuses_before_constructing_the_root(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                job = registered_job(fixture)
                fixture.input_path.write_bytes(b'x' * fixture.input_manifest[0]['bytes'])
                result = run_job(job, addon=fixture.addon)
                self.assertFalse(result['construction_executed'])
                self.assertTrue(result['reconciliation_required'])
                self.assertIsNone(fixture.hou.node(fixture.root))

    def test_stale_manifest_digest_refuses_before_constructing_the_root(self):
        with Fixture(program.VERSIONS[0]) as fixture:
            job = registered_job(fixture)
            job['frozen_inputs_sha256'] = '0' * 64
            result = run_job(job, addon=fixture.addon)
            self.assertFalse(result['construction_executed'])
            self.assertTrue(result['reconciliation_required'])
            self.assertIsNone(fixture.hou.node(fixture.root))

    def test_basis_cannot_be_silently_ignored_by_a_different_domain(self):
        with Fixture(program.VERSIONS[0]) as fixture:
            job = registered_job(fixture)
            selector = dict(schema='bridge.registered-domain-construction/1',
                            domain_pack='lighting_camera_render_v1', houdini_version=fixture.version)
            compiled = graph_catalog.compile_proposal(selector)
            Path(job['proposal_path']).write_text(json.dumps(selector), encoding='utf-8')
            Path(job['graph_path']).write_text(json.dumps(compiled.to_dict()), encoding='utf-8')
            job['graph_id'] = 'graph_' + canonical_sha256(dict(compiled=compiled.to_dict(),
                catalog_hash=graph_catalog.descriptor()['catalog_hash']))
            result = run_job(job, addon=fixture.addon)
            self.assertFalse(result['construction_executed'])
            self.assertTrue(result['reconciliation_required'])
            self.assertEqual(fixture.hou.node('/obj').children(), ())

    def test_managed_worker_refuses_launch_payload_different_from_persisted_inputs(self):
        with Fixture(program.VERSIONS[0]) as fixture:
            job = registered_job(fixture)
            directory = Path(job['result_path']).parent
            job.update(schema_version=PROTOCOL, inputs_path=str(directory / 'inputs.json'),
                attempt_token='explicit-incompatible-launch', attempt_generation=1,
                scheduler_root=str(fixture.directory / 'scheduler'), validation_scope='software_test')
            inputs = {key: job[key] for key in ('operation_id', 'graph_id', 'task_id', 'attempt_token',
                'attempt_generation', 'scheduler_root', 'validation_scope')}
            inputs.update(runtime_sha256=runtime_fingerprint(ROOT), catalog_hash=graph_catalog.descriptor()['catalog_hash'],
                graph_hash=json.loads(Path(job['graph_path']).read_text(encoding='utf-8'))['graph_hash'],
                proposal_sha256=hashlib.sha256(Path(job['proposal_path']).read_bytes()).hexdigest(),
                compiled_sha256=hashlib.sha256(Path(job['graph_path']).read_bytes()).hexdigest(),
                frozen_input_manifest=[], frozen_inputs_sha256=canonical_sha256([]))
            Path(job['inputs_path']).write_text(json.dumps(inputs), encoding='utf-8')
            result = run_job(job, addon=fixture.addon)
            self.assertFalse(result['construction_executed'])
            self.assertTrue(result['reconciliation_required'])
            self.assertIsNone(fixture.hou.node(fixture.root))


if __name__ == '__main__':
    unittest.main()
