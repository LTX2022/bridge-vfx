"""Explicit bottom hou API extensions for Swarm tests, never native execution.

Linear channels are evaluated from their stored keys. Save/load preserves actual
software scene state; no graph, operation result or acceptance receipt is supplied.
"""
import json
from pathlib import Path


def swarm_basis():
    """Explicit test task inputs, not inferred user coordinates or noise settings."""
    return {
        'schema': 'bridge.swarm-basis/1',
        'space': 'simulation_geometry',
        'goal_base': [0., 3., 0.],
        'seed': 314159,
        'time_origin': 0.,
        'time_range': [-2., 3.],
        'noise_context': {
            'swirlsize': 1., 'swirlscale': [1., 1., 1.], 'pulselength': 1.,
            'rough': .5, 'atten': 1., 'turb': 3, 'offset': [0., 0., 0., 0.],
        },
    }


def install_time_api(hou):
    """Extend an already constrained software hou instance with seconds/linear API."""
    hou.Keyframe.setTime = lambda key, time: key.setFrame(time * hou.fps() + 1)
    hou.Keyframe.time = lambda key: (key.frame() - 1) / hou.fps()
    probe = hou.node('/obj').createNode('geo', 'swarm_time_api_probe')
    parm_type = type(probe.createNode('box', 'box').parm('sizex'))
    probe.destroy()
    original_eval = parm_type.eval

    def evaluate(parm):
        state = parm._native_state
        keys = state['keyframes']
        if (not state['expression'] and not state['reference'] and keys
                and all(key['expression'] == 'linear()'
                        and key['language'] == str(hou.exprLanguage.Hscript)
                        for key in keys)):
            keys = sorted(keys, key=lambda key: key['frame'])
            frame = hou.frame()
            if len({key['frame'] for key in keys}) != len(keys):
                raise ValueError('duplicate key time')
            if frame <= keys[0]['frame']:
                return keys[0]['value']
            if frame >= keys[-1]['frame']:
                return keys[-1]['value']
            for first, second in zip(keys, keys[1:]):
                if first['frame'] <= frame <= second['frame']:
                    weight = (frame - first['frame']) / (second['frame'] - first['frame'])
                    return first['value'] * (1 - weight) + second['value'] * weight
        return original_eval(parm)

    parm_type.eval = evaluate
    parm_type.evalAtTime = lambda parm, time: parm.evalAtFrame(time * hou.fps() + 1)
    original_save, original_load = hou.hipFile.save, hou.hipFile.load
    header = b'bridge.software_hom_snapshot/1\n'

    def read_snapshot(path):
        raw = Path(path).read_bytes()
        if not raw.startswith(header):
            raise ValueError('not a software hou snapshot')
        return json.loads(raw[len(header):])

    def save(*args, **kwargs):
        result = original_save(*args, **kwargs)
        path = Path(hou.hipFile.path())
        data = read_snapshot(path)
        data['scene_time'] = {'frame': hou.frame(), 'fps': hou.fps()}
        path.write_bytes(header + json.dumps(data, sort_keys=True, allow_nan=False).encode())
        return result

    def load(path, *args, **kwargs):
        data = read_snapshot(path)
        result = original_load(path, *args, **kwargs)
        if data['scene_time']['fps'] != hou.fps():
            raise ValueError('unsupported saved FPS')
        hou.setFrame(data['scene_time']['frame'])
        for record in data['nodes']:
            node = hou.node(record['path'])
            for index, connection in enumerate(record['inputs']):
                if connection is None:
                    node.setInput(index, None)
        return result

    hou.hipFile.save, hou.hipFile.load = save, load
