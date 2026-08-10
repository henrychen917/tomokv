# Allocation review

## Scope and counting rules

This review accepts the brief's settled results: allocator ownership is not the lever, per-type/tiered operand pools are closed, and `csGroup` inline/SSO is already implemented. The target is allocator-call count (`ARCH_BRIEF.md:70-79`). The execution model matters only for lifetime: the IO thread owns parsing and the connection, while EX workers execute dispatched commands (`ARCH_BRIEF.md:9-18`).

I use the following symbols:

- `A` = RESP argument count including the command name; `L_i` = byte length of argument `i`.
- `K` = logical key count in a multi-key command; `S` = distinct destination shards/sub-fakes in one wave; `H` = non-null string hits returned by MGET; `M_i` = member count of gathered input `i`.
- “Call” means one `zmalloc`/`zcalloc`/`zrealloc`/SDS allocator request. A `zrealloc` may extend in place; the code does not expose that outcome, so it is still one allocator request.
- Byte sizes are requested sizes before jemalloc rounding. Sizes marked **inferred, LP64** follow directly from the cited C layouts; they were not measured because this review was explicitly read-only.
- A route-specific allocation rate is `calls per occurrence × occurrences/s`. The brief supplies exact rates only for GET and SET, not a whole-workload command mix (`ARCH_BRIEF.md:90-94`), so conditional cross-shard rows are ranked by their exact per-occurrence multiplier and retain an explicit frequency term.

## Executive result

The steady small-command path has two universal allocation sources, not one: the non-command RESP operands and the `clients_pending_ex` list node. A pooled `pendingCommand`, its preserved `argv` capacity, the fake ring, and the worker queues are otherwise allocation-free after warm-up (`src/networking.c:3658-3669`, `src/networking.c:6181-6200`, `src/server.c:6494-6509`, `src/server.c:15738-15771`).

The remaining cross-shard count is outside the completed `csGroup` SSO: each sub still gets a separately allocated `argv`, coalesced MGET copies every hit into a fresh SDS, and default MSET duplicates every value before the worker immediately consumes that duplicate (`src/server.c:8805-8820`, `src/server.c:8991-9005`, `src/server.c:8154-8173`, `src/server.c:8902-8937`, `src/server.c:8192-8199`).

Small replies allocate nothing because each fake has a reusable buffer and each real client has a reusable 16 KiB buffer. A qualifying worker-side zero-copy GET is the exception: it is deliberately forced into a heap reply block plus a heap list node, i.e. exactly two allocator calls for the first reference in an empty fake (`src/networking.c:859-882`, `src/networking.c:901-941`, `src/networking.c:720-771`).

The worker loop itself has no steady per-command allocation: queue storage, pop batches, prefetch state, and reply-signal accumulators are fixed arrays; its only loop-infrastructure allocations are first-use command-stat/latency blocks and a flat-retire-node pool miss (`src/server.h:2286-2309`, `src/server.c:15876-15879`, `src/server.c:16025-16038`, `src/server.c:16324-16353`, `src/server.c:16525-16532`, `src/server.c:2514-2531`, `src/flatstore.c:72-114`).

Concrete warm-path lower bounds make the count scale visible. These assume valid RESP, interned command token, all non-command operands `<=44` bytes, hot command/fake/sub pools, a reply that fits existing buffers, no DICT collision/resize, and one persistent `kvobj` per SET pair:

- Reference p1 GET is **2 allocator calls/command**: one key operand plus one empty-to-busy list node, or **1,653,754 calls/s** at 826,877 ops/s (`src/networking.c:3864-3870`, `src/object.c:432-443`, `src/server.c:6528-6531`, `ARCH_BRIEF.md:90-94`).
- Reference p1 SET is **4 calls/command**: key, value, membership node, and persistent `kvobj`, or **3,269,572 calls/s** at 817,393 ops/s (`src/networking.c:3864-3870`, `src/object.c:432-443`, `src/server.c:6528-6531`, `src/object.c:355-415`, `ARCH_BRIEF.md:90-94`).
- At p32, before the busy-interval node is apportioned, parser-only GET is at least **7,943,860 calls/s**; SET operands plus the persistent `kvobj` are at least **20,557,155 calls/s** (`ARCH_BRIEF.md:90-94`, `src/object.c:355-415`, `src/object.c:432-443`).
- A hit-complete cross-shard MGET(4) is **`9+S` calls/command**: 4 parser operands, 1 group, `S` sub vectors, and 4 result SDS copies. With four distinct shards that is 13, plus membership enrollment if the real client was idle (`src/server.c:8795-8802`, `src/server.c:8991-9004`, `src/server.c:8154-8173`, `src/server.c:6528-6531`).
- A cross-shard MSET(4) with EMBSTR operands is **`17+S` calls/command**: 8 parser operands, 1 group, `S` sub vectors, 4 duplicated values, and 4 persistent `kvobj`s. With four distinct shards that is 21, plus membership enrollment if idle (`src/server.c:8795-8802`, `src/server.c:8902-8937`, `src/server.c:8991-9004`, `src/object.c:355-415`, `src/server.c:6528-6531`).

