# Masked-monolith executor inbox

## Scope and invariants

This lane replaces only the `Task` slot topology used for parsed-operation dispatch. Each physical
thread owns one fixed-capacity `Task` slot array for the periods when that thread is an executor.
The allocation is made by that physical thread after CPU pinning, and construction first-touches
every slot there. A thread changing role reuses the same allocation; a FLIP changes only its block
mask.

The existing footprint locks still compile unchanged:

- `sizeof(Op) == 336`
- `sizeof(Client) == 1984`
- `sizeof(Task) == 32`

No atomic was added to `Op` or `Task`. Each sub-ring retains the old queue's producer-owned `tail`,
consumer-owned `head` and `retired` frontier, cached peer index, and release/acquire ordering.
`client_in`, `release_in`, and `transfer_in` are separate transfer paths and retain their existing
containers.

## Allocation and block mask

The total array capacity is fixed at boot to:

```
physical thread count * 1024 Task slots
```

This is the old worst-case per-consumer burst envelope (`1024` slots from every possible physical
producer), consolidated into one allocation. It depends on physical thread count, not the live
io:ex split, and is never resized on the hot path. There is no configuration knob: the existing
envelope is sufficient, so a capacity override would add an operational choice without a current
need.

At boot and at `ExInstall`, a consumer assigns every current producer a contiguous power-of-two
block. A lane descriptor stores `base`, `capacity`, and `mask = capacity - 1`; slot lookup is:

```
slots[base + (monotonic_index & mask)]
```

The allocation is 64-byte aligned. `Task` is 32 bytes and every capacity is at least 256 slots, so
every block begins and ends on cache-line boundaries. Two producers can never write the same cache
line. Head/retired/cache and tail/cache occupy distinct aligned cache lines exactly as in the old
SPSC queue.

IO producers receive the burst capacity after the internal reserve, equally rounded down to a
power of two. The capacity cannot fall below the old 1024 slots per IO producer. The tree also has
pre-existing direct executor producers: scatter phase 2, script apply, and stale-owner forwarding.
Relaying those through IO would change semantics and violate the no-relay rule, so each current EX
producer receives a 256-slot block in the same monolith. `256` is the existing maximum owner-grouped
bundle, not a tunable number. Unused rounding slack remains unassigned.

For the directed 64-thread extremes:

| live split | fixed total | IO block | EX direct block |
| --- | ---: | ---: | ---: |
| 63:1 | 65,536 slots | 1,024 slots each | 256 slots |
| 1:63 | 65,536 slots | 32,768 slots | 256 slots each |

Thus the single IO producer inherits the large unreserved part of the burst envelope while the
63-producer case preserves the old per-producer capacity.

Owner-grouped `push_batch` writes consecutive indices inside exactly one producer block and makes
one release store to that lane's tail. A wrap may split the physical writes at the end of the same
block, as it did in the old ring; it can never cross into another producer's block.

## Consumer scan and wake protocol

Every producer has independent head/tail scan points. `task_notify_` remains the active-producer
summary bitmap: the hot drain takes a word, visits only its set producers, and drains each indicated
sub-ring. Producers still publish slots before setting the bit, and the consumer still takes the
bit before draining. The existing read-first `NotifyMask::set` avoids an RMW while a producer is
already active.

The bitmap is a hint, not a correctness oracle. There are two independent full lookers:

1. The existing 100 microsecond depth-sampling beat already reads every producer scan point. If it
   sees a non-empty task lane without relying on the summary, it republishes that producer hint, so
   the next ordinary drain serves it even while other lanes keep the executor busy.
2. Before parking, `drain_tasks_unmasked` still directly drains every producer lane. The subsequent
   armed-depth recheck prevents sleeping on a push that raced the park protocol.

The task monolith has one blocked flag because the old sleep path armed every task channel together.
This removes sleep-only stores and does not change the producer wake decision or its memory order.

## Stable fast path

`push`, `push_prepared`, `push_batch`, `pop`, and `retire` have the same control-flow and publication
shape as `ExQueue`:

- producer: relaxed tail load, the same cached-full branch/acquire refresh, slot writes, one release
  tail store;
- consumer: relaxed head load, the same cached-empty branch/acquire refresh, slot read, one release
  head store;
- retirement: the same separate release `retired` store;
- notification: the same summary-bit transition and parked-peer check.

