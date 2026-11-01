# Command-scope instruction counts

All 64 ordinary-command pairs have POST <= PRE (zero added instructions). Counts are totals per bounded scope, not cycles, IPC or throughput. Read-local is 0 and no blocking waiters are installed. Both production namespaces and both thread modes are linked from the recorded server objects. MSET covers atomic 0 and 1; the other ordinary commands use atomic 1.

Local EVAL executes INCR; cross-owner EVAL executes GET and SET on two shards. EXEC includes MULTI, queued INCR commands, execution and retirement. EXEC-cross cycles over eight shards; at one child its placement is necessarily local. The script tracer enters Lua without counting Lua instructions, so callbacks into Tomo are included. External library instructions and fixture glue are excluded. Exact replies are asserted.

Build metadata records fixture and server SHA-256s. Individual JSON files in `instruction-receipts.tar.gz` record instruction counts by function and the traced executable SHA; their log tails record completion and the discarded full trace SHA. `comparison.json` contains the 64 ordinary pairs; `scripts-comparison.json` contains the 44 script/EXEC pairs. Rejected compilation trials and earlier incomplete script traces remain separately named and are not included in these tables.

## Ordinary commands

| Namespace | Command | Atomic | Mode | Batch/children | PRE | POST | Added |
|---|---|---:|---|---:|---:|---:|---:|
| db0 | GET | 1 | 1s | 1 | 783 | 783 | 0 |
| db0 | GET | 1 | 1s | 32 | 17585 | 17585 | 0 |
| db0 | GET | 1 | 2s | 1 | 1016 | 1016 | 0 |
| db0 | GET | 1 | 2s | 32 | 17043 | 17043 | 0 |
| db0 | INCR | 1 | 1s | 1 | 1269 | 1244 | -25 |
| db0 | INCR | 1 | 1s | 32 | 33666 | 32866 | -800 |
| db0 | INCR | 1 | 2s | 1 | 1502 | 1477 | -25 |
| db0 | INCR | 1 | 2s | 32 | 33124 | 32324 | -800 |
| db0 | LPUSH | 1 | 1s | 1 | 2800 | 2778 | -22 |
| db0 | LPUSH | 1 | 1s | 32 | 56843 | 56139 | -704 |
| db0 | LPUSH | 1 | 2s | 1 | 3033 | 3011 | -22 |
| db0 | LPUSH | 1 | 2s | 32 | 56301 | 55597 | -704 |
| db0 | MGET | 1 | 1s | 1 | 9990 | 9958 | -32 |
| db0 | MGET | 1 | 1s | 32 | 318502 | 317478 | -1024 |
| db0 | MGET | 1 | 2s | 1 | 9990 | 9958 | -32 |
| db0 | MGET | 1 | 2s | 32 | 318502 | 317478 | -1024 |
| db0 | MSET | 0 | 1s | 1 | 10748 | 10659 | -89 |
| db0 | MSET | 0 | 1s | 32 | 343781 | 340933 | -2848 |
| db0 | MSET | 0 | 2s | 1 | 10566 | 10462 | -104 |
| db0 | MSET | 0 | 2s | 32 | 337957 | 334629 | -3328 |
| db0 | MSET | 1 | 1s | 1 | 16306 | 16276 | -30 |
| db0 | MSET | 1 | 1s | 32 | 897102 | 894158 | -2944 |
| db0 | MSET | 1 | 2s | 1 | 15974 | 15929 | -45 |
| db0 | MSET | 1 | 2s | 32 | 886478 | 883054 | -3424 |
| db0 | RPUSH | 1 | 1s | 1 | 2638 | 2616 | -22 |
| db0 | RPUSH | 1 | 1s | 32 | 43410 | 42706 | -704 |
| db0 | RPUSH | 1 | 2s | 1 | 2871 | 2849 | -22 |
| db0 | RPUSH | 1 | 2s | 32 | 42868 | 42164 | -704 |
| db0 | SET | 1 | 1s | 1 | 926 | 894 | -32 |
| db0 | SET | 1 | 1s | 32 | 22161 | 21137 | -1024 |
| db0 | SET | 1 | 2s | 1 | 1159 | 1127 | -32 |
| db0 | SET | 1 | 2s | 32 | 21619 | 20595 | -1024 |
| normal | GET | 1 | 1s | 1 | 936 | 936 | 0 |
| normal | GET | 1 | 1s | 32 | 18482 | 18482 | 0 |
| normal | GET | 1 | 2s | 1 | 1556 | 1556 | 0 |
| normal | GET | 1 | 2s | 32 | 18327 | 18327 | 0 |
| normal | INCR | 1 | 1s | 1 | 1511 | 1484 | -27 |
| normal | INCR | 1 | 1s | 32 | 37411 | 36547 | -864 |
| normal | INCR | 1 | 2s | 1 | 2131 | 2104 | -27 |
| normal | INCR | 1 | 2s | 32 | 37256 | 36392 | -864 |
| normal | LPUSH | 1 | 1s | 1 | 3064 | 3043 | -21 |
| normal | LPUSH | 1 | 1s | 32 | 58130 | 57427 | -703 |
| normal | LPUSH | 1 | 2s | 1 | 3684 | 3663 | -21 |
| normal | LPUSH | 1 | 2s | 32 | 57975 | 57272 | -703 |
| normal | MGET | 1 | 1s | 1 | 10171 | 10171 | 0 |
| normal | MGET | 1 | 1s | 32 | 324294 | 324294 | 0 |
| normal | MGET | 1 | 2s | 1 | 10171 | 10171 | 0 |
| normal | MGET | 1 | 2s | 32 | 324294 | 324294 | 0 |
| normal | MSET | 0 | 1s | 1 | 10680 | 10593 | -87 |
| normal | MSET | 0 | 1s | 32 | 341605 | 338821 | -2784 |
| normal | MSET | 0 | 2s | 1 | 10498 | 10411 | -87 |
| normal | MSET | 0 | 2s | 32 | 335781 | 332997 | -2784 |
| normal | MSET | 1 | 1s | 1 | 16947 | 16942 | -5 |
| normal | MSET | 1 | 1s | 32 | 960766 | 960606 | -160 |
| normal | MSET | 1 | 2s | 1 | 16615 | 16610 | -5 |
| normal | MSET | 1 | 2s | 32 | 950142 | 949982 | -160 |
| normal | RPUSH | 1 | 1s | 1 | 2902 | 2881 | -21 |
| normal | RPUSH | 1 | 1s | 32 | 44697 | 43994 | -703 |
| normal | RPUSH | 1 | 2s | 1 | 3522 | 3501 | -21 |
| normal | RPUSH | 1 | 2s | 32 | 44542 | 43839 | -703 |
| normal | SET | 1 | 1s | 1 | 1060 | 1027 | -33 |
| normal | SET | 1 | 1s | 32 | 22450 | 21394 | -1056 |
| normal | SET | 1 | 2s | 1 | 1680 | 1647 | -33 |
| normal | SET | 1 | 2s | 32 | 22295 | 21239 | -1056 |

