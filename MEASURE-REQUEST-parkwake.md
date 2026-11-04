# Lane correctness record

## parkwake

PRE `8be4f68323` (origin/cpp, the published wave 15). Worktree `/home/user/Projects/cx-parkwake`,
branch `cx-parkwake`, never pushed. CPUs 32-63 only, ports 23300-23399, `LC_ALL=C` on every boot.
AGENTS.md does not exist in the worktree or in /home/user/Projects; PROJECT.md was read. This is a
correctness record: it makes no throughput claim. Findings source:
`round5-read/bounded-queue-wake-audit.md` (F1, F2, F3, F10, F11, F12 and the namespace-drain
watchdog).

Every witness below is a gate row in `tests/gate.sh` (job bodies `tests/parkwake.py` and
`build/parkwake-unit`), run on four arms:

- **PRE**: production build of `8be4f68323`.
- **PRE-diag**: PRE plus item 0 only, built with `make park-net-arm`. Every park's missed-wake safety
  net is 2 s instead of 50 ms, so a lost wake becomes a multi-second stall.
- **POST-diag**: the final source, built the same way.
- **POST**: the final production build.

Unless a row says otherwise, "all" means both modes (2s, 1s), both engines (uring, epoll) and both
namespaces (16 databases, 1 database).

### Result

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| 0 Instrument | n/a | `src/base/park_net.h`, `make park-net-arm` (`PARK_NET_MS`, default 2000). The production code is unchanged: at the item-0 commit, `.text`, `.data`, `.data.rel.ro`, `.tdata`, `.init_array` and `.eh_frame` are byte-identical to PRE; only the build's git-dirty string differed. `TOMO_MDBQSBR_LIVE_PARK` is now its 5,400 ms instance | the park timeouts read `kParkNetMs` | none |
| 1 F2 script livelock | `script-2s-{uring,epoll}`, both namespaces: no reply within 5 s ("executor livelocked"), on PRE and on PRE-diag | all 305 replies arrive (blocker + 300 RPOPLPUSH + 4 two-key EVALs): 133 OK and 172 errors "cross-shard second hop queue is full". POST-diag the same | a `ScatterFinish::Retry` (script wave refused for lane room) parks in `atomic_deferred_`, not in `xshard_retries_`, so the inbox drain keeps running | the 172 lane-full error replies (pre-existing; audit T6) are not Redis behaviour. Out of this lane's scope |
| 2 F1 retry lane | (a) **served half**: EXEC+PUBLISH and EXEC+SUBSCRIBE take 1.0-1.25 s per call on PRE (every call, all modes, engines, namespaces) and 28-36 s on PRE-diag. (b) **lane-wake half**: on a diag twin of POST with only the park predicate removed, **21 two-second stalls in about 4,500 calls** (EXEC+PUBLISH 8, EXEC+PUBLISH with a hot owner 5, EXEC+SUBSCRIBE 8; every mode and engine) | POST: every EXEC form ≤ 0.21 ms; the forced script escalation ≤ 3.5 ms, as on PRE. POST-diag with the same 200-call forms: **0 stalls in 4,800 calls** (max 4.9 ms) | every park branch (8, including the R7 copies) re-checks the lane head (seq_cst) after `arm_blocked()`. The IO's own EXEC/redispatch completions are now `enqueue_serve`d, where before they were only `mark_active`d | the FIFO question: see [below](#fifo-fairness-f1-question) |
| 3 F3 DatabaseExDrain | `build/parkwake-unit` F3 schedule built against PRE objects: `FAIL ... executor owing the DatabaseExDrain ack reported no work (would park)` | unit PASS (5/5 schedules) | `flip_control_pass` returns 1 while the ack is owed | the live window is not reachable on this box: the swapdb diagnostic gives SWAPDB p50 250 ms on PRE-diag and POST-diag alike, with no 2 s stall. The unit is the proof |
| 4 SWAPDB watchdog | SWAPDB during a 4.4 s SORT: **SIGABRT** "fatal: database namespace drain timeout elapsed_ms=2706-2743" on all 4 legs, on PRE and on PRE-diag | SORT 4.41-4.51 s, then SWAPDB OK at the same instant, server alive, exit 0 (all 4 legs on POST and POST-diag) | the drain deadline restarts while a participant is inside one pass across two monitor ticks, while an IO still holds an unfinished op, or while the boundary's own op runs. Clamped to the monitor's clock sample (see the POST-diag finding below) | none known |
| 5 F10 control wakes | PRE: the CONFIG SET appendonly rendezvous takes 49-51 ms per call (except 1s-epoll, 0.4 ms); CLIENT UNPAUSE 11-50 ms; DEBUG CLIENT-LB 41-43 ms in every 2s leg (one call per leg). PRE-diag: rendezvous 2.0 s, UNPAUSE 1.9 s, CLIENT-LB 1.99 s in one of four legs | POST: rendezvous ≤ 1.1 ms, UNPAUSE ≤ 0.02 ms, CLIENT-LB ≤ 0.14 ms. POST-diag passes | the rendezvous announce callback rings every member. UNPAUSE rings every other worker. The monitor thread rings the coordinator of an automatic FLIP or of an LB PlanReady. A deferred PlanReady keeps polling. A CLIENT-LB move rings its source | no live witness for automatic FLIP or LB PlanReady (NOT RUN, see below) |
| 6 F11 epoch through sleep | 16 databases: every server-side fd release takes 50-90 ms (p50 50 ms; 199-200 of 200 over 20 ms). PRE-diag: 2.0 s. The 1-database control: 0.05 ms | ≤ 0.09 ms in every leg, 0 misses (POST and POST-diag) | every IO, fused and executor blocking wait is bracketed by `park()`/`resume()`. The epoch is even while asleep | 16-database client-LB: the executor-fence policy refuses the move on PRE and POST alike, so it is not a wake defect. Proposal below |
| 7 F12 notices beyond 1,024 | 2,200 slot-less BLPOP clients on one IO, served by one RPUSH: slowest reply 1.06-1.43 s per leg, with 8,866-11,760 notices dropped. PRE-diag: in 5 of 8 legs, 804-1,176 replies still missing after 3 s (2 legs delivered within 22 ms; 1 leg never got all clients blocked) | slowest reply 15-27 ms per round, every reply delivered. 9,010-11,760 refused notices, all kept and reposted | a refused notice keeps its claim and is queued per worker (`Server::notify_retries_`). It is reposted every pass and counts as work, and `flip_quiesced` waits for it | none |

