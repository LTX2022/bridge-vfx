"""RBD HOM carrier adapter using the add-on's lease and transaction helpers."""
from __future__ import annotations

import copy
from functools import wraps
from itertools import islice
import json
import math
import secrets
from threading import RLock

from . import native_rbd_controls_program as program
from . import native_flip_rbd_domains as core

BASIS_KEY = 'bridge_rbd_velocity_basis_v1'
PROGRAM_KEY = 'bridge_rbd_velocity_program_v1'
AUTHORITY_KEY = '_BRIDGE_RBD_VELOCITY_AUTHORITY'
MAX_REGISTERED_ROOTS = 128
CHECKPOINT_SCHEMA = 'bridge.rbd-velocity-checkpoint/1'
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024


def _checkpoint_json(value):
    remaining = 2 * program.MAX_GEOMETRY_VALUES

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            program._fail('RBD_CHECKPOINT_BUDGET_EXCEEDED', 'bounded checkpoint structure required')
        if type(item) is dict:
            for name, child in item.items():
                if type(name) is not str:
                    program._fail('RBD_CHECKPOINT_INVALID', 'string checkpoint keys required')
                visit(name, depth + 1)
                visit(child, depth + 1)
        elif type(item) in (list, tuple):
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > MAX_CHECKPOINT_BYTES:
                program._fail('RBD_CHECKPOINT_BUDGET_EXCEEDED', 'bounded checkpoint string required')
        elif item is not None and type(item) not in (bool, int, float):
            program._fail('RBD_CHECKPOINT_INVALID', 'JSON checkpoint required')

    visit(value, 0)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, OverflowError):
        program._fail('RBD_CHECKPOINT_INVALID', 'finite checkpoint facts required')
    if len(encoded.encode('utf-8')) > MAX_CHECKPOINT_BYTES:
        program._fail('RBD_CHECKPOINT_BUDGET_EXCEEDED', 'complete checkpoint exceeds receipt budget')
    return json.loads(encoded)


def _serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self.authority['lock']:
            return method(self, *args, **kwargs)
    return invoke


