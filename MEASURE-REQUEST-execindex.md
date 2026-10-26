# execindex measurement and proof record

## execindex

Worktree `/home/user/Projects/cx-execindex`, branch `cx-execindex`, PRE
`3700b51d7fb3074f32330dd81f138efbf1ddd980`. No push. All lane execution is
restricted to CPUs 96–111 and ports 46800–46899. Throughput measurements are
maintainer-owned; this report makes no throughput claim.

A1–A5 are implemented and committed. Production code is frozen at `30f8cfa44`;
subsequent commits contain proof tooling, evidence, and the partial-job interface.
The extended runtime suite matrix is complete. Every outcome, including failed
attempts, is listed in "Completion after the content-filter stop" at the end of
this record. No merge/push was done.

### Design corrections and boundaries

- Writer marks cannot assume append order equals stamp order: a multi-key episode
  reuses an earlier stamp when it acquires another key. The index orders marks
  by stamp and tests out-of-order stamp insertion against the frozen predicate.
- Existing tests additionally lock `WatchReservation` at 88 bytes. The held-entry
  handle lives in a wrapper, preserving that lock and all Shard offsets/stride.
- A shard can move before an old owner forwards its queued fragment. Intrusive
  promotion must check the node's atomic lane identity before touching links;
  a foreign lane does nothing, matching PRE's unsuccessful local deque search.
- Duplicate finalize probes can be removed only for exact claim keys. Capped
  whole-shard claims and inactive WATCH aliases retain their cold cleanup probes.
- Random events obey production phase transitions: a unit cannot re-enter PLACE
  after it starts execution. An initial unrestricted generator violated this
  precondition and manufactured a dirty waiter. The corrected generator covers
  arrival, placement, wounds, abort, decision/finish, validation, dirty deferral,
  writer mark/unmark/forget, readiness/all-units, and promotion.

### Implementation and current evidence

- PRE release build SHA-256:
  `957d19eafa7beb151bfae017ea6675fca1da40b334a100602fa3fd38764029f4`.
- A1: debug-only `registry_visits`; release INFO `atomic_txn_*` unchanged.
- A2: frozen linear registry and 10,000,000-operation controls, both namespaces,
  zero mismatches. See `docs/execindex/a2-oracle-{multi,db0}.log`.
- A3: 10,000,000 operations in each namespace, zero mismatches. See
  `docs/execindex/a3-oracle-{multi,db0}.log`.
- Final oracle: 10,000,000 operations per namespace, zero mismatches; the gate
  runs this in every 1s/2s × atomic 0/1 × uring/epoll cell. The frozen PRE
  implementation is selected only with `TOMO_TXN_ORACLE`. INFO is unchanged.
- Final entry visits at N=16/256/4096: place=3, finish=5, promote=1,
  key_ready=2 in every size. All N4096/N16 ratios are **1.00**. PRE controls:
  place=241.00, finish=248.273, promote=241.00, key_ready=227.667.
- PRE fails the new complexity bound. A throwaway copy with the older-waiter
  refusal removed fails the oracle at step 512. Both negative controls are
  recorded in `docs/execindex/negative-controls.json`; neither mutation is in
  production.
- Retry scheduling: 1,000,000 events, 651,458 polls, 333,333 explicit promotions,
  zero PRE-deque ordering mismatches. Foreign-lane promotion and handoff checks
  pass.
- Directed checks cover nonmonotone arrivals, an aborted node in the middle,
  exact lifetime-pin release, connection close retaining a published waiting
  EXEC, and shutdown unlinking before destruction. Both unit kinds are covered.
  Shard/other footprint locks and the additional 88-byte reservation lock pass.
- These are bounded-work claims for the tested contended queue, not universal
  worst-case O(1): out-of-order insertion can search backward, lazy dead-node
  pruning is amortized, and held/mark sets are still scanned. Whole-registry
  FLUSH/SWAPDB/wildcard paths deliberately retain their cold walks.

### Instruction checks and identity

All **48** final command-scope pairs are exactly PRE-equal: GET, SET, INCR,
MGET, MSET; batch 1/32; 1s/2s; both namespaces. MSET includes atomic 0 and 1.
`docs/execindex/instructions/comparison.json` contains the complete table.
Scopes execute linked production objects, validate exact replies/data, count
named Tomo routines, and exclude fixture/library callees. A deterministic clock
stub avoids timing-dependent control flow. These are instruction counts, not
throughput or an IPC verdict. Full trace logs stay under `build/execindex/`,
with SHA-256 and final log excerpts in the committed evidence.

The first build had MGET/MSET instruction increases from compiler spillover.
Per-unit IPA headroom was re-derived using compile-only PRE/POST controls,
then the full final matrix was repeated. Initial results and trial receipts
are retained, rather than mixed into the final table. The larger batch-32
fixture needed a 2-million-step trace ceiling instead of the inherited
1-million-step ceiling; exact reply assertions and scope boundaries are unchanged.

