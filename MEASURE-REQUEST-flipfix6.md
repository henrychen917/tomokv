# FLIP transaction-session handover

## flipfix6

Branch `cx-flipfix6`, PRE `e32b04a445b056976abb308aa598e356fcbaae74`.
Resumed from `fe0f82542`; implementation commit `44f561020`, additional proof
commit `139b498d3`. No push. **Implementation complete; extended proof in progress.**
D18.1 and the conservative D18.2 policy in resume addendum 2 are implemented.
No further owner decision is requested. D18.4 is not implemented.

A clean MULTI/WATCH session now moves with its Client through FLIP. Prepared
unpublished state refuses FLIP at IoDrain on any source. A pinned close refuses
a reversible FLIP before cleanup can publish to frozen executors. The ordinary
reply/order/error contract is unchanged; the new errors are FLIP refusals only.

### Witness and diagnosis retained

The original 40/40 PRE directed failures, P1/P2/P3 confirmation, five-second PING
stalls and exact deadline predicates remain in
[the witness report](docs/flipfix6/witness-report.md). No production change was
made before that witness. The extended v3 diagnostic captured 24 refusals over
16 fresh boots: eight ClientPrepare and 16 IoDrain. All 16 IoDrain failures held
finalized, published, retired EXEC states with only MVCC owner-record references:
zero tasks, WATCH refs, child debt, registered cuts and pending sessions. They
were transient reclamation work, not S2. The v4 diagnostic showed that repeated
FLIP wake completions starved the executor's idle cleanup sweep.

The two old v2 late-ack events and two old v1 missing-clause events remain
**NOT CAPTURED historically**. They were not reassigned a clause. The extended
diagnostic retained snapshots of acknowledged IOs as well; no corresponding
late-ack event recurred. Existing logs and compressed evidence remain under
`docs/flipfix6/`. The prior unsafe draft is historical, not the delivered POST.

### Implementation and invariants

`src/cmd/flip_session.inc` owns the cold session helpers. The FLIP-only readiness
requires `pending == nullptr`, exactly `watched_refs_ == session->watched.size()`
(or zero with no session), and every original drain condition. The count is of
installed physical aliases: one per key in db1, sixteen in db16. An excess or
missing pin refuses readiness. ROB, output/borrow, atomic groups, barriers,
retire queue, executor completion, directory and protocol-mode checks remain.
The shared LB readiness and zero-pin destruction predicate are unchanged.
Both transfer request and finish recheck choose FLIP readiness through
`hold_for_commit`; merely changing the first preflight would be insufficient.

The Client address, queue, queue-error state, ROB sequence, watched aliases and
monitor state survive the existing transfer. The WATCH registry still names
`Client*`, so a later foreign write reaches the moved connection. Every PRE
session reader (64 matches) and the new readers are classified in
[session-audit.md](docs/flipfix6/session-audit.md).

S2 is detected on the original IO during an owed IoDrain pass, before ExDrain.
It refuses on **both surviving and converting sources** with
`ERR FLIP refused: prepared but unpublished MULTI/WATCH state`.
The pending attempt, admission/apply credits, age, queue and owner IO stay
untouched. Idle after rollback allows the same state to publish. No skip/drop,
receipt, executor-credit discount, cancellation/reprepare or DEBUG hook exists.

A pinned close uses `ERR FLIP refused: a pinned connection closed`. The refusal
and ClientPrepare -> ClientCommit edge serialize through the existing error
mutex. Before that edge it rolls back; if commitment already won, the existing
pin holds cleanup until completion reaches Idle. Rollback after commitment is
not possible. No new WATCH cleanup is prepared or published while pinned. Both
IO engines' already-closing branch revisits the same idempotent cleanup before
the unchanged lifetime check: otherwise a deferred WATCH close would wait for
zero pins without ever initiating their removal. The close implementation,
SPSC safe point and re-mask themselves are unchanged.

The IoDrain reclamation starvation is resolved by invoking the existing bounded
`atomic_cleanup_cycle(64)` in an owed executor IoDrain control pass, before any
ExDrain acknowledgement. There is no new time constant, admission exemption,
MVCC rule or cleanup after the frozen-owner safe point.

