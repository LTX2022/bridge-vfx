"""Bounded H21 data capture/reconstruction helpers; importing starts no DCC.

Only trusted workers call the HOM functions. Captured expressions/templates are
never evaluated as Python by this module or replayed as executable source.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path

from .official_karma import (VERSION, RESOLUTION, SELECTED_TYPES, canonical_sha256)
from dcc_task_runtime.render_profiles import OFFICIAL, SOURCE_HIP_SHA256

OBSERVATION_SCHEMA = 'bridge.official-karma-observation/3'
UI_PROBE_NODE='/stage/lights/backdrop_shallow'
UI_PROBE_PARM='ineditlayerblock'
UI_PROBE_EXPRESSION='hou.pwd().inputs()[0].inEditLayerBlock()'
UI_PROBE_REASON='unconnected_sopcreate_edit_layer_ui_probe'
MAX_OBSERVATION_BYTES = 8 * 1024 * 1024
MAX_VALUES = 200000
PRODUCT = '/Render/Products/renderproduct'
SETTINGS = '/Render/rendersettings'
BEAUTY = '/Render/Products/Vars/Beauty'
BEAUTY_ADAPTER = '/stage/lights/bridge_rgba_output'
BEAUTY_ATTRIBUTES = {
    'driver:parameters:aov:husk:name': ('String','string','C'),
    'driver:parameters:aov:husk:format': ('String','token','color4h'),
}
# Name decoding and usdvaluetype tags follow the installed Husk_Product.ds and
# loputils._addControlParmsToGroup convention. Storage is a custom driver field.
OUTPUT_ATTRIBUTES = {
    'driver:parameters:husk:source_colorspace': ('String', 'string', 'scene_linear'),
    'driver:parameters:husk:output_colorspace': ('String', 'string', 'ACEScg'),
    'driver:parameters:husk:OpenEXR:storage': ('String', 'string', 'scanline'),
    'driver:parameters:husk:OpenEXR:multipart': ('Toggle', 'bool', 0),
    'driver:parameters:husk:OpenEXR:compression': ('String', 'string', 'zips'),
}


def bounded_json(value):
    """Check the whole observation, including disabled/fallback attribute values."""
    remaining = MAX_VALUES
    def walk(v, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 20:
            raise ValueError('OFFICIAL_OBSERVATION_COMPLEXITY_LIMIT')
        if v is None or type(v) is bool:
            return
        if type(v) in (int, float):
            if (type(v) is int and v.bit_length() > 64) or not math.isfinite(v):
                raise ValueError('OFFICIAL_OBSERVATION_NONFINITE')
            return
        if type(v) is str:
            if len(v) > 32768 or '\0' in v:
                raise ValueError('OFFICIAL_OBSERVATION_TEXT_LIMIT')
            return
        if type(v) in (dict, list):
            if len(v) > 100000:
                raise ValueError('OFFICIAL_OBSERVATION_CONTAINER_LIMIT')
            if type(v) is dict:
                if any(type(k) is not str for k in v):
                    raise ValueError('OFFICIAL_OBSERVATION_KEYS_INVALID')
                for k, child in v.items():
                    walk(k, depth + 1); walk(child, depth + 1)
            else:
                for child in v: walk(child, depth + 1)
            return
        raise ValueError('OFFICIAL_OBSERVATION_JSON_REQUIRED')
    walk(value, 0)
    raw = json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > MAX_OBSERVATION_BYTES:
        raise ValueError('OFFICIAL_OBSERVATION_BYTE_LIMIT')
    return copy.deepcopy(value)


def native_value(value, *, _depth=0, _budget=None):
    """Serialize native typed values without asCode/eval or opaque string fallbacks."""
    if _budget is None: _budget = [MAX_VALUES]
    _budget[0] -= 1
    if _budget[0] < 0 or _depth > 12:
        raise ValueError('OFFICIAL_NATIVE_VALUE_LIMIT')
    if value is None or type(value) in (bool, str, int, float):
        bounded_json(value)
        return value
    if type(value).__name__ == 'AssetPath':
        return {'asset_path': str(value.path), 'resolved_path': str(value.resolvedPath)}
    if type(value).__name__ == 'Ramp':
        return {'ramp_basis': [str(v).rsplit('.', 1)[-1] for v in value.basis()],
                'keys': list(value.keys()), 'values': [native_value(v, _depth=_depth+1, _budget=_budget) for v in value.values()]}
    if isinstance(value, dict):
        return {str(k): native_value(v, _depth=_depth+1, _budget=_budget) for k,v in value.items()}
    try:
        result = []
        for child in value:
            if len(result) >= 100000:
                raise ValueError('OFFICIAL_NATIVE_VALUE_LIMIT')
            result.append(native_value(child, _depth=_depth+1, _budget=_budget))
        return result
    except TypeError as error:
        raise ValueError('OFFICIAL_NATIVE_VALUE_UNSUPPORTED:' + type(value).__name__) from error


def scalar_write(node, name, value):
    """Apply one declared work-copy/fresh-node edit, deleting any native driver."""
    parm = node.parm(name)
    if parm is None or parm.isLocked():
        raise ValueError('OFFICIAL_NATIVE_FIELD_UNAVAILABLE:' + name)
    parm.deleteAllKeyframes()
    parm.set(value, follow_parm_reference=False)
    if parm.keyframes() or type(parm.eval()) is not type(value) or parm.eval() != value:
        raise ValueError('OFFICIAL_NATIVE_FIELD_READBACK:' + name)
    return {'field': name, 'value': value, 'dynamic': False}



def menu_token_readback(node,name,token):
    """Ordinal menus eval to an index; evalAsString returns the semantic token."""
    parm=node.parm(name)
    if parm is None or parm.parmTemplate().type().name()!='Menu':
        raise ValueError('OFFICIAL_NATIVE_MENU_REQUIRED:'+name)
    items=tuple(parm.menuItems())
    index=parm.eval()
    if (not 1<=len(items)<=64 or len(set(items))!=len(items) or token not in items
            or parm.keyframes() or type(index) is not int or not 0<=index<len(items)
            or items[index]!=token or parm.evalAsString()!=token):
        raise ValueError('OFFICIAL_NATIVE_MENU_READBACK:'+name)
    return {'field':name,'token':token,'index':index,'dynamic':False}


def menu_token_write(node,name,token):
    parm=node.parm(name)
    if parm is None or parm.isLocked() or parm.parmTemplate().type().name()!='Menu':
        raise ValueError('OFFICIAL_NATIVE_MENU_UNAVAILABLE:'+name)
    items=tuple(parm.menuItems())
    if not 1<=len(items)<=64 or len(set(items))!=len(items) or token not in items:
        raise ValueError('OFFICIAL_NATIVE_MENU_TOKEN_REQUIRED:'+name)
    parm.deleteAllKeyframes()
    parm.set(items.index(token),follow_parm_reference=False)
    return menu_token_readback(node,name,token)


def configure_output(hou, node):
    return _configure_attributes(hou,node,OUTPUT_ATTRIBUTES)


def _configure_attributes(hou, node, attributes):
    """Add only fixed scalar driver properties to the existing last path author.

    This edits an owned work copy or a newly owned graph node. It does not touch
    the installed HDA or original HIP. Composed USD readback is mandatory after
    this function; template writes alone are not output acceptance.
    """
    if node.type().name() != 'editproperties':
        raise ValueError('OFFICIAL_OUTPUT_AUTHOR_TYPE_REQUIRED')
    group = node.parmTemplateGroup()
    for prop, (kind, usd_type, _value) in attributes.items():
        name = hou.text.encodeParm(prop)
        control = hou.text.encodeParm(prop + '_control')
        templates = [hou.StringParmTemplate(control, prop + ' control', 1, default_value=('none',),
                                            menu_items=('none', 'set'), menu_labels=('None', 'Set'))]
        if kind == 'Toggle':
            template = hou.ToggleParmTemplate(name, prop, default_value=True)
        else:
            template = hou.StringParmTemplate(name, prop, 1, default_value=('',))
        template.setTags({'usdvaluetype': usd_type})
        templates.append(template)
        for item in templates:
            existing = group.find(item.name())
            if existing is None:
                group.append(item)
            elif (existing.type().name() != item.type().name()
                  or existing.numComponents() != item.numComponents()
                  or existing.tags().get('usdvaluetype') != item.tags().get('usdvaluetype')):
                raise ValueError('OFFICIAL_OUTPUT_TEMPLATE_CONFLICT:' + item.name())
    node.setParmTemplateGroup(group)
    result = {}
    for prop, (_kind, _usd_type, value) in attributes.items():
        scalar_write(node, hou.text.encodeParm(prop + '_control'), 'set')
        result[prop] = scalar_write(node, hou.text.encodeParm(prop), value)
    return result



def configure_beauty(hou,node):
    scalar_write(node,'primpattern',BEAUTY)
    menu_token_write(node,'createprims','off')
    return _configure_attributes(hou,node,BEAUTY_ATTRIBUTES)


def beauty_author_readback(hou,node,expected_input):
    if node is None or node.type().name()!='editproperties' or node.errors() or node.warnings():
        raise ValueError('OFFICIAL_BEAUTY_AUTHOR_REQUIRED')
    wires=[(c.inputIndex(),c.inputNode().path(),c.outputIndex()) for c in node.inputConnections()]
    if wires!=[(0,expected_input,0)]:raise ValueError('OFFICIAL_BEAUTY_AUTHOR_CONNECTION_MISMATCH')
    menu_token_readback(node,'createprims','off')
    fields={'primpattern':BEAUTY}
    for prop,(_kind,typ,value) in BEAUTY_ATTRIBUTES.items():
        name=hou.text.encodeParm(prop)
        fields[hou.text.encodeParm(prop+'_control')]='set';fields[name]=value
        parm=node.parm(name)
        if parm is None or parm.parmTemplate().tags().get('usdvaluetype')!=typ:
            raise ValueError('OFFICIAL_BEAUTY_AUTHOR_TEMPLATE_MISMATCH')
    for name,expected in fields.items():
        parm=node.parm(name)
        if parm is None or parm.keyframes() or type(parm.eval()) is not type(expected) or parm.eval()!=expected:
            raise ValueError('OFFICIAL_BEAUTY_AUTHOR_FIELD_DRIFT:'+name)
    return {'path':node.path(),'type':'editproperties','input':expected_input,
            'primpattern':BEAUTY,'createprims':'off','attributes':{p:{'type':t,'value':v,'control':'set'}
                for p,(_k,t,v) in BEAUTY_ATTRIBUTES.items()}}


def verify_output_stage(stage, output, frame=1):
    """Validate the effective product and beauty, never husk's output override."""
    settings, product, beauty = (stage.GetPrimAtPath(p) for p in (SETTINGS, PRODUCT, BEAUTY))
    if not all((settings, product, beauty)):
        raise ValueError('OFFICIAL_OUTPUT_PRIMS_REQUIRED')
    def value(prim, name, expected_type=None):
        attr = prim.GetAttribute(name)
        if not attr or (expected_type is not None and str(attr.GetTypeName()) != expected_type):
            raise ValueError('OFFICIAL_OUTPUT_ATTRIBUTE_REQUIRED:' + name)
        return native_value(attr.Get(frame))
    if value(settings, 'resolution') != RESOLUTION or value(product, 'productName') != output:
        raise ValueError('OFFICIAL_OUTPUT_EFFECTIVE_PATH_OR_RESOLUTION_MISMATCH')
    if value(product, 'productType') != 'raster':
        raise ValueError('OFFICIAL_OUTPUT_BEAUTY_PRODUCT_REQUIRED')
    if [str(p) for p in settings.GetRelationship('products').GetTargets()] != [PRODUCT]:
        raise ValueError('OFFICIAL_OUTPUT_PRODUCT_RELATION_MISMATCH')
    if [str(p) for p in product.GetRelationship('orderedVars').GetTargets()] != [BEAUTY]:
        raise ValueError('OFFICIAL_OUTPUT_VAR_RELATION_MISMATCH')
    result = {}
    for name, (_kind, typ, expected) in OUTPUT_ATTRIBUTES.items():
        actual = value(product, name, typ)
        wanted = bool(expected) if typ == 'bool' else expected
        attr = product.GetAttribute(name)
        if type(actual) is not type(wanted) or actual != wanted or not attr.HasAuthoredValueOpinion():
            raise ValueError('OFFICIAL_OUTPUT_ATTRIBUTE_READBACK:' + name)
        result[name] = actual
    expected_var = {'sourceName': 'C.*[LO]', 'sourceType': 'lpe', 'dataType': 'color4f',
                    'driver:parameters:aov:husk:name': 'C', 'driver:parameters:aov:husk:format': 'color4h'}
    if any(value(beauty, name) != expected for name,expected in expected_var.items()):
        raise ValueError('OFFICIAL_OUTPUT_RGBA_BEAUTY_REQUIRED')
    filters = settings.GetRelationship('husk:orderedImageFilters')
    if (filters and filters.GetTargets()) or settings.GetAttribute('husk:orderedImageFilters'):
        raise ValueError('OFFICIAL_OUTPUT_FILTERS_UNSUPPORTED')
    return {'resolution': list(RESOLUTION), 'product': PRODUCT, 'beauty': BEAUTY,
            'product_name': output, 'attributes': result, 'rgba_beauty': expected_var}


