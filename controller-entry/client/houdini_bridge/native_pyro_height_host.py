"""A01 HOM carrier integration through the existing add-on transaction helpers.

This host reads the source surface, channels and connections. Solver geometry
is read only by the separately authorized volume_readback method. Ownership,
leases, scene persistence and operation receipts remain owned by the add-on.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
import json
import secrets

from . import native_pyro_height_program as program
from .native_pyro_domains import FIRE, source_program

BASIS_KEY = 'bridge_pyro_height_basis_v1'
PROGRAM_KEY = 'bridge_pyro_height_program_v1'
INPUT_FIELDS = {'h_base', 'axis', 'source_input', 'input_version', 'basis_input_sha256'}
_SNAPSHOTS = {}


class Host:
    def __init__(self, host):
        import hou
        self.h = host
        self.hou = hou

    def call(self, name, *args, **kwargs):
        return self.h[name](*args, **kwargs)

    def error(self, code, detail):
        raise self.h['BridgeCommandError'](code, detail)

    def binding(self, roles, pack):
        if pack.get('native_domain_id') != FIRE:
            self.error('EXPLICIT_FIRE_DOMAIN_REQUIRED', 'A01 belongs only to pyro_fire_v1')
        root = self.call('_fx_planned_owned_root', roles, pack)
        lease = self.call('_root_lease_check', root, scope='sop', renew=False)
        identity = self.call('_host_identity')
        version = self.hou.applicationVersionString()
        if (version not in (*program.SUPPORTED_VERSIONS, *PREPARATION_VERSIONS) or identity.get('task_id') != lease.get('task_id')
                or not identity.get('launch_nonce') or not identity.get('pid') or identity.get('version') != version):
            self.error('PYRO_HEIGHT_OWNED_GRAPH_REQUIRED', 'authenticated same-build host/lease required')
        return {'task_id': lease['task_id'], 'task_root': root, 'native_version': version,
                'paths': {role: roles[role] for role in ('source', 'source_control', 'solver', program.ROLE, 'output')}}

    def _node(self, path):
        node = self.hou.node(path)
        if node is None:
            self.error('PYRO_HEIGHT_OWNED_GRAPH_REQUIRED', 'required node absent: ' + str(path))
        return node

    def _nodes(self, roles, binding, input_version):
        result = {}
        for role in ('source', 'solver', program.ROLE, 'output'):
            node = self._node(roles[role])
            result[role] = {'origin': 'runtime_hom', 'task_owned': True,
                'task_id': binding['task_id'], 'task_root': binding['task_root'],
                'input_version': input_version, 'native_version': binding['native_version'],
                'path': node.path(), 'category': node.type().category().name().lower(),
                'type': node.type().name(), 'editable': node.isEditable(),
                'bypassed': node.isBypassed(), 'space': 'sop_local',
                'inputs': [{'input_index': wire.inputIndex(), 'output_index': wire.outputIndex(),
                            'node_path': wire.inputNode().path()} for wire in node.inputConnections()]}
        return result

    def parameters(self, roles):
        return program.collect_parameters(self._node(roles[program.ROLE]), self.h['_fx_planned_observation'])

    def production(self, roles):
        node = self._node(roles['solver'])
        count = self.call('_fx_planned_observation', node, 'numfields')
        if (count.get('origin') != 'runtime_hom' or count.get('type') != 'multiparm'
                or type(count.get('value')) is not int or not 1 <= count['value'] <= 64
                or count.get('driven') is not False):
            self.error('PYRO_HEIGHT_PRODUCTION_REQUIRED', 'actual bounded solver export allocation required')
        return {'origin': 'runtime_hom', 'node_path': node.path(),
                'addflamefield': self.call('_fx_planned_observation', node, 'addflamefield'),
                'conv_vdb': self.call('_fx_planned_observation', node, 'conv_vdb'),
                'exports': [{'enable': self.call('_fx_planned_observation', node, 'export_enable' + str(index)),
                             'name': self.call('_fx_planned_observation', node, 'export_fieldname' + str(index))}
                            for index in range(1, count['value'] + 1)]}

    def _context(self, roles, binding, data, frame, basis=None):
        source_node = self._node(roles['source'])
        source = program.collect_source_geometry(source_node.geometryAtFrame(frame, output_index=0),
                                                  node_path=source_node.path(), frame=frame)
        registration = source_program(FIRE, binding['native_version'], data['source_input'])
        if data['axis'] != registration['source']['direction']:
            self.error('PYRO_HEIGHT_BASIS_REQUIRED', 'axis must equal the actual trusted emitter axis')
        current_basis = program.freeze_basis(binding['native_version'], data['h_base'], data['axis'], source,
            task_id=binding['task_id'], task_root=binding['task_root'], input_version=data['input_version'],
            basis_input_sha256=data['basis_input_sha256'], source_program_sha256=registration['sha256'])
        if basis is not None and current_basis != basis:
            self.error('PYRO_HEIGHT_BASIS_CHANGED', 'actual source vertices or frozen input binding differs')
        context = {'basis': current_basis, 'source': source, 'source_input': copy.deepcopy(data['source_input']),
            'source_program': registration, 'nodes': self._nodes(roles, binding, data['input_version']),
            'production': self.production(roles),
            'source_program_observation': self.call('_fx_planned_observation', self._node(roles['source_control']), 'snippet')}
        program.validate_context(binding['native_version'], context)
        return context

    def _input(self, supplied):
        if not isinstance(supplied, dict) or set(supplied) != INPUT_FIELDS:
            self.error('PYRO_HEIGHT_BASIS_REQUIRED', 'explicit fields required: ' + ','.join(sorted(INPUT_FIELDS)))
        return copy.deepcopy(supplied)

    def context(self, roles, pack):
        binding = self.binding(roles, pack)
        raw = self._node(roles[program.ROLE]).userData(BASIS_KEY)
        if raw is None:
            self.error('PYRO_HEIGHT_BASIS_REQUIRED', 'explicit frozen A01 basis missing')
        try:
            frozen = json.loads(raw)
            if (set(frozen) != {'schema', 'binding', 'input', 'frame', 'basis', 'content_sha256'}
                    or frozen['schema'] != program.BASIS_SCHEMA or frozen['binding'] != binding
                    or frozen['content_sha256'] != program.basis_content_sha256(frozen)):
                self.error('PYRO_HEIGHT_BASIS_CHANGED', 'stored basis binding or digest differs')
            return self._context(roles, binding, self._input(frozen['input']), frozen['frame'], frozen['basis'])
        except (ValueError, KeyError, TypeError) as error:
            self.error(getattr(error, 'code', 'PYRO_HEIGHT_BASIS_CHANGED'), str(error))

    def _snapshot(self, roles, binding):
        if len(_SNAPSHOTS) >= 1024:
            self.error('PYRO_HEIGHT_SNAPSHOT_BUDGET_EXCEEDED', 'release finalized local snapshots before new writes')
        node = self._node(roles[program.ROLE])
        channels = {}
        for name in (*program.GATES, 'snippet'):
            target = self.call('_resolve_parm_target', node, [name])
            channels[name] = self.call('_snapshot_parm_state', target)
        token = secrets.token_urlsafe(32)
        identity = self.call('_host_identity')
        _SNAPSHOTS[token] = {'binding': copy.deepcopy(binding), 'channels': channels,
                'owner': {key: identity.get(key) for key in
                          ('pid', 'launch_nonce', 'process_generation', 'session_id', 'scene_epoch')},
                'userdata': {key: node.userData(key) for key in (BASIS_KEY, PROGRAM_KEY)}}
        return {'binding': copy.deepcopy(binding), 'token': token}

    def release_snapshot(self, snapshot):
        token = snapshot.get('token') if isinstance(snapshot, dict) else None
        original = _SNAPSHOTS.get(token)
        if original is not None and snapshot.get('binding') == original['binding']:
            del _SNAPSHOTS[token]

    def restore(self, snapshot, roles, pack):
        original = _SNAPSHOTS.get(snapshot.get('token')) if isinstance(snapshot, dict) else None
        if (original is None or set(snapshot) != {'binding', 'token'}
                or snapshot['binding'] != original['binding'] or original['binding'] != self.binding(roles, pack)):
            self.error('PYRO_HEIGHT_ROLLBACK_OWNER_CHANGED', 'original owner/graph binding required')
        identity = self.call('_host_identity')
        if any(identity.get(key) != value for key, value in original['owner'].items()):
            self.error('PYRO_HEIGHT_ROLLBACK_OWNER_CHANGED', 'rollback cannot cross the issuing host identity')
        node = self._node(roles[program.ROLE])
        for name, channel in reversed(tuple(original['channels'].items())):
            target = self.call('_resolve_parm_target', node, [name])
            self.call('_restore_parm_snapshot', target, channel)
            if self.call('_snapshot_parm_state', target) != channel:
                self.error('PARAMETER_RESTORE_MISMATCH', 'A01 channel restoration differs: ' + name)
        for key, value in original['userdata'].items():
            if value is None:
                if node.userData(key) is not None:
                    node.destroyUserData(key)
            else:
                node.setUserData(key, value)
            if node.userData(key) != value or (key in node.userDataDict()) != (value is not None):
                self.error('PARAMETER_RESTORE_MISMATCH', 'A01 registration restoration differs: ' + key)

    def initialize(self, params, roles, pack, fresh_roles):
        supplied = self.call('_fx_configuration', params).get('pyro_height_basis')
        node = self.hou.node(roles.get(program.ROLE, ''))
        registered = node is not None and node.userData(BASIS_KEY) is not None
        if supplied is None and not registered:
            return {'status': 'blocked', 'code': 'PYRO_HEIGHT_BASIS_REQUIRED',
                    'evidence_scope': 'parameters_only', 'missing_evidence': sorted(INPUT_FIELDS)}
        binding = self.binding(roles, pack)
        node = self._node(roles[program.ROLE])
        if supplied is None:
            return self.readback(roles, pack)
        data = self._input(supplied)
        if node.userData(BASIS_KEY) is not None:
            frozen = json.loads(node.userData(BASIS_KEY))
            if program.basis_content_sha256(frozen.get('input', {})) != program.basis_content_sha256(data):
                self.error('PYRO_HEIGHT_BASIS_CHANGED', 'rebuild cannot replace the frozen basis')
            return self.readback(roles, pack)
        if program.ROLE not in fresh_roles:
            self.error('PYRO_HEIGHT_BASIS_REQUIRED', 'initial registration requires a fresh owned mask')
        context = self._context(roles, binding, data, float(self.hou.frame()))
        snapshot = self._snapshot(roles, binding)
        candidate = None
        try:
            for write in program.initialization_plan():
                actual = self.call('_fx_planned_observation', node, write['parm'])
                if (actual['type'] != write['native_type'] or type(actual['size']) is not int or actual['size'] != 1
                        or any(actual.get(flag) is not False for flag in ('locked', 'disabled', 'hidden', 'driven'))):
                    self.error('PYRO_HEIGHT_RUNTIME_REQUIRED', write['parm'])
                target = self.call('_resolve_parm_target', node, [write['parm']])
                self.call('_set_parm_verified', target, write['value'])
            frozen = {'schema': program.BASIS_SCHEMA, 'binding': binding, 'input': data,
                      'frame': context['source']['frame'], 'basis': context['basis']}
            frozen['content_sha256'] = program.basis_content_sha256(frozen)
            node.setUserData(BASIS_KEY, json.dumps(frozen, sort_keys=True, allow_nan=False))
            candidate = self.plan(0., roles, pack)
            result = self.write(candidate, roles, pack)
            self.release_snapshot(candidate['snapshot'])
            self.release_snapshot(snapshot)
            return result
        except Exception:
            self.restore(snapshot, roles, pack)
            raise
        finally:
            self.release_snapshot(snapshot)
            if candidate is not None:
                self.release_snapshot(candidate['snapshot'])

    def plan(self, value, roles, pack):
        context = self.context(roles, pack)
        plan = program.plan_control(self.hou.applicationVersionString(), value, context, self.parameters(roles))
        writes = program.validate_plan(plan, context, self.parameters(roles))
        snapshot = self._snapshot(roles, self.binding(roles, pack))
        _SNAPSHOTS[snapshot['token']]['plan_seal'] = plan.seal
        return {'plan': plan, 'writes': writes, 'snapshot': snapshot}

    def write(self, candidate, roles, pack):
        plan = candidate['plan']
        context = self.context(roles, pack)
        writes = program.validate_plan(plan, context, self.parameters(roles))
        if program._hash(candidate.get('writes')) != program._hash(writes) or candidate['snapshot']['binding'] != self.binding(roles, pack):
            self.error('PYRO_HEIGHT_INVALID_PLAN', 'candidate writes or owner binding changed')
        snapshot = _SNAPSHOTS.get(candidate['snapshot'].get('token'))
        if (snapshot is None or snapshot['binding'] != candidate['snapshot']['binding']
                or snapshot.get('plan_seal') != plan.seal):
            self.error('PYRO_HEIGHT_INVALID_PLAN', 'original local rollback snapshot missing')
        node = self._node(roles[program.ROLE])
        try:
            target = self.call('_resolve_parm_target', node, ['snippet'])
            self.call('_set_parm_verified', target, writes[0]['value'])
            program.validate_plan(plan, self.context(roles, pack), self.parameters(roles), after_mutation=True)
            node.setUserData(PROGRAM_KEY, json.dumps(writes[0]['trusted_program'], sort_keys=True, allow_nan=False))
            return self.readback(roles, pack)
        except Exception:
            self.restore(candidate['snapshot'], roles, pack)
            raise

    def readback(self, roles, pack):
        context = self.context(roles, pack)
        version = self.hou.applicationVersionString()
        observed = program.control_readback(version, context, self.parameters(roles))
        raw = self._node(roles[program.ROLE]).userData(PROGRAM_KEY)
        if raw is None:
            self.error('PYRO_HEIGHT_READBACK_MISMATCH', 'persisted program registration missing')
        try:
            registration = json.loads(raw)
        except ValueError as error:
            self.error('PYRO_HEIGHT_READBACK_MISMATCH', str(error))
        if program._hash(registration) != program._hash(program.source_program(version, observed['value'], context)):
            self.error('PYRO_HEIGHT_READBACK_MISMATCH', 'persisted registration differs from actual channel/basis')
        return {'status': 'observed', **observed, 'registration': registration}

    def volume_readback(self, roles, pack, *, already_observed_geometry):
        """Use authorized caller-supplied native geometry; never cook the solver."""
        if not isinstance(already_observed_geometry, dict) or set(already_observed_geometry) != {'solver', program.ROLE}:
            self.error('PYRO_HEIGHT_VOLUME_REQUIRED', 'independent native producer and mask geometries required')
        frame = float(self.hou.frame())
        before = program.collect_volume_fields(already_observed_geometry['solver'], node_path=roles['solver'], frame=frame)
        after = program.collect_volume_fields(already_observed_geometry[program.ROLE], node_path=roles[program.ROLE], frame=frame)
        return program.validate_volume_readback(self.hou.applicationVersionString(), self.context(roles, pack),
                                                self.parameters(roles), before, after)
