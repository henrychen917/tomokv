# DIFF-TRK-1: information available at the consumer

The requested existing-ordering restriction prevents a complete causal fix in
the required `atomic=0, read-local=0` configuration. This is a source finding,
not a conclusion from a failed identity check or a performance measurement.

* `src/core/io_loop.h` stamps `Op::read_cut` only when
  `Server::atomic_tracking_active()` is true. Its comment explicitly states
  that the sequence is not loaded with atomic disabled.
* `NotifyRecordImpl::sequence` starts at zero in each `NotifyBatch`; it orders
  records from one operation, not operations from different clients.
* `tracking_broadcast_keys` passes only the changed key and writer client ID.
  Its `PubSubEventItem` sets `index`, `changed`, and `count` to zero. It carries
  neither a write commit version nor an execution stamp.
* `ClimonConn::tracking_pending` maps the key to an `Op*`. The operation can
  establish that the read is Done, but cannot place its execution before or
  after the write whose delayed event is now delivered.

Consider a SET which writes the same bytes already present. Schedule A executes
SET before GET; schedule B executes GET before SET. Deliver the SET event when
GET is Done but not retired in both schedules. At the tracking consumer, key,
writer ID, pending Op, reply bytes, state, and the batch-local sequence can all
be identical. The requested result differs: A must preserve enrollment without
a frame; B must invalidate and prevent stale re-enrollment. A decision using
only those observations cannot distinguish the schedules.

The existing `notify_events_fired` counter could supply an armed notification
sequence without introducing another global increment. However, that sequence
is not currently carried by the read or event, RESETSTAT semantics and
speculative notification records need examination, and a read execution
observation would still have to be added. A dispatch-time stamp alone does not
prove the read observed a write that committed after dispatch but before
execution. A post-retirement timestamp is also insufficient.

An asynchronous clarification asked whether adding ordering metadata confined
to armed tracking reads and notifications is permitted, while keeping unarmed
GET/SET/MGET/MSET bodies identical. Until that constraint is resolved, no
causally incomplete deduplication or speculative ordering patch is installed.
The scheduling fixture and exact Redis receipts remain a deterministic failing
witness, and CC4.4 is fixed independently.
