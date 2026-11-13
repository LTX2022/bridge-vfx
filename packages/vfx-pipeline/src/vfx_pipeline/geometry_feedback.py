"""两版之后的有限反馈：独立许可、单次派发与只读历史接收，旧任务账本不变。"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import math
from pathlib import Path
import secrets
import subprocess
import time

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.execution_lock import execution_lock
from dcc_task_runtime.platform_support import atomic_write, ensure_private_directory, process_identity
from houdini_bridge.official_karma_observation import checked_bytes, file_record
from . import geometry_graph
from .geometry_session import GeometrySession, _goal_view, _id, _text, _plain, _object

SCHEMA = 'bridge.geometry-feedback-authority/1'
STATE = 'bridge.geometry-feedback-state/1'
PREPARATION = 'bridge.geometry-feedback-preparation/1'
MAX_REVISION = 99
ROOT = Path(__file__).resolve().parents[4]


def _fail(code):
    raise ValueError('GEOMETRY_FEEDBACK_' + code)


def _write(path, value, *, new=False):
    path = _plain(path)
    ensure_private_directory(path.parent)
    if new and path.exists():
        _fail('EXISTING_RECORD_REQUIRES_QUERY')
    atomic_write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode(), owned_root=path.parent)
    return file_record(path)


def _runtime():
    from .task_creation import _runtime as current
    return current()


def _signed(registry, value):
    from .task_creation import _signed as sign
    return sign(registry, value)


def _verified(registry, path):
    from .task_creation import _verified as verify
    return verify(registry, path)


def validate_authority(record):
    """每次认证精确签名与不可变来源；从不准入进程或刷新旧消耗。"""
    value = json.loads(checked_bytes(record))
    if not isinstance(value, dict) or not isinstance(value.get('payload'), dict):
        _fail('AUTHORITY_REQUIRED')
    registry = _plain(value['payload'].get('registry', ''))
    payload = _verified(registry, Path(record['path']))
    fields = {'schema', 'registry', 'project_id', 'task_id', 'source_preparation', 'source_result', 'source_acceptance',
              'source_job', 'baseline_result', 'baseline_acceptance', 'baseline_job', 'source_scope', 'source_accounting',
              'source_accounting_prefix', 'source_execution_grant', 'runtime', 'worker', 'plan', 'request_id', 'scope_root',
              'instruction', 'artifact_version', 'budget', 'roles'}
    checkpoint = 'checkpoint' in payload
    if set(payload) != fields | ({'checkpoint'} if checkpoint else set()) | ({'checkpoint_prior'} if checkpoint and 'checkpoint_prior' in payload else set()) or payload['schema'] != SCHEMA:
        _fail('AUTHORITY_BINDING_INVALID')
    plan = payload['plan']
    if (not isinstance(plan, dict) or plan.get('schema') != 'bridge.geometry-feedback-plan/1'
            or type(plan.get('revision')) is not int or not ((plan['revision'] == 2) if checkpoint else (3 <= plan['revision'] <= MAX_REVISION))
            or plan.get('base_revision') != plan['revision'] - 1 or plan.get('task_id') != payload['task_id']
            or canonical_sha256({k: v for k, v in plan.items() if k != 'plan_sha256'}) != plan.get('plan_sha256')
            or geometry_graph.selector(plan['model_graph']) != plan['selector'] or payload['artifact_version'] != 1):
        _fail('PLAN_BINDING_INVALID')
    _id(payload['request_id']); _id(payload['project_id']); _text(payload['instruction'], 20, 8000)
    root = _plain(payload['scope_root'])
    parent_root = Path(payload['source_preparation']['path']).parent
    origin_root = Path(payload['baseline_result']['path']).parents[2]
    if (root.parent != origin_root / 'feedback-runs' or Path(record['path']) != root / 'authorization.json'
            or root == parent_root or root.is_relative_to(parent_root / 'jobs')):
        _fail('ROOT_BINDING_INVALID')
    from dcc_task_runtime.geometry_feedback_scope import limits
    budget, roles = limits(checkpoint)
    if payload['budget'] != budget or payload['roles'] != roles:
        _fail('BUDGET_CHANGED')
    for name in ('source_preparation', 'source_result', 'source_acceptance', 'source_job', 'baseline_result',
                 'baseline_acceptance', 'baseline_job', 'source_scope', 'source_accounting', 'runtime', 'worker'):
        checked_bytes(payload[name])
    if payload['source_execution_grant'] is not None:
        checked_bytes(payload['source_execution_grant'])
    parent = json.loads(checked_bytes(payload['source_result']))
    baseline = json.loads(checked_bytes(payload['baseline_result']))
    if (parent.get('task_id') != payload['task_id'] or baseline.get('task_id') != payload['task_id']
            or parent.get('revision') != plan['base_revision'] or baseline.get('revision') != 1
            or parent.get('operation_id') != plan['parent_operation_id']
            or baseline.get('operation_id') != plan['baseline_operation_id']
            or parent.get('preparation') != payload['source_preparation']):
        _fail('SOURCE_RESULT_CHANGED')
    from dcc_task_runtime.native_scope import NativeScope
    native = NativeScope({k: payload['source_scope'][k] for k in ('path', 'sha256')})
    if native.scope['task_id'] != payload['task_id']:
        _fail('SOURCE_SCOPE_CHANGED')
    frozen = json.loads(checked_bytes(payload['source_accounting']))
    envelope = native._verify_envelope(frozen)
    prefix = payload['source_accounting_prefix']
    journal = _plain(prefix['path'])
    if journal != native.journal_path or type(prefix.get('bytes')) is not int or not 0 < prefix['bytes'] <= 8 * 1024 * 1024:
        _fail('SOURCE_PREFIX_REQUIRED')
    with journal.open('rb') as stream:
        raw = stream.read(prefix['bytes'])
    if len(raw) != prefix['bytes'] or hashlib.sha256(raw).hexdigest() != prefix['sha256'] or raw.splitlines()[-1] != native._canonical(frozen):
        _fail('SOURCE_PREFIX_CHANGED')
    usage = native.completed_snapshot()
    if (envelope['state']['tickets'] != usage['tickets'] or envelope['state']['closed_reason'] != ('NATIVE_SCOPE_EXECUTION_FAILED' if checkpoint else None)
            or any(t['stopped_at'] is None for t in usage['tickets'])):
        _fail('SOURCE_ALL_STOPS_REQUIRED')
    if checkpoint:
        from .geometry_cold_checkpoint import inspect
        inspect(payload, native, usage)
    package = Path(payload['runtime']['path']).parent
    plugin = _object(package / 'plugin.json')
    manifest = json.loads(checked_bytes(payload['runtime']))
    if (plugin.get('name') != 'bridge-vfx' or plugin.get('version') not in ('0.4.20', '0.4.21', '0.4.22', '0.4.23')
            or canonical_sha256(manifest.get('files')) != manifest.get('file_manifest_sha256')
            or payload['worker'] != file_record(package / 'runtime/tools/run_geometry_creative.py')):
        _fail('RUNTIME_BINDING_INVALID')
    return payload


def _execution_binding(authority):
    payload = validate_authority(authority)
    root = Path(payload['scope_root'])
    bound = _verified(Path(payload['registry']), root / 'execution-binding.json')
    expected = {'schema': 'bridge.geometry-feedback-execution-binding/1', 'authority': authority,
                'preparation': file_record(root / 'geometry-preparation.json'), 'scope': file_record(root / 'scope.json')}
    if bound != expected:
        _fail('EXECUTION_BINDING_CHANGED')
    return payload, bound


def verify_job(job, native=None, *, for_execution=False, runtime_root=None, require_dispatch=True):
    """作业、准备、授权和当前快照逐项绑定，公开模型不能提供worker或预算。"""
    authority = job.get('feedback_authority')
    payload, bound = _execution_binding(authority)
    prep = json.loads(checked_bytes(bound['preparation']))
    root = Path(payload['scope_root'])
    expected_operation='geo_feedback_'+hashlib.sha256((payload['request_id']+payload['plan']['plan_sha256']).encode()).hexdigest()[:24]
    directory = root / 'jobs' / expected_operation
    required={'schema','preparation','operation_id','task_id','revision','directory','plan','execution_worker','feedback_authority'}
    if (set(job)!=required or job.get('operation_id')!=expected_operation
            or job.get('schema') != 'bridge.geometry-job/1' or job.get('preparation') != bound['preparation']
            or job.get('task_id') != payload['task_id'] or job.get('plan') != payload['plan']
            or job.get('revision') != payload['plan']['revision'] or job.get('directory') != str(directory)
            or job.get('execution_worker') != payload['worker'] or prep.get('feedback_authority') != authority
            or prep.get('schema') != PREPARATION or prep.get('scope') != {k: bound['scope'][k] for k in ('path', 'sha256')}
            or prep.get('task_id') != payload['task_id']):
        _fail('JOB_BINDING_CHANGED')
    if file_record(directory / 'job.json') != file_record(_plain(job['directory']) / 'job.json') or _object(directory / 'job.json') != job:
        _fail('JOB_CHANGED')
    if native is not None and native.binding != prep['scope']:
        _fail('NATIVE_BINDING_CHANGED')
    if for_execution and require_dispatch:
        original_root=Path(payload['baseline_result']['path']).parents[2]
        front=_object(original_root/'feedback-state.json')
        request=front.get('execution_requests',{}).get(payload['request_id'])
        entry=front.get('jobs',{}).get(expected_operation)
        intent=_object(directory/'controller-launch-intent.json')
        expected_command=[prep['supervisor_python'],'-I','-B',payload['worker']['path'],'run-job','--job',str(directory/'job.json')]
        if (request not in ({'state':'INTENT','operation_id':expected_operation,'plan_id':payload['plan']['plan_id']},
                            {'state':'DISPATCHED','operation_id':expected_operation,'plan_id':payload['plan']['plan_id']})
                or not isinstance(entry,dict) or entry.get('job_file')!=file_record(directory/'job.json')
                or entry.get('authority')!=authority or intent!={'command':expected_command,'job':file_record(directory/'job.json'),
                    'request_id':payload['request_id']}):
            _fail('DISPATCH_BINDING_REQUIRED')
    if for_execution:
        active = Path(runtime_root or ROOT)
        package_runtime = Path(payload['runtime']['path']).parent / 'runtime'
        snapshot = directory / 'project/control/snapshot'
        if active not in (package_runtime, snapshot):
            _fail('EXECUTION_RUNTIME_REQUIRED')
        relative = 'packages/vfx-pipeline/src/vfx_pipeline/geometry_feedback.py'
        manifest = json.loads(checked_bytes(payload['runtime']))
        actual = file_record(active / relative)
        if {'path': 'runtime/' + relative, 'bytes': actual['bytes'], 'sha256': actual['sha256']} not in manifest['files']:
            _fail('EXECUTION_MODULE_CHANGED')
    checkpoint = None
    if 'checkpoint' in payload:
        from dcc_task_runtime.native_scope import NativeScope
        from .geometry_cold_checkpoint import inspect
        source = NativeScope({k: payload['source_scope'][k] for k in ('path', 'sha256')})
        checkpoint = inspect(payload, source, source.completed_snapshot(), verify_warm=for_execution)
    return {'authority': payload, 'preparation': prep, 'checkpoint': checkpoint,
            'parent': json.loads(checked_bytes(payload['source_result'])),
            'baseline': json.loads(checked_bytes(payload['baseline_result']))}


def verify_resume(authority, source, control, scheduler):
    """仅为已签补充作业改用新范围；原GraphRun来源仍按旧scope认证。"""
    control = _plain(control)
    job = _object(control.parents[1] / 'job.json')
    details = verify_job(job)
    payload = details['authority']
    if (job['feedback_authority'] != authority or source != details['parent']['graph_source']
            or control != Path(job['directory']) / 'project/control'
            or Path(scheduler) != Path(payload['scope_root']) / 'scheduler'):
        _fail('RESUME_BINDING_CHANGED')
    return details['preparation']['scope']


def resolve_execution_plugin(binding, control, alpha, *, authority):
    """继续使用原已校准addon的精确字节，不把旧grant变成新版许可。"""
    payload, bound = _execution_binding(authority)
    if binding != {k: bound['scope'][k] for k in ('path', 'sha256')}:
        _fail('PLUGIN_SCOPE_CHANGED')
    control = _plain(control)
    job = _object(control.parents[1] / 'job.json')
    verify_resume(authority, json.loads(checked_bytes(payload['source_result']))['graph_source'], control, Path(payload['scope_root']) / 'scheduler')
    if job.get('feedback_authority') != authority:
        _fail('PLUGIN_JOB_CHANGED')
    parent_prep = json.loads(checked_bytes(payload['source_preparation']))
    expected = copy.deepcopy(parent_prep['hosts']['houdini']['alpha_calibration'])
    plugin = copy.deepcopy(expected['plugin_reuse']['active_plugin'])
    checked_bytes(plugin)
    expected['plugin_reuse']['active_plugin']['path'] = str(control / 'snapshot/plugins/houdini/_impl/houdini_bridge_addon.py')
    if alpha != expected:
        _fail('PLUGIN_ALPHA_CHANGED')
    return plugin


class FeedbackSession:
    """在原任务旁维护修订状态；两版原前端状态和原原生账本保持只读。"""
    def __init__(self, base):
        self.base = base
        self.root = base.root
        self.path = self.root / 'feedback-state.json'

    def _read(self):
        old = self.base._read()
        if old['revision'] not in (1, 2):
            _fail('TWO_ACCEPTED_REVISIONS_REQUIRED')
        if not self.path.exists():
            return {'schema': STATE, 'preparation': self.base.preparation, 'task_id': self.base.prep['task_id'], 'revision': old['revision'],
                    'assets': copy.deepcopy(old['assets']), 'served': {}, 'observations': {}, 'plans': {}, 'jobs': {},
                    'completed': [], 'authorizations': {}, 'execution_requests': {}, 'current_model_graph': copy.deepcopy(old['current_model_graph'])}
        state = _object(self.path)
        if (state.get('schema') != STATE or state.get('preparation') != self.base.preparation
                or state.get('task_id') != self.base.prep['task_id'] or type(state.get('revision')) is not int
                or not old['revision'] <= state['revision'] <= MAX_REVISION
                or len(state.get('completed', [])) != state['revision'] - old['revision']
                or any(not isinstance(state.get(k), dict) for k in ('assets', 'served', 'observations', 'plans', 'jobs', 'authorizations', 'execution_requests'))):
            _fail('STATE_INVALID')
        return state

    def _write(self, state):
        _write(self.path, state)

    def current_result(self, state=None):
        state = state or self._read()
        old = self.base._read()
        if state['revision'] == old['revision']:
            return GeometrySession.query(self.base,old['completed'][-1])
        return self.query(state['completed'][-1])

    def model(self, state):
        view = self.current_result(state)
        result = json.loads(checked_bytes(view['original_result']))
        model = result['plan']['model_graph']
        if model != state['current_model_graph']:
            _fail('CURRENT_MODEL_CHANGED')
        return copy.deepcopy(model)

    def catalog(self):
        state = self._read()
        original_state=GeometrySession._read(self.base)
        value=GeometrySession._observe_accepted(self.base,original_state,original_state['jobs'][original_state['completed'][-1]],
            json.loads(checked_bytes(original_state['jobs'][original_state['completed'][-1]]['job_file'])))
        value={'task_id':self.base.prep['task_id'],'revision':state['revision'],'public_brief':self.base.prep['public_brief'],
               'feedback':self.base.prep['feedback'],'model_catalog':geometry_graph.model_catalog(),'native_dispatch_attempted':False}
        value.update(revision=state['revision'], current_model_graph=self.model(state),
                     assets=[{k: v for k, v in item.items() if k != 'file'} for item in state['assets'].values()],
                     supplemental_execution={'required': True, 'max_dispatches_per_authorization': 1,
                                             'instruction': 'Propose edits against the current revision. An operator must authorize this exact plan and execution request with authorize-feedback before bridge_execute.'})
        return value

    def media(self, asset_id):
        _id(asset_id)
        with execution_lock(self.root, 'geometry-feedback'):
            state = self._read(); asset = state['assets'].get(asset_id)
            if not asset:
                _fail('REGISTERED_MEDIA_REQUIRED')
            raw = checked_bytes(asset['file'])
            if len(raw) > 4 * 1024 * 1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                _fail('PNG_MEDIA_REQUIRED')
            from .controller_media import FixedPngDecoder
            image = FixedPngDecoder(max_dimension=2048).decode(Path(asset['file']['path']))
            state['served'].setdefault(self.base.connection_id, {})[asset_id] = copy.deepcopy(asset['file'])
            self._write(state)
            from .workbuddy_mcp import _text_content
            return [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(raw).decode()},
                    _text_content({'asset_id': asset_id, 'revision': asset['revision'], 'sha256': asset['file']['sha256'], 'width': image['width'], 'height': image['height']})]

    def observe(self, asset_id, request_id, observation):
        _id(asset_id); _id(request_id); _text(observation, 10, 4000)
        with execution_lock(self.root, 'geometry-feedback'):
            state = self._read(); asset = state['assets'].get(asset_id)
            if not asset or state['served'].get(self.base.connection_id, {}).get(asset_id) != asset['file']:
                _fail('VIEW_ACTUAL_MEDIA_FIRST')
            checked_bytes(asset['file'])
            body = {'asset_id': asset_id, 'file': asset['file'], 'observation': observation}
            digest = canonical_sha256(body); old = state['observations'].get(request_id)
            if old:
                if old['request_sha256'] != digest:
                    _fail('REQUEST_CONFLICT')
                return {'observation_id': request_id, 'idempotent': True}
            state['observations'][request_id] = {**body, 'observation_id': request_id, 'connection_id': self.base.connection_id, 'request_sha256': digest}
            self._write(state)
            return {'observation_id': request_id, 'accepted': True}

    def propose(self, request_id, base_revision, goal, rationale, observation_ids, model_graph=None, edits=None):
        _id(request_id); _text(goal, 10, 2000); _text(rationale, 20, 4000)
        if type(base_revision) is not int or not 2 <= base_revision < MAX_REVISION:
            _fail('BASE_REVISION_REQUIRED')
        if not isinstance(observation_ids, list) or not 2 <= len(observation_ids) <= 8 or len(set(observation_ids)) != len(observation_ids):
            _fail('OBSERVATIONS_REQUIRED')
        if model_graph is not None:
            _fail('FEEDBACK_EDITS_REQUIRED')
        body = {'base_revision': base_revision, 'goal': goal, 'rationale': rationale, 'observation_ids': observation_ids, 'edits': edits}
        digest = canonical_sha256(body)
        with execution_lock(self.root, 'geometry-feedback'):
            state = self._read(); old = state['plans'].get(request_id)
            if old:
                if old['request_sha256'] != digest:
                    _fail('REQUEST_CONFLICT')
                return {'plan_id': request_id, 'revision': old['revision'], 'plan_sha256': old['plan_sha256'], 'idempotent': True}
            if state['revision'] != base_revision:
                _fail('PLAN_BASE_STALE')
            if any(j['state'] not in ('COMPLETE', 'FAILED', 'CANCELLED') and not (Path(j['directory'])/'error.json').is_file()
                   for j in state['jobs'].values()):
                _fail('JOB_STILL_ACTIVE')
            observed = set()
            for oid in observation_ids:
                _id(oid); item = state['observations'].get(oid)
                asset = state['assets'].get(item['asset_id']) if item else None
                if not item or not asset or item['file'] != asset['file']:
                    _fail('OBSERVATION_STALE')
                checked_bytes(item['file']); observed.add(item['asset_id'])
            required = {f'preview_{base_revision}', f'local_{base_revision}'}
            if not required <= observed:
                _fail('REQUIRED_VIEWS_MISSING')
            from .geometry_entry import validate_edit_inputs
            validate_edit_inputs({'current_model_graph': self.model(state)}, edits)
            model = self.model(state); nodes = {n['node_id']: n for n in model['nodes']}; touched = set()
            for edit in edits:
                if edit['node_id'] in touched or any(type(v) not in (int, float) or not math.isfinite(v) for v in edit['parms'].values()):
                    _fail('FINITE_DISTINCT_EDITS_REQUIRED')
                touched.add(edit['node_id']); nodes[edit['node_id']]['parameters'].update(edit['parms'])
            model = geometry_graph.model_proposal(model).to_dict()
            if model == state['current_model_graph']:
                _fail('DISTINCT_GEOMETRY_CHANGE_REQUIRED')
            old_state = self.base._read()
            plan = {'schema': 'bridge.geometry-feedback-plan/1', 'task_id': state['task_id'], 'plan_id': request_id,
                    'base_revision': base_revision, 'revision': base_revision + 1, 'goal': goal, 'rationale': rationale,
                    'observation_ids': list(observation_ids), 'model_graph': model, 'edits': copy.deepcopy(edits),
                    'selector': geometry_graph.selector(model), 'request_sha256': digest,
                    'parent_operation_id': state['completed'][-1] if state['completed'] else old_state['completed'][-1],
                    'baseline_operation_id': old_state['completed'][0]}
            plan['plan_sha256'] = canonical_sha256(plan)
            state['plans'][request_id] = plan; self._write(state)
            return {'plan_id': request_id, 'revision': plan['revision'], 'plan_sha256': plan['plan_sha256'], 'ready': True,
                    'supplemental_authorization_required': True}

    def execute(self, plan_id, request_id):
        _id(plan_id); _id(request_id)
        with execution_lock(self.root, 'geometry-feedback'):
            state = self._read(); auth = state['authorizations'].get(plan_id)
            if not auth:
                _fail('OPERATOR_AUTHORIZATION_REQUIRED')
            payload, bound = _execution_binding(auth)
            if payload['runtime']!=_runtime():
                _fail('CURRENT_RUNTIME_AUTHORIZATION_REQUIRED')
            if payload['request_id'] != request_id or payload['plan'] != state['plans'].get(plan_id):
                _fail('AUTHORIZED_REQUEST_REQUIRED')
            old = state['execution_requests'].get(request_id)
            if old:
                if old['plan_id'] != plan_id:
                    _fail('REQUEST_CONFLICT')
                return {'operation_id': old['operation_id'], 'state': state['jobs'][old['operation_id']]['state'], 'idempotent': True, 'controller_dispatch_attempted': False}
            plan = payload['plan']
            if plan['base_revision'] != state['revision']:
                _fail('PLAN_BASE_STALE')
            if any(j['state'] not in ('COMPLETE', 'FAILED', 'CANCELLED') for j in state['jobs'].values()):
                _fail('JOB_STILL_ACTIVE')
            root = Path(payload['scope_root'])
            operation = 'geo_feedback_' + hashlib.sha256((request_id + plan['plan_sha256']).encode()).hexdigest()[:24]
            directory = root / 'jobs' / operation
            job = {'schema': 'bridge.geometry-job/1', 'preparation': bound['preparation'], 'operation_id': operation,
                   'task_id': payload['task_id'], 'revision': plan['revision'], 'directory': str(directory), 'plan': plan,
                   'execution_worker': payload['worker'], 'feedback_authority': auth}
            job_path=directory/'job.json'
            if job_path.exists():
                if (_object(job_path)!=job or (directory/'controller-launch-intent.json').exists()
                        or (directory/'execute-owner.json').exists()):
                    _fail('PREPARED_JOB_CHANGED_OR_ALREADY_STARTED')
            else:
                _write(job_path,job,new=True)
            state['jobs'][operation] = {'operation_id': operation, 'state': 'UNKNOWN', 'revision': plan['revision'], 'plan_id': plan_id,
                                        'directory': str(directory), 'job_file': file_record(directory / 'job.json'), 'authority': auth}
            state['execution_requests'][request_id] = {'state': 'INTENT', 'operation_id': operation, 'plan_id': plan_id}
            self._write(state)
            prep = json.loads(checked_bytes(bound['preparation']))
            command = [prep['supervisor_python'], '-I', '-B', payload['worker']['path'], 'run-job', '--job', str(directory / 'job.json')]
            _write(directory / 'controller-launch-intent.json', {'command': command, 'job': file_record(directory / 'job.json'), 'request_id': request_id}, new=True)
            try:
                with (directory / 'controller.stdout.log').open('xb') as stdout, (directory / 'controller.stderr.log').open('xb') as stderr:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                               cwd=directory, env=dict(prep['environment']), start_new_session=True)
                launch = {'pid': process.pid, 'process_identity': process_identity(process.pid), 'started_at': time.time()}
                _write(directory / 'controller-started.json', launch, new=True)
                state['jobs'][operation].update(state='QUEUED', controller=file_record(directory / 'controller-started.json'))
                state['execution_requests'][request_id]['state'] = 'DISPATCHED'; self._write(state)
                return {'operation_id': operation, 'state': 'QUEUED', 'controller_dispatch_attempted': True, 'next_poll_seconds': 10}
            except BaseException:
                # INTENT留存；未知启动不能通过重试、换request或重新签同一plan重派。
                return {'operation_id': operation, 'state': 'UNKNOWN', 'controller_dispatch_attempted': 'unknown', 'blocked': True}

    def query(self, operation_id):
        _id(operation_id); state = self._read(); entry = state['jobs'].get(operation_id)
        if not entry:
            return GeometrySession.query(self.base,operation_id)
        directory = Path(entry['directory']); job = json.loads(checked_bytes(entry['job_file']))
        details = verify_job(job)
        payload = details['authority']
        result_path = directory / 'result.json'
        if not result_path.exists():
            error = directory / 'error.json'
            if error.exists():
                value = _object(error)
                from dcc_task_runtime.native_scope import NativeScope
                native=NativeScope(details['preparation']['scope'])
                try:
                    usage=native.completed_snapshot()
                except ValueError as error:
                    if str(error)!='NATIVE_SCOPE_COMPLETED_STOP_REQUIRED':
                        raise
                    return {'operation_id':operation_id,'state':'UNKNOWN','blocked':True,
                            'error_code':'FEEDBACK_STOP_UNCONFIRMED','native_dispatch_attempted':False}
                if not value.get('stop_confirmed'):
                    return {'operation_id':operation_id,'state':'UNKNOWN','blocked':True,
                            'error_code':'FEEDBACK_STOP_UNCONFIRMED','native_dispatch_attempted':False}
                if (value.get('task_id') != payload['task_id'] or value.get('operation_id') != operation_id
                        or value.get('preparation_record') != job['preparation'] or not value.get('stop_confirmed')
                        or any(t['stopped_at'] is None for t in usage['tickets'])):
                    _fail('FAILED_RESULT_BINDING_REQUIRED')
                with execution_lock(self.root, 'geometry-feedback'):
                    state = self._read(); state['jobs'][operation_id]['state'] = value['state']; self._write(state)
                return {'operation_id': operation_id, 'state': value['state'], 'error_code': value['code'], 'blocked': True, 'native_dispatch_attempted': False}
            return {'operation_id': operation_id, 'state': 'UNKNOWN' if entry['state'] == 'UNKNOWN' else 'RUNNING',
                    'action': 'OBSERVE_ORIGINAL', 'next_poll_seconds': 10, 'native_dispatch_attempted': False}
        result_record = file_record(result_path); result = json.loads(checked_bytes(result_record))
        acceptance_path = directory / 'accepted-result.json'
        if operation_id in state['completed']:
            receipt = self._accepted(entry, job, result, result_record)
        else:
            from .geometry_job import validate_result
            validation = validate_result(job['preparation'], job, result)
            if validation.get('state') != 'VERIFIED':
                _fail('RESULT_VERIFICATION_REQUIRED')
            with execution_lock(self.root, 'geometry-feedback'):
                state = self._read(); entry = state['jobs'][operation_id]
                if operation_id not in state['completed']:
                    if job['revision'] != state['revision'] + 1 or file_record(result_path) != result_record:
                        _fail('COMPLETION_ORDER_CHANGED')
                    if not acceptance_path.exists():
                        from dcc_task_runtime.native_scope import NativeScope
                        native = NativeScope(details['preparation']['scope'])
                        body = self._accepted_body(entry, job, result_record)
                        body.update(validation=validation, native_snapshot=native.completed_snapshot())
                        _write(acceptance_path, {'payload': body, 'signature': self._signature(native, body)}, new=True)
                    receipt = self._accepted({**entry, 'acceptance': file_record(acceptance_path)}, job, result, result_record)
                    _goal_view(result, receipt['validation'])
                    entry.update(state='COMPLETE', result=result_record, acceptance=file_record(acceptance_path))
                    state['completed'].append(operation_id); state['revision'] = job['revision']; state['current_model_graph'] = copy.deepcopy(job['plan']['model_graph'])
                    for name, key in ((f"preview_{job['revision']}", 'preview'), (f"local_{job['revision']}", 'local_preview')):
                        state['assets'][name] = {'asset_id': name, 'file': result['files'][key], 'kind': 'image', 'role': 'actual_render_preview' if key == 'preview' else 'actual_render_local_preview', 'revision': job['revision']}
                    self._write(state)
                else:
                    receipt = self._accepted(entry, job, result, result_record)
        return {'operation_id': operation_id, 'task_id': payload['task_id'], 'state': 'COMPLETE', 'revision': job['revision'],
                **_goal_view(result, receipt['validation']), 'action': 'ACCEPTED_RESULT_OBSERVED', 'result_view': 'accepted_immutable',
                'historical': job['revision'] < self._read()['revision'], 'observation_only': True, 'consumable_for_new_execution': False,
                'fresh_consumption_verified': False, 'native_dispatch_attempted': False, 'original_result': result_record,
                'acceptance_receipt': file_record(acceptance_path), 'files': result['files']}

    @staticmethod
    def _signature(native, payload):
        return hmac.new(native._key(), b'bridge.geometry-feedback-accepted/1\0' + native._canonical(payload), hashlib.sha256).hexdigest()

    def _accepted_body(self, entry, job, result_record):
        return {'schema': 'bridge.geometry-feedback-accepted/1', 'preparation': job['preparation'], 'authority': job['feedback_authority'],
                'task_id': job['task_id'], 'operation_id': job['operation_id'], 'revision': job['revision'],
                'job': entry['job_file'], 'result': result_record}

    def _accepted(self, entry, job, result, result_record):
        record = entry.get('acceptance')
        if not record or record['path'] != str(Path(entry['directory']) / 'accepted-result.json'):
            _fail('ACCEPTANCE_REQUIRED')
        value = json.loads(checked_bytes(record))
        from dcc_task_runtime.native_scope import NativeScope
        prep = json.loads(checked_bytes(job['preparation'])); native = NativeScope(prep['scope'])
        body = value.get('payload')
        expected = self._accepted_body(entry, job, result_record)
        if (not isinstance(body, dict) or set(body) != set(expected) | {'validation', 'native_snapshot'}
                or any(body.get(k) != v for k, v in expected.items())
                or not hmac.compare_digest(str(value.get('signature')), self._signature(native, body))):
            _fail('ACCEPTANCE_CHANGED')
        for record in result['files'].values():
            checked_bytes(record)
        _goal_view(result, body['validation'])
        return body

    def tasks(self):
        return [{'operation_id': key, 'task_id': self.base.prep['task_id'], 'revision': value['revision'], 'state': value['state']}
                for key, value in self._read()['jobs'].items()]

    def cancel(self, operation_id):
        state = self._read(); entry = state['jobs'].get(operation_id)
        if not entry:
            return GeometrySession.cancel(self.base,operation_id)
        if entry['state'] in ('COMPLETE', 'FAILED', 'CANCELLED'):
            return {'operation_id': operation_id, 'state': entry['state'], 'cancel_requested': False, 'native_dispatch_attempted': False}
        _write(Path(entry['directory']) / 'cancel-request.json', {'operation_id': operation_id, 'requested_at': time.time()})
        return {'operation_id': operation_id, 'state': entry['state'], 'cancel_requested': True, 'stop_confirmed': False, 'native_dispatch_attempted': False}


def authorize(registry, project_id, plan_id, request_id, instruction, *, supersede_operation=None, checkpoint_operation=None, checkpoint_replacement=None):
    """操作者只签一个已保存计划和确定请求；新范围不授予重建或校准权。"""
    from .project_entry import read_projects
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime.geometry_feedback_scope import limits, ROLE_SECONDS, SCHEMA as SCOPE_SCHEMA, RESOURCE_PROFILE
    from .artifact_registry import ArtifactRegistry
    _id(project_id); _id(plan_id); _id(request_id); _text(instruction, 20, 8000)
    registry = _plain(registry); item = read_projects(registry)['projects'].get(project_id)
    if not item or item['kind'] not in ('geometry', 'geometry_task'):
        _fail('EDITABLE_PROJECT_REQUIRED')
    base = GeometrySession(item['preparation']); session = FeedbackSession(base)
    with execution_lock(base.root, 'geometry-feedback'):
        state = session._read(); plan = state['plans'].get(plan_id)
        checkpoint = None; checkpoint_prior = None
        if checkpoint_operation is not None:
            _id(checkpoint_operation)
            if (supersede_operation is not None or state['revision'] != 1
                    or base._read()['revision'] != 1):
                _fail('ONE_CHECKPOINT_AUTHORIZATION_REQUIRED')
            from .geometry_cold_checkpoint import records, plan_for
            checkpoint = records(base, checkpoint_operation)
            if checkpoint_replacement is not None:
                _id(checkpoint_replacement)
                if (len(state['authorizations']) != 1 or set(state['jobs']) != {checkpoint_replacement}
                        or plan_id in state['plans'] or request_id in state['execution_requests']):
                    _fail('ONE_CHECKPOINT_REPLACEMENT_REQUIRED')
                prior = state['jobs'][checkpoint_replacement]
                if prior['state'] != 'FAILED':
                    _fail('CHECKPOINT_REPLACEMENT_STOP_REQUIRED')
                prior_directory = Path(prior['directory'])
                checkpoint_prior = {'authority': prior['authority'], 'job': prior['job_file'],
                                    'error': file_record(prior_directory/'error.json'),
                                    'journal': file_record(prior_directory/'incremental-state.json')}
            elif state['authorizations'] or state['jobs']:
                _fail('ONE_CHECKPOINT_AUTHORIZATION_REQUIRED')
            failed_job = json.loads(checked_bytes(checkpoint['job']))
            plan = plan_for(failed_job['plan'], plan_id, base._read()['completed'][0])
            state['plans'][plan_id] = plan
        BUDGET, ROLES = limits(checkpoint is not None)
        if checkpoint is None and (state['revision'] == 1 or checkpoint_replacement is not None):
            _fail('COLD_CHECKPOINT_REQUIRED')
        if not plan or plan['task_id'] != base.prep['task_id'] or plan['base_revision'] != state['revision']:
            _fail('CURRENT_PLAN_REQUIRED')
        if supersede_operation is not None:
            _id(supersede_operation)
            prior=state['jobs'].get(supersede_operation)
            if not prior or prior['state'] not in ('UNKNOWN','QUEUED','FAILED'):
                _fail('SUPERSEDE_FAILED_OPERATION_REQUIRED')
            failed_dir=Path(prior['directory']);error=_object(failed_dir/'error.json')
            if (error.get('task_id')!=base.prep['task_id'] or error.get('operation_id')!=supersede_operation
                    or (failed_dir/'result.json').exists()):
                _fail('SUPERSEDE_FAILURE_BINDING_REQUIRED')
            owner=failed_dir/'execute-owner.json';controller=failed_dir/'controller-started.json'
            from dcc_task_runtime.platform_support import process_status
            for path in (owner,controller):
                if not path.is_file():
                    _fail('SUPERSEDE_OWNER_REQUIRED')
                identity=_object(path)['process_identity']
                if process_status(identity)!='stopped':
                    _fail('SUPERSEDE_OWNER_STILL_ALIVE')
            previous_payload,previous_bound=_execution_binding(prior['authority'])
            previous_native=NativeScope({k:previous_bound['scope'][k] for k in ('path','sha256')})
            usage=previous_native.snapshot()
            for ticket in usage['tickets']:
                directory=Path(ticket['directory'])
                if (ticket['role']!='houdini-host' or ticket['stopped_at'] is not None
                        or (directory/'started.json').exists() or (directory/'stopped.json').exists()
                        or not (directory/'supervisor.stderr.log').is_file()
                        or 'ModuleNotFoundError' not in (directory/'supervisor.stderr.log').read_text()
                        or "No module named 'vfx_pipeline'" not in (directory/'supervisor.stderr.log').read_text()):
                    _fail('SUPERSEDE_PRESTART_FAILURE_REQUIRED')
            marker={'schema':'bridge.geometry-feedback-superseded-prestart/1','operation_id':supersede_operation,
                    'original_authority':prior['authority'],'original_job':prior['job_file'],'original_error':file_record(failed_dir/'error.json'),
                    'preserved_native_state':file_record(previous_native.state_path),'replacement_plan_id':plan_id,
                    'replacement_request_id':request_id,'instruction':instruction,'native_stop_claimed':False}
            record=_write(failed_dir/'operator-superseded.json',_signed(registry,marker),new=True)
            prior.update(state='FAILED',superseded=record)
            session._write(state)
        if any(j['state'] not in ('COMPLETE', 'FAILED', 'CANCELLED') for j in state['jobs'].values()):
            _fail('JOB_STILL_ACTIVE')
        if plan_id in state['authorizations']:
            payload, _ = _execution_binding(state['authorizations'][plan_id])
            if payload['request_id'] != request_id or payload['instruction'] != instruction or payload['runtime'] != _runtime():
                _fail('AUTHORIZATION_CONFLICT')
            return {'state': 'FEEDBACK_AUTHORIZED', 'revision': plan['revision'], 'authority': state['authorizations'][plan_id], 'max_dispatches': 1, 'budget': BUDGET, 'idempotent': True}
        parent_view = session.current_result(state)
        old = base._read(); baseline_view = base.query(old['completed'][0])
        parent = json.loads(checked_bytes(parent_view['original_result']))
        parent_prep_record = parent['preparation']; parent_prep = json.loads(checked_bytes(parent_prep_record))
        native = NativeScope(parent_prep['scope']); usage = native.completed_snapshot()
        if usage['closed_reason'] != ('NATIVE_SCOPE_EXECUTION_FAILED' if checkpoint else None) or any(t['stopped_at'] is None for t in usage['tickets']):
            _fail('SOURCE_ALL_STOPS_REQUIRED')
        parent_entry = (state['jobs'].get(plan['parent_operation_id']) or old['jobs'][plan['parent_operation_id']])
        digest = hashlib.sha256((plan['plan_sha256'] + request_id).encode()).hexdigest()[:20]
        root = base.root / 'feedback-runs' / ('revision-' + str(plan['revision']) + '-' + digest)
        if root.exists():
            _fail('PARTIAL_AUTHORIZATION_QUERY_REQUIRED')
        runtime = _runtime(); package = Path(runtime['path']).parent
        grant_path = base.root / 'execution-grant.json'
        prefix = native.journal_path.read_bytes()
        payload = {'schema': SCHEMA, 'registry': str(registry), 'project_id': project_id, 'task_id': base.prep['task_id'],
                   'source_preparation': parent_prep_record, 'source_result': parent_view['original_result'], 'source_acceptance': parent_view['acceptance_receipt'],
                   'source_job': parent_entry['job_file'], 'baseline_result': baseline_view['original_result'], 'baseline_acceptance': baseline_view['acceptance_receipt'],
                   'baseline_job': old['jobs'][old['completed'][0]]['job_file'], 'source_scope': file_record(native.path),
                   'source_accounting': file_record(native.state_path), 'source_accounting_prefix': {'path': str(native.journal_path), 'bytes': len(prefix), 'sha256': hashlib.sha256(prefix).hexdigest()},
                   'source_execution_grant': file_record(grant_path) if grant_path.exists() else None, 'runtime': runtime,
                   'worker': file_record(package / 'runtime/tools/run_geometry_creative.py'), 'plan': copy.deepcopy(plan), 'request_id': request_id,
                   'scope_root': str(root), 'instruction': instruction, 'artifact_version': 1, 'budget': BUDGET, 'roles': ROLES}
        if checkpoint is not None:
            from .geometry_cold_checkpoint import inspect
            payload['checkpoint'] = checkpoint
            if checkpoint_prior is not None:
                payload['checkpoint_prior'] = checkpoint_prior
            inspect(payload, native, usage, verify_warm=True)
        authority = _write(root / 'authorization.json', _signed(registry, payload), new=True)
        key = secrets.token_bytes(32)
        scope = copy.deepcopy(native.scope)
        for field in ('resource_profile', 'role_seconds', 'source_reuse', 'feedback_authority'):
            scope.pop(field, None)
        scope.update(schema=SCOPE_SCHEMA, resource_profile=RESOURCE_PROFILE, scope_id='feedback-' + digest,
                     output_root=str(root), budget=copy.deepcopy(BUDGET), role_seconds=copy.deepcopy(ROLE_SECONDS),
                     feedback_authority=authority, execution_authorized=True, status='AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION',
                     authorization={'authority': 'current_user_instruction', 'instruction': instruction},
                     accounting={'key_path': str(root / '.native-control/key'), 'key_sha256': hashlib.sha256(key).hexdigest()})
        if checkpoint is not None:
            from .geometry_task_templates import collector_policy
            scope['process_image_policy'] = collector_policy(native.scope, parent_prep.get('task_template'))
        scope_record = _write(root / 'scope.json', scope, new=True)
        scope_binding = {k: scope_record[k] for k in ('path', 'sha256')}
        NativeScope.initialize(scope_binding, key=key)
        prep = copy.deepcopy(parent_prep)
        prep.update(schema=PREPARATION, scope=scope_binding, feedback_authority=authority,
                    worker=payload['worker']['path'], ledger_root=str(root / 'artifact_ledger'))
        prep.pop('task_creation', None)
        for name, filename in (('configuration', 'geometry-configuration.json'), ('criteria', 'private-evaluation.json')):
            prep[name] = _write(root / filename, json.loads(checked_bytes(parent_prep[name])), new=True)
        media = {}
        for name, record in parent_prep['media'].items():
            path = root / 'media' / (name + '.png'); ensure_private_directory(path.parent); path.write_bytes(checked_bytes(record)); media[name] = file_record(path)
        prep['media'] = media
        prep['source_reuse'] = _write(root / 'source-reuse.json', {'schema': 'bridge.geometry-feedback-source/1', 'task_id': payload['task_id'], 'feedback_authority': authority}, new=True)
        prep['nuke_template'] = parent['files']['nk']
        prep['template_main_pattern'] = str(Path(parent['files']['main']['path']).with_name('main.%04d.exr'))
        prep['template_nuke_pattern'] = str(Path(parent['files']['nuke']['path']).with_name('nuke.%04d.exr'))
        for kind, cfg in prep['hosts'].items():
            cfg.pop('task_creation_origin', None)
            cfg.update(task_root=str(root), native_scope=scope_binding, resource_budget={'roots': [str(root)], 'max_bytes': BUDGET['max_disk_bytes'], 'native_scope': scope_binding}, feedback_ledger_root=str(root / 'artifact_ledger'))
            if kind == 'houdini':
                cfg['geometry_feedback_authority'] = authority
        ArtifactRegistry(root / 'artifact_ledger')
        prep['environment'] = dict(parent_prep['environment'])
        prep['environment']['HOUDINI_USER_PREF_DIR'] = str(root / 'runtime/houdini-prefs/__HVER__')
        prep['model_route'] = {'route': 'BridgeSupplementalFeedback', 'selected_model': 'operator', 'reasoning_effort': 'not_applicable', 'provider_identity': 'not_applicable'}
        prep_record = _write(root / 'geometry-preparation.json', prep, new=True)
        binding_payload = {'schema': 'bridge.geometry-feedback-execution-binding/1', 'authority': authority, 'preparation': prep_record, 'scope': scope_record}
        _write(root / 'execution-binding.json', _signed(registry, binding_payload), new=True)
        state['authorizations'][plan_id] = authority; session._write(state)
        return {'state': 'FEEDBACK_AUTHORIZED', 'task_id': payload['task_id'], 'revision': plan['revision'], 'authority': authority,
                'max_dispatches': 1, 'budget': BUDGET, 'roles': ROLES, 'request_id': request_id}
