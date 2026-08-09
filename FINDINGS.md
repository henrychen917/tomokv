# Inter-thread message-passing audit

Static audit of branch `2s-audit-msgpass` at `d7d7d137c`, for the specified Ryzen 7 7700X: eight
cores, one CCD, private L1/L2, shared 32 MiB L3, and 64-byte cache lines. I did not compile, run,
test, or benchmark anything. All wins below are estimates to be tested later; none is presented as
measured.

The architectural constraint is preserved throughout: IO remains the producer/coordinator, EX
remains the sole data owner/executor, and the existing IO/EX boundary remains the only stage
boundary. Nothing below adds a cache/memory tier, hot-item pool, stage, queue hop, or AMAC.

## Bottom line

- The dispatch ring is not bloated. Its entry is one 8-byte `client *`, already denser than uTPS's
  16-byte queue record. The misleading part is that our 8 bytes are only a handle to a large,
  pointer-rich graph, whereas the useful portion of the uTPS request is in its 16 bytes.
- On the default x86-64 build, the fixed carrier behind one ring entry is **1,336 bytes for GET**
  and **1,344 bytes for SET**, before key/value objects and before the reusable 1 KiB fake reply
  buffer. The formula is `8 queue + 1,160 client + 152 pendingCommand + 8*argc argv`.
- A line-aligned accounting of a steady small GET/SET finds **23 distinct boundary-related cache
  lines for GET and 24 for SET**, before any DB/table/value lines. The full-state move adds one.
  Allocation alignment and an EMBSTR straddling a line can add lines; batching amortizes the queue
  control lines over several commands.
- There is **no false sharing between `exQueue.head` and `exQueue.tail`**. They are explicitly on
  different, aligned 64-byte lines. `retired` correctly shares the consumer's head line;
  `cached_head` and `staged_tail` correctly share the producer's tail line.
- There are no per-slot ready flags in the dispatch ring. Eight 8-byte jobs share each slot line.
  Producer writes to later slots can overlap a consumer reading earlier slots on the same line, so
  adjacent slots can false-share. Padding them would be much worse than the disease.
- The reply-ready bytes do false-share on this machine: all 32 bytes for a connection share one
  line and, because one CCD resolves `num_cdb=1`, different EX cores can write different bytes in
  that line while IO clears them. This is real false sharing, but it is also excellent packing;
  spreading it out is unlikely to win on a one-CCD/shared-L3 machine.
- The best low-risk shrink is to make four sequential 64-bit handoff fields share one lifecycle
  word. The next is to remove the real-only `fakeClients[32]` array from every fake. The highest
  upside is a compact descriptor for the common reply-less scatter sub, but that requires a
  substantial API refactor.
- The **largest reducible carrier package** is the cross-shard sub fake: 1,160-byte client shell plus a
  1,024-byte reply buffer and 48-byte list, or 2,232 bytes/36 nominal lines per sub, even for
  coalesced MGET/MSET/DEL/EXISTS paths which do not build a sub reply. The largest removable field
  in the ordinary fake is the real-only 256-byte `fakeClients[32]` array (four lines of footprint,
  spanning five relative lines at its current offset). The 1 KiB fake buffer is
  the largest resident allocation, but its unused bytes are not touched, so merely shrinking it is
  not a good throughput proposal.

The measured facts in the brief materially change the ranking. With workers fixed around 500
ns/op, a 21x data increase costing 3.5%, and group prefetch a wash while open 97.8% of the time,
none of the recommendations relies on turning an LLC miss into a hit. The plausible gains come
from eliminating loads/stores, pointer dependencies, allocator operations, bytes zeroed/copied,
and cache lines that are actively handed between private L2s. A 1% win is only about 5 ns/op, so
even the small estimates require clean interleaved A/Bs.

## Counting basis and exact sizes

The size model is the default LP64 build (`sizeof(void *)=sizeof(size_t)=sizeof(long)=8`, 4-byte
`int`/enum) with `LOG_REQ_RES` absent, as in the normal Makefile path. The hardware's
`CACHE_LINE_SIZE` is 64 (`src/config.h:38-43`). “Lines” below means `ceil(bytes/64)` for a
line-aligned or nominal object. `client`, `pendingCommand`, operands, buffers, and `csGroup` are not
guaranteed cache-line aligned, so a small allocation can straddle an additional physical line.
This distinction matters: footprint is exact, but a runtime physical-line count depends on the
allocator address.

| Object | `sizeof` / requested bytes | Nominal lines | Derivation |
|---|---:|---:|---|
| `exQueue` | 16,512 | 258 | 128 bytes of aligned control area plus `2048*8=16,384` job bytes |
| one dispatch entry | 8 | 1/8 line | `client *`; eight entries per line |
| `cdbSlots` | 64 | 1 | 32 atomic bytes plus 32 bytes explicit pad; alignment asserted |
| `freebackRing` | 8,320 | 130 | 128 control bytes plus `1024*8=8,192` object-pointer bytes |
| `client` | 1,160 | 19 | manual layout below; alignment 8, no line-alignment attribute |
| `pendingCommand` | 152 | 3 | 64-byte `getKeysResult`, then tail release mask and two links |
| live GET/SET argv | 16 / 24 | 1 | two/three live pointers; retained vector capacity can be larger |
| `robj` | 24 | 1 | two 32-bit bitfield words plus `ptr` and `vmeta` pointers |
| `list` / `listNode` | 48 / 24 | 1 / 1 | six pointers; three pointers |
| `csGroup` header | 576 | 9 | last fixed fields end at 572; 8-byte alignment puts `inl[]` at 576 |
| `tomoOwnerOp` | 24 | 1 | `kv` 8 + `seq` 8 + enum 4 + 4 pad |
| `tomoVerMeta` | 120 | 2 | fixed state/pointers through offset 71 plus two 24-byte owner ops |
| `payloadHeader` | 9 | 1 | packed `size_t` plus byte type |
| `bulkStrRef` | 42 | 1 | packed: pointer 8 + count 4 + prefix 24 + CRLF 2 + owner 4 |
| `clientReplyBlock` | 24 | 1 | two `size_t`, one byte, tail padding before flexible data |

