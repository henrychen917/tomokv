<div align="center">

# Tomo KV · NUMA — shared node keyspace + role-flipping cores

**One physical database per NUMA node. Bucket-granular ownership inside it. Resharding that moves
a table entry instead of data. A fixed pool of cores that flip between ingress and execution under
a self-tuning controller — any core, either role, at least one of each per node.**

`db-per-node` · `O(1) ownership-flip resharding` · `any-core role-flipping` · `self-tuning split` · `RESP-compatible`

</div>

---

> This is the NUMA edition of the Tomo KV 2-Stage engine. The base pipeline (ingress parse/dispatch
> → out-of-order sharded execution → in-issue-order reply commit), the performance methodology, and
> the base knobs are documented in [`README.md`](README.md) — everything there still applies. The
> sibling branch `2s-numa-mcmd-lock-dev` preserves the previous **physically-sharded** model
> (one isolated kvstore per worker, copy-engine resharding) as a maintained alternative; this
> branch (`2s-numa-shared-kv-dev`) is the shared-keyspace evolution. The two are kept
> **byte-exact-interchangeable** (verified 108/108 across every command family) so either can be
> benchmarked against the other at any time.

## The model in one picture

```
node 0 (4 cores)                          node 1 (4 cores)
┌───────────────────────────────┐         ┌───────────────────────────────┐
│  ONE physical db (kvstore)    │         │  ONE physical db (kvstore)    │
│  16384 bucket-dicts           │         │  16384 bucket-dicts           │
│  ┌─────────┬─────────┐        │         │  ┌─────────┬─────────┐        │
│  │ w0 owns │ w1 owns │ ...    │         │  │ w3 owns │ w4 owns │ ...    │
│  │ buckets │ buckets │        │         │  │ buckets │ buckets │        │
│  └─────────┴─────────┘        │         │  └─────────┴─────────┘        │
│  io ⇄ ex flipping cores       │         │  io ⇄ ex flipping cores       │
│  (≥1 io, ≥1 ex, rest float)   │         │  (≥1 io, ≥1 ex, rest float)   │
└───────────────────────────────┘         └───────────────────────────────┘
        no cross-node data, locks, or cache lines — ever
```

- **Physical shards = nodes.** Each node owns one `kvstore` per logical db. 4 nodes → 4 physical
  dbs. Nothing about a node's keyspace — dict array, aggregates, bucket-dicts — is ever touched
  from another node.
- **Virtual shards = workers.** The kvstore's **dict index is the ownership bucket**
  (`xxh64(key) & 16383` — the same value the routing table uses). Each worker of a node owns a
  contiguous slice of bucket-dicts. The single-writer invariant of the base engine survives intact,
  just at bucket granularity: **the hot path has zero synchronization**.
- **Locks exist but are never contended.** Multi-key commands may cross ownership inside a node;
  they take cheap per-worker CAS locks (`tomokv-mcmd-lock`). Single-key traffic takes its own lock
  only when the knob is on. "Lock every time, never wait" — measured uncontended.

## Resharding is an ownership flip, not a copy

Because every key already lives in `dict[bucket]` of its node's shared kvstore, moving a bucket
range between two workers of a node **moves no data**: the existing drain-fence quiesces in-flight
writes to the range (microseconds), then `ex_bucket_table[b] = new_owner` — done. The entire
copy engine (scan → effect-log → replay → cleanup) is dead code in this mode.

Measured against the physical-shard copy engine (2M keys, ⅛ of the keyspace, concurrent GET load):

| | copy engine (physical shards) | **ownership flip (this branch)** |
|---|---|---|
| worst concurrent-GET sample during reshard | 837k (**−45% crater**) | **1412k (−7% blip)** |
| data moved | O(keys × value size) | **zero** |
| wall time (64B values) | ~270ms | ~270ms (both = coordinator phase latency) |

The flip is size-independent — the gap widens with real data. Cheap reshards are what make the
EWMA balancer and the flip controller's continuous probing affordable.

## Any core, either role

Threads are poly-bound: a core can serve as an **ingress (io)** thread or an **execution (ex)**
worker, and converts online in both directions:

- **grow-front** (ex→io): the node's highest live worker hands its buckets to its neighbor (an O(1)
  flip), parks, and joins the accept group as an io thread. Clients rebalance onto it.
