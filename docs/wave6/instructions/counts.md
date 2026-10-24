# Serverless command-scope instruction receipts

Named Tomo instructions including inlines, excluding external library callees and fixture glue. Totals are per batch; divide by batch for per-operation counts. Exact replies are asserted outside the counted region. Production namespace `tomo` runs databases=16 and `tomo_db0` runs databases=1. Eight CPUs, sixteen shards, split 6:2 or fused; read-local off, atomic=1 for plain commands. Default slowlog=10000 microseconds; off=-1. Synthetic clocks advance 1 microsecond per call, preventing debugger overhead from crossing the threshold.

| Runtime | Mode | Command | Batch | Threshold | PRE | Initial merge | POST | POST−PRE |
|---|---|---|---:|---:|---:|---:|---:|---:|
| normal | 1s | GET | 1 | -1 | 950 | 956 | 950 | 0 |
| normal | 1s | GET | 1 | 10000 | 1330 | 1339 | 1331 | 1 |
| normal | 1s | GET | 32 | -1 | 18930 | 19122 | 18930 | 0 |
| normal | 1s | GET | 32 | 10000 | 18966 | 19158 | 18966 | 0 |
| normal | 2s | GET | 1 | -1 | 1575 | 1577 | 1575 | 0 |
| normal | 2s | GET | 1 | 10000 | 1940 | 1945 | 1940 | 0 |
| normal | 2s | GET | 32 | -1 | 18935 | 18999 | 18935 | 0 |
| normal | 2s | GET | 32 | 10000 | 18971 | 19035 | 18971 | 0 |
| normal | 1s | SET | 1 | -1 | 1084 | 1090 | 1084 | 0 |
| normal | 1s | SET | 1 | 10000 | 1463 | 1472 | 1463 | 0 |
| normal | 1s | SET | 32 | -1 | 23218 | 23410 | 23218 | 0 |
| normal | 1s | SET | 32 | 10000 | 23254 | 23446 | 23254 | 0 |
| normal | 2s | SET | 1 | -1 | 1709 | 1711 | 1709 | 0 |
| normal | 2s | SET | 1 | 10000 | 2072 | 2077 | 2072 | 0 |
| normal | 2s | SET | 32 | -1 | 23223 | 23287 | 23223 | 0 |
| normal | 2s | SET | 32 | 10000 | 23259 | 23323 | 23259 | 0 |
| normal | 1s | INCR | 1 | -1 | 1547 | 1564 | 1547 | 0 |
| normal | 1s | INCR | 1 | 10000 | 1926 | 1946 | 1926 | 0 |
| normal | 1s | INCR | 32 | -1 | 38563 | 39107 | 38563 | 0 |
| normal | 1s | INCR | 32 | 10000 | 38599 | 39143 | 38599 | 0 |
| normal | 2s | INCR | 1 | -1 | 2172 | 2185 | 2172 | 0 |
| normal | 2s | INCR | 1 | 10000 | 2535 | 2551 | 2535 | 0 |
| normal | 2s | INCR | 32 | -1 | 38568 | 38984 | 38568 | 0 |
| normal | 2s | INCR | 32 | 10000 | 38604 | 39020 | 38604 | 0 |
| db0 | 1s | GET | 1 | -1 | 839 | 845 | 839 | 0 |
| db0 | 1s | GET | 1 | 10000 | 1219 | 1228 | 1220 | 1 |
| db0 | 1s | GET | 32 | -1 | 19377 | 19569 | 19377 | 0 |
| db0 | 1s | GET | 32 | 10000 | 19413 | 19605 | 19413 | 0 |
| db0 | 2s | GET | 1 | -1 | 1077 | 1079 | 1077 | 0 |
| db0 | 2s | GET | 1 | 10000 | 1442 | 1447 | 1442 | 0 |
| db0 | 2s | GET | 32 | -1 | 18995 | 19059 | 18995 | 0 |
| db0 | 2s | GET | 32 | 10000 | 19031 | 19095 | 19031 | 0 |
| db0 | 1s | SET | 1 | -1 | 971 | 977 | 971 | 0 |
| db0 | 1s | SET | 1 | 10000 | 1350 | 1359 | 1350 | 0 |
| db0 | 1s | SET | 32 | -1 | 23601 | 23793 | 23601 | 0 |
| db0 | 1s | SET | 32 | 10000 | 23637 | 23829 | 23637 | 0 |
| db0 | 2s | SET | 1 | -1 | 1209 | 1211 | 1209 | 0 |
| db0 | 2s | SET | 1 | 10000 | 1572 | 1577 | 1572 | 0 |
| db0 | 2s | SET | 32 | -1 | 23219 | 23283 | 23219 | 0 |
| db0 | 2s | SET | 32 | 10000 | 23255 | 23319 | 23255 | 0 |
| db0 | 1s | INCR | 1 | -1 | 1330 | 1347 | 1330 | 0 |
| db0 | 1s | INCR | 1 | 10000 | 1709 | 1729 | 1709 | 0 |
| db0 | 1s | INCR | 32 | -1 | 35618 | 36162 | 35618 | 0 |
| db0 | 1s | INCR | 32 | 10000 | 35654 | 36198 | 35654 | 0 |
| db0 | 2s | INCR | 1 | -1 | 1568 | 1581 | 1568 | 0 |
| db0 | 2s | INCR | 1 | 10000 | 1931 | 1947 | 1931 | 0 |
| db0 | 2s | INCR | 32 | -1 | 35236 | 35652 | 35236 | 0 |
| db0 | 2s | INCR | 32 | 10000 | 35272 | 35688 | 35272 | 0 |

MGET has eight keys on eight shards; totals include production scatter prepare, owner execution, completion and retirement.

| Runtime | Mode | Batch | Atomic | PRE | POST | POST−PRE |
|---|---|---:|---:|---:|---:|---:|
| normal | 1s | 1 | 0 | 10150 | 10182 | 32 |
| normal | 1s | 1 | 1 | 10171 | 10203 | 32 |
| normal | 1s | 8 | 0 | 80934 | 81190 | 256 |
| normal | 1s | 8 | 1 | 81102 | 81358 | 256 |
| normal | 2s | 1 | 0 | 10150 | 10182 | 32 |
| normal | 2s | 1 | 1 | 10171 | 10203 | 32 |
| normal | 2s | 8 | 0 | 80934 | 81190 | 256 |
| normal | 2s | 8 | 1 | 81102 | 81358 | 256 |
| db0 | 1s | 1 | 0 | 10301 | 10301 | 0 |
| db0 | 1s | 1 | 1 | 10322 | 10322 | 0 |
| db0 | 1s | 8 | 0 | 82142 | 82142 | 0 |
| db0 | 1s | 8 | 1 | 82310 | 82310 | 0 |
| db0 | 2s | 1 | 0 | 10301 | 10301 | 0 |
| db0 | 2s | 1 | 1 | 10322 | 10322 | 0 |
| db0 | 2s | 8 | 0 | 82142 | 82142 | 0 |
| db0 | 2s | 8 | 1 | 82310 | 82310 | 0 |

The two +1 plain cells are the exact-timed fused GET branch layout, in both namespaces. All other plain command totals equal PRE. The +32 MGET singleton / +256 batch-eight totals are the accepted notifycompat owner-scatter change (four instructions per key); DB0 MGET is unchanged.

SV4.14’s below-threshold recorder helper is 75 instructions on PRE and POST, versus 78 in the initial merge. The ordinary EXEC dispatch overhead (+6 in fused / +2 in split initially) is removed by outlining the retry insertion and unit-only AOF/promoter frame.
