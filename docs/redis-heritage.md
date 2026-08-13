# Redis heritage: what TomoKV keeps, adapts, and replaces

TomoKV is a Redis **8.6.2** fork (`REDIS_VERSION "8.6.2"`, `REDIS_VERSION_NUM 0x00080602`; the
binaries and the `HELLO` identity stay Redis-facing — [`src/version.h`](../src/version.h#L1-L2),
[`src/networking.c`](../src/networking.c#L5900-L5912)). This page collects, in one place, exactly which
parts of the original Redis architecture survive unchanged, which are kept but rewired for the
sharded thread-per-core model, which are replaced outright, and which are refused at startup.

## One-line answer

TomoKV keeps Redis's entire **command "front half"** — the RESP protocol, the command table, the
actual command *implementations*, and the reply machinery — and replaces the **"back half"**: the
single-threaded event loop becomes a key-sharded thread-per-core engine, and the per-`dict` keyspace
becomes the lock-free **FLATSTORE** open-addressing table.

Two points that come up a lot:
- **FLATSTORE replaces the in-memory key store; it is not an index layered over a `dict`.**
- **FLATSTORE is unrelated to RDB.** RDB persistence is a separate, *kept* subsystem that was
  adapted to serialize the sharded store.

## Kept unchanged — the Redis front half and command semantics

- **RESP protocol.** Inline and RESP-multibulk request parsing, RESP2/RESP3 replies, and `HELLO`
  version negotiation are the upstream code paths ([`src/networking.c`](../src/networking.c#L543-L551),
  [`src/networking.c`](../src/networking.c#L5831-L5845)).
- **Command table.** Inherited verbatim from Redis's generated command definitions
  ([`src/commands.c`](../src/commands.c#L1-L13)); TomoKV only *stamps routing metadata* onto the
  existing table rather than redefining commands.
- **Command implementations.** The real per-type logic — `getCommand`/`setCommand` in
  `t_string.c`, and the `t_hash.c` / `t_zset.c` / `t_list.c` / `t_set.c` families — runs **unchanged**.
  The only difference is *where* it runs: on the owning EX worker thread instead of the single main
  thread. A command's keys, arity, flags, and side effects are the Redis ones.
- **Reply machinery.** `addReply*`, shared replies, and the client output buffers are upstream.
- **Introspection / config.** `INFO`, `CONFIG`, and the config parser are inherited (TomoKV adds its
  own `tomokv-*` knobs on top).

## Kept but adapted to the sharded store

- **Keyspace databases.** The logical `server.db[i]` a client addresses is a facade. The real data
  lives in **per-worker shard databases** `server.exThreads[w].db[i]`; workers within one topology
  node alias a single physical DB array ([`README`](../README.md) "Architecture",
  [`src/server.c`](../src/server.c#L5561-L5585)).
- **RDB persistence (`SAVE`/`BGSAVE`/load).** **Kept**, and rewired to the shards: save iterates each
  worker's shard DB (`rdbSaveDb(&server.exThreads[w].db[j], …)` —
  [`src/rdb.c`](../src/rdb.c#L1704-L1714)); load routes every key to its owning worker via
  `exIndexForKey` and pre-sizes each node's flat table so the reload can't thrash a resize
  ([`src/rdb.c`](../src/rdb.c#L3932-L3936), [`src/rdb.c`](../src/rdb.c#L4008)). RDB is the on-disk
  *image of* whatever FLATSTORE holds — not the store itself.
- **Expiry.** Kept; expiry stores deliberately stay **DICT-backed (non-FLAT)** in every mode
  ([`src/server.c`](../src/server.c#L5561-L5585)).
- **Single-owner scripting / notifications.** Keyspace notifications, pub/sub, and MULTI/EVAL work
  within a single owner shard; multi-key shapes that would span shards are gated (see below).

## Replaced / re-architected — the back half

- **Concurrency model.** The single-threaded event loop becomes **thread-per-core**: *IO owners*
  keep connection, RESP parsing, and socket-output ownership, while *EX workers* execute commands.
  Each key belongs to exactly one worker, so command execution needs **no per-key lock**
  ([`src/server.c`](../src/server.c#L5614-L5625)).
- **Keyspace storage — FLATSTORE.** The per-index `dict` is replaced by the `KVSTORE_FLAT` branch of
  `kvstore`: a power-of-two array of atomic 64-bit slot words holding encoded `kvobj` pointers,
  resolved by lock-free linear probing ([`docs/storage-flatstore.md`](storage-flatstore.md),
  [`src/flatstore.c`](../src/flatstore.c#L207-L237)). It is selected when a node has **more than one
  EX worker** (shared-node mode). `kvstore` still allocates the `dicts[]` pointer array, but with
  `KVSTORE_ALLOCATE_DICTS_ON_DEMAND` the dictionaries are **never instantiated** and find/set branch
  to the flat table — i.e. the flat table *is* the store, not an index over a dict. With **one EX
  worker per node**, the store stays DICT-backed.
- **Memory reclamation — QSBR.** Inline `free()` is replaced by epoch-based deferred reclamation for
  retired values and replaced tables: a worker never frees an object a peer might still be reading
  ([`docs/reclamation-qsbr.md`](reclamation-qsbr.md)).
- **Request dispatch.** The normal request path is replaced by the real-client / fake-ring / SPSC /
  CDB IO→EX handoff; cross-shard commands use explicit gather / fan-all / pipeline / two-hop plans
  ([`docs/crossshard.md`](crossshard.md), [`docs/execution-model.md`](execution-model.md)).
- **Routing + online resharding.** Keys hash into **16,384 virtual buckets**; `ex_bucket_table` maps
  each bucket to its current owner worker, and resharding flips bucket ownership without copying keys
  where possible ([`docs/reshard-migration.md`](reshard-migration.md)).
- **Optional MVCC atomic mode.** Off by default; when enabled it gives multi-key atomic visibility
  across owners ([`docs/atomics-mvcc.md`](atomics-mvcc.md), [`src/config.c`](../src/config.c#L3183-L3184)).

## Refused at startup — does not fit the sharded model

- **Always refused:** Redis **Cluster**, external **modules** (the module API cannot see the sharded
  keyspace — [`src/server.c`](../src/server.c#L5771-L5790)), and the upstream **IO-thread pool**.
- **Refused under TomoKV sharding:** **AOF**, replica startup (`replicaof`/`slaveof`), **maxmemory
  eviction**, client eviction, and active **defragmentation** — those subsystems do not operate on
  the worker-owned dataset ([`src/server.c`](../src/server.c#L5651-L5715)). See the README
  [Compatibility and scope](../README.md#compatibility-and-scope) for the authoritative list.

## Consistency note

Replies stay in per-connection dispatch order, but with atomic mode off (the default) non-atomic
work on *different* owners can execute concurrently: a cross-worker `MSET` applies each owner's shard
independently rather than as one transaction, and cross-owner reads do not share a snapshot
([`src/server.c`](../src/server.c#L11706-L11759)).
