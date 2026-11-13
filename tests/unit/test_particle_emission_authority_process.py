"""Actual generated/TCP/owned-process P01 save/reopen at bottom HOM boundary."""
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import traceback
import unittest
from unittest.mock import patch

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.owned_process import OwnedProcessHandle
from houdini_bridge import native_particle_emission_program as program
from vfx_pipeline.production_hosts import stop_hosts
from vfx_pipeline.workbuddy_assembly import production_host_client
import particle_emission_process_boundary as boundary
import test_production_task_hosts as support

NATIVE_WRITES = frozenset({'parm_expression_write', 'parm_keys_write',
                         'parm_value_write', 'parm_keys_delete', 'parm_extrapolation_write'})


def tamper_expression(value, expression):
    if isinstance(value, dict):
        changed = 0
        for key, item in value.items():
            if isinstance(item, str) and item == expression:
                value[key] = 'import hou\nimport math\nimport hashlib\nreturn 0.0'
                changed += 1
            else:
                changed += tamper_expression(item, expression)
        return changed
    if isinstance(value, list):
        changed = 0
        for index, item in enumerate(value):
            if isinstance(item, str) and item == expression:
                value[index] = 'import hou\nimport math\nimport hashlib\nreturn 0.0'
                changed += 1
            else:
                changed += tamper_expression(item, expression)
        return changed
    return 0


