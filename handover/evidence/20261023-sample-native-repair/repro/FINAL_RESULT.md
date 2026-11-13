# Bounded native collection findings

The known historical software -02 symbol-processing timeout was not reproduced. The sole original sample invocation returned within its unchanged deadline. None of the bounded address-selector alternatives supplied the complete five-field identity header, so this work establishes no production replacement or reliable full observation. Historical -09's precise `TOOL_FAILED` cause remains unknown.

| Output | Actual operation | Tool PID | Seconds | Exit | stdout / stderr bytes | Evidence outcome |
|---|---|---:|---:|---:|---:|---|
| -01 | `sample 6774 1 1000 -file /dev/stdout` | 6777 | 2.595271 | 0 | 63,348 / 188 | Original three progress lines completed; timeout not reproduced |
| -01 | `vmmap -w -interleaved 6774 0` | 6807 | 0.112795 | 255 | 0 / 1,285 | Bare zero rejected as unknown argument |
| -02 | `vmmap -w -interleaved 8115 0x00000000` | 8118 | 0.301968 | 1 | 0 / 1,300 | Hexadecimal zero rejected as bad address |
| -03 | No collection tool ran | — | — | — | — | Target did not reach the harness's separate 4-second ready cutoff; exited by TERM and reaped |
| -04 | `vmmap -w -interleaved 11162 0x1` | 11164 | 0.267653 | 0 | 443 / 0 | Five identity header fields absent; following region cannot replace them |

The tools used the original byte-identical `_run_tool` snapshot with its existing 5-second per-tool and 16-second caller boundaries. Trace-only observation preserved original tool bytes and recorded fixed argv, PID, stages, deadline source, raw stream lengths/prefixes, return codes, cleanup and actual external ps states. The final -04 ready event occurred after 0.231752 seconds within the 120-second operation boundary. No sample was repeated. No actual-load-address follow-up satisfied its prerequisite, so none ran.

All four ordinary Python target leaders and all invoked tool leaders were reaped. Targets -01/-02/-04 exited 0 through parent event X; -03's ready-cutoff cleanup sent X, reached a one-second wait timeout, then reaped SIGTERM exit -15. Full descendant enumeration was not collected. The ps `wchan` field identified no specific kernel wait. No permission, concurrency or symbol-cache cause is inferred.

This work changed no production source, did not run a complete `observe_process`, and started no real Houdini/hython/husk/Nuke/WorkBuddy/HY3, graph, rendering or candidate activation. Earlier candidate/failed-run files remained read-only. These findings do not establish DCC, engineering, visual, M1 or production acceptance.

Raw results are under `outputs/sample-native-repair-20261023-01` through `-04`. This evidence directory contains the finite plans, exact scripts, frozen production source, historical diagnostic reference, individual result reports and chained SHA-256 manifests.
