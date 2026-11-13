"""P01 native channel transactions; simulation consumption remains unproven."""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
import hashlib
import json
import math
import secrets
import threading
from contextlib import contextmanager

from . import native_particle_ocean_geometry_domains as core
from . import native_particle_emission_program as program

CONTEXT = ('emission', '@emission_context')
KIND = 'trusted_particle_emission_expression'
CHECKPOINT_SCHEMA = 'bridge.particle-emission-checkpoint/1'
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
MAX_CHECKPOINT_VALUES = 131072
MAX_REOPEN_TRANSACTIONS = 128


def _fail(code, detail):
    raise program.ParticleEmissionError(code, detail)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')).hexdigest()


def _checkpoint_json(value):
    remaining = MAX_CHECKPOINT_VALUES

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            _fail('PARTICLE_EMISSION_CHECKPOINT_BUDGET_EXCEEDED', 'bounded checkpoint structure required')
        if type(item) is dict:
            for name, child in item.items():
                if type(name) is not str:
                    _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'string checkpoint keys required')
                visit(name, depth + 1)
                visit(child, depth + 1)
        elif type(item) in (list, tuple):
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            if len(item) > MAX_CHECKPOINT_BYTES:
                _fail('PARTICLE_EMISSION_CHECKPOINT_BUDGET_EXCEEDED', 'bounded checkpoint string required')
        elif type(item) is int:
            if item.bit_length() > 4096:
                _fail('PARTICLE_EMISSION_CHECKPOINT_BUDGET_EXCEEDED', 'bounded checkpoint integer required')
        elif item is not None and type(item) not in (bool, float):
            _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'JSON checkpoint required')

    visit(value, 0)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        raw = encoded.encode('utf-8')
    except (ValueError, OverflowError, UnicodeError):
        _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'finite UTF-8 checkpoint facts required')
    if len(raw) > MAX_CHECKPOINT_BYTES:
        _fail('PARTICLE_EMISSION_CHECKPOINT_BUDGET_EXCEEDED', 'complete checkpoint exceeds receipt budget')
    return json.loads(encoded)


def routed_write(percentage, observations, birth_rate_override=None):
    context = copy.deepcopy(observations.get(CONTEXT))
    if not isinstance(context, dict):
        _fail('PARTICLE_EMISSION_AUTHORITY_REQUIRED', 'current registered native context required')
    basis = program.validate_basis(context['basis'])
    rate = context['birth_rate'] if birth_rate_override is None else birth_rate_override
    limits = context.get('limits', {})
    program.validate_rate_range(basis, percentage, rate,
        native_minimum=limits.get('minimum'), native_maximum=limits.get('maximum'))
    source = program.expression(basis, percentage, birth_rate_override=rate)
    return core._write('emission', 'constantrate', source, 'float', value_kind=KIND,
        public_control='emission_variance', domain_id=core.PARTICLES,
        native_version=basis['native_version'], percentage=float(percentage), birth_rate=float(rate),
        emission_before=context, required_gates=copy.deepcopy(core._BIRTH_GATES))


def validate_write(write, observations, *, after_mutation=False):
    before = write.get('emission_before')
    if not isinstance(before, dict) or write != routed_write(write.get('percentage'),
            {CONTEXT: before}, write.get('birth_rate')):
        _fail('PARTICLE_EMISSION_PLAN_CHANGED', 'routed expression or frozen context differs')
    current = observations.get(CONTEXT)
    if not isinstance(current, dict):
        _fail('PARTICLE_EMISSION_AUTHORITY_REQUIRED', 'native observation required')
    if not after_mutation:
        if current != before:
            _fail('PARTICLE_EMISSION_CONTEXT_CHANGED', 'native context changed before write')
        return
    mutable = {'percentage', 'birth_rate', 'expression', 'channel', 'actual_rate'}
    if ({key: value for key, value in current.items() if key not in mutable}
            != {key: value for key, value in before.items() if key not in mutable}
            or current['percentage'] != write['percentage'] or current['birth_rate'] != write['birth_rate']
            or current['expression'] != (None if write['percentage'] == 0 else write['value'])):
        _fail('PARTICLE_EMISSION_READBACK_MISMATCH', 'native expression, baseline or immutable context differs')


