"""Explicit construction-only MCP route, separate from immutable diagnostics."""
import hashlib
import json
import math
import os
import re
import stat
import time
from pathlib import Path, PureWindowsPath

from dcc_task_runtime.graph_compiler import GraphCompileError
from houdini_bridge.native_render_scene import SUPPORTED_PROFILES
from . import graph_catalog
from .workbuddy_project import DiagnosticRun
from .workbuddy_mcp import DiagnosticMCP, TOOLS, IDENTIFIER, OBSERVATION, _schema, _text_content


SHORT_PROPOSAL = _schema({
    'schema_version': {'type': 'string', 'enum': ['1.0']},
    'nodes': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': _schema({
        'node_id': IDENTIFIER, 'node_type': {'type': 'string'},
        'context': {'type': 'string', 'enum': ['houdini_sop','houdini_obj','houdini_dop','houdini_lop','houdini_vop','houdini_rop']},
        'parameters': {'type': 'object'},
        'subnet_path':{'type':'array','maxItems':8,'items':IDENTIFIER},
    }, ('node_id', 'node_type', 'context'))},
    'connections': {'type': 'array', 'maxItems': 16, 'items': _schema({
        'source_node': {'type': 'string'}, 'source_port': {'type': 'string'},
        'target_node': {'type': 'string'}, 'target_port': {'type': 'string'},
        'target_index': {'type': 'integer', 'minimum': 0},
    }, ('source_node','source_port','target_node','target_port'))},
    'outputs': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': _schema({
        'output_id': IDENTIFIER, 'node_id': {'type': 'string'}, 'port': {'type': 'string'},
    }, ('output_id','node_id','port'))},
}, ('nodes','connections','outputs'))
PROPOSAL = {'anyOf':[SHORT_PROPOSAL,_schema({
    'schema':{'type':'string','enum':['bridge.registered-domain-construction/1']},
    'domain_pack':{'type':'string','enum':graph_catalog.registered_domain_ids()},
    'houdini_version':{'type':'string','enum':list(graph_catalog.HOUDINI_VERSIONS)},
    'native_branch':{'type':'string','enum':['softbody','grains']},
    'scene_profile':{'type':'string','enum':list(SUPPORTED_PROFILES)},
},('schema','domain_pack','houdini_version'))]}
GRAPH_TOOLS = [
    {'name':'submit_observation', 'description':'Persist your bounded observation using a stable request ID. Source video observations require the media_basis_id returned by the selected media_video_frames call. Does not certify vision or execute DCC.', 'inputSchema':_schema({'asset_id':IDENTIFIER,'request_id':IDENTIFIER,'observation':OBSERVATION,'media_basis_id':{'type':'string','pattern':'^selection-[0-9a-f]{32}$'}},('asset_id','request_id','observation'))},
    {'name':'media_attachments', 'description':'Return bounded actual attachments for registered synthetic media IDs; failures never fall back to text.', 'inputSchema':_schema({'asset_ids':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':IDENTIFIER}},('asset_ids',))},
    {'name':'media_video_frames', 'description':'Select up to 12 explicit zero-based frames from a registered local synthetic video using the controller fixed decoder. Every selection, including replay, returns a media_basis_id to bind the subsequent source video observation.', 'inputSchema':_schema({'asset_id':IDENTIFIER,'frames':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'integer','minimum':0}}},('asset_id','frames'))},
    {'name':'media_sequence_diagnostics', 'description':'Measure registered image pixels against the controller frozen expected/active frame interval; never certifies visual correctness.', 'inputSchema':_schema({'asset_ids':{'type':'array','minItems':1,'maxItems':12,'items':IDENTIFIER},'frame_numbers':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'integer','minimum':0}}},('asset_ids','frame_numbers'))},
    {'name':'graph_version', 'description':'Read the current durable editable graph version and invalidated downstream nodes/outputs.', 'inputSchema':_schema({'graph_id':IDENTIFIER},('graph_id',))},
    {'name':'graph_catalog', 'description':'Read allowed construction nodes, ports and typed parameter limits. Catalog declarations do not imply visual acceptance.', 'inputSchema':_schema()},
    {'name':'graph_propose', 'description':'Compile your own bounded network after submitting image observations. No host execution in this step.', 'inputSchema':_schema({'proposal':PROPOSAL,'request_id':IDENTIFIER},('proposal','request_id'))},
    {'name':'graph_trial', 'description':'Start a registered graph through the task-owned Houdini host/process boundary. Saves and checks an editable HIP; no simulation/cache/render. Reuse request ID when retrying.', 'inputSchema':_schema({'graph_id':IDENTIFIER,'request_id':IDENTIFIER},('graph_id','request_id'))},
    {'name':'graph_status', 'description':'Query persistent operation status and controller-recorded output evidence. Unknown execution is not success and must not be resubmitted under a new ID.', 'inputSchema':_schema({'operation_id':IDENTIFIER},('operation_id',))},
    {'name':'frame_execute', 'description':'Submit a persistent frame operation (at most 12 specified frames) through the shared scheduler. Same request+content reuses the recorded operation; changed content is refused.', 'inputSchema':_schema({'request_id':IDENTIFIER,'frames':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'integer','minimum':1}},'budget_seconds':{'type':'number','exclusiveMinimum':0,'maximum':120}},('request_id','frames'))},
    {'name':'houdini_render_bounded', 'description':'Render a registered saved HIP through the supervised task-owned Houdini host, with exact frames and persistent producer facts.', 'inputSchema':_schema({'request_id':IDENTIFIER,'saved_scene_id':IDENTIFIER,'render_target':{'type':'string'},'pattern':{'type':'string'},'frames':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'integer','minimum':1}},'budget_seconds':{'type':'number','exclusiveMinimum':0,'maximum':120}},('request_id','saved_scene_id','render_target','pattern','frames'))},
    {'name':'verify_render_output', 'description':'Verify an original completed controlled render after its owned process has stopped; controller policy and calibration only.', 'inputSchema':_schema({'request_id':IDENTIFIER,'operation_id':IDENTIFIER},('request_id','operation_id'))},
    {'name':'nuke_render_bounded', 'description':'Bounded Nuke render from a verified ledger artifact through a controller-owned Read→Write binding (max 12 frames, output under the controller save root). Preserves registered color/alpha; optional values must match. Returns a queryable operation with its host-boundary kind.', 'inputSchema':_schema({'request_id':IDENTIFIER,'artifact_id':IDENTIFIER,'pattern':{'type':'string'},'frames':{'type':'array','minItems':1,'maxItems':12,'uniqueItems':True,'items':{'type':'integer','minimum':1}},'colorspace':{'type':'string'},'premultiplied':{'type':'boolean'}},('request_id','artifact_id','pattern','frames'))},
    {'name':'operation_query', 'description':'Query a host-side persistent frame operation (pure read; never starts work).', 'inputSchema':_schema({'operation_id':IDENTIFIER},('operation_id',))},
    {'name':'operation_cancel', 'description':'Request cancellation of a graph operation. Cancellation is a request; the stop is confirmed separately.', 'inputSchema':_schema({'operation_id':IDENTIFIER},('operation_id',))},
    {'name':'feedback_edit', 'description':'Edit parameters of a REGISTERED graph node inside the task-owned leased root; catalog ranges enforced.', 'inputSchema':_schema({'graph_id':IDENTIFIER,'node_id':IDENTIFIER,'parms':{'type':'object','minProperties':1,'maxProperties':16},'task_id':IDENTIFIER},('graph_id','node_id','parms','task_id'))},
    {'name':'task_save', 'description':'Save the task scene with a content receipt (host-side ownership checks apply).', 'inputSchema':_schema()},
    {'name':'task_reopen', 'description':'Reopen a controller-registered task HIP by saved_scene_id; path/hash come from the service registry, never from the model.', 'inputSchema':_schema({'saved_scene_id':IDENTIFIER},('saved_scene_id',))},
    {'name':'consume_artifact', 'description':'Resolve a registered artifact for Nuke input; verifies frame set, freshness and the operation receipt. Reference images can never pass as renders.', 'inputSchema':_schema({'artifact_id':IDENTIFIER},('artifact_id',))},
]
for tool in GRAPH_TOOLS:
    tool['annotations'] = {'readOnlyHint':tool['name'] in ('graph_catalog','graph_status','operation_query'), 'destructiveHint':False,'idempotentHint':tool['name'] != 'media_video_frames','openWorldHint':False}