**Found by the POST-diag matrix and fixed: item 4's first version could abort the server.**
- The draining IO spins and stamps `drain_waiting_ms` from its own clock. If it stamps after the
  monitor sampled `now`, `now - start` wraps around, and a boundary that had just restarted its
  deadline is reported overdue.
- Witness: watchdog-2s-epoll on POST-diag aborted with "elapsed_ms=2136". That is below the
  2,700 ms bound, which only a wrap explains.
- Fix `2646077e16`: clamp the start to `now`. All 45 POST and POST-diag rows pass after it.
- Before the clamp it hit 1 of 12 watchdog legs (8 POST, 4 POST-diag). The window is a few hundred
  nanoseconds per monitor tick (every ≤ 50 ms) while an IO spins in DatabaseIoDrain, so production
  would have hit it too.

### Commits

| Commit | Content |
|---|---|
| `dd40e3c4d4` | item 0: test-only missed-wake diagnostic |
| `acfd49982d` | item 1 (F2) |
| `ae0bc734e4` | item 2 (F1) |
| `3fa761c357` | item 3 (F3) |
| `0d8555ed18`, `2646077e16` | item 4, and the clamp found by the POST-diag matrix |
| `e4b84ff485` | item 5 (F10) |
| `3123074504` | item 6 (F11) |
| `88d970703a` | item 7 (F12) |
| `5c14bc00ed`, `33d26ce96a`, `8805877673` | gate rows: tests/parkwake.py, tests/parkwake_unit.cc, tests/parkwake_slowsync.c, gate.sh, Makefile rules. `8805877673` makes the watchdog row assert its window |
| `07e3f45302`, `d49c5109a9` | census tooling; size-compensated inline budgets |
| `d1513fe2ed` | tools/lbosc3_pad.py: the source proof accepts the four monitor-thread wake lines (as cfgfix did for its gates) |
| `ddc260a3b7`, `d64ac09019` | receipts (docs/parkwake) |
| `ad7bc62d70`, `52eb30b951` | the proof loop keeps failing run directories; its timeout is configurable |

### Production diff

`git diff --stat 8be4f68323 HEAD -- src Makefile`: 20 files, +311/-57. In `src`: 19 files, +276/-40.
The Makefile part is the diagnostic target, two rules for the unit and the preload helper, and 18
inline budgets. Per item:

- **Item 0.** `src/base/park_net.h` (new) defines `kParkNetMs` and `kParkNetStretched`: 50 and
  false unless a test build defines `TOMO_PARK_NET_MS`. Three places read it:
  - the default of `Ring::submit_and_wait` (`src/net/uring.h`; the old `TOMO_MDBQSBR_LIVE_PARK`
    override is removed);
  - `IoLoop::idle_timeout_ms()`, which drops the cron-beat cap only when stretched;
  - both executor parks in `ex_loop.h`.
- **Item 1 (F2).** `ex_execute.inc` `execute()`: Retry → `atomic_deferred_`.
- **Item 2 (F1).**
  - `io_loop.h` `run_loop` and its generated R7 copy in `reorder.cc`: the retry-lane predicate in
    every park branch, plus `multi_retry_lane_note_pending()`, a cold helper in `multi.inc`.
  - `multi.inc` `multi_owner_pass_entry_impl`: three `enqueue_serve()` calls.
- **Item 3 (F3).** `ex_loop.h` `flip_control_pass`.
- **Item 4.** `multidb.cc`/`.h`: `drain_deadline_start()`, `note_drain_waiting()` and the
  monitor-only state in the heap `State`. `DatabaseMap` stays 120 bytes. `io_loop.h`
  `database_control_pass` makes two `note_drain_waiting()` calls.
- **Item 5 (F10).**
  - `Server::wake_peers_from()` (`server.h`).
  - The announce callback of `DebugSleepCoordinator::exclusive()` (`debug_sleep.h`, `fliplisten.cc`).
  - The waker argument of `command_client_pause()` (`client_pause.h`, `climon.cc`,
    `multi_execute.inc`, `multi.inc`).
  - The wake-only ring of `monitor_controllers()` and the source ring of `lb_debug_move_client()`
    (`lbplanner.cc`).
  - The PlanReady deferral of `lb_control_pass` (`io_loop.h`).
