# DESIGN-RINGDIET.md — arm the RYOW write ring on demand

**Status: implemented exactly as specified below. The design was fixed before the lane opened;
this file states it, and the sections after it are the proof.**

## The measured fact this answers

The ring-sizing merge (`b0335c239`, *"RYOW ring sized to the ROB window"*) versus the commit before
it, on the owner's box — 512 connections, 64 shards, pipeline depth 32, fused with read-local
armed, 8 interleaved runs per arm, idle box:

| cell | delta | instructions/op |
|---|---|---|
| pure SET | **−1.32%** | **+87** |
| pure GET | +0.80% | — |
| 1:1 mix | −0.08% | — |

The ring lane's own numbers: restoring correct bookkeeping after an overflow costs **+43
instructions per write**, and the armed sidecar costs **+972.8 bytes per connection**.

### Mechanism

The old sixteen-entry RYOW ring **overflowed** on a pure-write stream at depth 32 — and then
stopped bookkeeping entirely. It was cheap for precisely the wrong reason: it gave up. Sizing the
ring to the reordering window (`kRobWindow`, 64) made overflow unreachable, so **every** write is
now recorded — including on connections where no read will ever consult the record.

Main commands are zero-regression by law, and pure SET is a main command.

## The design

### (1) Arm on demand

A connection records its in-flight writes **only after a local read has armed it**.

Until armed:

* a write's entire bookkeeping is **one store of its ROB id** into `read_local_unarmed_write_id_`,
  a word on the producer's own cache line that `dispatch_` has already dirtied. No sidecar, no
  prune, no descriptor, no `Staged` tag — and therefore no resolve on the following frame either;
* a read that arrives **while writes are in flight must take the OWNER path** (demote). Read-your-
  own-writes stays exact: a read and a write of one key share one owner queue, so the owner path
  preserves per-key order by construction. RYOW may be held back only on an explicit key conflict,
  and demotion is strictly stronger than the ring, not weaker.

The arming state lives on a cache line the parse path already owns (the `dispatch_` line, in the
padding that already held `read_local_write_valid_/wide_/force_`), and the check is a **single
predictable test on that line** — `read_local_arm_state_ != 0`, zero in the state every connection
ends up in. **Nothing is evaluated behind it**: the gate-the-argument law. A dormant mechanism that
pulls one cold line per pass cost 0.345 fills per op and 3.8% on a control cell earlier this week,
so the gate word had to be one this frame's `acquire_read_local` has already pulled into L1.

#### The arming transient, and why it is not the overflow generation

The writes a connection published *before* arming are described by nothing. So the read that arms
the connection, and every read behind it, is demoted until the **newest of those writes retires** —
which, retirement being in order, retires all of them. The transient is bounded by one ROB drain.

The obvious implementation reuses the ring's conservative **overflow generation** for that fence.
That is wrong, and silently so: an overflow generation is *extended* by every write published while
it is live (`read_local_resolve_pending_body`), so on a 1:1 connection — which always has a write in
flight — it would never end, and not one read would ever be served locally again. The arming fence
is fixed at arming and is **never extended**; writes published after arming take ordinary ring slots
underneath it and are exact the moment it lifts. `tests/read_local_write_ring_unit.cc` case 16 is
that assertion.

### (2) Sidecar on first write

The 1216-byte `ReadLocalRobState` (a 1280-byte jemalloc class; the +972.8 B/connection of the
measured fact) is allocated **at the first write of an armed connection — never at accept**. A
pure-write connection, a pure-read connection and an idle connection each carry none of it.

Arming itself allocates nothing, which is what keeps a read-only connection free: the transient's
fence is a Rob word, not sidecar state. Allocation failure at the first armed write falls back to
the unarmed contract — always safe, and self-healing, because the next quiescent read re-arms and
the next write retries.

The MGET latest-read fence moved out of the sidecar into the Rob for the same reason: it is a
**read**-side fence, and a pure-MGET connection must not have to allocate 1216 bytes of write ring
to hold one id. It is also cheaper where it now lives — `local_mget_fence_pending()` runs once per
armed parse pass and no longer dereferences the heap.

### What did not change

* `Rob<64>` is still **192 bytes**: the four new producer-line words (`read_local_arm_state_`,
  `read_local_unarmed_write_id_`, `local_mget_fence_id_`, `read_local_arm_stats_`) fit the padding
  `dispatch_` already owned, and `local_mget_fence_id_` arrived from the sidecar, not from nowhere.
* `ReadLocalRobState` is still **1216 bytes**.
* The ring itself, its tag mirror, the overflow machinery, the derivation `static_assert`
  (`kWriteRingCapacity >= Capacity`) and both kept capacity fallbacks are untouched. This lane
  changes *when* the ring is used, never *how*.
* `op->mark_read_local_precise_write()` — and therefore the EX-side eviction guard — fires exactly
  where it fired before. The unarmed `refine_*` calls return the answer an unfilled ring returns,
  because the caller uses that answer to decide a property of the *command's keys*, which ring
  capacity never had a say in.
* No knob. Arm-on-demand is the only behaviour; there is nothing to turn off.

## Counters (INFO, `# Readlocal`)

| field | meaning |
|---|---|
| `read_local_arms` | connections a local read armed |
| `read_local_write_ring_sidecars` | RYOW sidecars allocated (never at accept) |
| `read_local_write_ring_records` | writes committed into a ring — **0 for a pure-write stream** |
| `read_local_fallback_arm_transient` | reads demoted by the arming transient, reported apart from `read_local_fallback_inflight_write` (a steady-state key conflict) so a bench can never confuse the two |

Every increment sits behind a `noinline` call the unarmed stream never makes, so the counters are
always on rather than diagnostic-only. The block is per IO thread; the ROB holds a pointer to it,
installed at `adopt_client` and re-pointed at the migration ownership edge, and **nullable** —
`adopt_client` runs in split mode too, where a thread has no read-local state at all.