`sizeof(client)==1,160` follows directly from the declaration in `src/server.h:1775-2020`:

| Byte range | Bytes | Contents |
|---|---:|---|
| 0..271 | 272 | fake identity, parent, and `fakeClients[32]` |
| 272..383 | 112 | real ring/atomic control through `reply_cdb` |
| 384..503 | 120 | fake/scatter/routing/prefetch context |
| 504..919 | 416 | common execution-client state |
| 920..991 | 72 | three intrusive `listNode`s |
| 992..1159 | 168 | reply/statistics/tail routing fields |

The current `robj` count must use this tree, not older audit notes that still describe the
pre-`vmeta` 16-byte object. An argument of length `L<=44` is EMBSTR and requests
`sizeof(robj)+sizeof(sdshdr8)+L+1 = 24+3+L+1 = 28+L` bytes. A 32-byte key or value therefore
requests 60 bytes. Above 44 bytes, the consumer follows a 24-byte `robj` allocation and a separate
SDS allocation of `header(L)+L+1` bytes.

`sizeof(csGroup)==576` can be checked at its tail: `sort_ctx` is at 544, `sort_stage` at 552,
`sort_fields` at 560, `inl_cap`/`inl_used` at 568/570, and the 8-aligned flexible `inl[]` begins at
576 (`src/server.h:2154-2322`). Consequently the existing exact allocations for the documented
four-key/four-shard common cases are:

- MGET(4): `576 + 192 inline = 768` bytes = 12 lines.
- MSET(4): `576 + 128 inline = 704` bytes = 11 lines.

## Dispatch queue: production, consumption, and sharing

### Layout and capacity

`exQueue` in `src/server.h:2482-2522` lays out as follows:

| Offset | Line | Field | Owner |
|---:|---:|---|---|
| 0 | 0 | atomic `head` | EX consumer writes |
| 4 | 0 | `cached_tail` | EX consumer only |
| 8 | 0 | atomic `retired` | EX consumer writes after execution |
| 64 | 1 | atomic `tail` | IO producer publishes |
| 68 | 1 | `cached_head` | IO producer only |
| 72 | 1 | `staged_tail` | IO producer only |
| 128 | 2..257 | `jobs[2048]` | IO writes, EX reads |

The queue block is explicitly line-aligned at allocation and asserted in `initExThreads`
(`src/server.c:21650-21669`). Each embedded member that needs it is also aligned. The physical
array has 2,048 entries, but the empty/full convention sacrifices one slot, so usable capacity is
**2,047**. Runtime auto sizing is floored at 2,048 and capped by the same static maximum, so it is
2,048 in this tree (`src/server.c:5271-5302`).

### Push

IO transfers execution state from the real client to its ring fake, but does not copy operands.
`moveExecutionState[ Slim ]` moves the `pendingCommand`, `argc`, `argv`, `cmd`, accounting, and
context pointers, and clears the corresponding real fields (`src/server.c:19704-19794`). Dispatch
then stamps the worker DB, CDB, bucket/hash routing fields, and `CLIENT_EX_PENDING`, and calls
`exDispatchPush` (`src/server.c:7699-7824`).

The fast `exQueuePush` (`src/server.c:19913-19950`) does this:

1. Reads/writes producer-private state on the tail line.
2. Reads the head line only when `cached_head` says the queue might be full.
3. Stores one 8-byte fake pointer in a jobs line.
4. Advances only `staged_tail`.

`flushExQueues` later release-stores the staged frontier to `tail` and advertises this producer's
bit in the worker's `q_summary` line. That publication is once per dirty queue per parse/flush
batch, not necessarily once per command (`src/server.c:19838-19876`). Cross-shard `csPushSpin`
publishes immediately because the coordinator is waiting for the scatter result.

### Pop and retire

`exQueuePopBatch` (`src/server.c:20004-20034`) consumes up to 16 pointers:

1. It reads/writes the head line.
2. It acquire-loads the tail line only when its cached tail says empty.
3. It copies the pointer run from jobs lines with one or two `memcpy`s.
4. It release-stores `head` once for the batch.

One pointer always occupies one jobs line. A 16-entry pop touches two jobs lines if it starts at an
8-slot boundary and three otherwise. After all popped commands execute, EX release-stores
`retired` once for the batch on the already-owned head line (`src/server.c:21069-21078`).

The queue portion of a command's batch therefore names four shared lines: head, tail, jobs, and
`q_summary`. Only the jobs line is intrinsically per command. Tail publication, summary
advertisement/harvest, head advance, and retirement are batch-amortized. The producer's cached-head
scheme also means the head line normally does not transfer back to IO until the ring approaches
full.

### False-sharing verdict

- **Head versus tail: none.** They cannot occupy the same line. The padding/alignment is correct.
- **Owner-private cached indices: none.** Each is deliberately beside the index written by the
  same owner.
- **Per-slot flags: none exist.** Tail publication makes all earlier job slots valid.
- **Adjacent jobs: possible false sharing.** A jobs line contains eight independent commands. After
  publishing a partial line, IO can write later slots in that line while EX reads earlier slots.
  The same packing also hands eight messages over with one line, so this is a favorable trade unless
  address-level measurements prove otherwise.