- **Item 6 (F11).** `ClientWorkScope::park()/resume()` and the `DatabaseWorkScope` forwarders
  (`server.h`; no-ops in the single-database namespace). Four IO parks, two executor parks and the
  R7 copies are bracketed.
- **Item 7 (F12).**
  - `Server::notify_retries_` with `defer_completion_notice()` (`server.h`, appended at the tail).
  - `notify_sender_to()`, `service_notify_retries()` and `notify_retries_pending()`
    (`ex_loop.h`), with the pass call sites and `flip_quiesced()`.
  - `blocking_notify_sender()` (`blocking.inc`).
  - The `notify_drop` comment (`signal.h`).

Layout locks all still hold: `Op` 336, `Client` 1984, `ThreadCtx` 1408, `Shard` 1440, `FlatStore`
944, `Rob<64>` 192, `AtomicEntry` 144, `Config` 624, `ExLoop` 5856/5864, `DatabaseMap` 120 and
`MultiRetryLane` 64. `Server` grows by 3,072 bytes at its tail.

### Why each wake is no longer lost

- **F1, retry lane.**
  - Producers CAS the lane head (seq_cst, a locked RMW) and then read `parked_` for their
    conditional wake.
  - The IO stores `parked_`, fences seq_cst (`arm_blocked`), then loads the head seq_cst.
  - So either the IO sees the node and does not wait, or the producer sees `parked_` and rings it.
    This is the Dekker pair of `ReadyMask::set` + `wake_if_parked`. The FLUSH producer keeps its
    unconditional `msg_to`.
  - The served half: a Done op is retired only from `pending_serve_`, so a completion made on the
    IO itself must be `enqueue_serve()`d.
- **F2.**
  - `atomic_deferred_` is serviced every pass and in `sweep()`. It counts held heads as work, is
    part of `flip_quiesced()`, and never gates `drain_tasks()`.
  - The executor keeps draining its own lane, so the refused post finds room.
  - The connection holds the scatter barrier, so no younger task of it can overtake the re-post.
- **F3.** The executor never reaches its empty-pass budget while the ack is owed, so it sees the
  IO's retirement on its next pass. The FLIP and LB drains already do this.
- **F10.** Each publication is followed by a Wake to the workers that must act:
  - all workers for the rendezvous and UNPAUSE;
  - the coordinator for an automatic FLIP or a PlanReady;
  - the source for DEBUG CLIENT-LB.

  A deferred PlanReady keeps its coordinator polling.
- **F11.**
  - A parked worker publishes an even epoch. `client_executor_quiesced()` waits only for scopes
    that were odd when sampled, so a park now ends the wait.
  - The epoch protects Client pointers held by in-pass code. A blocked thread holds none, and the
    epoll park's callbacks only mark this thread's own connections.
  - The database-map QSBR is acknowledgement-based and does not read peers' parity.
- **F12.**
  - A refused notice keeps its claim (`retire_queued`), so the client can be neither released nor
    migrated.
  - The owner reposts it every pass. The IO cannot park on a non-empty channel, so the channel
    drains and the repost lands.
  - No thread spins in place on a full channel.
- **Item 4.**
  - A boundary that waits for a command is no longer "overdue". The deadline restarts while any
    participant is inside one long pass, while any IO still holds an unfinished op, and while the
    boundary's own op executes.
  - A boundary that shows none of these for the whole bound is still reported, so the watchdog
    still catches a stuck control path. Redis runs SWAPDB after the command in progress.

### Proof: the four arms, job body by job body

`tools/parkwake_matrix.py` runs the gate rows' own job body (`tests/parkwake.py`, one invocation
per gate row) on every arm: server CPUs 32-39, load 40-47, port 23300, `--hz 1 --dynamic-hz no`.
Each cell shows the slowest event per leg; for retry that is the slowest EXEC form.

- control columns: CONFIG rendezvous / CLIENT UNPAUSE / DEBUG CLIENT-LB (2s only).
- PRE and POST call counts are the gate defaults. The diag arms run fewer calls (a miss costs 2 s
  there) and stop a form after three misses.
