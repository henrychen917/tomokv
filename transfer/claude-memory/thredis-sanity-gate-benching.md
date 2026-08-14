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

**2026-07-25 — three ways a benchmark LIES, all hit in one session (7700X, this box is STABLE: an
unchanged commit reproduced 5.41M vs 5.42M seven hours apart — do NOT reach for "thermal drift" as an
explanation before re-measuring the old build):**
1. **Stale output file.** Read `freshcells.out` before the new run rewrote it and reported the OLD
   build's numbers as the new build's. The tell was ignored: three rounds reproducing to 9 significant
   figures ACROSS a rebuild is impossible. ALWAYS verify the result file's mtime is after the build,
   or have the harness stamp the binary's mtime into its own output.
2. **Measuring on a busy box.** Started an A/B while a previous validation chain was still running
   (load 17) and got 1.84M for a build that does 4.5M — then nearly believed a "regression". Harness
   now REFUSES to measure unless load < 2 and no redis-server/memtier processes exist.
3. **Appending server logs.** `--logfile` appends, so a PREVIOUS run's crash markers read as this
   run's failure. Check by pid/timestamp or truncate at boot.

**LESSON: when a number moves, A/B the OLD BUILD AGAIN ON THE SAME BOX STATE before theorising.**
Attributing a drop to "drift" protected a conclusion I had already published; the user's pushback
("I doubt 5.4 to 4.5 is drift maybe we forgot to push a version?") is what forced the real test, and
the real cause was a genuine -17% regression in my own commit.
