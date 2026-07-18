<div align="center">

# Tomo KV · 2‑Stage

**A Tomasulo‑style, out‑of‑order key‑value engine built on the Redis 8 command surface.**

*Parse and dispatch on ingress threads · execute out‑of‑order on sharded workers · commit replies in issue order.*

`2‑stage io↔ex pipeline` · `RESP‑compatible` · `epoll or deep io_uring`

</div>

---

## What is Tomo KV?

**Tomo KV** ("Tomasulo KV") is a fork of Redis that replaces the single‑threaded command loop with a
**hardware‑inspired, out‑of‑order execution pipeline**. It keeps Redis's data structures, RESP protocol, and
on‑disk formats, but runs commands the way a superscalar CPU runs instructions: many at once, out of order
across independent units, yet **observably in order** to every client.

Its defining feature is a single tunable knob — **how you split your cores between *ingress* threads
(parse / dispatch / reply) and *execution* workers (run commands on owned shards)** — which lets you match
the engine to your workload's bottleneck. No fixed‑model engine offers this: Redis only scales I/O threads
(execution stays single‑threaded); Dragonfly and Garnet are rigid.

The **2‑Stage** edition is the lean, low‑latency member of the family. See [the family](#the-tomo-kv-family)
for the throughput‑oriented **3‑Stage** variant that adds a dedicated write‑back / reorder‑buffer stage.

---

## Architecture

Tomo KV is a direct translation of **Tomasulo's out‑of‑order execution algorithm** (IBM System/360 Model 91,
1967) into a key‑value server. The mapping is one‑to‑one, and the code names its structures after the
hardware they emulate (the reply bus is literally `reply_cdb`, the Common Data Bus; the 3‑Stage write‑back
thread is aliased `tomokv-rob-threads`, the Reorder Buffer):

| CPU (Tomasulo)                     | Tomo KV                                                                        |
| :--------------------------------- | :---------------------------------------------------------------------------- |
| Instruction stream                 | Pipelined RESP command stream on a connection                                 |
| Issue / dispatch                   | **Ingress (io) thread** parses RESP and routes each command by key            |
| Register file, partitioned         | **Per‑worker key‑shards** — each worker owns a disjoint slice of the keyspace  |
| Reservation stations / exec units  | **EX worker threads** executing against their own shard, in parallel          |
| Hazard avoidance (RAW/WAR/WAW)     | **Single‑writer‑per‑shard**: one key ⇒ one worker ⇒ no cross‑worker hazards    |
| Common Data Bus (CDB)              | **`reply_cdb`** — the mask bus workers use to signal completion               |
| Reorder buffer, in‑order commit    | **Per‑connection pipeline ring + `flushid`** — replies retire in issue order  |

```
                        ┌──────────────────────── ingress (io) thread ─────────────────────────┐
   client ── RESP ──►   │  recv → parse → route by key(hash) → dispatch          reply‑reorder  │  ──► client
   (SO_REUSEPORT,       │        │                                 │             (flushid ring)  │
    one io thread       │        │  SPSC queue per (io,worker)      │  ▲ reply‑ready (CDB bus)    │
    per connection)     └────────┼─────────────────────────────────┼──┼─────────────────────────┘
                                 ▼                                  │  │
                        ┌─────── EX worker 0 ───────┐   ┌─────── EX worker 1 ───────┐   ...
                        │  owns key‑shard 0         │   │  owns key‑shard 1         │
                        │  execute cmd->proc()      │   │  execute cmd->proc()      │   (N workers,
                        │  prefetch pipeline        │   │  prefetch pipeline        │    out of order)
                        └───────────────────────────┘   └───────────────────────────┘
```

**Stage 1 — Ingress (io threads).** Each connection is pinned for life to one io thread via a per‑thread
`SO_REUSEPORT` listener (the kernel load‑balances new connections across threads). The io thread reads,
parses RESP, computes the key hash, and **dispatches** each command into a lock‑free SPSC queue for the
worker that owns that key's shard. It also drains completed replies and writes them back to the socket,
reordered into issue order.