def parameter_value(parm,kind):
    if kind=='Ramp':
        import hou
        ramps=parm.evalAsRamps()
        if type(ramps) is not tuple or len(ramps)!=1 or not isinstance(ramps[0],hou.Ramp):
            raise ValueError('OFFICIAL_NATIVE_RAMP_SHAPE_INVALID')
        ramp=ramps[0]
        return [{'ramp_basis':[str(v).rsplit('.',1)[-1] for v in ramp.basis()],
                 'keys':list(ramp.keys()),'values':[native_value(v) for v in ramp.values()]}]
    result=native_value(parm.eval())
    if not isinstance(result,list):
        raise ValueError('OFFICIAL_NATIVE_PARAMETER_SHAPE_INVALID')
    return result



def ui_probe_omission(node):
    """Guard one unconnected H21 UI driver without evaluating it or inventing 0."""
    if (node.path()!=UI_PROBE_NODE or node.type().name()!='sopcreate' or node.inputConnections()):
        raise ValueError('OFFICIAL_UI_PROBE_CONTEXT_MISMATCH')
    parm=node.parmTuple(UI_PROBE_PARM)
    if parm is None or parm.parmTemplate().type().name()!='Toggle' or len(tuple(parm))!=1:
        raise ValueError('OFFICIAL_UI_PROBE_TEMPLATE_MISMATCH')
    template=parm.parmTemplate();component=tuple(parm)[0]
    default=template.defaultExpression()
    if isinstance(default,(list,tuple)) and len(default)==1:default=default[0]
    language=template.defaultExpressionLanguage()
    if isinstance(language,(list,tuple)) and len(language)==1:language=language[0]
    if not template.isHidden() or default!=UI_PROBE_EXPRESSION or language.name()!='Python':
        raise ValueError('OFFICIAL_UI_PROBE_TEMPLATE_MISMATCH')
    keys=component.keyframes()
    expression=component.expression() if keys else component.rawValue()
    if keys and component.expressionLanguage().name()!='Python':
        raise ValueError('OFFICIAL_UI_PROBE_DRIVER_MISMATCH')
    if expression!=UI_PROBE_EXPRESSION:
        raise ValueError('OFFICIAL_UI_PROBE_DRIVER_MISMATCH')
    return {'node':UI_PROBE_NODE,'parameter':UI_PROBE_PARM,'kind':'Toggle','components':1,
        'template_sha256':hashlib.sha256(template.asCode().encode()).hexdigest(),
        'hidden':True,'expression_language':'Python','source_expression':expression,'reason':UI_PROBE_REASON,'input_count':0,'value_status':'NOT_EVALUATED'}