INFO counters are `flip_session_clients_transferred`, `flip_refused_s2` and
`flip_refused_close`. Refusal counters count the winning reason once per episode;
the live row requires exact agreement between replies and counter deltas. No
S2-skip counter is exposed because the latest policy never skips a connection.

### Directed proof

The gate's `flipfix6` job boots every engine x atomic 0/1 x databases 1/16 leg
fresh for each case: EXEC storm, P1, P2, P3, active WATCH, semantic moves and
EXEC plus WATCH-close churn. A second pass runs EXEC and close churn with eight
clients per IO (48 session clients). Every EXEC reply must be an equal pair;
its sequence and final stored values must match every transaction sent. A moved
session counter must rise. Only the two exact immediate refusal reasons are
accepted; every FLIP episode, command gap and unrelated PING must stay below one
second. Close churn must actually raise its counter. PRE/PAD refusals are judged
separately at their existing five-second deadline, never counted as POST passes.

Semantic moves force the client off IO 5 with FLIP 1 7 and verify its new owner
and moved-session counter. Cases cover clean WATCH -> successful EXEC; foreign
write after movement -> nil EXEC; a queue spanning the move -> atomic `[1,1]`;
queue error -> EXECABORT without writes; DISCARD and RESET. Restore episodes
may retry only the exact approved close refusal, at most 64 fresh episodes.

Core fixture assertions cover exact aliases after completed/repeated WATCH,
UNWATCH, DISCARD, EXEC success/nil/EXECABORT and RESET/close cleanup, plus one
excess and one missing pin. Allocator injection covers WATCH preparation,
alias append rollback and successful retry for db1/db16; it is not an exhaustive
allocator-site proof. There are 16 prepared EXEC/WATCH cases (both database
settings, atomic modes and source kinds), and 36 close cases spanning IoDrain
through rollback/commit/install. Every closed WATCH retains all pins while
frozen and loses them through normal cleanup after Idle. LB's actual production
preflight also refuses a session in both linked namespace probes.

The directed gate run passed **18 rows, zero failures**, including all **72/72**
fresh-boot live cases. Across the 64 storm cases there were **1,478,476 FLIP
attempts**, **22,758 immediate close refusals**, and **zero S2 refusals**. The
largest observed FLIP was **17.586 ms**, PING was **17.524 ms**, and command
reply gap was **17.552 ms**. Every no-churn EXEC FLIP succeeded. All pairs,
reply counts, final values and session-move counters passed. These are
correctness stall observations, not throughput results.

Per-leg EXEC storm refusal counts (S2 is zero in every cell):

| Engine | Atomic | DBs | EXEC, 6 clients: completed | Close churn, 6 clients: refusals / attempts | EXEC, 48 clients: completed | Close churn, 48 clients: refusals / attempts |
|---|---:|---:|---:|---:|---:|---:|
| uring | 0 | 1 | 26,680 | 2,456 / 25,232 (9.73%) | 6,499 | 87 / 6,438 (1.35%) |
| uring | 1 | 1 | 28,071 | 2,495 / 25,357 (9.84%) | 6,470 | 104 / 6,377 (1.63%) |
| epoll | 0 | 1 | 28,716 | 2,661 / 26,445 (10.06%) | 6,457 | 89 / 6,403 (1.39%) |
| epoll | 1 | 1 | 30,066 | 2,601 / 26,494 (9.82%) | 6,477 | 88 / 6,414 (1.37%) |
| uring | 0 | 16 | 28,911 | 2,842 / 25,282 (11.24%) | 6,473 | 146 / 6,321 (2.31%) |
| uring | 1 | 16 | 28,801 | 2,713 / 24,815 (10.93%) | 6,331 | 148 / 6,403 (2.31%) |
| epoll | 0 | 16 | 29,705 | 2,945 / 25,545 (11.53%) | 6,460 | 131 / 6,293 (2.08%) |
| epoll | 1 | 16 | 29,430 | 3,107 / 25,357 (12.25%) | 6,398 | 145 / 6,246 (2.32%) |

The live storm did not naturally enter S2. Its refusal and unchanged-state
resumption are proved by the 16 deliberately prepared core cases, including
WATCH as well as EXEC. The expanded 54-assertion ASAN/UBSAN and TSAN run is
pending; the first gate run passed the earlier 46-assertion selection.
Per-case counters and timings are in [live-summary.json](docs/flipfix6/live-summary.json);
the full episode records are retained in the two compressed live-result files.

