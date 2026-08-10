# Execution-context and epoch-MVCC footprint audit

Audited branch: 2s-audit-execctx

Audited baseline: d7d7d137cc9131f3c261ece94eeec58af97d1666

This is a source and history audit only. I did not compile, start a server, run a
test, or run a benchmark. All sizes below are LP64/x86-64 ABI arithmetic from
the declarations in this tree: pointers, size_t, long, time_t, off_t, and
uint64_t are 8 bytes; int, unsigned, enum, and the C11 atomic int types are 4
bytes; atomic_flag is 1 byte; and the largest ordinary alignment in the
structures is 8 unless an explicit 64-byte alignment is shown.

The cache-line count is based on the specified 64-byte hardware line. “Layout
regions” means offset/64 within the object. A client is only 8-byte aligned, so
an allocator placement can make one layout region cross a physical line. I
give the physical range where that distinction changes the answer.

## Verdict

The best target is the dispatched client, not another prefetch scheme. The
current client is 1,160 bytes, spans 19 physical cache lines at every possible
8-byte-aligned placement, and a minimal successful dispatched GET touches 13
distinct 64-byte layout regions in the client structure alone. With the
placements permitted by normal allocator alignment, those fields occupy
12–14 physical lines. Four entire early lines are the real connection’s
fakeClients pointer array, which is dead space inside every fake. The default
jemalloc usable class is 1,280 bytes, or 20 lines of allocation capacity.

A 320-byte common execution core is feasible without changing the IO/EX stage
boundary. It would put the same GET state in five layout regions (normally
five or six physical lines), a reduction of eight layout regions and six to
nine physical lines per command. Keeping an optional 840-byte tail preserves
the real/generic client’s aggregate 1,160-byte field budget. Common fakes would
allocate only the 320-byte core. This is the one proposal I would prototype
first. The likely gain is 1–3%, not a cache-miss miracle: it comes from fewer
line-sized regions read and dirtied at handoff, fewer generic reset checks and
stores, tighter fake-ring packing, and about 5.13 MiB less struct payload for
200 connections at depth 32.

The next useful object-layout experiment is smaller and orthogonal. The
ordinary redisObject header is actually 24 bytes, not the stale 16 bytes in
several comments, because every object carries an 8-byte vmeta pointer.
Returning ordinary robj to 16 bytes while placing an 8-byte vmeta slot
immediately before every stored kvobj header keeps the total stored-key
allocation and key/value offsets exactly unchanged. It removes one
initialization store and moves common 9–12-byte command operands from the
48-byte allocator class to 32 bytes. It also restores the intended
44-byte EMBSTR object to exactly 64 bytes instead of the current 72. Expected
gain: 0.5–1.5% on small-object GET/SET, with an atomic-read regression test as
the decisive falsifier.

The current tomoVerMeta is 120 requested bytes and normally consumes the
128-byte allocator class. A tagged owner-job representation could be designed,
subject to the lifetime proof below, to remove 32 bytes of duplicated
kv/sequence descriptors, yielding
an 88-byte struct in the 96-byte class. Another 8-byte version_kvs field looks
derivable from version_db->keys, but this tree swaps database key stores, so
that derivation is not proven safe. The 80-byte form is therefore an option
only after a database/store lifetime proof. Both forms still span two lines,
so I expect at most 0.1–0.5% on atomic writes. Given the owner’s rejected
full-vmeta-embed result, I would not implement this before the client work.

The minimum active atomic-only footprint for a versioned key is one vmeta:
120 requested bytes, normally 128 usable bytes. For an overwrite bag that
continues to retain a predecessor after an ordinary overwrite’s grace would
have ended, the mathematical minimum rises to 151 requested bytes
(120-byte vmeta plus a 31-byte empty-key/empty-value kvobj) or 160 usable
bytes (128 + 32). A one-byte key makes the requested number 152. Real p32
keys are larger.

The measured context changes the ranking. Per-worker service is about 500 ns
regardless of thread count, a 21x data-set increase costs 3.5%, and group
prefetch is a wash with its gate 97.8% open. Therefore this report does not
credit any proposal merely for reducing hoped-for misses. It credits fewer
loads/stores/branches, fewer bytes initialized or copied, fewer line ownership
transfers, and more contexts fitting in the shared 32 MiB L3. On the stated
7700X, IO and EX cores have private 32 KiB L1d and 1 MiB L2 caches but share
one 32 MiB L3 on one CCD. A handoff can therefore move ownership between
private caches without being a cross-CCD or DRAM miss.

## Ranked proposals

