#!/usr/bin/env python3
"""Prepare the fixed H21 alpha chart and exact husk argv without launching a DCC."""
from __future__ import annotations
import argparse
import hashlib
import json
import shlex
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
for package in ('dcc-task-runtime', 'houdini-bridge'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
from dcc_task_runtime.owned_process import _canonical
from houdini_bridge.controlled_output import controlled_route_sha256

VERSION = '21.0.631'


def _record(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _plain(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ALPHA_PREPARE_PLAIN_ABSOLUTE_PATH_REQUIRED')
    return path


def _sources(houdini_root):
    framework = houdini_root / 'Frameworks/Houdini.framework/Versions/21.0'
    materialx = houdini_root / 'Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages/MaterialX/libraries/bxdf/standard_surface.mtlx'
    paths = {'materialx_definition': materialx,
        'materialx_usd_example': framework / 'Resources/houdini/usd/materials/basic_materials/basic_materials.usd',
        'usd_materialx_schema': framework / 'Libraries/usd_plugins/usdMtlx/resources/usdMtlx/schema.usda',
        'usd_render_schema': framework / 'Libraries/usd_plugins/usdRender/resources/usdRender/schema.usda',
        'usd_camera_schema': framework / 'Libraries/usd_plugins/usdGeom/resources/usdGeom/schema.usda',
        'karma_beauty_definition': framework / 'Resources/houdini/python3.11libs/husd/karmautils.py'}
    for path in paths.values():
        _plain(path)
        if not path.is_file():
            raise ValueError('ALPHA_PREPARE_PRIMARY_SOURCE_REQUIRED:' + str(path))
    document = ET.parse(materialx).getroot()
    definitions = {node.get('name'): node for node in document.findall('nodedef')}
    definition = definitions.get('ND_standard_surface_surfaceshader')
    inherited = definitions.get(definition.get('inherit')) if definition is not None else None
    inputs = {node.get('name'): node.get('type') for item in (definition, inherited) if item is not None for node in item.findall('input')}
    required = {'base': 'float', 'specular': 'float', 'emission': 'float', 'emission_color': 'color3', 'opacity': 'color3'}
    if any(inputs.get(name) != kind for name, kind in required.items()):
        raise ValueError('ALPHA_PREPARE_MATERIALX_DEFINITION_MISMATCH')
    example = paths['materialx_usd_example'].read_text()
    if 'outputs:mtlx:surface.connect' not in example or 'ND_standard_surface_surfaceshader' not in example:
        raise ValueError('ALPHA_PREPARE_USD_MATERIAL_BINDING_SOURCE_REQUIRED')
    beauty = paths['karma_beauty_definition'].read_text()
    if '"C.*[LO]"' not in beauty or '"color4"' not in beauty or '"lpe"' not in beauty:
        raise ValueError('ALPHA_PREPARE_KARMA_BEAUTY_SOURCE_REQUIRED')
    return paths, framework


def chart_usda(chart_path, colorspace, scene_profile="sphere_ground_v2"):
    """UsdGeom orthographic chart; the centre samples are away from all edges."""
    from dcc_task_runtime.render_profiles import definition
    width, height = definition(scene_profile)['resolution']
    q = json.dumps
    materials, geometry = [], []
    for index, (opacity, left, right) in enumerate(((0., -6.3, -3.3), (.5, -1.5, 1.5), (1., 3.3, 6.3))):
        materials.append(f'''        def Material "Opacity{index}"
        {{
            token outputs:mtlx:surface.connect = </World/Materials/Opacity{index}/Emission.outputs:out>
            token outputs:kma:surface.connect = </World/Materials/Opacity{index}/Emission.outputs:out>
            def Shader "Emission"
            {{
                uniform token info:id = "ND_standard_surface_surfaceshader"
                float inputs:base = 0
                float inputs:specular = 0
                float inputs:emission = 1
                color3f inputs:emission_color = (0.8, 0.8, 0.8)
                color3f inputs:opacity = ({opacity}, {opacity}, {opacity})
                token outputs:out
            }}
        }}''')
        geometry.append(f'''    def Mesh "Patch{index}" (prepend apiSchemas = ["MaterialBindingAPI"])
    {{
        uniform token subdivisionScheme = "none"
        uniform bool doubleSided = true
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [({left}, -4, 0), ({right}, -4, 0), ({right}, 4, 0), ({left}, 4, 0)]
        rel material:binding = </World/Materials/Opacity{index}>
    }}''')
    return f'''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Y"
    startTimeCode = 1
    endTimeCode = 1
    customLayerData = {{ string bridge_alpha_recipe = "emission-opacity-chart-v1" }}
)
def Xform "World"
{{
    def Camera "Camera"
    {{
        token projection = "orthographic"
        float horizontalAperture = 128
        float verticalAperture = {128 * height / width:g}
        float2 clippingRange = (0.1, 100)
        double3 xformOp:translate = (0, 0, 10)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        double shutter:open = 0
        double shutter:close = 0
    }}
    def Scope "Materials"
    {{
{chr(10).join(materials)}
    }}
{chr(10).join(geometry)}
}}
def Scope "Render"
{{
    def RenderSettings "Settings"
    {{
        uniform int2 resolution = ({width}, {height})
        uniform float pixelAspectRatio = 1
        uniform bool instantaneousShutter = true
        custom bool disableMotionBlur = true
        uniform token renderingColorSpace = {q(colorspace)}
        custom token husk:delegate = "BRAY_HdKarma"
        custom int karma:global:samplesperpixel = 4096
        rel husk:orderedImageFilters = []
        rel camera = </World/Camera>
        rel products = </Render/Beauty>
    }}
    def RenderProduct "Beauty"
    {{
        uniform token productType = "raster"
        uniform token productName = {q(str(chart_path))}
        rel orderedVars = </Render/Vars/C>
        custom string driver:parameters:husk:source_colorspace = "scene_linear"
        custom string driver:parameters:husk:output_colorspace = "ACEScg"
        custom string driver:parameters:husk:OpenEXR:storage = "scanline"
        custom int driver:parameters:husk:OpenEXR:multipart = 0
        custom string driver:parameters:husk:OpenEXR:compression = "none"
    }}
    def Scope "Vars"
    {{
        def RenderVar "C"
        {{
            uniform token dataType = "color4f"
            uniform string sourceName = "C.*[LO]"
            uniform token sourceType = "lpe"
            custom string driver:parameters:aov:husk:name = "C"
            custom token driver:parameters:aov:husk:format = "color4h"
        }}
    }}
}}
'''


def prepare(*, output_root, houdini_root, colorspace, scene_profile="sphere_ground_v2"):
    from dcc_task_runtime.render_profiles import LEGACY, definition
    fixture = definition(scene_profile)
    output_root, houdini_root = _plain(output_root), _plain(houdini_root)
    if houdini_root.name != 'Houdini' + VERSION or colorspace != 'ACEScg':
        raise ValueError('ALPHA_PREPARE_FROZEN_H21_ACESCG_SCOPE_REQUIRED')
    sources, framework = _sources(houdini_root)
    husk = _plain(framework / 'Resources/bin/husk')
    if not husk.is_file():
        raise ValueError('ALPHA_PREPARE_HUSK_FILE_REQUIRED')
    if output_root.exists():
        raise ValueError('ALPHA_PREPARE_FRESH_OUTPUT_DIRECTORY_REQUIRED')
    output_root.mkdir(parents=True, mode=0o700)
    scene, chart = output_root / 'alpha-chart.usda', output_root / 'alpha-chart.exr'
    with scene.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(chart_usda(chart, colorspace, scene_profile))
    route = {'resolution': fixture['resolution'], 'renderer': 'BRAY_HdKarma', 'colorspace': colorspace,
        'output_color_route': {'source': 'scene_linear', 'output': 'ACEScg'},
        'denoiser': 'off', 'motion_blur': False, 'image_filters': [], 'aov_semantics': 'karma_beauty_lpe_v1',
        'products': [{'kind': 'beauty', 'channels': ['R', 'G', 'B', 'A'], 'multipart': False}]}
    runtime_ready = _plain(ROOT / 'packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py')
    result = {'schema': 'bridge.alpha-chart.preparation/1.0', 'state': 'PREPARED',
        'houdini_version': VERSION, 'scene': _record(scene), 'chart_path': str(chart),
        'sample_pixels': fixture['sample_pixels'], 'opacities': [0., .5, 1.],
        'emission': [.8, .8, .8], 'resolution': fixture['resolution'], 'frames': [1],
        'route': route, 'route_sha256': controlled_route_sha256(route),
        'native_execution_status': 'NOT_RUN',
        'command': [str(husk), '--prerender-script', shlex.quote(str(runtime_ready)),
                    '--renderer', 'BRAY_HdKarma', '--settings', '/Render/Settings',
                    '--frame', '1', '--frame-count', '1', '--output', str(chart), str(scene)],
        'primary_sources': {name: _record(path) for name, path in sources.items()},
        'generator': _record(Path(__file__).resolve()), 'runtime_ready_adapter': _record(runtime_ready),
        'husk': _record(husk)}
    if scene_profile != LEGACY:
        result['scene_profile'] = scene_profile
    with (output_root / 'preparation.json').open('xb') as stream:
        stream.write(_canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--houdini-root', required=True)
    parser.add_argument('--colorspace', choices=['ACEScg'], required=True)
    parser.add_argument('--scene-profile', choices=['sphere_ground_v2','official_karma_disklight_v1'], default='sphere_ground_v2')
    args = parser.parse_args()
    result = prepare(output_root=args.output_root, houdini_root=args.houdini_root, colorspace=args.colorspace, scene_profile=args.scene_profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
