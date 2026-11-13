"""R05 rejection through actual addon preflight and public command entry."""
from contextlib import ExitStack
import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_program as program
from vfx_pipeline.workbuddy_assembly import software_host_client
from test_rbd_host_authority import fixed_fixture, public_registration

ROOT = Path(__file__).resolve().parents[2]


def load_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RbdAddonAuthorityTests(unittest.TestCase):
    def test_actual_addon_preflight_refuses_public_registration(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                host, nodes, roles, hou, identity = fixed_fixture(version)
                public_registration(host, nodes, roles, version)
                stack.enter_context(patch.dict(sys.modules, {'hou': hou}))
                spec = importlib.util.spec_from_file_location('_rbd_authority_addon',
                    ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
                addon = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(addon)
                addon.__dict__.update(host.h)
                addon._TASK_HOST_IDENTITY = copy.deepcopy(identity)
                pack = dict(native_domain_id=core.RBD, native_plan_schema=core.SCHEMA,
                            shared_render_schema='bridge.native-render-domains/1',
                            controls=core.control_contract(core.RBD, version))
                before = copy.deepcopy(nodes[program.ROLE].data)
                binding = dict(domain_plan=True, host_controls={'velocity_variance': 0.})
                addon._fx_prepare_source_runtime(binding, pack)
                self.assertEqual(binding['runtime_values'], {'velocity_variance': 0.})
                self.assertEqual(pack['controls']['velocity_variance']['native_status'], 'blocked')
                for name, value in (('fracture_scale', 1.), ('velocity_variance', -1.)):
                    refused_binding = dict(domain_plan=True, host_controls={name: value})
                    with self.assertRaises(addon.BridgeCommandError):
                        addon._fx_prepare_source_runtime(refused_binding, pack)
                    self.assertNotIn('runtime_values', refused_binding)
                with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
                    addon._fx_planned_observations({'velocity_variance': 0.}, roles, pack)
                self.assertEqual(refused.exception.code, 'RBD_VELOCITY_AUTHORITY_REQUIRED')
                self.assertEqual(nodes[program.ROLE].data, before)
                self.assertEqual(hou.frame(), 12.)

    def test_actual_apply_candidate_missing_packed_native_api_refuses_without_write(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                stack.enter_context(patch.dict(os.environ, {
                    'HOUDINI_BRIDGE_STATE_DIR': str(directory / 'houdini'),
                    'BRIDGE_SKILLS_STATE_ROOT': str(directory / 'state'),
                    'BRIDGE_SKILLS_SCHEDULER_ROOT': str(directory / 'scheduler')}))
                stack.enter_context(patch.dict(sys.modules))
                client, addon = software_host_client(
                    ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', directory / 'host')
                boundary = load_tool('rbd_authority_schema', 'native_schema_test_boundary.py')
                api = load_tool('rbd_authority_render_api', 'software_render_api_boundary.py')
                interfaces, states, ports = api.interface_profiles(ROOT, version)
                boundary.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', version,
                    instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
                hou = sys.modules['hou']
                api.install_stage_api(hou)
                node_class = type(hou.node('/obj'))
                stack.enter_context(patch.object(node_class, 'isBypassed', lambda node: False, create=True))
                addon._TASK_HOST_IDENTITY = dict(task_id='rbd-authority-task', version=version,
                    pid=os.getpid(), launch_nonce='explicit-rbd-authority-software',
                    session_id='rbd-authority-session', process_generation='rbd-authority-generation')
                params = dict(task_id='rbd-authority-task', constraints={'fx': {
                    'domain_pack': core.RBD, 'run_mode': 'diagnose', 'frames': [1]}},
                    render={'frame_range': dict(start=1, end=1, step=1)})
                built = client.call('agent.fx.build_preview', params)
                roles = built['scene_manifest']['nodes']
                carrier = hou.node(roles[program.ROLE])
                before_snippet = carrier.parm('snippet').eval()
                before_basis = carrier.userData('bridge_rbd_velocity_basis_v1')
                before_program = carrier.userData('bridge_rbd_velocity_program_v1')
                before_state = addon._fx_state_path(params['task_id']).read_bytes()
                original_frame = hou.frame()
                changes = copy.deepcopy(params)
                changes['constraints']['fx']['changes'] = {'velocity_variance': 0.}
                with self.assertRaises(addon.BridgeCommandError) as refused:
                    client.call('agent.fx.apply_candidate', changes)
                self.assertEqual(refused.exception.code, 'RBD_PACKED_GEOMETRY_COLLECTION_FAILED')
                self.assertEqual(carrier.parm('snippet').eval(), before_snippet)
                self.assertEqual(carrier.userData('bridge_rbd_velocity_basis_v1'), before_basis)
                self.assertEqual(carrier.userData('bridge_rbd_velocity_program_v1'), before_program)
                self.assertEqual(addon._fx_state_path(params['task_id']).read_bytes(), before_state)
                self.assertEqual(hou.frame(), original_frame)


if __name__ == '__main__':
    unittest.main()
