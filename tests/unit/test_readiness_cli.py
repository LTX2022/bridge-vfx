from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_workbuddy_graph import prepare_graph
from run_full_readiness_cases import prepared_case_factory
from vfx_pipeline.workbuddy_assembly import prepared_graph_facade


class ReadinessCliTests(unittest.TestCase):
    def test_isolated_entry_with_native_encoding_and_chinese_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / '中文 project'
            setup = (
                "import sys; from pathlib import Path; "
                "sys.path.insert(0, sys.argv[1]); "
                "from prepare_workbuddy_graph import prepare_graph; "
                "prepare_graph(Path(sys.argv[2]), app=None, "
                "scheduler_root=Path(sys.argv[2])/'中文 scheduler')"
            )
            interpreter = str(Path(sys._base_executable or sys.executable).resolve())
            prepared = subprocess.run(
                [interpreter, '-I', '-X', 'utf8=0', '-c', setup, str(ROOT / 'tools'), str(project)],
                capture_output=True, timeout=30)
            self.assertEqual(prepared.returncode, 0, prepared.stderr.decode('utf-8', errors='replace'))
            manifest_path = project / 'control/run.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['requested_model'] = '中文模型'
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
            exported = subprocess.run(
                [interpreter, '-I', '-X', 'utf8=0', str(project / 'control/server.py'), '--export'],
                capture_output=True, timeout=30)
            self.assertEqual(exported.returncode, 0, exported.stdout.decode('utf-8', errors='replace'))
            result = json.loads(exported.stdout.decode('utf-8'))
            self.assertNotEqual(result.get('status'), 'error', result)

    def test_invalid_backend_configuration_rejected_before_output_or_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'receipt.json'
            for arguments, message in (
                (['--backend', 'production'], 'production requires --prepared-projects'),
                (['--software-processes'], 'require --backend production'),
                (['--prepared-projects', str(Path(temporary) / 'absent.json')], 'require --backend production'),
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / 'tools/run_full_readiness_cases.py'),
                         '--output', str(output), *arguments], capture_output=True, text=True,
                        encoding='utf-8', timeout=15,
                        env=dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1'))
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(message, result.stderr)
                    self.assertFalse(output.exists())

    def test_prepared_case_requires_exact_version_and_existing_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve()
            case = 'lighting_camera_render_v1__build_inspect'
            for mapping in ({}, {'21.0.631': {case: 'relative'}},
                            {'21.0.631': {case: str(project)}}):
                with self.subTest(mapping=mapping):
                    with self.assertRaisesRegex(ValueError, 'FORMAL_CASE_CONFIG_REQUIRED'):
                        prepared_case_factory(mapping, '21.0.631')(
                            case_id=case, domain='lighting_camera_render_v1', scenario='build_inspect')
            control = project / 'control'
            control.mkdir()
            (control / 'run.json').write_text(json.dumps({'production_host': {'version': '22.0.429'}}), encoding='utf-8')
            (control / 'snapshot-manifest.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'FORMAL_CASE_VERSION_MISMATCH'):
                prepared_case_factory({'21.0.631': {case: str(project)}}, '21.0.631')(
                    case_id=case, domain='lighting_camera_render_v1', scenario='build_inspect')

    def test_production_missing_config_and_changed_snapshot_never_fall_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / '中文 project'
            prepare_graph(project, app=None, scheduler_root=project / 'scheduler')
            manifest = project / 'control/run.json'
            snapshot = project / 'control/snapshot'
            with self.assertRaisesRegex(ValueError, 'PRODUCTION_CONFIG_REQUIRED'):
                with prepared_graph_facade(manifest, repo_root=snapshot,
                                           scheduler_root=project / 'scheduler', backend='production'):
                    self.fail('production must refuse absent deployment configuration')
            source = snapshot / 'packages/vfx-pipeline/src/vfx_pipeline/graph_catalog.py'
            source.write_bytes(source.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'runtime changed'):
                with prepared_graph_facade(manifest, repo_root=snapshot,
                                           scheduler_root=project / 'scheduler', backend='diagnostic'):
                    self.fail('changed snapshot must fail before controller construction')
