# P1 terminal original repair

Reproduced the independent review exactly before editing: `p1-before.log`
shows changed bytes refused with old snapshots, but accepted after rehashing
the mutable store while keeping the original start binding unchanged.

The current client adds `seal_render_terminal(record)` for the original live
owned child only. It authenticates the actual supervisor started receipt,
current PID/Windows birth/task/launch nonce, rejects a stopped child, and reuses
`owned_process._signed_write/read_receipt` with this launch's new runtime key.
No key is copied, printed, retained in reports or replaced by a fixture key.
The signed event binds the original start digest, supervisor started digest,
owner/host/request/operation/config/save/frames and the entire terminal fact,
including output SHA and physical metadata. A deterministic task/operation event
name and permanent exclusive claim prevent the hook overwriting an original.
An identical retry returns the original without writing; changed content or an
incomplete claimed seal refuses. Controller/status never signs or upgrades.

COMPLETED reads authenticate the original terminal event before trusting mutable
store/byte observations. Missing originals give `RENDER_TERMINAL_ANCHOR_REQUIRED`;
rehashed store/output gives `RENDER_TERMINAL_ANCHOR_MISMATCH`; a modified unsigned
envelope gives `RENDER_TERMINAL_ANCHOR_INVALID`. Existing physical byte and save
checks still run after authentication. OCIO/alpha remain
`BLOCKED_MISSING_NATIVE_FACTS`; no metadata AVAILABLE or default was added.

## Main's exact hook

In addon `_terminal`, after assigning `record['execution_fact']` and before
`self._save(store)`, only for render records with state COMPLETED:

```python
from houdini_bridge.client import seal_render_terminal
seal_render_terminal(record)
```

The function returns the authenticated payload; it need not be put in the mutable
store. Do not call it from status/controller or for old completed records.
The existing start `producer_binding` and per-frame collector hooks remain.
Main owns addon integration; this author edited only the two clients, the owned
test file and this output directory. No new production module was introduced.

## Actual verification

`.venv/Scripts/python.exe -B tests/unit/test_houdini_output_receipts.py`

- `p1-directed.log`: first run failed because Windows venv's executable is a
  forwarding process, so its Python worker did not equal the supervised PID.
- `p1-directed-base-python.log`: after launching the real `sys._base_executable`,
  14 tests PASS in 3.911 seconds, process exit 0. Production identity guards were
  not relaxed. Real supervised child starts and stops are used, with fresh
  per-launch keys, actual codec/file reads, and scheduler/registry databases.
- New regression: replacing EXR and rehashing snapshots/output facts/execution
  fact keeps the controller binding unchanged but fails against the signed
  original. Also covers no original, envelope tampering, controller signing
  refusal, producer changed-content overwrite refusal, and identical no-write
  retries. Existing physical bytes/config/save/path/race refusals remain tested.
- Root and controller copies are identical; scoped `git diff --check` passed.

These are explicitly synthetic operation fields and file/codec fixtures in real
Python processes, not real DCC output or normal formal-case acceptance. No real
rendering/model/cache/simulation, full suite, packaging or commit was performed.
All test owned children finished with authenticated stopped receipts; the central
process channel was released to Main before delivery.

SHA-256:

- Root/client mirror: `c08eedddc6e80ea8f16005971f2267eab2bae6c17259c15e0ac25c68998e337b`
- `tests/unit/test_houdini_output_receipts.py`: `b541fcbfb1ffac3551f7e097a6fa4db53cc09d8b2002fb2595f9eaa2fa442d34`
