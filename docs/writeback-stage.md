# Boot-selectable write-back stage

One binary supports two request/reply pipelines. The immutable `tomokv-thread-wb` value chooses the
pipeline before threads or client-side state are allocated:

| Value | Pipeline | Reply/send owner |
| --- | --- | --- |
| `0` (default) | `IO -> EX -> IO` | The connection's IO thread |
| positive `N` | `IO -> EX -> WB` | One sticky WB thread per connection |
| `-1` | `IO -> EX -> WB` | WB count is the physical-core-budget remainder |

`N` is per topology node, like `tomokv-thread-io` and `tomokv-thread-ex`; the runtime totals are the
per-node values multiplied by `tomokv-nodes`.

The zero value is an architectural boundary, not a dormant third stage. It retains the established
two-stage parser, pending-client walk, adaptive completion polling, reply splice, socket writer, and
IO/EX controller. WB event loops, ready words, slot pages, return pools, input counters, uring state,
and static-WB pin matrices are not allocated. New WB configuration scalars occupy an existing
alignment gap in `redisServer`, and the client tail overlays its legacy pending-EX list node with the
WB pointer because the two owners cannot coexist. This keeps the existing structure sizes and
two-stage field offsets unchanged.

## Three-stage ownership

With WB enabled, the roles are deliberately asymmetric:

1. IO owns accept, receive, protocol parsing, command identification, and EX dispatch.
2. EX owns shard-local command execution and builds the command reply once on its fake client.
3. The sticky WB consumes EX completion, advances post-EX cross-shard stages, gathers the ordered
   reply prefix, and owns every socket write for that connection.

Trivial traffic can still execute inline on IO, including PING, protocol/admission errors, and
unauthenticated replies. Its completed output is handed to the sticky WB. IO does not inspect or
mutate WB-owned pending-send state, install a writable handler, or send a dispatched reply. That
single-writer rule also applies while a connection moves between IO owners: receive ownership can
move, but its WB assignment remains stable and node-local.

## Head-ready bitmap and fenced publication

Each accepted connection receives a stable slot on its WB. A WB owns compact 64-bit ready words,
one bit per slot. The bit means that the connection's current ordered pipeline head needs WB
inspection. There is no intrusive ready queue and no four-state client scheduler.

EX release-publishes a fake's CDB completion byte, executes a sequentially consistent fence, and
then reads the connection's `flushid`. It relaxed-ORs the ready bit only when the completed slot is
the ordered head. A deeper out-of-order completion sets no bit. After WB advances `flushid`, it
executes the matching sequentially consistent fence before acquire-checking the new head's CDB byte.

Those two StoreLoad fences are the validated conditional protocol. They close the only lost-ready
interleaving: EX cannot both miss that its completion became the head while WB misses that the new
head had already completed. Replacing this with an unconditional ready-bit publication was measured
and rejected; the conditional, fenced set-if-head protocol is intentional.

Depth-one completions signal immediately. Under backlog, only a completion that becomes the ordered
head performs the bitmap RMW. A per-WB `wake_pending` exchange creates one eventfd edge for an
empty-to-ready episode and coalesces later producers while the WB is awake or draining. The consumer
rotates its initial ready-word index, clears a bit only while holding a drain reference, and always
performs the fence/new-head recheck before parking.

## Ordered sends and wb-uring

The default WB sender gathers a small ready prefix into the real client's contiguous buffer and
uses one write. Larger or reference-bearing prefixes retain the existing splice/writev machinery.
Worker-owned value references return through the WB producer lane to the owning EX worker; they are
never decremented by WB.

`tomokv-wb-uring` independently controls a per-WB SENDMSG ring:

- `0` creates no WB sender ring and uses write/writev;
- positive `N` caps cross-connection SENDMSG SQEs per submit;
- `-1` derives a 32..512 cap from configured clients per WB.

There is at most one send in flight per connection. Its pin owns the client buffers and referenced
objects until the CQE consumes the sent prefix. A partial completion immediately chains the
remainder; EAGAIN parks on that WB's writable event. The CQE resumes the same fenced client drain,
so a later reply cannot overtake the partial send. Ring setup, SENDMSG probing, or unsupported CQEs
fall back per WB to write/writev instead of making the server unavailable.

