import hashlib
from pathlib import Path
import tempfile
import unittest

from dcc_task_runtime.contracts import TaskSpecV2
from dcc_task_runtime.graph_compiler import GraphCompileError
from vfx_pipeline.service import ModelSafePipeline, PipelineExecutionError
from vfx_pipeline.router import RouteLeg
from test_vfx_pipeline import raw_spec


class GraphAndSceneIntegrationTests(unittest.TestCase):
    def test_proposal_is_compiled_persisted_and_never_marked_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            pipeline = ModelSafePipeline(database)
            task = pipeline.store.create_task(raw_spec("pyro_smoke_v1", "dust"))
            proposal = {
                "nodes": [{"node_id": "source", "node_type": "sop.burst_source", "context": "houdini_sop"}],
                "outputs": [{"output_id": "source", "node_id": "source", "port": "geometry"}],
            }
            record = pipeline.graph_propose(task, proposal)
            self.assertFalse(record["executed"])
            self.assertEqual(record["maturity"], "experimental_candidate")
            self.assertEqual(record["graph_id"], pipeline.graph_propose(task, proposal)["graph_id"])
            restarted = ModelSafePipeline(database)
            self.assertEqual(len(restarted.graph_list(task)["graphs"]), 1)
            invalid = {"nodes": [{"node_id": "execute", "node_type": "python", "context": "houdini_sop"}]}
            with self.assertRaises(GraphCompileError):
                pipeline.graph_propose(task, invalid)
            self.assertEqual(len(restarted.graph_list(task)["graphs"]), 1)

    def test_hosts_receive_independent_paths_hashes_and_source_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenes = {}
            for app, suffix in (("houdini", "hip"), ("nuke", "nk")):
                path = root / ("scene." + suffix)
                path.write_bytes(app.encode())
                scenes[app] = {"scene_mode": "existing", "scene_path": str(path), "frozen_scene_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            raw = raw_spec("pyro_smoke_v1", "dust")
            raw.update(schema_version="2.1", target={"application": "pipeline", "scenes": scenes})
            spec = TaskSpecV2.from_mapping(raw)
            pipeline = ModelSafePipeline(root / "state.sqlite3")
            for app in scenes:
                leg = RouteLeg(app, "pyro_smoke_v1" if app == "houdini" else "nuke_composite_v1", "1.0.0", 8100, "preview")
                child = pipeline._subtask_spec(spec, leg, None)
                self.assertEqual(child["target"]["scene_path"], scenes[app]["scene_path"])
                self.assertEqual(child["constraints"]["frozen_scene_sha256"], scenes[app]["frozen_scene_sha256"])
            manifest = pipeline._freeze_task_sources(spec)
            self.assertEqual(set(manifest["scenes"]), {"houdini", "nuke"})
            Path(scenes["nuke"]["scene_path"]).write_text("changed")
            with self.assertRaises(PipelineExecutionError):
                pipeline._freeze_task_sources(spec)
