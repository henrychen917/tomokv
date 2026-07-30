# Prefetch review: EX and IO sides

## Scope and conclusion

This is a source-only review. I accept, without re-deriving, the architecture brief's conclusions that (1) FLATSTORE is used at more than one EX worker per node while the one-worker-per-node shape is DICT-backed, (2) QSBR protects the flat table and `kvobj` shell but not value interiors, (3) AMAC is rejected for the constant-depth flat lookup, (4) group distance equals current group size, (5) the old gate was effectively 32x rather than 8x L3 and therefore never opened in the measured cells, and (6) the remaining controls are auto-derived (`ARCH_BRIEF.md:25-36`, `ARCH_BRIEF.md:70-81`).

The main result is a storage-regime split:

- At ex=1/DICT, the live worker FSM can warm the dict bucket, entry, and `kvobj`, but its last stage stops at the `kvobj` allocation. It does not warm an out-of-line RAW string payload (`src/server.c:16081-16125`, `src/object.h:99-110`, `src/networking.c:1695-1704`).
- At ex>=2/FLATSTORE, the same FSM warms only the fake/argv/key operand chain. `PFS_HASH` calls `kvstoreGetDict()`, receives the never-created per-bucket dict pointer, and retires before issuing any flat-table, candidate-`kvobj`, or value-payload hint (`src/server.c:16050-16092`, `src/kvstore.c:329-340`, `src/server.h:2222-2231`).
- The custom IO loop has no live prefetch stage at ingress or reply drain. It invokes each fired callback serially, and the earlier same-client reply-prefix prefetch was deleted after being net-negative because it duplicated the splice walk (`src/ae.c:563-584`, `src/server.c:2778-2786`).

The recommended implementation is therefore:

1. Carry the full xxh64 already computed for dispatch, then extend the EX scoreboard with `FLAT_SLOT -> FLAT_KVOBJ -> VALDATA`. Keep the real lookup authoritative; the staged pointer is only a hint (`src/server.c:7318-7332`, `src/flatstore.c:149-158`).
2. Add a DICT `VALDATA` stage after the current `PFS_VALUE`, which should be renamed `PFS_KVOBJ` (`src/server.c:16113-16126`, `src/memory_prefetch.c:228-258`).
3. On IO ingress, group fired connection events and stage `connection -> client -> existing partial querybuf`; do not try to prefetch the normal newly allocated/reusable query buffer (`src/ae.c:563-584`, `src/networking.c:4356-4396`).
4. On IO completion, group heads across different real clients, stage `client -> CDB acquire -> fake -> reply source`, and consume the staged descriptors once. This is materially different from restoring the deleted duplicate same-client prefix walk (`src/server.c:2757-2793`, `src/server.c:2778-2786`).

## Concrete findings

### F1. The ordinary FLATSTORE single-key path receives exactly zero storage prefetches

`exPrefetchBatch()` is called immediately after a worker pops up to 16 fakes and before the serial execution loop (`src/server.h:2145-2149`, `src/server.c:16469-16523`). Its first four states warm the fake, argv vector, key object, and non-EMBSTR key bytes (`src/server.c:16050-16079`). The first storage state then calls `kvstoreGetDict()` and retires on `!d` (`src/server.c:16081-16092`).

In the flat regime, `kvstoreCreate()` allocates the separate flat table while leaving its on-demand `dicts[]` entries null (`src/kvstore.c:329-340`), and `kvstoreGetDict()` is a plain `dicts[didx]` load (`src/kvstore.c:103-105`). Consequently, ordinary ex>=2 GET/SET batches issue **0** flat-slot prefetches, **0** candidate-`kvobj` prefetches, and **0** value-data prefetches. This is the concrete storage hole the EX proposal below fills.

Those misses are presently consumed serially: the generic lookup calls `kvstoreDictFindLink()`, its flat arm computes xxh64 and calls `flatFindForWrite()`, and a matching 15-bit tag immediately causes a candidate pointer/key dereference (`src/db.c:3373-3384`, `src/kvstore.c:1047-1055`, `src/flatstore.c:149-158`). A GET subsequently reads the returned object and its payload while building the bulk reply (`src/t_string.c:448-459`, `src/networking.c:1695-1704`).

