"""In hython, measure one SOP downstream of two external geometry inputs."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import hou


def measure(node, attribute, field):
    node.cook(force=True)
    geo = node.geometry()
    if geo is None or node.errors():
        raise RuntimeError(f'{node.path()}: {node.errors()}')
    points = geo.intrinsicValue('pointcount')
    if not points:
        raise ValueError('empty output')
    result = {'points': points, 'primitives': geo.intrinsicValue('primitivecount')}
    if field:
        prim = next(p for p in geo.prims() if p.attribValue('name') == field)
        box = prim.boundingBox()
        lo, size = box.minvec(), box.sizevec()
        positions = itertools.product(range(1, 12), repeat=3)
        values = [prim.sample(tuple(lo[j] + size[j]*i[j]/12 for j in range(3))) for i in positions]
        if not all(map(math.isfinite, values)) or not any(values):
            raise ValueError('expected a nonzero finite scalar field')
        result.update(field=field, maximum=max(values), minimum=min(values),
                      sampled_field_sha256=hashlib.sha256(repr(values).encode()).hexdigest())
    else:
        values = geo.pointFloatAttribValues(attribute)
        if not values or not all(map(math.isfinite, values)):
            raise ValueError('missing or nonfinite point attribute')
        result.update(attribute=attribute, attribute_sha256=hashlib.sha256(
            geo.pointFloatAttribValuesAsString(attribute)).hexdigest())
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('scene', type=Path, help='isolated working copy of the HIP')
    ap.add_argument('receiver', help='SOP whose input is replaced')
    ap.add_argument('sink', help='downstream SOP to measure')
    ap.add_argument('first', type=Path)
    ap.add_argument('second', type=Path)
    ap.add_argument('--slot', type=int, default=0)
    ap.add_argument('--frame', type=float, required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--point-attribute', default='P')
    mode.add_argument('--scalar-field')
    args = ap.parse_args()
    first, second = args.first.resolve(strict=True), args.second.resolve(strict=True)
    if first == second:
        ap.error('specify two distinct input files')
    hou.hipFile.load(str(args.scene.resolve(strict=True)), suppress_save_prompt=True, ignore_load_warnings=True)
    hou.setFrame(args.frame)
    receiver, sink = hou.node(args.receiver), hou.node(args.sink)
    if receiver is None or sink is None:
        raise ValueError('receiver or sink not found')
    slot = args.slot
    old = next((c for c in receiver.inputConnections() if c.inputIndex() == slot), None)
    source, port = (old.inputNode(), old.outputIndex()) if old else (None, 0)
    file_node = receiver.parent().createNode('file')
    observations = []
    try:
        receiver.setInput(slot, file_node)
        for path in (first, second, first):
            file_node.parm('file').set(str(path))
            observations.append(measure(sink, args.point_attribute, args.scalar_field))
    finally:
        receiver.setInput(slot, source, port)
        file_node.destroy()
    a, b, repeat = observations
    metric = 'sampled_field_sha256' if args.scalar_field else 'attribute_sha256'
    passed = a[metric] != b[metric] and a == repeat
    print(json.dumps({'scene': str(args.scene), 'receiver': receiver.path(), 'sink': sink.path(),
                      'frame': args.frame, 'inputs': [str(first), str(second)],
                      'measurements': observations, 'changed_and_repeatable': passed}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
