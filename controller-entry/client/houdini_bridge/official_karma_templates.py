"""恢复已认证官方工作 HIP 的参数界面，并用来源快照读取封存观测。"""
from __future__ import annotations

import hashlib
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime.render_profiles import OFFICIAL
from .official_karma_observation import checked_bytes, load_record
from .official_karma_scene import SOURCE_ROLES, IMPORT_ROLES
from .official_karma import SOP_TYPES, VERSION, canonical_sha256

TEMPLATE_SCHEMA = 'bridge.official-karma-parameter-templates/1'
MAX_TEMPLATE_BYTES = 8 * 1024 * 1024
# 固定来源运行库的依赖顺序；仅执行已由原冻结逐字节认证的这些模块。
SOURCE_RUNTIME_MODULES = ('models', 'errors', 'execution_lock', 'windows_process',
                          'platform_support', 'process_image', 'render_profiles',
                          'owned_process', 'native_scope', 'alpha_calibration')

# 来源：2026-10-28 实际捕获并通过参数和 USD 核验的 29 个完整模板组，
# outputs/Bridge-disklight-templates-20261028/parameter-templates.json 的 roles 规范摘要。
# 仅适用于 Houdini 21.0.631 的固定官方 DiskLight 原件，不开放任意模板导入。
OFFICIAL_H21_TEMPLATE_ROLES_SHA256 = '495c6f13832e7de38be693b3f3873b00d2ff4d104380ead39e196408bf6f9009'


def source_paths():
    """固定模板角色到原教程节点的映射，调用方不能指定任意节点。"""
    result = {role: '/stage/lights/backdrop_shallow/sopnet/create/' + role
              for role in SOP_TYPES}
    result.update(SOURCE_ROLES)
    result.update({role: '/stage/lights/backdrop_shallow/' + name
                   for role, name in IMPORT_ROLES.items()})
    return result


def _signed_source(configuration):
    """先验证原签名封存回执，再使用其中绑定的来源范围与工程身份。"""
    from dcc_task_runtime import owned_process
    binding = configuration.get('observation_scope', configuration['native_scope'])
    case = NativeScope(binding).scope.get('official_case', {})
    if case.get('source_contract') != configuration['source_contract']:
        raise ValueError('OFFICIAL_SOURCE_READER_CONTRACT_MISMATCH')
    sealed = configuration['sealed_observation']
    payload = owned_process.read_receipt(sealed['directory'], 'official-sealed-observation',
                                         identity=sealed['identity'])
    if (not payload or canonical_sha256(payload) != sealed['sha256']
            or payload.get('scope_binding') != binding
            or payload.get('source_contract') != configuration['source_contract']):
        raise ValueError('OFFICIAL_SOURCE_READER_SIGNED_SEAL_REQUIRED')
    return binding, case, payload


def sealed_source_hip(configuration):
    """返回原签名封存中的工作 HIP 身份，不从调用方接受任意来源工程。"""
    _binding, _case, payload = _signed_source(configuration)
    checked_bytes(payload['hip'])
    return dict(payload['hip'])


def _source_nodes(observed):
    """汇总封存观测中本次重建所需的固定角色和参数模板身份。"""
    rows = {role: observed['nodes'][path] for role, path in source_paths().items()
            if role not in IMPORT_ROLES}
    rows.update({role: observed['sopcreate_import'][name]
                 for role, name in IMPORT_ROLES.items()})
    return rows


