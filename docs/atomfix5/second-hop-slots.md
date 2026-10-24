# AT4.21 — NOT REPRODUCED

PRE ef5204b2e: 1s/2s × atomic 0/1, eight server CPUs 48–55, driver 56–63,
16 shards, databases 16, uring, split 6:2, fused read-local 1, balancing/auto-FLIP
off, port 34810. DEBUG SHARDS proves the two shared keys have different owners.
32 concurrent clients each move its own set member between those keys in ten
256-command pipelines: 81,920 SMOVEs per leg. All four legs return 81,920 ones,
zero errors, source cardinality 32 and destination zero. See
reproductions-pre.json and reproductions-pre.log.gz.

No queue-full event was observed. Per the reproduction-first instruction, no
production fix or gate row is claimed: DQ=0, DF=0. The source refusal remains
in publish_phase2, publish_pop_retry and publish_sort_deref. Script wave posts
already return Retry on Full and keep a poster pending reference.

Any eventual fix must retain a single completion owner while yielding to the
normal executor loop; spinning inside publish would prevent that executor from
consuming its own incoming slots and can deadlock a producer cycle. A retry
must not rerun the old phase, decrement pending twice, rebuild a wave under
published tasks, or recreate an AOF group. Before posting it must reserve/check
all destinations without holding any queue slots, then keep a poster reference
until every task is visible (as script_post_phase already does). The issuing
connection's barrier/ROB operation must remain live until success. Deferred
posting must let all destination consumers run, including the posting owner.
A bounded-capacity owner-turn fixture should force Full in each of the three
publishers and verify these invariants before any live queue-pressure result
is treated as proof. None of that is asserted to have been implemented here.
