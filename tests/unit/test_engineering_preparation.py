"""Pure preparation with synthetic native source/executable boundaries; no DCC runs."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))
from test_native_scope import software_scope
from dcc_task_runtime import owned_process
from dcc_task_runtime.native_scope import NativeScope
import prepare_controlled_engineering as preparation


class EngineeringPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        install = self.root / 'software-install/Houdini21.0.631'
        framework = install / 'Frameworks/Houdini.framework/Versions/21.0'
        self.install = install
        files = {
            framework / 'Resources/bin/husk': 'explicit fake husk file; never execute',
            framework / 'Resources/bin/hython': 'explicit fake hython file; never execute',
            self.root / 'software-install/Nuke17.0': 'explicit fake Nuke file; never execute',
            framework / 'Resources/houdini/usd/materials/basic_materials/basic_materials.usd':
                'outputs:mtlx:surface.connect ND_standard_surface_surfaceshader',
            framework / 'Resources/houdini/python3.11libs/husd/karmautils.py': '"C.*[LO]" "color4" "lpe"',
            framework / 'Libraries/usd_plugins/usdMtlx/resources/usdMtlx/schema.usda': '# software USD schema source fixture',
            framework / 'Libraries/usd_plugins/usdRender/resources/usdRender/schema.usda': '# software USD schema source fixture',
            framework / 'Libraries/usd_plugins/usdGeom/resources/usdGeom/schema.usda': '# software USD schema source fixture',
            framework / 'Resources/fixture.ocio': 'name: ACEScg\n'}
        materialx = install / 'Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages/MaterialX/libraries/bxdf/standard_surface.mtlx'
        files[materialx] = '<materialx><nodedef name="ND_standard_surface_surfaceshader">' + ''.join(
            '<input name="' + name + '" type="' + kind + '" />' for name, kind in
            {'base': 'float', 'specular': 'float', 'emission': 'float', 'emission_color': 'color3', 'opacity': 'color3'}.items()) + '</nodedef></materialx>'
        for path, value in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value); path.chmod(0o700)
        hosts = {name: preparation.file_record(path) for name, path in {
            'hython': framework / 'Resources/bin/hython', 'husk': framework / 'Resources/bin/husk',
            'nuke': self.root / 'software-install/Nuke17.0',
            'supervisor_python': Path(sys.executable).resolve()}.items()}
        self.binding = software_scope(self.root, scope_id='explicit-software-engineering-preparation',
            status='PREPARED_NOT_AUTHORIZED', execution_authorized=False,
            project_color={'schema': 'bridge.project-color/1.0', 'project_id': 'software-project',
                'revision': 1, 'colorspace': 'ACEScg', 'source': 'human_project_selection'},
            versions={'houdini': '21.0.631', 'nuke': '17.0v1'}, hosts=hosts,
            native_color_tokens={'houdini_static_config': preparation.file_record(framework / 'Resources/fixture.ocio')},
            operations=[{'id': name} for name in ('alpha-h21', 'alpha-nuke', 'formal-h21', 'consume-nuke')])
        self.scope_path = Path(self.binding['path'])
        self.scope_bytes = self.scope_path.read_bytes()
        self.native = NativeScope(self.binding)
        self.state_bytes = self.native.state_path.read_bytes()

    def prepare(self):
        with mock.patch.object(owned_process, 'launch', side_effect=AssertionError('DCC launch forbidden')) as launch:
            result = preparation.prepare(self.scope_path)
        launch.assert_not_called()
        return result

    def test_official_preferences_use_the_documented_hver_macro_inside_scope(self):
        from dcc_task_runtime.render_profiles import OFFICIAL
        scope=dict(self.native.scope,scene_profile=OFFICIAL)
        environment=preparation._environment(scope)
        declared=environment['HOUDINI_USER_PREF_DIR']
        self.assertIn('__HVER__',declared)
        actual=Path(declared.replace('__HVER__','21.0'))
        self.assertTrue(actual.is_relative_to(self.root/'runtime'))
        self.assertTrue(actual.is_dir())
        self.assertEqual(self.native.snapshot()['dcc_starts'],0)

    def test_husk_ready_adapter_uses_canonical_compiled_filename_without_file_global(self):
        adapter = ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'
        linked = self.root / 'linked'; linked.mkdir()
        (linked / adapter.name).symlink_to(adapter)
        parent_link = self.root / 'parent-link'; parent_link.symlink_to(adapter.parent, target_is_directory=True)
        missing_owned = self.root / 'missing-owned'; missing_owned.mkdir()
        (missing_owned / adapter.name).write_bytes(adapter.read_bytes())
        linked_owned = self.root / 'linked-owned'; linked_owned.mkdir()
        (linked_owned / adapter.name).write_bytes(adapter.read_bytes())
        (linked_owned / 'owned_process.py').symlink_to(adapter.with_name('owned_process.py'))
        cases = {'valid': str(adapter), 'relative': adapter.name, 'empty': '', 'pseudo': '<string>',
            'noncanonical': str(adapter.parent / '..' / 'dcc_task_runtime' / adapter.name),
            'wrong-name': str(adapter.with_name('owned_process.py')), 'source-link': str(linked / adapter.name),
            'parent-link': str(parent_link / adapter.name), 'missing-owned': str(missing_owned / adapter.name),
            'owned-link': str(linked_owned / adapter.name)}
        code = '''import pathlib,runpy,sys
adapter=pathlib.Path(sys.argv[1]);filename=sys.argv[2]
def load(path,run_name):
    assert path==str(pathlib.Path(filename).with_name('owned_process.py'))
    assert run_name=='_bridge_husk_owned_runtime_ready'
    print('fixed-runtime-loaded',flush=True)
    return {'runtime_ready_and_wait':lambda:print('runtime-helper-reached',flush=True)}
runpy.run_path=load
namespace={'__name__':'explicit_fileless_husk_prerender'}
assert '__file__' not in namespace
exec(compile(adapter.read_bytes(),filename,'exec'),namespace)
'''
        self.adapter_context_results = []
        for name, filename in cases.items():
            command = [sys.executable, '-I', '-B', '-c', code, str(adapter), filename]
            result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=10)
            self.adapter_context_results.append({'case': name, 'command': command,
                'source_sha256': preparation.file_record(adapter)['sha256'], 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr})
            with self.subTest(case=name):
                if name == 'valid':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), ['fixed-runtime-loaded', 'runtime-helper-reached'])
                else:
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('HUSK_RUNTIME_READY_SOURCE_INVALID', result.stderr)

    def test_alpha_preparation_authors_and_binds_native_output_conversion(self):
        import prepare_native_alpha_scene as chart
        from houdini_bridge.controlled_output import controlled_route_sha256
        framework = self.root / 'fake-framework'
        husk = framework / 'Resources/bin/husk'
        husk.parent.mkdir(parents=True)
        husk.write_text('not executable: preparation fixture')
        with mock.patch.object(chart, '_sources', return_value=({}, framework)):
            prepared = chart.prepare(output_root=self.root / 'alpha-color',
                houdini_root=self.root / 'Houdini21.0.631', colorspace='ACEScg')
        scene = Path(prepared['scene']['path']).read_text()
        self.assertIn('driver:parameters:husk:source_colorspace = "scene_linear"', scene)
        self.assertIn('driver:parameters:husk:output_colorspace = "ACEScg"', scene)
        self.assertNotIn('oiio:ColorSpace', scene)
        self.assertEqual(prepared['route']['output_color_route'], {'source': 'scene_linear', 'output': 'ACEScg'})
        self.assertEqual(prepared['route_sha256'], controlled_route_sha256(prepared['route'], require_color_route=True))
        self.assertEqual(prepared['native_execution_status'], 'NOT_RUN')
        self.assertEqual(prepared['opacities'], [0., .5, 1.])

    def test_alpha_software_boundary_honors_actual_usda_four_component_precision(self):
        import prepare_native_alpha_scene as chart
        from engineering_houdini_api_fixture import write_boundaries
        from dcc_task_runtime.exr_codec import read_exr
        scripts=write_boundaries(self.root/'format-api',ROOT,husk_executable=Path(sys.executable))
        self.assertIn('husk:format = "color4h"',chart.chart_usda(self.root/'example.exr','ACEScg'))
        for precision in ('float','color4h'):
            with self.subTest(precision=precision):
                output=self.root/(precision+'.exr');scene=self.root/(precision+'.usda')
                text=chart.chart_usda(output,'ACEScg')
                if precision=='float':text=text.replace('husk:format = "color4h"','husk:format = "float"')
                scene.write_text(text)
                result=subprocess.run([sys.executable,'-B',str(scripts['alpha_husk_script']),
                    '--output',str(output),str(scene)],cwd=self.root,
                    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=20)
                if precision=='float':
                    self.assertNotEqual(result.returncode,0,'scalar USD format was incorrectly synthesized as RGBA')
                    self.assertIn('SOFTWARE_ALPHA_FORMAT_REQUIRES_COLOR4H',result.stderr)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    decoded=read_exr(output)
                    self.assertEqual(decoded['channels'],sorted('RGBA'))
                    self.assertTrue(all(c['pixel_type']==1 for c in decoded['channel_layout']['channels']))
                    for x,alpha in ((16,0.),(64,.5),(112,1.)):
                        samples=decoded['rows'][64]['channels']
                        self.assertEqual(samples['A'][x],alpha)
                        for channel in 'RGB':self.assertAlmostEqual(samples[channel][x],.8*alpha,delta=.02)
                    scene.write_text(text.replace('(0.8, 0.8, 0.8)','(0.6, 0.4, 0.2)')
                        .replace('(0.5, 0.5, 0.5)','(0.25, 0.25, 0.25)'))
                    changed=subprocess.run([sys.executable,'-B',str(scripts['alpha_husk_script']),
                        '--output',str(output),str(scene)],cwd=self.root,
                        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=20)
                    self.assertEqual(changed.returncode,0,changed.stderr)
                    samples=read_exr(output)['rows'][64]['channels']
                    self.assertEqual(samples['A'][64],.25)
                    for channel,color in zip('RGB',(.6,.4,.2)):
                        self.assertAlmostEqual(samples[channel][64],color*.25,delta=.001)

    def test_complete_snapshot_preparation_and_repeat_preserve_all_frozen_bytes(self):
        result = self.prepare()
        self.assertEqual(result['preflight']['state'], 'PREPARED')
        self.assertEqual(result['driver_preflight']['state'], 'PREPARED')
        self.assertEqual(result['native_execution_status'], 'NOT_RUN')
        bindings = json.loads(Path(result['bindings']['path']).read_text())
        project, snapshot = Path(bindings['project_root']), Path(result['snapshot_root'])
        self.assertEqual(bindings['main_plan'], preparation.MAIN_PLAN)
        self.assertEqual(len(bindings['native_start_inventory']), 8)
        self.assertNotIn('alpha_calibration', json.loads(Path(bindings['deployments']['houdini']['path']).read_text()))
        self.assertEqual(bindings['environment'].get('HOME'), os.environ.get('HOME'))
        self.assertNotIn('PYTHONPATH', bindings['environment'])
        for name in ('TMPDIR', 'TEMP', 'HOUDINI_USER_PREF_DIR', 'HOUDINI_TEMP_DIR', 'NUKE_TEMP_DIR'):
            self.assertTrue(Path(bindings['environment'][name]).is_relative_to(self.root))
        self.assertNotIn(str(self.native.key_path), bindings['source_freeze'])
        self.assertFalse(any('.native-control' in record['path'] for record in result['immutable_files']))
        self.assertEqual(bindings['outputs']['houdini_pattern'], str(project / 'saves/main.%04d.exr'))
        baseline = ROOT / 'docs/official-baselines/karma/frozen-scene-v2.json'
        copied = self.root / 'frozen-inputs/frozen-scene-v2.json'
        self.assertEqual(copied.read_bytes(), baseline.read_bytes())
        manifest = json.loads((project / 'control/run.json').read_text())
        self.assertEqual(manifest['construction_input_manifest'][0]['source_uri'], str(copied))
        self.assertEqual(bindings['project_files']['manifest']['path'], str(project / 'control/run.json'))
        self.assertIn(str(snapshot / 'tools/run_controlled_engineering.py'), bindings['source_freeze'])
        adapter = snapshot / 'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py'
        alpha = json.loads(Path(bindings['alpha_preparation']['path']).read_text())
        self.assertEqual(alpha['runtime_ready_adapter'], preparation.file_record(adapter))
        self.assertEqual(bindings['source_freeze'][str(adapter)], preparation.file_record(adapter)['sha256'])
        for name in ('activate_controlled_engineering.py', 'prepare_workbuddy.py', 'prepare_workbuddy_graph.py'):
            self.assertEqual((snapshot / 'tools' / name).read_bytes(), (ROOT / 'tools' / name).read_bytes())
        self.assertEqual((snapshot / 'docs/official-baselines/karma/frozen-scene-v2.json').read_bytes(), baseline.read_bytes())
        self.assertTrue(all(str(self.root) in path for path in bindings['source_freeze']))
        original = {record['path']: Path(record['path']).read_bytes() for record in result['immutable_files']}
        repeated = self.prepare()
        self.assertEqual(repeated['bindings'], result['bindings'])
        self.assertEqual({path: Path(path).read_bytes() for path in original}, original)
        self.assertEqual(self.scope_path.read_bytes(), self.scope_bytes)
        self.assertEqual(self.native.state_path.read_bytes(), self.state_bytes)
        self.assertEqual(self.native.snapshot()['dcc_starts'], 0)
        self.assertFalse(any(snapshot.rglob('*.pyc')))

    def test_changed_snapshot_source_is_refused_without_overwrite(self):
        result = self.prepare()
        path = Path(result['snapshot_root']) / 'tools/run_alpha_calibration.py'
        path.write_bytes(path.read_bytes() + b'\n# explicit test mutation\n')
        changed = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'FROZEN_FILE_CHANGED'):
            self.prepare()
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(self.scope_path.read_bytes(), self.scope_bytes)
        self.assertEqual(self.native.snapshot()['dcc_starts'], 0)

    def test_missing_frozen_file_is_refused_without_reconstruction(self):
        result = self.prepare()
        path = Path(result['snapshot_root']) / 'tools/run_controlled_engineering.py'
        path.unlink()
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(path.exists())
        self.assertEqual(self.scope_path.read_bytes(), self.scope_bytes)
        self.assertEqual(self.native.snapshot()['dcc_starts'], 0)


if __name__ == '__main__': unittest.main()
