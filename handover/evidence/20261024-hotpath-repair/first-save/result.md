# First-save worker implementation

Completed: graph_job_worker.py prepares the service-derived fresh operation HIP path after compilation, evidence/runtime/process validation and addon load, before the first lease/scene identity. The existing scheduler operation transaction fences setName and exact path readback; original wall/monotonic budgets are checked on both sides. owned_file rejects escaping/symlink paths, existing targets and missing parents are rejected, and the target must remain absent after naming. Save reuses the returned path with another fresh-path check. No deadline reset, scene epoch mutation, RPC, load/save during preparation, or new startup checkpoints.

software_host_client already provides memory-only setName and was not changed in this task. New direct tests: test_graph_worker_project_path.py. Only the two existing positive/reconciliation worker tests in test_graph_jobs.py received explicit bottom-native hou.hipFile wiring; original assertions remain.

Validation: Python 3.11 -I -B, cleared PYTHONPATH, cwd/TMPDIR /private/tmp. Combined direct path tests, startup diagnostics and GraphJobWorkerTests: 17 tests PASS in 31.934s (core-tests.log). AST confirms the same 18 ordered checkpoint calls. Current software_host_client bytes equal the task's before snapshot. sha256.txt covers the combined timing/fixture/first-save owned files; implementation.patch is relative to first-save before bytes.

Boundary: direct call-order tests explicitly stub validation and stop at the first lease; the existing worker tests exercise compile/build/save/reopen through their explicit bottom API boundary. Full strict first-save producer contract tests belong to A's owned-reopen fixture work. No native DCC or performance acceptance claimed.