## Top five eliminable allocation sources

This ordering is for the supplied hot cells: small-value GET/SET plus MGET(4)/MSET(4). The “rate weight” column makes the command-frequency factor explicit. The counts are read from code; the proposed mechanisms and their expected eliminated counts are design inferences.

| Rank | Allocation source | Exact count when route occurs | Rate weight | Concrete elimination mechanism |
|---:|---|---:|---:|---|
| 1 | RESP non-command operands | At least `A-1`; exactly `A-1` for lengths `<=44`, and two calls per RAW operand above 44 bytes. The command token is interned (`src/networking.c:3864-3870`, `src/object.c:432-443`, `src/object.c:149-153`). | Universal. GET has at least 1 and SET at least 2: **826,877/s** at p1 GET, **1,634,786/s** at p1 SET, **7,943,860/s** at p32 GET, and **13,704,770/s** at p32 SET using the brief's rates (`ARCH_BRIEF.md:90-94`). MGET(4) has at least 4; MSET(4) at least 8. | Put argument `robj` plus SDS bytes in a reusable arena attached to `pendingCommand`; skip individual frees through an arena mask. For SET/MSET, add an arena-source mode to `kvobjSetEx` that copies into the persistent `kvobj` and does not `decrRefCount`/adopt the arena source (`src/object.c:355-424`). |
| 2 | Cross-shard MSET value duplication | `K` calls for EMBSTR/INT values, `2K` for RAW values; MSET(4) is 4 or 8 calls (`src/server.c:8902-8937`, `src/object.c:530-544`). | `f_xshard_mset × K` or `×2K`. | The zero-copy move contract already exists and removes the duplicate: transfer each original value to its one sub, mark/null the head slot, let the worker consume it, and null the sub slot (`src/server.c:8912-8935`, `src/server.c:8192-8199`). Make that path the eligibility default after validating the existing contract, or make the arena-source SET path perform the same one-copy-to-`kvobj` operation. |
| 3 | Coalesced MGET result copies | One SDS allocation per hit, `H`; a hit-complete MGET(4) is 4 calls (`src/server.c:8154-8173`). | `f_xshard_mget × H`. | Replace `mget_vals[]` SDS ownership with `{robj *, owner_ex, missing}` descriptors. The worker takes the reference; the IO coordinator emits a `bulkStrRef` into the real client's encoded buffer and returns the ref through the existing fixed freeback ring after send (`src/server.h:2296-2309`, `src/networking.c:901-941`). |
| 4 | Cross-shard sub `argv` arrays | One allocation per sub per wave: `S`; MGET(4)/MSET(4) are at most 4 on four distinct shards. Legacy key subs request 16 bytes; coalesced requests are `8 × [1 + (1+extra)×keys_on_shard]` **inferred, LP64** (`src/server.c:8984-9005`, `src/server.c:9023-9033`). | `Σ_waves f_route × S_wave`; pipelines and two-hop commands pay it again for later waves (`src/server.c:9263-9273`, `src/server.c:9298-9327`, `src/server.c:10161-10203`). | Allocate every sub pointer vector on the IO coordinator from the command arena before publishing the sub. Make `csFreeSub` distinguish arena storage so it decrefs elements but does not `zfree(sub->argv)` (`src/server.c:8852-8858`). |
| 5 | `clients_pending_ex` membership node | One 24-byte node **inferred, LP64** per empty-to-busy interval (`src/server.c:6528-6531`, `src/adlist.h:16-20`, `src/adlist.c:109-117`). **Inference for the reference p1 configuration:** with one allowed in-flight command, each next dispatch follows a full drain, so this is one per command: **826,877/s** for GET or **817,393/s** for SET (`src/server.c:2896-2902`, `ARCH_BRIEF.md:90-94`). | `f_empty→busy`; continuous pipelines amortize it over a busy interval, not necessarily over exactly `P` commands (`src/server.c:6528-6531`, `src/server.c:2896-2902`). | Embed a `listNode clients_pending_ex_node` in the real client and use `listLinkNodeTail`/`listUnlinkNode`, exactly as the existing pending-write path embeds and links `clients_pending_write_node` (`src/server.h:1857-1860`, `src/networking.c:622-639`). |

