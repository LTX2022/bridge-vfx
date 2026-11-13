import hashlib
import importlib.util
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare_workbuddy', ROOT / 'tools/prepare_workbuddy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@unittest.skipIf(sys.version_info < (3, 11), 'launcher requires Python 3.11')
class PrepareWorkBuddyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'WorkBuddy.app'
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        self.info = {'CFBundleIdentifier': 'com.tencent.workbuddy.mac',
                     'CFBundleShortVersionString': 'test', 'CFBundleExecutable': 'CustomMain'}
        self.write_info()
        (self.app / 'Contents/MacOS/CustomMain').write_bytes(b'synthetic executable metadata fixture')

    def write_info(self):
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps(self.info))

    def test_standalone_export_and_preserve_existing_directory(self):
        destination = self.root / 'bundle'
        module.prepare(destination, app=self.app)
        source_runtime = ROOT/'packages/dcc-task-runtime/src/dcc_task_runtime'
        copied_runtime = destination/'control/runtime/dcc_task_runtime'
        expected = {path.relative_to(source_runtime).as_posix(): path.read_bytes()
                    for path in source_runtime.rglob('*') if path.is_file()
                    and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo')
                    and path.name != '.DS_Store'}
        actual = {path.relative_to(copied_runtime).as_posix(): path.read_bytes()
                  for path in copied_runtime.rglob('*') if path.is_file()}
        self.assertEqual(actual, expected)
        self.assertIn('pipeline_store.py', actual)
        config = json.loads((destination / 'project/.workbuddy/mcp.json').read_text())
        server = config['mcpServers']['bridge-hy3']
        result = subprocess.run([server['command'], *server['args'], '--export'],
                                cwd=self.root, capture_output=True, text=True, timeout=10, check=True)
        exported = json.loads(result.stdout)
        self.assertEqual(exported['observations'], [])
        self.assertFalse(exported['release_acceptance'])
        manifest = json.loads((destination / 'bundle-manifest.json').read_text())
        for item in manifest['files']:
            self.assertEqual(hashlib.sha256((destination / item['path']).read_bytes()).hexdigest(), item['sha256'])
        with self.assertRaises(ValueError): module.prepare(destination, app=self.app)

    def test_declared_executable_escape_rejected(self):
        self.info['CFBundleExecutable'] = '../../outside'
        self.write_info()
        with self.assertRaises(ValueError): module.prepare(self.root / 'bundle', app=self.app)
        self.assertFalse((self.root / 'bundle').exists())

    def test_png_has_valid_dimensions_and_different_content(self):
        a, b = module.png(0), module.png(1)
        self.assertTrue(a.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertNotEqual(a, b)
        self.assertEqual(int.from_bytes(a[16:20], 'big'), 512)
        self.assertEqual(int.from_bytes(a[20:24], 'big'), 384)