- **`q_summary`: intentional multi-writer sharing.** IO producers `fetch_or` different bits and EX
  exchanges the word. This is genuine coherence traffic, but splitting the word would restore a
  dense consumer scan or add more summary work.

The comment saying jobs are co-located with the tail line is stale: the actual aligned array starts
at offset 128, on the following line. The implementation is correct; only the prose is wrong.

## What one command actually passes

The queue contains only this:

```
exQueue.jobs[i] (client *)
        |
        +--> fake client (1,160 B shell)
                |-- parent ------------> real client
                |-- current_pending_cmd -> pendingCommand (152 B)
                |-- argv --------------> robj * vector
                |                           |-- argv[1] -> key robj -> key SDS bytes
                |                           `-- argv[2] -> SET value robj -> value SDS bytes
                |-- cmd ---------------> global redisCommand
                |-- db ----------------> worker DB
                `-- buf/reply ---------> reply bytes/list built by EX
```

The fixed envelope, excluding operands and reusable reply backing, is:

| Command | Queue | Fake | Pending | Live argv | Total | Relative to uTPS 16 B |
|---|---:|---:|---:|---:|---:|---:|
| GET | 8 | 1,160 | 152 | 16 | **1,336 B** | 83.5x |
| SET | 8 | 1,160 | 152 | 24 | **1,344 B** | 84.0x |

This is a footprint/representation comparison, not an allocation-per-op claim: ring fakes,
pending commands, and argv capacity are reused. It is nevertheless the graph whose lines are
touched and whose pointers serialize consumer work.

uTPS spends its 16 bytes on an 8-byte inline key/hash, type, size, and a 32-bit backing-buffer slot;
the consumer receives the discriminant and key token without first loading a request object. Our
8-byte entry contains none of those facts—it must first load the fake, then argv, then the key
object/bytes. We also must preserve real Redis client/command context, so a 16-byte universal
replacement is not credible without replacing the stock `client *` execution interface. The useful
target is therefore fewer lines and dependencies behind the existing pointer, plus a compact
specialization only for already-open-coded scatter semantics.

For a 32-byte key, add a 60-byte EMBSTR allocation. For SET with a 32-byte value, add another 60
bytes. Thus a concrete minimal GET32 carrier is 1,396 bytes and SET32/32 is 1,464 bytes, excluding
the global interned command token, allocator size-class slack, and reply backing.

### Inline fields versus pointers

| Item | Representation at the boundary | Consequence on EX |
|---|---|---|
| fake itself | pointer in queue | first dependent load |
| `argc` | inline in fake | no chase |
| `argv` | pointer | chase vector, then each `robj *` |
| key/value bytes | not inline in fake or queue | EMBSTR: inside the pointed-to robj allocation; RAW: another SDS pointer/chase |
| single SET value | pointer; no dispatch copy | EX encodes/adopts/copies it as command semantics require |
| `tomo_bkt` | inline 32-bit integer | routing bucket already computed by IO |
| `tomo_key_h` | inline 64-bit XXH routing hash | used by IO reorder/dependency logic before queueing |
| `tomo_bkt_ptr` | pointer to `argv[key]->ptr` | pointer-identity guard before reusing `tomo_bkt` |
| `prefetch_key_hash` | inline 64-bit dict hash | computed by EX, then consumed by the command lookup |
| `prefetch_dict` | pointer | extra dictionary chase on the dict-backed path |
| `prefetch_bucket_idx` | inline machine word | indexes the dict table |
| `cmd`, `db`, `parent`, `current_pending_cmd` | pointers | separate dependent metadata loads |

The routing XXH hash and dict hash are not interchangeable today: they serve different tables and
hash functions. Removing one merely because the group prefetch was a wash would conflate
functional hash reuse with speculative prefetching. The useful shrink is to reuse their storage at
non-overlapping lifecycle points, not to recompute either hash.

## Reply path

For an ordinary worker-routed command, **EX builds the reply**, not IO. It writes the fake's
separate 1 KiB starting buffer or reply list, saves `(parent,slot)` locally, and release-stores the
parent's ready byte after finishing the batch (`src/server.c:21030-21078`). IO acquire-loads that
byte in ring order, then `AddReplyFromClient` copies a small buffer, swaps eligible large equal-size
buffers, and O(1)-joins reply-list blocks (`src/server.c:3545-3792`,
`src/networking.c:1874-1974`). IO then clears the byte and calls `commandProcessed(fake)`.

On this one-CCD machine, one real client gets exactly one 64-byte `cdbSlots`. Its 32 ready bytes
share the line. Different workers completing different slots therefore invalidate the same line,
and IO's clear is another writer. There is no index-layout bug—the array is manually aligned and
padded—but there is per-slot false sharing by design. The one line also lets IO test any in-order
slot without pulling one of 32 lines, which is why padding is unattractive.

For a small GET/SET, at least one reply-payload line moves EX -> IO and IO copies those useful
bytes into its real-client output. With large copy-avoidance replies, the worker instead builds a
packed 42-byte `bulkStrRef` behind a 9-byte payload header. Worker fakes are forced to put this in a
reply-list block so `listJoin` transfers one reference without duplicating it. After the socket has
sent the referenced value, IO returns the `robj *` to its owning EX through `freebackRing`.

`freebackRing` is another well-laid-out SPSC ring: head at 0, tail at 64, 1,024 8-byte object slots
at 128, total 8,320 bytes/130 lines, and 1,023 usable entries. Head/tail do not false-share. Its
adjacent object slots have the same favorable packing/potential partial-line overlap as dispatch.

For a cross-shard command the answer differs: EX subs write result slots/sub replies, but the IO
coordinator builds the final array/integer/OK reply in `csReassemble`. The group head itself is a
ring fake but is not queued; the last completing sub publishes the head's normal ready byte.

