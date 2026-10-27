# AT4.12 proof and measurement request

## at412

Branch `cx-at412c`, continuing `cx-at412` at `5591449e2`. PRE is
`7ae703778e854a7b76945af5792a5ec5e88061a6` (cx-execindex); final production source is
`f7204660ef5651ad0ae14de14e13a693b2db0f8c`. Later commits contain tools, evidence and this report.
Processes use CPUs 48-63 (builds `-j16`); correctness servers 48-55, drivers 56-63;
server ports 20200-20299. Two early harness self-test runs used ephemeral guard
ports; the corrected 20299 run and exception are recorded in `docs/at412c/selftests/`. No push. No performance run, no load generator for measurement and no full
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
| Refusals, af5 shape, historical at412 POST (`docs/at412/af5/`) | 6,400/6,400 OK per command and 64/64 in the cut window, in every leg. PRE: 3,484-3,846 TRYAGAIN per 6,400 and 32-40 BUSY per 64 |
| Non-script instruction counts (48 command scopes) | **Zero added instructions:** 24 exactly equal (GET/SET/INCR), 24 lower (MGET/MSET); no increases. All 24 requested handler bodies are identical |
| Script cost | Final preparation is 298–312 instructions below PRE; full activation including Final is 76–88 below PRE. FIFO routines themselves execute 14 check + 27 admit + 14 release instructions. No rate claim |
| DQ / DF | DQ=+18, DF=+18. EXPECT constants unchanged |
| Arms (SHA-256) | PRE `6582b6cc…`, POST `b179853b…`, POST-layout `b2635958…`, PAD-A `019b5fc6…`; all rebuilt, full digests in §12 |

### 1. What was implemented (D4′)

| Piece | Where | What it does |
|---|---|---|
| Hand-off at every conflict exit | `scatter_engine.inc` (`xshard_complete_script`), `script_escalation.inc` (`script_escalate_handoff`) | The certification-CAS exit and the VALIDATE exit (after 8 restages) and the APPLY-conflict exit (at once) unpin, then hand off. No TRYAGAIN text remains in the script engine |
| Escalated attempt E (kind-2 unit) | `script_escalate_redispatch`, `script_group_prepare` | The IO lane re-prepares the command with `force_atomic`, attaches a `TxnGroupAttempt` before the first wave, draws or inherits the age, transfers the credit, reopens the apply window and posts wave 1 |
| E's waves | `ScriptPhase::Place` + cold `script_group_read`; RUN unchanged; APPLY under claims | PLACE+READ: `txn_group_read_prepare`, then a read at UINT64_MAX. The RUN wave runs on the workbench as before. APPLY validates nothing: the read-set bits are cleared because the claims proved exclusivity |
| Decision | `script_group_final` | Reserve, CAS 0 → ticket and publish in one coordinator step. A lost CAS aborts the process (falsifier). E never certifies |
| FIFO admission (replaces BUSY) | `xshard_prepare_script`, `script_window_*`, `txn_group_prepare` | Per-IO admission byte in `MultiRetryLane`: bits 0-6 count live optimistic activations (≤4), bit 7 = FIFO present. Waiters keep their frame unconsumed and the atomic-backpressure flag set. The cold resume arm grants the head. Scripts jump over the general 8-cut window |
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
| B | **§5.1 "zero added instructions" for MGET/MSET.** The table says `xshard_execute: none` while §6.2 places the escalated branch in the owner Pin case (2624-2644). GCC inlines `execute_script_phase` (its IPA-SRA clone, called once) into `xshard_execute`, so any edit there re-allocates registers in the MGET/MSET body. The admission edit in `xshard_prepare` does the same | 49 measured source shapes (`docs/at412/budgets3/shape-search.json`). Even deleting the script branch from `xshard_prepare` entirely moves MGET/MSET counts by up to 6 instructions per call (variant `z0`) | `xshard_execute`: solved (escalated wave = `ScriptPhase::Place`, cold callee: counts PRE-equal in every scope). `xshard_prepare`: solved in at412c by a script specialization reached before reload lifetime setup; every final ordinary scope is PRE-equal or lower (§8). The original shared-body site claim remains disproved; the final placement differs |

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

