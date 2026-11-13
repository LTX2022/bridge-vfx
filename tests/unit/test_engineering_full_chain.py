"""One frozen software-only engineering chain through real owned Python processes."""
from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tests/unit'))
import test_engineering_preparation as preparation_fixture
from test_native_scope import software_scope
from dcc_task_runtime.native_scope import NativeScope
from dcc_task_runtime import owned_process
from engineering_houdini_api_fixture import write_boundaries
from engineering_nuke_api_fixture import write_api
import prepare_controlled_engineering as preparation
import activate_controlled_engineering as activation
from engineering_image_tool_fixture import bootstrap


class EngineeringFullChainTests(unittest.TestCase):
    def test_frozen_eight_start_chain_uses_real_receipts_workers_and_final_verifier(self):
        self._run_chain(native_image_tools=False)

    def test_frozen_eight_start_chain_with_native_process_image_tools(self):
        self._run_chain(native_image_tools=True)

    def _run_chain(self, *, native_image_tools):
        fixture=preparation_fixture.EngineeringPreparationTests('test_complete_snapshot_preparation_and_repeat_preserve_all_frozen_bytes')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        retained=os.environ.get('BRIDGE_ENGINEERING_SOFTWARE_WORKSPACE')
        if retained:
            base=Path(retained)
            if (not base.is_absolute() or base!=base.resolve() or base.parent!=ROOT/'outputs'
                    or not base.name.startswith('software-engineering-')):
                raise ValueError('explicit software workspace must be a fresh outputs/software-engineering-* directory')
            base.mkdir(mode=0o700)
        else:
            temporary=tempfile.TemporaryDirectory(prefix='software-engineering-',dir=ROOT/'outputs');self.addCleanup(temporary.cleanup)
            base=Path(temporary.name).resolve()
        shutil.copytree(fixture.root/'software-install',base/'software-install')
        python=Path(sys.executable).resolve()
        native_image=(Path(sys.base_prefix)/'Resources/Python.app/Contents/MacOS/Python').resolve()
        self.assertTrue(native_image.is_file(),'software process proof requires the macOS framework Python image')
        source=dict(fixture.native.scope)
        source['process_image_policy']={'policy':'sample_header_v1','tools':{
            name:preparation.file_record(path) for name,path in
            (('sample','/usr/bin/sample'),('vmmap','/usr/bin/vmmap'))}}
        for name in ('hython','husk','nuke'):
            path=base/Path(source['hosts'][name]['path']).relative_to(fixture.root)
            shutil.copyfile(native_image,path);path.chmod(0o700)
            source['hosts'][name]=preparation.file_record(path)
        ocio=base/Path(source['native_color_tokens']['houdini_static_config']['path']).relative_to(fixture.root)
        source['native_color_tokens']={'houdini_static_config':preparation.file_record(ocio)}
        probe=subprocess.run([source['hosts']['husk']['path'],'--version'],capture_output=True,text=True,timeout=10)
        self.assertEqual(probe.returncode,0,probe.stderr)
        image_adapter=None
        image_audit=base/'software-image-tools.jsonl'
        image_bootstrap=''
        if not native_image_tools:
            image_adapter=base/'software-image-tool-template.py'
            shutil.copyfile(ROOT/'tests/unit/engineering_image_tool_fixture.py',image_adapter)
            image_adapter_sha256=hashlib.sha256(image_adapter.read_bytes()).hexdigest()
            image_bootstrap=bootstrap(image_adapter,image_audit)
        boundary_paths=write_boundaries(base/'native-api',ROOT,husk_executable=Path(source['hosts']['husk']['path']),image_adapter=image_adapter,image_audit=image_audit)
        boundary_paths['nuke_api']=write_api(base/'nuke-api',image_adapter=image_adapter,image_audit=image_audit)
        source['software_native_boundaries']={name:preparation.file_record(path) for name,path in boundary_paths.items()}
        for key in ('output_root','accounting'):source.pop(key,None)
        binding=software_scope(base/'candidate',**source)
        candidate=NativeScope(binding)
        prepared=preparation.prepare(candidate.path)
        review=activation.review_activation(candidate.path,prepared['bindings']['path'],base/'activated',
            expected_scope_sha256=binding['sha256'],expected_bindings_sha256=prepared['bindings']['sha256'])['review']
        activated=activation.activate_software_test(review['path'],expected_review_sha256=review['sha256'])
        native=NativeScope(activated['scope'])
        # External template is not an execution input after source-byte freezing.
        if image_adapter is not None:
            image_adapter.write_text("raise AssertionError('mutated external adapter must never execute')\n")
        def stop_owned_python():
            handles={}
            for ticket in native.snapshot()['tickets']:
                handles.setdefault(ticket['directory'],owned_process.OwnedProcessHandle(ticket['directory'],ticket['identity']))
            pending=[handle for handle in handles.values() if handle.poll() is None]
            for handle in pending:handle.terminate()
            deadline=time.monotonic()+30
            while pending and time.monotonic()<deadline:
                pending=[handle for handle in pending if handle.poll() is None]
                if pending:time.sleep(.05)
            if pending:raise AssertionError('software process stop remains UNKNOWN: '+str([str(handle.directory) for handle in pending]))
        self.addCleanup(stop_owned_python)
        snapshot=native.root/'project/control/snapshot'
        result_path=native.root/'software-full-chain-result.json'
        script=image_bootstrap+'''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import run_controlled_engineering as d
from dcc_task_runtime.execution_lock import execution_lock
scope,bindings,out=map(Path,sys.argv[2:])
report,data=d.preflight(scope,bindings)
assert report['state']=='PREPARED',report
assert data['scope']['evidence_source']==data['bindings']['evidence_source']=='software_test'
try:d.execute(scope,bindings,approved_scope_sha256=report['scope_sha256'],approved_bindings_sha256=report['bindings_sha256'])
except ValueError as error:assert 'EXPLICIT_REAL_HOST_AUTHORIZATION_REQUIRED' in str(error)
else:raise AssertionError('software evidence passed public native execution gate')
data.update(scope_path=scope,bindings_path=bindings,scope_sha256=report['scope_sha256'],bindings_sha256=report['bindings_sha256'])
budget=d._alpha_module().ScopeBudget(scope,bindings)
with execution_lock(data['root']/'engineering-driver-state.json','controlled-engineering'):
    journal=d.StageJournal(data['root']/'engineering-driver-state.json',report['scope_sha256'],report['bindings_sha256'])
    result=d._fresh(data,journal,budget)
    nk=Path(data['outputs']['nuke_script']); original=nk.read_bytes()
    try:
        nk.write_bytes(original+b'\\n# explicit software byte replacement\\n')
        try:d._final_result(data,journal,budget)
        except ValueError as error:assert 'ENGINEERING_FINAL_NUKE_SCRIPT_CHANGED' in str(error),error
        else:raise AssertionError('final verifier accepted replaced NK bytes')
    finally:nk.write_bytes(original)
    out.write_text(json.dumps(result,sort_keys=True))
'''
        command=[str(python),'-I','-B','-c',script,str(snapshot/'tools'),str(native.path),activated['bindings']['path'],str(result_path)]
        with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as process:
            try:stdout,stderr=process.communicate(timeout=native.scope['budget']['total_seconds']+60)
            except subprocess.TimeoutExpired:
                process.send_signal(signal.SIGINT)
                try:process.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate()
                raise
            completed=subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
        diagnostics=[]
        if completed.returncode:
            for path in sorted(native.root.rglob('*')):
                if path.is_file() and path.name in ('child.stderr.log','supervisor.stderr.log','error.txt','engineering-controller.log','engineering-driver-state.json','result.json','completion.json','error.json'):
                    diagnostics.append(str(path.relative_to(native.root))+': '+path.read_text(errors='replace')[-16000:])
        if completed.returncode:
            for path in native.root.rglob('journal.sqlite3'):
                with sqlite3.connect(path) as db:
                    for row in db.execute('SELECT payload FROM entries'):
                        value=json.loads(row[0])
                        if value.get('status')!='COMPLETE':diagnostics.append(str(path.relative_to(native.root))+': '+row[0])
        self.assertEqual(completed.returncode,0,completed.stderr+'\n'+'\n'.join(diagnostics))
        result=json.loads(result_path.read_text())
        if native_image_tools:
            self.assertFalse(image_audit.exists())
            self.assertIsNone(image_adapter)
            self.assertEqual(image_bootstrap,'')
        else:
            model_events=[json.loads(line) for line in image_audit.read_text().splitlines()]
            self.assertTrue(any(e['event']=='supervisor-bootstrap' for e in model_events))
            self.assertEqual(sum(e['event']=='controller-bootstrap' for e in model_events),2)
            self.assertEqual({e['adapter_sha256'] for e in model_events},{image_adapter_sha256})
            for event in model_events:
                if event['event']=='module-installed':
                    self.assertEqual(event['source_sha256'],hashlib.sha256(Path(event['source']).read_bytes()).hexdigest())
            calls=[e['argv'][0] for e in model_events if e['event']=='modeled-tool']
            self.assertTrue(calls);self.assertEqual(set(calls),{'/usr/bin/sample','/usr/bin/vmmap'})
            self.assertEqual(calls.count('/usr/bin/sample'),calls.count('/usr/bin/vmmap'))
            self.assertFalse(any('-summary' in e['argv'] for e in model_events if e['event']=='modeled-tool'))
        self.assertEqual(result['state'],'SOFTWARE_CHAIN_COMPLETED')
        self.assertEqual(result['evidence_source'],'software_test')
        self.assertEqual(result['machine_checks']['native_execution_status'],'NOT_RUN')
        state=native.snapshot()
        self.assertEqual(state['dcc_starts'],8)
        self.assertIsNone(state['closed_reason'])
        self.assertTrue(all(ticket['stopped_at'] is not None for ticket in state['tickets']))
        self.assertEqual([ticket['role'] for ticket in state['tickets']],
            ['alpha-husk','alpha-nuke','graph-worker','houdini-host','houdini-host','main-husk','nuke-host','nuke-render'])
        for ticket in state['tickets']:
            stopped=owned_process.read_receipt(ticket['directory'],'stopped',identity=ticket['identity'])
            self.assertEqual(owned_process.execution_returncode(stopped),0)
            started=owned_process.read_receipt(ticket['directory'],'started',identity=ticket['identity'])
            if 'writer_process_binding' in started:
                binding=started['writer_process_binding']
                anchor=binding['host_anchor']
                self.assertEqual(anchor['pid'],started['pid'])
                self.assertGreater(int(anchor['load_address'],16),0)
                if not native_image_tools:
                    self.assertEqual(anchor['load_address'],'0x100000000')
                    self.assertTrue(anchor['birth'].endswith('.000 +0000'))
        self.assertEqual(len(result['artifacts']),2)
        self.assertTrue(all(item['output_verification']['evidence_source']=='software_test' for item in result['artifacts']))
        self.assertEqual(result['artifacts'][0]['output_verification'],result['artifacts'][1]['output_verification'])
        self.assertEqual(preparation.file_record(native.root/'project/saves/composite.nk')['sha256'],result['nuke_snapshot']['sha256'])
        self.assertEqual(candidate.snapshot()['dcc_starts'],0)
        self.assertFalse(candidate.scope['execution_authorized'])
        self.assertFalse(list(snapshot.rglob('*.pyc')))
        if os.environ.get('BRIDGE_ENGINEERING_SOFTWARE_EVIDENCE'):
            target=Path(os.environ['BRIDGE_ENGINEERING_SOFTWARE_EVIDENCE']);target.mkdir(parents=True,exist_ok=True)
            (target/'software-full-chain-result.json').write_text(json.dumps(result,indent=2,sort_keys=True))
            (target/'software-full-chain-stdout.txt').write_text(completed.stdout)
            if retained:
                (target/'software-workspace.json').write_text(json.dumps({'evidence_source':'software_test',
                    'workspace':str(base),'scope':activated['scope'],'bindings':activated['bindings'],
                    'native_execution_status':'NOT_RUN','private_keys_copied':False,
                    'process_image_observation':'native_macos_tools' if native_image_tools else 'software_image_tool_model',
                    'image_adapter_installed':image_adapter is not None,'popen_bootstrap_installed':bool(image_bootstrap)},indent=2,sort_keys=True))


if __name__=='__main__':unittest.main()
