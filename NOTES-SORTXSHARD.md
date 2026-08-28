# Cross-owner SORT BY/GET notes

## 2026-08-28: static trace and design checkpoint

No part of this lane is already implemented.  The current multi-executor path still refuses every
`*`-bearing BY/GET in `parse_sort_options`, and `sort_run` still calls `sort_lookup`, which reaches a
second `Shard` directly.  That is legal only because admission currently proves one executor owns
all shards.

The existing seams are sufficient without changing the MVCC resolver or atomic record engine:

1. `xshard_prepare` already forces an actually-dereferencing SORT off localfast.  Its phase-one
   group contains only the source key (the STORE destination is deliberately omitted until hop 2).
2. The source owner's task serializes one source `ObjectImage`.  This is the point at which the
   natural-order element list becomes knowable.
3. A SORT-only state object will be carved into the scatter arena.  Its vectors own the decoded
   elements, concrete derived key/field requests, owner-grouped request order, and resolved values.
   No state is added to `Op` or `Client`; the only new `ScatterState` member is a pointer at its cold
   tail.
4. Completion of the source wave expands every `*`-bearing BY and non-`#` GET pattern for every
   source element.  Requests are bucketed by `router().shard_of(hash)` and posted as a second READ
   wave.  Every task reads only the `FlatStore` of the `Shard&` passed to it.
5. `xshard_execute` already installs `PinnedNowMs(state.now_cut_ms)` and a `ReadEpochGuard` from
   `state.snapshot`/`origin_conn_id` for every owner task.  The derived wave will run under those
   same two cuts as the source wave.  Dereferencing SORT must therefore pin a snapshot even when
   the command has STORE and even at atomic mode 0.
6. Once the last derived owner finishes, one executor calls the existing `sort_run` ordering core
   with a resolved-value matrix.  Missing keys, wrong types, and absent hash fields leave the
   corresponding presence bit clear.  `GET #` and globless patterns never create requests.  The
   existing result/presence vectors then feed either the array reply or `sort_encode_store`.
7. STORE continues through the existing phase-two `hop2[0]` plan and `apply_image_selected`, so the
   destination is written only by its ordinary owner task.

`sort_run` will remain the single implementation of ordering, LIMIT, DESC, NULL handling, and GET
row construction.  The direct shard lookup will be removed; the core will consume optional
parallel resolved BY/GET arrays instead.  Non-dereferencing forms pass no resolved matrix.

### Wave/state details

The ordinary `phase` byte remains 1 for both read waves and 2 for STORE apply.  A SORT-only wave enum
in the arena sidecar distinguishes source/gather/resolved.  This avoids changing the generic
two-hop mutation tests.  Before calling `finish_phase1`, derived groups are replaced with the
original explicit-key groups so generic status/error scans never index the dynamic request order.

Bare commands need a derived-wave publisher shaped like `publish_phase2`.  EXEC children do not
post new tasks: all shards are already transaction participants, so the last source owner rebuilds
the child groups, resets `pending`, and returns `PhaseAdvanced`; participant loops discover their
new group on the next child stage.  The same happens once more for STORE apply.

Task dependency/hazard enumeration must recognize the derived-wave key order instead of indexing
the explicit argv-key array.  This is routing glue only.  The resolver, version selection, commit
publication, and atomic apply machinery are unchanged.

### Snapshot cut inside EXEC

The parent transaction already pins one `SnapshotCut` when it contains a multi-owner read and stamps
read-only xshard children from it before dispatch.  Dereferencing SORT must opt into that same path
even with STORE: its read participant set is dynamic and may span owners although its initial source
group has size one.  The child must borrow the parent's registered cut; it must not register its
private scatter pool independently.

### Required validation geometry (not run in this lane)

This lane must never be validated with one executor.  The gate geometry is exactly:

```
--shards 16 --ratio 6:2 --enable-debug-command yes
```

The SORT battery will fail unless INFO reports 6 I/O and 2 executor threads and a wide `DEBUG SHARD`
candidate walk observes exactly shards 0 through 15. Because the default placement assigns shard
`sid` to executor slot `sid % 2`, it walks candidate pattern prefixes, queries `DEBUG SHARD` for the
source and every concrete derived key, and requires at least one derived key whose shard maps to the
other executor slot. It prints the source/derived shard pair and fails loudly if none is found.
STORE destinations are selected by the same geometry search rather than assumed from a key spelling.

Per lane rules, I have not built anything, run any test/load script, or started a server.

## 2026-08-28: implementation checkpoint

Implemented the planned owner-only waves:

- `sort_run` no longer includes or reaches `Server`, `Shard`, `FlatStore`, or `KvObj`. It consumes
  optional parallel resolved BY/GET arrays, so it remains the only ordering/LIMIT/projection core.
- A `SortDerefState` object is carved after the ordinary scatter arrays. The only new
  `ScatterState` member is its pointer at the cold tail. Concrete keys, fields, values, presence
  bits, and dynamic key order live in that arena-owned object's vectors.
- Source completion decodes the natural elements, expands concrete requests, and rebuilds the dense
  shard groups. Each gather task promotes/resolves only keys in its own `Shard&`, under the existing
  `ReadEpochGuard(state.snapshot, origin_conn_id)` and `PinnedNowMs(state.now_cut_ms)`.
- The last gather task reduces into `ResultHeap`, restores the explicit source groups before generic
  error/status scanning, and either finishes the reply or enters the unchanged STORE hop.
- Bare SORT has a derived-wave publisher. EXEC uses the already-declared all-shard participant
  barrier and advances the child stage twice (source to gather, then gather to STORE when present).
- Dynamic request keys were added to task hazard/dependency enumeration; no generic explicit-key
  index is used during the gather wave.
- Dereferencing SORT now pins a snapshot even for STORE and atomic mode 0. In EXEC it causes the
  parent transaction to register a cut and borrows that exact cut, including for STORE children.
  No resolver/version/publication code was changed.
- The multi-executor option refusals, `sort_deref_local`, and both denial constants were removed.

## 2026-08-28: validation and cleanup checkpoint

- `tests/sort.py` now rejects any geometry other than 16 observed shards at a 6:2 I/O:executor
  ratio. It buckets candidate names with `DEBUG SHARD`, derives the default owner slot from
  `shard % 2`, and fails loudly unless the source has concrete BY and GET keys plus a STORE
  destination on the other executor. The proven command asserts both its exact result and exact
  derived-lookup/reduction counter deltas.
- `tests/gate.sh` gives SORT its own two-executor boot in both atomic modes. The old one-executor
  negative-control target and refusal assertions were removed; the semantic, RYOW, MULTI/EXEC,
  STORE, and randomized phases now all run under the cross-owner geometry.
- Operator documentation no longer describes BY/GET as placement-dependent. The original
  `NOTES-SORT.md` is explicitly marked historical.

Per lane rules these are static test definitions only: no build, server, test, or load process was
started in this lane.
