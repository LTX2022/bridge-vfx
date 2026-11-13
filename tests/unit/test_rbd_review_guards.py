"""Permanent R01-R05 refusal guards using actual Host/addon and fixed HOM data."""
from contextlib import ExitStack
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_flip_rbd_domains as core
from houdini_bridge import native_rbd_controls_program as program
from houdini_bridge.native_rbd_controls_host import BASIS_KEY
from test_rbd_host_authority import fixed_fixture, prepare_zero

ROOT = Path(__file__).resolve().parents[2]


def native_state(nodes):
    return {role: dict(parameters={name: copy.deepcopy(parameter.value)
                                  for name, parameter in node.parameters.items()},
                       userdata=copy.deepcopy(node.data))
            for role, node in nodes.items()}


def trace_native_writes(stack, nodes):
    writes = []
    for role, node in nodes.items():
        for name, parameter in node.parameters.items():
            original = parameter.set
            def set_parameter(value, *args, original=original, role=role, name=name, **kwargs):
                writes.append(('parameter', role, name))
                return original(value, *args, **kwargs)
            stack.enter_context(patch.object(parameter, 'set', set_parameter))
        for method in ('setUserData', 'destroyUserData'):
            original = getattr(node, method)
            def set_userdata(*args, original=original, role=role, method=method, **kwargs):
                writes.append((method, role, args[0]))
                return original(*args, **kwargs)
            stack.enter_context(patch.object(node, method, set_userdata))
    return writes


