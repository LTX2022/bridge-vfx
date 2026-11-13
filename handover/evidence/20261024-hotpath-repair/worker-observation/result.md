# Approved single-point test synchronization

Changed only tests/unit/test_graph_job_recovery.py in test_native_child_wait_transport_keeps_real_supervisor_and_completion: join the actual controller thread for the existing service._remaining_seconds(service._row(operation)), then fail if alive. The generic helper, adversarial tests, production budgets/deadlines and all later success/signed-stop/slot/node-count assertions are unchanged. No sleep or additional shutdown allowance.

Validation ran once on a fresh copy of the previously fixed runtime snapshot, replacing only the changed test. The selected test passed; see test.log for measured duration. Snapshot manifest SHA256 f7edeac319cb214fc77bcef9a02acaa97455a4c0c94f4004ca74190f6c8a62c4; runtime_fingerprint 9e46efbd529595aa493f3368f3e50b39a76283cf0cf38ceea7349aa08f328a1d; changed test SHA256 ba7eee797ecf2355009afbda8ffe5c5dd4f8d21e3873ad239661ade2b95d945c. No manifested source file changed during execution.

This is the controlled Python process boundary only. It is not a test of A's later in-progress project-environment build, a native DCC or performance acceptance. No registry coverage is added by this selected case.
