"""Data-only source and comparison contract for the shipped H21 DiskLight case.

Reading HIP archive members does not load, evaluate or execute their content.
These facts are preparation evidence, never native or visual acceptance.
"""
from __future__ import annotations
import hashlib
import math
import re
import shlex
from pathlib import Path, PurePosixPath

from dcc_task_runtime.render_profiles import OFFICIAL, SOURCE_HIP_SHA256

VERSION = '21.0.631'
FRAME = 1
RESOLUTION = [420, 300]
OUTER_TYPES = {
    'backdrop_shallow': 'sopcreate', 'camera1': 'camera',
    'karmarendersettings': 'karmarenderproperties', 'transform3': 'xform',
    'disklight': 'light::2.0', 'render_disklight': 'null', 'switch3': 'switch',
    'update_output_image_path': 'editproperties', 'OUT_karma_lights': 'usdrender_rop',
}
SOP_TYPES = {
    'grid1': 'grid', 'output0': 'output', 'null1': 'null',
    'polyextrude1': 'polyextrude::2.0', 'merge1': 'merge',
    'polyextrude2': 'polyextrude::2.0', 'reverse1': 'reverse', 'grid2': 'grid',
    'polyextrude3': 'polyextrude::2.0', 'polyextrude4': 'polyextrude::2.0',
    'reverse2': 'reverse', 'group1': 'groupcreate', 'group2': 'groupcreate',
    'grouprange1': 'grouprange', 'sort1': 'sort', 'group3': 'groupcreate',
    'sort2': 'sort', 'group4': 'groupcreate', 'group5': 'groupcreate',
    'group6': 'groupcreate', 'color1': 'color', 'color2': 'color',
}
SELECTED_TYPES = {'stage/lights/' + name: kind for name, kind in OUTER_TYPES.items()}
SELECTED_TYPES.update({'stage/lights/backdrop_shallow/sopnet/create/' + name: kind
                       for name, kind in SOP_TYPES.items()})
THRESHOLDS = {'rgb_nrmse': .05, 'alpha_mae': .005, 'alpha_p99': .05,
              'structural_absolute': 1e-6, 'tile_size': 16,
              'diagnostic_absolute': .05, 'alpha_percentile': 'nearest_rank'}
MAX_IMAGE_SAMPLES = 420 * 300 * 4


def canonical_sha256(data):
    import json
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _index(data):
    """Exact old ASCII CPIO index, without extracting any paths."""
    if type(data) is not bytes or len(data) > 64 * 1024 * 1024:
        raise ValueError('OFFICIAL_SOURCE_BYTE_LIMIT')
    result, cursor = {}, 0
    while cursor + 76 <= len(data):
        h = data[cursor:cursor + 76]
        if h[:6] != b'070707' or any(c not in b'01234567' for c in h[6:]):
            raise ValueError('OFFICIAL_SOURCE_ARCHIVE_INVALID')
        ns, size = int(h[59:65], 8), int(h[65:76], 8)
        if not 1 <= ns <= 4096 or len(result) >= 100000:
            raise ValueError('OFFICIAL_SOURCE_ARCHIVE_LIMIT')
        start, end = cursor + 76 + ns, cursor + 76 + ns + size
        name = data[cursor + 76:start]
        if end > len(data) or not name.endswith(b'\0') or b'\0' in name[:-1]:
            raise ValueError('OFFICIAL_SOURCE_ARCHIVE_INVALID')
        name = name[:-1].decode('utf-8')
        if name == 'TRAILER!!!':
            if size or end != len(data):
                raise ValueError('OFFICIAL_SOURCE_ARCHIVE_INVALID')
            return result
        path = PurePosixPath(name)
        if not name or path.is_absolute() or '..' in path.parts or '\\' in name or name in result:
            raise ValueError('OFFICIAL_SOURCE_ARCHIVE_INVALID')
        result[name] = {'offset': start, 'bytes': size,
                        'sha256': hashlib.sha256(data[start:end]).hexdigest()}
        cursor = end
    raise ValueError('OFFICIAL_SOURCE_ARCHIVE_INVALID')


