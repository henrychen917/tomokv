# Wave 16 release candidate

## wave16 integration

This lane integrates the three wake-fix lanes found by today's bounded-queue audit
(`round5-read/bounded-queue-wake-audit.md`), plus the tailgen attainment tool, onto the published
wave 15.

- **Base:** `8be4f68323` (origin/cpp, wave 15; EXPECT 1177/1194).
- **Branch:** `cx-wave16`. Nothing was pushed.
- **CPUs and ports:** builds, censuses, correctness servers and the oracle ran on CPUs 0-31 and
  64-111 (with `make -j48`) while cx-parkwake was still proving on 32-63, and on 0-111 after it
  finished (from 21:26). Ports 24000-24099.
- **Locale:** `LC_ALL=C` on every boot.
- **Scope:** no throughput claim. Benchmarks, ABBA, NIC cells and the full iteration remain the
  maintainer's. `EXPECT_QUICK`, `EXPECT_FULL` and `tests/fixtures/nullrefresh-ledger-labels.json`
  are untouched.

### Merges (requested order, `--no-ff`, one merge commit each)

| Merge commit | Lane head | Conflicts and resolution |
|---|---|---|
| `9e57a8eaa8` | cx-blockwake `dee669dc1d` | Textually clean. `reorder.cc` was regenerated with `tests/r7shadow_sync.py --write`. The lane's hand-edited R7 copy of the F7 re-check carried a shortened comment, so the R7 parity check reported the envelope stale. The generated text differs in that comment only. |
| `2e4a8bc37e` | cx-parkwake `52eb30b951`: its head at merge time; production code final since `2646077e16`, later commits are tests and harness | `io_loop.h` park branches, the `ex_loop.h` EX park, the `server.h` tail and `gate.sh` take the union of both lanes (see the composition table). The db0 `xshard.o` pin was set provisionally. `reorder.cc` was regenerated. |
| `fccaf006dd` | cx-iowake `f486cae5c8` | Four Makefile pin blocks: main, genthread, rl2s and reorder in both namespaces. parkwake and iowake had each re-derived them from `8be4f68323`, so the merge took provisional additive values. The F5 line merged textually into `io_loop.h` and its R7 copy, and the generator confirms parity. |
| `ee365dd2ad` | cx-tailattain `ec259ee7b5` | Clean (`tools/tailgen` only). |
| `4d6891a3df` | cx-parkwake `66804eaa0f` (its final head, after the lane finished) | Clean. Documentation only: `MEASURE-REQUEST-parkwake.md` and `docs/parkwake/proof`. src/ and the Makefile are unchanged since `2646077e16`, so the composition, the budgets, the census and the arms carry over. |

**Integration commits after the merges:**
- `5c2edab959`: collects the blockwake rows.
- `0d7d5e76e6`: re-derives the inline budgets (the last production commit; POST is built from it).
- This report and its proof summaries.

Every lane's witnesses, tools, receipts and gate rows are kept.

### Integration finding: the blockwake rows were never collected

- **What was missing.** blockwake registered `job_blockwake_live` in `plan_jobs` (four jobs, two rows
  each), and its commit says the rows are "collected before the quick-tier exit". But no
  `collect_job` line reached the branch.
- **Why the lane did not see it.** A partial `GATE_ONLY_JOBS` run collects every selected job, so
  the lane's receipts were green.
- **The effect.** A complete gate would have run the four jobs and then never counted them, so the
  declared +8/+8 would not have materialized.
- **The fix (`5c2edab959`).** The jobs are collected beside the atomwake rows they were modelled
  on, before the quick-tier exit. The planned and collected inventories now agree: 390 collected and
  385 planned. The difference is the pre-existing helper and differ-group set, unchanged from
  `8be4f68323`. No job body or label changed.

### Semantic composition: every park re-checks the union

**The park sites.** A worker thread blocks in exactly ten places in the merged tree. Every one waits
with `kParkNetMs`: 50 ms in production, 2,000 ms in `make park-net-arm`. Those are the 4 IO-loop
waits in `io_loop.h`, their 4 generated R7 copies in `reorder.cc`, and the 2 executor waits in
`ex_loop.h`. Nothing else in the worker loops blocks:
- the `aof.cc` `submit_and_wait(1)` calls are pumped drains that wait for their own submitted CQEs;
- the remaining `Ring::kWaitTimeoutMs` users are monitor/supervisor timing and the DEBUG SLEEP
  rendezvous.

**Instantiations.**
- `run_loop<…, Fused=false>`: main.o, the 2s split IO.
- `run_loop<…, Fused=true>`: genthread.o, the 1s fused thread.
- `run_loop<…, Fused=true, SplitLocal=true>`: rl2s.o, the 2s IO with `--read-local 1`.
- `r7_run_loop<…, Fused=true>`: reorder.o, the 1s R7 envelope.
- `ExLoopT<false|true>::run`: the 2s executor, without or with read-local.