Two conditional promotions matter:

1. A qualifying large worker GET makes one reply-block allocation plus one list-node allocation, exactly **2 calls/command**, so it outranks item 5 whenever that route is common (`src/networking.c:932-941`, `src/networking.c:753-771`). It does not occur in the brief's 32-byte-value cells because the configurable gate defaults to 1,024 bytes and lower IO-thread counts impose 16 KiB/64 KiB gates (`src/config.c:3343-3349`, `src/networking.c:1641-1682`, `src/server.h:200-203`).
2. Cardinality-heavy set/zset scatter can allocate `Σ(1+M_i)` or `Σ(2+M_i)` calls and therefore outrank everything above for that command class; it is not placed in the top five because the brief gives no frequency/cardinality distribution for those commands (`src/server.c:8383-8405`, `src/server.c:8430-8479`).

## Allocation census

### 1. Parse, dispatch preparation, and operand ownership

| Allocation | Requested size and frequency | Allocator/free thread and lifetime | Disposition |
|---|---|---|---|
| `pendingCommand` structure | Pool miss only; `sizeof(pendingCommand)`, **152 bytes inferred, LP64**, from its fields and inline six-key buffer (`src/server.h:3862-3880`, `src/server.h:3941-3960`, `src/networking.c:6211-6213`). | Allocated by the parsing IO thread. Normally returned by that same IO identity to a 128-entry pool at terminal teardown; only pool overflow/oversized cases free it (`src/networking.c:3658-3669`, `src/networking.c:6314-6347`). | Already reused. Fold the arena's first slab into the same allocation so a cold miss remains one call. |
| RESP `argv` pointer vector | Capacity miss only after warm-up. Initial request is `8 × min(A,1024)` bytes **inferred, LP64**; unusually large streaming requests can `zrealloc` it as it fills (`src/networking.c:3719-3725`, `src/networking.c:3836-3840`). | Allocated/freed on the IO thread and retained with pooled commands while capacity is at most 64 (`src/networking.c:6188-6200`, `src/networking.c:6332-6347`). | Already reused for common commands. An arena can absorb the vector and removes cold/capacity misses; the RESP multibulk count is known before elements are built (`src/networking.c:3701-3724`). |
| RESP operand object, `L<=44` | One allocation for an embedded `robj` and type-8 SDS. Requested size is `sizeof(robj)+sizeof(sdshdr8)+L+1 = 20+L` bytes **inferred, LP64** (`src/object.h:99-114`, `src/sds.h:32-36`, `src/sds.h:322-326`, `src/object.c:221-241`). Frequency is `A-1` because `argv[0]` uses the intern table when recognized (`src/networking.c:3864-3870`). | Usually allocated on IO and decref/freed there at `freePendingCommand`; a DB-aliased operand released by the worker is masked so the IO thread skips it (`src/networking.c:6318-6325`, `src/server.c:16295-16308`). | Highest-priority arena target. |
| RESP operand object, `L>44` | Two calls: 16-byte `robj` **inferred, LP64** plus one SDS request of `header(L)+L+1` (`src/object.c:107-115`, `src/object.c:149-153`, `src/object.c:432-443`, `src/sds.c:98-115`). | Same ownership as the preceding row (`src/networking.c:6318-6325`, `src/server.c:16295-16308`). | Arena collapses two calls to zero on a warm command slab. An escaping RAW SET value must be copied/promoted; it cannot be adopted from arena storage. |
| “Big argument” query-buffer handoff | For a non-master argument at least 32 KiB that exactly occupies the query buffer, one 16-byte object header is allocated around the existing SDS, then a replacement query-buffer SDS is allocated at `L+2` or 16 KiB (`src/server.h:188-194`, `src/networking.c:3842-3862`). A preceding `sdsMakeRoomForNonGreedy` may also reallocate the query buffer while the bulk is incomplete (`src/networking.c:3798-3823`). | The object follows normal command ownership; the replacement query buffer stays with the connection (`src/networking.c:3842-3862`). | Do not put the large bytes in a command arena. The useful arena optimization is only the object header; preserve the current zero-copy SDS handoff. |
| Key-reference overflow | Zero calls through 6 keys; above 6, one allocation/reallocation of `8×K` bytes **inferred, LP64** (`src/server.h:3862-3880`, `src/db.c:3452-3478`). Preprocessing performs extraction for each valid command (`src/server.c:5869-5908`). | Allocated and freed by the IO thread with the pending command (`src/server.h:5561-5570`, `src/networking.c:6314-6319`). | Put overflow storage in the command arena. The common six-key case is already inline and should not change. |
| Inline-protocol parse | One full-line SDS, one SDS per token, one vector `s_realloc` per token, one `robj` per token, plus an `argv` capacity miss if needed (`src/networking.c:3508-3512`, `src/networking.c:3550-3568`, `src/sds.c:1047-1144`). | All are IO-thread allocations; token SDS ownership is adopted by each object and released at command teardown (`src/networking.c:3561-3568`, `src/networking.c:6318-6325`). | This is a much higher-count alternate protocol, not the RESP benchmark path. An arena-capable inline tokenizer could remove the per-token vector/SDS/object calls, but it is lower priority than RESP. |
| Deferred-object array | Once when a real client is assigned to an IO thread, not per command: 32 entries (`src/iothread.c:295-302`, `src/server.h:458-459`). `deferredObject` is 16 bytes **inferred, LP64**, so the request is 512 bytes (`src/server.h:1400-1408`). | Connection lifetime, IO-owned (`src/iothread.c:295-302`). | Exclude from per-command ranking. |

