# Lane correctness record

## blockwake

Blocking-client defects F6a, F6b, F6c, F7, F8 from
`round5-read/bounded-queue-wake-audit.md`. PRE is the published wave-15 commit `8be4f68323`
(`origin/cpp`); worktree `/home/user/Projects/cx-blockwake`, branch `cx-blockwake`, never pushed.
This is a correctness record and makes **no throughput claim**. CPUs 0-31 only; ports 23200-23299;
`LC_ALL=C` on every boot. The benchmark runner had already exited before any build.

Commits (one per item, on top of `8be4f68323`):
`66c95b0ac5` F6a · `cb5d7daf86` F6b · `22c7d3fac2` F6c · `2d61d86053` F7 · `ba3c71e2ae` F8 ·
`0ae112bbd4` db0 budget (zero-cost) · `076dbd4c20` + `76d0709d19` + `82736508f2` test/tool/gate.

### Table

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| **F6a** push to a cancelled waiter (S1 data loss) | `tests/blockwake.py cancel` vs the Redis 7.4 oracle: on PRE 30 of 36 trials deviate — a killed waiter's popped element is lost (LLEN 0 where Redis keeps 1), an unblocked waiter receives the element instead of its nil/`-UNBLOCKED` reply. Redis: 0. | 0 deviations in all four mode/engine legs (gate rows `blockwake cancel …`), 0 server-exit faults. BLPOP/BZPOPMIN/BLMOVE/XREADGROUP × KILL/UNBLOCK/UNBLOCK-ERROR. | `service()` and the deadline scan honour `cancel_requested` (hoisted into `honour_cancel`) before any claim, as `sweep()` already did. | none |
| **F6b** registering front waiter strands its followers (hang) | `tests/blockwake.py strand`: a SORT-stalled second owner holds W1's registration; `RPUSH k a b c` leaves W2/W3 blocked forever with LLEN 2 (PRE, all 4 legs). In 1s PRE, W1 even takes `c` out of FIFO order. | All 4 legs serve W1/W2/W3 `a`/`b`/`c` in FIFO order within 0.3 ms, LLEN 0 (gate rows `blockwake strand …`). | mark the shard dirty before the Registering early return; keep a claimed-here front waiter in place until its task pops, instead of removing it and serving followers first. | none |
| **F6c** probe-then-add registration wake race (narrow hang) | By construction (Dekker): a committer publishing data and reading the waiter count in the gap between a registration's empty probe and its add sees 0 waiters and skips dirty+wake. Positive-control hook `DEBUG BLOCKING-REGISTER-DEFER` added. | Closed as a Dekker: registration adds, `seq_cst` fence, reprobes; the waiter-count add is `seq_cst`; `Shard::blocking_publish_fence()` precedes every cross-owner count read (`blocking_atomic_published`, the EXEC commit). | add-then-fence-then-reprobe + producer fence + `seq_cst` waiter count. | Live client reproduction not achieved (see NOT RUN); fix is by-construction + covered by the differ blocking battery. |
| **F7** owner never re-checks the cross-thread dirty flag before parking (≤50 ms) | By construction: producer sets dirty + conditional `wake_if_parked`; the owner's park predicate never reads the flag, so a wake lost in the sweep→`arm_blocked` window waits out the park. `f7` harness could not hit the microsecond window from a client (max 3.5 ms over 400 swept trials — the owner re-polls/does not park). | Owner re-checks `blocking_owner_dirty_pending()` over its owned shards after `arm_blocked()`'s `seq_cst` fence (all three park paths); `set_blocking_dirty()` is `seq_cst`. Same publish-then-recheck shape as the credit doorbell. | park predicate now includes owned-shard dirty; gated on `blocking_waiters()!=0`. | Live 50 ms stall not reproduced (thread re-polls, not parks); by-construction + `txnorder_wake`/`atomwake` rows exercise the park/wake. |
| **F8** resumed BLMOVE refused by the atomic window never arms the doorbell (≤50 ms) | By construction: only `script_window_resume` set `credit_wait`; the blocking resume did not, so credit retirements/barrier clears rang every waiter except it. `f8` harness (saturated + commit-held window) woke in ~0.5 ms on both arms — the refused connection re-polls in `flush_ready`, so no 50 ms park observed. | On `ScatterPrepare::Backpressure`, if `!atomic_can_admit(self)`, set `credit_wait` — the same two lines as `script_window_resume`; `bbd7eb4880`'s doorbell now covers the resume. | credit-doorbell arm on the resumed-move refusal. | Live 50 ms stall not reproduced (connection re-polls); by-construction, identical to the `atomwake`-validated doorbell. |

