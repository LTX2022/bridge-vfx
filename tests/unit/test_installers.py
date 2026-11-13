from __future__ import annotations

import json
import importlib.util
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from nuke_bridge.install import BEGIN, END, install, uninstall


class InstallerTests(unittest.TestCase):
    def test_nuke_install_migrates_legacy_block_and_preserves_plugins(self) -> None:
        legacy = """import nuke\n\n# plugin before\nnuke.pluginAddPath('before')\n\n# nuke-bridge MCP addon\nimport os as _nb_os\n_nuke_bridge_addon = '/old'\nif _nb_os.path.isdir(_nuke_bridge_addon):\n    if nuke.env.get('gui'):\n        try:\n            import listener as _nb_listener\n            _port = _nb_listener.start_listener()\n        except Exception as _e:\n            pass\n\n# plugin after\nnuke.pluginAddPath('after')\n"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            plugin.mkdir()
            (plugin / "nuke_bridge_addon.py").write_text("# test\n", encoding="utf-8")
            nuke_dir = root / "nuke"
            nuke_dir.mkdir()
            init = nuke_dir / "init.py"
            init.write_text(legacy, encoding="utf-8")
            backup_dir = root / "backups"
            install(plugin, nuke_dir, backup_dir)
            migrated = init.read_text(encoding="utf-8")
            self.assertIn(BEGIN, migrated)
            self.assertIn(END, migrated)
            self.assertIn("if _nuke_bridge_nuke.env.get('gui'):", migrated)
            self.assertNotIn("nuke-bridge MCP addon", migrated)
            self.assertIn("pluginAddPath('before')", migrated)
            self.assertIn("pluginAddPath('after')", migrated)
            manifests = list(backup_dir.rglob("manifest.json"))
            self.assertEqual(len(manifests), 1)
            self.assertTrue(json.loads(manifests[0].read_text(encoding="utf-8"))["original_exists"])
            self.assertTrue(uninstall(nuke_dir, backup_dir))
            restored = init.read_text(encoding="utf-8")
            self.assertIn("pluginAddPath('before')", restored)
            self.assertIn("pluginAddPath('after')", restored)
            self.assertNotIn(BEGIN, restored)


class BundledDeploymentInstallerTests(unittest.TestCase):
    def _installer(self, skill):
        source = Path(__file__).resolve().parents[2]/'skills'/skill/'scripts/install_runtime.py'
        spec = importlib.util.spec_from_file_location('installer_'+skill.replace('-','_'),source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _bundle(self, root):
        (root/'plugins').mkdir(parents=True)
        for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
            directory = root/'deploy/packages'/package
            (directory/'src'/package.replace('-','_')).mkdir(parents=True)
            (directory/'pyproject.toml').write_text('[project]\nname = "'+package+'"\nversion = "1.0"\n')
            (directory/'src'/package.replace('-','_')/'__init__.py').write_text('VALUE = 1\n')
        worker = root/'deploy/packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
        worker.write_text('# bundled worker\n')
        (root/'deploy/tools').mkdir()
        for name in ('prepare_workbuddy_graph.py','prepare_workbuddy.py','nuke_owned_render_worker.py',
                     'verify_skill_lifecycle.py','native_schema_test_boundary.py'):
            (root/'deploy/tools'/name).write_text('print("bundled tool")\n')
        for relative in ('controller-entry/accept_core_chain.py','docs/native-basis/hda-interface-capture.json',
                         'docs/native-basis/native-boundary-metadata-supplement.json'):
            resource = root/'deploy'/relative;resource.parent.mkdir(parents=True,exist_ok=True);resource.write_text('{}\n')
        shutil.copytree(root/'deploy/packages/dcc-task-runtime',root/'runtime/dcc-task-runtime')
        source = Path(__file__).resolve().parents[2] / 'packages/dcc-task-runtime/src/dcc_task_runtime'
        for name in ('platform_support.py', 'windows_process.py'):
            for tree in ('deploy/packages', 'runtime'):
                destination = root / tree / 'dcc-task-runtime/src/dcc_task_runtime' / name
                destination.write_bytes((source / name).read_bytes())

    def test_readonly_activation_file_replacement_preserves_requested_bytes(self):
        for skill in ('houdini-bridge', 'nuke-bridge', 'vfx-visual-twin'):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'bundle'; self._bundle(root)
                installer = self._installer(skill); installer.ROOT = root
                target = Path(temporary) / 'target'; target.mkdir()
                active = target / 'active.json'
                active.write_bytes(b'old\n'); active.chmod(0o400)
                try:
                    installer.atomic_bytes(active, b'new\n')
                    self.assertEqual(active.read_bytes(), b'new\n')
                finally:
                    active.chmod(0o600)

    def test_missing_worker_and_source_mismatch_block_install_before_activation(self):
        for skill in ('houdini-bridge','nuke-bridge','vfx-visual-twin'):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)/'bundle';self._bundle(root)
                installer = self._installer(skill);installer.ROOT = root
                worker = root/'deploy/packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
                worker.unlink()
                with self.assertRaisesRegex(ValueError,'missing deployment graph worker'):
                    installer.execute(Path(temporary)/'target','install')
                self.assertFalse((Path(temporary)/'target/active.json').exists())
                worker.write_text('# worker\n')
                (root/'runtime/dcc-task-runtime/src/dcc_task_runtime/__init__.py').write_text('VALUE = 2\n')
                with self.assertRaisesRegex(ValueError,'runtime/deployment source mismatch'):
                    installer.execute(Path(temporary)/'target','install')

    def test_deployment_only_change_updates_and_rolls_back_actual_tool(self):
        for skill in ('houdini-bridge','nuke-bridge','vfx-visual-twin'):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)/'bundle';self._bundle(root)
                installer = self._installer(skill);installer.ROOT = root
                target = Path(temporary)/'target'
                first = installer.execute(target,'install')
                def tool():
                    return subprocess.run([sys.executable,'-I',str(target/'run_runtime.py'),'--tool',
                        'prepare_workbuddy_graph.py'],capture_output=True,text=True,check=True).stdout
                self.assertEqual(tool(),'bundled tool\n')
                (root/'deploy/tools/prepare_workbuddy_graph.py').write_text('print("updated bundled tool")\n')
                second = installer.execute(target,'install')
                self.assertNotEqual(first['active'],second['active'])
                self.assertEqual(tool(),'updated bundled tool\n')
                installer.execute(target,'rollback')
                self.assertEqual(tool(),'bundled tool\n')
                result = subprocess.run([sys.executable,'-I',str(target/'run_runtime.py'),'--tool','../escape.py'],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('existing bundled Python basename',result.stderr)
                installer.execute(target,'uninstall')
                self.assertFalse((target/'versions').exists())


    def _registration_writer(self, target, generation):
        (target/'houdini-packages').mkdir(exist_ok=True)
        (target/'nuke').mkdir(exist_ok=True)
        (target/'houdini-packages/houdini_bridge.json').write_text(json.dumps({'generation':generation}))
        (target/'nuke/init.py').write_text('# unrelated plugin\nGENERATION = '+repr(generation)+'\n')

    def _activation_snapshot(self, target):
        result = {}
        for name in ('active.json','run_runtime.py','houdini-packages/houdini_bridge.json','nuke/init.py'):
            p=target/name
            result[name] = ('directory',None) if p.is_dir() else ('file',p.read_bytes(),stat.S_IMODE(p.stat().st_mode)) if p.exists() else ('absent',None)
        return result

    def test_existing_generation_requires_complete_trusted_content(self):
        cases=('normal','worker','tool','controller','site','extra','empty','file','symlink','directory','manifest')
        for skill in ('houdini-bridge','nuke-bridge','vfx-visual-twin'):
            for case in cases:
                with self.subTest(skill=skill,case=case), tempfile.TemporaryDirectory() as temporary:
                    root=Path(temporary)/'bundle';self._bundle(root)
                    installer=self._installer(skill);installer.ROOT=root
                    target=Path(temporary)/'target'
                    with patch.object(installer,'register',side_effect=self._registration_writer):
                        first=installer.execute(target,'install')
                    final=target/'versions'/first['active']
                    corrupt={'worker':'deploy/packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py',
                             'tool':'deploy/tools/prepare_workbuddy_graph.py',
                             'controller':'deploy/controller-entry/accept_core_chain.py',
                             'site':'site/dcc_task_runtime/__init__.py'}
                    if case in corrupt:(final/corrupt[case]).write_text('corrupt bytes\n')
                    elif case=='extra':(final/'deploy/untrusted.py').write_text('print("foreign")\n')
                    elif case in ('empty','file'):
                        shutil.rmtree(final)
                        final.mkdir() if case=='empty' else final.write_text('not a directory\n')
                    elif case=='directory':(final/'plugins').rmdir()
                    elif case=='manifest':(final/'generation-manifest.json').write_text('{"schema":"bridge.skill-generation/1","entries":{}}\n')
                    elif case=='symlink':
                        file=final/'deploy/tools/prepare_workbuddy_graph.py';file.unlink()
                        try:
                            file.symlink_to(root/'deploy/tools/prepare_workbuddy_graph.py')
                        except OSError as error:
                            if sys.platform == 'win32' and getattr(error, 'winerror', None) == 1314:
                                raise unittest.SkipTest('Windows symbolic-link privilege unavailable; symbolic-link case not run') from error
                            raise
                    before=self._activation_snapshot(target)
                    with patch.object(installer,'register',side_effect=self._registration_writer) as registration:
                        if case=='normal':
                            self.assertEqual(installer.execute(target,'install')['active'],first['active'])
                        else:
                            with self.assertRaises((ValueError,OSError)):
                                installer.execute(target,'install')
                            registration.assert_not_called()
                    self.assertEqual(self._activation_snapshot(target),before)

    def test_launcher_failure_restores_exact_activation_state(self):
        for skill in ('houdini-bridge','nuke-bridge','vfx-visual-twin'):
            for upgrade in (False,True):
                for phase in ('directory','write','replace','after_launcher'):
                    with self.subTest(skill=skill,upgrade=upgrade,phase=phase), tempfile.TemporaryDirectory() as temporary:
                        root=Path(temporary)/'bundle';self._bundle(root)
                        installer=self._installer(skill);installer.ROOT=root
                        target=Path(temporary)/'target';target.mkdir()
                        self._registration_writer(target,'existing-other-setting')
                        if upgrade:
                            with patch.object(installer,'register',side_effect=self._registration_writer):installer.execute(target,'install')
                            (root/'deploy/tools/prepare_workbuddy_graph.py').write_text('print("next version")\n')
                            (target/'run_runtime.py').write_bytes((target/'run_runtime.py').read_bytes()+b'\n# original launcher bytes\n')
                            (target/'run_runtime.py').chmod(0o640)
                        if phase=='directory':
                            (target/'run_runtime.py').unlink(missing_ok=True);(target/'run_runtime.py').mkdir()
                        before=self._activation_snapshot(target)
                        calls=[]
                        real_replace=installer.os.replace
                        def broken_replace(source,destination):
                            name=Path(destination).name
                            if not calls and (phase=='replace' and name=='run_runtime.py' or phase=='after_launcher' and name=='active.json'):
                                calls.append(name);raise OSError('controlled activation replace failure')
                            return real_replace(source,destination)
                        if phase=='write' and hasattr(installer,'atomic_bytes'):
                            original=installer.atomic_bytes
                            def broken_bytes(path,data,mode=None):
                                if Path(path).name=='run_runtime.py' and not calls:
                                    calls.append('write');raise OSError('controlled launcher write failure')
                                return original(path,data,mode)
                            failure=patch.object(installer,'atomic_bytes',side_effect=broken_bytes)
                        elif phase=='write':
                            original_write=Path.write_text
                            def broken_text(path,*args,**kwargs):
                                if path.name=='run_runtime.py' and not calls:
                                    calls.append('write');raise OSError('controlled launcher write failure')
                                return original_write(path,*args,**kwargs)
                            failure=patch.object(Path,'write_text',broken_text)
                        else:failure=patch.object(installer.os,'replace',side_effect=broken_replace)
                        with patch.object(installer,'register',side_effect=self._registration_writer), failure:
                            with self.assertRaises((ValueError,OSError)):installer.execute(target,'install')
                        self.assertEqual(self._activation_snapshot(target),before)
                        self.assertFalse((target/'activation-journal.json').exists())

    def test_rollback_checks_generation_and_failed_recovery_keeps_journal(self):
        for skill in ('houdini-bridge','nuke-bridge','vfx-visual-twin'):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'bundle';self._bundle(root)
                installer=self._installer(skill);installer.ROOT=root
                target=Path(temporary)/'target'
                with patch.object(installer,'register',side_effect=self._registration_writer):
                    first=installer.execute(target,'install')
                    (root/'deploy/tools/prepare_workbuddy_graph.py').write_text('print("updated")\n')
                    installer.execute(target,'install')
                old=target/'versions'/first['active']
                (old/'deploy/tools/prepare_workbuddy_graph.py').write_text('broken rollback bytes\n')
                before=self._activation_snapshot(target)
                with patch.object(installer,'register') as registration:
                    with self.assertRaises(ValueError):installer.execute(target,'rollback')
                    registration.assert_not_called()
                self.assertEqual(self._activation_snapshot(target),before)
                # An uncompleted recovery must retain its durable intent and fail;
                # retry restores the original bytes once the filesystem permits it.
                (target/'run_runtime.py').write_bytes((target/'run_runtime.py').read_bytes()+b'\n# exact before recovery\n')
                snapshot=self._activation_snapshot(target)
                if not hasattr(installer,'atomic_bytes'):
                    self.fail('launcher transaction has no atomic byte restoration')
                original=installer.atomic_bytes
                failed=[]
                def blocked(path,data,mode=None):
                    if Path(path).name=='active.json' and not failed:
                        failed.append(True);raise OSError('controlled failure after launcher replacement')
                    if Path(path).name=='run_runtime.py' and failed:
                        raise OSError('controlled launcher recovery failure')
                    return original(path,data,mode)
                with patch.object(installer,'register',side_effect=self._registration_writer),patch.object(installer,'atomic_bytes',side_effect=blocked):
                    with self.assertRaises(OSError):installer.execute(target,'install')
                self.assertTrue((target/'activation-journal.json').is_file())
                with patch.object(installer,'register') as registration:
                    installer.execute(target,'status');registration.assert_not_called()
                self.assertEqual(self._activation_snapshot(target),snapshot)
                self.assertFalse((target/'activation-journal.json').exists())