- swapdb (F3's live attempt) runs only on the diag arms.

Arms:

- PRE: `13dbf1e2`.
- PRE-diag: `6b7a1a9f`.
- POST-diag: `ee3bc054`, the final source.
- POST: `4023172c`.

| Row | PRE | PRE-diag | POST-diag | POST |
|---|---|---|---|---|
| retry-2s-uring | FAIL: db16 1.1 s; db1 1.1 s | FAIL: db16 34.0 s; db1 34.0 s | PASS: db16 0.22 ms; db1 0.21 ms | PASS: db16 0.21 ms; db1 0.20 ms |
| retry-2s-epoll | FAIL: db16 1.2 s; db1 1.2 s | FAIL: db16 32.0 s; db1 36.0 s | PASS: db16 0.21 ms; db1 0.17 ms | PASS: db16 0.20 ms; db1 0.18 ms |
| retry-1s-uring | FAIL: db16 1.1 s; db1 1.2 s | FAIL: db16 34.0 s; db1 32.0 s | PASS: db16 0.20 ms; db1 0.21 ms | PASS: db16 0.18 ms; db1 0.18 ms |
| retry-1s-epoll | FAIL: db16 1.2 s; db1 1.2 s | FAIL: db16 32.0 s; db1 32.0 s | PASS: db16 0.21 ms; db1 0.18 ms | PASS: db16 0.21 ms; db1 0.18 ms |
| control-2s-uring | FAIL: db16 50 ms/50 ms/41 ms; db1 50 ms/50 ms/43 ms | FAIL: db16 2.0 s/1.9 s/0.76 ms; db1 2.0 s/1.9 s/0.74 ms | PASS: db16 0.96 ms/0.03 ms/0.13 ms; db1 0.40 ms/0.02 ms/0.12 ms | PASS: db16 0.42 ms/0.01 ms/0.12 ms; db1 1.09 ms/0.02 ms/0.12 ms |
| control-2s-epoll | FAIL: db16 51 ms/11 ms/42 ms; db1 50 ms/50 ms/42 ms | FAIL: db16 2.0 s/1.9 s/2.0 s; db1 2.0 s/1.9 s/0.75 ms | PASS: db16 0.37 ms/0.01 ms/0.14 ms; db1 0.36 ms/0.02 ms/0.14 ms | PASS: db16 0.37 ms/0.01 ms/0.14 ms; db1 0.36 ms/0.02 ms/0.12 ms |
| control-1s-uring | FAIL: db16 49 ms/50 ms/-; db1 49 ms/50 ms/- | FAIL: db16 2.0 s/1.9 s/-; db1 2.0 s/1.9 s/- | PASS: db16 0.91 ms/0.02 ms/-; db1 0.46 ms/0.01 ms/- | PASS: db16 0.49 ms/0.01 ms/-; db1 0.92 ms/0.02 ms/- |
| control-1s-epoll | FAIL: db16 0.40 ms/42 ms/-; db1 0.40 ms/42 ms/- | FAIL: db16 0.40 ms/1.9 s/-; db1 0.41 ms/1.9 s/- | PASS: db16 0.48 ms/0.03 ms/-; db1 0.45 ms/0.01 ms/- | PASS: db16 0.46 ms/0.01 ms/-; db1 0.89 ms/0.01 ms/- |
| epoch-2s-uring | FAIL: db16 90 ms; db1 0.07 ms | FAIL: db16 2.0 s; db1 0.07 ms | PASS: db16 0.10 ms; db1 0.06 ms | PASS: db16 0.08 ms; db1 0.07 ms |
| epoch-2s-epoll | FAIL: db16 88 ms; db1 0.07 ms | FAIL: db16 2.0 s; db1 0.07 ms | PASS: db16 0.10 ms; db1 0.06 ms | PASS: db16 0.09 ms; db1 0.07 ms |
| epoch-1s-uring | FAIL: db16 89 ms; db1 0.31 ms | FAIL: db16 2.0 s; db1 0.07 ms | PASS: db16 0.10 ms; db1 0.07 ms | PASS: db16 0.09 ms; db1 0.07 ms |
| epoch-1s-epoll | FAIL: db16 88 ms; db1 0.07 ms | FAIL: db16 2.0 s; db1 0.07 ms | PASS: db16 0.09 ms; db1 0.07 ms | PASS: db16 0.08 ms; db1 0.07 ms |
| slotless-2s-uring | FAIL: db16 1.3 s; db1 1.4 s | FAIL: db16 replies missing at 3 s; db1 replies missing at 3 s | PASS: db16 28 ms; db1 27 ms | PASS: db16 27 ms; db1 27 ms |
| slotless-2s-epoll | FAIL: db16 1.4 s; db1 1.2 s | FAIL: db16 replies missing at 3 s; db1 replies missing at 3 s | PASS: db16 26 ms; db1 26 ms | PASS: db16 26 ms; db1 26 ms |
| slotless-1s-uring | FAIL: db16 1.3 s; db1 1.1 s | FAIL: db16 unarmed; db1 22 ms | PASS: db16 24 ms; db1 21 ms | PASS: db16 20 ms; db1 20 ms |
| slotless-1s-epoll | FAIL: db16 1.2 s; db1 1.4 s | FAIL: db16 22 ms; db1 replies missing at 3 s | PASS: db16 21 ms; db1 21 ms | PASS: db16 20 ms; db1 20 ms |
| watchdog-2s-uring | FAIL: SIGABRT | FAIL: SIGABRT | PASS: SWAPDB at 4.452 s | PASS: SWAPDB at 4.476 s |
| watchdog-2s-epoll | FAIL: SIGABRT | FAIL: SIGABRT | PASS: SWAPDB at 4.305 s | PASS: SWAPDB at 4.413 s |
| watchdog-1s-uring | FAIL: SIGABRT | FAIL: SIGABRT | PASS: SWAPDB at 4.355 s | PASS: SWAPDB at 4.454 s |
| watchdog-1s-epoll | FAIL: SIGABRT | FAIL: SIGABRT | PASS: SWAPDB at 4.386 s | PASS: SWAPDB at 4.453 s |
| script-2s-uring | FAIL: db16 livelock; db1 livelock | FAIL: db16 livelock; db1 livelock | PASS: db16 305 replies; db1 305 replies | PASS: db16 305 replies; db1 305 replies |
| script-2s-epoll | FAIL: db16 livelock; db1 livelock | FAIL: db16 livelock; db1 livelock | PASS: db16 305 replies; db1 305 replies | PASS: db16 305 replies; db1 305 replies |
| swapdb-2s-epoll | not run | PASS: p50 250 ms max 251 ms | PASS: p50 150 ms max 231 ms | not run |

**Negative controls.**
- **F1 lane-wake half.** A throwaway diag twin of POST with only the park predicate removed
  (`b33a194b`, deleted after use) was run with the same 200-call forms as POST-diag (server
  56-63, load 48-55, 1 s miss threshold):

  | Arm | EXEC+PUBLISH | EXEC+PUBLISH with a hot owner | EXEC+SUBSCRIBE | contended EXEC | escalation |
  |---|---|---|---|---|---|
  | no predicate | 8 stalls of 2.0 s in 1,351 calls | 5 in 1,583 | 8 in 1,548 | 0 in 3,200 | 0 in 800 |
  | POST-diag | 0 in 1,600 (max 3.9 ms) | 0 in 1,600 (max 4.9 ms) | 0 in 1,600 (max 3.9 ms) | 0 in 3,200 | 0 in 800 |

- **F3.** `tests/parkwake_unit.cc` built with `-DPARKWAKE_UNIT_PRE` against the PRE objects:
  `FAIL parkwake unit: executor owing the DatabaseExDrain ack reported no work (would park)`. On
  POST, all five schedules print PASS.

**The same rows through the gate's own job interface on PRE.** `GATE_ONLY_JOBS=` the 22 parkwake
rows plus `parkwake_unit`, `--candidate-binary` PRE, single slot (server 48-55, load 56-63, ports
23350-23399):

- 21 rows FAIL.
- `parkwake_unit` is ok: it is built from the worktree, and the PRE witness is the control above.
- `parkwake-watchdog-1s-epoll` was ok. It passed vacuously: the SWAPDB connection landed on the
  fused thread running the SORT, so the boundary opened only after the command. Fixed in
  `8805877673`: SWAPDB and a probe now sit on two IO threads other than the key's owner, and the
  probe's PING must be held until the command ends. The revised row: PRE SIGABRT on all four legs;
  POST passes them all, with SWAPDB and the probe answering together at the SORT's end
  (4.34-4.54 s).

### FIFO fairness (F1 question)

**Question.** Does F1 explain the `txnorder_fifo_live` failures seen in the atomfix6 runs? Those
were 4 of 32 legs with plain p100 30.6 / 50.0 / 53.1 ms (PRE, 1s, atomic 0) and 41.3 ms (POST,
2s-epoll, atomic 1); see `docs/atomfix6/fifo-comparison.json`.

**Answer: no, not on this code base.**

1. **The row hardly uses the retry lane any more.** The audit's mechanism was that doomed EXECs
   retry through the lane and a writer queued behind one waits for that IO's timeout. On the
   current scheduler a contended EXEC waits in FIFO order instead (`atomic_txn_fifo_waits` about
   57 M per leg). Per 60 s leg, `atomic_txn_retries` is 0-16 and `atomic_txn_dooms` is 0, against
   about 9.5 M executed EXECs.
2. **No lost wake of any kind reaches a FIFO writer.** The row was run through the gate
   (`GATE_ONLY_JOBS=txnorder_fifo_live`, single slot, 8 server + 8 load CPUs, the wide-slot
   geometry) on both diagnostic arms. Any missed wake would show as a ≥ 2 s p100 there:

   | Arm | Legs | Failed | Max plain p100 | Legs with retries (retries) |
   |---|---|---|---|---|
   | PRE-diag | 16 | 0 | 1.61 ms | 10 (46) |
   | POST-diag | 16 | 0 | 2.97 ms | 13 (80) |

3. **The 30-53 ms failures do not recur on PRE or POST.**
   - **Setup.** The production loops ran PRE and POST at the same time on separate CCX pairs
     (8 server + 8 load CPUs each), alternating which arm got which pair. Each run is one gate run
     with `GATE_ONLY_JOBS=txnorder_fifo_live` (16 legs of 60 s). The POST count also includes the
     row's own run in the main gate's wide slot, which ran alongside the core TSAN build.
   - **Results.**

     | Arm | Runs | Legs | Failed | Max plain p100 | Median p100 | Legs > 20 ms | Legs with retries (retries) |
     |---|---|---|---|---|---|---|---|
     | PRE | 3 | 48 | 0 | 9.87 ms | 0.68 ms | 0 | 34 (2,955) |
     | POST | 4 | 64 | 0 | 4.01 ms | 0.73 ms | 0 | 50 (894) |

   - **Retry storms do not move the tail.** The first concurrent pair ran into wound-retry storms:
     PRE-A1 had 2,817 retries, up to 1,238 in one leg, and POST-B1 had 699. Plain p100 still
     stayed at or below 9.87 ms.
   - **Power.** At atomfix6's per-leg failure rate (about 12%), 48 clean PRE legs would happen by
     chance with probability about 0.2%.
   - **Conclusion.** On the wave-15 code the row has neither a lost-wake tail nor a 20 ms tail
     left for F1 to explain. F1 is still fixed on its own witness rows. The integration lane's 10×
     loops on the merged tree will extend these counts.
   - **Receipt.** `docs/parkwake/proof/fifo-legs.json`: all 144 legs (diag and production), each
     with p100, p99, retries and FIFO waits.

### Touched gate jobs through `tests/gate.sh`

**Main run.** `GATE_ONLY_JOBS=` 229 touched jobs (prerequisites added by the gate),
`tests/gate.sh quick --server-cores 32-47 --load-cores 48-63 --ports 23300-23399 --candidate-binary`
POST (`4023172c`), `REDIS74_ROOT=/home/user/Projects/redis`. This is the two-slot plan, with
`txnorder_fifo_live` in wide slot 1 running alongside the core TSAN build. Result: **679 ok, 20
FAIL** in 1 h 56 min. The jobs cover every declared mode and engine of:

- txnorder: txnorder_fifo, fifo_live, chain, index, wound, wake, txnorder2, txnorder-split/fused,
  txn_group_*, exec1s, execfair, txnfix4-*;
- atomics: atomfix5/6, atomwake, atomic_units;
- scripts: scriptfix*, script_bounds, at412-T1..T16 + owner, snapfix_bgsave_script;
- multidb/SWAPDB: multidb-* (including the mdbqsbr live twins), flushfix2/3;
- FLIP: flip, fliplisten, flip_saturated, flipctl, flipfix5/6/7*, the flipfix units;
- client-lb/key-lb: lb-stationary-1s/2s, lbplanner_units, racefix_climon;
- CONFIG: cfgfix, cfgfix2-*, config_unit, netfix_config, serverfix_config;
- pause: clientcompat-*, climonfix, climonfix4-*;
- pubsub and tracking: notify*, notifycompat, trackorder, trackfix_*, pubtrackfix, multifix-*,
  rootcore-notify, rootcompat-xsnotify/tracking;
- IO loop: iofix-*, netio-*, wb_policy, wb_mixed, respresume-*, reorder_*, core_units, debug-0/1,
  fused-0/1, aof/snapshot-*, persistfix*, rootcore-waitaof, serverfix_waitaof, wave15_*,
  wave15-block-*;
- blocking: slotless, blockfix*;
- three feature cells;
- the 23 parkwake rows.

The 20 FAIL rows:

- **18 are path artifacts of `--candidate-binary` outside `build/`.** blockfix2
  BLOCK-SERVE-REFUSED-DROP, the blockfix AT4.8 registry cost binding, and 16 txnorder2/txnorder_wake
  rows. These jobs resolve their units or the cost binding as `dirname($CANDIDATE_BINARY)/...`.
  Re-run with `--candidate-binary build/tomokv` (identical bytes, SHA-256 `4023172c`): **34 ok,
  0 FAIL** (blockfix2 7, blockfix_registry 1, moverfix 8, txnorder2 16, txnorder_wake 1, release 1).
- **`eoffix_aof` is a private lane proof.** It needs `EOFFIX_AOF_DIRECTORY`, a native AOF arm
  directory from that lane, and is never counted in EXPECT. NOT RUN.
- **`wave15-block-2s-uring-0-16` (deleted-stream repeated 200 times) is a real wrong reply, once.**
  Details below.

So, net of artifacts: 697 ok, 1 intermittent FAIL, 1 not runnable.

**Deleted-stream intermittent wrong reply (S1 candidate; not attributed to this lane).**
- **What failed.** At iteration 26 of 200 the waiter returned
  `[[b'boundary', [[b'1-0', [b'f', b'v']]]]]` instead of NOGROUP: "deleted group's waiter must not
  consume recreated stream". The RENAME arm ran with `DEL boundary other-owner` (cross-owner,
  `--atomic 1`). `notify_drop=0` in that run, so item 7 was not involved.