def validate_ramp_failure_context(context):
    if (type(context) is not dict or set(context)!={'schema','node','parameter','kind','api','stage'}
            or context['schema']!='bridge.official-karma-ramp-failure/1'
            or context['kind']!='Ramp' or context['api']!='evalAsRamps'
            or context['stage']!='evaluation_or_serialization'
            or type(context['node']) is not str or len(context['node'])>1024
            or type(context['parameter']) is not str or len(context['parameter'])>256):
        raise ValueError('OFFICIAL_RAMP_FAILURE_CONTEXT_INVALID')
    return bounded_json(context)


def capture_parameters(node, *, omitted_fields=()):
    """Capture concrete leaf values and native templates; do not replay drivers."""
    if omitted_fields not in ((),(UI_PROBE_PARM,)):
        raise ValueError('OFFICIAL_PARAMETER_OMISSION_NOT_ALLOWED')
    if omitted_fields:ui_probe_omission(node)
    result = {}
    tuples = tuple(node.parmTuples())
    if len(tuples) > 1024:
        raise ValueError('OFFICIAL_PARAMETER_COUNT_LIMIT')
    for parm in tuples:
        if parm.name() in omitted_fields:continue
        template = parm.parmTemplate()
        kind = template.type().name()
        if kind in ('Button', 'Separator', 'Label', 'FolderSet'):
            continue
        components = tuple(parm)
        multiparm = kind != 'Ramp' and len(components) == 1 and components[0].isMultiParmParent()
        if kind == 'Folder' and not multiparm:
            continue
        if kind not in ('Float', 'Int', 'Toggle', 'String', 'Menu', 'Ramp', 'Folder'):
            raise ValueError('OFFICIAL_PARAMETER_TYPE_UNSUPPORTED:' + parm.name())
        try:
            value = parameter_value(parm,kind)
            if kind=='Ramp':
                bounded_json(value)
                ramp=value[0]
                if (len(components)!=1 or not 2<=len(ramp['keys'])<=64
                        or len(ramp['ramp_basis'])!=len(ramp['keys'])
                        or len(ramp['values'])!=len(ramp['keys'])
                        or any(type(v) is not float for v in ramp['keys'])
                        or ramp['keys']!=sorted(ramp['keys'])
                        or any(v not in {'Constant','Linear','CatmullRom','MonotoneCubic','Bezier','BSpline','Hermite'}
                               for v in ramp['ramp_basis'])):
                    raise ValueError('OFFICIAL_OBSERVATION_RAMP_INVALID')
        except Exception as error:
            if kind=='Ramp':
                context={'schema':'bridge.official-karma-ramp-failure/1',
                         'node':node.path()[:1024], 'parameter':parm.name()[:256],
                         'kind':'Ramp', 'api':'evalAsRamps', 'stage':'evaluation_or_serialization'}
                error.official_ramp_context=bounded_json(context)
            raise
        result[parm.name()] = {'kind': kind, 'multiparm': multiparm,
            'components': len(components), 'value': value,
            'template_sha256': hashlib.sha256(template.asCode().encode()).hexdigest(),
            'locked': [p.isLocked() for p in components], 'disabled': [None for p in components],
            'raw_channels': [p.unexpandedString() if kind == 'String' and not p.keyframes() else None for p in components],
            'keyframe_counts': [len(p.keyframes()) for p in components]}
    return bounded_json(result)