def inspect_source(data):
    """Freeze the real branch inventory and unevaluated parameter/channel identities.

    Switch inputs belonging to other tutorial examples are recorded as excluded;
    only input 1 is admissible to the new reconstruction. Expressions are hashed
    and retained as source facts. No saved expression is a construction value.
    """
    if hashlib.sha256(data).hexdigest() != SOURCE_HIP_SHA256:
        raise ValueError('OFFICIAL_SOURCE_SHA256_MISMATCH')
    index = _index(data)
    def member(name):
        row = index[name]
        return data[row['offset']:row['offset'] + row['bytes']].decode('utf-8')
    nodes = {}
    for name, expected in SELECTED_TYPES.items():
        match = re.search(r'^type = ([^\r\n]+)$', member(name + '.init'), re.M)
        if not match or match[1] != expected:
            raise ValueError('OFFICIAL_SOURCE_NODE_TYPE_MISMATCH:' + name)
        definition, parameters = member(name + '.def'), member(name + '.parm')
        block = re.search(r'^inputs\s*\n\{\n(.*?)^\}', definition, re.M | re.S)
        inputs = []
        for line in block[1].splitlines() if block else []:
            tokens = shlex.split(line)
            if len(tokens) != 4 or not all(t.isdigit() for t in (tokens[0], tokens[2], tokens[3])):
                raise ValueError('OFFICIAL_SOURCE_WIRE_INVALID:' + name)
            inputs.append({'input': int(tokens[0]), 'source': tokens[1], 'output': int(tokens[2])})
        names = re.findall(r'^(\w+)\t+\[[^\n]*\]\t+\(', parameters, re.M)
        if len(names) != len(set(names)):
            raise ValueError('OFFICIAL_SOURCE_DUPLICATE_PARAMETER:' + name)
        refs = {suffix[1:]: dict(index[name + suffix], member=name + suffix)
                for suffix in ('.init', '.def', '.parm', '.chn') if name + suffix in index}
        nodes['/' + name] = {'native_type': expected, 'inputs': inputs,
            'saved_parameter_names': names, 'members': refs,
            'display': bool(re.search(r'\bdisplay on\b', definition)),
            'render': bool(re.search(r'\brender on\b', definition)),
            'has_saved_channels': name + '.chn' in index,
            'saved_channels_not_evaluated': member(name + '.chn') if name + '.chn' in index else ''}
    # Refuse missing/unmapped inputs on the selected dependency closure.
    for path, row in nodes.items():
        for wire in row['inputs']:
            if path == '/stage/lights/switch3' and wire['input'] != 1:
                continue
            source = str(PurePosixPath(path).parent / wire['source'])
            if source not in nodes:
                raise ValueError('OFFICIAL_SOURCE_UNMAPPED_INPUT:' + source)
    selected_switch = [w for w in nodes['/stage/lights/switch3']['inputs'] if w['input'] == 1]
    if selected_switch != [{'input': 1, 'source': 'render_disklight', 'output': 0}]:
        raise ValueError('OFFICIAL_SOURCE_DISKLIGHT_INPUT_MISMATCH')
    # Report executable source candidates across the HIP, including unselected chapters.
    # This is an inventory for review, not a claim that callback safety is established.
    executable_candidates = []
    for name in index:
        if re.search(r'(?i)(python|script|callback|event|\.py$|\.cmd$)', name):
            executable_candidates.append(dict(index[name], member=name))
        elif name.endswith('.def') and re.search(r'^delscript\s+(?!""\s*$).+', member(name), re.M):
            executable_candidates.append(dict(index[name], member=name))
    result = {'schema': 'bridge.official-karma-source-contract/1', 'profile': OFFICIAL,
        'source_sha256': SOURCE_HIP_SHA256, 'source_bytes': len(data), 'version': VERSION,
        'frame': FRAME, 'resolution': list(RESOLUTION), 'nodes': nodes,
        'sop_count': len(SOP_TYPES), 'selected_input': 1,
        'executable_candidates': executable_candidates,
        'native_execution_status': 'NOT_RUN', 'callback_review_status': 'REQUIRED',
        'thresholds': dict(THRESHOLDS)}
    return result


