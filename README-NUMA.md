<div align="center">

# Tomo KV · NUMA

**A NUMA-native evolution of the Tomo KV 2-Stage engine: one physical database per NUMA node,
bucket-granular ownership inside it, resharding that flips a table entry instead of copying data,
and a fixed pool of cores that change role — ingress ⇄ execution — under a self-tuning per-node
controller.**

`db-per-node` · `O(1) ownership-flip resharding` · `any-core role-flipping` · `self-tuning io/ex split` · `RESP-compatible`

</div>

---

> This document describes the architecture and configuration of the NUMA edition
> (branch `2s-numa-shared-kv-dev`). The base 2-Stage pipeline — ingress parse/dispatch →
> out-of-order sharded execution → in-issue-order reply commit — is documented in
> [`README.md`](README.md); everything there applies here unchanged. The sibling branch
> `2s-numa-mcmd-lock-dev` preserves the previous **physically-sharded** model (one isolated
> kvstore per worker, copy-engine resharding) as a maintained alternative; the two produce
> byte-identical results for the full command surface and can be swapped freely.

---

## 1 · The node model

```
node 0 (C cores)                            node 1 (C cores)
┌─────────────────────────────────┐         ┌─────────────────────────────────┐
│  ONE physical db per logical DB │         │  ONE physical db per logical DB │
│  = a kvstore of 16384 dicts     │         │  = a kvstore of 16384 dicts     │
│    dict index == bucket         │         │    dict index == bucket         │
│  ┌─────────┬─────────┬───┐      │         │  ┌─────────┬─────────┬───┐      │
│  │ worker a│ worker b│...│      │         │  │ worker c│ worker d│...│      │
│  │ owns a  │ owns a  │   │      │         │  │ owns a  │ owns a  │   │      │
│  │ bucket  │ bucket  │   │      │         │  │ bucket  │ bucket  │   │      │
│  │ range   │ range   │   │      │         │  │ range   │ range   │   │      │
│  └─────────┴─────────┴───┘      │         │  └─────────┴─────────┴───┘      │
│  cores: ≥1 io, ≥1 ex, rest flip │         │  cores: ≥1 io, ≥1 ex, rest flip │
└─────────────────────────────────┘         └─────────────────────────────────┘
     zero cross-node data structures, locks, or shared cache lines
```

**Physical shards are nodes.** Each logical database is materialized as one `kvstore` per NUMA
node. All of a node's state — the dict-pointer array, the aggregate counters, every bucket-dict,
every key — belongs to that node. Nothing on any data path reads or writes another node's memory,
which is what makes the design NUMA-native rather than NUMA-tolerant: locality is structural, not
scheduled.

**Virtual shards are workers.** Keys map to one of 16384 buckets (`xxh64(key) & 16383`), and the
bucket is *literally the dict index* inside the node's kvstore. A routing table
(`bucket → worker`) assigns each worker of a node a contiguous bucket range. A worker is the sole
mutator of its owned bucket-dicts, so the base engine's single-writer invariant survives intact —
the unit of exclusivity just shrinks from "a whole worker database" to "a bucket-dict". The
single-key hot path has **zero synchronization**.

**Worker counts are free.** Routing is table-driven; any worker count works (non-power-of-two
included), and the number of virtual shards at any moment equals the currently-live workers —
anywhere between one per node and all-but-one of each node's cores.

### Shared-kvstore mechanics

A node's kvstore is written by several worker threads (each in its own dict subset), which the
stock kvstore was never built for. The `KVSTORE_SHARED_MT` mode adapts the bookkeeping:

- aggregate counters (key count, non-empty dicts, bucket count, allocated dicts, rehash overhead)
  become relaxed atomics — node-local cache lines, no cross-node traffic;
- the Fenwick size-index (a log-n multi-writer tree walk per add/delete) is dropped; its few cold
  consumers (non-empty-dict iteration, fair-random selection) use linear fallbacks or are
  rerouted to owner-scoped equivalents;
- the rehashing list is guarded by a tiny spinlock taken only at rehash start/finish;
- dict creation is release-published so cross-owner readers always observe a fully-built dict.

Single-writer kvstores (the flag off) are bit-for-bit unchanged.

### FLATSTORE — the lock-free flat table (opt-in: `thredis-flat-store 1`)

A node's keyspace is 16384 per-bucket dicts so a reshard is an O(1) ownership flip (no key copy).
But 16384 dict *headers* (≈1.6 MB of `struct dict` + scattered hash tables) don't fit L2, so a
random lookup pays a cold header miss — a measured ~4.5% p32 tax versus a single-table layout, and
more on multi-CCD hardware. FLATSTORE removes it by replacing the 16384 dicts with **one lock-free
open-addressing table per node**, so a lookup hits one warm header:

- each 16-byte slot is `{ _Atomic ctrl, _Atomic kv }`, where `ctrl` packs a **48-bit hash tag**, the
  **14-bit ownership bucket**, and `TOMB`/`OCCUPIED` bits (`0` = empty);
- **GET** is a lock-free linear probe (acquire-load `ctrl`, stop on empty, acquire-load the value);
- **INSERT** claims a slot with one release-CAS on `ctrl` (the one-owner-per-bucket rule means the
  CAS only ever resolves cross-*key* physical collisions, never same-key races), then publishes the
  value; **DELETE** tombstones;
- **reshard stays O(1)** — the bucket is a per-slot tag, a pure function of the key and independent
  of ownership, so the flip is still just the `ex_bucket_table` write with zero table work.

Measured on a Ryzen 7 7700X (8c/1CCD), all features on, converged, medians:

| Regime | dict (default) | FLATSTORE | Δ |
| :--- | :--- | :--- | :--- |
| p32 GET (steady) | 7.39M | **7.73M** | +4.5% |
| p32 SET (steady) | 4.67M | **5.54M** | **+18.7%** |
| p32 GET (during a role-flip) | 6.40M | **7.68M** | flat holds |
| p32 GET (during a client-lb rebalance) | 6.87M | **7.44M** | flat holds |

The SET win is the lock-free CAS insert versus the dict's rehash/expand path; the flat table is also
far steadier through a reshard, because lock-free reads aren't disrupted by the flip the way a
per-bucket dict is.

> **Status: Stage 0, opt-in (default off).** GET/SET/DEL/MGET/EXISTS/KEYS/RANDOMKEY are correct
> (single-thread and under concurrent multi-worker load, verified by an adversarial review that
> caught and fixed two crash classes on the async-delete and TTL paths). The table is pre-sized (no
> online resize yet — Stage 2) and **leaks on delete** (safe reclamation of a value a lock-free
> reader may still hold needs the QSBR pass — Stage 1). Until those land it is not the default
> execution path; the proven 16384-dict store remains the default.

### The lock discipline

Multi-key commands may legitimately touch buckets owned by several workers of a node. With
`tomokv-mcmd-lock` enabled, every access to a worker's territory takes that worker's 1-byte CAS
lock — the owner on its own operations, borrowers per key, migration and flush machinery around
their critical sections. Because ownership means collisions are rare, the locks are almost always
uncontended: *lock every time, wait almost never*. With the knob off the entire discipline
compiles down to predicted-not-taken branches and the engine is the base lock-free design (multi-
key commands then use scatter-gather exclusively).

---

## 2 · Resharding: drain, flip, done

Moving a bucket range between two workers of a node used to mean physically copying every key.
Here the data already lives in `dict[bucket]` of the shared node kvstore — the only thing that
changes is *who serves it*:

1. **Drain fence** — in-flight writes to the migrating range are quiesced (the existing
   microsecond-scale per-producer fence).
2. **Flip** — `ex_bucket_table[range] = new_owner`. No scan, no serialization, no replay, no
   cleanup; the copy engine is entirely bypassed in shared mode.
3. **Done** — the new owner serves the range from the same dicts.

The cost is independent of key count and value size. Cheap reshards are load-bearing for the whole
design: the EWMA hot-bucket balancer and the flip controller both assume they can move ownership
often and casually.

Cross-node moves do not exist by design (data would actually have to move); the balancer and the
flip machinery are node-scoped, and manual reshard requests across physical databases are
rejected.

---

## 3 · Role-flipping: any core, either role

Every pool thread is poly-bound: it can run **ingress duty** (accept, parse, dispatch, reply
commit) or **execution duty** (own bucket ranges, run commands), and converts online:

- **grow-front (ex → io):** the node's highest live worker flips its whole range to its neighbor
  (an O(1) reshard), parks, joins the accept group as an io thread, and pulls a fair share of
  existing client connections.
- **grow-back (io → ex):** a converted io thread leaves the accept group, migrates its connections
  out (even split), parks, revives as a worker, and is seeded half of its neighbor's range —
  another O(1) flip.

Booting each node as `1 io + (C−1) ex` makes **every non-base core bidirectional**; the base io
core (the main thread on node 0) is permanently ingress, which is exactly the "at least one io per
node" floor. The actuator guards enforce the other bound: a node never drops below one live
worker. Nodes decide and flip **independently** — each node's controller acts on its own signals;
conversions from different nodes serialize through a single short migration gate.