def capture_stage(stage, *, case_id=None):
    """Observe complete composed properties, primvars and effective material state."""
    from pxr import UsdGeom, UsdShade
    prims = {}
    for prim in stage.Traverse():
        if len(prims) >= 512:
            raise ValueError('OFFICIAL_USD_PRIM_LIMIT')
        path, typ = str(prim.GetPath()), prim.GetTypeName()
        if typ in ('Material', 'Shader', 'NodeGraph'):
            raise ValueError('OFFICIAL_UNEXPLAINED_SHADER_SOURCE:' + path)
        attributes = {}
        for attr in prim.GetAttributes():
            name = attr.GetName()
            attributes[name] = {'type': str(attr.GetTypeName()),
                'authored': bool(attr.HasAuthoredValueOpinion()), 'value': native_value(attr.Get(1)),
                'interpolation': native_value(attr.GetMetadata('interpolation')),
                'element_size': native_value(attr.GetMetadata('elementSize'))}
        relationships = {rel.GetName(): [str(p) for p in rel.GetForwardedTargets()]
                         for rel in prim.GetRelationships()}
        material, relation = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if material or relation:
            raise ValueError('OFFICIAL_UNEXPLAINED_MATERIAL_BINDING:' + path)
        xform = UsdGeom.Xformable(prim)
        prims[path] = {'type': typ, 'attributes': attributes, 'relationships': relationships,
            'world_matrix': native_value(xform.ComputeLocalToWorldTransform(1)) if xform else None,
            'material_binding': None, 'active': bool(prim.IsActive()),
            'instanceable': bool(prim.IsInstanceable()), 'kind': native_value(prim.GetMetadata('kind'))}
    if case_id is None:
        # 旧DiskLight入口保留原判定，严格Rect路径门只用于新认证案例。
        if not any(p['type']=='Mesh' for p in prims.values()) or sum(p['type']=='DiskLight' for p in prims.values())!=1:
            raise ValueError('OFFICIAL_USD_DISKLIGHT_GEOMETRY_REQUIRED')
    elif case_id=='karma_lights_rectlight_v1':
        lights={p:row['type'] for p,row in prims.items() if row['type'] in ('DiskLight','RectLight','SphereLight','DistantLight','DomeLight','CylinderLight','GeometryLight')}
        if not any(p['type']=='Mesh' for p in prims.values()) or lights!={'/World/UsdLuxRectLight':'RectLight'}:
            raise ValueError('OFFICIAL_USD_LIGHT_GEOMETRY_REQUIRED')
    else:
        raise ValueError('OFFICIAL_USD_CASE_INVALID')
    metadata = {name: {'authored': bool(stage.HasAuthoredMetadata(name)), 'value': native_value(stage.GetMetadata(name))}
                for name in ('upAxis', 'metersPerUnit')}
    return bounded_json({'metadata': metadata, 'prims': prims})