The requested 10-million-call `perf stat -e instructions:u` plain-writer
fixture also uses an inner hardware counter around only the call loop, so
serverless initialization/destruction does not decide the null. Both whole
process perf output and inner counts are in `docs/execindex/plain-cost/`.

| Case | PRE instructions/call | POST instructions/call | Verdict |
| --- | ---: | ---: | --- |
| a: has_watches false | 38 | 38 | equal |
| b: key absent from registry | 621 | 497 | lower |
| c: group-write reservation + foreign mark | 801 | 665 | lower |
| d: hot list, N=64 | 4466 | 1195 | lower |

The loop uses the real source implementation with the namespace's compiler
budget and no debug visit instrumentation. Counts include loop/call overhead;
the fixed counter-bracketing tail contributes approximately 90 instructions.

Identity audit: 1,414 selected bodies, 127 changed shared/enclosing bodies;
**zero direct command-handler differences**, including INCR and MGET/MSET's
`cmd_xshard_only` implementations. Shared `xshard_execute` bodies do change,
so this is not a claim that the entire executed graph is byte-identical. Every
changed body and its reason is listed in `docs/execindex/changed-bodies.json`;
resolved relocation targets are checked, not merely instruction mnemonics.
The maintainer's generic/main-command null remains required.

### Artifacts and PAD semantics

All paths below are under `build/execindex/`. Exact digests and sizes are in
`docs/execindex/artifacts.json`.

- `PRE`: `957d19eafa7beb151bfae017ea6675fca1da40b334a100602fa3fd38764029f4`.
- `POST`: `aee048859f6f8d84d5aa4e0b30767ad1e8dac4595d383ff634a8226027d1566a`.
- `POST-layout`: `f697182c2ae572f27dca7db51bc0d9babf7f0388c682a6294e6f36be051a63b1`.
- `PAD-A`: `660409393444a5b6c1f6442a6bb281fcc4cb9437f8fd8141c9177eb4c7468e52`.

PAD-A is explicitly **type A (behaviour twin)**. The exact-layout pair is
**POST-layout vs PAD-A**: both link POST plus a symbol-isolated PRE image,
with identical sections, function addresses and data. PAD-A changes only
five bytes at the program entry to execute PRE. POST-layout executes POST.
The production release `POST` is smaller and is a separate merit arm; do not
call PAD-A its exact-layout twin. Use release PRE vs POST for merit, and the
matched common-image pair as the layout control. The link/object/patch proof
is `docs/execindex/pad-a.json`. Both images pass 16 bounded correctness boots
(1s/2s × both engines × db1/db16), including EXEC, WATCH abort and zero order
violations. No rates were measured.

`PRE-visits` and `POST-visits` are separate debug counter images, built from
the A1-only PRE and final source respectively. `debug-artifacts.json` records
objects, commands and digests; `debug-smoke.json` proves counters fire in all
16 mode/engine/namespace boots. Use `DEBUG TXN-REGISTRY-VISITS` deltas divided
by completed EXECs for the requested depth test. Do not compare debug timing
with release throughput.

### Gate bookkeeping and runtime proof

The new oracle and complexity aggregate rows are collected at
`tests/gate.sh:5550`, before the quick-tier exit at line 5653. DQ=+2, DF=+2. **Maintainer must change 798/815 to 800/817.**
Neither EXPECT constant was edited. The independent label inventory agrees
with all 817 declarations and has no missing/extra label; its count check
intentionally refuses the unchanged EXPECT_FULL=815.

`python3 tests/gates_test.py` passed all 72 tests after the final gate edits.
`make all` passed; every production-unit target and both live-control builds
passed `make -q`, including the blockfix release digest binding: 49 freshness
checks, zero failures (`docs/execindex/freshness.json`).

Initial gate evidence: 25 passing rows, no failures in `build/gate-run.BWdImp`.
The index rerun passed 3/3 rows in `build/gate-run.NzvzPo`. Both ran a binary
linked before the `30f8cfa44` freeze, so they are earlier evidence only. The
final-code matrix is in the completion section.
One subsequent fused/atomic-0 txnorder run failed the unchanged 40 ms writer
bound at 49.894 ms while this lane also ran compilers/GDB traces; values
were correct and order violations stayed zero. The failed ledger is retained
(`build/gate-run.aiaiHU`). Six idle-CPU repetitions through the job interface,
with the bound unchanged, all passed at 6.370-6.399 ms (completion section).

The fused/uring `debug-0` job subsequently recorded one bare RENAMENX error
(`ERR no such key`, iteration 2877) while MGET showed the losing source still
present. Its preceding transactional race passed. The earlier batteries had
left `atomic=1`, which the RENAMENX driver recorded explicitly. It is the
pre-existing defect AT4-WOUND-1: inherited, not introduced (completion section;
`docs/execindex/wound-window/DEFECT.md`).
Clean-server controls on both release arms each passed 16 repetitions of the
unmodified test: 131,072 transactional and 131,072 bare race iterations per
arm, with zero order violations. The full debug-sequence controls passed 33/33
rows twice on PRE (`yJ8ZhT`, `zCDUH1`) and twice on POST (`xO5Scb`, `7Wnh0A`).
`docs/execindex/nx-control/` retains the clean controls.

