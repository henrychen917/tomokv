# FLIP transaction-session handover

## flipfix6

Branch `cx-flipfix6`, base `e32b04a445b056976abb308aa598e356fcbaae74`. No push.
Witness and diagnosis delivered; **no production change**. D18.1 and D18.2 were
approved on 2026-10-31. A further, explicit requirement conflicts with active
WATCH transfer and needs an owner ruling before implementation.

### Additional blocker: durable WATCH references

The brief requires every other readiness clause, including watched references,
to stay unchanged. `Client::migration_protocol_idle()` at `src/net/conn.h:768`
requires `watched_refs_ == 0`. That count includes **durable WATCH registrations**,
not just in-flight work:

* `Shard::watch_add` (`src/cmd/multi.inc:3431-3455`) installs a
  `(Client*, generation, db, expiry)` entry and calls `client->watch_ref()`.
* `Shard::watch_remove` (`:3458-3474`) releases that pin. Normal WATCH retirement
  leaves it installed; otherwise a subsequent foreign write could not invalidate
  EXEC. The registry names the Client, not its IO thread.
* `multi_handle_io` (`:2205-2260`) installs one alias per physical namespace for
  each watched logical key. One active WATCH therefore retains 1 pin with
  `--databases 1`, or 16 pins with `--databases 16`.
* `flip_drain_idle()` deliberately omits the watched-reference check. IoDrain
  finishes, but ClientPrepare cannot accept a live WATCH with the stipulated
  zero-reference clause, even if the session clause is changed to `!pending`.

First diagnostic active-WATCH witness, uring/atomic 0/databases 1, fresh 6:2 boot:

```text
planned epoch=1 io=5 session=1 pending=0 drain=1 migration=0 watched_refs=1 watched_keys=1
planned epoch=1 io=4 session=1 pending=0 drain=1 migration=0 watched_refs=1 watched_keys=1
failure epoch=1 stage=5 deadline=1 error=ERR FLIP cannot quiesce a connection: connection ROB, reply, borrow, or owner-local protocol state is busy
```

Stage 5 is ClientPrepare in the db1 namespace (stage 8 in the multi-DB namespace).
The diagnostic source is generated inside this worktree's ignored build tree by
`tools/flipfix6_diag.py`; production source and PRE remain untouched.

**Proposed additional ruling (not implemented):** after IoDrain/ExDrain, the
FLIP-only readiness check may retain durable WATCH registry pins on the same
Client. Preserve the shared LB check and the destruction/lifetime checks. A
conservative implementation can require no S2 and require the reference count
to equal the number of session-owned installed WATCH aliases, rather than zero;
any transient/excess pins still refuse readiness. This needs a proof that the
session's alias count is exact after completed WATCH, repeated WATCH, UNWATCH,
RESET, EXECABORT, database boundaries and allocation failure. Simply deleting
the watched-reference guard is not the proposal.

This is outside the explicit "every other clause stays" instruction, despite
being consistent with the intended D18.1 behaviour. Implementation is paused
pending that narrow ruling; the requested witness and reader audit continue.

### Step 1: witness and predicate

`tests/flipfix6.py` adapts the EXEC partner's exact pipelined MULTI/INCR/INCR/EXEC
sequence, verifies equal replies and exact final values, and places a session on
every IO. It covers P1 (one EXEC then only GET), P2 (WATCH/UNWATCH then GET), P3
(serial same-owner transactions), and active WATCH. An independent PING worker
records its largest wait. The PRE expectation requires a deadline refusal and
a real >=4 s stall; an unopened window fails.

All **40/40** directed PRE cases reproduced the refusal: five cases on each of
the eight 2s legs, each on a fresh boot. Every refusal was in **ClientPrepare**
at the deadline. FLIP duration was 5.000-5.017 s; the unrelated PING waited
4.996-5.014 s, and every worker on every IO had a >=4 s reply gap. All servers
exited cleanly; reply/value checks passed after the refusal. These are liveness
witness durations, not performance measurements.

