"""Explicit captured HOM fixture; no Houdini, VEX or visual validation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from vfx_pipeline.workbuddy_assembly import software_host_client

ROOT = Path(__file__).resolve().parents[2]


def source_params(**changes):
    values={
        'emission_start_frame':('int',1),'emission_end_frame':('int',60),
        'direction':('vector3',[0,1,0]),'spread_angle_deg':('float',36.0),
        'speed_tier':('enum','fast'),'body_scale':('float',1.0),'ground_spread':('float',2.0),
        'protected_features':('string_list',['outline']),'roi':('vector4',[0,0,1,1]),
        'time_range':('frame_range',{'start':1,'end':180,'step':1}),
        'estimated_speed_magnitude':('float',5.0),'pulse_count':('int',2),
        'source_radius':('float',.5),'density':('float',1.2),'dissipation':('float',.4),
        'voxel_size':('float',.05),
    }
    for name,value in changes.items(): values[name]=(values[name][0],value)
    raw={'schema_version':'1.0','recipe_id':'reference_effect','objective_hash':'o'*64,
         'media_manifest_sha256':'m'*64,'ready':True,
         'controls':[{'name':name,'value_type':typ,'value':value} for name,(typ,value) in values.items()],
         'defaults':[],'missing_semantics':[]}
    inputs=[{'asset_id':'synthetic-ref','role':'reference','sha256':'a'*64}]
    return {'task_id':'abc123','inputs':inputs,'step_params':{
        'domain_pack':'pyro_smoke_v1','source_plan':raw,'source_controls':{key:value[1] for key,value in values.items()},
        'source_plan_sha256':canonical(raw),'source_input_binding_sha256':canonical(inputs)}}


def canonical(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False).encode()).hexdigest()


def load_boundary(filename):
    spec = importlib.util.spec_from_file_location(filename, ROOT / 'tools' / (filename + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSourceHost:
    def __init__(self, addon, pack_override=None, *, pack_id='pyro_smoke_v1', version='21.0.631'):
        self.addon = addon
        self.pack_override = pack_override
        self.pack_id = pack_id
        self.version = version
        self.calls = []
        self.initial_values = {}
        self.stack = ExitStack()

    def __enter__(self):
        try:
            temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='FAKE_HOST_source_')))
            self.state_path = temp / 'state.json'
            self.stack.enter_context(patch.dict(sys.modules))
            self.stack.enter_context(patch.dict(os.environ, {
                'HOUDINI_BRIDGE_STATE_DIR': str(temp / 'houdini'),
                'BRIDGE_SKILLS_STATE_ROOT': str(temp / 'installation'),
                'BRIDGE_SKILLS_SCHEDULER_ROOT': str(temp / 'scheduler'),
            }))
            software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', temp / 'client')
            self.hou = sys.modules['hou']
            self.native = load_boundary('native_schema_test_boundary')
            api = load_boundary('software_render_api_boundary')
            schema = ROOT / 'docs/native-basis/hda-interface-capture.json'
            self.catalog = self.native.capture_catalog(schema, self.version)
            interfaces, states, ports = api.interface_profiles(ROOT, self.version)
            with patch.object(self.native, 'capture_catalog', return_value=self.catalog):
                self.native.constrain_hou(schema, self.version, instance_states=states,
                    native_api_interfaces=interfaces, native_api_ports=ports)
            api.install_stage_api(self.hou)
            self.parm_class = self.hou._native_schema_parm_class
            node_class = type(self.hou.node('/obj'))
            original_set = self.parm_class.set
            original_set_keys = self.parm_class.setKeyframes
            original_create = node_class.createNode

            def set_value(parm, value, **kwargs):
                self.calls.append(('set', parm.path(), value, kwargs))
                return original_set(parm, getattr(parm, 'transform', lambda item: item)(value), **kwargs)

            def create_node(parent, native, name, **kwargs):
                node = original_create(parent, native, name, **kwargs)
                self.calls.append(('createNode', native, node.path()))
                for parm_name in ('disturbance', 'turbulence', 'shredding', 'numsources'):
                    parm = node.parm(parm_name)
                    if parm is not None:
                        self.initial_values[(node.path(), parm_name)] = parm.eval()
                return node

            def set_keyframes(parm, keys):
                merged = {key.frame(): key for key in parm.keyframes()}
                merged.update({key.frame(): key for key in keys})
                return original_set_keys(parm, [merged[frame] for frame in sorted(merged)])

            self.stack.enter_context(patch.object(self.parm_class, 'set', set_value))
            self.stack.enter_context(patch.object(self.parm_class, 'setKeyframes', set_keyframes))
            self.stack.enter_context(patch.object(node_class, 'createNode', create_node))
            for method in ('setInput', 'setDisplayFlag', 'setRenderFlag', 'cook'):
                original = getattr(node_class, method)

                def record(node, *args, _method=method, _original=original, **kwargs):
                    recorded = tuple(item.path() if hasattr(item, 'path') else item for item in args)
                    if _method == 'setInput' and len(recorded) == 2:
                        recorded += (0,)
                    self.calls.append((_method, node.path(), *recorded))
                    return _original(node, *args, **kwargs)

                self.stack.enter_context(patch.object(node_class, method, record))
            if self.pack_override is not None:
                self.stack.enter_context(patch.dict(self.addon._FX_PACKS, {self.pack_id: self.pack_override}))
            self.stack.enter_context(patch.object(self.addon, '_state_dir', return_value=temp / 'instances'))
            self.stack.enter_context(patch.object(self.addon, '_fx_state_path', return_value=self.state_path))
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    @property
    def nodes(self):
        return {node.path(): node for root in ('/', '/obj', '/stage', '/mat')
                for parent in [self.hou.node(root)] if parent is not None
                for node in (parent, *parent.allSubChildren())}

    def build(self, params=None):
        return self.addon.dispatch('agent.fx.build_preview', params or source_params())

    def manifest(self):
        return json.loads(self.state_path.read_text())

    def put_cache(self):
        root, manifest = self.addon._fx_manifest('abc123')
        manifest['cache'] = {'subject_hash': 'synthetic_old_cache'}
        self.addon._fx_store_manifest(root, manifest)

    def role(self, name):
        return self.hou.node(self.manifest()['nodes'][name])

    def writes(self):
        return [call for call in self.calls if call[0] in {
            'createNode', 'setInput', 'set', 'setDisplayFlag', 'setRenderFlag'}]