Final source, native `GATE_ONLY_JOBS` run `build/gate-run.CXwo22`: **18/18 at412
rows pass**, plus the release prerequisite. There are **372 TomoKV + 51 Redis
legs (423/423)** and **8/8 owner-fixture legs**. Every server boot requires rc 0
and no forced teardown. EVAL/EVALSHA/FCALL × 1s/2s × atomic 0/1 × uring/epoll
is the default; the single-geometry exceptions are stated below. Normal boots
use shards 16, 2s/6:2 or 1s/read-local 1, and databases 16. The two single-IO
rows use 2s/1:7. Servers use CPUs 48-55 and the driver 56-63.

| Row | Property | TomoKV | Redis | Result |
|---|---|---:|---:|---|
| T1 | Ninth conflict hands off; exact reply/data and one escalated commit | 24/24 | 3/3 | PASS |
| T2 | FIFO admission beyond four optimistic slots; no BUSY and waits witnessed | 24/24 | 3/3 | PASS |
| T3 | Four MGET cuts do not consume script admission slots (2s, 1:7) | 12/12 | 3/3 | PASS |
| T4 | APPLY conflict escalates immediately; no partial script result | 24/24 | 3/3 | PASS |
| T5 | Conflict escalation and a full FIFO window in one schedule | 24/24 | 3/3 | PASS |
| T6 | 30-second scripts + EXEC + WATCH/EXEC + plain-writer storm; exact accounting | 24/24 | 3/3 | PASS |
| T7 | Started older-script claim orders H, E_old, W, E_young across a writer episode | 24/24 | 3/3 | PASS |
| T8 | Opposite-order escalated scripts finish with Redis-equal data | 24/24 | 3/3 | PASS |
| T9 | Escalated scripts versus blind groups; no torn generation | 24/24 | 3/3 | PASS |
| T10 | Scripts/writers across FLIP, with quiescent transfer holds (2s only) | 12/12 | 3/3 | PASS |
| T11a | Live SAVE at optimistic Final and BGSAVE across escalation hand-off (2s, 1:7) | 12/12 | 3/3 | PASS |
| T11b | Three forced-conflict batches, drained BGSAVE/reload, exact restored data | 24/24 | 3/3 | PASS |
| T12 | Forced conflict/escalation with AOF reload and exact data | 24/24 | 3/3 | PASS |
| T13 | >64 simultaneous waiters, 128 scripts + 32 EXECs + eight writers; all finish | 24/24 | 3/3 | PASS |
| T14 | Final WRONGTYPE/OOM semantics and partial Lua write retention; labelled XS-OOM-1 suffix | 24/24 | 3/3 | PASS |
| T15 | Dispatched-script/FIFO-waiter disconnect cleanup; eight replies before clean shutdown | 24/24 | 3/3 | PASS |
| T16 | Exact same-shard events; cross-owner read-only calls against atomic script generations | 24/24 | 3/3 | PASS |
| owner | H1/H3 non-compliant-cycle controls, compliant rank schedules and wound-window guard | 8/8 | — | PASS |

Evidence: `docs/at412c/proof/directed-0-gate-run.CXwo22/` (all leg results, boot
argv/exits, native ledgers and log digests). The archived predecessor run had
15 rows ok and four FAIL, retained in `docs/at412c/historical-gate-54JIbr/`;
its failures remain failures. T7 was corrected; T11b/T15/T16 now isolate the
lane property as explained in §6 and the at412c section.

### 6. Deviations found (pre-existing, labelled)

Each was reproduced on PRE (`build/at412/pre/tomokv`) with the same result as POST, so none is
caused by this lane. None involves AT4-WOUND-1.