| 2s leg | EXEC refusal (s) | P1 (s) | P2 (s) | P3 (s) | Active WATCH (s) | Largest PING wait (s) |
|---|---:|---:|---:|---:|---:|---:|
| uring / atomic 0 / db1 | 5.000 | 5.000 | 5.000 | 5.000 | 5.001 | 5.001 |
| uring / atomic 1 / db1 | 5.000 | 5.000 | 5.002 | 5.000 | 5.003 | 5.003 |
| epoll / atomic 0 / db1 | 5.014 | 5.010 | 5.017 | 5.001 | 5.006 | 5.014 |
| epoll / atomic 1 / db1 | 5.004 | 5.005 | 5.012 | 5.002 | 5.003 | 5.009 |
| uring / atomic 0 / db16 | 5.012 | 5.003 | 5.007 | 5.007 | 5.008 | 5.011 |
| uring / atomic 1 / db16 | 5.004 | 5.008 | 5.015 | 5.009 | 5.012 | 5.011 |
| epoll / atomic 0 / db16 | 5.004 | 5.012 | 5.002 | 5.010 | 5.013 | 5.013 |
| epoll / atomic 1 / db16 | 5.001 | 5.000 | 5.002 | 5.000 | 5.000 | 5.003 |

For EXEC/P1/P2/P3, `flip_drain_idle=1`, `watched_refs=0`, session non-null and
`pending=0`: **the session-pointer clause is the sole protocol-idle failure**.
For active WATCH, both the session-pointer clause and the watched-reference
clause fail. The watched-reference count is exactly 1/16 in db1/db16,
respectively. No S2 was observed in **120 planned session-connection occurrences
out of 180 planned connection occurrences**. That bounded sample is not a
claim that S2 cannot occur.

The unchanged `tests/flipfix5.py --case op-flip --op EXEC` also ran on all eight
legs, both on PRE and on the diagnostic copy. Its uncontrolled placement may
leave the session on a surviving IO: PRE saw ten refusals on five legs, with
three legs completing FLIPs. Diagnostic v1 saw eleven refusals on six legs.
Nine were ClientPrepare/session-pointer failures; **two were IoDrain** before
planning, so they cannot be attributed to `migration_protocol_idle`. The first
diagnostic did not record the IoDrain clause; a second diagnostic adds per-IO
atomic snapshots of the exact drain conditions to investigate those separately.
The original driver's `pass` classification permits refusals if any FLIP
completed; it is not the POST acceptance criterion of the new witness.

Diagnostic v2 reran the unchanged partner twice per leg (16 fresh boots):
28 refusals, comprising 12 ClientPrepare/session-pointer failures and 16
IoDrain failures. Fourteen IoDrain dumps identify **only
`!multi_deferred_.empty()`** as false readiness (`mask=256`, bit 8 in the
diagnostic). Both epoll atomic modes and both database configurations reproduced
that earlier-stage blocker. Two more IoDrain failures had no unacknowledged IO
left by the dump; their exact clause is **NOT CAPTURED**. The two v1 IoDrain
clauses are likewise **NOT CAPTURED**, rather than retrospectively assigned the
v2 diagnosis. All 40 directed ClientPrepare refusals and all 12 v2
ClientPrepare refusals have exact clause records.

This partially refutes the brief's premise about the EXEC workload: successful
IoDrain does retire in-flight work, but the original partner can also exhaust
the deadline while waiting for deferred transaction state reclamation. A
ClientPrepare-only fix cannot resolve those episodes. `multi_reap_deferred`
(`multi.inc:3121-3130`) waits for `multi_records_done` (record/watch references
and child records, `:517-523`). The retained reference/root reclamation cause
has **not** been diagnosed beyond that clause. No drain predicate, transaction
state lifetime or txnorder rule has been weakened. Treat this as a separate
owner review item before promising every EXEC-workload FLIP completes.

