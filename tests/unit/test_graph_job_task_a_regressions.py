from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_graph_jobs import _proposal
from vfx_pipeline.graph_job_evidence import owned_file
from vfx_pipeline.graph_jobs import GraphJobService

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/helpers'))
from graph_job_process_fixture import directory_alias
MIGRATION_COLUMNS = {"attempt_generation", "cancel_requested", "stop_confirmed", "process_identity_json"}


class EvidenceAncestorAliasTests(unittest.TestCase):
    def test_trusted_root_ancestor_alias_is_accepted_for_existing_and_future_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); real = base / "real"; root = real / "task"
            root.mkdir(parents=True); (root / "result.json").write_text("{}")
            alias = base / "alias"; directory_alias(alias, real)
            self.assertEqual(owned_file(root, alias / "task/result.json"), root / "result.json")
            self.assertEqual(owned_file(root, alias / "task/future.json", required=False), root / "future.json")

    def test_links_below_root_and_sibling_are_rejected_through_ancestor_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); root = base / "real/task"; root.mkdir(parents=True)
            (root / "result.json").write_text("{}")
            alias = base / "alias"; directory_alias(alias, root.parent)
            directory_alias(root / 'linked', root)
            directory_alias(root / 'escape', base)
            for path in (alias / "task/linked/result.json", alias / "task/escape/new.json", root.parent / "other.json"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    owned_file(root, path, required=False)

    def test_looping_ancestor_alias_is_rejected_not_leaked_as_runtime_error(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); root = base / "real/task"; root.mkdir(parents=True)
            loop = base / "loop"; directory_alias(loop, loop)
            with self.assertRaisesRegex(ValueError, "outside the task root"):
                owned_file(root, loop / "task/future.json", required=False)


class SchemaMigrationConcurrencyTests(unittest.TestCase):
    def _old_db(self, root: Path, *, with_row: bool = True) -> None:
        root.mkdir(parents=True, exist_ok=True)
        db_path = root / "graph_jobs.sqlite3"
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("""CREATE TABLE operations (
                operation_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, request_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL, state TEXT NOT NULL, intent_json TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL, deadline_at REAL NOT NULL,
                pid INTEGER, process_token TEXT, result_json TEXT, error_code TEXT,
                UNIQUE(graph_id, request_id))""")
            if with_row:
                db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("legacy", "g", "r", "h", "SUCCEEDED", "{}", 1, 1, 2, None, None, "{}", None))

    def _columns(self, root: Path):
        with closing(sqlite3.connect(root / "graph_jobs.sqlite3")) as db:
            return {row[1] for row in db.execute("PRAGMA table_info(operations)")}

    def test_parallel_old_table_migration_serializes_and_preserves_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task"; scheduler = Path(directory) / "scheduler"; self._old_db(root)
            barrier = threading.Barrier(2)
            original = GraphJobService._init_db
            def synchronized(service):
                barrier.wait(5)
                return original(service)
            def open_service():
                service = GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=scheduler, worker_factory=lambda job: {})
                service.close()
            with patch.object(GraphJobService, "_init_db", synchronized):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(lambda _: open_service(), range(2)))
            self.assertTrue(MIGRATION_COLUMNS <= self._columns(root))
            with closing(sqlite3.connect(root / "graph_jobs.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT state FROM operations WHERE operation_id='legacy'").fetchone()[0], "SUCCEEDED")

    def test_parallel_new_database_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task"; scheduler = Path(directory) / "scheduler"
            def open_service(_):
                service = GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=scheduler, worker_factory=lambda job: {})
                service.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(open_service, range(2)))
            self.assertTrue(MIGRATION_COLUMNS <= self._columns(root))

    def test_mid_migration_ddl_failure_rolls_back_all_new_columns_and_retry_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "task"; scheduler = Path(directory) / "scheduler"; self._old_db(root)
            real_connect = sqlite3.connect
            class FaultConnection(sqlite3.Connection):
                alters = 0
                def execute(self, sql, parameters=(), /):
                    if sql.startswith("ALTER TABLE operations ADD COLUMN"):
                        type(self).alters += 1
                        if type(self).alters == 2:
                            raise sqlite3.OperationalError("injected migration ddl failure")
                    return super().execute(sql, parameters)
            def connect_fault(*args, **kwargs):
                kwargs["factory"] = FaultConnection
                return real_connect(*args, **kwargs)
            with patch("vfx_pipeline.graph_jobs.sqlite3.connect", side_effect=connect_fault):
                with self.assertRaisesRegex(sqlite3.OperationalError, "injected migration"):
                    GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=scheduler, worker_factory=lambda job: {})
            self.assertTrue(MIGRATION_COLUMNS.isdisjoint(self._columns(root)))
            service = GraphJobService(root, ROOT, "NEVER_A_DCC", scheduler_root=scheduler, worker_factory=lambda job: {})
            service.close(); self.assertTrue(MIGRATION_COLUMNS <= self._columns(root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
