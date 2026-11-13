# Hexadecimal-zero comparison result

The additional explicitly authorized format comparison also failed closed. `/usr/bin/vmmap -w -interleaved 8115 0x00000000` (tool PID 8118) completed in 0.301968 seconds with exit code 1, stdout 0 bytes and complete stderr 1,300 bytes. Its first line is `[invalid usage]: bad address '0x00000000' specified`.

This establishes rejection of zero as an address by this installed vmmap. It does not establish that nonzero address filtering fails. No actual-load-address operation followed because the required successful five-field header was absent.

The new ordinary Python 3.14 target PID 8115 loaded the same module set and remained alive through collection. It exited 0 after parent event `X` and was reaped without cleanup errors. The tool leader was reaped without cleanup errors; post-cleanup ps found no matching leaders. Full descendant enumeration was not collected.

The unchanged production `_run_tool` retained its 5-second tool and 16-second caller boundary. Its failure stage was `exit_status`, not `read_pipes` timeout. Trace-only data and raw streams are preserved in `outputs/sample-native-repair-20261023-02/result.json` and referenced binary files. The source snapshot still matched current production source at the end of this comparison.

Across both authorized runs there was exactly one sample invocation and two distinct vmmap zero-address comparisons. The sample returned successfully in 2.595271 seconds, so the known historical software -02 symbol-processing timeout was not reproduced. Historical -09's precise `TOOL_FAILED` cause remains unknown. No production repair, full `observe_process` success, DCC, engineering-closure, visual or production acceptance is established.

The first output directory and its original evidence files remained byte-identical against `sha256-manifest.json`; the separate `hex-zero-sha256-manifest.json` binds the added plan, script, report, logs and second output without rewriting that original manifest.