Three epoll feature cells failed only their servertail throwaway boots with
`bind: Address already in use` on port 46802. The socket inspection observed
TIME_WAIT client connections from 46802 to another lane's ports 47800/47801
(`docs/execindex/port-46802-collision.log`). No foreign process or system
network setting was changed. These failed attempts remain in the archive. The
three complete jobs were rerun within the allocated range and passed 104/104
rows (`nVKKub`, ports 46860-46869).

The atomic RYOW battery's existing speed comparison is excluded only in
selected diagnostic jobs through `GATE_PROOF_NO_RATES=1`, which passes its
existing `--no-rate-assertions` flag. Every correctness check still runs and
the driver explicitly prints SKIP for the rate claim. Full gate/receipt
behavior is unchanged. `flip_saturated`, `atomic_floor`, performance arms
and full iteration are NOT RUN under the lane's runtime restriction.

### Maintainer measurements required

NOT RUN in this lane: performance/load generators and full gate iteration.

- `calib/exec-merit.py`: `--conns 16`, `32`, `64`, `128`; all eight cells
  (1s/2s × atomic 0/1 × hot/uncontended), ABBA against PRE. Capture the unchanged
  `atomic_txn_*` deltas, including `atomic_txn_order_violations=0`.
- `calib/exec-depth-sweep.py` in BOTH `--mode 2s` and `--mode 1s`, cross-owner,
  same-owner/different-shard, and same-shard; 16x1, 16x4, 32x4, 64x4, 128x4,
  three blocks per cell. Binding cross-owner/same-owner criteria:
  median(64x4)/median(16x4) >= 0.90 and
  median(128x4)/median(16x4) >= 0.85.
- Exact-layout control: add ABBA POST-layout vs PAD-A to the same merit/depth
  cells; compare the direction of the matched-image difference separately
  from release PRE vs POST. PAD-A is type A, as defined above.
- Debug visit depth check: visits/completed EXEC at 128x4 <= 1.25 times 16x4;
  place_waits/EXEC flat within ±20%. Debug timing is not release throughput.
- Redis 7.4.10 context: merit-grade 3 blocks, 64 conns × pipe 4, four plain
  clients, io-threads 4 and io-threads-do-reads yes. Verify that the current
  driver actually supplies the Redis hot keys and plain clients (the design
  documented a defect in an older driver). Do not compare a private-key Redis
  cell with a hot-key TomoKV cell.
- Main-command null: the 14 generic cells plus 2s GET/SET at p1/p32. Use matched
  offered load, cycles/op, instructions/op and IPC; ex_loop.h changes require
  this null even when command bodies and serverless counts agree.

Single-shard write EXEC uses the same registry (`execute_watch_phase` calls
`watch_place_unit` even with one shard; only the arrival barrier is skipped).
From the owner's supplied single-shard probes, relative to 541k at 16x4,
64x4 is 0.776–0.815 and 128x4 is 0.782–0.786. These are supplied baseline
ratios, not measurements of this candidate. Same-shard POST ratios remain
NOT RUN pending the maintainer sweep.

Both modes share the indexed registry and intrusive owner lanes. In 1s the
same scan removal applies, while parsing/reply work remains in the fused
owner pass. The previous design's 2s constant-cost estimate does not establish
1s performance; report 1s depth ratios, visit counts, poll counts, and owner
profiles separately. No 1s throughput improvement is claimed here.

The supplied `exec-profile/SWEEP.txt` identifies its headline as `05a5e01a9`;
those probe rates are context, not measurements of the requested PRE commit
`3700b51d7`. Re-establish the latter with the supplied PRE artifact.

## Completion after the content-filter stop (2026-10-26)

The maintainer's continuation finished the lane on CPUs 96-111 and ports 46800-46899. Production
code is unchanged: `30f8cfa44` is still the last `src/`/Makefile change, and `build/tomokv` is
byte-identical to `build/execindex/POST`. Each gate invocation is a selected-job partial run of
`tests/gate.sh full --server-cores 96-103 --load-cores 104-111 --server-smt '' --load-smt ''`
with `GATE_ONLY_JOBS`, `GATE_PROOF_NET_IO`/`GATE_DIFFER_NET_IO` and `GATE_TXN_FUSED`, launched one
at a time with a fresh port window. `docs/execindex/proof-final/` keeps every invocation: its
plan, ledger, output and the text artifacts of each failing job. `summary.json` lists every run,
with its ports, timing and FAIL rows.

### AT4-WOUND-1: inherited, not introduced

`tests/txnorder_wound_window.cc` holds open the gap between the wound's phase CAS and its epoch
CAS. It fails identically in every cell (`docs/execindex/wound-window/results.json`):

