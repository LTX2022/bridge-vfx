# OCIO binding regression result

Final owned test module: `tests/unit/test_render_ocio_binding.py`.
Only that new module and this evidence directory were written by this agent.
Existing receipt helper, client, addon, mirror and shared fixtures were not edited.

Final scoped run: **10 tests PASS, 0 failures/errors/skips, 4.144 seconds,
exit 0**. The `tools.run_logged --` wrapper records actual invocation and outcome:

- [Raw final log](final-20261013T052753038022Z-20261013-132753.log)
- [Before/after scoped source freeze](final-20261013T052753038022Z-source-hashes.json)

All consumed scoped source hashes were unchanged during the final run.
Frozen test SHA-256: `80431a55cc942c7a1166825455e8c78b7ba01243b29e7a467d8710eff0838bb3`.
Consumed client SHA-256: `74c309a4cd6fbdfd34174aab60af0b0472806774dffb3a3e6dbac6e2342a8b0c`.
Consumed collector SHA-256: `83da454564d67b82a13eb8df17559c93498fd39db648e8da665ea408a67ec3b0`.
Shared receipt helper SHA-256 remains
`b541fcbfb1ffac3551f7e097a6fa4db53cc09d8b2002fb2595f9eaa2fa442d34`.
These hashes describe the executed version; subsequent A-owned API changes must
be evaluated by main's central affected tests and do not inherit this PASS.

Coverage includes both unsigned and signed legacy missing-preflight paths,
normal actual config/LUT facts, detached observation, exact output-path mismatch,
malformed facts, config/LUT tamper at collection, actual producer preseal and
signed consumer read, independently rehashed counterfeit records/bindings, and
corrupted EXR bytes despite valid preflight. Tamper preserves file size and
restores the original mtime. Failed preseal writes no anchor or exclusive claim;
restored original bytes can then be signed by the same actual producer.
Counterfeit facts with valid recomputed hashes cannot replace a signed terminal.
Consumer rejection leaves the scheduler reservation active; restoring original
files permits normal authenticated read and release.

Setup delegates to `receipts.HoudiniOutputReceiptTests()` as a local fixture;
the imported module is the only module-level receipt helper reference. Scoped
standard discovery finds exactly 10 methods, with no foreign TestCase aliases.
The real collector/client/validator/seal are never mocked. Only bottom-level HOM
and OCIO object APIs are explicit substitutes; files, hashes, EXR bytes, process
ownership and signatures use the actual existing implementation. Each supervisor
generates fresh signing material in its temporary fixture; no keys enter evidence.

Config/LUT preflight never proves runtime writer colorspace or alpha association;
completion metadata remains `BLOCKED_MISSING_NATIVE_FACTS`, with empty metadata.
No further interface changes are needed for this module. Formal addon exact-frame
override and legacy material calls remain main's central verification scope.

Software binding tests alone passed. Installation, real Houdini/Nuke, HY3/model,
visual and production acceptance are NOT_RUN. No full suite or formal process
tests ran; no commits were made. Earlier two-test baseline and intermediate
10-test logs remain audit material, not substitutes for this final scoped freeze.
