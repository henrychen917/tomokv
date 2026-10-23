# trackfix2 causal invalidations

Size impact, before implementation: no field is added to Op (336), Client
(1984), ThreadCtx, Shard, FlatStore, Rob, AtomicEntry, or Config. An armed
remembering read owns a CommandSpec copy and observation vector in tracking's
connection side state; the registry CommandSpec remains 48 bytes. ClimonConn's
completed-enrollment watermark map adds 56 bytes (184 -> 240). Each pending-key
value becomes a vector of readers plus two 64-bit notification watermarks
(8 -> 40 bytes). NotifyBatch gains one 64-bit completion stamp. NotifyOut gains
one 64-bit stamp. PubSubEventItem::count, previously unused for tracking,
transports it without growing transport structures. Compiled sizes: TrackingRead 152 bytes plus 8 bytes per shard and 4 bytes per
key (besides the existing strings); NotifyBatch 416 -> 424; NotifyOut 40 -> 48;
PubSubEventItem stays 48. DWARF receipts are in trackfix2/sizes.json. No per-read,
pending-key or enrollment node is allocated with tracking disarmed. The shared
ClimonConn/NotifyBatch/NotifyOut footprint increases also apply when another
feature allocates those objects (MONITOR or keyspace notifications); empty
tracking maps do not allocate nodes, and zero stamp fields remain inactive.
The tracking clock is neither sampled nor incremented on those paths.

## Certificate and publication

A process-wide 64-bit, non-resetting tracking clock orders *completed*
mutations. It is touched only by tracking reads and records carrying the
tracking route. A command's batch receives a release ticket after its owner
execution, including plain atomic publication, has completed. Scatter/EXEC
batches that complete elsewhere are sealed after all fragments join, before
retirement transports them. The stamp is deliberately a completion certificate,
not an early notification fire-point timestamp: erase and expiry observers can
fire before removal and speculative records can precede atomic commit. Keyless
records are sealed on their first owner drain, after the mutation stack returns.
A batch's multiple notifications for one key coalesce to one stamped change.
The global certificate needs no per-owner state migration or ownership lock.

## Read observation

Only a subscribed remembering read receives a side-owned CommandSpec copy.
Its ordinary flags, handler and id are preserved; an otherwise unused armed
handler pointer identifies the side object. An armed executor hook samples
the clock before the actual owner read; notification scopes cover special and
blocking fragments. Command notification wrappers retain their original bodies. Each shard has its own observation
slot, written only by its owner; fragments never contend on an atomic min loop.
Read-local capture samples before capturing any record and uses the same side
object. No record retries, seqlocks, write locks, or mutable value changes are
introduced. OFF/RESET cancel obligations but retain live side objects and the local drain
arming until every older read retires. Re-enabling tracking reuses that arming.
Queued MULTI reads keep the registry spec because the queue outlives the ROB
slot; their pre-existing conservative registration uses a zero certificate.
The side object stays alive through Done and in-order retirement;
consumer code does not read executor-owned observation slots before Done.

Snapshot reads cannot certify a world newer than their pinned MVCC cut. The
observer loads the clock before the current atomic epoch. If the read cut is
older than that epoch, it uses the dispatch certificate only when the cut
includes the epoch sampled after that dispatch certificate; otherwise it uses
zero. This covers a commit between the pass-wide read-cut sample and the later
per-read registration. Local reads, which capture the latest validated immutable
records, use their capture observation. Unobserved/error paths use zero. A delayed
write with certificate <= the read's observation is older and needs no frame
for that read; a newer certificate invalidates it. A commit not yet certified
when a read starts is conservatively concurrent. This can produce a conservative
invalidation, but cannot suppress a required one. The same comparison applies
to completed enrollments, so a delayed old event cannot erase a newer cache.

## Pending obligations and retirement

The pending-key table retains *all* pending reads, a maximum invalidating write
stamp, and a maximum already-delivered stamp. Incoming events retire old
completed enrollments, deliver at most one frame per client/key/change, and
record pending obligations. Pending reads are decided only at retirement, when
their actual observation is available. A read older than the invalidating
stamp never re-enrolls. If that change already emitted a frame for a completed
or sibling pending read, retirement emits none. A read that observed the change
may enroll normally. NOLOOP suppresses delivery, not invalidation accounting.
BCAST remains subscription based and observes every matching change.

## Ownership and modes

The read object and pending/completed tables move with ClimonConn in the
existing client ownership commit section. The op's spec points at a separately
allocated stable object, so moving the map cannot invalidate it. The global
clock is independent of shard and IO placement. Stamped transport copies and
stale-route forwarding preserve the certificate. Shard migration already drains
execution before moving ownership; no new per-owner state is introduced.
FLIP therefore preserves both pending obligations and completed watermarks.
Atomic 0 uses execution observations; atomic 1 additionally respects the pinned
snapshot bound. Both fused and split owner execution use the armed context;
read-local capture is explicitly covered before prefetch capture.

FLUSH conservatively invalidates every pending read as well as completed
subscriptions; the filter is not cleared while pending/new readers exist.
No ordering comparison may discard an event without a completed-publication
certificate and an observation at least as new. Unknown certificates remain
invalidating. Existing allocation-failure notification loss is not converted
into a causal proof; any such pre-existing path found is reported explicitly.

## Directed proof

Retain the 128 older-write windows and BCAST controls. Add windows holding a
read Done before retirement while a genuinely later SET notification arrives;
assert exactly one frame, no stale re-enrollment on a second write, and renewed
invalidation after a fresh read. Repeat with multiple pending reads of one key.
Run every protocol/option, engine, thread, atomic and read-local combination.
Missing held/replayed receipts fail. PRE must fail the old-write witness and the
retirement non-loss control; a disposable suppress-all arm must fail non-loss.
Production has no scheduling hooks. Full differential, whole selected gate
jobs, production-unit freshness, linked identity and labelled PAD-A receipts
are appended to the merit request, with no performance claim.

## Explicit non-loss boundary

The causal comparison never discards an invalidation for an older/unknown
observation, and invalidated pending reads never re-enroll. This does not fix
pre-existing resource-failure loss in notification recording: failure to
allocate NotifyBatch/owned keys/spill returns after incrementing the drop
counter; the keyless queue's 4096 cap also drops records; the retirement catch
can count a drop after allocation failure. These paths are in notify.inc and
are outside the ordering fix. A claim of losslessness under arbitrary OOM or
keyless-queue exhaustion would be false. The directed controls verify non-loss
under the scheduled causal windows, not allocation-failure delivery.

The completion certificate is conservative: an already-published write that
has not yet reached its completion hook, or a pinned snapshot with no suitable
certificate, can still cause an unnecessary invalidation. It cannot be dropped
as an "older" write without the visibility proof. This limitation is distinct
from the fixed delayed-transport duplicate and stale re-enrollment bugs.

## Separate baseline REDIRECT-close defect

The final broader validation exposed a pre-existing closure race: POST fails
one of five isolated tracking batteries and PRE fails three of five, each on
the same missing `broken_redirect` flag. A disposable trace shows that the
causal path correctly retires enrollment 45 on write certificate 46 and calls
`tracking_deliver_frame`. The directory lookup still finds the remote redirect
target, but `TrackingDeliver` later sees it gone and exits without notifying
the tracking source. The flag only gets set when the source's initial directory
lookup fails. This unchanged baseline delivery path is outside the ordering
comparison; the lane does not claim to fix it or label that battery uniformly
green. Trace scripts, binary-patch-free debug copies and raw receipts are under
`trackfix2/tracking-battery-recheck*` and `redirect_trace_build.py`.