### F2. `PFS_VALUE` removes a `kvobj`-shell miss, not the value-data miss named by the state

The current final DICT stage executes `dictGetKey(des[j])` and prefetches that returned address, then transitions directly to DONE (`src/server.c:16122-16126`). A `kvobj` is a header containing the separate `void *ptr` field (`src/object.h:99-110`), while a RAW string reply dereferences `obj->ptr` to read its SDS length and copy/reference its bytes (`src/networking.c:1695-1704`).

Therefore the current stage issues **1** hint for the `kvobj` allocation and **0** hints for a RAW value allocation. The upstream FSM has the missing distinction explicitly: `PREFETCH_KVOBJ` is followed by `PREFETCH_VALDATA`, and its value callback returns `kv->ptr` only for RAW strings (`src/memory_prefetch.c:24-30`, `src/memory_prefetch.c:228-258`, `src/memory_prefetch.c:296-300`). Reusing that separation on the live worker path is concrete and does not introduce AMAC.

### F3. The execution-adjacent next-op prefetch fires zero times in every regime

AUTO makes the distance equal to batch occupancy `n`, while the loop computes `la = j + n` for `j` in `[0,n)` and requires `la < n`; the body is therefore unreachable (`src/server.c:16542-16559`, `src/server.h:2195-2205`). The source records a PMU check: AUTO measured 193.87 and 195.05 prefetch instructions per batch, while strict distance 4 measured 207.65, a **7.1%** increase or about **13** additional hints per batch (`src/server.h:2207-2211`).

Even after correcting that index, it would remain DICT-only because its validity input is populated by `PFS_HASH`, which retires on FLATSTORE (`src/server.h:2219-2232`). The implementation below does not depend on this lookahead; the scoreboard rotation itself supplies the accepted group-sized distance.

### F4. The documented flat M-read wave does not exist in the actual MGET read path

The flat wave design comment describes A0/A1/A2/B/C/D, including a first-probe slot hint and a RAW value-data hint, and calls these waves the only flat-table prefetch issuer (`src/server.c:7414-7469`). The implemented `CS_MGET` coalesced branch instead performs a single loop of `K` serial `lookupKeyReadWithFlags()` calls followed by `sdsdup()`/integer conversion, with **0** `redis_prefetch_*` calls (`src/server.c:8150-8173`).

The wave implementation present in the file is write-only: FLAT MSET/MSETNX uses subwaves of **8**, warms key/value objects and bytes, computes each full hash, prefetches the home slot, and then applies each pair (`src/server.c:8200-8255`). Thus the missing read wave is not merely a stale description: a coalesced `K`-key flat MGET still pays `K` serial table/candidate/payload chains. It should use the same EX helper proposed for single-key groups rather than grow a second, divergent flat probe prefetcher.

### F5. The custom IO path issues zero ingress/reply hints, and the old reply experiment had the wrong traversal shape

The custom IO event loop receives `numevents` and immediately calls each read/write callback one event at a time; there is no prepass between `aeApiPoll()` and callback invocation (`src/ae.c:563-584`). A socket event's `clientData` is the `connection *`, and the client is one more dependent load through `connection.private_data` (`src/socket.c:247-255`, `src/connection.h:100-112`, `src/networking.c:4312-4314`).

The reply drain likewise walks real clients one at a time, acquires each client's ready mask, then consumes its in-order fake prefix (`src/server.c:2692-2697`, `src/server.c:2757-2793`). Its prior prepass walked that same prefix twice and was deleted as net-negative/noise (`src/server.c:2778-2786`). Restoring that code unchanged would reproduce the measured failure. Grouping one head from each of several clients lets the prefetch pass itself become the eventual consumer and supplies independent chains without a duplicate per-client traversal.

### F6. The legacy “dead” prefetcher still has conditional call sites, but it cannot prefetch the Tomo keyspace

`memory_prefetch.c` says all call sites were removed (`src/memory_prefetch.c:85-90`), but `processClientsFromIOThread()` still calls `resetCommandsBatch()` and `prefetchIOThreadCommands()`, which in turn calls `prefetchCommands()` (`src/iothread.c:550-570`, `src/iothread.c:471-508`). That path can be instantiated when the DEBUG `io-threads` setting is greater than 1, because `InitServerLast()` calls `initThreadedIO()` and that initializer returns early only at `io_threads_num <= 1` (`src/config.c:3451-3459`, `src/server.c:4736-4739`, `src/iothread.c:868-884`).

