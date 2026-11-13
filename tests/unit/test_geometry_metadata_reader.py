"""Real package/file checks in an isolated Python reader; no DCC execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline')
MODULE = 'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_session.py'


def seal(root):
    entries = []
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name != 'runtime-manifest.json':
            raw = path.read_bytes()
            entries.append({'path': path.relative_to(root).as_posix(), 'bytes': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest()})
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    (root / 'runtime-manifest.json').write_text(json.dumps({'schema_version': 1, 'files': entries,
        'file_manifest_sha256': hashlib.sha256(canonical).hexdigest()}))


CHILD = r'''
import importlib, importlib.util, json, sys
from pathlib import Path
root=Path(sys.argv[1]);mode=sys.argv[2]
for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(root/'runtime/packages'/package/'src'))
def audit(event,args):
    if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn'):
        raise AssertionError('reader must not launch a process')
sys.addaudithook(audit)
from vfx_pipeline import geometry_metadata_completion as metadata
evidence=metadata._StartEvidence()
old=root.parent/'original-production-record.txt'
evidence.add(metadata._record(old))
if mode=='mixed_module':
    module=importlib.import_module('vfx_pipeline.geometry_session')
    foreign=root.parent/'foreign-geometry-session.py'
    foreign.write_bytes(Path(module.__file__).read_bytes())
    spec=importlib.util.spec_from_file_location(module.__name__,foreign)
    replacement=importlib.util.module_from_spec(spec);spec.loader.exec_module(replacement)
    sys.modules[module.__name__]=replacement
elif mode=='foreign_function':
    module=importlib.import_module('vfx_pipeline.geometry_session')
    namespace={}
    exec(compile('def query(self, *args, **kwargs): return None',str(root.parent/'foreign.py'),'exec'),namespace)
    module.GeometrySession.query=namespace['query']
try:
    metadata._reader_evidence(evidence)
    if mode=='changed_after_open':
        path=root/'runtime/packages/vfx-pipeline/src/vfx_pipeline/geometry_session.py'
        path.write_bytes(path.read_bytes()+b'\n# changed after reader admission\n')
    elif mode=='old_source_changed':
        old.write_text('modified original production record')
    evidence.close_check()
except (ValueError,FileNotFoundError) as exc:
    print(json.dumps({'state':'REJECTED','error':str(exc)}))
else:
    print(json.dumps({'state':'VERIFIED','records':len(evidence.records),
                      'original_record_retained':str(old) in evidence.records}))
'''


class GeometryMetadataReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='metadata-reader-fixture-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.template = Path(cls.temporary.name).resolve() / 'template'
        for package in PACKAGES:
            shutil.copytree(ROOT / 'packages' / package / 'src',
                            cls.template / 'runtime/packages' / package / 'src',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (cls.template / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'agent-plugin/scripts/bridge_mcp.py', cls.template / 'scripts/bridge_mcp.py')
        (cls.template / 'plugin.json').write_text(json.dumps({'name':'bridge-vfx','version':'0.4.23'}))
        seal(cls.template)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='metadata-reader-case-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.package = self.directory / 'reader'
        shutil.copytree(self.template, self.package)
        (self.directory / 'original-production-record.txt').write_text('signed original production bytes')

    def run_reader(self, mode='normal'):
        result = subprocess.run([sys.executable, '-I', '-B', '-c', CHILD, str(self.package), mode],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_current_reader_uses_its_complete_package_and_retains_original_evidence(self):
        result = self.run_reader()
        self.assertEqual(result['state'], 'VERIFIED')
        self.assertTrue(result['original_record_retained'])
        self.assertGreater(result['records'], 8)

    def test_unknown_reader_version_is_rejected_with_consistent_manifest(self):
        (self.package / 'plugin.json').write_text(json.dumps({'name':'bridge-vfx','version':'0.4.99'}))
        seal(self.package)
        self.assertEqual(self.run_reader()['state'], 'REJECTED')

    def test_changed_reader_bytes_are_rejected(self):
        path = self.package / MODULE
        path.write_bytes(path.read_bytes() + b'\n# modified reader\n')
        result = self.run_reader()
        self.assertEqual(result['state'], 'REJECTED')
        self.assertEqual(result['error'], 'PLUGIN_BYTES_CHANGED')

    def test_changed_manifest_is_rejected(self):
        path = self.package / 'runtime-manifest.json'
        manifest = json.loads(path.read_text());manifest['files'][0]['sha256'] = '0' * 64
        path.write_text(json.dumps(manifest))
        result = self.run_reader()
        self.assertEqual(result['state'], 'REJECTED')
        self.assertEqual(result['error'], 'PLUGIN_MANIFEST_DIGEST_MISMATCH')

    def test_identical_module_loaded_from_other_directory_is_rejected(self):
        self.assertEqual(self.run_reader('mixed_module')['state'], 'REJECTED')

    def test_function_from_other_source_is_rejected(self):
        self.assertEqual(self.run_reader('foreign_function')['state'], 'REJECTED')

    def test_reader_changed_during_request_is_rejected_at_close(self):
        self.assertEqual(self.run_reader('changed_after_open')['state'], 'REJECTED')

    def test_original_production_evidence_remains_checked_at_close(self):
        self.assertEqual(self.run_reader('old_source_changed')['state'], 'REJECTED')


if __name__ == '__main__':
    unittest.main()