The two original-driver diagnostic sets observed another 9 and 12 planned
session-connection occurrences respectively, all with `pending=0`. Across the
recorded diagnostics: **0 S2 / 141 planned session occurrences**, within 214
total planned-connection occurrences. No inference that S2 is impossible.

Evidence: `docs/flipfix6/diagnosis-results.json`,
`docs/flipfix6/diagnosis-diagnosis.json`, and the `legacy-*-results.json` /
`legacy-diagnostic-diagnosis.json` files. Every directed refusal has its epoch,
stage, planned connections and failing clauses recorded; compressed server logs,
argv and clean-exit receipts are under `docs/flipfix6/diagnosis/`.

Runtime: `LC_ALL=C` for every boot, 16 shards, ratio 6:2, read-local/key-LB/client-LB/
automatic-FLIP off. Original partner servers used CPUs 32-39, port 20300; the
directed diagnostic servers used CPUs 40-47, port 20310. Harnesses/builds stayed
within CPUs 32-47; builds used `-j16`. No other lane's processes were touched.

### Session-reader audit

Completed source audit: [session-audit.md](docs/flipfix6/session-audit.md), with
all 64 source matches in [session-readers.txt](docs/flipfix6/session-readers.txt).
It covers both parser copies, fused/read-local eligibility, both LB selectors,
all `MultiSession` accessors and ownership transitions, retirement/close,
CLIENT/MONITOR and tracking. The queue keeps global registry specs; climon map
nodes already move through the existing routing transfer. Pending state is the
IO-bound member. Durable WATCH pins are the extra readiness blocker above.

### Owner rulings

| Ruling | Status |
|---|---|
| D18.1: FLIP transfers session state without S2 | Approved; implementation paused on the durable WATCH pin contradiction |
| D18.2: S2 stays on surviving source / immediate refusal on converting source | Approved; not implemented yet |
| Every other readiness clause, including watched references | Untouched; the zero-reference clause needs the additional decision above |
| SPSC masked monolith, block masks, ExDrain -> ExInstall re-mask, truth tables | Untouched |
| Global FLIP dispatch pause | Untouched |
| Listener handover 2026-10-22, IO4.3/NT4.4 option (a) | Untouched |
| Five-second deadline; no new time constant | Untouched |
| txnorder claims, wound-wait, versions, FIFO hand-off | Untouched |
| LB client mover and shared readiness predicate | Untouched |
| Single-owner writes, immutable replacement/QSBR, no reader retries/seqlocks, RYOW | Untouched |
| Layout locks; both thread modes; main-command instruction cost | No production change |

### Gate counts and artifacts

No gate row is registered yet: **DQ=0, DF=0**, counted by `collect_job` lines
relative to the quick exit. `EXPECT_QUICK=977` and `EXPECT_FULL=994` are untouched.

PRE: `build/flipfix6/PRE`, SHA-256
`89f2fa028dbe7f05e2a4d9b0f799c6819a391debf8cf4de5506f57397621cf77`.
POST and PAD-A do not exist: production implementation is paused as above.
Diagnostic-v1 and v2 hashes/provenance are in `docs/flipfix6/artifacts.json`;
neither diagnostic is a POST candidate or a PAD arm.
There is no throughput claim.

### Verification status

