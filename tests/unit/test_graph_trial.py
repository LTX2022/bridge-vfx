from __future__ import annotations

import copy
import dataclasses
import sys
import unittest
from pathlib import Path

from dcc_task_runtime.canonical import canonical_sha256  # noqa: E402
from dcc_task_runtime.graph_compiler import (  # noqa: E402
    GraphConnection,
    GraphNodeProposal,
    GraphOutput,
    GraphProposal,
)
from vfx_pipeline import graph_catalog  # noqa: E402
from vfx_pipeline.graph_trial import GraphExecutor  # noqa: E402


class DurableGraphJournalTests(unittest.TestCase):
    def test_intent_survives_restart_and_is_scoped_to_graph(self):
        import tempfile
        from dcc_task_runtime.pipeline_store import PipelineStore
        from vfx_pipeline.graph_trial import TaskGraphJournal
        from test_vfx_pipeline import raw_spec
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite3"
            store = PipelineStore(database)
            task = store.create_task(raw_spec("pyro_smoke_v1", "detail"))
            journal = TaskGraphJournal(store, task, "graph-one")
            intent = {"status": "INTENT", "intent": {"kind": "node.create"}}
            journal.write("create", intent)
            reopened = PipelineStore(database)
            self.assertEqual(TaskGraphJournal(reopened, task, "graph-one").read("create"), intent)
            self.assertIsNone(TaskGraphJournal(reopened, task, "graph-two").read("create"))


class Journal(dict):
    def read(self, operation_id):
        return self.get(operation_id)

    def write(self, operation_id, value):
        self[operation_id] = copy.deepcopy(value)


class FakeHoudiniClient:
    def __init__(self, fail_command=None):
        self.calls = []
        self.children = {"/obj": []}
        self.fail_command = fail_command
        self.root_leases = {}

    def call(self, command, params):
        self.calls.append((command, copy.deepcopy(params)))
        if command == self.fail_command:
            raise RuntimeError("simulated bridge disconnect")
        if command == "node.children":
            return {"path": params["path"], "nodes": copy.deepcopy(self.children.get(params["path"], []))}
        if command == "scene.create_task_root":
            root = "/obj/" + params["root_name"]
            lease = self.root_leases.get(root)
            if lease is not None and lease["task_id"] != params["task_id"]:
                raise AssertionError("SCENE_CONFLICT")
            if lease is None:
                if self.children.get(root):
                    raise AssertionError("SCENE_CONFLICT")
                self.children.setdefault("/obj", []).append({"path": root, "type": params["type"], "name": params["root_name"]})
                self.children.setdefault(root, [])
                self.root_leases[root] = {"task_id": params["task_id"], "status": "ACTIVE"}
                return {"path": root, "type": params["type"], "reused": False}
            return {"path": root, "type": params["type"], "reused": True}
        if command == "node.create":
            parent, name, node_type = params["parent"], params["name"], params["type"]
            path = f"{parent}/{name}"
            self.children.setdefault(parent, []).append({"path": path, "type": node_type, "name": name})
            self.children.setdefault(path, [])
            return {"path": path, "type": node_type}
        if command == "node.set_parms":
            return {"path": params["path"], "values": dict(params["parms"])}
        if command == "node.connect":
            return {"source": params["source"], "destination": params["destination"]}
        raise AssertionError(f"unexpected command: {command}")


def graph():
    # IDs are deliberately ordered opposite to the dependency so execution
    # order and compiled-node order exercise address-based operation lookup.
    return graph_catalog.compiler().compile(GraphProposal(
        nodes=(
            GraphNodeProposal("sink", "sop.pyro_source", context="houdini_sop"),
            GraphNodeProposal("source", "sop.sphere", context="houdini_sop"),
        ),
        connections=(GraphConnection("source", "geometry", "sink", "geometry"),),
        outputs=(GraphOutput("out", "sink", "geometry"),),
    ))