- **Repetitions in the same geometry.**

  | Repetition | PRE iterations | POST iterations | Failures |
  |---|---|---|---|
  | `tests/wave15_block_repeat.py`, interleaved, part of it under the differential's load | 12,800 | 12,600 | 0 |
  | focused RENAME-arm stress | 40,000 | 40,000 | 0 |

- **Likely mechanism, in code this lane did not change.**
  - A cross-owner atomic DEL may be published by the peer owner through
    `blocking_atomic_published`, which only sets the waiter shard's dirty flag (and wakes the
    owner if it is parked).
  - The owner sweeps dirty waiters in `blocking_owner_cycle`. In the split pass that runs on the
    10 ms blocking beat and after `drain_tasks()`.
  - The pipelined RENAME+XADD can therefore execute on that shard before the waiter is failed.
    The waiter is then re-probed against the recreated group.
  - The wave 15 integration record (`docs/wave15/jobs/block-repeat-integration.log`) shows this
    same row failing in 3 of 12 legs before its fix; this flake is what remains of it.
- **Smallest change I would propose (owner decision, blocking subsystem).** Before an executor
  runs a task on a shard whose `blocking_dirty_` is set, run that shard's sweep first, i.e.
  service dirty registries ahead of `drain_tasks()`, not only on the beat. The integration
  lane's 10× loops should include `wave15-block-*`.

