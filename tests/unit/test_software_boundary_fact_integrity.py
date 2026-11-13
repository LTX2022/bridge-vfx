from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from vfx_pipeline.domain_readiness import DomainReadinessRunner
from vfx_pipeline.workbuddy_assembly import software_host_client


ROOT = Path(__file__).resolve().parents[2]


def install_native_boundary(version="21.0.631"):
    modules = {}
    for filename in ("native_schema_test_boundary", "software_render_api_boundary"):
        spec = importlib.util.spec_from_file_location(filename, ROOT / "tools" / (filename + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[filename] = module
    api = modules["software_render_api_boundary"]
    interfaces, states, ports = api.interface_profiles(ROOT, version)
    modules["native_schema_test_boundary"].constrain_hou(
        ROOT / "docs/native-basis/hda-interface-capture.json", version,
        instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
    api.install_stage_api(sys.modules["hou"])


class SoftwareBoundaryFactIntegrityTests(unittest.TestCase):
    def _write_legacy_checkpoint(self, root, addon, client):
        from vfx_pipeline.domain_readiness import DomainReadinessRunner

        runner = DomainReadinessRunner(
            host_client=client, task_id="legacy-checkpoint",
            output_root=root / "outputs")
        spec = runner._spec("pyro_smoke_v1", "legacy-checkpoint-case")
        client.call("agent.fx.build_preview", spec)
        operation_id = "legacy-checkpoint-case.operation"
        task_id = spec["task_id"]
        params = {
            "task_id": task_id,
            "operation_id": operation_id,
            "domain_pack": "pyro_smoke_v1",
            "constraints": dict(spec.get("constraints") or {}),
            "frames": [1, 2],
            "output_path": str(root / "outputs" / "boundary.json"),
            "checkpoint_after_build": True,
        }
        result = client.call("agent.fx.software_boundary_execute", params)
        self.assertEqual(result["status"], "CHECKPOINT_REACHED")
        path = addon._fx_boundary_operation_path(task_id, operation_id)
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        checkpoint.pop("operation_receipt_sha256")
        path.write_text(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        params["checkpoint_after_build"] = False
        params["resume"] = True
        return task_id, operation_id, path, params

    def test_result_tamper_is_rejected_by_operation_fact_loader(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            environment = {
                "HOUDINI_BRIDGE_STATE_DIR": str(root / "houdini-state"),
                "BRIDGE_SKILLS_STATE_ROOT": str(root / "installation-state"),
                "BRIDGE_SKILLS_SCHEDULER_ROOT": str(root / "scheduler-state"),
            }
            with patch.dict(os.environ, environment), patch.dict(sys.modules):
                client, addon = software_host_client(
                    ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py",
                    root / "host-client")
                install_native_boundary()
                runner = DomainReadinessRunner(
                    host_client=client, task_id="fact-integrity", output_root=root / "output")
                case = runner.run_case("material_lookdev_v1", "build_inspect")
                self.assertEqual(case.result["status"], "BLOCKED")
                task_id = "fact-integrity-material_lookdev_v1__build_inspect"
                operation_id = "material_lookdev_v1__build_inspect.diagnostic"
                fact = client.operation_fact(operation_id, task_id)
                self.assertIsInstance(fact, dict)
                self.assertEqual(
                    fact["operation_receipt_sha256"], addon._fx_boundary_fact_digest(fact))
                path = addon._fx_boundary_operation_path(task_id, operation_id)
                tampered = json.loads(path.read_text(encoding="utf-8"))
                tampered["result"]["visual_verified"] = True
                path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                with self.assertRaises(addon.BridgeCommandError) as caught:
                    client.operation_fact(operation_id, task_id)
                self.assertEqual(caught.exception.code, "SOFTWARE_OPERATION_FACT_INVALID")

    def test_legacy_checkpoint_resumes_and_is_atomically_upgraded(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            environment = {
                "HOUDINI_BRIDGE_STATE_DIR": str(root / "houdini-state"),
                "BRIDGE_SKILLS_STATE_ROOT": str(root / "installation-state"),
                "BRIDGE_SKILLS_SCHEDULER_ROOT": str(root / "scheduler-state"),
            }
            with patch.dict(os.environ, environment), patch.dict(sys.modules):
                client, addon = software_host_client(
                    ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py",
                    root / "host-client")
                install_native_boundary()
                task_id, operation_id, path, params = self._write_legacy_checkpoint(root, addon, client)
                with self.assertRaises(addon.BridgeCommandError) as untrusted_read:
                    client.operation_fact(operation_id, task_id)
                self.assertEqual(untrusted_read.exception.code, "SOFTWARE_OPERATION_FACT_INVALID")
                atomic_upgrades = []
                original_replace = addon.os.replace

                def observe_replace(source, destination):
                    if Path(destination).resolve() == path.resolve():
                        upgraded = json.loads(Path(source).read_text(encoding="utf-8"))
                        atomic_upgrades.append(upgraded)
                    return original_replace(source, destination)

                with patch.object(addon.os, "replace", side_effect=observe_replace):
                    result = client.call("agent.fx.software_boundary_execute", params)
                self.assertEqual(result["status"], "COMPLETED")
                self.assertEqual(len(atomic_upgrades), 1)
                upgraded = atomic_upgrades[0]
                self.assertEqual(upgraded["state"], "CHECKPOINT_REACHED")
                self.assertEqual(upgraded["task_id"], task_id)
                self.assertEqual(upgraded["operation_id"], operation_id)
                self.assertEqual(upgraded["operation_receipt_sha256"], addon._fx_boundary_fact_digest(upgraded))
                completed = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(completed["state"], "COMPLETED")
                self.assertEqual(completed["operation_receipt_sha256"], addon._fx_boundary_fact_digest(completed))

    def test_tampered_legacy_checkpoint_is_rejected_without_upgrade(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            environment = {
                "HOUDINI_BRIDGE_STATE_DIR": str(root / "houdini-state"),
                "BRIDGE_SKILLS_STATE_ROOT": str(root / "installation-state"),
                "BRIDGE_SKILLS_SCHEDULER_ROOT": str(root / "scheduler-state"),
            }
            with patch.dict(os.environ, environment), patch.dict(sys.modules):
                client, addon = software_host_client(
                    ROOT / "plugins/houdini/_impl/houdini_bridge_addon.py",
                    root / "host-client")
                install_native_boundary()
                _task_id, _operation_id, path, params = self._write_legacy_checkpoint(root, addon, client)
                tampered = json.loads(path.read_text(encoding="utf-8"))
                tampered["checkpoint"]["node_readback"]["source"]["type"] = "Sop/not-the-current-node"
                path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(addon.BridgeCommandError) as caught:
                    client.call("agent.fx.software_boundary_execute", params)
                self.assertEqual(caught.exception.code, "SOFTWARE_OPERATION_FACT_INVALID")
                self.assertEqual(path.read_bytes(), before)
                self.assertNotIn("operation_receipt_sha256", json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
