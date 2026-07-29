# Plan to a stable TomoKV/THredis release

Written 2026-07-29. Goal, in the owner's words: *"a true stable none overwritten with redundant
stuff version"* — as bug-free and correct as possible while retaining the gains.

Everything below is ordered. Each item states what "done" means, so nothing is graded on a build
being clean.

---

## 0. State of the branch

`2s-numa-stable-dev`, all pushed:

| commit | what | evidence |
|---|---|---|
| `62f03ebcc` | 3 preflight harness defects (leak / shared-name reap / suites that never ran) | verified by inspection + both arg forms exercised |
| `d74df8895` | LB-1: flip controller UAF — main walked another io thread's client list | **KEEP** — `correctness_suite` 15/0 post-merge. ASAN discrimination: see §2 |
| `348f6dc23` | key-LB hot-key veto at per-bucket resolution + `tomokv-mset-move` restored (default off) | see §2 |
| `5b3b4581a` | active expiry never ran on the sharded keyspace (#42) | **KEEP** — re-validated post-merge, both regimes, both arms; 15/0; tax −1.42% worst |
| `0a2ef6c6f` | `flip_updown` exit status was a constant | both exit codes observed |

### The "pushed without a post-merge green" deviation — status 2026-07-29

The three merges were re-run post-merge against the problem each was built to solve. **Nothing was
reverted; no merge regressed.** What the pass actually found was that two of the three *tests* were
incapable of returning a verdict — which is why "it was validated pre-merge" was never worth much:

| merge | verdict | what the re-run added |
|---|---|---|
| `5b3b4581a` active expiry | **KEEP** ✅ | full 2×2 discrimination (PRE fails / POST passes, at `ex=1` and `ex=4`), 15/0, and the always-on tax priced at −1.42% worst cell |
| `d74df8895` LB-1 | **KEEP** (correctness), ASAN arm see §2 | 15/0 — and the discovery that its ASAN probe had **never once executed** past its own precondition |
| `348f6dc23` veto + mset-move | see §2 | — |

Two findings that outlast this pass: a **torn `expired_keys` counter** (§4) and the fact that the
LB-1 probe's precondition was unreadable on every build ever tested (§2). Both were found by the
sanity gate, not by a suite going red — a suite going red is exactly what neither could do.

---

## 1. BLOCKER — make the gate able to pass at all

Nothing can be certified until preflight can go green, and until 2026-07-29 it structurally could
not. Three defects are fixed (`62f03ebcc`); the remaining work is to confirm the fix and clear what
is left.

1. **Confirm the three repaired suites now execute.** Run `preflight.sh` once. `flip_updown.out`,
   `lb_skew.out`, `side_regression.out` must EXIST and contain a verdict. Before this fix they were
   graded "produced no result file" because `run_suite` (preflight.sh:85) passes the binary as env
   `TOMO_BIN` while the suites demanded `${1:?}` and died on line 1. **This single observation
   validates all three harness fixes at once.**
2. **`numcmd_check.sh` fails with exit 0 and no result file.** A suite that exits 0 and is graded
   FAIL is a harness defect, not a product defect. Diagnose before trusting any preflight verdict.
3. **`reshard_suite`: `reshard-survives` FAIL "server dead after cutovers."** The *ordering* checks
   pass cleanly (0 violations / 34831 and 0 / 3000). Establish whether the death is the product or
   another reaper. Given the leak class just fixed, re-test before investigating the server.
4. **`feature_sweep` exits 1; `controller_sweep` produces no result file.** Same triage: harness or
   product?
5. **`knob_matrix`: io-uring knobs "DID NOT BOOT"** — RESOLVED 2026-07-29, and not the way this
   item proposed. The knobs no longer exist (section 5): the backend is a compile-time choice. The
   cells are now `reject()` assertions that the retired names are refused, which is stronger than
   deleting them — deleting would leave nothing proving the knobs actually went away, and this tree
   has been bitten by a "retired" knob whose field merely fell to 0 by omission while every suite
   stayed green.
6. **Three suites still reap the shared name** — `numa2_validate.sh`, `shared_refcount_race.sh`,
   `expiry_clock_ab.sh`. They can still kill other sessions' servers. `shared_refcount_race.sh` has
   no `BIN`-style variable, so it needs a hand-written fix rather than the mechanical one.

**Done means:** a preflight run in which every suite either PASSes or FAILs *on its own merits*, with
no "produced no result file" and no leaked server afterwards (`ss -lptn | grep 79` empty).

### 1a. Findings against the six items above (2026-07-29, `b3f6839e4`…`f9d37dc00`)

Every item above was diagnosed from the code and the 2026-07-28 artefacts. **Six of the failures
listed in that NO-GO report were faults in the test rig, not in the build.** Corrections to the list
as written:

- **Item 1 could not have been satisfied as stated.** `side_regression.sh` was never wired into
  `preflight.sh` — `grep -c side_regression tools/preflight/preflight.sh` returned **0**. `62f03ebcc`
  repaired its `${1:?}` line, but no preflight run could produce `side_regression.out` before or
  after that fix, because nothing called it. Now wired in. Its verdict was *also* swallowed by
  `python3 … | tee` (exit status = `tee`'s = always 0) — the same constant-exit-status defect
  `0a2ef6c6f` fixed in `flip_updown`. Taken from `PIPESTATUS`.
- **`62f03ebcc`'s fix 2 was INERT under preflight**, which is the root cause item 6 half-sees.
  Eleven suites were changed to reap `pkill -9 -x "$(basename "$BIN")"`, but `preflight.sh` staged
  the binary **as `redis-server`** — so under preflight that basename expanded straight back to
  `redis-server` and preflight still SIGKILLed every other session's server. Staged as `redis-pf`
  now, so "is a FOREIGN server up" and "is MINE up" are finally different questions.
- **Item 6 is one-third stale.** `expiry_clock_ab.sh` does **not** reap the shared name; it already
  killed by its own recorded pid under a trap. Only `numa2_validate.sh` and
  `shared_refcount_race.sh` did, and both are fixed. `numa2_validate` also read its RSS series from
  `ps -C redis-server | head -1` — whichever server sorted first, possibly another session's.
- **Item 3 was a missing file, not a dead server and not a reaper.** `reshard_suite` probed liveness
  with `"$(dirname "$BIN")"/redis-cli`, and the staged binary's directory contains the server alone
  (`bins/stable/` holds exactly one file). The command did not exist, `alive` came back empty, FAIL.
  In the same run the ordering probe passed 0/3000 across 11 cutovers with 0 crash markers. Fixed by
  a fallback chain, and preflight now stages `redis-cli` beside the binary — which also repairs
  `keylb_veto.sh`, whose client had the identical unguarded spelling.
- **Item 2: `numcmd_check.sh` was never a suite.** A private A/B driver hardcoded to another agent's
  worktree and to `/tmp/numcmd_bins/…`, printing to stdout, ending on `pkill; sleep 1` so its status
  was 0 regardless. Rewritten as a suite; a probe that scores zero rows is now a FAIL, because
  silence was precisely how it passed before.
- **Item 5 is right about the uring cells and misses a fifth.** `tomokv-key-lb -1` is also a *test*
  defect: `config.c:3309` declares `[0, INT_MAX]` with `0 = OFF, N = min ops/s`; there is no `-1`
  auto. Both refusals are now asserted with `must_refuse`, which is stronger than dropping the cells.
- **Item 4, `controller_sweep`:** it aborted *before* `: > "$OUT"` on `FATAL: a memtier_benchmark is
  already running` — a load generator leaked by the suite that ran immediately before it. Graded as
  a controller failure. Every abort now writes a row naming itself; preflight refuses to start on a
  contended box and reaps its own leaked processes between suites, naming the leaker.
- **Item 4, `feature_sweep`:** two of its four FAILs are a stale-log artefact. Server logs were named
  `srv_<BOOTSEQ>_…` with `BOOTSEQ` restarting at 0 each run and opened with `>>`, so runs shared
  files — one held **14 boot banners**. `crash_scan` grepped that history, and a single assertion at
  03:57:35 on 28 Jul was re-reported as a fresh FAIL by the 04:22, 08:57 and 12:49 runs. Fixed with a
  per-run id (logs still preserved, never re-scanned). The other two, `post-alive … dead/hijacked`
  alongside `churn SUSPECT ops/sec=0`, are the signature of a contended/killed box, not a defect.
- **Bonus, and it explains a lot:** `preflight_history.tsv` recorded `GITDESC=unknown` on **every row
  ever written**, because it ran `git describe` in `$(dirname "$BIN")/..` = `/tmp`. The per-version
  ledger — the thing that is supposed to show regressions across versions at a glance — could not
  name a single version. Fixed.

**Still open after this pass (candidate PRODUCT items, not gate blockers):** `controller_sweep`'s
`1-flip SHIFT-ioward` / `SHIFT-exward` report `grow-front flips=0` / `grow-back flips=0`, and
`io_threads_live=?`. That `?` is not a parse failure — the server only logs `io_threads_live=` when a
flip *completes* (`server.c:17776`), and the token appears in **0 of 347** captured `csweep` server
logs. So no flip has ever completed under that stimulus. `flip_updown.sh` is the suite built to
answer this and has never once executed; its first real run is the evidence to judge on.

---

## 2. Validate what is already merged

Three merges are on the branch with no post-merge execution. Run each against the problem it was
built to solve, then either keep or revert. Do not re-derive; the acceptance criteria are known:

- **active expiry** (`5b3b4581a`) — **KEEP. Validated post-merge 2026-07-29.** ✅
  `tools/preflight/active_expiry_probe.sh`, traffic-free, 100k keys with a 10s TTL. The probe was
  run on BOTH arms so it is shown to discriminate, in BOTH regimes:

  | arm | ex=1 (dict) | ex=4 (FLATSTORE) |
  |---|---|---|
  | PRE `0bf21576486e` | FAIL — dbsize 100000→**100000**, `expired_keys_active=0` | FAIL — dbsize 100000→**100000**, `expired_keys_active=0` |
  | POST `2808210f9079` | PASS — dbsize 100000→**0**, `expired_keys_active=100000` | PASS — dbsize 100000→**0**, `expired_keys_active=100000` |

  The two binaries differ exactly by the fix (`nm`: PRE has no `exActiveExpireCycle`, POST does).
  `correctness_suite` on the merged binary: **15 passed, 0 failed**.
  Always-on tax, interleaved PRE/POST A/B, 2 reps × 8 cells, no-TTL workload (so the cycle takes
  its whole-db early-out and what is left is pure tax): worst cell `io7ex1 p32SET` **−1.42%**,
  every other cell within ±1%, against the 3% budget. `io7ex1` is where the tax should land and
  does — `ex=1` concentrates the per-worker cycle on one thread. Internal sanity check: `p32SET`
  io4ex4/io7ex1 = 7190302/1814430 = **3.95×** for a 4:1 worker ratio, so the harness is measuring
  the thing it claims. Raw: `$J/aexp/perf_ab.tsv`, `$J/aexp/acceptance.log`.
  **Caught by the sanity gate while doing this:** at `ex=4` the run reported `expired_keys=89886`
  alongside `expired_keys_active=100000` — the subset exceeding its own total. That is a real
  torn-counter defect; it is PRE-EXISTING and not a reason to revert. Filed in section 4.
- **hot-key veto** — three arms. A: `unbal_fine=7 unbal_grp=0 fire=0`. **B: `fire=1` — must STILL
  MIGRATE on genuine multi-bucket skew**; if B stops migrating the fix is "never move" and must be
  reverted. C (`key-lb-fine 0`): the original defect reproduces. Plus `<=3%` cost, measured against
  the PARENT build — at `fine 0` the bounds test is still compiled in, so the knob cannot price its
  own instruction.
- **mset-move** — `correctness_suite` 15/0 with the knob OFF *and* ON; ASAN churn clean; the
  `tomokv_xshard_mset_moved` gate-open counter asserted as a **delta**, never an absolute (absolute
  lets a knob-OFF run pass on the previous ON run's total).

  **STATUS 2026-07-29: RUNNER BUILT AND QUEUED, RESULT NOT YET IN.** `$J/mrg/run_item2.sh` chains
  the three stages under ONE box acquisition: `run_s2.sh` (correctness OFF/ON, veto A/B/C, churn
  delta) → `run_s2_asan.sh` → `run_s5cost.sh`. Two corrections were needed before it could be
  trusted:
  * **`run_s2.sh` never ran the churn under ASAN**, though `mset_move_churn.py`'s own docstring
    says the failure mode is "a USE-AFTER-FREE or a double free, not a wrong answer" and that the
    test must "run under ASAN to see the memory error at all". It drove the plain `-O2`
    `redis-s2`, where a UAF that happens to read intact memory is invisible — i.e. the arm that
    STABLE_PLAN calls "ASAN churn clean" did not exist. Added as `run_s2_asan.sh`, against
    `$J/mrg/asanpost/src/redis-server` (verified ASAN-instrumented, and verified to contain
    mset-move and the expiry fix), both knob arms, gate-open asserted as a delta.
  * The cost gate's `base` arm is `redis-base-pre2`, which lacks `tomokv-key-lb-fine`,
    `tomokv-mset-move` **and** `exActiveExpireCycle` — so it predates all three merges, not just
    this one. That makes the base-vs-cur number a *combined* price for the whole stack. A pass is
    therefore conservative; only a FAIL would need decomposing.
- **LB-1** (`d74df8895`) — `correctness_suite` **15 passed, 0 failed** on `redis-s3` ✅
  (`$J/mrg/s3_run.log`). The ASAN discrimination is covered below.

  **The probe could not run, and had never been able to (found 2026-07-29).**
  `lb1_uaf_probe.sh` established its grow-front precondition with
  `INFO threads | grep io_threads_live`. **That field does not exist in that section on any build
  in this tree** — `# Threads` emits `io_thread_N:clients=…` and `tomo_io_thread_N:clients=…` and
  nothing else (`server.c:13994`). So the grep matched nothing, `live0` and `live1` were both the
  empty string, `[ "$live0" = "$live1" ]` was true, and the probe printed
  `INVALID: no grow-front happened` and exited 2 — on every build, fixed or broken. It had never
  once reached `tomoGrowBackSlot`, the function it exists to test. Both arms did exactly this on
  the first run. The message also named the wrong cause: `DEBUG TOMO-MODESHIFT 7` was returning
  `OK` throughout; what failed was the *reading*, not the flip.
  **Audited the sibling suites rather than assuming** (2026-07-29): this is the same *class* as
  `flip_updown`'s bare `io=` grep (`f65813e9f`) but not the same bug — `flip_updown` matched the
  WRONG line (a `[balance] pressure … io=` notice), this matched NO line. `controller_sweep.sh` is
  the one that gets it right: `iolive()` reads `io_threads_live=` out of `$SRVLOG`, the server log,
  which is the only place the field is ever written. That is the pattern to copy, and it is what
  the fix below does. So the audit finding is narrower than first stated: two LB verdicts were
  computed from a text source that could not answer the question, and the third was already
  correct.
  Fixed by anchoring to the controller's own completion line, `GROW-FRONT complete —
  io_threads_live=N` (`server.c:17779`), which is written only when the conversion *completes* (a
  DEBUG `OK` means only that the request was accepted), plus a second guard that at least one
  `GROW-BACK` actually completed rather than merely being accepted.

**Done means:** each is green on its own acceptance, or reverted with the regression recorded.

---

## 3. Remaining merge queue

Serially, **one box acquisition each** — the previous campaign queued ~9 jobs concurrently and they
starved each other. That was an orchestration error, not a box problem.

| # | branch | acceptance | notes |
|---|---|---|---|
| 1 | cmdstats `8a24ab1b8`+2 | `cmdstat_check.sh` 18 failures → 0; `LATENCY HISTOGRAM` calls == exact count | **perf UNMEASURED** — adds per-command work on the worker hot path. If >3%, report before pushing |
| 2 | debug-reload `c8aab4059` **only** | `debug_reload.sh` 0/2 → 12/0 | EXCLUDE `cfea82654` — never compiled, never run. Known residual: FLATSTORE still panics ~1 in 3 via a resize/COPYING race |
| 3 | fpipe-lru `43bdd8972` **only** | `xshard_lookup_accounting.sh` 5/2 → 7/0 | EXCLUDE fix 2 — uncommitted, never compiled. Note LRU shows NO distortion (idempotent within a tick); only LFU and keyspace_hits are real |
| 4 | exec-nesting `c53223863` | builds + 15/0; probe if cheap | Default config: bookkeeping only, not data loss. If the probe cannot discriminate, merge on the static argument and SAY SO |
| 5 | deletions (5 commits) | 15/0 + `reshard_suite` + `flip_updown` | Large. Key-LB actuators verified unaffected (both paths already required same-node) |
| 6 | parked-removal `6b9d3a0b9` | **GATED on `flip_updown` passing** | Modifies flip actuation. Author validated only the MANUAL actuator. Resolved patch at `$J/mrg/step4_parked_removal_RESOLVED.patch`; it deletes `num_workers_alloc`, which active-expiry added folds over — auto-merge accepts both sides and the build then fails. Fix: `num_workers_alloc` → `num_workers` |
| 7 | h2-fence `e7628efc4` | rebase first (base `95872c371`, collides with the private-binary commit) | Evidence: 4/4 violations base → 0/4 fixed, 232 `fence_midbatch_ticks`. **Missing: the throughput cells (`h2_thr.py`) showing A and B still serve their NON-migrating buckets through a cutover — that is the owner's actual design claim and it currently rests on code reasoning alone.** Adds `tomokv-reshard-fence-timeout`, a new "migration did not happen" path that bumps `reshard_done_seq`, which the flip controller reads |

---

## 4. Unowned defects

Nothing is working on these.

- **LB-2** `server.hotkeys` — one process-global struct used as per-command scratch by every io
  thread. OOB read, double free, and `current_client` clobbering that indexes `argv[pos]` into a
  *different* client's argv. Dormant until `HOTKEYS START`, but the subsystem is unusable as written.
- **LB-3** `tm_flip_ctx` TOCTOU — non-atomic, and it is simultaneously the flip state machine AND
  the "is a flip in progress" gate. **The key balancer defers entirely on it** (`server.c:11475`).
  Writers: main, and any io thread via `DEBUG TOMO-MODESHIFT`.
- **LB-4** torn `tm_mig_mbox` request block — two publishers, non-atomic check-then-store.
- **`errorstats` concurrent `raxInsert`** — worker threads mutate the shared `server.errors` rax with
  no synchronisation. Structural race, not a counter race.
- **`activeSubexpiresCycle`** — hash-field TTLs, same decoy-`server.db` root cause as #42, unfixed.
- **`expired_keys` is a torn counter under multi-worker expiry** (found 2026-07-29 by the sanity
  gate while validating #42, see section 2). `server.stat_expiredkeys` is a plain `long long`
  incremented at `db.c:3085` from `deleteExpiredKeyAndPropagate`, which every worker calls. The
  race is PRE-EXISTING — that line is untouched upstream code and the worker LAZY path already
  reached it — but #42's worker cycle raised the write rate enough to make the loss measurable.
  Measured: at `ex=4`, `expired_keys=89886` while `expired_keys_active=100000` for exactly 100000
  reclaimed keys, i.e. **the subset exceeds the total and ~10.1% of increments are lost**; at
  `ex=1` (one worker, no contention) both read exactly 100000. Stat-only, no data loss.
  `expired_keys_active` is correct because it folds per-worker single-writer counters
  (`expiredKeysActiveTotal`, `server.c:13679`). Fix is the same shape: fold a per-worker counter
  rather than share one. Not fixed here — it is a counter, and this pass was validation only.
- **`fakeRingAutoTune`'s gate has never opened** — it reads `cmd->calls` for GET/SET, which never
  enter `call()`. `use_slim` has therefore never been exercised. Documented, deliberately not fixed:
  fixing it OPENS a hot-path gate for the first time and needs its own A/B.
- **Duplicate knob binding** — `tomokv-reshard-sustain-ticks` and `tomokv-key-lb-sustain` write the
  SAME field with different defaults and ranges. Aliased both ways; the wide-range name can push the
  field past the other's validator. `!= 0` gates the whole key-LB Schmitt debounce, so setting the
  reshard-looking knob to 0 silently disarms key LB's anti-thrash. Safe today only by config-table
  ordering. Fix: keep `tomokv-key-lb-sustain`, delete the other, hardwire the −1 auto behaviour.

---

## 5. io_uring — now a compile-time choice (knobs retired 2026-07-29)

**DONE: the collapse landed.** The backend is selected by the BUILD, not by config. A default
`make` is the epoll server; `make USE_URING=yes` is the io_uring server. Neither needs a flag.

What was deleted: `tomokv-io-uring`, `-recv`, `-reply-send`, `-sqpoll`, `-zc` — config entries,
`server.*` fields, and every read site. There were two gates in series on one decision (does the
code exist / is it switched on), and since all five were `IMMUTABLE_CONFIG` the second gate was
resolved at the same moment as the first — it could not enable anything the build lacked, only
disable something the operator had deliberately compiled in. The orphan FATAL that policed
sub-knob-without-master went with them: that state is now unrepresentable.

Two sub-features were retired at their shipped default of OFF rather than switched on by omission,
and their branches deleted (recoverable from git history):
- **SQPOLL.** `iouRecvEnsure`'s own comment records that it *regressed throughput and corrupted
  multi-chunk (>16K) reads*. It also spawns a spinning kernel poller per IO thread, which would
  have confounded the epoll-vs-uring comparison this split exists to enable — extra busy kernel
  threads are not io_uring's cost. Both rings are now plain `io_uring_queue_init(..., 0)`.
- **SEND_ZC.** Never validated, and its deferred-buffer-reset protocol (result CQE, then a later
  `F_NOTIF` CQE before `c->buf` may be reused) is the delicate part of the send path. No op on the
  ring can now produce `F_MORE`, so the reap loop is back to a fixed `n_submitted` count.

**Telling the binaries apart** — previously impossible, and the reason "did the gate open?" could
not be answered. `iouRecvDeliver` still bumps the same stat as the epoll read path, so instead of a
counter the build now names itself: a `NETWORK BACKEND: epoll|io_uring` line at startup and
`tomokv_net_backend` in `INFO server`. Any A/B that does not check one of those is a guess.

**Still true, still not done — the deep design.** `DEFER_TASKRUN`, `SINGLE_ISSUER`,
`register_ring_fd`, `RECVSEND_POLL_FIRST` appear NOWHERE in `src/`. The README's "registered ring
fd" claim was an overclaim and has been corrected. The collapse makes this work *easier*: the deep
flags are ring-construction parameters, and there is now exactly one construction site per ring
reachable in exactly one build configuration, instead of a matrix of runtime combinations each
needing its own validation.

**One piece still actively blocks the deep shape.** `iothread.c:168/:228` submit into another
thread's ring from MAIN. `SINGLE_ISSUER` forbids that, and if the cancel silently fails a
documented bug returns: a migrated client's still-armed multishot keeps eating socket bytes and
**the client silently desyncs forever**.

**UNRESOLVED — the migration contradiction (deliberately not fixed here).** `tomoMigrateTest` (now
`server.c:~18645`) declares connection migration unsupported under multishot-recv, while
`tmMigHandoff` disarms on the source and the adopt path re-arms on the destination — i.e. the exact
dance the refusal calls impossible is implemented — and the AUTONOMOUS path
(`tmMigScan → tmMigStartClient → tmMigHandoff`) has no guard at all. Both landed in the same commit,
so one is wrong from birth. This is a live client-LB question, not a theoretical one. Two things
changed on 2026-07-29 without resolving it:
- The refusal is now inside `#ifdef HAVE_LIBURING`. It was **not** guarded before, so a default
  epoll build with the old `-recv` knob set disabled migration while doing nothing whatsoever for
  I/O — a knob with only its side effect left. An epoll build can no longer reach it.
- Consequence: on a `USE_URING` build `DEBUG TOMO-MODESHIFT 5/6` always refuses, so
  `controller_sweep.sh`'s two migration cells cannot pass there. Unaffected on the default build.

Resolving it requires exercising autonomous migration on a `USE_URING` build — its own piece of work.

**Recommendation:** the epoll build is the shipping server. Treat the io_uring build as unshipped
until the deep flags exist and the migration contradiction is resolved.

---

## 6. Rejected / decided

- **Per-node main: NO.** The work main does is already a `for (node…)` loop. Every real problem is
  caused by singleton STATE, not a singleton THREAD. Shard the state and one 4 Hz thread drives N
  per-node machines (~0.005% of a core). Fork the thread without sharding the state and you get N
  racing writers on non-atomic singletons — including `tm_flip_ctx`, which is already LB-3. There is
  no ordering in which forking the thread is the valuable step.
- **Client-transfer redesign: not needed.** Client LB does not disconnect; it moves ownership of an
  open socket. The LB-1 window was ordinary connection churn, unrelated to transfer.

---

## 7. Standing rules

- **One server at a time. WAIT, NEVER KILL.** Killing to make room caused more loss than any code
  defect this cycle: `pkill -9 -x redis-server` killed other sessions' servers, `pkill -x flock`
  destroyed ~4 sessions' queued waiters, and `pkill -9 -x memtier_benchma` killed a live preflight's
  load generators. If someone else is on the box, you wait — a contended measurement is invalid
  anyway.
- **Stage every binary under a unique name; reap only that name.**
- **Tell the box-lock HOLDER from a WAITER before you kill anything.** `withbox.sh` runs
  `flock -w N 9` as a *child*. So in `fuser -v /tmp/tomo_box.lock`, a `withbox.sh` that still has a
  live `flock` child is QUEUED; a `withbox.sh` with **no** `flock` child has already acquired the
  lock and **is the running job**. I got this right diagnosing the wedge and then misapplied it 40
  minutes later, killing pid 470666 as "a stale waiter" when it was my own item-2 run that had just
  started — costing it its progress. Check for the `flock` child every time; it is one command.
- **`ppid=1` does NOT mean "abandoned" on this box** (learned 2026-07-29, the hard way). The
  standing advice was "a process with ppid=1 and no command is safe to clear; anything with a live
  parent is someone's running job". But the normal launch pattern here is
  `setsid nohup ./withbox.sh …`, so EVERY queued job is orphaned to init the moment it starts —
  including your own. On 2026-07-29 all 8 processes on the box lock were `ppid=1`. Use these
  instead, together: is any file in the owner's worktree newer than a few hours; is any live
  process `cwd`'d there other than the job's own shells; is the job past its own declared budget;
  and is it making progress (log mtime, per-thread `utime` deltas). A wedged job whose owner is
  gone is not "someone else on the box" — but prove all four before touching it, and preserve its
  artefacts first.
- **A killed server scores 0.00, not empty.** Reject `''|0|0.0|0.00` as INVALID. A LATE kill yields a
  merely DEPRESSED number, so distrust any single anomalous cell.
- **Right-sized tests**, two tiers: short and discriminating per change; the long suite after a batch,
  because per-change tests cannot see interaction. Shrink duration and breadth, never discrimination.
- **Sanity-gate every number.** Implausible ⇒ stop, re-read code and harness, fix, re-measure. This
  caught a fake −11.4% regression, a fake −15% regression, and two harness defects masking each other.
- **Prove the test discriminates** — see it FAIL pre-fix. And prove a gated feature's gate OPENED;
  "0 bugs" behind a closed gate is vacuous.
- **If a fix needs a second guard to make the first guard safe, the fix is wrong.** Go back to the
  smallest change that closes the original window. (The reshard teardown fix took four attempts and
  landed at 32 lines.)

---

## 8. Definition of done

1. Preflight green — every suite passes on its own merits, `preflight.GO` written.
2. Every merged branch validated against its own acceptance, or reverted.
3. The unowned defect list closed or explicitly deferred with a written reason.
4. One version: no agent forks, no side branches.
5. The quick-check 8 cells at expected throughput, then the competitive sweep LAST.