There is no role test, remask test, allocation test, growth test, or new branch in post/drain. Block
base/mask values are tenure-stable descriptor fields. Owner-grouped bulk posting remains one capacity
preflight and one tail publication.

## FLIP stage diff

No stage was added. The current stage order remains:

1. `IoDrain`
2. `IoPrepare`
3. `ExDrain`
4. `ClientPrepare`
5. `ClientCommit`
6. `ClientInstall`
7. role commit and `RoleReady`
8. `ShardCommit`
9. `ExInstall`
10. completion to `Idle`

The transport-specific differences are inside the standing steps:

| stage | existing obligation | masked-inbox delta |
| --- | --- | --- |
| `IoDrain` through `IoPrepare` | pause new dispatch; drain IO work; prepare destinations | none |
| `ExDrain` | drain retries/tasks/releases/AOF/notifications and acknowledge only when `flip_quiesced()` | `ex_inbound_quiesced()` now checks every monolith lane's `retired == tail`; converting and surviving producers are therefore parked with no claimed task left in a block |
| `ClientPrepare` through `RoleReady` | move clients, commit roles, activate dormant loops, and wait for ready roles | none; the old mask remains untouched while rollback is still possible |
| `ShardCommit` | publish final shard owners | none |
| `ExInstall` | rebind each final executor's shard notification pointers, acknowledge; coordinator completes after all EX acks | **before rebinding/ack**, each final executor calls `remask_task_inbox_quiesced(final_io, final_ex)` inside its existing allocation |

`ExInstall` is after the irreversible role/shard decision and before dispatch resumes. Remasking is
plain descriptor mutation on the consumer thread. Its acknowledgement is a release publication;
the coordinator acquire-observes all acknowledgements before publishing `Idle`, and producers
acquire-observe that stage before dispatching again. No producer can read a partially installed
base/mask. A pre-commit rollback never remasks and therefore needs no inverse operation.

## Cold growth discipline

The selected fixed envelope has no runtime growth trigger. `MaskedSpscArray::grow_quiesced` exists
for a future explicit capacity increase and refuses unless every lane is quiesced. It allocates and
first-touches a replacement on the consumer thread, installs a fresh mask, then releases the old
array. A caller must place it at the same parked point as the `ExInstall` remask; it is intentionally
unreachable from post, drain, backpressure, or any other hot path.

## Directed functional proof

`tests/spscmask_flip.py` requires a 64-thread 63:1 boot. Its gated `DEBUG IO-THREAD` observation
retains one live connection from every initial IO owner, proving all 63 producer lanes fire. Every
connection continuously pipelines ordered `SET key sequence` / `GET key` pairs while the control
connection flips 63:1 to 1:63 and back. The test requires every stream counter to advance under all
three installed masks, checks every reply position, drains every pipeline, and point-reads the final
acknowledged value for all 63 keys.

## Hot-key READ forwarding (`hot-forward`)

### Boundary and allocation

`hot-forward` is a boot-only numeric switch. `0` is the default: no forwarding object, slot, or
scratch buffer is allocated, and the IO loop uses a false template specialization containing no
forwarding branch. `1` allocates one fixed slot per physical shard and one fixed scratch buffer per
physical IO thread. There is no table, resize, runtime allocation, negative entry, write forwarding,
or multi-key read path. A slot can name exactly one key; the key is capped at 256 bytes and its fully
formatted positive GET reply at 4096 bytes. Either overflow leaves the slot unavailable and GET
uses the ordinary task path. Failure to make the bounded boot allocation fails initialization.

One slot per physical shard is the narrowest structure that retains a single writer while shards
move between executors: the current owner of that shard is the slot's only publisher. The existing
FLIP/LB quiescence and owner-publication barrier transfers that writer tenure together with the
shard. The slot owns copied key/reply bytes and an absolute expiry stamp; it never exposes a
`FlatStore`, `KvObj`, value pointer, borrow, or general read epoch.

### Detection and promotion

