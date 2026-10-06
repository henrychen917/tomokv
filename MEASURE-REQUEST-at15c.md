# AT15c — seed-7 edgetime PTTL investigation

Work in progress, 2026-10-06. This lane merged `origin/cpp` before editing
(merge `bfc13903f`).
Only this worktree is edited. No production change, test comparison relaxation,
EXPECT edit, benchmark, or push is part of this investigation.

## Reproduction and scheduling conditions

Three POST and three frozen PRE full armed-fused replays use the unchanged
`docs/at15b/replay.sh` and `tests/differ_gate.sh`, alternating arms, with fresh
output directories under `build/at15c/replay-*`. The wrapper requests 16 shards,
eight fused threads, read-local=1, databases=16, atomic=0; target CPUs 112–119,
Redis CPU 120, clients 121–127. All six frozen seeds and all discovered suites
remain in each replay. A failed matrix is retained as failed.

**Observed interference:** unrelated compiler jobs and another lane's server
were active. Although TomoKV's startup correctly discovered CPUs 112–119,
subsequent `/proc` readings showed TomoKV and Redis thread affinity masks
broadened to CPUs 112–127. `docs/at15c/host-conditions-1.json` preserves the
observed processes, working directories and per-thread masks. This lane did
not broaden those masks. These conditions limit performance attribution.

The first POST run reproduces both operations at −5 ms (target minus oracle).
The final reproduction table and full matrix verdicts are pending.

## Exact stream and hypotheses

`docs/at15c/dump_stream.py` extracts the unchanged generator with seed 7 without
opening a socket. `edgetime-seed7.json` contains all 4,426 zero-based operations
and concrete illustrative deadlines; `edgetime-seed7-context.log` contains both
pipeline prefixes and all preceding references to the queried keys. Each live
trace separately preserves its actual generated deadlines.

| Operation | Command | Deadline source / nearby work |
| --- | --- | --- |
| 1526 | `PTTL et:s:28:37b3577a50660a7f7dc658feabe6c5fe53` | Batch 1472–1535; MSET 1491, EXPIREAT 1492 (`floor(future_ms/1000)` seconds); KEYS 1521 and seven-key EXISTS 1525 |
| 2910 | `PTTL et:s:23:2c57d06537cb90580459a716b6b8cb20c4` | Batch 2880–2943; GETEX PXAT 2766 installs `future_ms`; PEXPIREAT GT 2878 names the same deadline; KEYS 2882, SINTERSTORE 2896, MGET 2903 and RENAME 2908 precede it |

The deadlines are a month in the future, not crossing expiry at these queries.
Hash-field expirations at deadline 1 exist in the chunks, on other hash keys;
the queried objects are strings. Active expiry is disabled by operation 0.
The stream contains no INFO, MULTI, EXEC, WAIT, DEBUG SLEEP, or notification
configuration/subscription. It ends by restoring active expiry.

Static ranking before live timing:

1. Existing cross-shard/store-walk scheduling or external scheduling delay:
   reachable (`KEYS` uses bounded scans and retry queues).
2. Owner-reference initialization: no ordinary-dispatch route found. Parser
   calls `multi_dispatch_entry` only for transaction commands or an existing
   MULTI session (`src/core/io_loop.h:3744`). `multi_dispatch_started` is called
   on final EXEC publication, after the transaction's time cut; the guard adds
   no timer, sleep, retry or deadline.
3. `no_multi`: checked only after requiring an active MULTI session
   (`src/cmd/multi.inc:1715`); metadata and ordinary dispatch source are
   unchanged from frozen PRE.
4. Subexpiry census: ordinary census is selected only by `Kind::DatabaseInfo`
   (`src/cmd/scatter_engine.inc:3342`), as is the EXEC census
   (`src/cmd/multi.inc:2165`). It is not part of KEYS or hash expiry.

## Client timing and server profile

`docs/at15c/trace_differ.py` executes the unchanged harness AST and wraps only
`conn`/`read_reply`. It retains every send and top-level pipelined reply's
monotonic and realtime start/end timestamps and raw bytes. Generators, 64-op
batches, read order, equality comparisons and exit statuses stay unchanged.
Client read completion is not server execution time: replies are buffered and
the harness reads target before oracle. `deadline - PTTL` independently yields
each server's millisecond command time cut, which is compared with the send
and read bounds. No clock tolerance is widened.

The separate focused replay owns fresh listeners at the wrapper's geometry.
POST uses `perf record -C 112-119 -g --call-graph dwarf,8192 --switch-events
-e cycles:u -F 999`. Timing and profile results are pending.

## Source-aware bisect

`docs/at15c/commit-inventory.json` inventories all sixteen lane commits by
`src`, Makefile and third-party tree identity. The frozen PRE is `61a9ab20f`.
AT15b has two production-changing commits: `bb5b461ee` and `76568a8fc`; all
seven later commits retain `76568a8fc`'s production tree. The first commit
names `hash_ttls_of`, while the follow-up uses the declared `hash_ttl_slot`.
The isolated builder records whether the intermediate tree compiles and links
candidate trees under `build/at15c/bisect-<sha>/tomokv` from frozen objects with
per-input SHA receipts. A first-bad result requires a stable passing PRE.

## Outcome, validation and arms

Root cause / non-defect proof, hot-body byte audit, rebuilt binary hashes and
the final directed receipts remain pending. No production fix is justified yet.

No gate row was added or removed; EXPECT counts require no change.
