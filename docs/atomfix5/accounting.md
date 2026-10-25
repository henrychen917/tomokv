# AT4.19 — exact accounting across an undecided multi-owner unit

The new atomfix5_accounting gate job checks 1s/2s × uring/epoll × databases 1/16,
atomic 1, four fresh schedules per leg. Eight server cores 48–55, load 56–63,
16 shards, split 6:2, fused read-local 1, LB/auto-FLIP off, ports 34800/34801.
The gate's own job interface ran every leg on PRE and POST.

An EXEC appends a unique element on one owner, performs a deferred multi-owner
MGET, and appends on the other owner. Existing counters plus an unread EXEC
reply prove that a candidate is installed while the unit is still undecided.
Eight other clients append 32 unique items each to those same keys. An owner
wait or an early reply proves competing traffic actually reached the held unit.
After all replies, the test requires the exact multiset of 258 acknowledged
items, zero losses/duplicates, and every integer length 1..129 exactly once
per list. The production path must also record conflicting writer waits.
Redis 7.4 executes the same commands and exact accounting assertions.

A missed window is retired and retried on fresh keys, at most four times; a
reply/data failure is never retried. Never opening the window fails the row.

PRE ef5204b2e: 32/32 directed schedules PASS. POST: 32/32 PASS. This baseline
already contains version-ordered writer episodes, so an honest test-gap row
cannot also claim a failing PRE runtime regression. That requested negative
control is NOT AVAILABLE on this named PRE; it is explicitly not counted as
PRE-fails/POST-passes evidence.

Falsifiability is established separately: tools/atomfix5_arms.py makes an
isolated copy of POST whose two multi_plain_write_ready entries return true.
The same gate job rejects this broken-writer control in all eight declared
legs, on exact data loss: the first list has 1 visible item after 129 acknowledged
appends (128 missing). The control is never a candidate or merit arm. Logs are
in accounting-{pre,post,broken}.log.gz, with the gate partial ledgers alongside.

One new row collected before the quick-tier exit: DQ=+1 / DF=+1; the lane total
is +2/+2 with WATCH. EXPECT_QUICK and EXPECT_FULL remain unchanged.
