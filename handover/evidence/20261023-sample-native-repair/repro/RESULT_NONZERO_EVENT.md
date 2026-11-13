# Completed nonzero-selector comparison

The single authorized `0x1` tool operation ran in output -04. The new ordinary Python target PID 11162 reached its explicit ready event in 0.231752 seconds. Ready was bounded by the overall 120-second operation deadline with 18 seconds reserved for collection and cleanup, rather than the discarded separate 4-second startup cutoff. The original production 5-second tool and 16-second observation deadlines remained unchanged.

`/usr/bin/vmmap -w -interleaved 11162 0x1`, tool PID 11164, returned in 0.267653 seconds with exit code 0, stdout 443 bytes and empty complete stderr. It contains none of the five required identity fields: Process, Parent Process, Load Address, Launch Time, Target Type. Its first line states `0x1 is not in any region.  Bytes before following region: 4307058687`; its following-region row is `__TEXT 100b88000-100b8c000`, referencing the actual copied ordinary Python executable in -04.

The following-region row is not substituted for a main-image Load Address or identity header. Header validation therefore rejected the candidate result, and no actual-load-address follow-up ran. Address probes ended without scanning another selector or invoking sample again.

The target exited 0 after explicit event X and was reaped. The tool leader was reaped with no cleanup errors. Subsequent ps queries found no matching leaders; full descendant enumeration was not collected. Source bytes still matched the frozen original. Exact raw streams, stage/deadline timing, actual ps bytes and cleanup facts are preserved in `outputs/sample-native-repair-20261023-04/result.json` and referenced files. The earlier -01/-02/-03 output and evidence hashes were rechecked without changing their bytes.
