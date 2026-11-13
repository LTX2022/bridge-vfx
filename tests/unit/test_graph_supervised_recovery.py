"""Actual controller death and retained supervisor evidence; no DCC starts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from vfx_pipeline.graph_jobs import GraphJobService
from test_graph_jobs import _proposal

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/helpers'))
from graph_job_process_fixture import python_command

class GraphSupervisedRecoveryTests(unittest.TestCase):
    def test_controller_dies_while_worker_alive_then_reconcile_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve(); script=base/'controller.py'
            script.write_text('''import json,os,sys,time
from pathlib import Path
for name in ('dcc-task-runtime','vfx-pipeline','houdini-bridge','nuke-bridge'):
    sys.path.insert(0,str(Path(sys.argv[1])/'packages'/name/'src'))
from vfx_pipeline.graph_jobs import GraphJobService
sys.path.insert(0,str(Path(sys.argv[1])/'tests/unit'))
sys.path.insert(0,str(Path(sys.argv[1])/'tests/helpers'))
from graph_job_process_fixture import launch_worker
from test_graph_jobs import _proposal
repo=Path(sys.argv[1]);base=Path(sys.argv[2])
def spawn(argv,**options):
    return launch_worker(argv[-1],fault='hang_after_completion',env=options['env'])
service=GraphJobService(base/'job',repo,'NEVER_DCC',scheduler_root=base/'scheduler',subprocess_factory=spawn)
op=service.trial(service.propose(_proposal(),'p'),'r');directory=service._worker_paths(op)['directory']
deadline=time.monotonic()+8
while not (directory/'worker_waiting').exists():
    if time.monotonic()>deadline:raise RuntimeError('worker never started')
    time.sleep(.01)
(base/'ready.json').write_text(json.dumps({'operation_id':op,'directory':str(directory)}))
os._exit(17)
''')
            env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join(str(ROOT/'packages'/p/'src') for p in ('vfx-pipeline','dcc-task-runtime','houdini-bridge','nuke-bridge'))
            child=subprocess.Popen(python_command(script,ROOT,base),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            stdout,stderr=child.communicate(timeout=15)
            self.assertEqual(child.returncode,17,stderr.decode())
            ready=json.loads((base/'ready.json').read_text());op=ready['operation_id'];directory=Path(ready['directory'])
            fresh=GraphJobService(base/'job',ROOT,'NEVER_DCC',scheduler_root=base/'scheduler',
                                  worker_factory=lambda _:self.fail('recovery must never launch'))
            try:
                self.assertEqual(fresh.reconcile(op)['state'],'RECONCILIATION_REQUIRED')
                self.assertTrue(fresh.scheduler.snapshot()['active'])
                (directory/'release_worker').touch()
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    result=fresh.reconcile(op)
                    if result['state']=='SUCCEEDED':break
                    time.sleep(.02)
                self.assertEqual(result['state'],'SUCCEEDED',result)
                self.assertTrue(result['stop_confirmed']);self.assertFalse(fresh.scheduler.snapshot()['active'])
                effects=[json.loads(line) for line in (directory/'software_host_effects.jsonl').read_text().splitlines()]
                self.assertEqual(sum(x['command']=='node.create' for x in effects),1)
            finally:
                (directory/'release_worker').touch();fresh.close()
