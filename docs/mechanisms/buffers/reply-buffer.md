# `client->buf`, `client->reply`, `clientReplyBlock`, and `replBufBlock`: reply buffers

## What the names mean

The ordinary client reply mechanism is a two-tier output queue: `client->buf` is a pointer to a heap allocation whose used prefix is `client->bufpos`, and `client->reply` is a list used after that first allocation cannot accept more data. The `client` core also records `reply_bytes`, `sentlen`, `buf_peak`, `buf_usable_size`, `buf_encoded`, and `last_header` to account for, transmit, resize, and decode those two tiers. (`src/server.h:1877-1921`)

Despite helper comments that call `client->buf` the "static buffer," it is not an inline array: `createClient` requests a heap allocation with `zmalloc_usable(PROTO_REPLY_CHUNK_BYTES, &buf_usable_size)`, and `PROTO_REPLY_CHUNK_BYTES` is 16,384 bytes. (`src/networking.c:503-534`, `src/server.h:181-185`)

The ordinary spill nodes are `clientReplyBlock`, not `replBufBlock`; each ordinary block has `size`, `used`, `buf_encoded`, and a flexible `buf[]` payload, and the list stored in `client->reply` owns those blocks. (`src/server.h:1120-1126`, `src/networking.c:89-99`, `src/networking.c:594-599`)

`replBufBlock` is a separate, shared replication-stream mechanism used collectively by replicas and the replication backlog; the replica write path asserts that the private `client->buf` and `client->reply` are empty. (`src/server.h:1128-1174`, `src/networking.c:2033-2051`, `src/networking.c:3410-3415`)

## Exact layouts and footprints

### The client-local first tier

`client->buf` is a `char *`; its exact allocated capacity is the allocator-reported `buf_usable_size`, not necessarily the requested size, and `bufpos` is its physical used end. For a plain oldest buffer, `sentlen` is the physical byte offset already sent; for an encoded oldest buffer, `last_header` identifies the current encoded chunk and `sentlen` counts logical bytes already consumed from that chunk's expanded output payload. (`src/server.h:1893-1901`, `src/server.h:1914-1921`, `src/networking.c:3231-3344`)

A real client initially requests 16 KiB. The cron resizer may shrink a plain buffer to `max(1,024, buf_peak + 1)` when half the current usable capacity is at least 1,024 and `buf_peak` is below that half; it may grow to `min(16,384, 2 * buf_usable_size)` only when the doubled size is below 32,768 and the observed peak equals the current usable capacity. (`src/server.h:183-189`, `src/server.c:2175-2208`)

The cron resizer does nothing when resizing is disabled, an io_uring send still references the allocation, or the buffer is encoded; a chosen replacement copies exactly `bufpos` bytes into a new allocator-sized block. (`src/server.c:2182-2197`, `src/server.c:2211-2227`)

A full or core fake client instead requests `FAKE_BUF_START_BYTES`, exactly 1,024 bytes, and both forms separately create an initially empty reply list. (`src/server.h:183-185`, `src/networking.c:339-350`, `src/networking.c:354-419`)

Before appending a plain payload to a fake whose list is still empty, `_addReplyToBufferOrList` doubles a prospective buffer size until it covers `bufpos + len` or reaches `FAKE_BUF_MAX_BYTES` (65,536), clamps to that maximum, copies the old used prefix, and swaps allocations; any remainder still spills to the list. (`src/networking.c:965-988`, `src/server.h:183-185`)

Neither `client->buf` nor its allocation call has an explicit cache-line alignment or padding contract. Unless externally predefined, `CACHE_LINE_SIZE` is 64 bytes normally and 128 bytes on Apple AArch64, so the requested 16-KiB real-client allocation spans 256 64-byte-line equivalents or 128 128-byte-line equivalents, while the requested 1-KiB fake allocation spans 16 or 8 respectively; allocator usable-size rounding can make the actual allocation larger. (`src/config.h:38-44`, `src/networking.c:346-347`, `src/networking.c:534-534`)

### `client->reply`, `list`, and `listNode`

