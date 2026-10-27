# AT4.12 proof and measurement request

## at412

Branch `cx-at412`, PRE `7ae703778e854a7b76945af5792a5ec5e88061a6` (cx-execindex). Final
production source: `9c265b209`; evidence and report commits follow it on the branch.
All lane processes used CPUs 48-63 (builds `-j16`); correctness servers 48-55, drivers 56-63;
ports 20200-20299. No push. No performance run, no load generator for measurement and no full
`tests/gate.sh` iteration: every gate number below is a `GATE_ONLY_JOBS` partial ledger.

Specification: `round4-read/at412-escalation-review.md` (holes H1-H6, conditions C1-C8, FIFO
§3, cleanup §4, cost §5, plan §6, D4′ §7). AT4-WOUND-1 is owned by woundfix and was not fixed
here; escalated scripts do not depend on that window (H4/C5 row below).

### Summary

| Item | Result |
|---|---|
| WIP `io_loop.h` edit (1150ec42d) | Semantics **kept** (7ea849660); code **relocated** out of io_loop.h (02bc7ba82). io_loop.h and reorder.cc now differ from PRE only by the design's cold resume arm |
| Holes H1-H6 | All six closed. The H1 and H3 cycles appear in the serverless owner fixture only with non-compliant inputs. The H2 negative control hangs BGSAVE. S1 reproduced on PRE (12/12 legs) and fixed |
| Holes found in the design | Two: the FIFO stale member (fixed, with a negative control) and the §5.1 cost claim for `xshard_prepare`/`xshard_execute` (counterexample in "Zero-cost proof") |
| Directed rows T1-T16, T11a, T11b, owner | See "Directed rows" |
| Refusals, af5 shape, final POST | 6,400/6,400 OK per command and 64/64 in the cut window, in every leg. PRE: 3,484-3,846 TRYAGAIN per 6,400 and 32-40 BUSY per 64 |
| Non-script instruction counts (48 command scopes) | 24 scopes exactly PRE-equal (every GET/SET/INCR scope). MGET/MSET differ **only in `xshard_prepare`**: 20 scopes execute fewer instructions than PRE, 4 execute more (db0 MSET 1s: +16 or +17 per call, +0.10%/+0.15%). Not zero |
| FIFO admission cost | +34 (normal namespace) / +40 (db0) instructions per cross-shard script admission |
| DQ / DF | DQ=+18, DF=+18. EXPECT constants unchanged |
| Arms (SHA-256) | PRE `decd26ff…`, POST `3c9ea2e6…`, POST-layout `d22a3b7c…`, PAD-A `a04975a6…` |

### 1. What was implemented (D4′)

| Piece | Where | What it does |
|---|---|---|
| Hand-off at every conflict exit | `scatter_engine.inc` (`xshard_complete_script`), `script_escalation.inc` (`script_escalate_handoff`) | The certification-CAS exit and the VALIDATE exit (after 8 restages) and the APPLY-conflict exit (at once) unpin, then hand off. No TRYAGAIN text remains in the script engine |
| Escalated attempt E (kind-2 unit) | `script_escalate_redispatch`, `script_group_prepare` | The IO lane re-prepares the command with `force_atomic`, attaches a `TxnGroupAttempt` before the first wave, draws or inherits the age, transfers the credit, reopens the apply window and posts wave 1 |
| E's waves | `ScriptPhase::Place` + cold `script_group_read`; RUN unchanged; APPLY under claims | PLACE+READ: `txn_group_read_prepare`, then a read at UINT64_MAX. The RUN wave runs on the workbench as before. APPLY validates nothing: the read-set bits are cleared because the claims proved exclusivity |
| Decision | `script_group_final` | Reserve, CAS 0 → ticket and publish in one coordinator step. A lost CAS aborts the process (falsifier). E never certifies |
| FIFO admission (replaces BUSY) | `xshard_prepare` script branch, `script_window_*`, `txn_group_prepare` | Per-IO admission byte in `MultiRetryLane`: bits 0-6 count live optimistic activations (≤4), bit 7 = FIFO present. Waiters keep their frame unconsumed and the atomic-backpressure flag set. The cold resume arm grants the head. Scripts jump over the general 8-cut window |
| S1 / H2 apply windows | `xshard_complete_script_final`, hand-off, redispatch | Owner-side close at every script Final; EX-side close at the hand-off; reopen at redispatch |
| Counters | `t_server.cc` INFO | `script_crossshard_window_waits`, `script_escalations`, `script_escalated_commits`, `script_waiters_peak`, `script_stage_watch_tasks`; `script_crossshard_window_refusals` stays and must read 0 |
| Test hooks | `DEBUG SCRIPT-APPLY-DEFER`, `SCRIPT-ESCALATE-FORCE`, `SCRIPT-STAGE-WATCH`; SCRIPT-STAGE-DEFER re-armed per restage | Armed at phase launch or read where they are decided (script-only code), never in the shared deferral gate |