def semantic_compare(reference, actual, *, reference_output, actual_output, export_up_axis_policy=None):
    """Compare typed USD facts with explicit, recorded export representation rules."""
    a, b = bounded_json(reference), bounded_json(actual)
    equivalences=[]
    export_axis_equivalent=False
    if export_up_axis_policy is not None:
        if export_up_axis_policy!='h21_export_fallback_y_v1':
            raise ValueError('OFFICIAL_EXPORT_METADATA_POLICY_INVALID')
        left=a.get('metadata',{}).get('upAxis')
        right=b.get('metadata',{}).get('upAxis')
        if (type(left) is dict and type(right) is dict
                and set(left)==set(right)=={'authored','value'}
                and left['authored'] is False and right['authored'] is True
                and left['value']==right['value']=='Y'):
            equivalences.append({'path':'/metadata/upAxis/authored','policy':export_up_axis_policy,
                                 'reference':False,'actual':True,'effective_value':'Y','fallback_value':'Y'})
            export_axis_equivalent=True
    for document, output in ((a, reference_output), (b, actual_output)):
        product = document.get('prims', {}).get(PRODUCT, {})
        attribute = product.get('attributes', {}).get('productName')
        if not attribute or attribute.get('value') != output:
            raise ValueError('OFFICIAL_SEMANTIC_OUTPUT_IDENTITY_REQUIRED')
        attribute['value'] = '<declared-render-product>'
    differences = []
    def compare(left, right, path):
        if export_axis_equivalent and path=='/metadata/upAxis/authored':
            return
        if len(differences) >= 32:
            return
        if type(left) in (float, int) and type(right) in (float, int):
            # Integer topology/enums remain exact; floats have the frozen 1e-6 limit.
            equal = (type(left) is type(right) and left == right) if type(left) is int or type(right) is int else abs(left-right) <= 1e-6
        elif type(left) is not type(right):
            equal = False
        elif type(left) is dict:
            if set(left) != set(right):
                differences.append({'path': path, 'kind': 'fields', 'expected': sorted(left), 'actual': sorted(right)})
                return
            for key in left: compare(left[key], right[key], path + '/' + key)
            return
        elif type(left) is list:
            if len(left) != len(right):
                differences.append({'path': path, 'kind': 'length', 'expected': len(left), 'actual': len(right)})
                return
            for i,(v,w) in enumerate(zip(left,right)): compare(v,w,path+'/'+str(i))
            return
        else:
            equal = left == right
        if not equal:
            differences.append({'path': path, 'kind': 'value', 'expected': left, 'actual': right})
    compare(a,b,'')
    return {'state': 'FAIL' if differences else 'PASS', 'differences': differences,
            'reference_sha256': canonical_sha256(reference), 'actual_sha256': canonical_sha256(actual),
            'export_up_axis_policy':export_up_axis_policy,'representation_equivalences':equivalences}


