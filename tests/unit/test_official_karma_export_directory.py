"""Export-directory regression tests, with no native execution or USD attestation.

Real code under test: worker._run_owned's warm branch, scalar_write,
verify_fixed_state and capture_parameters. Template/Parm/Node reuse the bottom
HOM fixtures in test_official_karma_observation; their test cases are not run here.

Explicit substitutes: HOM nodes and hipFile save/load (in-memory snapshots),
Path.exists/mkdir and file/receipt/scope persistence. Unrelated authoring is cut
at configure_output, configure_beauty and beauty_author_readback. The named
capture_observation boundary returns only real capture_parameters(rop), not a
scene/USD observation. Worker receipt literals such as real_host are not evidence
of native execution. These tests neither export USD nor start any process.
"""
import copy
from contextlib import ExitStack
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from houdini_bridge import official_karma_native as native
from houdini_bridge import official_karma_worker as worker
from test_official_karma_observation import Node, Parm, Template


SWITCH = '/stage/lights/switch3'
ROP = '/stage/lights/OUT_karma_lights'
AUTHOR = '/stage/lights/update_output_image_path'
SETTINGS = '/stage/lights/karmarendersettings'
DISKLIGHT = '/stage/lights/render_disklight'
DIRECTORY = 'savetodirectory_directory'
PROCESSOR = 'enableoutputprocessor_savetodirectory'


class _Scalar(Parm):
    def __init__(self, name, template, value):
        super().__init__(name, template, value)
        self.mutations = []
        self.read_only = False

    def _mutating(self, operation, *args):
        self.mutations.append((operation, args))
        if self.read_only:
            raise AssertionError('cold verification mutated ' + self.name())

    def deleteAllKeyframes(self):
        self._mutating('deleteAllKeyframes')
        super().deleteAllKeyframes()

    def set(self, value, **kwargs):
        self._mutating('set', value, kwargs)
        super().set(value, **kwargs)


class _Tuple:
    def __init__(self, parm):
        self.parm = parm

    def __iter__(self): return iter((self.parm,))
    def name(self): return self.parm.name()
    def parmTemplate(self): return self.parm.parmTemplate()
    def eval(self): return (self.parm.eval(),)


class _Node(Node):
    def __init__(self, path, fields=(), *, kind='fixture'):
        super().__init__()
        self._path = path
        self.kind = kind
        self.inputs = {}
        self.read_only = False
        for name, value in fields:
            template = Template(name, kind='Int' if type(value) is int else 'String')
            self.group.append(template)
            self.parms[name] = _Scalar(name, template, value)

    def path(self): return self._path
    def input(self, index): return self.inputs.get(index)
    def inputConnections(self):
        return tuple(SimpleNamespace(inputIndex=lambda index=index:index,
                                     inputNode=lambda node=node:node,outputIndex=lambda:0)
                     for index,node in sorted(self.inputs.items()))
    def parmTuples(self): return tuple(_Tuple(p) for p in self.parms.values())
    def parmTuple(self, name):
        if self.path() == SETTINGS and name == 'resolution':
            return SimpleNamespace(eval=lambda: (420, 300))
        parm = self.parm(name)
        return None if parm is None else _Tuple(parm)

    def setInput(self, index, node):
        if self.read_only:
            raise AssertionError('cold verification rewired ' + self.path())
        self.inputs[index] = node


class _HipMemory:
    """Parameter/topology persistence only; no actual HIP serialization."""
    def __init__(self, hou, case, store):
        self.hou = hou
        self.case = case
        self.store = store
        self.current_path = ''
        self.events = []

    def load(self, path, **kwargs):
        if self.hou.read_only:
            raise AssertionError('cold verification reloaded HIP')
        self.events.append(('load', path, kwargs))
        self.current_path = path
        if path != self.case['source_hip']['path']:
            self.hou.restore(copy.deepcopy(self.store[path]))

    def save(self, *, file_name, **kwargs):
        if self.hou.read_only:
            raise AssertionError('cold verification saved HIP')
        self.events.append(('save', file_name, kwargs))
        self.store[file_name] = copy.deepcopy(self.hou.snapshot())
        self.current_path = file_name

    def path(self): return self.current_path


