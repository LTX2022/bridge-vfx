"""Explicit bottom HOM clocks/channels for P01; no POP execution or authority."""
from contextlib import ExitStack
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
from types import SimpleNamespace
from unittest.mock import patch

from vfx_pipeline.workbuddy_assembly import software_host_client

ROOT = Path(__file__).resolve().parents[2]
CLOCK_STATE_KEY = '_test_particle_emission_clock_state_v1'
CLOCK_FIELDS = (('native_offset_time', 'Offset Time', -.25),
                ('native_scale_time', 'Scale Time', 1.))


def injected_states(states):
    for name, value in (('constantrate', 1200.), ('probemit', 0),
                        ('seed', 17.), ('jitterbirthtime', 'positive')):
        states.setdefault('Dop/popsource::2.0', {})[name] = dict(
            origin='test_injected_native_api', value=value,
            locked=False, hidden=False, disabled=False)
    states.setdefault('Dop/popsolver::2.0', {})['timescale'] = dict(
        origin='test_injected_native_api', value=1.,
        locked=False, hidden=False, disabled=False)


def seed_manifest(path):
    path = Path(path).resolve()
    path.write_text(json.dumps({'task_seed': 173}), encoding='utf-8')
    content = path.read_bytes()
    return [dict(index=0, asset_id='explicit-p01-task-seed',
                 semantic_role='particle_emission_basis', source_uri=str(path),
                 identity=str(path), sha256=hashlib.sha256(content).hexdigest(),
                 bytes=len(content))]


def install_bottom_api(hou, probe_path=None):
    node_class = type(hou.node('/obj'))
    parameter_class = hou._native_schema_parm_class
    clocks = {}
    original_parm, original_parms = node_class.parm, node_class.parms
    original_group = getattr(node_class, 'parmTemplateGroup', None)

    def trace(kind, path, **facts):
        if probe_path is None:
            return
        destination = Path(probe_path)
        phase_path = destination.with_suffix('.phase.json')
        if not phase_path.is_file():
            return
        event = dict(kind=kind, path=str(path), pid=os.getpid(),
                     phase=json.loads(phase_path.read_text(encoding='utf-8')), **facts)
        with destination.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')

    def clock_parameters(node):
        if node.type().nameWithCategory() != 'Sop/dopnet':
            return {}
        if node not in clocks:
            parameters = {}
            for name, label, value in CLOCK_FIELDS:
                parameter = parameter_class(name)
                parameter._node = node
                parameter._component_index = 0
                parameter._instance_key = name
                parameter.value = value
                parameter._native_state = dict(
                    locked=False, hidden=False, disabled=False,
                    expression=None, language=None, reference=None, keyframes=[],
                    pre_extrapolation=str(hou.parmExtrapolate.Constant),
                    post_extrapolation=str(hou.parmExtrapolate.Constant),
                    instance_state_origin='test_injected_native_api')
                parameter._template = SimpleNamespace(
                    kind='float', key=name, count=1, multiparms=(), records={},
                    raw=dict(disable_when='', hide_when='', ancestors=[]),
                    name=lambda name=name: name, label=lambda label=label: label,
                    type=lambda: 'parmTemplateType.Float', numComponents=lambda: 1,
                    menuItems=lambda: (), menuLabels=lambda: (),
                    menuUseToken=lambda: False, isHidden=lambda: False,
                    minIsStrict=lambda: False, maxIsStrict=lambda: False,
                    minValue=lambda: 0., maxValue=lambda: 1.)
                parameters[name] = parameter
            clocks[node] = parameters
        return clocks[node]

    def parm(node, name):
        parameters = clock_parameters(node)
        return parameters[name] if name in parameters else original_parm(node, name)

    def group(node):
        parameters = clock_parameters(node)
        if parameters:
            return SimpleNamespace(entries=lambda: tuple(
                parameter.parmTemplate() for parameter in parameters.values()))
        if original_group is not None:
            return original_group(node)
        return node.type().parmTemplateGroup()

    node_class.parm = parm
    node_class.parms = lambda node: [*original_parms(node), *clock_parameters(node).values()]
    node_class.parmTemplateGroup = group
    node_class.isBypassed = lambda node: False
    hou.fps = lambda: 24.
    hou.frameToTime = lambda frame: (float(frame) - 1.) / hou.fps()
    hou.time = lambda: hou.frameToTime(hou.frame())
    original_eval = parameter_class.eval
    original_expression = parameter_class.setExpression
    original_keys = parameter_class.setKeyframes
    original_set = parameter_class.set
    original_delete = parameter_class.deleteAllKeyframes
    original_extrapolation = parameter_class.setKeyframeExtrapolation

    def evaluate(parameter):
        source = parameter._native_state['expression']
        if parameter.name() != 'constantrate' or source is None:
            return original_eval(parameter)
        if parameter._native_state['language'] != str(hou.exprLanguage.Python):
            raise ValueError('P01 bottom boundary requires a Python channel')
        if not source.startswith('import hou\nimport math\nimport hashlib\n'):
            raise ValueError('P01 bottom boundary only evaluates generated expression bodies')
        namespace = {}
        exec('def evaluate():\n' + textwrap.indent(source, '    '), namespace)
        value = namespace['evaluate']()
        trace('expression_eval', parameter.path(), expression=source,
              frame=hou.frame(), time=hou.time(), value=value)
        return value

    def set_expression(parameter, source, language=None):
        trace('parm_expression_write', parameter.path(), expression=source, language=str(language))
        original_expression(parameter, source, language)
        if parameter.name() == 'constantrate':
            parameter._native_state['keyframes'] = [dict(
                frame=hou.frame(), value=None, expression=source, language=str(language))]

    def set_keys(parameter, keys):
        keys = tuple(keys)
        trace('parm_keys_write', parameter.path(), count=len(keys))
        original_keys(parameter, keys)
        if parameter.name() == 'constantrate' and len(keys) == 1 and keys[0].expression() is not None:
            parameter._native_state.update(expression=keys[0].expression(),
                                           language=str(keys[0].expressionLanguage()))

    def set_value(parameter, value, **kwargs):
        trace('parm_value_write', parameter.path(), value=value)
        return original_set(parameter, value, **kwargs)

    def delete_keys(parameter):
        trace('parm_keys_delete', parameter.path())
        return original_delete(parameter)

    def extrapolation(parameter, before, value):
        trace('parm_extrapolation_write', parameter.path(), before=before, value=str(value))
        return original_extrapolation(parameter, before, value)

    parameter_class.eval = evaluate
    parameter_class.setExpression = set_expression
    parameter_class.setKeyframes = set_keys
    parameter_class.set = set_value
    parameter_class.deleteAllKeyframes = delete_keys
    parameter_class.setKeyframeExtrapolation = extrapolation
    original_save, original_load = hou.hipFile.save, hou.hipFile.load

    def all_nodes():
        return tuple(node for root in ('/obj', '/stage', '/mat', '/out')
                     for parent in [hou.node(root)] if parent is not None
                     for node in parent.allSubChildren())

    def save(*args, **kwargs):
        for node in all_nodes():
            parameters = clock_parameters(node)
            if parameters:
                node.setUserData(CLOCK_STATE_KEY, json.dumps(dict(
                    schema='test.p01-native-clock-state/1', frame=hou.frame(),
                    parameters={name: dict(value=parameter.value,
                        state=copy.deepcopy(parameter._native_state))
                        for name, parameter in parameters.items()}), sort_keys=True))
        return original_save(*args, **kwargs)

    def load(path, *args, **kwargs):
        trace('hip_load_begin', path)
        result = original_load(path, *args, **kwargs)
        frames = set()
        for node in all_nodes():
            parameters = clock_parameters(node)
            if not parameters:
                continue
            raw = node.userData(CLOCK_STATE_KEY)
            if raw is None:
                raise ValueError('saved explicit native clock state is missing')
            saved = json.loads(raw)
            if saved['schema'] != 'test.p01-native-clock-state/1' or set(saved['parameters']) != set(parameters):
                raise ValueError('saved explicit native clock state differs')
            frames.add(saved['frame'])
            for name, parameter in parameters.items():
                parameter.value = saved['parameters'][name]['value']
                parameter._native_state = copy.deepcopy(saved['parameters'][name]['state'])
        if len(frames) > 1:
            raise ValueError('saved explicit native scene clocks disagree')
        if frames:
            hou.setFrame(frames.pop())
        trace('hip_load_end', path)
        return result

    hou.hipFile.save, hou.hipFile.load = save, load


