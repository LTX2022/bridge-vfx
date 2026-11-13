import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from vfx_pipeline.feedback_versions import FeedbackVersions
from vfx_pipeline.workbuddy_project import DiagnosticRun
from dcc_task_runtime.artifact_registry import ArtifactRegistry


class FeedbackVersionTests(unittest.TestCase):
    def test_native_readback_versions_restart_and_scoped_invalidation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / 'run.json'
            manifest.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'test','assets':[]}))
            run = DiagnosticRun(manifest); run.pipeline_task_id = 'task'
            registry = ArtifactRegistry(root / 'ledger'); run.artifact_registry = registry
            output = root / 'image.png'; output.write_bytes(b'x' * 2048)
            registry.set_operation_source(lambda op: {'task_id':'task','state':'COMPLETED',
                'frame_set':[1],'output_pattern':str(output),'started_at_epoch':0,
                'operation_receipt_sha256': hashlib.sha256(op.encode()).hexdigest()})
            dependency = 'graph:task:graph:output:out'
            for asset, deps in [('affected', [dependency]), ('child', ['artifact:affected']), ('unrelated', ['another-source'])]:
                registry.register(artifact_id=asset, task_id='task', artifact_class='raw_input', pattern=str(output),
                    frame_set=[1], dependencies=deps, colorspace='linear', premultiplied=False, operation_id='fixture')
            class Client:
                values = {'size': 1, 'artist_unrelated': 9}
                writes = 0
                def call(self, command, args):
                    if command == 'node.parms': return {'parms': dict(self.values)}
                    self.writes += 1; self.values.update(args['parms'])
                    return {'path': args['path'], 'values': dict(args['parms'])}
            client = Client()
            compiled = {'graph_hash': 'a' * 64, 'nodes': [
                {'node_id':'source', 'address':'sop:/source', 'parameters':{'size':1}},
                {'node_id':'sink', 'address':'sop:/sink', 'parameters':{}},
                {'node_id':'artist', 'address':'sop:/artist', 'parameters':{'x':5}}],
                'connections':[{'source_node':'sop:/source','target_node':'sop:/sink'}],
                'outputs':[{'node_id':'sink','output_id':'out'},{'node_id':'artist','output_id':'other'}]}
            versions = FeedbackVersions(run)
            with patch.object(versions, '_complete', side_effect=OSError('controller crash after host mutation')):
                with self.assertRaises(OSError):
                    versions.apply('graph', compiled, '/obj/source', 'source', {'size':2}, client)
            self.assertEqual(client.writes, 1)
            restarted = FeedbackVersions(run)
            recovered = restarted.apply('graph', compiled, '/obj/source', 'source', {'size':2}, client)
            self.assertEqual(client.writes, 1)
            self.assertTrue(recovered['replayed'])
            self.assertEqual(recovered['state'], 'COMPLETE')
            self.assertEqual(recovered['invalidated_nodes'], ['sink','source'])
            self.assertEqual(recovered['invalidated_outputs'], ['out'])
            self.assertEqual(client.values['artist_unrelated'], 9)
            self.assertEqual(recovered['compiled']['nodes'][2]['parameters'], {'x':5})
            self.assertTrue(registry.verify('affected')['invalidated'])
            self.assertTrue(registry.verify('child')['invalidated'])
            self.assertFalse(registry.verify('unrelated')['invalidated'])
            next_version = restarted.apply('graph', compiled, '/obj/source', 'source', {'size':3}, client)
            self.assertEqual(next_version['version'], 2)
            self.assertNotEqual(next_version['graph_hash'], recovered['graph_hash'])

    def test_host_changed_unrelated_parameter_is_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'run.json'
            path.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'test','assets':[]}))
            run = DiagnosticRun(path); run.pipeline_task_id='task'; run.artifact_registry=None
            class Client:
                values={'size':1,'unrelated':9}
                def call(self, command, args):
                    if command=='node.parms': return {'parms':dict(self.values)}
                    self.values={'size':2,'unrelated':0}; return {}
            graph={'graph_hash':'a'*64,'nodes':[{'node_id':'source','parameters':{}}],'connections':[],'outputs':[]}
            with self.assertRaisesRegex(ValueError, 'readback mismatch'):
                FeedbackVersions(run).apply('graph',graph,'/obj/source','source',{'size':2},Client())
            self.assertEqual(FeedbackVersions(run).current('graph')['state'],'DISPATCHED')

    def test_invalidation_failure_restarts_prepared_intent_without_duplicate_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'run.json'
            path.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'test','assets':[]}))
            run = DiagnosticRun(path); run.pipeline_task_id='task'
            class Registry:
                def invalidate_dependencies(self, *a, **kw): pass
            run.artifact_registry=Registry()
            class Client:
                values={'size':1,'unrelated':9}; writes=0
                def call(self, command, args):
                    if command=='node.parms': return {'parms':dict(self.values)}
                    self.values.update(args['parms']); self.writes += 1; return {}
            client=Client()
            graph={'graph_hash':'a'*64,'nodes':[{'node_id':'source','parameters':{}}],'connections':[],'outputs':[]}
            versions=FeedbackVersions(run)
            with patch.object(run.artifact_registry, 'invalidate_dependencies', side_effect=OSError('ledger unavailable')):
                with self.assertRaises(OSError):
                    versions.apply('graph',graph,'/obj/source','source',{'size':2},client)
            self.assertEqual(client.writes,0)
            self.assertEqual(versions.current('graph')['state'],'PREPARED')
            result=FeedbackVersions(run).apply('graph',graph,'/obj/source','source',{'size':2},client)
            self.assertEqual(result['version'],1)
            self.assertEqual(result['state'],'COMPLETE')
            self.assertEqual(client.writes,1)

    def test_native_candidate_restart_retains_frozen_plan_and_does_not_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest = root / 'run.json'
            manifest.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'test','assets':[]}))
            run = DiagnosticRun(manifest); run.pipeline_task_id = 'task'; run.artifact_registry = None
            path = '/obj/BRIDGE_GRAPH_' + 'a' * 64 + '/usd_network/light'
            compiled = {'graph_hash':'a' * 64, 'nodes':[{'node_id':'light','address':'lop:/light','parameters':{}}],
                        'connections':[], 'outputs':[{'node_id':'light','output_id':'image'}]}
            candidate = {'task_id':'task','base_graph_hash':'a' * 64,'node_path':path,
                'readback_names':['exposure','exposure_control'], 'controls':{'exposure':1.25},
                'request':{'task_id':'task','constraints':{'fx':{'domain_pack':'lighting_camera_render_v1','changes':{'exposure':1.25}}}}}
            class Client:
                writes = 0
                values = {'exposure':0.,'exposure_control':'set'}
                def call(self, command, params):
                    if command == 'node.parms':
                        if params.get('names') != ['exposure','exposure_control']:
                            raise AssertionError('unbounded expression evaluation')
                        return {'parms':dict(self.values)}
                    if command != 'agent.fx.apply_candidate':
                        raise AssertionError(command)
                    self.writes += 1; self.values['exposure'] = 1.25
                    return {'parameter_diff':[{'semantic_control':'exposure','node':path,'readback_verified':True}]}
            client = Client(); versions = FeedbackVersions(run)
            with patch.object(versions, '_complete', side_effect=OSError('interrupted controller commit')):
                with self.assertRaises(OSError):
                    versions.apply('g', compiled, path, 'light', {'exposure':1.25}, client, domain_candidate=candidate)
            result = FeedbackVersions(run).apply('g', compiled, path, 'light', {'exposure':1.25}, client, domain_candidate=candidate)
            self.assertTrue(result['replayed']); self.assertEqual(client.writes, 1)
            self.assertEqual(result['version'], 1); self.assertEqual(result['state'], 'COMPLETE')
            with run._connect() as db:
                encoded = json.loads(db.execute('SELECT payload FROM feedback_versions').fetchone()[0])
                encoded['domain_candidate']['controls']['exposure'] = 2
                db.execute('UPDATE feedback_versions SET payload=?', (json.dumps(encoded),))
            with self.assertRaisesRegex(ValueError, 'persisted native feedback plan changed'):
                FeedbackVersions(run).apply('g', compiled, path, 'light', {'exposure':2}, client, domain_candidate=candidate)
            self.assertEqual(client.writes, 1)

    def test_rbd_semantic_feedback_registered_route_and_restart_never_write_snippet(self):
        from types import SimpleNamespace
        from vfx_pipeline import graph_catalog
        from vfx_pipeline.workbuddy_graph_mcp import GraphRun
        for version in ('21.0.631', '22.0.429'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                manifest = Path(temporary) / 'run.json'
                manifest.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0',
                    'run_id':'test', 'assets':[], 'construction_authorized':True}))
                compiled = graph_catalog.compile_proposal({'schema':'bridge.registered-domain-construction/1',
                    'domain_pack':'rbd_destruction_v1', 'houdini_version':version}).to_dict()
                execution_root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(('task:' + compiled['graph_hash']).encode()).hexdigest()
                graph = graph_catalog.compile_proposal({'schema':'bridge.registered-domain-construction/1',
                    'domain_pack':'rbd_destruction_v1', 'houdini_version':version})
                node = next(n for n in compiled['nodes'] if n['node_id'] == 'rbd_velocity')
                path = graph_catalog.native_layout(graph, execution_root)[node['address']]['path']
                from houdini_bridge.operation_receipts import SCHEMA, canonical_sha256, operation_receipt_sha256
                identity = dict(task_id='task',pid=123,session_id='session',launch_nonce='nonce',
                    process_generation='generation',plugin_build='a'*64,scene_epoch=0)
                class Client:
                    value = 0.; writes = 0; wrong_node = False; fail_before_delivery = False
                    records = {}; query_error = False
                    def scene(self):
                        contract = {'schema':'houdini.task_scene_contract/2.0','task_id':'task',
                            'nodes':[{'path':path,'velocity_variance':self.value}]}
                        return {'host_identity':identity,'scene_contract':contract,
                                'scene_contract_sha256':canonical_sha256(contract)}
                    def call(self, command, params):
                        if command == 'agent.fx.operation_receipt':
                            if self.query_error: raise OSError('receipt query transport unknown')
                            return {'task_id':'task','operation_id':params['operation_id'],
                                'operation_receipt':self.records.get(params['operation_id']),
                                'current_host_identity':identity,'current_scene':self.scene()}
                        if command == 'agent.fx.inspect_controls':
                            self_request = {'task_id':'task', 'bridge_execution_binding':{'execution_root':execution_root},
                                'constraints':{'fx':{'domain_pack':'rbd_destruction_v1','run_mode':'diagnose'}},
                                'controls':['velocity_variance']}
                            if params != self_request: raise AssertionError(params)
                            return {'task_id':'task','execution_root':execution_root,'domain_pack':'rbd_destruction_v1',
                                'node_path':path + ('_foreign' if self.wrong_node else ''),
                                'controls':{'velocity_variance':self.value},'readback_verified':True}
                        if command != 'agent.fx.apply_candidate': raise AssertionError(command)
                        if self.fail_before_delivery:
                            self.fail_before_delivery = False
                            raise OSError('after controller CAS, before host receives request')
                        if params['operation_id'] in self.records: raise AssertionError('must query existing producer receipt')
                        changes = params['constraints']['fx']['changes']
                        if set(changes) != {'velocity_variance'}: raise AssertionError(changes)
                        before = self.scene()
                        self.value = changes['velocity_variance']; self.writes += 1
                        result = {'parameter_diff':[{'semantic_control':'velocity_variance','node':path,'readback_verified':True}]}
                        record = dict(schema=SCHEMA,kind='edit',stage='edit',command=command,state='COMPLETED',
                            task_id='task',operation_id=params['operation_id'],request_id=params['request_id'],request=params,
                            request_sha256=canonical_sha256({'task_id':'task','command':command,'request_id':params['request_id'],'request':params}),
                            frozen_input_manifest=[],frozen_inputs_sha256=canonical_sha256([]),host_identity=identity,
                            before_scene=before,after_scene=self.scene(),result=result,
                            facts={'scope':'edit','handler_result_sha256':canonical_sha256(result)})
                        record['operation_receipt_sha256'] = operation_receipt_sha256(record)
                        self.records[params['operation_id']] = record
                        return {**result,'operation_receipt':record}
                client = Client()
                def facade():
                    return GraphRun(manifest, SimpleNamespace(compiled_graph=lambda graph_id:compiled),
                                    task_id='task',host_client=client)
                run = facade()
                # Exact post-CAS / pre-host delivery window: producer query, not before-value inference.
                client.fail_before_delivery = True
                with self.assertRaises(OSError): run.feedback_edit('g','rbd_velocity',{'velocity_variance':3.},'task')
                self.assertEqual(run.graph_version('g')['state'],'DISPATCHED'); self.assertEqual(client.writes,0)
                operation_id = run.graph_version('g')['producer_request']['operation_id']
                client.query_error = True
                with self.assertRaises(OSError): facade().feedback_edit('g','rbd_velocity',{'velocity_variance':3.},'task')
                self.assertEqual(client.writes,0)
                client.query_error = False
                run = facade()
                result = run.feedback_edit('g','rbd_velocity',{'velocity_variance':3.},'task')
                self.assertEqual((result['version'], result['state'], client.writes),(1,'COMPLETE',1))
                self.assertEqual(result['producer_request']['operation_id'],operation_id)
                # A dispatched write is confirmed by exact semantic readback, never replayed.
                with patch.object(FeedbackVersions, '_complete', side_effect=OSError('after native mutation')):
                    with self.assertRaises(OSError): run.feedback_edit('g','rbd_velocity',{'velocity_variance':5.},'task')
                self.assertEqual(run.graph_version('g')['state'],'DISPATCHED')
                operation_id = run.graph_version('g')['producer_request']['operation_id']
                completed_receipt = client.records[operation_id]
                for state in ('INTENT', 'FAILED'):
                    incomplete = json.loads(json.dumps(completed_receipt))
                    incomplete['state'] = state
                    incomplete['operation_receipt_sha256'] = operation_receipt_sha256(incomplete)
                    client.records[operation_id] = incomplete
                    with self.assertRaisesRegex(ValueError,'producer attempt is unproven'):
                        facade().feedback_edit('g','rbd_velocity',{'velocity_variance':5.},'task')
                    self.assertEqual(client.writes,2)
                client.records[operation_id] = completed_receipt
                client.value = 6.
                with self.assertRaisesRegex(ValueError,'producer scene changed'):
                    facade().feedback_edit('g','rbd_velocity',{'velocity_variance':5.},'task')
                self.assertEqual(client.writes,2)
                client.value = 5.
                recovered = facade().feedback_edit('g','rbd_velocity',{'velocity_variance':5.},'task')
                self.assertEqual((recovered['version'], recovered['state'], client.writes),(2,'COMPLETE',2))
                self.assertTrue(recovered['replayed'])
                updated = next(n for n in recovered['compiled']['nodes'] if n['node_id'] == 'rbd_velocity')
                self.assertEqual(updated['parameters'],{'velocity_variance':5.})
                client.wrong_node = True
                with self.assertRaisesRegex(ValueError, 'trusted registered-node semantic readback'):
                    facade().feedback_edit('g','rbd_velocity',{'velocity_variance':6.},'task')
                self.assertEqual(client.writes,2)
                for bad in ({'snippet':'arbitrary code'}, {'velocity_variance':-1.}, {'velocity_variance':1.,'snippet':''}):
                    with self.assertRaises(ValueError): facade().feedback_edit('g','rbd_velocity',bad,'task')
                self.assertEqual(client.writes,2)

    def test_dispatched_completion_two_controllers_commit_one_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / 'run.json'
            manifest.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':'race','assets':[]}))
            run = DiagnosticRun(manifest); run.pipeline_task_id='task'; run.artifact_registry=None
            class Client:
                value = 1; writes = 0
                def call(self, command, args):
                    if command == 'node.parms': return {'parms':{'size':self.value}}
                    self.value=args['parms']['size']; self.writes+=1; return {}
            client = Client(); versions=FeedbackVersions(run)
            graph={'graph_hash':'a'*64,'nodes':[{'node_id':'source','parameters':{}}],'connections':[],'outputs':[]}
            with patch.object(versions,'_complete',side_effect=OSError('original controller delayed after readback')):
                with self.assertRaises(OSError): versions.apply('g',graph,'/obj/source','source',{'size':2},client)
            delayed = versions.current('g')
            recovered = FeedbackVersions(run).apply('g',graph,'/obj/source','source',{'size':2},client)
            self.assertTrue(recovered['replayed'])
            versions._complete('g',1,delayed,client)
            self.assertEqual(client.writes,1)
            with run._connect() as db:
                events = [json.loads(row[0]) for row in db.execute('SELECT payload FROM events')]
            self.assertEqual(sum(e['kind']=='feedback_version_committed' for e in events),1)
            changed = json.loads(json.dumps(delayed)); changed['graph_hash']='b'*64
            with self.assertRaisesRegex(ValueError,'completion payload changed'):
                versions._complete('g',1,changed,client)
            client.value=3
            with self.assertRaisesRegex(ValueError,'completion readback changed'):
                versions._complete('g',1,delayed,client)
