"""Real registry/ownership/lease/rehash logic with only explicit bottom HOM APIs.

No DCC, worker, VEX, simulation, renderer or model is started. These tests do
not replace trust hooks or certify deformation, reopening or output evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_geometry_controls_program as program
from houdini_bridge import native_geometry_runtime_registry as runtime
from test_native_geometry_controls_host import Fixture, Geometry, Node, load_addon


class NativeGeometryRuntimeRegistryTests(unittest.TestCase):
    def setUp(self):
        self.addon = load_addon()
        self.fixture = self.enterContext(Fixture(self.addon, program.VERSIONS[0]))
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture.hou.frame = lambda: self.frame
        self.frame = 1.
        self.geometry_calls = []
        self.source = self.fixture.nodes['instance_source']
        self.source.geometry = self.native_geometry
        self.registry = runtime.Registry(self.addon.__dict__, hou_module=self.fixture.hou)
        self.roles = self.fixture.roles
        self.pack = self.fixture.pack
        self.fresh = set(self.roles)
        self.document = dict(schema=runtime.REST_SCHEMA, task_id=self.fixture.task,
            task_root=self.fixture.root, native_version=self.fixture.version,
            input_version='explicit-bottom-rest-v1', source_node_path=self.source.path(),
            output=0, frame=1., space='sop_local_rest', unit='SU', local_x_axis=[1, 0, 0],
            source_geometry_sha256=program.source_geometry_sha256(self.fixture.source))
        self.path = self.directory / 'rest.json'
        self.params = self.write_input()
        self.addon._fx_geometry_source_basis = self.registry.source_basis
        self.addon._fx_geometry_source_geometry = self.registry.source_geometry
        self.addon._fx_geometry_registration = self.registry.registration
        self.fixture.host.host = self.addon.__dict__
        self.tokens = []
        self.addCleanup(self.cleanup_cohorts)

    def cleanup_cohorts(self):
        for token, transaction in list(runtime._TRANSACTIONS.items()):
            if transaction['entry']['host'] is self.addon.__dict__:
                self.registry.end(token, False)
        for key, entry in list(runtime._COHORTS.items()):
            if entry['host'] is self.addon.__dict__:
                runtime._COHORTS.pop(key)

    def native_geometry(self, *, output_index):
        self.geometry_calls.append(output_index)
        return Geometry(self.fixture.source)

    def write_input(self, raw=None):
        if raw is None:
            raw = json.dumps(self.document, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.path.write_bytes(raw)
        return dict(frozen_input_manifest=[dict(index=0, identity=str(self.path),
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
            semantic_role='geometry_rest_basis', geometry_observation='native_sop_read')])

    def binding(self):
        return self.fixture.host.binding(self.roles, self.pack)

    def begin(self, params=None, fresh=None):
        token = self.registry.begin(self.params if params is None else params, self.roles,
                                    self.pack, self.fresh if fresh is None else fresh)
        self.tokens.append(token)
        return token

    def initialize(self, commit=True):
        token = self.begin()
        with self.addon._root_lease_fence(self.fixture.root, task_id=self.fixture.task, scope='sop'):
            result = self.fixture.host.initialize(self.params, self.roles, self.pack, self.fresh)
        record = json.loads(self.fixture.carrier.userData(runtime._REGISTRATION_KEY))
        if commit:
            self.registry.end(token, True)
        return token, record, result

    def refused(self, callback, code=None):
        with self.assertRaises(program.GeometryControlsError) as caught:
            callback()
        if code is not None:
            self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_missing_production_hook_baseline(self):
        from houdini_bridge.native_geometry_controls_host import Host
        bare = Host({}, hou_module=self.fixture.hou)
        self.refused(lambda: bare.call('_fx_geometry_source_basis', self.roles, self.pack, self.binding()),
                     'GEOMETRY_HOST_HOOK_REQUIRED')

    def test_actual_host_initializes_and_new_registry_verifies_same_process(self):
        for version in program.VERSIONS:
            with self.subTest(version=version):
                if version != self.fixture.version:
                    self.fixture.version = version
                    self.fixture.identity['version'] = version
                    self.fixture.hou.applicationVersionString = lambda: version
                    self.document['native_version'] = version
                    self.params = self.write_input()
                    self.addon._root_lease_issue(self.fixture.root, self.fixture.task, 'sop')
                token, record, result = self.initialize()
                self.assertIsInstance(result, dict)
                replacement = runtime.Registry(self.addon.__dict__, hou_module=self.fixture.hou)
                self.assertTrue(replacement.registration('verify', self.roles, self.pack, record))
                basis = replacement.source_basis(self.roles, self.pack, self.binding())
                self.assertEqual(basis['basis_input_sha256'], self.params['frozen_input_manifest'][0]['sha256'])
                self.assertEqual(basis['source_geometry_sha256'], self.document['source_geometry_sha256'])
                self.assertTrue(self.geometry_calls)
                self.assertEqual(set(self.geometry_calls), {0})
                self.assertNotIn(token, runtime._TRANSACTIONS)
                self.cleanup_cohorts()
                self.fixture.carrier.userdata.clear()
                self.fixture.carrier.parameters['snippet'].set('')

    def test_current_host_globals_are_read_live_not_snapshotted(self):
        self.begin()
        identity = copy.deepcopy(self.fixture.identity)
        identity['launch_nonce'] = 'changed-live-nonce'
        self.addon._TASK_HOST_IDENTITY = identity
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, self.binding()))

    def test_missing_empty_and_ambiguous_basis_fail_before_geometry(self):
        cases = [{}, dict(frozen_input_manifest=[])]
        duplicate = copy.deepcopy(self.params)
        duplicate['frozen_input_manifest'].append(dict(duplicate['frozen_input_manifest'][0], index=1))
        cases.append(duplicate)
        for params in cases:
            with self.subTest(params=params):
                self.refused(lambda: self.begin(params), 'GEOMETRY_REST_INPUT_REQUIRED')
        self.assertFalse(self.geometry_calls)

    def test_tampered_bytes_and_hash_substitution_cannot_refresh_context(self):
        self.initialize()
        self.document['input_version'] = 'forged-version'
        new_params = self.write_input()
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, self.binding()),
                     'GEOMETRY_REST_INPUT_CHANGED')
        self.refused(lambda: self.begin(new_params, fresh=set()))

    def test_declared_hash_and_byte_count_are_both_enforced(self):
        for field, value in (('sha256', '0' * 64), ('bytes', 1), ('bytes', True)):
            with self.subTest(field=field, value=value):
                params = copy.deepcopy(self.params)
                params['frozen_input_manifest'][0][field] = value
                self.refused(lambda: self.begin(params))
        self.assertFalse(self.geometry_calls)

    def test_rehash_uses_same_bounded_bytes_without_reopening_unsafe_path(self):
        calls = []
        original = self.addon._rehash_frozen_input_manifest
        def observe(manifest):
            calls.append(copy.deepcopy(manifest))
            return original(manifest)
        with patch.object(self.addon, '_rehash_frozen_input_manifest', observe):
            self.begin()
        self.assertTrue(calls[0][0]['source_uri'].startswith('data:application/octet-stream;base64,'))
        self.assertEqual(calls[0][0]['sha256'], self.params['frozen_input_manifest'][0]['sha256'])
        self.assertEqual(calls[0][0]['bytes'], self.params['frozen_input_manifest'][0]['bytes'])

    def test_authenticated_document_can_explicitly_authorize_native_observation(self):
        self.document['geometry_observation'] = 'native_sop_read'
        params = self.write_input()
        params['frozen_input_manifest'][0].pop('geometry_observation')
        self.begin(params)
        basis = self.registry.source_basis(self.roles, self.pack, self.binding())
        self.assertEqual(basis['geometry_observation'], 'native_sop_read')
        self.assertIsNotNone(self.registry.source_geometry(self.source, basis))

    def test_identity_drift_during_input_verification_cannot_publish_cohort(self):
        original = self.addon._rehash_frozen_input_manifest
        def drift_identity(manifest):
            result = original(manifest)
            self.addon._TASK_HOST_IDENTITY = dict(self.fixture.identity, launch_nonce='during-read')
            return result
        with patch.object(self.addon, '_rehash_frozen_input_manifest', drift_identity):
            self.refused(lambda: self.begin(), 'GEOMETRY_AUTHENTICATED_HOST_REQUIRED')
        self.assertFalse(any(entry['host'] is self.addon.__dict__ for entry in runtime._COHORTS.values()))

    def test_input_replacement_during_rehash_is_refused(self):
        original = self.addon._rehash_frozen_input_manifest
        def replace_file(manifest):
            result = original(manifest)
            self.path.unlink()
            self.path.write_bytes(b'private replacement')
            return result
        with patch.object(self.addon, '_rehash_frozen_input_manifest', replace_file):
            self.refused(lambda: self.begin(), 'GEOMETRY_REST_INPUT_CHANGED')

    def test_duplicate_json_keys_nonfinite_and_arbitrary_hooks_are_refused(self):
        valid = json.dumps(self.document)
        invalid = [valid[:-1] + ', "frame": 1}', valid.replace('"frame": 1.0', '"frame": NaN'),
                   valid[:-1] + ', "source_geometry_callback": "unsafe"}']
        for raw in invalid:
            with self.subTest(raw=raw):
                params = self.write_input(raw.encode('utf-8'))
                self.refused(lambda: self.begin(params))

    def test_rest_schema_scope_and_authorization_are_explicit(self):
        original = copy.deepcopy(self.document)
        variants = [('task_id', 'foreign'), ('task_root', '/obj/foreign'),
            ('native_version', program.VERSIONS[1]), ('input_version', ''),
            ('source_node_path', self.roles[program.ROLE]), ('output', True), ('output', 1),
            ('space', 'world'), ('unit', 'm'), ('local_x_axis', [True, 0, 0]),
            ('source_geometry_sha256', 'bad')]
        for field, value in variants:
            with self.subTest(field=field):
                self.document = dict(original, **{field: value})
                self.refused(lambda: self.begin(self.write_input()))
        self.document = original
        params = self.write_input()
        params['frozen_input_manifest'][0].pop('geometry_observation')
        self.refused(lambda: self.begin(params), 'GEOMETRY_AUTHENTICATED_REST_BASIS_REQUIRED')

    def test_frame_drift_refuses_native_read_without_changing_frame(self):
        self.begin()
        basis = self.registry.source_basis(self.roles, self.pack, self.binding())
        self.frame = 2.
        self.refused(lambda: self.registry.source_geometry(self.source, basis), 'GEOMETRY_SOURCE_FRAME_REQUIRED')
        self.assertFalse(self.geometry_calls)
        self.assertEqual(self.frame, 2.)

    def test_static_source_cross_frame_read_uses_explicit_rest_frame_both_builds(self):
        for version in program.VERSIONS:
            with self.subTest(version=version):
                self.fixture.version = version
                self.fixture.identity['version'] = version
                self.fixture.hou.applicationVersionString = lambda: version
                self.document['native_version'] = version
                self.params = self.write_input()
                self.addon._root_lease_issue(self.fixture.root, self.fixture.task, 'sop')
                self.frame = 1.
                self.initialize()
                rest_calls = []
                def rest_geometry(frame, *, output_index):
                    rest_calls.append((frame, output_index))
                    return Geometry(self.fixture.source)
                self.source.geometryAtFrame = rest_geometry
                try:
                    for frame in (-2., 0., 2.):
                        self.frame = frame
                        observed = self.fixture.host.observations(self.roles, self.pack)
                        self.assertEqual(observed['context']['source']['frame'], 1.)
                        sampling = observed['context']['source_sampling']
                        self.assertEqual(sampling['rest_frame'], 1.)
                        self.assertEqual(sampling['current_frame'], frame)
                        self.assertTrue(sampling['static_source_verified'])
                        self.assertEqual(self.frame, frame)
                    self.assertEqual(rest_calls, [(1., 0)] * 3)
                finally:
                    self.cleanup_cohorts()
                    self.fixture.carrier.userdata.clear()
                    self.fixture.carrier.parameters['snippet'].set('')

    def cross_frame_source(self):
        self.begin()
        provenance = self.registry.source_basis(self.roles, self.pack, self.binding())
        rest = copy.deepcopy(self.fixture.source)
        self.rest_calls = []
        def rest_geometry(frame, *, output_index):
            self.rest_calls.append((frame, output_index))
            return Geometry(rest)
        self.source.geometryAtFrame = rest_geometry
        self.frame = 2.
        return provenance, rest

    def test_cross_frame_current_geometry_cannot_be_relabelled_as_rest(self):
        for mutation in ('P', 'N', 'id', 'topology', 'precision'):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.fixture.source)
                provenance, _ = self.cross_frame_source()
                if mutation == 'topology':
                    self.fixture.source['polygons'][0].reverse()
                elif mutation == 'precision':
                    attribute = self.fixture.source['point_attributes']['P']
                    attribute['precision'] = 'float32' if attribute['precision'] == 'float64' else 'float64'
                elif mutation == 'id':
                    self.fixture.source['point_attributes']['id']['values'][0] += 10000
                elif mutation == 'N':
                    self.fixture.source['point_attributes']['N']['values'][0] = [1., 0., 0.]
                else:
                    self.fixture.source['point_attributes']['P']['values'][0][0] += .25
                try:
                    self.refused(lambda: self.registry.source_geometry(self.source, provenance),
                                 'GEOMETRY_STATIC_SOURCE_REQUIRED')
                    self.assertEqual(self.rest_calls, [(1., 0)])
                    self.assertEqual(self.frame, 2.)
                finally:
                    self.fixture.source = original
                    self.cleanup_cohorts()

    def test_cross_frame_rest_geometry_must_match_frozen_hash(self):
        provenance, rest = self.cross_frame_source()
        rest['point_attributes']['P']['values'][0][0] += .5
        self.refused(lambda: self.registry.source_geometry(self.source, provenance), 'GEOMETRY_BASIS_CHANGED')
        self.assertFalse(self.geometry_calls)
        self.assertEqual(self.frame, 2.)

    def test_cross_frame_missing_geometry_outputs_are_refused(self):
        for missing in ('rest', 'current'):
            with self.subTest(missing=missing):
                provenance, _ = self.cross_frame_source()
                if missing == 'rest':
                    self.source.geometryAtFrame = lambda frame, *, output_index: None
                else:
                    self.source.geometry = lambda *, output_index: None
                self.refused(lambda: self.registry.source_geometry(self.source, provenance),
                             'GEOMETRY_REST_SOURCE_REQUIRED')
                self.assertEqual(self.frame, 2.)
                self.cleanup_cohorts()
                self.source.geometry = self.native_geometry

    def test_cross_frame_delayed_rest_and_current_reads_keep_all_guards(self):
        for stage in ('rest', 'current'):
            for drift in ('frame', 'input', 'node', 'identity'):
                with self.subTest(stage=stage, drift=drift):
                    provenance, rest = self.cross_frame_source()
                    original_identity = copy.deepcopy(self.fixture.identity)
                    original_session = self.source.session
                    class DelayedGeometry(Geometry):
                        def points(inner):
                            if drift == 'frame':
                                self.frame = 3.
                            elif drift == 'input':
                                self.path.write_bytes(b'changed during lazy read')
                            elif drift == 'node':
                                self.source.session += 1
                            else:
                                self.fixture.identity['launch_nonce'] = 'changed during lazy read'
                            return super().points()
                    if stage == 'rest':
                        self.source.geometryAtFrame = lambda frame, *, output_index: DelayedGeometry(rest)
                    else:
                        self.source.geometry = lambda *, output_index: DelayedGeometry(self.fixture.source)
                    try:
                        self.refused(lambda: self.registry.source_geometry(self.source, provenance))
                        self.assertEqual(self.frame, 3. if drift == 'frame' else 2.)
                    finally:
                        self.fixture.identity.clear()
                        self.fixture.identity.update(original_identity)
                        self.source.session = original_session
                        self.source.geometry = self.native_geometry
                        self.cleanup_cohorts()
                        self.params = self.write_input()

    def test_cross_frame_api_failure_does_not_leak_native_details(self):
        provenance, _ = self.cross_frame_source()
        def unsafe(frame, *, output_index):
            raise RuntimeError('secret-token PRIVATE-PATH')
        self.source.geometryAtFrame = unsafe
        error = self.refused(lambda: self.registry.source_geometry(self.source, provenance),
                             'GEOMETRY_REGISTRY_REFUSED')
        self.assertNotIn('secret-token', str(error))
        self.assertNotIn('PRIVATE-PATH', str(error))
        self.assertEqual(self.frame, 2.)

    def test_cross_frame_parameter_lazy_read_rechecks_identity_file_and_node(self):
        for drift in ('input', 'identity', 'node'):
            with self.subTest(drift=drift):
                self.frame = 1.
                self.initialize()
                self.source.geometryAtFrame = lambda frame, *, output_index: Geometry(self.fixture.source)
                self.frame = 2.
                original_identity = copy.deepcopy(self.fixture.identity)
                original_session = self.source.session
                observe = self.addon._fx_planned_observation
                def delayed(node, name):
                    value = observe(node, name)
                    if drift == 'input':
                        self.path.write_bytes(b'changed during parameter collection')
                    elif drift == 'identity':
                        self.fixture.identity['launch_nonce'] = 'parameter-lazy-drift'
                    else:
                        self.source.session += 1
                    return value
                self.addon._fx_planned_observation = delayed
                self.fixture.set_calls.clear()
                try:
                    self.refused(lambda: self.fixture.host.observations(self.roles, self.pack))
                    self.assertFalse(self.fixture.set_calls)
                    self.assertEqual(self.frame, 2.)
                finally:
                    self.addon._fx_planned_observation = observe
                    self.fixture.identity.clear()
                    self.fixture.identity.update(original_identity)
                    self.source.session = original_session
                    self.cleanup_cohorts()
                    self.params = self.write_input()
                    self.fixture.carrier.userdata.clear()
                    self.fixture.carrier.parameters['snippet'].set('')

    def test_cross_frame_sampling_does_not_change_persisted_checkpoint(self):
        self.initialize()
        before = self.registry.checkpoint(self.roles, self.pack)
        userdata = dict(self.fixture.carrier.userdata)
        self.source.geometryAtFrame = lambda frame, *, output_index: Geometry(self.fixture.source)
        self.frame = 2.
        self.fixture.set_calls.clear()
        after = self.registry.checkpoint(self.roles, self.pack)
        self.assertEqual(before, after)
        self.assertEqual(userdata, self.fixture.carrier.userdata)
        self.assertFalse(self.fixture.set_calls)
        self.assertNotIn('source_sampling', after['basis'])
        self.assertEqual(self.frame, 2.)

    def test_cross_frame_actual_input_failure_preserves_native_rollback(self):
        self.initialize()
        self.source.geometryAtFrame = lambda frame, *, output_index: Geometry(self.fixture.source)
        self.frame = 2.
        item = self.fixture.prepared(3)
        snippet = self.fixture.carrier.parameters['snippet']
        before = snippet.eval()
        def drift():
            self.path.write_bytes(b'input changed after native write')
            snippet.on_set = None
        snippet.on_set = drift
        try:
            self.refused(lambda: self.fixture.write(item))
            self.assertNotEqual(snippet.eval(), before)
            self.assertEqual(self.fixture.restore(item)['status'], 'restored')
            self.assertEqual(snippet.eval(), before)
            self.refused(lambda: self.fixture.host.observations(self.roles, self.pack))
            self.assertEqual(self.frame, 2.)
        finally:
            self.fixture.host.release(item)

    def test_frame_and_input_drift_during_native_read_are_refused(self):
        self.begin()
        basis = self.registry.source_basis(self.roles, self.pack, self.binding())
        def drift_frame(*, output_index):
            self.frame = 2.
            return Geometry(self.fixture.source)
        self.source.geometry = drift_frame
        self.refused(lambda: self.registry.source_geometry(self.source, basis), 'GEOMETRY_SOURCE_FRAME_REQUIRED')
        self.frame = 1.
        def drift_input(*, output_index):
            self.path.write_bytes(b'changed')
            return Geometry(self.fixture.source)
        self.source.geometry = drift_input
        self.refused(lambda: self.registry.source_geometry(self.source, basis))

    def test_pid_nonce_version_scene_epoch_and_host_session_drift_are_refused(self):
        self.initialize()
        binding = self.binding()
        identity = copy.deepcopy(self.fixture.identity)
        for field, value in [('pid', os.getpid() + 1), ('launch_nonce', 'reopened'),
                ('version', program.VERSIONS[1]), ('session_id', 'foreign-session'),
                ('process_generation', 'foreign-generation')]:
            with self.subTest(field=field):
                self.addon._TASK_HOST_IDENTITY = dict(identity, **{field: value})
                self.refused(lambda: self.registry.source_basis(self.roles, self.pack, binding))
        self.addon._TASK_HOST_IDENTITY = identity
        self.addon._BRIDGE_SCENE_STATE.scene_epoch = 1
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, binding))

    def test_node_session_replacement_and_actual_instance_forgery_are_refused(self):
        self.begin()
        binding = self.binding()
        node = self.fixture.carrier
        node.session += 100
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, binding), 'GEOMETRY_NODE_SESSION_CHANGED')
        node.session -= 100
        self.fixture.nodes[program.ROLE] = Node(self.fixture, node.path(), node.kind, node.session)
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, binding), 'GEOMETRY_NODE_SESSION_CHANGED')

    def test_extra_role_fresh_role_and_duplicate_node_forgery_are_refused(self):
        roles = dict(self.roles, forged='/obj/g03_unit/extra')
        self.refused(lambda: self.registry.begin(self.params, roles, self.pack, self.fresh))
        self.refused(lambda: self.begin(fresh=self.fresh | {'forged'}), 'GEOMETRY_FRESH_COHORT_REQUIRED')
        self.refused(lambda: self.begin(fresh=[]), 'GEOMETRY_REGISTERED_COHORT_REQUIRED')
        roles = dict(self.roles, instance_transform=self.roles[program.ROLE])
        self.refused(lambda: self.registry.begin(self.params, roles, self.pack, self.fresh))

    def test_source_provenance_and_binding_forgery_are_refused(self):
        self.begin()
        binding = self.binding()
        forged = dict(binding, host_identity=dict(binding['host_identity'], pid=os.getpid() + 1))
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, forged))
        basis = self.registry.source_basis(self.roles, self.pack, binding)
        forged = dict(basis, source_geometry_sha256='0' * 64)
        self.refused(lambda: self.registry.source_geometry(self.source, forged))
        self.refused(lambda: self.registry.source_geometry(self.fixture.carrier, basis))
        self.assertFalse(self.geometry_calls)

    def test_outer_rollback_discards_registered_record_and_source_context(self):
        token, record, _ = self.initialize(commit=False)
        self.assertTrue(self.registry.registration('verify', self.roles, self.pack, record))
        self.assertTrue(self.registry.end(token, False))
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, record),
                     'GEOMETRY_REGISTERED_COHORT_REQUIRED')
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, self.binding()))

    def test_existing_committed_rebuild_rollback_preserves_registration(self):
        _, record, _ = self.initialize()
        token = self.begin(fresh=set())
        self.fixture.host.initialize(self.params, self.roles, self.pack, set())
        self.registry.end(token, False)
        self.assertTrue(self.registry.registration('verify', self.roles, self.pack, record))
        token = self.begin(fresh=set())
        self.registry.end(token, True)
        self.assertTrue(self.registry.registration('verify', self.roles, self.pack, record))

    def test_fresh_authorization_only_with_active_owned_transaction(self):
        _, record, _ = self.initialize()
        self.refused(lambda: self.registry.registration('authorize_fresh', self.roles, self.pack, record),
                     'GEOMETRY_FRESH_COHORT_REQUIRED')
        token = self.begin(fresh=set())
        self.refused(lambda: self.registry.registration('authorize_fresh', self.roles, self.pack, record),
                     'GEOMETRY_FRESH_COHORT_REQUIRED')
        self.registry.end(token, False)

    def test_exact_record_verify_and_idempotent_revoke(self):
        _, record, _ = self.initialize()
        forged = dict(record, basis_sha256='0' * 64)
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, forged))
        self.refused(lambda: self.registry.registration('revoke', self.roles, self.pack, forged))
        self.assertTrue(self.registry.registration('verify', self.roles, self.pack, record))
        self.registry.registration('revoke', self.roles, self.pack, record)
        self.assertTrue(self.registry.registration('revoke', self.roles, self.pack, record))
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, record))
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, self.binding()))

    def test_actual_userdata_record_must_match_process_registration(self):
        _, record, _ = self.initialize()
        self.fixture.carrier.setUserData(runtime._REGISTRATION_KEY,
            json.dumps(dict(record, basis_sha256='0' * 64)))
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, record))
        self.refused(lambda: self.begin(fresh=set()))

    def test_restore_authority_survives_input_change_after_actual_snippet_set(self):
        _, record, _ = self.initialize()
        binding = self.binding()
        snippet = self.fixture.carrier.parameters['snippet']
        old_program = snippet.eval()
        snippet.set('float deform_amplitude = 0.25;\n')
        self.path.write_bytes(b'changed after actual native setter')
        calls = list(self.geometry_calls)
        self.assertTrue(self.registry.registration('authorize_restore', self.roles, self.pack, record))
        self.assertEqual(snippet.eval(), 'float deform_amplitude = 0.25;\n')
        self.assertEqual(self.geometry_calls, calls)
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, record))
        self.refused(lambda: self.registry.source_basis(self.roles, self.pack, binding))
        snippet.set(old_program)
        self.assertEqual(snippet.eval(), old_program)
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, record))

    def test_restore_authority_uses_stored_record_with_missing_input_and_tampered_userdata(self):
        _, record, _ = self.initialize()
        self.path.unlink()
        self.fixture.carrier.setUserData(runtime._REGISTRATION_KEY, 'tampered userdata')
        self.fixture.carrier.setUserData(runtime._BASIS_KEY, 'tampered basis')
        calls = list(self.geometry_calls)
        self.assertTrue(self.registry.registration('authorize_restore', self.roles, self.pack, record))
        self.assertEqual(self.geometry_calls, calls)
        self.refused(lambda: self.registry.registration('verify', self.roles, self.pack, record))
        self.refused(lambda: self.registry.registration('register', self.roles, self.pack, record))
        self.refused(lambda: self.registry.registration('authorize_fresh', self.roles, self.pack, record))

    def test_restore_authority_rejects_replaced_actual_target_and_node_session(self):
        _, record, _ = self.initialize()
        self.path.unlink()
        node = self.fixture.carrier
        node.session += 100
        self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record),
                     'GEOMETRY_NODE_SESSION_CHANGED')
        node.session -= 100
        self.fixture.nodes[program.ROLE] = Node(self.fixture, node.path(), node.kind, node.session)
        self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record),
                     'GEOMETRY_NODE_SESSION_CHANGED')

    def test_restore_authority_rejects_new_pid_nonce_session_version_and_epoch(self):
        _, record, _ = self.initialize()
        self.path.unlink()
        identity = copy.deepcopy(self.fixture.identity)
        for field, value in [('pid', os.getpid() + 1), ('launch_nonce', 'reopened'),
                ('session_id', 'foreign-session'), ('process_generation', 'foreign-generation'),
                ('version', program.VERSIONS[1])]:
            with self.subTest(field=field):
                self.addon._TASK_HOST_IDENTITY = dict(identity, **{field: value})
                self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record))
        self.addon._TASK_HOST_IDENTITY = identity
        self.addon._BRIDGE_SCENE_STATE.scene_epoch = 1
        self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record))

    def test_restore_authority_rejects_changed_root_and_foreign_record(self):
        _, record, _ = self.initialize()
        self.path.unlink()
        original = self.fixture.root_node
        self.fixture.root_node = Node(self.fixture, original.path(), original.kind, original.session)
        self.fixture.root_node.userdata = copy.deepcopy(original.userdata)
        self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record),
                     'GEOMETRY_NODE_SESSION_CHANGED')
        self.fixture.root_node = original
        for field, value in [('basis_sha256', '0' * 64), ('task_id', 'foreign-task')]:
            with self.subTest(field=field):
                foreign = dict(record, **{field: value})
                self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, foreign),
                             'GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')

    def test_restore_authority_never_accepts_revoked_or_userdata_only_registration(self):
        _, record, _ = self.initialize()
        self.registry.registration('revoke', self.roles, self.pack, record)
        self.path.unlink()
        self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record),
                     'GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
        self.cleanup_cohorts()
        self.refused(lambda: self.registry.registration('authorize_restore', self.roles, self.pack, record),
                     'GEOMETRY_REGISTERED_COHORT_REQUIRED')

    def test_register_requires_prior_exact_authorization(self):
        token, record, _ = self.initialize(commit=False)
        self.registry.registration('revoke', self.roles, self.pack, record)
        forged = dict(record, basis_sha256='0' * 64)
        self.refused(lambda: self.registry.registration('register', self.roles, self.pack, forged))
        self.registry.end(token, False)

    def test_userdata_only_and_empty_registry_never_reconstitute_trust(self):
        _, record, _ = self.initialize()
        self.cleanup_cohorts()
        replacement = runtime.Registry(self.addon.__dict__, hou_module=self.fixture.hou)
        self.refused(lambda: replacement.registration('verify', self.roles, self.pack, record),
                     'GEOMETRY_REGISTERED_COHORT_REQUIRED')
        self.refused(lambda: replacement.begin(self.params, self.roles, self.pack, set()),
                     'GEOMETRY_REGISTERED_COHORT_REQUIRED')
        self.refused(lambda: replacement.begin(self.params, self.roles, self.pack, self.fresh),
                     'GEOMETRY_FRESH_COHORT_REQUIRED')

    def test_native_failure_cannot_leak_paths_or_secrets(self):
        self.begin()
        basis = self.registry.source_basis(self.roles, self.pack, self.binding())
        def unsafe(*, output_index):
            raise RuntimeError('secret-token PRIVATE-PATH')
        self.source.geometry = unsafe
        error = self.refused(lambda: self.registry.source_geometry(self.source, basis), 'GEOMETRY_REGISTRY_REFUSED')
        self.assertNotIn('secret-token', str(error))
        self.assertNotIn('PRIVATE-PATH', str(error))
        trace = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        self.assertNotIn('secret-token', trace)
        self.assertNotIn('PRIVATE-PATH', trace)

    def test_token_scope_invalid_commit_and_active_cohort_are_refused(self):
        token = self.begin()
        self.refused(lambda: self.begin(), 'GEOMETRY_FRESH_COHORT_REQUIRED')
        self.refused(lambda: self.registry.end(token, True), 'GEOMETRY_REGISTERED_INITIALIZATION_REQUIRED')
        self.refused(lambda: self.registry.end(token, 1), 'GEOMETRY_TRANSACTION_REQUIRED')
        foreign = runtime.Registry({}, hou_module=self.fixture.hou)
        self.refused(lambda: foreign.end(token, False), 'GEOMETRY_TRANSACTION_REQUIRED')
        self.assertTrue(self.registry.end(token, False))
        self.refused(lambda: self.registry.end(token, False), 'GEOMETRY_TRANSACTION_REQUIRED')

    def test_budget_and_unsafe_paths_are_refused_before_native_read(self):
        self.refused(lambda: self.begin(self.write_input(b' ' * (runtime.MAX_REST_BYTES + 1))))
        self.params = self.write_input()
        for name in ('relative.json', str(self.directory / '..' / 'rest.json'),
                     str(self.path) + ':alternate', '//server/share/rest.json'):
            with self.subTest(name=name):
                params = copy.deepcopy(self.params)
                params['frozen_input_manifest'][0]['identity'] = name
                self.refused(lambda: self.begin(params))
        self.assertFalse(self.geometry_calls)

    def test_manifest_count_budget_rejects_before_reading(self):
        params = copy.deepcopy(self.params)
        params['frozen_input_manifest'] *= runtime.MAX_MANIFEST_ITEMS + 1
        self.refused(lambda: self.begin(params), 'GEOMETRY_REST_INPUT_REQUIRED')
        self.assertFalse(self.geometry_calls)

    def test_hardlink_is_refused(self):
        link = self.directory / 'hardlink.json'
        os.link(self.path, link)
        self.refused(lambda: self.begin())
        link.unlink()

    def test_ancestor_reparse_point_is_refused_at_bottom_filesystem_boundary(self):
        original = Path.lstat
        def native_lstat(path, *args, **kwargs):
            information = original(path, *args, **kwargs)
            if path == self.directory:
                fields = {name: getattr(information, name) for name in dir(information)
                          if name.startswith('st_')}
                fields['st_file_attributes'] = fields.get('st_file_attributes', 0) | 0x400
                return SimpleNamespace(**fields)
            return information
        with patch.object(Path, 'lstat', native_lstat):
            self.refused(lambda: self.begin(), 'GEOMETRY_REGISTRY_REFUSED')


if __name__ == '__main__':
    unittest.main()
