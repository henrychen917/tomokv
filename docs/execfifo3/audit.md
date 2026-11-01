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

The missing path was the parser. The original command scopes begin after
parsing. A linked-production parser scope at batch 32 finds db0 fused SET
at 23,669 -> 25,045 instructions (read-local off) and 27,427 -> 28,803
(read-local on). INCR adds 1,280 instructions per batch. The added calls are
`parse_len_crlf` and its caller, `resp_parse_t<false,true>`; SET adds 704
explicit memory operands per batch, INCR 608. The recorded Server, Shard,
ExLoop, ThreadCtx, IoLoop and Client accesses remain identical. A compiler
change therefore caused work outside the previously counted owner scope.
The SET delta is 160 stack reads, 480 stack writes and 64 reads of the
thread-local stack canary at `FS+0x28`; outlining address-taken parser locals
introduces stack protection as well as spills. The INCR/GET delta has 384
stack writes instead. The additional TLS reads are directly classified in
`memory-sites/`; they are not FIFO state or another owner's publication line.

FIFO/C1 enlarges each fused translation unit's initial GCC IPA size by 2,031
instructions. Its unchanged `large-unit-insns` ceiling reduces the allowance
for inlining existing code. Raising each of the two fused ceilings by exactly
2,031 restores the parser scopes above to PRE counts, including memory
operands. The extended trace also finds +44 instructions and three explicit
memory operands per batch in the multi-database split parser, including an
outlined `Client::nothing_to_write`. Restoring that unit's 1,646-size-unit
allowance removes this delta as well. The production change is three Makefile
values. All FIFO predicates, queue links, promotion rules and boundary code remain byte-for-byte
unchanged in source. Final linked-image scopes and perf receipts qualify the
result; no server throughput improvement is inferred.

The prior common-image PAD preserves the complete ELF layout, but selects
different PRE and POST functions; it does not put their executed instructions
at identical addresses. It cannot distinguish this compiler inlining change
from an intentional FIFO data-access change. The new PAD has the same explicit
limitation; compare the release arms as well.
