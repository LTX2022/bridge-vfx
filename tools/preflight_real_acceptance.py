#!/usr/bin/env python3
"""Read-only acceptance preflight. This tool never starts a host or model."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from readiness_evidence import DOMAINS, build_id
from prepare_workbuddy_graph import validate_media_config
ROOT = Path(__file__).resolve().parents[1]
VERSIONS = {'houdini': ('21.0.631', '22.0.429', '22.0.459'), 'nuke': ('17.0v1',)}
_MEDIA_UNSET = object()


def media_dependency(config, card, scope, *, media_config=_MEDIA_UNSET):
    """Read the fixed video dependency's identity; never invoke its binary."""
    required = False
    for document in (card, scope):
        references = document.get('references')
        if isinstance(references, list):
            required = required or any(isinstance(reference, dict) and reference.get('kind') == 'video'
                                       for reference in references)
    selected = config.get('controller_media', _MEDIA_UNSET) if media_config is _MEDIA_UNSET else media_config
    result = {'required': required, 'ffmpeg_started': False,
              'check_kind': 'static_file_and_execute_permission', 'errors': []}
    if not required:
        result['status'] = 'NOT_REQUIRED'
        return result
    if selected is _MEDIA_UNSET:
        result['status'] = 'BLOCKED' if required else 'NOT_REQUIRED'
        if required:
            result['errors'].append('controller_media.ffmpeg_executable: video reference requires project media configuration')
        return result
    try:
        validate_media_config(selected)
    except (OSError, ValueError, TypeError) as exc:
        result['errors'].append(str(exc))
    executable = selected.get('ffmpeg_executable') if isinstance(selected, dict) else None
    if isinstance(executable, str) and executable and Path(executable).is_absolute():
        path = Path(executable)
        result.update(configured_executable=executable, file_exists=path.is_file(),
                      executable=os.access(path, os.X_OK) and
                      (os.name != 'nt' or path.resolve().suffix.lower() in {'.exe', '.com'}))
        try:
            result['resolved_executable'] = str(path.resolve())
        except (OSError, RuntimeError) as exc:
            result['resolved_executable'] = None
            result['errors'].append('controller_media.ffmpeg_executable: cannot resolve: ' + type(exc).__name__)
        if path.is_file():
            try:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                result['observed_sha256'] = digest.hexdigest()
                result['hash_observation'] = 'READ_ONLY_NOT_RUNTIME_PINNED'
            except OSError as exc:
                result['hash_observation'] = 'UNAVAILABLE: ' + type(exc).__name__
    result['status'] = 'BLOCKED' if result['errors'] else 'READY'
    return result


def _canonical_sha256(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_valid(snapshot, request_id):
    if not isinstance(snapshot, dict): return False
    if snapshot.get('request_id') != request_id or not snapshot.get('source'): return False
    for key in ('operation_ids', 'request_operation_ids'):
        values = snapshot.get(key)
        if (not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))):
            return False
    supplied = snapshot.get('snapshot_sha256')
    observed = _canonical_sha256({key:value for key,value in snapshot.items() if key != 'snapshot_sha256'})
    return isinstance(supplied, str) and supplied == observed


