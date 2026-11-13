"""Project configuration and generated-snapshot media deployment probes."""
import argparse
import base64
import hashlib
import json
import io
import os
import shutil
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests' / 'helpers'))
from media_stdio_boundary import MediaLineReader
from prepare_workbuddy_graph import prepare_graph, validate_media_config
import preflight_real_acceptance as preflight


def static_decoder_fixture(root):
    """Create a static executable fixture; none of these tests invokes it."""
    executable = root / ('fixed-ffmpeg.exe' if os.name == 'nt' else 'fixed-ffmpeg')
    if os.name == 'nt':
        shutil.copyfile(sys.executable, executable)
    else:
        executable.write_text('#!/bin/sh\nexit 99\n')
    executable.chmod(0o700)
    return executable


@contextmanager
def nonexecutable_fixture(executable):
    """Use POSIX mode bits or an explicit bottom Windows access API boundary."""
    executable.chmod(0o600)
    if os.name == 'nt':
        native_access = os.access
        def access(path, mode):
            return False if Path(path) == executable and mode == os.X_OK else native_access(path, mode)
        with mock.patch('os.access', side_effect=access):
            yield
    else:
        yield


STDIO_BOUNDARY_FIXTURE = r'''
import atexit, hashlib, json, os, runpy, sys
from pathlib import Path
server = Path(sys.argv[1]).resolve()
control = server.parent
snapshot = control / 'snapshot'
for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
    sys.path.insert(0, str(snapshot / 'packages' / package / 'src'))
import houdini_bridge.client, nuke_bridge.client
calls = []
class DeniedDCCTransport:
    def __init__(self, *args, **kwargs):
        calls.append('DCC transport construction')
        raise AssertionError('DCC transport is forbidden in this media test')
houdini_bridge.client.HoudiniClient = DeniedDCCTransport
nuke_bridge.client.NukeClient = DeniedDCCTransport
manifest = json.loads((control / 'run.json').read_text())
fixed = str(Path(manifest['controller_media']['ffmpeg_executable']).resolve())
argv = []
network = []
def observe(event, args):
    if event == 'subprocess.Popen':
        if isinstance(args[1], str):
            import ctypes
            from ctypes import wintypes
            count = ctypes.c_int()
            parse = ctypes.WinDLL('shell32', use_last_error=True).CommandLineToArgvW
            parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            parse.restype = ctypes.POINTER(wintypes.LPWSTR)
            release = ctypes.WinDLL('kernel32', use_last_error=True).LocalFree
            release.argtypes = [wintypes.HLOCAL]
            release.restype = wintypes.HLOCAL
            parsed = parse(args[1], ctypes.byref(count))
            if not parsed:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                command = [parsed[index] for index in range(count.value)]
            finally:
                release(ctypes.cast(parsed, wintypes.HLOCAL))
        else:
            command = list(args[1])
        argv.append(command)
        if command[0] != fixed: raise AssertionError('unexpected process executable')
    if event == 'socket.connect':
        network.append('socket.connect')
        raise AssertionError('network is forbidden in this media test')
sys.addaudithook(observe)
def save_boundaries():
    Path(os.environ['BRIDGE_MEDIA_BOUNDARY_RECEIPT']).write_text(json.dumps({
        'server_path':str(server), 'server_sha256':hashlib.sha256(server.read_bytes()).hexdigest(),
        'dcc_transport_calls':calls, 'network_calls':network, 'actual_decoder_argv':argv,
        'fixture':'only bottom DCC transports denied; actual generated server.py stdio executed'}, indent=2)+'\n')
atexit.register(save_boundaries)
sys.argv = [str(server), *sys.argv[2:]]
runpy.run_path(str(server), run_name='__main__')
'''



