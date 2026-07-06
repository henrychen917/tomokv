<div align="center">

# Tomo KV · 2‑Stage

**A Tomasulo‑style, out‑of‑order key‑value engine built on the Redis 8 command surface.**

*Parse and dispatch on ingress threads · execute out‑of‑order on sharded workers · commit replies in issue order.*

`2‑stage io↔ex pipeline` · `RESP‑compatible` · `epoll or deep io_uring`

</div>

---

## What is Tomo KV?

**Tomo KV** ("Tomasulo KV") is a fork of Redis that replaces the single‑threaded command loop with a
**hardware‑inspired, out‑of‑order execution pipeline**. It keeps Redis's data structures, RESP protocol,
and on‑disk formats, but runs commands the way a modern superscalar CPU runs instructions: many at once,
out of order across independent units, yet **observably in order** to every client.

The key insight is an old one from computer architecture. A CPU core sustains high throughput on a serial
instruction stream by (1) **partitioning state** so independent instructions don't conflict, (2) executing
them **out of order** on multiple functional units, and (3) using a **reorder buffer** to retire results in
program order. A single‑threaded KV store like Redis faces the same problem — a serial stream of commands,
most of them independent — and Tomo KV applies the same solution.

The **2‑Stage** edition is the lean, low‑latency member of the family: a two‑stage pipeline (ingress →
execute) where the ingress thread also emits replies. See [the family](#the-tomo-kv-family) for the
throughput‑oriented 3‑Stage variant that adds a dedicated write‑back / reorder‑buffer stage.

---

## Inspiration: Tomasulo's algorithm, as a database

Tomo KV is a direct, deliberate translation of **Tomasulo's out‑of‑order execution algorithm** (IBM
System/360 Model 91, 1967) into a key‑value server. The mapping is one‑to‑one — the code names its
structures after the hardware they emulate (the reply bus is literally `reply_cdb`, the **Common Data
Bus**; the 3‑Stage write‑back thread is aliased `tomokv-rob-threads`, the **Reorder Buffer**).

| CPU (Tomasulo)                     | Tomo KV                                                                    |
| :--------------------------------- | :------------------------------------------------------------------------ |
| Instruction stream                 | Pipelined RESP command stream on a connection                             |
| Issue / dispatch                   | **Ingress (io) thread** parses RESP and routes each command by key        |
| Register file, partitioned         | **Per‑worker key‑shards** — each worker owns a disjoint slice of the keyspace |
| Reservation stations / exec units  | **EX worker threads** executing against their own shard, in parallel      |
| Hazard avoidance (RAW/WAR/WAW)     | **Single‑writer‑per‑shard**: one key ⇒ one worker ⇒ no cross‑worker hazards |
| Common Data Bus (CDB)              | **`reply_cdb`** — the mask bus workers use to signal completion           |
| Reorder buffer, in‑order commit    | **Per‑connection pipeline ring + `flushid`** — replies retire in issue order |

Because each key is owned by exactly one worker, there are no locks on the data path and no cross‑worker
data hazards to resolve. Commands to *different* keys execute fully in parallel and out of order; commands
to the *same* key (or on one connection) are serialized and their replies are committed to the socket in
the exact order the client sent them. **Linearizability per key and FIFO per connection are preserved** —
the client cannot tell the work was reordered, exactly as a program cannot tell its instructions were.

---

## Architecture — the 2‑stage pipeline

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

**Stage 1 — Ingress (io threads).** Each connection is pinned for life to one io thread via a
per‑thread `SO_REUSEPORT` listener (the kernel load‑balances new connections across threads). The io
thread reads, parses RESP, computes the key hash, and **dispatches** each command into a lock‑free SPSC
queue for the worker that owns that key's shard. It also drains completed replies and writes them back to
the socket, reordered into issue order.

**Stage 2 — Execute (EX workers).** Each worker owns a disjoint partition of the keyspace (its own set of
`redisDb` shards) and is the sole mutator of that partition. It pops a batch of commands, warms caches with
a multi‑pass software prefetch pipeline, executes `cmd->proc()` directly against its shard, and signals
completion on the Common Data Bus. No locks, no cross‑worker synchronization on the data path.

**Reply commit.** Completed commands retire through a per‑connection ring. The ingress thread advances a
`flushid` cursor over the ready‑prefix and splices replies onto the socket **strictly in issue order**, so
a command that finished early on an idle shard never overtakes an earlier command still running on a busy
one.

