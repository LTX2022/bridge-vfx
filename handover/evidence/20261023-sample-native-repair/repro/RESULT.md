# Native collection reproduction result

The unique baseline did **not** reproduce software attempt -02's historical timeout. It does not establish reliable production collection or explain historical -09 `TOOL_FAILED`.

The ordinary Python 3.14 target PID was 6774. Its copied framework Mach-O SHA-256 was `2648494b3142426b61787e0a0d458bf24f29e8e0cf0182fa61f1f3e0cb2fde12`, identical to the old -02 expected executable. It loaded EXR/native_scope/owned_process modules and waited for an explicit parent pipe event during all collection. No DCC application, rendering or graph was started.

| Operation | Fixed argv | Tool PID | Elapsed | Exit | stdout | stderr | Result |
|---|---|---:|---:|---:|---:|---:|---|
| Original sample | `/usr/bin/sample 6774 1 1000 -file /dev/stdout` | 6777 | 2.595271 s | 0 | 63,348 B | 188 B | Returned under original 5-second tool deadline |
| Address-zero comparison | `/usr/bin/vmmap -w -interleaved 6774 0` | 6807 | 0.112795 s | 255 | 0 B | 1,285 B | Rejected: `[invalid usage]: unknown argument: 0` |

Both calls used an unchanged, exact production `_run_tool` snapshot with a 16-second caller boundary and the original 5-second tool boundary. `sys.settrace` observed locals without substituting tools, result bytes, OS functions, parsers or clocks. The baseline invoked only the sample operation from `_vmmap`, so no second sample or baseline addressed-vmmap operation occurred. This is not a complete `observe_process` run.

The sample stderr contains all three expected progress lines, including `Sampling completed, processing symbols...` and the final file-written line. The production stage passed through `read_pipes`, `wait`, `exit_status`. Per-progress-line arrival times were not recorded, so the duration of the symbol-processing substage is not established. Actual external `/bin/ps` snapshots observed tool statuses `Rs`, `Ss`, `Us`; `wchan` was `-`, which identifies no specific kernel wait. Those snapshots do not identify a permission or concurrency cause.

The address-zero comparison completed at `exit_status` with full stderr and a nonzero status. The actual-load-address follow-up was not run because its prerequisite failed. No option variant or command was retried.

Target ps snapshots before the baseline and after each call all showed the same live PID/PPID/process group. The target accepted parent event `X`, exited 0 and was reaped; both tool leaders were reaped with no cleanup errors. Post-cleanup ps queries returned no matching leader. Full process-group descendant enumeration was not collected; no stronger descendant-stop claim is made.

Current source remained byte-identical to the frozen source after collection. All original candidates and failed runs were read-only. The result, raw streams, prefix/count/hash data, tool stage/deadline times and actual ps bytes are in `outputs/sample-native-repair-20261023-01/result.json` and its referenced binary files. The plan, executable scripts, exact source snapshot, old signed-diagnostic reference and manifest are in this evidence directory.
