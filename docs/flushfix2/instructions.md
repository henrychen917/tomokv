# Serverless command-scope instructions

PRE is `393d6ceb1`; POST production source is `34a2fa295`. These are executed instructions in named TomoKV bodies, including NOPs, excluding library callees and fixture glue. Counts cover the complete fixture scope at the listed batch size. They are not throughput or cycle measurements. Both images use read-local=0; the fixture cannot exercise the connection-side lane.

All 80 ordinary comparisons have zero added instructions (delta <= 0). Raw per-symbol counts and fixture/probe hashes are in `counts/`.

| Image | Command | Mode | Batch | Atomic | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|---:|
| normal | GET | 1s | 1 | 0 | 936 | 936 | 0 |
| normal | GET | 1s | 1 | 1 | 936 | 936 | 0 |
| normal | GET | 1s | 32 | 0 | 18482 | 18482 | 0 |
| normal | GET | 1s | 32 | 1 | 18482 | 18482 | 0 |
| normal | GET | 2s | 1 | 0 | 1556 | 1556 | 0 |
| normal | GET | 2s | 1 | 1 | 1556 | 1556 | 0 |
| normal | GET | 2s | 32 | 0 | 18327 | 18327 | 0 |
| normal | GET | 2s | 32 | 1 | 18327 | 18327 | 0 |
| normal | SET | 1s | 1 | 0 | 1060 | 1060 | 0 |
| normal | SET | 1s | 1 | 1 | 1060 | 1060 | 0 |
| normal | SET | 1s | 32 | 0 | 22450 | 22450 | 0 |
| normal | SET | 1s | 32 | 1 | 22450 | 22450 | 0 |
| normal | SET | 2s | 1 | 0 | 1680 | 1680 | 0 |
| normal | SET | 2s | 1 | 1 | 1680 | 1680 | 0 |
| normal | SET | 2s | 32 | 0 | 22295 | 22295 | 0 |
| normal | SET | 2s | 32 | 1 | 22295 | 22295 | 0 |
| normal | INCR | 1s | 1 | 0 | 1522 | 1511 | -11 |
| normal | INCR | 1s | 1 | 1 | 1522 | 1511 | -11 |
| normal | INCR | 1s | 32 | 0 | 37763 | 37411 | -352 |
| normal | INCR | 1s | 32 | 1 | 37763 | 37411 | -352 |
| normal | INCR | 2s | 1 | 0 | 2142 | 2131 | -11 |
| normal | INCR | 2s | 1 | 1 | 2142 | 2131 | -11 |
| normal | INCR | 2s | 32 | 0 | 37608 | 37256 | -352 |
| normal | INCR | 2s | 32 | 1 | 37608 | 37256 | -352 |
| normal | MGET | 1s | 1 | 0 | 10163 | 10160 | -3 |
| normal | MGET | 1s | 1 | 1 | 10190 | 10186 | -4 |
| normal | MGET | 1s | 32 | 0 | 324038 | 323942 | -96 |
| normal | MGET | 1s | 32 | 1 | 324902 | 324774 | -128 |
| normal | MGET | 2s | 1 | 0 | 10163 | 10160 | -3 |
| normal | MGET | 2s | 1 | 1 | 10190 | 10186 | -4 |
| normal | MGET | 2s | 32 | 0 | 324038 | 323942 | -96 |
| normal | MGET | 2s | 32 | 1 | 324902 | 324774 | -128 |
| normal | MSET | 1s | 1 | 0 | 10780 | 10695 | -85 |
| normal | MSET | 1s | 1 | 1 | 16991 | 16989 | -2 |
| normal | MSET | 1s | 32 | 0 | 344805 | 342085 | -2720 |
| normal | MSET | 1s | 32 | 1 | 961926 | 902094 | -59832 |
| normal | MSET | 2s | 1 | 0 | 10598 | 10513 | -85 |
| normal | MSET | 2s | 1 | 1 | 16659 | 16657 | -2 |
| normal | MSET | 2s | 32 | 0 | 338981 | 336261 | -2720 |
| normal | MSET | 2s | 32 | 1 | 951302 | 891470 | -59832 |
| db0 | GET | 1s | 1 | 0 | 818 | 777 | -41 |
| db0 | GET | 1s | 1 | 1 | 818 | 777 | -41 |
| db0 | GET | 1s | 32 | 0 | 18705 | 17393 | -1312 |
| db0 | GET | 1s | 32 | 1 | 18705 | 17393 | -1312 |
| db0 | GET | 2s | 1 | 0 | 1051 | 1016 | -35 |
| db0 | GET | 2s | 1 | 1 | 1051 | 1016 | -35 |
| db0 | GET | 2s | 32 | 0 | 18163 | 17043 | -1120 |
| db0 | GET | 2s | 32 | 1 | 18163 | 17043 | -1120 |
| db0 | SET | 1s | 1 | 0 | 926 | 920 | -6 |
| db0 | SET | 1s | 1 | 1 | 926 | 920 | -6 |
| db0 | SET | 1s | 32 | 0 | 22161 | 21969 | -192 |
| db0 | SET | 1s | 32 | 1 | 22161 | 21969 | -192 |
| db0 | SET | 2s | 1 | 0 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 1 | 1 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 32 | 0 | 21619 | 21619 | 0 |
| db0 | SET | 2s | 32 | 1 | 21619 | 21619 | 0 |
| db0 | INCR | 1s | 1 | 0 | 1308 | 1263 | -45 |
| db0 | INCR | 1s | 1 | 1 | 1308 | 1263 | -45 |
| db0 | INCR | 1s | 32 | 0 | 34914 | 33474 | -1440 |
| db0 | INCR | 1s | 32 | 1 | 34914 | 33474 | -1440 |
| db0 | INCR | 2s | 1 | 0 | 1541 | 1502 | -39 |
| db0 | INCR | 2s | 1 | 1 | 1541 | 1502 | -39 |
| db0 | INCR | 2s | 32 | 0 | 34372 | 33124 | -1248 |
| db0 | INCR | 2s | 32 | 1 | 34372 | 33124 | -1248 |
| db0 | MGET | 1s | 1 | 0 | 10307 | 9974 | -333 |
| db0 | MGET | 1s | 1 | 1 | 10334 | 9999 | -335 |
| db0 | MGET | 1s | 32 | 0 | 328646 | 317990 | -10656 |
| db0 | MGET | 1s | 32 | 1 | 329510 | 318790 | -10720 |
| db0 | MGET | 2s | 1 | 0 | 10307 | 9974 | -333 |
| db0 | MGET | 2s | 1 | 1 | 10334 | 9999 | -335 |
| db0 | MGET | 2s | 32 | 0 | 328646 | 317990 | -10656 |
| db0 | MGET | 2s | 32 | 1 | 329510 | 318790 | -10720 |
| db0 | MSET | 1s | 1 | 0 | 11017 | 10833 | -184 |
| db0 | MSET | 1s | 1 | 1 | 16428 | 16357 | -71 |
| db0 | MSET | 1s | 32 | 0 | 352389 | 346501 | -5888 |
| db0 | MSET | 1s | 32 | 1 | 952094 | 894518 | -57576 |
| db0 | MSET | 2s | 1 | 0 | 10835 | 10644 | -191 |
| db0 | MSET | 2s | 1 | 1 | 16096 | 16018 | -78 |
| db0 | MSET | 2s | 32 | 0 | 346565 | 340453 | -6112 |
| db0 | MSET | 2s | 32 | 1 | 941470 | 883670 | -57800 |

## Atomic-1 MGET with retained EXEC-format records

Eight records remain live before and after the measured scope. Batch size is 1. These scope deltas include compiler effects; the incremental delta subtracts the corresponding ordinary atomic-1 MGET delta, and is not an isolated branch instruction count.

| Image | Mode | PRE | POST | Delta | Ordinary delta | Incremental live delta |
|---|---|---:|---:|---:|---:|---:|
| normal | 1s | 12771 | 12847 | 76 | -4 | 80 |
| normal | 2s | 12643 | 12719 | 76 | -4 | 80 |
| db0 | 1s | 12835 | 12852 | 17 | -335 | 352 |
| db0 | 2s | 12707 | 12724 | 17 | -335 | 352 |
