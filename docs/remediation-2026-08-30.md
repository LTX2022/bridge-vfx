# Audit remediation evidence — 2026-08-30

This record covers only the gate/result contract, diagnostic task state,
Houdini parameter/cook/probe/support evidence, node scanning, and Nuke output
freshness findings. It also records the bounded-frame and loopback-manifest
security regressions found while independently reviewing those changes. It
does not implement the R2–R9 domain-network rebuild and does not promote any
domain to production support.

## Evidence classes

- **A — executed live or software evidence:** the project test runner; Houdini
  21.0.631 and 22.0.368 node scans plus contract/runtime probes; fresh headless
  loopback HTTP instances; and a newly started Nuke 17.0v1 instance exercising
  stale/fresh preview, final render, NK reopen, and reference lineage.
- **B — code inspection:** exact GatePolicy mappings, structured step outputs,
  diagnostic stop/resume behavior, transactional Houdini/Nuke parameter
  writes, support-index validation, authenticated Houdini startup, private
  token-manifest loading, detached evidence attestation, bounded frame
  planning, and DCC command ownership.
- **C — not validated here:** artistic similarity, real simulation dynamics,
  fault-injected rendered reference cases for every domain, real
  Doubao/DeepSeek/HY3 live routes, artist approval, cache production, and
  reusable-experience approval.

## Reproducible commands

Use the project interpreter for software tests and each application's own
Python for DCC probes:

```bash
python3 tests/run_tests.py
python3 tools/verify_docs_tools.py
python3 tools/verify_portability.py
python3 tools/verify_versions.py
python3 tools/verify_support_claims.py

hython tools/scan_node_types.py --json /absolute/output/houdini-node-scan.json
hython tools/probe_domain_packs.py --level contract --json /absolute/output/houdini-contract.json
hython tools/probe_domain_packs.py --level runtime --json /absolute/output/houdini-runtime.json
hython tools/validate_houdini_http.py --json /absolute/output/houdini-http.json

python3 tools/validate_nuke_live.py \
  --port NEW_OR_RELOADED_NUKE_PORT \
  --output-dir /absolute/isolated/nuke-artifacts \
  --json /absolute/output/nuke17-http.json
```

## Current observed boundary

The repository does not contain the previously documented
`outputs/live-validation/remediation-20260830-final/` directory. The existing
`remediation-20260830/` records are stale-source historical evidence only and
cannot validate the current addon, catalog or harness hashes. Any past H21/H22
status and `radx`/`sizex`/MaterialX `base_color` readback result must be rerun
against the current checkout before it can be cited as current evidence.

The Nuke harness must reject an intentionally stale preview and then accept a
newly rendered preview, final output, reopened NK, and reference-isolated final
Write. Nuke semantic patches are transactional: aliases resolving to the same
physical knob are rejected before mutation, and every requested value receives
a final whole-patch readback before the operation gate can pass. A passing
harness remains application-level evidence only; it is not a Houdini-domain
support promotion.

`outputs/live-validation/index.json` remains empty. Static
`validated_houdini_versions`, a contract probe, node creation, or software
tests cannot change that state. A hand-authored entry with recomputed hashes is
also rejected unless a trusted operator supplies an independent private-key
attestation; this batch does not auto-promote raw probe output.