| Rank | Proposal | Current | Proposed | Estimated result | Verdict |
|---:|---|---|---|---|---|
| 1 | Pack and split the client into a common execution core plus optional tail | client 1,160 B / 19-line span, class 1,280/20-line capacity; GET touches 13 layout regions (12–14 physical lines) | core 320 B/class 320 / 5 layout regions (5–6 physical); optional tail 840 B/class 896 / 14 regions (14–15 physical); real field total remains 1,160 B but two allocations can span 19–21 physical lines | 1–3% GET, roughly 5–15 ns/op; 15–35 fewer reset/move instructions is a reasonable target | Prototype first |
| 2 | Move the universal vmeta word out of ordinary robj and into a fixed kvobj prefix slot | sizeof(robj) = sizeof(kvobj) = 24 B/1 region; p9–p12 operand object 37–40 B, normally class 48; V44 object 72 B/2 regions | sizeof(robj) = sizeof(kvobj) = 16 B/1 region; stored kvobj adds an 8 B prefix so its total allocation is unchanged; operand becomes 29–32 B/class 32; V44 becomes 64 B/1 region | 0.5–1.5% small GET/SET; one less vmeta=NULL store per ordinary object and 16 fewer usable bytes for common key operands | Worth a contained prototype after client packing |
| 3 | Encode owner-op kind in the already-tagged queue pointer and share kv/seq in vmeta | tomoOwnerOp 24 B each; tomoVerMeta 120 B/class 128/2 regions | tomoVerMeta 88 B/class 96/2 regions; 80 B/class 80 only if version_kvs derivation is proven | 0.1–0.5% atomic write; likely only a few stores/instructions plus 32 usable bytes | Correctness-sensitive option; low confidence |
| 4 | Derive csMsetInstall.install_order from its array index | install 16 B; MSET8 array 128 B/2 regions | still 16 B and 128 B/2 regions because alignment replaces the field with padding | About 3–8 instructions/key, under 0.1% throughput | Safe cleanup if the index invariant is asserted; not a footprint win |
| 5 | Use separate worker and IO strides in flatBatch | for any IO+EX=8 split: 176 B/3 regions, normally class 192 | 24 + 8*(EX + 9 + 1) B: 144 B/3 regions at io3/ex5, 136 B/3 at io4/ex4, 128 B/2 at io5/ex3 | Essentially 0% throughput; the unused worker slots are allocated but not written | Memory hygiene only; will not pay |
| 6 | Correct commit_ctl’s padding | intended 64 B but actually 128 B/2 regions; live fields occupy one | 64 B/1 region by placing pointers before atomic_flag or padding from the real offset | 0% throughput; saves one global padding line | Fix opportunistically, not as performance work |
| 7 | Remove csPubRec.tag and trust FIFO position | record 152 B/3 regions; depth-32 ring 4,880 B/77 regions | record 144 B/3 regions; ring 4,624 B/73 regions | Below 0.1%; saves one cold identity store/compare | Not worth losing the lifetime-discipline assertion |
| 8 | Raise standalone EMBSTR limit from 44 to 52 if robj remains 24 B | max embedded request 72 B, class 80/2 regions; 45–52 B values use two allocations, normally 96 usable B total | max request 80 B, same class 80/2 regions | Workload-distribution dependent and probably below 0.3% overall | Do not do this if rank 2 is adopted; otherwise measure a size histogram first |

The full vmeta-in-kvobj design is deliberately absent from the ranked list.
Repository commit f3a830377 implemented it as a 112-byte prefix, predicted
300–500 instructions/key, and retained the prefix after promotion. The owner
has rejected that attempt as not paying. Nothing in this audit changes the
trade: the current measured install, including the separate vmeta allocation,
was already 50.8 ns versus 62.8 ns for ordinary install. I do not re-propose it.

For completeness, the confirmation/refutation measurements for the low-ranked
rows are:

- Rank 4: static layout must remain 16 bytes/install and 128 bytes/MSET8.
  Compare atomic MSET8 instructions/key; fewer than three saved
  instructions/key confirms that even the cleanup estimate was optimistic.
  Duplicate-key result/order is the correctness discriminator.
- Rank 5: record the batch allocation class and QSBR bytes/batch, then compare
  reclaim instructions/op. Throughput or instruction movement above 0.1%
  would be surprising; unchanged grace-ready decisions are mandatory.
- Rank 6: a future static assertion must report 64 bytes and inspection of the
  symbol address must show one aligned line. No throughput movement is
  expected; this proposal is refuted as a performance idea even if the size
  correction succeeds.
- Rank 7: confirm 144 bytes/record and 4,624 bytes at depth 32, then require
  unchanged own-read hold/conservative counters and publication ordering. A
  throughput result below 0.1% means the lost assertion bought nothing, which
  is my expectation.
- Rank 8: first measure the command-value length histogram. Only if 45–52
  bytes are material should a dedicated p45/p48/p52 cell compare allocation
  count, instructions/op, and throughput. Mutation, module DMA, and
  unsharing paths must retain identical results. No traffic in that band
  refutes the proposal without a benchmark.

## 1. client and dispatched fake client

### Exact current sizeof(client)

The default source configuration does not define LOG_REQ_RES. If an out-of-tree
build flag defines it, clientReqResInfo is inserted after last_header and every
later offset must be recomputed. For the tree as configured here,
sizeof(client) is 1,160 and alignof(client) is 8.
There is no smaller fake type: createFakeClient allocates this same full
client, so sizeof(the dispatched fake) is also 1,160 before its separate reply
buffer and list allocations.

