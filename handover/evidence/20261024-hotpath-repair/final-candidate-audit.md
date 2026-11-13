# Final candidate read-only audit

Decision: PASS

160 frozen runtime files match current source byte-for-byte and match their freeze hashes. Expected freeze/scope hashes, explicit 240/120/360-second profile, 2 starts, 512 MiB, one heavy operation and zero retries match. Scope is PREPARED_NOT_AUTHORIZED with execution_authorized=false. Existing bound preflight reports PREPARED, no blockers/active native processes, zero starts (hence zero tickets), NOT_RUN. No activation, stages or launch material found.

All 265 protected absolute-path originals and 207 previous originals resolved against previous_live_root match baseline hashes. Source snapshot has no extra files.

No candidate preparation, activation, preflight process, DCC launch or private-key read performed by this audit. Accounting facts rely on the existing completed preflight, not a new authenticated read. Exported keyless records do not transfer authorization. See JSON for all check results and source bindings.
