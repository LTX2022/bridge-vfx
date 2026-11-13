"""Fixed task-owned headless Nuke control host, native calls on script main thread."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import sys
import threading


def _root_ocio(nuke, record, colorspace, *, configure):
    """Persist the frozen project's actual OCIO configuration in the NK Root."""
    path = Path(record['path'])
    if (not path.is_absolute() or path != path.resolve() or path.is_symlink()
            or not path.is_file() or not 0 < record['bytes'] <= 1024 * 1024):
        raise ValueError('NUKE_PROJECT_COLOR_CONFIG_INVALID')
    with path.open('rb') as stream:
        content = stream.read(record['bytes'] + 1)
    if len(content) != record['bytes'] or hashlib.sha256(content).hexdigest() != record['sha256']:
        raise ValueError('NUKE_PROJECT_COLOR_CONFIG_CHANGED')
    root = nuke.root()
    expected = {'colorManagement': 'OCIO', 'OCIO_config': 'custom',
                'customOCIOConfigPath': str(path), 'workingSpaceLUT': colorspace}
    for name, value in expected.items():
        knob = root.knob(name)
        if knob is None:
            raise ValueError('NUKE_PROJECT_COLOR_KNOB_MISSING: ' + name)
        # LUT knob UI entries are not the canonical OCIO space catalog.
        # Check Nuke's parsed current config rather than an appended string.
        if name != 'customOCIOConfigPath':
            available = nuke.getOcioColorSpaces() if name == 'workingSpaceLUT' else knob.values()
            if (type(available) not in (list, tuple) or len(available) > 4096
                    or any(type(item) is not str or len(item) > 4096 for item in available)):
                raise ValueError('NUKE_PROJECT_COLOR_CATALOG_INVALID: ' + name)
            if name == 'workingSpaceLUT':
                # Nuke 17 encodes canonical name, menu path and aliases as
                # tab-separated fields. Labels and aliases do not grant a space.
                available = [item.split('\t', 1)[0] for item in available]
            if value not in available:
                observed = [str(item)[:80] for item in list(available)[:16]]
                raise ValueError('NUKE_PROJECT_COLOR_MENU_UNAVAILABLE: ' + name + ': ' + repr(observed))
        if configure:
            knob.setValue(value)
        if knob.value() != value:
            raise ValueError('NUKE_PROJECT_COLOR_READBACK_MISMATCH: ' + name)
    return expected


def _controlled_root_color(nuke, config, *, configure):
    binding = (config.get('resource_budget') or {}).get('native_scope')
    if binding is None or config.get('software_api') is True:
        return None
    from dcc_task_runtime.native_scope import NativeScope
    scope = NativeScope(binding)
    if scope.scope.get('evidence_source', 'real_host') != 'real_host':
        raise ValueError('NUKE_PROJECT_COLOR_SOURCE_MISMATCH')
    return _root_ocio(nuke, scope.scope['native_color_tokens']['houdini_static_config'],
                      scope.scope['project_color']['colorspace'], configure=configure)


def run(config_path):
    config=json.loads(Path(config_path).read_text())
    import nuke
    plugin=Path(config['addon_path'])
    digest=hashlib.sha256(plugin.read_bytes()).hexdigest()
    if digest != config['identity']['plugin_build']: raise ValueError('plugin build changed')
    spec=importlib.util.spec_from_file_location('nuke_bridge_addon',plugin)
    addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
    pending=queue.Queue()
    # _run_main owns the timeout/cancellation fence; callbacks are queued, and
    # only this script's main thread invokes them. No GUI event loop is needed.
    addon._TASK_HOST_EXECUTOR=pending.put
    if config.get('snapshot'):
        nuke.scriptOpen(config['snapshot'])
    else:
        nuke.scriptClear()
    _controlled_root_color(nuke, config, configure=not bool(config.get('snapshot')))
    for name,kind in [('Read1','Read'),('Write1','Write')]:
        node=nuke.toNode(name)
        if node is None:
            node=nuke.createNode(kind,inpanel=False);node.setName(name)
        if node.Class()!=kind: raise ValueError('task node has wrong class: '+name)
    identity=dict(config['identity'],pid=os.getpid(),scene_epoch=1,version=str(nuke.NUKE_VERSION_STRING))
    addon._TASK_HOST_IDENTITY=identity
    addon._TASK_HOST_ROOT=Path(config['task_root']).resolve()
    from nuke_bridge.task_host import controlled_artifact_registry
    registry=controlled_artifact_registry(fallback=addon._nuke_operation_fact,
        registry_root=os.environ.get('BRIDGE_ARTIFACT_LEDGER_ROOT'),task_id=identity['task_id'])
    if registry is not None:
        addon._NUKE_ARTIFACT_REGISTRY=registry
    def scene_changed(): identity['scene_epoch']+=1
    nuke.addOnScriptLoad(scene_changed)
    nuke.addOnScriptClose(scene_changed)
    addon.configure_nuke_background_route(nuke_executable=config['nuke_executable'],
        worker_script=config['render_worker'],software_api=config['software_api'],
        supervisor_executable=config['supervisor_executable'],resource_budget=config.get('resource_budget'))
    server=addon.NukeBridgeServer(token=config['token']);server.session_id=identity['session_id'];addon._SERVER=server
    port=server.start()
    from dcc_task_runtime.platform_support import atomic_write
    ready=Path(config['ready'])
    atomic_write(ready,json.dumps({'port':port,'task_host_identity':identity,'evidence_source':config['evidence_source']})
                 .encode('utf-8'),owned_root=ready.parent)
    try:
        while True:
            stop_path = config.get('stop_request')
            if stop_path is not None:
                stop_path = Path(stop_path)
                if stop_path != Path(config_path).resolve().parent/'stop-request.json' or stop_path.is_symlink():
                    raise ValueError('TASK_HOST_STOP_PATH_INVALID')
                if stop_path.exists():
                    request = json.loads(stop_path.read_text())
                    if request != {'schema':'bridge.nuke.task-host-stop/1', 'identity':config['identity']}:
                        raise ValueError('TASK_HOST_STOP_IDENTITY_MISMATCH')
                    break
            try: callback=pending.get(timeout=.1)
            except queue.Empty: continue
            try: callback()
            except BaseException:
                # _run_main captures callback failures and returns them over
                # TCP. Keep this main loop available for the next request.
                pass
    finally: server.stop()

if __name__=='__main__':
    try: run(sys.argv[1])
    except BaseException:
        import traceback
        Path(sys.argv[1]).with_name('worker-error.log').write_text(traceback.format_exc())
        raise
