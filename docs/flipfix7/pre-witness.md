# PRE witnesses: 9d6ab5526

No production source was changed before these 64 directed witnesses completed.

Each row is a fresh 6 IO / 2 EX boot, 16 shards, CPUs 48-55; drivers use 56-60, ports 21000/21001, LC_ALL=C. The late-output and signal windows reroll on fresh state; an exhausted campaign fails. Raw snapshots capture every held attempt, including IoDrain and ClientPrepare refusals on unsuccessful arming attempts.

| Engine | RL | Atomic | DBs | BLPOP stage / FLIP seconds | TLS stage / FLIP seconds | Late output stage / held seconds | SIGTERM / recovered |
|---|---:|---:|---:|---|---|---|---|
| uring | 0 | 0 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.404 | ignored 12 s / 0 of 1000 |
| uring | 0 | 0 | 16 | IoDrain / 5.001 | ClientPrepare / 5.000 | ClientInstall / 13.441 | ignored 12 s / 0 of 1000 |
| uring | 0 | 1 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.398 | ignored 12 s / 0 of 1000 |
| uring | 0 | 1 | 16 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.379 | ignored 12 s / 0 of 1000 |
| uring | 1 | 0 | 1 | IoDrain / 5.000 | ClientPrepare / 5.001 | ClientInstall / 13.561 | ignored 12 s / 0 of 1000 |
| uring | 1 | 0 | 16 | IoDrain / 5.000 | ClientPrepare / 5.014 | ClientInstall / 13.165 | ignored 12 s / 0 of 1000 |
| uring | 1 | 1 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.479 | ignored 12 s / 0 of 1000 |
| uring | 1 | 1 | 16 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.153 | ignored 12 s / 0 of 1000 |
| epoll | 0 | 0 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.475 | ignored 12 s / 0 of 1000 |
| epoll | 0 | 0 | 16 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.065 | ignored 12 s / 0 of 1000 |
| epoll | 0 | 1 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.401 | ignored 12 s / 0 of 1000 |
| epoll | 0 | 1 | 16 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.171 | ignored 12 s / 0 of 1000 |
| epoll | 1 | 0 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.541 | ignored 12 s / 0 of 1000 |
| epoll | 1 | 0 | 16 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.136 | ignored 12 s / 0 of 1000 |
| epoll | 1 | 1 | 1 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.433 | ignored 12 s / 0 of 1000 |
| epoll | 1 | 1 | 16 | IoDrain / 5.000 | ClientPrepare / 5.000 | ClientInstall / 13.071 | ignored 12 s / 0 of 1000 |

BLPOP holds the Blocking barrier and one parked ROB slot. TLS fails the owner-local engine check. Late output holds nothing_to_write(), plus send_inflight on uring; draining all 1,024 notification payloads releases the post-commit wedge. Every non-signal case verifies the blocked/TLS connection or every notification payload and stored sentinel after release. Signal cases deliberately force-stop only the owned PRE process after the bound and verify lost acknowledged keys by restart.

Debugger snapshots are read-only and stop the process briefly after the one-second failure bound. The observed late-wedge hold duration includes debugger time and the deliberate hold before draining; it is not a latency/performance measurement. BLPOP/TLS deadlines remain approximately five seconds. A forced signal stop is a reproduced failure, never a clean-shutdown pass.

PRE SHA-256: `f8116b72a37b6a1200dc5681b7eec43d88828a07175f23202afc6d104907ef0c`. The 80 serverless PRE command-scope counts are in counts/. No throughput or full iteration ran.
