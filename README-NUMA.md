<div align="center">

# Tomo KV · NUMA (role-flipping)

**A NUMA-aware evolution of the Tomo KV 2-stage engine: a fixed pool of threads that
*flip role* (ingress ⇄ worker) on demand, driven by a self-tuning controller, with all
load balancing kept strictly inside a NUMA node.**

*Logical nodes partition the pool · threads convert io↔ex without changing the total · an
extremum-seeking controller finds the best split · hot-key + client balancing stay node-local.*

`fixed-pool role-flip` · `within-node EWMA balancing` · `per-node M-command lock-borrow` · `RESP-compatible`

</div>

---

> This document covers **only what the NUMA version adds** on top of the base engine. For the
> core Tomasulo-style 2-stage pipeline (ingress parse/dispatch → out-of-order sharded execution →
> in-issue-order reply commit), the performance methodology, and the base configuration knobs, see
> [`README.md`](README.md). Everything there still applies; this is a superset.

## What the NUMA version adds

The base engine fixes the ingress/worker split at boot (`tomokv-io-threads` / `tomokv-ex-threads`).
On a multi-socket / multi-CCD box that is two problems at once: (a) the *right* split depends on the
live workload (dispatch-bound traffic wants more ingress; execution-bound traffic wants more
workers), and (b) a thread and the memory it touches should live on the **same** NUMA node, or every
access pays a cross-node hop.

The NUMA version addresses both without ever growing or shrinking the thread pool:

1. **Logical NUMA nodes** partition the fixed pool. Each node owns a contiguous slice of workers
   (and their keyspace buckets) plus a slice of ingress slots. A key's data, the worker that owns
   it, and the ingress threads that serve it are all pinned to one node.
2. **Fixed-pool role-flipping.** Threads are *dual-binding* ("poly") — a thread can serve as an
   ingress (io) thread or as an execution (ex) worker. **Grow-front** converts a worker into an
   ingress thread (ex→io); **grow-back** converts one back (io→ex). The **total** thread count is
   constant; only the boundary moves, and only *within a node's budget*.
3. **A self-tuning flip controller** (extremum-seeking) measures each node's own throughput and
   moves its boundary toward the maximum — no static thresholds, no hand-set target ratio.
4. **Within-node balancing only.** The EWMA hot-key bucket balancer and the client load balancer
   both operate **strictly inside a node**; cross-node balancing is deliberately disabled so data
   never migrates across the NUMA boundary. Each node decides from its own internal signals, and
   nodes act concurrently.
5. **Per-node M-command lock-borrow** (experimental) executes multi-key reads (`MGET`, `EXISTS`)
   node-locally instead of scattering them across every shard.

---

## The logical-node model

Set the topology at boot (all immutable):

```
tomokv-numa-nodes    N     # number of logical nodes (1 = single node = base 2-stage behavior)
tomokv-io-per-node   I     # ingress threads per node
tomokv-ex-per-node   E     # execution workers per node
```

The pool is `N × (I + E)` threads, always fully active. Node `n` owns:

* **worker slots** `[n·E, (n+1)·E)` — and, by construction (bucket ranges are monotone), a
  contiguous slice of the `16384` keyspace buckets. `tmNodeOfWorker(w) = w / E`.
* **ingress slots** `[n·I, (n+1)·I)`.

A worker that flips to serve as an ingress thread **keeps its node membership** — it just changes
role. So the io/ex boundary can move inside a node while every thread and every bucket it touches
stays node-resident.

`tomokv-numa-nodes 1` collapses the whole model to node 0 and is byte-for-byte the base 2-stage
engine.

---

## Fixed-pool role-flipping

Instead of a spare/parked thread (which would leave capacity idle), every thread is always doing
useful work in one of two roles. A flip is a bounded, online migration:

* **grow-front (ex→io):** the highest-indexed worker in the node stops popping its dispatch queue,
  hands its buckets to a neighbouring worker (via the online-reshard machinery — effect-log copy +
  drain-fence cutover, byte-exact under load), and re-binds as an ingress thread. Ingress capacity
  goes up by one, worker capacity down by one.
* **grow-back (io→ex):** the reverse — a converted ingress slot re-binds as a worker and reclaims a
  bucket range.

The migration is the same drain-fence cutover the reshard controller uses, so a flip **under live
traffic** is byte-exact and never drops or reorders a reply. Clients on a converting ingress thread
are re-spread evenly across the node's remaining ingress threads.

### The self-tuning flip controller (extremum-seeking)

The controller is **mathematically driven, not threshold-driven** — there is no static "flip when
io > 80%" rule. Per node, once per control tick (~4 Hz) it:

1. Maintains an **EWMA mean + variance** of that node's measured throughput (sum of the node's
   workers' `ops_total` deltas — the only proxy that survives a worker freezing on conversion).
