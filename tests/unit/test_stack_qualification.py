"""Frozen qualification boundaries; all sampling and target launches are software fixtures."""
import hashlib,importlib.util,json,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dcc_task_runtime import writer_tool_trace as trace

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('qualification_test_tool',ROOT/'tools/qualify_native_stack.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)

class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.candidate=self.root/'candidate';self.target=self.root/'target'
        self.image=self.root/'explicit-runtime-image';self.image.write_bytes(b'explicit software runtime-image fixture')
        self.prepared=q.prepare(self.candidate,self.target,target_image=self.image);self.review=self.prepared['review']
        self.python=str(Path(sys.executable).resolve());self.expected=str(self.image)

    def stream(self,argv,deadline,cancel):
        if argv[0]=='/bin/ps':data=('999 888 Tue Oct 27 06:00:00 2026 S '+self.expected+'\n').encode()
        else:
            self.assertEqual(argv[2:],['0','1','-file','/dev/stdout'])
            data=('Analysis of sampling '+Path(self.expected).name+' (pid 999) every 1 millisecond\nCall graph:\n    1 Thread_1\n      1 read (in libsystem_kernel.dylib) + 1 [0x123]\nTotal number in stack: 1\n').encode()
        return {'argv':argv,'pid':333,'spawned':True,'complete':True,'stdout':data,'stderr':b'',
            'started_monotonic':time.monotonic(),'ended_monotonic':time.monotonic(),'deadline_monotonic':deadline,
            'cleanup':{'leader_reaped':True,'group_absent':True,'errors':[]}}

    def captures(self):
        argv=['/bin/ps','-p','999','-o','pid=,ppid=,lstart=,stat=,comm='];end=time.monotonic()+5
        return [self.stream(argv,end,lambda:False),self.stream(['/usr/bin/sample','999','0','1','-file','/dev/stdout'],end,lambda:False),self.stream(argv,end,lambda:False)]

    def assess(self,items):return q.assess(trace,*items,pid=999,parent=888,expected=self.expected)

    def test_valid_single_snapshot_accepts_only_matching_identity_and_frames(self):
        self.assertEqual(self.assess(self.captures())['pid'],999)

    def test_header_without_stack_never_qualifies(self):
        values=self.captures();values[1]['stdout']=b'Process: Python [999]\n'
        with self.assertRaisesRegex(ValueError,'IDENTITY_OR_FRAMES'):self.assess(values)

    def test_changed_birth_or_parent_rejected(self):
        for old,new in [(b'06:00:00',b'06:00:01'),(b'999 888',b'999 887')]:
            with self.subTest(new=new):
                values=self.captures();values[2]['stdout']=values[2]['stdout'].replace(old,new)
                with self.assertRaises(ValueError):self.assess(values)

    def test_sample_deadline_or_unreaped_group_never_qualifies(self):
        values=self.captures();values[1]['complete']=False
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):self.assess(values)
        values=self.captures();values[1]['cleanup']['group_absent']=False
        with self.assertRaisesRegex(ValueError,'CLEANUP_UNKNOWN'):self.assess(values)
        values=self.captures();values[1]['ended_monotonic']=values[1]['deadline_monotonic']+.1
        with self.assertRaisesRegex(ValueError,'CAPTURE_LATE'):self.assess(values)

    def test_real_one_shot_report_has_frames_without_fabricated_full_report_header(self):
        data=(ROOT/'tests/fixtures/native-stack-single-snapshot.txt').read_bytes()
        frames=q.single_snapshot_frames(data,pid=53966,expected='/fixture/Python')
        self.assertTrue(any('time_sleep' in frame for frame in frames))
        self.assertTrue(any('__semwait_signal' in frame for frame in frames))
        self.assertNotIn(b'Process:',data)
        with self.assertRaises(ValueError):q.single_snapshot_frames(data,pid=53967,expected='/fixture/Python')
        with self.assertRaises(ValueError):q.single_snapshot_frames(data,pid=53966,expected='/fixture/other')

    def test_actual_multithread_snapshot_keeps_main_thread_branch_frames(self):
        for name,pid,expected,wanted in (
            ('hython',88334,'/fixture/hython',('main  (in hython)','GU_Agent::install','trieWalk')),
            ('vmmap',88393,'/usr/bin/vmmap',('VMUProcessDescription','_CFIterateDirectory','__getdirentries64'))):
            data=(ROOT/f'tests/fixtures/native-stack-{name}-multithread-snapshot.txt').read_bytes()
            frames=q.single_snapshot_frames(data,pid=pid,expected=expected)
            for symbol in wanted:self.assertTrue(any(symbol in frame for frame in frames),symbol)
            self.assertTrue(any(frame.startswith('+') for frame in frames))
            self.assertTrue(any('__workq_kernreturn' in frame for frame in frames))

    def test_branch_marker_does_not_weaken_header_thread_or_native_frame_gates(self):
        header=b'Analysis of sampling hython (pid 123) every 1 millisecond\nCall graph:\n'
        native=b'    + 1 symbol (in dyld) + 4 [0x123]\n'
        with self.assertRaises(ValueError):q.single_snapshot_frames(header+native,pid=123,expected='/fixture/hython')
        for line in (b'    + 1 no native address\n',b'    + 1 symbol (in dyld) + 4 [0x0]\n'):
            with self.assertRaises(ValueError):q.single_snapshot_frames(header+b'    1 Thread_1\n'+line,pid=123,expected='/fixture/hython')

    def test_snapshot_header_without_frames_and_conflicting_metadata_rejected(self):
        data=(ROOT/'tests/fixtures/native-stack-single-snapshot.txt').read_bytes()
        with self.assertRaises(ValueError):q.single_snapshot_frames(data.split(b'Call graph:')[0],pid=53966,expected='/fixture/Python')
        with self.assertRaises(ValueError):q.single_snapshot_frames(data+b'Path: /wrong\n',pid=53966,expected='/fixture/Python')
        with self.assertRaises(ValueError):q.single_snapshot_frames(data+data,pid=53966,expected='/fixture/Python')

    def test_out_of_order_or_different_command_evidence_rejected(self):
        values=self.captures();values[1]['started_monotonic']=values[0]['started_monotonic']-1
        with self.assertRaisesRegex(ValueError,'ORDER_INVALID'):self.assess(values)
        values=self.captures();values[1]['argv'][1]='998'
        with self.assertRaisesRegex(ValueError,'COMMAND_CHANGED'):self.assess(values)

    def test_prepared_bundle_is_zero_dcc_and_frozen_drift_rejected(self):
        self.assertEqual(self.prepared['budget']['dcc_starts'],0)
        q.read_review(self.review['path'],self.review['sha256'])
        p=self.candidate/'support/writer_tool_trace.py';p.write_bytes(p.read_bytes()+b'\n# explicit drift fixture\n')
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):q.read_review(self.review['path'],self.review['sha256'])

    def test_runtime_image_is_pinned_independently_from_launch_binary(self):
        value=q.read_review(self.review['path'],self.review['sha256'])
        self.assertNotEqual(value['tools']['python']['path'],value['target_runtime_image']['path'])
        self.image.write_bytes(b'explicit changed image fixture')
        with self.assertRaisesRegex(ValueError,'FROZEN_INPUT_CHANGED'):
            q.read_review(self.review['path'],self.review['sha256'])

    def test_real_python_framework_path_observation_rejects_launcher_and_accepts_exact_image(self):
        framework='/opt/homebrew/Cellar/python@3.11/3.11.16/Frameworks/Python.framework/Versions/3.11'
        launcher=framework+'/bin/python3.11';image=framework+'/Resources/Python.app/Contents/MacOS/Python'
        observed=('47534 47533 Tue Oct 27 07:13:18 2026 Ss '+image+'\n').encode()
        with self.assertRaisesRegex(ValueError,'STATE_MISMATCH'):trace._state(observed,47534,47533,launcher)
        value=trace._state(observed,47534,47533,image)
        self.assertEqual(value['path'],image);self.assertEqual(value['ppid'],47533)

    def test_no_grant_or_wrong_entry_cannot_spawn(self):
        with patch.object(q,'module',side_effect=AssertionError('must not load launch support')):
            with self.assertRaisesRegex(ValueError,'GRANT_REQUIRED'):q.execute(self.review['path'],self.review['sha256'],'')
            with self.assertRaisesRegex(ValueError,'FROZEN_ENTRY_REQUIRED'):q.execute(self.review['path'],self.review['sha256'],'explicit software fixture')
        self.assertFalse(self.target.exists())

    def fake_run(self,*,release_fails=False,sample_fails=False):
        started={'pid':999,'supervisor_identity':{'pid':888}}
        stopped={'pid':999,'observed_by':'owned_child_wait','descendant_result_unobserved':False,
            'started_sha256':hashlib.sha256(json.dumps(started,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'exit_code':0,'stop_reason':None}
        calls=[];wait_calls=[]
        def wait(**kw):
            wait_calls.append(kw)
            if release_fails and len(wait_calls)==1:raise TimeoutError('explicit release failure')
        handle=SimpleNamespace(pid=999,started=started,poll=lambda:None,wait=wait,terminate=lambda:None,
            _supervisor=SimpleNamespace(poll=lambda:0))
        def launch(command,**kw):
            calls.append(command);Path(kw['directory']).mkdir();Path(command[-2]).write_text('999');return handle
        def capture(argv,deadline,cancel):
            result=self.stream(argv,deadline,cancel)
            if sample_fails and argv[0]=='/usr/bin/sample':result['complete']=False
            return result
        owned=SimpleNamespace(launch=launch,read_receipt=lambda path,event,**kw:started if event=='started' else stopped,
            _canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':')).encode(),_disk_usage=lambda budget:0)
        traced=SimpleNamespace(_capture=capture,cleanup_confirmed=trace.cleanup_confirmed,_state=trace._state,sample_identity=trace.sample_identity)
        with patch.object(q,'__file__',str(self.candidate/'support/qualify_native_stack.py')), \
             patch.object(q,'module',side_effect=lambda name,path:owned if name=='_qualification_owned' else traced), \
             patch.dict(q.os.environ,q.CONTROLLER_ENV):
            result=q.execute(self.review['path'],self.review['sha256'],'explicit software boundary fixture')
        self.assertEqual(len(calls),1);self.assertEqual(result['dcc_starts'],0)
        self.assertFalse(result['H21_authorized']);return result

    def test_success_is_ordinary_target_only_and_cannot_be_retried(self):
        result=self.fake_run();self.assertEqual(result['state'],'QUALIFIED_ORDINARY_TARGET_ONLY')
        self.assertEqual(result['sample_calls'],1);self.assertTrue(result['trusted_native_stop'])
        self.assertFalse(result['hython_capability_proven'])
        with patch.object(q,'__file__',str(self.candidate/'support/qualify_native_stack.py')),patch.dict(q.os.environ,q.CONTROLLER_ENV):
            with self.assertRaisesRegex(ValueError,'RETRY_FORBIDDEN'):q.execute(self.review['path'],self.review['sha256'],'explicit fixture')

    def test_final_result_write_crossing_deadline_rejects_controller_success(self):
        clock=[0.];original=Path.write_text
        def write(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==self.target/'result.json':clock[0]=21.
            return result
        with patch.object(q.time,'monotonic',side_effect=lambda:clock[0]),patch.object(Path,'write_text',write):
            with self.assertRaisesRegex(ValueError,'FINAL_SEAL_DEADLINE'):self.fake_run()
        value=json.loads((self.target/'result.json').read_text())
        self.assertTrue(value['provisional_until_controller_exit_zero']);self.assertFalse(value['H21_authorized'])

    def test_release_failure_is_not_qualification_success(self):
        result=self.fake_run(release_fails=True)
        self.assertEqual(result['state'],'FAILED_STOPPED');self.assertIn('RELEASE_FAILED',result['failure'])

    def test_capture_failure_stops_without_another_target(self):
        result=self.fake_run(sample_fails=True)
        self.assertEqual(result['state'],'FAILED_STOPPED');self.assertEqual(result['ordinary_targets_started'],1)

if __name__=='__main__':unittest.main()
