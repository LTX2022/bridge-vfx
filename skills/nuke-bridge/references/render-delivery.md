# Render delivery

`nuke.render_delivery` accepts a Houdini artifact manifest or an explicit EXR
sequence. It verifies the input frame range, dimensions, channels, and color
space before building an editable Read-to-Write graph.

Long renders must run in background mode. Completion requires `verify_render`
to re-read every expected output frame. A successful delivery also saves the
editable `.nk` graph beside the EXR sequence. A missing Nuke installation
never turns a successful Karma render into a failed Houdini task; it is a
separate, actionable dependency failure.