class GraphExecutorTests(unittest.TestCase):
    def test_registered_multiparms_are_allocated_in_the_create_intent(self):
        for version in graph_catalog.HOUDINI_VERSIONS:
            for domain, role, parameters in (('crowd_agents_v1', 'import_geometry', {'fields': 1, 'compression': 0}),
                                             ('hair_fur_v1', 'guide_length', {'operations': 1}),
                                             ('water_flip_v1', 'container', {'customattributes': 0})):
                with self.subTest(version=version, domain=domain):
                    compiled = graph_catalog.compile_proposal(dict(
                        schema='bridge.registered-domain-construction/1',
                        domain_pack=domain, houdini_version=version))
                    schedule = graph_catalog.bounded_domain_schedule(compiled)
                    address = next(node.address for node in compiled.nodes if node.node_id == role)
                    self.assertEqual(schedule['creation_parameters'][address], parameters)
                    if domain == 'crowd_agents_v1':
                        transition = next(node.address for node in compiled.nodes if node.node_id == 'transition')
                        self.assertEqual(schedule['creation_parameters'][transition], {'blend': {
                            'schema': 'bridge.native-float-ramp/1', 'basis': ['Linear', 'Linear'],
                            'keys': [0., 1.], 'values': [0., 1.]}})
                        self.assertEqual(set(schedule['creation_parameters']), {address, transition})
                    else:
                        self.assertEqual(set(schedule['creation_parameters']), {address})
                    payload = {key: value for key, value in schedule.items() if key != 'schedule_sha256'}
                    self.assertEqual(schedule['schedule_sha256'], canonical_sha256(payload))
                    operations = dict(GraphExecutor._operations(compiled, '/obj/task'))
                    intent = operations[f'{compiled.graph_hash}:node:{address}:create']
                    self.assertEqual(intent['parameters'], parameters)

    def test_unregistered_graph_has_no_implicit_creation_parameters(self):
        self.assertIsNone(graph_catalog.bounded_domain_schedule(graph()))
        client, journal = FakeHoudiniClient(), Journal()
        result = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute('no-bootstrap', graph())
        self.assertTrue(result['construction_executed'])
        self.assertTrue(all('parms' not in params for command, params in client.calls if command == 'node.create'))

    def test_old_creation_journal_without_allocation_is_rejected_before_calls(self):
        compiled = graph_catalog.compile_proposal(dict(
            schema='bridge.registered-domain-construction/1',
            domain_pack='crowd_agents_v1', houdini_version='21.0.631'))
        operations = GraphExecutor._operations(compiled, '/obj/task')
        operation_id, intent = next((operation_id, intent) for operation_id, intent in operations
                                   if intent.get('parameters') == {'fields': 1, 'compression': 0})
        old_intent = {key: value for key, value in intent.items() if key != 'parameters'}
        journal = Journal({operation_id: dict(status='COMPLETE', intent=old_intent,
                                             result=dict(path=intent['path'], type=intent['type']))})
        client = FakeHoudiniClient()
        result = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute('old-bootstrap', compiled)
        self.assertTrue(result['reconciliation_required'])
        self.assertFalse(client.calls)

    def test_builds_only_allowlisted_topology_and_journals_each_mutation(self):
        client, journal = FakeHoudiniClient(), Journal()
        result = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-1", graph())

        self.assertTrue(result["construction_executed"])
        self.assertFalse(result["visual_verified"])
        self.assertFalse(result["reconciliation_required"])
        self.assertEqual(result["topology"]["nodes"]["houdini_sop:/source"].split("/")[-1], "source")
        self.assertEqual([command for command, _ in client.calls].count("node.create"), 2)
        self.assertEqual([command for command, _ in client.calls].count("scene.create_task_root"), 1)
        self.assertEqual([command for command, _ in client.calls].count("node.connect"), 1)
        self.assertEqual([command for command, _ in client.calls].count("node.set_parms"), 1)
        for index, (command, params) in enumerate(client.calls):
            if command == "node.create":
                self.assertEqual(client.calls[index - 1][0], "node.children")
                self.assertEqual(client.calls[index - 1][1]["path"], params["parent"])
        self.assertTrue(journal)
        self.assertTrue(all(entry["status"] == "COMPLETE" and "intent" in entry and "result" in entry for entry in journal.values()))
        self.assertNotIn("node.cook", [command for command, _ in client.calls])
        self.assertNotIn("code.exec_python", [command for command, _ in client.calls])

    def test_reordered_compiled_nodes_use_their_own_address_operations(self):
        client, journal = FakeHoudiniClient(), Journal()
        compiled = graph()
        GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-order", compiled)
        creates = [(params["name"], params["type"]) for command, params in client.calls if command == "node.create"]
        self.assertEqual(creates, [("source", "sphere"), ("sink", "pyrosource")])
        # The dependency source is connected to sink input zero.
        connection = next(params for command, params in client.calls if command == "node.connect")
        self.assertTrue(connection["source"].endswith("/source"))
        self.assertTrue(connection["destination"].endswith("/sink"))
        self.assertEqual(connection["input_index"], 0)

    def test_existing_completed_journal_is_not_replayed_without_host_revalidation(self):
        client, journal = FakeHoudiniClient(), Journal()
        compiled = graph()
        first = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-2", compiled)
        self.assertTrue(first["construction_executed"])
        calls_before = len(client.calls)
        client.children["/obj"].clear()  # Simulate external deletion after completion.
        second = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-2", compiled)
        self.assertTrue(second["reconciliation_required"])
        self.assertFalse(second["construction_executed"])
        self.assertIsNone(second["topology"])
        self.assertEqual(len(client.calls), calls_before)

    def test_invalid_context_is_rejected_before_any_bridge_call(self):
        client, journal = FakeHoudiniClient(), Journal()
        compiled = graph()
        bad = dataclasses.replace(compiled.nodes[0], context="lop", address="lop:/sink")
        tampered = dataclasses.replace(compiled, nodes=(bad, compiled.nodes[1]))
        result = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-3", tampered)
        self.assertTrue(result["reconciliation_required"])
        self.assertFalse(client.calls)

    def test_bridge_failure_leaves_unknown_operation_for_reconciliation(self):
        client, journal = FakeHoudiniClient(fail_command="node.connect"), Journal()
        result = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-4", graph())
        self.assertTrue(result["reconciliation_required"])
        self.assertFalse(result["construction_executed"])
        self.assertTrue(any(entry["status"] == "UNKNOWN" for entry in journal.values()))

    def test_caller_cannot_override_native_binding(self):
        client, journal = FakeHoudiniClient(), Journal()
        compiled = graph()
        bad = dataclasses.replace(compiled.nodes[1], node_type="sphere")
        tampered = dataclasses.replace(compiled, nodes=(compiled.nodes[0], bad))
        payload = {key: value for key, value in tampered.to_dict().items() if key != "graph_hash"}
        tampered = dataclasses.replace(tampered, graph_hash=canonical_sha256(payload))
        result = GraphExecutor(client, journal, lease_guard=lambda *args: None).execute("task-5", tampered)
        self.assertTrue(result["reconciliation_required"])
        self.assertFalse(client.calls)


