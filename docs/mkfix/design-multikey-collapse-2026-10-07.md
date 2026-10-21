# Multi-key congestion collapse — design read of the shipped scatter path

Read-only audit of `/home/user/Projects/cx-final` (branch `cx-final`, HEAD `eb543eef7`, gate reference
`0e894d165`, 517 gate rows). No file was modified; nothing was built or run. Every line number below is
from this tree.

**The fact being explained** ([[tomokv-multikey-congestion-collapse]]):

| command | p8 | p32 | p128 | CoV @p128 |
|---|---|---|---|---|
| GET | 10.09 M | 22.03 M | **25.27 M** | 0.30 % |
| SET | 9.87 M | 21.74 M | **24.39 M** | 2.01 % |
| MGET-8 | **2.077 M** | 1.807 M | 1.326 M | 4.54 % |
| MSET-8 | **2.106 M** | 1.749 M | 1.642 M | 4.91 % |

Two separate measured signatures must both be served by any explanation:

* **(A) the slope.** Single-key gains 2.5x from p8 to p128; multi-key loses 13–36 %.
* **(B) the p32 bimodality.** Slow cluster vs fast cluster: **+8.6 % instructions/op** (40,966 vs 37,714)
  at **identical IPC** (0.730 vs 0.719) and **identical cache-misses/op** (441.2 vs 440.5). Signature =
  *more work per delivered op*, not a memory stall. Server-bound (89 % server, 13.9 % loadgen).

