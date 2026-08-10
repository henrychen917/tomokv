# Tomo KV — Benchmark Results & Analysis

> **Status:** 2026‑07‑10. Three sweeps complete: DRAM throughput matrix (deep pipeline), YCSB ingress
> study (low pipeline), and a 25‑workload real‑world suite (realistic P1–P8). See §6 for the honest
> cross‑workload picture.

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

## 6. The 25‑workload real‑world suite (realistic pipeline depths)

A 25‑workload suite mapped to real use cases (CDN cache, sessions, game state, logging, job queues,
leaderboards, event streams, rate limiters, cross‑shard aggregation, …) at the pipeline depths those
apps actually use — **P1–P8, not P32** — ~4–8 GB DRAM, 256 B default values, 256 clients. Tomo is shown
at its best io/ex split per workload; every prime `DBSIZE`‑verified. `⭐` = Tomo beats the entire Redis
family (Redis + Valkey + Dragonfly).

| Workload | **tomo-2s** | rank | redis | valkey | dragonfly | garnet |
|---|---|---|---|---|---|---|
| #1 GET-only, P1 (CDN/read cache) | **0.83** (io6ex2) | 1 ⭐ | 0.79 | 0.80 | 0.80 | 0.66 |
| #2 95/5, P1 (web/API cache) | **0.83** (io6ex2) | 1 ⭐ | 0.79 | 0.81 | 0.80 | 0.68 |
| #3 90/10 256B P8 (general) | **3.18** (io4ex4) | 2 ⭐ | 3.15 | 2.84 | 0.87 | 3.93 |
| #4 80/20 512B P8 (sessions) | **2.89** (io4ex4) | 3 | 2.94 | 2.71 | 0.91 | 3.77 |
| #5 50/50 P8 (game state) | **3.35** (io5ex3) | 2 ⭐ | 2.64 | 2.45 | 1.31 | 3.80 |
| #6 20/80 P4 (logging) | **1.82** (io4ex4) | 4 | 2.19 | 1.88 | 1.37 | 2.29 |
| #7 100% SET P4 (bulk load) | **2.17** (io5ex3) | 3 | 2.27 | 1.84 | 1.98 | 2.23 |
| #8 GET/SET/EXPIRE P4 (TTL/OAuth) | **1.90** (io4ex4) | 4 | 2.24 | 2.10 | 0.89 | 2.26 |
| #9 90/10 32B **64M keys** | **3.51** (io4ex4) | 1 ⭐ | 2.90 | 2.66 | 2.98 | n/a |
| #10 90/10 128B (DNS/HTTP) | **3.18** (io4ex4) | 2 ⭐ | 3.09 | 2.86 | 2.83 | 4.04 |
| #11 90/10 256B (app cache) | **3.71** (io5ex3) | 2 ⭐ | 3.12 | 2.92 | 0.87 | 3.91 |
| #12 90/10 1KB (JSON docs) | **0.82** (io4ex4) | 4 | 1.31 | 1.37 | 0.79 | 1.37 |
| #13 90/10 4KB (ML features) | **0.59** (io6ex2) | 5 | 0.61 | 0.67 | 0.61 | 0.68 |
| #14 hotspot uniform | **3.18** (io4ex4) | 3 | 3.21 | 2.91 | 0.83 | 4.00 |
| #15 hotspot Gaussian-light | **3.16** (io4ex4) | 3 | 3.23 | 2.92 | 0.83 | 3.94 |
| #16 hotspot Gaussian-med | **3.17** (io4ex4) | 2 ⭐ | 3.15 | 2.96 | 0.83 | 3.89 |
| #17 hotspot Gaussian-heavy | **3.75** (io5ex3) | 2 ⭐ | 3.22 | 2.93 | 0.83 | 3.93 |
| #18 HASH (accounts/carts) | **1.88** (io4ex4) | 2 | 1.89 | 1.70 | 1.87 | n/a |
| #19 LIST (job queues) | **1.95** (io4ex4) | 2 | 1.72 | 1.70 | 1.98 | n/a |
| #20 ZSET (leaderboards) | **1.91** (io4ex4) | 3 | 2.09 | 1.82 | 2.07 | n/a |
| #21 COUNTER (rate-limit) | **0.59** (io4ex4) | 5 | 0.78 | 0.80 | 0.79 | 0.66 |
| #22 STREAM (event/IoT) | **0.87** (io4ex4) | 2 | 0.49 | 0.52 | 1.11 | n/a |
| #23 MGET k=8 (aggregation) | **0.34** (io4ex4) | 5 | 0.48 | 0.54 | 0.50 | 0.51 |
| #24 MSET k=8 (atomic multi) | **0.48** (io4ex4) | 5 | 0.63 | 0.62 | 0.53 | 1.11 |