def capture_resources(hou, stage, nodes, allowed_roots):
    """Capture only resolved local dependencies of the selected composed case."""
    from .official_karma_observation import file_record
    roots = tuple(Path(p).resolve(strict=True) for p in allowed_roots)
    files = {}
    def add(raw):
        if not raw:
            return
        path = Path(raw)
        if (not path.is_absolute() or path != path.resolve() or not path.is_file()
                or not any(path.is_relative_to(root) for root in roots)):
            raise ValueError('OFFICIAL_RESOURCE_OUTSIDE_FROZEN_ROOTS:' + str(raw))
        files[str(path)] = file_record(path)
    for node in nodes:
        definition = node.type().definition()
        if definition is not None:
            add(definition.libraryFilePath())
    for layer in stage.GetUsedLayers():
        if layer.anonymous:
            continue
        if str(layer.identifier).startswith('op:'):
            if not str(layer.identifier).startswith('op:/stage/lights/'):
                raise ValueError('OFFICIAL_RESOURCE_UNKNOWN_MEMORY_LAYER')
            continue
        add(layer.realPath)
    def assets(value):
        if type(value).__name__ == 'AssetPath':
            if value.path:
                if str(value.path).startswith('op:'):
                    if not str(value.path).startswith('op:/stage/lights/'):
                        raise ValueError('OFFICIAL_RESOURCE_UNKNOWN_MEMORY_ASSET')
                else:
                    if not value.resolvedPath:
                        raise ValueError('OFFICIAL_RESOURCE_UNRESOLVED:' + str(value.path))
                    add(value.resolvedPath)
        elif not isinstance(value, (str, bytes, int, float, bool)) and value is not None:
            try:
                for child in value: assets(child)
            except TypeError:
                pass
    for prim in stage.Traverse():
        for attribute in prim.GetAttributes(): assets(attribute.Get(1))
    selected = {node.path() for node in nodes}
    for parm, _raw in hou.fileReferences():
        if parm is not None and parm.node().path() in selected:
            resolved = parm.evalAsString()
            if resolved and not resolved.startswith(('op:', 'opdef:')):
                tags = parm.parmTemplate().tags()
                output_field = (tags.get('filechooser_mode') == 'write' or
                    parm.node().path() == '/stage/lights/karmarendersettings' and
                    parm.name() in ('picture','dcmfilename','productName') or
                    parm.node().path() == '/stage/lights/OUT_karma_lights' and
                    parm.name() in ('lopoutput','outputimage','savetodirectory_directory','husk_tiletempdir','husk_stdout','husk_stderr'))
                if output_field:
                    if not Path(resolved).is_absolute() or not Path(resolved).is_relative_to(roots[0]):
                        raise ValueError('OFFICIAL_OUTPUT_RESOURCE_OUTSIDE_SCOPE:' + resolved)
                else:
                    add(resolved)
    return [files[path] for path in sorted(files)]


