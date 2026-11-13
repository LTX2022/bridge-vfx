"""P02 native collectors for the existing authenticated addon transaction.

No task, process, render, simulation or producer lifecycle is owned here.
Geometry access may cook in HOM and must only run in an authorized host.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import copy
import json
import hmac
import secrets

from . import native_particle_ocean_geometry_domains as core
from . import native_particle_size_program as program


BASIS_KEY = 'bridge_particle_size_basis_v1'
PARAMETERS = dict(program.COMMON_GATES, valuetype=('ordinal', None),
                  singlevalue=('float', None), rangemethod=('ordinal', None),
                  distribinrange=('ordinal', None), randmethod=('ordinal', None),
                  randattrib=('string', None), randomseed=('integer', None),
                  enablestepping=('toggle', None), minvalue=('float', None),
                  rangevalue=('float', None))
GEOMETRY_ROLES = ('simulation', program.ROLE, 'instance_source', 'instances', 'output')


class Host:
    def __init__(self, host, *, hou_module=None):
        if hou_module is None:
            import hou as hou_module
        self.host = host
        self.hou = hou_module

    def call(self, name, *args, **kwargs):
        return self.host[name](*args, **kwargs)

    def binding(self, roles, pack):
        if pack.get('native_domain_id') != core.PARTICLES:
            raise program.ParticleSizeError('PARTICLE_SIZE_HOST_DOMAIN_REQUIRED', 'particles only')
        root = self.call('_fx_planned_owned_root', roles, pack)
        lease = self.call('_root_lease_check', root, scope='sop', renew=False)
        identity = self.call('_host_identity')
        version = self.hou.applicationVersionString()
        if (identity.get('task_id') != lease['task_id'] or not identity.get('launch_nonce')
                or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or identity.get('version') != version or version not in (*core.VERSIONS, *PREPARATION_VERSIONS)):
            raise program.ParticleSizeError('PARTICLE_SIZE_AUTHENTICATED_HOST_REQUIRED', 'lease/host identity differs')
        return dict(task_id=lease['task_id'], task_root=root, node_path=roles[program.ROLE],
                    native_version=version)

    def initialize(self, params, roles, pack, fresh_roles):
        supplied = self.call('_fx_configuration', params).get('particle_size_basis')
        node = self.hou.node(roles[program.ROLE])
        raw = node.userData(BASIS_KEY)
        try:
            binding = self.binding(roles, pack)
        except Exception as error:
            if supplied is not None or raw is not None:
                raise
            return dict(status='blocked', code='PARTICLE_SIZE_AUTHENTICATED_HOST_REQUIRED',
                        detail=str(error), missing=['authenticated task host for optional P02 registration'])
        if raw is not None:
            basis = self.basis(roles, pack)
            if supplied is not None and supplied != {name: basis[name] for name in ('size', 'task_seed')}:
                raise program.ParticleSizeError('PARTICLE_SIZE_BASIS_CHANGED', 'rebuild cannot replace registered basis')
            return basis
        if supplied is None:
            if program.ROLE not in fresh_roles:
                return dict(status='blocked', code='PARTICLE_SIZE_FROZEN_BASIS_REQUIRED',
                            missing=['fresh owned particle_size or existing registered basis'])
            observed = self.call('_fx_planned_observation', node, 'singlevalue')
            supplied = dict(size=observed.get('value'), task_seed=secrets.randbelow(2147483648))
        if (not isinstance(supplied, dict) or set(supplied) != {'size', 'task_seed'}
                or program.ROLE not in fresh_roles):
            raise program.ParticleSizeError('PARTICLE_SIZE_FROZEN_BASIS_REQUIRED', 'explicit basis and fresh owned node required')
        core._number(supplied['size'], .0001, 100, 'size')
        core._number(supplied['task_seed'], 0, 2147483647, 'task_seed', integer=True)
        observed = self.call('_fx_planned_observation', node, 'singlevalue')
        mode = self.call('_fx_planned_observation', node, 'valuetype')
        if (observed.get('type') != 'float' or type(observed.get('size')) is not int
                or observed['size'] != 1 or not core._typed_value(observed.get('value'), 'float', 1)
                or not core._near(observed['value'], supplied['size'])
                or any(observed.get(flag) is not False for flag in ('driven', 'locked', 'disabled', 'hidden'))
                or not core._gate_matches(mode, 'const')):
            raise program.ParticleSizeError('PARTICLE_SIZE_FROZEN_BASIS_REQUIRED', 'basis must match actual undriven constant pscale')
        basis = dict(schema=program.BASIS_SCHEMA, origin='runtime_hom', task_owned=True,
                     **binding, size=float(observed['value']), task_seed=supplied['task_seed'],
                     id_attribute='id')
        basis['content_sha256'] = program.basis_content_sha256(basis)
        node.setUserData(BASIS_KEY, json.dumps(basis, sort_keys=True, separators=(',', ':'), allow_nan=False))
        return self.basis(roles, pack)

    def basis(self, roles, pack):
        binding = self.binding(roles, pack)
        raw = self.hou.node(roles[program.ROLE]).userData(BASIS_KEY)
        try:
            basis = json.loads(raw) if raw is not None else None
        except (TypeError, ValueError) as error:
            raise program.ParticleSizeError('PARTICLE_SIZE_FROZEN_BASIS_REQUIRED', 'invalid persisted basis') from error
        if (not isinstance(basis, dict) or set(basis) != program.BASIS_FIELDS
                or basis.get('schema') != program.BASIS_SCHEMA or basis.get('origin') != 'runtime_hom'
                or basis.get('task_owned') is not True or basis.get('id_attribute') != 'id'
                or any(basis.get(key) != value for key, value in binding.items())
                or basis.get('content_sha256') != program.basis_content_sha256(basis)):
            raise program.ParticleSizeError('PARTICLE_SIZE_BASIS_CHANGED', 'persisted basis identity/digest differs')
        core._number(basis['size'], .0001, 100, 'size')
        core._number(basis['task_seed'], 0, 2147483647, 'task_seed', integer=True)
        return copy.deepcopy(basis)

    def geometry(self, node):
        try:
            return self._geometry(node)
        except program.ParticleSizeError:
            raise
        except Exception as error:
            raise program.ParticleSizeError('PARTICLE_SIZE_ACTUAL_GEOMETRY_REQUIRED',
                                          node.path() + ': ' + str(error)) from error

    def _geometry(self, node):
        geometry = node.geometry(output_index=0)
        if geometry is None:
            raise program.ParticleSizeError('PARTICLE_SIZE_ACTUAL_GEOMETRY_REQUIRED', node.path())
        points, primitives = tuple(geometry.points()), tuple(geometry.prims())
        attributes = tuple(geometry.pointAttribs())
        if len(points) > 8192 or len(primitives) > 8192 or len(attributes) > 128:
            raise program.ParticleSizeError('PARTICLE_SIZE_COPY_OBSERVATION_BUDGET_EXCEEDED', 'bounded native geometry collector')
        point_indices = {point.number(): index for index, point in enumerate(points)}
        if len(point_indices) != len(points):
            raise program.ParticleSizeError('PARTICLE_SIZE_ACTUAL_GEOMETRY_REQUIRED', 'duplicate point numbers')
        result = dict(origin='runtime_hom', points=len(points), primitives=len(primitives),
                      positions=[list(point.position()) for point in points],
                      point_attributes={}, primitive_records=[])
        for attribute in attributes:
            kind = str(attribute.dataType()).rsplit('.', 1)[-1].lower()
            precision = str(attribute.numericDataType()).rsplit('.', 1)[-1].lower() if kind in ('float', 'int', 'integer') else None
            if kind == 'int':
                kind = 'integer'
            name = attribute.name()
            if name in result['point_attributes']:
                raise program.ParticleSizeError('PARTICLE_SIZE_ATTRIBUTE_VALUES_REQUIRED', 'duplicate point attribute')
            values = []
            for point in points:
                value = point.attribValue(name)
                values.append(list(value) if isinstance(value, tuple) else value)
            result['point_attributes'][name] = dict(type=kind, size=attribute.size(), owner='point',
                precision=precision, is_array=attribute.isArrayType(), values=values)
        total_vertices = 0
        for primitive in primitives:
            kind = primitive.type().name()
            if kind != 'Polygon':
                result['primitive_records'].append(dict(type=kind, closed=None, vertices=[]))
                continue
            vertices = tuple(primitive.vertices())
            total_vertices += len(vertices)
            if total_vertices > 65536:
                raise program.ParticleSizeError('PARTICLE_SIZE_COPY_OBSERVATION_BUDGET_EXCEEDED', 'primitive vertex budget')
            result['primitive_records'].append(dict(type=kind, closed=primitive.isClosed(),
                vertices=[point_indices[vertex.point().number()] for vertex in vertices]))
        program._digest(result)
        return result

    def prepare(self, item):
        plan = program.plan_from_routed_writes([item['native_write']])
        if not plan.staged:
            raise program.ParticleSizeError('PARTICLE_SIZE_PLAN_CHANGED', 'staged plan required')
        node = item['node']
        names = sorted({write['parm'] for write in plan.writes} | {'valuetype', 'singlevalue'})
        snapshots = {}
        for name in names:
            parameter = self.call('_resolve_parm_target', node, [name])
            if parameter is None:
                raise program.ParticleSizeError('PARTICLE_SIZE_PARAMETER_UNAVAILABLE', name)
            snapshots[name] = self.call('_snapshot_parm_state', parameter, capture_extrapolation=True)
        snapshot = dict(parameters=snapshots, basis=node.userData(BASIS_KEY),
                        plan_sha256=plan.content_sha256, node_path=node.path())
        item['particle_size_snapshot'] = snapshot
        item['particle_size_snapshot_seal'] = program._plan_seal(program._digest(self._snapshot_identity(snapshot)))

    def _snapshot_identity(self, snapshot):
        def identity(value, key=None):
            if key == 'component':
                return value.path()
            if key == 'keyframes':
                return [self.call('_keyframe_identity', frame) for frame in value]
            if key == 'extrapolation':
                return [str(item) for item in value]
            if isinstance(value, dict):
                return {name: identity(item, name) for name, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [identity(item) for item in value]
            return value
        return identity(snapshot)

    def _snapshot(self, item):
        snapshot = item.get('particle_size_snapshot')
        seal = item.get('particle_size_snapshot_seal')
        if (not isinstance(snapshot, dict) or not isinstance(seal, str)
                or not hmac.compare_digest(seal, program._plan_seal(program._digest(self._snapshot_identity(snapshot))))
                or snapshot.get('node_path') != item['node'].path()):
            raise program.ParticleSizeError('PARTICLE_SIZE_PLAN_CHANGED', 'full native snapshot seal differs')
        return snapshot

    def _set(self, node, name, value, kind):
        actual = self.call('_fx_planned_observation', node, name)
        if (actual.get('type') != kind or type(actual.get('size')) is not int or actual['size'] != 1
                or any(actual.get(flag) is not False for flag in ('driven', 'locked', 'disabled', 'hidden'))):
            raise program.ParticleSizeError('PARTICLE_SIZE_PARAMETER_UNAVAILABLE', name + '/actual staged gate')
        parameter = self.call('_resolve_parm_target', node, [name])
        if parameter is None:
            raise program.ParticleSizeError('PARTICLE_SIZE_PARAMETER_UNAVAILABLE', name)
        self.call('_set_parm_verified', parameter, value)
        observed = self.call('_fx_planned_observation', node, name)
        if not core._gate_matches(observed, value):
            raise program.ParticleSizeError('PARTICLE_SIZE_PARAMETER_READBACK_MISMATCH', name)

    def write(self, item, roles, pack):
        plan = program.plan_from_routed_writes([item['native_write']])
        snapshot = self._snapshot(item)
        if snapshot['plan_sha256'] != plan.content_sha256:
            raise program.ParticleSizeError('PARTICLE_SIZE_PLAN_CHANGED', 'snapshot binds a different plan')
        node = item['node']
        if node.userData(BASIS_KEY) != snapshot['basis']:
            raise program.ParticleSizeError('PARTICLE_SIZE_BASIS_CHANGED', 'registration changed after prepare')
        for name, before in snapshot['parameters'].items():
            parameter = self.call('_resolve_parm_target', node, [name])
            if self._snapshot_identity(self.call('_snapshot_parm_state', parameter, capture_extrapolation=True)) != self._snapshot_identity(before):
                raise program.ParticleSizeError('NATIVE_CONTROL_CONTEXT_CHANGED', name + '/native snapshot changed')
        before = self.observations(roles, pack)
        program.validate_control_write_plan(plan, before)
        basis = before[program.ROLE, '@size_basis']
        size = basis['size'] if plan.size_override is None else plan.size_override
        self._set(node, 'valuetype', 'const', 'ordinal')
        self._set(node, 'singlevalue', size, 'float')
        if plan.percentage > 0:
            self._set(node, 'valuetype', 'rand', 'ordinal')
            values = {write['parm']: write for write in plan.writes}
            for name in ('randmethod', 'randattrib', 'rangemethod', 'distribinrange',
                         'enablestepping', 'randomseed', 'minvalue', 'rangevalue'):
                write = values[name]
                self._set(node, name, write['value'], write['native_type'])
        after = self.observations(roles, pack)
        result = program.validate_geometry_consumption(plan, after)
        actual = program.collect_control_readback(plan.native_version, after)
        return dict(parameter='particle_size_program', parameter_path=item['parm'].path(),
                    requested=plan.percentage, after=actual.observed_percentage,
                    readback_verified=True, evidence_scope=result.evidence_scope,
                    actual_pscale_by_id=result.pscale_by_id,
                    copied_ids=list(result.copied_ids), missing_evidence=list(result.missing_evidence))

    def restore(self, item):
        snapshot = self._snapshot(item)
        node = item['node']
        parameters = snapshot['parameters']
        errors = []
        def restore_parameter(name):
            parameter = self.call('_resolve_parm_target', node, [name])
            actual = self.call('_fx_planned_observation', node, name)
            if any(actual.get(flag) is not False for flag in ('driven', 'locked', 'disabled', 'hidden')):
                raise program.ParticleSizeError('PARTICLE_SIZE_PARAMETER_UNAVAILABLE', name + '/actual rollback gate')
            self.call('_restore_parm_snapshot', parameter, parameters[name])
        try:
            if 'minvalue' in parameters:
                self._set(node, 'valuetype', 'rand', 'ordinal')
                self._set(node, 'randmethod', 'custom', 'ordinal')
                self._set(node, 'rangemethod', 'minplusrange', 'ordinal')
                self._set(node, 'distribinrange', 'uniform', 'ordinal')
                for name in ('minvalue', 'rangevalue', 'randomseed', 'randattrib', 'enablestepping',
                             'distribinrange', 'randmethod', 'rangemethod'):
                    restore_parameter(name)
            self._set(node, 'valuetype', 'const', 'ordinal')
            restore_parameter('singlevalue')
            restore_parameter('valuetype')
        except Exception as error:
            errors.append('staged parameter restore: ' + str(error))
        for name in parameters:
            try:
                parameter = self.call('_resolve_parm_target', node, [name])
                if self._snapshot_identity(self.call('_snapshot_parm_state', parameter, capture_extrapolation=True)) != self._snapshot_identity(parameters[name]):
                    errors.append(name + ': native state remains unrestored')
            except Exception as error:
                errors.append(name + ': ' + str(error))
        try:
            if snapshot['basis'] is None:
                node.destroyUserData(BASIS_KEY)
            else:
                node.setUserData(BASIS_KEY, snapshot['basis'])
            if node.userData(BASIS_KEY) != snapshot['basis']:
                errors.append('basis userdata restore differs')
            for name, expected in parameters.items():
                parameter = self.call('_resolve_parm_target', node, [name])
                if self._snapshot_identity(self.call('_snapshot_parm_state', parameter, capture_extrapolation=True)) != self._snapshot_identity(expected):
                    errors.append(name + ': restored native snapshot differs')
        except Exception as error:
            errors.append('restore verification: ' + str(error))
        if errors:
            raise program.ParticleSizeError('PARTICLE_SIZE_RESTORE_FAILED', '; '.join(errors))

    def observations(self, roles, pack):
        binding = self.binding(roles, pack)
        result = {(program.ROLE, '@size_basis'): self.basis(roles, pack)}
        for requirement in core.node_requirements(core.PARTICLES, binding['native_version']):
            role = requirement['role']
            node = self.hou.node(roles[role])
            result[role, '@node'] = dict(origin='runtime_hom', task_owned=True,
                task_id=binding['task_id'], native_version=binding['native_version'], task_root=binding['task_root'],
                path=node.path(), type=node.type().name(), category=node.type().category().name().lower(),
                context_parent_path=node.parent().path())
        for edge in core.connection_requirements(core.PARTICLES, binding['native_version']):
            node = self.hou.node(roles[edge['destination_role']])
            connections = [connection for connection in node.inputConnections()
                           if connection.inputIndex() == edge['destination_input']]
            if len(connections) != 1:
                raise program.ParticleSizeError('ACTUAL_NATIVE_CONNECTION_REQUIRED', edge['destination_role'])
            connection = connections[0]
            source = connection.inputNode()
            result[edge['destination_role'], '@input/' + str(edge['destination_input'])] = dict(
                origin='runtime_hom', task_owned=True, source_path=source.path(), source_type=source.type().name(),
                source_output=connection.outputIndex(), destination_input=connection.inputIndex())
        for name in PARAMETERS:
            result[program.ROLE, name] = self.call('_fx_planned_observation', self.hou.node(roles[program.ROLE]), name)
        for role in GEOMETRY_ROLES:
            result[role, '@geometry/0'] = self.geometry(self.hou.node(roles[role]))
        result[program.ROLE, '@size_context'] = dict(origin='runtime_hom',
            schema='bridge.particle-size-context/1', binding=binding, geometry_roles=list(GEOMETRY_ROLES))
        program._context(binding['native_version'], result)
        return result
