import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_houdini_fx_domains import _load_addon


class OwnedHeadlessReopenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'own.hip';self.path.write_bytes(b'owned fixture')
        self.pref=self.root/'houdini-user-pref'/'21.0';self.pref.mkdir(parents=True)
        self.loaded=[];self.gui=False
        self.hip=SimpleNamespace(path=lambda:str(self.path),load=lambda *a,**k:self.loaded.append(a),
            hasUnsavedChanges=lambda:self.fail('headless dirty flag must not be used'))
        self.hou=SimpleNamespace(isUIAvailable=lambda:self.gui,hipFile=self.hip,getenv=lambda key:str(self.pref))
        self.addon=_load_addon()
        self.args={'path':str(self.path),'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def invoke(self):
        with patch.dict(sys.modules,{'hou':self.hou}),patch.dict('os.environ',{'HOUDINI_USER_PREF_DIR':str(self.pref)}):
            return self.addon.dispatch('scene.reopen_owned_hip',self.args)

    def test_just_saved_owned_headless_file_reopens_without_false_dirty_claim(self):
        result=self.invoke()
        self.assertTrue(result['owned_headless_reopen']);self.assertIsNone(result['has_unsaved_changes'])
        self.assertEqual(len(self.loaded),1)
        self.assertNotIn('scene.reopen_owned_hip',self.addon._DEFAULT_BRIDGE_COMMANDS)

    def test_gui_existing_scenes_cannot_use_private_reopen(self):
        self.gui=True
        with self.assertRaises(Exception):self.invoke()
        self.assertFalse(self.loaded)

    def test_changed_file_or_other_scene_rejected_before_load(self):
        self.path.write_bytes(b'changed')
        with self.assertRaises(Exception):self.invoke()
        self.path.write_bytes(b'owned fixture');self.hip.path=lambda:str(self.root/'other.hip')
        with self.assertRaises(Exception):self.invoke()
        self.assertFalse(self.loaded)

    def test_outside_task_directory_rejected(self):
        self.pref=self.root/'other'/'houdini-user-pref'/'21.0';self.pref.mkdir(parents=True)
        with self.assertRaises(Exception):self.invoke()
        self.assertFalse(self.loaded)


class GraphWorkerIdentityTests(unittest.TestCase):
    """HOM API-shaped software fixture; no Houdini version acceptance."""
    def setUp(self):
        OwnedHeadlessReopenTests.setUp(self)
        self.callbacks=[]
        self.hip.addEventCallback=self.callbacks.append
        self.hip.eventCallbacks=lambda:tuple(self.callbacks)
        self.hou.hipFileEventType=SimpleNamespace(BeforeClear='clear',BeforeLoad='load',BeforeMerge='merge')

    def identity(self):
        with patch.dict(sys.modules,{'hou':self.hou}):
            return self.addon.graph_worker_identity()

    def test_scene_events_change_identity_even_for_the_same_path(self):
        initial=self.identity()
        self.assertEqual(initial,self.identity())
        with patch.dict(sys.modules,{'hou':self.hou}):
            self.callbacks[0](self.hou.hipFileEventType.BeforeLoad)
        changed=self.identity()
        self.assertEqual(initial['hip_path'],changed['hip_path'])
        self.assertNotEqual(initial['scene_id'],changed['scene_id'])

    def test_missing_removed_callback_and_gui_fail_closed(self):
        self.hip.addEventCallback=lambda callback:None
        with self.assertRaises(Exception):self.identity()
        self.hip.addEventCallback=self.callbacks.append
        self.addon._GRAPH_WORKER_CALLBACK_INSTALLED=False
        self.identity();self.callbacks.clear()
        with self.assertRaises(Exception):self.identity()
        self.gui=True
        with self.assertRaises(Exception):self.identity()

    def test_process_identity_is_fresh_not_an_echo_from_lease(self):
        first=self.identity()
        with patch.object(self.addon.os,'getpid',return_value=987654321):
            other=self.identity()
        self.assertNotEqual(first['process_generation'],other['process_generation'])
