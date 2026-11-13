"""Explicit synthetic controller resource policy for cache approval fixtures."""
from pathlib import Path


CACHE_ROOT = Path(__file__).resolve().parent / 'synthetic-cache'


def cache_output_path(filename='smoke.vdb'):
    return str(CACHE_ROOT / filename)


def resource_metadata(output=None, scene='scene', frames=(1, 48, 1)):
    if output is None:
        output = cache_output_path()
    return {'resource_contract': {'estimated_bytes': 1024, 'max_disk_bytes': 1024 * 1024,
        'simulation_start_frame': 1, 'max_seconds': 120, 'task_roots': [str(CACHE_ROOT)], 'output_path': output,
        'content_version': scene, 'frame_range': list(frames),
        'invalidation_scope': ['smoke.simulation', 'render', 'composite']}}
