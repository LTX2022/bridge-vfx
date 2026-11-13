from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from vfx_pipeline.workbuddy_assembly import software_host_client

ROOT=Path(__file__).resolve().parents[2]

class SoftwareScenePersistenceTests(unittest.TestCase):
    def test_saved_bytes_bind_parameters_connections_and_fresh_reopen(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules):
            root=Path(tmp)
            software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',root/'first')
            hou=sys.modules['hou']; geo=hou.node('/obj').createNode('geo','owned')
            src=geo.createNode('sphere','src'); dst=geo.createNode('null','out');dst.setInput(0,src,2)
            src.parm('radx').set(1)
            scene=root/'one.hip'; hou.hipFile.save(str(scene)); before=hashlib.sha256(scene.read_bytes()).hexdigest()
            src.parm('radx').set(2);hou.hipFile.save(str(scene))
            self.assertNotEqual(before,hashlib.sha256(scene.read_bytes()).hexdigest())
            # A sidecar cannot change the immutable project receipt.
            Path(str(scene)+'.bridge-scene.json').write_text('{"nodes": []}')
            software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',root/'second')
            fresh=sys.modules['hou'];fresh.hipFile.load(str(scene))
            self.assertEqual(fresh.node('/obj/owned/src').parm('radx').eval(),2)
            self.assertEqual(fresh.node('/obj/owned/out').inputs()[0].path(),'/obj/owned/src')
            self.assertEqual(fresh.node('/obj/owned/out').inputConnections()[0].outputIndex(),2)
    def test_missing_or_legacy_snapshot_cannot_reopen_as_success(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules):
            root=Path(tmp);software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py',root)
            path=root/'invalid.hip';path.write_bytes(b'software fake hip\n')
            with self.assertRaisesRegex(ValueError,'SOFTWARE_SCENE_SNAPSHOT_INVALID'):
                sys.modules['hou'].hipFile.load(str(path))
