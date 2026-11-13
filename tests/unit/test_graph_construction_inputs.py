"""Pure trusted-generator checks; no DCC, app, model or render is started."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
try:
    from prepare_workbuddy_graph import prepare_graph
finally:
    sys.path.pop(0)


class ConstructionInputGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'rest.json'
        self.raw = b'{"schema":"explicit-pure-fixture"}\n'
        self.source.write_bytes(self.raw)
        self.inputs = [dict(index=0, asset_id='explicit-pure-rest',
                            identity=str(self.source), bytes=len(self.raw),
                            sha256=hashlib.sha256(self.raw).hexdigest(),
                            semantic_role='geometry_rest_basis',
                            geometry_observation='native_sop_read')]

    def prepare(self, destination, **kwargs):
        return prepare_graph(destination, app=None,
                             scheduler_root=self.root / 'scheduler', **kwargs)

    def assert_rejected_before_mutation(self, value):
        parent = self.root / 'must-stay-absent'
        destination = parent / 'bundle'
        with self.assertRaises(ValueError):
            self.prepare(destination, construction_input_manifest=value)
        self.assertFalse(parent.exists())
        self.assertFalse((self.root / 'scheduler').exists())
        existing = self.root / 'existing'
        existing.mkdir(exist_ok=True)
        sentinel = existing / 'keep.bin'
        sentinel.write_bytes(b'unchanged')
        with self.assertRaises(ValueError):
            self.prepare(existing, construction_input_manifest=value)
        self.assertEqual(list(existing.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_explicit_manifest_is_frozen_in_run_and_bound_to_bundle(self):
        destination = self.root / 'bundle'
        expected = copy.deepcopy(self.inputs)
        self.prepare(destination, construction_input_manifest=self.inputs)
        run_path = destination / 'control/run.json'
        run = json.loads(run_path.read_text(encoding='utf-8'))
        self.assertEqual(run['construction_input_manifest'], expected)
        self.inputs[0]['sha256'] = '0' * 64
        self.inputs.append(copy.deepcopy(self.inputs[0]))
        self.assertEqual(json.loads(run_path.read_text(encoding='utf-8'))['construction_input_manifest'], expected)
        bundle = json.loads((destination / 'bundle-manifest.json').read_text(encoding='utf-8'))
        entry = next(item for item in bundle['files'] if item['path'] == 'control/run.json')
        self.assertEqual(entry['sha256'], hashlib.sha256(run_path.read_bytes()).hexdigest())
        public_config = json.loads((destination / 'project/.workbuddy/mcp.json').read_text(encoding='utf-8'))
        self.assertNotIn('construction_input_manifest', json.dumps(public_config))

    def test_actual_snapshot_includes_and_imports_current_freezer(self):
        destination = self.root / 'snapshot-bundle'
        self.prepare(destination, construction_input_manifest=self.inputs)
        snapshot = destination / 'control/snapshot'
        relative = 'packages/vfx-pipeline/src/vfx_pipeline/graph_construction_inputs.py'
        source = ROOT / relative
        frozen = snapshot / relative
        self.assertEqual(frozen.read_bytes(), source.read_bytes())
        manifest = json.loads((destination / 'control/snapshot-manifest.json').read_text(encoding='utf-8'))
        entry = next(item for item in manifest['files'] if item['path'] == relative)
        self.assertEqual(entry['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        script = '''import json, sys
from pathlib import Path
snapshot = Path(sys.argv[1])
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(snapshot / 'packages' / package / 'src'))
from vfx_pipeline import graph_construction_inputs
assert Path(graph_construction_inputs.__file__).is_relative_to(snapshot)
value = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))['construction_input_manifest']
assert graph_construction_inputs.freeze_construction_inputs(value, verify_files=True) == value
print('snapshot helper imported and verified explicit files')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(snapshot),
                                 str(destination / 'control/run.json')],
                                cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('snapshot helper imported', result.stdout)

    def test_omitted_none_and_empty_inputs_preserve_compatibility(self):
        for label, options in (('omitted', {}), ('none', {'construction_input_manifest': None}),
                               ('empty', {'construction_input_manifest': []})):
            with self.subTest(label=label):
                destination = self.root / label
                self.prepare(destination, **options)
                run = json.loads((destination / 'control/run.json').read_text(encoding='utf-8'))
                if label == 'empty':
                    self.assertEqual(run['construction_input_manifest'], [])
                else:
                    self.assertNotIn('construction_input_manifest', run)

    def test_invalid_metadata_rejected_before_any_destination_mutation(self):
        invalid = [('object', {}), ('string', '[]'), ('missing-fields', [{}])]
        for field, values in (('bytes', (True, 0, -1, '12')),
                              ('sha256', ('invalid', 'g' * 64)),
                              ('identity', ('', 1)),
                              ('asset_id', ('', 1)),
                              ('semantic_role', ('', 1))):
            for value in values:
                manifest = copy.deepcopy(self.inputs)
                manifest[0][field] = value
                invalid.append((field + '-' + repr(value), manifest))
        for label, value in invalid:
            with self.subTest(label=label):
                self.assert_rejected_before_mutation(value)

    def test_changed_content_and_size_rejected_before_mutation(self):
        original = copy.deepcopy(self.inputs)
        for raw in (b'x' * len(self.raw), self.raw + b'changed'):
            with self.subTest(length=len(raw)):
                self.source.write_bytes(raw)
                self.assert_rejected_before_mutation(original)

    def test_unsafe_or_missing_paths_rejected_before_mutation(self):
        names = ('rest.json', str(self.root / '..' / self.root.name / 'rest.json'),
                 str(self.root / 'missing.json'), str(self.root))
        for name in names:
            with self.subTest(path=name):
                value = copy.deepcopy(self.inputs)
                value[0]['identity'] = name
                self.assert_rejected_before_mutation(value)
        alias = self.root / 'hardlink.json'
        os.link(self.source, alias)
        self.assert_rejected_before_mutation(self.inputs)

    def test_declared_item_and_byte_budgets_rejected_before_mutation(self):
        oversized_basis = copy.deepcopy(self.inputs)
        oversized_basis[0]['bytes'] = 64 * 1024 + 1
        oversized_other = copy.deepcopy(self.inputs)
        oversized_other[0]['semantic_role'] = 'explicit_fixture_input'
        oversized_other[0]['bytes'] = 8 * 1024 * 1024 + 1
        too_many = [dict(self.inputs[0], index=index) for index in range(33)]
        total = [dict(self.inputs[0], index=index, semantic_role='explicit_fixture_input',
                      bytes=8 * 1024 * 1024) for index in range(5)]
        for label, value in (('basis', oversized_basis), ('other', oversized_other),
                             ('items', too_many), ('total', total)):
            with self.subTest(label=label):
                self.assert_rejected_before_mutation(value)

    def test_cli_invalid_json_metadata_and_missing_file_preflight(self):
        config = self.root / 'manifest.json'
        cases = (('syntax', '{'), ('metadata', '[{}]'), ('null', 'null'), ('missing', None))
        for label, content in cases:
            with self.subTest(label=label):
                if content is None:
                    config.unlink()
                else:
                    config.write_text(content, encoding='utf-8')
                destination = self.root / 'cli-uncreated' / label
                result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/prepare_workbuddy_graph.py'),
                                         '--output', str(destination),
                                         '--construction-input-manifest', str(config)],
                                        cwd=self.root, capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('unrecognized arguments', result.stderr)
                self.assertNotIn('WorkBuddy.app', result.stderr)
                self.assertFalse(destination.parent.exists())


if __name__ == '__main__':
    unittest.main()
