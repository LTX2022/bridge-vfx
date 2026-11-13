"""固定官方 DiskLight 的受限原生分阶段构造及合并读回；不提供任意图快路径。"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_INCREMENTAL_MODE
from dcc_task_runtime.render_profiles import OFFICIAL
from . import graph_catalog

PROTOCOL = 'bridge.official-native-batch/1'
_IDENTITY = {'schema': 'bridge.registered-domain-construction/1',
             'domain_pack': 'lighting_camera_render_v1', 'houdini_version': '21.0.631',
             'scene_profile': OFFICIAL}


def selected_plan(job, compiled, root):
    """仅由可信作业范围和固定编译结果选择批量协议，结果自述不能选择验证方式。"""
    budget = job.get('native_scope_budget') or {}
    binding = budget.get('native_scope')
    if binding is None:
        return None
    scope = NativeScope(binding)
    if scope.scope.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE:
        return None
    schedule = graph_catalog.bounded_domain_schedule(compiled)
    if (scope.scope.get('scene_profile') != OFFICIAL or schedule is None
            or schedule.get('identity') != _IDENTITY
            or any(node.parameters for node in compiled.nodes)
            or schedule.get('creation_parameters')):
        raise ValueError('OFFICIAL_BATCH_REGISTERED_GRAPH_REQUIRED')
    task_id = str(job.get('task_id') or job.get('operation_id') or '')
    expected_root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(
        (task_id + ':' + compiled.graph_hash).encode()).hexdigest()
    if root != expected_root:
        raise ValueError('OFFICIAL_BATCH_ROOT_MISMATCH')
    layout = graph_catalog.native_layout(compiled, root)
    if (set(layout) != set(compiled.execution_order)
            or any(not row['path'].startswith(root + '/') or '..' in row['path'].split('/')
                   or row['parent'] != root and not row['parent'].startswith(root + '/')
                   for row in layout.values())):
        raise ValueError('OFFICIAL_BATCH_LAYOUT_OUTSIDE_ROOT')
    stages = schedule['stages']
    nodes, connections = [], []
    for index, stage in enumerate(stages):
        if (stage.get('index') != index or len(stage['nodes']) > 8
                or len(stage['connections']) > 16):
            raise ValueError('OFFICIAL_BATCH_STAGE_BOUNDS_INVALID')
        nodes.extend(stage['nodes'])
        connections.extend(stage['connections'])
    if (len(nodes) != len(set(nodes)) or set(nodes) != set(layout)
            or len(connections) != len(set(connections))
            or set(connections) != set(range(len(compiled.connections)))):
        raise ValueError('OFFICIAL_BATCH_STAGE_COVERAGE_INVALID')
    return {'schema': PROTOCOL, 'schedule': schedule, 'layout': layout,
            'root': root, 'task_id': task_id, 'graph_hash': compiled.graph_hash}


def marker(plan):
    """合并采集的证明范围显式绑定本图及其固定阶段计划。"""
    return {'schema': PROTOCOL, 'profile': OFFICIAL, 'graph_hash': plan['graph_hash'],
            'schedule_sha256': plan['schedule']['schedule_sha256']}


def operations(job, compiled, root):
    """worker 和完成读取器共用同一操作合同；旧图仍按原单节点合同核对。"""
    from .graph_trial import GraphExecutor
    plan = selected_plan(job, compiled, root)
    legacy = GraphExecutor._operations(compiled, root)
    if plan is None:
        return legacy
    result = [legacy[0]]
    for stage in plan['schedule']['stages']:
        operation_id = compiled.graph_hash + ':official-batch:' + str(stage['index'])
        result.append((operation_id, {'kind': 'official.native_batch', **marker(plan),
            'stage_index': stage['index'], 'nodes': list(stage['nodes']),
            'connections': list(stage['connections'])}))
    result.extend((key, value) for key, value in legacy if value.get('kind') == 'domain.initialize')
    return result


def _connection(compiled, plan, index):
    connection = compiled.connections[index]
    source = plan['layout'][connection.source_node]['path']
    target = plan['layout'][connection.target_node]['path']
    binding = graph_catalog.connection_binding(compiled, connection)
    if binding.get('input_name') or binding.get('output_name'):
        raise ValueError('OFFICIAL_BATCH_NAMED_PORT_UNSUPPORTED')
    if binding['kind'] == 'reference':
        return {'source': source, 'destination': target,
                'kind': 'container_dependency' if binding['field'].startswith('@') else 'reference',
                'field': binding['field']}
    entry = {'source': source, 'destination': target, 'input_index': binding['input_index']}
    if binding['output_index']:
        entry['output_index'] = binding['output_index']
    return entry


def expected_snapshot(compiled, plan, addresses, connection_indices):
    """由可信编译图推导目标结构与引用值，禁止把实际输出反向当成期望。"""
    addresses = set(addresses)
    layout = plan['layout']
    rows = {address: {'path': layout[address]['path'], 'parent': layout[address]['parent'],
        'type': layout[address]['type'],
        'category': 'Object' if layout[address]['category'] == 'Obj' else layout[address]['category'],
        'inputs': [], 'parameters': {}} for address in addresses}
    by_path = {row['path']: row for row in rows.values()}
    for index in connection_indices:
        entry = _connection(compiled, plan, index)
        if entry['source'] not in by_path or entry['destination'] not in by_path:
            raise ValueError('OFFICIAL_BATCH_CONNECTION_BEFORE_NODE')
        target = by_path[entry['destination']]
        if entry.get('kind') == 'reference':
            target['parameters'][entry['field']] = entry['source']
        elif 'kind' not in entry:
            target['inputs'].append({'input_index': entry['input_index'],
                'source': entry['source'], 'output_index': entry.get('output_index', 0)})
    for row in rows.values():
        row['inputs'].sort(key=lambda item: (item['input_index'], item['source'], item['output_index']))
    return {'schema': PROTOCOL, 'root': plan['root'],
            'root_type': graph_catalog.native_root_type(compiled),
            'nodes': sorted(rows.values(), key=lambda row: row['path'])}


def capture_native(hou, compiled, plan, addresses, connection_indices, *, check_errors=False):
    """一次读取公共节点树、实际类型、父级、端口连接和引用参数；不促发未初始化 LOP cook。"""
    expected = expected_snapshot(compiled, plan, addresses, connection_indices)
    root = hou.node(plan['root'])
    if (root is None or root.path() != plan['root'] or root.type().name() != expected['root_type']
            or root.parent().path() != '/obj'):
        raise ValueError('OFFICIAL_BATCH_NATIVE_ROOT_MISMATCH')
    actual_nodes = tuple(root.allSubChildren(recurse_in_locked_nodes=False,
                                             sync_delayed_definition=False))
    by_path = {node.path(): node for node in actual_nodes}
    if len(by_path) != len(actual_nodes) or set(by_path) != {row['path'] for row in expected['nodes']}:
        raise ValueError('OFFICIAL_BATCH_NATIVE_NODE_SET_MISMATCH')
    actual = []
    for wanted in expected['nodes']:
        node = by_path[wanted['path']]
        row = {'path': node.path(), 'parent': node.parent().path(), 'type': node.type().name(),
               'category': node.type().category().name(), 'inputs': [], 'parameters': {}}
        for connection in node.inputConnections():
            source = connection.inputNode()
            if source is None:
                raise ValueError('OFFICIAL_BATCH_NATIVE_CONNECTION_INVALID')
            row['inputs'].append({'input_index': connection.inputIndex(), 'source': source.path(),
                                  'output_index': connection.outputIndex()})
        row['inputs'].sort(key=lambda item: (item['input_index'], item['source'], item['output_index']))
        for name in wanted['parameters']:
            parm = node.parm(name)
            if parm is None:
                raise ValueError('OFFICIAL_BATCH_NATIVE_REFERENCE_MISSING')
            row['parameters'][name] = parm.eval()
        if check_errors and node.errors():
            raise ValueError('OFFICIAL_BATCH_NATIVE_NODE_ERRORS')
        actual.append(row)
    snapshot = {**expected, 'nodes': actual}
    if snapshot != expected:
        raise ValueError('OFFICIAL_BATCH_NATIVE_LAYOUT_MISMATCH')
    return snapshot


def _apply_stage(hou, compiled, plan, stage, check_budget):
    """在调用方持有的三层围栏内执行明确阶段，精确类型与 HDA 同步沿用原创建行为。"""
    nodes = {node.address: node for node in compiled.nodes}
    for address in stage['nodes']:
        check_budget()
        row, node = plan['layout'][address], nodes[address]
        if hou.node(row['path']) is not None:
            raise ValueError('OFFICIAL_BATCH_NODE_NOT_FRESH')
        parent = hou.node(row['parent'])
        if parent is None:
            raise ValueError('OFFICIAL_BATCH_PARENT_MISSING')
        child = parent.createNode(row['type'], node.node_id, exact_type_name=True)
        if (child.path() != row['path'] or child.type().name() != row['type']
                or child.parent().path() != row['parent']):
            raise ValueError('OFFICIAL_BATCH_CREATED_NODE_MISMATCH')
        if child.isDelayedDefinition():
            child.syncDelayedDefinition()
        child.allSubChildren(recurse_in_locked_nodes=True, sync_delayed_definition=True)
    for index in stage['connections']:
        check_budget()
        entry = _connection(compiled, plan, index)
        source, target = hou.node(entry['source']), hou.node(entry['destination'])
        if source is None or target is None:
            raise ValueError('OFFICIAL_BATCH_CONNECTION_NODE_MISSING')
        if entry.get('kind') == 'reference':
            parm = target.parm(entry['field'])
            if parm is None:
                raise ValueError('OFFICIAL_BATCH_NATIVE_REFERENCE_MISSING')
            parm.deleteAllKeyframes()
            parm.set(entry['source'])
        elif 'kind' not in entry:
            target.setInput(entry['input_index'], source, entry.get('output_index', 0))


def _journal_action(journal, operation_id, intent, callback):
    """一次真实阶段对应一条新协议记录，部分副作用失败绝不标为 COMPLETE。"""
    pending = {'operation_id': operation_id, 'status': 'INTENT', 'intent': intent}
    if not journal.claim(operation_id, pending):
        raise ValueError('OFFICIAL_BATCH_JOURNAL_RECONCILIATION_REQUIRED')
    try:
        result = callback()
        if not isinstance(result, Mapping):
            raise ValueError('OFFICIAL_BATCH_RESULT_INVALID')
    except BaseException:
        journal.write(operation_id, {**pending, 'status': 'UNKNOWN',
                                     'error_code': 'OFFICIAL_BATCH_STAGE_INCOMPLETE'})
        raise
    journal.write(operation_id, {**pending, 'status': 'COMPLETE', 'result': dict(result)})
    return dict(result)


def execute(worker, compiled, journal, *, native_api=None):
    """仅供已验证 worker 调用；根沿 typed dispatch，阶段使用真实原生 API 与持久围栏。"""
    if native_api is None:
        import hou as native_api
    plan = selected_plan(worker.job, compiled, worker.lease.root)
    if plan is None:
        raise ValueError('OFFICIAL_BATCH_SCOPE_REQUIRED')
    declared = operations(worker.job, compiled, plan['root'])
    if any(journal.read(key) is not None for key, _ in declared):
        raise ValueError('OFFICIAL_BATCH_JOURNAL_RECONCILIATION_REQUIRED')
    if native_api.node(plan['root']) is not None:
        raise ValueError('OFFICIAL_BATCH_ROOT_NOT_FRESH')
    root_id, root_intent = declared[0]
    root_type = graph_catalog.native_root_type(compiled)
    created = _journal_action(journal, root_id, root_intent, lambda: worker._fenced_dispatch(
        'scene.create_task_root', {'task_id': worker.execution_task_id, 'parent': '/obj',
            'type': root_type, 'root_layout': 'object_subnet/1' if root_type == 'subnet' else 'sop_geo/1',
            'root_name': plan['root'].rsplit('/', 1)[1]}))
    if created.get('path') != plan['root'] or created.get('type') != root_type or created.get('reused'):
        raise ValueError('OFFICIAL_BATCH_CREATED_ROOT_MISMATCH')
    addresses, connected = set(), []
    for stage in plan['schedule']['stages']:
        operation_id, intent = declared[1 + stage['index']]
        before_addresses, before_connected = set(addresses), list(connected)
        after_addresses = addresses | set(stage['nodes'])
        after_connected = connected + list(stage['connections'])
        def apply():
            with worker._official_batch_fence():
                before = capture_native(native_api, compiled, plan, before_addresses, before_connected)
                _apply_stage(native_api, compiled, plan, stage, worker._check_budget)
                after = capture_native(native_api, compiled, plan, after_addresses, after_connected)
                return {'schema': PROTOCOL, 'stage_index': stage['index'],
                        'before': before, 'after': after, 'native_api': 'hou'}
        _journal_action(journal, operation_id, intent, apply)
        addresses, connected = after_addresses, after_connected
    return {'task_id': worker.execution_task_id, 'graph_hash': compiled.graph_hash,
        'construction_executed': True, 'reconciliation_required': False, 'visual_verified': False,
        'construction_protocol': PROTOCOL,
        'topology': {'root': plan['root'],
            'nodes': {address: row['path'] for address, row in plan['layout'].items()},
            'connections': [_connection(compiled, plan, index) for index in connected]}}


def validate_stage_evidence(job, compiled, root, entries):
    """完成读取器逐阶段核对可信计划及原生读回，不能由结果字段切换成较弱验证。"""
    plan = selected_plan(job, compiled, root)
    if plan is None:
        return None
    addresses, connected = set(), []
    for stage in plan['schedule']['stages']:
        operation_id = compiled.graph_hash + ':official-batch:' + str(stage['index'])
        entry = entries.get(operation_id) or {}
        expected_before = expected_snapshot(compiled, plan, addresses, connected)
        addresses.update(stage['nodes'])
        connected.extend(stage['connections'])
        expected_after = expected_snapshot(compiled, plan, addresses, connected)
        result = entry.get('result') or {}
        if (entry.get('status') != 'COMPLETE' or result.get('schema') != PROTOCOL
                or result.get('stage_index') != stage['index'] or result.get('native_api') != 'hou'
                or result.get('before') != expected_before or result.get('after') != expected_after):
            raise ValueError('OFFICIAL_BATCH_STAGE_EVIDENCE_MISMATCH')
    return marker(plan)


def verify_reopened(worker, compiled, hip_path, hip_sha256):
    """冷开后一次真实读完整拓扑、引用与错误状态；封存参数及 USD 仍由原重开合同核验。"""
    import hou
    plan = selected_plan(worker.job, compiled, worker.lease.root)
    if plan is None:
        raise ValueError('OFFICIAL_BATCH_SCOPE_REQUIRED')
    with worker._official_batch_fence():
        capture_native(hou, compiled, plan, set(plan['layout']),
            [index for stage in plan['schedule']['stages'] for index in stage['connections']],
            check_errors=True)
    return {'hip_path': str(hip_path), 'hip_sha256': hip_sha256, 'root': plan['root'],
            'nodes_verified': True, 'parameters_verified': True, 'connections_verified': True,
            'native_batch_scope': marker(plan)}
