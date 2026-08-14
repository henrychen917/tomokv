---
name: thredis-benchmarking-methodology
description: "How THredis sweeps/tuning must be benchmarked — DB-size axis, core pinning, ratios, config breadth"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

The early sweeps benched too narrowly: fixed 100k-key DB (fully L3-resident on this box, L3≈24MB → ~240k-key residency boundary), so only the cache-hit regime was measured. Going forward, THredis sweeps/knob-tunes MUST:

- **Vary DB size** as a primary axis, including sizes whose working set can't stay in cache — e.g. {100k resident, 1M spills-L3, 10M DRAM-bound, 50M deep-DRAM} at 64B (50M×64B≈7.5GB, safe in 30GB RAM). Payload can stay ~64B but optionally vary {64B,1KB}; 1KB only at smaller keycounts (memory-bounded).
- **Test memtier ratios 1:1 AND 1:9** (SET:GET), plus skewed/zipf variants — large DB + uniform = misses; large DB + zipf = hot subset cached. That interplay is the point.
- **More configs** to reveal opt *interactions*: leave-one-out from all-on + add-one-from-all-off (marginal contribution with/without the others), the COMPUTE/COHERENCE halves, and the deep-tune int-vectors.
- **Benchmark load-gen pinned to the 8 unused E-cores (`taskset -c 8-15`), 8 threads, kept constant** across all cells (load-gen capacity must not be a variable). Pin the SERVER to `taskset -c 0-7` (4P+4E) so 8-15 are truly free. Core counts stay fixed; tune everything else.
- redis-benchmark is allowed as an additional driver / cross-check alongside memtier and the trace-replayer.
- Run on v7 (+ cross-shard MGET workloads) if v7 validates clean, else v6.

**Why:** the on-box noise (~8-17% CoV, replayers 20-30%) plus cache-residency means single-size results don't generalize; the opts are NUMA/cache-miss/pattern-gated (see [[thredis-v4-tunable-apparatus]], [[thredis-opt-and-testers]]). **How to apply:** when asked to sweep/tune, build the matrix as DB-size × ratio × pattern × config, time-budget per DB-size so partial runs stay balanced, median-of-N passes. The 6h-sweep request (2026-06-20) is the first run of this.

## OWNER RULE (2026-08-12): SATURATING CELLS ONLY — else we measure noise

Owner: "for 7 1 do p32 and p1; for 4 4 or new p32 optimum do only p32; only p32 25cl 8t
otherwise no saturation and we measure noise." The go-forward A/B matrix for THIS box:
- **io7ex1**: p32 GET, p32 SET, p1 GET, p1 SET  (t8 c25) — the worker-concentrated diet family
  ([[thredis-commtax-truth]]) shows LARGEST here; p1 is meaningful at io7ex1 (7 IO threads, IO-side
  saturates) but NOT at io4ex4.
- **io4ex4** AND **io5ex3** (the re-measured p32 SET optimum): p32 GET, p32 SET ONLY (t8 c25).
- DROP: p1 at io4ex4/io5ex3, single-conn anything, and any cell that doesn't saturate the server —
  they measure round-trip/network noise, not the server. All bench = t8 × c25 (200 conns).
Apparatus baked into `$J/sat_battery.sh`: config-readback assertion (`CONFIG GET tomokv-thread-io/
-ex` must equal the cell's request — `info threads` always shows 8 lines so it CANNOT gate config,
[[thredis-ab-harness-traps]] trap 7), both-binary version stamp in the log, fill-integrity check,
interleaved A/B/A/B. Pre-build gate: `git diff --stat HEAD` before every candidate build (trap 6).

## OWNER RULE (2026-08-12): BUILD PARITY with competitors — "if our competitors ship with pgo
## we do the same if not we do the same"

Comparison and shipped builds mirror the competitors' shipped build discipline. VERIFIED
2026-08-12 through Dragonfly's release chain (.github/workflows/release.yml -> tools/release.sh
-> Makefile `release:` target): **Dragonfly releases have NO PGO, NO LTO** — plain
CMAKE_BUILD_TYPE=Release with portability flags `-march=core2 -msse4.1 -mpopcnt
-mtune=skylake`; binary fingerprint agrees (GCC 14.3.0, ordinary .cold splitting only).
Redis/Valkey official builds are likewise plain -O2 class. THEREFORE: our default/comparison
build stays NON-PGO; the PGO/BOLT harness (dev @098e6722b: make pgo-generate/pgo-use +
tools/pgo_cycle.sh/bolt_cycle.sh; measured +10.4-15.0% p32, held-out mixed +10.8%) stays
in-repo as a validated OPTION, used only clearly-labeled and never in a published head-to-head
while the landscape is non-PGO. Garnet nuance: .NET's runtime does DYNAMIC PGO by default —
that is the platform, not a build choice; it does not trigger this rule. Re-verify competitor
pipelines whenever a comparison is published (their build could change; the parity fact is
dated). Corollary: -march/-mtune parity is the SAME rule — their shipped core2/skylake target
leaves Zen4 ISA headroom on the table, so a comparison built with -march=native on our side
would also break parity; match baselines or disclose flags.