| Requested proof | Status |
|---|---|
| `make -j16 all` on e32b04a44; `make -q all` freshness | PASS; freshness exit 0; layout assertions compiled |
| Unchanged flipfix5 EXEC partner, all eight 2s legs | RUN on PRE and diagnostic PRE; refusals and all clean exits retained above |
| Directed EXEC/P1/P2/P3/active-WATCH + unrelated PING, all eight legs | 40/40 confirmed PRE failures using `--expect pre`; exact reply/value accounting retained |
| `python3 tests/gates_test.py` | PASS, 76 tests on the final idle run with `LC_ALL=C GATE_TEST_PORT=20390`. Earlier idle run also passed 76; the first, concurrent run failed five scheduler fixtures at their unchanged 45 s timeout. Logs retained |
| Python syntax checks for new witness/diagnostic/archive tools | PASS |
| New `flipfix6` live gate row and ASAN/UBSAN/TSAN core fixture units | NOT RUN / not registered: production implementation paused on the preserved WATCH clause |
| Every FLIP gate job: `flip`, `fliplisten`, `flipctl`, `flip_unit`, `flipfix_units`, `flipfix5`, `flipfix5_units`, `core_units` | NOT RUN through the job interface: no candidate implementation; the standalone EXEC-partner run is not substituted for these jobs |
| LB: `lb_stationary`, `lbplanner_units`, `moverfix` | NOT RUN: no candidate implementation |
| txnorder: `txnorder`, `txnorder2`, `txnorder_index`, `txnorder_wake`, `txnorder_wound`, `txn_group_fused/split` | NOT RUN: no candidate implementation |
| `multifix`, `blockmulti`, `execfair`, `multirace`, debug batteries | NOT RUN: no candidate implementation |
| `atomfix5_watch`, `datafix2_watch`, `atomics`, `multidb`, `snapfix_bgsave_exec` | NOT RUN: no candidate implementation |
| `tls`, `netfix_tls`; BLPOP-held IoDrain row | NOT RUN: no candidate implementation; existing test and production behaviour untouched |
| Redis 7.4 oracle; standard differential seeds on both engines | NOT RUN: no candidate implementation |
| Every `job_production_units` target + freshness | NOT RUN: production change paused; only `make all` / its freshness completed |
| POST storm, moved-session/S2 counters, semantic-after-move cases, forced S2 policies | NOT RUN / not implemented because the extra ruling is pending |
| Main-command/MULTI instruction scopes; ClientPrepare counts | NOT RUN: no POST exists for comparison; no zero-instruction measurement claim |
| Performance benchmarks, load generators, full iteration gate | NOT RUN: explicitly reserved for maintainer |

The implementation pause follows the brief's instruction to stop and provide
evidence/proposal if a correct fix requires changing a preserved rule. It is not
a request to reapprove D18.1 or D18.2. The additional question concerns only the
durable WATCH-reference clause. All pending proof remains required if that
exception is approved and implementation resumes.

The two earlier harness runs used its default ephemeral port for its synthetic
socket ownership checks; that was outside the lane's requested listening-port
range. The final complete run explicitly set `GATE_TEST_PORT=20390`. Every
TomoKV boot used 20300 or 20310 and the requested CPU ranges.

### Reproduction commands

From this worktree (correctness only):

```sh
taskset -c 32-47 env LC_ALL=C python3 tests/flipfix6.py \
  --binary build/flipfix6/PRE --cores 32-39 --port 20300 --expect pre \
  --cases exec p1 p2 p3 watch --output build/flipfix6/reproduce-pre

taskset -c 32-47 python3 tools/flipfix6_diag.py
taskset -c 32-47 env LC_ALL=C make -C build/flipfix6/diag-source -j16 all
taskset -c 32-47 env LC_ALL=C python3 tests/flipfix5.py \
  --case op-flip --op EXEC --binary build/flipfix6/diag-source/build/tomokv \
  --cores 32-39 --port 20300 --seconds 6 --attempts 2 \
  --output build/flipfix6/reproduce-partner

taskset -c 32-47 env LC_ALL=C GATE_TEST_PORT=20390 python3 tests/gates_test.py
```

Build storage was about 3.0 GiB before removing superseded diagnostic-v1
artifacts. Raw superseded diagnostic logs are archived compressed with hashes
and counts. No server or harness child remains running. No push was made.

After the additional ruling and implementation, the maintainer's request remains
the 14 generic cells plus 2s GET/SET p1/p32 null cells, and FLIP episode latency
for PRE/POST/PAD-A with/without session clients (PRE refusal durations).
PAD-A must be labelled **A: behaviour twin**, POST's ELF with the FLIP-only
session clause restored to PRE, preserving text size/layout. No performance run
has been started by this lane.
