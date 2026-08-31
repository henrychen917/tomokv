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

## Inline versus inbox dispatch

Parsing computes the shard and reads the same bucket-owner array used by the split build.

- If the owner is the client-owning thread, the IO loop publishes the operation in the existing ROB
  and invokes the existing executor batch path inline. The executor's self-notification is
  suppressed and the completed client is put directly on that IO loop's serve queue. There is no
  task-queue post or wake for this case.
- If the owner is another generalized thread, dispatch uses the existing SPSC task channel and wake
  protocol. The owner consumes it during an executor pass. Completion returns through the existing
  ready-mask/reply path to the client-owning thread, which retires the ROB and sends the reply.

The same rule is applied to initial per-owner work for blocking commands, cross-shard scatter, and
`MULTI`/`EXEC`: remote fragments are posted first, then a self-owned fragment may run inline. Their
existing barriers are installed before inline execution, and the existing continuation,
coordination, and reply paths remain in charge afterward. Snapshot coordination explicitly makes
progress on the writer thread's fused executor pass while it waits, avoiding a self-wakeup
deadlock.

Single ownership is unchanged: only the current bucket owner executes a shard. Locally owned client
operations execute inline in arrival order. Mixed local/remote operations retain the same ROB
publish/retire ordering as the split build; inline completion merely makes that ROB entry ready
immediately.

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
