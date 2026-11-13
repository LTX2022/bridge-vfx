import importlib.util
import hashlib
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
try:
    from prepare_workbuddy_graph import prepare_graph
finally:
    sys.path.pop(0)


@unittest.skipIf(sys.version_info<(3,11),'standalone launcher requires Python 3.11')
class GraphBundleTests(unittest.TestCase):
    def test_official_derivation_is_written_before_bundle_hashes(self):
        from houdini_bridge.official_karma_inputs import derivation_rule
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            root=Path(directory)
            for official in (False,True):
                with self.subTest(official=official):
                    bundle=root/('official' if official else 'legacy')
                    kwargs={'official_case_derivation':derivation_rule(root)} if official else {}
                    prepare_graph(bundle,app=None,scheduler_root=root/'scheduler',**kwargs)
                    manifest=json.loads((bundle/'control/run.json').read_text())
                    if official:
                        self.assertEqual(manifest['domain_pack'],'lighting_camera_render_v1')
                        self.assertEqual(manifest['official_case_derivation'],kwargs['official_case_derivation'])
                    else:
                        self.assertEqual(manifest['domain_pack'],'pyro_smoke_v1')
                        self.assertNotIn('official_case_derivation',manifest)
                    value=json.loads((bundle/'bundle-manifest.json').read_text())
                    self.assertIn('control/run.json',{row['path'] for row in value['files']})
                    for row in value['files']:
                        self.assertEqual(hashlib.sha256((bundle/row['path']).read_bytes()).hexdigest(),row['sha256'],row['path'])

    def test_standalone_snapshot_export_and_no_permission_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=root/'app';(app/'Contents/MacOS').mkdir(parents=True)
            (app/'Contents/MacOS/Main').write_bytes(b'fixture')
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.tencent.workbuddy.mac','CFBundleShortVersionString':'fixture','CFBundleExecutable':'Main'}))
            bundle=root/'bundle';prepare_graph(bundle,app=app,scheduler_root=root/'installation')
            self.assertFalse((bundle/'project/.workbuddy/settings.json').exists())
            for name in ('verify_controlled_output.py', 'prepare_native_alpha_scene.py', 'run_alpha_calibration.py',
                         'run_controlled_engineering.py', 'prepare_controlled_engineering.py', 'prepare_nuke_project.py',
                         'activate_controlled_engineering.py', 'prepare_workbuddy_graph.py', 'prepare_workbuddy.py'):
                frozen=bundle/'control/snapshot/tools'/name
                self.assertEqual(frozen.read_bytes(),(ROOT/'tools'/name).read_bytes())
            baseline=Path('docs/official-baselines/karma/frozen-scene-v2.json')
            self.assertEqual((bundle/'control/snapshot'/baseline).read_bytes(),(ROOT/baseline).read_bytes())
            detached=subprocess.run([sys.executable,'-I',str(bundle/'control/snapshot/tools/verify_controlled_output.py'),'--help'],
                                    capture_output=True,text=True,timeout=15,cwd=root)
            self.assertEqual(detached.returncode,0,detached.stderr)
            config=json.loads((bundle/'project/.workbuddy/mcp.json').read_text())['mcpServers']['bridge-hy3-graph']
            command=[config['command'],*config['args'],'--export']
            result=subprocess.run(command,capture_output=True,text=True,timeout=15,cwd=root)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(json.loads(result.stdout)['release_acceptance'])
            target=bundle/'control/snapshot/packages/vfx-pipeline/src/vfx_pipeline/graph_catalog.py'
            target.write_text(target.read_text()+'\n# changed\n')
            changed=subprocess.run(command,capture_output=True,text=True,timeout=15,cwd=root)
            self.assertNotEqual(changed.returncode,0)
            self.assertIn('runtime changed',changed.stderr)
