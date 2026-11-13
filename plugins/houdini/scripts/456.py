"""Houdini post-scene startup hook for the local bridge.

Some Houdini 22 launch paths do not run ``456.py`` for the initial empty
scene, so ``123.py`` contains the same idempotent hook.  Keeping both hooks
is intentional: opening a hip file and creating a new scene each become
discoverable without requiring a manual Python Shell command.
"""

import hou

if hou.isUIAvailable():
    import houdini_bridge_addon

    houdini_bridge_addon.autostart()
