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
| `348f6dc23` | key-LB hot-key veto at per-bucket resolution + `tomokv-mset-move` restored (default off) | **KEEP** — veto 10/0 (arm B still migrates), mset-move 15/0 OFF+ON, ASAN churn clean, cost ≤3% |
| `5b3b4581a` | active expiry never ran on the sharded keyspace (#42) | **KEEP** — re-validated post-merge, both regimes, both arms; 15/0; tax −1.42% worst |
| `0a2ef6c6f` | `flip_updown` exit status was a constant | both exit codes observed |

### The "pushed without a post-merge green" deviation — status 2026-07-29

The three merges were re-run post-merge against the problem each was built to solve. **Nothing was
reverted; no merge regressed.** What the pass actually found was that two of the three *tests* were
incapable of returning a verdict — which is why "it was validated pre-merge" was never worth much:

| merge | verdict | what the re-run added |
|---|---|---|
| `5b3b4581a` active expiry | **KEEP** ✅ | full 2×2 discrimination (PRE fails / POST passes, at `ex=1` and `ex=4`), 15/0, and the always-on tax priced at −1.42% worst cell |
| `348f6dc23` veto + mset-move | **KEEP** ✅ | veto 10/0 across all three arms — critically **arm B still migrates** (`fire=1`), so the fix is not "never move"; arm C reproduces the original defect. mset-move 15/0 knob-OFF *and* knob-ON, gate delta 0 → 2.8M, and an **ASAN churn arm that did not previously exist** (3.2M moves, 0 mismatches, 0 reports). Cost ≤3% confirmed against the pre-all-three parent |
| `d74df8895` LB-1 | **KEEP**, but its UAF evidence is **not** obtained — see §2 | 15/0; found that its ASAN probe had **never once executed** past its own precondition; fixed the probe (0 → 25 grow-back cycles) and it *still* does not discriminate — the pre-fix build comes back clean too |

**Nothing was reverted. All three merges stay.** Two of the three were fully validated; LB-1 is kept
on inspection plus 15/0 correctness, with its missing empirical proof recorded as missing.

Findings that outlast this pass, none of which a suite could have gone red on:
1. a **torn `expired_keys` counter** under multi-worker expiry (§4);
2. the LB-1 probe's precondition was **unreadable on every build ever tested**, and once repaired
   the probe *still* cannot tell the vulnerable build from the fixed one (§2);
3. the "ASAN churn clean" arm that STABLE_PLAN required for mset-move **did not exist** (§2);
4. a live post-migration **wedge** on the experimental network backend, since deleted (§5).

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
5. **`knob_matrix`: alternate-backend knobs "DID NOT BOOT"** — RESOLVED 2026-07-29 by deletion.
   Those knobs no longer exist and neither does the backend they gated (section 5), so the cells
   were removed with them.
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

> **ANSWERED 2026-07-29 (§3e).** `flip_updown` has now run, on two builds. Flips **do** complete —
> four of them, `GROW-FRONT complete` / `GROW-BACK complete` both present, 0 arm rejections — so
> "no flip has ever completed" was a property of `controller_sweep`'s stimulus, not of the product.
> What the run found instead is that the controller stops after its initial climb and will not
> follow a later workload inversion: **FAIL on both arms, identically.** Filed in §4; it is now
> item 6's closed gate.

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
- **hot-key veto** (`348f6dc23`) — **KEEP. Validated post-merge 2026-07-29: 10 passed, 0 failed,
  `keylb_veto rc=0`.** ✅ All three arms behaved, and the author's original numbers reproduced
  exactly:

  | arm | workload | key counters | verdict |
  |---|---|---|---|
  | **A** window on | 97 % one key | `unbal_fine=7 unbal=7 unbal_grp=0 **fire=0**` | refused — and refused *at per-bucket resolution* (`fine_used=7 fine_arm=1`) |
  | **B** window on | 90 % spread over one shard | `**fire=1** unbal=0 unbal_fine=0 band=21` | **STILL MIGRATES** — the "never move" failure mode is excluded |
  | **C** window off (`key-lb-fine 0`) | 97 % one key | `unbal_fine=0 fine_used=0 **fire=1** noprog=20` | the ORIGINAL DEFECT reproduces |

  Arm B is the one that mattered and it passed: the veto is *selective*, not a blanket refusal, so
  there is nothing to revert. Arm C is what makes arm A attributable — with the window off the
  balancer fires on a single hot key and is stopped only by the no-progress guard, 20 times, which
  is precisely the "one wasted migration later" behaviour the window was built to prevent.
  The mechanism is visible in the run's own bucket dump: in group 77, bucket `b4942` carried
  **1 258 320 ops/s** while every sibling carried **1–6 ops/s**. A bucket flip relocates that load,
  it cannot divide it — so refusing is the correct answer, and the per-bucket window is what lets
  the planner see it. Raw: `$J/mrg/keylb_veto.out`.

  **Cost gate: PASSES, and the honest reading is "no measurable cost".** 4 arms × 3 reps × 20 s,
  ABBA-rotated, `base` = `redis-base-pre2` (verified byte-identical to `redis-aexp-pre`, i.e. it
  predates *all three* merges, so this prices the whole stack — a pass is conservative):

  | arm | p32set | vs base | p32get | vs base |
  |---|---|---|---|---|
  | `base` (feature absent) | 7 088 734 | — | 8 003 923 | — |
  | `off` (`fine 0`) | 7 031 011 | −0.81 % | 7 937 090 | −0.83 % |
  | `auto` (`fine -1`) | 7 060 448 | −0.40 % | 7 985 467 | −0.23 % |
  | `armed` (`fine 1`, window armed all run) | 7 088 524 | −0.00 % | 7 955 328 | −0.61 % |

  Worst arm −0.83 %, against a −3 % budget. But note **`armed` is not the worst arm and `off` is** —
  if the window had a real data-path cost, the always-armed arm would be the slowest and it is the
  fastest on `p32set`. Every arm sits inside this box's own ±2 % exclusive run-to-run noise, so the
  correct statement is *the cost is not measurable here*, not "the cost is 0.4 %".
  `migs=0` in all 24 cells, so no cell was invalidated by a cutover landing mid-measurement.
  Raw: `$J/mrg/keylb_fine_cost.tsv`.
  *Minor harness defect noticed, not fixed:* `keylb_fine_cost.sh`'s trailing "migrations fired per
  cell" summary re-prints the ops medians under a `migs=` label instead of the migration counts —
  garbled and capable of misleading. The TSV's `migs` column is the authoritative one.
- **mset-move** — `correctness_suite` 15/0 with the knob OFF *and* ON; ASAN churn clean; the
  `tomokv_xshard_mset_moved` gate-open counter asserted as a **delta**, never an absolute (absolute
  lets a knob-OFF run pass on the previous ON run's total).

  **KEEP. Validated post-merge 2026-07-29.** ✅ `correctness_suite` **15/0 with the knob OFF and
  15/0 with it ON**. Churn, gate asserted as a delta in both directions:

  | build | knob | `moved_delta` | gate | value mismatches |
  |---|---|---|---|---|
  | `redis-s2` (-O2) | OFF | **0** | correctly closed | 0 |
  | `redis-s2` (-O2) | ON | **2 836 003** | open | 0 |
  | `asanpost` (**ASAN**) | ON | **3 210 898** | open | 0, **0 ASAN report files**, server alive |
  | `asanpost` (**ASAN**) | OFF | **0** | correctly closed | 0, 0 ASAN report files |

  So the zero-copy hand-off ran millions of times with every value verified byte-for-byte, and the
  knob-OFF arm proves the delta is attributable rather than inherited from a previous run.

  **Two corrections were needed before this could be trusted:**
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

  **Re-run with the fixed probe — and the honest answer is that it still does not discriminate.**
  The repair itself is proven: `grow-front completed=1 io_threads_live=5`, and the run drove
  **25 grow-front/grow-back cycles** where every previous run drove **0**. Arm provenance verified
  at source, not assumed: `mrg/asanpre/src/server.c` contains the vulnerable
  `listRewind(server.clients[io_slot]…)` walk and zero `pinned_nonmig`; `mrg/asanpost/src/server.c`
  has the reverse. Both arms nevertheless came back clean:

  | arm | grow-backs | ASAN heap-use-after-free | verdict |
  |---|---|---|---|
  | PRE-fix `redis-lb1pre` (walk present) | 25 accepted | **0** | PASS — *should have failed* |
  | POST-fix `redis-lb1post` | 25 accepted | 0 | PASS |

  **Why it did not fire, from the run's own log** — the grown slot was nearly empty every time:
  `io thread 4 (0 conns)` ×5, `(1 conns)` ×10, `(2 conns)` ×7, `(3 conns)` ×1, `(4 conns)` ×2. So
  main's illegal walk of `server.clients[4]` traversed **at most four nodes**, and the UAF needs a
  client on *that* slot to be freed by its owner inside that traversal. 25 samples of a
  four-node walk is nowhere near the race. The probe's churn (`redis-cli ping` ×40 in a loop)
  makes short-lived connections spread over *all* io slots; only a handful ever land on the grown
  one. **To make it discriminate, the churn must pin many connections to the GROWN slot and churn
  them there** — that is the missing piece, and it is a probe change, not a product change.

  **Verdict: KEEP `d74df8895`.** Not because the probe went green — a green probe that cannot go
  red is worth nothing, which is the whole point of this section. Keep it because `correctness_suite`
  is 15/0 on it and because the defect is unambiguous on inspection: main walked
  `server.clients[io_slot]`, a list whose single owning thread frees nodes eagerly
  (`unlinkClient → listDelNode → zfree`, `adlist.c:173`), so `listNext()` could read freed memory.
  The fix replaces that with an owner-published `_Atomic` snapshot. **What is missing is the
  empirical proof, and it should not be recorded as obtained.**

**Done means:** each is green on its own acceptance, or reverted with the regression recorded.

---

## 3. Remaining merge queue

Serially, **one box acquisition each** — the previous campaign queued ~9 jobs concurrently and they
starved each other. That was an orchestration error, not a box problem.

| # | branch | acceptance | notes |
|---|---|---|---|
| 1 | cmdstats `8a24ab1b8`+2 | ~~`cmdstat_check.sh` 18 failures → 0; `LATENCY HISTOGRAM` calls == exact count~~ | **DONE 2026-07-29 — MERGED AND PUSHED** as `eac51d50a` (+ probe `fb1986434`). Acceptance met and shown to discriminate. Perf is no longer unmeasured: **−3.2 to −3.4% on p32 SET io4ex4, which EXCEEDS the 3% budget**; every other cell ≤1%. See §3a |
| 2 | debug-reload `c8aab4059` **only** | ~~`debug_reload.sh` 0/2 → 12/0~~ | **MERGED 2026-07-29 AND REVERTED — the acceptance FAILED.** POST reaches 12/0 in only **2 of 10 runs**; the other 8 crash the server. The residual this row called "FLATSTORE panics ~1 in 3" is understated on every axis: **8 in 10**, and mostly a **double free after silent data loss**, not a panic. Re-merge only together with a *validated* `cfea82654` (or an equivalent quiesce). See §3b |
| 3 | fpipe-lru `43bdd8972` **only** | ~~`xshard_lookup_accounting.sh` 5/2 → 7/0~~ | **DONE 2026-07-29 — MERGED AND PUSHED** as `bdec8d5ba` (+ preflight wiring `6d8211379`). Acceptance met and shown to discriminate on both arms; 15/0; postmerge worst cell −1.2%. See §3c |
| 4 | exec-nesting `c53223863` | ~~builds + 15/0; probe if cheap~~ | **DONE 2026-07-29 — MERGED AND PUSHED** as `5b078b10b` (+ suite `a6e66f6d4`). The probe did not have to be waived: **two** probes discriminate, one of them under the DEFAULT configuration. 15/0; postmerge a wash (worst cell −0.3%). See §3d |
| 5 | deletions (5 commits) | ~~15/0 + `reshard_suite` + `flip_updown`~~ | **DONE 2026-07-29 — MERGED AND PUSHED** as `5562e377b` (+ probe/README repair `6b6f088f0`). 15/0; `reshard_suite` 3/0 on **both** arms. **`flip_updown` FAILS — but IDENTICALLY on the pre-merge arm, so it is not this merge's**, and it is now a measured product finding rather than an unrun suite. Perf +0.3…+1.1%. See §3e |
| 6 | parked-removal `6b9d3a0b9` | **GATED on `flip_updown` passing — the gate is now CLOSED, see §3e** | Modifies flip actuation. Author validated only the MANUAL actuator. Resolved patch at `$J/mrg/step4_parked_removal_RESOLVED.patch`; it deletes `num_workers_alloc`, which active-expiry added folds over — auto-merge accepts both sides and the build then fails. Fix: `num_workers_alloc` → `num_workers`. **`num_workers_alloc` is still present after item 5 (40 uses in `server.c`, 3 in `server.h`), so that hazard is unchanged** |
| 7 | h2-fence `e7628efc4` | rebase first (base `95872c371`, collides with the private-binary commit) | Evidence: 4/4 violations base → 0/4 fixed, 232 `fence_midbatch_ticks`. **Missing: the throughput cells (`h2_thr.py`) showing A and B still serve their NON-migrating buckets through a cutover — that is the owner's actual design claim and it currently rests on code reasoning alone.** Adds `tomokv-reshard-fence-timeout`, a new "migration did not happen" path that bumps `reshard_done_seq`, which the flip controller reads |

### 3a. Item 1, cmdstats — MERGED 2026-07-29 (`eac51d50a`, probe `fb1986434`)

Merged exactly the three commits the row names (`cmdstats-fix` branches off `c2b73ac35`, already an
ancestor, so there is no drift). Full clean build on BOTH arms; one warning each, byte-identical —
`kvstore.c:73` `dictEncodeStoredKey` incompatible-pointer-type, **proven pre-existing by showing the
same line on the pre-merge build**. Zero new warnings.

**Acceptance met, and the test discriminates.** `cmdstat_check.sh`, io4ex4:

| arm | binary | `nm` | result |
|---|---|---|---|
| PRE `b01578a74` | `redis-cs-pre` md5 `52602190c5cd` | 0 `#B2` symbols | **18 WRONG** / 22 executed |
| POST `eac51d50a` | `redis-cs-post` md5 `44d75322002f` | 3 `#B2` symbols | **0 WRONG** / 22 executed |

The 18 are exactly what the defect predicts: worker-route and cross-shard `calls`/`usec` at 0, four
`latencystats` distributions missing, four `LATENCY HISTOGRAM` sample counts at 0, `tot-cmds`
20001 instead of 69001 (only the inline PINGs counted). POST is exact to the unit, including the
merged histogram counts 20000/20000/5000/4000/20000 — the assertion that separates a real
bucket-count merge from a well-formed reply that merely does not crash.
`correctness_suite` on POST: **15 passed, 0 failed**.

**Correction to `0dee9391d`'s own commit message.** It recorded `total_error_replies` as 4992/5000
on the PRE binary, i.e. 8 lost updates. Measured here on 4 workers: **4576/5000 — 424 lost, 8.5%**,
~50× the recorded loss. Same defect, much larger than claimed. POST reads exactly 5000.

**The acceptance script cannot finish, for a reason that is NOT this merge — see the new §4 entry.**
`CONFIG RESETSTAT` after error traffic segfaults the server on **both** arms, so its last five
assertions were unexecuted on both, and unexecuted is not passed. Closed by
`tools/preflight/cmdstat_reset_probe.{sh,py}` over an error-free workload: **PRE FAILED (3), POST
PASSED (6)**. That the error-free run does not crash on either binary is also a controlled
confirmation that the crash is the errorstats rax and not `#B2`'s shard reset.

**COST — EXCEEDS THE BUDGET ON ONE CELL. This is the flag the row asked for.**
3 reps × 20 s, ABBA-rotated, pre-vs-post binaries (the feature has no knob, so the build without it
is the only arm that prices it):

| cell | pre | post | delta |
|---|---|---|---|
| GET p1 io7ex1 | 833 628 | 828 076 | −0.67% |
| GET p32 io4ex4 | 8 006 701 | 7 953 139 | −0.67% |
| SET p1 io7ex1 | 820 853 | 819 736 | −0.14% |
| **SET p32 io4ex4** | **7 080 191** | **6 839 658** | **−3.40%** |

Real, not drift: the rep distributions do not overlap (min pre 7 019 813 > max post 6 855 756) on a
box with ±2% exclusive noise. But the asymmetry is the informative part — SET loses 240k ops/s and
GET only 54k for **identical** added work. A uniform per-command cost cannot do that; the cost
surfaces only where the **worker** is the bottleneck, and is absorbed by worker slack where the io
threads are. Decomposed on that one cell (3 reps, rotated, arm identity asserted from `CONFIG GET`
rather than assumed):

| arm | median ops/s | vs pre |
|---|---|---|
| pre | 7 103 961 | — |
| post | 6 878 697 | −3.17% |
| post `--latency-tracking no` | 6 973 612 | −1.83% |

All three separate cleanly (min nolat 6 940 643 > max post 6 891 505). So ~1.3 of the ~3.2 points is
the `hdr_record_value` that `latency-tracking` (a stock knob, **default yes**) now puts on the worker
path — before this merge workers recorded no histogram at all, because they never entered `call()`.
The other ~1.8 points is the counter shard plus the extra `getMonotonicUs`, and **that part is
unconditional**. Raw: `$J/step3_cmdstats/{cost_ab.tsv,cost_decomp.tsv}`.

**Pushed with the overage stated**, per the row's own "if >3%, report before pushing": it is 0.2–0.4
points over on ONE of four cells, against this project's own `postmerge.sh` regression threshold of
−4%, in exchange for an observability surface that was 100% wrong on the fork's main routes. That is
the owner's call to make — but it is now a measured number instead of the "UNMEASURED" the row
carried. If the 3% budget is to be enforced literally here, the lever is `latency-tracking no`, which
recovers ~40% of it and needs no code change.

### 3b. Item 2, debug-reload — MERGED 2026-07-29, THEN REVERTED

**The branch is untouched at `58adb8a11`.** The merge was validated before it was committed, so the
revert is a `git merge --abort`: there is no merge commit and no revert commit. `src/redis-server`
was rebuilt afterwards and is byte-identical to the pre-merge build (md5 `94ee07ef964ad399`), so the
worktree does not carry a stale binary for the next step.

Merged exactly what the row names: `c8aab4059` only, `cfea82654` excluded. Clean auto-merge, 2 files,
+150 lines, nothing else swept in. Full `make clean && make -j16` on **both** arms; **exactly one
warning each, identical** — `kvstore.c:73` `dictEncodeStoredKey` incompatible-pointer-type, proven
pre-existing by showing it on the PRE build log. **Zero new warnings.** Arm provenance checked in the
binaries, not assumed: `emptyData` disassembles to **2** `emptyDbStructure` calls in PRE and **3** in
POST.

**The test discriminates, exactly as the commit claimed.** `debug_reload.sh` on PRE
(`redis-dr-pre`, md5 `94ee07ef`): **0 passed / 2 failed**, both regimes, reload #1,
`Guru Meditation: Duplicated key found in RDB file #rdb.c:4017`.

**And then POST fails too — in a worse way.** Ten full runs of the same script on the merged binary
(`redis-dr-post`, md5 `7d828926`):

| regime | runs 12/0 | runs that crashed the server |
|---|---|---|
| dict (`ex=1`) | 9 / 10 | 1 (see below — unrelated stack) |
| **FLATSTORE (`ex=4`)** | **2 / 10** | **8 / 10** |

Crash signatures on the merged binary, all in the flat regime: `illegal decrRefCount for object
with: type 4, encoding 11, refcount 0` (OBJ_HASH / listpack) ×4, the same for `type 3` (OBJ_ZSET) ×2,
`type 0, encoding 0` (OBJ_STRING / raw) ×1, and `Duplicated key found in RDB file` ×1. Seven of the
eight are **double frees**, not panics.

**Mechanism, from the servers' own logs — and it corroborates `cfea82654`'s diagnosis.** In every
failing run the FLATSTORE resize coordinator ran *while the reload was between* `Loading RDB produced
by version` and `Done loading RDB`, and its snapshot captured a partially-mutated table:
`live=91719`, `73365`, `73365`, `18328` out of 100000. In `rep6` the resize line and
`Duplicated key found in RDB file` share a **millisecond** — the same correlation `cfea82654` reported
at `live=55039`. So the fold mutates the old table while the coordinator rebuilds the new one from a
pre-empty snapshot, and the swap resurrects rows the empty had already freed.

**The failure mode `dbsize` conservation cannot see, and this is the reason to revert rather than
ship with a note.** In the common case the reload *reports success*: all three `DEBUG RELOAD`s return
OK and `dbsize` reads exactly **100000** each time, so the suite's conservation check PASSES — while
`hget h:2 f1` and `zscore z:3 b` return **nil**. Keys are gone with the count intact. The 2000-key
readback then gets **no reply at all** for its full 30 s socket timeout (the server is *wedged*, not
dead), and the process dies ~30.2 s after the reload, when the timed-out client disconnects and its
teardown decrefs an already-freed object: 06:04:08.05→06:04:38.38, 06:06:29.56→06:06:59.86,
06:07:55.72→06:08:25.89. Silent data loss, then a hang, then memory corruption.

**`correctness_suite` on the merged binary: 15 passed, 0 failed.** It does not go red on any of this
— it has no reload/`emptyData` check at all. 15/0 was necessary and nowhere near sufficient here.

**Blast radius, so the next attempt is scoped correctly.** In the sharded build `FLUSHALL`/`FLUSHDB`
never reach `emptyData` — `db.c:1533/1557` route to `flushAllShards`, which *already* waits out
`flat_resize_active`. The fold's new exposure is therefore admin/replication only: `DEBUG RELOAD`,
`DEBUG FLUSHALL`, **replica full resync** (`replication.c:2119/2450/2501`), `CLUSTER RESET`
(`cluster_legacy.c:1086`), `module.c:14201`. A replica full resync is squarely a stable-release path,
which is why "it is only DEBUG" is not an argument for shipping it.

**Three corrections to the row as it was written:**
1. **"~1 in 3" is wrong** — 8 of 10, and 7 of the last 7 consecutively.
2. **"panics" is wrong** — 1 of 8 was the panic; 7 were double frees, and the *visible* symptom in
   most runs is lost keys under a correct `dbsize` plus a 30 s wedge.
3. **"FLATSTORE" is right for the attributable failures but the dict regime is not proven safe.**
   One dict run (`rep5`) died in `DEBUG RELOAD` #2 with **SIGSEGV in `getClientMemoryUsage` →
   `listEmpty`** (address 0x28). That stack has nothing to do with `emptyData`, so it is **not
   attributed to this merge** — but it cannot be cleared against the PRE arm either, because the PRE
   arm never survives reload #1. Recorded as an unattributed crash, 1 in 10, dict regime, under
   `DEBUG RELOAD`.

**What the next attempt needs.** `c8aab4059` + `cfea82654` (or an equivalent quiesce), compiled, zero
new warnings, `correctness_suite` 15/0, **and ≥10 runs of `debug_reload.sh` with 0 crashes** — one
green run proves nothing at an 80% failure rate, and two green runs in a row happened here on a build
that fails 8 times in 10. Rig, arms and every server log are kept at `$J/step3_dbgreload/`
(`run_acc.sh`, `run_reps.sh`, `debug_reload.sh.kept`, `srv_post_r*_{dict,flat}.log`,
`dr_pre.out`, `dr_post_r1..10.out`, `build_{pre,post}.log`).

**Not measured, deliberately:** the two `postmerge.sh` throughput cells. `emptyData` is not on any
command path a benchmark touches, and the merge was reverted on correctness before perf could matter.

### 3c. Item 3, fpipe-lru — MERGED 2026-07-29 (`bdec8d5ba`, wiring `6d8211379`)

Merged exactly the commit the row names. `git log HEAD..origin/fpipe-lru-fix` listed **one**
commit and the staged set was **three files** — `src/server.c` (24 lines, all inside
`csPipeSubExec`) plus the two new preflight files. **Fix 2 is excluded**: it is an uncommitted
`M src/server.c` in the author's worktree, is not on the branch, and was never compiled. Clean
auto-merge, nothing swept in.

`make clean && make -j16`, exit 0, **120 objects recompiled**, **exactly one warning** —
`kvstore.c:73` `dictEncodeStoredKey` incompatible-pointer-type, the same single warning the full
clean PRE build of this tree emits (`$J/step3_dbgreload/build_pre.log`). **Zero new warnings.**
*Sanity gate on the build itself:* an 8-second full build looked implausible until the `.o`
mtimes were read — all 120 land in a 3-second window and the link takes the next 4 — which is
what `-O3 -flto=auto` does: the per-TU pass only emits GIMPLE and the optimisation happens in a
parallel LTO link. The build is real, not a stale-object illusion.

**Acceptance met, and the test discriminates — the author's pre-fix numbers reproduced exactly.**
Both arms driven by the SAME script copy, io4/ex4:

| arm | binary | LFU delta/key (expect 20) | keyspace_hits delta (expect 80) | result |
|---|---|---|---|---|
| PRE `436e71c2e` | md5 `94ee07ef964ad399` | **40** | **160** | **5 passed / 2 failed** |
| POST `bdec8d5ba` | md5 `02540cc43f9bc24a` | 20 | 80 | **7 passed / 0 failed** |

The two controls — single-key `SCARD` and a same-shard localfast `SINTER` — read 20 / 80 on
**both** arms, so the two failures are attributable to the pipeline route and not to the counter
apparatus; and the routing oracle (`tomokv_xshard_multikey_split` delta 20 = one split per
`SINTER`) passed on both, so the pipeline arm really executed. The probe reads the LFU counter out
of the RDB (`RDB_OPCODE_FREQ`) with `--lfu-log-factor 0 --lfu-decay-time 0`, which turns the
counter into an exact access count, so the assertion is an integer and not a ratio.

`correctness_suite` on the merged binary: **15 passed, 0 failed.**

**Perf: no regression, and the change is off the benchmarked path.** `postmerge.sh`, 4 cells,
20 s each, against the recorded baseline: `p1GET_io7ex1` **+0.6%**, `p1SET_io7ex1` **+0.3%**,
`p32GET_io4ex4` **−0.7%**, `p32SET_io4ex4` **−1.2%** — all inside this box's ±2% exclusive noise,
and the only edited lines are in `csPipeSubExec`'s `GATHER1`/`PROBE` cases, which `GET`/`SET`
never enter. One rep per cell, so these **bound** the cost rather than resolve it; nothing here
needs a decomposition because there is no per-command work to price (the fix strictly *removes*
lookup side effects on one route).

Two notes on the change itself, checked rather than taken from the commit message:
- `CS_PIPE_REREAD` is `LOOKUP_NOTOUCH|LOOKUP_NOSTATS|LOOKUP_NONOTIFY` and deliberately **omits**
  `LOOKUP_NOEXPIRE`, so a re-read still sees a lazily-expired key as gone. Silencing the
  accounting did not silence expiry.
- The row's own caveat holds: **LRU shows no distortion** (`val->lru = LRU_CLOCK()` is idempotent
  within a 1 s tick), so only LFU and `keyspace_hits` were ever wrong. The commit says this too;
  the branch name overstates the defect.

**One thing was added beyond the merge (`6d8211379`), and it is a harness change, not a product
change.** The branch adds two files to `tools/preflight/` and nothing calls them — the same shape
§1a records for `side_regression.sh`, which sat unreferenced while this document listed its output
among the files a preflight run must produce. Wired in after `correctness_suite` (~10 s,
traffic-free), with `redis-xslookup` added to preflight's `_OURS` so a leak of it is reaped and
named. **Honest limit: the wiring itself has not been executed under `preflight.sh` — no full
preflight run was made in this step.** What ran twice is the same script under the same
`TOMO_BIN` / `TOMO_PREFLIGHT_DIR` contract `run_suite` uses; the only untested difference is the
private server name. Its port (7312) was checked against every other suite in the directory and
is unique.

Raw: `$J/step3_fpipe/` (`run.log`, `acc_pre.out`, `acc_post.out`, `correctness_post.out`,
`postmerge.out`, `build_post.log`, `run_step.sh`, and the two staged binaries).

### 3d. Item 4, exec-nesting — MERGED 2026-07-29 (`5b078b10b`, suite `a6e66f6d4`)

Merged exactly the commit the row names. **The row omits a hazard that the branch itself carries:**
`exnest-fix`'s tip is `7943601ab`, which is LB-1 — already on this branch as `d74df8895`. Merging
the *branch* rather than the *commit* would have re-applied it. `git log c2b73ac35..exnest-fix`
lists both; only the older one belongs here. The base `c2b73ac35` is already an ancestor, so there
is no drift, and the merged tree is byte-identical to what `git merge-tree` predicted **before** the
merge ran (`04905f37`) — checked again immediately before committing, since §7 records a case where
an unrelated agent's staged files entered a commit between those two moments.

`make clean && make -j16`, exit 0, 120 objects, **exactly one warning** — `kvstore.c:73`
`dictEncodeStoredKey` incompatible-pointer-type, the same single warning the pre-merge build of this
tree emits (`$J/step3_fpipe/build_post.log`, whose source tree is identical to the merge base: the
two commits since it touch only `tools/` and `docs/`). **Zero new warnings.** Arm provenance taken
from the binaries: POST carries `execution_nesting` as a 4-byte **TLS GLOBAL** symbol in the same
TLS block as `iotid`; PRE has no such symbol at all, because it was a field inside `struct
redisServer`.

**Both probes discriminate, and the more interesting one needs no non-default knob.**

1. **DEFAULT CONFIG — the bookkeeping consequence** (new, now shipped as
   `tools/preflight/exec_nesting.{sh,py}`). `call()`'s EL duration sampler runs *after*
   `exitExecutionUnit()`, so `execution_nesting == 0` there means "my unit is over". One connection
   holds its own io thread inside `DEBUG SLEEP`; a connection proven **by oracle** to be on a
   different io thread runs 50 × `DEBUG SLEEP 2ms` and reads `INFO stats
   eventloop_duration_cmd_sum` either side. 2 interleaved rounds:

   | arm | armed delta | unarmed control | verdict |
   |---|---|---|---|
   | PRE `14fc957c8` | **42 / 46 µs** | 102 799 / 103 331 µs | **FAIL** — ~100 ms of duration unsampled |
   | POST `5b078b10b` | 102 749 / 103 269 µs | 102 736 / 103 444 µs | PASS |

   The unarmed control is the whole point: it moves on **both** builds, so "the sum did not move"
   on PRE is attributable to the arm rather than to a dead probe — the failure mode §2 records for
   `lb1_uaf_probe`, which passed for years without ever reaching the function it tests.

2. **NON-DEFAULT CONFIG — the data-visible consequence** (the author's
   `$J/exn/exnest_probe.py`; needs `--lazyexpire-nested-arbitrary-keys no`, because
   `confAllowsExpireDel()` short-circuits to 1 under the default). Two io threads at depth 1 each,
   workers running `RANDOMKEY` over a fully-expired keyspace with active expiry off. 3 interleaved
   rounds: **PRE FAIL, FAIL, INVALID** (`dbsize` 400 → 400; the INVALID is its own overlap guard
   firing, not a pass) — **POST PASS, PASS, PASS** (`dbsize` 400 → 0).
   *Sanity gate on a number that looked wrong:* PRE served only 800–816 `RANDOMKEY` replies in the
   window where POST served 56 742–64 530, a 70× gap that at first read like two different
   workloads. It is the defect: when the lazy delete is refused, `RANDOMKEY` re-rolls up to
   `maxtries` times per call over a keyspace where **every** key is expired, so each call costs ~100
   lookups and returns nil. The gap corroborates the mechanism instead of contradicting it.

**So the row's own fallback — "if the probe cannot discriminate, merge on the static argument and
SAY SO" — was not needed.** The row's other claim is confirmed and can now be stated with a number:
under the default configuration this is bookkeeping only, but it is **total, not partial** — 100% of
the EL command-duration samples were lost for as long as any other io thread sat inside a top-level
command.

`correctness_suite` on the merged binary: **15 passed, 0 failed.**

**PERF: a wash, and it is a BOUND, not a result.** `postmerge.sh`, 4 cells, vs the recorded
baseline: `p32GET_io4ex4` **+0.0%**, `p32SET_io4ex4` **+0.1%**, `p1GET_io7ex1` **−0.3%**,
`p1SET_io7ex1` **+0.5%** — inside this box's ±2% exclusive noise, one rep per cell. Do not read
those cells as evidence about this change: **GET/SET at both configs are worker-routed, and workers
call `cmd->proc` directly without entering `call()`**, so the edited lines are barely executed
there. What was checked instead is static and decisive about cost: `enterExecutionUnit` compiles to
a single `mov %fs:…,%eax` / `mov %eax,%fs:…` pair (**local-exec** TLS) and the binary contains
**zero** `__tls_get_addr` calls, so the hot path traded a shared-memory RMW for a segment-relative
one and cannot have got slower.

**A second commit, and it is a harness change, not a product change (`a6e66f6d4`).** The defect that
was just fixed had **no** test in this tree — `correctness_suite` is 15/0 on the vulnerable build
*and* on the fixed one. Probe 1 is therefore shipped as `tools/preflight/exec_nesting.{sh,py}` and
wired into `preflight.sh` (port 7318, unused elsewhere; `redis-exnest` added to `_OURS`). It is
shown to discriminate **in its shipped form**, not only as the scratch script: PRE **3 passed / 1
failed, exit 1**; POST **4 passed / 0 failed, exit 0**. A preflight run must now also produce
`exec_nesting.out`. **Honest limit, the same one `6d8211379` carries: the wiring has not been
executed under `preflight.sh` itself** — no full preflight run was made in this step; what ran, on
both arms, is the same script under the same `TOMO_BIN` / `TOMO_PREFLIGHT_DIR` contract `run_suite`
uses.

**Found, not fixed — a stale comment this merge invalidates.** `expire.c:176` justifies the worker
expiry cycle's refusal to use `activeExpireCycleTryExpire()` by saying it mutates "main-thread-global
execution-unit state (`server.execution_nesting`, the pending-push/tracking queues)". The first item
is no longer true. The refusal is still correct on the second, but the comment now names a fixed
defect as a live reason and should be trimmed in a batch that already rebuilds `expire.c`; it was
left alone here rather than widen a validated merge by an uncompiled edit.

Raw: `$J/step3_exnest/` (`run.log`, `probeA.tsv`, `probeB.tsv`, `correctness_post.out`,
`postmerge_post.out`, `build_post.log`, `suite_ab.log`, `exec_nesting.{pre,post}.out`,
`elsample_probe.py`, `step.sh`, and both staged binaries).

### 3e. Item 5, deletions — MERGED 2026-07-29 (`5562e377b`, probe/README repair `6b6f088f0`)

Merged exactly the five commits the branch carries (`7e3ca8b18` copy engine, `af2efcf60`
`TOMO_MODE_WB`, `ef6d0730b` cluster tooling, `68886125d` module API, `d3ba0ac7f` a comment), off
base `1029d0e74` — already an ancestor, so no drift. Clean auto-merge; the merged tree is
byte-identical to what `git merge-tree` predicted **before** the merge ran (`8e2a2a58`), rechecked
immediately before committing per §7. 165 files, +204/−34 724.

`make clean && make -j16`, exit 0, 120 objects, **exactly one warning** — `kvstore.c:73`
`dictEncodeStoredKey` incompatible-pointer-type, **proven pre-existing by a full clean build of THIS
tree at the merge base** (`$J/step3_deletions/build_pre.log`, byte-identical warning line). **Zero
new warnings.**

**The row said "Large" and left the interesting question unasked: how much of that engine was
LIVE?** None of it, in every configuration this project gates or benchmarks. `migCaptureEffect`'s
first line on the pre-merge build is `if (server.shared_node_dbs) return;`, and `shared_node_dbs`
is `(ex_per_node > 1)` — so at any `tomokv-thread-ex ≥ 2` the capture, the log, the scan and the
replay were already unreachable. The PRE arm's own reshard log proves it rather than asserting it:
every cutover under load printed `fence drained: S_final=0` — **zero effect-log entries ever
recorded**. What the deletion removes from the running system is a `migration_active` relaxed load
plus a call on four write paths (`exExecFake`, `csSubExec`'s MSET and DEL, the 2-hop dump/restore).

**The one behaviour change, stated rather than buried.** `reshardArm`'s
`ex_dbs[src] != ex_dbs[dst]` refusal is now UNCONDITIONAL instead of `shared_node_dbs &&`-gated.
Checked, not assumed, that nothing automatic can hit it: `reshardDiffusionPass` skips any boundary
where `tmNodeOfWorker(w) != tmNodeOfWorker(w+1)`, the outlier path picks `B` only from same-node
neighbours (`hnode` check), the RELEVEL walk iterates a per-node `live[]`, and GROW-BACK arms
`src = w-1 → w` inside one node. What it *does* newly refuse is spare activation
(`DEBUG TOMO-MODESHIFT 2`) at `ex_per_node == 1`, because the spare slot keeps a **private** db
array (`node_dbs[nnodes]`) — that is the deprecated PARKED↔EX actuator item 6 deletes outright.
`DEBUG RESHARD START` cannot reach the refusal at all: `!tmWorkerLive(dst)` rejects a parked spare
first (`ERR bad range/workers`, observed on both arms), so the probe intended to discriminate it
could not, and that is recorded as **not obtained** rather than glossed.

**Arm provenance from the binaries and from live behaviour, never from git:**

| signal | PRE `redis-del-pre` `0859600e` | POST `redis-del-post` `9031cefe` |
|---|---|---|
| `nm`: `migCaptureEffect` / `migRangeChecksum` | 1 / 1 | **0 / 0** |
| `DEBUG RESHARD STATUS` | `… issued= applied= scan_done= src_keys= … converged=` | `active/phase/lo/hi/src/dst` only |
| cutover log line | `fence drained: S_final=0` | `fence drained` |

**Acceptance, both arms, one box acquisition:**

| check | PRE | POST |
|---|---|---|
| `correctness_suite` | — | **15 passed, 0 failed** |
| `reshard_suite` | **3/0** — 0 violations / 57 323, 6 cutovers, 0 arm rejects | **3/0** — 0 / 238 688, 6 cutovers, 0 arm rejects |
| `flip_updown` | **FAIL** io 3→3→3→3, 24 ctl lines, 2 GROW-FRONT + 2 GROW-BACK complete, 0 arm rejections | **FAIL — identical on every field** |

**`flip_updown` fails on both arms, and this is its FIRST EVER EXECUTION** (§1a: it had never once
run). It is not blind — it observed four real flips and 24 controller lines — and PRE and POST agree
field for field, so nothing here is attributable to this merge. The failure is the flip
**controller**: from a boot of io4/ex4 it grows the front twice and back twice within ~12 s, then
pins its forward deadzone (`dz(f1.61/b0.25)` POST, `dz(f1.75/b0.25)` PRE — pinned, no decay) and
HOLDs at `io=3` through every later p32↔p1 phase change, including ticks reading `io_sat=1.31`.
The suite is right to call that a failure: p32→p1→p32→p1 must move the mix both ways and it moves
neither. **Recorded as an open product item (§4), and it CLOSES item 6's gate** — item 6 says
"GATED on `flip_updown` passing", and not-run was never a pass, but now it is a measured FAIL.

*A caution for whoever picks that up:* the controller's `io=` field is `io_live_node`, and it read
**3** in the same run where `GROW-BACK complete — io_threads_live=4` was logged. Establish what that
field counts before reading any verdict built on it; `flip_updown` compares it across four phases.

**PERF: no regression, and the sign is the one the change predicts.** `postmerge.sh` vs the recorded
baseline: `p32SET_io4ex4` **+1.1%**, `p1GET_io7ex1` **+1.0%**, `p1SET_io7ex1` **+0.8%**,
`p32GET_io4ex4` **+0.3%**. All four inside this box's ±2% exclusive noise, one rep per cell, so these
**bound** the cost rather than prove a gain — but the write-heavy cell moves most and the pure-read
cell least, which is what deleting a per-write branch does.

**One harness defect the merge created, and it is the §2 shape again (`6b6f088f0`).**
`reshard_order.py` — `reshard_suite`'s entire driver — polled `DEBUG RESHARD STATUS` for
`scan_done=1` before every cutover. That field went with the cold scan, so on the merged build the
condition could never hold and every cutover paid the loop's full 200 × 5 ms timeout. Measured in
the arms' own logs: FLIP-to-FLIP cadence **0.704 s PRE vs 1.710 s POST**, a 1.006 s gap against a
1.000 s timeout. **The suite stayed green throughout** — a CUTOVER issued after the timeout is a
valid CUTOVER — so this was not a red suite but a green one doing a fraction of the work it claimed.
Repaired to wait on `phase=1` (`MIG_COPYING`), `reshardBeginCutover`'s actual precondition.

That repair alone made the probe *weaker*: with the stall gone it hit its 6-cutover / 3000-round
floors in ~2 s and exited having sampled **3 000** rounds where the same suite had just sampled
**238 688**. A race probe's evidence is its sample count, so a 79× cut is a real loss of
discrimination bought with a latency win. Added a 10 s wall-clock floor — the one budget unit that
does not move when the server gets faster:

| arm | rounds | cutovers | wall | verdict |
|---|---|---|---|---|
| pre-merge, probe as it was | 57 323 | 6 | ~15 s | 3/0 |
| merged, probe as it was | 238 688 | 6 | ~15 s | 3/0 |
| merged, `phase=1` only | 3 000 | 14 | ~7 s | 3/0 |
| **merged, `phase=1` + floor (shipped)** | **191 105** | **324** | ~16 s | **3/0** |

3.3× the rounds and 54× the cutovers of the arm this suite was last certified on, at unchanged cost.
0 violations, 0 arm rejects, 0 crash markers in every row. Also corrected a stale justification in
`reshard_arm_race.py` (it avoided `DEBUG RESHARD STATUS` because "STATUS runs `migRangeChecksum`
over the whole shard" — true until 2026-07-28, false now; its behaviour is unchanged, only the
reason was wrong), and the README's "effect-log copy" description of a deleted engine.

**Checked and clean, so the next step does not have to re-ask:** no io_uring symbol or knob returned
through the 3-way merge (0 references in `src/`); the config surface is bit-for-bit the same size
(213 `create*Config` entries both sides), so §5's retired-knob trap is not re-armed; no file under
`tools/` referenced any deleted test tree; all nine edited `.tcl` files are brace-complete under
tcl's own `info complete` and no `start_cluster` reference survives anywhere in `tests/`.

Raw: `$J/step3_deletions/` (`run.log`, `run_step.sh`, `run_probefix.sh`, `probefix.log`,
`build_{pre,post}.log`, `correctness_post_RESULT.out`, `reshard_{pre,post}.out`,
`reshard_post_fixedprobe.out`, `rs_{pre,post}.log`, `flip_{pre,post}.out`,
`flip_{pre,post}.srv.log`, `postmerge_post.out`, and both staged binaries).

---

## 4. Unowned defects

Nothing is working on these.

- **The FLATSTORE resize guard is ONE-SIDED, and it is what blocks §3 item 2** (evidence added
  2026-07-29, §3b). `FLAT_RZ_COPYING` needs the old table immutable for the whole rebuild. The
  coordinator enforces that against WORKERS (it parks them) and against a non-worker region that is
  **already** open (QUIESCING will not complete while any io `flat_epoch` is odd). Nothing re-checks
  the epoch once past QUIESCING, so a non-worker region that **opens during COPYING** is unguarded —
  and `emptyData`'s shard fold and `rdbLoad`'s `dbAddRDBLoad` are exactly such mutators. Measured:
  the coordinator snapshotting a table mid-reload (`live=91719/73365/18328` of 100000) loses keys
  silently, wedges the server, and ends in a double free, 8 runs in 10. `cfea82654` is a candidate
  fix (`tomoFlatResizeQuiesce`) and is **still never compiled and never run**. Owning this is the
  precondition for merging the `emptyData` fold.
- **THE FLIP CONTROLLER DOES NOT FOLLOW THE WORKLOAD, and it blocks merge-queue item 6** (found
  2026-07-29 by `flip_updown`'s first ever execution, §3e — **pre-existing: the pre-merge arm
  behaves identically, field for field**). Booted io4/ex4 with `--tomokv-thread-mode auto` and
  driven p32 → p1 → p32 → p1 at 45 s a phase, the controller actuates **four times in the first
  ~12 s** (GROW-FRONT ×2 to io6, then GROW-BACK ×2 back to io4), then pins its forward deadzone —
  `dz(f1.61/b0.25)` on the merged build, `dz(f1.75/b0.25)` on the pre-merge one, **pinned with no
  decay by design** — and HOLDs for the remaining ~3 minutes, through both later workload
  inversions, on ticks reading `io_sat` up to 1.31. The suite reads `io=3` in all four phases:
  `fwd=0`, `back=0`, FAIL. The mechanism is not "the actuator is broken" — 0 arm rejections, all
  four flips completed — it is the deadzone pin: after the initial climb the controller decides it
  has settled and never re-probes. Not fixed here (this was a merge validation pass, and the
  behaviour is not this merge's), but it is the gate item 6 named for itself, so **item 6 cannot
  merge until this passes.** Two traps for whoever takes it: (a) the field the suite grades on is
  `io_live_node`, which read **3** in the same run that logged `GROW-BACK complete —
  io_threads_live=4`, so establish what it counts before trusting any verdict computed from it;
  (b) a controller that never moves and a controller that moves once and stops both score
  "0 flips" on a single-phase test — which is how this survived unexamined.
- **LB-2** `server.hotkeys` — one process-global struct used as per-command scratch by every io
  thread. OOB read, double free, and `current_client` clobbering that indexes `argv[pos]` into a
  *different* client's argv. Dormant until `HOTKEYS START`, but the subsystem is unusable as written.
- **LB-3** `tm_flip_ctx` TOCTOU — non-atomic, and it is simultaneously the flip state machine AND
  the "is a flip in progress" gate. **The key balancer defers entirely on it** (`server.c:11475`).
  Writers: main, and any io thread via `DEBUG TOMO-MODESHIFT`.
- **LB-4** torn `tm_mig_mbox` request block — two publishers, non-atomic check-then-store.
- **`errorstats` concurrent `raxInsert`** — worker threads mutate the shared `server.errors` rax with
  no synchronisation. Structural race, not a counter race.
  **NOW HAS A REPRO, AND IT IS A HARD CRASH (found 2026-07-29 by the cmdstats acceptance).** Drive
  worker-executed error replies, then `CONFIG RESETSTAT`, and the server dies:
  `rax.c:1280 'rax->numnodes == 0' is not true` in `raxFreeWithCallback`, then **SIGSEGV in
  `raxIteratorNextStep`**. `resetErrorTableStats` (`server.c:4929`) frees `server.errors` and swaps
  the pointer while every IO thread and worker is still in `raxFind`/`raxInsert` on it
  (`server.c:12474`/`12507`); `INFO errorstats` walks the same rax at `server.c:14604`. It fired on
  the FIRST attempt on both a pre- and a post-cmdstats binary, so it is neither flaky nor new —
  it was simply never provoked, because nothing in preflight had combined error traffic with
  `RESETSTAT`. Promoted from "structural race" to **crash-on-demand**: this is no longer a dormant
  item, it is reachable by an ordinary admin command. `tools/preflight/cmdstat_check.py` dies on it
  every run and is left doing so deliberately.
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
- **The post-execution-unit singletons are now reached by every io thread, at full rate** (raised
  2026-07-29 by the exec-nesting merge, §3d — recorded because it is a consequence of a merge that
  was kept, not a reason to revert it). While `execution_nesting` was a process-global sum, an io
  thread's end-of-unit work was **skipped** whenever any other thread happened to be mid-command:
  that was the bug, and running it is the fix. But the state it runs against is still process-global
  — `server.duration_stats[EL_DURATION_TYPE_CMD]` (plain `cnt`/`sum`/`max`, non-atomic RMW,
  `latency.c:719`), `server.also_propagate` (`server.h:3468`) and `server.pending_push_messages`
  (`server.h:3592`), via `postExecutionUnitOperations()` / `afterCommand()`. So the write rate on
  singletons that were already shared has gone from "rare" to "every inline command on every io
  thread". This is the exact shape §4 already records for `expired_keys`: #42 did not create that
  race, it raised its rate until the loss was measurable. **Nothing was measured here** — no attempt
  was made to provoke a loss or a torn read, and the correctness impact is stat-only for
  `duration_stats`; `also_propagate` and `pending_push_messages` are NOT stat-only and deserve the
  look. Worker-routed commands (GET/SET and the rest of the whitelist) never enter `call()`, so the
  rate is bounded by inline traffic.
- **`fakeRingAutoTune`'s gate has never opened** — it reads `cmd->calls` for GET/SET, which never
  enter `call()`. `use_slim` has therefore never been exercised. Documented, deliberately not fixed:
  fixing it OPENS a hot-path gate for the first time and needs its own A/B.
- **Duplicate knob binding** — `tomokv-reshard-sustain-ticks` and `tomokv-key-lb-sustain` write the
  SAME field with different defaults and ranges. Aliased both ways; the wide-range name can push the
  field past the other's validator. `!= 0` gates the whole key-LB Schmitt debounce, so setting the
  reshard-looking knob to 0 silently disarms key LB's anti-thrash. Safe today only by config-table
  ordering. Fix: keep `tomokv-key-lb-sustain`, delete the other, hardwire the −1 auto behaviour.

---

## 5. io_uring — DELETED 2026-07-29

**The entire io_uring backend is gone from this tree**: the send ring, the multishot-recv ring,
the provided-buffer ring, `HAVE_LIBURING`, the `USE_URING` make flag, the five `tomokv-io-uring*`
knobs and their `server.*` fields, the orphan-FATAL that policed them, and every read site in
`networking.c` / `server.c` / `iothread.c` / `server.h`. There is one network backend: epoll.
`make USE_URING=yes` is now an unrecognised variable that `make` ignores — it builds the same
binary as `make`.

**Why — it was measured, not assumed.** At `io7/ex1`, p1, `-d 32`, 200 connections:

* epoll: **821,824 ops/s**, 0.5% spread across reps, matching the recorded baseline to 0.1%.
* io_uring: **wedged in 3 of 3 reps** — each wedge immediately following a client-LB connection
  migration (4 workers spinning in userspace, io threads idle in `ep_poll`, accepts-but-never-
  replies; a livelock, not a deadlock).
* The single io_uring rep that happened to see zero migrations completed at **812,777 ops/s** —
  i.e. **~1.1% SLOWER than epoll**, inside the noise band.

So the path cost a livelock and returned no win. It was also never the deep design: `DEFER_TASKRUN`,
`SINGLE_ISSUER`, `register_ring_fd` and `RECVSEND_POLL_FIRST` appeared nowhere in `src/`, so what
was being carried was a naive port — precisely the shape the literature says is net-neutral on the
network path. Keeping it meant maintaining a second, unshipped, wedging data path across every
change to the reply and client-lifetime code.

**It is to be reimplemented from scratch later**, deliberately not resurrected from this history.
No scaffolding was left behind for that rewrite: a clean tree is the deliverable, and the old code
is recoverable from git history if it is ever wanted as a reference.

Two things the deleted code had established, worth carrying into any future attempt:

- **The migration contradiction was real and unresolved.** `tomoMigrateTest` refused connection
  migration under multishot-recv, while `tmMigHandoff` disarmed on the source and the adopt path
  re-armed on the destination — the exact dance the refusal called impossible — and the AUTONOMOUS
  client-LB path (`tmMigScan → tmMigStartClient → tmMigHandoff`) had no guard at all. The observed
  wedges all landed seconds after an autonomous migration. **A reimplementation must settle
  fd-ownership-across-threads before it writes a single ring op.** With the backend deleted, the
  refusal is gone too, so client migration is unconditionally allowed again (its pre-io_uring
  behaviour) and `controller_sweep`'s two migration cells are unblocked.
- **`SINGLE_ISSUER` was already blocked** by main-thread submits into another thread's ring
  (`iothread.c:168/:228` as it then stood). Any deep design must make the owning thread the sole
  issuer from the start.

**Note on the retired-knob trap.** The five knobs were deleted outright — entries *and* fields —
not left as fields seeded to 0. See the `tomoInitRetiredKnobDefaults` comment in `config.c`: a
field that outlives its knob falls to 0 by omission, which is how FLATSTORE was once silently
turned off while `correctness_suite` stayed 15/15. `knob_matrix.sh`'s io_uring cells were removed
rather than converted to `reject()` assertions, because keeping them would have kept the retired
names alive in the tree; the boot log remains the witness that nothing else was zeroed.

*This section is the only place in the tree, outside git history, where the deleted backend is
named. It is kept deliberately, as the record of what was removed and why.*

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

- **ONE WORKTREE CANNOT HOLD TWO MERGE STEPS (learned the hard way 2026-07-29).** Section 3 says
  "serially, one box acquisition each" — but *two* agents were run concurrently **in `clean-w`
  itself**, on the same branch. Three things that cost real work, all of them invisible until you
  look for them:
  1. The other agent's edits appear as *your* dirty tree. Anything that assumes "the tree is mine"
     is wrong.
  2. **Its changes were STAGED.** A `git commit --amend` intended to fix only a message therefore
     swept 15 of its files into this step's merge commit (8 files → 20, +904/−784). Caught, and
     rebuilt with plumbing: `git commit-tree <clean-merge-tree> -p … && git reset --soft`, which
     restored HEAD *and* handed the other agent's staged set back untouched. The recovered tree
     `e9f27d70` was independently confirmed correct because it equals what `git merge-tree`
     predicted before the merge ran. **Never `--amend` in a shared worktree; never trust
     `git diff --cached` printed by an earlier command in the same `&&` chain — it does not gate it.**
     Commit by explicit pathspec (`git commit -F msg -- <paths>`), which leaves other staged paths
     alone.
  3. The other agent's build therefore *included* this step's merge, so its own baseline is not the
     branch point it thinks it is.
- **THERE IS A STASH IN `clean-w` THAT SOMEONE MUST RESOLVE.** When this step started, `clean-w` was
  dirty with a 674-line, 9-file uncommitted io_uring knob-collapse — the very work §5 and §1 item 5
  described as "DONE"/"RESOLVED". It was **never committed and never pushed**: all five
  `createBoolConfig("tomokv-io-uring*")` entries were still present on both `HEAD` and
  `origin/2s-numa-stable-dev` at that moment, so anyone running preflight from the pushed branch got
  the old behaviour, and §1 item 5's `knob_matrix` `reject()` cells did not exist either. A merge
  cannot run against a dirty tree, so it was stashed, not discarded:
  `stash@{0}`, plus a patch at `$J/step3_cmdstats/PREEXISTING_uring_collapse_uncommitted.patch`.
  A second agent has since begun a *different, larger* rewrite of the same area (deleting the
  backend outright). **Do not blind-pop the stash into that** — reconcile or drop it deliberately.
  General lesson: "DONE" in this document has meant "done in someone's working tree" at least once.
  Check `git log`/`origin`, not the file you are looking at.
- **`withbox.sh` destroys the holder's identity.** `exec 9>"$LOCK"` **truncates**, so the moment any
  waiter opens the lock, the `pid=… cmd=…` line the holder wrote is gone and `cat /tmp/tomo_box.lock`
  returns empty. The §7 rule below that says to read it is half-broken; only the
  `fuser -v` + "does this `withbox.sh` still have a live `flock` child" test works. Fix is one
  character: `exec 9>>"$LOCK"`.
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
