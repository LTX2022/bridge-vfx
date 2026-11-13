"""Fixed Houdini worker for the independently reviewed Capybara shot."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

VERSION = '21.0.631'
TRIGGER = 48
SAMPLES = (24, 47, 48, 50, 60)
TET_CAP = 50000

# This source is embedded in the saved Python SOP, so the HIP does not need
# the operator worker or its original absolute path to recook.
CUT_SOP = r'''
import collections
import re
import hou

node = hou.pwd()
target = node.geometry()
solid, rest, skeleton = [node.inputGeometry(i) for i in range(3)]
target.clear()
bounds = rest.boundingBox()
lo, hi = bounds.minvec(), bounds.maxvec()
height = hi[1]-lo[1]
cx, cz = (lo[0]+hi[0])/2, (lo[2]+hi[2])/2
assert height > 0, "invalid character bounds"
left = [(p.attribValue("name"), p.position()[0]) for p in skeleton.points()
        if re.search(r"left|(?:^|[_:.])l(?:$|[_:.])|^l[A-Z]", p.attribValue("name"), re.I)
        and abs(p.position()[0]-cx) > .04*height]
assert left, "no named left joint outside the centreline"
positive = sum(x > cx for _,x in left)
assert positive != len(left)/2, "left joint evidence is ambiguous"
side = 1 if positive > len(left)/2 else -1
positions = [p.position() for p in solid.points()]
tets = [tuple(v.point().number() for v in p.vertices()) for p in solid.prims()
        if p.type() == hou.primType.Tetrahedron]
assert 20 <= len(tets) <= 50000, "tetrahedra outside fixed count: " + str(len(tets))
owner = {}

def find(i):
    while owner[i] != i:
        owner[i] = owner[owner[i]]
        i = owner[i]
    return i

for tet in tets:
    for i in tet:
        owner.setdefault(i,i)
    for i in tet[1:]:
        owner[find(i)] = find(tet[0])
clusters = collections.Counter(find(t[0]) for t in tets)
largest = clusters.most_common(1)[0][0]
tets = [tet for tet in tets if find(tet[0]) == largest]

settings = ((.115,.135,.175), (.095,.155,.200), (.128,.150,.210))
min_x, radius_y, radius_z = settings[int(node.parent().userData("shot_tuning"))]
parts = []
for tet in tets:
    x,y,z = [sum(positions[i][axis] for i in tet)/4 for axis in range(3)]
    in_piece = (side*(x-cx)/height > min_x and abs((y-lo[1])/height-.55) < radius_y
                and abs(z-cz)/height < radius_z)
    parts.append(int(in_piece))
assert 5 <= sum(parts) < len(parts)*.24, "left waist subset outside fixed size"
body = set(i for tet,part in zip(tets,parts) if part==0 for i in tet)
piece = set(i for tet,part in zip(tets,parts) if part==1 for i in tet)
pairs = sorted(body & piece)
assert len(pairs) >= 4, "no shared waist seam"
point_attrs = {n: target.addAttrib(hou.attribType.Point,n,0) for n in ('id','shot_origin','shot_piece')}
prim_piece = target.addAttrib(hou.attribType.Prim,'shot_piece',0)
prim_name = target.addAttrib(hou.attribType.Prim,'name','')
body_group = target.createPointGroup('body')
seam_groups = [target.createPointGroup('seam_body'), target.createPointGroup('seam_piece')]
points = {}
for part, ids in enumerate((body,piece)):
    for i in sorted(ids):
        p = target.createPoint()
        p.setPosition(positions[i])
        p.setAttribValue(point_attrs['id'],2*i+part)
        p.setAttribValue(point_attrs['shot_origin'],i)
        p.setAttribValue(point_attrs['shot_piece'],part)
        points[part,i] = p
        if part == 0:
            body_group.add(p)
        if i in body and i in piece:
            seam_groups[part].add(p)
for tet,part in zip(tets,parts):
    prim = target.createTetrahedronInPlace(*(points[part,i] for i in tet))
    prim.setAttribValue(prim_piece,part)
    prim.setAttribValue(prim_name,'left_waist' if part else 'body')
target.addAttrib(hou.attribType.Global,'shot_height',height)
target.addAttrib(hou.attribType.Global,'shot_left',side)
target.addAttrib(hou.attribType.Global,'shot_left_joints',','.join(n for n,x in left))
target.setGlobalAttribValue('shot_height',height)
target.setGlobalAttribValue('shot_left',side)
target.setGlobalAttribValue('shot_left_joints',','.join(n for n,x in left))
'''

VELOCITY_SOP = r'''
import hou
node = hou.pwd()
geo = node.geometry()
prev = node.inputGeometry(1)
p0 = {p.attribValue("id"):p.position() for p in prev.points()}
h = geo.attribValue("shot_height")
side = geo.attribValue("shot_left")
v = geo.findPointAttrib("v") or geo.addAttrib(hou.attribType.Point,"v",(0.0,0.0,0.0))
for p in geo.points():
    velocity = (p.position()-p0[p.attribValue("id")])*24
    if p.attribValue("shot_piece") == 1 and abs(hou.frame()-48) < .001:
        velocity += hou.Vector3((side*4.2*h,.8*h,.38*h))
    p.setAttribValue(v,tuple(velocity))
'''

SURFACE_SOP = r'''
import hou
node = hou.pwd()
tet = node.inputGeometry(0)
out = node.geometry()
out.clear()
faces = {}
for prim in tet.prims():
    if prim.type() != hou.primType.Tetrahedron: continue
    v = [x.point() for x in prim.vertices()]
    piece = prim.attribValue("shot_piece")
    for a,b,c,d in ((0,1,2,3),(0,3,1,2),(0,2,3,1),(1,3,2,0)):
        ids = tuple(sorted((v[a].number(),v[b].number(),v[c].number())))
        if ids in faces:
            faces[ids] = None
        else:
            pa,pb,pc,pd = [v[i].position() for i in (a,b,c,d)]
            if (pb-pa).cross(pc-pa).dot(pd-pa) > 0:
                b,c = c,b
            faces[ids] = ([v[i] for i in (a,b,c)],piece)
points = {}
out_id = out.addAttrib(hou.attribType.Point,"id",0)
out_piece = out.addAttrib(hou.attribType.Prim,"shot_piece",0)
color = out.addAttrib(hou.attribType.Prim,"Cd",(0.,0.,0.))
for face in faces.values():
    if face is None: continue
    vertices, piece = face
    poly = out.createPolygon()
    for v in vertices:
        idx = v.number()
        if idx not in points:
            p = out.createPoint()
            p.setPosition(v.position())
            p.setAttribValue(out_id,v.attribValue("id"))
            points[idx] = p
        poly.addVertex(points[idx])
    poly.setAttribValue(out_piece,piece)
    poly.setAttribValue(color,(.31,.19,.12) if piece==0 else (.43,.25,.15))
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'SHOT_PLAIN_PATH_REQUIRED')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def checked(file):
    require(record(file['path']) == file, 'SHOT_SOURCE_DIGEST_CHANGED')
    return Path(file['path'])


def dump(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)


def read(path):
    return json.loads(Path(path).read_bytes())


def geometry(node, output=0):
    value = node.geometry(output)
    require(value is not None and not node.errors(),
            'SHOT_COOK_FAILED:' + node.path() + ':' + '; '.join(node.errors()))
    return value


def node(parent, typename, name, inputs=()):
    value = parent.createNode(typename, name, exact_type_name=True)
    require(value.type().name() == typename, 'SHOT_OPERATOR_IDENTITY_MISMATCH')
    for index, source in enumerate(inputs):
        if isinstance(source, tuple):
            value.setInput(index, source[0], source[1])
        elif source is not None:
            value.setInput(index, source)
    return value


def parm(value, name):
    p = value.parm(name)
    require(p is not None, 'SHOT_PARAMETER_UNAVAILABLE:' + value.type().name() + ':' + name)
    return p


def set_values(value, **parameters):
    for name, setting in parameters.items():
        p = parm(value, name)
        template = p.parmTemplate()
        items = template.menuItems() if hasattr(template,'menuItems') else ()
        if isinstance(setting, str) and items:
            require(setting in items, 'SHOT_PARAMETER_MENU_MISMATCH:' + name + ':' + setting)
            if type(template).__name__ == 'MenuParmTemplate' and not template.menuUseToken():
                setting = items.index(setting)
        p.set(setting)
    return value


def python_sop(parent, name, inputs, source):
    return set_values(node(parent, 'python', name, inputs), python=source)


def find_type(hou, name):
    names = hou.sopNodeTypeCategory().nodeTypes()
    if name in names:
        return name
    matches = sorted(n for n in names if n.startswith(name+'::') and not n.rsplit('::',1)[-1].isalpha())
    require(len(matches) == 1, 'SHOT_NATIVE_TYPE_UNAVAILABLE:' + name + ':' + ','.join(matches))
    return matches[0]


def available(hou, root):
    names = ('testgeometry_capybara','kinefx::jointdeform','pointdeform','tetconform',
             'vellumconstraints','vellumsolver','python','switch','null','file')
    types = {name: find_type(hou, name) for name in names}
    dump(root/'native-node-types.json', {'version': hou.applicationVersionString(), 'operators': types})
    return types


def points_by_id(geo):
    ids = {}
    for p in geo.points():
        key = p.attribValue('id')
        require(key not in ids, 'SHOT_POINT_ID_DUPLICATED')
        ids[key] = p
    return ids


def positions(geo):
    return {key: tuple(p.position()) for key, p in points_by_id(geo).items()}


def distance(p, q):
    return math.sqrt(sum((a-b)**2 for a,b in zip(p,q)))


def median(values):
    data = sorted(values)
    require(bool(data), 'SHOT_METRIC_INPUT_EMPTY')
    return (data[(len(data)-1)//2]+data[len(data)//2])/2


def geom_from_file(hou, file):
    value = hou.Geometry()
    value.loadFromFile(str(file))
    return value


def tetrahedra(hou, geo):
    return [p for p in geo.prims() if p.type() == hou.primType.Tetrahedron]


def two_piece_seams(rest):
    points = points_by_id(rest)
    return [(key, key+1) for key in sorted(points)
            if key%2 == 0 and key+1 in points]


def active_stitches(constraints, topo):
    require(len(constraints.points()) == len(topo.points()), 'SHOT_CONSTRAINT_POINT_LAYOUT_CHANGED')
    ids = [p.attribValue('id') for p in topo.points()]
    return sorted({tuple(sorted(ids[v.point().number()] for v in p.vertices()))
                   for p in constraints.prims() if len(p.vertices()) == 2
                   and len({ids[v.point().number()] % 2 for v in p.vertices()}) == 2})


def body_connected(hou, geo):
    parents = {}
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for tet in tetrahedra(hou, geo):
        if tet.attribValue('shot_piece') != 0:
            continue
        ids = [v.point().attribValue('id') for v in tet.vertices()]
        for i in ids:
            parents.setdefault(i,i)
        for i in ids[1:]:
            parents[find(i)] = find(ids[0])
    return bool(parents) and len({find(i) for i in parents}) == 1


def build_graph(hou, root, tuning):
    types = available(hou, root)
    parent = hou.node('/obj').createNode('geo','shot',run_init_scripts=False)
    parent.setUserData('shot_tuning', str(tuning))
    capy = node(parent, types['testgeometry_capybara'], 'CAPYBARA')
    set_values(capy, addshader=0, outputclip=0)
    clip = parm(capy, 'clip')
    require('walk' in clip.menuItems(), 'SHOT_WALK_CLIP_UNAVAILABLE')
    set_values(capy, clip='walk')
    if capy.parm('applylocomotion') is not None:
        set_values(capy, applylocomotion=0)
    parm(capy, 'frame').setExpression('$F', hou.exprLanguage.Hscript)
    skin = node(parent, types['kinefx::jointdeform'], 'SKIN_WALK', (capy, (capy,1), (capy,2)))
    hou.setFrame(1)
    rest = geometry(capy)
    h = rest.boundingBox().sizevec()[1]
    require(h > .1 and len(rest.points()) > 100 and rest.findPointAttrib('boneCapture') is not None,
            'SHOT_CAPYBARA_SKIN_OR_CAPTURE_REQUIRED')
    require(len(geometry(skin).points()) == len(rest.points()), 'SHOT_WALK_TOPOLOGY_MISMATCH')
    # Keep the skinned source intact. Reduce only the rest-space collision/solve proxy.
    ratio = min(100., 100.*2400/len(rest.prims()))
    reduce = set_values(node(parent, find_type(hou,'polyreduce'), 'SOLVE_PROXY', (capy,)),
                        percentage=ratio)
    tet = set_values(node(parent, types['tetconform'], 'TET_BODY', (reduce,)), usemaxtetscale=1,
                     maxtetscale=.15, outputsurftri=0, allowsurfacemods=1,
                     usesdf=1, voxelsize=h/48.)
    cut = python_sop(parent, 'LEFT_WAIST_CUT', (tet,capy,(capy,1)), CUT_SOP)
    animated = set_values(node(parent, types['pointdeform'], 'ANIMATED_TETS', (cut,capy,skin)), radius=.16*h)
    previous = node(parent, 'timeshift', 'PREVIOUS_POSE', (animated,))
    parm(previous,'frame').setExpression('$F-1',hou.exprLanguage.Hscript)
    impulse = python_sop(parent, 'WAIST_IMPULSE', (animated,previous), VELOCITY_SOP)
    volume = set_values(node(parent, types['vellumconstraints'], 'TET_STRETCH', (impulse,)),
                        constrainttype='tetstretch', stretchstiffness=1.0, stretchstiffnessexp='6')
    pins = set_values(node(parent, types['vellumconstraints'], 'BODY_ANIMATION_PINS', (volume,(volume,1))),
                      constrainttype='pin', pingroup='body', pintype='hard', matchanimation=1)
    seams = set_values(node(parent, types['vellumconstraints'], 'BREAKABLE_SEAM', (pins,(pins,1))),
                       constrainttype='stitch', grouptype='points', group='seam_piece',
                       targetgrouptype='points', targetgroup='seam_body', dobreaking=1,
                       breaktypestretch='stretchdistance', breakthreshold=.007*h,
                       stretchstiffness=1.0, stretchstiffnessexp=('4','3','2')[tuning],
                       maxdistcheck=1, maxdist=.006*h)
    solver = set_values(node(parent, types['vellumsolver'], 'SOLVE_TEAR', (seams,(seams,1))),
                        startframe=TRIGGER, substeps=2, niter=45)
    choose = node(parent, 'switch', 'ANIMATION_TO_SIM', (impulse,solver))
    parm(choose,'input').setExpression('$F >= 48',hou.exprLanguage.Hscript)
    skinout = python_sop(parent, 'TET_BOUNDARY_SURFACE', (choose,), SURFACE_SOP)
    cache = set_values(node(parent,'file','VIEW_CACHE'), file='$HIP/cache/surface.$F4.bgeo.sc')
    cache.setDisplayFlag(True)
    cache.setRenderFlag(True)
    parent.layoutChildren()
    proxy = geometry(reduce)
    solids = geometry(tet)
    count = len(tetrahedra(hou,solids))
    dump(root/'solve-proxy.json', {'skin_polygons':len(rest.prims()),'proxy_polygons':len(proxy.prims()),
         'tets':count,'types':list(solids.primTypeNames()),'height':h,'voxel':h/48.})
    print('TETRAHEDRA',count,'PROXY_POLYGONS',len(proxy.prims()),flush=True)
    require(20 <= count <= TET_CAP, 'SHOT_SOLVE_PROXY_TET_LIMIT:' + str(count))
    return parent, choose, skinout, seams, solver, animated, cut


def take_samples(hou, root, end, start=1):
    parent = hou.node('/obj/shot')
    main = parent.node('ANIMATION_TO_SIM')
    surface = parent.node('TET_BOUNDARY_SURFACE')
    seams = parent.node('BREAKABLE_SEAM')
    solver = parent.node('SOLVE_TEAR')
    animated = parent.node('ANIMATED_TETS')
    for frame in range(start,end+1):
        hou.setFrame(frame)
        geometry(main).saveToFile(str(root/'cache'/f'tets.{frame:04d}.bgeo.sc'))
        geometry(surface).saveToFile(str(root/'cache'/f'surface.{frame:04d}.bgeo.sc'))
        if frame in SAMPLES or frame == end:
            if frame < TRIGGER:
                constraint_geo = geometry(seams,1)
            else:
                constraint_geo = geometry(solver,1)
            constraint_geo.saveToFile(str(root/'cache'/f'constraints.{frame:04d}.bgeo.sc'))
            geometry(animated).saveToFile(str(root/'cache'/f'animated.{frame:04d}.bgeo.sc'))
        if frame in SAMPLES or frame == end:
            print('CACHED',frame,flush=True)


def verify_core(hou, root, *, write_preview=False):
    parent = hou.node('/obj/shot')
    require(parent is not None and all(parent.node(n) is not None for n in
            ('CAPYBARA','SKIN_WALK','TET_BODY','LEFT_WAIST_CUT','ANIMATED_TETS',
             'BREAKABLE_SEAM','SOLVE_TEAR','VIEW_CACHE')), 'SHOT_REOPEN_GRAPH_REQUIRED')
    baseline = read(root/'baseline.json')
    h = baseline['height']
    pairs = baseline['pairs']
    anchors = baseline['anchors']
    files = read(root/'cache-manifest.json')
    for file in files:
        checked(file)
    samples = {}
    preview = {}
    all_ids = None
    for frame in SAMPLES:
        tet = geom_from_file(hou, root/'cache'/f'tets.{frame:04d}.bgeo.sc')
        surf = geom_from_file(hou, root/'cache'/f'surface.{frame:04d}.bgeo.sc')
        con = geom_from_file(hou, root/'cache'/f'constraints.{frame:04d}.bgeo.sc')
        pts = positions(tet)
        velocity = tet.findPointAttrib('v')
        require(velocity is not None, 'SHOT_VELOCITY_REQUIRED')
        require(all(math.isfinite(n) for p in pts.values() for n in p)
                and all(math.isfinite(n) for p in tet.points() for n in p.attribValue(velocity)),
                'SHOT_NONFINITE_GEOMETRY')
        ids = sorted(pts)
        if all_ids is None:
            all_ids = ids
        require(ids == all_ids, 'SHOT_POINT_IDENTITIES_CHANGED')
        tet_count = len(tetrahedra(hou,tet))
        require(tet_count == baseline['tet_count'], 'SHOT_TET_TOPOLOGY_CHANGED')
        authored = positions(geom_from_file(hou, root/'cache'/f'animated.{frame:04d}.bgeo.sc'))
        samples[str(frame)] = {'target_gap': median([distance(pts[a],pts[b])/h for a,b in pairs]),
                               'stitches': len(active_stitches(con,tet)),
                               'anchor_error': max(distance(pts[a],authored[a])/h for a in anchors),
                               'surface_primitives': len(surf.prims()),'tetrahedra':tet_count,
                               'body_connected':body_connected(hou,tet)}
        require(samples[str(frame)]['surface_primitives'] > 0, 'SHOT_SURFACE_EMPTY')
        if write_preview:
            preview[str(frame)] = {'points':[list(p.position()) for p in surf.points()],
                'triangles': [[*[v.point().number() for v in p.vertices()],p.attribValue('shot_piece')]
                              for p in surf.prims()]}
    p24 = positions(geom_from_file(hou, root/'cache/tets.0024.bgeo.sc'))
    p47 = positions(geom_from_file(hou, root/'cache/tets.0047.bgeo.sc'))
    walk = max(distance(p24[i],p47[i])/h for i in p24)
    checks = {'walk': walk > .005, 'pre_trigger_closed': samples['47']['target_gap'] <= .005,
              'post_trigger_open': samples['60']['target_gap'] >= .02,
              'native_stitch_break': samples['47']['stitches'] > samples['60']['stitches'],
              'body_anchors_match': all(s['anchor_error'] <= .02 for s in samples.values()),
              'body_connected':all(s['body_connected'] for s in samples.values())}
    value = {'state': 'PASS' if all(checks.values()) else 'FAIL', 'version': VERSION,
             'height':h,'walk_displacement':walk,'checks':checks,'samples':samples}
    if write_preview:
        dump(root/'preview-data.json',preview)
    return value


def build(hou, root, tuning):
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.setFps(24)
    hou.playbar.setFrameRange(1,60)
    hou.playbar.setPlaybackRange(1,60)
    parent, _, _, seams, _, _, cut = build_graph(hou,root,tuning)
    (root/'cache').mkdir(exist_ok=False)
    hou.setFrame(1)
    hou.hipFile.save(str(root/'shot.hip'))
    hou.setFrame(47)
    rest = geometry(cut)
    pairs = two_piece_seams(rest)
    ids = points_by_id(rest)
    body = sorted(key for key in ids if key%2 == 0)
    anchors = body[::max(1,len(body)//32)][:32]
    authored = geometry(seams)
    stitches = active_stitches(geometry(seams,1),authored)
    baseline = {'trigger':TRIGGER,'height':rest.attribValue('shot_height'),
                'left_axis':rest.attribValue('shot_left'),'left_joints':rest.attribValue('shot_left_joints'),
                'pairs':pairs,'anchors':anchors,'tet_count':len(tetrahedra(hou,rest)),
                'stitch_pairs':stitches}
    dump(root/'baseline.json',baseline)
    require(stitches and len(pairs) >= 4, 'SHOT_NATIVE_STITCH_REQUIRED')
    take_samples(hou,root,60)
    dump(root/'cache-manifest.json',[record(file) for file in sorted((root/'cache').iterdir())])
    report = verify_core(hou,root,write_preview=True)
    dump(root/'warm.json',report)
    require(report['state']=='PASS','SHOT_CORE_MEASUREMENTS_FAILED:' + json.dumps(report['checks']))


def cold(hou, root):
    hou.hipFile.load(str(root/'shot.hip'),suppress_save_prompt=True)
    for frame in SAMPLES:
        geo = hou.node('/obj/shot/VIEW_CACHE').geometryAtFrame(frame)
        require(geo is not None and len(geo.prims()) > 0, 'SHOT_COLD_CACHE_REOPEN_FAILED')
    report = verify_core(hou,root)
    dump(root/'cold.json',report)
    require(report['state']=='PASS','SHOT_CORE_COLD_FAILED')


def main():
    import hou
    step, dispatch = sys.argv[1:]
    config = read(dispatch)
    root = Path(config['root'])
    require(Path(dispatch) == root/'dispatch.json'
            and checked(config['worker']) == Path(__file__).resolve(),
            'SHOT_WORKER_BINDING')
    scope = json.loads(os.environ['BRIDGE_NATIVE_SCOPE_BINDING'])
    require(scope['path'] == str(root/'scope.json') and record(scope['path'])['sha256'] == scope['sha256'],
            'SHOT_WORKER_SCOPE_BINDING')
    scope_spec = read(scope['path'])
    require(checked(scope_spec['dispatch']) == Path(dispatch)
            and [x['step'] for x in config['steps']].count(step) == 1
            and hou.applicationVersionString() == VERSION, 'SHOT_HOST_VERSION_OR_STEP_MISMATCH')
    tuning = read(checked(config['parameters']))['tuning']
    print('NATIVE',hou.applicationVersionString(),step,flush=True)
    if config['phase'] == 'B':
        {'build':build,'cold':lambda h,p,t:cold(h,p)}[step](hou,root,tuning)
    else:
        raise ValueError('SHOT_NEXT_PHASE_REQUIRES_ACCEPTED_CORE')


if __name__ == '__main__':
    main()
