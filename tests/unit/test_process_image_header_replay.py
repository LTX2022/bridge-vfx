"""Replay existing same-PID captures; no live target, sampler or vmmap is run."""
import json,os,time,unittest
from pathlib import Path
from unittest.mock import patch
from dcc_task_runtime import process_image as image
BASIS=Path(__file__).resolve().parents[2]/'handover/evidence/20261023-vmmap-repair/basis'
FIELDS=('Process','Parent Process','Load Address','Launch Time','Target Type')
def fields(raw):
    result={}
    for line in raw.decode().splitlines():
        for name in FIELDS:
            if line.startswith(name+':'):result[name]=line.split(':',1)[1].strip()
    return result

class HeaderReplayTests(unittest.TestCase):
    def sample(self,mode):return (BASIS/(mode+'-one-sample.stdout.txt')).read_bytes()
    def region(self,mode):return (BASIS/(mode+'-one-load-region.stdout.txt')).read_bytes()
    def replay(self,mode,header=None,region=None):
        pid=31228 if mode=='normal' else 31249;calls=[]
        data=self.sample(mode) if header is None else header
        mapping=self.region(mode) if region is None else region
        load=fields(data).get('Load Address')
        def tool(argv,deadline):
            calls.append(argv)
            if argv[0]=='/usr/bin/sample':
                self.assertEqual(argv,['/usr/bin/sample',str(pid),'1','1000','-file','/dev/stdout']);return data
            self.assertEqual(argv,['/usr/bin/vmmap','-w','-interleaved',str(pid),load]);return mapping
        self.calls=calls
        with patch.object(image,'_run_tool',side_effect=tool):return image._vmmap(pid,time.monotonic()+16)

    def test_archived_same_pid_headers_match_and_no_summary_is_requested(self):
        for mode in ('normal','relocated'):
            full=(BASIS/(mode+'-one-full.stdout.txt')).read_bytes()
            self.assertEqual(fields(full),fields(self.sample(mode)))
            self.assertEqual(set(fields(full)),set(FIELDS))
        value=self.replay('normal')
        self.assertEqual(value['load_address'],'0x100be8000')
        self.assertEqual(value['parent_pid'],31219)
        self.assertNotIn('*',value['path'])
        self.assertEqual(len(self.calls),2)
        self.assertFalse(any('-summary' in argv for argv in self.calls))

    def test_relocated_main_mapping_is_not_replaced_with_duplicate_rx(self):
        with self.assertRaisesRegex(image.ProcessImageError,'AMBIGUOUS_MAIN_IMAGE'):self.replay('relocated')
        self.assertEqual(self.calls[-1][-1],'0x100498000')

    def test_address_only_and_zero_snapshot_cannot_supply_identity_header(self):
        for name in ('normal-address.stdout.txt','normal-summary-address.stdout.txt','normal-same-sample0.stdout.txt'):
            data=(BASIS/name).read_bytes();self.assertEqual(fields(data),{})
            with self.assertRaisesRegex(image.ProcessImageError,'INVALID_VMMAP'):self.replay('normal',header=data)
            self.assertEqual(len(self.calls),1)

    def test_duplicate_wrong_pid_bad_birth_and_zero_load_are_refused(self):
        data=self.sample('normal')
        changes=(data+b'Load Address: 0x100be8000\n',data.replace(b'Python [31228]',b'Python [31229]'),data.replace(b'Launch Time:',b'Missing:'),data.replace(b'0x100be8000',b'0x0'))
        for changed in changes:
            with self.assertRaises(image.ProcessImageError):self.replay('normal',header=changed)

    def test_wrong_and_ambiguous_main_text_do_not_pass(self):
        region=self.region('normal')
        for changed in (region.replace(b'__TEXT',b'__DATA_CONST'),region+region,region.replace(b'100be8000-100bec000',b'200be8000-200bec000')):
            with self.assertRaises(image.ProcessImageError):self.replay('normal',region=changed)

    def fake_tool(self,argv,stderr,code=0,hold=False):
        class Process:
            pid=2000000000
            def __init__(self):
                self.returncode=None if hold else code;self.writers=[]
                def pipe(data):
                    rd,wr=os.pipe()
                    if data:os.write(wr,data)
                    if hold:self.writers.append(wr)
                    else:os.close(wr)
                    return os.fdopen(rd,'rb',buffering=0)
                self.stdout=pipe(b'header');self.stderr=pipe(stderr)
            def poll(self):return self.returncode
            def wait(self,timeout):
                for fd in self.writers:os.close(fd)
                self.writers=[]
                if self.returncode is None:self.returncode=-9
                return self.returncode
        with patch.object(image.subprocess,'Popen',return_value=Process()),patch.object(image.os,'killpg'):
            return image._run_tool(argv,time.monotonic()+16)

    def test_only_exact_success_progress_is_allowed(self):
        argv=['/usr/bin/sample','31228','1','1000','-file','/dev/stdout']
        progress=(BASIS/'normal-one-sample.stderr.txt').read_bytes()
        self.assertEqual(self.fake_tool(argv,progress),b'header')
        for wrong in (progress+b'warning\n',progress.replace(b'31228',b'31229')):
            with self.assertRaisesRegex(image.ProcessImageError,'TOOL_FAILED'):self.fake_tool(argv,wrong)
        for command in (['/usr/bin/vmmap','-w','-interleaved','-summary','31228'],['/usr/bin/sample','31228','0','1','-file','/dev/stdout']):
            with self.assertRaisesRegex(image.ProcessImageError,'TOOL_FAILED'):self.fake_tool(command,progress)
        with self.assertRaisesRegex(image.ProcessImageError,'TOOL_FAILED'):self.fake_tool(argv,progress,code=7)

    def test_progress_is_pinned_to_exact_command_pid_and_complete_bytes(self):
        argv=['/usr/bin/sample','31228','1','1000','-file','/dev/stdout']
        progress=(BASIS/'normal-one-sample.stderr.txt').read_bytes()
        for command in (argv+['-mayDie'],['/tmp/sample',*argv[1:]],
                [argv[0],'0',*argv[2:]],[argv[0],'2147483648',*argv[2:]],
                [argv[0],'031228',*argv[2:]],[argv[0],'31229',*argv[2:]],
                [*argv[:3],'1',*argv[4:]],[*argv[:-1],'/tmp/report']):
            with self.subTest(command=command),self.assertRaisesRegex(image.ProcessImageError,'TOOL_FAILED'):
                self.fake_tool(command,progress)
        for stderr in (progress[:-1],progress.replace(b'\n',b'\r\n'),progress+progress,b'\xff'+progress):
            with self.subTest(stderr=stderr),self.assertRaisesRegex(image.ProcessImageError,'TOOL_FAILED'):
                self.fake_tool(argv,stderr)
        self.assertEqual(self.fake_tool(argv,b''),b'header')

    def test_observation_and_capture_deadlines_are_not_extended(self):
        self.assertEqual(image.OBSERVE_TIMEOUT_SECONDS,16.)
        self.assertEqual(image.CAPTURE_TIMEOUT_SECONDS,60.)
        from dcc_task_runtime import owned_process
        self.assertEqual(owned_process.WRITER_COLLECTION_SECONDS,22.)

    def test_header_tool_deadline_still_fails_without_fallback(self):
        argv=['/usr/bin/sample','31228','1','1000','-file','/dev/stdout']
        with patch.object(image,'TOOL_TIMEOUT_SECONDS',.01):
            with self.assertRaisesRegex(image.ProcessImageError,'TIMEOUT') as raised:self.fake_tool(argv,b'',hold=True)
        self.assertTrue(raised.exception.diagnostic['cleanup']['leader_reaped'])
        self.assertEqual(image.TOOL_TIMEOUT_SECONDS,5.)