Derived budget, geometry-independent (from (B)'s own counters): an MGET-8 command costs
40,966/0.730 = **56,118 cyc** (slow) or 37,714/0.719 = **52,453 cyc** (fast), i.e. **6,557–7,015
cyc per key**. A saturated single-key op is ~4,894 cyc/op ([[tomokv-cycles-per-op-is-the-metric]],
different build/day — order-of-magnitude anchor only). So **each MGET-8 key costs ~1,660–2,120 cycles
more than a whole single-key command, ~13,300–17,000 extra cycles per MGET-8.** That is the budget the
candidates below must fill.

### Geometry correction that changes the arithmetic

`src/core/config.h:465`:

```
inline constexpr uint32_t cfg_default_shards(uint32_t executors) {
    return executors >= 32 ? 256 : 8 * executors;
}
```

resolved at `src/core/server.h:268-269`. On the EPYC box in 1s fused on 32 cores the default
(`--shards -1`) is therefore **256 shards, not 64**. [[tomokv-fanout-participants-law]] and
[[tomokv-collapse-ratio-law]] were measured at an explicit `--shards 64`. At 256 shards with 8 random
keys:

* E[distinct shards] = 256·(1−(255/256)^8) = **7.87 tasks per MGET-8** (vs 7.58 at 64 shards).
* E[distinct executors] (32) = 32·(1−(31/32)^8) = **7.17**.
* Collapse ratio 7.17/7.87 = **0.91** — even closer to 1 than the law's 64-shard figure, so
  [[tomokv-collapse-ratio-law]] is *more* binding at the shipped default, not less.
* **E[keys per touched group] = 8/7.87 = 1.016.** ~98.5 % of groups carry exactly one key. This single
  number kills three amortisation mechanisms in the code (see M4, M6, M7).

---

## 1. The scatter path for MGET/MSET as the code is today

Shipped live path is `IoLoop::parse_and_dispatch` in `src/core/io_loop.h`. `src/core/reorder.cc` holds a
second, byte-shaped copy of the same flow (`IoLoop::r7_parse_and_dispatch`, reorder.cc:2069) which is
**not the default** — `--reorder 0` since `c9726b3b9` ([[tomokv-tail-knee-curve]]). The reorder copy's
equivalents are cited where a change would have to be mirrored.

### 1.1 Parse (IO thread, connection owner)

| step | site | what happens |
|---|---|---|
| pass prologue | `io_loop.h:3064` `parse_and_dispatch<NoBorrow,BatchOps,IoPipe,SplitLocal>` | one pass cut for the whole pass (`pass_read_cut`, :3115-3118); `task_free_slots` / `post_task_quiet` lambdas bound to `self_id` (:3083-3088) |
| loop-top gates | `io_loop.h:3151` | `if (c->scatter_barrier() \|\| c->parse_backpressure()) break;` |
| | `io_loop.h:3153` | `if (read_local_enabled && rob.local_mget_fence_pending()) break;` — **1s+rl only** |
| ROB slot | `io_loop.h:3156-3163`, `src/net/rob.h:238/265/272` | `rob.acquire…()`; `nullptr` once `dispatch − flush ≥ Capacity`, `kRobWindow = 64` (`rob.h:80`) |
| RESP parse | `io_loop.h:3196-3205` → `src/net/resp.h:301 resp_parse` | argv pushed one `Slice` at a time via `Op::push_arg` (`resp.h:83/185/291`) |
| **argv spill** | `src/exec/op.h:40` `kInlineArgv = 8`; `op.h:123-136` | `MGET k1..k8` is **argc = 9** ⇒ first heap `std::realloc(nullptr, 16·16 B)` + `memcpy` of 8 Slices. `MSET k v ×8` is **argc = 17** ⇒ **two** reallocs (cap 0→16→32). `GET`/`SET` (argc 2–3) never leave `argv_inline_` |

### 1.2 Classification and lowering (IO thread)

| step | site | note |
|---|---|---|
| read-local fork | `io_loop.h:4111-4113` | if `read_local_enabled && read_local_mget_candidate && read_local_eligible` → `goto ordinary_dispatch` (MGET never reaches the scatter engine) |
| scatter gate | `io_loop.h:4114-4116` | `if (!(spec->flags & (AllShards\|MultiShard\|ConfigRoute))) goto ordinary_dispatch;` — GET/SET never pay the cross-TU call |
| prepare | `io_loop.h:4117-4121` → `src/cmd/scatter_engine.inc:1490 xshard_prepare` | returns `NotScatter / Ready / Backpressure / Error` |

Inside `xshard_prepare` (all `scatter_engine.inc`):

| step | line | note |
|---|---|---|
| classify + key plan | 1490-1600 | `classify`, `classify_keys`; 8 hashes + 8 router lookups into `routes[]` |
| `group_cap` | 1870-1891 | non-atomic branch is **O(k²)** pairwise shard compare (28 compares at k=8) |
| **read_fanout / needs_snapshot** | 1913-1924 | `read_fanout = group_cap > 1 && !(Write\|SnapshotWrite)`. For MGET this is **true at every atomic mode**; MSET (a Write) is false unless `tracking` |
| snapshot-window gate | 1935-1940 | `can_register_snapshot()` (limit 8) is consulted **only if `atomic_mode & ~kAtomicEnabledBit` ≠ 0**, i.e. only while records/groups are live. A pure MGET workload at `--atomic 0` *or* `--atomic 1` never trips it ⇒ the unresolved set is **unbounded** |
| arena size | 1950 → 795-817 `arena_layout_bytes` | `ScatterState` + `ShardGroup[group_cap]` + `KeyRef[k]` + `uint32[k]` + (`ValueSlot[k]` for MGET) + (`uint8[k]` status for MSET/DEL/…) + (`uint16[shard_slots]`, `OwnerRecordRefs[nthreads]` for atomic installs) |
| arena acquire | 1960 → 1475-1482 | `ScatterArenaPool::acquire`: LIFO of `kCached = 64` blocks of `kCommonBytes = 16384` (`src/cmd/xshard.h:110-111`), else `posix_memalign` |
| cut stamp | 2034-2046 | `state->snapshot = op.read_cut(...) : server.atomic_snapshot()`; `note_atomic_fanout_cut()` when `!tracking`; `note_atomic_commit_hold()` instrumentation |
| array init | 2055 → 829-890 `init_arena_arrays` | placement-new per `ShardGroup`/`KeyRef`/`ValueSlot`, `memset` of `key_order` and `status`, `std::fill_n(shard_groups, 256, UINT16_MAX)` for atomic installs. ~20 lines of the 16 KB arena first-touched here |
| **register cut** | 2078-2082 → `src/cmd/atomics_glue.inc:393-442` | `unresolved_snapshots_.push_back(state)` (a `std::vector<SnapshotCut*>` on the IO thread), then re-read `server.atomic_snapshot()` and adopt a newer cut; `publish_atomic_read_floor` when the min moves |
| grouping | 2094 → `build_initial_groups` | `uint32_t counts[256] = {}` + `uint32_t fill[256] = {}` (2 KB of stack zeroing) and `for (sid = 0; sid < nshards; sid++)` — a **256-iteration loop per multi-key command** at the shipped default |
| join counter | 2126 → 1115 `initialize_owner_completion` | plain MGET/MSET: `pending = state.nsub` (≈ 7.87). Atomic installs build `OwnerRecordRefs` per participating executor slot |
| return | 2130-2144 | `dispatch = {state, nsub, barrier, atomic_group}` |

### 1.3 Fan-out (IO thread) — the non-atomic arm

`io_loop.h:4166-4216`. MGET/MSET at `--atomic 0`, and MGET at any mode, take this arm; atomic writes
take `dispatch_atomic_scatter` (`io_loop.h:3000-3057`) which uses a **bundled** `post_tasks_quiet`.

```
4166   if (!scatter_dispatch.atomic_write) {
4173       uint32_t* const needed = dispatch_needed_;        // zero-on-entry member
4176       for (i < nshards) { sid=…; tid=worker_of_shard(sid); if (needed[tid]++==0) participants[n++]=tid; }
4180       for (p < nparticipants)
4182           if (task_free_slots(srv_->thread(tid)) < needed[tid]) { room = false; break; }
4188       for (p) needed[participants[p]] = 0;              // restore invariant
4189-4193  if (!room) { xshard_abandon_unpublished(state, pool, self_id); break; }
4195       op->attach_scatter_state(state);  rob.publish();
4197       for (i < nshards) { … Task task{c, op_id, sid, state};
4202             if (!post_task_quiet(owner, task)) std::abort();
4203-4206       touched_[tid]/touched_list_ bookkeeping }
```

Cross-thread handoffs created here, per MGET-8:

1. **~7.17 unconditional loads of consumer-owned lines.** `task_free_slots` →
   `ThreadCtx::task_free_slots` (`src/core/thread.h:517-519`) → `MaskedSpscArray::producer_free_slots`
   (`src/exec/masked_queue.h:413-419`), which **always** does `c.head.load(acquire)`.
   `MaskedSpscArray::push` (`masked_queue.h:230-247`) reads `c.head` **only when the producer-private
   `p.head_cached` says full**. So the single-key path touches no consumer line in steady state and the
   multi-key room check touches one per participant. `ConsumerLine`/`ProducerLine` are both
   `alignas(64)` and adjacent inside `Lane` (`masked_queue.h:58-90`).
2. **~7.87 separate tail stores**, one per task (`post_task_quiet` → `push`), not a bundle. The
   bundled arm's own comment (`io_loop.h:3049-3051`) says "each owner still receives one ordered bundle
   with one queue-tail store"; the plain arm deliberately does not
   (`io_loop.h:4164-4165`: "Constructing route and bundle arrays for MGET added work without helping its
   already-cheap individual queue stores").
3. **One notify bit + one wake decision per touched worker per pass** (not per task) —
   `io_loop.h:4391-4401` → `ThreadCtx::flush_task_notify`.
4. `rob.publish()` — one release store of `dispatch_` (`rob.h:296`), the word owners load.

`Backpressure` sets `c->set_atomic_backpressure(true)` (`io_loop.h:4133-4138`,
`src/net/conn.h:644-647`) and the frame is left unconsumed. Capacity is `kInboxSlots = 1024` per
(producer, consumer) lane (`thread.h:58`), so the room check can only fail under extreme skew.

### 1.4 Executor pickup

| step | site | note |
|---|---|---|
| drain | `src/core/ex_loop.h:1793` / `1818-1834` / `2122` → `src/core/thread.h:624-648 drain_tasks`, `:655-700 drain_task_producer_chunks` | visits only flagged producers; `task_in_->retire(p)` per item |
| **batch prefetch excludes scatter** | `ex_loop.h:2207-2220 prefetch_exec_batch` | `if (shard >= 0 && !batch[i].scatter && worker_of_shard(shard)==self && …) store().prefetch(op.hash);` |
| execute | `ex_loop.h:2315 execute(const Task&)` | `Op& op = t.client->rob().at(t.op_id)` — every fragment reads the Op out of the **connection owner's** ROB, and `op.arg(i)` is a `Slice` into the **connection's read buffer** (`src/exec/op.h:8-12,139`) |
| program order | `ex_loop.h:2435-2439`, `:2628-2651` | `has_parked_predecessor` early-exits when both deques are empty (`:2629-2632`); `parked_predecessor_in` is an O(parked) pairwise `xshard_tasks_share_key` scan but is dead with no cross-shard atomic window open |
| scatter body | `ex_loop.h:2446-2487` | `xshard_execute` → `xshard_watch_finish` → optional LB visit → `publish_size()` → `xshard_complete[_iofused]` |

`xshard_execute` (`scatter_engine.inc:2712-2800` then the per-kind arms):

* `PinnedNowMs now_cut(shard, state.now_cut_ms)` (:2721) — one expiry cut installed per fragment.
* `group_for(state, shard.id())` (:2727) — reads `shard_groups` (atomic installs) or linear-scans
  `groups[]`.
* `shard.store().atomic_has_records()` / `shard.has_watches()` gates (:2728-2745) — false in the
  measured cells.
* `if (!state.atomic_write) prefetch_owner_group(...)` (:2760) → **:971-973 `if (group.count < 2)
  return;`** — dead for ~98.5 % of groups at 256 shards.
* `atomic_read_floor()` (:2763) is gated behind `atomic_has_records()` ⇒ not reached in the measured
  cells. When reached it is an **O(#IO threads) seq_cst scan** (`server.h:2708-2722`).
* `ReadEpochGuard` (:2782-2793): `bound = snapshot != UINT64_MAX || multi_child`. Because
  `needs_snapshot` is true for every multi-owner MGET, **every MGET fragment binds and clears a read
  context on its shard's FlatStore**.
* `xshard_task_should_defer` (`ex_loop.h:2436/2607` → `atomics_glue.inc:599-650`) reads
  `state.debug_hop_deadline`, `debug_conditional_deadline`, `debug_fanout_deadline`,
  `debug_script_defer_deadline`, `atomic_direct`, `direct_ready` — fields spread over the
  ScatterState's head flags and its **cold tail** (`scatter_engine.inc:536-545, 603-608`), i.e. extra
  IO-owned lines pulled per fragment to evaluate always-false debug hooks.

MGET gather arm, `scatter_engine.inc:3018-3059`:

```
3020  if (state.phase != 2 && state.kind == Kind::Mget) {
3022      for (i < group.count) { pos = state.key_order[group.begin+i]; key = state.keys[pos];
3029          object = shard.store().find(key.hash, op.arg(key.arg));
3032          shard.note_keyspace_read(object);
3034          ValueSlot& slot = state.values[pos];
3040          … cutover = min(shard.zc_min(), ValueSlot::kInline);
3042          copy = zc_min == UINT32_MAX || value.n < cutover;
3043-3045     if (copy) { buffer = slot.copy_buffer(value.n); memcpy(buffer, value.p, value.n); }
3046-3051     else { shard.store().borrow(...); slot.ptr/shard/kind = Borrow; } }
```

`zc_min` defaults to **16384** (`config.h:389`), `ValueSlot::kInline` is **1024**
(`scatter_engine.inc:67`), so `cutover = 1024` and every realistic value is **copied into the arena**.

MSET arm, `scatter_engine.inc:3359-3390`: writes `state.status[pos]` (one byte per key) and installs the
value; `has_status` (`:783-788`) gives MSET a `status` array and no `values`; `has_values` (`:780-782`)
gives MGET `values` and no `status`.

### 1.5 Gather, reply sink, retirement

| step | site | note |
|---|---|---|
| join | `scatter_engine.inc:3863` | `state.pending.fetch_sub(1, acq_rel)` — **~7.87 cross-core locked RMWs per command on the ScatterState's first cache line**, which also carries `record_refs`, `watch_refs`, `conditional_failed`, `script_conflict`, `direct_ready`, `exact_sum`, `swap_ready_count`, `swap_done`, `kind`, `final_reply`, `final_error` (`:449-470`). The decision words `epoch`/`aborted` are deliberately isolated on their own padded line (`:613-620`) — `pending` is not |
| completion publish | `:3913-3918` | last owner: `state.snapshot_complete.exchange(true, acq_rel)` then `server.note_atomic_snapshot_complete(state.owner_io)` → `atomic_snapshot_completions_[io].fetch_add` (`server.h:2702-2704`) |
| Done + notify | `ex_loop.h:2479-2487`, `xshard_complete_impl` `final()` lambda `:3850-3859` | `ScatterFinish::Final` ⇒ caller publishes `OpState::Done` and notifies IO |
| IO-side floor sweep | `io_loop.h:620` → `atomics_glue.inc:474-505 refresh_snapshot_floor` | every IO pass: one acquire load of `atomic_snapshot_completions_[self]`; if it moved, **a full linear sweep of `unresolved_snapshots_`**, dereferencing each `SnapshotCut*` (the head line of a *different* 16 KB arena, last written by an executor) and swap-removing the complete ones |
| **write-back decision** | `src/core/wb_rule.h:76-106`, line **97** | `if (op.zc_ptr && op.zc_shard == Op::kScatterStateMarker) return false;` — see M1 |
| ordered drain | `src/net/wb.h:767-830 TOMO_WB_SERVE_BODY` → `src/net/rob.h:764-781 Rob::drain` | stops at the first non-`Done`; one release store of `flush_` per batch |
| retire hook | `io_loop.h:104-131` | `wb_.bind(...)`: `op.has_scatter_state()` ⇒ `xshard_retire(...)` with the borrow-release and zc-suppressed callbacks |
| assembly | `scatter_engine.inc:4210` → `src/cmd/xshard_commands.inc:1708-1776 assemble_mget`, `:1779+ assemble_final` | no-borrow arm (the default at `zc_min = 16384`): `reply_array_header` + 8 × `reply_bulk` into `op.reply`, a `SmallBuf<kInlineReply>` with `kInlineReply = 96` (`op.h:47`). Borrowed arm instead seals the fill segment and appends borrow segments to the connection queue |
| teardown | `scatter_engine.inc:4213-4232`, `:2160-2199 xshard_destroy` | borrow sweep over `values[]`; `unregister_snapshot` (`atomics_glue.inc:445-472`); `free_state_contents`; `pool.release` (back to the 64-block LIFO or `free`) |
| slot recycle | `rob.h:770-771` → `op.h:147-151` | `if (op.oversized()) op.shrink();` where `oversized() = argv_heap_ != nullptr \|\| reply.cap() > kShrinkKeep` ⇒ **argv spill alone throws away the reply buffer too** |

Shared state written by one thread and read by another, per MGET-8 command (the ranked list in §2 is
built from this):

| object | writer | reader | count |
|---|---|---|---|
| owner inbox `ConsumerLine.head` | ~7.17 executors | the IO thread (`producer_free_slots`) | ~7.17 loads of remote-dirty lines |
| owner inbox `ProducerLine.tail` + slot | IO thread | ~7.17 executors | ~7.87 stores + their pickup |
| `Op` header + argv + the connection rbuf key bytes | IO thread | ~7.17 executors | the Op's lines pulled into ~7 cores |
| ScatterState head flags / `groups` / `keys` / `key_order` / debug tail | IO thread | ~7.17 executors | ~6–10 lines × ~7 fragments |
| `ScatterState::pending` line | ~7.87 executors (locked RMW) | IO (none) | 7.87 serialized RFOs on one line |
| `ValueSlot[pos]` (MGET) | the owning executor | IO at assembly | ~8 lines RFO'd + ~8 demand fills |
| `status[0..7]` (MSET) | ~7.17 executors, **one byte each into one 64-byte line** | IO (`first_error`, `:741-759`) | ~7 serialized RFOs on **one** line |
| `snapshot_complete` (ScatterState head) | last executor | IO (`refresh_snapshot_floor`) | 1 |
| `atomic_snapshot_completions_[io]` | every last-owner executor | every IO pass | unpadded `std::atomic<uint64_t>[128]`, `server.h:3472` |
| `atomic_read_floors_[io]` | the owning IO (`seq_cst` store) | cleanup readers (`seq_cst`) | unpadded, `server.h:3471`, adjacent to the above |

---

## 2. Mechanism candidates, with code evidence

Ranked by expected cycles/op at p32. **LEVEL** = flat in pipeline depth (explains why multi-key is
expensive at all); **SLOPE** = grows with depth (explains (A)); **both signatures** = also predicts (B).

### M1 — the write-back rule refuses to batch any multi-key reply. SLOPE + (B). Rank 1.

`src/core/wb_rule.h:76-106` is the landed final write-back policy (`kSmallPipe = 16`,
`kCompleteVisits = 3`, hard-coded `6fd07a0aa`, [[tomokv-wb-complete-small-pipes]]). The prefix walk is:

```
91   while (prefix < threshold) {
92       const auto& op = rob.at(head + prefix);
93       if (op.state.load(acquire) != OpState::Done) break;
97       if (op.zc_ptr && op.zc_shard == Op::kScatterStateMarker) return false;
98       bytes += reply_bytes(op); … ++prefix; }
101  if (prefix >= threshold) return false;
```

`Op::attach_scatter_state` (`op.h:398-402`) sets exactly `zc_ptr = state; zc_shard =
kScatterStateMarker (−2)`, and `io_loop.h:4196` calls it for **every** scattered MGET/MSET. So a Done
multi-key op at the ROB head makes `defer()` return `false` at `prefix == 0` ⇒ the connection is served
immediately with whatever one-reply prefix exists. The author's own reason is in the comment:
*"A Done scatter's byte size is unknown here; do not traverse its sub-ops."*

Who pays: the connection's IO thread, in user time (serve/prepare/pump/SQE build/segment walk) and in
kernel time (one `send` SQE + one CQE per command instead of per 8–16).

Why it is the slope, not a level: GET's divisor **grows with depth** — the same landed rule reports
7.0 cmds/send at p8 d1 and 7.7–8.0 at d2/static S=16, and ~8.7 implied at p128 from the 25.27 M row.
MGET's divisor is pinned at ~1.0 at every depth. Deeper pipes therefore buy single-key a cheaper
reply path and buy multi-key nothing. The arithmetic closes:
[[tomokv-exwb-kills-submit-batching]]'s measured law is `throughput = (threads that ISSUE SENDS) ×
~90 k ops/s`. With one send per command and 32 fused senders that ceiling is **2.88 M MGET/s**;
measured MGET is 2.08 M (p8) → 1.81 M (p32) → 1.33 M (p128), i.e. **at or under the one-send-per-command
ceiling at every depth**, while GET at p32 is 22.0 M = 7.6× it. Multi-key is living on the p1 law.

Class: not RFO, not O(outstanding) — **per-op fixed cost that single-key amortises and multi-key cannot**.
Fits (B) exactly: more serve/pump/submit executions per delivered op is extra instructions on
already-hot lines ⇒ instructions/op up, IPC flat, cache-misses/op flat.

Expected cycles: a serve+prepare+pump+submit cycle is of order 400–900 user instructions plus a
syscall-class kernel cost. Paid once per MGET-8 instead of once per 8–16 commands ⇒ **of order
3,000–8,000 cyc/command of the 13,300–17,000 gap.**

### M2 — ~7.87 fragments, each a cold-start task on an arena owned by another core. LEVEL, with a cycles SLOPE. Rank 2.

Per-fragment fixed cost, paid 7.87 times per MGET-8 and once per GET:

* `ex_loop.h:2315-2490` preamble: `ClientWorkScope`, `forward_stale_task`, `multi_task_tagged`,
  `rob().at(op_id)` (remote Op line), `set_cached_now_ms`, `has_blocking_state`,
  `has_parked_predecessor`, `xshard_task_should_defer` (6 field loads spanning the ScatterState head
  **and** cold tail), `note_execution`, then `xshard_execute`'s own `PinnedNowMs`, `group_for`,
  `atomic_has_records`, `has_watches`, `prefetch_owner_group` (early-returns), `ReadEpochGuard`
  set/clear, `note_keyspace_read`, `xshard_watch_finish`, `publish_size`, `xshard_complete`.
* Read set per fragment: Op header + argv + the key bytes in the connection rbuf + ScatterState head
  flags + `groups[g]` + `keys[pos]` + `key_order` + debug tail + its `ValueSlot`/`status` byte ≈ **6–10
  distinct cache lines of memory the IO thread owns**, pulled into ~7 different cores.

Why the cycles slope: the *count* is depth-independent, but the *cost per line* is not. The live-arena
working set per IO thread is (conns/thread) × min(depth, 64) × ~1.3 KB touched:

| depth | live arenas / IO thread (32 conns/thread) | touched bytes | vs 1 MB L2 / 16 MB L3 per CCX |
|---|---|---|---|
| p8 | 256 | ~333 KB | fits L2 |
| p32 | 1024 | ~1.3 MB | **spills L2**; ~10.6 MB for 8 threads on a CCX — borderline L3 |
| p128 | 2048 (ROB-clamped at 64) | ~2.7 MB | ~21 MB per CCX — **exceeds L3** |

The arena stride is a fixed 16 KB (`xshard.h:111`), so 1024 live arenas also span 4096 4 KB pages
against a ~3072-entry L2 TLB. This is the one candidate that predicts the p32 **bimodality** as a
working-set boundary crossed differently by different warm-ups — two tight clusters, one steady and one
oscillating. It does **not** fit (B)'s "identical cache-misses/op", so (B) must be M1/M3/M5 and the
slope may be M2; the measurement in §3 separates them.

Class: mixed — producer→consumer RFO on `ValueSlot`/`status`/`pending`, consumer demand fills on
everything else.

Expected cycles: ~7 fragments × (6–10 remote lines) at 80–200 cyc/line once out of L2 = **3,000–9,000
cyc/command**, and that term is what the io:ex ratio inversion in [[tomokv-fanout-participants-law]]
is buying down when a narrow tier wins at deep pipes.

### M3 — IO-side allocator churn forced by `kInlineArgv = 8` + `kInlineReply = 96`. SLOPE + (B). Rank 3.

Per MGET-8 (8 keys, ~64 B values, no borrow), all on the connection's IO thread:

| call | site |
|---|---|
| `std::realloc(nullptr, 256)` + `memcpy` 8 Slices (argv spill at argc 9) | `op.h:124-134` |
| `SmallBuf::grow` ladder 96→192→384→768: **3 × `malloc` + 2 × `free` + ~1.3 KB of `memcpy`** for a ~570 B MGET-8 reply | `src/base/slice.h:190-197`, `op.h:245` |
| `reply.shrink_to_inline()` → `free(768)` | `slice.h:218-221`, reached because `oversized()` is already true from `argv_heap_` |
| `free(argv_heap_)` | `op.h:148` |

**≈ 4 allocations + 4 frees + ~1.3 KB of copying per MGET-8; exactly zero for GET/SET** (argc ≤ 3 stays
inline, a 64 B GET reply is ~72 B ≤ 96). MSET-8 is argc 17 ⇒ two reallocs, and its `+OK` reply stays
inline so only argv churns.

The benched shape is one argument over the cliff: `kInlineArgv = 8` ⇒ argv spills at **argc ≥ 9**, which
is **MGET with ≥ 8 keys** and **MSET with ≥ 4 pairs**. `tests/abba_workloads.py:18` sets
`MULTI_KEYS = 8`.

Why the slope: allocate at parse, free at retire — the two are separated by the whole pipeline depth. At
p1 the pair is adjacent and the allocator's LIFO returns the same hot block; at p32 ~1024 blocks per
thread are live, the free list behaves like a queue, and each returned block is cold for the `memcpy`
that follows. Jemalloc tcache overflow adds arena work on top. Fits (B): allocator instructions on warm
metadata raise instructions/op without moving IPC or cache-misses/op much.

Class: allocation, plus locality degradation with depth.

Expected cycles: 8–9 allocator calls at ~60–120 instructions each ≈ 800 instructions, plus 200–400 for
the copies, plus cold-block write misses — **of order 1,500–3,000 cyc/command**, more at depth.

The layout constraint is explicit and must be respected: `op.h:487`
`static_assert(sizeof(Op) == 336, "Op grew: pay for it inside the struct or re-run the 64c A/B")`, and
`op.h:42-46` records that **the 352-byte version measured −3.7 % at 64c p32**. Raising `kInlineArgv`
costs 16 B per slot — forbidden.

### M4 — scatter fragments get no table prefetch at all. LEVEL (pure IPC). Rank 4.

`ex_loop.h:2207-2220 prefetch_exec_batch` excludes scatter tasks by construction
(`!batch[i].scatter`). `xshard_execute` claims to compensate at `:2760` —
*"The executor-wide batch prefetch deliberately excludes scatter tasks. Recover their structural
advantage here"* — but `prefetch_owner_group` (`:971-973`) returns immediately when
`group.count < 2`, and at 256 shards **E[group.count] = 1.016**. So:

* a GET in a batch gets its hash-table line prefetched one or more batch positions ahead;
* an MGET fragment's probe is an **un-prefetched demand load**, every time.

The compensation was placed where the distance is zero (immediately before the lookup) and omitted where
the distance exists (the batch walk). Who pays: the executor, as a load stall.

Honest risk: [[tomokv-coherence-not-hiding-law]] fact 1 and [[tomokv-latency-hiding-program]] closed
four executor-side prefetch/scheduling lanes as nulls — "latency already hidden at saturation". This
candidate is different in kind (the load is currently *not issued at all* on one path while it *is* on
the other), but the law predicts it may still measure null. Rank it 4 for that reason, not for the size
of the stall.

Class: not RFO — a missing load-side prefetch. IPC lever, multiplicative with the instruction levers
([[tomokv-cycles-per-op-is-the-metric]]).

### M5 — `refresh_snapshot_floor`'s O(outstanding) sweep. SLOPE + (B). Rank 5.

`io_loop.h:620` runs `scatter_pool_.refresh_snapshot_floor(*srv_, self_->id())` on **every IO pass**.
`atomics_glue.inc:474-505`:

```
475  const uint64_t completed = server.atomic_snapshot_completions(owner_io);
476  if (completed == observed_snapshot_completions_) return 0;
478  for (size_t i = 0; i < unresolved_snapshots_.size();) {
479      SnapshotCut* state = unresolved_snapshots_[i];
480      if (!state->snapshot_complete.load(acquire)) { i++; continue; } … swap-remove … }
```

Every multi-owner MGET registers a cut (`scatter_engine.inc:1913-1924` + `:2078`), and no window caps
the set in the measured cells (§1.2). `N = unresolved_snapshots_.size()` is therefore the IO thread's
in-flight multi-owner-read count, **∝ pipeline depth**, and each element dereference is the head line of
a distinct 16 KB arena last written by an executor. Per-op amortisation is
`N_inflight / completions_per_pass`, so the slope is not guaranteed — but the cache footprint of the
sweep is, and the sweep is a named symbol whose profile share is directly measurable.

Two adjacent, cheaper problems in the same machinery:

* `server.h:3471-3472`: `std::atomic<uint64_t> atomic_read_floors_[128];
  std::atomic<uint64_t> atomic_snapshot_completions_[128];` — **unpadded and adjacent**. Eight IO
  threads' floors share one line; executors `fetch_add` into the completions line that eight IO threads
  load every pass. Classic false sharing, multi-key-only traffic.
* `publish_atomic_read_floor` is a **`seq_cst` store** (`server.h:2699-2701`) ⇒ a full barrier on the IO
  thread whenever the published minimum moves (≈ once per multi-key completion).

Note the self-cancelling detail that *downgrades* the sibling scan: `active_snapshot_floor`
(`atomics_glue.inc:377-389`) is O(N) but only fires when `unresolved_floor_refs_` reaches zero. Cuts come
from `atomic_commit_safe_`, which never advances under a read-only workload, so every cut is equal, refs
= N, and a single unregister never empties them. **The exact-minimum scan is therefore dead in a pure
MGET cell and alive only in a read/write mix** — a prediction the mix cells can check.

Class: O(outstanding) scan + false sharing + one full barrier per command.

Expected cycles: unresolved without the profile share. Bounded above by (N/completions-per-pass) line
touches; the false sharing and the barrier are ~100–300 cyc/command.

### M6 — `build_initial_groups` scans all 256 shards per command. LEVEL. Rank 6.

`scatter_engine.inc` `build_initial_groups` (called from `xshard_prepare:2094`):

```
uint32_t counts[256] = {};                              // 1 KB zeroed
for (pos < key_count) counts[keys[pos].shard]++;
const uint32_t nshards = state.server->nshards();       // 256 at the shipped default
for (uint32_t sid = 0; sid < nshards; sid++) { if (!counts[sid]) continue; … }
uint32_t fill[256] = {};                                // 1 KB zeroed
```

Plus `bool seen[256] = {}` in the atomic-write `group_cap` branch (`:1876`) and
`std::fill_n(state.shard_groups, state.shard_slots /*256*/, UINT16_MAX)` in `init_arena_arrays`
(`:861-862`) for atomic installs — **another 512 B written per atomic-write command**. Every `m*` cell
in `tests/headline_cells.txt` runs `atomic=1`.

So ~2 KB of stack zeroing (32 cache lines) + a 256-iteration loop + 512 B of arena fill, per multi-key
command, to place ~8 keys into ~8 groups. Flat in depth, and 4× worse at the shipped 256-shard default
than at the `--shards 64` the fan-out laws were measured on. Only the dispatch arm honours the
"touches two owners whether the server runs 4 threads or 128" principle (`io_loop.h:4169-4172`);
grouping does not.

Expected cycles: ~770 instructions for the scan + ~100–200 for the zeroing ≈ **900–1,000 instr
(~1,300 cyc) per command**, i.e. ~2.4 % of (B)'s instruction count. Free to remove, multi-key-only.

### M7 — MSET's `status[]` byte array is one line written by ~7 executors. LEVEL→SLOPE, MSET only. Rank 7.

`arena_layout_bytes` carves `status` as `carve_size<uint8_t>(off, key_count)` (`:804`) — a **dense,
1-byte-aligned array**. For MSET-8 that is 8 bytes in **one** 64-byte line, and the MSET arm writes
`state.status[pos]` per key (`:3369`, `:3380`, `:3382`, `:3387`) from ~7.17 distinct executors. The IO
thread then reads it in `first_error` (`:741-759`) and assembly. `init_arena_arrays:856` memsets it clean
on the IO thread first.

This is the textbook class-(b) case in [[tomokv-coherence-not-hiding-law]]: ~7 producer stores into one
consumer-owned line, serialized, non-hiding. Its *latency* grows with depth because the fragments spread
out in time and the line is evicted between them. It predicts **MSET degrades for a reason MGET does
not** — and MGET's `values[]` is clean by accident (1048 B stride ⇒ no two keys share a line).

But [[tomokv-coherence-not-hiding-law]] (2026-09-14) is explicit: *"the law says which lines CAN cost;
only the pinned A/B/B/A says which DO"* — five offset fixes from the line-sharing audit measured NULL.
Rank 7 accordingly.

### M8 — `pending` join counter on a shared, non-isolated line. LEVEL. Rank 8.

`scatter_engine.inc:3863` `state.pending.fetch_sub(1, acq_rel)` × 7.87 per command, on the ScatterState's
**first** cache line alongside `record_refs`, `watch_refs`, and six more atomics (`:449-470`). The
read-mostly decision words got their own padded line (`:613-620`); the per-command join counter did not.
7.87 serialized locked RMWs at 80–200 cyc ≈ **600–1,600 cyc/command**, flat in depth. Mitigation here is
*not* a different counter layout (the RMWs are inherent to the join) but fewer participants — which is
what the fan-out law already says, and what `exmajor` already failed to buy (§4).

### M9 — ROB head-of-line blocking × order statistics. SLOPE, structural. Rank 9 as a lever, Rank 1 as an explanation of the p128 cliff.

`Rob::drain` (`rob.h:764-781`) retires a strictly in-order prefix and breaks at the first non-`Done`.
`Rob::acquire` refuses past `Capacity` (`rob.h:272`) with `kRobWindow = 64` (`rob.h:80`). So:

* per-connection in-flight is clamped at 64 regardless of client depth — **at p128 the client's credit
  window is larger than the server's ROB**;
* a multi-key command retires only when the **slowest of ~7.87** fragments answers, so its residency is
  E[max of ~8 queue waits], not E[one];
* throughput per connection = window / residency. Offering more load lengthens the owner queues, which
  lengthens E[max] superlinearly, which lowers throughput at a fixed window. That is the congestion
  collapse shape, and it is also exactly why *fewer* executors win at deep pipes
  ([[tomokv-fanout-participants-law]]: 12:20 loses 56 % at p32).

This is the structural term. It is not a bug and there is no small fix for it; it is the reason M1 and M2
matter, and the reason the honest answer may be "p8 is the right bench depth for multi-key".

### Ruled out from the code (do not spend a lane on these)

| hypothesis | why the code says no |
|---|---|
| all-or-nothing room check rejecting commands and re-doing prepare | `kInboxSlots = 1024` per lane (`thread.h:58`); the abandon arm (`io_loop.h:4189-4193`) needs ~8 free slots out of 1024. `lb_fused_masked_lane_high_water` settles it with no code change |
| snapshot window (8) throttling multi-key | `can_register_snapshot` is gated on `atomic_mode & ~kAtomicEnabledBit` (`scatter_engine.inc:1935-1937`), which is zero for pure MGET at `--atomic 0` **and** `--atomic 1`. This is also why [[tomokv-multikey-congestion-collapse]]'s `--atomic 0` vs `1` control came out within 1.3 % |
| program-order pairwise scan | `has_parked_predecessor` early-exits on two empty deques (`ex_loop.h:2629-2632`); both are empty with no cross-shard atomic window |
| `active_snapshot_floor` O(N) exact-minimum rescan | fires only when `unresolved_floor_refs_` hits 0; impossible while `atomic_commit_safe_` is static (read-only cell) |
| `reap_deferred` / `flush_borrow_releases` O(N) | `deferred_destroy_` needs non-zero `record_refs`/`watch_refs` (atomic groups only); borrows need `value.n ≥ 1024` at `zc_min = 16384` |
| arena pool exhaustion | `acquire`/`release` (`:1475-1488`) is a balanced LIFO in steady state; only a growing live set allocates |

### Conditional, 1s + read-local only: the one-command MGET fence

`read_local = 0` is the default (`config.h:375`), but the all-on posture (cells m25–m48, m73–m96, smoke
m47/m92) turns it on, and there it is a hard serialization:

* `io_loop.h:3513` `if (mget && rob.has_pending_read_local()) break;` — an MGET is not even considered
  while any local read is pending on this connection;
* `io_loop.h:4296-4297` `rob.arm_current_local_mget_fence();` (`rob.h:347-350`);
* `io_loop.h:4307-4311` `read_local_batch = !read_local_mget_candidate; … if (read_local_mget_candidate)
  break;` — the pass ends;
* `io_loop.h:3153` `if (read_local_enabled && rob.local_mget_fence_pending()) break;` — the next pass
  cannot parse past it.

**Net effect: one MGET in flight per connection, i.e. effective depth 1 for MGET regardless of what the
client offers.** Deeper client pipes then add only queueing around a depth-1 command. Also
`read_local_lane_demand = min(argc−1, nshards) = 8` (`io_loop.h:3519-3520`) ⇒ an MGET needs 8 lane slots
where a GET needs 1, so under lane pressure (`read_local_lane_quota`, `io_loop.h:3133-3135`) MGET is
demoted 8× more often.

The fence is a correctness fence ("no younger frame may receive a read cut until this id either completes
locally or is irrevocably transferred", `rob.h:342-346`) — but note `io_loop.h:3110-3118` already gives
**one read cut to the whole parse pass**. The fence therefore forbids precisely the case the pass-cut
design already made safe (several MGETs parsed in one pass share one cut). That is the relaxation to
propose if Lane A shows rl=1 multi-key is fence-bound.

---

## 3. Top 3: confirm/refute without touching production code, then the smallest change

### M1 — no write-back batching for multi-key

**Measure first (zero production change).**

1. **Replies per send, from the clean-shutdown report.** `src/net/wb.h:704-718` keeps
   `sends_submitted`, `retired`, `serves`, `serves_empty`; `src/core/shutdown_report.h:68-74` aggregates
   them and `:452-468` emits them as JSON. Boot, run the cell, shut down cleanly, read
   `retired / sends_submitted`.
   *Prediction if M1 holds:* GET ≈ 3.5 at p8 rising to 8–16 at p32/p128; **MGET and MSET ≈ 1.0 at every
   depth.** Refuted if MGET's ratio rises with depth like GET's.
2. **The `--wb-policy` discriminator.** `--wb-policy 0` is "LATENCY: every ready head on every captured
   pass" (`wb_rule.h:76-77`, knob at `config.h:867-873`). If the scatter exit already makes multi-key
   behave as policy 0, then **policy 0 vs 1 must be a null for MGET/MSET and a large loss for GET** on
   the same binary. This is a two-arm, same-binary, knob-only experiment: the cleanest possible proof,
   and it also sizes the prize (the GET delta is roughly what multi-key is forfeiting).
3. **Cross-check** `serves`, `serves_empty` and system time share (`/proc/<pid>/stat`, or
   `perf stat -e syscalls:sys_enter_io_uring_enter`) against the 25 GbE MGET rate to see whether the
   per-command send is the binding resource, i.e. whether the measured rate sits on
   `senders × ~90 k` ([[tomokv-exwb-kills-submit-batching]]).

**Smallest change if confirmed.** Give a Done scatter a **known byte bound** so the prefix walk can
continue instead of bailing.

* The last owner already RMWs the ScatterState head line (`pending.fetch_sub`, `:3863`) and already
  writes `final_reply`/`final_integer` on it (`:3936`, `:3941-3942`). Add **one `uint32_t
  reply_upper_bound` on that same line**, stored by the last owner before it publishes `Done`. For MGET
  it is `Σ (values[i].len + 16) + 16`, computable from data the gathering owner just wrote; for
  MSET/DEL/EXISTS/… `final_reply` is already one of `Ok`/`Integer`, i.e. an exactly known small size.
  **Zero added cache-line crossings** — the line is already being RFO'd (the law's own criterion,
  [[tomokv-coherence-not-hiding-law]]).
* Then in `wb_rule.h`, replace line 97 with a bound read instead of a bail:
  `bytes += op.scatter_reply_bound();` and let the existing `bytes >= kWbufInline` test do its job.
* **Hot-path law:** the branch `op.zc_ptr && op.zc_shard == Op::kScatterStateMarker` already exists and
  is false for GET/SET (`zc_ptr == nullptr` at `zc_min = 16384`), so the single-key body is byte-identical.
  `sizeof(Op)` is untouched (the field lives in the arena, not in `Op`). `src/core/reorder.cc` needs no
  mirror — `wb_rule::defer` is shared.
* Risk to bench: this *adds* deferral to multi-key, which is a latency trade. The burst-tail cells must
  be in the acceptance set ([[tomokv-burst-shape-flips-wb-ranking]],
  [[tomokv-wb-adaptive-lowload-deep-pipe-loss]]). Do **not** make the rule adaptive; the knob is
  0|1 and the constants are hard-coded by owner ruling.

### M3 — allocator churn forced by the argv spill

**Measure first (test-file constant only).**

1. **Key-count sweep across the spill cliff.** `tests/abba_workloads.py:18 MULTI_KEYS = 8` is a
   *test* constant. Sweep `MULTI_KEYS ∈ {2,3,4,7,8,9,16}` at p8 and p32 for MGET and MSET and plot
   **cycles per key**. The spill boundary is argc ≥ 9 ⇒ **MGET at k ≥ 8** and **MSET at k ≥ 4**.
   *Prediction if M3 holds:* a visible step in cycles/key between MGET-7 and MGET-8, and between MSET-3
   and MSET-4, larger at p32 than at p8, with no step at MGET-9→MGET-16 beyond the linear key term.
   This is the sharpest single discriminator in the whole note and needs no production change.
2. `perf record` on the server cores; symbol share of `malloc`/`free`/`realloc`/`je_*` and of
   `SmallBuf::grow`, at MGET p32 vs GET p32.
3. `MALLOC_CONF=stats_print:true` on shutdown for per-bin allocation counts; divide by `cmdstat_mget:calls`
   (`src/cmd/t_server.cc:2703-2724`) to get allocations per command.

**Smallest change if confirmed.** Two independent one-liners, benched separately
([[tomokv-hotpath-decomposition-verdict]]: bench bundles *and* their parts):

* **(a) stop the argv spill from discarding the reply buffer.** `op.h:147-151` currently ORs the two
  conditions, so an MGET that grew a 768 B reply buffer frees it every retire and re-grows it every
  command. Split the decision: shrink the reply only when `reply.cap() > kShrinkKeep`, free argv only
  when `argv_cap_ > kArgvKeep` (e.g. 32 Slices = 512 B; bounded retention is 64 slots × 512 B = 32 KB
  per connection, strictly cheaper than the already-tolerated `kShrinkKeep = 4096` per slot).
  **Hazard to state in the lane brief:** once `argv_heap_ != nullptr`, `Op::arg` (`op.h:139`) routes
  *every* later command on that ROB slot through the heap array. On a mixed connection that moves GET off
  the inline path. So retain argv **only** if the measurement shows the mixed-shape cells are unaffected,
  or retain the block in a side field rather than in `argv_heap_` — which `sizeof(Op) == 336` forbids,
  so the honest minimal version is **(a) applied to the reply only**, leaving argv alloc/free as is.
* **(b) one allocation instead of three for the reply ladder.** `slice.h:190-197 grow()` doubles from
  `cap_`, so a 96 B inline buffer reaching ~570 B allocates 192, 384 and 768 with two intermediate
  frees and ~700 B of extra `memcpy`. Round the **first** growth up to the need
  (`ncap = max(round_up_64(need), cap_*2)`). This touches a shared template, so it changes behaviour for
  any reply over 96 B — `v1g_l0` (`GET:1024 p32`, `tests/wb_rule_cells.txt`) is the required control and
  is probably also a win there.

### M5 — the O(outstanding) snapshot-floor sweep

**Measure first (zero production change).**

1. **Prove every multi-owner MGET registers a cut.** `INFO` exposes `atomic_fanout_cuts` and
   `atomic_read_cuts_held` (`src/cmd/t_server.cc:2362`, `:2475-2477`). At `--atomic 0`,
   `note_atomic_fanout_cut` fires once per cut-carrying multi-owner read
   (`scatter_engine.inc:2039`), so `atomic_fanout_cuts / cmdstat_mget:calls` should be ≈ the
   fraction of MGETs with more than one group (≈ 1.0 at 8 random keys). At `--atomic 1` that counter
   stays 0 by construction — read `atomic_read_cuts_held` instead, and note the distinction in the report.
2. **Size the sweep.** `perf record`, symbol share of `ScatterArenaPool::refresh_snapshot_floor` and
   `active_snapshot_floor` (both named, out-of-line in `atomics_glue.inc`), at MGET p8 vs p32 vs p128.
   *Prediction if M5 holds:* the share grows with depth. Refuted if it is below ~0.3 % at p32.
3. **Separate the false sharing from the sweep.** `perf stat` the coherence pair from
   [[tomokv-coherence-not-hiding-law]] (`ls_any_fills_* − ls_dmnd_fills_*` per op, plus store-buffer stall
   events) on MGET p8 vs p32 vs GET p32. The unpadded `atomic_read_floors_`/`atomic_snapshot_completions_`
   lines (`server.h:3471-3472`) should show as store-side crossings that GET does not have.

**Smallest change if confirmed.** Two separable pieces:

* **Pad the two arrays.** `server.h:3471-3472` → one cache line per thread slot (or
  `struct alignas(64) { std::atomic<uint64_t> v; }`). Memory cost 128 × 64 B × 2 = 16 KB of cold Server
  tail. Touches no hot path and no struct any op reads. This is hygiene, not a lane on its own —
  fold it into whichever lane lands, and report it with its own PRE/POST row.
* **Make the sweep O(completed), not O(N).** Registration cuts are monotone non-decreasing
  (`atomics_glue.inc:398-404` always compares against the running minimum, and `atomic_commit_safe_` only
  advances), so `unresolved_snapshots_` is **already sorted by cut at insert**. `unregister_snapshot`'s
  swap-remove (`:456-459`) is what destroys the order. Replace swap-remove with a tombstone plus a
  front-pop-while-complete, so `refresh_snapshot_floor` pops exactly the completed prefix and
  `active_snapshot_floor` disappears. This is entirely inside `ScatterArenaPool`; no hot path, no Op, no
  layout. The exact published floor must be preserved — that is the correctness contract in
  `xshard.h:120-126` and `server.h:2708-2722`, and the gate rows that cover it
  (`xshard_plain_stale_cuts()` must stay zero, `t_server.cc:1091`) are the regression guard.

**Hot-path law for all three:** every change above is either inside the multi-key-only code
(`scatter_engine.inc`, `atomics_glue.inc`, the `kScatterStateMarker` branch) or in a cold Server tail.
No GET/SET body changes. `sizeof(Op) == 336` and `sizeof(ScatterState) ≤ 7264` (implied by
`scatter_engine.inc:624-627`) must both still hold, with the existing `static_assert`s as the enforcement.

---

## 4. What NOT to try again

| dead idea | verdict | citation |
|---|---|---|
| **ex-wb / eager publish** — let the owner that finishes the gather send the reply itself | −10.5 to −22.2 % at each arm's own best ratio. The mechanism is **stage width**, not eagerness: moving the send onto the execute stage means buying send width on the expensive stage. Corollary: *keep the send on the same stage as the receive.* Any "the last owner assembles and sends the MGET reply" design is this, and it is closed | [[tomokv-exwb-kills-submit-batching]], [[tomokv-exwb-deleted]], [[tomokv-exwb-fork-verdict]] |
| **exmajor** — collapse one task per shard into one task per executor for multi-key | Static evidence excellent (−14.9 % tasks at 16 ex), measured LOSS: MSET 1s p8 −1.3 %, p32 −2.2 %; MGET 2s p8 −2.3 %, p32 −3.2 %. Then **refuted again in the regime its own evidence predicted** (24:8 deep pipe: MSET p32 −3.9 %). At the shipped default the collapse ratio is **0.91** (worse than the 64-shard 0.96), so there is nothing to collapse. Shelved twice | [[tomokv-collapse-ratio-law]], [[tomokv-fanout-participants-law]] |
| **hp-* / hotpath diet lanes** — including **opt1, literally an `xshard_prepare` bypass** | round 1 +1.68 %, round 2 −0.41 % ⇒ sign-flip ⇒ deprecated. opt3 +0.72 %/−0.33 %, opt2 −0.44 %. The −1.9 % bundle **does not decompose into its parts**. Also: sub-1 % NIC verdicts need the 02:00–07:30 quiet window | [[tomokv-hotpath-decomposition-verdict]], [[tomokv-hotpath-was-a-net-negative]] |
| **publication-diet style arena re-layout** ("it fits in the hole") | A 161-instruction cut lost 2.3 % on the mixed shape by landing a per-write store in the same line as `probe_sequence`. Signature: pure SET +1.97 %, pure GET flat, 1:1 mix −2.29 % with instructions DOWN 87. Any `ScatterState`/arena field move must name **which line** the padding belongs to and **who reads it**, and must be benched on a mixed shape | [[tomokv-coherence-not-hiding-law]] (2026-09-07) |
| **line-sharing fixes as a program** | Five offset fixes from the LINE-SHARING-AUDIT measured NULL cumulatively (±1 %). "The law says which lines CAN cost; only the pinned A/B/B/A says which DO." Applies directly to M7 (`status[]`) and M8 (`pending`) | [[tomokv-coherence-not-hiding-law]] (2026-09-14) |
| **executor-side prefetch/scheduling to hide latency** | Four nulls; law closed as "latency already hidden at saturation". M4 is a *missing* load, not a hiding scheme — but it carries this risk and must be measured, not assumed | [[tomokv-latency-hiding-program]], [[tomokv-coherence-not-hiding-law]] (fact 1) |
| **moving the gather fill to another thread** (connalloc family) | −0.6 % cycles despite −55 to −58 instr/op; the block migrates between cores twice per lifecycle. Law: *any split of allocate/fill/publish across two threads adds ≥ 1 crossing per record unless the owner never reads the block at insert.* So do not "pre-fill ValueSlots on the connection" or "let IO allocate the record for MSET" | [[tomokv-coherence-not-hiding-law]] (2026-09-05 21:00, 2026-09-06) |
| **weave / weave2** | Stopped at design: synchronous gaps 130–700 ns | [[tomokv-fused-flush-granularity]] (2026-09-22) |
| **widening the EX drain chunk for multi-key** | `ex-all` costs **−3 to −5 % on MGET/MSET p8**; ex 128 is the widest safe chunk | [[tomokv-fused-flush-granularity]] (2026-09-22) |
| **adaptive / load-detecting write-back** | Lost deep pipes, floors and p50; shipped as a hard-coded `S=16, D=3` with a 0|1 knob. M1's fix must keep that shape | [[tomokv-wb-adaptive-lowload-deep-pipe-loss]], [[tomokv-wb-complete-small-pipes]] |
| **time-constant rules in the write-back path** | Dead twice (T = round trip; m × min busy pass). "The coalescing clock is the PASS; a time constant does not scale, a count of passes does" | [[tomokv-fused-flush-granularity]] (2026-09-21/22) |
| **raising `kInlineArgv`** | `sizeof(Op)` must stay 336; the 352 B version measured **−3.7 % at 64c p32** | `src/exec/op.h:42-46`, `:487` |

---

## 5. Lane plan

Per the standing rules: Fable plans and judges, **codex gpt-6 max writes all code**, mainline tests
([[user-fable-plans-codex-codes-mainline-tests]]); **codex XOR bench, never both**
([[user-phases-codex-xor-bench]]); code → merit → gate → merge, and no benefit ⇒ deprecate there
([[user-merit-before-gate]]).

### Lane A — `mkprobe` (MEASUREMENT ONLY; no production file touched)

**Scope.** One tool plus one cells file. The only source edit permitted is
`tests/abba_workloads.py:18 MULTI_KEYS`, behind an env override (`TOMO_MULTI_KEYS`), and the lane must
show that with the override unset the generated memtier argv is byte-identical to today's (the frozen
`headline_cells.txt` SHA is already the receipt convention, cf. `tests/wb_rule_cells.txt:3`).

**Deliverables.**

1. `tests/mkprobe_cells.txt` reusing existing IDs so nothing is re-derived:
   `m02 m03` (1s rl0 MGET p8/p32), `m05 m06` (1s rl0 MSET), `m26 m27` (1s rl1 MGET),
   `m50 m51 m53 m54` (2s rl0 MGET/MSET), `m74 m75` (2s rl1 MGET), plus the single-key controls
   `p8g p8s h05 h06` and `d128g_l0`, plus a new p128 multi-key pair in the same grammar.
2. `tools/mkprobe_probe.py`, modelled on `tools/exbatch_directed.py` (same ownership/reaping, fresh boot
   per sample, retained failures, `--dry-run` grammar check, `--self-test`). It must emit one row per
   cell with: **rate, instr/op, IPC, cyc/op** (`tests/abba_profile.py:41` EVENTS and `:324-329` derived),
   `retired/sends_submitted`, `serves_empty/serves` (shutdown-report JSON,
   `src/core/shutdown_report.h:452-468`), `atomic_fanout_cuts` and `atomic_read_cuts_held`
   (`INFO`), `cmdstat_mget/mset:calls`, `lb_fused_masked_lane_high_water` and
   `lb_fused_masked_lane_full_events` (`src/cmd/lbsignals.cc:238-243`), and
   `lb_fused_queue_delay_ewma_us` / `lb_fused_oldest_age_max_us`. **Caveat to carry in the tool's
   report:** the age/queue-delay signals are driven by `flipctl_.signal_sample_rate()`
   (`src/core/server.h:512-514`) and flipctl is Split-only (`:505`), so those columns are 2s-only; assert
   non-zero in the arm or print "not available", never a silent zero
   ([[thredis-vacuous-validation-trap]]).
3. A **second perf group** run (separate pass, since `abba_profile` pins a 3-event group): the
   coherence pair `ls_any_fills_* − ls_dmnd_fills_*` per op, store-buffer stall events, and
   dTLB/tablewalker events, on the server cores only.
4. A `--wb-policy 0` vs `1` same-binary pair for `{MGET, MSET, GET, SET} × {p8, p32}`.
5. The `TOMO_MULTI_KEYS ∈ {2,3,4,7,8,9,16}` sweep × `{MGET, MSET}` × `{p8, p32}`, reported as
   **cycles per key**.
6. `perf record` symbol shares for: `malloc/free/realloc/je_*`, `SmallBuf::grow`,
   `ScatterArenaPool::refresh_snapshot_floor`, `active_snapshot_floor`, `build_initial_groups`,
   `xshard_prepare`, `xshard_execute`, `assemble_mget`.

**Acceptance bar for Lane A.** The lane is DONE when each of M1, M2, M3, M4, M5 carries a verdict of
**CONFIRMED / REFUTED / UNRESOLVED (with the reason)**, and:

* **n ≥ 6 per multi-key cell** — multi-key verdicts never rest on one sample
  ([[tomokv-multikey-congestion-collapse]] rule 2);
* a **same-binary null over the 14 saturation cells** runs FIRST and lands inside the box band, before
  any verdict is read ([[user-check-share-before-gate-or-bench]], [[tomokv-parity-bar]]);
* box share checked per [[user-monitor-lanes-no-idle-box]] / [[thredis-one-server-one-bench]]
  (`boxguard.sh`, laneguard cores) and, for any sub-1 % NIC claim, the 02:00–07:30 quiet window;
* every number gets a plausibility check ([[thredis-sanity-gate-benching]]); the M1 prediction is
  arithmetic (`retired/sends_submitted ≈ 1.0`) and must be reported as PASS/FAIL of that prediction, not
  as a narrative;
* **no production file is modified.** If the lane concludes a counter is missing (e.g. there is no
  counter for `xshard_abandon_unpublished`, §2 "ruled out"), it says so and stops — adding one is Lane B
  work.

**Expected cost.** Roughly the exbatch directed-cell shape: ~18 cells × 6 samples × (3 s warm-up +
20 s window + 5 s tail) × 3 instrument passes, plus the 7-point key sweep × 4 cells × 6. Order of a
long night on a dedicated box; it is a serial measure-queue job
([[tomokv-measure-queue-pipeline]]).

### Lane B — one code lane, chosen by Lane A's table

Build **exactly one** mechanism, chosen by this decision table. Do not bundle; the hotpath lesson is that
bundles do not decompose.

| Lane A result | Lane B |
|---|---|
| `retired/sends_submitted ≈ 1.0` for multi-key at every depth AND `--wb-policy 0` vs `1` is a null for MGET/MSET but a loss for GET | **`mkwb`** — scatter reply-size bound on the ScatterState head line + `wb_rule.h:97` reads it instead of bailing (§3 M1) |
| M1 refuted, but the MGET-7→8 / MSET-3→4 step is present and larger at p32 | **`mkalloc`** — split `Op::oversized()`/`shrink()` so an argv spill stops discarding the reply buffer, and/or first-growth sizing in `SmallBuf::grow` (§3 M3), benched as two separate arms |
| M1 and M3 refuted, `refresh_snapshot_floor` share grows with depth | **`mkfloor`** — sorted/front-pop `unresolved_snapshots_` + padded floor/completion arrays (§3 M5) |
| all three refuted, M4's missing prefetch shows as a probe-side stall in the coherence/TLB pass | **`mkprefetch`** — extend `prefetch_exec_batch` to scatter tasks via the existing `xshard_visit_task_hashes` accessor; the `!batch[i].scatter` branch already separates the paths |
| nothing confirmed | Land only the free hygiene items (M6's 256-shard scan, the unpadded arrays) each with its own PRE/POST row, and **report the p8 bench rule as structural** (M9): multi-key is reply-syscall- and order-statistic-bound, and the honest answer is the bench rule we already have |

**Acceptance bar for Lane B (three-regime A/B, cycles/op is the metric).**

* **Instrument first.** Freeze the instrument, then the 14-cell same-binary null inside the band
  ([[tomokv-gate-instrument-contract]], [[user-check-share-before-gate-or-bench]]).
* **Benefit regime** (must win): `m02 m03 m05 m06` (1s rl0 MGET/MSET p8/p32) and
  `m50 m51 m53 m54` (2s rl0). Bar: **median of n ≥ 6 ≥ +3 % on at least the two p32 multi-key cells**,
  and **no multi-key cell worse than −1 %**. Report rate, instr/op, IPC and cyc/op for every row; judge
  by **cyc/op** ([[tomokv-cycles-per-op-is-the-metric]], [[user-prepost-table-rule]]).
* **Neutral regime** (must not move): single-key `p8g p8s h05 h06 h15 h31 h48 h01 h17` in both modes at
  p1/p8/p32. Bar: **every cell ≥ stable** ([[tomokv-parity-bar]], `stablecmp32` from a clean worktree),
  within the same-binary band. For `mkwb` and `mkalloc`, additionally an **instruction null on the
  untaken path** — the off-path must cost zero instructions, which is the lesson that cost
  `store_string` its IPA-SRA clone ([[tomokv-coherence-not-hiding-law]] 2026-09-05 21:00).
* **Deficit regime** (must not regress): `v1g_l0` (`GET:1024 p32`, the reply-ladder control),
  `d128g_l0`, the floor-0.4 burst tails and `t01`–`t04` (`mkwb` adds deferral to multi-key, so the
  burst-tail class is mandatory, [[tomokv-burst-shape-flips-wb-ranking]]). Bar: never worse within
  resolution.
* **Mixed shape** (mandatory for any arena/layout touch): a 1:1 and a 1:9 MIX8 cell. Pure-shape cells
  cannot see false sharing ([[tomokv-coherence-not-hiding-law]] 2026-09-07).
* **14-cell null** repeated after the arm is built (A/B/B/A, same binary) to prove the band did not move.
* **Gate**: `tests/gate.sh` full STABLE, 517 rows, 0 gating FAIL, plus `xshard_plain_stale_cuts() == 0`
  for `mkfloor`. New knob ⇒ knob_matrix row ([[thredis-codex-fork-integration-traps]]); but prefer
  **no knob** — hard-code a consistent gain or delete it ([[user-hardcode-or-delete]]).
* **Loss classification**: any residual loss is labelled MECHANISM / TRADE / UNTUNED / IMPLEMENTATION
  COST ([[user-loss-vs-untuned]]).
* On merge: delete the worktree in the same step ([[user-merge-then-delete-worktree]]); on failure,
  shelve with a branch plus findings and report ([[user-shelve-and-report]]).

### What this lane pair deliberately does not attempt

M9 (ROB head-of-line × order statistics) and the 1s+rl MGET fence are both named here but are **not** in
Lane B. The fence relaxation is a correctness argument about read cuts and belongs in a separate design
round with the atomics owner; M9 has no small fix and is the reason the p8 bench rule exists. Both are
recorded so the next reader does not re-derive them.
