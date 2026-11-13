"""Exercise real package files and imports; no DCC or production state is used."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py',
    'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/alpha_calibration.py',
    'runtime/packages/houdini-bridge/src/houdini_bridge/alpha_reuse.py',
)
GEOMETRY_MODULES = MODULES + (
    'runtime/packages/dcc-task-runtime/src/dcc_task_runtime/native_scope.py',
    'runtime/packages/houdini-bridge/src/houdini_bridge/controlled_output.py',
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


class HistoricalReaderPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='historical-reader-package-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package = self.root / 'bridge-vfx'
        for name in ('dcc-task-runtime', 'houdini-bridge'):
            shutil.copytree(ROOT / 'packages' / name / 'src',
                            self.package / 'runtime/packages' / name / 'src',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.seal()

    def seal(self, version='0.4.23', name='bridge-vfx'):
        (self.package / 'plugin.json').write_bytes(canonical({'name': name, 'version': version}))
        entries = []
        for relative in ('plugin.json', *GEOMETRY_MODULES):
            raw = (self.package / relative).read_bytes()
            entries.append({'path': relative, 'bytes': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest()})
        self.manifest = {'schema_version': 1, 'files': entries,
                         'file_manifest_sha256': hashlib.sha256(canonical(entries)).hexdigest()}
        (self.package / 'runtime-manifest.json').write_bytes(canonical(self.manifest))

    def query(self, setup='', expression='verify()'):
        code = '''
import json
import subprocess
from pathlib import Path
from dcc_task_runtime import process_image as image
verify = image._historical_package_sources
def reject_process(*args, **kwargs):
    raise AssertionError('reader attempted process launch')
subprocess.Popen = reject_process
''' + setup + '''
try:
    result = ''' + expression + '''
    print(json.dumps({'state': 'OK', 'sources': sorted(result)}))
except image.ProcessImageError as error:
    print(json.dumps({'state': 'REJECTED', 'error': str(error)}))
'''
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env['PYTHONPATH'] = os.pathsep.join(str(self.package / 'runtime/packages' / name / 'src')
                                          for name in ('dcc-task-runtime', 'houdini-bridge'))
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=self.root,
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_rejected(self, error, **kwargs):
        result = self.query(**kwargs)
        self.assertEqual(result, {'state': 'REJECTED', 'error': 'PROCESS_IMAGE_' + error})

    def test_maintained_readers_validate_actual_module_sources(self):
        for version in ('0.4.12', '0.4.18', '0.4.19', '0.4.20', '0.4.21', '0.4.22', '0.4.23'):
            with self.subTest(version=version):
                self.seal(version)
                result = self.query()
                self.assertEqual(result['state'], 'OK')
                self.assertEqual(set(result['sources']), {
                    str(self.package / path) for path in ('plugin.json', 'runtime-manifest.json', *MODULES)
                })

    def test_unknown_reader_and_wrong_package_name_are_rejected(self):
        for version, name in (('0.4.24', 'bridge-vfx'), ('99.0.0', 'bridge-vfx'), ('0.4.23', 'other')):
            with self.subTest(version=version, name=name):
                self.seal(version, name)
                self.assert_rejected('HISTORICAL_PACKAGE_INVALID')

    def test_manifest_digest_and_duplicate_entries_are_rejected(self):
        self.manifest['file_manifest_sha256'] = '0' * 64
        path = self.package / 'runtime-manifest.json'
        path.write_bytes(canonical(self.manifest))
        self.assert_rejected('HISTORICAL_PACKAGE_INVALID')
        self.seal()
        self.manifest['files'].append(dict(self.manifest['files'][0]))
        self.manifest['file_manifest_sha256'] = hashlib.sha256(canonical(self.manifest['files'])).hexdigest()
        path.write_bytes(canonical(self.manifest))
        self.assert_rejected('HISTORICAL_PACKAGE_INVALID')

    def test_changed_module_bytes_are_rejected(self):
        path = self.package / MODULES[1]
        path.write_bytes(path.read_bytes() + b'\n# changed after package manifest\n')
        self.assert_rejected('HISTORICAL_SOURCE_CHANGED')

    def test_loaded_module_from_another_directory_is_rejected(self):
        source = self.package / MODULES[1]
        foreign = self.root / 'foreign-alpha.py'
        foreign.write_bytes(source.read_bytes())
        self.assert_rejected('HISTORICAL_RUNTIME_SOURCE_MISMATCH', setup=f'''
from dcc_task_runtime import alpha_calibration
alpha_calibration.__file__ = {str(foreign)!r}
''')

    def test_replaced_function_code_is_rejected(self):
        self.assert_rejected('HISTORICAL_RUNTIME_SOURCE_MISMATCH', setup='''
image._historical_package_sources = lambda: None
''')

    def test_shape_reader_still_requires_original_0411_producer(self):
        authority_path = self.root / 'authority.json'
        authority_path.write_bytes(canonical({'runtime_requirements': {
            'version': '0.4.23', 'formal_root': str(self.package),
            'plugin': {}, 'manifest': {}, 'historical_sources': {},
        }}))
        authority = {'path': str(authority_path), 'bytes': authority_path.stat().st_size,
                     'sha256': hashlib.sha256(authority_path.read_bytes()).hexdigest()}
        scope_path = self.root / 'scope.json'
        scope_path.write_bytes(canonical({'shape_authority': authority}))
        binding = {'path': str(scope_path), 'sha256': hashlib.sha256(scope_path.read_bytes()).hexdigest()}
        self.assert_rejected('HISTORICAL_SHAPE_RUNTIME_REQUIRED',
                             expression=f'verify(shape_scope_binding={binding!r})')

    def geometry_fixture(self, version):
        """Original file closure supplied after the caller's authority checks."""
        original = self.root / ('producer-' + version)
        snapshot = self.root / ('snapshot-' + version)
        original.mkdir()
        (original / 'plugin.json').write_bytes(canonical({'name': 'bridge-vfx', 'version': version}))
        entries = []
        for relative in GEOMETRY_MODULES:
            raw = (self.package / relative).read_bytes() + b'\n# original production file\n'
            path = original / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            snap = snapshot / relative.removeprefix('runtime/')
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_bytes(raw)
            entries.append({'path': relative, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        manifest = {'schema_version': 1, 'files': entries,
                    'file_manifest_sha256': hashlib.sha256(canonical(entries)).hexdigest()}
        (original / 'runtime-manifest.json').write_bytes(canonical(manifest))
        return original, snapshot, {entry['path']: entry for entry in entries}

    def geometry_query(self, fixture, *, feedback=False, setup=''):
        original, snapshot, index = fixture
        prefix = f'''
original = Path({str(original)!r})
snapshot = Path({str(snapshot)!r})
original_index = {index!r}
baselines = image._FeedbackGeometryBaselines() if {feedback!r} else {{}}
geometry_modules = image._HISTORICAL_SHAPE_MODULES[:4] + (
    ('houdini_bridge.controlled_output','houdini-bridge','controlled_output.py','verify_controlled_output'),
)
def read_geometry():
    image._geometry_alpha_module_sources(original,original_index,baselines,snapshot,geometry_modules,
        error_code={'GEOMETRY_FEEDBACK_ALPHA_MODULE_CHANGED' if feedback else 'GEOMETRY_ALPHA_MODULE_CHANGED'!r})
    return baselines
'''
        return self.query(setup=prefix + setup, expression='read_geometry()')

    def test_cross_version_created_and_feedback_keep_both_source_closures(self):
        for version, feedback in (('0.4.18', False), ('0.4.20', True)):
            with self.subTest(version=version, feedback=feedback):
                fixture = self.geometry_fixture(version)
                result = self.geometry_query(fixture, feedback=feedback)
                self.assertEqual(result['state'], 'OK')
                original, snapshot, _ = fixture
                expected = {str(self.package / relative) for relative in GEOMETRY_MODULES}
                expected.update(str(original / relative) for relative in GEOMETRY_MODULES)
                expected.update(str(snapshot / relative.removeprefix('runtime/')) for relative in GEOMETRY_MODULES)
                self.assertTrue(expected <= set(result['sources']))

    def test_cross_version_original_package_and_snapshot_bytes_stay_required(self):
        for version, feedback in (('0.4.18', False), ('0.4.20', True)):
            fixture = self.geometry_fixture(version)
            original, snapshot, _ = fixture
            for path in (original / MODULES[0], snapshot / MODULES[0].removeprefix('runtime/')):
                with self.subTest(version=version, path=path):
                    raw = path.read_bytes()
                    try:
                        path.write_bytes(raw + b'\n# changed original\n')
                        result = self.geometry_query(fixture, feedback=feedback)
                        self.assertEqual(result, {'state': 'REJECTED', 'error': 'PROCESS_IMAGE_HISTORICAL_SOURCE_CHANGED'})
                    finally:
                        path.write_bytes(raw)

    def test_cross_version_reader_manifest_and_loaded_function_stay_required(self):
        fixture = self.geometry_fixture('0.4.20')
        self.manifest['file_manifest_sha256'] = '0' * 64
        (self.package / 'runtime-manifest.json').write_bytes(canonical(self.manifest))
        self.assertEqual(self.geometry_query(fixture, feedback=True), {
            'state': 'REJECTED', 'error': 'PROCESS_IMAGE_GEOMETRY_FEEDBACK_ALPHA_MODULE_CHANGED'})
        self.seal()
        result = self.geometry_query(fixture, feedback=True, setup='''
from houdini_bridge import controlled_output
controlled_output.verify_controlled_output = lambda: None
''')
        self.assertEqual(result, {'state': 'REJECTED', 'error': 'PROCESS_IMAGE_HISTORICAL_RUNTIME_SOURCE_MISMATCH'})

    def test_cross_version_unknown_reader_cannot_use_old_authority(self):
        fixture = self.geometry_fixture('0.4.18')
        self.seal('0.4.24')
        self.assertEqual(self.geometry_query(fixture), {
            'state': 'REJECTED', 'error': 'PROCESS_IMAGE_GEOMETRY_ALPHA_MODULE_CHANGED'})

    def test_feedback_large_result_does_not_expand_reader_source_limit(self):
        fixture = self.geometry_fixture('0.4.20')
        large = self.root / 'original-result.json'
        large.write_bytes(b' ' * (3 * 1024 * 1024))
        result = self.geometry_query(fixture, feedback=True, setup=f'''
result_path = {str(large)!r}
baselines[result_path] = image._feedback_source_snapshot(result_path)
baselines.result_paths.add(result_path)
''')
        self.assertEqual(result['state'], 'OK')
        self.assertIn(str(large), result['sources'])


if __name__ == '__main__':
    unittest.main()