Liveness bookkeeping is per-node: each node's live workers form a prefix of its slot range
(conversion is LIFO within the node), and every consumer of the live set — command routing,
`KEYS`/`FLUSH` fan-outs, `RANDOMKEY` weighting, the balancer, debug interfaces — resolves
membership through the per-node predicate rather than any global count. A converted worker keeps
draining its old dispatch queues while serving as io, so a straggler request that raced the
conversion is still consumed rather than stranded.

### The flip controller

One controller instance per node, driven by measured outcomes rather than static thresholds:

- **Throughput estimator** — an EWMA of the node's executed-ops rate with an EWMA variance; every
  judgment is a z-score against the node's own noise. Idle ticks (no executed ops, no queue depth,
  no ingress busy) carry no information and freeze the estimator; a node with no offered load
  never probes.
- **Direction** — chosen by comparing io-side and ex-side throughput. At steady state the two are
  equal, so their difference is exactly the queue-depth trend: standing worker queues mean
  execution lags (grow back); dry queues mean the node is dispatch-bound (grow front).
- **Probe loop** — flip one step, wait for the reshard to settle (adaptively: settled = the
  smoothed rate stops moving relative to its own noise), then judge. Gains continue the climb;
  losses revert and reverse. Convergence locks when neither neighbor config shows a significant
  gain, and a sustained workload shift re-opens exploration.

The EWMA hot-bucket balancer runs alongside it, also node-scoped: a worker running hot relative to
its same-node peers sheds an imbalance-proportional slice of buckets to its coolest neighbor, and
a flipped-away worker's load weight transfers to the neighbor that absorbed its range.

---

## 4 · Multi-key execution

Cross-shard commands choose among three strategies:

| strategy | used for | mechanism |
|---|---|---|
| **fine-grained borrow** | `MGET`, `EXISTS` | the first key's owner executes the whole command, taking each key's owner lock per key; cross-node forms split into one borrow per node and combine. |
| **node-locked stock proc** | same-node `SINTER`, `SINTERCARD`, `ZINTERCARD`, `TOUCH` | the stock command runs on one worker of the node holding all that node's worker locks (ascending order — cycle-free); replies and side-effects are stock by construction. |
| **scatter / merge-pipeline / 2-hop** | everything else (`MSET`, `DEL`, unions, `*STORE`, `RENAME`, `COPY`, `LMOVE`, …) | the base engine's paths, lock-coordinated with borrowers when the discipline is on. |

Hash-field-TTL commands (`HEXPIRE` family) mutate a per-database structure that spans workers;
on a shared node db they execute under the node's locks (and are refused with an error if the lock
discipline is disabled).

A dispatch-time optimization removes redundant key hashing: the router necessarily hashes the key
to pick a worker, and carries the resulting bucket on the in-flight command so the execution-side
dict selection reuses it instead of rehashing (pointer-matched, cleared at the end of each
execution).

---

## 5 · Flush semantics under sharing

`FLUSHALL`/`FLUSHDB` on a shared node cannot empty per worker (concurrent kvstore-wide frees would
race). Instead: sentinels still flow through every bucket-owning worker's queue — preserving
per-connection ordering — and the node's workers rendezvous; the last to arrive performs the one
`kvstoreEmpty` while its siblings wait, after which all resume. Flushes are serialized with each
other and are mutually exclusive with migrations and flips (a flush freezes bucket boundaries for
its duration; waiting flushers on the main thread keep pumping the coordinator so nothing
deadlocks). Note the semantic consequence: a flush briefly stops the whole node, for the duration
of the free.

---

## 6 · Configuration

### Topology (boot-only)

| knob | default | meaning |
|---|---|---|
| `tomokv-numa-nodes` | 1 | logical node count (1 = the whole server is one node); max 16 |
| `tomokv-cores-per-node` | derive | cores per node; pool = nodes × cores |
| `tomokv-io-per-node` | derive | boot ingress threads per node |
| `tomokv-ex-per-node` | derive | boot workers per node — `1 io + (C−1) ex` maximizes flip range |
| `tomokv-io-threads` / `tomokv-ex-threads` | — | legacy global totals; must equal nodes × per-node values when both given |

### Role-flipping

| knob | default | mutable | meaning |
|---|---|---|---|
| `tomokv-thread-modes` | off | no | poly-bound threads (prerequisite for any flipping) |
| `tomokv-thread-balance` | off | yes | the per-node flip controller + EWMA-weighted client balancing |
| `tomokv-flip-rebalance` | on | yes | client re-spread and load-weight transfer at each conversion; also gates the **continuous client-lb** (below) |
| `tomokv-modeshift-test` | 0 | yes | manual actuator hooks: `7`/`8` = grow front/back (single-node only), `70+n`/`80+n` = per-node (n < 10). Setting an unchanged value is a no-op — toggle through 0 between repeats. |