**PRE through the same interface.**
- First run, the 22 parkwake rows: 21 FAIL as designed, plus the vacuous watchdog-1s-epoll pass that
  `8805877673` closed. See the proof section above.
- After the fix, the four watchdog rows on PRE all FAIL with SIGABRT, elapsed_ms 2701-2743.

### Differential vs Redis 7.4.10 (`tests/differ_gate.sh`, standard seeds, split 6:2)

| Engine | Target / load CPUs, ports | Seeds | Atomic | Result |
|---|---|---|---|---|
| uring | 32-39 / 40-47, 23360-23361 | 7 19 20 23 21 | 0 and 1 | **pass=475 fail=0**, 17m41s; 232 of 245 commands diffed; mode equivalence ok |
| epoll | 48-55 / 56-63, 23380-23381 | 7 19 20 23 22 | 0 and 1 | **pass=475 fail=0**, 17m38s; 232 of 245 commands diffed; mode equivalence ok |

Both runs used the oracle `/home/user/Projects/redis/src/redis-server` (7.4.10) and the candidate POST
`4023172c`. The rotating fifth seed is allocated per run by `tests/_differ_history.py`.

### Build and tooling checks

- `make all` builds every `job_production_units` target, the mdbqsbr live arms, `blockfix-cost`
  and the blockfix2 units: all exit 0 on the final tree.