| Diagnostic cell | PRE `3700b51d7` | POST `30f8cfa44` |
|---|---|---|
| multi namespace, 1s | FAIL | FAIL |
| multi namespace, 2s | FAIL | FAIL |
| db0 namespace, 1s | FAIL | FAIL |
| db0 namespace, 2s | FAIL | FAIL |

Every cell reports `read_done=1 pre_epoch=0 aborted=1 no_such_key=1 source_present=1
commit_accepted=1 final_epoch=1`. The first PRE-db0 attempt failed to link: the db0 objects need
the multi objects that carry the shared Lua code, as the Makefile's `txnorder-watch-db0-unit` rule
links them. That log is kept as `pre-db0-build-attempt1-link-failed.log`. The PRE multi binary
rebuilt bit-for-bit (`39bc12dc`).

**The fused/uring debug-0 failure is this window.** In `build/gate-run.G2pyOc`, the `txn_nx` bare
race at the inherited `atomic=1`, iteration 2877, A answered `ERR no such key` while its source
was still present, and B won. The diagnostic produces the same reply (`NoSuchKey`), the same data
shape (A's source present, the destination holding the winner's value) and an accepted commit.
The PRE code path, in short:

1. The older group B places on the destination shard and wounds the younger A. `txn_wound`
   (`multi.inc:3227`) CASes A's phase to `Wounded` (3230). Its epoch CAS (3233) has not run yet.
2. A's last placement, on the source owner, fails its `Executing` CAS (`txn_group.inc:183-184`).
   It sets `aborted` but leaves the epoch at 0 (185), and returns `Done` (234-235).
3. `scatter_engine.inc:2906-2908` skips the RENAMENX source read (3512-3530). `finish_phase1`
   answers `NoSuchKey` (`xshard_commands.inc:1285-1288`).
4. The epoch is not cancelled, so A is not retried (`txn_group.inc:427`) and is queued as
   `CommitQueued` (431).
5. `txn_group_decide` wins the CAS from 0 to A's ticket (`scatter_engine.inc:4102`,
   `txn_group.inc:254-256`). The aborted arm retries only a cancelled epoch (4122-4127), so A
   replies `ERR no such key` (`xshard_commands.inc:1858`).
6. B's epoch CAS then fails, B proceeds, and B wins.

The lane did not introduce or widen the window, for these reasons:

- `txn_group.inc`, `scatter_engine.inc`, `xshard_commands.inc`, `atomics_glue.inc`, `xshard.cc`
  and `server.h` are byte-identical between PRE and POST.
- The `txn_wound` body and the wound predicate are unchanged
  (`docs/execindex/wound-window/source-identity.json`).
- The only `ex_execute.inc` change touches the MULTI-unit retry hooks, not the scatter
  completion or the `CommitQueued` path.
- The window lies between two adjacent atomic instructions inside `txn_wound`, and the lane adds
  nothing between them.
- The observed rates cannot distinguish the arms: POST had 1 failure in 229,376 bare iterations
  and PRE 0 in 163,840 (all debug-job batteries plus the clean `nx-control` boots).
- **Live reproduction on both arms** (`docs/execindex/nx-preempt/`). The same race ran on
  release boots (fused, uring, `--atomic 1`), with spin/sleep injectors pinned to the server CPUs
  so that a wounder is likely descheduled between its CASes. Blocks ran in the order
  PRE/POST/POST/PRE. **PRE: 3 failures** in 974,848 iterations (89,417 group wounds,
  3.4e-5 per wound). **POST: 3 failures** in 1,089,536 (93,138 wounds, 3.2e-5 per wound). All six
  have the debug-0 shape, and `atomic_txn_order_violations` stayed 0. The rate per wound is the
  same on both arms, so the index neither created nor widened the window.

`docs/execindex/wound-window/DEFECT.md` is the note for the fix lane (woundfix). It covers the
interleaving with anchors, why D2's wound-wait guarantee breaks, the EXEC and allocation-failure
variants, the smallest fix and its directed checks. The diagnostic stays a documented failure on
PRE and POST, not a gate row.

### txnorder fused/atomic-0 writer bound (40 ms, unchanged)

Six repetitions ran through the job interface (`GATE_ONLY_JOBS=txnorder-fused-0`, uring, the
failing cell), one invocation at a time, with nothing else on CPUs 96-111:

| Run | Started | Port window | Max plain INCR latency (bound 40 ms) | Verdict |
|---|---|---|---:|---|
| rep1 | 11:46:53 | 46800-46809 | 6.392 ms | pass |
| rep2 | 11:47:44 | 46810-46819 | 6.394 ms | pass |
| rep3 | 11:48:36 | 46820-46829 | 6.388 ms | pass |
| rep4 | 11:49:27 | 46830-46839 | 6.370 ms | pass |
| rep5 | 11:50:19 | 46840-46849 | 6.399 ms | pass |
| rep6 | 11:51:11 | 46850-46859 | 6.375 ms | pass |