### Multi-key / locking

| knob | default | mutable | meaning |
|---|---|---|---|
| `tomokv-mcmd-lock` | off | no | the per-worker lock discipline. Boot-only: a runtime toggle would race in-flight commands against the lock gates. Off = base lock-free engine, scatter-only multi-key. |

`tomokv-mcmd-nodelocal` was REMOVED (2026-07-27) together with the node-local read borrow it
selected. Multi-key reads are now single-owner localfast (all keys on one worker) or
scatter-gather / merge-pipeline; there is no path that reads a key from a non-owner worker.
Cross-key reads (`SINTER`/`SINTERCARD`/`ZINTERCARD`/`EXISTS`/`TOUCH`) are per-key atomic but
NOT atomic across keys, so they may observe a concurrent writer mid-update — a deliberate,
uniform divergence from stock Redis's single-threaded cross-key atomicity.

### Storage engine

| knob | default | mutable | meaning |
|---|---|---|---|
| `thredis-flat-store` | off | no | replace the node's 16384-dict kvstore with the lock-free **FLATSTORE** open-addressing table (see *Shared-kvstore mechanics*). Requires a shared node (workers-per-node > 1). Stage 0 / opt-in — pre-sized, leaks on delete; not yet the default execution path. |

### Balancer

`tomokv-reshard-*` (chunk, imbalance bar, sustain, min-ops, cool margin, progress ratio) tune the
within-node EWMA **bucket** balancer exactly as in the base engine; `0` means self-derived.

**Continuous client-lb.** The connection balancer now mirrors the bucket balancer: a 1 Hz cron
(beside the reshard autotune) that, within a node, moves the minimal set of connections off an io
thread that is a *sustained* busy-outlier (busy-EWMA mean + 25% bar + a short sustain streak) onto
the least-loaded thread — a damped, half-the-excess move that converges instead of chasing a single
hot connection. It runs whenever `tomokv-thread-modes` is on (busy is maintained there), so client
load is balanced continuously, not only at a flip. `DEBUG TOMO-IOLOAD` dumps per-thread mode, conn
count, and busy for inspection.

All other base knobs — batching, spin, prefetch stages, reply path, io_uring — apply unchanged.

### Example

```sh
make -C src USE_URING=yes -j

# 2 nodes × 4 cores; every non-base core can flip; self-tuning; lock discipline on:
./src/redis-server --port 6379 \
    --tomokv-numa-nodes 2 --tomokv-io-per-node 1 --tomokv-ex-per-node 3 \
    --tomokv-io-threads 2 --tomokv-ex-threads 6 \
    --tomokv-thread-modes yes --tomokv-thread-balance yes \
    --tomokv-mcmd-lock yes --save ''

# One big node, static split, shared keyspace only:
./src/redis-server --port 6379 \
    --tomokv-numa-nodes 1 --tomokv-io-threads 4 --tomokv-ex-threads 4 \
    --tomokv-mcmd-lock yes --save ''
```

Boolean knobs take `yes`/`no`. Pin the server and the load generator to disjoint cores.

---

## 7 · Scope and known gaps

- **Replication/AOF/cluster**: same restrictions as the base sharded engine (boot-gated).
- **SCAN** over shard data: unchanged from the base engine.
- **Spare-thread mode**: superseded by role-flipping; spare activation into a shared node is
  rejected.
- **Concurrent per-node migrations**: node decisions are independent but conversions serialize
  through one gate; true concurrency requires per-node migration state.
- **Controller convergence-lock** at the optimum is still loose (it keeps probing); cheap flips
  make the churn tolerable, and tighter lock-in is the top controller work item.
- **Keysize histograms** (`INFO keysizes`) are disabled on shared node databases.

Design documents in-tree: `NUMA_SHARED_KV_PLAN.md` (implementation log),
`MCMD_LOCK_DESIGN.md` (multi-key lock evolution), `SHARED_KEYSPACE_DESIGN.md` (the original
shared-keyspace proposal, realized here as db-per-node).

## The Tomo KV family

| edition | branch | keyspace | reshard |
|---|---|---|---|
| 2-Stage (base) | — | per-worker isolated | copy engine |
| NUMA · physical shards | `2s-numa-mcmd-lock-dev` | per-worker isolated | copy engine |
| **NUMA · shared node db** (this) | `2s-numa-shared-kv-dev` | one per node, bucket-owned | O(1) ownership flip |

Tomo KV is a research fork of [Redis](https://github.com/redis/redis) (8.x) and inherits its data
types, protocol, and command surface.
