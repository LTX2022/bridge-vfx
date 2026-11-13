"""有界桌体学习案例的实际几何评估；不以节点命名或保存成功替代尺寸。"""
from __future__ import annotations

from dcc_task_runtime.canonical import canonical_sha256
from .geometry_evaluation import _verified_components, _extent, _center, _number

SCHEMA = 'bridge.table-geometry-test-criteria/1'


def validate_criteria(criteria):
    initial = criteria.get('initial')
    feedback = criteria.get('feedback')
    names = {'width', 'depth', 'height', 'top_thickness', 'leg_width', 'leg_depth', 'inset_x', 'inset_z'}
    if (criteria.get('schema') != SCHEMA or not isinstance(initial, dict) or set(initial) != names
            or any(not _number(v) or v <= 0 for v in initial.values())
            or not _number(criteria.get('relative_tolerance')) or not 0 < criteria['relative_tolerance'] < .1
            or not _number(criteria.get('absolute_tolerance')) or not 0 < criteria['absolute_tolerance'] < .01
            or not isinstance(feedback, dict)
            or set(feedback) != {'width_ratio', 'ratio_absolute_tolerance', 'preserve_absolute_tolerance'}
            or any(not _number(v) or v <= 0 for v in feedback.values()) or feedback['width_ratio'] <= 1
            or feedback['ratio_absolute_tolerance'] >= .1 or feedback['preserve_absolute_tolerance'] >= .01
            or initial['top_thickness'] >= initial['height']
            or 2 * (initial['inset_x'] + initial['leg_width']) >= initial['width']
            or 2 * (initial['inset_z'] + initial['leg_depth']) >= initial['depth']):
        raise ValueError('TABLE_EVALUATION_CRITERIA_INVALID')
    return initial, feedback


def measure(observation):
    points, faces, parts, bounds, digest = _verified_components(observation)
    if len(parts) != 5:
        raise ValueError('TABLE_EVALUATION_FIVE_COMPONENTS_REQUIRED')
    for part in parts:
        lo, hi = part['bounds']['minimum'], part['bounds']['maximum']
        indices = set(part['point_indices'])
        corners = {(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])}
        if (part['point_count'] != 8 or part['primitive_count'] != 6 or len(corners) != 8
                or {tuple(points[i]) for i in indices} != corners):
            raise ValueError('TABLE_EVALUATION_AXIS_ALIGNED_BOXES_REQUIRED')
        planes = []
        for face in faces:
            if face[0] not in indices:
                continue
            fixed = [(axis, points[face[0]][axis]) for axis in range(3)
                     if all(points[i][axis] == points[face[0]][axis] for i in face)]
            if len(face) != 4 or len(fixed) != 1:
                raise ValueError('TABLE_EVALUATION_BOX_FACES_REQUIRED')
            planes.extend(fixed)
        if len(set(planes)) != 6:
            raise ValueError('TABLE_EVALUATION_BOX_FACES_REQUIRED')
    ordered = sorted(parts, key=lambda p: p['bounds']['maximum'][1])
    top, legs = ordered[-1], ordered[:-1]
    tb = top['bounds']; size = _extent(tb); center = _center(tb)
    tolerance = max(1e-4, 1e-3 * max(_extent(bounds)))
    legs.sort(key=lambda p: (_center(p['bounds'])[0], _center(p['bounds'])[2]))
    spans = [_extent(p['bounds']) for p in legs]
    centers = [_center(p['bounds']) for p in legs]
    insets_x = [min(p['bounds']['minimum'][0] - tb['minimum'][0],
                    tb['maximum'][0] - p['bounds']['maximum'][0]) for p in legs]
    insets_z = [min(p['bounds']['minimum'][2] - tb['minimum'][2],
                    tb['maximum'][2] - p['bounds']['maximum'][2]) for p in legs]
    quadrants = {(1 if c[0] > center[0] else -1, 1 if c[2] > center[2] else -1) for c in centers}
    checks = {
        'five_closed_box_components': True,
        'horizontal_top': size[1] < min(size[0], size[2]),
        'upright_legs': all(s[1] > max(s[0], s[2]) for s in spans),
        'legs_grounded': all(abs(p['bounds']['minimum'][1]) <= tolerance for p in legs),
        'top_leg_contact': all(abs(p['bounds']['maximum'][1] - tb['minimum'][1]) <= tolerance for p in legs),
        'legs_under_top': all(v > tolerance for v in insets_x + insets_z),
        'four_corner_supports': len(quadrants) == 4,
        'centered': abs(center[0]) <= tolerance and abs(center[2]) <= tolerance,
        'symmetric_supports': all(max(v) - min(v) <= tolerance for v in (
            [abs(c[0] - center[0]) for c in centers], [abs(c[2] - center[2]) for c in centers],
            *[[s[a] for s in spans] for a in range(3)])),
    }
    return {'schema': 'bridge.table-geometry-measurement/1', 'geometry_sha256': digest,
            'width': size[0], 'depth': size[2], 'height': tb['maximum'][1], 'top_thickness': size[1],
            'leg_width': [s[0] for s in spans], 'leg_depth': [s[2] for s in spans],
            'leg_height': [s[1] for s in spans], 'inset_x': insets_x, 'inset_z': insets_z,
            'structural_checks': checks}


def evaluate(observation, criteria, before=None):
    initial, feedback = validate_criteria(criteria)
    base = {'layer': 'case_table_geometry' if before is None else 'case_table_geometry_feedback',
            'criteria_sha256': canonical_sha256(criteria), 'human_visual_acceptance': 'PENDING'}
    try:
        after = measure(observation)
        previous = measure(before) if before is not None else None
    except ValueError as error:
        return {**base, 'state': 'FAIL', 'error_code': str(error)}
    checks = dict(after['structural_checks'])
    if previous is None:
        for name, target in initial.items():
            values = after[name] if isinstance(after[name], list) else [after[name]]
            tolerance = max(criteria['absolute_tolerance'], abs(target) * criteria['relative_tolerance'])
            checks['initial_' + name] = all(abs(v - target) <= tolerance for v in values)
        details = {'measurements': after}
    else:
        ratio = after['width'] / previous['width']
        checks.update(before_structure=all(previous['structural_checks'].values()),
                      before_initial_target=evaluate(before, criteria)['state'] == 'PASS',
                      actual_geometry_changed=after['geometry_sha256'] != previous['geometry_sha256'],
                      width_ratio=abs(ratio - feedback['width_ratio']) <= feedback['ratio_absolute_tolerance'])
        for name in ('depth', 'height', 'top_thickness', 'leg_width', 'leg_depth', 'leg_height', 'inset_x', 'inset_z'):
            old = previous[name] if isinstance(previous[name], list) else [previous[name]]
            new = after[name] if isinstance(after[name], list) else [after[name]]
            checks['preserved_' + name] = len(old) == len(new) and all(
                abs(a - b) <= feedback['preserve_absolute_tolerance'] for a, b in zip(old, new))
        details = {'before': previous, 'after': after, 'width_ratio': ratio}
    return {**base, **details, 'checks': checks, 'state': 'PASS' if all(checks.values()) else 'FAIL'}