| Label | Deviation from Redis 7.4.10 | PRE | Historical POST | Evidence | Final gate treatment |
|---|---|---|---|---|---|
| XS-NOTIFY-1 | Cross-owner scripts publish no keyspace events and no CLIENT TRACKING invalidations (single-owner scripts do) | same | same | `docs/at412/deviations/probe-{redis,pre,post}.json` | T16 requires exact same-shard notifications; cross-owner event/tracking absence is a separate failing non-gate diagnostic |
| XS-OOM-1 | A cross-owner EVAL refused by maxmemory omits Redis's ` script: <sha>` suffix | same | same | probe JSON (`two_key_eval_oom`) | T14 compares the message without the suffix and records the deviation |
| XS-OOM-2 | DEL under maxmemory answers `ERR out of memory` while script intents are live | same | same | `oom2-shebang.txt` | T14 deletes before setting maxmemory |
| XS-SHEBANG-1 | `#!lua flags=…` shebangs do not compile (`EVAL`/`EVAL_RO`) | same | same | `oom2-shebang.txt`, `shebang_probe.py` | T16 uses plain EVAL_RO bodies |
| XS-SHUT-1 | SHUTDOWN NOSAVE with cross-owner scripts in flight aborts in `atomic_destroy_pending` → `atomic_remove_unit_intents` (flatstore_atomic.inc:232) | rc −6, 2/2 | rc −6, 2/2 (EXEC/RENAME rc 0) | `shutdown-abort.txt`, `shutdown-abort-pre-stack.txt` | T15 drains and verifies all eight accepted calls before clean shutdown; in-flight shutdown stays a failing non-gate diagnostic |
| SNAP-STORM-1 | BGSAVE loop under a unit storm can stall: `snapshot_cuts_armed == rdb_saves`, units stuck, plain writers progress, resolves on disconnect. Reproduced with EXEC+writers and no scripts | full storm 4/7 stalled; EXEC+writers 2/5 | scripts+writers 4/5; EXEC+writers 0/5; full 1s 9/11, 2s 2/5 | `bgsave-storm-stall.json` | T11b saves/reloads after each forced-conflict batch drains; T11a keeps the live cut/handoff overlap. Continuous storm stays a failing non-gate diagnostic; mechanism not isolated |
| FLIP-MULTI-1 | A connection that ever ran MULTI keeps its MultiSession, so it is never FLIP-transferable (`migration_protocol_idle`) | same | same | T10 notes | T10 runs scripts + writers with a hold around each FLIP; a full EXEC storm refuses every FLIP on PRE and POST |

The final gate tolerates no crash, abort, forced teardown or stall. Reproduction
commands and fresh PRE/final-POST evidence for SNAP-STORM-1, XS-SHUT-1 and XS-NOTIFY-1 are in
`docs/at412c/diagnostics/`; `tests/at412_diagnostics.py` is deliberately outside the
gate and returns nonzero when a defect reproduces. The fresh PRE snapshot mixed storm
stalled on its first 30-second attempt; the script-free variant did not reproduce
in ten 5-second and five 30-second attempts. Historical script-free evidence remains
labelled separately. Final POST aborted with rc -6 on the first shutdown attempt,
committed writes but emitted no events/invalidations on the first notification
attempt, and timed out in BGSAVE on the second fresh snapshot-storm attempt
(`rdb_bgsave_in_progress=1`, cuts=9, saves=9). All three diagnostics returned rc 1;
their commands and final binary digest are in `docs/at412c/final-controls.json`.
The fixes belong to other lanes.

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

### 8. Zero-added-instruction proof for non-script commands

**48/48 scopes meet the requirement: 24 equal, 24 lower, zero higher.** GET/SET/INCR
are equal per function too. MGET/MSET have the same algorithms and ordinary loader
lifetimes as PRE. One source template supplies ordinary and script preparation;
the ordinary entry tail-jumps to the script specialization before constructing
`RuntimeLoadingGuard`. FIFO state and its argument lifetimes therefore remain in
the script route. Scripts have no reload containers. Four preparation leaves and
the SortOptions copy retain explicit inlining when they gain a second caller.
There is no layout-lock or claim-protocol change.

The serverless probe links final production objects. GET/SET/INCR execute the
production executor batch entry; MGET/MSET cover eight-shard prepare, owner
execution, completion and retirement. Both namespaces, both thread modes and
batches 1/32 are included; MSET covers atomic 0/1. Counts include named production
routines, stub clock calls, and exclude fixture glue and outside library callees.
Each trace checks exact replies/data. They are instruction counts, not rates.
`tools/at412_artifacts.py scope` fails on a missing pair or any positive delta;
cache reuse requires the exact probe SHA-256. Evidence: `docs/at412c/instructions/`.

