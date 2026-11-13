#!/usr/bin/env python3
"""Offline, explicitly targeted installation of a bundled Bridge Skill.

The runtime launcher and native registrations refer to the same immutable
content-addressed generation. No pip, network, user site or global config is used.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]


def _path_is_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _platform_support():
    directory = ROOT / 'runtime/dcc-task-runtime/src/dcc_task_runtime'
    if not (directory / 'platform_support.py').is_file():
        raise ValueError('bundled filesystem support is missing')
    name = '_bridge_installer_fs_' + hashlib.sha256(str(directory.resolve()).encode('utf-8')).hexdigest()[:16]
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__package__ = name
        package.__path__ = [str(directory)]
        sys.modules[name] = package
    return importlib.import_module(name + '.platform_support')


def files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))


def fingerprint(root):
    h = hashlib.sha256()
    for path in files(root):
        h.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def self_test():
    errors = []
    packages = sorted((ROOT / 'runtime').glob('*/src'))
    if not packages:
        errors.append('no bundled runtime packages; install from a release ZIP')
    for package in packages:
        if not (package.parent / 'pyproject.toml').is_file():
            errors.append('missing pyproject: ' + package.parent.name)
    deployment = ROOT / 'deploy'
    for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
        if not (deployment/'packages'/package/'pyproject.toml').is_file():
            errors.append('missing deployment package: '+package)
    for tool in ('prepare_workbuddy_graph.py','prepare_workbuddy.py','nuke_owned_render_worker.py',
                 'verify_skill_lifecycle.py','native_schema_test_boundary.py'):
        if not (deployment/'tools'/tool).is_file():
            errors.append('missing deployment tool: '+tool)
    for relative in ('controller-entry/accept_core_chain.py','docs/native-basis/hda-interface-capture.json',
                     'docs/native-basis/native-boundary-metadata-supplement.json'):
        if not (deployment/relative).is_file():
            errors.append('missing deployment resource: '+relative)
    if not (deployment/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py').is_file():
        errors.append('missing deployment graph worker')
    for package in packages:
        deployed = deployment/'packages'/package.parent.name/'src'
        if deployed.is_dir() and fingerprint(package) != fingerprint(deployed):
            errors.append('runtime/deployment source mismatch: '+package.parent.name)
    for plugin in ('houdini', 'nuke'):
        directory = ROOT / 'plugins' / plugin
        if directory.exists():
            implementation = directory / ('_impl/houdini_bridge_addon.py' if plugin == 'houdini' else 'nuke_bridge_addon.py')
            if not implementation.is_file():
                errors.append('missing plugin: ' + plugin)
            deployed = deployment/'plugins'/plugin
            if not deployed.is_dir() or fingerprint(directory) != fingerprint(deployed):
                errors.append('plugin/deployment source mismatch: '+plugin)
    return errors


def atomic_bytes(path, data, mode=None):
    path = Path(path).absolute()
    platform = _platform_support()
    platform._plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    platform._owned_path(path, path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    temporary=Path(temporary_name)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary,mode)
        platform.atomic_replace(temporary, path, owned_root=path.parent)
    finally:
        platform.remove_owned_path(temporary, owned_root=path.parent)


def atomic(path, value):
    atomic_bytes(path,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode('utf-8'))


def _tree_entries(root):
    if _path_is_link(root) or not root.exists():
        raise ValueError('generation source/path missing or symlinked: '+str(root))
    entries={}
    for path in [root,*sorted(root.rglob('*'))] if root.is_dir() else [root]:
        if _path_is_link(path):
            raise ValueError('generation contains a symlink: '+str(path))
        relative=path.relative_to(root).as_posix() if path!=root else ''
        if '__pycache__' in Path(relative).parts or path.suffix in ('.pyc','.pyo') or path.name=='.DS_Store':
            continue
        if path.is_dir():
            entries[relative]={'kind':'directory'}
        elif path.is_file():
            payload=path.read_bytes()
            entries[relative]={'kind':'file','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
        else:
            raise ValueError('generation contains a non-regular path: '+str(path))
    return entries


def generation_manifest():
    entries={'site':{'kind':'directory'}}
    def include(source,prefix):
        for relative,record in _tree_entries(source).items():
            name=prefix+('/'+relative if relative else '')
            if name in entries:
                raise ValueError('runtime package collision: '+name)
            entries[name]=record
    for source in sorted((ROOT/'runtime').glob('*/src/*')):
        if source.name=='__pycache__' or source.suffix in ('.pyc','.pyo') or source.name=='.DS_Store':
            continue
        include(source,'site/'+source.name)
    include(ROOT/'plugins','plugins')
    include(ROOT/'deploy','deploy')
    payload=LAUNCHER.encode('utf-8')
    entries['launcher.py']={'kind':'file','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    return {'schema':'bridge.skill-generation/1','entries':entries}


def manifest_identity(manifest):
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def verify_generation(directory,generation,expected=None):
    if (not isinstance(generation,str) or len(generation)!=64
            or any(c not in '0123456789abcdef' for c in generation)
            or directory.is_symlink() or not directory.is_dir()):
        raise ValueError('invalid installed generation path')
    manifest_path=directory/'generation-manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('installed generation has no trusted manifest')
    declared=json.loads(manifest_path.read_text(encoding='utf-8'))
    if (not isinstance(declared,dict) or declared.get('schema')!='bridge.skill-generation/1'
            or manifest_identity(declared)!=generation or expected is not None and declared!=expected):
        raise ValueError('installed generation manifest identity differs')
    actual=_tree_entries(directory)
    actual.pop('');actual.pop('generation-manifest.json')
    if (actual!=declared.get('entries')
            or any(actual.get(name)!={'kind':'directory'} for name in ('site','plugins','deploy'))
            or actual.get('launcher.py',{}).get('kind')!='file'):
        raise ValueError('installed generation structure/content differs from trusted manifest')
    return declared


LAUNCHER = '''from pathlib import Path
import hashlib, json, runpy, sys
root = Path(__file__).resolve().parent
state = json.loads((root / "active.json").read_text())
generation = root / "versions" / state["active"]
site = generation / "site"
deploy = generation / "deploy"
for package in ("dcc-task-runtime","houdini-bridge","nuke-bridge","vfx-pipeline"):
    sys.path.insert(0,str(deploy / "packages" / package / "src"))
sys.path.insert(0, str(site))
if sys.argv[1:] == ["--deployment-root"]:
    print(json.dumps({"generation":state["active"],"deployment_root":str(deploy)}))
elif sys.argv[1:] == ["--probe"]:
    import dcc_task_runtime
    module = Path(dcc_task_runtime.__file__).resolve()
    if not module.is_relative_to(site.resolve()):
        raise RuntimeError("runtime import escaped installed generation")
    print(json.dumps({"generation": state["active"], "module": str(module), "sha256": hashlib.sha256(module.read_bytes()).hexdigest()}))
elif len(sys.argv) >= 3 and sys.argv[1] == "--tool":
    name = sys.argv[2]
    if Path(name).name != name or not name.endswith(".py") or not (deploy/"tools"/name).is_file():
        raise SystemExit("tool must be an existing bundled Python basename")
    sys.path.insert(0,str(deploy/"tools"))
    sys.argv = [str(deploy/"tools"/name),*sys.argv[3:]]
    runpy.run_path(sys.argv[0],run_name="__main__")
else:
    module = sys.argv.pop(1)
    runpy.run_module(module, run_name="__main__")
'''



def register(target, generation):
    site = target / 'versions' / generation / 'site'
    plugins = target / 'versions' / generation / 'deploy/plugins'
    selected = target / 'versions' / generation / 'plugins'
    env = dict(os.environ, PYTHONPATH=str(site), PYTHONNOUSERSITE='1',
               BRIDGE_SKILLS_APPROVAL_SECRET_FILE=str(target / 'approval.key'),
               NUKE_BRIDGE_BACKUP_DIR=str(target / 'backups'))
    calls = []
    if (selected / 'houdini').is_dir():
        calls.append(["from houdini_bridge.install import install; import sys; install(sys.argv[1], sys.argv[2])", str(plugins / 'houdini'), str(target / 'houdini-packages')])
    if (selected / 'nuke').is_dir():
        calls.append(["from nuke_bridge.install import install; import sys; install(sys.argv[1], sys.argv[2], sys.argv[3])", str(plugins / 'nuke'), str(target / 'nuke'), str(target / 'backups')])
    for call in calls:
        subprocess.run([sys.executable, '-s', '-c', *call], env=env, cwd=target, check=True, capture_output=True, text=True)


ACTIVATION_PATHS=('houdini-packages/houdini_bridge.json','nuke/init.py','active.json','run_runtime.py','approval.key')


def _activation_snapshot(target):
    previous={}
    for name in ACTIVATION_PATHS:
        path=target/name
        if _path_is_link(path) or path.exists() and not path.is_file():
            raise ValueError('activation path is not a regular file: '+name)
        previous[name]=None if not path.exists() else {
            'bytes':path.read_bytes().hex(),'mode':stat.S_IMODE(path.stat().st_mode)}
    return previous


def activate(target, state):
    generation=target/'versions'/state['active']
    verify_generation(generation,state['active'])
    previous=_activation_snapshot(target)
    journal=target/'activation-journal.json'
    atomic(journal,{'schema':'bridge.skill-activation/2','paths':previous})
    try:
        register(target,state['active'])
        old_launcher=previous['run_runtime.py']
        atomic_bytes(target/'run_runtime.py',(generation/'launcher.py').read_bytes(),
                     None if old_launcher is None else old_launcher['mode'])
        atomic(target/'active.json',state)
        _platform_support().remove_owned_path(journal, owned_root=target)
    except BaseException:
        recover(target)
        raise


def recover(target):
    journal=target/'activation-journal.json'
    if not journal.exists():
        return
    payload=json.loads(journal.read_text(encoding='utf-8'))
    previous=payload.get('paths') if isinstance(payload,dict) else None
    if (not isinstance(payload,dict) or payload.get('schema')!='bridge.skill-activation/2' or not isinstance(previous,dict)
            or set(previous)!=set(ACTIVATION_PATHS)):
        raise ValueError('activation journal cannot prove complete prior state')
    decoded={}
    for name,record in previous.items():
        if record is None:
            decoded[name]=None
        elif (isinstance(record,dict) and set(record)=={'bytes','mode'} and isinstance(record['bytes'],str)
                and type(record['mode']) is int and 0<=record['mode']<=0o7777):
            decoded[name]=(bytes.fromhex(record['bytes']),record['mode'])
        else:
            raise ValueError('invalid activation journal record')
    for name,record in decoded.items():
        path=target/name
        if _path_is_link(path) or path.exists() and not path.is_file():
            raise ValueError('activation recovery path is not a regular file: '+name)
        if record is None:
            _platform_support().remove_owned_path(path, owned_root=target)
        elif not path.exists() or path.read_bytes()!=record[0] or stat.S_IMODE(path.stat().st_mode)!=record[1]:
            atomic_bytes(path,record[0],record[1])
    if _activation_snapshot(target)!=previous:
        raise ValueError('activation recovery did not restore exact prior state')
    _platform_support().remove_owned_path(journal, owned_root=target)


@contextlib.contextmanager
def locked(target):
    platform = _platform_support()
    platform.ensure_private_directory(target)
    descriptor = platform.open_private_file(target / '.install.lock', os.O_RDWR | os.O_CREAT)
    with os.fdopen(descriptor, 'r+b') as handle:
        platform.lock_file(handle.fileno())
        try:
            yield
        finally:
            platform.unlock_file(handle.fileno())


def execute(target, action):
    target = Path(target).expanduser().absolute()
    _platform_support()._plain_path(target)
    if _path_is_link(target):
        raise ValueError('installation target cannot be a symlink')
    for relative in ('versions', 'active.json', 'activation-journal.json', 'run_runtime.py', 'houdini-packages', 'houdini-packages/houdini_bridge.json', 'nuke', 'nuke/init.py', 'backups', 'approval.key', '.install.lock'):
        if _path_is_link(target / relative):
            raise ValueError('managed installation path cannot be a symlink: ' + relative)
    with locked(target):
        recover(target)
        active = target / 'active.json'
        state = json.loads(active.read_text(encoding='utf-8')) if active.exists() else {}
        if action == 'install':
            errors = self_test()
            if errors:
                raise ValueError('; '.join(errors))
            expected = generation_manifest()
            generation = manifest_identity(expected)
            versions = target / 'versions'; versions.mkdir(exist_ok=True)
            final = versions / generation
            if final.exists() or _path_is_link(final):
                verify_generation(final,generation,expected)
            else:
                with tempfile.TemporaryDirectory(dir=versions, prefix='.stage-') as temp:
                    staged = Path(temp)
                    site = staged / 'site'; site.mkdir()
                    for source in sorted((ROOT / 'runtime').glob('*/src/*')):
                        if source.name == '__pycache__':
                            continue
                        destination = site / source.name
                        if destination.exists():
                            raise ValueError('runtime package collision: ' + source.name)
                        if source.is_dir():
                            shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
                        else:
                            shutil.copy2(source, destination)
                    shutil.copytree(ROOT / 'plugins', staged / 'plugins', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
                    shutil.copytree(ROOT / 'deploy',staged / 'deploy',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
                    (staged/'launcher.py').write_bytes(LAUNCHER.encode('utf-8'))
                    atomic(staged/'generation-manifest.json',expected)
                    verify_generation(staged,generation,expected)
                    staged.rename(final)
            verify_generation(final,generation,expected)
            new = {'schema_version': 1, 'active': generation, 'previous': state.get('active') if state.get('active') != generation else state.get('previous')}
            activate(target, new)
            state = new
        elif action == 'rollback':
            if not state.get('previous') or not (target / 'versions' / state['previous']).is_dir():
                raise ValueError('no installed previous generation')
            state = dict(state, active=state['previous'], previous=state['active'])
            activate(target, state)
        elif action == 'uninstall':
            if not state:
                raise ValueError('no active installation')
            verify_generation(target/'versions'/state['active'],state['active'])
            site = target / 'versions' / state['active'] / 'site'
            env = dict(os.environ, PYTHONPATH=str(site), PYTHONNOUSERSITE='1')
            for module, arguments in [('houdini_bridge', [str(target / 'houdini-packages')]), ('nuke_bridge', [str(target / 'nuke'), str(target / 'backups')])]:
                if (site / module).is_dir():
                    subprocess.run([sys.executable, '-s', '-c', 'from ' + module + '.install import uninstall; import sys; uninstall(*sys.argv[1:])', *arguments], env=env, cwd=target, check=True, capture_output=True)
            platform = _platform_support()
            platform.remove_owned_path(active, owned_root=target)
            platform.remove_owned_path(target / 'run_runtime.py', owned_root=target)
            platform.remove_owned_path(target / 'versions', owned_root=target)
            state = {'uninstalled': True}
        elif action != 'status':
            raise ValueError('unknown action')
        elif state.get('active'):
            verify_generation(target/'versions'/state['active'],state['active'])
        return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--target', type=Path)
    parser.add_argument('--action', choices=('install', 'rollback', 'status', 'uninstall'), default='install')
    args = parser.parse_args()
    if args.self_test:
        problems = self_test()
        print('PASS' if not problems else 'FAIL: ' + '; '.join(problems))
        return bool(problems)
    if args.target is None:
        parser.error('--target is required; no default global/user installation')
    print(json.dumps(execute(args.target, args.action), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
