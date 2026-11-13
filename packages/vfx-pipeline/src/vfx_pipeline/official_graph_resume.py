"""在同一已授权任务中采用认证的旧 GraphRun，只为必要下游启用当前宿主。"""
from __future__ import annotations

from contextlib import contextmanager, closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from dcc_task_runtime.canonical import canonical_sha256
from dcc_task_runtime.native_scope import NativeScope, OFFICIAL_INCREMENTAL_MODE
from dcc_task_runtime.render_profiles import OFFICIAL
from houdini_bridge.official_karma_observation import file_record, checked_bytes
from .graph_jobs import GraphJobService, _public_result
from .graph_scheduler import GraphScheduler


def _path(value):
    """控制文件只能使用绝对真实路径，禁止通过链接或路径折叠切换来源。"""
    path = Path(value)
    if (not path.is_absolute() or path != path.resolve()
            or any(item.is_symlink() for item in (path, *path.parents))):
        raise ValueError('OFFICIAL_RESUME_PATH_INVALID')
    return path


def _load(path):
    """读取控制端已定位的 JSON 原件，摘要在调用处登记和重验。"""
    return json.loads(_path(path).read_text(encoding='utf-8'))


@contextmanager
def _read_database(path):
    """只读打开既有 SQLite，保留 WAL 视图，不建表、不迁移、不更新原回执。"""
    path = _path(path)
    if not path.is_file():
        raise ValueError('OFFICIAL_RESUME_DATABASE_REQUIRED')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        yield db
    finally:
        db.close()


class _ReadOnlyScheduler(GraphScheduler):
    """复用正式启动来源核验，跳过有建表副作用的调度器构造器。"""
    def __init__(self, root):
        self.root = _path(root)
        self.path = self.root / 'graph_scheduler.sqlite3'

    def connect(self):
        return _read_database(self.path)


class _ReadOnlyJobs(GraphJobService):
    """复用正式 GraphRun 校验方法；旧作业库只允许读取已完成操作。"""
    def __init__(self, root, snapshot, scheduler_root, budget, seconds, snapshot_record):
        self.root = _path(root)
        self.jobs_dir = self.root / 'graph-jobs'
        self.db_path = self.root / 'graph_jobs.sqlite3'
        self.repo_root = _path(snapshot)
        self.resource_budget = budget
        self.job_budget_seconds = seconds
        self.scheduler = _ReadOnlyScheduler(scheduler_root)
        self._lock = threading.RLock()
        self._processes, self._process_tokens = {}, {}
        self.worker_factory = None
        self._source_snapshot_record = copy.deepcopy(snapshot_record)

    def _connect(self):
        return _read_database(self.db_path)

    def _source_catalogue(self):
        """按原快照装载封闭目录包，兼容单源旧目录及带几何相对依赖的双源目录。"""
        import ast
        import importlib.util
        import sys
        import types
        control = self.repo_root.parent
        if _snapshot(control) != self._source_snapshot_record:
            raise ValueError('OFFICIAL_RESUME_SOURCE_CATALOGUE_SNAPSHOT_CHANGED')
        rows = _load(self._source_snapshot_record['path'])['files']
        directory = self.repo_root/'packages/vfx-pipeline/src/vfx_pipeline'
        names = ['graph_catalog']
        if any(row['path'] == (directory/'geometry_graph.py').relative_to(self.repo_root).as_posix() for row in rows):
            names.insert(0,'geometry_graph')
        sources = {}
        for name in names:
            path = directory/(name+'.py')
            matches = [row for row in rows if row['path'] == path.relative_to(self.repo_root).as_posix()]
            record = file_record(_path(path))
            if len(matches) != 1 or matches[0]['sha256'] != record['sha256']:
                raise ValueError('OFFICIAL_RESUME_SOURCE_CATALOGUE_CHANGED')
            sources[name] = (path,checked_bytes(record))
        # 函数内相对导入也须由这份快照登记；空搜索路径不能回落到当前实现。
        for path,raw in sources.values():
            for node in ast.walk(ast.parse(raw,filename=str(path))):
                if isinstance(node,ast.ImportFrom) and node.level:
                    required = {node.module} if node.module else {item.name for item in node.names}
                    if node.level != 1 or not required <= sources.keys():
                        raise ValueError('OFFICIAL_RESUME_SOURCE_CATALOGUE_DEPENDENCY_REQUIRED')
        alias = '_bridge_readonly_catalogue_' + canonical_sha256(self._source_snapshot_record)
        package = types.ModuleType(alias)
        package.__package__,package.__path__ = alias,[]
        sys.modules[alias] = package
        try:
            for name,(path,raw) in sources.items():
                spec = importlib.util.spec_from_file_location(alias+'.'+name,path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module.__name__] = module
                setattr(package,name,module)
                # 执行已核字节，避免loader在校验后重新打开另一个文件。
                exec(compile(raw,str(path),'exec'),module.__dict__)
            if _snapshot(control) != self._source_snapshot_record:
                raise ValueError('OFFICIAL_RESUME_SOURCE_CATALOGUE_SNAPSHOT_CHANGED')
            return package.graph_catalog
        except BaseException:
            for name in (alias,*(alias+'.'+name for name in sources)):
                sys.modules.pop(name,None)
            raise

    def _validated_result(self, row, paths):
        """保留完整正式完成校验，仅将目录来源绑定到旧作业的封存版本。"""
        from .graph_job_worker import validate_completion
        graph = self._graph_record_for_operation(row['operation_id'])
        catalogue = self._source_catalogue()
        result = validate_completion(root=self.root,repo_root=self.repo_root,paths=paths,
            operation=dict(row),graph_record=dict(graph),scheduler=self.scheduler,
            source_catalogue=catalogue)
        if _snapshot(self.repo_root.parent) != self._source_snapshot_record:
            raise ValueError('OFFICIAL_RESUME_SOURCE_CATALOGUE_SNAPSHOT_CHANGED')
        return result

    def _worker_paths(self, operation_id, generation=None):
        generation = int(self._row(operation_id)['attempt_generation']) if generation is None else generation
        directory = _path(self.jobs_dir / operation_id / ('attempt-' + str(generation)))
        if not directory.is_dir():
            raise ValueError('OFFICIAL_RESUME_ATTEMPT_REQUIRED')
        names = {'proposal': 'proposal.json', 'graph': 'compiled.json', 'result': 'result.json',
                 'journal': 'journal.sqlite3', 'lease': 'scene_lease.sqlite3', 'error': 'error.txt',
                 'inputs': 'inputs.json', 'identity': 'worker_identity.json', 'completion': 'completion.json'}
        return {'directory': directory, **{key: directory / name for key, name in names.items()}}