## Cross-shard/scatter path

The common coalescer builds one full fake `client` per distinct owner, puts that fake's argv in the
group bump region, and queues one 8-byte pointer to each owner (`src/server.c:11591-11807`). Each
sub points back to a shared `csGroup` through `csparent`. Workers concurrently write group result
arrays/counters, accumulate statistics, and decrement `g->pending`. The last decrementer signals
the group head's ready byte. IO then reassembles, frees/recycles subs, and frees the group.

The current 576-byte group header is a union in behavior but not in layout: atomic-MSET state,
MGET/set/zset/XREAD result pointers, two-hop state, merge-pipeline state, SORT state, and common
accounting all occupy every group even though most are mutually exclusive. `csGroupNew` zeros the
entire 576-byte header plus the exactly-sized inline tail for every cross-shard command.

Its hot synchronization fields are also scattered:

- `pending` is at offset 0.
- `rcount`/`err` are at 168/180.
- `usec` is at 504.
- `had_err`/`probe` are at 512/520.

For a multi-sub command, every worker performs a locked add to `usec` and a locked decrement of
`pending`, so at least two different group lines move among EX cores. Worse, `pending` shares its
line with immutable `nsub`, `ctype`, `nkeys`, `subs`, `head`, and key-signature fields. That is
avoidable false sharing around an unavoidable completion RMW. `csGroup` has no cache-line alignment
guarantee.

Common coalesced MGET/MSET/DEL/EXISTS subs do not use their 1 KiB reply buffer or list to return a
result: MGET copies SDS values into `g->mget_vals`, MSET produces the final `+OK` on IO, and
DEL/EXISTS add to `g->rcount`. Nevertheless each pooled sub carries and resets the whole client
shell, buffer, and list. More complex/legacy/`CS_LOCAL` rows do build a stock client reply and need a
full fake.

Multi-hop payloads are also pointers, not inline queue data. Examples include `h2_payload` SDS,
MGET SDS result copies, set-member arrays, score arrays, verdict vectors, and sub argv vectors.
They are published through the sub queue/completion barriers and consumed by IO or a later EX wave
through the same existing IO/EX split.

## Owner-operation lane used by atomics

Atomic version completion uses the reserved lane at
`server.io_threads + server.tm_ngrow_io`. Completion workers are serialized by `commit_lock`, so
although physical producer threads can change, the lane is one logical SPSC producer. It uses the
same 8-byte job array and the same separated indices. Bit 0 tags an embedded `tomoOwnerOp *` rather
than a `client *` (`src/server.c:230-240`, `src/server.c:9041-9130`).

The semantic owner message is currently 32 bytes: an 8-byte queue pointer naming a 24-byte embedded
operation. The operation then names a `kvobj`; EX follows `op -> kv -> vmeta`, applies STAMP, PRUNE,
or CANCEL, updates `owner_ops_pending`, and clears `op->kv`/`op->seq`. Two operation records consume
48 of the 120 bytes in every `tomoVerMeta`.

The lane's queue indices are aligned correctly. `stamp_pending` shares the worker's deliberately
contended `q_summary` line, and the current operation record spans the second vmeta line while state
such as `owner_ops_pending` is in the first, so a normal owner job touches both vmeta lines.

## End-to-end distinct-line count

This count is for a steady, small, non-cross-shard GET/SET using the slim state move, with a
line-aligned fake and one-line EMBSTR operands/reply. It excludes database tables, stored values,
allocator metadata, the IO-only destination output line, and lines touched only by network I/O. It
includes shared transport controls even where batching amortizes their instruction/coherence cost.

| Boundary component | GET lines | SET lines | Notes |
|---|---:|---:|---|
| fake-client shell hot set | 11 | 11 | relative lines 0, 6-12, 15-17 across move, EX, reply, and reset |
| pending release-mask line | 1 | 1 | worker currently writes an IO-owned `pendingCommand` tail line |
| argv pointer vector | 1 | 1 | 16/24 live bytes |
| interned argv[0] object | 1 | 1 | globally hot, but still a pointer chase in release scan |
| key robj + 32-byte EMBSTR | 1 | 1 | can straddle two physical lines |
| SET value robj + 32-byte EMBSTR | 0 | 1 | variable payload |
| command descriptor | 1 | 1 | global/hot, reached through `fake->cmd` |
| fake reply payload | 1 | 1 | 39-byte GET32 or 5-byte `+OK` nominally fits one line |
| dispatch head/tail/jobs/summary | 4 | 4 | only jobs is intrinsically per-command; controls are batched/cached |
| parent line containing `reply_cdb` pointer | 1 | 1 | EX follows `fake->parent` before publication |
| aligned reply-ready line | 1 | 1 | EX release write, IO acquire read and clear |
| **Total** | **23** | **24** | full move adds one fake line; straddles can add more |

The unavoidable core of this count, given the fixed IO/EX ownership split, is much smaller: a queue
payload line, publication/control state amortized over a batch, a completion line, the useful
key/value byte lines, and a reply byte line. The 11-line fake compatibility surface, the
pending-command result bounce, duplicated cross-shard values, and oversized scatter shells are the
reducible portion.

## Ranked proposals

The percentages are per affected workload, not automatically whole-server wins, and are not
additive.

