---
name: thredis-prefetch-dict-lifetime-invariant
description: "REFUTED: the next-op prefetch's cached `dict *` is NOT a use-after-free — the tomo branch deliberately omits KVSTORE_FREE_EMPTY_DICTS so bucket dicts persist. The safety depends on a flag nobody enforces."
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-07-30. An adversarial Codex review called the next-op prefetch fix DEFECTIVE with a detailed
six-step interleaving: `exPrefetchBatch()` caches a raw `dict *` in each fake, the exec loop
dereferences it several commands later, and a `DEL` earlier in the same popped batch frees the
now-empty bucket dict → worker-thread use-after-free. It reads convincingly. **It is false**, and I
verified it in the source:

- `initServer` (`src/server.c` ~4562-4577): `flags = KVSTORE_ALLOCATE_DICTS_ON_DEMAND`; the
  `cluster_enabled` branch adds `KVSTORE_FREE_EMPTY_DICTS` but is **unreachable** (cluster is
  refused at boot); the `else if (server.ex_threads > 0)` tomo branch **deliberately does not add
  it**, and the comment says exactly why: *"the IO-thread nextop prefetch (PFS_HASH #3 feed) reads
  worker dicts cross-thread; a dict freed-on-empty by its owner would turn that benign stale-read
  race into a use-after-free. Dicts persist once created."*
- `freeDictIfNeeded` (`src/kvstore.c:193`) returns early without the flag, so `DEL` cannot release
  a bucket dict; `kvstoreEmpty` frees the internal tables but retains the mapped `dict` object.
- `initTempDb` (`src/db.c` ~1241) mirrors the same two branches.
- `emptyDbAsync` (`src/lazyfree.c` ~286) checks ONLY `cluster_enabled` — but `emptyData` passes
  `async = 0` for `server.node_dbs` deliberately, so the real keyspace never reaches it.

**THE OPEN RISK IS THE UNENFORCED INVARIANT.** Prefetch safety depends on a flag never being set,
protected only by a comment. Anyone adding `KVSTORE_FREE_EMPTY_DICTS` later (to reclaim memory,
say) silently creates the UAF the reviewer described. A guardrail task (`guard-prefetch-invariant`)
was launched to convert it into a boot-time/compile-time check.

**Separate, still UNCONFIRMED:** `emptyDbAsync` has no `ex_threads` branch, so it rebuilds
`db->keys` with `slot_count_bits = 0` (ONE dict) while `getKeySlot` returns buckets up to 16383,
and `kvstoreGetDict` is `return kvs->dicts[didx];` with no bounds check. `node_dbs` is protected;
`server.db` (the decoy, which `selectDb()` hands every client as `c->db`) is NOT — `emptyData`
passes the caller's `async` through for it. Whether any path then indexes the decoy by bucket is
what `verify-flushasync` was asked to settle. If reachable, `FLUSHALL ASYNC` corrupts memory.

Related: [[thredis-prefetch-truth]], [[thredis-codex-first-delegation]],
[[thredis-verify-before-implementing]].
