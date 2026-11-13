from __future__ import annotations

import copy
import hashlib
import json
import math
import textwrap
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from houdini_bridge import native_particle_emission_program as program


def basis(version='21.0.631', **overrides):
    values = dict(task_id='task-中文', task_root='/obj/task', node_path='/obj/task/emission',
                  birth_rate=1200., task_seed=173, birth_start_time=-.25, fps=24.)
    values.update(overrides)
    return program.freeze_basis(version, **values)


class NativeTimeExpression:
    def __init__(self, source):
        self.current_time = 0.
        self.clock_reads = 0
        self.namespace = {'hou': SimpleNamespace(time=self.time)}
        if '\n' in source:
            exec('def evaluate():\n' + textwrap.indent(source, '    '), self.namespace)
            self.evaluate = self.namespace['evaluate']
        else:
            self.evaluate = lambda: eval(source, self.namespace)

    def time(self):
        self.clock_reads += 1
        return self.current_time

    def sample(self, time):
        self.current_time = time
        with patch.dict(sys.modules, {'hou': self.namespace['hou']}):
            return self.evaluate()


class ParticleEmissionProgramTests(unittest.TestCase):
    def assert_code(self, code, callback, *args, **kwargs):
        with self.assertRaises(program.ParticleEmissionError) as caught:
            callback(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_basis_is_bounded_json_integrity_and_returns_independent_copy(self):
        for version in program.SUPPORTED_VERSIONS:
            frozen = basis(version)
            serialized = json.dumps(frozen, ensure_ascii=False).encode('utf-8')
            self.assertLess(len(serialized), program.MAX_BASIS_BYTES)
            self.assertEqual(program.validate_basis(json.loads(serialized), version), frozen)
            observed = program.validate_basis(frozen)
            observed['birth_rate'] = 0.
            self.assertEqual(frozen['birth_rate'], 1200.)
            body = {key: value for key, value in frozen.items() if key != 'content_sha256'}
            digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                              allow_nan=False).encode('utf-8')).hexdigest()
            self.assertEqual(frozen['content_sha256'], digest)

    def test_basis_tampering_extra_fields_and_native_build_changes_reject(self):
        frozen = basis()
        for field, value in (('birth_rate', 3.), ('task_seed', 2), ('task_id', 'other'),
                             ('birth_start_time', 0.), ('fps', 30.)):
            changed = dict(frozen, **{field: value})
            self.assert_code('PARTICLE_EMISSION_BASIS_CHANGED', program.validate_basis, changed)
        self.assert_code('PARTICLE_EMISSION_INVALID_BINDING', program.validate_basis,
                         dict(frozen, origin='runtime_hom'))
        self.assert_code('PARTICLE_EMISSION_BASIS_VERSION_CHANGED', program.validate_basis,
                         frozen, '22.0.429')
        self.assert_code('UNSUPPORTED_NATIVE_VERSION', basis, '20.5')

    def test_owned_paths_and_text_budgets_are_required(self):
        for path in ('/obj/task/../foreign', '/obj/task//emission', '/obj/task/emission/',
                     '/obj/task2/emission', '/obj/task', 'C:\\task', '/obj/task/./emission'):
            with self.subTest(path=path):
                self.assert_code('PARTICLE_EMISSION_INVALID_BINDING', basis, node_path=path)
        for text in ('', 'x\n', 'x' * 513, '汉' * 180, '\ud800'):
            self.assert_code('PARTICLE_EMISSION_INVALID_BINDING', basis, task_id=text)

    def test_numeric_inputs_refuse_boolean_nonfinite_and_invalid_ranges(self):
        for field, values in (
            ('birth_rate', [True, -1., 10000001., float('nan'), float('inf'), 10 ** 400]),
            ('birth_start_time', [True, float('nan'), float('-inf')]),
            ('fps', [0., -24., True, float('inf')]),
        ):
            for value in values:
                with self.subTest(field=field, value=str(value)):
                    self.assert_code('PARTICLE_EMISSION_INVALID_NUMBER', basis, **{field: value})
        for seed in (-1, 2147483648, 1., True, '1'):
            self.assert_code('PARTICLE_EMISSION_INVALID_SEED', basis, task_seed=seed)
        for percentage in (-1., 100.1, True, '2', float('nan')):
            self.assert_code('PARTICLE_EMISSION_INVALID_NUMBER', program.expression, basis(), percentage)

    def test_second_buckets_use_birth_start_and_do_not_resample_substeps(self):
        for version in program.SUPPORTED_VERSIONS:
            frozen = basis(version)
            native = NativeTimeExpression(program.expression(frozen, 80.))
            observed = [native.sample(time) for time in (-.25, -.2, 0., .2, .749)]
            self.assertEqual(len(set(observed)), 1)
            self.assertNotEqual(observed[0], native.sample(.75))
            self.assertNotEqual(observed[0], native.sample(math.nextafter(-.25, -math.inf)))
            self.assertEqual(native.clock_reads, 7)
            self.assertEqual(native.sample(1.749), native.sample(.75))
            self.assertNotEqual(native.sample(1.75), native.sample(.75))

    def test_native_time_expression_matches_oracle_across_negative_zero_positive_time(self):
        for version in program.SUPPORTED_VERSIONS:
            for seed in (0, 173, 2147483647):
                frozen = basis(version, task_seed=seed)
                for percentage in (0., .001, 30., 100.):
                    native = NativeTimeExpression(program.expression(frozen, percentage))
                    for time in (-100.25, -1.25, -.25, 0., .75, 1.25, 50.75):
                        self.assertEqual(native.sample(time), program.rate_at_time(frozen, percentage, time))
                        self.assertGreaterEqual(native.sample(time), 0.)

    def test_stability_recreation_versions_and_fps_do_not_change_second_samples(self):
        first = basis()
        second = basis('22.0.429', fps=120.)
        source = program.expression(first, 50.)
        self.assertEqual(source, program.expression(second, 50.))
        for time in (-2., 0., 1., 3.):
            self.assertEqual(NativeTimeExpression(source).sample(time),
                             NativeTimeExpression(program.expression(json.loads(json.dumps(first)), 50.)).sample(time))
        self.assertNotEqual(program.rate_at_time(first, 50., 0.),
                            program.rate_at_time(basis(task_seed=174), 50., 0.))

    def test_percentage_and_rate_override_preserve_underlying_seed_sample(self):
        frozen = basis()
        for time in (-2., 0., 2.):
            rate = program.rate_at_time(frozen, 100., time)
            self.assertAlmostEqual(program.rate_at_time(frozen, 50., time), (rate + 1200.) / 2.)
            self.assertAlmostEqual(program.rate_at_time(frozen, 100., time, 2400.), rate * 2.)
            native = NativeTimeExpression(program.expression(frozen, 50., 2400.))
            self.assertEqual(native.sample(time), program.rate_at_time(frozen, 50., time, 2400.))
        self.assertEqual(frozen['birth_rate'], 1200.)

    def test_zero_variance_and_zero_birth_rate_are_constant_without_native_clock_reads(self):
        for frozen, percentage, override, expected in (
            (basis(), 0., None, 1200.), (basis(), 0., 4321., 4321.),
            (basis(birth_rate=0.), 100., None, 0.), (basis(), 100., 0., 0.),
        ):
            native = NativeTimeExpression(program.expression(frozen, percentage, override))
            self.assertEqual(native.sample(float('nan')), expected)
            self.assertEqual(native.clock_reads, 0)
            self.assertEqual(program.rate_at_time(frozen, percentage, 0., override), expected)

    def test_full_distribution_is_not_clamped_to_product_rate_maximum(self):
        frozen = basis(birth_rate=10000000.)
        fact = program.validate_rate_range(frozen, 100.)
        self.assertEqual((fact['minimum'], fact['maximum']), (0., 20000000.))
        self.assertFalse(fact['native_hard_limits_proven'])
        self.assertEqual(fact['missing_evidence'], ['native_rate_hard_limits'])
        native = NativeTimeExpression(program.expression(frozen, 100.))
        rates = [native.sample(index + frozen['birth_start_time']) for index in range(100)]
        self.assertGreater(max(rates), 10000000.)
        self.assertLessEqual(max(rates), 20000000.)

    def test_actual_hard_limits_cover_both_distribution_endpoints(self):
        frozen = basis()
        proven = program.validate_rate_range(frozen, 100., native_minimum=0., native_maximum=2400.)
        self.assertTrue(proven['native_hard_limits_proven'])
        self.assertEqual(proven['missing_evidence'], [])
        for limits in ({'native_minimum': 1.}, {'native_maximum': 2399.}):
            self.assert_code('PARTICLE_EMISSION_NATIVE_RANGE_EXCEEDED', program.validate_rate_range,
                             frozen, 100., **limits)
        self.assert_code('PARTICLE_EMISSION_INVALID_NATIVE_LIMITS', program.validate_rate_range,
                         frozen, 50., native_minimum=2., native_maximum=1.)
        self.assertFalse(program.validate_rate_range(frozen, 10., native_minimum=0.)['native_hard_limits_proven'])

    def test_nonzero_variation_that_collapses_is_rejected(self):
        for frozen, percentage in ((basis(), 5e-324), (basis(), 1e-14),
                                   (basis(birth_rate=5e-324), 50.)):
            self.assert_code('PARTICLE_EMISSION_RANGE_NOT_REPRESENTABLE',
                             program.expression, frozen, percentage)
        self.assertEqual(program.expression(basis(birth_rate=0.), 5e-324), '0.0')

    def test_unrepresentable_second_buckets_and_invalid_native_time_refuse(self):
        self.assert_code('PARTICLE_EMISSION_TIME_NOT_REPRESENTABLE', program.expression,
                         basis(birth_start_time=1e100), 50.)
        frozen = basis()
        native = NativeTimeExpression(program.expression(frozen, 50.))
        for time in (1e100, -1e100):
            self.assert_code('PARTICLE_EMISSION_TIME_NOT_REPRESENTABLE',
                             program.rate_at_time, frozen, 50., time)
            with self.assertRaisesRegex(ValueError, 'PARTICLE_EMISSION_TIME_NOT_REPRESENTABLE'):
                native.sample(time)
        for time in (True, float('nan'), float('inf'), '1'):
            self.assert_code('PARTICLE_EMISSION_INVALID_NUMBER', program.rate_at_time, frozen, 50., time)
            with self.assertRaisesRegex(ValueError, 'PARTICLE_EMISSION_INVALID_NUMBER'):
                native.sample(time)

    def test_generated_source_never_calls_host_writers_or_reads_request_geometry(self):
        source = program.expression(basis(), 50.)
        self.assertEqual(source.count('hou.'), 1)
        self.assertIn('hou.time()', source)
        self.assertNotIn('random.', source)
        self.assertNotIn('geometry', source)
        self.assertNotIn('task-中文', source)
        self.assertNotIn('/obj/task', source)
        self.assertEqual(program.validate_basis(copy.deepcopy(basis())), basis())


if __name__ == '__main__':
    unittest.main()
