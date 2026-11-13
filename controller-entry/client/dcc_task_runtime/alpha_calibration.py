"""Bounded alpha calibration authority and exact native material fixture recipe.

The software protocol never promotes supplied RGB samples to native evidence.
Native acceptance binds fixed observer sources, original host operations and
current chart/composite bytes before accepting measured association.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
if __package__:
    from . import owned_process
else:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dcc_task_runtime import owned_process

from dcc_task_runtime.render_profiles import LEGACY, OFFICIAL, definition

RENDER_TOLERANCE = .02
COMPOSITE_TOLERANCE = 1e-4
EMISSION = (.8, .8, .8)
OPACITIES = (0., .5, 1.)


def _sha(value):
    return hashlib.sha256(owned_process._canonical(value)).hexdigest()


def calibration_material_recipe(opacity):
    """Exact H21 Vop/mtlxstandard_surface fields from the installed HDA capture."""
    if type(opacity) not in (int, float) or opacity not in OPACITIES:
        raise ValueError('ALPHA_FIXTURE_OPACITY_INVALID')
    return {'base': (0.,), 'specular': (0.,), 'emission': (1.,),
            'emission_color': EMISSION, 'opacity': (float(opacity),) * 3}


def validate_material_readback(node, opacity):
    """Inspect native templates and actual values; this performs no writes/cooks."""
    if node.type().name() != 'mtlxstandard_surface':
        raise ValueError('ALPHA_FIXTURE_NATIVE_TYPE_MISMATCH')
    result = {}
    for name, expected in calibration_material_recipe(opacity).items():
        parm = node.parmTuple(name)
        if parm is None:
            raise ValueError('ALPHA_FIXTURE_NATIVE_PARAMETER_REQUIRED:' + name)
        template = parm.parmTemplate()
        if (template.numComponents() != len(expected)
                or template.type().name() != 'Float'
                or any(p.isDisabled() or p.isLocked() for p in parm)):
            raise ValueError('ALPHA_FIXTURE_NATIVE_TEMPLATE_MISMATCH:' + name)
        observed = tuple(parm.eval())
        if (len(observed) != len(expected) or any(type(v) not in (int, float)
                or not math.isfinite(v) or abs(v - e) > 1e-8 for v, e in zip(observed, expected))):
            raise ValueError('ALPHA_FIXTURE_NATIVE_READBACK_MISMATCH:' + name)
        result[name] = list(observed)
    return result


def _file(record):
    path = Path(record['path'])
    if (not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > 1024 * 1024):
        raise ValueError('ALPHA_CALIBRATION_SOURCE_INVALID')
    raw = path.read_bytes()
    if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise ValueError('ALPHA_CALIBRATION_SOURCE_CHANGED')
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError('ALPHA_CALIBRATION_SOURCE_OBJECT_REQUIRED')
    return value


def _rgb(value):
    if (type(value) is not list or len(value) != 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('ALPHA_CALIBRATION_NUMERIC_INVALID')
    return value


def _close(a, b, tolerance):
    return all(abs(x - y) <= tolerance for x, y in zip(_rgb(a), b))


def _numeric_observation(raw, composite):
    if raw.get('schema') != 'bridge.alpha-fixture-samples/1' or composite.get('schema') != 'bridge.alpha-composite-samples/1':
        raise ValueError('ALPHA_CALIBRATION_SAMPLE_SCHEMA')
    samples = raw.get('samples')
    if type(samples) is not list or len(samples) != len(OPACITIES):
        raise ValueError('ALPHA_CALIBRATION_FRACTIONAL_REQUIRED')
    alphas = []
    for sample, opacity in zip(samples, OPACITIES):
        alpha = sample.get('alpha')
        if type(alpha) not in (int, float) or not math.isfinite(alpha) or abs(alpha - opacity) > RENDER_TOLERANCE:
            raise ValueError('ALPHA_CALIBRATION_ALPHA_MISMATCH')
        _rgb(sample.get('rgb'))
        alphas.append(alpha)
    modes = [associated for associated in (True, False)
             if all(_close(sample['rgb'], [e * (a if associated else 1.) for e in EMISSION], RENDER_TOLERANCE)
                    for sample, a in zip(samples[1:], alphas[1:]))]
    if len(modes) != 1:
        raise ValueError('ALPHA_CALIBRATION_AMBIGUOUS')
    associated = modes[0]
    outputs = composite.get('samples')
    if type(outputs) is not list or len(outputs) != 3:
        raise ValueError('ALPHA_CALIBRATION_COMPOSITE_REQUIRED')
    for original, result in zip(samples, outputs):
        a = original['alpha']
        color = original['rgb'] if associated else [v * a for v in original['rgb']]
        if (not _close(result.get('over_black'), color, COMPOSITE_TOLERANCE)
                or not _close(result.get('over_white'), [v + 1. - a for v in color], COMPOSITE_TOLERANCE)):
            raise ValueError('ALPHA_CALIBRATION_COMPOSITE_MISMATCH')
    # Independent additive probe: RGB at alpha zero is valid emission and must
    # survive Read -> composition -> Write without implicit alpha multiplication.
    additive = composite.get('additive') or {}
    rgb = [.125, .0625, .25]
    if (additive.get('alpha') != 0 or not _close(additive.get('input_rgb'), rgb, COMPOSITE_TOLERANCE)
            or not _close(additive.get('over_black'), rgb, COMPOSITE_TOLERANCE)
            or not _close(additive.get('over_white'), [v + 1. for v in rgb], COMPOSITE_TOLERANCE)):
        raise ValueError('ALPHA_CALIBRATION_ADDITIVE_LOST')
    return associated


# 原049可信校验器；历史入口保留其原terminal哈希与观察器来源，不能接纳任意源码。
LEGACY_VERIFIER_SHA256 = '1acc81701798ee365357520ed46917b4b84f3d271d080a8b049e948d9705f319'


def validate_alpha_calibration(binding, *, expected_version, expected_plugin_build,
                               expected_route_sha256, evidence_source):
    """默认校验维持当前模块及实时文件身份合同。"""
    return _validate_alpha_calibration(binding, expected_version=expected_version,
        expected_plugin_build=expected_plugin_build, expected_route_sha256=expected_route_sha256,
        evidence_source=evidence_source)


def validate_historical_alpha_calibration(binding, *, verifier_source, expected_version,
                                          expected_plugin_build, expected_route_sha256, evidence_source,
                                          shape_scope_binding=None):
    """新历史校验器认证已封存旧源；不执行改写源码或改造原anchor。"""
    from dcc_task_runtime import process_image
    if (type(verifier_source) is not dict or verifier_source.get('sha256') != LEGACY_VERIFIER_SHA256
            or evidence_source != 'real_host'):
        raise ValueError('ALPHA_HISTORICAL_VERIFIER_SOURCE_REQUIRED')
    with process_image._historical_validation_sources(verifier_source, shape_scope_binding=shape_scope_binding):
        source = _rehash_record(verifier_source, 2 * 1024 * 1024)
        if source != verifier_source or Path(source['path']).name != 'alpha_calibration.py':
            raise ValueError('ALPHA_HISTORICAL_VERIFIER_SOURCE_REQUIRED')
        return _validate_alpha_calibration(binding, expected_version=expected_version,
            expected_plugin_build=expected_plugin_build, expected_route_sha256=expected_route_sha256,
            evidence_source=evidence_source, historical_source=verifier_source)


def _validate_alpha_calibration(binding, *, expected_version, expected_plugin_build,
                                expected_route_sha256, evidence_source, historical_source=None):
    """Reauthenticate original signed terminal and rehash current source bytes.

    Binding: directory, identity, terminal_sha256. The signed alpha-calibration
    event binds exact version/build/route, evidence_source, module SHA, and two
    bounded source files (houdini_raw, nuke_composite). Real host acceptance also
    requires both original native operations and their fixed observer sources.
    """
    try:
        if evidence_source not in ('software_test', 'real_host'):
            raise ValueError('ALPHA_CALIBRATION_EVIDENCE_SOURCE')
        directory, identity = Path(binding['directory']), binding['identity']
        start = owned_process.read_receipt(directory, 'started', identity=identity)
        stop = owned_process.read_receipt(directory, 'stopped', identity=identity)
        terminal = owned_process.read_receipt(directory, 'alpha-calibration', identity=identity)
        if not start or not stop or not terminal or owned_process.execution_returncode(stop) != 0:
            raise ValueError('ALPHA_CALIBRATION_EXECUTION_REQUIRED')
        if (binding['terminal_sha256'] != _sha(terminal)
                or terminal.get('started_sha256') != _sha(start)
                or terminal.get('stopped_sha256') != _sha(stop)
                or terminal.get('version') != expected_version
                or terminal.get('plugin_build') != expected_plugin_build
                or terminal.get('route_sha256') != expected_route_sha256
                or terminal.get('evidence_source') != evidence_source
                or terminal.get('verifier_sha256') != (historical_source['sha256'] if historical_source is not None
                    else hashlib.sha256(Path(__file__).read_bytes()).hexdigest())):
            raise ValueError('ALPHA_CALIBRATION_BINDING_MISMATCH')
        sources = terminal['sources']
        if set(sources) != {'houdini_raw', 'nuke_composite'}:
            raise ValueError('ALPHA_CALIBRATION_SOURCES_REQUIRED')
        raw, composite = (_file(sources[k]) for k in ('houdini_raw', 'nuke_composite'))
        if evidence_source == 'real_host':
            _validate_native_authority(terminal, sources, raw, composite, expected_version, historical_source=historical_source)
        associated = _numeric_observation(raw, composite)
        return {'schema': 'bridge.alpha-calibration/1.0', 'associated': associated, 'source_hashes': {k: v['sha256'] for k, v in sources.items()},
                'terminal_sha256': _sha(terminal), 'version': expected_version,
                'plugin_build': expected_plugin_build, 'route_sha256': expected_route_sha256,
                'evidence_source': evidence_source}
    except (KeyError, TypeError, AttributeError, OSError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('ALPHA_CALIBRATION_INVALID') from exc


def observe_native_nuke(nuke, *, chart_path, output_root, project_colorspace, expected_version='17.0v1', scene_profile=LEGACY):
    """Dedicated synthetic calibration only; call inside an owned native Nuke.

    Reads raw native Houdini chart pixels at frozen plate centers, composites
    over black/white and rereads written EXRs. No registry or generic input path
    is enabled by this function. Runtime knob/menu mismatches fail immediately.
    """
    fixture = definition(scene_profile)
    width, height = fixture['resolution']
    if nuke.NUKE_VERSION_STRING != expected_version:
        raise ValueError('ALPHA_NUKE_VERSION_MISMATCH')
    if project_colorspace != 'ACEScg':
        raise ValueError('ALPHA_PROJECT_COLOR_UNSUPPORTED')
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    chart = Path(chart_path).resolve(strict=True)
    if chart.suffix.lower() != '.exr':
        raise ValueError('ALPHA_CHART_EXR_REQUIRED')
    nodes = []
    def knob(node, name, value):
        field = node.knob(name)
        if field is None:
            raise ValueError('ALPHA_NUKE_KNOB_REQUIRED:' + name)
        field.setValue(value)
        actual = field.value()
        if name == 'format':
            valid = actual.name() == value and actual.width() == width and actual.height() == height
        elif isinstance(value, (tuple, list)):
            valid = tuple(actual) == tuple(value)
        else:
            valid = actual == value
        if not valid:
            raise ValueError('ALPHA_NUKE_READBACK_MISMATCH:' + name)
    def make(kind):
        node = getattr(nuke.nodes, kind)()
        nodes.append(node)
        return node
    def pixels(node):
        return [{'alpha': float(node.sample('rgba.alpha', x, y)),
                 'rgb': [float(node.sample('rgba.' + c, x, y)) for c in ('red', 'green', 'blue')]}
                for x, y in fixture['sample_pixels']]
    def file_record(path):
        raw = path.read_bytes()
        return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    def reader(path):
        node = make('Read')
        knob(node, 'file', str(path))
        knob(node, 'colorspace', project_colorspace)
        knob(node, 'raw', True)
        return node
    images = []
    try:
        nuke.frame(1)
        nuke.addFormat(f'{width} {height} 0 0 {width} {height} 1 bridge_alpha_calibration')
        source = reader(chart)
        if source.width() != width or source.height() != height:
            raise ValueError('ALPHA_CHART_RESOLUTION_MISMATCH')
        source_samples = pixels(source)
        associated = _numeric_mode(source_samples)
        current = source
        if not associated:
            premult = make('Premult'); premult.setInput(0, source); current = premult
        def composite(foreground, background, suffix):
            bg = make('Constant'); knob(bg, 'format', 'bridge_alpha_calibration')
            knob(bg, 'color', [background, background, background, 1.])
            merge = make('Merge2'); knob(merge, 'operation', 'over')
            merge.setInput(0, bg); merge.setInput(1, foreground)
            target = root / (suffix + '.exr')
            write = make('Write'); write.setInput(0, merge)
            knob(write, 'file', str(target)); knob(write, 'file_type', 'exr')
            knob(write, 'channels', 'rgba'); knob(write, 'colorspace', project_colorspace)
            knob(write, 'raw', True)
            nuke.execute(write, 1, 1)
            result = reader(target)
            samples = pixels(result)
            images.append(file_record(target))
            return samples
        black = composite(current, 0., 'over-black')
        white = composite(current, 1., 'over-white')
        additive = make('Constant'); knob(additive, 'format', 'bridge_alpha_calibration')
        knob(additive, 'color', [.125, .0625, .25, 0.])
        additive_black = composite(additive, 0., 'additive-black')
        additive_white = composite(additive, 1., 'additive-white')
        raw_result = {'schema': 'bridge.alpha-fixture-samples/1', 'samples': source_samples,
                      'chart': file_record(chart), 'native_version': nuke.NUKE_VERSION_STRING}
        if scene_profile != LEGACY:
            raw_result.update(scene_profile=scene_profile, resolution=fixture['resolution'], sample_pixels=fixture['sample_pixels'])
        composite_result = {'schema': 'bridge.alpha-composite-samples/1',
            'samples': [{'over_black': b['rgb'], 'over_white': w['rgb']} for b, w in zip(black, white)],
            'additive': {'alpha': 0, 'input_rgb': [.125, .0625, .25],
                         'over_black': additive_black[1]['rgb'], 'over_white': additive_white[1]['rgb']},
            'images': images, 'native_version': nuke.NUKE_VERSION_STRING}
        _numeric_observation(raw_result, composite_result)
        records = {}
        for name, value in [('houdini_raw', raw_result), ('nuke_composite', composite_result)]:
            path = root / (name + '.json')
            with path.open('xb') as stream: stream.write(owned_process._canonical(value))
            records[name] = file_record(path)
        return {'sources': records, 'chart': file_record(chart), 'images': images,
                'associated': associated, 'execution': 'native_nuke_readback'}
    finally:
        for node in reversed(nodes): nuke.delete(node)


def _numeric_mode(samples):
    # Opaque plus genuinely fractional pixels distinguish association without
    # imposing any RGB rule on alpha-zero source pixels.
    modes = [mode for mode in (True, False) if all(
        _close(sample['rgb'], [v * (a if mode else 1.) for v in EMISSION], RENDER_TOLERANCE)
        and abs(sample['alpha'] - a) <= RENDER_TOLERANCE
        for sample, a in zip(samples[1:], OPACITIES[1:]))]
    if len(modes) != 1:
        raise ValueError('ALPHA_CALIBRATION_AMBIGUOUS')
    return modes[0]


def _rehash_record(record, limit=512 * 1024 * 1024):
    path = Path(record['path'])
    if (not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > limit):
        raise ValueError('ALPHA_NATIVE_SOURCE_INVALID')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(block)
            if size > limit: raise ValueError('ALPHA_NATIVE_SOURCE_BUDGET')
            digest.update(block)
    if size != record['bytes'] or digest.hexdigest() != record['sha256']:
        raise ValueError('ALPHA_NATIVE_SOURCE_CHANGED')
    return record


def _required_writer_binding(start):
    error = start.get('writer_process_binding_error')
    if error is not None:
        detail = str(error).replace('\n', ' ').replace('\r', ' ')[:512]
        raise ValueError('ALPHA_NATIVE_WRITER_BINDING_REQUIRED:' + detail)
    image = start.get('writer_process_binding')
    if type(image) is not dict:
        raise ValueError('ALPHA_NATIVE_WRITER_BINDING_REQUIRED')
    return image


def validate_native_process_binding(start, stop, *, expected_executable, identity, command):
    """Check authenticated original receipts against trusted controller inputs.

    This performs offline validation after receipt authentication, never derives
    an expected executable from the observation, and never treats diagnostics as
    authority. Call before signing output or admitting the next native operation.
    """
    from dcc_task_runtime import process_image
    process_image._validate_expected(expected_executable)
    if (type(start) is not dict or type(stop) is not dict
            or start.get('schema') != owned_process.SCHEMA or start.get('event') != 'started'
            or stop.get('schema') != owned_process.SCHEMA or stop.get('event') != 'stopped'
            or start.get('identity') != identity or stop.get('identity') != identity
            or type(start.get('pid')) is not int or start['pid'] <= 0
            or stop.get('pid') != start['pid']
            or stop.get('started_sha256') != _sha(start)
            or type(command) is not list or not command
            or start.get('argv_sha256') != _sha(command)
            or str(Path(command[0]).resolve()) != expected_executable['image']['path']):
        raise ValueError('ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
    execution_code = owned_process.execution_returncode(stop)
    image = _required_writer_binding(start)
    if execution_code != 0:
        raise ValueError('ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
    try:
        if set(image) != {'expected_executable', 'host_anchor'}:
            raise ValueError('ALPHA_NATIVE_WRITER_BINDING_INVALID')
        process_image._validate_expected(image['expected_executable'])
        process_image._validate_observation(image['host_anchor'])
    except (KeyError, TypeError, ValueError) as cause:
        raise ValueError('ALPHA_NATIVE_WRITER_BINDING_INVALID:' + str(cause)) from cause
    anchor = image['host_anchor']
    if (image['expected_executable'] != expected_executable
            or anchor['pid'] != start['pid']
            or anchor['image'] != expected_executable['image']):
        raise ValueError('ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
    return image


def _validate_native_authority(terminal, sources, raw, composite, expected_version, *, historical_source=None):
    operations = terminal.get('native_operations')
    if type(operations) is not dict or set(operations) != {'houdini', 'nuke'}:
        raise ValueError('ALPHA_NATIVE_CALIBRATION_PRODUCER_REQUIRED')
    # 历史terminal固定旧观察器原路径；当前校验实现的__file__不冒充旧模块。
    verifier_path = Path(historical_source['path'] if historical_source is not None else __file__).resolve()
    repo = verifier_path.parents[4]
    fixed_sources = {'houdini': repo / 'tools/prepare_native_alpha_scene.py',
                     'nuke': verifier_path}
    outputs = {}
    for role, binding in operations.items():
        directory, identity = Path(binding['directory']), binding['identity']
        start = owned_process.read_receipt(directory, 'started', identity=identity)
        stop = owned_process.read_receipt(directory, 'stopped', identity=identity)
        output = owned_process.read_receipt(directory, 'alpha-output', identity=identity)
        if not start or not stop or not output or owned_process.execution_returncode(stop) != 0:
            raise ValueError('ALPHA_NATIVE_EXECUTION_REQUIRED')
        _required_writer_binding(start)
        source = _rehash_record(output['source'], 2 * 1024 * 1024)
        command = output['command']
        from dcc_task_runtime import process_image
        if type(command) is not list or not command:
            raise ValueError('ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
        # The original signed command is controller-issued; refreeze current
        # executable bytes rather than adopting an expectation from the anchor.
        executable_path = Path(command[0]).resolve()
        digest = _rehash_record(output['executable'])
        if digest['path'] != str(executable_path):
            raise ValueError('ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
        version = expected_version if role == 'houdini' else '17.0v1'
        if historical_source is None:
            expected_executable = process_image.freeze_executable(str(executable_path), version, digest['sha256'])
            image = validate_native_process_binding(start, stop,
                expected_executable=expected_executable, identity=identity, command=command)
        else:
            expected_executable = _required_writer_binding(start)['expected_executable']
            # 原signed expected、stop、anchor始终完整精确互证；fresh对象独立保存且不改写。
            image = validate_native_process_binding(start, stop,
                expected_executable=expected_executable, identity=identity, command=command)
            current_expected = process_image.verify_historical_executable(expected_executable,
                path=str(executable_path), version=version, sha256=digest['sha256'],
                completed_at=stop.get('observed_at'))
        anchor, executable_image = image['host_anchor'], expected_executable['image']
        if (source['path'] != str(fixed_sources[role])
                or binding['output_sha256'] != _sha(output)
                or output.get('started_sha256') != _sha(start)
                or output.get('stopped_sha256') != _sha(stop)
                or output.get('route_sha256') != terminal['route_sha256']
                or output.get('plugin_build') != terminal['plugin_build']
                or output.get('evidence_source') != 'real_host'
                or type(command) is not list or not command
                or start.get('argv_sha256') != _sha(command)
                or expected_executable.get('version') != (expected_version if role == 'houdini' else '17.0v1')
                or anchor.get('pid') != start.get('pid')
                or anchor.get('image') != executable_image
                or str(Path(command[0]).resolve()) != executable_image.get('path')):
            raise ValueError('ALPHA_NATIVE_OPERATION_BINDING_MISMATCH')
        if role == 'houdini' and (Path(command[0]).name != 'husk'
                or output['scene']['path'] not in command):
            raise ValueError('ALPHA_NATIVE_SCENE_COMMAND_MISMATCH')
        profile = raw.get('scene_profile', LEGACY)
        fixture = definition(profile)
        tail = ['--project-colorspace', 'ACEScg'] + ([] if profile == LEGACY else ['--scene-profile', profile])
        if role == 'nuke' and (len(command) != 8 + len(tail)
                or command[1:4] != ['-t', str(fixed_sources['nuke']), '--observe-native']
                or command[4] != '--chart' or command[6] != '--output-root'
                or command[8:] != tail
                or command[5] != output['chart']['path']
                or not Path(command[0]).name.startswith('Nuke17.0')):
            raise ValueError('ALPHA_NATIVE_OBSERVER_COMMAND_MISMATCH')
        _rehash_record({'path': executable_image['path'], 'sha256': executable_image['sha256'],
                        'bytes': executable_image['stat']['size']})
        outputs[role] = output
    if profile != LEGACY:
        from dcc_task_runtime.exr_codec import read_exr
        header = read_exr(outputs['houdini']['chart']['path'], with_pixels=False)
        if ([header['width'], header['height']] != fixture['resolution']
                or set(header['channels']) != set('RGBA')
                or raw.get('resolution') != fixture['resolution']
                or raw.get('sample_pixels') != fixture['sample_pixels']):
            raise ValueError('ALPHA_NATIVE_PROFILE_MISMATCH')
    chart = _rehash_record(outputs['houdini']['chart'])
    _rehash_record(outputs['houdini']['scene'], 2 * 1024 * 1024)
    if (outputs['nuke'].get('chart') != chart or raw.get('chart') != chart
            or outputs['nuke'].get('sources') != sources
            or raw.get('native_version') != '17.0v1'
            or composite.get('native_version') != '17.0v1'
            or len(composite.get('images', [])) != 4
            or outputs['nuke'].get('images') != composite['images']):
        raise ValueError('ALPHA_NATIVE_CHART_HANDOFF_MISMATCH')
    for image in composite['images']: _rehash_record(image)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Observe only a dedicated native alpha calibration chart inside Nuke')
    parser.add_argument('--observe-native', action='store_true', required=True)
    parser.add_argument('--chart', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--project-colorspace', required=True)
    parser.add_argument('--scene-profile', choices=[LEGACY, OFFICIAL], default=LEGACY)
    args = parser.parse_args()
    import nuke
    owned_process.runtime_ready_and_wait()
    result = observe_native_nuke(nuke, chart_path=args.chart, output_root=args.output_root,
                                project_colorspace=args.project_colorspace, scene_profile=args.scene_profile)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__': raise SystemExit(main())
