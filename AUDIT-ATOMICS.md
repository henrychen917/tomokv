# AUDIT-ATOMICS — night audit of the `--atomic 1` epoch-MVCC subsystem

Base: mainline 775aeea48 (t-merge14). Branch: `t-night-atomics`. Scope: `src/store/atomic_mvcc.h`,
`src/store/flatstore_atomic.inc`, `src/cmd/atomics_glue.inc`, `src/cmd/scatter_engine.inc`, the
capacity/DENYOOM trigger paths, `tests/atomic_*.py`. Read-local / B+ pending-filter code, the
command registry, parse_and_dispatch, WB/send and ex-sched were read for context only and are not
touched. Every claim below cites file:line in the base tree; every change made tonight is
implementation-level (no protocol, visibility, or layout change) and lands as its own commit.

Method: full read of the four scoped files (9.1k lines) plus the call sites that decide their
invariants (`flatstore.h` find/insert_into/erase/active_expire/choose_victim, `ex_loop.h` execute /
cleanup cadence, `io_loop.h` hazard + read-cut stamping, `multi.inc` prepare_write_key + finalizer,
`server.h` commit bracket / admission / floor). Nothing was booted or benchmarked (lane rule).

---------------------------------------------------------------------------------------------------

## 0. Verdict in one table