The following is the field-by-field layout. Padding rows are real ABI padding,
not guesses.

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 4 | isFake |
| 4 | 4 | padding for parent |
| 8 | 8 | parent |
| 16 | 256 | fakeClients[32] |
| 272 | 4 | dispatchid |
| 276 | 4 | flushid |
| 280 | 4 | fake_ring_cur_depth |
| 284 | 4 | ring_size |
| 288 | 4 | ring_mask |
| 292 | 4 | ring_want_grow |
| 296 | 4 | cs_barrier |
| 300 | 4 | mset_pending_lock |
| 304 | 4 | mset_drain_latch |
| 308 | 4 | mset_pending_count |
| 312 | 4 | mset_read_waiting |
| 316 | 4 | padding for pointer alignment |
| 320 | 8 | mset_pending_head |
| 328 | 8 | mset_pending_tail |
| 336 | 8 | mset_pub |
| 344 | 8 | tomo_read_snapshot |
| 352 | 4 | tomo_read_snapshot_pinned |
| 356 | 4 | fake_ring_decay_skip |
| 360 | 8 | fake_ring_hwm_ewma |
| 368 | 4 | fake_ring_hwm_win |
| 372 | 4 | padding for reply_cdb |
| 376 | 8 | reply_cdb |
| 384 | 4 | fake_slot |
| 388 | 4 | cdb |
| 392 | 8 | csgroup |
| 400 | 8 | csparent |
| 408 | 4 | cssub_idx |
| 412 | 4 | is_flush |
| 416 | 4 | flush_dbid |
| 420 | 4 | flush_async |
| 424 | 8 | drain_ack |
| 432 | 8 | mig_parked_node |
| 440 | 4 | mig_parked_tid |
| 444 | 4 | padding |
| 448 | 8 | atomic_window_parked_node |
| 456 | 4 | atomic_window_parked_tid |
| 460 | 4 | padding |
| 464 | 8 | arrival_us |
| 472 | 8 | prefetch_key_hash |
| 480 | 4 | prefetch_key_hash_valid |
| 484 | 4 | padding |
| 488 | 8 | prefetch_dict |
| 496 | 8 | prefetch_bucket_idx |
| 504 | 8 | id |
| 512 | 8 | flags |
| 520 | 8 | conn |
| 528 | 1 | tid |
| 529 | 1 | running_tid |
| 530 | 1 | io_flags |
| 531 | 1 | read_error |
| 532 | 4 | resp |
| 536 | 8 | db |
| 544 | 8 | name |
| 552 | 8 | lib_name |
| 560 | 8 | lib_ver |
| 568 | 8 | querybuf |
| 576 | 8 | qb_pos |
| 584 | 8 | querybuf_peak |
| 592 | 4 | argc |
| 596 | 4 | padding |
| 600 | 8 | argv |
| 608 | 4 | argv_len |
| 612 | 4 | original_argc |
| 616 | 8 | original_argv |
| 624 | 8 | all_argv_len_sum |
| 632 | 24 | pending_cmds: head, tail, len, ready_len |
| 656 | 8 | current_pending_cmd |
| 664 | 8 | deferred_objects |
| 672 | 4 | deferred_objects_num |
| 676 | 4 | padding |
| 680 | 8 | io_deferred_objects |
| 688 | 4 | io_deferred_objects_num |
| 692 | 4 | io_deferred_objects_size |
| 696 | 8 | cmd |
| 704 | 8 | lastcmd |
| 712 | 8 | lookedcmd |
| 720 | 8 | realcmd |
| 728 | 8 | user |
| 736 | 4 | reqtype |
| 740 | 4 | multibulklen |
| 744 | 8 | bulklen |
| 752 | 8 | reply |
| 760 | 8 | reply_bytes |
| 768 | 8 | deferred_reply_errors |
| 776 | 8 | sentlen |
| 784 | 8 | ctime |
| 792 | 8 | duration |
| 800 | 4 | slot |
| 804 | 4 | cluster_compatibility_check_slot |
| 808 | 8 | cur_script |
| 816 | 8 | lastinteraction |
| 824 | 8 | io_lastinteraction |
| 832 | 8 | obuf_soft_limit_reached_time |
| 840 | 8 | io_last_client_cron |
| 848 | 4 | authenticated |
| 852 | 4 | padding |
| 856 | 8 | reploff_next |
| 864 | 8 | woff |
| 872 | 8 | peerid |
| 880 | 8 | sockname |
| 888 | 8 | client_list_node |
| 896 | 8 | io_thread_client_list_node |
| 904 | 8 | last_memory_usage |
| 912 | 4 | last_memory_type |
| 916 | 4 | padding |
| 920 | 24 | clients_pending_ex_node |
| 944 | 24 | clients_pending_write_node |
| 968 | 24 | pending_ref_reply_node |
| 992 | 8 | net_input_bytes_curr_cmd |
| 1000 | 8 | net_output_bytes_curr_cmd |
| 1008 | 8 | buf_peak |
| 1016 | 8 | buf_peak_last_reset_time |
| 1024 | 8 | bufpos |
| 1032 | 8 | buf_usable_size |
| 1040 | 8 | buf |
| 1048 | 1 | buf_encoded |
| 1049 | 7 | padding |
| 1056 | 8 | last_header |
| 1064 | 8 | net_input_bytes |
| 1072 | 8 | net_output_bytes |
| 1080 | 8 | commands_processed |
| 1088 | 8 | task |
| 1096 | 8 | node_id |
| 1104 | 4 | pending_read |
| 1108 | 4 | padding |
| 1112 | 8 | tomo_bkt_ptr |
| 1120 | 4 | tomo_bkt |
| 1124 | 4 | padding |
| 1128 | 8 | tomo_key_h |
| 1136 | 8 | flush_bar |
| 1144 | 8 | cold |
| 1152 | 8 | uring |
| 1160 | 0 | end; no tail padding |

There are 55 bytes of internal padding and no tail padding. The size arithmetic
is therefore 1,105 bytes of fields + 55 bytes of padding = 1,160 bytes.
ceil(1,160/64) is 19. Because 1,160 + the maximum 56-byte displacement of an
8-byte-aligned address is 1,216 = 19*64, the allocation spans 19 physical
lines for every allowed 8-byte placement. Under the default jemalloc classes,
the 1,160-byte request has 1,280 usable bytes, or 20 lines of capacity; that
allocator slack is not part of sizeof(client).

### Existing cold sidecar

The tree has already made one good split. clientCold is nullable and every
fake leaves cold NULL. Its exact size is 504 bytes, or eight layout regions
(eight or nine physical lines without a 64-byte placement guarantee).

| Offset | Bytes | clientCold group |
|---:|---:|---|
| 0 | 4 | initialized |
| 4 | 4 | padding |
| 8 | 88 | multiState: pointer + four ints + size_t + int/pad + 48-byte list |
| 96 | 72 | blockingState |
| 168 | 40 | three pubsub pointers, tracking id, tracking-prefix pointer |
| 208 | 12 | replstate, start-on-ack, repldbfd |
| 220 | 4 | padding for off_t |
| 224 | 16 | repldboff, repldbsize |
| 240 | 8 | replpreamble |
| 248 | 80 | ten 64-bit replication offsets/timestamps |
| 328 | 41 | replid[41] |
| 369 | 3 | padding |
| 372 | 4 | slave_listening_port |
| 376 | 8 | slave_addr |
| 384 | 8 | slave_capa, slave_req |
| 392 | 64 | main-channel id, six node/position fields, io_last_repl_cron |
| 456 | 40 | five module/auth pointers |
| 496 | 8 | postponed_list_node |
| 504 | 0 | end |

Commit 127edc6d3 introduced this sidecar. The merge description at 94f0a33da
reports +1.3% GET for the combined cold-sidecar and lazy-decoy-DB change. That
is not a clean sidecar-only measurement, but it is a useful prior that moving
truly cold client state can matter at the one-percent scale.

There is a second in-tree prior in the client declaration itself: moving the
24 bytes of tomo bucket/hash carry from the middle of the struct to its tail
restored the old reply-control offsets and is recorded as a roughly 2–5% win.
That result is specifically about packing/cross-core line ownership, not an
LLC-miss hypothesis, and is why the 13-to-5 packing experiment ranks first.

### What a minimal fake GET touches

This count is for the client struct itself. It deliberately excludes the
pointed-to argv objects, dictionary/table/value, and the separate 1,024-byte
fake reply buffer.

