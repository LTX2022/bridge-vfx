"""Shared saved facts and isolated live worker journals, without host processes."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from vfx_pipeline.graph_jobs import GraphJobService
from vfx_pipeline.production_hosts import _shared_env, _scene_transition_operation_store_path
from vfx_pipeline.workbuddy_assembly import software_host_client

ROOT = Path(__file__).resolve().parents[2]


class ParticleEmissionStateRootTests(unittest.TestCase):
    def test_shared_saved_contracts_do_not_share_rpc_or_live_operation_ownership(self):
        with ExitStack() as stack:
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
            stack.enter_context(patch.dict(sys.modules))
            _, addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', directory / 'api')
            control = directory / 'control'
            service = GraphJobService(control / 'jobs', ROOT, 'NEVER_A_DCC',
                scheduler_root=directory / 'scheduler', worker_factory=lambda job: None)
            stack.callback(service.close)
            environments = (_shared_env({}, control, directory / 'scheduler'),
                            service._worker_env(control / 'jobs/graph-jobs/explicit-attempt'))
            facts = []
            for environment in environments:
                with patch.dict(os.environ, environment):
                    facts.append(dict(discovery=addon._state_dir(), task=addon._task_state_root(),
                        saves=addon._fx_task_saves_path('explicit-p01'),
                        live_operations=addon._fx_operations_store_path('explicit-p01'),
                        leases=addon._root_leases_dir()))
            self.assertNotEqual(facts[0]['discovery'], facts[1]['discovery'])
            self.assertNotEqual(facts[0]['live_operations'], facts[1]['live_operations'])
            self.assertNotEqual(facts[0]['leases'], facts[1]['leases'])
            self.assertEqual(facts[0]['saves'], facts[1]['saves'])
            self.assertEqual(facts[0]['task'], facts[1]['task'])
            self.assertEqual(facts[0]['live_operations'], _scene_transition_operation_store_path(control, 'explicit-p01'))

    def test_legacy_state_layout_is_retained_without_explicit_shared_root(self):
        with ExitStack() as stack:
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
            stack.enter_context(patch.dict(sys.modules))
            stack.enter_context(patch.dict(os.environ, {'HOUDINI_BRIDGE_STATE_DIR': str(directory / 'legacy')}))
            os.environ.pop('HOUDINI_BRIDGE_TASK_STATE_DIR', None)
            _, addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', directory / 'api')
            self.assertEqual(addon._task_state_root(), addon._state_dir().parent)
            self.assertEqual(addon._fx_task_saves_path('explicit-p01').parent,
                             addon._fx_operations_store_path('explicit-p01').parent)

    def test_relative_shared_fact_root_is_refused(self):
        with ExitStack() as stack:
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
            stack.enter_context(patch.dict(sys.modules))
            _, addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', directory / 'api')
            with patch.dict(os.environ, {'HOUDINI_BRIDGE_TASK_STATE_DIR': 'relative/task-state'}):
                with self.assertRaises(addon.BridgeCommandError) as caught:
                    addon._task_state_root()
            self.assertEqual(caught.exception.code, 'TASK_STATE_ROOT_INVALID')
