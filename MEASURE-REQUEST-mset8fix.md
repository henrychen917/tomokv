# Lane correctness record

## mset8fix

PRE: `84642b620c30fa724f0a6f3adb670f767bf16440` (wave-15 release candidate). Worktree
`/home/user/Projects/cx-mset8fix`, branch `cx-mset8fix`, not pushed. Commits: `25b24430e8` (item 1
rows), `e8c85da27a` (item 2 fix and unit), `9c1f4cf03e` (item 4 inline budgets and count receipts),
`9f87b7886c` (row definition: four hogs per IO thread, slow-batch evidence), `a2778b88d8` (gate
one-slot fix), `d726d5b468` (item 3 proof), then item 5 (arms and this record). POST is the source at
`9c1f4cf03e`: no later commit touches `src/` or the Makefile. CPUs: 112-127 until the maintainer's
"box free" (04:39), then 0-127 with each timing-sensitive series on a CCD of its own; ports
23000-23099; `LC_ALL=C` on every boot. This is a correctness record: it makes no throughput claim.

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| Lone IO refused by the global atomic window, 2s (new rows `atomwake-live-2s-{uring,epoll}`) | 10 of 10 gate runs FAIL both rows; 240 of 240 legs fail. The probe completes 2-38 batches while the median hog completes 2072-3827; the probe's slowest batch takes 0.54-5.0 s | Clean CCD 4: 10 of 10 runs pass all five rows; 240 of 240 2s legs pass; probe slowest batch 1.8-5.1 ms; no probe batch of 10 ms or more in any leg | Credit doorbell: a parking IO that holds a window-refused frame publishes a waiter bit, then re-checks the window; each retirement of an admitted group rings one published waiter with the existing `wake_if_parked` | Shared CCD 7: 7 of 10 runs pass; 3 of 240 2s legs had one probe batch of 21.1-23.5 ms (slow progress, no timer gap; see Proof) |
| Same park in 1s (rows `atomwake-live-1s-{uring,epoll}`) | Not a witness: 3 of 3 runs pass. The fused thread that owns the probe also owns shards, so other threads' groups keep waking it | 20 of 20 runs pass (CCD 4 and CCD 7); 480 of 480 legs pass | The same change in the fused park variants | none seen |
| Doorbell interleavings (row `atomwake_unit`, real rings, both engines) | Cannot build on PRE (no doorbell API) | 20 of 20 runs pass | Unit cases A-E below | none |
| Survey hot-key cell strings-MSET8-n100-p32 (2s, ratio 24:8, 256 shards, atomic 1, 64 connections x pipeline 32), 3 visits per arm | Request latency p999 132-150 ms, max 462-800 ms; 6.7k-10.5k requests of 20 ms or more; 19-38 connections saw one; 2-4 connections starved (under 25% of the median connection); slowest connection 2.9-3.9% of the median | p999 6.6-10.2 ms (better), max 8.0-11.8 ms (better); 0 requests of 20 ms or more; 0 stalled and 0 starved connections; slowest connection 34-58% of the median (better). p50 2.41-2.43 ms against PRE's 1.93-2.03 ms and p99 5.5-6.8 ms against 4.7-5.0 ms (worse: the starved connections are now served) | as above | The woken IO still competes through the same CAS, so per-connection shares stay uneven (34-58%) |
| BGSAVE barrier clear (cold wait named in the analysis) | Not witnessed separately | `atomwake_unit` case E: clearing the barrier rings every published waiter, both engines | `SnapshotManager::start` rings all waiters after each of its four barrier clears | The `abort_file()` clear on the failed-epoch path (after a shutdown-coordination timeout) does not ring: one wait of at most 50 ms |
| CONFIG SET atomic 1 to 0 (cold wait named in the analysis) | Not run | Not changed | none | Waiters beyond the in-flight groups wait at most 50 ms, once (no ring at that cold site; each in-flight retirement still rings one waiter) |
| txnorder FIFO live fairness, wide slot, 5 runs | 5 of 5 runs pass, 80 of 80 legs; worst plain p100 per run 2.5-4.2 ms | 5 of 5 runs pass, 80 of 80 legs; worst plain p100 per run 1.5-3.6 ms | none | The earlier 50.02/53.10 ms failures did not recur on PRE in 5 runs, so this lane cannot tie them to this mechanism (see FIFO) |
| Gate one-slot runs that select `txnorder_fifo_live` | The planner held the only slot for the FIFO job, which waited for `release` on that same slot: the run hung (found here) | Runs `release`, then the FIFO job | `start_workers` reserves the wide slot only when the run has more than one slot | none |
| Zero cost (serverless command-scope instruction counts, PRE against POST) | -- | Identical in every required row: 72 of 72 ordinary rows, 72 of 72 atomfix6 rows, 36 of 36 parser rows | 10 per-unit inline budgets size-compensated in the Makefile | atomic-1 MSET executes 5 more instructions per admitted group (in `xshard_destroy`); 4 hot bodies differ by inlining |

