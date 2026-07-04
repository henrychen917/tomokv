---
name: thredis-s8-two-reply-release-paths
description: THredis has TWO reply-ref release paths; S8 zero-copy forwarding must route both back to the owning worker
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis (the S8 zero-copy reply optimization) forwards a worker shard's DB value
straight into the client reply as a `bulkStrRef` (no copy). The value's refcount is
+1'd on the worker (`networking.c` `_addBulkStrRefToBufferOrList`, ~line 748) and
the matching decref MUST be routed back to the owning worker via the free-back ring
(`freebackPush`) — because the owning worker is the SOLE refcount mutator for its
shard's values (paper §4.8 single-writer-per-key). Any cross-thread `decrRefCount`
on a forwarded value races the worker and corrupts the refcount → premature free →
heap-use-after-free in `dbSetValue` (db.c:681 decref / :688 read) on the next
overwrite of that key.

THE TRAP: there are **two** places that release `str_ref->obj`, not one:
1. `releaseBufReferences` (networking.c ~2267) — the inline `c->buf` path.
2. `processSentDataInEncodedBuffer` (networking.c ~2743) — the reply-LIST writev path.

S8 FORCES worker fakes onto the LIST form (so `listJoin` can splice the fake's reply
into the real client with no copy/double-decref), so path #2 is the one that actually
runs for forwarded values. Both paths need the `if (str_ref->owner_worker >= 0)
freebackPush(...)` branch. Adding it to only one (path #1) left path #2 doing a racy
`ioDeferFreeRobj` → the UAF. Fix: same freeback branch in BOTH.

Also: `server.clients_with_pending_ref_reply[]` is sized `[MY_IO_THREADS_MAX+1]` and
indexed by `iotid`; a worker's iotid is OUT OF RANGE, so the flushdb-protection
tracking (and `clientIsInPendingRefReplyList`, which has a `[iotid]` clause) must be
SKIPPED for worker fakes (gate on `owner_worker < 0` / `if (c->isFake) return 0`).
Fakes don't need it — the +1 ref + free-back ring already keep the value alive.

Validated ASAN-clean via /tmp/s8_validate.sh (big-value GET + overwrite + churn).
See [[thredis-opt-and-testers]], [[thredis-worker-argv-refcount-race]],
[[thredis-iotid-worker-slot-fix]].