| Namespace | Command | Mode | Atomic | Batch | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|---:|
| normal | GET | 1s | 1 | 1 | 949 | 949 | +0 |
| normal | GET | 1s | 1 | 32 | 18,898 | 18,898 | +0 |
| normal | GET | 2s | 1 | 1 | 1,575 | 1,575 | +0 |
| normal | GET | 2s | 1 | 32 | 18,935 | 18,935 | +0 |
| normal | SET | 1s | 1 | 1 | 1,078 | 1,078 | +0 |
| normal | SET | 1s | 1 | 32 | 23,026 | 23,026 | +0 |
| normal | SET | 2s | 1 | 1 | 1,704 | 1,704 | +0 |
| normal | SET | 2s | 1 | 32 | 23,063 | 23,063 | +0 |
| normal | INCR | 1s | 1 | 1 | 1,541 | 1,541 | +0 |
| normal | INCR | 1s | 1 | 32 | 38,371 | 38,371 | +0 |
| normal | INCR | 2s | 1 | 1 | 2,167 | 2,167 | +0 |
| normal | INCR | 2s | 1 | 32 | 38,408 | 38,408 | +0 |
| normal | MGET | 1s | 1 | 1 | 10,243 | 10,204 | -39 |
| normal | MGET | 1s | 1 | 32 | 326,598 | 325,350 | -1,248 |
| normal | MGET | 2s | 1 | 1 | 10,243 | 10,204 | -39 |
| normal | MGET | 2s | 1 | 32 | 326,598 | 325,350 | -1,248 |
| normal | MSET | 1s | 0 | 1 | 10,894 | 10,841 | -53 |
| normal | MSET | 1s | 1 | 1 | 17,080 | 17,036 | -44 |
| normal | MSET | 1s | 0 | 32 | 348,453 | 346,757 | -1,696 |
| normal | MSET | 1s | 1 | 32 | 964,774 | 963,366 | -1,408 |
| normal | MSET | 2s | 0 | 1 | 10,690 | 10,659 | -31 |
| normal | MSET | 2s | 1 | 1 | 16,726 | 16,704 | -22 |
| normal | MSET | 2s | 0 | 32 | 341,925 | 340,933 | -992 |
| normal | MSET | 2s | 1 | 32 | 953,446 | 952,742 | -704 |
| db0 | GET | 1s | 1 | 1 | 828 | 828 | +0 |
| db0 | GET | 1s | 1 | 32 | 19,025 | 19,025 | +0 |
| db0 | GET | 2s | 1 | 1 | 1,067 | 1,067 | +0 |
| db0 | GET | 2s | 1 | 32 | 18,675 | 18,675 | +0 |
| db0 | SET | 1s | 1 | 1 | 965 | 965 | +0 |
| db0 | SET | 1s | 1 | 32 | 23,409 | 23,409 | +0 |
| db0 | SET | 2s | 1 | 1 | 1,204 | 1,204 | +0 |
| db0 | SET | 2s | 1 | 32 | 23,059 | 23,059 | +0 |
| db0 | INCR | 1s | 1 | 1 | 1,324 | 1,324 | +0 |
| db0 | INCR | 1s | 1 | 32 | 35,426 | 35,426 | +0 |
| db0 | INCR | 2s | 1 | 1 | 1,563 | 1,563 | +0 |
| db0 | INCR | 2s | 1 | 32 | 35,076 | 35,076 | +0 |
| db0 | MGET | 1s | 1 | 1 | 10,370 | 10,337 | -33 |
| db0 | MGET | 1s | 1 | 32 | 330,662 | 329,606 | -1,056 |
| db0 | MGET | 2s | 1 | 1 | 10,370 | 10,337 | -33 |
| db0 | MGET | 2s | 1 | 32 | 330,662 | 329,606 | -1,056 |
| db0 | MSET | 1s | 0 | 1 | 11,143 | 11,117 | -26 |
| db0 | MSET | 1s | 1 | 1 | 16,497 | 16,489 | -8 |
| db0 | MSET | 1s | 0 | 32 | 356,421 | 355,589 | -832 |
| db0 | MSET | 1s | 1 | 32 | 955,046 | 954,790 | -256 |
| db0 | MSET | 2s | 0 | 1 | 10,962 | 10,935 | -27 |
| db0 | MSET | 2s | 1 | 1 | 16,166 | 16,157 | -9 |
| db0 | MSET | 2s | 0 | 32 | 350,629 | 349,765 | -864 |
| db0 | MSET | 2s | 1 | 32 | 944,454 | 944,166 | -288 |

In the ordinary MGET/MSET traces, preparation changes some inlining boundaries:
`initialize_owner_completion` executes 3–6 additional named instructions and db0
`Op::cmd_name` executes 12. These are included in the totals, not omitted. The
prepare savings exceed them in every cell. Owner execution, deferral, completion,
retirement and command-handler instruction counts remain PRE-equal in these scopes.

