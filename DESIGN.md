# Generalized-thread experiment

This branch is an ablation build. It removes the IO/executor role split while retaining the store,
parser, reply representation, ROB, task channels, scatter machinery, atomics, and shard ownership
rules. It is not a product lane and this document makes no performance claim.

## Loop structure

Boot creates one generalized thread for every selected CPU. Each physical thread constructs both
an `IoLoop` and an `ExLoop`, owns the network ring used for accepts, receives, sends, and parking,
and owns the executor ring used by the existing task and persistence paths. The executor is exposed
as a bounded, non-blocking pass. The IO loop invokes that pass between its own loop passes and
includes it in its pre-park sweep, so executor work is serviced without a second OS thread or an
executor spin loop. Only the network loop parks.

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
`pending_serve_` stage WB input. EX retains gather/prefetch/execute batches of 32; ordinary IFID
dispatch is capped at 32 operations per connection pass; WB serves up to 16 connections per batch.
All three sizes are named compile-time constants in `genthread_pipeline.h`. There are no runtime
knobs, fibers, per-request schedulers, or new atomics.

This commit is the coarse comparison arm. It intentionally does not interleave batch micro-stages;
that is the next commit's arm.

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
