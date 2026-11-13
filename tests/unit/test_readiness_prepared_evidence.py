from __future__ import annotations
import json
import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import build_readiness_report as reports
import readiness_evidence as evidence


class PreparedEvidenceContractTests(unittest.TestCase):
    def test_real_prior_graph_snapshot_rejected_after_digest_recomputation(self):
        logical = os.environ.get('BRIDGE_PREPARED_MATERIAL_CASE')
        if not logical:
            self.skipTest('existing material causal producer input required; target execution is not requested')
        path = Path(logical)
        original_bytes = path.read_bytes()
        case = json.loads(original_bytes)
        self.assertEqual(case['domain_pack'], 'material_lookdev_v1')
        self.assertEqual(case['graph_version'], 1)
        old = next(receipt['result']['scene_transition'] for receipt in case['stage_receipts']
                   if receipt.get('operation') == 'task_reopen' and receipt.get('graph_version') == 0)
        self.assertEqual(old['task_id'], case['controller_task_id'])
        prior = old['result']
        current = case['execution_fact']['scene']
        self.assertNotEqual(prior['snapshot_sha256'], current['snapshot_sha256'])
        self.assertEqual(evidence.digest(prior['snapshot_path']), prior['snapshot_sha256'])
        self.assertEqual(evidence.digest(current['snapshot_path']), case['save_receipt']['sha256'])
        fact = copy.deepcopy(case['execution_fact'])
        old_digest, old_fingerprint, old_request = (fact[key] for key in
                                                   ('operation_receipt_sha256', 'scene_fingerprint', 'request_sha256'))
        fact['scene'].update(snapshot_path=prior['snapshot_path'], snapshot_sha256=prior['snapshot_sha256'])
        fact['scene_fingerprint'] = evidence._canonical_sha256(
            {'scene': prior['snapshot_sha256'], 'config': fact['render_config']})
        request = {'task_id': fact['task_id'], 'frames': fact['frame_set'],
                   'budget_seconds': fact['budget_seconds'], 'scene_sha256': prior['snapshot_sha256'],
                   'render_target': fact['render_target'], 'output_pattern': fact['output_pattern'],
                   'dependencies': fact['dependencies']}
        fact['request_sha256'] = evidence._canonical_sha256(request)
        fact['operation_receipt_sha256'] = evidence._canonical_sha256(
            {key: value for key, value in fact.items() if key != 'operation_receipt_sha256'})
        case['execution_fact'] = fact
        for receipt in case['stage_receipts']:
            result = receipt.get('result')
            if isinstance(result, dict) and isinstance(result.get('execution_fact'), dict):
                result['execution_fact'] = copy.deepcopy(fact)
        replacements = {old_digest: fact['operation_receipt_sha256'],
                        old_fingerprint: fact['scene_fingerprint'], old_request: fact['request_sha256']}

        def replace(value):
            if isinstance(value, dict):
                return {key: replace(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace(child) for child in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        case = replace(case)
        self.assertEqual(evidence._formal_receipt_source_errors(fact, 'prior-snapshot'), [])
        self.assertEqual(evidence._render_file_errors(fact, 'prior-snapshot'), [])
        observed = evidence.inspect_prepared_case(case, ROOT)
        print('actual same-owner v0/v1 snapshot input:', json.dumps({
            'case_path': str(path), 'case_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'owner': case['controller_task_id'], 'graph_version': case['graph_version'],
            'prior_snapshot_sha256': prior['snapshot_sha256'], 'save_sha256': case['save_receipt']['sha256'],
            'recomputed_scene_fingerprint': fact['scene_fingerprint'],
            'recomputed_request_sha256': fact['request_sha256'],
            'recomputed_operation_receipt_sha256': fact['operation_receipt_sha256'],
            'observed': observed}, ensure_ascii=False), flush=True)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertNotIn('render', observed['stages'])
        self.assertFalse(any(proof['stage'] == 'render' for proof in observed['proofs']))
        self.assertTrue(any('snapshot hash does not bind current saved HIP' in error for error in observed['errors']))

    def case(self):
        return {'case_id': 'material_lookdev_v1__causal_candidate',
                'domain_pack': 'material_lookdev_v1', 'scenario': 'causal_candidate',
                'case_execution': 'prepared_production_controller', 'status': 'PASS',
                'controller_task_id': 'owner', 'graph_id': 'graph', 'graph_version': 1,
                'formal_controller_verified': True, 'formal_domain_lifecycle_verified': True,
                'stage_receipts': []}

    def test_operation_names_and_success_booleans_never_establish_stages(self):
        case = self.case()
        for operation in ('graph_trial', 'graph_status', 'feedback_edit', 'task_save',
                          'task_reopen', 'houdini_render_bounded', 'register_render_artifact',
                          'consume_artifact', 'nuke_input_binding'):
            case['stage_receipts'].append({'operation': operation, 'result': {
                'status': 'PASS', 'operation_id': 'claimed', 'structure_verified': True,
                'native_geometry_readback': True, 'usable_as_render_input': True}})
        observed = reports._domain_execution_binding({'cases': [case]}, case['domain_pack'], ROOT)
        self.assertEqual(observed['stages'], [])
        self.assertEqual(observed['operation_ids'], [])
        self.assertFalse(observed['passed'])
        self.assertTrue(any('full_semantic' in error for error in observed['errors']))
        self.assertFalse(any('production dispatch receipt missing' in error for error in observed['errors']))

    def test_diagnostic_fact_cannot_be_promoted_by_prepared_label_or_command(self):
        case = self.case()
        case['stage_receipts'] = [{'operation': 'operation_query', 'command': 'agent.fx.collect_evidence',
                                  'result': {'execution_fact': {
                                      'schema': 'bridge.houdini.software-boundary-fact/1.0',
                                      'state': 'COMPLETED', 'operation_id': 'claimed'}}}]
        result = evidence.inspect_prepared_case(case, ROOT)
        self.assertEqual(result['stages'], [])
        self.assertIn('diagnostic', result['errors'][0])

    def test_malformed_prepared_context_fails_closed(self):
        for mutation in ({'controller_task_id': None}, {'graph_version': True},
                         {'stage_receipts': None}, {'stage_receipts': [None, 1, []]},
                         {'save_receipt': {'scene_contract': []}},
                         {'stage_receipts': [{'operation': 'graph_version', 'task_id': 'owner',
                                              'graph_id': 'graph', 'result': {'version': 1, 'compiled': [1]}}]}):
            with self.subTest(mutation=mutation):
                case = dict(self.case(), **mutation)
                result = evidence.inspect_prepared_case(case, ROOT)
                self.assertEqual(result['stages'], [])
                self.assertTrue(result['errors'])
        self.assertEqual(evidence.inspect_prepared_case(None, ROOT)['stages'], [])
        host = {'task_id': 'owner', 'launch_nonce': 'nonce', 'pid': 51}
        source = {'manifest_path': str(ROOT / 'outputs/negative-fixture/control/run.json')}
        for invalid in ({'observed_by': None}, {'observed_by': 'controller_claim'},
                        {'identity': {'task_id': 'old-owner', 'launch_nonce': 'nonce'}},
                        {'pid': None}, {'pid': 52}, {'pid': 51.0},
                        {'exit_code': None}, {'exit_code': 1}, {'exit_code': False},
                        {'child_wait_observed': None}, {'child_wait_observed': False},
                        {'job_active_processes': None}, {'job_active_processes': 1},
                        {'job_active_processes': False}, {'job_active_processes': 0.0}):
            with self.subTest(invalid_stop_fields=invalid):
                payload = dict(identity={'task_id': 'owner', 'launch_nonce': 'nonce'}, pid=51,
                               exit_code=0, observed_by='owned_child_wait', platform='windows',
                               child_wait_observed=True, job_active_processes=0)
                payload.update(invalid)
                resolver = mock.Mock()
                resolver.read_supervisor.return_value = payload
                with self.assertRaises(ValueError):
                    evidence._prepared_stop(host, source, resolver)
        for invalid in (None, {}, {'pid': 51, 'exit_code': 0, 'platform': 'posix'},
                        {'pid': 51, 'identity': {'task_id': 'owner', 'launch_nonce': 'nonce'},
                         'exit_code': 0, 'platform': 'unknown'}):
            with self.subTest(invalid_common_stop=invalid):
                resolver = mock.Mock()
                resolver.read_supervisor.return_value = invalid
                with self.assertRaises(ValueError):
                    evidence._prepared_stop(host, source, resolver)
        resolver = mock.Mock()
        resolver.read_supervisor.side_effect = ValueError('SUPERVISOR_STOP_NOT_BOUND')
        with self.assertRaisesRegex(ValueError, 'SUPERVISOR_STOP_NOT_BOUND'):
            evidence._prepared_stop(host, source, resolver)
        resolver.read_supervisor.assert_called_once_with(
            str(Path(source['manifest_path']).parent / 'houdini-task-host/supervisor-nonce'),
            {'task_id': 'owner', 'launch_nonce': 'nonce'})

    def test_unsupported_schema_and_empty_typed_fact_do_not_gain_stages(self):
        for schema in ('bridge.houdini.lifecycle_fact/1.0',
                       'bridge.houdini.render.execution_fact/1.0',
                       'bridge.houdini.scene-transition-operation/1.0', 'claimed/1'):
            with self.subTest(schema=schema):
                case = self.case()
                case['stage_receipts'] = [{'task_id': 'owner', 'graph_id': 'graph', 'graph_version': 1,
                                          'result': {'execution_fact': {'schema': schema, 'command': 'scene.reopen_task_hip'}}}]
                self.assertEqual(evidence.inspect_prepared_case(case, ROOT)['stages'], [])

    def fixture(self, root):
        plugin = 'plugins/houdini/_impl/houdini_bridge_addon.py'
        source = root / 'source'
        current = source / plugin
        current.parent.mkdir(parents=True)
        current.write_bytes(b'finite source fixture, never executed')
        control = root / 'control'
        frozen = control / 'snapshot' / plugin
        frozen.parent.mkdir(parents=True)
        frozen.write_bytes(current.read_bytes())
        manifest = control / 'run.json'
        manifest.write_text('{}', encoding='utf-8')
        index = control / 'snapshot-manifest.json'
        index.write_text(json.dumps({'files': [{'path': plugin, 'sha256': evidence.digest(frozen)}]}), encoding='utf-8')
        binding = {'manifest_path': str(manifest), 'manifest_sha256': evidence.digest(manifest),
                   'snapshot_manifest_sha256': evidence.digest(index), 'repo_root': str(control / 'snapshot')}
        return source, binding, frozen, index

    def test_frozen_source_bytes_and_current_source_are_distinct_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            source, binding, frozen, _ = self.fixture(Path(directory))
            hashes, stale = evidence._prepared_source(binding, source, None)
            self.assertEqual(stale, [])
            self.assertEqual(hashes['plugins/houdini/_impl/houdini_bridge_addon.py'], evidence.digest(frozen))
            (source / 'plugins/houdini/_impl/houdini_bridge_addon.py').write_bytes(b'new current source')
            self.assertEqual(evidence._prepared_source(binding, source, None)[1], list(hashes))
            frozen.write_bytes(b'corrupt frozen source')
            with self.assertRaises(ValueError):
                evidence._prepared_source(binding, source, None)

    def test_duplicate_escaping_and_unbound_frozen_paths_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            source, binding, frozen, index = self.fixture(Path(directory))
            entry = {'path': 'plugins/houdini/_impl/houdini_bridge_addon.py', 'sha256': evidence.digest(frozen)}
            for entries in ([entry, entry], [dict(entry, path='../escape')],
                            [dict(entry, path='/absolute')], [dict(entry, sha256='0' * 64)], []):
                with self.subTest(entries=entries):
                    index.write_text(json.dumps({'files': entries}), encoding='utf-8')
                    changed = dict(binding, snapshot_manifest_sha256=evidence.digest(index))
                    with self.assertRaises(ValueError):
                        evidence._prepared_source(changed, source, None)

    def test_package_resolver_checks_same_logical_bytes_without_live_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, binding, frozen, index = self.fixture(base / 'original')
            package = base / 'package'
            logical_paths = [Path(binding['manifest_path']), index, frozen]
            path_map = {}
            for number, logical in enumerate(logical_paths):
                relative = f'evidence/file-{number}'
                physical = package / relative
                physical.parent.mkdir(parents=True, exist_ok=True)
                physical.write_bytes(logical.read_bytes())
                path_map[str(logical)] = {'original_logical_path': str(logical), 'package_relative_path': relative,
                                          'sha256': evidence.digest(logical), 'bytes': logical.stat().st_size,
                                          'modified_ns': logical.stat().st_mtime_ns}
            current = package / 'source/bridge-skills/plugins/houdini/_impl/houdini_bridge_addon.py'
            current.parent.mkdir(parents=True)
            current.write_bytes(frozen.read_bytes())
            map_file = package / 'evidence/bound-files/path-map.json'
            map_file.parent.mkdir(parents=True)
            map_file.write_text(json.dumps(path_map), encoding='utf-8')
            files = [{'path': path.relative_to(package).as_posix(), 'sha256': evidence.digest(path),
                      'bytes': path.stat().st_size} for path in package.rglob('*') if path.is_file()]
            manifest = package / 'package-manifest.json'
            manifest.write_text(json.dumps({'schema': 'bridge.s06.package_manifest/1.0',
                                            'file_count': len(files), 'files': files}), encoding='utf-8')
            resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=evidence.digest(manifest))
            frozen.unlink()
            self.assertEqual(evidence._prepared_source(binding, resolver.source_root, resolver)[1], [])
            (package / 'evidence/file-2').write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                evidence._prepared_source(binding, resolver.source_root, resolver)
