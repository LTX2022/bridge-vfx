"""Focused coverage for the read-only render-readback diagnostic entry.

Layered software proof only: binding uniqueness, dump validation refusals,
admission gating and activation binding.  The single bounded native pass is
authorized separately and is not exercised here.
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

import run_render_readback_diagnostic as diagnostic


class SaveEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='render-readback-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.hip = self.directory / 'task.hip'
        self.hip.write_bytes(b'hip-bytes')
        self.store = {'saves': [
            {'path': str(self.hip), 'sha256': 'a' * 64, 'scene_contract_sha256': 'c' * 64},
            {'path': str(self.hip), 'sha256': 'a' * 64, 'scene_contract_sha256': 'd' * 64},
            {'path': str(self.directory / 'other.hip'), 'sha256': 'a' * 64,
             'scene_contract_sha256': 'c' * 64},
        ]}
        self.store_path = self.directory / 'saves.json'
        self.store_path.write_text(json.dumps(self.store))

    def _record(self):
        digest = hashlib.sha256(self.hip.read_bytes()).hexdigest()
        return {'path': str(self.hip), 'bytes': self.hip.stat().st_size, 'sha256': digest}

    def test_matching_entry_is_unique(self):
        record = self._record()
        record['sha256'] = 'a' * 64
        entry = diagnostic.save_entry(self.store_path, record, 'c' * 64)
        self.assertEqual(entry['scene_contract_sha256'], 'c' * 64)

    def test_ambiguous_or_missing_entries_are_refused(self):
        record = self._record()
        record['sha256'] = 'a' * 64
        self.store['saves'].append(dict(self.store['saves'][0]))
        self.store_path.write_text(json.dumps(self.store))
        with self.assertRaisesRegex(ValueError, 'SAVE_ENTRY_INVALID'):
            diagnostic.save_entry(self.store_path, record, 'c' * 64)
        with self.assertRaisesRegex(ValueError, 'SAVE_ENTRY_INVALID'):
            diagnostic.save_entry(self.store_path, record, 'e' * 64)


class ValidateDumpTests(unittest.TestCase):
    def setUp(self):
        self.config = {'inputs': {'hip': {'path': '/tmp/x.hip'},
                                  'render_role': '/obj/root/render_network/render'}}
        self.dump = {'schema': 'bridge.render-readback.dump/1', 'houdini_version': '21.0.631',
                     'frame': 1, 'hip_path': '/tmp/x.hip',
                     'render_node': {'path': '/obj/root/render_network/render',
                                     'parameters': {'loppath': {'value': '/stage/lop1'}}},
                     'render_settings_prim': {'typeName': 'RenderSettings',
                                              'attributes': {'resolution': {'value': [128, 128],
                                                                            'authored': True}}}}

    def test_valid_dump_is_accepted(self):
        self.assertTrue(diagnostic.validate_dump(self.dump, self.config))

    def test_header_prim_or_resolution_gaps_are_refused(self):
        cases = [
            {'schema': 'other/1'},
            {'schema': 'bridge.render-readback.dump/1', 'houdini_version': '20.0.0',
             'frame': 1, 'hip_path': '/tmp/x.hip',
             'render_node': self.dump['render_node'],
             'render_settings_prim': self.dump['render_settings_prim']},
            dict(self.dump, render_settings_prim={'typeName': 'Xdr'} |
                 {'typeName': 'RenderSettings'} if False else {'typeName': 'Mesh'}),
        ]
        wrong_prim = dict(self.dump)
        wrong_prim['render_settings_prim'] = {'typeName': 'Mesh'}
        cases.append(wrong_prim)
        no_resolution = dict(self.dump)
        no_resolution['render_settings_prim'] = {'typeName': 'RenderSettings', 'attributes': {}}
        cases.append(no_resolution)
        for dump in cases:
            with self.assertRaisesRegex(ValueError, 'DUMP_'):
                diagnostic.validate_dump(dump, self.config)


class AdmissionTests(unittest.TestCase):
    def _native(self, **state):
        native = patch.dict('os.environ')
        native.start(); self.addCleanup(native.stop)
        stub = {'closed_reason': None, 'dcc_starts': 0, 'tickets': [],
                'disk_bytes': 0, 'total_seconds': 0}
        stub.update(state)
        native_mock = unittest.mock.MagicMock()
        native_mock.snapshot.return_value = stub
        native_mock.role_seconds.return_value = 120
        return native_mock

    def test_refuses_used_closed_or_occupied_scope(self):
        with self.assertRaisesRegex(ValueError, 'ADMISSION_REFUSED'):
            diagnostic.admission(self._native(dcc_starts=1))
        with self.assertRaisesRegex(ValueError, 'ADMISSION_REFUSED'):
            diagnostic.admission(self._native(closed_reason='X'))
        with self.assertRaisesRegex(ValueError, 'ADMISSION_REFUSED'):
            diagnostic.admission(self._native(tickets=[{'stopped_at': None}]))


class ActivateBindingTests(unittest.TestCase):
    def test_instruction_constant_is_the_recorded_user_text(self):
        self.assertEqual(diagnostic.INSTRUCTION, '你全都可以做，做过的记得写下到文档一起提交')
        self.assertEqual(diagnostic.AUTHORITY, 'current_user_conditional_instruction')


if __name__ == '__main__':
    unittest.main()


class ExperimentValidateDumpTests(unittest.TestCase):
    def setUp(self):
        self.config = {'inputs': {'hip': {'path': '/tmp/x.hip'}}}
        self.dump = {'schema': 'bridge.resolution-experiment.dump/1',
                     'houdini_version': '21.0.631', 'hip_path': '/tmp/x.hip',
                     'variants': {'v1_baseline_tail': {'resolution': {'value': 'Gf.Vec2i(2048, 1152)'}}}}

    def test_valid_experiment_dump_is_accepted(self):
        import importlib
        experiment = importlib.import_module('run_resolution_experiment')
        self.assertTrue(experiment.validate_dump(self.dump, self.config))

    def test_missing_variants_or_baseline_are_refused(self):
        import importlib
        experiment = importlib.import_module('run_resolution_experiment')
        with self.assertRaisesRegex(ValueError, 'DUMP_'):
            experiment.validate_dump(dict(self.dump, variants={}), self.config)
        no_baseline = dict(self.dump)
        no_baseline['variants'] = {'v2_native_callback': {}}
        with self.assertRaisesRegex(ValueError, 'DUMP_'):
            experiment.validate_dump(no_baseline, self.config)

    def test_instruction_constant_is_the_current_user_text(self):
        import importlib
        experiment = importlib.import_module('run_resolution_experiment')
        self.assertEqual(experiment.INSTRUCTION, '继续下一步')