def _pixels(image):
    if (not isinstance(image, dict) or [image.get('width'), image.get('height')] != RESOLUTION
            or set(image.get('channels', [])) != set('RGBA')
            or len(image.get('channels', [])) != 4 or image.get('structural_validated') is not True):
        raise ValueError('OFFICIAL_IMAGE_FORMAT_MISMATCH')
    layout = image.get('channel_layout') or {}
    window = [0, 0, 419, 299]
    if (layout.get('data_window') != window or layout.get('display_window') != window
            or len(layout.get('channels', [])) != 4
            or {c.get('name') for c in layout.get('channels', [])} != set('RGBA')
            or any(c.get('pixel_type') != 1 or c.get('x_sampling') != 1 or c.get('y_sampling') != 1
                   for c in layout.get('channels', []))):
        raise ValueError('OFFICIAL_IMAGE_LAYOUT_MISMATCH')
    rows = image.get('rows')
    if not isinstance(rows, list) or len(rows) != 300:
        raise ValueError('OFFICIAL_IMAGE_PIXELS_REQUIRED')
    by_y = {}
    for row in rows:
        y = row.get('y')
        channels = row.get('channels')
        if type(y) is not int or not 0 <= y < 300 or y in by_y or not isinstance(channels, dict) or set(channels) != set('RGBA'):
            raise ValueError('OFFICIAL_IMAGE_PIXELS_INVALID')
        if any(type(values) is not list or len(values) != 420
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in values)
                for values in channels.values()):
            raise ValueError('OFFICIAL_IMAGE_PIXELS_INVALID')
        if any(not 0 <= v <= 1 for v in channels['A']):
            raise ValueError('OFFICIAL_IMAGE_ALPHA_RANGE_INVALID')
        by_y[y] = channels
    return by_y


