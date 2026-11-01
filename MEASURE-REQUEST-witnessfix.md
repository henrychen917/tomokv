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
