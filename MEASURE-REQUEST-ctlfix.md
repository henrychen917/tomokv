# FLIP controller correctness — lane ctlfix

## ctlfix

Base: `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`. Branch `cx-ctlfix`.
Correctness work only; no throughput claim. All lane builds and test processes use
CPUs 48–63, with live test ports confined to 35800–35899. No push.

### CT4.1 completion consumption and state table

REPRODUCED through `tests/gate.sh`, job `flip_unit`, using the existing
`CoreConcurrencyTest::Fixture<false>`: 8 logical workers, 6 IO + 2 EX, 16 shards,
database 0, load balancers off, no network/worker loop. An automatic 6:2 → 4:4
completion followed by accepted manual 4:4 → 6:2 before the monitor tick produced
`completed=2 phase=waiting-flip consumed=0` on PRE. The first attempted run failed
to compile because the embedded fixture needed `TOMO_CORE_CONCURRENCY_TEST`;
`ct41-pre-repro.log` is the armed reproduction, not that infrastructure failure.

The existing `pending_completed_` becomes the monitor's monotonically consumed
completion cursor as well as its automatic request's baseline. The monitor consumes
the entire newly completed count once under the admission mutex after acquiring
Idle. No event queue, allocation, hot-path bookkeeping, or layout field is added.
Only one isolated completion at the expected target without an intervening refusal
can contribute automatic cost. Any manual/ambiguous batch cancels the hypothesis
and learns a fresh anchor at the actual placement. Admission rejects stale
controller evidence under the same mutex, without consuming its completion.

Here A is the automatic request, M a manual request, O a monitor observation;
“settle” means discard the stale hypothesis and settle at the live placement.
Accepted same-target no-ops count as completions in the existing actuator.

| Ordering / observation | Completion handling | Controller action |
|---|---|---|
| A active; O (with or without a refused M) | No completed transaction consumed | Wait for Idle; defer forced trigger |
| A completed; O; no M | Consume A once; price isolated cost | Enter A's requested Seeking/Settling phase |
| A completed; M completed; O, different final target | Consume both once; discard combined cost | Settle |
| A completed; M completed; O, same final target/no-op | Consume both once; discard combined cost | Settle; never mistake matching target for isolated A |
| A completed; O; M completed; O | Consume A then M once each; retain only A's isolated cost | First continue A, then settle |
| A refused; M completed; O | Consume M; refusal makes attribution ambiguous | Settle without outcome/cost learning |
| M refused while A active; A completed; O | Consume completion once; conservative ambiguity handling | Settle without attributing an outcome |
| A refused; O; no completion | No completion to consume | Existing settle/return path |
| M active; O in any other phase | No partial completion consumed | Wait for Idle |
| M completed; O in BootPending/Measuring/Seeking/Settling/Anchored | Consume complete batch once | Settle |
| M completes between sampling and automatic admission | Admission count check rejects stale request | Next O consumes M; settle |
| Forced trigger before/during/after any completion above | Consume completed count first; isolate cost only if valid | Restart Measuring after Idle |
| Repeated O with unchanged completion count | Consume nothing again | Continue current phase; no duplicate cost/learning |

These equivalence classes cover arbitrary repeated M completions: the count delta
consumes every member of a batch, and any batch beyond the one isolated A is
intervention. A request admitted just after the locked observation belongs to the
next observation. The monitor does not reconstruct intermediate manual targets.

### CT4.2 IO-only boot measurement

REPRODUCED on frozen PRE through the same gate job. The existing in-memory boot
fixture publishes deterministic fingerprints and feeds 6000 completed commands
per 1-second tick at 6:2 / 16 shards. PRE enters boot measurement once, spends
53 ticks in Measuring, and still reports samples 0 / cap 15. No sockets or
timing-dependent arming are involved.

Count every accepted stabilized rate reading against the budget before asking
whether both roles supplied enough work for a demand estimate. Missing role
evidence contributes no demand draw. At the cap, record `hold-no-demand`, clear
the requested debug seek, and settle at the live split. The regression includes
IO-only, intermittent executor work, and continuous executor work, and requires
Anchored plus the maneuver sampling arm off. The cap remains a count of accepted
readings, not a promise about elapsed time during unstable/invalid windows.

### Gate accounting

The existing `flip controller model unit` row is extended with deterministic
production-controller schedules. Its original arithmetic tests remain present.
No added or retired ledger label: DQ=0, DF=0. The row is collected before the
quick-tier exit. `EXPECT_QUICK` and `EXPECT_FULL` remain untouched.

Build identities, complete correctness results, label-fixture reconciliation, and
the maintainer's 14-cell PRE/POST/PAD-A merit request follow after verification.