def capture_parameter_templates(hou, configuration, source_hip_record):
    """在独立来源读取进程导出原生完整模板；本函数不加载或保存场景。"""
    from .official_karma_scene import load_observation
    observed = load_observation(configuration, VERSION)
    expected_hip = sealed_source_hip(configuration)
    if source_hip_record != expected_hip or hou.applicationVersionString() != VERSION:
        raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_SOURCE_MISMATCH')
    rows = {}
    for role, source in _source_nodes(observed).items():
        path = source_paths()[role]
        node = hou.node(path)
        if node is None or node.type().name() != source['type']:
            raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_NODE_MISMATCH:' + role)
        fields = {}
        for name, field in source['parameters'].items():
            parm = node.parmTuple(name)
            if parm is None:
                raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_FIELD_MISSING:' + role + '.' + name)
            digest = hashlib.sha256(parm.parmTemplate().asCode().encode()).hexdigest()
            if digest != field['template_sha256']:
                raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_FIELD_MISMATCH:' + role + '.' + name)
            fields[name] = digest
        dialog = node.parmTemplateGroup().asDialogScript(full_info=True)
        rows[role] = {'source_path': path, 'native_type': source['type'],
                      'dialog_lines': dialog.splitlines(keepends=True),
                      'field_templates': fields}
    checked_bytes(expected_hip)
    return {'schema': TEMPLATE_SCHEMA, 'profile': OFFICIAL, 'version': VERSION,
            'source_scope': configuration.get('observation_scope', configuration['native_scope']),
            'sealed_observation': configuration['sealed_observation'],
            'source_contract': configuration['source_contract'],
            'source_hip': expected_hip, 'roles': rows}


def validate_parameter_templates(configuration, observed=None):
    """纯数据预检模板旁车的来源、角色与字段身份，不启动 DCC。"""
    record = configuration.get('parameter_templates')
    if record is None:
        raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_RECORD_REQUIRED')
    payload = load_record(record, MAX_TEMPLATE_BYTES)
    # 整组模板内容与原生可信基准比较，不能仅相信旁车自报的字段摘要。
    if (type(payload.get('roles')) is not dict
            or canonical_sha256(payload['roles']) != OFFICIAL_H21_TEMPLATE_ROLES_SHA256):
        raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_CONTENT_MISMATCH')
    keys = {'schema', 'profile', 'version', 'source_scope', 'sealed_observation',
            'source_contract', 'source_hip', 'roles'}
    if (set(payload) != keys or payload['schema'] != TEMPLATE_SCHEMA
            or payload['profile'] != OFFICIAL or payload['version'] != VERSION
            or payload['source_scope'] != configuration.get('observation_scope', configuration['native_scope'])
            or payload['sealed_observation'] != configuration['sealed_observation']
            or payload['source_contract'] != configuration['source_contract']
            or payload['source_hip'] != sealed_source_hip(configuration)):
        raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_BINDING_MISMATCH')
    if observed is None:
        from .official_karma_scene import load_observation
        observed = load_observation(configuration, VERSION)
    expected = _source_nodes(observed)
    if type(payload['roles']) is not dict or set(payload['roles']) != set(expected):
        raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_ROLE_SET_MISMATCH')
    for role, source in expected.items():
        row = payload['roles'][role]
        if (type(row) is not dict or set(row) != {'source_path', 'native_type', 'dialog_lines', 'field_templates'}
                or row['source_path'] != source_paths()[role] or row['native_type'] != source['type']
                or row['field_templates'] != {name: field['template_sha256']
                    for name, field in source['parameters'].items()}
                or type(row['dialog_lines']) is not list or not row['dialog_lines']
                or any(type(line) is not str for line in row['dialog_lines'])):
            raise ValueError('OFFICIAL_PARAMETER_TEMPLATE_ROLE_MISMATCH:' + role)
    return payload


def _field_template_matches(parm, field):
    """比较实际叶参数的类型、分量和模板摘要，与最终读回使用同一严格条件。"""
    return (parm is not None
            and parm.parmTemplate().type().name() == field['kind']
            and len(tuple(parm)) == field['components']
            and hashlib.sha256(parm.parmTemplate().asCode().encode()).hexdigest()
            == field['template_sha256'])


def _deferred_ramp_instance(node, name, fields):
    """只延后匹配 Ramp 父模板将原生生成的合法实例，其他缺项仍需恢复模板。"""
    import re
    field = fields[name]
    for parent, source in fields.items():
        if source['kind'] != 'Ramp':
            continue
        match = re.fullmatch(re.escape(parent) + r'([1-9][0-9]*)(interp|pos|value)', name)
        if match is None or not _field_template_matches(node.parmTuple(parent), source):
            continue
        values = source['value']
        if (len(values) != 1 or type(values[0]) is not dict
                or type(values[0].get('keys')) is not list
                or not 1 <= int(match.group(1)) <= len(values[0]['keys'])):
            continue
        expected_kind = 'Menu' if match.group(2) == 'interp' else 'Float'
        if field['kind'] == expected_kind and field['components'] == 1 and not field['multiparm']:
            return True
    return False