Detection reuses `ExLoop::note_lb_hash`'s existing 1-in-N countdown. On the tick where that code
already records a bucket sample, an exact, successful, ordinary GET may also update the shard
slot's owner-only candidate. Sixteen consecutive sampled GETs for the same exact hash and key
promote it. Non-GET visits add no detector work, and there is no second counter or heavy-hitter
policy. `hot-forward=1` keeps this same countdown active even when `key-lb=0`; an explicit
`lb-sample-rate=0` is rejected with forwarding enabled rather than silently making promotion
impossible. Until a promotion, the enabled GET path sees only the one predicted unavailable-slot
branch; detector work occurs only on the pre-existing sampled tick. This is the no-hot
zero-regression posture.

Promotion performs one owner-local no-touch lookup after the sampled GET. Only a live String is
published. Integer encoding is rendered to the same decimal bulk reply as `GET`; raw/external
strings are copied. Missing keys and wrong types are not represented. A different candidate can
replace the named key only after it independently reaches the same fixed threshold.

### Publication and torn-read protocol

Each opt-in slot contains one atomic 64-bit sequence and atomic 64-bit words for all published
metadata, exact key bytes, and reply bytes. These are the only new atomics. They are required to be
always lock-free. The owner makes the sequence odd, writes the atomic words with relaxed stores,
then release-stores the next even sequence. Invalidation leaves the sequence odd. An IO reader:

1. acquire-loads an even sequence;
2. relaxed-loads metadata and exact-compares hash, key length, and key words;
3. copies the bounded reply words into its owner-local scratch buffer;
4. executes an acquire fence and re-loads the sequence; and
5. uses the copy only if both sequence reads are the same even value.

There is one attempt: odd sequence, version churn, or any mismatch falls through to normal owner
dispatch; readers never spin and the owner never waits for readers. Atomic payload words avoid the
C++ data race that a seqlock around plain bytes would still have. No atomic is added to `Op`,
`Client`, `Task`, `Shard`, `FlatStore`, or the ordinary routing/store metadata.

The owner updates forwarding state only at logical publication boundaries. After a completed
ordinary single-key write handler, it republishes the final live String when the command's exact
key is the promoted key and the bounded copy fits; otherwise it invalidates that matching slot.
Every scatter, multi-key, script, atomic-group, FLUSH, or other broad write fragment invalidates its
physical shard's slot and does not republish an intermediate value. These actions occur before the
write operation's existing `Done` release. MVCC physical changes remain invalid until a later
sampled plain GET after the pending epoch state has drained. Rehash and snapshot table moves do not
change a logical value and need no slot action. Lazy/active expiry needs no asynchronous publish:
the absolute deadline in the slot makes it unusable at that same deadline, and the owner path then
performs the real deletion.

### IO eligibility, order, and expiry

The enabled IO specialization adds one predicted-false attempt after the ordinary route has
computed the exact hash and physical shard, but before it loads the executor owner or publishes a
`Task`. ACL, MULTI handling, connection observers, and atomic read-cut stamping have already run.
Only the registry's exact two-argument GET row is eligible; TLS, multi-key, and atomic-tracked
reads fall back. The notification shadow remains eligible: monitor/tracking hooks have already run
before routing, SAVE observes writes rather than reads, and a positive-only slot suppresses no
key-miss or expired event (both conditions fall back to the owner).

A parse call starts a forwarding tail only when that connection's ROB is quiescent. Each local hit
publishes a normal Done ROB entry and advances the tail. Another local command or owner task
advances the ROB dispatch id without advancing that tail, permanently disabling forwarding for the
rest of the parse call. Thus a pure p32 GET pipeline forwards all 32 reads, while `SET k v; GET k`
cannot read the slot ahead of its owner task. Reply retirement and wire order remain the existing
ROB path.

The slot carries `expire_at_ms` in the store's absolute `CLOCK_REALTIME` domain. Only after an
active exact-key match does IO sample that clock (once per parse call); an elapsed slot falls back
instead of replying null, so the owner performs expiry and any observers. Persistent/no-hot reads
pay no clock call. Forwarded successes preserve IO command counts, operation counts, fingerprinting,
and a plain IO-owner forwarded-hit counter included in keyspace hit reporting.

Fallback is therefore mandatory for: no slot; non-GET or multi-key read; non-quiescent/non-prefix
connection order; ACL or TLS rejection; active atomic tracking/read cut; live maxmemory touch
policy; hash/key mismatch; odd or changed sequence; expired deadline; missing/wrong-type publisher
state; or key/reply overflow. Every fallback is the pre-existing owner task path, not a second read
implementation.