The steady successful path consists of moveExecutionStateSlim, worker
prefetch/dispatch, getCommand, reply construction, completion drain, and
commandProcessed/resetClientInternal. It touches these 13 layout regions:

| Region | Offsets | GET-touched fields | Cold fields sharing the region |
|---:|---|---|---|
| 0 | 0–63 | isFake, parent | first 48 B of fakeClients |
| 5 | 320–383 | snapshot-pinned check (snapshot itself only when pinned) | atomic pending FIFO, ring controller, reply_cdb |
| 6 | 384–447 | fake_slot, cdb, csgroup, csparent | flush and migration fields |
| 7 | 448–511 | prefetch hash/valid/dict/bucket | atomic-window parking, arrival timestamp, id |
| 8 | 512–575 | flags, conn, running_tid, resp, db | names, library identity, querybuf |
| 9 | 576–639 | argc, argv, argv_len, argv byte sum, pending-list head | parser peaks, original argv |
| 10 | 640–703 | pending-list tail/counts, current_pending_cmd, cmd | deferred-object arrays |
| 11 | 704–767 | user, reply, reply_bytes | lookup/real command, request parser state |
| 12 | 768–831 | deferred-error invariant, sentlen, duration reset, slot, cluster slot, cur_script | creation/interaction times |
| 13 | 832–895 | authenticated | output-limit time, cron time, repl offsets, peer names, client-list pointer |
| 15 | 960–1023 | command byte counters, buf_peak | intrusive global-list nodes, peak reset time |
| 16 | 1024–1087 | bufpos, usable size, buf, encoded flag, last_header, commands_processed | lifetime network totals |
| 17 | 1088–1151 | tomo bucket pointer/index/hash and cold-null check | migration task/node, pending_read, flush barrier |

At a 64-byte-aligned base this is exactly 13 physical lines. Enumerating every
8-byte base displacement for the exact accessed fields gives 11–14 physical
lines; restricting that to normal 16-byte allocator placements gives 12–14.
The stable answer to “how many lines?” is therefore 13 distinct layout
regions, normally 12–14 actual hardware lines.

The hot/cold interleave is severe:

- Every fake carries the real-only 256-byte fakeClients array: four complete
  lines that are never useful to the fake.
- Ring growth, atomic connection admission, flush, migration, parser, client
  list, replication-adjacent, and monitoring fields sit in the same lines as
  dispatch, command, reply, and reset fields.
- The hot set is not merely large; it is scattered from offset 0 through
  offset 1,151. A worker prefetch of fake and &fake->argc cannot cover the
  completion and reply tail.

resetFakeClientState initializes most of the structure when a fake is created
or repurposed, but it is not the entire steady per-command tax. The steady tax
is the scattered move, execute, reply, completion, and generic reset work
above. This distinction matters: merely shrinking a one-time constructor
would not explain a throughput win.

### Proposed 320-byte execution core

This is a layout target, not a patch. The payload fits with explicit arithmetic:

- 31 eight-byte words = 248 bytes: parent; snapshot; group/parent pointers;
  three prefetch words; flags, conn, db; argv and argv accounting; pending
  list pointers/current command; user; reply, reply bytes and sent length;
  buffer/counter words; tomo pointer/hash; and one tail pointer.
- 14 four-byte words = 56 bytes: isFake, snapshot pin, fake slot/CDB,
  prefetch-valid, RESP, argc/argv length, pending list counts,
  authentication, slot/cluster slot, and tomo bucket.
- Four bytes = tid, running_tid, io_flags, and buf_encoded.
- Payload is 308 bytes; 4 bytes round to 8-byte alignment and 8 bytes remain
  reserved, producing exactly 320 bytes.

All 13 GET regions collapse into the first five 64-byte regions. A separate
clientExecTail can be laid out at 840 bytes. Its payload is the remaining
805 current field bytes, including the existing clientCold pointer. The core
adds a new 8-byte tail pointer, but the current struct has 55 padding bytes:
308 bytes of core payload + 805 bytes of tail payload = 1,113, leaving 47
bytes for alignment/reserve inside a 320 + 840 = 1,160-byte combined budget.
Thus a real or generic client can retain the current requested-byte total,
although it uses two allocations; a common express fake allocates only the
320-byte core.

At pipeline depth 32, struct payload per connection changes from
32*1,160 = 37,120 bytes to 32*320 = 10,240 bytes, saving 26,880 bytes. At 200
connections that is 5,376,000 bytes, or 5.13 MiB, before allocator-class
effects. With the default classes, the comparison is 32*1,280 = 40,960 usable
bytes versus 10,240, saving 30,720 per connection and 6,144,000 bytes
(5.86 MiB) at 200 connections. This matters on a single shared 32 MiB L3 even
when the workload is not miss-bound.

The cost is substantial:

- Direct client field references in networking, parsing, replication,
  modules, blocking, and diagnostics need core/tail accessors.
- The express whitelist must prove that a command cannot reach a tail field.
  A generic fake allocates or retains the tail before dispatch.
- The GET/SET express retire path needs a specialized reset that clears only
  the core. Treating deferred_reply_errors, cur_script, duration, and similar
  omitted fields as zero without an eligibility proof would turn stale state
  into corruption.
- The tail cannot be freed while a worker, completion drain, module callback,
  or QSBR-protected action can still name it. IO ownership and the existing
  completion release/acquire edge should remain the lifetime boundary.
- Real IO parsing pays a tail indirection for parser-only fields. Measure IO
  headroom and instructions as well as EX.

This proposal creates no stage, queue, cache-resident tier, hot-key pool, or
AMAC path. The same IO thread dispatches the same core directly to the same EX
worker, and the same completion returns to IO.

The confirmation measurement is:

1. Add static assertions for core 320, tail 840, and the hot offsets.
2. Count express commands that allocate or read a tail; a minimal GET/SET run
   must remain zero.
3. Compare instructions/op and cycles/op for p32 GET first. The primary
   success criterion is at least 0.5% fewer retired instructions or a
   reproducible 1% throughput improvement. LLC misses are diagnostic only.