`r7_run_loop` is only instantiated with `Fused=true`, so its two split branches exist in source
only. They are regenerated from `io_loop.h` and stay byte-parallel with it.

**Conditions (the brief's union).**
- **F1 retry lane**: `MultiRetryLane` head, produced by EXEC/group/escalation/FLUSH continuations.
- **F7 blocking dirty**: an owned shard's `blocking_dirty_`, set by cross-thread pushes, cancels and
  BLMOVE hand-offs.
- **Refused frame**: a frame the global atomic window refused (`credit_wait`). It is armed by
  `script_window_resume` and, since F8, by the resumed BLMOVE in `blocking_resume_move_impl`.
- **F5 TLS send**: synchronous TLS output units still to send.
- **F3 drain ack**: an owed DatabaseIoDrain/DatabaseExDrain acknowledgement.

**Table key.** "re-check" means the value is loaded after `arm_blocked()` (a `parked_` store plus a
seq_cst fence), and a true value skips the wait. "work" means the condition makes the pass report
work, so the loop `continue`s before the sweep and the park. N/A means no producer can raise the
condition for that thread.

| # | Park site | Runs in | F1 retry lane | F7 blocking dirty | Refused frame (credit doorbell) | F5 TLS send progress | F3 drain ack |
|---|---|---|---|---|---|---|---|
| 1 | `io_loop.h:793` `epoll_pass<…,Fused>(wait_ms)` | 1s fused epoll; 2s read-local IO epoll | re-check `:779` (seq_cst head load), then `multi_retry_lane_note_pending()` | re-check `:773` (`blocking_owner_dirty_pending`, seq_cst). In the 2s read-local IO the owned-shard set is empty, so it is false | re-check `:767` (`credit_wait` and `atomic_credit_wait_arm`) | work (`flush_ready` Phase 1 `if (pump_tls) work++`) | work (`database_control_pass` returns 1 in every boundary stage; it also acks the fused executor's ExDrain) |
| 2 | `io_loop.h:801` `epoll_pass<…,false>(wait_ms)` | 2s split IO epoll | re-check `:779` | N/A: a split IO owns no shard. The producer wakes the owner EX, which re-checks at #10 | re-check `:767` | work | work |
| 3 | `io_loop.h:811` `submit_and_wait(1, wait_ms)` | 1s fused uring; 2s read-local IO uring | re-check `:779` | re-check `:773` | re-check `:767` | work | work |
| 4 | `io_loop.h:820` `submit_and_wait(1, wait_ms)` | 2s split IO uring | re-check `:779` | N/A (as #2) | re-check `:767` | work | work |
| 5 | `reorder.cc:1018` `r7_epoll_pass<…,Fused>(wait_ms)` | 1s R7 epoll | re-check `:1004` | re-check `:998` | re-check `:992` | work (`r7_flush_ready`, same line) | work (same `database_control_pass`) |
| 6 | `reorder.cc:1026` (split branch) | not instantiated | re-check `:1004` | N/A | re-check `:992` | work | work |
| 7 | `reorder.cc:1036` `submit_and_wait(1, wait_ms)` | 1s R7 uring | re-check `:1004` | re-check `:998` | re-check `:992` | work | work |
| 8 | `reorder.cc:1045` (split branch) | not instantiated | re-check `:1004` | N/A | re-check `:992` | work | work |
| 9 | `ex_loop.h:752` frozen park | 2s EX, after its FLIP/LB ExDrain ack | N/A: lanes are per IO (every producer passes `owner_io` or the IO's own id), and only `IoLoop::multi_owner_pass_entry` drains one | not re-checked, by design: after the ack the executor is a hard safe point and may not touch a shard. The coordinator wakes it unconditionally at every stage publication; the dirty flag is then served by #10's re-check or the sweep | N/A: executors hold no client frames | N/A: no connections | already acked: the frozen state is entered only after the ack (the database stages are not "frozen") |
| 10 | `ex_loop.h:777` normal park | 2s EX | N/A (as #9) | re-check `:772` | N/A | N/A | work (`flip_control_pass` returns 1 while the DatabaseExDrain ack is owed, F3, so the 2,048-pass spin never reaches the park) |

**Why "work" is enough for F5 and F3.** Neither condition has a cross-thread producer that could
lose a wake.

F5 is the IO's own synchronous output. A pass that sent a unit reports work and does not park. A
pass that sent nothing has one of two states, and each ends in a CQE that wakes the park:
- an asynchronous send is in flight (`pump_tls` returns false on `send_inflight()`): its CQE;
- the socket-userspace write would block: `arm_tls_socket_poll` gives a POLLOUT CQE or an epoll
  edge.

A TLS connection with output pending also stays in `active_` (`tls_output` blocks `done`). The
pre-park sweep's `flush_ready` therefore pumps it once more.

F3: while a database boundary is open, the IO and fused threads spin, because the control pass
returns 1. The executor spins while its ack is owed. Each stage entry is announced by
`DatabaseMap::wake_workers()`, an unconditional eventfd write per participant, after the stage
store.

**F8 survives the pre-park reset.** The IO clears `credit_wait` just before its sweep, at
`io_loop.h:742`. A blocked client whose resume the window refused is still recomputed:
- it still has its blocking op in flight, so it is not `done` and stays in `active_`;
- the sweep's `flush_ready` re-runs `blocking_resume_move_impl`;
- that sets `credit_wait` again if `!atomic_can_admit`, so the doorbell is armed at the park.

**One memory-ordering discipline.** Every re-check is the same publish-then-recheck Dekker pair as
`ReadyMask::set` with `wake_if_parked`, and as the credit doorbell (`bbd7eb4880`):
- **Waiter:** `parked_.store`, then `atomic_thread_fence(seq_cst)` in `arm_blocked()`, then a
  seq_cst load of the condition.
- **Producer:** a seq_cst RMW or store of the condition, then the `parked_` load inside
  `wake_if_parked`.

| Condition | Producer publish | Waiter re-check after `arm_blocked()` |
|---|---|---|
| F1 retry lane | `multi_enqueue_node`: `head.compare_exchange_weak(…, seq_cst)`, then `wake_if_parked` | `head.load(seq_cst)` |
| F7 blocking dirty | `Shard::set_blocking_dirty`: `store(true, seq_cst)`, then `wake_if_parked` | `has_blocking_waiters()` and `blocking_dirty_pending()`, both seq_cst loads |
| Refused frame | retirement: `atomic_credits_.retire()` (seq_cst RMW), then `atomic_credit_waiters_.load(seq_cst)`, `fetch_and`, `wake_if_parked` | `atomic_credit_waiters_.fetch_or(bit, seq_cst)`, then `atomic_can_admit()` (seq_cst loads) |

F6c's registration probe/add uses the same rule: add (seq_cst), fence, reprobe, against the
committer's `blocking_publish_fence()`.

**Merge-specific composition.** No architecture or algorithm change was needed. The conflicts
composed as a union; no condition replaced another.
- The fused IO branches park only when the credit doorbell, the F7 dirty re-check and the F1 lane
  re-check are all false, and `any_fused_inbound()` is false too. Each is computed after
  `arm_blocked()`.
- parkwake's F11 `database_work.park()/resume()` bracket stays tight around the wait itself, also
  in the EX park that F7 now gates.
- F12's notice-retry service stays counted as work in both executor passes and both sweeps,
  including the regenerated R7 `r7_fused_pass_impl`/`r7_sweep`.
- iowake's F5 line sits in the TLS branch of `flush_ready`/`r7_flush_ready` and is independent of
  the park predicates.

### Item 4 (optional): DEBUG LOADAOF and an open large AOF record. Not done; more than one check

The rewrite mark's existing check is `pending_chunks() || stream_owner_.large_token()`
(`aof.cc:1816`). It could be added to the writer-thread branch of `prepare_debug_loadaof` in about
three lines. That is only part of the fix:
- **The off-writer branch** (`AofManager::wait_until_drained`, every other IO thread) sees only the
  atomic chunk count. `stream_owner_` is writer-private, so this branch needs a new atomic mirror of
  the large-record state.
- **The lost-acknowledged-write case** (iowake's 200k-field HSET) happens when the owner's large
  write has not yet opened its record at prepare time. Closing it needs the reload ordered after
  in-flight owner work, which is a protocol change for the owner.

The check alone would fix only a LOADAOF issued on the writer's own IO thread, so it was left out,
as the brief asks. The finding stays as iowake reported it (DEBUG-only; Redis serializes DEBUG
LOADAOF with every command).

### Inline budgets for the merged tree (`0d7d5e76e6`)

The lanes re-derived their `large-unit-insns` pins against `8be4f68323` independently. The merged
sources grow 24 pinned units, 12 per namespace. Two of them no lane pinned, both from blockwake's
edits:
- `t_server.o`, +71/+73 (the DEBUG BLOCKING-REGISTER-DEFER handler);
- src `xshard.o`, +239.

`tools/wave16_budgets.py` (compile-only; parkwake's method with wave16 paths) works in three steps:
1. **`initial`** measures each unit's IPA size, PRE and merged.
2. **`select`** scans ±24 in steps of 8 around *PRE pin + growth* and keeps the value with the
   fewest bodies that differ from PRE.
3. **`refine`** handles eight units whose select value still changed an unedited hot body
   (`parse_and_dispatch`, `flush_ready<false,..>`, `FlatStore::*`). Over a ±96 scan in steps of 4,
   it ranks by unintended hot bodies first, then changed bodies, then distance from the compensated
   value.

Receipts are in `docs/wave16/budgets/{initial,selected,refined}.json`.

| Unit | PRE pin | IPA unit, PRE -> merged | blockwake pin | parkwake pin | iowake pin | wave16 pin | rule |
|---|---|---|---|---|---|---|---|
| `db0/src/persist/aof.o` | 40597 | 33295 -> 33348 (+53) | = | = | 40650 | **40650** | select |
| `src/persist/aof.o` | 38653 | 33366 -> 33419 (+53) | = | = | 38714 | **38714** | select |
| `db0/src/cmd/climon.o` | 29422 | 25968 -> 26021 (+53) | = | 29459 | = | **29459** | select |
| `src/cmd/climon.o` | 28847 | 26013 -> 26066 (+53) | = | 28900 | = | **28900** | select |
| `db0/src/core/fliplisten.o` | 48705 | 39841 -> 39901 (+60) | = | 48789 | = | **48797** | refine |
| `src/core/fliplisten.o` | 48951 | 39981 -> 40041 (+60) | = | 49003 | = | **49063** | refine |
| `db0/src/core/genthread.o` | 135506 | 113423 -> 113815 (+392) | = | 135778 | 135538 | **135922** | select |
| `src/core/genthread.o` | 134842 | 114221 -> 114721 (+500) | = | 135198 | 134874 | **135382** | refine |
| `db0/src/cmd/latency_tracking.o` | 10020 | 17690 -> 17830 (+140) | = | 10160 | = | **10160** | select |
| `src/cmd/latency_tracking.o` | 10013 | 17755 -> 17895 (+140) | = | 10153 | = | **10153** | select |
| `db0/src/main.o` | 150687 | 107589 -> 107832 (+243) | = | 150916 | 150695 | **150834** | refine |
| `src/main.o` | 152477 | 108341 -> 108718 (+377) | = | 152824 | 152485 | **152850** | refine |
| `db0/src/cmd/multidb.o` | 10032 | 5167 -> 5266 (+99) | = | 10125 | = | **10131** | select |
| `src/cmd/multidb.o` | 10025 | 7108 -> 7220 (+112) | = | 10131 | = | **10137** | select |
| `db0/src/core/reorder.o` | 153552 | 125921 -> 126379 (+458) | = | 153850 | 153584 | **153986** | select |
| `src/core/reorder.o` | 152568 | 126850 -> 127416 (+566) | = | 152982 | 152600 | **153118** | select |
| `db0/src/core/rl2s.o` | 169904 | 121906 -> 122327 (+421) | = | = | 169928 | **170325** | refine |
| `src/core/rl2s.o` | 168119 | 122841 -> 123390 (+549) | = | 168503 | 168151 | **168640** | refine |
| `db0/src/snapshot/snapshot.o` | 16184 | 13635 -> 13766 (+131) | = | = | 16339 | **16339** | select |
| `src/snapshot/snapshot.o` | 16744 | 13916 -> 14047 (+131) | = | = | 16899 | **16899** | select |
| `db0/src/cmd/t_server.o` | 34277 | 28444 -> 28515 (+71) | = | = | = | **34348** | select |
| `src/cmd/t_server.o` | 34101 | 28726 -> 28799 (+73) | = | = | = | **34174** | select |
| `db0/src/cmd/xshard.o` | 171751 | 136675 -> 136920 (+245) | 171932 | 171823 | = | **172012** | select |
| `src/cmd/xshard.o` | 168287 | 136981 -> 137220 (+239) | = | 168328 | = | **168538** | refine |

`=` means the lane kept the PRE pin. Before `refine`, the linked image had 14 unintended hot changed
bodies. After it, the normal namespace has none left in `parse_and_dispatch` or `flush_ready<false,..>`.

### Command-scope instruction counts: equal to the 8be4f68323 receipts

`tools/wave16_counts.py` re-traces the merged objects with the lanes' own fixtures, tracer and
accounting. Each kind is compared with the committed `8be4f68323` receipt of the lane that owns the
fixture. Every row must be identical, in total and per function, including atomic-1 MSET.

| Census (fixture) | PRE receipt | Rows | Identical | Changed rows |
|---|---|---|---|---|
| ordinary (`tests/blockfix4_scope.cc`, lua) | `docs/parkwake/counts/pre-ordinary` | 80 | 80 | 0 |
| atomfix6 (`tests/txnorder_command_scope.cc`, complete) | `docs/parkwake/counts/pre-atomfix6` | 80 | 80 | 0 |
| parser (`tests/wave14_parser_scope.cc`, lua) | `docs/parkwake/counts/pre-parser` | 36 | 36 | 0 |
| wave11 (`tests/wave11_scope.cc`, complete) | `docs/iowake/counts/PRE` | 80 | 80 | 0 |

**Coverage.** The 80-row kinds cover GET, SET, INCR, MGET and MSET × 2s/1s × batch 1/32 ×
atomic 0/1 × normal/db0. The parser kind covers PARSE-GET/SET/INCR × 1s (read-local 0/1) and 2s ×
batch 1/32, at atomic 1.

**The parser fixture.** The census uses blockwake's fixture, which pins the topology to CPUs 0-7.
parkwake's copy declares CPUs 48-55, outside this lane's CPUs. Both lanes' PRE parser receipts are
identical in all 36 rows, totals and functions, so the CPU ids do not enter the counts.

Ordinary census rows (instructions per batch; PRE = POST in every cell):

| Command | normal 2s b1 a0/a1 | normal 2s b32 a0/a1 | normal 1s b1 a0/a1 | normal 1s b32 a0/a1 | db0 2s b1 a0/a1 | db0 2s b32 a0/a1 | db0 1s b1 a0/a1 | db0 1s b32 a0/a1 |
|---|---|---|---|---|---|---|---|---|
| GET | 1,555 / 1,555 | 18,295 / 18,295 | 935 / 935 | 18,450 / 18,450 | 1,015 / 1,015 | 17,011 / 17,011 | 782 / 782 | 17,553 / 17,553 |
| SET | 1,642 / 1,642 | 21,079 / 21,079 | 1,022 / 1,022 | 21,234 / 21,234 | 1,124 / 1,124 | 20,499 / 20,499 | 891 / 891 | 21,041 / 21,041 |
| INCR | 2,096 / 2,096 | 36,136 / 36,136 | 1,476 / 1,476 | 36,291 / 36,291 | 1,472 / 1,472 | 32,164 / 32,164 | 1,239 / 1,239 | 32,706 / 32,706 |
| MGET | 10,129 / 10,154 | 322,950 / 323,750 | 10,129 / 10,154 | 322,950 / 323,750 | 9,973 / 9,993 | 318,020 / 318,660 | 9,973 / 9,993 | 318,020 / 318,660 |
| MSET | 10,353 / 16,310 | 331,141 / 940,134 | 10,535 / 16,642 | 336,965 / 950,758 | 10,497 / 15,627 | 335,749 / 874,134 | 10,679 / 15,965 | 341,573 / 884,950 |

The census ran on the final objects before `info_stats.o` was recompiled to stamp the clean commit
id. That object holds the INFO git strings and sits in no counted scope.

### Changed hot bodies (`tools/wave16_identity.py`, `docs/wave16/identity`)

The merged POST is compared group by group with the headline PRE, using the gate's strict
normalizer and parkwake's hot selection, with its intended pattern widened to all three lanes'
edits. Of 11,282 linked groups, 450 differ from PRE: 165 hot and 285 cold.

| Hot body (normal / db0 groups) | Why it changed |
|---|---|
| `IoLoop::run_loop<..>` 24 / 24 | Park boundary: the union re-check (F1 lane, F7 dirty, credit) and F11's park/resume bracket. `idle_timeout_ms()` reads `kParkNetMs`. |
| `IoLoop::flush_ready<HasTls=true,..>` 18 / 18, `r7_flush_ready<true,..>` 8 / 8 | F5: `if (pump_tls) work++`, in the TLS branch only. Every `HasTls=false` `flush_ready` is PRE-identical. |
| `ExLoopT<false\|true>::run` 2 / 2 | EX park (F7 re-check, F11 bracket, `kParkNetMs`), F12's pass call and F3 through the control pass. |
| `ExLoopT<..>::sweep` 3 / 3, `r7_sweep` 2 / 2, `fused_pass_impl` 2 / 2, `r7_fused_pass_impl` 2 / 2 | F12: one predicted-false `notify_retries_pending()` test per pass, which serves refused completion notices. |
| `ExLoopT<..>::execute`, `execute_latency`, `execute_timed`, 5 / 5 each | F2: the `ScatterFinish::Retry` arm parks in `atomic_deferred_` (cold arm). |
| `cmd_xshard_only_impl<false\|true>` 2 / 2 | Data displacement only (identical instructions). |
| **Unintended:** `parse_and_dispatch<..>` 0 / 8 (db0 `<false,32,false>`, `<false,32,true>`, `<true,0,false>`, `<true,32,false>`, `<true,32,true>`, with their `.isra`/`.cold` clones) | Compiler spillover in db0 `rl2s.o` and `fliplisten.o`. It changes at every scanned pin, the PRE pin included. parkwake's own image changed 4 normal and 6 db0 `parse_and_dispatch` groups (its identity receipt); this image changes 0 normal and 8 db0. |
| **Unintended:** `FlatStore::scan<xshard_execute lambda>` 1 / 0 | Spillover in src `xshard.o`, at every scanned pin. parkwake had it too. |

**Against the brief's expectation** (only the F5 TLS line plus cold park-boundary code), two
parkwake items also sit in hot functions:
- the per-pass F12 test;
- execute's F2 Retry arm.

Both are parkwake's intended edits, and neither enters a counted command scope, so all 276 census
rows are unchanged. The cold changes are the lanes' intended bodies plus inventoried spillover:
`docs/wave16/identity/changed-bodies.md`.

### Row delta

All 35 new rows are collected before the quick-tier exit. Collection lines in `tests/gate.sh`:
blockwake at 7090, parkwake from 7098, iowake at 7426; the quick exit is at 7476.

| Lane | Jobs | Rows | DQ | DF |
|---|---|---|---|---|
| blockwake | `blockwake-live-{2s,1s}-{uring,epoll}` (cancel and strand rows each) | 8 | +8 | +8 |
| parkwake | `parkwake-{retry,control,epoch,slotless,watchdog}-{2s,1s}-{uring,epoll}`, `parkwake-script-2s-{uring,epoll}`, `parkwake_unit` | 23 | +23 | +23 |
| iowake | `iowake-{tls,aof,bgsave,loadaof}` | 4 | +4 | +4 |
| tailattain, integration | none | 0 | 0 | 0 |
| **Total** | 31 jobs | **35** | **+35** | **+35** |

For the maintainer:
- `EXPECT_QUICK` 1177 → **1212** and `EXPECT_FULL` 1194 → **1229**.
- The ledger-label fixture needs the 35 labels:
  - blockwake: `blockwake cancel: no element lost to a cancelled waiter (<mode>, <engine>)` and
    `blockwake strand: a registering front waiter does not strand its followers (<mode>, <engine>)`;
  - parkwake: `parkwake_label()` in gate.sh prints each label, plus the `parkwake_unit` row;
  - iowake: the four `iowake F…` labels in `job_iowake`.
- No integration row was added.

### Arms

| Arm | Path | SHA-256 | `.text` |
|---|---|---|---|
| PRE (`8be4f68323`, reused) | `/home/user/Projects/bench-bins/tomokv-headline-8be4f68323` | `d8fa44bc578b463b27892e36cba70df9be55858ed91a3b8ad64f6e23ba838385` | 9,230,039 at 0x2dcd0 |
| POST (`0d7d5e76e6`, clean) | `/home/user/Projects/bins/wave16-post-3f058fa1` | `3f058fa120523b754fa984f118a93ae33c6007008d60ff58b8ba3814dbf19d05` | 9,251,911 at 0x2dcd0 (+21,872) |
| PAD-A | `/home/user/Projects/bins/wave16-pad-e3f67993` | `e3f6799348458167a2ff76f17e3feb7c944c41739f001a0bb0e76f77e61c679a` | 9,251,911 at 0x2dcd0 |

**PAD-A is kind A, a behaviour twin** (`tools/wave16_pad.py`, the parkwake/mset8fix method). The PRE
objects of `8be4f68323` are linked with one padding object. `.text` then starts where POST's does
and has POST's exact size, while PRE's behaviour is kept. The PRE objects are a clean rebuild in
`build/wave16/pre-source`. Their `.text` is byte-identical to the headline PRE's, and also to
blockwake's, parkwake's and iowake's PRE arms. It is a size control only: function placement and
data keep PRE's layout. Receipt: `docs/wave16/arms.json`.

The diagnostic arm `build/park-net/tomokv` (`make park-net-arm`, `-DTOMO_PARK_NET_MS=2000`, test-only,
SHA-256 `8af37b4e6083312644961e3e270c2c8d7d753150a3e6b4b25fe2216f3f532be3`) is not in `bins`.

### S1 candidate: deleted-stream group waiter served from a renamed stream (not changed; rare residual)

**What was seen.** parkwake's broad run on its POST recorded one wrong reply in
`wave15-block-2s-uring-0-16`, at iteration 26 of 200
(`docs/parkwake/proof/wave15-deleted-stream-fail.json`):
- `XREADGROUP … BLOCK 0` waits on `boundary`;
- then a pipelined `DEL boundary other-owner` (`--atomic 1`), `RENAME replacement boundary`,
  `XADD boundary 1-0`;
- the waiter returned the renamed group's `1-0` instead of NOGROUP. Redis fails it right after
  the DEL, before the RENAME runs.

parkwake did not reproduce it in 65,000+ further iterations (PRE and POST).

**Mechanism (code read; no lane changed this code).**
- A plain mutation on a shard that holds waiters and atomic records forces a sweep before it runs
  (`blocking_plain_mutation_published`, `ex_execute.inc:238`). This is why the XGROUP CREATE arm
  is safe.
- An atomic DEL only marks the waiter's shard dirty and wakes the owner (`blocking_atomic_published`).
  It does so before the op's `Done`, so the flag is visible before the pipelined RENAME is dispatched.
- The owner sweeps that flag at one of these points:
  - in MVCC cleanup (`xshard_cleanup_shard_at`, as soon as the read floor passes the DEL's record:
    normally the same pass);
  - in its idle `sweep()`;
  - on the 10 ms blocking beat;
  - before parking (F7).
- An atomic RENAME participant has no pre-execute sweep (`blocking_scatter_mutation_published` skips
  atomic groups). If cleanup is held back (read floor, cleanup budget) and the owner stays busy, the
  RENAME installs the replacement group before the sweep. The XADD's forced sweep then sees group
  `g` alive and serves the waiter.

**Witness attempts (scratch harness, CPUs 56-63, the failing leg's geometry: 2s, uring, atomic 1,
16 databases, read-local 0).** The RENAME arm alone:
- headline PRE, no load: 300 iterations, 0 wrong replies;
- headline PRE with three clients keeping the waiter's owner busy on its other shards: 1,000
  iterations, 0 wrong replies;
- the 2 s park-net arm of the merged tree, no load and owner load: 2,000 iterations, 0 wrong
  replies.

The window is an ordering race inside the owner's passes, not a missed wake, so the 2 s net does not
widen it. No deterministic witness on PRE was obtained in the time available.

**Why no change was made.** The instruction allowed a change only with a PRE witness and a small fix.
- An airtight fix needs a dirty check per task, before an atomic participant runs on a shard with
  waiters. Every scatter task would pay a load and a branch, which moves the counted MGET/MSET
  scopes (the zero-cost requirement).
- A census-neutral per-pass sweep ahead of `drain_tasks()` (parkwake's proposal) is only airtight if
  the drain executes a task snapshot taken before the check. That reworks the drain, so it is not
  small.
- Sweeping inside `blocking_atomic_published` when the committer owns the waiter's shard is cold and
  census-neutral, but it covers only same-owner commits.

**Proposal for the owner.** The per-pass pre-drain sweep (a predicted-false
`blocking_waiters() != 0` test per pass), with the drain bound to a snapshot taken before the check,
plus the same-owner direct sweep at commit. Until then this is a documented rare residual (S1
class: wrong reply). The `wave15-block-*` rows ran 10× in this lane (see Proof).

### Proof

All gate runs went through `tests/gate.sh iteration` with `GATE_ONLY_JOBS` and
`GATE_PROOF_NO_RATES=1`. These are PARTIAL ledgers, not receipts, with no EXPECT tally, ABBA or NIC.
- **CPUs and ports:** CPUs 0-31 and 64-111 until cx-parkwake finished, 0-111 after; ports
  24000-24099.
- **Binaries:** POST is `build/tomokv`, byte-identical to `bins/wave16-post-3f058fa1`. The
  diagnostic arm is `build/park-net/tomokv`.
- **Ledgers:** `docs/wave16/proof/`.

**Build.**
- `make all`, all 61 `job_production_units` targets, both mdbqsbr twin arms, blockfix-cost,
  blockfix2, `build/parkwake-unit`, `build/parkwake-slowsync.so`, `build/atomwake-unit` and
  `park-net-arm`: rc 0, 55 warnings (as PRE).
- `make -q` on every one of them: fresh.

| Proof | Arm | Selection / environment | Result |
|---|---|---|---|
| **All 35 new rows** (31 jobs), 2 s park net (task 3) | diag | blockwake ×4, parkwake ×23 (`_unit` included), iowake ×4; one gate run | **35 / 35 ok** |
| same, second pass | diag | single slot, 2 load CPUs | 34 ok, 1 vacuous: `blockwake strand (1s, epoll)` opened its registering window in 0 of 9 trials. Every reply was correct (W1 `a`, W2 `b`, W3 `c`, LLEN 0, no stranded waiter). |
| `blockwake-live-1s-epoll` re-run ×3, same geometry | diag | | **6 / 6 ok** |
| `txnorder_fifo_live`, at412 T6/T9, atomwake ×4 + unit | diag | the first diag run plus 2 diag-loop runs (3 runs) | **FIFO 3 / 3, T6 3 / 3, T9 3 / 3, atomwake unit 3 / 3, atomwake live rows 11 / 12** (the one miss is the contention-tail leg in the first run, see below) |
| `atomwake-live-2s-uring` ×5 | diag | | **5 / 5 ok** (with the loops: 7 runs of the 2s-uring row on the 2 s arm, 6 pass) |
| Every job the three lanes list as touched, plus the 35 new rows | POST | 256 jobs: parkwake's broad set, blockwake's and iowake's main batches, `wave15-block-*`. `eoffix_aof` excluded (NOT RUN) | **925 ok, 2 FAIL.** Both FAILs are `redis_tcl`, a harness port collision (note below); re-run alone it passes both modes. The run includes all 35 new rows (35 / 35 ok), `wave15-block-*` 12 / 12, FIFO live, T6, T9, atomwake ×4 + unit, the blockfix, txnorder, multidb, FLIP, LB, AOF, snapshot, TLS and respresume families, and the four feature batteries. |
| `redis_tcl`, checked-in manifest, 2s and 1s | POST | alone, single slot | **2 / 2 ok** (second isolated run; see the note below) |
| iowake engine batch | POST | `GATE_NET_IO=epoll GATE_PROOF_NET_IO=epoll`, 44 env-engine jobs | **148 ok, 0 FAIL** |
| iowake fused batch: tls, aof-epoll/uring, snapshot-epoll/uring, debug-0/1, aof_frame | POST | `GATE_TXN_FUSED=1` | **195 ok, 0 FAIL** |
| iowake fused epoll batch: tls, debug-0/1, aof_frame, aoforder | POST | `GATE_TXN_FUSED=1`, epoll | **58 ok, 0 FAIL** |
| `tests/differ_gate.sh`, standard seeds 7 19 20 21 23 | POST | uring, 6:2 on 24-31, load 104-111 | **pass=475 fail=0** (17m44s) |
| `tests/differ_gate.sh`, standard seeds 7 19 20 22 23 | POST | epoll | **pass=475 fail=0** (17m37s) |
| `python3 tests/gates_test.py` | | CPUs 8-15, 80-95 | **79 tests OK** (200.6 s) |
| `tests/gateplan.py --self-test` | | | **12 OK** |
| `txnorder_fifo_live` ×10, in its wide slot | POST | one gate run per loop: 8 in one lane, 2 in parallel lanes on other CCXs | **10 / 10 ok** (plus the P1 run: 11 / 11) |
| at412 T6 + T9 ×10 | POST | 8 in one lane, 2 in parallel lanes | **T6 10 / 10, T9 10 / 10 ok** (plus P1: 11 / 11 each) |
| `wave15-block-*` ×10, the coordinator's addition (12 rows of 200 repetitions per loop) | POST | | **10 / 10 loops, 120 / 120 rows ok** (24,000 deleted-stream iterations, 0 wrong replies) |
| `atomwake-live-2s-uring`, interleaved A/B ×5 | POST / PRE | | **POST 5 / 5, PRE 5 / 5** (60 legs each, 0 failures) |

**Notes on the red runs, none attributed to the merged code.**
- **The first `redis_tcl` in the broad run** failed both modes before any test ran: "Can't find a non
  busy port in the 24004-24004 range". Two jobs overlapped on slot 1, and `netfix2-exclusive` held
  24004 as its `--tls-port` (its PORT+1) while `redis_tcl` needed it as the Tcl controller port.
  This is a harness port collision.
- **The first isolated `redis_tcl`** passed 1s. 2s failed one test more than 1s, "CONFIG SET rollback
  on apply error". Redis's `find_available_port` also binds port+10000 (34052 here). That port is
  in the ephemeral range, which other lanes' clients were drawing from. The five other Tcl failures
  are present in both modes, and the manifest accounts for them (unknown DEBUG subcommand,
  `list-compress-depth`, `aof-use-rdb-preamble no`). The second isolated run passed both modes.
- **The loop lanes**: each main FIFO and T6/T9 loop was stopped by PID after its 8th run, and runs
  9-10 ran on two parallel lanes. The stopped 9th attempt was terminated at its start (`release`
  prerequisite only), torn down by the gate's own cleanup, and is not counted.
- **The atomwake diag leg**: one leg of 12 in the first diag run (`rl0-db16-rep2`) had one probe
  batch of 33.4 ms (its first replies at 28.6 ms) against the 20 ms bound.
  - A missed wake on the 2 s arm costs 2,000 ms, so this is a credit-contention tail. The test notes
    such tails ("24 ms, 1 of 288 POST legs").
  - It ran on a box shared with five other lanes.
  - The row passed in every later diag run and in all 10 POST/PRE A/B runs.

### NOT RUN

- **Maintainer-reserved:** benchmarks, merit or throughput cells, ABBA, NIC cells and the full
  `iteration`/`push` gate. No EXPECT tally or receipt was produced.
- **`eoffix_aof`:** a private lane proof that needs `EOFFIX_AOF_DIRECTORY` native arms from eoffix.
  Its subject (EOF QSBR) is untouched by these lanes.
- **Redis Tcl `unit/tls` and the AOF integration units:** the harness has no TLS mode, and the AOF
  units are external-server-skipped, as iowake reported. TLS is covered by the gate's TLS rows and
  `iowake-tls`.
- **Item 4 (DEBUG LOADAOF large-record wait):** not implemented; it needs more than the existing
  check (see above).
- **S1 deleted-stream residual:** no code change; no PRE witness (see above).
- **PRE census:** not re-traced. The comparison uses the lanes' committed `8be4f68323` receipts.
  All four PRE arms and the headline share one `.text` (`7fd66b3a…`).
- **Parkwake's live F3, automatic FLIP and LB PlanReady witnesses:** not reachable on this box, as
  parkwake reported. They are covered by its units and the flip/lb jobs in the broad run.