### Production diff summary

`git diff --stat 8be4f68323 HEAD -- src Makefile`: 10 files, +175/-25.

- `src/cmd/blocking.inc` (+92/-14): `honour_cancel` (F6a) called in `service()` and the deadline
  scan; `claimed_here` keeps a Registering/claimed front waiter in place and marks dirty (F6b);
  add-then-fence-then-reprobe in the Registering branch + one-shot `DEBUG BLOCKING-REGISTER-DEFER`
  stall (F6c); `blocking_publish_fence()` at the top of `blocking_atomic_published` (F6c);
  `blocking_owner_dirty_pending()` (F7); `credit_wait` arm on the resumed-move Backpressure (F8).
- `src/core/shard.h` (+25/-5): `has_blocking_waiters`/`blocking_waiters` seq_cst loads,
  `blocking_waiter_added` seq_cst RMW, `set_blocking_dirty` seq_cst store, `blocking_dirty_pending`
  peek, `blocking_publish_fence` helper.
- `src/core/ex_loop.h` (+7/-1), `src/core/io_loop.h` (+8/-2), `src/core/reorder.cc` (+7/-2): the
  F7 pre-park dirty re-check in the split-EX and both fused (io_loop, reorder) park paths.
- `src/core/server.h` (+10): cold tail field `debug_blocking_register_defer_` + accessors (F6c
  control). Server is not a layout-locked constant; `Shard` is unchanged (1440 B).
- `src/cmd/multi_execute.inc` (+4): `blocking_publish_fence()` before the EXEC-commit count reads.
- `src/cmd/t_server.cc` (+14): `DEBUG BLOCKING-REGISTER-DEFER` handler.
- `Makefile` (+5/-1): db0 `xshard.o` `large-unit-insns` 171751→171932 (zero-cost compensation).

No architecture or algorithm change: single-owner writes, QSBR, the reorder ring, the atomic
window and the FIFO hand-off are untouched. All added cross-thread ordering is the same
publish-then-recheck / Dekker pattern the credit doorbell (`bbd7eb4880`) already uses.

### Row delta

New gate rows before the quick-tier exit: `job_blockwake_live` emits 2 rows (cancel, strand) for
each of 2s/1s × uring/epoll = **8 rows**. **DQ=+8, DF=+8**. `EXPECT_QUICK`/`EXPECT_FULL` and
`tests/fixtures/nullrefresh-ledger-labels.json` are maintainer-owned and untouched; the eight new
labels are `blockwake cancel: no element lost to a cancelled waiter (<mode>, <engine>)` and
`blockwake strand: a registering front waiter does not strand its followers (<mode>, <engine>)`.
No other row count changes; `EXPECT_QUICK=1177`/`EXPECT_FULL=1194` would become `1185`/`1202`.

### Arms (SHA-256)

| Arm | Path | SHA-256 | .text size |
|---|---|---|---|
| PRE | `/home/user/Projects/bins/blockwake-pre-0f2283a2` | `0f2283a25317c9a4106d03b1a1433a62340190d2196eb3d3e7687200b4d9f6cb` | 9,230,039 |
| POST | `/home/user/Projects/bins/blockwake-post-e8322077` | `e8322077682b9be1c0d265981e0aed7f4c4ca7bb4034a755fc28040c4cc42b2c` | 9,232,471 |
| PAD-A | `/home/user/Projects/bins/blockwake-pad-6aa96336` | `6aa963365a0ec284cc525d3c6908e342570d343249b9c5c14a71146a04d087aa` | 9,232,471 |

PRE is a clean build of `8be4f68323`. POST is `build/tomokv` at HEAD. PAD-A (kind A, behaviour
twin: `tools/blockwake_pad.py`) links PRE's objects with one padding object to POST's exact `.text`
start and size; it reproduces PRE's `strand` failure, so the +2,432-byte size change is not itself
the cause of any POST effect. No (B) inverse control: no throughput claim is made.

### Zero cost

