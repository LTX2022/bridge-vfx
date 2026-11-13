"""Bound native Root OCIO setup; enum readback alone cannot add a LUT."""
from pathlib import Path
import hashlib
import json
import os
import secrets
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from nuke_bridge.task_host_worker import _root_ocio, _controlled_root_color


class Root:
    def __init__(self):
        self.values={'colorManagement':'Nuke','OCIO_config':'nuke-default',
                     'customOCIOConfigPath':'','workingSpaceLUT':'linear'}
        self.writes=[];self.unavailable=False;self.clamp=None
    def knob(self, name):
        menus={'colorManagement':['Nuke','OCIO'],'OCIO_config':['nuke-default','custom']}
        def values():
            if name=='workingSpaceLUT':
                return ['ACEScg'] if (self.values['colorManagement']=='OCIO' and self.values['OCIO_config']=='custom' and self.values['customOCIOConfigPath'] and not self.unavailable) else ['linear']
            return menus[name]
        def set_value(value):
            self.writes.append((name,value))
            if self.clamp!=name:self.values[name]=value
        return SimpleNamespace(value=lambda:self.values[name],values=values,setValue=set_value)


class ProjectOcioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=(Path(self.temp.name)/'config.ocio').resolve();p.write_text('frozen native configuration fixture')
        self.record={'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        self.root=Root();self.nuke=SimpleNamespace(root=lambda:self.root,
            getOcioColorSpaces=lambda: [] if self.root.unavailable else ['ACEScg'])

    def test_configuration_order_and_cold_readback_do_not_append_missing_colorspace(self):
        expected=_root_ocio(self.nuke,self.record,'ACEScg',configure=True)
        self.assertEqual([n for n,v in self.root.writes],['colorManagement','OCIO_config','customOCIOConfigPath','workingSpaceLUT'])
        writes=list(self.root.writes)
        self.assertEqual(_root_ocio(self.nuke,self.record,'ACEScg',configure=False),expected)
        self.assertEqual(self.root.writes,writes)
        self.root.values['colorManagement']='Nuke'
        with self.assertRaisesRegex(ValueError,'READBACK_MISMATCH'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=False)
        self.assertEqual(self.root.writes,writes)

    def test_configuration_drift_is_rejected_before_native_mutation(self):
        Path(self.record['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'CONFIG_CHANGED'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=True)
        self.assertEqual(self.root.writes,[])

    def test_unavailable_menu_and_native_clamp_are_rejected(self):
        self.root.unavailable=True
        with self.assertRaisesRegex(ValueError,'MENU_UNAVAILABLE: workingSpaceLUT'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=True)
        self.assertFalse(any(n=='workingSpaceLUT' for n,v in self.root.writes))
        self.root.clamp='colorManagement';self.root.values['colorManagement']='Nuke'
        with self.assertRaisesRegex(ValueError,'READBACK_MISMATCH: colorManagement'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=True)

    def test_legacy_and_explicit_software_hosts_keep_existing_color_behavior(self):
        self.assertIsNone(_controlled_root_color(None,{},configure=True))
        self.assertIsNone(_controlled_root_color(None,{'software_api':True,'resource_budget':{'native_scope':{}}},configure=True))

    def test_cold_worker_rejects_missing_menu_with_all_strings_matching_before_execute(self):
        from nuke_bridge import owned_render_worker as worker
        from dcc_task_runtime import native_scope
        # Prepared, non-executable accounting fixture; only native Nuke API is
        # substituted. It never admits a process or creates native evidence.
        root=Path(self.temp.name).resolve()
        key=secrets.token_bytes(32)
        scope={'schema':'bridge.engineering-closure-scope/1','output_root':str(root),
            'budget':dict(native_scope._BUDGET),'status':'PREPARED_NOT_AUTHORIZED',
            'execution_authorized':False,'evidence_source':'real_host',
            'native_color_tokens':{'houdini_static_config':self.record},
            'project_color':{'colorspace':'ACEScg'},
            'accounting':{'key_path':str(root/'.native-control/key'),
                'key_sha256':hashlib.sha256(key).hexdigest()}}
        scope_path=root/'scope.json';scope_path.write_text(json.dumps(scope))
        binding={'path':str(scope_path),'sha256':hashlib.sha256(scope_path.read_bytes()).hexdigest()}
        native_scope.NativeScope.initialize(binding,key=key)
        config=root/'launch.json';config.write_text(json.dumps({'software_api':False,
            'resource_budget':{'native_scope':binding}}))
        snapshot=root/'composite.nk';snapshot.write_text('Root {}')
        expected=_root_ocio(self.nuke,self.record,'ACEScg',configure=True)
        self.assertEqual(self.root.values,expected)
        self.root.unavailable=True
        calls=[]
        self.nuke.scriptOpen=lambda path:calls.append(('scriptOpen',path))
        self.nuke.execute=lambda *args:calls.append(('execute',args))
        env={'BRIDGE_NUKE_HOST_CONFIG':str(config),
             'BRIDGE_NUKE_HOST_CONFIG_SHA256':hashlib.sha256(config.read_bytes()).hexdigest()}
        writes=list(self.root.writes)
        with patch.dict(os.environ,env),patch.object(worker,'_load_nuke_api',return_value=self.nuke):
            with self.assertRaisesRegex(ValueError,'MENU_UNAVAILABLE: workingSpaceLUT'):
                worker.main(['worker',str(snapshot),'Write1','1','1',str(root/'out.%04d.exr'),'[1]'])
        self.assertEqual(calls,[('scriptOpen',str(snapshot))])
        self.assertEqual(self.root.writes,writes)
        self.assertEqual(native_scope.NativeScope(binding).snapshot()['dcc_starts'],0)

    def test_worker_rejects_changed_inherited_host_config(self):
        from nuke_bridge.owned_render_worker import _verify_project_root
        config=Path(self.temp.name).resolve()/'launch.json';config.write_text('{}')
        with patch.dict(os.environ,{'BRIDGE_NUKE_HOST_CONFIG':str(config),
                                   'BRIDGE_NUKE_HOST_CONFIG_SHA256':'0'*64}):
            with self.assertRaisesRegex(ValueError,'HOST_CONFIG_CHANGED'):
                _verify_project_root(self.nuke)

    def test_canonical_ocio_catalog_is_independent_of_lut_ui_labels(self):
        original=self.root.knob
        def labeled(name):
            knob=original(name)
            if name=='workingSpaceLUT':knob.values=lambda:['a grouped UI label']
            return knob
        self.root.knob=labeled
        expected=_root_ocio(self.nuke,self.record,'ACEScg',configure=True)
        self.assertEqual(expected['workingSpaceLUT'],'ACEScg')
        self.assertEqual(_root_ocio(self.nuke,self.record,'ACEScg',configure=False),expected)
        self.root.unavailable=True
        with self.assertRaisesRegex(ValueError,'MENU_UNAVAILABLE: workingSpaceLUT'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=False)

    def test_native17_tab_fields_use_only_canonical_name(self):
        self.nuke.getOcioColorSpaces=lambda:[
            'scene_linear\tscene_linear (Linear Rec.709 (sRGB))',
            'ACEScg\tColorspaces/ACES/ACEScg\t\tACES - ACEScg,lin_ap1']
        expected=_root_ocio(self.nuke,self.record,'ACEScg',configure=True)
        self.assertEqual(_root_ocio(self.nuke,self.record,'ACEScg',configure=False),expected)
        self.nuke.getOcioColorSpaces=lambda:['Other\tColorspaces/ACES/ACEScg\t\tACEScg']
        with self.assertRaisesRegex(ValueError,'MENU_UNAVAILABLE: workingSpaceLUT'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=False)
        self.nuke.getOcioColorSpaces=lambda:[object()]
        with self.assertRaisesRegex(ValueError,'CATALOG_INVALID'):
            _root_ocio(self.nuke,self.record,'ACEScg',configure=False)