4. Verify 5–6 physical client lines with sampled data addresses or cache-line
   access tracing; do not infer it from five logical regions alone.
5. Run atomic mixed reads, cross-shard groups, cluster mode, modules, blocking,
   and disconnect/reuse stress before accepting any lifetime change.

If instructions and throughput are flat, the smaller fake-ring footprint is
still real but does not justify the accessor complexity.

## 2. Epoch-MVCC and atomic structures

### Exact structures

#### redisObject / kvobj header

Current sizeof(redisObject), sizeof(robj), and sizeof(kvobj) are all 24 bytes:

| Offset | Bytes | Contents |
|---:|---:|---|
| 0 | 4 | type:3 + encoding:4 + refcount:23 + iskvobj:1; one bit unused |
| 4 | 4 | metabits:8 + lru:24 |
| 8 | 8 | ptr |
| 16 | 8 | vmeta |
| 24 | 0 | end |

It occupies one layout region, but it has grown by 8 bytes from the 16-byte
layout still shown in object.c comments.

#### tomoOwnerOp

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | kv |
| 8 | 8 | seq |
| 16 | 4 | kind enum |
| 20 | 4 | tail padding |
| 24 | 0 | end |

Two embedded operations consume 48 bytes.

#### tomoVerMeta

Current sizeof(tomoVerMeta) is 120 bytes, align 8, two layout regions:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | version_seq |
| 8 | 8 | committed_head |
| 16 | 4 | version_order |
| 20 | 1 | version_tombstone |
| 21 | 1 | version_reservation |
| 22 | 1 | stamp_state |
| 23 | 1 | retire_state |
| 24 | 1 | detached |
| 25 | 3 | padding |
| 28 | 4 | owner_ops_pending |
| 32 | 8 | version_prev |
| 40 | 8 | committed_prev |
| 48 | 8 | version_kvs |
| 56 | 8 | version_db |
| 64 | 8 | reservation_owner |
| 72 | 24 | owner_op[0] |
| 96 | 24 | owner_op[1] |
| 120 | 0 | end |

The normal allocator class is 128 bytes, exactly two lines when class-aligned.
The first region holds the read cursor, sequence/order/state, both chain
links, and store/database pointers. The second holds reservation ownership and
both owner jobs. A stable versioned read normally needs only the first region;
version creation and STAMP/PRUNE lifetime handling touch both.

committed_head itself is 8 bytes at vmeta offset 8. It is authoritative only
in the physical head, but every vmeta carries the field because any version
can become the physical head and inherit/publish the cursor.

#### Per-key signature and publication records

The atomic group’s incremental per-key arrays are:

- csMsetInstall: pointer 8 + owner int 4 + install_order uint32 4 = 16 bytes.
  An MSET8 array is 128 bytes, two regions.
- Full key hash: 8 bytes/key. Eight hashes are exactly one line.
- key_sig: 8 bytes/group, plus key_h pointer and key_h_n/padding in csGroup.
  For MSET8, installs + hashes + signature are 200 bytes, or 25 bytes/key
  before the group’s fixed fields.

csReadKeys is 144 stack bytes: signature 8 + count 4 + padding 4 + 16 hashes
(128), or three regions.

csPubRec is 152 bytes:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | tag |
| 8 | 8 | key_sig |
| 16 | 4 | key_h_n |
| 20 | 4 | padding |
| 24 | 128 | key_h[16] |
| 152 | 0 | end |

For an eight-key record, tag/signature/count plus eight hashes touch the first
88 bytes, normally two or three physical lines depending on the record’s
position. csMsetPub has a 16-byte aligned header followed by records. At
capacity 32 it requests 16 + 32*152 = 4,880 bytes, or 77 layout regions. This
is lazy per connection, not per command.

The hash vector and detached publication copy are lifetime data, not an
optional cache hint. A pointer from csPubRec back into csGroup would be a
use-after-free: csReassemble can free the group while the publication window
is still represented by the connection-owned record.

#### QSBR records

flatRetireNode is the minimum ordinary two-pointer list node:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | masked_kv/payload |
| 8 | 8 | next |
| 16 | 0 | end |

Four nodes have 64 bytes of capacity if contiguous, but recycled nodes are
independent allocations and one retire can touch one physical line. The
worker-local pool removes steady malloc/free; it does not remove the two
pointer stores.

flatBatch has a 24-byte fixed header:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | head |
| 8 | 4 | nworkers |
| 12 | 4 | padding |
| 16 | 8 | next |
| 24 | variable | uint64_t arr[] |

Let S = IO + EX + 1 and W = ceil(S/64). Current requested size is
24 + 8*(2*S + W). With eight pinned service cores, S=9 and W=1 for every
IO/EX split, so the request is 176 bytes/three regions, normally class 192.
It stores EX worker snapshots only for the live EX count, but reserves S
words for that subarray so all three subarrays share one stride.

#### Shared commit/admission lines

commit_seq_line is correctly 64 bytes and the atomic admission counter is
correctly 64 bytes.

commit_ctl is not. Its source pad is calculated as 64 - 8 - 1 - 16 = 39
bytes, but the compiler inserts seven bytes between the one-byte atomic_flag
and the first pointer:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | next_seq |
| 8 | 1 | lock |
| 9 | 7 | implicit pointer padding |
| 16 | 8 | head |
| 24 | 8 | tail |
| 32 | 39 | explicit pad |
| 71 | 57 | tail padding forced by align(64) |
| 128 | 0 | end |

Thus sizeof(commit_ctl) is 128, not 64. Only its first line is live, so this
does not add a per-command line touch. Reordering to next_seq, head, tail,
lock, then 39 bytes of pad yields exactly 64.

### Version-bag footprint

The table points at a physical install-ordered bag. Each versioned member has:

- its ordinary kvobj allocation;
- one separately allocated 120-byte vmeta (normally 128 usable bytes);
- version_prev for physical order;
- committed_prev for committed order; and
- the physical head’s committed_head cursor.

A raw pre-epoch tail has no vmeta and is implicit sequence zero. A freshly
versioned absent key can therefore add only the vmeta over an ordinary stored
key: 120 requested/128 usable bytes. An overwrite retains the predecessor
until prune and both grace periods complete. With no metadata and SDS5 key,
an embedded kvobj request is:

