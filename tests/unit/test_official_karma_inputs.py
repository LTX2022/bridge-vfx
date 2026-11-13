"""Offline signed original fixtures. No native host is ever executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from dcc_task_runtime import native_scope,owned_process,process_image
from dcc_task_runtime.exr_codec import write_exr
from houdini_bridge import official_karma_inputs as inputs, official_karma_observation as evidence
from houdini_bridge import official_karma_worker as worker
from houdini_bridge.official_karma import canonical_sha256
from dcc_task_runtime.render_profiles import OFFICIAL
from test_native_scope import software_scope
import test_official_karma_observation as dto_fixture
import test_official_karma_preparation as image_fixture


class SealedInputsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(dir='/private/tmp');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        # Use the typed bottom DTO fixture while retaining actual validator/sealer.
        self.dto=dto_fixture.ObservationContractTests();self.dto.setUp();self.addCleanup(self.dto.doCleanups)
        control=self.root/'project/control';control.mkdir(parents=True)
        (self.root/'frozen-inputs').mkdir()
        self.template=control/'run.json'
        self.template_record=evidence.write_new(self.template,{'application':'pipeline',
            'domain_pack':'lighting_camera_render_v1','construction_authorized':True,'execution_authorized':True,
            'render_authorized':True,'simulation_authorized':False,'cache_authorized':False,
            'official_case_derivation':inputs.derivation_rule(self.root)})
        hip=self.root/'official.hip';hip.write_bytes(b'explicit HIP file identity fixture; not a Houdini project')
        usd=self.root/'official.usd';usd.write_bytes(b'explicit USD file identity fixture; not native output')
        hosts={}
        for name in ('hython','husk'):
            path=self.root/name;path.write_text('explicit executable image fixture; never execute');path.chmod(0o700)
            hosts[name]=evidence.file_record(path)
        case={'observer':evidence.file_record(Path(worker.__file__)),
            'source_contract':self.dto.contract,'static_review':self.dto.contract,
            'source_files':[self.dto.contract],'source_hip':evidence.file_record(hip),
            'source_freeze':{str(p):evidence.file_record(p)['sha256'] for p in evidence.required_source_paths()},
            'paths':{'official_hip':str(hip),'official_usd':str(usd),'official_image':str(self.root/'official.exr')},
            'commands':{r:[hosts['husk' if r=='official-husk' else 'hython']['path'],r]
                for r in ('official-open-save','official-cold-export','official-husk')},
            'derivation':inputs.derivation_rule(self.root)}
        self.binding=software_scope(self.root,schema=native_scope.OFFICIAL_SCOPE_SCHEMA,
            resource_profile=native_scope.OFFICIAL_RESOURCE_PROFILE,scene_profile=OFFICIAL,
            budget=native_scope.OFFICIAL_BUDGET,evidence_source='real_host',hosts=hosts,official_case=case)
        # 'real_host' tests schema validation of offline originals only. The explicit
        # fake image/DTO inputs above are not real DCC evidence or deliverables.
        self.scope=native_scope.NativeScope(self.binding)
        self.value=copy.deepcopy(self.dto.value)
        self.value.update(scope_sha256=self.binding['sha256'],output=case['paths']['official_image'])
        self.bindings=evidence.write_new(self.root/'runtime-bindings.json',{
            'scope_sha256':self.binding['sha256'],'evidence_source':'real_host',
            'project_files':{'manifest':self.template_record}})
        image=image_fixture.OfficialImageComparisonTests.image()
        image.update(pixel_count=126000,sample_count=504000,compression=0,color_metadata={'oiio:ColorSpace':'ACEScg'})
        image['channels']=sorted(image['channels']);image['channel_layout']['channels'].sort(key=lambda c:c['name'])
        write_exr(self.root/'official.exr',image,image['rows'])
        self.originals=[]
        for index,role in enumerate(case['commands']):
            directory=self.root/role
            identity={'operation_id':role,'fixture':'offline-signed-original-only'}
            ticket=self.scope.admit(role,directory,identity)
            directory.mkdir()
            (directory/'receipt.key').write_bytes(b'explicit-unit-fixture-secret')
            command=case['commands'][role]
            (directory/'intent.json').write_text(json.dumps({'command':command}))
            executable=hosts['husk' if role=='official-husk' else 'hython']
            expected=process_image.freeze_executable(executable['path'],'21.0.631',executable['sha256'])
            anchor={'schema':process_image.OBSERVATION_SCHEMA,'platform':'darwin','pid':123+index,
                'parent_pid':1,'birth':'2026-10-26 10:00:00.123 +0000','load_address':'0x100000000',
                'image':copy.deepcopy(expected['image'])}
            start={'schema':owned_process.SCHEMA,'event':'started','identity':identity,'pid':123+index,
                'observed_at':ticket['admitted_at'],'execution_protocol':1,'argv_sha256':canonical_sha256(command),
                'writer_process_binding':{'expected_executable':expected,'host_anchor':anchor}}
            owned_process._signed_write(directory,start)
            stop=dict(start,event='stopped',observed_at=ticket['admitted_at']+.01,
                started_sha256=canonical_sha256(start),observed_by='owned_child_wait',exit_code=0,
                descendant_result_unobserved=False,stop_reason=None,supervisor_exit_code=0,execution_result='succeeded')
            owned_process._signed_write(directory,stop)
            if role!='official-husk':
                observed={'schema':owned_process.SCHEMA,'event':'official-observation','identity':identity,
                    'scope_binding':self.binding,'started_sha256':canonical_sha256(start),
                    'observer':case['observer'],'source_contract':case['source_contract'],'role':role,
                    'captured_pid':start['pid'],'evidence_source':'real_host','hip':evidence.file_record(hip),
                    'observation':evidence.write_new(directory/'observation.json',self.value)}
                if role=='official-cold-export': observed['usd']=evidence.file_record(usd)
                owned_process._signed_write(directory,observed)
            self.scope.finish(ticket)
            self.originals.append({'directory':str(directory),'identity':identity})

    def seal(self):
        return evidence.seal_observations(self.binding,*self.originals)

    def test_originals_seal_then_derived_manifest_are_reauthenticated_without_rewrites(self):
        before=(Path(self.binding['path']).read_bytes(),Path(self.bindings['path']).read_bytes(),self.template.read_bytes())
        with mock.patch.object(owned_process,'launch',side_effect=AssertionError('native launch forbidden')):
            seal=self.seal()
            self.assertEqual(evidence.read_sealed(seal,expected_scope=self.binding),self.value)
            record=inputs.materialize(self.template,self.bindings,seal)
            result=evidence.load_record(record)
            manifest=inputs.resolve_manifest(self.template,self.bindings)
        self.assertEqual(manifest,self.root/'project/control/official-run.json')
        self.assertEqual(result['observation_sha256'],canonical_sha256(self.value))
        self.assertEqual(before,(Path(self.binding['path']).read_bytes(),Path(self.bindings['path']).read_bytes(),self.template.read_bytes()))
        self.assertEqual(self.scope.snapshot()['dcc_starts'],3)
        with self.assertRaisesRegex(ValueError,'ALREADY_EXISTS'):
            inputs.materialize(self.template,self.bindings,seal)
        configuration=Path(result['configuration']['path']);value=json.loads(configuration.read_text())
        value['scene']['resolution']=[128,128];configuration.write_text(json.dumps(value))
        with self.assertRaises(ValueError): inputs.resolve_manifest(self.template,self.bindings)

    def test_changed_original_command_or_missing_stop_cannot_be_sealed(self):
        directory=Path(self.originals[2]['directory'])
        intent=directory/'intent.json';value=json.loads(intent.read_text());value['command'].append('--changed')
        intent.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'FROZEN_COMMAND'): self.seal()

    def test_foreign_scope_and_forged_or_modified_observation_refused(self):
        seal=self.seal()
        bad=dict(seal,sha256='f'*64)
        with self.assertRaises(ValueError): evidence.read_sealed(bad,expected_scope=self.binding)
        cold=Path(self.originals[1]['directory'])/'observation.json';cold.write_text('{}')
        with self.assertRaises(ValueError): inputs.materialize(self.template,self.bindings,seal)

    def test_changed_frozen_template_and_unauthorized_scope_cannot_derive(self):
        self.template.write_text('{}')
        with self.assertRaises(ValueError): inputs.frozen_context(self.template,self.bindings)


class FrozenCommandTests(unittest.TestCase):
    def test_generated_worker_commands_use_the_actual_cli_parser_and_exact_case_paths(self):
        from houdini_bridge.official_karma_preparation import case_commands,relocate_case
        from houdini_bridge.official_karma_worker import argument_parser
        root=Path('/private/tmp/explicit fixture root')
        observer={'path':str(root/'project/control/snapshot/packages/houdini-bridge/src/houdini_bridge/official_karma_worker.py'),
            'bytes':1,'sha256':'a'*64}
        hosts={'hython':{'path':'/explicit/native/hython'},'husk':{'path':'/explicit/native/husk'}}
        paths={'official_usd':str(root/'official/official.usd')}
        commands=case_commands(root,hosts,observer,paths)
        for role in ('official-open-save','official-cold-export'):
            parsed=argument_parser().parse_args(commands[role][2:])
            self.assertEqual(parsed.phase,role)
            self.assertEqual(parsed.scope,str(root/'scope.json'))
        husk=commands['official-husk']
        self.assertEqual(husk[husk.index('--lock-random')+1],'1')
        self.assertNotIn('--output',husk)
        case={'observer':observer,'source_hip':{'path':str(root/'official-inputs/source.hip')},
            'source_files':[{'path':str(root/'official-inputs/source.hip')}],
            'original_files':[{'path':'/original/source.hip'}],
            'source_freeze':{observer['path']:'a'*64},'paths':paths,'commands':commands}
        target=Path('/private/tmp/final fixture root')
        moved=relocate_case(case,root,target)
        self.assertEqual(moved['source_hip']['path'],str(target/'official-inputs/source.hip'))
        self.assertEqual(moved['original_files'],case['original_files'])
        for role in ('official-open-save','official-cold-export'):
            self.assertEqual(argument_parser().parse_args(moved['commands'][role][2:]).scope,str(target/'scope.json'))
        import shlex
        self.assertEqual(shlex.split(moved['commands']['official-husk'][2]),[str(target/'project/control/snapshot/packages/dcc-task-runtime/src/dcc_task_runtime/husk_runtime_ready.py')])


if __name__=='__main__':unittest.main()
