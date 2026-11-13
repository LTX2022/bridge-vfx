"""Official preparation fixtures: Python only, never native acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from dcc_task_runtime import native_scope, owned_process
from dcc_task_runtime.render_profiles import LEGACY, OFFICIAL, definition, output_policy
from houdini_bridge import controlled_output, official_karma
import test_native_scope as scope_fixtures

ROOT = Path(__file__).resolve().parents[2]

def tool(name):
    spec = importlib.util.spec_from_file_location('official_test_' + name, ROOT/'tools'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OfficialBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binding = scope_fixtures.software_scope(self.root,
            schema=native_scope.OFFICIAL_SCOPE_SCHEMA,
            resource_profile=native_scope.OFFICIAL_RESOURCE_PROFILE,
            scene_profile=OFFICIAL, budget=native_scope.OFFICIAL_BUDGET)
        self.scope = native_scope.NativeScope(self.binding)

    def admit(self, role, suffix=None, parent=None):
        if parent:
            return self.scope.admit(role, parent['directory'], parent['identity'], parent=parent)
        suffix = suffix or role
        return self.scope.admit(role, self.root/suffix, {'op': suffix},
            heavy=role not in ('houdini-host', 'nuke-host'))

    def stop(self, ticket):
        scope_fixtures.NativeScopeTests.stop(self, ticket)
        self.scope.finish(ticket)

    def prefix(self):
        for role in ('official-open-save', 'official-cold-export', 'official-husk'):
            self.stop(self.admit(role))

    def test_order_idempotency_and_unknown_stop_survive_restart(self):
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_ORDER_REQUIRED'):
            self.admit('alpha-husk')
        first = self.admit('official-open-save')
        restored = native_scope.NativeScope(self.binding)
        self.assertTrue(restored.admit('official-open-save', first['directory'], first['identity'])['reused'])
        with self.assertRaisesRegex(ValueError, 'PRIOR_STOP_REQUIRED'):
            self.admit('official-cold-export')
        with self.assertRaisesRegex(ValueError, 'STOP_UNKNOWN'):
            self.scope.finish(first)
        self.assertEqual(restored.snapshot()['dcc_starts'], 1)
        self.stop(first)
        self.stop(self.admit('official-cold-export'))
        third = self.admit('official-husk')
        with self.assertRaisesRegex(ValueError, 'PRIOR_STOP_REQUIRED'):
            self.admit('houdini-host')
        self.stop(third)
        self.stop(self.admit('alpha-husk'))

    def test_all_eleven_share_one_ledger_and_twelfth_is_refused(self):
        self.prefix()
        for role in ('alpha-husk', 'alpha-nuke', 'graph-worker'):
            self.stop(self.admit(role))
        self.stop(self.admit('houdini-host', 'initial'))
        host = self.admit('houdini-host', 'reopen')
        child = self.admit('main-husk', parent=host)
        self.stop(host)
        self.scope.finish(child)
        self.stop(self.admit('nuke-host'))
        self.stop(self.admit('nuke-render'))
        state = native_scope.NativeScope(self.binding).snapshot()
        self.assertEqual(state['dcc_starts'], 11)
        self.assertEqual({t['role'] for t in state['tickets']}, set(native_scope._OFFICIAL_ROLES))
        self.assertTrue(all(t['stopped_at'] is not None for t in state['tickets']))
        with self.assertRaisesRegex(ValueError, 'STARTS_EXHAUSTED'):
            self.admit('alpha-husk', 'twelfth')
        # Restart or a new request identity cannot replenish this experiment.
        with self.assertRaisesRegex(ValueError, 'ALREADY_INITIALIZED'):
            native_scope.NativeScope.initialize(self.binding, key=self.scope._key())
        with self.assertRaises(ValueError):
            native_scope.NativeScope(dict(self.binding, sha256='0'*64))

    def test_timeout_and_exact_resource_profile_are_not_advisory(self):
        first = self.admit('official-open-save')
        with mock.patch.object(native_scope.time, 'time', return_value=first['admitted_at'] + 601):
            with self.assertRaisesRegex(ValueError, 'TIME_EXHAUSTED'):
                self.scope.check()
        self.assertEqual(self.scope.snapshot()['closed_reason'], 'NATIVE_SCOPE_TIME_EXHAUSTED')
        for updates in ({'budget': dict(native_scope.OFFICIAL_BUDGET, max_dcc_starts=12)},
                        {'scene_profile': LEGACY}, {'resource_profile': 'arbitrary'},
                        {'role_seconds': {'official-husk': 600}}):
            value = json.loads(Path(self.binding['path']).read_text())
            value.update(updates)
            path = self.root/'invalid.json'; path.write_text(json.dumps(value))
            import hashlib
            with self.assertRaises(ValueError):
                native_scope.NativeScope({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    def test_total_600_across_stopped_roles_is_not_reset_per_stage(self):
        # Only the supervisor receipt boundary is substituted; all admission,
        # signed accounting, timing and remaining-budget logic stays real.
        clock = time.time() - 700
        def stopped(ticket):
            return {'schema': owned_process.SCHEMA, 'observed_at': ticket['admitted_at'] + 120,
                'execution_protocol': 1, 'exit_code': 0, 'supervisor_exit_code': 0,
                'descendant_result_unobserved': False, 'stop_reason': None,
                'execution_result': 'succeeded'}
        with mock.patch.object(native_scope.NativeScope, '_stop', side_effect=stopped):
            for role in ('official-open-save', 'official-cold-export', 'official-husk', 'alpha-husk', 'alpha-nuke'):
                with mock.patch.object(native_scope.time, 'time', return_value=clock):
                    ticket = self.admit(role)
                with mock.patch.object(native_scope.time, 'time', return_value=clock + 120):
                    self.scope.finish(ticket)
                clock += 120
            self.assertEqual(self.scope.snapshot()['total_seconds'], 600)
            with self.assertRaisesRegex(ValueError, 'TIME_EXHAUSTED'):
                self.admit('graph-worker')
            self.assertEqual(self.scope.snapshot()['dcc_starts'], 5)


class OfficialProfileTests(unittest.TestCase):
    def test_exact_policy_cannot_mix_resolution_or_channels_between_cases(self):
        old = output_policy(LEGACY)
        new = output_policy(OFFICIAL)
        self.assertEqual(old, controlled_output._POLICY)
        self.assertEqual(controlled_output.validate_controlled_policy(new), new)
        for bad in (dict(new, resolution=[128, 128]), dict(old, resolution=[420, 300]),
                    dict(new, channels=list('RGB')), dict(new, frames=[True]), dict(new, extra=1)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                controlled_output.validate_controlled_policy(bad)
        modified = definition(OFFICIAL); modified['resolution'][0] = 1
        self.assertEqual(definition(OFFICIAL)['resolution'], [420, 300])
        with self.assertRaises(ValueError): definition('grey_sphere')

    def test_alpha_geometry_resolution_and_sample_centres_are_case_specific(self):
        prepare = tool('prepare_native_alpha_scene')
        legacy = prepare.chart_usda('/private/tmp/old.exr', 'ACEScg')
        official = prepare.chart_usda('/private/tmp/new.exr', 'ACEScg', OFFICIAL)
        self.assertIn('resolution = (128, 128)', legacy)
        self.assertIn('resolution = (420, 300)', official)
        self.assertIn('verticalAperture = 91.4286', official)
        self.assertEqual(definition(OFFICIAL)['sample_pixels'], [[70,150],[210,150],[350,150]])
        # Orthographic mapping places every sample safely inside its own patch.
        for (x, y), (left, right) in zip(definition(OFFICIAL)['sample_pixels'], [(-6.3,-3.3),(-1.5,1.5),(3.3,6.3)]):
            world_x = ((x + .5) / 420 - .5) * 12.8
            self.assertLess(left, world_x); self.assertLess(world_x, right)
            self.assertEqual(y, 150)
        with self.assertRaises(ValueError): prepare.chart_usda('/private/tmp/x.exr', 'ACEScg', 'bad')

    def test_alpha_facade_sees_eleven_without_changing_old_eight(self):
        runner = tool('run_alpha_calibration')
        old = {'schema': 'bridge.engineering-closure-scope/1'}
        new = {'schema': native_scope.OFFICIAL_SCOPE_SCHEMA, 'scene_profile': OFFICIAL}
        self.assertEqual(runner._limits(old)['max_dcc_starts'], 8)
        self.assertEqual(runner._limits(new)['max_dcc_starts'], 11)
        self.assertEqual(sum(runner._roles(new)[0].values()), 11)
        with self.assertRaises(ValueError): runner._limits(dict(old, scene_profile=OFFICIAL))


class OfficialOneStageDiagnosticBudgetTests(unittest.TestCase):
    def test_one_start_and_120_seconds_are_enforced_by_the_same_native_ledger(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root=Path(temporary).resolve()
            binding=scope_fixtures.software_scope(root,schema=native_scope.OFFICIAL_SCOPE_SCHEMA,
                resource_profile=native_scope.OFFICIAL_RESOURCE_PROFILE,scene_profile=OFFICIAL,
                execution_mode=native_scope.OFFICIAL_DIAGNOSTIC_MODE,budget=native_scope.OFFICIAL_DIAGNOSTIC_BUDGET)
            scope=native_scope.NativeScope(binding)
            for role in ('official-cold-export','official-husk','alpha-husk','graph-worker','nuke-host'):
                with self.subTest(role=role),self.assertRaises(ValueError):scope.admit(role,root/role,{'role':role})
            ticket=scope.admit('official-open-save',root/'one',{'operation':'one'})
            scope_fixtures.NativeScopeTests.stop(self,ticket);scope.finish(ticket)
            self.assertEqual(scope.snapshot()['dcc_starts'],1)
            self.assertEqual(scope.scope['budget']['total_seconds'],120)
            with self.assertRaises(ValueError):scope.admit('official-open-save',root/'two',{'operation':'two'})
            runner=tool('run_alpha_calibration')
            self.assertEqual(runner.ScopeBudget(binding['path']).limits['max_dcc_starts'],1)

    def test_mode_cannot_borrow_full_budget_or_appear_on_legacy_scope(self):
        for legacy,wrong_budget in ((False,True),(True,False)):
            with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
                fields={'execution_mode':native_scope.OFFICIAL_DIAGNOSTIC_MODE}
                if not legacy:fields.update(schema=native_scope.OFFICIAL_SCOPE_SCHEMA,
                    resource_profile=native_scope.OFFICIAL_RESOURCE_PROFILE,scene_profile=OFFICIAL,
                    budget=native_scope.OFFICIAL_BUDGET if wrong_budget else native_scope.OFFICIAL_DIAGNOSTIC_BUDGET)
                with self.assertRaises(ValueError):scope_fixtures.software_scope(Path(temporary).resolve(),**fields)


class OfficialImageComparisonTests(unittest.TestCase):
    @staticmethod
    def image():
        channels = [{'name': c, 'pixel_type': 1, 'x_sampling': 1, 'y_sampling': 1, 'p_linear': 0} for c in 'RGBA']
        return {'width': 420, 'height': 300, 'channels': list('RGBA'), 'structural_validated': True,
            'channel_layout': {'channels': channels, 'data_window': [0,0,419,299], 'display_window': [0,0,419,299]},
            'rows': [{'y': y, 'channels': {c: [.5 if c != 'A' else 1.] * 420 for c in 'RGBA'}} for y in range(300)]}

    def test_exact_nuke_equality_compares_504000_samples(self):
        image = self.image()
        result = official_karma.compare_decoded(image, image, require_identical=True)
        self.assertEqual(result['state'], 'PASS')
        self.assertEqual(result['samples_compared'], 504000)
        self.assertEqual(result['different_samples'], 0)
        self.assertEqual(len(result['tiles']), 27 * 19)
        self.assertIsNone(result['over_diagnostic_threshold_bounds'])
        candidate = copy.deepcopy(image); candidate['rows'][21]['channels']['A'][19] = .999
        result = official_karma.compare_decoded(image, candidate, require_identical=True)
        self.assertEqual(result['state'], 'FAIL')
        self.assertEqual(result['different_samples'], 1)
        self.assertEqual(result['channels']['A']['worst_pixel'], [19,21])

    def test_rgb_alpha_and_local_error_diagnostics_have_fixed_thresholds(self):
        image, candidate = self.image(), self.image()
        candidate['rows'][23]['channels']['R'][17] = 1.
        local = official_karma.compare_decoded(image, candidate)
        self.assertEqual(local['state'], 'PASS')
        self.assertEqual(local['over_diagnostic_threshold_bounds'], [17,23,17,23])
        self.assertEqual(local['channels']['R']['maximum'], .5)
        self.assertGreater(local['tiles'][28]['rgb_rms'], 0)
        for row in candidate['rows']:
            row['channels']['R'] = [1.] * 420
            row['channels']['A'] = [.99] * 420
        failed = official_karma.compare_decoded(image, candidate)
        self.assertEqual(failed['state'], 'FAIL')
        self.assertGreater(failed['rgb_nrmse'], .05)
        self.assertGreater(failed['alpha_mae'], .005)
        self.assertEqual(failed['thresholds'], official_karma.THRESHOLDS)

    def test_bad_shapes_nonfinite_or_missing_alpha_never_receive_pass(self):
        image = self.image()
        for mutate in (lambda v: v.update(width=128), lambda v: v.update(channels=list('RGB')),
                       lambda v: v['rows'][0]['channels']['A'].__setitem__(0, float('nan')),
                       lambda v: v['rows'][1].update(y=0),
                       lambda v: v['channel_layout']['channels'][0].update(pixel_type=2)):
            bad = copy.deepcopy(image); mutate(bad)
            with self.assertRaises(ValueError): official_karma.compare_decoded(image, bad)

    def test_file_entry_decodes_real_exr_bytes_and_requires_physical_color(self):
        from dcc_task_runtime.exr_codec import write_exr
        image = self.image()
        image.update(pixel_count=126000, sample_count=504000, compression=0,
                     color_metadata={'oiio:ColorSpace': 'ACEScg'})
        image['channels'] = sorted(image['channels'])
        image['channel_layout']['channels'].sort(key=lambda c: c['name'])
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            left = Path(directory).resolve()/'reference.exr'
            right = left.with_name('nuke.exr')
            write_exr(left, image, image['rows'])
            write_exr(right, image, image['rows'])
            result = official_karma.compare_files(left, right, require_identical=True)
            self.assertEqual(result['state'], 'PASS')
            self.assertEqual(result['samples_compared'], 504000)
            image['rows'][3]['channels']['R'][5] = .75
            write_exr(right, image, image['rows'])
            changed = official_karma.compare_files(left, right, require_identical=True)
            self.assertEqual(changed['state'], 'FAIL')
            self.assertEqual(changed['channels']['R']['worst_pixel'], [5,3])
            for metadata, cause in (({}, 'COLORSPACE_UNVERIFIED'),
                                    ({'oiio:ColorSpace': 'lin_rec709'}, 'COLORSPACE_CONFLICT')):
                image['color_metadata'] = metadata
                write_exr(right, image, image['rows'])
                with self.assertRaisesRegex(ValueError, cause):
                    official_karma.compare_files(left, right)
            image['color_metadata'] = {'oiio:ColorSpace': 'ACEScg'}
            image['rows'][0]['channels']['A'][0] = -.1
            write_exr(right, image, image['rows'])
            with self.assertRaisesRegex(ValueError, 'ALPHA_RANGE'):
                official_karma.compare_files(left, right)
            link = left.with_name('linked.exr'); link.symlink_to(left)
            with self.assertRaisesRegex(ValueError, 'PLAIN_ABSOLUTE'):
                official_karma.compare_files(left, link)

    def test_wrong_source_bytes_are_refused_before_archive_parsing(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_SHA256_MISMATCH'):
            official_karma.inspect_source(b'not an official hip')
