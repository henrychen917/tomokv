---
name: thredis-prefetch-stage-verdicts-provisional
description: "User directive (2026-07-03): do NOT finalize per-prefetch-stage keep/drop verdicts on single-regime data — verify across many memory-bound situations + NUMA first; key-prefetch is the likely keeper"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

**Directive (user, 2026-07-03):** don't lock in a keep/drop verdict for each prefetch stage (or any
edit) on one workload. Test MORE situations and verify MORE before deciding. Same for the hot-path edits.

**User's priors:** key prefetch (the dict bucket→entry→value chase — pf-w-hash/entry/value + keyobj) is
"100% worth" keeping. The other stages (fc/argv/cmd, io-struct/io-reply, nextop, the pass-1 loop
machinery) are uncertain — "maybe only worth on NUMA."

**Why the single-regime ablation was inconclusive:** the knobstages sweep (overnight_sweep/knobstages.tsv,
2026-07-03) came back a WASH on the 1-CCD 7700X — everything within ±3% at n=1, because 512B/4KB GET/SET
on 8 threads is **dispatch-bound, not DRAM-latency-bound**, so a latency-hiding prefetcher has nothing to
hide. Weak flags only: 3s pass-1-loop-machinery −4.3% (empty loop costs), 3s entry-chase +3.3% — both
barely above the ~3% noise floor, NOT verdicts. (Sanity: A0 hash-off < A1 hash-on by ~1-1.7% both forks →
hash-carry pays for itself; numbers internally coherent, just small.)

**How to apply — expand the eval before any verdict:** run each stage across memory-bound regimes where
prefetch can actually matter: (1) pointer-chasing / logic-heavy commands (HGETALL, LRANGE, ZRANGE,
SMEMBERS, BITCOUNT-1MB — the paper's Tier-2/3), (2) working sets that clearly exceed L3 with random access,
(3) a DB-size sweep cache-resident→DRAM-spill (the adaptive-gate's raison d'être), (4) larger values, (5)
higher pipeline depths. THEN re-run all of it on the Threadripper (multi-CCD + NUMA modes + 8-ch DDR5) —
per the user, some stages may ONLY pay off there. Until that's done, keep ALL prefetch-stage knobs GATED
default-on (don't hardwire, don't drop). See [[thredis-sanity-gate-benching]], the adaptive gate note in
[[thredis-endgame-two-versions]], and the eval plan in overnight_sweep/v13_bench_plan.md.

**v13 scoreboard rewrite (2026-07-03, commits ba9918a0e/a12f77368):** exPrefetchBatch is now a
Redis-8-style round-robin FSM ("Tomo scoreboard": STRUCT→ARGV→KEYOBJ→KEYBYTES→HASH→ENTRY→VALUE→DONE,
yield-per-issue, writes retire at HASH) with gem5 per-stage width knobs (pf-w-struct/-argv/-keyobj/
-keybytes/-hash/-entry/-value; functional SipHash+stash always runs). Old pass-1 bools (pf-fc/argv/cmd/
keyobj) RETIRED; pf-cmd stage deleted (cmd table L1-hot); embstr keybytes skip. Measured on the 7700X:
whole pipeline ≈ parity everywhere (2s exact parity, 3s flat within noise) — this box's MLP at P16
covers the misses; even the bucket prefetch is flat, P1d inert even with raw long keys; the retirement
study's earlier "+12% pf_always" did NOT reproduce post-#E1 (it was an interaction with batch-push
starvation). Redis comparison: their FSM is dict-only (same-thread ops → only the dict is cold); ours
adds the cross-core operand links. Dragonfly: no batch prefetcher — cache-conscious dashtable
(fingerprint buckets) + zero-distance point prefetches + shard parallelism; their "fingerprinted bucket
dict" idea logged for v14. Threadripper remains the deciding regime for all stage-width verdicts.
