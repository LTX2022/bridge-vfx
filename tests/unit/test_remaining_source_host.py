"""F2 behavioral native-adapter tests, only explicit synthetic fake HOM.

The code under test starts at add-on.dispatch. No private helper is used as an
alternative successful path; getters/oracles inspect what was actually written.
"""
from __future__ import annotations
import json
import math
import re
import unittest
from test_houdini_parm_probe import _load_addon
from source_host_fixture import FakeSourceHost, source_params, canonical


def written_intervals(program):
    return [(int(a),int(b)) for a,b in re.findall(r'\(@Frame >= (\d+) && @Frame < (\d+)\)',program)]


def gates_at(program,frames):
    intervals=written_intervals(program)
    return [any(a<=frame<b for a,b in intervals) for frame in frames]


class NativeSourceBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.addon=_load_addon()

    def test_changed_start_end_writes_different_host_program_and_invalidates_cache(self):
        with FakeSourceHost(self.addon) as host:
            initial=host.build(source_params(pulse_count=1))
            program=host.role('source_control').parm('snippet').eval()
            self.assertEqual(written_intervals(program),[(1,61)])
            self.assertEqual(gates_at(program,[0,1,60,60.5,61,80,100,101]),[False,True,True,True,False,False,False,False])
            host.put_cache();before=len(host.writes())
            changed=host.build(source_params(pulse_count=1,emission_start_frame=80,emission_end_frame=100))
            newer=host.role('source_control').parm('snippet').eval()
            self.assertNotEqual(program,newer)
            self.assertEqual(written_intervals(newer),[(80,101)])
            self.assertEqual(gates_at(newer,[1,60,79,80,100,100.5,101]),[False,False,False,True,True,True,False])
            writes=host.writes()[before:]
            self.assertTrue(any(call[0]=='set' and call[1].endswith('/snippet') and call[2]==newer for call in writes))
            self.assertTrue(changed['scene_manifest']['source_plan_cache_invalidated'])
            self.assertNotIn('cache',changed['scene_manifest'])
            self.assertEqual(changed['visual_validation'],'INCONCLUSIVE')
            self.assertFalse(changed['real_execution_validated'])
            self.assertFalse(changed['scene_manifest']['execution_assessment']['simulation_executed'])
            self.assertFalse(any(call[0]=='cook' and call[1].endswith(('FX_SOLVER','FX_OUTPUT')) for call in host.calls))

    def test_pulses_are_disjoint_source_on_off_bands_not_shredding(self):
        with FakeSourceHost(self.addon) as host:
            host.build(source_params(pulse_count=3,emission_start_frame=10,emission_end_frame=19))
            program=host.role('source_control').parm('snippet').eval()
            self.assertEqual(written_intervals(program),[(10,12),(14,16),(18,20)])
            self.assertEqual(gates_at(program,range(9,21)),[False,True,True,False,False,True,True,False,False,True,True,False])
            solver=host.role('solver')
            self.assertEqual(solver.parm('shredding').eval(),host.initial_values[(solver.path(),'shredding')])
            self.assertFalse(any(call[0]=='set' and call[1].endswith('/shredding') for call in host.calls))

    def test_direction_speed_cone_bind_real_velocity_code_and_leave_noise_untouched(self):
        with FakeSourceHost(self.addon) as host:
            host.build(source_params(direction=[1,0,0],spread_angle_deg=60.0,speed_tier='medium',estimated_speed_magnitude=2.5))
            control=host.role('source_control')
            program=control.parm('snippet').eval()
            self.assertIn('vector axis = set(1, 0, 0);',program)
            self.assertIn('v@v = active * 2.5 * velocity_direction;',program)
            half_angle=float(re.search(r'float cone_cos = .*cos\(([^)]+)\)',program).group(1))
            self.assertAlmostEqual(half_angle,math.pi/6)
            # Independent cone oracle, not Houdini/VEX execution.
            for u in (0,.25,.5,1):
                c=1-u*(1-math.cos(half_angle));s=math.sqrt(1-c*c)
                self.assertAlmostEqual(math.hypot(2.5*c,2.5*s),2.5)
                self.assertLessEqual(math.acos(c),math.pi/6+1e-12)
            self.assertEqual(control.parm('class').evalAsString(),'point')
            self.assertEqual(host.role('source_points').parm('mode').eval(),2)
            self.assertEqual(host.role('source_volume').parm('attributes').eval(),'density v')
            self.assertIn('f@density = active * 1.2;',program)
            for name in ('disturbance','turbulence','shredding'):
                self.assertFalse(any(call[0]=='set' and call[1].endswith('/'+name) for call in host.calls))
            host.put_cache()
            host.build(source_params(direction=[0,0,-1],spread_angle_deg=0.0,speed_tier='slow',estimated_speed_magnitude=1.0))
            self.assertNotIn('cache',host.manifest())
            self.assertIn('vector axis = set(0, 0, -1);',control.parm('snippet').eval())
            self.assertIn('v@v = active * 1 * velocity_direction;',control.parm('snippet').eval())

    def test_native_missing_parameter_menu_or_node_refused_before_any_mutation(self):
        for missing in ('node','parameter','menu'):
            with self.subTest(missing=missing),FakeSourceHost(self.addon) as host:
                if missing=='node': del host.catalog[('Sop','volumerasterizeattributes')]
                elif missing=='parameter':
                    del host.catalog[('Sop','attribwrangle')]['parameters']['snippet']
                else:
                    host.catalog[('Sop','pyrosource')]['parameters']['mode']['menu_tokens']=['unknown','UNKNOWN']
                with self.assertRaises(self.addon.BridgeCommandError) as caught: host.build()
                self.assertIn(caught.exception.code,{'UNSUPPORTED_NODE','UNSUPPORTED_SOURCE_CONTROL'})
                self.assertEqual(host.writes(),[])
                self.assertFalse(host.state_path.exists())

    def test_driven_and_locked_source_program_fail_before_writes_or_reconnection(self):
        for guard in ('driven','locked'):
            with self.subTest(guard=guard),FakeSourceHost(self.addon) as host:
                host.build();host.put_cache()
                parm=host.role('source_control').parm('snippet')
                if guard=='driven':
                    driver=host.native.Keyframe(parm.eval())
                    driver.setFrame(host.hou.frame())
                    host.native.set_parm_state(parm,keyframes=[driver])
                else: host.native.set_parm_state(parm,locked=True)
                before=len(host.writes());original=host.state_path.read_bytes()
                with self.assertRaises(self.addon.BridgeCommandError) as caught:
                    host.build(source_params(emission_start_frame=80,emission_end_frame=100))
                self.assertIn(caught.exception.code,{'PARAMETER_STATE_UNSUPPORTED','PARAMETER_LOCKED'})
                self.assertEqual(len(host.writes()),before)
                self.assertEqual(host.state_path.read_bytes(),original)

    def test_readback_failure_rolls_back_entire_source_write_set_and_keeps_old_manifest(self):
        with FakeSourceHost(self.addon) as host:
            host.build();host.put_cache();original=host.state_path.read_bytes()
            source=host.role('source_control');old_program=source.parm('snippet').eval()
            radii=host.role('source').parmTuple('rad').eval()
            voxel=host.role('solver').parm('divsize').eval()
            parm=source.parm('snippet')
            parm.transform=lambda value:'coerced_invalid_program' if isinstance(value,str) and '@Frame >= 80' in value else value
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                host.build(source_params(emission_start_frame=80,emission_end_frame=100,voxel_size=.06,body_scale=1.1))
            self.assertEqual(caught.exception.code,'PARAMETER_READBACK_MISMATCH')
            self.assertEqual(source.parm('snippet').eval(),old_program)
            self.assertEqual(host.role('source').parmTuple('rad').eval(),radii)
            self.assertEqual(host.role('solver').parm('divsize').eval(),voxel)
            self.assertEqual(host.state_path.read_bytes(),original)

    def test_unknown_control_invalid_timing_zero_direction_and_resource_bound_refused_before_writes(self):
        cases=[source_params(direction=[0,0,0]),source_params(pulse_count=3,emission_end_frame=2),
            source_params(emission_end_frame=200),source_params(body_scale=100.0)]
        extra=source_params();raw=extra['step_params']['source_plan']
        raw['controls'].append({'name':'source_script','value_type':'text','value':'UNTRUSTED_SCRIPT'})
        extra['step_params']['source_controls']['source_script']='UNTRUSTED_SCRIPT'
        extra['step_params']['source_plan_sha256']=canonical(raw);cases.append(extra)
        for index,params in enumerate(cases):
            with self.subTest(index=index),FakeSourceHost(self.addon) as host:
                with self.assertRaises(self.addon.BridgeCommandError): host.build(params)
                self.assertEqual(host.writes(),[])

    def test_unchanged_host_program_reuses_topology_and_keeps_valid_cache(self):
        with FakeSourceHost(self.addon) as host:
            host.build();host.put_cache()
            creates=[call for call in host.calls if call[0]=='createNode']
            result=host.build()
            self.assertEqual([call for call in host.calls if call[0]=='createNode'],creates)
            self.assertIn('cache',result['scene_manifest'])
            self.assertEqual(result['scene_manifest']['source_plan_invalidates_from'],[])
            self.assertFalse(result['scene_manifest']['source_plan_cache_invalidated'])
            self.assertTrue(all(row['readback_verified'] for row in result['scene_manifest']['source_plan_host_readback'].values()))

    def test_late_callback_drift_rolls_back_complete_write_set(self):
        with FakeSourceHost(self.addon) as host:
            host.build();host.put_cache();original=host.state_path.read_bytes()
            control=host.role('source_control').parm('snippet')
            old_program=control.eval()
            voxel=host.role('source_volume').parm('voxelsize')
            def corrupt_earlier(value):
                if value==.06:control.value='FAKE_CALLBACK_DRIFT'
                return value
            voxel.transform=corrupt_earlier
            with self.assertRaises(self.addon.BridgeCommandError) as caught:
                host.build(source_params(voxel_size=.06,emission_start_frame=80,emission_end_frame=100))
            self.assertEqual(caught.exception.code,'PARAMETER_READBACK_MISMATCH')
            self.assertEqual(control.eval(),old_program)
            self.assertEqual(host.state_path.read_bytes(),original)

    def test_manifest_cannot_redirect_source_writes_outside_owned_root(self):
        with FakeSourceHost(self.addon) as host:
            host.build()
            outside=host.nodes['/obj'].createNode('geo','unowned_external').createNode('attribwrangle','control')
            root,manifest=self.addon._fx_manifest('abc123')
            manifest['nodes']['source_control']=outside.path()
            self.addon._fx_store_manifest(root,manifest)
            count=len(host.writes());original=host.state_path.read_bytes()
            with self.assertRaises(self.addon.BridgeCommandError) as caught:host.build()
            self.assertEqual(caught.exception.code,'SCENE_CONFLICT')
            self.assertEqual(len(host.writes()),count)
            self.assertEqual(host.state_path.read_bytes(),original)
            self.assertEqual(outside.parm('snippet').eval(),'')
