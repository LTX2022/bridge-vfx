# Failure recovery

`BRIDGE_UNREACHABLE` means check the intended DCC instance and its local addon;
do not launch another instance or resubmit a mutation whose outcome is unknown.
`BUSY` means query the existing operation and wait for its accounted outcome,
not retry the mutation; do not restart Houdini. `UNSUPPORTED_NODE`
or `RUNTIME_MISMATCH` means probe the installed version and choose a certified
recipe or stop. `COOK_FAILED`, `USD_EXPORT_FAILED`, `RENDER_FAILED`, and
`ARTIFACT_INVALID` require inspecting the named gate and its upstream inputs.
Change only the cause supported by evidence and invalidate the affected downstream outputs.

Use the installed runtime's checkpoint and exact operation ID. Resume only if
that operation's state permits it. If dispatch or actual stop is uncertain,
use the trusted reconciliation route; never rebuild as a substitute. Preserve
failed candidates and the last valid baseline. A stage success does not finish
the parent creative task. Apply the task's recorded repair budget and report
partial results when it is exhausted; do not promise a universal resume or
three-loop implementation that the selected runtime has not advertised.
