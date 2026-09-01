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

## Three coarse batch streams

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

The permanent `coarse` arm retains that shipped implementation unchanged. `streams0` is the new
buffered scheduling control: it uses explicit loop-local IFID B, EX A, and WB C contexts and the
same queue reservations and post-execution lane retirement as the interleaved experiment, but does
not overlap their micro-stages. Its compile-time schedule is:

`N0 / I0 / N1 / I1 / I2 / E0 / E1 / E2 / W0 / W1 / W2 / N2`

Thus the three contiguous stream groups are `IFID -> EX -> WB`, empty contexts cost only their
stage guards, and a self-owned command still crosses `task_in_[self]` at I2 before the later E0
gather. EX pops with an unretired frontier and publishes one merged retirement update per source
lane only after E2. Snapshot and ordered/cold executor debt use the established monolithic pass.
The single N2 boundary submits receive rearms, task/completion notifications, and reply sends.
Executor control runs outside the declared N0..N2 rotation. If it leaves ordinary snapshot or
ordered debt while task consumption is permitted, E0 gathers with an unretired frontier, durably
appends that batch to the monolithic deque, and only then publishes its one retirement update per
source lane. A snapshot/LB hard task fence instead leaves fresh work in the bounded lanes. The
mask-independent pre-park audit uses the same unretired E0/E1/E2 path, so `streams0` never falls
through to the grandfathered coarse executor drain.

There are two forced touches outside the fused loop and schedule/config plumbing. One spare bit in
`Client::parse_backpressure_` records that B owns a decoded, unpublished Op. It blocks compaction,
growth, migration, and release until I2 publishes the ROB and reserved task, advances the parse
cursor, and clears the bit; it does not change the 1984-byte Client layout. `ExLoop::fused_sweep`
also accepts a no-fresh-task mode so the pre-park audit can leave Task consumption to the buffered
schedules' unretired E0/E1/E2 path. Its default preserves every pre-existing caller.

`streams0` uses the named compile-time caps `kGenthreadIfidBatchOps=128`,
`kGenthreadExBatchOps=128`, and `kGenthreadWbBatchConns=64`, with one B context, one active A
context (the allocated D context is unused in this control), and one C context.
`kGenthreadStreams0Schedule` is declared beside those caps and context counts in
`genthread_pipeline.h`. `streams0` is boot-only and requires the uring network engine.

## Static `streams` microstage arm

`streams` uses the same three independent B/A/C handoffs as `streams0`, but advances them in the
owner-approved static modulo order:

`N0 / I0 / N1 / E0 / W0 / I1 / E1 / W1 / I2 / E2 / W2 / N2`

The sections are literal sections of the one `IoLoop::run_loop` body. The contexts remain hoisted
loop locals: one IFID B, exactly two EX contexts A/D, and one WB C. They use the named caps
`kGenthreadIfidBatchOps=128`, `kGenthreadExBatchOps=128`, and
`kGenthreadWbBatchConns=64`; `kGenthreadStreamsSchedule` records the literal order beside those
constants in `genthread_pipeline.h`.

- I0 prepares at most one decoded, unpublished point command per ready connection and leaves its
  parse cursor unchanged. The prepared bit pins the read buffer; N1 can only append into it.
- E0 gathers with `pop_unretired` and prefetches Op state. W0 then gathers completion-ready clients
  and prefetches their ROB heads. I1 hashes/routes B and reserves destination-lane credits.
- E1 resolves the Op, verifies current shard ownership, and only then prefetches the FlatStore.
  W1 stages complete reply frames and I2 performs `ROB publish -> reserved Task publish -> parse
  cursor advance`, followed by one notification per destination. Neither W1 nor I2 mutates an
  owned FlatStore, so the E1-to-E2 purity gap is intact.
- E2 calls the shipped owner-gated `exec_batch_prefetched` path. Only after every gathered task is
  Executed, Forwarded, or DeferredDurably does it publish one merged retired-frontier update per
  source lane. W2 builds send SQEs; N2 is the sole network submission boundary.

The four engineered latency windows are E0-to-E1 (W0+I1), E1-to-E2 (W1+I2), W0-to-W1 (I1+E1),
and I1-to-I2 (E1+W1). If IFID encounters a cold/contextual frame, B's unpublished point ops are
discarded without moving their parse cursors and that input is retried through the established
monolithic IFID path. Scatter, scripts, scans, blocking commands, and retrying atomics therefore do
not enter I1/I2. Snapshot or ordered executor debt is handled outside the declared rotation; E0
durably transfers freshly gathered tasks to the established monolithic deque before the E2
retirement boundary only while task consumption remains permitted. Snapshot/LB hard-stop states
leave fresh work in the bounded SPSC lanes and preserve their backpressure and safe-point fence.

