# IO loop refinement

## iofix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`; branch `cx-iofix`.
No push. Performance acceptance is pending maintainer measurement.

All four register findings reproduced on PRE with 16 shards, CPUs 80–87,
split 6:2 or eight fused workers, both uring and epoll, ports 19800–19801.
The clients ran on CPUs 88–95. Raw reproduction evidence is in `docs/iofix/`.
Source oracle: `/home/user/Projects/redis/src`; binary oracle:
`/home/user/Projects/redis74/src/redis-server`.

WB4.1: only advancing a bounded completion counter counts as deferred work.
Saturated half-rule and unbounded completion entries retain their FIFO/lifetime
pins while the existing arm/recheck/park protocol waits for owner completions.
The Dth increment still schedules a pass to try the half threshold immediately.
This preserves WB4.2's bounded visit clock: D=3 can still expire in short idle
passes. The fix removes the subsequent indefinite spin; it does not establish
that the small-pipe completion clause becomes effective at low load.

The new `iofix-deferred` gate job owns all four mode/engine legs and an oracle
reply comparison in each. It fails on PRE in every leg after executing all four
policy arms. It is collected before the quick-tier exit: DQ=+1, DF=+1 so far.
`EXPECT_QUICK` and `EXPECT_FULL` are unchanged. Final counts, POST validation,
binary hashes, PAD-A construction and the merit cells will be recorded here
after the remaining changes.