**Stage 2 — Execute (EX workers).** Each worker owns a disjoint partition of the keyspace and is its sole
mutator. It pops a batch of commands, warms caches with a multi‑pass software prefetch pipeline, executes
`cmd->proc()` directly against its shard, and signals completion on the Common Data Bus. No locks, no
cross‑worker synchronization on the data path.

**Reply commit.** Completed commands retire through a per‑connection ring. The ingress thread advances a
`flushid` cursor over the ready‑prefix and splices replies onto the socket **strictly in issue order**, so a
command that finished early on an idle shard never overtakes an earlier command still running on a busy one.
Replies leave over one of two interchangeable backends — classic **epoll** `write()`, or a
**deeply‑integrated io_uring** send path (ring‑per‑thread, batched submits, registered ring fd).

**Correctness.** Because each key is owned by exactly one worker, there are no locks on the data path and no
cross‑worker hazards. Commands to *different* keys execute fully in parallel and out of order; commands to
the *same* key (or one connection) are serialized and committed to the socket in the exact order the client
sent them. **Linearizability per key and FIFO per connection are preserved** — the client cannot tell the
work was reordered, exactly as a program cannot tell its instructions were.

---

## Performance

> 📊 **Latest results & analysis:** see **[BENCHMARKS.md](BENCHMARKS.md)** — three regimes on a 1‑CCD
> 7700X: the **DRAM throughput matrix** (deep pipeline — Tomo ~2.4× Redis), the **YCSB ingress study**
> (low pipeline — Tomo wins all workloads +5–16%), and a **25‑workload real‑world suite** (realistic
> P1–P8 — Tomo is the strongest general‑purpose engine, consistently #2 behind Garnet, a throughput‑only
> cache with no data structures and a ~33 M‑key ceiling). Honest per‑workload table + weak spots inside.

Every number below is single node, loopback, **AMD Ryzen 7 7700X** (8 cores / 1 CCD); server and load
generator (`memtier_benchmark`) each pinned to a disjoint set of 8 hyperthreads; **jemalloc on every
binary**; median of interleaved reps, each sanity‑gated against its expected range (contended reads
discarded and re‑run). Five workloads, five tables — each shows **all five 8‑core Tomo splits** against
**Redis 8** (`io-threads 8`), **Dragonfly** (`proactor_threads 8`), **Garnet**, and **Valkey**
(`io-threads 8`). All figures are **M ops/s**, higher is better.

Because the ingress/execution split is Tomo's defining knob, read these tables as *one story*: **different
workloads want different splits, and Tomo is the only engine that can retune to match.** Dispatch‑bound work
wants ingress; execution‑bound work wants workers.

### 1 · No pipeline (P1)

*Method: GET/SET 32 B, **pipeline = 1**, 2 M‑key cache‑resident DB, `-t8 -c64`. Latency‑hiding comes from
512 concurrent connections, so throughput here is bounded by per‑command overhead, not latency.*

| Config | GET 32 B | SET 32 B |
| :--- | :--- | :--- |
| Tomo `io2ex6` | 0.33 | 0.32 |
| Tomo `io3ex5` | 0.47 | 0.47 |
| Tomo `io4ex4` | 0.60 | 0.59 |
| Tomo `io5ex3` | 0.71 | 0.70 |
| **Tomo `io6ex2`** | **0.82** | **0.81** |
| Redis 8 | 0.79 | 0.79 |
| Dragonfly | 0.80 | 0.79 |
| Garnet | 0.67 | 0.64 |
| Valkey | 0.81 | 0.80 |

