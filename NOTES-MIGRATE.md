# Runtime ownership migration

This document is the design contract for runtime bucket, client, and thread-role
migration.  It was written before the implementation.  The central rule is:

> At every instant a bucket has exactly one executor (EX) owner and a connection
> has exactly one I/O (IO) owner.

Registration, queue membership, and readiness are not ownership.  A resource can
temporarily be unregistered or absent from a work queue, but its owner is always
defined.  Ownership changes at one release/acquire publication point; the old
owner must not touch the resource after that point and the new owner may not touch
it before that point.

## Prior-art audit

The Redis fork in `/home/user/Projects/tomokv` was inspected before this design.
The requested commits and the heads/history of `flip-u1`, `flip-ownership`,
`flip-signal`, `globallb`, and `consolidated-ex-wb` establish these useful rules:

* `f4cbed5c5` registered `flipCommand` with arity `-2` and flags
  `WRITE|ADMIN|NOSCRIPT|NO_MULTI|NO_ASYNC_LOADING`.  It also returned the live
  and target split, and added `DEBUG TOMO-FLIPSELFTEST`.
* `1ce393392` separated runtime split authority from its actuator and validated
  that IO and EX counts are positive and sum to the provisioned thread budget.
  Its automatic planner and search policy are deliberately not ported here.
* `8164f382d` refused changes during synchronous or asynchronous loading.  This
  tree inherits that safety rule.
* `d4ae88d12` distinguished the operator's requested split from the provisioning
  stride in configuration output.  This tree similarly reports live and target
  values rather than reconstructing either from affinity.

The conservation failure was not fixed by the first diagnostic change.
`5397f2614` published and graded `io_threads_live + num_workers_live ==
configured`, but was primarily observation.  The actual grow-back abort leak was
fixed in `d7d7d137c`: it introduced explicit half-move accounting, rollback on
every abort/release path, atomic grow-back states, and a recovery counter.
`d9192276b` then fixed role-identity publication (including a dormant EX draining
under an IO identity), and `451ec41d7` fixed target publication order.  Thus the
fork ultimately fixed the P0 rather than only hiding it.  This design goes one
step further: all conditions which can refuse a FLIP are checked before any role
or resource ownership is committed.

The fork's automatic r8/r10 controllers, m1 model, cost cells, hill-climb, and
actuator search are policy and are not ported.  This implementation is manual
only.

## Shared terminology and publication rules

* A **physical shard** is a `Shard` object and its `FlatStore`.  The store is
  never copied or rebuilt during migration.
* A **bucket owner** is the EX thread id returned by `Router::shard_of(hash)`.
  Despite the historical method name, the entry is runtime ownership, not
  physical storage identity.  An immutable home map selects the physical shard.
* Bucket transfers are aligned to complete physical-shard ranges.  A non-thread-
  safe `FlatStore` cannot safely be split between two EX threads.  A range can
  contain one or more complete shards, but never part of one.
* A **connection owner** is `Client::ifid_thread()`.  Epoll/io_uring registration
  follows that owner; it does not define ownership.
* All ownership fields use atomic release/acquire publication.  No code may infer
  ownership from a vector, queue, event registration, or thread role.
* A stale message is safe only because the receiver checks the current owner
  before touching the resource and forwards it when ownership differs.

## 1. Bucket transfer

### State machine

Only one bucket-range transfer can publish at a time.  The coordinator owns a
descriptor `(begin, end, source, destination, phase)`.

1. **IDLE / SOURCE OWNS** — every entry in the range resolves to `source`.
2. **PREPARE** — validate that the range is non-empty, aligned to complete
   physical shards, uniformly owned by `source`, and that source and destination
   are live EX threads.  Reserve the destination's shard-vector capacity.  No
   ownership has changed.
3. **QUIESCE SOURCE** — stop admitting matching work at the source.  Drain its
   task and borrow-release inboxes, ordered and retry queues, and any matching
   deferred work.  New stale arrivals are forwarded.  Wait until no executing
   operation, scatter group, atomic group/commit ticket, snapshot control step,
   or epoch-pinned read can touch the range.  Refusal or timeout here leaves the
   source owner unchanged.
