"""Process-local G03 trust; the addon owns the enclosing build transaction.

Bind source_basis/source_geometry/registration as the three Host hooks. Keep
begin's opaque token until all build/readback/manifest work completes, then
end(token, commit). Persisted userData alone cannot recreate trust; reopening
requires the addon's private verified-HIP authority and fresh native readback.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import base64
import copy
from functools import wraps
import hashlib
import json
import os
import secrets
import stat
from threading import RLock

from . import native_geometry_controls_program as program
from .render_ocio_facts import _chain, _file_path, _signature

REST_SCHEMA = 'bridge.geometry-rest-input/1'
CHECKPOINT_SCHEMA = 'bridge.geometry-registry-checkpoint/1'
MAX_CHECKPOINT_BYTES = 256 * 1024
MAX_COHORTS = 128
MAX_MANIFEST_ITEMS = 32
MAX_REST_BYTES = 65536
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
_COHORTS = {}
_TRANSACTIONS = {}
_LOCK = RLock()
_REGISTRATION_KEY = 'bridge_geometry_deform_initialization_v1'
_BASIS_KEY = 'bridge_geometry_deform_basis_v1'
_REQUIRED_ROLES = ('instance_source', program.ROLE, 'instance_transform')


def _fail(code):
    raise program.GeometryControlsError(code, 'bounded G03 registry refused the current request') from None


def _bounded_json(value, limit=MAX_REST_BYTES):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > limit:
        _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
    return encoded


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('GEOMETRY_REST_INPUT_INVALID')
        result[key] = value
    return result


def _constant(value):
    _fail('GEOMETRY_REST_INPUT_INVALID')


def _checkpoint_json(value):
    remaining = [32768]
    def visit(item, depth):
        remaining[0] -= 1
        if depth > 24 or remaining[0] < 0:
            _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                _fail('GEOMETRY_CHECKPOINT_INVALID')
            for child in item.values():
                visit(child, depth + 1)
        elif type(item) in (list, tuple):
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str and len(item) > MAX_CHECKPOINT_BYTES:
            _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
        elif item is not None and type(item) not in (str, int, float, bool):
            _fail('GEOMETRY_CHECKPOINT_INVALID')
    visit(value, 0)
    return json.loads(_bounded_json(value, MAX_CHECKPOINT_BYTES))


def _protected(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with _LOCK:
            try:
                return method(self, *args, **kwargs)
            except program.GeometryControlsError:
                raise
            except Exception:
                _fail('GEOMETRY_REGISTRY_REFUSED')
    return invoke


def _read_file(item, limit):
    name = item.get('source_uri') or item.get('identity')
    path = _file_path(name)
    if str(path) != name or path.lstat().st_nlink != 1:
        _fail('GEOMETRY_REST_INPUT_PATH_REQUIRED')
    size = item.get('bytes')
    if (type(size) is not int or not 0 < size <= limit
            or not program._digest(item.get('sha256'))):
        _fail('GEOMETRY_REST_INPUT_INVALID')
    chain = _chain(path)
    before = path.lstat()
    if before.st_size != size:
        _fail('GEOMETRY_REST_INPUT_CHANGED')
    flags = (os.O_RDONLY | getattr(os, 'O_BINARY', 0)
             | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or _signature(opened) != _signature(before)
                or opened.st_nlink != 1 or _chain(path) != chain):
            _fail('GEOMETRY_REST_INPUT_CHANGED')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(size + 1)
        if (len(raw) != size or _signature(os.fstat(descriptor)) != _signature(before)
                or _signature(path.lstat()) != _signature(before) or _chain(path) != chain
                or hashlib.sha256(raw).hexdigest() != item['sha256']):
            _fail('GEOMETRY_REST_INPUT_CHANGED')
        return raw, (_signature(before), chain)
    finally:
        os.close(descriptor)


class Registry:
    def __init__(self, host, *, hou_module=None):
        if hou_module is None:
            import hou as hou_module
        self.host = host
        self.hou = hou_module

    def _call(self, name, *args, **kwargs):
        callback = self.host.get(name)
        if not callable(callback):
            _fail('GEOMETRY_HOST_HOOK_REQUIRED')
        try:
            return callback(*args, **kwargs)
        except Exception:
            _fail('GEOMETRY_REGISTRY_HOST_REFUSED')

    def _binding(self, roles, pack):
        if (type(roles) is not dict or not 3 <= len(roles) <= MAX_COHORTS
                or any(role not in roles for role in _REQUIRED_ROLES)
                or type(pack) is not dict or pack.get('native_domain_id') != 'procedural_geometry_v1'):
            _fail('GEOMETRY_OWNED_GRAPH_REQUIRED')
        _bounded_json(roles)
        _bounded_json(pack)
        requirements = pack.get('nodes')
        if (type(requirements) is not list or len(requirements) != len(roles)
                or any(type(item) is not dict for item in requirements)
                or len({item.get('role') for item in requirements}) != len(roles)
                or {item.get('role') for item in requirements} != set(roles)
                or any(type(role) is not str or not role or role == '__root__' for role in roles)
                or any(not program._path(path) for path in roles.values())
                or len(set(roles.values())) != len(roles)):
            _fail('GEOMETRY_OWNED_GRAPH_REQUIRED')
        root = self._call('_fx_planned_owned_root', roles, pack)
        lease = self._call('_root_lease_check', root, scope='sop', renew=False)
        identity = (self._call('_fx_geometry_host_identity', lease['task_id'])
                    if callable(self.host.get('_fx_geometry_host_identity')) else self._call('_host_identity'))
        version = self.hou.applicationVersionString()
        if (not program._path(root) or not root.startswith('/obj/')
                or type(lease) is not dict or type(identity) is not dict
                or not lease.get('task_id') or identity.get('task_id') != lease['task_id']
                or version not in (*program.VERSIONS, *PREPARATION_VERSIONS) or identity.get('version') != version
                or type(identity.get('pid')) is not int or identity['pid'] != os.getpid()
                or type(identity.get('scene_epoch')) is not int or identity['scene_epoch'] < 0
                or any(type(identity.get(key)) is not str or not identity[key]
                       for key in ('launch_nonce', 'session_id', 'process_generation'))):
            _fail('GEOMETRY_AUTHENTICATED_HOST_REQUIRED')
        _bounded_json(identity)
        return dict(task_id=lease['task_id'], task_root=root, native_version=version,
                    host_identity=copy.deepcopy(identity))

    def _nodes(self, roles, binding):
        paths = dict(roles, __root__=binding['task_root'])
        nodes, sessions = {}, set()
        for role, path in paths.items():
            node = self.hou.node(path)
            if (node is None or node.path() != path
                    or (role != '__root__' and not path.startswith(binding['task_root'] + '/'))):
                _fail('GEOMETRY_OWNED_GRAPH_REQUIRED')
            session = node.sessionId()
            if type(session) is not int or session <= 0 or session in sessions:
                _fail('GEOMETRY_NODE_SESSION_CHANGED')
            sessions.add(session)
            nodes[role] = (node, session)
        return nodes

    def _manifest(self, manifest, binding, roles):
        """Rehash descriptor-observed bytes with unchanged declared size and SHA.

        The existing rehasher supports data URIs. Giving it these bounded bytes
        avoids its unbounded second filesystem open, while path/descriptor
        snapshots still fence the original supplied file around verification.
        """
        if type(manifest) is not list or not 1 <= len(manifest) <= MAX_MANIFEST_ITEMS:
            _fail('GEOMETRY_REST_INPUT_REQUIRED')
        _bounded_json(manifest)
        basis_items = [item for item in manifest if type(item) is dict
                       and item.get('semantic_role') == 'geometry_rest_basis']
        if len(basis_items) != 1:
            _fail('GEOMETRY_REST_INPUT_REQUIRED')
        basis_item = basis_items[0]
        snapshots, basis_raw, total, byte_manifest = [], None, 0, []
        for index, item in enumerate(manifest):
            if (type(item) is not dict or type(item.get('index')) is not int
                    or item['index'] != index or 'frames' in item):
                _fail('GEOMETRY_REST_INPUT_INVALID')
            limit = MAX_REST_BYTES if item is basis_item else MAX_INPUT_BYTES
            raw, snapshot = _read_file(item, min(limit, MAX_TOTAL_BYTES - total))
            total += len(raw)
            snapshots.append(snapshot)
            byte_item = copy.deepcopy(item)
            byte_item['source_uri'] = 'data:application/octet-stream;base64,' + base64.b64encode(raw).decode('ascii')
            byte_manifest.append(byte_item)
            if item is basis_item:
                basis_raw = raw
        manifest_hash = self._call('_rehash_frozen_input_manifest', byte_manifest)
        expected_hash = hashlib.sha256(json.dumps(byte_manifest, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        if manifest_hash != expected_hash:
            _fail('GEOMETRY_REST_INPUT_CHANGED')
        for item, snapshot in zip(manifest, snapshots):
            path = _file_path(item.get('source_uri') or item.get('identity'))
            if (_signature(path.lstat()), _chain(path)) != snapshot:
                _fail('GEOMETRY_REST_INPUT_CHANGED')
        document = json.loads(basis_raw.decode('utf-8'), object_pairs_hook=_object,
                              parse_constant=_constant)
        required = {'schema', 'task_id', 'task_root', 'native_version', 'input_version',
                    'source_node_path', 'output', 'frame', 'space', 'unit', 'local_x_axis',
                    'source_geometry_sha256'}
        if type(document) is not dict:
            _fail('GEOMETRY_AUTHENTICATED_REST_BASIS_REQUIRED')
        observation = basis_item.get('geometry_observation', document.get('geometry_observation'))
        if (not required <= set(document)
                or set(document) - required - {'geometry_observation'}
                or document['schema'] != REST_SCHEMA
                or any(document[key] != binding[key] for key in ('task_id', 'task_root', 'native_version'))
                or type(document['input_version']) is not str or not document['input_version']
                or document['source_node_path'] != roles['instance_source']
                or type(document['output']) is not int or document['output'] != 0
                or document['space'] != 'sop_local_rest' or document['unit'] != 'SU'
                or type(document['local_x_axis']) is not list or len(document['local_x_axis']) != 3
                or any(type(value) not in (int, float) for value in document['local_x_axis'])
                or document['local_x_axis'] != [1, 0, 0]
                or not program._digest(document['source_geometry_sha256'])
                or observation != 'native_sop_read'
                or ('geometry_observation' in document
                    and document['geometry_observation'] != 'native_sop_read')):
            _fail('GEOMETRY_AUTHENTICATED_REST_BASIS_REQUIRED')
        program._number(document['frame'], 'authenticated rest frame')
        provenance = {key: copy.deepcopy(value) for key, value in document.items() if key != 'schema'}
        provenance.update(basis_input_sha256=basis_item['sha256'],
                          geometry_observation=observation)
        return provenance

    def _find(self, roles, pack):
        entries = [entry for entry in _COHORTS.values()
                   if entry['host'] is self.host and entry['hou'] is self.hou
                   and entry['roles'] == roles and entry['pack'] == pack]
        if len(entries) != 1:
            _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
        return entries[0]

    def _check_identity(self, entry):
        if self._binding(entry['roles'], entry['pack']) != entry['binding']:
            _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
        current = self._nodes(entry['roles'], entry['binding'])
        if any(current[role][0] is not node or current[role][1] != session
               for role, (node, session) in entry['nodes'].items()):
            _fail('GEOMETRY_NODE_SESSION_CHANGED')

    def _check(self, entry):
        self._check_identity(entry)
        provenance = self._manifest(entry['manifest'], entry['binding'], entry['roles'])
        if provenance != entry['provenance']:
            _fail('GEOMETRY_REST_INPUT_CHANGED')
        self._check_identity(entry)
        return provenance

    def _checkpoint(self, entry):
        from .native_geometry_controls_host import Host
        self._check(entry)
        if entry['record'] is None:
            _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
        node = entry['nodes'][program.ROLE][0]
        userdata = {key: node.userData(key) for key in (_BASIS_KEY, _REGISTRATION_KEY)}
        if any(type(raw) is not str or len(raw.encode('utf-8')) > MAX_REST_BYTES
               for raw in userdata.values()):
            _fail('GEOMETRY_CHECKPOINT_INVALID')
        hooks = dict(self.host, _fx_geometry_source_basis=self.source_basis,
                     _fx_geometry_source_geometry=self.source_geometry,
                     _fx_geometry_registration=self.registration)
        observed = Host(hooks, hou_module=self.hou).observations(entry['roles'], entry['pack'])
        if observed['binding'] != entry['binding']:
            _fail('GEOMETRY_AUTHENTICATED_HOST_REQUIRED')
        basis_raw = userdata[_BASIS_KEY]
        basis = json.loads(basis_raw, object_pairs_hook=_object, parse_constant=_constant)
        if basis != observed['context']['basis']:
            _fail('GEOMETRY_BASIS_CHANGED')
        parameters = [dict(role=program.ROLE, parm=name,
                           observation=observed['parameters'][(program.ROLE, name)])
                      for name in (*program.GATES, 'snippet')]
        self._check(entry)
        self.registration('verify', entry['roles'], entry['pack'], entry['record'])
        current = program.collect_parameters(node, self.host['_fx_planned_observation'])
        if (_checkpoint_json([current[(program.ROLE, name)] for name in (*program.GATES, 'snippet')])
                != _checkpoint_json([item['observation'] for item in parameters])
                or {key: node.userData(key) for key in userdata} != userdata):
            _fail('GEOMETRY_CHECKPOINT_CHANGED')
        self._check_identity(entry)
        return _checkpoint_json(dict(schema=CHECKPOINT_SCHEMA, manifest=entry['manifest'],
            roles=entry['roles'], pack_sha256=program._hash(entry['pack']),
            binding=entry['binding'], basis=basis, record=entry['record'], parameters=parameters))

    @_protected
    def checkpoint(self, roles, pack):
        """Capture registered facts, including inside an unfinished fresh build.

        Parameters are ordered JSON objects {role, parm, observation} for all
        GATES followed by snippet. Observation preserves full collected facts;
        native tuples become JSON lists. The entire copy is bounded to 256 KiB.
        """
        return self._checkpoint(self._find(roles, pack))

    def _checkpoint_shape(self, checkpoint, roles, pack, binding):
        value = _checkpoint_json(checkpoint)
        fields = {'schema', 'manifest', 'roles', 'pack_sha256', 'binding', 'basis',
                  'record', 'parameters'}
        if (type(value) is not dict or set(value) != fields
                or value['schema'] != CHECKPOINT_SCHEMA or value['roles'] != roles
                or value['pack_sha256'] != program._hash(pack)):
            _fail('GEOMETRY_CHECKPOINT_INVALID')
        previous = value['binding']
        if (type(previous) is not dict or set(previous) != set(binding)
                or any(previous.get(key) != binding[key]
                       for key in ('task_id', 'task_root', 'native_version'))):
            _fail('GEOMETRY_CHECKPOINT_INVALID')
        identity = previous.get('host_identity')
        if (type(identity) is not dict or identity.get('task_id') != binding['task_id']
                or identity.get('version') != binding['native_version']
                or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or type(identity.get('scene_epoch')) is not int or identity['scene_epoch'] < 0
                or any(type(identity.get(key)) is not str or not identity[key]
                       for key in ('launch_nonce', 'session_id', 'process_generation'))):
            _fail('GEOMETRY_CHECKPOINT_INVALID')
        parameters = value['parameters']
        if (type(parameters) is not list or len(parameters) != len(program.GATES) + 1
                or any(type(item) is not dict or set(item) != {'role', 'parm', 'observation'}
                       or item['role'] != program.ROLE or item['parm'] != name
                       or type(item['observation']) is not dict
                       for name, item in zip((*program.GATES, 'snippet'), parameters))):
            _fail('GEOMETRY_CHECKPOINT_INVALID')
        return value

    @_protected
    def reopen(self, roles, pack, checkpoint):
        """Rebind verified saved facts without initializing or writing HOM state.

        Only the enclosing verified scene/lease scope can authorize recovery.
        Keep the returned token until all addon work has completed, then end it.
        """
        binding = self._binding(roles, pack)
        value = self._checkpoint_shape(checkpoint, roles, pack, binding)
        if self._call('_fx_geometry_reopen_authority', copy.deepcopy(roles),
                      copy.deepcopy(pack), copy.deepcopy(value)) is not True:
            _fail('GEOMETRY_REOPEN_AUTHORITY_REQUIRED')
        provenance = self._manifest(value['manifest'], binding, roles)
        nodes = self._nodes(roles, binding)
        if self._binding(roles, pack) != binding:
            _fail('GEOMETRY_AUTHENTICATED_HOST_REQUIRED')
        previous = [(key, entry) for key, entry in _COHORTS.items()
                    if entry['host'] is self.host and entry['hou'] is self.hou
                    and entry['binding']['task_root'] == binding['task_root']]
        if len(previous) > 1:
            _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
        if previous:
            old = previous[0][1]
            if any(transaction['entry'] is old for transaction in _TRANSACTIONS.values()):
                _fail('GEOMETRY_TRANSACTION_ACTIVE')
            if (not old['committed'] or old['roles'] != roles or old['pack'] != pack
                    or old['record'] != value['record'] or old['manifest'] != value['manifest']
                    or old['binding'] != value['binding']):
                _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
            if (old['binding'] == binding and all(old['nodes'][role][0] is node
                    and old['nodes'][role][1] == session for role, (node, session) in nodes.items())):
                _fail('GEOMETRY_CURRENT_COHORT_REPLACEMENT_REFUSED')
        elif len(_COHORTS) >= MAX_COHORTS:
            _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
        if len(_TRANSACTIONS) >= MAX_COHORTS:
            _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
        entry = dict(host=self.host, hou=self.hou, roles=copy.deepcopy(roles),
            pack=copy.deepcopy(pack), binding=binding, nodes=nodes,
            manifest=copy.deepcopy(value['manifest']), provenance=provenance,
            fresh=frozenset(), committed=False, authorized=None,
            record=copy.deepcopy(value['record']))
        self._record(entry, entry['record'])
        expected = dict(value, binding=copy.deepcopy(binding))
        token = secrets.token_hex(32)
        for key, _ in previous:
            _COHORTS.pop(key)
        _COHORTS[token] = entry
        _TRANSACTIONS[token] = dict(entry=entry, owned=True, previous=previous,
                                    checkpoint=expected)
        try:
            if self._checkpoint(entry) != expected:
                _fail('GEOMETRY_CHECKPOINT_CHANGED')
            if self._call('_fx_geometry_reopen_authority', copy.deepcopy(roles),
                          copy.deepcopy(pack), copy.deepcopy(value)) is not True:
                _fail('GEOMETRY_REOPEN_AUTHORITY_REQUIRED')
            if self._checkpoint(entry) != expected:
                _fail('GEOMETRY_CHECKPOINT_CHANGED')
            return token
        except Exception:
            self.end(token, False)
            raise

    @_protected
    def begin(self, params, roles, pack, fresh_roles):
        if (type(params) is not dict or type(fresh_roles) not in (set, frozenset, tuple, list)
                or len(fresh_roles) > MAX_COHORTS or len(set(fresh_roles)) != len(fresh_roles)
                or not set(fresh_roles) <= set(roles)):
            _fail('GEOMETRY_FRESH_COHORT_REQUIRED')
        binding = self._binding(roles, pack)
        manifest = copy.deepcopy(params.get('frozen_input_manifest'))
        provenance = self._manifest(manifest, binding, roles)
        nodes = self._nodes(roles, binding)
        if self._binding(roles, pack) != binding:
            _fail('GEOMETRY_AUTHENTICATED_HOST_REQUIRED')
        matches = [entry for entry in _COHORTS.values() if entry['host'] is self.host
                   and entry['hou'] is self.hou and entry['binding']['task_root'] == binding['task_root']]
        if matches:
            entry = self._find(roles, pack)
            self._check(entry)
            if (fresh_roles or not entry['committed'] or entry['record'] is None
                    or entry['manifest'] != manifest or entry['provenance'] != provenance):
                _fail('GEOMETRY_FRESH_COHORT_REQUIRED')
            owned = False
            self.registration('verify', roles, pack, entry['record'])
        else:
            if program.ROLE not in fresh_roles:
                _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
            for role in fresh_roles:
                node = nodes[role][0]
                if node.userData(_BASIS_KEY) is not None or node.userData(_REGISTRATION_KEY) is not None:
                    _fail('GEOMETRY_FRESH_COHORT_REQUIRED')
            if len(_COHORTS) >= MAX_COHORTS:
                _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
            entry = dict(host=self.host, hou=self.hou, roles=copy.deepcopy(roles),
                pack=copy.deepcopy(pack), binding=binding, nodes=nodes, manifest=manifest,
                provenance=provenance, fresh=frozenset(fresh_roles), committed=False,
                authorized=None, record=None)
            owned = True
        if any(transaction['entry'] is entry for transaction in _TRANSACTIONS.values()):
            _fail('GEOMETRY_TRANSACTION_ACTIVE')
        if len(_TRANSACTIONS) >= MAX_COHORTS:
            _fail('GEOMETRY_REGISTRY_BUDGET_EXCEEDED')
        token = secrets.token_hex(32)
        if owned:
            _COHORTS[token] = entry
        _TRANSACTIONS[token] = dict(entry=entry, owned=owned)
        return token

    @_protected
    def source_basis(self, roles, pack, binding):
        entry = self._find(roles, pack)
        if binding != entry['binding']:
            _fail('GEOMETRY_AUTHENTICATED_HOST_REQUIRED')
        if entry['committed'] and entry['record'] is None:
            _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
        return copy.deepcopy(self._check(entry))

    @_protected
    def source_geometry(self, node, provenance):
        matches = [entry for entry in _COHORTS.values() if entry['host'] is self.host
                   and entry['hou'] is self.hou and entry['nodes']['instance_source'][0] is node
                   and entry['provenance'] == provenance]
        if len(matches) != 1:
            _fail('GEOMETRY_REGISTERED_COHORT_REQUIRED')
        entry = matches[0]
        self.source_basis(entry['roles'], entry['pack'], entry['binding'])
        frame = program._number(self.hou.frame(), 'current native frame')
        if provenance.get('geometry_observation') != 'native_sop_read':
            _fail('GEOMETRY_SOURCE_FRAME_REQUIRED')
        observe = getattr(node, 'geometryAtFrame', None)
        if callable(observe):
            geometry = observe(provenance['frame'], output_index=provenance['output'])
        elif frame == provenance['frame']:
            geometry = node.geometry(output_index=provenance['output'])
        else:
            _fail('GEOMETRY_SOURCE_FRAME_REQUIRED')
        if frame != provenance['frame']:
            from .native_geometry_controls_host import Host
            observer = Host(self.host, hou_module=self.hou)
            source = observer._observe_source(node, geometry, provenance, provenance['frame'])
            if program.source_geometry_sha256(source) != provenance['source_geometry_sha256']:
                _fail('GEOMETRY_BASIS_CHANGED')
            observer._current_source(node, source, provenance, frame)
        if geometry is None:
            _fail('GEOMETRY_REST_SOURCE_REQUIRED')
        self._check(entry)
        if program._number(self.hou.frame(), 'current native frame') != frame:
            _fail('GEOMETRY_SOURCE_FRAME_REQUIRED')
        return geometry

    def _record(self, entry, record):
        provenance = entry['provenance']
        expected = dict(schema=program.REGISTRATION_SCHEMA, origin='runtime_hom',
            initialized=True, registered=True, generator=program.GENERATOR,
            task_id=provenance['task_id'], task_root=provenance['task_root'],
            input_version=provenance['input_version'], native_version=provenance['native_version'],
            node_path=entry['roles'][program.ROLE], basis_sha256=None,
            initial_program_sha256=hashlib.sha256(b'float deform_amplitude = 0;\n').hexdigest(),
            gates_sha256=program._hash(program.GATES))
        if type(record) is not dict or not program._digest(record.get('basis_sha256')):
            _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
        expected['basis_sha256'] = record['basis_sha256']
        if _bounded_json(record) != _bounded_json(expected):
            _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')

    @_protected
    def registration(self, action, roles, pack, record):
        """Restore authorization checks retained trust and current targets only.

        It changes no registry state and grants no forward validation authority;
        external input and carrier userData may be damaged during rollback.
        """
        entry = self._find(roles, pack)
        if action == 'authorize_restore':
            self._check_identity(entry)
            self._record(entry, record)
            if entry['record'] is None or entry['record'] != record:
                _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
            return True
        self._check(entry)
        self._record(entry, record)
        active = [transaction for transaction in _TRANSACTIONS.values()
                  if transaction['entry'] is entry and transaction['owned']]
        if action == 'authorize_fresh':
            if (len(active) != 1 or entry['committed'] or program.ROLE not in entry['fresh']
                    or entry['record'] is not None
                    or (entry['authorized'] is not None and entry['authorized'] != record)):
                _fail('GEOMETRY_FRESH_COHORT_REQUIRED')
            entry['authorized'] = copy.deepcopy(record)
        elif action == 'register':
            if len(active) != 1 or entry['committed'] or entry['authorized'] != record:
                _fail('GEOMETRY_FRESH_COHORT_REQUIRED')
            if entry['record'] is not None and entry['record'] != record:
                _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
            entry['record'] = copy.deepcopy(record)
        elif action == 'verify':
            if entry['record'] != record:
                _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
            raw = entry['nodes'][program.ROLE][0].userData(_REGISTRATION_KEY)
            if (type(raw) is not str or len(raw) > MAX_REST_BYTES
                    or json.loads(raw, object_pairs_hook=_object, parse_constant=_constant) != record):
                _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
        elif action == 'revoke':
            if entry['authorized'] != record or (entry['record'] is not None and entry['record'] != record):
                _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
            entry['record'] = None
        else:
            _fail('GEOMETRY_REGISTRATION_ACTION_REQUIRED')
        return True

    @_protected
    def end(self, token, commit):
        if type(token) is not str or type(commit) is not bool:
            _fail('GEOMETRY_TRANSACTION_REQUIRED')
        transaction = _TRANSACTIONS.get(token)
        if transaction is None or transaction['entry']['host'] is not self.host or transaction['entry']['hou'] is not self.hou:
            _fail('GEOMETRY_TRANSACTION_REQUIRED')
        entry = transaction['entry']
        if commit:
            self._check(entry)
            if entry['record'] is None:
                _fail('GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
            self.registration('verify', entry['roles'], entry['pack'], entry['record'])
            if ('checkpoint' in transaction
                    and self._checkpoint(entry) != transaction['checkpoint']):
                _fail('GEOMETRY_CHECKPOINT_CHANGED')
        if transaction['owned']:
            if commit:
                entry['committed'] = True
                entry['fresh'] = frozenset()
            else:
                _COHORTS.pop(token, None)
                for key, previous in transaction.get('previous', ()):
                    _COHORTS[key] = previous
        _TRANSACTIONS.pop(token)
        return True