def output_topology():
    return {'schema':'bridge.official-karma-output-topology/1',
            'rop':'/stage/lights/OUT_karma_lights','input':0,'output':0,
            'original_source':'/stage/lights/update_output_image_path',
            'source':BEAUTY_ADAPTER,'adapter_input':'/stage/lights/update_output_image_path'}


def observation_inputs(path,source):
    wires=[dict(w,source=str(Path(path).parent/w['source'])) for w in source['inputs']]
    if path=='/stage/lights/OUT_karma_lights':
        if wires!=[{'input':0,'source':'/stage/lights/update_output_image_path','output':0}]:
            raise ValueError('OFFICIAL_SOURCE_EXPORT_CONNECTION_MISMATCH')
        wires=[{'input':0,'source':BEAUTY_ADAPTER,'output':0}]
    return sorted(wires,key=lambda w:w['input'])


def capture_observation(hou, source_contract, *, output, scope_sha256, source_contract_sha256, allowed_resource_roots):
    if hou.applicationVersionString() != VERSION or hou.frame() != 1:
        raise ValueError('OFFICIAL_NATIVE_VERSION_OR_FRAME_MISMATCH')
    nodes, native_nodes = {}, []
    omission=ui_probe_omission(hou.node(UI_PROBE_NODE))
    for path, typ in SELECTED_TYPES.items():
        native_path = '/' + path
        node = hou.node(native_path)
        if node is None or node.type().name() != typ:
            raise ValueError('OFFICIAL_NATIVE_NODE_MISMATCH:' + native_path)
        native_nodes.append(node)
        if node.errors() or node.warnings():
            raise ValueError('OFFICIAL_NATIVE_NODE_DIAGNOSTIC:' + native_path)
        inputs = [{'input': c.inputIndex(), 'source': c.inputNode().path(), 'output': c.outputIndex()}
                  for c in node.inputConnections()]
        expected = source_contract['nodes'][native_path]
        wires = observation_inputs(native_path,expected)
        if sorted(inputs,key=lambda w:w['input']) != wires:
            raise ValueError('OFFICIAL_NATIVE_CONNECTION_MISMATCH:' + native_path)
        flags = None
        if node.type().category().name() == 'Sop':
            flags = {'display': bool(node.isDisplayFlagSet()), 'render': bool(node.isRenderFlagSet())}
            if flags != {k:expected[k] for k in ('display','render')}:
                raise ValueError('OFFICIAL_NATIVE_GEOMETRY_FLAG_MISMATCH:' + native_path)
        nodes[native_path] = {'type': typ, 'parameters': capture_parameters(node,omitted_fields=(UI_PROBE_PARM,) if native_path==UI_PROBE_NODE else ()), 'inputs': sorted(inputs,key=lambda w:w['input']), 'flags': flags}
    switch = hou.node('/stage/lights/switch3').parm('input')
    if switch.keyframes() or switch.eval() != 1:
        raise ValueError('OFFICIAL_NATIVE_STATIC_DISKLIGHT_REQUIRED')
    adapter=hou.node(BEAUTY_ADAPTER)
    adapter_fact=beauty_author_readback(hou,adapter,'/stage/lights/update_output_image_path')
    native_nodes.append(adapter)
    stage = adapter.stage(frame=1,
        apply_viewport_overrides=False, ignore_errors=False)
    verify_output_stage(stage, output)
    supplements = {}
    for name in ('sopimport', 'xform', 'loftpayloadinfo1'):
        node = hou.node('/stage/lights/backdrop_shallow/' + name)
        if node is None:
            raise ValueError('OFFICIAL_SOPCREATE_IMPORT_MAPPING_REQUIRED:' + name)
        native_nodes.append(node)
        supplements[name] = {'type': node.type().name(), 'parameters': capture_parameters(node)}
    result = {'schema': OBSERVATION_SCHEMA, 'profile': OFFICIAL, 'version': VERSION,
        'frame': 1, 'scope_sha256': scope_sha256, 'source_sha256': SOURCE_HIP_SHA256,
        'source_contract_sha256': source_contract_sha256, 'nodes': nodes,
        'capture_policy':{'schema':'bridge.official-karma-parameter-capture/1','ui_disabled':'NOT_EVALUATED','omissions':[omission]},
        'sopcreate_import': supplements, 'output_adapter':adapter_fact,'output_topology':output_topology(),
        'stage': capture_stage(stage), 'output': output,
        'resources': capture_resources(hou, stage, native_nodes, allowed_resource_roots)}
    return bounded_json(result)


