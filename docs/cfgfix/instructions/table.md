# Command-scope instruction census

PRE `97f0d76e3782485ae2e2f797805484ef09eb52752a5019935d1bc409d4fb4fd1`; POST `ce784365c3693d2582e417dd3f3098b79e81450d1e9c90cc687323138b2009c3`.

Serverless complete production command scope; excludes libc/kernel time and explicitly records clock/library calls. This is instruction accounting, not a cycles, IPC, latency or throughput result.

| Namespace | Command | Mode | Batch | Atomic | PRE | POST | Delta |
|---|---|---|---|---|---:|---:|---:|
| db0 | GET | 1s | 1 | 1 | 783 | 783 | 0 |
| db0 | GET | 1s | 32 | 1 | 17585 | 17585 | 0 |
| db0 | GET | 2s | 1 | 1 | 1016 | 1016 | 0 |
| db0 | GET | 2s | 32 | 1 | 17043 | 17043 | 0 |
| db0 | INCR | 1s | 1 | 1 | 1269 | 1269 | 0 |
| db0 | INCR | 1s | 32 | 1 | 33666 | 33666 | 0 |
| db0 | INCR | 2s | 1 | 1 | 1502 | 1502 | 0 |
| db0 | INCR | 2s | 32 | 1 | 33124 | 33124 | 0 |
| db0 | MGET | 1s | 1 | 1 | 9981 | 9980 | -1 |
| db0 | MGET | 1s | 32 | 1 | 318214 | 318182 | -32 |
| db0 | MGET | 2s | 1 | 1 | 9981 | 9980 | -1 |
| db0 | MGET | 2s | 32 | 1 | 318214 | 318182 | -32 |
| db0 | MSET | 1s | 1 | 0 | 10747 | 10746 | -1 |
| db0 | MSET | 1s | 1 | 1 | 16295 | 16295 | 0 |
| db0 | MSET | 1s | 32 | 0 | 343749 | 343717 | -32 |
| db0 | MSET | 1s | 32 | 1 | 896750 | 896750 | 0 |
| db0 | MSET | 2s | 1 | 0 | 10565 | 10564 | -1 |
| db0 | MSET | 2s | 1 | 1 | 15963 | 15963 | 0 |
| db0 | MSET | 2s | 32 | 0 | 337925 | 337893 | -32 |
| db0 | MSET | 2s | 32 | 1 | 886126 | 886126 | 0 |
| db0 | SET | 1s | 1 | 1 | 926 | 926 | 0 |
| db0 | SET | 1s | 32 | 1 | 22161 | 22161 | 0 |
| db0 | SET | 2s | 1 | 1 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 32 | 1 | 21619 | 21619 | 0 |
| normal | GET | 1s | 1 | 1 | 936 | 936 | 0 |
| normal | GET | 1s | 32 | 1 | 18482 | 18482 | 0 |
| normal | GET | 2s | 1 | 1 | 1556 | 1556 | 0 |
| normal | GET | 2s | 32 | 1 | 18327 | 18327 | 0 |
| normal | INCR | 1s | 1 | 1 | 1511 | 1511 | 0 |
| normal | INCR | 1s | 32 | 1 | 37411 | 37411 | 0 |
| normal | INCR | 2s | 1 | 1 | 2131 | 2131 | 0 |
| normal | INCR | 2s | 32 | 1 | 37256 | 37256 | 0 |
| normal | MGET | 1s | 1 | 1 | 10167 | 10167 | 0 |
| normal | MGET | 1s | 32 | 1 | 324166 | 324166 | 0 |
| normal | MGET | 2s | 1 | 1 | 10167 | 10167 | 0 |
| normal | MGET | 2s | 32 | 1 | 324166 | 324166 | 0 |
| normal | MSET | 1s | 1 | 0 | 10682 | 10682 | 0 |
| normal | MSET | 1s | 1 | 1 | 16947 | 16947 | 0 |
| normal | MSET | 1s | 32 | 0 | 341669 | 341669 | 0 |
| normal | MSET | 1s | 32 | 1 | 960766 | 960766 | 0 |
| normal | MSET | 2s | 1 | 0 | 10500 | 10500 | 0 |
| normal | MSET | 2s | 1 | 1 | 16615 | 16615 | 0 |
| normal | MSET | 2s | 32 | 0 | 335845 | 335845 | 0 |
| normal | MSET | 2s | 32 | 1 | 950142 | 950142 | 0 |
| normal | SET | 1s | 1 | 1 | 1060 | 1060 | 0 |
| normal | SET | 1s | 32 | 1 | 22450 | 22450 | 0 |
| normal | SET | 2s | 1 | 1 | 1680 | 1680 | 0 |
| normal | SET | 2s | 32 | 1 | 22295 | 22295 | 0 |
