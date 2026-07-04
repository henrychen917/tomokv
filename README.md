<div align="center">

# Tomo KV · 3‑Stage

**A Tomasulo‑style, out‑of‑order key‑value engine built on the Redis 8 command surface.**

*Issue on ingress threads · execute out‑of‑order on sharded workers · commit replies in issue order from a dedicated reorder‑buffer stage.*

`3‑stage ifid↔ex↔wb pipeline` · `RESP‑compatible` · `epoll or deep io_uring`

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

The **3‑Stage** edition is the throughput‑oriented member of the family. It adds a **dedicated write‑back
stage** — a true hardware‑style **Reorder Buffer (ROB)** thread — so that reply reordering and socket sends
run off the ingress thread's critical path. This decouples receive/parse from send, which pays off most on
larger, send‑bound values and high fan‑out. See [the family](#the-tomo-kv-family) for the leaner 2‑Stage
variant.

---

## Inspiration: Tomasulo's algorithm, as a database

Tomo KV is a direct, deliberate translation of **Tomasulo's out‑of‑order execution algorithm** (IBM
System/360 Model 91, 1967) into a key‑value server. The mapping is one‑to‑one — the code names its
structures after the hardware they emulate. The reply bus is literally `reply_cdb`, the **Common Data
Bus**; the write‑back stage is aliased `tomokv-rob-threads`, the **Reorder Buffer**.

| CPU (Tomasulo)                     | Tomo KV · 3‑Stage                                                          |
| :--------------------------------- | :------------------------------------------------------------------------ |
| Instruction stream                 | Pipelined RESP command stream on a connection                             |
| **Issue** / dispatch               | **ifid (ingress) thread** parses RESP and routes each command by key      |
| Register file, partitioned         | **Per‑worker key‑shards** — each worker owns a disjoint slice of the keyspace |
| Reservation stations / **execute** | **EX worker threads** executing against their own shard, in parallel      |
| Hazard avoidance (RAW/WAR/WAW)     | **Single‑writer‑per‑shard**: one key ⇒ one worker ⇒ no cross‑worker hazards |
| Common Data Bus (CDB)              | **`reply_cdb`** — the mask bus workers use to signal completion           |
| **Reorder buffer**, in‑order commit | **WB thread** (`tomokv-rob-threads`) reorders + writes back replies in issue order |

Because each key is owned by exactly one worker, there are no locks on the data path and no cross‑worker
data hazards to resolve. Commands to *different* keys execute fully in parallel and out of order; commands
to the *same* key (or on one connection) are serialized and their replies are committed to the socket in
the exact order the client sent them. **Linearizability per key and FIFO per connection are preserved** —
the client cannot tell the work was reordered, exactly as a program cannot tell its instructions were.

---

## Architecture — the 3‑stage pipeline

```
                ┌──── ifid (issue) thread ────┐        ┌──── WB / ROB thread ────┐
 client ─RESP─► │ recv → parse → route → issue│        │ reorder (flushid) →     │ ─► client
 (SO_REUSEPORT) │        │                     │        │ write‑back replies      │
                └────────┼─────────────────────┘        └──────────▲──────────────┘
                         │  SPSC queue per (ifid,worker)           │ reply‑ready (CDB bus)
                         ▼                                         │
                ┌─── EX worker 0 ───┐   ┌─── EX worker 1 ───┐   ┌─── EX worker 2 ───┐   ...
                │ owns key‑shard 0  │   │ owns key‑shard 1  │   │ owns key‑shard 2  │   (N workers,
                │ execute + prefetch│   │ execute + prefetch│   │ execute + prefetch│    out of order)
                └───────────────────┘   └───────────────────┘   └───────────────────┘
```

**Stage 1 — Issue (ifid threads).** Each connection is pinned for life to one ifid thread via a
per‑thread `SO_REUSEPORT` listener (the kernel load‑balances new connections across threads). The ifid
thread reads, parses RESP, computes the key hash, and **issues** each command into a lock‑free SPSC queue
for the worker that owns that key's shard. Unlike the 2‑Stage design, it does **not** send replies — it
returns immediately to receiving and parsing, keeping ingress off the reply critical path.

**Stage 2 — Execute (EX workers).** Each worker owns a disjoint partition of the keyspace (its own set of
`redisDb` shards) and is the sole mutator of that partition. It pops a batch of commands, warms caches with
a multi‑pass software prefetch pipeline, executes `cmd->proc()` directly against its shard, and signals
completion on the Common Data Bus. No locks, no cross‑worker synchronization on the data path.

