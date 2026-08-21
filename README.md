# TomoKV

## What it is

TomoKV is a Redis 8 fork that shards a keyspace across dedicated execution workers. IO owners retain
connection and parsing ownership; socket-output ownership stays on IO in the default two-stage boot
or moves to a sticky write-back (WB) thread when that optional stage is enabled. The inherited
version macros are
`REDIS_VERSION "8.6.2"` and `REDIS_VERSION_NUM 0x00080602`; the binaries and `HELLO` identity also
remain Redis-facing. ([`src/version.h`](src/version.h#L1-L2),
[`docs/ARCH_BRIEF.md`](docs/ARCH_BRIEF.md#L1-L5),
[`src/Makefile`](src/Makefile#L421-L429),
[`src/networking.c`](src/networking.c#L5900-L5912))

The fork keeps the Redis protocol parser, command metadata, and reply machinery, but replaces the
normal request path with IO-to-EX dispatch, owner-routed storage, cross-shard execution, and deferred
reclamation. It is not a drop-in replacement for every Redis deployment feature; the supported
boundary is described under [Compatibility and scope](#compatibility-and-scope). For a consolidated
view of exactly what is kept, adapted, replaced, and refused from upstream Redis — including why
FLATSTORE replaces the `dict` key store (and is unrelated to RDB) — see
[Redis heritage](docs/redis-heritage.md).

The consolidated integration candidate is stamped
`loopback-final.2026-08-17.1`. Its ordered source boundaries, retained unified-side work, selected
pipeline modes, and cross-branch invariants are recorded in
[Loopback-final unified pipeline](docs/unified-pipeline.md). This integration stamp does not change
the Redis-facing `8.6.2` identity above.

## Architecture and per-command lifecycle

Every supported configuration resolves at least one IO thread and one EX worker per topology node.
With both counts and the core budget omitted, the two-stage pool is the process's
`sched_getaffinity` CPU count divided across nodes and starts two-thirds IO / one-third EX, rounded
to `io11/ex5` at 16 CPUs. Explicit `tomokv-thread-io` and `tomokv-thread-ex` values describe and
override that starting split per node; `static` keeps the split, while `auto` permits per-node
controllers to convert provisioned threads between roles at between-slice checkpoints. Each node's
controller decides independently from its own signals, while physical conversions serialize
globally. Single-node configurations take a dedicated
`nnodes == 1` path that bypasses the multi-node admission protocols, so single-node flip behavior is
identical to the pre-topology controller. Both modes use the same polymorphic thread machinery. ([`src/server.c`](src/server.c#L5614-L5625),
[`src/server.c`](src/server.c#L5717-L5776),
[`src/server.c`](src/server.c#L5840-L5850),
[`src/server.c`](src/server.c#L23146-L23420))

`tomokv-thread-wb` selects the reply pipeline at boot. Its default `0` preserves the existing
`IO -> EX -> IO` path and allocates no WB runtime state. Positive `N` creates `N` dedicated WB
threads per node, while `-1` assigns the physical-core-budget remainder. In that mode IO only
receives/parses/dispatches, EX executes shard-local work, and one sticky WB per connection owns
post-EX coordination and every socket send. WB remains a fixed role outside the IO/EX flip pool.
See [Boot-selectable write-back stage](docs/writeback-stage.md).

Keys hash into 16,384 virtual buckets, and `ex_bucket_table` maps each bucket to its current worker.
Workers in one topology node alias the same physical database array. When the resolved pool has more
than one EX slot per node, the physical key stores are shared FLAT kvstores; with one EX slot per
node, the key store remains DICT-backed. Expiry stores remain non-FLAT in either case. ([`src/server.h`](src/server.h#L1560-L1571),
[`src/server.c`](src/server.c#L5561-L5585),
[`src/server.c`](src/server.c#L6108-L6137))

A normal command follows this path:

1. **Accept and read.** An IO owner accepts the connection, creates and owns the real client, and
   reads through the event-loop path or the optional io_uring bridge. ([`src/networking.c`](src/networking.c#L503-L613),
   [`src/networking.c`](src/networking.c#L4718-L4953))
2. **Parse and preprocess.** The owner parses inline or RESP multibulk input into a
   `pendingCommand`, resolves command metadata, extracts keys, and computes routing state.
   ([`src/networking.c`](src/networking.c#L4478-L4715),
   [`src/server.c`](src/server.c#L7692-L7746))
3. **Choose a route.** Validation selects stateful execution, one owner worker, a supported
   cross-shard plan, or synchronous IO-side fallback. Stateful operations wait for the client's
   in-flight ring to empty; even synchronous fallback completes through that ring so it cannot
   overtake older replies. ([`src/server.c`](src/server.c#L8191-L8277),
   [`src/server.c`](src/server.c#L8494-L8645))
4. **Reserve a fake.** Non-stateful work takes `dispatchid & ring_mask` in the real client's
   bounded fake-client ring and moves command state into that fake. A full ring stalls admission
   without consuming the parsed command. ([`src/server.c`](src/server.c#L8304-L8434),
   [`src/server.c`](src/server.c#L20719-L20816))
5. **Publish worker work.** For worker and cross-shard routes, the IO owner stages the fake on the
   SPSC lane for that IO-producer/worker pair, then release-publishes the lane. A full lane
   back-pressures the producer rather than dropping the command. ([`src/server.c`](src/server.c#L3882-L3961),
   [`src/server.c`](src/server.c#L20859-L21054))
6. **Execute worker work.** For those routes, `exSlice` harvests advertised lanes, executes each fake
   against its worker DB under the applicable owner lock, and builds the reply on the fake.
   Cross-shard commands retain one ring head while per-owner sub-fakes execute and later stages are
   coordinated. ([`src/server.c`](src/server.c#L21479-L21602),
   [`src/server.c`](src/server.c#L21720-L22364),
   [`src/server.c`](src/server.c#L22144-L22199))
7. **Publish completion.** Worker routes release-publish the fake's CDB ready byte and then the
   lane's execution-retirement frontier. Synchronous IO fallback instead executes `call(fake)` on
   the owner and release-publishes CDB locally. In worker lanes, `retired == tail`, not merely
   `head == tail`, proves execution quiescence. With WB enabled, only a completion that is the
   ordered head advertises the connection in its WB's fenced ready bitmap. ([worker completion](src/server.c#L22242-L22263),
   [IO fallback](src/server.c#L8605-L8640))
8. **Retire in order and write.** At `tomokv-thread-wb 0`, the IO owner acquire-checks only the
   contiguous `flushid` prefix, splices ready replies, recycles each slot, and writes. With WB
   enabled, the sticky WB performs that ordered drain, advances post-EX cross-shard stages, and is
   the sole writer. Workers may finish out of order; wire replies do not. ([`src/server.c`](src/server.c#L4120-L4383),
   [`src/networking.c`](src/networking.c#L1956-L2000),
   [`src/networking.c`](src/networking.c#L3355-L3628))

## Documentation map

- [Loopback-final unified pipeline](docs/unified-pipeline.md) — Version stamp and ordered content
  ledger for the consolidated two-stage/WB, flip, atomic, read-fast, and Arm C candidate.
- [Thread-per-core execution](docs/execution-model.md) — IO owners manage connections, parsing, and
  ordered output while EX workers consume per-producer SPSC lanes, execute against worker DBs, and
  publish per-client CDB completions.
- [FLATSTORE](docs/storage-flatstore.md) — Shared-node key storage uses a power-of-two,
  open-addressing table of atomic tagged-pointer slots; coordinated rebuilds publish a replacement
  and defer freeing the old table.
- [QSBR reclamation](docs/reclamation-qsbr.md) — Removed FLAT payloads are batched and reclaimed only
  after foreign-reader, dispatch-pin, IO-epoch, and worker-progress checks pass; replaced tables use
  a separate all-readers-outside test.
- [MVCC atomics](docs/atomics-mvcc.md) — When enabled, eligible cross-routed whole-value writes install
  per-key versions before publishing one group sequence, and snapshot resolution supports a
  connection's own uncommitted or stamped versions; the complete prune/lifetime path is FLAT-only.
- [Cross-shard scatter/gather](docs/crossshard.md) — Supported multi-key shapes are classified,
  coalesced or scattered to current owner workers, and reassembled once, with barriers around
  pipeline and two-hop continuations.
- [Online resharding](docs/reshard-migration.md) — A contiguous boundary range moves between adjacent
  workers sharing one physical database by draining old-owner lanes and rewriting ownership; drain
  acknowledgements carry a fence generation so a stale ack from an aborted cutover can never satisfy
  a newer fence. Keys are not copied and this is not cross-node data migration.
- [Load balancing](docs/loadbalance-flip.md) — Per-node controllers convert threads between IO and
  EX roles (deciding independently per node, serializing conversions globally), move adjacent-worker
  bucket ranges, and hand eligible connections between IO owners. Multi-node role state is observable
  via `INFO` (`tomokv_node_<n>_io_live` / `_ex_live`) and key→node routing via
  `DEBUG TOMO-NODEOF <key>`.
- [Boot-selectable write-back stage](docs/writeback-stage.md) — `tomokv-thread-wb` chooses the
  no-allocation two-stage path or a sticky-WB reply pipeline with fenced head readiness, optional
  SENDMSG batching, and WB-owned post-EX cross-shard completion.
- [Mechanism index](docs/mechanisms/INDEX.md)

## Benchmark results

Cross-system comparison sweep, 2026-08-13: TomoKV (`auto`, flip-cost-inclusive) vs stock Redis vs
Dragonfly v1.39 on one 8-core Zen 4 box, 8 GB fixed keyspace, 200 connections. Full protocol and
caveats in [methodology](docs/bench/methodology.md).

- [Cross-system throughput, 32 B](docs/bench/cross-system-d32.md) — TomoKV leads all 24 cells:
  4.3–4.7× Redis everywhere; 1.05–1.07× Dragonfly at p1 and 1.8× on pipelined reads.
- [IO↔EX split sweep](docs/bench/io-ex-sweep.md) — the bathtub: p1 optimum io7/ex1, p32 GET optimum
  io5/ex3, p32 SET optimum io4/ex4; the flip lands the optimum in three of four regimes.
- [Multi-key MGET/MSET](docs/bench/multikey-mget-mset.md) — TomoKV +10–21% unpipelined; Dragonfly
  ~13% ahead pipelined (marked optimization target).
- [Multi-key atomicity](docs/bench/atomicity-torn.md) — torn-read probe: TomoKV `tomokv-atomic yes`
  and Redis are torn-free; TomoKV `atomic=off` tears 24% under maximal contention by design;
  Dragonfly v1.39 (defaults) tears 0.74%.
- [Flip convergence cost](docs/bench/flip-cost.md) — auto boots balanced and converges inside the
  measured window: 10–15 s typical (~1%), 115 s worst observed (~4%).

**EPYC 9754 "Bergamo" (64 server cores), 2026-08-15** — first big-box results, branch
`epyc-hardening-dev` (probe-start mixer, SMT-aware ccd pinning, two-phase online resize,
role-identity adoption, large-pool flip episodes; `KNOWN_ISSUES.md` has the honest ledger):

- Sustained 16 GB populate p99.99 write tail **2392 ms → 40 ms** (parallel copy, then
  serve-while-copy resize); populate throughput +2× to ~12 M SET/s.
- vs Dragonfly v1.39 at equal cores: GET pipe-32 **19.9 M vs 7.8 M (2.56×)**, SET pipe-32 15.1 M vs
  9.5 M, pipe-4 GET 10.3 M vs 5.0 M (2.08×); unpipelined p1 3.45 M vs 3.71 M (−7%) — parity at
  ≤32 cores, and the p1 comparison is loadgen-arrangement-sensitive (see EPYC_FIRST_LIGHT.md).
- Per-thread economics: one EX thread saturates at ~1.18 M unpipelined ops/s on Zen 4c; io:ex knee
  ≈ 16:1 at p1; the flip's large-pool episodes land io60/ex4 on a 64-thread pool (was a 32↔63
  sawtooth livelock).
- SMT oversubscription (128 server threads on 64 cores) hurts both engines — TomoKV −44% p1 /
  −56% p32, Dragonfly ±5% p1 / −34% p32. Don't.

## Configuration

This is the complete TomoKV configuration surface registered by `createXConfig` in
[`src/config.c`](src/config.c#L3182-L3319). `Immutable` means startup-only; `modifiable` entries may
be changed at runtime. The compiled bounds used below are 16 topology nodes, 128 IO threads, 128 EX
workers, 128 WB threads, and a maximum pipeline depth of 32. ([`src/server.h`](src/server.h#L1486-L1487),
[`src/server.h`](src/server.h#L1523),
[`src/server.h`](src/server.h#L1559))

| Name | Type | Default | Accepted values | Effect |
| --- | --- | ---: | --- | --- |
| [`tomokv-atomic`](src/config.c#L3183) | Boolean, modifiable | `no` | `no`, `yes` | Enables MVCC admission for eligible cross-routed atomic writes and snapshot reads; enabling it initializes lifecycle state, and changes wake parked clients. ([apply callback](src/config.c#L3141-L3149)) |
| [`tomokv-atomic-window`](src/config.c#L3190) | Integer, modifiable | `-1` | `-1..INT_MAX` | Caps admitted in-flight atomic write groups; `-1` derives the limit from live writer concurrency and pipeline depth, `0` is unlimited, and a positive value is exact. |
| [`tomokv-atomic-reclaim-limit`](src/config.c#L3191) | Integer bytes, modifiable | `-1` | `-1..LLONG_MAX` | Bounds the process-wide pool of atomic-version bytes awaiting physical reclaim; `-1` derives one RAM/maxmemory budget, `0` disables accounting/allocation, and pressure stalls writers before ring allocation. |
| [`tomokv-client-lb`](src/config.c#L3311) | Boolean, modifiable | `yes` | `no`, `yes` | Enables continuous migration of eligible connections away from sustained busy-outlier IO owners. |
| [`tomokv-cores-per-node`](src/config.c#L3210) | Integer, immutable | `0` | `0..384` | Sets the core budget per topology node; at WB=0, `0` uses the explicit IO+EX sum or, when a role is missing, the process affinity count divided across nodes. With explicit WB it derives IO+EX+WB, and with WB=-1 it is derived from allowed physical cores. |
| [`tomokv-io-uring`](src/config.c#L3245) | Integer, immutable | `0` | `0..2` | Selects the native event-loop backend (epoll on Linux) at `0`; `1` selects the staged/taskrun-aware io_uring backend and `2` is its compatibility spelling. ([runtime dispatch](src/uring2.c#L1768-L1776)) |
| [`tomokv-uring-multishot`](src/config.c#L3257) | Integer, immutable | `0` | `0..8192` | Uses one-shot receive with no provided-buffer ring at `0`; positive `N` requests multishot receive with `N` registered buffers per IO owner. Unsupported setup or arm flags fall back to one-shot for that owner. |
| [`tomokv-uring-sendcopy-min`](src/config.c#L3258) | Integer, modifiable | `0` | `0..INT_MAX` bytes | Keeps scratch-copy sends at `0`; positive `N` permits an eligible plain client-buffer prefix of at most `N` bytes to remain pinned and be sent directly. |
| [`tomokv-key-lb`](src/config.c#L3292) | Integer, modifiable | `20000` | `0..INT_MAX` | Sets the bucket-balancer load floor; `0` disables it, and the controller compares `N` with operation deltas from its nominal one-second sampling tick rather than an elapsed-time-normalized rate. ([schedule](src/server.c#L2943-L2947), [controller](src/server.c#L16882-L16918)) |
| [`tomokv-nodes`](src/config.c#L3209) | Integer, immutable | `1` | `1..16` | Sets the number of topology nodes; `ccd` placement composes each node from adjacent shared-L3 groups as needed, while `numa`, `float`, and `static` give nodes NUMA, logical, and explicit meanings. |
| [`tomokv-os-busypoll`](src/config.c#L3289) | Boolean, immutable | `no` | `no`, `yes` | Enables best-effort `SO_BUSY_POLL` on accepted sockets; it is separate because kernel busy-polling consumes CPU. ([socket setup](src/socket.c#L196-L202)) |
| [`tomokv-os-opts`](src/config.c#L3288) | Boolean, immutable | `no` | `no`, `yes` | Enables best-effort `TCP_QUICKACK` on accepted sockets and `MADV_HUGEPAGE` on hot worker allocations. ([socket setup](src/socket.c#L188-L195), [worker allocation](src/server.c#L22841-L22864)) |
| [`tomokv-pin-ex`](src/config.c#L3253) | String, immutable | `""` | Empty or a valid static CPU specification | Supplies per-node EX-worker CPU lists for static pinning, for example `node0=4-7 node1=12-15`. ([grammar and checks](src/server.c#L22464-L22617)) |
| [`tomokv-pin-io`](src/config.c#L3252) | String, immutable | `""` | Empty or a valid static CPU specification | Supplies per-node IO-owner CPU lists for static pinning, for example `node0=0-3 node1=8-11`. ([grammar and checks](src/server.c#L22464-L22617)) |
| `tomokv-pin-wb` | String, immutable | `""` | Empty or a valid static CPU specification | Supplies per-node WB CPU lists. It is required only with WB enabled plus `pin-mode static`, and its backing matrix is not allocated at WB=0. |
| [`tomokv-pin-mode`](src/config.c#L3251) | Enum, immutable | `ccd` | `float`, `ccd`, `numa`, `static` | Chooses scheduler placement, shared-L3/CCD placement, NUMA placement, or explicit per-role IO/EX/WB CPU lists. ([enum](src/config.c#L178-L184)) |
| [`tomokv-pipeline-depth`](src/config.c#L3318) | Integer, immutable | `-1` | `-1..32` | Bounds the per-connection in-flight/fake-ring cap: `-1` resolves to 32, `0` to depth 1, and positive `N` sets the cap; per-client depth may decay and regrow, and positive choices should be powers of two because indexing uses a bit mask. ([resolution](src/server.c#L5860-L5865), [ring initialization](src/networking.c#L647-L661), [decay](src/server.c#L16598-L16630)) |
| `tomokv-p1direct-publish` | Boolean, modifiable | `no` | `no`, `yes` | Lets an eligible p1direct executor write a complete inline reply to a plain socket before publishing completion; partial and failed writes retain the normal IO-side flush. |
| `tomokv-prefetch-ex` | Integer, modifiable compatibility parser | `1` | `0..2` | Retains the p1-lineage configuration surface. The flip lineage retired the broad selectable prefetch apparatus; targeted storage and gather lookahead remain automatic, so this stored value does not select a data path. |
| `tomokv-prefetch-io` | Integer, modifiable compatibility parser | `0` | `0..2` | Retains the p1-lineage configuration surface. The flip lineage retired the broad selectable prefetch apparatus, so this stored value does not select a data path. |
| [`tomokv-reorder`](src/config.c#L3218) | Integer, modifiable | `0` | `0..3` | Selects the staged IO-to-worker admission-reordering level; `0` bypasses the reorder machinery. ([dispatch gate](src/server.c#L3986-L4022)) |
| [`tomokv-reshard-fence-timeout`](src/config.c#L3303) | Integer, modifiable | `10000` | `0..INT_MAX` milliseconds | Sets the cutover watchdog for both the atomic-lifecycle pre-drain and producer drain-fence waits; a positive `N` aborts after `N` milliseconds, while `0` waits indefinitely. ([atomic pre-drain](src/server.c#L15879-L15927), [producer fence](src/server.c#L16011-L16032)) |
| [`tomokv-strict-order`](src/config.c#L3182) | Integer, modifiable | `0` | `0..100000` | Controls cross-IO worker-lane selection: `0` uses batched rotation, `1` selects the globally oldest head, and `N >= 2` permits an epsilon of `N-1` microseconds. ([field contract](src/server.h#L4107)) |
| [`tomokv-thread-ex`](src/config.c#L3244) | Integer, immutable | `0` | `0..128` | Sets the starting EX-worker count per node. At WB=0, two zero role values select the 2:1 IO/EX default from the core budget, which is affinity-derived when that budget is also zero; one explicit role wins and the other is the core-budget complement. |
| [`tomokv-thread-io`](src/config.c#L3243) | Integer, immutable | `0` | `0..128` | Sets the starting IO-thread count per node. At WB=0, two zero role values select the 2:1 IO/EX default from the core budget, which is affinity-derived when that budget is also zero; one explicit role wins and the other is the core-budget complement. |
| [`tomokv-thread-mode`](src/config.c#L3230) | Enum, immutable | `auto` | `auto`, `static`, `climb`, `model` | Selects r8 auto actuation, a fixed boot split, r8+r10 measured climbing, or m1 filtered-target actuation. ([enum](src/config.c#L171-L177)) |
| `tomokv-thread-wb` | Integer, immutable | `0` | `-1..128` | Selects the pipeline per node: `0` is the exact two-stage/no-allocation path, positive `N` creates dedicated WB threads, and `-1` takes the physical-core-budget remainder. WB is never a flip-adoptable role. |
| `tomokv-wb-uring` | Integer, immutable | `0` | `-1..4096` | Controls per-WB SENDMSG batching: `0` uses write/writev with no sender ring, `-1` derives a cap, and positive `N` caps SQEs per submit; unsupported rings fall back per WB. |
| [`tomokv-zerocopy-min-value`](src/config.c#L3319) | Integer, modifiable | `1024` | `0..INT_MAX` bytes | Uses copy-avoidance when forwarding values at least `N` bytes; `0` disables it. ([reply path](src/networking.c#L1758-L1763)) |

`tomokv-uring-sqpoll` and `tomokv-uring-coalesce` are retired experiments, not configuration
knobs. Their formerly meaningful non-default spellings are rejected at boot so stale deployments
cannot silently run a different path.

Static pin specifications are whitespace- or semicolon-separated `nodeN=cpu-list` tokens; each CPU
list accepts comma-separated IDs and inclusive ranges. Static mode requires IO and EX coverage, plus
WB coverage when WB is enabled; nonempty specifications with another pin mode are rejected.
([`src/server.c`](src/server.c#L22464-L22617))

## Build and run

The top-level default target delegates to `src`; `all` builds `redis-server`, `redis-sentinel`,
`redis-cli`, `redis-benchmark`, and the RDB/AOF check tools. The default optimization is `-O3` with
LTO and frame pointers. ([`Makefile`](Makefile#L1-L19),
[`src/Makefile`](src/Makefile#L24-L37),
[`src/Makefile`](src/Makefile#L421-L437))

```sh
make
./src/redis-server
./src/redis-cli

# Explicit three-stage boot:
./src/redis-server --tomokv-thread-io 1 --tomokv-thread-ex 1 --tomokv-thread-wb 1
```

There is no Makefile `run` target. With no two-stage thread options, the pool uses only CPUs in the
process affinity set and starts at the documented two-thirds-IO split; explicit IO/EX values retain
their authority. A resolved pool with at least two EX slots per node selects the shared FLAT key
store. ([`src/server.c`](src/server.c#L5717-L5776),
[`src/server.c`](src/server.c#L6108-L6137))

io_uring support is build-time `auto`: on Linux it is included when `pkg-config` finds liburing
2.4 or newer. `USE_URING=yes` makes that requirement strict; both IO receive and WB SENDMSG rings
remain runtime-off by default.
([`src/Makefile`](src/Makefile#L308-L335), [`src/config.c`](src/config.c#L3245))

The explicit `pgo-generate` and `pgo-use` targets exist, but they are not dependencies of the
default build. They build only the server, require a profile directory without whitespace, and both
force `USE_URING=yes`; no training workload target is provided. ([`Makefile`](Makefile#L11-L16),
[`src/Makefile`](src/Makefile#L577-L610))

```sh
make pgo-generate
# Exercise ./src/redis-server with a representative workload, then stop it.
make pgo-use
```

The default profile directory is `./pgo-data`; pass the same absolute `PGO_PROFILE_DIR` to both
commands to use another location.

## Compatibility and scope

- **Protocol.** New clients default to RESP2. `HELLO 2` and `HELLO 3` select RESP2 or RESP3 reply
  encoding, and inline plus RESP multibulk request parsing is retained. ([`src/networking.c`](src/networking.c#L543-L551),
  [`src/networking.c`](src/networking.c#L5831-L5845),
  [`src/networking.c`](src/networking.c#L3977-L3979))
- **Command surface.** The command table is inherited from Redis's generated command definitions,
  then TomoKV stamps routing metadata onto it. Supported cross-shard shapes use explicit gather,
  fan-all, pipeline, or two-hop implementations; unported multi-key shapes are rejected instead of
  running against the empty logical DB. MULTI/EXEC spanning worker shards returns `CROSSSLOT`.
  ([`src/commands.c`](src/commands.c#L1-L13),
  [`src/server.c`](src/server.c#L6696-L6729),
  [`src/server.c`](src/server.c#L8214-L8248),
  [`src/server.c`](src/server.c#L10784-L11179))
- **Consistency boundary.** Replies remain in per-connection dispatch order, but non-atomic work on
  different owners may execute concurrently. With atomic mode off by default, a cross-worker MSET
  applies owner shards independently rather than as one transaction, and cross-owner reads do not
  share a snapshot. ([`src/config.c`](src/config.c#L3183-L3184),
  [`src/server.c`](src/server.c#L11706-L11759),
  [`src/server.c`](src/server.c#L22171-L22199))
- **Replaced internals.** Dispatch is the real-client/fake-ring/SPSC/CDB path above. Shared-node key
  storage uses FLATSTORE instead of per-bucket dictionaries, and removed values plus replaced tables
  use the documented QSBR/deferred-reclamation protocols. The one-EX-per-node key-store path remains
  DICT-backed. ([`src/server.c`](src/server.c#L5561-L5585),
  [`src/flatstore.c`](src/flatstore.c#L207-L294),
  [`src/server.c`](src/server.c#L8955-L9233))
- **Unsupported deployment features.** Startup refuses Redis Cluster, external modules, and the
  upstream IO-thread pool. Under TomoKV sharding it also refuses AOF, startup configuration as a
  replica (`replicaof` / `slaveof`), maxmemory eviction, client eviction, and active defragmentation
  because those subsystems do not operate on the worker-owned dataset. ([`src/server.c`](src/server.c#L5651-L5715),
  [`src/server.c`](src/server.c#L6072-L6091))