### 2. The WIP `io_loop.h` edit

| Question | Answer |
|---|---|
| The edit at the stop (1150ec42d) | `close_client`: `script_window_forget()` moved from inside `if (!c->closing())` to every non-dead entry |
| Correct? | **Yes. Kept** (7ea849660). QUIT, CLIENT KILL of self and the parse-error/receive-limit arms call `mark_closing()` first, so their teardown reaches `close_client()` with `closing()` already true. The old placement skipped the forget for them. A connection can still be a FIFO member there: its queued EVALSHA frame may have been consumed without admission (NOSCRIPT after SCRIPT FLUSH, an ACL/OOM refusal), and it then sends QUIT. It was freed while the per-IO FIFO still held its pointer, and the next head scan read freed memory |
| Final form | Relocated (02bc7ba82) into `multi_close_entry` (cold, called by `close_client` on every non-dead entry before `mark_dead`) and `command_client_migration_extract` (source IO, before the hand-over). Reason: `close_client` is inlined into `parse_and_dispatch`; the edit changed that hot body |
| io_loop.h / reorder.cc vs PRE now | Only the design's resume arm: `if (c->atomic_backpressure()) script_window_resume(...)` (§3.6) |

### 3. Holes H1-H6 and conditions C1-C8

| Hole / condition | Closed by | Evidence |
|---|---|---|
| **H1 / C1** age clock | `script_escalate_redispatch`: `age_ns = now_ns()` (CLOCK_MONOTONIC), `age_io` = IO, `age_seq = ++multi_retry_lane(io).age_seq`, drawn on the IO at the first escalated dispatch (`age_ns = 0` at the hand-off means "draw at redispatch"); later attempts inherit the triple | owner fixture: the E → V → W → E cycle appears only with a realtime-derived age (non-compliant control); with the production triple no cycle (8 legs) |
| **H2 / C7** window across the IO lane | EX-side `atomic_apply_close` at the hand-off; `atomic_apply_open` at redispatch; owner-side close at every script Final (S1) | T11a H2 schedule: BGSAVE while a forced escalation meets a rival write → OK. Negative control (hand-off close removed, `docs/at412/h2-negative-control/`): BGSAVE never finishes |
| **H3 / C2** bracket while placing | E never certifies and holds no ticket while placing; the ticket is reserved, CASed and published at the decision (`script_group_final`) | owner fixture: the F2-mirrored cycle appears only when the bracket is held while placing (non-compliant control) |
| **H4 / C3** no sidecar | `script_group_prepare` attaches the `TxnGroupAttempt` (and `kGroupAttemptRef`) before wave 1; doom visitors exempt group-attempt states | T9 (80 escalated scripts against blind MSET groups: no torn generation), T7, T8 |
| **H5 / C8** FIFO predicate | the admission byte counts optimistic script activations only; escalated attempts take no slot and register no cut (the temporary prepare cut is unregistered before dispatch) | T3: four cross-owner MGET cuts held, EVAL answers without waiting (PRE: BUSY). T2: more than 4 cuts, zero refusals, waits counted |
| **H6** APPLY-time exit | the APPLY-conflict exit hands off at once | T4 (APPLY partial: escalations +1), T6 storm (zero TRYAGAIN) |
| **C4** order of work | PLACE → read only after placement; RUN only when the attempt is Executing (otherwise abort); APPLY waits on nothing foreign | owner fixture, T13 |
| **C5** wounds only while placing | `script_group_read` re-checks `Wounded` before and after `txn_group_read_prepare` and completes the cancellation itself, so a wound observed before the wounder's epoch store cannot leak into a committed attempt. This is the script-side guard for the AT4-WOUND-1 window; woundfix's code is untouched | owner fixture `wound_window`; no failure in any row is attributed to AT4-WOUND-1 |
| **C6** one op, one reply | the hand-off returns Waiting; the ROB op stays in flight and the barrier is held | T1/T12 reply identity; T15 disconnect leg |
| **S1** SAVE wedge | owner-side close at every script Final | PRE: SAVE never returns in 12/12 legs (`docs/at412/pre-T11a/`); POST: T11a passes |

