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


if __name__=='__main__':unittest.main()