In a Tomo sharded run it batches dictionaries through `kvstoreGetDict(c->db->keys, ...)` (`src/memory_prefetch.c:405-417`), but real clients initially point at the deliberately empty `server.db` decoy; the real data is in the worker/node DBs (`src/server.c:4409-4425`, `src/server.c:6555-6594`). It can therefore count a prefetch batch once `key_count > 1` while warming no real shard storage (`src/memory_prefetch.c:365-376`). This conditional legacy path should be explicitly disabled or relabeled; it should not be reused for the custom IO proposal.

### F7. `pf_issued` is a stage-visit count, not an instruction count

`PFS_STRUCT` emits two builtin prefetches—one for the metadata head and one for the execution-fields line—but sets `issued` only once (`src/server.c:16050-16056`). The loop adds that boolean to `pf_issued` (`src/server.c:16133-16134`). The counter therefore undercounts that state by exactly **1 instruction per issued PFS_STRUCT visit** and cannot distinguish slot, entry, `kvobj`, or payload hints. The rollout instrumentation below needs per-stage instruction counters; otherwise another “enabled but issued nothing” failure remains possible (`src/server.h:2367-2373`).

## Current machinery map

### Storage selection and common gate

`shared_node_dbs` is true when workers per node exceed one; only then is `KVSTORE_FLAT` set on the real keyspace. Expiry storage deliberately masks the flat flag off (`src/server.c:4507-4518`). Thus the review's shorthand is:

- **ex=1 per node:** real keyspace is DICT.
- **ex>=2 per node:** real keyspace is FLATSTORE.
- **expires:** DICT in both shapes (`src/server.c:4507-4518`, `ARCH_BRIEF.md:25-36`).

Every live worker FSM state, including the operand-only states, is behind the DB-footprint gate. The gate records a batch, refreshes its L3-share/value-width controller every 64 batches, estimates this worker's shard share, clears hash validity, and returns before entering the FSM when `est < auto_min` (`src/server.c:15884-15969`). Stage widths otherwise follow current batch occupancy; the value chase is capped from measured L3 share and value-size EWMA (`src/server.c:15971-16006`).

### Live worker batch FSM

The thread is the owning EX worker: `exThreadMain()` runs `exSlice()`, which pops the batch and invokes `exPrefetchBatch()` before execution (`src/server.c:16469-16523`, `src/server.c:16769-16775`). In FLATSTORE mode, the entire slice is inside the worker's flat/QSBR region and table resize exclusion (`src/server.c:16384-16425`, `src/server.c:16763-16765`).

| Stage | Address/hint | Address becomes available after | Command filter | DICT ex=1 | FLAT ex>=2 |
|---|---|---|---|---|---|
| `PFS_STRUCT` | `fake` and `&fake->argc`—**2** hints | Queue pop supplies `fake` | None, if gate open | Reachable | Reachable |
| `PFS_ARGV` | `fake->argv` | One full group rotation after struct hint | `argc >= 2`, non-null argv/db | Reachable | Reachable |
| `PFS_KEYOBJ` | `fake->argv[1]` | argv line is warm | Non-null key | Reachable | Reachable |
| `PFS_KEYBYTES` | `key->ptr` | key object is warm | Skips EMBSTR/null | Reachable | Reachable |
| `PFS_HASH` | `&d->ht_table[0][idx]`; also computes/stashes DICT SipHash | Key bytes are warm; resolves `d` with `kvstoreGetDict()` | Nonempty dict; bucket hint for reads and writes | Reachable | **Retires before hint** |
| `PFS_ENTRY` | Head `dictEntry *` | Bucket line is warm | READONLY only | Reachable | Unreachable |
| `PFS_VALUE` | `dictGetKey(entry)`, i.e. `kvobj *` | Entry line is warm | READONLY and value-width budget | Reachable | Unreachable |

The implementation of all seven states is at `src/server.c:16025-16126`; the read-only chase decision and measured **~35%** pure-SET regression when chasing old write values are recorded at `src/server.c:16098-16106`. This review preserves that filter.

