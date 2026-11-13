"""测试案例的几何测量与反馈评审；只消费实际几何，不授予生产或视觉通过。"""
from __future__ import annotations
import math
from collections import Counter
from dcc_task_runtime.canonical import canonical_sha256


def _fail(code):
    raise ValueError('GEOMETRY_EVALUATION_' + code)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _bounds(points, indices):
    return {'minimum':[min(points[i][axis] for i in indices) for axis in range(3)],
            'maximum':[max(points[i][axis] for i in indices) for axis in range(3)]}


def _extent(bounds):
    return [b-a for a,b in zip(bounds['minimum'], bounds['maximum'])]


def _center(bounds):
    return [(a+b)/2 for a,b in zip(bounds['minimum'], bounds['maximum'])]


def _verified_components(observation):
    """独立从真实点面拓扑重算连通分量，不信任外部自报bbox或部件标签。"""
    if (not isinstance(observation,dict) or observation.get('schema')!='bridge.geometry-observation/1'
            or observation.get('space')!='world' or observation.get('units')!='metres'
            or observation.get('up_axis')!='Y'):
        _fail('WORLD_OBSERVATION_REQUIRED')
    original_hash=observation.get('geometry_sha256')
    body={k:v for k,v in observation.items() if k!='geometry_sha256'}
    if original_hash is not None and original_hash!=canonical_sha256(body):
        _fail('OBSERVATION_DIGEST_CHANGED')
    points=observation.get('points');faces=observation.get('faces')
    if (type(points) is not list or not 1<=len(points)<=256 or type(faces) is not list
            or not 1<=len(faces)<=256):
        _fail('BOUNDED_POLYGON_DATA_REQUIRED')
    if any(type(p) is not list or len(p)!=3 or any(not _number(v) for v in p) for p in points):
        _fail('FINITE_POINTS_REQUIRED')
    if observation.get('point_count')!=len(points) or observation.get('primitive_count')!=len(faces):
        _fail('COUNTS_CHANGED')
    parents=list(range(len(points)));edges=Counter();used=set()
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for face in faces:
        if (type(face) is not list or not 3<=len(face)<=16
                or any(type(i) is not int or not 0<=i<len(points) for i in face)
                or len(set(face))!=len(face)):
            _fail('POLYGON_INDICES_REQUIRED')
        used.update(face)
        # 面积来自实际顶点，防止不同索引掩盖重合或共线退化面。
        origin=points[face[0]];area=0.0
        for i in range(1,len(face)-1):
            a=[points[face[i]][k]-origin[k] for k in range(3)]
            b=[points[face[i+1]][k]-origin[k] for k in range(3)]
            cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
            area+=math.sqrt(sum(v*v for v in cross))/2
        if not math.isfinite(area) or area<=1e-12:
            _fail('DEGENERATE_POLYGON')
        for i in face[1:]:parents[root(i)]=root(face[0])
        for a,b in zip(face,face[1:]+face[:1]):edges[tuple(sorted((a,b)))]+=1
    if used!=set(range(len(points))) or any(count!=2 for count in edges.values()):
        _fail('CLOSED_COMPONENTS_REQUIRED')
    groups={}
    for i in range(len(points)):groups.setdefault(root(i),[]).append(i)
    actual=[{'point_indices':indices,'point_count':len(indices),
             'primitive_count':sum(face[0] in indices for face in faces),
             'bounds':_bounds(points,indices)} for indices in groups.values()]
    actual.sort(key=lambda c:c['bounds']['minimum'])
    reported=observation.get('components')
    if reported is not None and canonical_sha256(reported)!=canonical_sha256(actual):
        _fail('COMPONENT_REPORT_CHANGED')
    actual_bounds=_bounds(points,range(len(points)))
    if observation.get('bounds') is not None and canonical_sha256(observation['bounds'])!=canonical_sha256(actual_bounds):
        _fail('BOUNDS_CHANGED')
    return points,faces,actual,actual_bounds,original_hash or canonical_sha256(body)