def launch_source():
    import test_production_task_hosts as support
    marker = "native.constrain_hou(native_root/"
    if support.STRICT_RENDER_NATIVE.count(marker) != 1:
        raise ValueError('expected one strict bottom API installation')
    native_source = support.STRICT_RENDER_NATIVE.replace(marker,
        "sys.path.insert(0,str(native_root/'tests/unit'))\n"
        "import particle_emission_process_boundary as p01_boundary\n"
        "p01_boundary.injected_states(states)\n" + marker)
    native_source += "p01_boundary.install_bottom_api(hou,os.environ['BRIDGE_TEST_P01_NATIVE_PROBE'])\n"
    bootstrap_marker = "sys.modules['houdini_bridge_addon']=addon"
    if support.HYTHON.count(bootstrap_marker) != 1:
        raise ValueError('expected one actual addon bootstrap installation')
    return support.HYTHON.replace(bootstrap_marker, bootstrap_marker + '\n' + native_source)


class RegisteredFixture:
    def __init__(self, version):
        self.version = version
        self.stack = ExitStack()

    def __enter__(self):
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch.dict(os.environ, {
            'HOUDINI_BRIDGE_STATE_DIR': str(self.directory / 'houdini'),
            'BRIDGE_SKILLS_STATE_ROOT': str(self.directory / 'state'),
            'BRIDGE_SKILLS_SCHEDULER_ROOT': str(self.directory / 'scheduler')}))
        self.stack.enter_context(patch.dict(sys.modules))
        self.client, self.addon = software_host_client(
            ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py', self.directory / 'host')
        modules = []
        for name in ('native_schema_test_boundary', 'software_render_api_boundary'):
            spec = importlib.util.spec_from_file_location('p01_registered_' + name, ROOT / 'tools' / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules.append(module)
        native, api = modules
        interfaces, states, ports = api.interface_profiles(ROOT, self.version)
        injected_states(states)
        native.constrain_hou(ROOT / 'docs/native-basis/hda-interface-capture.json', self.version,
            instance_states=states, native_api_interfaces=interfaces, native_api_ports=ports)
        self.hou = sys.modules['hou']
        api.install_stage_api(self.hou)
        install_bottom_api(self.hou)
        self.hou.expandString = lambda value: value
        self.task = 'particle-emission-registered-worker'
        identity = dict(task_id=self.task, version=self.version, pid=os.getpid(),
            launch_nonce='explicit-p01-registered-boundary', session_id='p01-registered-session',
            process_generation='p01-registered-generation', plugin_build=self.addon._FX_LOADED_ADDON_SHA256)
        self.stack.enter_context(patch.object(self.addon, '_TASK_HOST_IDENTITY', identity, create=True))
        self.input_manifest = seed_manifest(self.directory / '冻结粒子 seed with space.json')
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)
