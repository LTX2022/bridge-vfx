"""Archive storage and concurrency contracts; no DCC or production state."""
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('history_archive', ROOT/'tools/history_archive.py')
archive = importlib.util.module_from_spec(spec);spec.loader.exec_module(archive)


class HistoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.a = self.root/'version-a';self.b = self.root/'version-b'
        for p in (self.a, self.b):
            p.mkdir();(p/'same.py').write_text('value = 17\n')
        (self.a/'only.py').write_text('value = 19\n');os.chmod(self.a/'only.py', 0o640)
        self.consumer = self.root/'consumer.py';self.consumer.write_text('print("consumer")\n')
        self.registry = self.root/'projects.json';self.registry.write_text('{}')
        self.store = self.root/'archive'
        self.result = archive.build(self.store, [self.a, self.b], consumer=self.consumer,
                                    registry=self.registry, legacy_guard=False)
        self.reader = archive.Store(self.store)

    def test_dedup_roundtrip_keeps_original_paths_bytes_modes(self):
        self.assertEqual((self.result['files'],self.result['unique_contents']),(3,2))
        self.assertEqual(self.reader.compact()['removed_files'],3)
        self.assertFalse(self.a.exists())
        with self.reader.lease():
            self.assertEqual((self.a/'same.py').read_bytes(),(self.b/'same.py').read_bytes())
            self.assertEqual((self.a/'only.py').stat().st_mode&0o777,0o640)
            self.assertEqual((self.a/'same.py').stat().st_nlink,1)
        self.assertEqual(self.reader.compact()['state'],'COMPACT')

    def test_corrupt_database_refuses_restore_and_preserves_existing(self):
        with (self.store/'contents.sqlite3').open('ab') as stream:stream.write(b'corrupt')
        with self.assertRaisesRegex(ValueError,'DIGEST_MISMATCH'):self.reader.compact()
        self.assertTrue((self.a/'same.py').exists())

    def test_missing_archive_refuses(self):
        self.reader.compact();(self.store/'contents.sqlite3').unlink()
        with self.assertRaises(FileNotFoundError):
            with self.reader.lease():pass
        self.assertFalse(self.a.exists())

    def test_modified_or_extra_file_not_overwritten_or_deleted(self):
        (self.a/'same.py').write_text('changed\n')
        with self.assertRaisesRegex(ValueError,'FILE_CHANGED'):self.reader.compact()
        self.assertTrue(self.b.exists())
        with self.assertRaisesRegex(ValueError,'FILE_CHANGED'):
            with self.reader.lease():pass
        (self.a/'extra.txt').write_text('retain')
        with self.assertRaisesRegex(ValueError,'TREE_CHANGED'):self.reader.compact()
        self.assertTrue((self.a/'extra.txt').exists())

    def test_partial_existing_root_rejected_without_repair(self):
        (self.a/'same.py').unlink()
        with self.assertRaisesRegex(ValueError,'TREE_CHANGED'):
            with self.reader.lease():pass
        self.assertFalse((self.a/'same.py').exists())

    def test_traversal_and_case_collision_rejected(self):
        config=json.loads((self.store/'catalog.json').read_text())
        for path in ('../escape.py','/absolute.py','sub//x.py','SAME.py'):
            value=json.loads(json.dumps(config));value['roots'][0]['files'][0]['path']=path
            # SAME.py duplicates the other source entry only after adding it.
            if path=='SAME.py':value['roots'][0]['files'].append(dict(config['roots'][0]['files'][1],path='same.py'))
            (self.store/'catalog.json').write_bytes(archive.canonical(value))
            with self.assertRaisesRegex(ValueError,'MEMBER_INVALID'):archive.Store(self.store)

    def test_symlink_and_hardlink_rejected(self):
        p=self.a/'same.py';p.unlink();p.symlink_to(self.b/'same.py')
        with self.assertRaisesRegex(ValueError,'LINKED_PATH'):self.reader.verify_expanded()
        p.unlink();os.link(self.b/'same.py',p)
        with self.assertRaisesRegex(ValueError,'FILE_INVALID'):self.reader.verify_expanded()

    def test_private_state_refused(self):
        (self.a/'receipt.key').write_text('test key')
        with self.assertRaisesRegex(ValueError,'PRIVATE_STATE'):
            archive.build(self.root/'other', [self.a], consumer=self.consumer,registry=self.registry)
        self.assertFalse((self.root/'other').exists())

    def test_active_lease_prevents_compaction_in_another_process(self):
        script='import sys;sys.path.insert(0,sys.argv[1]);from history_archive import Store;print(Store(sys.argv[2]).compact()["state"])'
        with self.reader.lease():
            result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT/'tools'),str(self.store)],capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout.strip(),'IN_USE')
        self.assertEqual(self.reader.compact()['state'],'COMPACT')

    def test_interrupted_retirement_restores_canonical_root(self):
        original = archive.shutil.rmtree
        def interrupted(path, *args, **kwargs):
            if Path(path).parent.name == 'retiring':
                raise OSError('simulated process interruption')
            return original(path, *args, **kwargs)
        with mock.patch.object(archive.shutil, 'rmtree', side_effect=interrupted):
            with self.assertRaises(OSError):self.reader.compact()
        self.assertFalse(self.a.exists())
        with self.reader.lease():self.reader.verify_expanded()
        self.assertEqual(self.reader.compact()['state'], 'COMPACT')
        self.assertEqual(list((self.store/'retiring').iterdir()), [])

    def test_project_scope_restores_only_its_declared_roots(self):
        self.reader.config['projects'] = {'a': [str(self.a)], 'b': [str(self.b)]}
        self.reader.compact()
        with self.reader.scope('a'):
            with self.reader.lease():
                self.assertTrue(self.a.exists());self.assertFalse(self.b.exists())
            self.reader.compact()
        with self.reader.scope('new-project'):
            with self.reader.lease():
                self.assertTrue(self.a.exists());self.assertTrue(self.b.exists())

    def test_gateway_children_are_not_mistaken_for_legacy_clients(self):
        process_list = '201 1 python3.11 ./scripts/bridge_mcp.py serve --history-archive-gateway\n202 201 python3.11 /old/scripts/bridge_mcp.py serve\n203 1 python3.11 /old/scripts/bridge_mcp.py serve\n'
        with mock.patch.object(archive.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=process_list)):
            self.assertEqual(self.reader.legacy_readers(), [203])

    def test_legacy_consumers_and_mutations_pin(self):
        self.reader.config['legacy_guard']=True
        with mock.patch.object(self.reader,'legacy_readers',return_value=[123]):
            self.assertEqual(self.reader.compact()['state'],'LEGACY_READERS_ACTIVE')
        self.reader.pin()
        self.assertEqual(self.reader.compact()['state'],'PINNED')

    def test_pin_only_preserves_selected_project(self):
        self.reader.config['projects'] = {'a': [str(self.a)]}
        with self.reader.scope('a'):self.reader.pin()
        self.assertEqual(self.reader.compact()['state'], 'PARTIALLY_PINNED')
        self.assertTrue(self.a.exists());self.assertFalse(self.b.exists())

    def test_idle_input_preserves_pipelined_messages(self):
        read, write = os.pipe()
        with os.fdopen(read, 'r') as stream:
            try:
                lines=archive.input_lines(stream, idle_seconds=0.01)
                self.assertIsNone(next(lines))
                os.write(write,b'first\nsecond\n')
                self.assertEqual(next(lines),'first\n');self.assertEqual(next(lines),'second\n')
            finally:os.close(write)

    def test_query_burst_reuses_cache_and_idle_reclaims_it(self):
        self.consumer.write_text('import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if "id" in r:print(json.dumps({"id":r["id"],"result":{}}),flush=True)\n')
        self.reader.config['consumer_sha256']=archive.digest(self.consumer.read_bytes())
        self.reader.compact()
        request=json.dumps({'id':1,'method':'tools/call','params':{'name':'bridge_continue_task'}})+'\n'
        def messages(_):
            yield request
            self.assertTrue(self.a.exists())
            yield request
            yield None
            self.assertFalse(self.a.exists())
            yield request
        with mock.patch.object(archive,'input_lines',side_effect=messages), mock.patch.object(self.reader,'_restore',wraps=self.reader._restore) as restore:
            archive.gateway(self.reader,stdin=io.StringIO(),stdout=io.StringIO())
            self.assertEqual(restore.call_count,2)
        self.assertFalse(self.a.exists())

    def test_query_gateway_restores_and_compacts_without_changing_response(self):
        self.consumer.write_text('''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id' in r:print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':{'state':'COMPLETE'}}),flush=True)
''')
        self.reader.config['consumer_sha256']=archive.digest(self.consumer.read_bytes())
        self.reader.compact();out=io.StringIO()
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'bridge_continue_task','arguments':{}}}
        archive.gateway(self.reader,stdin=io.StringIO(json.dumps(request)+'\n'),stdout=out)
        self.assertEqual(json.loads(out.getvalue())['result'],{'state':'COMPLETE'})
        self.assertFalse(self.a.exists())

    def test_mutating_gateway_retains_expanded_sources(self):
        self.consumer.write_text('''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id' in r:print(json.dumps({'id':r['id'],'result':{'state':'FAILED'}}),flush=True)
''')
        self.reader.config['consumer_sha256']=archive.digest(self.consumer.read_bytes())
        self.reader.compact()
        request={'id':1,'method':'tools/call','params':{'name':'bridge_execute','arguments':{}}}
        archive.gateway(self.reader,stdin=io.StringIO(json.dumps(request)+'\n'),stdout=io.StringIO())
        self.assertTrue(self.a.exists())
        self.assertEqual(self.reader.compact()['state'],'PINNED')


class TerminalReceiptArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base/'project'/'producer-records'
        self.root.mkdir(parents=True)
        self.record = {'schema': 'bridge.houdini.producer-operation/1.0',
                       'state': 'COMPLETED', 'task_id': 'task', 'operation_id': 'operation'}
        self.name = archive.digest(b'task')+'/'+archive.digest(b'operation')+'.json'
        self.path = self.root/self.name;self.path.parent.mkdir()
        self.path.write_text(json.dumps(self.record));os.chmod(self.path, 0o600)
        self.consumer = self.base/'consumer.py';self.consumer.write_text('')
        self.registry = self.base/'registry.json';self.registry.write_text('{}')
        self.directory = self.base/'archive'

    def build(self):
        archive.build(self.directory, [self.root], consumer=self.consumer,
                      registry=self.registry, legacy_guard=False, terminal_record_roots=[self.root])
        return archive.Store(self.directory)

    def test_terminal_receipt_roundtrip_preserves_original_bytes_and_mode(self):
        os.chmod(self.root, 0o700);os.chmod(self.path.parent, 0o700)
        raw = self.path.read_bytes();store = self.build()
        self.assertEqual(store.compact()['removed_files'], 1)
        with store.lease():
            self.assertEqual(self.path.read_bytes(), raw)
            self.assertEqual(self.path.stat().st_mode&0o777, 0o600)
            self.assertEqual(self.root.stat().st_mode&0o777, 0o700)
            self.assertEqual(self.path.parent.stat().st_mode&0o777, 0o700)
        self.assertEqual(store.compact()['state'], 'COMPACT')

    def test_unfinished_or_credential_records_refused(self):
        for replacement in ({'state': 'INTENT'}, {'access_token': 'test-secret'}, {'budget_token': 'test-secret'}):
            self.path.write_text(json.dumps({**self.record, **replacement}))
            with self.assertRaises(ValueError):self.build()
            self.assertFalse(self.directory.exists())
            self.assertTrue(self.path.exists())

    def test_record_filename_must_bind_task_and_operation(self):
        self.path.write_text(json.dumps({**self.record, 'operation_id': 'different'}))
        with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):self.build()

    def test_terminal_query_schema_supported_but_unknown_schema_refused(self):
        self.path.write_text(json.dumps({**self.record, 'schema': 'unknown'}))
        with self.assertRaisesRegex(ValueError, 'TERMINAL_RECORD_REQUIRED'):self.build()
        self.path.write_text(json.dumps({**self.record, 'schema': 'bridge.houdini.producer-query/2'}))
        store = self.build();store.compact()
        with store.lease():self.assertTrue(self.path.exists())

    def test_duplicate_state_key_refused(self):
        self.path.write_text(json.dumps(self.record)[:-1]+', "state": "INTENT"}')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_KEY'):self.build()

    def test_new_records_require_pin_and_are_never_compacted(self):
        store = self.build();extra = self.root/'new.json';extra.write_text('new receipt')
        with self.assertRaisesRegex(ValueError, 'TREE_CHANGED'):
            with store.lease():pass
        store.pin()
        with store.lease():self.assertEqual(extra.read_text(), 'new receipt')
        self.assertEqual(store.compact()['state'], 'PINNED')
        self.assertTrue(extra.exists());self.assertTrue(self.path.exists())

    def test_pin_does_not_allow_old_record_changes_or_missing_members(self):
        store = self.build();store.pin();raw = self.path.read_bytes()
        self.path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'FILE_CHANGED'):
            with store.lease():pass
        self.path.write_bytes(raw);self.path.unlink()
        with self.assertRaisesRegex(ValueError, 'TREE_CHANGED'):
            with store.lease():pass

    def test_pinned_extra_symlink_refused(self):
        store = self.build();store.pin();(self.root/'alias').symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, 'LINKED_PATH'):
            with store.lease():pass

    def test_missing_pinned_root_is_not_replaced_with_stale_archive(self):
        store = self.build();store.pin();archive.shutil.rmtree(self.root)
        with self.assertRaisesRegex(ValueError, 'PINNED_RECORD_ROOT_MISSING'):
            with store.lease():pass
        self.assertFalse(self.root.exists())

    def test_source_pin_does_not_relax_source_tree_checks(self):
        archive.build(self.directory, [self.root], consumer=self.consumer,registry=self.registry,legacy_guard=False)
        store = archive.Store(self.directory);store.pin();(self.root/'new.py').write_text('unfrozen')
        with self.assertRaisesRegex(ValueError, 'TREE_CHANGED'):
            with store.lease():pass

    def test_observe_pin_survives_idle_and_followup_query(self):
        extra = self.root/'new.json'
        self.consumer.write_text('import sys,json\nfrom pathlib import Path\nfor line in sys.stdin:\n r=json.loads(line)\n if r.get("params",{}).get("name")=="bridge_observe":Path('+repr(str(extra))+').write_text("new receipt")\n if "id" in r:print(json.dumps({"id":r["id"],"result":{}}),flush=True)\n')
        store = self.build();store.compact()
        def messages(_):
            yield json.dumps({'id':1,'method':'tools/call','params':{'name':'bridge_observe'}})+'\n'
            yield None
            yield json.dumps({'id':2,'method':'tools/call','params':{'name':'bridge_continue_task'}})+'\n'
        out = io.StringIO()
        with mock.patch.object(archive, 'input_lines', side_effect=messages):
            archive.gateway(store, stdin=io.StringIO(), stdout=out)
        self.assertEqual(len(out.getvalue().splitlines()), 2)
        self.assertEqual(store.compact()['state'], 'PINNED')
        self.assertTrue(extra.exists())


if __name__=='__main__':unittest.main()
