#!/usr/bin/env python3
"""Resume output verification/registration without launching or reconnecting a DCC."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


def _alpha_configuration(config, result_path):
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime.alpha_calibration import validate_alpha_calibration
    scope = NativeScope(config.get('native_scope'))
    scope.check()
    path = Path(result_path)
    expected = scope.root/'alpha-calibration-result.json'
    if (not path.is_absolute() or path != path.resolve() or path != expected
            or any(p.is_symlink() for p in (path,*path.parents))
            or not path.is_file() or not 0 < path.stat().st_size <= 1024*1024):
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_RESULT_PATH_INVALID')
    result = json.loads(path.read_text(encoding='utf-8'))
    if (result.get('schema') != 'bridge.alpha-runner.result/1'
            or result.get('scope_sha256') != scope.binding['sha256']):
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_RESULT_SCOPE_MISMATCH')
    binding, claimed = result.get('alpha_calibration'), result.get('calibration')
    if not isinstance(binding,dict) or not isinstance(claimed,dict):
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_RESULT_INVALID')
    directory = Path(binding.get('directory',''))
    if (not directory.is_absolute() or directory != directory.resolve()
            or not directory.is_relative_to(scope.root)
            or any(p.is_symlink() for p in (directory,*directory.parents))):
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_RESULT_PATH_INVALID')
    source = config.get('evidence_source')
    verified = validate_alpha_calibration(binding, expected_version=config['version'],
        expected_plugin_build=config['plugin_build'], expected_route_sha256=claimed.get('route_sha256'),
        evidence_source=source)
    if verified != claimed:
        raise ValueError('CONTROLLED_OUTPUT_ALPHA_RESULT_MISMATCH')
    # The render verifier independently matches this signed calibration route
    # against the original render's observed configuration before registration.
    detached = json.loads(json.dumps(config,allow_nan=False))
    detached['alpha_calibration'] = binding
    return detached


def resume(project, render_operation, request_id, artifact_id=None, *, alpha_result_path=None):
    from dcc_task_runtime.artifact_registry import ArtifactRegistry
    from vfx_pipeline.workbuddy_assembly import production_host_client
    from vfx_pipeline.workbuddy_graph_mcp import GraphRun
    project = Path(project).resolve(strict=True)
    control = project / 'control'
    snapshot = control / 'snapshot'
    if ROOT != snapshot:
        raise ValueError('CONTROLLED_OUTPUT_USE_FROZEN_PROJECT_ENTRY')
    manifest = control / 'run.json'
    index = control / 'snapshot-manifest.json'
    saved = json.loads((control / 'production-hosts.json').read_text(encoding='utf-8'))
    config = saved['hosts']['houdini']
    if alpha_result_path is not None:
        config = _alpha_configuration(config,alpha_result_path)
    host = production_host_client(config, control / 'host-state')
    host.bind_task(saved['task_id'])
    registry = ArtifactRegistry(control / 'artifact_ledger')
    host.bind_artifact_registry(registry)
    facade = GraphRun(manifest, None, task_id=saved['task_id'], host_client=host,
                      artifact_registry=registry, save_root=str(project / 'saves'))
    facade.controller_source = {
        'manifest_path': str(manifest),
        'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'snapshot_manifest_sha256': hashlib.sha256(index.read_bytes()).hexdigest(),
        'repo_root': str(snapshot), 'backend': 'production',
        'software_processes': saved['hosts']['houdini'].get('evidence_source') == 'software_test',
    }
    result = facade.verify_render_output(request_id, render_operation)
    if artifact_id is not None:
        fact = result['execution_fact']
        image = fact['metadata']['1']
        result['artifact'] = facade.register_render_artifact(
            artifact_id, 'preview_temp', fact['output_pattern'], fact['frame_set'],
            image['colorspace'], image['premultiplied'], request_id)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--render-operation', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--artifact-id')
    parser.add_argument('--alpha-result',type=Path)
    args = parser.parse_args()
    result = resume(args.project, args.render_operation, args.request_id, args.artifact_id, alpha_result_path=args.alpha_result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