### 4. Holes in the design found while implementing (counterexamples)

| # | Hole | Counterexample | Disposition |
|---|---|---|---|
| A | **FIFO stale member.** §3.2 keys membership by connection only. A waiter whose frame is consumed without admission (EVALSHA → NOSCRIPT after SCRIPT FLUSH, an ACL or OOM refusal at re-parse, arena allocation failure after the grant) stays in the FIFO. As head it blocks every later waiter on its IO until the connection sends another script or closes | `tests/at412_owner.cc` stale-head check; negative control without pruning fails at that check (`docs/at412/fifo-stale/`) | Fixed (bd82e6ebd): each member records its frame (ROB dispatch id); stale members are pruned at the head scan, and a member arriving with a new frame re-queues at the tail |
| B | **§5.1 "zero added instructions" for MGET/MSET.** The table says `xshard_execute: none` while §6.2 places the escalated branch in the owner Pin case (2624-2644). GCC inlines `execute_script_phase` (its IPA-SRA clone, called once) into `xshard_execute`, so any edit there re-allocates registers in the MGET/MSET body. The admission edit in `xshard_prepare` does the same | 49 measured source shapes (`docs/at412/budgets3/shape-search.json`). Even deleting the script branch from `xshard_prepare` entirely moves MGET/MSET counts by up to 6 instructions per call (variant `z0`) | `xshard_execute`: solved (escalated wave = `ScriptPhase::Place`, cold callee: counts PRE-equal in every scope). `xshard_prepare`: not removable; residual measured below |

Smaller deviations from the site table (§3.6/§6.2), all script-only:

- **Slot count site.** In `txn_group_prepare`'s script return, not by a call in prepare's
  script-only block. It is the next script-only point and comes after the credit admission, so a
  credit refusal still leaves a granted head in place. The FIFO records its granted head and pops
  it there.
- **Release site.** The EX releases at `script_snapshot_done` (every optimistic Final and the
  hand-off), the lane at redispatch, `xshard_abandon_unpublished` before publication. The IO folds
  releases when it next needs a slot or resumes a waiter. The `assemble_final` release (§3.6) was
  dropped because any call there changed that body.
- **Test hooks.** SCRIPT-APPLY-DEFER arms the existing fan-out park (lead = coordinator) at APPLY
  launch. SCRIPT-STAGE-WATCH counts READ launches. SCRIPT-ESCALATE-FORCE is read where it is
  decided. §6.2 armed them at prepare.
- **Residual.** A script that is admitted and then abandoned by the IO dispatch (task queue full)
  has already been popped from the FIFO; it re-queues at the tail.

### 5. Directed rows

DIRECTED-ROWS-PLACEHOLDER

### 6. Deviations found (pre-existing, labelled)

Each was reproduced on PRE (`build/at412/pre/tomokv`) with the same result as POST, so none is
caused by this lane. None involves AT4-WOUND-1.