def _schema_error(value, schema, path='$'):
    """Return a deterministic JSON-schema subset error, or ``None``.

    The MCP adapter is a trust boundary.  Python's permissive ``int``/``float``
    conversions are deliberately not used here: booleans, numeric strings,
    non-finite numbers, unknown object keys and frame-shape coercions must be
    rejected before a facade or host client is called.
    """
    if not isinstance(schema, dict):
        return '{}: invalid schema'.format(path)
    if 'anyOf' in schema:
        alternatives=schema['anyOf']
        if not isinstance(alternatives,list) or not alternatives:
            return '{}: invalid schema'.format(path)
        if all(_schema_error(value,option,path) is not None for option in alternatives):
            return '{}: no permitted schema matches'.format(path)
        return None
    if 'enum' in schema and value not in schema['enum']:
        return '{}: value is not in enum'.format(path)
    expected = schema.get('type')
    if expected == 'object':
        if not isinstance(value, dict):
            return '{}: expected object'.format(path)
        properties = schema.get('properties') or {}
        required = schema.get('required') or []
        missing = [name for name in required if name not in value]
        if missing:
            return '{}: missing required properties'.format(path)
        if schema.get('additionalProperties') is False:
            extra = set(value) - set(properties)
            if extra:
                return '{}: unknown properties'.format(path)
        elif isinstance(schema.get('additionalProperties'), dict):
            for key in set(value) - set(properties):
                error = _schema_error(value[key], schema['additionalProperties'], '{}.{}'.format(path, key))
                if error:
                    return error
        if 'minProperties' in schema and len(value) < int(schema['minProperties']):
            return '{}: too few properties'.format(path)
        if 'maxProperties' in schema and len(value) > int(schema['maxProperties']):
            return '{}: too many properties'.format(path)
        for key, child in properties.items():
            if key in value:
                error = _schema_error(value[key], child, '{}.{}'.format(path, key))
                if error:
                    return error
        return None
    if expected == 'array':
        if not isinstance(value, list):
            return '{}: expected array'.format(path)
        if 'minItems' in schema and len(value) < int(schema['minItems']):
            return '{}: too few items'.format(path)
        if 'maxItems' in schema and len(value) > int(schema['maxItems']):
            return '{}: too many items'.format(path)
        if schema.get('uniqueItems'):
            frozen = []
            for item in value:
                try:
                    frozen.append(json.dumps(item, sort_keys=True, allow_nan=False))
                except (TypeError, ValueError):
                    frozen.append(repr(item))
            if len(set(frozen)) != len(value):
                return '{}: duplicate items'.format(path)
        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                error = _schema_error(item, item_schema, '{}[{}]'.format(path, index))
                if error:
                    return error
        return None
    if expected == 'string':
        if not isinstance(value, str):
            return '{}: expected string'.format(path)
        if 'minLength' in schema and len(value) < int(schema['minLength']):
            return '{}: string is too short'.format(path)
        if 'maxLength' in schema and len(value) > int(schema['maxLength']):
            return '{}: string is too long'.format(path)
        pattern = schema.get('pattern')
        if pattern and re.search(str(pattern), value) is None:
            return '{}: string pattern mismatch'.format(path)
        return None
    if expected == 'integer':
        if type(value) is not int:
            return '{}: expected integer'.format(path)
        numeric = value
    elif expected == 'number':
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return '{}: expected finite number'.format(path)
        numeric = value
    elif expected == 'boolean':
        if type(value) is not bool:
            return '{}: expected boolean'.format(path)
        return None
    elif expected in (None, ''):
        return None
    else:
        return '{}: unsupported schema type'.format(path)
    if 'minimum' in schema and numeric < schema['minimum']:
        return '{}: below minimum'.format(path)
    if 'exclusiveMinimum' in schema and numeric <= schema['exclusiveMinimum']:
        return '{}: below exclusive minimum'.format(path)
    if 'maximum' in schema and numeric > schema['maximum']:
        return '{}: above maximum'.format(path)
    if 'exclusiveMaximum' in schema and numeric >= schema['exclusiveMaximum']:
        return '{}: above exclusive maximum'.format(path)
    return None


def _validate_frame_request(frames, budget_seconds=None, *, label='frame'):
    if not isinstance(frames, list) or not frames or len(frames) > 12:
        raise ValueError('{} frames must be a non-empty list of at most 12 items'.format(label))
    if any(type(frame) is not int or frame < 1 for frame in frames):
        raise ValueError('{} frames must contain only positive integers'.format(label))
    if len(set(frames)) != len(frames):
        raise ValueError('{} frames must not contain duplicates'.format(label))
    if budget_seconds is not None:
        if isinstance(budget_seconds, bool) or not isinstance(budget_seconds, (int, float)) or not math.isfinite(float(budget_seconds)):
            raise ValueError('budget_seconds must be a finite number')
        if float(budget_seconds) <= 0 or float(budget_seconds) > 120:
            raise ValueError('budget_seconds must be positive and no greater than 120')
    return list(frames)


