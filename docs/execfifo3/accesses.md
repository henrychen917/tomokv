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

The added ordinary-path accesses are compiler generated. Counts below are per
batch of 32, FIFO minus PRE; POST minus PRE is zero. These are **explicit x86
memory operands**, excluding implicit call/return and push/pop stack accesses.

| Path | Added loads | Added stores | Lines and other writers |
| --- | ---: | ---: | --- |
| Fused SET, read-local 0 or 1 | 160 stack + 64 TLS | 480 stack | One additional traced stack line; stack is private to this thread. TLS loads address `FS+0x28`, the stack-canary word on the first TLS line; initialized by the runtime, never written by EXEC bookkeeping. |
| Fused INCR / GET | 160 stack + 64 TLS | 384 stack | Same private stack/TLS explanation; no extra Shard/owner/Client access. |
| Multi-database split parser, GET/SET/INCR | 1 stack + 1 Client header | 1 stack | No additional unique object line. The Client load is in the existing first 64-byte header (`nothing_to_write`, `fill_` at +40); the connection's IO writes this header during parsing, sending and retirement. FIFO bookkeeping adds no store there. |
| Owner SET/INCR, including armed read-local replacement | 0 | 0 | Existing Shard+8 read short-circuits; no queue/counter access. |

The TLS attribution is dynamic, not inferred from an unclassified address:
`memory-sites/fifo-extra-loads.json` records exactly 64 additional reads of
`ThreadTLS+0`, and the batch-1 site trace records the `fs:[0x28]` prologue and
epilogue loads. Input-buffer accesses are unchanged. POST's explicit operand
counts, classified object accesses and TLS accesses return exactly to PRE.
The raw per-object counts and stack footprint are in `memory/*.json`.