| Label | Deviation from Redis 7.4.10 | PRE | POST | Evidence | Rows that tolerate or report it |
|---|---|---|---|---|---|
| XS-NOTIFY-1 | Cross-owner scripts publish no keyspace events and no CLIENT TRACKING invalidations (single-owner scripts do) | same | same | `docs/at412/deviations/probe-{redis,pre,post}.json` | T16 accepts it only all-or-nothing (no partial event set) |
| XS-OOM-1 | A cross-owner EVAL refused by maxmemory omits Redis's ` script: <sha>` suffix | same | same | probe JSON (`two_key_eval_oom`) | T14 compares the message without the suffix and records the deviation |
| XS-OOM-2 | DEL under maxmemory answers `ERR out of memory` while script intents are live | same | same | `oom2-shebang.txt` | T14 deletes before setting maxmemory |
| XS-SHEBANG-1 | `#!lua flags=…` shebangs do not compile (`EVAL`/`EVAL_RO`) | same | same | `oom2-shebang.txt`, `shebang_probe.py` | T16 uses plain EVAL_RO bodies |
| XS-SHUT-1 | SHUTDOWN NOSAVE with cross-owner scripts in flight aborts in `atomic_destroy_pending` → `atomic_remove_unit_intents` (flatstore_atomic.inc:232) | rc −6, 2/2 | rc −6, 2/2 (EXEC/RENAME rc 0) | `shutdown-abort.txt`, `shutdown-abort-pre-stack.txt` | T15 asserts a clean exit and therefore fails on it |
| SNAP-STORM-1 | BGSAVE loop under a unit storm can stall: `snapshot_cuts_armed == rdb_saves`, units stuck, plain writers progress, resolves on disconnect. Reproduced with EXEC+writers and no scripts | full storm 4/7 stalled; EXEC+writers 2/5 | scripts+writers 4/5; EXEC+writers 0/5; full 1s 9/11, 2s 2/5 | `bgsave-storm-stall.json` | T11b asserts progress and fails when it stalls. Mechanism not isolated |
| FLIP-MULTI-1 | A connection that ever ran MULTI keeps its MultiSession, so it is never FLIP-transferable (`migration_protocol_idle`) | same | same | T10 notes | T10 runs scripts + writers with a hold around each FLIP; a full EXEC storm refuses every FLIP on PRE and POST |

### 7. Assertion flips (§6.5)

| Location | Before | After |
|---|---|---|
| `tests/txnorder.py` | `SCRIPT_REFUSALS` allow-list | Any RespError fails; the report keeps `{TRYAGAIN: 0, BUSY: 0}` |
| `tests/xscript.py` allow-list | dict of retryable refusals | removed |
| `tests/xscript.py` opposite-order loop, script/MSET race | refusals counted | refusals are errors |
| `tests/xscript.py` `cut_window_refusal` | expects BUSY | renamed `cut_window_fifo`: no BUSY, `script_crossshard_window_waits` must rise, every waiter gets its reply |
| `tests/mode_equivalence.py:204-210` | synthetic BUSY negative control | kept |
| `tests/mode_equivalence.py:291` | refusal counter must stay 0 | kept |
| `docs/wave5d/check_refusals.py` | `KNOWN` = tolerated | `KNOWN` = must never appear |

### 8. Zero-cost proof for non-script commands

**Command scopes.** Serverless probe (`tests/txnorder_command_scope.cc` through the derived
`tools/at412_scope.py` instrument): GET, SET, INCR, MGET, MSET; batch 1 and 32; 1s and 2s; both
physical namespaces (normal, db0); MSET at atomic 0 and 1. PRE = 7ae703778 objects, POST = the
final objects. Counts are instructions executed inside named production routines between the
scope markers, with the clock stubbed. They are not rates.

| Command scope (both namespaces, both modes, batch 1 and 32) | PRE vs POST instruction count | Where |
|---|---|---|
| GET, SET, INCR (24 scopes) | **equal** in all 24, per function too | — |
| MGET normal (4 scopes) | POST **fewer**: −11 per call (−0.107%) | `xshard_prepare` only |
| MGET db0 (4) | POST **fewer**: −10 per call (−0.096%) | `xshard_prepare` only |
| MSET normal, atomic 0 / 1 (8) | POST **fewer**: −8 / −7 per call (−0.07% / −0.04%) | `xshard_prepare` only |
| MSET db0 2s, atomic 0 / 1 (4) | POST **fewer**: −6 / −7 per call | `xshard_prepare` only |
| MSET db0 1s, atomic 0 / 1 (4) | POST **more**: +17 / +16 per call (+0.153% / +0.097%) | `xshard_prepare` only |