def compare_decoded(reference, candidate, *, require_identical=False):
    """Fixed linear RGBA thresholds and local diagnostics; no tolerance arguments."""
    if type(require_identical) is not bool:
        raise ValueError('OFFICIAL_COMPARISON_MODE_INVALID')
    left, right = _pixels(reference), _pixels(candidate)
    count = 420 * 300
    stats = {c: {'maximum': 0., 'absolute_sum': 0., 'squared_sum': 0., 'worst_pixel': [0, 0]}
             for c in 'RGBA'}
    tiles, alpha, reference_rgb_sq, bbox, different = {}, [], 0., None, 0
    for y in range(300):
        for x in range(420):
            tile = tiles.setdefault((x // 16, y // 16), {'rgb_squared_sum': 0., 'alpha_absolute_sum': 0., 'pixels': 0})
            tile['pixels'] += 1
            exceeded = False
            for c in 'RGBA':
                a, b = left[y][c][x], right[y][c][x]
                d = abs(b - a)
                if not math.isfinite(d) or not math.isfinite(d * d):
                    raise ValueError('OFFICIAL_COMPARISON_NUMERIC_OVERFLOW')
                different += int(a != b)
                stat = stats[c]
                stat['absolute_sum'] += d
                stat['squared_sum'] += d * d
                if d > stat['maximum']:
                    stat['maximum'], stat['worst_pixel'] = d, [x, y]
                exceeded |= d > THRESHOLDS['diagnostic_absolute']
                if c == 'A':
                    alpha.append(d)
                    tile['alpha_absolute_sum'] += d
                else:
                    reference_rgb_sq += a * a
                    tile['rgb_squared_sum'] += d * d
            if exceeded:
                bbox = [x, y, x, y] if bbox is None else [min(bbox[0], x), min(bbox[1], y), max(bbox[2], x), max(bbox[3], y)]
    for stat in stats.values():
        stat['mean_absolute'] = stat.pop('absolute_sum') / count
        stat['rms'] = math.sqrt(stat.pop('squared_sum') / count)
    rgb_rms = math.sqrt(sum(stats[c]['rms'] ** 2 for c in 'RGB') / 3)
    reference_rms = math.sqrt(reference_rgb_sq / (count * 3))
    if not math.isfinite(reference_rms):
        raise ValueError('OFFICIAL_COMPARISON_NUMERIC_OVERFLOW')
    if not math.isfinite(rgb_rms) or any(not math.isfinite(v) for row in stats.values()
                                         for v in (row['maximum'], row['mean_absolute'], row['rms'])):
        raise ValueError('OFFICIAL_COMPARISON_NUMERIC_OVERFLOW')
    nrmse = rgb_rms / max(reference_rms, 1e-6)
    alpha.sort()
    p99 = alpha[math.ceil(.99 * count) - 1]
    passed = (nrmse <= THRESHOLDS['rgb_nrmse'] and stats['A']['mean_absolute'] <= THRESHOLDS['alpha_mae']
              and p99 <= THRESHOLDS['alpha_p99'] and (not require_identical or different == 0))
    tile_result = []
    for (tx, ty), row in sorted(tiles.items(), key=lambda item: (item[0][1], item[0][0])):
        n = row['pixels']
        tile_result.append({'bounds': [tx * 16, ty * 16, min(419, tx * 16 + 15), min(299, ty * 16 + 15)],
            'pixels': n, 'rgb_rms': math.sqrt(row['rgb_squared_sum'] / (3 * n)),
            'alpha_mae': row['alpha_absolute_sum'] / n})
    return {'schema': 'bridge.official-karma-image-comparison/1', 'profile': OFFICIAL,
        'state': 'PASS' if passed else 'FAIL', 'resolution': list(RESOLUTION),
        'samples_compared': MAX_IMAGE_SAMPLES, 'require_identical': require_identical,
        'different_samples': different, 'rgb_nrmse': nrmse, 'reference_rgb_rms': reference_rms,
        'alpha_mae': stats['A']['mean_absolute'], 'alpha_p99': p99, 'channels': stats,
        'tiles': tile_result, 'over_diagnostic_threshold_bounds': bbox, 'thresholds': dict(THRESHOLDS),
        'human_visual_review': 'PENDING'}


def compare_files(reference, candidate, *, require_identical=False):
    from .controlled_output import _validate_exr_color
    from dcc_task_runtime.exr_codec import read_exr
    import tempfile
    import os
    import stat
    def capture(raw):
        path = Path(raw)
        if (not path.is_absolute() or path != path.resolve()
                or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()):
            raise ValueError('OFFICIAL_IMAGE_PLAIN_ABSOLUTE_REQUIRED')
        before = path.stat()
        limit = 16 * 1024 * 1024
        if not 0 < before.st_size <= limit or before.st_nlink != 1:
            raise ValueError('OFFICIAL_IMAGE_BYTE_LIMIT')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            opened = os.fstat(descriptor)
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if not stat.S_ISREG(opened.st_mode) or any(getattr(before, k) != getattr(opened, k) for k in fields):
                raise ValueError('OFFICIAL_IMAGE_CHANGED_DURING_READ')
            digest, size, blocks = hashlib.sha256(), 0, []
            while True:
                chunk = os.read(descriptor, min(65536, limit - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValueError('OFFICIAL_IMAGE_BYTE_LIMIT')
                digest.update(chunk)
                blocks.append(chunk)
            if size != before.st_size or any(getattr(before, k) != getattr(os.fstat(descriptor), k) for k in fields):
                raise ValueError('OFFICIAL_IMAGE_CHANGED_DURING_READ')
        finally:
            os.close(descriptor)
        identity = {'path': str(path), 'bytes': size, 'sha256': digest.hexdigest()}
        with tempfile.TemporaryDirectory(prefix='official-image-snapshot-') as directory:
            snapshot = Path(directory)/'image.exr'
            snapshot.write_bytes(b''.join(blocks))
            image = read_exr(snapshot)
        if (any(p.is_symlink() for p in (path, *path.parents))
                or any(getattr(before, k) != getattr(path.stat(), k) for k in fields)):
            raise ValueError('OFFICIAL_IMAGE_CHANGED_DURING_READ')
        _validate_exr_color(image, 'ACEScg')
        return identity, image
    left_record, left = capture(reference)
    right_record, right = capture(candidate)
    return dict(compare_decoded(left, right, require_identical=require_identical),
                reference=left_record, candidate=right_record)
