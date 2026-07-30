# HANDOFF — 2026-07-30

Branch `2s-numa-stable-dev` @ `52674f834`, pushed, level with origin.

## READ FIRST

Four deep Codex reviews landed and **have not been read by anyone**. ~990 lines against the real
codebase, briefed with `$JOB/ARCH_BRIEF.md` so they already skip what we'd settled:

| file | lines |
|---|---|
| `$JOB/cw/rev-bugs/BUG_REVIEW.md` | 232 (+664-line companion) |
| `$JOB/cw/rev-dead/DEAD_CODE_REVIEW.md` | 291 |
| `$JOB/cw/rev-prefetch/PREFETCH_REVIEW.md` | 281 |
| `$JOB/cw/rev-alloc/ALLOC_REVIEW.md` | 187 |

Read `BUG_REVIEW.md` first — it was told not to pad, so its main section should be real defects with
triggering interleavings and a proposed discriminating test each. Speculation is in its own section.

## MERGE QUEUE — four Codex diffs, reviewed for size only, NOT read

All are clean `git worktree` forks off `52674f834`, so `git diff HEAD` in each IS the change (no
inherited dirt — that problem was batch 1 and is fixed).

Merge in this order. **Owner ruling: merge all EXCEPT `hotkeys`.**

### 1. `$JOB/cw/mbox` — LB-4, torn mailbox (+41/−36, server.c + server.h)
`tm_mig_mbox[].req_kind/req_dest/req_count` (`server.h:~2680-2682`) are plain ints with TWO
publishers (main via `tmRebalanceOntoNewIo`/`tmClientBalanceCron`/`tomoGrowBackSlot`, and an io
thread via `DEBUG TOMO-MODESHIFT`→`tomoMigrateTest`). An interleave yields one publisher's
`req_kind` with the other's `req_dest`/`req_count` — a torn request acted on as coherent. The
CONSUMER side was already a correct acquire/release pair and was told not to change.
**Acceptance:** verify the consumer contract is unchanged; publication is atomic as a unit.
Smallest and most contained — take it first.

### 2. `$JOB/cw/flipctx` — LB-3, flip gate TOCTOU (+91/−49, server.c + server.h)
`tm_flip_ctx` is simultaneously the flip state machine AND the "is a flip in progress" gate, plain
non-atomic, written by main (`tmFlipTick`) and any io thread (`DEBUG TOMO-MODESHIFT`, `debug.c:~952`).
**The key balancer defers entirely on it** (`reshardAutoTune`, `server.c:~11475`). Refusal checks at
`~17293/~17355/~19078/~19087` are plain loads. Asked for a single atomic CAS claim, no lock, and
explicitly told NOT to restructure the phase machine.
**GATE: this one needs the FULL FOUR-CELL FLIP CHECK, not just postmerge** — flip only just reached
within 1% of static in all four cells and this is the easiest thing to break:
`$JOB/flipcheck.sh` (io4/ex4 boot) and `$JOB/flipcheck71.sh` (io7/ex1 boot). Required:
p1→io7/ex1 within 1% of 831,649; p32→io4/ex4. Measure the STEADY-STATE window from the flip-ctl
HOLD lines, not the phase average — averaging in the convergence transient understates it.

### 3. `$JOB/cw/errstat` — errorstats rax race (+215/−29, server.c + server.h)
`incrementErrorCount` mutates the shared `server.errors` **rax** from EX workers with no
synchronisation — a concurrent `raxInsert`, i.e. structural corruption, not a lost counter. Told to
follow the per-thread-shards-merged-on-read pattern from the cmdstats fix (`8a24ab1b8`), NOT a mutex.
**Acceptance, and it already exists:** drive exactly 5000 errors. Pre-fix `total_error_replies` read
**4992** — 8 lost updates, which is what proves concurrency. Post-fix it must read exactly 5000.
Also check how it bounded the per-thread structure: errorstats keys are arbitrary strings, so
unbounded distinct keys × threads is a memory risk it was asked to address.

### 4. `$JOB/cw/iosat` — #59, io_sat signal (finished, diff not yet sized)
`busy_ewma_q4` is events-per-`aeProcessEventsIO`-pass (`server.c:~17246`), and that function burns
zero-timeout passes while `replyWorking > 0` — so it COLLAPSES exactly when an io thread spins
hardest. It measures batch size, not utilization. Proof: io7/ex1 reads `busy=0–5` at 1.85M ops/s
(p32) but `16–180` at 834k ops/s (p1) — the higher-throughput regime reads LOWER.
Told to mirror the workers' time-based `tm_busy_us`, state its per-pass cost against the ≤3% rule,
and say loudly if the signal's natural RANGE changed — the `dz(f0.25/b0.25)` deadzone constants were
tuned against the OLD signal.
**GATE: four-cell flip check, same as `flipctx`.** This changes what the controller steers on.

