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
(maximally ingress‑provisioned `io6ex2` **overtakes Redis on every DRAM read cell**).

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
| Tomo `io5ex3` | 3.08 | 3.09 | **1.26** | 3.08 |
| Tomo `io4ex4` | 2.53 | 2.52 | **1.26** | 2.51 |
| Tomo `io6ex2` *(ingress‑extreme)* | **3.44** | **3.55** | 1.22 | **3.43** |
| Tomo `io2ex6` *(execution‑extreme)* | 1.41 | 1.40 | 0.77 | 1.39 |
| Redis 8 | 3.23 | 3.36 | **1.27** | 3.21 |
| Dragonfly | 0.87 | 0.81 | 0.63 | 2.20 |

Here the moderate splits land **within ~5 % of Redis** and tie on 4 KB; Redis keeps a small edge on flat
512 B reads at *those* splits — but the ingress‑heavy extreme **`io6ex2` beats Redis on all three DRAM read
cells** (512 B 1:9 3.44 vs 3.23, hot‑key 3.55 vs 3.36, FB‑ETC 3.43 vs 3.21); dial ingress up when the
workload is purely I/O‑bound. The worker‑heavy extreme `io2ex6` collapses here — 2 ingress threads can't
feed the pipeline (the starvation cliff). This regime is
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

Tomo KV adds runtime knobs on top of every standard Redis directive. **Sensible defaults ship on** — most
knobs exist for research and per‑workload tuning, not day‑to‑day use. The ones that matter most:

### Threading & topology
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-io-threads` | auto | Number of **ingress** threads (parse + dispatch + reply). |
| `tomokv-ex-threads` | auto | Number of **EX worker** threads (must be a power of two). |
| `tomokv-pipeline-depth` | max | Per‑connection in‑flight command ring depth. |
| `tomokv-ex-queue-depth` | max | Per‑(io,worker) SPSC dispatch queue depth. |
| `tomokv-pin-mode` | 2 | Core‑pinning strategy (dense / shared‑L3‑aware). |
| `tomokv-worker-pop-batch` | 16 | Max commands a worker drains per queue per sweep. |

### Reply backend
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-io-uring` | off | Master switch for the io_uring backend (build with `USE_URING=yes`). |
| `tomokv-io-uring-reply-send` | off | Send replies via io_uring instead of epoll `write()`. |
| `tomokv-io-uring-recv` | off | Multishot io_uring receive with provided buffer rings. |
| `tomokv-io-uring-zc` / `-sqpoll` | off | Zero‑copy send (≥ threshold) / kernel submission polling. |

### Prefetch pipeline
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-opt-prefetch-worker` | on | Master switch for the worker prefetch pipeline. |
| `tomokv-prefetch-adaptive-min-keys` | auto | Enable prefetch only once a shard exceeds this key count (DRAM‑bound). |
| `tomokv-pf-fc` / `-argv` / `-cmd` / `-keyobj` | on | Individual pass‑1 prefetch stages. |
| `tomokv-pf-w-struct` / `-hash` / `-entry` / `-value` | 256 | Per‑stage prefetch window widths. |
| `tomokv-pf-w-nextop` | 256 | Execution‑adjacent next‑op look‑ahead distance. |
| `tomokv-opt-hash-carry` | on | Compute each key's hash once; reuse through dispatch + lookup. |

### Dispatch & reply de‑contention
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-opt-batch-push` | on | Stage worker pushes, one tail release per batch. |
| `tomokv-batch-push-eager` | on | Publish the staged batch at end of parse (kills worker starvation). |
| `tomokv-opt-coalesce-signal` | on | Coalesce per‑parent reply‑ready signals. |
| `tomokv-opt-spsc-cache` | on | Producer‑side SPSC index caching (avoids cross‑core loads). |
| `tomokv-opt-multi-cdb` / `tomokv-num-cdb` | off / auto | Spread reply signaling across multiple CDB cache lines. |
| `tomokv-opt-perthread-stats` | on | Cache‑line‑isolated per‑thread counters (no false sharing). |

### Advanced
Cross‑shard (`tomokv-opt-cross-shard`, `-cross-setop`, `-fanall`), online resharding
(`tomokv-reshard-auto` and the `tomokv-reshard-*` family), memory (`tomokv-operand-pool`,
`tomokv-zerocopy-min-value`), and a suite of research/experimental predictors
(`tomokv-vf-*`, `tomokv-opt-ship-reuse`, `tomokv-opt-feedback-prefetch`) are available and default‑off.
Run `redis-server --help` or see `config.c` for the full surface.

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