2. **Probes** by flipping one step in the current search direction (first probe grows front, since
   ingress is the usual first bottleneck).
3. After an **adaptive warmup** (it waits for the reshard to settle, not a fixed number of ticks),
   compares the new throughput against the pre-flip baseline as a **z-score** (gain measured in
   units of the node's own noise σ). Better → keep going that direction. Worse → **revert and
   reverse**.
4. **Converges** when both neighbouring configurations show no significant gain, and **locks**; a
   sustained workload shift (tracked by a slow baseline) re-opens exploration.

Because the outcome is measured, a wrong initial guess self-corrects, and the controller will climb
all the way to an aggressive split (e.g. 6 ingress / 2 workers) when — and only when — the workload
actually rewards it. Nothing is set in stone; every bound is relative to the node's own numbers.

> **Status.** The flip controller and actuators are **fully live for `tomokv-numa-nodes 1`** (the
> whole server is node 0). For `tomokv-numa-nodes ≥ 2` the per-node controller *runs* (it measures
> each node and logs its decisions) and within-node balancing + the per-node M-command borrow are
> live, but the multi-node flip **actuators are staged** (`tomoGrowFrontNode` / `tomoGrowBackNode`
> refuse cleanly, pending per-worker liveness accounting). So a ≥2-node server boots, balances, and
> serves correctly, but does not yet perform the role-flip itself. This is the next milestone.

---

## Within-node load balancing

Two independent balancers, both **node-scoped**:

* **EWMA hot-key bucket balancer** (the self-driving reshard controller from the base engine, now
  node-local). Each worker keeps an EWMA of its load; when one worker runs hot relative to its
  same-node neighbours, a proportional slice of its buckets migrates to the coolest **same-node**
  neighbour. The transfer size is **imbalance-proportional** — `chunk ≈ (L_hot − L_cool)/(2·L_hot)`
  of the hot worker's range — so a small imbalance moves a few buckets and a large one moves many,
  instead of a fixed step. When a worker is flipped away, its EWMA weight is **added to its
  neighbour** and the controller re-derives the new balance from there (no artificial "kick").
* **Client load balancing** across the node's ingress threads (even split on connect and on any
  grow-front/grow-back that vacates an ingress slot).

Cross-node balancing is **off by design**: a bucket never migrates across the NUMA boundary, so a
key's data stays on the node that owns it for its whole lifetime.

---

## Per-node M-command lock-borrow (experimental)

Knob: `tomokv-mcmd-lock` (boolean, **default off**). When off, multi-key commands use the base
scatter-gather path and this code is inert.

The base engine executes a cross-shard `MGET`/`EXISTS` by *scattering* it into one sub-command per
owning worker, dispatching each across an SPSC queue, then gathering and reordering the replies —
N cross-thread round-trips per command. The lock-borrow path instead **executes node-locally**:

* The command's keys are grouped **by node**. One sub per node is dispatched to a node-local worker
  (the node's first-seen key owner).
* That worker **borrows** each of its node's keys directly from the key's true owner db, under a
  cheap per-worker spinlock (`tomo_wkr_lock`) that mutually excludes the owner's single-key hot path
  (which takes the same lock). Reads use `LOOKUP_NOEFFECTS` (a pure read that never mutates a
  non-owned db).
* `MGET` writes each value copy into its original position slot; `EXISTS` counts present keys. The
  IO thread reassembles the per-node partials in key order.

Every borrow stays **inside the node** — the point of the split on real NUMA, where a cross-node db
read would be the expensive case. For `tomokv-numa-nodes 1` an `MGET` uses an even cheaper single-
worker borrow (no group allocation); `EXISTS` uses the one-sub form of the same path.

**Lock discipline (post-review).** Introducing "a borrower reads another worker's db" breaks the
base engine's single-writer-per-worker-db invariant. To restore it, **when the knob is on, *every*
worker-db access takes the per-worker lock** — the single-key hot path, the scattered multi-key
sub-commands (reads *and* writes), and the online-migration apply/scan/cleanup. All of those run on
the owning worker's own thread, so they lock that worker; a borrower locks each key's true owner. The
lock is a 1-byte CAS and the whole discipline is inert when the knob is off (the base lock-free path
is byte-for-byte unchanged).

**Validation (this repo, `io4ex4` = 2 logical nodes on a single-CCD box):**

| Check | Result |
|---|---|
| Byte-exact vs scatter (MGET+EXISTS, present/absent mix) | identical, numa=1 **and** numa=2 |
| 60 s integrity stress (writers hold `key:i==v-i`, readers verify) | 2.35 M ops, **0 integrity errors**, no crash |
| Concurrent **multi-key** MSET+DEL vs borrow reads | 0.88 M ops, **0 errors**, no rehash-during-borrow crash |
| Concurrent **online migration** (8 within-node reshards, real data) vs borrow reads | 1.26 M ops, **0 errors**, byte-exact |
| Throughput, borrow vs scatter, saturated (`-P16 -c16`) | **parity** (0.99–1.19×), within run-to-run noise |

The throughput result is *expected* parity: a single physical CCD has no remote-memory penalty, so
the node-locality advantage cannot show up here — the measurement proves the per-node split adds no
overhead. **The NUMA-locality payoff is untestable on this box and awaits real multi-CCD hardware.**

**Scope.** Only *reads* are **borrowed** today (`MGET`, `EXISTS`); multi-key *writes* (`MSET`,
`DEL`, `*STORE`) still use the base scatter path — but now safely, since those sub-commands take the
owner lock under the knob. `TOUCH` (which shares `EXISTS`'s shape but exists for its access-time
side-effect) is deliberately kept on the scatter path. Extending the *borrow* itself to set-ops and
writes is future work.

---

## Configuration (NUMA-specific)

| Knob | Default | Mutable | Meaning |
|---|---|---|---|
| `tomokv-numa-nodes` | `1` | no | Number of logical nodes. `1` = base 2-stage. |
| `tomokv-io-per-node` | `0` | no | Ingress threads per node (`0` = derive from `tomokv-io-threads`). |
| `tomokv-ex-per-node` | `0` | no | Workers per node (`0` = derive from `tomokv-ex-threads`). |
| `tomokv-cores-per-node` | `0` | no | Cores per node (`0` = derive from io+ex per node). |
| `tomokv-thread-modes` | `off` | no | Enable dual-binding poly threads (required for role-flip). |
| `tomokv-thread-balance` | `off` | yes | Enable the auto flip controller + EWMA-weighted balancing. |
| `tomokv-flip-rebalance` | `on` | yes | Re-spread clients / transfer EWMA weight on each flip. |
| `tomokv-mcmd-lock` | `off` | yes | **Experimental** per-node M-command lock-borrow (MGET/EXISTS). |
| `tomokv-reshard-imbalance-pct` | `0` (auto) | yes | Within-node hot-worker bar; `0` = auto outlier detection. |
| `tomokv-reshard-min-ops` | `20000` | yes | Minimum ops before a within-node reshard may fire. |

The base engine's threading, batching/spin/prefetch, reply-path, and io_uring knobs all still apply
— see [`README.md`](README.md).

---

## Building & running

```sh
# Build (epoll backend)
make -C src -j

# …or with the io_uring backend
make -C src USE_URING=yes -j

# Run a 2-node instance: 2 ingress + 2 workers per node (io4/ex4 total),
# auto flip controller on, per-node M-command borrow on:
./src/redis-server --port 6379 \
    --tomokv-numa-nodes 2 \
    --tomokv-io-per-node 2 --tomokv-ex-per-node 2 \
    --tomokv-io-threads 4 --tomokv-ex-threads 4 \
    --tomokv-thread-modes yes --tomokv-thread-balance yes \
    --tomokv-mcmd-lock yes \
    --save ''

# Single-node (base 2-stage) with the LIVE role-flip controller:
./src/redis-server --port 6379 \
    --tomokv-numa-nodes 1 --tomokv-io-threads 6 --tomokv-ex-threads 2 \
    --tomokv-thread-modes yes --tomokv-thread-balance yes --save ''

# Talk to it with any Redis client
redis-cli -p 6379 ping
```

Boolean knobs take `yes`/`no`. Topology knobs are immutable (set at boot); balancing and mcmd-lock
knobs are runtime-mutable via `CONFIG SET`.

---

## Status & scope

| Area | State |
|---|---|
| Logical-node topology + node-local buckets/ingress | **live** (all node counts) |
| Within-node EWMA hot-key balancing + client balancing | **live** |
| Role-flip controller + actuators, `numa-nodes 1` | **live** (extremum-seeking, byte-exact under load) |
| Per-node role-flip actuators, `numa-nodes ≥ 2` | **staged** (controller runs; actuators refuse pending per-worker liveness) |
| Per-node M-command lock-borrow (`MGET`/`EXISTS`) | **live, experimental** (default off); byte-exact + integrity-validated, adversarially reviewed (safe vs single-key ops, scattered multi-key reads+writes, and online migration) |
| M-command *borrow* for set-ops / writes | **not yet** (multi-key writes still scatter — safely — under the lock) |
| Real multi-CCD / multi-socket NUMA measurement | **pending hardware** (sim shows correctness + parity only) |

All correctness results in this document were produced on a single-CCD development box, where the
role-flip and lock-borrow paths are validated for **correctness and no-overhead** but cannot exhibit
the cross-node-locality speedup they are designed for. Those numbers must be re-measured on true
NUMA hardware before any performance claim is made.