24 + (1 + K + 2) + (V + 4) = 31 + K + V bytes.

The absolute K=0,V=0 predecessor is 31 requested/class 32. Once the ordinary
path’s predecessor grace would have ended, the smallest overwrite-bag delta is
120 + 31 = 151 requested and normally 128 + 32 = 160 usable bytes. For the
warm 9–12-byte keys and a 32-byte value, each kvobj is 72–75
requested/class 80, so a one-version-plus-raw-predecessor bag occupies
80 + 80 + 128 = 288 usable bytes versus 80 for the ordinary live key.

Every additional version adds its kvobj class plus another 128-byte vmeta
until pruning removes it.

### Lines touched by reads

For a no-metadata, warm-key, embedded p32 value and an ideal line-aligned
allocation:

| Read shape | Table | kvobj/value | vmeta | global snapshot | Total |
|---|---:|---:|---:|---:|---:|
| Raw/non-atomic current value | 1 | 2 | 0 | 0 | 3 lines |
| Versioned, committed winner is physical head | 1 | 2 | 1 first-vmeta region | 1 commit_seq line | 5 lines |
| Versioned, winner is first predecessor | 1 | 1 physical-head header + 2 winner lines | 2 first-vmeta regions | 1 | 7 lines |

Every further skipped committed candidate adds one candidate header line and
one first-vmeta line. The measured mean resolver walk of 1.03 says the common
cost is the fixed 5-line shape, not a deep chain. A command with an already
pinned snapshot still touched the shared snapshot line when that pin was
drawn; kvobjVersionAt itself can then avoid reloading it.

This is two extra line accesses on the common versioned read, but more
importantly it is dependent acquire loads and branches on every versioned
read. Deriving committed_head by scanning the physical bag would trade one
stored word for more per-command work in exactly the instruction-bound regime
described by the measurements. I reject it.

### Lines touched by writes

There is no honest single “unique lines” number for a versioned write: STAMP
and PRUNE revisit the same table slot and head at different times, key-to-owner
mapping changes queue lines, and chain length changes maintenance walks.
Counting temporal line-touch events is more useful because those revisits are
the instruction and coherence tax.

For the first versioned overwrite of a raw, embedded p32 key, excluding input
argv/reply, allocator internals, and group/queue shared lines:

| Phase | Ordinary overwrite | Atomic overwrite |
|---|---:|---:|
| Install | table slot 1 + old header/SDS header 1 + new kvobj bytes 2 = 4 | same 4 + two vmeta initialization regions = 6 |
| Retirement record stores | one record-write event = 1 | prune anchor + physical value + vmeta = 3 record-write events (one to three distinct physical lines) |
| STAMP maintenance | 0 | re-probe slot + head header + first vmeta region = at least 3 |
| PRUNE/grace maintenance | 0 | owner descriptor region + re-probe slot + head/vmeta + raw predecessor/header = at least 5 before deeper walks |
| Lower bound | about 5 temporal storage-line visits | at least 17, before owner queues and group/global control |

Packing recycled retire nodes can make multiple node writes share a resident
line, so the table is not a miss prediction. It is an inventory of repeated
line-sized state accesses. Atomic MSET8 additionally touches the two-line
install array, one-line hash vector, commit control/frontier lines, admission
line, and owner queue lines. The previous write audit measured the consequence
more directly: roughly 2,900 extra retired instructions/key, about 74%
instruction work and 26% lost IPC (consistent with the supplied 70/30
summary), three retire records/key, and about 5.1 prune-walk steps/key.

The important negative result is also preserved: version installation,
including the separate vmeta allocation, measured 50.8 ns versus 62.8 ns for
ordinary install. Shrinking metadata can reduce bytes and stores, but the
allocation by itself is not a demonstrated bottleneck.

### How much vmeta bookkeeping can be derived?

Current vmeta bytes divide as follows:

| Purpose | Bytes | Derivable? |
|---|---:|---|
| version_seq + committed_head | 16 | No without adding read scans or losing publication ordering |
| version_order and five state bytes | 9 plus 3 padding | version_order survives group teardown; state-byte packing saves no allocator class and complicates races |
| owner_ops_pending | 4 | No; it is the lifetime pin preventing vmeta free while queued jobs name it |
| version_prev + committed_prev | 16 | No; they represent different orders |
| version_kvs + version_db | 16 | version_kvs appears derivable, but db->keys is swapped in this tree; unsafe without a stronger lifetime invariant |
| reservation_owner | 8 | No current proof |
| owner_op[2] | 48 | kv and seq are duplicated; job identity/kind can be encoded instead |

So 32 of the 120 bytes are representational duplication that a tagged-job
design can remove while retaining explicit store ownership. Forty bytes are
derivable only if version_kvs also passes the separate DB/store lifetime
proof. The remaining 80 bytes are either semantic state or alignment at the
proposed representation.

The representationally duplicated owner-job bytes can be reduced by encoding
the kind in the existing tagged owner-queue pointer. A vmeta is at least
8-byte aligned. Bit 0 already distinguishes an owner job from a client; bits
1–2 can encode STAMP/PRUNE/CANCEL while the remaining bits address the vmeta.
The vmeta then stores one owner_kv and one pending_seq. The two queue entries
can coexist because their kinds live in the queue words, not in a mutable
shared descriptor.

Keeping both version_kvs and version_db, an 88-byte target is:

| Offset | Bytes | Proposed field |
|---:|---:|---|
| 0 | 8 | version_seq |
| 8 | 8 | committed_head |
| 16 | 8 | version_prev |
| 24 | 8 | committed_prev |
| 32 | 8 | version_kvs |
| 40 | 8 | version_db |
| 48 | 4 | version_order |
| 52 | 5 | state bytes |
| 57 | 3 | padding |
| 60 | 4 | owner_ops_pending |
| 64 | 8 | reservation_owner |
| 72 | 8 | owner_kv |
| 80 | 8 | pending_seq |
| 88 | 0 | end |

That is 120 -> 88 requested bytes and class 128 -> class 96, but still two
cache-line regions. If a proof establishes that every queued/pruning vmeta’s
version_db remains alive and version_db->keys still names the exact original
store, version_kvs can be removed and the layout repacked to 80 bytes/class
80. The current DB-swap assignments mean that proof cannot be assumed.

