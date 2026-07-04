---
name: thredis-jemalloc-and-overnight-findings
description: "jemalloc is THredis's biggest throughput lever (works via LD_PRELOAD); THredis-jemalloc≈Dragonfly; cross-shard slowness root cause; dispatch-bound GET/SET; LB +133%"
metadata:
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Overnight sweep 2026-06-21 (full writeup: /home/henry/Projects/MORNING_REPORT.md, local-only, never pushed). Key durable facts:

- **jemalloc is the #1 throughput lever and now WORKS.** The bundled jemalloc 5.3.0 won't compile on this box's GCC 16 (C23 default kills old-style defs); instead `LD_PRELOAD=/usr/lib/libjemalloc.so.2` (system 5.3.1) routes all allocs through jemalloc — verified mapped into the process. **Any modern allocator (jemalloc/tcmalloc/mimalloc) is ~+50% (1:1) / ~+30% (1:9) over glibc malloc** on THredis 4/4 (8 threads contend on glibc arena locks). glibc is also the **least stable** (wedges far more). ⇒ ALL THredis benching must use jemalloc LD_PRELOAD; every earlier libc number was handicapped ~30-50%. To fix the bundled build: bump jemalloc to ≥5.3.1 or pass `-std=gnu17` to its configure (the `configure` exec-bit also gets stripped by distclean → `chmod +x`).
- **LD_PRELOAD jemalloc ALSO overrides Dragonfly's static mimalloc** (verified jemalloc mapped, mimalloc gone) → allocator-matched cross-product runs are possible.
- **THredis-on-jemalloc ≈ Dragonfly at GET/SET** (3.66M/3.95M vs 3.73M/3.75M @1:1/1:9, 1M gaussian, 8 cores) — the architecture was never behind; libc was the gap. Dragonfly keeps a p99 edge (~1.7ms vs ~2.8ms). On multi-key, Redis single-thread MGET (1.24M) > Dragonfly (380k) > THredis cross-shard (182k).
- **Cross-shard multi-key is pathologically slow — ROOT CAUSE: `dispatchCrossShard` calls a full `createFakeClient` per sub-key**, each allocating a client struct + 16KB PROTO_REPLY_CHUNK_BYTES reply buffer + a reply list ⇒ ~130KB alloc/free churn per MGET-of-8 (~20GB/s allocator traffic). NOT a sync bug. Single-key GET is fast because it uses preallocated inline ring-slot fakes. **Fix = per-IO-thread pool of recycled sub-clients** (csGetSub/csPutSub reset+reuse instead of create/free; sub lifetime is IO-thread-owned so an IO-local pool is safe). Designed + documented; NOT yet implemented (needs mkey_oracle + ASAN validation before porting to the live cross-shard path). Top next-step.
- **Small-value GET/SET is IO-DISPATCH-bound, not memory-bound:** DB size 100k→30M is ~flat even under uniform R:R (per-op DRAM lookup hides behind dispatch/parse/ring). Large values become memory-bandwidth-bound (~4.6 GB/s @64KB). Pipelining is the dominant lever (8× from pipe 1→16). ⇒ re-run the opt sweep in the LARGE-VALUE / BITCOUNT (worker-bound) regime — that's where the cache/coherence/prefetch opts should fire (they're ~noise on small-value GET/SET).
- **v8 ≈ paper-baseline (stable)** on small-value GET/SET (±noise; jemalloc, 4/4). Opt leave-one-out: only `batch-push` clearly helps (+3%); `prefetch-worker` HURTS (−3%); rest noise.
- **Load-balancer is the clearest THredis win: +133% under worker skew** (742k→1.74M, cload -w0). [[thredis-v8d-migration-validated]]
- **Predictor (vf): ~59% accuracy on gaussian-RANDOM** (near base-rate, by design) via the new `DEBUG RESHARD PREDACC` tool (added in THredis/ tree only, not yet in v8). Real-trace (Meta CacheLib) accuracy: see report §5.
- **Intermittent worker-ring WEDGE** under very high op-rate (>~3.5M/s, small-value 1:9 4/4 + multi-key): memtier blocks; `timeout`-wrap all bench memtier. glibc wedges far more than jemalloc. Proper fix = ring-full backpressure handling (concurrencykit ck_ring backoff — not installed).
- Tools now present/used: perf (paranoid=2 ok for user-space; splits cpu_core/cpu_atom), pahole (SPSC ring is false-sharing-free — validated), lstopo (18MB L3; P-cores private 3MB L2; E-clusters share 4MB L2), mimalloc/tcmalloc (LD_PRELOAD). Built: cload multi-key (-c mget/mset -k N), PREDACC. See also [[thredis-benchmarking-methodology]].
