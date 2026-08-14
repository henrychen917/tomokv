---
name: thredis-ab-harness-traps
description: "A/B harness traps that faked a -15% regression, plus instr/op as the verdict metric on this drift-prone box (NOTE: that characterisation is the LAPTOP; the 7700X is ±2% exclusive — [[thredis-box-noise-truth]])"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

On 2026-07-25 a full night of A/B numbers was invalidated by harness bugs, not code. The traps and
the fixes now baked into `ab2.sh` / `comp_inter.sh` (job dir `fd085c8e/tmp`):

1. **A renamed binary defeats `pkill -x redis-server`.** Builds were copied to `bins/base` and
   `bins/retirenode`, so the process `comm` became `base`/`retirenode` and every teardown matched
   NOTHING. Servers leaked cell to cell; by rep 2 four fought over cores 0-7. Fix: keep the file
   named `redis-server` inside `bins/<tag>_d/`, and ASSERT `pgrep -x redis-server | wc -l == 1`
   before every measurement.
2. **`comm` truncates at 15 chars** — `pkill -x memtier_benchmark` matches nothing; use
   `memtier_benchma`.
3. **Two harness instances** append to one TSV and bind the same port (seen: duplicate rows at
   ops=0). Both scripts now take an `exec 9>/tmp/<name>.lock; flock -n 9` single-instance guard.
4. **`pgrep -f <script>` / `pkill -f <script>` match the caller's own shell** — killed my shell
   mid-command (exit 144) and produced phantom "2 instances still running" counts. Kill/count by
   exact `comm`, or walk `/proc/*/cmdline` excluding `$$`.
5. **`#!/usr/bin/env bash` makes `comm` = `bash`**, so `pgrep -x <script>.sh` reports DEAD for a
   living script. Not interchangeable with `#!/bin/bash` for process matching.
6. **Backgrounded loops die with their launching tool call** unless `setsid nohup ... < /dev/null &`
   + `disown`.
7. **A `timeout`-killed trace run orphans its server**, which then contends with the next launch.

**Verdict metric: instructions/op, not ops/s.** The same binary measured 7.98M then 5.64M p32 GET in
one session (~30% swing) on this thermally-throttled laptop. `ab2.sh` perf-stats the server over each
window and derives instr/op; it is immune to frequency drift, and it cross-checks throughput — on the
retire-node change instr/op −2.52% and ops +2.57% agreed to 0.05pp. Also log effective GHz per cell:
flat GHz across cells is the evidence that thermal drift did NOT contaminate the run.

The tell that exposed trap 1: a SET-only change appeared to cost −15% on GET. GET retires nothing, so
that is mechanically impossible — implausibility, not the number itself, is what caught it. See
[[thredis-sanity-gate-benching]] and [[thredis-benchmarking-methodology]].

## instr/op is POLLUTED on this fork — qualify the "instr/op is the verdict metric" rule

Measured 2026-07-28: `perf stat -e instructions -p <server-pid>` over a fixed op count reported
**~15,000 instructions/op for a plain GET** — roughly 3-5x what the command actually costs. Cause:
the EX workers and IO threads BUSY-SPIN waiting for work (`exPauseCpu()`, server.c:15154, plus the
`tomoWkrTrylock` spin at :7050), and every spin iteration retires instructions. So a process-wide
instruction count is partly a WALL-CLOCK PROXY: it grows with idle time, not just with work.

Consequences:
- instr/op is still the right metric for **allocation-count** work (allocations are unambiguous), and
  the csGroup/alloc numbers stand.
- It is NOT clean for pricing a small per-command addition (a clock read, a TLS access). The F-clock
  latch measured +0.37% GET / +1.66% SET, both **below the 3.8-8.1% within-arm spread** -- the metric
  bounded the cost rather than measuring it.
- To use it at all, run at SATURATION so spin time is minimal, and treat any delta smaller than the
  within-arm spread as "not resolved", never as a result.
- For throughput questions, measure **ops/s** directly ([[thredis-three-regime-testing]]).

Also from that run: a round-1-only read said +2.1%/+2.2%; the full ABBA rotation REVERSED it. One
round is not a measurement on this box even with a drift-resistant metric.

## A killed server scores 0.00, NOT empty — the silent-invalid trap

2026-07-28, the 32-cell IO/EX scaling sweep: **7 of 32 cells came back `0.00` ops/s.** The harness
guarded the wrong failure shape — it wrote `DEAD` only when memtier's output was *empty*
(`${o:-DEAD}`), but a server killed mid-run still lets memtier print a `Totals` line reading
**0.00**. So `0.00` entered the table as if it were a measurement, and rendered as a legitimate-
looking `0.00M` cell. In a *scaling* table that is worse than a blank: it reads as "this thread
config cannot serve", which is a false architectural finding, and `io1ex7` (5 of 8 cells invalid)
would have been reported as a collapsed configuration.

Two rules from this:
- **Guard the value, not just its absence.** Any bench cell must reject `''|0|0.0|0.00` as INVALID.
  A metric that can be produced by failure must never be allowed to look like data.
