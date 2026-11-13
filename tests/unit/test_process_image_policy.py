"""Frozen collector policy tests. All OS collectors are replaced at their boundary."""
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dcc_task_runtime import process_image as image, native_scope, owned_process
from dcc_task_runtime import writer_tool_trace as trace, window_trace
import test_process_image as boundaries
import test_native_scope as scopes
from test_official_karma_preparation import tool


def sample_policy():
    return {'policy': 'sample_header_v1', 'tools': {
        name: {'path': path, 'bytes': 5, 'sha256': hashlib.sha256(b'tools').hexdigest()}
        for name, path in (('sample', '/usr/bin/sample'), ('vmmap', '/usr/bin/vmmap'))}}


class CollectorPolicyTests(unittest.TestCase):
    def setUp(self):
        self.boundary = boundaries.ProcessImageBoundaryTests()
        self.boundary.setUp()
        self.addCleanup(self.boundary.doCleanups)
        self.calls = []

    def tools(self, argv, deadline):
        self.calls.append(argv)
        if argv[:4] == ['/usr/bin/vmmap', '-w', '-interleaved', '-summary']:
            argv = ['/usr/bin/sample', argv[4], '1', '1000', '-file', '/dev/stdout']
        return self.boundary.tools(argv, deadline)

    def observe(self, policy):
        with patch.object(image, '_run_tool', side_effect=self.tools), \
             patch.object(image, 'check_collector_tools'):
            return image._observe(self.boundary.current, time.monotonic()+16, collector_policy=policy)

    def test_legacy_and_sample_sequences_have_identical_proof_contract_and_exact_counts(self):
        old = self.observe(image.scope_collector_policy({}))
        legacy = copy.deepcopy(self.calls); self.calls.clear()
        new = self.observe(sample_policy())
        self.assertEqual(old, new)
        self.assertEqual([a[0] for a in legacy], ['/bin/ps', '/usr/bin/vmmap', '/usr/bin/vmmap',
            '/usr/sbin/lsof', '/usr/sbin/lsof', '/usr/bin/vmmap', '/usr/bin/vmmap', '/bin/ps'])
        self.assertEqual([a[0] for a in self.calls], ['/bin/ps', '/usr/bin/sample', '/usr/bin/vmmap',
            '/usr/sbin/lsof', '/usr/sbin/lsof', '/usr/bin/sample', '/usr/bin/vmmap', '/bin/ps'])
        self.assertEqual(sum('-summary' in a for a in legacy), 2)
        self.assertEqual(sum('-summary' in a for a in self.calls), 0)
        self.assertEqual((image.TOOL_TIMEOUT_SECONDS, image.OBSERVE_TIMEOUT_SECONDS,
                          owned_process.WRITER_COLLECTION_SECONDS), (5, 16, 22))

    def test_unscoped_default_remains_sample_and_thread_policy_does_not_leak(self):
        self.observe(image.scope_collector_policy({})); self.calls.clear()
        with patch.dict(os.environ, {}, clear=True), patch.object(image, '_run_tool', side_effect=self.tools):
            image.observe_process(self.boundary.current)
        self.assertEqual(sum(a[0]=='/usr/bin/sample' for a in self.calls), 2)
        self.assertIsNone(getattr(image._TOOL_TRACE, 'collector_policy', None))

    def test_unknown_missing_extra_and_altered_bindings_fail_before_any_os_tool(self):
        bad = []
        value=sample_policy(); value['policy']='future_unknown'; bad.append(value)
        value=sample_policy(); del value['tools']['sample']; bad.append(value)
        value=sample_policy(); value['tools']['ps']=value['tools']['sample']; bad.append(value)
        for field, altered in (('path','/tmp/sample'), ('bytes',True), ('sha256','G'*64)):
            value=sample_policy(); value['tools']['sample'][field]=altered; bad.append(value)
        bad.extend((None, {}, {'policy':'sample_header_v1','tools':{}},
                    {'policy':'legacy_vmmap_summary_v1','tools':sample_policy()['tools']}))
        for value in bad:
            with self.subTest(value=value), patch.object(image, '_run_tool', side_effect=AssertionError('OS tool forbidden')), \
                 self.assertRaises(image.ProcessImageError):
                image._observe(self.boundary.current, time.monotonic()+16, collector_policy=value or {})

    def test_tool_size_or_hash_drift_is_rejected_before_ps(self):
        for field, actual in (('size',6), ('sha256','0'*64)):
            @contextmanager
            def opened(path, deadline):
                yield 123, {'size': actual if field=='size' else 5}
            with self.subTest(field=field), patch.object(image, '_opened_image', side_effect=opened), \
                 patch.object(image, '_hash', return_value=actual if field=='sha256' else hashlib.sha256(b'tools').hexdigest()), \
                 patch.object(image, '_run_tool', side_effect=AssertionError('must reject before collection')), \
                 self.assertRaisesRegex(image.ProcessImageError, 'COLLECTOR_TOOL_CHANGED'):
                image._observe(self.boundary.current, time.monotonic()+16, collector_policy=sample_policy())

    def test_authenticated_scope_selects_all_child_and_host_reobservations(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            binding=scopes.software_scope(Path(temporary).resolve(), process_image_policy=sample_policy())
            with patch.dict(os.environ, BRIDGE_NATIVE_SCOPE_BINDING=json.dumps(binding)), \
                 patch.object(image, 'check_collector_tools'), patch.object(image, '_run_tool', side_effect=self.tools):
                anchor=image.observe_process(self.boundary.host)
                proof=image.capture_ancestry(self.boundary.expected, anchor)
            self.assertEqual(len(proof['chain']), 2)
            self.assertEqual(sum(a[0]=='/usr/bin/sample' for a in self.calls), 10)
            self.assertFalse(any('-summary' in a for a in self.calls))
            # A changed frozen scope cannot silently fall back to global sample.
            Path(binding['path']).write_text('{}')
            with patch.dict(os.environ, BRIDGE_NATIVE_SCOPE_BINDING=json.dumps(binding)), \
                 patch.object(image, '_run_tool', side_effect=AssertionError('OS tool forbidden')), \
                 self.assertRaisesRegex(ValueError, 'NATIVE_SCOPE_CHANGED'):
                image.observe_process(self.boundary.current)

    def test_legacy_authenticated_scope_reaches_child_capture(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            binding=scopes.software_scope(Path(temporary).resolve())
            with patch.dict(os.environ, BRIDGE_NATIVE_SCOPE_BINDING=json.dumps(binding)), \
                 patch.object(image, '_run_tool', side_effect=self.tools):
                anchor=image.observe_process(self.boundary.host)
                image.capture_ancestry(self.boundary.expected, anchor)
            self.assertEqual(sum('-summary' in a for a in self.calls), 10)
            self.assertFalse(any(a[0]=='/usr/bin/sample' for a in self.calls))

    def test_scope_validation_accepts_new_engineering_and_official_contracts(self):
        variants=({}, {'schema':native_scope.OFFICIAL_SCOPE_SCHEMA,
            'resource_profile':native_scope.OFFICIAL_RESOURCE_PROFILE,
            'scene_profile':'official_karma_disklight_v1','budget':native_scope.OFFICIAL_BUDGET})
        for fields in variants:
            with self.subTest(fields=fields), tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
                binding=scopes.software_scope(Path(temporary).resolve(),process_image_policy=sample_policy(),**fields)
                scope=native_scope.NativeScope(binding)
                self.assertEqual(image.scope_collector_policy(scope.scope), sample_policy())
                self.assertNotIn('writer_trace_tools',scope.scope)
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary, self.assertRaises(image.ProcessImageError):
            scopes.software_scope(Path(temporary).resolve(),process_image_policy={'policy':'unrecognized','tools':{}})


class DiagnosticPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(); (self.root/'receipt.key').write_bytes(b'policy software fixture')
        self.policy=sample_policy(); self.binding={'path':'explicit-fixture','sha256':'a'*64}
        self.identity={'op':'policy-test'}
        self.spec={'native_scope_ticket':{'id':'ticket'},'writer_runtime':{'nonce':'nonce'}}

    def test_signed_source_accepts_exactly_two_addressed_and_binds_policy(self):
        source=window_trace.SignedToolEvents(self.root,identity=self.identity,scope_binding=self.binding,
            writer_pid=111,spec=self.spec,collector_policy=self.policy)
        now=time.monotonic()
        summary=['/usr/bin/vmmap','-w','-interleaved','-summary','111']
        with self.assertRaisesRegex(ValueError,'UNEXPECTED'):source.spawned(SimpleNamespace(pid=222),summary,now,now+5)
        for index in range(2):
            argv=['/usr/bin/vmmap','-w','-interleaved','111','0x1000']
            token=source.spawned(SimpleNamespace(pid=222+index),argv,now,now+5)
            source.finished(token,0,None)
        with self.assertRaisesRegex(ValueError,'LIMIT'):source.spawned(SimpleNamespace(pid=224),argv,now,now+5)
        source.close()
        for event in ('window-tool-start-0','window-tool-finish-1','window-tool-summary'):
            receipt=owned_process.read_receipt(self.root,event,identity=self.identity)
            self.assertEqual(receipt['process_image_policy'],self.policy)
        self.assertEqual(receipt['count'],2)

    def test_external_witness_rejects_foreign_policy_and_excess_original_event(self):
        witness=window_trace.WindowWitness.__new__(window_trace.WindowWitness)
        witness.policy=self.policy;witness.scope=SimpleNamespace(binding=self.binding)
        witness.child={'pid':111,'supervisor_pid':os.getpid(),'ticket_id':'ticket','runtime_nonce':'nonce'}
        witness.events={};witness.source_summary=None
        source=window_trace.SignedToolEvents(self.root,identity=self.identity,scope_binding=self.binding,
            writer_pid=111,spec=self.spec,collector_policy=self.policy)
        now=time.monotonic();source.spawned(SimpleNamespace(pid=222),
            ['/usr/bin/vmmap','-w','-interleaved','111','0x1000'],now,now+5)
        event=source.rows[0]['start']; event['process_image_policy']=image.scope_collector_policy({})
        witness._receipt=lambda name:event if name=='window-tool-start-0' else None
        with self.assertRaisesRegex(ValueError,'EVENT_IDENTITY'):witness._refresh()
        event['process_image_policy']=self.policy; event['index']=2
        witness._receipt=lambda name:event if name=='window-tool-start-2' else None
        with self.assertRaisesRegex(ValueError,'EVENT_COMMAND'):witness._refresh()

    def summary(self):
        return {'scope_binding':self.binding,'process_image_policy':self.policy,'writer_pid':111,
            'cleanup_complete':True,'observer_errors':[],'same_timeout_stacks_captured':[],
            'calls':[{'index':index,'argv':['/usr/bin/vmmap','-w','-interleaved','111','0x1000'],
                'tool_exit_code':0,'tool_diagnostic':None,'thread_joined':True,'witness_state':'INCOMPLETE',
                'reason':'TOOL_FINISHED_BEFORE_TRIGGER','auxiliary_tools':[]} for index in range(2)]}

    def test_survey_uses_external_policy_and_exact_new_or_old_count(self):
        value=self.summary()
        def allowed(value, policy=self.policy):
            return trace.survey_next_allowed(value,collector_policy=policy,scope_binding=self.binding)
        self.assertTrue(allowed(value));self.assertFalse(trace.survey_next_allowed(value))
        for count in (0,1,3,4):
            altered=copy.deepcopy(value);altered['calls']=(altered['calls']*2)[:count]
            self.assertFalse(allowed(altered))
        for field in ('process_image_policy','scope_binding'):
            altered=copy.deepcopy(value);altered.pop(field);self.assertFalse(allowed(altered))
        altered=copy.deepcopy(value);altered['calls'][0]['argv'].insert(3,'-summary');self.assertFalse(allowed(altered))
        altered=copy.deepcopy(value);altered['process_image_policy']['tools']['sample']['sha256']='b'*64
        self.assertFalse(allowed(altered))
        old=self.summary();old.pop('process_image_policy');old['calls']*=2
        self.assertTrue(allowed(old,image.scope_collector_policy({})))
        old['calls'].pop();self.assertFalse(allowed(old,image.scope_collector_policy({})))

    def test_trace_recorder_new_policy_refuses_summary_and_third_addressed(self):
        tools={'ps':{'path':'/bin/ps','bytes':1,'sha256':'b'*64},'sample':self.policy['tools']['sample']}
        with patch.object(trace,'file_record',side_effect=lambda path:tools['ps' if str(path)=='/bin/ps' else 'sample']):
            recorder=trace.ToolTrace(self.root/'trace',writer_pid=111,identity=self.identity,
                scope_binding=self.binding,collection_end=time.monotonic()+5,tools=tools,collector_policy=self.policy)
        now=time.monotonic()
        with self.assertRaisesRegex(ValueError,'UNEXPECTED'):
            recorder.spawned(SimpleNamespace(pid=222),['/usr/bin/vmmap','-w','-interleaved','-summary','111'],now,now+5)
        with patch.object(recorder,'_watch'):
            for index in range(2):
                row=recorder.spawned(SimpleNamespace(pid=222+index),['/usr/bin/vmmap','-w','-interleaved','111','0x1000'],now,now+5)
                recorder.finished(row,0,None)
            with self.assertRaisesRegex(ValueError,'LIMIT'):
                recorder.spawned(SimpleNamespace(pid=224),['/usr/bin/vmmap','-w','-interleaved','111','0x1000'],now,now+5)
        result=recorder.close();summary=json.loads(Path(result['record']['path']).read_text())
        self.assertEqual(summary['process_image_policy'],self.policy)
        self.assertEqual(len(summary['calls']),2)


class PreparationPolicyTests(unittest.TestCase):
    def test_preparation_checks_tool_drift_before_snapshot_or_output(self):
        prepare=tool('prepare_controlled_engineering')
        fake=SimpleNamespace(scope={'process_image_policy':sample_policy()},snapshot=lambda: self.fail('snapshot before drift check'))
        with patch.object(prepare,'plain',return_value=Path('/explicit-fixture/scope.json')), \
             patch.object(prepare,'file_record',return_value={'sha256':'a'*64}), \
             patch.object(prepare,'NativeScope',return_value=fake), \
             patch.object(prepare,'checked',side_effect=ValueError('EXPLICIT_TOOL_DRIFT')) as checked:
            with self.assertRaisesRegex(ValueError,'EXPLICIT_TOOL_DRIFT'):prepare._prepare('/explicit-fixture/scope.json')
        checked.assert_called_once_with(sample_policy()['tools']['sample'])


if __name__=='__main__':
    unittest.main()