def _snapshot(control):
    """逐项认证原控制快照的文件集合，路径仍指向原目录。"""
    index = file_record(control / 'snapshot-manifest.json')
    rows = _load(index['path']).get('files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('OFFICIAL_RESUME_SNAPSHOT_REQUIRED')
    seen = set()
    for row in rows:
        name = row.get('path') if isinstance(row, dict) else None
        if (not isinstance(name, str) or not name or '\\' in name or name.startswith('/')
                or any(part in ('', '.', '..') for part in name.split('/')) or name in seen):
            raise ValueError('OFFICIAL_RESUME_SNAPSHOT_PATH_INVALID')
        seen.add(name)
        record = file_record(_path(control / 'snapshot' / name))
        if record['sha256'] != row.get('sha256'):
            raise ValueError('OFFICIAL_RESUME_SNAPSHOT_CHANGED')
    return index


def _geometry_accounting_snapshot(native, record):
    """只读认证原停止票据前缀；当前账本可追加，原归档必须确实存在于完整签名链。"""
    from dcc_task_runtime.native_scope import _accounting_lock
    path = _path(record['path'])
    if not path.is_relative_to(native.root):
        raise ValueError('GEOMETRY_RESUME_ACCOUNTING_PATH_INVALID')
    raw = checked_bytes(record)
    with _accounting_lock(native.state_path):
        current = native._read()
        # _read/_load_accounted已认证完整链、anchor、当前state及每张可信停止回执。
        lines = native.journal_path.read_bytes().splitlines()
        matches = [index for index, line in enumerate(lines) if line == raw]
        if len(matches) != 1:
            raise ValueError('GEOMETRY_RESUME_ACCOUNTING_NOT_IN_JOURNAL')
        payload = native._verify_envelope(json.loads(raw))
        state = payload.get('state')
        if (set(payload) != {'seq', 'previous', 'state'} or payload.get('seq') != matches[0]
                or type(state) is not dict
                or state.get('schema') != 'bridge.native-scope-state/1'
                or state.get('scope_sha256') != native.binding['sha256']
                or state.get('task_id', native.scope['task_id']) != native.scope['task_id']
                or type(state.get('tickets')) is not list
                or state['tickets'] != current['tickets'][:len(state['tickets'])]):
            raise ValueError('GEOMETRY_RESUME_ACCOUNTING_PREFIX_MISMATCH')
        if any(ticket.get('stopped_at') is None for ticket in state['tickets']):
            raise ValueError('GEOMETRY_RESUME_ACCOUNTING_ALL_STOPS_REQUIRED')
        from time import time
        now = time()
        charges = [max(ticket['charged_seconds'], ticket['stopped_at'] - ticket['admitted_at'])
                   for ticket in state['tickets']]
        if (any(ticket['admitted_at'] > now or ticket['stopped_at'] > now + 1 for ticket in state['tickets'])
                or sum(charges) > native.scope['budget']['total_seconds']
                or any(charge > native.role_seconds(ticket['role'])
                       for ticket, charge in zip(state['tickets'], charges))):
            raise ValueError('GEOMETRY_RESUME_ACCOUNTING_BUDGET_INVALID')
    return copy.deepcopy(state)


def inspect_resume_source(preparation_path, source_operation_id=None):
    """零宿主启动重验旧成功 GraphRun、原任务回执、原范围和保存合同。"""
    from dcc_task_runtime import owned_process
    from .production_hosts import native_scope_budget
    preparation_path = _path(preparation_path)
    prep = _load(preparation_path)
    geometry = prep.get('schema') == 'bridge.geometry-execution-preparation/1'
    if (prep.get('schema') not in ('bridge.official-karma-incremental/1', 'bridge.geometry-execution-preparation/1')
            or prep.get('state') != 'PREPARED'):
        raise ValueError('OFFICIAL_RESUME_PREPARATION_REQUIRED')
    project = _path(prep['project'])
    control = project / 'control'
    if preparation_path.parent != project.parent:
        raise ValueError('OFFICIAL_RESUME_PREPARATION_LAYOUT_MISMATCH')
    checked_bytes(prep['manifest'])
    checked_bytes(prep['snapshot_manifest'])
    checked_bytes(prep['configuration'])
    manifest = _load(control / 'run.json')
    if (prep['manifest'] != file_record(control / 'run.json')
            or prep['snapshot_manifest'] != _snapshot(control)
            or manifest.get('application') != 'pipeline'
            or manifest.get('domain_pack') != ('material_lookdev_v1' if geometry else 'lighting_camera_render_v1')):
        raise ValueError('OFFICIAL_RESUME_MANIFEST_MISMATCH')
    native = NativeScope(prep['scope'])
    if geometry:
        from dcc_task_runtime.native_scope import GEOMETRY_RESOURCE_PROFILE, GEOMETRY_SCENE_PROFILE
        parts = preparation_path.relative_to(native.root).parts if preparation_path.is_relative_to(native.root) else ()
        configuration = json.loads(checked_bytes(prep['configuration']))
        if (native.resource_profile != GEOMETRY_RESOURCE_PROFILE
                or native.scope.get('scene_profile') != GEOMETRY_SCENE_PROFILE
                or len(parts) != 3 or parts[0] != 'jobs'
                or parts[2] != 'geometry-execution-preparation.json'
                or project != preparation_path.parent / 'project'
                or configuration.get('profile') != GEOMETRY_SCENE_PROFILE
                or configuration.get('supported_versions') != ['21.0.631']
                or native.scope.get('versions', {}).get('houdini') != '21.0.631'):
            raise ValueError('GEOMETRY_RESUME_SCOPE_OR_LAYOUT_MISMATCH')
        scheduler_root = _path(prep['scheduler_root'])
        if scheduler_root != native.root / 'scheduler':
            raise ValueError('GEOMETRY_RESUME_SCHEDULER_MISMATCH')
        scope_state = copy.deepcopy(prep['accounting_snapshot'])
        state = _geometry_accounting_snapshot(native, scope_state)
        # 单向绑定：prep不嵌journal摘要，journal绑定prep；返回来源再冻结journal。
        geometry_journal = preparation_path.parent / 'graph-source-journal.json'
        journal = _load(geometry_journal)
    else:
        if (native.root != project.parent or native.scope.get('scene_profile') != OFFICIAL
                or native.scope.get('execution_mode') != OFFICIAL_INCREMENTAL_MODE):
            raise ValueError('OFFICIAL_RESUME_SCOPE_MISMATCH')
        state = native.snapshot()
        # snapshot 含当前目录磁盘占用；续目录新增文件不会改变原签名记账状态。
        scope_state = file_record(native.state_path)
        if any(row.get('stopped_at') is None for row in state['tickets']):
            raise ValueError('OFFICIAL_RESUME_ALL_STOPS_REQUIRED')
        journal = _load(project.parent / 'incremental-state.json')
        scheduler_root = project.parent / 'scheduler'
    if journal.get('preparation') != file_record(preparation_path):
        raise ValueError('OFFICIAL_RESUME_JOURNAL_PREPARATION_MISMATCH')
    stage = journal.get('stages', {}).get('build_completed', {})
    receipt = stage.get('result', {})
    operation_id = receipt.get('operation_id')
    if (stage.get('state') != 'DONE' or not isinstance(operation_id, str)
            or source_operation_id is not None and source_operation_id != operation_id):
        raise ValueError('OFFICIAL_RESUME_COMPLETED_OPERATION_REQUIRED')
    host = manifest['production_host']
    budget = native_scope_budget(prep['scope'], host['resource_budget'], control / 'jobs', scheduler_root)
    jobs = _ReadOnlyJobs(control / 'jobs', control / 'snapshot', scheduler_root,
                         budget, native.role_seconds('graph-worker'), prep['snapshot_manifest'])
    row = jobs._row(operation_id)
    intent = json.loads(row['intent_json'])
    task_id, graph_id = intent['task_id'], row['graph_id']
    if geometry and task_id != native.scope['task_id']:
        raise ValueError('GEOMETRY_RESUME_TASK_MISMATCH')
    if (row['state'] != 'SUCCEEDED' or row['stop_confirmed'] != 1 or row['cancel_requested']
            or intent.get('repo_root') != str(control / 'snapshot')
            or intent.get('scheduler_root') != str(scheduler_root)
            or intent.get('native_scope_budget') != budget):
        raise ValueError('OFFICIAL_RESUME_GRAPH_OPERATION_MISMATCH')
    jobs._operation_budget(row)
    if not jobs._observed_stopped(row):
        raise ValueError('OFFICIAL_RESUME_GRAPH_STOP_UNCONFIRMED')
    paths = jobs._worker_paths(operation_id)
    raw = jobs._validated_result(row, paths)
    public = _public_result(raw, root=jobs.root, operation_id=operation_id, graph_id=graph_id,
        root_task_id=task_id, attempt_token=row['process_token'], attempt_generation=row['attempt_generation'])
    if json.loads(row['result_json']) != public:
        raise ValueError('OFFICIAL_RESUME_STORED_RESULT_MISMATCH')
    status = jobs.status(operation_id)
    if any(receipt.get(key) != value for key, value in status.items()) or receipt.get('task_id') != task_id:
        raise ValueError('OFFICIAL_RESUME_RECEIPT_MISMATCH')
    with _read_database(control / 'pipeline.sqlite3') as db:
        rows = db.execute("SELECT payload_json FROM pipeline_records WHERE task_id=? AND category='graph_trial_receipt' AND record_id=?",
                          (task_id, operation_id)).fetchall()
    if len(rows) != 1:
        raise ValueError('OFFICIAL_RESUME_TASK_RECEIPT_REQUIRED')
    trial_receipt = json.loads(rows[0]['payload_json'])
    body = dict(trial_receipt)
    receipt_hash = body.pop('receipt_hash', None)
    if (canonical_sha256(body) != receipt_hash or receipt.get('receipt_hash') != receipt_hash
            or any(body.get(key) != value for key, value in {'task_id': task_id, 'graph_id': graph_id,
                'operation_id': operation_id, 'run_id': manifest['run_id'], 'session_id': manifest['session_id'],
                'lower_state': 'SUCCEEDED', 'reconciliation_required': False,
                'cancellation_requested': False, 'stop_confirmed': True, 'success': True,
                'completed': True, 'terminal': True, 'stopped': True}.items())):
        raise ValueError('OFFICIAL_RESUME_TASK_RECEIPT_MISMATCH')
    supervisor = paths['directory'] / 'owned-supervisor'
    identity = jobs._supervisor_identity(row)
    started = owned_process.read_receipt(supervisor, 'started', identity=identity)
    stopped = owned_process.read_receipt(supervisor, 'stopped', identity=identity)
    worker_pid = _load(paths['identity'])['process_identity']['pid']
    if (not started or not stopped or stopped.get('observed_by') != 'owned_child_wait'
            or owned_process.execution_returncode(stopped) != 0
            or started.get('pid') != worker_pid or stopped.get('pid') != worker_pid):
        raise ValueError('OFFICIAL_RESUME_OWNED_STOP_REQUIRED')
    if geometry:
        original_workers = [ticket for ticket in state['tickets']
                            if ticket['role'] == 'graph-worker' and ticket['directory'] == str(supervisor)
                            and ticket['identity'] == identity]
        if (len(original_workers) != 1
                or original_workers[0]['stopped_at'] != stopped.get('observed_at')
                or original_workers[0].get('stopped_sha256') != hashlib.sha256(NativeScope._canonical(stopped)).hexdigest()):
            raise ValueError('GEOMETRY_RESUME_ACCOUNTED_WORKER_REQUIRED')
    sidecars = sorted((control / 'houdini-instances/fx_operations').glob('*.saves.json'))
    if len(sidecars) != 1:
        raise ValueError('OFFICIAL_RESUME_UNIQUE_SAVE_SIDECAR_REQUIRED')
    saves = _load(sidecars[0]).get('saves', [])
    artifact = raw['artifact']
    candidates = [item for item in saves if item.get('path') == artifact['hip_path']]
    if (len(candidates) != 1 or candidates[0].get('sha256') != artifact['hip_sha256']
            or candidates[0].get('scene_contract_sha256') != raw['verification'].get('registered_scene_contract_sha256')
            or candidates[0].get('scene_contract', {}).get('task_id') != task_id):
        raise ValueError('OFFICIAL_RESUME_SAVED_GRAPH_CONTRACT_REQUIRED')
    # 原账本允许继续追加；仅固定旧 GraphRun 本行及其原始证据，不给数据库整体封新摘要。
    evidence = [paths[name] for name in ('proposal', 'graph', 'result', 'journal', 'lease', 'inputs', 'identity', 'completion')]
    evidence += [supervisor / (name + '.json') for name in ('started', 'stopped')]
    evidence += [Path(artifact['hip_path'])]
    if geometry:
        evidence += [Path(scope_state['path']), geometry_journal]
    return {'schema': 'bridge.geometry-graph-resume-source/1' if geometry else 'bridge.official-graph-resume-source/1', 'task_id': task_id,
        'graph_id': graph_id, 'operation_id': operation_id, 'receipt': receipt,
        'preparation': file_record(preparation_path), 'scope': file_record(prep['scope']['path']),
        'scope_state_sha256': scope_state['sha256'], 'scope_state': scope_state,
        'stopped_tickets_sha256': canonical_sha256(state['tickets']), 'manifest': file_record(control / 'run.json'),
        'snapshot_manifest': prep['snapshot_manifest'], 'project': str(project), 'control': str(control),
        'jobs_root': str(jobs.root), 'scheduler_root': str(scheduler_root),
        'compiled_graph': jobs.compiled_graph(graph_id), 'operation_sha256': canonical_sha256(dict(row)),
        'trial_receipt_sha256': canonical_sha256(trial_receipt),
        'source_files': [file_record(path) for path in evidence],
        'save_sidecars': [file_record(path) for path in sidecars]}


class _VerifiedCompiledGraph:
    """只向下游版本登记提供已认证旧图，不暴露旧 propose/trial 执行能力。"""
    def __init__(self, source):
        self.source = source

    def bind_task(self, task_id):
        if task_id != self.source['task_id']:
            raise ValueError('OFFICIAL_RESUME_TASK_MISMATCH')

    def compiled_graph(self, graph_id):
        if graph_id != self.source['graph_id']:
            raise ValueError('OFFICIAL_RESUME_GRAPH_MISMATCH')
        return copy.deepcopy(self.source['compiled_graph'])


def _copy_save_sidecars(source, control):
    """逐字复制唯一已认证保存合同，不改写旧 HIP 路径、范围或任务身份。"""
    destination = control / 'houdini-instances/fx_operations'
    destination.mkdir(parents=True, exist_ok=True)
    _path(destination)
    for record in source['save_sidecars']:
        raw = checked_bytes(record)
        target = _path(destination / Path(record['path']).name)
        if target.exists():
            original, current = json.loads(raw), _load(target)
            mutable = {'saves', 'active_generation', 'active_scene'}
            old_saves, new_saves = original.get('saves'), current.get('saves')
            # 后续正规保存可以追加场景；原条目和固定头部必须原样保留且只出现一次。
            if (not isinstance(old_saves, list) or not isinstance(new_saves, list)
                    or new_saves[:len(old_saves)] != old_saves
                    or any(not isinstance(item, dict) for item in new_saves)
                    or len({item.get('path') for item in new_saves}) != len(new_saves)
                    or {key: value for key, value in original.items() if key not in mutable}
                    != {key: value for key, value in current.items() if key not in mutable}):
                raise ValueError('OFFICIAL_RESUME_SAVE_SIDECAR_CHANGED')
            # 新条目只保留；本 helper 不认证它们，后续正规 task_reopen 仍验证其合同。
        else:
            with target.open('xb') as handle:
                handle.write(raw)


def _checkpoint_task_copy(source,control):
    """检查点下游只写当前control副本；原任务库用SQLite只读backup保留WAL一致性。"""
    from dcc_task_runtime.platform_support import atomic_replace,atomic_write
    control=_path(control);origin=_path(Path(source['control'])/'pipeline.sqlite3')
    destination=_path(control/'pipeline.sqlite3');marker=_path(control/'checkpoint-task-source.json')
    if control==Path(source['control']) or origin==destination:
        raise ValueError('GEOMETRY_CHECKPOINT_TASK_COPY_REQUIRED')
    def identity(path):
        with _read_database(path) as db:
            task=db.execute('SELECT spec_json FROM pipeline_tasks WHERE task_id=?',(source['task_id'],)).fetchall()
            receipt=db.execute("SELECT payload_json FROM pipeline_records WHERE task_id=? AND category='graph_trial_receipt' AND record_id=?",(source['task_id'],source['operation_id'])).fetchall()
        if len(task)!=1 or len(receipt)!=1:
            raise ValueError('GEOMETRY_CHECKPOINT_TASK_RECEIPT_REQUIRED')
        value=json.loads(task[0][0]);trial=json.loads(receipt[0][0])
        if (value.get('domains')!=[{'identifier':'material_lookdev_v1','version':'1.0.0'}]
                or canonical_sha256(trial)!=source['trial_receipt_sha256']):
            raise ValueError('GEOMETRY_CHECKPOINT_TASK_SOURCE_CHANGED')
        return {'task_spec_sha256':canonical_sha256(value),'trial_receipt_sha256':canonical_sha256(trial)}
    expected={'schema':'bridge.geometry-checkpoint-task-source/1','task_id':source['task_id'],
        'source_control':source['control'],'source_operation_id':source['operation_id'],
        'source_graph_id':source['graph_id'],**identity(origin)}
    if marker.exists():
        if _load(marker)!=expected:raise ValueError('GEOMETRY_CHECKPOINT_TASK_SOURCE_CHANGED')
    else:
        # 首次装配时prepare_execution仅复制了初始task DB；已有下游诊断状态则不能替换。
        if (control/'diagnostic.sqlite3').exists():raise ValueError('GEOMETRY_CHECKPOINT_TASK_COPY_ALREADY_USED')
        temporary=_path(control/'checkpoint-task-pipeline.tmp.sqlite3')
        if temporary.exists():raise ValueError('GEOMETRY_CHECKPOINT_TASK_COPY_UNCONFIRMED')
        try:
            with _read_database(origin) as old,closing(sqlite3.connect(temporary)) as new:
                old.backup(new)
            temporary.chmod(0o600)
            if identity(temporary)!=identity(origin):raise ValueError('GEOMETRY_CHECKPOINT_TASK_SOURCE_CHANGED')
            atomic_replace(temporary,destination,owned_root=control)
            atomic_write(marker,(json.dumps(expected,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode(),owned_root=control)
        finally:
            if temporary.exists():temporary.unlink()
    current=identity(destination)
    if any(current[key]!=expected[key] for key in current):raise ValueError('GEOMETRY_CHECKPOINT_TASK_SOURCE_CHANGED')
    return destination


@contextmanager
def resume_graph_facade(manifest_path, source, *, repo_root, scheduler_root=None,checkpoint_task_copy=False,feedback_authority=None):
    """使用当前控制快照及原任务账本，按需启动新宿主承接已认证的旧成功图。"""
    from .service import ModelSafePipeline, TrustedExecutionControl
    from .production_hosts import ensure_hosts, validate_deployments
    from .workbuddy_assembly import (build_graph_facade, _DeferredTaskBoundary,
        production_host_client, production_nuke_client, ProductionBoundaryError)
    verified = inspect_resume_source(source['preparation']['path'], source['operation_id'])
    if verified != source:
        raise ValueError('OFFICIAL_RESUME_SOURCE_CHANGED')
    manifest_path = _path(manifest_path)
    control, snapshot = manifest_path.parent, _path(repo_root)
    if snapshot != control / 'snapshot':
        raise ValueError('OFFICIAL_RESUME_CURRENT_SNAPSHOT_LAYOUT_REQUIRED')
    _snapshot(control)
    manifest = _load(manifest_path)
    geometry = source.get('schema') == 'bridge.geometry-graph-resume-source/1'
    domain = 'material_lookdev_v1' if geometry else 'lighting_camera_render_v1'
    if (manifest.get('application') != 'pipeline' or manifest.get('domain_pack') != domain
            or manifest.get('construction_authorized') is not True):
        raise ValueError('OFFICIAL_RESUME_CURRENT_MANIFEST_INVALID')
    task_id = source['task_id']
    if checkpoint_task_copy and not geometry:raise ValueError('GEOMETRY_CHECKPOINT_SOURCE_REQUIRED')
    if feedback_authority is not None and (not checkpoint_task_copy or not geometry):
        raise ValueError('GEOMETRY_FEEDBACK_TASK_COPY_REQUIRED')
    task_database=(_checkpoint_task_copy(source,control) if checkpoint_task_copy
                   else Path(source['control'])/'pipeline.sqlite3')
    pipeline = ModelSafePipeline(task_database)
    task = pipeline.store.get_task(task_id)
    if task.get('spec', {}).get('domains') != [{'identifier': domain, 'version': '1.0.0'}]:
        raise ValueError('OFFICIAL_RESUME_TASK_DOMAIN_MISMATCH')
    configs = validate_deployments(manifest['production_host'], manifest['production_nuke'],
        controller_root=control, repo_root=snapshot, application='pipeline')
    by_kind = {item['application']: item for item in configs}
    scheduler = _path(scheduler_root) if scheduler_root is not None else (Path(source['scheduler_root']) if geometry else control / 'scheduler')
    if geometry:
        if feedback_authority is not None:
            from .geometry_feedback import verify_resume
            scope_binding=verify_resume(feedback_authority,source,control,scheduler)
            if any(config.get('native_scope')!=scope_binding for config in configs):
                raise ValueError('GEOMETRY_FEEDBACK_SCOPE_MISMATCH')
        else:
            scope_binding = {key: source['scope'][key] for key in ('path', 'sha256')}
            if (any(config.get('native_scope') != scope_binding for config in configs)
                    or scheduler != Path(source['scheduler_root'])):
                raise ValueError('GEOMETRY_RESUME_CURRENT_SCOPE_OR_SCHEDULER_MISMATCH')
    _copy_save_sidecars(source, control)

    def bind_source(boundary, kind):
        if kind == 'houdini':
            boundary.verified_jobs_root = source['jobs_root']
            boundary._verified_graph_source = {'jobs_root': source['jobs_root'], 'task_id': task_id,
                'operation_id': source['operation_id'], 'receipt_sha256': canonical_sha256(source['receipt'])}
        return boundary

    def host_factory(kind):
        bound_h, bound_n = ensure_hosts(by_kind['houdini'], by_kind['nuke'], task_id=task_id,
            controller_root=control, repo_root=snapshot, scheduler_root=scheduler,
            application='pipeline', host_kinds={kind})
        factory = production_host_client if kind == 'houdini' else production_nuke_client
        boundary = factory(bound_h if kind == 'houdini' else bound_n,
                           control / ('host-state' if kind == 'houdini' else 'nuke-state'))
        return bind_source(boundary, kind)

    def detached_factory(kind):
        state_file = control / 'production-hosts.json'
        if not state_file.is_file():
            return None
        saved = _load(state_file)
        fingerprint = hashlib.sha256(json.dumps(configs, ensure_ascii=False, sort_keys=True,
                                                allow_nan=False).encode('utf-8')).hexdigest()
        if saved.get('task_id') != task_id or saved.get('config_sha256') != fingerprint:
            raise ProductionBoundaryError('PRODUCTION_DEPLOYMENT_CHANGED')
        config = saved.get('hosts', {}).get(kind)
        if config is None:
            return None
        factory = production_host_client if kind == 'houdini' else production_nuke_client
        return bind_source(factory(config, control / ('host-state' if kind == 'houdini' else 'nuke-state')), kind)

    host = _DeferredTaskBoundary('houdini', lambda: host_factory('houdini'), lambda: detached_factory('houdini'))
    nuke = _DeferredTaskBoundary('nuke', lambda: host_factory('nuke'), lambda: detached_factory('nuke'))
    facade = build_graph_facade(manifest_path, trusted_execution=TrustedExecutionControl(pipeline),
        jobs=_VerifiedCompiledGraph(source), task_id=task_id, session_id=manifest['session_id'],
        backend='production', repo_root=snapshot, host_client=host, nuke_client=nuke,
        host_config=by_kind['houdini'], nuke_config=by_kind['nuke'],
        save_root=(control.parent if checkpoint_task_copy else Path(source['project']))/'saves')
    facade.controller_source = {'manifest_path': str(manifest_path),
        'manifest_sha256': file_record(manifest_path)['sha256'],
        'snapshot_manifest_sha256': file_record(control / 'snapshot-manifest.json')['sha256'],
        'repo_root': str(snapshot), 'backend': 'production', 'software_processes': False}
    yield facade


def inspect_nuke_resume_source(preparation_path):
    """只重验过去成功的生产、登记和消费事实，为独立 Nuke 下游固定输入。"""
    from nuke_bridge.task_host import input_artifact_registry
    preparation_path = _path(preparation_path)
    prep = _load(preparation_path)
    if prep.get('schema') != 'bridge.official-karma-incremental/1' or not isinstance(prep.get('resume_graph'), dict):
        raise ValueError('OFFICIAL_NUKE_RESUME_PREPARATION_REQUIRED')
    graph = prep['resume_graph']
    if inspect_resume_source(graph['preparation']['path'], graph['operation_id']) != graph:
        raise ValueError('OFFICIAL_NUKE_RESUME_GRAPH_CHANGED')
    native = NativeScope(prep['scope'])
    state = native.snapshot()
    if any(ticket.get('stopped_at') is None for ticket in state['tickets']):
        raise ValueError('OFFICIAL_NUKE_RESUME_ALL_STOPS_REQUIRED')
    control, project = _path(prep['control']), _path(prep['project'])
    if native.root != project.parent:
        raise ValueError('OFFICIAL_NUKE_RESUME_ROOT_MISMATCH')
    if (prep['manifest'] != file_record(control / 'run.json')
            or prep['snapshot_manifest'] != _snapshot(control)):
        raise ValueError('OFFICIAL_NUKE_RESUME_SOURCE_CHANGED')
    journal = _load(preparation_path.parent / 'incremental-state.json')
    if journal.get('preparation') != file_record(preparation_path):
        raise ValueError('OFFICIAL_NUKE_RESUME_JOURNAL_MISMATCH')
    stages = journal.get('stages', {})
    if any(stages.get(name, {}).get('state') != 'DONE' for name in ('save', 'verify', 'register', 'consume')):
        raise ValueError('OFFICIAL_NUKE_RESUME_REGISTERED_INPUT_REQUIRED')
    registered, consumed = stages['register']['result'], stages['consume']['result']
    receipt = registered.get('registry_operation_receipt')
    task_id = graph['task_id']
    if (registered.get('task_id') != task_id or consumed.get('usable_as_render_input') is not True
            or consumed.get('artifact_id') != registered.get('artifact_id')
            or not isinstance(receipt, dict) or consumed.get('registry_operation_receipt') != receipt):
        raise ValueError('OFFICIAL_NUKE_RESUME_CONSUMPTION_MISMATCH')
    saved = stages['save']['result']
    fact = stages['verify']['result']['execution_fact']
    source = {'schema': 'bridge.official-nuke-resume-source/1', 'preparation': file_record(preparation_path),
        'task_id': task_id, 'artifact_id': registered['artifact_id'], 'artifact_version': registered['version'],
        'producer_scope': file_record(prep['scope']['path']), 'producer_control': str(control),
        'producer_ledger': str(control / 'artifact_ledger'), 'producer_manifest': prep['manifest'],
        'producer_snapshot_manifest': prep['snapshot_manifest'],
        'producer_deployment': file_record(control / 'production-hosts.json'),
        'producer_owners': file_record(control / 'host-state/houdini-operation-owners.json'),
        'registry_operation_receipt': receipt, 'producer_fact_sha256': canonical_sha256(fact),
        'producer_stopped_tickets_sha256': canonical_sha256(state['tickets']),
        'source_graph': graph, 'project': str(project), 'saved_scene_id': saved['saved_scene_id'],
        'hip': file_record(saved['path']), 'main_exr': file_record(fact['metadata']['1']['path']),
        'pattern': registered['pattern']}
    # 原范围即使因后续 Nuke 配置失败关闭，也不改变已停止生产操作的真实成功事实。
    registry = input_artifact_registry(source, scope=native, task_id=task_id, require_continuation=False)
    entry = registry.lookup(source['artifact_id'])
    if (entry != registered or registry.verify_operation_receipt(receipt) != receipt
            or not registry.verify(source['artifact_id']).get('usable')):
        raise ValueError('OFFICIAL_NUKE_RESUME_REGISTERED_ENTRY_CHANGED')
    return source


class _NoHoudiniContinuation:
    """Nuke 专用续接禁止以任何命令激活或重做 Houdini。"""
    backend_kind = 'production'
    def prepare_task(self, task_id):
        self.task_id = task_id
    def bind_task(self, task_id):
        self.task_id = task_id
    def bind_artifact_registry(self, registry):
        pass
    def call(self, command, params=None):
        raise ValueError('OFFICIAL_NUKE_RESUME_HOUDINI_DISABLED')


@contextmanager
def resume_nuke_facade(manifest_path, source, *, repo_root, scheduler_root=None):
    """只启动当前 Nuke，复用原主产物 Registry 与原任务，不重做生产或登记。"""
    from .service import ModelSafePipeline, TrustedExecutionControl
    from .production_hosts import ensure_hosts, validate_deployments
    from .feedback_versions import FeedbackVersions
    from .workbuddy_assembly import (build_graph_facade, _DeferredTaskBoundary,
        production_nuke_client, ProductionBoundaryError)
    from nuke_bridge.task_host import input_artifact_registry, _input_source_payload
    if inspect_nuke_resume_source(source['preparation']['path']) != source:
        raise ValueError('OFFICIAL_NUKE_RESUME_SOURCE_CHANGED')
    manifest_path = _path(manifest_path)
    control, snapshot = manifest_path.parent, _path(repo_root)
    if snapshot != control / 'snapshot':
        raise ValueError('OFFICIAL_RESUME_CURRENT_SNAPSHOT_LAYOUT_REQUIRED')
    _snapshot(control)
    manifest = _load(manifest_path)
    if (manifest.get('application') != 'pipeline' or manifest.get('domain_pack') != 'lighting_camera_render_v1'
            or manifest.get('construction_authorized') is not True):
        raise ValueError('OFFICIAL_NUKE_RESUME_CURRENT_MANIFEST_INVALID')
    configs = validate_deployments(manifest['production_host'], manifest['production_nuke'],
        controller_root=control, repo_root=snapshot, application='pipeline')
    by_kind = {item['application']: item for item in configs}
    native = NativeScope(by_kind['nuke']['native_scope'])
    pointer = by_kind['nuke'].get('input_artifact_source')
    if pointer is None or _input_source_payload(pointer, native) != source:
        raise ValueError('OFFICIAL_NUKE_RESUME_INPUT_POINTER_MISMATCH')
    task_id, graph = source['task_id'], source['source_graph']
    registry = input_artifact_registry(source, scope=native, task_id=task_id)
    pipeline = ModelSafePipeline(Path(graph['control']) / 'pipeline.sqlite3')
    if pipeline.store.get_task(task_id).get('spec', {}).get('domains') != [
            {'identifier': 'lighting_camera_render_v1', 'version': '1.0.0'}]:
        raise ValueError('OFFICIAL_RESUME_TASK_DOMAIN_MISMATCH')
    scheduler = _path(scheduler_root) if scheduler_root is not None else control / 'scheduler'

    def host_factory():
        _bound_h, bound_n = ensure_hosts(by_kind['houdini'], by_kind['nuke'], task_id=task_id,
            controller_root=control, repo_root=snapshot, scheduler_root=scheduler,
            application='pipeline', host_kinds={'nuke'})
        return production_nuke_client(bound_n, control / 'nuke-state')

    def detached_factory():
        state_file = control / 'production-hosts.json'
        if not state_file.is_file():
            return None
        saved = _load(state_file)
        fingerprint = hashlib.sha256(json.dumps(configs, ensure_ascii=False, sort_keys=True,
                                                allow_nan=False).encode('utf-8')).hexdigest()
        if saved.get('task_id') != task_id or saved.get('config_sha256') != fingerprint:
            raise ProductionBoundaryError('PRODUCTION_DEPLOYMENT_CHANGED')
        config = saved.get('hosts', {}).get('nuke')
        return None if config is None else production_nuke_client(config, control / 'nuke-state')

    nuke = _DeferredTaskBoundary('nuke', host_factory, detached_factory)
    facade = build_graph_facade(manifest_path, trusted_execution=TrustedExecutionControl(pipeline),
        jobs=_VerifiedCompiledGraph(graph), task_id=task_id, session_id=manifest['session_id'],
        backend='production', repo_root=snapshot, host_client=_NoHoudiniContinuation(), nuke_client=nuke,
        registry=registry, host_config=by_kind['houdini'], nuke_config=by_kind['nuke'],
        save_root=Path(source['project']) / 'saves')
    facade.controller_source = {'manifest_path': str(manifest_path),
        'manifest_sha256': file_record(manifest_path)['sha256'],
        'snapshot_manifest_sha256': file_record(control / 'snapshot-manifest.json')['sha256'],
        'repo_root': str(snapshot), 'backend': 'production', 'software_processes': False}
    FeedbackVersions(facade).register_completed(graph['graph_id'], graph['compiled_graph'])
    yield facade