The parser-to-worker transition does not copy command state: the pending command and its `argv` pointers move from the real client to the ring fake (`src/server.c:15538-15558`, `src/server.c:15584-15609`). Terminal `commandProcessed(fake)` resets the fake and frees/returns that pending command only after the IO drain has consumed the worker result (`src/server.c:2869-2877`, `src/networking.c:3893-3925`).

### 2. Fake-client ring and dispatch queues

| Allocation | Requested size and frequency | Allocator/free thread and lifetime | Disposition |
|---|---|---|---|
| Ring fake, first use of a slot | Three calls: `sizeof(client)`, a 1,024-byte buffer, and `sizeof(list)`; `sizeof(list)` is 48 bytes **inferred, LP64** (`src/networking.c:331-340`, `src/adlist.h:27-33`). Slots are lazy-created up to a hard maximum of 32 (`src/server.c:6502-6509`, `src/server.h:1508-1508`). | Created by the owning IO thread and reused across commands. Freed at connection teardown or by idle ring-depth decay only when no command is in flight (`src/networking.c:2575-2585`, `src/server.c:11728-11768`). | Correctly amortized. Do not replace with a per-command arena. |
| Fake buffer growth | At most one allocation/free at each power-of-two high-water crossing from 1 KiB through 64 KiB; therefore at most six growth events per slot (`src/server.h:188-193`, `src/networking.c:859-877`). | The worker can trigger growth while building the fake reply; the old buffer is freed immediately there. The grown buffer remains attached to the fake and is reusable (`src/networking.c:859-877`, `src/networking.c:359-363`). | Already high-water reused. Keep outside the command arena because the slot persists. |
| Cross-shard sub-fake pool miss | Same three allocations as a ring fake. A hit reuses the client, buffer, and reply-list object; pool cap is 96 per IO identity (`src/networking.c:344-375`). | Created/recycled by the coordinator IO thread; reply blocks are emptied, but the fake shell/buffer/list persist (`src/networking.c:377-399`). | Already amortized. This pool is for composite fake shells, not the disproven per-type operand pool. |
| `clients_pending_ex` list node | One 24-byte node **inferred, LP64** per empty-to-busy interval (`src/server.c:6528-6531`, `src/adlist.h:16-20`, `src/adlist.c:109-117`). | Allocated by the IO thread at dispatch; freed by that IO thread when its ring fully drains (`src/server.c:2896-2902`, `src/adlist.c:165-174`). | Replace with an intrusive node embedded in `client`, as ranked above. |
| Worker dispatch/freeback queues | No per-command allocation: jobs and returned object pointers live in fixed ring arrays (`src/server.h:2286-2309`). Push and pop only write/read those slots (`src/server.c:15738-15771`, `src/server.c:15790-15840`). | Queue lifetime. | No action. |

### 3. Reply construction and socket lifetime

