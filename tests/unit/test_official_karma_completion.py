"""Completion boundary fixtures: native operations and OCIO are explicitly substituted."""
import copy,io,json,struct,sys,tempfile,unittest,zlib
from contextlib import ExitStack,redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import run_controlled_engineering as driver
from dcc_task_runtime.render_profiles import OFFICIAL
from houdini_bridge import official_karma_display as display
from houdini_bridge.official_karma_observation import file_record


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.control=self.root/'project/control';self.control.mkdir(parents=True)
        self.saves=self.root/'project/saves';self.saves.mkdir()
        self.nk=self.saves/'composite.nk';self.nk.write_text('explicit software NK fixture')
        for p in (self.root/'runtime-bindings.json',self.control/'official-seal.json',self.control/'official-display.json'):p.write_text('{}')
        self.sources={}
        for name,path in (('official',self.root/'official.exr'),('bridge',self.saves/'main.0001.exr'),('nuke',self.saves/'nuke.0001.exr')):
            path.write_bytes(b'explicit software EXR source fixture '+name.encode());self.sources[name]=file_record(path)
        self.roles=driver.selected_roles({'scene_profile':OFFICIAL})
        self.tickets=[{'role':role,'stopped_at':1} for role,n in self.roles.items() for _ in range(n)]
        owner=self
        class Native:
            def __init__(self):
                self.root=owner.root;self.over=False;self.checks=0
                self.scope={'budget':{'max_disk_bytes':536870912},'official_case':{'paths':{'official_image':owner.sources['official']['path']}}}
            def check(self):
                self.checks+=1
                if self.over:raise ValueError('NATIVE_SCOPE_DISK_EXHAUSTED')
                return {'disk_bytes':sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())}
            def snapshot(self):return dict(self.check(),closed_reason=None,dcc_starts=len(owner.tickets),tickets=owner.tickets)
        self.native=Native();self.budget=NS(native=self.native)
        self.data={'root':self.root,'control':self.control,'bindings_path':self.root/'runtime-bindings.json','scope':{'scene_profile':OFFICIAL,'official_case':self.native.scope['official_case']},'bindings':{'project_files':{}},'scope_sha256':'fixture','bindings_sha256':'fixture','outputs':{'houdini_pattern':str(self.saves/'main.%04d.exr'),'nuke_pattern':str(self.saves/'nuke.%04d.exr'),'nuke_script':str(self.nk)}}
        self.journal=NS(result=lambda _:{'operation_id':'fixture'})
        self.display={'reference':self.sources['official'],'policy':{'explicit_software_fixture':True}}
        self.previews={'schema':'bridge.official-karma-previews/1','display':file_record(self.control/'official-display.json'),'processor_cache_id':'fixture-cache','sources':copy.deepcopy(self.sources),'previews':{}}
        folder=self.root/'previews';folder.mkdir()
        for name in ('official','bridge','nuke','difference'):
            self.previews['previews'][name]=display._png(folder/(name+'.png'),420,300,[[0]*(420*4) for _ in range(300)])
        self.index=self.root/'official-previews.json';self.write_index()
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(display,'resolve_display',return_value=self.display))
        self.stack.enter_context(patch.object(display,'_processor',return_value=(None,'fixture-cache')))

    def write_index(self):self.index.write_text(json.dumps(self.previews))

    def final(self):
        v={'evidence_source':'real_host'}
        nuke={'output_verification':v,'formal_receipt':{'execution_fact':{'worker_receipt':{'snapshot':str(self.nk),'snapshot_sha256':file_record(self.nk)['sha256']}}}}
        entry={'version':1,'operation_id':'fixture','operation_receipt_sha256':'fixture','output_verification':v,'payload':{'completion_snapshot':{},'completion_metadata':{'1':{'width':driver.selected_plan(self.data['scope'])['resolution'][0],'height':driver.selected_plan(self.data['scope'])['resolution'][1],'channels':list('RGBA')}}}}
        registry=NS(set_operation_source=lambda _:None,lookup=lambda _:entry,verify=lambda _:{'usable':True})
        comparisons=[{'state':'PASS','reference':self.sources['official'],'candidate':self.sources['bridge']},{'state':'PASS','reference':self.sources['bridge'],'candidate':self.sources['nuke']}]
        alpha=NS(checked=lambda v:Path(v['path']),file_record=file_record)
        with ExitStack() as stack:
            for name,value in (('_alpha_original',lambda *a:{'calibration':v,'alpha_calibration':{}}),('_verify_registered',lambda *a:{'artifact':entry,'execution_fact':{}}),('_nuke_original',lambda *a:nuke),('_alpha_module',lambda:alpha),('_evidence_source',lambda *a:'real_host')):stack.enter_context(patch.object(driver,name,value))
            stack.enter_context(patch('dcc_task_runtime.artifact_registry.ArtifactRegistry',return_value=registry))
            stack.enter_context(patch('houdini_bridge.official_karma.compare_files',side_effect=comparisons))
            stack.enter_context(patch('houdini_bridge.official_karma_inputs.resolve_manifest',return_value=self.control/'run.json'))
            return driver._final_result(self.data,self.journal,self.budget)

    def test_valid_existing_previews_bind_current_sources_and_actual_pngs(self):
        result=self.final();self.assertEqual(result['state'],'AWAITING_HUMAN_REVIEW')
        self.assertEqual(result['official_previews'],file_record(self.index))
        self.assertGreaterEqual(self.native.checks,4)

    def test_new_index_is_validated_and_returned_after_generation(self):
        self.index.unlink()
        with patch.object(display,'write_previews',return_value=self.previews) as generated:
            result=self.final()
        self.assertEqual(generated.call_count,1)
        self.assertEqual(result['official_previews'],file_record(self.index))

    def test_legacy_completion_keeps_its_existing_output_contract(self):
        from dcc_task_runtime.render_profiles import LEGACY
        self.data['scope']['scene_profile']=LEGACY
        self.tickets=[{'role':role,'stopped_at':1} for role,n in driver.selected_roles(self.data['scope']).items() for _ in range(n)]
        self.index.unlink()
        with patch.object(display,'validate_previews',side_effect=AssertionError('legacy has no official preview contract')):
            result=self.final()
        self.assertEqual(result['state'],'AWAITING_HUMAN_REVIEW')
        self.assertIsNone(result['official_previews'])

    def test_malformed_or_stale_index_does_not_skip_validation(self):
        self.index.write_text('invalid JSON; no new preview generation')
        with self.assertRaises(ValueError):self.final()
        self.previews['sources']['bridge']['sha256']='0'*64;self.write_index()
        with self.assertRaisesRegex(ValueError,'INDEX_INVALID'):self.final()

    def test_missing_changed_or_rebound_pngs_are_rejected(self):
        path=Path(self.previews['previews']['bridge']['path']);old=path.read_bytes()
        path.unlink()
        with self.assertRaises(OSError):self.final()
        path.write_bytes(old+b'changed')
        with self.assertRaisesRegex(ValueError,'FILE_CHANGED'):self.final()
        path.write_bytes(b'not PNG');self.previews['previews']['bridge']=file_record(path);self.write_index()
        with self.assertRaisesRegex(ValueError,'PNG_INVALID'):self.final()

    def test_display_or_source_bytes_cannot_change_under_the_index(self):
        self.previews['processor_cache_id']='other-cache';self.write_index()
        with self.assertRaisesRegex(ValueError,'DISPLAY_CHANGED'):self.final()
        self.previews['processor_cache_id']='fixture-cache';self.write_index()
        Path(self.sources['bridge']['path']).write_bytes(b'changed source bytes')
        with self.assertRaises(ValueError):self.final()

    def test_budget_is_checked_after_preview_validation(self):
        original=display.validate_previews
        def validated(*args):
            record=original(*args);self.native.over=True;return record
        with patch.object(display,'validate_previews',side_effect=validated):
            with self.assertRaisesRegex(ValueError,'DISK_EXHAUSTED'):self.final()

    def test_generation_cannot_publish_index_after_budget_exhaustion(self):
        self.index.unlink()
        def generated(*args):self.native.over=True;return self.previews
        with patch.object(display,'write_previews',side_effect=generated):
            with self.assertRaisesRegex(ValueError,'DISK_EXHAUSTED'):self.final()
        self.assertFalse(self.index.exists())

    def test_png_capacity_is_checked_before_any_file_write(self):
        self.native.scope['budget']['max_disk_bytes']=0
        path=self.root/'must-not-exist.png'
        with self.assertRaisesRegex(ValueError,'DISK_EXHAUSTED'):display._png(path,1,1,[[0,0,0,0]],scope=self.native)
        self.assertFalse(path.exists())

    def test_png_crc_truncation_and_inflate_limits_are_enforced(self):
        raw=Path(self.previews['previews']['bridge']['path']).read_bytes()
        for changed in (raw[:-1],raw+b'extra',raw[:30]+bytes([raw[30]^1])+raw[31:]):
            with self.assertRaisesRegex(ValueError,'PNG_INVALID'):display._validate_png(changed)
        def chunk(k,b):return struct.pack('>I',len(b))+k+b+struct.pack('>I',zlib.crc32(k+b)&0xffffffff)
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',420,300,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'0'*600000))+chunk(b'IEND',b'')
        with self.assertRaisesRegex(ValueError,'PNG_INVALID'):display._validate_png(raw)

    def test_diagnostic_cli_zero_does_not_promote_business_acceptance(self):
        for state in ('IDENTITY_DIAGNOSTIC_FINISHED','TIMEOUT_NOT_REPRODUCED','DIAGNOSTIC_FIRST_STAGE_COMPLETED','FAILED','QUERY_REQUIRED'):
            result={'state':state,'full_chain_accepted':False,'hip_business':'NOT_RUN'}
            with patch('sys.argv',['driver','--scope','/fixture/scope','--bindings','/fixture/bindings','--execute']),patch.object(driver,'execute',return_value=result),redirect_stdout(io.StringIO()) as stream:
                code=driver.main()
            self.assertEqual(code,2 if state in ('FAILED','QUERY_REQUIRED') else 0)
            self.assertFalse(json.loads(stream.getvalue())['full_chain_accepted'])