def load_actual_restore_addon(stack, host, hou, identity):
    stack.enter_context(patch.dict(sys.modules, {'hou': hou}))
    spec = importlib.util.spec_from_file_location('_rbd_review_guards_addon',
        ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py')
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.__dict__.update(host.h)
    # Restore-only HOM fixture supplies the trusted seed boundary; persisted
    # manifest authority is exercised by the formal authority/reopen suites.
    addon._fx_rbd_task_seed = lambda roles, pack: 123
    addon._TASK_HOST_IDENTITY = copy.deepcopy(identity)
    return addon


class RbdReviewGuardTests(unittest.TestCase):
    def test_r01_last_userdata_read_changing_earlier_export_gate_refuses(self):
        for version in core.VERSIONS:
            with self.subTest(version=version):
                host, nodes, roles, hou, identity = fixed_fixture(version)
                carrier = nodes[program.ROLE]
                original_userdata = carrier.userData
                reads = []
                def userdata(name):
                    value = original_userdata(name)
                    if name == BASIS_KEY:
                        reads.append(name)
                        if len(reads) == 3:
                            carrier.parm('exportlist').set('w')
                    return value
                carrier.userData = userdata
                before_data = copy.deepcopy(carrier.data)
                with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
                    host.observations({'velocity_variance': 0.}, roles, {}, task_seed=123)
                self.assertEqual(refused.exception.code, 'RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED')
                self.assertGreaterEqual(len(reads), 3)
                self.assertEqual(carrier.parm('exportlist').value, 'w')
                self.assertEqual(carrier.parm('snippet').value, '')
                self.assertEqual(carrier.data, before_data)
                self.assertEqual(hou.frame(), 12.)

    def test_r02_actual_addon_restore_identity_drift_has_no_native_writes(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = prepare_zero(host, nodes, roles, version)
                host.write(item, roles, {})
                item['snapshot'] = dict(mode='value_only_compat', evaluated='')
                item['parm'].eval = lambda: item['parm'].value
                item['parm'].set('current-context-value')
                identity['launch_nonce'] = 'different-current-context'
                addon = load_actual_restore_addon(stack, host, hou, identity)
                before = native_state(nodes)
                writes = trace_native_writes(stack, nodes)
                with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
                    addon._fx_restore_planned_item(item, roles, {})
                self.assertEqual(refused.exception.code, 'RBD_VELOCITY_AUTHORITY_REQUIRED')
                self.assertEqual(writes, [])
                self.assertEqual(native_state(nodes), before)
                self.assertEqual(hou.frame(), 12.)

    def test_r03_direct_host_restore_lost_lease_has_no_native_writes(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                host, nodes, roles, hou, identity = fixed_fixture(version)
                item = prepare_zero(host, nodes, roles, version)
                host.write(item, roles, {})
                before = native_state(nodes)
                lease_reads = []
                def lost_lease(root, **kwargs):
                    lease_reads.append((root, kwargs))
                    raise ValueError('LEASE_LOST')
                host.h['_root_lease_check'] = lost_lease
                writes = trace_native_writes(stack, nodes)
                with self.assertRaisesRegex(ValueError, '^LEASE_LOST$'):
                    host.restore(item)
                self.assertTrue(lease_reads)
                self.assertEqual(lease_reads[0][0], '/obj/task')
                self.assertEqual(writes, [])
                self.assertEqual(native_state(nodes), before)
                self.assertEqual(hou.frame(), 12.)

    def test_r04_late_old_solver_geometry_cannot_hide_current_source_drift(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                host, nodes, roles, hou, identity = fixed_fixture(version)
                host.write(prepare_zero(host, nodes, roles, version), roles, {})
                before = native_state(nodes)
                original_input = nodes['solver'].inputGeometry
                frozen_input = original_input(0).freeze()
                returned_temperatures = []
                def input_geometry(input_index):
                    geometry = frozen_input.freeze()
                    returned_temperatures.append(geometry.points()[0].values['temperature'])
                    nodes['configure'].native_geometry.points()[0].values['temperature'] = 42.
                    return geometry
                nodes['solver'].inputGeometry = input_geometry
                writes = trace_native_writes(stack, nodes)
                with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
                    host.readback(roles, {}, {'velocity_variance': 0.})
                self.assertEqual(refused.exception.code, 'RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED')
                self.assertTrue(returned_temperatures)
                self.assertEqual(returned_temperatures[0], 20.)
                self.assertTrue(all(value == 20. for value in returned_temperatures))
                self.assertEqual(nodes['configure'].native_geometry.points()[0].values['temperature'], 42.)
                self.assertEqual(writes, [])
                self.assertEqual(native_state(nodes), before)
                self.assertEqual(hou.frame(), 12.)

    def test_r05_second_wire_enumeration_stops_at_native_connection_limit(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                host, nodes, roles, hou, identity = fixed_fixture(version)
                carrier = nodes[program.ROLE]
                original_connections = carrier.inputConnections
                calls, yielded = [], {}
                def connections():
                    calls.append(True)
                    if len(calls) == 1:
                        return original_connections()
                    call_index = len(calls)
                    yielded[call_index] = 0
                    def values():
                        yielded[call_index] += 1
                        yield original_connections()[0]
                        for index in range(10000):
                            yielded[call_index] += 1
                            yield SimpleNamespace(inputIndex=lambda: 1, outputIndex=lambda: 0,
                                inputNode=lambda: nodes['configure'])
                    return values()
                carrier.inputConnections = connections
                before = native_state(nodes)
                writes = trace_native_writes(stack, nodes)
                with self.assertRaises(core.NativeFlipRbdDomainError) as refused:
                    host.observations({'velocity_variance': 0.}, roles, {}, task_seed=123)
                self.assertEqual(refused.exception.code, 'RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED')
                self.assertGreaterEqual(len(calls), 2)
                self.assertGreaterEqual(yielded[2], 2)
                self.assertLessEqual(yielded[2], 5)
                self.assertTrue(all(count <= 5 for count in yielded.values()))
                self.assertEqual(writes, [])
                self.assertEqual(native_state(nodes), before)
                self.assertEqual(hou.frame(), 12.)

    def test_fixed_zero_actual_addon_restore_keeps_legitimate_same_context_flow(self):
        for version in core.VERSIONS:
            with self.subTest(version=version), ExitStack() as stack:
                host, nodes, roles, hou, identity = fixed_fixture(version)
                before = native_state(nodes)
                original_velocity = copy.deepcopy(nodes['configure'].native_geometry.points()[0].values['v'])
                item = prepare_zero(host, nodes, roles, version)
                item['snapshot'] = dict(mode='value_only_compat', evaluated=item['parm'].value)
                item['parm'].eval = lambda: item['parm'].value
                self.assertEqual(host.write(item, roles, {})['after'], 0.)
                self.assertEqual(host.readback(roles, {}, {'velocity_variance': 0.})['controls'],
                                 {'velocity_variance': 0.})
                addon = load_actual_restore_addon(stack, host, hou, identity)
                addon._fx_restore_planned_item(item, roles, {})
                self.assertEqual(native_state(nodes), before)
                self.assertEqual(nodes[program.ROLE].geometryAtFrame(1).points()[0].values['v'], original_velocity)
                self.assertEqual(hou.frame(), 12.)
                self.assertEqual(addon._fx_rbd_velocity_host().write(
                    prepare_zero(host, nodes, roles, version), roles, {})['after'], 0.)


if __name__ == '__main__':
    unittest.main()