| Rank | Change | Estimated affected-path win | Verdict |
|---:|---|---:|---|
| 1 | One lifecycle handoff word | 1-2.5% GET/SET | Likely to pay |
| 2 | Real-only fake-ring pointer tail | 2-5% common scatter; 0-0.5% ordinary | Likely to pay if scatter matters |
| 3 | Compact/aligned common `csGroup` header | 2-6% common scatter | Likely to pay |
| 4 | 128-byte compact common scatter sub | 5-12% common scatter | Highest upside, high refactor risk |
| 5 | Structured large-reply reference in existing fake buffer | 3-10% eligible large GET | Likely to pay only when zero-copy is active |
| 6 | Encode owner-op kind in the queue word | 1-3% atomic completion | Conditional; zero with atomics off |
| 7 | Enable existing cross-shard MSET value move | 0-1.5% small values here | Probably will not pay on this box |

### 1. Reuse one 64-bit lifecycle word

Four 64-bit values have non-overlapping lifetimes:

```
IO route hash -> optional queue arrival stamp -> EX dict hash -> EX argv-release result
```

The route hash is consumed by IO's reorder staging before the fake is queued. Ordered pop/age reads
the arrival stamp before `exPrefetchBatch`. The dict hash is consumed before the post-proc argv
release scan. The release mask is consumed by IO only after the ready-byte acquire. A single union
with named phase helpers can therefore carry all four without recomputation.

**Current size.** `arrival_us`, `prefetch_key_hash`, and `tomo_key_h` occupy 24 bytes in `client`;
`pendingCommand.argv_released_mask` adds 8. `client` is 1,160 bytes/19 lines and `pendingCommand` is
152 bytes/3 lines. The fixed GET/SET envelopes are 1,336/1,344 bytes.

**Proposed size.** Keep one 8-byte word in `client`, delete the other two client words, and delete
the pending word. `client` becomes **1,144 bytes/18 lines** and `pendingCommand` becomes **144
bytes/3 lines**. The fixed envelopes become **1,312 bytes for GET** and **1,320 for SET**. More
important than 24 bytes, EX stops dirtying the IO-owned pending-command tail line. On the express
GET/SET path, where the command vector is not rewritten, it can also scan `fake->argc/argv`, which
it already needs, instead of following `current_pending_cmd`; general worker commands may retain
that read but still publish the mask in an already-hot fake line. IO applies the mask while freeing
the pending command on its own core.

**Cost.** The reorder staging order must copy the route hash before replacing it with arrival time.
Ordered pop/age must finish before prefetch overwrites the word. The express vector-alias invariant
must be asserted before dropping the pending-pointer read; other commands keep that read.
MSET-move dispatch must publish its release bits into the same result word. The pending free/reclaim
helpers need the mask passed from the fake instead of reading a struct member. `argc>64`,
disconnect, ring reuse, cross-shard retries, strict ordering, and prefetch-gated paths all need
explicit lifecycle assertions. Naming the union by phase is preferable to open-coded aliases.

**Estimated win.** About **1-2.5%** on small worker-routed GET/SET: on the express path one
dependent pointer load can go, and on every covered path one cross-core RFO/store and one
command-specific shared line disappear. The byte shrink alone is not the justification.

**Confirm/refute.** Interleaved p32 GET32 and SET32 A/Bs with reorder 0 and its shipped enabled
setting, strict-order coverage, dict-backed ex1 and flat multi-EX cases. Record retired
instructions/op, cycles/op, and address-attributed cache-to-cache/RFO samples for the old
`pendingCommand+128` line. Refute if that line does not disappear from EX stores or throughput is
within noise despite a repeatable instruction reduction. Correctness coverage must include
MSET-move, more than 64 argv entries, disconnect while in flight, and ring-slot reuse.

### 2. Move `fakeClients[32]` to real-client-only tail storage

Every fake contains a 256-byte pointer array which only real clients use. Worse,
`resetFakeClientState` zeros it on every cross-shard pool hit.

**Current size.** Fake shell **1,160 bytes/19 lines**. With its 1,024-byte buffer and 48-byte list,
one resident fake package is **2,232 bytes/36 nominal lines**. Each real also contains the same
array, where it is useful.

**Proposed size.** Remove the array from `client`; allocate real clients as
`sizeof(client)+32*sizeof(client *)` and address the tail with a no-load helper. Fakes allocate only
the base. Standalone, `client` becomes **904 bytes/15 lines**, a fake package **1,976 bytes/32
lines**, and a real allocation remains exactly 1,160 useful bytes. Combined with proposal 1, the
base is **888 bytes/14 lines**, the fake package is **1,960 bytes/31 lines**, and the real allocation
is 1,144 bytes. No side pointer or dependent load is introduced.

**Cost.** Update the approximately 15 direct `fakeClients` access sites, real allocation/free and
memory accounting, and audit every place that assumes `sizeof(client)` is the complete real
allocation. Fake reset must stop zeroing nonexistent tail storage. This changes field offsets and
needs the same reply-layout sensitivity checks called out by the existing 2-5% layout-regression
comment in `client`.

**Estimated win.** Ordinary persistent ring fakes: **0-0.5%**, primarily tighter working-set
packing; their array was not cleared per command. Common cross-shard traffic: **2-5%**, because
every recycled sub avoids a 256-byte memset spanning relative lines 0-4 (the three middle lines are
otherwise unnecessary) in addition to the four-line shell-footprint reduction.

**Confirm/refute.** MGET4/MSET4/DEL4/EXISTS4 across four owners, with counters for xsub pool hits,
bytes cleared per recycle, instructions/sub, and throughput. Also run ordinary GET/SET to prove the
field-offset change is neutral or positive. Refute the scatter claim if 256 fewer store bytes/sub
does not reduce instructions/cycles or if reply-field packing regresses the ordinary path.

### 3. Replace the monolithic `csGroup` header with a compact common header and typed tail

The common four-key commands pay for every unrelated command family's state. Make a 192-byte,
three-line common header and put only the selected command family's extension immediately after it
in the same allocation, before the existing exactly-sized bump tail. This is still one group, one
allocation, the same workers, and the same queue waves—no new stage or hop.

