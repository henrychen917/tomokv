# Cross-shard multi-key commands

This phase adds scatter/gather execution and the Redis command surface.  It deliberately does **not**
make a multi-key command atomic across shards.  Every `FlatStore` remains lock-free in the literal
sense: only its shard owner touches it, and there are no store atomics or mutexes.  A concurrent
client may observe part of `MSET`, `DEL`, a move, or a STORE operation while other owner tasks are
still running.  Epoch MVCC is a later phase.

## Layout and lifetime

The IO thread parses one client-visible `Op`, computes every key hash, and coalesces argv indices in
a heap `ScatterState::groups[shard]`.  There is exactly one `Task` for each touched shard, regardless
of how many request keys that shard owns.  Before publishing the `Op`, IO counts tasks by target
worker and checks the complete capacity requirement for every producer-to-worker SPSC queue.  It
then publishes the one ROB entry followed by all owner tasks.  `sizeof(Op) == 336` and
`sizeof(Client) == 1984` are unchanged; all variable multi-key data lives in `ScatterState`.

MGET has request-indexed heap result slots.  Each owner writes only slots for its group's argv
indices, and values are copied out of `FlatStore`.  The last completing owner acquires all group
writes through the completion counter and serializes one RESP array in request order.  The borrowed
GET-value protocol therefore remains exclusive to single-shard `GET`.

`KEYS` sends one task to every shard.  Owners walk only their own stores with the bounded scan API
(256 physical slots per executor pass), copy matching names into group-owned chunks, and resume the
same task from an executor-local retry deque.  No IO thread inspects a `FlatStore`.

## Execution shapes

Single-phase fan-out is used by MGET, MSET, multi-key DEL/UNLINK/EXISTS/TOUCH, and KEYS.  These do
not install a connection parse barrier.  MSET and deletion tasks may finish at different times, so
their partial visibility is part of the stated non-atomic contract.

MSETNX, RENAME, RENAMENX, COPY, SMOVE, LMOVE, RPOPLPUSH, SINTER/SUNION/SDIFF/SINTERCARD, and the
three SET STORE variants use two hops and install `Client::scatter_barrier`.  Hop 1 validates or
gathers logical value images.  The last hop-1 owner computes the decision/result, constructs a
coalesced apply layout, and performs a complete hop-2 queue-capacity preflight before publishing any
hop-2 task.  Refusal returns a clean error reply.  The barrier is cleared only when the ROB becomes
quiescent, so a later command on that connection cannot race the apply hop.

The important non-atomic windows are explicit:

- MSETNX checks all keys in hop 1 and writes in hop 2.  Another client can create/delete a key in
  between, and individual writes become visible as their owners apply them.
- RENAME/COPY and SMOVE/LMOVE gather logical source/destination images, then replace/delete the
  affected keys on their owners.  Cross-shard source and destination tasks can be observed in either
  completion order; an admission failure can leave an already-applied counterpart visible.
- Set operations gather member snapshots before computing.  Plain variants return that gathered
  view.  STORE variants subsequently replace the destination (of any old type) in hop 2, so source
  changes between gather and store are intentionally not retried.

Sequential single-connection behavior remains Redis-compatible.  For single-phase operations, IO
publishes each connection's tasks in parse order to every touched shard's SPSC input.  A later
single-key or scatter task for key K therefore sits behind the earlier fan-out group on K's owner.
That per-owner FIFO property supplies read-your-own-writes without a global barrier.  Two-hop
commands use the stronger parse barrier described above.

## Snapshot interaction and MVCC seam

Scatter writes present every mutation key to `FlatStore::snapshot_prepare_write` before any key in
that owner task is mutated.  The group remembers its per-key gate cursor across `Pending`, so
incremental pre-image serialization applies backpressure without repeating already-ready keys.
Validate/gather and apply are distinct phases.  `ScatterState::epoch` is a reserved `uint64_t`, with
no behavior in this phase, and is the intended future epoch-MVCC attachment point for versioned
validation, read sets, and retries.

Audit finding: the old FLUSHALL/FLUSHDB task was **not capture-safe**.  `FlatStore::clear()` freed the
frozen table while the capture walker still held its table/cursor state.  During capture, FLUSH now
prepares every key's pre-image and performs logical erases instead; this preserves the frozen table
geometry until snapshot handoff completes.  Outside capture it retains the proportional `clear()`
fast path.  Bounded scan also leaves expired frozen entries physically present for the capture
walker while reporting them logically absent to KEYS.

## Measurements for the owner

No benchmark was run in this implementation pass.  The useful follow-up cells are MGET-8 and
MSET-8 versus eight pipelined single-key commands, with keys spread across many shards, plus the
latency/throughput cost of the parse barrier for RENAME, MSETNX, LMOVE, and a representative set
STORE command.  Report task count per command as well as throughput so the expected one-task-per-
touched-shard coalescing is visible.