`client->reply` has type `list *`. In declaration order, `listNode` contains `listNode *prev`, `listNode *next`, and `void *value`; `list` contains `listNode *head`, `listNode *tail`, function pointers `dup`, `free`, and `match`, then `unsigned long len`. These fields are non-atomic. On LP64 the ABI-derived footprints are 24 bytes per `listNode` and 48 bytes for the `list` header; neither has a source size assertion or cache-line alignment contract. (`src/server.h:1893-1895`, `src/adlist.h:16-34`)

### `clientReplyBlock`

The exact declared order is two `size_t` fields (`size`, `used`), one `char` (`buf_encoded`), then flexible payload `char buf[]`; there are no atomic fields and no explicit packing or alignment attributes. (`src/server.h:1120-1126`)

On an LP64 ABI, `sizeof(clientReplyBlock)` is 24 bytes by field-size/alignment derivation: 16 bytes for the two `size_t` values, one flag byte, and seven bytes of structure tail padding. The flexible `buf[]` member itself has offset 17; the allocation formula nevertheless subtracts the 24-byte `sizeof` value when deriving logical capacity, leaving those seven bytes unused at the allocation end. These values are ABI-derived, not guarded by a source `_Static_assert`. (`src/server.h:1120-1126`, `src/networking.c:859-875`)

A new list block requests `max(required_size, 16,384) + sizeof(clientReplyBlock)` bytes, where `required_size` is `len` for a plain payload and `len + sizeof(payloadHeader)` for an encoded payload; `size` is then set to the allocator's usable size minus the fixed header. (`src/networking.c:859-877`, `src/server.h:183-183`)

`reply_bytes` accounts for block capacity (`tail->size`), and `getClientOutputBufferMemoryUsage` reports `reply_bytes + listLength(reply) * (sizeof(listNode) + sizeof(clientReplyBlock))`. That is the coded accounting formula, not exact allocator consumption: actual memory also includes allocator rounding/metadata for each block and node plus the separately allocated 48-byte LP64 list header. (`src/networking.c:876-879`, `src/networking.c:6169-6184`, `src/adlist.c:22-33`, `src/adlist.c:76-84`)

`clientReplyBlock` has no cache-line isolation; a minimum 16-KiB logical payload spans at least 256 64-byte lines or 128 128-byte lines, and its ABI-derived fields and flexible payload share one allocation. (`src/config.h:38-44`, `src/server.h:1120-1126`, `src/networking.c:859-877`)

### Encoded payloads

An encoded buffer is a sequence of packed `payloadHeader { size_t payload_len; uint8_t payload_type; }` followed immediately by that payload; the two payload types are `PLAIN_REPLY` and `BULK_STR_REF`. On LP64 the packed header is exactly 9 bytes. (`src/server.h:1089-1104`)

`bulkStrRef` is packed and stores, in order, `robj *obj`, `unsigned int prefix_cnt`, `char prefix[LONG_STR_SIZE + 3]`, `char crlf[2]`, and `int owner_ex`; a nonnegative `owner_ex` identifies a worker to which the eventual decrement must be returned. With `LONG_STR_SIZE == 21`, its LP64 footprint is 42 bytes. (`src/server.h:1105-1118`, `src/util.h:31`, `src/networking.c:1007-1032`)

`tryAddPayload` accepts a payload exactly when `used + sizeof(payloadHeader) + len <= size`, writes the header and bytes, and advances `used` by that exact sum. (`src/networking.c:814-824`)

### `replBufBlock`

The declared fields are non-atomic `int refcount`, `long long id`, `long long repl_offset`, `size_t size`, `size_t used`, and flexible `char buf[]`. (`src/server.h:1165-1174`)

On the repository's LP64 ABI the fixed header is 40 bytes by layout derivation: four bytes for `refcount`, four bytes of alignment, then four eight-byte fields; this is inferred from the declaration and is not guarded by a source assertion. (`src/server.h:1165-1174`)

When replication bytes need a new block, the requested payload size is `min(max(len, 16,384), max(repl_backlog_size / 16, 16,384))`; allocation requests that value plus `sizeof(replBufBlock)`, and the stored capacity becomes allocator usable size minus the header. (`src/replication.c:517-534`, `src/server.h:183-183`)

