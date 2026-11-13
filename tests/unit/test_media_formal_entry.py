"""The generated MCP subprocess serves registered media without DCC or models."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests' / 'helpers'))
from media_stdio_boundary import MediaLineReader


class FormalMediaEntryTests(unittest.TestCase):
    def test_actual_generated_media_video_and_frozen_metric_tools(self):
        from prepare_workbuddy_graph import prepare_graph
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ffmpeg = shutil.which('ffmpeg')
            self.assertIsNotNone(ffmpeg)
            prepare_graph(root / 'project', app=None, scheduler_root=root / 'scheduler', execution_profile=True,
                media_config={'ffmpeg_executable': ffmpeg,
                    'sequence_diagnostics': {'expected_frames':[0,2], 'active_frames':[0,2], 'max_temporal_delta':1}})
            control = root / 'project' / 'control'
            movie = control / 'synthetic.mp4'
            result = subprocess.run([ffmpeg, '-nostdin','-loglevel','error','-f','lavfi','-i',
                'testsrc=size=16x16:rate=2:duration=2','-c:v','mpeg4','-pix_fmt','yuv420p','-threads','1',str(movie)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest_path = control / 'run.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['assets'].append({'asset_id':'video','file':movie.name,
                'sha256':hashlib.sha256(movie.read_bytes()).hexdigest(),'classification':'controller_generated_synthetic'})
            manifest_path.write_text(json.dumps(manifest))
            env = {**os.environ, 'PYTHONPATH':'', 'BRIDGE_SKILLS_STATE_ROOT':str(root / 'state'),
                   'HOUDINI_BRIDGE_STATE_DIR':str(root / 'host-state'), 'BRIDGE_SKILLS_SCHEDULER_ROOT':str(root / 'scheduler')}
            proc = subprocess.Popen([sys.executable,'-I',str(control / 'server.py'),'--backend','software'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            reader = MediaLineReader(proc.stdout)
            identifier = 0
            def rpc(method, params):
                nonlocal identifier
                identifier += 1
                proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':identifier,'method':method,'params':params})+'\n'); proc.stdin.flush()
                line = reader.response_line()
                return json.loads(line)
            def tool(name, arguments):
                return rpc('tools/call', {'name':name, 'arguments':arguments})['result']
            try:
                rpc('initialize',{'protocolVersion':'2024-11-05','clientInfo':{'name':'media-software-test'},'capabilities':{}})
                proc.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n'); proc.stdin.flush()
                decoded = tool('media_video_frames', {'asset_id':'video','frames':[0,2]})
                self.assertFalse(decoded['isError'], decoded)
                ids = json.loads(decoded['content'][0]['text'])['asset_ids']
                attached = tool('media_attachments', {'asset_ids':ids})
                self.assertFalse(attached['isError'], attached)
                self.assertEqual([block['type'] for block in attached['content']], ['image','image'])
                metrics = tool('media_sequence_diagnostics', {'asset_ids':ids,'frame_numbers':[0,2]})
                self.assertFalse(metrics['isError'], metrics)
                receipt = json.loads(metrics['content'][0]['text'])
                self.assertEqual(receipt['status'], 'PASS')
                self.assertFalse(receipt['motion_correctness_verified'])
                forged = tool('media_video_frames', {'asset_id':'video','frames':[0], 'path':'/private.png'})
                self.assertTrue(forged['isError'])
                changed = tool('media_sequence_diagnostics', {'asset_ids':ids,'frame_numbers':[0,2], 'active_frames':[0]})
                self.assertTrue(changed['isError'])
            finally:
                proc.stdin.close()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=5)
                stderr = proc.stderr.read()
                proc.stdout.close(); proc.stderr.close()
            self.assertEqual(proc.returncode, 0, stderr)
