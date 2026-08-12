# `PFS_*` — the worker lookup-prefetch scoreboard states

## Exact mechanism name and shape

The state machine inside `exPrefetchBatch()` is an unnamed enum whose exact identifiers, in numeric order, are `PFS_STRUCT = 0`, `PFS_ARGV`, `PFS_KEYOBJ`, `PFS_KEYBYTES`, `PFS_HASH`, `PFS_FLAT_KVOBJ`, `PFS_ENTRY`, `PFS_VALUE`, and `PFS_DONE`. In plain English, it is the per-fake state set for a round-robin worker-side software-prefetch scoreboard. (`src/server.c:21256-21279`)

There is no `PFS_FLAT` identifier in the pinned source: the FLAT second stage is named `PFS_FLAT_KVOBJ`. Likewise, the coded common order puts `PFS_KEYBYTES` before `PFS_HASH`; the shorter names/order in the mechanism brief are not the live enum. (`src/server.c:21268-21278`)

This has an AMAC-like per-lookup state record and interleaved pointer-chase steps, but it is not refill-style AMAC. The batch population is fixed for the invocation: completed entries retire, no fresh lookup refills their slots, and the loop ends when all `n` original entries reach `PFS_DONE`. The source describes it as group/scoreboard prefetch and reserves refill-style AMAC for a future variable-depth structure. (`src/server.c:21256-21275`, `src/server.c:21286-21293`, `src/server.c:21421-21424`, `src/server.h:2341-2359`)

## State and scratch layout

`WORKER_POP_BATCH` is 16, and the caller's persistent pop buffer is `client *batch[WORKER_POP_BATCH]` inside the worker-local `exSliceCtx`. On an LP64 build its declared pointer payload is 128 bytes, equal to two 64-byte line widths or one 128-byte Apple-AArch64 line width. The field has no independent alignment attribute, so an unaligned placement can make that payload intersect an additional boundary line. (`src/server.h:2329-2333`, `src/server.c:21680-21711`, `src/config.h:38-43`)

After the mode-0 return, `exPrefetchBatch()` declares these bounded automatic scratch arrays. (`src/server.c:21120-21139`)

| Scratch object | Exact declaration and meaning | Declared payload on LP64 |
| --- | --- | --- |
| `storage` | A 16-element union of `dict *d` and `flatSlot *slot`; each lookup uses the member selected by `PFS_HASH`. (`src/server.c:21134-21137`, `src/server.c:21343-21345`, `src/server.c:21379`) | `16 * sizeof(void *)` = 128 bytes. |
| `idxs` | `unsigned long idxs[16]`; holds either a DICT bucket index or the FLAT 15-bit tag. (`src/server.c:21138`, `src/server.c:21345`, `src/server.c:21370-21371`) | `16 * sizeof(unsigned long)` = 128 bytes. |
| `des` | `dictEntry *des[16]`; carries a DICT bucket-head result from `PFS_ENTRY` to `PFS_VALUE`. (`src/server.c:21139`, `src/server.c:21402-21414`) | `16 * sizeof(void *)` = 128 bytes. |
| `st` | `uint8_t st[16]`; one enum value per original batch position. (`src/server.c:21277-21285`) | Exactly 16 bytes. |

The four arrays therefore have 400 bytes of declared LP64 payload, excluding ordinary stack-frame padding and scalars. None has `aligned(CACHE_LINE_SIZE)` or cache-line padding, so the code does not promise isolated lines or even line-aligned array starts; the compiler's automatic-object layout decides which 64- or 128-byte lines they touch. (`src/server.c:21134-21139`, `src/server.c:21277-21289`, `src/config.h:38-43`)

The persistent per-fake outputs are `uint64_t prefetch_key_hash`, `dict *prefetch_dict`, the union member `unsigned long prefetch_bucket_idx`, and `int prefetch_key_hash_valid` in the 320-byte `client` execution core. On 64-bit layouts the code asserts `prefetch_key_hash` begins at offset 136, placing the hash/dict/index group in the core's third 64-byte layout region; validity is a later integer in the core. (`src/server.h:1875-1947`, `src/server.h:1953-1966`)

The FLAT carrier is `struct flatSlot { _Atomic uint64_t w; }`, encoded as a 15-bit tag, one tomb bit, and a 48-bit masked pointer. Its logical payload is 8 bytes and eight such words total 64 payload bytes, but the source has no `sizeof(flatSlot)` assertion. `flatTableNew()` obtains the slot array with ordinary `zcalloc`, and neither the type nor that allocation call requests cache-line alignment, so the executable code does not enforce the header comment's “64B-aligned” description or guarantee that the allocation starts on a line boundary. (`src/flatstore.h:47-58`, `src/flatstore.h:106-117`, `src/flatstore.c:70-76`)