AE_READABLE and receive-side io_uring remain IO-owned. AE_WRITABLE and the sender ring are WB-owned.
TLS is rejected only when WB is enabled because split read/write owners cannot safely mutate one TLS
session concurrently; `tomokv-thread-wb 0` retains the existing TLS behavior.

## Post-EX cross-shard coordination

EX remains responsible only for shard-local work. The last sub-fake release-publishes one common
group-completion marker. In three-stage mode the sticky WB alone consumes that marker and performs
the next action: gather/reassemble, launch a pipeline or two-hop continuation through its dedicated
producer lane, advance MSETNX reservations, or publish an atomic commit after every install is
ready. Parsed-command and sub-fake return objects are then posted to their origin IO pool.

The two-stage boot keeps its original last-EX election and IO-side gather/retirement helpers. Shared
atomic publication records are detached before commit in both modes and retired only after the
matching commit sequence is visible, so neither mode can leave a stale record behind a freed group.

## Client and slot lifetime

Client construction assigns WB by connection node and client identity. Per-client slot metadata
pages grow only on accept, never from completion producers or the ready scanner. Disconnect follows
a quiescent recycle protocol:

1. WB-originated close is posted to the connection IO mailbox.
2. IO disables receive ownership and waits for fake-ring, action-mailbox, writable-registration,
   ready-bit, drain-reference, and SENDMSG pins to clear.
3. The WB slot pointer is removed, then the stable slot is recycled under the cold accept/disconnect
   lock.

This prevents a late CQE, bitmap scan, or EX completion from observing a new client through a reused
slot.

## Sizing and pinning

In WB mode, IO and EX are explicit positive per-node counts. WB sizing is layered on top:

- `tomokv-thread-wb 0` runs the unchanged two-role resolver. With a zero core budget, the budget is
  `io + ex`.
- Positive WB with a zero core budget sets the budget to `io + ex + wb`.
- `tomokv-thread-wb -1` subtracts explicit IO and EX from `tomokv-cores-per-node`. If that budget is
  also zero, boot counts CPUs allowed by affinity/cgroups, deduplicates SMT siblings into physical
  cores, divides the result across topology nodes, and assigns the remainder to WB.

For example, `nodes=8`, `cores-per-node=8`, `thread-io=2`, `thread-ex=3`, and `thread-wb=3`
resolves global totals of IO 16, EX 24, and WB 24.

Every enabled role must be positive and fit both the per-node core budget and its compiled global
capacity. IO/growth/WB producer identities share the bounded producer-lane namespace, so an
otherwise-valid role sum that exceeds that namespace is rejected at boot.

`ccd` and `numa` placement put WB after the node's EX and IO logical ranges. Static placement needs
`tomokv-pin-io` and `tomokv-pin-ex` in two-stage mode, and additionally requires complete
`tomokv-pin-wb` coverage when WB is enabled. The WB static-pin matrix itself is allocated only in
that enabled/static combination.

## Flip boundary and known follow-up

The flip controller remains a two-role IO/EX controller. With WB enabled it may still move the
boundary inside the provisioned IO/EX pool, but WB count, placement, event loops, queues, client
assignments, and producer lanes remain static. No thread can adopt a WB role through a polymorphic
checkpoint.

A future three-role controller is a known follow-up. This release intentionally does not invent one:
the validated behavior is a static WB pool beside the existing independently validated IO/EX
controller.

## Observability and permanent gates

`INFO` exposes WB busy/idle time, counted threads, ready drains and re-arms, replies, gather paths,
wake edges/suppression, and wb-uring setup/submission/completion/fallback counters. At
`tomokv-thread-wb 0`, these fields are zero and WB-only input batching fields are absent.

`tools/notifyguard.sh` protects the fenced protocol, bitmap scheduler, sole send owner, slot
quiescence, no-allocation split, dual cross-shard owners, and static-WB flip boundary. The knob
matrix exercises WB off, explicit, AUTO, range failures, static pinning, and all wb-uring modes.
`tools/preflight/wb0_parity.sh` is the permanent B,C,C,B canonical p16 GET gate against the retained
`219ec74cc` artifact; it compares throughput, the INFO key surface, and idle/load RSS.