Correctness obligations for even the 88-byte option are:

- pending_seq and owner_kv remain immutable until both tagged jobs consume
  them;
- STAMP cannot clear shared state before PRUNE runs;
- CANCEL’s one-job case decrements owner_ops_pending exactly once;
- owner_ops_pending release/acquire still pins vmeta across every queue and
  grace edge;
- queue decoding masks all three tag bits before dereference; and
- promotion cannot retire vmeta while a tagged queue word can still name it.

Failure is a use-after-free, so this remains a described option. Measurement
must show the expected vmeta class change, unchanged STAMP/PRUNE/cancel counts,
and at least 0.3% fewer atomic-ON instructions/op without changing atomic-OFF.
Anything smaller is not worth this proof burden.

### Per-key signature: what is and is not redundant

install_order in csMsetInstall is exactly its array index in current code.
Removing it saves its store/load/assert work, but the struct stays 16 bytes due
to 8-byte alignment. The semantic copy in vmeta->version_order cannot be
removed: it remains after csGroup is freed and orders duplicate-key installs.

key_sig can be recomputed from key_h, but that costs up to 16 loads/ORs on
every own-read check and fails the filter-only representation when key_h_n is
zero. In this instruction-bound system, storing the 8-byte group signature is
the right trade.

The 64-bit exact hashes cannot be shortened without introducing collision
false negatives into a correctness gate. The detached csPubRec copy cannot be
a group pointer because the group can already be freed. The only clearly
derivable publication field is tag: FIFO position identifies the record, but
tag is a cheap assertion of that lifetime discipline. Removing it changes
152 -> 144 bytes and saves four regions in a depth-32 ring, but not the
two-to-three lines touched by an eight-key record. I think it will not pay.

### QSBR records and lifetime

flatRetireNode cannot become smaller than 16 bytes while it remains an
independent singly-linked payload record. Reusing a retired kvobj’s first word
as the list link is unsafe: a QSBR reader may still be dereferencing the
object, which is exactly why it was retired. Reusing vmeta space before
owner_ops_pending reaches zero or before its metadata grace completes has the
same use-after-free failure mode.

An intrusive special-record design after the final pin drops might remove the
two atomic-only 16-byte nodes for physical/vmeta retirement, but it would need
to prove that no stale reader observes the overwritten word and that batch
discard can distinguish every payload. The current node pool has already
removed the steady allocator pair and previously measured about +2.6% SET.
I would not trade the simple lifetime proof for at most 32 transient bytes/key
without a profile naming retire-node stores.

The flatBatch stride can safely be compacted because only EX snapshots need EX
slots:

proposed bytes = 24 + 8*(EX + (IO+EX+1) + ceil((IO+EX+1)/64)).

For eight service cores, that is 144 bytes at io3/ex5, 136 at io4/ex4, 128 at
io5/ex3, and 120 at io6/ex2. The current code already writes only EX live
snapshots, so this removes allocation slack, not loop work. Earlier QSBR
batching changed 8.9 to 83 objects/batch and 303 to 119 ns/pass for only about
+1% throughput. This smaller header change will not pay as a throughput
project.

## 3. Stored kvobj, robj, and SDS thresholds

### Current exact formulas

For K < 32, an SDS5 key needs K+2 bytes: one-byte header, K bytes, and NUL.
The kvobj adds another one-byte “key SDS header size” field, so stored key
bytes are K+3.

An embedded SDS8 value needs V+4 bytes: len, alloc, flags, V bytes, and NUL.

With no key metadata:

- standalone EMBSTR robj request = 24 + (V+4) = 28+V;
- stored embedded kvobj request = 24 + (K+3) + (V+4) = 31+K+V;
- stored RAW wrapper request = 24 + (K+3) = 27+K, plus the separate value SDS.

Every key metadata bit adds another 8 bytes before the kvobj. The 192-byte
embed gate deliberately omits metadata, so the actual allocation can exceed
192 and cross another allocator class even when the gate accepts it.

OBJ_ENCODING_EMBSTR_SIZE_LIMIT is 44. At V=44 the standalone request is
28+44 = 72 bytes. The final occupied byte is offset 71, which explains the
“about 71” wording, but sizeof-style allocation arithmetic is 72. It is not a
64-byte object anymore. V=36 is the largest current standalone value whose
request is at most 64.

For warm 9–12-byte keys, current stored requests and default jemalloc classes
are:

| Value V | K=9 | K=10 | K=11 | K=12 |
|---:|---:|---:|---:|---:|
| 24 | 64 / class 64 | 65 / class 80 | 66 / class 80 | 67 / class 80 |
| 32 | 72 / class 80 | 73 / class 80 | 74 / class 80 | 75 / class 80 |
| 44 | 84 / class 96 | 85 / class 96 | 86 / class 96 | 87 / class 96 |
| 64 | 104 / class 112 | 105 / class 112 | 106 / class 112 | 107 / class 112 |
| 71 | 111 / class 112 | 112 / class 112 | 113 / class 128 | 114 / class 128 |

There are two real boundary problems:

- At V=24, one byte of common key length changes a one-line/class-64 request
  into a two-line/class-80 request.
- At V=71, common K=9–10 and K=11–12 split across the 112/128 allocator-class
  boundary. Both still require two ideal physical lines, but the latter wastes
  another 14–15 usable bytes.

The current 192-byte fit rule gives maximum embedded V of 152, 151, 150, and
149 for K=9,10,11,12 respectively. The stale “up to 170-byte copy” comment is
not true for these common keys with the 24-byte header.

### Proposed 16-byte ordinary robj with fixed kvobj vmeta prefix

The layout-preserving concept, still subject to the audit below, is:

ordinary object:

    [16-byte robj header][optional embedded standalone value]

stored object:

    [key metadata][8-byte vmeta slot][16-byte kvobj header][key][embedded value]

The vmeta slot is immediately before the kvobj pointer, so kvobjVmeta is still
one fixed-displacement atomic load. It does not need a popcount or metadata
walk. kvobj metadata accessors skip the slot, and allocation/free/defrag
accessors subtract both metadata and the slot.

