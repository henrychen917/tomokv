# Serverless command-scope instruction counts

Exact named TomoKV instructions per batch; setup, verification and external library bodies excluded. Divide by batch for per-command counts (also stored in comparison.json). Every cell verifies its exact reply and resulting data. Read-local, FLIP, balancing and maxmemory are off. Plain commands use the production executor entry; multi-key commands use the production eight-shard scatter chain with group completion and retirement. The 32-command scatter batch repeats completed groups, not an overlapped parser pipeline. Clock reads return deterministic timestamps to keep debugger pauses out of slowlog selection. These counts do not measure throughput, cycles, IPC, parsing, network or queueing.

Each cell is PRE → POST (difference). Runtime normal uses 16 databases; db0 uses the single-database compile.

| Command | Batch | Slowlog µs | normal 1s | normal 2s | db0 1s | db0 2s |
|---|---:|---:|---:|---:|---:|---:|
| GET | 1 | -1 | 949 → 939 (-10) | 1575 → 1559 (-16) | 828 → 818 (-10) | 1067 → 1051 (-16) |
| GET | 1 | 10000 | 1330 → 1297 (-33) | 1940 → 1924 (-16) | 1209 → 1174 (-35) | 1432 → 1416 (-16) |
| GET | 32 | -1 | 18898 → 18578 (-320) | 18935 → 18423 (-512) | 19025 → 18705 (-320) | 18675 → 18163 (-512) |
| GET | 32 | 10000 | 18934 → 18650 (-284) | 18971 → 18459 (-512) | 19061 → 18773 (-288) | 18711 → 18199 (-512) |
| SET | 1 | -1 | 1078 → 1068 (-10) | 1704 → 1688 (-16) | 965 → 955 (-10) | 1204 → 1188 (-16) |
| SET | 1 | 10000 | 1457 → 1425 (-32) | 2067 → 2051 (-16) | 1344 → 1310 (-34) | 1567 → 1551 (-16) |
| SET | 32 | -1 | 23026 → 22706 (-320) | 23063 → 22551 (-512) | 23409 → 23089 (-320) | 23059 → 22547 (-512) |
| SET | 32 | 10000 | 23062 → 22778 (-284) | 23099 → 22587 (-512) | 23445 → 23157 (-288) | 23095 → 22583 (-512) |
| INCR | 1 | -1 | 1541 → 1531 (-10) | 2167 → 2151 (-16) | 1324 → 1314 (-10) | 1563 → 1547 (-16) |
| INCR | 1 | 10000 | 1920 → 1888 (-32) | 2530 → 2514 (-16) | 1703 → 1669 (-34) | 1926 → 1910 (-16) |
| INCR | 32 | -1 | 38371 → 38051 (-320) | 38408 → 37896 (-512) | 35426 → 35106 (-320) | 35076 → 34564 (-512) |
| INCR | 32 | 10000 | 38407 → 38123 (-284) | 38444 → 37932 (-512) | 35462 → 35174 (-288) | 35112 → 34600 (-512) |

All 48 plain cells add zero instructions. GET/SET handler identity and all shared executor/scatter differences are retained in the linked-body inventory. Smaller totals reflect helper inlining; they are not throughput claims.

| Command, 8 keys | Batch | Atomic | normal 1s | normal 2s | db0 1s | db0 2s |
|---|---:|---:|---:|---:|---:|---:|
| MGET | 1 | 1 | 10243 → 10243 (+0) | 10243 → 10243 (+0) | 10370 → 10370 (+0) | 10370 → 10370 (+0) |
| MGET | 32 | 1 | 326598 → 326598 (+0) | 326598 → 326598 (+0) | 330662 → 330662 (+0) | 330662 → 330662 (+0) |
| MSET | 1 | 0 | 10894 → 10894 (+0) | 10690 → 10690 (+0) | 11143 → 11143 (+0) | 10962 → 10962 (+0) |
| MSET | 1 | 1 | 17080 → 17080 (+0) | 16726 → 16726 (+0) | 16497 → 16497 (+0) | 16166 → 16166 (+0) |
| MSET | 32 | 0 | 348453 → 348453 (+0) | 341925 → 341925 (+0) | 356421 → 356421 (+0) | 350629 → 350629 (+0) |
| MSET | 32 | 1 | 964774 → 964774 (+0) | 953446 → 953446 (+0) | 955046 → 955046 (+0) | 944454 → 944454 (+0) |

Per-function and excluded library-call changes are retained in comparison.json. External library call counts match in all 72 cells; the retained raw excluded-target differences are only the fixture callback PRE/POST path names. There is no assertion that equal named instruction totals imply equal cycles or rate.
