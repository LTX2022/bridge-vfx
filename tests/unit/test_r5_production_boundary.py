"""Production assembly regressions; replace transport only, never the facade."""
import json
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
from pathlib import Path
from vfx_pipeline.workbuddy_assembly import _ConfiguredBoundary, ProductionBoundaryError

IDENTITY = {'task_id':'owner-A','session_id':'session','launch_nonce':'nonce','pid':123,
            'process_generation':'generation','plugin_build':'a'*64,'scene_epoch':0,'version':'17.0v1'}

class NativeTransport:
    def __init__(self, ignore_edits=False):
        self.calls=[]; self.ignore_edits=ignore_edits
        self.nodes={'Read1':{'name':'Read1','class':'Read','knobs':{'file':'/wrong.exr','colorspace':'linear','raw':True},'inputs':[]},
                    'Write1':{'name':'Write1','class':'Write','knobs':{'file':'/wrongout.exr','colorspace':'linear','raw':True,'premultiplied':True},'inputs':[]}}
    def health(self):return {"task_host_identity":dict(IDENTITY)}
    def call(self, cmd, params):
        self.calls.append((cmd,params))
        if cmd=='get_node':return json.loads(json.dumps(self.nodes[params['name']]))
        if cmd=='set_knob' and not self.ignore_edits:
            knobs=self.nodes[params['node']]['knobs']
            if params['knob'] not in knobs:raise ValueError('native knob missing')
            knobs[params['knob']]=params['value']
        if cmd=='connect_nodes' and not self.ignore_edits:
            if 'src' not in params or params['src'] is not None and params['src'] not in self.nodes:raise ValueError('connect requires an existing source or explicit None')
            inputs=self.nodes[params['dst']]['inputs'];index=params.get('input_index',0)
            while len(inputs)<=index:inputs.append(None)
            inputs[index]=params['src']
        return {}

class ProductionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.transport=NativeTransport()
        self.client=_ConfiguredBoundary(kind='nuke',transport=self.transport,config={
            'expected_identity':IDENTITY,'evidence_source':'software_test','application':'nuke','version':'17.0v1','plugin_build':'a'*64,'transport':'tcp',
            'host':'127.0.0.1','port':54321,'task_root':str(self.root),'executable':'/not-started/Nuke'},state_dir=self.root)
        self.client.bind_task('owner-A')
        self.artifact={'artifact_id':'input-1','pattern':str(self.root/'input.%03d.exr'),
          'usable_as_render_input':True,'verification':{'frame_set':[1,2]},'colorspace':'linear','premultiplied':False}
    def binding(self,premultiplied=False):
        return self.client.render_binding('owner-A',str(self.root/'output.%03d.exr'),[1,2],'linear',premultiplied,artifact_binding=self.artifact)
    def test_houdini_exact_versions_and_current_acceptance_defaults(self):
        import sys
        from vfx_pipeline import production_hosts
        from vfx_pipeline.domain_readiness import DomainReadinessRunner
        from vfx_pipeline.workbuddy_assembly import _production_config
        executable = str(Path(sys.executable).resolve())
        config = {'lifecycle':'task_owned', 'application':'houdini',
            'executable':executable, 'supervisor_executable':executable,
            'task_root':str(self.root), 'session_seconds':20,
            'evidence_source':'real_host', 'resource_budget':{'roots':[str(self.root)], 'max_bytes':1024},
            'transport':'http', 'port':54321, 'plugin_build':'a'*64}
        for version in ('21.0.631', '22.0.429', '22.0.459'):
            with self.subTest(version=version):
                identity = dict(IDENTITY, version=version)
                selected = dict(config, version=version, expected_identity=identity)
                validated = production_hosts._validate(selected, 'houdini', self.root,
                    Path(__file__).resolve().parents[2], False)
                self.assertEqual(validated['version'], version)
                self.assertEqual(_production_config(selected, kind='houdini')['expected_identity']['version'], version)
                selected['expected_identity'] = dict(identity, version='21.0.632')
                with self.assertRaisesRegex(ProductionBoundaryError, 'HOST_IDENTITY_REQUIRED'):
                    _production_config(selected, kind='houdini')
        with self.assertRaisesRegex(ValueError, 'PRODUCTION_VERSION_REQUIRED'):
            production_hosts._validate(dict(config, version='22.0.458'), 'houdini', self.root,
                Path(__file__).resolve().parents[2], False)
        runner = DomainReadinessRunner(task_id='defaults', output_root=self.root / 'defaults')
        self.assertEqual(runner.houdini_versions, ('21.0.631', '22.0.459'))
        self.assertEqual(self.transport.calls, [])

    def test_houdini_binding_requires_trusted_task_version_and_plugin(self):
        from vfx_pipeline import production_hosts as hosts
        work=self.root/'houdini-task-host';work.mkdir(mode=0o700)
        state=self.root/'houdini-instances/instances';state.mkdir(parents=True)
        (state/'123.json').write_text(json.dumps({'token_file':'token'}));(state/'token').write_text('private-test-token')
        identity=dict(IDENTITY,version='22.0.459')
        binding={'directory':str(work/'supervisor-nonce'),'identity':{'task_id':'owner-A','launch_nonce':'nonce'}}
        (work/'supervisor-binding.json').write_text(json.dumps(binding))
        observed=SimpleNamespace(pid=123,poll=lambda:None)
        config={'version':'22.0.459','plugin_build':'a'*64,'task_root':str(self.root)}
        for override in (None,binding):
            for source in ('ready','health'):
                for field,value in ((None,None),('task_id','other-task'),('version','22.0.429'),('plugin_build','b'*64)):
                    ready=dict(identity);actual=dict(identity)
                    if field:(ready if source=='ready' else actual)[field]=value
                    ready_bytes=json.dumps({'port':54321,'task_host_identity':ready})
                    (work/'host.ready').write_text(ready_bytes)
                    with self.subTest(override=override is not None,source=source,field=field), \
                         mock.patch.object(hosts,'OwnedProcessHandle',return_value=observed), \
                         mock.patch('houdini_bridge.client.HoudiniClient') as client:
                        client.return_value.health.return_value={'task_host_identity':actual}
                        if field:
                            with self.assertRaisesRegex(ValueError,'DEPLOYMENT_IDENTITY_MISMATCH'):
                                hosts._h_config(config,work,self.root,task_id='owner-A',binding_override=override)
                            if source=='ready':client.assert_not_called()
                        else:
                            result=hosts._h_config(config,work,self.root,task_id='owner-A',binding_override=override)
                            self.assertEqual(result['expected_identity'],identity)
                        self.assertEqual((work/'host.ready').read_text(),ready_bytes)
        foreign={**binding,'identity':{'task_id':'other-task','launch_nonce':'nonce'}}
        with mock.patch.object(hosts,'OwnedProcessHandle') as handle, mock.patch('houdini_bridge.client.HoudiniClient') as client:
            with self.assertRaisesRegex(ValueError,'UNTRUSTED_RECONCILE'):
                hosts._h_config(config,work,self.root,task_id='owner-A',binding_override=foreign)
            handle.assert_not_called();client.assert_not_called()

    def test_houdini_identity_reclaim_requires_own_signed_stop(self):
        from vfx_pipeline import production_hosts as hosts
        from houdini_bridge import task_host
        work=self.root/'houdini-task-host';work.mkdir(mode=0o700)
        ready={'task_host_identity':{'pid':123,'launch_nonce':'nonce'}}
        observed=SimpleNamespace(pid=123,directory=work/'supervisor-nonce',
            identity={'task_id':'owner-A','launch_nonce':'nonce'},poll=mock.Mock(return_value=None),receipt=mock.Mock(return_value=None))
        deployment=self.root/'production-hosts.json'
        for outcome in ('foreign-ready','unknown','persist-failure','after-persist-crash','confirmed'):
            observed.poll.return_value=None;observed.receipt.return_value=None
            payload=ready if outcome!='foreign-ready' else {'task_host_identity':{'pid':124,'launch_nonce':'foreign'}}
            (work/'host.ready').write_text(json.dumps(payload))
            hosts._atomic(deployment,{'hosts':{'houdini':{'pid':123,'launch_nonce':'nonce'}}})
            def reclaim(path,child):
                self.assertIs(child,observed)
                if outcome not in ('foreign-ready','unknown'):
                    observed.poll.return_value=0;observed.receipt.return_value={'event':'stopped'}
                return outcome not in ('foreign-ready','unknown')
            def persist():
                self.assertTrue((work/'host.ready').is_file())
                if outcome=='persist-failure':raise RuntimeError('interrupted before deployment commit')
                hosts._atomic(deployment,{'hosts':{}})
            with self.subTest(outcome=outcome),mock.patch.dict(task_host._ACTIVE_CHILDREN,{123:observed},clear=True), \
                 mock.patch.object(task_host,'_reclaim_child',side_effect=reclaim) as stop, \
                 mock.patch.object(hosts,'remove_owned_path',wraps=hosts.remove_owned_path) as remove:
                if outcome=='after-persist-crash':remove.side_effect=RuntimeError('interrupted before ready removal')
                if outcome=='confirmed':
                    hosts._reclaim_mismatched_houdini(work,'owner-A',observed,persist_stopped=persist)
                    self.assertFalse((work/'host.ready').exists());self.assertNotIn(123,task_host._ACTIVE_CHILDREN)
                elif outcome in ('persist-failure','after-persist-crash'):
                    with self.assertRaisesRegex(RuntimeError,'interrupted'):
                        hosts._reclaim_mismatched_houdini(work,'owner-A',observed,persist_stopped=persist)
                    self.assertTrue((work/'host.ready').is_file())
                    self.assertEqual(bool(json.loads(deployment.read_text())['hosts']),outcome=='persist-failure')
                    remove.side_effect=None
                    hosts._reclaim_mismatched_houdini(work,'owner-A',observed,
                        persist_stopped=lambda:hosts._atomic(deployment,{'hosts':{}}))
                    self.assertFalse((work/'host.ready').exists())
                    self.assertEqual(json.loads(deployment.read_text())['hosts'],{})
                    self.assertEqual(stop.call_count,1)
                else:
                    with self.assertRaisesRegex(ValueError,'IDENTITY_RECONCILE_REQUIRED'):
                        hosts._reclaim_mismatched_houdini(work,'owner-A',observed,persist_stopped=persist)
                    self.assertEqual(json.loads((work/'host.ready').read_text()),payload)
                    self.assertTrue(json.loads(deployment.read_text())['hosts'])
                    remove.assert_not_called()
                    if outcome=='foreign-ready':stop.assert_not_called()

        # Re-enter the complete deployment entry after both publication windows.
        # Only launcher/supervisor/transport APIs are replaced; deployment state
        # and _h_config execute their shipped paths.
        import sys
        for source in ('ready','health'):
            for window in ('before-persist','after-persist'):
                with self.subTest(source=source,window=window):
                    base=self.root/(source+'-'+window);base.mkdir();control=base/'control';work=control/'houdini-task-host'
                    task='reclaim-task';handles={};phase={'value':'good'};launches=[]
                    executable=str(Path(sys.executable).resolve());repo=Path(__file__).resolve().parents[2]
                    common={'lifecycle':'task_owned','executable':executable,'supervisor_executable':executable,
                        'task_root':str(base),'resource_budget':{'roots':[str(base)],'max_bytes':1048576},
                        'session_seconds':20,'evidence_source':'software_test'}
                    hconfig=dict(common,application='houdini',version='22.0.459')
                    nconfig=dict(common,application='nuke',version='17.0v1')
                    def launch(config,directory,task_id,*args):
                        directory.mkdir(exist_ok=True,mode=0o700);number=len(launches)+1;launches.append(number)
                        identity=dict(IDENTITY,task_id=task_id,version=config['version'],plugin_build=config['plugin_build'],pid=200+number,launch_nonce='launch'+str(number))
                        supervisor=directory/('supervisor-'+identity['launch_nonce']);supervisor.mkdir()
                        handle=SimpleNamespace(directory=supervisor,identity={'task_id':task_id,'launch_nonce':identity['launch_nonce']},pid=identity['pid'],stopped=False)
                        handle.poll=lambda:0 if handle.stopped else None
                        handle.receipt=lambda:{'event':'stopped'} if handle.stopped else None
                        handles[str(supervisor)]=handle;task_host._ACTIVE_CHILDREN[handle.pid]=handle
                        hosts._atomic(directory/'supervisor-binding.json',{'directory':str(supervisor),'identity':handle.identity})
                        hosts._atomic(directory/'host.ready',{'port':54321,'task_host_identity':identity})
                        state=control/'houdini-instances/instances';state.mkdir(parents=True,exist_ok=True)
                        (state/(str(handle.pid)+'.json')).write_text(json.dumps({'token_file':'token'}));(state/'token').write_text('test-token')
                    def observed(directory,identity):
                        handle=handles[str(directory)];self.assertEqual(handle.identity,identity);return handle
                    def health():
                        actual=json.loads((work/'host.ready').read_text())['task_host_identity']
                        if phase['value']=='bad-health':actual=dict(actual,version='22.0.429')
                        return {'task_host_identity':actual}
                    def reclaim(_stop,child):child.stopped=True;return True
                    nreceipt={'work_dir':str(base/'nuke-host'),'expected_identity':{'task_id':task}}
                    from nuke_bridge import task_host as nuke_host
                    with mock.patch.object(hosts,'_launch_h',side_effect=launch), \
                         mock.patch.object(hosts,'OwnedProcessHandle',side_effect=observed), \
                         mock.patch('houdini_bridge.client.HoudiniClient') as client, \
                         mock.patch.object(task_host,'_reclaim_child',side_effect=reclaim) as reclaim_call, \
                         mock.patch.dict(task_host._ACTIVE_CHILDREN,{},clear=True), \
                         mock.patch.object(nuke_host,'start',return_value=nreceipt), \
                         mock.patch.object(nuke_host,'reconnect',return_value=nreceipt):
                        client.return_value.health.side_effect=health
                        kwargs=dict(task_id=task,controller_root=control,repo_root=repo,scheduler_root=base/'scheduler',allow_software_processes=True)
                        initial=hosts.ensure_hosts(hconfig,nconfig,**kwargs)
                        prior_identity=initial[0]['expected_identity']
                        if source=='ready':
                            payload=json.loads((work/'host.ready').read_text());payload['task_host_identity']['version']='22.0.429';hosts._atomic(work/'host.ready',payload)
                        else:phase['value']='bad-health'
                        state_file=control/'production-hosts.json';write=hosts._atomic;remove_file=hosts.remove_owned_path
                        def interrupted_write(path,value):
                            if Path(path)==state_file and 'houdini' not in value.get('hosts',{}):raise RuntimeError('before-persist')
                            return write(path,value)
                        def interrupted_remove(path,**kwargs):
                            if Path(path)==work/'host.ready':raise RuntimeError('after-persist')
                            return remove_file(path,**kwargs)
                        patcher=mock.patch.object(hosts,'_atomic',side_effect=interrupted_write) if window=='before-persist' else mock.patch.object(hosts,'remove_owned_path',side_effect=interrupted_remove)
                        with patcher,self.assertRaisesRegex(RuntimeError,window):hosts.ensure_hosts(hconfig,nconfig,**kwargs)
                        self.assertTrue((work/'host.ready').is_file());self.assertEqual(reclaim_call.call_count,1)
                        self.assertEqual('houdini' in json.loads(state_file.read_text())['hosts'],window=='before-persist')
                        phase['value']='good'
                        try:recovered=hosts.ensure_hosts(hconfig,nconfig,**kwargs)
                        except ValueError as exc:
                            self.assertEqual(source,'ready')
                            self.assertEqual(str(exc),'PRODUCTION_HOST_DEPLOYMENT_IDENTITY_MISMATCH_STOP_CONFIRMED')
                            recovered=hosts.ensure_hosts(hconfig,nconfig,**kwargs)
                        self.assertNotEqual(recovered[0]['expected_identity']['pid'],prior_identity['pid'])
                        self.assertEqual(recovered[0]['expected_identity']['version'],'22.0.459')
                        self.assertEqual(reclaim_call.call_count,1);self.assertEqual(len(launches),2)
                        self.assertEqual(hosts.ensure_hosts(hconfig,nconfig,**kwargs),recovered)

    def test_cross_task_rejected_before_transport(self):
        with self.assertRaises(ProductionBoundaryError):self.client.call('get_node',{'name':'Read1','task_id':'owner-B'})
        self.assertEqual(self.transport.calls,[])
        operation = 'nrend-' + 'a' * 16
        for command in ('render_status', 'render_cancel', 'control.render_resolve'):
            for owner in (None, 'owner-B', 'owner-A'):
                with self.subTest(command=command, owner=owner):
                    self.client._operation_owners_path().write_text(json.dumps(
                        {} if owner is None else {operation: owner}))
                    params = {'task_id': operation}
                    self.transport.calls.clear()
                    if owner == 'owner-A':
                        self.client.call(command, params)
                        self.assertEqual(self.transport.calls, [(command, params)])
                    else:
                        with self.assertRaisesRegex(ProductionBoundaryError, 'OPERATION_OWNER_MISMATCH'):
                            self.client.call(command, params)
                        self.assertEqual(self.transport.calls, [])
    def test_unusable_artifact_rejected_before_mutation(self):
        self.artifact['usable_as_render_input']=False
        with self.assertRaises(ProductionBoundaryError):self.binding()
        self.assertEqual(self.transport.calls,[])
    def test_binding_sets_and_reads_actual_connection_and_paths(self):
        for premultiplied in (False,True):
            with self.subTest(premultiplied=premultiplied):
                self.artifact['premultiplied']=premultiplied
                self.transport.nodes['Read1']['knobs']['raw']=True
                self.transport.nodes['Write1']['knobs'].update(raw=True,premultiplied=not premultiplied)
                result=self.binding(premultiplied)
                self.assertTrue(result['input_binding']['connection_verified'])
                self.assertEqual(self.transport.nodes['Read1']['knobs']['file'],self.artifact['pattern'])
                self.assertEqual(self.transport.nodes['Write1']['inputs'],['Read1'])
                self.assertEqual(self.transport.nodes['Write1']['knobs']['file'],str(self.root/'output.%03d.exr'))
                self.assertIs(self.transport.nodes['Read1']['knobs']['raw'],False)
                self.assertIs(self.transport.nodes['Write1']['knobs']['raw'],False)
                self.assertIs(self.transport.nodes['Write1']['knobs']['premultiplied'],premultiplied)

    def test_binding_missing_or_wrong_native_knob_types_refuse_before_mutation(self):
        original=json.loads(json.dumps(self.transport.nodes))
        for name,knob in (('Read1','file'),('Read1','colorspace'),('Read1','raw'),
                          ('Write1','file'),('Write1','colorspace'),('Write1','raw'),('Write1','premultiplied')):
            for missing in (False,True):
                with self.subTest(name=name,knob=knob,missing=missing):
                    self.transport.nodes=json.loads(json.dumps(original));self.transport.calls.clear()
                    if missing:del self.transport.nodes[name]['knobs'][knob]
                    else:self.transport.nodes[name]['knobs'][knob]=0
                    before=json.loads(json.dumps(self.transport.nodes))
                    with self.assertRaisesRegex(ProductionBoundaryError,'NATIVE_COLOR_KNOBS_REQUIRED'):self.binding()
                    self.assertEqual(self.transport.nodes,before)
                    self.assertTrue(all(command=='get_node' for command,_ in self.transport.calls))

    def test_binding_color_or_alpha_conversion_refuses_before_mutation(self):
        for field,value in (('colorspace','other-space'),('premultiplied',True)):
            with self.subTest(field=field),mock.patch.dict(self.artifact,{field:value}):
                before=json.loads(json.dumps(self.transport.nodes));self.transport.calls.clear()
                with self.assertRaisesRegex(ProductionBoundaryError,'COLOR_CONVERSION_REQUIRED'):self.binding()
                self.assertEqual(self.transport.nodes,before)
                self.assertTrue(all(command=='get_node' for command,_ in self.transport.calls))

    def test_binding_knob_failure_or_ignored_edit_restores_before_connect(self):
        original=json.loads(json.dumps(self.transport.nodes))
        original['Read1']['knobs']['colorspace']='original-space'
        original['Write1']['knobs']['colorspace']='original-space'
        for name,knob in (('Read1','file'),('Read1','colorspace'),('Read1','raw'),
                          ('Write1','file'),('Write1','colorspace'),('Write1','raw'),('Write1','premultiplied')):
            for mode in ('raise_after_write','ignore_once'):
                with self.subTest(name=name,knob=knob,mode=mode):
                    self.transport.nodes=json.loads(json.dumps(original));self.transport.calls.clear()
                    dispatch=self.transport.call;faulted=False
                    def fault(command,params):
                        nonlocal faulted
                        if command=='set_knob' and params['node']==name and params['knob']==knob and not faulted:
                            faulted=True
                            if mode=='ignore_once':return {}
                            dispatch(command,params);raise RuntimeError('controlled native write failure')
                        return dispatch(command,params)
                    with mock.patch.object(self.transport,'call',side_effect=fault):
                        with self.assertRaises((ProductionBoundaryError,RuntimeError)):self.binding()
                    self.assertTrue(faulted);self.assertEqual(self.transport.nodes,original)
                    self.assertFalse(any(command=='connect_nodes' for command,_ in self.transport.calls))

    def test_binding_connection_failure_restores_original_source(self):
        original=json.loads(json.dumps(self.transport.nodes))
        original['OldRead']={'name':'OldRead','class':'Read','knobs':{},'inputs':[]}
        for source in (None,'OldRead'):
            for mode in ('raise_after_connect','drift_after_connect'):
                with self.subTest(source=source,mode=mode):
                    self.transport.nodes=json.loads(json.dumps(original))
                    self.transport.nodes['Write1']['inputs']=[] if source is None else [source]
                    before=json.loads(json.dumps(self.transport.nodes));dispatch=self.transport.call;faulted=False
                    def fault(command,params):
                        nonlocal faulted
                        result=dispatch(command,params)
                        if command=='connect_nodes' and params['src']=='Read1' and not faulted:
                            faulted=True
                            if mode=='raise_after_connect':raise RuntimeError('controlled native connect failure')
                            self.transport.nodes['Read1']['knobs']['raw']=True
                        return result
                    with mock.patch.object(self.transport,'call',side_effect=fault):
                        with self.assertRaises((ProductionBoundaryError,RuntimeError)) as caught:self.binding()
                    self.assertNotIn('ROLLBACK_UNCONFIRMED',str(caught.exception))
                    self.assertTrue(faulted)
                    for name in ('Read1','Write1'):self.assertEqual(self.transport.nodes[name]['knobs'],before[name]['knobs'])
                    self.assertEqual(self.transport.nodes['Write1']['inputs'],[source])

    def test_binding_rollback_failure_cannot_claim_restoration(self):
        dispatch=self.transport.call
        def fault(command,params):
            if command=='connect_nodes' and params['src'] is None:raise RuntimeError('controlled disconnect failure')
            result=dispatch(command,params)
            if command=='connect_nodes':raise RuntimeError('controlled failure after connect')
            return result
        with mock.patch.object(self.transport,'call',side_effect=fault):
            with self.assertRaisesRegex(ProductionBoundaryError,'ROLLBACK_UNCONFIRMED'):self.binding()
        self.assertEqual(self.transport.nodes['Write1']['inputs'],['Read1'])
        self.assertIs(self.transport.nodes['Read1']['knobs']['raw'],True)
        self.assertIs(self.transport.nodes['Write1']['knobs']['raw'],True)
        self.assertIs(self.transport.nodes['Write1']['knobs']['premultiplied'],True)

    def test_ignored_mutations_cannot_claim_verified(self):
        self.transport.ignore_edits=True
        with self.assertRaises(ProductionBoundaryError):self.binding()
    def test_transport_response_is_not_real_host_attestation(self):
        self.client.call('get_node',{'name':'Read1'})
        self.assertIsNot(self.client.real_nuke_bound,True)

    def test_wrong_host_session_is_rejected_before_mutation(self):
        self.transport.health=lambda:{"task_host_identity":{**IDENTITY,"session_id":"other"}}
        with self.assertRaises(ProductionBoundaryError):self.binding()
        self.assertEqual(self.transport.calls,[])