After prefetch, DICT execution arms the stashed SipHash for the actual command lookup (`src/server.c:16203-16210`). The separate execution-adjacent next-op issuer is unreachable for the index reason in F3 (`src/server.c:16542-16559`).

### Other prefetch machinery

| Machinery | Running thread/caller | Stages | Storage reachability |
|---|---|---|---|
| FLAT MSET/MSETNX wave | Owning EX worker inside `csSubExec()` | Groups of 8: key/value object, key/value bytes, full xxh64, home-slot hint, then apply | FLAT only; explicit `kvstoreIsFlat()` branch (`src/server.c:8192-8255`) |
| Coalesced MGET | Owning EX worker inside `csSubExec()` | No live stage; K serial lookups | Both engines, but zero flat/dict hints in this branch (`src/server.c:8150-8179`) |
| Legacy command batch | Stock main thread processing work returned from stock IO threads | client/pending-command; reply/memory fields; argv objects; argv bytes; DICT bucket, entry, kvobj, RAW valdata | Conditional legacy path; real Tomo storage unreachable through decoy DB (`src/iothread.c:471-508`, `src/memory_prefetch.c:340-417`, `src/server.c:4409-4425`) |
| Bit-count streaming hints | Whichever worker/inline thread executes the bit command | Sequential input data, fixed `p + 2048` | Value-local, independent of DICT/FLAT (`src/bitops.c:93-103`, `src/bitops.c:283-295`, `src/bitops.c:332-343`) |

The bit-count hints are complete command-local streaming prefetches, not part of the request/lookup/reply machinery and should remain separate.

## EX-side implementation

### 1. Carry the full flat hash at dispatch

The IO owner already computes xxh64 to route every ordinary keyed command, but `tomoKeyBucket()` returns only the low 14-bit bucket and the remaining hash bits are discarded (`src/server.c:7318-7332`, `src/server.c:7345-7349`). Replace that call with:

```c
uint64_t h = tomoKeyHash(key, sdslen(key));
fake->tomo_hash = h;
fake->tomo_hash_ptr = key;
fake->tomo_bkt = h & TOMO_BUCKET_MASK;
fake->tomo_bkt_ptr = key;
```

`tomoKeyHash()` already exposes the required full xxh64 (`src/server.c:6899-6900`). Add the two full-hash fields beside the existing carried bucket fields, pointer-guard them exactly like `tomo_bkt_ptr`, and clear the pointer at the same post-proc point that clears the bucket hint (`src/db.c:504-516`, `src/server.c:16254-16260`, `src/server.c:16282-16286`). Do **not** reuse `prefetch_key_hash`: that field is DICT SipHash and is consumed by `dictArmHashHint()` (`src/server.h:1695-1702`, `src/server.c:16203-16210`).

This gives the worker the flat home-slot address without re-reading key bytes or hashing. It also enables a later correctness-neutral `kvstoreDictFindLinkWithHash()`/TLS full-hash hint so the actual flat probe can avoid the current second xxh64 at `src/kvstore.c:1047-1053`. The initial prefetch change does not require that optimization.

### 2. Split the FSM by storage engine

Keep the existing `STRUCT -> ARGV -> KEYOBJ -> KEYBYTES` states. At the current `PFS_HASH` boundary, branch on `kvstoreIsFlat(fake->db->keys)`:

- **DICT:** retain the existing `HASH -> ENTRY -> KVOBJ` path, then add `VALDATA`.
- **FLAT:** use `tomo_hash` to enter `FLAT_SLOT -> FLAT_KVOBJ -> VALDATA`.

The flat table is already available through the same accessor used by the implemented MSET wave (`src/server.c:8216-8239`). Suggested bounded scratch per batch is:

```c
flatTable *fts[WORKER_POP_BATCH];
uint64_t flat_words[WORKER_POP_BATCH];
kvobj *flat_candidates[WORKER_POP_BATCH];
```

All arrays remain bounded by the existing maximum of 16 (`src/server.h:2145-2149`).

#### `FLAT_SLOT`

Issue:

```c
redis_prefetch_read(&t->slots[h & t->mask]);
```

