# -*- coding: utf-8 -*-
"""C3 frozen entry-level acceptance through the FORMAL generated server.

The project is prepared by the real ``prepare_workbuddy_graph.prepare_graph``
(controller-selected software/execution profile) and the MCP session runs in
the GENERATED ``control/server.py`` subprocess — the same entry production
uses, with the controller-selected software backend injecting only fake HOM
clients into a real supervised Python worker.  GraphRun/GraphMCP/assembly/save/reopen are
the shipped code.

Scenarios (frozen):
1. build -> save -> reopen -> bounded feedback edit -> short frame operation;
2. the frame operation id queries and cancels via the operation registry
   (kind host-frame), never via graph jobs;
3. unauthorized profile, 13 frames, 999s budget, wrong types, unknown
   control, arbitrary path are all rejected with host-call counting;
4. same request retry reuses; a new request is a new round; failures never
   rotate ids;
5. completed outputs -> ledger registration -> Nuke bounded render ->
   result query/cancel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

PROPOSAL = {
    "schema_version": "1.0",
    "nodes": [
        {"node_id": "source", "node_type": "sop.sphere", "context": "houdini_sop", "parameters": {}},
        {"node_id": "raster", "node_type": "sop.rasterize", "context": "houdini_sop",
         "parameters": {"voxelsize": 0.2}},
        {"node_id": "sink", "node_type": "sop.volume_output", "context": "houdini_sop", "parameters": {}},
    ],
    "connections": [
        {"source_node": "houdini_sop:/source", "source_port": "geometry",
         "target_node": "houdini_sop:/raster", "target_port": "geometry", "target_index": 0},
        {"source_node": "houdini_sop:/raster", "source_port": "volume",
         "target_node": "houdini_sop:/sink", "target_port": "volume", "target_index": 0},
    ],
    "outputs": [{"output_id": "out", "node_id": "sink", "port": "volume"}],
}


class FormalServerEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory(prefix="c3-formal-")
        cls.root = Path(cls._tmp.name)
        cls._env_backup = {key: os.environ.get(key) for key in (
            "BRIDGE_SKILLS_STATE_ROOT", "BRIDGE_SKILLS_SCHEDULER_ROOT",
            "HOUDINI_BRIDGE_STATE_DIR")}
        os.environ["BRIDGE_SKILLS_STATE_ROOT"] = str(cls.root / "state")
        os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(cls.root / "state" / "sched")
        os.environ["HOUDINI_BRIDGE_STATE_DIR"] = str(cls.root / "state")
        from prepare_workbuddy_graph import prepare_graph
        cls.destination = cls.root / "project-1"
        prepare_graph(cls.destination, app=None, scheduler_root=cls.root / "sched",
                      execution_profile=True, simulation_profile=True,
                      render_profile=True)

    @classmethod
    def tearDownClass(cls) -> None:
        for key, value in cls._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls._tmp.cleanup()

    def setUp(self) -> None:
        import tempfile
        import uuid
        from prepare_workbuddy_graph import prepare_graph
        # Each formal MCP process gets a clean controller project and isolated
        # scheduler/state roots.  The production server still owns all state
        # durably within that project; tests must not leak an active slot from
        # the previous method into the next one.
        self.destination = self.root / ("project-" + uuid.uuid4().hex[:12])
        self.test_state = self.root / ("state-" + uuid.uuid4().hex[:12])
        prepare_graph(self.destination, app=None, scheduler_root=self.test_state / "sched",
                      execution_profile=True, simulation_profile=True,
                      render_profile=True)
        self.server = self.destination / "control" / "server.py"
        self.assertTrue(self.server.is_file(), "the formal generator must produce control/server.py")
        self.server_env = dict(os.environ)
        self.server_env["PYTHONPATH"] = ""
        self.server_env["BRIDGE_SKILLS_STATE_ROOT"] = str(self.test_state)
        self.server_env["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(self.test_state / "sched")
        self.server_env["HOUDINI_BRIDGE_STATE_DIR"] = str(self.test_state)
        self.host_call_log = self.destination / "host-calls.jsonl"
        self.nuke_call_log = self.destination / "nuke-calls.jsonl"
        self.server_env["BRIDGE_SOFTWARE_HOST_CALL_LOG"] = str(self.host_call_log)
        self.server_env["BRIDGE_SOFTWARE_NUKE_CALL_LOG"] = str(self.nuke_call_log)
        self._boot_server()

    def _boot_server(self, backend: str = "software") -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-I", str(self.server), "--backend", backend],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=self.server_env, cwd=str(self.destination))
        self._id = 0
        init = self.request("initialize", {"protocolVersion": "2024-11-05",
                                           "clientInfo": {"name": "c3-formal"}, "capabilities": {}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "bridge-hy3-construction")
        self.notify("notifications/initialized")

    def _stop_server(self) -> None:
        if self.proc is None:
            return
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.proc.stdout.read()
        self.proc.stdout.close()
        err = self.proc.stderr.read()
        self.proc.stderr.close()
        self.assertEqual(self.proc.returncode, 0, "generated server exit must be clean")
        self.assertFalse(err.strip(), "generated server stderr must stay empty: " + err[:400])
        self.proc = None

    def restart_server(self) -> None:
        self._stop_server()
        self._boot_server()

    def tearDown(self) -> None:
        self._stop_server()

    def _send(self, payload):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            self.assertTrue(line, "server closed the session")
            response = json.loads(line)
            if response.get("id") == self._id:
                return response

    def notify(self, method):
        self._send({"jsonrpc": "2.0", "method": method})

    def tool(self, name, arguments):
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "result" not in response:
            raise AssertionError(f"{name}: json-rpc error {response}")
        if response["result"].get("isError"):
            return {"isError": True, "text": response["result"]["content"][0]["text"]}
        return json.loads(response["result"]["content"][0]["text"])

    def completed_graph_trial(self, graph_id, request_id):
        arguments = {'graph_id': graph_id, 'request_id': request_id}
        deadline = time.monotonic() + 120
        trial = self.tool('graph_trial', arguments)
        operation_id = trial.get('operation_id')
        polled = False
        while operation_id and trial.get('state') in {'PREPARED', 'STARTING', 'RUNNING'} and time.monotonic() < deadline:
            time.sleep(.05)
            trial = self.tool('graph_status', {'operation_id': operation_id})
            self.assertEqual(trial.get('operation_id'), operation_id, trial)
            polled = True
        if polled and trial.get('state') == 'SUCCEEDED':
            trial = self.tool('graph_trial', arguments)
            self.assertEqual(trial.get('operation_id'), operation_id, trial)
        self.assertEqual(trial.get('state'), 'SUCCEEDED', trial)
        self.assertTrue(trial.get('stop_confirmed'), trial)
        return trial

    @staticmethod
    def _call_count(path: Path) -> int:
        if not path.is_file():
            return 0
        return len(path.read_text(encoding="utf-8").splitlines())

    @staticmethod
    def _commands(path: Path) -> list[str]:
        if not path.is_file():
            return []
        return [json.loads(line)["command"] for line in path.read_text(encoding="utf-8").splitlines()]

    # ---- frozen scenarios -------------------------------------------------
    def test_full_entry_chain(self) -> None:
        tools = {t["name"] for t in self.request("tools/list", {})["result"]["tools"]}
        self.assertLessEqual({"graph_propose", "graph_trial", "graph_status", "frame_execute",
                              "operation_query", "operation_cancel", "feedback_edit",
                              "task_save", "task_reopen", "nuke_render_bounded",
                              "consume_artifact"}, tools)
        # observations for both registered synthetic images (formal run assets)
        catalog = self.tool("catalog", {})
        asset_ids = [item["asset_id"] for item in catalog["assets"]]
        for index, asset_id in enumerate(asset_ids):
            self.tool("submit_observation", {"asset_id": asset_id, "request_id": f"obs-{index}",
                                             "observation": {"description": "synthetic", "dominant_colors": ["grey"]}})
        graph = self.tool("graph_propose", {"proposal": PROPOSAL, "request_id": "propose-1"})
        graph_id = graph["graph_id"]
        # scenario 1: build -> save -> reopen -> feedback -> short frames
        trial = self.completed_graph_trial(graph_id, "trial-1")
        self.assertEqual(trial.get("state"), "SUCCEEDED", trial)
        result = trial.get("result") or {}
        self.assertTrue(result.get("construction_executed"), trial)
        verification = result.get("verification") or {}
        self.assertTrue(verification.get("nodes_verified"), trial)
        self.assertTrue(verification.get("parameters_verified"), trial)
        self.assertTrue(verification.get("connections_verified"), trial)
        save = self.tool("task_save", {})
        self.assertTrue(save.get("saved_scene_id"))
        # The durable controller receipt and saved scene must survive a fresh
        # generated server process before the public reopen call can proceed.
        self.restart_server()
        reopen = self.tool("task_reopen", {"saved_scene_id": save["saved_scene_id"]})
        self.assertFalse(reopen.get("isError"))
        self.assertGreater(reopen.get("structure_verified", 0), 0, reopen)
        task_binding = self.tool("health", {})["task_id"]
        initial_graph = self.tool("graph_version", {"graph_id": graph_id})
        edit = self.tool("feedback_edit", {"graph_id": graph_id, "node_id": "raster",
                                           "parms": {"voxelsize": 0.3}, "task_id": task_binding})
        self.assertFalse(edit.get("isError"), edit)
        edited_graph = self.tool("graph_version", {"graph_id": graph_id})
        self.assertEqual(edited_graph["version"], initial_graph["version"] + 1)
        self.assertEqual(edited_graph["state"], "COMPLETE")
        self.assertEqual(edited_graph["invalidated_nodes"], ["raster", "sink"])
        self.assertEqual(edited_graph["invalidated_outputs"], ["out"])
        before_source = next(node for node in initial_graph["compiled"]["nodes"] if node["node_id"] == "source")
        after_source = next(node for node in edited_graph["compiled"]["nodes"] if node["node_id"] == "source")
        self.assertEqual(before_source, after_source)
        feedback_save = self.tool('task_save', {})
        self.assertTrue(feedback_save.get('saved_scene_id'), feedback_save)
        jobs_root = self.destination / 'control/jobs/graph-jobs'
        completed_workers = {str(path.relative_to(jobs_root)): path.read_bytes()
                             for path in jobs_root.glob('*/attempt-*/completion.json')}
        self.assertEqual(len(completed_workers), 1, completed_workers)
        self.restart_server()
        commands_before_trial_retry = self._commands(self.host_call_log)
        retried_trial = self.completed_graph_trial(graph_id, 'trial-1')
        self.assertEqual(retried_trial['operation_id'], trial['operation_id'])
        self.assertEqual(self._commands(self.host_call_log), commands_before_trial_retry,
                         'a restored adoption must not rebind the original graph over feedback')
        after_retry = self.tool('graph_version', {'graph_id': graph_id})
        self.assertEqual(after_retry, edited_graph)
        retried_save = self.tool('task_save', {})
        self.assertTrue(retried_save.get('saved_scene_id'), retried_save)
        saved_bytes = Path(retried_save['path']).read_bytes()
        header = b'bridge.software_hom_snapshot/1\n'
        self.assertTrue(saved_bytes.startswith(header))
        saved_scene = json.loads(saved_bytes[len(header):].decode('utf-8'))
        raster_path = trial['result']['topology']['nodes']['houdini_sop:/raster']
        raster = next(node for node in saved_scene['nodes'] if node['path'] == raster_path)
        self.assertEqual(raster['parms']['voxelsize'], 0.3)
        self.assertEqual({str(path.relative_to(jobs_root)): path.read_bytes()
                          for path in jobs_root.glob('*/attempt-*/completion.json')}, completed_workers,
                         'the old trial request must not launch another construction attempt')
        host_commands_before_frame = self._commands(self.host_call_log)
        frames = self.tool("frame_execute", {"request_id": "frames-1", "frames": [1, 2, 3],
                                             "budget_seconds": 60})
        self.assertTrue(frames.get("operation_id"))
        host_commands_after_frame = self._commands(self.host_call_log)
        self.assertEqual(host_commands_after_frame.count("agent.fx.simulate_segment") -
                         host_commands_before_frame.count("agent.fx.simulate_segment"), 1)
        # scenario 2: the host-frame operation queries/cancels via the registry
        query = self.tool("operation_query", {"operation_id": frames["operation_id"]})
        self.assertEqual(query["kind"], "host-frame")
        self.assertIn("operation.status", self._commands(self.host_call_log))
        cancel = self.tool("operation_cancel", {"operation_id": frames["operation_id"]})
        self.assertEqual(cancel["kind"], "host-frame")
        self.assertIn("operation.cancel", self._commands(self.host_call_log))
        # scenario 4: same request retry reuses; unknown ids are unknown
        host_commands_before_retry = self._commands(self.host_call_log)
        frames_again = self.tool("frame_execute", {"request_id": "frames-1", "frames": [1, 2, 3],
                                                   "budget_seconds": 60})
        self.assertEqual(frames_again["operation_id"], frames["operation_id"])
        self.assertEqual(self._commands(self.host_call_log).count("agent.fx.simulate_segment") -
                         host_commands_before_retry.count("agent.fx.simulate_segment"), 1,
                         "a retry may reach the host, but must retain the same stable request identity")
        host_commands_before_unknown = self._commands(self.host_call_log)
        unknown = self.tool("operation_query", {"operation_id": "op-never"})
        self.assertTrue(unknown.get("isError"))
        self.assertEqual(self._commands(self.host_call_log), host_commands_before_unknown,
                         "an unknown operation must not dispatch or mint a replacement request")
        # scenario 3: rejections with zero host side effects
        rejections = [
            {"name": "frame_execute", "arguments": {"request_id": "bad-13", "frames": list(range(1, 14))}},
            {"name": "frame_execute", "arguments": {"request_id": "bad-999", "frames": [1], "budget_seconds": 999}},
            {"name": "frame_execute", "arguments": {"request_id": "bad-type", "frames": "nope"}},
            {"name": "feedback_edit", "arguments": {"graph_id": graph_id, "node_id": "ghost",
                                                    "parms": {"scale": 1.0}, "task_id": task_binding}},
            {"name": "feedback_edit", "arguments": {"graph_id": graph_id, "node_id": "raster",
                                                    "parms": {"voxelsize": 0.3}, "task_id": task_binding,
                                                    "path": "/obj/foreign/root"}},
            {"name": "nuke_render_bounded", "arguments": {
                "request_id": "bad-path", "artifact_id": "formal-input-" + task_binding,
                "pattern": str(self.destination.parent / "outside.%03d.exr"), "frames": [1]}},
        ]
        host_calls_before = self._call_count(self.host_call_log)
        nuke_calls_before = self._call_count(self.nuke_call_log)
        for item in rejections:
            response = self.request("tools/call", {"name": item["name"], "arguments": item["arguments"]})
            self.assertTrue(response["result"].get("isError"), item)
        self.assertEqual(self._call_count(self.host_call_log), host_calls_before,
                         "rejected public requests must not cross the Houdini host boundary")
        self.assertEqual(self._call_count(self.nuke_call_log), nuke_calls_before,
                         "rejected public requests must not cross the Nuke host boundary")
        # NaN must be rejected at the JSON parse layer
        self.proc.stdin.write('{"jsonrpc":"2.0","id":9999,"method":"tools/call","params":'
                              '{"name":"frame_execute","arguments":{"request_id":"nan-1","frames":[NaN],"budget_seconds":60}}}\n')
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        self.assertTrue(line and ("Invalid JSON" in line or "isError" in line), line)
        # scenario 5: the controller-bound Nuke completion itself supplies
        # the durable operation fact and artifact registration.  The model
        # has no fact/artifact writer tools to call by guessed operation id.
        public_names = {item["name"] for item in self.request("tools/list", {})["result"]["tools"]}
        self.assertNotIn("record_render_fact", public_names)
        self.assertNotIn("register_render_artifact", public_names)
        for forbidden in ("record_render_fact", "register_render_artifact"):
            denied = self.request("tools/call", {"name": forbidden, "arguments": {}})
            self.assertTrue(denied["result"].get("isError"))
        nuke = self.tool("nuke_render_bounded", {"request_id": "nuke-1",
                                                 "artifact_id": "formal-input-" + task_binding,
                                                 "pattern": str(self.destination / "saves" / "nuke-r.%03d.exr"),
                                                 "frames": [1, 2]})
        self.assertTrue(nuke.get("operation_id"), nuke)
        consumed = self.tool("consume_artifact", {"artifact_id": nuke["artifact_id"]})
        self.assertTrue(consumed["usable_as_render_input"], consumed)
        nuke_status = self.tool("operation_query", {"operation_id": nuke["operation_id"]})
        self.assertEqual(nuke_status["kind"], "nuke-render")
        self.assertIn("render_status", self._commands(self.nuke_call_log))
        nuke_cancel = self.tool("operation_cancel", {"operation_id": nuke["operation_id"]})
        self.assertEqual(nuke_cancel["kind"], "nuke-render")
        self.assertIn("render_cancel", self._commands(self.nuke_call_log))

    def test_new_request_is_a_new_frame_round(self) -> None:
        for index, asset in enumerate(self.tool("catalog", {})["assets"]):
            self.tool("submit_observation", {"asset_id": asset["asset_id"], "request_id": f"obs-r-{index}",
                                             "observation": {"description": "x", "dominant_colors": ["g"]}})
        graph = self.tool("graph_propose", {"proposal": PROPOSAL, "request_id": "propose-r"})
        self.completed_graph_trial(graph["graph_id"], "trial-r")
        first = self.tool("frame_execute", {"request_id": "fr-r1", "frames": [1], "budget_seconds": 60})
        second = self.tool("frame_execute", {"request_id": "fr-r2", "frames": [1], "budget_seconds": 60})
        self.assertNotEqual(first["operation_id"], second["operation_id"])
        self.assertNotEqual(first["operation_id"], "unknown")

    def test_generated_diagnostic_entry_refuses_unapproved_execution(self) -> None:
        from prepare_workbuddy_graph import prepare_graph
        self._stop_server()
        self.destination = self.root / "project-unapproved"
        self.test_state = self.root / "state-unapproved"
        prepare_graph(self.destination, app=None, scheduler_root=self.test_state / "sched",
                      execution_profile=False, simulation_profile=False, render_profile=False)
        self.server = self.destination / "control" / "server.py"
        self.server_env = dict(os.environ)
        self.server_env["PYTHONPATH"] = ""
        self.server_env["BRIDGE_SKILLS_STATE_ROOT"] = str(self.test_state)
        self.server_env["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(self.test_state / "sched")
        self.server_env["HOUDINI_BRIDGE_STATE_DIR"] = str(self.test_state)
        self.host_call_log = self.destination / "host-calls.jsonl"
        self.nuke_call_log = self.destination / "nuke-calls.jsonl"
        self.server_env["BRIDGE_SOFTWARE_HOST_CALL_LOG"] = str(self.host_call_log)
        self.server_env["BRIDGE_SOFTWARE_NUKE_CALL_LOG"] = str(self.nuke_call_log)
        self._boot_server(backend="diagnostic")
        health = self.tool("health", {})
        self.assertFalse(health["dcc_dispatch_enabled"])
        self.assertFalse(health["simulation_enabled"])
        self.assertFalse(health["render_enabled"])
        rejected_frame = self.tool("frame_execute", {
            "request_id": "unauthorized-frame", "frames": [1], "budget_seconds": 30})
        self.assertTrue(rejected_frame.get("isError"), rejected_frame)
        rejected_render = self.tool("nuke_render_bounded", {
            "request_id": "unauthorized-render", "artifact_id": "not-registered",
            "pattern": str(self.destination / "saves" / "out.%03d.exr"), "frames": [1]})
        self.assertTrue(rejected_render.get("isError"), rejected_render)
        self.assertEqual(self._call_count(self.host_call_log), 0)
        self.assertEqual(self._call_count(self.nuke_call_log), 0)

    def _any_asset(self):
        catalog = self.tool("catalog", {})
        return catalog["assets"][0]["asset_id"]


if __name__ == "__main__":
    unittest.main()
