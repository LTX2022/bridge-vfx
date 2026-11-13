import dataclasses
import hashlib
import unittest
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from vfx_pipeline.scene_lease import SceneLease, SceneLeaseGuard, SceneLeaseStore
from vfx_pipeline.graph_trial import GraphExecutor
from test_graph_trial import FakeHoudiniClient, Journal, graph


class SceneLeaseTests(unittest.TestCase):
    def setUp(self):
        self.graph = graph()
        self.root = '/obj/BRIDGE_GRAPH_' + hashlib.sha256(('task:' + self.graph.graph_hash).encode()).hexdigest()
        self.lease = SceneLease('task', 'session', 'process-1', 'scene', self.root, 1, 200)
        self.current = self.lease
        self.identity = {'session_id': 'session', 'process_generation': 'process-1', 'scene_id': 'scene'}
        self.guard = SceneLeaseGuard(self.lease, lambda: self.current, lambda: self.identity, clock=lambda: 100)

    def test_no_guard_never_calls_host(self):
        client = FakeHoudiniClient()
        result = GraphExecutor(client, Journal()).execute('task', self.graph)
        self.assertEqual(result['diagnostics'][0]['code'], 'SCENE_LEASE_REQUIRED')
        self.assertEqual(client.calls, [])

    def test_valid_controller_guard_allows_only_construction(self):
        client = FakeHoudiniClient()
        result = GraphExecutor(client, Journal(), lease_guard=self.guard).execute('task', self.graph)
        self.assertTrue(result['construction_executed'])
        self.assertFalse(result['visual_verified'])
        self.guard('task',self.root,'node.info',{'path':self.root+'/material'})
        root_params={'parent':'/obj','task_id':'task','root_name':self.root.rsplit('/',1)[1]}
        for typ,layout in [('geo','sop_geo/1'),('subnet','object_subnet/1')]:
            self.guard('task',self.root,'scene.create_task_root',dict(root_params,type=typ,root_layout=layout))
        for change in [{'type':'subnet'}, {'type':'geo','root_layout':'object_subnet/1'},
                {'type':'subnet','root_layout':'sop_geo/1'}, {'type':'lopnet','root_layout':'object_subnet/1'},
                {'type':'subnet','root_layout':'object_subnet/1','task_id':'foreign'},
                {'type':'subnet','root_layout':'object_subnet/1','parent':'/stage'},
                {'type':'subnet','root_layout':'object_subnet/1','root_name':'foreign'}]:
            with self.subTest(root=change),self.assertRaises(ValueError):
                self.guard('task',self.root,'scene.create_task_root',{**root_params,**change})

    def test_stale_generation_or_restarted_host_blocks_before_calls(self):
        for field, value in [('session_id', 'other'), ('process_generation', 'process-2'), ('scene_id', 'other')]:
            self.identity[field] = value
            with self.assertRaises(ValueError): self.guard('task', self.root, 'node.children', {'path': '/obj'})
            self.identity[field] = getattr(self.lease, field)
        self.current = dataclasses.replace(self.lease, generation=2)
        client = FakeHoudiniClient()
        result = GraphExecutor(client, Journal(), lease_guard=self.guard).execute('task', self.graph)
        self.assertFalse(result['construction_executed'])
        self.assertEqual(client.calls, [])

    def test_expiry_task_and_path_scope_rejected(self):
        for task, command, params in [('other', 'node.children', {'path': '/obj'}),
            ('task', 'node.info', {'path': '/obj/user_scene'}),
            ('task', 'node.set_parms', {'path': '/obj/user_scene'}),
            ('task', 'node.connect', {'source': self.root+'/a', 'destination': '/obj/user_scene'}),
            ('task', 'node.create', {'parent': '/obj', 'name': 'user_scene'}),
            ('task', 'code.exec_python', {})]:
            with self.assertRaises(ValueError): self.guard(task, self.root, command, params)
        expired = SceneLeaseGuard(self.lease, lambda: self.current, lambda: self.identity, clock=lambda: 200)
        with self.assertRaises(ValueError): expired('task', self.root, 'node.children', {'path': '/obj'})

    def test_lease_rechecked_between_operations(self):
        client, journal = FakeHoudiniClient(), Journal()
        original = client.call
        def call(command, params):
            result = original(command, params)
            if command == 'node.create': self.current = dataclasses.replace(self.lease, generation=2)
            return result
        client.call = call
        result = GraphExecutor(client, journal, lease_guard=self.guard).execute('task', self.graph)
        self.assertTrue(result['reconciliation_required'])
        self.assertEqual(sum(command == 'node.create' for command, _ in client.calls), 1)

    def test_invalid_identity_cannot_form_lease(self):
        for change in ({'generation': True}, {'expires_at': float('nan')}, {'session_id': ''}, {'root': '/obj/user'}):
            with self.assertRaises(ValueError): dataclasses.replace(self.lease, **change)


class PersistentLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'leases.sqlite3'
        self.now = 100
        self.store = SceneLeaseStore(self.path, clock=lambda: self.now)
        self.fields = dict(task_id='task', session_id='session', process_generation='process', scene_id='scene', root='/obj/BRIDGE_GRAPH_test')

    def test_restart_retains_ownership_and_expiry_does_not_release_it(self):
        lease = self.store.acquire(**self.fields, ttl=1)
        restarted = SceneLeaseStore(self.path, clock=lambda: 200)
        self.assertEqual(restarted.current('session', 'scene'), lease)
        with self.assertRaises(ValueError): restarted.acquire(**self.fields)
        with self.assertRaises(ValueError): restarted.renew(lease)
        with self.assertRaises(ValueError): restarted.revoke(lease)

    def test_generation_and_stale_holder_fencing(self):
        lease = self.store.acquire(**self.fields)
        renewed = self.store.renew(lease, ttl=300)
        with self.assertRaises(ValueError): self.store.revoke(lease, host_operations_reconciled=True)
        self.store.revoke(renewed, host_operations_reconciled=True)
        second = self.store.acquire(**self.fields)
        self.assertGreater(second.generation, lease.generation)
        with self.assertRaises(ValueError): self.store.renew(renewed)

    def test_competing_store_instances_have_single_winner(self):
        def acquire(index):
            store = SceneLeaseStore(self.path)
            try: return store.acquire(**{**self.fields, 'task_id': 'task'+str(index)})
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(acquire, range(4)))
        self.assertEqual(sum(item is not None for item in results), 1)

    def test_persisted_revocation_blocks_graph_guard(self):
        lease = self.store.acquire(**self.fields)
        guard = SceneLeaseGuard(lease, lambda: self.store.current('session', 'scene'),
            lambda: {k:self.fields[k] for k in ('session_id','process_generation','scene_id')}, clock=lambda: self.now)
        guard('task', lease.root, 'node.children', {'path':'/obj'})
        self.store.revoke(lease, host_operations_reconciled=True)
        with self.assertRaises(ValueError): guard('task', lease.root, 'node.children', {'path':'/obj'})