### Production diff

`git diff --stat 84642b620c 9c1f4cf03e -- src Makefile`: 10 files, +146/-25 (src alone 9 files,
+124/-15).

- `src/core/server.h`: `atomic_credit_waiters_` (one 64-bit word; bit `b` stands for thread ids
  `b` and `b+64`) and 8 bytes of padding replace `uint32_t atomic_credit_layout_padding_[3]` and its
  4-byte alignment hole. Server stays 141,888 bytes and every other member keeps its offset (gdb
  `ptype /o`, PRE against POST: of 854 members only this one differs). The word shares
  `atomic_credits_`'s cache line (offsets 93552 and 93560), so the retirer loads the line its RMW
  just wrote. New: `atomic_credit_doorbell()` (inline: one seq_cst load and one predicted-false
  branch), `atomic_credit_wait_arm()` (cold, out of line: `fetch_or`, then `atomic_can_admit()`),
  `atomic_ring_credit_waiters()` (cold, out of line). `atomic_can_admit()`'s barrier load and the
  barrier clear become seq_cst. `atomic_retire_group()` is unchanged.
- `src/core/atomic_admission.h`: `can_admit()`'s load and `retire()`'s RMW become seq_cst (the same
  `mov` and `lock xadd` on x86-64).
- `src/core/thread.h`: `AtomicAdmissionState` gains `credit_wait` and `credit_ring_cursor` inside
  its 64 bytes (its static_assert holds; ThreadCtx stays 1408 bytes).
- `src/cmd/script_escalation.inc`: `script_window_resume()` sets `credit_wait` at its existing
  early return where the window refuses.
- `src/core/io_loop.h` (`run_loop`: every engine, mode, TLS, Unix and split-local instantiation)
  and `src/core/reorder.cc` (`r7_run_loop`): clear `credit_wait` before the pre-park sweep (whose
  resume visits recompute it); after `arm_blocked()`, publish and re-check; room means do not wait.
- `src/cmd/scatter_engine.inc` (`xshard_destroy`) and `src/cmd/multi.inc` (`release_admission`):
  ring right after `atomic_retire_group()`. These are the two places an admitted group finishes
  (MSET/MGET groups, scripts, FLUSH and transaction groups end in `xshard_destroy`, EXEC in
  `release_admission`).
- `src/snapshot/snapshot.cc`: ring every waiter after each barrier clear in `start()`.

No admission, ticket, collapse-guard, preservation-floor, window-size or reclamation code
changes, and nothing hands credits to waiters in any order: a woken IO retries its frame through
the same strong CAS as every other IO. FIFO hand-off of credits to waiters is the algorithm change
the brief reserves; it is not implemented and is listed below as the option for the remaining
unevenness.

### Why no wake-up is lost (both orders)

W is the IO about to park with a refused frame, R any thread finishing an admitted group, C the
credit word, B the waiter word, P W's `parked_`.