No‑pipe throughput is **io‑thread‑bound** — every command pays its own `recv`/`send`/`epoll`, and execution
is idle. So it is *monotone in ingress share* (0.33 → 0.82, a 2.5× swing) and the dial is the whole story:
at ingress‑heavy `io6ex2`, Tomo **leads the field** (0.82, past Valkey/Dragonfly ~0.80 and Garnet 0.67).
The balanced `io4ex4` under‑provisions ingress here and trails — that is a config choice, not an
architectural limit. Enabling the io_uring backend lifts Tomo `io6ex2` to **0.84** (its batched submit
reclaims the per‑command syscalls that pipelining otherwise amortizes — the one loopback regime where
io_uring beats epoll); Dragonfly's io_uring is flat vs its own epoll (0.80). *(Only Tomo and Dragonfly have
an io_uring data path; Redis/Valkey/Garnet are epoll‑only.)*

### 2 · Pipelined (P32)

*Method: GET/SET 32 B and 1:1 mixed, **pipeline = 32**, 2 M‑key cache‑resident DB, `-t8 -c25`.*

| Config | GET | SET | GET/SET 1:1 |
| :--- | :--- | :--- | :--- |
| Tomo `io2ex6` | 4.38 | 4.23 | 4.10 |
| Tomo `io3ex5` | 6.34 | 5.99 | 5.91 |
| **Tomo `io4ex4`** | **7.92** | 6.04 | 6.63 |
| Tomo `io5ex3` | 7.78 | 4.95 | 5.62 |
| Tomo `io6ex2` | 5.45 | 3.78 | 3.91 |
| Redis 8 | 3.59 | 2.38 | 2.59 |
| Dragonfly | 5.75 | 5.25 | 5.42 |
| **Garnet** | **9.90** | **8.83** | **9.43** |
| Valkey | 3.21 | 2.45 | 2.76 |

Deep pipelining amortizes the per‑command syscalls and the io→ex hop, so this is where raw execution
throughput shows. **Garnet leads** — its no‑hop shared‑store design (the network thread executes the store
op inline, made safe by epoch reclamation instead of sharding) has no dispatch hop to pay. Tomo's balanced
`io4ex4` is **second and comfortably beats Dragonfly, Redis, and Valkey**; the dial peaks around
`io4ex4`/`io5ex3` where ingress and execution are matched to this 32 B, both‑bound workload.

### 3 · DRAM‑resident

*Method: GET 512 B (2 M keys, ~1 GB) and GET 4 KB (1 M keys, ~4 GB) — working sets well past the 32 MB L3 —
**pipeline = 16**, `-t8 -c25`.*

| Config | GET 512 B | GET 4 KB |
| :--- | :--- | :--- |
| Tomo `io2ex6` | 1.36 | 0.79 |
| Tomo `io3ex5` | 2.01 | 1.03 |
| Tomo `io4ex4` | 2.56 | **1.27** |
| Tomo `io5ex3` | 3.11 | 1.18 |
| **Tomo `io6ex2`** | **3.64** | 1.18 |
| Redis 8 | 3.29 | 1.12 |
| Dragonfly | 0.82 | 0.60 |
| Garnet | **3.97** | 0.68 |
| Valkey | 3.17 | 0.95 |

Larger values make this I/O‑bound, so throughput is again monotone in ingress share (dial up for the send
work). At 512 B, Garnet leads with **Tomo `io6ex2` close behind (3.64)** and past Redis/Valkey; at **4 KB
Tomo `io4ex4` wins outright (1.27)** — the ingress/execution hop amortizes on large values and the
zero‑copy send path pays. Dragonfly collapses above 256 B (0.82 / 0.60) — a known artifact of its
reply‑builder capping the coalescing buffer, which fragments large‑value sends into many syscalls.

### 4 · Hot key

*Method: **DRAM‑resident 8 M‑key DB (~724 MB)**, GET/SET 32 B, **pipeline = 32**, with a tight Gaussian
key distribution (median 4 M, σ = 3 → a ~18‑key hot set — a "viral item," not one key). Tomo is shown with
its **EWMA hot‑shard auto‑reshard off / on**, plus the reshards it fired; competitors have no equivalent.*

