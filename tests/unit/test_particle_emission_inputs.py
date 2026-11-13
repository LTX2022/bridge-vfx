"""Frozen particle seed files do not attest native emission consumption."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vfx_pipeline import graph_construction_inputs as inputs


class ParticleEmissionInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.path = self.directory / '粒子 seed with space.json'

    def manifest(self, value=None, *, raw=None):
        content = json.dumps(value).encode('utf-8') if raw is None else raw
        self.path.write_bytes(content)
        return [dict(index=0, asset_id='explicit-emission-seed', semantic_role='particle_emission_basis',
                     identity=str(self.path), bytes=len(content), sha256=hashlib.sha256(content).hexdigest())]

    def test_explicit_seed_is_stably_read_without_defaults(self):
        for value in (0, 173, 2147483647):
            with self.subTest(seed=value):
                manifest = self.manifest({'task_seed': value})
                before = copy.deepcopy(manifest)
                self.assertEqual(inputs.particle_emission_configuration(manifest), {'task_seed': value})
                self.assertEqual(manifest, before)
        self.assertIsNone(inputs.particle_emission_configuration([]))

    def test_foreign_and_duplicate_fields_and_non_int32_seeds_refuse(self):
        for value in (None, [], {}, {'task_seed': True}, {'task_seed': -1},
                      {'task_seed': 2147483648}, {'task_seed': 173.},
                      {'task_seed': 173, 'native_seed': 17}, {'task_seed': '173'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inputs.particle_emission_configuration(self.manifest(value))
        with self.assertRaises(ValueError):
            inputs.particle_emission_configuration(self.manifest(raw=b'{"task_seed":0,"task_seed":173}'))

    def test_duplicate_files_content_changes_and_oversize_refuse(self):
        manifest = self.manifest({'task_seed': 173})
        duplicate = copy.deepcopy(manifest[0])
        duplicate['index'] = 1
        with self.assertRaises(ValueError):
            inputs.particle_emission_configuration(manifest + [duplicate])
        self.path.write_bytes(b'x' * manifest[0]['bytes'])
        with self.assertRaises(ValueError):
            inputs.particle_emission_configuration(manifest)
        with self.assertRaises(ValueError):
            inputs.particle_emission_configuration(self.manifest(raw=b' ' * 4097))

    def test_late_same_size_file_drift_cannot_supply_a_seed(self):
        manifest = self.manifest({'task_seed': 173})
        original_signature = inputs._signature
        calls = []
        def change_after_read(stat_result):
            calls.append(None)
            if len(calls) == 3:
                self.path.write_bytes(b'x' * manifest[0]['bytes'])
            return original_signature(stat_result)
        with patch.object(inputs, '_signature', change_after_read), self.assertRaises(ValueError):
            inputs.particle_emission_configuration(manifest)
