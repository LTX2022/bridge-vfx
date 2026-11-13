#!/usr/bin/env python3
"""Verify the three release Skills in an isolated temporary user directory.

The verifier performs clean ZIP extraction, bundled self-tests,
the shipped Houdini/Nuke installer functions,
active-version update, pointer rollback, and scoped uninstall.  It never
touches the caller's home directory or a real DCC preference directory.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import runpy
import json
import os
import shutil
import queue
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parent))
from readiness_evidence import build_id


def _safe_member(name: str) -> None:
    if not name or "\\" in name or ":" in name:
        raise ValueError("unsafe ZIP member: {}".format(name))
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError("unsafe ZIP member: {}".format(name))
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{index}' for index in range(1, 10)),
                *(f'lpt{index}' for index in range(1, 10))}
    if any(part.endswith((' ', '.')) or part.split('.')[0].casefold() in reserved
           or any(character in '<>"|?*' or ord(character) < 32 for character in part)
           for part in path.parts):
        raise ValueError("unsafe Windows ZIP member: {}".format(name))


def _extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(archive, "r") as package:
        infos = package.infolist()
        for info in infos:
            _safe_member(info.filename.rstrip("/") if info.filename.endswith("/") else info.filename)
            identity = info.filename.rstrip("/").casefold()
            if identity in seen:
                raise ValueError("duplicate ZIP member: {}".format(info.filename))
            seen.add(identity)
            mode = (int(info.external_attr) >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise ValueError("ZIP symlink is not allowed: {}".format(info.filename))
        package.extractall(destination)
    roots = sorted(path for path in destination.iterdir() if path.is_dir())
    if len(roots) != 1:
        raise ValueError("release archive must contain exactly one top-level directory")
    return roots[0]


def _python() -> str:
    return str(Path(getattr(sys, '_base_executable', None) or sys.executable).resolve())


def _software_environment(user_root: Path) -> dict[str, str]:
    user_root = user_root.resolve()
    home = user_root / 'isolated-home'
    temporary = user_root / 'isolated-temp'
    for directory in (home, temporary, home/'AppData/Roaming', home/'AppData/Local'):
        directory.mkdir(parents=True, exist_ok=True)
    env = {"PATH":os.defpath,"LANG":"C.UTF-8","LC_ALL":"C.UTF-8",
        'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8', 'PYTHONDONTWRITEBYTECODE':'1',
        'PYTHONNOUSERSITE':'1', 'HOME':str(home), 'USERPROFILE':str(home),
        'APPDATA':str(home/'AppData/Roaming'), 'LOCALAPPDATA':str(home/'AppData/Local'),
        'XDG_CONFIG_HOME':str(home/'.config'), 'XDG_CACHE_HOME':str(home/'.cache'),
        'TEMP':str(temporary), 'TMP':str(temporary), 'TMPDIR':str(temporary),
        'HOUDINI_USER_PREF_DIR':str(home/'houdini/__HVER__'),
        'BRIDGE_SKILLS_STATE_ROOT':str(user_root/'bridge-state'),
        'BRIDGE_SKILLS_SCHEDULER_ROOT':str(user_root/'scheduler'),
        'HOUDINI_BRIDGE_STATE_DIR':str(user_root/'houdini-state'),
        'NUKE_BRIDGE_BACKUP_DIR':str(user_root/'nuke-backups')}
    for key in ("SYSTEMROOT","WINDIR"):
        if key in os.environ:
            env[key]=os.environ[key]
    return env


def _invoke(root: Path, target: Path, action: str) -> dict[str, Any]:
    command = [_python(), "-I", "-X", "utf8", str(root / "scripts/install_runtime.py"), "--target", str(target), "--action", action]
    env = _software_environment(target.parent)
    completed = subprocess.run(command, cwd=target.parent, env=env, capture_output=True,
                               text=True, encoding='utf-8', errors='strict', timeout=120)
    with (target.parent/'installer-events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'action':action, 'command':command, 'returncode':completed.returncode,
                                 'stdout':completed.stdout, 'stderr':completed.stderr}, ensure_ascii=False)+'\n')
    if completed.returncode:
        raise RuntimeError("installer failed: " + completed.stderr)
    return json.loads(completed.stdout)


def _probe(target: Path) -> dict[str, Any]:
    result = subprocess.run([_python(), "-I", "-X", "utf8", str(target / "run_runtime.py"), "--probe"],
                            cwd=target, env=_software_environment(target.parent), capture_output=True,
                            text=True, encoding='utf-8', errors='strict', check=True, timeout=30)
    probe = json.loads(result.stdout)
    module = Path(probe['module']).resolve()
    if not module.is_relative_to((target/'versions'/probe['generation']/'site').resolve()):
        raise RuntimeError('probe dependency escaped installed generation')
    if hashlib.sha256(module.read_bytes()).hexdigest() != probe['sha256']:
        raise RuntimeError('probe module digest differs from installed bytes')
    return probe


def _registrations(target: Path, generation: str, root: Path) -> dict[str, bool]:
    checks = {}
    if (root / "plugins/houdini").is_dir():
        actual = json.loads((target / "houdini-packages/houdini_bridge.json").read_text(encoding='utf-8'))
        expected = target / "versions" / generation / "deploy/plugins/houdini"
        checks["houdini"] = Path(actual["path"]).resolve() == expected.resolve()
    if (root / "plugins/nuke").is_dir():
        import ast
        code = (target / "nuke/init.py").read_text(encoding='utf-8')
        values = [ast.literal_eval(node.value) for node in ast.parse(code).body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_nuke_bridge_root" for t in node.targets)]
        checks["nuke"] = len(values) == 1 and Path(values[0]).resolve() == (target / "versions" / generation / "deploy/plugins/nuke").resolve()
    return checks


def _installed_paths(deployment: Path, snapshot: Path | None = None) -> dict[str, str]:
    paths = {}
    for name, module in sorted(sys.modules.items()):
        if name.split('.')[0] not in {'dcc_task_runtime', 'houdini_bridge', 'nuke_bridge', 'vfx_pipeline',
                                       'prepare_workbuddy_graph', 'prepare_workbuddy', 'native_schema_test_boundary',
                                       'readiness_evidence', 'verify_skill_lifecycle', 'houdini_bridge_addon',
                                       'nuke_bridge_addon'} and not name.startswith('_bridge_graph_job_addon_'):
            continue
        source = getattr(module, '__file__', None)
        if source:
            actual = Path(source).resolve()
            allowed = (deployment/'packages', deployment/'tools', deployment/'plugins', deployment.parent/'site')
            if snapshot is not None:
                allowed += (snapshot/'packages', snapshot/'tools', snapshot/'plugins')
            if not any(actual.is_relative_to(directory.resolve()) for directory in allowed):
                raise RuntimeError('runtime dependency escaped installed generation: '+name)
            paths[name] = str(actual)
    return paths


_NUKE_API = '''import threading
from pathlib import Path
NUKE_VERSION_STRING = "17.0v1"
GUI = False
_nodes = {}
_callbacks = []
_main_thread = threading.get_ident()
_root_path = ""
def _assert_main():
    if threading.get_ident() != _main_thread:
        raise RuntimeError("native API called off main thread")
class Knob:
    def __init__(self, value=None): self._value = value
    def value(self): _assert_main(); return self._value
    def setValue(self, value): _assert_main(); self._value = value
class Node:
    def __init__(self, kind, name=None):
        _assert_main()
        self.kind = kind
        self.label = name or kind + "1"
        self._knobs = {"file":Knob(""), "colorspace":Knob("linear")}
        self._inputs = []
        _nodes[self.label] = self
    def setName(self, name):
        _assert_main(); _nodes.pop(self.label); self.label = name; _nodes[name] = self
    def name(self): _assert_main(); return self.label
    def Class(self): _assert_main(); return self.kind
    def knobs(self): _assert_main(); return dict(self._knobs)
    def knob(self, name): _assert_main(); return self._knobs.get(name)
    def __getitem__(self, name): _assert_main(); return self._knobs.setdefault(name, Knob())
    def inputs(self): _assert_main(); return len(self._inputs)
    def input(self, index): _assert_main(); return self._inputs[index] if index < len(self._inputs) else None
    def setInput(self, index, node):
        _assert_main()
        while len(self._inputs) <= index: self._inputs.append(None)
        self._inputs[index] = node
    def xpos(self): _assert_main(); return 0
    def ypos(self): _assert_main(); return 0
class _Root:
    def __init__(self): self._knobs = {"name":Knob("")}
    def name(self): _assert_main(); return _root_path
    def __getitem__(self, name): _assert_main(); return self._knobs.setdefault(name, Knob())
    def knobs(self): _assert_main(); return dict(self._knobs)
_root = _Root()
def root(): _assert_main(); return _root
def modified(): _assert_main(); return False
def scriptClear(): _assert_main(); _nodes.clear()
def addOnScriptLoad(callback): _assert_main(); _callbacks.append(callback)
def addOnScriptClose(callback): _assert_main(); _callbacks.append(callback)
def toNode(name): _assert_main(); return _nodes.get(name)
def createNode(kind, inpanel=False): _assert_main(); return Node(kind)
def allNodes(recurseGroups=False): _assert_main(); return list(_nodes.values())
def delete(node): _assert_main(); _nodes.pop(node.name(), None)
def executeInMainThreadWithResult(callback):
    raise RuntimeError("GUI dispatch is outside the headless API boundary")
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bootstrap_source(binding: dict[str, Any]) -> str:
    return ('import hashlib,runpy,sys\nfrom pathlib import Path\n'
        'binding='+repr(json.dumps(binding, sort_keys=True))+'\n'
        'verifier=Path('+repr(binding['verifier'])+')\n'
        'if verifier.is_symlink() or hashlib.sha256(verifier.read_bytes()).hexdigest()!='
        +repr(binding['verifier_sha256'])+': raise RuntimeError("installed verifier changed")\n'
        'sys.argv=[str(verifier),"--closure-worker",binding,*sys.argv[1:]]\n'
        'runpy.run_path(str(verifier),run_name="__main__")\n')


def _check_closure_binding(binding: dict[str, Any]) -> tuple[Path, Path]:
    deployment = Path(__file__).resolve().parents[1]
    verifier = Path(binding['verifier'])
    state = Path(binding['state'])
    control = state/'generated/control'
    snapshot = control/'snapshot'
    target = state.parent
    if (binding.get('scope') != 'software_native_api_only'
            or verifier != Path(__file__).resolve() or _sha256(verifier) != binding['verifier_sha256']
            or state != state.resolve() or state.name != 'closure-evidence'
            or not deployment.is_relative_to((target/'versions').resolve())
            or Path(binding['control']) != control or Path(binding['snapshot']) != snapshot):
        raise RuntimeError('software bootstrap scope escaped installed closure')
    bootstrap = state/'software-bootstrap.py'
    if bootstrap.is_symlink() or bootstrap.read_bytes() != _bootstrap_source(binding).encode('utf-8'):
        raise RuntimeError('software bootstrap bytes changed')
    manifest = control/'snapshot-manifest.json'
    if manifest.is_symlink() or _sha256(manifest) != binding['snapshot_manifest_sha256']:
        raise RuntimeError('generated snapshot manifest changed')
    entries = json.loads(manifest.read_text(encoding='utf-8'))['files']
    if not entries:
        raise RuntimeError('generated snapshot manifest is empty')
    for entry in entries:
        _safe_member(entry['path'])
        path = snapshot/entry['path']
        installed = deployment/entry['path']
        if (path.is_symlink() or not path.resolve().is_relative_to(snapshot.resolve())
                or not installed.is_file() or _sha256(path) != entry['sha256']
                or _sha256(installed) != entry['sha256']):
            raise RuntimeError('generated snapshot differs from installed bytes: '+entry['path'])
    api = state/'native-api/nuke.py'
    if api.is_symlink() or _sha256(api) != binding['nuke_api_sha256']:
        raise RuntimeError('software Nuke API bytes changed')
    return deployment, snapshot


def _closure_runner(worker: Path, arguments: list[str], binding: dict[str, Any]) -> tuple[Path, Path, Path]:
    deployment, snapshot = _check_closure_binding(binding)
    control = Path(binding['control'])
    graph_worker = snapshot/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
    host_runner = control/'houdini-task-host/task_host_runner.py'
    if worker.is_symlink() or worker != worker.resolve():
        raise RuntimeError('software runner must be a regular absolute path')
    if worker == graph_worker:
        if len(arguments) != 2 or arguments[0] != '--job':
            raise RuntimeError('graph worker requires its exact owned job arguments')
        job = json.loads(arguments[1])
        job_root = control/'jobs'
        if (job.get('repo_root') != str(snapshot) or job.get('root') != str(job_root)
                or job.get('validation_scope') != 'software_test'):
            raise RuntimeError('graph worker job escaped installed software scope')
        result = Path(job['result_path'])
        if result.is_symlink() or not result.resolve().is_relative_to(job_root.resolve()):
            raise RuntimeError('graph worker result escaped owned jobs')
        return deployment, snapshot, result.parent
    if worker != host_runner or arguments:
        raise RuntimeError('software runner is not a bundled graph worker or owned host runner')
    from houdini_bridge.task_host import RUNNER_TEMPLATE
    tree = ast.parse(worker.read_text(encoding='utf-8'))
    libraries = next(ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id=='ADDON_LIBS' for target in node.targets))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr=='task_host_serve']
    if len(calls) != 1:
        raise RuntimeError('owned host runner has no exact public host entry')
    parameters = {keyword.arg:ast.literal_eval(keyword.value) for keyword in calls[0].keywords}
    expected = RUNNER_TEMPLATE.format(addon_libs=libraries, **parameters)
    owner = json.loads(os.environ['BRIDGE_OWNED_SUPERVISOR_IDENTITY'])
    if (worker.read_text(encoding='utf-8') != expected
            or Path(libraries) != snapshot/'plugins/houdini/python3.11libs'
            or parameters['stop_file'] != str(host_runner.parent/'host.stop')
            or parameters['ready_file'] != str(host_runner.parent/'host.ready')
            or parameters['warmup'] is not False
            or owner != {'task_id':parameters['task_id'], 'launch_nonce':parameters['launch_nonce']}):
        raise RuntimeError('owned host runner content or supervisor scope changed')
    return deployment, snapshot, worker.parent


def _closure_worker(worker: Path, arguments: list[str], binding: dict[str, Any]) -> int:
    deployment = Path(__file__).resolve().parents[1]
    for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
        sys.path.insert(0,str(deployment/'packages'/package/'src'))
    deployment, snapshot, output = _closure_runner(worker, arguments, binding)
    for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
        sys.path.insert(0,str(snapshot/'packages'/package/'src'))
    from vfx_pipeline.workbuddy_assembly import software_host_client
    from native_schema_test_boundary import constrain_hou
    os.environ['HOUDINI_BRIDGE_STATE_DIR'] = str(output/'software-bridge-state') if arguments else os.environ['HOUDINI_BRIDGE_STATE_DIR']
    preference = Path(os.environ['HOUDINI_USER_PREF_DIR'])
    if not preference.resolve().is_relative_to(Path(binding['state']).parent.resolve()):
        raise RuntimeError('software preference escaped isolated user root')
    preference.mkdir(parents=True,exist_ok=True)
    client, addon = software_host_client(snapshot/'plugins/houdini/_impl/houdini_bridge_addon.py', output/'software-host')
    sys.modules['houdini_bridge_addon'] = addon
    _closure_native_api(deployment)
    sys.argv = [str(worker),*arguments]
    try:
        runpy.run_path(str(worker),run_name='__main__')
    finally:
        (output/'installed-imports.json').write_text(json.dumps(_installed_paths(deployment, snapshot),indent=2)+'\n', encoding='utf-8')
        (output/'runner-evidence.json').write_text(json.dumps({'scope':binding['scope'],
            'runner':str(worker),'runner_sha256':_sha256(worker),'pid':os.getpid(),
            'snapshot_manifest_sha256':binding['snapshot_manifest_sha256'],
            'verifier_sha256':binding['verifier_sha256']},indent=2)+'\n',encoding='utf-8')
    return 0


class _MCPProcess:
    def __init__(self, control: Path, state: Path):
        self.state = state
        self.responses: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.sequence = 0
        self.lines: queue.Queue = queue.Queue()
        self.errors = (state/'generated-server.stderr').open('w', encoding='utf-8')
        self.output = (state/'generated-server.stdout').open('w', encoding='utf-8')
        self.command = [_python(),'-I','-X','utf8',str(control/'server.py'),'--backend','production','--software-processes']
        self.process = subprocess.Popen(self.command, cwd=state, env=_software_environment(state),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, text=True, encoding='utf-8', errors='strict')
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.output.write(line)
                self.output.flush()
                self.lines.put(line)
        except Exception as exc:
            self.lines.put(exc)
        finally:
            self.lines.put(None)

    def rpc(self, method: str, parameters: dict[str, Any], *, notification: bool = False) -> dict[str, Any]:
        self.sequence += 1
        request = {'jsonrpc':'2.0','method':method,'params':parameters}
        if not notification:
            request['id'] = self.sequence
        self.requests.append(request)
        self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        if notification:
            return {}
        deadline = time.monotonic()+35
        while time.monotonic()<deadline:
            try:
                line = self.lines.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty:
                break
            if line is None or isinstance(line, Exception):
                raise RuntimeError('generated server ended or returned invalid UTF-8: '+str(line))
            response = json.loads(line)
            self.responses.append(response)
            if response.get('id')==request['id']:
                if 'error' in response or 'result' not in response:
                    raise RuntimeError('generated server JSON-RPC rejection: '+json.dumps(response))
                return response['result']
        raise RuntimeError('generated server JSON-RPC deadline exceeded: '+method)

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.rpc('tools/call',{'name':name,'arguments':arguments})
        if result.get('isError'):
            raise RuntimeError('generated server tool failed: '+name+' '+json.dumps(result))
        payload = json.loads(result['content'][0]['text'])
        if not isinstance(payload,dict) or payload.get('isError'):
            raise RuntimeError('generated server tool returned invalid evidence: '+name)
        return payload

    def close(self) -> int:
        try:
            self.process.stdin.close()
            try:
                code = self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
                raise RuntimeError('generated server did not exit after EOF')
            if code != 0:
                raise RuntimeError('generated server exited unsuccessfully: '+str(code))
            return code
        finally:
            self.reader.join(timeout=2)
            self.output.close()
            self.errors.close()
            self.process.stdout.close()
            (self.state/'generated-mcp.json').write_text(json.dumps({'command':self.command,
                'requests':self.requests,'responses':self.responses},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def _generated_graph_session(server: _MCPProcess, proposal: dict[str, Any]) -> dict[str, Any]:
    initialized = server.rpc('initialize',{'protocolVersion':'2024-11-05',
        'clientInfo':{'name':'installed-closure','version':'2'},'capabilities':{}})
    server.rpc('notifications/initialized',{},notification=True)
    health = server.tool('health',{})
    catalog = server.tool('catalog',{})
    for index,asset in enumerate(catalog['assets']):
        server.tool('submit_observation',{'asset_id':asset['asset_id'],'request_id':'installed-observation-'+str(index),
            'observation':{'description':'synthetic installation graph fixture','dominant_colors':['grey']}})
    graph = server.tool('graph_propose',{'proposal':proposal,'request_id':'installed-proposal'})
    arguments = {'graph_id':graph['graph_id'],'request_id':'installed-trial'}
    trial = server.tool('graph_trial',arguments)
    operation = trial.get('operation_id')
    if not operation:
        raise RuntimeError('generated graph trial returned no operation')
    deadline = time.monotonic()+55
    while trial.get('state') in {'PREPARED','STARTING','RUNNING'} and time.monotonic()<deadline:
        time.sleep(.2)
        queried = server.tool('graph_status',{'operation_id':operation})
        if queried.get('operation_id')!=operation:
            raise RuntimeError('generated graph status changed operation identity')
        trial = server.tool('graph_trial',arguments)
        if trial.get('operation_id')!=operation:
            raise RuntimeError('generated graph retry changed operation identity')
    if trial.get('state')!='SUCCEEDED' or trial.get('stop_confirmed') is not True:
        raise RuntimeError('generated owned graph trial did not complete: '+json.dumps(trial))
    saved = server.tool('task_save',{})
    if not saved.get('saved_scene_id'):
        raise RuntimeError('generated task_save returned no persistent scene receipt')
    return {'initialize':initialized,'health':health,'graph':graph,'trial':trial,'saved':saved}


def _signed_stop(directory: Path, identity: dict[str, Any], pid: int, *, successful: bool) -> dict[str, Any]:
    from dcc_task_runtime.owned_process import read_receipt, execution_returncode
    started = read_receipt(directory,'started',identity=identity)
    stopped = read_receipt(directory,'stopped',identity=identity)
    if not started or not stopped or started['pid']!=pid or successful and execution_returncode(stopped)!=0:
        raise RuntimeError('owned process has no matching signed stop: '+str(directory))
    return {'identity':identity,'started':started,'stopped':stopped,
        'signature_verified_in_isolated_run':True,'signing_key_retained':False,
        'envelope_sha256':{event:_sha256(directory/(event+'.json')) for event in ('started','stopped')}}


def _graph_completion(control: Path, snapshot: Path, operation: str, scheduler_root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    from vfx_pipeline.graph_job_worker import validate_completion
    from vfx_pipeline.graph_scheduler import GraphScheduler
    job_root = control/'jobs'
    with closing(sqlite3.connect((job_root/'graph_jobs.sqlite3').as_uri()+'?mode=ro',uri=True)) as database:
        database.row_factory = sqlite3.Row
        row = database.execute('SELECT * FROM operations WHERE operation_id=?',(operation,)).fetchone()
        if row is None:
            raise RuntimeError('MCP operation has no generated controller job')
        row = dict(row)
        graph = database.execute('SELECT * FROM graphs WHERE graph_id=?',(row['graph_id'],)).fetchone()
        if graph is None:
            raise RuntimeError('MCP operation has no registered graph')
        graph = dict(graph)
    directory = job_root/'graph-jobs'/operation/('attempt-'+str(row['attempt_generation']))
    paths = {'directory':directory,**{key:directory/name for key,name in {
        'proposal':'proposal.json','graph':'compiled.json','result':'result.json','journal':'journal.sqlite3',
        'lease':'scene_lease.sqlite3','error':'error.txt','inputs':'inputs.json',
        'identity':'worker_identity.json','completion':'completion.json'}.items()}}
    result = validate_completion(root=job_root,repo_root=snapshot,paths=paths,operation=row,
        graph_record=graph,scheduler=GraphScheduler(scheduler_root))
    identity = {'operation_id':operation,'attempt_token':row['process_token'],'generation':row['attempt_generation']}
    stop = _signed_stop(directory/'owned-supervisor',identity,row['pid'],successful=True)
    return result, stop, directory


def _closure_native_api(deployment: Path) -> None:
    from native_schema_test_boundary import constrain_hou
    constrain_hou(deployment/'docs/native-basis/hda-interface-capture.json',
                  supplement_path=deployment/'docs/native-basis/native-boundary-metadata-supplement.json',
                  instance_states={'Sop/box': {name: {'origin': 'test_injected_native_api', 'value': 1.0,
                                                    'disabled': False, 'locked': False}
                                  for name in ('scale', 'sizex', 'sizey', 'sizez')}})


def _closure_459_static_api(deployment: Path, state: Path):
    """Read installed459 originals through a separate bottom HOM API object."""
    from vfx_pipeline.workbuddy_assembly import software_host_client
    from native_schema_test_boundary import capture_catalog, constrain_hou
    previous = sys.modules.get('hou')
    try:
        client, addon = software_host_client(
            deployment/'plugins/houdini/_impl/houdini_bridge_addon.py', state/'software-459-api')
        api = sys.modules['hou']
        if api is previous:
            raise RuntimeError('459 closure reused an existing software API object')
        api.applicationVersionString = lambda: '22.0.459'
        schema = deployment/'docs/native-basis/hda-interface-capture.json'
        constrain_hou(schema, version='22.0.459')
        catalog = capture_catalog(schema, version='22.0.459')
        checks = {'exact_459_api_version':api.applicationVersionString()=='22.0.459',
            'separate_software_api':api is not previous,
            'exact_55_original_hda_sections':len(catalog)==55,
            'captured_wrangle_present':('Sop','attribwrangle') in catalog,
            'compiled_object_not_invented':('Obj','geo') not in catalog,
            'compiled_driver_not_invented':('Driver','usdrender') not in catalog}
        return ({'scope':'software_static_459_only','native_host_started':False,
            'deployment_root':str(deployment),'schema_sha256':_sha256(schema.with_name('hda-interface-22.0.459.json')),
            'operators':sorted('/'.join(key) for key in catalog),
            'checks':checks,'passed':all(checks.values())}, api)
    finally:
        if previous is None:
            sys.modules.pop('hou', None)
        else:
            sys.modules['hou'] = previous


def _installed_closure(target: Path) -> dict[str, Any]:
    deployment = Path(__file__).resolve().parents[1]
    if not deployment.is_relative_to((target/'versions').resolve()):
        raise RuntimeError('closure verifier must be invoked through the installed launcher')
    from prepare_workbuddy_graph import prepare_graph
    from vfx_pipeline.production_hosts import stop_hosts
    from vfx_pipeline.workbuddy_assembly import software_host_client
    from native_schema_test_boundary import constrain_hou
    state = target/'closure-evidence'
    state.mkdir()
    static_459, api_459 = _closure_459_static_api(deployment, state)
    control = state/'generated/control'
    snapshot = control/'snapshot'
    scheduler = state/'generated-scheduler'
    api = state/'native-api'
    api.mkdir()
    (api/'nuke.py').write_text(_NUKE_API,encoding='utf-8')
    bootstrap = state/'software-bootstrap.py'
    bootstrap.write_text('',encoding='utf-8')
    common = {'lifecycle':'task_owned','executable':_python(),'supervisor_executable':_python(),
        'task_root':str(state),'resource_budget':{'roots':[str(state)],'max_bytes':512*1024*1024},
        'session_seconds':120,'evidence_source':'software_test'}
    prepared = prepare_graph(state/'generated',app=None,execution_profile=True,scheduler_root=scheduler,
        production_host_config={**common,'application':'houdini','version':'21.0.631','software_launch_script':str(bootstrap)},
        production_nuke_config={**common,'application':'nuke','version':'17.0v1','software_api_dir':str(api)})
    binding = {'scope':'software_native_api_only','verifier':str(Path(__file__).resolve()),
        'verifier_sha256':_sha256(Path(__file__)),'state':str(state),'control':str(control),'snapshot':str(snapshot),
        'snapshot_manifest_sha256':_sha256(control/'snapshot-manifest.json'),'nuke_api_sha256':_sha256(api/'nuke.py')}
    bootstrap.write_bytes(_bootstrap_source(binding).encode('utf-8'))
    bootstrap_sha = _sha256(bootstrap)
    manifest_path = control/'run.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['production_host']['software_launch_script_sha256'] = bootstrap_sha
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    _check_closure_binding(binding)
    proposal = {'schema_version':'1.0','nodes':[
        {'node_id':'geo','node_type':'obj.geometry','context':'houdini_obj'},
        {'node_id':'box','node_type':'sop.box','context':'houdini_sop','subnet_path':['geo']},
        {'node_id':'rasterize','node_type':'sop.rasterize','context':'houdini_sop','subnet_path':['geo'],
         'parameters':{'voxelsize':0.25,'attributes':'density temperature v'}}],
        'connections':[{'source_node':'houdini_sop:/geo/box','source_port':'geometry',
          'target_node':'houdini_sop:/geo/rasterize','target_port':'geometry'}],
        'outputs':[{'output_id':'volume','node_id':'houdini_sop:/geo/rasterize','port':'volume'}]}
    server = None
    session = None
    stop_results = {}
    exit_code = None
    try:
        server = _MCPProcess(prepared['control'],state)
        session = _generated_graph_session(server,proposal)
    finally:
        try:
            if server is not None:
                exit_code = server.close()
        finally:
            if (control/'production-hosts.json').is_file():
                stop_results = stop_hosts(control)
                (state/'hosts-stop.json').write_text(json.dumps(stop_results,indent=2)+'\n',encoding='utf-8')
    if not session or exit_code != 0 or set(stop_results)!={'houdini','nuke'}:
        raise RuntimeError('generated server or both owned hosts did not finish')
    hosts = json.loads((control/'production-hosts.json').read_text(encoding='utf-8'))['hosts']
    host_stops = {}
    for kind,host in hosts.items():
        if kind=='houdini':
            owner = json.loads((Path(host['work_dir'])/'supervisor-binding.json').read_text(encoding='utf-8'))
            if stop_results[kind].get('returncode')!=0 or stop_results[kind]['receipt'].get('confirmed_exit') is not True:
                raise RuntimeError('Houdini software host did not stop cleanly')
        else:
            owner = {'directory':host['supervisor_dir'],'identity':host['supervisor_identity']}
            if stop_results[kind].get('stopped') is not True:
                raise RuntimeError('Nuke software host stop is unconfirmed')
        host_stops[kind] = _signed_stop(Path(owner['directory']),owner['identity'],host['expected_identity']['pid'],successful=kind=='houdini')
    operation = session['trial']['operation_id']
    result, stop_evidence, directory = _graph_completion(control,snapshot,operation,scheduler)
    verification = result['verification']
    worker_hip = Path(verification['hip_path'])
    saved = session['saved']
    hip = Path(saved['path'])
    if not hip.resolve().is_relative_to(state.resolve()) or hip.is_symlink() or _sha256(hip)!=saved['sha256']:
        raise RuntimeError('generated task_save HIP bytes changed or escaped task root')
    os.environ['HOUDINI_BRIDGE_STATE_DIR']=str(state/'fresh-bridge-state')
    client, addon = software_host_client(deployment/'plugins/houdini/_impl/houdini_bridge_addon.py',state/'fresh-host')
    api_21 = sys.modules.get('hou')
    _closure_native_api(deployment)
    reopened = client.call('scene.open_hip',{'path':str(hip),'sha256':saved['sha256']})
    topology = result['topology']['nodes']
    expected_types = {'houdini_obj:/geo':'Obj/geo','houdini_sop:/geo/box':'Sop/box',
                      'houdini_sop:/geo/rasterize':'Sop/volumerasterizeattributes'}
    infos = {address:client.call('node.info',{'path':path}) for address,path in topology.items()}
    parameters = client.call('node.parms',{'path':topology['houdini_sop:/geo/rasterize']})['parms']
    worker_imports = json.loads((directory/'installed-imports.json').read_text(encoding='utf-8'))
    host_imports = json.loads((control/'houdini-task-host/installed-imports.json').read_text(encoding='utf-8'))
    worker_runner = json.loads((directory/'runner-evidence.json').read_text(encoding='utf-8'))
    host_runner = json.loads((control/'houdini-task-host/runner-evidence.json').read_text(encoding='utf-8'))
    _check_closure_binding(binding)
    requests = server.requests
    trials = [request['params']['arguments'] for request in requests
              if request['method']=='tools/call' and request['params']['name']=='graph_trial']
    worker_argv = [_python(),str(bootstrap),str(snapshot/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'),
                   '--job',None]
    inputs = json.loads((directory/'inputs.json').read_text(encoding='utf-8'))
    launch = json.loads((directory/'owned-supervisor/intent.json').read_text(encoding='utf-8'))
    checks = {'installed_459_static_resources_verified':static_459['passed'],
        'fresh_21_and_459_api_objects_separate':api_21 is not None and api_21 is not api_459
            and type(api_21.node('/obj')) is not type(api_459.node('/obj')),
        'generated_server_started':bool(session['initialize']) and exit_code==0,
        'generated_server_dispatched_owned_worker':bool(trials) and all(arguments==trials[0] for arguments in trials)
            and inputs['software_launch_script']==str(bootstrap) and inputs['software_launch_script_sha256']==bootstrap_sha
            and launch['command'][:4]==worker_argv[:4] and len(launch['command'])==5
            and json.loads(launch['command'][4])['operation_id']==operation
            and stop_evidence['started']['argv_sha256']==hashlib.sha256(json.dumps(launch['command'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest(),
        'default_owned_worker_completed':session['trial']['state']=='SUCCEEDED' and session['trial']['stop_confirmed'] is True,
        'signed_owned_worker_stop_verified':stop_evidence['signature_verified_in_isolated_run'],
        'both_owned_hosts_stopped':set(host_stops)=={'houdini','nuke'} and all(item['signature_verified_in_isolated_run'] for item in host_stops.values()),
        'task_save_verified':bool(saved['saved_scene_id']) and _sha256(hip)==saved['sha256'],
        'fresh_host_loaded_saved_bytes':str(reopened.get('path'))==str(hip),
        'fresh_readback_process_differs_from_worker':os.getpid()!=stop_evidence['started']['pid']
            and all(os.getpid()!=host['expected_identity']['pid'] for host in hosts.values()),
        'fresh_readback_preserved_hip_sha256':_sha256(hip)==saved['sha256'] and _sha256(worker_hip)==verification['hip_sha256'],
        'nodes_verified':all(infos[address]['type']==native for address,native in expected_types.items()),
        'parameters_verified':all(parameters[key]==value for key,value in proposal['nodes'][2]['parameters'].items()),
        'connections_verified':infos['houdini_sop:/geo/rasterize']['inputs']==[topology['houdini_sop:/geo/box']],
        'worker_imports_installed':bool(worker_imports) and all(Path(path).is_relative_to(deployment) or Path(path).is_relative_to(snapshot) for path in worker_imports.values()),
        'host_imports_installed':bool(host_imports) and all(Path(path).is_relative_to(deployment) or Path(path).is_relative_to(snapshot) for path in host_imports.values()),
        'runner_paths_and_hashes_verified':all(record['scope']==binding['scope']
            and record['snapshot_manifest_sha256']==binding['snapshot_manifest_sha256']
            and record['verifier_sha256']==binding['verifier_sha256']
            and record['runner']==str(path) and record['runner_sha256']==_sha256(path)
            and record['pid']==pid for record,path,pid in (
                (worker_runner,snapshot/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py',stop_evidence['started']['pid']),
                (host_runner,control/'houdini-task-host/task_host_runner.py',hosts['houdini']['expected_identity']['pid']))),
        'result_verified':all(verification.get(key) is True for key in ('nodes_verified','parameters_verified','connections_verified'))}
    return {'scope':'software_native_api_only','native_host_started':False,'deployment_root':str(deployment),
        'static_459_closure':static_459,
        'software_launch':{'executable':_python(),'script':str(bootstrap),'sha256':bootstrap_sha},
        'generated_server':{'command':server.command,'exit_code':exit_code},
        'operation_id':operation,'graph_id':session['graph']['graph_id'],'status':session['trial'],'artifact':verification,
        'task_save':saved,'signed_stop':stop_evidence,'host_signed_stops':host_stops,
        'fresh_readback':{'nodes':infos,'parameters':parameters},'generated_session':session,
        'generated_responses':server.responses,'import_paths':_installed_paths(deployment),
        'worker_import_paths':worker_imports,'host_import_paths':host_imports,
        'runner_evidence':{'worker':worker_runner,'host':host_runner},'sys_path':list(sys.path),
        'checks':checks,'passed':all(checks.values()),'blockers':[name for name,passed in checks.items() if not passed]}


def _verify_installed_closure(target: Path) -> dict[str, Any]:
    output = target/'installed-closure.json'
    result = subprocess.run([_python(),'-I','-X','utf8',str(target/'run_runtime.py'),'--tool','verify_skill_lifecycle.py',
        '--installed-closure',str(target),'--output',str(output)],cwd=target,
        env=_software_environment(target.parent),
        capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=180)
    (target/'installed-closure.stdout').write_text(result.stdout, encoding='utf-8')
    (target/'installed-closure.stderr').write_text(result.stderr, encoding='utf-8')
    payload = json.loads(output.read_text(encoding='utf-8')) if output.is_file() else None
    if (result.returncode not in (0, 1) or not isinstance(payload, dict)
            or type(payload.get('passed')) is not bool or not payload.get('checks')
            or payload['passed'] != all(value is True for value in payload['checks'].values())
            or result.returncode != int(not payload['passed'])):
        details=result.stderr
        if output.is_file():
            details += json.dumps(payload.get('checks',{}) if isinstance(payload, dict) else {},sort_keys=True)
        raise RuntimeError('installed closure failed: '+details)
    return payload


def _retain_evidence(user_root: Path, retained: Path) -> list[dict[str, Any]]:
    from dcc_task_runtime.platform_support import atomic_write

    retained.mkdir(parents=True, exist_ok=True)

    def copy_bytes(source, destination):
        source = Path(source)
        if source.is_symlink():
            raise ValueError('evidence source must be a regular owned file')
        atomic_write(Path(destination), source.read_bytes(), owned_root=retained)
        return destination

    target = user_root/'installed'
    if (target/'closure-evidence').is_dir():
        shutil.copytree(target/'closure-evidence', retained/'closure-evidence', dirs_exist_ok=True,
                        copy_function=copy_bytes,
                        ignore=shutil.ignore_patterns('*.key', '*.token', '*secret*', '__pycache__', '*.pyc',
                                                     'production-hosts.json', 'launch.json', 'host.json'))
    for source in [user_root/'installer-events.jsonl',
                   *(target/name for name in ('installed-closure.json','installed-closure.stdout','installed-closure.stderr'))]:
        if source.is_file():
            copy_bytes(source, retained/source.name)
    entries = [{'path':path.relative_to(retained).as_posix(), 'bytes':path.stat().st_size,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in sorted(retained.rglob('*')) if path.is_file() and path.name!='evidence-sha256.json']
    (retained/'evidence-sha256.json').write_text(json.dumps(entries,indent=2)+'\n', encoding='utf-8')
    return entries


@contextmanager
def _lifecycle_workspace(parent: Path):
    temporary = Path(tempfile.mkdtemp(prefix='中文 空格 bridge-skill-lifecycle-',dir=parent)).resolve()
    if not temporary.is_relative_to(parent.resolve()):
        raise RuntimeError('isolated workspace escaped output parent')
    try:
        yield temporary
    finally:
        from dcc_task_runtime.owned_process import read_receipt
        confirmed = True
        for intent_path in temporary.rglob('intent.json'):
            try:
                intent = json.loads(intent_path.read_text(encoding='utf-8'))
                confirmed = confirmed and read_receipt(intent_path.parent,'stopped',identity=intent['identity']) is not None
            except (OSError, ValueError, KeyError):
                confirmed = False
        if confirmed:
            from dcc_task_runtime.platform_support import remove_owned_path
            remove_owned_path(temporary, owned_root=parent)


def _verify_current_release_source(root: Path, skill: str, source: Path | None = None) -> dict[str, Any]:
    """Bind the complete declared release layout to current source bytes."""
    from build_release import iter_release_files, locate_package_source
    source = Path(source) if source is not None else Path(__file__).resolve().parents[1]
    layout = json.loads((source/'tools/release_layout.json').read_text(encoding='utf-8'))['skills']
    if skill not in layout:
        raise ValueError('unknown release Skill: '+str(skill))
    config = layout[skill]
    expected = {}

    def include_file(origin, relative):
        if not origin.is_file():
            raise ValueError('current release source is missing: '+str(origin))
        name = relative.as_posix()
        if name in expected:
            raise ValueError('current release layout contains duplicate path: '+name)
        expected[name] = _sha256(origin)

    def include_tree(origin, relative):
        if not origin.is_dir():
            raise ValueError('current release source tree is missing: '+str(origin))
        for path in iter_release_files(origin):
            include_file(path, relative/path.relative_to(origin))

    for relative in config['files']:
        include_file(source/'skills'/skill/relative, Path(relative))
    for name in config['runtime_packages']:
        package = locate_package_source(name, start=source, allow_installed=False).parent
        include_tree(package, Path('runtime')/name)
    for name in config['plugins']:
        include_tree(source/'plugins'/name, Path('plugins')/name)
    for relative in config['deployment_trees']:
        include_tree(source/relative, Path('deploy')/relative)
    for relative in config['deployment_resources']:
        include_file(source/relative, Path('deploy')/relative)
    actual = {path.relative_to(root).as_posix(): _sha256(path) for path in iter_release_files(root)}
    missing = sorted(set(expected)-set(actual))
    unexpected = sorted(set(actual)-set(expected))
    changed = sorted(name for name in set(actual)&set(expected) if actual[name] != expected[name])
    if missing or unexpected or changed:
        raise ValueError('release differs from current source: missing={}, unexpected={}, changed={}'.format(
            missing, unexpected, changed))
    canonical = json.dumps(expected, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'files_verified': len(expected), 'files_sha256': hashlib.sha256(canonical).hexdigest()}


def _artifact_lifecycle(archive: Path, artifact: dict[str, Any], user_root: Path, evidence_root: Path,
                        *, readonly_files: bool = False) -> dict[str, Any]:
    from build_release import validate_packaged_bytes
    if not artifact.get('sha256') or not artifact.get('files') or not artifact.get('file_manifest_sha256'):
        raise ValueError('release ZIP requires archive and member SHA-256 manifests')
    validate_packaged_bytes(archive, artifact)
    root = _extract(archive, user_root / "extracted")
    current_source_binding = _verify_current_release_source(root, artifact['skill'])
    target = user_root / "installed"
    target.mkdir()
    # Existing unrelated plug-in settings must survive all real installer actions.
    (target / "nuke").mkdir()
    other_nuke = "# 其它插件\nOTHER_PLUGIN = '中文 空格 preserved'\n"
    (target / "nuke/init.py").write_bytes(other_nuke.encode('utf-8'))
    (target / "houdini-packages").mkdir()
    other_houdini = b'{"path":"other-plugin","enable":true}\n'
    (target / "houdini-packages/other.json").write_bytes(other_houdini)
    first = _invoke(root, target, "install")
    first_probe = _probe(target)
    first_registration = _registrations(target, first["active"], root)
    try:
        closure = _verify_installed_closure(target)
    finally:
        _retain_evidence(user_root, evidence_root/artifact['skill'])
    # A preceding release fixture changes actual importable module bytes, not a
    # verifier-owned active marker. The shipped installer identifies the build.
    variant = user_root / "release-variant"
    shutil.copytree(root, variant)
    module = variant / "runtime/dcc-task-runtime/src/dcc_task_runtime/__init__.py"
    module.write_bytes(module.read_bytes() + b"\n# lifecycle synthetic release variant\n")
    deployed_module = variant / 'deploy/packages/dcc-task-runtime/src/dcc_task_runtime/__init__.py'
    deployed_module.write_bytes(module.read_bytes())
    if readonly_files:
        for name in ('active.json', 'run_runtime.py', 'nuke/init.py', 'houdini-packages/other.json'):
            (target/name).chmod(stat.S_IREAD)
        for path in (target/'versions').rglob('*'):
            if path.is_file():
                path.chmod(stat.S_IREAD)
    second = _invoke(variant, target, "install")
    second_probe = _probe(target)
    second_registration = _registrations(target, second["active"], root)
    broken = user_root / "broken-release"
    shutil.copytree(variant, broken)
    broken_package = "nuke-bridge" if (broken / "runtime/nuke-bridge").is_dir() else "houdini-bridge"
    broken_module = broken / "runtime" / broken_package / "src" / broken_package.replace("-", "_") / "install.py"
    broken_module.write_text("raise RuntimeError('synthetic registration failure')\n", encoding='utf-8')
    deployed_broken = broken / 'deploy/packages' / broken_package / 'src' / broken_package.replace('-','_') / 'install.py'
    deployed_broken.write_bytes(broken_module.read_bytes())
    try:
        _invoke(broken, target, "install")
        failure_preserved = False
    except RuntimeError:
        failure_preserved = (_probe(target) == second_probe
            and all(_registrations(target, second["active"], root).values()))
    rollback = _invoke(variant, target, "rollback")
    rollback_probe = _probe(target)
    rollback_registration = _registrations(target, rollback["active"], root)
    _invoke(root, target, "uninstall")
    preserved = ((target / "nuke/init.py").read_bytes() == other_nuke.encode()
                 and (target / "houdini-packages/other.json").read_bytes() == other_houdini)
    checks = {
        "installed_dependency_closure": closure["passed"],
        "actual_import_changed": first_probe["sha256"] != second_probe["sha256"],
        "generation_changed": first["active"] != second["active"],
        "failed_upgrade_preserved_active_import_and_registration": failure_preserved,
        "rollback_import_restored": rollback_probe == first_probe,
        "registration_switched": all(first_registration.values()) and all(second_registration.values()) and all(rollback_registration.values()),
        "unrelated_settings_preserved": preserved,
        "uninstalled": not (target / "active.json").exists() and not (target / "versions").exists() and not (target / "run_runtime.py").exists(),
    }
    return {"skill": artifact["skill"], "archive": archive.name, 'archive_sha256':artifact['sha256'],
            'readonly_files':readonly_files, 'current_source_binding':current_source_binding,
            "fixture": "second release differs in actual bundled dcc_task_runtime module bytes",
            "installed_closure": closure, "installed": first_probe, "upgraded": second_probe, "rolled_back": rollback_probe,
            "checks": checks, "passed": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--release-dir", type=Path)
    mode.add_argument("--installed-closure", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--user-root', type=Path, help='empty isolated directory below the output parent')
    parser.add_argument('--readonly-files', action='store_true', help='exercise read-only installed files during upgrade/rollback/uninstall')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('refusing to overwrite existing lifecycle evidence')
    if args.installed_closure:
        payload = _installed_closure(args.installed_closure.resolve())
        args.output.write_text(json.dumps(payload,indent=2)+"\n", encoding='utf-8')
        return 0 if payload["passed"] else 1
    release = args.release_dir.resolve()
    manifest_path = release/'release-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {"houdini-bridge", "nuke-bridge", "vfx-visual-twin"}
    artifacts = manifest.get("artifacts", [])
    if {item.get("skill") for item in artifacts} != expected or len(artifacts) != 3:
        raise ValueError("exactly three Skill artifacts required")
    results = []
    evidence_root = args.output.with_suffix("").with_name(args.output.stem+"-raw")
    if evidence_root.exists():
        raise ValueError('refusing to reuse existing raw lifecycle evidence')
    source_build = build_id(Path(__file__).resolve().parents[1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    user_parent = args.output.parent.resolve()
    if args.user_root:
        user_parent = args.user_root.absolute()
        if (user_parent.is_symlink() or not user_parent.resolve().is_relative_to(args.output.parent.resolve())
                or user_parent.resolve()==args.output.parent.resolve()
                or user_parent.exists() and any(user_parent.iterdir())):
            raise ValueError('user root must be an empty isolated child of the output parent')
        user_parent.mkdir(parents=True, exist_ok=True)
    with _lifecycle_workspace(user_parent) as temporary:
        for artifact in artifacts:
            user_root = Path(temporary)/artifact['skill']
            try:
                _safe_member(artifact['archive'])
                if Path(artifact['archive']).name!=artifact['archive']:
                    raise ValueError('release archive must be a basename')
                results.append(_artifact_lifecycle(release / artifact["archive"], artifact, user_root, evidence_root,
                                                   readonly_files=args.readonly_files))
            except Exception as exc:
                results.append({"skill": artifact["skill"], "passed": False, "error": str(exc)})
            finally:
                results[-1]['evidence_files'] = _retain_evidence(user_root, evidence_root/artifact['skill'])
                for path in user_root.rglob('*'):
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(Path(temporary).resolve()):
                        path.chmod(path.stat().st_mode | stat.S_IWRITE)
    source_unchanged = source_build == build_id(Path(__file__).resolve().parents[1])
    payload = {"schema": "bridge.full_readiness.skill_lifecycle/2.0",
               "source": "software_subprocess", "build_id": source_build, "host_installation_touched": False,
               'source_unchanged':source_unchanged, 'readonly_files':args.readonly_files,
               'release_manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
               'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'signing_keys_retained':False,
               'isolated_state_retained':str(temporary) if temporary.exists() else None,
               "artifacts": results, "passed": source_unchanged and len(results) == 3 and all(item["passed"] for item in results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--closure-worker"]:
        raise SystemExit(_closure_worker(Path(sys.argv[3]),sys.argv[4:],json.loads(sys.argv[2])))
    raise SystemExit(main())