class Host:
    def __init__(self, host, hou_module=None):
        if hou_module is None:
            import hou as hou_module
        self.h = host
        self.hou = hou_module
        self.authority = host.setdefault(AUTHORITY_KEY, dict(lock=RLock(), records={}))
        self.authority.setdefault('transactions', {})

    def _copy_record(self, record):
        if record is None:
            return None
        return {key: value if key == 'nodes' else copy.deepcopy(value) for key, value in record.items()}

    def _capture(self, roles, pack):
        binding, identity = self.binding(roles, pack)
        frame = self.hou.frame()
        if type(frame) not in (int, float) or not math.isfinite(frame):
            program._fail('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED', 'finite current frame required')
        nodes, facts, parameters, wires = {}, {}, {}, {}
        for role in ('configure', program.ROLE, 'solver'):
            node = self.hou.node(roles.get(role, ''))
            if node is None:
                program._fail('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED', role)
            nodes[role] = node
        data = {name: nodes[program.ROLE].userData(name) for name in (BASIS_KEY, PROGRAM_KEY)}
        if any(value is not None and (type(value) is not str
                                     or len(value) > program.MAX_GEOMETRY_BYTES + 4096
                                     or len(value.encode('utf-8')) > program.MAX_GEOMETRY_BYTES + 4096)
                for value in data.values()):
            program._fail('RBD_VELOCITY_AUTHORITY_BUDGET_EXCEEDED', 'bounded native registration required')
        fps = self.hou.fps()
        for role, node in nodes.items():
            try:
                facts[role] = dict(node_path=node.path(), session_id=node.sessionId(),
                    type=node.type().name(), category=node.type().category().name().lower(),
                    editable=node.isEditable(), bypassed=node.isBypassed(), errors=list(node.errors()))
            except Exception:
                program._fail('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED', 'native node state/' + role)
            if (type(facts[role]['session_id']) is not int or facts[role]['editable'] is not True
                    or facts[role]['bypassed'] is not False or facts[role]['errors']):
                program._fail('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED', 'native node state/' + role)
        for name in (*program.GATES, 'snippet'):
            parameters[(program.ROLE, name)] = self.call('_fx_planned_observation', nodes[program.ROLE], name)
        for name in ('startframe', 'overwriteattributes', 'usescale', 'timescale'):
            parameters[('solver', name)] = self.call('_fx_planned_observation', nodes['solver'], name)
        for source, output, target, input_index in program.EDGES:
            connections = tuple(islice(iter(nodes[target].inputConnections()), 5))
            matched = [connection for connection in connections if connection.inputIndex() == input_index]
            if len(connections) > 4 or len(matched) != 1:
                program._fail('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED', target)
            connection = matched[0]
            if connection.inputNode() != nodes[source] or connection.outputIndex() != output:
                program._fail('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED', target)
            wires[(target, input_index)] = dict(source_role=source, source_output=output,
                source_path=nodes[source].path(), all_connections=[
                    (item.inputIndex(), item.inputNode().path(), item.outputIndex()) for item in connections])
        if self.binding(roles, pack) != (binding, identity) or self.hou.frame() != frame:
            program._fail('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED', 'host identity or frame changed during observation')
        return dict(binding=binding, identity=copy.deepcopy(identity), frame=frame, nodes=nodes,
                    facts=facts, parameters=parameters, wires=wires, data=data, fps=fps)

    def _same_context(self, before, after):
        return (all(before['nodes'][role] == after['nodes'][role] for role in before['nodes'])
                and all(before[key] == after[key] for key in before if key != 'nodes'))

    def _record(self, context):
        key = context['binding']['task_root']
        record = self.authority['records'].get(key)
        if record is None:
            if any(value is not None for value in context['data'].values()):
                program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'userData cannot authorize a velocity basis')
            return key, None
        if (record['identity'] != context['identity'] or record['binding'] != context['binding']
                or any(record['nodes'][role] != context['nodes'][role] for role in record['nodes'])
                or record['node_sessions'] != {role: fact['session_id'] for role, fact in context['facts'].items()}
                or record['data'] != context['data']):
            program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'current host, nodes or registered userData differs')
        return key, record

    def _issue_record(self, key, context, basis):
        if key not in self.authority['records'] and len(self.authority['records']) >= MAX_REGISTERED_ROOTS:
            program._fail('RBD_VELOCITY_AUTHORITY_BUDGET_EXCEEDED', 'registered root budget exceeded')
        self.authority['records'][key] = dict(binding=copy.deepcopy(context['binding']),
            identity=copy.deepcopy(context['identity']), nodes=context['nodes'],
            node_sessions={role: fact['session_id'] for role, fact in context['facts'].items()},
            basis=copy.deepcopy(basis), data=copy.deepcopy(context['data']))

    def _checkpoint_context(self, roles, pack, context):
        return _checkpoint_json(dict(schema=CHECKPOINT_SCHEMA, roles=roles,
            pack_sha256=program._digest(pack), binding=context['binding'], identity=context['identity'],
            native_version=self.hou.applicationVersionString(), frame=context['frame'], fps=context['fps'],
            nodes={role: {name: value for name, value in fact.items() if name != 'session_id'}
                   for role, fact in context['facts'].items()},
            parameters=[dict(role=role, parm=name, observation=observation)
                        for (role, name), observation in sorted(context['parameters'].items())],
            wires=[dict(role=role, input_index=index, observation=observation)
                   for (role, index), observation in sorted(context['wires'].items())], data=context['data']))

    @_serialized
    def checkpoint(self, roles, pack):
        context = self._capture(roles, pack)
        _, record = self._record(context)
        if record is None or any(type(raw) is not str for raw in context['data'].values()):
            program._fail('RBD_REOPEN_CHECKPOINT_REQUIRED', 'registered velocity program required')
        observations = self.observations({'velocity_variance': 0.}, roles, pack)
        program.velocity_control_readback(self.hou.applicationVersionString(), observations)
        if record['basis'] != observations[(program.ROLE, '@basis')]:
            program._fail('RBD_CHECKPOINT_CHANGED', 'registered baseline changed')
        for current in (self._capture(roles, pack), self._capture(roles, pack)):
            if not self._same_context(context, current):
                program._fail('RBD_CHECKPOINT_CHANGED', 'native checkpoint facts changed')
        return self._checkpoint_context(roles, pack, context)

    def _reopen_authorized(self, roles, pack, checkpoint):
        callback = self.h.get('_fx_rbd_reopen_authority')
        if not callable(callback) or callback(copy.deepcopy(roles), copy.deepcopy(pack),
                                              copy.deepcopy(checkpoint)) is not True:
            program._fail('RBD_REOPEN_AUTHORITY_REQUIRED', 'verified saved scene scope required')

    @_serialized
    def reopen(self, roles, pack, checkpoint):
        value = _checkpoint_json(checkpoint)
        context = self._capture(roles, pack)
        current = self._checkpoint_context(roles, pack, context)
        if (type(value) is not dict or set(value) != set(current) or value['schema'] != CHECKPOINT_SCHEMA
                or any(value[name] != current[name] for name in current if name != 'identity')):
            program._fail('RBD_CHECKPOINT_INVALID', 'saved checkpoint differs from current native facts')
        previous_identity = value['identity']
        if (type(previous_identity) is not dict or previous_identity.get('task_id') != context['binding']['task_id']
                or previous_identity.get('version') != current['native_version']
                or previous_identity.get('plugin_build') != context['identity'].get('plugin_build')
                or type(previous_identity.get('pid')) is not int or previous_identity['pid'] <= 0
                or type(previous_identity.get('scene_epoch')) is not int or previous_identity['scene_epoch'] < 0
                or any(type(previous_identity.get(name)) is not str or not previous_identity[name]
                       for name in ('launch_nonce', 'session_id', 'process_generation'))):
            program._fail('RBD_CHECKPOINT_INVALID', 'complete saved host identity required')
        self._reopen_authorized(roles, pack, value)
        key = context['binding']['task_root']
        if any(transaction['key'] == key for transaction in self.authority['transactions'].values()):
            program._fail('RBD_TRANSACTION_ACTIVE', 'reopen already owns this root')
        if len(self.authority['transactions']) >= MAX_REGISTERED_ROOTS:
            program._fail('RBD_CHECKPOINT_BUDGET_EXCEEDED', 'reopen transaction budget exceeded')
        try:
            basis = json.loads(context['data'][BASIS_KEY])
            program._basis(basis, current['native_version'])
        except (TypeError, ValueError, KeyError):
            program._fail('RBD_CHECKPOINT_INVALID', 'saved packed velocity baseline required')
        if basis['identity'] != context['binding']:
            program._fail('RBD_CHECKPOINT_INVALID', 'saved baseline belongs to another task')
        previous = self.authority['records'].get(key)
        self._issue_record(key, context, basis)
        issued = self.authority['records'][key]
        token = secrets.token_hex(32)
        self.authority['transactions'][token] = dict(key=key, previous=previous, issued=issued,
            roles=copy.deepcopy(roles), pack=copy.deepcopy(pack), checkpoint=value)
        try:
            restored = self.checkpoint(roles, pack)
            if any(restored[name] != current[name] for name in current):
                program._fail('RBD_CHECKPOINT_CHANGED', 'native facts changed during registration')
            self._reopen_authorized(roles, pack, value)
            if not self._same_context(context, self._capture(roles, pack)):
                program._fail('RBD_CHECKPOINT_CHANGED', 'final reopen context changed')
        except Exception:
            self.end(token, commit=False)
            raise
        return token

    @_serialized
    def end(self, token, commit):
        if type(token) is not str or type(commit) is not bool:
            program._fail('RBD_TRANSACTION_REQUIRED', 'current private transaction required')
        transaction = self.authority['transactions'].get(token)
        if transaction is None:
            program._fail('RBD_TRANSACTION_REQUIRED', 'current private transaction required')
        key, issued = transaction['key'], transaction['issued']
        if self.authority['records'].get(key) is not issued:
            program._fail('RBD_CHECKPOINT_CHANGED', 'registration changed before transaction completion')
        if commit:
            expected = transaction['checkpoint']
            actual = self.checkpoint(transaction['roles'], transaction['pack'])
            if any(actual[name] != expected[name] for name in actual if name != 'identity'):
                program._fail('RBD_CHECKPOINT_CHANGED', 'saved facts changed before transaction completion')
            self._reopen_authorized(transaction['roles'], transaction['pack'], expected)
            for current in (self.checkpoint(transaction['roles'], transaction['pack']),
                            self.checkpoint(transaction['roles'], transaction['pack'])):
                if current != actual:
                    program._fail('RBD_CHECKPOINT_CHANGED', 'final committed facts changed')
            self._reopen_authorized(transaction['roles'], transaction['pack'], expected)
        else:
            if transaction['previous'] is None:
                self.authority['records'].pop(key)
            else:
                self.authority['records'][key] = transaction['previous']
        self.authority['transactions'].pop(token)

    def call(self, name, *args, **kwargs):
        return self.h[name](*args, **kwargs)

    def _identity(self, task_id):
        callback = self.h.get('_fx_owned_domain_host_identity')
        return callback(task_id) if callable(callback) else self.call('_host_identity')

    def binding(self, roles, pack):
        root = self.call('_fx_planned_owned_root', roles, pack)
        lease = self.call('_root_lease_check', root, scope='sop', renew=False)
        identity = self._identity(lease['task_id'])
        if identity.get('task_id') != lease['task_id'] or identity.get('version') != self.hou.applicationVersionString():
            program._fail('RBD_ACTUAL_OWNED_PROGRAM_NODE_REQUIRED', 'lease and host identity differ')
        return dict(task_id=lease['task_id'], task_root=root), identity

    @_serialized
    def initialize(self, params, roles, pack, fresh_roles):
        if program.ROLE not in roles:
            return dict(status='blocked', code='RBD_VELOCITY_CARRIER_REQUIRED')
        node = self.hou.node(roles[program.ROLE])
        raw = node.userData(PROGRAM_KEY)
        try:
            self.binding(roles, pack)
        except core.NativeFlipRbdDomainError as error:
            if raw is not None or node.userData(BASIS_KEY) is not None:
                raise
            return dict(status='blocked', code=error.code,
                        evidence_scope='unregistered_passthrough_carrier', detail=str(error))
        if raw is not None or node.userData(BASIS_KEY) is not None:
            self._record(self._capture(roles, pack))
        writes = [dict(role=program.ROLE, parm=name, native_type=kind, value=value)
                  for name, (kind, value) in program.GATES.items()]
        if not raw:
            writes.append(dict(role=program.ROLE, parm='snippet', native_type='string', value=''))
        if 'configure' in fresh_roles:
            writes.append(dict(role='configure', parm='createpackedfragments', native_type='toggle', value=0))
        result = self.call('_fx_apply_fresh_domain_plan', writes, roles, fresh_roles)
        return dict(parameters=result, basis_registration='deferred_until_atomic_control_write',
                    evidence_scope='passthrough_carrier_initialization')

    def _pending_basis(self, writes):
        for write in writes:
            if write.get('value_kind') == 'trusted_rbd_velocity_program':
                for guard in write.get('frozen_readback_guards', ()):
                    if (guard['role'], guard['parm']) == (program.ROLE, '@basis'):
                        return copy.deepcopy(guard['value'])
        return None

    @_serialized
    def observations(self, changes, roles, pack, writes=(), *, task_seed=None):
        if 'velocity_variance' not in changes and not any(write.get('role') == program.ROLE for write in writes):
            return {}
        if 'activation_frame' in changes:
            program._fail('RBD_INITIAL_VELOCITY_ACTIVATION_COMBINATION_UNSUPPORTED',
                          'initial velocity requires the unchanged actual active baseline')
        context = self._capture(roles, pack)
        key, record = self._record(context)
        seed_reader = self.h.get('_fx_rbd_task_seed')
        if callable(seed_reader):
            trusted_seed = seed_reader(roles, pack)
            if (type(trusted_seed) is not int or not 0 <= trusted_seed < 2 ** 31
                    or (task_seed is not None and (type(task_seed) is not int or task_seed != trusted_seed))):
                program._fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'owned manifest task seed required')
            task_seed = trusted_seed
        binding, identity = context['binding'], context['identity']
        version = self.hou.applicationVersionString()
        carrier = self.hou.node(roles.get(program.ROLE, ''))
        if carrier is None:
            program._fail('RBD_VELOCITY_CARRIER_REQUIRED', 'owned detail wrangle missing')
        pending = self._pending_basis(writes)
        raw = context['data'][BASIS_KEY]
        basis = copy.deepcopy(record['basis']) if record else pending
        if pending is not None and (record is None or pending != record['basis']):
            program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'pending plan has no current issuing authority')
        solver = self.hou.node(roles['solver'])
        start = self.call('_fx_planned_observation', solver, 'startframe')
        if start.get('type') != 'integer' or start.get('driven') is not False or not core._typed_value(start.get('value'), 'integer', 1):
            program._fail('RBD_ACTIVATION_EVENT_CARRIER_REQUIRED', 'actual undriven integer solver start frame')
        frame = int(start['value'])
        upstream = program.collect_packed_geometry(self.hou.node(roles['configure']), frame, self.hou)
        if basis is None:
            snippet = self.call('_fx_planned_observation', carrier, 'snippet')
            if snippet.get('value') != '' or carrier.userData(PROGRAM_KEY):
                program._fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'only unregistered passthrough can acquire a baseline')
            seed = secrets.randbelow(2 ** 31) if task_seed is None else task_seed
            basis = program.velocity_basis(version, binding, upstream, seed, frame)
        if basis.get('identity') != binding or (task_seed is not None and task_seed != basis.get('task_seed')):
            program._fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'saved task binding or seed changed')
        result = {(program.ROLE, '@basis'): basis, ('configure', '@packed_geometry/0'): upstream,
                  ('solver', '@time'): dict(origin='runtime_hom', fps=context['fps'])}
        for role in ('configure', program.ROLE, 'solver'):
            node = self.hou.node(roles[role])
            result[(role, '@node')] = dict(origin='runtime_hom', native_version=version, **binding,
                node_path=node.path(), category=node.type().category().name().lower(), type=node.type().name(),
                editable=node.isEditable(), host_identity=copy.deepcopy(identity))
        for source, output, target, input_index in program.EDGES:
            observed_connections = tuple(islice(iter(self.hou.node(roles[target]).inputConnections()), 5))
            if len(observed_connections) > 4:
                program._fail('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED', 'bounded native input connections')
            connections = [connection for connection in observed_connections if connection.inputIndex() == input_index]
            if len(connections) != 1:
                program._fail('RBD_ACTUAL_VELOCITY_CONSUMER_CONNECTION_REQUIRED', target)
            connection = connections[0]
            actual_path = connection.inputNode().path()
            result[(target, '@input/' + str(input_index))] = dict(origin='runtime_hom',
                source_role=source if actual_path == roles[source] else 'foreign',
                source_output=connection.outputIndex(), source_path=actual_path)
        for name in (*program.GATES, 'snippet'):
            result[(program.ROLE, name)] = self.call('_fx_planned_observation', carrier, name)
        for name in ('startframe', 'overwriteattributes', 'usescale', 'timescale'):
            result[('solver', name)] = self.call('_fx_planned_observation', solver, name)
        program._context(version, result)
        registration = context['data'][PROGRAM_KEY]
        if registration:
            result[(program.ROLE, '@program')] = dict(origin='runtime_hom', **json.loads(registration))
        else:
            result[(program.ROLE, '@program')] = dict(origin='runtime_hom', registration=None)
        result[(program.ROLE, '@packed_geometry/0')] = program.collect_packed_geometry(carrier, frame, self.hou)
        result[('solver', '@input_geometry/0')] = program.collect_packed_geometry(solver, frame, self.hou, input_index=0)
        for role, field, input_index in (('solver', '@input_geometry/0', 0),
                                         (program.ROLE, '@packed_geometry/0', None),
                                         ('configure', '@packed_geometry/0', None)):
            current_geometry = program.collect_packed_geometry(context['nodes'][role], frame, self.hou,
                                                              input_index=input_index)
            if current_geometry != result[(role, field)]:
                program._fail('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED', 'native geometry changed after downstream reads')
        for current in (self._capture(roles, pack), self._capture(roles, pack)):
            if not self._same_context(context, current):
                program._fail('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED', 'native state changed after lazy geometry reads')
        if self.binding(roles, pack) != (binding, identity) or self.hou.frame() != context['frame']:
            program._fail('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED', 'final authenticated context differs')
        if callable(seed_reader):
            final_seed = seed_reader(roles, pack)
            if type(final_seed) is not int or final_seed != task_seed:
                program._fail('RBD_FROZEN_VELOCITY_BASIS_REQUIRED', 'owned task seed changed during native reads')
        if record is None:
            self._issue_record(key, context, basis)
        return result

    @_serialized
    def prepare(self, item):
        item['rbd_velocity_snapshot'] = {name: item['node'].userData(name) for name in (BASIS_KEY, PROGRAM_KEY)}
        item['rbd_velocity_authority_snapshot'] = [
            (key, self._copy_record(record)) for key, record in self.authority['records'].items()
            if record['nodes'][program.ROLE] == item['node']]
        snapshots = item['rbd_velocity_authority_snapshot']
        if snapshots:
            binding = snapshots[0][1]['binding']
        else:
            root = self.call('_root_for_path', item['node'].path())
            if root is None:
                program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'leased restoration root required')
            lease = self.call('_root_lease_check', root, scope='sop', renew=False)
            binding = dict(task_root=root, task_id=lease['task_id'])
        item['rbd_velocity_restore_context'] = dict(binding=copy.deepcopy(binding),
            identity=copy.deepcopy(self._identity(binding['task_id'])), node_path=item['node'].path(),
            node_session_id=item['node'].sessionId(), parameter_path=item['parm'].path())
        self._authorize_restore(item)

    def _authorize_restore(self, item):
        context = item.get('rbd_velocity_restore_context')
        if not isinstance(context, dict):
            program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'private restoration context required')
        binding = context['binding']
        lease = self.call('_root_lease_check', binding['task_root'], scope='sop', renew=False)
        if (lease.get('task_id') != binding['task_id'] or self._identity(binding['task_id']) != context['identity']
                or not context['node_path'].startswith(binding['task_root'] + '/')
                or self.hou.node(context['node_path']) != item['node']
                or item['node'].sessionId() != context['node_session_id']
                or item['parm'].path() != context['parameter_path']):
            program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'current restoration lease, identity or node differs')

    @_serialized
    def restore_parameters(self, item):
        self._authorize_restore(item)
        self.call('_restore_parm_snapshot', item['parm'], item['snapshot'])
        self.restore(item)

    @_serialized
    def restore(self, item):
        self._authorize_restore(item)
        snapshots = item.get('rbd_velocity_authority_snapshot', [])
        for key, record in snapshots:
            if (record['identity'] != self._identity(record['binding']['task_id'])
                    or any(self.hou.node(node.path()) != node
                           or node.sessionId() != record['node_sessions'][role]
                           for role, node in record['nodes'].items())):
                program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'rollback cannot modify a different host or node')
        for name, value in item['rbd_velocity_snapshot'].items():
            if value is None:
                item['node'].destroyUserData(name)
            else:
                item['node'].setUserData(name, value)
            if item['node'].userData(name) != value:
                program._fail('PARAMETER_RESTORE_MISMATCH', 'RBD basis/program restoration differs')
        for key, record in snapshots:
            self.authority['records'][key] = self._copy_record(record)

    @_serialized
    def write(self, item, roles, pack):
        root = self.call('_fx_planned_owned_root', roles, pack)
        if any(transaction['key'] == root for transaction in self.authority['transactions'].values()):
            program._fail('RBD_TRANSACTION_ACTIVE', 'candidate cannot replace a pending reopen')
        write = item['native_write']
        changes = {'velocity_variance': write['public_value']}
        observations = self.observations(changes, roles, pack, [write])
        core.validate_control_write_plan([write], observations)
        node = item['node']
        if (item.get('rbd_velocity_snapshot') != {name: node.userData(name) for name in (BASIS_KEY, PROGRAM_KEY)} or
                node.path() != roles[program.ROLE] or item['parm'].path() != node.path() + '/snippet'):
            program._fail('RBD_NATIVE_TRANSACTION_CONTEXT_CHANGED', 'prepared carrier or userData differs')
        basis = observations[(program.ROLE, '@basis')]
        context = self._capture(roles, pack)
        key, record = self._record(context)
        if record is None or record['basis'] != basis:
            program._fail('RBD_VELOCITY_AUTHORITY_REQUIRED', 'native write requires its current issuing authority')
        record['data'] = {BASIS_KEY: json.dumps(basis, sort_keys=True),
                          PROGRAM_KEY: json.dumps(write['registration'], sort_keys=True)}
        node.setUserData(BASIS_KEY, record['data'][BASIS_KEY])
        actual = self.call('_set_parm_verified', item['parm'], write['value'])
        node.setUserData(PROGRAM_KEY, record['data'][PROGRAM_KEY])
        observations = self.observations(changes, roles, pack, [write])
        core.validate_applied_readback([write], observations)
        readback = program.validate_velocity_readback([write], observations)[0]
        return dict(parameter='snippet', parameter_path=item['parm'].path(), after=readback['value'],
                    readback_verified=True, native_parameter_readback=actual, native_velocity_readback=readback,
                    actual_consumer_geometry=observations[('solver', '@input_geometry/0')])

    @_serialized
    def inspect_controls(self, roles, pack):
        context = self._capture(roles, pack)
        if context['data'][PROGRAM_KEY] is not None or context['data'][BASIS_KEY] is not None:
            return self.readback(roles, pack, {'velocity_variance': 0.})
        observations = self.observations({'velocity_variance': 0.}, roles, pack)
        if observations[(program.ROLE, 'snippet')]['value'] != '':
            program._fail('RBD_ACTUAL_VELOCITY_PROGRAM_REGISTRATION_REQUIRED', 'unregistered carrier is not passthrough')
        basis, _ = program._context(self.hou.applicationVersionString(), observations)
        for field in ((program.ROLE, '@packed_geometry/0'), ('solver', '@input_geometry/0')):
            actual = observations[field]
            if (actual['geometry'] != basis['geometry']['geometry']
                    or actual['node_path'] != roles[program.ROLE]
                    or actual['frame'] != basis['initialization_frame']
                    or actual['native_version'] != basis['native_version']):
                program._fail('RBD_ACTUAL_VELOCITY_CONSUMPTION_MISMATCH', 'unregistered passthrough differs')
        return dict(controls={'velocity_variance': 0.}, evidence_scope='packed_initial_velocity_passthrough',
                    native_simulation='NOT_RUN', actual_consumer_geometry=observations[('solver', '@input_geometry/0')])

    def readback(self, roles, pack, normalized):
        if 'velocity_variance' not in normalized:
            return {}
        observations = self.observations({'velocity_variance': normalized['velocity_variance']}, roles, pack)
        value = program.velocity_control_readback(self.hou.applicationVersionString(), observations)
        return dict(controls={'velocity_variance': value},
                    evidence_scope='packed_initial_velocity_carrier', native_simulation='NOT_RUN',
                    actual_consumer_geometry=observations[('solver', '@input_geometry/0')])