for every eligible fake in the current group, then yield to the next fake. This targets the first demand load in `flatFindForWrite()` (`src/flatstore.c:149-154`). One 64-byte line contains eight 8-byte slots (`src/flatstore.h:50-52`), so scanning the expected short probe window after the full group rotation requires no extra dependent prefetch.

After that rotation, atomically load warmed slot words from the home line until EMPTY or a live word with the 15-bit target tag is found. Save only the word/pointer; do not declare a hit and do not alter lookup output. EMPTY remains the probe stop and tag mismatch remains a continue, matching the real probe (`src/flatstore.c:133-145`, `src/flatstore.c:149-159`).

#### `FLAT_KVOBJ`

For the first live matching-tag word, decode its pointer and issue:

```c
redis_prefetch_read(candidate_kv);
```

The expected miss removed is the `kvobj` header plus embedded-key line that `flatKeyMatch()` immediately reads (`src/flatstore.c:125-130`, `src/object.c:245-250`). A wrong candidate can arise only from a 15-bit tag collision in the prefetched probe window—probability **1/32768 per unrelated live slot under uniform tags**, inferred directly from the 15-bit field width (`src/flatstore.h:22-27`, `src/flatstore.h:43-46`). It costs a wrong hint but cannot change the lookup result because the actual command still re-probes and compares the key.

After another full group rotation, compare the warmed candidate's embedded key with the requested key. If it is not exact, stop prefetch chasing for that fake and let the real lookup handle the rare collision/tail. Do not turn this scratch pointer into a lookup result.

#### `VALDATA`

For an exact candidate on a READONLY command, issue a value hint only for:

```c
kv->type == OBJ_STRING &&
kv->encoding == OBJ_ENCODING_RAW &&
kv->ptr != NULL
```

and target `(char *)kv->ptr - 1`, which warms the SDS flags/length-adjacent byte and first payload line. The existing flat wave documents this exact target and why INT/embedded forms do not need it (`src/server.c:7454-7463`). For DICT, rename the current `PFS_VALUE` to `PFS_KVOBJ`, verify that the warmed entry's key is the requested key before reading `kv->ptr`, and then enter the same RAW-only state. That verification is necessary because the current code takes the bucket head and never compares its key before prefetching its `kvobj` (`src/server.c:16113-16125`); upstream's `PREFETCH_VALDATA` already shows the required key comparison and RAW-only callback (`src/memory_prefetch.c:239-258`, `src/memory_prefetch.c:296-300`).

Use the existing auto-derived value-width `w4`; skip this dependent chase when current occupancy is below the structural minimum of 4 (`src/server.c:15986-16006`, `src/server.h:2193-2194`). Preserve the current READONLY check, because chasing the old value on SET previously regressed the pure-write case by about 35% (`src/server.c:16098-16106`).

### 3. EX stage contract

| Proposal | Expected miss removed | Prefetch distance | Earliest safe/known address | Wrong/freed-address rule |
|---|---|---|---|---|
| `FLAT_SLOT` | First flat home-slot cache line, currently first touched by the real probe | One current-group rotation, `g <= 16` | Full hash is known at IO dispatch; table pointer is known on owner EX after `fake->db` is assigned (`src/server.c:6555-6562`, `src/server.c:7318-7332`) | A resize cannot free/swap the table during the enclosing EX flat section (`src/server.c:16413-16425`, `src/server.c:16763-16765`) |
| `FLAT_KVOBJ` | Candidate header + embedded key needed by `flatKeyMatch()` | One additional group rotation after slot hint | Matching 15-bit tag is readable after slot line arrives (`src/flatstore.c:135-142`) | QSBR protects a decoded live/retired `kvobj` for the slice; a tag collision is a non-authoritative wrong hint (`src/flatstore.h:54-59`) |
| `VALDATA` | First RAW SDS line read/copied or referenced by reply construction | One additional group rotation after `kvobj` hint | `kv->ptr` is readable only after exact-key check on warmed `kvobj` (`src/object.h:99-110`, `src/networking.c:1695-1704`) | QSBR does **not** protect the interior (`ARCH_BRIEF.md:32-34`); issue the hint on the owning EX worker before batch execution, never retain/dereference that pointer in the command, and re-probe normally |
| DICT `VALDATA` | Same RAW SDS payload miss at ex=1 | One group rotation after current `PFS_VALUE`/renamed `PFS_KVOBJ` | The proposed exact-key check on the warmed dict entry exposes the target `kvobj`, then its `ptr` (`src/server.c:16113-16126`, `src/memory_prefetch.c:239-258`) | Same hint-only rule; current DICT lookup remains authoritative |

