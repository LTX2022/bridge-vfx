import copy
import sys
import unittest

import test_readiness_native_command_evidence as native_fixture


class NativeCreationInitializationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native_fixture.NativeCommandEvidenceTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.addon = self.fixture.addon
        self.hou = sys.modules['hou']
        self.root = self.hou.node(self.fixture.saved['scene_contract']['execution_root'])
        self.transition = self.root.createNode('dopnet', 'simulation').createNode('crowdtransition::3.0', 'transition')
        self.ramp = dict(schema='bridge.native-float-ramp/1', basis=['Linear', 'Linear'],
                         keys=[0., 1.], values=[0., 1.])

    def test_explicit_ramp_initialization_uses_native_constructor_and_readback(self):
        parameter = self.transition.parm('blend')
        with self.assertRaisesRegex(ValueError, 'native default is not captured'):
            parameter.evalAsRamp()
        result = self.addon._set_parms(self.transition, {'blend': self.ramp})
        actual = parameter.evalAsRamp()
        self.assertEqual(actual.basis(), (self.hou.rampBasis.Linear, self.hou.rampBasis.Linear))
        self.assertEqual(actual.keys(), (0., 1.))
        self.assertEqual(actual.values(), (0., 1.))
        self.assertEqual(result['blend']['type'], 'ramp')

    def test_invalid_ramp_payloads_do_not_mutate_native_parameter(self):
        self.addon._set_parms(self.transition, {'blend': self.ramp})
        for changes in ({'values': [False, 1.]}, {'keys': [True, 1.]},
                        {'basis': ['Linear', 'Constant']}, {'values': [0., 2.]},
                        {'keys': [0., .5, 1.]}, {'code': 'untrusted()'}):
            with self.subTest(changes=changes):
                payload = dict(copy.deepcopy(self.ramp), **changes)
                with self.assertRaises(self.addon.BridgeCommandError):
                    self.addon._set_parms(self.transition, {'blend': payload})
                self.assertEqual(self.transition.parm('blend').evalAsRamp().values(), (0., 1.))

    def test_ramp_payload_cannot_replace_a_scalar_parameter(self):
        before = self.transition.parm('duration').eval()
        with self.assertRaises(self.addon.BridgeCommandError):
            self.addon._set_parms(self.transition, {'duration': self.ramp})
        self.assertEqual(self.transition.parm('duration').eval(), before)


if __name__ == '__main__':
    unittest.main()