| Identity set | Equal / total | Changed bodies |
|---|---|---|
| ccfix hot bodies | 1,274 / 1,378 | 104 flush_ready/r7_flush_ready instantiations containing the design's cold resume arm |
| Command handlers | 1,224 / 1,232 | INFO and DEBUG only |
| Extended hot list | 1,327 / 1,448 | Resume arm; preparation; script completion/tail target; owner Place dispatch including one db0 owner lambda |
| GET/SET/INCR/MGET/MSET handlers | **24 / 24** | None |

Identity evidence is `docs/at412c/identity/`. The raw ccfix assertion rejects the
resume-arm edits; the lane wrapper accepts exactly that named set, plus INFO/DEBUG,
and separately requires all 24 requested handlers to match. It does not claim
whole-program identity. Final IPA initial sizes are 121768/120766, with selected
budgets 152000/150500 (`docs/at412c/budgets-final/`). The original 49-shape search
and its −11…+17 residual remain historical evidence in `docs/at412/budgets3/`;
that residual is absent from the final source.

### 9. Script admission and complete-activation cost

The final constant-kind script route removes generic reload scaffolding and
reduces the whole preparation scope by 298–312 instructions against PRE. The
FIFO routines themselves execute **14 check + 27 admit** instructions; Final
executes **14 release** instructions. These are included in the totals below.
Full activation includes prepare, every dispatched wave, Final and retirement;
the added work after admission is +224 instructions in the normal namespace and
+222 in db0. Preparation savings leave total activation 76–88 below PRE.

The old report's activation tracer skipped fixture callbacks that dispatch later
waves, so its totals and statement that Final was unmeasured are superseded.
The corrected tracer follows those callbacks while excluding their own instructions.
Both PRE and POST were traced under this same rule. This is an uncontended two-owner
EVAL scope after one warm-up activation, not a throughput result.

| Namespace | Scope | Mode | Atomic | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|
| normal | EVAL | 1s | 0 | 38,023 | 37,944 | -79 |
| normal | EVAL | 1s | 1 | 38,030 | 37,942 | -88 |
| normal | EVAL | 2s | 0 | 38,053 | 37,974 | -79 |
| normal | EVAL | 2s | 1 | 38,060 | 37,972 | -88 |
| normal | EVAL-ADMIT | 1s | 0 | 7,980 | 7,677 | -303 |
| normal | EVAL-ADMIT | 1s | 1 | 7,987 | 7,675 | -312 |
| normal | EVAL-ADMIT | 2s | 0 | 7,980 | 7,677 | -303 |
| normal | EVAL-ADMIT | 2s | 1 | 7,987 | 7,675 | -312 |
| db0 | EVAL | 1s | 0 | 35,422 | 35,346 | -76 |
| db0 | EVAL | 1s | 1 | 35,429 | 35,344 | -85 |
| db0 | EVAL | 2s | 0 | 35,452 | 35,376 | -76 |
| db0 | EVAL | 2s | 1 | 35,459 | 35,374 | -85 |
| db0 | EVAL-ADMIT | 1s | 0 | 7,984 | 7,686 | -298 |
| db0 | EVAL-ADMIT | 1s | 1 | 7,991 | 7,684 | -307 |
| db0 | EVAL-ADMIT | 2s | 0 | 7,984 | 7,686 | -298 |
| db0 | EVAL-ADMIT | 2s | 1 | 7,991 | 7,684 | -307 |

Full per-function counts and probe receipts: `docs/at412c/script-instructions/`.
This prices the final implementation, including the S1 close; it does not isolate
mechanism cost from compiler allocation or estimate contention throughput.

### 10. Gate runs

| Run | Geometry / jobs | Native result |
|---|---|---|
| Historical 54JIbr, saved POST 931130b2 | All at412 rows | 15 ok / 4 FAIL (T7/T11b/T15/T16); preserved, superseded by the final directed run |
| CXwo22, POST b179853b | All 18 at412 rows, release prerequisite, production_units | **19 ok / 0 FAIL**, 423/423 server/oracle legs and 8/8 owner legs |
| LwEpq1, POST b179853b | Broad native transaction, scripting/functions, persistence, FLIP and notification jobs; default uring boots plus each job's complete internal matrix | **420 ok / 0 FAIL** |
| 2U0RnS, POST b179853b | Epoll transaction-order, scriptatomic/xscript, scripting/functions and notification jobs, including their internal matrices | **203 ok / 0 FAIL** |
| JMYoLv, POST b179853b | Fused io_uring DEBUG, snapshot/SAVE, AOF and notification jobs, including their internal matrices | **204 ok / 0 FAIL** |
| R5aocp, POST b179853b | Fused epoll DEBUG and notification jobs, including their internal matrices | **51 ok / 0 FAIL** |
| SVpV0r / tpQWzJ | Initial io_uring / epoll differential attempts with binary-only Redis prefix | **Preflight rc 2; comparisons NOT RUN**: required Redis source headers absent; retained and queued again with the full checkout |
| zLdqei, POST b179853b | EXEC fairness across both modes/engines/atomic settings; io_uring fused batteries | **20 ok / 0 FAIL** |
| reErX1, POST b179853b | Epoll FLIP, controller, saturated hand-off and fused batteries | **31 ok / 0 FAIL** |

