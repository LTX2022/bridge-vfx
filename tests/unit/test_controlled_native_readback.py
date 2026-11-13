"""Formal add-on readback with explicit bottom HOM/USD API substitutes only."""
import hashlib
import importlib.util
import os
import json
import copy
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


def load_tool(name):
    spec = importlib.util.spec_from_file_location('controlled_test_' + name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControlledNativeReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='controlled-native-readback-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.modules = patch.dict(sys.modules)
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.environment = patch.dict(os.environ, {'BRIDGE_SKILLS_STATE_ROOT': str(self.root / 'state'),
            'HOUDINI_BRIDGE_STATE_DIR': str(self.root / 'houdini'), 'BRIDGE_SKILLS_SCHEDULER_ROOT': str(self.root / 'scheduler')})
        self.environment.start(); self.addCleanup(self.environment.stop)
        from vfx_pipeline.workbuddy_assembly import software_host_client
        self.client, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.root / 'host')
        boundary = load_tool('native_schema_test_boundary')
        self.api = load_tool('software_render_api_boundary')
        version = getattr(self, 'native_version', '21.0.631')
        profile = getattr(self, 'scene_profile', 'sphere_ground_v2')
        interfaces, states, ports = self.api.static_scene_interface_profiles(ROOT, version)
        boundary.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', version,
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        self.hou = sys.modules['hou']
        self.api.install_stage_api(self.hou)
        self.api.install_material_binding_api()
        self.native_graph_boundary = self.api.install_graph_native_layout_api(self.hou)
        from vfx_pipeline import graph_catalog
        from vfx_pipeline.graph_trial import GraphExecutor
        from vfx_pipeline.scene_lease import SceneLeaseStore, SceneLeaseGuard
        selector = {'schema':'bridge.registered-domain-construction/1', 'domain_pack':'material_lookdev_v1',
                    'houdini_version':version, 'scene_profile':profile}
        compiled = graph_catalog.compile_proposal(selector)
        self.task_id = 'controlled-readback'
        self.addon._TASK_HOST_IDENTITY = dict(self.addon._host_identity(), task_id=self.task_id,
            pid=os.getpid(), launch_nonce='explicit-unit-readback',
            plugin_build=self.addon._FX_LOADED_ADDON_SHA256, version=version)
        self.selector, self.compiled = selector, compiled
        root_path = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((self.task_id + ':' + compiled.graph_hash).encode()).hexdigest()
        host = self.addon.graph_worker_identity()
        store = SceneLeaseStore(self.root / 'leases.json')
        lease = store.acquire(task_id=self.task_id, root=root_path,
            **{key: host[key] for key in ('session_id','process_generation','scene_id')})
        guard = SceneLeaseGuard(lease, lambda: store.current(lease.session_id, lease.scene_id), self.addon.graph_worker_identity)
        with store.operation(lease):
            built = GraphExecutor(self.client, {}, lease_guard=guard).execute(self.task_id, compiled)
            self.assertTrue(built['construction_executed'], built)
            self.built = built
            config_path = ROOT / 'docs/official-baselines/karma' / (
                'frozen-scene-v2.json' if profile == 'sphere_ground_v2' else 'frozen-scene.json')
            raw = config_path.read_bytes()
            frozen = [{'index':0, 'asset_id':'karma-static-scene', 'semantic_role':'render_scene_configuration',
                       'source_uri':str(config_path), 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)}]
            self.frozen = frozen
            self.addon.graph_initialize_registered_domain(self.task_id, selector, built['topology'],
                compiled.graph_hash, self.root / 'render', frozen_input_manifest=frozen)
            self.contract = self.addon._fx_capture_scene_contract(self.task_id)
        self.roles = {item['role']:item['path'] for item in self.contract['nodes']}
        self.render = self.hou.node(self.roles['render'])
        self.native = self.hou.node(self.roles['settings'])
        terminal = self.hou.node(self.roles['settings_binding'])
        self.stage = terminal.stage(frame=1, apply_viewport_overrides=False, ignore_errors=False)
        self.settings = self.stage.GetPrimAtPath(self.render.parm('rendersettings').eval())
        self.product = self.stage.GetPrimAtPath(self.settings.GetRelationship('products').GetTargets()[0])
        self.var = self.stage.GetPrimAtPath(self.product.GetRelationship('orderedVars').GetTargets()[0])
        from houdini_bridge.render_color_facts import collect_render_color_facts
        self.color_fact = collect_render_color_facts(self.stage, frame=1, settings_path=str(self.settings.GetPath()))
        self.policy = {'policy':'controlled_output_v1', 'scene_variant':'sphere_ground_v2', 'resolution':[128,128],
                       'frames':[1], 'channels':['R','G','B','A']}
        self.color = {'schema':'bridge.project-color/1.0','project_id':'controlled','revision':1,
                      'colorspace':'ACEScg','source':'human_project_selection'}

    def readback(self):
        return self.addon._fx_controlled_output_readback(self.render, self.settings, self.color_fact,
            1, self.contract, self.policy, self.color)

    def test_formal_frozen_v2_readback_accepts_stock_karma_beauty(self):
        self.assertEqual(self.contract['frozen_scene_parameters']['profile'], 'sphere_ground_v2')
        self.assertEqual(set(self.contract['frozen_scene_parameters']['geometry']), {'Sphere','Ground'})
        namespace = self.contract['frozen_scene_parameters']['fields']['settings.rendervarsparentprimpath']
        beauty_path = namespace + '/beauty'
        self.assertEqual(self.native.parm('beauty').eval(), 1)
        self.assertEqual(self.native.parm('rendervarsparentprimpath').eval(), namespace)
        self.assertEqual(self.hou.node(self.roles['render_product']).parm('orderedVars').eval(), beauty_path)
        self.assertEqual(self.product.GetRelationship('orderedVars').GetTargets(), [beauty_path])
        self.assertEqual(str(self.var.GetPath()), beauty_path)
        self.assertEqual(self.settings.GetAttribute('resolution').Get(1), [128,128])
        for name, kind, value in [('sourceName','string','C.*[LO]'), ('sourceType','string','lpe'),
                                 ('dataType','token','color4f'), ('driver:parameters:aov:husk:name','string','C')]:
            with self.subTest(attribute=name):
                attribute = self.var.GetAttribute(name)
                self.assertEqual(str(attribute.GetTypeName()), kind)
                self.assertEqual(attribute.Get(1), value)
        result = self.readback()
        self.assertEqual(result['output_color_route'], {'source': 'scene_linear', 'output': 'ACEScg'})
        self.assertEqual(result['resolution'], [128,128])
        self.assertEqual(result['renderer'], 'BRAY_HdKarma')
        self.assertEqual(result['aov_semantics'], 'karma_beauty_lpe_v1')
        self.assertFalse(result['motion_blur'])
        self.assertEqual(result['image_filters'], [])
        self.assertRegex(result['route_sha256'], r'^[a-f0-9]{64}$')

    def test_native_output_color_attributes_are_authored_and_strictly_verified(self):
        original = copy.deepcopy(self.color_fact)
        for field, change in [('source_colorspace', {'value': 'Raw'}),
                              ('output_colorspace', {'value': 'Linear Rec.709 (sRGB)'}),
                              ('output_colorspace', {'type_name': 'token'}),
                              ('output_colorspace', {'authored': False}),
                              ('source_colorspace', None)]:
            with self.subTest(field=field, change=change):
                self.color_fact = copy.deepcopy(original)
                attributes = self.color_fact['products'][0]['attributes']
                key = 'driver:parameters:husk:' + field
                if change is None:
                    attributes.pop(key)
                else:
                    attributes[key].update(change)
                with self.assertRaises(self.addon.BridgeCommandError) as failure:
                    self.readback()
                self.assertEqual(failure.exception.code, 'CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY')
        self.color_fact = original

    def test_locked_definition_nodes_bind_boundary_and_legacy_full_contract(self):
        root = self.hou.node(self.built['topology']['root'])
        self.assertEqual(self.native_graph_boundary['locked_definition_nodes'], 18)
        self.assertEqual(len(root.allSubChildren()), 41)
        self.assertEqual(len(root.allSubChildren(recurse_in_locked_nodes=False)), 23)
        interior = {node.path() for node in self.native.allSubChildren()}
        self.assertEqual(len(interior), 18)
        public = {record['path'] for record in self.contract['nodes']}
        self.assertEqual(self.contract['schema'], 'houdini.task_scene_contract/2.1')
        self.assertEqual(self.contract['capture_policy'], 'locked-hda-definition/1')
        boundary = next(item for item in self.contract['hda_boundaries'] if item['path'] == self.native.path())
        self.assertEqual(interior, {record['path'] for record in boundary['internal_nodes']})
        self.assertTrue(interior.isdisjoint(public))
        self.assertEqual(boundary['static_fingerprint']['node_count'], 18)
        self.assertTrue(boundary['static_fingerprint']['identity_complete'])
        legacy = self.addon._fx_capture_scene_contract(self.task_id, capture_policy='legacy-full/2.0')
        self.assertEqual(legacy['schema'], 'houdini.task_scene_contract/2.0')
        self.assertNotIn('capture_policy', legacy)
        self.assertNotIn('hda_boundaries', legacy)
        self.assertTrue(interior <= {record['path'] for record in legacy['nodes']})
        self.assertTrue(all('parameter_channels' in record for record in legacy['nodes']))
        self.assertEqual(self.hou.node(self.roles['geometry_network']).type().nameWithCategory(), 'Object/geo')

    def test_locked_definition_nodes_survive_fake_hip_save_reopen(self):
        manifest = self.addon._fx_manifest(self.task_id)[1]
        environment = self.addon._fx_project_environment_readback(manifest, self.task_id)
        settings = self.hou.node(self.roles['settings'])
        resources = {}
        for name in ('dcmfilename', 'productName'):
            matches = [item for item in environment['resources']
                       if item['role'] == 'settings' and item['path'] == settings.path()
                       and item['type'] == 'Lop/karmarendersettings' and item['parameter'] == name]
            self.assertEqual(len(matches), 1)
            item = matches[0]
            resources[name] = (item['raw'], item['evaluated'])
            self.assertTrue(Path(item['raw']).is_absolute())
            self.assertNotIn('$HIP', item['raw'])
            parm = settings.parm(name)
            self.assertEqual((parm.unexpandedString(), parm.eval()), resources[name])
        before_contract = self.addon._fx_capture_scene_contract(self.task_id)
        definition_digests = {item['path']: [row['sha256'] for row in item['definitions']]
                              for item in before_contract['hda_boundaries']}
        hip = self.root/'locked-definition.hip'
        saved = self.addon.dispatch('scene.save_hip', {'task_id': self.task_id, 'path': str(hip)})
        self.assertEqual(saved['scene_contract'], before_contract)
        self.assertEqual(saved['scene_contract_sha256'], self.addon._fx_scene_contract_digest(before_contract))
        self.hou.hipFile.hasUnsavedChanges = lambda: True
        result = self.addon.dispatch('scene.reopen_task_hip', {'task_id': self.task_id,
            'path': str(hip), 'sha256': saved['sha256'], 'scene_contract_sha256': saved['scene_contract_sha256'],
            'operation_id': 'formal-handoff', 'request_id': 'formal-handoff'})
        self.assertTrue(result['parameters_verified'])
        self.assertEqual(Path(self.hou.hipFile.path()), hip)
        root = self.hou.node(self.built['topology']['root'])
        settings = self.hou.node(self.roles['settings'])
        self.assertEqual(len(root.allSubChildren()), 41)
        self.assertEqual(len(root.allSubChildren(recurse_in_locked_nodes=False)), 23)
        self.assertTrue(settings.isLockedHDA())
        self.assertEqual(len(settings.allSubChildren()), 18)
        reopened_contract = self.addon._fx_capture_scene_contract(self.task_id)
        self.assertEqual(reopened_contract, saved['scene_contract'])
        self.assertEqual({item['path']: [row['sha256'] for row in item['definitions']]
                          for item in reopened_contract['hda_boundaries']}, definition_digests)
        for name, expected in resources.items():
            parm = settings.parm(name)
            self.assertEqual((parm.unexpandedString(), parm.eval()), expected)
        legacy = self.addon._fx_capture_scene_contract(self.task_id, capture_policy='legacy-full/2.0')
        legacy['schema'] = 'houdini.task_scene_contract/1.0'
        legacy.pop('owned_roots')
        for row in legacy['nodes']: row.pop('parameter_channels', None)
        saves_path = self.addon._fx_task_saves_path(self.task_id)
        store = json.loads(saves_path.read_text())
        store['saves'][-1].update(scene_contract=legacy,
            scene_contract_sha256=self.addon._fx_scene_contract_digest(legacy))
        saves_path.write_text(json.dumps(store))
        reopened = self.addon.dispatch('scene.reopen_task_hip', {'task_id': self.task_id,
            'path': str(hip), 'sha256': saved['sha256']})
        self.assertTrue(reopened['parameters_verified'])
        self.assertNotIn('scene_transition', reopened)
        self.assertEqual(Path(self.hou.hipFile.path()), hip)

    def saved_reopen(self, operation='path-reopen'):
        hip = self.root/'path-sensitive.hip'
        saved = self.addon.dispatch('scene.save_hip', {'task_id': self.task_id, 'path': str(hip)})
        self.hou.hipFile.hasUnsavedChanges = lambda: True
        params = {'task_id': self.task_id, 'path': str(hip), 'sha256': saved['sha256'],
                  'scene_contract_sha256': saved['scene_contract_sha256'],
                  'operation_id': operation, 'request_id': operation}
        return hip, saved, params

    def test_task_reopen_common_exit_path_failures_and_transaction_rollback(self):
        hip, saved, params = self.saved_reopen()
        original_load, original_name = self.hou.hipFile.load, self.hou.hipFile.setName
        saves_path = self.addon._fx_task_saves_path(self.task_id)
        for fault in ('warning', 'name_exception', 'wrong_path', 'rebind', 'completion'):
            with self.subTest(fault=fault):
                args = dict(params, operation_id=fault, request_id=fault)
                before_save = saves_path.read_bytes()
                runner = self.addon.fx_operation_runner(self.task_id)
                before_generation = runner.generation
                manifest_root, manifest = self.addon._fx_manifest(self.task_id)
                before_manifest = self.addon._fx_snapshot_manifest_persistence(manifest_root, self.task_id)
                calls = []
                def load(path, **options):
                    calls.append(('load', path))
                    result = original_load(path, **options)
                    if fault == 'warning' and not options.get('ignore_load_warnings'):
                        raise self.hou.LoadWarning('explicit software load warning')
                    return result
                def name(path):
                    calls.append(('setName', path))
                    if fault == 'name_exception': raise RuntimeError('explicit setName failure')
                    return original_name(str(hip.parent/'wrong.hip') if fault == 'wrong_path' else path)
                @contextmanager
                def rebind(*args, **kwargs):
                    self.assertEqual(args[2:4], (str(hip), saved['sha256']))
                    if fault == 'rebind': raise RuntimeError('explicit rebind failure')
                    with real_rebind(*args, **kwargs) as result: yield result
                real_rebind = self.addon._fx_registered_rebind_saved_contract
                real_complete = self.addon._fx_scene_transition_complete
                with patch.object(self.hou.hipFile, 'load', side_effect=load), \
                        patch.object(self.hou.hipFile, 'setName', side_effect=name), \
                        patch.object(self.hou.hipFile, 'save', side_effect=AssertionError('reopen saved HIP')), \
                        patch.object(self.addon, '_fx_registered_rebind_saved_contract', side_effect=rebind), \
                        patch.object(self.addon, '_fx_scene_transition_complete',
                            side_effect=RuntimeError('explicit completion failure') if fault == 'completion' else real_complete), \
                        patch.object(self.addon, '_root_lease_write', wraps=self.addon._root_lease_write) as lease_write:
                    if fault == 'warning':
                        result = self.addon.dispatch('scene.reopen_task_hip', args)
                        self.assertEqual(result['load_warnings'], ['explicit software load warning'])
                        self.assertEqual(result['scene_transition']['state'], 'COMPLETED')
                    else:
                        with self.assertRaises(Exception): self.addon.dispatch('scene.reopen_task_hip', args)
                        self.assertEqual(saves_path.read_bytes(), before_save)
                        self.assertEqual(runner.generation, before_generation)
                        self.assertEqual(self.addon._fx_snapshot_manifest_persistence(manifest_root, self.task_id), before_manifest)
                        self.assertEqual(runner._load()['scene_transitions'][fault]['state'], 'INTENT')
                        if fault in {'name_exception', 'wrong_path'}: lease_write.assert_not_called()
                self.assertEqual(sum(call[0] == 'load' for call in calls), 2 if fault == 'warning' else 1)
                self.assertEqual(sum(call[0] == 'setName' for call in calls), 1)
                self.assertEqual(hashlib.sha256(hip.read_bytes()).hexdigest(), saved['sha256'])
                snapshot = self.addon._fx_scene_transition_snapshot(self.task_id, params, require_source=True)
                self.assertEqual(hashlib.sha256(Path(snapshot['snapshot_path']).read_bytes()).hexdigest(), saved['sha256'])

    def test_task_reopen_unsaved_replay_requires_exact_path_content_and_transition(self):
        hip, saved, params = self.saved_reopen()
        completed = self.addon.dispatch('scene.reopen_task_hip', params)
        transition = completed['scene_transition']
        saves_path = self.addon._fx_task_saves_path(self.task_id)
        original_saves = saves_path.read_bytes()
        current_identity = dict(self.addon._TASK_HOST_IDENTITY)
        original_name = self.hou.hipFile.setName
        parm = self.hou.node(self.roles['settings']).parm('dcmfilename')
        raw = parm.unexpandedString()
        for fault in ('none', 'snapshot_path', 'parameter', 'identity', 'active_transition', 'active_contract', 'request_contract', 'request_sha'):
            with self.subTest(fault=fault):
                saves_path.write_bytes(original_saves)
                self.addon._TASK_HOST_IDENTITY = dict(current_identity)
                original_name(str(hip)); parm.set(raw)
                args = dict(params)
                if fault == 'snapshot_path': original_name(transition['result']['snapshot_path'])
                if fault == 'parameter': parm.set('changed')
                if fault == 'identity': self.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'other-launch'
                if fault in {'active_transition', 'active_contract'}:
                    store = json.loads(original_saves)
                    if fault == 'active_transition': store['active_scene']['transition_operation_id'] = 'another-reopen'
                    else: store['active_scene']['scene_contract_sha256'] = '0'*64
                    saves_path.write_text(json.dumps(store))
                if fault == 'request_contract': args['scene_contract_sha256'] = '0'*64
                if fault == 'request_sha': args['sha256'] = '0'*64
                with patch.object(self.hou.hipFile, 'load', side_effect=AssertionError('replay loaded HIP')), \
                        patch.object(self.hou.hipFile, 'setName', side_effect=AssertionError('replay renamed HIP')), \
                        patch.object(self.hou.hipFile, 'save', side_effect=AssertionError('replay saved HIP')):
                    if fault == 'none':
                        replay = self.addon.dispatch('scene.reopen_task_hip', args)
                        self.assertTrue(replay['idempotent'])
                        self.assertEqual(replay['scene_transition'], transition)
                    else:
                        with self.assertRaises(self.addon.BridgeCommandError): self.addon.dispatch('scene.reopen_task_hip', args)
        saves_path.write_bytes(original_saves)
        self.addon._TASK_HOST_IDENTITY = current_identity
        original_name(str(hip)); parm.set(raw)
        with patch.object(self.hou, 'playbar', SimpleNamespace(frameRange=lambda:(1,1), playbackRange=lambda:(1,1)), create=True), \
                patch.object(self.hou, 'takes', SimpleNamespace(currentTake=lambda:SimpleNamespace(name=lambda:'Main')), create=True):
            fingerprint = self.addon._bridge_scene_fingerprints(self.task_id)
        self.assertEqual(fingerprint['global_scene_fingerprint']['details']['hip_path'], str(hip))

    def test_task_reopen_intent_proves_named_full_scene_without_active_record(self):
        hip, saved, params = self.saved_reopen()
        saves_path = self.addon._fx_task_saves_path(self.task_id)
        original_saves = saves_path.read_bytes()
        original_load = self.hou.hipFile.load
        for fault in ('snapshot_path', 'parameter', 'incomplete_contract', 'none', 'old_active',
                      'warning', 'warning_identity', 'warning_epoch', 'missing_load_fact',
                      'completion_failure', 'completed_then_raised'):
            with self.subTest(fault=fault):
                saves_path.write_bytes(original_saves)
                if fault == 'old_active':
                    self.addon.dispatch('scene.reopen_task_hip', dict(params,
                        operation_id='previous-active', request_id='previous-active'))
                args = dict(params, operation_id='intent-'+fault, request_id='intent-'+fault)
                def load(path, **options):
                    result = original_load(path, **options)
                    if fault.startswith('warning') and not options.get('ignore_load_warnings'):
                        raise self.hou.LoadWarning('explicit software load warning')
                    return result
                from contextlib import ExitStack
                with ExitStack() as stack:
                    stack.enter_context(patch.object(self.hou.hipFile, 'load', side_effect=load))
                    stack.enter_context(patch.object(self.addon, '_fx_finalize_task_reopen',
                        side_effect=RuntimeError('interrupt before task handoff')))
                    if fault == 'snapshot_path':
                        stack.enter_context(patch.object(self.hou.hipFile, 'setName', side_effect=RuntimeError('interrupt before naming')))
                    if fault == 'missing_load_fact':
                        stack.enter_context(patch.object(self.addon, '_fx_task_reopen_record_loaded', side_effect=RuntimeError('load fact write failed')))
                    with self.assertRaises(RuntimeError): self.addon.dispatch('scene.reopen_task_hip', args)
                if fault == 'parameter': self.hou.node(self.roles['settings']).parm('dcmfilename').set('changed')
                if fault == 'incomplete_contract':
                    store = json.loads(saves_path.read_text())
                    contract = copy.deepcopy(saved['scene_contract']); contract['nodes'].pop()
                    store['saves'][-1].update(scene_contract=contract,
                        scene_contract_sha256=self.addon._fx_scene_contract_digest(contract))
                    saves_path.write_text(json.dumps(store))
                identity = dict(self.addon._TASK_HOST_IDENTITY)
                if fault == 'warning_identity': self.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'foreign-launch'
                if fault == 'warning_epoch':
                    for callback in self.hou.hipFile.eventCallbacks(): callback(self.hou.hipFileEventType.BeforeClear)
                runner = self.addon.fx_operation_runner(self.task_id)
                saved_before_reconcile = saves_path.read_bytes()
                generation_before_reconcile = runner.generation
                lease_before_reconcile = self.addon._root_lease_read(saved['scene_contract']['execution_root'])
                rejected = fault in {'snapshot_path', 'parameter', 'incomplete_contract', 'warning_identity', 'warning_epoch', 'missing_load_fact'}
                with patch.object(self.hou.hipFile, 'load', side_effect=AssertionError('reconcile/replay loaded HIP')), \
                        patch.object(self.hou.hipFile, 'setName', side_effect=AssertionError('reconcile/replay renamed HIP')), \
                        patch.object(self.hou.hipFile, 'save', side_effect=AssertionError('reconcile/replay saved HIP')):
                    if rejected:
                        with self.assertRaises(self.addon.BridgeCommandError) as caught:
                            self.addon.dispatch('scene.reconcile_transition', args)
                        self.assertEqual(caught.exception.code, 'PRODUCTION_SCENE_TRANSITION_RECONCILIATION_UNPROVEN')
                        self.assertEqual(runner._load()['scene_transitions'][args['operation_id']]['state'], 'INTENT')
                        self.assertEqual(saves_path.read_bytes(), saved_before_reconcile)
                        self.assertEqual(runner.generation, generation_before_reconcile)
                    else:
                        if fault in {'completion_failure', 'completed_then_raised'}:
                            complete = self.addon._fx_scene_transition_complete
                            def fail_completion(*arguments, **keywords):
                                if fault == 'completed_then_raised': complete(*arguments, **keywords)
                                raise OSError('interrupted completion persistence')
                            with patch.object(self.addon, '_fx_scene_transition_complete', side_effect=fail_completion):
                                with self.assertRaises(OSError): self.addon.dispatch('scene.reconcile_transition', args)
                            self.assertEqual(saves_path.read_bytes(), saved_before_reconcile)
                            self.assertEqual(runner.generation, generation_before_reconcile)
                            self.assertEqual(runner._load()['scene_transitions'][args['operation_id']]['state'], 'INTENT')
                            lease_after = self.addon._root_lease_read(saved['scene_contract']['execution_root'])
                            for key in ('owner_generation', 'owner_session_id', 'scene_epoch'):
                                self.assertEqual(lease_after[key], lease_before_reconcile[key])
                        result = self.addon.dispatch('scene.reconcile_transition', args)
                        self.assertTrue(result['reconciled'])
                        record = result['scene_transition']
                        self.assertEqual(record['state'], 'COMPLETED')
                        active = json.loads(saves_path.read_text())
                        self.assertEqual(active['active_generation'], runner.generation)
                        self.assertEqual(active['active_scene']['transition_operation_id'], args['operation_id'])
                        self.addon._check_executor_generation(self.task_id)
                        self.addon._root_lease_check(saved['scene_contract']['execution_root'], task_id=self.task_id, scope='sop', renew=False)
                        replay = self.addon.dispatch('scene.reopen_task_hip', args)
                        self.assertTrue(replay['idempotent'])
                        self.assertEqual(replay['scene_transition'], record)
                        if fault == 'warning':
                            self.assertEqual(record['post_load_identity']['scene_epoch'], record['before_scene_epoch']+2)
                self.addon._TASK_HOST_IDENTITY = identity

    def test_task_reopen_submit_render_uses_original_path_and_independent_snapshot(self):
        from dcc_task_runtime import owned_process
        hip, saved, params = self.saved_reopen()
        reopened = self.addon.dispatch('scene.reopen_task_hip', params)
        snapshot = Path(reopened['scene_transition']['result']['snapshot_path'])
        snapshot_bytes = snapshot.read_bytes()
        identity = self.addon._host_identity()
        supervisor = self.root/'software-supervisor'; supervisor.mkdir()
        key = supervisor/'receipt.key'; key.write_bytes(b's'*32); key.chmod(0o600)
        binding = {'task_id': self.task_id, 'launch_nonce': identity['launch_nonce']}
        owned_process._signed_write(supervisor, {'schema': owned_process.SCHEMA, 'event': 'started',
            'identity': binding, 'pid': identity['pid'], 'resource_budget': {
                'max_bytes': 64*1024*1024, 'roots': [str(self.root)]}})
        class Scheduler:
            root = self.root/'software-scheduler'
            def reserve(_self, owner, operation): return {'token': 'software-heavy-slot', 'generation': 1}
            def arm(_self, owner, operation, token, *, identity): pass
            def release(_self, owner, operation, token, *, stopped=True): pass
        runner = self.addon.fx_operation_runner(self.task_id)
        args = {'request_id': 'path-identity-render', 'frames': [1], 'budget_seconds': 30,
            'render_target': self.roles['render'], 'output_pattern': str(self.root/'render.%03d.exr'),
            'project_color': self.color, 'output_acceptance': self.policy}
        with patch.dict(os.environ, {'BRIDGE_OWNED_SUPERVISOR_DIR': str(supervisor),
                'BRIDGE_OWNED_SUPERVISOR_IDENTITY': json.dumps(binding)}), \
                patch.object(self.addon, '_FX_GRAPH_SCHEDULER', Scheduler()):
            for fault in ('wrong_path', 'snapshot_corruption', 'none'):
                with self.subTest(fault=fault):
                    self.hou.hipFile.setName(str(hip.parent/'other.hip') if fault == 'wrong_path' else str(hip))
                    snapshot.chmod(0o600)
                    snapshot.write_bytes(b'corrupted software snapshot' if fault == 'snapshot_corruption' else snapshot_bytes)
                    snapshot.chmod(0o400)
                    if fault == 'none':
                        result = runner.submit_render(args)
                        self.assertEqual(result['record']['state'], 'QUEUED')
                        self.assertEqual(result['record']['scene']['path'], str(hip))
                    else:
                        with self.assertRaises(self.addon.BridgeCommandError) as caught: runner.submit_render(args)
                        self.assertEqual(caught.exception.code, 'SCENE_STATE_DRIFT')

    def test_unlocked_hda_foreign_nodes_and_wrong_object_category_are_rejected(self):
        from types import SimpleNamespace
        root = self.hou.node(self.built['topology']['root'])
        root.setUserData('bridge_fx_owned', None)
        def initialize():
            return self.addon.graph_initialize_registered_domain(self.task_id, self.selector,
                self.built['topology'], self.compiled.graph_hash, self.root/'render', frozen_input_manifest=self.frozen)
        self.native.allowEditingOfContents()
        with self.assertRaises(self.addon.BridgeCommandError) as unlocked: initialize()
        self.assertEqual(unlocked.exception.code, 'SCENE_STATE_MISMATCH')
        self.native.matchCurrentDefinition()
        foreign = self.hou.node(self.roles['geometry_network']).createNode('sphere', 'foreign_node')
        with self.assertRaises(self.addon.BridgeCommandError) as unexpected: initialize()
        self.assertEqual(unexpected.exception.code, 'SCENE_STATE_MISMATCH')
        foreign.destroy()
        node_class = type(root)
        original = node_class.type
        def wrong_category(node):
            value = original(node)
            if node.path() == self.roles['geometry_network']:
                return SimpleNamespace(**{**vars(value), 'category':lambda:SimpleNamespace(name=lambda:'Obj')})
            return value
        with patch.object(node_class, 'type', wrong_category):
            with self.assertRaises(self.addon.BridgeCommandError) as wrong: initialize()
        self.assertEqual(wrong.exception.code, 'SCENE_STATE_MISMATCH')

    def test_native_denoiser_motion_or_resolution_outside_policy_rejected(self):
        for name, value in [('denoiser','oidn'), ('enablemblur',1), ('resolution',[256,128])]:
            with self.subTest(name=name):
                parm = self.addon._resolve_parm_target(self.native, [name])
                original = parm.eval()
                parm.set(value)
                try:
                    with self.assertRaises(self.addon.BridgeCommandError) as error: self.readback()
                    self.assertEqual(error.exception.code, 'CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY')
                finally: parm.set(original)

    def test_aov_semantics_extra_variables_or_filters_rejected(self):
        from houdini_bridge.render_color_facts import collect_render_color_facts
        def recapture():
            self.color_fact = collect_render_color_facts(self.stage, frame=1,
                settings_path=str(self.settings.GetPath()))
        original = dict(self.var.attributes)
        for key, value in [('sourceName','C'), ('sourceType','raw'), ('dataType','color3f'),
                           ('driver:parameters:aov:husk:name','diffuse')]:
            with self.subTest(key=key):
                self.var.attributes = dict(original)
                self.var.attributes[key] = self.api.Attribute(original[key].kind, value, key)
                recapture()
                self.assertEqual(self.product.GetRelationship('orderedVars').GetTargets(), [str(self.var.GetPath())])
                with self.assertRaises(self.addon.BridgeCommandError) as error: self.readback()
                self.assertEqual(error.exception.code, 'CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY')
        self.var.attributes = original
        product = self.stage.GetPrimAtPath(self.color_fact['products'][0]['path'])
        extra = self.api.Prim(str(self.var.GetPath()) + '_extra', 'RenderVar', self.stage)
        extra.attributes = dict(original)
        self.stage.prims[str(extra.GetPath())] = extra
        product.relations['orderedVars'].append(str(extra.GetPath()))
        recapture()
        with self.assertRaises(self.addon.BridgeCommandError): self.readback()
        product.relations['orderedVars'].remove(str(extra.GetPath()))
        recapture()
        self.settings.relations['husk:orderedImageFilters'] = ['/Filters/unexpected']
        with self.assertRaises(self.addon.BridgeCommandError): self.readback()

    def test_composed_usd_resolution_cannot_disagree_with_native_parameters(self):
        self.settings.attributes['resolution'] = self.api.Attribute('int2', [129,128], 'resolution')
        with self.assertRaises(self.addon.BridgeCommandError) as error: self.readback()
        self.assertEqual(error.exception.code, 'CONTROLLED_OUTPUT_CONFIG_OUTSIDE_POLICY')


if __name__ == '__main__': unittest.main()