### Executed instruction counts

[comparison-all.json](docs/flipfix6/counts/comparison-all.json) contains 100 PRE/POST
pairs. The established serverless command-scope fixture was extended with MULTI;
production objects take link precedence. `tools/crlffix_step.c` steps an owned
child; executed NOPs count, library callees and fixture glue do not. No server,
load generator or rate measurement is involved.

**All 80 GET/SET/INCR/MGET/MSET cells are identical**, including every per-function
count: batch 1/32, 1s/2s, atomic 0/1 and both namespaces. Read-local execution is
not counted by this fixture (`read_local=0`); its live gate legs remain required.

MULTI INCR INCR EXEC totals (atomic 0 and 1 have the same counts):

| Namespace | Mode | Batch | PRE | POST | Added |
|---|---|---:|---:|---:|---:|
| db0 | 1s | 1 | 31,717 | 31,739 | 22 |
| db0 | 1s | 32 | 850,136 | 850,840 | 704 |
| db0 | 2s | 1 | 31,481 | 31,503 | 22 |
| db0 | 2s | 32 | 842,094 | 842,798 | 704 |
| normal | 1s | 1 | 33,722 | 33,762 | 40 |
| normal | 1s | 32 | 922,882 | 924,162 | 1,280 |
| normal | 2s | 1 | 33,495 | 33,536 | 41 |
| normal | 2s | 32 | 914,849 | 916,130 | 1,281 |

The extra instructions reflect compiler inlining changes in `txn_add_claim`,
`database_owned_key`, `ensure_state_slot` and `snapshot_prepare_write`, plus
one instruction in the normal split executor. No new EXEC hook executes.
Code identity and a MULTI performance improvement are not claimed.

| One production ClientPrepare pass | PRE normal | POST normal | PRE db0 | POST db0 |
|---|---:|---:|---:|---:|
| One connection without a session | 2,446 | 2,526 | 2,432 | 2,516 |
| One connection with an idle session | 649 | 2,556 | 649 | 2,546 |

PRE's session pass refuses readiness; POST prepares an actual transfer. This is
not an equal-work timing comparison. The empty-session case shows the extra
cold-control work. `.text` is 8,729,431 bytes on PRE and 8,726,423 on POST/PAD-A.

### Owner rulings

| Ruling | Status |
|---|---|
| D18.1: session queue, queue error and watched keys move with Client | Approved; implemented |
| Exact durable WATCH alias-count exception | Approved resume ruling; implemented; transient/excess pins still refuse |
| D18.2, resume addendum 2: S2 on any source refuses at IoDrain | Approved; implemented; original state/credits/IO retained |
| Pinned-close conservative refusal | Approved; precommit rollback, cleanup deferred behind existing pin through Idle |
| D18.4 receipt alternative | **Not implemented, owner decision after the freeze**; evidence in `docs/flipfix6/s2-exdrain-review.md` |
| SPSC masked monolith, block masks, ExDrain -> ExInstall re-mask and truth tables | Untouched |
| Global FLIP dispatch pause | Untouched; no frame publishes through it |
| Listener handover 2026-10-22, IO4.3/NT4.4 option (a) | Same operations/order; surrounding failure/commit serialization only |
| Five-second deadline and no new time constant | Untouched |
| txnorder claims, wound-wait, versions, FIFO hand-off | Untouched |
| Executor quiesce readiness and admission/apply fences | Untouched; no receipt/discount |
| Other connection readiness clauses | Untouched except the expressly approved session/WATCH exception |
| LB mover | Original session refusal and shared predicate retained |
| Single-owner writes, immutable replacement/QSBR, no reader retries/seqlocks, RYOW | Untouched |
| Layout locks and both thread modes | Release assertions pass; no locked field added/moved |
| D18.3 TLS, blocked BLPOP 0 and non-draining connections | No readiness changes; their liveness policy stays out of scope |

### Proof status and gate accounting

All commands and builds use CPUs 32-47 only, builds `-j16`; gate server CPUs
32-39, load CPUs 40-47, ports 20300-20399. Every server/oracle boot has `LC_ALL=C`.
Every correctness run uses the gate job interface and its own declared geometry;
no full iteration, performance benchmark or load-generator merit run is started.

