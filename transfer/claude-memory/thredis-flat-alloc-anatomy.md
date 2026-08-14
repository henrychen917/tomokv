---
name: thredis-flat-alloc-anatomy
description: "Where the flat SET path's allocator time actually goes — retire node is the flat-vs-dict delta (fixed, +2.6%); embed-threshold miss is the open lever"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Profile: flat spends ~10.2% of EX cycles in the allocator vs ~4.4% for dict, with
`je_edata_heap_remove_first` and `je_tcache_bin_flush_small` appearing ONLY under flat. Two wrong
answers before the right one (2026-07-25):

1. **kvobj recycle pool — DISPROVED.** Instrumented: pool worked (hits, zero rejects) but saw only
   ~2.4k objects in 20s of multi-million-ops/s traffic. Branch `2s-numa-kvobj-recycle-dev`, committed
   as a documented negative result, NOT merged.
2. **Why it missed, and the key structural fact:** `kvobjSet` (object.c) embeds key+value in ONE
   allocation only while `sizeof(kvobj) + (keylen+3) + (4+vallen) <= CACHE_LINE_SIZE (64)`; otherwise
   it takes `kvobjCreate(..., sdsnewlen(...))` — TWO allocations. memtier's ~16-char key at `-d 32`
   sums to ~71 bytes, so **every SET in our benchmarks misses the embed path by a few bytes**. The
   pool was hooked to `kvobjCreateEmbedString`, which this workload essentially never calls.
3. **The actual flat-vs-dict delta is the retire node.** `dbSetValue` db.c:704 requires BOTH old and
   new to be non-embstr for the in-place swap, and the incoming value is embstr — so dict takes the
   copy path too. What is flat-only is `kvstoreFlatRetireRaw` → `flatRetire`, which `zmalloc`s a node
   per overwrite, matched by a `zfree` in `flatBatchFree`.

**FIXED and pushed** (`97ece9789`, `d1a411971` on 2s-numa-shared-kv-dev): recycle retire nodes via a
`__thread` pool. Measured p32 SET instr/op −2.5%, ops +2.6%; GET flat. Two traps in the first attempt,
both general: (a) adding a field to `exThread` shifts every later field — the `_Static_assert`s only
cover `flat_retire_local` vs `loop_seq`/`in_flat_section`, so use a `__thread` counter instead of
perturbing a hot struct; (b) peak-with-reset on a pool's OWN occupancy never trims (`n <= peak` by
construction) — use a low-water scavenger (min occupancy over the window = the surplus never needed).

**OPEN, biggest remaining lever:** raise the embed threshold 64 → 192 so the common SET is one
allocation instead of two. It also removes the second cache line behind `stringObjectLen` (6.5% of EX
cycles — every value-length read and GET reply touches the separate value allocation). REQUIRES a
`len <= 255` guard that does not exist today (embedded value sds is always SDS_TYPE_8, one-byte
length; the 64-byte limit made that unreachable). Built + correctness-gated on `2s-numa-embed-dev`
but never benchmarked. Gate any layout change on lengths straddling 64/192/255 + APPEND/GETRANGE/
SETRANGE + digest + churn readback BEFORE benchmarking. See [[thredis-ab-harness-traps]].
