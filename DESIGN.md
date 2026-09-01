# Generalized-thread experiment

This branch is an ablation build. It removes the IO/executor role split while retaining the store,
parser, reply representation, ROB, task channels, scatter machinery, atomics, and shard ownership
rules. It is not a product lane and this document makes no performance claim.

## Loop structure

Boot creates one generalized thread for every selected CPU. Each physical thread constructs both
an `IoLoop` and an `ExLoop`, owns the network ring used for accepts, receives, sends, and parking,
and owns the executor ring used by existing persistence/control paths. Pipelined task and
completion handoffs originate on the network ring so N2 is their single submission boundary.
Executor control work
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

## Selectable pipelined-fused schedule

`--genthread-schedule coarse|pipelined-fused` is boot-latched and reported through `CONFIG GET`.
`coarse` is the default and permanent control arm. Selecting `pipelined-fused` does not remove that
control: every pass below `kGenthreadPipelineMinOccupancy` runs the complete coarse
`IFID -> EX -> WB` rotation. Occupancy is capped and measured from the ready work of the three
independent streams (buffered IFID clients, inbound EX tasks, and completion/WB readiness), so a
thin non-empty pass does work proportional to its payload instead of traversing empty microstages.

The deep-pass schedule is the owner-approved static order:

`N0 / I0 / N1 / E0 / W0 / I1 / E1 / W1 / I2 / E2 / W2 / N2`

- `N0` reaps network events and commits recv/send progress. In the pipelined arm it neither parses
  nor constructs a follow-up send.
- `I0` parses and decodes one prepared-unpublished simple point command per ready connection into
  IFID batch B. Only GET, SET, single-key DEL, INCR, and DECR qualify. Encountering a cold/special
  shard command discards the unpublished B prefix and runs the coarse pass, so scatter, scripts,
  scans, blocking commands, retrying atomics, and all other commands retain the monolithic path.
- `N1` rearms B's connections append-only. A prepared Op pins its argv slices; buffer compaction
  and growth remain legal only at `ROB quiesced && prepared == 0`.
- `E0` gathers EX batch A with `pop_unretired` and prefetches the referenced Op line. It does not
  advance a source lane's retired frontier.
- `W0` consumes completion channels/ready bits, gathers WB batch C, and prefetches each ROB head.
  Completion discovery is ready-mask driven rather than an active-connection scan.
- `I1` hashes/routes B and reserves actual capacity credits in each destination SPSC producer lane.
  Ordinary publications account for outstanding credits, making I2 failure-free.
- `E1` resolves each Op, verifies the current shard owner, and only then forms/touches a FlatStore
  address for prefetch. A stale task is durably transferred to the executor's stale queue. A special
  task racing the pass preflight, and all younger gathered work behind it, move to the established
  ordered-deferred monolith.
- `W1` retires only the ready ROB prefix and stages complete reply frames. Deferred out-of-band
  frames flush only through the ROB flush frontier produced by that retirement.
- `I2` performs `ROB publish -> reserved task publish -> parse-cursor advance`, then publishes one
  notification per touched destination.
- `E2` executes/completes eligible tasks. Only after every A task is Executed, Forwarded, or
  DeferredDurably does it issue one `retire_n` frontier update per source lane.
- `W2` constructs send SQEs without submitting them. `N2` submits the network ring once, including
  N1 receives, I2 task wakes, E2 completion wakes, and W2 sends. The executor ring remains for real
  persistence/control IO.

The four intended latency gaps are E0->E1 (filled by W0+I1), E1->E2 (W1+I2), W0->W1 (I1+E1), and
I1->I2 (E1+W1). No work between E1 and E2 mutates an owned FlatStore. The source spells these as
sections of the one `IoLoop::run_loop` body; B, A/D, and C are hoisted locals, not member-resident
state machines or eleven context-reloading calls.

V1 has exactly two EX contexts. When EX remains deep and IFID+WB cannot fill the normal gap, the
fallback is `E1(A) E0(D) E1(D) E2(A) E2(D)`. A and D merge their lane counts and still publish one
retired-frontier update per lane after both E2 sections. There is no triple buffering. At the pass
boundary every local context is empty; cold safety pointers exist only so teardown/migration can
recognize a Client referenced during the current loop body.

Local point commands use the same self-producer SPSC lane as remote commands: I2 publishes them to
`task_in_[self]`, and a later E0/E1/E2 executes them. IFID never executes shard work inline. The
existing coarse executor's prefetch loop also performs the owner check before its first FlatStore
touch, so the formal E1 ordering applies to both selectable schedules.

All caps, the two-context rule, the occupancy threshold, and the exact static schedule live together
in `genthread_pipeline.h`. The bake-off axes therefore remain named compile-time constants; the sole
runtime surface selects the control or experimental schedule.

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