- **grow-back** (io→ex): a converted io thread drains its connections out (even split), parks, and
  revives as a worker, seeded with half its neighbor's range.

Boot each node as `1 io + (cores−1) ex` and **every non-base core floats**; the guards are exactly
the invariant you want — grow-front refuses at 1 ex/node, grow-back refuses at the 1 base io/node.
A 4-core node covers the full range 1io/3ex ⇄ 3io/1ex. **Nodes flip independently** (each node's
controller decides from its own signals; conversions serialize through the single migration gate,
~ms each). Validated: repeated full-range sweeps on both nodes under load — 68 grow-fronts + 68
grow-backs + 152 reshards in one 8-minute run, 19.6M integrity-verified operations, zero errors.

### The flip controller

Per node, an extremum-seeker on **measured node throughput** (EWMA mean ± variance — every decision
is scored in units of the node's own noise; nothing is an absolute threshold):

- **Direction** comes from comparing io-side vs ex-side throughput. At steady state the two rates
  are equal, so their difference *is* the queue-depth trend: standing worker queues ⇒ execution
  lags ⇒ grow back; dry queues ⇒ dispatch-bound ⇒ grow front.
- **Probes** flip one step, wait for the reshard to settle (adaptively — not a fixed delay), and
  judge the throughput delta as a z-score. Better → continue; worse → revert and reverse.
- **Idle ticks carry no information** and freeze the estimator (folding them was the historical
  σ≈2×mean bug that made every gate meaningless); a node with no offered load never probes.

Observed behavior: on a uniform GET load the controller climbs monotonically
(1.39M → 1.56M → 1.64M → 1.72M → **1.74M ops/s at 7io/1ex**, σ ≈ 0.5–1% of mean), beating the
static 4io/4ex baseline by ~9% once settled. Known remaining work: convergence-lock engagement
(it keeps probe-reverting at the optimum), probe-cost accounting, and alternative estimators
(windowed median, paired probes, UCB budgets).

## Multi-key commands

Three execution strategies, each measured into its role:

| path | commands | why |
|---|---|---|
| **fine-grained borrow** | `MGET`, `EXISTS` | one worker executes the whole command, taking each key's owner lock per key. Beats both scatter (+24–190% depending on shape) and the stock-proc alternative (measured 0.81–0.93× — group machinery dominates at small N). |
| **node-locked stock proc** | `SINTER`, `SINTERCARD`, `ZINTERCARD`, `TOUCH` (same-node) | the stock command runs on one worker under all the node's locks — byte-exact with every stock side-effect, +22–51% on intersections. Unions/zops stay off it (measured losers: reference computes them 4-way-parallel on io threads). |
| **scatter / pipeline / 2-hop** | everything else (`MSET`, `DEL`, unions, `*STORE`, `RENAME`, `LMOVE`, …) | the base engine's paths, now lock-coordinated with the borrowers when the knob is on. |

Cross-node commands split by node and combine. All of it is byte-exact against both the scatter
reference and the physical-shard branch.

## Verification status

| gate | result |
|---|---|
| Byte-exact vs physical-shard branch | **108/108** checks (all families: strings/expire/hash/list/set/zset/bits/HLL + full cross-shard incl. 2-hop) |
| Cross-shard corruption harness | PASS (0/200 canaries, max sharing) |
| Intercard + setop oracles | PASS / 30-0 |
| Megastress (8 min: flips + reshards + FLUSHALL + verified load) | 19.6M ops, 0 integrity errors, 0 crashes |
| **AddressSanitizer** (4 min, flips + flushes + mixed load) | 8.8M ops, **0 ASAN reports** |
| Throughput vs physical shards | geomean **1.006** (per-family ±10% campaign drift on this box; no reproducible regression) |
| Reshard service impact | −7% blip vs the copy engine's −45% crater |

All numbers are from a single-CCD development box: they establish **correctness and no-overhead**.
The NUMA-locality wins the design targets (node-local memory, no cross-node cache lines) are
structural but **unmeasurable here** — they await multi-CCD hardware.

## Configuration

| knob | default | mutable | meaning |
|---|---|---|---|
| `tomokv-numa-nodes` | 1 | no | logical node count (1 = single big node) |
| `tomokv-io-per-node` / `tomokv-ex-per-node` | derive | no | boot split per node; `1 io + (cores−1) ex` enables full any-core flipping |
| `tomokv-thread-modes` | off | no | poly threads (required for flipping) |
| `tomokv-thread-balance` | off | yes | the per-node flip controller + EWMA-weighted balancing |
| `tomokv-flip-rebalance` | on | yes | client re-spread + EWMA weight transfer at each flip |
| `tomokv-mcmd-lock` | off | **no** | the lock discipline + borrow/node-local paths. Boot-only: a runtime toggle would race in-flight groups. |
| `tomokv-mcmd-nodelocal` | off | no | A/B experiment: MGET/EXISTS via stock proc instead of borrow (measured slower; kept for re-testing) |
| `tomokv-modeshift-test` | 0 | yes | test hooks: `7`/`8` global grow front/back, `70+n`/`80+n` per-node (n<10). Note: setting an unchanged value is a no-op — toggle through 0 between repeats. |

Reshard tuning (`tomokv-reshard-*`) and every base-engine knob apply unchanged.

Sizing note: with `N` nodes × `C` cores, you get `N` physical dbs; the number of *virtual* shards
(per-worker ownership ranges) at any moment equals the live ex workers — between `N` (1/node) and
`N×(C−1)` (all-but-one per node). The fine ownership granularity underneath is always 16384
buckets, and worker counts need **not** be powers of two.

## Building & running

```sh
make -C src USE_URING=yes -j        # or plain `make -C src -j` for the epoll backend

# 2 NUMA nodes × 4 cores, full any-core flipping, self-tuning split, M-command locks:
./src/redis-server --port 6379 \
    --tomokv-numa-nodes 2 --tomokv-io-per-node 1 --tomokv-ex-per-node 3 \
    --tomokv-io-threads 2 --tomokv-ex-threads 6 \
    --tomokv-thread-modes yes --tomokv-thread-balance yes \
    --tomokv-mcmd-lock yes --save ''

# Single big node (whole server is node 0), flip controller live:
./src/redis-server --port 6379 \
    --tomokv-numa-nodes 1 --tomokv-io-threads 4 --tomokv-ex-threads 4 \
    --tomokv-thread-modes yes --tomokv-thread-balance yes --save ''

redis-cli -p 6379 ping
```

Boolean knobs take `yes`/`no`. Pin the server to one node-set of cores and the load generator
elsewhere for meaningful numbers.

## Known gaps (honest list)

- **HFE (hash-field TTLs)**: the estore keeps single-writer aggregates — `HEXPIRE`-family on a
  shared node db is not MT-safe yet.
- **Spare-thread mode**: activation into a shared node is rejected (the spare keeps a private db);
  the flip model replaces the spare anyway.
- **SCAN** on shard data: unchanged from the base engine (decoy-bound).
- **Concurrent per-node migrations**: nodes *decide* independently but conversions serialize
  through one migration gate (~ms each); true concurrency needs per-node migration state.
- **Controller convergence-lock** doesn't engage at the optimum yet (it keeps probe-reverting) —
  cheap probes make this churn tolerable, but it's the top controller TODO.
- A pre-existing mass-connection-kill livelock (`freeClientsInAsyncFreeQueue`) reproduces on both
  branches with a now-deterministic recipe (see `NUMA_SHARED_KV_PLAN.md`) — not introduced here,
  still to be root-caused.

## The Tomo KV family

| edition | branch | keyspace | reshard |
|---|---|---|---|
| 2-Stage (base) | — | per-worker isolated | copy engine |
| NUMA · physical shards | `2s-numa-mcmd-lock-dev` | per-worker isolated | copy engine |
| **NUMA · shared node db** (this) | `2s-numa-shared-kv-dev` | **one per node, bucket-owned** | **O(1) ownership flip** |

Design documents: `NUMA_SHARED_KV_PLAN.md` (implementation log + every measured result),
`MCMD_LOCK_DESIGN.md` (the lock-borrow evolution), `SHARED_KEYSPACE_DESIGN.md` (the original
proposal this implements, refined to db-per-node).

Tomo KV is a research fork of [Redis](https://github.com/redis/redis) (8.x) and inherits its data
types, protocol, and command surface.