The value-interior rule matters for a batch containing an earlier write followed by a read of the same key. The staged payload may describe the pre-write value and may be freed by that earlier command; the later read must therefore ignore the staged pointer and perform the normal lookup. The already-issued prefetch may be wasted, but no stale load enters reply construction. This is an inference from the serial batch execution order (`src/server.c:16534-16540`) and the brief's explicit non-QSBR interior lifetime (`ARCH_BRIEF.md:32-34`).

### 4. Reuse the flat read stages for coalesced MGET

Factor the flat stages into a helper that accepts `(db, key object, full hash)` arrays and returns only optional candidate hints, not values. Call it from both `exPrefetchBatch()` and the coalesced `CS_MGET` branch. For MGET, use the existing fixed subwave size 8 and then execute the current per-key lookup/copy loop for that subwave (`src/server.c:7470-7483`, `src/server.c:8150-8173`, `src/server.c:8219-8250`).

This converts `K` serial flat chains into `ceil(K/8)` group waves while preserving the scatter-gather ownership rule. It must not reintroduce the deleted non-owner whole-MGET path; the source records **1547/4000** reverse-order violations for that design (`src/server.c:6565-6572`).

## IO-side implementation

The custom IO identities own their event loops and connections; `ioThreadMain()` sets the identity and repeatedly calls `aeProcessEventsIO()` (`src/server.c:17330-17416`, `src/server.c:17427-17465`). No IO proposal below reads the worker's flat table or bypasses owner publication.

### 1. Ingress: group `connection -> client -> partial querybuf`

Add an optional prefetch-kind field to `aeFileEvent`, or an equivalent connection-specific hook, set by the socket/TLS connection registration path. Do not cast arbitrary `aeFileEvent.clientData` to `connection *`: listeners register `NULL`, and notifier events register other types (`src/server.c:17375-17379`, `src/iothread.c:901-906`). Ordinary socket read events do register the connection itself (`src/socket.c:247-255`).

In `aeProcessEventsIO()`, replace the immediate one-event loop with fixed-cap subgroups:

1. `g = min(16, numevents - base)`. If `g < 4`, invoke callbacks normally; the group is too short for the accepted dependent-chain distance (`src/server.h:2145-2149`, `src/server.h:2193-2194`).
2. Pass I0: for tagged connection events, prefetch `connection *conn`.
3. Pass I1 after a full rotation: read the warmed `conn->private_data`, save `client *c`, and prefetch `c` plus the cache line containing input state.
4. Pass I2 after another rotation: if `c->querybuf != NULL` and `sdslen(c->querybuf) > c->qb_pos`, prefetch `c->querybuf + c->qb_pos`.
5. Invoke the existing callbacks in original fired-event order, re-reading `eventLoop->events[fd]` exactly as the current loop does (`src/ae.c:566-584`).

| Ingress hint | Expected miss removed | Distance/why | Address-known point | Lifetime/risk |
|---|---|---|---|---|
| `connection *` | Event `clientData` line containing type/private_data/read handler | `g` independent fired events | Poll output gives fd; event table gives tagged `clientData` (`src/ae.h:51-57`, `src/ae.h:72-85`) | All staging passes finish before any callback can close a connection; hints are not retained for callback use |
| `client *` | Client header/input-state line before `CLIENT_EX_PENDING`, IO flags, and query state checks | One group rotation after connection hint | `connection.private_data` is at `src/connection.h:100-112`; read handler consumes it at `src/networking.c:4312-4323` | IO thread owns the client; async free is processed only after reply/write handling in `beforeSleepIO()` (`src/server.c:2939-2946`) |
| Existing partial querybuf | First unconsumed parser line for a split/large request | One group rotation after client hint | Only clients already carrying a private/partial buffer expose it before callback | Hint only; callback still reloads pointer because `sdsMakeRoomFor*()` can replace it (`src/networking.c:4378-4395`) |