`replBufBlock` likewise has no cache-line alignment or padding attribute. Its minimum requested 16-KiB payload spans at least 256 ordinary 64-byte-line equivalents or 128 128-byte-line equivalents, and its ABI-derived 40-byte header precedes the payload in the same allocation; allocation placement supplies no guarantee that the header occupies one line or which line the payload first shares. (`src/config.h:38-44`, `src/server.h:1165-1174`, `src/replication.c:517-528`)

## Ordinary `addReply` protocol

1. `addReply(c, obj)` first calls `_prepareClientToWrite`; it appends nothing if that function returns `C_ERR`. (`src/networking.c:1067-1082`)
2. `_prepareClientToWrite` permits script/module pseudo-clients, rejects `CLIENT_CLOSE_ASAP`, silenced replies unless `CLIENT_PUSHING`, masters unless force-reply is set, and clients with no connection. A `CLIENT_EX_PENDING` fake returns `C_OK` without entering a socket-write queue; otherwise a main-running client with no older reply is linked to its IO owner's pending-write list. (`src/networking.c:748-781`)
3. For an SDS-encoded object, `addReply` passes `obj->ptr` and `sdslen(obj->ptr)` to `_addReplyToBufferOrList`; for `OBJ_ENCODING_INT`, it formats into a 32-byte stack array and passes the produced byte count; any other encoding panics. (`src/networking.c:1067-1082`)
4. `_addReplyToBufferOrList` returns immediately for `CLIENT_CLOSE_AFTER_REPLY`; if the destination is a replica, it schedules that invalid connection for asynchronous close rather than putting command output in the private reply queue. (`src/networking.c:933-945`)
5. A push for any current client carrying `CLIENT_PUSHING` is diverted to `server.pending_push_messages` when that client is `server.current_client[iotid].p`, an executing client exists, and the executing command does not itself have a push as its reply. The executable condition does not separately require a subscription flag. (`src/networking.c:883-890`, `src/networking.c:952-963`)
6. After the fake-only growth rule described above, `_addReplyPayloadToBuffer` can use `client->buf` only while `client->reply` is empty. In plain mode it copies `min(buf_usable_size - bufpos, len)` bytes; in encoded mode it accepts only an entire header-plus-payload through `tryAddPayload`. (`src/networking.c:893-914`, `src/networking.c:965-988`)
7. If `len > reply_len`, the exact suffix `[s + reply_len, s + len)` is offered to `client->reply`. A compatible plain tail may copy only the portion that fits and leave a remainder for a new block; an encoded tail accepts the entire `header + payload` through `tryAddPayload` or accepts none of it. Any remainder causes a new minimum-16-KiB block allocation. (`src/networking.c:814-824`, `src/networking.c:838-880`, `src/networking.c:986-988`)
8. Every ordinary append adds `len` to the current command's network-output accounting, and each block allocation immediately checks the client output-buffer limit. (`src/networking.c:947-950`, `src/networking.c:876-880`)

The protocol-building APIs layer on this primitive: `addReplyProto` prepares then calls `_addReplyToBufferOrList`, bulk helpers emit a length header, body, and CRLF, and aggregate-length helpers select the RESP prefix before writing the integer. (`src/networking.c:1103-1108`, `src/networking.c:1607-1664`, `src/networking.c:1799-1846`)

## Referenced bulk strings and free-back

For a copy-avoiding bulk reply, `_addBulkStrRefToBufferOrList` increments the object reference, records the executing worker as `owner_ex` when the destination is a worker fake, and formats the bulk prefix and suffix. (`src/networking.c:1007-1032`)

A worker fake is forced to store that reference in a list block rather than its first-tier buffer, because later fake-to-real transfer joins the list without copying while the first-tier path copies bytes. (`src/networking.c:1038-1047`, `src/networking.c:1956-1990`)

