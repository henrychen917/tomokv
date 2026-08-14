---
name: thredis-lb-3pct-budget
description: "User rule — load-balancing/adaptive machinery must cost <=3% throughput, or it doesn't ship (why the original EWMA bucket balancer was removed)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**User rule (2026-07-25): "lb is important yes but it's not worth more than 3% throughput deficit at
all — that's why we got rid of the original ewma buckets in the first place."**

**Sharpened same day: "keep hot path ideally as fast and low overhead as possible. Architectural
things like the hops are unavoidable, but basically everything about load balancing is. LB needs to at
the min introduce basically almost no impact on hot path to be called viable."**
So 3% is the CEILING, not the target. The distinction that matters: architectural costs (cross-shard
hops, the dispatch itself) are inherent to the design and are paid knowingly; LB/adaptive machinery is
OPTIONAL, so it must be ~free per-op or it is not viable. Practical test for any new mechanism: what
does it add to the PER-OP path (not just steady-state throughput)? Prefer designs where the common
case executes zero extra atomics and at most a predictable branch — e.g. move state per-thread so the
hot path needs no shared write (the FLATSTORE retire path went from a CONTENDED CAS on a shared
Treiber stack to a plain thread-local push: strictly cheaper than what it replaced), and push all
coordination into rare/slow paths (region markers around admin ops, not around dispatch).

Load balancing / adaptive machinery (flip controller, thread-modes balancer, bucket LB, and by
extension any always-on bookkeeping like the QSBR reclaim gate) has a **hard budget of ~3% throughput**.
Past that it is not worth shipping no matter how good the balancing is — the original EWMA per-bucket
balancer was DELETED for exactly this reason.

**Why:** these systems exist to protect the tail / adapt to skew, but the common case is a stable
workload where the machinery only subtracts. A permanent 10-17% tax to handle an occasional shift is
a bad trade; make the mechanism cheap in the common case instead of accepting the tax.

**How to apply:** whenever adding an always-on mechanism, measure it against the same config with the
mechanism OFF, interleaved (A/B in one binary via a runtime knob is best — see
[[thredis-flat-reclaim-capacity]] for the grace-mode bisection that isolated a 17% cost to one clause).
If it exceeds ~3%, do NOT accept it as "the cost of correctness/adaptivity" — find the scoped version.
Worked example: the FLATSTORE QSBR main-thread gate cost 17% when main was marked busy for its entire
I/O phase; scoping the marker to only the regions that actually touch flat values (call() on main,
activeExpireCycle, shutdown save) gave the identical guarantee at **0.2%**. Same correctness, budget met.

Related: [[thredis-flip-controller-momentum]] (momentum controller: 0 flips on a steady workload =
near-zero steady cost), [[thredis-flip-overhead-decomposed]], [[thredis-sanity-gate-benching]].