**Stage 3 — Write‑back (WB / ROB threads).** One or more dedicated write‑back threads act as the reorder
buffer. A WB thread watches the CDB for completed commands, advances a per‑connection `flushid` cursor over
the ready‑prefix, splices replies **strictly in issue order**, and performs the socket send — via epoll or
a per‑thread io_uring ring. Retirement (freeing argv/operands) happens here too, on the WB's own memory
pool. Because sends are off the ingress thread, receive and transmit run fully in parallel; scaling the WB
stage independently is what makes the 3‑Stage design win on send‑bound and larger‑value workloads.

---

## Performance

Measured on this repository's current code (v13 line), single node, loopback, AMD Ryzen 7 7700X
(8 cores, single CCD), server and load generator capped at 8 threads each, 30-second runs, two
interleaved repetitions (spread ≤ 2%), `memtier_benchmark`. Compared against stock **Redis 8**
(`io-threads 8`) and **Dragonfly** (`proactor_threads 8`) on identical cells.

**Regime 1 — small values, deep pipelining (32 B values, 2 M keys, pipeline 32).** The
dispatch-bound regime the architecture targets:

| System | GET | GET/SET 1:1 |
| :--- | :--- | :--- |
| **Tomo KV 2-Stage** | **7.25 M ops/s** | **6.38 M ops/s** |
| Tomo KV 3-Stage | 5.14 M ops/s | 4.52 M ops/s |
| Redis 8 | 4.43 M ops/s | 2.78 M ops/s |
| Dragonfly | 5.66 M ops/s | 5.29 M ops/s |

Tomo KV 2-Stage: **1.64× Redis / 1.28× Dragonfly** on GET, **2.30× Redis** on mixed 1:1.

**Regime 2 — DRAM-resident working set (~6 GB: 512 B × 8 M keys and 4 KB × 1.4 M keys, pipeline 16):**

| System | 512B 1:1 | 512B 1:9 | hot-key | 4KB 1:1 | 4KB 1:9 | FB-ETC |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Tomo KV 2-Stage | 2.39 M | 2.41 M | 2.44 M | 1.26 M | 1.24 M | 2.58 M |
| Tomo KV 3-Stage | 2.37 M | 2.34 M | 2.29 M | **1.38 M** | 1.25 M | 2.37 M |
| Redis 8 | 3.08 M | 3.23 M | 3.36 M | 1.88 M | 1.26 M | 3.22 M |
| Dragonfly | 1.34 M | 0.88 M | 0.82 M | 0.84 M | 0.63 M | 2.70 M |

(hot-key = Gaussian-concentrated GETs; FB-ETC = a Facebook ETC-like mix: 1:30 write:read,
Gaussian keys, small-skewed value-size distribution.)

**Honest reading.** Tomo KV owns the small-value pipelined regime and beats Dragonfly across
nearly every cell in both regimes. Stock Redis leads the DRAM-resident regime **on this 1-CCD
loopback box**: when every operation misses to DRAM, Redis's single pipeline simply does less
per-op work than Tomo's dispatch + cross-core handoff — and the de-contention machinery that
pays for that handoff has no contention to remove on a single CCD. The multi-CCD / real-NIC
evaluation (where that machinery is designed to pay) is pending on a Threadripper-class box.
Dragonfly's low pipelined-GET numbers at ≥256 B are a known loopback-specific artifact of its
reply path (its 32 B GET and FB-ETC results are representative; treat the 512 B/4 KB cells as
loopback-only). Validation before benchmarking: correctness (round-trips, MGET, expiry, DEL,
FLUSHDB) plus a reconnect-storm churn stress — both editions pass with zero crashes.

**Historical provenance.** The original EE451 evaluation of this architecture (earlier code
line, same class of hardware) measured 1.81× Redis on Tier-1 GET/SET, 1.66× on HGETALL, 3.46×
on BITCOUNT-1MB, and 2.0× at the saturated ceiling; those results reproduce within 1% under
the original methodology. Every number above was sanity-gated: results inconsistent with the
mechanism or with neighboring measurements are investigated and re-run, never reported.

-------------------------------- | :--------------- | :---------------- | :------------ |
| GET / SET (small value)           | 1.99 M ops/s     | **3.63 M ops/s**  | **1.81×**     |
| HGETALL (logic‑heavy)             | 1.59 M ops/s     | **2.64 M ops/s**  | **1.66×**     |
| BITCOUNT (1 MB, CPU‑bound)        | 2.6 K ops/s      | **9.1 K ops/s**   | **3.46×**     |
| Saturated ceiling (parallel load) | ~1.99 M ops/s    | **~3.98 M ops/s** | **2.0×**      |

