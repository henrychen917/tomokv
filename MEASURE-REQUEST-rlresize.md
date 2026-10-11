## rlresize

Worktree/branch `/home/user/Projects/cx-rlresize` / `cx-rlresize`, from origin/cpp `991d48f65`
(PRE). Not pushed. Every build, server, oracle and client ran under `taskset -c 80-95` (owner
override of the spec's 112-127: servers 80-87, Redis oracle 88, clients 89-95); ports 25451-25471.

The txnfix2 abort is fixed. The path audit found two more omissions of the same rule on one FLUSH
path; each has its own deterministic reproduction (fails on PRE), its own fix commit and a gate row.
No existing test assertion changed; `EXPECT_QUICK`/`EXPECT_FULL` are untouched.

| Check | PRE `991d48f65` | POST | Receipts |
|---|---|---|---|
| `atomic_torn.py`, txnfix2 argv, armed fused, 16 databases | server SIGABRT (exit -6) | **5/5 pass** | [PRE](docs/rlresize/pre-original-16db/run.json), [PRE stack](docs/rlresize/pre-original-16db-gdb/server.log), [POST](docs/rlresize/proof/batteries.log) |
| same, 1 database | server SIGABRT (exit -6) | **5/5 pass** | [PRE](docs/rlresize/pre-original-1db/run.json) |
| txnfix2's split argv (2s 6:2, read-local 0) | passes (txnfix2) | **1/1 pass** | `docs/rlresize/proof/batteries/torn-split-16db/` |
| `rehash-waits-unit atomic-growth` (real owner queue) | SIGABRT 3/3; gdb: `resize_retirement == nullptr` | **PASS 3/3** | [PRE](docs/rlresize/unit-atomic-growth-pre/), [POST](docs/rlresize/unit-atomic-growth-post/run.log) |
| live DEBUG-driven repro, 16 and 1 databases | server lost at the completing SET (256 of 256) | **resize completes; 1691 keys read back** | [PRE](docs/rlresize/server-repro-pre-16db/test.log), [POST](docs/rlresize/server-repro-post-16db/test.log) (and `-1db`) |
| `rehash-waits-unit flush-prepared` | SIGABRT 3/3; gdb: record null | **PASS 3/3** | [PRE](docs/rlresize/unit-flush-prepared-pre/), [POST](docs/rlresize/unit-flush-prepared-post/run.log) |
| `store-regression flush-prepared-capacity` (disarmed and armed) | merge stalls forever 3/3 (armed control too) | **PASS 3/3** | [PRE](docs/rlresize/unit-flush-capacity-pre/run.log), [POST](docs/rlresize/unit-flush-capacity-post/run.log) |
| hot bodies vs PRE (`lbstall_artifacts.py compare`) | | **1204/1204 identical** | [hot.log](docs/rlresize/identity/hot.log) |
| full bodies (`ccfix_audit.py`) | | hot 1208/1208, handlers 1211/1211; 61 of 16447 changed: 30 lane, 31 cold/growth | [summary](docs/rlresize/identity/full/summary.json) |

### Defects

**1. Armed atomic growth skipped the retirement reservation (txnfix2's abort).**
`atomic_prepare_capacity_read_local()` (`src/store/flatstore_atomic.inc:794`) grows the table for an
atomic owner pass. It allocated and published the new table without `prepare_resize_retirement()`,
which every other armed resize start runs. The completing step `rehash_step_read_local()` cannot
allocate; with the production owner sink (`defer_resize` bound, `src/core/read_local.h:269`) it
aborts on a missing record (`src/store/flatstore.h:3261`). Boot reserves one record, so the first
resize on a shard always completes: the abort needs an earlier completed resize to have consumed the
boot record. That is why txnfix2's fresh-server `held_burst` reduction passed while the full battery,
with its table history, aborted. Split never arms a store (`configure_read_local(true)` exists only
in `ExLoopT::activate_fused`). History: `4788b2102` (09-02) added the armed atomic growth; `bf41dd331`
(09-09) introduced the reservation and missed that path.

**2. FLUSH between snapshot prepare and mark released the prepared snapshot's record.**
`cmd_flush` (`src/cmd/t_server.cc:2838`) calls `clear()` whenever no capture is active, and Preparing
and Prepared owners keep executing tasks (`snapshot_blocks_tasks`, `src/core/ex_loop.h:1844`). So
FLUSHALL (FLUSHDB with one database) can land after `snapshot_prepare` reserved the record and
allocated the post-cut table, and before `snapshot_mark` publishes it. `clear_read_local` released
the record unconditionally; mark published the table anyway; the post-capture merge then aborts.

**3. The same FLUSH escaped the prepared snapshot's capacity plan (both modes).**
`snapshot_prepare` sizes the post-cut table at 2 x `cap_[0]`: while prepared the current table cannot
resize and refuses new keys only when full. `clear()` always installed 1024 slots. A store shrunk
below 512 slots could therefore accept, before mark, more keys than the prepared table holds. After
the cut `insert_into` finds no free slot and `rehash_step` returns without advancing, forever: the
cut table is never retired and new keys are refused. This is the "joins the resize trigger" half of
the rule, and it is not armed-only.

### Fixes (one commit each, reproductions first)

| Reproduction | Fix | Change |
|---|---|---|
| `3295a52c4` | `71d73fc87` | atomic growth reserves the record exactly as `start_rehash_read_local`: allocate the table, `prepare_resize_retirement()`, on refusal free the table and return the capacity failure every atomic caller already reports (InsertFailed/Oom/Error) |
| `162198f94` | `e10af7c60` | `clear_read_local` keeps the record while `snapshot_prepared_` |
| `8c5ff1945` | `572dc3b2c` | `clear_capacity()`: FLUSH's replacement is `min(prepared / 2, 1024)` while prepared, 1024 otherwise (`clear` and `clear_read_local`; the allocation-failure fallback already keeps the current capacity) |

`6728441c3` spelled the reservation in place to keep the helper inlined; trials showed it moves hot
bodies no budget restores, so `2724c6de6` reverts it. `986bd6f10` re-derives the inlining budgets.
`381f97ae1` adds the gate rows. Edits above the `make_word` assertion are in place, so its compiled
`__LINE__` stays 2280.

### Reproductions

- **Original battery** ([PRE runs](docs/rlresize/pre-original-16db/run.json)): the unchanged
  `tests/atomic_torn.py` with txnfix2's exact argv (ports/cores adapted) loses the PRE server with
  SIGABRT for 16 and 1 databases; under gdb the abort is `rehash_step_read_local` completing a resize.
- **Deterministic unit** (`tests/rehash_waits_unit.cc`, selections `atomic-growth`,
  `flush-prepared`): the existing real-QSBR fixture (real `ReadLocalDeferredQueue` sink with
  `defer_resize`). `atomic-growth` consumes the boot record with an ordinary resize, fills the table to
  one key below the 70% trigger and calls `atomic_prepare_capacity(1)`, which doubles it (128 -> 256);
  owner maintenance completes the resize. PRE: SIGABRT 3/3; gdb at the abort frame shows
  `read_local_extended == true`, `resize_retirement == nullptr`, `defer_resize ==
  ReadLocalDeferredQueue::init` lambda, `cap_ == {256, 0}` (the txnfix2 state).
  [gdb](docs/rlresize/unit-atomic-growth-pre/gdb.log). `flush-prepared`: prepare, `clear()`, a
  write, mark, full capture/handoff, merge -> PRE SIGABRT 3/3, record null
  ([gdb](docs/rlresize/unit-flush-prepared-pre/gdb.log)).
- **Deterministic live server** ([atomic_growth_server.py](docs/rlresize/atomic_growth_server.py)):
  armed fused, maintenance paused (`DEBUG SET-ACTIVE-EXPIRE 0`), `DEBUG REHASH-STATE` checked after
  every step: plain SETs grow shard 0 1024 -> 2048 and complete it; SETs fill to 1433 keys; one
  cross-owner atomic MSET grows shard 0 to 4096 (rehash count unchanged: the atomic path); plain SETs
  drive the resize. PRE dies at drive SET 256 of 256 (exit -6, 16 and 1 databases); POST completes and
  reads back every key.
- **Capacity** (`tests/store_regression.cc` case `flush-prepared-capacity`): `FlatStore(64)`,
  prepare (128-slot post-cut table), `clear()`, insert until refused, mark, capture, merge. PRE: 256
  keys accepted, merge stalled at old cursor 486/1024 with 128 keys unmoved (disarmed 3/3; an
  armed-first control copy fails identically). POST: 63 keys accepted (the same refusal the
  pre-flush table had), merge completes, all readable, new keys accepted.

FLUSH-in-the-window is shown reachable from source (above), not by a live race: holding owners
between prepare and mark needs a timing window, so the gated reproductions are the deterministic
store-level sequences of exactly that call order.

### Path audit

Rule: every armed resize start reserves the record its completion hands, with the old table, to the
owner FIFO; every allocation path joins the resize trigger. Armed = fused `--read-local 1` store with
the production sink. Plain stores have no foreign reader, so a direct `free` is correct there.

| # | Path (POST source) | Tables | Record (armed) | Trigger / capacity | Verdict |
|---|---|---|---|---|---|
| 1 | `FlatStore()` -> `alloc_table` (flatstore.h:675, :2503) | table 0 at construction | n/a: built disarmed; #2 reserves | n/a | OK |
| 2 | `prepare_read_local` (:706) | none | reserves the boot record | n/a | OK |
| 3 | `maybe_start_grow`/`maybe_start_shrink` -> `start_rehash` -> `start_rehash_read_local` (:3542, :3558, :3571, :3219) | new table 0, old demoted | reserves before publishing; frees the table on failure | 70% grow, 17.5% shrink, both suppressed while prepared | OK |
| 4 | `rehash_step` plain (:3587) | frees table 1 at completion | n/a | n/a | OK |
| 5 | `rehash_step_read_local` (:3236) | unlinks table 1; record + table to `defer_resize` (serverless sinks retire synchronously) | consumer; aborts without a record | n/a | OK once every start reserves |
| 6 | `atomic_prepare_capacity` plain (flatstore_atomic.inc:422) | grows table 0 for an atomic pass | n/a | insert's discipline | OK |
| 7 | `atomic_prepare_capacity_read_local` (flatstore_atomic.inc:794) | grows/publishes table 0 | **missing** | insert's discipline | **confirmed, fixed (`71d73fc87`)** |
| 8 | `snapshot_prepare` (:1081) | allocates the unpublished post-cut table | reserves first | 2 x `cap_[0]`; resizes suppressed until the cut | OK |
| 9 | `snapshot_mark`/`snapshot_mark_read_local` (:1107, :2751) | publishes it; current becomes the frozen table 1 | uses #8's record | relies on #8's sizing | OK given #12/#13 |
| 10 | `snapshot_cancel` (:1212) | frees a never-published prepared table | record stays spare | n/a | OK |
| 11 | `snapshot_handoff_complete` (:1200) | frozen table becomes an ordinary old table for #5 | #8's record | capture-time gate | OK |
| 12 | `clear_read_local` record release (:2945) | FLUSH retires both tables via the object ring | **released while a snapshot was prepared** | n/a | **confirmed, fixed (`e10af7c60`)** |
| 13 | `clear`/`clear_read_local` replacement (:1773, :2945) | fresh table 0 | n/a | **1024 slots regardless of the prepared plan** | **confirmed, fixed (`572dc3b2c`)** |
| 14 | `clear_during_snapshot`/`_read_local` (:1808, :2989) | FLUSH during capture: tombstones only | untouched | n/a | OK |
| 15 | `multidb_flush` (multidb.cc:656) | per-key erase; shrink via #3 | via #3 | via #3 | OK |
| 16 | SWAPDB `multidb_commit_swap` (multidb.cc:744) | namespace map only | none | none | N/A |
| 17 | DEBUG RELOAD/LOADAOF (scatter_engine.inc, DebugReload/DebugLoadAof) | `clear()` then reload, growth via #3 | via #3/#12 | via #3/#13 | OK (inherits the fixed clear) |
| 18 | `~FlatStore` (:683) | frees at teardown after disarming | n/a | n/a | OK |
| 19 | `configure_read_local`/`rebind_read_local_retire_sink` (:715, :726) | none; a reserved record travels with its store across handoff | n/a | n/a | OK |
| 20 | `read_local_reclaim_table` (:3373), `ResizeRetireQueue` (resize_retirement.h) | frees retired tables after grace | consumer | n/a | OK |
| 21 | `ExpireIndex` (flatstore.h:143-360) | owner-only two-table index, freed directly | outside QSBR: foreign probes read only `tab_/cap_/mask_` and KvObj (GET/MGET only) | own triggers | N/A |
| 22 | collection tables (t_hash.cc, t_zset.cc) | owner-only | not read-local eligible | own triggers | N/A |

Every caller reaches #7 through `atomic_prepare_capacity`, so one fix covers all of them:
atomics_glue.inc:73 (plain atomic write), :201 (direct RENAME), :978 (owner-local prepared writes),
multi.inc:1036 (MULTI write prepare), scatter_engine.inc:2828 (scatter MSET/DEL/UNLINK...),
flatstore_atomic.inc:1517 and :1858 (rollback restore).
Not fixed (no correctness effect): neither atomic growth path increments `rehash_counter_`, so the
`rehashes` statistic omits atomic resizes (visible in the live repro).

### Gate rows: DQ = +3, DF = +3

| Row | Site | PRE | POST |
|---|---|---|---|
| `storage flush-prepared-capacity regression` | `job_storage_units` case list, `tests/gate.sh:1625` | FAIL (stall) | ok |
| `armed resize retirement: atomic-growth` | `job_atomic_units`, loop at `tests/gate.sh:1733` | FAIL (SIGABRT) | ok |
| `armed resize retirement: flush-prepared` | same loop | FAIL (SIGABRT) | ok |

Both jobs are collected (`:3577`, `:3579`) before the quick-tier exit (`:3715`). Source inventory
(`gate_ledger_fixture.source_labels`): PRE 625 quick / 642 full, POST 628 / 645
([inventory](docs/rlresize/gate-rows/inventory.json)). **Owner update: EXPECT_QUICK=628,
EXPECT_FULL=645**; the arithmetic comment sits above the untouched constants. `job_wait_units` is
not used because `gates_test` pins its two rows. The label fixture and `tools/iopass_validate.py` list
the new witnesses. The raw fixture check refuses only the count (fixture = source = 645, missing and
extra none) and its self-test is 9/10 for the same reason; an in-memory check at 645 passes
([raw](docs/rlresize/gate-rows/ledger-raw.log), [prospective](docs/rlresize/gate-rows/ledger-prospective.json),
[self-test](docs/rlresize/gate-rows/ledger-self-test.log)). Row snippets run with stubbed helpers:
[POST](docs/rlresize/gate-rows/rows-post.log) all ok, [PRE](docs/rlresize/gate-rows/rows-pre.log) all FAIL.

### Identity vs PRE (docs/ttlclean method)

The fixes add code to `atomic_prepare_capacity_read_local`, which ten objects emit, and to the
FLUSH bodies, so GCC's IPA starting units grow (+7 main/genthread/rl2s/reorder, +37 t_server/aof,
+44 xshard; [unit-sizes](docs/rlresize/identity/unit-sizes.jsonl)). The budgets were re-derived by
compile-only scans with per-body classification
([trials](docs/rlresize/identity/budget-trials/SUMMARY.txt), tool
[budget.py](docs/rlresize/tools/budget.py)). The in-place spelling and an out-of-line helper both
change ordinary bodies at every scanned value, including the hot `r7_fused_sweep_impl`; calling
`prepare_resize_retirement()` leaves a hot-clean value in every object, so it is the shipped form.

| Budget (large-unit-insns) | PRE | POST |
|---|---|---|
| src / db0 t_server.o | 31330 / 31725 | 31379 / 31766 |
| src / db0 aof.o | 34400 / 34800 | 34437 / 34813 |
| src / db0 xshard.o | 127880 / 126482 | 127924 / 126542 |
| src / db0 genthread.o | 129420 / 129640 | 129453 / 129655 |
| src rl2s.o / db0 reorder.o | 162300 / 148258 | 162311 / 148269 |
| main.o x2, db0 rl2s.o, src reorder.o (defaults) | | unchanged (main/db0 rl2s emit one object at every value) |

- `tools/lbstall_artifacts.py compare`: **1204/1204 hot bodies identical** (bytes + resolved
  relocation targets).
- `tools/ccfix_audit.py`: hot 1208/1208, command handlers 1211/1211; **61 of 16447** object bodies
  change ([changed-bodies](docs/rlresize/identity/full/changed-bodies.json)):
  - lane (30): `atomic_prepare_capacity_read_local` (10 objects), `clear` and `clear_read_local`
    (6 each), new out-of-line `prepare_resize_retirement` `.isra` clones in genthread.o/reorder.o (4
    objects x body + `.cold`);
  - growth/cold collateral of that outlining (8): `maybe_start_shrink` and
    `ExLoopT::snapshot_control_pass<32,false>` in those four objects now call the helper;
  - other cold bodies (23): FLUSH/AOF teardown and manifest (`~AofManager`, `manifest_name`), client
    migration (`command_client_migration_extract`), MULTI/SORT preparation (`prepare_commands`,
    `normalize_multi_blocking_pop`, `prepare_sort_deref` lambda), FLIP control
    (`flip_control_pass<true>`), LB sampling (`scan_home<lb_scan_bucket_bytes>`),
    atomic maintenance (`atomic_collapse`, `atomic_collapse_read_local`), capture gate
    (`snapshot_prepare_write`), `pubsub_start_publish`, and COMDAT copies (`kvobj_external_bytes`,
    `kvobj_free_with_capacity`, `std::` helpers).
- Linked binary (linker maps, [attribution](docs/rlresize/identity/linked-attribution.json)): the
  linker keeps main.o's or xshard.o's copy of each changed COMDAT, so **27 changed bodies reach the
  binary: 14 lane + 13 cold** (`snapshot_control_pass` x2, `command_client_migration_extract` x2,
  `prepare_commands`, `normalize_multi_blocking_pop` (+cold), `prepare_sort_deref` lambda (+cold),
  `~AofManager` x2, `manifest_name` x2). `maybe_start_shrink`, `kvobj_*`, `pubsub_start_publish`,
  `flip_control_pass`, `atomic_collapse*` and `snapshot_prepare_write` stay PRE's bytes in the binary.
- Layout: struct layouts are unchanged (no data member added; the layout `static_assert`s compile).
  Loadable sections differ (`.text` +1408 bytes; [linked.json](docs/rlresize/identity/linked.json)):
  542 of 544 hot functions move and 395 change their 64-byte-line offset
  ([placement](docs/rlresize/identity/placement.json)). Bodies are identical, so any throughput
  difference is placement only; if the owner wants the number, the standard null or PAD A/B applies.
  No benchmark was run.

### Proofs (CPUs 80-95)

| Proof | Result | Receipt |
|---|---|---|
| `make all` PRE and POST | exit 0, 0 warnings; POST `make -q all` fresh | [builds](docs/rlresize/proof/builds/README.txt) |
| `job_production_units` (29 targets) + `mdbqsbr-live-arms` | exit 0; **29/29 `make -q` fresh**; only the known warnings | [status](docs/rlresize/proof/builds/production-units.status) |
| `python3 tests/gates_test.py` | **66/66 OK** (80 s) | [log](docs/rlresize/proof/gates-test.log) |
| `atomic_torn.py`, txnfix2 argv: fused 16 db x5, fused 1 db x5, split x1 (fresh server each) | **11/11 pass**, servers alive and clean exit | [log](docs/rlresize/proof/batteries.log) |
| `atomic_ryow.py --no-rate-assertions`, `atomic_hazards.py`, `atomic_plain.py --atomic 1/0`, fused and split | **8/8 pass** | same |
| storage cases (all 13), `rehash-waits-unit retirement` / `maintenance` | all PASS | [log](docs/rlresize/unit-regressions-post/run.log) |
| Redis 7.4.10 differential, all 47 suites, seeds 7 19 20 23, atomic 0/1, split and armed fused | **split 376/376 legs, armed fused 368/368 legs, 0 differences**; both armed read-local witnesses fired (hits=983, atomic 0 and 1); the 8 armed `sort` legs skip by design (split-only suite); 232 of 245 commands diffed | [split](docs/rlresize/differ/split.log), [armed fused](docs/rlresize/differ/armed-fused.log) |

The torn battery skips its release-only promotion budget (argv has no `--release-build`, as in
txnfix2) and, once each, two OFF controls whose losing race did not manifest; no assertion was
changed. `atomic_ryow` ran with its existing `--no-rate-assertions` option, as txnfix2 did.
`tools/iopass_validate.py` pins itself to 112-127 and was not run; its new entries were run directly.

### Reproduce

```sh
# PRE: git archive 991d48f65 | tar -x -C build/rlresize/pre-src; copy tests/{rehash_waits_unit,store_regression}.cc
(cd build/rlresize/pre-src && taskset -c 80-95 make -j16 all build/rehash-waits-unit build/store-regression)
taskset -c 80-95 ./build/rehash-waits-unit atomic-growth      # also flush-prepared
taskset -c 80-95 ./build/store-regression flush-prepared-capacity
docs/rlresize/proof_batteries.sh build/tomokv all            # live atomic batteries
docs/rlresize/proof_differ.sh build/tomokv                   # differential, both geometries
taskset -c 80-95 python3 tools/lbstall_artifacts.py compare build/rlresize/pre-src/build build out.json
taskset -c 80-95 python3 tools/ccfix_audit.py build/rlresize/pre-src/build build out-full
```

Commits: `3295a52c4` `71d73fc87` `162198f94` `e10af7c60` `8c5ff1945` `572dc3b2c` `381f97ae1`
`6728441c3` `2724c6de6` `986bd6f10` + docs. Binaries: PRE `a2e29e80…` (`build/rlresize/pre-src/build/tomokv`),
POST `749b696a…` (`build/tomokv`); unit binaries in [binaries.txt](docs/rlresize/binaries.txt).