Once transmission has consumed the whole referenced payload, `owner_ex >= 0` routes the object to `freebackPush`; otherwise, if `c->running_tid != IOTHREAD_MAIN_THREAD_ID`, `ioDeferFreeRobj` defers it, and the remaining main-running branch calls `decrRefCount` directly. (`src/networking.c:3231-3277`)

That worker-return channel is documented separately in [the `freebackRing` mechanism](freeback-ring.md). (`src/server.h:2479-2492`)

## Fake-to-real reply handoff

An ordinary worker-routed fake builds replies in its own `buf` and `reply` allocations, then release-publishes that fake's completion slot; the owning IO thread acquire-tests completion before touching those reply fields. Cross-shard group heads and synchronous inline fakes use the same CDB handoff but have distinct producers described by the fake-ring mechanism. (`src/server.c:22055-22061`, `src/server.c:22242-22252`, `src/server.c:4236-4241`, `src/server.c:8478-8482`, `src/server.c:8605-8640`)

For an ordinary completed fake, `handleWorkerReplies` calls `AddReplyFromClient(real, fake)` in ring order. (`src/server.c:4236-4311`)

`AddReplyFromClient` schedules the destination for asynchronous close and returns when the source already has `CLIENT_CLOSE_ASAP`. It also returns if either destination preparation fails, or after the first-tier copy if the destination then has `CLIENT_CLOSE_AFTER_REPLY`; only the successful path copies `src->buf[0..bufpos)`, passes the second preparation, and `listJoin`s all source list nodes into the destination in O(1) ownership transfer. (`src/networking.c:1956-1988`)

On that successful splice path, the function adds the source's capacity accounting to the destination, zeros `src->reply_bytes` and `src->bufpos`, transfers deferred error records when present, and rechecks the destination's output limit. (`src/networking.c:1985-2000`)

After `AddReplyFromClient` returns—whether it spliced or took an early exit—the IO drain clears the completion byte, resets the fake command, and advances `flushid`. Thus a fake slot is never reused while the handoff function may still read its reply storage. (`src/networking.c:1958-2000`, `src/server.c:4320-4341`)

The carrier ring and completion edge are documented in [the fake-client ring](fake-client-ring.md) and [the `cdbSlots` completion mechanism](cdb-completion-slots.md). (`src/server.c:4221-4241`, `src/server.c:4334-4341`)

## Ownership and thread handoffs

The ordinary `client->buf`, `client->reply`, their list nodes, and `clientReplyBlock` fields are non-atomic and are mutated by the client owner. Worker execution never concurrently appends to a real client's queue: it writes a fake's private queue and release-publishes completion; the I/O owner acquire-consumes it, runs the handoff (conditionally splicing or taking a coded early return), and only then clears and reuses the fake. (`src/server.h:1893-1921`, `src/networking.c:1956-2000`, `src/server.c:3149-3168`, `src/server.c:4236-4341`)

Replication blocks and their `refcount` are also non-atomic. Main records a replica's starting cursor plus a bounded ending node/position before setting `running_tid` and enqueuing the client; transfer into the I/O thread's pending list is protected by `pending_clients_mutex`, and the I/O thread takes that mutex before joining the list into its processing set. The I/O sender reads only through the snapshot bound and changes only its private cursor, leaving block refcounts and the shared list untouched. On the return path, the I/O thread joins the client under `mainThreadPendingClientsMutexes[t->id]`; main takes that same mutex before processing the client, sets `running_tid` to main, and conditionally reconciles the cursor and refcounts. (`src/server.h:1128-1174`, `src/iothread.c:26-34`, `src/iothread.c:69-79`, `src/iothread.c:127-150`, `src/iothread.c:459-471`, `src/iothread.c:555-610`, `src/iothread.c:724-727`, `src/networking.c:3410-3430`)

## Socket-consumption protocol

`clientPrepareReplyIOV` exposes the unsent first-tier prefix first, then walks `client->reply` in list order; plain blocks contribute byte ranges and encoded blocks are expanded into their constituent output ranges. (`src/networking.c:3120-3182`)

For the synchronous/non-io_uring write path, a nonempty reply list uses `connWritev`; a plain first-tier-only reply uses `connWrite`, while an encoded first tier also uses the vector path. (`src/networking.c:3349-3402`)

