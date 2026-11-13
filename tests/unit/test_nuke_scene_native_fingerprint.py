"""Exercise native Format values in the actual render request fingerprint."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_nuke_bridge_addon_runtime import load_addon
from test_nuke_composite_format import Format, Knob


class SceneNativeFingerprintTests(unittest.TestCase):
    def test_native_format_fingerprint_is_stable_and_covers_format_and_nk_bytes(self):
        addon=load_addon()
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'scene.nk';script.write_text('Root {}\n')
            knobs={'file':Knob('/input.exr'),'format':Knob(Format()),'zorder':Knob(0)}
            node=SimpleNamespace(knobs=lambda:knobs,Class=lambda:'Read')
            nuke=SimpleNamespace(Format=Format,root=lambda:SimpleNamespace(name=lambda:str(script)),
                NUKE_VERSION_STRING='17.0v1',toNode=lambda name:node if name=='Read1' else None)
            captured=[]
            canonical=addon._canonical_payload_sha256
            def record(value):
                captured.append(value);return canonical(value)
            with patch.object(addon,'_nuke_scene_fingerprint',return_value={'fingerprint_complete':True,'scene_fingerprint':'a'*64}), patch.object(addon,'_canonical_payload_sha256',side_effect=record):
                before=addon._nuke_scene_version_fingerprint(nuke)
                self.assertEqual(captured[-1]['script'],str(script))
                self.assertEqual(captured[-1]['script_bytes'],len(script.read_bytes()))
                self.assertTrue(captured[-1]['script_sha256'])
                knobs['format'].current=Format()
                self.assertEqual(addon._nuke_scene_version_fingerprint(nuke),before)
                knobs['format'].current=Format(256)
                self.assertNotEqual(addon._nuke_scene_version_fingerprint(nuke),before)
                knobs['format'].current=Format()
                script.write_text('Root { first_frame 2 }\n')
                self.assertNotEqual(addon._nuke_scene_version_fingerprint(nuke),before)
                knobs['format'].current=Format(128.0)
                with self.assertRaisesRegex(ValueError, 'Format field'):
                    addon._nuke_scene_version_fingerprint(nuke)
                knobs['format'].current=object()
                with self.assertRaises(TypeError):addon._nuke_scene_version_fingerprint(nuke)
