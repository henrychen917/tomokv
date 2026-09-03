# Armed local-read capture-at-prefetch audit

Baseline: `b7fd92c0736618c719f29d0202aea009edc6adcb`.

## Phase 1 finding: execute reloads the slot

The armed point-read batch in `ExLoopT::drain_local_reads()` has separate prefetch and execute
walks, but the prefetch walk does not retain a lookup result.  `FlatStore::read_local_prefetch()`
only snapshots eligible table topology and issues a hardware hint for each table's home slot.  The
later `prepare_local_read()` call invokes `FlatStore::read_local_probe()`, whose open-addressing
walk acquire-loads the slot words at execute time and selects the `KvObj` then.

Consequently, a plain cross-client writer can replace a prefetched slot between those walks.  Such
an immutable-object replacement deliberately does not advance the read-local table generation, so
execute accepts the newer pointer and can stall on an object that the batch did not prefetch.  The
same shape exists inside MGET for its at-most-32-key prefetch window.

This is not an ordering requirement.  Parser-side write-ring and owner-tail conflict checks keep a
connection's own unresolved writes out of the local execution path.  A read racing only another
connection's committed replacement may place its read cut before that replacement and serve the
already-observed immutable object.

## Capture constraints

Capture must perform the complete validated probe at prefetch time, not retain only the home word:
linear probing must still skip tombstones and tag/key mismatches, stop at empty, and search the
current table before the old table.  The capture therefore consists of the observed slot address,
the `KvObj` pointer decoded from that slot (or a miss), and the store publication generation.
Execute may read the captured object directly but must not reload the slot.

The capture is safe only as stack-local state for one `drain_local_reads()` pass.  Both batch walks
run inside the fused pass's rotation boundary; its `ThreadCtx` tick is published only after the pass
returns.  Writers unlink first and defer both displaced objects and retired tables until every
active participant publishes a tick newer than the retirement stamp.  Thus the captured slot/table
and object remain allocated through execute, while the final publication validation still rejects
an open atomic group, table resize/move, bulk clear, or ownership handoff.  Plain object replacement,
DEL, and TTL replacement leave that generation unchanged and may legally be observed on either
side of the read cut.

Every later batch must probe and capture afresh; no capture may be stored in the persistent local
lane or survive a rotation boundary.  Stable misses retain their existing command behavior: GET
demotes to the owner, while MGET emits a nil element.