Full table: `docs/at412/instructions/comparison.json` (48 pairs). Every other function on these
paths executes PRE's count exactly: `xshard_execute`, `xshard_task_should_defer`,
`xshard_complete_impl`, `assemble_final`, `xshard_retire`, the `ScatterState` constructor and
every handler.

**Identity audit** (`docs/at412/identity/`, ccfix canonicalisation):

| Body set | Equal / total | Changed bodies |
|---|---|---|
| ccfix hot bodies | 1,274 / 1,378 | the 104 `flush_ready`/`r7_flush_ready` instantiations: the cold resume arm (§3.6) |
| command handlers | 1,224 / 1,232 | `cmd_info`, `cmd_debug_impl` (new INFO fields and DEBUG hooks) |
| extended hot list (adds `cmd_incr`, `cmd_xshard_only`, `xshard_*`, `assemble_final`) | 1,328 / 1,448 | resume arm (104); `xshard_complete_script` (script-only); `xshard_complete_impl` (only the script tail-call target); `xshard_prepare` (admission branch); `xshard_execute` (the Place case; counts equal) |
| GET/SET/INCR/MGET/MSET handler bodies | 24 / 24 | none |

**Why `xshard_prepare` is not zero (classification: IMPLEMENTATION COST, compiler register
allocation in a shared body).** The script admission must live in `xshard_prepare`: it is the
only place that can return Backpressure for a script. Any change there moves GCC's register
allocation for the whole function. The search (`docs/at412/budgets3/shape-search.json`) measured
49 shapes on the batch-1 cells:

| Variant (shape of the script branch) | MGET/MSET batch-1 deltas | Note |
|---|---|---|
| PRE `xshard_prepare` text inside the POST unit (diagnostic, not functional) | 0 in every cell | the rest of the unit does not perturb `xshard_prepare` |
| No script branch at all (diagnostic, not functional) | −6 … +4 | deleting code moves the allocation too |
| Design shape, call in the script-only block (PRE of this session) | −19 … +30 | |
| Final: design else-if, slot counted in `txn_group_prepare` | −11 … +17 | smallest positive maximum of the functional shapes |
| Inline fast path + cold slow path, strict-identity variant, argument-slot tricks, early check at classification | up to +78 | worse |

The IPA (inlining) decisions of every PRE function in the unit are budget-insensitive in the
swept range; the budgets were re-derived anyway (`docs/at412/budgets3/sweep.json`): xshard.o
150700, db0 xshard.o 149450.

### 9. FIFO admission cost per cross-shard script

| Scope (EVAL, 2 keys on 2 owners, `tests/txnorder_command_scope.cc`) | PRE | POST | POST minus PRE | Breakdown |
|---|---:|---:|---:|---|
| EVAL-ADMIT (`xshard_prepare` only), normal | 7,987 | 8,021 | **+34** (+0.43%) | `script_window_admissible` +14, `script_window_admit` +27, prepare −7 |
| EVAL-ADMIT, db0 | 7,991 | 8,031 | **+40** (+0.50%) | +14, +27, prepare −1 |
| EVAL activation scope (prepare, first wave, retirement), normal | 10,625 | 10,684 | +59 | admission +34; S1 owner-side close wrapper +28; `xshard_destroy` −8 (window already closed) |
| EVAL activation scope, db0 | 10,580 | 10,643 | +63 | same |

Values are per activation at atomic 1 (atomic 0 is identical). The slot release at Final
(`script_window_release`, a flag test and one atomic add) lies outside the activation scope as
the probe drives it; it was not measured. The design estimated +10 to +12 for the FIFO; the
measured +34/+40 includes two call frames. Escalation itself adds nothing to an uncontended
script (every escalation edit replaced a TRYAGAIN tail).

### 10. Gate runs

GATE-RUNS-PLACEHOLDER

### 11. DQ / DF