def restore_parameter_templates(hou, configuration, roles, observed=None):
    """只给叶模板缺项或差异的角色安装已认证界面，避免改写原生 UI 文件夹。"""
    if 'parameter_templates' not in configuration:
        return ()
    if observed is None:
        from .official_karma_scene import load_observation
        observed = load_observation(configuration, VERSION)
    # 即使全部角色可跳过，也先认证完整旁车及全部来源身份。
    payload = validate_parameter_templates(configuration, observed)
    sources = _source_nodes(observed)
    installed = []
    for role, row in payload['roles'].items():
        node = hou.node(roles[role])
        fields = sources[role]['parameters']
        needs_restore = False
        for name, field in fields.items():
            parm = node.parmTuple(name)
            if _field_template_matches(parm, field):
                continue
            # Ramp 父项写入封存点数后生成子项；最终 initialize/readback 仍逐项校验。
            if parm is None and _deferred_ramp_instance(node, name, fields):
                continue
            needs_restore = True
            break
        if not needs_restore:
            continue
        group = node.parmTemplateGroup()
        group.setToDialogScript(''.join(row['dialog_lines']))
        node.setParmTemplateGroup(group)
        installed.append(role)
    return tuple(sorted(installed))


def _validate_reader_runtime(case, directory):
    """来源私有包执行原冻结依赖；未隔离变化的当前运行库仍逐字节核对。"""
    import importlib
    from pathlib import Path
    from .official_karma_observation import file_record
    # 范围和进程回执使用下方原源码副本，其余依赖仍要求当前字节等于原冻结。
    names = tuple(name for name in SOURCE_RUNTIME_MODULES
                  if name not in ('native_scope', 'owned_process', 'process_image'))
    old_root = directory.parents[3] / 'packages/dcc-task-runtime/src/dcc_task_runtime'
    freeze = case['source_freeze']
    for name in names:
        old_path = str(old_root / (name + '.py'))
        module = importlib.import_module('dcc_task_runtime.' + name)
        path = getattr(module, '__file__', None)
        if (old_path not in freeze or path is None
                or file_record(Path(path))['sha256'] != freeze[old_path]):
            raise ValueError('OFFICIAL_SOURCE_READER_RUNTIME_DRIFT:' + name)


def _source_reader_builtins(native_scope_snapshot, runtime_snapshot=None):
    """只在来源模块内重定向旧运行库导入，不替换全局模块或全局导入器。"""
    import builtins
    ordinary_import = builtins.__import__

    def source_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0:
            if runtime_snapshot is not None:
                if name == 'dcc_task_runtime' and fromlist:
                    if any(item in SOURCE_RUNTIME_MODULES for item in fromlist):
                        return runtime_snapshot
                prefix = 'dcc_task_runtime.'
                if name.startswith(prefix) and name[len(prefix):] in SOURCE_RUNTIME_MODULES:
                    module = getattr(runtime_snapshot, name[len(prefix):])
                    return module if fromlist else runtime_snapshot
            elif name == 'dcc_task_runtime.native_scope':
                return native_scope_snapshot
        return ordinary_import(name, globals, locals, fromlist, level)

    local_builtins = dict(vars(builtins))
    local_builtins['__import__'] = source_import
    return local_builtins


