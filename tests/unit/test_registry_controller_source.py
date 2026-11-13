from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from vfx_pipeline.workbuddy_graph_mcp import GraphRun
import test_registry_operation_receipts as registry_tests


class RegistryControllerSourceTests(unittest.TestCase):
    second_source = 'packages/dcc-task-runtime/src/dcc_task_runtime/contracts.py'

    def source(self, root):
        native = 'plugins/houdini/_impl/houdini_bridge_addon.py'
        snapshot = root / 'snapshot'
        addon = snapshot / native
        addon.parent.mkdir(parents=True)
        addon.write_text('native provider source', encoding='utf-8')
        addon_hash = hashlib.sha256(addon.read_bytes()).hexdigest()
        second = snapshot / self.second_source
        second.parent.mkdir(parents=True)
        second.write_text('explicit frozen software dependency, never executed', encoding='utf-8')
        index = root / 'snapshot-manifest.json'
        index.write_text(json.dumps({'files': [{'path': native, 'sha256': addon_hash},
            {'path': self.second_source, 'sha256': hashlib.sha256(second.read_bytes()).hexdigest()}]}), encoding='utf-8')
        manifest = root / 'run.json'
        manifest.write_text(json.dumps({'backend': 'production'}), encoding='utf-8')
        caller = GraphRun.__new__(GraphRun)
        caller.controller_source = {'backend': 'production', 'manifest_path': str(manifest),
            'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'snapshot_manifest_sha256': hashlib.sha256(index.read_bytes()).hexdigest(),
            'repo_root': str(snapshot)}
        return caller, {'host_identity': {'plugin_build': addon_hash}}, addon, index

    def test_source_map_reads_all_bound_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            caller, fact, addon, index = self.source(Path(directory))
            result = caller._registry_receipt_sources(fact)
            self.assertEqual(set(result), {str(addon), str(index), str(Path(directory) / 'run.json'),
                str(Path(directory) / 'snapshot' / self.second_source)})
            for name, checksum in result.items():
                self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(), checksum)

    def test_second_source_pin_survives_real_registry_register_lookup_and_read_frame(self):
        """Software EXR/SQLite inputs exercise registration, not host rendering."""
        fixture = registry_tests.RegistryOperationReceiptTests('test_receipt_is_persisted_with_actual_version_and_survives_new_registry')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        root = fixture.root / 'controller'
        caller, fact, addon, index = self.source(root)
        second = root / 'snapshot' / self.second_source
        sources = caller._registry_receipt_sources(fact)
        if os.environ.get('BRIDGE_TEST_REGISTRY_OLD_SOURCE_MAP') == '1':
            sources = {name: value for name, value in sources.items() if name != str(second)}
        entry = fixture.register(receipt_source_files=sources)
        registry, receipt = fixture.registry, entry['registry_operation_receipt']
        for name, checksum in sources.items():
            self.assertEqual(receipt['current_source'].get(name), checksum)
        self.assertEqual(registry.lookup(entry['artifact_id'])['registry_operation_receipt'], receipt)
        consumed = registry.read_frame(entry['artifact_id'], 1)
        self.assertEqual(consumed['sha256'], fixture.fact['frame_snapshots']['1']['sha256'])
        self.assertEqual(consumed['registry_operation_receipt'], receipt)
        self.assertTrue(consumed['image']['rows'])
        original = second.read_bytes()
        actions = {'verify': lambda: registry.verify_operation_receipt(receipt),
            'lookup': lambda: registry.lookup(entry['artifact_id']),
            'read_frame': lambda: registry.read_frame(entry['artifact_id'], 1)}
        for mutation in ('changed', 'removed'):
            try:
                if mutation == 'changed':
                    second.write_bytes(b'changed frozen support source')
                else:
                    second.unlink()
                for label, action in actions.items():
                    with self.subTest(mutation=mutation, consumer=label):
                        with self.assertRaisesRegex(registry_tests.ArtifactError, 'REGISTRY_RECEIPT_SOURCE_UNAVAILABLE'):
                            action()
            finally:
                second.write_bytes(original)
        self.assertEqual(registry.verify_operation_receipt(receipt), receipt)

    def test_missing_config_retains_no_typed_claim(self):
        caller = GraphRun.__new__(GraphRun)
        self.assertIsNone(caller._registry_receipt_sources({}))

    def test_changed_file_and_wrong_host_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            caller, fact, addon, index = self.source(Path(directory))
            with self.assertRaisesRegex(ValueError, 'differs from completed host'):
                caller._registry_receipt_sources({'host_identity': {'plugin_build': '0' * 64}})
            addon.write_text('changed', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                caller._registry_receipt_sources(fact)

    def test_unbound_index_and_wrong_snapshot_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            caller, fact, addon, index = self.source(Path(directory))
            caller.controller_source['repo_root'] = str(Path(directory) / 'elsewhere')
            with self.assertRaisesRegex(ValueError, 'not controller-owned'):
                caller._registry_receipt_sources(fact)
            caller.controller_source['repo_root'] = str(Path(directory) / 'snapshot')
            index.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                caller._registry_receipt_sources(fact)

    def test_escaping_or_duplicate_snapshot_paths_refused(self):
        for name in ('../native.py', '/native.py', 'C:/native.py', 'C:native.py', 'a\\native.py'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                caller, fact, addon, index = self.source(Path(directory))
                records = json.loads(index.read_text(encoding='utf-8'))['files']
                records.append({'path': name, 'sha256': '0' * 64})
                index.write_text(json.dumps({'files': records}), encoding='utf-8')
                caller.controller_source['snapshot_manifest_sha256'] = hashlib.sha256(index.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, 'path is invalid'):
                    caller._registry_receipt_sources(fact)


if __name__ == '__main__':
    unittest.main()
