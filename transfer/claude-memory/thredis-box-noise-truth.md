---
name: thredis-box-noise-truth
description: "CORRECTION — the dev box is a 7700X desktop with ±2% run-to-run when EXCLUSIVE; the \"15-30% drift\" figure is the laptop's and must not be used to explain away results here"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

## The dev box is a 7700X desktop, not the laptop

`AMD Ryzen 7 7700X`, 8C/16T, **single CCD**, 32 MiB L3, 1 NUMA node. Owner's ruling 2026-07-28:

> "this box doesn't drift 15 30%... it's 7700x unless ur running 2 benches at the same time it's
> usually +- 2%... not laptop"

**Exclusive run-to-run noise is ±2%.** The "~15% run-to-run drift ⇒ interleave mandatory" note in
[[thredis-prefetch-status]] and the "drifts 15-30%" line in [[thredis-ab-harness-traps]] /
[[thredis-benchmarking-methodology]] describe the **laptop**. Carrying that number to this box is a
serious error, not a conservative one.

## Why this matters more than a units nit

A wide noise band is an all-purpose excuse. With ±15-30% assumed, *any* inconvenient result can be
dismissed as drift, and two real failures were dismissed exactly that way:

1. A subagent's A/B saw HEAD's own median move **-9% between runs on identical code** and attributed
   it to thermal drift. On a ±2% box that explanation is impossible. The real cause was
   **contention**: my `rc_gate` benchmarks ran 21:36-21:47 inside that agent's `ad`/`ae` cells
   (21:19-21:57). I polluted its measurements while believing I had serialised.
2. The same agent then graded two changes at -0.6%/-0.7%/+1.7% as "all within noise, revert both".
   At ±2% that verdict is not supported — **+1.7% may be real signal** — and the underlying cells
   were contaminated anyway.

**Rule: on this box a swing >5% between identical arms is CONTENTION OR A BUG, never drift.**
It is a sanity-gate STOP-AND-LOOK, matching [[thredis-sanity-gate-benching]].

## The process failure, and the fix

`boxfree.sh` samples CPU *instantaneously*, so it reports FREE in the gaps between another agent's
cells — it cannot serialise two cooperating processes. Checking it before each run is NOT enough.
Use a **shared exclusive lock** that every benchmark takes for its whole duration
(`flock` on one well-known path), so waiting is automatic rather than polite. Per-script private
locks (each agent flocking its own file) provide no mutual exclusion at all.

Related traps that survive unchanged: renamed binaries defeating `pkill -x` in BOTH directions
(see [[thredis-alloc-truth]] and [[thredis-ab-harness-traps]]) — and note a leaked server is far
more damaging when the true noise floor is ±2%.
