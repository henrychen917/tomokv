# Final ordinary-command scopes

48 PRE/POST pairs; 24 equal, 24 lower, zero increases. Counts are executed
instructions in named production routines, with clock calls stubbed. Library
callees outside those routines and fixture glue are excluded. These are bounded
correctness traces, not rates. Every fixture checks exact replies and data.
GET/SET/INCR use the linked production executor batch entry; MGET/MSET use
eight-shard preparation, owner execution, completion and retirement.

PRE: 7ae703778; POST production source: f7204660e. Probe hashes are in each
trace JSON and the four build receipts. A cached trace is reused only when its
probe SHA-256 matches. tools/at412_artifacts.py scope asserts all 48 deltas <= 0.

| Namespace | Command | Mode | Atomic | Batch | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|---:|
| normal | GET | 1s | 1 | 1 | 949 | 949 | +0 |
| normal | GET | 1s | 1 | 32 | 18,898 | 18,898 | +0 |
| normal | GET | 2s | 1 | 1 | 1,575 | 1,575 | +0 |
| normal | GET | 2s | 1 | 32 | 18,935 | 18,935 | +0 |
| normal | SET | 1s | 1 | 1 | 1,078 | 1,078 | +0 |
| normal | SET | 1s | 1 | 32 | 23,026 | 23,026 | +0 |
| normal | SET | 2s | 1 | 1 | 1,704 | 1,704 | +0 |
| normal | SET | 2s | 1 | 32 | 23,063 | 23,063 | +0 |
| normal | INCR | 1s | 1 | 1 | 1,541 | 1,541 | +0 |
| normal | INCR | 1s | 1 | 32 | 38,371 | 38,371 | +0 |
| normal | INCR | 2s | 1 | 1 | 2,167 | 2,167 | +0 |
| normal | INCR | 2s | 1 | 32 | 38,408 | 38,408 | +0 |
| normal | MGET | 1s | 1 | 1 | 10,243 | 10,204 | -39 |
| normal | MGET | 1s | 1 | 32 | 326,598 | 325,350 | -1,248 |
| normal | MGET | 2s | 1 | 1 | 10,243 | 10,204 | -39 |
| normal | MGET | 2s | 1 | 32 | 326,598 | 325,350 | -1,248 |
| normal | MSET | 1s | 0 | 1 | 10,894 | 10,841 | -53 |
| normal | MSET | 1s | 1 | 1 | 17,080 | 17,036 | -44 |
| normal | MSET | 1s | 0 | 32 | 348,453 | 346,757 | -1,696 |
| normal | MSET | 1s | 1 | 32 | 964,774 | 963,366 | -1,408 |
| normal | MSET | 2s | 0 | 1 | 10,690 | 10,659 | -31 |
| normal | MSET | 2s | 1 | 1 | 16,726 | 16,704 | -22 |
| normal | MSET | 2s | 0 | 32 | 341,925 | 340,933 | -992 |
| normal | MSET | 2s | 1 | 32 | 953,446 | 952,742 | -704 |
| db0 | GET | 1s | 1 | 1 | 828 | 828 | +0 |
| db0 | GET | 1s | 1 | 32 | 19,025 | 19,025 | +0 |
| db0 | GET | 2s | 1 | 1 | 1,067 | 1,067 | +0 |
| db0 | GET | 2s | 1 | 32 | 18,675 | 18,675 | +0 |
| db0 | SET | 1s | 1 | 1 | 965 | 965 | +0 |
| db0 | SET | 1s | 1 | 32 | 23,409 | 23,409 | +0 |
| db0 | SET | 2s | 1 | 1 | 1,204 | 1,204 | +0 |
| db0 | SET | 2s | 1 | 32 | 23,059 | 23,059 | +0 |
| db0 | INCR | 1s | 1 | 1 | 1,324 | 1,324 | +0 |
| db0 | INCR | 1s | 1 | 32 | 35,426 | 35,426 | +0 |
| db0 | INCR | 2s | 1 | 1 | 1,563 | 1,563 | +0 |
| db0 | INCR | 2s | 1 | 32 | 35,076 | 35,076 | +0 |
| db0 | MGET | 1s | 1 | 1 | 10,370 | 10,337 | -33 |
| db0 | MGET | 1s | 1 | 32 | 330,662 | 329,606 | -1,056 |
| db0 | MGET | 2s | 1 | 1 | 10,370 | 10,337 | -33 |
| db0 | MGET | 2s | 1 | 32 | 330,662 | 329,606 | -1,056 |
| db0 | MSET | 1s | 0 | 1 | 11,143 | 11,117 | -26 |
| db0 | MSET | 1s | 1 | 1 | 16,497 | 16,489 | -8 |
| db0 | MSET | 1s | 0 | 32 | 356,421 | 355,589 | -832 |
| db0 | MSET | 1s | 1 | 32 | 955,046 | 954,790 | -256 |
| db0 | MSET | 2s | 0 | 1 | 10,962 | 10,935 | -27 |
| db0 | MSET | 2s | 1 | 1 | 16,166 | 16,157 | -9 |
| db0 | MSET | 2s | 0 | 32 | 350,629 | 349,765 | -864 |
| db0 | MSET | 2s | 1 | 32 | 944,454 | 944,166 | -288 |
