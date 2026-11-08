# Server-state decisions preserved by readability-a5

These entries record rationale found in the frozen source, with function names at
`9a09e5919`. The dates below are documentation dates unless an original date is
explicitly supplied. Historical measurements are provenance, not new performance
results; this lane does not run throughput measurements.

## 2026-11-08 — Fixed assertion padding

`version.cc::assertion_rodata_pad`: the stable-assertion conversion reduced the
suffix-merged linked `.rodata` by 1152 bytes. The last-linked namespace variant
owns that exact padding so later section addresses remain fixed. Source literal
sizes do not determine the required padding. The entry wrapper remains outside
execution-loop translation units and preserves their compiler settings.

## 2026-11-08 — Owner GET borrowing threshold

`Config::zc_min`, consumed by `Shard::set_zc_min`: keep the 16384-byte default,
zero-as-off behavior, and the gather cutoff `min(zc-min, ValueSlot::kInline)`.
The removed comment attributes the choice to an owner ruling and reports -4.1%
server cycles at d16K on the wire-limited NIC and a +20–24% class on unrestricted
wires in prototype history. No receipt or date accompanies those numbers in the
source, and this lane does not independently substantiate them. Local-read
replies always copy.

## 2026-11-08 — Configuration grammar and ownership

`parse_config_args`, `EncodingConfig::parse`, `cfg_parse_query_buffer_limit` and
`cfg_process_store`: retain shared parsing without broadening Redis-named or
TomoKV-alias grammars. General 0/off and -1/auto guidance has exceptions (notably
slowlog, list size and hz); the comments now follow the actual parsers. Config
string views borrow stable token storage; vectors own values. Process defaults
allocate no sidecar. Config's 624-byte layout remains fixed, including encoding,
stream, writeback, password-length and process-handle storage.

## 2026-11-08 — Optional telemetry and writeback defaults

`Config` initialization: automatic FLIP and read-local default off; fingerprint
sampling belongs to the enabled FLIP controller. Latency tracking defaults to no,
although Redis 7.4 defaults to yes. `wb_policy=1`, small-pipeline threshold 16 and
completion-visit limit 3 remain the defaults supplied by `wb_rule`; this lane
changes no policy or allocation behavior. The original Config comments call the
writeback defaults measured without including a measurement table.

## 2026-11-08 — Fused-only shadow scheduling

`reorder_for_mode` keeps split mode at zero because split IO already flushes
independently. The source attributes the restriction to measured wall loss but
supplies no number in this file. `reorder_available` remains the capability gate
used by the offline layout control; no scheduling arm is created here.

## 2026-11-08 — Network engine and live publication

`persistence_engine` derives syscall persistence IO for epoll, which has no
io_uring ring. The old network-enum comment says only uring had measured results;
that historical evidence limit is not a runtime contract. `LiveConfigMailbox`
keeps fixed three-slot storage, one consumer per physical thread (plus the
transfer coordinator), and serialized CONFIG writers. Both committed and staged
values remain available even if either participant stops. No reader retry,
seqlock, allocation per update or slot reclamation is introduced.

## 2026-11-08 — Flat shards and locality accounting

`Shard::note_execution`, `Shard::note_migration` and `migration_cost_bytes`: keep
one flat keyspace and whole-store ownership transfers, with locality expressed
through placement. The removed header records prototype L3 partition results of
+22.3% on set_p16 and +14.2% on mget8, and about 51 GB/s CCX fabric bandwidth
against about 50 GB/s from one core. Those figures have no receipt/date in this
header and are not independently revalidated here. Migration invalidates cache
residency even though it does not copy keys, so it cannot be priced as free.

## 2026-11-08 — Runtime roles and SPSC transport

`ThreadCtx::set_role`, `post_task` and `post_task_quiet`: role changes are runtime
state, with a direct transition after the FLIP drains rather than an intermediate
Idle role. The removed header cites an earlier prototype P0 and an approximately
16:1 IO:EX depth-one optimum scaling as 16:1/depth; those historical observations
are not universal placement guarantees. Per-producer SPSC queues avoid the MPSC
push RMW. Quiet pushes batch notification work once per producer/consumer pair;
the old comment illustrated 32 pushes sharing one notification/wake decision.

## 2026-11-08 — Progress does not depend solely on masks

`ThreadCtx::sample_depth`, `drain_tasks_unmasked` and `arm_blocked`: time-based
100-microsecond sampling prevents idle-spin frequency from dominating pressure
signals. The sweep repairs task summary bits and the pre-park path drains queues
directly. The source records 209 connections holding posted, unserved claims
while a sender was idle; that incident motivates the independent queue check.
The store/fence/recheck park protocol and each notification's publish order stay
explicit in source, including fused consumers kept busy by parked transactions.

## 2026-11-08 — Separate transport and accounting cache lines

`ThreadCtx::note_command` and `ThreadCtxLayoutLock`: keep `atomic_scan_holds_`
beside transport pointers at offset 120, and ordinary `total_commands_` at offset
408 beside owner-written accounting. The original comment dates the confirmed
counter swap to 2026-09-13. The flip controller still reads total commands; this
separates transport traffic rather than eliminating all remote reads. ThreadCtx
remains 1408 bytes, including its optional read-local tail pointer.

## 2026-11-08 — Shard layout and WATCH state

`Shard::has_watches`, `refresh_has_watches`, `note_txn_boundary` and
`ShardLayoutLock`: packed route endpoints leave the WATCH summary in the hot
header. Transaction-boundary notes travel with the physical shard. Notification
bindings and optional LB arrays belong to the cold tail; moving `server_` to
offset 8 previously shifted the header. The 1440-byte stride, FlatStore offset 56
and Stats offset 1000 remain locked, alongside both WATCH-map offsets.

## 2026-11-08 — Background census must not expire keys

`Shard::lb_scan_bucket_bytes`: preserve `expire_on_visit=false`. The source names
an expwide S1 failure: a controller census outside any operation's expiry cut can
otherwise delete a key while a cross-shard read still needs it. A temporarily
high byte estimate is acceptable; a torn read is not.

## 2026-11-08 — Observable faults and reservation overlap

`Shard::Stats::atomic_gauge_underflows` records a version-byte over-decrement
instead of aborting, but must remain zero in tests. `watch_reservation_coexist`
records overlapping undecided reservations; crossed reservations must not create
a wait-for cycle. Armed tests must demonstrate this overlap before accepting a
clean result. These counters are distinct from expected holds and refusals so a
violation cannot be hidden inside a normally nonzero aggregate.

## 2026-11-08 — Read-local state is optional in both modes

`ThreadCtx::init_read_local_state`, `read_local_arm_stats_or_null` and
`Shard::set_notify_mask`: the implementations support armed state in split as
well as fused mode. Notification masks come from committed live-config mailboxes,
not a seqlock. Plain telemetry fields retain their exceptional INFO read path;
a general C++ race-free snapshot guarantee is not established by these structs.
This lane documents that limitation without changing the implementation.
