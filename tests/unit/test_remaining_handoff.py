"""F3 executable-controller tests. All media/app files are synthetic fixtures.

The generated server is invoked in subprocesses; no DCC method is requested.
No WorkBuddy executable is launched and no account or application is accessed.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from vfx_pipeline import graph_handoff
from vfx_pipeline.service import ModelSafePipeline
from vfx_pipeline.workbuddy_graph_mcp import GraphRun
from test_task_b_integration import ready_analysis
from test_prepare_workbuddy_graph import prepare_graph


class WindowsHandoffIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='handoff identity 中文 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / 'inbox').mkdir()
        self.target = self.root / 'inbox/response.json'
        self.raw = b'{"synthetic":true}'
        self.target.write_bytes(self.raw)

    def test_windows_reader_returns_only_matching_regular_file_bytes(self):
        self.assertEqual(graph_handoff._read_windows_response(self.target), self.raw)

    def test_hardlink_oversize_and_reparse_are_rejected_before_open(self):
        alias = self.root / 'alias.json'
        os.link(self.target, alias)
        with mock.patch.object(graph_handoff.os, 'open', side_effect=AssertionError('linked file opened')):
            with self.assertRaisesRegex(ValueError, 'non-linked'):
                graph_handoff._read_windows_response(self.target)
        alias.unlink()
        with self.target.open('wb') as stream:
            stream.seek(graph_handoff.MAX_RESPONSE_BYTES)
            stream.write(b'x')
        with mock.patch.object(graph_handoff.os, 'open', side_effect=AssertionError('oversized file opened')):
            with self.assertRaisesRegex(ValueError, 'size bound'):
                graph_handoff._read_windows_response(self.target)
        self.target.write_bytes(self.raw)
        original_lstat = Path.lstat
        for changed_path in (self.target, self.target.parent):
            def observed_lstat(path, *arguments, **keywords):
                information = original_lstat(path, *arguments, **keywords)
                if path == changed_path:
                    return SimpleNamespace(st_mode=information.st_mode, st_nlink=information.st_nlink,
                                           st_file_attributes=0x400)
                return information
            with self.subTest(path=changed_path.name), mock.patch.object(Path, 'lstat', observed_lstat):
                with mock.patch.object(graph_handoff.os, 'open', side_effect=AssertionError('reparse file opened')):
                    with self.assertRaises(ValueError):
                        graph_handoff._read_windows_response(self.target)

    def test_changed_open_handle_is_rejected_before_any_bytes_are_read(self):
        foreign = self.root / 'foreign.json'
        foreign.write_bytes(b'unit-only foreign bytes')
        original_open = os.open
        original_fdopen = os.fdopen
        def redirected_open(path, flags):
            return original_open(foreign if Path(path) == self.target else path, flags)
        def watched_fdopen(descriptor, mode):
            stream = original_fdopen(descriptor, mode)
            stream.read = mock.Mock(side_effect=AssertionError('foreign bytes read'))
            return stream
        with mock.patch.object(graph_handoff.os, 'open', redirected_open), mock.patch.object(graph_handoff.os, 'fdopen', watched_fdopen):
            with self.assertRaisesRegex(ValueError, 'before reading'):
                graph_handoff._read_windows_response(self.target)

    def test_post_read_file_and_directory_identity_changes_are_rejected(self):
        original_fstat = os.fstat
        observations = []
        def changed_fstat(descriptor):
            information = original_fstat(descriptor)
            observations.append(information)
            if len(observations) == 2:
                fields = {name: getattr(information, name) for name in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
                return SimpleNamespace(**{**fields, 'st_mtime_ns': information.st_mtime_ns + 1,
                                         'st_file_attributes': getattr(information, 'st_file_attributes', 0)})
            return information
        with mock.patch.object(graph_handoff.os, 'fstat', changed_fstat):
            with self.assertRaisesRegex(ValueError, 'during reading'):
                graph_handoff._read_windows_response(self.target)
        directories = graph_handoff._response_path_identity(self.target)
        with mock.patch.object(graph_handoff, '_response_path_identity', side_effect=[directories, ((0, 0),)]):
            with self.assertRaisesRegex(ValueError, 'during reading'):
                graph_handoff._read_windows_response(self.target)


class GeneratedHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='FAKE_HOST_handoff_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        app = self.root / 'fake-app'
        (app / 'Contents/MacOS').mkdir(parents=True)
        (app / 'Contents/MacOS/Main').write_bytes(b'NOT AN EXECUTABLE: SYNTHETIC FIXTURE')
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'com.tencent.workbuddy.mac',
            'CFBundleShortVersionString': 'FAKE_HOST_ONLY', 'CFBundleExecutable': 'Main'}))
        self.bundle = self.root / 'bundle'
        prepare_graph(self.bundle, app=app, scheduler_root=self.root/'installation')
        self.control = self.bundle / 'control'
        self.command = [sys.executable, '-I', str(self.control/'server.py')]
        self.manifest = json.loads((self.control/'run.json').read_text())
        self.assets = [item['asset_id'] for item in self.manifest['assets']]

    def cli(self, *arguments, expected=0):
        result = subprocess.run(self.command + list(arguments), cwd=self.root,
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + '\n' + result.stderr)
        return json.loads(result.stdout)

    def mcp(self, calls):
        messages = [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{
                'protocolVersion':'2025-06-18','clientInfo':{'name':'FAKE_HOST_TEST','version':'1'},'capabilities':{}}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
        ]
        messages += [{'jsonrpc':'2.0','id':i+2, **call} for i, call in enumerate(calls)]
        run = subprocess.run(self.command, cwd=self.root, input=''.join(json.dumps(m)+'\n' for m in messages),
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
        responses = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual(len(responses),len(calls)+1,run.stdout)
        for response in responses:
            self.assertNotIn('error',response,run.stdout)
        return [item['result'] for item in responses[1:]]

    def observations(self):
        calls=[]
        for index,asset in enumerate(self.assets):
            calls += [ {'method':'tools/call','params':{'name':'media','arguments':{'asset_id':asset}}},
                {'method':'tools/call','params':{'name':'submit_observation','arguments':{
                'asset_id':asset,'request_id':'observation_'+str(index),
                'observation':{'description':'Synthetic fixture observation; not real HY3 output.',
                               'uncertainties':['No real model or DCC in this test']}}}}]
        for result in self.mcp(calls):
            self.assertFalse(result.get('isError'),result)
        contract=self.cli('--handoff-contract')
        self.assertTrue(contract['ready'],contract)
        return contract

    def raw(self, contract, change=None):
        envelope=contract['response_template']
        envelope['tool_call_id']='synthetic_raw_response_1'
        envelope['analysis']=ready_analysis(36.0)
        if change: change(envelope)
        return json.dumps(envelope, ensure_ascii=False, indent=2).encode('utf-8')

    def submit(self, raw, *, request='manual_1', name='原始回复.json', expected=0, extra=()):
        (self.control/'inbox'/name).write_bytes(raw)
        return self.cli('--handoff-response',name,'--request-id',request,'--actor','FAKE_OPERATOR',
            '--expected-bytes',str(len(raw)),'--expected-sha256',hashlib.sha256(raw).hexdigest(),
            '--confirm-complete',*extra,expected=expected)

    def test_generated_entrypoint_observe_capture_register_submit_and_replay(self):
        before=self.cli('--handoff-contract')
        self.assertFalse(before['ready'])
        self.assertEqual(set(before['missing_asset_observations']),set(self.assets))
        self.assertEqual(list((self.control/'jobs/graph-jobs').iterdir()), [])
        contract=self.observations()
        raw=self.raw(contract)
        result=self.submit(raw)
        self.assertTrue(result['human_intervention'])
        self.assertFalse(result['automated_collection'])
        self.assertFalse(result['route_execution_verified'])
        self.assertFalse(result['provider_identity_verified'])
        self.assertFalse(result['dcc_dispatched'])
        self.assertFalse(result['registration']['route_execution_verified'])
        self.assertIn('analysis_submission',result)
        self.assertTrue(Path(result['result_file']).is_file())
        pipeline=ModelSafePipeline(self.control/'pipeline.sqlite3')
        task=contract['task_id']
        captures=pipeline.store.records(task,'reference_analysis_capture')
        self.assertEqual(len(captures),1)
        self.assertEqual(captures[0]['raw_response_utf8'].encode('utf-8'),raw)
        self.assertFalse(captures[0]['route_exchange_captured'])
        handoffs=pipeline.store.records(task,'manual_reference_handoff')
        self.assertEqual(base64.b64decode(handoffs[0]['raw_response_base64']),raw)
        self.assertEqual(handoffs[0]['state'],'SUBMITTED')
        second=self.submit(raw)
        self.assertTrue(second['replayed'])
        exported=self.cli('--export')
        self.assertEqual(exported['human_intervention_count'],1)
        self.assertEqual(len(exported['human_handoffs']),1)
        self.assertEqual(len(pipeline.store.records(task,'reference_analysis_capture')),1)
        self.assertEqual(len(pipeline.store.records(task,'external_model_run')),1)
        self.assertFalse(exported['real_workbuddy_acceptance'])
        self.assertEqual(list((self.control/'jobs/graph-jobs').iterdir()),[])
        self.assertNotEqual(pipeline.store.get_task(task)['state'],'COMPLETED')
        # A changed reply cannot borrow a previously submitted request identity.
        changed=raw.replace(b'36.0',b'37.0')
        self.assertNotEqual(raw,changed)
        rejected=self.submit(changed,expected=2)
        self.assertIn('already bound',rejected['message'])
        self.assertEqual(len(pipeline.store.records(task,'reference_analysis_capture')),1)

    def test_generated_replay_observations_and_model_tools_cannot_grant_capture(self):
        first=self.observations()
        second=self.observations()
        self.assertEqual(first['response_template']['observation_record_ids'],second['response_template']['observation_record_ids'])
        results=self.mcp([{'method':'tools/list'}, {'method':'tools/call','params':{
            'name':'capture_reference_analysis','arguments':{'verified':True,'path':'/not/allowed'}}}])
        names={item['name'] for item in results[0]['tools']}
        self.assertFalse(names & {'capture_reference_analysis','register_reference_analysis_run','authorize','handoff_response'})
        self.assertTrue(results[1]['isError'])

    def test_generated_missing_response_and_incomplete_observations_are_refused(self):
        result=self.submit(b'{}',expected=2)
        self.assertIn('observations',result['message'])
        contract=self.observations()
        result=self.cli('--handoff-response','missing.json','--request-id','missing','--actor','FAKE',
            '--expected-bytes','2','--expected-sha256',hashlib.sha256(b'{}').hexdigest(),
            '--confirm-complete',expected=2)
        self.assertIn('FileNotFoundError',result['error_type'])
        self.assertFalse(result['dcc_dispatched'])

    def test_generated_wrong_session_run_media_and_self_verified_are_refused(self):
        contract=self.observations()
        mutations=[lambda d:d.update(session_id='another-session'),lambda d:d.update(run_id='another-run'),
            lambda d:d.update(observation_record_ids=['model-invented-observation']),
            lambda d:d.update(verified=True),
            lambda d:d.update(observation_record_ids=d['observation_record_ids']*2)]
        for index,mutation in enumerate(mutations):
            with self.subTest(case=index):
                data=json.loads(json.dumps(contract))
                rejected=self.submit(self.raw(data,mutation),request='bad_'+str(index),expected=2)
                self.assertFalse(rejected['provider_identity_verified'])
        pipeline=ModelSafePipeline(self.control/'pipeline.sqlite3')
        self.assertEqual(pipeline.store.records(contract['task_id'],'reference_analysis_capture'),())
        self.assertEqual(pipeline.store.records(contract['task_id'],'external_model_run'),())
        records=pipeline.store.records(contract['task_id'],'manual_reference_handoff')
        self.assertEqual(len(records),len(mutations))
        self.assertTrue(all(row['state']=='REJECTED_OR_INTERRUPTED' for row in records))

    def test_generated_truncated_json_bad_analysis_utf8_and_duplicate_json_rejected(self):
        contract=self.observations()
        raw=self.raw(contract)
        broken=[raw[:-1],b'\xff\xfe',raw.replace(b'"confidence": 0.9',b'"confidence": "NaN"'),
            raw.replace(b'"schema":',b'"schema": "duplicate", "schema":',1)]
        for index,payload in enumerate(broken):
            with self.subTest(case=index): self.submit(payload,request='invalid_'+str(index),expected=2)
        self.submit(raw[:-1],request='length_mismatch',expected=2,extra=(
            '--expected-bytes',str(len(raw)),'--expected-sha256',hashlib.sha256(raw).hexdigest()))
        pipeline=ModelSafePipeline(self.control/'pipeline.sqlite3')
        self.assertEqual(pipeline.store.records(contract['task_id'],'external_model_run'),())

    def test_generated_path_symlink_media_tamper_and_no_collector_are_unverified(self):
        contract=self.observations()
        raw=self.raw(contract)
        (self.control/'inbox/good.json').write_bytes(raw)
        args=['--request-id','paths','--actor','FAKE','--expected-bytes',str(len(raw)),
            '--expected-sha256',hashlib.sha256(raw).hexdigest(),'--confirm-complete']
        for name in ['../inbox/good.json', 'good.json:alternate']:
            with self.subTest(name=name): self.cli('--handoff-response',name,*args,expected=2)
        with self.subTest(check='real_symlink'):
            try:
                (self.control/'inbox/link.json').symlink_to(self.control/'inbox/good.json')
            except OSError as error:
                if getattr(error, 'winerror', None) == 1314:
                    self.skipTest('NOT_RUN: Windows symbolic-link privilege unavailable')
                raise
            self.cli('--handoff-response','link.json',*args,expected=2)
        facade=GraphRun(self.control/'run.json',None)
        with self.assertRaisesRegex(ValueError,'collector is not configured'):
            facade.capture_reference_analysis(raw,{},'absent')
        media=self.control/self.manifest['assets'][0]['file']
        media.write_bytes(media.read_bytes()+b'SYNTHETIC_TAMPER')
        self.cli('--handoff-contract',expected=2)
        pipeline=ModelSafePipeline(self.control/'pipeline.sqlite3')
        self.assertEqual(pipeline.store.records(contract['task_id'],'external_model_run'),())
