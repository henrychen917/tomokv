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

> **On the split:** the table above fixes `io4w4`, which under‑provisions ingress for this I/O‑bound
> regime. On the same 8 cores, `io6w2` reaches **3.26 M** — matching Redis's 8‑thread peak. See
> [Configurable execution topology](#configurable-execution-topology--a-cpuarchitecture-idea): the gap
> is a topology choice, not an architectural limit.

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
`N`‑way parallel execution while preserving its semantics.

> **Scope, honestly.** The gains are largest for pipelined small‑value traffic and compute‑heavy commands
> on a saturated server. Non‑pipelined, single‑connection, latency‑bound traffic sees little benefit — one
> command in flight cannot be parallelized. All numbers are single‑node loopback; behavior on a real NIC
> and multi‑CCD/NUMA hardware is a separate (ongoing) evaluation. Every benchmark in this project is
> sanity‑gated: a number that doesn't match the mechanism is treated as a bug, not a result.

---

## Configurable execution topology — a CPU‑architecture idea

Tomo KV's defining knob is that **you split your core budget between *ingress* threads (parse /
dispatch / reply) and *execution* workers (run commands on owned shards)** — the way a CPU architect
sizes fetch/decode/issue width against the number of execution units. You match the machine to *your*
workload's bottleneck instead of matching your workload to a fixed machine. Redis only lets you scale
I/O threads (execution stays single‑threaded); Dragonfly is a rigid shard‑per‑core model. Neither can
re‑balance ingress against execution — Tomo can, and on the same cores it changes performance
dramatically.

**The split is a real, consequential dial** (2‑Stage, 512 B GET/SET 1:9, DRAM‑resident 8 M keys,
same 8 cores, `memtier` loopback):

| Split (8 cores) | ops/s | note |
| :--- | :--- | :--- |
| `io4w4` | 2.48 M | ingress‑starved for this I/O‑bound cell |
| **`io6w2`** | **3.26 M** | ingress provisioned → **+31%**, matches Redis's 8‑thread peak (3.22 M) |
| `io7w1` | 1.80 M | workers starved → collapse |

At **equal I/O parallelism the architecture is a wash** — Tomo `io4w4` = 2.48 M vs Redis `io‑threads 4`
= 2.45 M — and both scale identically as I/O threads are added (Tomo io4→io6, Redis io4→io8). So a
DRAM‑resident small‑value workload isn't "slower on Tomo"; it just wants its cores spent on ingress,
which one knob does.

**Which way to dial depends on where your bottleneck is:**

| Bottleneck | Symptom | Dial toward | Measured (6 cores, 2‑Stage) |
| :--- | :--- | :--- | :--- |
| **Ingress / reply‑send** | small values at high op‑rate, or large‑value replies (the io thread sends) | **more ingress** (`io4w2`) | 64 B GET 4.4 M · 16 KB GET 0.55 M |
| balanced | mixed | `io3w3` | 64 B GET 4.5 M · 16 KB GET 0.45 M |
| **Execution** | CPU‑heavy commands (HGETALL, ZRANGE, BITCOUNT, set ops) | **more workers** (`io2w4`) | 64 B GET 3.2 M · 16 KB GET 0.33 M |

In 2‑Stage the ingress threads do parsing *and* reply‑sends, so both small‑value and large‑value GET
favor more ingress; **workers win when the command itself is CPU‑heavy** — exactly the regime where the
architecture posts its biggest wins (the paper's HGETALL 1.66× and BITCOUNT‑1 MB 3.46× are worker‑
parallelism gains). Rule of thumb: **profile your dominant command, then give cores to whichever stage
is the wall.**

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
