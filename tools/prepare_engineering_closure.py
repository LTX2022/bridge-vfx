#!/usr/bin/env python3
"""Freeze one reviewable engineering scope; never import or launch a DCC."""
import argparse
import hashlib
import json
import secrets
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCOPE_ID = 'engineering-closure-20261020-h21-03'
OUTPUT = ROOT / 'outputs' / SCOPE_ID
SUPERSEDED_SCOPE = ROOT / 'outputs/engineering-closure-20261020-h21-02/scope.json'
H21 = Path('/Applications/Houdini/Houdini21.0.631/Frameworks/Houdini.framework/Versions/Current/Resources')
NUKE = Path('/Applications/Nuke17.0v1/Nuke17.0v1.app/Contents/MacOS/Nuke17.0')


def frozen_file(path):
    path = path.expanduser().resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def prepare(project_id=None, project_colorspace=None, *, key):
    if type(key) is not bytes or len(key) != 32:
        raise ValueError('SCOPE_ACCOUNTING_KEY_REQUIRED')
    if (project_id is None) != (project_colorspace is None):
        raise ValueError('project-id and project-colorspace must be supplied together')
    color = None
    if project_id is not None:
        sys.path.insert(0, str(ROOT / 'packages/dcc-task-runtime/src'))
        from dcc_task_runtime.project_color import validate_project_color
        color = validate_project_color({'schema': 'bridge.project-color/1.0', 'project_id': project_id,
            'revision': 1, 'colorspace': project_colorspace, 'source': 'human_project_selection'})
    hosts = {name: frozen_file(path) for name, path in {
        'hython': H21 / 'bin/hython', 'husk': H21 / 'bin/husk', 'nuke': NUKE,
        'supervisor_python': Path(sys.executable)}.items()}
    ocio = H21 / 'packages/ocio/houdini-config-v2.1.0_aces-v1.3_ocio-v2.3.ocio'
    config = frozen_file(ocio)
    config['selected_token_declared'] = bool(color and ('name: ' + color['colorspace']) in ocio.read_text())
    return {'schema': 'bridge.engineering-closure-scope/1', 'scope_id': SCOPE_ID,
        'status': 'PREPARED_NOT_AUTHORIZED', 'host_started': False,
        'execution_authorized': False,
        'accounting': {'key_path': str(OUTPUT / '.native-control/receipt.key'),
            'key_sha256': hashlib.sha256(key).hexdigest()},
        'supersedes': {'scope_id': 'engineering-closure-20261020-h21-02', **frozen_file(SUPERSEDED_SCOPE)},
        'output_root': str(OUTPUT), 'new_project_only': True,
        'versions': {'houdini': '21.0.631', 'nuke': '17.0v1'}, 'hosts': hosts,
        'project_color': color,
        'native_color_tokens': {'houdini_static_config': config,
            'nuke': 'NATIVE_MENU_READBACK_REQUIRED', 'runtime_readback_required': True},
        'budget': {'per_operation_seconds': 120, 'total_seconds': 600, 'max_dcc_starts': 8,
            'max_disk_bytes': 512 * 1024 * 1024, 'max_heavy_operations': 1, 'automatic_retries': 0},
        'operations': [
            {'id': 'alpha-h21', 'host': 'husk', 'purpose': 'fixed source-bound constant-emission opacity 0/0.5/1 USD chart; render one frame'},
            {'id': 'alpha-nuke', 'host': 'nuke', 'purpose': 'native source pixel readback; over black/white; additive-alpha-zero preservation; write/readback EXRs'},
            {'id': 'formal-h21', 'host': 'hython', 'purpose': 'fresh sphere_ground_v2 single 128x128 frame and authenticated controlled output verification'},
            {'id': 'consume-nuke', 'host': 'nuke', 'purpose': 'consume only authenticated registered artifact; save/write/readback'}],
        'alpha_fixture': {'emission_color': [.8, .8, .8], 'base': 0, 'specular': 0, 'emission': 1,
            'opacity': [0, .5, 1], 'karma_absolute_tolerance': .02, 'nuke_absolute_tolerance': 1e-4,
            'native_material_contract': frozen_file(ROOT / 'docs/native-basis/hda-interface-capture.json'),
            'native_fixture_readback_required': True, 'execution': 'NOT_RUN'},
        'exclusions': ['Houdini22', 'existing Desktop project', 'models', 'vendor compilation', 'simulation', 'cache', 'automatic retry'],
        'stop_on': ['native parameter/menu readback mismatch', 'alpha ambiguous or additive RGB lost',
            'missing original signed terminal', 'unexpected process/build/file identity', 'any budget exhausted'],
        'required_before_launch': ['shared scope admission for control hosts, graph workers, Nuke workers and husk descendants',
            'explicit approval of this frozen scope and final runtime bindings',
            'native chart generator and observer fixed source hashes frozen',
            'route flags and original calibration operations authenticated',
            'project color selection' if color is None else 'native Houdini/Nuke ACEScg menu readback']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id')
    parser.add_argument('--project-colorspace')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / 'packages/dcc-task-runtime/src'))
    from dcc_task_runtime.native_scope import NativeScope
    target = OUTPUT / 'scope.json'
    try:
        if target.exists():
            raw = target.read_bytes()
            binding = {'path': str(target), 'sha256': hashlib.sha256(raw).hexdigest()}
            native = NativeScope(binding)
            native.snapshot()
            scope = prepare(args.project_id, args.project_colorspace, key=native.key_path.read_bytes())
            expected = (json.dumps(scope, ensure_ascii=False, indent=2) + '\n').encode()
            if raw != expected:
                raise ValueError('frozen scope differs; prepare a separate scope rather than overwrite')
        else:
            if ((OUTPUT / '.native-control').exists() or (OUTPUT / 'native-scope-state.json').exists()):
                raise ValueError('accounting originals already exist; initialization cannot repair or overwrite them')
            key = secrets.token_bytes(32)
            scope = prepare(args.project_id, args.project_colorspace, key=key)
            raw = (json.dumps(scope, ensure_ascii=False, indent=2) + '\n').encode()
            OUTPUT.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream: stream.write(raw)
            binding = {'path': str(target), 'sha256': hashlib.sha256(raw).hexdigest()}
            NativeScope.initialize(binding, key=key).snapshot()
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({'scope': str(target), 'sha256': hashlib.sha256(raw).hexdigest(), 'host_started': False}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
