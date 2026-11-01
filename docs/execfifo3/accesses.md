# FIFO field accesses relative to PRE

Offsets are bytes relative to the named object. A heap object need not start
at a cache-line boundary: the physical line is floor((base + offset) / 64).
The scope receipts record object alignment; Shard and owner offsets are unchanged.

| Object / new field | Offset | Access and writer | No transaction state |
| --- | ---: | --- | --- |
| `tomo::TxnKeyQueue::ehead` | 56 | physical shard owner; waiter link/unlink and FIFO gate | not accessed |
| `tomo::TxnKeyQueue::etail` | 64 | physical shard owner; waiter link/unlink and FIFO gate | not accessed |
| `tomo::TxnWaiter::eprev` | 32 | physical shard owner; waiter link/unlink | not accessed |
| `tomo::TxnWaiter::enext` | 40 | physical shard owner; waiter link/unlink | not accessed |
| `tomo::TxnRetryQueues::ready_head` | 40 | owner loop; C1 promotion/drain | not accessed |
| `tomo::TxnRetryQueues::ready_tail` | 48 | owner loop; C1 promotion/drain | not accessed |
| `tomo::TxnRetryQueues::markless_count` | 56 | owner loop; C1 promotion/drain | not accessed |
| `tomo::TxnRetryQueues::chaining` | 60 | owner loop; C1 promotion/drain | not accessed |
| `tomo::MultiOwnerRetryNode::markless` | 57 | owner named by lane; C1 link/unlink/promotion | not accessed |
| `tomo::MultiOwnerRetryNode::ready_prev` | 64 | owner named by lane; C1 link/unlink/promotion | not accessed |
| `tomo::MultiOwnerRetryNode::ready_next` | 72 | owner named by lane; C1 link/unlink/promotion | not accessed |
| `tomo::MultiOwnerRetryNode::runnable` | 80 | owner named by lane; C1 link/unlink/promotion | not accessed |

`Shard::reserved_route_[0]` is newly used at +9, beside the existing
`has_watches_` byte at +8 and owner clock at +16 (all header line 0 for
a 64-byte-aligned shard). It is touched only by boundary paths.
`TxnOwnerCounters::values[20..22]` occupy +160, +168, +176 within the
existing 192-byte owner slot; no subsequent Server offset changes.

The plain-writer final gate retains the existing Op hazard bit after a refusal.
The newly used FIFO counters and queue fields are unreachable with
`has_watches_ == false`. On a watched shard, a missing key queue returns
before loading ehead. On an existing key queue the FIFO gate reads ehead,
then the immutable unit age and existing shared liveness words if non-null.
The shared decision/abort/refcount words are written by the transaction’s
participating threads; the queue links themselves have one owner writer.

Additional parser accesses are thread-private stack traffic caused by lost
inlining, plus an existing Client load in the multi-database split parser.
No other thread writes the parser stack. Full per-object line/access deltas,
explicit stack reads/writes, and stack footprint counts are in `memory/*.json`.