- `make -q` then reports nothing stale for `all`, each of the 62 unit targets, `blockfix-cost`
  with its sha file, or the two blockfix2 units.
- The first `make -k` pass found the lbosc3 PAD proof failure; it is fixed in `d1513fe2ed`.
- `python3 tests/gates_test.py`: 14 + 79 tests OK.
- **Disk trim afterwards.** To keep `build/` near 15 GB, regenerable unit outputs were deleted after
  the runs: wb-rule/lbplanner controls, the gate-cache, the mdbqsbr arms and similar. A later
  `make` or gate run rebuilds them; `make -q all` stays clean. The PRE/diag source trees used by
  `tools/parkwake_pad.py` were removed too. All arms are kept, in `build/parkwake/arms` and
  `/home/user/Projects/bins`.



### Zero cost

**Command-scope instruction counts, PRE against POST.** `tools/parkwake_counts.py` runs the
serverless census with the tracer, per function, on PRE `8be4f68323` and on the budget-selected POST
objects:

| Scope set | Rows | Identical | Delta |
|---|---|---|---|
| ordinary | 80 (72 required + 8 MSET atomic-1) | 80 | 0 in every row |
| atomfix6 | 80 | 80 | 0 in every row |
| parser (PARSE-GET/SET/INCR) | 36 | 36 | 0 in every row |

The ordinary rows cover GET, SET, INCR, MGET and MSET; batch 1 and 32; 1s and 2s; atomic 0 and 1;
both namespaces. Example rows, PRE = POST:

- GET: db0 2s/b1 1,015; normal 2s/b32 18,295.
- SET: normal 2s/b1 1,642.
- INCR: normal 1s/b32 36,291.
- MGET: normal 2s/b32 322,950.
- MSET: normal atomic 1 2s/b32 940,134.

Receipts: `docs/parkwake/counts/` (comparison and counts JSON).

The census ran on server `480de2e6`. The final POST `4023172c` differs from it in three ways only,
and `docs/parkwake/identity/clamp-delta-summary.json` shows no hot body changed:

- the item-4 clamp: `DatabaseMap::drain_deadline_start` and `DatabaseMap::monitor`, main thread,
  cold;
- the INFO git id;
- a 32-byte shift of the code linked after `multidb.o`.

So the counts carry over.

**Park boundary.** The changes add no work per command:

- the retry-lane load and the epoch park/resume stores run only when a thread is about to block;
- the notice-retry check is one predictable branch per pass (`notify_retries_pending()`, a vector
  emptiness test);
- the F2 arm is cold (Retry only).

**Changed hot bodies.** `tools/parkwake_identity.py` uses the gate's strict normalizer and the hot
selection of `docs/wave9/identity.py`. 117 hot groups changed. Each line gives variants in the
tomo / tomo_db0 namespaces.

- **Intended (100):**
  - `IoLoop::run_loop<..>` 24/24 (park predicate, epoch park/resume);
  - `ExLoopT<..>::run` 2/2 (epoch park/resume, `kParkNetMs`);
  - `sweep<..>` 3/3, `r7_sweep<..>` 2/2, `fused_pass_impl<..>` 2/2 and `r7_fused_pass_impl<..>`
    2/2 (notice-retry service);
  - `execute<..>`, `execute_latency<..>` and `execute_timed<..>` 5/5 each (the F2 Retry arm).
- **Displacement only (4):** `cmd_xshard_only_impl<..>` 2/2.
- **Unintended (13):**
  - `IoLoop::parse_and_dispatch<..>` 4/6: `now_ns()` is no longer inlined at two cold sites;
  - `IoLoop::flush_ready<false,true,true,{false,true},true>` 2/0;
  - `FlatStore::scan<xshard_execute lambda>` 1/0.

None of the 13 is on a census path whose count moved: all 196 census rows are identical. Full
list: `docs/parkwake/identity/changed-bodies.md`.

**Inline budgets.** Eighteen size-compensated `--param large-unit-insns` values in the Makefile, so
each grown unit keeps PRE's inlining decisions. Per unit (db0 / tomo):

| Unit | db0 | tomo |
|---|---|---|
| climon | 29,459 | 28,900 |
| latency_tracking | 10,160 | 10,153 |
| multidb | 10,125 | 10,131 |
| xshard | 171,823 | 168,328 |
| fliplisten | 48,789 | 49,003 |
| genthread | 135,778 | 135,198 |
| reorder | 153,850 | 152,982 |
| rl2s | 169,904 (PRE value) | 168,503 |
| main | 150,916 | 152,824 |

Receipts: `docs/parkwake/budgets/`.

### Row delta

DQ=+23 and DF=+23. The new rows are 22 `parkwake-*` live rows and `parkwake_unit`, all collected
before the quick-tier exit:

- retry, control, epoch, slotless and watchdog, each × {2s,1s} × {uring,epoll};
- script × 2s × {uring,epoll}.

EXPECT_QUICK and EXPECT_FULL were not edited; for the maintainer they become 1177 → 1200 and
1194 → 1217. `tests/fixtures/nullrefresh-ledger-labels.json` (maintainer-owned) also needs the 23
labels; `parkwake_label()` in gate.sh prints each one.

### Arms

| Arm | Path | SHA-256 |
|---|---|---|
| PRE (`8be4f68323`) | `/home/user/Projects/bins/parkwake-pre-13dbf1e2` | `13dbf1e200102ea347d623e38ace196109ef3790835785002a14925fafac533d` |
| POST (src at `2646077e16`) | `/home/user/Projects/bins/parkwake-post-4023172c` | `4023172c9e668c8592f213f65817e77a2ab5319deb1643ea4f16a5183c5a090f` |
| PAD-A (PRE behaviour, POST `.text` start and size) | `/home/user/Projects/bins/parkwake-pad-41b68ed0` | `41b68ed0dc83881a7af5696fc1c5339c838fbdaf6eb70599cf8665d81c3addab` |

PAD-A is made by `tools/parkwake_pad.py` from the PRE objects plus one padding object. Its `.text`
is `0x2dcd0` + `0x8d12f7`, matching POST. It is a size control only. Diagnostic arms (test-only,
not in bins):

- PRE-diag `6b7a1a9f...`;
- POST-diag `ee3bc054...` (rebuilt after the clamp; the first POST-diag build was `ee824ef4...`).

### Residuals and proposals (no architecture or algorithm change was needed for any item)

- **16-database client-LB refusal (F11 follow-on).**
  - DEBUG CLIENT-LB and the automatic client balancer refuse a move with
    `LbStallReason::Executor` while any peer is mid-pass. This happens on PRE and POST alike, so it
    is a readiness-fence policy, not a lost wake, and the client-LB witness runs with one database.
  - Smallest change I would propose: treat `Executor` as retryable within the existing `kPassLimit`
    tail instead of refusing. That is a policy change; the owner decides.
- **Spurious "cross-shard second hop queue is full" error replies** (audit T6). In the F2 script
  workload, 172 of 305 replies are this error on POST and POST-diag; on PRE no reply arrives at all.
  Redis never returns it. This lane removes only the livelock.
- **F3 live window.** The DatabaseExDrain owe-and-park window is not reachable on this box: fast
  NVMe; `appendfsync always` defers Done; an LD_PRELOAD write-delay shim makes the AOF writer
  dominate. The deterministic unit schedule is the gate proof (PRE FAIL, POST PASS). The diag
  swapdb attempt shows no 2 s stall on either arm.
- **F10 automatic FLIP and LB PlanReady.** The wakes are in place: `monitor_controllers` rings the
  coordinator after `flipctl_tick` starts a FLIP or `lb_controller_tick` publishes PlanReady.
  - Live witness NOT RUN: `DEBUG FLIPCTL SEEK FORCE` did not issue an automatic FLIP within 3 s on
    this geometry, so the sub-form was dropped.
  - The existing flipctl/flip gate jobs exercise that path; see the gate run below.
- **Contended-EXEC form of the retry row.** It rarely arms (0-4 retries per leg on POST), so the
  lane-wake half is witnessed by the negative control (no-predicate twin), not by that form.

### Harness changes (reported, no gate verdict changed)

- `tools/lbosc3_pad.py`: the PAD source proof removes exactly the four parkwake wake lines of
  `monitor_controllers` before its complete-body comparison, as it already did for cfgfix.
  Found by `make -k` over `job_production_units`.
- `Makefile`: `park-net-arm`, `build/parkwake-unit` and `build/parkwake-slowsync.so`. The 18 inline
  budgets are production build flags, listed above.
- New: `tests/parkwake.py`, `tests/parkwake_unit.cc`, `tests/parkwake_slowsync.c`,
  `tests/parkwake_parser_scope.cc`, `tools/parkwake_{counts,budgets,identity,pad,matrix,summary}.py`
  and `tools/parkwake_loop.sh`.

### NOT RUN (with reason)

- **Throughput, merit, ABBA, NIC and the full iteration tier.** These stay with the maintainer per
  the brief. PRE, POST and PAD-A are ready in `/home/user/Projects/bins`.
- **A complete quick or full gate.** Only the 229 touched jobs plus their prerequisites ran: a
  partial ledger, no EXPECT tally, and no receipt, since `--candidate-binary` withholds one.
- **`eoffix_aof`.** It needs `EOFFIX_AOF_DIRECTORY`, the eoffix lane's native AOF arms.
- **Live witnesses for the automatic FLIP and LB PlanReady wakes (F10).** `DEBUG FLIPCTL SEEK FORCE`
  started no automatic FLIP within 3 s on this geometry. flipctl and flip/flipfix* passed in the
  gate run.
- **F3 live window.** It was not reachable on this box; the unit schedule is the proof.
- **A census re-run on `4023172c` itself.** The census ran on `480de2e6`. The identity inventory
  shows no hot body differs between the two.
- **`asan_batteries` and the armed-fused differential geometry.** Both are full-tier only. The
  core TSAN build ran as a gate prerequisite; the differential ran split on both engines.
- **AGENTS.md.** Absent; nothing to read.