| # | Class | Finding | Severity | Action tonight |
|---|-------|---------|----------|----------------|
| S1 | stability | FLUSH/DEBUG RELOAD leave a finite per-store read cut behind: `atomic_tombstone_all` installs tombstones through `atomic_install_plain`, which stores `atomic_read_epoch_ = ticket` (flatstore_atomic.inc:523), and never restores it (601-632). Any later UNBOUND chain read on that store (direct RENAME source read, atomics_glue.inc:82; MULTI-child pop hop-two) resolves at FLUSH's ticket with conn 0 and cannot see a newer committed group -> RENAME answers "no such key" for a key its own MSET just acknowledged. | HIGH (RYOW hole, narrow trigger) | FIXED (commit 2) + regression test |
| S2 | stability | `for_each_touched_key` names NO keys for XREAD/XREADGROUP: it calls `key_count_for(kind, op, ..., xread_count = 0, ...)` (atomics_glue.inc:366) so the localfast XREAD path skips the own-undecided fence (`xshard_task_should_defer` 741) and the read-context bind (`xshard_plain_prepare` 911-929). Pipelined `DEL s1 s2` (cross-shard, atomic) then `XREAD STREAMS s1 0` can read the stream the DEL already acknowledged as deleted. XREADGROUP (a Write) also escapes the snapshot COW gate in `xshard_local_snapshot_prepare` (600). | HIGH (RYOW hole for streams) | FIXED (commit 3) + regression test |
| E1 | latency | RENAMENX/COPY NX validator full-table scan: `store.for_each` over every physical slot of the shard on the pending-record collision arm (atomics_glue.inc:164-168), repeated on every Retry until the foreign group decides. O(N) owner stall per retry; identical answer available from one hash probe. | MEDIUM (owner stall / DoS shape) | FIXED (commit 4) |
| D1 | diet (IO) | Every atomic group value-initializes `nthreads` cache-line-aligned `OwnerRecordRefs` slots (scatter_engine.inc:762-763) and then re-reads all of them (1013-1016): 64 lines touched per MSET-8 on 64 threads, only ~8 are ever read. | LOW-MEDIUM | FIXED (commit 5): construct participants only |
| D2 | diet (IO) | `build_initial_groups`/`build_groups`/`build_sort_deref_groups` scan 256 shard ids (804-847, 780-802, 880-904) for every scatter op; only `nshards` (64) can be non-zero. ~600 predictable instructions per MGET/MSET on the IO thread. | LOW | FIXED (commit 5): bound loop by `nshards()` |
| D3 | diet (owner) | Group install computes `kvobj_size(value)` three times and `kvobj_size(old)` twice per key (atomic_admit 398, exchange_physical 1184/1187, caller 2573-2574). | LOW | NOT changed (needs a signature change on `atomic_exchange_physical`, whose read-local twin is B+ territory) |
| D4 | diet (owner) | DEL/UNLINK atomic groups heap-allocate one key-anchor `KvObj` per key via generic `xshard_make_string` (scatter_engine.inc:2638) purely to carry key identity for the record. | LOW-MEDIUM | NOT changed (record-layout / lifetime change; see IDEAS §7.3) |
| D5 | diet (owner) | Tracked single-key plain writes promote twice: `xshard_plain_prepare` 1019 then `begin_plain_version` 14 on the same key in the same owner pass. | LOW | NOT changed (dwarfed by the mandatory deep clone on that path; noted) |
| C1 | clean | `AtomicEntry::prev` is write-only (flatstore_atomic.inc:892, 1349, 1460, 1633, 1729, 1842, 2018; no reader). `AtomicResolved::matched/physical` and the `count_predecessor` parameter are never consumed (only `.value` is read, 547). | note | NOT changed (144-byte layout lock; resolver is B+'s working area) |
| C2 | clean | `atomic_sweep(floor, cutoff, budget)` ignores `budget` beyond zero-test (592-595); callers pass budgets they believe are honoured (ex_loop.h:1703). Misleading name/contract. | note | NOT changed (signature shared with ex_loop.h) |
| C3 | clean | `publish_epoch()/publish_aborted()` are identity wrappers (scatter_engine.inc:536-542) left from the per-child decision-word era; `(void)server` in `xshard_task_should_defer` (659). | note | NOT changed (churn without effect) |
| C4 | clean | `atomic_collapse` vs `atomic_collapse_read_local` (1261-1639 vs 1642-2024) and the five other `*_read_local` twins are ~600 duplicated lines. | accepted | Deliberate: "restore exact disarmed FlatStore path" (4788b2102) keeps the disarmed path byte-identical. Leave. |

Gauge underflow counters: no driver found (see §3.6). Preservation floor: no violation found (§3.5).

---------------------------------------------------------------------------------------------------

## 1. Instruction diet on the group write path (audit question 1)

### 1.1 What one MSET key costs on its owner today (xshard_execute atomic_write arm, 2455-2588)

Per GROUP (per owner-shard span): `atomic_prepare_capacity(count)` (2458), `atomic_prepare_group`
-> `atomic_alloc_entry` (pooled, one 144+8n byte block, zero-filled) (2466), `aborted.load`
(2477), `prefetch_owner_group` (2481), `atomic_finish_group_install` (2579, one gauge
write-pair), `atomic_publish_group` -> `atomic_link_entry` (2580; head/tail/conn bucket splice,
`live++`, two stat pointers, one `mix64`), one `record_refs.fetch_add` per executor (2582), one
`pending.fetch_sub` in complete (3442), and on the last owner the two-RMW commit bracket + one
`epoch.store` (server.h:2444-2452). Everything per-group is already per-group.

Per KEY: two `op.arg()` loads; `xshard_make_atomic_string` (t_string.cc:290; pooled block via
`atomic_acquire_value_block` 432-454: `good_size` + class + pop); `atomic_admit` (397: one
`kvobj_size`, one predicted branch, one add); `atomic_install_group` (309-315: bounds check +
`atomic_exchange_physical` 1172-1210: one probe run, `obj_bytes_` -= old / += new,
`expires_` insert-or-erase); two more `kvobj_size` for the byte totals; `key_anchor = nullptr`.
The `expires_.erase(h)` per key is NOT extra: `insert_into` (flatstore.h:2300-2302, 2315-2317)
does the same unconditional erase, so the atomic path mirrors the ordinary SET exactly.

Verdict: the owner-side per-key work is the inherent triple (materialize, probe/exchange,
account). The only redundancies are D3 (three `kvobj_size` on the same hot object, ~20-30
instructions/key) and, for new keys, a second probe run because `exchange()` returns nullptr and
`insert_into` re-probes (1209; mm11 keys exist, so cold). Neither is changed tonight: D3 needs
`atomic_exchange_physical` to return sizes, and that function has a read-local twin (1124-1167)
that the B+ lane owns; the new-key probe fold is a table-insert change (IDEAS §7.5).

### 1.2 What one MSET/MGET costs on IO (xshard_prepare 1254-1841)

`init_arena_arrays` (728-767) placement-news `owner_slots = nthreads` `OwnerRecordRefs`, each
`alignas(64)` (354-360): 64 distinct lines written per atomic group on a 64-thread box, then
`initialize_owner_completion` (1003-1018) reads all 64 `group_count`s back. Only participating
executors (<= 8 for MSET-8) are ever read afterwards (2565, 3438, atomics_glue.inc:244,
scatter_engine.inc:3601). D1 fix: construct exactly the participating slots inside
`initialize_owner_completion` (one `seen[kMaxThreads]` byte array on the stack) and drop the
64-slot loop. `OwnerRecordRefs` is an aggregate with trivial destructor (implicit-lifetime), so the
existing all-slot reset in `xshard_multi_child_complete` (3692-3696) stays legal on the
unconstructed slots it writes.

`build_initial_groups` / `build_groups` (804-847 / 780-802) zero two 1 KiB arrays and walk
`sid = 0..255`; a `for (sid < nshards)` bound removes ~190 useless iterations per op (D2).
Group ORDER (ascending shard id) is preserved exactly — `groups[0].shard` is the fan-out lead
(1816) and posting order feeds task queues, so a reordering would be an algorithmic change and is
not made.

### 1.3 Atomics/fences where the single-owner invariant would allow plain stores

Checked every atomic in the group path. `state.aborted` / `state.epoch` / `record_refs` /
`watch_refs` / `pending` are cross-owner by construction (last-owner commit, IO retire, foreign
resolvers via `group_epoch`), so none can be demoted. `owner_record_refs[slot].nodes/remaining`
are already plain (single executor). `atomic_activity_` fetch_add/sub fire only on the
empty<->non-empty edge (897-898, 1338-1339). `group_refs->fetch_sub(1, release)` on collapse
(1335-1336) is required: it is the deferred-destroy handshake (`reap_deferred` 528-543 loads with
acquire). No demotable atomics found. The `atomic_epoch()` acquire load per resolver visit (140)
is the read side (B+), not touched.

### 1.4 Record fields never read

`AtomicEntry::prev` (atomic_mvcc.h:19) is written at link/unlink and never read — the list is
walked forward only and unlinking is always a prefix cut. It cannot be deleted (144-byte lock) but
is 8 bytes of dead payload that a future field could reuse without growing the record.
`AtomicResolved::matched/physical` (100-104) are computed and dropped at 547.

---------------------------------------------------------------------------------------------------

## 2. Stability findings with mechanism (audit question 2)

### S1 — FLUSH leaves `atomic_read_epoch_` finite (FIXED, commit 2)

Mechanism. `find()` (flatstore.h:985-990) resolves every key through
`atomic_resolve(h, key, atomic_read_epoch_)` whenever `atomic_pending_->live != 0`, so the
per-store read context is load-bearing for every read on a shard that has records. Contexts are
bracketed by every caller — `ReadEpochGuard` (scatter_engine.inc:2533-2547; binds only when the
group carries a finite snapshot), `xshard_plain_prepare`/`xshard_plain_finish` (ex_loop.h:2571-2576),
begin_plain_version's error arms (atomics_glue.inc:34-57), the script Read wave (2239/2253) — except
one: `atomic_tombstone_all` (flatstore_atomic.inc:601-632) installs one tombstone per tracked key
through `atomic_install_plain`, whose last statement is `atomic_read_epoch_ = epoch` (523). The
AllShards / DebugReload / DebugLoadAof arms that call it (scatter_engine.inc:2920-2921, 2925, 2936)
run under an UNBOUND guard (FLUSH has no snapshot: 1675-1678, `key_count == 0`), so nothing
restores UINT64_MAX afterwards. The store's cut stays at FLUSH's ticket until the next plain op on
that shard or the next bound scatter fragment.

Who reads unbound? `execute_atomic_direct_rename` (atomics_glue.inc:82) — RENAME is `read_latest`
(2545) — and the MULTI-child atomic pop hop two (2802-2806 skips `begin_plain_version` when
`multi_child`). Trace for RENAME after `MSET... ; FLUSHDB ; MSET...` on the source shard with a
floor pinned (so the first MSET's record survives to FLUSH): list = [E_mset1 (T1, parked=base),
E_flush (Tf, parked=v1), E_mset2 (T2, parked=null)], cut=Tf, conn=0. Resolver: E_mset1 visible,
E_flush visible (Tf <= Tf) -> winner null, E_mset2 (T2 > Tf, own_committed false because the
read carries conn 0) -> excluded. RENAME answers "ERR no such key" for a key its own MSET
acknowledged. This is exactly the RYOW hazard class the lane must protect.

Fix (implementation-level, no visibility change): `atomic_tombstone_all` saves the read context
before its install loop and restores it after. Callers that had a legitimate context keep it;
callers that had none get UINT64_MAX/0 back. Regression: `tests/atomic_hazards.py` §1 (pins the
floor with a parked cross-shard MGET via DEBUG ATOMIC-FANOUT-DEFER, then MSET/FLUSHDB/MSET/RENAME
on one pipelined connection and asserts RENAME=OK and GET dest=new value; the pinned floor is
asserted non-vacuously by checking the FLUSH really tombstoned: INFO atomic entries advance).

### S2 — XREAD/XREADGROUP touch no keys in the localfast MVCC glue (FIXED, commit 3)

Mechanism. `xshard_prepare` marks a 1-key non-blocking XREAD/XREADGROUP `local_xshard`
(scatter_engine.inc:1603-1604, 1612-1621). Owner-side, both the program-order fence and the read
bind consult `for_each_touched_key` (atomics_glue.inc:320-375), which for `Kind::Xread/Xreadgroup`
calls `key_count_for(..., xread_count = 0, ...)` (366) and therefore visits nothing. Consequences:
(a) `xshard_task_should_defer` (741) finds no own-undecided predecessor, so a pipelined XREAD runs
while its own connection's older cross-shard DEL/EXEC child on that stream is still epoch-0;
(b) `xshard_plain_prepare` (911-929) records nothing, returns true without
`atomic_set_read_context`, and the handler reads at (UINT64_MAX, conn 0) — an own private
tombstone/XADD is invisible (resolver 974-983: `owner.group_epoch && epoch == 0 && !own_committed`);
(c) `has_parked_predecessor` -> `xshard_tasks_share_key` -> `for_each_task_key` (753-808) also
reports no overlap for a plain XREAD. `op.atomic_hazard()` IS set for the XREAD
(io_loop.h:4628 precedes the Blocking branch), so only the key enumeration is missing.
IO already parsed the op successfully (xshard_prepare 1473-1479), so re-parsing on the owner
cannot fail or write to the sink.

Fix: enumerate XREAD keys via `stream_parse_xread` (first_key + key_count) and XREADGROUP's via
`stream_parse_xreadgroup` (key_arg) inside `for_each_touched_key`; add XREADGROUP (a Write) to
`xshard_local_snapshot_prepare`'s key list so its PEL mutation takes the same COW pre-image gate
every other localfast write takes. Regression: `tests/atomic_hazards.py` §2 (DEBUG
ATOMIC-COMMIT-DELAY widens the epoch-0 window; pipelined cross-shard `DEL stream other...` then
`XREAD STREAMS stream 0` must answer nil, and the armed rounds assert the XREAD really waited
inside the window — non-vacuous per the harness rules).

### 2.3 Connection close mid-group — SAFE

`Client` cannot be freed while `atomic_groups_io_ != 0` (conn.h:683-704); the counter is
incremented at every atomic dispatch (io_loop.h:4861 inside the `atomic_write` branch,
multi.inc:1510, blocking.inc:1254) and decremented only at retire (scatter_engine.inc:3728,
multi.inc:1916), both gated identically on `atomic_group`. The arena outlives retire while records
name it: `xshard_destroy` defers (1875-1878) on `record_refs || watch_refs`, `free_state_contents`
frees only heap sidecars, and `key_order`/`keys`/`owner_record_refs` stay in the arena until
`reap_deferred` (528-543). Group key identity (`xshard_atomic_key_slice` 295-300) dereferences
`stable_object->key()`; that object is either the installed value (later parked, immutable, freed
only when ITS entry collapses, which is after this one because collapse is a strict prefix) or a
DEL anchor freed by `free_state_key_anchors` at reap. Expiry (flatstore.h:1305) and eviction
(2054, flatstore_atomic.inc:417) both skip keys with records, so no third party can free a
`stable_object` early. No defect.

### 2.4 OOM mid-group (DENYOOM/maxmemory) — SAFE

`xshard_execute` atomic_write: admit failure on key i unadmits nothing extra (admit charges only on
success), discards a not-yet-published value only if owner-built (2565; an IO-prebuilt one stays on
`key_anchor` and is freed at reap), sets `aborted`, and publishes the partially-installed entry when
`installed > 0` (2578-2583) so collapse restores predecessors (aborted arm 1381-1425) — or discards
it when nothing was installed (2585). `execute_atomic_apply`: capacity first (175), materialize all
(183-223), admit all with rollback (225-240), prepare entry with rollback (245-256), then an
infallible install loop. `begin_plain_version` releases entry+clone+context on every failure arm.
Byte accounting is symmetric on every arm (see 3.6). No defect.

### 2.5 Resize during a group — SAFE

`atomic_prepare_capacity` (357-395) guarantees `live+tombs+additional < 70% cap` or grows, and is
called before every install pass (2458, atomics_glue.inc:175, 984, 54, multi.inc:795, and collapse's
restore path 1575). Eviction inside `atomic_admit` converts live->tomb (sum unchanged) so the
guarantee survives interleaved admits. `atomic_exchange_physical` handles the rehash split
(1203-1207). `atomic_prepare_capacity` may `rehash_step()` between `find()` and install in
`begin_plain_version`; rehash moves pointers, never objects, so `visible` stays valid. No defect.
Law "new alloc path joins the resize trigger": every path that inserts (group install, plain
install, transaction install, collapse restore) is preceded by `atomic_prepare_capacity`. Holds.

### 2.6 EXEC nested with WATCH — SAFE (read for context; not my file)

`prepare_write_key` (multi.inc:769-829) reserves the watch (`watch_reserve_write` with the
transaction's epoch/abort words and `watch_refs`) BEFORE capacity/clone/admit/install, and the
finalizer decides once (1852-1877) and only then `finalize_reservations`. Child scatters point at
their own epoch/abort words and are published together via `publish_multi_child_epochs` inside the
commit bracket (1868-1870 + server.h:2444-2452), so a reader sees all or none. The
`atomic_has_own_undecided(..., &state.epoch)` exclusion-by-epoch-word (782-787) is observability
only, as its comment says. No defect found in the atomic glue for this path.

### 2.7 Other checks

- `atomic_promote_all_for_shutdown` (2026-2034) aborts if `snapshot_active_` (collapse returns
  false) — shutdown during a BGSAVE with live records => `std::abort()`. Cold, exit-path only;
  noted, not changed (shutdown ordering is main's).
- Direct RENAME `direct_ready` handshake (atomics_glue.inc:73-79, 132): destination retries until
  1/2; `xshard_task_should_defer` 691-704 parks rather than spins. Fine.
- `xshard_prepare` failure arms after arena creation all route through `xshard_destroy`
  (1775, 1785, 1832), which unregisters the snapshot, closes `apply_open`, retires admission and
  frees prebuilt values. Fine.

---------------------------------------------------------------------------------------------------

## 3. Preservation floor and accounting (audit question 2, continued)

### 3.5 Preservation floor — no violation found

Cleanup selects a strict list PREFIX of entries with `aborted || (epoch && epoch < floor &&
epoch <= cleanup_cutoff)` (1266-1277). floor = min over IO threads of (oldest registered inclusive
cut + 1) (server.h:2591-2606; register/unregister/refresh keep an exact min with refcounts,
atomics_glue.inc:402-514, including the publish-then-confirm handshake 419-450). Every entry in the
prefix therefore has epoch <= every live reader's cut, so the prefix's per-key argmax IS what the
oldest reader would answer; it is promoted into the boundary slot or the table (1553-1598) and the
losers are retired only after all key derefs (1614-1618). Owner-pass ordering "cutoff before floor"
is honoured at both call sites (ex_loop.h:1695-1696, atomics_glue.inc:1042-1044). Entries that are
undecided (epoch 0, not aborted) stop the prefix (1273), so a private version is never reclaimed.

### 3.6 Gauge underflow counters — no driver found

`atomic_gauge_sub` (333-340) is the single shrink point. Charge/uncharge pairs checked:
plain install: admit(+clone) / install_plain(-clone, +old) (519-520); group install: admit(+v) per
key / finish_group_install(-sum v, +sum old) (317-323, 2579); unadmit(-v) mirrors admit exactly
(428-430); collapse direct: -parked per slot (1332); collapse aborted/no-boundary: -parked, loser
(physical, never charged) retired uncharged (1429-1443); collapse aborted/boundary: -loser,
replacement moves into the boundary slot still charged, -parked only if it is not the replacement
(1419-1427); overlap collapse: -slot when replaced (1586-1588), -parked unless it stays parked as the
boundary winner (1606-1608), `physical_loser` uncharged (1613). Sizes are stable between charge and
uncharge because parked objects are immutable and the clone that a handler mutates in place is
physical (uncharged) at that time. Nothing found that could drive `atomic_gauge_underflows`.

---------------------------------------------------------------------------------------------------

## 4. Cleanliness (audit question 3)

- No disabled bake-off arms remain in the four files. The only `#if` is
  `TOMO_READ_LOCAL_SET_TAX_VARIANT == 3` (441-453, 1226-1235) — B+'s.
- `publish_epoch`/`publish_aborted` (536-542) are identity wrappers from the per-child decision
  era; harmless.
- Duplicated helpers between atomics_glue.inc and scatter_engine.inc: none that are byte-similar.
  `for_each_touched_key` (glue 320-375), `xshard_local_snapshot_prepare` (glue 545-611) and
  `key_count_for/key_arg_for` (engine 639-678) are three "which args are keys" answers for three
  purposes (program-order set, snapshot pre-image set, routing set) and legitimately differ; S2 is
  what happens when one of them drifts. Not merged tonight (a routing-table change, IDEAS §7.6).
- Misleading names: `atomic_sweep(…, budget)` (592-595) does not honour `budget`;
  `xshard_cleanup_shard_at(…, budget)` passes it through. `AtomicResolved::physical` means
  "winner came from the table", not "physical pointer". `ShardGroup::membership` is only built for
  atomic groups (798-799, 838), so it reads 0 on ordinary groups — fine but undocumented.
- Dead: `AtomicEntry::prev`, `AtomicResolved::matched/physical`, `count_predecessor` (always true).

---------------------------------------------------------------------------------------------------

## 5. Changes made tonight (each its own commit; what / why / expected effect / risk)

1. **AUDIT-ATOMICS.md** (this file).
2. **S1 fix — `atomic_tombstone_all` restores the read context.** What: save
   `atomic_read_epoch_/atomic_read_origin_conn_id_` before the tombstone install loop, restore after.
   Why: `atomic_install_plain` sets the epoch for its ordinary caller (`begin_plain_version` needs
   the fresh clone visible to the handler) and FLUSH inherited that side effect. Effect: no
   behaviour change on any bracketed path; unbound reads after FLUSH/DEBUG RELOAD resolve at
   "latest" again. Risk: nil — two scalar saves/restores on a cold path (FLUSH with live records).
   Test: `tests/atomic_hazards.py` §1.
3. **S2 fix — XREAD/XREADGROUP key enumeration.** What: `for_each_touched_key` parses XREAD
   (`stream_parse_xread`) / XREADGROUP (`stream_parse_xreadgroup`) key ranges instead of passing
   `xread_count = 0`; `xshard_local_snapshot_prepare` gates XREADGROUP's stream key. Why: the
   localfast stream read/PEL-write must join the same own-undecided fence, read-context bind and
   COW gate as every other localfast command. Effect: a pipelined XREAD behind its own connection's
   undecided DEL/EXEC on the stream now defers until the group decides, then reads at its cut with
   its origin conn (RYOW restored); XREADGROUP during BGSAVE takes a pre-image like XADD does.
   Risk: low — the parser already succeeded on IO for every op that can reach these functions; the
   cost is one option-word scan per XREAD on shards that have records (or carry a hazard).
   Test: `tests/atomic_hazards.py` §2.
4. **E1 fix — NX validator probes instead of scanning.** What: new public
   `FlatStore::atomic_has_physical(hash, key)` (wraps the existing private `atomic_find_physical`,
   which probes both tables exactly as `for_each` visits both), used in `execute_atomic_apply`.
   Why: the collision arm did an O(N) full-shard walk per retry. Effect: identical verdict, O(1).
   Risk: nil.
5. **D1+D2 diet — participant-only OwnerRecordRefs, nshards-bounded group build.** What:
   `init_arena_arrays` no longer constructs all `nthreads` slots; `initialize_owner_completion`
   constructs exactly the slots it counts (stack `seen[kMaxThreads]`); the three group builders loop
   `sid < nshards`. Why: §1.2. Effect: ~56 fewer cache lines written and read per atomic group on a
   64-thread server; ~600 fewer IO instructions per scatter op; group order and dispatch order are
   unchanged. Risk: low — every reader of `owner_record_refs[slot]` is a participating executor
   (2565, 3438, 3601, glue 244); the all-slot reset in `xshard_multi_child_complete` (3692-3696)
   writes an implicit-lifetime aggregate and remains legal. Expected to be measurable only as
   instr/op on the IO side; NOT a headline number.

Zero new compiler warnings (checked against a baseline build of the unmodified tree). Layout
locks untouched: no struct in the locked set changes (`AtomicEntry`=144 asserted at
atomic_mvcc.h:54; `ScatterState` arena fit asserted at scatter_engine.inc:519).

---------------------------------------------------------------------------------------------------

## 6. Left alone, and why

- Everything under `read_local_enabled_` and the resolver body (`atomic_resolve_internal`,
  `atomic_find_tracked`, membership filter): B+ lane. Includes D3 and the promote-loop hoist idea.
- `atomic_sweep` budget contract (C2): signature shared with ex_loop.h (another lane's file).
- `AtomicEntry::prev` removal (C1): 144-byte layout lock; only reusable, not removable.
- `record_refs` per-owner RMW and the ScatterState header-line contention: protocol change
  (IDEAS §7.1/7.2).
- DEL key-anchor allocation (D4): record-lifetime/layout change (IDEAS §7.3).
- Shutdown-during-BGSAVE abort (2.7): main/shutdown ordering, not this lane.
- `for_each_touched_key` / `xshard_local_snapshot_prepare` / `key_arg_for` unification (§4):
  a routing-table refactor that touches classify(); S2 is fixed inside the existing shape instead.

---------------------------------------------------------------------------------------------------

## 7. ARCHITECTURAL / ALGORITHMIC IDEAS (not implemented)

Each idea: what, why it might pay, and one line on how it respects the owner's design philosophy
(single-owner writes / no shared-writer index; reads never obstructed — immutable replacement +
QSBR, no reader retries or seqlocks; no in-place overwrite while read-local is armed; numeric knobs
0=off/-1=auto with self-derived thresholds; main commands zero-regression; hardcode-or-delete;
one file per feature).

7.1 **Pre-counted `record_refs` (drop one contended RMW per owner per group).** Today every
    installing executor does `record_refs.fetch_add(1)` (2582, glue 283, multi.inc:823) on the
    ScatterState header line that all owners are also `pending.fetch_sub`-ing, and cleanup later
    `fetch_sub`s it. Pre-setting `record_refs = participating executors` at prepare (IO side, plain
    store before publication) turns the install-time add into nothing and requires only that an
    executor which installs NOTHING (abort/MSETNX-fail/zero installed) decrements once. Saves ~1 of
    ~3 header-line transfers per owner per MSET; needs the never-dispatched teardown arm
    (`xshard_destroy` before any owner ran) to zero it so `defer_destroy` cannot leak. Philosophy:
    pure accounting on the single-owner path; readers untouched; no knob; zero-regression by
    construction on non-atomic commands (they carry no records).

7.2 **Split the ScatterState hot header.** `pending`, `epoch`, `record_refs`, `watch_refs`,
    `aborted` (367-376) share one line. Every resolver on every owner loads `epoch` through
    `group_epoch` (atomic_mvcc.h:138) while completing owners RMW `pending`/`record_refs` on the
    same line; moving `epoch`+`aborted` (read-mostly) to their own line makes the read side a
    shared-state hit instead of a bouncing line. Arena-only layout change (ScatterState is not in
    the lock set; the 16 KiB MGET-8 fit assert at 519 must hold). Philosophy: reads never
    obstructed — this removes a write-side line bounce from the read path without touching
    visibility.

7.3 **DEL groups without a per-key anchor allocation.** DEL/UNLINK allocate one `KvObj` per key
    (2638) whose only job is to own the key bytes for `xshard_atomic_key_slice`. Alternatives:
    (a) give group entries a variable-length key-bytes tail like plain entries (`plain_key_data`),
    sized at `atomic_prepare_group` from the span's total key bytes — one allocation per owner span
    instead of one per key; (b) arena-carve the anchors in `xshard_prepare` (IO side, one block).
    Both keep the record immutable and owner-written. Philosophy: single-owner writes preserved;
    hardcode (one layout), no knob; MGET/MSET unaffected (zero-regression on main commands).

7.4 **One collapse attempt per owner pass instead of one `atomic_promote_key` per key.**
    `xshard_execute` calls `atomic_promote_key` per key (2514-2532) and `xshard_plain_prepare` per
    touched key (913, 1019); each is a membership-filtered list walk plus a prefix scan, but
    `atomic_collapse` is key-agnostic (it reclaims the whole eligible prefix regardless of which key
    asked). Hoisting to "walk once, collapse once if anything is eligible" per owner task would cut
    k-1 list walks for a k-key group on a tracked shard. Read-side adjacent (touches the promotion
    trigger next to B+'s filter), so an idea only. Philosophy: cleanup stays owner-local and
    off the reader's critical path; no semantics change (same prefix reclaimed).

7.5 **Exchange-or-insert in one probe run.** For a NEW key `atomic_exchange_physical` probes to an
    empty slot, returns nullptr, and `insert_into` (1209) probes again from the start remembering
    the first tombstone. A single run that records first-tombstone and terminal-empty and inserts
    directly halves probe work on new-key installs. Touches the table insert discipline that the
    read-local twin mirrors, so it belongs with B+ or after B+ lands. Philosophy: no reader impact;
    identical table state; zero-regression on SET (which uses `insert()`, not this path).

7.6 **One key-position oracle.** `for_each_touched_key`, `xshard_local_snapshot_prepare` and
    `key_count_for/key_arg_for` each re-derive "which argv are keys" per Kind. S2 is the drift they
    permit. A single `classify_keys(op) -> span list` consumed by all three (routing on IO, fence and
    COW on owners) removes the class of bug. It changes `classify()` ownership (command registry
    adjacent), hence not tonight. Philosophy: one file per feature (the oracle lives with classify),
    hardcode-or-delete (no per-command tables in three places).

7.7 **Cheaper group commit for single-executor groups.** When every shard of a group is owned by
    one executor (16-shard/8-executor placements make this common for 2-key groups), the
    `pending`/`remaining` two-level completion (3436-3443) and the commit bracket still run their
    atomics although no other thread can observe the intermediate state; a "single owner" fast arm
    could commit with plain stores plus one release store of `epoch`. Philosophy: single-owner
    writes made explicit; readers unchanged (they still see epoch 0 -> ticket); no knob.