class _Hou:
    def __init__(self, case, *, fixed=False, store=None):
        self.read_only = False
        self.frames = []
        self.nodes = {}
        self.nodes[SWITCH] = _Node(SWITCH, [('input', 1)])
        self.nodes[DISKLIGHT] = _Node(DISKLIGHT)
        self.nodes[SWITCH].setInput(1, self.nodes[DISKLIGHT])
        self.nodes[SETTINGS] = _Node(SETTINGS, [
            ('engine', 'cpu'), ('enablemblur', 0), ('denoiser', 'off')])
        self.nodes[AUTHOR] = _Node(AUTHOR, [
            ('productName_control', 'set'), ('productName', case['paths']['official_image'])])
        self.nodes[ROP] = _Node(ROP, [
            ('renderer', 'BRAY_HdKarma'), ('runcommand', 0), ('soho_foreground', 1),
            ('lopoutput', case['paths']['official_usd']),
            ('loppath', native.BEAUTY_ADAPTER if fixed else AUTHOR),
            ('rendercommand', 'husk'), ('husk_tpostframe', 0),
            (DIRECTORY, str(Path(case['paths']['official_usd']).parent) if fixed else '$HIP'),
            (PROCESSOR, 0 if fixed else 1)], kind='usdrender_rop')
        self.nodes[ROP].setInput(0,self.nodes[AUTHOR])
        if fixed:
            self._create_adapter('editproperties', node_name=native.BEAUTY_ADAPTER.rsplit('/', 1)[1])
            self.nodes[native.BEAUTY_ADAPTER].setInput(0, self.nodes[AUTHOR])
            self.nodes[ROP].setInput(0,self.nodes[native.BEAUTY_ADAPTER])
        else:
            # Reproduce a source directory/processor carrying native drivers.
            for name in (DIRECTORY, PROCESSOR):
                self.nodes[ROP].parm(name).keys = ['source native driver']
        self._bind_parent()
        self.hipFile = _HipMemory(self, case, {} if store is None else store)

    def _bind_parent(self):
        self.nodes[AUTHOR].parent = lambda: SimpleNamespace(createNode=self._create_adapter)

    def _create_adapter(self, kind, *, node_name):
        if self.read_only:
            raise AssertionError('cold verification created an adapter')
        path = '/stage/lights/' + node_name
        node = self.nodes[path] = _Node(path, kind=kind)
        return node

    def node(self, path): return self.nodes.get(path)
    def applicationVersionString(self): return native.VERSION
    def setFrame(self, frame):
        if self.read_only:
            raise AssertionError('cold verification changed frame')
        self.frames.append(frame)

    def snapshot(self):
        return {path: {'kind': node.kind,
            'fields': {name: {'value': copy.deepcopy(parm.value), 'keys': list(parm.keys),
                             'locked': parm.locked, 'kind': parm.template.kind}
                       for name, parm in node.parms.items()},
            'inputs': {index: source.path() for index, source in node.inputs.items()}}
            for path, node in self.nodes.items()}

    def restore(self, saved):
        self.nodes = {path: _Node(path, [(name, field['value'])
            for name, field in state['fields'].items()], kind=state['kind'])
            for path, state in saved.items()}
        for path, state in saved.items():
            node = self.nodes[path]
            node.inputs = {index: self.nodes[source] for index, source in state['inputs'].items()}
            for name, field in state['fields'].items():
                parm = node.parm(name)
                parm.keys = list(field['keys'])
                parm.locked = field['locked']
                parm.template.kind = field['kind']
        self._bind_parent()

    def forbid_writes(self):
        self.read_only = True
        for node in self.nodes.values():
            node.read_only = True
            for parm in node.parms.values():
                parm.read_only = True
                parm.mutations.clear()