**Cross-product head-to-head is NOT reliable on this box (decided 2026-06-21).** This laptop is an Intel Ultra X9 *hybrid*: cores 0-3 = P-cores, 4-15 = E-cores. The 8-core server set `taskset 0-7` is 4P+4E. Unpinned engines (Redis/Dragonfly/KeyDB) get Intel Thread Director to float hot threads onto the 4 P-cores; THredis pins statically (manual: workers→0..W-1, IO→W..W+IO-1), so 4/4 strands all 4 IO threads on E-cores and 5/3 lands one IO on a P-core. That asymmetry + high variance (5-min averages diverged badly from 15s bursts: no-pin 4/4 burst 3.50M vs steady 2.64M) makes head-to-head rankings untrustworthy here. **Decision: only test THredis-vs-THredis (relative deltas, same binary family, same box) on this machine; reserve cross-product comparison for homogeneous server HW (EPYC/TR), which is the paper target anyway.** Pin verdict: floating helped only modestly (+11% 1:1, +5% 1:9 at 4/4) and was jittery, so **pinning kept as the default** (`pin_mode 0`=manual, `1`=smart; the no-pin-default experiment was reverted). For IO-bound GET/SET the **IO/worker split matters more than pin-vs-float** (pinned 5/3 beat 4/4 by ~18%). One-shot cross-product snapshot (kept LOCAL, never pushed, per standing constraint): Dragonfly 3.77M/3.66M (1:1/1:9), Redis 2.85M/2.94M, THredis-opt 5/3-pin 2.79M/3.66M (ties Dragonfly at 1:9), KeyDB 1.40M/1.57M. memtier gotcha: Dragonfly binds IPv4 loopback only under protected mode → drive it with `-s 127.0.0.1` (default `localhost` picks ::1 for some conns → connection refused → 0 ops). Also saw an intermittent THredis worker-ring backpressure WEDGE under concentrated hot-key 4/4 1:9 (memtier blocks; retry succeeded at 3.11M) — wrap bench memtier in `timeout`.

**THERMAL DRIFT ⇒ INTERLEAVE IS MANDATORY (2026-06-21, the big one).** Under sustained load this box drifts **~15% downward run-to-run** (E-core throttling: round1 ~561k → round3 ~475k at fixed config). So **any single-run or sequential A/B of a <10% effect is unreliable** — the drift dwarfs the signal. RULE: for sub-10% effects, **interleave configs in back-to-back runs AND alternate order (AB/BA) with cooldowns, 3-4+ rounds**, then compare per-round and the mean; a real effect keeps the same sign every round, a wash flips sign within ±4%. This invalidated two "wins" measured by sequential A/B: **adaptive pf-w-value "+21%@4KB"** (washed: all widths ±2-3% within a round) and the **§14 cold-dict prefetch "+16%"** (washed: ON/OFF sign-flips ±4%). Only large effects survive sloppy measurement — jemalloc (+30-54%), LB (+133%), architecture. See [[thredis-prefetch-status]] and [[thredis-forwarding-deadend]].

**PINNING RULE (refined 2026-06-21, supersedes "only self-comparison"):** match THredis's pinning to the comparison so the hybrid P/E box is fair:
- **THredis-vs-THredis (self) → STATIC PINNED** (default `pin_mode 0` manual). Both sides identically pinned ⇒ relative deltas are clean; this is the canonical config. (All predictor/opt sweeps are self-comparisons ⇒ pinned.)
- **THredis-vs-Redis/Dragonfly/KeyDB (cross-product) → THredis FLOATED (no-pin)** so it gets the same Thread-Director→P-core placement the unpinned competitors get; a pinned THredis straddles P/E and is unfairly handicapped. Float mechanism: `pin_mode 2` = OFF (or env `THREDIS_NOPIN=1`); the no-pin-default revert kept manual as default but the float OPTION must exist for cross-product. (Earlier corrected Dragonfly run used pinned-THredis and noted "+~11% if floated" — per this rule it should have floated; redo cross-product floated.)
