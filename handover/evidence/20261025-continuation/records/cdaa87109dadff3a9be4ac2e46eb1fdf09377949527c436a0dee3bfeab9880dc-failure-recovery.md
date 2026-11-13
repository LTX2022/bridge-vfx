# Failure recovery

When a render is interrupted, use `task.status` and `task.events` to identify
the first unverified frame. `task.resume` preserves frames that already pass
`verify_render`. Missing Nuke, invalid EXR paths, and color-space ambiguity are
actionable dependency failures, not proof that an upstream Karma render failed.

After three repair loops the task becomes `PARTIAL`. The result names the
remaining output or graph gate; it never reports a background render as done
without frame verification.