| Allocation | Requested size and frequency | Allocator/free thread and lifetime | Disposition |
|---|---|---|---|
| Real-client reply buffer/list | Connection setup allocates a 16 KiB buffer and a list object (`src/networking.c:401-427`, `src/networking.c:505-510`). | Connection lifetime, owned by the connection's IO identity. | Not per command. |
| Small fake/real reply | Zero calls while the reply fits the reusable fake/real buffer and no reply list already exists (`src/networking.c:787-825`, `src/networking.c:859-882`). The drain copies the fake's short buffer to the real and O(1)-joins any list (`src/networking.c:1852-1885`). | Fake bytes become real-output bytes on the IO drain. | Already inline/reused. |
| Reply-list spill | Each new chunk is two calls: one block of `max(16 KiB,payload)+sizeof(clientReplyBlock)` plus one 24-byte list node **inferred, LP64** (`src/networking.c:720-771`, `src/server.h:1121-1127`, `src/adlist.h:16-20`). Subsequent payloads reuse the tail until it is full (`src/networking.c:732-750`). | A worker may allocate the block/node on a fake. `listJoin` transfers both to the real client; the IO send path later deletes the node and its callback frees the block (`src/networking.c:1880-1885`, `src/networking.c:3066-3091`, `src/networking.c:86-96`). | Cannot be command-arena memory because it can outlive command retirement. An intrusive header that combines list linkage with `clientReplyBlock` would remove one call per new spill block, but requires a reply-list representation change. |
| Deferred aggregate length | `addReplyDeferredLen` always allocates one 24-byte placeholder node **inferred, LP64**. It is deleted if merged into an adjacent block; otherwise `setDeferredReply` allocates exactly `length+sizeof(clientReplyBlock)` for the header block (`src/networking.c:1285-1311`, `src/networking.c:1313-1373`). | Built by the command-executing thread; after fake-list splice, sent and freed by IO as above. | A small inline deferred-header slot would remove the placeholder call only if all paths can represent it without an adlist node. Lower frequency than ordinary operand creation. |
| Worker zero-copy bulk reference | For a qualifying RAW value, the worker takes a ref and is forced to call `_addReplyPayloadToList`; the first reference in an empty fake therefore allocates one at-least-16-KiB encoded block and one node (`src/networking.c:901-941`, `src/networking.c:753-771`). The descriptor itself is 42 bytes and its packed header 9 bytes **inferred, LP64**, so about 51 useful bytes occupy that first chunk (`src/server.h:1101-1119`). | Worker increments the object. IO owns the spliced block, sends it, and returns the object through the fixed freeback ring so the owning worker decrefs it (`src/server.h:2296-2309`, `src/networking.c:3066-3091`). | Add one structured forwarded-reference slot to the fake/result. On drain, encode it directly into the real client's existing empty 16 KiB buffer via `_addBulkStrRefToBuffer`, avoiding both allocations when that buffer accepts it (`src/networking.c:810-825`). The handoff must be structured: blindly copying the current fake inline bytes would duplicate the ref and double-decref (`src/networking.c:932-940`). |

The decisive arena constraint is visible here: fake reply-list blocks are transferred into the real client's socket backlog before `commandProcessed(fake)` destroys the command state, and may be freed only after a later socket write (`src/server.c:2820-2874`, `src/networking.c:1880-1885`, `src/networking.c:3066-3091`). They must never point into a reset command arena.

### 4. Cross-shard scatter/gather

#### Base group and scatter

| Allocation | Requested size and frequency | Allocator/free thread and lifetime | Disposition |
|---|---|---|---|
| `csGroup` | Exactly one call per cross-shard command: `sizeof(csGroup)+round8(want)`, with the inline tail capped at 512 bytes (`src/server.c:8795-8802`, `src/server.h:2100-2105`). | IO coordinator allocates it and frees it last after all subs/results are consumed (`src/server.c:10524-10561`). | SSO is complete. A command arena can still remove this one enclosing allocation by placing the whole group there; this is not a new per-array pool. |
| Coordinator arrays (`subs`, result-pointer lanes, position maps) | Usually zero extra calls because `csInlineWant` sizes them and `csgAlloc` serves them from the group tail; an overflow is one heap call per spilled array (`src/server.c:8805-8849`). | IO coordinator alloc/free; inline storage dies with the group (`src/server.c:8845-8849`, `src/server.c:10524-10561`). | No new pool. If a command arena owns the group, preserve `csgAlloc` semantics for overflow. |
| Owner map | Zero calls through 128 keys; above 128, one `4×K`-byte allocation **inferred, LP64** (`src/server.c:8949-8955`). | IO coordinator allocates before scatter and frees after pushing all subs (`src/server.c:8955-9005`). | Arena overflow target. The 128-entry stack fast path is already correct. |
| Sub `argv` | One call per sub per wave. Coalesced size is `8×[1+(1+extra)×keys_on_shard]`; legacy key sub is 16 bytes; full-copy/fan-all is `8×A`, all **inferred, LP64** (`src/server.c:8991-9004`, `src/server.c:9023-9033`, `src/server.c:9524-9548`). | IO coordinator allocates and fills it before queue publication. `csFreeSub` decrefs elements and frees it on the IO coordinator after the worker barrier (`src/server.c:8852-8858`). | Command-arena allocation removes `S` calls per wave. |
| Position arrays | The pointer lane plus each per-sub `int[]` is allocated through `csgCalloc/csgAlloc`, so it is normally inside the existing group allocation and only spills past the inline cap (`src/server.c:8973-8996`). | IO group lifetime. | Already SSO; do not count common-case arrays as heap calls. |