| Config | hot GET (off / on) | hot SET (off / on) | reshards fired |
| :--- | :--- | :--- | :--- |
| Tomo `io2ex6` | 4.46 / 4.38 | 4.19 / 4.00 | 6 |
| Tomo `io3ex5` | 6.22 / 6.22 | 5.79 / 5.82 | 0 |
| Tomo `io4ex4` | 7.81 / 7.20 | 7.20 / 7.22 | 3 |
| Tomo `io5ex3` | 9.14 / 9.16 | 8.05 / 7.95 | 0 |
| **Tomo `io6ex2`** | **9.64** / 8.20 | 5.62 / 5.94 | 1 |
| Redis 8 | 3.94 | 2.78 | — |
| Dragonfly | 6.15 | 5.30 | — |
| Garnet | 9.52 | 7.91 | — |
| Valkey | 3.36 | 2.52 | — |

Two honest findings here. **(1)** A realistic hot‑key skew *does not bottleneck sharding for anyone*:
because keys are hash‑distributed, even a tight Gaussian spreads across all shards, so every engine runs at
~its balanced throughput and the ingress dial dominates (hot‑key GET is dispatch‑bound → `io6ex2` tops it at
9.64, essentially tying Garnet's 9.52). Only a literal single hammered key — not a real workload — bottlenecks
a shard‑per‑thread engine (there Dragonfly drops to ~2.8 M while Tomo's io/ex split holds ~8 M).
**(2) The EWMA reshard is net‑negative on this box.** When it fires (see the reshards column) it *costs*
a few percent (io6ex2 9.64 → 8.20); when it stays idle the two columns are identical. On a single‑CCD,
hash‑sharded engine the hot set is already balanced, so the controller is chasing transient noise and paying
migration cost with no real hot *shard* to relieve. Its value is genuine sustained imbalance — the
multi‑CCD / skewed‑population case — which is why it is a knob (`tomokv-reshard-min-ops`), default‑on but
trivially disabled.

### 5 · Non‑standard commands

*Method: `BITCOUNT` on 16 KB strings (50 k keys), `HGETALL` on 80‑field hashes (10 k keys), `ZRANGE 0 -1`
on 80‑member sorted sets (10 k keys), **pipeline = 16**, `-t8 -c25`.*

| Config | `BITCOUNT` 16 KB | `HGETALL` (80 f) | `ZRANGE` (80 m) |
| :--- | :--- | :--- | :--- |
| **Tomo `io2ex6`** | 2.08 | **0.51** | **0.96** |
| Tomo `io3ex5` | **2.16** | 0.50 | 0.95 |
| Tomo `io4ex4` | 1.98 | 0.50 | 0.94 |
| Tomo `io5ex3` | 1.68 | 0.47 | 0.83 |
| Tomo `io6ex2` | 1.27 | 0.37 | 0.65 |
| Redis 8 | 2.18 | 0.22 | 0.41 |
| Dragonfly | 0.72 | 0.49 | 0.87 |
| Garnet | **3.31** | *n/a* | *n/a* |
| Valkey | 1.73 | 0.105 | 0.30 |

This is the **mirror image of table 1**: compute‑ and reassembly‑heavy commands are *execution‑bound*, so
the **worker‑leaning splits win** (`io2ex6`/`io3ex5` top every column) — exactly the opposite of dispatch‑bound
GET wanting ingress. That is the dial's whole point. Tomo beats Redis **~2.3×** on `HGETALL` and `ZRANGE`
(the worker does the field/member reassembly in parallel) and matches it on `BITCOUNT` (a single‑integer
reply, so dispatch‑bound). Garnet tops `BITCOUNT` but **does not implement hashes or sorted sets** (n/a).

### Honest scope

All numbers are single‑node **loopback on one CCD**. The de‑contention machinery, the worker‑heavy end of
the dial, and the io_uring / EWMA‑reshard knobs are designed to pay on **multi‑CCD / real‑NIC** hardware
(cross‑CCD transfers cost ~100–200 cycles vs cheap shared‑L3 here); that evaluation is pending on a
Threadripper‑class box. Validation before every number: correctness round‑trips + a reconnect‑storm churn
stress + (for structural changes) an AddressSanitizer pass. Results inconsistent with the mechanism or with
neighbouring measurements are investigated and re‑run, never reported.

---

## Under the hood

Every optimization is an independent, runtime‑gated knob (see [Configuration](#configuration)). They fall
into a few families:

- **Out‑of‑order core.** Per‑worker keyspace partitioning, lock‑free SPSC dispatch queues with producer‑side
  index caching, single‑writer shards, and the CDB reply‑reorder protocol — the foundation everything else
  sits on.
- **Software‑pipelined prefetch.** A multi‑pass, gem5‑style prefetch engine runs on the worker just ahead of
  execution: it warms the command's fake‑client struct, argv, command descriptor, and key object, then
  chases the dict bucket → entry → value across a tunable window, plus an execution‑adjacent *next‑op*
  look‑ahead. A DB‑size‑adaptive gate turns it off for cache‑resident shards and on when the working set
  spills to DRAM. Hash‑carry computes each key's hash once and reuses it through dispatch and lookup.
- **Dispatch & reply de‑contention.** Staged batch‑push with **eager per‑batch publish** (keeps cross‑CCD
  store‑batching without starving idle workers), per‑parent reply‑signal coalescing, a multi‑bus CDB to
  spread reply signaling across cache lines, batched mask clears, cache‑line‑isolated per‑thread counters to
  kill false sharing, and an **adaptive reply‑drain spin** that removes the non‑pipelined latency floor.
- **Self‑tuning ingress/reply controllers** *(merged, all default `-1`=auto).* Five continuous controllers on
  the ingress and fake‑ring path, each with a strict override: a **userspace CDB drain‑spin**
  (`tomokv-io-drain-userpoll`, replaces the epoll‑syscall reply‑wait with EWMA‑gated userspace re‑checks), a
  **drain tail‑skip** (`tomokv-drain-tail-skip`), an **express‑slim** state‑move for GET/SET keyed on the
  live hit‑rate (`tomokv-express-slim`), a **per‑connection fake‑ring depth** demand‑grow/decay
  (`tomokv-fake-ring-depth`), and a **per‑connection fake‑buf width** auto‑sizer (`tomokv-fake-buf`). Measured
  neutral on single‑CCD loopback (P1 there is io‑thread‑bound, not reply‑poll‑bound — turn the dial instead);
  designed to pay on the multi‑CCD / real‑NIC eval.
- **Zero‑copy & large values.** Value objects can be forwarded to the ingress thread without a copy above a
  size threshold, with ownership returned to the owning worker via a free‑back ring so refcounts are only
  ever touched by the shard's owner.
- **Multi‑key & cross‑shard.** Every multi‑key command is split into per‑shard sub‑commands, dispatched in
  parallel, and reassembled — driven by a **per‑command registry** (one table stamps classification,
  scatter geometry and reply shape) rather than a hand‑maintained list. Reads (`MGET`/`EXISTS`/`TOUCH`/
  `SINTER`/`SUNION`/`SDIFF`) gather in a single hop; writes run a **two‑hop phase machine** (gather → coordinator
  compute → single‑writer destination write) that preserves single‑writer‑per‑shard and never lets a live
  object cross a thread — values cross as private serialized bytes. Served cross‑shard: `MSET`/`DEL`/`UNLINK`,
  conditional moves (`RENAME`/`RENAMENX`/`COPY`/`SMOVE`), read‑then‑store (`SINTERSTORE`/`SUNIONSTORE`/
  `SDIFFSTORE`/`SINTERCARD`, `ZUNION`/`ZINTER`/`ZDIFF` ±`STORE`, `ZINTERCARD`), byte/HLL ops (`BITOP`,
  multi‑key `PFCOUNT`, `PFMERGE`), list moves (`LMOVE`/`RPOPLPUSH`, `MSETNX`) and ordered pops
  (`LMPOP`/`ZMPOP`); blocking variants (`BLMOVE`/`BLMPOP`/…) reply the immediate result when data is
  available and the timed‑out form when they would block (no cross‑shard client parking). A **SAFE‑GATE**
  (`thredis-xshard-guard`, default on) rejects any remaining unported multi‑key command with a clear error
  instead of letting it run against the empty decoy DB. `FLUSHALL`/`FLUSHDB` are handled by queue‑ordered
  flush sentinels.
- **Kernel integration.** `SO_REUSEPORT` connection load‑balancing, `TCP_NODELAY`, taskset‑aware core pinning
  with shared‑L3/CCD awareness, NUMA‑local worker binding, and an optional **deep io_uring** reply path
  (multishot recv, `SEND_ZC`, `SQPOLL`, registered ring fd).
- **Online resharding.** Live key‑shard migration (effect‑log copy + drain‑fence cutover) with a dual‑rate‑EWMA
  hot‑shard auto‑tuner, for rebalancing genuinely skewed keyspaces without downtime (see table 4 for its
  workload‑dependence). Opt‑in trigger hardening (sustain window, Schmitt hysteresis, cool‑margin) suppresses
  spurious ping‑pong on marginal imbalance. The cross‑shard writes above stay correct across a live cutover:
  in‑range writes are captured to the migration effect log and held at the drain fence exactly like every
  single‑key write.

---

## Configuration

Tomo KV follows one convention across its whole config surface, borrowed from CPU micro‑architecture:
**every adaptive quantity has a hardware‑style AUTO mode (a continuous controller — saturating counters,
leaky/EWMA integrators, multiplicative grow‑decay — driven only by *current* signals, so a workload that
shifts on a dime re‑tunes within batches) and a STRICT number mode** (you pin the value, adaptation off).
KV workloads are unpredictable at runtime; nothing calibrates‑then‑locks, and no controller accumulates
history that makes it slow to change its mind.

Value conventions: **mandatory** = you must set it (fatal at boot if unset) · **`-1` = AUTO** where `0`
means *off* · **`0` = AUTO** where off is meaningless · explicit `N` = strict.

### Threading & topology (set these — they are the deliberate choices)

| Knob | Values | Meaning |
| :--- | :--- | :--- |
| `tomokv-io-threads` | **mandatory** ≥ 1 | Ingress threads (parse/dispatch/reply). No default — the io/ex split is the most consequential decision you make (see the performance section). |
| `tomokv-ex-threads` | **mandatory** ≥ 1, **any count** | Execution workers (one shard each). Sharding is the point of this server: `0` is rejected at boot — use upstream Redis for a single-executor deployment. |
| `tomokv-pin-mode` | `0` float · `1` manual · `2` auto (default) | `0`: no pinning, the scheduler decides. `1`: pin to the exact cores in `tomokv-pin-cores`. `2`: arch‑aware auto — topology‑smart placement (shared‑L3/CCD grouping, NUMA‑local shard memory), respecting taskset/cgroup affinity. |
| `tomokv-pin-cores` | e.g. `"0,2,4,6"` | Manual core list for pin‑mode 1, applied in thread‑pin order (io threads first, then workers), round‑robin if short. |
| `tomokv-pipeline-depth` | `0` auto (default) · pow2 ≤ 32 | Per‑connection in‑flight ring. Auto resolves to the max (32) — a deeper ring never hurts shallow clients, it only costs idle memory, and the per‑connection demand‑grow/decay controller (`tomokv-fake-ring-depth`) trims the live slots back down. |
| `tomokv-ex-queue-depth` | `0` auto (default) · pow2 ≤ 65536 | io→worker SPSC queue size. Auto resolves to 2048. |

### Batching, spin & prefetch (AUTO controllers with strict overrides)

| Knob | Values | Meaning |
| :--- | :--- | :--- |
| `tomokv-worker-pop-batch` | `0` auto (default) · 1–16 strict | Fakes a worker pops per queue visit. Auto: saturating up/down controller (full batch ⇒ double the cap; sparse pass ⇒ halve) — 2‑bit‑predictor flavor. |
| `tomokv-worker-spin` | `0` auto (default) · N strict rounds | Worker idle spin before yielding. Auto: multiplicative budget (spin that paid grows ×1.5, wasted window halves). |
| `tomokv-pf-w-struct/-argv/-keyobj/-keybytes/-hash/-entry` | `-1` auto (default) · `0` off · N strict | Per‑stage scoreboard‑prefetcher widths. Auto: width = the *current* batch occupancy — zero history, re‑tunes on the next batch. |
| `tomokv-pf-w-value` | `-1` auto (default) · `0` off · N strict cap | Value‑chase width. Auto: cache‑budget controller — width = (L3 / 2·workers) / EWMA(value size), leaky integrator, refreshed continuously. |
| `tomokv-pf-w-nextop` | `-1` auto · `0` off (default) · N strict | Next‑op lookahead prefetch distance. Auto: lookahead = current batch. |
| `tomokv-prefetch-min-keys` | `0` auto (default) · N strict | Prefetch enable gate. Auto: opens when the shard's self‑measured footprint (dbSize × (96 B + EWMA value size)) exceeds 8× the machine's detected L3 — prefetching a cache‑resident shard measurably hurts. |
| `tomokv-pf-value-budget-kb` | `0` auto (default) · N strict | The value‑chase cache budget. Auto: L3 / (2 × workers). |
| `tomokv-l3-kb` | `0` auto‑detect (default) · N strict | L3 size feeding the controllers. Pin it on VMs that hide cache topology from sysfs. |
| `tomokv-io-drain-userpoll` | `-1` auto (default) · `0` syscall‑only · N userpoll passes | Reply‑wait drain mode. Auto: EWMA of in‑flight replies with a Schmitt band picks userspace re‑checks vs an epoll syscall. |
| `tomokv-drain-tail-skip` | `-1`/`1` auto (default) · `0` legacy | Skip the tail drain pass when work is already pending. |
| `tomokv-express-slim` | `-1` auto (default) · `0` off · 1–100 fixed pct | Slim state‑move for GET/SET, engaged when the live GET+SET hit‑rate clears the threshold (auto: EWMA + Schmitt). |
| `tomokv-fake-ring-depth` | `-1` auto (default) · `0` eager · N fixed | Per‑connection live fake‑ring depth. Auto: lazy‑create, demand‑grow on stall, decay at empty‑ring checkpoints. |
| `tomokv-fake-buf` | `-1` auto (default) · `0` 16 KB legacy · N bytes | Per‑connection fake output‑buffer width. Auto: demand‑grow at the spill site (capped). |

### Load balancing (self‑driving reshard controller)

| Knob | Values | Meaning |
| :--- | :--- | :--- |
| `tomokv-reshard-min-ops` | `0` off · N ops/s (default 20000) | Significance floor + master switch. Everything else self‑derives: EWMA rates with a continuously recomputed alpha, an outlier trigger bar (mean + k·σ with a relative floor), settle windows in controller time — no calibration, no lock‑in. Workload‑dependent (see table 4); `0` disables it. |
| `tomokv-reshard-imbalance-pct` | `0` auto (default) · N strict | Trigger bar override: fixed percent‑of‑mean instead of the outlier bar. |
| `tomokv-reshard-chunk` | `0` auto (default) · N strict | Migration granule. Auto: buckets/(16·workers), clamped. |
| `tomokv-reshard-sustain-ticks` | `0` legacy (default) · `-1` auto · N ticks | Require K consecutive outlier ticks before firing (opt‑in trigger hardening). |
| `tomokv-reshard-progress-ratio` | `0` legacy (default) · N pct | Keep migrating a hotspot only while the peak keeps shrinking by ≥ this fraction. |
| `tomokv-reshard-cool-margin-pct` | `0` legacy (default) · `-1` auto · N pct | Schmitt cool‑margin: the neighbour must sit below mean·(1−N/100) to receive a move. |

### Reply path & memory

| Knob | Values | Meaning |
| :--- | :--- | :--- |
| `tomokv-num-cdb` | `0` auto (default) · N strict | Reply‑bus count. Auto: one bus per worker on multi‑CCD machines (de‑contention), a single bus on one CCD (nothing to de‑contend). Topology is machine identity, read once. |
| `tomokv-zerocopy-min-value` | `0` off · N bytes (default 1024) | Zero‑copy reply threshold — strict by design: the copy‑vs‑bookkeeping crossover is a machine property, not a workload signal (measured ~1 KB here). |
| `tomokv-opt-operand-pool` | bool (default off) | Argv‑operand recycling pool (tiered, demand‑grow, op‑clocked decay — the same controller style). Hardwired ON in the 3‑Stage edition; gated here pending 2‑Stage validation. |

### Kernel / io_uring (experimental, default off)

`tomokv-io-uring`, `-sqpoll`, `-recv`, `-zc`, `tomokv-io-uring-reply-send`, `tomokv-worker-direct-send`,
`tomokv-os-opts`, `tomokv-os-busypoll` — io_uring network backend and OS tuning experiments; all immutable
booleans, all default off. Loopback‑neutral except at P1 (see table 1); they exist for real‑NIC evaluation.

---

## Building & running

```sh
# Standard build (epoll backend)
make -j

# With the io_uring backend enabled
make -j USE_URING=yes

# Run a 2-stage instance: 6 ingress threads, 4 workers
./src/redis-server --tomokv-io-threads 6 --tomokv-ex-threads 4 \
                   --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048

# Talk to it with any Redis client
./src/redis-cli set hello world
./src/redis-cli get hello
```

Tomo KV builds and runs like stock Redis and speaks unmodified RESP2/RESP3, so existing clients,
`redis-cli`, and `memtier_benchmark` work as‑is. jemalloc is the recommended allocator (bundled).

---

## Compatibility & scope

Tomo KV targets the **sharded, high‑throughput data‑plane** use case. The full string/hash/list/set/zset
command set runs on the worker path, and the multi‑key surface (moves, read‑then‑store set/zset ops, byte/HLL
ops, list moves, ordered pops) is served **cross‑shard** through the scatter‑gather registry described above.
Blocking commands are served non‑blocking (immediate result, or the timed‑out form rather than parking a
client across shards). Features that assume a single global keyspace or a serial main thread — cluster mode,
replication/AOF propagation, pub/sub, keyed scripting, and multi‑key `SCAN` — remain outside scope. Every
multi‑key command that has **no** correct cross‑shard implementation is rejected loudly by the SAFE‑GATE
(`thredis-xshard-guard`) rather than served incorrectly against the decoy keyspace. This is a research engine
focused on the parallel‑execution thesis, not a drop‑in replacement for every Redis deployment.

---

## The Tomo KV family

| Edition | Pipeline | Best for |
| :--- | :--- | :--- |
| **Tomo KV · 2‑Stage** (this) | ingress → execute (replies on the ingress thread) | Low latency, small values, dispatch‑bound traffic. |
| **Tomo KV · 3‑Stage** | ingress → execute → **write‑back / ROB** (dedicated reply stage) | High throughput, larger / send‑bound values. |

Both share the same out‑of‑order core, optimization set, and RESP surface; they differ only in whether reply
commit runs on the ingress thread (2‑Stage) or on a dedicated reorder‑buffer thread (3‑Stage).

---

## Credits

Tomo KV is a research fork of **[Redis](https://github.com/redis/redis)** (8.x) and inherits its data
structures, protocol, and BSD‑3‑Clause license. The out‑of‑order architecture is inspired by
**Tomasulo's algorithm** (R. M. Tomasulo, *"An Efficient Algorithm for Exploiting Multiple Arithmetic
Units,"* IBM Journal, 1967). Original Redis © Redis Ltd.; Tomo KV modifications retain the upstream license.
