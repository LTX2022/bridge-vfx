"""显式软件几何夹具；检查桌体评估，不声明原生宿主事实。"""
import copy
import unittest

from vfx_pipeline.geometry_evaluation import evaluate_initial, evaluate_feedback


def criteria():
    return {'schema':'bridge.table-geometry-test-criteria/1',
            'initial':{'width':1.2,'depth':.7,'height':.75,'top_thickness':.06,
                       'leg_width':.08,'leg_depth':.08,'inset_x':.08,'inset_z':.08},
            'relative_tolerance':.02,'absolute_tolerance':.002,
            'feedback':{'width_ratio':1.2,'ratio_absolute_tolerance':.005,'preserve_absolute_tolerance':.002}}


def table(width=1.2, depth=.7, height=.75, shift_leg=0., top_gap=0.):
    points=[];faces=[]
    def box(size, center):
        offset=len(points)
        for x,y,z in ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                      (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)):
            points.append([c+s*v/2 for c,s,v in zip(center,size,(x,y,z))])
        faces.extend([[offset+i for i in face] for face in
                      ((0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5))])
    box((width,.06,depth),(0,height-.03+top_gap,0))
    for i,(x,z) in enumerate(((-1,-1),(-1,1),(1,-1),(1,1))):
        box((.08,height-.06,.08),(x*(width/2-.12)+(shift_leg if i==0 else 0),
                                (height-.06)/2,z*(depth/2-.12)))
    return {'schema':'bridge.geometry-observation/1','space':'world','units':'metres','up_axis':'Y',
            'points':points,'faces':faces,'point_count':len(points),'primitive_count':len(faces)}


class TableEvaluationTests(unittest.TestCase):
    def test_five_part_table_baseline_and_twenty_percent_feedback(self):
        self.assertEqual(evaluate_initial(table(),criteria())['state'],'PASS')
        result=evaluate_feedback(table(),table(width=1.44),criteria())
        self.assertEqual(result['state'],'PASS')
        self.assertAlmostEqual(result['width_ratio'],1.2)
        self.assertEqual(result['human_visual_acceptance'],'PENDING')

    def test_fifteen_percent_is_failure_even_when_structure_is_valid(self):
        result=evaluate_feedback(table(),table(width=1.38),criteria())
        self.assertEqual(result['state'],'FAIL')
        self.assertFalse(result['checks']['width_ratio'])
        self.assertTrue(result['checks']['four_corner_supports'])

    def test_feedback_preserves_depth_and_height(self):
        for kwargs,name in (({'depth':.8},'preserved_depth'),({'height':.85},'preserved_height')):
            with self.subTest(name=name):
                result=evaluate_feedback(table(),table(width=1.44,**kwargs),criteria())
                self.assertEqual(result['state'],'FAIL')
                self.assertFalse(result['checks'][name])

    def test_floating_top_and_asymmetric_support_are_failures(self):
        for kwargs,name in (({'top_gap':.03},'top_leg_contact'),({'shift_leg':.03},'symmetric_supports')):
            with self.subTest(name=name):
                result=evaluate_initial(table(**kwargs),criteria())
                self.assertEqual(result['state'],'FAIL')
                self.assertFalse(result['checks'][name])

    def test_counts_and_topology_are_recomputed(self):
        for change in ('counts','open_mesh','claimed_bounds'):
            value=table()
            if change=='counts':value['point_count']=8
            elif change=='open_mesh':value['faces'].pop();value['primitive_count']-=1
            else:value['bounds']={'minimum':[0,0,0],'maximum':[1.2,.75,.7]}
            with self.subTest(change=change):
                self.assertEqual(evaluate_initial(value,criteria())['state'],'FAIL')

    def test_skewed_box_cannot_pass_with_matching_bounds(self):
        value=table();value['points'][0][0]+=.05
        self.assertEqual(evaluate_initial(value,criteria())['state'],'FAIL')

    def test_unchanged_geometry_is_not_successful_feedback(self):
        result=evaluate_feedback(table(),table(),criteria())
        self.assertEqual(result['state'],'FAIL')
        self.assertFalse(result['checks']['actual_geometry_changed'])

    def test_wrong_initial_size_cannot_be_hidden_by_correct_feedback_ratio(self):
        result=evaluate_feedback(table(width=1.1),table(width=1.32),criteria())
        self.assertEqual(result['state'],'FAIL')
        self.assertTrue(result['checks']['width_ratio'])
        self.assertFalse(result['checks']['before_initial_target'])

    def test_invalid_and_unknown_criteria_do_not_fall_back_to_success(self):
        for change in ('schema','invalid_ratio','impossible_inset'):
            value=copy.deepcopy(criteria())
            if change=='schema':value['schema']='bridge.unknown-criteria/1'
            elif change=='invalid_ratio':value['feedback']['width_ratio']=float('nan')
            else:value['initial']['inset_x']=.7
            with self.subTest(change=change),self.assertRaises(ValueError):
                evaluate_initial(table(),value)