All scoreboard arrays and DICT scratch accesses are worker-local ordinary objects with no atomic ordering. The sole storage-stage atomic read is the `memory_order_acquire` load of `flatSlot.w` in `PFS_FLAT_KVOBJ`. FLAT insert publishes a new tag/pointer word with an acquire-release compare-exchange, while overwrite and delete publish replacement/tomb words with release stores; the FSM's acquire read uses that storage publication but consumes the word only as a hint. The prefetch hints themselves expand to high-locality `__builtin_prefetch` calls when supported and no-op expressions otherwise. (`src/server.c:21385-21396`, `src/flatstore.c:239-285`, `src/config.h:120-136`)

## Round-robin issue protocol

1. Initialize every `st[j]` to `PFS_STRUCT`, clear `storage[j].d`, clear `des[j]`, clear each fake's `prefetch_key_hash_valid`, and set `remaining = n`. (`src/server.c:21279-21286`)
2. Start `cur = 0`. Each outer iteration selects `j = cur`, wraps `cur` modulo `n`, and skips positions already at `PFS_DONE`. (`src/server.c:21288-21294`)
3. For the selected lookup, set local Boolean `issued = 0` and advance stages in an inner loop until either the stage sets `issued` or the lookup reaches `PFS_DONE`. Guard failures and stages that issue no hint therefore fall through in the same visit. (`src/server.c:21294-21297`, `src/server.c:21304-21329`, `src/server.c:21417-21421`)
4. Add that Boolean to `pfw->pf_issued`. A visit counts at most one even when its stage emits two hints, as `PFS_STRUCT` does. (`src/server.c:21298-21303`, `src/server.c:21421-21423`)
5. When the selected state is `PFS_DONE`, decrement `remaining`; terminate when it reaches zero. (`src/server.c:21290-21293`, `src/server.c:21421-21424`)

This rotation gives a hint from one lookup time to land while other lookup states advance. The code does not wait for, test completion of, or consume a result from the prefetch instruction itself. (`src/server.c:21256-21265`, `src/config.h:130-136`)

## Exact stages

| State | Transition, branch conditions, and exact hint |
| --- | --- |
| `PFS_STRUCT` | Set the next state to `PFS_ARGV`; issue `redis_prefetch_read(fake)` and `redis_prefetch_read(&fake->argc)`; set `issued = 1`. The base address is in the first 64-byte layout region, which contains `db` and `argv` at offsets 32 and 56 on the asserted 64-bit layout; `argc` is separately asserted at offset 276 in the fifth region. (`src/server.c:21298-21303`, `src/server.h:1884-1892`, `src/server.h:1923-1933`, `src/server.h:1953-1966`) |
| `PFS_ARGV` | If `argc < 2`, `argv == NULL`, or `db == NULL`, go directly to `PFS_DONE` with no hint. Otherwise set `PFS_KEYOBJ` and prefetch the `argv` vector base. (`src/server.c:21304-21310`) |
| `PFS_KEYOBJ` | Read `k = fake->argv[1]`; a null key retires. Otherwise set `PFS_KEYBYTES` and prefetch the `robj` header at `k`. (`src/server.c:21311-21317`) |
| `PFS_KEYBYTES` | Set `PFS_HASH`. If the key is not `OBJ_ENCODING_EMBSTR` and `k->ptr` is non-null, prefetch `k->ptr` and yield this visit; an embedded or null-pointer case emits no hint and falls straight through to `PFS_HASH`. (`src/server.c:21319-21328`, `src/object.h:80-93`) |
| `PFS_HASH` — FLAT branch | Let `kvs = fake->db->keys` and `key = fake->argv[1]`. Only when `fake->tomo_bkt_ptr == key->ptr`, `kvstoreFlatTable(kvs)` is non-null, and `t->slots` is non-null does this branch use carried `tomo_key_h`: `slot = &t->slots[h & t->mask]`, `idxs[j] = flat_tag_of(h)`. A read-only command advances to `PFS_FLAT_KVOBJ`; every other command advances to `PFS_DONE`. In both cases it prefetches the 8-byte home slot and increments `issued_slot`. (`src/server.c:21329-21353`) |
| `PFS_HASH` — DICT branch | If FLAT did not take the branch, select a dict with `kvstoreGetDict`: in the supported worker mode use carried `tomo_bkt` when the key-pointer proof matches, otherwise recompute `tomoKeyBucket`; the no-worker fallback uses positive `fake->slot` or zero. A null/empty dict or null table retires. Otherwise compute `h = dictGetHash`, store the hash/valid bit/dict/bucket index on the fake, select `PFS_ENTRY` only for a non-null read-only command (writes select `PFS_DONE`), and prefetch `&d->ht_table[0][idx]`. (`src/server.c:21355-21383`) |
| `PFS_FLAT_KVOBJ` | Acquire-load `storage[j].slot->w`, then set `PFS_DONE`. Only if `FLAT_IS_LIVE(w)` and `flat_word_tag(w) == idxs[j]` does it decode `dictGetKV(flat_word_ptr(w))`; a non-null result is prefetched and increments `issued_kvobj`. No key comparison or authoritative lookup result is produced here. (`src/server.c:21385-21400`, `src/flatstore.h:47-58`) |
| `PFS_ENTRY` | Read `de = storage[j].d->ht_table[0][idxs[j]]`. Null retires. Otherwise save `des[j]`, choose `PFS_VALUE` only when the original batch index satisfies `j < w4`, and prefetch `de`; indices outside the adaptive width retire after this hint. (`src/server.c:21402-21409`) |
| `PFS_VALUE` | Decode `kv = dictGetKey(des[j])`, set `PFS_DONE`, and prefetch `kv` only when non-null. In this DB dictionary, keys and values are unified `kvobj` objects and `dictGetKV` is the typed wrapper around `dictGetKey`. (`src/server.c:21411-21415`, `src/server.c:1850-1862`, `src/server.h:5850-5851`) |
| `PFS_DONE` | Issue nothing. The outer loop skips it, and the transition into it retires that original batch position through `remaining--`. The `default` switch arm also forces `PFS_DONE`. (`src/server.c:21290-21296`, `src/server.c:21417-21424`) |