The EX-heavy fallback uses the second EX context and exactly
`E1(A) E0(D) E1(D) E2(A) E2(D)`. The merged A/D batch still performs one retired-frontier update
per source lane. Local point commands have no bypass: I2 publishes them to `task_in_[self]` and a
later E0/E1/E2 consumes them like remote work. Like `streams0`, `streams` is boot-only and requires
the uring network engine.

## `streams` depth gate and residual carry

`streams` has its own compile-time gate; it does not reuse or modify the retained
`pipelined-fused` gate. It starts closed. A closed rotation runs the complete buffered `streams0`
order and records the maximum actual IFID-op, EX-task, or WB-client batch occupancy. A sample of at
least `kGenthreadStreamsMinBatchOccupancy=8` opens the next modulo rotation; a lower sample keeps the
next rotation coarse. The same actual counts close an open gate. The decision is therefore made
before N0 without a thread-wide preflight, and thin non-empty work remains proportional to its
payload through the ready lists and bounded queue gathers.

Only B before I1 and A before E1 may cross N2 to the next N0. A non-empty B or A below the
occupancy threshold may accumulate for at most
`kGenthreadStreamsResidualAgeCapRotations=1`; appending new work does not reset the oldest
residual's age, so its second visit must publish, execute, or durably defer it. A carried B owns no
destination reservations, retains at most one prepared-unpublished Op per connection, and keeps
the connection's read buffer pinned plus the teardown/migration safety view live. Its prepared bit
also prevents the ROB-quiescence barrier backstop from treating that unpublished work as fully
idle. A placement transition rolls B back rather than carry hidden work across its safe point.

A carried A keeps its gathered source-lane prefixes unretired. Its next E0 appends only up to
`kGenthreadExBatchOps=128` and reissues the Op-line prefetch for the entire combined batch before
E1. If snapshot/control state makes the pipeline ineligible, A transfers to the ordered monolithic
deque before one merged `retire_n` per source lane. A residual is settled before any correctness
sweep, park, placement safe point, or loop exit; no batch is ever carried after I1 reservations or
after E1 has touched an owned FlatStore.

WB has no residual state. Every C gathered at W0 reaches W1 and W2 in the same rotation, and N2
submits a staged SEND immediately. Thus reply transmission is never delayed to manufacture batch
depth. The gate and age cap live beside all batch caps, context counts, and the static schedules in
the single commented block in `genthread_pipeline.h`.

## Schedule selector and legacy pipelined-fused arm

`--genthread-schedule coarse|pipelined-fused|iofused|streams0|streams` is boot-latched and reported
through `CONFIG GET`.
`coarse` is the default and permanent control arm. Selecting `pipelined-fused` does not remove that
control: every pass below `kGenthreadPipelineMinOccupancy` runs the complete coarse
`IFID -> EX -> WB` rotation. The gate is decided before N0 from the preceding pass's actual batch
occupancy. A closed gate uses ordinary completion-time progress and the complete coarse rotation;
it does not scan the active set or read ahead every EX lane to rediscover that the pass is thin.
The coarse batch's existing IFID/EX/WB counts are the next occupancy sample. A thin non-empty pass
therefore does work proportional to its payload and executes no pipelined stage preflight.

The deep-pass schedule is the owner-approved static order:

`N0 / I0 / N1 / E0 / W0 / I1 / E1 / W1 / I2 / E2 / W2 / N2`

- `N0` reaps network events and commits recv/send progress. In the pipelined arm it neither parses
  nor constructs a follow-up send.
- `I0` parses and decodes one thread-wide batch across all ready connections, taking multiple
  complete frames per connection until the batch or that connection's ROB window is capped. The
  owner-local parse cut advances speculatively so later frames are visible inside the same stage;
  the corresponding ROB suffix remains unpublished. Only GET, SET, single-key DEL, INCR, and DECR
  qualify. A failed I1 reservation or a cold/contextual command rolls the parse cuts back in reverse
  order before the coarse path retries them. Protocol errors, ACL/auth, transactions, subscriber
  mode, scatter, scripts, scans, blocking commands, and retrying atomics cannot publish through an
  unpublished suffix.
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
- `I2` walks each connection's prepared suffix in order and performs `ROB publish -> reserved task
  publish`; the speculative parse cursor becomes committed at that point. It then publishes one
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
retired-frontier update per lane after both E2 sections. There is no triple buffering. For this
retained legacy arm, every local context is empty at the pass boundary; cold safety pointers exist
only so teardown/migration can recognize a Client referenced during the current loop body.

Local point commands use the same self-producer SPSC lane as remote commands: I2 publishes them to
`task_in_[self]`, and a later E0/E1/E2 executes them. IFID never executes shard work inline. The
existing coarse executor's prefetch loop also performs the owner check before its first FlatStore
touch, so the formal E1 ordering applies to buffered and shipped coarse schedules alike.

All caps, the two-context rule, both occupancy thresholds, the `streams` residual-age cap, and the
exact static schedules live together in `genthread_pipeline.h`. The bake-off axes therefore remain
named compile-time constants; the sole runtime surface selects the control or experimental
schedule.

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