Do **not** add a normal-case querybuf read-prefetch. New clients start with `querybuf == NULL`; the reusable/private buffer is assigned inside `readQueryFromClient()`, then the kernel read writes the new bytes immediately before parsing (`src/networking.c:456-458`, `src/networking.c:4356-4375`, `src/networking.c:4396-4453`). Before the callback the normal buffer address is unknown, and after the read the just-written bytes are already cache-resident. Only an existing partial buffer has a useful pre-callback address.

### 2. Reply completion: group heads across clients

Refactor `handleWorkerReplies()` into subgroup staging over the existing `clients_pending_ex[iotid]` order. The unit of work is **one current in-order head per real client**, not the whole ready prefix of one client:

1. Gather up to `g` real-client pointers and prefetch each real header. Set `g` from current occupancy, capped at 16. If `server.num_cdb` makes `g * num_cdb` exceed the target issue window, use `max(1, 16 / num_cdb)` for this subgroup; `num_cdb` is immutable and each bus is one cache line (`src/server.c:2439-2462`, `src/server.h:1568-1582`).
2. After one rotation, read each warmed `real->reply_cdb` pointer and prefetch the CDB line(s) that `cdbCombinedMask()` will acquire.
3. After one rotation, execute the existing acquire loads. Only if the current ring head's bit is set, load `real->fakeClients[slot]` and prefetch the fake header. Preserve `flushid` order and stop at a not-ready head (`src/server.c:2757-2769`, `src/server.c:2788-2793`).
4. After one rotation, read the now-published fake fields and prefetch `fake->buf`, `fake->reply`, and—if present—the first reply-list node/block.
5. For an encoded first block containing `BULK_STR_REF`, one final rotation can prefetch the referenced RAW `obj->ptr`; the reference is explicitly incremented while the worker builds the reply (`src/networking.c:901-914`, `src/networking.c:932-950`).
6. Consume each staged head through the existing `AddReplyFromClient()`/cross-shard branch, clear ready bits, and retire it. Repeat the wave for deeper ready prefixes.

This traversal does not repeat a ready-prefix scan: the staged head is the head consumed by the existing drain. It also creates independent chains across clients, whereas the deleted design duplicated a single client's prefix (`src/server.c:2778-2786`).

| Reply hint | Expected miss removed | Distance/why | Address-known point | Lifetime/risk |
|---|---|---|---|---|
| Real client + CDB | Real-client ring metadata and worker-written cache-line-isolated ready bus | One `g`-client rotation per dependency | Pending list supplies `real`; warmed real supplies `reply_cdb` (`src/server.c:2692-2697`, `src/server.h:1636-1644`) | Owner IO thread controls the list; CDB must still be read with the existing acquire |
| Ready fake | Worker-written fake header | One rotation after CDB hint/acquire | Head slot and ready bit are known only after `cdbCombinedMask()` (`src/server.c:2757-2763`, `src/server.c:2788-2794`) | Fake ring object remains owned by parent; close path defers reclamation until in-flight fakes retire (`src/server.c:2699-2713`) |
| Static/list reply source | First cache line copied by `AddReplyFromClient()` or read while joining/writing list data | One rotation after fake hint | `fake->buf`, `bufpos`, and `reply` become valid to IO only after acquire | **Never dereference before acquire**: worker may realloc and free `fake->buf` while constructing it (`src/networking.c:859-877`); release/acquire publishes the final pointer (`src/server.c:2757-2759`, `src/server.c:16690-16699`) |
| Referenced value source | First RAW payload line later passed through writev/socket copy | One final group rotation before consume/write | Encoded reply block exposes `bulkStrRef.obj`, whose ref was taken by worker (`src/networking.c:903-914`) | Lifetime is refcount/freeback, not QSBR; IO returns the reference to the owner EX worker only after send (`src/networking.c:2941-2965`) |

`AddReplyFromClient()` copies `src->buf` and O(1)-joins the reply list (`src/networking.c:1852-1885`), then the drain calls `writeToClient()` once for the accumulated real reply (`src/server.c:2883-2893`). Prefetch the cold source, not the destination: the destination was just written during the splice. The writev builder later walks the real reply list and payload blocks (`src/networking.c:2980-3037`).