4. **PUBLISHING** — publish the descriptor in `PREPARING`.  Routing through the
   descriptor still returns `source` while every `owner_[bucket]` entry is
   written to `destination`.  Readers therefore cannot observe a half-written
   range.
5. **COMMITTED / DESTINATION OWNS** — a single release-store of the descriptor
   phase is the ownership handoff.  Before it, only source may touch the shards;
   after it, only destination may touch them.  Routing through the descriptor now
   returns `destination` even if a caller raced with publication.
6. **INSTALL** — move the physical `Shard*` bookkeeping from the source vector to
   the destination vector.  The objects and all keys/MVCC versions stay where
   they are.  This is bookkeeping after ownership, so source must not dereference
   them.
7. **STABLE** — after all pre-commit source work has either completed or passed
   the receiver's ownership check, clear the descriptor.  The already-written
   owner array now supplies the same destination result.

The forwarding rule is deliberately chosen over per-request routing epochs: an
IO thread can route using a pre-flip owner read and enqueue after the handoff.
Every EX task and borrow release checks current ownership before its first shard
access.  The old owner forwards a stale item to the current owner.  Converted IO
threads also drain and forward their old EX inbox until the handoff grace point,
so a late producer cannot strand work in a dormant inbox.

### In-flight cases

| In-flight state | Resolution |
| --- | --- |
| Operation queued in the losing EX inbox | Drained before publication, or ownership-checked and forwarded. |
| IO read old owner but has not enqueued | Old receiver observes the committed owner and forwards. |
| Operation executing in source | Handoff waits for the source safe point. |
| Ordered, atomic, MULTI, or retry-deferred operation | Its queue is drained; transfer cannot cut the operation/group. |
| Cross-shard scatter group | A global group-in-flight witness must reach zero before publication. |
| Atomic group with commit ticket | Both group and apply/commit witnesses must reach zero; a ticket is never divided. |
| Borrow release queued for an old owner | Receiver forwards before calling `unborrow`. |
| Epoch-MVCC read with pinned snapshot | It completes while source owns the unchanged physical shard; transfer waits for the pin/group witness, so no read crosses the edge. |
| Reader racing the multi-entry owner-array write | The published descriptor returns source throughout `PREPARING` and destination after one commit store. |
| Cursor/whole-shard operation | The complete physical shard is the minimum transfer unit; ownership is sampled once and checked at execution. |

There is no intentionally unsafe case.  Whole-shard alignment is a necessary
restriction: moving only owner entries for part of one non-thread-safe store would
create two concurrent owners of that store even though buckets themselves looked
correct.

## 2. Client transfer

The client and fd move only after the connection protocol is idle.  The reorder
buffer is drained rather than moved while it contains work.

### State machine

1. **SOURCE ACTIVE** — `Client::ifid_thread()` names source; source alone may
   parse, retire, write, register, or close the client.
2. **DRAIN REQUESTED** — source stops parsing new requests and stops arming new
   receives.  Already-parsed operations continue.  Socket bytes already received
   but not parsed remain in the client's input buffer.
3. **DRAIN ROB/OOB** — wait for `dispatch_id == flush_id`, no ready/retire entry,
   empty write segments, no send in flight, and no `WbEngine` deferred OOB or
   active OOB drain for this client.  Empty segments plus no send CQE implies no
   outstanding zero-copy value borrow.  Refusal/timeout here leaves source owner
   and resumes it unchanged.
4. **DETACH ENGINE** — still under source ownership:
   * io_uring cancels the fd's receive/poll request and waits for the original CQE
     to acknowledge cancellation.  A cancellation CQE never transfers ownership.
   * epoll performs `EPOLL_CTL_DEL` at an event-loop boundary, after the current
     returned event batch is consumed.  Thus no source stack frame retains the
     `Client*`.
