"""Python bootstrap sources for explicitly authorized software host processes."""

from pathlib import Path
import sys

SOFTWARE_PYTHON = Path(getattr(sys, '_base_executable', None) or sys.executable).resolve()

BOOTSTRAP_SETUP = '''import ast,json,os,runpy,sys
from pathlib import Path
runner=Path(sys.argv[1])
tree=ast.parse(runner.read_text(encoding='utf-8'))
libs=next((ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='ADDON_LIBS' for target in node.targets)),None)
if libs is not None:
    addon_root=Path(libs).parent
    snapshot=addon_root.parent.parent
else:
    if '--job-file' in sys.argv:
        job=json.loads(Path(sys.argv[sys.argv.index('--job-file')+1]).read_text(encoding='utf-8'))
    else:
        job=json.loads(sys.argv[sys.argv.index('--job')+1])
    snapshot=Path(job['repo_root'])
    addon_root=snapshot/'plugins/houdini'
addon_source=addon_root/'_impl/houdini_bridge_addon.py'
os.environ.setdefault('HOUDINI_BRIDGE_STATE_DIR',str(runner.parent/'fake-native-state/bridge-instances'))
os.environ.setdefault('BRIDGE_SKILLS_STATE_ROOT',str(runner.parent/'fake-native-state/runtime-state'))
if not snapshot.is_absolute() or not addon_source.is_file():
    raise ValueError('software bootstrap requires a formal add-on snapshot')
for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    source=snapshot/'packages'/package/'src'
    if not source.is_dir():raise ValueError('software bootstrap snapshot package missing:'+package)
    sys.path.insert(0,str(source))
from vfx_pipeline.workbuddy_assembly import software_host_client
client,addon=software_host_client(addon_source,runner.parent/'fake-native-state')
sys.modules['houdini_bridge_addon']=addon
'''

BOOTSTRAP_RUN = '''pref=os.environ.get('HOUDINI_USER_PREF_DIR')
if pref:Path(pref).mkdir(parents=True,exist_ok=True)
sys.argv=[str(runner),*sys.argv[2:]]
runpy.run_path(str(runner),run_name='__main__')
'''

HYTHON = BOOTSTRAP_SETUP + BOOTSTRAP_RUN

LIFECYCLE_BOOTSTRAP = BOOTSTRAP_SETUP + '''import time
scenario=os.environ.get('FAKE_HOST_SCENARIO','ok')
call=next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='task_host_serve')
params={keyword.arg:ast.literal_eval(keyword.value) for keyword in call.keywords}
if scenario=='ignore_stop':
    params.update(stop_file=None,max_seconds=120)
    addon.task_host_serve(**params)
    sys.exit(0)
if scenario=='exit':
    print('fixture startup failure',file=sys.stderr)
    sys.exit(7)
if scenario=='hang':
    time.sleep(120)
    sys.exit(0)
if scenario in ('wrong_nonce','dead_pid','bad_protocol'):
    payload={'task_id':params['task_id'],'pid':os.getpid(),'port':18421,
        'protocol_version':'task-host/1.0','addon_sha256':'a'*64,
        'launch_nonce':params['launch_nonce']}
    if scenario=='wrong_nonce':payload['launch_nonce']='not-my-nonce'
    if scenario=='dead_pid':payload['pid']=999999
    if scenario=='bad_protocol':payload['protocol_version']='task-host/0.9'
    Path(params['ready_file']).write_text(json.dumps(payload),encoding='utf-8')
    while scenario=='wrong_nonce' or not Path(params['stop_file']).exists():
        time.sleep(.05)
    sys.exit(0)
''' + BOOTSTRAP_RUN
