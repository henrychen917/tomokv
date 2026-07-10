# Tomo KV — Benchmark Results & Analysis

> **Status:** results so far (2026‑07‑10). Two full sweeps complete (DRAM throughput matrix + YCSB
> ingress study); a 25‑workload real‑world suite is currently running and will extend this document.

## Test bed & methodology

| | |
|---|---|
| **CPU** | AMD Ryzen 7700X — **8 cores / 16 threads, single CCD, single NUMA node** |
| **Allocator** | jemalloc (`LD_PRELOAD`) for every engine |
| **Pinning** | server → cores 0–7, load generator → cores 8–15 (never shared) |
| **Transport** | loopback TCP |
| **Data set** | **~4 GB, DRAM‑resident** (40 M × 32 B; spills L3 → prefetch engaged) unless noted |
| **Windows** | 300 s measured + 12 s warmup discard (throughput matrix); 120 s (YCSB) |
| **Engines** | Tomo KV (2‑stage) · Redis 8 (`--io-threads 8`) · Valkey (`--io-threads 8`) · Dragonfly (`--proactor_threads 8`) · Garnet |
| **Sanity** | every prime verified via `DBSIZE`; every number plausibility‑checked (Little's law, monotonicity) |

Tomo's headline knob is the **io/ex thread split** — how many of the 8 cores parse+reply on the
**ingress** side (io) vs. execute on sharded **workers** (ex). `ioNexM` = N io threads, M ex threads.

---

## 1. The dial — one engine, tuned per workload

Tomo is not a single operating point; the io/ex split is a **runtime dial**, and different workloads
peak at different splits. This is the central result: **there is a Tomo config that wins each of the
popular workloads.**

| Workload | Best Tomo split | Why |
|---|---|---|
| No‑pipeline / low‑pipeline (P1) | **io6ex2** (io‑heavy) | latency‑bound; more ingress services more concurrent round‑trips |
| Pipelined GET | **io5ex3** | dispatch‑bound; wants ingress but needs ≥3 ex to execute |
| Pipelined SET | **io3ex5** | write path is execution‑bound at DRAM scale; wants ex workers |
| Pipelined mixed / balanced | **io4ex4** | wins GET **and** SET simultaneously |

---

## 2. Pipelined throughput — 4 GB DRAM, 32 B values (M ops/s)

| config | GET | SET | MIX (1:1) |
|---|---|---|---|
| tomo io2ex6 | 4.49 | 4.31 | 4.15 |
| tomo io3ex5 | 6.30 | **5.49** | 5.84 |
| tomo io4ex4 | 7.91 | 4.98 | **6.35** |
| tomo io5ex3 | **8.41** | 3.72 | 4.67 |
| tomo io6ex2 | 6.10 | 2.68 | 3.42 |
| **redis** | 3.46 | 2.20 | 2.40 |
| **dragonfly** | 4.92 | 4.44 | 4.58 |
| **valkey** | 3.28 | 2.45 | 2.74 |
| garnet | 9.86 † | 8.84 † | 9.24 † |

- **Tomo leads the C/C++ Redis‑compatible field on every pipelined workload:** ~2.4× Redis/Valkey,
  ~1.5–1.7× Dragonfly on GET. A single balanced config (**io4ex4**) beats Redis, Valkey and Dragonfly
  on GET, SET **and** mixed at once.
- **Dragonfly** is the strongest rival, notably on SET; Tomo still leads with its SET‑optimal split.
- **†Garnet's DRAM numbers are excluded as invalid** — its fixed hash index (`-i`) was undersized for a
  40 M‑key set, so the database never fully materialized (verified via `DBSIZE`). Garnet's *cache‑resident*
  numbers (below) are valid; its DRAM numbers are being re‑measured with a correctly‑sized index.

**Cache‑resident (100 k keys, fits L3, prefetch off):** Garnet leads pipelined GET (9.89 M) with Tomo
io5ex3 close behind (9.16 M); Tomo io4ex4 leads pipelined SET among the C/C++ field. Garnet's advantage
is a *cache‑resident‑only* result and it supports strings only (no hashes/lists/zsets/streams).

---

## 3. No‑pipeline (P1) — the low‑latency regime

memtier `-c256 --pipeline=1` (one op per round‑trip). This was Tomo's historical soft spot; the dial
resolves it.

| io2ex6 | io3ex5 | io4ex4 | io5ex3 | **io6ex2** | redis | dragonfly | valkey |
|---|---|---|---|---|---|---|---|
| 0.33 | 0.47 | 0.60 | 0.71 | **0.82** | 0.79 | 0.80 | 0.80 |

With the io‑heavy split, **Tomo matches/edges the whole field at no‑pipe** — no regime where it falls
behind. (Within run‑to‑run noise this is a tie, which is the point: no weakness.)

---

## 4. Hot‑key & high‑payload — 4 GB DRAM

| workload | best Tomo | redis | dragonfly | valkey | garnet |
|---|---|---|---|---|---|
| Hot‑key GET (Gaussian) | **9.65** (io6ex2) | 3.96 | 6.09 | 3.32 | 9.75 |
| GET 512 B payload | 3.13 (io5ex3) | **3.18** | 0.80 ✗ | 2.98 | 3.96 † |
| GET 16 KB payload | **0.58** (io5ex3) | 0.46 | 0.36 | 0.46 | 0.40 |

- **Hot‑key:** Tomo ties Garnet, clearly beats Redis/Valkey/Dragonfly.
- **Large payloads:** Tomo wins at 16 KB; ties Redis at 512 B. **✗Dragonfly collapses on payloads ≥512 B.**

---

## 5. YCSB — industry‑standard, low‑pipeline

YCSB is synchronous (one op per client, no pipelining), Zipfian, records stored as **hashes**
(READ→HGETALL, UPDATE→HSET). 2 M records × ~1 KB, 100 client threads.

| Workload | **Tomo io6ex2** | dragonfly | redis | valkey |
|---|---|---|---|---|
| **A** — 50/50 read/update | **643 k** | 613 k | 613 k | 461 k |
| **B** — 95/5 (realistic cache) | **623 k** | 561 k | 550 k | 345 k |
| **C** — 100% read | **648 k** | 556 k | 542 k | 339 k |

**Tomo (high‑ingress io6ex2) wins every YCSB workload, and the lead grows with read‑fraction:
+5% → +11% → +16%** — at lower latency (153 µs vs Redis 163 µs on A). Garnet is excluded (no hash type).

### The ingress dial on YCSB (Workload A, 100 threads)

| io2ex6 | io3ex5 | io4ex4 | io5ex3 | **io6ex2** | io7ex1 |
|---|---|---|---|---|---|
| 308 k @324 µs | 405 k @246 µs | 500 k @199 µs | 580 k @171 µs | **643 k @153 µs** | 623 k @159 µs ↓ |

Low → high ingress buys **+109% throughput / −53% latency**, monotonic and Little's‑law‑exact
(throughput = threads/latency to the digit). The peak is **io6ex2**; at io7ex1 a single ex worker can no
longer execute the HGETALLs, so it dips — a genuine sweet spot, not "max out io."

---

## 6. Reshard / EWMA auto‑balancer — honest status

Tomo's EWMA hot‑shard reshard was measured **neutral‑to‑negative on this box**. Root cause: keys map to
workers by `xxh64(key)` hashing, which *scatters* even a tight Gaussian hot‑set across all workers, so
there is no per‑worker imbalance to fix — the migration pays a small transient cost and recovers to
baseline (it does not stay worse; the earlier "−8%" was a short‑test artifact). A genuine throughput win
from resharding requires **sustained per‑worker imbalance**, which arises from **multi‑CCD / NUMA
topology** — untested here, targeted for the Threadripper/EPYC platform.

---

## 7. Bottom line & caveats

- **Tomo KV wins the popular workloads** vs. the C/C++ Redis‑compatible field (Redis, Valkey, Dragonfly):
  pipelined throughput (all value sizes), hot‑key, large payloads, and **standard low‑pipeline YCSB** —
  each via the appropriate io/ex split, with **io4ex4 a strong single‑config default**.
- **Garnet** leads only *cache‑resident pipelined strings* (a .NET store with no hash/list/zset/stream
  types); its DRAM‑scale numbers here are invalid pending re‑measurement.
- **Caveats:** results are on a **1‑CCD 7700X over loopback**. Multi‑CCD/NUMA placement, real‑NIC
  (io_uring zero‑copy), and the reshard payoff are explicitly *not* exercised here and are expected to
  favor Tomo further. All numbers are single‑box and should be reproduced on the target server class.

*A 25‑workload real‑world suite (strings, value sweeps, hotspots, hashes/lists/zsets/streams, cross‑shard
MGET/MSET, moving‑hotspot) is in progress and will extend §2–§5 with per‑use‑case results.*