Further engine/mode and differential runs are still running; this table will be
completed from their actual partial ledgers. It is not a full gate receipt. All commands, hashes,
job outcomes and per-leg inventories are archived by tools/at412c_record.py in
`docs/at412c/proof/`. The FLIP saturation job uses its existing memtier process
only as correctness stress: rates are discarded and no PRE/POST performance
comparison is run. No SKIP/NOT RUN appeared in the completed broad run's logs.

The first queued phases use the binary-only /home/user/Projects/redis74 prefix.
Quick-tier preflight warns about absent Redis source files for the unselected
ACL-metadata job; its selected jobs use the valid 7.4.10 oracle binary. Full-tier
preflight refuses that prefix before running differential comparisons. Both
failed attempts are retained. The retry runner uses the complete
/home/user/Projects/redis checkout; both binaries have the same
SHA-256 (`docs/at412c/provenance.json`).

### 11. DQ / DF

`job_at412` adds 18 rows (T1-T16 with T11 as T11a/T11b, plus `at412-owner`), all collected
at tests/gate.sh line 5583, before the quick-tier exit at lines 5680–5684:
**DQ=+18, DF=+18**, on top of execindex's +2/+2. `EXPECT_QUICK=798`
and `EXPECT_FULL=815` are unchanged in this branch; the maintainer moves them to 800/817 for
execindex and to **818/835** with at412. `build/at412-owner` joins `job_production_units` (built
and `make -q`-checked there) and the `debug-*`/`txn_group_*` dependency list.

### 12. Final rebuilt arms

| Arm | Path | SHA-256 | Source / behaviour |
|---|---|---|---|
| PRE | `build/at412/pre/tomokv` | `6582b6ccacf8a58a46e5204c808fbbb262cbb9d3238bb0eb01c57ea2d2674bdc` | 7ae703778e854a7b76945af5792a5ec5e88061a6 |
| POST | `build/at412/POST` | `b179853b0bdee33cea6c151e45a448bada761d19976df57ba834e739f92e78e7` | f7204660ef5651ad0ae14de14e13a693b2db0f8c |
| POST-layout | `build/at412/POST-layout` | `b263595804d2e3cd95b7cbaa22e0424766d87388b0b75f7edca2f24919e49237` | f7204660e plus symbol-isolated 7ae703778 objects |
| PAD-A | `build/at412/PAD-A` | `019b5fc64e7171c642f806f7d77eafee1586915d61b9c7618f384fe26ed12296` | type A: PRE behaviour in POST-layout common image |

`docs/at412c/arms.json` and `pad-a.json` bind the outputs to the final objects.
PRE was rebuilt from a local archive of 7ae703778 inside this worktree. POST
equals build/tomokv. POST-layout links POST followed by symbol-isolated PRE
objects. PAD-A is **type A, behaviour twin**: PRE behaviour in the same common
image, changing only five bytes at main. Sections and symbol addresses match
exactly. The twin is POST-layout, not the smaller release POST; measure both
pairwise comparisons separately.

`.text` is 8,267,735 bytes in PRE and 8,293,031 in POST (+25,296); both common-image
arms are 16,560,407 bytes. Data/BSS sizes also match within the control pair.
These static sizes do not predict the rate verdict; the merit request keeps the
ordinary and common-image comparisons separate.

Final common-image smoke: **16/16 cells passed**, POST-layout/PAD-A × 1s/2s ×
io_uring/epoll × databases 1/16, with clean exits. Each checks EXEC, WATCH,
exact data, zero transaction-order violations, and EVAL/EVALSHA/FCALL on a
DEBUG-witnessed distinct-owner pair (`docs/at412c/pad-smoke.json`).