One of the three common lines should contain all concurrently worker-mutated scalar state
(`pending`, `usec`, `had_err`, `rcount`, `err`, `probe`, and atomic-write counters as applicable).
The other two hold immutable/common routing and simple result pointers. Allocate the group on a
64-byte boundary. This does not eliminate required atomics; it prevents their ownership transfers
from invalidating read-only routing lines and reduces the number of separately bounced mutable
lines.

**Current size.** Header **576 bytes/9 lines**, unaligned. MGET4 is **768 bytes/12 lines** and MSET4
is **704 bytes/11 lines**. Every byte is zeroed. Multi-sub completion and stats update at least two
different header lines.

**Proposed size.** Common header **192 bytes/3 lines**. With unchanged exact tails, MGET4 becomes
**384 bytes/6 lines** and MSET4 **320 bytes/5 lines**, saving 384 bytes/six zeroed lines per
command. Complex commands get a typed extension sized for their actual mode; the target is not to
force every possible extension into 192 bytes. Manual alignment over-allocation adds at most 72
raw bytes (`64 + saved raw pointer`) but still leaves these allocations materially smaller.

**Cost.** This is a broad field-access refactor. Some merge pipelines feed a later HOP2, so typed
extensions must reflect real coexistence, not an unsafe C union based only on command names.
Teardown, abort, disconnect, atomic retries, and flexible-tail address calculations need a complete
mode matrix. Add static offset/size assertions for the common header and its shared-mutable line.

**Estimated win.** **2-6%** on small cross-shard commands: 384 fewer zero stores per group, six
fewer active header lines, and fewer line acquisitions around the two per-sub atomic updates.
Ordinary single-key traffic is unchanged.

**Confirm/refute.** A/B MGET4/MSET4/DEL4/EXISTS4 at one, two, four, and eight distinct owners.
Count bytes zeroed, retired instructions, locked operations (unchanged count), cache-to-cache
transfers at the old offsets 0/168/504/512, and total throughput/tail latency. Refute if packing the
atomics increases serialization enough to offset fewer ownership acquisitions, or if common-group
construction is too small a fraction to move cycles.

### 4. Use a compact descriptor for reply-less coalesced subs

For coalesced MGET/MSET/DEL/EXISTS (and only rows proven to return through group slots/counters),
queue a pointer-tagged compact `csSubMsg` instead of a stock `client`. A conservative 128-byte/two-
line descriptor can hold the group, DB, command, argv, argc/sub index, flags/context, bucket hint,
and reserved room. Allocate exactly `nsub*128` bytes in the existing group allocation. Full-proc,
legacy, and sub-reply rows continue to use full fake clients.

This does **not** add a pool, queue, stage, or hop. It uses the existing group lifetime and the same
per-owner `exQueue`. A spare low pointer bit can identify the descriptor; the owner-op tag already
proves queue-word tagging is used in this tree.

**Current size.** Per sub: **2,232 bytes/36 nominal lines** (`1,160 client + 1,024 buffer + 48
list`), excluding argv already held in the group tail. MGET4 over four owners uses a 768-byte/12-line
group plus four packages, or **9,696 bytes/156 nominal lines**, before operands and the head fake.