Multi-stage cross-shard heads require one guard: if `csPipeAdvance()` or `csLaunchHop2()` keeps the head in flight, consume no later slot from that real in this wave, exactly matching the current in-order break behavior (`src/server.c:2829-2847`). Other clients in the subgroup remain independent.

### 3. QSBR and ownership summary for IO

QSBR is not the lifetime mechanism for either IO proposal. Connection/client safety comes from IO ownership and staging all hints before callbacks; reply safety comes from the worker's release bit, the IO acquire, fake-ring drain deferral, and reference pin/freeback (`ARCH_BRIEF.md:38-49`, `src/server.c:2699-2713`, `src/server.c:2757-2759`, `src/networking.c:2941-2965`).

The hard rule is: a prefetch instruction may target a speculative address, but obtaining that address must itself obey ownership and publication. In particular, reading `fake->buf`, a reply-list node, or `bulkStrRef.obj` before the CDB acquire is invalid even though the eventual operation is “only a prefetch,” because the prerequisite pointer load races worker construction (`src/networking.c:859-877`, `src/server.c:16690-16699`).

## Instrumentation and rollout

Add per-worker counters for `pf_struct`, `pf_argv`, `pf_keyobj`, `pf_keybytes`, `pf_dict_bucket`, `pf_dict_entry`, `pf_flat_slot`, `pf_kvobj`, `pf_valdata`, plus `flat_tag_candidate`, `flat_exact_candidate`, and `flat_tail_fallback`. Count actual builtin calls, not FSM visits, correcting F7's exact one-instruction discrepancy (`src/server.c:16050-16056`, `src/server.c:16133-16134`).

Add IO-owner counters/histograms for:

- fired-event group occupancy 1..16 and partial-querybuf eligibility;
- reply subgroup occupancy, CDB lines hinted, heads ready, fake hints, static-buffer hints, list-block hints, and bulk-ref value hints;
- skipped groups below 4.

These are single-owner per-thread stats, matching the architecture's existing owner-written signal pattern (`ARCH_BRIEF.md:38-49`, `src/server.c:17435-17445`).

Roll out as separately compilable changes in this order:

1. observability only;
2. full flat-hash carry plus `FLAT_SLOT`;
3. `FLAT_KVOBJ`;
4. RAW `VALDATA` on FLAT and DICT;
5. coalesced MGET reuse;
6. IO ingress client grouping;
7. IO cross-client reply grouping.

Each step has a concrete nonzero-issued predicate before throughput comparison. Use the brief's required ops/s verdict and both standard regimes: io4/ex4 p32 for FLAT and io7/ex1 p1 for DICT (`ARCH_BRIEF.md:85-93`). For IO stages, also report group-occupancy histograms; a throughput result with almost all groups below 4 tests eligibility, not prefetch efficacy.

## Speculative or measurement-dependent items

The following are not findings because the source does not provide a concrete miss count or benefit:

- **IO client-line benefit.** The connection-to-client chain is concrete, but whether those two objects miss often enough depends on fired-event fanout and cache residency. The occupancy/miss counters must decide whether I0/I1 ship.
- **`PREFETCHW` for the querybuf append destination.** The final address is known only after `sdsMakeRoomFor*()` and immediately before `connRead()` (`src/networking.c:4378-4396`), leaving little software distance; the normal reusable buffer is also likely hot. Do not include it in the first implementation.
- **A second flat slot-line hint.** A home-line hint covers eight slots, but this review did not measure the fraction of probes crossing that line (`src/flatstore.h:50-52`). Use `flat_tail_fallback` before adding another hint.
- **More than the first RAW payload line.** Reply copy/send streams the remaining bytes, and additional hints could consume bandwidth/LFB capacity. The existing value-size controller already narrows the chase for large values (`src/server.c:15986-16006`); start with one line.
- **Batching `handleClientsWithPendingWrites()`.** That function also walks clients serially (`src/networking.c:3310-3353`), but worker completion already calls `writeToClient()` directly after splice (`src/server.c:2883-2893`). Measure residual pending-write volume before extending the IO group prefetcher there.