Earlier values of the same cell:

| Run | Engine | Value | Verdict | Note |
|---|---|---:|---|---|
| BWdImp | uring | 14.091 ms | pass | Before the production freeze |
| aiaiHU | uring | 49.894 ms | FAIL | Instruction-scope GDB traces were running on the same CPUs (09:53-09:54) |
| smLPMY | uring | 13.100 ms | pass | |
| iixwpY | epoll | 6.368 ms | pass | |
| ypUQ2p | epoll | 6.367 ms | pass | |
| me0Op9 | epoll | 8.889 ms | pass | |

On idle CPUs the cell sits at about 6.4 ms. The 49.894 ms sample came from CPU sharing, not from
the index.

### Port-range reruns, and why some FLIP rows cannot pass on an even slot port

The lane's ports, 46800-46899, lie inside the kernel's ephemeral range (32768-60999). The
mainline gate uses 7899-7998, below that range. On the headline it passed all nine FLIP-family
rows discussed here (`cx-final/build/gate-ledger-iteration.txt`): FLIP close on uring and epoll,
signal stop, both perfio rows and the four fliplisten rows. Two effects follow:

- **Foreign ephemeral ports.** Any client on the box may take one of our ports as its source
  port. Its TIME-WAIT, which carries no SO_REUSEADDR, then blocks our server's bind for 60 s even
  though the server sets SO_REUSEADDR and SO_REUSEPORT (`io_loop.h:179-180`).
- **TCP self-connect.** A client storm against a slot port that is not listening can connect a
  socket to itself.

Plain `connect()` draws even source ports first: the server saw 3,123 distinct even client ports
and 2 odd ones. So an odd slot port removes the self-connect, and from 12:16 on the launcher uses
odd 9-port windows. Excerpts of the 0.2 s socket samples are in `docs/execindex/port-selfconnect/`.

**The three epoll feature jobs.** These are `feature-split-0`, `feature-split-1` and
`feature-armed-0` from `zVmicf`, whose servertail throwaway boots hit a foreign TIME-WAIT on
46802. Rerun `feature-epoll-rerun`: **104/104 ok** (including the release row) on 46860-46869.
The three servertail rows are green.

**The FLIP rows.** The uring support run (`333qQ8`) failed five rows on slot port 46800: four
flip rows and fliplisten `io-ex complete`. Every rerun on an even slot port failed the same flip
rows, on both arms:

| Run | Binary | Slot port | ok | FAIL | Cause |
|---|---|---|---:|---:|---|
| `flip-uring-rerun` (ZBhFdi) | POST | 46870 (even) | 8 | 6 | Four flip rows (`FLIP close (epoll)`, `signal stop`, perfio `epoll-flip` and `epoll-lb`) and fliplisten `io-ex complete` and `ex-io complete`. After the churn connector (12,829 connects) the port reads `owned port already busy` / `bind: Address already in use` |
| `flip-fliplisten-PRE` (8nOuib) | **PRE** | 46810 (even) | 6 | 8 | The same four flip rows plus all four fliplisten rows. Samples show a client using 46812 (PORT+2) as its source port at 12:11:28, then **`TIME-WAIT 127.0.0.1:46810 -> 127.0.0.1:46810`** (a self-connect) from 12:11:29 to the end of the run |
| `flip-uring-oddport` (dydRrY) | POST | 46801 (odd) | **13** | 1 | All 10 flip-job rows pass. Zero self-connects. Remaining failure: fliplisten `io-ex complete` uring legs, `bind tls-port: Address already in use` on 46802 (PORT+1), held by `TIME-WAIT 127.0.0.1:46802 -> 127.0.0.1:46801` from 12:18:16 to 12:19:19 |
| `flip-fliplisten-PRE-oddport` (C4WVsf) | **PRE** | 46831 (odd) | 12 | 2 | The same TLS-port TIME-WAIT (`46832 -> 46831`) fails fliplisten `io-ex complete`. Separately, **PRE** failed perfio `epoll-lb` with `selected socket did not move` (not a port failure; POST passed this row in every odd-port run) |
| `support-epoll` (XE9k7H) | POST | 46811 (odd) | **52** | 0 | The flip job on epoll (fused), every row green |
| `fliplisten-rerun` (TJV9SZ) | POST | 46811 (odd) | **5** | 0 | fliplisten alone, not behind the flip job's connection storm. All four rows green |

On even slot ports PRE fails the same four flip rows as POST, plus two fliplisten rows that POST
passed in its even-port run. With an odd slot port, every flip-job row passes on POST on both
engines, and fliplisten passes 4/4 when run on its own. The one remaining fliplisten failure
comes from the TLS port (PORT+1, which is even when PORT is odd). It picks up a TIME-WAIT from the
flip job's own connection storm. That failure is environmental, and PRE shows it too.

### Runtime matrix on the final binary: every outcome

