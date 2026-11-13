"""The explicit OS-tool model cannot supply the expected executable identity."""
import hashlib
import os
from pathlib import Path
import sys
import time
import tempfile
import runpy
import subprocess
import unittest
from unittest.mock import patch
from engineering_image_tool_fixture import ADDRESS, tool_boundary, bootstrap
from dcc_task_runtime import process_image as image


class EngineeringImageToolFixtureTests(unittest.TestCase):
    def test_bootstrap_executes_frozen_bytes_after_external_template_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            template=Path(temporary)/'template.py';output=Path(temporary)/'source.txt'
            source="from pathlib import Path\ndef install(log,source,*facts): Path(log).write_text(source)\n"
            template.write_text(source);program=bootstrap(template,output)
            template.write_text("raise AssertionError('mutable external source executed')\n")
            exec(program,{})
            self.assertEqual(output.read_text(),source)

    def test_controller_bootstrap_preserves_original_program_argv_and_process_options(self):
        source=Path(__file__).with_name('engineering_image_tool_fixture.py')
        namespace=runpy.run_path(str(source));old_finders=list(sys.meta_path)
        with tempfile.TemporaryDirectory() as temporary, patch.object(image,'_run_tool'), patch.object(subprocess,'Popen') as actual:
            log=Path(temporary)/'tools.jsonl';server=log.parent/'activated/project/control/server.py'
            server.parent.mkdir(parents=True);server.write_text('# actual software server bytes\n')
            executable=str(Path(sys.executable).resolve())
            module_sha=hashlib.sha256(Path(image.__file__).read_bytes()).hexdigest()
            try:
                namespace['install'](log,source.read_text(),module_sha,executable)
                command=[executable,'-I','-B',str(server),'--backend','production','--software-processes']
                options={'cwd':str(server.parent),'env':{'software':'explicit'},'stdin':subprocess.PIPE,'start_new_session':True}
                subprocess.Popen(command,**options)
                passed=actual.call_args.args[0]
                self.assertEqual(passed[:4],[executable,'-I','-B','-c'])
                self.assertEqual(passed[-4:],command[3:])
                self.assertEqual(actual.call_args.kwargs,options)
                unknown=command[:-1]
                subprocess.Popen(unknown,**options)
                self.assertEqual(actual.call_args.args[0],unknown)
                with self.assertRaisesRegex(ValueError,'MODULE_SOURCE_MISMATCH'):
                    namespace['install'](log,source.read_text(),'wrong-source-hash',executable)
            finally:
                sys.meta_path[:]=old_finders
                if hasattr(image,'_explicit_software_image_tool_boundary'):del image._explicit_software_image_tool_boundary

    def test_fixed_argv_model_and_independent_input_refusals(self):
        executable=(Path(sys.base_prefix)/'Resources/Python.app/Contents/MacOS/Python').resolve()
        parent=1234;pid=os.getpid();info=executable.stat();ambiguous=False
        def original(argv,deadline):
            self.assertGreater(deadline,time.monotonic())
            if argv[0]=='/bin/ps':return f'{pid} {parent} Fri Oct 23 10:00:00 2026 S\n'.encode()
            if argv[0]=='/usr/sbin/lsof':
                record=f'ftxt\0tREG\0D{hex(info.st_dev)}\0i{info.st_ino}\0n{executable}\0\n'.encode()
                return f'p{pid}\0R{parent}\0\n'.encode()+record*(2 if ambiguous else 1)
            return b'explicit passthrough'
        events=[];boundary=tool_boundary(original,events.append);deadline=time.monotonic()+16
        header=['/usr/bin/sample',str(pid),'1','1000','-file','/dev/stdout']
        vmmap=['/usr/bin/vmmap','-w','-interleaved',str(pid),ADDRESS]
        self.assertIn(f'Process: software [{pid}]'.encode(),boundary(header,deadline))
        self.assertIn(str(executable).encode(),boundary(vmmap,deadline))
        legacy=['/usr/bin/vmmap','-w','-interleaved','-summary',str(pid)]
        self.assertEqual(boundary(legacy,deadline),boundary(header,deadline))
        self.assertEqual(boundary(['/bin/not-modeled'],deadline),b'explicit passthrough')
        for argv,reason in [(header+['-bad'],'ARGV_INVALID'),
                (header[:1]+['0']+header[2:],'PID_INVALID'),
                (header[:2]+['0']+header[3:],'ARGV_INVALID'),
                (legacy+['-bad'],'ARGV_INVALID'),
                (vmmap[:-1]+['0x200000000'],'ARGV_INVALID'),
                (header[:1]+[str(pid+1)]+header[2:],'PID_INVALID')]:
            with self.subTest(argv=argv),self.assertRaisesRegex(ValueError,reason):boundary(argv,deadline)
        ambiguous=True
        with self.assertRaisesRegex(ValueError,'MAIN_AMBIGUOUS'):boundary(header,deadline)
        ambiguous=False
        # Production parsers, double observation and executable comparison stay intact.
        with patch.object(image,'_run_tool',side_effect=boundary):
            observed=image.observe_process(pid)
            self.assertEqual(observed['image']['path'],str(executable))
            wrong=Path('/bin/sleep')
            expected=image.freeze_executable(str(wrong),'wrong-software-executable',hashlib.sha256(wrong.read_bytes()).hexdigest())
            anchor={**observed,'pid':parent,'parent_pid':1}
            with self.assertRaisesRegex(image.ProcessImageError,'EXECUTABLE_MISMATCH'):
                image.capture_ancestry(expected,anchor)
        self.assertFalse(getattr(image,'_explicit_software_image_tool_boundary',False),'module import must not install a fallback')


if __name__=='__main__':unittest.main()