def cached_node_diagnostics(hou):
    """Read last-cook messages only; never cook a stage or evaluate a parm."""
    rows=[];complete=True
    for path in ['/'+p for p in SELECTED_TYPES]+[BEAUTY_ADAPTER]:
        row={'path':path,'exists':False,'type':None,'cached_native_messages':True,'queries':{}}
        try:
            node=hou.node(path)
            if node is not None:
                row.update(exists=True,type=node.type().name())
                for name in ('errors','warnings','messages'):
                    try:
                        values=tuple(getattr(node,name)())
                        texts=[str(v) for v in values[:16]]
                        truncated=len(values)>16 or any(len(v)>4096 for v in texts)
                        row['queries'][name]={'state':'TRUNCATED' if truncated else 'OBSERVED',
                            'values':[v[:4096] for v in texts]}
                        if truncated:complete=False
                    except Exception as error:
                        complete=False
                        row['queries'][name]={'state':'CAPTURE_FAILED','error':type(error).__name__+':'+str(error)[:2048]}
        except Exception as error:
            complete=False;row['capture_error']=type(error).__name__+':'+str(error)[:2048]
        rows.append(row)
    return bounded_json({'schema':'bridge.official-karma-native-diagnostic/1',
        'mode':'cached_native_messages','diagnostics_incomplete':not complete,'nodes':rows})
