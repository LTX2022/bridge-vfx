"""Saved frozen plans retain their exact historical field set across reopen."""
import copy
import json
from contextlib import contextmanager
import unittest

import test_controlled_native_readback as fixtures


class FrozenScenePlanCompatibilityTests(unittest.TestCase):
    @contextmanager
    def fixture(self, profile, version='21.0.631'):
        case = fixtures.ControlledNativeReadbackTests()
        case.scene_profile, case.native_version = profile, version
        try:
            case.setUp()
            yield case
        finally:
            case.doCleanups()

    def legacy_contract(self, case):
        contract = copy.deepcopy(case.contract)
        frozen = contract['frozen_scene_parameters']
        frozen.pop('parameter_plan_revision')
        for field in ('settings_binding.res_mode', 'settings_binding.resolution',
                      'render.soho_foreground', 'render.husk_tpostframe'):
            frozen['fields'].pop(field)
        # Retain the actual old factory controls in both scene and full public
        # channel contract. Compatibility does not author new controls on load.
        for role, name, value in [('settings_binding', 'res_mode', 'autoheight'),
                                  ('settings_binding', 'resolution', (2048, 1080)),
                                  ('render', 'soho_foreground', 0), ('render', 'husk_tpostframe', 1)]:
            node = case.hou.node(case.roles[role])
            case.addon._resolve_parm_target(node, [name]).set(value, follow_references=False)
        case.native.parm('custom_metadata').set(2)
        for record in contract['nodes']:
            node = case.hou.node(record['path'])
            observed = {parm.name(): case.addon._fx_scene_parameter_readback(parm, case.task_id)
                        for parm in node.parms()}
            record['parameters'] = {name: value for name, (value, channel) in observed.items()
                                    if channel['evaluated_available']}
            record['parameter_channels'] = {name: channel for name, (value, channel) in observed.items()}
        root, manifest = case.addon._fx_manifest(case.task_id)
        manifest.pop('frozen_scene_plan_revision')
        case.addon._fx_store_manifest(root, manifest)
        saves = case.addon._fx_task_saves_path(case.task_id)
        saves.write_text(json.dumps({'active_scene': {
            'scene_contract': contract, 'scene_contract_sha256': case.addon._fx_scene_contract_digest(contract),
            'identity': case.addon._host_identity()}}))
        return contract

    def test_legacy_v1_v2_reopen_and_resave_keep_old_controls_and_detect_drift(self):
        for profile in ('sphere_ground_v1', 'sphere_ground_v2'):
            with self.subTest(profile=profile), self.fixture(profile) as case:
                legacy = self.legacy_contract(case)
                result = case.addon._fx_verify_scene_contract(legacy, case.task_id)
                self.assertEqual(result['frozen_scene_parameters'], legacy['frozen_scene_parameters'])
                captured = case.addon._fx_capture_scene_contract(case.task_id)
                self.assertEqual(captured['frozen_scene_parameters'], legacy['frozen_scene_parameters'])
                hip = case.root / 'legacy-resave.hip'
                saved = case.addon.dispatch('scene.save_hip', {'task_id': case.task_id,
                    'operation_id': 'legacy-save', 'request_id': 'legacy-save', 'path': str(hip),
                    'frozen_input_manifest': []})
                self.assertEqual(saved['scene_contract']['frozen_scene_parameters'], legacy['frozen_scene_parameters'])
                reopened = case.addon.dispatch('scene.reopen_task_hip', {
                    'task_id': case.task_id, 'path': str(hip), 'sha256': saved['sha256'],
                    'scene_contract_sha256': saved['scene_contract_sha256'],
                    'operation_id': 'legacy-open', 'request_id': 'legacy-open'})
                self.assertTrue(reopened['parameters_verified'])
                self.assertEqual(case.hou.node(case.roles['render']).parm('soho_foreground').eval(), 0)
                self.assertEqual(case.hou.node(case.roles['render']).parm('husk_tpostframe').eval(), 1)
                case.hou.node(case.roles['source']).parm('radx').set(.8)
                with self.assertRaises(case.addon.BridgeCommandError):
                    case.addon._fx_verify_scene_contract(saved['scene_contract'], case.task_id)

    def test_only_exact_known_untagged_sets_and_complete_current_revision_are_accepted(self):
        with self.fixture('sphere_ground_v2') as case:
            current = case.contract
            self.assertEqual(current['frozen_scene_parameters']['parameter_plan_revision'], 2)
            untagged = copy.deepcopy(current)
            untagged['frozen_scene_parameters'].pop('parameter_plan_revision')
            verified = case.addon._fx_verify_scene_contract(untagged, case.task_id)
            self.assertEqual(verified['frozen_scene_parameters'], untagged['frozen_scene_parameters'])
            for contract in (copy.deepcopy(current), copy.deepcopy(untagged)):
                contract['frozen_scene_parameters']['fields'].pop('settings_binding.resolution')
                with self.assertRaises(case.addon.BridgeCommandError):
                    case.addon._fx_verify_scene_contract(contract, case.task_id)
            legacy = self.legacy_contract(case)
            legacy['frozen_scene_parameters']['fields'].pop('source.rad')
            with self.assertRaises(case.addon.BridgeCommandError):
                case.addon._fx_verify_scene_contract(legacy, case.task_id)


if __name__ == '__main__':
    unittest.main()
