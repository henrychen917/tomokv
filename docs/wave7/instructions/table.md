# Serverless command-scope instruction counts

Exact named TomoKV instructions per batch; setup, verification and external library bodies excluded. Divide by batch for per-command counts (also stored in comparison.json). Every cell verifies its exact reply and resulting data. Read-local, FLIP, balancing and maxmemory are off. Plain commands use the production executor entry; multi-key commands use the production eight-shard scatter chain with group completion and retirement. The eight-command scatter batch repeats completed groups, not an overlapped parser pipeline. Clock reads return deterministic timestamps to keep debugger pauses out of slowlog selection. These counts do not measure throughput, cycles, IPC, parsing, network or queueing.

Each cell is PRE → POST (difference). Runtime normal uses 16 databases; db0 uses the single-database compile.

| Command | Batch | Slowlog µs | normal 1s | normal 2s | db0 1s | db0 2s |
|---|---:|---:|---:|---:|---:|---:|
| GET | 1 | -1 | 950 → 949 (-1) | 1575 → 1575 (+0) | 839 → 828 (-11) | 1077 → 1067 (-10) |
| GET | 1 | 10000 | 1330 → 1330 (+0) | 1940 → 1940 (+0) | 1219 → 1209 (-10) | 1442 → 1432 (-10) |
| GET | 32 | -1 | 18930 → 18898 (-32) | 18935 → 18935 (+0) | 19377 → 19025 (-352) | 18995 → 18675 (-320) |
| GET | 32 | 10000 | 18966 → 18934 (-32) | 18971 → 18971 (+0) | 19413 → 19061 (-352) | 19031 → 18711 (-320) |
| SET | 1 | -1 | 1084 → 1078 (-6) | 1709 → 1704 (-5) | 971 → 965 (-6) | 1209 → 1204 (-5) |
| SET | 1 | 10000 | 1462 → 1457 (-5) | 2072 → 2067 (-5) | 1349 → 1344 (-5) | 1572 → 1567 (-5) |
| SET | 32 | -1 | 23218 → 23026 (-192) | 23223 → 23063 (-160) | 23601 → 23409 (-192) | 23219 → 23059 (-160) |
| SET | 32 | 10000 | 23254 → 23062 (-192) | 23259 → 23099 (-160) | 23637 → 23445 (-192) | 23255 → 23095 (-160) |
| INCR | 1 | -1 | 1547 → 1541 (-6) | 2172 → 2167 (-5) | 1330 → 1324 (-6) | 1568 → 1563 (-5) |
| INCR | 1 | 10000 | 1925 → 1920 (-5) | 2535 → 2530 (-5) | 1708 → 1703 (-5) | 1931 → 1926 (-5) |
| INCR | 32 | -1 | 38563 → 38371 (-192) | 38568 → 38408 (-160) | 35618 → 35426 (-192) | 35236 → 35076 (-160) |
| INCR | 32 | 10000 | 38599 → 38407 (-192) | 38604 → 38444 (-160) | 35654 → 35462 (-192) | 35272 → 35112 (-160) |

All 48 plain cells add zero instructions. The unarmed SET body is identical to headline and no WATCH callback or key lookup executes on these no-watcher paths.

| Command, 8 keys | Batch | Atomic | normal 1s | normal 2s | db0 1s | db0 2s |
|---|---:|---:|---:|---:|---:|---:|
| MGET | 1 | 0 | 10182 → 10222 (+40) | 10182 → 10222 (+40) | 10301 → 10349 (+48) | 10301 → 10349 (+48) |
| MGET | 1 | 1 | 10203 → 10243 (+40) | 10203 → 10243 (+40) | 10322 → 10370 (+48) | 10322 → 10370 (+48) |
| MGET | 8 | 0 | 81190 → 81510 (+320) | 81190 → 81510 (+320) | 82142 → 82526 (+384) | 82142 → 82526 (+384) |
| MGET | 8 | 1 | 81358 → 81678 (+320) | 81358 → 81678 (+320) | 82310 → 82694 (+384) | 82310 → 82694 (+384) |
| MSET | 1 | 0 | 10854 → 10894 (+40) | 10650 → 10690 (+40) | 11095 → 11143 (+48) | 10914 → 10962 (+48) |
| MSET | 1 | 1 | 17024 → 17080 (+56) | 16670 → 16726 (+56) | 16457 → 16497 (+40) | 16126 → 16166 (+40) |
| MSET | 8 | 0 | 86797 → 87117 (+320) | 85165 → 85485 (+320) | 88725 → 89109 (+384) | 87277 → 87661 (+384) |
| MSET | 8 | 1 | 161490 → 161938 (+448) | 158658 → 159106 (+448) | 157626 → 157946 (+320) | 154978 → 155298 (+320) |

Per-function and excluded library-call changes are retained in comparison.json. External library call counts match in all 80 cells; the retained raw excluded-target differences are only the fixture callback PRE/POST path names. There is no assertion that equal named instruction totals imply equal cycles or rate.
