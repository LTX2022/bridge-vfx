from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(ROOT/'packages'/package/'src'))

import verify_skill_lifecycle as lifecycle


class SkillLifecycleVerifierTests(unittest.TestCase):
    def test_closure_box_instance_values_are_explicit_without_claiming_native_defaults(self):
        from vfx_pipeline.workbuddy_assembly import software_host_client
        client, addon = software_host_client(ROOT/'plugins/houdini/_impl/houdini_bridge_addon.py', self.root/'api')
        lifecycle._closure_native_api(ROOT)
        import hou
        legacy_api = hou
        static_459, api_459 = lifecycle._closure_459_static_api(ROOT, self.root)
        self.assertTrue(static_459['passed'])
        self.assertEqual(len(static_459['operators']), 55)
        self.assertNotIn('Driver/usdrender', static_459['operators'])
        self.assertNotIn('Obj/geo', static_459['operators'])
        self.assertIs(sys.modules['hou'], legacy_api)
        self.assertIsNot(api_459, legacy_api)
        self.assertIsNot(type(api_459.node('/obj')), type(legacy_api.node('/obj')))
        self.assertEqual(legacy_api.applicationVersionString(), '21.0.631')
        self.assertEqual(api_459.applicationVersionString(), '22.0.459')
        box = hou.node('/obj').createNode('geo', 'fixture').createNode('box', 'box')
        for name in ('scale', 'sizex', 'sizey', 'sizez'):
            parm = box.parm(name)
            self.assertEqual(parm.eval(), 1.0)
            self.assertEqual(parm._native_state['instance_state_origin'], 'test_injected_native_api')
            self.assertEqual(parm._template.raw['default_status'], 'NOT_CAPTURED')
            value, channel = addon._fx_scene_parameter_readback(parm)
            self.assertEqual(value, 1.0)
            self.assertTrue(channel['evaluated_available'])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bridge-verifier-mock-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def current_release_fixture(self):
        source = self.root/'current-source'
        release = self.root/'extracted-release'
        layout = {'files':['SKILL.md', 'scripts/install_runtime.py', 'references/use.md'],
                  'runtime_packages':['dcc-task-runtime'], 'plugins':['houdini'],
                  'deployment_trees':['packages','tools'], 'deployment_resources':['docs/card.json']}
        sources = {
            'skills/houdini-bridge/SKILL.md':'SKILL.md',
            'skills/houdini-bridge/scripts/install_runtime.py':'scripts/install_runtime.py',
            'skills/houdini-bridge/references/use.md':'references/use.md',
            'packages/dcc-task-runtime/pyproject.toml':'runtime/dcc-task-runtime/pyproject.toml',
            'packages/dcc-task-runtime/src/dcc_task_runtime/__init__.py':'runtime/dcc-task-runtime/src/dcc_task_runtime/__init__.py',
            'plugins/houdini/addon.py':'plugins/houdini/addon.py',
            'tools/generator.py':'deploy/tools/generator.py', 'docs/card.json':'deploy/docs/card.json'}
        for relative, packaged in sources.items():
            origin=source/relative; origin.parent.mkdir(parents=True,exist_ok=True)
            origin.write_text(relative+'\n',encoding='utf-8')
            target=release/packaged; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(origin.read_bytes())
        layout_file=source/'tools/release_layout.json'
        layout_file.write_text(json.dumps({'skills':{'houdini-bridge':layout}}),encoding='utf-8')
        for path in (source/'packages').rglob('*'):
            if path.is_file():
                target=release/'deploy'/path.relative_to(source)
                target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(path.read_bytes())
        target=release/'deploy/tools/release_layout.json'; target.write_bytes(layout_file.read_bytes())
        return source,release

    def test_current_release_binds_every_layout_section_before_install(self):
        source,release=self.current_release_fixture()
        import build_release
        with mock.patch.object(build_release,'locate_package_source',return_value=source/'packages/dcc-task-runtime/src'):
            result=lifecycle._verify_current_release_source(release,'houdini-bridge',source)
            self.assertEqual(result['files_verified'],11)
            for relative in ('SKILL.md','scripts/install_runtime.py','references/use.md',
                             'runtime/dcc-task-runtime/src/dcc_task_runtime/__init__.py',
                             'plugins/houdini/addon.py','deploy/tools/generator.py','deploy/docs/card.json'):
                path=release/relative; before=path.read_bytes(); path.write_bytes(before+b'stale')
                with self.subTest(relative=relative),self.assertRaisesRegex(ValueError,'changed='):
                    lifecycle._verify_current_release_source(release,'houdini-bridge',source)
                path.write_bytes(before)

    def test_current_release_rejects_new_source_omission_and_old_extra_file(self):
        source,release=self.current_release_fixture()
        import build_release
        with mock.patch.object(build_release,'locate_package_source',return_value=source/'packages/dcc-task-runtime/src'):
            added=source/'tools/new-required-worker.py'; added.write_text('required\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'missing=.*new-required-worker'):
                lifecycle._verify_current_release_source(release,'houdini-bridge',source)
            added.unlink()
            (release/'scripts/old-installer.py').write_text('obsolete\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'unexpected=.*old-installer'):
                lifecycle._verify_current_release_source(release,'houdini-bridge',source)

    def test_lifecycle_rejects_stale_top_level_bytes_before_installer(self):
        source,release=self.current_release_fixture()
        (release/'scripts/install_runtime.py').write_text('stale\n',encoding='utf-8')
        import build_release
        artifact={'skill':'houdini-bridge','sha256':'a'*64,'files':[{}],'file_manifest_sha256':'b'*64}
        with mock.patch.object(lifecycle,'__file__',str(source/'tools/verify_skill_lifecycle.py')), \
                mock.patch.object(lifecycle,'_extract',return_value=release), \
                mock.patch.object(build_release,'validate_packaged_bytes'), \
                mock.patch.object(build_release,'locate_package_source',return_value=source/'packages/dcc-task-runtime/src'), \
                mock.patch.object(lifecycle,'_invoke') as invoke:
            with self.assertRaisesRegex(ValueError,'changed=.*install_runtime'):
                lifecycle._artifact_lifecycle(self.root/'unused.zip',artifact,self.root/'user',self.root/'evidence')
            invoke.assert_not_called()

    def test_generated_session_uses_same_trial_and_saves_after_terminal(self):
        server = mock.Mock()
        server.rpc.return_value = {'capabilities':{}}
        trials = iter([{'operation_id':'owned-operation','state':'RUNNING'},
                       {'operation_id':'owned-operation','state':'SUCCEEDED','stop_confirmed':True}])
        calls = []
        def tool(name, arguments):
            calls.append((name, arguments))
            if name=='catalog': return {'assets':[{'asset_id':'first'},{'asset_id':'second'}]}
            if name=='graph_propose': return {'graph_id':'registered-graph'}
            if name=='graph_trial': return next(trials)
            if name=='graph_status': return {'operation_id':'owned-operation','state':'RUNNING'}
            if name=='task_save': return {'saved_scene_id':'owned-save'}
            return {}
        server.tool.side_effect = tool
        with mock.patch.object(lifecycle.time,'sleep'):
            result = lifecycle._generated_graph_session(server,{'nodes':[]})
        self.assertEqual(result['saved']['saved_scene_id'],'owned-save')
        self.assertEqual([arguments for name,arguments in calls if name=='graph_trial'],
            [{'graph_id':'registered-graph','request_id':'installed-trial'}]*2)
        self.assertEqual(calls[-1],('task_save',{}))
        self.assertEqual(len([name for name,arguments in calls if name=='submit_observation']),2)

    def test_generated_session_rejects_changed_operation_and_unconfirmed_stop(self):
        for changed in (True,False):
            with self.subTest(changed=changed):
                server = mock.Mock()
                server.rpc.return_value = {}
                def tool(name,arguments):
                    if name=='catalog': return {'assets':[]}
                    if name=='graph_propose': return {'graph_id':'graph'}
                    if name=='graph_trial': return {'operation_id':'operation','state':'RUNNING' if changed else 'SUCCEEDED','stop_confirmed':False}
                    if name=='graph_status': return {'operation_id':'foreign','state':'SUCCEEDED'}
                    return {}
                server.tool.side_effect = tool
                with mock.patch.object(lifecycle.time,'sleep'), self.assertRaises(RuntimeError):
                    lifecycle._generated_graph_session(server,{})
                self.assertFalse(any(call.args[0]=='task_save' for call in server.tool.call_args_list))

    def test_worker_route_accepts_prepared_snapshot_and_rejects_original_or_escaped_job(self):
        control = self.root/'generated/control'
        snapshot = control/'snapshot'
        worker = snapshot/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
        worker.parent.mkdir(parents=True)
        worker.write_text('raise SystemExit(0)\n',encoding='utf-8')
        result = control/'jobs/graph-jobs/operation/attempt-1/result.json'
        job = {'repo_root':str(snapshot),'root':str(control/'jobs'),'validation_scope':'software_test','result_path':str(result)}
        binding = {'control':str(control)}
        with mock.patch.object(lifecycle,'_check_closure_binding',return_value=(self.root/'deploy',snapshot)):
            actual = lifecycle._closure_runner(worker,['--job',json.dumps(job)],binding)
            self.assertEqual(actual,(self.root/'deploy',snapshot,result.parent))
            for changed in (dict(job,validation_scope='host_construction_only'),
                            dict(job,result_path=str(self.root/'escaped/result.json')),
                            dict(job,repo_root=str(self.root/'deploy'))):
                with self.assertRaises(RuntimeError):
                    lifecycle._closure_runner(worker,['--job',json.dumps(changed)],binding)
            with self.assertRaisesRegex(RuntimeError,'not a bundled'):
                lifecycle._closure_runner(self.root/'deploy/packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py',[],binding)

    def test_owned_host_runner_requires_template_paths_nonce_and_no_warmup(self):
        from houdini_bridge.task_host import RUNNER_TEMPLATE
        control = self.root/'generated/control'
        snapshot = control/'snapshot'
        worker = control/'houdini-task-host/task_host_runner.py'
        worker.parent.mkdir(parents=True)
        parameters = {'addon_libs':str(snapshot/'plugins/houdini/python3.11libs'),'task_id':'task',
            'stop_file':str(worker.parent/'host.stop'),'ready_file':str(worker.parent/'host.ready'),
            'poll_seconds':.01,'max_seconds':120,'warmup':False,'launch_nonce':'owned-nonce'}
        worker.write_text(RUNNER_TEMPLATE.format(**parameters),encoding='utf-8')
        environment = {'BRIDGE_OWNED_SUPERVISOR_IDENTITY':json.dumps({'task_id':'task','launch_nonce':'owned-nonce'})}
        with mock.patch.dict(os.environ,environment), mock.patch.object(lifecycle,'_check_closure_binding',return_value=(self.root/'deploy',snapshot)):
            self.assertEqual(lifecycle._closure_runner(worker,[],{'control':str(control)})[2],worker.parent)
            worker.write_text(RUNNER_TEMPLATE.format(**dict(parameters,warmup=True)),encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'scope changed'):
                lifecycle._closure_runner(worker,[],{'control':str(control)})
            worker.write_text(RUNNER_TEMPLATE.format(**parameters)+'print("injected")\n',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'content'):
                lifecycle._closure_runner(worker,[],{'control':str(control)})

    def binding_fixture(self):
        target = self.root/'installed'
        deployment = target/'versions/generation/deploy'
        verifier = deployment/'tools/verify_skill_lifecycle.py'
        verifier.parent.mkdir(parents=True)
        verifier.write_text('installed-verifier\n',encoding='utf-8')
        state = target/'closure-evidence'
        control = state/'generated/control'
        snapshot = control/'snapshot'
        relative = 'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
        for base in (deployment,snapshot):
            path = base/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('installed-worker\n',encoding='utf-8')
        manifest = control/'snapshot-manifest.json'
        manifest.write_text(json.dumps({'files':[{'path':relative,'sha256':lifecycle._sha256(deployment/relative)}]}),encoding='utf-8')
        api = state/'native-api/nuke.py'
        api.parent.mkdir()
        api.write_text(lifecycle._NUKE_API,encoding='utf-8')
        binding = {'scope':'software_native_api_only','verifier':str(verifier),'verifier_sha256':lifecycle._sha256(verifier),
            'state':str(state),'control':str(control),'snapshot':str(snapshot),
            'snapshot_manifest_sha256':lifecycle._sha256(manifest),'nuke_api_sha256':lifecycle._sha256(api)}
        (state/'software-bootstrap.py').write_bytes(lifecycle._bootstrap_source(binding).encode('utf-8'))
        return verifier,deployment,snapshot,binding

    def test_snapshot_binding_rejects_changed_manifest_snapshot_api_and_bootstrap(self):
        verifier,deployment,snapshot,binding = self.binding_fixture()
        with mock.patch.object(lifecycle,'__file__',str(verifier)):
            self.assertEqual(lifecycle._check_closure_binding(binding),(deployment,snapshot))
            for path in (snapshot/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py',
                         Path(binding['control'])/'snapshot-manifest.json',
                         Path(binding['state'])/'native-api/nuke.py',
                         Path(binding['state'])/'software-bootstrap.py'):
                with self.subTest(path=path.name):
                    original = path.read_bytes()
                    path.write_bytes(original+b'changed')
                    with self.assertRaises(RuntimeError): lifecycle._check_closure_binding(binding)
                    path.write_bytes(original)

    def test_evidence_excludes_native_auth_tokens_and_keys(self):
        source = self.root/'user/installed/closure-evidence'
        source.mkdir(parents=True)
        for name in ('receipt.key','session.token','host.json','production-hosts.json','launch.json','credential-secret.json'):
            (source/name).write_bytes(b'sensitive')
        (source/'completion.json').write_bytes(b'completed')
        retained = self.root/'retained'
        entries = lifecycle._retain_evidence(self.root/'user',retained)
        self.assertEqual([entry['path'] for entry in entries],['closure-evidence/completion.json'])
        self.assertEqual(entries[0]['sha256'],hashlib.sha256(b'completed').hexdigest())

    def test_unknown_signed_stop_preserves_original_isolated_state(self):
        from dcc_task_runtime import owned_process
        with mock.patch.object(owned_process,'read_receipt',return_value=None):
            with lifecycle._lifecycle_workspace(self.root) as isolated:
                supervisor = isolated/'installed/closure-evidence/owned-supervisor'
                supervisor.mkdir(parents=True)
                (supervisor/'receipt.key').write_bytes(b'original-current-key')
                (supervisor/'intent.json').write_text('{"identity":{"operation_id":"operation"}}',encoding='utf-8')
            self.assertTrue(isolated.exists())
            self.assertTrue((supervisor/'receipt.key').is_file())
        with mock.patch.object(owned_process,'read_receipt',return_value={'exit_code':0}):
            with lifecycle._lifecycle_workspace(self.root) as completed:
                supervisor = completed/'owned-supervisor'
                supervisor.mkdir()
                (supervisor/'receipt.key').write_bytes(b'fresh-current-key')
                (supervisor/'intent.json').write_text('{"identity":{}}',encoding='utf-8')
                snapshot = completed/'saved.hip'
                snapshot.write_bytes(b'owned snapshot')
                snapshot.chmod(stat.S_IREAD)
            self.assertFalse(completed.exists())

    def test_readonly_saved_snapshot_evidence_can_be_retained_again(self):
        source = self.root/'user/installed/closure-evidence/saved.hip'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'owned snapshot')
        source.chmod(stat.S_IREAD)
        retained = self.root/'retained'
        lifecycle._retain_evidence(self.root/'user', retained)
        copied = retained/'closure-evidence/saved.hip'
        copied.chmod(stat.S_IREAD)
        entries = lifecycle._retain_evidence(self.root/'user', retained)
        self.assertEqual(copied.read_bytes(), b'owned snapshot')
        self.assertEqual(entries[0]['sha256'], lifecycle._sha256(source))

    def test_native_api_is_standalone_and_main_thread_checked(self):
        namespace = {'__name__':'nuke'}
        exec(compile(lifecycle._NUKE_API,'isolated/nuke.py','exec'),namespace)
        self.assertEqual(namespace['NUKE_VERSION_STRING'],'17.0v1')
        node = namespace['createNode']('Read')
        node.setName('Read1')
        self.assertIs(namespace['toNode']('Read1'),node)
        with mock.patch.object(namespace['threading'],'get_ident',return_value=-1), self.assertRaisesRegex(RuntimeError,'off main thread'):
            namespace['allNodes']()
        self.assertNotIn('test_nuke_task_host',lifecycle._NUKE_API)
        self.assertNotIn('software_host_bootstrap',lifecycle._bootstrap_source({'verifier':'installed.py','verifier_sha256':'a'*64}))

    def test_native_api_supports_actual_nuke_addon_readback_without_server(self):
        api = types.ModuleType('nuke')
        exec(compile(lifecycle._NUKE_API,'isolated/nuke.py','exec'),api.__dict__)
        with mock.patch.dict(sys.modules,{'nuke':api}), mock.patch.dict(os.environ,lifecycle._software_environment(self.root),clear=True):
            spec = importlib.util.spec_from_file_location('_lifecycle_native_nuke',ROOT/'plugins/nuke/nuke_bridge_addon.py')
            addon = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(addon)
            api.scriptClear()
            read = api.createNode('Read')
            read.setName('Read1')
            write = api.createNode('Write')
            write.setName('Write1')
            write.setInput(0,read)
            actual = addon.dispatch('get_node',{'name':'Write1'})
            self.assertEqual(actual['class'],'Write')
            self.assertEqual(actual['inputs'],['Read1'])
            self.assertIsNone(addon._SERVER)

    def test_signed_stop_rejects_missing_wrong_pid_or_unsuccessful_worker(self):
        from dcc_task_runtime import owned_process
        directory = self.root/'supervisor'
        directory.mkdir()
        for event in ('started','stopped'):
            (directory/(event+'.json')).write_text('{}',encoding='utf-8')
        success = {'exit_code':0, 'execution_protocol':1, 'supervisor_exit_code':0,
                   'execution_result':'succeeded', 'descendant_result_unobserved':False,
                   'stop_reason':None, 'evidence_source':'software_fixture'}
        with mock.patch.object(owned_process,'read_receipt',side_effect=[{'pid':31},success]):
            self.assertTrue(lifecycle._signed_stop(directory,{'operation_id':'operation'},31,successful=True)['signature_verified_in_isolated_run'])
        for receipts in ([None,None],[{'pid':32},success],[{'pid':31},{'exit_code':7}],
                         [{'pid':31},{'exit_code':0}]):
            with mock.patch.object(owned_process,'read_receipt',side_effect=receipts),self.assertRaises(RuntimeError):
                lifecycle._signed_stop(directory,{},31,successful=True)

    def test_installed_closure_uses_production_hosts_and_derives_worker_gate(self):
        from contextlib import ExitStack
        from dcc_task_runtime import owned_process
        import prepare_workbuddy_graph
        import native_schema_test_boundary
        from vfx_pipeline import production_hosts, workbuddy_assembly
        for changed in (False,True):
            with self.subTest(changed_worker_command=changed):
                target = self.root/'中文 空格'/('changed' if changed else 'normal')/'installed'
                deployment = target/'versions/generation/deploy'
                verifier = deployment/'tools/verify_skill_lifecycle.py'
                verifier.parent.mkdir(parents=True)
                verifier.write_text('installed verifier fixture\n',encoding='utf-8')
                state = target/'closure-evidence'
                control = state/'generated/control'
                snapshot = control/'snapshot'
                directory = control/'jobs/graph-jobs/operation/attempt-1'
                worker = snapshot/'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
                host_runner = control/'houdini-task-host/task_host_runner.py'
                host_records = {}
                captured = {}
                stop = {'signature_verified_in_isolated_run':True,'started':{'pid':2101}}
                def prepare(destination,**kwargs):
                    captured.update(kwargs)
                    control.mkdir(parents=True)
                    (control/'run.json').write_text(json.dumps({'production_host':kwargs['production_host_config']}),encoding='utf-8')
                    (control/'snapshot-manifest.json').write_text('{"files":[]}',encoding='utf-8')
                    for path in (worker,host_runner):
                        path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_text('owned runner fixture\n',encoding='utf-8')
                    for kind,pid in (('houdini',2102),('nuke',2103)):
                        work = control/(kind+'-task-host')
                        work.mkdir(exist_ok=True)
                        owner = {'directory':str(work/'supervisor'),'identity':{'task_id':'task','launch_nonce':kind}}
                        (work/'supervisor-binding.json').write_text(json.dumps(owner),encoding='utf-8')
                        host_records[kind] = {'work_dir':str(work),'supervisor_dir':owner['directory'],
                            'supervisor_identity':owner['identity'],'expected_identity':{'pid':pid}}
                    (control/'production-hosts.json').write_text(json.dumps({'hosts':host_records}),encoding='utf-8')
                    return {'control':control}
                server = mock.Mock()
                server.close.return_value = 0
                server.command = ['python','server.py','--backend','production','--software-processes']
                server.requests = [{'method':'tools/call','params':{'name':'graph_trial',
                    'arguments':{'graph_id':'graph','request_id':'installed-trial'}}}]
                server.responses = []
                topology = {'houdini_obj:/geo':'/obj/geo','houdini_sop:/geo/box':'/obj/geo/box',
                            'houdini_sop:/geo/rasterize':'/obj/geo/rasterize'}
                verification = {'hip_path':str(directory/'operation.hip'),'hip_sha256':hashlib.sha256(b'worker hip').hexdigest(),
                    'nodes_verified':True,'parameters_verified':True,'connections_verified':True}
                def session(server,proposal):
                    directory.mkdir(parents=True)
                    (directory/'operation.hip').write_bytes(b'worker hip')
                    saved = state/'saved.hip'
                    saved.write_bytes(b'task saved hip')
                    command = [lifecycle._python(),str(state/'software-bootstrap.py'),str(worker),'--job',json.dumps({'operation_id':'operation'})]
                    if changed: command[2] = str(self.root/'foreign.py')
                    stop['started']['argv_sha256'] = hashlib.sha256(owned_process._canonical(command)).hexdigest()
                    supervisor = directory/'owned-supervisor'
                    supervisor.mkdir()
                    (supervisor/'intent.json').write_text(json.dumps({'command':command}),encoding='utf-8')
                    (directory/'inputs.json').write_text(json.dumps({'software_launch_script':str(state/'software-bootstrap.py'),
                        'software_launch_script_sha256':lifecycle._sha256(state/'software-bootstrap.py')}),encoding='utf-8')
                    for output,runner,pid in ((directory,worker,2101),(host_runner.parent,host_runner,2102)):
                        (output/'installed-imports.json').write_text(json.dumps({'vfx_pipeline':str(snapshot/'packages/vfx-pipeline/src/vfx_pipeline/__init__.py')}),encoding='utf-8')
                        (output/'runner-evidence.json').write_text(json.dumps({'scope':'software_native_api_only','runner':str(runner),
                            'runner_sha256':lifecycle._sha256(runner),'pid':pid,
                            'snapshot_manifest_sha256':lifecycle._sha256(control/'snapshot-manifest.json'),
                            'verifier_sha256':lifecycle._sha256(verifier)}),encoding='utf-8')
                    return {'initialize':{'capabilities':{}},'health':{},'graph':{'graph_id':'graph'},
                        'trial':{'operation_id':'operation','state':'SUCCEEDED','stop_confirmed':True},
                        'saved':{'path':str(saved),'sha256':lifecycle._sha256(saved),'saved_scene_id':'saved'}}
                client = mock.Mock()
                def readback(command,arguments):
                    if command=='scene.open_hip': return {'path':arguments['path']}
                    if command=='node.parms': return {'parms':{'voxelsize':.25,'attributes':'density temperature v'}}
                    native = {'/obj/geo':'Obj/geo','/obj/geo/box':'Sop/box','/obj/geo/rasterize':'Sop/volumerasterizeattributes'}
                    return {'type':native[arguments['path']],'inputs':['/obj/geo/box'] if arguments['path'].endswith('rasterize') else []}
                client.call.side_effect = readback
                stops = {'houdini':{'returncode':0,'receipt':{'confirmed_exit':True}},'nuke':{'stopped':True}}
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(lifecycle,'__file__',str(verifier)))
                    stack.enter_context(mock.patch.object(prepare_workbuddy_graph,'prepare_graph',side_effect=prepare))
                    stop_hosts = stack.enter_context(mock.patch.object(production_hosts,'stop_hosts',return_value=stops))
                    stack.enter_context(mock.patch.object(lifecycle,'_MCPProcess',return_value=server))
                    stack.enter_context(mock.patch.object(lifecycle,'_generated_graph_session',side_effect=session))
                    stack.enter_context(mock.patch.object(lifecycle,'_check_closure_binding',return_value=(deployment,snapshot)))
                    stack.enter_context(mock.patch.object(lifecycle,'_graph_completion',return_value=({'verification':verification,'topology':{'nodes':topology}},stop,directory)))
                    stack.enter_context(mock.patch.object(lifecycle,'_signed_stop',return_value={'signature_verified_in_isolated_run':True}))
                    stack.enter_context(mock.patch.dict(sys.modules, {}))
                    api_459 = types.SimpleNamespace(node=lambda path: mock.Mock())
                    stack.enter_context(mock.patch.object(lifecycle,'_closure_459_static_api',
                        return_value=({'passed':True},api_459)))
                    def fresh_21_api(*args,**kwargs):
                        sys.modules['hou']=types.SimpleNamespace(node=lambda path: types.SimpleNamespace())
                        return client,None
                    stack.enter_context(mock.patch.object(workbuddy_assembly,'software_host_client',side_effect=fresh_21_api))
                    stack.enter_context(mock.patch.object(native_schema_test_boundary,'constrain_hou'))
                    stack.enter_context(mock.patch.object(lifecycle,'_installed_paths',return_value={}))
                    stack.enter_context(mock.patch.dict(os.environ,{}))
                    receipt = lifecycle._installed_closure(target)
                self.assertEqual(receipt['passed'],not changed)
                self.assertEqual(receipt['checks']['generated_server_dispatched_owned_worker'],not changed)
                stop_hosts.assert_called_once_with(control)
                server.close.assert_called_once()
                for kind in ('houdini','nuke'):
                    config = captured['production_host_config' if kind=='houdini' else 'production_nuke_config']
                    self.assertEqual(config['application'],kind)
                    self.assertEqual(config['lifecycle'],'task_owned')
                    self.assertEqual(config['evidence_source'],'software_test')
                    self.assertEqual(config['session_seconds'],120)
                    self.assertEqual(config['resource_budget']['roots'],[str(state)])
                self.assertNotIn('GraphJobService',lifecycle._installed_closure.__code__.co_names)


if __name__=='__main__':
    unittest.main()
