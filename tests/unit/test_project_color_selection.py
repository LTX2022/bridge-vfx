"""Human selection validation and deployment propagation without host launch."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
from dcc_task_runtime.project_color import validate_project_color
from vfx_pipeline.production_hosts import validate_deployments

SELECTION = {'schema': 'bridge.project-color/1.0', 'project_id': '项目一',
             'revision': 1, 'colorspace': 'User Selected Native Token',
             'source': 'human_project_selection'}


class ProjectColorSelectionTests(unittest.TestCase):
    def test_canonical_detached_selection(self):
        value = dict(SELECTION)
        actual = validate_project_color(value)
        self.assertEqual(actual, value)
        value['colorspace'] = 'changed'
        self.assertEqual(actual, SELECTION)

    def test_missing_and_invalid_selection(self):
        with self.assertRaisesRegex(ValueError, '^PROJECT_COLOR_SELECTION_REQUIRED$'):
            validate_project_color(None)
        invalid = [{}, [], {**SELECTION, 'native_verified': True}]
        for key, values in {'schema': ['wrong'], 'source': ['native'],
                            'revision': [True, 0, -1, 1.5],
                            'project_id': ['', ' x', 'a'*257, 1],
                            'colorspace': ['', 'x\n', '\x00x', 'a'*257]}.items():
            invalid.extend({**SELECTION, key: value} for value in values)
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^PROJECT_COLOR_SELECTION_INVALID$'):
                validate_project_color(value)

    def test_deployment_match_mismatch_absence_and_detachment(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            python = str(Path(sys.executable).resolve())
            common = {'lifecycle': 'task_owned', 'executable': python,
                      'supervisor_executable': python, 'task_root': str(root),
                      'session_seconds': 30, 'evidence_source': 'software_test',
                      'resource_budget': {'roots': [str(root)], 'max_bytes': 1024}}
            h = {**common, 'application': 'houdini', 'version': '22.0.459'}
            n = {**common, 'application': 'nuke', 'version': '17.0v1'}
            kwargs = dict(controller_root=root, repo_root=ROOT, allow_software_processes=True)
            self.assertTrue(all('project_color' not in c for c in validate_deployments(h,n,**kwargs)))
            h['project_color'] = dict(SELECTION)
            validate_deployments(h,n,**kwargs)
            n['project_color'] = dict(SELECTION)
            configs = validate_deployments(h,n,**kwargs)
            h['project_color']['revision'] = 2
            self.assertEqual(configs[0]['project_color'], SELECTION)
            with self.assertRaisesRegex(ValueError, 'PROJECT_COLOR_SELECTION_INVALID:deployment_mismatch'):
                validate_deployments(h,n,**kwargs)

    def test_cli_pair_and_both_hosts_with_no_implicit_selection(self):
        spec = importlib.util.spec_from_file_location('project_color_cli', ROOT/'tools/configure_production_hosts.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases = [([], True), (['--project-id', 'p'], False),
                 (['--project-colorspace', 'Token'], False),
                 (['--project-id', 'p', '--project-colorspace', 'Token', '--project-color-revision', '0'], False),
                 (['--project-id', 'p', '--project-colorspace', 'Token', '--project-color-revision', '3'], True)]
        for extra, success in cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as name:
                root = Path(name).resolve()
                output = root/'config.json'
                python = str(Path(sys.executable).resolve())
                argv = ['configure', '--output', str(output), '--task-root', str(root),
                        '--houdini-executable', python, '--nuke-executable', python,
                        '--python-executable', python, '--houdini-version', '22.0.459',
                        '--max-bytes', '1024', '--session-seconds', '30', *extra]
                with mock.patch.object(sys,'argv',argv), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    if not success:
                        with self.assertRaises(SystemExit): module.main()
                        self.assertFalse(output.exists())
                        continue
                    self.assertEqual(module.main(),0)
                payload = json.loads(output.read_text())
                if not extra:
                    self.assertTrue(all('project_color' not in c for c in payload.values()))
                else:
                    self.assertEqual(payload['houdini']['project_color'], payload['nuke']['project_color'])
                    self.assertEqual(payload['houdini']['project_color'], {**SELECTION, 'project_id':'p', 'colorspace':'Token', 'revision':3})


if __name__ == '__main__': unittest.main()
