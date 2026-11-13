# Testing and live validation

## Default software gates

The default test suite is standard-library-only and does not launch a DCC or contact a model endpoint. It covers v1 compatibility, v2 contracts, domain registration, graph validation, causal candidates, policy, persistence, double approval, experience isolation, model-gateway request contracts, DCC command payloads, reference lineage, release contents, and Skill resources.

Tests using local loopback clients need permission to bind `127.0.0.1`. A sandbox `PermissionError` is an environment limitation and must be reported separately from assertion failures.

Every first-party DCC action has an exact `GatePolicy`. Gate kinds are `capability`, `operation`, `progress`, `verification`, and `not_applicable`; the deprecated `evidence_carrier` is accepted only as legacy data and never satisfies a policy. Strict tasks must provide an explicit kind and a boolean `passed`. `TECH_VERIFY`, `ARTIFACT_VERIFY`, and `DELIVER` additionally require a passing, action-matched `verification` gate. Carrier-only, progress-only, a wrong name, an unknown kind, an omitted strict kind, or a non-boolean verdict fails closed.

Structured DCC responses are stored under `TaskResult.step_outputs` and the matching checkpoint step. New strict tasks do not hide structured payloads inside gates. A checkpoint written before `step_outputs` existed remains readable; a diagnostic resume rewinds from the first technical-evidence step instead of returning the same completed result without doing work.

All v2 render ranges and Nuke v1 render ranges are bounded before a recipe allocates steps. The shared limit is 10,000 declared frames; 10,000 is accepted and 10,001 is rejected, including for a hand-built Nuke `TaskSpec` that bypasses the normal parser. Existing Houdini v1 specifications keep their historical input range, while v2 reference-rebuild work remains bounded. Nuke recipes keep the validated sequence as a lazy `range` until the bounded steps are materialized.

## Live DCC gates

The two Houdini probe levels are intentionally different:

```bash
hython tools/scan_node_types.py --json /absolute/path/node-types.json
hython tools/probe_domain_packs.py --level contract --json /absolute/path/contract.json
hython tools/probe_domain_packs.py --level runtime --json /absolute/path/runtime.json
hython tools/validate_houdini_http.py --json /absolute/path/houdini-http.json
```

`contract` checks native type/template addressability. `runtime` creates a disposable graph, cooks it, performs scalar/tuple snapshot-set-readback-restore, destroys the graph, and does not save a HIP. Neither level renders, proves artistic correctness, or promotes support. JSON records bind the exact Houdini build, command, UTC time, git commit, dirty-diff digest, probe/addon/catalog hashes, level, and evidence identity.

The runtime JSON also contains `resolver_target_probes` for representative HOM addresses: scalar tuple-components `radx` and `sizex`, plus the MaterialX `base_color` `ParmTuple`. All three must report addressable, writable, readback-verified, and restore-verified on each tested Houdini build. `validate_houdini_http.py` starts a new headless Bridge server from the checkout, calls health, capabilities, and FX probe through real loopback HTTP, verifies the process/source identity and fail-closed support state, then shuts down only the server it started.

A newly constructed Houdini server creates a random bearer token by default and exposes only the explicit structured-command allowlist; arbitrary Python is excluded. Starting a new unauthenticated server requires the explicit legacy opt-in flag, which still does not enable arbitrary Python. The legacy `code.exec_python` contract is available only when a trusted local operator deliberately launches Houdini with `HOUDINI_BRIDGE_ENABLE_CODE_EXEC=1`; it remains forbidden to visual-twin planners. Existing already-running tokenless GUI sessions remain client-compatible without weakening new instances. A tokenized manifest references a separate token sidecar; the instances directory must be a real owner-controlled directory, and on POSIX both manifest and token must be regular, non-symlink, current-user-owned `0600` files. The token is omitted from serialized endpoint inventories and evidence.

Live validation is opt-in and writes a new immutable evidence directory. Each Houdini pack must run on both Houdini 21 and 22:

1. Record exact application, Python, renderer, node type, and parameter-alias capability results.
2. Build an editable network from a clean scene.
3. Cook a short real solve or procedural result.
4. Collect domain evidence and inject a known fault.
5. Produce a bounded candidate that targets the injected cause.
6. Prove cache denial without a grant.
7. Grant the exact subject, write the production simulation cache when applicable, and reopen/read it.
8. Render and record before/after metrics, hashes, graph paths, and errors.