Coverage by the prompt's categories. Every job named here has a green final-code run in the table
below; the engine column is the proof engine, and many jobs also boot both engines internally.

| Category | Jobs |
|---|---|
| MULTI/EXEC | `debug-0/1` (multires, multirace, execatomic, execiso, execfix, txniso, txn_nx, session_monotonic, xacct, xmove), `fused-0/1`, `txn_group_split/fused`, `multidb-*` (8 cells) |
| txnorder | `txnorder-{fused,split}-{0,1}`: three complete final-code passes per engine (uring rows 1, 2 and 24; epoll rows 3-5), plus six fused/atomic-0 repetitions. `txnorder_index` (the new rows, every declared cell), `txnorder2` (R1-R12, WATCH, RENAME join), `txnorder_wake` |
| execfair | `execfair` (1s/2s × atomic 0/1 × uring/epoll inside the row) |
| WATCH | `datafix2_watch` (rows 36-37), `atomfix5_watch`, the txnorder2 WATCH rows, `multidb-*` |
| Blocking | `blockfix_structure`, `blockfix_registry`, `blockfix_mkstream` (uring row 14, epoll row 29) |
| Scripting | `script_bounds`, `scriptfix` (rows 14 and 29), `xscript` and `scriptatomic` (debug jobs) |
| Atomics | `atomic_units`, `atomfix5_accounting`, `atomic_batteries` and `release_batteries` (rows 32-35), atomfix (debug jobs) |
| FLIP | `flip` (green on odd slot ports on both engines, rows 27 and 29), `flipctl`, `flip_unit`, `flipfix_units`; `fliplisten` (row 40; see the port section) |
| Notification | `notify`, `notifycompat`, `notify_order`, `notify_aof`, `tracking_redirect`, `trackfix_accounting`, `trackfix_order` (rows 14 and 29) |
| Persistence | `aof-{epoll,uring}`, `snapshot-{epoll,uring}`, `aof_frame`, `aoforder` (rows 30-31), `persistfix_units`, `persistfix2_*` (row 14) |
| Differential | `tests/differ_gate.sh` through `differ-split` and `differ-armed`, standard seeds {7 19 20 23 21} (permanent 7/19 plus rotation), 235 legs per part. Split and armed-fused at atomic 0/1, plus mode equivalence, on uring (row 38) and epoll (row 39): 0 diffs |
| Also | `core_units`, `wait_units`, `auth`, `dump_restore`, `serverfix_waitaof`, `moverfix`, `sort`, `feature-split-*`, `feature-armed-*` |

`atomic_txn_order_violations` stayed 0 in every txnorder, execfair and debug battery that asserts
it.