The new jobs add two serverless rows at `collect_job flipfix6_units` and one live
row at `collect_job flipfix6`, at lines **6138 / 6352**, both **before** the quick-tier exit at line **6412**. **DQ=+3, DF=+3**.
`EXPECT_QUICK=977` / `EXPECT_FULL=994` are untouched; the owner update is **980 / 997**.
The existing planned-close test now asserts the approved prompt refusal while
retaining ownership/lifetime/quota checks. The BLPOP-held IoDrain signal test in
`tests/flipfix.py` is unchanged.

Completed: `make all`; all `job_production_units` targets; 58 `make -q` checks
([freshness.json](docs/flipfix6/freshness.json)); initial sanitizer core/FLIP rows;
command/control counts. The expanded WATCH-S2 sanitizer selection is pending.
Still running/pending: full requested live/gate matrix, both differential engines,
PAD-A negative control and final `python3 tests/gates_test.py`. These are not yet
claimed as passes. Any unresolved failure or NOT RUN item will be explicit here.

### Delivered arms and maintainer measurement request

| Arm | Path | SHA-256 |
|---|---|---|
| PRE e32b04a44 | `build/flipfix6/PRE` | `89f2fa028dbe7f05e2a4d9b0f799c6819a391debf8cf4de5506f57397621cf77` |
| POST | `build/flipfix6/POST` | `19f9b4a1f2a52c781ce338c4886c291f28f9e8d2c72ae265d8913d6528187b02` |
| PAD-A | `build/flipfix6/PAD-A` | `a943edf1437d9274b90624009bb26afd8f0356c6d625760b33d5f692530ef944` |

PAD-A is **(A) behaviour twin**, exactly as requested: POST's ELF with only the
FLIP-only session clause restored to PRE. Two bytes in each namespace change
(`je` past the pending-state rejection -> two-byte NOP); every non-null session
then returns false. All other bytes, section layouts and symbol addresses are
identical. POST's S2/close policy and bounded IoDrain cleanup remain in PAD-A.
[pad-a.json](docs/flipfix6/pad-a.json) records offsets and before/after bytes;
`tools/flipfix6_artifacts.py` rebuilds and verifies it.

Maintainer-only merit request: PRE, POST and PAD-A, the gate's instrument on the
quiet box, matched offered loads and its normal ABBA/null controls:

- [merit-cells.txt](docs/flipfix6/merit-cells.txt): the established generic 14 cells,
  plus explicit 2s GET/SET p1/p32 null cells. The p32 shapes also occur in the
  generic set; the separate labels retain the explicit null request. Rate at
  matched load decides merit; cycles/op, instructions/op and IPC explain it.
- FLIP episode latency for all three arms, with and without a session client:
  8 threads, 16 shards, initial 6:2, alternate FLIP 4 4 / FLIP 6 2; report
  completion/refusal counts and p50/p99/max duration separately. Session arm:
  same pipelined cross-owner MULTI INCR INCR EXEC partner; control: equivalent
  ordinary clients with no MULTI/WATCH history. Cover both engines, atomic modes
  and namespaces. PRE/PAD session refusal durations are results, not successful
  episode latencies. POST S2/close refusals must be separated by their counters.

**No throughput claim.** Performance cells, `flip_saturated`, `atomic_floor` and
the full `tests/gate.sh iteration` are **NOT RUN: maintainer-owned by instruction**.
`GATE_PROOF_NO_RATES=1` omits only the existing performance assertions in selected
correctness jobs. The correctness stall limits above are not a merit measurement.

Disk: superseded S2 arm binaries/source were removed after SHA/count retention;
non-delivery unit debug sections were compressed with every allocated section
verified unchanged (`debug-compression.json`). PRE/POST/PAD-A were not compressed.
The first directed run is archived in `gate-session-evidence.tar.gz`. Raw log
SHA-256s and counts are in `gate-session-archive.json`; repetitive per-tenure
timing lines/arrays were retired after recording their counts. Boot arguments,
exit records, control evidence and derived shutdown summaries remain. Further
cleanup follows the remaining proofs; target is under about 20 GiB in `build/`.
