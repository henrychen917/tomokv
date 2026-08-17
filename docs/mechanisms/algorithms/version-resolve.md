# Version-bag snapshot resolution

## Visibility rule

A cross-shard read samples one global timestamp `T`. Every installed version points to its group's
shared `tomoCommit`; the version is committed when `commit_ts != 0` and normally visible when
`commit_ts <= T`.

The per-key stamped index is unordered because versions are linked before their commit timestamps
exist. `kvobjVersionAt` scans it and chooses the greatest visible `(commit_ts, version_order)`.
`version_order` preserves duplicate-key last-pair-wins within one group. A raw tail is the implicit
rank `(0, 0)`.

## Fast paths

`lookupKeyReadWithFlags` first performs the ordinary key lookup:

1. `vmeta == NULL` returns the raw object immediately. No atomic-mode test or clock load occurs.
2. `TOMO_SINGLE_COMMITTED` licenses a direct metadata-object return. With a pinned snapshot, the
   shared timestamp must be at or below that pin; an unpinned single-owner read needs no clock.
3. Any transient bag calls `kvobjVersionAt` with the command's existing pin or a lazy current
   timestamp.

Promotion after local retirement removes metadata from a sole live committed value, restoring the
first path. This is the steady-state reason pure reads do not pay a permanent MVCC tax.

## Own-uncommitted stage

The expensive physical scan is relevant only while the real connection's `mset_pending_count` is
nonzero. The physical chain is newest-install-first. `csMsetOwnVersionAt` skips canceled versions and
finds the first node whose immutable `origin_client_id` matches the reader.

- If its shared timestamp is still zero, return that own version (or absence for an own tombstone).
- If it is already committed, stop without considering an older delayed own group.

Same-key jobs from one connection retain owner-queue order, so the first non-canceled own node is
the connection's program-order newest installed write to that key.

## Stamped-index stage

The resolver acquire-loads `stamped_head` and follows `stamped_prev`:

- timestamp zero is skipped;
- timestamp at or below `T` competes for the greatest normal rank;
- a timestamp above `T` is invisible unless `origin_client_id` matches the reader;
- among own-above-`T` versions, the greatest connection-global `install_order` wins.

If an own-above-`T` candidate exists it is the result; otherwise the normal greatest rank is used.
A selected tombstone becomes `NULL`. Passing `reader_connection == NULL` disables both own stages
and yields strict snapshot resolution for write-side presence probes.

## Why own widening is required

A connection may pipeline MSET then MGET. MGET can pin `T` before the write commits. One key owner
may resolve while its own version is still uncommitted; another may resolve after the shared
timestamp is published above `T`. Without immutable connection identity, those keys could return
new and old values from the same own group.

The physical stage covers the first key. The own-above-`T` stamped candidate covers the second.
Other clients never pass the identity test, so the normal snapshot boundary remains intact.

## Snapshot and lifetime ordering

Cross-shard reads enter the FLAT group pin before sampling the commit clock. The last owner publisher
release-stores the shared timestamp and then the global clock. A reader that acquires the new clock
therefore sees every stamped link; one that sampled the old clock excludes the group.

Local PRUNE callbacks start only after commit publication. Their first grace protects readers whose
old snapshot may still require predecessors; physical free takes a second grace after unlink. The
resolver may consequently traverse stale-but-safe index or metadata pointers, but never freed
storage.

## Invariants

- One command uses one `T` across all of its owner subs.
- Non-own metadata with `commit_ts > T` is never selected.
- Shared `commit_ts == 0` makes every shard of that group invisible to normal readers.
- Own widening is exact connection identity, not a probabilistic membership filter.
- A raw or promoted key returns without a commit-clock access on the single-owner path.
- Retirement never changes a still-live version's rank; it only filters obsolete nodes.

See `src/db.c::lookupKeyReadWithFlags`, `src/server.c::kvobjVersionAt`, and
[MVCC atomic multi-key commands](../../atomics-mvcc.md).
