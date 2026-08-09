# Inline atomic version metadata

## What changed

I chose a conditional full embed. Atomic versions allocate one block laid out as:

`[112-byte tomoVerMeta][key metadata][24-byte kvobj header][key][optional embedded value]`

Ordinary `robj` and `kvobj` allocations remain unchanged. The existing 8-byte `vmeta` pointer word
in the header is now the acquire/release committed-head cursor itself: `0` means raw, `1` means an
active bag with no committed value, and any other value is the committed-head `kvobj` address. A
previously unused header bit records that the allocation permanently has the inline prefix, so
freeing and defrag can still recover the allocation base after promotion clears the cursor.

The full metadata shrank from 120 bytes to 112 bytes by moving the committed-head word into the
existing header slot and reordering `version_seq` to the end of the prefix, immediately adjacent to
the header when there is no key metadata. Static assertions hold `sizeof(redisObject) == 24` and
`sizeof(tomoVerMeta) == 112`.

Version creation now initializes that prefix in place and publishes it through the header cursor.
It does not call `zcalloc`. Promotion clears the cursor but keeps the prefix storage alive with the
`kvobj`, so it no longer queues or frees a separate metadata object. The old vmeta allocation and
retirement INFO counters remain present deliberately as engagement counters, but there is no code
left that increments them.

The read resolver consumes its first captured header cursor directly, avoiding the old
vmeta-pointer load followed by a dependent committed-head load. The common cursor-equals-physical-
head case derives the adjacent prefix without a second header acquire. Non-head candidates still
check whether their metadata is active, because a promoted allocation can later be the raw tail of
a new bag.

Two lifetime/layout details were handled explicitly:

- Key metadata remains immediately before the header. Module-metadata copies use
  `kvobjGetMetaPtr`; freeing, allocation accounting, and defrag use `kvobjGetAllocPtr`.
- Active inline metadata contains queued owner-op addresses and self/chain pointers, so active
  versioned objects are not moved by active defrag. Promoted inline objects also remain immovable:
  a reader may have captured the pre-promotion cursor and still be consuming the retained prefix
  until its flat grace ends.

## Falsifier

Engagement requires `tomokv_atomic_write_vmeta_allocs` to fall from one per written key to
approximately zero. `tomokv_atomic_retire_vmeta` should also be approximately zero, while
`tomokv_atomic_write_kvobj_allocs` should remain one per written key and its usable-size histogram
should move to the combined allocation classes. Total retirements should consequently fall from
about three to about two per written key (prune plus physical only).

Helpfulness requires instructions per operation to fall in the same pure MSET8/perf-stat cell. If
`write_vmeta_allocs` is near zero but instructions/op does not fall reproducibly from the measured
78,275 baseline, the separate allocation was not a meaningful part of the write tax. Throughput is
not the verdict on this box.

## Expected instruction effect

My static estimate is **300-500 instructions saved per written key**, midpoint about 400. That is
the removed jemalloc allocation/free pair, the vmeta allocation-size census work, and one retire
enqueue/reclaim dispatch, plus the avoided blanket 120-byte zero fill; the field initialization
stores required for correctness remain. For MSET8 this predicts roughly 2,400-4,000 fewer
instructions/op. This is an estimate, not a measurement, and the falsifier above takes precedence.

## Size-class arithmetic

These numbers use the default jemalloc classes already named by the in-tree counters and the
warm10k `memtier-N` key shape (9-12 byte keys). Such a key occupies 12-15 bytes in the kvobj: one
stored SDS-header-size byte plus an SDS_TYPE_5 allocation.

- **32-byte value:** the embedded SDS_TYPE_8 value is 36 bytes. Before: the kvobj request was
  `24 + (12..15) + 36 = 72..75`, an 80-byte usable class, plus the 120-byte vmeta in the 128-byte
  class: **208 usable bytes across two allocations**. Now the request is
  `112 + 24 + (12..15) + 36 = 184..187`, the **192-byte class in one allocation**. Net: one fewer
  object and 16 fewer usable bytes while the version is active.
- **4KB value:** the RAW value SDS remains a separate, identical allocation in both versions
  (`sdsReqSize(4096, SDS_TYPE_16) = 4102` requested), so it cancels out. Before: the wrapper was
  `24 + (12..15) = 36..39`, a 48-byte class, plus the 128-byte vmeta class: **176 usable bytes**.
  Now `112 + 24 + (12..15) = 148..151`, the **160-byte class**. Again the net is one fewer object
  and 16 fewer usable bytes while active.

The tree's current embed limit is 192 bytes. I did not retune it. The versioned fit calculation now
includes the 112-byte prefix, so the common 32-byte/warm10k shape still embeds at 184-187 bytes but
does not accidentally spill into a larger class. Ordinary objects retain the existing fit
arithmetic. Reverting the policy to the older 64-byte threshold would stop this common versioned
shape from embedding and would confound this allocation experiment.

After promotion the old design could free its 128-byte metadata object while this design retains
the 112-byte prefix until the value itself is overwritten. At quiescence that is up to about
1.12 MB of requested prefix space for 10,000 keys. Shrinking on promotion would require another
allocation, table-pointer replacement, and grace period on the path this change is trying to
remove, so I accepted this bounded retained-space tradeoff.

## Considered and rejected

- **Unconditional full metadata in `redisObject`:** rejected because it would grow every ordinary
  object from 24 bytes by roughly 112 bytes and push unrelated values through multiple allocator
  classes.
- **Only a committed-head field in the header:** rejected because reads improve but the standalone
  vmeta allocation, retirement, and free remain; `write_vmeta_allocs` would stay one per key and
  fail the primary falsifier.
- **Small inline metadata plus spill pointer:** rejected for this implementation because every
  installed version needs the sequence, physical/committed links, owner-op records, database/store
  ownership, and retirement state. The target write path would spill on every key, preserving the
  allocation being tested. It may be worth revisiting only after a design removes or externalizes
  those always-live fields.
- **Reallocate a smaller raw kvobj at promotion:** rejected because it adds an allocation, copy,
  table publication, and another reader grace to the prune path, trading away the intended savings.

## Verification performed

Per instruction, I did not compile, start a server, run tests, or benchmark. Static checks were
limited to diff/whitespace inspection and source searches confirming that no vmeta allocation,
standalone vmeta free, or vmeta-retire enqueue remains.