class Host:
    def __init__(self, host, *, hou_module=None):
        if hou_module is None:
            import hou as hou_module
        self.host = host
        self.hou = hou_module
        self.authority = host.setdefault('_BRIDGE_PARTICLE_EMISSION_AUTHORITY',
            {'lock': threading.RLock(), 'records': {}, 'snapshots': {}})
        self.authority.setdefault('builds', {})
        self.authority.setdefault('reopens', {})

    def call(self, name, *args, **kwargs):
        callback = self.host.get(name)
        if not callable(callback):
            _fail('PARTICLE_EMISSION_HOST_HOOK_REQUIRED', name)
        return callback(*args, **kwargs)

    def _binding(self, roles, pack):
        if pack.get('native_domain_id') != core.PARTICLES:
            _fail('PARTICLE_EMISSION_DOMAIN_REQUIRED', 'particles only')
        root = self.call('_fx_planned_owned_root', roles, pack)
        lease = self.call('_root_lease_check', root, scope='sop', renew=False)
        identity = (self.call('_fx_geometry_host_identity', lease['task_id'])
                    if callable(self.host.get('_fx_geometry_host_identity')) else self.call('_host_identity'))
        version = self.hou.applicationVersionString()
        if (version not in (*core.VERSIONS, *PREPARATION_VERSIONS) or identity.get('version') != version
                or identity.get('task_id') != lease.get('task_id') or not lease.get('task_id')
                or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or not isinstance(identity.get('launch_nonce'), str) or not identity['launch_nonce']
                or any(not isinstance(identity.get(field), str) or not identity[field]
                       for field in ('plugin_build', 'session_id', 'process_generation'))
                or type(identity.get('scene_epoch')) is not int or identity['scene_epoch'] < 0):
            _fail('PARTICLE_EMISSION_AUTHENTICATED_HOST_REQUIRED', 'current root lease and full host identity required')
        nodes = {}
        for role, native_type, category in (('emission', 'popsource::2.0', 'dop'),
                ('simulation', 'dopnet', 'sop'), ('solver', 'popsolver::2.0', 'dop')):
            node = self.hou.node(roles.get(role, ''))
            if (node is None or node.path() != roles[role] or not node.path().startswith(root + '/')
                    or node.type().name() != native_type or node.type().category().name().lower() != category):
                _fail('PARTICLE_EMISSION_OWNED_NODE_REQUIRED', role)
            nodes[role] = {'path': node.path(), 'session_id': node.sessionId(), 'type': native_type}
        if any(self.hou.node(roles[role]).parent().path() != roles['simulation'] for role in ('emission', 'solver')):
            _fail('PARTICLE_EMISSION_OWNED_NODE_REQUIRED', 'emission must belong to actual simulation')
        return {'task_id': lease['task_id'], 'task_root': root, 'native_version': version,
                'identity': copy.deepcopy(identity), 'nodes': nodes, 'pack_sha256': _sha(pack)}

    def _snapshot_identity(self, snapshot):
        def convert(value, field=None):
            if field == 'component':
                return value.path()
            if field == 'keyframes':
                return [self.call('_keyframe_identity', keyframe) for keyframe in value]
            if field == 'extrapolation':
                return [str(item) for item in value]
            if isinstance(value, dict):
                return {key: convert(item, key) for key, item in value.items()
                        if key != 'evaluated' and not (key == 'value' and value.get('expression'))}
            if isinstance(value, (list, tuple)):
                return [convert(item) for item in value]
            return value
        return convert(snapshot)

    def _parameter(self, roles):
        parameter = self.call('_resolve_parm_target', self.hou.node(roles['emission']), ['constantrate'])
        if parameter is None or len(parameter._components()) != 1:
            _fail('PARTICLE_EMISSION_PARAMETER_REQUIRED', 'actual scalar constantrate')
        return parameter

    def _channel(self, parameter):
        return self._snapshot_identity(self.call('_snapshot_parm_state', parameter, capture_extrapolation=True))

    def _limits(self, parameter):
        template = parameter.parmTemplate()
        result = {'minimum': None, 'maximum': None}
        for key, strict, getter in (('minimum', 'minIsStrict', 'minValue'),
                                   ('maximum', 'maxIsStrict', 'maxValue')):
            if not callable(getattr(template, strict, None)) or not callable(getattr(template, getter, None)):
                continue
            flag = getattr(template, strict)()
            if type(flag) is not bool:
                _fail('PARTICLE_EMISSION_NATIVE_LIMITS_REQUIRED', 'actual strict-bound flag must be boolean')
            if flag:
                value = getattr(template, getter)()
                if not core._typed_value(value, 'float', 1):
                    _fail('PARTICLE_EMISSION_NATIVE_LIMITS_REQUIRED', 'actual finite strict bound required')
                result[key] = float(value)
        return result

    def _clock_fields(self, node):
        required = {'Offset Time', 'Scale Time'}
        found = {}
        pending = [iter(node.parmTemplateGroup().entries())]
        count = 0
        while pending:
            template = next(pending[-1], None)
            if template is None:
                pending.pop()
                continue
            count += 1
            if count > 4096 or len(pending) > 32:
                _fail('PARTICLE_EMISSION_CLOCK_INTERFACE_REQUIRED', 'bounded actual parameter template group required')
            label = template.label()
            if label in required:
                if label in found or not isinstance(template.name(), str) or not template.name():
                    _fail('PARTICLE_EMISSION_CLOCK_INTERFACE_REQUIRED', 'ambiguous actual clock template')
                found[label] = template.name()
            children = getattr(template, 'parmTemplates', None)
            if callable(children):
                pending.append(iter(children()))
        if set(found) != required:
            _fail('PARTICLE_EMISSION_CLOCK_INTERFACE_REQUIRED', 'actual Offset Time and Scale Time templates unavailable')
        return found

    def _native(self, roles):
        facts = {}
        for role, name, target in core._BIRTH_GATES:
            fact = self.call('_fx_planned_observation', self.hou.node(roles[role]), name)
            kind, size = core._gate_spec(role, name)
            core._runtime({(role, name): fact}, role, name, kind, size)
            if not core._gate_matches(fact, target) or any(fact.get(flag) is not False for flag in ('locked', 'hidden', 'disabled')):
                _fail('PARTICLE_EMISSION_GATE_CHANGED', role + '/' + name)
            facts[role + '/' + name] = fact
        simulation = self.hou.node(roles['simulation'])
        clock_fields = self._clock_fields(simulation)
        for label, name in clock_fields.items():
            fact = self.call('_fx_planned_observation', simulation, name)
            if (fact.get('type') != 'float' or fact.get('size') != 1
                    or not core._typed_value(fact.get('value'), 'float', 1)
                    or type(fact.get('driven')) is not bool
                    or label == 'Scale Time' and fact['driven']):
                _fail('PARTICLE_EMISSION_CLOCK_REQUIRED', 'actual scalar clock interface required')
            if any(fact.get(flag) is not False for flag in ('locked', 'hidden', 'disabled')):
                _fail('PARTICLE_EMISSION_CLOCK_REQUIRED', name)
            parameter = self.call('_resolve_parm_target', simulation, [name])
            facts['simulation/' + label] = {'name': name, 'fact': fact, 'channel': self._channel(parameter)}
        if facts['simulation/Scale Time']['fact']['value'] != 1:
            _fail('PARTICLE_EMISSION_CLOCK_REQUIRED', 'non-unit DOP time scale is not captured')
        solver = self.hou.node(roles['solver'])
        scale = self.call('_fx_planned_observation', solver, 'timescale')
        core._runtime({('solver', 'timescale'): scale}, 'solver', 'timescale', 'float')
        if scale['value'] != 1 or any(scale.get(flag) is not False for flag in ('locked', 'hidden', 'disabled')):
            _fail('PARTICLE_EMISSION_CLOCK_REQUIRED', 'actual solver time scale must remain one')
        facts['solver/timescale'] = scale
        for name, kind in (('probemit', 'toggle'), ('seed', 'float'), ('jitterbirthtime', 'ordinal')):
            fact = self.call('_fx_planned_observation', self.hou.node(roles['emission']), name)
            core._runtime({('emission', name): fact}, 'emission', name, kind)
            if any(fact.get(flag) is not False for flag in ('locked', 'hidden', 'disabled')):
                _fail('PARTICLE_EMISSION_GATE_CHANGED', name)
            facts['emission/' + name] = fact
        fps = self.hou.fps()
        frame, time = self.hou.frame(), self.hou.time()
        start = facts['simulation/Offset Time']['fact']['value']
        if (type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 10000
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in (frame, time, start))
                or not math.isclose(time, self.hou.frameToTime(frame), rel_tol=0, abs_tol=1e-9)):
            _fail('PARTICLE_EMISSION_CLOCK_REQUIRED', 'actual consistent scene clock required')
        return _checkpoint_json({'gates': facts, 'fps': float(fps), 'frame': float(frame),
                                 'time': float(time), 'birth_start_time': float(start)})

    @contextmanager
    def build_transaction(self, root):
        with self.authority['lock']:
            self._reject_reopen(root)
            if root in self.authority['builds']:
                _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'nested build is unavailable')
            previous = self.authority['records'].get(root)
            if previous is not None and any(
                    self.hou.node(fact['path']) is None
                    or self.hou.node(fact['path']).sessionId() != fact['session_id']
                    for fact in previous['binding']['nodes'].values()):
                if any(snapshot['root'] == root for snapshot in self.authority['snapshots'].values()):
                    _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'old native session still has a pending transaction')
                if self.authority['records'].get(root) is previous:
                    self.authority['records'].pop(root)
                previous = None
            scope = {'issued': None}
            self.authority['builds'][root] = scope
            try:
                yield
                if scope['issued'] is not None:
                    if self.authority['records'].get(root) is not scope['issued']:
                        _fail('PARTICLE_EMISSION_TRANSACTION_CHANGED', 'build registration was replaced')
                    self.observations(scope['roles'], scope['pack'])
            except Exception:
                if scope['issued'] is not None and self.authority['records'].get(root) is scope['issued']:
                    if previous is None:
                        self.authority['records'].pop(root)
                    else:
                        self.authority['records'][root] = previous
                raise
            finally:
                self.authority['builds'].pop(root, None)

    def invalidate_scene(self):
        with self.authority['lock']:
            self.authority['records'].clear()
            self.authority['snapshots'].clear()
            self.authority['reopens'].clear()

    def initialize(self, params, roles, pack, fresh_roles):
        supplied = self.call('_fx_configuration', params).get('particle_emission_basis')
        if supplied is None:
            return {'status': 'BLOCKED', 'code': 'PARTICLE_EMISSION_EXPLICIT_SEED_REQUIRED'}
        with self.authority['lock']:
            binding = self._binding(roles, pack)
            self._reject_reopen(binding['task_root'])
            if binding['task_root'] in self.authority['records']:
                current = self.observations(roles, pack)[CONTEXT]
                if supplied != {'task_seed': current['basis']['task_seed']}:
                    _fail('PARTICLE_EMISSION_BASIS_CHANGED', 'registered task seed is immutable')
                return copy.deepcopy(current['basis'])
            if not isinstance(supplied, dict) or set(supplied) != {'task_seed'} or 'emission' not in fresh_roles:
                _fail('PARTICLE_EMISSION_FRESH_INITIALIZATION_REQUIRED', 'explicit task seed and fresh owned emission required')
            native = self._native(roles)
            parameter = self._parameter(roles)
            rate = self.call('_fx_planned_observation', self.hou.node(roles['emission']), 'constantrate')
            core._runtime({('emission', 'constantrate'): rate}, 'emission', 'constantrate', 'float')
            if any(rate.get(flag) is not False for flag in ('locked', 'disabled', 'hidden')):
                _fail('PARTICLE_EMISSION_PARAMETER_REQUIRED', 'editable undriven baseline required')
            basis = program.freeze_basis(binding['native_version'], task_id=binding['task_id'],
                task_root=binding['task_root'], node_path=roles['emission'], birth_rate=rate['value'],
                task_seed=supplied['task_seed'], birth_start_time=native['birth_start_time'], fps=native['fps'])
            channel = self._channel(parameter)
            limits = self._limits(parameter)
            program.validate_rate_range(basis, 0., native_minimum=limits['minimum'], native_maximum=limits['maximum'])
            record = {'binding': binding, 'basis': basis, 'limits': limits,
                'native': {key: value for key, value in native.items() if key not in ('frame', 'time')},
                'percentage': 0., 'birth_rate': float(rate['value']), 'expression': None, 'channel': channel}
            self.authority['records'][binding['task_root']] = record
            build = self.authority['builds'].get(binding['task_root'])
            if build is not None:
                build.update(issued=record, roles=copy.deepcopy(roles), pack=copy.deepcopy(pack))
            try:
                self.observations(roles, pack)
            except Exception:
                if self.authority['records'].get(binding['task_root']) is record:
                    self.authority['records'].pop(binding['task_root'])
                raise
            return copy.deepcopy(basis)

    def registered(self, roles, pack):
        return roles.get('emission') is not None and any(record['binding']['nodes']['emission']['path'] == roles['emission']
                                                       for record in self.authority['records'].values())

    def observations(self, roles, pack):
        with self.authority['lock']:
            binding = self._binding(roles, pack)
            record = self.authority['records'].get(binding['task_root'])
            if record is None or record['binding'] != binding:
                _fail('PARTICLE_EMISSION_AUTHORITY_REQUIRED', 'current private node/session/identity registration required')
            native = self._native(roles)
            if {key: value for key, value in native.items() if key not in ('frame', 'time')} != record['native']:
                _fail('PARTICLE_EMISSION_CONTEXT_CHANGED', 'native gates, FPS or birth origin changed')
            parameter = self._parameter(roles)
            if self._limits(parameter) != record['limits']:
                _fail('PARTICLE_EMISSION_CONTEXT_CHANGED', 'actual strict rate bounds changed')
            fact = self.call('_fx_planned_observation', self.hou.node(roles['emission']), 'constantrate')
            if (fact.get('type') != 'float' or fact.get('size') != 1
                    or fact.get('origin') != 'runtime_hom' or type(fact.get('driven')) is not bool
                    or any(fact.get(flag) is not False for flag in ('locked', 'disabled', 'hidden'))
                    or self._channel(parameter) != record['channel']):
                _fail('PARTICLE_EMISSION_CHANNEL_CHANGED', 'actual full channel differs from issued channel')
            if record['expression'] is not None:
                component = parameter._components()[0]
                if (component.expression() != record['expression']
                        or component.expressionLanguage() != self.hou.exprLanguage.Python):
                    _fail('PARTICLE_EMISSION_CHANNEL_CHANGED', 'actual issued expression and language required')
            elif fact['driven']:
                _fail('PARTICLE_EMISSION_CHANNEL_CHANGED', 'zero variation must remain undriven')
            expected = program.rate_at_time(record['basis'], record['percentage'], native['time'],
                                            birth_rate_override=record['birth_rate'])
            if not core._near(fact.get('value'), expected):
                _fail('PARTICLE_EMISSION_READBACK_MISMATCH', 'actual native channel evaluation differs')
            if (native != self._native(roles) or self._channel(parameter) != record['channel']
                    or native != self._native(roles) or self._limits(parameter) != record['limits']
                    or binding != self._binding(roles, pack)):
                _fail('PARTICLE_EMISSION_CONTEXT_CHANGED', 'late identity or native clock/gate drift')
            return {CONTEXT: dict(copy.deepcopy(record), **native, actual_rate=float(fact['value']))}

    def prepare(self, item, roles, pack):
        with self.authority['lock']:
            context = self.observations(roles, pack)
            write = item['native_write']
            validate_write(write, context)
            root = context[CONTEXT]['binding']['task_root']
            self._reject_reopen(root)
            if any(snapshot['root'] == root for snapshot in self.authority['snapshots'].values()):
                _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'one pending transaction per task root')
            token = secrets.token_hex(32)
            parameter = self._parameter(roles)
            snapshot = self.call('_snapshot_parm_state', parameter, capture_extrapolation=True)
            self.authority['snapshots'][token] = {'root': root, 'binding': context[CONTEXT]['binding'],
                'write': copy.deepcopy(write), 'before': self.authority['records'][root],
                'snapshot': snapshot, 'last_channel': self._snapshot_identity(snapshot), 'issued': None}
            item['particle_emission_snapshot'] = token

    def _transaction(self, item, roles, pack):
        snapshot = self.authority['snapshots'].get(item.get('particle_emission_snapshot'))
        if (snapshot is None or snapshot['binding'] != self._binding(roles, pack)
                or item['native_write'] != snapshot['write']):
            _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'private prepared transaction required')
        self._reject_reopen(snapshot['root'])
        if self.authority['records'].get(snapshot['root']) is not (snapshot['issued'] or snapshot['before']):
            _fail('PARTICLE_EMISSION_TRANSACTION_CHANGED', 'private record was replaced')
        return snapshot

    def write(self, item, roles, pack):
        with self.authority['lock']:
            snapshot = self._transaction(item, roles, pack)
            validate_write(snapshot['write'], self.observations(roles, pack))
            write = snapshot['write']
            parameter = self._parameter(roles)
            component = parameter._components()[0]
            try:
                component.deleteAllKeyframes()
                if write['percentage'] == 0:
                    parameter.set(write['birth_rate'], follow_references=False)
                else:
                    component.setExpression(write['value'], language=self.hou.exprLanguage.Python)
                    if (component.expression() != write['value']
                            or component.expressionLanguage() != self.hou.exprLanguage.Python):
                        _fail('PARTICLE_EMISSION_READBACK_MISMATCH', 'native Python expression differs')
            finally:
                snapshot['last_channel'] = self._channel(parameter)
            issued = copy.deepcopy(snapshot['before'])
            issued.update(percentage=write['percentage'], birth_rate=write['birth_rate'],
                expression=None if write['percentage'] == 0 else write['value'], channel=snapshot['last_channel'])
            snapshot['issued'] = issued
            self.authority['records'][snapshot['root']] = issued
            observed = self.observations(roles, pack)
            validate_write(write, observed, after_mutation=True)
            return {'after': observed[CONTEXT]['percentage'], 'readback_verified': True,
                    'evidence_scope': 'native_parameter_expression_only', 'native_program_readback': self.readback(roles, pack)}

    def restore(self, item, roles, pack):
        with self.authority['lock']:
            snapshot = self._transaction(item, roles, pack)
            parameter = self._parameter(roles)
            if self._channel(parameter) != snapshot['last_channel']:
                _fail('PARTICLE_EMISSION_RESTORE_AUTHORITY_REQUIRED', 'foreign channel replacement cannot be overwritten')
            self._transaction(item, roles, pack)
            self.call('_restore_parm_snapshot', parameter, snapshot['snapshot'])
            if self._channel(parameter) != self._snapshot_identity(snapshot['snapshot']):
                _fail('PARTICLE_EMISSION_RESTORE_FAILED', 'complete native channel was not restored')
            self.authority['records'][snapshot['root']] = snapshot['before']
            self.authority['snapshots'].pop(item['particle_emission_snapshot'])

    def release(self, item):
        with self.authority['lock']:
            self.authority['snapshots'].pop(item.get('particle_emission_snapshot'), None)

    def _reject_reopen(self, root):
        if any(transaction['root'] == root for transaction in self.authority['reopens'].values()):
            _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'reopen already owns this task root')

    def _checkpoint_capture(self, roles, pack, record):
        binding = self._binding(roles, pack)
        basis = program.validate_basis(record['basis'], binding['native_version'])
        native = self._native(roles)
        immutable = {key: value for key, value in native.items() if key not in ('frame', 'time')}
        if (any(basis[name] != binding[name] for name in ('task_id', 'task_root', 'native_version'))
                or basis['node_path'] != roles['emission']
                or basis['fps'] != immutable['fps']
                or basis['birth_start_time'] != immutable['birth_start_time']):
            _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'basis must bind the actual task, clock and emission')
        parameter = self._parameter(roles)
        limits = self._limits(parameter)
        program.validate_rate_range(basis, record['percentage'], record['birth_rate'],
            native_minimum=limits['minimum'], native_maximum=limits['maximum'])
        expected_expression = (None if record['percentage'] == 0 else
            program.expression(basis, record['percentage'], record['birth_rate']))
        if record['expression'] != expected_expression:
            _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'saved expression differs from the frozen program')
        nodes = self._checkpoint_nodes(binding)
        targets = {(role, name) for role, name, _ in core._BIRTH_GATES}
        targets.update({('emission', name) for name in ('constantrate', 'probemit', 'seed', 'jitterbirthtime')})
        targets.add(('solver', 'timescale'))
        targets.update(('simulation', fact['name']) for key, fact in immutable['gates'].items()
                       if key.startswith('simulation/'))
        parameters = []
        for role, name in sorted(targets):
            target = self.call('_resolve_parm_target', self.hou.node(roles[role]), [name])
            if target is None:
                _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'actual native checkpoint parameter required')
            parameters.append(dict(role=role, parm=name, channel=self._channel(target)))
        value = _checkpoint_json(dict(schema=CHECKPOINT_SCHEMA, roles=roles,
            pack_sha256=binding['pack_sha256'],
            binding={name: binding[name] for name in ('task_id', 'task_root', 'native_version')},
            identity=binding['identity'], nodes=nodes, basis=basis,
            percentage=record['percentage'], birth_rate=record['birth_rate'],
            expression=record['expression'], channel=self._channel(parameter), limits=limits,
            native=immutable, parameters=parameters))
        if (immutable != {key: value for key, value in self._native(roles).items() if key not in ('frame', 'time')}
                or self._channel(parameter) != value['channel']
                or immutable != {key: value for key, value in self._native(roles).items() if key not in ('frame', 'time')}
                or self._limits(parameter) != value['limits']
                or nodes != self._checkpoint_nodes(binding) or binding != self._binding(roles, pack)):
            _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'late native binding drift')
        return value, binding

    def _checkpoint_nodes(self, binding):
        nodes = {}
        for role, fact in binding['nodes'].items():
            node = self.hou.node(fact['path'])
            if node is None:
                _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'actual checkpoint node required')
            node_fact = dict(path=node.path(), type=node.type().name(),
                category=node.type().category().name().lower(), parent=node.parent().path(),
                editable=node.isEditable(), bypassed=node.isBypassed(), errors=list(node.errors()))
            if node_fact['editable'] is not True or node_fact['bypassed'] is not False or node_fact['errors']:
                _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'actual editable unbypassed owned nodes required')
            nodes[role] = node_fact
        return nodes

    def checkpoint(self, roles, pack):
        with self.authority['lock']:
            context = self.observations(roles, pack)[CONTEXT]
            root = context['binding']['task_root']
            record = self.authority['records'][root]
            value, binding = self._checkpoint_capture(roles, pack, record)
            for _ in range(2):
                self.observations(roles, pack)
                current, current_binding = self._checkpoint_capture(roles, pack, record)
                if (current != value or current_binding != binding
                        or self.authority['records'].get(root) is not record):
                    _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'complete native checkpoint facts changed')
            self.observations(roles, pack)
            if self.authority['records'].get(root) is not record:
                _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'terminal private registration changed')
            return value

    def _reopen_authorized(self, roles, pack, checkpoint):
        callback = self.host.get('_fx_particle_emission_reopen_authority')
        if not callable(callback) or callback(copy.deepcopy(roles), copy.deepcopy(pack),
                                              copy.deepcopy(checkpoint)) is not True:
            _fail('PARTICLE_EMISSION_REOPEN_AUTHORITY_REQUIRED', 'verified saved HIP and lease scope required')

    def _reopen_owned(self, token, transaction, record):
        if (self.authority['reopens'].get(token) is not transaction
                or self.authority['records'].get(transaction['root']) is not record):
            _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'private reopen registration was replaced')

    def _abort_reopen(self, token, transaction):
        if self.authority['reopens'].get(token) is not transaction:
            return
        issued = transaction['issued']
        root = transaction['root']
        if issued is not None and self.authority['records'].get(root) is issued:
            if transaction['previous'] is None:
                self.authority['records'].pop(root)
            else:
                self.authority['records'][root] = transaction['previous']
        self.authority['reopens'].pop(token)

    def reopen(self, roles, pack, checkpoint):
        with self.authority['lock']:
            value = _checkpoint_json(checkpoint)
            if type(value) is not dict or not {'basis', 'percentage', 'birth_rate', 'expression'} <= set(value):
                _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'complete saved checkpoint required')
            seed_record = {name: value[name] for name in ('basis', 'percentage', 'birth_rate', 'expression')}
            current, binding = self._checkpoint_capture(roles, pack, seed_record)
            if (set(value) != set(current) or value.get('schema') != CHECKPOINT_SCHEMA
                    or any(value[name] != current[name] for name in current if name != 'identity')):
                _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'saved checkpoint differs from actual native facts')
            previous_identity = value['identity']
            identity = binding['identity']
            session_fields = {'pid', 'launch_nonce', 'session_id', 'process_generation', 'scene_epoch'}
            if (type(previous_identity) is not dict or set(previous_identity) != set(identity)
                    or any(previous_identity[name] != identity[name] for name in identity if name not in session_fields)
                    or type(previous_identity.get('pid')) is not int or previous_identity['pid'] <= 0
                    or type(previous_identity.get('scene_epoch')) is not int or previous_identity['scene_epoch'] < 0
                    or any(type(previous_identity.get(name)) is not str or not previous_identity[name]
                           for name in ('launch_nonce', 'session_id', 'process_generation'))):
                _fail('PARTICLE_EMISSION_CHECKPOINT_INVALID', 'complete compatible saved host identity required')
            root = binding['task_root']
            self._reject_reopen(root)
            if root in self.authority['builds'] or any(
                    snapshot['root'] == root for snapshot in self.authority['snapshots'].values()):
                _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'pending native write or build cannot reopen')
            if len(self.authority['reopens']) >= MAX_REOPEN_TRANSACTIONS:
                _fail('PARTICLE_EMISSION_CHECKPOINT_BUDGET_EXCEEDED', 'reopen transaction budget exceeded')
            previous = self.authority['records'].get(root)
            token = secrets.token_hex(32)
            transaction = dict(root=root, previous=previous, issued=None, roles=copy.deepcopy(roles),
                pack=copy.deepcopy(pack), checkpoint=value, binding=binding)
            self.authority['reopens'][token] = transaction
            try:
                self._reopen_authorized(roles, pack, value)
                self._reopen_owned(token, transaction, previous)
                recaptured, recaptured_binding = self._checkpoint_capture(roles, pack, seed_record)
                if recaptured != current or recaptured_binding != binding:
                    _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'native facts changed during authorization')
                issued = dict(binding=copy.deepcopy(binding),
                    **{name: copy.deepcopy(value[name]) for name in
                       ('basis', 'percentage', 'birth_rate', 'expression', 'channel', 'limits', 'native')})
                transaction['issued'] = issued
                self.authority['records'][root] = issued
                if self.checkpoint(roles, pack) != current:
                    _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'native facts changed during registration')
                self._reopen_authorized(roles, pack, value)
                self._reopen_owned(token, transaction, issued)
                if self.checkpoint(roles, pack) != current:
                    _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'late authorized native facts changed')
                self._reopen_owned(token, transaction, issued)
                if transaction['root'] in self.authority['builds'] or any(
                        snapshot['root'] == transaction['root'] for snapshot in self.authority['snapshots'].values()):
                    _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'pending native write or build cannot end reopen')
            except Exception:
                self._abort_reopen(token, transaction)
                raise
            return token

    def end(self, token, commit):
        with self.authority['lock']:
            if type(token) is not str or type(commit) is not bool:
                _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'current opaque reopen token and boolean required')
            transaction = self.authority['reopens'].get(token)
            if transaction is None:
                _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'current private reopen transaction required')
            try:
                issued = transaction['issued']
                if issued is None:
                    _fail('PARTICLE_EMISSION_TRANSACTION_REQUIRED', 'reopen has not issued a registration')
                self._reopen_owned(token, transaction, issued)
                if not commit:
                    self._abort_reopen(token, transaction)
                    return
                roles, pack, expected = transaction['roles'], transaction['pack'], transaction['checkpoint']
                for _ in range(2):
                    actual = self.checkpoint(roles, pack)
                    if (actual['identity'] != transaction['binding']['identity']
                            or any(actual[name] != expected[name] for name in actual if name != 'identity')):
                        _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'saved facts changed before commit')
                    self._reopen_authorized(roles, pack, expected)
                    self._reopen_owned(token, transaction, issued)
                    if self.checkpoint(roles, pack) != actual:
                        _fail('PARTICLE_EMISSION_CHECKPOINT_CHANGED', 'final native facts changed before commit')
                    self._reopen_owned(token, transaction, issued)
                self._reopen_authorized(roles, pack, expected)
                self._reopen_owned(token, transaction, issued)
                issued['checkpoint_reopen'] = dict(evidence_scope='trusted_software_checkpoint_rebind',
                    previous_identity=copy.deepcopy(expected['identity']), identity=copy.deepcopy(actual['identity']),
                    new_pid_and_nonce=(expected['identity']['pid'] != actual['identity']['pid']
                        and expected['identity']['launch_nonce'] != actual['identity']['launch_nonce']),
                    native_writes=False)
                self.authority['reopens'].pop(token)
            except Exception:
                self._abort_reopen(token, transaction)
                raise

    def readback(self, roles, pack):
        current = self.observations(roles, pack)[CONTEXT]
        rate_range = program.validate_rate_range(current['basis'], current['percentage'], current['birth_rate'],
            native_minimum=current['limits']['minimum'], native_maximum=current['limits']['maximum'])
        missing = ['same_build_POP_substep_emission_integration',
                   'time_scale_and_bucket_boundary_native_consumption', 'verified_new_PID_checkpoint_reopen']
        reopened = current.get('checkpoint_reopen')
        if reopened is not None and reopened['new_pid_and_nonce'] is True:
            missing.remove('verified_new_PID_checkpoint_reopen')
            missing.append('real_host_new_PID_checkpoint_reopen')
        return {'status': 'BLOCKED', 'evidence_scope': 'native_parameter_expression_only',
                'percentage': current['percentage'], 'birth_rate': current['birth_rate'],
                'actual_rate': current['actual_rate'], 'context': current, 'rate_range': rate_range,
                'checkpoint_reopen': copy.deepcopy(reopened), 'missing_evidence': missing}
