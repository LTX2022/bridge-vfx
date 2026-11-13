# Version compatibility

The bridge probes Houdini rather than hard-coding a release. It has adaptive
paths for Houdini 20.5 through 22.0, but a version is `CERTIFIED` only after a
real end-to-end test with that exact application's `hython`, Solaris nodes, and
Karma renderer. Untested builds are `COMPATIBLE_UNVERIFIED`.

Do not run cross-version Python as a replacement for hython. A failed node type
probe is an explicit compatibility failure, not a reason to substitute a nearby
node and report an equivalent result.

