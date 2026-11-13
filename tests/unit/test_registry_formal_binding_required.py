from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import test_houdini_output_receipts as fixtures
from dcc_task_runtime.artifact_registry import ArtifactRegistry, ArtifactError
from houdini_bridge.client import render_execution_fact


class RegistryFormalBindingRequiredTests(unittest.TestCase):
    def test_houdini_producer_cannot_use_legacy_registration_without_source_binding(self):
        fixture = fixtures.HoudiniOutputReceiptTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fact = render_execution_fact(fixture.record)
        registry = ArtifactRegistry(fixture.root / 'registry')
        registry.set_operation_source(lambda operation_id: fact)
        with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED'):
            registry.register(artifact_id='unbound-native-output', task_id=fact['task_id'],
                artifact_class='confirmed_cache', pattern=fact['output_pattern'], frame_set=fact['frame_set'],
                colorspace='linear', premultiplied=False, dependencies=fact['dependencies'],
                operation_id=fact['operation_id'], scene_fingerprint=fact['scene_fingerprint'])
        self.assertEqual(registry.history('unbound-native-output'), [])
        self.assertIsNone(registry.lookup('unbound-native-output'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