`clientConsumeReplyBytes` advances `sentlen`, resets a fully consumed first tier, removes fully consumed list blocks while subtracting their capacity from `reply_bytes`, and leaves a partial encoded payload pinned through `last_header` and `sentlen`. (`src/networking.c:3282-3347`)

The vector-write path calls that retirement routine immediately after a successful `connWritev`. (`src/networking.c:3349-3364`)

## Replication-buffer protocol

`feedReplicationBuffer` returns when no backlog exists; otherwise it repeatedly fills unused tail capacity, then allocates blocks with the formula above until all input bytes have been copied, updating `master_repl_offset` and backlog history length by each copied count. (`src/replication.c:484-547`)

Each new block starts with `refcount = 0`, a monotonically assigned `id`, `repl_offset = old master_repl_offset + 1`, and `used = min(capacity, remaining len)`. (`src/replication.c:484-485`, `src/replication.c:524-545`)

A replica stores its starting node and `ref_block_pos`, then increments that block's non-atomic `refcount`. The backlog stores only `ref_repl_buf_node`; its first attachment asserts a newly added block and `start_pos == 0`, then increments that block's count. (`src/replication.c:549-576`)

The main-thread replica sender writes from `ref_block_pos`; after fully consuming a block and finding a successor, it decrements the old node, increments the successor, advances the cursor, and attempts incremental trimming. (`src/networking.c:3433-3450`)

When a replica is assigned to an IO thread, main snapshots a bounded end node and byte position plus an IO-private current cursor; the IO sender advances those private cursors without changing block refcounts. When the client returns, main performs one old-node decrement/new-node increment and copies the byte position only if either the node or byte cursor moved. (`src/iothread.c:127-150`, `src/networking.c:3414-3430`, `src/iothread.c:69-79`)

Trimming stops if only one block remains, the head `refcount` is not exactly one (the backlog's own reference), or removing its full capacity would reduce retained history to the configured backlog size or below; otherwise it transfers the backlog reference to the successor and deletes the old full block. (`src/replication.c:409-456`)

## Enforced invariants

- Once list-backed reply data exists, later bytes do not return to the first-tier buffer, preserving output order. (`src/networking.c:895-900`)
- `size` is capacity and `used` is physical occupied bytes: a new plain block initializes it to `len`, while a new encoded block advances it by `sizeof(payloadHeader) + len`; plain appends never copy more than `size - used`. (`src/networking.c:814-824`, `src/networking.c:838-875`)
- Encoded payloads are admitted atomically as `header + payload`, and the decoder asserts that each declared payload fits before the end of its containing buffer. (`src/networking.c:814-824`, `src/networking.c:3192-3208`)
- A worker-owned referenced value receives its matching decrement on the owning worker, not on the sending IO thread. (`src/networking.c:1012-1020`, `src/networking.c:3258-3272`)
- Replica clients use the shared replication list and keep both private ordinary reply tiers empty. (`src/networking.c:2033-2051`, `src/networking.c:3410-3415`)
- Replication trimming is a head-only operation and deletes a block only after its reference count is zero and `used == size`. (`src/replication.c:425-456`)

## Callers and users

Command implementations call `addReply` and its protocol-specific family through the declarations in `server.h`; concrete wrappers include status/error, integer, aggregate, bulk, and verbatim reply builders. (`src/server.h:5028-5067`, `src/networking.c:1119-1347`, `src/networking.c:1545-1900`)

Ordinary worker replies converge on `AddReplyFromClient` during ordered ring drain. Cross-shard reassembly uses it only for branches that retain sub-client buffers, such as legacy MGET, KEYS, and local-fast; coalesced MGET and aggregate MSET/DEL/EXISTS branches emit directly on the destination instead. (`src/server.c:4236-4311`, `src/server.c:14947-14978`)

Replication propagation calls `feedReplicationBuffer` directly or through `feedReplicationBufferWithObject`; it deliberately replaces the ordinary `addReply*` path for replicas and the backlog. (`src/replication.c:387-402`, `src/replication.c:479-484`)
