# Split-IO batch micro-pipeline

## Scope

This lane changes only the internal loop of a pure IO thread. The public architecture remains the
same split: IO owns connections, parsing, ROB production/retirement, and sends; EX exclusively owns
shard execution. A command still travels:

```
connection-owning IO -> destination EX -> connection-owning IO
```

The task and completion transports, their atomics and memory orders, shard ownership, FLIP stages,
and the EX loop are unchanged. The existing build assertions remain the footprint gate:

- `sizeof(Op) == 336`
- `sizeof(Client) == 1984`

No runtime knob, fiber, per-request scheduler/state machine, or new atomic is introduced.

## Independent streams

Each IO thread advances two independent batch streams. They are not two halves of one request
batch: an IFID batch comes from this thread's wire connections, while a WB batch comes from any EX
core that completed operations for those connections.

### IFID

The IFID stream is:

```
RX/CQE -> RESP parse/decode -> hash/route -> ROB/Task preparation
       -> quiet SPSC slot/tail publication -> folded destination notifications
```

CQE/epoll harvesting commits received bytes and marks connections active; it never parses inline.
The batch then visits at most 16 active connections and publishes at most 32 operations from each
connection. `parse_and_dispatch` retains all command-specific barriers and continuation behavior.
Task slots and producer tails are published immediately during parse/hash/route. `IFID.POST` later
folds the notification/wake edge once per touched destination; only that per-destination list is
carried between stages, not per-request state.

The partial-frame rule from `744cd57f5` is unchanged. `ParseResult::Incomplete` still becomes
`NeedInput` only when no cursor progress occurred. Such a connection keeps its partial tail, arms a
receive, and leaves the active set while WB readiness remains independently actionable. The cold
pre-park sweep rotates through enough fixed batches to inspect the complete active set once before
sleeping, so bounding the hot IFID batch cannot strand a re-arm.

### WB

The WB stream is:

```
completion/ready observation -> prefetch -> ordered ROB retirement/reply preparation
                             -> iovec/SQE construction -> submit -> CQE/send reclamation
```

`WB.OBSERVE` drains the existing client channels and ready mask, then detaches at most 16 clients
from `pending_serve_`. Clearing `serve_pending` at detach preserves the old completion race: a new
completion may enqueue another future visit while this batch is in progress. The existing AOF reply
gate is checked before detaching a batch.

`WbEngine::prepare*` is the retirement/reply-staging portion of the former `serve*` call.
`WbEngine::pump*` remains the only constructor of sends and is invoked later by `WB.SUBMIT`. Their
combination uses the same ROB drain, output-limit behavior, TLS variants, iovec builder, SQE builder,
and one-send-per-socket rule as before. ROB slots are still retired strictly from `flush_id` through
the contiguous Done prefix. Send CQEs advance output frontiers and release completed borrows at the
next RX/CQE boundary, exactly as before.

## Prefetch targets

WB prefetching has two passes over the detached batch:

1. Hint the `Op::state` line for every outstanding ROB slot, capped by the 64-slot ROB window.
2. Acquire-load those states in ROB order. For the contiguous Done prefix, hint up to the first
   512 bytes (eight 64-byte lines) of a plain zero-copy borrow whose `zc_shard` identifies store
   ownership.

The acquire in pass 2 is required before reading the non-atomic borrow descriptor written by EX.
Negative `zc_shard` markers are special retirement state, not store payloads, and are not followed.
Prefetch is only a cache hint: it does not read/copy reply bytes, create ownership, extend lifetime,
or alter release-to-shard handling. Reply construction and `sendmsg` continue to borrow the original
store pointer.

## Static schedule and buffering

All geometry and the exact schedule live in `src/core/iopipe_pipeline.h` as commented compile-time
constants. One hot rotation is:

```
WB.OBSERVE(W) -> IFID.RX(I) -> WB.PF(W) -> IFID.PARSE+HASH(I)
              -> WB.RETIRE+PREP(W) -> IFID.POST(I) -> WB.SUBMIT+RECLAIM(W)
```

Every stage returns immediately when its stream buffer is empty. IFID parse/hash supplies useful
independent ALU/control work between WB's remote-state/payload hints and retirement. Quiet task
publication happens during that filler and therefore does not wait for WB; destination doorbells
are folded at `IFID.POST` and submitted with the prepared WB sends at the early fire point.

IFID and WB each own a ping/pong pair and advance their buffer index independently only after a
non-empty batch completes. The buffers contain only bounded arrays of `Client*` plus WB's
batch-local submit permission (needed to preserve output-limit suppression). They add nothing to
`Client`, `Op`, or any cross-thread structure. The full rotation completes before FLIP control runs,
so no hidden staged reference crosses an IO quiesce/role-conversion boundary.

The fixed constants are:

| item | value |
| --- | ---: |
| IFID buffers | 2 |
| IFID clients per batch | 16 |
| IFID operations per client | 32 |
| WB buffers | 2 |
| WB clients per batch | 16 |
| WB ready-state hints per client | 64 |
| borrowed payload hint window | 512 bytes |
| completion backstop cadence | 64 rotations |

## Validation posture

This is a functional experiment, not a performance claim. The operator must measure loopback p1
and p128 and then the NIC cells before considering a merge; the send-path result remains NIC-gated.
The lane's functional acceptance uses port 7844 and cores 48–55 only.
