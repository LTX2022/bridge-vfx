"""Host phase ordering with software-only process/transport boundaries; no DCC."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from vfx_pipeline import production_hosts
from vfx_pipeline.workbuddy_assembly import _DeferredTaskBoundary
from dcc_task_runtime import native_scope, owned_process
from test_native_scope import software_scope


class DeferredHostLifecycleTests(unittest.TestCase):
    def test_houdini_ready_uses_existing_scoped_session_budget_only(self):
        from houdini_bridge import task_host
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            root=Path(temp)
            for scoped in (False, True):
                config={'executable':'/not-launched/hython','version':'21.0.631','session_seconds':117.,
                        'supervisor_executable':'/not-launched/python','evidence_source':'software_test',
                        'resource_budget':{'native_scope':{'path':'scope','sha256':'f'*64}} if scoped else {}}
                with mock.patch.object(task_host,'start',return_value=0) as start, \
                     mock.patch.object(production_hosts,'_shared_env',return_value={}):
                    production_hosts._launch_h(config,root/'work','task',root/'control',root/'scheduler',root)
                args=start.call_args.args[0]
                self.assertEqual(args.ready_timeout,117. if scoped else 10)
                self.assertEqual(args.max_seconds,117.)

    def test_validated_writer_identity_can_be_revalidated_without_trusting_changed_facts(self):
        import copy
        import sys
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temp:
            root=Path(temp).resolve();python=Path(sys.executable).resolve()
            common={'lifecycle':'task_owned','executable':str(python),'supervisor_executable':str(python),
                'task_root':str(root),'resource_budget':{'roots':[str(root)],'max_bytes':536870912},
                'session_seconds':120,'evidence_source':'software_test'}
            h=dict(common,application='houdini',version='21.0.631',writer_executable={
                'path':str(python),'version':'21.0.631','sha256':hashlib.sha256(python.read_bytes()).hexdigest()})
            n=dict(common,application='nuke',version='17.0v1')
            options={'controller_root':root/'control','repo_root':Path(__file__).resolve().parents[2],
                'allow_software_processes':True}
            first=production_hosts.validate_deployments(h,n,**options)
            self.assertEqual(production_hosts.validate_deployments(*first,**options),first)
            for changed in ('stat','extra','version'):
                bad=copy.deepcopy(first[0]);writer=bad['writer_executable']
                if changed=='stat':writer['image']['stat']['inode']+=1
                elif changed=='extra':writer['caller_verified']=True
                else:writer['version']='22.0.459'
                with self.subTest(changed=changed),self.assertRaises(ValueError):
                    production_hosts.validate_deployments(bad,first[1],**options)

    def stopped(self, ticket):
        directory=Path(ticket['directory']);directory.mkdir(exist_ok=True)
        (directory/'receipt.key').write_bytes(b'explicit-software-receipt-key')
        start={'schema':owned_process.SCHEMA,'event':'started','identity':ticket['identity'],
               'pid':123,'execution_protocol':1,'observed_at':ticket['admitted_at']}
        owned_process._signed_write(directory,start)
        owned_process._signed_write(directory,dict(start,event='stopped',observed_at=ticket['admitted_at']+.01,
            started_sha256=hashlib.sha256(owned_process._canonical(start)).hexdigest(),
            observed_by='owned_child_wait',exit_code=0,descendant_result_unobserved=False,
            stop_reason=None,supervisor_exit_code=0,execution_result='succeeded'))

    def test_deferred_phases_keep_exact_two_houdini_one_nuke_allowances(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();scope=native_scope.NativeScope(software_scope(root))
            events=[];tickets=[]
            def deferred(kind):
                def factory():
                    role=kind+'-host'
                    ticket=scope.admit(role,root/('host-'+str(len(tickets))),{'software':len(tickets)},heavy=False)
                    tickets.append(ticket);events.append(role)
                    return mock.Mock()
                boundary=_DeferredTaskBoundary(kind,factory)
                boundary.bind_task('software-task')
                return boundary
            h=deferred('houdini');n=deferred('nuke')
            registry=mock.Mock();registry._operation_source=None
            h.bind_artifact_registry(registry);n.bind_artifact_registry(registry)
            # Controller setup, health metadata, and discovering the completion
            # method before a graph is terminal consume no native start.
            self.assertIsNone(h.real_process_bound)
            marker=h.mark_graph_trial_complete
            self.assertEqual(scope.snapshot()['dcc_starts'],0)
            events.append('graph-worker-completed')
            marker('software-task',{'state':'SUCCEEDED'})
            self.assertEqual(events,['graph-worker-completed','houdini-host'])
            h.call('save',{});self.assertEqual(scope.snapshot()['dcc_starts'],1)
            self.stopped(tickets[0]);scope.finish(tickets[0])
            h2=deferred('houdini');h2.call('reopen',{})
            n.call('prepare_composite',{})
            n.call('readback',{})
            self.assertEqual(events,['graph-worker-completed','houdini-host','houdini-host','nuke-host'])
            with self.assertRaisesRegex(ValueError,'STARTS_EXHAUSTED'):
                deferred('houdini').call('reopen',{})
            with self.assertRaisesRegex(ValueError,'STARTS_EXHAUSTED'):
                deferred('nuke').call('readback',{})
            self.assertEqual(scope.snapshot()['dcc_starts'],3)

    def test_expired_cached_boundary_does_not_create_replacement(self):
        transport=mock.Mock();transport.call.side_effect=RuntimeError('host stopped')
        factory=mock.Mock(return_value=transport)
        boundary=_DeferredTaskBoundary('houdini',factory);boundary.bind_task('software-task')
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'host stopped'):boundary.call('save',{})
        factory.assert_called_once()

    def test_single_host_selection_preserves_complete_deployment_fingerprint(self):
        configs=[{'application':'houdini'},{'application':'nuke','task_root':'/private/tmp/software-hosts',
                  'evidence_source':'software_test'}]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            hbound={'application':'houdini'}
            from nuke_bridge import task_host
            with mock.patch.object(production_hosts,'validate_deployments',return_value=configs), \
                 mock.patch.object(production_hosts,'_launch_h') as launch_h, \
                 mock.patch.object(production_hosts,'_h_config',return_value=hbound), \
                 mock.patch.object(task_host,'start') as launch_n:
                h,n=production_hosts.ensure_hosts({}, {},task_id='software-task',controller_root=root,
                    repo_root=root,scheduler_root=root,host_kinds={'houdini'})
                self.assertEqual(h,hbound);self.assertIsNone(n)
                launch_h.assert_called_once();launch_n.assert_not_called()
                state=json.loads((root/'production-hosts.json').read_text())
                expected=hashlib.sha256(json.dumps(configs,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
                self.assertEqual(state['config_sha256'],expected)
                self.assertEqual(set(state['hosts']),{'houdini'})

    def test_detached_output_verification_never_activates_live_host(self):
        live=mock.Mock(side_effect=AssertionError('live host must not start'))
        detached=mock.Mock();detached.call.return_value={'state':'COMPLETED'}
        boundary=_DeferredTaskBoundary('houdini',live,lambda:detached)
        boundary.bind_task('software-task')
        self.assertEqual(boundary.call('output.verify.status',{'verification_id':'v'}),{'state':'COMPLETED'})
        live.assert_not_called()

class HostPhaseBudgetTests(unittest.TestCase):
    def fixture(self, root, kind='nuke', *, budget=120.0):
        nonce='software-nonce';work=root/('nuke-host-'+nonce if kind=='nuke' else 'houdini-task-host')
        directory=work/('supervisor' if kind=='nuke' else 'supervisor-'+nonce)
        directory.mkdir(parents=True)
        identity={'task_id':'software-task','launch_nonce':nonce}
        if kind=='nuke':identity.update(plugin_build='software-build',session_id='software-session',process_generation=1)
        expected=dict(identity,pid=123,version='17.0v1' if kind=='nuke' else '21.0.631',plugin_build='software-build')
        command=[str(Path(__import__('sys').executable).resolve()),'software_fixture.py']
        (directory/'receipt.key').write_bytes(b'explicit-software-only-key')
        (directory/'intent.json').write_text(json.dumps({'command':command,'budget_seconds':120}))
        start={'schema':owned_process.SCHEMA,'event':'started','identity':identity,'pid':123,
               'observed_at':100.0,'execution_protocol':1,
               'argv_sha256':hashlib.sha256(owned_process._canonical(command)).hexdigest()}
        if budget is not None:start['budget_seconds']=budget
        owned_process._signed_write(directory,start)
        config={'application':kind,'work_dir':str(work),'task_root':str(root),
                'expected_identity':expected,'version':expected['version'],'plugin_build':'software-build',
                'executable':command[0],'supervisor_dir':str(directory),'supervisor_identity':identity,
                'lifecycle':'task_owned','transport':'tcp' if kind=='nuke' else 'http',
                'host':'127.0.0.1','port':1}
        if kind=='houdini':(work/'supervisor-binding.json').write_text(json.dumps({'directory':str(directory),'identity':identity}))
        return config,directory,start

    def test_both_hosts_bound_actual_child_budget_after_setup_and_stop_reserve(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ('houdini','nuke'):
                config,_,_=self.fixture(Path(temp).resolve()/kind,kind)
                with mock.patch.object(production_hosts.time,'time',return_value=140):
                    self.assertEqual(production_hosts.host_phase_budget(config),74.0)
                    self.assertEqual(production_hosts.host_phase_budget(config,20),20.0)
                with mock.patch.object(production_hosts.time,'time',return_value=214):
                    with self.assertRaisesRegex(ValueError,'PHASE_BUDGET_EXHAUSTED'):
                        production_hosts.host_phase_budget(config)

    def test_actual_python_supervisor_signs_the_budget_used_by_phase_admission(self):
        import sys
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();nonce='software-python';work=root/('nuke-host-'+nonce)
            identity={'task_id':'software-task','launch_nonce':nonce,'plugin_build':'software-build',
                      'session_id':'software-session','process_generation':1}
            executable=str(Path(sys.executable).resolve())
            handle=owned_process.launch([executable,'-c','import time; time.sleep(1)'],
                directory=work/'supervisor',identity=identity,supervisor_executable=executable,budget_seconds=20)
            config={'application':'nuke','work_dir':str(work),'task_root':str(root),
                'expected_identity':dict(identity,pid=handle.pid,version='17.0v1'),
                'version':'17.0v1','plugin_build':'software-build','executable':executable,
                'supervisor_dir':str(work/'supervisor'),'supervisor_identity':identity}
            try:
                self.assertEqual(handle.started['budget_seconds'],20)
                actual=production_hosts.host_phase_budget(config)
                self.assertGreater(actual,0);self.assertLessEqual(actual,14)
            finally:
                handle.terminate();handle.wait(timeout=5)

    def test_unsigned_intent_budget_cannot_replace_missing_signed_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            config,_,_=self.fixture(Path(temp).resolve(),budget=None)
            with mock.patch.object(production_hosts.time,'time',return_value=101):
                with self.assertRaisesRegex(ValueError,'DEADLINE_UNVERIFIED'):
                    production_hosts.host_phase_budget(config)

    def test_stopped_or_mismatched_identity_refuses_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            config,directory,start=self.fixture(Path(temp).resolve())
            config['expected_identity']['launch_nonce']='foreign'
            with self.assertRaisesRegex(ValueError,'DEADLINE_UNVERIFIED'):production_hosts.host_phase_budget(config)
            config['expected_identity']['launch_nonce']='software-nonce'
            owned_process._signed_write(directory,dict(start,event='stopped',observed_at=101,
                started_sha256=hashlib.sha256(owned_process._canonical(start)).hexdigest(),
                observed_by='owned_child_wait',exit_code=0,descendant_result_unobserved=False,
                stop_reason=None,supervisor_exit_code=0,execution_result='succeeded'))
            with self.assertRaisesRegex(ValueError,'DEADLINE_UNVERIFIED'):production_hosts.host_phase_budget(config)

    def test_nuke_boundary_injects_remaining_budget_at_final_dispatch(self):
        from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();config,_,_=self.fixture(root)
            transport=mock.Mock();transport.health.return_value={'task_host_identity':config['expected_identity']}
            transport.call.return_value={'operation_id':'software-render'}
            boundary=_ConfiguredBoundary(kind='nuke',transport=transport,config=config,state_dir=root/'boundary')
            boundary.bind_task('software-task')
            with mock.patch.object(production_hosts.time,'time',return_value=140):
                boundary.call('render_write',{'request_id':'software-request'})
            self.assertEqual(transport.call.call_args.args[1]['budget_seconds'],74.0)
            transport.call.reset_mock()
            with mock.patch.object(production_hosts.time,'time',return_value=214):
                with self.assertRaisesRegex(ValueError,'PHASE_BUDGET_EXHAUSTED'):
                    boundary.call('render_write',{'request_id':'another-request'})
            transport.call.assert_not_called()
