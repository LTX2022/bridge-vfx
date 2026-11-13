"""Current SAVE admission from addon originals; only the HOM boundary is fake."""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import unittest

import test_readiness_native_command_evidence as native
from houdini_bridge.operation_receipts import canonical_sha256, operation_receipt_sha256

evidence = native.evidence
ROOT = native.ROOT


class CurrentSaveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native.NativeCommandEvidenceTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.case = self.fixture.prepared_case()
        self.case['stage_receipts'] = self.case['stage_receipts'][1:]
        self.case['controller_source'] = self.fixture.source
        self.case['status'] = 'BLOCKED'

    def inspect(self, case=None, root=ROOT, resolver=None):
        return evidence.inspect_prepared_case(self.case if case is None else case, root, resolver=resolver)

    def replace_save(self, saved):
        case = deepcopy(self.case)
        case['save_receipt'] = saved
        case['stage_receipts'][-1]['result'] = saved
        return case

    def assert_rejected(self, result):
        self.assertFalse(any(proof.get('proof_scope') == 'current_task_save' for proof in result['proofs']))
        self.assertTrue(any(missing.startswith('save:') for missing in result['missing_proofs']))
        self.assertTrue(result['errors'])

    @contextmanager
    def changed_file(self, path, payload):
        path = Path(path)
        original, mode = path.read_bytes(), path.stat().st_mode
        try:
            path.chmod(0o600)
            path.write_bytes(payload)
            yield
        finally:
            path.write_bytes(original)
            path.chmod(mode)

    @staticmethod
    def rehash(record):
        record['request_sha256'] = canonical_sha256({key: record[key] for key in
            ('task_id', 'command', 'request_id', 'request')})
        record['facts']['handler_result_sha256'] = canonical_sha256(record['result'])
        record['operation_receipt_sha256'] = operation_receipt_sha256(record)

    def test_current_original_admits_only_save_without_domain_or_lifecycle_promotion(self):
        result = self.inspect()
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['stages'], ['save'])
        proof = result['proofs'][0]
        self.assertEqual(proof['proof_scope'], 'current_task_save')
        self.assertTrue(proof['current_source_matches'])
        self.assertFalse(proof['domain_lifecycle_verified'])
        self.assertEqual(proof['producer_sha256'], evidence.digest(Path(proof['producer_path'])))
        self.assertFalse(any(missing.startswith('save:') for missing in result['missing_proofs']))
        for stage in ('full_semantic', 'preview', 'output', 'recovery'):
            self.assertTrue(any(stage in missing for missing in result['missing_proofs']))
        self.assertEqual(self.case['status'], 'BLOCKED')

    def test_summary_and_verified_booleans_cannot_replace_native_original(self):
        saved = {key: value for key, value in self.case['save_receipt'].items() if key not in {
            'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent'}}
        case = self.replace_save(saved)
        case['typed_save_evidence'] = {'typed_save_verified': True, 'scope': 'current_task_save'}
        result = self.inspect(case)
        self.assertEqual(result['proofs'], [])
        self.assertTrue(any('typed save producer missing' in missing for missing in result['missing_proofs']))

    def test_changed_original_bytes_and_summary_storage_are_rejected(self):
        path = Path(self.case['save_receipt']['operation_store_path'])
        for payload in (path.read_bytes() + b'\n', b'{}\n', b'{"typed_save_verified":true}\n'):
            with self.subTest(payload=payload[-30:]), self.changed_file(path, payload):
                self.assert_rejected(self.inspect())

    def test_rehashed_upper_receipt_cannot_replace_persisted_request_or_host(self):
        for field, value in (('request_id', 'other-request'), ('operation_id', 'other-operation'),
                             ('pid', self.case['save_receipt']['operation_receipt']['host_identity']['pid'] + 1)):
            saved = deepcopy(self.case['save_receipt'])
            record = saved['operation_receipt']
            if field == 'pid':
                record['host_identity'][field] = value
            else:
                record[field] = record['request'][field] = value
            self.rehash(record)
            with self.subTest(field=field):
                self.assert_rejected(self.inspect(self.replace_save(saved)))

    def test_wrong_owner_graph_state_and_host_scene_identity_are_rejected(self):
        mutations = ({'task_id': 'other-owner'}, {'state': 'RUNNING'}, {'version': True}, {'version': -1})
        for mutation in mutations:
            case = deepcopy(self.case)
            case['stage_receipts'][0]['result'].update(mutation)
            with self.subTest(mutation=mutation):
                self.assert_rejected(self.inspect(case))
        saved = deepcopy(self.case['save_receipt'])
        saved['operation_receipt']['after_scene']['host_identity']['scene_epoch'] += 1
        self.rehash(saved['operation_receipt'])
        self.assert_rejected(self.inspect(self.replace_save(saved)))

    def test_current_hip_and_frozen_snapshot_bytes_are_both_required(self):
        saved = self.case['save_receipt']
        paths = (saved['path'], saved['operation_receipt']['facts']['saved_scene']['snapshot_path'])
        for path in paths:
            with self.subTest(path=path), self.changed_file(path, Path(path).read_bytes() + b'changed'):
                self.assert_rejected(self.inspect())

    def test_copied_producer_at_noncanonical_owner_or_operation_path_is_rejected(self):
        for relative in ('other-owner/original.json', 'copied-original.json'):
            saved = deepcopy(self.case['save_receipt'])
            copied = self.fixture.directory / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(Path(saved['operation_store_path']).read_bytes())
            saved['operation_store_path'] = str(copied)
            with self.subTest(relative=relative):
                self.assert_rejected(self.inspect(self.replace_save(saved)))

    def test_old_graph_version_and_feedback_dependencies_cannot_replace_current_save(self):
        case = deepcopy(self.case)
        case['graph_version'] = case['stage_receipts'][0]['result']['version'] = 1
        case['stage_receipts'][-1]['graph_version'] = 1
        self.assert_rejected(self.inspect(case))
        saved = deepcopy(self.case['save_receipt'])
        saved['feedback_dependencies'][-1] = saved['feedback_dependencies'][-1].replace(':version:0', ':version:1')
        self.assert_rejected(self.inspect(self.replace_save(saved)))
        case = deepcopy(self.case)
        case['stage_receipts'][-1]['graph_version'] = False
        self.assert_rejected(self.inspect(case))

    def test_earlier_same_owner_save_cannot_replace_latest_actual_save(self):
        saved = self.fixture.addon.dispatch('scene.save_hip', {
            'task_id': self.fixture.owner, 'operation_id': 'task-save-later-unit',
            'request_id': 'task-save-later-unit', 'frozen_input_manifest': [],
            'graph_hash': self.fixture.graph_hash, 'path': str(self.fixture.directory / 'later.hip'),
            'root_path': self.case['save_receipt']['scene_contract']['execution_root']})
        saved['feedback_dependencies'] = self.case['save_receipt']['feedback_dependencies']
        latest = deepcopy(self.case['stage_receipts'][-1])
        latest['result'] = saved
        case = deepcopy(self.case)
        case['stage_receipts'].append(latest)
        self.assert_rejected(self.inspect(case))
        case['save_receipt'] = saved
        self.assertEqual(self.inspect(case)['errors'], [])

    def test_source_must_match_current_graph_save_and_controller(self):
        for position in ('graph', 'save', 'controller'):
            case = deepcopy(self.case)
            source = dict(self.fixture.source, manifest_sha256='0' * 64)
            if position == 'controller':
                case['controller_source'] = source
            else:
                case['stage_receipts'][0 if position == 'graph' else -1]['source'] = source
            with self.subTest(position=position):
                self.assert_rejected(self.inspect(case))

    def test_corrupt_frozen_native_source_rejects_even_when_current_source_matches(self):
        path = Path(self.fixture.source['repo_root']) / 'plugins/houdini/_impl/houdini_bridge_addon.py'
        with self.changed_file(path, path.read_bytes() + b'corrupt'):
            self.assert_rejected(self.inspect())

    def test_stale_current_source_preserves_frozen_save_fact_but_blocks_current_claim(self):
        current_root = Path(self.fixture.source['repo_root'])
        path = current_root / 'packages/vfx-pipeline/src/vfx_pipeline/workbuddy_graph_mcp.py'
        current_copy = self.fixture.directory / 'current'
        for original in current_root.rglob('*.py'):
            target = current_copy / original.relative_to(current_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
        target = current_copy / path.relative_to(current_root)
        target.write_bytes(target.read_bytes() + b'\ncurrent changed\n')
        result = self.inspect(root=current_copy)
        self.assertFalse(result['proofs'][0]['current_source_matches'])
        self.assertFalse(result['supporting_evidence']['current_task_save']['current_source_matches'])
        self.assertTrue(any('current-source binding stale' in missing for missing in result['missing_proofs']))
        self.assertTrue(any('frozen source differs from current build' in error for error in result['errors']))

    def test_resolver_custom_export_roots_consume_unchanged_originals_without_keys(self):
        package = self.fixture.directory / 'export-package'
        saved = self.case['save_receipt']
        source = self.fixture.source
        logical_files = [Path(source['manifest_path']), Path(source['manifest_path']).parent / 'snapshot-manifest.json',
            Path(saved['operation_store_path']), Path(saved['path']),
            Path(saved['operation_receipt']['facts']['saved_scene']['snapshot_path'])]
        frozen_root = Path(source['repo_root'])
        for original in frozen_root.rglob('*.py'):
            logical_files.append(original)
            target = package / 'export/source' / original.relative_to(frozen_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
        mapping = {}
        for index, logical in enumerate(dict.fromkeys(logical_files)):
            relative = f'evidence/original-{index}'
            actual = package / relative
            actual.parent.mkdir(parents=True, exist_ok=True)
            actual.write_bytes(logical.read_bytes())
            mapping[str(logical)] = {'original_logical_path': str(logical), 'package_relative_path': relative,
                'sha256': evidence.digest(logical), 'bytes': logical.stat().st_size,
                'modified_ns': logical.stat().st_mtime_ns}
        map_file = package / 'metadata/path-map.json'
        map_file.parent.mkdir(parents=True)
        map_file.write_text(json.dumps(mapping), encoding='utf-8')
        entries = [{'path': path.relative_to(package).as_posix(), 'sha256': evidence.digest(path),
                    'bytes': path.stat().st_size} for path in package.rglob('*') if path.is_file()]
        manifest = package / 'metadata/manifest.json'
        manifest.write_text(json.dumps({'schema': 'bridge.s06.package_manifest/1.0',
            'file_count': len(entries), 'files': entries}), encoding='utf-8')
        resolver = evidence.PackageEvidenceResolver(package, manifest_sha256=evidence.digest(manifest),
            source_relative_root='export/source', manifest_path='metadata/manifest.json', map_path='metadata/path-map.json')
        for logical in dict.fromkeys(logical_files):
            logical.chmod(0o600)
            logical.unlink()
        result = self.inspect(root=resolver.source_root, resolver=resolver)
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['proofs'][0]['current_source_matches'])
        self.assertFalse(any(path.name == 'receipt.key' for path in package.rglob('*')))
        producer = result['proofs'][0]
        self.assertEqual(resolver.resolve(producer['producer_path'],
            expected_sha256=producer['producer_sha256']).read_bytes(),
            (json.dumps(saved['operation_receipt'], ensure_ascii=False, sort_keys=True,
                        separators=(',', ':')) + '\n').encode('utf-8'))


class PublicCurrentSaveEvidenceTests(unittest.TestCase):
    def test_fresh_public_graph_run_task_save_is_consumed_without_summary_generation_aliasing(self):
        import test_formal_public_task_save as public

        fixture = public.FormalPublicTaskSaveTests('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.host.hou.node(fixture.host.manifest()['execution_root']).destroy()
        from vfx_pipeline import graph_catalog
        from vfx_pipeline.feedback_versions import FeedbackVersions

        selector = {'schema': 'bridge.registered-domain-construction/1',
            'domain_pack': 'procedural_geometry_v1', 'houdini_version': fixture.host.version}
        compiled = graph_catalog.compile_proposal(selector)
        root_path = '/obj/BRIDGE_GRAPH_' + hashlib.sha256((fixture.owner + ':' + compiled.graph_hash).encode()).hexdigest()
        fixture.addon.dispatch('scene.create_task_root', {'task_id': fixture.owner,
            'parent': '/obj', 'type': graph_catalog.native_root_type(compiled),
            'root_layout': 'object_subnet/1' if graph_catalog.native_root_type(compiled) == 'subnet' else 'sop_geo/1',
            'root_name': root_path.rsplit('/', 1)[1]})
        layout = graph_catalog.native_layout(compiled, root_path)
        topology = {'root': root_path, 'nodes': {}, 'connections': []}
        for address, row in sorted(layout.items(), key=lambda item: item[1]['path'].count('/')):
            fixture.addon.dispatch('node.create', {'task_id': fixture.owner, 'parent': row['parent'],
                'type': row['type'], 'name': row['path'].rsplit('/', 1)[1]})
            topology['nodes'][address] = row['path']
        for connection in compiled.connections:
            source, target = topology['nodes'][connection.source_node], topology['nodes'][connection.target_node]
            binding = graph_catalog.resolve_connection_binding(graph_catalog.connection_binding(compiled, connection),
                fixture.addon.dispatch('node.info', {'task_id': fixture.owner, 'path': source}),
                fixture.addon.dispatch('node.info', {'task_id': fixture.owner, 'path': target}))
            if binding['kind'] == 'reference':
                if binding['field'].startswith('@'):
                    topology['connections'].append({'source': source, 'destination': target,
                        'kind': 'container_dependency', 'field': binding['field']})
                else:
                    fixture.addon.dispatch('node.set_parms', {'task_id': fixture.owner,
                        'path': target, 'parms': {binding['field']: source}})
                    topology['connections'].append({'source': source, 'destination': target,
                        'kind': 'reference', 'field': binding['field']})
            else:
                fixture.addon.dispatch('node.connect', {'task_id': fixture.owner, 'source': source,
                    'destination': target, 'input_index': binding['input_index'], 'output_index': binding['output_index']})
                topology['connections'].append({'source': source, 'destination': target,
                    'input_index': binding['input_index'], 'output_index': binding['output_index']})
        with native.patch.object(fixture.host.hou, 'expandString', side_effect=lambda value: value, create=True):
            fixture.addon.graph_initialize_registered_domain(fixture.owner, selector, topology,
                compiled.graph_hash, fixture.directory / 'render-output')
        with fixture.facade._connect() as database:
            database.execute('DELETE FROM feedback_versions')
        FeedbackVersions(fixture.facade).register_completed('public-save-graph', compiled.to_dict())
        saved = fixture.facade.task_save()
        current = fixture.facade.graph_version('public-save-graph')
        context = {'task_id': fixture.owner, 'graph_id': 'public-save-graph',
            'graph_version': current['version'], 'source': fixture.source}
        case = {'case_id': 'public-task-save-adapter-unit', 'status': 'BLOCKED',
            'controller_task_id': fixture.owner, 'graph_id': 'public-save-graph',
            'graph_version': current['version'], 'controller_source': fixture.source,
            'save_receipt': saved, 'stage_receipts': [dict(context, operation='graph_version', result=current),
                dict(context, operation='task_save', result=saved)]}
        result = evidence.inspect_prepared_case(case, ROOT)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['stages'], ['save'])
        self.assertTrue(result['proofs'][0]['current_source_matches'])
        self.assertEqual(result['proofs'][0]['operation_id'], fixture.transport.calls[0][1]['operation_id'])
        self.assertEqual(result['proofs'][0]['host_identity'], fixture.transport.health_reads[0])
        self.assertEqual(result['proofs'][0]['proof_scope'], 'current_task_save')
        self.assertFalse(result['proofs'][0]['domain_lifecycle_verified'])
        self.assertTrue(result['missing_proofs'])
        self.assertFalse(any(missing.startswith('save:') for missing in result['missing_proofs']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