def measure(observation):
    """识别横梁和两柱，返回实际尺寸与结构检查；输入必须已经由调用方认证来源。"""
    points,faces,components,bounds,digest=_verified_components(observation)
    if len(components)!=3:
        _fail('THREE_COMPONENTS_REQUIRED')
    spans=[_extent(c['bounds']) for c in components]
    total=_extent(bounds);width,height,depth=total
    if min(total)<=1e-8:
        _fail('POSITIVE_EXTENTS_REQUIRED')
    tolerance=max(1e-4,1e-3*height)
    by_width=sorted(range(3),key=lambda i:spans[i][0],reverse=True)
    if spans[by_width[0]][0]-spans[by_width[1]][0]<=tolerance:
        _fail('UNIQUE_BEAM_REQUIRED')
    beam=components[by_width[0]]
    columns=sorted((components[i] for i in by_width[1:]),key=lambda c:_center(c['bounds'])[0])
    left,right=columns;lb,rb,bb=left['bounds'],right['bounds'],beam['bounds']
    ls,rs,bs=_extent(lb),_extent(rb),_extent(bb)
    lc,rc,bc=_center(lb),_center(rb),_center(bb)
    opening=rb['minimum'][0]-lb['maximum'][0]
    contacts=[]
    for c in columns:
        b=c['bounds']
        contacts.append({'signed_vertical_gap':bb['minimum'][1]-b['maximum'][1],
            'x_overlap':min(bb['maximum'][0],b['maximum'][0])-max(bb['minimum'][0],b['minimum'][0]),
            'z_overlap':min(bb['maximum'][2],b['maximum'][2])-max(bb['minimum'][2],b['minimum'][2])})
    symmetric=(abs(lb['minimum'][0]+rb['maximum'][0])<=tolerance
               and abs(lb['maximum'][0]+rb['minimum'][0])<=tolerance
               and all(abs(lb[side][axis]-rb[side][axis])<=tolerance
                       for side in ('minimum','maximum') for axis in (1,2)))
    checks={'three_closed_components':True,
        'columns_grounded':all(abs(c['bounds']['minimum'][1])<=tolerance for c in columns),
        'positive_clear_opening':opening>tolerance and lc[0]<0<rc[0],
        'upright_columns':all(s[1]>max(s[0],s[2])+tolerance for s in (ls,rs)),
        'horizontal_beam':bs[0]>max(bs[1],bs[2])+tolerance,
        'left_right_symmetric':symmetric,
        'beam_centered':abs(bc[0])<=tolerance and abs(bc[2]-(lc[2]+rc[2])/2)<=tolerance,
        'beam_column_contact':all(abs(c['signed_vertical_gap'])<=tolerance
                                  and c['x_overlap']>tolerance and c['z_overlap']>tolerance for c in contacts)}
    return {'schema':'bridge.geometry-measurement/1','geometry_sha256':digest,
        'width':width,'height':height,'depth':depth,'opening_width':opening,
        'column_widths':[ls[0],rs[0]],'column_heights':[ls[1],rs[1]],
        'column_depths':[ls[2],rs[2]],'column_center_z':[lc[2],rc[2]],'beam_center_z':bc[2],'column_ground_y':[lb['minimum'][1],rb['minimum'][1]],
        'beam_width':bs[0],'beam_height':bs[1],'beam_depth':bs[2],
        'height_over_width':height/width,'column_width_over_width':[ls[0]/width,rs[0]/width],
        'opening_over_width':opening/width,'beam_height_over_height':bs[1]/height,
        'column_height_over_height':[ls[1]/height,rs[1]/height],
        'contact_gaps':contacts,'bounds':bounds,'beam':beam,'columns':columns,
        'tolerance':tolerance,'structural_checks':checks}