- **Every bench binary gets a private `comm`.** The kill comes from OTHER sessions running
  `pkill -9 -x redis-server`, which matches on `comm` and ignores the advisory box lock — see
  [[thredis-preflight-contract]]. Staging as e.g. `redis-tsw`/`redis-corr`/`redis-rs` makes a run
  unkillable by name-based reapers. Note this INVERTS trap 1 above: trap 1 said keep the file named
  `redis-server` so your own teardown matches. Both are satisfied by a unique name **plus** a
  teardown that kills that same unique name — never the shared one.
- Confirmed blast radius: ~100 scripts in the job dir and 13 shipped `tools/preflight/*.sh` still
  reap the shared name, so any of them running concurrently can void another session's run.
  `threadsweep.sh` is fixed (stages `redis-tsw`); the preflight suite is only partly converted
  (`reshard_suite`→`redis-rs`, `correctness_suite`→`redis-corr`).

## Trap 4 — an unbounded `redis-cli` HANGS the harness instead of failing it (2026-08-03)

`redis-cli` against a **wedged event-loop thread** never returns. Every boot-wait loop and liveness
check in the preflight tree was written as a bare `$CLI -p $PORT ping`, so the exact failure those
suites exist to catch — a dead event loop — made the suite hang forever rather than report FAIL.
No verdict, and the whole time budget gone. **46 sites across 21 scripts**; all now `timeout 2`.

A test that hangs is strictly worse than one that fails: a failure is data, a hang is nothing. Bound
every external command that talks to the server under test.

Corollary that cost a 5-minute run before I spotted it: this also applies to *my own* ad-hoc probe
scripts, and any such script needs a `trap cleanup EXIT INT TERM` — when the outer harness times out
and SIGTERMs the script, a trap-less script leaves the server running and the next arm measures a
contended box (or refuses to start on a busy port).

## Trap 5 — `pgrep -f` self-matches WATCHERS too, not just killers (2026-08-03)

The standing rule was "never `pkill -f <pattern>` — it matches the caller's own shell". The same
defect in the *watching* direction cost ~8 idle hours: a driver script waited with

    while pgrep -f 'preflight.sh src/redis-server'; do sleep 30; done

while a concurrently-armed **Monitor** had that exact string inside its own command line. `pgrep -f`
matched the monitor, so the driver waited forever for a process that was really its own observer.
The box had been clear the whole time. Stopping the monitor released it instantly.

**Rule: `pgrep -f`/`pkill -f` are unsafe whenever ANY other live process — your shell, a monitor, a
sibling agent, a logging wrapper — can contain the pattern as text.** Prefer `pgrep -x <comm>` on a
private binary name, a PID captured at launch, or a marker/lock file. If `-f` is unavoidable,
exclude self and known watchers explicitly.

## Trap 6 — the CANDIDATE BINARY was the base, from git cleanup corrupting the worktree (2026-08-12)

A lockdiet battery came back +0.5% with `foreign_engagements=MISSING`. Root cause: earlier
`git stash` panic-cleanup ran `git checkout <base-sha> -- .` inside the candidate worktree, which
REVERTS every tracked file to the base's content and stages it; a subsequent `git checkout <cand-sha>`
(detached) did NOT overwrite the modified tracked files, so `make` compiled the BASE with the
candidate's changes gone (−337 lines). The A/B was base-vs-base = pure noise. The `git status`
−337-line diff, run AFTER the battery, was the hard proof. Rules:
- **Before building ANY candidate, run `git diff --stat HEAD` and confirm it matches the expected
  change size.** A clean `git status` is the pre-build gate, not an afterthought.
- **Redis `build=<hash>` is git-SHA-derived, NOT working-tree-content-derived** — it showed the same
  `1c79494` for the corrupt and the clean tree, so the version stamp does NOT catch a dirty/reverted
  tree. It is not a content witness; only `git diff HEAD` is.
- **Never `git checkout <sha> -- .` as cleanup** — it silently reverts the worktree. Use
  `git reset --hard <sha>` (unambiguous, whole-tree) when you want a known state.
- **Never bare `git stash drop`** on this repo — the stash stack is SHARED across all worktrees
  (per the environment rules); I dropped a 2-week-old foreign stash by reflex and had to
  `git stash store <sha>` it back. Restore-what-you-don't-own.

## Trap 7 — harness hardcoded the thread config the cells claimed to vary (2026-08-12)

The lockdiet battery's `boot()` hardcoded `--tomokv-thread-io 4 --tomokv-thread-ex 4` while the cell
table passed "io71 7 1"; the io/ex never reached the server, so the io7ex1 rows were io4ex4 repeats —
and io7ex1 is exactly where an owner-lock-per-command change shows LARGEST (highest per-worker cmd
rate). **Assert the server booted the config the cell asked for** (scrape INFO threads / the boot
args), or the discriminating cell silently becomes a duplicate of the easy one.

### The through-line for all seven traps
Every one of them **produced a plausible non-result instead of a failure**: a vacuous oracle that
passed a dead server, unbounded `redis-cli` that hung, a renamed binary that made `pkill -x` match
nothing, a `wait` on a live child, a watcher matching itself, a base binary wearing the candidate's
name, and a discriminating cell silently collapsed to the easy one. None threw an error; all made a
broken thing look like a working thing. When a harness result is "nothing happened" OR a suspiciously
small/clean delta, suspect the harness before believing it — and for perf specifically, the
`MISSING`/`0.5%-noise` shape is the tell that the two arms may be the same binary (trap 6).
