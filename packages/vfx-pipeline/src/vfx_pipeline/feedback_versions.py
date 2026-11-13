"""Durable graph feedback versions backed by the existing run database."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class FeedbackVersions:
    def __init__(self, run):
        self.run = run
        with run._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS feedback_versions (
                graph_id TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(graph_id,version))''')

    def current(self, graph_id):
        with self.run._connect() as db:
            row = db.execute('SELECT version,state,payload FROM feedback_versions WHERE graph_id=? ORDER BY version DESC LIMIT 1', (graph_id,)).fetchone()
        return {'version': row[0], 'state': row[1], **json.loads(row[2])} if row else None

    def completed_revision_chain(self, graph_id, from_version, to_version):
        """在单个稳定读事务中认证原注册图及连续反馈行，不修改版本或生产事实。"""
        from dcc_task_runtime.canonical import canonical_sha256
        from dcc_task_runtime.artifact_registry import validate_feedback_revision_chain
        if (type(from_version) is not int or type(to_version) is not int
                or from_version < 0 or to_version <= from_version):
            raise ValueError('FEEDBACK_REVISION_CHAIN_RANGE_INVALID')
        jobs = getattr(self.run, 'jobs_service', None) or self.run.jobs
        with self.run._connect() as db:
            registered_path = getattr(jobs, 'db_path', None)
            if registered_path is not None:
                from pathlib import Path
                # 普通注册图和反馈行在同一SQLite读事务内取得，不能拼接两个时点。
                db.execute('ATTACH DATABASE ? AS feedback_registered_graph',
                           (Path(registered_path).resolve().as_uri() + '?mode=ro',))
            db.execute('BEGIN')
            rows = db.execute('SELECT version,state,payload FROM feedback_versions WHERE graph_id=? ORDER BY version',
                              (str(graph_id),)).fetchall()
            if registered_path is not None:
                row = db.execute('SELECT compiled_json FROM feedback_registered_graph.graphs WHERE graph_id=?',
                                 (str(graph_id),)).fetchone()
                if row is None:
                    raise ValueError('FEEDBACK_REVISION_REGISTERED_GRAPH_REQUIRED')
                registered = json.loads(row[0])
            else:
                # 恢复装配提供已认证且不可变的_VerifiedCompiledGraph，不读取可变外部图库。
                registered = jobs.compiled_graph(graph_id)
            chain = {'schema':'bridge.feedback-revision-chain/1', 'task_id':self.run.pipeline_task_id,
                'graph_id':str(graph_id), 'from_version':from_version, 'to_version':to_version,
                'registered_graph':registered,
                'rows':[{'version':row[0], 'state':row[1], 'payload':json.loads(row[2])} for row in rows]}
            chain['chain_sha256'] = canonical_sha256(chain)
            validate_feedback_revision_chain(chain, task_id=self.run.pipeline_task_id, graph_id=str(graph_id),
                                            from_version=from_version, to_version=to_version)
        return chain

    def register_completed(self, graph_id, compiled):
        payload = {'compiled': compiled, 'graph_hash': compiled['graph_hash'],
                   'base_graph_hash': compiled['graph_hash'], 'invalidated_nodes': [],
                   'invalidated_outputs': [], 'task_id': self.run.pipeline_task_id}
        with self.run._connect() as db:
            db.execute('INSERT OR IGNORE INTO feedback_versions VALUES(?,?,?,?)',
                       (graph_id, 0, 'COMPLETE', json.dumps(payload)))

    def apply(self, graph_id, compiled, path, node_id, parms, client, *, domain_candidate=None):
        parms = json.loads(json.dumps(parms, allow_nan=False))
        previous = self.current(graph_id)
        if previous and previous.get('domain_candidate') is not None:
            self._verify_domain_candidate(previous)
        if previous and previous['state'] != 'COMPLETE':
            actual = self._readback(previous, client)
            actual = json.loads(json.dumps(actual, allow_nan=False))
            if previous['state'] == 'PREPARED':
                if actual != previous['before']:
                    raise ValueError('prepared feedback source changed; reconciliation required')
                self._execute(graph_id, previous['version'], previous, client)
            else:
                if previous.get('producer_request') is not None:
                    self._finish_dispatched(graph_id, previous['version'], previous, client, recover=True)
                else:
                    if actual != previous['after']:
                        raise ValueError('feedback execution requires reconciliation; no edit replay is permitted')
                    self._complete(graph_id, previous['version'], previous, client)
            previous = self.current(graph_id)
        before = self._readback({'path': path, 'domain_candidate': domain_candidate}, client)
        if not isinstance(before, dict) or any(key not in before for key in parms):
            raise ValueError('feedback requires actual native parameter readback')
        before = json.loads(json.dumps(before, allow_nan=False))
        if previous and all(before.get(key) == value for key, value in parms.items()):
            return {'path': path, 'values': dict(parms), **previous, 'replayed': True}
        source = json.loads(json.dumps(previous['compiled'] if previous else compiled, allow_nan=False))
        version = previous['version'] + 1 if previous else 1
        affected = {str(node_id)}
        addresses = {str(node.get('address')): str(node['node_id']) for node in source['nodes']}
        changed = True
        while changed:
            changed = False
            for edge in source.get('connections') or []:
                left = addresses.get(edge['source_node'], edge['source_node'])
                right = addresses.get(edge['target_node'], edge['target_node'])
                if left in affected and right not in affected:
                    affected.add(right); changed = True
        outputs = [row['output_id'] for row in source.get('outputs') or []
                   if addresses.get(row['node_id'], row['node_id']) in affected]
        for node in source['nodes']:
            if str(node['node_id']) == str(node_id):
                node['parameters'] = {**node.get('parameters', {}), **dict(parms)}
        after = {**before, **parms}
        payload = {'compiled': source, 'path': path, 'node_id': node_id, 'before': before,
                   'after': after, 'graph_hash': digest(source),
                   'base_graph_hash': compiled['graph_hash'],
                   'invalidated_nodes': sorted(affected), 'invalidated_outputs': sorted(outputs),
                   'task_id': self.run.pipeline_task_id}
        if domain_candidate is not None:
            payload['domain_candidate'] = json.loads(json.dumps(domain_candidate, allow_nan=False))
            payload['domain_candidate_sha256'] = digest(domain_candidate)
            self._verify_domain_candidate(payload)
        if domain_candidate is not None and domain_candidate.get('readback_kind') == 'rbd_initial_velocity':
            operation_id = 'feedback-' + digest([self.run.pipeline_task_id, graph_id, version, payload])
            payload['producer_request'] = {**payload['domain_candidate']['request'],
                'operation_id': operation_id, 'request_id': operation_id, 'frozen_input_manifest': []}
        # Persist intent before the host mutation. A restart may confirm this
        # exact readback; it cannot infer success from an absent process.
        with self.run._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT MAX(version) FROM feedback_versions WHERE graph_id=?', (graph_id,)).fetchone()[0]
            if (latest or 0) != version - 1:
                raise ValueError('feedback version changed concurrently')
            db.execute('INSERT INTO feedback_versions VALUES(?,?,?,?)', (graph_id, version, 'PREPARED', json.dumps(payload)))
        result = self._execute(graph_id, version, payload, client)
        return {**result, **self.current(graph_id), 'replayed': False}

    def _readback(self, payload, client):
        candidate = payload.get('domain_candidate') or {}
        if candidate.get('readback_kind') != 'rbd_initial_velocity':
            return client.call('node.parms', self._readback_request(payload)).get('parms')
        result = client.call('agent.fx.inspect_controls', {
            'task_id': candidate['task_id'],
            'bridge_execution_binding': {'execution_root': candidate['execution_root']},
            'constraints': {'fx': {'domain_pack': 'rbd_destruction_v1', 'run_mode': 'diagnose'}},
            'controls': ['velocity_variance']})
        controls = result.get('controls')
        if (result.get('task_id') != candidate['task_id']
                or result.get('execution_root') != candidate['execution_root']
                or result.get('domain_pack') != 'rbd_destruction_v1'
                or result.get('node_path') != payload['path']
                or result.get('readback_verified') is not True
                or not isinstance(controls, dict) or set(controls) != {'velocity_variance'}):
            raise ValueError('RBD feedback requires trusted registered-node semantic readback')
        from houdini_bridge import native_flip_rbd_domains as rbd
        rbd.conditional_runtime_route(rbd.RBD, 'velocity_variance', controls['velocity_variance'],
                                     candidate['identity']['houdini_version'])
        return controls

    @staticmethod
    def _readback_request(payload):
        request = {'path': payload['path']}
        if payload.get('domain_candidate') is not None:
            request['names'] = payload['domain_candidate']['readback_names']
        return request

    def _verify_domain_candidate(self, payload):
        candidate = payload.get('domain_candidate')
        if (not isinstance(candidate, dict) or digest(candidate) != payload.get('domain_candidate_sha256')
                or candidate.get('task_id') != self.run.pipeline_task_id
                or candidate.get('base_graph_hash') != payload.get('base_graph_hash')
                or candidate.get('node_path') != payload.get('path')):
            raise ValueError('persisted native feedback plan changed; reconciliation required')

    def _execute(self, graph_id, version, payload, client):
        if payload.get('domain_candidate') is not None:
            self._verify_domain_candidate(payload)
        registry = self.run.artifact_registry
        if registry is not None:
            tags = ['graph:{}:{}:node:{}'.format(self.run.pipeline_task_id, graph_id, item)
                    for item in payload['invalidated_nodes']]
            tags += ['graph:{}:{}:output:{}'.format(self.run.pipeline_task_id, graph_id, item)
                     for item in payload['invalidated_outputs']]
            registry.invalidate_dependencies(tags, reason='graph {} version {}'.format(graph_id, version))
        # Only PREPARED is known not to have reached the host. Once dispatched,
        # a restart must read back the exact result instead of repeating edits.
        with self.run._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE feedback_versions SET state=? WHERE graph_id=? AND version=? AND state=?',
                                ('DISPATCHED', graph_id, version, 'PREPARED')).rowcount
            if changed != 1:
                raise ValueError('feedback dispatch owner changed; reconciliation required')
        return self._finish_dispatched(graph_id, version, payload, client)

    def _finish_dispatched(self, graph_id, version, payload, client, *, recover=False):
        edits = {key: value for key, value in payload['after'].items() if payload['before'].get(key) != value}
        candidate = payload.get('domain_candidate')
        if candidate is None:
            result = client.call('node.set_parms', {'path': payload['path'], 'parms': edits, 'task_id': self.run.pipeline_task_id})
        else:
            request = payload.get('producer_request')
            if request is None:
                result = client.call('agent.fx.apply_candidate', candidate['request'])
            else:
                result = self._producer_result(payload, client, recover=recover)
            diffs = result.get('parameter_diff') or []
            if ({item.get('semantic_control') for item in diffs} != set(candidate['controls'])
                    or any(item.get('readback_verified') is not True or item.get('node') != payload['path'] for item in diffs)):
                raise ValueError('native feedback transaction has no exact registered-node readback')
        actual = self._readback(payload, client)
        actual = json.loads(json.dumps(actual, allow_nan=False))
        if actual != payload['after']:
            raise ValueError('feedback readback mismatch, including protected unrelated parameters')
        self._complete(graph_id, version, payload, client)
        return result

    def _producer_result(self, payload, client, *, recover):
        request = payload['producer_request']
        query = None
        if recover:
            query = client.call('agent.fx.operation_receipt', {
                'task_id': self.run.pipeline_task_id, 'operation_id': request['operation_id']})
            if (query.get('task_id') != self.run.pipeline_task_id
                    or query.get('operation_id') != request['operation_id']
                    or 'operation_receipt' not in query):
                raise ValueError('feedback producer query binding changed; reconciliation required')
            record = query['operation_receipt']
        else:
            record = None
        if record is None:
            record = client.call('agent.fx.apply_candidate', request).get('operation_receipt')
            query = None
        from houdini_bridge.operation_receipts import validate_operation_receipt
        validate_operation_receipt(record, require_completed=False)
        if (record['command'] != 'agent.fx.apply_candidate'
                or record['task_id'] != self.run.pipeline_task_id or record['request'] != request
                or record['operation_id'] != request['operation_id']
                or record['request_id'] != request['request_id'] or record['state'] != 'COMPLETED'):
            raise ValueError('feedback producer attempt is unproven; reconciliation required')
        if query is not None and (query.get('current_host_identity') != record['host_identity']
                                  or query.get('current_scene') != record['after_scene']):
            raise ValueError('feedback producer scene changed; reconciliation required')
        return record['result']

    def _complete(self, graph_id, version, payload, client):
        actual = json.loads(json.dumps(self._readback(payload, client), allow_nan=False))
        if actual != payload['after']:
            raise ValueError('feedback completion readback changed; reconciliation required')
        frozen = {key: value for key, value in payload.items() if key not in {'version', 'state'}}
        with self.run._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,payload FROM feedback_versions WHERE graph_id=? AND version=?',
                             (graph_id, version)).fetchone()
            if row is None or json.loads(row[1]) != frozen:
                raise ValueError('feedback completion payload changed; reconciliation required')
            if row[0] == 'COMPLETE':
                return
            changed = db.execute('UPDATE feedback_versions SET state=? WHERE graph_id=? AND version=? AND state=?',
                                 ('COMPLETE', graph_id, version, 'DISPATCHED')).rowcount
            if changed != 1:
                raise ValueError('feedback completion owner changed; reconciliation required')
            self.run._event(db, 'feedback_version_committed', {'graph_id': graph_id, 'version': version,
                'graph_hash': payload['graph_hash'], 'invalidated_nodes': payload['invalidated_nodes'],
                'invalidated_outputs': payload['invalidated_outputs']})

    def dependencies(self):
        with self.run._connect() as db:
            rows = db.execute('SELECT graph_id,version,state,payload FROM feedback_versions ORDER BY version DESC').fetchall()
        dependencies, seen = [], set()
        for graph_id, version, state, encoded in rows:
            if graph_id in seen:
                continue
            seen.add(graph_id)
            if state != 'COMPLETE':
                raise ValueError('pending feedback cannot produce a new artifact')
            payload = json.loads(encoded)
            for output in payload['compiled'].get('outputs') or []:
                dependencies.append('graph:{}:{}:output:{}'.format(self.run.pipeline_task_id, graph_id, output['output_id']))
            dependencies.append('graph:{}:{}:version:{}'.format(self.run.pipeline_task_id, graph_id, version))
        return dependencies