## Script and EXEC paths

| Namespace | Command | Atomic | Mode | Batch/children | PRE | POST | Added |
|---|---|---:|---|---:|---:|---:|---:|
| db0 | EVAL | 1 | 1s | 1 | 27971 | 27987 | 16 |
| db0 | EVAL | 1 | 2s | 1 | 28000 | 28116 | 116 |
| db0 | EVAL-local | 1 | 1s | 1 | 3482 | 3510 | 28 |
| db0 | EVAL-local | 1 | 1s | 32 | 105489 | 106385 | 896 |
| db0 | EVAL-local | 1 | 2s | 1 | 3715 | 3839 | 124 |
| db0 | EVAL-local | 1 | 2s | 32 | 104947 | 108915 | 3968 |
| db0 | EXEC | 0 | 1s | 1 | 22064 | 22004 | -60 |
| db0 | EXEC | 0 | 1s | 32 | 174798 | 173974 | -824 |
| db0 | EXEC | 0 | 2s | 1 | 22018 | 21956 | -62 |
| db0 | EXEC | 0 | 2s | 32 | 174256 | 173430 | -826 |
| db0 | EXEC | 1 | 1s | 1 | 22064 | 22004 | -60 |
| db0 | EXEC | 1 | 1s | 32 | 174798 | 173974 | -824 |
| db0 | EXEC | 1 | 2s | 1 | 22018 | 21956 | -62 |
| db0 | EXEC | 1 | 2s | 32 | 174256 | 173430 | -826 |
| db0 | EXEC-cross | 0 | 1s | 1 | 22064 | 22004 | -60 |
| db0 | EXEC-cross | 0 | 1s | 32 | 210100 | 208961 | -1139 |
| db0 | EXEC-cross | 0 | 2s | 1 | 22018 | 21956 | -62 |
| db0 | EXEC-cross | 0 | 2s | 32 | 206354 | 205213 | -1141 |
| db0 | EXEC-cross | 1 | 1s | 1 | 22064 | 22004 | -60 |
| db0 | EXEC-cross | 1 | 1s | 32 | 210100 | 208961 | -1139 |
| db0 | EXEC-cross | 1 | 2s | 1 | 22018 | 21956 | -62 |
| db0 | EXEC-cross | 1 | 2s | 32 | 206354 | 205213 | -1141 |
| normal | EVAL | 1 | 1s | 1 | 30703 | 30755 | 52 |
| normal | EVAL | 1 | 2s | 1 | 30728 | 30876 | 148 |
| normal | EVAL-local | 1 | 1s | 1 | 3897 | 3924 | 27 |
| normal | EVAL-local | 1 | 1s | 32 | 114774 | 115638 | 864 |
| normal | EVAL-local | 1 | 2s | 1 | 4517 | 4640 | 123 |
| normal | EVAL-local | 1 | 2s | 32 | 114619 | 118555 | 3936 |
| normal | EXEC | 0 | 1s | 1 | 23325 | 23309 | -16 |
| normal | EXEC | 0 | 1s | 32 | 186817 | 186677 | -140 |
| normal | EXEC | 0 | 2s | 1 | 23250 | 23264 | 14 |
| normal | EXEC | 0 | 2s | 32 | 185347 | 186167 | 820 |
| normal | EXEC | 1 | 1s | 1 | 23325 | 23309 | -16 |
| normal | EXEC | 1 | 1s | 32 | 186817 | 186677 | -140 |
| normal | EXEC | 1 | 2s | 1 | 23250 | 23264 | 14 |
| normal | EXEC | 1 | 2s | 32 | 185347 | 186167 | 820 |
| normal | EXEC-cross | 0 | 1s | 1 | 23325 | 23309 | -16 |
| normal | EXEC-cross | 0 | 1s | 32 | 223679 | 223476 | -203 |
| normal | EXEC-cross | 0 | 2s | 1 | 23250 | 23264 | 14 |
| normal | EXEC-cross | 0 | 2s | 32 | 219005 | 219762 | 757 |
| normal | EXEC-cross | 1 | 1s | 1 | 23325 | 23309 | -16 |
| normal | EXEC-cross | 1 | 1s | 32 | 223679 | 223476 | -203 |
| normal | EXEC-cross | 1 | 2s | 1 | 23250 | 23264 | 14 |
| normal | EXEC-cross | 1 | 2s | 32 | 219005 | 219762 | 757 |
