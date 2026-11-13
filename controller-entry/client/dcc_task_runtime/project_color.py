"""Validate an explicit human project selection, not native execution evidence."""
from __future__ import annotations


def validate_project_color(value):
    """Return a detached canonical selection; never choose a default standard."""
    if value is None:
        raise ValueError('PROJECT_COLOR_SELECTION_REQUIRED')
    keys = ('schema', 'project_id', 'revision', 'colorspace', 'source')
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('PROJECT_COLOR_SELECTION_INVALID')
    if (value['schema'] != 'bridge.project-color/1.0'
            or value['source'] != 'human_project_selection'
            or type(value['revision']) is not int or value['revision'] <= 0):
        raise ValueError('PROJECT_COLOR_SELECTION_INVALID')
    for key in ('project_id', 'colorspace'):
        token = value[key]
        if (not isinstance(token, str) or not 0 < len(token) <= 256
                or token != token.strip()
                or any(ord(character) < 32 or ord(character) == 127 for character in token)):
            raise ValueError('PROJECT_COLOR_SELECTION_INVALID')
    return {key: value[key] for key in keys}