class ParticleEmissionAuthorityProcessTests(unittest.TestCase):
    def verified_stop(self, project, state, identity):
        stopped = stop_hosts(project / 'control')
        receipt = stopped['houdini']['receipt']
        self.assertTrue(receipt['confirmed_exit'], stopped)
        self.assertTrue(receipt['heavy_slot_released'], stopped)
        work = Path(state['hosts']['houdini']['work_dir'])
        binding = json.loads((work / 'supervisor-binding.json').read_text(encoding='utf-8'))
        fact = OwnedProcessHandle(binding['directory'], binding['identity']).receipt()
        self.assertIsNotNone(fact)
        self.assertEqual(fact['pid'], identity['pid'])
        self.assertEqual(fact['observed_by'], 'owned_child_wait', fact)
        if os.name == 'nt':
            self.assertTrue(fact['child_wait_observed'], fact)
            self.assertEqual(fact['job_active_processes'], 0, fact)
        return dict(result=stopped, owned_stop_fact=fact)

    def host_client(self, project, suffix):
        state = json.loads((project / 'control/production-hosts.json').read_text(encoding='utf-8'))
        client = production_host_client(state['hosts']['houdini'], project / suffix)
        client.bind_task(state['task_id'])
        return state, client, client.call('ping', {})['task_host_identity']

    def saved_store(self, project, saved):
        matching = []
        for path in project.rglob('*.saves.json'):
            store = json.loads(path.read_text(encoding='utf-8'))
            receipts = [receipt for receipt in store.get('saves', [])
                        if Path(receipt['path']).resolve() == Path(saved['path']).resolve()
                        and receipt['sha256'] == saved['sha256']]
            if receipts:
                matching.append((path, receipts[-1]))
        self.assertEqual(len(matching), 1, [str(item[0]) for item in matching])
        return matching[0]

    def native_events(self, probe, phase):
        self.assertTrue(probe.is_file(), str(probe))
        return [event for line in probe.read_text(encoding='utf-8').splitlines()
                if (event := json.loads(line))['phase'] == phase]

    def assert_readback(self, readback, saved_context):
        self.assertEqual(readback['status'], 'BLOCKED', readback)
        self.assertEqual(readback['evidence_scope'], 'native_parameter_expression_only')
        self.assertEqual(readback['percentage'], 45.)
        self.assertEqual(readback['birth_rate'], 2300.)
        current = readback['context']
        self.assertEqual(current['basis'], saved_context['basis'])
        self.assertEqual(current['expression'], saved_context['expression'])
        self.assertEqual(current['channel'], saved_context['channel'])
        self.assertEqual(current['gates'], saved_context['gates'])
        self.assertEqual(current['limits'], saved_context['limits'])
        self.assertEqual(current['fps'], saved_context['fps'])
        self.assertEqual(current['birth_start_time'], saved_context['birth_start_time'])
        self.assertEqual(current['basis']['task_seed'], 173)
        self.assertEqual(current['gates']['emission/seed']['value'], 17.)
        self.assertAlmostEqual(readback['actual_rate'], program.rate_at_time(
            current['basis'], 45., current['time'], birth_rate_override=2300.))
        self.assertIn('same_build_POP_substep_emission_integration', readback['missing_evidence'])

    def archive(self, project, version, lifecycle, final_stop, probe):
        archive = os.environ.get('BRIDGE_TEST_P01_AUTHORITY_ARCHIVE')
        if not archive:
            return
        target = Path(archive) / version
        target.mkdir(parents=True, exist_ok=False)
        (target / 'lifecycle.json').write_text(
            json.dumps(lifecycle, ensure_ascii=False, indent=2), encoding='utf-8')
        (target / 'stop.json').write_text(
            json.dumps(final_stop, ensure_ascii=False, indent=2), encoding='utf-8')
        if probe.is_file():
            shutil.copyfile(probe, target / 'native-api-calls.jsonl')
        snapshot = project / 'control/snapshot'
        rows = []
        for path in sorted(snapshot.rglob('*.py')):
            relative = path.relative_to(snapshot)
            original = support.ROOT / relative
            rows.append(dict(path=relative.as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                current_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest()
                if original.is_file() else None))
        (target / 'snapshot-code.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
        files = [Path(__file__), Path(boundary.__file__), support.ROOT / 'tests/unit/software_host_bootstrap.py',
                 support.ROOT / 'tools/native_schema_test_boundary.py',
                 support.ROOT / 'tools/software_render_api_boundary.py']
        bindings = [dict(path=path.relative_to(support.ROOT).as_posix(),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in files]
        (target / 'bottom-api-source.json').write_text(json.dumps(bindings, indent=2), encoding='utf-8')
        for path in project.rglob('*.log'):
            if path.name in {'child.stderr.log', 'child.stdout.log', 'supervisor.stderr.log', 'supervisor.stdout.log'}:
                destination = target / 'logs' / path.relative_to(project)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        for filename in ('error.txt', 'result.json', 'completion.json'):
            for path in project.rglob(filename):
                destination = target / 'job-results' / path.relative_to(project)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

    def test_generated_workers_verified_save_restores_new_pid_nonce_without_apply(self):
        helper = support.ProductionTaskHostsTests(
            'test_registered_render_domains_formal_workers_feedback_and_new_instance_reopen')
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                project, api = base / '粒子 project with space', base / 'api'
                api.mkdir()
                (api / 'nuke.py').write_text(support.FAKE, encoding='utf-8')
                bootstrap = base / '固定粒子底层 API.py'
                bootstrap.write_text(boundary.launch_source(), encoding='utf-8')
                frozen = boundary.seed_manifest(base / '冻结发射 seed with space.json')
                host = helper.config(project, 'houdini', bootstrap, api)
                host.update(version=version, session_seconds=120)
                nuke = helper.config(project, 'nuke', support.SOFTWARE_PYTHON, api)
                nuke['session_seconds'] = 120
                support.prepare_graph(project, app=None, scheduler_root=project / 'scheduler',
                    execution_profile=True, render_profile=True,
                    production_host_config=host, production_nuke_config=nuke,
                    construction_input_manifest=frozen)
                probe = project / 'particle-native-calls.jsonl'
                phase_file = probe.with_suffix('.phase.json')
                lifecycle = dict(version=version, task_seed=173, native_seed=17.,
                    frozen_input_manifest=frozen, frozen_inputs_sha256=canonical_sha256(frozen),
                    scope='P01 verified-save/new-PID software parameter expressions; native POP NOT_RUN',
                    checkpoint_refusals=[])
                process = None
                with patch.dict(os.environ, {'BRIDGE_TEST_NATIVE_ROOT': str(support.ROOT),
                        'BRIDGE_TEST_NATIVE_VERSION': version, 'BRIDGE_TEST_P01_NATIVE_PROBE': str(probe),
                        'HOUDINI_BRIDGE_STATE_DIR': str(project / 'bridge-state'),
                        'BRIDGE_SKILLS_STATE_ROOT': str(project / 'runtime-state')}):
                    try:
                        phase_file.write_text(json.dumps('fresh_trial'), encoding='utf-8')
                        process = helper.boot(project)
                        for index, asset in enumerate(helper.tool(process, 'catalog', {})['assets']):
                            helper.tool(process, 'submit_observation', dict(asset_id=asset['asset_id'],
                                request_id='p01-observation-' + str(index), observation=dict(
                                    description='explicit bottom particle clock and native channels',
                                    dominant_colors=['grey'])))
                        selector = dict(schema='bridge.registered-domain-construction/1',
                            domain_pack='particles_v1', houdini_version=version)
                        proposal = helper.tool(process, 'graph_propose', dict(
                            request_id='p01-proposal', proposal=selector))
                        self.assertIn('graph_id', proposal, proposal)
                        trial = helper.completed_graph_trial(process, project, dict(
                            graph_id=proposal['graph_id'], request_id='p01-trial'))
                        lifecycle.update(proposal=proposal, trial=trial)
                        diagnostics = [path.read_text(encoding='utf-8', errors='replace')[-32768:]
                                       for path in project.rglob('error.txt')]
                        self.assertEqual(trial.get('state'), 'SUCCEEDED', str(trial) + '\n' + '\n'.join(diagnostics))
                        self.assertTrue(trial['stop_confirmed'], trial)
                        contract_digest = trial['result']['verification']['registered_scene_contract_sha256']
                        self.assertRegex(contract_digest, r'^[0-9a-f]{64}$')
                        handoff_records = []
                        for record_path in project.rglob('ops_*.json'):
                            record_store = json.loads(record_path.read_text(encoding='utf-8'))
                            transition = (record_store.get('scene_transitions') or {}).get(trial['operation_id'] + '-handoff')
                            if transition is not None:
                                handoff_records.append(transition)
                        self.assertEqual(len(handoff_records), 1, handoff_records)
                        self.assertEqual(handoff_records[0]['command'], 'scene.reopen_task_hip')
                        self.assertEqual(handoff_records[0]['state'], 'COMPLETED')
                        self.assertEqual(handoff_records[0]['request']['sha256'], trial['result']['artifact']['sha256'])
                        lifecycle['initial_handoff_transition'] = handoff_records[0]
                        inputs = list(project.glob('control/jobs/graph-jobs/*/attempt-*/inputs.json'))
                        self.assertEqual(len(inputs), 1, inputs)
                        worker_inputs = json.loads(inputs[0].read_text(encoding='utf-8'))
                        self.assertEqual(worker_inputs['frozen_input_manifest'], frozen)
                        self.assertEqual(worker_inputs['frozen_inputs_sha256'], canonical_sha256(frozen))
                        worker_identity = json.loads((inputs[0].parent / 'worker_identity.json').read_text(encoding='utf-8'))
                        worker_stop = OwnedProcessHandle(inputs[0].parent / 'owned-supervisor', dict(
                            operation_id=worker_inputs['operation_id'], attempt_token=worker_inputs['attempt_token'],
                            generation=worker_inputs['attempt_generation'])).receipt()
                        self.assertIsNotNone(worker_stop)
                        self.assertEqual(worker_stop['pid'], worker_identity['process_identity']['pid'])
                        self.assertEqual(worker_stop['observed_by'], 'owned_child_wait', worker_stop)
                        if os.name == 'nt':
                            self.assertTrue(worker_stop['child_wait_observed'], worker_stop)
                            self.assertEqual(worker_stop['job_active_processes'], 0, worker_stop)
                        with closing(sqlite3.connect(inputs[0].parent / 'journal.sqlite3')) as database:
                            entries = [json.loads(row[0]) for row in database.execute('SELECT payload FROM entries')]
                        initialization = next(entry for entry in entries if entry['intent'].get('kind') == 'domain.initialize')
                        self.assertEqual(initialization['status'], 'COMPLETE', initialization)
                        self.assertEqual(initialization['result']['frozen_inputs_sha256'], canonical_sha256(frozen))
                        lifecycle.update(worker_inputs=worker_inputs, initialization=initialization,
                                         worker_identity=worker_identity, verified_worker_stop=worker_stop)
                        roles = {address.rsplit('/', 1)[-1]: path
                                 for address, path in trial['result']['topology']['nodes'].items()}
                        state, client, before = self.host_client(project, 'before-probe')
                        self.assertNotEqual(worker_identity['process_identity']['pid'], before['pid'])
                        phase_file.write_text(json.dumps('apply'), encoding='utf-8')
                        applied = client.call('agent.fx.apply_candidate', dict(task_id=state['task_id'],
                            constraints={'fx': dict(domain_pack='particles_v1', run_mode='diagnose',
                                changes={'emission_variance': 45., 'birth_rate': 2300.})}))
                        context = applied['native_geometry_readback']['context']
                        self.assert_readback(applied['native_geometry_readback'], context)
                        self.assertEqual(context['basis']['birth_rate'], 1200.)
                        self.assertEqual(context['binding']['identity'], before)
                        expression = context['expression']
                        self.assertTrue(expression.startswith('import hou\nimport math\nimport hashlib\n'))
                        native_parameters = client.call('node.parms', dict(path=roles['emission'],
                            names=['constantrate', 'probemit', 'seed', 'jitterbirthtime']))['parms']
                        phase_file.write_text(json.dumps('save'), encoding='utf-8')
                        saved = helper.tool(process, 'task_save', {})
                        self.assertIn('saved_scene_id', saved, saved)
                        checkpoint = saved['scene_contract']['particle_emission_checkpoint']
                        self.assertIsInstance(checkpoint, dict)
                        self.assertTrue(checkpoint)
                        self.assertEqual(checkpoint['schema'], 'bridge.particle-emission-checkpoint/1')
                        self.assertEqual(checkpoint['identity'], before)
                        self.assertEqual(checkpoint['basis'], context['basis'])
                        self.assertEqual(checkpoint['expression'], expression)
                        self.assertEqual(checkpoint['channel'], context['channel'])
                        self.assertEqual(checkpoint['percentage'], 45.)
                        self.assertEqual(checkpoint['birth_rate'], 2300.)
                        self.assertTrue(checkpoint['parameters'])
                        store_path, receipt = self.saved_store(project, saved)
                        self.assertEqual(receipt['scene_contract']['particle_emission_checkpoint'], checkpoint)
                        lifecycle.update(applied=applied, host_before=before, saved=saved,
                                         saved_parameters=native_parameters, saved_checkpoint=copy.deepcopy(checkpoint))
                        helper.close(process)
                        process = None
                        lifecycle['stop_before_reopen'] = self.verified_stop(project, state, before)
                        phase_file.write_text(json.dumps('reopen'), encoding='utf-8')
                        process = helper.boot(project)
                        reopened = helper.tool(process, 'task_reopen', dict(saved_scene_id=saved['saved_scene_id']))
                        self.assertTrue(reopened.get('parameters_verified'), reopened)
                        self.assertTrue(reopened.get('nodes_verified'), reopened)
                        self.assertTrue(reopened.get('connections_verified'), reopened)
                        self.assertTrue(reopened.get('particle_emission_restored'), reopened)
                        state, client, after = self.host_client(project, 'after-probe')
                        self.assertNotEqual(before['pid'], after['pid'])
                        self.assertNotEqual(before['launch_nonce'], after['launch_nonce'])
                        self.assertEqual(client.call('node.parms', dict(path=roles['emission'],
                            names=['constantrate', 'probemit', 'seed', 'jitterbirthtime']))['parms'], native_parameters)
                        reopen_events = self.native_events(probe, 'reopen')
                        load_ends = [index for index, event in enumerate(reopen_events) if event['kind'] == 'hip_load_end']
                        self.assertTrue(load_ends, reopen_events)
                        self.assertFalse([event for event in reopen_events[load_ends[-1] + 1:]
                                          if event['kind'] in NATIVE_WRITES])
                        original_frame = client.call('scene.info', {})['frame']
                        phase_file.write_text(json.dumps('direct_readback'), encoding='utf-8')
                        evidence = client.call('agent.fx.collect_evidence', dict(task_id=state['task_id'],
                            constraints={'fx': dict(domain_pack='particles_v1', run_mode='diagnose', frames=[1, 25])},
                            render={'frame_range': {'start': 1, 'end': 25, 'step': 24}}))['evidence']
                        readbacks = evidence['native_geometry_readback']
                        self.assertEqual(set(readbacks), {'1', '25'})
                        for readback in readbacks.values():
                            self.assert_readback(readback, context)
                            self.assertEqual(readback['context']['binding']['identity'], after)
                        self.assertEqual(client.call('scene.info', {})['frame'], original_frame)
                        self.assertEqual(client.call('node.parms', dict(path=roles['emission'],
                            names=['constantrate', 'probemit', 'seed', 'jitterbirthtime']))['parms'], native_parameters)
                        direct_events = self.native_events(probe, 'direct_readback')
                        self.assertFalse([event for event in direct_events if event['kind'] in NATIVE_WRITES])
                        self.assertTrue([event for event in direct_events if event['kind'] == 'expression_eval'])
                        self.assertEqual({event['pid'] for event in direct_events}, {after['pid']})
                        lifecycle.update(reopened=reopened, host_after=after, reopen_native_events=reopen_events,
                            direct_readback=readbacks, direct_native_events=direct_events,
                            original_frame=original_frame, restored_frame=client.call('scene.info', {})['frame'])
                        helper.close(process)
                        process = None
                        lifecycle['stop_after_readback'] = self.verified_stop(project, state, after)
                        original_store = store_path.read_bytes()
                        for corruption in ('missing_checkpoint', 'tampered_expression_checkpoint'):
                            store = json.loads(original_store)
                            receipt = next(receipt for receipt in reversed(store['saves'])
                                if Path(receipt['path']).resolve() == Path(saved['path']).resolve()
                                and receipt['sha256'] == saved['sha256'])
                            contract = receipt['scene_contract']
                            if corruption == 'missing_checkpoint':
                                del contract['particle_emission_checkpoint']
                            else:
                                changed = tamper_expression(contract['particle_emission_checkpoint'], expression)
                                self.assertGreater(changed, 0, 'checkpoint must retain the issued native expression')
                            receipt['scene_contract_sha256'] = canonical_sha256(contract)
                            store_path.write_text(json.dumps(store, ensure_ascii=False), encoding='utf-8')
                            try:
                                phase_file.write_text(json.dumps(corruption), encoding='utf-8')
                                process = helper.boot(project)
                                refused_state, _, refused_identity = self.host_client(project, corruption + '-probe')
                                self.assertNotEqual(refused_identity['pid'], after['pid'])
                                self.assertNotEqual(refused_identity['launch_nonce'], after['launch_nonce'])
                                refusal = helper.tool(process, 'task_reopen', dict(saved_scene_id=saved['saved_scene_id']))
                                record = dict(corruption=corruption, result=refusal, host=refused_identity,
                                    rewritten_contract_sha256=receipt['scene_contract_sha256'])
                                lifecycle['checkpoint_refusals'].append(record)
                                self.assertTrue(refusal.get('isError'), refusal)
                                self.assertRegex(refusal.get('text', ''),
                                    r'PARTICLE_EMISSION_[A-Z_]+|ARTIFACT_STRUCTURE_MISMATCH|ARTIFACT_CONTRACT_INVALID')
                                self.assertEqual(hashlib.sha256(Path(saved['path']).read_bytes()).hexdigest(), saved['sha256'])
                                events = self.native_events(probe, corruption)
                                load_ends = [index for index, event in enumerate(events) if event['kind'] == 'hip_load_end']
                                after_load = events[load_ends[-1] + 1:] if load_ends else events
                                self.assertFalse([event for event in after_load if event['kind'] in NATIVE_WRITES])
                                record['native_events'] = events
                                helper.close(process)
                                process = None
                                record['verified_stop'] = self.verified_stop(project, refused_state, refused_identity)
                            finally:
                                store_path.write_bytes(original_store)
                    except Exception as error:
                        lifecycle['failure'] = dict(type=type(error).__name__,
                            message=str(error), traceback=traceback.format_exc())
                        raise
                    finally:
                        if process is not None:
                            helper.close(process)
                        final_stop = stop_hosts(project / 'control')
                        self.archive(project, version, lifecycle, final_stop, probe)


if __name__ == '__main__':
    unittest.main()