5. **PREPARE DESTINATION** — reserve destination client/WB capacity and enqueue
   capacity before changing ownership.  Connections with owner-local state that
   cannot be transferred (TLS state, WAIT/blocking state, pubsub/subscriber state,
   MONITOR/CLIENT TRACKING state, MULTI/WATCH state) are refused during FLIP
   preflight, not here.
6. **HANDOFF** — remove source-local membership and release-store
   `ifid_thread = destination`.  This one store is the connection ownership edge.
   The target is the sole owner immediately, even while the fd is temporarily
   unregistered.  Source transports the pointer but never touches the connection
   again.
7. **DESTINATION INSTALL** — destination acquire-loads ownership, installs its WB
   slot and directory entry, then:
   * io_uring arms a receive on the destination ring;
   * epoll performs `EPOLL_CTL_ADD` on the destination epoll set.
8. **DESTINATION ACTIVE** — destination resumes parsing and retirement using the
   unchanged, empty ROB and any buffered input bytes.

### In-flight cases

| In-flight state | Resolution |
| --- | --- |
| Parsed op has a ROB slot or EX task | Drain until ROB is quiescent; the ROB never moves half-full. |
| Bytes received but not parsed | Kept in `Client` and parsed only after target activation. |
| io_uring recv/poll points at `Client` | Explicit asynchronous cancellation; wait for the original CQE before handoff. |
| io_uring send CQE pending | Drain it before handoff. |
| epoll event already returned to source | Transfer is performed only after that event batch completes; then `DEL`. |
| Kernel zero-copy send borrows a value | Segment/send drain waits for release; migration is refused on timeout. |
| Reply partly retired or buffered | Flush completely before transfer, preserving protocol order. |
| Deferred push/OOB frame | `WbEngine` finishes its drain; migration cannot strand or discard the deferred frame. |
| Ready/retire queue contains the client | Source consumes it before declaring the client idle. |
| Newly routed completion races drain | ROB cannot become quiescent until the completion retires; the global FLIP dispatch pause prevents new work. |
| TLS, blocked WAIT, pubsub, tracking, monitor, MULTI, or WATCH owner-local state | Refused by preflight because that state is not yet represented inside `Client`.  No partial move is attempted. |
| Close/error during drain | Source remains owner and performs normal close; FLIP preflight is refused. |

This deliberately extends the invariant documented in `src/net/epoll.h`.
Registrations are no longer "armed once for the lifetime of the fd"; they are
**armed once per IO-ownership tenure**.  Normal operation still never rearms an
edge-triggered fd.  Migration alone uses explicit `EPOLL_CTL_DEL` on the old set
and `EPOLL_CTL_ADD` on the new set.  Teardown continues to rely on `close(fd)`
when no migration is occurring.

There is no intentionally unsafe client move.  Refusing non-self-contained
client modes is preferable to copying hidden loop-local state or violating the
ROB/borrow contract.

## 3. Manual FLIP

Grammar:

```
FLIP
FLIP <io> <ex>
```

The no-argument form reports `live_io`, `live_ex`, `target_io`, `target_ex`, and
whether a transition is moving.  The mutating form returns `+OK` only after the
live split equals the target.  IO and EX must both be positive and `io + ex` must
equal the provisioned physical-thread count.

The command inherits the fork's flags: write, admin, no-script, no-MULTI, and
no-async-loading.  Existing C++ admin commands are not generally hidden behind
`--enable-debug-command`; only `DEBUG` is.  FLIP therefore follows the existing
admin-command convention and does not invent a new configuration knob or gate.

### State machine

1. **IDLE** — `target == live`, no dispatch gate.  Report requests are served
   synchronously.
2. **VALIDATE** — under the flip mutex, validate grammar, positive counts, exact
   conservation, no other FLIP, no loading/reload, no snapshot, and enough
   convertible threads.  Select candidates and destinations while excluding the
   requester/coordinator, AOF writer, and UNIX-listener owner.  Inspect every
   affected bucket/client for all refusal conditions above.  Preallocate dormant
   loop resources, queue capacity, and vector capacity on the future owner
   threads.  Any failure increments `flip_refused` and leaves the old shape live.
