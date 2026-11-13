"""Actual addon candidate/manifest paths with explicit bottom HOM expressions."""
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from houdini_bridge import native_particle_emission_program as program
from houdini_bridge import native_particle_emission_host as adapter
from vfx_pipeline.workbuddy_assembly import software_host_client
import test_native_geometry_addon_wiring as support
import test_native_particle_emission_host as bottom

ROOT = Path(__file__).resolve().parents[2]


class Fixture:
    def __init__(self, version):
        self.version, self.stack = version, ExitStack()

    def __enter__(self):
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {
            'HOUDINI_BRIDGE_STATE_DIR': str(self.directory / 'houdini'),
            'BRIDGE_SKILLS_STATE_ROOT': str(self.directory / 'state'),
            'BRIDGE_SKILLS_SCHEDULER_ROOT': str(self.directory / 'scheduler')}))
        self.stack.enter_context(patch.dict(sys.modules))
        self.client, self.addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py',
                                                       self.directory / 'host')
        native = support.load_boundary('p01_schema_boundary', 'native_schema_test_boundary.py')
        api = support.load_boundary('p01_stage_boundary', 'software_render_api_boundary.py')
        interfaces, states, ports = api.interface_profiles(ROOT, self.version)
        for name, value in (('constantrate', 1200.), ('probemit', 0), ('seed', 17.), ('jitterbirthtime', 'positive')):
            states.setdefault('Dop/popsource::2.0', {})[name] = dict(origin='test_injected_native_api',
                value=value, locked=False, hidden=False, disabled=False)
        states.setdefault('Dop/popsolver::2.0', {})['timescale'] = dict(origin='test_injected_native_api',
            value=1., locked=False, hidden=False, disabled=False)
        native.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', self.version,
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        self.hou = sys.modules['hou']
        api.install_stage_api(self.hou)
        self.hou.fps = lambda: 24.
        self.hou.frameToTime = lambda frame: (frame - 1.) / self.hou.fps()
        self.stack.enter_context(patch.object(type(self.hou.node('/obj')), 'isBypassed',
            lambda node: bool(getattr(node, '_native_bypassed', False)), create=True))
        self.task = 'particle-emission-addon'
        identity = dict(task_id=self.task, version=self.version, pid=os.getpid(),
            launch_nonce='explicit-p01-addon-boundary', session_id='p01-unit-session',
            process_generation='p01-unit-generation', plugin_build=hashlib.sha256(
                (ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py').read_bytes()).hexdigest())
        self.stack.enter_context(patch.object(self.addon, '_TASK_HOST_IDENTITY', identity, create=True))
        self.params = dict(task_id=self.task, constraints={'fx': {'domain_pack': 'particles_v1',
            'run_mode': 'diagnose', 'frames': [1, 2]}},
            render={'frame_range': {'start': 1, 'end': 2, 'step': 1}})
        built = self.client.call('agent.fx.build_preview', self.params)
        self.roles = built['scene_manifest']['nodes']
        self.pack = self.addon._fx_pack(self.params)[1]
        self.root = self.hou.node(built['scene_manifest']['execution_root'])
        self.parameter = self.hou.node(self.roles['emission']).parm('constantrate')
        simulation = self.hou.node(self.roles['simulation'])
        clock_parameters = {}
        for name, label, value in (('native_offset', 'Offset Time', -.25), ('native_scale', 'Scale Time', 1.)):
            owner = SimpleNamespace(path=simulation.path, fixture=SimpleNamespace(hou=self.hou, write_calls=[]))
            parameter = bottom.NativeParameter(owner, name, value)
            template = SimpleNamespace(name=lambda name=name: name, label=lambda label=label: label,
                type=lambda: 'parmTemplateType.Float', numComponents=lambda: 1,
                menuItems=lambda: (), menuLabels=lambda: (), menuUseToken=lambda: False,
                minIsStrict=lambda: False, maxIsStrict=lambda: False, minValue=lambda: 0., maxValue=lambda: 1.)
            parameter.parmTemplate = lambda template=template: template
            clock_parameters[name] = parameter
        node_class = type(simulation)
        original_parm = node_class.parm
        self.stack.enter_context(patch.object(node_class, 'parm',
            lambda node, name: clock_parameters[name] if node == simulation and name in clock_parameters else original_parm(node, name)))
        self.stack.enter_context(patch.object(node_class, 'parmTemplateGroup',
            lambda node: SimpleNamespace(entries=lambda: tuple(parameter.parmTemplate() for parameter in clock_parameters.values()))
            if node == simulation else node.type().parmTemplateGroup(), create=True))
        parameter_class = type(self.parameter)
        original_eval, original_expression = parameter_class.eval, parameter_class.setExpression
        original_keys = parameter_class.setKeyframes

        def eval_expression(parameter):
            source = parameter._native_state['expression']
            if parameter.name() != 'constantrate' or source is None:
                return original_eval(parameter)
            if not source.startswith('import hou\nimport math\nimport hashlib\n'):
                raise ValueError('bottom boundary only evaluates the generated P01 expression')
            namespace = {}
            exec('def evaluate():\n' + textwrap.indent(source, '    '), namespace)
            return namespace['evaluate']()

        def set_expression(parameter, source, language=None):
            original_expression(parameter, source, language)
            if parameter.name() == 'constantrate':
                parameter._native_state['keyframes'] = [dict(frame=self.hou.frame(), value=None,
                    expression=source, language=str(language))]

        def set_keys(parameter, keys):
            original_keys(parameter, keys)
            if parameter.name() == 'constantrate' and len(keys) == 1 and keys[0].expression() is not None:
                parameter._native_state.update(expression=keys[0].expression(), language=str(keys[0].expressionLanguage()))

        self.stack.enter_context(patch.object(parameter_class, 'eval', eval_expression))
        self.stack.enter_context(patch.object(parameter_class, 'setExpression', set_expression))
        self.stack.enter_context(patch.object(parameter_class, 'setKeyframes', set_keys))
        self.host = self.addon._fx_particle_emission_host()
        self.host.initialize({'constraints': {'fx': {'particle_emission_basis': {'task_seed': 173}}}},
                             self.roles, self.pack, {'emission'})
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def apply(self, changes):
        params = copy.deepcopy(self.params)
        params['constraints']['fx']['candidate_patch'] = changes
        return self.client.call('agent.fx.apply_candidate', params)


class ParticleEmissionAddonTests(unittest.TestCase):
    def test_public_build_enters_real_scope_and_scene_clear_preserves_legacy_birth_rate(self):
        for version in program.SUPPORTED_VERSIONS:
            calls = []
            original = adapter.Host.build_transaction
            @contextmanager
            def observe_scope(host, root):
                calls.append(root)
                with original(host, root):
                    yield
            with self.subTest(version=version), patch.object(adapter.Host, 'build_transaction', observe_scope):
                with Fixture(version) as fixture:
                    self.assertEqual(calls, [fixture.root.path()])
                    fixture.addon._bridge_scene_event(fixture.hou.hipFileEventType.BeforeClear)
                    fixture.root.destroy()
                    self.assertEqual(fixture.host.authority['records'], {})
                    fixture.client.call('agent.fx.build_preview', fixture.params)
                    self.assertEqual(len(calls), 2)
                    result = fixture.apply({'birth_rate': 1800.})
                    self.assertTrue(result['gates'][0]['passed'])
                    self.assertEqual(fixture.host.authority['records'], {})

    def test_outer_build_failure_revokes_only_issued_registration_and_allows_retry(self):
        for version in program.SUPPORTED_VERSIONS:
            for failure in ('outer_exception', 'late_gate', 'successor'):
                with self.subTest(version=version, failure=failure):
                    fixture = bottom.NativeEmissionFixture(version)
                    successor = {'newer_private_record': True}
                    with self.assertRaises((OSError, program.ParticleEmissionError)):
                        with fixture.host.build_transaction('/obj/p01_api'):
                            fixture.initialize()
                            if failure == 'late_gate':
                                fixture.nodes['emission'].parm('constantactivate').value = 0.
                            elif failure == 'successor':
                                fixture.host.authority['records']['/obj/p01_api'] = successor
                                raise OSError('actual caller failed after initialization')
                            else:
                                raise OSError('actual caller failed after initialization')
                    self.assertEqual(fixture.host.authority['builds'], {})
                    if failure == 'successor':
                        self.assertIs(fixture.host.authority['records']['/obj/p01_api'], successor)
                    else:
                        self.assertEqual(fixture.host.authority['records'], {})
                        fixture.nodes['emission'].parm('constantactivate').value = 1.
                        fixture.nodes['emission'].native_session += 1
                        with fixture.host.build_transaction('/obj/p01_api'):
                            fixture.initialize()
                        self.assertEqual(fixture.context()['percentage'], 0.)

    def test_actual_candidate_joint_baseline_expression_readback_and_zero_restore(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                result = fixture.apply({'emission_variance': 45., 'birth_rate': 2300.})
                self.assertTrue(result['parameter_diff'])
                self.assertEqual(result['native_geometry_readback']['status'], 'BLOCKED')
                self.assertEqual(result['native_geometry_readback']['evidence_scope'], 'native_parameter_expression_only')
                self.assertEqual(fixture.host.readback(fixture.roles, fixture.pack)['birth_rate'], 2300.)
                values = []
                for frame in (-12., -6.5, 0., 1., 7., 24., 24.5, 25.):
                    fixture.hou.setFrame(frame)
                    current = fixture.host.readback(fixture.roles, fixture.pack)
                    expected = program.rate_at_time(current['context']['basis'], 45., fixture.hou.time(), 2300.)
                    self.assertAlmostEqual(fixture.parameter.eval(), expected)
                    values.append(current['actual_rate'])
                self.assertGreater(len(set(values)), 1)
                fixture.apply({'birth_rate': 3100.})
                self.assertEqual(fixture.host.readback(fixture.roles, fixture.pack)['percentage'], 45.)
                fixture.apply({'emission_variance': 0.})
                self.assertEqual(fixture.parameter.eval(), 3100.)
                self.assertEqual(fixture.parameter.keyframes(), ())

    def test_manifest_failure_restores_full_native_channel_and_private_registration(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.apply({'emission_variance': 30.})
                before = copy.deepcopy(fixture.parameter._native_state)
                context = fixture.host.observations(fixture.roles, fixture.pack)
                with patch.object(fixture.addon, '_fx_store_manifest', side_effect=OSError('owned test manifest failure')):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as rejected:
                        fixture.apply({'emission_variance': 70., 'birth_rate': 3200.})
                self.assertEqual(rejected.exception.code, 'CANDIDATE_PERSIST_FAILED', str(rejected.exception))
                self.assertEqual(fixture.parameter._native_state, before)
                self.assertEqual(fixture.host.observations(fixture.roles, fixture.pack), context)
                self.assertEqual(fixture.host.authority['snapshots'], {})

    def test_saved_scene_bytes_are_not_new_identity_authority(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.apply({'emission_variance': 15.})
                fixture.client.call('scene.save_hip', dict(task_id=fixture.task, path=str(fixture.directory / 'p01-owned-save.hip')))
                before = copy.deepcopy(fixture.parameter._native_state)
                fixture.addon._TASK_HOST_IDENTITY['launch_nonce'] = 'different-host'
                with self.assertRaises(ValueError) as rejected:
                    fixture.host.observations(fixture.roles, fixture.pack)
                self.assertIn('PARTICLE_EMISSION_AUTHORITY_REQUIRED', str(rejected.exception))
                self.assertEqual(fixture.parameter._native_state, before)

    def test_late_persisted_gate_drift_refuses_and_restores_manifest_and_channel(self):
        for version in program.SUPPORTED_VERSIONS:
            with self.subTest(version=version), Fixture(version) as fixture:
                fixture.apply({'emission_variance': 30.})
                before = copy.deepcopy(fixture.parameter._native_state)
                before_manifest = fixture.addon._fx_manifest(fixture.task)[1]
                store = fixture.addon._fx_store_manifest
                gate = fixture.hou.node(fixture.roles['emission']).parm('constantactivate')
                def persist_then_drift(root, manifest):
                    result = store(root, manifest)
                    gate.value = 0.
                    return result
                with patch.object(fixture.addon, '_fx_store_manifest', side_effect=persist_then_drift):
                    with self.assertRaises(fixture.addon.BridgeCommandError) as rejected:
                        fixture.apply({'emission_variance': 70.})
                self.assertEqual(rejected.exception.code, 'CANDIDATE_PERSIST_FAILED', str(rejected.exception))
                self.assertEqual(fixture.parameter._native_state, before)
                self.assertEqual(fixture.addon._fx_manifest(fixture.task)[1], before_manifest)
                self.assertEqual(gate.eval(), 0.)
                gate.value = 1.
                self.assertEqual(fixture.host.readback(fixture.roles, fixture.pack)['percentage'], 30.)
                self.assertEqual(fixture.host.authority['snapshots'], {})


if __name__ == '__main__':
    unittest.main()
