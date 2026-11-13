"""Houdini new-scene startup hook for the local bridge.

The add-on server is process-local and ``autostart`` is idempotent, so this
early hook safely complements ``456.py`` across Houdini 21 and 22.
"""

import hou

if hou.isUIAvailable():
    import houdini_bridge_addon

    houdini_bridge_addon.autostart()
