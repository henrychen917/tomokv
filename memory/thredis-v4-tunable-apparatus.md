---
name: thredis-v4-tunable-apparatus
description: THredis-opt-v4 = the tunable ablation apparatus; what each knob is and the laptop ablation findings
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis-opt-v4 (/home/henry/Projects/THredis-opt-v4) is the **tunable experimental
apparatus** for the paper's ablation — every optimization is a runtime knob, default =
v3 behavior. Built + ASAN-validated (oracles + toggle-storms, all 0-failure). Conf now
**4/4** (myiothreads 4, myworkerthreads 4) to match the paper. See [[thredis-opt-and-testers]],
[[thredis-paper-results-and-venue]], [[thredis-s8-two-reply-release-paths]].

KNOBS (all MODIFIABLE/runtime-safe unless noted; CONFIG SET sweepable on one live server):
- thredis-opt-{prefetch-worker,prefetch-io,hash-carry,value-forward,spsc-cache,
  coalesce-signal,batch-push,perthread-stats,zerocopy}  (9 bool toggles)
- thredis-opt-multi-cdb (S5, IMMUTABLE startup-only — per-worker reply masks; live flip
  would desync writer/clearer)
- thredis-pf-w-{struct,hash,entry,value,io-struct,io-reply} (per-STAGE prefetch widths, int)
- thredis-worker-pop-batch (1..16; decoupled from prefetch widths)
- value-forward trigger gates: thredis-vf-min-dictsize (#2 cache-cold proxy),
  thredis-vf-min-run, thredis-vf-min-write-permille (#3 recent-write-rate gate)
- thredis-vf-predictor (#4 branch-predictor-style: per-worker 2-bit-counter PHT indexed by
  key-hash XOR gshare history; learns per-key from op_0 lookup cost via rdtsc miss-classify),
  thredis-vf-predictor-miss-cycles
RUNTIME-TOGGLE TRAP (learned twice): a knob that caches/derives cross-thread state can crash
on live flip — spsc-cache (stale cached_tail/head; fixed by maintaining cache on the off-path)
and multi-cdb (made IMMUTABLE). Validate live toggling with a toggle-storm under ASAN.

LAPTOP ABLATION FINDINGS (Intel Ultra X9, 16c, SINGLE-NUMA, P=cores0-3 / E=cores4-15;
thermally throttles under sustained load — read DELTAS not absolutes; ~9% CoV):
META-CONCLUSION: the laptop exercises NONE of the conditions the opts target, so most read
~neutral here and their value is on EPYC + real workloads. v4 is the apparatus; the laptop's
job is correctness + the architecture baseline.
- v4 ALLON ≈ hard-coded v3 within <2% on every workload (toggles faithful).
- batch-push: best read helper (+3.7% GET-PIPE) but -1.2% on 1:1 MIX (latency-vs-throughput);
  spsc-cache +1.4%, coalesce/hash-carry +0.5-0.7% (all robust-but-small; GROW on multi-CCD).
- prefetch-worker: HURTS small L3-resident reads (disabling = +6%!), HELPS writes (+3.9%) and
  big-values; can't auto-gate (value size unknown pre-lookup) => deployment toggle. Per-stage
  widths ~noise here (no DRAM latency to hide); real payoff on EPYC/cache-missing.
- perthread-stats (S6), multi-cdb (S5): flat (single-NUMA; need multi-CCD).
- value-forward (#7): neutral-WITHIN-NOISE on random workloads (uniform/Gaussian rarely produce
  same-key runs). NEEDS real access patterns (skew/temporal/phases) to fire. The #4 predictor's
  history likewise needs real traces — on i.i.d. random it degrades to base-rate (no worse than
  a static gate, minus rdtsc cost). => evaluate VF/predictor on Zipfian/phasic/REAL CACHE TRACES
  (Twitter cluster trace, Meta CacheLib), NOT memtier-uniform. This is the EPYC-era eval.
- worker-pop-batch: 16 fine (best for writes, flat reads).

THredis-opt-v5 (forked from frozen v4) adds: tournament forward predictor
(thredis-vf-predictor-tournament: general bimodal + gshare history + chooser),
feedback-directed prefetch (thredis-opt-feedback-prefetch: per-key prefetch-useful
2-bit counters gate the value-chase), SHiP-style reuse predictor
(thredis-opt-ship-reuse: reuse_pht + keep-warm; anti-pollution clflush deferred),
the EX/expire fix [[thredis-ex-expire-fix]], and the trace replayer
(/home/henry/Projects/thredis-trace-replay: zipf/phasic/file modes, self-ID oracle).
All ASAN/oracle-validated incl. toggle-storms + replayer correctness.

ADAPTIVE SWEEP on PATTERNED workloads (replayer zipf θ0.99 + phasic; n=6; throttled
laptop, deltas <~5% shaky): FIRST workloads where the mechanisms can fire.
- VALUE-FORWARD VINDICATED: +5.5% (zipf), +4.1% (phasic) vs VFOFF — helps on realistic
  skewed/phasic patterns (was noise on uniform random; needs same-key runs to fire).
- simple predictor: +9.3% phasic (tracks read/write phase flips), ~0 zipf.
- tournament: mixed (+3.5% phasic, -6.2% zipf) — simple often beats it on this HW.
- feedback-prefetch: -9.3% zipf (per-read rdtsc overhead + over-throttle), ~0 phasic.
- SHiP: +2.3% zipf / -3.5% phasic (small/mixed).
- ALL combined: +7.0% zipf (best — composes), +1.6% phasic.
CAVEAT: single-NUMA + cache-resident + throttled; predictors' real test is EPYC + real
cache traces (cache-missing + true temporal locality) where prefetch/reuse should flip +.
