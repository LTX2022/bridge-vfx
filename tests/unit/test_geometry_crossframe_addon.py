"""G03 formal commands with explicit bottom rest data, never a VEX cook."""
import copy
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_program as program
import test_native_geometry_addon_wiring as wiring


class GeometryCrossframeAddonTests(unittest.TestCase):
    def observation(self, fixture, frames):
        params = copy.deepcopy(fixture.params)
        params['constraints']['fx']['frames'] = frames
        params['render']['frame_range'] = dict(start=frames[0], end=frames[-1], step=1)
        return fixture.client.call('agent.fx.collect_evidence', params)['evidence']

    def test_registered_static_source_reads_all_frames_and_restores_original_frame(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                fixture.apply({'deformation': 3.})
                original_frame = fixture.hou.frame()
                before = fixture.carrier.parm('snippet').eval()
                evidence = self.observation(fixture, [-1, 0, 1, 2])
                self.assertEqual(fixture.hou.frame(), original_frame)
                self.assertEqual(fixture.carrier.parm('snippet').eval(), before)
                self.assertEqual(set(evidence['native_geometry_readback']), {'-1', '0', '1', '2'})
                for readback in evidence['native_geometry_readback'].values():
                    self.assertEqual(readback['value'], 3.)
                    self.assertEqual(readback['status'], 'BLOCKED')
                    self.assertEqual(readback['evidence_scope'], 'parameters_only')

    def test_failed_native_observation_restores_original_frame_without_rewriting_program(self):
        for version in program.VERSIONS:
            with self.subTest(version=version), wiring.Fixture(version) as fixture:
                fixture.build()
                fixture.apply({'deformation': 3.})
                original_frame = fixture.hou.frame()
                before = fixture.carrier.parm('snippet').eval()
                node_class = type(fixture.hou.node(fixture.source_path))
                original_geometry = node_class.geometry

                def geometry(node, output_index=0):
                    if node.path() == fixture.source_path and fixture.hou.frame() == 2:
                        raise ValueError('explicit bottom native observation failure')
                    return original_geometry(node, output_index=output_index)

                with patch.object(node_class, 'geometry', geometry):
                    with self.assertRaises(Exception):
                        self.observation(fixture, [1, 2])
                self.assertEqual(fixture.hou.frame(), original_frame)
                self.assertEqual(fixture.carrier.parm('snippet').eval(), before)


if __name__ == '__main__':
    unittest.main()