def _criteria(criteria):
    """评审阈值来自单独的控制侧文件；不进入编译器、执行器或模型输入。"""
    if not isinstance(criteria,dict) or criteria.get('schema')!='bridge.geometry-test-criteria/1':
        _fail('CRITERIA_REQUIRED')
    initial=criteria.get('initial');feedback=criteria.get('feedback')
    required={'width','height','height_over_width','column_width_over_width','opening_over_width',
              'beam_height_over_height','column_height_over_height'}
    if (not isinstance(initial,dict) or set(initial)!=required
            or any(not _number(v) or v<=0 for v in initial.values())
            or not _number(criteria.get('relative_tolerance'))
            or not 0<criteria['relative_tolerance']<1
            or not isinstance(feedback,dict)
            or set(feedback)!={'opening_width_ratio','ratio_absolute_tolerance','preserve_relative_tolerance','preserve_absolute_tolerance'}
            or any(not _number(v) or v<=0 for v in feedback.values())
            or feedback['opening_width_ratio']<=1):
        _fail('CRITERIA_FIELDS_INVALID')
    return initial,feedback


def evaluate_initial(observation, criteria):
    """首版比值与物理尺寸评审；不以保存、像素相同或文字描述替代几何。"""
    if isinstance(criteria, dict) and criteria.get('schema') == 'bridge.table-geometry-test-criteria/1':
        from .table_evaluation import evaluate
        return evaluate(observation, criteria)
    initial,_=_criteria(criteria)
    try:m=measure(observation)
    except ValueError as error:
        return {'state':'FAIL','layer':'case_geometry','error_code':str(error),'criteria_sha256':canonical_sha256(criteria)}
    checks=dict(m['structural_checks']);relative=criteria['relative_tolerance']
    for name,target in initial.items():
        values=m[name] if isinstance(m[name],list) else [m[name]]
        checks['initial_'+name]=all(abs(value-target)<=abs(target)*relative for value in values)
    return {'state':'PASS' if all(checks.values()) else 'FAIL','layer':'case_geometry',
        'criteria_sha256':canonical_sha256(criteria),'checks':checks,'measurements':m,
        'human_visual_acceptance':'PENDING'}


def evaluate_feedback(before, after, criteria):
    """只验证实际门洞变化和应保留几何，不把灯光/曝光变化当作几何反馈。"""
    if isinstance(criteria, dict) and criteria.get('schema') == 'bridge.table-geometry-test-criteria/1':
        from .table_evaluation import evaluate
        return evaluate(after, criteria, before=before)
    _,f=_criteria(criteria)
    try:a,b=measure(before),measure(after)
    except ValueError as error:
        return {'state':'FAIL','layer':'case_geometry_feedback','error_code':str(error),'criteria_sha256':canonical_sha256(criteria)}
    tolerance=max(f['preserve_absolute_tolerance'],f['preserve_relative_tolerance']*a['height'])
    ratio=b['opening_width']/a['opening_width'] if a['opening_width']>0 else None
    checks={'before_structure':all(a['structural_checks'].values()),
            'after_structure':all(b['structural_checks'].values()),
            'actual_geometry_changed':a['geometry_sha256']!=b['geometry_sha256'],
            'opening_width_ratio':ratio is not None and abs(ratio-f['opening_width_ratio'])<=f['ratio_absolute_tolerance']}
    for name in ('height','column_widths','column_heights','column_depths','column_center_z','beam_center_z','column_ground_y','beam_height','beam_depth'):
        old=a[name] if isinstance(a[name],list) else [a[name]]
        new=b[name] if isinstance(b[name],list) else [b[name]]
        checks['preserved_'+name]=len(old)==len(new) and all(abs(x-y)<=tolerance for x,y in zip(old,new))
    return {'state':'PASS' if all(checks.values()) else 'FAIL','layer':'case_geometry_feedback',
        'criteria_sha256':canonical_sha256(criteria),'checks':checks,'opening_width_ratio':ratio,
        'preserve_tolerance':tolerance,'before':a,'after':b,'human_visual_acceptance':'PENDING'}
