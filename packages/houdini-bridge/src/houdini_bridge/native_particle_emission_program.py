"""P01 frozen input validation and deterministic Python parameter expressions.

The host must authenticate inputs, preserve emission gates, and verify native
expression consumption and substep integration. A content digest is integrity,
not ownership or evidence that a simulation executed.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS

import hashlib
import json
import math
from pathlib import PurePosixPath


SUPPORTED_VERSIONS = ('21.0.631', '22.0.429')
BASIS_SCHEMA = 'bridge.particle-emission-basis/1'
MAX_BASIS_BYTES = 4096
MAX_TEXT_BYTES = 512
MAX_BIRTH_RATE = 10000000.
UNIFORM_DENOMINATOR = (1 << 53) - 1
BASIS_FIELDS = {
    'schema', 'native_version', 'task_id', 'task_root', 'node_path',
    'birth_rate', 'task_seed', 'birth_start_time', 'fps', 'content_sha256',
}


class ParticleEmissionError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def _fail(code, detail):
    raise ParticleEmissionError(code, detail)


def _number(value, label, *, minimum=None, maximum=None):
    if type(value) not in (int, float):
        _fail('PARTICLE_EMISSION_INVALID_NUMBER', label)
    try:
        number = float(value)
    except (OverflowError, ValueError):
        _fail('PARTICLE_EMISSION_INVALID_NUMBER', label)
    if (not math.isfinite(number) or minimum is not None and number < minimum
            or maximum is not None and number > maximum):
        _fail('PARTICLE_EMISSION_INVALID_NUMBER', label)
    return number


def _text(value, label):
    if (type(value) is not str or not value or len(value) > MAX_TEXT_BYTES
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        _fail('PARTICLE_EMISSION_INVALID_BINDING', label)
    try:
        if len(value.encode('utf-8')) > MAX_TEXT_BYTES:
            _fail('PARTICLE_EMISSION_INVALID_BINDING', label + '/UTF-8 budget')
    except UnicodeError:
        _fail('PARTICLE_EMISSION_INVALID_BINDING', label + '/UTF-8')
    return value


def _path(value, label):
    value = _text(value, label)
    if (not value.startswith('/obj/') or '\\' in value
            or str(PurePosixPath(value)) != value
            or any(part in ('', '.', '..') for part in value.split('/')[1:])):
        _fail('PARTICLE_EMISSION_INVALID_BINDING', label + '/canonical owned SOP path')
    return value


def _body(version, *, task_id, task_root, node_path, birth_rate,
          task_seed, birth_start_time, fps):
    if type(version) is not str or version not in (*SUPPORTED_VERSIONS, *PREPARATION_VERSIONS):
        _fail('UNSUPPORTED_NATIVE_VERSION', 'captured H21 or H22 build required')
    task_id = _text(task_id, 'task_id')
    task_root = _path(task_root, 'task_root')
    node_path = _path(node_path, 'node_path')
    if not node_path.startswith(task_root + '/'):
        _fail('PARTICLE_EMISSION_INVALID_BINDING', 'emission node must be inside task root')
    if type(task_seed) is not int or not 0 <= task_seed <= 2147483647:
        _fail('PARTICLE_EMISSION_INVALID_SEED', 'nonnegative int32 task seed required')
    birth_rate = _number(birth_rate, 'birth_rate', minimum=0., maximum=MAX_BIRTH_RATE)
    birth_start_time = _number(birth_start_time, 'birth_start_time')
    fps = _number(fps, 'fps', minimum=0.)
    if fps == 0.:
        _fail('PARTICLE_EMISSION_INVALID_NUMBER', 'fps must be positive')
    return dict(schema=BASIS_SCHEMA, native_version=version, task_id=task_id,
                task_root=task_root, node_path=node_path, birth_rate=birth_rate,
                task_seed=task_seed, birth_start_time=birth_start_time, fps=fps)


def _digest(body):
    serialized = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(serialized.encode('utf-8')) > MAX_BASIS_BYTES:
        _fail('PARTICLE_EMISSION_BASIS_BUDGET_EXCEEDED', 'frozen basis bytes')
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def freeze_basis(version, *, task_id, task_root, node_path, birth_rate,
                 task_seed, birth_start_time, fps):
    body = _body(version, task_id=task_id, task_root=task_root, node_path=node_path,
                 birth_rate=birth_rate, task_seed=task_seed,
                 birth_start_time=birth_start_time, fps=fps)
    return dict(body, content_sha256=_digest(body))


def validate_basis(basis, version=None):
    if (type(basis) is not dict or len(basis) != len(BASIS_FIELDS)
            or set(basis) != BASIS_FIELDS):
        _fail('PARTICLE_EMISSION_INVALID_BINDING', 'exact bounded JSON basis required')
    if basis['schema'] != BASIS_SCHEMA:
        _fail('PARTICLE_EMISSION_INVALID_BINDING', 'basis schema')
    if version is not None and (type(version) is not str or version != basis['native_version']):
        _fail('PARTICLE_EMISSION_BASIS_VERSION_CHANGED', 'native build differs')
    body = _body(basis['native_version'], **{field: basis[field] for field in (
        'task_id', 'task_root', 'node_path', 'birth_rate', 'task_seed', 'birth_start_time', 'fps')})
    digest = basis['content_sha256']
    if (type(digest) is not str or len(digest) != 64
            or any(character not in '0123456789abcdef' for character in digest)
            or digest != _digest(body)):
        _fail('PARTICLE_EMISSION_BASIS_CHANGED', 'frozen basis digest differs')
    return dict(body, content_sha256=digest)


def _targets(basis, percentage, birth_rate_override):
    basis = validate_basis(basis)
    percentage = _number(percentage, 'emission_variance', minimum=0., maximum=100.)
    base = basis['birth_rate'] if birth_rate_override is None else _number(
        birth_rate_override, 'birth_rate_override', minimum=0., maximum=MAX_BIRTH_RATE)
    fraction = percentage / 100.
    minimum = base * (1. - fraction)
    maximum = base * (1. + fraction)
    if percentage > 0. and base > 0.:
        if (fraction == 0. or base * fraction == 0. or minimum == maximum
                or minimum == base or maximum == base
                or fraction < 1. and minimum == 0.):
            _fail('PARTICLE_EMISSION_RANGE_NOT_REPRESENTABLE', 'nonzero variation collapsed')
        if math.ulp(basis['birth_start_time']) >= 1.:
            _fail('PARTICLE_EMISSION_TIME_NOT_REPRESENTABLE', 'birth-start second buckets collapsed')
    return basis, base, fraction, minimum, maximum


def validate_rate_range(basis, percentage, birth_rate_override=None, *,
                        native_minimum=None, native_maximum=None):
    """Check the full distribution against supplied actual hard limits only.

    Omitted limits remain unproven; product/UI maxima never clamp the generated
    distribution. The host is responsible for collecting native hard-limit facts.
    """
    _, _, _, minimum, maximum = _targets(basis, percentage, birth_rate_override)
    lower = None if native_minimum is None else _number(native_minimum, 'native_minimum')
    upper = None if native_maximum is None else _number(native_maximum, 'native_maximum')
    if lower is not None and upper is not None and lower > upper:
        _fail('PARTICLE_EMISSION_INVALID_NATIVE_LIMITS', 'reversed actual hard limits')
    if (lower is not None and minimum < lower or upper is not None and maximum > upper):
        _fail('PARTICLE_EMISSION_NATIVE_RANGE_EXCEEDED', 'full rate distribution exceeds hard limits')
    proven = lower is not None and upper is not None
    return dict(minimum=minimum, maximum=maximum, native_minimum=lower,
                native_maximum=upper, native_hard_limits_proven=proven,
                evidence_scope='mathematical_rate_range',
                missing_evidence=[] if proven else ['native_rate_hard_limits'])


def _bucket(time, start):
    time = _number(time, 'time')
    delta = time - start
    if (not math.isfinite(delta) or math.ulp(time) >= 1.
            or math.ulp(delta) >= 1.):
        _fail('PARTICLE_EMISSION_TIME_NOT_REPRESENTABLE', 'scene-second bucket resolution')
    return math.floor(delta)


def rate_at_time(basis, percentage, time, birth_rate_override=None):
    basis, base, fraction, _, _ = _targets(basis, percentage, birth_rate_override)
    time = _number(time, 'time')
    if fraction == 0. or base == 0.:
        return base
    bucket = _bucket(time, basis['birth_start_time'])
    payload = ('bridge.P01/1:' + str(basis['task_seed']) + ':' + str(bucket)).encode('ascii')
    sample = int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big') >> 11
    uniform = 2. * sample / UNIFORM_DENOMINATOR - 1.
    return base * (1. + fraction * uniform)


def expression(basis, percentage, birth_rate_override=None):
    """Generate owned hou.exprLanguage.Python source, without native execution."""
    basis, base, fraction, _, _ = _targets(basis, percentage, birth_rate_override)
    if fraction == 0. or base == 0.:
        return repr(base)
    return '\n'.join((
        'import hou',
        'import math',
        'import hashlib',
        'scene_time = hou.time()',
        'if type(scene_time) not in (int, float) or not math.isfinite(scene_time):',
        "    raise ValueError('PARTICLE_EMISSION_INVALID_NUMBER: time')",
        'elapsed = scene_time - ' + repr(basis['birth_start_time']),
        'if not math.isfinite(elapsed) or math.ulp(scene_time) >= 1. or math.ulp(elapsed) >= 1.:',
        "    raise ValueError('PARTICLE_EMISSION_TIME_NOT_REPRESENTABLE')",
        'bucket = math.floor(elapsed)',
        'payload = (' + repr('bridge.P01/1:' + str(basis['task_seed']) + ':')
        + " + str(bucket)).encode('ascii')",
        "sample = int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big') >> 11",
        'uniform = 2. * sample / ' + str(UNIFORM_DENOMINATOR) + ' - 1.',
        'return ' + repr(base) + ' * (1. + ' + repr(fraction) + ' * uniform)',
    ))
