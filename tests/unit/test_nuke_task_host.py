from __future__ import annotations
import ctypes
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from nuke_bridge import task_host
from nuke_bridge.client import NukeClient
from nuke_bridge import owned_render_worker
from software_host_bootstrap import SOFTWARE_PYTHON
ROOT=Path(__file__).resolve().parents[2]
FAKE='''import json,threading
from pathlib import Path
NUKE_VERSION_STRING="17.0v1"
GUI=False
_nodes={};_callbacks=[];_main=threading.get_ident()
_root_path=""
def _assert():
    if threading.get_ident()!=_main: raise AssertionError("native API called off main thread")
def modified():_assert();return False
def scriptClear(): _assert();_nodes.clear()
def scriptOpen(path):
    global _root_path
    _assert();raw=Path(path).read_text(errors="replace")
    try:payload=json.loads(raw.split("\\n",1)[1]) if raw.startswith("bridge.test_nuke_snapshot/1\\n") else None
    except (ValueError,IndexError):payload=None
    _nodes.clear()
    loaded={}
    if isinstance(payload,dict) and payload.get("schema")=="bridge.test_nuke_snapshot/1":
        for item in payload.get("nodes",[]):
            node=Node(item["class"],item["name"]);loaded[item["name"]]=node
            for name,value in item.get("knobs",{}).items():node.knob(name).setValue(value)
        for item in payload.get("nodes",[]):
            node=loaded[item["name"]]
            for index,source in enumerate(item.get("inputs",[])):
                if source is not None:node.setInput(index,loaded[source])
    _root_path=str(path)
    for c in _callbacks:c()
def scriptSaveAs(path,overwrite=False):
    global _root_path
    _assert();target=Path(path)
    if target.exists() and not overwrite:raise FileExistsError(str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    nodes=[]
    for node in _nodes.values():
        nodes.append({"name":node.name(),"class":node.Class(),
            "knobs":{name:knob.value() for name,knob in node.knobs().items()},
            "inputs":[source.name() if source is not None else None for source in node._inputs]})
    target.write_text("bridge.test_nuke_snapshot/1\\n"+json.dumps({"schema":"bridge.test_nuke_snapshot/1","nodes":nodes},sort_keys=True))
    _root_path=str(target)
def addOnScriptLoad(callback):_callbacks.append(callback)
def addOnScriptClose(callback):pass
def executeInMainThreadWithResult(callback):raise AssertionError("GUI dispatch must not run headless")
def toNode(name):_assert();return _nodes.get(name)
class Knob:
    def __init__(self,value=None):self._value=value
    def value(self):return self._value
    def setValue(self,value):self._value=value
    def setAnimated(self):pass
    def setValueAt(self,value,frame):self._value=value
class Node:
    def __init__(self,kind,name=None):
        self.kind=kind;self.label=name or kind+"1";self._knobs={"file":Knob(""),"colorspace":Knob("linear")};self._inputs=[];_nodes[self.label]=self
    def setName(self,name):_assert();_nodes.pop(self.label);self.label=name;_nodes[name]=self
    def name(self):_assert();return self.label
    def Class(self):_assert();return self.kind
    def knobs(self):_assert();return dict(self._knobs)
    def knob(self,name):_assert();return self._knobs.get(name)
    def __getitem__(self,name):return self._knobs.setdefault(name,Knob())
    def inputs(self):_assert();return len(self._inputs)
    def input(self,index):_assert();return self._inputs[index] if index<len(self._inputs) else None
    def setInput(self,index,node):
        _assert()
        while len(self._inputs)<=index:self._inputs.append(None)
        self._inputs[index]=node
    def xpos(self):return 0
    def ypos(self):return 0
def createNode(kind,inpanel=False):_assert();return Node(kind)
def allNodes(recurseGroups=False):_assert();return list(_nodes.values())
def delete(node):_assert();_nodes.pop(node.name(),None)
class Undo:
    def __init__(self,label):pass
    def __enter__(self):return self
    def __exit__(self,*args):return False
class _Root:
    def __init__(self):self._knobs={"name":Knob(_root_path)}
    def name(self):return _root_path
    def __getitem__(self,name):return self._knobs.setdefault(name,Knob())
    def knobs(self):return self._knobs
def root():_assert();return _Root()
'''