Replies leave the server over one of two interchangeable backends: classic **epoll** `write()`, or a
**deeply‑integrated io_uring** send path (ring‑per‑thread, batched submits, registered ring fd). The
backend is a runtime choice; correctness is identical.

---

## Performance & the ingress/execution split

Tomo KV's performance is inseparable from its defining knob: **how you split your cores between
*ingress* threads (parse / dispatch / reply) and *execution* workers (run commands on owned shards).**
So this section presents both together — the benchmarks, and the split that shapes them.

*Methodology.* Single node, loopback, AMD Ryzen 7 7700X (8 cores, single CCD); server and load
generator each capped at 8 threads; `memtier_benchmark`; **jemalloc on every binary**; 3 interleaved
reps (median reported), each number sanity‑gated against its normal range (contended reads discarded
and re‑run). Baselines: Redis 8 (`io-threads 8`) and Dragonfly (`proactor_threads 8`).

### The knob — a CPU‑architecture idea

You size ingress vs execution the way a CPU architect sizes fetch/decode/issue width against the number
of execution units — to match *your* workload's bottleneck. No fixed‑model engine offers this: Redis
only scales I/O threads (execution stays single‑threaded); Dragonfly is a rigid shard‑per‑core model. On
8 cores we show three moderate splits — **`io5ex3`** (ingress‑leaning), **`io4ex4`** (balanced),
**`io3ex5`** (execution‑leaning). The **extremes** `io6ex2` (ingress‑heavy) / `io2ex6` (worker‑heavy) are included below as edge rows: on a
low‑core box each starves the opposite stage and usually loses — but they mark the ceiling of the dial
(maximally ingress‑provisioned `io6ex2` **overtakes Redis on the small/mid‑value DRAM read cells** — 512 B 1:9, hot‑key, FB‑ETC; Redis keeps 4 KB).

### Dispatch‑ and compute‑bound — where Tomo KV wins outright

Small‑value pipelined ops and CPU‑heavy commands (**M ops/s**, higher is better):

| Config | GET 32 B | GET/SET 1:1 32 B | `BITCOUNT` 16 KB | `HGETALL` (80 f) | `ZRANGE` (80 m) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tomo `io5ex3`** | **8.09** | 5.77 | **3.88** | 0.47 | 0.82 |
| **Tomo `io4ex4`** | 7.73 | **6.66** | 3.30 | **0.50** | **0.90** |
| Tomo `io3ex5` | 6.04 | 5.61 | 2.54 | 0.48 | 0.88 |
| Tomo `io6ex2` *(ingress‑extreme)* | 5.05 | 3.96 | 3.38 | 0.37 | 0.64 |
| Tomo `io2ex6` *(execution‑extreme)* | 4.27 | 3.96 | 1.77 | **0.50** | 0.68 |
| Redis 8 | 4.40 | 2.75 | 2.21 | 0.28 | 0.48 |
| Dragonfly | 5.76 | 5.41 | 1.08 | 0.46 | 0.82 |