| # | Run (artifacts) | Binary | Engine | `GATE_TXN_FUSED` | Jobs | ok | FAIL | Outcome |
|---:|---|---|---|---|---|---:|---:|---|
| 1 | txnorder-uring-2 (`aiaiHU`) | POST | uring | 0 | 4 jobs: txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 | 4 | 1 | FAIL `txnorder battery (fused, atomic 0)`: writer bound at 49.894 ms while GDB instruction traces shared the CPUs. Data exact, order violations 0. Six idle reruns pass (rows 16-21) |
| 2 | txnorder-uring-3 (`smLPMY`) | POST | uring | 0 | 4 jobs: txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 | 5 | 0 | all green |
| 3 | txnorder-epoll-1 (`iixwpY`) | POST | epoll | 0 | 4 jobs: txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 | 5 | 0 | all green |
| 4 | txnorder-epoll-2 (`ypUQ2p`) | POST | epoll | 0 | 4 jobs: txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 | 5 | 0 | all green |
| 5 | txnorder-epoll-3 (`me0Op9`) | POST | epoll | 0 | 4 jobs: txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 | 5 | 0 | all green |
| 6 | debug-split-uring (`1KNQE5`) | POST | uring | 0 | 10 jobs: debug-0 debug-1 txn_group_split txn_group_fused fused-0 fused-1 feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 | 191 | 0 | all green |
| 7 | debug-fused-uring (`G2pyOc`) | POST | uring | 1 | 2 jobs: debug-0 debug-1 | 32 | 1 | FAIL `txn_nx battery (atomic 0)`, bare race iteration 2877: **AT4-WOUND-1** (inherited; `docs/execindex/wound-window/`) |
| 8 | debug-split-epoll (`zVmicf`) | POST | epoll | 0 | 10 jobs: debug-0 debug-1 txn_group_split txn_group_fused fused-0 fused-1 feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 | 188 | 3 | FAIL 3 servertail rows: throwaway boot `bind: Address already in use` on 46802 (foreign TIME-WAIT). Rerun green (row 22) |
| 9 | debug-fused-epoll (`Xcknov`) | POST | epoll | 1 | 2 jobs: debug-0 debug-1 | 33 | 0 | all green |
| 10 | debug-prefix-pre-1 (`yJ8ZhT`) | PRE | uring | 1 | 2 jobs: debug-0 debug-1 | 33 | 0 | PRE control, all green |
| 11 | debug-prefix-pre-2 (`zCDUH1`) | PRE | uring | 1 | 2 jobs: debug-0 debug-1 | 33 | 0 | PRE control, all green |
| 12 | debug-prefix-post-1 (`xO5Scb`) | POST | uring | 1 | 2 jobs: debug-0 debug-1 | 33 | 0 | all green |
| 13 | debug-prefix-post-2 (`7Wnh0A`) | POST | uring | 1 | 2 jobs: debug-0 debug-1 | 33 | 0 | all green |
| 14 | support (`333qQ8`) | POST | uring | 0 | 27 jobs: atomfix5_watch atomfix5_accounting atomic_units moverfix blockfix_structure blockfix_registry blockfix_mkstream script_bounds scriptfix sort notify notifycompat tracking_redirect notify_order notify_aof trackfix_accounting trackfix_order flip fliplisten flipctl flip_unit flipfix_units persistfix_units persistfix2_lastsave persistfix2_shutdown persistfix2_commands persistfix2_errors | 88 | 5 | FAIL 5: four flip rows (close-epoll, signal stop, perfio epoll-flip/epoll-lb) and fliplisten `io-ex complete`, on even slot port 46800: `bind`/`owned port already busy`/self-connect PING (environmental; rows 23, 26-28) |
| 15 | support-epoll (first) (`AIgci9`) | POST | epoll | 1 | 16 jobs: moverfix blockfix_structure blockfix_registry blockfix_mkstream script_bounds scriptfix sort notify notifycompat tracking_redirect notify_order notify_aof trackfix_accounting trackfix_order flip flipctl | 0 | 0 | Incomplete: stopped at the content-filter stop, no rows. Completed as row 29 |
| 16 | txnorder-fused0-rep1 (`o5GK1l`) | POST | uring | 0 | 1 jobs: txnorder-fused-0 | 2 | 0 | all green |
| 17 | txnorder-fused0-rep2 (`GQgPrB`) | POST | uring | 0 | 1 jobs: txnorder-fused-0 | 2 | 0 | all green |
| 18 | txnorder-fused0-rep3 (`8MW0w8`) | POST | uring | 0 | 1 jobs: txnorder-fused-0 | 2 | 0 | all green |
| 19 | txnorder-fused0-rep4 (`sZiaqo`) | POST | uring | 0 | 1 jobs: txnorder-fused-0 | 2 | 0 | all green |
| 20 | txnorder-fused0-rep5 (`FTMdut`) | POST | uring | 0 | 1 jobs: txnorder-fused-0 | 2 | 0 | all green |
| 21 | txnorder-fused0-rep6 (`Eef62V`) | POST | uring | 0 | 1 jobs: txnorder-fused-0 | 2 | 0 | all green |
| 22 | feature-epoll-rerun (`nVKKub`) | POST | epoll | 0 | 3 jobs: feature-split-0 feature-split-1 feature-armed-0 | 104 | 0 | all green |
| 23 | flip-uring-rerun (`ZBhFdi`) | POST | uring | 0 | 2 jobs: flip fliplisten | 8 | 6 | FAIL 6 on even slot port 46870: the same four flip rows and fliplisten `io-ex`/`ex-io complete` (environmental self-connect/TIME-WAIT) |
| 24 | txnorder-uring-final (`Aad5q1`) | POST | uring | 0 | 4 jobs: txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 | 5 | 0 | all green |
| 25 | index-execfair-final (`kZ32F3`) | POST | uring | 0 | 6 jobs: txnorder_index execfair txnorder2 txnorder_wake core_units wait_units | 32 | 0 | all green |
| 26 | flip-fliplisten-PRE (`8nOuib`) | PRE | uring | 0 | 2 jobs: flip fliplisten | 6 | 8 | **PRE**, even slot port 46810: FAIL 8, the same four flip rows and all four fliplisten rows. Self-connect `46810 -> 46810` sampled |
| 27 | flip-uring-oddport (`dydRrY`) | POST | uring | 0 | 2 jobs: flip fliplisten | 13 | 1 | Odd slot port: all 10 flip rows green. FAIL fliplisten `io-ex complete`: TLS bind on 46802 (PORT+1), blocked by `TIME-WAIT 46802 -> 46801` |
| 28 | flip-fliplisten-PRE-oddport (`C4WVsf`) | PRE | uring | 0 | 2 jobs: flip fliplisten | 12 | 2 | **PRE**, odd slot port: FAIL fliplisten `io-ex complete` (TLS TIME-WAIT 46832) and PRE perfio `epoll-lb` (`selected socket did not move`) |
| 29 | support-epoll (`XE9k7H`) | POST | epoll | 1 | 16 jobs: moverfix blockfix_structure blockfix_registry blockfix_mkstream script_bounds scriptfix sort notify notifycompat tracking_redirect notify_order notify_aof trackfix_accounting trackfix_order flip flipctl | 52 | 0 | all green |
| 30 | persistence-0 (`wSTzLa`) | POST | uring | 0 | 6 jobs: aof-epoll aof-uring snapshot-epoll snapshot-uring aof_frame aoforder | 146 | 0 | all green |
| 31 | persistence-1 (`lbdtZ0`) | POST | uring | 1 | 6 jobs: aof-epoll aof-uring snapshot-epoll snapshot-uring aof_frame aoforder | 146 | 0 | all green |
| 32 | atomic-release-uring-0 (`sR3otX`) | POST | uring | 0 | 5 jobs: release_batteries atomic_batteries auth dump_restore serverfix_waitaof | 24 | 0 | all green |
| 33 | atomic-release-uring-1 (`ZlDGRn`) | POST | uring | 1 | 5 jobs: release_batteries atomic_batteries auth dump_restore serverfix_waitaof | 24 | 0 | all green |
| 34 | atomic-release-epoll-0 (`DPofok`) | POST | epoll | 0 | 5 jobs: release_batteries atomic_batteries auth dump_restore serverfix_waitaof | 24 | 0 | all green |
| 35 | atomic-release-epoll-1 (`uOJIVa`) | POST | epoll | 1 | 5 jobs: release_batteries atomic_batteries auth dump_restore serverfix_waitaof | 24 | 0 | all green |
| 36 | watch-multidb-uring (`cyTIGa`) | POST | uring | 0 | 9 jobs: datafix2_watch multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1 multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1 | 26 | 0 | all green |
| 37 | watch-multidb-epoll (`zYoZoH`) | POST | epoll | 0 | 9 jobs: datafix2_watch multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1 multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1 | 26 | 0 | all green |
| 38 | differ-uring (`GKTASz`) | POST | uring | 0 | 2 jobs: differ-split differ-armed | 6 | 0 | all green |
| 39 | differ-epoll (`OHDgNw`) | POST | epoll | 0 | 2 jobs: differ-split differ-armed | 6 | 0 | all green |
| 40 | fliplisten-rerun (`TJV9SZ`) | POST | uring | 0 | 1 jobs: fliplisten | 5 | 0 | all green |