#### Gather payloads

| Allocation | Requested size and frequency | Allocator/free thread and lifetime | Disposition |
|---|---|---|---|
| Coalesced MGET values | `H` SDS calls, each `header(L)+L+1`; integer-encoded values also allocate through `sdsfromlonglong` (`src/server.c:8154-8173`). | Owning workers allocate copies into position slots; the IO coordinator consumes/frees them during reassembly or teardown (`src/server.c:10308-10320`, `src/server.c:10538-10544`). | Replace with owner-tagged object descriptors and the existing freeback mechanism. This removes `H` calls and `H` value copies. |
| MSET value copies | `K` embedded-object calls or `2K` RAW object+SDS calls (`src/server.c:8902-8937`, `src/object.c:530-544`). | IO coordinator makes the duplicate; the destination worker consumes it into `kvobjSetEx`, then nulls the sub slot; remaining sub refs are cleaned on IO (`src/server.c:8192-8199`, `src/server.c:8852-8858`). | Use the already-implemented move contract or the arena-source SET contract. |
| Set gather | For each nonempty input, one `8×M_i` pointer vector plus one fresh SDS per member: `1+M_i` calls (`src/server.c:8383-8405`). | Worker allocates; IO coordinator frees after barrier (`src/server.c:10524-10535`). | This count is cardinality-dominant. See “Speculative opportunities”: eliminating it needs a different merge protocol, not merely an arena. |
| Zset/set-as-zset gather | For each nonempty input, one `8×M_i` pointer vector, one `8×M_i` score vector, and one SDS/member: `2+M_i` calls (`src/server.c:8430-8479`). | Worker allocates; IO coordinator frees after barrier (`src/server.c:10524-10535`). | Same protocol issue as set gather. |

#### Merge pipeline and two-hop commands

The merge pipeline has one group call plus the ordinary sub-`argv` calls. Its GATHER1 stage allocates an `8×M` candidate pointer vector, optionally an `8×M` temporary score vector, one SDS per candidate, and for Z operations an `8×M×K` zeroed score matrix (`src/server.c:9133-9188`). The coordinator then allocates `4×K` bytes for `pipe_order` and `M` bytes for `pipe_verdict` (`src/server.c:9231-9279`).

Each nonempty PROBE hop makes three allocator requests: a temporary `4×K` `kidx`, an `8×(nk+1)` sub `argv`, and a `4×nk` `pipe_probe_pos`; the previous probe-position vector is freed before replacement (`src/server.c:9298-9327`). `kidx` can use the same 128-key stack/heap split as `wof`, `pipe_probe_pos` can be a single `4×K` arena vector reused across hops, and sub `argv` belongs in the command arena. That removes three calls per normal probe hop without changing the member-copy protocol.

Final Z-pipeline reassembly allocates exactly three arrays: `8×K` weights, `4×K` order, and `16×survivors` `{sds,double}` pairs **inferred, LP64**, then frees all pipeline payloads (`src/server.c:10252-10291`, `src/server.c:10298-10302`). These are coordinator-only, bounded-lifetime arena candidates.

Two-hop paths make one sub-`argv` allocation per HOP1/HOP2 sub (`src/server.c:9914-9931`, `src/server.c:10169-10203`) and may create a growable serialized SDS through `rioInitWithBuffer(sdsempty())` (`src/server.c:8040-8058`, `src/server.c:10015-10030`, `src/server.c:10102-10127`). The serialized payload crosses workers and the IO coordinator and therefore belongs to the group/command lifetime, but its final byte count is data-dependent and SDS growth can make multiple allocator requests.

Concrete two-hop scratch counts:

- BITOP allocates `8×K` source pointers, `8×K` lengths, one result SDS of `maxlen`, one 16-byte object wrapper **inferred, LP64**, and the `rio` output SDS/growth (`src/server.c:10033-10073`). The two fixed `K` arrays are stack/arena candidates.
- PFMERGE allocates an `8×K` wrapper vector and one 16-byte object wrapper per non-null gathered image before result/serialization internals (`src/server.c:10076-10100`, `src/object.h:99-114`). The vector and wrappers can be command-arena objects if teardown skips individual `zfree`.
- LMOVE HOP1 allocates one SDS for the selected element; HOP2 allocates a string object and may create a new list/listpack persistent value (`src/server.c:8617-8638`, `src/server.c:8647-8663`). The result SDS can live in the command arena, but the destination value cannot.
- MPOP HOP2 makes the normal sub `argv` allocation and also allocates `createStringObject("1",1)` once (`src/server.c:10179-10198`). Replace that object with `shared.integers[1]`; the integer constructor already returns the shared object for that value (`src/object.c:461-481`).