`job_at412` adds 18 rows (T1-T16 with T11 as T11a/T11b, plus `at412-owner`), all collected
before the quick-tier exit: **DQ=+18, DF=+18**, on top of execindex's +2/+2. `EXPECT_QUICK=798`
and `EXPECT_FULL=815` are unchanged in this branch; the maintainer moves them to 800/817 for
execindex and to **818/835** with at412. `build/at412-owner` joins `job_production_units` (built
and `make -q`-checked there) and the `debug-*`/`txn_group_*` dependency list.

### 12. Arms

| Arm | Path | SHA-256 | What it is |
|---|---|---|---|
| PRE | `build/at412/pre/tomokv` | `decd26ffb38c69f5cf96f7b9bdc961113049d4b67d8cce142d0f80efbb61bb42` | cx-execindex 7ae703778, built from `build/at412/pre-source`, `make -q` fresh |
| POST | `build/at412/POST` (= `build/tomokv`) | `3c9ea2e65f351e7cbf203c203a2819d301fab2bb5c109b65df2013555c795eaa` | production source 9c265b209 |
| POST-layout | `build/at412/POST-layout` | `d22a3b7c1c0ceb0be19bfb937e369fb055fda90407c6ec7cd72d8b70c01af987` | POST objects + symbol-isolated PRE objects; executes POST |
| PAD-A | `build/at412/PAD-A` | `a04975a6b790852afd8187c51ba06a0b6229d3dc559807f8dcf4e6c913edd886` | POST-layout with `main` jumping to PRE (5 bytes): PRE behaviour in POST-layout's exact image |

`docs/at412/arms.json`, `docs/at412/pad-a.json` (sections and symbols match, 5 changed bytes),
`docs/at412/pad-smoke.json` (16/16 correctness cells on POST-layout and PAD-A: 1s/2s × uring/epoll
× 1/16 databases).

### 13. Merit request (maintainer; this lane ran no measurement)

| # | Cell | Arms | What it decides |
|---|---|---|---|
| 1 | The **14 generic cells** (the standing generic-14 matrix) | PRE vs POST, ABBA; and POST-layout vs PAD-A (layout control) | Non-script commands. The instruction residual is in `xshard_prepare` only (−11 … +17 per MGET/MSET call); expect noise. A loss here is classified IMPLEMENTATION COST (register allocation), not MECHANISM |
| 2 | **EXEC merit** (`calib/exec-merit.py`, its 8 cells) | PRE vs POST | EXECs now share claims with escalated scripts; the uncontended EXEC path is untouched |
| 3 | **Contended-script throughput**: the T6 storm shape (EXEC + WATCH + plain writers + two-owner scripts on one key pair) at a fixed duration | PRE vs POST | Report completed scripts/s, EXEC/s, writers/s and refusals per arm. PRE answers part of its scripts with TRYAGAIN (af5: 54-60% at pipeline 16); POST answers all of them. Count only OK replies as throughput |
| 4 | Optional: uncontended two-owner EVAL p1/p32 | PRE vs POST | The +34/+40 admission instructions (§9) and the S1 close (+28) |

Protocol notes: boot both arms with `--databases 1` (memory: databases-default trap); keep the
same `--atomic` and ratio per cell; check `script_crossshard_window_refusals == 0`,
`script_escalations` and `atomic_txn_order_violations == 0` after each POST cell.

### 14. Not run

| Item | Reason |
|---|---|
| Any performance measurement (generic cells, EXEC merit, contended-script throughput) | Forbidden in this lane; requested above |
| Full `tests/gate.sh` iteration | Forbidden; partial ledgers only |
| `script_window_release` instruction count at Final | Outside the activation scope as the probe drives it |
| A fix for XS-SHUT-1 / SNAP-STORM-1 / XS-NOTIFY-1 / FLIP-MULTI-1 | Pre-existing, outside AT4.12; flagged, not fixed |
| A fix for AT4-WOUND-1 | Owned by woundfix |

## at412c

Continuation from `5591449e2`, branch `cx-at412c`; no push. CPUs 48-63 and
ports 20200-20299 only. T7's incorrect waiter/holder assumption is fixed;
`docs/at412c/t7/` contains the reproduced failure and corrected 27-leg run.
Final-source proof and arm tables below will supersede the at412 WIP tables.
