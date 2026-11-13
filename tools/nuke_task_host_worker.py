#!/usr/bin/env python3
"""Run the fixed packaged task-host worker."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for layout in ('runtime','packages'):
    source=root/layout/'nuke-bridge'/'src'
    if (source/'nuke_bridge').is_dir():
        sys.path.insert(0,str(source));break
from nuke_bridge.task_host_worker import run
if __name__=='__main__':run(sys.argv[1])
