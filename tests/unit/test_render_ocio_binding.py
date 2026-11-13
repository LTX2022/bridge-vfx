"""Actual file and supervised Python producer tests; never DCC render facts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/unit'))

import test_houdini_output_receipts as receipts
from houdini_bridge import client


class NativeOcioConfigFixture:
    """Explicit bottom-level OCIO object APIs, backed by separate on-disk files."""
    def __init__(self, directory):
        self.directory = directory

    def getCacheID(self):
        return 'explicit-file-api-fixture'

    def getSearchPath(self):
        return str(self.directory)

    def getWorkingDir(self):
        return str(self.directory)

    def getCurrentContext(self):
        return self

    def resolveFileLocation(self, reference):
        return str(self.directory / reference)

    def getColorSpaceFromFilepath(self, path):
        return ('fixture-linear', 0)

    def getFileRules(self):
        return SimpleNamespace(getNumEntries=lambda: 1, getName=lambda index: 'Default',
                               getPattern=lambda index: '', getExtension=lambda index: '',
                               getRegex=lambda index: '', getColorSpace=lambda index: 'fixture-linear')

    def getProcessor(self, context, source, destination):
        if context is not self or (source, destination) != ('fixture-linear', 'fixture-display'):
            raise ValueError('unexpected explicit transform request')
        return SimpleNamespace(getProcessorMetadata=lambda: SimpleNamespace(
            getFiles=lambda: ['look.spi1d']))


def corrupt_preserving_size_and_mtime(path):
    original = path.read_bytes()
    observed = path.stat()
    changed = original[:-1] + bytes([original[-1] ^ 1])
    path.write_bytes(changed)
    os.utime(path, ns=(observed.st_atime_ns, observed.st_mtime_ns))
    return original, observed


def restore_file(path, original, observed):
    path.write_bytes(original)
    os.utime(path, ns=(observed.st_atime_ns, observed.st_mtime_ns))


def run_preseal_producer(initial_path):
    """Real authenticated producer exercises the seal's existing collection call."""
    from dcc_task_runtime.owned_process import _atomic, read_receipt

    initial_path = Path(initial_path)
    initial = json.loads(initial_path.read_text(encoding='utf-8'))
    record = initial['record']
    supervisor = record['supervisor_binding']
    deadline = time.monotonic() + 8
    while read_receipt(supervisor['directory'], 'started', identity=supervisor['identity']) is None:
        if time.monotonic() > deadline:
            raise RuntimeError('supervised Python producer never started')
        time.sleep(.01)
    record['host_identity'] = {'pid': os.getpid(),
                               'launch_nonce': supervisor['identity']['launch_nonce'],
                               'fixture_kind': 'explicit_python_file_producer_not_DCC'}
    record['output_facts'] = {'1': client.collect_render_output_fact(record, 1)}
    record['execution_fact'] = client.render_execution_fact(record)
    target = Path(initial['corruption_path'])
    original, observed = corrupt_preserving_size_and_mtime(target)
    event = client._render_terminal_event(client.render_producer_binding(record))
    anchor = Path(supervisor['directory']) / (event + '.json')
    try:
        try:
            client.seal_render_terminal(record)
        except client.BridgeError as error:
            failure = error.code
        else:
            raise AssertionError('changed OCIO file was accepted before sealing')
        assert not anchor.exists(), 'failed seal wrote a terminal original'
        assert not anchor.with_suffix('.claim').exists(), 'failed seal consumed terminal claim'
        assert target.stat().st_mtime_ns == observed.st_mtime_ns
        assert target.stat().st_size == observed.st_size
        assert target.read_bytes() != original
    finally:
        restore_file(target, original, observed)
    sealed = client.seal_render_terminal(record)
    assert read_receipt(supervisor['directory'], event, identity=supervisor['identity']) == sealed
    _atomic(initial_path.parent / 'preseal-result.json', {
        'failure': failure, 'record': record, 'event': event,
        'restored_bytes_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})


class RenderOcioBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = receipts.HoudiniOutputReceiptTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def install_preflight(self):
        from houdini_bridge import render_ocio_facts

        self.ocio_directory = self.fixture.root / 'OCIO 配置 空格'
        self.ocio_directory.mkdir()
        self.config_path = self.ocio_directory / 'config.ocio'
        self.config_path.write_text(
            'ocio_profile_version: 2\nsearch_path: .\n'
            'fixture_transform: !<FileTransform> {src: look.spi1d}\n', encoding='utf-8')
        self.dependency_path = self.ocio_directory / 'look.spi1d'
        self.dependency_path.write_bytes(b'Version 1\nFrom 0 1\nLength 2\nComponents 1\n{\n0\n1\n}\n')
        self.native_hou = SimpleNamespace(Color=SimpleNamespace(
            ocio_configPath=lambda: str(self.config_path),
            ocio_spaces=lambda: ['fixture-linear', 'fixture-display'],
            ocio_roles=lambda: ['scene_linear'], ocio_activeDisplays=lambda: ['fixture-monitor'],
            ocio_activeViews=lambda: ['fixture-view']))
        self.native_ocio = SimpleNamespace(Config=SimpleNamespace(
            CreateFromFile=lambda path: NativeOcioConfigFixture(Path(path).parent)))
        self.collector = render_ocio_facts.collect_ocio_configuration
        self.validator = render_ocio_facts.validate_ocio_configuration
        self.fixture.record['render_config']['1']['ocio_configuration_fact'] = self.collect_preflight()
        self.refresh_configuration_binding()

    def collect_preflight(self):
        return self.collector(
            self.native_hou, final_output_path=str(self.fixture.path), ocio_module=self.native_ocio,
            transform_requests=[{'label': 'explicit-fixture-pair',
                                 'source': 'fixture-linear', 'destination': 'fixture-display'}])

    def refresh_configuration_binding(self):
        record = self.fixture.record
        record['scene_fingerprint'] = client.render_receipt_digest({
            'scene': record['scene']['snapshot_sha256'], 'config': record['render_config']})

    def assert_bridge_error(self, code, operation):
        with self.assertRaises(client.BridgeError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def assert_no_native_completion(self, observed):
        self.assertNotIn('colorspace', observed['metadata'])
        self.assertNotIn('premultiplied', observed['metadata'])
        self.assertIn('PROJECT_COLOR_SELECTION_REQUIRED', observed['missing_facts'])
        self.assertIn('KARMA_HUSK_BEAUTY_ALPHA_ASSOCIATION_REQUIRED', observed['missing_facts'])
        record = copy.deepcopy(self.fixture.record)
        record.update(output_facts={'1': observed}, completion_metadata_status='AVAILABLE',
                      metadata={'1': {'colorspace': 'linear', 'premultiplied': False}})
        execution = client.render_execution_fact(record)
        self.assertEqual(execution['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(execution['metadata'], {})

    def test_legacy_missing_preflight_is_explicitly_blocked(self):
        observed = client.collect_render_output_fact(self.fixture.record, 1)
        self.assertIn('PROJECT_COLOR_SELECTION_REQUIRED', observed['missing_facts'])
        self.assertIsNone(observed.get('ocio_configuration_fact'))
        self.assertNotIn('colorspace', observed['metadata'])
        self.assertNotIn('premultiplied', observed['metadata'])
        self.fixture.record['output_facts'] = {'1': observed}
        execution = client.render_execution_fact(self.fixture.record)
        self.assertEqual(execution['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(execution['metadata'], {})

    def test_signed_legacy_terminal_does_not_gain_native_metadata(self):
        self.fixture.persist_contract_fixture()
        execution = self.fixture.read()['execution_fact']
        observed = execution['output_facts']['1']
        self.assertIn('PROJECT_COLOR_SELECTION_REQUIRED', observed['missing_facts'])
        self.assertEqual(execution['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(execution['metadata'], {})

    def test_actual_preflight_is_detached_and_never_native_completion(self):
        self.install_preflight()
        preflight = self.fixture.record['render_config']['1']['ocio_configuration_fact']
        self.assertEqual(preflight['final_output_path'], str(self.fixture.path))
        self.assertEqual(preflight['source'], 'parent_houdini_preflight')
        self.assertEqual(preflight['config']['file'], {
            'path': str(self.config_path), 'bytes': self.config_path.stat().st_size,
            'sha256': hashlib.sha256(self.config_path.read_bytes()).hexdigest()})
        self.assertEqual(preflight['dependencies'], [{
            'path': str(self.dependency_path), 'bytes': self.dependency_path.stat().st_size,
            'sha256': hashlib.sha256(self.dependency_path.read_bytes()).hexdigest()}])
        self.validator(preflight)
        observed = client.collect_render_output_fact(self.fixture.record, 1)
        self.assertEqual(observed['ocio_configuration_fact'], preflight)
        self.assertNotIn('OCIO_PREFLIGHT_OBSERVATION_REQUIRED', observed['missing_facts'])
        self.assert_no_native_completion(observed)
        self.assertNotIn('colorspace', preflight)
        self.assertNotIn('premultiplied', preflight)
        self.assertNotIn('completion_metadata_status', preflight)
        preflight['config']['file']['sha256'] = '0' * 64
        preflight['dependencies'][0]['path'] = str(self.config_path)
        preflight['missing_facts'].clear()
        self.assertEqual(observed['ocio_configuration_fact']['config']['file']['sha256'],
                         hashlib.sha256(self.config_path.read_bytes()).hexdigest())
        self.assertEqual(observed['ocio_configuration_fact']['dependencies'][0]['path'],
                         str(self.dependency_path))
        self.assertTrue(observed['ocio_configuration_fact']['missing_facts'])

    def test_preflight_must_match_exact_output_override(self):
        self.install_preflight()
        preflight = self.fixture.record['render_config']['1']['ocio_configuration_fact']
        for alternate in (str(self.fixture.root / 'frame.002.exr'), self.fixture.path.name):
            with self.subTest(path=alternate):
                preflight['final_output_path'] = alternate
                self.refresh_configuration_binding()
                self.assert_bridge_error('RENDER_OUTPUT_BINDING_MISMATCH',
                    lambda: client.collect_render_output_fact(self.fixture.record, 1))

    def test_malformed_rehashed_preflight_is_not_an_observation(self):
        self.install_preflight()
        original = copy.deepcopy(self.fixture.record['render_config']['1']['ocio_configuration_fact'])
        for field, value in (('schema', 'counterfeit/1'), ('source', 'effective_writer'),
                             ('dependencies', [{'path': str(self.dependency_path)}])):
            with self.subTest(field=field):
                malformed = copy.deepcopy(original)
                malformed[field] = value
                self.fixture.record['render_config']['1']['ocio_configuration_fact'] = malformed
                self.refresh_configuration_binding()
                with self.assertRaises(ValueError):
                    self.validator(malformed)
                self.assert_bridge_error('RENDER_OCIO_CONFIGURATION_CHANGED',
                    lambda: client.collect_render_output_fact(self.fixture.record, 1))

    def test_collection_rehashes_config_and_dependency_with_restored_mtime(self):
        self.install_preflight()
        for path in (self.config_path, self.dependency_path):
            with self.subTest(file=path.name):
                original, observed = corrupt_preserving_size_and_mtime(path)
                try:
                    self.assertEqual(path.stat().st_size, observed.st_size)
                    self.assertEqual(path.stat().st_mtime_ns, observed.st_mtime_ns)
                    self.assert_bridge_error('RENDER_OCIO_CONFIGURATION_CHANGED',
                        lambda: client.collect_render_output_fact(self.fixture.record, 1))
                finally:
                    restore_file(path, original, observed)
        self.assert_no_native_completion(client.collect_render_output_fact(self.fixture.record, 1))

    def test_signed_consumer_rehashes_config_and_dependency(self):
        self.install_preflight()
        self.fixture.persist_contract_fixture()
        anchor = self.fixture.anchor_path.read_bytes()
        for path in (self.config_path, self.dependency_path):
            with self.subTest(file=path.name):
                original, observed = corrupt_preserving_size_and_mtime(path)
                try:
                    self.assertEqual(path.stat().st_mtime_ns, observed.st_mtime_ns)
                    self.assert_bridge_error('RENDER_OCIO_CONFIGURATION_CHANGED', self.fixture.read)
                    self.assertFalse(self.fixture.scheduler.snapshot()['active'])
                    self.assertEqual(self.fixture.anchor_path.read_bytes(), anchor)
                finally:
                    restore_file(path, original, observed)
        execution = self.fixture.read()['execution_fact']
        self.assertEqual(execution['completion_metadata_status'], 'BLOCKED_MISSING_NATIVE_FACTS')
        self.assertEqual(execution['metadata'], {})
        self.assertFalse(self.fixture.scheduler.snapshot()['active'])

    def test_independently_rehashed_counterfeit_cannot_replace_signed_terminal(self):
        self.install_preflight()
        self.fixture.persist_contract_fixture()
        original_record = copy.deepcopy(self.fixture.record)
        original_binding = copy.deepcopy(self.fixture.binding)
        anchor = self.fixture.anchor_path.read_bytes()
        for path in (self.config_path, self.dependency_path):
            with self.subTest(file=path.name):
                original, observed = corrupt_preserving_size_and_mtime(path)
                try:
                    counterfeit = self.collect_preflight()
                    self.validator(counterfeit)
                    self.assertNotEqual(counterfeit,
                        original_record['render_config']['1']['ocio_configuration_fact'])
                    self.fixture.record['render_config']['1']['ocio_configuration_fact'] = counterfeit
                    self.refresh_configuration_binding()
                    self.fixture.record['output_facts']['1'] = client.collect_render_output_fact(
                        self.fixture.record, 1)
                    self.fixture.persist()
                    self.assertEqual(self.fixture.record['execution_fact']['operation_receipt_sha256'],
                                     client.render_receipt_digest(self.fixture.record['execution_fact']))
                    self.assert_bridge_error('OPERATION_BINDING_MISMATCH', self.fixture.read)
                    self.fixture.binding['producer_binding'] = client.render_producer_binding(self.fixture.record)
                    self.assert_bridge_error('RENDER_TERMINAL_ANCHOR_MISMATCH', self.fixture.read)
                    self.assertEqual(self.fixture.anchor_path.read_bytes(), anchor)
                    self.assertFalse(self.fixture.scheduler.snapshot()['active'])
                finally:
                    restore_file(path, original, observed)
                    self.fixture.record = copy.deepcopy(original_record)
                    self.fixture.binding = copy.deepcopy(original_binding)
                    self.fixture.write_store()
        self.assertEqual(self.fixture.read()['execution_fact'], original_record['execution_fact'])

    def test_actual_producer_seal_rehashes_before_creating_terminal(self):
        from dcc_task_runtime.owned_process import launch, read_receipt

        self.install_preflight()
        executable = getattr(sys, '_base_executable', sys.executable)
        for index, path in enumerate((self.config_path, self.dependency_path)):
            with self.subTest(file=path.name):
                directory = self.fixture.root / ('preseal-' + str(index))
                directory.mkdir()
                supervisor = directory / 'supervisor'
                identity = {'task_id': self.fixture.record['task_id'], 'launch_nonce': uuid4().hex}
                record = copy.deepcopy(self.fixture.record)
                record['supervisor_binding'] = {'directory': str(supervisor), 'identity': identity}
                initial = directory / 'initial.json'
                initial.write_text(json.dumps({'record': record, 'corruption_path': str(path)}), encoding='utf-8')
                environment = {key: value for key, value in os.environ.items()
                               if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}}
                environment['PYTHONDONTWRITEBYTECODE'] = '1'
                handle = launch([executable, '-B', str(Path(__file__).resolve()),
                                 '--preseal-producer', str(initial)], directory=supervisor,
                                identity=identity, supervisor_executable=executable,
                                env=environment, budget_seconds=20)
                try:
                    status = handle.wait(timeout=12)
                    self.assertEqual(status, 0, (supervisor / 'child.stderr.log').read_text())
                    result = json.loads((directory / 'preseal-result.json').read_text(encoding='utf-8'))
                    self.assertEqual(result['failure'], 'RENDER_OCIO_CONFIGURATION_CHANGED')
                    self.assertEqual(result['restored_bytes_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                    terminal = read_receipt(supervisor, result['event'], identity=identity)
                    self.assertEqual(terminal['execution_fact'], result['record']['execution_fact'])
                    self.assertEqual(terminal['pid'], result['record']['host_identity']['pid'])
                    self.assertNotEqual(terminal['pid'], os.getpid())
                    self.assertIsNotNone(read_receipt(supervisor, 'stopped', identity=identity))
                    self.assert_no_native_completion(terminal['execution_fact']['output_facts']['1'])
                finally:
                    if handle.poll() is None:
                        handle.terminate()
                        handle.wait(timeout=8)

    def test_valid_preflight_cannot_validate_corrupted_exr_bytes(self):
        self.install_preflight()
        self.fixture.persist_contract_fixture()
        original, observed = corrupt_preserving_size_and_mtime(self.fixture.path)
        try:
            self.validator(self.fixture.record['render_config']['1']['ocio_configuration_fact'])
            self.assert_bridge_error('RENDER_OUTPUT_BYTES_UNVERIFIED',
                lambda: client.collect_render_output_fact(self.fixture.record, 1))
            self.assert_bridge_error('RENDER_OUTPUT_BYTES_UNVERIFIED', self.fixture.read)
            self.assertFalse(self.fixture.scheduler.snapshot()['active'])
        finally:
            restore_file(self.fixture.path, original, observed)
        self.assertEqual(self.fixture.read()['execution_fact']['completion_metadata_status'],
                         'BLOCKED_MISSING_NATIVE_FACTS')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--preseal-producer':
        run_preseal_producer(sys.argv[2])
    else:
        unittest.main(verbosity=2)
