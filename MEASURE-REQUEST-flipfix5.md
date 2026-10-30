# FLIP stale-stage replay — review and measurement request

## flipfix5

Branch `cx-flipfix5`, base `e2b237926` (origin/cpp). No push. Production source is commit
`bec4a1e20` (fix `586b2304c` plus the DEBUG hook `bec4a1e20`); later commits add tests,
tools and evidence only. FLIP's design is unchanged: the truth tables, the block masks and the
re-mask protocol (re-mask inside the ExDrain → ExInstall quiesce) are untouched. The fix makes the
control passes obey that protocol; it does not change it, so no owner proposal is needed. The
no-write-obstructed-read law is untouched (no read or write path changed).

| Item | Result |
|---|---|
| Defect | `ExLoopT<false>::flip_control_pass()` aborts in ExInstall: `remask_task_inbox_quiesced()` false, predicate `all_quiesced()` |
| Root cause | A control pass tests the stage it loaded at the top of the pass against the **live** epoch. A thread held between the two loads replays an already acknowledged stage in the next FLIP. |
| Engines | Aborts on io_uring legs only (63 of 96 PRE attempts with the seven aborting partners); 0 of 96 on epoll, where the hold never opened by itself |
| PRE abort rate, uring legs | 1.1–3.2 aborts per 100k completed FLIPs, depending on the partner operation (table 1) |
| POST | 0 aborts in 216 step-1-scale attempts; 0 in 48 extra uring attempts on an abort-wrapper twin of the fix |
| Fix | `Server::flip_stage_owed()`: token first, then the stage must reload equal across an unchanged epoch; used by every per-thread stage action (EX, IO, database boundary) |
| Directed rows | 2 serverless rows (deterministic holds + 5 planted pre-fix controls) and 1 live row (all 8 legs, natural + held phases). DQ=+3, DF=+3 |
| Directed live row | PRE: fails (all 4 uring legs abort, 1.8–6.2 s). PAD-A: aborts on all 8 legs. POST: passes all 8 legs, 39,120–52,536 stale samples refused per held phase |
| GET/SET/INCR/MGET/MSET | 80 of 80 command-scope cells: zero added instructions, identical per-function counts |
| FLIP control pass | Idle passes unchanged (EX 29/32, IO 25/26 instructions); a pass on a non-Idle stage adds 15–19 instructions |
| Separate finding (not fixed) | A pipelined cross-owner MULTI/EXEC client holds every FLIP to its 5 s deadline (PRE and POST alike) |

### Step 1 — reproduction on e2b237926

FLIP exists only in 2s ("ERR FLIP is unavailable with --thread-mode 1s"), so every leg is 2s:
both engines × atomic 0/1 × databases 1/16. Server on CPUs 24–31 (`--shards 16 --ratio 6:2
--flip-auto 0 --key-lb 0 --client-lb 0`), harness on 16–23, port 20200, fresh boot per attempt,
8 s per attempt. The flipper alternates `FLIP 4 4` / `FLIP 6 2`. An attempt is an *abort* when the
server dies on SIGABRT. Table 1: aborts / attempts (PRE `5432534f…`).

| Partner operation of the FLIP storm | uring-0-db1 | uring-1-db1 | uring-0-db16 | uring-1-db16 | epoll-0-db1 | epoll-1-db1 | epoll-0-db16 | epoll-1-db16 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MSET + FLUSHALL SYNC (flushfix2 live-flip witness, unchanged) | 2/6 | 6/6 | 4/6 | 3/6 | 0/6 | 0/6 | 0/6 | 0/6 |
| FLUSHALL ASYNC | 2/3 | 3/3 | 3/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| FLUSHDB | 2/3 | 2/3 | 1/3 | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| SCAN (full cursor walk) | 3/3 | 1/3 | 1/3 | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| RANDOMKEY | 2/3 | 1/3 | 2/3 | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| EVAL (cross-owner script) | 2/3 | 2/3 | 2/3 | 1/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| SWAPDB 0 7 (0 0 in db1) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| DBSIZE NOW (exact, scatters to every owner) | 3/3 | 3/3 | 3/3 | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| DBSIZE (plain, published counts) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| KEYS | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| BGSAVE (FLIP refused during the snapshot) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| Cross-owner EXEC (pipelined MULTI INCR INCR EXEC) | 0/3 † | 0/3 † | 0/3 † | 0/3 † | 0/3 † | 0/3 † | 0/3 † | 0/3 † |
| No partner (FLIP storm alone) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |

Aborts per 100k completed FLIPs on the uring legs: witness 1.47, FLUSHALL ASYNC 3.12, FLUSHDB
1.30, DBSIZE NOW 3.21, SCAN 1.13, RANDOMKEY 2.99, EVAL 1.26; 0 for every other operation and for
every epoll leg.

† EXEC: in 22 of 24 attempts FLIP never completed — every FLIP was refused after its 5 s
deadline ("ERR FLIP timed out before the ownership commit" ×30, "ERR FLIP cannot quiesce a
connection: connection ROB, reply, borrow, or owner-local protocol state is busy" ×16) and the
EXEC client stalled for each window. That is a separate liveness defect (below). Where FLIP
did run beside EXEC it aborted too: an exploratory run on uring-0-db16 aborted after 2,692 FLIPs
(`build/flipfix5/runs/smoke-exec-0`). EXEC is therefore not a distinct abort mechanism.

The abort needs a task in the replaying executor's inbox. The partners that never aborted
supply none in that gap: plain DBSIZE answers from published counts on the IO thread (no owner
task), SWAPDB replies locally in db1 and in db16 runs the database boundary that FLIP serializes
with ("a FLIP is already in progress"), BGSAVE makes FLIP refuse during its snapshot, and KEYS
throttled the storm to ~3.5k FLIPs per attempt instead of ~60k. With no partner the replay still
happens but re-masks an empty inbox silently (the unit's silent planted controls show it). Raw
counts: `docs/flipfix5/step1-pre.json`.

### Step 2 — diagnosis

Method: diagnostic copies of PRE (and later of the first POST candidate) with an abort-time dump
in the ExInstall branch, push provenance on every inbox lane, stage/epoch/ack timestamps, and a
linked `__wrap_abort` printing executable offsets for offline `addr2line`. No debugger attach, no
core dump. Patch scripts: `docs/flipfix5/diag/`; all 21 dumps: `docs/flipfix5/diagnosis.json`.

* **Predicate.** `MaskedSpscArray::remask_quiesced()` returns false at `all_quiesced()` in every
  dump (the allocation, role-vector and producer-count checks before it pass).
* **Task and inbox.** One lane of an IO producer holds `head=0 retired=0 tail=1` (an MSET
  sub-task) or `tail=4` (FLUSHALL sub-tasks, one per owned shard). The lane was reset by the
  previous ExInstall re-mask, then received exactly that ordinary dispatch.
* **Who enqueued it.** The IO thread's ordinary `parse_and_dispatch` → `post_task_quiet`
  (push site symbolized to `ThreadCtx::post_task_quiet`), in the Idle gap after the FLIP finished
  and before the next one paused dispatch. Legitimate traffic.
* **Why the quiesce logic "believed" the inbox was drained.** It did not: the re-mask ran outside
  the quiesce. At every dump the live stage is IoDrain of the **next** epoch E+1, the thread's own
  ExInstall acknowledgement is epoch E, and its token is 0 (cleared by `flip_begin`). The pass had
  loaded `stage == ExInstall` (epoch E, already acknowledged), was held, and then evaluated
  `!flip_acked(tid, stage)`, which rebuilds the token from the live epoch E+1 → "not acknowledged"
  → ExInstall's body ran again in E+1 while dispatch had resumed.
* **The hold.** With no syscall inside the window (diag v3), 5 of 8 dumps show 86–199 µs between
  the stage load and the acknowledgement test with **no involuntary context switch** (`nivcsw`
  unchanged), each sample landing right at a millisecond tick; the other 3 show the epoch changing
  during the stage load itself. Timeline example (uring-0-db1): own ExInstall acknowledgement of E
  at t, stage sample t+20 µs, FLIP E finished t+64 µs, FLIP E+1 admitted t+92 µs, acknowledgement
  test t+148 µs. The kernel work that stretches the window showed up only with io_uring here; epoll
  produced no abort in 84 attempts with the aborting partners.
* **Same class elsewhere.** Every per-thread stage test in the EX pass (DatabaseExDrain, IoPrepare,
  ExDrain, ExInstall, Rollback), the IO pass (IoDrain … RoleReady, Rollback) and the IO database
  pass has the same form; a stale IO ClientCommit/RoleReady replay would re-run listener install
  or pub/sub re-homing in the wrong epoch, and a stale DatabaseExDrain acknowledgement could be
  counted by the next boundary. The fix covers all of them.

### Step 3 — fix and directed rows

`Server::flip_stage_owed(tid, stage)` (one out-of-line copy per namespace) replaces
`!flip_acked(tid, stage)` in every per-thread stage action:

```cpp
uint64_t token = flip_ack_[tid].load(acquire);          // first
const uint64_t epoch = flip_epoch();
const bool live = flip_stage() == stage && flip_epoch() == epoch;
if (live) return token != ((epoch << 8) | stage);        // owed iff not acknowledged in this epoch
/* stale sample: count it, act on nothing */ return false;
```

`flip_begin()` clears the tokens with release stores after its Planning CAS (plain stores on
x86), so a token cleared by the next FLIP forces the stage reload to see Planning or later. An
owed stage cannot advance without the thread's acknowledgement (failure only turns it into
Rollback of the same epoch), so the existing `flip_ack()` still stamps the right epoch. The
database-boundary passes judge quiescence only after the owed test. INFO stats gains
`flip_stale_stage_refusals` (stale samples the old test would have acted on). Both new Server
fields fill the padding after `flip_failed_`: `sizeof(Server)` and every member offset are
unchanged (verified at compile time). `DEBUG FLIP-STAGE-HOLD <us>` (production 0) holds an
executor that already acknowledged ExInstall before its owed test until the next FLIP is admitted:
the measured hold, on demand, on both engines.

**History.** The first candidate read the token *after* the validation. The live hunt on its
abort-wrapper twin found the residual race (4 aborts in 11 uring attempts: validation passed,
the thread was held, the next `flip_begin` cleared the token, the stale ExInstall looked owed).
Reading the token first closed it: 0 aborts in 48 attempts on the same twin. The serverless row
now pins this order with a planted late-token control.

Directed rows (DQ=+3, DF=+3; EXPECT_QUICK/EXPECT_FULL untouched, 946/963 → 949/966 is the
maintainer's update):

| Row (gate job) | What it does | PRE e2b237926 | PAD-A | POST |
|---|---|---|---|---|
| FLIP stale stage sample refused (ASAN+TSAN) — `flipfix5_units` | Core fixture 6:2; a test hook holds the pass while the sampled FLIP finishes and the next begins: ExInstall (empty inbox; with a resumed SET; held inside the owed test after validation), DatabaseExDrain, IO RoleReady | n/a (hook absent) | n/a (serverless) | 5/5 refused, PASS under ASAN/UBSAN and TSAN |
| FLIP stale stage planted pre-fix controls fail — `flipfix5_units` | Same holds with the pre-fix live-epoch test or a token read after validation planted | n/a | n/a | 4 planted holds replay (FAIL witness, exit 1); the posted-task hold aborts in the re-mask (witness, exit 134) |
| FLIP stale stage storm (all legs) — `flipfix5` | 8 legs, fresh boot each; FLIP storm against MSET+FLUSHALL SYNC, FLUSHALL ASYNC, FLUSHDB, DBSIZE NOW, SCAN, RANDOMKEY and EVAL at once; 6 s natural, then 4 s with FLIP-STAGE-HOLD 2000 | FAIL: all 4 uring legs abort (1.8, 6.2, 3.8, 2.1 s); the epoll legs cannot arm the hold | FAIL: all 8 legs abort (uring 1.7–7.2 s; epoll 7.1–7.2 s, ~1 s after arming) | PASS: all 8 legs; natural phase 22,419–29,126 FLIPs and 0–6 stale samples refused; held phase 13,042–17,513 FLIPs and 39,120–52,536 refused |

POST at the step-1 scale (same commands as table 1): 0 aborts in 216 attempts (the witness
6 × 8 legs; FLUSHALL ASYNC, FLUSHDB, DBSIZE NOW, SCAN, RANDOMKEY, EVAL, EXEC 3 × 8 legs each).
EXEC still fails 17/24 on the separate FLIP liveness defect, with no abort
(`docs/flipfix5/step1-post.json`).
Row evidence: `docs/flipfix5/row-final.json`, unit outputs `docs/flipfix5/unit/`.

### Step 4 — instruction counts

Serverless, through the established fixture (`tools/crlffix_step.c` stepping an owned child;
no server, listener, rate or debugger). `tools/flipfix5_counts.py`: PRE objects built from
`git archive e2b237926`, POST from the frozen tree. Counts are executed instructions (NOPs
included) in named TomoKV bodies, excluding library callees and fixture glue.

GET/SET/INCR/MGET/MSET, batch 1 and 32, 1s and 2s, atomic 0 and 1, both namespaces: **80 of 80
cells add zero instructions and every per-function count is identical**
(`docs/flipfix5/counts/comparison.json`). Examples: GET 2s batch 1 normal 1,556 → 1,556; SET 2s
batch 32 db0 21,619 → 21,619; MSET 2s batch 32 atomic 1 normal 950,182 → 950,182.

The FLIP control pass itself (`tests/flipfix5_control_scope.cc`, one call of the linked
production symbol per stage state):

| Control pass (one call) | normal PRE | normal POST | normal change | db0 PRE | db0 POST | db0 change |
|---|---:|---:|---|---:|---:|---|
| EX, Idle (every executor pass) | 29 | 29 | unchanged | 32 | 32 | unchanged |
| EX, ExDrain owed (quiesce + ack) | 486 | 505 | 19 more | 479 | 498 | 19 more |
| EX, ExDrain already acknowledged | 35 | 53 | 18 more | 38 | 56 | 18 more |
| EX, ExInstall owed (re-mask + ack) | 560 | 578 | 18 more | 563 | 581 | 18 more |
| EX, ExInstall already acknowledged | 38 | 55 | 17 more | 40 | 58 | 18 more |
| IO, Idle (pass snapshot Idle) | 25 | 25 | unchanged | 26 | 26 | unchanged |
| IO, IoDrain owed (drain + ack) | 603 | 618 | 15 more | 602 | 617 | 15 more |
| IO, IoDrain already acknowledged | 215 | 230 | 15 more | 214 | 229 | 15 more |
| IO, RoleReady owed | 475 | 491 | 16 more | 471 | 487 | 16 more |
| IO, RoleReady already acknowledged | 226 | 241 | 15 more | 225 | 240 | 15 more |

The added work is the call to the out-of-line owed test (four acquire loads: token, epoch, stage,
epoch; three compares) plus, in the EX pass, the FLIP-STAGE-HOLD armed check; it runs only on
non-Idle stages.

Code identity is **not** claimed: 63 function symbols changed size and 8 were added
(`docs/flipfix5/function-sizes.json`), including hot IO/EX bodies (`parse_and_dispatch`,
`flush_ready`, `run_loop`, `ExLoopT::execute`) whose executed counts above are identical: the
control-pass and DEBUG edits shift GCC's per-unit inlining and cross-jumping decisions (for
example, `execute<false,false>` now jumps to one shared inlined `wake_if_parked` copy instead of
calling it). `.text` is 8,659,639 bytes on POST/PAD-A, 336 fewer than PRE. This is what the
PAD-A layout control is for.

### Proof

All on CPUs 16–31 and ports 20200–20299, `LC_ALL=C` on every boot, against the POST arm
(`build/tomokv` = `build/flipfix5/arms/post/tomokv`, `230c841c…`).

| Proof item | Command | Result |
|---|---|---|
| Lane-relevant gate jobs, every leg, through the gate's job interface | `GATE_ONLY_JOBS='<61 jobs incl. prerequisites>' GATE_PROOF_NO_RATES=1 tests/gate.sh --server-cores 16-23 --load-cores 24-31 --ports 20200-20299` | **357 ok, 0 FAIL** (`docs/flipfix5/gate-partial.ledger`) |
| Re-run of the two flipfix5 jobs after DBSIZE NOW joined the live row | same, `GATE_ONLY_JOBS='flipfix5 flipfix5_units'` | **4 ok, 0 FAIL** (`docs/flipfix5/gate-partial-2.ledger`) |
| Differential vs Redis 7.4.10, split 6:2, io_uring | `GATE_DIFFER_NET_IO=uring tests/differ_gate.sh … 20220 20221 16-23 6:2` | **pass=475, fail=0**; seeds 7, 19, 20, 23 + rotating 21; 232/245 commands diffed |
| Same, epoll | `GATE_DIFFER_NET_IO=epoll …` | **pass=475, fail=0**; seeds 7, 19, 20, 23 + rotating 22 (`docs/flipfix5/differ.json`) |
| Gate self-tests | `python3 tests/gates_test.py` | **73 tests OK** (after the final gate.sh edit) |
| Builds and freshness | `make all`; the gate's `production_units` job built every `job_production_units` target (56 ready markers incl. core TSAN) | `make -q` returns 0 for `all`, all 51 unit targets and the 3 blockfix makefile targets (55 checks, `docs/flipfix5/freshness.json`); build warnings identical to PRE (53, same inventory) |

Jobs in the gate run: FLIP — `flip` (incl. the flipfix close/signal rows), `fliplisten`, `flipctl`,
`flip_unit`, `flipfix_units`, `flipfix5`, `flipfix5_units`, `core_units`; LB — `lb-stationary-1s`,
`lb-stationary-2s`, `lbplanner_units`, `moverfix`; txnorder — `txnorder_index`, `txnorder_wound`,
`txnorder2`, `txnorder_wake`, `txnorder-{fused,split}-{0,1}`; multirace and the other debug
batteries — `debug-0`, `debug-1`; atomics — `atomic_units` (incl. the flushfix FLUSH witnesses),
`atomic_batteries` (RYOW rate assertion omitted by `GATE_PROOF_NO_RATES`), `atomfix5_watch`,
`atomfix5_accounting`; read-local — `rlfix3_zc`, `rlfix3_info`, `rlcache`, `splitlocal_units`,
`feature-armed-{0,1}`; snapshot/SAVE — `snapshot-{epoll,uring}`, `snapfix_shutdown`,
`snapfix_bgsave_script`, `snapfix_bgsave_exec`, `snapfix2_tables`, `persistfix2_{lastsave,shutdown,
commands,errors}`, `persistfix_units`; database boundaries (whose control pass changed) —
`multidb-{1s,2s}-{0,1}-{0,1}`; split batteries `feature-split-{0,1}`.

**DQ = +3, DF = +3** (two serverless rows and one live row, all collected before the quick exit).
`EXPECT_QUICK`/`EXPECT_FULL` are unchanged (946/963); the maintainer's update is 949/966 plus the
three labels in the label fixture.

### Separate findings for the owner (not fixed here)

1. **FLIP vs a pipelined cross-owner MULTI/EXEC client (liveness).** While the client runs, a
   FLIP that must move its connection waits for it to become transferable, but FLIP's own
   dispatch pause holds the client mid-transaction; every such FLIP is refused at its 5 s
   deadline and the client stalls 5 s per FLIP. PRE 22/24, POST 17/24 step-1 EXEC attempts never
   completed a FLIP; no abort on either arm. A fix would touch FLIP's connection-transfer
   readiness (design-level), so it is reported, not attempted.
2. **LB control pass (observation, not investigated).** `lb_control_pass()` checks
   `lb_stage()` and later `lb_acked()`/`lb_ack()`, which recompute stage and epoch live. It cannot
   replay a stale stage the way FLIP did, but its `flip_quiesced()` test and `lb_ack()` can
   straddle an LB stage change. Worth a review with the same lens.

### Arms

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE (`e2b237926`) | `build/flipfix5/arms/pre/tomokv` | `5432534fb83d957ef7972d0df26f7e3e461069c8a4e8ad04bf6deeef1778b716` |
| POST (source `bec4a1e20`, built at `0586ee74a`, clean) | `build/flipfix5/arms/post/tomokv` | `230c841c9b313f9a2b4e82ee97536fa3593b7bc81ff9fefaacba991ca9c0363b` |
| PAD-A | `build/flipfix5/arms/pad-a/tomokv` | `29340cf7f37c0b1149d222223b3b8acb8aa37aeda3c520dec0891232e6c10260` |

PAD-A is the **(A) behaviour twin**: POST's exact ELF (sections, symbols, addresses) with 6
bytes changed — in each namespace's `Server::flip_stage_owed`, `je <live>` → `jmp <live>` and
`jne <stale>` → 2-byte NOP — which restores the pre-fix live-epoch test. Plan, offsets and the
before/after bytes: `docs/flipfix5/pad-a-plan.json` (`tools/flipfix5_artifacts.py`).

### Measurement request

No throughput claim is made. Please measure with the gate's instrument on a quiet box, PRE,
POST and PAD-A:

* the 14 generic cells and 2s GET/SET p1/p32 (expected null: zero added command-scope
  instructions, but GCC moved code in hot IO/EX bodies — POST vs PRE carries that layout, POST vs
  PAD-A isolates the behaviour, which only runs during FLIP);
* a FLIP episode-latency comparison (the fix adds 15–19 instructions to each non-Idle control
  pass), e.g. repeated `FLIP 4 4` / `FLIP 6 2` under modest load, reporting episode duration
  percentiles for PRE, POST and PAD-A.

NOT RUN (by rule, all maintainer-owned): `flip_saturated` (memtier load generator) and
`atomic_floor` (throughput floor); the full `tests/gate.sh iteration`; ABBA/perf cells; every
performance benchmark. `atomic_batteries` ran with its rate assertion omitted. Read-local-1
command-scope counts are not available from the established fixture (it calls the executor batch
entry with `read_local=0`); the live gate jobs above exercise the armed lane.
