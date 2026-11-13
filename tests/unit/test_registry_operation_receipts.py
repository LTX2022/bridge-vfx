from __future__ import annotations

import hashlib
import copy
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'packages/dcc-task-runtime/src'))

from dcc_task_runtime import artifact_registry as registry_module
from dcc_task_runtime.artifact_registry import ArtifactError, ArtifactRegistry, frame_path
from dcc_task_runtime.exr_codec import encode_tiny_exr, read_exr
from dcc_task_runtime.canonical import canonical_sha256


class RegistryOperationReceiptTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='registry-receipt-software-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.pattern = str(self.root / 'fixture.%03d.exr')
        self.source = self.root / 'explicit-software-file-producer.py'
        self.source.write_text('boundary = "synthetic EXR input, no DCC execution"\n', encoding='utf-8')
        snapshots, metadata = {}, {}
        for frame in (1, 2):
            path = frame_path(self.pattern, frame)
            path.write_bytes(encode_tiny_exr(float(frame)))
            info = path.stat()
            snapshots[str(frame)] = {'path': str(path), 'bytes': info.st_size,
                'modified_ns': info.st_mtime_ns, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            metadata[str(frame)] = dict(read_exr(path, with_pixels=False), **snapshots[str(frame)],
                colorspace='scene_linear', premultiplied=False)
            metadata[str(frame)].pop('rows')
        self.fact = {'task_id': 'fixture-owner', 'operation_id': 'fixture-operation',
            'frame_set': [1, 2], 'output_pattern': self.pattern, 'state': 'COMPLETED',
            'started_at_epoch': 1.0, 'scene_fingerprint': 'fixture-scene',
            'operation_receipt_sha256': hashlib.sha256(b'explicit software input receipt').hexdigest(),
            'completion_metadata_status': 'AVAILABLE', 'frame_snapshots': snapshots,
            'metadata': metadata, 'dependencies': ['fixture-scene']}
        self.producer_db = self.root / 'software-input-facts.sqlite3'
        with closing(sqlite3.connect(self.producer_db)) as db, db:
            db.execute('CREATE TABLE facts (operation_id TEXT PRIMARY KEY, payload TEXT)')
            db.execute('INSERT INTO facts VALUES (?, ?)', ('fixture-operation', json.dumps(self.fact)))
        self.registry = ArtifactRegistry(self.root / 'ledger')
        self.registry.set_operation_source(self.operation_source)

    def operation_source(self, operation_id):
        with closing(sqlite3.connect(self.producer_db)) as db:
            row = db.execute('SELECT payload FROM facts WHERE operation_id=?', (operation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def register(self, **changes):
        arguments = {'artifact_id': 'fixture-output', 'task_id': 'fixture-owner',
            'artifact_class': 'preview_temp', 'pattern': self.pattern, 'frame_set': [1, 2],
            'colorspace': 'scene_linear', 'premultiplied': False, 'dependencies': ['fixture-scene'],
            'operation_id': 'fixture-operation', 'scene_fingerprint': 'fixture-scene',
            'operation_receipt_sha256': self.fact['operation_receipt_sha256'],
            'receipt_source_files': {str(self.source): hashlib.sha256(self.source.read_bytes()).hexdigest()}}
        arguments.update(changes)
        return self.registry.register(**arguments)

    def replace_fact(self, fact):
        with closing(sqlite3.connect(self.producer_db)) as db, db:
            db.execute('UPDATE facts SET payload=? WHERE operation_id=?', (json.dumps(fact), 'fixture-operation'))

    def assert_no_commit(self):
        self.assertEqual(self.registry.history('fixture-output'), [])
        with self.registry._connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM artifact_operation_receipts').fetchone()[0], 0)

    def test_admission_uses_canonical_temporary_parent_without_accepting_links(self):
        canonical_parent=self.root.resolve()
        alias=canonical_parent/'temporary-parent-alias'
        alias.symlink_to(canonical_parent,target_is_directory=True)
        original=tempfile.TemporaryDirectory
        created=[]
        def temporary(*args,**kwargs):
            directory=original(*args,**kwargs)
            created.append(Path(directory.name))
            return directory
        with mock.patch.object(registry_module.tempfile,'gettempdir',return_value=str(alias)), \
                mock.patch.object(registry_module.tempfile,'TemporaryDirectory',side_effect=temporary):
            with self.registry._typed_admission(self.fact,self.pattern,[1,2],metadata=self.fact['metadata']) as admission:
                self.assertEqual(len(admission),2)
        self.assertEqual(len(created),1)
        self.assertEqual(created[0].parent,canonical_parent)
        self.assertFalse(created[0].exists())
        linked_source=alias/Path(self.pattern % 1).name
        with self.assertRaisesRegex(ValueError,'TASK_PATH_LINK'):
            registry_module.remove_owned_path(linked_source,owned_root=alias)
        self.assertTrue(frame_path(self.pattern,1).is_file())

    def test_selected_unavailable_completion_keeps_producer_binding_refusal(self):
        self.fact.update(project_color={'schema':'bridge.project-color/1.0', 'project_id':'test-project',
            'revision':1, 'colorspace':'scene_linear', 'source':'human_project_selection'},
            metadata={}, completion_metadata_status='BLOCKED_MISSING_NATIVE_FACTS')
        self.replace_fact(self.fact)
        with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_PRODUCER_BINDING_REQUIRED'):
            self.register()
        self.assert_no_commit()

    def test_human_project_color_is_preserved_and_bound_to_producer(self):
        color = {'schema':'bridge.project-color/1.0', 'project_id':'test-project',
                 'revision':1, 'colorspace':'scene_linear', 'source':'human_project_selection'}
        self.fact['project_color'] = color
        for image in self.fact['metadata'].values():
            image['project_color'] = dict(color)
        self.replace_fact(self.fact)
        entry = self.register()
        self.assertEqual(entry['project_color'], color)
        self.assertEqual(self.registry.lookup('fixture-output')['project_color'], color)
        receipt = self.registry.verify_operation_receipt(entry['registry_operation_receipt'])
        self.assertEqual(receipt['completion_metadata']['1']['project_color'], color)
        self.fact['project_color'] = dict(color, revision=2)
        self.replace_fact(self.fact)
        with self.assertRaises(ArtifactError):
            self.registry.verify_operation_receipt(receipt)

    def test_human_project_color_rejects_forged_payload_and_frame_disagreement(self):
        color = {'schema':'bridge.project-color/1.0', 'project_id':'test-project',
                 'revision':1, 'colorspace':'scene_linear', 'source':'human_project_selection'}
        with self.assertRaises(ArtifactError):
            self.register(payload={'project_color':color})
        self.fact['project_color'] = color
        self.fact['metadata']['1']['project_color'] = color
        self.replace_fact(self.fact)
        with self.assertRaises(ArtifactError):
            self.register()
        self.assert_no_commit()

    def test_receipt_is_persisted_with_actual_version_and_survives_new_registry(self):
        entry = self.register(scene_fingerprint='', operation_receipt_sha256='')
        receipt = entry['registry_operation_receipt']
        observer = ArtifactRegistry(self.root / 'ledger')
        observer.set_operation_source(self.operation_source)
        self.assertEqual(observer.lookup_operation_receipt('fixture-output', 1), receipt)
        self.assertEqual(receipt['state'], 'COMPLETED')
        self.assertEqual(receipt['stage'], 'persisted_output')
        self.assertEqual(receipt['frame_snapshots'], self.fact['frame_snapshots'])
        self.assertEqual(receipt['producer_receipt_sha256'], self.fact['operation_receipt_sha256'])
        with observer._connect() as db:
            row = db.execute('SELECT payload_json FROM artifact_operation_receipts').fetchone()
            self.assertEqual(json.loads(row[0]), receipt)
        self.assertEqual(observer.lookup('fixture-output')['registry_operation_receipt'], receipt)
        consumed = observer.read_frame('fixture-output', 2)
        self.assertEqual(consumed['registry_operation_receipt'], receipt)
        self.assertEqual(consumed['sha256'], self.fact['frame_snapshots']['2']['sha256'])
        self.assertTrue(consumed['image']['rows'])

    def test_unknown_incomplete_or_untyped_producer_cannot_commit_receipt(self):
        for change in ({'state': 'RUNNING'}, {'completion_metadata_status': 'UNAVAILABLE'},
                       {'metadata': {}}, {'operation_receipt_sha256': ''}, {'dependencies': ['other']}):
            with self.subTest(change=change):
                self.replace_fact(dict(self.fact, **change))
                with self.assertRaises(ArtifactError):
                    self.register(operation_receipt_sha256='')
                self.assert_no_commit()
        self.replace_fact(self.fact)
        with self.assertRaisesRegex(ArtifactError, 'OPERATION_NOT_FOUND'):
            self.register(operation_id='unknown')
        self.assert_no_commit()

    def test_missing_stale_or_unknown_source_cannot_commit_receipt(self):
        for sources in ({}, {str(self.source): '0'*64}, {str(self.root / 'missing.py'): '0'*64}):
            with self.subTest(sources=sources):
                with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_SOURCE_UNAVAILABLE'):
                    self.register(receipt_source_files=sources)
                self.assert_no_commit()

    def test_bounded_source_map_keeps_all_123_or_256_sources_current(self):
        implementation_count = len(registry_module._RECEIPT_IMPLEMENTATION_SOURCES)
        for total_count in (123, 256):
            with self.subTest(total_count=total_count):
                sources = {str(self.source): hashlib.sha256(self.source.read_bytes()).hexdigest()}
                for index in range(total_count - implementation_count - 1):
                    path = self.root / f'frozen-source-{total_count}-{index}.py'
                    path.write_bytes(f'explicit software source fixture {index}\n'.encode())
                    sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                receipt = self.register(artifact_id=f'source-map-{total_count}',
                    receipt_source_files=sources)['registry_operation_receipt']
                expected = dict(sources, **registry_module._RECEIPT_IMPLEMENTATION_SOURCES)
                self.assertEqual(len(receipt['current_source']), total_count)
                self.assertEqual(receipt['current_source'], expected)
                self.assertEqual(self.registry.lookup(f'source-map-{total_count}')['registry_operation_receipt'], receipt)
                leaf = Path(next(reversed(sources)))
                original = leaf.read_bytes()
                try:
                    leaf.write_bytes(b'changed frozen dependency')
                    with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_SOURCE_UNAVAILABLE'):
                        self.registry.verify_operation_receipt(receipt)
                    leaf.write_bytes(original)
                    leaf.unlink()
                    with self.assertRaisesRegex(ArtifactError, 'REGISTRY_RECEIPT_SOURCE_UNAVAILABLE'):
                        self.registry.verify_operation_receipt(receipt)
                finally:
                    leaf.write_bytes(original)
        extra = self.root / 'one-source-too-many.py'
        extra.write_bytes(b'explicit source bound overflow fixture')
        sources[str(extra)] = hashlib.sha256(extra.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArtifactError, 'receipt source file budget exceeded'):
            self.register(artifact_id='over-budget', receipt_source_files=sources)
        self.assertEqual(self.registry.history('over-budget'), [])

    def test_bounded_source_map_preserves_8mb_file_limit_and_closes_failure_fd(self):
        path = self.root / 'oversized-source.py'
        with path.open('wb') as stream:
            stream.truncate(8*1024*1024 + 1)
        with self.assertRaisesRegex(ArtifactError, 'bounded regular source file required'):
            self.register(receipt_source_files={str(path): '0'*64})
        self.assert_no_commit()
        path.unlink()

    def test_color_premultiplication_and_physical_metadata_are_read_back(self):
        for change in ({'colorspace': 'other'}, {'premultiplied': True}, {'artifact_class': 'raw_input'}):
            with self.subTest(change=change), self.assertRaises(ArtifactError):
                self.register(**change)
            self.assert_no_commit()
        for pixel_type in (0, 2.0):
            fact = copy.deepcopy(self.fact)
            fact['metadata']['2']['channel_layout']['channels'][0]['pixel_type'] = pixel_type
            self.replace_fact(fact)
            with self.subTest(pixel_type=pixel_type), self.assertRaisesRegex(ArtifactError, 'PHYSICAL_METADATA_MISMATCH'):
                self.register()
            self.assert_no_commit()

    def test_failed_sql_insert_rolls_back_artifact_history_and_receipt(self):
        with self.registry._connect() as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON artifact_operation_receipts BEGIN SELECT RAISE(ABORT, 'explicit receipt failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'explicit receipt failure'):
            self.register()
        self.assert_no_commit()

    def test_actual_commit_failure_cannot_return_completed(self):
        with self.registry._connect() as db:
            db.execute('CREATE TABLE receipt_parent (id TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE receipt_commit_check (id TEXT REFERENCES receipt_parent(id) DEFERRABLE INITIALLY DEFERRED)')
            db.execute("CREATE TRIGGER deferred_receipt AFTER INSERT ON artifact_operation_receipts BEGIN INSERT INTO receipt_commit_check VALUES ('missing-parent'); END")
        connect = self.registry._connect

        def foreign_key_connection():
            db = connect()
            db.execute('PRAGMA foreign_keys=ON')
            return db

        with mock.patch.object(self.registry, '_connect', side_effect=foreign_key_connection):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
                self.register()
        self.assert_no_commit()

    def test_all_frame_bytes_remain_bound_after_registration(self):
        entry = self.register()
        path = frame_path(self.pattern, 2)
        original, before = path.read_bytes(), path.stat()
        path.write_bytes(encode_tiny_exr(90.0))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ArtifactError, 'COMPLETION_BYTES_UNAVAILABLE'):
            self.registry.verify_operation_receipt(entry['registry_operation_receipt'])
        with self.assertRaises(ArtifactError):
            self.registry.read_frame('fixture-output', 1)
        path.write_bytes(original)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(ArtifactError):
            self.registry.lookup_operation_receipt('fixture-output', 1)

    def test_post_registration_source_and_producer_changes_are_rejected(self):
        receipt = self.register()['registry_operation_receipt']
        self.source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ArtifactError, 'SOURCE_UNAVAILABLE'):
            self.registry.verify_operation_receipt(receipt)
        self.source.write_text('boundary = "synthetic EXR input, no DCC execution"\n', encoding='utf-8')
        changed = dict(self.fact, operation_receipt_sha256='1'*64)
        self.replace_fact(changed)
        with self.assertRaisesRegex(ArtifactError, 'PRODUCER_CHANGED'):
            self.registry.verify_operation_receipt(receipt)
        observer = ArtifactRegistry(self.root / 'ledger')
        with self.assertRaisesRegex(ArtifactError, 'OPERATION_SOURCE_REQUIRED'):
            observer.verify_operation_receipt(receipt)

    def test_recomputed_digest_cannot_replace_actual_committed_receipt(self):
        receipt = self.register()['registry_operation_receipt']
        for change in ({'version': 2}, {'registry_path': str(self.root / 'other.sqlite3')},
                       {'producer_fact_sha256': '0'*64}, {'task_id': 'other'}):
            changed = dict(receipt, **change)
            changed.pop('registry_operation_receipt_sha256')
            changed['registry_operation_receipt_sha256'] = canonical_sha256(changed)
            with self.subTest(change=change), self.assertRaises(ArtifactError):
                self.registry.verify_operation_receipt(changed)
        with self.registry._connect() as db:
            db.execute('DELETE FROM artifact_operation_receipts')
        with self.assertRaisesRegex(ArtifactError, 'DB_READBACK_MISMATCH'):
            self.registry.verify_operation_receipt(receipt)

    def test_superseded_version_is_audit_only_and_db_columns_are_bound(self):
        first = self.register()['registry_operation_receipt']
        second = self.register()['registry_operation_receipt']
        self.assertEqual(second['version'], 2)
        with self.assertRaisesRegex(ArtifactError, 'CURRENT_VERSION_CHANGED'):
            self.registry.verify_operation_receipt(first)
        with self.registry._connect() as db:
            db.execute("UPDATE artifacts SET colorspace='tampered' WHERE artifact_id='fixture-output'")
        with self.assertRaisesRegex(ArtifactError, 'DB_READBACK_MISMATCH'):
            self.registry.verify_operation_receipt(second)

    def test_dependency_version_and_invalidation_are_bound(self):
        parent, fact = self.independent_parent()
        receipt = self.register(dependencies=['artifact:parent'])['registry_operation_receipt']
        self.assertEqual(receipt['dependency_records']['parent']['version'], 1)
        self.registry.register(artifact_id='parent', task_id='fixture-owner', artifact_class='preview_temp',
            pattern=parent['pattern'], frame_set=[1, 2], operation_id=fact['operation_id'],
            dependencies=fact['dependencies'])
        with self.assertRaisesRegex(ArtifactError, 'DB_READBACK_MISMATCH'):
            self.registry.verify_operation_receipt(receipt)
        self.registry.invalidate_dependencies(['artifact:parent'], reason='explicit test change')
        with self.assertRaises(ArtifactError):
            self.registry.verify_operation_receipt(receipt)

    def independent_parent(self, artifact_id='parent', dependencies=('parent-scene',), with_receipt=False):
        fact = copy.deepcopy(self.fact)
        fact.update(operation_id=artifact_id + '-operation', dependencies=list(dependencies),
            output_pattern=str(self.root / (artifact_id + '.%03d.exr')),
            operation_receipt_sha256=hashlib.sha256(b'independent software parent').hexdigest())
        for frame in (1, 2):
            path = frame_path(fact['output_pattern'], frame)
            path.write_bytes(encode_tiny_exr(float(frame + 10)))
            info = path.stat()
            snapshot = {'path': str(path), 'bytes': info.st_size, 'modified_ns': info.st_mtime_ns,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            fact['frame_snapshots'][str(frame)] = snapshot
            image = read_exr(path, with_pixels=False)
            image.pop('rows')
            fact['metadata'][str(frame)] = dict(image, **snapshot, colorspace='scene_linear', premultiplied=False)
        with closing(sqlite3.connect(self.producer_db)) as db, db:
            db.execute('INSERT INTO facts VALUES (?, ?)', (fact['operation_id'], json.dumps(fact)))
        source_files = {str(self.source): hashlib.sha256(self.source.read_bytes()).hexdigest()} if with_receipt else None
        entry = self.registry.register(artifact_id=artifact_id, task_id=fact['task_id'], artifact_class='preview_temp',
            pattern=fact['output_pattern'], frame_set=fact['frame_set'], colorspace='scene_linear', premultiplied=False,
            operation_id=fact['operation_id'], operation_receipt_sha256=fact['operation_receipt_sha256'],
            dependencies=fact['dependencies'], scene_fingerprint=fact['scene_fingerprint'], receipt_source_files=source_files)
        self.replace_fact(dict(self.fact, dependencies=['artifact:' + artifact_id]))
        return entry, fact

    def test_independent_parent_bytes_changed_or_removed_reject_child_receipt(self):
        parent, _ = self.independent_parent()
        child = self.register(dependencies=['artifact:parent'])
        receipt = child['registry_operation_receipt']
        path = frame_path(parent['pattern'], 2)
        original, info = path.read_bytes(), path.stat()
        child_sha = hashlib.sha256(frame_path(self.pattern, 2).read_bytes()).hexdigest()
        for mutation in ('changed_same_mtime', 'removed'):
            with self.subTest(mutation=mutation):
                try:
                    if mutation == 'removed':
                        path.unlink()
                    else:
                        path.write_bytes(encode_tiny_exr(90.0))
                        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                    self.assertEqual(hashlib.sha256(frame_path(self.pattern, 2).read_bytes()).hexdigest(), child_sha)
                    with self.assertRaises(ArtifactError):
                        self.registry.verify_operation_receipt(receipt)
                finally:
                    path.write_bytes(original)
                    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

    def test_changed_independent_parent_cannot_commit_child_receipt(self):
        parent, _ = self.independent_parent()
        frame_path(parent['pattern'], 2).write_bytes(encode_tiny_exr(90.0))
        with self.assertRaises(ArtifactError):
            self.register(dependencies=['artifact:parent'])
        self.assert_no_commit()

    def test_independent_parent_unknown_or_changed_producer_rejects_child_receipt(self):
        _, fact = self.independent_parent(with_receipt=True)
        receipt = self.register(dependencies=['artifact:parent'])['registry_operation_receipt']
        for change in ({'state': 'RUNNING'}, {'operation_receipt_sha256': '0'*64}, {'metadata': {}}):
            with closing(sqlite3.connect(self.producer_db)) as db, db:
                db.execute('UPDATE facts SET payload=? WHERE operation_id=?',
                    (json.dumps(dict(fact, **change)), fact['operation_id']))
            with self.subTest(change=change), self.assertRaises(ArtifactError):
                self.registry.verify_operation_receipt(receipt)
        with closing(sqlite3.connect(self.producer_db)) as db, db:
            db.execute('DELETE FROM facts WHERE operation_id=?', (fact['operation_id'],))
        with self.assertRaisesRegex(ArtifactError, 'OPERATION_NOT_FOUND'):
            self.registry.verify_operation_receipt(receipt)

    def test_independent_parent_transitive_bytes_are_also_current(self):
        grandparent, _ = self.independent_parent('grandparent')
        self.independent_parent(dependencies=['artifact:grandparent'], with_receipt=True)
        receipt = self.register(dependencies=['artifact:parent'])['registry_operation_receipt']
        self.assertEqual(set(receipt['dependency_records']), {'parent', 'grandparent'})
        frame_path(grandparent['pattern'], 2).unlink()
        with self.assertRaises(ArtifactError):
            self.registry.verify_operation_receipt(receipt)

    def test_independent_parent_file_identity_fence_rolls_back_child(self):
        parent, _ = self.independent_parent()
        path = frame_path(parent['pattern'], 2)
        connect = self.registry._connect

        def mutation_connection():
            db = connect()
            db.create_function('mutate_parent_file', 0, lambda: path.write_bytes(encode_tiny_exr(99.0)))
            db.execute("CREATE TEMP TRIGGER mutate_parent BEFORE INSERT ON artifacts WHEN NEW.artifact_id='fixture-output' BEGIN SELECT mutate_parent_file(); END")
            return db

        with mock.patch.object(self.registry, '_connect', side_effect=mutation_connection):
            with self.assertRaisesRegex(ArtifactError, 'COMPLETION_BYTES_UNAVAILABLE'):
                self.register(dependencies=['artifact:parent'])
        self.assert_no_commit()

    def test_independent_parent_version_fence_rejects_concurrent_update(self):
        parent, fact = self.independent_parent()
        entered, release = threading.Event(), threading.Event()
        decoder = registry_module.read_exr
        owner = {}

        def parent_decode(path, **arguments):
            if (threading.get_ident() == owner.get('id') and not entered.is_set()
                    and hashlib.sha256(Path(path).read_bytes()).hexdigest() == fact['frame_snapshots']['1']['sha256']):
                entered.set()
                if not release.wait(5):
                    raise AssertionError('parent decoder barrier timeout')
            return decoder(path, **arguments)

        def child_register():
            owner['id'] = threading.get_ident()
            return self.register(dependencies=['artifact:parent'])

        writer = ArtifactRegistry(self.root / 'ledger')
        writer.set_operation_source(self.operation_source)
        with mock.patch.object(registry_module, 'read_exr', side_effect=parent_decode), ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(child_register)
            try:
                self.assertTrue(entered.wait(3))
                updated = pool.submit(writer.register, artifact_id='parent', task_id=fact['task_id'],
                    artifact_class='preview_temp', pattern=parent['pattern'], frame_set=[1, 2],
                    colorspace='scene_linear', premultiplied=False, operation_id=fact['operation_id'],
                    operation_receipt_sha256=fact['operation_receipt_sha256'], dependencies=fact['dependencies'])
                self.assertEqual(updated.result(2)['version'], 2)
            finally:
                release.set()
            with self.assertRaisesRegex(ArtifactError, 'DB_READBACK_MISMATCH'):
                pending.result(3)
        self.assert_no_commit()

    def test_independent_parent_callback_wait_does_not_hold_sql_transaction(self):
        self.independent_parent()
        entered, release = threading.Event(), threading.Event()
        owner = {}

        def parent_source(operation_id):
            if operation_id == 'parent-operation' and threading.get_ident() == owner.get('id') and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise AssertionError('parent source barrier timeout')
            return self.operation_source(operation_id)

        def child_register():
            owner['id'] = threading.get_ident()
            return self.register(dependencies=['artifact:parent'])

        self.registry.set_operation_source(parent_source)
        writer = ArtifactRegistry(self.root / 'ledger')
        writer.set_operation_source(self.operation_source)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(child_register)
            try:
                self.assertTrue(entered.wait(3))
                unrelated = pool.submit(writer.register, artifact_id='unrelated', task_id='fixture-owner',
                    artifact_class='preview_temp', pattern=self.pattern, frame_set=[1, 2], operation_id='fixture-operation')
                self.assertEqual(unrelated.result(2)['version'], 1)
                self.assertFalse(pending.done())
            finally:
                release.set()
            self.assertEqual(pending.result(3)['registry_operation_receipt']['state'], 'COMPLETED')

    def test_hash_and_decode_waits_do_not_hold_sqlite_write_transaction(self):
        entered, release = threading.Event(), threading.Event()
        decoder = registry_module.read_exr
        owner = {}

        def bounded_decode(path, **arguments):
            if threading.get_ident() == owner.get('id') and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise AssertionError('actual decode barrier timeout')
            return decoder(path, **arguments)

        def typed_register():
            owner['id'] = threading.get_ident()
            return self.register()

        other = ArtifactRegistry(self.root / 'ledger')
        other.set_operation_source(self.operation_source)
        with mock.patch.object(registry_module, 'read_exr', side_effect=bounded_decode), ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(typed_register)
            try:
                self.assertTrue(entered.wait(3))
                unrelated = pool.submit(other.register, artifact_id='unrelated', task_id='fixture-owner',
                    artifact_class='preview_temp', pattern=self.pattern, frame_set=[1, 2], operation_id='fixture-operation')
                self.assertEqual(unrelated.result(2)['version'], 1)
                self.assertFalse(pending.done())
            finally:
                release.set()
            self.assertEqual(pending.result(3)['version'], 1)


if __name__ == '__main__':
    unittest.main()