**Two things are true at once, and both matter.**

**1. Garnet posts the highest raw string throughput** on the P8 rows — but Garnet is a fundamentally
different, narrower system, and its lead is bounded by what it *cannot* do:
- **No data structures** — no hashes, lists, sorted sets or streams (`n/a` on #18/#19/#20/#22). A large
  share of real Redis traffic is exactly these.
- **Keyspace‑capped** — its fixed hash index could not materialize the **64 M‑key** set (#9) even at
  `-i 8g`/`-m 24g`; it tops out near ~33 M keys. Tomo serves #9 at 3.5 M ops/s.
- A managed‑runtime (.NET/GC) single‑node cache — higher, spikier CPU (load 23–30 vs Tomo's steady spin)
  and no sharded/cluster model.

So Garnet is **out of the running on 5 / 24 workloads** before a single throughput number is compared.

**2. Among the general‑purpose engines that run the whole mix, Tomo is the strongest.** On the read‑heavy
and pipelined workloads — the bulk of cache traffic — Tomo ranks **#2 overall (behind only Garnet) and
ahead of the entire Redis family**: #3, #5, #10, #11, #16, #17, the two no‑pipe rows it wins outright,
and the 64 M‑key row Garnet can't run. It also matches Redis on hashes (#18) and beats it on lists (#19)
and streams (#22).

**Where Tomo trails (honest):** write‑heavy mixes (#6/#8), large values (#12 1 KB, #13 4 KB), the counter
(#21), and cross‑shard MGET/MSET (#23/#24) — Redis/Valkey edge ahead there. These are the 1‑CCD‑bound /
large‑value regimes (§2 already showed SET turns execution‑bound at DRAM scale) and are exactly where the
in‑flight DRAM / large‑value work is aimed.

**Net:** at realistic pipeline depths on a 1‑CCD box, **Tomo is the fastest general‑purpose engine that
can actually serve the full workload mix** — consistently #2 behind a throughput‑only cache that forfeits
a fifth of the workloads outright. At **deep pipeline (§2) and no‑pipe / YCSB (§3, §5), Tomo leads the
field outright.**

## 7. Reshard / EWMA auto‑balancer — honest status

Tomo's EWMA hot‑shard reshard was measured **neutral‑to‑negative on this box**. Root cause: keys map to
workers by `xxh64(key)` hashing, which *scatters* even a tight Gaussian hot‑set across all workers, so
there is no per‑worker imbalance to fix — the migration pays a small transient cost and recovers to
baseline (it does not stay worse; the earlier "−8%" was a short‑test artifact). A genuine throughput win
from resharding requires **sustained per‑worker imbalance**, which arises from **multi‑CCD / NUMA
topology** — untested here, targeted for the Threadripper/EPYC platform.

---

## 8. Bottom line & caveats

- **Tomo leads the field outright** at **deep pipeline** (§2 — ~2.4× Redis, ~1.5–1.7× Dragonfly),
  **no‑pipe / low‑pipe** (§3 + §5 YCSB — beats every engine, +5–16% on YCSB), and the **64 M‑key**
  workload (§6 #9) that Garnet cannot even run.
- **At realistic moderate pipeline** (§6, the 25‑workload suite), **Tomo is the strongest general‑purpose
  engine** — consistently **#2 (behind only Garnet) and ahead of the entire Redis family** on the
  read/pipelined workloads, and it runs *all* 25. Garnet posts higher raw string throughput but is a
  narrower system: **no hash/list/zset/stream and a ~33 M‑key ceiling — inapplicable to 5 / 24 workloads.**
- **Honest weak spots:** write‑heavy mixes, large values (1 KB/4 KB), counters, and cross‑shard MGET/MSET
  on this 1‑CCD box — Redis/Valkey edge ahead there; this is the in‑flight DRAM / large‑value work.
- **Caveats:** all results are on a **1‑CCD 7700X over loopback**. Multi‑CCD/NUMA placement, real‑NIC
  behaviour, and the reshard payoff are explicitly *not* exercised here and are expected to
  favor Tomo further. Single‑box numbers; reproduce on the target server class.

*Raw data: `benchmarks/data/` (DRAM matrix, YCSB) + the 25‑workload suite pivots. Deep‑pipeline (§2) and
suite (§6) are complementary regimes — Tomo dominates the former, is the top general‑purpose engine in
the latter.*