Coordinator materialization for non-pipelined set/zset results is allocation-heavy but algorithmic. A set result starts with a temporary pointer vector and a new intset object; `createIntsetObject` is already two allocations and each successful integer insertion may `zrealloc` the intset (`src/server.c:9560-9617`, `src/object.c:572-576`, `src/intset.c:211-238`). A zset result allocates weights, a result zset, optional order and contribution arrays, and temporary zsets; `createZsetObject` itself allocates the zset shell, dictionary, skiplist, skiplist header, and `robj`, while each result member is a separate skiplist-node allocation containing its member SDS (`src/server.c:9692-9788`, `src/object.c:593-601`, `src/t_zset.c:141-181`, `src/t_zset.c:207-219`). These counts scale with result cardinality and are not safely eliminated by merely changing the allocator.

### 5. Worker execution loop and persistent command effects

The queue/pop machinery is allocation-free per command: `exQueue.jobs[]` is fixed, `exSliceCtx.batch[16]` persists with the slice, prefetch arrays/state are stack arrays, and completion aggregation is stack-bounded by the batch (`src/server.h:2286-2294`, `src/server.c:15790-15840`, `src/server.c:15876-15879`, `src/server.c:16025-16038`, `src/server.c:16324-16353`, `src/server.c:16525-16532`). The execute loop calls each command and then publishes completion without allocating loop metadata (`src/server.c:16469-16523`, `src/server.c:16690-16710`).

The exceptions are not steady per-command loop allocations:

- The first command on a thread allocates one zeroed per-command statistics block; latency tracking allocates one pointer table per thread and a histogram on the first sample for each command (`src/server.c:2514-2531`, `src/server.h:4453-4463`, `src/server.h:4484-4496`).
- A FLATSTORE overwrite needs a 16-byte retire node **inferred, LP64** only when the worker-local recycled-node pool is empty; steady write load reuses nodes, and trim runs every 4,096 worker passes (`src/flatstore.h:60-77`, `src/flatstore.c:72-114`, `src/server.c:16402-16410`).

Command handlers still allocate persistent database state. For SET, `kvobjSetEx` creates one `kvobj` allocation containing the embedded key and, when it fits, the value; its exact requested formula is `sizeof(robj)+metadata+1+key_sds_req+value_sds_req` (`src/object.c:163-205`, `src/object.c:355-415`). SET explicitly enables RAW embedding, with a 192-byte/255-byte fit rule (`src/t_string.c:150-159`, `src/object.c:287-299`).

That database allocation is not eliminable by a command arena: it survives command completion. FLATSTORE inserts the resulting pointer without an entry allocation (`src/kvstore.c:1075-1099`, `src/flatstore.c:165-192`). In the DICT engine, the DB dict is `no_value`; an empty bucket encodes the key directly, while a collision allocates one 16-byte `dictEntryNoValue` **inferred, LP64** (`src/server.c:1041-1053`, `src/dict.c:48-62`, `src/dict.c:148-152`, `src/dict.c:554-578`). Table expansion is an occasional load-factor capacity event, not one call per SET (`src/dict.c:1647-1673`, `src/dict.c:1745-1757`).

## Per-command arena assessment

The arena design in this section is an inference from the cited ownership and teardown paths; it is not an existing implementation.

### Fit: yes, if it is a reusable `pendingCommand` arena

The correct owner is `pendingCommand`, not `client`, ring slot, worker, or `csGroup`. Parsing acquires the pending command; dispatch transfers that exact object to the fake; and the IO drain finally calls `commandProcessed(fake)` after replies or cross-shard reassembly are complete (`src/networking.c:4135-4181`, `src/server.c:15538-15558`, `src/server.c:2820-2874`). That is already the required cross-thread command-lifetime token.

A separately allocated arena per command would merely exchange GET's one operand allocation for one arena allocation. The first slab should therefore be part of the pooled `pendingCommand` allocation and reset on reuse. A 2 KiB inline slab raises the existing 128-entry pool's maximum retained memory by **256 KiB per IO identity**; 4 KiB raises it by **512 KiB per IO identity** (**inferred arithmetic**) (`src/networking.c:3658-3669`). Oversized commands should use a small number of geometric overflow slabs, retained only under an explicit cap, so one overflow call replaces many operand/result calls.

### What belongs in it