def validate(config, card, scope, *, media_config=_MEDIA_UNSET, _media_dependency=None):
    errors = []
    if card.get('domain_pack') not in DOMAINS: errors.append('unknown domain')
    case_id = card.get('case_id')
    if not isinstance(case_id, str) or not case_id: errors.append('case_id required')
    case_ids = card.get('case_ids', [case_id])
    if (not isinstance(case_ids, list) or not case_ids
            or any(not isinstance(value, str) or not value for value in case_ids)
            or len(case_ids) != len(set(case_ids)) or case_id not in case_ids):
        errors.append('card case_ids must be unique nonempty IDs including case_id')
        case_ids = []
    required_versions = card.get('required_versions', {})
    if not isinstance(required_versions, dict):
        errors.append('card required_versions must be an object')
        required_versions = {}
    applications = ['nuke'] if card.get('domain_pack') == 'nuke_composite_v1' else ['houdini']
    if card.get('composite'): applications.append('nuke')
    for app in applications:
        host = config.get(app, {})
        if host.get('version') not in VERSIONS[app]: errors.append(app + ': explicit supported version required')
        if 'required_versions' in card:
            allowed = required_versions.get(app)
            if (not isinstance(allowed, list) or not allowed
                    or any(not isinstance(value, str) or not value for value in allowed)):
                errors.append(app + ': card required_versions must declare a nonempty version list')
            elif host.get('version') not in allowed:
                errors.append(app + ': configured version is not allowed by card required_versions')
        if not host.get('plugin_build'): errors.append(app + ': plugin build required')
        try:
            if not Path(host['executable']).is_file(): errors.append(app + ': executable missing')
        except (KeyError, TypeError): errors.append(app + ': executable required')
    for field in ('expected_nodes','expected_connections','key_parameters','native_basis','save_reopen','stop_recovery','artifact_checks','raw_evidence_path','human_checks'):
        if not card.get(field): errors.append('card missing ' + field)
    if card.get('native_basis_status') != 'VERIFIED_SOURCE': errors.append('native interface basis unresolved')
    frames = scope.get('frames', [])
    if not isinstance(frames, list) or not 1 <= len(frames) <= 12 or any(type(f) is not int for f in frames) or len(set(frames)) != len(frames): errors.append('1..12 distinct integer frames required')
    seconds = scope.get('seconds')
    if type(seconds) not in (float,int) or not math.isfinite(seconds) or not 0 < seconds <= 120: errors.append('time budget must be 0..120 seconds')
    if type(scope.get('disk_bytes')) is not int or scope['disk_bytes'] <= 0: errors.append('positive disk budget required')
    if scope.get('case_id') not in case_ids or scope.get('domain_pack') != card.get('domain_pack'): errors.append('scope/card mismatch')
    if scope.get('confirmed') is not True or not scope.get('confirmed_by'): errors.append('explicit operator resource confirmation required')
    if not scope.get('task_root') or not scope.get('content_version'): errors.append('task root and content version required')
    request_id = scope.get('request_id')
    if not isinstance(request_id, str) or not request_id: errors.append('request_id required for operation-bound preflight')
    before = scope.get('operation_snapshot_before')
    after = scope.get('operation_snapshot_after')
    if (not _snapshot_valid(before, request_id) or not _snapshot_valid(after, request_id)
            or set(before.get('operation_ids', [])) != set(after.get('operation_ids', []))
            or set(before.get('request_operation_ids', [])) != set(after.get('request_operation_ids', []))):
        errors.append('request-bound before/after operation snapshots must prove no new operation or launch')
    if scope.get('cache'):
        for key in ('path','estimated_bytes','invalidation_scope','frames','content_version'):
            if not scope['cache'].get(key): errors.append('cache confirmation missing ' + key)
        if scope['cache'].get('frames') != frames or scope['cache'].get('content_version') != scope.get('content_version'): errors.append('cache scope mismatch')
    dependency = _media_dependency if _media_dependency is not None else media_dependency(config, card, scope, media_config=media_config)
    errors.extend(dependency['errors'])
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--media-config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scope = {}
    dependency = {'status':'NOT_CHECKED', 'ffmpeg_started':False}
    try:
        config, card, scope = (json.loads(p.read_text()) for p in (args.config,args.card,args.scope))
        media_config = json.loads(args.media_config.read_text()) if args.media_config else _MEDIA_UNSET
        dependency = media_dependency(config, card, scope, media_config=media_config)
        errors = validate(config, card, scope, media_config=media_config, _media_dependency=dependency)
    except (OSError,ValueError,TypeError) as exc:
        errors = [str(exc)]
    request_id = scope.get('request_id') if isinstance(scope, dict) else None
    before = scope.get('operation_snapshot_before') if isinstance(scope, dict) else None
    after = scope.get('operation_snapshot_after') if isinstance(scope, dict) else None
    proof = {
        'request_id': request_id,
        'operation_created': False,
        'launch_attempted': False,
        'host_started': False,
        'snapshot_before': before,
        'snapshot_after': after,
    }
    receipt = {'schema':'bridge.readiness.preflight_event/1','phase':'preflight',
               'case_id':scope.get('case_id') if isinstance(scope, dict) else None,
               'stage':'preflight','build_id':build_id(ROOT),'request_id':request_id,
               'host_started':False,'model_called':False,'passed':not errors,'errors':errors,
               'media_dependency':dependency,
               'no_operation_proof':proof,
               'next_step':'Trusted controller must separately validate the exact same scope at live launch; this receipt grants no launch authority.'}
    receipt['event_id'] = _canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return 0 if not errors else 1

if __name__ == '__main__': raise SystemExit(main())
