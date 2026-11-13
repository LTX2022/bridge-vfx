"""Exact render fixtures; profile selection never grants native execution."""
from __future__ import annotations
import copy

LEGACY = 'sphere_ground_v2'
OFFICIAL = 'official_karma_disklight_v1'
GEOMETRY = 'bounded_geometry_rig_v1'
SOURCE_HIP_SHA256 = '831b34f61491caab897aa357eead398e3d770ac2a1c9187ea4ca4e669cc29106'
_DEFINITIONS = {
    GEOMETRY: {'resolution': [420, 300], 'sample_pixels': [[70, 150], [210, 150], [350, 150]],
               'policy': 'controlled_output_geometry_v1'},
    LEGACY: {'resolution': [128, 128], 'sample_pixels': [[16, 64], [64, 64], [112, 64]],
             'policy': 'controlled_output_v1'},
    OFFICIAL: {'resolution': [420, 300], 'sample_pixels': [[70, 150], [210, 150], [350, 150]],
               'policy': 'controlled_output_official_karma_v1'},
}


def definition(profile=LEGACY):
    if type(profile) is not str or profile not in _DEFINITIONS:
        raise ValueError('RENDER_PROFILE_UNSUPPORTED')
    return copy.deepcopy(_DEFINITIONS[profile])


def output_policy(profile=LEGACY):
    fixture = definition(profile)
    return {'policy': fixture['policy'], 'scene_variant': profile,
            'resolution': fixture['resolution'], 'frames': [1], 'channels': ['R', 'G', 'B', 'A']}
