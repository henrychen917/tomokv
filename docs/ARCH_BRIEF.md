# TomoKV / THredis — architecture brief for reviewers

A fork of Redis 8 that shards the keyspace across NUMA nodes and executes commands on dedicated
worker threads. Read this before reviewing; it is the context you would otherwise spend hours
reconstructing, and several of the conclusions below were expensive to reach.

## Execution model

- **Threads have roles.** IO threads own client connections (per-io-thread `SO_REUSEPORT`
  listeners, so a connection belongs to exactly one io thread). EX worker threads execute commands.
  A 4 Hz controller (`tomoFlipController`) converts threads between the two roles at runtime — a
  "flip". Config is `--tomokv-thread-io N --tomokv-thread-ex M`, and `--tomokv-thread-mode auto`
  enables the controller. PARKED is the transit state of both flip directions.
- **Workers BYPASS stock `call()`.** Commands routed to a worker never enter `call()`, so everything
  stock Redis maintains inside it is silently skipped there. This has already produced a family of
  real bugs (commandstats read 0%, slowlog never fires for worker commands, MONITOR misses them,
  latency monitor, hotkeys, client-side-caching tracking, `c->woff`, `postExecutionUnitOperations`).
  **If you find more members of this family, that is a valuable finding.**
- **`server.db` is an EMPTY DECOY** under sharding. `initServer` says so verbatim; `selectDb()`
  hands every client `&server.db[id]`. The real keyspace is `server.node_dbs[node][dbid]`, aliased
  as `server.ex_dbs[w]` / `exThreads[w].db`. Two serious bugs came from code walking the decoy:
  active expiry never ran at all, and `DEBUG RELOAD` panicked. `activeSubexpiresCycle` has the same
  shape and is being fixed now. **Any other main-thread cron arm that walks `server.db` is suspect.**

## Storage

- **FLATSTORE** is a lock-free open-addressing table replacing per-bucket dicts. It is active iff
  `thredis_flat_store && shared_node_dbs`, where `shared_node_dbs = (workers_per_node > 1)`.
  **So at `--tomokv-thread-ex 1` the keyspace is DICT-backed and at ex>=2 it is FLATSTORE — two
  different engines.** Code gated on one is dead in the other. `kvstoreGetDict()` returns NULL under
  FLATSTORE, and a caller that silently no-ops on NULL is how a bug hides. Test both regimes.
- **QSBR epoch reclamation** protects flat-table readers. It covers the kvobj and the table, but NOT
  value interiors: `lpReplace`/`lpBatchAppend` reallocate and free immediately, so a concurrent
  reader can see a torn or freed value interior.
- `db->expires` is deliberately created with `KVSTORE_FLAT` masked OFF, so `kvstoreGetDict()` is
  valid on it.

## Ownership — the invariant that matters most

**Single-writer-per-slot.** `server.clients[t]` is written only by io thread `t`; `exThreads[w]`
state only by worker `w`; `tm_io_sig[t]` only by io thread `t`. A non-owner must NEVER traverse
another thread's structures — a use-after-free was found where the 4 Hz controller walked another
io thread's client list while that thread freed nodes eagerly.

**The correct pattern here is OWNER-PUBLISHES / READER-SNAPSHOTS**, not locking. Precedent:
`tmMigServiceOut` computes a flag on the owning thread and publishes it into `tm_io_sig` for main to
read (commit `7943601ab`). Per-thread state merged on read is the other standard move
(`server.dirty`, `execution_nesting`, per-command stats). **Never add a lock to the per-connection
request path.**

## Load balancing (three separate mechanisms, all on by default)

1. **Key LB** — migrates hot bucket ranges between workers. 16384 buckets, `ex_bucket_table[]` maps
   bucket→worker GLOBALLY (not node-partitioned), so clients already dispatch cross-node. Within-node
   only by design. A hot *key* is unbalanceable (`h > 1/W`) and is vetoed rather than chased.
2. **Client LB** — moves connections between io threads. NODE-SCOPED. Does not disconnect: it
   transfers ownership of an open socket.
3. **Flip** — the io/ex role controller above.

Reshard cutover uses a **drain fence**: the old owner finishes in-flight work, the new owner stalls
only the migrating range (not the whole thread), then ownership flips. Both sides keep serving their
non-conflicting buckets throughout.

## Ordering guarantees

Same key → same owner queue → FIFO. Same-client pipelined ordering is enforced by `cs_barrier`
(client stalls its next command until the fake ring drains). **Cross-key ordering within a client is
explicitly NOT guaranteed** — that is an owner ruling, not a bug.

## Conclusions already reached — do NOT re-derive these

- **Cross-thread allocator ownership is a dead end** (~0.3% ceiling, disproven). The real lever is
  allocation **COUNT**, not who frees.
- **The tiered operand pool was deleted** as net-negative. Per-type pools are disproven. A
  per-command arena is still open.
- **csGroup inline/SSO storage is DONE** (`968565c72`).
- **AMAC was rejected for the flat table**: its refill only pays on variable-depth chains, and the
  flat probe chain is constant-depth (~2 steps via a 15-bit tag). Group prefetching with distance =
  group size is the right shape.
- **The prefetch gate had never opened** for a long period due to a units bug (32x L3, not 8x).
  Later gate-open FLAT measurements still exercised operands only because the null per-bucket dict
  retired before storage; levels 2/3 now provide the explicit FLAT SLOT/KVOBJ experiment.
- **Value forwarding is permanently dead** (three physics walls, proven neutral everywhere).
- **io_uring was deleted entirely** after measuring: no win at io7/ex1 p1, plus a livelock under
  client LB. To be reimplemented from scratch later.
- `instr/op` is **polluted** on this fork: workers busy-spin (`exPauseCpu`), so a process-wide
  instruction count partly tracks idle time. Use **ops/s** for throughput verdicts.

## Hardware / measurement

7700X desktop, 8 cores. Server pinned 0-7, load generator 8-15. Box noise is ±2% **when exclusive**.
Standard apparatus: `-d 32`, 2M keys **seeded**, `-t 8 -c 25` (200 connections). Two bracketing
configs: **io4/ex4 at p32** (throughput-bound, FLATSTORE live) and **io7/ex1 at p1** (latency-bound,
DICT-backed). Reference: p1GET 826,877 · p1SET 817,393 · p32GET 7,943,860 · p32SET 6,852,385.
Target hardware later: 24-core multi-CCD Threadripper, 8-channel DDR5, NPS/NUMA modes.