def run_generated_media_probe(root: Path, ffmpeg: str) -> dict:
    """Run actual generated server.py stdio; deny only bottom DCC transports."""
    root.mkdir(parents=True, exist_ok=False)
    config = {'ffmpeg_executable':ffmpeg,
              'attachment_limits':{'max_attachments':2, 'max_attachment_bytes':1024*1024,
                                   'max_total_bytes':2*1024*1024, 'max_dimension':512},
              'sequence_diagnostics':{'expected_frames':[0,2], 'active_frames':[0,2], 'max_temporal_delta':1}}
    config_path = root / 'controller-media.json'
    config_path.write_text(json.dumps(config, indent=2)+'\n')
    prepare_graph(root / 'generated-project', app=None, scheduler_root=root / 'scheduler',
                  media_config=json.loads(config_path.read_text()))
    control = root / 'generated-project' / 'control'
    movie = control / 'assets' / 'synthetic.mp4'
    encode_argv = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                   '-i', 'testsrc=size=16x16:rate=2:duration=2', '-c:v', 'mpeg4',
                   '-pix_fmt', 'yuv420p', '-threads', '1', str(movie)]
    encoded = subprocess.run(encode_argv, capture_output=True, text=True, timeout=15)
    (root / 'ffmpeg-encode.stdout.log').write_text(encoded.stdout)
    (root / 'ffmpeg-encode.stderr.log').write_text(encoded.stderr)
    if encoded.returncode:
        raise AssertionError('ffmpeg encode failed: ' + encoded.stderr)
    manifest_path = control / 'run.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['assets'].append({'asset_id':'synthetic-video', 'file':'assets/synthetic.mp4',
        'sha256':hashlib.sha256(movie.read_bytes()).hexdigest(), 'classification':'controller_generated_synthetic',
        'mime_type':'video/mp4', 'version':1})
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    bundle_path = control.parent / 'bundle-manifest.json'
    bundle = json.loads(bundle_path.read_text())
    for item in bundle['files']:
        if item['path'] == 'control/run.json':
            item['sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    bundle['files'].append({'path':'control/assets/synthetic.mp4', 'sha256':hashlib.sha256(movie.read_bytes()).hexdigest()})
    bundle_path.write_text(json.dumps(bundle, indent=2)+'\n')
    (root / 'source-registration.json').write_text(json.dumps(manifest['assets'][-1], indent=2)+'\n')
    probe_path = root / 'stdio-boundary-fixture.py'
    probe_path.write_text(STDIO_BOUNDARY_FIXTURE)
    mcp = json.loads((control.parent/'project/.workbuddy/mcp.json').read_text())['mcpServers']['bridge-hy3-graph']
    official_argv = [mcp['command'], *mcp['args']]
    assert '--backend' not in official_argv
    probe_argv = [mcp['command'], '-I', str(probe_path), str(control/'server.py')]
    env = {**os.environ, 'PYTHONPATH':'', 'BRIDGE_SKILLS_STATE_ROOT':str(root/'state'),
           'HOUDINI_BRIDGE_STATE_DIR':str(root/'host-state'), 'BRIDGE_SKILLS_SCHEDULER_ROOT':str(root/'scheduler'),
           'BRIDGE_MEDIA_BOUNDARY_RECEIPT':str(root/'boundary-evidence.json')}
    env.pop('BRIDGE_ARTIFACT_LEDGER_ROOT', None)
    proc = subprocess.Popen(probe_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    reader = MediaLineReader(proc.stdout)
    requests, responses, receipts = [], [], []
    identifier = 0
    def rpc(method, params):
        nonlocal identifier
        identifier += 1
        request = {'jsonrpc':'2.0','id':identifier,'method':method,'params':params}
        requests.append(request)
        proc.stdin.write(json.dumps(request)+'\n'); proc.stdin.flush()
        line = reader.response_line()
        response = json.loads(line); responses.append(response)
        assert 'result' in response, response
        return response['result']
    def tool(name, arguments, rejected=False):
        response = rpc('tools/call', {'name':name,'arguments':arguments})
        receipts.append({'name':name,'arguments':arguments,'result':response})
        assert response['isError'] is rejected, response
        return response
    def text_result(response):
        return json.loads(response['content'][0]['text'])
    try:
        rpc('initialize', {'protocolVersion':'2024-11-05','clientInfo':{'name':'media-deployment-software-probe'},'capabilities':{}})
        notification = {'jsonrpc':'2.0','method':'notifications/initialized'}
        requests.append(notification); proc.stdin.write(json.dumps(notification)+'\n'); proc.stdin.flush()
        health = text_result(tool('health', {}))
        catalog = text_result(tool('catalog', {}))
        video = next(item for item in catalog['assets'] if item['asset_id']=='synthetic-video')
        assert video['kind']=='video' and video['mime_type']=='video/mp4'
        assert video['sha256']==manifest['assets'][-1]['sha256']
        assert video['observation_asset_id']=='synthetic-video'
        observation = {'description':'Software test received the registered extracted images; no model or human visual assessment.',
                       'uncertainties':['Motion correctness and visual content were not assessed.']}
        tool('submit_observation', {'asset_id':'synthetic-video','observation':observation,'request_id':'before-frames'}, rejected=True)
        noframes_argv = [*probe_argv,'--handoff-contract']
        noframes_env = {**env,'BRIDGE_MEDIA_BOUNDARY_RECEIPT':str(root/'before-frames-boundary-evidence.json')}
        noframes = subprocess.run(noframes_argv,capture_output=True,text=True,timeout=15,env=noframes_env)
        (root/'before-frames-handoff.stdout.log').write_text(noframes.stdout)
        (root/'before-frames-handoff.stderr.log').write_text(noframes.stderr)
        assert noframes.returncode!=0 and 'media_video_frames before observing' in noframes.stdout
        extraction = text_result(tool('media_video_frames', {'asset_id':'synthetic-video','frames':[0,2]}))
        assert extraction['source_asset_id']=='synthetic-video' and extraction['frames']==[0,2] and not extraction['replayed']
        ids = extraction['asset_ids']
        attached = tool('media_attachments', {'asset_ids':ids})
        frame_media = tool('media', {'asset_id':ids[0]})
        assert frame_media['content'][0]==attached['content'][0]
        catalog_after = text_result(tool('catalog', {}))
        derived = [next(item for item in catalog_after['assets'] if item['asset_id']==key) for key in ids]
        for block, record, frame in zip(attached['content'], derived, [0,2]):
            assert record['kind']=='image' and record['mime_type']=='image/png'
            assert (record['width'],record['height'])==(512,512)
            assert record['parent_asset_id']=='synthetic-video' and record['parent_sha256']==video['sha256']
            assert record['source_frame']==frame and record['version']==1
            assert hashlib.sha256(base64.b64decode(block['data'],validate=True)).hexdigest()==record['sha256']
        other = text_result(tool('media_video_frames', {'asset_id':'synthetic-video','frames':[1,3]}))
        replay = text_result(tool('media_video_frames', {'asset_id':'synthetic-video','frames':[0,2]}))
        assert replay['replayed'] is True and replay['asset_ids']==ids
        assert len({extraction['media_basis_id'],other['media_basis_id'],replay['media_basis_id']})==3
        # An interleaved caller may select another valid frame set before this
        # caller submits; only its explicit controller selection is the basis.
        later = text_result(tool('media_video_frames', {'asset_id':'synthetic-video','frames':[1,3]}))
        request = {'asset_id':'synthetic-video','observation':observation,'request_id':'after-frames',
                   'media_basis_id':replay['media_basis_id']}
        tool('submit_observation', {key:value for key,value in request.items() if key!='media_basis_id'}, rejected=True)
        tool('submit_observation', {**request,'media_basis_id':'selection-'+'0'*32}, rejected=True)
        observed = text_result(tool('submit_observation', request))
        assert observed['asset_id']=='synthetic-video' and observed['media_basis']['source_sha256']==video['sha256']
        assert observed['media_basis']['source_version']==1
        assert [item['asset_id'] for item in observed['media_basis']['frames']]==ids
        assert observed['media_basis']['media_basis_id']==replay['media_basis_id']
        retried = text_result(tool('submit_observation', request))
        assert retried['replayed'] is True and retried['receipt']==observed['receipt']
        assert retried['media_basis']==observed['media_basis']
        tool('submit_observation', {**request,'media_basis_id':later['media_basis_id']}, rejected=True)
        assert observed['media_basis']['motion_correctness_verified'] is False
        assert observed['model_identity_verified'] is False and observed['reference_analysis_route_verified'] is False
        for image in manifest['assets'][:-1]:
            tool('media', {'asset_id':image['asset_id']})
            tool('submit_observation', {'asset_id':image['asset_id'],'observation':observation,
                 'request_id':'image-'+image['asset_id']})
        metrics = text_result(tool('media_sequence_diagnostics', {'asset_ids':ids,'frame_numbers':[0,2]}))
        assert metrics['status']=='PASS' and metrics['visual_verified'] is False
        assert text_result(tool('media_video_frames', {'asset_id':'synthetic-video','frames':[0,2]}))['replayed'] is True
        tool('submit_observation', {'asset_id':ids[0],'observation':observation,'request_id':'derived-as-source'}, rejected=True)
        tool('media_attachments', {'asset_ids':ids+[manifest['assets'][0]['asset_id']]}, rejected=True)
        tool('media_video_frames', {'asset_id':'synthetic-video','frames':[0],'path':'/unregistered.mp4'}, rejected=True)
        tool('media_sequence_diagnostics', {'asset_ids':ids,'frame_numbers':[0,2],'active_frames':[0]}, rejected=True)
    finally:
        proc.stdin.close()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait(timeout=5)
        stderr = proc.stderr.read();proc.stdout.close();proc.stderr.close()
        (root/'server.stderr.log').write_text(stderr)
        (root/'server.requests.jsonl').write_text(''.join(json.dumps(item)+'\n' for item in requests))
        (root/'server.responses.jsonl').write_text(''.join(json.dumps(item)+'\n' for item in responses))
        (root/'tools-receipts.json').write_text(json.dumps(receipts,indent=2)+'\n')
    assert proc.returncode==0, stderr
    boundary = json.loads((root/'boundary-evidence.json').read_text())
    assert boundary['dcc_transport_calls']==[] and boundary['network_calls']==[]
    assert len(boundary['actual_decoder_argv'])==2
    assert boundary['actual_decoder_argv'][0][0]==str(Path(ffmpeg).resolve())
    with closing(sqlite3.connect(control/'diagnostic.sqlite3')) as db:
        operation_count = db.execute('SELECT COUNT(*) FROM operation_registry').fetchone()[0]
        records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM media_derivatives ORDER BY asset_id')]
    assert operation_count==0
    with closing(sqlite3.connect(control/'pipeline.sqlite3')) as db:
        spec = json.loads(db.execute('SELECT spec_json FROM pipeline_tasks').fetchone()[0])
        captures = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM pipeline_records WHERE category='connector_observation_capture'")]
        capture = next(item for item in captures if item['asset_id']=='synthetic-video')
    reference = next(item for item in spec['references'] if item['asset_id']=='synthetic-video')
    assert reference['kind']=='video' and reference['sha256']==video['sha256']
    assert capture['asset_id']=='synthetic-video' and capture['asset_sha256']==video['sha256']
    handoff_argv = [*probe_argv,'--handoff-contract']
    handoff_env = {**env,'BRIDGE_MEDIA_BOUNDARY_RECEIPT':str(root/'handoff-boundary-evidence.json')}
    handoff = subprocess.run(handoff_argv,capture_output=True,text=True,timeout=15,env=handoff_env)
    (root/'handoff.stdout.log').write_text(handoff.stdout);(root/'handoff.stderr.log').write_text(handoff.stderr)
    assert handoff.returncode==0, handoff.stdout+handoff.stderr
    contract = json.loads(handoff.stdout)
    assert contract['ready'] is True and len(contract['response_template']['observation_record_ids'])==3
    assert contract['video_observation_basis']['synthetic-video']==observed['media_basis']
    assert contract['provider_identity_verified'] is False and contract['route_execution_verified'] is False
    handoff_boundary = json.loads((root/'handoff-boundary-evidence.json').read_text())
    assert handoff_boundary['dcc_transport_calls']==[] and handoff_boundary['actual_decoder_argv']==[]
    frame_path = control / next(record['file'] for record in records if record['asset_id']==ids[0])
    original = frame_path.read_bytes()
    try:
        frame_path.write_bytes(original+b'tampered')
        changed_env = {**env,'BRIDGE_MEDIA_BOUNDARY_RECEIPT':str(root/'changed-frame-boundary-evidence.json')}
        changed = subprocess.run(handoff_argv,capture_output=True,text=True,timeout=15,env=changed_env)
        (root/'changed-frame-handoff.stdout.log').write_text(changed.stdout)
        (root/'changed-frame-handoff.stderr.log').write_text(changed.stderr)
        assert changed.returncode!=0 and 'MEDIA_VERSION_CHANGED' in changed.stdout
    finally:
        frame_path.write_bytes(original)
    production_argv = [*official_argv,'--backend','production']
    production = subprocess.run(production_argv,capture_output=True,text=True,timeout=15,env=env)
    (root/'production-missing-config.stdout.log').write_text(production.stdout)
    (root/'production-missing-config.stderr.log').write_text(production.stderr)
    assert production.returncode!=0 and 'PRODUCTION_CONFIG_REQUIRED' in production.stdout
    (root/'argv.json').write_text(json.dumps({'ffmpeg_encode':encode_argv,'ffmpeg_encode_returncode':encoded.returncode,
        'official_mcp_argv':official_argv,'actual_server_with_bottom_transport_denial':probe_argv,'server_returncode':proc.returncode,
        'handoff_contract':handoff_argv,'handoff_returncode':handoff.returncode,'changed_frame_handoff_returncode':changed.returncode,
        'before_frames_handoff':noframes_argv,'before_frames_handoff_returncode':noframes.returncode,
        'production_missing_config':production_argv,'production_returncode':production.returncode},indent=2)+'\n')
    summary = {'status':'SOFTWARE_PASS','entry':'actual generated control/server.py default diagnostic stdio',
        'source':manifest['assets'][-1], 'derivatives':records,'catalog_source':video,'reference':reference,
        'observation_receipt':observed,'trusted_observation_capture':capture,'health':health,
        'video_selections':[extraction,other,replay,later],'retry_receipt':retried,
        'handoff_contract':contract,'before_frames_handoff':'REJECTED','changed_frame_handoff':'REJECTED',
        'configured_executable':ffmpeg,'consumed_executable':boundary['actual_decoder_argv'][0][0],
        'actual_decoder_argv':boundary['actual_decoder_argv'],'dcc_calls':boundary['dcc_transport_calls'],
        'network_calls':boundary['network_calls'],'operation_count':operation_count,'sequence_diagnostics':metrics,
        'production_missing_config':'REJECTED','snapshot_manifest_sha256':hashlib.sha256((control/'snapshot-manifest.json').read_bytes()).hexdigest(),
        'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'native_dcc':'NOT_RUN','workbuddy_hy3':'NOT_RUN','visual_acceptance':'NOT_RUN'}
    (root/'media-probe-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


class ControllerMediaDeploymentTests(unittest.TestCase):
    def test_stdout_eof_with_live_stderr_reaches_bounded_cleanup(self):
        interpreter = str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())
        child = subprocess.Popen([interpreter, '-u', '-c',
            'import os,sys;os.close(sys.stdout.fileno());sys.stdin.read();'
            'sys.stderr.write("closed-stdout");sys.stderr.flush();os._exit(0)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            reader = MediaLineReader(child.stdout)
            with self.assertRaisesRegex(AssertionError, 'closed stdout'):
                reader.response_line(timeout=5)
            self.assertIsNone(child.poll())
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            stderr = child.stderr.read()
            child.stdout.close()
            child.stderr.close()
        self.assertEqual(child.returncode, 0)
        self.assertEqual(stderr, 'closed-stdout')

    def test_actual_pipe_reader_preserves_lines_eof_timeout_and_read_failure(self):
        reader = MediaLineReader(io.StringIO('first\nsecond\n'))
        self.assertEqual(reader.readline(), 'first\n')
        self.assertEqual(reader.readline(), 'second\n')
        self.assertEqual(reader.readline(), '')
        with self.assertRaisesRegex(AssertionError, 'response timeout'):
            reader.readline(timeout=0)
        class FailedStream:
            def __iter__(self):
                raise OSError('pipe failed')
        failed = MediaLineReader(FailedStream())
        with self.assertRaisesRegex(AssertionError, 'pipe read failed'):
            failed.readline()

    def test_windows_shebang_scripts_are_not_direct_decoder_executables(self):
        import prepare_workbuddy_graph as generator
        import vfx_pipeline.controller_media as controller_media
        from vfx_pipeline.controller_media import FixedVideoDecoder
        from vfx_pipeline.media_readiness import MediaReadinessError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            windows_access = SimpleNamespace(name='nt', access=lambda path, mode: True, X_OK=os.X_OK)
            for name in ('fixed-ffmpeg', 'fixed-ffmpeg.py', 'fixed-ffmpeg.cmd'):
                executable = root / name
                executable.write_text('#!/usr/bin/env python3\nraise SystemExit(0)\n')
                executable.chmod(0o700)
                with self.subTest(name=name), mock.patch.object(generator, 'os', windows_access), \
                     mock.patch.object(controller_media, 'os', windows_access), \
                     mock.patch.object(preflight, 'os', windows_access), \
                     mock.patch('subprocess.run', side_effect=AssertionError('static only')):
                    with self.assertRaisesRegex(ValueError, 'not executable'):
                        validate_media_config({'ffmpeg_executable': str(executable)})
                    with self.assertRaisesRegex(MediaReadinessError, 'UNAVAILABLE'):
                        FixedVideoDecoder(str(executable))
                    dependency = preflight.media_dependency({'controller_media': {'ffmpeg_executable': str(executable)}},
                        {'references': [{'kind': 'video'}]}, {})
                    self.assertEqual(dependency['status'], 'BLOCKED')
                    self.assertFalse(dependency['executable'])

    def test_fixed_native_decoder_preserves_argv_and_propagates_process_failures(self):
        from vfx_pipeline.controller_media import FixedVideoDecoder
        from vfx_pipeline.media_readiness import MediaReadinessError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = static_decoder_fixture(root)
            decoder = FixedVideoDecoder(str(executable))
            source = root / 'registered.mp4'
            source.write_bytes(b'negative process boundary fixture')
            with mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 7)) as launch:
                with self.assertRaisesRegex(MediaReadinessError, 'VIDEO_DECODE_FAILED: rc=7'):
                    decoder.decode(source, root / 'failure', [0, 2])
            command = launch.call_args.args[0]
            self.assertEqual(command[:6], [str(executable.resolve()), '-nostdin', '-hide_banner', '-loglevel', 'error',
                                          '-protocol_whitelist'])
            self.assertEqual(command[6], 'file,pipe')
            self.assertEqual(command[command.index('-i') + 1], str(source))
            self.assertIn("select='eq(n\\,0)+eq(n\\,2)'", command[command.index('-vf') + 1])
            self.assertNotIn('shell', launch.call_args.kwargs)
            for label, error in [('timeout', subprocess.TimeoutExpired(command, 30)), ('launch', OSError('refused'))]:
                with self.subTest(label=label), mock.patch('subprocess.run', side_effect=error):
                    with self.assertRaisesRegex(MediaReadinessError, 'VIDEO_DECODE_FAILED: ' + type(error).__name__):
                        decoder.decode(source, root / label, [0])

    def test_explicit_selection_survives_interleave_replay_restart_and_rejects_wrong_basis(self):
        from vfx_pipeline.controller_media import ControllerMediaService, FixedPngDecoder
        from vfx_pipeline.workbuddy_graph_mcp import GraphRun, GraphMCP
        from test_media_readiness import _png

        class Decoder:
            calls = 0
            def decode(self, source, output, frames):
                self.calls += 1
                output.mkdir(parents=True)
                records = []
                for index, frame in enumerate(frames):
                    path = output / ('frame-%03d.png' % index)
                    path.write_bytes(_png(frame*30+1, width=4, height=4))
                    records.append({'source_frame':frame, 'path':str(path), **FixedPngDecoder().decode(path)})
                return {'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                        'frames':records, 'time_basis':'zero_based_decoded_frame_index'}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = []
            for name, data, mime in [('video', b'software-video-fixture', 'video/mp4'),
                                     ('other', b'other-software-video-fixture', 'video/mp4'),
                                     ('image', _png(1), 'image/png')]:
                path = root / (name + ('.png' if mime=='image/png' else '.mp4'))
                path.write_bytes(data)
                assets.append({'asset_id':name, 'file':path.name, 'mime_type':mime, 'version':1,
                               'sha256':hashlib.sha256(data).hexdigest(), 'classification':'controller_generated_synthetic'})
            manifest = root / 'run.json'
            manifest.write_text(json.dumps({'schema':'bridge.workbuddy.diagnostic_run/1.0',
                'run_id':'selection-test', 'assets':assets, 'construction_authorized':True}))
            decoder = Decoder()
            def restart():
                run = GraphRun(manifest, object())
                run.media_service = ControllerMediaService(run, video_decoder=decoder)
                return run
            run = restart()
            with mock.patch('subprocess.Popen', side_effect=AssertionError('no process allowed')), \
                 mock.patch('socket.socket', side_effect=AssertionError('no network allowed')):
                first = run.media_video_frames('video', [0,2])
                second = run.media_video_frames('video', [1,3])
                replay = run.media_video_frames('video', [0,2])
                later = run.media_video_frames('video', [1,3])
                self.assertEqual(decoder.calls, 2)
                self.assertTrue(replay['replayed'])
                self.assertEqual(first['asset_ids'], replay['asset_ids'])
                self.assertEqual(len({item['media_basis_id'] for item in (first,second,replay,later)}), 4)
                payload = {'description':'Software fixture observation only', 'uncertainties':['No visual assessment.']}
                with self.assertRaisesRegex(ValueError, 'media_basis_id required'):
                    run.submit_observation('video', payload, 'missing-selection')
                for source, selection in [('video','selection-'+'0'*32), ('other', replay['media_basis_id'])]:
                    with self.subTest(source=source), self.assertRaises(ValueError):
                        run.submit_observation(source, payload, 'wrong-selection', selection)
                receipt = run.submit_observation('video', payload, 'stable-observation', replay['media_basis_id'])
                basis = receipt['media_basis']
                self.assertEqual([item['source_frame'] for item in basis['frames']], [0,2])
                self.assertEqual(basis['media_basis_id'], replay['media_basis_id'])
                resumed = restart()
                retried = resumed.submit_observation('video', payload, 'stable-observation', replay['media_basis_id'])
                self.assertTrue(retried['replayed'])
                self.assertEqual(retried['receipt'], receipt['receipt'])
                self.assertEqual(retried['media_basis'], basis)
                with self.assertRaisesRegex(ValueError, 'another observation'):
                    resumed.submit_observation('video', payload, 'stable-observation', later['media_basis_id'])
                exported = resumed.export()
                self.assertEqual(exported['observations'][0]['receipt']['media_basis'], basis)
                selections = [event['payload']['media_basis_id'] for event in exported['events']
                              if event['kind']=='video_frames_selected']
                self.assertEqual(selections, [item['media_basis_id'] for item in (first,second,replay,later)])
                mismatched_frames = {**basis, 'frames':resumed._video_observation_basis('video',second['media_basis_id'])['frames']}
                for altered in [mismatched_frames, {**basis, 'media_basis_id':second['media_basis_id']},
                                {**basis, 'source_asset_id':'other'}, {**basis, 'source_version':2},
                                {**basis, 'source_sha256':'f'*64}, {**basis, 'source_mime_type':'video/webm'},
                                {**basis, 'selection_receipt':{**basis['selection_receipt'], 'event_hash':'f'*64}}]:
                    with self.subTest(altered=altered), self.assertRaises(ValueError):
                        resumed.validate_reference_media('video', observed_basis=altered)
                resumed.assets['video']['version'] = 2
                with self.assertRaisesRegex(ValueError, 'version changed'):
                    resumed.validate_reference_media('video', observed_basis=basis)
                resumed.assets['video']['version'] = 1
                image_receipt = resumed.submit_observation('image', payload, 'image-observation')
                self.assertNotIn('media_basis', image_receipt)
                with self.assertRaisesRegex(ValueError, 'only valid for source video'):
                    resumed.submit_observation('image', payload, 'image-selection', replay['media_basis_id'])
                tools = GraphMCP(resumed).tools
                self.assertEqual(sum(item['name']=='submit_observation' for item in tools), 1)
                schema = next(item['inputSchema'] for item in tools if item['name']=='submit_observation')
                self.assertIn('media_basis_id', schema['properties'])
                self.assertNotIn('media_basis_id', schema['required'])
                self.assertFalse(next(item for item in tools if item['name']=='media_video_frames')['annotations']['idempotentHint'])

    def test_config_rejects_missing_nonexecutable_unknown_and_invalid_policies_before_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = static_decoder_fixture(root)
            valid = {'ffmpeg_executable':str(executable)}
            self.assertEqual(validate_media_config(valid), valid)
            invalid = [({}, 'absolute local'), ({'ffmpeg_executable':'ffmpeg'}, 'absolute local'),
                ({'ffmpeg_executable':str(root/'absent')}, 'file missing'),
                ({**valid,'command':['ffmpeg']}, 'unknown fields'),
                ({**valid,'ffmpeg_sha256':'0'*64}, 'unknown fields'),
                ({**valid,'software_test':{}}, 'unknown fields'),
                ({**valid,'attachment_limits':{'max_attachments':True}}, 'positive integer'),
                ({**valid,'attachment_limits':{'max_total_bytes':0}}, 'positive integer'),
                ({**valid,'attachment_limits':{'extra':1}}, 'existing attachment'),
                ({**valid,'sequence_diagnostics':{'expected_frames':[0,2],'active_frames':[1]}}, 'subset'),
                ({**valid,'sequence_diagnostics':{'expected_frames':[2,0],'active_frames':[0]}}, 'sorted distinct'),
                ({**valid,'sequence_diagnostics':{'expected_frames':[0],'active_frames':[0],'max_temporal_delta':True}}, 'finite nonnegative'),
                ({**valid,'sequence_diagnostics':{'expected_frames':[0],'active_frames':[0],'max_temporal_delta':float('nan')}}, 'finite nonnegative')]
            for index, (config, error) in enumerate(invalid):
                with self.subTest(index=index), mock.patch('subprocess.run', side_effect=AssertionError('configuration must be static')):
                    destination = root / ('invalid-%s' % index)
                    with self.assertRaisesRegex(ValueError, error):
                        prepare_graph(destination, app=None, media_config=config)
                    self.assertFalse(destination.exists())
            with nonexecutable_fixture(executable), self.assertRaisesRegex(ValueError, 'not executable'):
                prepare_graph(root/'nonexecutable', app=None, media_config=valid)
            self.assertFalse((root/'nonexecutable').exists())

    def test_video_preflight_dependency_is_static_specific_and_nonvideo_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = static_decoder_fixture(Path(directory))
            video = {'references':[{'asset_id':'video','kind':'video'}]}
            with mock.patch('subprocess.run', side_effect=AssertionError('preflight must not launch')), \
                 mock.patch('subprocess.Popen', side_effect=AssertionError('preflight must not launch')):
                optional = preflight.media_dependency({}, {}, {})
                self.assertEqual(optional['status'], 'NOT_REQUIRED')
                for stale in ({'ffmpeg_executable':'/missing/ffmpeg'}, {'unknown':True}, None):
                    self.assertEqual(preflight.media_dependency({'controller_media':stale}, {}, {})['status'], 'NOT_REQUIRED')
                    self.assertEqual(preflight.media_dependency({}, {}, {}, media_config=stale)['errors'], [])
                missing = preflight.media_dependency({}, video, {})
                self.assertEqual(missing['status'], 'BLOCKED')
                self.assertIn('controller_media.ffmpeg_executable', missing['errors'][0])
                config = {'controller_media':{'ffmpeg_executable':str(executable)}}
                ready = preflight.media_dependency(config, video, {})
                self.assertEqual(ready['status'], 'READY')
                self.assertEqual(ready['resolved_executable'], str(executable.resolve()))
                self.assertEqual(ready['observed_sha256'], hashlib.sha256(executable.read_bytes()).hexdigest())
                self.assertFalse(ready['ffmpeg_started'])
                with nonexecutable_fixture(executable):
                    self.assertEqual(preflight.media_dependency(config, video, {})['status'], 'BLOCKED')
                    self.assertIn('not executable', preflight.media_dependency(config, video, {})['errors'][0])
                self.assertTrue(any('resource confirmation' in error for error in preflight.validate({}, video, {})))
                self.assertTrue(any('before/after operation snapshots' in error for error in preflight.validate({}, video, {})))

    def test_actual_video_generated_snapshot_consumes_config_and_registered_derivatives(self):
        ffmpeg = shutil.which('ffmpeg')
        self.assertIsNotNone(ffmpeg, 'local fixed ffmpeg required; no automatic download')
        with tempfile.TemporaryDirectory() as directory:
            result = run_generated_media_probe(Path(directory)/'probe', ffmpeg)
            self.assertEqual(result['status'], 'SOFTWARE_PASS')
            self.assertEqual(result['operation_count'], 0)
            self.assertEqual(result['consumed_executable'], str(Path(ffmpeg).resolve()))
            self.assertEqual(sorted(record['source_frame'] for record in result['derivatives']), [0,1,2,3])
            self.assertTrue(all(record['parent_sha256'] == result['source']['sha256'] for record in result['derivatives']))


if __name__ == '__main__':
    if '--evidence-root' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--evidence-root', type=Path, required=True)
        parser.add_argument('--ffmpeg', required=True)
        args = parser.parse_args()
        print(json.dumps(run_generated_media_probe(args.evidence_root, args.ffmpeg), indent=2))
    else:
        unittest.main()
