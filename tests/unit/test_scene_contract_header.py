"""Serialized capture-policy checks; no Houdini or other native host executes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/houdini-bridge/src'))
sys.path.insert(0, str(ROOT / 'tools'))

from houdini_bridge.operation_receipts import canonical_sha256, validate_scene_contract_header


def public_node(path, type_name, category):
    return {'path': path, 'type': type_name, 'category': category, 'parameters': {'value': 1},
            'parameter_channels': {'value': {'evaluated_available': True, 'expression': None,
                'reference_path': None, 'keyframes': []}}, 'inputs': []}


def definition(type_name, category):
    value = {'type': type_name, 'category': category, 'version': '',
             'sections': [{'name': 'Contents', 'bytes': 3,
                           'sha256': hashlib.sha256(b'abc').hexdigest()}],
             'extra_file_options': {'fixture': True}, 'extra_info': ''}
    return dict(value, sha256=canonical_sha256(value))


def locked_contract(task_id='task-1'):
    main = definition('Sop/fixture_asset::1', 'Sop')
    child = definition('Sop/fixture_child::1', 'Sop')
    return {'schema': 'houdini.task_scene_contract/2.1', 'capture_policy': 'locked-hda-definition/1',
        'task_id': task_id, 'execution_root': '/obj/root', 'owned_roots': ['/obj/root'],
        'nodes': [public_node('/obj/root', 'Object/geo', 'Object'),
                  public_node('/obj/root/asset', main['type'], main['category']),
                  public_node('/obj/root/renderer', 'Driver/usdrender', 'Driver')],
        'hda_boundaries': [{'path': '/obj/root/asset', 'type': main['type'], 'category': main['category'],
            'is_locked_hda': True, 'matches_current_definition': True, 'definition': main,
            'definitions': sorted([main, child], key=lambda item: item['sha256']),
            'internal_nodes': [
                {'path': '/obj/root/asset/child', 'type': child['type'], 'category': child['category'],
                 'definition_sha256': child['sha256']},
                {'path': '/obj/root/asset/child/null', 'type': 'Sop/null', 'category': 'Sop',
                 'definition_sha256': None}],
            'internal_node_count': 2, 'static_fingerprint': {'sha256': 'a' * 64,
                'node_count': 2, 'scope': 'locked-hda-internal/1', 'identity_complete': True,
                'errors': [], 'full_scene_identity_verified': False}}]}


def legacy_contract(task_id='task-1'):
    return {'schema': 'houdini.task_scene_contract/2.0', 'task_id': task_id,
        'execution_root': '/obj/root', 'nodes': [
            public_node('/obj/root', 'Object/geo', 'Object'),
            public_node('/obj/root/asset/inside', 'Sop/null', 'Sop'),
            public_node('/obj/root/renderer', 'Driver/usdrender', 'Driver')]}


class SceneContractHeaderTests(unittest.TestCase):
    def test_policy_selection_keeps_legacy_bytes_and_requires_explicit_v1_entry(self):
        contract = legacy_contract()
        before = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = canonical_sha256(contract)
        self.assertEqual(validate_scene_contract_header(contract, task_id='task-1'), 'legacy-full/2.0')
        self.assertEqual(json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(',', ':')), before)
        self.assertEqual(canonical_sha256(contract), digest)
        contract['schema'] = 'houdini.task_scene_contract/1.0'
        with self.assertRaisesRegex(ValueError, 'legacy schema'):
            validate_scene_contract_header(contract)
        self.assertEqual(validate_scene_contract_header(contract, allow_legacy_v1=True), 'legacy-full/2.0')

    def test_locked_policy_binds_definitions_and_explicit_public_descendants(self):
        contract = locked_contract()
        before = deepcopy(contract)
        self.assertEqual(validate_scene_contract_header(contract, task_id='task-1'), 'locked-hda-definition/1')
        self.assertEqual(contract, before)
        node = contract['hda_boundaries'][0]['internal_nodes'].pop()
        contract['nodes'].append(public_node(node['path'], node['type'], node['category']))
        contract['hda_boundaries'][0]['internal_node_count'] -= 1
        self.assertEqual(validate_scene_contract_header(contract), 'locked-hda-definition/1')

    def test_locked_policy_missing_bindings_and_identity_changes_reject(self):
        mutations = {
            'schema': lambda c: c.update(schema='houdini.task_scene_contract/9.0'),
            'task': lambda c: c.update(task_id='other'),
            'missing_policy': lambda c: c.pop('capture_policy'),
            'wrong_policy': lambda c: c.update(capture_policy='legacy-full/2.0'),
            'missing_execution_root': lambda c: c.pop('execution_root'),
            'invalid_execution_root': lambda c: c.update(execution_root='/obj/root/../foreign'),
            'missing_owned_roots': lambda c: c.pop('owned_roots'),
            'empty_owned_roots': lambda c: c.update(owned_roots=[]),
            'malformed_owned_roots': lambda c: c.update(owned_roots='/obj/root'),
            'invalid_owned_root': lambda c: c.update(owned_roots=['/obj/root', []]),
            'duplicate_owned_roots': lambda c: c.update(owned_roots=['/obj/root', '/obj/root']),
            'unowned_execution_root': lambda c: c.update(owned_roots=['/obj/foreign']),
            'unowned_public_node': lambda c: c['nodes'].append(public_node('/obj/root_other', 'Sop/null', 'Sop')),
            'missing_boundaries': lambda c: c.pop('hda_boundaries'),
            'empty_boundaries': lambda c: c.update(hda_boundaries=[]),
            'missing_boundary_node': lambda c: c['nodes'].pop(1),
            'public_channels': lambda c: c['nodes'][0].pop('parameter_channels'),
            'boundary_type': lambda c: c['hda_boundaries'][0].update(type='Sop/other'),
            'unlocked': lambda c: c['hda_boundaries'][0].update(is_locked_hda=False),
            'definition_mismatch': lambda c: c['hda_boundaries'][0].update(matches_current_definition=None),
            'missing_definition': lambda c: c['hda_boundaries'][0].pop('definition'),
            'missing_child_definitions': lambda c: c['hda_boundaries'][0].update(definitions=[]),
            'changed_section': lambda c: c['hda_boundaries'][0]['definition']['sections'][0].update(bytes=4),
            'changed_options': lambda c: c['hda_boundaries'][0]['definition']['extra_file_options'].update(fixture=False),
            'provenance_in_identity': lambda c: c['hda_boundaries'][0]['definition'].update(library_file_path='/tmp/asset.hda'),
            'unbound_child': lambda c: c['hda_boundaries'][0]['internal_nodes'][0].update(definition_sha256='b' * 64),
            'null_known_child': lambda c: c['hda_boundaries'][0]['internal_nodes'][0].update(definition_sha256=None),
            'missing_child_ref': lambda c: c['hda_boundaries'][0]['internal_nodes'][0].pop('definition_sha256'),
            'internal_type': lambda c: c['hda_boundaries'][0]['internal_nodes'][0].update(type='Sop/other'),
            'external_internal_path': lambda c: c['hda_boundaries'][0]['internal_nodes'][0].update(path='/obj/foreign'),
            'duplicate_internal': lambda c: c['hda_boundaries'][0]['internal_nodes'].append(c['hda_boundaries'][0]['internal_nodes'][0]),
            'wrong_count': lambda c: c['hda_boundaries'][0].update(internal_node_count=1),
            'wrong_static_count': lambda c: c['hda_boundaries'][0]['static_fingerprint'].update(node_count=1),
            'incomplete_static': lambda c: c['hda_boundaries'][0]['static_fingerprint'].update(identity_complete=False),
            'static_errors': lambda c: c['hda_boundaries'][0]['static_fingerprint'].update(errors=['unreadable']),
            'static_digest': lambda c: c['hda_boundaries'][0]['static_fingerprint'].update(sha256='bad'),
        }
        for name, mutate in mutations.items():
            contract = locked_contract()
            mutate(contract)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'SCENE_CONTRACT_INVALID'):
                validate_scene_contract_header(contract, task_id='task-1')

    def test_legacy_cannot_claim_folded_nodes_and_new_limits_remain_bounded(self):
        for field, value in (('capture_policy', 'locked-hda-definition/1'), ('hda_boundaries', [])):
            contract = legacy_contract()
            contract[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_scene_contract_header(contract)
        for count in (129,):
            contract = locked_contract()
            contract['nodes'].extend(public_node('/obj/root/n' + str(i), 'Sop/null', 'Sop') for i in range(count))
            with self.assertRaisesRegex(ValueError, 'node limit'):
                validate_scene_contract_header(contract)
        contract = locked_contract()
        contract['nodes'][0]['parameter_channels'] = {str(i): {} for i in range(513)}
        with self.assertRaisesRegex(ValueError, 'public node readback'):
            validate_scene_contract_header(contract)
        contract = locked_contract()
        contract['oversized'] = 'x' * (2 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, 'contract byte limit'):
            validate_scene_contract_header(contract)


class SceneContractConsumerTests(unittest.TestCase):
    def test_hip_saved_reader_accepts_both_policies_and_keeps_required_public_readback(self):
        import run_hip_diagnostic as hip
        with tempfile.TemporaryDirectory(dir='/private/tmp', prefix='contract-consumer-') as temporary:
            root = Path(temporary)
            saves = root / 'houdini-instances/fx_operations'
            saves.mkdir(parents=True)
            path = root / 'saved.hip'
            for contract in (legacy_contract(), locked_contract()):
                contract['frozen_scene_parameters'] = {'profile': 'sphere_ground_v2', 'fields': {'fixture': 1},
                    'geometry': {name: {'resolved_prims': [{'material_prim_path': '/fixture/material'}]}
                                 for name in ('Sphere', 'Ground')}}
                def save(value):
                    digest = canonical_sha256(value)
                    record = {'path': str(path), 'sha256': 'c' * 64, 'scene_contract': value,
                              'scene_contract_sha256': digest}
                    (saves / 'task.saves.json').write_text(json.dumps({'saves': [record]}))
                    return record, digest
                saved, digest = save(contract)
                data = {'control': root, 'config': {'task_id': 'task-1'}}
                self.assertEqual(hip._saved_contract(data, path, 'c' * 64, digest), saved)
                for field in ('parameter_channels', 'inputs', 'frozen_scene_parameters'):
                    broken = deepcopy(contract)
                    (broken if field == 'frozen_scene_parameters' else broken['nodes'][0]).pop(field)
                    _, broken_digest = save(broken)
                    with self.subTest(schema=contract['schema'], missing=field), self.assertRaisesRegex(ValueError, 'READBACK'):
                        hip._saved_contract(data, path, 'c' * 64, broken_digest)
                if contract['schema'].endswith('/2.1'):
                    broken = deepcopy(contract)
                    broken.pop('hda_boundaries')
                    _, broken_digest = save(broken)
                    with self.assertRaisesRegex(ValueError, 'FULL_CONTRACT_REQUIRED'):
                        hip._saved_contract(data, path, 'c' * 64, broken_digest)

    def test_readiness_checks_channels_for_both_new_and_legacy_policy(self):
        import readiness_evidence as evidence
        for contract in (legacy_contract(), locked_contract()):
            document = {'scene': {'scene_contract': contract, 'scene_contract_sha256': canonical_sha256(contract)},
                        'task_id': 'task-1', 'render_target': '/obj/root/renderer'}
            before = evidence._houdini_render_errors(document, 'fixture')
            self.assertFalse(any('saved channel contract' in error for error in before), before)
            contract['nodes'][0]['parameter_channels']['value']['evaluated_available'] = False
            document['scene']['scene_contract_sha256'] = canonical_sha256(contract)
            errors = evidence._houdini_render_errors(document, 'fixture')
            with self.subTest(schema=contract['schema']):
                self.assertTrue(any('saved channel contract malformed' in error for error in errors), errors)
        contract = locked_contract()
        contract.pop('capture_policy')
        document['scene'] = {'scene_contract': contract, 'scene_contract_sha256': canonical_sha256(contract)}
        self.assertTrue(any('saved task contract/target identity mismatch' in error
                            for error in evidence._houdini_render_errors(document, 'fixture')))


if __name__ == '__main__':
    unittest.main()
