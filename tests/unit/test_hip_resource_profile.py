"""HIP240 controller checks; no DCC or native module is dispatched."""
from __future__ import annotations
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import run_hip_diagnostic as hip
from dcc_task_runtime.native_scope import NativeScope, HIP_RESOURCE_PROFILE, HIP_BUDGET, HIP_ROLE_SECONDS


class HipResourceProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='hip360-controller-', dir='/private/tmp')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.ocio = self.root / 'test.ocio'
        self.ocio.write_text('explicit software configuration\n')
        self.counter = 0

    def candidate(self, profile=HIP_RESOURCE_PROFILE):
        self.counter += 1
        return hip.prepare(self.root / ('candidate-' + str(self.counter)),
            plan=ROOT / 'handover/HIP_RESOURCE_PROPOSAL_20261024.md',
            hython=Path(sys.executable).resolve(), supervisor_python=Path(sys.executable).resolve(),
            ocio_config=self.ocio, evidence_source='software_test', resource_profile=profile)

    def test_explicit_profile_is_frozen_but_default_stays_legacy_and_zero_launch(self):
        with mock.patch.object(hip.owned_process, 'launch', side_effect=AssertionError('native forbidden')) as launch:
            old = self.candidate(None)
            legacy = hip.frozen_data(old['scope']['path'])
            self.assertIsNone(legacy['native'].resource_profile)
            self.assertEqual(legacy['native'].scope['budget'], hip.OUTER_BUDGET)
            self.assertEqual(legacy['freeze']['limits'], hip.LIMITS)
            new = self.candidate()
            data = hip.frozen_data(new['scope']['path'])
            self.assertEqual(data['native'].scope['budget'], HIP_BUDGET)
            self.assertEqual(data['freeze']['limits']['role_seconds'], HIP_ROLE_SECONDS)
            self.assertEqual(data['limits']['total_seconds'], 360)
            self.assertFalse(data['native'].scope['execution_authorized'])
            self.assertEqual(data['native'].snapshot()['dcc_starts'], 0)
            with self.assertRaisesRegex(ValueError, 'RESOURCE_PROFILE'):
                self.candidate('untrusted-model-choice')
        launch.assert_not_called()

    def test_activation_requires_new_explicit_resource_confirmation(self):
        prepared = self.candidate()
        data = hip.frozen_data(prepared['scope']['path'])
        target = self.root / 'authorized'
        expected = {'candidate_scope': prepared['scope'], 'candidate_freeze': prepared['freeze'],
            'source_sha256': hashlib.sha256(hip.canonical(data['freeze']['sources'])).hexdigest(),
            'target_root': str(target)}
        review_base = {'schema': 'bridge.hip-diagnostic.review/1', 'decision': 'APPROVED',
            'reviewer': '/root/hip_only_plan_review', **expected}
        old_review = hip.write(self.root / 'old-review.json', review_base)
        old_auth = hip.write(self.root / 'old-authorization.json', {
            'schema': 'bridge.hip-diagnostic.conditional-authorization/1',
            'authority': 'current_user_conditional_instruction', 'instruction': hip.AUTH_TEXT,
            'review': old_review, **expected})
        with self.assertRaisesRegex(ValueError, 'RESOURCE_CONTRACT'):
            hip.activate(prepared['scope']['path'], review_path=old_review['path'],
                authorization_path=old_auth['path'], output_root=target)
        contract = {'resource_profile': HIP_RESOURCE_PROFILE, 'resource_contract': data['limits']}
        review = hip.write(self.root / 'review.json', {**review_base, **contract})
        auth_base = {'schema': 'bridge.hip-diagnostic.conditional-authorization/1',
            'authority': 'current_user_resource_contract_confirmation',
            'instruction': '同意新预算，审核后执行', 'review': review, **expected, **contract}
        altered = json.loads(json.dumps(auth_base)); altered['resource_contract']['role_seconds']['houdini-host'] = 240
        bad = hip.write(self.root / 'bad-auth.json', altered)
        with self.assertRaisesRegex(ValueError, 'RESOURCE_CONTRACT'):
            hip.activate(prepared['scope']['path'], review_path=review['path'],
                authorization_path=bad['path'], output_root=target)
        auth = hip.write(self.root / 'authorization.json', auth_base)
        result = hip.activate(prepared['scope']['path'], review_path=review['path'],
            authorization_path=auth['path'], output_root=target)
        self.assertEqual(result['state'], 'AUTHORIZED_FOR_EXPLICIT_LIVE_EXECUTION')
        self.assertEqual(result['dcc_starts'], 0)
        self.assertEqual(NativeScope(result['scope']).role_seconds('houdini-host'), 120)

    def test_admission_has_role_limits_and_single_stop_reserve(self):
        p = self.candidate(); native = NativeScope(p['scope']); state = native.snapshot()
        self.assertEqual(hip.admission(native, 0)['max_seconds'], 230)
        graph = {'role': 'graph-worker', 'stopped_at': 1, 'charged_seconds': 239.5}
        second = {**state, 'dcc_starts': 1, 'tickets': [graph], 'total_seconds': 239.5}
        with mock.patch.object(native, 'snapshot', return_value=second):
            self.assertEqual(hip.admission(native, 1)['max_seconds'], 110)
        for bad in ({**second, 'tickets': [{**graph, 'charged_seconds': 240.001}]},
                    {**second, 'tickets': [{**graph, 'stopped_at': None}]},
                    {**second, 'total_seconds': 360}):
            with mock.patch.object(native, 'snapshot', return_value=bad):
                with self.assertRaisesRegex(ValueError, 'ADMISSION'):
                    hip.admission(native, 1)

    def test_graph_uses_original_deadline_when_launch_takes_time(self):
        service = types.SimpleNamespace(operation_deadline=lambda _: 1240, clock=lambda: 1000)
        with mock.patch.object(hip.time, 'monotonic', return_value=100):
            self.assertEqual(hip.graph_deadlines(service, 'op', 340, 10), (1240, 340, 330))
        service.clock = lambda: 1020
        with mock.patch.object(hip.time, 'monotonic', return_value=120):
            self.assertEqual(hip.graph_deadlines(service, 'op', 340, 10), (1240, 340, 330))

    def test_cold_runner_reserves_ten_once_for_new_profile(self):
        captures = []
        def serve(**kwargs):
            captures.append(kwargs)
            return {'stop_reason': 'stop_file'}
        addon = types.SimpleNamespace(task_host_serve=serve)
        for profile, expected in ((None, 100), (HIP_RESOURCE_PROFILE, 110)):
            data = {'frozen': ROOT, 'config': {'task_id': 'software-host', 'resource_profile': profile}}
            raw = hip.cold_runner(data, self.root, 'explicit-software-nonce', {'max_seconds': 110})
            with mock.patch.dict(sys.modules, {'houdini_bridge_addon': addon}), \
                    mock.patch.object(sys, 'path', list(sys.path)):
                exec(compile(raw, 'fixed-software-runner', 'exec'), {'__name__': '__main__'})
            self.assertEqual(captures[-1]['max_seconds'], expected)
            self.assertFalse(captures[-1]['warmup'])
            self.assertNotIn('writer_executable', captures[-1])


if __name__ == '__main__':
    unittest.main()