## Branch invariants and consumers

- Every dereference needed to discover the next link is preceded by the prior state's hint and at least one scoreboard rotation when that prior state issued. A no-hint guard/embedded-key path deliberately advances within the same visit. (`src/server.c:21256-21265`, `src/server.c:21294-21329`)
- FLAT writes stop after the home-slot hint, and DICT writes stop after the bucket hint; only commands with non-null `cmd` and `CMD_READONLY` chase an existing object. (`src/server.c:21346-21350`, `src/server.c:21372-21382`)
- The DICT value width is `w4 = min(n, clamp(pf_cached_w4, 4, 256))`; `PFS_ENTRY` applies it by original array index `j < w4`, not by hit rank. (`src/server.c:21234-21254`, `src/server.c:21402-21409`, `src/server.h:2377-2378`)
- FLAT's acquire-loaded word is used only to decide whether to issue a hint. Command execution later performs the authoritative lookup, so tag collision, overwrite, or stale-word cases cannot become a returned lookup result through this state machine. (`src/server.c:21385-21400`, `src/server.c:21455-21518`)
- Before any slice work, the worker seq-cst publishes `in_flat_section = 1` and backs out while `flat_resize_active` is set; it seq-cst clears the flag at slice end. The coordinator waits for every worker flag to reach zero before entering the copy/swap phase, so it cannot replace the FLAT table while `PFS_HASH` and `PFS_FLAT_KVOBJ` retain its slot pointer. (`src/server.c:21820-21843`, `src/server.c:22355-22366`, `src/server.c:9361-9444`)
- DICT `PFS_HASH`'s valid hash is consumed immediately before command execution by `exExecFake()`, which calls `dictArmHashHint()` only when validity, `argv`, and `argv[1]` are all present. (`src/server.c:21455-21469`, `src/server.c:21511-21518`)
- `prefetch_dict` and `prefetch_bucket_idx` are also referenced by the execution-loop next-op look-ahead, but the compiled AUTO distance is `n`, making `la = j + n` fail `la < n` for every `j`; that retained consumer issues no hint in the pinned code. (`src/server.h:2381-2420`, `src/server.c:22076-22093`)

## Caller

`exSlice()` is the only caller. After a nonempty SPSC pop it snapshots `server.prefetch_ex_level` and invokes `exPrefetchBatch(ctx->batch, n, prefetch_mode)` before executing the batch; remote mode 2 places the message-carrier phases around the same call. (`src/server.c:21953-21975`, `src/server.c:21992-22003`, `src/server.c:22042-22053`)

That input channel has one I/O producer per lane and the owning worker as its sole consumer. The producer writes `jobs[]` before release-storing `tail`; the worker acquire-loads `tail` before copying the pointers into `batch`, and release-stores `head` after the copy to publish reusable capacity. The FSM begins only after that acquire/copy handoff. (`src/server.c:20820-20840`, `src/server.c:20852-20889`, `src/server.c:20936-20969`, `src/server.c:21024-21054`, `src/server.c:22042-22053`)

See [`exPrefetchBatch`](exprefetchbatch.md) for mode, gate, value-width, scratch lifetime, and queue handoff details; see [the L3 footprint gate](l3-footprint-gate.md) for the engagement calculation.