Best‑split Tomo beats Redis **1.8× GET, 2.4× mixed, 1.8× `BITCOUNT`, 1.8× `HGETALL`, 1.9× `ZRANGE`**, and
beats Dragonfly on every cell. And **the split is the story**: ingress‑leaning `io5ex3` wins the
dispatch‑bound reads (GET, and `BITCOUNT` — its reply is a single integer, so it's dispatch‑bound); balanced
`io4ex4` wins writes and big‑reply commands (mixed, `HGETALL`, `ZRANGE` — the worker does the
mutation/serialization while ingress handles the larger sends). One knob spans both; no single Redis or
Dragonfly configuration does.

### DRAM‑resident — matched, not beaten (on 1‑CCD loopback)

Working set ~6 GB (512 B × 8 M keys, 4 KB × 1.4 M keys, pipeline 16):

| Config | 512 B 1:9 | hot‑key | 4 KB 1:9 | FB‑ETC |
| :--- | :--- | :--- | :--- | :--- |
| Tomo `io5ex3` | 3.08 | 3.09 | 1.26 | 3.08 |
| Tomo `io4ex4` | 2.53 | 2.52 | 1.26 | 2.51 |
| Tomo `io3ex5` | 1.96 | 1.96 | 1.05 | 1.95 |
| Tomo `io6ex2` *(ingress‑extreme)* | **3.44** | **3.55** | 1.22 | **3.43** |
| Tomo `io2ex6` *(execution‑extreme)* | 1.41 | 1.40 | 0.77 | 1.39 |
| Redis 8 | 3.23 | 3.36 | **1.27** | 3.21 |
| Dragonfly | 0.87 | 0.81 | 0.63 | 2.20 |

This regime is purely I/O‑bound, and the table shows the cleanest demonstration of the dial in the whole
document: throughput is **monotone in ingress share** — 3.44 (`io6ex2`) → 3.08 (`io5ex3`) → 2.53 (`io4ex4`)
→ 1.96 (`io3ex5`) → 1.41 (`io2ex6`). Honest read against Redis: only the ingress ladder's top competes —
**`io6ex2` beats Redis on 512 B 1:9 / hot‑key / FB‑ETC** (3.44/3.55/3.43 vs 3.23/3.36/3.21) while Redis
keeps 4 KB 1:9 (1.27 vs 1.22); `io5ex3` lands within ~5–8 %; balanced and execution‑leaning splits trail by
~20–40 % — as they should, since their cores are deliberately spent on execution this workload never uses.
Dial ingress up for pure I/O‑bound work; the worker‑heavy extreme `io2ex6` marks the starvation cliff
(2 ingress threads can't feed the pipeline). This regime is
I/O‑bound — the value never fits a register‑cheap execution step, so it wants ingress, exactly the dial
Tomo exposes. (hot‑key = Gaussian‑concentrated GETs; FB‑ETC = a Facebook‑ETC‑like mix: 1:30 write:read,
Gaussian keys, small‑skewed value sizes. Dragonfly's low ≥ 256 B pipelined‑GET numbers are a known
loopback reply‑path artifact — its 32 B GET and FB‑ETC results are representative.)

### Honest scope

All numbers are single‑node **loopback on one CCD**. The de‑contention machinery and the worker‑heavy end
of the dial are designed to pay on **multi‑CCD / real‑NIC** hardware (cross‑CCD transfers ~100–200 cycles
vs cheap shared‑L3 here); that evaluation is pending on a Threadripper‑class box. Validation before every
number: correctness (round‑trips, MGET, expiry, DEL, FLUSHDB) + a reconnect‑storm churn stress + (for
structural changes) an AddressSanitizer pass. Results inconsistent with the mechanism or with neighbouring
measurements are investigated and re‑run, never reported.

## Optimizations

Every optimization is an independent, runtime‑gated knob (see [Configuration](#configuration)). They fall
into a few families:

- **Out‑of‑order core.** Per‑worker keyspace partitioning, lock‑free SPSC dispatch queues with producer‑side
  index caching, single‑writer shards, and the CDB reply‑reorder protocol — the foundation everything else
  sits on.
- **Software‑pipelined prefetch.** A multi‑pass, gem5‑style prefetch engine runs on the worker just ahead
  of execution: it warms the command's fake‑client struct, argv, command descriptor, key object, then
  chases the dict bucket → entry → value across a tunable window, plus an execution‑adjacent *next‑op*
  look‑ahead. A DB‑size‑adaptive gate turns it off for cache‑resident shards and on when the working set
  spills to DRAM. Hash‑carry computes each key's hash once and reuses it through dispatch and lookup.
- **Dispatch & reply de‑contention.** Staged batch‑push with **eager per‑batch publish** (keeps cross‑CCD
  store‑batching without starving idle workers), per‑parent reply‑signal coalescing, a multi‑bus CDB to
  spread reply signaling across cache lines, batched mask clears, and cache‑line‑isolated per‑thread
  counters (dirty/stats) to kill false sharing.
- **Zero‑copy & large values.** Value objects can be forwarded to the ingress thread without a copy above a
  size threshold, with ownership returned to the owning worker via a free‑back ring so refcounts are only
  ever touched by the shard's owner.
- **Multi‑key & cross‑shard.** `MGET`/`MSET`/`DEL`/`EXISTS`/`UNLINK`/`TOUCH` and set operations are split
  into per‑shard sub‑commands, dispatched in parallel, and reassembled — with `FLUSHALL`/`FLUSHDB` handled
  by queue‑ordered flush sentinels.
- **Kernel integration.** `SO_REUSEPORT` connection load‑balancing, `TCP_NODELAY`, taskset‑aware core
  pinning with shared‑L3/CCD awareness, NUMA‑local worker binding, and an optional **deep io_uring** reply
  path (multishot recv, `SEND_ZC`, `SQPOLL`, registered ring fd).
- **Online resharding.** Live key‑shard migration (effect‑log copy + drain‑fence cutover) with an optional
  dual‑rate‑EWMA hot‑shard auto‑tuner, for rebalancing skewed keyspaces without downtime.

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
| `tomokv-pipeline-depth` | `0` auto (default) · pow2 ≤ 32 | Per‑connection in‑flight ring. Auto resolves to the max (32) — a deeper ring never hurts shallow clients, it only costs idle memory; the per‑connection demand‑grow/decay ring controller (grow on ring‑full stall, decay at empty‑ring checkpoints) is the queued follow‑up. |
| `tomokv-ex-queue-depth` | `0` auto (default) · pow2 ≤ 65536 | io→worker SPSC queue size. Auto resolves to 2048 (same roadmap note as above). |

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

### Load balancing (self‑driving reshard controller)

| Knob | Values | Meaning |
| :--- | :--- | :--- |
| `tomokv-reshard-min-ops` | `0` off · N ops/s (default 20000) | Significance floor + master switch. Everything else self‑derives: EWMA rates with a continuously recomputed alpha, an outlier trigger bar (mean + k·σ with a relative floor), settle windows in controller time — no calibration, no lock‑in. |
| `tomokv-reshard-imbalance-pct` | `0` auto (default) · N strict | Trigger bar override: fixed percent‑of‑mean instead of the outlier bar. |
| `tomokv-reshard-chunk` | `0` auto (default) · N strict | Migration granule. Auto: buckets/(16·workers), clamped. |

### Reply path & memory

| Knob | Values | Meaning |
| :--- | :--- | :--- |
| `tomokv-num-cdb` | `0` auto (default) · N strict | Reply‑bus count. Auto: one bus per worker on multi‑CCD machines (de‑contention), a single bus on one CCD (nothing to de‑contend). Topology is machine identity, read once. |
| `tomokv-zerocopy-min-value` | `0` off · N bytes (default 1024) | Zero‑copy reply threshold — strict by design: the copy‑vs‑bookkeeping crossover is a machine property, not a workload signal (measured ~1 KB here). |
| `tomokv-opt-operand-pool` | bool (default off) | Argv‑operand recycling pool (tiered, demand‑grow, op‑clocked decay — the same controller style). Hardwired ON in the 3‑Stage edition; gated here pending 2‑Stage validation. |

### Kernel / io_uring (experimental, default off)

`tomokv-io-uring`, `-sqpoll`, `-recv`, `-zc`, `tomokv-io-uring-reply-send`,
`tomokv-os-opts`, `tomokv-os-busypoll` — io_uring network backend and OS tuning experiments; all
immutable booleans, all default off. Loopback‑neutral in our measurements; they exist for real‑NIC
evaluation. The rings are built in the "fully exploited" shape (`IORING_SETUP_SINGLE_ISSUER |
DEFER_TASKRUN` with plain‑ring fallback probing, registered ring fd, one batched submit per flush
pass); multishot recv arms with `IORING_RECVSEND_POLL_FIRST`; zero‑copy send detaches the reply
buffer on submit (registered‑buffer pool, `SEND_ZC[_FIXED]`) and reaps `F_NOTIF` completions
asynchronously on later passes.

| knob | values | meaning |
|---|---|---|
| `tomokv-uring-bufring` | `0` auto (512) · N (default 0) | Provided‑buffer ring size per IO thread for multishot recv; rounded up to a power of two, clamped to [64, 65536]. Boot log reports the effective size; an `ENOBUFS ... re-armed` notice means raise it. |
| `tomokv-uring-zc-min` | N bytes (default 1024) | Minimum reply size for zero‑copy send — below it a copying send beats ZC's notif CQE + bookkeeping (same ~1 KiB machine property as `tomokv-zerocopy-min-value`). Modifiable at runtime. |

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
command set runs on the worker path. Features that assume a single global keyspace or a serial main thread —
cluster mode, replication/AOF propagation, blocking commands, pub/sub, scripting, and multi‑key `SCAN` — are
outside the current scope; where a command cannot be served correctly under sharding it is rejected with a
clear error rather than served incorrectly. This is a research engine focused on the parallel‑execution
thesis, not a drop‑in replacement for every Redis deployment.

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
