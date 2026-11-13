"""Generated server and actual owned Python worker consume explicit rest inputs."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from dcc_task_runtime.canonical import canonical_sha256
from houdini_bridge import native_geometry_controls_program as program
from vfx_pipeline import graph_catalog
from vfx_pipeline.production_hosts import stop_hosts
from vfx_pipeline.service import ModelSafePipeline
from vfx_pipeline.workbuddy_project import media_descriptor
from vfx_pipeline.workbuddy_assembly import production_host_client
import test_production_task_hosts as support
from test_native_geometry_controls_program import BottomGeometry


REST_API = '''sys.path.insert(0,str(native_root/'tests/unit'))
from test_native_geometry_controls_host import Geometry
from test_native_geometry_controls_program import BottomGeometry
from test_native_geometry_observation import NativeAttribute,NativePrimitive,NativeVertex
from test_native_particle_size_host import NativeName
rest_document=json.loads(Path(os.environ['BRIDGE_TEST_GEOMETRY_REST_INPUT']).read_text(encoding='utf-8'))
rest_path=rest_document['source_node_path']
rest_geometry=BottomGeometry(rest_path).observe()
class RestAttribute(NativeAttribute):
    def dataType(self):return NativeName(self.kind)
    def numericDataType(self):return NativeName(self.precision)
class RestGeometry(Geometry):
    def pointAttribs(self):
        return (RestAttribute('P','point','Float',3,'Float64',(0.,0.,0.)),
            RestAttribute('N','point','Float',3,'Float64',(0.,1.,0.),qualifier='normal',transformed=True),
            RestAttribute('id','point','Int',1,'Int32',0))
    def primAttribs(self):return ()
    def vertexAttribs(self):return ()
    def globalAttribs(self):return ()
    def points(self):
        points=tuple(super().points())
        for point in points:
            original=point.attribValue
            point.attribValue=lambda attr,original=original:original(attr if isinstance(attr,str) else attr.name())
        return points
    def prims(self):
        points=self.points()
        return (NativePrimitive(0,[NativeVertex(index,points[point],{})
            for index,point in enumerate(self.source['polygons'][0])],{}),)
original_geometry=Node.geometry
def explicit_rest_geometry(self,output_index=0):
    if self.path()==rest_path:
        if output_index!=0:raise ValueError('explicit rest source has only output zero')
        return RestGeometry(rest_geometry)
    return original_geometry(self,output_index=output_index)
Node.geometry=explicit_rest_geometry
def explicit_rest_geometry_at_frame(self,frame,output_index=0):
    if self.path()!=rest_path or frame!=rest_document['frame'] or output_index!=0:
        raise ValueError('explicit rest frame/output unavailable')
    return RestGeometry(rest_geometry)
Node.geometryAtFrame=explicit_rest_geometry_at_frame
Node.isBypassed=lambda self:False
'''


class GeometryConstructionProcessTests(unittest.TestCase):
    def test_generated_server_owned_workers_bind_authenticated_rest_inputs(self):
        helper = support.ProductionTaskHostsTests('test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen')
        for version in program.VERSIONS:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                project, api = base / 'project', base / 'api'
                api.mkdir()
                (api / 'nuke.py').write_text(support.FAKE, encoding='utf-8')
                rest_path = base / '冻结输入 with space.json'
                native = support.STRICT_RENDER_NATIVE.replace(
                    "native.constrain_hou(native_root/", "states.setdefault('Sop/attribwrangle',{})['snippet']=dict(origin='test_injected_native_api',value='',locked=False,disabled=False,hidden=False)\nnative.constrain_hou(native_root/")
                launch = support.HYTHON.replace("sys.modules['houdini_bridge_addon']=addon",
                    "sys.modules['houdini_bridge_addon']=addon\n" + native + REST_API)
                bootstrap = base / 'fake-hython.py'
                bootstrap.write_text(launch, encoding='utf-8')
                host = helper.config(project, 'houdini', bootstrap, api)
                host.update(version=version, session_seconds=120)
                nuke = helper.config(project, 'nuke', support.SOFTWARE_PYTHON, api)
                nuke['session_seconds'] = 120
                support.prepare_graph(project, app=None, scheduler_root=project / 'scheduler',
                    execution_profile=True, render_profile=True,
                    production_host_config=host, production_nuke_config=nuke)
                manifest_path = project / 'control/run.json'
                snapshot = project / 'control/snapshot'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                references = [dict(asset_id=item['asset_id'], kind=media_descriptor(item)['kind'],
                    uri=str((manifest_path.parent / item['file']).resolve()), sha256=item['sha256'])
                    for item in manifest['assets']]
                spec = dict(schema_version='2.0', task_type='visual.reference_rebuild',
                    intent='synthetic bounded graph construction trial',
                    target=dict(application='pipeline', scene_mode='current'), references=references,
                    domains=[dict(identifier='pyro_smoke_v1', version='1.0.0')],
                    feedback='synthetic graph construction trial only', render={}, delivery=dict(composite=False))
                pipeline = ModelSafePipeline(project / 'control/pipeline.sqlite3')
                task_id = pipeline.reference_task_start(spec, idempotency_key='graph-run:' + manifest['run_id'],
                                                       purpose='graph_construction')['task_id']
                selector = dict(schema='bridge.registered-domain-construction/1',
                    domain_pack='procedural_geometry_v1', houdini_version=version)
                compiled = graph_catalog.compile_proposal(selector)
                graph_root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((task_id + ':' + compiled.graph_hash).encode()).hexdigest()
                layout = graph_catalog.native_layout(compiled, graph_root)
                source_path = next(row['path'] for address, row in layout.items()
                                   if address.rsplit('/', 1)[-1] == 'instance_source')
                source = BottomGeometry(source_path).observe()
                document = dict(schema='bridge.geometry-rest-input/1', task_id=task_id,
                    task_root=graph_root, native_version=version, input_version='explicit-process-rest-v1',
                    source_node_path=source_path, output=0, frame=1., space='sop_local_rest', unit='SU',
                    local_x_axis=[1., 0., 0.], source_geometry_sha256=program.source_geometry_sha256(source),
                    geometry_observation='native_sop_read')
                rest_path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
                raw = rest_path.read_bytes()
                inputs = [dict(index=0, asset_id='explicit-process-rest', semantic_role='geometry_rest_basis',
                    source_uri=str(rest_path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                    explicit_transport_padding=['x' * 8000 for index in range(5)])]
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                manifest['construction_input_manifest'] = inputs
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
                process = None
                trial = None
                lifecycle = {}
                with patch.dict(os.environ, {'BRIDGE_TEST_NATIVE_ROOT': str(support.ROOT),
                        'BRIDGE_TEST_NATIVE_VERSION': version, 'BRIDGE_TEST_GEOMETRY_REST_INPUT': str(rest_path),
                        'HOUDINI_BRIDGE_STATE_DIR': str(project / 'bridge-state'),
                        'BRIDGE_SKILLS_STATE_ROOT': str(project / 'runtime-state')}):
                    try:
                        process = helper.boot(project)
                        for index, asset in enumerate(helper.tool(process, 'catalog', {})['assets']):
                            helper.tool(process, 'submit_observation', dict(asset_id=asset['asset_id'],
                                request_id='input-observation-' + str(index), observation=dict(
                                    description='explicit bottom native source fixture', dominant_colors=['grey'])))
                        proposal = helper.tool(process, 'graph_propose', dict(proposal=selector, request_id='input-proposal'))
                        self.assertIn('graph_id', proposal, proposal)
                        arguments = dict(graph_id=proposal['graph_id'], request_id='input-trial')
                        trial = helper.completed_graph_trial(process, project, arguments)
                        details = '\n'.join(path.read_text(encoding='utf-8', errors='replace') for path in project.rglob('error.txt'))
                        self.assertEqual(trial.get('state'), 'SUCCEEDED', str(trial) + '\n' + details)
                        self.assertTrue(trial['stop_confirmed'], trial)
                        self.assertFalse(trial['result']['visual_verified'])
                        state = json.loads((project / 'control/production-hosts.json').read_text(encoding='utf-8'))
                        client = production_host_client(state['hosts']['houdini'], project / 'identity-probe')
                        client.bind_task(task_id)
                        before = client.call('ping', {})['task_host_identity']
                        parameters = dict(task_id=task_id, constraints={'fx': {
                            'domain_pack': 'procedural_geometry_v1', 'run_mode': 'diagnose',
                            'changes': {'deformation': 3.}}})
                        applied = client.call('agent.fx.apply_candidate', parameters)
                        self.assertEqual(applied['native_geometry_readback']['value'], 3.)
                        transitions = (project / 'control/scene-transitions.json').read_bytes()
                        repeated = helper.tool(process, 'graph_trial', arguments)
                        self.assertIn('operation_id', repeated, repeated)
                        self.assertEqual(repeated['operation_id'], trial['operation_id'])
                        self.assertEqual(client.call('ping', {})['task_host_identity'], before)
                        self.assertEqual((project / 'control/scene-transitions.json').read_bytes(), transitions)
                        input_files = list(project.glob('control/jobs/graph-jobs/*/attempt-*/inputs.json'))
                        self.assertEqual(len(input_files), 1, input_files)
                        persisted = json.loads(input_files[0].read_text(encoding='utf-8'))
                        self.assertEqual(persisted['frozen_input_manifest'], inputs)
                        self.assertEqual(persisted['frozen_inputs_sha256'], canonical_sha256(inputs))
                        job_file = input_files[0].parent / 'worker-job.json'
                        self.assertTrue(job_file.is_file())
                        worker_identity = json.loads((input_files[0].parent / 'worker_identity.json').read_text(encoding='utf-8'))
                        self.assertNotEqual(worker_identity['process_identity']['pid'], before['pid'])
                        journal_path = input_files[0].parent / 'journal.sqlite3'
                        with closing(sqlite3.connect(journal_path)) as database:
                            records = [json.loads(row[0]) for row in database.execute('SELECT payload FROM entries')]
                        initialization = next(row for row in records if row['intent'].get('kind') == 'domain.initialize')
                        self.assertEqual(initialization['result']['frozen_inputs_sha256'], canonical_sha256(inputs))
                        deform_path = next(row['path'] for address, row in layout.items()
                                           if address.rsplit('/', 1)[-1] == program.ROLE)
                        names = ['snippet', 'class', 'group', 'vex_precision']
                        saved_parameters = client.call('node.parms', dict(path=deform_path, names=names))['parms']
                        saved = helper.tool(process, 'task_save', {})
                        self.assertIn('saved_scene_id', saved, saved)
                        helper.close(process)
                        process = None
                        stopped_before = stop_hosts(project / 'control')
                        self.assertTrue(stopped_before['houdini']['receipt']['confirmed_exit'], stopped_before)
                        process = helper.boot(project)
                        reopened = helper.tool(process, 'task_reopen', dict(saved_scene_id=saved['saved_scene_id']))
                        self.assertTrue(reopened.get('geometry_registry_restored'), reopened)
                        self.assertTrue(reopened.get('nodes_verified'), reopened)
                        self.assertTrue(reopened.get('parameters_verified'), reopened)
                        self.assertTrue(reopened.get('connections_verified'), reopened)
                        state = json.loads((project / 'control/production-hosts.json').read_text(encoding='utf-8'))
                        client = production_host_client(state['hosts']['houdini'], project / 'reopen-probe')
                        client.bind_task(task_id)
                        after = client.call('ping', {})['task_host_identity']
                        self.assertNotEqual(after['pid'], before['pid'])
                        self.assertNotEqual(after['launch_nonce'], before['launch_nonce'])
                        reopened_parameters = client.call('node.parms', dict(path=deform_path, names=names))['parms']
                        self.assertEqual(reopened_parameters, saved_parameters)
                        observation = dict(task_id=task_id, constraints={'fx': {
                            'domain_pack': 'procedural_geometry_v1', 'run_mode': 'diagnose', 'frames': [-1, 0, 1, 2]}},
                            render={'frame_range': {'start': -1, 'end': 2, 'step': 1}})
                        frame_before = client.call('scene.info', {})['frame']
                        evidence = client.call('agent.fx.collect_evidence', observation)['evidence']
                        self.assertEqual(client.call('scene.info', {})['frame'], frame_before)
                        self.assertEqual(set(evidence['native_geometry_readback']), {'-1', '0', '1', '2'})
                        self.assertEqual(set(evidence['native_geometry_outputs']), {'-1', '0', '1', '2'})
                        for collected in evidence['native_geometry_readback'].values():
                            self.assertEqual(collected['value'], 3.)
                            self.assertEqual(collected['status'], 'BLOCKED')
                            self.assertEqual(collected['evidence_scope'], 'parameters_only')
                        for outputs in evidence['native_geometry_outputs'].values():
                            self.assertEqual(outputs['status'], 'BLOCKED')
                            self.assertTrue(outputs['missing'])
                            raw_source = outputs['outputs']['instance_source']
                            self.assertEqual(raw_source['points'], source['points'])
                            self.assertEqual(raw_source['polygons'], source['polygons'])
                            for name in ('P', 'N', 'id'):
                                self.assertEqual(raw_source['attributes']['point'][name]['values'],
                                                 source['point_attributes'][name]['values'])
                        self.assertEqual(client.call('node.parms', dict(path=deform_path, names=names))['parms'], saved_parameters)
                        lifecycle = dict(applied=applied, saved=saved, reopened=reopened,
                            stop_before_reopen=stopped_before, host_before=before, host_after=after,
                            parameters_before=saved_parameters, parameters_after=reopened_parameters,
                            direct_readback=evidence['native_geometry_readback']['1'],
                            cross_frame_readback=evidence['native_geometry_readback'],
                            cross_frame_outputs=evidence['native_geometry_outputs'],
                            original_frame=frame_before, restored_frame=client.call('scene.info', {})['frame'])
                    finally:
                        if process is not None:
                            helper.close(process)
                        stopped = stop_hosts(project / 'control')
                        archive = os.environ.get('BRIDGE_TEST_GEOMETRY_INPUT_ARCHIVE')
                        if archive:
                            target = Path(archive) / version
                            target.mkdir(parents=True, exist_ok=False)
                            for label, value in (('trial', trial), ('stop', stopped), ('rest_input', document), ('lifecycle', lifecycle)):
                                (target / (label + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
                            shutil.copyfile(rest_path, target / 'rest-input-original.json')
                            jobs_root = project / 'control/jobs'
                            allowed = {'graph_jobs.sqlite3', 'journal.sqlite3', 'scene_lease.sqlite3',
                                'compiled.json', 'completion.json', 'inputs.json', 'proposal.json', 'result.json',
                                'worker_identity.json', 'worker-job.json', 'started.json', 'stopped.json',
                                'child.stderr.log', 'child.stdout.log', 'supervisor.stderr.log', 'supervisor.stdout.log'}
                            for path in jobs_root.rglob('*'):
                                if path.is_file() and (path.name in allowed or path.suffix == '.hip' or path.name.endswith('.native-operations.json')):
                                    output = target / 'jobs' / path.relative_to(jobs_root)
                                    output.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copyfile(path, output)
                            shutil.copy2(project / 'control/snapshot-manifest.json', target / 'snapshot-manifest.json')
                            for source_root in (project / 'saves', project / 'scene-transition-snapshots'):
                                if source_root.is_dir():
                                    for path in source_root.rglob('*.hip'):
                                        output = target / 'scene-files' / path.relative_to(project)
                                        output.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copyfile(path, output)
                            transitions_path = project / 'control/scene-transitions.json'
                            if transitions_path.is_file():
                                shutil.copyfile(transitions_path, target / 'scene-transitions.json')


if __name__ == '__main__':
    unittest.main()
