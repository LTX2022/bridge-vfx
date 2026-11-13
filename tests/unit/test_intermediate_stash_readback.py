"""Intermediate native parameter states never replace initialized asset evidence."""
import sys
import unittest
from unittest.mock import patch

import test_readiness_native_command_evidence as native_fixture


class IntermediateStashReadbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native_fixture.NativeCommandEvidenceTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addon = self.fixture.addon
        self.root = sys.modules['hou'].node(self.fixture.saved['scene_contract']['execution_root'])
        self.creation_request = dict(parent=self.root.path(), type='stash', name='pending_agent',
            task_id=self.fixture.owner, operation_id='create-pending-agent', request_id='create-pending-agent',
            frozen_input_manifest=[])
        self.creation = self.addon.dispatch('node.create', self.creation_request)
        self.node = sys.modules['hou'].node(self.creation['path'])
        self.parameter = self.node.parm('stash')

    def create_next_node(self):
        return self.addon.dispatch('node.create', dict(self.creation_request,
            type='null', name='next_node', operation_id='create-next-node', request_id='create-next-node'))

    def test_unobserved_data_is_not_promoted_to_empty_geometry(self):
        value, channel = self.addon._fx_scene_parameter_readback(
            self.parameter, self.fixture.owner, allow_uninitialized_stash=True)
        self.assertIsNone(value)
        self.assertFalse(channel['evaluated_available'])
        self.assertEqual(channel['data_state'], 'readback_unavailable')
        self.assertNotIn('geometry_contract', channel)
        self.assertFalse(channel['stashfile_available'])
        self.assertIn('native default is not captured', channel['evaluation_error'])
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'owned stash recipe identity'):
            self.addon._fx_scene_parameter_readback(self.parameter, self.fixture.owner)

    def test_explicit_bottom_null_observation_remains_uninitialized(self):
        with patch.object(type(self.parameter), 'evalAsGeometry', return_value=None):
            value, channel = self.addon._fx_scene_parameter_readback(
                self.parameter, self.fixture.owner, allow_uninitialized_stash=True)
        self.assertIsNone(value)
        self.assertEqual(channel['data_state'], 'observed_null')
        self.assertNotIn('geometry_contract', channel)
        self.assertTrue(channel['evaluated_available'])

    def test_observed_unregistered_nonnull_data_is_rejected(self):
        with patch.object(type(self.parameter), 'evalAsGeometry', return_value=object()), \
                self.assertRaisesRegex(self.addon.BridgeCommandError, 'unregistered data'):
            self.addon._fx_scene_parameter_readback(
                self.parameter, self.fixture.owner, allow_uninitialized_stash=True)

    def test_malformed_registered_recipe_cannot_be_downgraded_to_pending(self):
        for key in ('bridge_native_agent_recipe_v1', 'bridge_native_route_recipe_v1'):
            for marker in ('{', ''):
                self.node.setUserData(key, marker)
                with self.subTest(key=key, marker=marker), self.assertRaises((ValueError, self.addon.BridgeCommandError)):
                    self.addon._fx_scene_parameter_readback(
                        self.parameter, self.fixture.owner, allow_uninitialized_stash=True)
                self.node.destroyUserData(key)

    def test_typed_save_rejects_pending_data_even_when_primitive_construction_accepts_it(self):
        target = self.fixture.directory / 'pending.hip'
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'owned stash recipe identity'):
            self.addon.dispatch('scene.save_hip', {
                'path': str(target), 'root_path': self.root.path(), 'task_id': self.fixture.owner,
                'operation_id': 'save-pending-stash', 'request_id': 'save-pending-stash',
                'graph_hash': self.fixture.graph_hash, 'frozen_input_manifest': []})
        self.assertFalse(target.exists())

    def test_following_primitive_uses_verified_same_host_creation(self):
        result = self.create_next_node()
        self.assertEqual(result['operation_receipt']['state'], 'COMPLETED')
        self.assertEqual(result['operation_receipt']['facts']['proof_scope'], 'native_command')

    def test_intermediate_children_and_info_are_partial_native_queries(self):
        for command in ('node.children', 'node.info'):
            with self.subTest(command=command):
                result = self.addon.dispatch(command, dict(self.creation_request,
                    path=self.root.path(), operation_id='pending-' + command, request_id='pending-' + command))
                record = result['operation_receipt']
                self.assertEqual(record['facts']['proof_scope'], 'native_command')
                pending = next(node for node in record['after_scene']['scene_contract']['nodes']
                               if node['path'] == self.node.path())
                self.assertNotIn('stash', pending['parameters'])
                self.assertFalse(pending['parameter_channels']['stash']['evaluated_available'])

    def test_query_does_not_adopt_preexisting_unregistered_stash(self):
        self.root.createNode('stash', 'older_unregistered_asset')
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'owned stash recipe identity'):
            self.addon.dispatch('node.children', dict(self.creation_request, path=self.root.path(),
                operation_id='old-asset-query', request_id='old-asset-query'))

    def test_preexisting_unregistered_stash_is_not_accepted_as_pending(self):
        self.root.createNode('stash', 'older_unregistered_asset')
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'owned stash recipe identity'):
            self.create_next_node()
        self.assertIsNone(sys.modules['hou'].node(self.root.path() + '/next_node'))

    def test_different_host_attempt_does_not_inherit_pending_assets(self):
        self.addon._TASK_HOST_IDENTITY = dict(self.addon._TASK_HOST_IDENTITY, launch_nonce='different-attempt')
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'owned stash recipe identity'):
            self.create_next_node()
        self.assertIsNone(sys.modules['hou'].node(self.root.path() + '/next_node'))

    def test_missing_creation_record_cannot_authorize_pending_state(self):
        from pathlib import Path
        Path(self.creation['operation_store_path']).unlink()
        with self.assertRaises(ValueError):
            self.create_next_node()
        self.assertIsNone(sys.modules['hou'].node(self.root.path() + '/next_node'))

    def test_pending_geometry_cannot_prove_equality_for_idempotent_replay(self):
        before = tuple(node.path() for node in self.root.allSubChildren())
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'cannot prove scene equality'):
            self.addon.dispatch('node.create', self.creation_request)
        self.assertEqual(tuple(node.path() for node in self.root.allSubChildren()), before)

    def test_expression_driver_cannot_be_hidden_by_unavailable_data(self):
        self.parameter.setExpression('geometry()', language=sys.modules['hou'].exprLanguage.Hscript)
        with self.assertRaisesRegex(self.addon.BridgeCommandError, 'external file or driver'):
            self.addon._fx_scene_parameter_readback(
                self.parameter, self.fixture.owner, allow_uninitialized_stash=True)


if __name__ == '__main__':
    unittest.main()