class GraphRun(DiagnosticRun):
    def __init__(self, manifest_path, jobs, *, trusted_execution=None, task_id=None, session_id=None,
                 host_client=None, artifact_registry=None, save_root=None, nuke_client=None):
        super().__init__(manifest_path)
        if self.manifest.get('construction_authorized') is not True:
            raise ValueError('controller construction authorization required')
        self.jobs = jobs
        self.host_client = host_client
        self.nuke_client = nuke_client
        self.artifact_registry = artifact_registry
        self.save_root = save_root
        # persistent operation registry (kind+owner) and save receipts
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS operation_registry (
                    operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL,
                    request_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS save_receipts (
                    saved_scene_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, receipt TEXT NOT NULL);
            ''')
        self.trusted_execution = trusted_execution
        self.pipeline_task_id = str(task_id or '').strip() or None
        self.session_id = str(session_id or self.manifest.get('session_id') or '').strip() or None
        if self.trusted_execution is not None and (self.pipeline_task_id is None or self.session_id is None):
            raise ValueError('trusted observation collector requires task_id and controller session_id')

    def media(self, asset_id):
        service = getattr(self, 'media_service', None)
        return service.media(asset_id) if service is not None else super().media(asset_id)

    def media_attachments(self, asset_ids):
        if getattr(self, 'media_service', None) is None:
            raise ValueError('controller media service is not configured')
        return self.media_service.attachments(asset_ids)

    def media_video_frames(self, asset_id, frames):
        if getattr(self, 'media_service', None) is None:
            raise ValueError('controller media service is not configured')
        return self.media_service.extract_video(asset_id, frames)

    def media_sequence_diagnostics(self, asset_ids, frame_numbers):
        from .controller_media import PngMetricDecoder
        policy = getattr(self, 'media_diagnostics_policy', None)
        if not policy or getattr(self, 'media_service', None) is None:
            raise ValueError('controller must freeze expected and active frames before diagnostics')
        return self.media_service.sequence_diagnostics(asset_ids, frame_numbers=frame_numbers,
            expected_frames=policy['expected_frames'], active_frames=policy['active_frames'],
            raster_decoder=PngMetricDecoder(), max_temporal_delta=policy.get('max_temporal_delta', 1.0))


    def submit_observation(self, asset_id, observation, request_id, media_basis_id=None):
        result = super().submit_observation(asset_id, observation, request_id, media_basis_id)
        if self.trusted_execution is None:
            return result
        captured = self.trusted_execution.register_connector_observation(
            self.pipeline_task_id,
            run_id=self.run_id,
            session_id=self.session_id,
            asset_id=asset_id,
            observation=observation,
            connector_receipt={**result, 'replayed': False},
            input_class='synthetic',
        )
        return {
            **result,
            'controller_observation_record_id': captured['record_id'],
            'controller_observation_record_hash': captured['record_hash'],
            # A per-image connector observation is evidence input, not proof of
            # the final external analysis response or provider identity.
            'reference_analysis_route_verified': False,
        }

    def capture_reference_analysis(self, raw_response, config, request_id, *, collection_mode="controller_transport"):
        """Controller-only handoff; intentionally not exposed as an MCP tool."""
        if self.trusted_execution is None:
            raise ValueError('trusted response collector is not configured')
        captured = self.trusted_execution.capture_reference_analysis_response(
            self.pipeline_task_id,
            run_id=self.run_id,
            session_id=self.session_id,
            raw_response=raw_response,
            config=config,
            input_class='synthetic',
            collection_mode=collection_mode,
        )
        registered = self.trusted_execution.register_reference_analysis_run(
            self.pipeline_task_id,
            run_id=self.run_id,
            session_id=self.session_id,
            analysis=captured['analysis'],
            capture_id=captured['capture_id'],
            config=config,
            input_class='synthetic',
        )
        submitted = self.trusted_execution.pipeline.reference_analysis_submit(
            self.pipeline_task_id,
            captured['analysis'],
            run_id=self.run_id,
            request_id=request_id,
        )
        return {
            'capture': captured,
            'registration': registered,
            'analysis_submission': submitted,
            'provider_identity_verified': registered['provider_identity_verified'],
            'real_workbuddy_acceptance': False,
        }
    def _register_operation(self, operation_id, kind, owner, request_id):
        with self._connect() as db:
            prior = db.execute('SELECT kind,owner,request_id FROM operation_registry WHERE operation_id=?',
                               (str(operation_id),)).fetchone()
            if prior is not None and tuple(prior) != (kind, str(owner), str(request_id)):
                raise ValueError('operation ID is already bound to another producer')
            db.execute('INSERT OR IGNORE INTO operation_registry VALUES(?,?,?,?)',
                       (str(operation_id), kind, str(owner), str(request_id)))
        return operation_id

    def _lookup_operation(self, operation_id):
        with self._connect() as db:
            row = db.execute('SELECT kind, owner, request_id FROM operation_registry WHERE operation_id=?',
                             (str(operation_id),)).fetchone()
        return {'kind': row[0], 'owner': row[1], 'request_id': row[2]} if row else None

    def _save_receipt(self, receipt):
        saved_scene_id = 'scene-' + hashlib.sha256(json.dumps(
            [receipt.get('path'), receipt.get('sha256')], ensure_ascii=False).encode()).hexdigest()[:16]
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO save_receipts VALUES(?,?,?)',
                       (saved_scene_id, str(self.pipeline_task_id), json.dumps(receipt, ensure_ascii=False)))
        return saved_scene_id

    def _resolve_receipt(self, saved_scene_id):
        with self._connect() as db:
            row = db.execute('SELECT receipt FROM save_receipts WHERE saved_scene_id=?',
                             (str(saved_scene_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def health(self):
        execution_profile = bool(self.manifest.get('execution_authorized') is True)
        host_bound = self.host_client is not None
        nuke_bound = self.nuke_client is not None
        host_boundary = str(getattr(self.host_client, 'boundary_kind', '') or '')
        nuke_boundary = str(getattr(self.nuke_client, 'boundary_kind', '') or '')
        strict_fake = host_boundary.startswith('strict_fake_') or nuke_boundary.startswith('strict_fake_')
        return {**super().health(), 'mode':'synthetic_construction_only',
                'task_id':self.pipeline_task_id, 'session_id':self.session_id,
                'backend_kind': getattr(self, 'backend_kind', 'production'),
                'execution_boundary': 'strict_fake_host_process' if strict_fake else 'configured',
                'host_boundary_kind': host_boundary or None,
                'nuke_boundary_kind': nuke_boundary or None,
                'real_host_bound': getattr(self.host_client, 'real_host_bound', None),
                'real_nuke_bound': getattr(self.nuke_client, 'real_nuke_bound', None),
                'real_process_bound': getattr(self.host_client, 'real_process_bound', None),
                'real_dcc_started': False if strict_fake else None,
                'dcc_dispatch_enabled':bool(execution_profile and host_bound),
                'simulation_enabled':bool(execution_profile and self.manifest.get('simulation_authorized') is True and host_bound),
                'cache_enabled':False,
                'render_enabled':bool(execution_profile and self.manifest.get('render_authorized') is True and nuke_bound),
                'permission_mode':'full_access_user_selected'}

    def graph_catalog(self):
        return {**graph_catalog.descriptor(), 'trial_max_nodes':8, 'trial_budget_seconds':120,
                'construction_only':True}

    def graph_propose(self, proposal, request_id):
        profile = proposal.get('scene_profile') if isinstance(proposal, dict) else None
        frozen = self.manifest.get('construction_input_manifest')
        has_scene = isinstance(frozen, list) and any(
            isinstance(item, dict) and item.get('semantic_role') == 'render_scene_configuration'
            for item in frozen)
        if profile is not None or has_scene:
            from .graph_construction_inputs import render_scene_configuration
            version = proposal.get('houdini_version') if isinstance(proposal, dict) else None
            scene = render_scene_configuration(frozen, version)
            if scene is not None or profile is not None:
                if (scene is None or profile not in SUPPORTED_PROFILES
                        or scene['profile'] != profile):
                    raise ValueError('frozen render scene configuration profile differs from registered profile')
        observed = {item['asset_id'] for item in self.export()['observations']}
        if not set(self.assets).issubset(observed):
            raise ValueError('submit observations of both registered images before proposing')
        result = self.jobs.propose(proposal, request_id)
        return {'graph_id':result,'executed':False} if isinstance(result,str) else result

    def _mark_graph_trial_complete(self, result):
        """Bind downstream software state only after a completed trial receipt."""
        marker = getattr(self.host_client, 'mark_graph_trial_complete', None)
        if not isinstance(result, dict):
            return result
        if result.get('success') is True or result.get('state') == 'SUCCEEDED':
            graph_id = result.get('graph_id') or (result.get('operation') or {}).get('graph_id')
            service = getattr(self, 'jobs_service', None) or self.jobs
            if graph_id and hasattr(service, 'compiled_graph'):
                from .feedback_versions import FeedbackVersions
                FeedbackVersions(self).register_completed(str(graph_id), service.compiled_graph(graph_id))
            if callable(marker):
                # Preserve the coordinator's terminal operation receipt.  The
                # host binding is a downstream side effect of that receipt,
                # not a replacement for its state, result, or verification.
                return {**result, 'host_binding': marker(self.pipeline_task_id, result)}
        return result

    def graph_trial(self, graph_id, request_id):
        result = self.jobs.trial(graph_id, request_id)
        if isinstance(result, str):
            self._register_operation(result, 'graph', 'houdini', str(request_id))
        elif isinstance(result, dict):
            operation_id = result.get('operation_id') or (result.get('operation') or {}).get('operation_id')
            if operation_id:
                self._register_operation(operation_id, 'graph', 'houdini', str(request_id))
        if not isinstance(result, str):
            if ((getattr(self, 'backend_kind', '') == 'software_fake_hou'
                    or bool(getattr(self, 'wait_for_formal_trial', False)))
                    and isinstance(result, dict) and result.get('operation_id')
                    and getattr(self, 'jobs_service', None) is not None):
                operation_id = str(result['operation_id'])
                deadline = time.monotonic() + 10.0
                lower = self.jobs_service.status(operation_id)
                while lower.get('state') in {'PREPARED', 'STARTING', 'RUNNING'} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    lower = self.jobs_service.status(operation_id)
                # Re-read through the coordinator so the task ledger and the
                # public formal result reflect the same terminal observation.
                return self._mark_graph_trial_complete(self.jobs.status(operation_id))
            return result
        # The formal profiles run a bounded worker at the selected host
        # boundary.  Wait for the terminal construction receipt before
        # handing the controller its save/edit steps; a caller may still use
        # graph_status for a separately submitted asynchronous profile.
        if (getattr(self, 'backend_kind', '') == 'software_fake_hou'
                or bool(getattr(self, 'wait_for_formal_trial', False))):
            deadline = time.monotonic() + 10.0
            status = self.jobs.status(result)
            while status.get('state') in {'PREPARED', 'STARTING', 'RUNNING'} and time.monotonic() < deadline:
                time.sleep(0.01)
                status = self.jobs.status(result)
            return self._mark_graph_trial_complete(status)
        return {'operation_id': result, 'accepted': True, 'completed': False}

    def graph_status(self, operation_id):
        return self.jobs.status(operation_id)

    # ---- extended toolchain (R06): every tool routes through public services ----
    def _require_host_client(self):
        if self.host_client is None:
            raise ValueError('no host session is attached to this task')
        return self.host_client

    def _require_execution_profile(self):
        if self.manifest.get('execution_authorized') is not True:
            raise ValueError('bounded execution is not authorized for this manifest')
        return self._require_host_client()

    def _require_simulation_profile(self):
        if self.manifest.get('execution_authorized') is not True \
                or self.manifest.get('simulation_authorized') is not True:
            raise ValueError('bounded simulation is not authorized for this manifest')
        return self._require_host_client()

    def frame_execute(self, request_id, frames, budget_seconds=120.0):
        frames = _validate_frame_request(frames, budget_seconds)
        if not isinstance(request_id, str) or re.fullmatch(r'^[a-zA-Z0-9_-]{1,100}$', request_id) is None:
            raise ValueError('request_id must be a bounded identifier')
        client = self._require_simulation_profile()
        if self.pipeline_task_id is None:
            raise ValueError('frame operations require a controller task binding')
        budget = budget_seconds
        result = client.call('agent.fx.simulate_segment', {
            'task_id': self.pipeline_task_id,
            'step_params': {'domain_pack': str(self.manifest.get('domain_pack') or ''), 'frames': frames},
            'budget_seconds': budget, 'request_id': str(request_id)})
        operation_id = result.get('request_id')
        drain = getattr(client, 'drain', None)
        if callable(drain) and operation_id:
            observed = drain(self.pipeline_task_id, operation_id)
            if isinstance(observed, dict):
                result = {**result, 'record': observed}
        self._register_operation(operation_id, 'host-frame', 'houdini', str(request_id))
        return {'operation_id': operation_id, 'state': (result.get('record') or {}).get('state'),
                'operation': result.get('record')}

    def houdini_render_bounded(self, request_id, saved_scene_id, render_target, pattern, frames, budget_seconds=120.0):
        """Render the current registered saved HIP through the task-owned host."""
        if self.manifest.get('render_authorized') is not True or self.manifest.get('execution_authorized') is not True:
            raise ValueError('bounded Houdini rendering is not authorized')
        frames = _validate_frame_request(frames, budget_seconds, label='houdini render')
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id):
            raise ValueError('request_id must be a bounded identifier')
        receipt = self._resolve_receipt(saved_scene_id)
        if receipt is None:
            raise ValueError('unknown saved_scene_id')
        from .feedback_versions import FeedbackVersions
        dependencies = FeedbackVersions(self).dependencies()
        if receipt.get('feedback_dependencies', []) != dependencies:
            raise ValueError('saved scene is not the current graph content version')
        output = Path(pattern).expanduser()
        if (not output.is_absolute() or not output.resolve().is_relative_to(Path(self.save_root).resolve())
                or output.suffix.lower() != '.exr'):
            raise ValueError('render output must be under controller save root')
        client = self._require_host_client()
        # Reopen is a separate durable scene transition; a retry of an existing
        # render queries its frozen operation without mutating the host scene.
        existing = self._lookup_operation(request_id)
        if existing is None:
            self.task_reopen(saved_scene_id)
        result = client.call('render.start', {'task_id': self.pipeline_task_id, 'request_id': request_id,
            'render_target': render_target, 'output_pattern': str(output), 'frames': frames,
            'budget_seconds': budget_seconds, 'dependencies': dependencies})
        operation_id = str(result['operation_id'])
        self._register_operation(operation_id, 'houdini-render', 'houdini', request_id)
        return {'operation_id': operation_id, 'state': result['record']['state'], 'operation': result['record']}

    def verify_render_output(self, request_id, operation_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', request_id):
            raise ValueError('controlled verification request_id is required')
        parent = self._lookup_operation(operation_id)
        if not parent or parent['kind'] != 'houdini-render':
            raise ValueError('CONTROLLED_OUTPUT_PARENT_BINDING_REQUIRED')
        result = self._require_host_client().call('output.verify',
            {'task_id': self.pipeline_task_id, 'operation_id': operation_id, 'verification_id': request_id})
        self._register_operation(request_id, 'houdini-output-verification', 'houdini', request_id)
        return result

    def operation_query(self, operation_id):
        entry = self._lookup_operation(operation_id)
        if entry is None:
            raise ValueError('unknown operation: {}'.format(operation_id))
        kind = entry['kind']
        if kind == 'graph':
            return {'kind': kind, 'operation': self.jobs.status(operation_id)}
        if kind == 'host-frame':
            client = self._require_host_client()
            return {'kind': kind, 'operation': client.call('operation.status', {
                'task_id': self.pipeline_task_id, 'operation_id': operation_id})['operation']}
        if kind == 'houdini-output-verification':
            return {'kind': kind, **self._require_host_client().call('output.verify.status', {'verification_id': operation_id})}
        if kind == 'houdini-render':
            result = self._require_host_client().call('render.status', {'task_id': self.pipeline_task_id, 'operation_id': operation_id})
            return {'kind': kind, **result}
        if kind == 'nuke-render':
            client = self._require_nuke_client()
            return {'kind': kind, 'operation': client.call('render_status', {'task_id': operation_id})}
        raise ValueError('unknown operation kind')

    def operation_cancel(self, operation_id):
        entry = self._lookup_operation(operation_id)
        if entry is None:
            raise ValueError('unknown operation: {}'.format(operation_id))
        kind = entry['kind']
        if kind == 'graph':
            return {'kind': kind, 'cancel': self.jobs.cancel(operation_id)}
        if kind == 'host-frame':
            client = self._require_host_client()
            record = client.call('operation.cancel', {'task_id': self.pipeline_task_id,
                                                      'operation_id': operation_id})
            return {'kind': kind, 'cancel': record}
        if kind == 'houdini-output-verification':
            return {'kind': kind, 'cancel': {'state': 'COMPLETED', 'cancel_requested': False}}
        if kind == 'houdini-render':
            result = self._require_host_client().call('render.cancel', {'task_id': self.pipeline_task_id, 'operation_id': operation_id})
            return {'kind': kind, 'cancel': result}
        if kind == 'nuke-render':
            client = self._require_nuke_client()
            return {'kind': kind, 'cancel': client.call('render_cancel', {'task_id': operation_id})}
        raise ValueError('unknown operation kind')

    def _require_nuke_client(self):
        if self.nuke_client is None:
            raise ValueError('no nuke session is attached to this task')
        return self.nuke_client

    def _validated_nuke_composite_spec(self, spec):
        """Resolve the controller's registered input before native graph actions."""
        if not isinstance(spec, dict) or spec.get('task_id') != self.pipeline_task_id:
            raise ValueError('NUKE_COMPOSITE_TASK_MISMATCH')
        render = spec.get('render') or {}
        frame_range = render.get('frame_range') or {}
        start, end, step = (frame_range.get(key) for key in ('start', 'end', 'step'))
        if (any(type(value) is not int for value in (start, end, step))
                or start < 1 or step < 1 or end < start or (end - start) // step + 1 > 12):
            raise ValueError('NUKE_COMPOSITE_FRAME_RANGE_INVALID')
        frames = list(range(start, end + 1, step))
        output = Path(str(render.get('output_dir') or '')).expanduser()
        if not output.is_absolute() or not output.resolve().is_relative_to(Path(self.save_root).resolve()):
            raise ValueError('NUKE_COMPOSITE_OUTPUT_OUTSIDE_TASK')
        inputs = spec.get('inputs')
        if (not isinstance(inputs, list) or len(inputs) != 1
                or not isinstance(inputs[0], dict) or inputs[0].get('role') != 'effect_render'):
            raise ValueError('NUKE_COMPOSITE_REGISTERED_EFFECT_INPUT_REQUIRED')
        item = inputs[0]
        artifact_id = item.get('artifact_id') or item.get('asset_id')
        entry = self.artifact_registry.lookup(artifact_id) if self.artifact_registry is not None else None
        if (not isinstance(entry, dict) or entry.get('task_id') != self.pipeline_task_id
                or entry.get('pattern') != item.get('path')):
            raise ValueError('NUKE_COMPOSITE_INPUT_OWNER_MISMATCH')
        consumed = self.consume_artifact(artifact_id)
        if (consumed.get('usable_as_render_input') is not True
                or not set(frames).issubset(set((consumed.get('verification') or {}).get('frame_set') or []))):
            raise ValueError('NUKE_COMPOSITE_INPUT_NOT_USABLE')
        from nuke_bridge.operation_receipts import freeze_agent_inputs
        frozen = freeze_agent_inputs(self.pipeline_task_id, inputs)
        snapshots = (entry.get('payload') or {}).get('completion_snapshot') or {}
        for frame in frozen['frozen_inputs_manifest'][0].get('frames') or []:
            saved = snapshots.get(str(frame['frame'])) or {}
            if any(frame.get(key) != saved.get(key) for key in ('sha256', 'bytes')):
                raise ValueError('NUKE_COMPOSITE_INPUT_SNAPSHOT_MISMATCH')
        return frames, consumed, frozen

    def nuke_composite_action(self, command, spec):
        """Controller-only forwarding to the existing editable Nuke graph API."""
        if command not in {'agent.nuke.composite.build_graph', 'agent.nuke.composite.audit_lineage',
                           'agent.nuke.composite.apply_patch'}:
            raise ValueError('NUKE_COMPOSITE_ACTION_UNSUPPORTED')
        self._validated_nuke_composite_spec(spec)
        return self._require_nuke_client().call(command, spec)

    def nuke_composite_render_bounded(self, request_id, spec, frames):
        """Execute the existing composite Write through the fixed owned worker.

        The graph builder audits all intermediate nodes. Unlike render_binding,
        this path retains those connections and never replaces them by Read→Write.
        """
        if (self.manifest.get('execution_authorized') is not True
                or self.manifest.get('render_authorized') is not True):
            raise ValueError('nuke rendering is not authorized for this manifest')
        if not isinstance(request_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id) is None:
            raise ValueError('request_id must be a bounded identifier')
        frames = _validate_frame_request(frames, label='nuke composite render')
        available, consumed, frozen = self._validated_nuke_composite_spec(spec)
        if not set(frames).issubset(set(available)):
            raise ValueError('NUKE_COMPOSITE_FRAME_RANGE_INVALID')
        client = self._require_nuke_client()
        built = client.call('agent.nuke.composite.build_graph', spec)
        audit = client.call('agent.nuke.composite.audit_lineage', spec)
        for response, name in ((built, 'editable_native_composite_graph'),
                               (audit, 'reference_isolated_from_final_write')):
            gates = [gate for gate in response.get('gates', []) if gate.get('name') == name]
            if not gates or any(gate.get('passed') is not True for gate in gates):
                raise ValueError('NUKE_COMPOSITE_GRAPH_UNVERIFIED')
        graph = built.get('graph') or {}
        write_name, pattern = graph.get('write'), graph.get('final_pattern')
        node = client.call('get_node', {'name': write_name})
        if (not isinstance(write_name, str) or node.get('class') != 'Write'
                or node.get('knobs', {}).get('file') != pattern
                or not Path(str(pattern)).resolve().is_relative_to(Path(self.save_root).resolve())):
            raise ValueError('NUKE_COMPOSITE_WRITE_UNVERIFIED')
        colorspace, premultiplied = consumed.get('colorspace'), consumed.get('premultiplied')
        if not isinstance(colorspace, str) or not colorspace or type(premultiplied) is not bool:
            raise ValueError('NUKE_COMPOSITE_COLOR_METADATA_REQUIRED')
        read_name = (graph.get('input_nodes') or {}).get('effect_render')
        read = client.call('get_node', {'name': read_name})
        if read.get('class') != 'Read' or read.get('knobs', {}).get('file') != consumed.get('pattern'):
            raise ValueError('NUKE_COMPOSITE_READ_UNVERIFIED')
        premult_node = client.call('get_node', {'name': (graph.get('graph_nodes') or {}).get('effect_premult')})
        disabled = premult_node.get('knobs', {}).get('disable')
        if premult_node.get('class') != 'Premult' or type(disabled) is not bool:
            raise ValueError('NUKE_COMPOSITE_PREMULT_READBACK_REQUIRED')
        premultiplied = premultiplied or not disabled
        targets = ((read_name, {'colorspace': colorspace, 'raw': False}),
                               (write_name, {'colorspace': colorspace,
                                             'premultiplied': premultiplied, 'raw': False}))
        original = {}
        for name, settings in targets:
            before = client.call('get_node', {'name': name})
            if any(key not in before.get('knobs', {}) for key in settings):
                raise ValueError('NUKE_COMPOSITE_NATIVE_COLOR_KNOBS_REQUIRED')
            original[name] = {key: before['knobs'][key] for key in settings}
        try:
            for name, settings in targets:
                for knob, value in settings.items():
                    client.call('set_knob', {'node': name, 'knob': knob, 'value': value})
                after = client.call('get_node', {'name': name})
                if any(after.get('knobs', {}).get(key) != value for key, value in settings.items()):
                    raise ValueError('NUKE_COMPOSITE_NATIVE_COLOR_READBACK_FAILED')
            # Color writes may invoke native callbacks. Audit the final graph,
            # then re-read the complete binding before any worker submission.
            final_audit = client.call('agent.nuke.composite.audit_lineage', spec)
            gates = [gate for gate in final_audit.get('gates', [])
                     if gate.get('name') == 'reference_isolated_from_final_write']
            if not gates or any(gate.get('passed') is not True for gate in gates):
                raise ValueError('NUKE_COMPOSITE_GRAPH_UNVERIFIED')
            for name, settings in targets:
                after = client.call('get_node', {'name': name})
                expected_class, expected_file = ('Read', consumed['pattern']) if name == read_name else ('Write', pattern)
                if (after.get('class') != expected_class
                        or after.get('knobs', {}).get('file') != expected_file
                        or any(after.get('knobs', {}).get(key) != value for key, value in settings.items())):
                    raise ValueError('NUKE_COMPOSITE_NATIVE_COLOR_READBACK_FAILED')
            final_premult = client.call('get_node', {'name': (graph.get('graph_nodes') or {}).get('effect_premult')})
            if (final_premult.get('class') != 'Premult'
                    or type(final_premult.get('knobs', {}).get('disable')) is not bool
                    or final_premult['knobs']['disable'] != disabled):
                raise ValueError('NUKE_COMPOSITE_PREMULT_READBACK_REQUIRED')
        except Exception:
            for name, settings in original.items():
                for knob, value in settings.items():
                    client.call('set_knob', {'node': name, 'knob': knob, 'value': value})
            raise
        binding = {'source': 'controller', 'task_id': self.pipeline_task_id,
            'node': write_name, 'pattern': pattern, 'frames': frames, 'input_binding': frozen}
        if consumed.get('project_color') is not None:
            binding['project_color'] = consumed['project_color']
        result = client.call('render_write', {'node': write_name, 'output_binding': binding,
            'pattern': pattern, 'frame_set': frames, 'frame_range': [min(frames), max(frames)],
            'background': True, 'request_id': request_id,
            'colorspace': colorspace, 'premultiplied': premultiplied})
        operation_id = result.get('operation_id') or result.get('task_id')
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError('NUKE_COMPOSITE_OPERATION_MISSING')
        self._register_operation(operation_id, 'nuke-render', 'nuke', request_id)
        return {'operation_id': operation_id, 'state': result.get('state'),
            'pattern': pattern, 'frames': frames, 'input_artifact_id': consumed['artifact_id']}

    def nuke_render_bounded(self, request_id, pattern, frames, colorspace=None,
                            premultiplied=None, artifact_id=None):
        """Bounded Nuke render through the C2 public service (C3.7).

        Omitted color/alpha inherit the verified artifact. Explicit conversion
        requires a separate configured path and is rejected by this Read→Write.
        Registers a public operation of kind nuke-render; evidence carries the
        backend kind (real host vs software fake) from the client binding.
        """
        if (self.manifest.get('render_authorized') is not True
                or self.manifest.get('execution_authorized') is not True):
            raise ValueError('nuke rendering is not authorized for this manifest')
        if not isinstance(request_id, str) or re.fullmatch(r'^[a-zA-Z0-9_-]{1,100}$', request_id) is None:
            raise ValueError('request_id must be a bounded identifier')
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError('nuke render pattern must be a non-empty string')
        frames = _validate_frame_request(frames, label='nuke render')
        if not isinstance(artifact_id, str) or not re.fullmatch(r'^[A-Za-z0-9_.-]{1,120}$', artifact_id):
            raise ValueError('a registered artifact_id is required before Nuke execution')
        if self.artifact_registry is not None:
            entry = self.artifact_registry.lookup(artifact_id)
            if entry is not None and entry.get('task_id') != self.pipeline_task_id:
                raise ValueError('NUKE_INPUT_ARTIFACT_OWNER_MISMATCH')
        artifact = self.consume_artifact(artifact_id)
        if not artifact.get('usable_as_render_input'):
            raise ValueError('registered artifact is not a fresh readable render input')
        input_color = artifact.get('colorspace')
        input_premult = artifact.get('premultiplied')
        if (not isinstance(input_color, str) or not input_color.strip()
                or type(input_premult) is not bool):
            raise ValueError('registered artifact color metadata is required')
        # Read→Write preserves the registered interpretation; this route does
        # not perform an independently specified color or alpha conversion.
        if colorspace is None:
            colorspace = input_color
        if premultiplied is None:
            premultiplied = input_premult
        if (not isinstance(colorspace, str) or colorspace != input_color
                or type(premultiplied) is not bool or premultiplied != input_premult):
            raise ValueError('registered artifact color or alpha conversion is not configured')
        input_frames = list((artifact.get('verification') or {}).get('frame_set') or [])
        if not set(frames).issubset(set(input_frames)):
            raise ValueError('requested Nuke frames are not covered by the registered artifact')
        try:
            Path(str(pattern)).expanduser().resolve().relative_to(Path(self.save_root).resolve())
        except ValueError:
            raise ValueError('nuke render output must stay under the controller save root')
        client = self._require_nuke_client()
        render_binding_factory = getattr(client, 'render_binding', None)
        if not callable(render_binding_factory):
            raise ValueError('controller Nuke output binding is required')
        binding = render_binding_factory(self.pipeline_task_id, str(pattern), list(frames),
                                         str(colorspace), bool(premultiplied),
                                         artifact_binding=artifact)
        if (not isinstance(binding, dict) or binding.get('source') != 'controller'
                or not isinstance(binding.get('node'), str) or not binding.get('node')
                or str(binding.get('pattern') or '') != str(pattern)
                or list(binding.get('frames') or []) != list(frames)
                or not isinstance(binding.get('input_binding'), dict)
                or binding['input_binding'].get('kind') != 'artifact_read'
                or str(binding['input_binding'].get('artifact_id') or '') != artifact_id
                or not binding['input_binding'].get('connection_verified')):
            raise ValueError('controller Nuke output binding is invalid')
        if artifact.get('project_color') is not None:
            binding['project_color'] = artifact['project_color']
        result = client.call('render_write', {
            'node': binding['node'], 'output_binding': binding,
            'pattern': str(pattern), 'frame_set': list(frames), 'background': bool(binding.get('background', False)),
            'frame_range': [min(frames), max(frames)], 'request_id': str(request_id),
            'colorspace': str(colorspace), 'premultiplied': bool(premultiplied)})
        operation_id = result.get('operation_id') or result.get('task_id')
        self._register_operation(operation_id, 'nuke-render', 'nuke', str(request_id))
        boundary_kind = str(getattr(self.nuke_client, 'boundary_kind', '') or '')
        if boundary_kind.startswith('strict_fake_'):
            evidence_kind = 'strict_fake_host'
        elif getattr(self, 'backend_kind', '') == 'software_fake_hou':
            evidence_kind = 'software_fake_host'
        else:
            evidence_kind = 'real_host'
        return {'operation_id': operation_id, 'state': result.get('state'),
                'artifact_id': 'nuke-render-' + str(operation_id),
                'input_artifact_id': artifact_id,
                'backend_kind': getattr(self.nuke_client, 'backend_kind', 'unknown'),
                'evidence_kind': evidence_kind,
                'real_host_bound': getattr(self.nuke_client, 'real_host_bound', None),
                'real_nuke_bound': getattr(self.nuke_client, 'real_nuke_bound', None),
                'boundary_kind': boundary_kind or None}

    def feedback_edit(self, graph_id, node_id, parms, task_id):
        """Bounded feedback: only registered graph nodes and catalog ranges."""
        client = self._require_host_client()
        requested_task_id = str(task_id or '').strip()
        if requested_task_id and requested_task_id != self.pipeline_task_id:
            raise ValueError('feedback edits must target the task-owned root')
        effective_task_id = self.pipeline_task_id
        if not effective_task_id:
            raise ValueError('feedback edits require a controller task binding')
        jobs_service = getattr(self, 'jobs_service', None) or self.jobs
        if not hasattr(jobs_service, 'compiled_graph'):
            raise ValueError('no registered graph store is attached to this task')
        compiled = jobs_service.compiled_graph(graph_id)
        matches = [n for n in compiled.get('nodes') or [] if n.get('node_id') == str(node_id)]
        node = matches[0] if len(matches) == 1 else None
        if node is None:
            raise ValueError('node {} is not part of the registered graph'.format(node_id))
        from . import graph_catalog
        spec = graph_catalog.catalog_specs().get(str(node.get('node_type')))
        if spec is None:
            raise ValueError('node type has no catalog parameter specification')
        graph_hash = str(compiled.get('graph_hash') or '')
        if not graph_hash:
            raise ValueError('the registered graph has no hash')
        import hashlib as _hl
        root_digest = _hl.sha256((str(effective_task_id) + ':' + graph_hash).encode()).hexdigest()
        root = '/obj/BRIDGE_GRAPH_' + root_digest
        from dcc_task_runtime.graph_compiler import CompiledGraph, CompiledNode, CompiledConnection, CompiledOutput
        registered = CompiledGraph(
            nodes=tuple(CompiledNode(**item) for item in compiled['nodes']),
            connections=tuple(CompiledConnection(**item) for item in compiled['connections']),
            outputs=tuple(CompiledOutput(**item) for item in compiled['outputs']),
            execution_order=tuple(compiled['execution_order']),
            cycle_boundaries=tuple(compiled.get('cycle_boundaries') or ()), graph_hash=graph_hash)
        layout = graph_catalog.native_layout(registered, root)
        path = layout[node['address']]['path']
        identity = graph_catalog.registered_domain_identity(registered)
        from . import geometry_graph
        geometry_nodes = any(n.node_type in {geometry_graph.BOX, geometry_graph.TRANSFORM}
                             or '_bounded_geometry_rig_v1_' in n.node_type for n in registered.nodes)
        if geometry_nodes:
            # 几何反馈只允许精确重编译后的原模型字段；固定rig不能借用材质域控制路由。
            if (not identity or identity.get('schema') != geometry_graph.SCHEMA
                    or identity.get('scene_profile') != geometry_graph.PROFILE
                    or identity.get('domain_pack') != geometry_graph.DOMAIN
                    or identity.get('houdini_version') != geometry_graph.VERSION
                    or graph_catalog.compile_proposal(identity).to_dict() != registered.to_dict()):
                raise ValueError('GEOMETRY_FEEDBACK_REGISTERED_SELECTOR_REQUIRED')
            model = geometry_graph.model_proposal(identity['model_graph'])
            originals = [n for n in model.nodes
                         if geometry_graph.MODEL_PREFIX + n.node_id == str(node_id)
                         and node['address'] == 'houdini_sop:/geometry_network/' + geometry_graph.MODEL_PREFIX + n.node_id
                         and node['node_type'] == n.node_type]
            if len(originals) != 1:
                raise ValueError('GEOMETRY_FEEDBACK_MODEL_NODE_REQUIRED')
            if not isinstance(parms, dict) or not 1 <= len(parms) <= 6:
                raise ValueError('GEOMETRY_FEEDBACK_FINITE_PARAMETERS_REQUIRED')
            declared = {p.name: p for p in graph_catalog.compiler().node_catalog[originals[0].node_type].parameters}
            for name, value in parms.items():
                field = declared.get(name)
                if (field is None or field.value_type != 'float'
                        or field.minimum is None or field.maximum is None):
                    raise ValueError('GEOMETRY_FEEDBACK_DECLARED_FLOAT_REQUIRED')
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not math.isfinite(value) or not field.minimum <= value <= field.maximum):
                    raise ValueError('GEOMETRY_FEEDBACK_FINITE_RANGE_REQUIRED')
            from .feedback_versions import FeedbackVersions
            # 本分支字段均已严格验证为有界float；写出编码须与HOM浮点读回同类型。
            return FeedbackVersions(self).apply(str(graph_id), compiled, path, str(node_id),
                {name:float(value) for name,value in parms.items()}, client)
        if (identity and identity['domain_pack'] == 'rbd_destruction_v1'
                and (str(node_id) == 'rbd_velocity' or 'velocity_variance' in parms)):
            from houdini_bridge import native_flip_rbd_domains as rbd
            if str(node_id) != 'rbd_velocity' or set(parms) != {'velocity_variance'}:
                raise ValueError('RBD feedback requires the registered velocity carrier and velocity_variance only')
            if rbd.conditional_runtime_route(rbd.RBD, 'velocity_variance', parms['velocity_variance'],
                                             identity['houdini_version']) != rbd.RBD_VELOCITY_ROUTE:
                raise ValueError('RBD feedback has no fixed native program route')
            candidate = {'identity': identity, 'base_graph_hash': graph_hash,
                'task_id': effective_task_id, 'execution_root': root, 'node_path': path,
                'controls': dict(parms), 'readback_kind': 'rbd_initial_velocity',
                'request': {'task_id': effective_task_id,
                    'bridge_execution_binding': {'execution_root': root},
                    'constraints': {'fx': {'domain_pack': rbd.RBD, 'run_mode': 'diagnose',
                                            'changes': dict(parms)}}}}
            from .feedback_versions import FeedbackVersions
            return FeedbackVersions(self).apply(str(graph_id), compiled, path, str(node_id),
                dict(parms), client, domain_candidate=candidate)
        if identity and identity.get('scene_profile') == 'official_karma_disklight_v1':
            from houdini_bridge.official_karma_feedback import candidate_write_plan, EXPOSURE, GATE
            configuration = getattr(self, 'official_feedback_configuration', None)
            if node_id != 'light' or not isinstance(configuration, dict):
                raise ValueError('OFFICIAL_FEEDBACK_REGISTERED_LIGHT_REQUIRED')
            writes = candidate_write_plan(dict(parms),configuration)
            names = [EXPOSURE,GATE]
            if "rectlight_shape_target" in configuration:
                from houdini_bridge.rectlight_shape_target import WIDTH,HEIGHT,WIDTH_GATE,HEIGHT_GATE
                names = [WIDTH,HEIGHT,WIDTH_GATE,HEIGHT_GATE,EXPOSURE,GATE]
            candidate = {'identity': identity, 'base_graph_hash': graph_hash,
                'task_id': effective_task_id, 'execution_root': root, 'node_path': path,
                'writes': writes, 'controls': dict(parms), 'readback_names': names,
                'request': {'task_id': effective_task_id, 'frozen_render_scene': configuration,
                    'bridge_execution_binding': {'execution_root': root},
                    'constraints': {'fx': {'domain_pack': identity['domain_pack'],
                        'run_mode': 'diagnose', 'changes': dict(parms)}}}}
            from .feedback_versions import FeedbackVersions
            return FeedbackVersions(self).apply(str(graph_id), compiled, path, str(node_id),
                {item['parm']: item['value'] for item in writes}, client, domain_candidate=candidate)
        if identity and identity['domain_pack'] in {'material_lookdev_v1', 'lighting_camera_render_v1'}:
            from houdini_bridge.native_render_domains import control_contract, candidate_write_plan, SHUTTER_CONTRACT
            contract = control_contract(identity['domain_pack'], identity['houdini_version'])
            if not parms or len(parms) > 5 or any(name not in contract or contract[name]['role'] != node_id for name in parms):
                raise ValueError('feedback controls must belong to the registered native node')
            writes = candidate_write_plan(identity['domain_pack'], dict(parms), identity['houdini_version'],
                                          shutter_contract=SHUTTER_CONTRACT)
            if any(item['role'] != node_id for item in writes):
                raise ValueError('feedback plan crosses the registered native node')
            candidate = {'identity': identity, 'base_graph_hash': graph_hash,
                'task_id': effective_task_id, 'execution_root': root, 'node_path': path,
                'writes': writes, 'controls': dict(parms),
                'readback_names': sorted({item['parm'] for item in writes} |
                    {field for item in writes for role, field, expected in item.get('required_gates', ()) if role == node_id}),
                'request': {'task_id': effective_task_id,
                    'bridge_execution_binding': {'execution_root': root},
                    'constraints': {'fx': {'domain_pack': identity['domain_pack'], 'run_mode': 'diagnose',
                                            'changes': dict(parms)}}}}
            from .feedback_versions import FeedbackVersions
            return FeedbackVersions(self).apply(str(graph_id), compiled, path, str(node_id),
                {item['parm']: item['value'] for item in writes}, client, domain_candidate=candidate)
        for name, value in dict(parms).items():
            pspec = spec.get(name)
            if pspec is None:
                raise ValueError('parameter {} is not declared in the catalog'.format(name))
            enum_values = pspec.get('enum_values')
            if enum_values is not None:
                if not isinstance(value, str) or value not in enum_values:
                    raise ValueError('parameter {} is outside catalog enum values'.format(name))
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError('parameter {} must be a finite number'.format(name))
            if float(value) != float(value) or float(value) in (float('inf'), float('-inf')):
                raise ValueError('parameter {} must be finite'.format(name))
            if value < pspec['minimum'] or value > pspec['maximum']:
                raise ValueError('parameter {} outside catalog range'.format(name))
        from .feedback_versions import FeedbackVersions
        return FeedbackVersions(self).apply(str(graph_id), compiled, path, str(node_id), dict(parms), client)

    def graph_version(self, graph_id):
        from .feedback_versions import FeedbackVersions
        current = FeedbackVersions(self).current(str(graph_id))
        if current is not None:
            return current
        service = getattr(self, 'jobs_service', None) or self.jobs
        compiled = service.compiled_graph(graph_id)
        return {'version': 0, 'state': 'REGISTERED', 'compiled': compiled,
                'graph_hash': compiled['graph_hash'], 'invalidated_nodes': [], 'invalidated_outputs': []}

    def task_save(self):
        client = self._require_host_client()
        if self.save_root is None:
            raise ValueError('no controller save root configured')
        from .feedback_versions import FeedbackVersions
        dependencies = FeedbackVersions(self).dependencies()
        request = {'task_id': self.pipeline_task_id}
        if getattr(self, 'backend_kind', None) == 'production':
            from uuid import uuid4
            verifier = getattr(client, '_verify_identity', None)
            if not callable(verifier):
                raise ValueError('FORMAL_TYPED_SAVE_HOST_MISMATCH')
            host_identity = verifier().get('task_host_identity')
            if not isinstance(host_identity, dict):
                raise ValueError('FORMAL_TYPED_SAVE_HOST_MISMATCH')
            source_files = self._registry_receipt_sources({'host_identity': host_identity})
            if not source_files:
                raise ValueError('FORMAL_TYPED_SAVE_SOURCE_MISMATCH')
            operation_id = 'task-save-' + uuid4().hex
            path = str(Path(self.save_root) / (operation_id + '.hip'))
            request.update(operation_id=operation_id, request_id=operation_id,
                           frozen_input_manifest=[])
        else:
            path = str(Path(self.save_root) / (str(self.pipeline_task_id or 'task') + '.hip'))
        request['path'] = path
        receipt = client.call('scene.save_hip', request)
        if getattr(self, 'backend_kind', None) == 'production':
            from houdini_bridge.operation_receipts import validate_operation_receipt
            record = receipt.get('operation_receipt')
            validate_operation_receipt(record)
            if (record['command'] != 'scene.save_hip' or record['task_id'] != self.pipeline_task_id
                    or record['request'] != request or receipt.get('operation_store_format') != 'producer_record'
                    or record['operation_id'] != request['operation_id']
                    or record['result'] != {key: value for key, value in receipt.items() if key not in {
                        'operation_receipt', 'operation_store_path', 'operation_store_format', 'idempotent'}}):
                raise ValueError('FORMAL_TYPED_SAVE_BINDING_MISMATCH')
            after_identity = verifier().get('task_host_identity')
            identity_fields = ('task_id', 'pid', 'session_id', 'launch_nonce',
                               'process_generation', 'plugin_build', 'scene_epoch')
            if (not isinstance(after_identity, dict)
                    or any(record['host_identity'].get(key) != host_identity.get(key)
                           or after_identity.get(key) != host_identity.get(key) for key in identity_fields)):
                raise ValueError('FORMAL_TYPED_SAVE_HOST_MISMATCH')
            from .production_hosts import _scene_transition_operation_store_path
            from houdini_bridge.operation_receipt_store import load_record, record_path
            config = client.production_config
            control_root = Path(client.scene_transition_path).parent
            runner_path = _scene_transition_operation_store_path(control_root, self.pipeline_task_id)
            stored_path = record_path(runner_path, self.pipeline_task_id, record['operation_id'])
            if (receipt.get('operation_store_path') != str(stored_path)
                    or load_record(runner_path, self.pipeline_task_id, record['operation_id']) != record):
                raise ValueError('FORMAL_TYPED_SAVE_STORAGE_MISMATCH')
            from dcc_task_runtime.platform_support import _owned_path
            from houdini_bridge.operation_receipts import canonical_sha256
            saved = record['facts']['saved_scene']
            owned_root = Path(config['task_root'])
            hip = _owned_path(Path(path), owned_root)
            snapshot = _owned_path(Path(saved['snapshot_path']), owned_root)
            if (receipt.get('path') != path or saved['path'] != path
                    or receipt.get('sha256') != saved['sha256']
                    or not hip.is_file() or hashlib.sha256(hip.read_bytes()).hexdigest() != saved['sha256']
                    or not snapshot.is_file() or hashlib.sha256(snapshot.read_bytes()).hexdigest() != saved['sha256']
                    or receipt.get('scene_contract') != record['after_scene']['scene_contract']
                    or receipt.get('scene_contract_sha256') != canonical_sha256(receipt.get('scene_contract'))):
                raise ValueError('FORMAL_TYPED_SAVE_BINDING_MISMATCH')
            if self._registry_receipt_sources(record) != source_files:
                raise ValueError('FORMAL_TYPED_SAVE_SOURCE_MISMATCH')
        if FeedbackVersions(self).dependencies() != dependencies:
            raise ValueError('saved scene graph content changed during native save')
        receipt['feedback_dependencies'] = dependencies
        saved_scene_id = self._save_receipt(receipt)
        return {**receipt, 'saved_scene_id': saved_scene_id}

    def task_reopen(self, saved_scene_id):
        client = self._require_host_client()
        receipt = self._resolve_receipt(saved_scene_id)
        if receipt is None:
            raise ValueError('unknown saved_scene_id: {}'.format(saved_scene_id))
        from .feedback_versions import FeedbackVersions
        if receipt.get('feedback_dependencies', []) != FeedbackVersions(self).dependencies():
            raise ValueError('saved scene is not the current graph content version')
        return client.call('scene.reopen_task_hip', {'path': receipt['path'], 'sha256': receipt['sha256'],
                                                     'task_id': self.pipeline_task_id})

    def record_render_fact(self, operation_id, frame_set, output_pattern, scene_fingerprint=""):
        """Controller-side registration of a completed render's facts (C4).

        This is NOT a model tool: the formal server exposes it only through the
        control assembly; tests drive it to mirror what a real render backend
        writes at completion.
        """
        if self.artifact_registry is None:
            raise ValueError('no artifact ledger is attached to this task')
        facts = getattr(self, '_operation_facts', None)
        if facts is None:
            raise ValueError('no operation fact source is configured')
        facts[str(operation_id)] = {
            'task_id': 'nuke:' + str(operation_id), 'scene_fingerprint': str(scene_fingerprint or ''),
            'frame_set': sorted({int(f) for f in frame_set}),
            'output_pattern': str(output_pattern), 'state': 'COMPLETED',
            'started_at_epoch': 0.0,
            'operation_receipt_sha256': __import__('hashlib').sha256(
                str(operation_id).encode()).hexdigest()}
        return {'recorded': True, 'operation_id': str(operation_id)}

    def _registry_receipt_sources(self, fact):
        source = getattr(self, 'controller_source', None)
        if source is None:
            return None
        if not isinstance(source, dict) or source.get('backend') != 'production':
            raise ValueError('configured producer source is invalid')
        manifest = Path(source.get('manifest_path', ''))
        snapshot = Path(source.get('repo_root', ''))
        index = manifest.parent / 'snapshot-manifest.json'
        if not manifest.is_absolute() or snapshot != manifest.parent / 'snapshot':
            raise ValueError('configured producer snapshot is not controller-owned')
        sources = {}

        def bound_file(path, expected):
            for component in (path, *path.parents):
                info = os.lstat(component)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('configured producer source traverses a link')
            if not path.is_file() or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
                raise ValueError('configured producer source file is invalid')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('configured producer source bytes changed')
            sources[str(path)] = expected

        bound_file(manifest, source.get('manifest_sha256'))
        bound_file(index, source.get('snapshot_manifest_sha256'))
        records = json.loads(index.read_text(encoding='utf-8')).get('files')
        if not isinstance(records, list) or not records:
            raise ValueError('configured producer snapshot is empty')
        native = 'plugins/houdini/_impl/houdini_bridge_addon.py'
        seen = set()
        for record in records:
            name = record.get('path') if isinstance(record, dict) else None
            if (not isinstance(name, str) or not name or '\\' in name or name.startswith('/')
                    or PureWindowsPath(name).drive or Path(name).is_absolute()
                    or any(part in ('', '.', '..') for part in name.split('/')) or name in seen):
                raise ValueError('configured producer source path is invalid')
            seen.add(name)
            path = snapshot / name
            expected = record.get('sha256')
            bound_file(path, expected)
            if name == native and expected != (fact.get('host_identity') or {}).get('plugin_build'):
                raise ValueError('configured producer addon differs from completed host')
        if native not in seen:
            raise ValueError('configured producer addon source is missing')
        return sources

    def register_render_artifact(self, artifact_id, artifact_class, pattern, frame_set,
                                 colorspace, premultiplied, operation_id):
        if self.artifact_registry is None:
            raise ValueError('no artifact ledger is attached to this task')
        from .feedback_versions import FeedbackVersions
        route = self._lookup_operation(operation_id)
        if route and route['kind'] in {'houdini-render', 'houdini-output-verification'}:
            if not isinstance(colorspace, str) or not colorspace.strip() or type(premultiplied) is not bool:
                raise ValueError('explicit color space and boolean alpha association required')
            fact = self.operation_query(operation_id).get('execution_fact')
            if not fact or fact.get('state') != 'COMPLETED':
                raise ValueError('Houdini render has no completed producer receipt')
            if pattern != fact['output_pattern'] or sorted(frame_set) != fact['frame_set']:
                raise ValueError('artifact output differs from producing render')
            if fact['dependencies'] != FeedbackVersions(self).dependencies():
                raise ValueError('producing render dependencies are no longer current')
            receipt_sources = self._registry_receipt_sources(fact)
            # 新操作可接替已失效版本；同操作重用仍在下面执行完整 verify。
            prior = self.artifact_registry.registration_head(str(artifact_id), task_id=fact['task_id'])
            if prior and prior.get('operation_id') == str(operation_id):
                if receipt_sources is None:
                    from dcc_task_runtime.artifact_registry import ArtifactError
                    raise ArtifactError('REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED')
                expected = {'task_id': fact['task_id'], 'artifact_class': str(artifact_class),
                    'pattern': fact['output_pattern'], 'frame_set': fact['frame_set'],
                    'colorspace': colorspace, 'premultiplied': premultiplied,
                    'dependencies': sorted(fact['dependencies']),
                    'scene_fingerprint': fact['scene_fingerprint'],
                    'operation_receipt_sha256': fact['operation_receipt_sha256']}
                if any(prior.get(key) != value for key, value in expected.items()):
                    raise ValueError('registration request differs from the previous registration')
                # registration_head仅含原条目；同操作恢复必须读取并核验已提交的正式回执。
                receipt = self.artifact_registry.lookup_operation_receipt(str(artifact_id), prior['version'])
                sources = receipt.get('current_source') or {}
                if not sources or any(sources.get(name) != digest for name, digest in receipt_sources.items()):
                    raise ValueError('previous registration producer source differs from the configured controller')
                report = self.artifact_registry.verify(str(artifact_id))
                if not report.get('usable'):
                    raise ValueError('previous registration is no longer valid')
                return {**prior, 'registry_operation_receipt': receipt}
            receipt_options = {'receipt_source_files': receipt_sources} if receipt_sources is not None else {}
            # 多节点编辑保持每次原反馈版本；只有控制端原库可提供连续完成链。
            def feedback_revision_source(*, task_id, graph_id, from_version, to_version):
                if task_id != self.pipeline_task_id:
                    raise ValueError('FEEDBACK_REVISION_TASK_MISMATCH')
                return FeedbackVersions(self).completed_revision_chain(graph_id, from_version, to_version)
            self.artifact_registry.set_feedback_revision_source(feedback_revision_source)
            if prior and str(prior.get('pattern')) != str(pattern):
                receipt_options['expected_previous_version'] = prior['version']
            return self.artifact_registry.register(artifact_id=str(artifact_id), task_id=fact['task_id'],
                artifact_class=str(artifact_class), pattern=fact['output_pattern'], frame_set=fact['frame_set'],
                colorspace=colorspace, premultiplied=premultiplied, operation_id=str(operation_id),
                dependencies=fact['dependencies'], scene_fingerprint=fact['scene_fingerprint'],
                operation_receipt_sha256=fact['operation_receipt_sha256'], **receipt_options)
        return self.artifact_registry.register(
            artifact_id=str(artifact_id), task_id='nuke:' + str(operation_id),
            artifact_class=str(artifact_class), pattern=str(pattern),
            frame_set=[int(f) for f in frame_set], colorspace=str(colorspace),
            premultiplied=bool(premultiplied), operation_id=str(operation_id),
            dependencies=FeedbackVersions(self).dependencies())

    def consume_artifact(self, artifact_id):
        if self.artifact_registry is None:
            raise ValueError('no artifact ledger is attached to this task')
        entry = self.artifact_registry.lookup(artifact_id)
        if entry is None:
            raise ValueError('unknown artifact')
        report = self.artifact_registry.verify(artifact_id)
        if entry.get('artifact_class') == 'raw_input':
            return {'artifact_id': artifact_id, 'artifact_class': 'raw_input',
                    'usable_as_render_input': False,
                    'hint': 'raw reference material never becomes a render result'}
        result = {'artifact_id': artifact_id, 'artifact_class': entry.get('artifact_class'),
                'operation_id': entry.get('operation_id'),
                'pattern': entry.get('pattern'),
                'colorspace': entry.get('colorspace'), 'premultiplied': entry.get('premultiplied'),
                'operation_receipt_sha256': entry.get('operation_receipt_sha256'),
                'verification': {'ok': report['ok'], 'fresh': report['fresh'],
                                 'readable': report.get('readable', False),
                                 'no_duplicates': report['no_duplicates'],
                                 'metadata_present': report.get('metadata_present', False),
                                 'dependencies_present': report.get('dependencies_present', False),
                                 'usable': report.get('usable', False),
                                 'frame_set': report['frame_set']},
                'usable_as_render_input': bool(report.get('usable', False))}
        if entry.get('project_color') is not None:
            from dcc_task_runtime.project_color import validate_project_color
            result['project_color'] = validate_project_color(entry['project_color'])
        if entry.get('output_verification') is not None:
            result['output_verification'] = json.loads(json.dumps(entry['output_verification'], allow_nan=False))
        receipt = entry.get('registry_operation_receipt')
        if receipt is not None:
            result['registry_operation_receipt'] = self.artifact_registry.verify_operation_receipt(receipt)
        return result


class GraphMCP(DiagnosticMCP):
    def __init__(self, facade):
        super().__init__(facade)
        if not isinstance(facade, GraphRun):
            raise ValueError('explicit construction facade required')
        graph_names = {tool['name'] for tool in GRAPH_TOOLS}
        active = GRAPH_TOOLS
        if getattr(facade, 'application', 'pipeline') == 'nuke':
            unavailable = {'graph_catalog', 'graph_propose', 'graph_trial', 'graph_status',
                'graph_version', 'frame_execute', 'houdini_render_bounded', 'verify_render_output', 'feedback_edit',
                'task_save', 'task_reopen'}
            active = [tool for tool in GRAPH_TOOLS if tool['name'] not in unavailable]
        self._active_graph_names = {tool['name'] for tool in active}
        self.tools = [tool for tool in TOOLS if tool['name'] not in graph_names] + active
        self.server_name = 'bridge-hy3-construction'
        self.instructions = 'Synthetic construction only. Graph proposals are compiled before trials in task-owned Houdini. No arbitrary paths, scripts, simulation, cache, render or acceptance grants. Full Access is user-selected and not an isolation claim.'
        if getattr(facade, 'application', 'pipeline') == 'nuke':
            self.instructions = 'Task-owned Nuke controller. Use only registered inputs and the configured prepared composite. Query persistent operation status after execution. Full Access is user-selected and not an isolation claim.'

    def _call(self, params):
        name = params.get('name')
        if name not in {item['name'] for item in GRAPH_TOOLS}:
            return super()._call(params)
        if name not in self._active_graph_names:
            return {'isError': True, 'content': [_text_content({'code':'APPLICATION_TOOL_UNAVAILABLE'})]}
        arguments = params.get('arguments', {})
        schema = next(item['inputSchema'] for item in GRAPH_TOOLS if item['name']==name)
        if (set(params)-{'name','arguments','_meta'} or not isinstance(arguments,dict)
                or set(arguments)-set(schema['properties']) or set(schema['required'])-set(arguments)):
            return {'isError':True,'content':[_text_content({'code':'INVALID_ARGUMENTS'})]}
        schema_error = _schema_error(arguments, schema)
        if schema_error:
            self.facade.record_event('mcp_tool_rejected', {'tool': name, 'code': 'INVALID_ARGUMENTS'})
            return {'isError':True,'content':[_text_content({'code':'INVALID_ARGUMENTS'})]}
        self.facade.record_event('graph_tool_requested', {'tool':name,'arguments':arguments})
        try:
            result = getattr(self.facade,name)(**arguments)
        except GraphCompileError as exc:
            self.facade.record_event('graph_compile_rejected', {'diagnostics':[d.to_dict() for d in exc.diagnostics]})
            return {'isError':True,'content':[_text_content({'code':'GRAPH_COMPILE_REJECTED','diagnostics':[d.to_dict() for d in exc.diagnostics]})]}
        except (ValueError,TypeError,KeyError) as exc:
            self.facade.record_event('graph_tool_rejected', {'tool':name})
            code = getattr(exc, 'code', None)
            if not isinstance(code, str) or re.fullmatch(r'PRODUCTION_[A-Z0-9_]{1,64}', code) is None:
                code = 'GRAPH_REQUEST_REJECTED'
            return {'isError':True,'content':[_text_content({'code':code,'hint':'Check registered IDs, input schema, required observations and operation status. Do not change request IDs to bypass an unresolved operation.'})]}
        except RuntimeError as exc:
            # structured host errors (BridgeCommandError and friends) reach the
            # model as their stable CODE plus a truncated hint - no paths
            self.facade.record_event('graph_tool_host_error', {'tool':name})
            return {'isError':True,'content':[_text_content({
                'code': str(getattr(exc, 'code', 'HOST_REJECTED')),
                'hint': str(getattr(exc, 'hint', '') or exc)[:200]})]}
        self.facade.record_event('graph_tool_completed', {'tool':name,'result':result})
        return {'isError':False,'content':result if name == 'media_attachments' else [_text_content(result)]}