class OfficialKarmaExportDirectoryTests(unittest.TestCase):
    def setUp(self):
        # Virtual absolute paths only. USD and image parents intentionally differ.
        self.root = Path('/official-karma-export-directory-fixture')
        self.case = {'paths': {
            'official_hip': str(self.root / 'work/official.hip'),
            'official_usd': str(self.root / 'usd/export/official.usd'),
            'official_image': str(self.root / 'images/official.exr')},
            'source_hip': {'path': str(self.root / 'source/vendor.hip')},
            'observer': {'fixture': 'observer'},
            'source_contract': {'path': str(self.root / 'contract.json'), 'sha256': 'c' * 64}}
        self.expected_directory = str(Path(self.case['paths']['official_usd']).parent)
        self.scope = SimpleNamespace(root=self.root, binding={'sha256': 's' * 64},
            scope={'hosts': {'hython': {'path': str(self.root / 'host/bin/hython')}}},
            check=Mock(name='scope_check_boundary'))

    def _warm(self, hou):
        def capture_rop(actual_hou, contract, **kwargs):
            self.assertIs(actual_hou, hou)
            return {'fixture_boundary': 'ROP parameters only',
                    'parameters': native.capture_parameters(actual_hou.node(ROP))}

        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'hou': hou}))
            stack.enter_context(patch.object(Path, 'exists', return_value=False))
            stack.enter_context(patch.object(Path, 'mkdir'))
            for name in ('configure_output', 'configure_beauty', 'beauty_author_readback'):
                stack.enter_context(patch.object(worker, name))
            captured = stack.enter_context(patch.object(worker, 'capture_observation', side_effect=capture_rop))
            stack.enter_context(patch.object(worker, 'load_record', return_value={'fixture': 'contract'}))
            stack.enter_context(patch.object(worker, 'file_record', return_value={'fixture': 'HIP record'}))
            written = stack.enter_context(patch.object(worker, 'write_new', return_value={'fixture': 'observation record'}))
            stack.enter_context(patch.object(worker, 'check_frozen_case'))
            stack.enter_context(patch.object(worker.owned_process, 'read_receipt', return_value=None))
            stack.enter_context(patch.object(worker.owned_process, '_signed_write'))
            result = worker._run_owned(self.scope, self.case, self.root / 'warm',
                {'fixture': 'identity'}, {'fixture': 'started'}, 'official-open-save')
        captured.assert_called_once()
        return result, written.call_args.args[1]['parameters']

    def _reopen(self, source):
        cold = _Hou(self.case, store=source.hipFile.store)
        cold.hipFile.load(self.case['paths']['official_hip'], suppress_save_prompt=True,
                          ignore_load_warnings=False)
        self.assertIsNot(cold.node(ROP), source.node(ROP))
        self.assertIsNot(cold.node(ROP).parm(DIRECTORY), source.node(ROP).parm(DIRECTORY))
        return cold

    def _fixed_cold(self):
        source = _Hou(self.case, fixed=True)
        source.hipFile.save(file_name=self.case['paths']['official_hip'], save_to_recent_files=False)
        return self._reopen(source)

    def _verify_read_only(self, hou, drift=None):
        before = hou.snapshot()
        parameters = native.capture_parameters(hou.node(ROP))
        events = copy.deepcopy(hou.hipFile.events)
        hou.forbid_writes()
        with patch.object(worker, 'beauty_author_readback'):
            if drift is None:
                self.assertIs(worker.verify_fixed_state(hou, self.case), hou.node(ROP))
            else:
                with self.assertRaisesRegex(ValueError, '^OFFICIAL_FIXED_STATE_DRIFT:' + drift + '$'):
                    worker.verify_fixed_state(hou, self.case)
        self.assertEqual(hou.snapshot(), before)
        self.assertEqual(native.capture_parameters(hou.node(ROP)), parameters)
        self.assertEqual(hou.hipFile.events, events)
        self.assertFalse(any(parm.mutations for node in hou.nodes.values() for parm in node.parms.values()))
        return parameters

    def _assert_static_export_controls(self, parameters):
        directory = parameters[DIRECTORY]
        self.assertEqual(directory['kind'], 'String')
        self.assertEqual(directory['value'], [self.expected_directory])
        self.assertEqual(directory['raw_channels'], [self.expected_directory])
        self.assertEqual(directory['keyframe_counts'], [0])
        self.assertEqual(parameters[PROCESSOR]['value'], [0])
        self.assertIs(type(parameters[PROCESSOR]['value'][0]), int)
        self.assertEqual(parameters[PROCESSOR]['keyframe_counts'], [0])

    def test_warm_writes_static_usd_parent_and_disables_processor_before_save(self):
        hou = _Hou(self.case)
        self.assertEqual(hou.node(ROP).parm(DIRECTORY).value, '$HIP')
        self.assertEqual(hou.node(ROP).parm(PROCESSOR).value, 1)
        result, captured = self._warm(hou)
        self.assertIs(hou.node(ROP).input(0),hou.node(native.BEAUTY_ADAPTER))
        self.assertEqual(hou.hipFile.store[self.case['paths']['official_hip']][ROP]['inputs'],{0:native.BEAUTY_ADAPTER})
        self.assertEqual(result['state'], 'OBSERVED_NOT_ACCEPTED')
        for name, value in ((DIRECTORY, self.expected_directory), (PROCESSOR, 0)):
            self.assertEqual(hou.node(ROP).parm(name).mutations, [
                ('deleteAllKeyframes', ()),
                ('set', (value, {'follow_parm_reference': False}))])
        self._assert_static_export_controls(captured)
        self.assertEqual(hou.hipFile.events, [
            ('load', self.case['source_hip']['path'],
             {'suppress_save_prompt': True, 'ignore_load_warnings': False}),
            ('save', self.case['paths']['official_hip'], {'save_to_recent_files': False})])
        saved = hou.hipFile.store[self.case['paths']['official_hip']][ROP]['fields']
        self.assertEqual(saved[DIRECTORY]['value'], self.expected_directory)
        self.assertEqual(saved[DIRECTORY]['keys'], [])
        self.assertEqual(saved[PROCESSOR]['value'], 0)
        self.assertEqual(saved[PROCESSOR]['keys'], [])
        cold = self._reopen(hou)
        self.assertEqual(self._verify_read_only(cold), captured)

    def test_warm_requires_available_export_control_parameters(self):
        for name in (DIRECTORY, PROCESSOR):
            for unavailable in ('missing', 'locked'):
                with self.subTest(field=name, unavailable=unavailable):
                    hou = _Hou(self.case)
                    if unavailable == 'missing':
                        del hou.node(ROP).parms[name]
                    else:
                        hou.node(ROP).parm(name).locked = True
                    with self.assertRaisesRegex(ValueError, '^OFFICIAL_NATIVE_FIELD_UNAVAILABLE:' + name + '$'):
                        self._warm(hou)
                    self.assertFalse(hou.hipFile.store)

    def test_cold_fixed_state_is_read_only_and_capture_survives_reopen(self):
        cold = self._fixed_cold()
        parameters = self._verify_read_only(cold)
        self._assert_static_export_controls(parameters)

    def test_cold_rejects_export_input_drift_with_correct_loppath(self):
        for inputs in ({},{0:AUTHOR},{1:native.BEAUTY_ADAPTER},{0:native.BEAUTY_ADAPTER,1:AUTHOR}):
            cold=self._fixed_cold()
            cold.node(ROP).inputs={index:cold.node(path) for index,path in inputs.items()}
            before=cold.snapshot()
            with self.subTest(inputs=inputs),patch.object(worker,'beauty_author_readback'):
                with self.assertRaisesRegex(ValueError,'OFFICIAL_EXPORT_CONNECTION_DRIFT'):
                    worker.verify_fixed_state(cold,self.case)
            self.assertEqual(cold.snapshot(),before)

    def test_cold_rejects_directory_drift_without_repair(self):
        for value in ('', '$HIP', '$HIP/usd', 'usd/export', str(self.root / 'elsewhere'),
                      self.case['paths']['official_usd'],
                      str(Path(self.case['paths']['official_image']).parent), 0):
            with self.subTest(value=value):
                cold = self._fixed_cold()
                cold.node(ROP).parm(DIRECTORY).value = value
                self._verify_read_only(cold, DIRECTORY)

    def test_cold_rejects_processor_switch_drift_including_wrong_scalar_type(self):
        for value in (1, '0', False, 0.0):
            with self.subTest(value=value, scalar_type=type(value).__name__):
                cold = self._fixed_cold()
                cold.node(ROP).parm(PROCESSOR).value = value
                self._verify_read_only(cold, PROCESSOR)

    def test_cold_rejects_missing_or_driven_controls_even_with_matching_evaluation(self):
        for name in (DIRECTORY, PROCESSOR):
            for fault in ('missing', 'driver'):
                with self.subTest(field=name, fault=fault):
                    cold = self._fixed_cold()
                    if fault == 'missing':
                        del cold.node(ROP).parms[name]
                    else:
                        parm = cold.node(ROP).parm(name)
                        self.assertEqual(parm.eval(), self.expected_directory if name == DIRECTORY else 0)
                        parm.keys = ['serialized native expression/keyframe']
                    self._verify_read_only(cold, name)