class NativeCreationTypeTests(unittest.TestCase):
    def test_exact_creation_preserves_declared_types_under_native_preferences(self):
        import importlib.util
        import os
        import tempfile
        from unittest.mock import patch
        from vfx_pipeline.workbuddy_assembly import software_host_client
        root = Path(__file__).resolve().parents[2]
        def tool(name):
            spec = importlib.util.spec_from_file_location('graph_type_' + name, root / 'tools' / (name + '.py'))
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            return module
        native, api = tool('native_schema_test_boundary'), tool('software_render_api_boundary')
        compiled = graph_catalog.compile_proposal(dict(schema='bridge.registered-domain-construction/1',
            domain_pack='material_lookdev_v1', houdini_version='21.0.631', scene_profile='sphere_ground_v2'))
        preferences = {'Lop/light':'light::2.0', 'Lop/rendervar':'rendervar::2.0',
                       'Vop/mtlxnormalmap':'mtlxnormalmap::2.0'}
        for operator, preferred in preferences.items():
            with self.subTest(operator=operator), tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp, patch.dict(sys.modules), patch.dict(os.environ, {
                    'BRIDGE_SKILLS_STATE_ROOT':tmp+'/state', 'HOUDINI_BRIDGE_STATE_DIR':tmp+'/houdini',
                    'BRIDGE_SKILLS_SCHEDULER_ROOT':tmp+'/scheduler'}):
                client, addon = software_host_client(root/'plugins/houdini/_impl/houdini_bridge_addon.py', Path(tmp)/'host')
                interfaces, states, ports = api.static_scene_interface_profiles(root, '21.0.631')
                native.constrain_hou(root/'docs/native-basis/hda-interface-capture.json', '21.0.631',
                    instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports,
                    native_api_type_preferences={operator:preferred})
                class DefaultCreationClient:
                    def call(self, command, params):
                        params = dict(params)
                        params.pop('exact_type_name', None)
                        return client.call(command, params)
                journal = Journal()
                failed = GraphExecutor(DefaultCreationClient(), journal, lease_guard=lambda *args: None).execute('preferred-type', compiled)
                self.assertFalse(failed['construction_executed'])
                self.assertTrue(failed['reconciliation_required'])
                last = list(journal.values())[-1]
                self.assertEqual(last['status'], 'COMPLETE', last.get('error'))
                self.assertEqual(last['intent']['type'], operator.split('/',1)[1])
                self.assertEqual(last['result']['type'], preferred)
                self.assertIn('unexpected path or type', failed['diagnostics'][0]['message'])
                built = GraphExecutor(client, Journal(), lease_guard=lambda *args: None).execute('exact-type', compiled)
                self.assertTrue(built['construction_executed'], built)
                self.assertFalse(built['reconciliation_required'])
                for node in compiled.nodes:
                    actual = sys.modules['hou'].node(built['topology']['nodes'][node.address])
                    self.assertEqual(actual.type().name(), graph_catalog.native_binding(node.node_type).native_type)
                parent = built['topology']['root'] + '/usd_network'
                with self.assertRaises(addon.BridgeCommandError) as invalid:
                    client.call('node.create', dict(parent=parent, type='light', name='invalid_exact',
                        task_id='exact-type', exact_type_name='true'))
                self.assertEqual(invalid.exception.code, 'INVALID_ARGUMENT')
                self.assertIsNone(sys.modules['hou'].node(parent + '/invalid_exact'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