Serverless command-scope instruction census (`tools/blockwake_counts.py`, the mset8fix tracer),
PRE vs POST, GET/SET/INCR/MGET/MSET × 1s/2s × batch 1/32 × atomic 0/1, both namespaces (normal and
db0), plus the parser kind. **All identical, 0 changed rows:**

| Census | Required rows | Identical | Changed hot bodies |
|---|---|---|---|
| ordinary | 72 | 72 | none |
| atomfix6 | 72 | 72 | none |
| parser | 36 | 36 | none |

The blocking-registry edits touch no counted command's scope, so **no hot body on GET/SET/INCR/
MGET/MSET changed** — not even atomic-1 MSET. The one hazard found and fixed: the +181-insn growth
of the db0 `xshard` unit (blocking.inc) tipped `FlatStore::find` past the threshold that inlines
`Slice::key_eq`, adding ~35 instr/op to db0 GET/INCR/MGET. Raising that object's `large-unit-insns`
by 181 (171751→171932) restored `find` to its PRE size (0x3eb); the normal namespace was never
affected. Confirmed by `nm` on the production binaries and by the re-run census (0 violations).

### Proof runs (CPUs 0-31, ports 23200-23299, `--candidate-binary build/tomokv`)

- **blocking / BLPOP·BLMOVE·XREAD / client-kill / atomics / txn / multidb jobs** (one
  `GATE_ONLY_JOBS` run): **55 ok, 0 FAIL** — blockfix4 (5), blockfix2 (7), blockfix_registry,
  blockfix_structure, blockfix_mkstream, atomwake-live ×4, atomwake_unit, atomfix6_units (12),
  atomfix6-live ×2, txnorder_fifo (10), txnorder_wake, multidb-{1s,2s}-0-1 (3 each),
  acl_recheck (2), aclkeys_wake.
- **feature batteries + Tcl + client-kill** (second run): **150 ok, 0 FAIL** — feature-split-0/1
  (34 each) and feature-armed-0/1 (35 each), which run the `blocking`, `blockmulti`, `multi_exec`,
  `stream`, `streamgroups`, `pubsub` … batteries on split/fused/fused+read-local boots; `redis_tcl`
  (both modes: covers unit/type/list, list-2/3, stream, stream-cgroups, multi, pubsub); climonfix
  (7); clientcompat-disconnect; clientcompat-multi-tracking.
- **new blockwake-live rows**: **8 ok, 0 FAIL** (cancel + strand × 4 mode/engine) on POST.
- **`tests/differ_gate.sh`** standard seeds, both engines: uring `rc=0` (375 rows, 0 diffs,
  incl. `differ blocking` atomic 0/1 seeds 7/19/20); epoll 461 rows, 0 FAIL, 0 diffs.
- **`python3 tests/gates_test.py`**: OK. **`tests/gateplan.py --self-test`**: 12 OK (with the new
  job).
- **`make all`** + every `job_production_units` target: built (production_units job ok);
  **`make -q all`**: FRESH at HEAD.

### NOT RUN / NOT REPRODUCED

- **F6c / F7 / F8 live deterministic PRE-failing rows.** All three fixes are shipped and correct by
  construction (Dekker / publish-then-recheck, identical to the sanctioned credit doorbell). Their
  *live* windows did not reproduce from a client in the reachable geometries: F6c's probe→add gap is
  microseconds and the cross-owner committer's data-apply is serialized with the owner's
  registration; F7's lost wake is the sweep→`arm_blocked` transition (the `f7` harness peaked at
  3.5 ms over 400 swept `SCRIPT-APPLY-DEFER` trials); F8's refused resume is **re-polled** in
  `flush_ready` (the probe woke in ~0.5 ms on both arms even with a commit-held, saturated window),
  so no 50 ms park is observed — the thread busy-retries rather than parking. The fixes make the
  thread a doorbell/dirty waiter so that *when* it does park it is rung; this is the exact mechanism
  the passing `atomwake` rows validate. The BGSAVE-cut-barrier variant of F8 was not set up.
  `tests/blockwake.py f8`/`f7` ship as harnesses, not gate rows (a row that cannot fail on PRE
  would be a weak test).
- **Throughput / ABBA / full iteration / NIC**: maintainer's, per the division of labour.
- **The maintainer sets `EXPECT_QUICK`/`EXPECT_FULL` (+8/+8) and adds the 8 labels to the ledger
  fixture** before a counted gate run.