For M metadata bytes, current key/value start is:

M + 24.

Proposed key/value start is:

M + 8 + 16 = M + 24.

Thus every stored kvobj request, key offset, value offset, embed result, and
cache-line boundary in the preceding table remains byte-for-byte unchanged.
The 192-byte gate must explicitly add the 8-byte stored prefix after
sizeof(kvobj) falls to 16, preserving current policy.

Ordinary object effects are:

- common K=9–12 embedded key operands: 28+K = 37–40 bytes/class 48 currently;
  20+K = 29–32 bytes/class 32 proposed, saving 16 usable bytes and one
  vmeta=NULL store per parsed object;
- standalone V=44 EMBSTR: 72/class 80 currently; 64/class 64 proposed,
  restoring the original one-line intent;
- standalone V=32 EMBSTR: 60/class 64 currently; 52/class 64 proposed, fewer
  bytes but the same allocator class; and
- RAW object shell: 24 requested/class 32 currently; 16/class 16 proposed,
  saving 16 usable bytes while leaving the SDS allocation unchanged.

Required audit surface includes every direct ->vmeta use, initStaticStringObject,
object allocation/free/accounting, kvobj metadata transition, EXPIRE realloc,
RDB metadata copy, defrag, DB swap helpers, and module metadata/DMA paths. The
slot has exactly the same acquire/release lifetime as the current header word;
only its address changes. Active version and QSBR rules do not change.

This differs materially from the rejected full-vmeta embed:

- it relocates only the existing 8-byte pointer word;
- stored-key total bytes and version-metadata allocation/retirement are
  unchanged;
- promotion retains no extra 112-byte prefix; and
- ordinary transient/command objects, not version bags, receive the shrink.

The falsifier is strict. On p32 GET, allocator histograms must show common key
objects moving 48 -> 32 and instructions/op must fall. Atomic mixed-read and
MSET8 instructions/op must not regress by more than 0.5%. Stored kvobj usable
classes and all metadata/defrag correctness tests must be unchanged. If the
fixed negative-displacement vmeta load costs more than the removed object
stores/classes save, reject it.

### Should the EMBSTR limit change independently?

Lowering 44 to 36 merely forces values 37–44 back into two allocations. Their
current 65–72-byte request already consumes class 80; a separate 24-byte
object/class 32 plus SDS/class 48 consumes the same 80 usable bytes with an
extra allocation. It should not pay.

If robj remains 24 bytes, raising 44 to 52 fills the already-paid class 80:
28+52 = 80. Values 45–52 currently use a class-32 object plus a typically
class-64 SDS, 96 usable bytes over two allocations. This could help a workload
with a spike in exactly that band, but it changes the long-standing boundary
between immutable EMBSTR and mutable RAW. Every caller that assumes values
above 44 are RAW would need review.

The tree’s own performance history is a warning against threshold folklore:
the RAW-value-embed discriminator was +18.4% at 64-byte values but -0.3% at
240 bytes. The current 192-byte stored-value threshold captures the demonstrated
small-value win and stops before the measured large-value wash. I would keep
192 and make no standalone limit change unless an allocation histogram shows
material traffic at 45–52. If the 16-byte robj proposal lands, the present
limit of 44 already returns to an exact 64-byte request and should remain.

## What I think will not pay

- Full tomoVerMeta embedding in kvobj: already rejected by measurement; no new
  fact changes it.
- Deriving committed_head by scanning: saves 8 bytes only by adding dependent
  work to every versioned read.
- Removing or shortening exact key hashes: either adds repeated OR/compare
  work or creates correctness false negatives.
- Pointing csPubRec at csGroup: a direct use-after-free in the detached
  publication window.
- Intrusive reuse of a kvobj or vmeta before its grace/pin ends: a direct
  use-after-free, not an optimization.
- Shrinking flatRetireNode below two pointers: incompatible with its current
  independent list-node role.
- flatBatch stride compaction, commit_ctl padding repair, or csPubRec.tag
  removal as throughput projects: they save cold/capacity bytes but no common
  line touches.
- Lowering EMBSTR to force 64 bytes while robj is still 24: same usable bytes,
  more allocations.
- Any extra pipeline stage, queue hop, cache/memory tier, hot-item pool, or
  AMAC scheme. Besides violating the owner rule, the supplied measurements
  point away from miss-hiding as the limiting resource.

## Recommended measurement order

1. Prototype client hot-field packing without changing stage ownership. First
   use a full-size reordered client to isolate 13 -> 5 layout-region packing;
   then enable the 320-byte fake core/tail split to isolate resident footprint
   and specialized reset. Measure instructions/op at each step.
2. Prototype the 16-byte ordinary robj/fixed vmeta-prefix slot separately.
   Measure p32 GET and SET, then atomic mixed read/MSET8 as regression cells.
3. Only if atomic metadata remains visible in an instruction profile, test the
   88-byte tagged-owner-job vmeta. Do not attempt the 80-byte version until the
   DB/store lifetime proof is written down and stressable.
4. Fold the padding and zero-footprint cleanups into unrelated correctness
   work; do not spend a benchmark campaign on them.

For all cells, use same-binary toggles or tightly paired builds, report
instructions/op and cycles/op first, and treat throughput movement below the
box’s run-to-run noise as a wash. LLC events can explain a result but must not
be the success criterion on this measured workload.

## Verification performed

- Read the current client/fake allocation, slim transfer, worker prefetch,
  execution, reply, completion, and reset paths.
- Reconstructed client, clientCold, redisObject, tomoOwnerOp, tomoVerMeta,
  signature/publication, retire-node, batch, and commit-control layouts from
  the declarations.
- Read the version resolver, version installation, STAMP/PRUNE publication,
  two-stage retirement, promotion, DB-store swap, and QSBR readiness paths.
- Read the relevant history for the cold-client split, RAW-value embedding,
  atomic write-cost decomposition, QSBR batching, and rejected vmeta embed.
- Confirmed that every recommendation preserves the existing IO/EX split and
  adds no stage or queue.
- Per the absolute constraint, ran no build, compiler, server, test, or
  benchmark.
