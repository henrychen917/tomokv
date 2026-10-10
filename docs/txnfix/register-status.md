# txnfix REGISTER status addendum

The round-4 REGISTER is `/home/user/Projects/round4-read/REGISTER.md`, outside
this lane's worktree. The instruction to edit only this worktree prevents an
in-place update. These are the proposed status lines for the maintainer; no
finding is marked fixed before its proof is complete.

| Finding | Lane status | Remaining requirement |
|---|---|---|
| AT4.1 | WIP: optimistic EXEC validation, transparent retries and exclusive fallback implemented; new directed/stress rows pass both modes, atomics and database counts | Complete regression/differential, shutdown and hot-body proof; approve fallback |
| AT4.2 | CONFIRMED, Stage B not implemented | Cancellable read-dependent atomic groups, txngroup rows and cost proof |
| AT4.3 | CONFIRMED, Stage B not implemented | Cancellable atomic MSETNX and concurrent-SET proof |

The crossed-WATCH pattern hangs PRE and completes under the new age rule.
DEL/UNLINK count at atomic 1 remains a reply constraint. Hits/misses can count
discarded EXEC attempts. The retained cut is a cleanup pin, and phantom
protection is enabled for whole-shard reads.

The earlier round-3 MULTI constraint needs its separate factual correction:
CONFIG SET is accepted; SAVE is refused by Redis too. Current engine refusals
are FLUSHALL, FLUSHDB, ACL, the six subscription-control commands, and DEBUG
RELOAD/LOADAOF. This lane does not change those refusals.
