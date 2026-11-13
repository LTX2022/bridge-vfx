"""Actual addon recovery rejects late native reads before final commit."""
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_host as runtime
import test_rbd_reopen_addon as support
from test_native_rbd_controls_program import packed_geometry


class RbdReopenReviewGuards(unittest.TestCase):
    def run_late_native_fault(self, kind):
        for version in core.VERSIONS:
            with self.subTest(version=version), support.Fixture(version) as fixture:
                geometry = packed_geometry()
                if kind == 'geometry':
                    native_class = type(fixture.carrier())
                    original_geometry = native_class.geometryAtFrame

                    def fixed_source(node, frame, output_index=0):
                        if (node.type().name() == 'rbdconfigure' or node.path() == fixture.roles['rbd_velocity']) and output_index == 0:
                            return geometry
                        return original_geometry(node, frame, output_index=output_index)

                    fixture.stack.enter_context(patch.object(native_class, 'geometryAtFrame', fixed_source))
                path, receipt = fixture.save()
                fixture.discard_authority()
                original_end = runtime.Host.end
                original_checkpoint = runtime.Host.checkpoint
                node_class = type(fixture.carrier())
                original_connections = node_class.inputConnections
                after_checkpoint, events = [], []

                def checkpoint_marked(host, roles, pack):
                    result = original_checkpoint(host, roles, pack)
                    after_checkpoint.append(True)
                    return result

                def connections_with_fault(node):
                    result = original_connections(node)
                    if after_checkpoint and not events and node.path() == fixture.roles['solver']:
                        if kind == 'gate':
                            fixture.carrier().parm('exportlist').set('w')
                        elif kind == 'geometry':
                            geometry.points()[0].values['temperature'] += 1
                        else:
                            loaded = Path(fixture.hou.hipFile.path())
                            loaded.chmod(loaded.stat().st_mode | stat.S_IWRITE)
                            loaded.write_bytes(loaded.read_bytes() + b'\nexplicit late HIP drift\n')
                        events.append(kind)
                    return result

                def end_with_native_fault(host, token, commit):
                    if not commit:
                        return original_end(host, token, commit)
                    with patch.object(runtime.Host, 'checkpoint', checkpoint_marked), \
                            patch.object(node_class, 'inputConnections', connections_with_fault):
                        return original_end(host, token, commit)

                before_save = fixture.addon._fx_task_saves_path(fixture.task).read_bytes()
                with patch.object(runtime.Host, 'end', end_with_native_fault):
                    with self.assertRaises(fixture.addon.BridgeCommandError):
                        fixture.reopen(path)
                self.assertEqual(events, [kind])
                support.RbdReopenAddonTests().assert_no_authority(fixture)
                self.assertEqual(fixture.addon._fx_task_saves_path(fixture.task).read_bytes(), before_save)
                transition = fixture.addon.fx_operation_runner(fixture.task)._load()['scene_transitions']['rbd-unit-reopen']
                self.assertEqual(transition['state'], 'INTENT')
                if kind == 'hip':
                    self.assertNotEqual(fixture.addon._fx_sha256_file(Path(fixture.hou.hipFile.path())), receipt['sha256'])

    def test_final_wire_read_changes_earlier_gate_and_revokes_completion(self):
        self.run_late_native_fault('gate')

    def test_final_native_read_changes_hip_and_revokes_completion(self):
        self.run_late_native_fault('hip')

    def test_final_wire_read_changes_actual_geometry_and_revokes_completion(self):
        self.run_late_native_fault('geometry')


if __name__ == '__main__':
    unittest.main()
