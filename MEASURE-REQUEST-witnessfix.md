# Regression witness repairs

## witnessfix

Base: `7d2f8a2051961a1942735fb6dc9b507d778e09d1`; branch `cx-witnessfix`.
Test-side changes only. Correctness commands use CPUs 80-95, ports 20500-20599,
and `LC_ALL=C` for server boots. No performance measurements or full iteration.
Receipts are recorded under `docs/witnessfix/`; temporary controls live in `build/`.

### V1 — ACLKEYS3 last-owner-task wake

Added the `aclkeys_wake` gate job. It runs the existing production-body unit in
both database images, split/fused and atomic 0/1, across eleven schedules (88
invocations). The window cases require latch stages 1/2/3 and a renewed IO
notification after the last owner task leaves; missing arming is a failure.
Control builders/runners now accept the lane CPU allocation instead of forcing
the maintainer's CPUs.

Proof receipts: pending the baseline build and the no-wake/no-hold controls.
This is a serverless schedule, not a claim that a live listener hit the race.

DQ=+1, DF=+1: `collect_job aclkeys_wake` is before the quick-tier exit.
`EXPECT_QUICK`/`EXPECT_FULL` are unchanged and remain maintainer-owned.

### V2 — dead refusal counters

Removed all assertions/diagnostics based on `script_group_occ_giveups` and
`script_crossshard_window_refusals` from at412, wave8, mode_equivalence, differ
and xscript. Their existing exact replies, conservation and live wait/retry
counter checks remain the evidence. No new production counter is needed to
detect a refused reply. DQ=DF=0. Live and PRE receipts pending.

### V4 / TM4.1 — debug battery atomic drift

Before every `job_debug` battery, restore `atomic` and require `CONFIG GET`
to return the requested value. A failed restore fails that battery without
mislabeling its configuration. `*-atomic.txt` records each live assertion.
DQ=DF=0. Both split atomic settings and the explicit fused posture need runs.

### V14 — lottery campaign

`tests/gate.sh lottery` now exposes the existing nightly runner. CPU checks
require the assigned affinity, eight server CPUs and disjoint client CPUs;
ports must leave room for three listeners below 32768. The old hard-coded
112-127 / 25300 allocation could not run in this lane. Every boot inherits C
locale. The normal gate counts remain unchanged (DQ=DF=0).

Campaign command: `LC_ALL=C LOTTERY_CPUS=80-95 LOTTERY_JOBS=16 taskset -c 80-95
tests/gate.sh lottery --server-cpus 80-87 --client-cpus 88-95 --port 20590
--output build/witnessfix/lottery`. Results pending; no hit is inferred from
an attempted command or an empty trace.