Totals over all 40 attempts: **1,389 ok rows and 27 FAIL rows**. Each run's release-build row
counts as ok. Every FAIL is accounted for:

| FAIL rows | Arm | Cause |
|---:|---|---|
| 1 | POST | **AT4-WOUND-1** (row 7) |
| 1 | POST | Writer bound at 49.894 ms while GDB traces shared the CPUs (row 1); six idle reruns pass |
| 15 | POST | Port range inside the ephemeral range: three foreign TIME-WAITs on servertail boots (row 8), and FLIP rows on even slot ports or on the even TLS port (rows 14, 23, 27). Every one has a green rerun (rows 22, 27, 29, 40) |
| 9 | PRE | The same port-range causes (rows 26, 28) |
| 1 | PRE | perfio `epoll-lb`: `selected socket did not move` (row 28). Green on POST in rows 27 and 29 |

No FAIL was caused by the index change.

Before the freeze, `BWdImp` (25/25, 09:02-09:19) and `NzvzPo` (3/3, 09:28-09:41) ran a binary
linked before `30f8cfa44`: `build/tomokv` was relinked at 09:42:47. They count only as earlier
evidence. Their jobs were rerun on the final binary (rows 1-5, 24 and 25). The clean `nx-control`
boots (16 repetitions per arm, `docs/execindex/nx-control/`) are live controls run outside the
gate's job interface, not gate rows.

### Build, unit and freshness checks (`docs/execindex/freshness-final.json`)

- `python3 tests/gates_test.py`: **72 tests OK** (`docs/execindex/gates-test-final.log`).
- Each of these returned rc 0 and rebuilt nothing ("Nothing to be done" / "up to date"):
  `make all`, every `job_production_units` target (`make -k` over the gate's 45 unit binaries),
  `mdbqsbr-live-arms`, and `tools/blockfix_cost.mk build/blockfix-cost`.
- **49 `make -q` freshness checks: 0 failures.** They cover `all`, the 45 units, both mdbqsbr
  arms, and the blockfix cost binary with its bound release digest.
- `build/execindex/POST` SHA-256 is still
  `aee048859f6f8d84d5aa4e0b30767ad1e8dac4595d383ff634a8226027d1566a`, identical before and after
  the checks. `build/tomokv` is byte-identical to it. Nothing was rebuilt; the last source or
  Makefile change remains `30f8cfa44`.

### Still NOT RUN in this lane (maintainer-owned)

Performance and load generators (exec-merit, the depth sweeps, benchtxn, memtier, the generic and
GET/SET null cells), `flip_saturated`, `atomic_floor`, and the full `tests/gate.sh` iteration.
The live AT4-WOUND-1 check used CPU injectors only to widen a race; it measured no rate.
