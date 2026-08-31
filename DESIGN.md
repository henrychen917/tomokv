# Generalized-thread experiment

This branch is an ablation build. It removes the IO/executor role split while retaining the store,
parser, reply representation, ROB, task channels, scatter machinery, atomics, and shard ownership
rules. It is not a product lane and this document makes no performance claim.

## Loop structure

Boot creates one generalized thread for every selected CPU. Each physical thread constructs both
an `IoLoop` and an `ExLoop`, owns the network ring used for accepts, receives, sends, and parking,
and owns the executor ring used by the existing task and persistence paths. Executor control work
is exposed as a bounded, non-blocking pass; ordinary task consumption is advanced by the static
micro-stage schedule described below. The IO loop includes both sides in its pre-park correctness
sweep, so executor work is serviced without a second OS thread or an executor spin loop. Only the
network loop parks.

The published `ThreadCtx` wake endpoint remains the network ring. That lets remote producers wake a
generalized owner whether the pending work is a client operation or an executor task. Startup still
has separate load and activation barriers: every thread loads its owned shard sections before any
listener becomes reachable, then every fused loop is activated before serving traffic.

All selected thread IDs appear in both dense placement views. The bucket-owner array spreads shards
round-robin over all generalized threads unless `--shard-home` supplies an explicit complete map.
`--place` may select exact CPUs; its legacy `ifid`/`ex` labels do not create roles in this build.

## Uniform inbox dispatch

Parsing computes the shard and reads the same bucket-owner array used by the split build.

Every owner uses the existing per-producer SPSC task channel and notification protocol. This
includes self ownership: a generalized thread publishes the ROB entry, posts the `Task` to
`task_in_[self]` during its IO/parse phase, and consumes it only during its later executor phase.
There is no inline execution bypass. Blocking commands, cross-shard scatter, and `MULTI`/`EXEC`
post their self-owned fragments through the same path as their remote fragments, after the same
all-or-nothing queue-capacity checks.

Remote-owner posting and completion are unchanged. Self completion schedules retirement directly
on the colocated IO loop without a redundant cross-thread wake. The task still crossed the queue,
so its publication, execution, continuation, and ROB ordering have the same shape as split mode.
Snapshot coordination explicitly makes progress on the writer thread's fused executor pass while
it waits, avoiding a self-wakeup deadlock.

Single ownership is unchanged: only the current bucket owner executes a shard. The existing
masked-monolith SPSC mesh remains the only task transport; `task_in_[self]` is the local staging
lane, not a special queue and not an inline fast path.

## Arm 2: three coarse batch streams

Every physical thread advances three independent streams. They are not three phases of one batch:

- IFID batches originate on this thread's connections. CQE/RX processing and buffered-input
  parsing decode commands, hash keys, select shard owners, prepare ROB/Task state, and publish the
  tasks to each destination's producer lane.
- EX batches are gathered from every producer lane targeting shards owned by this thread. The
  established batch first prefetches the batch's FlatStore buckets, then probes/executes the whole
  homogeneous batch and publishes completions.
- WB batches originate from completion notifications for this thread's connections. WB finds the
  retireable ROB prefix, constructs replies/iovecs and send SQEs, submits output, and reclaims the
  retired slots in ROB order.

The exact arm-2 hot rotation is deliberately coarse and static:

`IFID batch -> EX batch -> WB batch -> repeat`

Each call returns immediately when its stream is empty. Network/control maintenance surrounds the
rotation, and the pre-park correctness sweep uses the same IFID/EX/WB order. Local tasks published
by IFID therefore cannot execute until the later EX batch.

The streams are buffered independently by structures they already own: connection read buffers and
the ROB bound IFID, the per-producer SPSC lanes stage EX input, and the completion masks plus
`pending_serve_` stage WB input. The original coarse comparison used EX/IFID batches of 32 and WB
batches of 16. The adaptive loop below retains this exact coarse ordering while making the current
batch caps compile-time sweep points in `genthread_pipeline.h`.

This commit is the coarse comparison arm. It intentionally does not interleave batch micro-stages;
that is the next commit's arm.

## Arm 3: interleaved batch micro-stages

Arm 3 retains the same three independent streams and the same SPSC/ROB ownership edges, but splits
only the batch boundaries that launch or consume a useful memory dependency:

- IFID is triple-buffered across `RX_PARSE`, `HASH`, and `ROUTE_ISSUE`. `RX_PARSE` reaps network
  CQEs, parses and decodes ordinary keyed commands into an owner-local batch, and leaves each
  connection at its unpublished ROB tail. `HASH` hashes the batch in one tight loop.
  `ROUTE_ISSUE` maps hashes to shards/owners, prepares direct-reply and Task metadata, publishes the
  ROB entries, then batch-coalesces publication notifications to the existing producer lanes.
  While an unpublished batch owns an `Op`, RX does not re-arm that Client after parsing: its ROB is
  still formally quiescent, so a receive-buffer grow would otherwise move the argv slices before
  `HASH` consumes them.
  Commands with established special continuations keep those paths; every resulting local shard
  Task still publishes through `task_in_[self]` and never executes in IFID.