3. **QUIESCE** — publish a global dispatch pause.  IO threads stop parsing after
   their current parser pass but keep retiring, sending, cancelling, and handling
   control messages.  EX threads drain tasks, releases, retries, and groups.  Each
   thread acknowledges only at a loop safe point.  Wait for zero scatter groups,
   zero atomic groups/apply tickets, no snapshot/pinned operation, drained
   migrating ROBs/OOB/borrows, and detached engine registrations.  Timeout or
   inability to quiesce clears the gate, restores normal admission, increments
   `flip_refused`, resets target to live, and returns an error.  Ownership is
   still entirely the old shape.
4. **COMMIT PLAN** — verify conservation immediately before mutation.  From this
   point every resource and queue needed by the plan is reserved and no expected
   operational condition may fail.  An internal failure is an invariant failure,
   not a recoverable partial shape.
5. **EX TO IO** — for each selected EX, transfer all of its complete shard ranges
   to surviving EX threads using the bucket state machine, drain/forward its last
   EX messages, atomically change its role, and activate its prepared IO loop.
   Buckets leave before the role changes.
6. **IO TO EX** — for each selected IO, transfer all its clients to surviving IO
   threads using the client state machine, atomically change its role, activate
   its prepared EX loop, and only then rebalance/take complete shard ranges.
   Connections leave before the role changes; buckets arrive afterward.
7. **AWAIT LIVE** — every converted physical thread publishes target-role ready;
   all transferred objects are installed; forwarding inboxes are empty.  Count
   ready IO and EX threads, assert both their sum and the physical-thread count
   equal the provisioned total, and increment the conservation-check counter.
8. **COMPLETED** — set live and target to the verified split, increment
   `flip_completed`, clear the dispatch gate, then complete the request's ROB
   operation with `+OK`.  This ordering makes the reply proof that the shape is
   live.

FLIP is a single transaction at the control-plane level.  Every recoverable
refusal point is in VALIDATE or QUIESCE, before ownership mutation.  The
implementation must not attempt a best-effort rollback after the commit plan;
such a rollback would itself create ambiguous ownership.  Unexpected failures
after that edge terminate via an invariant assertion instead of publishing a
partial, apparently healthy split.

### In-flight cases

| In-flight state | Resolution |
| --- | --- |
| Request is being parsed/acquired but not published | IO acknowledges pause only after the parser pass; acquired slots are published or cancelled normally. |
| Published single-shard task | Drained, executed, or forwarded before the corresponding bucket edge. |
| Cross-shard/atomic operation | Global witnesses must be zero; FLIP never cuts the group or its commit ticket. |
| Epoch-pinned read/snapshot control | Completes before commit; FLIP is refused while snapshot/load/reload is active. |
| Completion/borrow release headed to a converting thread | Old-role inbox is drained and stale messages are ownership-forwarded during the grace phase. |
| FLIP request's own ROB slot | It is held by the surviving coordinator IO and completed only in COMPLETED/refused state.  That client is never selected for transfer. |
| New socket request during pause | Bytes may be received/buffered, but no new command is dispatched until the gate clears. |
| Client reply, OOB, recv/send CQE, or zero-copy borrow | Resolved by the client-transfer drain rules before commit. |
| Late route using a pre-transfer bucket owner | Resolved by EX forwarding; no per-request epoch is required. |
| Loading or async reload | Refused, inheriting the fork's `NO_ASYNC_LOADING` safety rule. |

### Observability and tests

`INFO` exposes live IO/EX counts, completed flips, refused flips, successful
conservation checks, and conservation violations.  The report form exposes both
live and target counts so a refusal or transition is visible directly.  A test
must cover both conversion directions, invalid totals, report/live agreement,
counter changes, data survival, connection order across an IO handoff, and the
fact that conservation checks increase without a violation.

No automatic controller, timer, target search, or background hill-climb exists.