| Step | W (`run_loop` / `r7_run_loop` park) | R (`atomic_retire_group` + `atomic_credit_doorbell`) |
|---|---|---|
| 1 | `P = true` (release), seq_cst fence (`arm_blocked`) | `C.fetch_sub(1)` seq_cst (`retire`) |
| 2 | `B.fetch_or(bit)` seq_cst | `B.load()` seq_cst; zero: done |
| 3 | barrier and `C` loads, seq_cst (`atomic_can_admit`): room means no wait | claim `B.fetch_and(~bit)` acq_rel; bit already gone: next bit |
| 4 | no room and no inbound work: wait (ring CQE, epoll mail, 50 ms timeout) | per holder of the bit: `P.load` acquire; parked: `wake_if_parked` (msg_ring Wake; epoll: mail + eventfd) |
| 5 | `P = false` (`clear_blocked`); the bit stays until a ringer consumes it | |

W2, W3, R1 and R2 are seq_cst, so they lie in one total order S consistent with program order.

1. **W publishes, then R looks (W2 before R2 in S).** R2 sees the bit, or a later RMW of B: only
   another ringer's claim can clear it, and that ringer then wakes W or finds it awake. The claim
   reads from W2's release RMW (all later RMWs on B continue its release sequence), so W1 happens
   before R4: R4 reads `P == true`, or `false` only from W5, after W's wait returned. With `P ==
   true` R posts the Wake. If W has not reached its wait yet, the CQE (or the mail plus eventfd
   count) is already pending and the wait returns at once. R prepares the SQE on its own ring
   (`Ring::sqe()` flushes a full SQ rather than failing), and R's next `submit_and_reap()` or park
   sends it.
2. **R looks, then W publishes (R2 before W2).** Then R1 < R2 < W2 < W3 in S, so W3 sees R1's
   decrement or a later value. With room, W does not wait and retries the frame on its next pass.
   Without room, W3 read `used == limit` (limit >= 16) admitted, unretired groups. Each of those
   finishes with an R1' later than W3's read point in C's modification order, hence later than W3
   in S (a seq_cst load cannot read a value older than an SC RMW that precedes it in S), so
   W2 < W3 < R1' < R2' and case 1 applies to R'. Every admitted group finishes in `xshard_destroy`
   or `release_admission`, both of which ring. The exceptions are OOM rollbacks of a group admitted
   and retired within the same call: a waiter that saw the window full also saw at least 15 other
   groups, which ring.
3. **Barrier.** The barrier clear is a seq_cst `fetch_and` followed by the ring's seq_cst loads of
   B; W's re-check loads the barrier seq_cst after W2. Either W sees the barrier cleared (and case
   2 applies to the credits) or the clearer sees W's bit and rings every published waiter.

A claim returns a bit to exactly one ringer. A claimed bit whose holders are all awake passes its
wake to the next published bit. One finished group rings one bit; the scan starts one past the bit
this thread rang last, so N waiters are each rung within N consecutive retirements of one retirer.
No disarm is needed: a bit left by an IO that woke on its own costs the next retirement one claim
and at most one spurious Wake. Bits are shared by thread ids `b` and `b+64`; the ringer wakes every
parked holder, so aliasing can only add a spurious wake. The 50 ms ring timeout is unchanged and is
now defence in depth, not the liveness guarantee.

`atomwake_unit` (tests/atomwake_unit.cc) executes both orders on real rings in both engines:
A, publish then retire: the retirement rings the parked waiter exactly once and consumes its bit;
B, retire then publish: the publishing re-check returns room and nothing is posted; C, two parked
waiters are rung in turn even when the first re-publishes before the next retirement; D, an awake
holder's wake passes to a parked one; E, a barrier clear rings both waiters. Built against a
retirement path that does not ring (the first POST variant, after the doorbell moved out of
`atomic_retire_group()`), case A failed in both engines, so the unit can fail.

### Proof

The rows (`tests/atomwake.py`, wired as gate jobs `atomwake-live-{2s,1s}-{uring,epoll}` and
`atomwake_unit`). Each leg boots a fresh server (`--shards 16`: a 256-credit window, `--hz 1`,
`--dynamic-hz no`, key and client LB off, FLIP off in 2s, `--atomic 1`), places through DEBUG
IO-THREAD one probe connection alone on one IO thread (not the admin thread) and four hogs on every
other IO thread, gives every connection eight private keys on eight distinct shards (DEBUG SHARDS),
and runs batch-synchronous pipelines of 32 MSET8 for 5 s. A leg passes only if INFO
atomic_window_stalls grew, the probe's slowest batch took under 20 ms, the probe completed at least
25% of the median hog's batches, every reply is +OK, the probe's keys hold its last write and no
connection changed IO thread. Legs: read-local 0 and 1, databases 1 and 16, 3 repetitions: 12 per
row. Each series below is `tools/mset8fix_loop.sh` around `tests/gate.sh quick` with
`GATE_ONLY_JOBS`, `--candidate-binary` and fixed `--server-cores/--load-cores/--ports`; per-leg
numbers are in docs/mset8fix/proof/summary.json (`tools/mset8fix_proof.py`).

| Series (server / load CPUs) | Rows | Runs passing | Legs passing | Probe batches (median hog) | Probe slowest batch | Window stalls per leg |
|---|---|---|---|---|---|---|
| PRE 2s (32-39 / 40-47) | 2s uring, 2s epoll | 0 of 10 (each row FAILs every run) | 0 of 240 | 2-38 (2072-3827) | 542-5025 ms | at least 389,681 |
| PRE 1s (48-55 / 56-63) | 1s uring, 1s epoll | 3 of 3 | 72 of 72 | 4139-7964 (3261-4231) | 1.3-2.3 ms | at least 1,312,667 |
| POST, clean CCD 4 (64-71 / 72-79) | all five | 10 of 10 | 480 of 480; unit 10 of 10 | 2s: 1846-3662 (2026-3053); 1s: 4060-7825 | 2s: 1.8-5.1 ms; 1s: 1.1-2.2 ms | 2s at least 723,119 |
| POST, shared CCD 7 (112-119 / 120-127) | all five | 7 of 10 | 477 of 480; unit 10 of 10 | 2s: 1816-3543 (1958-3058) | 2s: 1.8-23.5 ms (3 legs over 20 ms) | 2s at least 700,445 |

The PRE witness is decisive (the probe waits on the 50 ms ring timeout again and again: whole
seconds per batch) and needs no tuning. On POST the probe's slowest batch on the clean CCD is
5.1 ms over 240 2s legs, against the 20 ms threshold.

The three CCD 7 failures (21.20 ms 2s uring, 21.14 ms 2s uring, 23.50 ms 2s epoll; one batch each,
the rest of each leg normal) are not timer rescues. CCD 7 is also the CPU mask of the
coordinator's pinned lifeboat, screen, lane-monitor and pending-mover processes, which share the
server CPUs and the probe driver's CPU 120. The 23.50 ms batch carries the new evidence: the probe
client had 0 involuntary context switches, and its 32 replies arrived as 8 at 3.0 ms, single
replies at 4.0, 5.0, 11.5 and 16.0 ms, then the remaining 20 at 23.0-23.5 ms. The probe's IO kept
being woken and admitted single groups; it never sat out a 50 ms timeout. That is the remaining
unevenness of the CAS race (a woken IO can lose the freed credit to an IO that is already running)
made worse by CPU sharing; it is the case FIFO hand-off would address. No probe batch of 10 ms or
more occurred in 480 clean-CCD legs.

Earlier six-hogs definition (`25b24430e8`, replaced by `9f87b7886c`, same thresholds): PRE 2s 10 of
10 runs FAIL; PRE 1s one row FAIL in each of 3 runs (5 of 36 1s epoll legs at 22.9-56.6 ms, with hog
batches of 62-128 ms in those legs); POST on CCD 7 6 of 7 runs pass (one leg at 24.2 ms with a hog at
27.9 ms). Six hogs (960 MSETs outstanding against 256 credits) made hog-side queueing (POST hog
maxima 20-94 ms, median 33 ms) the dominant latency, which says nothing about a timer rescue; four
hogs keep the window saturated (at least 700k refusals per 2s leg) while PRE still starves the
probe completely.

#### Survey hot-key latency check (tools/mset8fix_latency.py)

The survey's strings-MSET8-n100-p32 cell (bench-merit/SURVEY-W15-CMDS-STRINGS-11032337): its
server argv (2s, `--ratio 24:8`, 256 shards, `--atomic 1`, LB and FLIP off, one database), its seed
and MSET8 scripts and calib/survey-client with 64 connections on 64 pinned workers, pipeline 32,
4 s, three visits per arm (docs/mset8fix/latency/). All latencies are per request.

| Visit | Arm | p50 ms | p99 ms | p999 ms | max ms | requests of 20 ms or more | connections with one | starved connections | slowest connection / median | window stalls |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | PRE | 1.98 | 4.97 | 145.75 | 462.4 | 9,054 | 19 | 2 | 1,344 / 34,512 (3.9%) | 876,997 |
| 2 | PRE | 2.03 | 4.97 | 150.21 | 800.1 | 6,713 | 38 | 4 | 1,056 / 36,464 (2.9%) | 1,105,032 |
| 3 | PRE | 1.93 | 4.70 | 131.73 | 600.7 | 10,469 | 37 | 3 | 1,216 / 37,072 (3.3%) | 972,493 |
| 1 | POST | 2.41 | 6.76 | 10.20 | 11.8 | 0 | 0 | 0 | 12,128 / 35,408 (34.3%) | 2,945,211 |
| 2 | POST | 2.42 | 6.17 | 7.01 | 8.6 | 0 | 0 | 0 | 18,336 / 34,432 (53.3%) | 3,385,745 |
| 3 | POST | 2.43 | 5.45 | 6.61 | 8.0 | 0 | 0 | 0 | 19,072 / 32,992 (57.8%) | 3,685,226 |

POST removes the tail (p999 and max better by an order of magnitude or more, no stalled or starved
connection). Its p50 and p99 are worse because the requests PRE starved are now served alongside
the rest; the requests completed per 4 s visit were 2.20-2.30M on PRE and 2.13-2.15M on POST. That
is a correctness instrument (3 short visits, correctness CPUs, no ABBA), not a rate measurement;
the maintainer's merit run decides the rate. POST also refuses about three times as many
admissions (window stalls) and sends a Wake per published waiter per retirement: the CPU cost of
that wake traffic is for the maintainer's measurement (classification: TRADE for the
redistribution, IMPLEMENTATION COST for the wakes).

#### txnorder FIFO live fairness, 5 runs per arm

`txnorder_fifo_live` in its validated geometry (the planner's exclusive wide slot: 8 server and 8
load CPUs; PRE on 96-103 / 104-111, POST on 0-7 / 8-15), 16 legs per run (databases 1 and 16, 1s and
2s, atomic 0 and 1, uring and epoll), thresholds untouched.

| Arm | Runs passing | Legs passing | Worst plain p100 per run (ms) |
|---|---|---|---|
| PRE | 5 of 5 | 80 of 80 | 4.20, 2.53, 2.75, 3.15, 3.82 |
| POST | 5 of 5 | 80 of 80 | 1.53, 3.32, 2.69, 3.65, 3.22 |

The intermittent 50.02 and 53.10 ms failures did not recur on PRE in 5 runs, so this lane can
neither confirm nor exclude that they were this mechanism. What is known: those values sit on the
50 ms ring timeout that this fix removes from the window wait; the gate boots this row with
`--shards 16` (a 256-credit window) and its hot shape keeps up to 64 x 4 = 256 transactions
outstanding, and EXEC groups take window credits (`release_admission` retires them). Whether the
window actually refuses there was not measured (execfair.py records no atomic_window_stalls), and
other waits end on the same 50 ms timeout.

#### Touched gate jobs, tests and builds

- One POST run of 144 touched jobs through `tests/gate.sh quick` with `GATE_ONLY_JOBS` (atomwake,
  atomic units, atomfix5/6, at412 T1-T16 and owner, script bounds and scriptfix*, txnorder*,
  multifix, execfair, exec1s, txn groups, fused, debug, clientcompat-multi, txnfix4, flip* and
  flipfix*, wave15 flip/idle/rebind, snapshot, snapfix*, persistfix2, aof*, flushfix2/3, cfgfix and
  cfgfix2, config unit, maxmemrace, iofix, netio, wb_policy, lb-stationary, reorder*, wave14,
  respresume*, multidb, release batteries): 514 ok, 17 FAIL. 16 FAILs were txnorder2/txnorder_wake
  rows: with `--candidate-binary` outside the tree they look for their units next to the binary
  (a harness artifact); rerun with the in-tree binary: 18 of 18 ok. The 17th, `correctness family
  wave14_epoll_eof`, needs the private WAVE14_EOF_DIRECTORY diagnostic: NOT RUN.
- `atomic_batteries` and `perfio_stream` (timed rows, run separately): 7 of 7 ok.
- `txnorder_fifo_live`: 5 runs per arm (above).
- `python3 tests/gates_test.py` (after the gate.sh change): 14 of 14 and 78 of 78 OK.
  `tests/gateplan.py --self-test`: 12 of 12 OK.
- `make all` and every `job_production_units` target (62), plus `build/atomwake-unit`,
  `mdbqsbr-live-arms`, `build/blockfix-cost` and `build/blockfix2-{,db0-}unit`: built; `make -q`
  reports every one fresh at the final commit.

### Zero cost

Serverless command-scope instruction counts (`tools/mset8fix_counts.py`: the repository's
single-step tracer between scope_begin and scope_end; kinds ordinary, atomfix6 and parser), PRE
against POST, batch 1 and 32, 1s and 2s, both namespaces (db0 and normal). Receipts in
docs/mset8fix/counts/.

| Census | Required rows (GET/SET/INCR/MGET/MSET at atomic 0, MGET at atomic 1) | Identical | Violations |
|---|---|---|---|
| ordinary | 72 | 72 | none |
| atomfix6 | 72 | 72 | none |
| parser | 36 | 36 | none |

Added cost on atomic-1 MSET (the only rows allowed to change): 5 instructions per admitted group
(`xshard_destroy` 81 to 86 in db0, 82 to 87 in normal: the doorbell's load and branch), so +5 at
batch 1 and +160 at batch 32, in both modes and namespaces. The ring itself runs only while an IO
is published.

Inline budgets: the doorbell grows the initial IPA unit size of the IO units by 126/129 (main,
genthread, rl2s, reorder), xshard by 27/29 and snapshot by 50. Compile-only scans over +/-40 around
each size-compensated budget (`tools/mset8fix_budgets.py`, docs/mset8fix/budgets/) chose, per unit,
the fewest changed hot bodies: genthread 134842 / 135506 (src / db0), rl2s 168119 / 169904, xshard
168287 / 171751, snapshot 16744 / 16184, db0 main 150687, db0 reorder 153552; src main keeps 152477
(the only scanned value that keeps the 2s parse_and_dispatch PRE-identical) and src reorder keeps
152568.

Linked bodies, PRE against POST, with the gate's strict normalizer (`tools/mset8fix_identity.py`,
docs/mset8fix/identity/changed-bodies.md; identity is a proxy, the counts above decide): 127
function groups differ. 84 are the intended edits (every `run_loop`/`r7_run_loop` instantiation,
the doorbell functions, `xshard_destroy`, `release_admission`, `script_window_resume`,
`SnapshotManager::start`, `set_snapshot_atomic_barrier`); 18 differ only in data displacements;
21 are cold (`main`, `Server::init`, `atomic_collapse`, `lb_control_pass`, `flip_control_pass`
and similar). Hot bodies that differ by inlining only:

| Hot body | PRE bytes | POST bytes |
|---|---|---|
| `tomo::IoLoop::flush_ready<false, true, true, false, true>` (normal, epoll, fused sweep pass) | 2385 | 2462 |
| `tomo_db0::IoLoop::flush_ready<true, false, true, false, false>` (db0, TLS, uring, fused) | 2806 | 2854 |
| `tomo_db0::IoLoop::flush_ready<true, false, true, true, false>` (db0, TLS, uring, fused, Unix) | 2806 | 2854 |
| `tomo::FlatStore::scan<xshard_execute lambda>` (normal) | 3774 | 3807 |

The three `flush_ready` variants inline `script_window_resume`, whose refused branch now stores
`credit_wait`; none of them is on a census path above, and the census rows they would serve are
identical. The scan lambda belongs to xshard key-scan commands, not to the counted commands.

### Arms

| Arm | Path | SHA-256 | .text start / size |
|---|---|---|---|
| PRE | /home/user/Projects/bins/mset8fix-pre-0f01a91e | 0f01a91e52e2d8afe18e58df933fd0107d06b40a6f2923df451fcb090434956e | 0x2dcd0 / 9,225,959 |
| POST | /home/user/Projects/bins/mset8fix-post-5393948f | 5393948f5e4b5a6b80e831ad07d90be718184fda421daf96d818f82c4bdb2f28 | 0x2dcd0 / 9,230,039 |
| PAD-A | /home/user/Projects/bins/mset8fix-pad-a7e6d39c | a7e6d39c230112fb24362d3bfbdbe53a03235cb69f8963d4d201366dabf188ed | 0x2dcd0 / 9,230,039 |

PRE is built from an export of `84642b620c`; POST is `build/tomokv` at `9c1f4cf03e` (the same
SHA-256 as the binary every POST series above ran). PAD-A (`tools/mset8fix_pad.py`, as cfgfix2's)
links PRE's objects with one 4,080-byte padding object, `.text` placed at POST's start, so PRE
behaviour runs with POST's text extent: a POST effect that is real moves POST and leaves PAD-A with
PRE. It is a size control only; function placement and data keep PRE's layout. Its PRE behaviour
was checked live: one 2s uring witness leg on PAD-A fails as on PRE (probe 30 batches against the
median hog's 2762, slowest probe batch 2.1 s). The row-definition commit after the
arms changed only tests/atomwake.py: the arms are unchanged binaries of unchanged sources.

### Row delta and harness changes

- Rows: +5 before the quick-tier exit (`atomwake-live-2s-uring`, `atomwake-live-2s-epoll`,
  `atomwake-live-1s-uring`, `atomwake-live-1s-epoll`, `atomwake_unit`): DQ=+5, DF=+5, so the
  maintainer would set EXPECT_QUICK=1172+5=1177 and EXPECT_FULL=1189+5=1194. EXPECT is untouched.
- tests/gate.sh `start_workers`: the FIFO wide slot is reserved only with more than one slot
  (`a2778b88d8`); multi-slot plans are unchanged.
- Makefile: `build/atomwake-unit` rule and the 10 budget values above.

### Residuals and options

- Unevenness under saturation: a woken IO retries through the same CAS and can lose the freed
  credit to an IO that is already running (survey: slowest connection 34-58% of the median; shared
  CCD 7: three single batches of 21-23.5 ms that trickled rather than stalled). Option, not
  implemented (an algorithm change): hand freed credits to published waiters in FIFO order.
- CONFIG SET atomic 1 to 0 and the `abort_file()` barrier clear do not ring: at most one 50 ms wait.
- OOM rollbacks of a just-admitted group do not ring; the window is at least 16, so 15 or more other
  groups do.
- EXEC at atomic 0 that the window refuses busy-polls as before (a pre-existing spin, not a park);
  unchanged.
- Wake traffic: more window refusals and one Wake per published waiter per retirement; CPU cost for
  the maintainer to measure.

### NOT RUN

- Throughput benchmarks, ABBA, full iteration, atomic_floor and efficiency runs: the maintainer's.
- `correctness family wave14_epoll_eof`: needs the private WAVE14_EOF_DIRECTORY diagnostic.
- A window-stall measurement in the txnorder FIFO geometry (not part of the brief; see FIFO).
- A live witness of the BGSAVE-barrier and CONFIG SET atomic cold waits (covered by unit case E and
  listed as residuals respectively).