**Proposed size.** **128 bytes/2 lines per sub**, no reply buffer/list. Standalone with the current
group header, MGET4 becomes one `576+192+4*128 = 1,280`-byte allocation, **20 lines**: 8,416 fewer
bytes/136 fewer nominal lines. With proposal 3 it is `192+192+512 = 896` bytes/**14 lines**. Only a
small fraction of the current 1 KiB buffers is actively touched, so the dynamic line win is smaller
than the resident count; eliminating full-client reset and compatibility-field traffic is the real
case.

**Cost.** High. `csSubExec`, lookup/notification helpers, `server.current_client`, statistics,
prefetch dispatch, free/abort paths, and queue batch decoding currently assume `client *`. The
common cases need explicit-context helpers rather than constructing a full client on the EX stack.
Every ordinary queue job also pays a well-predicted tag test unless decoding can be hoisted by run.
The group inline cap must treat descriptors as exactly-sized structural storage, not an unused fixed
reservation.

**Estimated win.** **5-12%** for the selected small scatter commands, zero for ordinary commands and
rows that retain full fakes. This is the largest upside, but its engineering/correctness risk puts it
after the simpler shrinks.

**Confirm/refute.** First instrument the actual common-row share and full-client fields read by
those rows. Then A/B MGET4/MSET4/DEL4/EXISTS4, recording instructions/sub, bytes initialized,
group allocation bytes, queue tag-branch misses, and throughput. Ordinary GET/SET must show no
measurable regression from tag decoding. Refute the 128-byte target if explicit-context semantics
need more than two lines or if common rows frequently fall back to full clients.

### 5. Put the structured large-reply reference in the existing fake buffer

Keep a worker's zero-copy `bulkStrRef` as a structured ownership record in the existing fake buffer
and move—not blindly copy—that record into the real reply on drain. The real client's empty 16 KiB
buffer can encode it; fallback may allocate the same list block as today. The existing freeback ring
still returns the object after send, so there is no new hop.

**Current size.** Useful record **51 bytes** (`9+42`), but the first reference forces a
`16,384+24 = 16,408`-byte reply-block request plus a 24-byte list node: **16,432 requested bytes/258
nominal lines and two allocations** for about one line of useful metadata.

**Proposed size.** **51 useful bytes in the already-allocated 1,024-byte fake buffer**, nominally
one line (possibly two when unaligned), **zero new allocation bytes** in the common empty-real-buffer
case. The fake/real state must represent a single moved reference so only one eventual freeback is
issued.

**Cost.** Add a typed/move-aware drain path, output-limit fallback, disconnect cleanup, and
io_uring lifetime coverage. The current forced-list rule prevents a real double-decrement bug, so a
plain `memcpy` is explicitly unsafe.

**Estimated win.** **3-10% for copy-avoidance-eligible large GETs**, from removing two allocator
calls and list manipulation; **0% for the 32-byte GET/SET cells** because they never take this path.
At network-bandwidth saturation the percentage will be lower.

**Confirm/refute.** Eligible 16 KiB/64 KiB GETs at several IO counts, with zero-copy gate-hit,
allocations/op, bytes allocated, freeback jobs/op, throughput, and disconnect/partial-write/io_uring
correctness. Refute if allocator calls disappear but wire throughput/cycles do not move.

### 6. Encode owner-op kind in the tagged queue word

Use low bits 0..2 of the aligned `kvobj *` to encode “owner job” and STAMP/PRUNE/CANCEL. Store the
one pending sequence in `tomoVerMeta`, ordered into its first hot line. The queued word then names
the kv directly; no embedded operation object is required.

**Current size.** Queue word 8 plus `tomoOwnerOp` 24 = **32 semantic bytes**. `tomoVerMeta` is **120
bytes/2 lines**, with 48 bytes of owner records. Drain follows `op -> kv -> vmeta`, touches both
vmeta lines, and clears 16 bytes of the op.

**Proposed size.** Queue word 8 plus one shared `owner_seq` 8 = **16 semantic bytes**, matching the
uTPS density for this lane. `tomoVerMeta` becomes **80 bytes/2 nominal lines**, saving 40 bytes per
version metadata object. Put state, pending count, and `owner_seq` in line 0 so the ordinary owner
operation needs one vmeta line rather than two.

**Cost.** Prove at least 8-byte kv alignment, object lifetime through the second queued operation,
STAMP-before-PRUNE sequencing, cancel/retry behavior, and no ABA from a retired vmeta. Decoder masks
must be centralized and asserted. This does not change the queue or add a stage.

**Estimated win.** **1-3% on atomic commit/owner completion**, plus 40 bytes less transient version
metadata; **zero overall when atomics are off**.

**Confirm/refute.** Atomic MSET/MSETNX throughput and latency, instructions/owner-job, owner
jobs/command, vmeta bytes/live versions, and address samples for the old second vmeta line. Refute
if vmeta line 1 remains necessary on nearly every job or owner drain is not material.

### 7. Existing cross-shard MSET value move

`tomokv-mset-move` already implements a no-copy ownership transfer but defaults off because no gain
was measured. It remains a useful falsifier, not a recommended default on this machine.

**Current size.** Each copied value of `L<=44` adds one `28+L`-byte object (60 bytes for L=32,
nominally one line, possibly two). Above 44, it adds a 24-byte object plus a separate
`header(L)+L+1` SDS allocation. The worker still touches one value object either way.

**Proposed size.** **0 duplicate bytes/0 duplicate lines**; the original parser value is transferred
to the owner sub. Queue and sub sizes do not change.

**Cost.** The existing released-mask/NULL ownership contract is load-bearing, retries need private
copies, and proposal 1 would have to preserve these release bits. Moving saves IO allocation/copy
work but does not remove the worker's value-byte demand.

**Estimated win.** **0-1.5% for small-value MSET on this one-CCD box; likely a wash**, consistent
with the code's recorded history. Larger values may benefit from copy elimination, but that is a
different workload, not evidence of miss hiding.

**Confirm/refute.** Interleaved MSET4 at 32 B, 1 KiB, and 16 KiB values with
`tomokv_xshard_mset_moved` proving the arm is live; record allocations/copies, instructions, and
throughput. Do not enable by default unless the representative small-value cell wins outside noise.

## Changes I do not think will pay

These are useful diagnostic A/Bs at most. Their size arithmetic is included so they are not vague
“try packing” suggestions.

| Option | Current -> proposed size | Cost | Estimated result and falsifier |
|---|---|---|---|
| 32-bit dispatch handles | `exQueue` 16,512 B/258 lines -> 8,320 B/130 lines; token 8 -> 4 B | Requires a stable per-IO handle table/arena, producer encoding, consumer decode and an extra dependent table load; owner tags complicate it | **Likely -2% to +0.5%; do not implement.** Falsify only if active queue arrays cause measurable L2/L3 pressure and an A/B reduces instructions or keeps them flat while throughput rises |
| Reduce capacity to 1,024 | 16,512 B/258 lines -> 8,320 B/130 lines; usable 2,047 -> 1,023 | Doubles backpressure risk; source records that deriving below 2,048 regressed throughput | **Negative; do not do.** Only revisit if `tomokv_ex_queue_full/ops` is zero with large margin in every supported load and an interleaved A/B wins |
| Pad every jobs slot | 16,512 B/258 lines -> `128+2048*64=131,200` B/2,050 lines | Removes adjacent-slot overlap but destroys eight-per-line packing and contiguous pointer `memcpy` | **Strongly negative, perhaps -2% to -10%.** Use only as a diagnostic to attribute cache-to-cache events, never as the target design |
| One completion line per worker | one-CCD `cdbSlots` 64 B/1 line per real -> `8*64=512` B/8 lines | Removes EX/EX byte false sharing but adds 448 B per connection and spreads IO completions across eight lines | **Probably wash/negative (-1% to +1%) on shared L3; keep one CDB.** Falsify with single-connection and many-connection p32 A/Bs plus address-level line transfers; a win only at one connection is not enough |
| Pad every ready byte | 64 B/1 line -> `32*64=2,048` B/32 lines per CDB | IO pulls a distinct line per in-order slot; huge per-client footprint | **Negative; do not do.** A padded diagnostic can bound false-sharing cost, but is not shippable |
| Restore a 32-bit ready bitmap | logical 32 B -> 4 B, still one aligned 64-byte allocation | Concurrent workers and IO require locked fetch-or/fetch-and on the same word; the tree deliberately replaced this | **Negative in an overhead-bound regime.** Refuted only by a bitmap A/B with fewer locked cycles and higher throughput, which is unlikely |
| Shrink fake start buffer to 256 B | package 2,232 B/36 nominal lines -> 1,464 B/24 lines | Small replies still touch one line; 257-1,024 B replies add grow allocation/copy, while grown slots persist anyway | **0% or negative for normal GET/SET; do not do for speed.** Revisit only for a connection-count memory objective, not this throughput audit |

The 32-bit-handle comparison is the important uTPS lesson. Their 32-bit buffer slot is cheap
because the surrounding design makes it the direct address of a compact request. In this tree a
handle would merely replace a hot pointer with a handle-table pointer chase; it would not remove
the 1,160-byte compatibility object or operand graph. First shrink what the pointer names.

## Alignment audit

| Structure | Aligned/padded correctly? | Finding |
|---|---|---|
| `exQueue` | Yes | queue base asserted 64-byte aligned; head, tail, and jobs each start a new line |
| `freebackRing` | Yes | enclosing base asserted; head, tail, objects at 0/64/128 |
| `cdbSlots` | Yes | type is 64-byte aligned/64 bytes; allocation manually rounds the pointer up |
| `exThread.q_top/q_summary` | Yes for intent | contended summary has its own line; immutable lane pointers start on another aligned line |
| xsub pool counts | Yes | per-IO count is aligned and padded to one line |
| `client` / ring fake | No line guarantee | 8-byte-aligned 1,160-byte shell; hot cross-thread fields are scattered across 11+ lines |
| `pendingCommand` | No line guarantee | worker currently writes only the tail release mask, bouncing an IO-owned allocation line |
| `csGroup` | No line guarantee | multi-EX atomics are scattered and `pending` shares immutable metadata |
| `tomoVerMeta` | No line guarantee | owner-operation hot data spans both nominal lines |

The first five show that the queue/control structures have already received careful alignment
work. The profitable remaining alignment work is coupled to shrinking/reordering `csGroup` and
owner metadata; merely adding padding to the existing large objects would increase bytes touched.

## Measurement needed to decide

Run these only after the ongoing measurement on the box is complete:

1. **Small ordinary path:** p32 GET32 and SET32, one connection and a many-connection case, at the
   representative IO/EX splits. Primary metrics: ops/s, ns/op, cycles/op, instructions/op, EX pop
   batch size, IO publish batch size, and queue-full events.
2. **Scatter:** MGET4, MSET4, DEL4, EXISTS4 deliberately placed on four owners, then one/two/eight
   owner variants. Add xsub pool hits, group bytes zeroed, bytes initialized/sub, and atomic
   operations/sub.
3. **Reply:** eligible 16 KiB and 64 KiB GETs. Add allocations/op, list blocks/op, freeback jobs/op,
   output bytes, partial writes, and io_uring/non-io_uring coverage.
4. **Atomics:** MSET/MSETNX with owner-job counts, live vmeta bytes, commit latency, and owner-drain
   cycles.
5. **Coherence attribution:** use the AMD-supported cache-to-cache/IBS facilities available on the
   host to sample the exact `jobs[]`, `cdbSlots`, old pending-mask, `csGroup` atomic, and owner-op
   addresses. Interpret line traffic, not just aggregate LLC misses.

An estimated win is confirmed only by repeated, interleaved A/Bs larger than session noise with no
material p99 regression. It is refuted if the intended instructions/stores/line transfers do not
fall, even if one throughput run happens to be faster. The core comparison should remain against
the measured 500 ns/command budget: this audit is trying to remove command work, not manufacture a
cache-miss story the data has already rejected.

## Direct answers

- **How many distinct lines?** A nominal **23 for small GET, 24 for small SET** across the current
  boundary dependency graph, before DB/stored-value lines; full state move adds one and allocation
  straddles can add more. Six of those are transport/completion lines, four of which are
  batch-amortized controls; 11 are the fake shell's hot surface.
- **Which are unavoidable?** Useful request key/value bytes, one queue payload handoff, batched
  publication/control, one completion synchronization line, and useful reply bytes. The full fake
  compatibility surface, pending-mask bounce, unrelated group modes, and oversized common scatter
  sub are not unavoidable.
- **False sharing on ring indices?** **No.** Head/retired and tail/staging live on separate aligned
  lines. Adjacent job slots can false-share; reply-ready bytes definitely can on this one-CDB box.
- **Largest reducible item?** Across the full scope, the common cross-shard full fake package:
  **2,232 bytes/36 nominal lines per sub**, target 128 bytes/2 lines. In the ordinary ring fake, the
  largest plainly removable field is **`fakeClients[32]`, 256 bytes/four footprint lines**; because
  it begins at offset 16, its reset currently spans five relative lines. The 1 KiB reply
  buffer is larger in resident bytes but is not the best speed target because unused capacity is
  not touched.
- **How close to uTPS?** The ring entry is already 8 bytes, but the semantic fixed carrier is
  1,336/1,344 bytes because the queue record is not self-contained. Proposals 1+2 reduce it to
  **1,056 bytes for GET and 1,064 for SET** (`8 queue + 888 fake + 144 pending + argv`), still about
  66x uTPS's 16 bytes. Getting dramatically closer for arbitrary Redis commands requires replacing
  the stock `client *` execution API; the bounded compact-sub proposal does that only where the
  semantics are already open-coded and reply-less.
