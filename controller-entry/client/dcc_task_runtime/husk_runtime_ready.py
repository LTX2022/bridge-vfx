"""Fixed H21 prerender code point; this file is executed by husk as a script."""
import os
from pathlib import Path
import runpy
import sys
import traceback

try:
    _filename = sys._getframe().f_code.co_filename
    if type(_filename) is not str:
        raise ValueError('HUSK_RUNTIME_READY_SOURCE_INVALID')
    _adapter = Path(_filename)
    if (not _adapter.is_absolute() or str(_adapter) != _filename
            or _adapter.name != 'husk_runtime_ready.py'
            or any(ord(char) < 32 or ord(char) == 127 for char in _filename)):
        raise ValueError('HUSK_RUNTIME_READY_SOURCE_INVALID')
    _owned_path = _adapter.with_name('owned_process.py')
    for _source in (_adapter, _owned_path):
        if (any(path.is_symlink() for path in (_source, *_source.parents))
                or not _source.is_file() or _source != _source.resolve(strict=True)
                or _source.stat().st_nlink != 1):
            raise ValueError('HUSK_RUNTIME_READY_SOURCE_INVALID')
    _owned = runpy.run_path(str(_owned_path),
                            run_name='_bridge_husk_owned_runtime_ready')
    _owned['runtime_ready_and_wait']()
except BaseException:
    traceback.print_exc()
    os._exit(2)
