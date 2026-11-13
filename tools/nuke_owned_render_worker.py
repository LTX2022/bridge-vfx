#!/usr/bin/env python3
"""Fixed packaged Nuke worker entry; no user/global import fallback."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
# 冷消费的真实来源核验也依赖Houdini生产证据和VFX登记实现，全部仅从本包装配。
for package, module in (('dcc-task-runtime','dcc_task_runtime'),('nuke-bridge','nuke_bridge'),
                        ('houdini-bridge','houdini_bridge'),('vfx-pipeline','vfx_pipeline')):
    for layout in ('runtime', 'packages'):
        source = root / layout / package / 'src'
        if (source / module).is_dir():
            sys.path.insert(0, str(source))
            break
from nuke_bridge.owned_render_worker import main
if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