### NOT TO MERGE: `$JOB/cw/hotkeys` — LB-2 (+712/−157, **787 lines in hotkeys.c**)
Owner ruling: skip. I asked for per-command scratch to become thread-local following the
`execution_nesting` precedent; it returned a subsystem rewrite. The defect is real (one global
struct as per-command scratch for every io thread → OOB read, double free, `argv[pos]` indexing a
DIFFERENT client's argv) but it is **dormant until `HOTKEYS START`**. Re-run with a tighter brief
rather than reviewing 787 lines to fix a dormant race.

## PROCEDURE PER MERGE

```
cd $JOB/cw/<fork> && git diff HEAD > /tmp/<fork>.patch
cd $JOB/clean-w && git apply --3way /tmp/<fork>.patch
# READ the applied diff. Do not merge unread code.
make -j8                       # zero new warnings; kvstore.c:73 is pre-existing, prove it
# run the acceptance named above — SEE it fail on the pre-fix binary or it proves nothing
tools/preflight/postmerge.sh src/redis-server [acceptance-script]
# push on green, with the acceptance evidence AND the four cells in the message
```

`postmerge.sh` = acceptance + io4/ex4 p32 d32 + io7/ex1 p1 d32, ~4 min. Reference cells:
p1GET 826,877 · p1SET 817,393 · p32GET 7,943,860 · p32SET 6,852,385. Worse than −4% ⇒ revert.
**A missing acceptance script is reported UNVALIDATED, not passing — that is by design.**

**CONTENTION:** count `ps -eo args= | grep -c '[c]odex exec'` before ANY timing run. A gate came
back with all four cells negative on a config-table edit that touches no data path — physically
impossible as a regression, so it was measuring Codex CPU. Implausibility is the tell.

## STILL OPEN

- **#57** arm-race test does not discriminate — the PRE-FIX binary passes both arms, so the merged
  reshard teardown fix is uncertified. `cutover_no_coord=1` appeared and passed anyway because that
  counter is reported, not asserted. Few-line fix.
- **debug-reload** merged then REVERTED — FLATSTORE residual crashes 8 runs in 10 (filed as "~1 in
  3"). Root cause understood: nothing re-checks `FLAT_RZ_COPYING` once past QUIESCING, so a region
  opening during COPYING is unguarded. Do not merge anything that crashes 8/10.
- **h2-fence** merged then REVERTED — "the fence is right, one initializer is not"; SEGVs on every
  real client teardown. Design is the owner's specified protocol and works. Its throughput cells
  (`h2_thr.py`, A and B still serving NON-migrating buckets through a cutover) have NEVER RUN.
- **`hotkeys`** re-run with a tight brief.
- **Full preflight has never gone green.** `$JOB/ee451_run.log` is still 0 bytes.
- Task list #26/#31/#36/#40/#41/#47/#54 unassessed — **check the code before starting any of them**,
  four "pending" items turned out already done this session.

## RULES THAT COST US TO LEARN

- **Codex does the work; Claude coordinates, reviews, tests, merges.** `codex exec --sandbox
  danger-full-access -m gpt-5.6-sol -c model_reasoning_effort=xhigh`, cwd = a throwaway
  `git worktree add --detach`. Never `cp -a` a dirty tree. Codex NEVER builds, tests, or starts a
  server — testing is ours, and a Codex-started server would contend with the gate.
- **One server at a time. WAIT, NEVER KILL.** Killing to make room destroyed more work this cycle
  than any product bug. If the box looks idle but jobs are queued, the holder is probably a leaked
  server holding `withbox.sh`'s lock fd 9 — look for oddly-named binaries; `ppid=1` with no command
  is safe to clear, anything with a live parent is not.
- **Verify before implementing.** Grep the CODE, not the task list or memory — and search the
  BEHAVIOUR and call sites, not the feature name. A `SSO`/`inline_buf` grep missed an
  implementation that existed under other naming and I declared it "confirmed not done".
- **A killed server prints `Totals … 0.00`, not nothing.** Reject `''|0|0.0|0.00` as INVALID.
- **Sanity-gate every number.** Ask whether the change COULD cost what you measured.
- **Prove the test discriminates** — see it fail pre-fix. Several suites here had never executed at
  all, and one "15/0" was returned alongside an 11-minute hang.
- **If a fix needs a second guard to make the first safe, the fix is wrong.**