- EX is triple-buffered across `INPUT_PF`, `FILL`, `BUCKET_PF`, `OBJECT_PF`, and `EXECUTE`.
  `INPUT_PF` reads ahead the published Task slots and their referenced Op state without changing a
  queue frontier. `FILL` gathers up to the 128-Task cap plus producer-lane IDs. `BUCKET_PF` issues the
  existing FlatStore bucket prefetch loop. `OBJECT_PF` consumes the warmed bucket probe far enough
  to prefetch a tag candidate, without making a logical lookup or mutation. `EXECUTE` runs the
  existing homogeneous execution loop, publishes completions, and only then advances each source
  lane's separate retired frontier. Older retry, atomic, snapshot, and continuation machinery
  remains in the executor control pass.
- WB is triple-buffered across `GATHER`, `PREPARE`, and `SUBMIT`. `GATHER` observes completion
  channels/ready bits, gathers up to the 64-connection cap, and prefetches each ROB head.
  `PREPARE` drains only the ready ROB prefix in order and stages reply/segment state. `SUBMIT`
  constructs and publishes the send operation through the existing plain, kTLS, or userspace-TLS
  pump. Send completion retains its existing byte reclamation and zero-copy release rules.

The three buffer arrays are independent: IFID buffers contain decoded `Op` references, EX buffers
contain copied `Task` values and producer IDs, and WB buffers contain owning `Client` references.
They are owner-local and add no atomics or fields to `Op` or `Client`. Each phase owns a ring index
into its three slots (fill/hash/route, fill/bucket/object/execute, and gather/prepare/submit).
Advancing an index preserves FIFO batch progression without scanning every slot for the oldest
sequence. Consuming a slot changes only its count/state; the arrays are not cleared or shuffled. A
connection held by IFID or WB cannot migrate or be deleted until that owner-local reference is
released; EX queue quiescence continues to use the existing post-execution retired frontier.

The shallow `kGenthreadStaticSchedule` is:

1. `EX.BUCKET_PF`
2. `IFID.HASH`
3. `WB.PREPARE`
4. `EX.OBJECT_PF`
5. `IFID.ROUTE_ISSUE`
6. `EX.INPUT_PF`
7. `WB.SUBMIT`
8. `EX.EXECUTE`
9. `IFID.RX_PARSE`
10. `EX.FILL`
11. `WB.GATHER`

Every entry runs once per shallow loop pass and returns immediately if its required input slot is
empty or its output slot is full. A gather takes all observed input up to its cap in that one
invocation: IFID and EX cap at 128 items and WB at 64 connections. Thus backlog grows the useful
work under one stage entry/exit instead of causing repeated 18-entry rotations of fixed 32/16-item
batches. Input prefetch is likewise bounded by the EX cap rather than performing one hint per lane.
Bucket prefetch remains separated from object probe, object probe from execution, IFID parsing from
hash/publication, and WB head prefetch/preparation from submission by useful work in the other
streams. The pre-park path remains a mask-independent correctness backstop.

## Depth-adaptive schedule

IFID records one natural-depth observation per gathered batch without changing `Op` or `Client`.
In shallow mode it divides the bytes already buffered for the gathered connections by the bytes in
their first decoded frames; in coarse mode it uses operations dispatched per participating
connection. Both estimate the batch that the input would naturally supply if micro-staging did not
stop after the first unpublished op. Only the outer loop-pass boundary consumes these owner-local
observations and changes mode; no operation tests the mode.

The gate averages eight observations. Its high threshold is `EX cap / 8` (16 with the current cap)
and its low threshold is one quarter of that (4), providing hysteresis. At or above the high
threshold, the interleave window becomes zero and the loop degenerates to the coarse
`IFID -> EX -> WB` rotation: stages run back-to-back, executor queue consumption drains naturally,
and no micro-stage or buffer search is paid. At or below the low threshold it restores the
two-buffer shallow prefetch window. A shallow-to-deep transition finishes at most three already
staged batches in cursor order once before entering the coarse steady state.

Batch caps, buffer depths, the two thresholds/window length, the interleave window, stage enum, and
the exact shallow order are compile-time constants in the single `genthread_pipeline.h` block.
There are no runtime knobs, fibers, per-request runnable states, new atomics, or changes to
ownership/ROB semantics.

## Retained and disabled controls

Key and client load balancing remain available, with every generalized thread participating as both
network endpoint and shard owner. Shard migration continues to use the existing ownership transfer
protocol.

The role-conversion controls have no meaning here:

- `--ratio` (and the `ratio` configuration directive) is rejected during parsing with a
  generalized-thread-specific error.
- `FLIP`, including its argument forms, returns an error explaining that it is unavailable in
  generalized-thread mode.
- `INFO SERVER` reports `thread_model:generalized` and the generalized thread count.

The split-loop and flip-controller sources are retained for comparison and to keep unrelated
mechanisms intact, but this executable enters only the dedicated fused startup/loop path. It does
not select split versus fused execution with a per-operation mode branch.
