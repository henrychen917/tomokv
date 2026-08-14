---
name: thredis-flip-controller-frozen
description: "OWNER RULE — the flip controller decision stack is FROZEN; validated, do not modify"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

The flip controller's decision stack is FROZEN by owner ruling (2026-08-08): idle detection, sat
calculations, where to settle, where it is NOT allowed to settle, how long it measures settled
throughput and sat, and how it settles. All of it. "Unless something changes this stays."

**Why:** It has proven itself — validated from p1 GET to ZRANGE, settling correctly on both; the
step-4 quorum balancer and momentum hill-climb passed their conformance suites. The known boot-ramp
misclimb (1-in-5 boots on EX-bound atomic 9:1, wedges at ~1.3k ops/s) is ACCEPTED behavior — the
designed fix (ramp guard + RE-BASELINE pressure guard, judged 8/10, in workflow wf_012ea261-80f's
result) was REJECTED because it touches detection windows and settle/anchor behavior. Shipping
answer for atomic write-heavy workloads: document static provisioning (io4/ex4 — faster than auto
there anyway, 919-939k vs ~865k).

**How to apply:** Never modify detection thresholds, sat math, stability windows, measurement
durations, anchor/re-baseline behavior, or climb/settle logic — not even "startup-only" scoped
versions (explicitly rejected). The ONLY permitted lane is mechanical cost reduction where every
decision input, output, threshold, cadence, and duration stays bit-identical (e.g., skipping
redundant recomputation in the settled dir=0 state). If a proposed tax cut requires changing what
the controller sees or when it looks — the honest answer is "not reducible under the rule."
Related: [[thredis-lb-3pct-budget]], [[thredis-threadcfg-sendbound]].