Nuke 17 validation uses separate effect, reference, optional plate, and AOV inputs. It saves and reopens the NK, reconstructs state from hidden metadata, recursively verifies final Write lineage with bounded symbolic sequence matching, renders the declared frame set including stride, and checks that output frames are fresh and readable. Embedded hash tokens such as `ref_####_beauty.exr` are supported, while an ordinary percent sign is not treated as a sequence token. Every render stores pre-render and produced identities; an old EXR, a file with no produced identity, an unchanged `mtime_ns`, a later-mutated file, or an unreadable frame fails and is reported in `stale_frames`/`unreadable_frames`.

Run the operator-only live harness against a newly started or explicitly reloaded Nuke 17 bridge, never an old GUI that still holds the previous module:

```bash
python3 tools/validate_nuke_live.py \
  --port NEW_NUKE_PORT \
  --output-dir /absolute/isolated/output \
  --json /absolute/path/nuke-live.json
```

The harness uses the privileged `nuke_run` command only to create its isolated 64x64 test sources. `nuke_run` is not exposed to planner models or task recipes.

Run at most one newly launched Houdini GUI instance at a time. Never close a DCC process that existed before the validation run.

## Live model gates

The release weak-model route is `DoubaoDesktopRoute`, not a claimed fixed
Doubao weight. First prove `DOUBAO_UI_CONTROLLED`: bind the exact executable
path/hash/signature, app build, driver hash and observed model label; use an
isolated conversation; obtain five consecutive accessibility read cycles; and
verify the composer and image entry without touching existing conversations.
Only synthetic, non-private fixtures may be uploaded. Run the non-mutating
preflight with `python3 tools/validate_doubao_desktop.py`; duplicate installs,
missing UI events, stale transcripts or an unverified route fail closed.

Then prove `DOUBAO_SKILL_CONFORMANT` against all 16 packs. Each pack needs
build/inspect, causal-candidate and approval-recovery cases, direct synthetic
reference-media evidence, zero forbidden actions, at least 95% first-action
accuracy, and 100% completion within two bounded correction turns. The
conformance entry must reference the exact UI evidence and driver identities.
UI control alone, a model reply alone, or software fakes cannot satisfy this
gate.

Real DeepSeek and HY3 tests remain useful optional-adapter evidence. They must
still probe actual capabilities and protect credentials/media boundaries, but
they cannot substitute for either Doubao release gate.

## Evidence index

`outputs/live-validation/index.json` is the only machine-readable support source. Domain entries bind pack and adapter versions, exact DCC build, git/dirty identity, addon and catalog hashes, reference and scene hashes, fault case, semantic-control read/write/restore coverage, approval events, regular non-symlink artifacts with SHA-256, metric deltas, artist acceptance, and overall result. Global `model_routes` bind the exact Doubao application and UI driver; per-domain `model_skill_conformance` entries must reference that immutable route evidence. The dirty identity is the SHA-256 of the canonical porcelain status, unstaged binary diff, staged binary diff, and every untracked file's bytes or symlink target, excluding generated live-validation output.

A self-consistent SHA-256 entry is not execution proof. Every non-empty index entry additionally requires a detached `hmac-sha256-v1` operator attestation made with an owner-only private key from `BRIDGE_SKILLS_EVIDENCE_ATTESTATION_KEY_FILE` (or `~/.bridge-skills/evidence-attestation.key`). Missing, short, symlinked, non-`0600`, wrong-owner, or wrong-signature keys fail closed in both the release verifier and Houdini runtime. This remediation batch deliberately provides no automatic promotion path from raw probe JSON: the later end-to-end release workflow must validate the raw harness schema and obtain the trusted promotion attestation. `docs/domain-support.md` must not claim a higher status than the attested index proves. The current index is intentionally empty, requires no key, and keeps every domain `experimental`/inconclusive even when its contract or runtime probe succeeds.

The 2026-08-30 audit-remediation evidence boundary and reproducible command set are recorded in [`remediation-2026-08-30.md`](remediation-2026-08-30.md).