`docs/at412c/freshness.json` records 51 successful make -q checks: PRE and POST
all, all 46 primary job_production_units targets, the two mdbqsbr live-arm
build roots, and blockfix-cost with its server/hash receipt. The native helper
built every target using -j16 before these checks.

### 13. Merit request (maintainer; NOT RUN here)

The worktree-root `MEASURE-REQUEST` contains exact recipes and decision criteria.
The standing 14-cell set is frozen in `docs/at412c/merit/generic14.txt`, copied from
the execfair/bugs5 matrix with provenance in `recipes.json`.

| Cells | Arms | Verdict |
|---|---|---|
| Generic 14: h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0 | PRE vs POST; POST-layout vs PAD-A type A | Gate ABBA per-cell rate/latency at matched offered load, with cycles/op, IPC and instructions/op and measured spread |
| EXEC merit's eight cells: 1s/2s × atomic 0/1 × uncontended/hot | PRE vs POST | Completed EXEC/s, writer progress/share and latency; 64 connections, p4, 16 generator threads, three 20-second ABBA blocks |
| T6 contended-script shape | PRE vs POST | Successful scripts/s plus EXEC and plain-writer progress; separate refusals and WATCH aborts, exact final-data accounting; three 30-second ABBA blocks |
| Optional two-owner EVAL p1/p32, both modes/atomics | PRE vs POST | Uncontended admission and Final cost in the rate instrument |

Use --databases 1 explicitly, preserve each recipe's geometry/read-local posture,
and match offered load. Require POST refusals and atomic_txn_order_violations to
remain zero; retain escalation, committed-escalation and FIFO-wait counters.
A crash, missing reply or wrong final data invalidates the cell. This lane makes
no throughput claim; the instruction results do not decide performance.

### 14. Not run / outside this lane

| Item | Reason |
|---|---|
| Generic, EXEC and contended-script performance measurements | Maintainer-owned quiet-box measurements; requested in §13 and MEASURE-REQUEST |
| Full tests/gate.sh iteration | Maintainer-owned; only native selected-job ledgers were requested here |
| Fixes for XS-SHUT-1 / SNAP-STORM-1 / XS-NOTIFY-1 / FLIP-MULTI-1 | Pre-existing and outside this lane; separate diagnostics retain failures |
| Fix for AT4-WOUND-1 | Owned by woundfix; this lane's schedules remain independent of it |

## at412c

Continuation from 5591449e2, with no push. The final production change is
f7204660e; the instruction/identity/arm receipts are committed separately.

T7's archived failure was a schedule error: its old EXEC blocker held k, so the
older script was only a waiter on k when the plain writer began. A waiter does
not block a plain writer. The observed [101,1] reply was reproduced in 11/24
Tomo legs on the saved 931130b2 binary (Redis 3/3 passed). H now holds a peer of k
on the same shard plus j. E_old must place/read k and wait on H's j; both the
placement-wait counter and three READ tasks must be witnessed before W. Exact
replies assert H, E_old, W, E_young order. Direct corrected proof and the final native T7 job are both 27/27;
`docs/at412c/t7/` retains both runs and the negative evidence.

T11b now forces and verifies three conflict/escalation batches, drains each,
then BGSAVEs, reloads and checks exact data. T11a retains the live SAVE/hand-off
window. T15 keeps dispatched-script/FIFO-waiter disconnect checks and verifies
eight accepted replies plus exact data before clean SHUTDOWN. T16 requires exact
same-shard events and races cross-owner read-only calls against an atomic script
writer. Its old atomic-0 MSET writer could correctly expose [2,1]; it could not
prove atomic read-only generations. Missing cross-owner events, in-flight shutdown
abort and continuous snapshot-storm stalls remain documented non-gate diagnostics.
No gate success rule permits a crash, abort, forced teardown or stalled reply.

The preparation split closes the remaining instruction-cost failure without
changing claim admission, epoch rules, layouts or ordinary command algorithms.
All 48 final ordinary scopes have no added instructions; all 24 requested handler
bodies match PRE. The script trace now includes Final release. All four arms are
rebuilt with full digests. Merit remains a request for the maintainer.

This continuation adds no rows: **at412c DQ/DF = +0/+0; cumulative at412 = +18/+18**.
EXPECT_QUICK/EXPECT_FULL remain untouched. The final port-bounded harness self-test
passed 72/72; its earlier timeout and ephemeral-guard exception are preserved in
`docs/at412c/selftests/`.
