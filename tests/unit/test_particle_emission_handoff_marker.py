import json
from pathlib import Path
import tempfile
import time
import unittest

from vfx_pipeline.graph_jobs import GraphJobError, GraphJobService, _public_result
import test_graph_jobs as support


class ParticleEmissionHandoffMarkerTests(unittest.TestCase):
    def test_exact_saved_contract_survives_both_public_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = dict(root=Path(directory), operation_id='owned-operation', graph_id='owned-graph')
            result = dict(graph_hash='a' * 64, verification=dict(nodes_verified=True,
                parameters_verified=True, connections_verified=True,
                registered_scene_contract_sha256='b' * 64, foreign_detail='not public'))
            first = _public_result(result, **arguments)
            second = _public_result(first, **arguments)
            self.assertEqual(second['verification']['registered_scene_contract_sha256'], 'b' * 64)
            self.assertEqual(first, second)
            self.assertNotIn('foreign_detail', second['verification'])
            result['verification'].pop('registered_scene_contract_sha256')
            self.assertNotIn('registered_scene_contract_sha256', _public_result(result, **arguments)['verification'])

    def test_invalid_present_contract_cannot_downgrade_to_ordinary_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = dict(root=Path(directory), operation_id='owned-operation', graph_id='owned-graph')
            for digest in (None, False, 1, '', 'A' * 64, 'a' * 63, 'g' * 64, ['a' * 64]):
                with self.subTest(digest=digest), self.assertRaisesRegex(GraphJobError, 'REGISTERED_SCENE_CONTRACT_INVALID'):
                    _public_result(dict(graph_hash='a' * 64,
                        verification=dict(registered_scene_contract_sha256=digest)), **arguments)
            with self.assertRaisesRegex(GraphJobError, 'REGISTERED_SCENE_CONTRACT_INVALID'):
                _public_result(dict(verification=dict(registered_scene_contract_sha256='a' * 64)), **arguments)

    def test_actual_operation_persistence_and_status_retain_exact_contract(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        def worker(job):
            compiled = json.loads(Path(job['graph_path']).read_text(encoding='utf-8'))
            return dict(construction_executed=True, graph_hash=compiled['graph_hash'],
                verification=dict(nodes_verified=True, registered_scene_contract_sha256='c' * 64))
        service = GraphJobService(root, Path(__file__).resolve().parents[2], 'hython',
            scheduler_root=root / 'installation', worker_factory=worker)
        self.addCleanup(service.close)
        graph = service.propose(support._proposal(), 'marker-proposal')
        operation = service.trial(graph, 'marker-trial')
        for attempt in range(100):
            status = service.status(operation)
            if status['state'] == 'SUCCEEDED':
                break
            time.sleep(.01)
        self.assertEqual(status['state'], 'SUCCEEDED', status)
        self.assertEqual(status['result']['verification']['registered_scene_contract_sha256'], 'c' * 64)
        stored = json.loads(service._row(operation)['result_json'])
        self.assertEqual(stored['verification'], status['result']['verification'])
        stored['verification']['registered_scene_contract_sha256'] = None
        with service._connect() as database:
            database.execute('UPDATE operations SET result_json=? WHERE operation_id=?',
                (json.dumps(stored), operation))
        with self.assertRaisesRegex(GraphJobError, 'REGISTERED_SCENE_CONTRACT_INVALID'):
            service.status(operation)
