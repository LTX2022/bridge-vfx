from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))

from vfx_pipeline.graph_jobs import _public_result


class PublicNativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=ROOT / 'outputs')))
        self.binding = dict(root=self.root, operation_id='owned-operation', graph_id='owned-graph',
            root_task_id='owned-task', attempt_token='bounded-attempt-token', attempt_generation=2)
        self.relative = 'graph-jobs/owned-operation/attempt-2/owned-operation.native-operations.json'
        self.reference = dict(schema='bridge.houdini.native-command-evidence/2.0', task_id='owned-task',
            operation_id='owned-operation', graph_hash='a' * 64, attempt_token='bounded-attempt-token',
            attempt_generation=2, count=3, bytes=1024, sha256='b' * 64,
            path=str(self.root / self.relative), private_extra={'path': 'C:/private/credential'})
        self.result = dict(graph_hash='a' * 64, native_operation_evidence=self.reference)

    def test_bounded_reference_survives_repeated_sanitizing_without_private_paths(self):
        first = _public_result(self.result, **self.binding)
        published = first['native_operation_evidence']
        self.assertEqual(published['path'], self.relative)
        self.assertNotIn('private_extra', published)
        self.assertEqual(_public_result(first, **self.binding), first)

    def test_foreign_owner_attempt_and_invalid_bounds_are_omitted(self):
        for field, value in (('task_id', 'foreign'), ('operation_id', 'foreign'),
                             ('graph_hash', 'c' * 64), ('attempt_token', 'old-attempt'),
                             ('attempt_generation', 1), ('attempt_generation', True),
                             ('count', True), ('count', 4097), ('bytes', 0), ('bytes', 67108865),
                             ('sha256', 'unbounded')):
            with self.subTest(field=field, value=value):
                result = deepcopy(self.result)
                result['native_operation_evidence'][field] = value
                self.assertNotIn('native_operation_evidence', _public_result(result, **self.binding))

    def test_foreign_paths_and_missing_actual_attempt_binding_are_omitted(self):
        for path in ('../private.json', 'graph-jobs/foreign/attempt-2/owned-operation.native-operations.json',
                     'graph-jobs/owned-operation/attempt-1/owned-operation.native-operations.json',
                     'graph-jobs/owned-operation/attempt-2/credential.json'):
            with self.subTest(path=path):
                result = deepcopy(self.result)
                result['native_operation_evidence']['path'] = path
                self.assertNotIn('native_operation_evidence', _public_result(result, **self.binding))
        binding = dict(self.binding, attempt_token=None, attempt_generation=None)
        self.assertNotIn('native_operation_evidence', _public_result(self.result, **binding))


if __name__ == '__main__':
    unittest.main(verbosity=2)
