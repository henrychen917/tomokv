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
| `d74df8895` | LB-1: flip controller UAF — main walked another io thread's client list | **build only** |
| `348f6dc23` | key-LB hot-key veto at per-bucket resolution + `tomokv-mset-move` restored (default off) | 3-arm veto evidence + cost, from its author; **not re-run post-merge** |
| `5b3b4581a` | active expiry never ran on the sharded keyspace (#42) | validated pre-merge both regimes; **not re-run post-merge** |
| `0a2ef6c6f` | `flip_updown` exit status was a constant | both exit codes observed |

**Three of these were pushed without a post-merge green.** That is a known deviation, recorded so it
is not mistaken for validated work. Item 2 below closes it.

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
5. **`knob_matrix`: io-uring knobs "DID NOT BOOT"** — expected, not a bug. `try()` sets ONE knob, so
   `tomokv-io-uring-recv yes` alone hits the deliberate orphan FATAL. Fix the *test* to set the
   master knob with it, or drop those cells.
6. **Three suites still reap the shared name** — `numa2_validate.sh`, `shared_refcount_race.sh`,
   `expiry_clock_ab.sh`. They can still kill other sessions' servers. `shared_refcount_race.sh` has
   no `BIN`-style variable, so it needs a hand-written fix rather than the mechanical one.

**Done means:** a preflight run in which every suite either PASSes or FAILs *on its own merits*, with
no "produced no result file" and no leaked server afterwards (`ss -lptn | grep 79` empty).

---

## 2. Validate what is already merged

Three merges are on the branch with no post-merge execution. Run each against the problem it was
built to solve, then either keep or revert. Do not re-derive; the acceptance criteria are known:

- **active expiry** — `tools/preflight/active_expiry_probe.sh`. Traffic-free, 100k keys with a TTL:
  pre-fix `dbsize` stays 100000 and `expired_keys_active=0` at BOTH `ex=1` and `ex=4`; post-fix
  `dbsize → 0` within ~3s past the TTL. Must hold in both regimes.
- **hot-key veto** — three arms. A: `unbal_fine=7 unbal_grp=0 fire=0`. **B: `fire=1` — must STILL
  MIGRATE on genuine multi-bucket skew**; if B stops migrating the fix is "never move" and must be
  reverted. C (`key-lb-fine 0`): the original defect reproduces. Plus `<=3%` cost, measured against
  the PARENT build — at `fine 0` the bounds test is still compiled in, so the knob cannot price its
  own instruction.
- **mset-move** — `correctness_suite` 15/0 with the knob OFF *and* ON; ASAN churn clean; the
  `tomokv_xshard_mset_moved` gate-open counter asserted as a **delta**, never an absolute (absolute
  lets a knob-OFF run pass on the previous ON run's total).
- **LB-1** — `correctness_suite` 15/0, plus the staged ASAN probe at `$J/exn/lb1_uaf_probe.sh`
  **pre-fix and post-fix**; the pre-fix arm is what makes it discriminate. It self-declares INVALID
  if no grow-front happened, if every grow-back was refused earlier, or if no churn occurred.

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
- **`fakeRingAutoTune`'s gate has never opened** — it reads `cmd->calls` for GET/SET, which never
  enter `call()`. `use_slim` has therefore never been exercised. Documented, deliberately not fixed:
  fixing it OPENS a hot-path gate for the first time and needs its own A/B.
- **Duplicate knob binding** — `tomokv-reshard-sustain-ticks` and `tomokv-key-lb-sustain` write the
  SAME field with different defaults and ranges. Aliased both ways; the wide-range name can push the
  field past the other's validator. `!= 0` gates the whole key-LB Schmitt debounce, so setting the
  reshard-looking knob to 0 silently disarms key LB's anti-thrash. Safe today only by config-table
  ordering. Fix: keep `tomokv-key-lb-sustain`, delete the other, hardwire the −1 auto behaviour.

---

## 5. io_uring — do not ship as-is

Collapse to one knob (`tomokv-io-uring`) is right, but it is not a cleanup:

- **The current path is NOT the deep design.** `DEFER_TASKRUN`, `SINGLE_ISSUER`, `register_ring_fd`,
  `RECVSEND_POLL_FIRST` appear NOWHERE in `src/`. The ring is `io_uring_queue_init(..., 0)`. The
  README's "registered ring fd" claim is an overclaim.
- **One piece actively blocks the deep shape.** `iothread.c:168/:228` submit into another thread's
  ring from MAIN. `SINGLE_ISSUER` forbids that, and if the cancel silently fails a documented bug
  returns: a migrated client's still-armed multishot keeps eating socket bytes and **the client
  silently desyncs forever**.
- **It may never have executed under test.** Nothing anywhere boots `--tomokv-io-uring yes` together
  with `--tomokv-io-uring-recv yes`, and `iouRecvDeliver` bumps the same stat as the epoll path, so
  INFO cannot tell you whether the gate opened.
- **Contradictory migration handling** — `server.c:18159` declares migration unsupported under recv,
  while `:17885/:18107` disarm-and-re-arm across migrations, and the AUTONOMOUS path
  (`tmMigScan → tmMigStartClient → tmMigHandoff`) has no guard at all. Both landed in the same
  commit, so one is wrong from birth. **This is a live client-LB question, not a theoretical one.**

**Recommendation:** land the knob collapse; treat the uring path as unshipped until the deep flags
exist and the migration contradiction is resolved.

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