class NukeTaskHostTests(unittest.TestCase):
    def test_ready_deadline_uses_scoped_budget_without_extending_launch_budget(self):
        from dcc_task_runtime.native_scope import NativeScope
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            root=Path(temp)
            for scoped in (False, True):
                with self.subTest(scoped=scoped):
                    handle=mock.Mock();handle.poll.side_effect=RuntimeError('ready loop entered after ten seconds')
                    budget={'native_scope':{'path':'scope','sha256':'f'*64}} if scoped else None
                    with mock.patch.object(NativeScope,'__init__',return_value=None), \
                         mock.patch.object(NativeScope,'validate_host'), \
                         mock.patch.object(NativeScope,'root',root,create=True), \
                         mock.patch.object(task_host.owned_process,'launch',return_value=handle) as launch, \
                         mock.patch.object(task_host,'time',mock.Mock(monotonic=mock.Mock(side_effect=[100.,110.067]))):
                        with self.assertRaisesRegex(RuntimeError,'loop entered' if scoped else 'ready timeout'):
                            task_host.start(task_id='t',task_root=root/str(scoped),nuke_executable=str(SOFTWARE_PYTHON),
                                addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=str(SOFTWARE_PYTHON),
                                budget_seconds=117.,resource_budget=budget,ledger_root=root/'control/artifact_ledger',scheduler_root=root/'scheduler',
                                controller_root=root/'control' if scoped else None)
                    self.assertEqual(launch.call_args.kwargs['budget_seconds'],117.)
                    env=launch.call_args.kwargs['env']
                    self.assertEqual('BRIDGE_NUKE_HOST_CONFIG' in env,scoped)
                    if scoped:
                        path=Path(env['BRIDGE_NUKE_HOST_CONFIG'])
                        import hashlib
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),env['BRIDGE_NUKE_HOST_CONFIG_SHA256'])
                        self.assertEqual(json.loads(path.read_bytes())['controller_root'],str(root/'control'))
                        self.assertIn(str(ROOT/'packages/houdini-bridge/src'),env['PYTHONPATH'].split(os.pathsep))
                        self.assertIn(str(ROOT/'packages/vfx-pipeline/src'),env['PYTHONPATH'].split(os.pathsep))
                    handle.terminate.assert_called_once()
                    handle.wait.assert_called_once_with(timeout=4)

    @unittest.skipUnless(os.name == 'nt', 'Windows ready-file sharing')
    def test_permanent_real_ready_read_denial_stops_owned_host(self):
        import time
        from dcc_task_runtime import owned_process, windows_process
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE,encoding='utf-8')
            actual_read=Path.read_text
            blocking_handles=[]

            def denied_ready_read(path,*args,**kwargs):
                if path.name=='ready.json' and not blocking_handles:
                    handle=windows_process.kernel32.CreateFileW(str(path),0x80000000,0,None,3,0,None)
                    if handle==ctypes.c_void_p(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    blocking_handles.append(handle)
                return actual_read(path,*args,**kwargs)

            started=time.monotonic()
            try:
                with mock.patch.object(Path,'read_text',denied_ready_read):
                    with self.assertRaisesRegex(RuntimeError,'ready unreadable'):
                        task_host.start(task_id='ready-denial',task_root=root/'task',
                            nuke_executable=str(SOFTWARE_PYTHON),addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',
                            supervisor_executable=str(SOFTWARE_PYTHON),software_api=True,software_api_dir=api,budget_seconds=60)
            finally:
                for handle in blocking_handles:
                    windows_process.kernel32.CloseHandle(handle)
            self.assertEqual(len(blocking_handles),1)
            self.assertLess(time.monotonic()-started,16)
            work=list((root/'task').glob('nuke-host-*'))
            self.assertEqual(len(work),1)
            self.assertFalse((work[0]/'host.json').exists())
            intent=json.loads((work[0]/'supervisor/intent.json').read_text(encoding='utf-8'))
            owned=owned_process.OwnedProcessHandle(work[0]/'supervisor',intent['identity'])
            self.assertIsNotNone(owned.poll())
            stopped=owned.receipt()
            self.assertTrue(stopped['child_wait_observed'])
            self.assertEqual(stopped['job_active_processes'],0)

    @unittest.skipUnless(os.name == 'nt', 'Windows ready-file sharing')
    def test_real_ready_read_sharing_violation_retries_same_host(self):
        from dcc_task_runtime import windows_process
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE,encoding='utf-8')
            actual_read=Path.read_text
            errors=[]

            def locked_ready_read(path,*args,**kwargs):
                if path.name=='ready.json' and not errors:
                    handle=windows_process.kernel32.CreateFileW(str(path),0x80000000,0,None,3,0,None)
                    if handle==ctypes.c_void_p(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        return actual_read(path,*args,**kwargs)
                    except PermissionError as exc:
                        errors.append((exc.errno,getattr(exc,'winerror',None)))
                        raise
                    finally:
                        windows_process.kernel32.CloseHandle(handle)
                return actual_read(path,*args,**kwargs)

            with mock.patch.object(Path,'read_text',locked_ready_read):
                receipt=task_host.start(task_id='ready-sharing',task_root=root/'task',
                    nuke_executable=str(SOFTWARE_PYTHON),addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',
                    supervisor_executable=str(SOFTWARE_PYTHON),software_api=True,software_api_dir=api,budget_seconds=20)
            try:
                self.assertEqual(len(errors),1)
                self.assertEqual(errors[0][0],errno.EACCES)
                client=NukeClient(receipt['port'],token=receipt['token'])
                self.assertEqual(client.health()['task_host_identity'],receipt['expected_identity'])
                self.assertEqual(client.call('get_node',{'name':'Read1'})['class'],'Read')
                intent=json.loads((Path(receipt['work_dir'])/'supervisor/intent.json').read_text(encoding='utf-8'))
                self.assertEqual(intent['identity']['launch_nonce'],receipt['expected_identity']['launch_nonce'])
                self.assertEqual(len(list((root/'task').glob('nuke-host-*'))),1)
            finally:
                stopped=task_host.stop(receipt['work_dir'])
            self.assertTrue(stopped['stopped'])

    def test_same_worker_real_tcp_main_thread_identity_reconnect_and_observed_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            receipt=task_host.start(task_id='task-owned',task_root=root/'task',nuke_executable=str(SOFTWARE_PYTHON),
                addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=str(SOFTWARE_PYTHON),
                software_api=True,software_api_dir=api,budget_seconds=20)
            restarted=None
            try:
                client=NukeClient(receipt['port'],token=receipt['token'])
                health=client.health()
                self.assertEqual(health['task_host_identity'],receipt['expected_identity'])
                self.assertEqual(client.call('get_node',{'name':'Read1'})['class'],'Read')
                self.assertEqual(client.call('get_node',{'name':'Write1'})['class'],'Write')
                with self.assertRaisesRegex(Exception,'another task'):
                    client.call('get_node',{'name':'Read1','task_id':'wrong-task'})
                (Path(receipt['work_dir'])/'host.json').unlink()
                self.assertEqual(task_host.reconnect(receipt['work_dir'])['expected_identity'],receipt['expected_identity'])
                foreign=root/'foreign.nk';foreign.write_text('Root {}')
                with self.assertRaisesRegex(Exception,'outside this task root'):
                    client.call('open_script',{'path':str(foreign)})
                snapshot=root/'task/scene.nk';snapshot.write_text('Root {}')
                client.call('set_knob',{'node':'Read1','knob':'file','value':'input.%04d.exr'})
                client.call('set_knob',{'node':'Read1','knob':'colorspace','value':'ACEScg'})
                client.call('set_knob',{'node':'Write1','knob':'file','value':'output.%04d.exr'})
                client.call('connect_nodes',{'src':'Read1','dst':'Write1','input_index':0})
                client.call('save_script',{'path':str(snapshot),'overwrite':True})
                digest=__import__('hashlib').sha256(snapshot.read_bytes()).hexdigest()
                client.call('set_knob',{'node':'Read1','knob':'file','value':'mutated.exr'})
                client.call('open_script',{'path':str(snapshot),'sha256':digest})
                readback=client.call('get_node',{'name':'Read1'})
                writeback=client.call('get_node',{'name':'Write1'})
                self.assertEqual(readback['knobs']['file'],'input.%04d.exr')
                self.assertEqual(readback['knobs']['colorspace'],'ACEScg')
                self.assertEqual(writeback['knobs']['file'],'output.%04d.exr')
                self.assertEqual(writeback['inputs'],['Read1'])
                self.assertEqual(client.health()['task_host_identity']['scene_epoch'],2)
                with self.assertRaisesRegex(ValueError,'scene epoch changed'):
                    task_host.reconnect(receipt['work_dir'])
                first_stop=task_host.stop(receipt['work_dir'])
                self.assertTrue(first_stop['stopped'])
                restarted=task_host.start(task_id='task-owned',task_root=root/'task',
                    nuke_executable=str(SOFTWARE_PYTHON),
                    addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',
                    supervisor_executable=str(SOFTWARE_PYTHON),
                    process_generation=2,snapshot=snapshot,software_api=True,
                    software_api_dir=api,budget_seconds=20)
                restarted_client=NukeClient(restarted['port'],token=restarted['token'])
                restored_read=restarted_client.call('get_node',{'name':'Read1'})
                restored_write=restarted_client.call('get_node',{'name':'Write1'})
                self.assertEqual(restored_read['knobs']['file'],'input.%04d.exr')
                self.assertEqual(restored_read['knobs']['colorspace'],'ACEScg')
                self.assertEqual(restored_write['knobs']['file'],'output.%04d.exr')
                self.assertEqual(restored_write['inputs'],['Read1'])
            finally:
                if restarted is not None:
                    task_host.stop(restarted['work_dir'])
                stopped=task_host.stop(receipt['work_dir'])
            self.assertTrue(stopped['stopped'])
            self.assertEqual(stopped['receipt']['observed_by'],'owned_child_wait')
            self.assertEqual(task_host.owned_process.execution_returncode(stopped['receipt']),0)
            self.assertEqual(stopped['receipt']['pid'],receipt['expected_identity']['pid'])
            with self.assertRaisesRegex(RuntimeError,'stopped'):task_host.reconnect(receipt['work_dir'])

    def test_scoped_host_graceful_stop_has_signed_success_and_rejects_wrong_identity(self):
        import hashlib
        from dcc_task_runtime.native_scope import NativeScope
        from dcc_task_runtime.owned_process import execution_returncode
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();api=root/'api';api.mkdir();(api/'nuke.py').write_text(FAKE)
            binary={'path':str(SOFTWARE_PYTHON),'bytes':SOFTWARE_PYTHON.stat().st_size,
                    'sha256':hashlib.sha256(SOFTWARE_PYTHON.read_bytes()).hexdigest()}
            color={'schema':'bridge.project-color/1.0','project_id':'scope-test','revision':1,
                   'colorspace':'ACEScg','source':'human_project_selection'}
            from test_native_scope import software_scope
            binding=software_scope(root,versions={'houdini':'21.0.631','nuke':'17.0v1'},project_color=color,
                hosts={key:dict(binary) for key in ('hython','nuke','husk','supervisor_python')})
            budget={'roots':[str(root)],'max_bytes':512*1024*1024,'native_scope':binding}
            receipt=task_host.start(task_id='scoped-nuke',task_root=root/'task',nuke_executable=str(SOFTWARE_PYTHON),
                addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=str(SOFTWARE_PYTHON),
                software_api=True,software_api_dir=api,budget_seconds=20,resource_budget=budget,
                ledger_root=root/'ledger',scheduler_root=root/'scheduler',project_color=color)
            stopped=task_host.stop(receipt['work_dir'])
            self.assertTrue(stopped['stopped'])
            self.assertEqual(stopped['status'],'STOP_CONFIRMED')
            self.assertEqual(execution_returncode(stopped['receipt']),0)
            self.assertIsNone(NativeScope(binding).check()['closed_reason'])
            # An unrelated request cannot authorize worker exit as successful.
            # A separate unscoped own-Python host avoids consuming a second
            # Nuke-host role in the frozen eight-start scope.
            foreign=task_host.start(task_id='wrong-stop',task_root=root/'wrong-stop',nuke_executable=str(SOFTWARE_PYTHON),
                addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=str(SOFTWARE_PYTHON),
                software_api=True,software_api_dir=api,budget_seconds=20)
            work=Path(foreign['work_dir'])
            config=json.loads((work/'launch.json').read_text())
            task_host._write(Path(config['stop_request']),{'schema':'bridge.nuke.task-host-stop/1','identity':{}})
            handle=task_host.owned_process.OwnedProcessHandle(work/'supervisor',config['identity'])
            try: self.assertNotEqual(handle.wait(timeout=5),0)
            finally:
                if handle.poll() is None: handle.terminate();handle.wait(timeout=3)

    def test_production_cannot_inject_fake_api_or_foreign_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            config=dict(task_id='t',task_root=Path(temp)/'task',nuke_executable=str(SOFTWARE_PYTHON),addon_path=ROOT/'plugins/nuke/nuke_bridge_addon.py',supervisor_executable=str(SOFTWARE_PYTHON))
            with mock.patch('dcc_task_runtime.owned_process.launch',side_effect=AssertionError('must not launch')):
                with self.assertRaisesRegex(ValueError,'test-only'):task_host.start(**config,software_api_dir=temp)
                foreign=Path(temp)/'foreign.nk';foreign.write_text('Root {}')
                with self.assertRaisesRegex(ValueError,'outside task'):task_host.start(**config,snapshot=foreign)

class FixedRenderWorkerTests(unittest.TestCase):
    def run_worker(self,kind='Write',pattern='out.%04d.exr',frames=None):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'scene.nk';path.write_text('Root {}')
            node=mock.Mock();node.Class.return_value=kind
            knob=mock.Mock();knob.value.return_value=pattern
            node.__getitem__=mock.Mock(return_value=knob)
            api=mock.Mock();api.toNode.return_value=node
            with mock.patch.object(owned_render_worker,'_load_nuke_api',return_value=api),mock.patch.object(owned_render_worker,'_write_receipt'):
                owned_render_worker.main(['worker',str(path),'Write1','1','3','out.%04d.exr',json.dumps(frames or [1,3])])
            return api
    def test_exact_sparse_native_write_is_executed(self):
        api=self.run_worker();self.assertEqual([call.args[1:] for call in api.execute.call_args_list],[(1,1),(3,3)])
    def test_wrong_node_path_and_frame_bounds_rejected_before_execute(self):
        for config in ({'kind':'Read'},{'pattern':'wrong.%04d.exr'},{'frames':[1,2]}):
            with self.subTest(config=config),self.assertRaises(ValueError):self.run_worker(**config)

if __name__=='__main__':unittest.main()
