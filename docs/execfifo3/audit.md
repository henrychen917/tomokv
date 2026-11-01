# Plain-writer audit

Base: `e32b04a44`; FIFO: `2461efbbb` (execfifo2). Work uses CPUs 96–111,
ports 20600–20699, and `LC_ALL=C`. No throughput workload is authorized here.

The source audit does **not** support an unconditional FIFO waiter lookup on
SET/INCR. `ex_execute.inc` already tests `Shard::has_watches()` before calling
`multi_plain_write_ready`. The dispatch probe in `atomics_glue.inc` has the
same guard. Both read the existing byte at Shard+8 (header line 0), next to
the owner-written clock at +16. No FIFO queue or reservation map is read when
the byte is false. Read-local SET uses this same owner gate; read-local arms
immutable replacement, not a different FIFO predicate.

The added boundary byte occupies Shard+9, existing padding. Only this shard's
owner writes it, and only transaction/blocked-service paths access it.
`TxnRetryQueues` remains 80 bytes; its new ready links, markless count and
chaining flag consume existing padding. The ordinary ExLoop fields do not
move. `TxnOwnerCounters` remains 192 bytes (20 -> 23 counters); the Server
members after its array do not move either. FIFO links enlarge heap-owned
TxnKeyQueue/TxnWaiter records, which ordinary no-WATCH/no-EXEC writes never
allocate or access.

New accesses when the slow path is active:

* `watch_key_ready_impl<true>` reads the key queue's EXEC head, its reservation
  liveness/age, and (when a head exists) writer marks. It may unlink dead
  waiters. These are owner-only queue links; decision/abort/refcount words can
  be written by participating IO/owner threads. Existing held-claim checks
  remain in force.
* A refused writer retains its episode, sets its existing Op hazard bit, and
  updates owner-local FIFO/writer counters. A successful final gate removes
  marks only for a previously hazardous Op. Dispatch probes preserve marks.
* C1 boundary/chain calls execute only on tagged transaction tasks, or after
  `service_multi_retries` finds a nonempty retry queue. Their no-transaction
  fast return reads the same count as PRE.

Instruction counts alone do not prove cache-line identity. Linked-image
memory traces, read-local scopes, and finite one/two-thread perf fixtures
will test the source conclusion. Compiler changes outside the former command
scope remain possible. The prior common-image PAD preserves the complete
ELF layout, but selects different PRE and POST functions; it does not put
their executed instructions at identical addresses.
