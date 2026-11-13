from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import unittest

from houdini_bridge import native_pyro_domains as plans
from houdini_bridge.domain_packs import DOMAIN_PACKS

ROOT = Path(__file__).resolve().parents[2]
SOURCE = {'emission_windows':[(1, 4), (9, 12)], 'direction':[0, 1, 0],
          'spread':30, 'speed':2, 'particle_separation':.1}


class NativePyroPlanTests(unittest.TestCase):
    def test_all_existing_controls_refuse_untyped_readback_and_incomplete_runtime(self):
        version = '21.0.631'
        for domain in (plans.SMOKE, plans.FIRE):
            for name, control in plans.control_contract(domain, version).items():
                if control['native_status'] != 'mapped' or name == 'flame_height':
                    continue
                with self.subTest(domain=domain, control=name):
                    with self.assertRaisesRegex(plans.NativePyroDomainError, 'READBACK_REQUIRED'):
                        plans.control_readback(domain, name, {}, version)
        for name, values in (
            ('source_scale', {('source', 'rad'): [1, True, 1]}),
            ('voxel_size', {('solver', 'divsize'): 1, ('source_volume', 'voxelsize'): True}),
            ('volume_samples', {('render_settings', 'varianceaa_minsamples'): True,
                ('render_settings', 'varianceaa_maxsamples'): 1, ('render_settings', 'volumequality'): 3}),
        ):
            with self.assertRaises(plans.NativePyroDomainError):
                plans.control_readback(plans.SMOKE, name, values, version)
        writes = plans.control_write_plan(plans.FIRE, 'fuel_rate', 2, version)
        observed = {('solver', 'source_vscale3'): {'origin': 'runtime_hom', 'type': 'float',
            'size': 1, 'locked': False, 'disabled': False, 'hidden': False, 'driven': False}}
        for role, name, value in writes[0]['required_gates']:
            observed[role, name] = {'origin': 'runtime_hom', 'value': value}
        observed['solver', 'source_activate3']['value'] = True
        with self.assertRaisesRegex(plans.NativePyroDomainError, 'GATE_BLOCKED'):
            plans.validate_control_write_plan(writes, observed)

    def test_original_vendor_archives_match_frozen_source_hashes(self):
        metadata = json.loads((ROOT/'docs/native-basis/native-boundary-metadata-supplement.json').read_text(encoding='utf-8'))
        missing = set()
        for version in plans.SUPPORTED_VERSIONS:
            operators = metadata['versions'][version]['operators']
            for operator in ('Sop/pyrosolver', 'Sop/pyrosource', 'Sop/volumerasterizeattributes', 'Lop/karmarendersettings'):
                with self.subTest(version=version, operator=operator):
                    native = operators[operator]
                    self.assertEqual(native['status'], 'CAPTURED')
                    path = Path(native['source']['path'])
                    if not path.is_file():
                        missing.add(str(path))
                        continue
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), native['source']['file_sha256'])
        if missing:
            self.skipTest('NOT_RUN: original vendor archives unavailable: ' + '; '.join(sorted(missing)))

    def test_both_version_hda_fields_menus_types_and_allocation_are_real(self):
        metadata = json.loads((ROOT/'docs/native-basis/native-boundary-metadata-supplement.json').read_text(encoding='utf-8'))
        role_ops = {'solver':'Sop/pyrosolver', 'source_points':'Sop/pyrosource',
                    'source_volume':'Sop/volumerasterizeattributes'}
        for version in plans.SUPPORTED_VERSIONS:
            operators = metadata['versions'][version]['operators']
            for operator in role_ops.values():
                fact = operators[operator]
                self.assertEqual(fact['status'],'CAPTURED')
            for pack in (plans.SMOKE, plans.FIRE):
                with self.subTest(version=version, pack=pack):
                    for node in plans.node_requirements(pack,version):
                        if node['role'] in role_ops:
                            fields = operators[role_ops[node['role']]]['parameters']
                            for aliases in node['required_parms']:
                                self.assertTrue(any(p in fields or re.sub(r'\d+$','#',p) in fields for p in aliases), aliases)
                    writes = plans.trusted_initialization_plan(pack,version,SOURCE)
                    allocated = set()
                    for write in writes:
                        if write['role'] not in role_ops:
                            continue
                        fields = operators[role_ops[write['role']]]['parameters']
                        name = write['parm']
                        template = name if name in fields else re.sub(r'\d+$','#',name)
                        self.assertIn(template, fields)
                        native = fields[template]
                        kind = write['native_type']
                        self.assertEqual('toggle' if kind == 'keyframes' else kind,native['type'])
                        if kind == 'ordinal':
                            self.assertIn(write['value'],native['menu_tokens'][::2])
                        if kind == 'multiparm':
                            allocated.add((write['role'],name))
                        if '#' in template:
                            parent = 'attributes' if write['role']=='source_points' else 'numfields' if name.startswith('export_') else 'numsources'
                            self.assertIn((write['role'],parent),allocated)
                    values = {(w['role'],w['parm']):w['value'] for w in writes if w['native_type']!='keyframes'}
                    exports = [v for (role,name),v in values.items() if role=='solver' and name.startswith('export_fieldname')]
                    self.assertEqual(set(exports), {'density','temperature','vel'} | ({'flame'} if pack==plans.FIRE else set()))
                    self.assertEqual(values[('solver','conv_vdb')],0)
                    for row in (3 if pack==plans.SMOKE else 4,):
                        norm = next(i for i,w in enumerate(writes) if w['parm']==f'source_vnormalize{row}')
                        copy_mode = next(i for i,w in enumerate(writes) if w['parm']==f'source_voperator{row}' and w['value']=='copy')
                        self.assertLess(norm,copy_mode)
                        self.assertEqual(writes[norm]['value'],0)

    def test_overlay_preserves_every_public_control_and_source_topology(self):
        for pack in DOMAIN_PACKS:
            if pack.identifier not in (plans.SMOKE,plans.FIRE):
                continue
            original = pack.to_dict(); frozen=copy.deepcopy(original)
            for version in plans.SUPPORTED_VERSIONS:
                updated = plans.overlay_core_pack_dict(original,version)
                self.assertEqual(original,frozen)
                self.assertEqual({c['id'] for c in updated['controls']},{c.identifier for c in pack.controls})
                by_role = {n['role']:n for n in updated['nodes']}
                self.assertEqual(by_role['solver']['input_role'],'source_volume')
                self.assertEqual(by_role['source_volume']['input_role'],'source_control')
                self.assertEqual(by_role['source_control']['input_role'],'source_points')
                self.assertEqual(by_role['source_points']['input_role'],'source')
                self.assertEqual(by_role['solver']['type_candidates'],['pyrosolver'])
                self.assertNotIn({'source_role':'source','source_output':0,'destination_role':'solver','destination_input':0},updated['connections'])
                if pack.identifier==plans.SMOKE:
                    self.assertEqual(by_role['render_settings'], next(n for n in frozen['nodes'] if n['role']=='render_settings'))
            host={'nodes':[{'role':'source','types':['sphere']},{'role':'solver','types':['pyrosolver']},{'role':'output','types':['null']}],
                  'controls':{c.identifier:{} for c in pack.controls}}
            self.assertEqual(set(plans.overlay_host_pack(pack.identifier,host,'21.0.631')['controls']),set(host['controls']))
            host['controls'].pop(next(iter(host['controls'])))
            with self.assertRaisesRegex(plans.NativePyroDomainError,'PUBLIC_CONTROL_CONTRACT_CHANGED'):
                plans.overlay_host_pack(pack.identifier,host,'21.0.631')

    def test_source_program_is_trusted_numeric_mask_with_nonzero_fire_attributes(self):
        for version in plans.SUPPORTED_VERSIONS:
            for pack in (plans.SMOKE,plans.FIRE):
                registration=plans.source_program(pack,version,SOURCE)
                program=registration['program']
                self.assertEqual(registration['sha256'],hashlib.sha256(program.encode()).hexdigest())
                self.assertIn('@Frame >= 1 && @Frame < 5',program)
                self.assertIn('@Frame >= 9 && @Frame < 13',program)
                self.assertNotIn('f@fuel = 0',program)
                writes=plans.trusted_initialization_plan(pack,version,SOURCE)
                vals={(w['role'],w['parm']):w['value'] for w in writes if w['native_type']!='keyframes'}
                if pack==plans.FIRE:
                    self.assertGreater(vals[('source_points','fval2')],0)
                    self.assertGreater(vals[('source_points','fval3')],0)
                    self.assertIn('f@flame = f@burn',program)
                    self.assertIn('burn flame',vals[('source_volume','attributes')])
                    self.assertEqual(vals[('solver','source_volume3')],'flame')
                    self.assertEqual(vals[('solver','source_vfield3')],'flame')
                    self.assertEqual(vals[('solver','source_vnormalize3')],1)
        schedule=plans.activation_schedule(SOURCE)
        self.assertEqual([(k['frame'],k['value']) for k in schedule],[(0,0),(1,1),(5,0),(9,1),(13,0)])
        self.assertTrue(all(k['interpolation']=='constant' for k in schedule))
        long=plans.activation_schedule({**SOURCE,'emission_windows':[(1,1000000)]})
        self.assertEqual(len(long),3)
        for changed in ({**SOURCE,'snippet':'arbitrary'}, {**SOURCE,'speed':'1; arbitrary'},
                        {**SOURCE,'direction':[0,0,0]}, {**SOURCE,'emission_windows':[(1,4),(3,7)]}):
            with self.assertRaises(plans.NativePyroDomainError):
                plans.source_program(plans.FIRE,'21.0.631',changed)

    def test_unit_conversions_synchronized_voxels_and_precise_unavailable_semantics(self):
        v='21.0.631'
        for name,pack,value in [('burn_rate',plans.FIRE,2),('burn_rate',plans.FIRE,1e-10),('source_scale',plans.SMOKE,.5),('voxel_size',plans.SMOKE,.2),('field_sharpen',plans.SMOKE,3),('volume_samples',plans.SMOKE,7)]:
            writes=plans.control_write_plan(pack,name,value,v)
            observations={(w['role'],w['parm']):w['value'] for w in writes}
            self.assertAlmostEqual(plans.control_readback(pack,name,observations,v),value)
        self.assertEqual(plans.control_write_plan(plans.FIRE,'burn_rate',2,v)[0]['value'],.5)
        with self.assertRaisesRegex(plans.NativePyroDomainError,'INVALID_NATIVE_CONTROL_VALUE'):
            plans.control_write_plan(plans.FIRE,'burn_rate',1e-320,v)
        identity=plans.control_write_plan(plans.SMOKE,'field_sharpen',0,v)
        taps=[x for w in identity for x in w['value']]
        self.assertEqual(sum(taps),1)
        self.assertEqual(sum(x!=0 for x in taps),1)
        taps=[x for w in plans.control_write_plan(plans.SMOKE,'field_sharpen',3,v) for x in w['value']]
        self.assertAlmostEqual(sum(taps),1)
        for pack,name,value,reason in [(plans.FIRE,'burn_rate',0,'ZERO_FLAME_DEPLETION'),
            (plans.FIRE,'flame_height',3,'PYRO_HEIGHT_BASIS_REQUIRED'),
            (plans.FIRE,'glow_amount',1,'EXTERNAL_NUKE_CONTROL')]:
            with self.assertRaisesRegex(plans.NativePyroDomainError,reason):
                plans.control_write_plan(pack,name,value,v)
        with self.assertRaisesRegex(plans.NativePyroDomainError,'READBACK_MISMATCH'):
            plans.control_readback(plans.SMOKE,'voxel_size',{('solver','divsize'):.1,('source_volume','voxelsize'):.2},v)

    def test_normalized_volume_samples_joint_plan_rejects_existing_base_and_xpu(self):
        for version in plans.SUPPORTED_VERSIONS:
            metadata=json.loads((ROOT/'docs/native-basis/native-boundary-metadata-supplement.json').read_text(encoding='utf-8'))
            native=metadata['versions'][version]['operators']['Lop/karmarendersettings']
            self.assertEqual(native['status'], 'CAPTURED')
            fields=native['parameters']
            for w in plans.volume_sampling_initialization_plan(version):
                self.assertEqual(w['native_type'],fields[w['parm']]['type'])
            self.assertIn('convergence_mode != Variance',fields['varianceaa_minsamples']['disable_when'])
            writes=plans.control_write_plan(plans.SMOKE,'volume_samples',7,version)
            for w in writes:
                self.assertEqual(w['native_type'],fields[w['parm']]['type'])
            self.assertEqual([(w['parm'],w['value']) for w in writes],
                             [('varianceaa_minsamples',1),('varianceaa_maxsamples',1),('volumequality',7.)])
            observed={}
            for w in writes:
                observed[(w['role'],w['parm'])]={'origin':'runtime_hom','type':w['native_type'],'size':1,
                    'locked':False,'disabled':False,'hidden':False,'driven':False,'value':w['value']}
            observed[('render_settings','engine')]={'origin':'runtime_hom','value':'cpu'}
            observed[('render_settings','convergence_mode')]={'origin':'runtime_hom','value':'Variance'}
            plans.validate_control_write_plan(writes,observed)
            for parm,value in [('engine','xpu'),('convergence_mode','Path Traced'),('varianceaa_minsamples',2),('varianceaa_maxsamples',9)]:
                changed=copy.deepcopy(observed); changed[('render_settings',parm)]['value']=value
                with self.assertRaisesRegex(plans.NativePyroDomainError,'GATE_BLOCKED'):
                    plans.validate_control_write_plan(writes,changed)
            with self.assertRaisesRegex(plans.NativePyroDomainError,'BASE_NOT_NORMALIZED'):
                plans.control_readback(plans.SMOKE,'volume_samples',
                    {('render_settings','varianceaa_minsamples'):2,('render_settings','varianceaa_maxsamples'):9,
                     ('render_settings','volumequality'):7.},version)
            self.assertEqual([w['value'] for w in plans.volume_sampling_initialization_plan(version)],['cpu','Variance',1,1])

    def test_candidate_preflight_requires_actual_gates_types_and_no_driven_channels(self):
        writes=plans.control_write_plan(plans.FIRE,'fuel_rate',2,'21.0.631')
        observed={('solver','source_vscale3'):{'origin':'runtime_hom','type':'float','size':1,'locked':False,'disabled':False,'hidden':False,'driven':False}}
        for role,parm,value in writes[0]['required_gates']:
            observed[(role,parm)]={'origin':'runtime_hom','value':value}
        plans.validate_control_write_plan(writes,observed)
        for field in ('locked','disabled','hidden','driven','type','origin'):
            changed=copy.deepcopy(observed)
            changed[('solver','source_vscale3')][field]=True if field not in ('type','origin') else 'unknown'
            with self.assertRaises(plans.NativePyroDomainError):
                plans.validate_control_write_plan(writes,changed)
        changed=copy.deepcopy(observed); changed[('solver','source_activate3')]['value']=0
        with self.assertRaisesRegex(plans.NativePyroDomainError,'GATE_BLOCKED'):
            plans.validate_control_write_plan(writes,changed)
        with self.assertRaisesRegex(plans.NativePyroDomainError,'INTERFACE_REQUIRED'):
            plans.validate_control_write_plan(writes,{})


if __name__=='__main__':
    unittest.main()
