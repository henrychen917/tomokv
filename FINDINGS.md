# Zero-width raw-head read hint

## Result

The read path now tests one bit in the first `kvobj` word before loading
`vmeta`.  A true bit means that the physical table head is the non-tombstone
committed value for every snapshot which can still be live, so the reader
returns that object directly.  A false bit retains the existing resolver.

This is incremental rather than full promotion.  A completed prune grace may
set the bit while the object still owns `tomoVerMeta` and while older committed
history or an uncommitted physical member remains below it.  The existing full
promotion still removes metadata when its stricter conditions happen to hold.

## Bit reused and proof that it was free

The first object word previously declared these four bitfields:

```text
type 3 + encoding 4 + refcount 23 + iskvobj 1 = 31 bits
```

The remaining bit in that 32-bit allocation unit was padding.  It is now named
`tomo_raw_hint`.  The adjacent metadata word is not touched: all of its bits
remain assigned to `metabits` (8) and `lru` (24).  In particular, no key-metadata
class, LRU/LFU state, refcount bit, flat-slot tag bit, pointer bit, or allocator
prefix was borrowed.

`struct redisObject` was 24 bytes before this change (two 32-bit bitfield words
and two pointers) and has a build-time assertion that it is still exactly 24
bytes.  The first word is exposed through a same-width union member only to
perform atomic hint operations.  No allocation expression changed, so key
offsets, allocation requests, and jemalloc size classes are unchanged.  The
local `embed` sibling independently used this same formerly-padding bit while
asserting a 24-byte header, which corroborates the layout arithmetic; this
change does not take that sibling's object-growing mechanism.

Ordinary `kvobj` constructors initialize the bit true.  Non-`kvobj` `robj`
constructors and the static-object initializer set it false.  Attaching version
metadata to a fresh object clears it before publication.

## Why a stale-optimistic read cannot occur

The bit's invariant is stronger than "the head is committed right now":

> If the bit is true, the physical table head is the value selected by every
> snapshot that can still execute this key lookup.

There are three publication cases.

### 1. Installing a new physical head

`kvobjSetVmeta()` clears the fresh object's bit before its release-store of the
metadata pointer.  The owner subsequently publishes that object with the flat
table's release-store.  A reader which acquire-loads the new table pointer must
therefore observe the initialized clear bit.  A reader which already acquired
the old pointer remains protected by its flat/QSBR region and may return the old
raw head at its earlier lookup linearization point.

This avoids a locked header RMW on every install: the clear is an ordinary
write only because the new object is not published yet; the following release
stores carry it to readers.

### 2. Changing the winner without changing the physical head

Stamps may arrive out of install order.  If a buried member becomes the new
committed maximum, `tomoApplyVersionStamp()` release-clears the physical head's
hint before release-publishing the different `committed_head`.  Pruning applies
the same rule before it publishes a re-exposed physical head whose winner is a
different object.

The existing I3 cross-lane fence makes this ordering semantic as well as
memory-visible: every stamp at or below a reader's pinned snapshot was queued
before that snapshot became visible, and the key owner drains the entire stamp
lane before executing normal read jobs.  Thus a reader whose snapshot includes
the new winner executes after the hint clear.  The reader's acquire-load of the
header cannot use the prior true state.  A reader which executes before the
clear has an earlier snapshot frontier and the old physical head is still its
winner.

### 3. Setting the hint

The hint is not set merely when a stamp arrives.  `tomoVersionPruneAfterGrace()`
sets it only when all of the following hold:

- the callback is for a committed frontier, not cancellation;
- the physical head equals the committed-head cursor;
- the head is applied, non-tombstone, and has a real sequence;
- the head sequence is no newer than the callback's `retire_max`.

The completed QSBR grace proves every reader pinned below `retire_max` has
quiesced.  Every remaining or future snapshot therefore selects this physical
head.  Members below it do not invalidate the proof: an already-committed older
member cannot win a monotone later snapshot, and any currently uncommitted
member must pass through case 2 before it can become visible.  This is the
state in which the hint engages but full promotion cannot.

Full promotion sets the bit only after release-clearing `vmeta`.  A racing
reader which sees false and then sees no metadata takes the old raw fallback;
that is stale-pessimistic and correct.  Hint loads and dynamic transitions are
atomic whole-word operations.  The key owner is the sole header writer, so a
transition retains the other 31 bits with a load plus release-store instead of
paying for a locked RMW; readers only acquire-load this word.

## Expected census movement

The patch exposes the same exact census names used for the supplied
measurement:

- `tomokv_atomic_read_raw`
- `tomokv_atomic_read_versioned`
- `tomokv_atomic_read_walk`

They are owner-local fields placed in the already cache-line-isolated `kstat`
slot and folded only by `INFO`.  `raw + versioned` partitions
`lookupKeyReadWithFlags()` calls, including misses in `raw`; `walk` counts only
committed candidates inspected by actual resolver calls.

The engagement falsifier is

```text
read_versioned / (read_raw + read_versioned)
```

falling well below the supplied 53% in the 1:1 cell.  The residual versioned
population should be heads whose safe grace has not completed, physical heads
which are still uncommitted, committed tombstones, and genuine winner/head
mismatches.  Pure MGET should remain near zero versioned reads.  If the ratio
moves but 1:1 throughput does not, the fixed resolver cost was not the missing
throughput; if it does not move, this implementation did not engage.

## Rejected alternatives

- Growing `kvobj`, embedding version metadata, or changing an allocation
  request: rejected by the measured `embed` loss and the hard size constraint.
- Reusing a `metabits` or `lru` bit: rejected because those two fields already
  consume their complete 32-bit word and carry live semantics.
- Stealing a flat-table hash-tag bit: rejected because it is not free; reducing
  the tag changes collision/probe behaviour and would confound the experiment.
- Setting the hint immediately at stamp time: rejected because a reader pinned
  below that stamp may execute its key lookup later and still needs history.
- Setting it only at full promotion: rejected as vacuous under continuous
  writes, the workload in question.
- Treating a committed tombstone as raw: rejected because returning its
  placeholder object would turn an absent key into a present value.
- Clearing only on new table installs: rejected because an out-of-order buried
  stamp can change `committed_head` without changing the table pointer.
- Trusting a hint retained by any re-exposed historical object: rejected; prune
  explicitly clears it when that object is not the current committed winner.

## Static verification only

- Audited every `committed_head` release-store and every `kvobjSetVmeta()` call.
- Audited all four heap-object constructors and the stack-object initializer for
  explicit bit initialization.
- Kept the per-thread stats slot at one 64-byte cache line by consuming existing
  padding.
- `git diff --check` passes.
- Per the hard constraint, no compiler, server, benchmark, or test was run.