p50 latency drops correspondingly (e.g. 1.52 ms → 0.35 ms on Tier‑1). The pattern is consistent: **the
heavier the command, the larger the multi‑core win**, because Tomo KV turns Redis's serial execution into
`N`‑way parallel execution while preserving its semantics. The 3‑Stage pipeline extends that advantage into
larger and send‑bound values by scaling the write‑back stage independently of ingress.

> **Scope, honestly.** The gains are largest for pipelined traffic and compute‑heavy or send‑bound commands
> on a saturated server. Non‑pipelined, single‑connection, latency‑bound traffic sees little benefit — one
> command in flight cannot be parallelized. All numbers are single‑node loopback; behavior on a real NIC
> and multi‑CCD/NUMA hardware is a separate (ongoing) evaluation. Every benchmark in this project is
> sanity‑gated: a number that doesn't match the mechanism is treated as a bug, not a result.

---

## Optimizations

Every optimization is an independent, runtime‑gated knob (see [Configuration](#configuration)). They fall
into a few families:

- **Out‑of‑order core.** Per‑worker keyspace partitioning, lock‑free SPSC dispatch queues with producer‑side
  index caching, single‑writer shards, and the CDB → WB reply‑reorder protocol — the foundation everything
  else sits on.
- **Software‑pipelined prefetch.** A multi‑pass, gem5‑style prefetch engine runs on the worker just ahead
  of execution: it warms the command's fake‑client struct, argv, command descriptor, key object, then
  chases the dict bucket → entry → value across a tunable window, plus an execution‑adjacent *next‑op*
  look‑ahead. A DB‑size‑adaptive gate turns it off for cache‑resident shards and on when the working set
  spills to DRAM. Hash‑carry computes each key's hash once and reuses it through dispatch and lookup.
- **Tiered operand pool.** The WB stage retires command operands into size‑class‑tiered, demand‑grown pools
  and recycles them back to the owning ingress thread through a lock‑free ring, with idle decay — cutting
  allocator traffic on write‑heavy, larger‑value workloads.
- **Dispatch & reply de‑contention.** Staged batch‑push with **eager per‑batch publish**, per‑parent
  reply‑signal coalescing, a multi‑bus CDB to spread reply signaling across cache lines, batched mask
  clears, and cache‑line‑isolated per‑thread counters to kill false sharing.
- **Zero‑copy & large values.** Value objects can be forwarded without a copy above a size threshold, with
  ownership returned to the owning worker via a free‑back ring so refcounts are only ever touched by the
  shard's owner; the WB write‑back path sends buffered, list, and encoded replies without stalling.
- **Multi‑key & cross‑shard.** `MGET`/`MSET`/`DEL`/`EXISTS`/`UNLINK`/`TOUCH` and set operations are split
  into per‑shard sub‑commands, dispatched in parallel, and reassembled — with `FLUSHALL`/`FLUSHDB` handled
  by queue‑ordered flush sentinels.
- **Kernel integration.** `SO_REUSEPORT` connection load‑balancing, `TCP_NODELAY`, taskset‑aware core
  pinning with shared‑L3/CCD awareness, NUMA‑local worker binding, and an optional **deep io_uring**
  write‑back path (multishot recv, `SEND_ZC`, `SQPOLL`, registered ring fd).
- **Online resharding.** Live key‑shard migration (effect‑log copy + drain‑fence cutover) with an optional
  dual‑rate‑EWMA hot‑shard auto‑tuner, for rebalancing skewed keyspaces without downtime.

---

## Configuration

Tomo KV adds runtime knobs on top of every standard Redis directive. **Sensible defaults ship on** — most
knobs exist for research and per‑workload tuning, not day‑to‑day use. The ones that matter most:

### Threading & topology
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-ifid-threads` | auto | Number of **ingress (issue)** threads. |
| `tomokv-ex-threads` | auto | Number of **EX worker** threads (must be a power of two). |
| `tomokv-strict-pipeline` | off → **set `yes`** | Enables the 3‑stage strict pipeline (dedicated WB send). Required for this edition. |
| `tomokv-wb-threads` (`tomokv-rob-threads`) | 0 → **set ≥1** | Number of **write‑back / reorder‑buffer** threads. |
| `tomokv-wb-epoll` (`tomokv-rob-epoll`) | off | Use epoll `write()` on the WB stage instead of io_uring. |
| `tomokv-pin-mode` | 2 | Core‑pinning strategy (dense / shared‑L3‑aware). |

<sub>The 3‑Stage pipeline is opt‑in: pass `--tomokv-strict-pipeline yes --tomokv-wb-threads N` (see
[Building & running](#building--running)). Build with `make USE_URING=yes` — the strict WB send path
requires it.</sub>

### Reply backend
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-wb-epoll` | off | WB stage sends via epoll `write()` (else io_uring). |
| `tomokv-io-uring` | off | Master switch for the io_uring backend. |
| `tomokv-io-uring-recv` / `-zc` / `-sqpoll` | off | Multishot receive / zero‑copy send / kernel submission polling. |

### Prefetch pipeline
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-opt-prefetch-worker` | on | Master switch for the worker prefetch pipeline. |
| `tomokv-prefetch-adaptive-min-keys` | auto | Enable prefetch only once a shard exceeds this key count (DRAM‑bound). |
| `tomokv-pf-fc` / `-argv` / `-cmd` / `-keyobj` | on | Individual pass‑1 prefetch stages. |
| `tomokv-pf-w-struct` / `-hash` / `-entry` / `-value` | 256 | Per‑stage prefetch window widths. |
| `tomokv-pf-w-nextop` | 256 | Execution‑adjacent next‑op look‑ahead distance. |
| `tomokv-opt-hash-carry` | on | Compute each key's hash once; reuse through dispatch + lookup. |

### Dispatch, reply & memory de‑contention
| Knob | Default | Meaning |
| :--- | :--- | :--- |
| `tomokv-opt-batch-push` | on | Stage worker pushes, one tail release per batch. |
| `tomokv-batch-push-eager` | on | Publish the staged batch at end of parse. |
| `tomokv-opt-coalesce-signal` | on | Coalesce per‑parent reply‑ready signals. |
| `tomokv-operand-pool-tiered` | off | Size‑class‑tiered operand pool with WB→ingress recycle ring. |
| `tomokv-opt-multi-cdb` / `tomokv-num-cdb` | off / auto | Spread reply signaling across multiple CDB cache lines. |
| `tomokv-opt-perthread-stats` | on | Cache‑line‑isolated per‑thread counters (no false sharing). |

### Advanced
Cross‑shard (`tomokv-opt-cross-shard`, `-cross-setop`, `-fanall`), online resharding
(`tomokv-reshard-auto` and the `tomokv-reshard-*` family), memory (`tomokv-zerocopy-min-value`), and a
suite of research/experimental predictors (`tomokv-vf-*`, `tomokv-opt-ship-reuse`,
`tomokv-opt-feedback-prefetch`) are available and default‑off. Run `redis-server --help` or see `config.c`
for the full surface.

---

## Building & running

```sh
# The 3-Stage strict pipeline requires the io_uring backend:
make -j USE_URING=yes

# Run a 3-stage instance: 4 ingress, 4 workers, 2 write-back (ROB) threads
./src/redis-server --tomokv-ifid-threads 4 --tomokv-ex-threads 4 \
                   --tomokv-strict-pipeline yes --tomokv-wb-threads 2

# Talk to it with any Redis client
./src/redis-cli set hello world
./src/redis-cli get hello
```

Tomo KV builds and runs like stock Redis and speaks unmodified RESP2/RESP3, so existing clients,
`redis-cli`, and `memtier_benchmark` work as‑is. jemalloc is the recommended allocator (bundled).

> **Tuning tip.** Scale the write‑back stage with how *send‑bound* your workload is: small‑value,
> dispatch‑bound traffic wants more workers and few WB threads; larger, send‑bound values scale up with WB
> threads. Ingress, execute, and write‑back counts should sum to your available core budget.

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
| **Tomo KV · 2‑Stage** | ingress → execute (replies on the ingress thread) | Low latency, small values, dispatch‑bound traffic. |
| **Tomo KV · 3‑Stage** (this) | ingress → execute → **write‑back / ROB** (dedicated reply stage) | High throughput, larger / send‑bound values. |

Both share the same out‑of‑order core, optimization set, and RESP surface; they differ only in whether reply
commit runs on the ingress thread (2‑Stage) or on a dedicated reorder‑buffer thread (3‑Stage).

---

## Credits

Tomo KV is a research fork of **[Redis](https://github.com/redis/redis)** (8.x) and inherits its data
structures, protocol, and BSD‑3‑Clause license. The out‑of‑order architecture is inspired by
**Tomasulo's algorithm** (R. M. Tomasulo, *"An Efficient Algorithm for Exploiting Multiple Arithmetic
Units,"* IBM Journal, 1967). Original Redis © Redis Ltd.; Tomo KV modifications retain the upstream license.
