Instructions per bounded batch; PRE = POST in every entry. Atomic 1 except the explicit MSET a0 column.

| Namespace | Mode | Batch | GET | SET | INCR | MGET (8 keys) | MSET a0 (8 keys) | MSET a1 (8 keys) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| normal | 1s | 1 | 939 | 1068 | 1531 | 10243 | 10894 | 17080 |
| normal | 1s | 32 | 18578 | 22706 | 38051 | 326598 | 348453 | 964774 |
| normal | 2s | 1 | 1559 | 1688 | 2151 | 10243 | 10690 | 16726 |
| normal | 2s | 32 | 18423 | 22551 | 37896 | 326598 | 341925 | 953446 |
| db0 | 1s | 1 | 818 | 955 | 1314 | 10370 | 11143 | 16497 |
| db0 | 1s | 32 | 18705 | 23089 | 35106 | 330662 | 356421 | 955046 |
| db0 | 2s | 1 | 1051 | 1188 | 1547 | 10370 | 10962 | 16166 |
| db0 | 2s | 32 | 18163 | 22547 | 34564 | 330662 | 350629 | 944454 |

No listener, IO engine, worker threads, rate or timing measurement. Counts cover linked production owner/scatter routines, including NOPs and inlined code; setup, fixture glue and external library bodies are excluded. External-call counts also agree. Clocks use the established deterministic stub. Exact result assertions must pass. Read-local is 0, slowlog is -1, balancing/flip are off. A separate GDB single-step implementation agrees on every function count in all 96 PRE/POST traces.
