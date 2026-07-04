---
name: thredis-sanity-gate-benching
description: "User rule (2026-07-03): sanity-check every bench/validation number; if it doesn't make sense STOP, reread code, fix, re-bench — never reason from a nonsense result"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

**Rule (user, 2026-07-03):** after EACH bench cell AND each validation result, check the number is
physically sensible. If it doesn't make sense — stop the bench, reread the relevant code/harness, edit
the cause, then bench again. Applies to throughput AND correctness/validation results equally.

**Why:** this session alone, blindly-trusted numbers wasted real time — the pinning artifact (v12 "4.36M
regression" that was SMT-sibling contention), the dragonfly 256B collapse (nearly reported as a THredis
win), the bool-knob START_FAIL (whole stage-ablation run = zeros), concurrent-session contamination
(32B GET reading 1.2M). A nonsense number is a bug (in harness or code), not data.

**How to apply:** plausibility-check vs neighbors / known baselines / the mechanism / line-rate. First
suspects when a number is wrong: concurrent memtier or other session on the port; `pkill -f` self-match;
bool knob passed as 0/1; redis-benchmark \r + default-port; pinning to SMT siblings; dragonfly loopback
pipelined-GET collapse; stale RDB dir. Fix → re-run → only then record. See [[thredis-benchmarking-methodology]]
and the v13 acceptance plan (overnight_sweep/v13_bench_plan.md). Endgame bench spec in [[thredis-endgame-two-versions]].
**Corollary (user, 2026-07-03):** when a delta is within run-to-run variance (~3% on the 1-CCD 7700X),
it is UNRESOLVED, not zero — do more runs (3-5+) until the sign is stable or it's provably a wash.
Never call a keep/drop verdict on a single within-noise pass. Interleave configs to cancel thermal drift.
