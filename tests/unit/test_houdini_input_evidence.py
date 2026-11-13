import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_houdini_fx_domains import _load_addon


class InputEvidenceTests(unittest.TestCase):
    def test_node_info_preserves_input_slots_without_cooking(self):
        addon=_load_addon()
        source=SimpleNamespace(path=lambda:'/obj/task/source')
        node=SimpleNamespace(path=lambda:'/obj/task/sink',type=lambda:SimpleNamespace(nameWithCategory=lambda:'Sop/merge'),
            errors=lambda:(),warnings=lambda:(),inputs=lambda:(None,source),
            inputConnections=lambda:(SimpleNamespace(inputNode=lambda:source,inputIndex=lambda:1,outputIndex=lambda:0),),
            cook=lambda: self.fail('node.info must not cook'))
        with patch.dict(sys.modules,{'hou':SimpleNamespace()}), patch.object(addon,'_node',return_value=node):
            info=addon.dispatch('node.info',{'path':'/obj/task/sink'})
        self.assertEqual(info['inputs'],[None,'/obj/task/source'])
