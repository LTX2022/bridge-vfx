# OCIO output binding tests

Owned files: `tests/unit/test_render_ocio_binding.py` and this evidence directory only.
The existing receipt module is imported as a module; its TestCase is instantiated
only inside setUp, preventing duplicate discovery of the helper's tests.

The agreed collector is used directly with explicit `transform_requests` pairs.
Each preflight binds the exact `final_output_path` and includes
`config={path, file:{path,bytes,sha256}}`, `dependencies=[{path,bytes,sha256}]`,
`api_facts`, structured `missing_facts`, and explicit reconstruction scope.
Only bottom-level HOM and OCIO object APIs are substituted. Configuration/LUT,
EXR, scene files, hashes, supervisor signatures, producer process and consumer
reads are actual operations. No client, collector, validator or seal is mocked.

Main's integrated absent-preflight, path and drift error contracts are exercised
by 10 methods. Tests additionally prove restored-mtime config/LUT changes are
rejected at collection, seal and consumer read. Independently rehashed counterfeit
records first fail frozen start binding; even an independently regenerated
counterfeit producer binding cannot replace the signed original. An actual
producer recovers after a failed preseal drift check without consuming the
exclusive terminal claim. Color/alpha/runtime gaps remain BLOCKED.

Formal addon output-override/material regressions remain main-owned. This module
does not load or execute the addon. No additional main interface change required.

No real DCC, full suite, formal process tests, shared-source edits, or commits.