1. The RESP `argv` vector, non-command argument wrappers and SDS bytes, and key-reference overflow (`src/networking.c:3719-3725`, `src/networking.c:3864-3870`, `src/db.c:3452-3478`).
2. `csGroup` plus its inline tail, all sub `argv` vectors, owner-map overflow, pipeline `kidx`/probe positions, and final coordinator-only arrays (`src/server.c:8795-8849`, `src/server.c:8949-9005`, `src/server.c:9298-9327`, `src/server.c:10252-10302`).
3. Fixed-lifetime two-hop scratch and serialized payload only when its growth policy can allocate from arena slabs (`src/server.c:10033-10100`).

### What must not belong in it

1. Any `kvobj`, list/listpack, or other value installed in the database, because it survives the command (`src/db.c:438-472`, `src/db.c:809-849`).
2. Reply blocks/list nodes transferred to the real client's socket backlog, because the socket may consume them after command teardown (`src/networking.c:1880-1885`, `src/networking.c:3066-3091`).
3. Fake shells and fake buffers, because they are reused across commands and can be retained/decayed independently of one command (`src/networking.c:331-399`, `src/server.c:11728-11768`).

### Required lifetime rule

Reset an arena only when all four conditions hold:

1. Every worker sub/wave has completed and the IO coordinator has acquired the completion signal; staged pipelines and HOP2 must not merely have finished HOP1 (`src/server.c:2829-2848`, `src/server.c:16690-16699`).
2. `csReassemble` has consumed/free-equivalent-cleared every group/sub/result view (`src/server.c:10308-10320`, `src/server.c:10524-10561`).
3. No reply backlog contains a pointer into the arena. Plain bytes must already be copied into the real reply buffer/block, and referenced values must have independent DB-object refs tracked through the freeback ring (`src/networking.c:1852-1885`, `src/server.h:2296-2309`).
4. `commandProcessed(fake)` reaches terminal pending-command teardown; blocked commands keep the arena because `commandProcessed` deliberately returns without reset (`src/networking.c:3914-3924`, `src/networking.c:6314-6347`).

The arena must not be a concurrently bumped shared object. The IO coordinator knows sub-`argv` and most coordinator array sizes before publishing queues, so it can allocate them serially. Dynamic worker-sized member gathers must remain worker-private or use one arena/slab per sub and be adopted by the coordinator only after the barrier (`src/server.c:8940-9005`, `src/server.c:8383-8483`). An atomic bump pointer would add cross-core contention to the request path, contradicting both the ownership pattern in the brief and the code's pre-publication construction model (`ARCH_BRIEF.md:38-49`, `src/server.c:8861-8880`).

### Object-destruction rule

Arena placement cannot use `OBJ_STATIC_REFCOUNT`: `incrRefCount` panics when such an object is retained, while cross-shard builders currently retain command/key arguments (`src/object.c:690-700`, `src/server.c:8991-9002`). Nor can ordinary `decrRefCount` run on an arena object, because it unconditionally `zfree`s the object allocation at zero (`src/object.c:704-737`).

The least invasive first implementation is an explicit arena-owned bitmask/side table in `pendingCommand`, restricted initially to audited GET/SET/MGET/MSET routes. Teardown skips individual frees for those slots; cross-shard builders borrow those arguments without refcount increments because the command arena outlives every sub. SET/MSET must pass an explicit “arena source” flag into `kvobjSetEx`: copy into the persistent `kvobj`, never adopt the source SDS, and skip the final source decref (`src/object.c:355-424`). This keeps the common `robj` layout unchanged and makes every escape point explicit.

## Speculative opportunities, not findings

These ideas have concrete allocation counts but no code-proven replacement protocol or workload frequency, so they are deliberately excluded from the ranked findings:

- Set/zset gather's `ΣM_i` member copies could in principle become an owner-tagged iterator/stream or a staged merge, but current reassembly needs private data after all worker barriers and workers cannot safely expose mutable container interiors (`src/server.c:8383-8483`, `src/server.c:10524-10535`). A design must first prove snapshot semantics across concurrent owners.
- The temporary intset/zset materialization could be replaced with a flat coordinator result builder, but the current result depends on encoding conversion, aggregation order, and sorted reply order (`src/server.c:9560-9788`, `src/server.c:10247-10291`). The allocator count alone does not prove that a replacement is faster or simpler.
- Combining `clientReplyBlock` and `listNode` would remove one allocation per spill block, but adlist ownership is used throughout reply handling; a safe intrusive conversion needs a complete audit of duplication, joining, deferred placeholders, and deletion (`src/networking.c:86-96`, `src/networking.c:720-771`, `src/networking.c:1285-1373`, `src/networking.c:1852-1885`).
