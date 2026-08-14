# EPYC first light — 2026-08-14

Box: AMD EPYC 9754 (Bergamo, Zen 4c), 128c/256t, 16 CCDs (8 cores + 16 MB L3 each),
128 GB, **NPS1** (single NUMA node — CCDs are the only locality domains). Frequency is
firmware-controlled (~3.1 GHz observed, no cpufreq interface). Noise floor: **±0.15%**
across interleaved A/A (20 s cells) — far quieter than the 7700X desktop (±2%).

Layout: server = CCDs 0–7 (cpus 0–63), one node per CCD (`tomokv-nodes 8`, io4/ex4 per
node, static), loadgen = memtier 64t×4c pinned cpus 64–127. SMT siblings idle.
Config: `bench-epyc.conf`. Dataset: 120 M keys, 64 B values ≈ 16.7 GB (DRAM-bound).

## Bugs found (in priority order)

### 1. Per-node probe clustering (P0, FIXED in tree, not committed)
The dispatch router and the flat table consume the SAME xxh64: node = a contiguous
range of `h & 0x3FFF` buckets, slot = `h & mask`. At `tomokv-nodes 8` every key a node
owns has hash bits 11–13 frozen, so only 1/8 of its table slots are natural homes
(2048-slot runs every 16384) — effective load factor 8× nominal inside the home runs.
Measured: **~6,600 probes/lookup** (IPC 6.1, 82% of worker cycles in
`flatFindForWrite`) at a nominal 60% LF. Invisible at nodes=1 (old box); one frozen
bit at the old 2-node sims.

Fix: `flat_slot_start(h, mask)` (murmur3 fmix64 finalizer) in flatstore.h; probe
starts in flatGet/flatFindForWrite (+full-wrap fallback), and the three home-line
computations in the prefetch machinery (server.c). Tag bits (49+) untouched.

Effect at 10 M × 32 B: GET p32 7.9M → 21.4M (2.7×), SET p32 6.9M → 17.5M (2.5×),
populate 1.8M → 8.1M SET/s.

### 2. `tomokv-pin-mode ccd` counts SMT siblings as cores (P1, open)
On this box it treats each CCD's 16 logical CPUs as 16 cores AND enumerates L3 domains
non-contiguously: an 8-node/64-thread server landed on 4 physical CCDs (0, 1, 12, 13)
with IO and EX sharing physical cores via hyperthreads. Workaround: `pin-mode static`
with explicit physical-core specs (see bench-epyc.conf). Fix needed: filter
`thread_siblings` to one CPU per core and sort L3 domains by first CPU.

### 3. Big-DB sustained-SET tail (#122, confirmed here)
16 GB populate sustains 5.97 M SET/s but p99.9 = 133 ms, **p99.99 = 2.39 s** across 88
resizes. Dragonfly's same populate: 9.3 M SET/s with p99.99 = 5.1 ms. The resize/
reclaim stall dominates the write tail at scale. (Steady-state SET p32 p99.99 is fine:
2.7 ms.)

### 4. p1 (unpipelined) per-request latency gap vs Dragonfly (open)
Tomo 113 µs avg vs dfly 80 µs at 256 conns loopback ⇒ 2.2M vs 3.2M ops/s p1 (−41%
GET / −50% SET). The IO→EX handoff round-trip is on every request's critical path;
dfly runs shard-local in the proactor. Not worker-bound (workers ~idle at p1).

## TomoKV vs Dragonfly v1.39 — 16 GB, 64 B values, 64 threads each, same cells

Throughput (ops/s) and latency (ms): avg / p50 / p99 / p99.9 / p99.99

| Cell | TomoKV | Dragonfly | Tomo/Dfly |
|---|---|---|---|
| GET p1  | 2.25M — .11/.11/.24/.30/.40 | 3.17M — .08/.08/.12/.16/.32 | **0.71×** |
| SET p1  | 2.12M — .12/.11/.27/.34/.38 | 3.19M — .08/.08/.12/.16/.29 | **0.66×** |
| GET p32 | 19.9M — .38/.37/.78/1.03/1.26 | 7.78M — 1.04/.99/1.90/2.83/4.03 | **2.56×** |
| SET p32 | 15.1M — .53/.50/1.21/1.48/2.74 | 9.50M — .85/.82/1.46/2.45/3.50 | **1.59×** |
| 1:9 p32 | 16.9M — .46/.41/.96/1.30/1.88 | 7.84M — 1.03/.98/1.92/2.93/4.02 | **2.15×** |

Under pipeline Tomo wins throughput AND every latency percentile; unpipelined dfly
wins both.

## Knob A/B at 16 GB (interleaved, ±0.15% floor)

- `tomokv-reorder 2`: GET p32 **+2.4%**, mixed 1:9 **+2.3%**, hot-key (gaussian)
  +2.2% — first box where reorder pays. Level 3 = level 2 throughput with a worse
  tail. Recommend default 2 on multi-CCD (pending regime sweep).
- `tomokv-prefetch-ex 0/1/2`: wash (±1%) at 64 B values, including level 2
  (cross-node message prefetch). `tomokv-prefetch-io 1/2`: wash.

## Standing caveats
- p1 cells are connection-count-bound (256 conns × loopback RTT); they measure
  per-request latency, not capacity.
- Per-worker law: ~620k ops/s/worker here (GET p32, DRAM-bound 16 GB) vs ~2M on the
  7700X at cache-resident sizes — re-derive the census on this box before using it.
- Single-run cells except where marked interleaved; box noise ±0.15% makes 20 s cells
  trustworthy for >1% deltas.
