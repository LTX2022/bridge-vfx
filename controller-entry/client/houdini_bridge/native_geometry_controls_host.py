"""Bounded G03 HOM adapter; operation and producer lifecycles stay in the addon.

Inject the existing ownership, lease, parameter and transaction helpers. Three
additional hooks are mandatory, with no fallback to client configuration:

``_fx_geometry_source_basis(roles, pack, binding)`` authenticates the current
frozen input and rest provenance from the server registry. Return task_id,
task_root, native_version, input_version, basis_input_sha256, source_geometry_sha256, source_node_path,
output, frame, space, unit and local_x_axis. These are facts, not defaults.
``_fx_geometry_source_geometry(node, provenance)`` returns that source's actual
geometry at the authenticated rest frame, already obtained or acquired under
separate cook authorization. Cross-frame access also reads current SOP output
and requires unchanged P/N/id, attribute storage and topology. Context source
retains the rest frame; source_sampling records the actual current sample frame.
``_fx_geometry_registration(action, roles, pack, record)`` must return True.
Actions authorize_fresh/register/verify/authorize_restore/revoke use the server creation and
initialization registry, never merely trust userData. Restore authority verifies
the exact prepared native target without re-reading failed external input.
Revoke is idempotent and
limited to this exact record. Register/revoke participate in the addon build
transaction; initialization failure still requires destroying its fresh nodes.

Call initialize only from the leased fresh build transaction. Feedback uses
plan -> prepare -> write, restore on transaction failure, then release on either
outcome. The enclosing addon transaction holds its root lease fence across all
manifest/save work; this adapter does not acquire that non-reentrant lock again.
Parameters and userData are restored through existing snapshot hooks. No VEX
cook, deformed output, downstream consumption or save/reopen PASS is issued.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
from itertools import islice
import json
import secrets

from . import native_geometry_controls_program as program

BASIS_KEY = 'bridge_geometry_deform_basis_v1'
REGISTRATION_KEY = 'bridge_geometry_deform_initialization_v1'
ROLES = ('instance_source', program.ROLE, 'instance_transform')
_SNAPSHOTS = {}


class Host:
    def __init__(self, host, *, hou_module=None):
        if hou_module is None:
            import hou as hou_module
        self.host = host
        self.hou = hou_module

    def call(self, name, *args, **kwargs):
        callback = self.host.get(name)
        if not callable(callback):
            program._fail('GEOMETRY_HOST_HOOK_REQUIRED', name)
        return callback(*args, **kwargs)

    def binding(self, roles, pack):
        if pack.get('native_domain_id') != 'procedural_geometry_v1':
            program._fail('GEOMETRY_HOST_DOMAIN_REQUIRED', 'G03 belongs to procedural geometry')
        if any(role not in roles for role in ROLES):
            program._fail('GEOMETRY_OWNED_GRAPH_REQUIRED', 'source, deform and transform roles required')
        root = self.call('_fx_planned_owned_root', roles, pack)
        lease = self.call('_root_lease_check', root, scope='sop', renew=False)
        identity = (self.call('_fx_geometry_host_identity', lease['task_id'])
                    if callable(self.host.get('_fx_geometry_host_identity')) else self.call('_host_identity'))
        version = self.hou.applicationVersionString()
        if (version not in (*program.VERSIONS, *PREPARATION_VERSIONS) or not lease.get('task_id')
                or identity.get('task_id') != lease['task_id'] or identity.get('version') != version
                or not isinstance(identity.get('launch_nonce'), str) or not identity['launch_nonce']
                or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or type(identity.get('scene_epoch')) is not int or identity['scene_epoch'] < 0):
            program._fail('GEOMETRY_AUTHENTICATED_HOST_REQUIRED', 'current native host and root lease differ')
        return dict(task_id=lease['task_id'], task_root=root, native_version=version,
                    host_identity=copy.deepcopy(identity))

    def _node(self, roles, role):
        node = self.hou.node(roles[role])
        if node is None or node.path() != roles[role]:
            program._fail('GEOMETRY_OWNED_GRAPH_REQUIRED', role + '/actual node absent')
        return node

    def _source(self, node, provenance):
        geometry = self.call('_fx_geometry_source_geometry', node, copy.deepcopy(provenance))
        return self._observe_source(node, geometry, provenance, provenance['frame'])

    def _observe_source(self, node, geometry, provenance, frame):
        if geometry is None:
            program._fail('GEOMETRY_REST_SOURCE_REQUIRED', 'authorized source geometry unavailable')
        points = tuple(islice(iter(geometry.points()), 8193))
        primitives = tuple(islice(iter(geometry.prims()), 8193))
        if len(points) > 8192 or len(primitives) > 8192:
            program._fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED', '8192 points/primitives')
        point_indices = {point.number(): index for index, point in enumerate(points)}
        if len(point_indices) != len(points):
            program._fail('GEOMETRY_UNPACKED_SOURCE_REQUIRED', 'duplicate point numbers')
        source = dict(origin='runtime_hom', node_path=node.path(), output=provenance['output'],
                      frame=frame, space=provenance['space'], unit=provenance['unit'],
                      points=len(points), point_attributes={}, primitive_types=[], polygons=[])
        for name in ('P', 'N', 'id'):
            attribute = geometry.findPointAttrib(name)
            if attribute is None or attribute.name() != name or attribute.size() not in (1, 3):
                program._fail('GEOMETRY_SOURCE_ATTRIBUTE_REQUIRED', name)
            kind = str(attribute.dataType()).rsplit('.', 1)[-1].lower()
            if kind == 'int':
                kind = 'integer'
            precision = str(attribute.numericDataType()).rsplit('.', 1)[-1].lower()
            values = []
            for point in points:
                value = point.attribValue(name)
                if isinstance(value, (tuple, list)):
                    if len(value) > 3:
                        program._fail('GEOMETRY_SOURCE_ATTRIBUTE_REQUIRED', name + '/unbounded tuple')
                    value = list(value)
                values.append(value)
            source['point_attributes'][name] = dict(owner='point', type=kind, size=attribute.size(),
                precision=precision, is_array=attribute.isArrayType(), values=values)
        total_vertices = 0
        for primitive in primitives:
            if primitive.type().name() != 'Polygon':
                program._fail('GEOMETRY_UNPACKED_SOURCE_REQUIRED', 'only actual unpacked polygons supported')
            vertices = tuple(islice(iter(primitive.vertices()), 65537 - total_vertices))
            total_vertices += len(vertices)
            if total_vertices > 65536:
                program._fail('GEOMETRY_OBSERVATION_BUDGET_EXCEEDED', '65536 vertices')
            try:
                polygon = [point_indices[vertex.point().number()] for vertex in vertices]
            except KeyError as error:
                raise program.GeometryControlsError('GEOMETRY_UNPACKED_SOURCE_REQUIRED',
                                                    'vertex references an absent point') from error
            source['primitive_types'].append('Polygon')
            source['polygons'].append(polygon)
        program.source_geometry_sha256(source)
        return source

    def _current_source(self, node, source, provenance, frame):
        if program._number(self.hou.frame(), 'current native frame') != frame:
            program._fail('GEOMETRY_SOURCE_FRAME_REQUIRED', 'native frame changed before current geometry observation')
        if frame == provenance['frame']:
            return source
        observe = getattr(node, 'geometry', None)
        if not callable(observe):
            program._fail('GEOMETRY_CURRENT_SOURCE_REQUIRED', 'actual current-frame SOP output required')
        current = self._observe_source(node, observe(output_index=provenance['output']), provenance, frame)
        if program._number(self.hou.frame(), 'current native frame') != frame:
            program._fail('GEOMETRY_SOURCE_FRAME_REQUIRED', 'native frame changed during current geometry observation')
        if ({name: value for name, value in current.items() if name != 'frame'}
                != {name: value for name, value in source.items() if name != 'frame'}):
            program._fail('GEOMETRY_STATIC_SOURCE_REQUIRED', 'current P/N/id and topology differ from rest')
        return current

    def _context(self, roles, pack, binding):
        frame = program._number(self.hou.frame(), 'current native frame')
        provenance = self.call('_fx_geometry_source_basis', roles, pack, copy.deepcopy(binding))
        required = ('input_version', 'basis_input_sha256', 'source_geometry_sha256', 'source_node_path', 'output',
                    'frame', 'space', 'unit', 'local_x_axis')
        if (not isinstance(provenance, dict) or any(name not in provenance for name in required)
                or any(provenance.get(name) != binding[name]
                       for name in ('task_id', 'task_root', 'native_version'))
                or provenance['source_node_path'] != roles['instance_source']):
            program._fail('GEOMETRY_AUTHENTICATED_REST_BASIS_REQUIRED', 'server source provenance required')
        if (type(provenance['output']) is not int or provenance['output'] != 0
                or provenance['space'] != 'sop_local_rest' or provenance['unit'] != 'SU'):
            program._fail('GEOMETRY_AUTHENTICATED_REST_BASIS_REQUIRED', 'explicit rest output, space and units required')
        program._number(provenance['frame'], 'authenticated source frame')
        nodes = {}
        for role in ROLES:
            node = self._node(roles, role)
            if not node.path().startswith(binding['task_root'] + '/'):
                program._fail('GEOMETRY_OWNED_GRAPH_REQUIRED', role + '/outside leased root')
            connections = tuple(islice(iter(node.inputConnections()), 3))
            if len(connections) > 2:
                program._fail('GEOMETRY_SOURCE_CONNECTION_REQUIRED', role + '/extra inputs')
            nodes[role] = dict(origin='runtime_hom', task_owned=True, task_id=binding['task_id'],
                task_root=binding['task_root'], native_version=binding['native_version'],
                input_version=provenance['input_version'], path=node.path(),
                session_id=node.sessionId(),
                category=node.type().category().name().lower(), type=node.type().name(),
                editable=node.isEditable(), bypassed=node.isBypassed(), space=provenance['space'],
                inputs=[dict(input_index=wire.inputIndex(), output_index=wire.outputIndex(),
                             node_path=wire.inputNode().path()) for wire in connections])
        source_node = self._node(roles, 'instance_source')
        source = self._source(source_node, provenance)
        current = self._current_source(source_node, source, provenance, frame)
        if program._number(self.hou.frame(), 'current native frame') != frame:
            program._fail('GEOMETRY_SOURCE_FRAME_REQUIRED', 'native frame changed during rest geometry observation')
        if (self.binding(roles, pack) != binding or
                self.call('_fx_geometry_source_basis', roles, pack, copy.deepcopy(binding)) != provenance):
            program._fail('GEOMETRY_CONTEXT_CHANGED', 'authenticated source changed during geometry observation')
        if (not program._digest(provenance['source_geometry_sha256']) or
                program.source_geometry_sha256(source) != provenance['source_geometry_sha256']):
            program._fail('GEOMETRY_BASIS_CHANGED', 'actual rest geometry differs from authenticated input')
        basis = program.freeze_basis(binding['native_version'], source,
            local_x_axis=provenance['local_x_axis'], task_id=binding['task_id'],
            task_root=binding['task_root'], input_version=provenance['input_version'],
            basis_input_sha256=provenance['basis_input_sha256'])
        context = dict(basis=basis, source=source, nodes=nodes,
                       host_identity=copy.deepcopy(binding['host_identity']),
                       source_sampling=dict(rest_frame=provenance['frame'], current_frame=frame,
                           current_source_geometry_sha256=program.source_geometry_sha256(current),
                           static_source_verified=True))
        program.validate_context(binding['native_version'], context)
        if program._number(self.hou.frame(), 'current native frame') != frame:
            program._fail('GEOMETRY_SOURCE_FRAME_REQUIRED', 'native frame changed during context validation')
        return context

    def _registration(self, context):
        basis = context['basis']
        zero = program.source_program(basis['native_version'], 0, context)
        return dict(schema=program.REGISTRATION_SCHEMA, origin='runtime_hom', initialized=True,
            registered=True, generator=program.GENERATOR, task_id=basis['task_id'],
            task_root=basis['task_root'], input_version=basis['input_version'],
            native_version=basis['native_version'], node_path=context['nodes'][program.ROLE]['path'],
            basis_sha256=basis['content_sha256'], initial_program_sha256=zero['sha256'],
            gates_sha256=program._hash(program.GATES))

    def _registry(self, action, roles, pack, record):
        if self.call('_fx_geometry_registration', action, roles, pack, copy.deepcopy(record)) is not True:
            program._fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED', 'server registry rejected ' + action)

    def _userdata(self, node):
        return {name: node.userData(name) for name in (BASIS_KEY, REGISTRATION_KEY)}

    def _restore_userdata(self, node, values):
        for name, value in values.items():
            if value is None:
                node.destroyUserData(name)
            else:
                node.setUserData(name, value)
        if self._userdata(node) != values:
            program._fail('GEOMETRY_RESTORE_FAILED', 'native userData restoration differs')

    def initialize(self, params, roles, pack, fresh_roles):
        binding = self.binding(roles, pack)
        node = self._node(roles, program.ROLE)
        before = self._userdata(node)
        if any(value is not None for value in before.values()):
            observed = self.observations(roles, pack)
            return program.control_readback(binding['native_version'], observed['context'], observed['parameters'])
        if program.ROLE not in fresh_roles:
            program._fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED', 'existing unregistered carrier cannot be adopted')
        context = self._context(roles, pack, binding)
        record = self._registration(context)
        self._registry('authorize_fresh', roles, pack, record)
        snippet = self.call('_fx_planned_observation', node, 'snippet')
        if (snippet.get('value') != '' or snippet.get('type') != 'string' or snippet.get('size') != 1
                or any(snippet.get(flag) is not False for flag in ('driven', 'locked', 'disabled', 'hidden'))):
            program._fail('GEOMETRY_FOREIGN_PROGRAM_REJECTED', 'only a fresh empty writable snippet may initialize')
        writes = program.initialization_plan() + [dict(role=program.ROLE, parm='snippet',
            native_type='string', value=program.source_program(binding['native_version'], 0, context)['program'])]
        try:
            self.call('_fx_apply_fresh_domain_plan', writes, roles, fresh_roles)
            context['initialization'] = record
            parameters = program.collect_parameters(node, self.host['_fx_planned_observation'])
            result = program.control_readback(binding['native_version'], context, parameters)
            if self.binding(roles, pack) != binding or self._context(roles, pack, binding) != {
                    key: value for key, value in context.items() if key != 'initialization'}:
                program._fail('GEOMETRY_CONTEXT_CHANGED', 'source or identity changed during initialization')
            self._registry('register', roles, pack, record)
            node.setUserData(BASIS_KEY, program._json(context['basis']))
            node.setUserData(REGISTRATION_KEY, program._json(record))
            self.observations(roles, pack)
            return result
        except Exception:
            try:
                self._registry('revoke', roles, pack, record)
            finally:
                self._restore_userdata(node, before)
            raise

    def observations(self, roles, pack):
        frame = program._number(self.hou.frame(), 'current native frame')
        binding = self.binding(roles, pack)
        provenance = self.call('_fx_geometry_source_basis', roles, pack, copy.deepcopy(binding))
        context = self._context(roles, pack, binding)
        node = self._node(roles, program.ROLE)
        raw = self._userdata(node)
        try:
            basis = json.loads(raw[BASIS_KEY])
            record = json.loads(raw[REGISTRATION_KEY])
        except (TypeError, ValueError) as error:
            raise program.GeometryControlsError('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED',
                                                'persisted basis and initialization required') from error
        if basis != context['basis']:
            program._fail('GEOMETRY_BASIS_CHANGED', 'current authenticated source differs from persisted rest basis')
        context['initialization'] = record
        program._registered_context(context, basis)
        self._registry('verify', roles, pack, record)
        parameters = program.collect_parameters(node, self.host['_fx_planned_observation'])
        program.control_readback(binding['native_version'], context, parameters)
        if (self.binding(roles, pack) != binding or
                self.call('_fx_geometry_source_basis', roles, pack, copy.deepcopy(binding)) != provenance):
            program._fail('GEOMETRY_CONTEXT_CHANGED', 'authenticated source changed during parameter observation')
        if (program._number(self.hou.frame(), 'current native frame') != frame
                or context['source_sampling']['current_frame'] != frame):
            program._fail('GEOMETRY_SOURCE_FRAME_REQUIRED', 'native frame changed during parameter observation')
        return dict(context=context, parameters=parameters, binding=binding)

    def plan(self, value, roles, pack):
        observed = self.observations(roles, pack)
        return program.plan_control(observed['binding']['native_version'], value,
                                    observed['context'], observed['parameters'])

    def prepare(self, plan, roles, pack):
        observed = self.observations(roles, pack)
        writes = program.validate_plan(plan, observed['context'], observed['parameters'])
        if len(_SNAPSHOTS) >= 128:
            program._fail('GEOMETRY_SNAPSHOT_BUDGET_EXCEEDED', 'release completed transaction snapshots')
        node = self._node(roles, program.ROLE)
        parameter = self.call('_resolve_parm_target', node, ['snippet'])
        if parameter is None or parameter.path() != node.path() + '/snippet':
            program._fail('GEOMETRY_PARAMETER_UNAVAILABLE', 'actual snippet target required')
        snapshot = self.call('_snapshot_parm_state', parameter, capture_extrapolation=True)
        if (snapshot.get('mode') != 'hom_channels' or len(snapshot.get('components', ())) != 1
                or snapshot.get('evaluated') != observed['parameters'][program.ROLE, 'snippet']['value']):
            program._fail('GEOMETRY_NATIVE_SNAPSHOT_REQUIRED', 'full native channel snapshot required')
        token = secrets.token_hex(32)
        _SNAPSHOTS[token] = dict(plan=plan, write=copy.deepcopy(writes[0]), node=node, parm=parameter,
            node_session_id=node.sessionId(), snapshot=snapshot, userdata=self._userdata(node), binding=observed['binding'],
            roles=copy.deepcopy(roles), pack=copy.deepcopy(pack))
        return dict(geometry_snapshot=token, node=node, parm=parameter,
                    native_write=copy.deepcopy(writes[0]), invalidates_from='shaping_meshing')

    def _snapshot(self, item, roles, pack):
        snapshot = _SNAPSHOTS.get(item.get('geometry_snapshot'))
        if (snapshot is None or item.get('node') is not snapshot['node']
                or item.get('parm') is not snapshot['parm'] or item.get('native_write') != snapshot['write']
                or roles != snapshot['roles'] or pack != snapshot['pack']):
            program._fail('GEOMETRY_PLAN_CHANGED', 'prepared transaction handle or target differs')
        if (self.binding(roles, pack) != snapshot['binding']
                or self._node(roles, program.ROLE).sessionId() != snapshot['node_session_id']):
            program._fail('GEOMETRY_CONTEXT_CHANGED', 'current host or carrier identity differs')
        return snapshot

    def _verify_snapshot(self, snapshot, *, after_mutation=False):
        for state in snapshot['snapshot']['components']:
            expected = dict(state)
            if after_mutation:
                expected['value'] = snapshot['write']['value']
            if not self.call('_verify_component_state', expected):
                program._fail('GEOMETRY_CONTEXT_CHANGED', 'full native snippet channel state differs')

    def validate(self, item, roles, pack):
        snapshot = self._snapshot(item, roles, pack)
        if self._userdata(snapshot['node']) != snapshot['userdata']:
            program._fail('GEOMETRY_CONTEXT_CHANGED', 'initialization userData changed after prepare')
        self._verify_snapshot(snapshot)
        observed = self.observations(roles, pack)
        program.validate_plan(snapshot['plan'], observed['context'], observed['parameters'])
        return observed

    def write(self, item, roles, pack):
        observed = self.validate(item, roles, pack)
        snapshot = self._snapshot(item, roles, pack)
        native_readback = self.call('_set_parm_verified', snapshot['parm'], snapshot['write']['value'])
        after = self.observations(roles, pack)
        program.validate_plan(snapshot['plan'], after['context'], after['parameters'], after_mutation=True)
        self._snapshot(item, roles, pack)
        self._verify_snapshot(snapshot, after_mutation=True)
        if self._userdata(snapshot['node']) != snapshot['userdata']:
            program._fail('GEOMETRY_CONTEXT_CHANGED', 'initialization userData changed during write')
        result = program.control_readback(observed['binding']['native_version'], after['context'], after['parameters'])
        return dict(result, parameter='snippet', parameter_path=snapshot['parm'].path(),
                    readback_verified=True, native_parameter_readback=native_readback,
                    invalidates_from='shaping_meshing')

    def restore(self, item, roles, pack):
        snapshot = self._snapshot(item, roles, pack)
        record = json.loads(snapshot['userdata'][REGISTRATION_KEY])
        self._registry('authorize_restore', roles, pack, record)
        errors = []
        try:
            self.call('_restore_parm_snapshot', snapshot['parm'], snapshot['snapshot'])
        except Exception as error:
            errors.append(str(error))
        try:
            self._restore_userdata(snapshot['node'], snapshot['userdata'])
        except Exception as error:
            errors.append(str(error))
        if errors:
            program._fail('GEOMETRY_RESTORE_FAILED', '; '.join(errors))
        parameters = program.collect_parameters(snapshot['node'], self.host['_fx_planned_observation'])
        if program._json(program._parameters(parameters)) != snapshot['plan'].frozen_parameters_json:
            program._fail('GEOMETRY_RESTORE_FAILED', 'actual parameter state differs from frozen pre-write state')
        self._snapshot(item, roles, pack)
        return dict(status='restored', evidence_scope='parameters_only')

    def rollback(self, item, roles, pack):
        return self.restore(item, roles, pack)

    def release(self, item):
        _SNAPSHOTS.pop(item.get('geometry_snapshot'), None)