def _source_runtime_snapshot(alias, paths, sources):
    """构造原运行库的私有包，让其相对导入也只能使用已认证的原模块。"""
    import sys
    import types
    name = alias + '.runtime'
    package = types.ModuleType(name)
    package.__package__ = name
    # 不提供文件系统搜索路径，避免相对导入执行未预先认证的源码或 pyc。
    package.__path__ = []
    sys.modules[name] = package
    for member in SOURCE_RUNTIME_MODULES:
        module = types.ModuleType(name + '.' + member)
        module.__file__ = str(paths[member])
        module.__package__ = name
        sys.modules[module.__name__] = module
        setattr(package, member, module)
    local_builtins = _source_reader_builtins(package.native_scope, package)
    for member in SOURCE_RUNTIME_MODULES:
        module = getattr(package, member)
        module.__dict__['__builtins__'] = local_builtins
        exec(compile(sources[member], str(paths[member]), 'exec'), module.__dict__)
    return package


def read_source_observation(configuration):
    """用来源快照的已认证读取器解读旧封存；当前源码不冒充旧冻结版本。"""
    import re
    import sys
    import types
    from pathlib import Path
    from .official_karma import canonical_sha256
    from .official_karma_observation import file_record, validate_observation

    binding, case, payload = _signed_source(configuration)
    observer = case.get('observer', {})
    observer_path = Path(observer.get('path', ''))
    suffix = ('packages', 'houdini-bridge', 'src', 'houdini_bridge', 'official_karma_worker.py')
    if tuple(observer_path.parts[-5:]) != suffix:
        raise ValueError('OFFICIAL_SOURCE_READER_PATH_INVALID')
    directory = observer_path.parent
    modules = ('official_karma', 'official_karma_native', 'official_karma_observation')
    paths = {name: directory / (name + '.py') for name in modules}
    runtime_root = directory.parents[3] / 'packages/dcc-task-runtime/src/dcc_task_runtime'
    paths.update({name: runtime_root / (name + '.py') for name in SOURCE_RUNTIME_MODULES})
    freeze = case.get('source_freeze')
    if (type(freeze) is not dict or not freeze
            or any(str(path) not in freeze for path in paths.values())):
        raise ValueError('OFFICIAL_SOURCE_READER_FREEZE_INCOMPLETE')
    sources = {}
    # 在执行任何来源代码前验证整份原冻结；缺件、路径漂移和摘要不符继续拒绝。
    for filename, digest in freeze.items():
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('OFFICIAL_SOURCE_READER_FREEZE_INVALID')
        record = file_record(filename)
        if record['sha256'] != digest:
            raise ValueError('OFFICIAL_FROZEN_SOURCE_CHANGED')
        for name, path in paths.items():
            if filename == str(path):
                sources[name] = checked_bytes(record)
    if observer != file_record(observer_path):
        raise ValueError('OFFICIAL_SOURCE_READER_OBSERVER_MISMATCH')
    _validate_reader_runtime(case, directory)
    alias = '_bridge_official_source_' + canonical_sha256(
        {'scope': binding, 'freeze': freeze})
    if alias not in sys.modules:
        package = types.ModuleType(alias)
        package.__path__ = [str(directory)]
        package.__package__ = alias
        sys.modules[alias] = package
        try:
            # 原范围和回执共享私有来源包，内部相对导入也不会使用当前新实现。
            runtime_snapshot = _source_runtime_snapshot(alias, paths, sources)
            package._runtime_snapshot = runtime_snapshot
            package._native_scope_snapshot = runtime_snapshot.native_scope
            local_builtins = _source_reader_builtins(runtime_snapshot.native_scope, runtime_snapshot)
            for name in modules:
                fullname = alias + '.' + name
                module = types.ModuleType(fullname)
                module.__file__ = str(paths[name])
                module.__package__ = alias
                module.__dict__['__builtins__'] = local_builtins
                sys.modules[fullname] = module
                setattr(package, name, module)
                # 仅执行上面逐字节认证的原读取器源码，不执行 HIP 参数表达式或未认证 pyc。
                exec(compile(sources[name], str(paths[name]), 'exec'), module.__dict__)
        except Exception:
            for name in tuple(sys.modules):
                if name == alias or name.startswith(alias + '.'):
                    sys.modules.pop(name, None)
            raise
    reader = sys.modules[alias + '.official_karma_observation']
    result = reader.read_sealed(configuration['sealed_observation'], expected_scope=binding)
    return validate_observation(result, scope_binding=binding,
                                source_contract=configuration['source_contract'])
